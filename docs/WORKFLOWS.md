# Workflows

Workflows sind mehrstufige Abläufe in `workflows/<kategorie>/*.yaml`. Sie werden vom Dashboard
(Workflow Studio), per MCP (`run_workflow`), REST (`POST /api/workflows/<id>/run`) oder CLI ausgeführt:

```bash
.venv/bin/python -m backend.cli workflows
.venv/bin/python -m backend.cli run-workflow images/text-to-image --inputs '{"prompt": "Leuchtturm im Sturm", "variants": 2}'
```

## Die Standard-Abläufe aus dem Konzept

**Bild:** Beschreibung → Creative Director analysiert → Prompt-Engineering (Agent + `prompt-engineering`-Skill,
technische Stil-/Negativ-Ergänzung in `backend/orchestration/prompts.py`) → Hardwareprofil → Modellauswahl
(`ModelSelector`) → ComfyUI → Qualitätsprüfung (automatisch) → Varianten → Export → Metadaten (Sidecar + Index).
Umgesetzt in `images/text-to-image`.

**Video:** Beschreibung → Konzept → Storyboard (`scenes`) → Kamera/Bewegung (`camera` je Szene) → Referenzbilder →
Image-to-Video → Schnitt mit Übergängen → Audio & Untertitel → Qualitätsprüfung → finales Rendering.
Umgesetzt in `videos/storyboard-to-video`; ohne GPU automatisch `videos/kenburns-slideshow`.

**Branding:** Analyse/Zielgruppe/Positionierung (Brief-Eingaben) → Farbpalette → Typografie → Logo-Konzepte →
Bildsprache → Social-Media-Asset → Brand Guidelines → Export. Umgesetzt in `branding/brand-kit`.

## Alle Workflows (generiert)


### `branding/brand-kit` – Brand Kit

Markenidentität in einem Durchlauf: Farbpalette, Typografie, Logo-Konzepte, Bildsprache, Social-Media-Asset und Brand-Guidelines (HTML + Markdown).

- Voraussetzungen: –
- Eingaben: **brand_name**, **industry**, tagline, audience, positioning, brand_values, voice, base_color, harmony, logo_style, logo_concepts, logo_symbol, imagery_prompt, image_provider
- Schritte: palette → typography → logos → logo_sheet → imagery → social → social_text → guidelines

### `images/product-photo` – Produktfoto

Werbetaugliches Produktfoto im Studio-Look, optional freigestellt und im Social-Format exportiert.

- Voraussetzungen: –
- Eingaben: **product**, setting, mood, aspect_ratio, variants, remove_background, social_format, image_provider
- Schritte: generate → cutout → social → qa

### `images/text-to-image` – Text zu Bild

Bild aus einer Beschreibung erzeugen – hardwaregerechte Modellwahl, Varianten, optional Upscaling, Qualitätsprüfung.

- Voraussetzungen: –
- Eingaben: **prompt**, negative_prompt, style, aspect_ratio, variants, model, seed, upscale, image_provider
- Schritte: generate → upscale → qa

### `images/variations` – Bildvarianten

Aus einem vorhandenen Bild mehrere Varianten mit steigender Veränderungsstärke erzeugen und als Übersicht anlegen.

- Voraussetzungen: –
- Eingaben: **source**, **prompt**, strengths, image_provider
- Schritte: variants → sheet

### `motion-design/logo-reveal-3d` – 3D-Logo-Reveal

SVG-Logo als 3D-Objekt mit Kamerafahrt (Blender) – ideal als Intro-Bumper.

- Voraussetzungen: blender
- Eingaben: **svg**, material, color, background, seconds, quality
- Schritte: render → qa

### `motion-design/product-turntable-3d` – 3D-Produkt-Turntable

Produkt (eigenes 3D-Modell oder Grundform) im Studio-Set mit 360°-Kamerafahrt rendern (Blender), optional als 9:16-Version.

- Voraussetzungen: blender
- Eingaben: model, product, color, material, background, seconds, quality, vertical_version
- Schritte: render → vertical → qa

### `motion-design/title-intro` – Titel-Intro / Outro

Animiertes Intro (Remotion) mit Logo und Untertitel; ohne Node.js automatisch FFmpeg-Titelkarte.

- Voraussetzungen: –
- Eingaben: **title**, subtitle, logo, kind, background, text_color, accent, format, duration_s
- Schritte: render → qa

### `social-media/instagram-post` – Instagram-Post (Bild + Clip)

Quadratischer oder Hochformat-Post mit Text, optional zusätzlich als animierter Reel-Clip (Remotion).

- Voraussetzungen: –
- Eingaben: prompt, image, **headline**, subline, cta, brand_name, accent, format, animated, image_provider
- Schritte: visual → sized → post → reel → qa

### `social-media/multi-format-export` – Multi-Format-Export

Ein Video gleichzeitig für YouTube (16:9), Reels/TikTok (9:16) und Feed (1:1/4:5) exportieren – mit unscharfem Hintergrund statt schwarzer Balken.

