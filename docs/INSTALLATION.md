# Installation

## Voraussetzungen

| Komponente | Pflicht | Version | Zweck |
|---|---|---|---|
| Python | ja | ≥ 3.10 (getestet 3.12, 3.13) | Backend, MCP-Server, ComfyUI |
| Git | ja (für ComfyUI) | beliebig | ComfyUI klonen |
| FFmpeg + FFprobe | ja | ≥ 6 (getestet 6.1.1) | Videoverarbeitung, Analyse |
| Node.js | empfohlen | ≥ 20 (getestet 22) | Dashboard-Build, Remotion |
| Blender | optional | ≥ 3.6 (getestet 4.0.2) | 3D-Visualisierungen |
| NVIDIA-Treiber | für GPU | aktuell; PyTorch cu130 | Bild-/Videogenerierung |
| Speicherplatz | ja | ≥ 10 GB (Low) · 50 GB (Mid) · 120 GB (High) | Modelle |

`uv` (https://docs.astral.sh/uv/) wird automatisch genutzt, wenn installiert (deutlich schneller als pip).

## Linux / macOS

```bash
./check-system.sh       # zeigt Hardware, Werkzeuge, später auch Profil + Provider
./setup.sh              # interaktiv
```

`setup.sh` erledigt in 8 Schritten:

1. Voraussetzungen prüfen; FFmpeg auf Wunsch per apt/dnf/brew installieren
2. `.venv` anlegen, Projekt + Abhängigkeiten installieren (optional `rembg`)
3. `.env` aus `.env.example` anlegen (bestehende wird **nie** überschrieben), Verzeichnisse anlegen
4. Hardware analysieren → `data/reports/hardware-report.md`
5. ComfyUI nach `engines/comfyui/ComfyUI` klonen, eigenes venv, **PyTorch passend zur Hardware**
   (CUDA cu130, ROCm 7.2, macOS-Standard/MPS oder CPU – laut ComfyUI `docs/installation.md`)
6. Dashboard bauen, Remotion installieren (fragt; Lizenzhinweis)
7. Claude-Code-Integration anzeigen (`.mcp.json`, Agents, Skills)
8. `python -m backend.cli check`, optional Unit-Tests und Modell-Downloads

Optionen: `--yes` (kleine Schritte ohne Rückfrage – lädt **nie** Modelle), `--skip-comfyui`, `--skip-node`,
`--cpu` (CPU-PyTorch erzwingen), `--with-models`. Das Skript ist idempotent: erneutes Ausführen ergänzt nur Fehlendes.

Start:

```bash
./start.sh              # ComfyUI (falls lokal installiert) + Backend/Dashboard
./start.sh --no-comfyui # eigene ComfyUI-Instanz verwenden
./start.sh --dev        # zusätzlich Vite-Dev-Server auf :5173
```

## Windows

```powershell
powershell -ExecutionPolicy Bypass -File .\check-system.ps1
powershell -ExecutionPolicy Bypass -File .\setup.ps1      # -Yes -SkipComfyUI -SkipNode -Cpu -WithModels
powershell -ExecutionPolicy Bypass -File .\start.ps1      # -NoComfyUI -Dev
```

Besonderheiten:

* Fehlende Programme (Python, Git, FFmpeg, Node.js) können per `winget` installiert werden (Rückfrage).
* Der MCP-Server wird in `.mcp.json` über `${ACS_PYTHON:-.venv/bin/python}` gestartet. `setup.ps1` setzt dafür
  (nach Rückfrage) die Benutzer-Umgebungsvariable `ACS_PYTHON` auf `.venv\Scripts\python.exe`.
* AMD-/Intel-GPUs unter Windows sind nur eingeschränkt nutzbar (Profil `low`); NVIDIA wird voll unterstützt.
* Alternative zu ComfyUI per Skript: **ComfyUI Desktop** (https://www.comfy.org/download) installieren und
  `ACS__COMFYUI__URL` in `.env` auf dessen Adresse setzen (Standard `http://127.0.0.1:8000` bei Desktop – im
  ComfyUI-Fenster unter *Settings → Server-Config* prüfen). Modelle dann mit
  `scripts\models\download_models.py --models-dir <ComfyUI-Desktop-Modellordner>` laden.

## Bestehende ComfyUI-Installation nutzen

```ini
# .env
ACS__COMFYUI__URL=http://127.0.0.1:8188
ACS__PATHS__COMFYUI_DIR=D:/ComfyUI          # nur für start.sh/start.ps1 und den Modell-Downloader
```

`python -m backend.cli validate-templates` prüft, ob alle Templates zu Ihrer ComfyUI-Version passen.

## Docker (optional)

```bash
docker compose up -d studio                 # Backend + Dashboard; nutzt ComfyUI auf dem Host
docker compose --profile gpu up -d          # zusätzlich ComfyUI mit NVIDIA-GPU (NVIDIA Container Toolkit nötig)
```

Modelle liegen auf dem Host in `engines/comfyui/models` (`download_models.py --models-dir engines/comfyui/models`).
Blender und Remotion sind im Container nicht enthalten (nativ installieren).

## Konfiguration

Reihenfolge (später gewinnt): `configs/studio.yaml` → `configs/studio.local.yaml` (Dashboard → Settings schreibt hierhin)
→ `.env` → Umgebungsvariablen `ACS__ABSCHNITT__SCHLÜSSEL`.

| Datei | Inhalt |
|---|---|
| `configs/studio.yaml` | Server, Pfade, ComfyUI, FFmpeg, Jobs, Kosten, Qualität |
| `configs/providers.yaml` (+ `.local.yaml`) | Provider-Registry (local/cloud, Kosten, aktiviert, Rollen) |
| `configs/models.yaml` | Modellkatalog (URLs, Größen, Lizenzen, VRAM) |
| `configs/hardware_profiles.yaml` | Profile low/mid/high |

Wichtige Variablen: `ACS_API_TOKEN` (API-Token, Pflicht wenn das Backend nicht nur auf localhost lauscht),
`ACS__HARDWARE__PROFILE`, `ACS__COMFYUI__URL`, `HF_TOKEN` (nur für „gated“ Modelle beim Download).

## Installation überprüfen

```bash
.venv/bin/python -m backend.cli check        # alle Provider mit Status
.venv/bin/python -m pytest -q                # Test-Suite
curl http://127.0.0.1:8420/api/health
```

In Claude Code: `/mcp` zeigt den Server `ai-creative-studio` als verbunden; das Tool `run_smoke_test` prüft
ComfyUI ohne Modelle.
