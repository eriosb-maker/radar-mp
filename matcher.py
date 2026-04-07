"""
Motor de matching: calcula un score 0–100 entre una licitación y un perfil de proveedor.
"""
import json
import logging
from datetime import datetime, timedelta, timezone

import numpy as np
from sentence_transformers import SentenceTransformer

from config import EMBEDDING_MODEL

log = logging.getLogger(__name__)

# Carga el modelo una sola vez (tarda ~10s la primera vez)
_model: SentenceTransformer | None = None


def get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        log.info("Cargando modelo de embeddings %s ...", EMBEDDING_MODEL)
        _model = SentenceTransformer(EMBEDDING_MODEL)
        log.info("Modelo listo.")
    return _model


def embed(texto: str) -> list[float]:
    model = get_model()
    vector = model.encode(texto, normalize_embeddings=True)
    return vector.tolist()


def cosine_sim(a: list[float], b: list[float]) -> float:
    va = np.array(a, dtype=np.float32)
    vb = np.array(b, dtype=np.float32)
    dot = float(np.dot(va, vb))
    # Los vectores ya vienen normalizados desde SentenceTransformer
    return max(0.0, min(1.0, dot))


# ------------------------------------------------------------------ #
# Score principal
# ------------------------------------------------------------------ #

def calcular_score(licitacion, proveedor) -> tuple[float, dict]:
    """
    Devuelve (score_total, breakdown_dict).

    Componentes:
      - similaridad_semantica : 40 pts  (coseno embedding licitación vs rubros)
      - region                : 20 pts  (región coincide o proveedor acepta todas)
      - monto                 : 20 pts  (monto estimado dentro del rango)
      - urgencia              : 10 pts  (cierre en < 48 h)
      - reservado             : 10 pts  (futuro: baja competencia histórica)
    """
    breakdown = {
        "similaridad": 0,
        "region": 0,
        "monto": 0,
        "urgencia": 0,
        "bono_competencia": 0,
    }

    # 1. Similitud semántica (40 pts)
    lic_emb = licitacion.get_embedding()
    if lic_emb is None:
        texto = licitacion.texto_para_embedding()
        lic_emb = embed(texto)
        licitacion.set_embedding(lic_emb)

    rubros_texto = proveedor.rubros or ""
    prov_emb = embed(rubros_texto)

    sim = cosine_sim(lic_emb, prov_emb)
    breakdown["similaridad"] = round(sim * 40, 2)

    # 2. Región (20 pts)
    regiones_prov = proveedor.get_regiones()
    if not regiones_prov:                          # sin restricción → acepta todas
        breakdown["region"] = 20
    elif licitacion.region and any(
        r.lower() in licitacion.region.lower() or licitacion.region.lower() in r.lower()
        for r in regiones_prov
    ):
        breakdown["region"] = 20

    # 3. Monto (20 pts)
    monto = licitacion.monto_estimado
    if monto is None:
        breakdown["monto"] = 10   # sin info → partial credit
    elif proveedor.monto_min <= monto <= proveedor.monto_max:
        breakdown["monto"] = 20
    elif monto < proveedor.monto_min * 0.5 or monto > proveedor.monto_max * 2:
        breakdown["monto"] = 0    # muy fuera de rango
    else:
        breakdown["monto"] = 10   # rango adyacente

    # 4. Urgencia (10 pts)
    if licitacion.fecha_cierre:
        ahora = datetime.utcnow()
        delta = licitacion.fecha_cierre - ahora
        if timedelta(0) < delta <= timedelta(hours=48):
            breakdown["urgencia"] = 10
        elif timedelta(0) < delta <= timedelta(hours=96):
            breakdown["urgencia"] = 5

    total = sum(breakdown.values())
    return round(total, 1), breakdown


# ------------------------------------------------------------------ #
# Embedding masivo de licitaciones (usado en ingesta)
# ------------------------------------------------------------------ #

def embeder_licitaciones(licitaciones: list) -> list:
    """
    Genera embeddings en batch para una lista de objetos Licitacion.
    Mucho más rápido que uno a uno.
    """
    model = get_model()
    sin_embedding = [l for l in licitaciones if l.get_embedding() is None]
    if not sin_embedding:
        return licitaciones

    textos = [l.texto_para_embedding() for l in sin_embedding]
    vectores = model.encode(textos, normalize_embeddings=True, batch_size=64, show_progress_bar=False)

    for lic, vec in zip(sin_embedding, vectores):
        lic.set_embedding(vec.tolist())

    return licitaciones
