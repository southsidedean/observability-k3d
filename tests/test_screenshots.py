"""Tests for the screenshots: scripts/screenshots.sh refuses anything but the simulated network,
scripts/screenshots.py keeps only the picture in each PNG, and every picture in
images/screenshots/ is one docs/screenshots.json lists, in both themes, with no metadata left.
The browser itself runs only on the test VM, so nothing here starts one.
"""

from __future__ import annotations

import importlib.util
import json
import os
import struct
import subprocess
import zlib
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parent.parent
SHOTS = ROOT / "docs" / "screenshots.json"
IMAGES = ROOT / "images" / "screenshots"


def load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("screenshots", ROOT / "scripts" / "screenshots.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


screenshots = load_script()


def chunk(kind: bytes, body: bytes) -> bytes:
    return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))


def png(*extra: bytes) -> bytes:
    """A one-pixel PNG, with extra chunks before its picture."""
    header = chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 0, 0, 0, 0))
    data = chunk(b"IDAT", zlib.compress(b"\x00\x00"))
    return bytes(screenshots.SIGNATURE) + header + b"".join(extra) + data + chunk(b"IEND", b"")


def test_metadata_is_taken_out_and_the_picture_kept() -> None:
    marked = png(chunk(b"tEXt", b"Comment\x00taken on my-server.lan"), chunk(b"tIME", b"\x07\xea\x0a\x1c\x00\x00\x00"),
                 chunk(b"eXIf", b"MM\x00*"), chunk(b"sRGB", b"\x00"))  # fmt: skip
    clean = screenshots.strip(marked)
    assert [kind for kind, _ in screenshots.chunks(clean)] == [b"IHDR", b"sRGB", b"IDAT", b"IEND"]
    assert b"my-server" not in clean
    assert screenshots.strip(clean) == clean


@pytest.mark.parametrize("bad", [b"GIF89a", png()[:-3], png().replace(b"IDAT", b"IDAt")])
def test_a_damaged_png_is_refused(bad: bytes) -> None:
    with pytest.raises(ValueError):
        screenshots.strip(bad)


def test_the_shot_list_is_valid() -> None:
    config = screenshots.load_shots(SHOTS)
    assert {shot["site"] for shot in config["shots"]} == {"dashboard", "grafana"}


@pytest.mark.parametrize("shots", [
    [{"name": "a", "site": "dashboard", "path": "/"}, {"name": "a", "site": "dashboard", "path": "/keys"}],
    [{"name": "a", "site": "elsewhere", "path": "/"}],
    [{"name": "a", "site": "grafana", "path": "https://example.com/"}],
    [{"name": "../a", "site": "grafana", "path": "/"}],
])  # fmt: skip
def test_a_bad_shot_list_is_refused(tmp_path: Path, shots: list[dict[str, str]]) -> None:
    path = tmp_path / "shots.json"
    path.write_text(json.dumps({"viewport": {}, "shots": shots}))
    with pytest.raises(ValueError):
        screenshots.load_shots(path)


def run(tmp_path: Path, *args: str, settings: str | None = None, devices: str | None = None) -> subprocess.CompletedProcess[str]:
    """scripts/screenshots.sh with a fake docker that only records it was called."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    (bin_dir / "docker").write_text(f'#!/bin/sh\necho "$@" >> {tmp_path}/docker.log\n')
    (bin_dir / "docker").chmod(0o755)
    env = {k: v for k, v in os.environ.items() if not k.startswith("OK3D_")}
    env |= {"PATH": f"{bin_dir}:{env['PATH']}", "OK3D_SETTINGS": settings or str(tmp_path / "settings.yaml"),
            "OK3D_DEVICES": devices or str(ROOT / "devices.demo.yaml")}  # fmt: skip
    return subprocess.run([str(ROOT / "scripts" / "screenshots.sh"), *args], cwd=ROOT, env=env, capture_output=True,
                          text=True, check=False)  # fmt: skip


def test_it_refuses_settings_for_a_real_domain(tmp_path: Path) -> None:
    (tmp_path / "settings.yaml").write_text("host:\n  dataRoot: /srv/ok3d\ntls:\n  domain: my-server.lan\n")
    result = run(tmp_path)
    assert result.returncode == 1
    assert "not noc.home.arpa" in result.stderr
    assert not (tmp_path / "docker.log").exists()


def test_it_refuses_devices_that_arent_the_demos(tmp_path: Path) -> None:
    (tmp_path / "settings.yaml").write_text((ROOT / "settings.example.yaml").read_text())
    devices = tmp_path / "devices.yaml"
    devices.write_text("devices:\n  - name: router\n    address: 192.168.1.1\n    role: gateway\n    checks: [ping]\n")
    result = run(tmp_path, devices=str(devices))
    assert result.returncode == 1
    assert "isn't devices.demo.yaml" in result.stderr
    assert not (tmp_path / "docker.log").exists()


def test_setup_wont_touch_settings_that_are_there(tmp_path: Path) -> None:
    (tmp_path / "settings.yaml").write_text("settingsVersion: 1\n")
    result = run(tmp_path, "--setup")
    assert result.returncode == 1
    assert "is here already" in result.stderr
    assert (tmp_path / "settings.yaml").read_text() == "settingsVersion: 1\n"


def test_it_needs_ok3d_installed(tmp_path: Path) -> None:
    text = (ROOT / "settings.example.yaml").read_text().replace("dataRoot: /srv/ok3d", f"dataRoot: {tmp_path}/data")
    (tmp_path / "settings.yaml").write_text(text)
    result = run(tmp_path)
    assert result.returncode == 1
    assert "is ok3d installed and applied here?" in result.stderr


def test_an_unknown_option_shows_the_usage(tmp_path: Path) -> None:
    assert "Usage: scripts/screenshots.sh [--setup]" in run(tmp_path, "--all").stderr


def test_every_picture_is_a_listed_shot_in_both_themes_with_no_metadata() -> None:
    pictures = sorted(p.name for p in IMAGES.glob("*.png")) if IMAGES.is_dir() else []
    if not pictures:
        pytest.skip("no screenshots yet")
    names = {shot["name"] for shot in screenshots.load_shots(SHOTS)["shots"]}
    assert pictures == sorted(f"{n}-{t}.png" for n in names for t in screenshots.THEMES)
    sources = json.loads((IMAGES / "sources.json").read_text())
    assert sorted(sources) == pictures
    for name in pictures:
        kinds = {kind for kind, _ in screenshots.chunks((IMAGES / name).read_bytes())}
        assert kinds <= screenshots.KEEP, name
