# Benutzerhandbuch

## Zwei Wege zum Ergebnis

1. **Claude Code (empfohlen für kreative Aufträge):** Projekt in Claude Code öffnen und den Auftrag in natürlicher
   Sprache formulieren. Der Agent `creative-director` plant, delegiert an Spezialisten (Bild, Video, Motion, Brand,
   Schnitt, Qualität) und nutzt die MCP-Tools. Ergebnisse landen in der Asset-Bibliothek.
2. **Dashboard (http://127.0.0.1:8420):** direkte Bedienung aller Funktionen mit Live-Fortschritt.

Beides arbeitet auf derselben Job-Queue und Bibliothek – ein in Claude gestarteter Job erscheint sofort im Dashboard.

## Beispiel-Aufträge an Claude

| Auftrag | Was passiert |
|---|---|
| „Erstelle 4 Logo-Konzepte und ein Brand Kit für ‚Nordlicht Kaffee‘, Spezialitätenrösterei, warm und handwerklich.“ | `brand-designer` → Workflow `branding/brand-kit`: Palette, Typografie, Logos, Bildsprache, Social-Post, Guidelines (HTML/MD) |
| „Ein YouTube-Thumbnail zum Thema Mars-Mission mit dem Titel ‚Zum Mars!‘.“ | `social-media/youtube-thumbnail`: Hintergrund 16:9 → exakt 1280×720 → Titel → Prüfung gegen YouTube-Preset |
| „Ein 15-Sekunden-Werbevideo für unsere Trinkflasche, 9:16, mit Musik aus assets/references/musik.mp3.“ | Storyboard (3–5 Szenen) → `videos/storyboard-to-video` (GPU) bzw. Ken-Burns-Fallback (CPU) → Musik, Untertitel, QA |
| „Mach aus logo.svg einen 3D-Logo-Reveal.“ | `motion-designer` → `motion-design/logo-reveal-3d` (Blender) |
| „Exportiere video.mp4 für YouTube, Reels und den Feed.“ | `social-media/multi-format-export`: 16:9, 9:16, 1:1 mit Blur-Hintergrund |
| „Prüfe alle Bilder vom Projekt X auf Qualität.“ | `quality-reviewer` → `generate_quality_report` (Markdown + JSON in `assets/exports/reports`) |

Claude fragt nach, bevor es große Modelle herunterlädt, Dateien verschiebt oder (falls je konfiguriert) Kosten verursacht.

## Dashboard-Bereiche

* **Dashboard** – Hardwareprofil, CPU/RAM/GPU/VRAM, ComfyUI-Status, Provider, aktive Jobs (mit Abbrechen), letzte Ergebnisse.
* **Image Studio** – Prompt, Negativ-Prompt, Stil, Modell (oder automatisch), Provider (*Mock* = Testmodus ohne KI),
  Seitenverhältnis oder Pixelgröße, Seed, Steps, CFG, Varianten; Ressourcenschätzung vor dem Start; Bearbeiten-Tab für
  Img2Img, Upscaling, Freistellen, Text-Overlay.
* **Video Studio** – Text-/Bild-zu-Video mit Kamerabewegung, Dauer, FPS; Storyboard-Editor; ohne GPU wird der
  Ken-Burns-Workflow angeboten; Render-Queue.
* **Brand Studio** – Brand Brief → Brand Kit, Palettengenerator mit WCAG-Kontrast, Schriftvorschläge, Marken-Assets.
* **Workflows** – alle Workflows mit automatisch erzeugten Formularen, Fortschritt, Protokoll, Retry.
* **Asset Library** – Suche (Prompt, Dateiname, Tags, Modell), Filter, Favoriten, Tags, Detailansicht mit Seed, Modell,
  Qualitätsbericht und exaktem ComfyUI-Workflow, Upload, Neu-Indizieren, Organisieren (mit Vorschau).
* **Settings** – Hardware-Report, Modellkatalog (mit Download-Befehl – Downloads nie aus der Oberfläche), Provider
  (an/aus), Pfade, ComfyUI-Verbindung, Leistung, Kostenlimits, API-Token, Hell/Dunkel.

## Reproduzierbarkeit

Jede erzeugte Datei hat eine Sidecar-Datei `<datei>.meta.json` mit Prompt, Seed, Modell, Parametern und dem exakt
ausgeführten ComfyUI-Workflow. Gleicher Seed + gleiche Parameter + gleiches Modell ⇒ gleiches Bild (auf derselben
Hardware/Version). Die Sidecars machen die Bibliothek auch ohne Datenbank portabel (`rescan_assets` liest sie wieder ein).

## Eigene Dateien verwenden

Dateien in `assets/references/` kopieren (oder im Dashboard hochladen) und „Neu indizieren“ – danach sind sie per
Asset-ID oder Pfad (`references/datei.png`) in allen Tools nutzbar. Zugriffe außerhalb von `assets/` sind gesperrt;
zusätzliche Ordner können in `configs/studio.local.yaml` unter `paths.extra_allowed_dirs` freigegeben werden.

## Tipps für gute Ergebnisse

* Bild-Prompts: Motiv → Umgebung → Licht → Kamera/Objektiv → Stil. FLUX/Z-Image verstehen ganze Sätze; SD 1.5/SDXL
  profitieren von Negativ-Prompts.
* Video-Prompts (Wan): eine Handlung pro Clip, Kamerabewegung explizit, 2–5 Sekunden; längere Videos = mehrere Szenen.
* Erst Entwürfe (wenige Steps, kleine Auflösung, Varianten), dann den besten Seed hochwertig rendern und hochskalieren.
* Auf CPU-Systemen: Standbilder + Ken-Burns + gute Musik ergeben überraschend wirkungsvolle Videos.
