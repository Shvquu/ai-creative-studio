# Architektur – AI Creative Studio

## 1. Überblick

```text
 ┌──────────────────────────── Claude Code (Orchestrator) ────────────────────────────┐
 │  .claude/agents (Creative Director, Image Designer, Video Director, …)             │
 │  .claude/skills (image-generation, video-editing, quality-control, …)              │
 └───────────────┬───────────────────────────────────────────────────────────────────┘
                 │ MCP (stdio)                         Browser
                 ▼                                        ▼
        ┌─────────────────┐   HTTP (localhost)   ┌──────────────────┐
        │  mcp_server/    │ ───────────────────▶ │  Dashboard       │ React/Vite (apps/dashboard)
        │  validierte     │                      │  served by API   │
        │  Tools          │                      └────────┬─────────┘
        └────────┬────────┘                               │ REST + SSE
                 └──────────────────┬─────────────────────┘
                                    ▼
 ┌──────────────────────────── backend (FastAPI, Python) ────────────────────────────┐
 │ api/            REST-Routen, SSE-Events, Fehler-Mapping, Token-Auth (optional)    │
 │ orchestration/  Studio-Fassade, Modellauswahl, Prompt-Builder, Job-Handler        │
 │ workflows/      YAML-Workflow-Engine (Schritte, Templates, Fortschritt)           │
 │ jobs/           Async-Job-Queue (GPU/CPU/Workflow-Pools), Retry, Cancel, SQLite   │
 │ providers/      ImageProvider · VideoProvider · ProcessingProvider ·              │
 │                 MotionProvider · Render3DProvider + Registry                      │
 │ assets/         Asset-Index (SQLite), Sidecar-Metadaten, Suche, Thumbnails        │
 │ quality/        Bild-/Videoanalyse, Auflösungsvalidierung, Reports                │
 │ core/           Config, Logging, Pfad-Schutz, Hardware, Kostenkontrolle, DB       │
 └──────┬───────────────┬──────────────┬──────────────┬──────────────┬───────────────┘
        ▼               ▼              ▼              ▼              ▼
    ComfyUI          FFmpeg/        Blender       Remotion       Pillow/numpy
  (HTTP + WS)       FFprobe       (headless)      (npx CLI)      (rembg opt.)
  SD/SDXL/FLUX/
  Z-Image/Wan
```

**Grundsatz:** Claude Code ist Orchestrator, nicht Generator. Alle Medien entstehen in lokalen
Engines. Das Backend ist die einzige Instanz, die Engines anspricht – MCP-Server und Dashboard
sind zwei Clients derselben API (eine Wahrheit für Jobs, Assets und Kosten).

## 2. Schichten und Verantwortlichkeiten

| # | Bereich | Modul | Verantwortung |
|---|---|---|---|
| 1 | AI Orchestration | `backend/orchestration`, `.claude/` | Modellauswahl nach Hardware, Prompt-Technik, Job-Handler, Agents & Skills |
| 2 | Image Generation | `backend/providers/comfyui/image.py` | Text→Bild, Bild→Bild, Inpaint, Outpaint, Upscale via ComfyUI-Templates |
| 3 | Video Generation | `backend/providers/comfyui/video.py` | Text→Video, Bild→Video (Wan 2.1/2.2) |
| 4 | Image Processing | `backend/providers/image_tools.py` | Lanczos-Upscale, Resize/Crop, Text-Overlay, Paletten, rembg |
| 5 | Video Processing | `backend/providers/ffmpeg.py` | Info, Convert, Trim, Merge+Transitions, Audio, Untertitel, Frames, Interpolation, Aspect |
| 6 | Motion Design | `backend/providers/remotion.py`, `engines/remotion` | React-basierte Motion Graphics |
| 7 | 3D Rendering | `backend/providers/blender.py`, `engines/blender/scripts` | Produkt-Turntables, 3D-Text (Cycles/EEVEE headless) |
| 8 | Asset Management | `backend/assets` | Index, Metadaten, Suche, Tags, Favoriten, Organisieren |
| 9 | Workflow Management | `backend/workflows`, `workflows/` | Mehrstufige Pipelines als YAML |
| 10 | Quality Assurance | `backend/quality` | Schärfe, Belichtung, Rauschen, Black/Freeze-Frames, Flicker, Reports |

## 3. Provider-Architektur

Alle Generatoren implementieren abstrakte Interfaces aus `backend/providers/base.py`:

```text
BaseProvider        get_capabilities() · get_models() · health() · close()
├─ ImageProvider    generate() · edit() · inpaint() · outpaint() · upscale() · remove_background()
├─ VideoProvider    generate() · image_to_video() · process() · upscale()
├─ ProcessingProvider  get_info() · convert() · render() · extract_frames() · add_audio()
│                      add_subtitles() · merge() · trim() · resize() · compress() · interpolate()
├─ MotionProvider   get_compositions() · render()
└─ Render3DProvider get_templates() · render()
```

