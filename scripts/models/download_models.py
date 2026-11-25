#!/usr/bin/env python3
"""Download models from the catalog (configs/models.yaml) into ComfyUI's models folder.

Every model is confirmed individually (size, license, hardware fit) unless --yes is given.
Downloads are resumable (.part files + HTTP Range) and skipped when already complete.

Examples:
    python scripts/models/download_models.py --list
    python scripts/models/download_models.py --recommended
    python scripts/models/download_models.py --model sd15-lcm --model realesrgan-x4
    python scripts/models/download_models.py --model sdxl --comfyui-dir D:/ComfyUI
Gated models: set HF_TOKEN in the environment (never in files).
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402

from backend.core.catalog import CatalogModel, load_catalog  # noqa: E402
from backend.core.config import load_settings  # noqa: E402
from backend.core.hardware import collect_report, select_profile  # noqa: E402
from backend.orchestration.selector import ModelSelector  # noqa: E402


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def target_for(models_dir: Path, folder: str, name: str) -> Path:
    return models_dir / folder / name


def file_complete(path: Path, expected_gb: float) -> bool:
    if not path.is_file():
        return False
    size_gb = path.stat().st_size / 1e9
    return abs(size_gb - expected_gb) <= max(0.02, expected_gb * 0.02)


def download(url: str, dest: Path, token: str | None) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    headers = {"User-Agent": "ai-creative-studio-model-downloader"}
    if token and "huggingface.co" in url:
        headers["Authorization"] = f"Bearer {token}"
    pos = part.stat().st_size if part.exists() else 0
    if pos:
        headers["Range"] = f"bytes={pos}-"
    with httpx.Client(follow_redirects=True, timeout=httpx.Timeout(60.0, read=300.0)) as client:
        with client.stream("GET", url, headers=headers) as resp:
            if resp.status_code == 416:  # already complete
                part.rename(dest)
                return
            if resp.status_code in (401, 403):
                raise SystemExit(f"Zugriff verweigert ({resp.status_code}) – Modell ist evtl. 'gated': Lizenz auf "
                                 f"huggingface.co akzeptieren und HF_TOKEN setzen.\n{url}")
            resp.raise_for_status()
            if pos and resp.status_code != 206:
                pos = 0  # server ignored Range → restart
            total = int(resp.headers.get("content-length", 0)) + pos
            mode = "ab" if pos else "wb"
            done = pos
            started = time.monotonic()
            last = 0.0
            with part.open(mode) as fh:
                for chunk in resp.iter_bytes(1 << 20):
                    fh.write(chunk)
                    done += len(chunk)
                    now = time.monotonic()
                    if now - last > 0.5:
                        speed = (done - pos) / max(0.001, now - started)
                        pct = f"{done / total * 100:5.1f}%" if total else ""
                        sys.stderr.write(f"\r    {pct} {human(done)} / {human(total)}  {human(speed)}/s   ")
                        sys.stderr.flush()
                        last = now
            sys.stderr.write("\n")
    part.rename(dest)


def confirm(question: str) -> bool:
    try:
        return input(f"{question} [j/N] ").strip().lower() in ("j", "ja", "y", "yes")
    except EOFError:
        return False


def main() -> int:
    settings = load_settings()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--list", action="store_true", help="Katalog mit Hardware-Eignung anzeigen")
    parser.add_argument("--recommended", action="store_true", help="Empfohlene Modelle für dieses System anbieten")
    parser.add_argument("--model", action="append", default=[], help="Katalog-ID (mehrfach möglich)")
    parser.add_argument("--comfyui-dir", default=str(settings.resolve(settings.paths.comfyui_dir)))
    parser.add_argument("--models-dir", help="Direkt in diesen models-Ordner laden (statt <comfyui-dir>/models)")
    parser.add_argument("--yes", action="store_true", help="Ohne Rückfrage herunterladen (nur bewusst verwenden!)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    catalog = load_catalog(str(settings.configs_dir))
    report = collect_report(ROOT)
    decision = select_profile(report, settings.hardware.profile)
    models_dir = Path(args.models_dir) if args.models_dir else Path(args.comfyui_dir) / "models"

    if args.list or not (args.model or args.recommended):
        print(f"Hardwareprofil: {decision.profile} – {decision.reason}\nZiel: {models_dir}\n")
        for m in catalog.models.values():
            fits, note = catalog.hardware_fit(m, decision.effective_vram_gb, report.ram_total_gb, decision.cpu_only)
            installed = all(file_complete(target_for(models_dir, f.folder, f.name), f.size_gb) for f in m.files)
            comm = {True: "kommerziell ok", False: "NICHT kommerziell", "restricted": "kommerziell mit Auflagen"}[m.commercial_use]
            print(f"{'✅' if installed else '  '} {m.id:18} {m.total_size_gb:6.2f} GB  {'passt' if fits else 'zu groß':7}  "
                  f"{m.type:7} {m.license} ({comm}) – {note}")
        if not (args.model or args.recommended):
            print("\nHerunterladen: --model <id>  oder  --recommended")
        return 0

    selected: list[CatalogModel] = []
    if args.recommended:
        rec = ModelSelector(catalog).recommended(decision, report.ram_total_gb)
        seen: set[str] = set()
        for task in ("text_to_image", "upscale", "text_to_video", "image_to_video"):
            if rec.get(task):
                mid = rec[task][0]["id"]
                if mid not in seen:
                    seen.add(mid)
                    selected.append(catalog.get(mid))
    for mid in args.model:
        m = catalog.get(mid)
        if m not in selected:
            selected.append(m)

    token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")
    failures = 0
    for m in selected:
        fits, note = catalog.hardware_fit(m, decision.effective_vram_gb, report.ram_total_gb, decision.cpu_only)
        todo = [f for f in m.files if not file_complete(target_for(models_dir, f.folder, f.name), f.size_gb)]
        need_gb = sum(f.size_gb for f in todo)
        print(f"\n■ {m.name} ({m.id})")
        print(f"  Lizenz: {m.license} · kommerzielle Nutzung: {m.commercial_use}")
        if m.license_note:
            print(f"  Hinweis: {m.license_note}")
        print(f"  Hardware: {note}")
        if not todo:
            print("  Bereits vollständig installiert.")
            continue
        for f in todo:
            print(f"  - {f.folder}/{f.name}  ({f.size_gb:.2f} GB)")
        free_gb = shutil.disk_usage(models_dir if models_dir.exists() else models_dir.parent if models_dir.parent.exists() else ROOT).free / 1e9
        if need_gb + 2 > free_gb:
            print(f"  ❌ Nicht genug Speicherplatz: benötigt {need_gb:.1f} GB (+2 GB Reserve), frei {free_gb:.1f} GB")
            failures += 1
            continue
        if not fits:
            print("  ⚠️  Dieses Modell passt laut Hardwareprofil nicht zu Ihrem System.")
        if args.dry_run:
            continue
        if not args.yes and not confirm(f"  {need_gb:.2f} GB herunterladen?"):
            print("  übersprungen")
            continue
        for f in todo:
            dest = target_for(models_dir, f.folder, f.name)
            print(f"  ↓ {f.name}")
            try:
                download(f.url, dest, token)
            except (httpx.HTTPError, OSError) as exc:
                print(f"  ❌ Fehler: {exc} (erneuter Aufruf setzt den Download fort)")
                failures += 1
                break
            if not file_complete(dest, f.size_gb):
                print(f"  ⚠️  Größe weicht ab: {human(dest.stat().st_size)} statt ~{f.size_gb} GB")
        else:
            print("  ✅ fertig")
    print("\nHinweis: ComfyUI erkennt neue Modelle automatisch (Liste wird bei jeder Anfrage neu gelesen).")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
