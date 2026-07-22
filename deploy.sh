#!/usr/bin/env bash
#
# deploy.sh — full Ubuntu server deployment for the Document & Image Service
#
# Run this AFTER you copy the project onto the server, for example:
#
#   scp -r documents/ user@server:/tmp/documents
#   ssh user@server
#   sudo bash /tmp/documents/deploy.sh
#
# Or if already in place:
#
#   cd /var/www/documents
#   sudo bash deploy.sh
#
# Optional environment overrides:
#   APP_DIR=/var/www/documents
#   SERVER_NAME=files.example.com
#   BIND=127.0.0.1:8000
#   WORKERS=4
#   SKIP_APACHE=1
#   SKIP_APT=1
#
set -euo pipefail

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="${APP_DIR:-/var/www/documents}"
SERVER_NAME="${SERVER_NAME:-files.example.com}"
BIND="${BIND:-127.0.0.1:8000}"
WORKERS="${WORKERS:-4}"
SERVICE_NAME="documents"
SKIP_APACHE="${SKIP_APACHE:-0}"
SKIP_APT="${SKIP_APT:-0}"
SERVICE_USER="www-data"
SERVICE_GROUP="www-data"

log()  { echo "==> $*"; }
warn() { echo "WARNING: $*" >&2; }
die()  { echo "ERROR: $*" >&2; exit 1; }

require_root() {
  if [[ "$(id -u)" -ne 0 ]]; then
    die "Run as root: sudo bash deploy.sh"
  fi
}

# ---------------------------------------------------------------------------
# Pre-flight
# ---------------------------------------------------------------------------
require_root

echo ""
echo "=============================================="
echo " Document & Image Service — server deploy"
echo "=============================================="
echo " Source:      ${SCRIPT_DIR}"
echo " Install to:  ${APP_DIR}"
echo " Bind:        ${BIND}"
echo " Workers:     ${WORKERS}"
echo " ServerName:  ${SERVER_NAME}"
echo " Apache:      $([[ "${SKIP_APACHE}" == "1" ]] && echo skipped || echo enabled)"
echo "=============================================="
echo ""

if [[ ! -f "${SCRIPT_DIR}/app/main.py" ]]; then
  die "Cannot find app/main.py in ${SCRIPT_DIR}. Run this script from the project root."
fi

if ! id "${SERVICE_USER}" >/dev/null 2>&1; then
  die "System user '${SERVICE_USER}' does not exist. Is this an Ubuntu/Apache host?"
fi

# ---------------------------------------------------------------------------
# System packages
# ---------------------------------------------------------------------------
if [[ "${SKIP_APT}" != "1" ]]; then
  log "Installing system packages"
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -y
  apt-get install -y \
    python3 \
    python3-venv \
    python3-pip \
    apache2 \
    openssl \
    curl \
    rsync
  a2enmod proxy proxy_http headers rewrite >/dev/null
else
  log "Skipping apt package install (SKIP_APT=1)"
fi

command -v python3 >/dev/null || die "python3 is not installed"
command -v curl >/dev/null || die "curl is not installed"

# ---------------------------------------------------------------------------
# Copy / sync project into APP_DIR
# ---------------------------------------------------------------------------
log "Preparing application directory: ${APP_DIR}"
mkdir -p "${APP_DIR}"

if [[ "$(realpath "${SCRIPT_DIR}")" != "$(realpath "${APP_DIR}")" ]]; then
  log "Syncing project files to ${APP_DIR}"
  # Preserve an existing .env if present at the destination
  if [[ -f "${APP_DIR}/.env" && ! -f "${SCRIPT_DIR}/.env" ]]; then
    cp -a "${APP_DIR}/.env" /tmp/documents.env.backup
  fi

  rsync -a \
    --exclude 'venv/' \
    --exclude '__pycache__/' \
    --exclude '*.pyc' \
    --exclude 'logs/*.log' \
    --exclude 'app/storage/documents/*' \
    --exclude 'app/storage/images/*' \
    --exclude 'app/storage/optimized/*' \
    --exclude 'app/storage/thumbnails/*' \
    --exclude '.env' \
    "${SCRIPT_DIR}/" "${APP_DIR}/"

  # Keep destination .env; otherwise restore backup if we had one
  if [[ ! -f "${APP_DIR}/.env" && -f /tmp/documents.env.backup ]]; then
    mv /tmp/documents.env.backup "${APP_DIR}/.env"
  fi
  rm -f /tmp/documents.env.backup
