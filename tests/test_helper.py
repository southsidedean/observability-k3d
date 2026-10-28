"""Tests for ok3d-helper (src/ok3d/helper.py): it carries out a good request, and refuses
everything else without running anything.

The helper assumes the Dashboard's container may have been taken over, so most of these are
requests it must refuse: wrong fields, wrong values, wrong age, wrong size, things that aren't
plain files at all, and tricks with the folders themselves. None of them may stop it from
answering the next request. A fake ok3d command records what it was asked to run.
"""

from __future__ import annotations

import fcntl
import os
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from ok3d import helper

ID = "3f9a0c51d2e8b746"
GOOD = f"id={ID}\naction=check\n"


def make_ok3d(tmp_path: Path) -> Path:
    """An ok3d checkout whose ok3d command records its arguments."""
    ok3d_dir = tmp_path / "ok3d"
    ok3d_dir.mkdir()
    command = ok3d_dir / "ok3d"
    command.write_text('#!/bin/sh\necho "$@" >> "$(dirname "$0")/ran"\necho "checked: $1"\n')
    command.chmod(0o755)
    return ok3d_dir


@pytest.fixture
def h(tmp_path: Path) -> helper.Opened:
    """The helper's folders, opened, in a new data root."""
    folders = helper.Folders.for_data_root(make_ok3d(tmp_path), tmp_path / "data")
    folders.data_root.mkdir()
    return helper.open_folders(folders)


def ran(h: helper.Opened) -> list[str]:
    path = h.folders.ok3d_dir / "ran"
    return path.read_text().splitlines() if path.exists() else []


def result(h: helper.Opened) -> dict[str, str]:
    head, _, _ = (h.folders.own / "result").read_text().partition("\n\n")
    return dict(line.split("=", 1) for line in head.splitlines())


def send(h: helper.Opened, text: str | bytes = GOOD) -> None:
    data = text.encode() if isinstance(text, str) else text
    (h.folders.outbox / "request").write_bytes(data)


def taken(h: helper.Opened) -> list[str]:
    return sorted(os.listdir(h.folders.own / "taken"))


def test_a_check_runs_ok3d_check_and_answers(h: helper.Opened) -> None:
    send(h)
    assert helper.handle_once(h) == f"ran ./ok3d check for {ID}: exit 0"
    assert ran(h) == ["check"]
    assert {"id": ID, "action": "check", "state": "finished", "exit": "0"}.items() <= result(h).items()
    assert (h.folders.own / "result").read_text().endswith("\n\nchecked: check\n")
    assert not (h.folders.outbox / "request").exists()
    assert taken(h) == []


def test_an_apply_runs_ok3d_apply(h: helper.Opened) -> None:
    send(h, f"action=apply\nid={ID}\n")
    helper.handle_once(h)
    assert ran(h) == ["apply"]


def test_a_failing_command_reports_its_exit_status(h: helper.Opened) -> None:
    (h.folders.ok3d_dir / "ok3d").write_text("#!/bin/sh\necho broken\nexit 3\n")
    send(h)
    helper.handle_once(h)
    assert result(h)["exit"] == "3"


def test_a_command_that_cant_start_still_gets_an_answer(h: helper.Opened) -> None:
    (h.folders.ok3d_dir / "ok3d").chmod(0o644)
    send(h)
    assert helper.handle_once(h) == f"couldn't run ./ok3d check for {ID}"
    assert {"id": ID, "state": "failed", "reason": "the ok3d command couldn't run"}.items() <= result(h).items()


def test_no_request_does_nothing(h: helper.Opened) -> None:
    assert helper.handle_once(h) is None
    assert not (h.folders.own / "result").exists()


def test_the_answer_is_readable_only_by_you(h: helper.Opened) -> None:
    send(h)
    helper.handle_once(h)
    for name in ("result", "output", "seen"):
        assert stat.S_IMODE((h.folders.own / name).stat().st_mode) == 0o600, name
    for folder in (h.folders.own, h.folders.outbox, h.folders.own / "taken"):
        assert stat.S_IMODE(folder.stat().st_mode) == 0o700, folder


def test_folders_made_by_someone_else_are_tightened(tmp_path: Path) -> None:
    folders = helper.Folders.for_data_root(make_ok3d(tmp_path), tmp_path / "data")
    folders.outbox.mkdir(parents=True, mode=0o777)
    folders.outbox.chmod(0o777)
    helper.open_folders(folders)
    assert stat.S_IMODE(folders.outbox.stat().st_mode) == 0o700


