# AI Creative Studio – Dashboard

Lokales Web-Dashboard (React 19 + Vite 8 + TypeScript, ohne UI-Framework).

## Entwicklung

```bash
cd apps/dashboard
npm install
npm run dev          # http://127.0.0.1:5173 – /api wird an das Backend (127.0.0.1:8420) weitergeleitet
```

Das Backend muss laufen (`./start.sh` bzw. `python -m backend.cli serve`).

## Build

```bash
npm run build        # Typecheck + Bundle nach dist/
```

Das Backend liefert `dist/` automatisch unter http://127.0.0.1:8420/ aus (SPA-Fallback).

## Smoke-Test (Playwright)

```bash
node e2e/smoke.mjs http://127.0.0.1:8420 [--screens <ordner>] [--no-generate]
```

Öffnet alle Bereiche, prüft Überschriften und Konsolenfehler, generiert ein Bild mit dem
Mock-Provider (keine KI nötig), prüft Asset-Detailansicht, Workflow-Formular, Settings,
Theme-Umschaltung und das mobile Layout (390×844, kein horizontaler Überlauf).

## Struktur

```text
src/
  api.ts               Typisierter API-Client, Fehler-Envelope, Token, Formatierung
  state.tsx            Datenhooks, Job-Live-Updates (SSE + Polling-Fallback), Toasts,
                       Kostenbestätigung (HTTP 402 → Dialog → erneuter Request mit confirm_token)
  components/ui.tsx    Karten, Badges, Formularfelder, Modals, Drawer, Job-Listen, Asset-Grid,
                       Asset-Picker, Kosten-/Ressourcen-Schätzung
  pages/               Dashboard, ImageStudio, VideoStudio, BrandStudio, WorkflowStudio,
                       AssetLibrary, Settings
  styles.css           Design-Tokens (Dark/Light), Layout, Komponenten, Responsive
e2e/smoke.mjs          Browser-Smoke-Test
```

Navigation per Hash-Routing (`#/images`, `#/assets` …). Ein optionales API-Token
(Server mit `ACS_API_TOKEN`) wird unter *Settings → Oberfläche* lokal im Browser gespeichert.
Modell-Downloads werden bewusst **nicht** aus der Oberfläche ausgelöst – das Dashboard zeigt
den passenden Befehl (`python scripts/models/download_models.py --model <id>`).
