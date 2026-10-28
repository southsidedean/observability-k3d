"""Tests for ok3d-helper (src/ok3d/helper.py): it carries out a good request, and refuses
everything else without running anything.

The helper assumes the Dashboard's container may have been taken over, so most of these are
requests it must refuse: wrong fields, wrong values, wrong age, wrong size, and things that
aren't plain files at all. A fake ok3d command records what it was asked to run.
"""

from __future__ import annotations

import fcntl
import os
import stat
import time
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from ok3d import helper

ID = "3f9a0c51d2e8b746"


@pytest.fixture
def folders(tmp_path: Path) -> helper.Folders:
    """A data root and an ok3d checkout whose ok3d command records its arguments."""
    ok3d_dir = tmp_path / "ok3d"
    ok3d_dir.mkdir()
    command = ok3d_dir / "ok3d"
    command.write_text('#!/bin/sh\necho "$@" >> "$(dirname "$0")/ran"\necho "checked: $1"\n')
    command.chmod(0o755)
    f = helper.Folders.for_data_root(ok3d_dir, tmp_path / "data")
    helper.prepare(f)
    return f


def ran(folders: helper.Folders) -> list[str]:
    path = folders.ok3d_dir / "ran"
    return path.read_text().splitlines() if path.exists() else []


def result(folders: helper.Folders) -> dict[str, str]:
    head, _, _ = (folders.own / "result").read_text().partition("\n\n")
    return dict(line.split("=", 1) for line in head.splitlines())


def send(folders: helper.Folders, text: str | bytes) -> None:
    data = text.encode() if isinstance(text, str) else text
    (folders.outbox / "request").write_bytes(data)


def test_a_check_runs_ok3d_check_and_answers(folders: helper.Folders) -> None:
    send(folders, f"id={ID}\naction=check\n")
    assert helper.handle_once(folders) == f"ran ./ok3d check for {ID}: exit 0"
    assert ran(folders) == ["check"]
    assert {"id": ID, "action": "check", "state": "finished", "exit": "0"}.items() <= result(folders).items()
    assert (folders.own / "result").read_text().endswith("\n\nchecked: check\n")
    assert not (folders.outbox / "request").exists()
    assert not (folders.own / "request").exists()


def test_an_apply_runs_ok3d_apply(folders: helper.Folders) -> None:
    send(folders, f"action=apply\nid={ID}\n")
    helper.handle_once(folders)
    assert ran(folders) == ["apply"]


def test_a_failing_command_reports_its_exit_status(folders: helper.Folders) -> None:
    (folders.ok3d_dir / "ok3d").write_text("#!/bin/sh\necho broken\nexit 3\n")
    send(folders, f"id={ID}\naction=check\n")
    helper.handle_once(folders)
    assert result(folders)["exit"] == "3"


def test_no_request_does_nothing(folders: helper.Folders) -> None:
    assert helper.handle_once(folders) is None
    assert not (folders.own / "result").exists()


def test_the_answer_is_readable_only_by_you(folders: helper.Folders) -> None:
    send(folders, f"id={ID}\naction=check\n")
    helper.handle_once(folders)
    for name in ("result", "output", "seen"):
        assert stat.S_IMODE((folders.own / name).stat().st_mode) == 0o600, name
    assert stat.S_IMODE(folders.own.stat().st_mode) == 0o700


