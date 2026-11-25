---
name: blender-3d
description: >-
  Erstellt 3D-Szenen und -Animationen headless mit Blender (Python-API): Produkt-Turntables mit
  Studio-Licht (eigene .glb/.obj/.fbx/.stl-Modelle oder Grundformen), animierte 3D-Typografie und
  3D-Logos aus SVG – als Video, Einzelbild oder Bildsequenz, optional transparent. Verwenden bei
  „3D“, „Turntable“, „360°-Produktansicht“, „3D-Logo“, „Logo-Reveal“, „3D-Text“, „Produkt rendern“,
  „Blender“, „Kamerafahrt um das Modell“.
---

# Blender 3D

## Beschreibung
Drei geprüfte Szenen-Skripte in `engines/blender/scripts/` (gemeinsame Hilfen in `acs_common.py`):

| Template | Inhalt | Wichtige `params` |
|---|---|---|
| `product_turntable` | Studio-Set, 3-Punkt-Licht, 360°-Orbit | `model_path` (Asset .glb/.gltf/.obj/.fbx/.stl/.ply) **oder** `product` (bottle, box, can, sphere, torus), `color`, `material`, `background`, `degrees`, `camera_distance` |
| `text_3d` | extrudierter Text mit Animation | `text`, `font_path`, `color`, `material`, `background`, `accent`, `extrude`, `bevel`, `animation` (rise, spin, zoom, none) |
| `logo_extrude` | SVG → 3D-Logo, SVG-Farben bleiben erhalten | `svg_path`, `color` (optional Einheitsfarbe), `material`, `background`, `extrude`, `bevel`, `degrees` |
Materialien: glossy, matte, metal, glass, plastic. Render-Optionen: `width`, `height`, `fps`, `frames`,
`samples`, `engine` (CYCLES, EEVEE), `device` (auto, cpu, gpu), `output` (video, frames, still), `transparent`.

## Anwendungsfälle
Produktpräsentationen, Shop-360°-Ansichten, Logo-Bumper, 3D-Titel für Intros, Mockups.

## Auslösekriterien
Ein 3D-Modell/SVG soll präzise dargestellt oder 3D-Bewegung erzeugt werden (exakter als KI-Video).

## Voraussetzungen
Blender ≥ 3.6 (getestet 4.0), im PATH oder `ACS__BLENDER__BLENDER_PATH`. Prüfen: `list_providers` →
blender `available`. GPU-Rendering (OptiX/CUDA/HIP/Metal) wird bei `device: auto` automatisch genutzt,
sonst Cycles CPU. Builds ohne OpenImageDenoise rendern automatisch ohne Denoiser (mehr Rauschen → mehr Samples).

## Arbeitsablauf
1. Eingaben klären: Modell/SVG (als Asset hochladen), Farben/Material, Format, Dauer.
2. **Entwurf**: 960×540, 16 Samples, kurze Dauer → Look und Kamera abstimmen.
3. **Final**: 1920×1080, 128+ Samples (CPU: Minuten pro Sekunde Video – vorher Dauer ansagen).
4. Rendern über Workflow (inkl. QA) oder direkt `render_3d`.
5. Optional Hochformat (`resize_video`, Modus blur) und Schnitt (`video-editing`).

## Tool-Nutzung
```text
run_workflow("motion-design/product-turntable-3d", {"model": "<glb_asset>", "material": "metal",
             "color": "#9CA3AF", "seconds": 4, "quality": "draft", "vertical_version": true})
run_workflow("motion-design/logo-reveal-3d", {"svg": "<svg_asset>", "material": "glossy", "quality": "final"})
render_3d(template="text_3d", params={"text": "LAUNCH", "animation": "rise", "material": "metal",
          "accent": "#38BDF8"}, width=1920, height=1080, frames=72, samples=64, output="video")
render_3d(template="product_turntable", params={"product": "bottle", "color": "#2563EB"}, output="still")
```
REST: `POST /api/render3d/render` (Body wie `render_3d`, zusätzlich `fps`, `engine`, `device`,
`transparent`, `save_blend`), `GET /api/render3d/templates`. Ausgaben: MP4 (Frames werden per FFmpeg kodiert),
PNG-Einzelbild oder PNG-Sequenz; mit `save_blend` zusätzlich die `.blend`-Szene.

## Qualitätsanforderungen
- Objekt vollständig im Bild, zentriert, Boden-Schatten vorhanden, keine Clipping-Artefakte.
- Video: fps wie angefordert, Dauer = Frames/fps, keine schwarzen Frames (`analyze_video`).
- Rauschen: bei sichtbarem Korn Samples erhöhen (Final ≥ 128).
- Logo: Proportionen und Farben wie im SVG, keine Z-Fighting-Flecken (Ebenen werden automatisch gestaffelt).

## Fehlerbehandlung
- `tool_not_found` „Blender nicht gefunden“ → Installation (blender.org) oder Pfad setzen.
- `validation_error` „Unbekannte Parameter“ / „Datei nicht gefunden“ → Tabelle oben; Dateien als Asset-ID.
- `validation_error` „logo_extrude benötigt params.svg_path“.
- `external_process_error` „Blender-Fehler“ → `details.log_tail`; häufig nicht unterstütztes Modellformat
  oder SVG ohne Pfade (Text in SVG vorher in Pfade umwandeln).
- `timeout` → weniger Samples/Frames/Auflösung, GPU-Rendering.
- Weitere Codes: [../image-generation/reference/errors.md](../image-generation/reference/errors.md).

## Beispiele
1. **Shop-Turntable**: `.glb` des Kunden → Entwurf (draft) → Freigabe → final + 9:16-Version für Reels.
2. **Logo-Bumper**: finales SVG aus `brand-identity` → `logo-reveal-3d` (3 s) → als Intro vor das Video (`video-editing`).
3. **3D-Titel**: `render_3d(template="text_3d", params={"text": "SALE", "animation": "spin"})` → mit `add_audio` vertonen.
