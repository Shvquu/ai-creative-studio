---
name: video-editing
description: >-
  Schneidet und finalisiert Videos lokal mit FFmpeg: Timeline aus Clips und Bildern (Ken Burns),
  Übergänge (xfade), Trimmen, Musik ersetzen/mischen mit Lautheitsnormalisierung und Fades, Untertitel
  (eingebrannt oder als Spur), Seitenverhältnisse (blur/crop/pad), Formatkonvertierung (MP4, WebM, MOV,
  GIF, Audio), Frame-Extraktion, Frame-Interpolation und Multi-Format-Export. Verwenden bei „schneide …
  zusammen“, „Übergang“, „Musik drunter“, „Untertitel“, „kürzen“, „Hochformat für TikTok/Reels“,
  „als GIF“, „Frames exportieren“, „flüssiger machen“, „für alle Plattformen exportieren“.
---

# Videoschnitt & Export

## Beschreibung
Alle Operationen laufen als Jobs über den FFmpeg-Provider (`backend/providers/ffmpeg.py`) mit
validierten Parametern – keine freien FFmpeg-Kommandos. Ausgabe: H.264/AAC, yuv420p, `+faststart`.

## Anwendungsfälle
Clips verbinden, Bilder zu Video, Musik/Untertitel, Plattform-Formate, Kompression, GIFs, Standbilder.

## Auslösekriterien
Vorhandene Medien sollen geschnitten, kombiniert, vertont oder exportiert werden.

## Voraussetzungen
FFmpeg/FFprobe installiert (`list_providers` → ffmpeg verfügbar). Medien als Assets; Musik/SRT in
`assets/references/` (nach manuellem Kopieren `rescan_assets`). Nutzungsrechte an Musik beim Benutzer erfragen.

## Arbeitsablauf
1. `get_video_info` für jeden Clip (Dauer, fps, Auflösung, Audio).
2. Schnittplan: Reihenfolge, Dauer, Übergang, Musik, Untertitel-Cues `{start_s, end_s, text}`.
3. Bevorzugt **ein** `render_video`-Aufruf (Timeline); Einzeltools für Korrekturen.
4. Plattform-Exporte mit `resize_video` bzw. Workflow `social-media/multi-format-export`.
5. `analyze_video` mit Erwartungen; Übergabe an `quality-control`.

## Tool-Nutzung
```text
render_video(clips=[{"source": "<img1>", "duration_s": 3, "ken_burns": {"zoom": "in", "pan": "left"}},
                    {"source": "<clip2>", "start_s": 0.5, "end_s": 3.5}],
             width=1920, height=1080, fps=30, transition="dissolve", transition_duration=0.6,
             audio={"source": "<music>", "fade_out_s": 1.5},
             subtitles=[{"start_s": 0.3, "end_s": 2.6, "text": "Ehrlich geröstet."}])
merge_videos(sources=["<a>", "<b>", "<c>"], transition="fade", transition_duration=0.5)
trim_video(source="<id>", start_s=1.0, end_s=6.5)
add_audio(video="<id>", audio="<music>", mode="mix", volume=0.6, fade_in_s=0.5, fade_out_s=2)
add_subtitles(video="<id>", subtitles="<srt_asset>", burn_in=true)
resize_video(source="<id>", aspect_ratio="9:16", mode="blur")
convert_video(source="<id>", format="gif")          # webm, mov, mkv, mp3, wav, m4a …
extract_frames(source="<id>", count=8)
interpolate_video(source="<id>", target_fps=48)      # motion = Bewegungskompensation, blend = schnell
create_title_card(title="Kapitel 2", subtitle="Die Röstung", duration_s=3)
run_workflow("social-media/multi-format-export", {"video": "<id>", "formats": ["16:9", "9:16", "1:1"], "max_size_mb": 50})
```
REST: `POST /api/process/{render|merge|trim|add_audio|add_subtitles|resize|convert|extract_frames|interpolate|compress|title_card}`,
`GET /api/process/info?path=<id>`.
Übergänge: none, fade, dissolve, wipeleft, wiperight, wipeup, wipedown, slideleft, slideright, slideup,
slidedown, circleopen, circleclose, radial, smoothleft, smoothright, fadeblack, fadewhite, zoomin, pixelize, hblur.
Ken Burns: `zoom` in/out/none, `pan` none/left/right/up/down, `strength` 0–0,6.

## Qualitätsanforderungen
- Dauer = Summe der Clips − Übergänge (± 5 %); fps konstant; Audio vorhanden, wenn Musik gewünscht.
- Lautheit −16 LUFS (bei `normalize`), Musik endet mit Fade, keine Klicks an Schnitten.
- Untertitel ≤ 2 Zeilen, ≤ 42 Zeichen/Zeile, ≥ 1,2 s Standzeit, im Safe-Area-Bereich.
- Plattform: 16:9 1920×1080, 9:16 1080×1920, 1:1 1080×1080 (`validate_resolution(preset="reels")` etc.).
- `analyze_video` Score ≥ 60, keine schwarzen Frames > 0,5 s.

## Fehlerbehandlung
Siehe [../image-generation/reference/errors.md](../image-generation/reference/errors.md). Speziell:
- `external_process_error` → `details.stderr_tail` lesen; meist defekte/fehlende Eingabe → `get_video_info`.
- `validation_error` „duration_s ist für Bilder erforderlich“ → bei Bild-Clips Dauer angeben.
- `validation_error` „Untertiteldatei muss .srt, .vtt oder .ass sein“.
- `tool_not_found` (ffmpeg) → Installation laut `docs/INSTALLATION.md`.
- `timeout` bei sehr langen Renderings → in Abschnitten rendern und mit `merge_videos` verbinden.

## Beispiele
1. **Reel aus 4 KI-Clips**: `merge_videos(transition="none")` → `add_audio(mode="replace")` → `add_subtitles(burn_in=true)` → `resize_video("9:16", "crop")`.
2. **Foto-Slideshow mit Musik**: `render_video` mit 10 Bild-Clips (Ken Burns), `transition="fade"`, `audio`.
3. **Plattform-Paket**: `run_workflow("social-media/multi-format-export", ...)` + `convert_video(format="gif")` für eine Vorschau.
