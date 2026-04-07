"""
Pipeline de ingesta: llama a la API de Mercado Público,
guarda licitaciones en DB y calcula matches con proveedores.
"""
import asyncio
import json
import logging
from datetime import datetime

from sqlalchemy.orm import Session

from chilecompra import client
from config import SCORE_MINIMO
from database import Licitacion, Oportunidad, Proveedor, SessionLocal
from matcher import calcular_score, embeder_licitaciones

log = logging.getLogger(__name__)


# ------------------------------------------------------------------ #
# Ingesta de licitaciones
# ------------------------------------------------------------------ #

async def ingestar_activas() -> int:
    """Descarga licitaciones activas y las persiste. Devuelve cantidad nueva."""
    log.info("Iniciando ingesta de licitaciones activas...")
    try:
        licitaciones_raw = await client.licitaciones_activas()
    except Exception as e:
        log.error("Error llamando a API ChileCompra: %s", e)
        return 0

    db: Session = SessionLocal()
    nuevas = 0
    try:
        for raw in licitaciones_raw:
            codigo = raw["id"]
            if not codigo:
                continue

            existente = db.get(Licitacion, codigo)
            if existente:
                # Actualizar estado si cambió
                if existente.estado != raw["estado"]:
                    existente.estado = raw["estado"]
                    db.add(existente)
                continue

            lic = Licitacion(
                id               = codigo,
                nombre           = raw["nombre"],
                descripcion      = raw["descripcion"],
                organismo        = raw["organismo"],
                codigo_organismo = raw["codigo_organismo"],
                region           = raw["region"],
                monto_estimado   = raw["monto_estimado"],
                fecha_cierre     = raw["fecha_cierre"],
                fecha_publicacion= raw["fecha_publicacion"],
                estado           = raw["estado"],
                tipo             = raw["tipo"],
                raw_json         = json.dumps(raw["raw"], ensure_ascii=False),
            )
            db.add(lic)
            nuevas += 1

        db.commit()
        log.info("Licitaciones nuevas ingresadas: %d", nuevas)
    except Exception as e:
        db.rollback()
        log.error("Error guardando licitaciones: %s", e)
    finally:
        db.close()

    return nuevas


# ------------------------------------------------------------------ #
# Cálculo de oportunidades
# ------------------------------------------------------------------ #

def calcular_oportunidades() -> int:
    """
    Para cada proveedor activo, calcula score contra licitaciones activas
    aún no procesadas. Devuelve cantidad de oportunidades generadas.
    """
    db: Session = SessionLocal()
    total_nuevas = 0

    try:
        proveedores = db.query(Proveedor).filter(Proveedor.activo == True).all()
        if not proveedores:
            log.info("No hay proveedores registrados.")
            db.close()
            return 0

        licitaciones = (
            db.query(Licitacion)
            .filter(Licitacion.estado.in_(["activa", "publicada", "Publicada", "Activa"]))
            .all()
        )
        if not licitaciones:
            # Fallback: tomar cualquier estado reciente
            licitaciones = (
                db.query(Licitacion)
                .order_by(Licitacion.ingested_at.desc())
                .limit(500)
                .all()
            )

        log.info("Calculando scores: %d proveedores × %d licitaciones",
                 len(proveedores), len(licitaciones))

        # Generar embeddings en batch
        licitaciones = embeder_licitaciones(licitaciones)
        db.commit()  # guardar embeddings calculados

        # IDs ya procesados por proveedor
        oportunidades_existentes: set[tuple] = set(
            (o.proveedor_id, o.licitacion_id)
            for o in db.query(Oportunidad.proveedor_id, Oportunidad.licitacion_id).all()
        )

        for proveedor in proveedores:
            for lic in licitaciones:
                if (proveedor.id, lic.id) in oportunidades_existentes:
                    continue

                score, detalle = calcular_score(lic, proveedor)
                if score < SCORE_MINIMO:
                    continue

                oport = Oportunidad(
                    proveedor_id  = proveedor.id,
                    licitacion_id = lic.id,
                    score         = score,
                    score_detalle = json.dumps(detalle),
                )
                db.add(oport)
                total_nuevas += 1

        db.commit()
        log.info("Oportunidades nuevas generadas: %d", total_nuevas)

    except Exception as e:
        db.rollback()
        log.error("Error calculando oportunidades: %s", e)
    finally:
        db.close()

    return total_nuevas


# ------------------------------------------------------------------ #
# Ciclo completo (usado por el scheduler)
# ------------------------------------------------------------------ #

async def ciclo_completo():
    nuevas = await ingestar_activas()
    if nuevas > 0 or True:   # recalcular siempre por cambios de fecha/estado
        calcular_oportunidades()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(ciclo_completo())
