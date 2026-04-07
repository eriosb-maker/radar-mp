"""
Motor de Due Diligence de Contratistas — Mercado Público.

Dado el RUT de un proveedor:
  1. Resuelve RUT → CodigoProveedor interno
  2. Descarga historial: órdenes de compra + licitaciones adjudicadas
  3. Calcula métricas financieras y de riesgo
  4. Detecta red flags
  5. Genera análisis narrativo con Claude Opus
"""
import logging
from datetime import datetime

import anthropic

from chilecompra import ChileCompraClient, _parse_fecha, _parse_monto
from config import ANTHROPIC_API_KEY, CHILECOMPRA_TICKET

log = logging.getLogger(__name__)

claude  = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None
mp      = ChileCompraClient(ticket=CHILECOMPRA_TICKET)


# ------------------------------------------------------------------ #
# 1. Resolución RUT → datos del proveedor
# ------------------------------------------------------------------ #

async def resolver_proveedor(rut: str) -> dict:
    """
    Busca el proveedor por RUT y devuelve sus datos básicos incluyendo
    el CodigoProveedor interno de Mercado Público.
    """
    data = await mp.buscar_proveedor_rut(rut)
    if not data:
        raise ValueError(f"No se encontró proveedor con RUT {rut}")

    # La API puede devolver distintas estructuras:
    # - listaEmpresas[].CodigoEmpresa / NombreEmpresa  (más común)
    # - listaProveedores[].CodigoProveedor / NombreProveedor
    # - Listado[].CodigoProveedor
    proveedor = None
    if isinstance(data, list) and data:
        proveedor = data[0]
    elif isinstance(data, dict):
        listado = (data.get("listaEmpresas")
                   or data.get("listaProveedores")
                   or data.get("Listado")
                   or [])
        if listado:
            proveedor = listado[0]
        elif data.get("CodigoEmpresa") or data.get("CodigoProveedor"):
            proveedor = data

    if not proveedor:
        raise ValueError(f"RUT {rut} no encontrado en Mercado Público")

    codigo = (proveedor.get("CodigoEmpresa")
              or proveedor.get("CodigoProveedor")
              or proveedor.get("codigo")
              or "")
    nombre = (proveedor.get("NombreEmpresa")
              or proveedor.get("NombreProveedor")
              or proveedor.get("nombre")
              or "")

    return {
        "rut":    rut,
        "nombre": nombre,
        "codigo": str(codigo),
        "raw":    proveedor,
    }


# ------------------------------------------------------------------ #
# 2. Descarga del historial
# ------------------------------------------------------------------ #

async def obtener_historial(codigo_proveedor: str) -> dict:
    """Descarga órdenes de compra y licitaciones adjudicadas del proveedor."""
    import asyncio

    ordenes_task     = mp.ordenes_proveedor(codigo_proveedor)
    licitaciones_task = _licitaciones_adjudicadas(codigo_proveedor)

    ordenes, licitaciones = await asyncio.gather(
        ordenes_task, licitaciones_task,
        return_exceptions=True
    )

    if isinstance(ordenes, Exception):
        log.warning("Error descargando órdenes: %s", ordenes)
        ordenes = []
    if isinstance(licitaciones, Exception):
        log.warning("Error descargando licitaciones: %s", licitaciones)
        licitaciones = []

    return {"ordenes": ordenes, "licitaciones": licitaciones}


async def _licitaciones_adjudicadas(codigo_proveedor: str) -> list[dict]:
    import aiohttp
    from chilecompra import BASE_URL, TIMEOUT
    url = f"{BASE_URL}/licitaciones.json"
    params = {
        "ticket":          CHILECOMPRA_TICKET,
        "estado":          "adjudicada",
        "CodigoProveedor": codigo_proveedor,
    }
    async with aiohttp.ClientSession() as s:
        async with s.get(url, params=params, timeout=TIMEOUT) as resp:
            resp.raise_for_status()
            data = await resp.json(content_type=None)
    return data.get("Listado") or []


# ------------------------------------------------------------------ #
# 3. Métricas
# ------------------------------------------------------------------ #

