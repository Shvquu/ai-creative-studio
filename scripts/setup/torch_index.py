"""Print the pip arguments to install PyTorch for the detected accelerator (ComfyUI docs/installation.md).

Output is a single line of pip arguments, e.g.
  torch torchvision torchaudio --extra-index-url https://download.pytorch.org/whl/cu130
"""

from __future__ import annotations

import platform
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.core.hardware import collect_report  # noqa: E402

PKGS = "torch torchvision torchaudio"


def pip_args(force_cpu: bool = False) -> str:
    report = collect_report(ROOT)
    accel = "none" if force_cpu else report.accelerator
    if accel == "cuda":
        return f"{PKGS} --extra-index-url https://download.pytorch.org/whl/cu130"
    if accel == "rocm" and platform.system() == "Linux":
        return f"{PKGS} --index-url https://download.pytorch.org/whl/rocm7.2"
    if accel == "mps":
        return PKGS  # default macOS wheels include MPS support
    if platform.system() == "Darwin":
        return PKGS
    return f"{PKGS} --index-url https://download.pytorch.org/whl/cpu"


if __name__ == "__main__":
    print(pip_args("--cpu" in sys.argv))