- Voraussetzungen: –
- Eingaben: **video**, formats, mode, max_size_mb
- Schritte: formats → compress → qa

### `social-media/youtube-thumbnail` – YouTube-Thumbnail

Plakativer Hintergrund, exakt 1280×720 zugeschnitten, mit großem Titel und Prüfung gegen YouTube-Vorgaben.

- Voraussetzungen: –
- Eingaben: **topic**, **title**, subtitle, accent, text_position, variants, image_provider
- Schritte: background → sized → titled → qa

### `videos/image-to-video` – Bild zu Video

Ein Standbild (vorhanden oder neu generiert) mit einem Videomodell animieren.

- Voraussetzungen: ai_video · Fallback: `videos/kenburns-slideshow`
- Eingaben: **prompt**, image, style, camera_move, aspect_ratio, duration_s, image_provider, video_provider
- Schritte: reference → animate → qa

### `videos/kenburns-slideshow` – Ken-Burns-Video (CPU-tauglich)

Video ohne KI-Videomodell: Standbilder (generiert oder vorhanden) mit Kamerafahrten (Zoom/Pan), Übergängen, Musik und Untertiteln. Fallback für Systeme ohne GPU.

- Voraussetzungen: –
- Eingaben: scenes, images, prompt, style, aspect_ratio, duration_s, transition, music, subtitles, title, image_provider
- Schritte: plan → stills → timeline → edit → qa

### `videos/storyboard-to-video` – Storyboard zu Video

Mehrszeniges Video: pro Szene Referenzbild → Image-to-Video → Schnitt mit Übergängen → Musik → Untertitel → Qualitätsprüfung. Ohne GPU wird automatisch die Ken-Burns-Variante genutzt.

- Voraussetzungen: ai_video · Fallback: `videos/kenburns-slideshow`
- Eingaben: **scenes**, style, aspect_ratio, transition, music, subtitles, title, image_provider, video_provider
- Schritte: references → clips → timeline → edit → qa

### `videos/text-to-video` – Text zu Video

Kurzer KI-Clip (Wan 2.x) aus einer Beschreibung, optional mit Frame-Interpolation. Ohne GPU automatisch Ken-Burns-Fallback.

- Voraussetzungen: ai_video · Fallback: `videos/kenburns-slideshow`
- Eingaben: **prompt**, camera_move, aspect_ratio, duration_s, model, interpolate_to_fps, video_provider
- Schritte: clip → smooth → qa
## Eigene Workflows schreiben

```yaml
id: social-media/quote-card          # eindeutig, entspricht üblicherweise dem Pfad
name: Zitat-Karte
description: Zitat auf generiertem Hintergrund im Instagram-Format.
category: social-media
requires: [ai_image]                 # optional: ai_image, ai_video, gpu, ffmpeg, blender, remotion, rembg
fallback: null                       # Workflow-ID, falls requires nicht erfüllt
inputs:
  quote: {type: text, required: true, label: Zitat}
  mood: {type: choice, default: calm, options: [calm, bold]}
steps:
  - id: bg
    action: image.generate
    params: {prompt: "abstract {{ inputs.mood }} background", style: social-bold, aspect_ratio: "1:1"}
  - id: post
    action: image.text_overlay
    params: {source: "{{ steps.bg.asset.id }}", title: "{{ inputs.quote }}", position: center}
  - id: qa
    action: quality.analyze
    params: {assets: "{{ steps.post.asset_ids }}", preset: instagram_post}
outputs:
  post: "{{ steps.post.asset.id }}"
```

Regeln:

* Ausdrücke `{{ … }}` laufen in einer **Jinja2-Sandbox**. Ein String, der nur aus einem Ausdruck besteht, behält
  den Datentyp (Liste, Zahl, Objekt). Leere Werte (`None`, `""`) werden entfernt → Standardwerte greifen.
* Jeder Schritt liefert `asset` (erstes Asset), `asset_ids`, `assets` und typabhängige Felder
  (`colors`, `passed`, `seed`, …). Mit `foreach` zusätzlich `results` (ein Eintrag je Element; Zugriff auf das
  aktuelle Element über `item` bzw. den Namen in `as:`, Index über `index`).
* `when:` überspringt Schritte; `continue_on_error: true` lässt den Workflow trotz Fehler weiterlaufen.
* Kontext: `inputs`, `steps`, `caps` (Fähigkeiten des Systems), `project`. Filter `slug` erzeugt Dateinamen.
* Eingabenamen `values`, `items`, `keys`, `get`, `update`, `pop` sind verboten (kollidieren mit Dict-Methoden in Jinja).
* Actions = alle Job-Typen (`GET /api/jobs/types`) + Helfer: `util.set`, `util.collect`, `timeline.from_assets`,
  `brand.typography`, `prompt.build`.
* Nach dem Anlegen: `POST /api/workflows/reload` oder Backend neu starten. Fehlerhafte Dateien werden beim Laden abgewiesen.
