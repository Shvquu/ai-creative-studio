---
name: social-media-design
description: >-
  Erstellt Social-Media-Inhalte lokal in exakt passenden Formaten: Instagram-Posts/Stories/Reels,
  TikTok, YouTube-Thumbnails, X/LinkedIn/Facebook/Pinterest-Grafiken, OG-Images – mit Text-Overlays,
  animierten Varianten und Multi-Format-Export von Videos. Verwenden bei „Instagram-Post“, „Story“,
  „Reel“, „TikTok“, „YouTube-Thumbnail“, „LinkedIn-Grafik“, „Post mit Text drauf“, „für alle Plattformen
  exportieren“, „Hochformat-Version“.
---

# Social-Media-Design

## Beschreibung
Workflows und Werkzeuge, die Plattformmaße garantieren (Zuschnitt `crop`, `pad` oder unscharfer
Hintergrund `blur`), Text gestalterisch sauber per Overlay setzen (keine KI-Schrift) und gegen
Plattform-Presets validieren.

## Anwendungsfälle
Kampagnen-Posts, Thumbnails, Ankündigungen, Reels aus Bildern, Format-Varianten eines Videos.

## Auslösekriterien
Ein Kanal/eine Plattform wird genannt oder ein Bild/Video braucht Text + exaktes Plattformformat.

## Formate
| Preset | Größe | | Preset | Größe |
|---|---|---|---|---|
| `instagram_post` | 1080×1080 | | `youtube_thumbnail` | 1280×720 |
| `instagram_portrait` | 1080×1350 | | `youtube_banner` | 2560×1440 |
| `instagram_story` | 1080×1920 | | `x_post` | 1600×900 |
| `tiktok` | 1080×1920 | | `linkedin_post` | 1200×627 |
| `pinterest_pin` | 1000×1500 | | `facebook_cover` | 1640×624 |
| `og_image` | 1200×630 | | | |
Prüf-Presets (`validate_resolution`): youtube_thumbnail, youtube_1080p, youtube_4k, instagram_post,
instagram_portrait, instagram_story, reels, tiktok, x_post, linkedin_post, og_image.

## Voraussetzungen
Bildgenerierung oder vorhandenes Bild; für animierte Posts Remotion (`motion-design`).

## Arbeitsablauf
1. Plattform + Ziel (Reichweite, Klick, Ankündigung) klären; Kernaussage ≤ 6 Wörter.
2. Visual erzeugen mit Freiraum für Text: Stil `social-bold` oder `thumbnail` („negative space on the left“).
3. Zuschneiden auf Preset (`resize_image`), Text setzen (`add_text_overlay`, Großbuchstaben bei Thumbnails).
4. Optional animierte Variante (`render_motion_graphics` → `SocialPost` / `KineticText`).
5. Validieren (`validate_resolution`, `analyze_image`), taggen (Plattform, Kampagne).

## Tool-Nutzung
```text
run_workflow("social-media/youtube-thumbnail", {"topic": "astronaut planting a tree on mars, dramatic sunset",
             "title": "Leben auf dem Mars?", "accent": "#F97316", "text_position": "left", "variants": 3})
run_workflow("social-media/instagram-post", {"prompt": "...", "headline": "Neu: Winterröstung",
             "subline": "Nur bis Februar", "cta": "Jetzt probieren", "brand_name": "Nordlicht",
             "format": "instagram_portrait", "animated": true})
run_workflow("social-media/multi-format-export", {"video": "<id>", "formats": ["16:9", "9:16", "4:5"], "mode": "blur"})
resize_image(source="<id>", format_preset="linkedin_post", mode="crop")
add_text_overlay(source="<id>", title="5 TIPPS", subtitle="für bessere Fotos", position="right", accent="#22D3EE")
validate_resolution(source="<id>", preset="youtube_thumbnail")
```
REST: `POST /api/images/resize`, `POST /api/images/text_overlay`, `POST /api/quality/validate-resolution`.

## Qualitätsanforderungen
- Exakte Maße laut Preset (`validate_resolution` → `valid: true`); Thumbnails ≤ 2 MB als JPG (YouTube-Vorgabe – Dateigröße `size_bytes` über `get_asset_metadata` prüfen, wird nicht automatisch geprüft).
- Text: Kontrast ≥ 4,5:1 (Overlay-Panel aktiv lassen), auf dem Smartphone lesbar (Titel ≥ 8 % Bildhöhe), nicht in UI-Zonen (Story: oben/unten 250 px frei).
- Thumbnails: ein klares Motiv, max. 5 Wörter, starker Kontrast.
- QA-Score ≥ 60.

## Fehlerbehandlung
- Text überdeckt Motiv → `text_position` ändern oder Visual mit Freiraum neu generieren.
- `validation_error` „Unbekanntes Format“ → Preset-Liste oben.
- Remotion fehlt → animierter Schritt wird übersprungen (`continue_on_error`), statisches Bild bleibt.
- Weitere Codes: [../image-generation/reference/errors.md](../image-generation/reference/errors.md).

## Beispiele
1. **Thumbnail-A/B-Test**: youtube-thumbnail mit `variants: 3` → `validate_resolution` → Benutzer wählt.
2. **Launch-Paket**: instagram-post (`instagram_post` + Reel) + `resize_image` für `linkedin_post` und `og_image`.
3. **Video-Verteilung**: multi-format-export 16:9/9:16/1:1 mit `max_size_mb: 50`.
