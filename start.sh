#!/bin/bash
set -e

cd "$(dirname "$0")"

echo "──────────────────────────────────────────"
echo "  Radar Mercado Público — Inicializando"
echo "──────────────────────────────────────────"

# Crear venv si no existe
if [ ! -d ".venv" ]; then
  echo "→ Creando entorno virtual con uv..."
  uv venv --python 3.13
fi

# Activar
source .venv/bin/activate

# Instalar dependencias si faltan
echo "→ Verificando dependencias..."
uv pip install -q fastapi uvicorn sqlalchemy aiohttp "sentence-transformers>=3.1" numpy apscheduler python-dotenv python-multipart

# API Key Anthropic (opcional, para análisis IA futuro)
if [ -z "$ANTHROPIC_API_KEY" ]; then
  echo "⚠  ANTHROPIC_API_KEY no definida (opcional para esta versión)"
fi

echo ""
echo "  Servidor en: http://127.0.0.1:8766"
echo "  Abre con:    open -a Safari http://127.0.0.1:8766"
echo ""

python app.py
