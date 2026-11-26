# Projektstatus

Stand: 2026-11-26 · Entwicklungsumgebung: Cloud-Container **ohne GPU** (4 vCPU, 15,7 GB RAM, Ubuntu 24.04),
ComfyUI 0.46.0 (CPU), FFmpeg 6.1.1, Blender 4.0.2, Node 22, Remotion 4.0.547.

Legende: ✅ erfüllt · ⚠️ erfüllt mit Einschränkung · ❌ nicht umgesetzt

## Definition of Done

| Kriterium | Status | Nachweis |
|---|---|---|
| Hardware wird automatisch erkannt | ✅ | `backend/core/hardware.py`; `check-system.sh/.ps1`; Tests `test_select_profile` (10 Konstellationen) |
| Passendes Hardwareprofil wird ermittelt | ✅ | low/mid/high + manueller Override; hier: `low` (CPU) |
| ComfyUI ist integriert | ✅ | HTTP + WebSocket, Upload, Download, Abbruch – live getestet |
| Mindestens ein Bildmodell lokal ausführbar | ✅ | **SD 1.5 + LCM real auf CPU generiert** (512² in ~50 s), automatisch für Profil `low` gewählt |
| Video-Workflow integriert, sofern Hardware es zulässt | ⚠️ | Wan 2.1/2.2-Templates vorhanden und gegen ComfyUI validiert; **ohne GPU hier nicht ausführbar** → Ken-Burns-Fallback live getestet |
| FFmpeg funktioniert | ✅ | Render, Übergänge, Audio, Untertitel, Formate, Interpolation, Analyse – live getestet |
| Provider-Architektur funktioniert | ✅ | 6 Provider, 5 Rollen; Mock-Cloud-Provider in Tests registriert |
| MCP-Schnittstelle funktioniert | ✅ | 51 Tools; Tests über echten MCP-Client; Claude Code lädt den Server über `.mcp.json` |
| Agents vorhanden und dokumentiert | ✅ | 7 Agents in `.claude/agents/` (Frontmatter + Tool-Allowlists validiert) |
| Alle Skills implementiert | ✅ | 13 Skills mit allen Pflichtabschnitten; `scripts/maintenance/validate_claude_config.py` |
| Wichtigste Workflows ausführbar | ✅ | 14 Workflows; Bild, Ken-Burns-Video, Storyboard (Fallback), Brand Kit, Thumbnail, Intro, 3D live ausgeführt |
| Dashboard funktioniert | ✅ | 7 Bereiche; Playwright-Smoke-Test 17/17 gegen echtes Backend |
| Dateien werden gespeichert und wiedergefunden | ✅ | Asset-Index + Sidecars, Suche/Filter/Tags/Favoriten, Rescan |
| Kostenkontrolle funktioniert | ✅ | Budget, Limit pro Job, HMAC-Bestätigung, Ledger; über API, MCP und Dashboard getestet |
| Tests erfolgreich | ✅ | siehe unten |
| Installation dokumentiert | ✅ | `docs/INSTALLATION.md`; `setup.sh` in frischem Klon erfolgreich durchgelaufen |

## Feature-Matrix

