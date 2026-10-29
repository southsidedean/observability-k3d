"""The pre-commit hook, run for real in a throwaway repository: what it refuses and what it
lets through. Each test makes one commit attempt and checks the hook's answer.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A new repository on a work branch, with the hooks turned on and one first commit."""
    hooks = tmp_path / "hooks"
    shutil.copytree(ROOT / ".githooks", hooks)
    # The hook finds its name check next to it, as in the repository.
    (tmp_path / "scripts").mkdir()
    shutil.copy2(ROOT / "scripts" / "private-names.sh", tmp_path / "scripts")
    work = tmp_path / "repo"
    work.mkdir()
    for args in (
        ["init", "-q", "-b", "work"],
        ["config", "user.name", "Test"],
        ["config", "user.email", "test@example.com"],
        ["config", "commit.gpgsign", "false"],
        ["config", "core.hooksPath", str(hooks)],
    ):
        git(work, *args)
    (work / "README.md").write_text("A test repository.\n")
    git(work, "add", "README.md")
    assert commit(work).returncode == 0
    return work


def git(work: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=work, capture_output=True, text=True, check=True)


def commit(work: Path, **env: str) -> subprocess.CompletedProcess[str]:
    """Try to commit what's staged; the hook's answer is in returncode and stderr."""
    return subprocess.run(
        ["git", "commit", "-q", "-m", "test"],
        cwd=work,
        capture_output=True,
        text=True,
        env={**os.environ, **env},
        check=False,  # a refusal is an answer to check, not an error
    )


def add(work: Path, name: str, content: str | bytes) -> None:
    path = work / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content)
    git(work, "add", "-f", name)


def test_a_commit_on_main_is_refused(repo: Path) -> None:
    git(repo, "branch", "-m", "main")
    add(repo, "notes.md", "Notes.\n")
    result = commit(repo)
    assert result.returncode == 1
    assert "This is main" in result.stderr


@pytest.mark.parametrize(
    "name", ["settings.yaml", "devices.yaml", "users.yml", ".env", ".env.local", "local/agent.yaml", "ca.key"]
)
def test_your_own_setup_and_keys_are_refused(repo: Path, name: str) -> None:
    add(repo, name, "x: 1\n")
    result = commit(repo)
    assert result.returncode == 1
    assert name in result.stderr


@pytest.mark.parametrize("name", ["settings.example.yaml", "devices.example.yaml", ".env.example"])
def test_the_examples_are_allowed(repo: Path, name: str) -> None:
    add(repo, name, "UNIFI_API_KEY=\n")
    assert commit(repo).returncode == 0


# The key header is built in two pieces so this file doesn't contain one whole, which the hook
# would refuse when this file itself is committed.
PRIVATE_KEY_HEADER = "-----BEGIN RSA " + "PRIVATE KEY-----"


@pytest.mark.parametrize(
    "line",
    ["UNIFI_API_KEY=abc123", "SMTP_PASSWORD=hunter2", "NTFY_TOKEN=tk_123", PRIVATE_KEY_HEADER],
)
def test_lines_that_look_like_secrets_are_refused(repo: Path, line: str) -> None:
    add(repo, "notes.txt", line + "\n")
    result = commit(repo)
    assert result.returncode == 1
    assert "look like secrets" in result.stderr
    # The value itself isn't repeated back.
    assert "abc123" not in result.stderr and "hunter2" not in result.stderr


def test_a_name_from_the_private_names_list_is_refused(repo: Path) -> None:
    names = Path(git(repo, "rev-parse", "--absolute-git-dir").stdout.strip()) / "hooks" / "private-names"
    names.parent.mkdir(parents=True, exist_ok=True)
    names.write_text("# my own names\nmyrealhost\n192\\.168\\.42\\.\n")
    add(repo, "notes.md", "Grafana runs on MyRealHost.\n")
    result = commit(repo)
    assert result.returncode == 1
    assert "private-names" in result.stderr


