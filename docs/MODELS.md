# Modelle & Lizenzen

Alle Modelle sind in `configs/models.yaml` katalogisiert. URLs, Dateinamen und Ordner stammen aus den offiziellen
ComfyUI-Workflow-Templates (`comfyui-workflow-templates 0.11.118`), Größen aus der Hugging-Face-API, Lizenzen aus den
Model Cards (Stand 2026-11-25). **Nichts wird automatisch heruntergeladen.**

```bash
.venv/bin/python scripts/models/download_models.py --list            # Katalog + Hardware-Eignung + Installationsstatus
.venv/bin/python scripts/models/download_models.py --recommended     # Vorschläge für dieses System
.venv/bin/python scripts/models/download_models.py --model sdxl      # einzelnes Modell (fragt nach)
```

Der Downloader zeigt Größe, Lizenz und Hardware-Eignung, prüft freien Speicher (+2 GB Reserve), fragt **pro Modell**
nach, lädt fortsetzbar (`.part` + HTTP-Range) und überspringt vollständige Dateien. Für „gated“ Modelle `HF_TOKEN`
setzen (nur Umgebungsvariable).

## Katalog (generiert)


| ID | Name | Typ | Größe | min./empf. VRAM | RAM | CPU | Lizenz | Kommerziell | Aufgaben |
|---|---|---|---:|---|---|---|---|---|---|
| `sd15-lcm` | Stable Diffusion 1.5 + LCM-LoRA (schnell) | image | 2.26 GB | 2 / 4 GB | 8 GB | ja | CreativeML OpenRAIL-M + OpenRAIL++ (LoRA) | mit Auflagen | text_to_image, image_to_image, inpaint, outpaint |
| `sd15` | Stable Diffusion 1.5 | image | 2.13 GB | 2 / 4 GB | 8 GB | ja | CreativeML OpenRAIL-M | mit Auflagen | text_to_image, image_to_image, inpaint, outpaint |
| `sdxl` | Stable Diffusion XL 1.0 Base | image | 6.94 GB | 6 / 10 GB | 16 GB | nein | CreativeML OpenRAIL++-M | mit Auflagen | text_to_image, image_to_image, inpaint, outpaint |
| `flux2-klein-4b` | FLUX.2 [klein] 4B (distilled) | image | 16.14 GB | 8 / 16 GB | 32 GB | nein | Apache-2.0 | ja | text_to_image |
| `z-image-turbo` | Z-Image Turbo | image | 20.7 GB | 12 / 16 GB | 32 GB | nein | Apache-2.0 | ja | text_to_image |
| `flux1-schnell` | FLUX.1 [schnell] (fp8, all-in-one) | image | 17.24 GB | 12 / 16 GB | 32 GB | nein | Apache-2.0 | ja | text_to_image |
| `flux1-dev` | FLUX.1 [dev] (fp8) – NICHT kommerziell | image | 17.25 GB | 12 / 16 GB | 32 GB | nein | FLUX.1 [dev] Non-Commercial License | **nein** | text_to_image |
| `realesrgan-x4` | Real-ESRGAN x4plus | upscale | 0.07 GB | 1 / 2 GB | 4 GB | ja | BSD-3-Clause | ja | upscale |
| `wan21-t2v-1.3b` | Wan 2.1 Text-to-Video 1.3B | video | 9.83 GB | 6 / 10 GB | 16 GB | nein | Apache-2.0 | ja | text_to_video |
| `wan22-ti2v-5b` | Wan 2.2 TI2V 5B (Text- & Image-to-Video, 720p) | video | 18.15 GB | 8 / 16 GB | 32 GB | nein | Apache-2.0 | ja | text_to_video, image_to_video |
| `wan22-i2v-14b` | Wan 2.2 Image-to-Video 14B (fp8 + Lightning 4-Step) | video | 38.05 GB | 16 / 24 GB | 64 GB | nein | Apache-2.0 | ja | image_to_video |

*VRAM „min.“ = lauffähig mit ComfyUI-Offloading (langsam); „empf.“ = flüssig. Text-Encoder (`qwen_3_4b`,
`umt5_xxl_fp8`) werden zwischen Modellen geteilt.*

