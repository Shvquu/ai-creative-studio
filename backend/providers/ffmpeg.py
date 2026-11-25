"""FFmpeg processing provider.

All commands are built as argument lists (never via a shell). Files that are
referenced *inside* filter graphs (subtitles, text files, fonts) are copied
into a per-call work directory and referenced by bare file names, which avoids
platform-specific filter escaping problems (Windows drive letters etc.).
"""

from __future__ import annotations

import asyncio
import collections
import json
import logging
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from backend.core.errors import ExternalProcessError, StudioTimeoutError, ToolNotFoundError, ValidationError
from backend.core.fonts import find_font
from backend.core.media import MediaInfo, kind_for, probe_media
from backend.jobs.context import JobContext

from .base import Capability, GenerationResult, ProcessingProvider, ProviderHealth

log = logging.getLogger("ffmpeg")

XFADE_TRANSITIONS = (
    "fade", "dissolve", "wipeleft", "wiperight", "wipeup", "wipedown", "slideleft", "slideright", "slideup",
    "slidedown", "circleopen", "circleclose", "radial", "smoothleft", "smoothright", "fadeblack", "fadewhite",
    "zoomin", "pixelize", "hblur",
)
Transition = Literal["none", "fade", "dissolve", "wipeleft", "wiperight", "wipeup", "wipedown", "slideleft",
                     "slideright", "slideup", "slidedown", "circleopen", "circleclose", "radial", "smoothleft",
                     "smoothright", "fadeblack", "fadewhite", "zoomin", "pixelize", "hblur"]


# ----------------------------------------------------------------------------
# Request models
# ----------------------------------------------------------------------------

class ConvertRequest(BaseModel):
    source: str
    format: Literal["mp4", "webm", "mov", "mkv", "gif", "mp3", "wav", "m4a"] = "mp4"
    crf: int | None = Field(None, ge=0, le=51)
    fps: float | None = Field(None, gt=0, le=120)
    width: int | None = Field(None, ge=16, le=7680)
    height: int | None = Field(None, ge=16, le=4320)
    remove_audio: bool = False


class TrimRequest(BaseModel):
    source: str
    start_s: float = Field(0.0, ge=0)
    end_s: float | None = Field(None, gt=0)
    duration_s: float | None = Field(None, gt=0)


class MergeRequest(BaseModel):
    sources: list[str] = Field(min_length=2, max_length=100)
    transition: Transition = "none"
    transition_duration: float = Field(0.5, ge=0.1, le=5)
    width: int | None = Field(None, ge=16, le=7680)
    height: int | None = Field(None, ge=16, le=4320)
    fps: float | None = Field(None, gt=0, le=120)


class KenBurns(BaseModel):
    zoom: Literal["in", "out", "none"] = "in"
    pan: Literal["none", "left", "right", "up", "down"] = "none"
    strength: float = Field(0.15, ge=0, le=0.6)


class TimelineClip(BaseModel):
    source: str
    duration_s: float | None = Field(None, gt=0, le=600, description="Required for images")
    start_s: float | None = Field(None, ge=0)
    end_s: float | None = Field(None, gt=0)
    ken_burns: KenBurns | None = None


class AudioTrack(BaseModel):
    source: str
    volume: float = Field(1.0, ge=0, le=4)
    fade_in_s: float = Field(0.0, ge=0, le=30)
    fade_out_s: float = Field(1.0, ge=0, le=30)
    mode: Literal["replace", "mix"] = "replace"
    normalize: bool = True


class SubtitleCue(BaseModel):
    start_s: float = Field(ge=0)
    end_s: float = Field(gt=0)
    text: str = Field(min_length=1, max_length=500)


class SubtitleStyle(BaseModel):
    font_size: int = Field(28, ge=8, le=200)
    color: str = Field("#FFFFFF", pattern=r"^#[0-9A-Fa-f]{6}$")
    outline_color: str = Field("#000000", pattern=r"^#[0-9A-Fa-f]{6}$")
    outline: int = Field(2, ge=0, le=10)
    position: Literal["bottom", "top", "middle"] = "bottom"
    margin_v: int = Field(40, ge=0, le=1000)


class RenderRequest(BaseModel):
    clips: list[TimelineClip] = Field(min_length=1, max_length=200)
    width: int = Field(1920, ge=16, le=7680)
    height: int = Field(1080, ge=16, le=4320)
    fps: float = Field(30, gt=0, le=120)
    transition: Transition = "fade"
    transition_duration: float = Field(0.6, ge=0.1, le=5)
    audio: AudioTrack | None = None
    subtitles: list[SubtitleCue] | str | None = None
    subtitle_style: SubtitleStyle = SubtitleStyle()
    burn_subtitles: bool = True
    output_name: str | None = Field(None, max_length=120)


