import json
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean, Column, DateTime, Float, String, Text, create_engine
)
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from config import DATABASE_URL

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


class Base(DeclarativeBase):
    pass


class Licitacion(Base):
    __tablename__ = "licitaciones"

    id              = Column(String, primary_key=True)   # CodigoExterno
    nombre          = Column(Text)
    descripcion     = Column(Text)
    organismo       = Column(String)
    codigo_organismo = Column(String)
    region          = Column(String)
    monto_estimado  = Column(Float, nullable=True)
    fecha_cierre    = Column(DateTime, nullable=True)
    fecha_publicacion = Column(DateTime, nullable=True)
    estado          = Column(String)
    tipo            = Column(String, nullable=True)      # L1, LE, LP, LQ, etc.
    embedding_json  = Column(Text, nullable=True)        # JSON de lista float
    raw_json        = Column(Text)
    ingested_at     = Column(DateTime, default=datetime.utcnow)

    def get_embedding(self) -> list[float] | None:
        if self.embedding_json:
            return json.loads(self.embedding_json)
        return None

    def set_embedding(self, vector: list[float]):
        self.embedding_json = json.dumps(vector)

    def texto_para_embedding(self) -> str:
        partes = [self.nombre or "", self.descripcion or "", self.organismo or ""]
        return " ".join(p for p in partes if p).strip()


class Proveedor(Base):
    __tablename__ = "proveedores"

    id         = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    rut        = Column(String, unique=True)
    nombre     = Column(String)
    email      = Column(String)
    rubros     = Column(Text)                # texto libre: "construcción, mantención edificios, pintura"
    regiones   = Column(Text)               # JSON list: ["Metropolitana", "Valparaíso"]
    monto_min  = Column(Float, default=0)
    monto_max  = Column(Float, default=999_999_999_999)
    activo     = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    def get_regiones(self) -> list[str]:
        if self.regiones:
            return json.loads(self.regiones)
        return []

    def set_regiones(self, lista: list[str]):
        self.regiones = json.dumps(lista)


class Oportunidad(Base):
    __tablename__ = "oportunidades"

    id            = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    proveedor_id  = Column(String)
    licitacion_id = Column(String)
    score         = Column(Float)
    score_detalle = Column(Text)     # JSON con breakdown por componente
    notificado    = Column(Boolean, default=False)
    created_at    = Column(DateTime, default=datetime.utcnow)

    def get_detalle(self) -> dict:
        if self.score_detalle:
            return json.loads(self.score_detalle)
        return {}


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    Base.metadata.create_all(bind=engine)
