# MCP-Server `ai-creative-studio`

Der MCP-Server verbindet Claude Code mit dem lokalen Studio. Er basiert auf dem offiziellen
MCP-Python-SDK **2.x** (`mcp.server.mcpserver.MCPServer`, stdio-Transport) und ist ein dünner,
validierender Client der Backend-API – alle Jobs erscheinen deshalb live im Dashboard.

## Einrichtung

`.mcp.json` im Projekt registriert den Server automatisch:

```json
{"mcpServers": {"ai-creative-studio": {"type": "stdio",
  "command": "${ACS_PYTHON:-.venv/bin/python}", "args": ["-m", "mcp_server.server"],
  "env": {"ACS_MCP_BACKEND_URL": "${ACS_MCP_BACKEND_URL:-http://127.0.0.1:8420}", "ACS_API_TOKEN": "${ACS_API_TOKEN:-}"}}}}
```

* Das Backend muss laufen (`./start.sh`). Ist es nicht erreichbar, liefern Tools eine klare Fehlermeldung mit Startbefehl.
* Windows: `ACS_PYTHON` auf `.venv\Scripts\python.exe` setzen (macht `setup.ps1`).
* `.claude/settings.json` aktiviert den Server und erlaubt seine Tools; `organize_assets` fragt immer nach.
* Status in Claude Code: `/mcp`. Manueller Test: `.venv/bin/python -m mcp_server.server` (wartet auf stdio).

## Sicherheit

| Maßnahme | Umsetzung |
|---|---|
| Keine Shell | Tools rufen nur definierte API-Endpunkte auf; es gibt kein Tool, das Befehle ausführt |
| Dateizugriff | Nur Asset-IDs oder Pfade in `assets/`; `..` wird im MCP-Server abgewiesen, das Backend prüft zusätzlich per `PathGuard` (inkl. Symlinks) |
| Eingabevalidierung | Typisierte, begrenzte Parameter (Pydantic/JSON-Schema: Längen, Bereiche, Enums, Hex-Farben, Seitenverhältnisse) |
| Timeouts | 30 s pro HTTP-Anfrage (`ACS_MCP_TIMEOUT_S`), Warten auf Jobs max. 1800 s in 60-s-Abschnitten |
| Logging | `data/logs/mcp.log` (rotierend); stdout bleibt dem Protokoll vorbehalten |
| Kosten | Kostenpflichtige Aktionen liefern `status: cost_confirmation_required` + Schätzung; erst nach Zustimmung mit `confirm_token` |
| Authentifizierung | `ACS_API_TOKEN` wird als Bearer-Token weitergereicht |

## Ergebnisformat

Generierende Tools warten standardmäßig (`wait=true`) und liefern:

```json
{"job_id": "…", "status": "succeeded", "progress": 1.0,
 "result": {"model": "sd15-lcm", "seed": 42, "provider": "comfyui",
   "assets": [{"id": "…", "path": "generated/2026-11-25/image_00001_.png",
               "file": "/abs/pfad/assets/generated/2026-11-25/image_00001_.png",
               "kind": "image", "width": 512, "height": 512, "quality_score": 100, "quality_passed": true}]}}
```

`file` ist ein absoluter Pfad – Claude kann Bilder damit über das Read-Tool ansehen und beurteilen.
Fehler kommen als Tool-Fehler mit Code und Handlungshinweis, z. B.
`[model_not_installed] … – Benutzer fragen, ob das Modell heruntergeladen werden soll …`.

## Tools (generiert aus dem Server)

Fett = Pflichtparameter.


