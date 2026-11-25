"""Hardware & software environment detection and hardware-profile selection.

Works on Linux, Windows and macOS without optional dependencies. Detection
sources (all optional, failures are tolerated):

* NVIDIA:  ``nvidia-smi`` (name, VRAM, driver, CUDA version, utilisation)
* AMD:     ``rocm-smi`` / ``amd-smi`` and ``/sys/class/drm/*/device/mem_info_vram_total`` (Linux)
* Apple:   ``sysctl`` + ``system_profiler`` (Apple Silicon uses unified memory)
* Windows: ``Get-CimInstance Win32_VideoController`` (fallback, VRAM often capped at 4 GB)
* PyTorch: if importable in *this* interpreter (normally it is installed only in ComfyUI's venv)

The profile decision is deliberately conservative: it is better to recommend
a smaller model that runs than a large one that crashes with out-of-memory.
"""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import psutil
from pydantic import BaseModel, Field

ProfileName = Literal["low", "mid", "high"]
GpuBackend = Literal["cuda", "rocm", "mps", "directml", "none"]

_CMD_TIMEOUT = 10


# ----------------------------------------------------------------------------
# Models
# ----------------------------------------------------------------------------

class GpuInfo(BaseModel):
    vendor: Literal["nvidia", "amd", "apple", "intel", "unknown"]
    name: str
    vram_total_gb: float | None = None
    vram_free_gb: float | None = None
    utilization_pct: float | None = None
    driver_version: str | None = None
    backend: GpuBackend = "none"
    unified_memory: bool = False
    source: str = ""


class ToolInfo(BaseModel):
    name: str
    available: bool
    version: str | None = None
    path: str | None = None


class HardwareReport(BaseModel):
    os: str
    os_version: str
    architecture: str
    cpu_model: str
    cpu_cores_physical: int | None
    cpu_cores_logical: int | None
    ram_total_gb: float
    ram_available_gb: float
    disk_free_gb: float
    disk_total_gb: float
    gpus: list[GpuInfo] = []
    cuda_version: str | None = None
    rocm_version: str | None = None
    torch: dict | None = None
    python_version: str
    tools: dict[str, ToolInfo] = {}
    is_container: bool = False
    notes: list[str] = []

    @property
    def best_gpu(self) -> GpuInfo | None:
        accel = [g for g in self.gpus if g.backend != "none"]
        if not accel:
            return None
        return max(accel, key=lambda g: g.vram_total_gb or 0)

    @property
    def effective_vram_gb(self) -> float:
        """VRAM usable for models. Apple unified memory: ~65 % of RAM (macOS default GPU limit)."""
        gpu = self.best_gpu
        if gpu is None:
            return 0.0
        if gpu.unified_memory:
            return round(self.ram_total_gb * 0.65, 1)
        return gpu.vram_total_gb or 0.0

    @property
    def accelerator(self) -> GpuBackend:
        gpu = self.best_gpu
        return gpu.backend if gpu else "none"


class ProfileDecision(BaseModel):
    profile: ProfileName
    reason: str
    accelerator: GpuBackend
    effective_vram_gb: float
    cpu_only: bool
    warnings: list[str] = Field(default_factory=list)


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------

