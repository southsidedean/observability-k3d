"""The pre-commit hook, run for real in a throwaway repository: what it refuses and what it
lets through. Each test makes one commit attempt and checks the hook's answer.
"""

from __future__ import annotations

import os
import re
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


def private_names(repo: Path, text: str) -> None:
    """Writes the repository's private-names list (git may make no hooks folder)."""
    names = Path(git(repo, "rev-parse", "--absolute-git-dir").stdout.strip()) / "hooks" / "private-names"
    names.parent.mkdir(parents=True, exist_ok=True)
    names.write_text(text)


@pytest.mark.parametrize(("listed", "written"), [
    ("media-box", "media_box"), ("media-box", "MediaBox"), ("media-box", "media.box"),
    ("media-box", "media - box"), ("media-box", "media\\_box"), ("media box", "media-box"),
    ("box9", "box-9"), ("box9", "BOX 9"), ("MediaBox", "media-box"),
])  # fmt: skip
def test_a_private_name_is_refused_however_it_is_written(repo: Path, listed: str, written: str) -> None:
    private_names(repo, f"{listed}\n")
    add(repo, "notes.md", f"First line.\nGrafana runs on {written}.\n")
    result = commit(repo)
    assert result.returncode == 1
    assert "notes.md" in result.stderr
    # It says where, not what.
    assert written.lower() not in result.stderr.lower()


@pytest.mark.parametrize("name", ["café.md", "two words.md", "tab\there.md", 'quote".md'])
def test_a_file_git_would_quote_is_still_checked(repo: Path, name: str) -> None:
    private_names(repo, "myrealhost\n")
    add(repo, name, "Grafana runs on myrealhost.\n")
    assert commit(repo).returncode == 1


def test_a_file_that_isnt_utf8_is_still_checked(repo: Path) -> None:
    private_names(repo, "myrealhost\n")
    add(repo, "latin1.md", "Caf\xe9 notes: Grafana runs on myrealhost.\n".encode("latin-1"))
    assert commit(repo).returncode == 1


def test_a_private_name_in_a_file_name_is_refused(repo: Path) -> None:
    private_names(repo, "myrealhost\n")
    add(repo, "MyRealHost-notes.md", "Nothing private here.\n")
    result = commit(repo)
    assert result.returncode == 1
    assert "name of a file" in result.stderr
    assert "myrealhost" not in result.stderr.lower()


def test_a_private_name_in_the_commit_message_is_refused(repo: Path) -> None:
    private_names(repo, "myrealhost\n")
    add(repo, "notes.md", "Nothing private here.\n")
    result = subprocess.run(["git", "commit", "-q", "-m", "Notes about MyRealHost"], cwd=repo,
                            capture_output=True, text=True, check=False)  # fmt: skip
    assert result.returncode == 1
    assert "commit message" in result.stderr
    assert "real" not in result.stderr.lower()


def test_a_list_the_check_cant_read_stops_the_commit(repo: Path) -> None:
    private_names(repo, "my(host\n")  # not a valid regex: it would match nothing, and pass everything
    add(repo, "notes.md", "Nothing private here.\n")
    result = commit(repo)
    assert result.returncode == 1
    assert "valid regex" in result.stderr


def test_a_list_with_windows_line_endings_still_matches(repo: Path) -> None:
    private_names(repo, "myrealhost\r\nother  \r\n")
    add(repo, "notes.md", "Grafana runs on myrealhost.\n")
    assert commit(repo).returncode == 1


def test_without_its_name_check_the_hook_refuses(repo: Path) -> None:
    private_names(repo, "myrealhost\n")
    (repo.parent / "scripts" / "private-names.sh").unlink()
    add(repo, "notes.md", "Nothing private here.\n")
    result = commit(repo)
    assert result.returncode == 1
    assert "private-names.sh" in result.stderr


