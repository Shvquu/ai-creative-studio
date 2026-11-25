"""Hardware-aware model selection."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from backend.core.catalog import Catalog, CatalogModel
from backend.core.errors import HardwareInsufficientError, ModelNotInstalledError
from backend.core.hardware import ProfileDecision


@dataclass
class Candidate:
    model: CatalogModel
    installed: bool
    fits: bool
    note: str
    preferred_rank: int
    missing: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.model.id, "name": self.model.name, "installed": self.installed, "fits_hardware": self.fits,
            "note": self.note, "missing_files": self.missing, "size_gb": self.model.total_size_gb,
            "license": self.model.license, "commercial_use": self.model.commercial_use,
            "profile_rank": self.preferred_rank if self.preferred_rank < 99 else None,
        }


class ModelSelector:
    def __init__(self, catalog: Catalog) -> None:
        self.catalog = catalog

    def candidates(self, task: str, decision: ProfileDecision, ram_gb: float,
                   installed: dict[str, set[str]] | None) -> list[Candidate]:
        profile = self.catalog.profiles.get(decision.profile)
        section = "video" if task in ("text_to_video", "image_to_video") else "image"
        if task == "upscale":
            preferred = profile.upscale if profile else []
        else:
            preferred = getattr(profile, section).models if profile else []
        out = []
        for m in self.catalog.for_task(task):
            fits, note = self.catalog.hardware_fit(m, decision.effective_vram_gb, ram_gb, decision.cpu_only)
            missing = [f.name for f in m.missing_files(installed)] if installed is not None else []
            rank = preferred.index(m.id) if m.id in preferred else 99
            out.append(Candidate(m, installed is not None and not missing, fits, note, rank, missing))
        out.sort(key=lambda c: (not c.fits, not c.installed, c.preferred_rank))
        return out

    def choose(self, task: str, decision: ProfileDecision, ram_gb: float,
               installed: dict[str, set[str]]) -> Candidate:
        cands = self.candidates(task, decision, ram_gb, installed)
        usable = [c for c in cands if c.fits and c.installed]
        if usable:
            return usable[0]
        if any(c.installed for c in cands):
            best = next(c for c in cands if c.installed)
            raise HardwareInsufficientError(
                f"Installierte Modelle für '{task}' passen nicht zur Hardware ({best.model.id}: {best.note}).",
                details={"candidates": [c.to_dict() for c in cands]},
            )
        fitting = [c for c in cands if c.fits]
        if not fitting:
            raise HardwareInsufficientError(
                f"Für '{task}' gibt es auf dieser Hardware (Profil {decision.profile}) kein lauffähiges Modell.",
                details={"candidates": [c.to_dict() for c in cands]},
            )
        rec = fitting[0]
        raise ModelNotInstalledError(
            f"Kein passendes Modell für '{task}' installiert. Empfehlung für Profil '{decision.profile}': "
            f"{rec.model.name} ({rec.model.total_size_gb} GB) – python scripts/models/download_models.py --model {rec.model.id}",
            details={"recommended": rec.to_dict(), "candidates": [c.to_dict() for c in cands]},
        )

    def recommended(self, decision: ProfileDecision, ram_gb: float) -> dict[str, list[dict[str, Any]]]:
        """Models recommended for download for this hardware (no installation info needed)."""
        result: dict[str, list[dict[str, Any]]] = {}
        for task in ("text_to_image", "image_to_image", "upscale", "text_to_video", "image_to_video"):
            cands = [c for c in self.candidates(task, decision, ram_gb, None) if c.fits]
            cands.sort(key=lambda c: c.preferred_rank)
            result[task] = [c.to_dict() for c in cands[:3]]
        return result
