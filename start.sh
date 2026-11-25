#!/usr/bin/env bash
# AI Creative Studio – start ComfyUI (if installed locally) and the backend/dashboard.
# Usage: ./start.sh [--no-comfyui] [--dev] [--host 127.0.0.1] [--port 8420]
#   --no-comfyui  do not start the local ComfyUI (use an already running instance)
#   --dev         additionally run the dashboard dev server (Vite, port 5173)
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

START_COMFY=1; DEV=0; HOST=""; PORT=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-comfyui) START_COMFY=0 ;;
    --dev) DEV=1 ;;
    --host) HOST="$2"; shift ;;
    --port) PORT="$2"; shift ;;
    -h|--help) sed -n '2,6p' "$0"; exit 0 ;;
    *) echo "Unbekannte Option: $1"; exit 2 ;;
  esac
  shift
done

VPY="$ROOT/.venv/bin/python"
[[ -x "$VPY" ]] || { echo "Nicht eingerichtet – zuerst ./setup.sh ausführen."; exit 1; }
mkdir -p data/logs
PIDS=()
cleanup() {
  for pid in "${PIDS[@]:-}"; do [[ -n "$pid" ]] && kill "$pid" 2>/dev/null || true; done
}
trap cleanup EXIT INT TERM

read -r COMFY_URL COMFY_DIR < <("$VPY" -c 'from backend.core.config import load_settings as l; s=l(); print(s.comfyui.url, s.resolve(s.paths.comfyui_dir))')
COMFY_PORT="$(printf '%s' "$COMFY_URL" | sed -E 's#.*:([0-9]+).*#\1#')"

if [[ $START_COMFY -eq 1 ]]; then
  if curl -s --max-time 2 "$COMFY_URL/system_stats" >/dev/null 2>&1; then
    echo "✔ ComfyUI läuft bereits ($COMFY_URL)"
  elif [[ -f "$COMFY_DIR/main.py" && -x "$COMFY_DIR/.venv/bin/python" ]]; then
    ARGS="$("$VPY" scripts/setup/comfyui_args.py)"
    echo "→ starte ComfyUI ($COMFY_DIR, Port $COMFY_PORT ${ARGS:+, $ARGS}) – Log: data/logs/comfyui.log"
    # shellcheck disable=SC2086
    (cd "$COMFY_DIR" && exec .venv/bin/python main.py --listen 127.0.0.1 --port "$COMFY_PORT" $ARGS) >> data/logs/comfyui.log 2>&1 &
    PIDS+=($!)
    for _ in $(seq 1 90); do
      curl -s --max-time 1 "$COMFY_URL/system_stats" >/dev/null 2>&1 && { echo "✔ ComfyUI bereit"; break; }
      sleep 1
    done
  else
    echo "! ComfyUI nicht installiert (./setup.sh) und nicht erreichbar – Generierung nicht verfügbar, Verarbeitung (FFmpeg/Blender/Remotion) schon."
  fi
fi

if [[ $DEV -eq 1 ]]; then
  (cd apps/dashboard && npm run dev -- --host 127.0.0.1) >> data/logs/dashboard-dev.log 2>&1 &
  PIDS+=($!)
  echo "→ Dashboard-Dev-Server: http://127.0.0.1:5173"
fi

echo "→ Backend & Dashboard: http://${HOST:-127.0.0.1}:${PORT:-8420}  (Strg+C beendet alles)"
"$VPY" -m backend.cli serve ${HOST:+--host "$HOST"} ${PORT:+--port "$PORT"}