def test_only_the_last_lines_of_output_are_kept(h: helper.Opened) -> None:
    (h.folders.ok3d_dir / "ok3d").write_text("#!/bin/sh\nseq 1 500\n")
    send(h)
    helper.handle_once(h)
    output = (h.folders.own / "result").read_text().partition("\n\n")[2].splitlines()
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
def test_a_bad_request_is_refused_and_nothing_runs(h: helper.Opened, text: str, reason: str) -> None:
    send(h, text)
    assert helper.handle_once(h) == f"refused a request: {reason}"
    assert ran(h) == []
    answer = result(h)
    assert answer["state"] == "refused"
    assert answer["reason"] == reason
    # The answer repeats nothing from the request but a valid id, so the page can match it.
    assert set(answer) <= {"id", "state", "reason", "finished"}
    assert answer.get("id", ID) == ID


def test_a_refusal_names_the_request_when_its_id_is_valid(h: helper.Opened) -> None:
    send(h, f"id={ID}\naction=delete\n")
    helper.handle_once(h)
    assert result(h)["id"] == ID
    send(h, "id=../../etc\naction=delete\n")
    helper.handle_once(h)
    assert "id" not in result(h)


def test_a_stale_request_is_refused(h: helper.Opened) -> None:
    send(h)
    old = time.time() - helper.MAX_AGE - 10
    os.utime(h.folders.outbox / "request", (old, old))
    assert helper.handle_once(h) == "refused a request: the request isn't recent"
    assert ran(h) == []


def test_a_request_from_the_future_is_refused(h: helper.Opened) -> None:
    send(h)
    later = time.time() + helper.MAX_SKEW + 60
    os.utime(h.folders.outbox / "request", (later, later))
    assert helper.handle_once(h) == "refused a request: the request isn't recent"


def test_the_same_request_twice_runs_once(h: helper.Opened) -> None:
    send(h, f"id={ID}\naction=apply\n")
    helper.handle_once(h)
    send(h, f"id={ID}\naction=apply\n")
    assert helper.handle_once(h) == "refused a request: the request was carried out already"
    assert ran(h) == ["apply"]


def test_old_ids_are_forgotten_after_a_while(h: helper.Opened) -> None:
    for n in range(helper.SEEN + 5):
        assert not helper.seen_before(h, f"{n:016x}")
    seen = (h.folders.own / "seen").read_text().split()
    assert len(seen) == helper.SEEN
    assert seen[-1] == f"{helper.SEEN + 4:016x}"


def test_a_link_is_refused_and_its_target_is_left_alone(h: helper.Opened, tmp_path: Path) -> None:
    secret = tmp_path / "secret"
    secret.write_text(GOOD)
    (h.folders.outbox / "request").symlink_to(secret)
    assert helper.handle_once(h) == "refused a request: the request isn't a plain file"
    assert ran(h) == []
    assert secret.read_text() == GOOD
    assert taken(h) == []


def test_a_hard_link_is_refused(h: helper.Opened) -> None:
    other = h.folders.outbox / "other"
    other.write_text(GOOD)
    os.link(other, h.folders.outbox / "request")
    assert helper.handle_once(h) == "refused a request: the request is a link to another file"
    assert ran(h) == []
    assert other.read_text() == GOOD


def test_a_pipe_is_refused_without_waiting(h: helper.Opened) -> None:
    os.mkfifo(h.folders.outbox / "request")
    assert helper.handle_once(h) == "refused a request: the request isn't a plain file"
    assert ran(h) == []
    assert taken(h) == []


def test_a_folder_is_refused_and_left_untouched(h: helper.Opened, tmp_path: Path) -> None:
    keep = tmp_path / "keep"
    keep.mkdir()
    (keep / "file").write_text("x")
    (h.folders.outbox / "request" / "deep").mkdir(parents=True)
    (h.folders.outbox / "request" / "link").symlink_to(keep)
    assert helper.handle_once(h) == "refused a request: the request isn't a plain file"
    assert (keep / "file").exists()
    # It stays where it landed, under a name of its own, and nothing inside it is touched.
    [left] = taken(h)
    assert (h.folders.own / "taken" / left / "deep").is_dir()


