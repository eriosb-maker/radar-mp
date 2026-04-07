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

# Cargar .env si existe
if [ -f ".env" ]; then
  export $(grep -v '^#' .env | xargs)
  echo "→ Variables cargadas desde .env"
fi

# Validar ticket ChileCompra
if [ -z "$CHILECOMPRA_TICKET" ]; then
  echo "⚠  CHILECOMPRA_TICKET no definido."
  echo "   Copia .env.example a .env y agrega tu ticket."
  echo "   Obtener ticket en: https://api.mercadopublico.cl/modules/IniciarSesion.aspx"
  exit 1
fi

echo ""
echo "  Servidor en: http://127.0.0.1:8766"
echo "  Abre con:    open -a Safari http://127.0.0.1:8766"
echo ""

python app.py
