---
name: quality-control
description: >-
  Prüft Bild- und Videoqualität automatisiert und visuell: Schärfe, Belichtung, Clipping, Rauschen,
  leere Bilder, Auflösung und Seitenverhältnis gegen Plattform-Presets, Codecs/fps/Dauer, schwarze und
  eingefrorene Frames, Flicker – und erstellt Qualitätsberichte (Markdown + JSON). Verwenden nach jeder
  Generierung sowie bei „prüfe das Bild/Video“, „ist das gut genug“, „passt das für YouTube/Instagram“,
  „gibt es Artefakte“, „Qualitätsbericht“, „Abnahme“.
---

# Qualitätskontrolle

## Beschreibung
Messbare Prüfungen aus `backend/quality/analyzer.py` plus visuelle Kontrolle durch Claude. Jede
Generierung wird bereits automatisch geprüft (`quality` im Job-Ergebnis, `quality.auto_check: true`);
dieser Skill vertieft, vergleicht mit Erwartungen und dokumentiert.

## Anwendungsfälle
Abnahme vor Übergabe, Plattform-Compliance, Fehlersuche (Ruckler, schwarze Frames), Batch-Reports.

## Auslösekriterien
Nach `image-generation`, `image-editing`, `video-generation`, `video-editing`, `motion-design`,
`blender-3d` – und auf Nachfrage.

## Voraussetzungen
Assets im Index (Asset-ID); FFmpeg für Videoanalysen.

## Messwerte & Schwellen
| Prüfung | Bestanden | Befund |
|---|---|---|
| Score | ≥ 60 und kein „error“ | Start 100; Warnung −10, Fehler −30 |
| Schärfe (Laplace-Varianz, ≤ 1024 px) | ≥ 40 (Fotos) | < 40 Warnung; Grafiken/Logos ausgenommen |
| Helligkeit Ø (0–255) | 35–225 | außerhalb Warnung |
| Ausgefressene Lichter | ≤ 8 % | Warnung |
| Abgesoffene Schatten | ≤ 15 % | Info |
| Rauschen σ | ≤ 12 | Warnung |
| Leer/einfarbig | – | Fehler |
| Seitenverhältnis | ±2 % | Fehler |
| Video schwarze Frames | ≤ 0,5 s | Warnung; > 50 % der Dauer Fehler |
| Video eingefroren | ≤ 60 % der Dauer | Warnung |
| Flicker (Ø Helligkeitssprung) | ≤ 25 | Warnung |
| fps / Dauer | ±0,5 fps / ±5 % | Warnung |
Presets für `validate_resolution`: youtube_thumbnail, youtube_1080p, youtube_4k, instagram_post,
instagram_portrait, instagram_story, reels, tiktok, x_post, linkedin_post, og_image, print_a4_300dpi, logo.

## Arbeitsablauf
1. Messen: `analyze_image` / `analyze_video` mit Erwartungen aus dem Brief.
2. Plattform: `validate_resolution(source, preset=…)` (Mindestmaße + Seitenverhältnis; exakte Maße mit `exact=true`).
3. Visuell: Bild mit `Read` ansehen; Video: `extract_frames(count=6)` und Frames ansehen –
   auf Hände, Gesichter, Text-Artefakte, Morphing, Nähte, Kanten achten.
4. Urteil je Asset (Freigabe / Nacharbeit mit konkreter Maßnahme / Verwerfen).
5. Report: `generate_quality_report(assets=[…], title=…)` → `assets/exports/reports/*.md|json`.
6. `tag_asset(add_tags=["approved"])` bzw. `["needs-rework"]`.

## Tool-Nutzung
```text
analyze_image(source="<id>", min_width=1280, min_height=720, expected_aspect="16:9")
analyze_image(source="<logo>", purpose="logo")
analyze_video(source="<id>", expected_fps=24, expected_duration_s=15, require_audio=true)
validate_resolution(source="<id>", preset="instagram_story")
validate_resolution(width=1080, height=1350, preset="instagram_portrait", exact=true)
generate_quality_report(assets=["<id1>", "<id2>"], title="Kampagne Winter – Abnahme")
```
REST: `POST /api/quality/analyze` · `POST /api/quality/report` · `POST /api/quality/validate-resolution`.

## Qualitätsanforderungen an den Prüfer
- Jeden Befund mit Messwert nennen; keine Freigabe bei „error“-Befunden.
- Grenzfälle (Score 60–75) explizit als „menschliche Sichtung empfohlen“ markieren.
- Maßnahmen konkret (Tool + Parameter oder zuständiger Agent).

## Fehlerbehandlung
- `not_found` → Asset-ID prüfen (`search_assets`), ggf. `rescan_assets`.
- `tool_not_found` (ffprobe) → FFmpeg installieren; Bildprüfung funktioniert weiterhin.
- Analyse eines Formats ohne Bild/Video (z. B. Audio) → nur Metadaten, Score 100 ist dann bedeutungslos.
- Weitere Codes: [../image-generation/reference/errors.md](../image-generation/reference/errors.md).

## Beispiele
1. **Thumbnail-Abnahme**: `validate_resolution(preset="youtube_thumbnail")` + `analyze_image` → Freigabe, wenn beides passt und der Titel lesbar ist.
2. **KI-Clip mit Ruckeln**: `analyze_video` zeigt eingefroren 70 % → video-director: stärkere Bewegung im Prompt; alternativ `interpolate_video`.
3. **Kampagnenreport**: alle Assets mit Tag `winter` (`search_assets(tags=["winter"])`) → `generate_quality_report`.