| Bereich | Funktion | Implementiert | Automatisch getestet | Live hier ausgeführt |
|---|---|---|---|---|
| Bild | Text→Bild (Checkpoint, SD 1.5/LCM) | ✅ | ✅ | ✅ echtes Modell |
| Bild | SDXL, FLUX.1, FLUX.2 Klein, Z-Image Turbo | ✅ | ✅ Template-Validierung | ⚠️ GPU nötig – Graphen von ComfyUI akzeptiert (nur „Modell fehlt“) |
| Bild | Bild→Bild, Inpainting, Outpainting | ✅ | ✅ Templates + Provider | ⚠️ Graphen validiert, nicht mit echtem Modell ausgeführt |
| Bild | ControlNet (SD 1.5 Canny/Scribble) | ✅ | ✅ | ✅ Canny mit echtem Modell (Scribble-Pfad = gleiche Graph-Logik ohne Canny-Node) |
| Bild | LoRAs, Seeds, Batch, Stil-Presets | ✅ | ✅ | ✅ (LCM-LoRA) |
| Bild | Upscaling Real-ESRGAN / Lanczos-Fallback | ✅ | ✅ | ✅ echtes Modell |
| Bild | Freistellen (rembg, optional) | ✅ | ✅ | ✅ (U²-Net, RGBA-Ausgabe) |
| Bild | Text-Overlay, Formate, Palette, Kontaktbogen | ✅ | ✅ | ✅ |
| Video | Text→Video / Bild→Video (Wan 2.1 1.3B, Wan 2.2 5B/14B) | ✅ | ✅ Template-Validierung | ⚠️ GPU nötig |
| Video | KI-Video-Upscaling (ESRGAN pro Frame) + Fallback | ✅ | ✅ | ✅ echtes Modell, FPS + Audio erhalten; Lanczos-Fallback ✅ |
| Video | Frame-Interpolation | ✅ FFmpeg `minterpolate` | ✅ | ✅ |
| Video | Video→Video | ❌ | – | – (Interface vorhanden, liefert `capability_not_supported`) |
| Video | Character Consistency | ⚠️ | – | nur über Referenzbild (I2V) + feste Seeds; kein Identitätsmodell |
| Schnitt | Timeline, Übergänge, Audio, Untertitel, Formate, Kompression, Frames | ✅ | ✅ | ✅ |
| Motion | Remotion (5 Kompositionen) + FFmpeg-Titelkarten-Fallback | ✅ | ✅ | ✅ |
| 3D | Blender Turntable, 3D-Text, SVG-Logo | ✅ | ✅ | ✅ (Cycles CPU) |
| Branding | Palette, Typografie, Logos, Guidelines HTML/MD | ✅ | ✅ | ✅ (Logos mit Mock-Provider) |
| QA | Bild-/Videoanalyse, Presets, Reports | ✅ | ✅ | ✅ |
| Infrastruktur | Job-Queue: Retry, Abbruch, Timeout, Recovery, SSE | ✅ | ✅ | ✅ (inkl. ComfyUI-Abbruch) |
| Infrastruktur | Docker | ✅ | – | ⚠️ Studio-Image gebaut und gestartet (nur mit Proxy-CA dieser Sandbox); GPU-ComfyUI-Image nicht gebaut |
| Setup | `setup.sh`, `start.sh`, `check-system.sh` | ✅ | – | ✅ in frischem Klon (inkl. ComfyUI + PyTorch CPU) |
| Setup | `setup.ps1`, `start.ps1`, `check-system.ps1` | ✅ | – | ⚠️ nur mit PowerShell 7 geparst, **nicht unter Windows ausgeführt** |

## Live-Tests in dieser Umgebung (echte Engines)

| Test | Ergebnis |
|---|---|
| MCP → API → Queue → ComfyUI → SD 1.5 + LCM (CPU) | 512² in 52 s, QA-Score 100, Bild visuell geprüft |
| Real-ESRGAN x4 Upscale (CPU) | 512² → 1024² in 31 s |
| ControlNet Canny (SD 1.5 + LCM, CPU) | 384² mit Kreis-Steuerbild; Workflow-Sidecar enthält Canny/ControlNet-Nodes |
| ESRGAN-Video-Upscale über ComfyUI (`LoadVideo` → `GetVideoComponents` → `CreateVideo`) | 96×64 → 192×128, 24 fps + Audio erhalten |
| rembg-Freistellung | ✅ (Modell lädt beim ersten Aufruf) |
| ComfyUI Smoke-Test (Bild + MP4 ohne Modell) | ✅ |
| Abbruch eines laufenden ComfyUI-Jobs | ✅ (Queue-Löschung + Interrupt) |
| Alle 16 Templates gegen `/object_info` (Nodes, Inputs, Enums) | ✅ |
| Alle Templates an `/prompt` gesendet | ✅ nur „Modelldatei fehlt“, keine Strukturfehler |
| Blender: Turntable, SVG-Logo (Cycles CPU) | ✅ (Fallback ohne OIDN-Denoiser greift) |
| Remotion: TitleIntro, KineticText | ✅ |
| Workflows mit Mock-Generator + echtem FFmpeg/Blender/Remotion | text-to-image, kenburns-slideshow, storyboard (→ Fallback), youtube-thumbnail, brand-kit, title-intro, product-turntable-3d ✅ |
| Dashboard (Playwright, Chromium) | 17/17 Prüfungen, Desktop + Mobil |

