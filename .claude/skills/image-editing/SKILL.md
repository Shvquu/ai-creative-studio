---
name: image-editing
description: >-
  Bearbeitet vorhandene Bilder lokal: Image-to-Image (Stil/Variation), Inpainting (Bereich ersetzen),
  Outpainting (Bild erweitern), Hochskalieren (Real-ESRGAN/Lanczos), Hintergrund entfernen (rembg),
  Zuschneiden/Formatwandlung, Text-Overlays und Variantenreihen. Verwenden bei „ändere / ersetze /
  entferne … im Bild“, „mach den Hintergrund transparent“, „erweitere das Bild nach links“,
  „mach es größer / schärfer“, „zuschneiden auf 4:5“, „Varianten von diesem Bild“, „im Stil von Aquarell“.
---

# Bildbearbeitung

## Beschreibung
Operationen auf einem vorhandenen Asset (ID oder Pfad unter `assets/`). KI-Bearbeitungen laufen über
ComfyUI-Templates (`checkpoint_img2img`, `checkpoint_inpaint`, `checkpoint_outpaint`, `esrgan_upscale`)
mit Checkpoint-Modellen (`sd15`, `sd15-lcm`, `sdxl`); Werkzeuge ohne KI über `local-image-tools`.

## Anwendungsfälle
- Stilwechsel, Farbstimmung, Variationen (img2img)
- Objekt/Himmel/Hintergrund ersetzen, Störendes entfernen (Inpainting)
- Bildformat erweitern, z. B. Quadrat → 16:9 (Outpainting)
- Freistellen für Produktbilder und Logos, Hochskalieren für Druck/Web
- Zuschnitt auf Social-Formate, Text auf Bildern, Variantenübersichten

## Auslösekriterien
Es existiert bereits ein Bild und es soll verändert werden. Neues Bild → `image-generation`.

## Voraussetzungen
- Quellbild als Asset (Upload landet in `assets/references/`; manuell kopierte Dateien mit `rescan_assets` indizieren).
- KI-Bearbeitung: installiertes Checkpoint-Modell (`sd15`, `sd15-lcm` oder `sdxl`) + laufendes ComfyUI.
- Freistellen: Python-Extra `rembg` (`pip install -e ".[rembg]"`).
- KI-Upscaling: Modell `realesrgan-x4` (67 MB); sonst automatisch Lanczos.

## Arbeitsablauf
1. Quelle prüfen: `get_asset_metadata(asset_id)` (Größe, Alpha-Kanal, Herkunft).
2. Operation wählen:
   | Ziel | Tool | Kernparameter |
   |---|---|---|
   | Stil/Variation | `edit_image(mode="img2img")` | `strength` 0,3 (subtil) – 0,75 (stark) |
   | Bereich ersetzen | `edit_image(mode="inpaint")` | `mask` (weiß = neu) oder transparente Bereiche der Quelle; `strength` 0,8–1,0 |
   | Erweitern | `edit_image(mode="outpaint")` | `left/top/right/bottom` Pixel, Prompt beschreibt die neue Fläche |
   | Größer | `upscale_image` | `scale` 2–4, `method` auto/model/lanczos |
   | Freistellen | `remove_background` | Ergebnis: PNG mit Alpha |
   | Format | `resize_image` | `format_preset` (z. B. `instagram_portrait`) oder `width`+`height`, `mode` crop/pad/blur/stretch |
   | Text | `add_text_overlay` | `title`, `subtitle`, `position`, `accent` |
3. Prompt bei img2img/inpaint beschreibt das **Zielbild** bzw. den neuen Bereich, nicht die Änderung („a red sports car“ statt „make it red“).
4. Ergebnis mit `analyze_image` prüfen, Vorher/Nachher dem Benutzer nennen.

## Tool-Nutzung
```text
edit_image(source="<id>", mode="img2img", prompt="watercolor painting of the same harbor scene",
           strength=0.55)
edit_image(source="<id>", mode="inpaint", mask="<mask_id>", prompt="clear blue sky with soft clouds")
edit_image(source="<id>", mode="outpaint", right=384, prompt="continuation of the sandy beach and sea")
upscale_image(source="<id>", scale=4, method="model")
remove_background(source="<id>")
resize_image(source="<id>", format_preset="instagram_story", mode="blur")
run_workflow("images/variations", {"source": "<id>", "prompt": "...", "strengths": [0.35, 0.55, 0.75]})
```
REST: `POST /api/images/{edit|inpaint|outpaint|upscale|remove_background|resize|text_overlay}`.
Formate (`resize_image`): instagram_post, instagram_portrait, instagram_story, tiktok, youtube_thumbnail,
youtube_banner, x_post, linkedin_post, facebook_cover, pinterest_pin, og_image.

## Qualitätsanforderungen
- Inpainting: Übergänge an der Maskenkante nicht sichtbar; Rest des Bildes pixelgleich (Template komponiert Original zurück).
- Outpainting: keine Naht, Perspektive und Licht passen.
- Upscaling: Schärfe steigt, keine Halos; bei Grafiken/Logos lieber Vektorisierung empfehlen.
- Freistellen: saubere Kanten (Haare, Glas kritisch prüfen) – bei Problemen `remove_background(source, alpha_matting=true)` oder ein anderes rembg-Modell (`model="isnet-general-use"`).
- QA-Score ≥ 60 wie in `image-generation`.

## Fehlerbehandlung
Siehe [../image-generation/reference/errors.md](../image-generation/reference/errors.md). Speziell:
- `validation_error` „Bild muss transparente Bereiche enthalten“ → Inpainting ohne Maske braucht Alpha → Maske anfordern.
- `capability_not_supported` bei Bearbeitung mit FLUX/Z-Image → für Bearbeitungen `sd15`/`sdxl` wählen.
- `capability_not_supported` „rembg“ → Extra installieren lassen oder Hintergrund per Inpainting ersetzen.
- `path_not_allowed` → Datei nach `assets/references/` kopieren, `rescan_assets`, dann Asset-ID nutzen.

## Beispiele
1. **Produkt freistellen und in Szene setzen**: `remove_background` → `edit_image(mode="outpaint", ...)`
   bzw. neues Hintergrundbild generieren und im Schnitt kombinieren.
2. **Quadrat → YouTube-Banner**: `edit_image(mode="outpaint", left=448, right=448, prompt=...)` →
   `resize_image(format_preset="youtube_banner", mode="crop")`.
3. **Variantenvergleich**: `run_workflow("images/variations", ...)` → Übersicht (Contact Sheet) dem Benutzer zeigen.