@pytest.mark.skipif(os.getuid() == 0, reason="root ignores folder permissions")
def test_a_folder_that_cant_be_removed_doesnt_stop_the_next_request(h: helper.Opened) -> None:
    locked = h.folders.outbox / "request" / "sub"
    locked.mkdir(parents=True)
    (locked / "x").write_text("x")
    locked.chmod(0)
    try:
        assert helper.handle_once(h) == "refused a request: the request isn't a plain file"
        send(h)
        assert helper.handle_once(h) == f"ran ./ok3d check for {ID}: exit 0"
    finally:
        for left in taken(h):
            (h.folders.own / "taken" / left / "sub").chmod(0o700)


def test_a_very_deep_folder_doesnt_stop_the_next_request(h: helper.Opened) -> None:
    path = h.folders.outbox / "request"
    path.mkdir()
    fd = os.open(path, os.O_RDONLY)
    for _ in range(2000):  # deeper than a service's open-file limit
        os.mkdir("d", dir_fd=fd)
        child = os.open("d", os.O_RDONLY, dir_fd=fd)
        os.close(fd)
        fd = child
    os.close(fd)
    assert helper.handle_once(h) == "refused a request: the request isn't a plain file"
    send(h)
    assert helper.handle_once(h) == f"ran ./ok3d check for {ID}: exit 0"


def test_an_outbox_swapped_for_a_link_leads_nowhere(h: helper.Opened, tmp_path: Path) -> None:
    # Someone replaces the outbox with a link to a folder of yours that has a "request" in it.
    victim = tmp_path / "victim"
    (victim / "request" / "src").mkdir(parents=True)
    (victim / "request" / "src" / "code.py").write_text("print('mine')\n")
    os.rename(h.folders.outbox, tmp_path / "old-outbox")
    h.folders.outbox.symlink_to(victim)
    assert helper.handle_once(h) is None
    assert (victim / "request" / "src" / "code.py").read_text() == "print('mine')\n"
    assert taken(h) == []


def test_an_outbox_that_is_a_link_at_start_is_refused(tmp_path: Path) -> None:
    folders = helper.Folders.for_data_root(make_ok3d(tmp_path), tmp_path / "data")
    (tmp_path / "elsewhere").mkdir()
    folders.outbox.parent.mkdir(parents=True)
    folders.outbox.symlink_to(tmp_path / "elsewhere")
    with pytest.raises(SystemExit, match="isn't a folder"):
        helper.open_folders(folders)


def test_a_command_that_runs_too_long_is_stopped_with_everything_it_started(
    h: helper.Opened, monkeypatch: pytest.MonkeyPatch
) -> None:
    pid_file = h.folders.ok3d_dir / "child"
    (h.folders.ok3d_dir / "ok3d").write_text(f"#!/bin/sh\necho started\nsleep 60 &\necho $! > {pid_file}\nsleep 60\n")
    monkeypatch.setitem(helper.TIMEOUTS, "check", 1)
    send(h)
    helper.handle_once(h)
    assert result(h)["exit"] == "124"
    assert "stopped ./ok3d check after 1 seconds" in (h.folders.own / "result").read_text()
    child = int(pid_file.read_text())
    for _ in range(50):
        try:
            os.kill(child, 0)
        except ProcessLookupError:
            break
        time.sleep(0.1)
    else:
        pytest.fail("the command's own child was left running")


def test_a_second_helper_will_not_start(h: helper.Opened) -> None:
    lock = os.open(h.folders.own / "lock", os.O_WRONLY | os.O_CREAT, 0o600)
    fcntl.flock(lock, fcntl.LOCK_EX)
    try:
        with pytest.raises(SystemExit, match="another helper"):
            helper.watch(h.folders)
    finally:
        os.close(lock)


def test_it_wont_start_without_the_ok3d_command(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="no ok3d command"):
        helper.open_folders(helper.Folders.for_data_root(tmp_path, tmp_path / "data"))


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


@given(data=st.binary(max_size=200))
def test_a_refusal_only_ever_repeats_a_valid_id(data: bytes) -> None:
    found = helper.find_id(data)
    assert found is None or helper.ID.fullmatch(found)


def test_it_runs_isolated_with_only_the_standard_library(h: helper.Opened) -> None:
    # The service runs `python3 -I src/ok3d/helper.py`: isolated, so it can't lean on the ok3d
    # package being installed. (This runs the test's own Python, the same way.)
    send(h)
    out = subprocess.run(
        [sys.executable, "-I", helper.__file__, "once", "--ok3d-dir", str(h.folders.ok3d_dir),
         "--data-root", str(h.folders.data_root)],
        capture_output=True, text=True, check=True, cwd="/",
    )
    assert out.stdout.strip() == f"ran ./ok3d check for {ID}: exit 0"
    assert ran(h) == ["check"]