else
  log "Already running from ${APP_DIR} — no copy needed"
fi

cd "${APP_DIR}"

# Ensure storage placeholders survive rsync excludes
mkdir -p \
  app/storage/documents \
  app/storage/images \
  app/storage/optimized \
  app/storage/thumbnails \
  logs
touch \
  app/storage/documents/.gitkeep \
  app/storage/images/.gitkeep \
  app/storage/optimized/.gitkeep \
  app/storage/thumbnails/.gitkeep \
  logs/.gitkeep

# ---------------------------------------------------------------------------
# Python venv + dependencies
# ---------------------------------------------------------------------------
log "Creating / refreshing Python virtual environment"
if [[ ! -d venv ]]; then
  python3 -m venv venv
fi

# shellcheck disable=SC1091
source venv/bin/activate
pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
deactivate

# ---------------------------------------------------------------------------
# Environment file
# ---------------------------------------------------------------------------
if [[ ! -f .env ]]; then
  log "Creating .env"
  if [[ -f .env.example ]]; then
    cp .env.example .env
  else
    cat > .env <<'EOF'
API_KEY=change-me
PORT=8000
MAX_UPLOAD_SIZE=50MB
LOG_LEVEL=INFO
EOF
  fi

  if command -v openssl >/dev/null 2>&1; then
    GENERATED_KEY="$(openssl rand -hex 32)"
    sed -i "s/^API_KEY=.*/API_KEY=${GENERATED_KEY}/" .env
    log "Generated API_KEY (saved in ${APP_DIR}/.env)"
  else
    warn "openssl missing — set API_KEY in ${APP_DIR}/.env manually"
  fi
else
  log ".env already exists — leaving unchanged"
fi

# Sync PORT from BIND if present
BIND_PORT="${BIND##*:}"
if grep -q '^PORT=' .env; then
  sed -i "s/^PORT=.*/PORT=${BIND_PORT}/" .env
else
  echo "PORT=${BIND_PORT}" >> .env
fi

