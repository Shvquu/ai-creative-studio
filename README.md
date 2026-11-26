# AI Creative Studio

**Lokales, kostenloses und erweiterbares KI-Produktionsstudio für Bilder, Videos, Motion Graphics, 3D und Branding – orchestriert von Claude Code.**

Claude Code arbeitet als Creative Director: Es versteht kreative Aufträge, plant Szenen, wählt passend zur Hardware
Modelle und Workflows aus, startet die Generierung in lokalen Engines und prüft die Ergebnisse. Die Medien selbst
entstehen ausschließlich lokal – mit **ComfyUI** (SD 1.5, SDXL, FLUX, Z-Image, Wan 2.x), **FFmpeg**, **Blender** und
**Remotion**. Keine Pflicht-Cloud, keine versteckten Kosten, nach den Downloads offline nutzbar.

```text
Claude Code ──MCP──▶ mcp_server ──HTTP──▶ Backend (FastAPI) ──▶ ComfyUI · FFmpeg · Blender · Remotion
  Agents & Skills                           Jobs · Assets · QA · Kostenkontrolle
                         Dashboard (React) ──┘
```

## Funktionen

| Bereich | Umfang |
|---|---|
| Bilder | Text→Bild, Bild→Bild, Inpainting, Outpainting, Real-ESRGAN-Upscaling, Freistellen (rembg), Varianten, LoRAs, Stil-Presets, Seeds |
| Videos | Text→Video & Bild→Video (Wan 2.1 1.3B, Wan 2.2 5B/14B), Storyboards, Frame-Interpolation; **CPU-Fallback** mit Ken-Burns-Kamerafahrten |
| Schnitt | Timeline-Rendering, 20 Übergänge (xfade), Musik mit Lautheitsnormalisierung, Untertitel (eingebrannt/Spur), Formatwandlung 16:9 ↔ 9:16 ↔ 1:1, Kompression |
| Motion & 3D | Remotion-Intros, Bauchbinden, Social-Clips, kinetische Typo; Blender-Produkt-Turntables, 3D-Text, 3D-Logos aus SVG |
| Branding | Farbpaletten mit WCAG-Kontrast, Schriftpaarungen (freie Fonts), Logo-Konzepte, Brand Guidelines (HTML + Markdown) |
| Qualität | Schärfe, Belichtung, Rauschen, Leerbild, Seitenverhältnis, Plattform-Presets, schwarze/eingefrorene Frames, Flackern, Berichte |
| Infrastruktur | Hardware-Erkennung & Profile, Async-Job-Queue (Retry/Abbruch/Fortschritt), Asset-Bibliothek mit reproduzierbaren Metadaten, Kostenkontrolle, 50 MCP-Tools, Dashboard |

## Schnellstart

```bash
git clone <repo> ai-creative-studio && cd ai-creative-studio
./check-system.sh          # Hardware & Werkzeuge prüfen
./setup.sh                 # Einrichtung (fragt vor großen Downloads)
./start.sh                 # ComfyUI + Backend + Dashboard → http://127.0.0.1:8420
```

Windows (PowerShell):

```powershell
powershell -ExecutionPolicy Bypass -File .\check-system.ps1
powershell -ExecutionPolicy Bypass -File .\setup.ps1
powershell -ExecutionPolicy Bypass -File .\start.ps1
```

Modelle (einzeln bestätigt, passend zur Hardware vorgeschlagen):

```bash
.venv/bin/python scripts/models/download_models.py --list
.venv/bin/python scripts/models/download_models.py --recommended
```

Dann Claude Code im Projektordner starten – der MCP-Server `ai-creative-studio`, 7 Agents und 13 Skills
werden automatisch geladen. Beispiel: *„Erstelle ein 20-Sekunden-Produktvideo für unsere neue Trinkflasche im
9:16-Format mit Musik und Untertiteln.“*

## Hardwareprofile

| Profil | Kriterien | Bild | Video |
|---|---|---|---|
| Low-End | CPU-only, < 8 GB VRAM | SD 1.5 + LCM (≈ 1 min/Bild auf CPU) | Ken-Burns-Fallback; Wan 2.1 1.3B ab 6 GB VRAM |
| Mid-Range | 8–15 GB VRAM | FLUX.2 Klein 4B, SDXL, Z-Image Turbo | Wan 2.2 TI2V 5B, Wan 2.1 1.3B |
| High-End | ≥ 16 GB VRAM + ≥ 32 GB RAM | Z-Image Turbo, FLUX.2 Klein, FLUX.1 schnell | Wan 2.2 I2V 14B (Lightning) |

Details: [docs/HARDWARE_ANALYSIS.md](docs/HARDWARE_ANALYSIS.md) · Modelle & Lizenzen: [docs/MODELS.md](docs/MODELS.md)

## Dokumentation

| Dokument | Inhalt |
|---|---|
| [docs/INSTALLATION.md](docs/INSTALLATION.md) | Installation (Linux, macOS, Windows, Docker), Konfiguration |
| [docs/USER_GUIDE.md](docs/USER_GUIDE.md) | Benutzerhandbuch: Dashboard, Claude Code, typische Aufträge |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Architektur, Provider-Interfaces, Entscheidungen, Sicherheit |
| [docs/WORKFLOWS.md](docs/WORKFLOWS.md) | Alle Workflows, eigene Workflows schreiben |
| [docs/MCP.md](docs/MCP.md) | MCP-Server und alle Tools |
| [docs/MODELS.md](docs/MODELS.md) | Modellkatalog, Lizenzen, eigene Modelle/Templates |
| [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) | Fehlerbehebung |
| [docs/STATUS.md](docs/STATUS.md) | Was implementiert, getestet und hardwarebedingt nicht verfügbar ist |
| [docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md) | Plan & Risiken |

## Tests

```bash
.venv/bin/python -m pytest                       # Kernsuite (Mock-Provider, echtes FFmpeg)
ACS_TEST_COMFYUI_URL=http://127.0.0.1:8188 .venv/bin/python -m pytest -m "live_comfyui or live_models or blender or remotion"
node apps/dashboard/e2e/smoke.mjs http://127.0.0.1:8420   # Dashboard im Browser (Playwright)
```

## Kosten & Lizenzen

Standardmäßig fallen **keine Kosten** an: Es sind ausschließlich lokale Provider aktiv. Cloud-Provider müssten
explizit hinzugefügt und aktiviert werden, benötigen ein Monatsbudget > 0 und eine Bestätigung pro Aktion.

Dieser Quellcode steht unter der MIT-Lizenz. Modelle und Drittprogramme haben eigene Lizenzen – insbesondere ist
**FLUX.1 [dev] nicht kommerziell nutzbar**, SD 1.5/SDXL unterliegen OpenRAIL-Nutzungsauflagen und **Remotion** ist
für Firmen mit mehr als 3 Mitarbeitenden lizenzpflichtig. Siehe [docs/MODELS.md](docs/MODELS.md).