* Nicht unterstützte Operationen werfen `CapabilityNotSupportedError` (kein stilles Ignorieren).
* `configs/providers.yaml` registriert Provider mit **Rollen** (`image`, `video`, `processing`, …)
  und Metadaten (local/cloud, Kostenmodell, API-Key-Pflicht, aktiviert). Ein Provider kann mehrere
  Rollen haben (ComfyUI: `image` + `video`, gemeinsamer HTTP-Client).
* **Neue Provider** = neue Klasse + YAML-Eintrag (`roles: {image: paket.modul:Klasse}`) – keine
  Änderungen an API, Queue oder MCP nötig.
* Lange Operationen erhalten einen `JobContext` (Fortschritt, Abbruch, Ausgabeverzeichnis).

### ComfyUI-Integration (verifiziert gegen ComfyUI 0.46.0)

| Zweck | Endpoint |
|---|---|
| Workflow einreihen | `POST /prompt {prompt, client_id, prompt_id}` |
| Fortschritt | `WS /ws?clientId=` – Events `progress`, `executing`, `execution_success`, `execution_error`, `execution_interrupted` |
| Ergebnis | `GET /history/{prompt_id}` → `outputs[node].images[]` (Videos mit `animated: [true]`) |
| Datei laden | `GET /view?filename&subfolder&type` |
| Upload | `POST /upload/image` (multipart) |
| Abbruch | `POST /interrupt {prompt_id}` · `POST /queue {delete: [id]}` |
| Modelle | `GET /models/{folder}` · `GET /object_info/{node}` |
| Status | `GET /system_stats` (RAM/VRAM, Version), `GET /queue` |

Workflows liegen als **API-Format-Templates** in `engines/comfyui/workflows/*.json` mit einem
`meta`-Block, der Parameter auf `[node_id, input]`-Ziele abbildet. Templates werden in Tests
strukturell geprüft und mit `scripts/maintenance/validate_comfy_templates.py` gegen
`/object_info` einer echten ComfyUI-Instanz validiert (Node-Klassen, Input-Namen, Enum-Werte).

## 4. Job-System

* Persistenz in SQLite (`data/studio.db`, WAL). Status: `queued → running → succeeded | failed | cancelled`
  (`retrying` zwischen Versuchen).
* Drei Ressourcen-Pools mit eigener Parallelität: **gpu** (Standard 1), **cpu** (2), **workflow** (2).
  Workflow-Schritte reservieren dieselben Semaphoren → kein Deadlock, keine VRAM-Überbuchung.
* **Retry:** automatische Wiederholung nur bei `retryable`-Fehlern (Provider nicht erreichbar, Timeout),
  exponentielles Backoff. Manuelles Retry per API.
* **Cancel:** wartende Jobs werden verworfen; laufende erhalten `CancelledError` → ComfyUI-Provider
  sendet `/interrupt` bzw. löscht den Prompt aus der Queue; FFmpeg/Blender-Prozesse werden beendet.
* **Timeout** pro Job (`jobs.default_timeout_s`, Generierung `comfyui.generation_timeout_s`).
* **Events** (Fortschritt, Statuswechsel) via Server-Sent Events `/api/events`.
* Nach Neustart: `running`-Jobs → `failed` („durch Neustart unterbrochen“, retry-fähig), `queued` werden fortgesetzt.

## 5. Asset-Management & Reproduzierbarkeit

* Ausgaben unter `assets/generated/YYYY-MM-DD/`, Uploads unter `assets/references/`,
  Exporte unter `assets/exports/`.
* Pro Datei ein **Sidecar** `<datei>.meta.json` mit Prompt, Negative Prompt, Seed, Modell,
  Provider, allen Parametern und – bei ComfyUI – dem **exakt ausgeführten Workflow-JSON**.
  Damit ist jede Generierung reproduzierbar, auch ohne Datenbank.
* SQLite-Index für Suche (Text, Tags, Typ, Projekt, Favoriten, Datum). `rescan` indiziert manuell
  hinzugefügte Dateien; `organize` verschiebt nach Regeln (Standard: Dry-Run).

## 6. Kostenkontrolle

```text
Anfrage → CostGuard.estimate() → kostenlos (local)? ──ja──▶ ausführen
                                    │nein
                                    ▼
             Provider aktiviert? API-Key gesetzt? Budget > 0 und nicht überschritten?
                                    │ja
                                    ▼
             402 + Schätzung + Bestätigungs-Token (HMAC, 10 min gültig)
                                    │ Benutzer bestätigt (UI-Dialog / Claude fragt nach)
                                    ▼
             erneute Anfrage mit Token → ausführen → Kosten im Ledger buchen
```

Jede Schätzung enthält Provider, Modell, Anzahl, Einzel-/Gesamtkosten und erwarteten
Ressourcenverbrauch (VRAM, RAM, Dauer, Speicher) – auch für kostenlose lokale Jobs.
Es werden keine Cloud-Provider mitgeliefert; das Framework ist mit einem Mock-Cloud-Provider getestet.