| Tool | Beschreibung | Parameter |
|---|---|---|
| `get_system_status` | Systemstatus: Hardwareprofil, CPU/RAM/GPU/VRAM-Auslastung, ComfyUI-Erreichbarkeit, Provider, aktive Jobs, Speicher. |  |
| `get_hardware_profile` | Erkannte Hardware, gewähltes Profil (low/mid/high) inkl. Begründung und empfohlene Modelle pro Aufgabe. | refresh |
| `list_providers` | Alle Provider mit Ort (local/cloud), Kostenmodell, API-Key-Pflicht, aktiviert, Gesundheit und Fähigkeiten. |  |
| `get_available_models` | Modellkatalog mit Installationsstatus, Hardware-Eignung, Lizenz und Empfehlung je Aufgabe. | task |
| `get_presets` | Stil-Presets, Kamerabewegungen, Social-Media-Formate, Auflösungs-Presets, Übergänge. |  |
| `get_comfyui_templates` | ComfyUI-Workflow-Templates (engines/comfyui/workflows) mit Aufgabe, Modellfamilie und Parametern. |  |
| `run_smoke_test` | Prüft die ComfyUI-Anbindung ohne Modelle (Queue, Ausführung, Bild- und Video-Download). | timeout_s |
| `estimate_cost` | Kosten- und Ressourcenschätzung (Provider, Modell, Anzahl, Kosten, VRAM/RAM, Dauer) ohne etwas auszuführen. | **job_type**, **params** |
| `get_workflows` | Verfügbare Workflows (Bild, Video, Branding, Social Media, Motion Design) mit Eingaben und Voraussetzungen. |  |
| `run_workflow` | Workflow ausführen. Ohne GPU nutzen Video-Workflows automatisch den Ken-Burns-Fallback (siehe fallback_used). | **workflow_id**, **inputs**, project, confirm_token, wait, timeout_s |
| `get_job_status` | Status, Fortschritt, Fehler und Ergebnis (Assets mit Dateipfaden, Qualität) eines Jobs. | **job_id** |
| `wait_for_job` | Blockiert bis der Job fertig ist (oder Timeout) und gibt das Ergebnis zurück. | **job_id**, timeout_s |
| `cancel_job` | Job abbrechen (wartend: sofort; laufend: ComfyUI-Interrupt bzw. Prozessabbruch). | **job_id** |
| `retry_job` | Fehlgeschlagenen/abgebrochenen Job mit identischen Parametern neu starten. | **job_id** |
| `list_jobs` | Job-Historie (neueste zuerst). | status, type, limit |
| `generate_image` | Bild(er) mit lokalem KI-Modell generieren (ComfyUI). Ergebnis: Assets mit Pfad, Seed, Modell und Qualitätsscore. | **prompt**, negative_prompt, style, model, aspect_ratio, width, height, steps, cfg, seed, batch_size, loras, control_image, control_mode, control_strength, provider, project, tags, confirm_token, wait, timeout_s |
| `edit_image` | Bild bearbeiten: img2img (Variation), inpaint (Maske weiß = neu; ohne Maske Alpha-Kanal) oder outpaint (Ränder erweitern). | **source**, prompt, mode, strength, mask, left, top, right, bottom, model, seed, provider, project, wait, timeout_s |
| `upscale_image` | Hochskalieren mit Real-ESRGAN (falls installiert) oder Lanczos-Fallback. | **source**, scale, method, project, wait, timeout_s |
| `remove_background` | Hintergrund entfernen (rembg, lokal; optionales Paket). Ergebnis: PNG mit Transparenz. alpha_matting = feinere Kanten (langsamer). | **source**, alpha_matting, model, project, wait, timeout_s |
| `create_contact_sheet` | Übersichtsbild (Kontaktbogen) mehrerer Bilder/Varianten – z. B. zur Auswahl durch den Benutzer. | **sources**, columns, labels, cell, background |
| `resize_image` | Bild auf Social-Media-Format oder feste Größe bringen (Zuschnitt, Rand oder Blur-Hintergrund). | **source**, format_preset, width, height, mode, output_format, wait |
| `add_text_overlay` | Titel/Untertitel auf ein Bild setzen (Thumbnails, Social Posts) mit Kontrastfläche. | **source**, **title**, subtitle, position, color, accent, uppercase, font_scale, wait |
| `extract_palette` | Farbpalette aus einem Bild extrahieren oder aus einer Basisfarbe ableiten (inkl. WCAG-Kontrastwerte). | source, base_color, harmony, count |
| `generate_video` | KI-Video generieren (Wan 2.x via ComfyUI). Mit image = Image-to-Video. Ohne GPU: Fehler mit Fallback-Workflow. | **prompt**, image, model, aspect_ratio, duration_s, frames, fps, camera_move, negative_prompt, seed, provider, project, confirm_token, wait, timeout_s |
| `upscale_video` | Video hochskalieren: Real-ESRGAN Frame für Frame (ComfyUI, Audio/FPS bleiben) oder FFmpeg-Lanczos-Fallback. | **source**, scale, method, project, wait, timeout_s |
| `get_video_info` | Medieninfo per ffprobe: Auflösung, Dauer, FPS, Codecs, Bitrate, Audio. | **path** |
| `convert_video` | Format/Codec konvertieren (MP4/H.264, WebM/VP9, GIF mit Palette, Audio-Extraktion). | **source**, format, crf, fps, width, height, remove_audio, wait, timeout_s |
| `trim_video` | Video schneiden (Start/Ende oder Dauer). | **source**, start_s, end_s, duration_s, wait |
| `extract_frames` | Einzelbilder extrahieren (x Bilder pro Sekunde oder n gleichmäßig verteilte Frames). | **source**, fps, count, start_s, format, wait |
| `merge_videos` | Clips zusammenfügen (normalisiert Auflösung/FPS/Audio) mit Übergängen (xfade). | **sources**, transition, transition_duration, width, height, fps, wait, timeout_s |
| `add_audio` | Musik/Ton hinzufügen (ersetzen oder mischen), Loop auf Videolänge, Fades, Lautheitsnormalisierung (-16 LUFS). | **video**, **audio**, mode, volume, fade_in_s, fade_out_s, normalize, wait |
| `add_subtitles` | Untertitel einbrennen (libass) oder als Spur einbetten (mov_text). | **video**, **subtitles**, burn_in, font_size, position, wait |
| `resize_video` | Seitenverhältnis ändern (z. B. 16:9 → 9:16) mit Blur-Hintergrund, Zuschnitt oder Balken. | **source**, **aspect_ratio**, mode, wait, timeout_s |
| `render_video` | Finales Video aus Timeline rendern: Bilder (Ken Burns) + Videos → Übergänge → Musik → Untertitel. | **clips**, width, height, fps, transition, transition_duration, audio, subtitles, output_name, project, wait, timeout_s |
| `create_title_card` | Animierte Titelkarte mit FFmpeg (funktioniert ohne Node.js/Remotion). | **title**, subtitle, duration_s, width, height, background, color, accent, wait |
| `compress_video` | Video verkleinern (Zielgröße in MB oder CRF, optional maximale Breite) – z. B. für Upload-Limits. | **source**, target_size_mb, crf, max_width, wait, timeout_s |
| `interpolate_video` | Frame-Interpolation (FFmpeg minterpolate, bewegungskompensiert) für flüssigere KI-Clips. | **source**, target_fps, mode, wait, timeout_s |
| `render_motion_graphics` | Motion Graphics mit Remotion rendern (Intro, Bauchbinde, Social-Clip, kinetische Typo, Outro). | **composition**, **props**, width, height, duration_s, fps, transparent, project, wait, timeout_s |
| `render_3d` | 3D-Szene mit Blender (headless) rendern: Produkt-Turntable, 3D-Text oder SVG-Logo-Extrusion. | **template**, params, width, height, frames, fps, samples, output, engine, device, transparent, save_blend, project, wait, timeout_s |
| `create_brand_guidelines` | Brand Guidelines als HTML (offline, Bilder eingebettet) + Markdown + brand.json erzeugen. | **brand_name**, tagline, mission, audience, positioning, values, voice, palette, heading_font, body_font, logos, imagery, imagery_style, dos, donts |
| `suggest_typography` | Schriftpaarungen (freie Google Fonts, SIL OFL) passend zu Stichworten. | **keywords**, limit |
| `list_assets` | Neueste Assets (Bilder, Videos, Audio, 3D, Dokumente). | kind, limit, sort |
| `search_assets` | Assets nach Text (Prompt, Dateiname, Tags, Modell, Notizen), Typ, Tags, Favoriten und Projekt durchsuchen. | query, kind, tags, favorite, project, limit |
| `get_asset_metadata` | Vollständige Metadaten inkl. Prompt, Seed, Parameter, Qualitätsbericht und exaktem ComfyUI-Workflow (Sidecar). | **asset_id** |
| `tag_asset` | Tags, Favorit, Bewertung, Notizen oder Projekt eines Assets ändern. | **asset_id**, add_tags, remove_tags, favorite, rating, notes, project |
| `organize_assets` | Assets in Ordnerstruktur sortieren. Standard: Dry-Run (zeigt nur geplante Verschiebungen). Nur nach Bestätigung dry_run=false. | rule, asset_ids, dry_run |
| `rescan_assets` | Manuell nach assets/ kopierte Dateien indizieren (z. B. Referenzbilder in assets/references). |  |
| `analyze_image` | Bildqualität prüfen: Auflösung, Schärfe, Belichtung, Clipping, Kontrast, Rauschen, Leere – Score 0–100 mit Befunden. | **source**, min_width, min_height, expected_aspect, purpose, preset |
| `analyze_video` | Videoqualität prüfen: Streams, Auflösung, FPS, Dauer, Audio, schwarze/eingefrorene Segmente, Schärfe, Flackern. | **source**, expected_fps, expected_duration_s, expected_aspect, require_audio, min_width, min_height |
| `validate_resolution` | Auflösung/Seitenverhältnis gegen Plattform-Presets oder eigene Vorgaben prüfen. | source, width, height, preset, aspect, exact |
| `generate_quality_report` | Qualitätsbericht (Markdown + JSON in assets/exports/reports) für mehrere Assets erstellen. | **assets**, title, preset, project |