def calcular_metricas(historial: dict) -> dict:
    ordenes     = historial.get("ordenes", [])
    licitaciones = historial.get("licitaciones", [])

    contratos = []

    for oc in ordenes:
        monto = _parse_monto(oc.get("Monto") or oc.get("MontoTotal"))
        fecha = _parse_fecha(oc.get("FechaCreacion") or oc.get("Fecha"))
        contratos.append({
            "tipo":      "orden_compra",
            "id":        oc.get("CodigoExterno", ""),
            "nombre":    oc.get("Nombre", ""),
            "organismo": oc.get("NombreOrganismo", "") or oc.get("Comprador", ""),
            "monto":     monto,
            "fecha":     fecha,
            "estado":    oc.get("Estado", ""),
        })

    for lic in licitaciones:
        monto = _parse_monto(lic.get("MontoEstimado") or lic.get("Monto"))
        fecha = _parse_fecha(lic.get("FechaCierre") or lic.get("FechaAdjudicacion"))
        contratos.append({
            "tipo":      "licitacion",
            "id":        lic.get("CodigoExterno", ""),
            "nombre":    lic.get("Nombre", ""),
            "organismo": lic.get("NombreOrganismo", ""),
            "monto":     monto,
            "fecha":     fecha,
            "estado":    "adjudicada",
        })

    con_monto = [c for c in contratos if c["monto"] is not None and c["monto"] > 0]
    total     = sum(c["monto"] for c in con_monto)

    # Agrupación por organismo
    por_org: dict[str, dict] = {}
    for c in con_monto:
        org = c["organismo"].strip() or "Sin información"
        if org not in por_org:
            por_org[org] = {"monto": 0.0, "contratos": 0}
        por_org[org]["monto"]     += c["monto"]
        por_org[org]["contratos"] += 1

    # HHI (Herfindahl-Hirschman Index) — mide concentración
    hhi = 0.0
    org_principal = {"nombre": "", "monto": 0, "porcentaje": 0}
    if total > 0 and por_org:
        shares     = {k: v["monto"] / total for k, v in por_org.items()}
        hhi        = sum(s ** 2 for s in shares.values())
        top_org    = max(por_org, key=lambda k: por_org[k]["monto"])
        org_principal = {
            "nombre":     top_org,
            "monto":      por_org[top_org]["monto"],
            "porcentaje": round(shares[top_org] * 100, 1),
        }

    top_organismos = sorted(
        [{"nombre": k, **v, "porcentaje": round(v["monto"] / total * 100, 1) if total > 0 else 0}
         for k, v in por_org.items()],
        key=lambda x: x["monto"], reverse=True
    )[:8]

    # Agrupación por año
    por_anio: dict[int, dict] = {}
    for c in contratos:
        if c["fecha"]:
            anio = c["fecha"].year
            if anio not in por_anio:
                por_anio[anio] = {"monto": 0.0, "contratos": 0}
            por_anio[anio]["contratos"] += 1
            if c["monto"]:
                por_anio[anio]["monto"] += c["monto"]

    # Variación interanual
    anios_sorted = sorted(por_anio.keys())
    variacion_yoy = {}
    for i in range(1, len(anios_sorted)):
        a0, a1 = anios_sorted[i - 1], anios_sorted[i]
        m0 = por_anio[a0]["monto"]
        m1 = por_anio[a1]["monto"]
        variacion_yoy[a1] = round((m1 - m0) / m0 * 100, 1) if m0 > 0 else None

    fechas = [c["fecha"] for c in contratos if c["fecha"]]

    return {
        "total_contratos":   len(contratos),
        "total_con_monto":   len(con_monto),
        "total_adjudicado":  round(total),
        "monto_promedio":    round(total / len(con_monto)) if con_monto else 0,
        "monto_maximo":      round(max(c["monto"] for c in con_monto)) if con_monto else 0,
        "monto_minimo":      round(min(c["monto"] for c in con_monto)) if con_monto else 0,
        "organismos_unicos": len(por_org),
        "top_organismos":    top_organismos,
        "org_principal":     org_principal,
        "hhi":               round(hhi, 4),
        "por_anio":          {str(k): v for k, v in sorted(por_anio.items())},
        "variacion_yoy":     {str(k): v for k, v in variacion_yoy.items()},
        "primer_contrato":   min(fechas).isoformat() if fechas else None,
        "ultimo_contrato":   max(fechas).isoformat() if fechas else None,
        "contratos_detalle": contratos[:50],   # primeros 50 para UI
    }


