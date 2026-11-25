# Hardware- und Systemanalyse

> **Wichtig:** Dieses Repository wurde in einer **Cloud-Entwicklungsumgebung (Container ohne GPU)**
> aufgebaut. Ihr eigener Rechner („SuperDuperPC“) konnte aus der Cloud-Session nicht angebunden
> werden. Die Analyse unten beschreibt daher (1) die gemessene Entwicklungsumgebung und (2) die
> **automatische Erkennung**, die auf Ihrem Rechner läuft und dort das passende Profil wählt.
>
> Auf Ihrem Rechner ausführen:
>
> ```bash
> ./check-system.sh            # Linux / macOS
> ```
> ```powershell
> .\check-system.ps1           # Windows
> ```
>
> Das Ergebnis wird nach `data/reports/hardware-report.md` geschrieben und im Dashboard unter
> *Settings → Hardware* angezeigt.

---

## 1. Gemessene Entwicklungsumgebung (Cloud-Container, 2026-11-25)

Ermittelt mit `python -m backend.cli hardware` (Modul `backend/core/hardware.py`):

| Eigenschaft | Wert |
|---|---|
| Betriebssystem | Ubuntu 24.04.5 LTS (Linux 6.18, x86_64, KVM-VM) |
| CPU | Intel Xeon @ 2.10 GHz, 4 Kerne / 4 Threads (AVX-512, AMX) |
| Arbeitsspeicher | 15,7 GB |
| GPU | **keine** (kein `nvidia-smi`, kein ROCm, kein `/dev/dri`) |
| VRAM | 0 GB |
| CUDA | nicht vorhanden |
| Python | 3.12.3 (Projekt-venv), System 3.13 |
| Node.js / npm | v22.23.5 / 10.9.9 |
| FFmpeg / FFprobe | 6.1.1 |
| Blender | 4.0.2 (zu Testzwecken via apt installiert) |
| Git / Docker / uv | 2.43 / 29.9 / 0.11 |
| Freier Speicher | ~53 GB |
| Vorhandene AI-Anwendungen | keine – ComfyUI 0.46.0 wurde zu Testzwecken im CPU-Modus installiert |

**Automatisch gewähltes Profil: `low` (CPU-only).**

Konsequenzen für diese Umgebung (und jede Maschine ohne GPU):

* Bildgenerierung nur mit **SD 1.5 + LCM-LoRA** (6 Schritte, 512²) – real getestet, siehe
  `docs/STATUS.md` (Abschnitt „Live-Tests“).
* **Keine KI-Videogenerierung** (Wan-Modelle benötigen eine GPU; Text-Encoder allein ≈ 6,7 GB fp8).
  Fallback: Workflow `videos/kenburns-slideshow` (generierte Standbilder + Kamerafahrten +
  Übergänge via FFmpeg).
* Upscaling mit Real-ESRGAN funktioniert auf CPU (langsam), alternativ Lanczos.
* FFmpeg-, Blender- (Cycles CPU) und Remotion-Pipelines laufen vollständig.

---

## 2. Was die automatische Erkennung prüft

| Bereich | Quelle | Plattform |
|---|---|---|
| OS, Architektur | `platform` | alle |
| CPU-Modell, Kerne | `/proc/cpuinfo`, `sysctl`, `Win32_Processor`, `psutil` | alle |
| RAM, Speicherplatz | `psutil`, `shutil.disk_usage` | alle |
| NVIDIA-GPU, VRAM, Treiber, CUDA | `nvidia-smi` | Linux, Windows |
| AMD-GPU, VRAM | `/sys/class/drm/*/device/mem_info_vram_total`, `rocm-smi`, `/opt/rocm/.info/version` | Linux |
| Apple Silicon (MPS) | `sysctl`, `system_profiler SPDisplaysDataType` | macOS |
| Sonstige GPUs | `Win32_VideoController` (VRAM von WMI auf 4 GB gedeckelt) | Windows |
| PyTorch-Backend | `torch.cuda` / `torch.version.hip` / `torch.backends.mps` (nur falls importierbar) | alle |
| Werkzeuge | `python`, `node`, `npm`, `git`, `ffmpeg`, `ffprobe`, `blender`, `docker`, `uv` | alle |

Bei Apple Silicon wird „effektives VRAM“ als ~65 % des Unified Memory angesetzt (macOS-Standardlimit
für GPU-Speicher).

---

## 3. Hardwareprofile

Definiert in `configs/hardware_profiles.yaml`, Auswahl in `backend/core/hardware.py:select_profile`.

### Low-End
**Kriterien:** CPU-only · NVIDIA/AMD < 8 GB VRAM · DirectML (AMD/Intel unter Windows) · Apple Silicon < 24 GB

| Bereich | Empfehlung |
|---|---|
| Bildmodelle | **SD 1.5 + LCM-LoRA** (2,3 GB, 6 Schritte), SD 1.5; SDXL nur ab 6 GB VRAM |
| Auflösung | 512–768 px (lange Kante), danach Real-ESRGAN-Upscaling |
| Videomodelle | Wan 2.1 T2V 1.3B nur mit GPU ≥ 6 GB (480p, max. 33 Frames) – **ohne GPU keine KI-Videos** |
| Quantisierung | fp16-Checkpoints; ComfyUI mit `--lowvram` (GPU) bzw. `--cpu` |
| Zu langsam | SDXL auf CPU (> 10 min/Bild), jede Videogenerierung auf CPU, FLUX/Z-Image |
| Fallback | `videos/kenburns-slideshow`: Standbilder → Zoom/Pan → Übergänge → Musik/Untertitel |

