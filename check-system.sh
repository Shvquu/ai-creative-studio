#!/usr/bin/env bash
# AI Creative Studio – system check (Linux/macOS). Works before and after setup.
# Before setup: shell-level checks. After setup: full hardware report + provider health.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
have() { command -v "$1" >/dev/null 2>&1; }
row() { printf '  %-14s %s\n' "$1" "$2"; }

echo "== System =="
row "OS" "$(uname -srm)"
if [[ "$(uname)" == "Darwin" ]]; then
  row "CPU" "$(sysctl -n machdep.cpu.brand_string 2>/dev/null) ($(sysctl -n hw.ncpu) Threads)"
  row "RAM" "$(( $(sysctl -n hw.memsize) / 1073741824 )) GB"
else
  row "CPU" "$(grep -m1 'model name' /proc/cpuinfo 2>/dev/null | cut -d: -f2 | xargs) ($(nproc) Threads)"
  row "RAM" "$(awk '/MemTotal/ {printf "%.1f GB", $2/1048576}' /proc/meminfo)"
fi
row "Speicher" "$(df -h "$ROOT" | awk 'NR==2 {print $4 " frei von " $2}')"
if have nvidia-smi; then
  nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader | while read -r line; do row "GPU (NVIDIA)" "$line"; done
  row "CUDA" "$(nvidia-smi | grep -o 'CUDA Version: [0-9.]*' | cut -d' ' -f3)"
elif have rocm-smi; then
  row "GPU (AMD)" "$(rocm-smi --showproductname 2>/dev/null | grep -m1 'Card series' | cut -d: -f3 | xargs)"
elif [[ "$(uname)" == "Darwin" && "$(uname -m)" == "arm64" ]]; then
  row "GPU" "Apple Silicon (MPS, Unified Memory)"
else
  row "GPU" "keine unterstützte GPU erkannt → CPU-Modus"
fi

echo; echo "== Werkzeuge =="
for t in python3 git ffmpeg ffprobe node npm blender uv docker; do
  if have "$t"; then row "$t" "$("$t" --version 2>&1 | head -1 | cut -c1-70)"; else row "$t" "— nicht gefunden"; fi
done

if [[ -x .venv/bin/python ]]; then
  echo; echo "== Hardwareprofil & Empfehlungen =="
  .venv/bin/python -m backend.cli hardware --write-report | sed -n '5,40p'
  echo; echo "== Provider =="
  .venv/bin/python -m backend.cli check
  echo; echo "Report gespeichert: data/reports/hardware-report.md"
else
  echo; echo "Noch nicht eingerichtet → ./setup.sh ausführen."
fi
