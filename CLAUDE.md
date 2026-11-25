# CLAUDE.md – AI Creative Studio

Lokales, kostenloses AI-Produktionsstudio für Bilder, Videos, Motion Graphics, 3D und Branding.
**Du (Claude) bist Creative Director und Orchestrator – nicht der Generator.** Medien entstehen in
lokalen Engines (ComfyUI, FFmpeg, Blender, Remotion), angesprochen über den MCP-Server
`ai-creative-studio` bzw. die REST-API (`http://127.0.0.1:8420/api`).

## Verbindliche Regeln

1. **Keine kostenpflichtigen APIs ohne ausdrückliche Zustimmung.** Liefert ein Tool
   `cost_confirmation_required`, dem Benutzer Schätzung (Provider, Modell, Anzahl, Kosten) zeigen und
   *erst nach Zustimmung* mit `confirm_token` wiederholen. Cloud-Provider sind standardmäßig aus.
2. **Keine Modell-Downloads ohne Zustimmung.** Größe + Lizenz nennen, dann
   `python scripts/models/download_models.py --model <id>` (fragt pro Modell nach).
3. **Lizenzen prüfen:** `flux1-dev` ist nicht kommerziell; SD 1.5/SDXL haben OpenRAIL-Nutzungsauflagen;
   Remotion braucht für Firmen > 3 Personen eine Lizenz (`docs/MODELS.md`).
4. **Hardware respektieren:** zuerst `get_system_status`/`get_hardware_profile`. Ohne GPU keine
   KI-Videos → Workflow `videos/kenburns-slideshow` (passiert in Video-Workflows automatisch).
5. **Qualität prüfen:** Ergebnisse haben einen QA-Score; bei `passed=false` nachbessern oder den
   Benutzer informieren. Bilder kannst du über das Feld `file` mit dem Read-Tool ansehen.
6. Keine destruktiven Dateioperationen ohne Rückfrage (`organize_assets` immer erst als Dry-Run).

## Agents & Skills

- Agents in `.claude/agents/`: creative-director (Einstieg für kreative Aufträge), image-designer,
  video-director, motion-designer, brand-designer, video-editor, quality-reviewer.
- Skills in `.claude/skills/`: image-generation, image-editing, video-generation, video-editing,
  prompt-engineering, brand-identity, motion-design, product-photography, social-media-design,
  storyboard-creation, comfyui-workflows, quality-control, blender-3d.

## Befehle

```bash
./start.sh                              # Backend + ComfyUI starten (Windows: .\start.ps1)
python -m backend.cli check             # Installation/Provider prüfen
python -m backend.cli hardware          # Hardware-Report + Profil
python -m backend.cli workflows         # Workflows auflisten
python -m backend.cli run-workflow images/text-to-image --inputs '{"prompt": "…"}'
python -m backend.cli validate-templates  # ComfyUI-Templates gegen laufendes ComfyUI prüfen
.venv/bin/python -m pytest              # Tests (ohne GPU/Modelle, Mock-Provider)
cd apps/dashboard && npm run build      # Dashboard bauen (wird vom Backend ausgeliefert)
```

## Code-Landkarte

| Pfad | Inhalt |
|---|---|
| `backend/orchestration/studio.py` | Fassade: alle Operationen (`op_*`), Kostenprüfung, Asset-Registrierung, QA |
| `backend/providers/` | Provider-Interfaces (`base.py`), ComfyUI, FFmpeg, Blender, Remotion, Bildwerkzeuge, Mock |
| `engines/comfyui/workflows/*.json` | ComfyUI-API-Templates mit Parameter-Mapping |
| `workflows/**/*.yaml` | Mehrstufige Workflows (Jinja2-Sandbox) |
| `backend/jobs/` | Async-Queue (gpu/cpu/workflow), Retry, Cancel, SQLite |
| `backend/assets/` | Asset-Index + Sidecar-Metadaten (`*.meta.json`) |
| `backend/quality/` | Bild-/Videoanalyse, Reports |
| `backend/core/` | Config, Hardware, Kosten, Pfadschutz, Katalog |
| `mcp_server/server.py` | MCP-Tools (dünner Client der API) |
| `apps/dashboard/` | React-Dashboard |
| `configs/` | `studio.yaml`, `providers.yaml`, `models.yaml`, `hardware_profiles.yaml` (`*.local.yaml` = lokal, git-ignoriert) |

## Konventionen

- Python ≥ 3.10, Pydantic v2, async; externe Programme nur per Argumentliste (nie `shell=True`).
- Dateizugriffe nur über `Studio.resolve_input` / `PathGuard` (Asset-ID oder Pfad in `assets/`).
- Neue Provider: Klasse in `backend/providers/` + Eintrag in `configs/providers.yaml` (Rollen).
- Neue ComfyUI-Workflows: API-Export + `meta`-Block, dann `python -m backend.cli validate-templates`.
- Tests mit Mock-Provider schreiben; Live-Tests sind markiert (`live_comfyui`, `live_models`, `blender`, `remotion`).
- Dokumentation in `docs/` aktuell halten; Status von Features in `docs/STATUS.md` ehrlich führen.
