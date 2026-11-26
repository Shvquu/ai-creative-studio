---
name: image-generation
description: >-
  Erzeugt KI-Bilder lokal über ComfyUI (SD 1.5/LCM, SDXL, FLUX.1, FLUX.2 Klein, Z-Image Turbo) mit
  hardwaregerechter Modellwahl, Stil-Presets, Seitenverhältnissen, Varianten, Seeds, optionalem
  Upscaling und automatischer Qualitätsprüfung. Verwenden bei „generiere/erstelle/male ein Bild“,
  „Key Visual“, „Illustration“, „Hintergrundbild“, „mehrere Varianten“, „gleicher Seed“, „in 16:9“,
  „fotorealistisch“, „im Anime-/Aquarell-Stil“. Nicht für Bearbeitung vorhandener Bilder
  (→ image-editing), Produktfotos (→ product-photography), Logos (→ brand-identity) oder
  Social-Formate mit Text (→ social-media-design).
---

# Bildgenerierung

## Beschreibung
Text-to-Image über die lokale ComfyUI-Instanz. Das Backend wählt – wenn kein `model` angegeben ist –
das beste **installierte** Modell, das zum Hardwareprofil passt (`configs/hardware_profiles.yaml`),
ergänzt modellabhängige Stil-/Negativ-Begriffe (`backend/orchestration/prompts.py`), speichert jede
Datei mit Sidecar-Metadaten (Prompt, Seed, Modell, exakter Workflow) und prüft die Qualität.

## Anwendungsfälle
- Key Visuals, Moodboards, Szenenbilder, Hintergründe, Illustrationen, Konzeptkunst
- Referenzbilder für Image-to-Video (→ video-generation)
- Variantenserien mit festem Seed für A/B-Vergleiche

## Auslösekriterien
Der Benutzer möchte ein **neues** Bild aus einer Beschreibung. Bei „bearbeite / ersetze / erweitere“
→ `image-editing`; bei Text im Bild für Social → `social-media-design`.

## Voraussetzungen
- Backend läuft (`./start.sh`), ComfyUI erreichbar (`get_system_status` → `comfyui.available`).
- Mindestens ein Bildmodell installiert (`get_available_models`). Empfehlungen je Profil:
  `low` → `sd15-lcm` · `mid` → `flux2-klein-4b`, `sdxl` · `high` → `z-image-turbo`, `flux2-klein-4b`.
- Für Tests ohne Modelle: `provider: "mock"` (synthetische Bilder, **keine KI**, deutlich markiert).

## Arbeitsablauf
1. `get_hardware_profile` (einmal pro Sitzung) – Profil und `cpu_only` merken.
2. Prompt nach Skill `prompt-engineering` formulieren (Motiv, Umgebung, Licht, Kamera, Stimmung).
3. Stil-Preset wählen: photorealistic, cinematic, product, logo-flat, logo-3d, isometric, illustration,
   anime, watercolor, 3d-render, social-bold, thumbnail (`get_presets`).
4. Seitenverhältnis statt Pixelmaße: `1:1, 3:2, 2:3, 4:3, 3:4, 16:9, 9:16, 21:9` – das Backend
   setzt modellgerechte Auflösungen (SD 1.5 ≈ 512 px, SDXL/FLUX ≈ 1 MP).
5. Generieren (bei mehreren Varianten `batch_size` 2–4; Profil begrenzt: low 2, mid 4, high 8).
6. Ergebnis prüfen (`quality` im Job-Ergebnis, sonst `analyze_image`). Nicht bestanden → Prompt/Seed
   anpassen (max. 3 Iterationen), dann Benutzer fragen.
7. Optional hochskalieren (`upscale_image`, Real-ESRGAN oder Lanczos-Fallback).
8. Asset-IDs, Modell, Seed und QA-Score berichten; mit `tag_asset` taggen.