# ------------------------------------------------------------------ #
# 4. Red Flags
# ------------------------------------------------------------------ #

RED_FLAG_DEFS = {
    "concentracion_extrema": {
        "titulo":  "Concentración extrema en un organismo",
        "nivel":   "ALTO",
        "detalle": "Más del 80% de los ingresos provienen de un único organismo comprador. "
                   "Indica posible dependencia estructural o captura del organismo.",
    },
    "concentracion_alta": {
        "titulo":  "Alta concentración de clientes",
        "nivel":   "MEDIO",
        "detalle": "Entre 60% y 80% del total adjudicado proviene de un solo organismo. "
                   "Riesgo de colusión o favoritismo.",
    },
    "crecimiento_explosivo": {
        "titulo":  "Crecimiento explosivo inexplicable",
        "nivel":   "ALTO",
        "detalle": "El monto adjudicado creció más de 300% en un año. "
                   "Puede indicar captura del Estado o irregularidades en el proceso de contratación.",
    },
    "empresa_nueva_contratos_grandes": {
        "titulo":  "Empresa nueva con contratos de gran monto",
        "nivel":   "ALTO",
        "detalle": "La empresa tiene menos de 2 años de historial en Mercado Público "
                   "pero adjudica contratos de alto valor.",
    },
    "hhi_monopolio": {
        "titulo":  "Estructura de monopolio de proveedor (HHI > 0.75)",
        "nivel":   "MEDIO",
        "detalle": "El índice de concentración HHI supera 0.75, indicando que un solo "
                   "organismo domina abrumadoramente la demanda hacia este proveedor.",
    },
    "contrato_atipico": {
        "titulo":  "Contrato atípico de muy alto valor",
        "nivel":   "MEDIO",
        "detalle": "Existe al menos un contrato cuyo monto supera 5 veces el promedio "
                   "del proveedor. Podría ser trato directo no justificado.",
    },
}


def detectar_red_flags(metricas: dict) -> list[dict]:
    flags = []
    pct_principal = metricas["org_principal"].get("porcentaje", 0)

    if pct_principal >= 80:
        flags.append({**RED_FLAG_DEFS["concentracion_extrema"],
                      "valor": f"{pct_principal}% — {metricas['org_principal']['nombre']}"})
    elif pct_principal >= 60:
        flags.append({**RED_FLAG_DEFS["concentracion_alta"],
                      "valor": f"{pct_principal}% — {metricas['org_principal']['nombre']}"})

    for anio_str, var in metricas["variacion_yoy"].items():
        if var is not None and var > 300:
            flags.append({**RED_FLAG_DEFS["crecimiento_explosivo"],
                          "valor": f"+{var}% en {anio_str}"})

    if metricas["hhi"] > 0.75:
        flags.append({**RED_FLAG_DEFS["hhi_monopolio"],
                      "valor": f"HHI = {metricas['hhi']}"})

    if metricas["monto_promedio"] > 0 and metricas["monto_maximo"] > metricas["monto_promedio"] * 5:
        flags.append({**RED_FLAG_DEFS["contrato_atipico"],
                      "valor": f"Máx ${metricas['monto_maximo']:,} vs promedio ${metricas['monto_promedio']:,}"})

    if metricas["primer_contrato"]:
        primer = datetime.fromisoformat(metricas["primer_contrato"])
        anios_activo = (datetime.now() - primer).days / 365
        if anios_activo < 2 and metricas["total_adjudicado"] > 50_000_000:
            flags.append({**RED_FLAG_DEFS["empresa_nueva_contratos_grandes"],
                          "valor": f"{anios_activo:.1f} años activo, ${metricas['total_adjudicado']:,} adjudicado"})

    return flags


