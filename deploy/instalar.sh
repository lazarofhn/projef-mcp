#!/usr/bin/env bash
# Instala o projef-mcp como serviço systemd num servidor Linux (Debian/Ubuntu).
# Uso (na pasta do repositório, como o usuário que vai rodar o serviço):
#   PROJEF_HOSTNAME=projef.seudominio.com.br bash deploy/instalar.sh
set -euo pipefail
cd "$(dirname "$0")/.."
: "${PROJEF_HOSTNAME:?defina PROJEF_HOSTNAME com o domínio público (ex.: projef.seudominio.com.br)}"
PORTA="${PROJEF_PORT:-8092}"

python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q .
.venv/bin/python -m playwright install chromium
sudo .venv/bin/python -m playwright install-deps chromium

if [ ! -f .env ]; then
  SEGREDO=$(python3 -c "import secrets; print(secrets.token_urlsafe(24))")
  cat > .env <<ENV
PROJEF_HOST=127.0.0.1
PROJEF_PORT=$PORTA
PROJEF_PATH_SECRET=$SEGREDO
PROJEF_ALLOWED_HOSTS=$PROJEF_HOSTNAME
PROJEF_CONCORRENCIA=2
ENV
  chmod 600 .env
fi

sed -e "s|__USUARIO__|$USER|g" -e "s|__PASTA__|$PWD|g" deploy/projef-mcp.service \
  | sudo tee /etc/systemd/system/projef-mcp.service >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable --now projef-mcp
sleep 3

SEG=$(grep PROJEF_PATH_SECRET .env | cut -d= -f2)
curl -s -o /dev/null -w "teste local: HTTP %{http_code} (esperado 406 ou 400)\n" -X POST \
  "http://127.0.0.1:$PORTA/$SEG/mcp" -H "Content-Type: application/json" -d '{}'
echo "Depois de publicar a porta $PORTA no domínio (ex.: Cloudflare Tunnel), a URL do conector será:"
echo "  https://$PROJEF_HOSTNAME/$SEG/mcp"
