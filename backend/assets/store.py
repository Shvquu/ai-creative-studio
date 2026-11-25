"""Asset index with sidecar metadata.

Every registered file gets
  * a row in the SQLite ``assets`` table (fast search/filter), and
  * a sidecar ``<file>.meta.json`` next to it (portable, reproducible – contains the
    prompt, seed, model, parameters and, for ComfyUI, the exact executed workflow).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from backend.core.db import Database, from_json, to_json, utcnow
from backend.core.errors import NotFoundError, PathNotAllowedError, ValidationError
from backend.core.media import AssetKind, MediaInfo, kind_for, mime_for, probe_media
from backend.core.paths import slugify

log = logging.getLogger("assets")

SIDECAR_SUFFIX = ".meta.json"
IGNORED_NAMES = {".gitkeep", ".DS_Store", "Thumbs.db"}


class Asset(BaseModel):
    id: str
    path: str  # relative to the assets root (POSIX separators)
    kind: AssetKind
    mime: str | None = None
    size_bytes: int | None = None
    sha256: str | None = None
    width: int | None = None
    height: int | None = None
    duration_s: float | None = None
    fps: float | None = None
    created_at: str
    job_id: str | None = None
    provider: str | None = None
    model: str | None = None
    prompt: str | None = None
    negative_prompt: str | None = None
    seed: int | None = None
    params: dict[str, Any] = {}
    tags: list[str] = []
    favorite: bool = False
    rating: int | None = None
    project: str | None = None
    quality: dict[str, Any] | None = None
    source: str | None = None
    notes: str | None = None

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> Asset:
        data = dict(row)
        data["params"] = from_json(data.get("params"), {}) or {}
        data["tags"] = from_json(data.get("tags"), []) or []
        data["quality"] = from_json(data.get("quality"))
        data["favorite"] = bool(data.get("favorite"))
        return cls(**data)

    @property
    def name(self) -> str:
        return Path(self.path).name


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _norm_tags(tags: list[str] | None) -> list[str]:
    out: list[str] = []
    for t in tags or []:
        t = str(t).strip().lower()[:48]
        if t and t not in out:
            out.append(t)
    return out[:50]


class AssetStore:
    def __init__(self, db: Database, root: Path, cache_dir: Path, ffprobe: str = "ffprobe", ffmpeg: str = "ffmpeg") -> None:
        self.db = db
        self.root = root.resolve()
        self.cache_dir = cache_dir
        self.ffprobe = ffprobe
        self.ffmpeg = ffmpeg

    # ---------------------------------------------------------------- helpers
    def rel(self, path: Path) -> str:
        resolved = path.resolve()
        try:
            return resolved.relative_to(self.root).as_posix()
        except ValueError:
            raise PathNotAllowedError(f"Asset must be inside the assets directory: {path}") from None

    def abs_path(self, asset: Asset) -> Path:
        return (self.root / asset.path).resolve()

    def generated_dir(self, project: str | None = None) -> Path:
        day = datetime.now().strftime("%Y-%m-%d")
        base = self.root / "generated" / day
        if project:
            base = base / slugify(project)
        base.mkdir(parents=True, exist_ok=True)
        return base

    # --------------------------------------------------------------- register
    async def register(
        self,
        path: Path,
        *,
        job_id: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        prompt: str | None = None,
        negative_prompt: str | None = None,
        seed: int | None = None,
        params: dict[str, Any] | None = None,
        tags: list[str] | None = None,
        project: str | None = None,
        source: str = "generated",
        workflow: dict[str, Any] | None = None,
        write_sidecar: bool = True,
    ) -> Asset:
        path = path.resolve()
        rel = self.rel(path)
        if not path.is_file():
            raise NotFoundError(f"File not found: {path}")
        try:
            info: MediaInfo | None = await probe_media(path, self.ffprobe)
        except Exception as exc:  # probing must never block registration
            log.warning("Could not probe %s: %s", path.name, exc)
            info = None
        digest = await asyncio.to_thread(_sha256, path)

        existing = self.db.fetchone("SELECT id, created_at FROM assets WHERE path=?", (rel,))
        asset = Asset(
            id=existing["id"] if existing else uuid.uuid4().hex,
            path=rel,
            kind=info.kind if info else kind_for(path),
            mime=info.mime if info else mime_for(path),
            size_bytes=path.stat().st_size,
            sha256=digest,
            width=info.width if info else None,
            height=info.height if info else None,
            duration_s=info.duration_s if info else None,
            fps=info.fps if info else None,
            created_at=existing["created_at"] if existing else utcnow(),
            job_id=job_id,
            provider=provider,
            model=model,
            prompt=prompt,
            negative_prompt=negative_prompt,
            seed=seed,
            params=params or {},
            tags=_norm_tags(tags),
            project=project,
            source=source,
        )
        self._upsert(asset)
        if write_sidecar:
            self.write_sidecar(asset, workflow=workflow)
        return asset

    def _upsert(self, a: Asset) -> None:
        self.db.execute(
            """INSERT INTO assets (id,path,kind,mime,size_bytes,sha256,width,height,duration_s,fps,created_at,job_id,
                 provider,model,prompt,negative_prompt,seed,params,tags,favorite,rating,project,quality,source,notes)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET path=excluded.path, kind=excluded.kind, mime=excluded.mime,
                 size_bytes=excluded.size_bytes, sha256=excluded.sha256, width=excluded.width, height=excluded.height,
                 duration_s=excluded.duration_s, fps=excluded.fps, job_id=excluded.job_id, provider=excluded.provider,
                 model=excluded.model, prompt=excluded.prompt, negative_prompt=excluded.negative_prompt,
                 seed=excluded.seed, params=excluded.params, tags=excluded.tags, favorite=excluded.favorite,
                 rating=excluded.rating, project=excluded.project, quality=excluded.quality, source=excluded.source,
                 notes=excluded.notes""",
            (
                a.id, a.path, a.kind, a.mime, a.size_bytes, a.sha256, a.width, a.height, a.duration_s, a.fps,
                a.created_at, a.job_id, a.provider, a.model, a.prompt, a.negative_prompt, a.seed, to_json(a.params),
                to_json(a.tags), int(a.favorite), a.rating, a.project, to_json(a.quality), a.source, a.notes,
            ),
        )

    def write_sidecar(self, asset: Asset, workflow: dict[str, Any] | None = None) -> Path:
        target = self.abs_path(asset)
        sidecar = target.with_name(target.name + SIDECAR_SUFFIX)
        data = {"acs_version": 1, "asset": asset.model_dump(mode="json")}
        if sidecar.is_file() and workflow is None:
            old = from_json(sidecar.read_text(encoding="utf-8"), {}) or {}
            if "workflow" in old:
                data["workflow"] = old["workflow"]
        if workflow is not None:
            data["workflow"] = workflow
        sidecar.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        return sidecar

    def read_sidecar(self, asset: Asset) -> dict[str, Any] | None:
        target = self.abs_path(asset)
        sidecar = target.with_name(target.name + SIDECAR_SUFFIX)
        if not sidecar.is_file():
            return None
        return from_json(sidecar.read_text(encoding="utf-8"), None)

    # ------------------------------------------------------------------ query
    def get(self, asset_id: str) -> Asset:
        row = self.db.fetchone("SELECT * FROM assets WHERE id=?", (asset_id,))
        if not row:
            raise NotFoundError(f"Asset not found: {asset_id}")
        return Asset.from_row(row)

    def find_by_path(self, path: Path) -> Asset | None:
        try:
            rel = self.rel(path)
        except PathNotAllowedError:
            return None
        row = self.db.fetchone("SELECT * FROM assets WHERE path=?", (rel,))
        return Asset.from_row(row) if row else None

    def search(
        self,
        query: str | None = None,
        *,
        kind: str | None = None,
        tags: list[str] | None = None,
        favorite: bool | None = None,
        project: str | None = None,
        job_id: str | None = None,
        since: str | None = None,
        until: str | None = None,
        sort: Literal["newest", "oldest", "name", "size", "rating"] = "newest",
        limit: int = 60,
        offset: int = 0,
    ) -> tuple[list[Asset], int]:
        where, args = [], []
        if query:
            for term in query.split():
                like = f"%{term}%"
                where.append("(path LIKE ? OR prompt LIKE ? OR tags LIKE ? OR model LIKE ? OR notes LIKE ? OR project LIKE ?)")
                args += [like] * 6
        if kind:
            kinds = [k.strip() for k in kind.split(",") if k.strip()]
            where.append(f"kind IN ({','.join('?' * len(kinds))})")
            args += kinds
        for tag in _norm_tags(tags):
            where.append("tags LIKE ?")
            args.append(f'%"{tag}"%')
        if favorite is not None:
            where.append("favorite=?")
            args.append(int(favorite))
        if project:
            where.append("project=?")
            args.append(project)
        if job_id:
            where.append("job_id=?")
            args.append(job_id)
        if since:
            where.append("created_at>=?")
            args.append(since)
        if until:
            where.append("created_at<=?")
            args.append(until)
        clause = (" WHERE " + " AND ".join(where)) if where else ""
        order = {
            "newest": "created_at DESC",
            "oldest": "created_at ASC",
            "name": "path ASC",
            "size": "size_bytes DESC",
            "rating": "COALESCE(rating,0) DESC, created_at DESC",
        }[sort]
        total = (self.db.fetchone(f"SELECT COUNT(*) AS n FROM assets{clause}", args) or {"n": 0})["n"]
        rows = self.db.fetchall(
            f"SELECT * FROM assets{clause} ORDER BY {order} LIMIT ? OFFSET ?",
            [*args, max(1, min(limit, 500)), max(0, offset)],
        )
        return [Asset.from_row(r) for r in rows], total

    def stats(self) -> dict[str, Any]:
        rows = self.db.fetchall("SELECT kind, COUNT(*) AS n, COALESCE(SUM(size_bytes),0) AS bytes FROM assets GROUP BY kind")
        return {
            "by_kind": {r["kind"]: {"count": r["n"], "bytes": r["bytes"]} for r in rows},
            "total": sum(r["n"] for r in rows),
            "total_bytes": sum(r["bytes"] for r in rows),
            "favorites": (self.db.fetchone("SELECT COUNT(*) AS n FROM assets WHERE favorite=1") or {"n": 0})["n"],
        }

    def all_tags(self) -> list[dict[str, Any]]:
        counts: dict[str, int] = {}
        for row in self.db.fetchall("SELECT tags FROM assets"):
            for tag in from_json(row["tags"], []) or []:
                counts[tag] = counts.get(tag, 0) + 1
        return [{"tag": t, "count": n} for t, n in sorted(counts.items(), key=lambda x: (-x[1], x[0]))]

    def projects(self) -> list[str]:
        return [r["project"] for r in self.db.fetchall("SELECT DISTINCT project FROM assets WHERE project IS NOT NULL ORDER BY project")]

    # ----------------------------------------------------------------- update
    def update(
        self,
        asset_id: str,
        *,
        tags: list[str] | None = None,
        add_tags: list[str] | None = None,
        remove_tags: list[str] | None = None,
        favorite: bool | None = None,
        rating: int | None = None,
        notes: str | None = None,
        project: str | None = None,
    ) -> Asset:
        asset = self.get(asset_id)
        if tags is not None:
            asset.tags = _norm_tags(tags)
        if add_tags:
            asset.tags = _norm_tags(asset.tags + add_tags)
        if remove_tags:
            drop = set(_norm_tags(remove_tags))
            asset.tags = [t for t in asset.tags if t not in drop]
        if favorite is not None:
            asset.favorite = favorite
        if rating is not None:
            if not 0 <= rating <= 5:
                raise ValidationError("rating must be between 0 and 5")
            asset.rating = rating
        if notes is not None:
            asset.notes = notes[:4000]
        if project is not None:
            asset.project = project or None
        self._upsert(asset)
        if self.abs_path(asset).is_file():
            self.write_sidecar(asset)
        return asset

    def set_quality(self, asset_id: str, quality: dict[str, Any]) -> Asset:
        asset = self.get(asset_id)
        asset.quality = quality
        self._upsert(asset)
        if self.abs_path(asset).is_file():
            self.write_sidecar(asset)
        return asset

    # --------------------------------------------------------------- maintenance
    async def rescan(self) -> dict[str, Any]:
        """Index files added manually and drop rows whose files were deleted."""
        added, removed = [], []
        known = {r["path"] for r in self.db.fetchall("SELECT path FROM assets")}
        for path in sorted(self.root.rglob("*")):
            if not path.is_file() or path.name in IGNORED_NAMES or path.name.endswith(SIDECAR_SUFFIX):
                continue
            if any(part.startswith(".") for part in path.relative_to(self.root).parts):
                continue
            rel = path.relative_to(self.root).as_posix()
            if rel in known:
                continue
            meta: dict[str, Any] = {}
            sidecar = path.with_name(path.name + SIDECAR_SUFFIX)
            if sidecar.is_file():
                meta = (from_json(sidecar.read_text(encoding="utf-8"), {}) or {}).get("asset", {})
            source = "reference" if rel.startswith("references/") else meta.get("source") or "imported"
            asset = await self.register(
                path,
                job_id=meta.get("job_id"), provider=meta.get("provider"), model=meta.get("model"),
                prompt=meta.get("prompt"), negative_prompt=meta.get("negative_prompt"), seed=meta.get("seed"),
                params=meta.get("params"), tags=meta.get("tags"), project=meta.get("project"), source=source,
                write_sidecar=False,
            )
            added.append(asset.path)
        for rel in known:
            if not (self.root / rel).is_file():
                self.db.execute("DELETE FROM assets WHERE path=?", (rel,))
                removed.append(rel)
        return {"added": added, "removed": removed}

    def organize(
        self,
        rule: Literal["by_kind", "by_project", "by_date"] = "by_kind",
        *,
        asset_ids: list[str] | None = None,
        dry_run: bool = True,
    ) -> dict[str, Any]:
        """Move assets into a tidy folder structure. Dry-run by default (no file changes)."""
        if asset_ids:
            assets = [self.get(a) for a in asset_ids]
        else:
            assets = [Asset.from_row(r) for r in self.db.fetchall("SELECT * FROM assets WHERE source!='reference' OR source IS NULL")]
        kind_dirs = {"image": "images", "video": "videos", "audio": "exports/audio", "model3d": "exports/3d",
                     "subtitle": "exports/subtitles", "document": "exports/documents", "other": "exports/other"}
        moves = []
        for a in assets:
            src = self.abs_path(a)
            if rule == "by_kind":
                dest_dir = self.root / kind_dirs.get(a.kind, "exports/other")
            elif rule == "by_project":
                dest_dir = self.root / kind_dirs.get(a.kind, "exports/other") / slugify(a.project or "ohne-projekt")
            else:
                dest_dir = self.root / kind_dirs.get(a.kind, "exports/other") / a.created_at[:7]
            dest = dest_dir / src.name
            if dest.resolve() == src:
                continue
            counter = 1
            while dest.exists():
                dest = dest_dir / f"{src.stem}_{counter:03d}{src.suffix}"
                counter += 1
            moves.append({"asset_id": a.id, "from": a.path, "to": dest.relative_to(self.root).as_posix()})
        if not dry_run:
            for m in moves:
                src = self.root / m["from"]
                dst = self.root / m["to"]
                if not src.is_file():
                    continue
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(dst))
                side = src.with_name(src.name + SIDECAR_SUFFIX)
                if side.is_file():
                    shutil.move(str(side), str(dst.with_name(dst.name + SIDECAR_SUFFIX)))
                self.db.execute("UPDATE assets SET path=? WHERE id=?", (m["to"], m["asset_id"]))
                asset = self.get(m["asset_id"])
                self.write_sidecar(asset)
        return {"rule": rule, "dry_run": dry_run, "moves": moves, "count": len(moves)}

    # --------------------------------------------------------------- thumbnails
    async def thumbnail(self, asset_id: str, size: int = 384) -> Path:
        asset = self.get(asset_id)
        src = self.abs_path(asset)
        if not src.is_file():
            raise NotFoundError(f"File missing on disk: {asset.path}")
        size = max(64, min(size, 1024))
        thumb_dir = self.cache_dir / "thumbs"
        thumb_dir.mkdir(parents=True, exist_ok=True)
        thumb = thumb_dir / f"{asset.id}_{size}.webp"
        if thumb.is_file() and thumb.stat().st_mtime >= src.stat().st_mtime:
            return thumb
        if asset.kind == "image":
            await asyncio.to_thread(_image_thumb, src, thumb, size)
        elif asset.kind == "video":
            frame = thumb_dir / f"{asset.id}_frame.png"
            seek = min(1.0, (asset.duration_s or 0) / 3)
            await _video_frame(self.ffmpeg, src, frame, seek)
            await asyncio.to_thread(_image_thumb, frame, thumb, size)
            frame.unlink(missing_ok=True)
        else:
            raise NotFoundError("No thumbnail available for this asset type")
        return thumb


def _image_thumb(src: Path, dst: Path, size: int) -> None:
    from PIL import Image, ImageOps

    with Image.open(src) as im:
        im = ImageOps.exif_transpose(im)
        im.thumbnail((size, size))
        if im.mode not in ("RGB", "RGBA"):
            im = im.convert("RGBA" if "A" in im.getbands() else "RGB")
        im.save(dst, "WEBP", quality=82)


async def _video_frame(ffmpeg: str, src: Path, dst: Path, seek: float) -> None:
    exe = shutil.which(ffmpeg) or ffmpeg
    proc = await asyncio.create_subprocess_exec(
        exe, "-y", "-v", "error", "-ss", f"{seek:.2f}", "-i", str(src), "-frames:v", "1", str(dst),
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
    )
    _, err = await asyncio.wait_for(proc.communicate(), timeout=60)
    if proc.returncode != 0 or not dst.is_file():
        raise NotFoundError(f"Could not extract video frame: {err.decode(errors='replace')[-300:]}")
