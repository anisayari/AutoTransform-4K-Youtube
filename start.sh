#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$ROOT_DIR/.venv"
PYTHON_BIN="${PYTHON_BIN:-python3}"
STAMP_FILE="$VENV_DIR/.requirements.sha256"
DEFAULT_PORT="${APP_PORT:-5001}"

cd "$ROOT_DIR"

if [ ! -d "$VENV_DIR" ]; then
  echo "[setup] creation du virtualenv"
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

CURRENT_HASH="$("$PYTHON_BIN" - <<'PY'
from pathlib import Path
import hashlib

print(hashlib.sha256(Path("requirements.txt").read_bytes()).hexdigest())
PY
)"

INSTALLED_HASH=""
if [ -f "$STAMP_FILE" ]; then
  INSTALLED_HASH="$(cat "$STAMP_FILE")"
fi

if [ "$CURRENT_HASH" != "$INSTALLED_HASH" ]; then
  echo "[setup] installation des dependances"
  pip install -r requirements.txt
  printf '%s' "$CURRENT_HASH" > "$STAMP_FILE"
fi

if [ ! -f ".env" ]; then
  echo "[setup] creation de .env depuis .env.example"
  cp .env.example .env
fi

if [ ! -f "client_secret.json" ]; then
  cat <<'EOF'
[warning] client_secret.json est manquant.
Ajoute ton fichier OAuth Google a la racine du projet avant de connecter YouTube.
EOF
fi

APP_PORT="$("$PYTHON_BIN" - <<PY
import socket

start_port = int(${DEFAULT_PORT})
for port in range(start_port, start_port + 20):
    with socket.socket() as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            continue
        print(port)
        break
else:
    raise SystemExit("aucun port libre trouve entre 5001 et 5020")
PY
)"

export APP_PORT
export GOOGLE_REDIRECT_URI="http://localhost:${APP_PORT}/auth/google/callback"
echo "[run] http://localhost:${APP_PORT}"
echo "[oauth] origin: http://localhost:${APP_PORT}"
echo "[oauth] redirect: ${GOOGLE_REDIRECT_URI}"
exec "$PYTHON_BIN" run.py
