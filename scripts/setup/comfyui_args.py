"""Print the ComfyUI launch arguments for the detected hardware profile (used by start.sh/start.ps1)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.core.catalog import load_catalog  # noqa: E402
from backend.core.config import load_settings  # noqa: E402
from backend.core.hardware import collect_report, select_profile  # noqa: E402

if __name__ == "__main__":
    settings = load_settings()
    decision = select_profile(collect_report(ROOT), settings.hardware.profile)
    profile = load_catalog(str(settings.configs_dir)).profiles[decision.profile]
    args = profile.comfyui_args_cpu if decision.cpu_only else profile.comfyui_args
    print(" ".join(args))
