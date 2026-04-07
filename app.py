"""
Radar de Oportunidades — Mercado Público
Backend FastAPI + Scheduler APScheduler
"""
import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy.orm import Session

from fastapi.responses import Response

from config import POLL_INTERVAL_MINUTOS
from database import Licitacion, Oportunidad, Proveedor, get_db, init_db
from due_diligence import due_diligence_completo
from ingesta import ciclo_completo
from notifier import enviar_alertas
from report_dd import generar_docx

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
log = logging.getLogger(__name__)

scheduler = AsyncIOScheduler(timezone="America/Santiago")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Startup
    init_db()
    log.info("Base de datos inicializada.")

    # Primera ingesta en background (no bloquea el startup)
    import asyncio
    asyncio.create_task(ciclo_completo())

    # Scheduler: polling + notificaciones
    scheduler.add_job(ciclo_completo, "interval", minutes=POLL_INTERVAL_MINUTOS,
                      id="ingesta", replace_existing=True)
    scheduler.add_job(enviar_alertas, "interval", minutes=60,
                      id="alertas", replace_existing=True)
    scheduler.start()
    log.info("Scheduler activo — polling cada %d min.", POLL_INTERVAL_MINUTOS)

    yield

    # Shutdown
    scheduler.shutdown()


app = FastAPI(title="Radar Mercado Público", version="1.0.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")


# ------------------------------------------------------------------ #
# Schemas Pydantic
# ------------------------------------------------------------------ #

class ProveedorCreate(BaseModel):
    rut:       str
    nombre:    str
    email:     str
    rubros:    str           # "construcción, mantención, pintura"
    regiones:  list[str]     # ["Metropolitana", "Valparaíso"]
    monto_min: float = 0
    monto_max: float = 999_999_999_999


class ProveedorUpdate(BaseModel):
    nombre:    str | None = None
    email:     str | None = None
    rubros:    str | None = None
    regiones:  list[str] | None = None
    monto_min: float | None = None
    monto_max: float | None = None


# ------------------------------------------------------------------ #
# Helpers de serialización
# ------------------------------------------------------------------ #

def _ser_licitacion(l: Licitacion) -> dict:
    return {
        "id":              l.id,
        "nombre":          l.nombre,
        "descripcion":     l.descripcion,
        "organismo":       l.organismo,
        "region":          l.region,
        "monto_estimado":  l.monto_estimado,
        "fecha_cierre":    l.fecha_cierre.isoformat() if l.fecha_cierre else None,
        "fecha_publicacion": l.fecha_publicacion.isoformat() if l.fecha_publicacion else None,
        "estado":          l.estado,
        "tipo":            l.tipo,
    }


def _ser_proveedor(p: Proveedor) -> dict:
    return {
        "id":        p.id,
        "rut":       p.rut,
        "nombre":    p.nombre,
        "email":     p.email,
        "rubros":    p.rubros,
        "regiones":  p.get_regiones(),
        "monto_min": p.monto_min,
        "monto_max": p.monto_max,
        "activo":    p.activo,
    }


# ------------------------------------------------------------------ #
# Rutas — Frontend
# ------------------------------------------------------------------ #

@app.get("/", include_in_schema=False)
async def root():
    return FileResponse("static/index.html")


# ------------------------------------------------------------------ #
# Rutas — Proveedores
# ------------------------------------------------------------------ #

@app.post("/api/proveedores", status_code=201)
def crear_proveedor(body: ProveedorCreate, db: Session = Depends(get_db)):
    if db.query(Proveedor).filter(Proveedor.rut == body.rut).first():
        raise HTTPException(400, f"RUT {body.rut} ya está registrado.")

    p = Proveedor(
        rut       = body.rut,
        nombre    = body.nombre,
        email     = body.email,
        rubros    = body.rubros,
        monto_min = body.monto_min,
        monto_max = body.monto_max,
    )
    p.set_regiones(body.regiones)
    db.add(p)
    db.commit()
    db.refresh(p)
    return _ser_proveedor(p)


@app.get("/api/proveedores/{rut}")
def obtener_proveedor(rut: str, db: Session = Depends(get_db)):
    p = db.query(Proveedor).filter(Proveedor.rut == rut).first()
    if not p:
        raise HTTPException(404, "Proveedor no encontrado.")
    return _ser_proveedor(p)


@app.put("/api/proveedores/{rut}")
def actualizar_proveedor(rut: str, body: ProveedorUpdate, db: Session = Depends(get_db)):
    p = db.query(Proveedor).filter(Proveedor.rut == rut).first()
    if not p:
        raise HTTPException(404, "Proveedor no encontrado.")

    if body.nombre   is not None: p.nombre    = body.nombre
    if body.email    is not None: p.email     = body.email
    if body.rubros   is not None: p.rubros    = body.rubros
    if body.regiones is not None: p.set_regiones(body.regiones)
    if body.monto_min is not None: p.monto_min = body.monto_min
    if body.monto_max is not None: p.monto_max = body.monto_max

    db.commit()
    return _ser_proveedor(p)


# ------------------------------------------------------------------ #
# Rutas — Oportunidades
# ------------------------------------------------------------------ #

@app.get("/api/oportunidades/{rut}")
def listar_oportunidades(
    rut: str,
    limit: int = 50,
    score_min: float = 40,
    db: Session = Depends(get_db)
):
    p = db.query(Proveedor).filter(Proveedor.rut == rut).first()
    if not p:
        raise HTTPException(404, "Proveedor no encontrado.")

    ops = (
        db.query(Oportunidad)
        .filter(
            Oportunidad.proveedor_id == p.id,
            Oportunidad.score >= score_min
        )
        .order_by(Oportunidad.score.desc())
        .limit(limit)
        .all()
    )

    resultado = []
    for op in ops:
        lic = db.get(Licitacion, op.licitacion_id)
        if not lic:
            continue
        resultado.append({
            "oportunidad_id": op.id,
            "score":          op.score,
            "score_detalle":  op.get_detalle(),
            "licitacion":     _ser_licitacion(lic),
        })

    return {"total": len(resultado), "oportunidades": resultado}


