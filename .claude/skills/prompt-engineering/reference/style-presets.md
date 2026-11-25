# Stil-Presets & Kamera-Vokabular

Quelle: `backend/orchestration/prompts.py` (`STYLE_PRESETS`, `CAMERA_MOVES`). Das Backend hängt die
Positiv-Begriffe an den Prompt an und ergänzt – nur bei Familien mit Negativ-Prompt (SD 1.5, SDXL) – die
Negativ-Begriffe.

| Preset (`style`) | Label | Wirkung (positiv) | Gut für |
|---|---|---|---|
| `photorealistic` | Fotorealistisch | natural lighting, sharp focus, 35mm photograph | Menschen, Orte, Lifestyle |
| `cinematic` | Cinematisch | dramatic lighting, anamorphic lens, shallow DOF, film grain | Key Visuals, Storyboards, Video-Referenzen |
| `product` | Produktfotografie | studio softbox, seamless background, crisp reflections | E-Commerce, Werbung |
| `logo-flat` | Logo (flach) | minimalist flat vector logo, geometric, white background | Logo-Konzepte |
| `logo-3d` | Logo (3D) | glossy 3D emblem, studio lighting | Logo-Varianten, App-Icons |
| `isometric` | Isometrisch | isometric 3D illustration, pastel, diorama | Erklärgrafiken, Tech |
| `illustration` | Illustration | detailed digital illustration, clean linework | Editorial, Blog |
| `anime` | Anime | key visual, cel shading | Fan-/Gaming-Content |
| `watercolor` | Aquarell | soft washes, paper texture | Einladungen, sanfte Marken |
| `3d-render` | 3D-Render | global illumination, PBR materials | Produkt-Mockups |
| `social-bold` | Social Media | bold composition, saturated, negative space for text | Posts mit Textfläche |
| `thumbnail` | YouTube-Thumbnail | high impact, dramatic contrast, empty side for title | Thumbnails |

## Kamera (`camera_move` für Video)

| Wert | Phrase im Prompt |
|---|---|
| `static` | static camera, locked-off shot |
| `dolly-in` | the camera slowly dollies in towards the subject |
| `dolly-out` | the camera slowly pulls back revealing the scene |
| `pan-left` / `pan-right` | the camera pans smoothly to the left / right |
| `orbit` | the camera orbits slowly around the subject |
| `tilt-up` | the camera tilts up |
| `crane-up` | a crane shot rising upwards over the scene |
| `tracking` | tracking shot following the subject |
| `handheld` | subtle handheld camera movement |
| `zoom-in` | slow zoom in |

## Bausteine für Bild-Prompts

- **Licht**: golden hour, blue hour, overcast soft light, rim light, softbox, neon, candlelight, volumetric light
- **Objektiv**: 24mm wide angle, 35mm, 50mm, 85mm portrait lens, macro, tilt-shift, aerial drone shot
- **Komposition**: centered, rule of thirds, symmetrical, top-down flat lay, low angle, negative space on the left
- **Material/Oberfläche**: brushed aluminum, matte ceramic, frosted glass, linen texture, wet asphalt
