# Fehlercodes des AI Creative Studio – Reaktionsleitfaden

Alle Tools/REST-Endpunkte liefern Fehler als `{"error": {"code", "message", "details"}}`.
Jobs speichern denselben Block in `job.error`. Diese Tabelle gilt für **alle** Skills.

| Code | HTTP | Bedeutung | Richtige Reaktion |
|---|---:|---|---|
| `provider_unavailable` | 503 | ComfyUI (o. a.) nicht erreichbar | Benutzer bitten, `./start.sh` (Windows: `.\start.ps1`) auszuführen bzw. ComfyUI zu starten; URL prüfen (`ACS__COMFYUI__URL`). Wird bei Jobs automatisch 1× wiederholt. |
| `model_not_installed` | 409 | Modelldatei fehlt in ComfyUI | `details.missing_files` nennen und den Befehl `python scripts/models/download_models.py --model <id>` mit Downloadgröße zeigen. **Nicht selbst herunterladen** – Freigabe abwarten. Alternativ ein installiertes Modell wählen (`get_available_models`). |
| `hardware_insufficient` | 409 | Aufgabe passt nicht zur Hardware (z. B. KI-Video ohne GPU) | Ehrlich erklären; Fallback anbieten: `videos/kenburns-slideshow` (siehe `details.fallback_workflow`), kleineres Modell, geringere Auflösung/Frames. |
| `cost_confirmation_required` | 402 | Kostenpflichtiger Provider | Kosten aus `details.estimate` (Provider, Modell, Anzahl, Summe, Währung) nennen, **ausdrücklich** fragen; nur nach „Ja“ erneut mit `confirm_token=<details.estimate.confirmation_token>` senden (gültig ~10 min). |
| `budget_exceeded` | 402 | Monatsbudget 0/überschritten oder Limit pro Job | Nicht umgehen. Lokalen Provider verwenden oder Benutzer auf `costs.monthly_budget` in `configs/studio.local.yaml` hinweisen. |
| `provider_disabled` | 403 | Provider deaktiviert / API-Key fehlt | Lokalen Standard-Provider nutzen; Cloud-Provider nur auf ausdrücklichen Wunsch aktivieren. |
| `validation_error` | 400 | Ungültige Parameter | Meldung lesen, Parameter korrigieren (Bereiche, Pflichtfelder, Hex-Farben `#RRGGBB`, Seitenverhältnis `16:9`). Nicht blind wiederholen. |
| `capability_not_supported` | 400 | Provider/Modell kann die Operation nicht | Anderes Modell (`get_available_models` → `tasks`) oder anderen Provider wählen. |
| `path_not_allowed` | 403 | Pfad außerhalb von `assets/` | Asset-ID verwenden oder Datei nach `assets/references/` legen lassen und `rescan_assets` ausführen. |
| `not_found` | 404 | Asset/Job/Workflow unbekannt | IDs mit `search_assets` / `list_jobs` / `get_workflows` prüfen. |
| `tool_not_found` | 503 | FFmpeg/Blender/npx fehlt | Installationshinweis aus der Meldung weitergeben (`docs/INSTALLATION.md`); Fallback (z. B. FFmpeg-Titelkarte statt Remotion). |
| `generation_error` | 500 | Engine-Fehler, z. B. Out-of-Memory | Bei OOM: Auflösung/Frames/Batch senken, kleineres Modell, ComfyUI mit `--lowvram`. Sonst Meldung zeigen. |
| `external_process_error` | 500 | FFmpeg/Blender/Remotion-Prozess fehlgeschlagen | `details.stderr_tail`/`log_tail` auswerten, Eingabedateien prüfen (`get_video_info`). |
| `timeout` | 504 | Zeitlimit überschritten | Kleinere Aufgabe oder Benutzer informieren; Jobs werden automatisch erneut versucht. |
| `job_cancelled` | 409 | Abgebrochen | Nichts tun, außer der Benutzer möchte neu starten (`retry_job`). |
| `unauthorized` | 401 | API-Token fehlt/falsch | `ACS_API_TOKEN` in `.env` von Backend und MCP-Server abgleichen. |

Grundsätze: nie Fehler verschweigen, nie Sicherheits- oder Kostenmechanismen umgehen, nie
Shell-Befehle als Workaround ausführen.
