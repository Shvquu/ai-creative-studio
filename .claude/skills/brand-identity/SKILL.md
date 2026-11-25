---
name: brand-identity
description: >-
  Erstellt Markenidentitäten lokal: Marken-/Zielgruppen-/Positionierungsanalyse, Farbpalette mit
  Rollen und WCAG-Kontrast, Typografie-Paarungen (freie OFL-Schriften), Logo-Konzepte (KI), Bildsprache,
  Social-Media-Asset und Brand Guidelines als HTML + Markdown + JSON. Verwenden bei „Logo“, „Brand
  Identity“, „Corporate Design“, „Markenfarben“, „welche Schrift passt“, „Brand Guidelines“, „Brand Kit“,
  „Styleguide“, „Markenauftritt für mein Startup“.
---

# Markenidentität

## Beschreibung
Der Workflow `branding/brand-kit` erstellt in einem Lauf Palette → Typografie → Logo-Konzepte →
Logo-Übersicht → Bildsprache → Social-Post → Guidelines. Einzelschritte sind als Tools verfügbar, um
gezielt zu iterieren. Logos aus Diffusionsmodellen sind **Konzepte/Moodboards**, keine fertigen Vektorlogos.

## Anwendungsfälle
Neugründung, Rebranding-Moodboard, Pitch-Präsentation, Social-Media-Grundausstattung, Styleguide für Freelancer.

## Auslösekriterien
Es geht um Wiedererkennung einer Marke (Farben, Schrift, Logo, Tonalität) statt um ein Einzelbild.

## Voraussetzungen
Name, Branche/Angebot, Zielgruppe, 3–5 Werte, Tonalität, Wunschfarbe. Bildgenerierung verfügbar
(für Logos/Bildsprache; ohne Modelle Test mit `image_provider: "mock"`).

## Arbeitsablauf (10 Schritte)
1. **Markenanalyse**: Angebot, Persönlichkeit, Werte (aus dem Briefing; max. eine Rückfragerunde).
2. **Zielgruppe**: Demografie, Bedürfnisse, Kanäle.
3. **Positionierung**: „Für [Zielgruppe] ist [Marke] die [Kategorie], die [Nutzen], weil [Beweis].“
4. **Palette**: `extract_palette(base_color, harmony)` – Harmonien: analogous, complementary, triadic, split, monochrome.
5. **Typografie**: `suggest_typography(keywords)` – Paarungen u. a. modern-tech (Space Grotesk/Inter), editorial (Playfair Display/Source Sans 3), corporate (Montserrat/Merriweather), warm-craft (Fraunces/Inter).
6. **Logo-Konzepte**: Stil `logo-flat` oder `logo-3d`, `1:1`, 4–8 Varianten; Symbol beschreiben, keinen Text erwarten.
7. **Bildsprache**: 2 Beispielbilder (`imagery_prompt`).
8. **Social-Asset**: Instagram-Post mit Tagline (automatisch im Workflow).
9. **Guidelines**: HTML (offline, Bilder eingebettet) + Markdown + `brand.json` unter `assets/exports/brand/<marke>/`.
10. **Export/Übergabe**: Asset-IDs, Pfade, nächste Schritte (Vektorisierung, Markenrecherche).

## Tool-Nutzung
```text
run_workflow("branding/brand-kit", {
  "brand_name": "Kleinwerk", "industry": "handmade ceramic tableware", "tagline": "Form folgt Gefühl.",
  "audience": "design-affine Haushalte 28–50", "brand_values": ["handwerklich", "ruhig", "nachhaltig"],
  "voice": ["warm", "präzise"], "base_color": "#8B5E3C", "harmony": "analogous",
  "logo_style": "logo-flat", "logo_concepts": 6, "logo_symbol": "a simple bowl silhouette formed by two hands",
  "imagery_prompt": "handmade ceramic bowls on linen, soft daylight, earthy tones"})
extract_palette(base_color="#8B5E3C", harmony="complementary", count=5)
suggest_typography(keywords=["warm", "craft"])
create_brand_guidelines(brand_name="Kleinwerk", palette=["#8B5E3C", "..."], heading_font="Fraunces",
                        body_font="Inter", logos=["<asset>"], values=["…"], voice=["…"])
# Felder = BrandGuideRequest (backend/orchestration/brand.py); Achtung: hier `values`, im Workflow `brand_values`
```
REST: `POST /api/brand/guidelines`, `GET /api/brand/typography?keywords=warm,craft`,
`POST /api/workflows/branding/brand-kit/run`.
3D-Logo aus finalem SVG → Skill `blender-3d` (`motion-design/logo-reveal-3d`).

## Qualitätsanforderungen
- Primärfarbe erreicht ≥ 4,5:1 Kontrast zu Weiß oder Schwarz (in Guidelines ausgewiesen).
- Palette: 1 Primär-, 1–2 Sekundär-/Akzent-, 1–2 Neutralfarben; max. 2 Schriftfamilien.
- Logo-Konzepte: einfach, bei 32 px noch erkennbar, max. 3 Farben, `analyze_image(purpose="logo")` ohne „blank“-Fehler.
- Guidelines vollständig: Positionierung, Werte, Tonalität, Farben, Typografie, Logo, Bildsprache, Do/Don't.

## Fehlerbehandlung
- Logos mit unlesbarem Pseudo-Text → Symbol-only generieren, Wortmarke mit echter Schrift setzen.
- `validation_error` „Hex-Farbe“ → Format `#RRGGBB`.
- `model_not_installed` → für Logos genügt `sdxl` oder `flux2-klein-4b`; Download nur nach Freigabe.
- Hinweis an Benutzer: Markenrechtliche Prüfung (DPMA/EUIPO) ist nicht Teil des Systems.
- Weitere Codes: [../image-generation/reference/errors.md](../image-generation/reference/errors.md).

## Beispiele
1. **Startup-Kit**: ein `brand-kit`-Lauf → Präsentation von Palette, 6 Logo-Konzepten, Guidelines-Link.
2. **Iteration**: Kunde mag Konzept 3 → `edit_image(mode="img2img", source=<logo3>, strength=0.35)` für Varianten → Guidelines neu erstellen.
3. **Vorhandenes Logo**: `extract_palette(source=<logo>)` → `suggest_typography` → `create_brand_guidelines` ohne Neugenerierung.
