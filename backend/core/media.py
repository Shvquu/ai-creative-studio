"""Media type detection and probing (Pillow for images, ffprobe for audio/video)."""

from __future__ import annotations

import asyncio
import json
import mimetypes
import shutil
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from .errors import ExternalProcessError, ToolNotFoundError

AssetKind = Literal["image", "video", "audio", "model3d", "subtitle", "document", "other"]

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
VIDEO_EXT = {".mp4", ".webm", ".mov", ".mkv", ".avi", ".m4v", ".gif"}
AUDIO_EXT = {".mp3", ".wav", ".ogg", ".flac", ".m4a", ".aac", ".opus"}
MODEL3D_EXT = {".glb", ".gltf", ".obj", ".fbx", ".stl", ".blend", ".usd", ".usdz", ".ply"}
SUBTITLE_EXT = {".srt", ".vtt", ".ass"}
DOCUMENT_EXT = {".md", ".pdf", ".txt", ".html", ".json", ".yaml", ".yml"}

mimetypes.add_type("model/gltf-binary", ".glb")
mimetypes.add_type("model/gltf+json", ".gltf")
mimetypes.add_type("text/vtt", ".vtt")
mimetypes.add_type("application/x-subrip", ".srt")
mimetypes.add_type("image/webp", ".webp")


def kind_for(path: Path) -> AssetKind:
    ext = path.suffix.lower()
    if ext in IMAGE_EXT:
        return "image"
    if ext in VIDEO_EXT:
        return "video"
    if ext in AUDIO_EXT:
        return "audio"
    if ext in MODEL3D_EXT:
        return "model3d"
    if ext in SUBTITLE_EXT:
        return "subtitle"
    if ext in DOCUMENT_EXT:
        return "document"
    return "other"


def mime_for(path: Path) -> str:
    mime, _ = mimetypes.guess_type(path.name)
    return mime or "application/octet-stream"


class MediaInfo(BaseModel):
    path: str
    kind: AssetKind
    mime: str
    size_bytes: int
    width: int | None = None
    height: int | None = None
    duration_s: float | None = None
    fps: float | None = None
    frame_count: int | None = None
    video_codec: str | None = None
    audio_codec: str | None = None
    pixel_format: str | None = None
    bitrate_kbps: float | None = None
    has_audio: bool = False
    has_alpha: bool | None = None
    format_name: str | None = None
    raw: dict[str, Any] | None = None


def probe_image(path: Path) -> MediaInfo:
    from PIL import Image

    with Image.open(path) as im:
        has_alpha = im.mode in ("RGBA", "LA", "PA") or (im.mode == "P" and "transparency" in im.info)
        return MediaInfo(
            path=str(path),
            kind="image",
            mime=mime_for(path),
            size_bytes=path.stat().st_size,
            width=im.width,
            height=im.height,
            has_alpha=has_alpha,
            format_name=im.format,
            pixel_format=im.mode,
        )


def _parse_rate(rate: str | None) -> float | None:
    if not rate or rate in ("0/0", "N/A"):
        return None
    if "/" in rate:
        num, den = rate.split("/", 1)
        try:
            n, d = float(num), float(den)
            return round(n / d, 3) if d else None
        except ValueError:
            return None
    try:
        return float(rate)
    except ValueError:
        return None


def parse_ffprobe(path: Path, data: dict[str, Any]) -> MediaInfo:
    streams = data.get("streams", [])
    fmt = data.get("format", {})
    video = next((s for s in streams if s.get("codec_type") == "video" and not s.get("disposition", {}).get("attached_pic")), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    duration = fmt.get("duration") or (video or {}).get("duration") or (audio or {}).get("duration")
    fps = _parse_rate((video or {}).get("avg_frame_rate")) or _parse_rate((video or {}).get("r_frame_rate"))
    frames = (video or {}).get("nb_frames")
    bitrate = fmt.get("bit_rate")
    kind = kind_for(path)
    if kind not in ("video", "audio"):
        kind = "video" if video else "audio" if audio else kind
    return MediaInfo(
        path=str(path),
        kind=kind,
        mime=mime_for(path),
        size_bytes=path.stat().st_size,
        width=(video or {}).get("width"),
        height=(video or {}).get("height"),
        duration_s=round(float(duration), 3) if duration not in (None, "N/A") else None,
        fps=fps,
        frame_count=int(frames) if frames and str(frames).isdigit() else None,
        video_codec=(video or {}).get("codec_name"),
        audio_codec=(audio or {}).get("codec_name"),
        pixel_format=(video or {}).get("pix_fmt"),
        bitrate_kbps=round(float(bitrate) / 1000, 1) if bitrate not in (None, "N/A") else None,
        has_audio=audio is not None,
        format_name=fmt.get("format_name"),
        raw=data,
    )


async def run_ffprobe(path: Path, ffprobe: str = "ffprobe", timeout: float = 60) -> dict[str, Any]:
    exe = shutil.which(ffprobe) or (ffprobe if Path(ffprobe).is_file() else None)
    if not exe:
        raise ToolNotFoundError(f"ffprobe not found ('{ffprobe}'). Install FFmpeg (see docs/INSTALLATION.md).")
    proc = await asyncio.create_subprocess_exec(
        exe, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise ExternalProcessError(f"ffprobe timed out for {path.name}") from None
    if proc.returncode != 0:
        raise ExternalProcessError(f"ffprobe failed for {path.name}: {err.decode(errors='replace')[-500:]}")
    return json.loads(out.decode("utf-8", errors="replace") or "{}")


async def probe_media(path: Path, ffprobe: str = "ffprobe") -> MediaInfo:
    kind = kind_for(path)
    if kind == "image":
        return await asyncio.to_thread(probe_image, path)
    if kind in ("video", "audio"):
        return parse_ffprobe(path, await run_ffprobe(path, ffprobe))
    return MediaInfo(path=str(path), kind=kind, mime=mime_for(path), size_bytes=path.stat().st_size)
