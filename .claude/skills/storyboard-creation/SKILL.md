---
name: storyboard-creation
description: >-
  Entwickelt Storyboards für Videos: Dramaturgie, Szenenliste mit Bild-/Bewegungsprompts, Dauer,
  Kamerabewegung und Untertitel – direkt im Eingabeformat der Workflows `videos/storyboard-to-video`
  und `videos/kenburns-slideshow`. Optional mit Vorschau-Standbildern und Kontaktbogen. Verwenden bei
  „Storyboard“, „Szenenplan“, „Ablauf für den Werbespot“, „Shotlist“, „plane ein 30-Sekunden-Video“,
  „Erklärvideo in Szenen“.
---

# Storyboard-Erstellung

## Beschreibung
Ein Storyboard ist hier ein JSON-Objekt, das ohne Umbau an die Video-Workflows übergeben werden kann.
Jede Szene ist eine Einstellung (ein KI-Clip bzw. ein Standbild mit Kamerafahrt).

## Anwendungsfälle
Werbespots, Produktvideos, Social-Reels, Erklärvideos, Trailer, Präsentationsvideos, Pitch-Animatics.

## Auslösekriterien
Ein Video mit mehr als einer Einstellung soll entstehen oder der Benutzer will den Ablauf vorab sehen.

## Voraussetzungen
Briefing (Ziel, Kernbotschaft, Länge, Kanal/Format). Für Vorschaubilder: Bildgenerierung verfügbar
(oder `image_provider: "mock"` für reine Layout-Animatics).

## Arbeitsablauf
1. **Dramaturgie** festlegen: Hook (0–3 s) → Problem/Kontext → Lösung/Produkt → Nutzen → CTA.
   Social: Hook in Szene 1, Text groß; YouTube: ruhigerer Aufbau.
2. **Länge → Szenen**: KI-Clips 2–5 s; Faustregel `Szenen ≈ Gesamtdauer / 3,5`. Übergänge kosten je ~0,6 s.
3. **Szenen schreiben** ([templates/storyboard.json](templates/storyboard.json)):
   - `prompt` (Englisch, Subjekt + Aktion + Umgebung + Licht; siehe `prompt-engineering`)
   - `duration_s` (2–5, Ken Burns bis 20)
   - `camera` ∈ static, dolly-in, dolly-out, pan-left, pan-right, orbit, tilt-up, crane-up, tracking, handheld, zoom-in
   - `caption` (Deutsch, ≤ 42 Zeichen, optional; wird zum Untertitel)
4. **Kontinuität**: gleiche Figur/Produkt-Beschreibung wortgleich in jeder Szene wiederholen; Licht und
   Tageszeit konsistent; Stil global über `style`.
5. **Vorschau** (optional, empfohlen vor teurer Videogenerierung): je Szene ein Standbild
   (`generate_image`, gleicher Stil/Seitenverhältnis) und Übersicht zeigen; Freigabe einholen.
6. **Übergabe** an `video-generation` (`videos/storyboard-to-video`) – ohne GPU automatisch Ken Burns.

## Tool-Nutzung
```text
get_presets()                       # Kamera, Stile, Übergänge
generate_image(prompt=scene.prompt, style="cinematic", aspect_ratio="16:9")      # Vorschau je Szene
run_workflow("videos/storyboard-to-video", {
  "scenes": [...], "style": "cinematic", "aspect_ratio": "16:9", "transition": "fade",
  "music": "<audio_asset>", "subtitles": true, "title": "Nordlicht Launch"})
run_workflow("videos/kenburns-slideshow", {"scenes": [...], "style": "cinematic"})   # Animatic/CPU
estimate_cost(job_type="workflow.run", params={...})
```
CLI: `python -m backend.cli run-workflow videos/storyboard-to-video --inputs storyboard.json`
(die Datei enthält dann genau das `inputs`-Objekt).

## Qualitätsanforderungen
- Gesamtdauer ±10 % der Vorgabe; jede Szene hat genau eine klare Aussage und eine Bewegung.
- Captions lesbar (≤ 42 Zeichen, ≥ 1,2 s sichtbar), Hook in den ersten 3 s.
- JSON validiert gegen das Workflow-Schema (`get_workflows` → Eingaben `scenes`, `style`, `aspect_ratio`, `transition`).
- Keine realen Personen/Marken, keine Szenen, die das Modell nicht kann (lesbarer Text im Bild, viele Personen mit Händen im Fokus).

## Fehlerbehandlung
- `validation_error` bei `scenes` → Liste von Objekten mit `prompt` prüfen; Zahlen als Zahlen, nicht Strings.
- `hardware_insufficient` / `fallback_used` → Benutzer informieren, dass Ken-Burns-Variante entstanden ist.
- Lange Laufzeit → zuerst Animatic (`videos/kenburns-slideshow`), dann KI-Video nach Freigabe.
- Weitere Codes: [../image-generation/reference/errors.md](../image-generation/reference/errors.md).

## Beispiele
1. **15-s-Reel (9:16)**: 4 Szenen (Hook 3 s, Produkt 4 s, Nutzen 4 s, CTA 4 s), `transition: "none"` für Tempo, Captions als Untertitel.
2. **30-s-Werbespot (16:9)**: 8 Szenen à 3,5 s, `cinematic`, Musik mit Fade-out, danach Outro über `motion-design`.
3. **Animatic ohne GPU**: dasselbe Storyboard mit `videos/kenburns-slideshow` zur Abstimmung mit dem Kunden.