def test_only_the_last_lines_of_output_are_kept(folders: helper.Folders) -> None:
    (folders.ok3d_dir / "ok3d").write_text("#!/bin/sh\nseq 1 500\n")
    send(folders, f"id={ID}\naction=check\n")
    helper.handle_once(folders)
    output = (folders.own / "result").read_text().partition("\n\n")[2].splitlines()
    assert output == [str(n) for n in range(301, 501)]


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("", "the request isn't finished"),
        (f"id={ID}\naction=check", "the request isn't finished"),
        (f"id={ID}\naction=delete\n", "the request asks for something the helper doesn't do"),
        (f"id={ID}\naction=check --yes\n", "the request asks for something the helper doesn't do"),
        (f"id={ID}\naction=check;reboot\n", "the request asks for something the helper doesn't do"),
        (f"id={ID}\naction=CHECK\n", "the request asks for something the helper doesn't do"),
        (f"id={ID}\naction=\n", "the request asks for something the helper doesn't do"),
        ("id=short\naction=check\n", "the request's id isn't valid"),
        (f"id={ID.upper()}\naction=check\n", "the request's id isn't valid"),
        (f"id=../{ID}\naction=check\n", "the request's id isn't valid"),
        (f"id={'a' * 65}\naction=check\n", "the request's id isn't valid"),
        (f"id={ID}\n", "the request is missing a line"),
        (f"id={ID}\naction=check\naction=apply\n", "the request repeats a line"),
        (f"id={ID}\naction=check\nstack=all\n", "the request has a line the helper doesn't know"),
        (f"id={ID}\n\naction=check\n", "the request has a line the helper doesn't know"),
        (f"id={ID}\r\naction=check\r\n", "the request's id isn't valid"),
        (f" id={ID}\naction=check\n", "the request has a line the helper doesn't know"),
        (f"id={ID}\naction=check\n" + "#" * 5000 + "\n", "the request is too big"),
        (f"id={ID}\naction=chéck\n", "the request isn't plain text"),
        (f"id={ID}\naction=check\x00\n", "the request asks for something the helper doesn't do"),
    ],
)
def test_a_bad_request_is_refused_and_nothing_runs(folders: helper.Folders, text: str, reason: str) -> None:
    send(folders, text)
    assert helper.handle_once(folders) == f"refused a request: {reason}"
    assert ran(folders) == []
    answer = result(folders)
    assert answer["state"] == "refused"
    assert answer["reason"] == reason
    # The answer never repeats what the request said.
    assert "id" not in answer


def test_a_stale_request_is_refused(folders: helper.Folders) -> None:
    send(folders, f"id={ID}\naction=check\n")
    old = time.time() - helper.MAX_AGE - 10
    os.utime(folders.outbox / "request", (old, old))
    assert helper.handle_once(folders) == "refused a request: the request isn't recent"
    assert ran(folders) == []


def test_a_request_from_the_future_is_refused(folders: helper.Folders) -> None:
    send(folders, f"id={ID}\naction=check\n")
    later = time.time() + helper.MAX_SKEW + 60
    os.utime(folders.outbox / "request", (later, later))
    assert helper.handle_once(folders) == "refused a request: the request isn't recent"


def test_the_same_request_twice_runs_once(folders: helper.Folders) -> None:
    send(folders, f"id={ID}\naction=apply\n")
    helper.handle_once(folders)
    send(folders, f"id={ID}\naction=apply\n")
    assert helper.handle_once(folders) == "refused a request: the request was carried out already"
    assert ran(folders) == ["apply"]


def test_old_ids_are_forgotten_after_a_while(folders: helper.Folders) -> None:
    for n in range(helper.SEEN + 5):
        assert not helper.seen_before(folders, f"{n:016x}")
    seen = (folders.own / "seen").read_text().split()
    assert len(seen) == helper.SEEN
    assert seen[-1] == f"{helper.SEEN + 4:016x}"


def test_a_link_is_refused_and_its_target_is_left_alone(folders: helper.Folders, tmp_path: Path) -> None:
    secret = tmp_path / "secret"
    secret.write_text(f"id={ID}\naction=check\n")
    (folders.outbox / "request").symlink_to(secret)
    assert helper.handle_once(folders) == "refused a request: the request isn't a plain file"
    assert ran(folders) == []
    assert secret.read_text() == f"id={ID}\naction=check\n"
    assert not (folders.own / "request").exists()


def test_a_hard_link_is_refused(folders: helper.Folders, tmp_path: Path) -> None:
    other = folders.outbox / "other"
    other.write_text(f"id={ID}\naction=check\n")
    os.link(other, folders.outbox / "request")
    assert helper.handle_once(folders) == "refused a request: the request is a link to another file"
    assert ran(folders) == []
    assert other.exists()


def test_a_folder_is_refused_and_removed(folders: helper.Folders) -> None:
    (folders.outbox / "request" / "deep").mkdir(parents=True)
    (folders.outbox / "request" / "deep" / "file").write_text("x")
    assert helper.handle_once(folders) == "refused a request: the request isn't a plain file"
    assert not (folders.own / "request").exists()