## 7. MCP-Server

`mcp_server/server.py` nutzt das offizielle MCP-Python-SDK **2.x** (`mcp.server.mcpserver.MCPServer`,
stdio-Transport). Er ist ein dünner, validierender Client der lokalen Backend-API:

* Eingaben per Pydantic/`Annotated[..., Field(...)]` typisiert und begrenzt.
* Timeouts pro Aufruf, Logging nach `data/logs/mcp.log` (stdout bleibt für das Protokoll frei).
* **Keine Shell-Ausführung**, keine freien Dateipfade außerhalb erlaubter Verzeichnisse
  (das Backend prüft zusätzlich jede Pfadangabe).
* Kostenpflichtige Aktionen liefern die Schätzung zurück; Claude muss den Benutzer fragen und das
  Token übergeben.

Abweichung von der vorgeschlagenen Struktur: Das Verzeichnis heißt `mcp_server/` statt `mcp/server/`,
weil ein Top-Level-Paket `mcp` das offizielle SDK-Paket `mcp` beim Import überschatten würde.

## 8. Workflow-Engine

YAML-Definitionen in `workflows/<kategorie>/*.yaml`:

```yaml
id: images/text-to-image
inputs:
  prompt: {type: string, required: true}
steps:
  - id: generate
    action: image.generate
    params: {prompt: "{{ inputs.prompt }}", aspect_ratio: "{{ inputs.aspect_ratio }}"}
  - id: qa
    action: quality.analyze
    params: {assets: "{{ steps.generate.assets }}"}
```

* Platzhalter werden mit einer **Jinja2-Sandbox** ausgewertet (kein Code-Zugriff).
* `when:` für bedingte Schritte, `foreach:` für Szenen-Listen (Storyboards).
* Actions sind registrierte Funktionen (`image.generate`, `video.image_to_video`, `video.concat`,
  `video.add_audio`, `motion.render`, `render3d.render`, `brand.palette`, `quality.analyze`, …).
* Hardware-Fallbacks: Video-Workflows prüfen `capabilities.video` und nutzen sonst den
  Ken-Burns-Pfad.

## 9. Sicherheit

* API bindet standardmäßig an `127.0.0.1`; optionaler Bearer-Token (`ACS_API_TOKEN`).
* `PathGuard` erlaubt Dateizugriffe nur in `assets/`, `data/tmp/` und konfigurierten Zusatzordnern.
* Externe Programme nur mit Argumentlisten (`subprocess`/`asyncio.create_subprocess_exec`), nie `shell=True`.
* Uploads: Größenlimit, MIME-Prüfung, sichere Dateinamen.
* Secrets nur aus Umgebungsvariablen; `public_dict()` liefert Settings ohne Secrets.
* Template-Ausdrücke in Workflows laufen in einer Jinja2-`SandboxedEnvironment`.

## 10. Architekturentscheidungen (Kurz-ADRs)

| ADR | Entscheidung | Begründung | Alternativen |
|---|---|---|---|
| 1 | Python/FastAPI-Backend | ComfyUI, MCP-SDK, Bildanalyse sind Python-nativ | Node/Express |
| 2 | ComfyUI als einzige Diffusions-Engine | größtes Modell-Ökosystem, native Offloading-Strategien, stabile HTTP-API | diffusers direkt (mehr eigener Code, weniger Modelle) |
| 3 | SQLite statt Redis/Postgres | Local-first, keine Zusatzdienste, ausreichend für Einzelplatz | Redis-Queue (zusätzlicher Dienst) |
| 4 | MCP-Server als API-Client | eine Wahrheit für Jobs; Dashboard sieht MCP-Jobs live | MCP mit eingebettetem Backend (doppelte Queue) |
| 5 | API-Format-Templates + Meta-Mapping | Benutzer können eigene ComfyUI-Exporte einbinden | Workflows im Code zusammenbauen |
| 6 | React + Vite ohne UI-Framework | wenige Abhängigkeiten, statisch vom Backend ausgeliefert | Next.js (Server nötig) |
| 7 | Jinja2-Sandbox für Workflow-Platzhalter | ausdrucksstark, sicher | eigene Mini-Sprache |
| 8 | Remotion optional | Lizenz für Firmen > 3 Personen kostenpflichtig → FFmpeg-Fallback für Titel | nur FFmpeg |

## 11. Lizenzen (Drittanbieter)

| Komponente | Lizenz | Hinweis |
|---|---|---|
| ComfyUI | GPL-3.0 | separat installiert, nur über HTTP angesprochen |
| FFmpeg | LGPL/GPL (je nach Build) | System-Installation |
| Blender | GPL | separat installiert |
| Remotion | Remotion License | kostenlos für Einzelpersonen/≤ 3 Mitarbeitende; sonst Firmenlizenz |
| Modelle | siehe `docs/MODELS.md` | FLUX.1-dev & FLUX.2-Klein-9B sind **nicht** kommerziell nutzbar |
