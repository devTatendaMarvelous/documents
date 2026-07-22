#!/usr/bin/env bash
#
# install.sh — bootstrap the Document & Image Service on Ubuntu Linux.
#
# Usage:
#   cd /var/www/documents
#   bash install.sh
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

echo "==> Document & Image Service installer"
echo "    Project root: ${SCRIPT_DIR}"

# ---------------------------------------------------------------------------
# Python virtual environment
# ---------------------------------------------------------------------------
if [[ ! -d "venv" ]]; then
  echo "==> Creating Python virtual environment (venv)"
  python3 -m venv venv
else
  echo "==> Virtual environment already exists"
fi

# shellcheck disable=SC1091
source venv/bin/activate

echo "==> Upgrading pip"
pip install --upgrade pip setuptools wheel

echo "==> Installing Python dependencies"
pip install -r requirements.txt

# ---------------------------------------------------------------------------
# Directories
# ---------------------------------------------------------------------------
echo "==> Creating storage and log directories"
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
# Environment file
# ---------------------------------------------------------------------------
if [[ ! -f ".env" ]]; then
  echo "==> Generating .env from .env.example"
  if [[ -f ".env.example" ]]; then
    cp .env.example .env
    # Generate a random API key when openssl is available
    if command -v openssl >/dev/null 2>&1; then
      GENERATED_KEY="$(openssl rand -hex 32)"
      if grep -q '^API_KEY=' .env; then
        sed -i "s/^API_KEY=.*/API_KEY=${GENERATED_KEY}/" .env
      else
        echo "API_KEY=${GENERATED_KEY}" >> .env
      fi
      echo "    Generated a random API_KEY — store it securely"
    else
      echo "    WARNING: openssl not found; leave API_KEY=change-me and update manually"
    fi
  else
    cat > .env <<'EOF'
API_KEY=change-me
PORT=8000
MAX_UPLOAD_SIZE=50MB
LOG_LEVEL=INFO
EOF
    echo "    Created a default .env — update API_KEY before production use"
  fi
else
  echo "==> .env already exists — leaving it unchanged"
fi

# ---------------------------------------------------------------------------
# Permissions
# ---------------------------------------------------------------------------
echo "==> Setting directory permissions"

# Prefer www-data when present (production Ubuntu + Apache)
if id www-data >/dev/null 2>&1; then
  TARGET_USER="www-data"
  TARGET_GROUP="www-data"
else
  TARGET_USER="$(id -un)"
  TARGET_GROUP="$(id -gn)"
  echo "    www-data not found; using ${TARGET_USER}:${TARGET_GROUP}"
fi

# Ownership (may require sudo when installing system-wide)
if [[ "$(id -u)" -eq 0 ]]; then
  chown -R "${TARGET_USER}:${TARGET_GROUP}" \
    app/storage \
    logs \
    .env \
    venv 2>/dev/null || true
elif command -v sudo >/dev/null 2>&1; then
  sudo chown -R "${TARGET_USER}:${TARGET_GROUP}" \
    app/storage \
    logs 2>/dev/null || true
  # Ensure the service account can read the project
  sudo chown -R "${TARGET_USER}:${TARGET_GROUP}" "${SCRIPT_DIR}" 2>/dev/null || \
    echo "    NOTE: Could not change ownership of ${SCRIPT_DIR}. Run with sudo if needed."
fi

chmod 750 app/storage app/storage/* logs 2>/dev/null || true
chmod 640 .env 2>/dev/null || true
chmod 755 app app/api app/core app/utils 2>/dev/null || true

echo ""
echo "==> Installation complete"
echo ""
echo "Next steps:"
echo "  1. Review and edit .env  (especially API_KEY)"
echo "  2. sudo cp documents.service /etc/systemd/system/"
echo "  3. sudo systemctl daemon-reload"
echo "  4. sudo systemctl enable --now documents"
echo "  5. Configure Apache reverse proxy (see apache-vhost.conf / README.md)"
echo ""
echo "Quick local test:"
echo "  source venv/bin/activate"
echo "  gunicorn -k uvicorn.workers.UvicornWorker -w 2 -b 0.0.0.0:8000 app.main:app"
echo ""
