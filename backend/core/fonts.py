"""Locate usable TrueType/OpenType fonts on Linux, macOS and Windows (no downloads)."""

from __future__ import annotations

import os
import platform
from functools import lru_cache
from pathlib import Path

_PREFERRED = {
    "sans-bold": ["Inter-Bold", "InterDisplay-Bold", "DejaVuSans-Bold", "LiberationSans-Bold", "Arial Bold", "arialbd",
                  "Helvetica-Bold", "SegoeUI-Bold", "segoeuib", "FreeSansBold", "NotoSans-Bold", "Roboto-Bold"],
    "sans": ["Inter-Regular", "InterDisplay-Regular", "DejaVuSans", "LiberationSans-Regular", "Arial", "arial",
             "Helvetica", "segoeui", "FreeSans", "NotoSans-Regular", "Roboto-Regular"],
    "serif": ["DejaVuSerif", "LiberationSerif-Regular", "Georgia", "georgia", "Times New Roman", "times",
              "FreeSerif", "NotoSerif-Regular"],
    "serif-bold": ["DejaVuSerif-Bold", "LiberationSerif-Bold", "Georgia Bold", "georgiab", "timesbd", "FreeSerifBold"],
    "mono": ["DejaVuSansMono", "LiberationMono-Regular", "Consolas", "consola", "Menlo", "FreeMono"],
}


def font_dirs() -> list[Path]:
    system = platform.system()
    dirs: list[Path] = []
    if system == "Windows":
        windir = os.environ.get("WINDIR", r"C:\Windows")
        dirs.append(Path(windir) / "Fonts")
        local = os.environ.get("LOCALAPPDATA")
        if local:
            dirs.append(Path(local) / "Microsoft" / "Windows" / "Fonts")
    elif system == "Darwin":
        dirs += [Path("/System/Library/Fonts"), Path("/System/Library/Fonts/Supplemental"), Path("/Library/Fonts"),
                 Path.home() / "Library" / "Fonts"]
    else:
        dirs += [Path("/usr/share/fonts"), Path("/usr/local/share/fonts"), Path.home() / ".local/share/fonts",
                 Path.home() / ".fonts"]
    return [d for d in dirs if d.is_dir()]


@lru_cache(maxsize=1)
def _index() -> dict[str, Path]:
    index: dict[str, Path] = {}
    for d in font_dirs():
        for ext in ("*.ttf", "*.otf", "*.TTF", "*.OTF"):
            for f in d.rglob(ext):
                index.setdefault(f.stem.lower(), f)
    return index


def find_font(style: str = "sans-bold") -> Path | None:
    index = _index()
    for name in _PREFERRED.get(style, []) + _PREFERRED["sans"]:
        hit = index.get(name.lower()) or index.get(name.lower().replace(" ", ""))
        if hit:
            return hit
    return next(iter(index.values()), None)


def list_fonts(limit: int = 200) -> list[dict[str, str]]:
    return [{"name": k, "path": str(v)} for k, v in sorted(_index().items())[:limit]]