class ExtractFramesRequest(BaseModel):
    source: str
    fps: float | None = Field(None, gt=0, le=120, description="Frames per second to extract")
    count: int | None = Field(None, ge=1, le=5000, description="Evenly spaced number of frames")
    start_s: float = Field(0.0, ge=0)
    duration_s: float | None = Field(None, gt=0)
    format: Literal["png", "jpg", "webp"] = "png"
    max_frames: int = Field(500, ge=1, le=10000)

    @model_validator(mode="after")
    def _one_mode(self) -> ExtractFramesRequest:
        if self.fps is None and self.count is None:
            self.fps = 1.0
        return self


class AddAudioRequest(BaseModel):
    video: str
    audio: str
    mode: Literal["replace", "mix"] = "replace"
    volume: float = Field(1.0, ge=0, le=4)
    original_volume: float = Field(1.0, ge=0, le=4)
    fade_in_s: float = Field(0.0, ge=0, le=30)
    fade_out_s: float = Field(1.0, ge=0, le=30)
    loop_audio: bool = True
    normalize: bool = True


class AddSubtitlesRequest(BaseModel):
    video: str
    subtitles: list[SubtitleCue] | str
    burn_in: bool = True
    style: SubtitleStyle = SubtitleStyle()


class ResizeRequest(BaseModel):
    source: str
    aspect_ratio: str | None = Field(None, pattern=r"^\d{1,2}:\d{1,2}$")
    width: int | None = Field(None, ge=16, le=7680)
    height: int | None = Field(None, ge=16, le=4320)
    mode: Literal["crop", "pad", "blur"] = "blur"
    pad_color: str = Field("#000000", pattern=r"^#[0-9A-Fa-f]{6}$")


class CompressRequest(BaseModel):
    source: str
    target_size_mb: float | None = Field(None, gt=0.1, le=10000)
    crf: int = Field(28, ge=0, le=51)
    max_width: int | None = Field(None, ge=16, le=7680)
    audio_kbps: int = Field(128, ge=32, le=320)


class InterpolateRequest(BaseModel):
    source: str
    target_fps: float = Field(48, gt=1, le=240)
    mode: Literal["motion", "blend"] = "motion"


class TitleCardRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    subtitle: str | None = Field(None, max_length=300)
    duration_s: float = Field(4.0, gt=0.5, le=60)
    width: int = Field(1920, ge=16, le=7680)
    height: int = Field(1080, ge=16, le=4320)
    fps: float = Field(30, gt=0, le=120)
    background: str = Field("#0F172A", pattern=r"^#[0-9A-Fa-f]{6}$")
    color: str = Field("#FFFFFF", pattern=r"^#[0-9A-Fa-f]{6}$")
    accent: str = Field("#38BDF8", pattern=r"^#[0-9A-Fa-f]{6}$")
    background_image: str | None = None
    font: str | None = None


class SequenceRequest(BaseModel):
    directory: str
    pattern: str = Field("frame_%05d.png", max_length=64, pattern=r"^[A-Za-z0-9_.%-]+$")
    fps: float = Field(24, gt=0, le=120)


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------

def _hex_to_ff(color: str) -> str:
    return "0x" + color.lstrip("#").upper()


def _hex_to_ass(color: str) -> str:
    c = color.lstrip("#")
    r, g, b = c[0:2], c[2:4], c[4:6]
    return f"&H00{b}{g}{r}".upper()


def _fmt_srt_time(t: float) -> str:
    ms = int(round(t * 1000))
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def cues_to_srt(cues: list[SubtitleCue]) -> str:
    lines = []
    for i, cue in enumerate(sorted(cues, key=lambda c: c.start_s), start=1):
        if cue.end_s <= cue.start_s:
            raise ValidationError(f"Untertitel {i}: Ende muss nach Start liegen")
        lines += [str(i), f"{_fmt_srt_time(cue.start_s)} --> {_fmt_srt_time(cue.end_s)}", cue.text.strip(), ""]
    return "\n".join(lines)


def parse_aspect(value: str) -> float:
    a, b = value.split(":")
    if float(b) == 0:
        raise ValidationError("Invalid aspect ratio")
    return float(a) / float(b)


def even(n: float) -> int:
    return max(2, int(round(n / 2)) * 2)


# ----------------------------------------------------------------------------
# Provider
# ----------------------------------------------------------------------------

