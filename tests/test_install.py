"""Tests for install.sh, the installer behind curl ... | sh, with stand-ins for git and docker.

The stand-in git "clones" a tiny ok3d whose ./ok3d only records that it ran, so these test
what install.sh decides: which release, where, the settings it makes, and when it stops.
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

GIT = r"""#!/bin/sh
echo "git $*" >>"$FAKE_LOG"
case "$1" in
ls-remote)
	printf '%s\trefs/tags/%s\n' a v0.3.0 b v0.4.0 c v0.10.0 d v0.11.0-rc1 e v0.9.2
	;;
clone)
	for last; do :; done
	mkdir -p "$last/.git"
	cp "$FAKE_EXAMPLE" "$last/settings.example.yaml"
	if [ -z "${FAKE_OLD:-}" ]; then
		printf '#!/bin/sh\ncase "$1" in\ninstall) echo "ran ok3d install in $(pwd)" ;;\nesac\n' >"$last/ok3d"
	else
		printf '#!/bin/sh\necho old\n' >"$last/ok3d"
	fi
	chmod +x "$last/ok3d"
	;;
esac
"""


@pytest.fixture
def env(tmp_path: Path) -> dict[str, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in {"git": GIT, "docker": "#!/bin/sh\n"}.items():
        (bin_dir / name).write_text(body)
        (bin_dir / name).chmod(0o755)
    data_root = tmp_path / "data"
    data_root.mkdir()
    return {
        **{k: v for k, v in os.environ.items() if not k.startswith("OK3D_")},
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "HOME": str(tmp_path / "home"),
        "FAKE_LOG": str(tmp_path / "calls.log"),
        "FAKE_EXAMPLE": str(ROOT / "settings.example.yaml"),
        "OK3D_DATA_ROOT": str(data_root),
    }


def install(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["sh", str(ROOT / "install.sh")], capture_output=True, text=True, env=env, check=False)


def calls(env: dict[str, str]) -> list[str]:
    log = Path(env["FAKE_LOG"])
    return log.read_text().splitlines() if log.exists() else []


def test_it_installs_the_newest_release_into_home(env: dict[str, str]) -> None:
    result = install(env)
    assert result.returncode == 0, result.stderr
    home = Path(env["HOME"]) / "ok3d"
    clone = next(line for line in calls(env) if line.startswith("git clone"))
    assert "--branch v0.10.0 " in clone  # newest by number, not by text; never a test tag
    assert f"ran ok3d install in {home}" in result.stdout


def test_it_makes_settings_with_your_data_root(env: dict[str, str]) -> None:
    install(env)
    settings = Path(env["HOME"]) / "ok3d" / "settings.yaml"
    assert f"  dataRoot: {env['OK3D_DATA_ROOT']}\n" in settings.read_text()
    assert stat.S_IMODE(settings.stat().st_mode) == 0o600


def test_it_keeps_settings_you_have(env: dict[str, str]) -> None:
    install(env)
    settings = Path(env["HOME"]) / "ok3d" / "settings.yaml"
    settings.write_text("settingsVersion: 1\n  dataRoot: " + env["OK3D_DATA_ROOT"] + "\n# mine\n")
    install(env)
    assert "# mine" in settings.read_text()


def test_it_brings_a_checkout_up_to_the_release(env: dict[str, str]) -> None:
    install(env)
    install({**env, "OK3D_VERSION": "v0.9.2"})
    assert any(line.endswith("checkout --quiet v0.9.2") for line in calls(env))


def test_it_says_how_to_make_the_data_root(env: dict[str, str]) -> None:
    result = install({**env, "OK3D_DATA_ROOT": "/nonexistent/ok3d"})
    assert result.returncode == 1
    assert "sudo install -d -o" in result.stderr
    assert "ran ok3d install" not in result.stdout


@pytest.mark.parametrize("root", ["relative/path", "/srv/ok 3d", "/srv/$(reboot)", "/srv/a#b"])
def test_it_refuses_an_odd_data_root(env: dict[str, str], root: str) -> None:
    result = install({**env, "OK3D_DATA_ROOT": root})
    assert result.returncode == 1
    assert not (Path(env["HOME"]) / "ok3d" / "settings.yaml").exists()


@pytest.mark.parametrize("version", ["latest", "v1", "--upload-pack=x", "v0.5.0;reboot"])
def test_it_refuses_an_odd_version(env: dict[str, str], version: str) -> None:
    result = install({**env, "OK3D_VERSION": version})
    assert result.returncode == 1
    assert not any(line.startswith("git clone") for line in calls(env))


def test_it_wont_overwrite_a_folder_that_isnt_ok3d(env: dict[str, str]) -> None:
    (Path(env["HOME"]) / "ok3d").mkdir(parents=True)
    result = install(env)
    assert result.returncode == 1
    assert "isn't an ok3d checkout" in result.stderr


def test_it_stops_on_a_release_without_an_installer(env: dict[str, str]) -> None:
    result = install({**env, "FAKE_OLD": "1"})
    assert result.returncode == 1
    assert "has no installer" in result.stderr