def test_a_private_name_is_refused_in_a_worktree_too(repo: Path) -> None:
    # In a worktree, .git is a file and the hooks folder is the main repository's.
    names = Path(git(repo, "rev-parse", "--absolute-git-dir").stdout.strip()) / "hooks" / "private-names"
    names.parent.mkdir(parents=True, exist_ok=True)
    names.write_text("myrealhost\n")
    tree = repo.parent / "tree"
    assert git(repo, "worktree", "add", "-q", "-b", "other", str(tree)).returncode == 0
    add(tree, "notes.md", "Grafana runs on MyRealHost.\n")
    result = commit(tree)
    assert result.returncode == 1
    assert "private-names" in result.stderr


def test_text_without_private_names_is_allowed(repo: Path) -> None:
    names = Path(git(repo, "rev-parse", "--absolute-git-dir").stdout.strip()) / "hooks" / "private-names"
    names.parent.mkdir(parents=True, exist_ok=True)
    names.write_text("myrealhost\n")
    add(repo, "notes.md", "Grafana runs on my-server.lan.\n")
    assert commit(repo).returncode == 0


def test_an_image_needs_images_checked(repo: Path) -> None:
    add(repo, "images/shot.png", b"\x89PNG\r\n\x1a\n")
    result = commit(repo)
    assert result.returncode == 1
    assert "IMAGES_CHECKED=1" in result.stderr
    assert commit(repo, IMAGES_CHECKED="1").returncode == 0


@pytest.mark.parametrize(("listed", "written"), [
    ("media-box", "media_box"), ("media-box", "MediaBox"), ("media-box", "media.box"),
    ("media box", "media-box"), ("box9", "box-9"), ("box9", "BOX 9"),
])  # fmt: skip
def test_a_private_name_is_refused_however_it_is_written(repo: Path, listed: str, written: str) -> None:
    names = Path(git(repo, "rev-parse", "--absolute-git-dir").stdout.strip()) / "hooks" / "private-names"
    names.write_text(f"{listed}\n")
    add(repo, "notes.md", f"First line.\nGrafana runs on {written}.\n")
    result = commit(repo)
    assert result.returncode == 1
    assert "notes.md: line 2" in result.stderr
    # It says where, not what.
    assert written.lower() not in result.stderr.lower()


def test_without_its_name_check_the_hook_refuses(repo: Path) -> None:
    names = Path(git(repo, "rev-parse", "--absolute-git-dir").stdout.strip()) / "hooks" / "private-names"
    names.write_text("myrealhost\n")
    (repo.parent / "scripts" / "private-names.sh").unlink()
    add(repo, "notes.md", "Nothing private here.\n")
    result = commit(repo)
    assert result.returncode == 1
    assert "private-names.sh" in result.stderr


def check(repo: Path, *files: str) -> subprocess.CompletedProcess[str]:
    """scripts/private-names.sh check, run in the test repository."""
    return subprocess.run(["sh", str(ROOT / "scripts" / "private-names.sh"), "check", *files], cwd=repo,
                          capture_output=True, text=True, check=False)  # fmt: skip


def test_the_name_check_passes_only_clean_text(repo: Path) -> None:
    names = Path(git(repo, "rev-parse", "--absolute-git-dir").stdout.strip()) / "hooks" / "private-names"
    (repo / "clean.md").write_text("Grafana runs on my-server.lan.\n")
    (repo / "named.md").write_text("Grafana runs on my_real_host.\n")
    assert check(repo, "clean.md").returncode == 2  # no list: it can't check, so it doesn't pass
    names.write_text("# only a comment\n\n")
    assert check(repo, "clean.md").returncode == 2  # nor with a list of no patterns
    names.write_text("my-real-host\n")
    assert check(repo, "clean.md").returncode == 0
    named = check(repo, "named.md")
    assert named.returncode == 1
    assert "named.md: a private name on line 1" in named.stderr
    assert "real" not in named.stderr
    assert check(repo, "clean.md", "missing.md").returncode == 2
    assert check(repo).returncode == 2  # no files: the usage