# ------------------------------------------------------------------ #
# 5. Análisis Claude
# ------------------------------------------------------------------ #

async def analisis_ia(proveedor: dict, metricas: dict, red_flags: list) -> str:
    if not claude:
        return "Análisis IA no disponible (configura ANTHROPIC_API_KEY en .env)."

    flags_txt = "\n".join(
        f"  [{f['nivel']}] {f['titulo']}: {f['valor']}" for f in red_flags
    ) or "  No se detectaron alertas significativas."

    top_orgs_txt = "\n".join(
        f"  {i+1}. {o['nombre']}: ${o['monto']:,.0f} ({o['porcentaje']}%)"
        for i, o in enumerate(metricas["top_organismos"])
    )

    por_anio_txt = "\n".join(
        f"  {anio}: ${v['monto']:,.0f} en {v['contratos']} contratos"
        for anio, v in metricas["por_anio"].items()
    )

    prompt = f"""Eres un abogado senior especialista en contratación pública chilena y auditoría de integridad.

Analiza el siguiente perfil de contratista en Mercado Público y redacta un informe ejecutivo de due diligence.

=== PROVEEDOR ===
Nombre: {proveedor['nombre']}
RUT: {proveedor['rut']}
Código MP: {proveedor['codigo']}
Historial: {metricas['primer_contrato'] or 'Desconocido'} → {metricas['ultimo_contrato'] or 'Desconocido'}

=== RESUMEN FINANCIERO ===
Total adjudicado histórico: ${metricas['total_adjudicado']:,} CLP
Número de contratos: {metricas['total_contratos']} ({metricas['total_con_monto']} con monto informado)
Monto promedio: ${metricas['monto_promedio']:,} CLP
Monto máximo: ${metricas['monto_maximo']:,} CLP
Organismos compradores únicos: {metricas['organismos_unicos']}
HHI de concentración: {metricas['hhi']} (0=diversificado, 1=monopolio)

=== TOP ORGANISMOS COMPRADORES ===
{top_orgs_txt}

=== EVOLUCIÓN ANUAL ===
{por_anio_txt}

=== ALERTAS DETECTADAS ===
{flags_txt}

Redacta en español, con nivel ejecutivo (para directorio o gerencia legal), estructurado en:

1. **PERFIL DEL CONTRATISTA** (2-3 párrafos sobre quién es y su posición en el mercado público)
2. **ANÁLISIS FINANCIERO** (interpretación de los números, tendencias, solidez)
3. **ANÁLISIS DE RIESGO** (evaluación de cada alerta detectada, contexto legal aplicable)
4. **CONCLUSIÓN Y RECOMENDACIÓN** (¿es apto para contratar? ¿qué diligencias adicionales se requieren?)

Marco legal aplicable: Ley 19.886 de Bases de Licitaciones, DL 211 (libre competencia), Ley 20.393 (responsabilidad penal empresas).
"""

    resp = claude.messages.create(
        model  = "claude-opus-4-6",
        max_tokens = 2000,
        messages   = [{"role": "user", "content": prompt}],
    )
    return resp.content[0].text


# ------------------------------------------------------------------ #
# 6. Pipeline completo
# ------------------------------------------------------------------ #

async def due_diligence_completo(rut: str) -> dict:
    """
    Ejecuta el pipeline completo y devuelve el informe estructurado.
    """
    log.info("Iniciando DD para RUT %s", rut)

    proveedor   = await resolver_proveedor(rut)
    log.info("Proveedor: %s (código %s)", proveedor["nombre"], proveedor["codigo"])

    historial   = await obtener_historial(proveedor["codigo"])
    log.info("Contratos obtenidos: %d OC + %d licitaciones",
             len(historial["ordenes"]), len(historial["licitaciones"]))

    metricas    = calcular_metricas(historial)
    red_flags   = detectar_red_flags(metricas)
    analisis    = await analisis_ia(proveedor, metricas, red_flags)

    return {
        "proveedor":  proveedor,
        "metricas":   metricas,
        "red_flags":  red_flags,
        "analisis_ia": analisis,
        "generado_en": datetime.now().isoformat(),
    }
