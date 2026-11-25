"""Command line interface: ``python -m backend.cli <command>`` (or ``acs <command>``)."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from backend.core.config import get_settings


def _print(data: Any) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False, default=str))


def hardware_markdown(report: Any, decision: Any, recommended: dict[str, Any], profile: Any) -> str:
    gpu_lines = [f"| {g.name} | {g.vendor} | {g.vram_total_gb or '?'} GB | {g.backend} | {g.driver_version or '-'} |"
                 for g in report.gpus] or ["| – | – | – | – | – |"]
    tools = [f"| {t.name} | {'✅' if t.available else '❌'} | {t.version or '-'} |" for t in report.tools.values()]
    rec_lines = []
    for task, models in recommended.items():
        names = ", ".join(f"{m['name']} ({m['size_gb']} GB)" for m in models) or "– (Hardware unzureichend)"
        rec_lines.append(f"| {task} | {names} |")
    lines = [
        "# Hardware-Report", "", f"Erstellt: {datetime.now():%Y-%m-%d %H:%M}", "",
        f"**Profil: `{decision.profile}`** – {decision.reason}", "",
        "| Eigenschaft | Wert |", "|---|---|",
        f"| Betriebssystem | {report.os} {report.os_version} ({report.architecture}) |",
        f"| CPU | {report.cpu_model} ({report.cpu_cores_physical} Kerne / {report.cpu_cores_logical} Threads) |",
        f"| RAM | {report.ram_total_gb} GB (frei: {report.ram_available_gb} GB) |",
        f"| Speicher frei | {report.disk_free_gb} GB von {report.disk_total_gb} GB |",
        f"| Beschleuniger | {decision.accelerator} · effektives VRAM {decision.effective_vram_gb} GB |",
        f"| CUDA / ROCm | {report.cuda_version or '-'} / {report.rocm_version or '-'} |",
        f"| Python | {report.python_version} |", "",
        "## GPUs", "", "| Name | Hersteller | VRAM | Backend | Treiber |", "|---|---|---|---|---|", *gpu_lines, "",
        "## Werkzeuge", "", "| Tool | Verfügbar | Version |", "|---|---|---|", *tools, "",
        "## Empfohlene Modelle", "", "| Aufgabe | Modelle (Priorität) |", "|---|---|", *rec_lines, "",
    ]
    if profile is not None and profile.notes:
        lines += ["## Hinweise zum Profil", ""] + [f"- {n}" for n in profile.notes] + [""]
    if decision.warnings or report.notes:
        lines += ["## Warnungen", ""] + [f"- {w}" for w in [*decision.warnings, *report.notes]] + [""]
    return "\n".join(lines)


def cmd_hardware(args: argparse.Namespace) -> int:
    from backend.core.catalog import load_catalog
    from backend.core.hardware import collect_report, select_profile
    from backend.orchestration.selector import ModelSelector

    settings = get_settings()
    report = collect_report(settings.project_root)
    decision = select_profile(report, settings.hardware.profile)
    catalog = load_catalog(str(settings.configs_dir))
    recommended = ModelSelector(catalog).recommended(decision, report.ram_total_gb)
    if args.json:
        _print({"report": report.model_dump(), "decision": decision.model_dump(), "recommended": recommended})
    else:
        md = hardware_markdown(report, decision, recommended, catalog.profiles.get(decision.profile))
        print(md)
        if args.write_report:
            out = settings.data_dir / "reports" / "hardware-report.md"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(md, encoding="utf-8")
            print(f"\n→ geschrieben: {out}", file=sys.stderr)
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from backend.api.app import create_app

    settings = get_settings()
    host = args.host or settings.server.host
    port = args.port or settings.server.port
    if host not in ("127.0.0.1", "localhost", "::1") and not settings.api_token:
        print("WARNUNG: Server ist im Netzwerk erreichbar, aber ACS_API_TOKEN ist nicht gesetzt.", file=sys.stderr)
    uvicorn.run(create_app(), host=host, port=port, log_level="info")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    """Verify the installation and print a status table (exit code 1 on critical problems)."""
    from backend.orchestration.studio import Studio

    async def run() -> int:
        studio = Studio()
        report, decision = studio.hardware()
        critical = False
        rows = []
        for name in studio.registry.infos:
            health = await studio.registry.health(name)
            for role, h in health.items():
                rows.append((f"{name}/{role}", h.available, h.detail))
                if name == "ffmpeg" and not h.available:
                    critical = True
        print(f"Profil: {decision.profile} – {decision.reason}")
        for name, ok, detail in rows:
            print(f"  {'✅' if ok else '⚠️ '} {name:28} {detail}")
        print(f"  Workflows: {len(studio.workflows.specs)} · Job-Typen: {len(studio.ops)}")
        try:
            prov = studio.registry.get("image", "comfyui")
            print(f"  ComfyUI-Templates: {len(prov.templates.templates)}")
        except Exception as exc:  # pragma: no cover
            print(f"  ComfyUI-Templates: Fehler {exc}")
        await studio.stop()
        return 1 if critical else 0

    return asyncio.run(run())


def cmd_workflows(args: argparse.Namespace) -> int:
    from backend.orchestration.studio import Studio

    studio = Studio(configure_logging=False)
    for wf in studio.workflows.list():
        req = f" (benötigt: {', '.join(wf['requires'])})" if wf["requires"] else ""
        print(f"{wf['id']:40} {wf['name']}{req}")
    return 0


def cmd_run_workflow(args: argparse.Namespace) -> int:
    from backend.orchestration.studio import Studio

    inputs = json.loads(Path(args.inputs).read_text(encoding="utf-8")) if args.inputs and Path(args.inputs).is_file() else json.loads(args.inputs or "{}")

    async def run() -> int:
        studio = Studio()
        await studio.start()
        job = await studio.submit("workflow.run", {"workflow_id": args.workflow, "inputs": inputs})
        last = ""
        while True:
            job = await studio.queue.wait(job.id, timeout=1.0)
            line = f"{job.status.value} {int(job.progress * 100):3d}% {job.message}"
            if line != last:
                print(line, file=sys.stderr)
                last = line
            if job.is_final:
                break
        _print(job.result if job.result else job.error)
        await studio.stop()
        return 0 if job.status.value == "succeeded" else 1

    return asyncio.run(run())


def cmd_validate_templates(args: argparse.Namespace) -> int:
    from backend.orchestration.studio import Studio

    async def run() -> int:
        studio = Studio(configure_logging=False)
        prov = studio.registry.get("image", "comfyui")
        info = await prov.client.object_info()
        failures = 0
        for tpl in prov.templates.list():
            errors = tpl.validate_object_info(info)
            failures += bool(errors)
            print(f"{'OK  ' if not errors else 'FAIL'} {tpl.id} {errors if errors else ''}")
        await studio.stop()
        return 1 if failures else 0

    return asyncio.run(run())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="acs", description="AI Creative Studio")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("hardware", help="Hardware analysieren und Profil bestimmen")
    p.add_argument("--json", action="store_true")
    p.add_argument("--write-report", action="store_true", help="nach data/reports/hardware-report.md schreiben")
    p.set_defaults(func=cmd_hardware)
    p = sub.add_parser("serve", help="API + Dashboard starten")
    p.add_argument("--host")
    p.add_argument("--port", type=int)
    p.set_defaults(func=cmd_serve)
    sub.add_parser("check", help="Installation prüfen").set_defaults(func=cmd_check)
    sub.add_parser("workflows", help="Workflows auflisten").set_defaults(func=cmd_workflows)
    p = sub.add_parser("run-workflow", help="Workflow ausführen")
    p.add_argument("workflow")
    p.add_argument("--inputs", help="JSON-String oder Pfad zu JSON-Datei")
    p.set_defaults(func=cmd_run_workflow)
    sub.add_parser("validate-templates", help="ComfyUI-Templates gegen laufendes ComfyUI prüfen").set_defaults(
        func=cmd_validate_templates)
    args = parser.parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