def _run(cmd: list[str], timeout: int = _CMD_TIMEOUT) -> str | None:
    exe = shutil.which(cmd[0])
    if not exe:
        return None
    try:
        proc = subprocess.run(
            [exe, *cmd[1:]],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            encoding="utf-8",
            errors="replace",
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip()


def _gb(n_bytes: float | int | None) -> float | None:
    if n_bytes is None:
        return None
    return round(float(n_bytes) / (1024**3), 2)


def _first_line(text: str | None) -> str | None:
    if not text:
        return None
    return text.splitlines()[0].strip()


# ----------------------------------------------------------------------------
# CPU / OS
# ----------------------------------------------------------------------------

def detect_cpu_model() -> str:
    system = platform.system()
    if system == "Linux":
        try:
            for line in Path("/proc/cpuinfo").read_text(errors="replace").splitlines():
                if line.lower().startswith("model name"):
                    return line.split(":", 1)[1].strip()
        except OSError:
            pass
    elif system == "Darwin":
        out = _run(["sysctl", "-n", "machdep.cpu.brand_string"])
        if out:
            return out
    elif system == "Windows":
        out = _run(["powershell", "-NoProfile", "-Command", "(Get-CimInstance Win32_Processor).Name"])
        if out:
            return _first_line(out) or out
    return platform.processor() or platform.machine() or "unknown"


def detect_container() -> bool:
    if Path("/.dockerenv").exists():
        return True
    try:
        cgroup = Path("/proc/1/cgroup").read_text(errors="replace")
        return any(k in cgroup for k in ("docker", "kubepods", "containerd"))
    except OSError:
        return False


# ----------------------------------------------------------------------------
# GPU detection
# ----------------------------------------------------------------------------

def detect_nvidia() -> tuple[list[GpuInfo], str | None]:
    out = _run([
        "nvidia-smi",
        "--query-gpu=name,memory.total,memory.free,driver_version,utilization.gpu",
        "--format=csv,noheader,nounits",
    ])
    if not out:
        return [], None
    gpus: list[GpuInfo] = []
    for line in out.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 5:
            continue
        name, total, free, driver, util = parts[:5]

        def num(v: str) -> float | None:
            try:
                return float(v)
            except ValueError:
                return None

        total_mb, free_mb = num(total), num(free)
        gpus.append(GpuInfo(
            vendor="nvidia",
            name=name,
            vram_total_gb=round(total_mb / 1024, 2) if total_mb else None,
            vram_free_gb=round(free_mb / 1024, 2) if free_mb else None,
            utilization_pct=num(util),
            driver_version=driver,
            backend="cuda",
            source="nvidia-smi",
        ))
    cuda_version = None
    header = _run(["nvidia-smi"])
    if header:
        m = re.search(r"CUDA Version:\s*([\d.]+)", header)
        if m:
            cuda_version = m.group(1)
    return gpus, cuda_version


def detect_amd_linux() -> tuple[list[GpuInfo], str | None]:
    gpus: list[GpuInfo] = []
    drm = Path("/sys/class/drm")
    if drm.is_dir():
        for card in sorted(drm.glob("card[0-9]*")):
            dev = card / "device"
            vram_file = dev / "mem_info_vram_total"
            vendor_file = dev / "vendor"
            try:
                if not vram_file.is_file() or vendor_file.read_text().strip() != "0x1002":
                    continue
                total = int(vram_file.read_text().strip())
                used_file = dev / "mem_info_vram_used"
                used = int(used_file.read_text().strip()) if used_file.is_file() else None
            except (OSError, ValueError):
                continue
            name = "AMD GPU"
            product = dev / "product_name"
            if product.is_file():
                name = product.read_text(errors="replace").strip() or name
            gpus.append(GpuInfo(
                vendor="amd",
                name=name,
                vram_total_gb=_gb(total),
                vram_free_gb=_gb(total - used) if used is not None else None,
                backend="rocm" if shutil.which("rocminfo") or shutil.which("rocm-smi") else "none",
                source="sysfs",
            ))
    rocm_version = None
    for candidate in (Path("/opt/rocm/.info/version"), Path("/opt/rocm/.info/version-dev")):
        if candidate.is_file():
            rocm_version = candidate.read_text().strip()
            break
    if gpus and all(g.name == "AMD GPU" for g in gpus):
        names = _run(["rocm-smi", "--showproductname", "--json"])
        if names:
            try:
                data = json.loads(names)
                card_names = [v.get("Card series") or v.get("Card model") for v in data.values() if isinstance(v, dict)]
                for gpu, nm in zip(gpus, card_names, strict=False):
                    if nm:
                        gpu.name = nm
            except (ValueError, AttributeError):
                pass
    return gpus, rocm_version


def detect_apple() -> list[GpuInfo]:
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        return []
    name = _run(["sysctl", "-n", "machdep.cpu.brand_string"]) or "Apple Silicon"
    gpu_name = f"{name} GPU"
    out = _run(["system_profiler", "SPDisplaysDataType", "-json"], timeout=20)
    if out:
        try:
            data = json.loads(out)
            displays = data.get("SPDisplaysDataType", [])
            if displays and displays[0].get("sppci_model"):
                gpu_name = displays[0]["sppci_model"]
        except ValueError:
            pass
    return [GpuInfo(vendor="apple", name=gpu_name, backend="mps", unified_memory=True, source="system_profiler")]


def detect_windows_generic() -> list[GpuInfo]:
    out = _run([
        "powershell", "-NoProfile", "-Command",
        "Get-CimInstance Win32_VideoController | Select-Object Name,AdapterRAM,DriverVersion | ConvertTo-Json",
    ], timeout=20)
    if not out:
        return []
    try:
        data = json.loads(out)
    except ValueError:
        return []
    if isinstance(data, dict):
        data = [data]
    gpus = []
    for item in data:
        name = str(item.get("Name") or "GPU")
        lname = name.lower()
        vendor = "amd" if ("amd" in lname or "radeon" in lname) else "intel" if "intel" in lname else (
            "nvidia" if "nvidia" in lname else "unknown")
        ram = item.get("AdapterRAM")
        gpus.append(GpuInfo(
            vendor=vendor,  # type: ignore[arg-type]
            name=name,
            vram_total_gb=_gb(ram) if isinstance(ram, (int, float)) and ram > 0 else None,
            driver_version=item.get("DriverVersion"),
            # AMD/Intel on Windows: DirectML is possible but much slower and less compatible than CUDA.
            backend="directml" if vendor in ("amd", "intel") else "none",
            source="Win32_VideoController (VRAM capped at 4 GB by WMI)",
        ))
    return gpus


def detect_torch() -> dict | None:
    """Only inspects torch if it is already importable – never installs anything."""
    try:
        import importlib.util

        if importlib.util.find_spec("torch") is None:
            return None
        import torch  # type: ignore

        info = {
            "version": torch.__version__,
            "cuda_available": bool(torch.cuda.is_available()),
            "cuda_version": getattr(torch.version, "cuda", None),
            "hip_version": getattr(torch.version, "hip", None),
            "mps_available": bool(getattr(torch.backends, "mps", None) and torch.backends.mps.is_available()),
        }
        return info
    except Exception:  # pragma: no cover - defensive
        return None


# ----------------------------------------------------------------------------
# Tools
# ----------------------------------------------------------------------------

@dataclass(frozen=True)
class _ToolSpec:
    name: str
    cmd: tuple[str, ...]
    pattern: str | None = None


_TOOLS = (
    _ToolSpec("python", (sys.executable, "--version")),
    _ToolSpec("node", ("node", "--version")),
    _ToolSpec("npm", ("npm", "--version")),
    _ToolSpec("git", ("git", "--version")),
    _ToolSpec("ffmpeg", ("ffmpeg", "-version"), r"ffmpeg version (\S+)"),
    _ToolSpec("ffprobe", ("ffprobe", "-version"), r"ffprobe version (\S+)"),
    _ToolSpec("blender", ("blender", "--version"), r"Blender (\S+)"),
    _ToolSpec("docker", ("docker", "--version")),
    _ToolSpec("uv", ("uv", "--version")),
)


def detect_tools(overrides: dict[str, str] | None = None) -> dict[str, ToolInfo]:
    overrides = overrides or {}
    tools: dict[str, ToolInfo] = {}
    for spec in _TOOLS:
        cmd = list(spec.cmd)
        if spec.name in overrides:
            cmd[0] = overrides[spec.name]
        exe = cmd[0] if os.path.isabs(cmd[0]) and os.path.exists(cmd[0]) else shutil.which(cmd[0])
        if not exe:
            tools[spec.name] = ToolInfo(name=spec.name, available=False)
            continue
        out = _run([exe, *cmd[1:]], timeout=20)
        version = None
        if out:
            if spec.pattern:
                m = re.search(spec.pattern, out)
                version = m.group(1) if m else _first_line(out)
            else:
                version = _first_line(out)
        tools[spec.name] = ToolInfo(name=spec.name, available=out is not None, version=version, path=exe)
    return tools


# ----------------------------------------------------------------------------
# Report
# ----------------------------------------------------------------------------

def collect_report(disk_path: Path | None = None, tool_overrides: dict[str, str] | None = None) -> HardwareReport:
    vm = psutil.virtual_memory()
    disk = shutil.disk_usage(disk_path or Path.cwd())
    notes: list[str] = []

    gpus, cuda_version = detect_nvidia()
    amd, rocm_version = detect_amd_linux() if platform.system() == "Linux" else ([], None)
    gpus += amd
    gpus += detect_apple()
    if platform.system() == "Windows" and not gpus:
        gpus += detect_windows_generic()

    torch_info = detect_torch()
    if torch_info and torch_info.get("cuda_available") and not cuda_version:
        cuda_version = torch_info.get("cuda_version")

    for g in gpus:
        if g.vendor == "amd" and g.backend == "none":
            notes.append(f"AMD GPU '{g.name}' gefunden, aber keine ROCm-Installation erkannt – GPU-Beschleunigung nicht nutzbar.")
        if g.backend == "directml":
            notes.append(f"'{g.name}' kann unter Windows nur über DirectML genutzt werden (langsamer, eingeschränkt kompatibel).")
    if not any(g.backend != "none" for g in gpus):
        notes.append("Keine nutzbare GPU-Beschleunigung gefunden – CPU-Fallback (sehr langsam, keine Videogenerierung).")

    container = detect_container()
    if container:
        notes.append("Läuft in einem Container – erkannte Hardware entspricht ggf. nicht dem Host-System.")

    return HardwareReport(
        os=platform.system(),
        os_version=platform.release() if platform.system() != "Linux" else _linux_pretty_name(),
        architecture=platform.machine(),
        cpu_model=detect_cpu_model(),
        cpu_cores_physical=psutil.cpu_count(logical=False),
        cpu_cores_logical=psutil.cpu_count(logical=True),
        ram_total_gb=_gb(vm.total) or 0.0,
        ram_available_gb=_gb(vm.available) or 0.0,
        disk_free_gb=_gb(disk.free) or 0.0,
        disk_total_gb=_gb(disk.total) or 0.0,
        gpus=gpus,
        cuda_version=cuda_version,
        rocm_version=rocm_version,
        torch=torch_info,
        python_version=platform.python_version(),
        tools=detect_tools(tool_overrides),
        is_container=container,
        notes=notes,
    )


def _linux_pretty_name() -> str:
    try:
        for line in Path("/etc/os-release").read_text().splitlines():
            if line.startswith("PRETTY_NAME="):
                return line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return platform.release()


# ----------------------------------------------------------------------------
# Profile selection
# ----------------------------------------------------------------------------

def select_profile(report: HardwareReport, override: str = "auto") -> ProfileDecision:
    vram = report.effective_vram_gb
    accel = report.accelerator
    ram = report.ram_total_gb
    warnings: list[str] = []

    if accel == "none":
        profile: ProfileName = "low"
        reason = "Keine GPU-Beschleunigung: CPU-Modus (nur kleine Bildmodelle, keine KI-Videogenerierung)."
    elif accel == "mps":
        if ram >= 64:
            profile, reason = "high", f"Apple Silicon mit {ram:.0f} GB Unified Memory."
        elif ram >= 24:
            profile, reason = "mid", f"Apple Silicon mit {ram:.0f} GB Unified Memory."
        else:
            profile, reason = "low", f"Apple Silicon mit nur {ram:.0f} GB Unified Memory."
        warnings.append("MPS ist deutlich langsamer als CUDA; Videomodelle nur eingeschränkt nutzbar.")
    elif accel == "directml":
        profile, reason = "low", "DirectML-Beschleunigung (AMD/Intel unter Windows) – konservatives Profil."
    else:
        if vram >= 16 and ram >= 32:
            profile, reason = "high", f"{accel.upper()}-GPU mit {vram:.0f} GB VRAM und {ram:.0f} GB RAM."
        elif vram >= 16:
            profile, reason = "mid", f"{vram:.0f} GB VRAM, aber nur {ram:.0f} GB RAM (große Modelle brauchen RAM zum Laden)."
        elif vram >= 8:
            profile, reason = "mid", f"{accel.upper()}-GPU mit {vram:.0f} GB VRAM."
        else:
            profile, reason = "low", f"{accel.upper()}-GPU mit nur {vram:.0f} GB VRAM."
        if accel == "rocm":
            warnings.append("ROCm: nicht alle Modelle/Nodes sind getestet; bei Fehlern fp16/--use-split-cross-attention probieren.")

    if report.disk_free_gb < 30:
        warnings.append(f"Nur {report.disk_free_gb:.0f} GB freier Speicher – Modelle benötigen 2–40 GB pro Modell.")
    if ram < 15:
        warnings.append(f"Nur {ram:.1f} GB RAM – große Modelle können beim Laden auslagern.")
    elif ram < 32 and profile != "low":
        warnings.append(f"{ram:.0f} GB RAM: für FLUX/Wan-14B werden ≥ 32 GB RAM empfohlen.")

    if override in ("low", "mid", "high") and override != profile:
        warnings.append(f"Profil manuell auf '{override}' gesetzt (automatisch erkannt: '{profile}').")
        reason = f"Manuell gesetzt. Automatische Erkennung: {profile} – {reason}"
        profile = override  # type: ignore[assignment]

    return ProfileDecision(
        profile=profile,
        reason=reason,
        accelerator=accel,
        effective_vram_gb=vram,
        cpu_only=accel == "none",
        warnings=warnings,
    )


def live_usage() -> dict:
    """Cheap, frequently-polled usage numbers for the dashboard."""
    vm = psutil.virtual_memory()
    usage = {
        "cpu_pct": psutil.cpu_percent(interval=None),
        "ram_used_gb": _gb(vm.total - vm.available),
        "ram_total_gb": _gb(vm.total),
        "ram_pct": vm.percent,
        "gpus": [],
    }
    gpus, _ = detect_nvidia()
    usage["gpus"] = [g.model_dump() for g in gpus]
    return usage
