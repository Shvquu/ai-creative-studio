---
name: comfyui-workflows
description: >-
  Erklärt, prüft und erweitert die ComfyUI-Workflow-Templates des Studios (API-Format mit
  Parameter-Mapping in engines/comfyui/workflows/*.json): eigene ComfyUI-Workflows einbinden,
  Parameter zuordnen, LoRAs, Uploads, Validierung gegen eine laufende ComfyUI-Instanz und Modellbedarf.
  Verwenden bei „eigenen ComfyUI-Workflow einbinden“, „Workflow als Template speichern“, „neues Modell
  unterstützen“, „Template validieren“, „warum lehnt ComfyUI den Workflow ab“, „welche Nodes braucht …“.
---

# ComfyUI-Workflows & Templates

## Beschreibung
Das Backend spricht ComfyUI ausschließlich über die HTTP/WebSocket-API an (`/prompt`, `/history`,
`/view`, `/upload/image`, `/interrupt`, `/queue`, `/object_info`, `/models/{folder}`). Generiert wird mit
**Templates**: ein Workflow im ComfyUI-**API-Format** plus `meta`-Block, der Studio-Parameter auf
Node-Eingänge abbildet. Vorhandene Templates (validiert gegen ComfyUI 0.46.0):

| Template | Aufgabe | Modelle |
|---|---|---|
| `checkpoint_txt2img` / `_img2img` / `_inpaint` / `_outpaint` | Bild | `sd15`, `sd15-lcm`, `sdxl`, eigene Checkpoints |
| `flux_schnell_txt2img` | Bild | `flux1-schnell`, `flux1-dev` |
| `flux2_klein_txt2img` | Bild | `flux2-klein-4b` |
| `z_image_turbo_txt2img` | Bild | `z-image-turbo` |
| `esrgan_upscale` | Upscale | `realesrgan-x4` |
| `wan21_t2v` | Video T2V | `wan21-t2v-1.3b` |
| `wan22_5b_t2v` / `wan22_5b_i2v` | Video | `wan22-ti2v-5b` |
| `wan22_14b_i2v` | Video I2V | `wan22-i2v-14b` |
| `smoke_test_image` / `smoke_test_video` | Funktionstest ohne Modelle | – |

## Anwendungsfälle
Eigene Community-Workflows nutzen, neues Modell anbinden, Fehlerdiagnose bei abgelehnten Workflows,
Prüfung nach ComfyUI-Updates.

## Auslösekriterien
Es geht um die Struktur/Technik von ComfyUI-Workflows, nicht um das Generieren selbst
(→ `image-generation`, `video-generation`).

## Voraussetzungen
Laufendes ComfyUI (Standard `http://127.0.0.1:8188`), Zugriff auf `engines/comfyui/workflows/`.
Custom Nodes nur, wenn der Benutzer sie installiert hat – Templates im Repo verwenden nur Core-Nodes.

## Template-Format
```jsonc
{
  "meta": {
    "id": "my_template",                    // eindeutig, = Dateiname ohne .json
    "name": "Mein Workflow", "task": "text_to_image", "kind": "image",
    "family": "sdxl", "description": "…",
    "parameters": {
      "prompt":   {"targets": [["6", "text"]], "required": true},
      "width":    {"targets": [["5", "width"], ["8", "width"]], "default": 1024},
      "model":    {"targets": [["4", "ckpt_name"]], "default": "sd_xl_base_1.0.safetensors"},
      "image":    {"targets": [["10", "image"]], "required": true}
    },
    "uploads": ["image"],                   // Parameter = lokale Datei → wird vorher nach ComfyUI hochgeladen
    "lora_anchor": {"model": ["4", 0], "clip": ["4", 1]},   // LoRA-Kette wird hier eingefügt
    "outputs": ["9"]                        // Node-IDs, deren Dateien übernommen werden
  },
  "workflow": { "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "…"}}, "…": {} }
}
```
- `targets`: Liste `[node_id, input_name]`; ein Parameter kann mehrere Eingänge setzen.
- Standard-Parameternamen (vom Backend befüllt): `prompt`, `negative_prompt`, `model`, `width`, `height`,
  `batch_size`, `seed`, `steps`, `cfg`, `sampler`, `scheduler`, `strength`, `image`, `mask`, `frames`, `fps`,
  `filename_prefix`. Unbekannte Werte werden abgelehnt, `None` lässt den Template-Default stehen.
- Dynamische Eingänge (z. B. `SaveVideo`) werden mit Punkt adressiert: `"format": "mp4", "format.codec": "h264"`.
- Videoausgaben erscheinen in `/history` unter `outputs[node].images` mit `animated: [true]` – der Collector sammelt alle Dateien.

## Arbeitsablauf: eigenen Workflow einbinden
1. In ComfyUI den Workflow bauen und testen → Menü **Workflow → Export (API)** bzw. „Save (API Format)“.
2. Datei als `engines/comfyui/workflows/<id>.json` mit `meta` + `workflow` (Export-Inhalt) anlegen.
3. Parameter-Ziele eintragen (Node-IDs aus dem Export), `outputs` setzen, Uploads markieren.
4. Validieren: `python -m backend.cli validate-templates` (prüft Node-Klassen, Eingangsnamen, Enum-Werte
   gegen `/object_info` der laufenden Instanz). Strukturfehler meldet das Backend beim Start.
5. Optional Modell in `configs/models.yaml` eintragen (`tasks: {text_to_image: <template_id>}`, Dateien mit URL/Größe/Lizenz),
   damit Auswahl, Downloader und Hardwareprüfung es kennen.
6. Testen: `generate_image(prompt="test", model="<catalog_id>")` bzw. `template`-Parameter über REST.

## Tool-Nutzung
```text
get_available_models()          # Katalog + installierte Dateien + Hardware-Passung
get_system_status()             # comfyui.available, Version, Geräte
generate_image(prompt="…", model="sdxl")                     # Template über Katalog
```
MCP: `get_comfyui_templates()` (alle Templates + Parameter), `run_smoke_test()` (Anbindung ohne Modelle prüfen). REST: `GET /api/comfyui/templates`, `GET /api/models`.
CLI: `python -m backend.cli validate-templates` · `python -m backend.cli check`.

## Qualitätsanforderungen
- `validate-templates` meldet `OK` für jedes Template; Smoke-Test (`smoke_test_image`) läuft durch.
- Keine fest verdrahteten absoluten Pfade, keine Custom Nodes ohne Dokumentation in `meta.requires_custom_nodes`.
- Lizenz des Modells im Katalog gepflegt (`license`, `commercial_use`).

## Fehlerbehandlung
- `model_not_installed` (ComfyUI `value_not_in_list` bei `ckpt_name`/`unet_name`/…): Datei fehlt im
  passenden Ordner (`models/checkpoints`, `diffusion_models`, `text_encoders`, `vae`, `loras`, `upscale_models`).
- `validation_error` „ComfyUI hat den Workflow abgelehnt“: `details.node_errors` lesen – falscher Eingangsname,
  falscher Link-Typ oder Enum-Wert (z. B. Sampler-Name).
- `generation_error` mit OOM → `--lowvram`, kleinere Auflösung/Frames, fp8-Varianten.
- `provider_unavailable` → ComfyUI starten (`./start.sh`).
- Übersicht: [../image-generation/reference/errors.md](../image-generation/reference/errors.md).

## Beispiele
1. **Community-SDXL-Workflow mit Refiner**: exportieren, `meta.parameters` für Prompt/Seed/Size setzen, validieren, als `model`-Variante in den Katalog.
2. **Neues LoRA**: Datei nach `ComfyUI/models/loras/`, dann `generate_image(prompt="…", model="sdxl", loras=[{"name": "file.safetensors", "strength": 0.8}])` (nur Templates mit `lora_anchor`, d. h. Checkpoint- und FLUX.1-Templates).
3. **Nach ComfyUI-Update**: `python -m backend.cli validate-templates` → bei FAIL Eingangsnamen im Template anpassen.
