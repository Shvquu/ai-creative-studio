---
name: prompt-engineering
description: >-
  Schreibt und optimiert Prompts für die lokalen Bild- und Videomodelle – modellfamilienspezifisch
  (SD 1.5/SDXL mit Negativ-Prompts und Gewichtungen; FLUX.1, FLUX.2 Klein und Z-Image mit natürlicher
  Sprache, cfg≈1, ohne Negativ-Prompt; Wan-Video mit Subjekt+Aktion+Kamera+Licht). Verwenden bei
  „verbessere meinen Prompt“, „warum sieht das Bild komisch aus“, „mehr Fotorealismus“, „konsistenter
  Stil über mehrere Bilder“, „wie beschreibe ich die Kamerabewegung“, sowie intern vor jeder Generierung.
---

# Prompt Engineering

## Beschreibung
Claude formuliert den **kreativen** Prompt; das Backend ergänzt **technische** Teile
(Stil-Preset-Begriffe, familienabhängige Negativ-Prompts, Kamera-Phrasen). Dieser Skill sorgt dafür,
dass beides zusammenpasst und das Ergebnis reproduzierbar bleibt.

## Anwendungsfälle
Neue Prompts, Prompt-Reparatur bei schlechten Ergebnissen, Serien mit konsistentem Look, Video-Prompts,
Übersetzen deutscher Beschreibungen in modellfreundliches Englisch.

## Auslösekriterien
Vor jeder Generierung (Skills `image-generation`, `video-generation`, `product-photography`,
`brand-identity`) und wenn Ergebnisse nicht dem Wunsch entsprechen.

## Voraussetzungen
Wissen, welches Modell läuft: `get_available_models` / Job-Ergebnis `model`. Familien: `sd15`
(sd15, sd15-lcm), `sdxl`, `flux1` (flux1-schnell, flux1-dev), `flux2` (flux2-klein-4b), `z-image`
(z-image-turbo), Video `wan21`, `wan22-5b`, `wan22-14b`.

## Arbeitsablauf
1. Ziel in einem Satz: *Was* ist zu sehen, *wofür* wird es genutzt?
2. Prompt auf **Englisch** (alle Modelle sind darauf trainiert; Z-Image versteht auch Chinesisch).
3. Struktur: **Subjekt → Details → Umgebung → Licht → Kamera/Objektiv → Stil/Stimmung**.
4. Familie berücksichtigen (Tabelle unten), Stil über `style`-Preset statt Schlagwortlisten.
5. Nach der Generierung: Abweichungen analysieren, **eine** Variable ändern (Prompt *oder* Seed *oder* CFG), erneut testen.
6. Funktionierende Prompts + Seed im Asset dokumentieren (Sidecar enthält alles automatisch).

## Familien-Leitfaden

| Familie | Prompt-Stil | Negativ-Prompt | CFG / Schritte | Hinweise |
|---|---|---|---|---|
| `sd15`, `sdxl` | kommagetrennte Begriffe ok; Gewichtung `(term:1.2)` | **ja** (Backend ergänzt Basis-Negativ) | SD1.5 6–8/25; SDXL 5–7/30; LCM 1–2/4–8 | SD1.5 nativ 512 px, SDXL 1024 px – nicht größer generieren, sondern hochskalieren |
| `flux1`, `flux2`, `z-image` | ganze Sätze, präzise Beschreibung, Text in `"Anführungszeichen"` | **nein** (wird ignoriert) | cfg 1; 4 (FLUX/Klein) bzw. 8 (Z-Image) Schritte | keine Gewichtungs-Syntax; Reihenfolge = Wichtigkeit; Typografie: FLUX.2 Klein |
| `wan*` (Video) | 1–3 Sätze, Präsens, **eine** Hauptbewegung | optional (Backend nutzt den offiziellen Wan-Standard-Negativ) | Modell-Defaults | Subjekt + Aktion + Kamera + Licht; 2–5 s; Frames 4n+1 |

Beispiele:
- SDXL: `portrait of an elderly fisherman, weathered skin, (wool sweater:1.1), harbor background, golden hour, 85mm lens, shallow depth of field`
- FLUX.2/Z-Image: `An elderly fisherman in a thick wool sweater stands at a misty harbor at golden hour. Close-up portrait, 85mm lens, shallow depth of field, natural skin texture.`
- Wan: `A barista slowly pours steamed milk into a cup, forming a heart-shaped latte art. The camera dollies in. Warm morning light from the window, shallow depth of field.`

Stil-Presets & Kamera-Vokabular: [reference/style-presets.md](reference/style-presets.md).

## Tool-Nutzung
```text
get_presets()                                   # styles, camera_moves, aspect_ratios
generate_image(prompt="<englischer Satz>", style="cinematic", negative_prompt="")    # FLUX/Z-Image: leer
generate_image(prompt="...", model="sdxl", negative_prompt="text, watermark, extra fingers")
generate_video(prompt="<Subjekt + Aktion + Licht>", camera_move="tracking")
```
REST-Hilfe: `GET /api/presets`. Der Workflow-Helfer `prompt.build` kombiniert Prompt + Preset in Workflows.

## Qualitätsanforderungen
- Jedes Bildelement aus dem Brief ist im Prompt benannt; nichts Widersprüchliches („night, bright sunlight“).
- Max. ~75 Wörter für SD-Familien (CLIP-Limit), ~150 Wörter für FLUX/Z-Image.
- Keine Namen realer Personen, Künstler-Imitation lebender Künstler oder Markennamen.
- Ergebnis besteht QA (`quality-control`) und erfüllt den Brief visuell.

## Fehlerbehandlung
- Pseudo-Text im Bild → Text aus dem Prompt entfernen, Overlay nutzen (`add_text_overlay`) oder FLUX.2 Klein mit Text in Anführungszeichen.
- Überladene Bilder → weniger Subjekte, `negative_prompt` (nur SD), Komposition beschreiben („centered, plenty of negative space“).
- Video steht still → stärkeres Bewegungsverb, `camera_move` setzen, Dauer verkürzen.
- `validation_error` (z. B. Prompt > 4000 Zeichen) → kürzen. Weitere Codes: [../image-generation/reference/errors.md](../image-generation/reference/errors.md).

## Beispiele
1. **Deutsch → Prompt**: „Ein gemütliches Café im Winter“ → `A cozy Scandinavian café on a snowy winter evening, warm string lights in the windows, people silhouetted inside, soft snowfall, cinematic wide shot.` + `style="cinematic"`.
2. **Serie konsistent**: gleicher Prompt-Kern + gleicher `seed` + gleiches `model`; nur Motiv-Teil tauschen.
3. **Reparatur**: SDXL zeigt deformierte Hände → Hände aus dem Fokus nehmen („hands out of frame“) oder Pose ändern; Negativ ergänzen.
