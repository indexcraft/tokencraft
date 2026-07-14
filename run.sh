#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

export TOKENCRAFT_LOCAL_MODE=true

echo "Checking dependencies..."
python3 -m pip install -q -r requirements.txt

echo "Starting TokenCraft at http://127.0.0.1:8000 ..."
(
  for i in $(seq 1 30); do
    if curl -s -o /dev/null http://127.0.0.1:8000/health; then
      (open http://127.0.0.1:8000 2>/dev/null || xdg-open http://127.0.0.1:8000 2>/dev/null || true)
      break
    fi
    sleep 1
  done
) &
python3 -m uvicorn app:app --host 127.0.0.1 --port 8000
