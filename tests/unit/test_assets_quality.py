"""Asset store (sidecars, search, organize, thumbnails) and quality analysis."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from backend.assets import AssetStore
from backend.core.db import Database
from backend.core.errors import PathNotAllowedError, ValidationError
from backend.quality.analyzer import QualityAnalyzer, analyze_image_file, validate_resolution
from tests.conftest import needs_ffmpeg, write_test_image, write_test_video


@pytest.fixture
def store(tmp_path: Path) -> AssetStore:
    root = tmp_path / "assets"
    (root / "generated").mkdir(parents=True)
    return AssetStore(Database(tmp_path / "a.db"), root, tmp_path / "cache")


async def test_register_writes_sidecar_and_is_searchable(store: AssetStore) -> None:
    img = write_test_image(store.root / "generated" / "fox.png")
    a = await store.register(img, prompt="a red fox in snow", seed=42, model="sd15", tags=["Fox", "fox", "Winter"],
                             project="Demo", workflow={"1": {"class_type": "X", "inputs": {}}})
    assert a.kind == "image" and a.width == 640 and a.tags == ["fox", "winter"]
    side = json.loads((img.parent / "fox.png.meta.json").read_text())
    assert side["asset"]["seed"] == 42 and side["workflow"]["1"]["class_type"] == "X"
    items, total = store.search("fox snow")
    assert total == 1 and items[0].id == a.id
    assert store.search(tags=["winter"])[1] == 1 and store.search(kind="video")[1] == 0
    assert store.search(project="Demo")[1] == 1
    updated = store.update(a.id, add_tags=["best"], favorite=True, rating=5)
    assert updated.favorite and "best" in updated.tags
    assert store.search(favorite=True)[1] == 1
    with pytest.raises(ValidationError):
        store.update(a.id, rating=9)
    # sidecar keeps workflow after metadata update
    assert "workflow" in json.loads((img.parent / "fox.png.meta.json").read_text())


async def test_register_outside_root_rejected(store: AssetStore, tmp_path: Path) -> None:
    outside = write_test_image(tmp_path / "elsewhere.png")
    with pytest.raises(PathNotAllowedError):
        await store.register(outside)


async def test_rescan_and_organize(store: AssetStore) -> None:
    write_test_image(store.root / "references" / "ref.png")
    write_test_image(store.root / "generated" / "a.png")
    (store.root / "generated" / ".gitkeep").write_text("")
    res = await store.rescan()
    assert sorted(res["added"]) == ["generated/a.png", "references/ref.png"]
    plan = store.organize("by_kind", dry_run=True)
    assert plan["count"] == 1 and plan["moves"][0]["to"] == "images/a.png"
    assert (store.root / "generated" / "a.png").exists()  # dry run changes nothing
    store.organize("by_kind", dry_run=False)
    assert (store.root / "images" / "a.png").exists() and not (store.root / "generated" / "a.png").exists()
    (store.root / "images" / "a.png").unlink()
    res = await store.rescan()
    assert res["removed"] == ["images/a.png"]


async def test_thumbnails(store: AssetStore) -> None:
    a = await store.register(write_test_image(store.root / "generated" / "t.png", (1600, 900)))
    thumb = await store.thumbnail(a.id, 256)
    from PIL import Image

    with Image.open(thumb) as im:
        assert max(im.size) == 256


@needs_ffmpeg
async def test_video_metadata_and_thumbnail(store: AssetStore) -> None:
    v = await store.register(write_test_video(store.root / "generated" / "v.mp4", 1.5))
    assert v.kind == "video" and v.duration_s == pytest.approx(1.5, abs=0.1) and v.fps == 24
    assert (await store.thumbnail(v.id)).is_file()


# ---------------------------------------------------------------- quality
def test_image_quality_sharp_vs_blurry(tmp_path: Path) -> None:
    sharp = analyze_image_file(write_test_image(tmp_path / "s.png"))
    blurry = analyze_image_file(write_test_image(tmp_path / "b.png", sharp=False))
    assert sharp.metrics["sharpness"] > blurry.metrics["sharpness"] * 5
    assert sharp.passed
    assert any(i.check == "sharpness" for i in blurry.issues)


def test_blank_and_aspect_checks(tmp_path: Path) -> None:
    from PIL import Image

    p = tmp_path / "blank.png"
    Image.new("RGB", (800, 600), (128, 128, 128)).save(p)
    rep = analyze_image_file(p, expected_aspect="16:9", min_width=1280)
    checks = {i.check for i in rep.issues}
    assert {"blank", "aspect_ratio", "resolution"} <= checks and not rep.passed and rep.score <= 10


def test_validate_resolution_presets() -> None:
    assert validate_resolution(1280, 720, preset="youtube_thumbnail")["valid"]
    bad = validate_resolution(1080, 1080, preset="instagram_story")
    assert not bad["valid"] and any("Seitenverhältnis" in p for p in bad["problems"])
    assert not validate_resolution(1300, 720, preset="youtube_thumbnail", exact=True)["valid"]
    with pytest.raises(ValidationError):
        validate_resolution(1, 1, preset="nope")


@needs_ffmpeg
async def test_video_quality_detects_black_and_frozen(settings: Any, tmp_path: Path) -> None:
    import subprocess

    from backend.providers.registry import ProviderRegistry

    ff = ProviderRegistry(settings).get("processing", "ffmpeg")
    black = tmp_path / "black.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=black:s=320x240:d=3:r=24",
                    "-pix_fmt", "yuv420p", str(black)], check=True)
    rep = await QualityAnalyzer(ff).analyze_video(black, expected_fps=30, require_audio=True)
    checks = {i.check for i in rep.issues}
    assert {"black_frames", "fps", "audio"} <= checks and not rep.passed
    good = await QualityAnalyzer(ff).analyze_video(write_test_video(tmp_path / "ok.mp4", 2), expected_fps=24)
    assert good.passed, good.issues
    md = QualityAnalyzer.report_markdown([rep, good])
    assert "black.mp4" in md and "❌" in md and "✅" in md
