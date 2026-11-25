---
name: product-photography
description: >-
  Erzeugt werbetaugliche Produktbilder lokal: Studio-Packshots, Lifestyle-Szenen, freigestellte
  Produkte (rembg), Social-Formate und 3D-Produkt-Turntables. Verwenden bei „Produktfoto“, „Packshot“,
  „E-Commerce-Bild“, „Produkt auf Marmor/Holz/weißem Hintergrund“, „freistellen“, „Amazon/Shop-Bild“,
  „Produkt in Szene setzen“, „360°-Ansicht“. Für Produktvideos mit KI → video-generation.
---

# Produktfotografie

## Beschreibung
Kombiniert Bildgenerierung mit dem Stil-Preset `product` (Studio-Softbox, nahtloser Hintergrund,
saubere Reflexionen), optionalem Freistellen und Formatexport. Für echte Produkte mit 3D-Modell
(.glb/.obj/.fbx/.stl) liefert Blender die exakteste Darstellung.

## Anwendungsfälle
Shop-Bilder, Werbeanzeigen, Kampagnen-Key-Visuals, Mockups für Pitches, Social-Posts, Turntables.

## Auslösekriterien
Ein **Produkt** steht im Mittelpunkt. Allgemeine Szenen → `image-generation`.

## Voraussetzungen
Bildmodell installiert (Fotorealismus: `z-image-turbo` > `flux2-klein-4b` > `sdxl` > `sd15-lcm`).
Freistellen: rembg-Extra. 3D: Blender (`list_providers`).

**Wichtig:** Diffusionsmodelle erfinden Produktdetails. Für reale Produkte, deren Aussehen stimmen
muss, (a) eigenes Foto als Basis mit `image-editing` (Outpainting/Hintergrund) oder (b) 3D-Modell mit
`blender-3d` verwenden – nie ein KI-Bild als Foto des echten Produkts ausgeben.

## Arbeitsablauf
1. Produkt präzise beschreiben: Form, Material, Farbe, Oberfläche, Größe, Besonderheiten (Englisch).
2. Szene wählen: Studio (`on a seamless light grey background`), Podest (`on a white marble pedestal`),
   Lifestyle (`on a sunlit kitchen counter`), Flat Lay (`top-down flat lay on linen`).
3. Licht: `soft box lighting, gentle shadow, crisp reflections`; Stimmung: premium, minimal, fresh, bold.
4. Workflow `images/product-photo` ausführen (Varianten, optional Freistellen + Social-Format).
5. QA (Schärfe, Belichtung, saubere Kanten) und Auswahl mit dem Benutzer.
6. Optional: Turntable (`motion-design/product-turntable-3d`) oder Image-to-Video (`video-generation`).

## Tool-Nutzung
```text
run_workflow("images/product-photo", {
  "product": "matte black stainless steel water bottle with a bamboo lid",
  "setting": "on a white marble pedestal with soft reflections, light grey seamless background",
  "mood": "premium, minimal", "aspect_ratio": "4:3", "variants": 3,
  "remove_background": true, "social_format": "instagram_portrait"})
generate_image(prompt="<produkt + szene>", style="product", aspect_ratio="1:1", batch_size=2)
remove_background(source="<asset>")
resize_image(source="<asset>", format_preset="instagram_post", mode="pad")
run_workflow("motion-design/product-turntable-3d", {"model": "<glb_asset>", "material": "metal", "quality": "draft"})
```
REST: `POST /api/workflows/images/product-photo/run`.

## Qualitätsanforderungen
- Produkt scharf (Laplace ≥ 40), korrekt belichtet (keine ausgefressenen Lichter > 8 % auf dem Produkt), zentriert, vollständig im Bild.
- Shop-Standard: quadratisch, ≥ 1000 px lange Kante, Produkt füllt ~85 % – bei SD 1.5 vorher `upscale_image`.
- Freisteller: Alpha-Kanal vorhanden (`analyze_image` → `has_alpha`), keine Halos/Restflächen.
- Keine Fantasie-Logos/Schriftzüge auf dem Produkt (Prompt: „no text, no logo“; bei SD zusätzlich Negativ-Prompt).

## Fehlerbehandlung
- Text/Logos auf dem Produkt → Prompt „unbranded, no text“, Inpainting der Fläche.
- Ränder beim Freistellen → `edit_image(mode="inpaint")` oder anderes Ausgangsbild mit klarerem Hintergrund.
- `capability_not_supported` (rembg fehlt) → Hinweis `pip install -e ".[rembg]"`.
- Weitere Codes: [../image-generation/reference/errors.md](../image-generation/reference/errors.md).

## Beispiele
1. **Shop-Set**: product-photo mit `variants: 4`, `remove_background: true` → 4 Freisteller + Originale.
2. **Kampagne**: Lifestyle-Szene `16:9` + Social `instagram_story` + Image-to-Video-Clip mit `orbit`.
3. **Echtes 3D-Modell**: `.glb` hochladen → `product-turntable-3d` (`quality: "final"`, `vertical_version: true`).