Gefundene und behobene Fehler durch Live-Tests: Race-Condition (ComfyUI meldet `execution_success` vor dem
History-Eintrag), Katalog-Auflösung SD 1.5 vs. LCM-Variante, Jinja-Namenskollision (`values`/`items`),
Filter-Quoting bei FFmpeg-Titelkarten, SVG-Skalierung/Z-Fighting im 3D-Logo, Blender ohne OIDN.

## Nicht umgesetzt / bewusst ausgelassen

| Thema | Grund / Alternative |
|---|---|
| Whisper (Speech-to-Text) | evaluiert, nicht integriert; Untertitel werden als Cue-Liste/SRT übergeben. Nächster Schritt: `faster-whisper` als optionale Operation `process.transcribe` |
| RIFE-Frame-Interpolation | benötigt Custom-Nodes; stattdessen FFmpeg `minterpolate` (bewegungskompensiert, CPU) |
| Video→Video (z. B. Wan VACE) | hoher VRAM-Bedarf, nicht testbar; Interface vorhanden |
| Cloud-Provider | bewusst keiner mitgeliefert (kostenfreier Kern); Framework + Kostenkontrolle mit Mock-Cloud-Provider getestet |
| GGUF-Quantisierung | ComfyUI rät inzwischen davon ab (int8 „convrot“/fp8 bevorzugt) – Katalog nutzt fp8/bf16-Dateien |
| ComfyUI-Manager / Custom Nodes | nicht nötig: alle Templates nutzen ausschließlich Kern-Nodes |

## Bekannte Einschränkungen

* **Ihre Hardware wurde nicht analysiert** (Rechner war aus der Cloud-Session nicht erreichbar). `check-system.sh/.ps1`
  auf dem Zielrechner ausführen; das Profil wird dort automatisch gewählt.
* GPU-Pfade (CUDA/ROCm/MPS), Wan-Videos und große Bildmodelle sind gegen ComfyUI validiert, aber nicht ausgeführt.
  VRAM-/Zeitangaben im Katalog sind Richtwerte aus Modellkarten/ComfyUI-Dokumentation, keine eigenen Messungen.
* Windows-Skripte sind syntaktisch geprüft, aber nicht auf Windows gelaufen.
* Apple Silicon und AMD-Erkennung sind implementiert und per Unit-Test simuliert, nicht auf echter Hardware geprüft.
* Remotion: Lizenzpflicht für Firmen > 3 Mitarbeitende.

## Testergebnisse (2026-11-26)

| Lauf | Ergebnis |
|---|---|
| Vollständige Suite mit Live-ComfyUI (`ACS_TEST_COMFYUI_URL` gesetzt) | **111 bestanden** (Unit, Integration, API, MCP, SSE, FFmpeg, Blender, Remotion, ComfyUI live, echte Modelle) |
| Ohne Live-ComfyUI | Live-Modelltests werden übersprungen, Rest grün |
| Dashboard-Smoke-Test (Playwright) | 17/17 |
| `validate_claude_config.py` | 20 Dateien, keine Probleme |
| `ruff check`, `tsc --noEmit` (Dashboard, Remotion) | sauber |

## Tests ausführen

```bash
.venv/bin/python -m pytest                                    # Kernsuite (Live-ComfyUI-Tests werden übersprungen)
ACS_TEST_COMFYUI_URL=http://127.0.0.1:8188 .venv/bin/python -m pytest   # inkl. Live-Tests
node apps/dashboard/e2e/smoke.mjs http://127.0.0.1:8420
.venv/bin/python scripts/maintenance/validate_claude_config.py
```