### Mid-Range
**Kriterien:** 8–15 GB VRAM (z. B. RTX 3060 12 GB, 4060 Ti 16 GB mit < 32 GB RAM, 4070) · Apple Silicon 24–63 GB

| Bereich | Empfehlung |
|---|---|
| Bildmodelle | **FLUX.2 Klein 4B** (Typografie, Apache 2.0), **SDXL**; Z-Image Turbo ab 12 GB |
| Auflösung | 1024² nativ, bis 1536 px lange Kante |
| Videomodelle | **Wan 2.2 TI2V 5B** (720p/24 fps, T2V + I2V, mit Offloading), Wan 2.1 1.3B für schnelle 480p-Entwürfe |
| Quantisierung | fp8-Text-Encoder (`umt5_xxl_fp8_e4m3fn_scaled`), ComfyUI-Offloading automatisch |
| Zu langsam | Wan 2.2 14B (erfordert ≥ 16 GB VRAM + 64 GB RAM), FLUX.1 fp8 (17 GB) bei < 32 GB RAM |

### High-End
**Kriterien:** ≥ 16 GB VRAM **und** ≥ 32 GB RAM (RTX 4080/4090/5090, A-Serie) · Apple Silicon ≥ 64 GB

| Bereich | Empfehlung |
|---|---|
| Bildmodelle | **Z-Image Turbo** (Fotorealismus), FLUX.2 Klein 4B, FLUX.1 schnell fp8, SDXL |
| Auflösung | 1024²–2048 px, Batch bis 8 |
| Videomodelle | **Wan 2.2 I2V 14B fp8 + Lightning-LoRAs** (4 Schritte), Wan 2.2 5B für T2V |
| Quantisierung | fp8-Diffusionsmodelle (14B), bf16 für ≤ 6B-Modelle |
| Hinweis | Wan 14B: 2× 14,3 GB Experten – 64 GB RAM empfohlen, sonst Swapping |

---

## 4. Modellanforderungen (verifiziert)

Größen per Hugging-Face-API, Lizenzen aus den Model Cards (Stand 2026-11-25). Details in `docs/MODELS.md`.

| Modell | Download | min. / empf. VRAM | RAM | CPU | Lizenz | Kommerziell |
|---|---:|---|---|---|---|---|
| SD 1.5 + LCM | 2,3 GB | 2 / 4 GB | 8 GB | ja | OpenRAIL-M | eingeschränkt |
| SDXL Base 1.0 | 6,9 GB | 6 / 10 GB | 16 GB | nein | OpenRAIL++-M | eingeschränkt |
| FLUX.2 Klein 4B | 16,1 GB | 8 / 16 GB | 32 GB | nein | Apache-2.0 | ja |
| Z-Image Turbo | 20,7 GB | 12 / 16 GB | 32 GB | nein | Apache-2.0 | ja |
| FLUX.1 schnell fp8 | 17,2 GB | 12 / 16 GB | 32 GB | nein | Apache-2.0 | ja |
| FLUX.1 dev fp8 | 17,3 GB | 12 / 16 GB | 32 GB | nein | Non-Commercial | **nein** |
| Real-ESRGAN x4 | 0,07 GB | 1 / 2 GB | 4 GB | ja | BSD-3 | ja |
| Wan 2.1 T2V 1.3B | 9,8 GB | 6 / 10 GB | 16 GB | nein | Apache-2.0 | ja |
| Wan 2.2 TI2V 5B | 18,2 GB | 8 / 16 GB | 32 GB | nein | Apache-2.0 | ja |
| Wan 2.2 I2V 14B fp8 | 38,0 GB | 16 / 24 GB | 64 GB | nein | Apache-2.0 | ja |

*„min. VRAM“ = mit ComfyUI-Offloading lauffähig (deutlich langsamer); „empf.“ = flüssiges Arbeiten.
Text-Encoder (`qwen_3_4b`, `umt5_xxl_fp8`) werden zwischen Modellen geteilt und nur einmal geladen.*

---

## 5. Optimierungsbedarf

1. **VRAM:** GPU-Jobs laufen seriell (`jobs.gpu_concurrency: 1`), damit sich Modelle nicht gegenseitig verdrängen.
2. **RAM:** große Modelle (FLUX.1, Wan 14B) werden beim Laden komplett in den RAM gelesen → ≥ 32/64 GB.
3. **Speicher:** ein vollständiges High-End-Setup belegt > 100 GB. Der Downloader zeigt Größen
   und verlangt eine Bestätigung pro Modell (`scripts/models/download_models.py`).
4. **CPU-Modus:** nur LCM-Workflows (4–8 Schritte) sind praktikabel.
5. **Videolänge:** Wan erzeugt 2–5 s pro Clip; längere Videos entstehen durch Szenen + Schnitt (FFmpeg).
6. **Windows + AMD:** nur DirectML – Profil wird konservativ auf `low` gesetzt.

---

## 6. Manuelles Überschreiben

```yaml
# configs/studio.local.yaml
hardware:
  profile: mid   # auto | low | mid | high
```

oder `ACS__HARDWARE__PROFILE=mid` in `.env`.