## Tool-Nutzung
```text
generate_image(prompt="a lighthouse on a cliff at dusk, waves crashing, warm window light,
               wide angle", style="cinematic", aspect_ratio="16:9", batch_size=2, wait=true)
→ {job: {...status: "succeeded", result: {asset_ids: [...], seed: 123, model: "sdxl", quality: [...]}}}

generate_image(prompt="...", model="sd15-lcm", seed=42, steps=6)          # reproduzierbar
upscale_image(source="<asset_id>", scale=2, method="auto")
run_workflow("images/text-to-image", {"prompt": "...", "style": "photorealistic",
             "aspect_ratio": "3:2", "variants": 3, "upscale": true})
```
REST: `POST /api/images/generate` (Body = Parameter) → 202 + Job; `GET /api/jobs/{id}/wait?timeout=120`.
CLI: `python -m backend.cli run-workflow images/text-to-image --inputs '{"prompt":"...","variants":2}'`.

### Komposition per ControlNet (SD 1.5)

Wenn Form/Komposition vorgegeben ist (Produktumriss, Logo-Silhouette, Skizze), ein Steuerbild mitgeben:

```
generate_image(prompt="a glossy orange planet in space", control_image="references/form.png",
               control_mode="canny", control_strength=0.8)       # Foto → Kanten
generate_image(prompt="cozy cottage, watercolor", control_image="references/skizze.png",
               control_mode="none")                               # Skizze/Scribble direkt
```

Benötigt `controlnet-canny-sd15` bzw. `controlnet-scribble-sd15` (je 0,72 GB, OpenRAIL) und ein SD-1.5-Modell;
ohne `model` wählt das Studio automatisch die beste installierte SD-1.5-Variante (z. B. `sd15-lcm`).

## Qualitätsanforderungen
- QA bestanden: Score ≥ 60 und kein „error“-Befund; Schärfe (Laplace-Varianz) ≥ 40 bei Fotos.
- Keine leeren/einfarbigen Bilder, Belichtung Ø 35–225, ausgefressene Lichter ≤ 8 %.
- Auflösung passend zum Zweck (Web ≥ 1024 px lange Kante – bei SD 1.5 danach hochskalieren).
- Visuell: keine deformierten Hände/Gesichter im Fokus, kein Pseudo-Text, Stil entspricht dem Brief.
- Lizenz: `flux1-dev` nur nicht-kommerziell; SD 1.5/SDXL mit OpenRAIL-Nutzungsregeln.

## Fehlerbehandlung
Vollständige Tabelle: [reference/errors.md](reference/errors.md). Häufig hier:
- `provider_unavailable` → „Bitte `./start.sh` ausführen (startet ComfyUI + Backend).“
- `model_not_installed` → `python scripts/models/download_models.py --model <id>` + Größe nennen, Freigabe abwarten.
- `hardware_insufficient` → kleineres Modell (`sd15-lcm`) oder geringere Auflösung vorschlagen.
- `generation_error` mit OOM-Hinweis → `batch_size` 1, kleineres Seitenverhältnis, kleineres Modell.
- `cost_confirmation_required` → Kosten nennen, fragen, erst dann `confirm_token` senden.

## Beispiele
1. **Moodboard (mid-Profil)**: 3× `generate_image(style="cinematic", aspect_ratio="16:9", batch_size=2)`
   mit Varianten der Lichtstimmung → besten Seed wählen → `upscale_image(scale=2)`.
2. **CPU-Laptop**: `generate_image(prompt=..., model="sd15-lcm", aspect_ratio="1:1")` (~1 min/Bild),
   danach `upscale_image(scale=2)`; Benutzer vorab auf Dauer hinweisen (`estimate_cost`).
3. **Reproduktion**: Sidecar lesen (`get_asset_metadata` → `sidecar.asset.seed`, `params`) und mit
   identischem `model`/`seed`/`steps`/`cfg` erneut generieren, nur den Prompt minimal ändern.