## Lizenzhinweise

| Lizenz | Modelle | Kommerzielle Nutzung |
|---|---|---|
| Apache-2.0 | FLUX.1 schnell, FLUX.2 Klein 4B, Z-Image Turbo, Wan 2.1/2.2 | erlaubt |
| CreativeML OpenRAIL-M / ++-M | SD 1.5, SDXL, LCM-LoRA | erlaubt, aber mit **Nutzungsbeschränkungen** (keine verbotenen Anwendungsfälle laut Lizenz) |
| FLUX.1 [dev] Non-Commercial | FLUX.1 dev | **nicht erlaubt** – nur privat/Test |
| BSD-3-Clause | Real-ESRGAN x4plus | erlaubt |

Weitere Komponenten: ComfyUI (GPL-3.0, separat installiert), FFmpeg (LGPL/GPL), Blender (GPL),
**Remotion** (frei für Einzelpersonen und Firmen ≤ 3 Mitarbeitende, sonst Firmenlizenz: https://www.remotion.dev/license –
FFmpeg-Titelkarten sind die lizenzfreie Alternative), rembg (MIT; Modelle U²-Net Apache-2.0).
FLUX.2 Klein **9B** ist nicht im Katalog, da nicht kommerziell lizenziert.

## Eigene Modelle

* **Beliebige SD-1.5/SDXL-Checkpoints**: Datei nach `ComfyUI/models/checkpoints` – sie erscheinen in `get_available_models`
  und funktionieren mit `model: "<dateiname>.safetensors"` (generische Checkpoint-Templates).
* **LoRAs**: nach `ComfyUI/models/loras`, Nutzung über `loras: [{name, strength}]` (Checkpoint- und FLUX.1-Templates).
* **Neue Modellfamilie**: ComfyUI-Workflow als API exportieren, Template in `engines/comfyui/workflows` anlegen
  (siehe Skill `comfyui-workflows`), Katalogeintrag in `configs/models.yaml` ergänzen, Profile anpassen,
  `python -m backend.cli validate-templates` und `pytest tests/unit/test_core.py::test_catalog_consistency` ausführen.

## Download-Quellen (generiert)


**sd15-lcm**
- `checkpoints/v1-5-pruned-emaonly-fp16.safetensors` (2.13 GB) – https://huggingface.co/Comfy-Org/stable-diffusion-v1-5-archive/resolve/main/v1-5-pruned-emaonly-fp16.safetensors
- `loras/lcm-lora-sdv1-5.safetensors` (0.135 GB) – https://huggingface.co/latent-consistency/lcm-lora-sdv1-5/resolve/main/pytorch_lora_weights.safetensors

**sd15**
- `checkpoints/v1-5-pruned-emaonly-fp16.safetensors` (2.13 GB) – https://huggingface.co/Comfy-Org/stable-diffusion-v1-5-archive/resolve/main/v1-5-pruned-emaonly-fp16.safetensors

**sdxl**
- `checkpoints/sd_xl_base_1.0.safetensors` (6.94 GB) – https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0/resolve/main/sd_xl_base_1.0.safetensors

**flux2-klein-4b**
- `diffusion_models/flux-2-klein-4b.safetensors` (7.75 GB) – https://huggingface.co/Comfy-Org/flux2-klein/resolve/main/split_files/diffusion_models/flux-2-klein-4b.safetensors
- `text_encoders/qwen_3_4b.safetensors` (8.05 GB) – https://huggingface.co/Comfy-Org/z_image_turbo/resolve/main/split_files/text_encoders/qwen_3_4b.safetensors
- `vae/flux2-vae.safetensors` (0.34 GB) – https://huggingface.co/Comfy-Org/flux2-klein/resolve/main/split_files/vae/flux2-vae.safetensors

