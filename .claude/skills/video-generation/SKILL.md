---
name: video-generation
description: >-
  Erzeugt KI-Videoclips lokal mit Wan 2.1/2.2 über ComfyUI: Text-to-Video, Image-to-Video und
  mehrszenige Videos aus Storyboards – mit Hardwareprüfung, Kamerabewegungen, Frame-Regeln (4n+1),
  Interpolation und automatischem Fallback auf Ken-Burns-Videos ohne GPU. Verwenden bei „erstelle ein
  Video/einen Clip“, „animiere dieses Bild“, „Text zu Video“, „Werbespot“, „Reel mit KI-Szenen“,
  „lass die Kamera um das Produkt fahren“. Schnitt/Audio/Untertitel → video-editing,
  Szenenplanung → storyboard-creation.
---

# Videogenerierung

## Beschreibung
Wan-Modelle erzeugen 2–5 s lange Clips. Das System wählt das Modell nach Hardware, rundet Frames auf
4n+1, setzt modellgerechte Auflösungen und speichert Clips als MP4 (H.264). Ohne GPU gibt es **keine**
KI-Videos – die Video-Workflows wechseln dann automatisch auf `videos/kenburns-slideshow`.

## Anwendungsfälle
- Atmosphärische B-Roll, Produkt-Kamerafahrten, animierte Key Visuals
- Social-Clips (9:16), Werbespots aus mehreren Szenen
- Image-to-Video aus generierten oder hochgeladenen Bildern

## Auslösekriterien
Bewegtbild soll **generiert** werden. Vorhandene Clips schneiden → `video-editing`;
reine Text-/Grafikanimation → `motion-design`; 3D → `blender-3d`.

## Voraussetzungen
| Profil | Modell | Modus | Auflösung / fps | Download |
|---|---|---|---|---|
| low (GPU ≥ 6 GB) | `wan21-t2v-1.3b` | nur T2V | 832×480 / 16 | 9,8 GB |
| mid | `wan22-ti2v-5b` | T2V + I2V | 1280×704 / 24 | 18,2 GB |
| high | `wan22-i2v-14b` | I2V (4 Schritte) | 832×480 / 16 | 38 GB, 64 GB RAM |
CPU-only: kein KI-Video → `videos/kenburns-slideshow`. Prüfen mit `get_hardware_profile` und `get_system_status` (`capabilities`).

## Arbeitsablauf
1. Hardware prüfen; bei `cpu_only` den Fallback **vorher** ankündigen.
2. Modus wählen: Image-to-Video bevorzugen (bessere Kontrolle über Look und Komposition).
3. Prompt: Subjekt → Aktion → Umgebung → Kamera → Licht → Stil (Skill `prompt-engineering`).
   Kamera zusätzlich als `camera_move`: static, dolly-in, dolly-out, pan-left, pan-right, orbit,
   tilt-up, crane-up, tracking, handheld, zoom-in.
4. Dauer als `duration_s` (Backend → Frames 4n+1, begrenzt durch Modell/Profil).
5. `estimate_cost(job_type="video.generate", params)` → `resources.est_seconds` dem Benutzer nennen.
6. Ausführen, mit `wait_for_job` (Timeout 600 s, ggf. wiederholt) verfolgen.
7. `analyze_video`: eingefroren (Standbild statt Bewegung), Flicker, schwarze Frames.
8. Optional: `interpolate_video(target_fps=48)` für flüssigere Bewegung; Übergabe an `video-editing`.

## Tool-Nutzung
```text
generate_video(prompt="steam rising from a ceramic coffee cup on a wooden table, morning sunlight
               through the window, shallow depth of field", camera_move="dolly-in",
               aspect_ratio="16:9", duration_s=3)
generate_video(prompt="the waves roll gently onto the shore", image="<asset_id>", camera_move="pan-right")
run_workflow("videos/image-to-video", {"prompt": "...", "style": "cinematic", "duration_s": 3})
run_workflow("videos/text-to-video", {"prompt": "...", "camera_move": "orbit", "interpolate_to_fps": 32})
run_workflow("videos/storyboard-to-video", {"scenes": [...], "music": "<audio_id>", "subtitles": true})
run_workflow("videos/kenburns-slideshow", {"scenes": [...]})          # CPU-tauglich
```
REST: `POST /api/videos/generate` · `POST /api/workflows/videos/storyboard-to-video/run`.
CLI: `python -m backend.cli run-workflow videos/text-to-video --inputs '{"prompt":"..."}'`.

## Qualitätsanforderungen
- `analyze_video`: Score ≥ 60, keine schwarzen Frames > 0,5 s, eingefroren < 60 % der Dauer, Flicker ≤ 25.
- fps entspricht dem Modell (16 bzw. 24) bzw. dem Interpolationsziel.
- Visuell: kein Morphing von Gesichtern/Händen im Fokus, Motiv bleibt konsistent, Kamerabewegung wie angefordert.
- Ergebnis berichtet `fallback_used`, wenn statt KI-Video Ken Burns genutzt wurde.

## Fehlerbehandlung
Siehe [../image-generation/reference/errors.md](../image-generation/reference/errors.md). Speziell:
- `hardware_insufficient` (keine GPU) → `run_workflow("videos/kenburns-slideshow", ...)` anbieten.
- `generation_error` OOM → kürzere Dauer, `aspect_ratio` mit weniger Pixeln, kleineres Modell (`wan21-t2v-1.3b`), ComfyUI `--lowvram`.
- `capability_not_supported` „image_to_video“ bei `wan21-t2v-1.3b` → Wan 2.2 nutzen oder Text-to-Video.
- `model_not_installed` → Downloadbefehl mit Größe nennen (Wan 14B ≈ 38 GB!), Freigabe abwarten.
- `timeout` → Benutzer informieren; Generierung dauert auf Mittelklasse-GPUs mehrere Minuten pro Clip.

## Beispiele
1. **Produktclip (mid)**: Referenzbild mit `product-photography` → `generate_video(image=..., camera_move="orbit", duration_s=4)` → `analyze_video`.
2. **30-s-Werbespot**: Storyboard mit 8 Szenen à 3–4 s (Skill `storyboard-creation`) → `videos/storyboard-to-video` mit Musik + Untertiteln.
3. **Laptop ohne GPU**: gleicher Auftrag → `videos/kenburns-slideshow` mit denselben `scenes`; Ergebnis als „Slideshow mit Kamerafahrten“ kommunizieren.
