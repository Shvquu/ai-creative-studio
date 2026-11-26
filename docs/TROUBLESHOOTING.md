# Fehlerbehebung

Alle Fehler haben einen stabilen Code (API: `{"error": {"code", "message", "details"}}`, MCP: `[code] Meldung – Hinweis`).
Logs: `data/logs/studio.log` (Backend), `data/logs/mcp.log` (MCP-Server), `data/logs/comfyui.log` (ComfyUI über start.sh).

## Fehlercodes

| Code | Bedeutung | Lösung |
|---|---|---|
| `provider_unavailable` | ComfyUI nicht erreichbar (wird automatisch 1× wiederholt) | `./start.sh` startet ComfyUI mit; eigene Instanz → `ACS__COMFYUI__URL` prüfen; `curl $URL/system_stats` |
| `model_not_installed` | Modell(-datei) fehlt in ComfyUI | Meldung nennt die Dateien → `scripts/models/download_models.py --model <id>`; eigene Dateien in den richtigen Ordner (`checkpoints`, `diffusion_models`, `text_encoders`, `vae`, `loras`, `upscale_models`) |
| `hardware_insufficient` | Aufgabe passt nicht zur Hardware (z. B. KI-Video ohne GPU) | `details.fallback_workflow` nutzen (z. B. `videos/kenburns-slideshow`), kleineres Modell, niedrigere Auflösung |
| `generation_error` | ComfyUI-Ausführung fehlgeschlagen | `details.engine_error` lesen; bei OOM Auflösung/Frames senken, andere GPU-Programme schließen |
| `validation_error` | Ungültige Parameter / Workflow-Eingaben | Meldung nennt Feld; Schemas: `GET /docs` (OpenAPI) |
| `path_not_allowed` | Datei außerhalb von `assets/` | Datei nach `assets/references/` kopieren + `rescan_assets` bzw. Upload im Dashboard; weitere Ordner: `paths.extra_allowed_dirs` |
| `tool_not_found` | FFmpeg/Blender/npx fehlt | installieren oder Pfad setzen (`ACS__FFMPEG__FFMPEG_PATH`, `ACS__BLENDER__BLENDER_PATH`) |
| `timeout` | Zeitlimit überschritten (automatisch 1× wiederholt) | `comfyui.generation_timeout_s` / `jobs.default_timeout_s` erhöhen; kürzere Clips |
| `cost_confirmation_required` | Kostenpflichtiger Provider | Schätzung prüfen, bestätigen → erneut mit `confirm_token` |
| `budget_exceeded` / `provider_disabled` | Kein Budget / Provider aus | `costs.monthly_budget` setzen bzw. Provider aktivieren (nur bewusst!) |
| `interrupted` | Job lief beim Neustart des Backends | „Retry“ im Dashboard oder `retry_job` |
| `unauthorized` | `ACS_API_TOKEN` gesetzt, Token fehlt | Token im Dashboard (Settings) bzw. in der Umgebung des MCP-Servers setzen |

## Häufige Probleme

**ComfyUI startet nicht / „Torch not compiled with CUDA enabled“**
PyTorch passt nicht zur GPU. Im ComfyUI-venv neu installieren:
`engines/comfyui/ComfyUI/.venv/bin/python -m pip install --force-reinstall torch torchvision torchaudio --extra-index-url https://download.pytorch.org/whl/cu130`
(Befehle für ROCm/CPU: `python scripts/setup/torch_index.py`). Laut ComfyUI-README benötigen NVIDIA-GPUs ab der 20er-Serie cu130.

**Sehr langsame Generierung**
CPU-Modus? `python -m backend.cli hardware` zeigt das Profil. Auf CPU nur `sd15-lcm` (≈ 1 min für 512² bei 4 Kernen).
Keine „Performance-Flags“ wie `--lowvram` setzen – ComfyUI verwaltet VRAM selbst und rät davon ab.

**Out of Memory (VRAM)**
Auflösung/Frames reduzieren (Wan: weniger Frames, 480p statt 720p), kleineres Modell (`wan21-t2v-1.3b`, `sd15-lcm`),
andere GPU-Programme schließen. GPU-Jobs laufen bereits seriell (`jobs.gpu_concurrency: 1`).

**Modell wird nicht gefunden, obwohl heruntergeladen**
Ordner prüfen (`get_available_models` zeigt `missing_files`). ComfyUI Desktop nutzt einen eigenen Modellordner →
`download_models.py --models-dir <Pfad>`. Dateinamen müssen exakt dem Katalog entsprechen.

**Template passt nicht mehr nach ComfyUI-Update**
`python -m backend.cli validate-templates` listet unbekannte Nodes/Inputs/Enum-Werte. Template anpassen (siehe Skill `comfyui-workflows`).

**Blender rendert nicht / „Build without OpenImageDenoiser“**
Distributions-Builds (z. B. Ubuntu-Paket) haben teils kein OIDN – die Skripte rendern dann automatisch ohne Denoising
(Log: `ACS_INFO denoiser unavailable`). Für bessere Qualität Blender von blender.org verwenden. EEVEE braucht eine GPU/OpenGL –
im Headless-Betrieb `engine: CYCLES`.

**Remotion: „Abhängigkeiten fehlen“ / Browser-Download schlägt fehl**
`cd engines/remotion && npm install && npx remotion browser ensure`. Ohne Remotion fallen Intros/Outros automatisch
auf FFmpeg-Titelkarten zurück.

**Dashboard zeigt nur JSON-Hinweis statt Oberfläche**
Dashboard nicht gebaut: `cd apps/dashboard && npm install && npm run build`, dann Backend neu starten (das Backend
prüft beim Start, ob `apps/dashboard/dist` existiert).

**MCP-Server in Claude Code nicht verbunden**
`/mcp` in Claude Code prüfen. Python-Pfad: Linux/macOS `.venv/bin/python`, Windows `ACS_PYTHON` setzen.
Manuell testen: `.venv/bin/python -m mcp_server.server` (darf keine Fehlermeldung ausgeben, wartet auf stdin).
Backend muss laufen (`./start.sh`), sonst melden Tools „Backend nicht erreichbar“.

**Fehlende Schriftarten / Textdarstellung**
Für Text-Overlays werden Systemschriften gesucht (Inter, DejaVu, Arial, Segoe …). Linux: `sudo apt install fonts-dejavu fonts-inter`.

**Firmen-Proxy mit TLS-Inspektion (pip/npm/Docker-Builds schlagen mit „certificate verify failed“ fehl)**
Firmen-CA bereitstellen: `PIP_CERT`/`SSL_CERT_FILE` (Python), `NODE_EXTRA_CA_CERTS` (Node). Für Docker-Builds die CA per
`--build-context` einbinden und dieselben Variablen setzen. Niemals TLS-Prüfung deaktivieren.

**Speicherplatz**
Generierte Medien liegen in `assets/`, Cache/Thumbnails in `data/cache` (löschbar). `organize_assets` räumt auf
(immer erst Dry-Run).

## Diagnose-Befehle

```bash
./check-system.sh                                # Hardware, Werkzeuge, Profil, Provider
.venv/bin/python -m backend.cli check            # Provider-Gesundheit
.venv/bin/python -m backend.cli validate-templates
curl -s http://127.0.0.1:8420/api/system/status | python -m json.tool
.venv/bin/python -m pytest -q                    # Selbsttest
```