class FFmpegProvider(ProcessingProvider):
    def __init__(self, info: Any, settings: Any, shared: dict[str, Any] | None = None) -> None:
        super().__init__(info, settings, shared)
        cfg = settings.ffmpeg
        self.ffmpeg = cfg.ffmpeg_path
        self.ffprobe = cfg.ffprobe_path
        self.timeout = cfg.timeout_s
        self.crf = cfg.default_crf
        self.preset = cfg.preset
        self.vcodec = cfg.video_codec
        self.acodec = cfg.audio_codec

    def get_capabilities(self) -> set[Capability]:
        return {Capability.MEDIA_INFO, Capability.CONVERT, Capability.RENDER, Capability.EXTRACT_FRAMES,
                Capability.ADD_AUDIO, Capability.ADD_SUBTITLES, Capability.MERGE, Capability.TRIM, Capability.RESIZE,
                Capability.COMPRESS, Capability.FRAME_INTERPOLATION}

    def _exe(self) -> str:
        exe = shutil.which(self.ffmpeg) or (self.ffmpeg if Path(self.ffmpeg).is_file() else None)
        if not exe:
            raise ToolNotFoundError(f"FFmpeg nicht gefunden ('{self.ffmpeg}'). Installation: docs/INSTALLATION.md")
        return exe

    async def health(self) -> ProviderHealth:
        try:
            exe = self._exe()
        except ToolNotFoundError as exc:
            return ProviderHealth(available=False, detail=exc.message)
        proc = await asyncio.create_subprocess_exec(exe, "-hide_banner", "-version", stdout=asyncio.subprocess.PIPE,
                                                    stderr=asyncio.subprocess.DEVNULL)
        out, _ = await proc.communicate()
        first = out.decode(errors="replace").splitlines()[0] if out else ""
        version = first.split(" ")[2] if first.startswith("ffmpeg version") else None
        return ProviderHealth(available=proc.returncode == 0, detail=first[:120], version=version)

    async def get_info(self, path: Path) -> MediaInfo:
        return await probe_media(Path(path), self.ffprobe)

    # ----------------------------------------------------------- execution
    async def run(self, args: list[str], ctx: JobContext | None = None, *, total_s: float | None = None,
                  cwd: Path | None = None, span: tuple[float, float] = (0.0, 1.0), label: str = "") -> None:
        cmd = [self._exe(), "-hide_banner", "-y", "-nostdin", "-progress", "pipe:1", "-nostats", *args]
        log.debug("ffmpeg %s", " ".join(cmd[1:]))
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, cwd=str(cwd) if cwd else None,
        )
        tail: collections.deque[str] = collections.deque(maxlen=30)

        async def read_err() -> None:
            assert proc.stderr
            async for line in proc.stderr:
                tail.append(line.decode(errors="replace").rstrip())

        async def read_out() -> None:
            assert proc.stdout
            async for raw in proc.stdout:
                line = raw.decode(errors="replace").strip()
                if ctx and total_s and line.startswith("out_time_us="):
                    try:
                        t = int(line.split("=", 1)[1]) / 1_000_000
                    except ValueError:
                        continue
                    frac = min(0.99, max(0.0, t / total_s))
                    ctx.report(span[0] + (span[1] - span[0]) * frac, label or "FFmpeg verarbeitet")

        try:
            await asyncio.wait_for(asyncio.gather(read_out(), read_err(), proc.wait()), timeout=self.timeout)
        except asyncio.CancelledError:
            proc.kill()
            await proc.wait()
            raise
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise StudioTimeoutError(f"FFmpeg hat das Zeitlimit ({int(self.timeout)} s) überschritten") from None
        if proc.returncode != 0:
            relevant = [ln for ln in tail if ln and not ln.startswith("  ")][-6:]
            raise ExternalProcessError("FFmpeg-Fehler: " + " | ".join(relevant), details={"stderr_tail": list(tail)})

    def _out(self, ctx: JobContext, stem: str, suffix: str) -> Path:
        ctx.output_dir.mkdir(parents=True, exist_ok=True)
        base = "".join(c if c.isalnum() or c in "-_" else "_" for c in stem)[:80] or "output"
        target = ctx.output_dir / f"{base}{suffix}"
        i = 1
        while target.exists():
            target = ctx.output_dir / f"{base}_{i:03d}{suffix}"
            i += 1
        return target

    def _venc(self, crf: int | None = None) -> list[str]:
        return ["-c:v", self.vcodec, "-preset", self.preset, "-crf", str(crf if crf is not None else self.crf),
                "-pix_fmt", "yuv420p", "-movflags", "+faststart"]

    def _workdir(self) -> Path:
        return Path(tempfile.mkdtemp(prefix="acs_ff_"))

    def _result(self, files: list[Path], params: dict[str, Any]) -> GenerationResult:
        return GenerationResult(files=files, provider=self.name, parameters=params)

    # ---------------------------------------------------------- operations
    async def convert(self, req: ConvertRequest, ctx: JobContext) -> GenerationResult:
        src = Path(req.source)
        info = await self.get_info(src)
        out = self._out(ctx, f"{src.stem}_converted", f".{req.format}")
        vf: list[str] = []
        if req.width or req.height:
            vf.append(f"scale={req.width or -2}:{req.height or -2}")
        if req.fps:
            vf.append(f"fps={req.fps}")
        args = ["-i", str(src)]
        if req.format in ("mp3", "wav", "m4a"):
            codec = {"mp3": ["-c:a", "libmp3lame", "-q:a", "2"], "wav": ["-c:a", "pcm_s16le"], "m4a": ["-c:a", "aac", "-b:a", "192k"]}
            args += ["-vn", *codec[req.format], str(out)]
        elif req.format == "gif":
            fps = req.fps or min(15, info.fps or 15)
            scale = f"scale={req.width or 640}:-1:flags=lanczos"
            args += ["-filter_complex", f"fps={fps},{scale},split[a][b];[a]palettegen[p];[b][p]paletteuse", str(out)]
        else:
            if vf:
                args += ["-vf", ",".join(vf)]
            if req.format == "webm":
                args += ["-c:v", "libvpx-vp9", "-crf", str(req.crf or 32), "-b:v", "0", "-row-mt", "1"]
                args += ["-an"] if req.remove_audio else ["-c:a", "libopus", "-b:a", "128k"]
            else:
                args += self._venc(req.crf)
                args += ["-an"] if req.remove_audio else ["-c:a", self.acodec, "-b:a", "192k"]
            args.append(str(out))
        await self.run(args, ctx, total_s=info.duration_s, label="Konvertierung")
        return self._result([out], req.model_dump())

    async def trim(self, req: TrimRequest, ctx: JobContext) -> GenerationResult:
        src = Path(req.source)
        duration = req.duration_s or ((req.end_s - req.start_s) if req.end_s else None)
        if duration is not None and duration <= 0:
            raise ValidationError("end_s muss größer als start_s sein")
        out = self._out(ctx, f"{src.stem}_trim", ".mp4")
        args = ["-ss", f"{req.start_s:.3f}", "-i", str(src)]
        if duration:
            args += ["-t", f"{duration:.3f}"]
        args += [*self._venc(), "-c:a", self.acodec, "-b:a", "192k", str(out)]
        await self.run(args, ctx, total_s=duration, label="Schnitt")
        return self._result([out], req.model_dump())

    async def merge(self, req: MergeRequest, ctx: JobContext, *, out_name: str = "merged",
                    span: tuple[float, float] = (0.0, 1.0)) -> GenerationResult:
        infos = [await self.get_info(Path(s)) for s in req.sources]
        for s, info in zip(req.sources, infos, strict=True):
            if info.kind != "video" or not info.duration_s:
                raise ValidationError(f"Kein gültiges Video: {Path(s).name}")
        w = even(req.width or infos[0].width or 1280)
        h = even(req.height or infos[0].height or 720)
        fps = req.fps or infos[0].fps or 30
        td = req.transition_duration if req.transition != "none" else 0.0
        if td and any(i.duration_s <= td * 2 for i in infos):  # type: ignore[operator]
            td = max(0.1, min(i.duration_s for i in infos) / 3)  # type: ignore[type-var]
        args: list[str] = []
        for s in req.sources:
            args += ["-i", str(s)]
        n = len(req.sources)
        filters: list[str] = []
        silent_idx = n
        for i, info in enumerate(infos):
            filters.append(
                f"[{i}:v]scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,"
                f"setsar=1,fps={fps},format=yuv420p,settb=AVTB[v{i}]"
            )
            if info.has_audio:
                filters.append(f"[{i}:a]aformat=sample_rates=48000:channel_layouts=stereo,asetpts=PTS-STARTPTS[a{i}]")
            else:
                args += ["-f", "lavfi", "-t", f"{info.duration_s:.3f}", "-i", "anullsrc=r=48000:cl=stereo"]
                filters.append(f"[{silent_idx}:a]aformat=sample_rates=48000:channel_layouts=stereo[a{i}]")
                silent_idx += 1
        total = sum(i.duration_s or 0 for i in infos) - td * (n - 1)
        if req.transition == "none":
            filters.append("".join(f"[v{i}][a{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=1[vout][aout]")
        else:
            cum = infos[0].duration_s or 0
            vprev, aprev = "v0", "a0"
            for i in range(1, n):
                offset = max(0.0, cum - td)
                vlabel = "vout" if i == n - 1 else f"vx{i}"
                alabel = "aout" if i == n - 1 else f"ax{i}"
                filters.append(f"[{vprev}][v{i}]xfade=transition={req.transition}:duration={td:.3f}:offset={offset:.3f}[{vlabel}]")
                filters.append(f"[{aprev}][a{i}]acrossfade=d={td:.3f}[{alabel}]")
                cum = cum + (infos[i].duration_s or 0) - td
                vprev, aprev = vlabel, alabel
        out = self._out(ctx, out_name, ".mp4")
        args += ["-filter_complex", ";".join(filters), "-map", "[vout]", "-map", "[aout]", *self._venc(),
                 "-c:a", self.acodec, "-b:a", "192k", str(out)]
        await self.run(args, ctx, total_s=total, span=span, label="Clips werden zusammengefügt")
        return self._result([out], req.model_dump() | {"duration_s": round(total, 3)})

    async def image_clip(self, image: Path, duration: float, width: int, height: int, fps: float,
                         ken_burns: KenBurns | None, ctx: JobContext, span: tuple[float, float]) -> Path:
        """Still image → video clip, optionally with Ken-Burns zoom/pan (zoompan)."""
        frames = max(1, int(round(duration * fps)))
        out = self._out(ctx, f"{image.stem}_clip", ".mp4")
        kb = ken_burns or KenBurns(zoom="none")
        # upscale first so zoompan has enough pixels (avoids jitter)
        pre = f"scale={width * 2}:{height * 2}:force_original_aspect_ratio=increase,crop={width * 2}:{height * 2}"
        if kb.zoom == "none" and kb.pan == "none":
            vf = f"{pre},scale={width}:{height},fps={fps},format=yuv420p"
            args = ["-loop", "1", "-t", f"{duration:.3f}", "-i", str(image), "-vf", vf]
        else:
            z_end = 1 + kb.strength
            if kb.zoom == "in":
                z = f"1+({z_end - 1:.4f})*on/{frames}"
            elif kb.zoom == "out":
                z = f"{z_end:.4f}-({z_end - 1:.4f})*on/{frames}"
            else:
                z = f"{z_end:.4f}"
            cx, cy = "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
            if kb.pan == "left":
                cx = f"(iw-iw/zoom)*(1-on/{frames})"
            elif kb.pan == "right":
                cx = f"(iw-iw/zoom)*on/{frames}"
            elif kb.pan == "up":
                cy = f"(ih-ih/zoom)*(1-on/{frames})"
            elif kb.pan == "down":
                cy = f"(ih-ih/zoom)*on/{frames}"
            vf = f"{pre},zoompan=z='{z}':x='{cx}':y='{cy}':d={frames}:s={width}x{height}:fps={fps},format=yuv420p"
            args = ["-i", str(image), "-vf", vf, "-frames:v", str(frames)]
        args += [*self._venc(), "-an", str(out)]
        await self.run(args, ctx, total_s=duration, span=span, label=f"Bild-Clip {image.name}")
        return out

    async def render(self, req: RenderRequest, ctx: JobContext) -> GenerationResult:
        """Timeline render: images (Ken Burns) + videos → transitions → audio → subtitles."""
        n = len(req.clips)
        work: list[Path] = []
        prepared: list[Path] = []
        w, h = even(req.width), even(req.height)
        for i, clip in enumerate(req.clips):
            span = (0.6 * i / n, 0.6 * (i + 1) / n)
            src = Path(clip.source)
            kind = kind_for(src)
            if kind == "image":
                if not clip.duration_s:
                    raise ValidationError(f"Clip {i + 1}: duration_s ist für Bilder erforderlich")
                prepared.append(await self.image_clip(src, clip.duration_s, w, h, req.fps, clip.ken_burns, ctx, span))
                work.append(prepared[-1])
            elif kind == "video":
                if clip.start_s or clip.end_s or clip.duration_s:
                    trimmed = await self.trim(TrimRequest(source=str(src), start_s=clip.start_s or 0, end_s=clip.end_s,
                                                          duration_s=clip.duration_s), ctx)
                    prepared.append(trimmed.files[0])
                    work.append(trimmed.files[0])
                else:
                    prepared.append(src)
            else:
                raise ValidationError(f"Clip {i + 1}: nicht unterstützter Dateityp {src.suffix}")
        name = req.output_name or f"render_{uuid.uuid4().hex[:6]}"
        if len(prepared) == 1:
            single = await self.convert(ConvertRequest(source=str(prepared[0]), format="mp4", width=w, height=h,
                                                       fps=req.fps), ctx)
            current = single.files[0]
        else:
            merged = await self.merge(MergeRequest(sources=[str(p) for p in prepared], transition=req.transition,
                                                   transition_duration=req.transition_duration, width=w, height=h,
                                                   fps=req.fps), ctx, out_name=name if not (req.audio or req.subtitles) else f"{name}_cut",
                                      span=(0.6, 0.8))
            current = merged.files[0]
        if req.audio:
            work.append(current)
            res = await self.add_audio(AddAudioRequest(video=str(current), audio=req.audio.source, mode=req.audio.mode,
                                                       volume=req.audio.volume, fade_in_s=req.audio.fade_in_s,
                                                       fade_out_s=req.audio.fade_out_s, normalize=req.audio.normalize),
                                       ctx, span=(0.8, 0.9))
            current = res.files[0]
        if req.subtitles:
            work.append(current)
            res = await self.add_subtitles(AddSubtitlesRequest(video=str(current), subtitles=req.subtitles,
                                                               burn_in=req.burn_subtitles, style=req.subtitle_style),
                                           ctx, span=(0.9, 1.0))
            current = res.files[0]
        final = current
        if final.stem != name and (req.audio or req.subtitles or len(prepared) == 1):
            target = self._out(ctx, name, ".mp4")
            final.rename(target)
            final = target
        for tmp in work:
            if tmp != final and tmp.exists() and tmp.parent == ctx.output_dir:
                tmp.unlink(missing_ok=True)
        info = await self.get_info(final)
        return self._result([final], {"clips": n, "width": w, "height": h, "fps": req.fps, "transition": req.transition,
                                      "duration_s": info.duration_s, "audio": bool(req.audio), "subtitles": bool(req.subtitles)})

    async def extract_frames(self, req: ExtractFramesRequest, ctx: JobContext) -> GenerationResult:
        src = Path(req.source)
        info = await self.get_info(src)
        duration = req.duration_s or max(0.0, (info.duration_s or 0) - req.start_s)
        target_dir = ctx.output_dir / f"{src.stem}_frames_{uuid.uuid4().hex[:6]}"
        target_dir.mkdir(parents=True, exist_ok=True)
        if req.count:
            fps = req.count / duration if duration else 1
        else:
            fps = req.fps or 1
        args = ["-ss", f"{req.start_s:.3f}", "-i", str(src)]
        if req.duration_s:
            args += ["-t", f"{req.duration_s:.3f}"]
        quality = ["-q:v", "2"] if req.format == "jpg" else []
        limit = min(req.max_frames, req.count or req.max_frames)
        args += ["-vf", f"fps={fps:.6f}", "-frames:v", str(limit), *quality, str(target_dir / f"frame_%05d.{req.format}")]
        await self.run(args, ctx, total_s=duration, label="Frames werden extrahiert")
        files = sorted(target_dir.glob(f"frame_*.{req.format}"))
        return self._result(files, req.model_dump() | {"directory": str(target_dir), "count": len(files)})

    async def add_audio(self, req: AddAudioRequest, ctx: JobContext, span: tuple[float, float] = (0.0, 1.0)) -> GenerationResult:
        video, audio = Path(req.video), Path(req.audio)
        vinfo = await self.get_info(video)
        duration = vinfo.duration_s or 0
        out = self._out(ctx, f"{video.stem}_audio", ".mp4")
        afilters = [f"volume={req.volume}"]
        if req.normalize:
            afilters.insert(0, "loudnorm=I=-16:TP=-1.5:LRA=11")
        if req.fade_in_s:
            afilters.append(f"afade=t=in:st=0:d={req.fade_in_s}")
        if req.fade_out_s and duration > req.fade_out_s:
            afilters.append(f"afade=t=out:st={duration - req.fade_out_s:.3f}:d={req.fade_out_s}")
        args = ["-i", str(video)]
        if req.loop_audio:
            args += ["-stream_loop", "-1"]
        args += ["-i", str(audio)]
        chain = ",".join(afilters)
        if req.mode == "mix" and vinfo.has_audio:
            fc = (f"[1:a]{chain},atrim=0:{duration:.3f}[music];[0:a]volume={req.original_volume}[orig];"
                  f"[orig][music]amix=inputs=2:duration=first:dropout_transition=0[aout]")
        else:
            fc = f"[1:a]{chain},atrim=0:{duration:.3f},asetpts=PTS-STARTPTS[aout]"
        args += ["-filter_complex", fc, "-map", "0:v", "-map", "[aout]", "-c:v", "copy", "-c:a", self.acodec,
                 "-b:a", "192k", "-t", f"{duration:.3f}", "-movflags", "+faststart", str(out)]
        await self.run(args, ctx, total_s=duration, span=span, label="Audio wird hinzugefügt")
        return self._result([out], req.model_dump())

    async def add_subtitles(self, req: AddSubtitlesRequest, ctx: JobContext, span: tuple[float, float] = (0.0, 1.0)) -> GenerationResult:
        video = Path(req.video)
        info = await self.get_info(video)
        work = self._workdir()
        try:
            if isinstance(req.subtitles, str):
                sub_src = Path(req.subtitles)
                if sub_src.suffix.lower() not in (".srt", ".vtt", ".ass"):
                    raise ValidationError("Untertiteldatei muss .srt, .vtt oder .ass sein")
                sub_file = work / f"subs{sub_src.suffix.lower()}"
                shutil.copyfile(sub_src, sub_file)
            else:
                sub_file = work / "subs.srt"
                sub_file.write_text(cues_to_srt(req.subtitles), encoding="utf-8")
            out = self._out(ctx, f"{video.stem}_subtitled", ".mp4")
            if req.burn_in:
                st = req.style
                align = {"bottom": 2, "top": 8, "middle": 5}[st.position]
                style = (f"FontSize={st.font_size},PrimaryColour={_hex_to_ass(st.color)},OutlineColour="
                         f"{_hex_to_ass(st.outline_color)},BorderStyle=1,Outline={st.outline},Alignment={align},MarginV={st.margin_v}")
                font = find_font("sans-bold")
                fonts_opt = ""
                if font:
                    (work / "fonts").mkdir(exist_ok=True)
                    shutil.copyfile(font, work / "fonts" / font.name)
                    fonts_opt = ":fontsdir=fonts"
                vf = f"subtitles={sub_file.name}{fonts_opt}:force_style='{style}'"
                args = ["-i", str(video.resolve()), "-vf", vf, *self._venc(), "-c:a", "copy", str(out.resolve())]
            else:
                args = ["-i", str(video.resolve()), "-i", sub_file.name, "-map", "0", "-map", "1", "-c", "copy",
                        "-c:s", "mov_text", str(out.resolve())]
            await self.run(args, ctx, total_s=info.duration_s, cwd=work, span=span, label="Untertitel")
        finally:
            shutil.rmtree(work, ignore_errors=True)
        return self._result([out], {"burn_in": req.burn_in, "style": req.style.model_dump()})

    async def resize(self, req: ResizeRequest, ctx: JobContext) -> GenerationResult:
        src = Path(req.source)
        info = await self.get_info(src)
        sw, sh = info.width or 1920, info.height or 1080
        if req.width and req.height:
            w, h = even(req.width), even(req.height)
        elif req.aspect_ratio:
            ar = parse_aspect(req.aspect_ratio)
            # keep the longer source edge as reference, cap at 1920 on the long side
            if ar >= 1:
                w = even(min(max(sw, sh), 1920))
                h = even(w / ar)
            else:
                h = even(min(max(sw, sh), 1920))
                w = even(h * ar)
        else:
            raise ValidationError("aspect_ratio oder width+height angeben")
        if req.mode == "crop":
            vf = f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1"
            fc = None
        elif req.mode == "pad":
            vf = (f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
                  f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color={_hex_to_ff(req.pad_color)},setsar=1")
            fc = None
        else:
            vf = None
            fc = (f"[0:v]split[bg][fg];[bg]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},"
                  f"gblur=sigma=30,eq=brightness=-0.08[b];[fg]scale={w}:{h}:force_original_aspect_ratio=decrease[f];"
                  f"[b][f]overlay=(W-w)/2:(H-h)/2,setsar=1,format=yuv420p[vout]")
        is_image = info.kind == "image"
        suffix = src.suffix if is_image else ".mp4"
        out = self._out(ctx, f"{src.stem}_{w}x{h}", suffix)
        args = ["-i", str(src)]
        if fc:
            args += ["-filter_complex", fc, "-map", "[vout]"]
            if not is_image and info.has_audio:
                args += ["-map", "0:a"]
        else:
            args += ["-vf", vf]
        if is_image:
            args += ["-frames:v", "1", str(out)]
        else:
            args += [*self._venc(), "-c:a", self.acodec, "-b:a", "192k", str(out)]
        await self.run(args, ctx, total_s=info.duration_s, label="Format wird angepasst")
        return self._result([out], req.model_dump() | {"width": w, "height": h})

    async def compress(self, req: CompressRequest, ctx: JobContext) -> GenerationResult:
        src = Path(req.source)
        info = await self.get_info(src)
        out = self._out(ctx, f"{src.stem}_compressed", ".mp4")
        args = ["-i", str(src)]
        if req.max_width and info.width and info.width > req.max_width:
            args += ["-vf", f"scale={even(req.max_width)}:-2"]
        if req.target_size_mb and info.duration_s:
            total_kbps = req.target_size_mb * 8192 / info.duration_s
            v_kbps = max(100, int(total_kbps - req.audio_kbps) * 0.95)
            args += ["-c:v", self.vcodec, "-preset", self.preset, "-b:v", f"{int(v_kbps)}k", "-maxrate", f"{int(v_kbps * 1.2)}k",
                     "-bufsize", f"{int(v_kbps * 2)}k", "-pix_fmt", "yuv420p", "-movflags", "+faststart"]
        else:
            args += self._venc(req.crf)
        args += ["-c:a", self.acodec, "-b:a", f"{req.audio_kbps}k", str(out)]
        await self.run(args, ctx, total_s=info.duration_s, label="Komprimierung")
        new = await self.get_info(out)
        return self._result([out], req.model_dump() | {"size_before": info.size_bytes, "size_after": new.size_bytes})

    async def interpolate(self, req: InterpolateRequest, ctx: JobContext) -> GenerationResult:
        src = Path(req.source)
        info = await self.get_info(src)
        out = self._out(ctx, f"{src.stem}_{int(req.target_fps)}fps", ".mp4")
        if req.mode == "motion":
            vf = f"minterpolate=fps={req.target_fps}:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1"
        else:
            vf = f"framerate=fps={req.target_fps}"
        args = ["-i", str(src), "-vf", vf, *self._venc(), "-c:a", "copy", str(out)]
        await self.run(args, ctx, total_s=info.duration_s, label="Frame-Interpolation")
        return self._result([out], req.model_dump() | {"source_fps": info.fps})

    async def title_card(self, req: TitleCardRequest, ctx: JobContext) -> GenerationResult:
        """Animated title card (FFmpeg fallback for motion graphics, no Remotion needed)."""
        work = self._workdir()
        try:
            font = Path(req.font) if req.font else find_font("sans-bold")
            if not font or not font.is_file():
                raise ToolNotFoundError("Keine Schriftart gefunden (z. B. fonts-dejavu installieren)")
            shutil.copyfile(font, work / f"font{font.suffix}")
            (work / "title.txt").write_text(req.title, encoding="utf-8")
            w, h, d = even(req.width), even(req.height), req.duration_s
            fade = min(0.8, d / 4)
            alpha = f"if(lt(t,{fade}),t/{fade},if(gt(t,{d - fade:.3f}),({d:.3f}-t)/{fade},1))"
            size = max(24, int(h * 0.09))
            y_title = f"(h-text_h)/2-{int(h * 0.04)}+{int(h * 0.03)}*(1-min(1,t/{fade}))"
            draw = [f"drawtext=fontfile=font{font.suffix}:textfile=title.txt:fontcolor={_hex_to_ff(req.color)}:"
                    f"fontsize={size}:x=(w-text_w)/2:y='{y_title}':alpha='{alpha}'"]
            bar_w = int(w * 0.12)
            draw.append(f"drawbox=x=(iw-{bar_w})/2:y=ih/2+{int(h * 0.04)}:w={bar_w}:h={max(2, int(h * 0.006))}:"
                        f"color={_hex_to_ff(req.accent)}:t=fill:enable='gte(t,{fade / 2:.3f})'")
            if req.subtitle:
                (work / "subtitle.txt").write_text(req.subtitle, encoding="utf-8")
                draw.append(f"drawtext=fontfile=font{font.suffix}:textfile=subtitle.txt:fontcolor={_hex_to_ff(req.color)}@0.8:"
                            f"fontsize={int(size * 0.42)}:x=(w-text_w)/2:y=h/2+{int(h * 0.08)}:alpha='{alpha}'")
            if req.background_image:
                bg = Path(req.background_image).resolve()
                inputs = ["-loop", "1", "-t", f"{d:.3f}", "-i", str(bg)]
                pre = f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},eq=brightness=-0.25,"
            else:
                inputs = ["-f", "lavfi", "-i", f"color=c={_hex_to_ff(req.background)}:s={w}x{h}:d={d:.3f}:r={req.fps}"]
                pre = ""
            out = self._out(ctx, "title_card", ".mp4")
            args = [*inputs, "-vf", pre + ",".join(draw) + f",fps={req.fps},format=yuv420p", "-t", f"{d:.3f}",
                    *self._venc(), "-an", str(out.resolve())]
            await self.run(args, ctx, total_s=d, cwd=work, label="Titelkarte")
        finally:
            shutil.rmtree(work, ignore_errors=True)
        return self._result([out], req.model_dump())

    async def encode_sequence(self, req: SequenceRequest, ctx: JobContext) -> GenerationResult:
        directory = Path(req.directory)
        frames = sorted(directory.glob(req.pattern.replace("%05d", "*").replace("%04d", "*")))
        if not frames:
            raise ValidationError(f"Keine Frames gefunden: {directory}/{req.pattern}")
        out = self._out(ctx, f"{directory.name}_sequence", ".mp4")
        args = ["-framerate", str(req.fps), "-i", str(directory / req.pattern), *self._venc(), str(out)]
        await self.run(args, ctx, total_s=len(frames) / req.fps, label="Bildsequenz wird kodiert")
        return self._result([out], req.model_dump() | {"frames": len(frames)})

    async def detect(self, path: Path, *, black: bool = True, freeze: bool = True, scenes: bool = False) -> dict[str, Any]:
        """Run blackdetect / freezedetect / scene detection and parse the log output."""
        filters = []
        if black:
            filters.append("blackdetect=d=0.25:pix_th=0.10")
        if freeze:
            filters.append("freezedetect=n=0.003:d=1")
        if scenes:
            filters.append("select='gt(scene,0.35)',metadata=print")
        exe = self._exe()
        proc = await asyncio.create_subprocess_exec(
            exe, "-hide_banner", "-nostdin", "-i", str(path), "-vf", ",".join(filters) or "null", "-an", "-f", "null", "-",
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
        )
        try:
            _, err = await asyncio.wait_for(proc.communicate(), timeout=self.timeout)
        except asyncio.TimeoutError:
            proc.kill()
            raise StudioTimeoutError("Videoanalyse hat das Zeitlimit überschritten") from None
        text = err.decode(errors="replace")
        result: dict[str, Any] = {"black_segments": [], "freeze_segments": [], "scene_changes": []}
        for line in text.splitlines():
            if "black_start:" in line:
                parts = dict(p.split(":", 1) for p in line.split("]")[-1].split() if ":" in p)
                result["black_segments"].append({k: float(v) for k, v in parts.items() if k in ("black_start", "black_end", "black_duration")})
            elif "freeze_start" in line:
                result["freeze_segments"].append({"start": float(line.rsplit(":", 1)[1])})
            elif "freeze_duration" in line and result["freeze_segments"]:
                result["freeze_segments"][-1]["duration"] = float(line.rsplit(":", 1)[1])
            elif "freeze_end" in line and result["freeze_segments"]:
                result["freeze_segments"][-1]["end"] = float(line.rsplit(":", 1)[1])
            elif "pts_time:" in line and "scene" not in line and scenes:
                try:
                    result["scene_changes"].append(float(line.split("pts_time:")[1].split()[0]))
                except (IndexError, ValueError):
                    pass
        return result


def requests_schema() -> dict[str, Any]:
    """JSON schemas of all FFmpeg request models (used by docs/API)."""
    models = [ConvertRequest, TrimRequest, MergeRequest, RenderRequest, ExtractFramesRequest, AddAudioRequest,
              AddSubtitlesRequest, ResizeRequest, CompressRequest, InterpolateRequest, TitleCardRequest]
    return {m.__name__: m.model_json_schema() for m in models}


if __name__ == "__main__":  # pragma: no cover
    print(json.dumps(requests_schema(), indent=2)[:2000])