def name_check(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """scripts/private-names.sh, run in the test repository."""
    return subprocess.run(["sh", str(ROOT / "scripts" / "private-names.sh"), *args], cwd=repo,
                          capture_output=True, text=True, check=False)  # fmt: skip


def test_the_patterns_a_list_gives(repo: Path) -> None:
    sep = "[^A-Za-z0-9]{0,3}"
    private_names(repo, "# a comment\n\nmedia-box\n-box9-\nMediaBox\n2024\nmy\\.host\n- _\n")
    result = name_check(repo, "patterns")
    assert result.returncode == 0
    assert result.stdout.splitlines() == [f"media{sep}box", f"box{sep}9", f"Media{sep}Box", "2024", "my\\.host"]


def test_the_name_check_passes_only_clean_text(repo: Path) -> None:
    (repo / "clean.md").write_text("Grafana runs on my-server.lan.\n")
    (repo / "named.md").write_text("Grafana runs on my_real_host.\n")
    (repo / "-n").write_text("Grafana runs on my real host.\n")
    assert name_check(repo, "patterns").returncode == 3  # no list
    assert name_check(repo, "check", "clean.md").returncode == 2  # it can't check, so it doesn't pass
    private_names(repo, "# only a comment\n\n")
    assert name_check(repo, "check", "clean.md").returncode == 2  # nor with a list of no patterns
    private_names(repo, "my-real-host\n")
    assert name_check(repo, "check", "clean.md").returncode == 0
    named = name_check(repo, "check", "named.md")
    assert named.returncode == 1
    assert "named.md: a private name on line 1" in named.stderr
    assert "real" not in named.stderr
    assert name_check(repo, "check", "-n").returncode == 1  # a file named like an option
    assert name_check(repo, "check", "clean.md", "missing.md").returncode == 2
    assert name_check(repo, "check", "named.md", "missing.md").returncode == 2
    assert name_check(repo, "check").returncode == 2  # no files: the usage
    private_names(repo, "my(host\n")
    assert name_check(repo, "check", "clean.md").returncode == 2


def test_a_message_line_starting_with_a_hash_is_checked_too(repo: Path) -> None:
    # With -m, git keeps lines that start with #, and "#42 ..." is a common subject.
    private_names(repo, "media-box\n")
    add(repo, "notes.md", "Nothing private here.\n")
    result = subprocess.run(["git", "commit", "-q", "-m", "#42 MediaBox fix"], cwd=repo,
                            capture_output=True, text=True, check=False)  # fmt: skip
    assert result.returncode == 1
    assert "commit message" in result.stderr


def test_a_commit_that_takes_a_name_out_can_be_made_with_v(repo: Path) -> None:
    # git commit -v shows the diff below the message, and the diff still has the name in it.
    add(repo, "leak.md", "Grafana runs on media-box.\n")
    assert commit(repo).returncode == 0  # before the name was listed
    private_names(repo, "media-box\n")
    git(repo, "rm", "-q", "leak.md")
    editor = "sh -c 'printf \"Take the name out\\n\" | cat - \"$1\" >\"$1.new\" && mv \"$1.new\" \"$1\"' editor"
    result = subprocess.run(["git", "commit", "-q", "-v"], cwd=repo, capture_output=True, text=True, check=False,
                            env={**os.environ, "GIT_EDITOR": editor})  # fmt: skip
    assert result.returncode == 0, result.stderr


def test_a_merge_gets_the_same_checks(repo: Path) -> None:
    private_names(repo, "media-box\n")
    git(repo, "switch", "-q", "-c", "side")
    add(repo, "leak.md", "Grafana runs on media-box.\n")
    # Committed past the hooks, as --no-verify can; the merge mustn't bring it in unchecked.
    subprocess.run(["git", "commit", "-q", "--no-verify", "-m", "side"], cwd=repo, check=True)
    git(repo, "switch", "-q", "work")
    add(repo, "other.md", "Something else.\n")
    assert commit(repo).returncode == 0
    result = subprocess.run(["git", "merge", "-q", "--no-ff", "-m", "Merge the side branch", "side"], cwd=repo,
                            capture_output=True, text=True, check=False)  # fmt: skip
    assert result.returncode != 0
    assert "private-names" in result.stderr


def test_no_list_and_no_script_means_no_check(repo: Path) -> None:
    (repo.parent / "scripts" / "private-names.sh").unlink()
    add(repo, "notes.md", "Nothing private here.\n")
    assert commit(repo).returncode == 0


def test_a_scissors_line_typed_into_a_message_hides_nothing(repo: Path) -> None:
    private_names(repo, "media-box\n")
    add(repo, "notes.md", "Nothing private here.\n")
    result = subprocess.run(["git", "commit", "-q", "-m", "title", "-m", "# --- >8 ---", "-m", "MediaBox"],
                            cwd=repo, capture_output=True, text=True, check=False)  # fmt: skip
    assert result.returncode == 1


def test_commit_v_works_with_a_longer_comment_string(repo: Path) -> None:
    # core.commentString came in git 2.45; an older git ignores it, and this would test nothing.
    version = subprocess.run(["git", "version"], capture_output=True, text=True, check=True).stdout
    found = re.search(r"(\d+)\.(\d+)", version)
    if not found or (int(found[1]), int(found[2])) < (2, 45):
        pytest.skip("core.commentString needs git 2.45 or newer")
    add(repo, "leak.md", "Grafana runs on media-box.\n")
    assert commit(repo).returncode == 0  # before the name was listed
    private_names(repo, "media-box\n")
    git(repo, "config", "core.commentString", "//")
    git(repo, "rm", "-q", "leak.md")
    editor = "sh -c 'printf \"Take the name out\\n\" | cat - \"$1\" >\"$1.new\" && mv \"$1.new\" \"$1\"' editor"
    result = subprocess.run(["git", "commit", "-q", "-v"], cwd=repo, capture_output=True, text=True, check=False,
                            env={**os.environ, "GIT_EDITOR": editor})  # fmt: skip
    assert result.returncode == 0, result.stderr


def test_a_merge_on_main_is_explained(repo: Path) -> None:
    git(repo, "switch", "-q", "-c", "side")
    add(repo, "side.md", "Side.\n")
    assert commit(repo).returncode == 0
    subprocess.run(["git", "switch", "-q", "-c", "main", "work"], cwd=repo, check=True)
    result = subprocess.run(["git", "merge", "-q", "--no-ff", "-m", "Merge", "side"], cwd=repo,
                            capture_output=True, text=True, check=False)  # fmt: skip
    assert result.returncode != 0
    assert "--ff-only" in result.stderr


def test_finishing_a_merge_on_main_is_explained(repo: Path) -> None:
    subprocess.run(["git", "switch", "-q", "-c", "main", "work"], cwd=repo, check=True)
    git(repo, "switch", "-q", "-c", "side")
    add(repo, "README.md", "Side's version.\n")
    assert commit(repo).returncode == 0
    git(repo, "switch", "-q", "main")
    subprocess.run(["git", "commit", "-q", "--no-verify", "--allow-empty", "-m", "on main"], cwd=repo, check=True)
    (repo / "README.md").write_text("Main's version.\n")
    git(repo, "add", "README.md")
    subprocess.run(["git", "commit", "-q", "--no-verify", "-m", "main's"], cwd=repo, check=True)
    merged = subprocess.run(["git", "merge", "-q", "side"], cwd=repo, capture_output=True, text=True, check=False)
    assert merged.returncode != 0  # a conflict
    add(repo, "README.md", "Both.\n")
    result = commit(repo)
    assert result.returncode == 1
    assert "--ff-only" in result.stderr
