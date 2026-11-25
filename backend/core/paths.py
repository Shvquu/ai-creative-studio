"""Path access control.

API and MCP inputs may only reference files inside explicitly allowed roots
(assets directory, data/tmp and user-configured extra directories). This
prevents path traversal (``../../etc/passwd``) and access to arbitrary files.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from .errors import NotFoundError, PathNotAllowedError, ValidationError

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


def safe_filename(name: str, max_len: int = 120) -> str:
    """Return a filesystem-safe file name (no separators, no leading dots)."""
    base = os.path.basename(name.replace("\\", "/"))
    cleaned = _SAFE_NAME.sub("_", base).strip("._") or "file"
    if len(cleaned) > max_len:
        stem, dot, ext = cleaned.rpartition(".")
        if dot and len(ext) <= 10:
            cleaned = stem[: max_len - len(ext) - 1] + "." + ext
        else:
            cleaned = cleaned[:max_len]
    return cleaned


def slugify(text: str, max_len: int = 48) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:max_len].strip("-") or "item"


class PathGuard:
    def __init__(self, roots: list[Path], default_root: Path) -> None:
        self.roots = [r.resolve() for r in roots]
        self.default_root = default_root.resolve()

    def is_allowed(self, path: Path) -> bool:
        resolved = path.resolve()
        return any(resolved == root or root in resolved.parents for root in self.roots)

    def resolve(self, value: str | os.PathLike[str], *, must_exist: bool = True, kind: str = "file") -> Path:
        raw = os.fspath(value)
        if not raw or "\x00" in raw:
            raise ValidationError("Invalid path")
        candidate = Path(raw).expanduser()
        if not candidate.is_absolute():
            candidate = self.default_root / candidate
        resolved = candidate.resolve()
        if not self.is_allowed(resolved):
            raise PathNotAllowedError(
                f"Path is outside the allowed directories: {raw}",
                details={"allowed_roots": [str(r) for r in self.roots]},
            )
        if must_exist:
            if kind == "file" and not resolved.is_file():
                raise NotFoundError(f"File not found: {raw}")
            if kind == "dir" and not resolved.is_dir():
                raise NotFoundError(f"Directory not found: {raw}")
        return resolved

    def output_path(self, directory: Path, filename: str) -> Path:
        """Build a non-colliding output path inside an allowed directory."""
        directory = directory.resolve()
        if not self.is_allowed(directory):
            raise PathNotAllowedError(f"Output directory not allowed: {directory}")
        directory.mkdir(parents=True, exist_ok=True)
        name = safe_filename(filename)
        target = directory / name
        stem, suffix = target.stem, target.suffix
        counter = 1
        while target.exists():
            target = directory / f"{stem}_{counter:03d}{suffix}"
            counter += 1
        return target
