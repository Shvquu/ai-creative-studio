# Implementierungsplan & Risiken

Stand: 2026-11-25. Fortschritt und Testergebnisse: `docs/STATUS.md`.

## Phasen

| Phase | Inhalt | Ergebnis / Nachweis |
|---|---|---|
| **A – Discovery** | Repo-Analyse (leer), Hardware, ComfyUI-Quellcode-Analyse (v0.46.0), MCP-SDK-Analyse (2.3.0), Modell-Verifikation via HF-API | `HARDWARE_ANALYSIS.md`, `ARCHITECTURE.md`, dieser Plan |
| **B – Foundation** | Struktur, `pyproject.toml`, Config-Layering, Logging, Fehler, PathGuard, SQLite, Datenmodelle | Unit-Tests für Config/Paths/Hardware |
| **C – AI Integration** | ComfyUI-Client (HTTP+WS), Templates (SD1.5/LCM, SDXL, FLUX.1, FLUX.2 Klein, Z-Image, ESRGAN, Wan 2.1/2.2), Modellkatalog & -auswahl, Downloader | Templates gegen echtes `/object_info` validiert; Live-Generierung mit SD1.5+LCM auf CPU |
| **D – Processing** | FFmpeg-Provider, Bildwerkzeuge, Blender-Skripte, Remotion-Projekt, Qualitätsanalyse | Tests mit echten FFmpeg-/Blender-Läufen |
| **E – Orchestration** | Job-Queue, Kostenkontrolle, Workflow-Engine + YAML-Workflows, MCP-Server, Agents, Skills | MCP-Tests über In-Memory-Client, Workflow-Tests mit Mock-Provider |
| **F – Dashboard** | FastAPI-Routen, React-Dashboard (7 Bereiche), SSE | E2E-Test mit Playwright (Screenshots) |
| **G – Quality** | Fehlerbehandlung, Sicherheitsprüfung, Optimierung | vollständige Test-Suite |
| **H – Documentation** | Installation, Modelle, Workflows, MCP, Troubleshooting, Status | `docs/*` |

## Technische Risiken

| Risiko | Auswirkung | Gegenmaßnahme |
|---|---|---|
| **Keine GPU in der Entwicklungsumgebung** | Videomodelle und große Bildmodelle nicht live testbar | Templates gegen echte ComfyUI-`/object_info` validiert, modellfreie Live-Tests (Video-Pipeline mit `EmptyImage`), SD1.5+LCM real auf CPU; GPU-Pfade transparent als „nicht live getestet“ markiert |
| Hardware des Benutzers unbekannt | falsches Profil | Auto-Erkennung + `check-system`-Skripte + manueller Override |
| ComfyUI-API-Änderungen | Workflows brechen | Validator-Skript gegen `/object_info`, Versionsangabe im Status, generischer Output-Collector |
| Modell-VRAM-Bedarf schwankt (Auflösung, Frames) | OOM-Abbrüche | konservative Profile, Frame-/Auflösungslimits pro Profil, GPU-Pool = 1, Fehlermeldung mit Hinweis auf kleinere Einstellungen |
| Große Downloads (bis ~40 GB/Modell) | Speicher, Zeit | Größenanzeige, Einzelbestätigung, Speicherplatzprüfung, Wiederaufnahme per HTTP-Range |
| Lizenzen (FLUX.1-dev, Remotion) | rechtliche Risiken | `commercial_use` im Katalog, Warnung in UI/MCP, Remotion optional mit FFmpeg-Fallback |
| MCP-SDK 2.x neu (Breaking Changes ggü. 1.x) | veraltete Beispiele funktionieren nicht | gegen installierte 2.3.0 entwickelt, Version gepinnt `>=2.3,<3` |
| Windows-Pfade/Prozesse | Skripte schlagen fehl | `setup.ps1`/`start.ps1`, nur `pathlib`, keine Shell-Strings |
| Lange Jobs blockieren | schlechte UX | asynchrone Queue, Fortschritt via SSE, Cancel |

## Hardwarebedingte Einschränkungen (dieser Container)

* Kein CUDA/ROCm/MPS → `low`-Profil, CPU-Modus.
* Live getestet werden können: ComfyUI-Integration (Queue, Fortschritt, Abbruch, Upload, Download),
  SD 1.5 + LCM-Generierung, Real-ESRGAN-Upscaling (CPU), alle FFmpeg-/Blender-/Remotion-Pfade.
* Nicht live testbar: Wan-Videogenerierung, SDXL/FLUX/Z-Image in sinnvoller Zeit.