**z-image-turbo**
- `diffusion_models/z_image_turbo_bf16.safetensors` (12.31 GB) – https://huggingface.co/Comfy-Org/z_image_turbo/resolve/main/split_files/diffusion_models/z_image_turbo_bf16.safetensors
- `text_encoders/qwen_3_4b.safetensors` (8.05 GB) – https://huggingface.co/Comfy-Org/z_image_turbo/resolve/main/split_files/text_encoders/qwen_3_4b.safetensors
- `vae/ae.safetensors` (0.34 GB) – https://huggingface.co/Comfy-Org/z_image_turbo/resolve/main/split_files/vae/ae.safetensors

**flux1-schnell**
- `checkpoints/flux1-schnell-fp8.safetensors` (17.24 GB) – https://huggingface.co/Comfy-Org/flux1-schnell/resolve/main/flux1-schnell-fp8.safetensors

**flux1-dev**
- `checkpoints/flux1-dev-fp8.safetensors` (17.25 GB) – https://huggingface.co/Comfy-Org/flux1-dev/resolve/main/flux1-dev-fp8.safetensors

**realesrgan-x4**
- `upscale_models/RealESRGAN_x4plus.safetensors` (0.067 GB) – https://huggingface.co/Comfy-Org/Real-ESRGAN_repackaged/resolve/main/RealESRGAN_x4plus.safetensors

**wan21-t2v-1.3b**
- `diffusion_models/wan2.1_t2v_1.3B_fp16.safetensors` (2.84 GB) – https://huggingface.co/Comfy-Org/Wan_2.1_ComfyUI_repackaged/resolve/main/split_files/diffusion_models/wan2.1_t2v_1.3B_fp16.safetensors
- `text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors` (6.74 GB) – https://huggingface.co/Comfy-Org/Wan_2.1_ComfyUI_repackaged/resolve/main/split_files/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors
- `vae/wan_2.1_vae.safetensors` (0.25 GB) – https://huggingface.co/Comfy-Org/Wan_2.1_ComfyUI_repackaged/resolve/main/split_files/vae/wan_2.1_vae.safetensors

**wan22-ti2v-5b**
- `diffusion_models/wan2.2_ti2v_5B_fp16.safetensors` (10.0 GB) – https://huggingface.co/Comfy-Org/Wan_2.2_ComfyUI_Repackaged/resolve/main/split_files/diffusion_models/wan2.2_ti2v_5B_fp16.safetensors
- `text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors` (6.74 GB) – https://huggingface.co/Comfy-Org/Wan_2.1_ComfyUI_repackaged/resolve/main/split_files/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors
- `vae/wan2.2_vae.safetensors` (1.41 GB) – https://huggingface.co/Comfy-Org/Wan_2.2_ComfyUI_Repackaged/resolve/main/split_files/vae/wan2.2_vae.safetensors

**wan22-i2v-14b**
- `diffusion_models/wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors` (14.3 GB) – https://huggingface.co/Comfy-Org/Wan_2.2_ComfyUI_Repackaged/resolve/main/split_files/diffusion_models/wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors
- `diffusion_models/wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors` (14.3 GB) – https://huggingface.co/Comfy-Org/Wan_2.2_ComfyUI_Repackaged/resolve/main/split_files/diffusion_models/wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors
- `loras/wan2.2_i2v_lightx2v_4steps_lora_v1_high_noise.safetensors` (1.23 GB) – https://huggingface.co/Comfy-Org/Wan_2.2_ComfyUI_Repackaged/resolve/main/split_files/loras/wan2.2_i2v_lightx2v_4steps_lora_v1_high_noise.safetensors
- `loras/wan2.2_i2v_lightx2v_4steps_lora_v1_low_noise.safetensors` (1.23 GB) – https://huggingface.co/Comfy-Org/Wan_2.2_ComfyUI_Repackaged/resolve/main/split_files/loras/wan2.2_i2v_lightx2v_4steps_lora_v1_low_noise.safetensors
- `text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors` (6.74 GB) – https://huggingface.co/Comfy-Org/Wan_2.1_ComfyUI_repackaged/resolve/main/split_files/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors
- `vae/wan_2.1_vae.safetensors` (0.25 GB) – https://huggingface.co/Comfy-Org/Wan_2.1_ComfyUI_repackaged/resolve/main/split_files/vae/wan_2.1_vae.safetensors
