#!/usr/bin/env bash
# AI Creative Studio – setup for Linux and macOS.
#
# Idempotent: re-running only adds what is missing and never overwrites existing
# configuration (.env, configs/*.local.yaml). Large downloads (ComfyUI + PyTorch,
# models) are confirmed individually.
#
# Usage: ./setup.sh [--yes] [--skip-comfyui] [--skip-node] [--cpu] [--with-models]
#   --yes          accept all small/safe steps without asking (NEVER downloads models)
#   --skip-comfyui do not install ComfyUI (e.g. you already run one – set ACS__COMFYUI__URL)
#   --skip-node    skip dashboard build and Remotion
#   --cpu          install CPU-only PyTorch for ComfyUI
#   --with-models  offer the recommended models for this hardware at the end
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

YES=0; SKIP_COMFY=0; SKIP_NODE=0; CPU=0; WITH_MODELS=0
for arg in "$@"; do
  case "$arg" in
    --yes) YES=1 ;;
    --skip-comfyui) SKIP_COMFY=1 ;;
    --skip-node) SKIP_NODE=1 ;;
    --cpu) CPU=1 ;;
    --with-models) WITH_MODELS=1 ;;
    -h|--help) sed -n '2,16p' "$0"; exit 0 ;;
    *) echo "Unbekannte Option: $arg"; exit 2 ;;
  esac
done

c_ok() { printf '\033[32m✔\033[0m %s\n' "$*"; }
c_warn() { printf '\033[33m!\033[0m %s\n' "$*"; }
c_err() { printf '\033[31m✘\033[0m %s\n' "$*"; }
step() { printf '\n\033[1m== %s ==\033[0m\n' "$*"; }
ask() {  # ask "question" default(y|n)
  local q="$1" def="${2:-n}" reply
  if [[ $YES -eq 1 ]]; then [[ "$def" == "y" ]]; return; fi
  local hint="[j/N]"; [[ "$def" == "y" ]] && hint="[J/n]"
  read -r -p "$q $hint " reply || reply=""
  reply="${reply:-$def}"
  [[ "$reply" =~ ^([jJyY]|ja|yes)$ ]]
}
have() { command -v "$1" >/dev/null 2>&1; }

# ---------------------------------------------------------------- 1. prerequisites
step "1/8 Voraussetzungen"
PY=""
for candidate in python3.13 python3.12 python3.11 python3.10 python3 python; do
  if have "$candidate" && "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)' 2>/dev/null; then
    PY="$candidate"; break
  fi
done
if [[ -z "$PY" ]] && ! have uv; then
  c_err "Python ≥ 3.10 nicht gefunden. Installieren: https://www.python.org/downloads/ (oder 'uv': https://docs.astral.sh/uv/)"
  exit 1
fi
[[ -n "$PY" ]] && c_ok "Python: $($PY --version 2>&1)"
have uv && c_ok "uv: $(uv --version)"
have git && c_ok "git: $(git --version)" || c_warn "git fehlt (für ComfyUI-Installation nötig)"

if have ffmpeg && have ffprobe; then
  c_ok "FFmpeg: $(ffmpeg -version | head -1 | cut -d' ' -f3)"
else
  c_warn "FFmpeg fehlt (Pflicht für Videoverarbeitung)."
  if [[ "$(uname)" == "Darwin" ]] && have brew; then
    ask "FFmpeg mit Homebrew installieren (brew install ffmpeg)?" y && brew install ffmpeg
  elif have apt-get; then
    ask "FFmpeg mit apt installieren (sudo apt-get install -y ffmpeg)?" y && sudo apt-get install -y ffmpeg
  elif have dnf; then
    ask "FFmpeg mit dnf installieren (sudo dnf install -y ffmpeg)?" y && sudo dnf install -y ffmpeg
  else
    c_warn "Bitte FFmpeg manuell installieren: https://ffmpeg.org/download.html"
  fi
fi
NODE_OK=0
if have node && node -e 'process.exit(parseInt(process.versions.node) >= 20 ? 0 : 1)'; then
  NODE_OK=1; c_ok "Node.js: $(node --version)"
else
  c_warn "Node.js ≥ 20 fehlt – Dashboard-Build und Remotion werden übersprungen (https://nodejs.org)."
fi
have blender && c_ok "Blender: $(blender --version 2>/dev/null | head -1)" || c_warn "Blender nicht gefunden – 3D-Workflows deaktiviert (optional, https://www.blender.org/download/)."

# ---------------------------------------------------------------- 2. python env
step "2/8 Python-Umgebung (.venv)"
if [[ ! -x .venv/bin/python ]]; then
  if have uv; then uv venv --python ">=3.10" .venv; else "$PY" -m venv .venv; fi
  c_ok ".venv erstellt"
else
  c_ok ".venv vorhanden"
fi
VPY="$ROOT/.venv/bin/python"
if have uv; then
  VIRTUAL_ENV="$ROOT/.venv" uv pip install -q -e ".[dev]"
else
  "$VPY" -m pip install -q --upgrade pip
  "$VPY" -m pip install -q -e ".[dev]"
fi
c_ok "Python-Abhängigkeiten installiert"
if ! "$VPY" -c "import rembg" 2>/dev/null; then
  if ask "Optional: Hintergrundentfernung (rembg, ~200 MB inkl. onnxruntime) installieren?" n; then
    if have uv; then VIRTUAL_ENV="$ROOT/.venv" uv pip install -q -e ".[rembg]"; else "$VPY" -m pip install -q -e ".[rembg]"; fi
    c_ok "rembg installiert (lädt beim ersten Aufruf ein Modell, ~170 MB)"
  fi
fi

