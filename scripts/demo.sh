#!/usr/bin/env bash
# Starts Stock Report on a throwaway database with fresh fake data, so you can click through everything.
# It never touches stock.db. The demo accounts use the placeholder password P@ss123 (demo data only).
set -e
cd "$(dirname "$0")/.."
PY=.venv/bin/python; [ -x "$PY" ] || PY=.venv/Scripts/python
dir=$(mktemp -d)
export DATABASE_URL="sqlite:///$dir/demo.db"
# Set DEMO_PASSWORD yourself to use a different password.
export DEMO_PASSWORD="${DEMO_PASSWORD:-P@ss123}"
echo "Demo database: $dir"
PORT=${PORT:-8000}  # set PORT=8001 if another server already uses 8000
echo "Open http://localhost:$PORT  ·  sam@example.com (staff), acme@acme.example.com, nova@nova.example.com"
echo "Password for all three: $DEMO_PASSWORD"
# LAN=1 listens on every address, so a phone or another computer on your network can open it.
HOST=127.0.0.1; [ "${LAN:-}" = "1" ] && HOST=0.0.0.0
exec "$PY" -u -m uvicorn app.main:app --host "$HOST" --port "$PORT"