def test_a_folder_inside_a_link_is_not_followed_when_removed(folders: helper.Folders, tmp_path: Path) -> None:
    keep = tmp_path / "keep"
    keep.mkdir()
    (keep / "file").write_text("x")
    (folders.outbox / "request").mkdir()
    (folders.outbox / "request" / "link").symlink_to(keep)
    helper.handle_once(folders)
    assert (keep / "file").exists()


def test_a_pipe_is_refused_without_waiting(folders: helper.Folders) -> None:
    os.mkfifo(folders.outbox / "request")
    assert helper.handle_once(folders) == "refused a request: the request isn't a plain file"
    assert ran(folders) == []


def test_something_left_in_the_helpers_folder_is_cleared(folders: helper.Folders) -> None:
    (folders.own / "request").mkdir()
    (folders.own / "request" / "x").write_text("x")
    send(folders, f"id={ID}\naction=check\n")
    assert helper.handle_once(folders) is None
    send(folders, f"id={ID}\naction=check\n")
    assert helper.handle_once(folders) == f"ran ./ok3d check for {ID}: exit 0"


def test_a_command_that_runs_too_long_is_stopped(folders: helper.Folders, monkeypatch: pytest.MonkeyPatch) -> None:
    (folders.ok3d_dir / "ok3d").write_text("#!/bin/sh\necho started\nsleep 30\n")
    monkeypatch.setitem(helper.TIMEOUTS, "check", 1)
    send(folders, f"id={ID}\naction=check\n")
    helper.handle_once(folders)
    assert result(folders)["exit"] == "124"
    assert "stopped ./ok3d check after 1 seconds" in (folders.own / "result").read_text()


def test_a_second_helper_will_not_start(folders: helper.Folders, tmp_path: Path) -> None:
    lock = os.open(folders.own / "lock", os.O_WRONLY | os.O_CREAT, 0o600)
    fcntl.flock(lock, fcntl.LOCK_EX)
    try:
        with pytest.raises(SystemExit, match="another helper"):
            helper.watch(folders)
    finally:
        os.close(lock)


def test_it_wont_start_without_the_ok3d_command(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="no ok3d command"):
        helper.prepare(helper.Folders.for_data_root(tmp_path, tmp_path / "data"))


@settings(max_examples=500, deadline=None)
@given(data=st.binary(max_size=helper.MAX_REQUEST + 100), age=st.floats(-1000, 1000))
def test_any_bytes_are_either_a_valid_request_or_refused(data: bytes, age: float) -> None:
    now = 1_800_000_000.0
    try:
        request = helper.parse_request(data, now - age, now)
    except helper.Refused:
        return
    assert request.action in helper.ACTIONS
    assert helper.ID.fullmatch(request.id)
    assert data == f"id={request.id}\naction={request.action}\n".encode() or data == (
        f"action={request.action}\nid={request.id}\n".encode()
    )


@settings(max_examples=300, deadline=None)
@given(
    action=st.text(max_size=20),
    request_id=st.text(max_size=80),
    extra=st.lists(st.tuples(st.text(max_size=10), st.text(max_size=10)), max_size=3),
)
def test_only_known_actions_and_ids_get_through(action: str, request_id: str, extra: list[tuple[str, str]]) -> None:
    lines = [f"id={request_id}", f"action={action}"] + [f"{k}={v}" for k, v in extra]
    data = ("\n".join(lines) + "\n").encode("utf-8")
    try:
        request = helper.parse_request(data, 0.0, 0.0)
    except helper.Refused:
        return
    assert not extra
    assert request.action in helper.ACTIONS
    assert helper.ID.fullmatch(request.id)


def test_it_runs_on_the_hosts_own_python_with_nothing_installed(folders: helper.Folders) -> None:
    # The service runs `python3 -I src/ok3d/helper.py`: isolated, so it can't lean on the
    # ok3d package being installed, or on anything else outside the standard library.
    import subprocess
    import sys

    script = Path(helper.__file__)
    send(folders, f"id={ID}\naction=check\n")
    out = subprocess.run(
        [sys.executable, "-I", str(script), "once", "--ok3d-dir", str(folders.ok3d_dir),
         "--data-root", str(folders.outbox.parent.parent)],
        capture_output=True, text=True, check=True, cwd="/",
    )
    assert out.stdout.strip() == f"ran ./ok3d check for {ID}: exit 0"
    assert ran(folders) == ["check"]