# ---------------------------------------------------------------------------
# Permissions
# ---------------------------------------------------------------------------
log "Setting ownership to ${SERVICE_USER}:${SERVICE_GROUP}"
chown -R "${SERVICE_USER}:${SERVICE_GROUP}" "${APP_DIR}"
chmod 750 app/storage app/storage/* logs
chmod 640 .env
chmod 755 "${APP_DIR}"
find app -type d -exec chmod 755 {} \;
find app -type f -name '*.py' -exec chmod 644 {} \;
chmod +x install.sh deploy.sh 2>/dev/null || true

# ---------------------------------------------------------------------------
# systemd unit (paths rewritten for APP_DIR / BIND / WORKERS)
# ---------------------------------------------------------------------------
log "Installing systemd unit: ${SERVICE_NAME}.service"
UNIT_SRC="${APP_DIR}/documents.service"
UNIT_DST="/etc/systemd/system/${SERVICE_NAME}.service"

if [[ ! -f "${UNIT_SRC}" ]]; then
  die "Missing ${UNIT_SRC}"
fi

# Rewrite paths from the template defaults to the actual APP_DIR / BIND / WORKERS
sed \
  -e "s|/var/www/documents|${APP_DIR}|g" \
  -e "s|-w 4|-w ${WORKERS}|g" \
  -e "s|-b 127.0.0.1:8000|-b ${BIND}|g" \
  "${UNIT_SRC}" > "${UNIT_DST}"

systemctl daemon-reload
systemctl enable "${SERVICE_NAME}"
systemctl restart "${SERVICE_NAME}"

sleep 2
if ! systemctl is-active --quiet "${SERVICE_NAME}"; then
  warn "Service failed to start — recent logs:"
  journalctl -u "${SERVICE_NAME}" -n 40 --no-pager || true
  die "${SERVICE_NAME}.service is not active"
fi
log "systemd service is active"

# ---------------------------------------------------------------------------
# Apache reverse proxy (optional)
# ---------------------------------------------------------------------------
if [[ "${SKIP_APACHE}" != "1" ]]; then
  if command -v apache2 >/dev/null 2>&1 || command -v apachectl >/dev/null 2>&1; then
    log "Configuring Apache VirtualHost (${SERVER_NAME})"
    SITE_AVAILABLE="/etc/apache2/sites-available/${SERVICE_NAME}.conf"
    PROXY_TARGET="http://${BIND}/"

    cat > "${SITE_AVAILABLE}" <<EOF
<VirtualHost *:80>
    ServerName ${SERVER_NAME}
    ServerAdmin admin@${SERVER_NAME}

    ProxyPreserveHost On
    ProxyRequests Off

    RequestHeader set X-Forwarded-Proto "http"
    RequestHeader set X-Real-IP %{REMOTE_ADDR}s

    # Align with default MAX_UPLOAD_SIZE=50MB
    LimitRequestBody 52428800

    ProxyPass / ${PROXY_TARGET}
    ProxyPassReverse / ${PROXY_TARGET}

    ErrorLog \${APACHE_LOG_DIR}/documents_error.log
    CustomLog \${APACHE_LOG_DIR}/documents_access.log combined
</VirtualHost>
EOF

    a2ensite "${SERVICE_NAME}.conf" >/dev/null
    if apache2ctl configtest; then
      systemctl reload apache2
      log "Apache site enabled and reloaded"
    else
      warn "Apache configtest failed — fix ${SITE_AVAILABLE} then: systemctl reload apache2"
    fi
  else
    warn "Apache not installed — skipping reverse proxy (set SKIP_APACHE=1 to silence)"
  fi
else
  log "Skipping Apache configuration (SKIP_APACHE=1)"
fi

# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------
log "Running local health check"
HEALTH_URL="http://${BIND}/health"
# BIND may be 127.0.0.1:8000 — curl that directly
if curl -fsS --max-time 5 "${HEALTH_URL}" | grep -q '"status"[[:space:]]*:[[:space:]]*"ok"'; then
  log "Health check passed: ${HEALTH_URL}"
else
  warn "Health check did not return ok — check: journalctl -u ${SERVICE_NAME} -f"
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
API_KEY_VALUE="$(grep -E '^API_KEY=' "${APP_DIR}/.env" | head -n1 | cut -d= -f2- || true)"

echo ""
echo "=============================================="
echo " Deploy complete"
echo "=============================================="
echo " App path:     ${APP_DIR}"
echo " Service:      systemctl status ${SERVICE_NAME}"
echo " Logs:         journalctl -u ${SERVICE_NAME} -f"
echo " App log:      ${APP_DIR}/logs/application.log"
echo " Health:       curl ${HEALTH_URL}"
echo " API key:      ${APP_DIR}/.env  (API_KEY=${API_KEY_VALUE:0:8}…)"
if [[ "${SKIP_APACHE}" != "1" ]]; then
  echo " Apache host:  http://${SERVER_NAME}/"
  echo "               (point DNS A record to this server, then consider certbot)"
fi
echo ""
echo " Test upload:"
echo "   curl -X POST http://${BIND}/upload/document \\"
echo "     -H \"X-API-Key: \$(grep ^API_KEY= ${APP_DIR}/.env | cut -d= -f2-)\" \\"
echo "     -F \"file=@./somefile.pdf\""
echo ""
echo " Useful commands:"
echo "   sudo systemctl restart ${SERVICE_NAME}"
echo "   sudo journalctl -u ${SERVICE_NAME} -n 100 --no-pager"
echo "   sudo nano ${APP_DIR}/.env && sudo systemctl restart ${SERVICE_NAME}"
echo "=============================================="
echo ""
