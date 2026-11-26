"""Config, paths, hardware profile selection, catalog."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError as PydanticValidationError

from backend.core.catalog import Catalog, frames_4n1
from backend.core.config import deep_merge, env_overrides, load_settings, parse_dotenv, save_local_overrides
from backend.core.errors import NotFoundError, PathNotAllowedError, ValidationError
from backend.core.hardware import GpuInfo, HardwareReport, collect_report, select_profile
from backend.core.paths import PathGuard, safe_filename, slugify

REPO = Path(__file__).resolve().parents[2]


# ----------------------------------------------------------------- config
def test_env_overrides_nested_and_typed() -> None:
    out = env_overrides({"ACS__SERVER__PORT": "9000", "ACS__HARDWARE__PROFILE": "mid", "OTHER": "x",
                         "ACS__QUALITY__AUTO_CHECK": "false"})
    assert out == {"server": {"port": 9000}, "hardware": {"profile": "mid"}, "quality": {"auto_check": False}}


def test_deep_merge_does_not_mutate() -> None:
    base = {"a": {"b": 1, "c": 2}}
    merged = deep_merge(base, {"a": {"b": 5}})
    assert merged == {"a": {"b": 5, "c": 2}} and base == {"a": {"b": 1, "c": 2}}


def test_dotenv_parser(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text('# comment\nexport ACS_API_TOKEN="abc"\nACS__SERVER__PORT=9100\nBROKEN\n', encoding="utf-8")
    assert parse_dotenv(env) == {"ACS_API_TOKEN": "abc", "ACS__SERVER__PORT": "9100"}


def test_load_settings_layering_and_secrets(tmp_path: Path) -> None:
    (tmp_path / "configs").mkdir()
    (tmp_path / "configs" / "studio.yaml").write_text("server: {port: 8500}\napi_token: from-yaml\n", encoding="utf-8")
    (tmp_path / "configs" / "studio.local.yaml").write_text("server: {port: 8600}\n", encoding="utf-8")
    s = load_settings(tmp_path, environ={"ACS__COMFYUI__URL": "http://x:1"})
    assert s.server.port == 8600
    assert s.comfyui.url == "http://x:1"
    assert s.api_token is None  # never from YAML
    s2 = load_settings(tmp_path, environ={"ACS_API_TOKEN": "secret"})
    assert s2.api_token == "secret" and "secret" not in str(s2.public_dict())


def test_save_local_overrides_validates(tmp_path: Path) -> None:
    (tmp_path / "configs").mkdir()
    save_local_overrides(tmp_path, {"hardware": {"profile": "high"}})
    assert load_settings(tmp_path, environ={}).hardware.profile == "high"
    with pytest.raises(PydanticValidationError):
        save_local_overrides(tmp_path, {"hardware": {"profile": "ultra"}})


# ------------------------------------------------------------------ paths
def test_path_guard_blocks_traversal(tmp_path: Path) -> None:
    root = tmp_path / "assets"
    (root / "a").mkdir(parents=True)
    (root / "a" / "f.png").write_bytes(b"x")
    guard = PathGuard([root], default_root=root)
    assert guard.resolve("a/f.png") == (root / "a" / "f.png").resolve()
    for bad in ("../secret", "/etc/passwd", "a/../../x", "a\x00b"):
        with pytest.raises((PathNotAllowedError, ValidationError)):
            guard.resolve(bad)
    with pytest.raises(NotFoundError):
        guard.resolve("a/missing.png")


def test_path_guard_symlink_escape(tmp_path: Path) -> None:
    root = tmp_path / "assets"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret")
    (root / "link.txt").symlink_to(outside)
    with pytest.raises(PathNotAllowedError):
        PathGuard([root], root).resolve("link.txt")


def test_safe_names(tmp_path: Path) -> None:
    assert safe_filename("../../evil name?.png") == "evil_name_.png"
    assert safe_filename("") == "file"
    assert slugify("Nordlicht Kaffee GmbH!") == "nordlicht-kaffee-gmbh"
    guard = PathGuard([tmp_path], tmp_path)
    (tmp_path / "x.png").write_bytes(b"1")
    assert guard.output_path(tmp_path, "x.png").name == "x_001.png"


# --------------------------------------------------------------- hardware
def _report(gpus: list[GpuInfo], ram: float = 32.0, disk: float = 200.0) -> HardwareReport:
    return HardwareReport(os="Linux", os_version="t", architecture="x86_64", cpu_model="c", cpu_cores_physical=8,
                          cpu_cores_logical=16, ram_total_gb=ram, ram_available_gb=ram, disk_free_gb=disk,
                          disk_total_gb=500, gpus=gpus, python_version="3.12")


@pytest.mark.parametrize(
    "gpus, ram, expected",
    [
        ([], 16, "low"),
        ([GpuInfo(vendor="nvidia", name="RTX 3050", vram_total_gb=6, backend="cuda")], 16, "low"),
        ([GpuInfo(vendor="nvidia", name="RTX 3060", vram_total_gb=12, backend="cuda")], 32, "mid"),
        ([GpuInfo(vendor="nvidia", name="RTX 4090", vram_total_gb=24, backend="cuda")], 64, "high"),
        ([GpuInfo(vendor="nvidia", name="RTX 4080", vram_total_gb=16, backend="cuda")], 16, "mid"),
        ([GpuInfo(vendor="amd", name="RX 7900", vram_total_gb=24, backend="rocm")], 64, "high"),
        ([GpuInfo(vendor="apple", name="M2", backend="mps", unified_memory=True)], 16, "low"),
        ([GpuInfo(vendor="apple", name="M3 Pro", backend="mps", unified_memory=True)], 36, "mid"),
        ([GpuInfo(vendor="apple", name="M3 Max", backend="mps", unified_memory=True)], 128, "high"),
        ([GpuInfo(vendor="amd", name="Radeon", vram_total_gb=4, backend="directml")], 32, "low"),
    ],
)
def test_select_profile(gpus: list[GpuInfo], ram: float, expected: str) -> None:
    decision = select_profile(_report(gpus, ram))
    assert decision.profile == expected
    assert decision.cpu_only == (not gpus or all(g.backend == "none" for g in gpus))


def test_profile_override_and_warnings() -> None:
    d = select_profile(_report([], 8, disk=10), override="mid")
    assert d.profile == "mid" and any("manuell" in w for w in d.warnings)
    assert any("Speicher" in w for w in d.warnings) and any("RAM" in w for w in d.warnings)


def test_apple_effective_vram() -> None:
    r = _report([GpuInfo(vendor="apple", name="M", backend="mps", unified_memory=True)], 64)
    assert r.effective_vram_gb == pytest.approx(41.6)


def test_collect_report_runs_on_this_machine(tmp_path: Path) -> None:
    report = collect_report(tmp_path)
    assert report.ram_total_gb > 0 and report.cpu_cores_logical
    assert "python" in report.tools and report.tools["python"].available


# ---------------------------------------------------------------- catalog
def test_catalog_consistency() -> None:
    from backend.providers.comfyui.templates import TemplateLibrary

    catalog = Catalog(REPO / "configs")
    templates = TemplateLibrary(REPO / "engines" / "comfyui" / "workflows")
    for m in catalog.models.values():
        assert m.files, m.id
        for f in m.files:
            assert f.url.startswith("https://huggingface.co/"), f.url
            assert f.size_gb > 0
        for tpl_id in m.tasks.values():
            tpl = templates.get(tpl_id)
            unknown = set(m.params) - set(tpl.meta.parameters)
            assert not unknown, f"{m.id}: params {unknown} not in template {tpl_id}"
        assert m.commercial_use in (True, False, "restricted")
    for name, profile in catalog.profiles.items():
        for mid in profile.image.models + profile.video.models + profile.upscale:
            assert mid in catalog.models, f"profile {name} references unknown model {mid}"
    assert catalog.get("flux1-dev").commercial_use is False


def test_catalog_resolution_and_frames() -> None:
    catalog = Catalog(REPO / "configs")
    assert catalog.resolution("sdxl", "16:9") == (1344, 768)
    assert catalog.resolution("sd15", "5:4") == (680, 512)  # nearest
    assert catalog.resolution(None, "1:1") is None
    assert frames_4n1(48) == 49 and frames_4n1(81) == 81 and frames_4n1(200, 121) == 121 and frames_4n1(1) == 1
    fits, note = catalog.hardware_fit(catalog.get("sdxl"), 0, 16, cpu_only=True)
    assert not fits and "GPU" in note
    fits, note = catalog.hardware_fit(catalog.get("wan22-i2v-14b"), 24, 32, cpu_only=False)
    assert fits and "RAM" in note
