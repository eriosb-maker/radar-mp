"""
Cliente asíncrono para la API pública de Mercado Público / ChileCompra.
Docs: https://www.chilecompra.cl/api/
"""
import logging
from datetime import date, datetime

import aiohttp

from config import CHILECOMPRA_TICKET

log = logging.getLogger(__name__)

BASE_URL   = "https://api.mercadopublico.cl/servicios/v1/publico"
TIMEOUT    = aiohttp.ClientTimeout(total=120)


def _fecha(d: date) -> str:
    """Convierte date a formato ddmmaaaa que espera la API."""
    return d.strftime("%d%m%Y")


def _parse_fecha(s: str | None) -> datetime | None:
    if not s:
        return None
    for fmt in ("%d/%m/%Y %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt)
        except (ValueError, TypeError):
            continue
    return None


ESTADO_CODIGOS = {
    5:  "activa",
    6:  "cerrada",
    7:  "desierta",
    8:  "adjudicada",
    9:  "revocada",
    18: "suspendida",
}


def _normalizar_licitacion(raw: dict) -> dict:
    """
    Aplana y normaliza un objeto licitación del JSON de la API.
    El endpoint /licitaciones?estado=activas devuelve campos mínimos:
    CodigoExterno, Nombre, CodigoEstado, FechaCierre.
    El detalle completo (organismo, región, monto) se obtiene con /licitaciones?codigo=XXX.
    """
    regiones = raw.get("Regiones") or []
    region_str = regiones[0].get("RegionNombre", "") if regiones else ""

    codigo_estado = raw.get("CodigoEstado")
    estado_str = ESTADO_CODIGOS.get(codigo_estado, raw.get("Estado", "")) or "activa"

    return {
        "id":               raw.get("CodigoExterno", ""),
        "nombre":           raw.get("Nombre", ""),
        "descripcion":      raw.get("Descripcion", ""),
        "organismo":        raw.get("NombreOrganismo", ""),
        "codigo_organismo": str(raw.get("CodigoOrganismo", "")),
        "region":           region_str,
        "monto_estimado":   _parse_monto(raw.get("MontoEstimado")),
        "fecha_cierre":     _parse_fecha(raw.get("FechaCierre")),
        "fecha_publicacion":_parse_fecha(raw.get("FechaCreacion") or raw.get("FechaPublicacion")),
        "estado":           estado_str,
        "tipo":             raw.get("Tipo", ""),
        "raw":              raw,
    }


def _parse_monto(valor) -> float | None:
    if valor is None:
        return None
    try:
        return float(str(valor).replace(".", "").replace(",", "."))
    except (ValueError, TypeError):
        return None


class ChileCompraClient:
    def __init__(self, ticket: str = CHILECOMPRA_TICKET):
        self.ticket = ticket

    def _params(self, extra: dict) -> dict:
        return {"ticket": self.ticket, **extra}

    async def _get(self, session: aiohttp.ClientSession, path: str, params: dict) -> dict:
        url = f"{BASE_URL}/{path}.json"
        async with session.get(url, params=params, timeout=TIMEOUT) as resp:
            resp.raise_for_status()
            return await resp.json(content_type=None)

    # ------------------------------------------------------------------ #
    # Licitaciones
    # ------------------------------------------------------------------ #

    async def licitaciones_activas(self) -> list[dict]:
        """Todas las licitaciones actualmente publicadas/activas."""
        async with aiohttp.ClientSession() as s:
            data = await self._get(s, "licitaciones", self._params({"estado": "activas"}))
        return [_normalizar_licitacion(l) for l in (data.get("Listado") or [])]

    async def licitaciones_por_fecha(self, fecha: date, estado: str = "") -> list[dict]:
        params = {"fecha": _fecha(fecha)}
        if estado:
            params["estado"] = estado
        async with aiohttp.ClientSession() as s:
            data = await self._get(s, "licitaciones", self._params(params))
        return [_normalizar_licitacion(l) for l in (data.get("Listado") or [])]

    async def licitacion_detalle(self, codigo: str) -> dict | None:
        async with aiohttp.ClientSession() as s:
            data = await self._get(s, "licitaciones", self._params({"codigo": codigo}))
        listado = data.get("Listado") or []
        return _normalizar_licitacion(listado[0]) if listado else None

    async def licitaciones_por_organismo(self, codigo_organismo: str) -> list[dict]:
        async with aiohttp.ClientSession() as s:
            data = await self._get(
                s, "licitaciones",
                self._params({"CodigoOrganismo": codigo_organismo, "estado": "activas"})
            )
        return [_normalizar_licitacion(l) for l in (data.get("Listado") or [])]

    # ------------------------------------------------------------------ #
    # Órdenes de compra
    # ------------------------------------------------------------------ #

    async def ordenes_proveedor(self, codigo_proveedor: str) -> list[dict]:
        async with aiohttp.ClientSession() as s:
            data = await self._get(
                s, "ordenesdecompra",
                self._params({"CodigoProveedor": codigo_proveedor})
            )
        return data.get("Listado") or []

    # ------------------------------------------------------------------ #
    # Empresas
    # ------------------------------------------------------------------ #

    async def buscar_proveedor_rut(self, rut: str) -> dict | None:
        """Devuelve código interno del proveedor a partir de RUT."""
        async with aiohttp.ClientSession() as s:
            url = f"{BASE_URL}/Empresas/BuscarProveedor"
            params = self._params({"rutempresaproveedor": rut})
            async with s.get(url, params=params, timeout=TIMEOUT) as resp:
                resp.raise_for_status()
                return await resp.json(content_type=None)

    async def listar_organismos(self) -> list[dict]:
        async with aiohttp.ClientSession() as s:
            url = f"{BASE_URL}/Empresas/BuscarComprador"
            async with s.get(url, params={"ticket": self.ticket}, timeout=TIMEOUT) as resp:
                resp.raise_for_status()
                data = await resp.json(content_type=None)
        return data.get("listaOrganismos") or []


# Instancia global
client = ChileCompraClient()
