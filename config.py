import os
from dotenv import load_dotenv

load_dotenv()

CHILECOMPRA_TICKET = os.getenv("CHILECOMPRA_TICKET", "0F6A6527-FFF9-4907-9622-EC72A4C73E9B")
ANTHROPIC_API_KEY  = os.getenv("ANTHROPIC_API_KEY", "")

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./radar_mp.db")
EMBEDDING_MODEL = "paraphrase-multilingual-mpnet-base-v2"

# Score thresholds
SCORE_ALERTA   = 70   # notificar por email
SCORE_MINIMO   = 40   # mostrar en dashboard

# Polling
POLL_INTERVAL_MINUTOS = 30

# Email (opcional — configurar para notificaciones)
SMTP_HOST     = os.getenv("SMTP_HOST", "")
SMTP_PORT     = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER     = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
FROM_EMAIL    = os.getenv("FROM_EMAIL", "radar@riosyrios.cl")