# ---------------------------------------------------------------- 3. config
step "3/8 Konfiguration"
if [[ -f .env ]]; then c_ok ".env vorhanden (unverändert)"; else cp .env.example .env; c_ok ".env aus .env.example erstellt"; fi
"$VPY" - <<'PYEOF'
from backend.core.config import load_settings
s = load_settings(); s.ensure_dirs()
print("✔ Verzeichnisse bereit:", s.assets_dir, s.data_dir)
PYEOF

# ---------------------------------------------------------------- 4. hardware
step "4/8 Hardware-Analyse"
"$VPY" -m backend.cli hardware --write-report | sed -n '1,14p'
PROFILE_JSON="$("$VPY" -m backend.cli hardware --json)"
ACCEL="$(printf '%s' "$PROFILE_JSON" | "$VPY" -c 'import json,sys; print(json.load(sys.stdin)["decision"]["accelerator"])')"
c_ok "Vollständiger Report: data/reports/hardware-report.md (Beschleuniger: $ACCEL)"

# ---------------------------------------------------------------- 5. ComfyUI
step "5/8 ComfyUI"
COMFY_DIR="$("$VPY" -c 'from backend.core.config import load_settings as l; s=l(); print(s.resolve(s.paths.comfyui_dir))')"
if [[ $SKIP_COMFY -eq 1 ]]; then
  c_warn "übersprungen (--skip-comfyui). Eigene Instanz: ACS__COMFYUI__URL in .env setzen."
elif [[ -f "$COMFY_DIR/main.py" ]]; then
  c_ok "ComfyUI vorhanden: $COMFY_DIR"
  if [[ -d "$COMFY_DIR/.git" ]] && ask "ComfyUI aktualisieren (git pull + requirements)?" n; then
    git -C "$COMFY_DIR" pull --ff-only && "$COMFY_DIR/.venv/bin/python" -m pip install -q -r "$COMFY_DIR/requirements.txt"
  fi
else
  TORCH_ARGS="$("$VPY" scripts/setup/torch_index.py $([[ $CPU -eq 1 ]] && echo --cpu))"
  echo "ComfyUI wird nach $COMFY_DIR installiert (git clone + eigenes venv)."
  echo "PyTorch: pip install $TORCH_ARGS"
  echo "Download: ca. 1 GB (CPU) bis 4 GB (CUDA/ROCm) – ohne Modelle."
  if ask "ComfyUI jetzt installieren?" y; then
    git clone --depth 1 https://github.com/Comfy-Org/ComfyUI.git "$COMFY_DIR"
    if have uv; then uv venv --python ">=3.10" "$COMFY_DIR/.venv"; else "$PY" -m venv "$COMFY_DIR/.venv"; fi
    CPY="$COMFY_DIR/.venv/bin/python"
    # shellcheck disable=SC2086
    if have uv; then VIRTUAL_ENV="$COMFY_DIR/.venv" uv pip install $TORCH_ARGS; else "$CPY" -m pip install --upgrade pip && "$CPY" -m pip install $TORCH_ARGS; fi
    if have uv; then VIRTUAL_ENV="$COMFY_DIR/.venv" uv pip install -r "$COMFY_DIR/requirements.txt"; else "$CPY" -m pip install -r "$COMFY_DIR/requirements.txt"; fi
    c_ok "ComfyUI installiert"
  else
    c_warn "ComfyUI nicht installiert – Bild-/Videogenerierung erst nach Installation verfügbar."
  fi
fi

# ---------------------------------------------------------------- 6. node projects
step "6/8 Dashboard & Remotion"
if [[ $SKIP_NODE -eq 1 || $NODE_OK -eq 0 ]]; then
  c_warn "übersprungen"
else
  (cd apps/dashboard && npm install --no-fund --no-audit --loglevel=error && npm run build --silent) && c_ok "Dashboard gebaut (apps/dashboard/dist)"
  if [[ -d engines/remotion/node_modules/@remotion/cli ]]; then
    c_ok "Remotion-Abhängigkeiten vorhanden"
  elif ask "Remotion (Motion Graphics) installieren? ~300 MB inkl. Headless-Chrome. Lizenz: kostenlos für Einzelpersonen/Firmen ≤ 3 Personen." y; then
    (cd engines/remotion && npm install --no-fund --no-audit --loglevel=error && npx remotion browser ensure) && c_ok "Remotion bereit"
  fi
fi

# ---------------------------------------------------------------- 7. claude code
step "7/8 Claude Code (MCP, Agents, Skills)"
c_ok ".mcp.json registriert den MCP-Server 'ai-creative-studio' (Python: .venv/bin/python)"
c_ok "$(ls .claude/agents | wc -l | tr -d ' ') Agents, $(ls -d .claude/skills/*/ | wc -l | tr -d ' ') Skills unter .claude/"
echo "  In Claude Code im Projektordner starten; der MCP-Server wird automatisch geladen (/mcp zeigt den Status)."

# ---------------------------------------------------------------- 8. verify
step "8/8 Überprüfung"
"$VPY" -m backend.cli check || c_warn "Prüfung meldet Probleme (siehe oben)"
if ask "Kurzen Testlauf der Test-Suite ausführen (~1 Minute)?" n; then
  "$VPY" -m pytest -q -x tests/unit
fi
if [[ $WITH_MODELS -eq 1 ]] || ask "Empfohlene Modelle für dieses System jetzt anzeigen/herunterladen (jede Datei wird einzeln bestätigt)?" n; then
  "$VPY" scripts/models/download_models.py --recommended --comfyui-dir "$COMFY_DIR" || true
else
  echo "Modelle später: .venv/bin/python scripts/models/download_models.py --list"
fi

printf '\n\033[1mFertig.\033[0m Starten mit: ./start.sh  →  http://127.0.0.1:8420\n'
