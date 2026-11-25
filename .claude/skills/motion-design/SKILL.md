---
name: motion-design
description: >-
  Erstellt Motion Graphics lokal mit Remotion (React) und FFmpeg: animierte Intros/Outros,
  Titelkarten, Lower Thirds (auch transparent), kinetische Typografie, animierte Social-Posts.
  Verwenden bei „Intro“, „Outro“, „Bauchbinde“, „Lower Third“, „animierter Text“, „kinetic typography“,
  „Reel mit Textanimation“, „Titel einblenden“, „Endkarte mit Abo-Button“. Für 3D-Animationen
  (Produkt, 3D-Text, 3D-Logo) → blender-3d.
---

# Motion Design

## Beschreibung
Fünf parametrisierbare Remotion-Kompositionen (`engines/remotion/src/compositions`) plus
FFmpeg-Titelkarte als Fallback ohne Node.js. Größe, fps und Dauer kommen aus den Parametern.

## Anwendungsfälle
YouTube-Intros/Outros, Interview-Bauchbinden, Reels/TikToks mit Text-Hooks, animierte Ankündigungen,
Kapitel-Titel, Social-Ads.

## Auslösekriterien
Bewegte **Grafik/Typografie** statt KI-generierter Szenen.

## Voraussetzungen
- Remotion: Node.js ≥ 20, `cd engines/remotion && npm install` (prüfen: `list_providers` → remotion `available`).
- Lizenz: Remotion ist frei für Einzelpersonen und Firmen ≤ 3 Personen; größere Firmen brauchen eine Firmenlizenz.
- Ohne Remotion: `create_title_card` (FFmpeg) – `TitleIntro`/`Outro` fallen im Workflow automatisch darauf zurück.

## Kompositionen
| ID | Pflicht | Optional | Standard |
|---|---|---|---|
| `TitleIntro` | `title` | `subtitle`, `logo` | 1920×1080, 4 s |
| `LowerThird` | `name` | `role`, `transparent` | 1920×1080, 5 s |
| `SocialPost` | `headline` | `image`, `subline`, `cta`, `brandName` | 1080×1920, 6 s |
| `KineticText` | `phrases` (≤ 30) | – | 1080×1920, 4,5 s |
| `Outro` | – | `headline`, `cta`, `url`, `logo` | 1920×1080, 4 s |
Gemeinsam: `background`, `textColor`, `accent` (`#RRGGBB`), `fontFamily`. `logo`/`image` = Asset-ID.

## Arbeitsablauf
1. Verfügbarkeit prüfen (`list_providers`).
2. Texte kürzen: Titel ≤ 5 Wörter, Phrasen ≤ 3 Wörter, Lesezeit ≥ 1,5 s + 0,3 s/Wort.
3. Farben aus der Marke (Skill `brand-identity`), Kontrast ≥ 4,5:1.
4. Entwurf in kleiner Auflösung rendern (z. B. 960×540), dann final.
5. `analyze_video(expected_duration_s=…)`; Einbau in den Schnitt über `video-editing`.

## Tool-Nutzung
```text
render_motion_graphics(composition="TitleIntro", props={"title": "Nordlicht Kaffee",
    "subtitle": "Ehrlich geröstet.", "logo": "<asset>", "accent": "#F59E0B", "background": "#0F172A"},
    width=1920, height=1080, duration_s=4)
render_motion_graphics(composition="KineticText", props={"phrases": ["Lokal.", "Kostenlos.", "Kreativ."]},
    width=1080, height=1920, duration_s=4.5)
render_motion_graphics(composition="LowerThird", props={"name": "Alex Beispiel", "role": "Röstmeisterin",
    "transparent": true})
create_title_card(title="Kapitel 1", subtitle="Herkunft", duration_s=3)
run_workflow("motion-design/title-intro", {"title": "...", "subtitle": "...", "kind": "Outro", "format": "9:16"})
run_workflow("social-media/instagram-post", {"headline": "...", "animated": true})
```
REST: `POST /api/motion/render` (Body: `composition`, `props`, `width`, `height`, `fps`, `duration_s`,
`transparent` → MOV/ProRes 4444 mit Alpha), `GET /api/motion/compositions`.
Remotion Studio zur Vorschau: `cd engines/remotion && npm run dev`.

## Qualitätsanforderungen
- Text vollständig im Safe-Area-Bereich (≥ 5 % Rand), keine Überläufe bei langen Titeln (kürzen).
- Dauer exakt wie angefordert (±0,1 s), fps 30 (Standard), keine schwarzen Frames außer gewolltem Fade.
- Transparente Lower Thirds nur als MOV; MP4 hat keinen Alphakanal.

## Fehlerbehandlung
- `tool_not_found` „Remotion ist nicht installiert“ → `npm install` im Remotion-Ordner oder FFmpeg-Titelkarte.
- `validation_error` „Prop … erforderlich / unbekannte Props“ → Tabelle oben.
- `external_process_error` (Remotion) → `details.log_tail`; häufig fehlender Chrome-Headless-Download
  (`npx remotion browser ensure` im Remotion-Ordner, benötigt einmalig Internet).
- Weitere Codes: [../image-generation/reference/errors.md](../image-generation/reference/errors.md).

## Beispiele
1. **YouTube-Paket**: `TitleIntro` (4 s) + `Outro` mit CTA „Abonnieren“ → `video-editing` hängt beides an den Hauptclip.
2. **Reel-Hook**: `KineticText` mit 3 Phrasen + Musik (`add_audio`).
3. **Interview**: `render_motion_graphics(composition="LowerThird", props={...}, transparent=true)` → MOV mit Alpha, im Schnittprogramm überlagern.