# ------------------------------------------------------------------ #
# Rutas — Licitaciones
# ------------------------------------------------------------------ #

@app.get("/api/licitaciones")
def listar_licitaciones(
    estado: str | None = None,
    organismo: str | None = None,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db)
):
    q = db.query(Licitacion)
    if estado:
        q = q.filter(Licitacion.estado.ilike(f"%{estado}%"))
    if organismo:
        q = q.filter(Licitacion.organismo.ilike(f"%{organismo}%"))

    total = q.count()
    lics  = q.order_by(Licitacion.ingested_at.desc()).offset(offset).limit(limit).all()

    return {
        "total": total,
        "licitaciones": [_ser_licitacion(l) for l in lics]
    }


@app.get("/api/licitaciones/{codigo}")
async def detalle_licitacion(codigo: str, db: Session = Depends(get_db)):
    lic = db.get(Licitacion, codigo)
    if not lic:
        raise HTTPException(404, "Licitación no encontrada.")

    # Enriquecer con detalle de la API si aún no tiene organismo
    if not lic.organismo:
        try:
            detalle = await client.licitacion_detalle(codigo)
            if detalle:
                lic.organismo        = detalle["organismo"]
                lic.codigo_organismo = detalle["codigo_organismo"]
                lic.region           = detalle["region"]
                lic.monto_estimado   = detalle["monto_estimado"]
                lic.descripcion      = detalle["descripcion"]
                lic.raw_json         = json.dumps(detalle["raw"], ensure_ascii=False)
                db.commit()
        except Exception as e:
            log.warning("No se pudo enriquecer %s: %s", codigo, e)

    data = _ser_licitacion(lic)
    data["raw"] = json.loads(lic.raw_json) if lic.raw_json else {}
    return data


# ------------------------------------------------------------------ #
# Rutas — Sistema
# ------------------------------------------------------------------ #

@app.get("/api/stats")
def stats(db: Session = Depends(get_db)):
    return {
        "licitaciones_total":   db.query(Licitacion).count(),
        "licitaciones_activas": db.query(Licitacion).filter(
            Licitacion.estado.ilike("%activa%") | Licitacion.estado.ilike("%publicada%")
        ).count(),
        "proveedores":          db.query(Proveedor).filter(Proveedor.activo == True).count(),
        "oportunidades_hoy":    db.query(Oportunidad).filter(
            Oportunidad.created_at >= datetime.utcnow().replace(hour=0, minute=0, second=0)
        ).count(),
        "ultima_ingesta":       datetime.utcnow().isoformat(),
    }


@app.post("/api/ingesta/forzar")
async def forzar_ingesta():
    """Fuerza una ingesta manual (útil para testing)."""
    await ciclo_completo()
    return {"ok": True, "mensaje": "Ingesta completada."}


@app.post("/api/ingesta/enriquecer")
async def enriquecer_licitaciones(limite: int = 50, db: Session = Depends(get_db)):
    """
    Descarga el detalle (organismo, región, monto, descripción) de licitaciones
    que solo tienen nombre. Llamar en horario nocturno para no saturar la API.
    """
    import asyncio
    sin_detalle = (
        db.query(Licitacion)
        .filter(Licitacion.organismo == None)
        .limit(limite)
        .all()
    )
    enriquecidas = 0
    for lic in sin_detalle:
        try:
            detalle = await client.licitacion_detalle(lic.id)
            if detalle:
                lic.organismo        = detalle["organismo"]
                lic.codigo_organismo = detalle["codigo_organismo"]
                lic.region           = detalle["region"]
                lic.monto_estimado   = detalle["monto_estimado"]
                lic.descripcion      = detalle["descripcion"]
                lic.raw_json         = json.dumps(detalle["raw"], ensure_ascii=False)
                enriquecidas += 1
            await asyncio.sleep(0.3)   # respetar rate limit
        except Exception as e:
            log.warning("Enriquecimiento %s: %s", lic.id, e)
    db.commit()
    return {"enriquecidas": enriquecidas, "total_sin_detalle": len(sin_detalle)}


# ------------------------------------------------------------------ #
# Rutas — Due Diligence
# ------------------------------------------------------------------ #

@app.get("/dd", include_in_schema=False)
async def dd_page():
    return FileResponse("static/dd.html")


@app.get("/api/dd/{rut}")
async def due_diligence_json(rut: str):
    """
    Genera el informe de due diligence completo para un RUT.
    Puede tardar 30-60 segundos (descarga datos + análisis Claude).
    """
    try:
        informe = await due_diligence_completo(rut)
        return informe
    except ValueError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        log.error("Error en DD para %s: %s", rut, e)
        raise HTTPException(500, f"Error generando informe: {e}")


@app.get("/api/dd/{rut}/docx")
async def due_diligence_docx(rut: str):
    """Genera y descarga el informe en formato DOCX."""
    try:
        informe = await due_diligence_completo(rut)
    except ValueError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        raise HTTPException(500, str(e))

    docx_bytes = generar_docx(informe)
    nombre = informe["proveedor"]["nombre"] or rut
    nombre_archivo = f"DD_{nombre.replace(' ', '_')[:40]}.docx"

    return Response(
        content     = docx_bytes,
        media_type  = "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers     = {"Content-Disposition": f'attachment; filename="{nombre_archivo}"'},
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="127.0.0.1", port=8766, reload=False)
