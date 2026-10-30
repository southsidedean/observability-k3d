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
    command.write_text(
        '#!/bin/sh\necho "$@" >> "$(dirname "$0")/ran"\n'
        'env | grep "^OK3D_" >> "$(dirname "$0")/env" || true\n'
        'if [ "$1" = validate ]; then\n'
        '  if grep -q bad "$3"; then echo "FAIL  the $2 in $3"; exit 1; fi\n'
        '  echo "PASS  the $2 in $3"; exit 0\n'
        'fi\n'
        'echo "checked: $1"\n'
    )
    command.chmod(0o755)
    return ok3d_dir


@pytest.fixture(autouse=True)
def systemd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Stand-ins for systemctl and systemd-run, so no test asks the machine's own systemd. An
    upgrade counts as running while the folder's "upgrading" file is there; systemd-run
    records its arguments in "started", and fails when there's a "fail-start" file."""
    fake = tmp_path / "systemd"
    fake.mkdir()
    for name, body in {
        "systemctl": f'[ -e "{fake}/upgrading" ]',
        "systemd-run": f'[ ! -e "{fake}/fail-start" ] || {{ echo "Unit ok3d-upgrade.service was already loaded"; exit 1; }}\n'
                       f'printf "%s\\n" "$@" >"{fake}/started"',
    }.items():  # fmt: skip
        (fake / name).write_text(f"#!/bin/sh\n{body}\n")
        (fake / name).chmod(0o755)
    monkeypatch.setattr(helper, "SYSTEMCTL", str(fake / "systemctl"))
    monkeypatch.setattr(helper, "SYSTEMD_RUN", str(fake / "systemd-run"))
    return fake


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
    assert helper.handle_once(h) == f"couldn't carry out ./ok3d check for {ID}"
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
        (f"id={ID}\n\naction=check\n", "the request is missing a line"),
        (f"id={ID}\r\naction=check\r\n", "the request's id isn't valid"),
        (f" id={ID}\naction=check\n", "the request has a line the helper doesn't know"),
        (f"id={ID}\naction=check\n" + "#" * 70000 + "\n", "the request is too big"),
        (f"id={ID}\naction=check\n\nextra", "the request has something after it"),
        (f"id={ID}\naction=check\nname=NTFY_TOPIC\n", "the request has a line the helper doesn't know"),
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
    if request.action in ("check", "apply"):
        assert data in (f"id={request.id}\naction={request.action}\n".encode(),
                        f"action={request.action}\nid={request.id}\n".encode())  # fmt: skip
        assert request.body == b""
    if request.action == "set-env":
        assert request.name in helper.ENV_NAMES
        assert helper.ENV_VALUE.fullmatch(request.body.decode())


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


# Saving settings and devices, and setting secrets.

SETTINGS = "settingsVersion: 1\nhost:\n  dataRoot: /srv/ok3d\n"


def ask(h: helper.Opened, head: str, body: str | bytes) -> str | None:
    data = body.encode() if isinstance(body, str) else body
    send(h, head.encode() + b"\n" + data)
    return helper.handle_once(h)


def test_a_valid_settings_file_is_checked_then_saved(h: helper.Opened) -> None:
    (h.folders.ok3d_dir / "settings.yaml").write_text("settingsVersion: 1\n")
    assert ask(h, f"id={ID}\naction=save-settings\n", SETTINGS) == f"ran save-settings for {ID}: exit 0"
    saved = h.folders.ok3d_dir / "settings.yaml"
    assert saved.read_text() == SETTINGS
    assert stat.S_IMODE(saved.stat().st_mode) == 0o600
    assert ran(h)[0].startswith("validate settings ")
    assert "Saved settings.yaml." in (h.folders.own / "result").read_text()
    # The old one is kept, where the Dashboard can't see it.
    [backup] = (h.folders.ok3d_dir / "local" / "backups").glob("settings.yaml.*")
    assert backup.read_text() == "settingsVersion: 1\n"
    assert not list(os.listdir(h.folders.own / "taken"))
    assert not (h.folders.own / "staged-settings.yaml").exists()


def test_a_settings_file_that_fails_the_check_isnt_saved(h: helper.Opened) -> None:
    (h.folders.ok3d_dir / "settings.yaml").write_text("settingsVersion: 1\n")
    ask(h, f"id={ID}\naction=save-settings\n", "settingsVersion: bad\n")
    assert (h.folders.ok3d_dir / "settings.yaml").read_text() == "settingsVersion: 1\n"
    answer = result(h)
    assert answer["exit"] == "1"
    assert "Not saved: your settings.yaml is unchanged." in (h.folders.own / "result").read_text()
    assert not (h.folders.ok3d_dir / "local").exists()


def test_devices_are_saved_the_same_way(h: helper.Opened) -> None:
    ask(h, f"id={ID}\naction=save-devices\n", "devices: []\n")
    assert (h.folders.ok3d_dir / "devices.yaml").read_text() == "devices: []\n"
    assert ran(h)[0].startswith("validate devices ")


def test_only_the_last_backups_are_kept(h: helper.Opened) -> None:
    for n in range(helper.BACKUPS + 3):
        ask(h, f"id={n:016x}\naction=save-devices\n", f"devices: []  # {n}\n")
    backups = list((h.folders.ok3d_dir / "local" / "backups").glob("devices.yaml.*"))
    assert len(backups) == helper.BACKUPS


@pytest.mark.parametrize(
    ("body", "reason"),
    [
        (b"", "the file is empty"),
        (b"x" * (helper.MAX_FILE + 1), "the file is too big"),
        (b"devices: []\x00\n", "the file has control characters"),
        (b"devices: []\r\n", "the file has control characters"),
        (b"devices: []\x1b[31m\n", "the file has control characters"),
        ("devices: [] # caf\u00e9\n".encode("latin-1"), "the file isn't UTF-8 text"),
    ],
    ids=["empty", "too-big", "nul", "carriage-return", "escape", "latin-1"],
)
def test_a_bad_file_is_refused_before_anything_runs(h: helper.Opened, body: bytes, reason: str) -> None:
    assert ask(h, f"id={ID}\naction=save-devices\n", body) == f"refused a request: {reason}"
    assert ran(h) == []
    assert not (h.folders.ok3d_dir / "devices.yaml").exists()


def test_a_save_needs_its_file(h: helper.Opened) -> None:
    send(h, f"id={ID}\naction=save-settings\n")
    assert helper.handle_once(h) == "refused a request: the request isn't finished"


def test_a_value_is_set_in_dotenv_and_never_answered_back(h: helper.Opened) -> None:
    env = h.folders.ok3d_dir / ".env"
    env.write_text("# my notes\nNTFY_TOPIC=old\nSMTP_PASSWORD=keep\nNTFY_TOPIC=older\n")
    value = "ok3d-7f3k9q2m8x"
    assert ask(h, f"id={ID}\naction=set-env\nname=NTFY_TOPIC\n", value) == f"ran set-env for {ID}: exit 0"
    assert env.read_text() == f"# my notes\nNTFY_TOPIC={value}\nSMTP_PASSWORD=keep\n"
    assert stat.S_IMODE(env.stat().st_mode) == 0o600
    for name in ("result", "output", "seen"):
        path = h.folders.own / name
        assert not path.exists() or value not in path.read_text(), name
    assert result(h)["name"] == "NTFY_TOPIC"
    assert ran(h) == []
    [backup] = (h.folders.ok3d_dir / "local" / "backups").glob(".env.*")
    assert stat.S_IMODE(backup.stat().st_mode) == 0o600
    assert stat.S_IMODE((h.folders.ok3d_dir / "local" / "backups").stat().st_mode) == 0o700


def test_a_value_is_added_when_dotenv_has_none(h: helper.Opened) -> None:
    ask(h, f"id={ID}\naction=set-env\nname=UNIFI_API_KEY\n", "abc123\n")
    assert (h.folders.ok3d_dir / ".env").read_text() == "UNIFI_API_KEY=abc123\n"


def test_an_empty_value_clears_a_line(h: helper.Opened) -> None:
    (h.folders.ok3d_dir / ".env").write_text("NTFY_TOKEN=abc\n")
    ask(h, f"id={ID}\naction=set-env\nname=NTFY_TOKEN\n", "")
    assert (h.folders.ok3d_dir / ".env").read_text() == "NTFY_TOKEN=\n"


@pytest.mark.parametrize(
    ("head", "value", "reason"),
    [
        (f"id={ID}\naction=set-env\nname=PATH\n", "x", "the request names a .env line the helper doesn't set"),
        (f"id={ID}\naction=set-env\nname=ntfy_topic\n", "x", "the request names a .env line the helper doesn't set"),
        (f"id={ID}\naction=set-env\n", "x", "the request is missing a line"),
        (f"id={ID}\naction=set-env\nname=NTFY_TOPIC\n", "two\nlines", "the value has characters .env can't hold safely"),
        (f"id={ID}\naction=set-env\nname=NTFY_TOPIC\n", "a b", "the value has characters .env can't hold safely"),
        (f"id={ID}\naction=set-env\nname=NTFY_TOPIC\n", "$(reboot)", "the value has characters .env can't hold safely"),
        (f"id={ID}\naction=set-env\nname=NTFY_TOPIC\n", "'quoted'", "the value has characters .env can't hold safely"),
        (f"id={ID}\naction=set-env\nname=NTFY_TOPIC\n", "back\\slash", "the value has characters .env can't hold safely"),
        (f"id={ID}\naction=set-env\nname=NTFY_TOPIC\n", "caf\u00e9", "the value has characters .env can't hold safely"),
        (f"id={ID}\naction=set-env\nname=NTFY_TOPIC\n", "x" * 1025, "the value has characters .env can't hold safely"),
    ],
)
def test_a_bad_value_is_refused_and_dotenv_is_untouched(h: helper.Opened, head: str, value: str, reason: str) -> None:
    env = h.folders.ok3d_dir / ".env"
    env.write_text("NTFY_TOPIC=keep\n")
    assert ask(h, head, value) == f"refused a request: {reason}"
    assert env.read_text() == "NTFY_TOPIC=keep\n"
    assert value not in (h.folders.own / "result").read_text() or value == "x"


def test_a_dotenv_that_is_a_link_is_left_alone(h: helper.Opened, tmp_path: Path) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.write_text("NTFY_TOPIC=keep\n")
    (h.folders.ok3d_dir / ".env").symlink_to(elsewhere)
    ask(h, f"id={ID}\naction=set-env\nname=NTFY_TOPIC\n", "new")
    assert result(h)["state"] == "failed"
    assert elsewhere.read_text() == "NTFY_TOPIC=keep\n"


def test_an_id_in_the_body_is_never_taken_for_the_requests(h: helper.Opened) -> None:
    send(h, b"action=save-devices\n\nid=" + ID.encode() + b"\n")
    helper.handle_once(h)
    assert "id" not in result(h)



def test_settings_from_the_dashboard_keep_the_settings_only_you_may_change(h: helper.Opened) -> None:
    ask(h, f"id={ID}\naction=save-settings\n", SETTINGS)
    assert ran(h)[0].endswith(" --from-dashboard")


def test_devices_dont_get_the_settings_option(h: helper.Opened) -> None:
    ask(h, f"id={ID}\naction=save-devices\n", "devices: []\n")
    assert not ran(h)[0].endswith(" --from-dashboard")


def test_ok3d_runs_without_the_helpers_own_ok3d_settings(h: helper.Opened, monkeypatch: pytest.MonkeyPatch) -> None:
    # Otherwise ./ok3d validate could check one file while the helper writes another.
    monkeypatch.setenv("OK3D_SETTINGS", "/elsewhere/settings.yaml")
    monkeypatch.setenv("OK3D_DEVICES", "/elsewhere/devices.yaml")
    ask(h, f"id={ID}\naction=save-devices\n", "devices: []\n")
    send(h, f"id={'1' * 16}\naction=check\n")
    helper.handle_once(h)
    assert len(ran(h)) == 2
    env = h.folders.ok3d_dir / "env"
    assert not env.exists() or env.read_text() == ""


@pytest.mark.parametrize(
    ("before", "after"),
    [
        (b"SMTP_PASSWORD=p\xe4ss\nNTFY_TOPIC=old\n", b"SMTP_PASSWORD=p\xe4ss\nNTFY_TOPIC=new\n"),
        (b"UNIFI_API_KEY=a\x0cb\nNTFY_TOPIC=old\n", b"UNIFI_API_KEY=a\x0cb\nNTFY_TOPIC=new\n"),
        (b"NTFY_TOKEN=keep\r\nNTFY_TOPIC=old\r\n", b"NTFY_TOKEN=keep\r\nNTFY_TOPIC=new\n"),
        (b"NTFY_TOKEN=keep", b"NTFY_TOKEN=keep\nNTFY_TOPIC=new\n"),
        (b"NTFY_TOPICS=other\nNTFY_TOPIC=old\n", b"NTFY_TOPICS=other\nNTFY_TOPIC=new\n"),
        (b"# NTFY_TOPIC=commented\n", b"# NTFY_TOPIC=commented\nNTFY_TOPIC=new\n"),
        (b"", b"NTFY_TOPIC=new\n"),
    ],
    ids=["latin-1", "form-feed", "crlf", "no-final-newline", "longer-name", "comment", "empty"],
)
def test_setting_a_value_leaves_every_other_byte_of_dotenv_alone(h: helper.Opened, before: bytes, after: bytes) -> None:
    env = h.folders.ok3d_dir / ".env"
    env.write_bytes(before)
    ask(h, f"id={ID}\naction=set-env\nname=NTFY_TOPIC\n", "new")
    assert env.read_bytes() == after


def test_a_settings_file_that_is_a_link_is_left_alone(h: helper.Opened, tmp_path: Path) -> None:
    elsewhere = tmp_path / "elsewhere.yaml"
    elsewhere.write_text("settingsVersion: 1\n")
    (h.folders.ok3d_dir / "settings.yaml").symlink_to(elsewhere)
    ask(h, f"id={ID}\naction=save-settings\n", SETTINGS)
    assert result(h)["state"] == "failed"
    assert elsewhere.read_text() == "settingsVersion: 1\n"


def test_the_log_never_holds_a_value(h: helper.Opened) -> None:
    message = ask(h, f"id={ID}\naction=set-env\nname=NTFY_TOKEN\n", "tk_s3cr3tvalue")
    assert message == f"ran set-env for {ID}: exit 0"



@pytest.mark.parametrize("name", ["OK3D_ADMIN_PASSWORD", "ANTHROPIC_API_KEY", "DEADMAN_URL"])
def test_the_lines_only_you_may_set_are_refused(h: helper.Opened, name: str) -> None:
    # Choosing the admin password would sign someone in to Grafana; a key of theirs would get
    # the agents' conversations; the dead man's switch could point anywhere.
    env = h.folders.ok3d_dir / ".env"
    env.write_text(f"{name}=mine\n")
    assert ask(h, f"id={ID}\naction=set-env\nname={name}\n", "theirs") == (
        "refused a request: the request names a .env line the helper doesn't set"
    )
    assert env.read_text() == f"{name}=mine\n"


# What the helper publishes for the Dashboard.


def test_it_publishes_copies_of_your_settings_and_devices(h: helper.Opened) -> None:
    (h.folders.ok3d_dir / "settings.yaml").write_text(SETTINGS)
    (h.folders.ok3d_dir / "devices.yaml").write_text("devices: []\n")
    helper.publish(h)
    assert (h.folders.own / "current-settings.yaml").read_text() == SETTINGS
    assert (h.folders.own / "current-devices.yaml").read_text() == "devices: []\n"
    assert stat.S_IMODE((h.folders.own / "current-settings.yaml").stat().st_mode) == 0o600
    assert (h.folders.own / "alive").read_text().startswith("20")
    # And forgets one you've removed.
    (h.folders.ok3d_dir / "devices.yaml").unlink()
    helper.publish(h)
    assert not (h.folders.own / "current-devices.yaml").exists()


def test_it_publishes_which_env_lines_are_set_and_never_a_value(h: helper.Opened) -> None:
    (h.folders.ok3d_dir / ".env").write_text(
        "UNIFI_API_KEY=k3y-value\nNTFY_TOPIC=\nNTFY_TOKEN=''\nSMTP_PASSWORD=old\nSMTP_PASSWORD=\n"
        "OK3D_ADMIN_PASSWORD=\"adm1n\"\nOTHER=x\n"
    )
    helper.publish(h)
    published = (h.folders.own / "env-set").read_text()
    assert published.split() == ["OK3D_ADMIN_PASSWORD", "UNIFI_API_KEY"]
    for value in ("k3y-value", "adm1n", "old"):
        for name in os.listdir(h.folders.own):
            path = h.folders.own / name
            assert not path.is_file() or value not in path.read_text(errors="replace"), name


def test_it_wont_publish_through_a_link(h: helper.Opened, tmp_path: Path) -> None:
    secret = tmp_path / "secret.yaml"
    secret.write_text("private: yes\n")
    (h.folders.ok3d_dir / "settings.yaml").symlink_to(secret)
    helper.publish(h)
    assert not (h.folders.own / "current-settings.yaml").exists()


def test_once_publishes_too(h: helper.Opened) -> None:
    (h.folders.ok3d_dir / "settings.yaml").write_text(SETTINGS)
    helper.main(["once", "--ok3d-dir", str(h.folders.ok3d_dir), "--data-root", str(h.folders.data_root)])
    assert (h.folders.own / "current-settings.yaml").exists()


def test_the_heartbeat_goes_on_while_a_long_command_runs(h: helper.Opened, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(helper, "PUBLISH_EVERY", 0.2)
    (h.folders.ok3d_dir / "ok3d").write_text("#!/bin/sh\nsleep 1\n")
    send(h)
    helper.handle_once(h)
    assert (h.folders.own / "alive").exists()


def test_an_answer_left_running_is_marked_failed_when_the_helper_starts(h: helper.Opened) -> None:
    (h.folders.own / "result").write_text(f"id={ID}\naction=apply\nstate=running\n\n")
    helper.clear_unfinished(h)
    answer = result(h)
    assert answer["id"] == ID
    assert answer["state"] == "failed"
    assert answer["reason"] == "the helper stopped while it ran"


def test_a_finished_answer_is_left_alone_at_start(h: helper.Opened) -> None:
    (h.folders.own / "result").write_text(f"id={ID}\naction=check\nstate=finished\nexit=0\n\nReady.\n")
    helper.clear_unfinished(h)
    assert result(h)["state"] == "finished"


def test_a_save_based_on_the_file_as_it_is_goes_ahead(h: helper.Opened) -> None:
    import hashlib

    (h.folders.ok3d_dir / "devices.yaml").write_text("devices: []\n")
    base = hashlib.sha256(b"devices: []\n").hexdigest()
    ask(h, f"id={ID}\naction=save-devices\nbase={base}\n", "devices: [] # new\n")
    assert (h.folders.ok3d_dir / "devices.yaml").read_text() == "devices: [] # new\n"


def test_a_save_based_on_an_older_file_is_refused(h: helper.Opened) -> None:
    import hashlib

    (h.folders.ok3d_dir / "devices.yaml").write_text("devices: [] # changed on the server\n")
    base = hashlib.sha256(b"devices: []\n").hexdigest()
    ask(h, f"id={ID}\naction=save-devices\nbase={base}\n", "devices: [] # from the page\n")
    assert (h.folders.ok3d_dir / "devices.yaml").read_text() == "devices: [] # changed on the server\n"
    assert result(h)["exit"] == "1"
    assert "changed on the server since the page showed it" in (h.folders.own / "result").read_text()
    assert ran(h) == []


def test_base_none_means_there_was_no_file(h: helper.Opened) -> None:
    ask(h, f"id={ID}\naction=save-devices\nbase=none\n", "devices: []\n")
    assert (h.folders.ok3d_dir / "devices.yaml").exists()
    (h.folders.ok3d_dir / "devices.yaml").write_text("devices: [] # since\n")
    ask(h, f"id={'2' * 16}\naction=save-devices\nbase=none\n", "devices: []\n")
    assert (h.folders.ok3d_dir / "devices.yaml").read_text() == "devices: [] # since\n"


@pytest.mark.parametrize("head", [f"id={ID}\naction=save-devices\nbase=xyz\n", f"id={ID}\naction=check\nbase=none\n"])
def test_a_bad_base_is_refused(h: helper.Opened, head: str) -> None:
    body = "devices: []\n" if "save" in head else None
    if body is None:
        send(h, head)
        helper.handle_once(h)
    else:
        ask(h, head, body)
    assert result(h)["state"] == "refused"
    assert ran(h) == []


def test_env_lines_are_read_as_ok3d_reads_them(h: helper.Opened) -> None:
    (h.folders.ok3d_dir / ".env").write_text("NTFY_TOKEN= \nNTFY_TOPIC=\"\"\nSMTP_PASSWORD='x'\n")
    helper.publish(h)
    assert (h.folders.own / "env-set").read_text().split() == ["NTFY_TOKEN", "SMTP_PASSWORD"]


UPGRADE = f"id={ID}\naction=upgrade\nversion=v0.5.1\n"


def test_look_for_release_runs_ok3d_upgrade(h: helper.Opened) -> None:
    send(h, f"id={ID}\naction=look-for-release\n")
    assert helper.handle_once(h) == f"ran ./ok3d upgrade for {ID}: exit 0"
    assert ran(h) == ["upgrade"]


def test_an_upgrade_starts_in_a_service_of_its_own(h: helper.Opened, systemd: Path) -> None:
    send(h, UPGRADE)
    assert helper.handle_once(h) == f"ran ./ok3d upgrade v0.5.1 for {ID}: exit 0"
    started = (systemd / "started").read_text().splitlines()
    assert started[:4] == ["--user", "--unit=ok3d-upgrade", "--collect", "--quiet"]
    assert started[-4:] == [str(h.folders.ok3d_dir / "ok3d"), "upgrade", "v0.5.1", "--yes"]
    assert f"--working-directory={h.folders.ok3d_dir}" in started
    assert ran(h) == []  # not run under the helper, whose service the new release restarts
    assert {"action": "upgrade", "state": "finished", "exit": "0"}.items() <= result(h).items()
    assert "Started the upgrade to v0.5.1" in (h.folders.own / "result").read_text()


def test_an_upgrade_that_cant_start_says_so(h: helper.Opened, systemd: Path) -> None:
    (systemd / "fail-start").touch()
    send(h, UPGRADE)
    helper.handle_once(h)
    assert result(h)["exit"] == "1"
    assert "The upgrade didn't start." in (h.folders.own / "result").read_text()


@pytest.mark.parametrize("version", ["0.5.1", "v0.5", "v0.5.1.1", "v0.5.1 ", "v0.5.1;reboot", "--help",
                                     "v1234567.0.0", ""])  # fmt: skip
def test_an_upgrade_takes_only_a_release(h: helper.Opened, version: str, systemd: Path) -> None:
    send(h, f"id={ID}\naction=upgrade\nversion={version}\n")
    assert helper.handle_once(h) == "refused a request: the request's version isn't a release"
    assert not (systemd / "started").exists()


@pytest.mark.parametrize("text", [f"id={ID}\naction=upgrade\n", f"id={ID}\naction=check\nversion=v0.5.1\n"])
def test_version_goes_with_upgrade_and_nothing_else(h: helper.Opened, text: str, systemd: Path) -> None:
    send(h, text)
    assert (helper.handle_once(h) or "").startswith("refused a request")
    assert ran(h) == [] and not (systemd / "started").exists()


@pytest.mark.parametrize("text", [GOOD, f"id={ID}\naction=apply\n", UPGRADE, f"id={ID}\naction=look-for-release\n"])
def test_nothing_else_runs_while_an_upgrade_does(h: helper.Opened, text: str, systemd: Path) -> None:
    (systemd / "upgrading").touch()
    send(h, text)
    assert helper.handle_once(h) == f"refused a request: {helper.UPGRADE_RUNNING}"
    assert ran(h) == [] and not (systemd / "started").exists()


def test_an_upgrade_from_a_terminal_counts_too(h: helper.Opened) -> None:
    # ./ok3d upgrade holds a lock on local/upgrading while it runs, here held by the test.
    (h.folders.ok3d_dir / "local").mkdir()
    lock = h.folders.ok3d_dir / "local" / "upgrading"
    with lock.open("w") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        send(h)
        assert helper.handle_once(h) == f"refused a request: {helper.UPGRADE_RUNNING}"
    # Let go of (as when the upgrade ends, however it ends), the file left behind counts for nothing.
    send(h, GOOD.replace(ID, "4" * 16))
    assert helper.handle_once(h) == f"ran ./ok3d check for {'4' * 16}: exit 0"


def test_an_upgrade_that_stopped_partway_is_marked_stopped(h: helper.Opened, systemd: Path) -> None:
    (h.folders.own / "upgrade").write_text("from=0.5.1\nto=v0.5.2\nstate=running\nstep=Deleting the cluster\n")
    (systemd / "upgrading").touch()
    helper.publish(h)
    assert "state=running" in (h.folders.own / "upgrade").read_text()  # still running: left alone
    (systemd / "upgrading").unlink()
    helper.publish(h)
    text = (h.folders.own / "upgrade").read_text()
    assert "state=failed" in text and "to=v0.5.2" in text and "stopped partway, at Deleting the cluster" in text


def test_an_upgrade_that_finishes_while_its_checked_isnt_marked_stopped(h: helper.Opened, monkeypatch: pytest.MonkeyPatch) -> None:
    # The upgrade finishes just as the helper asks whether one is running: it writes its last
    # state, then ends. The helper must not mark that finished upgrade as stopped.
    upgrade = h.folders.own / "upgrade"
    upgrade.write_text("from=0.5.1\nto=v0.5.2\nstate=running\nstep=Making the cluster again\n")

    def finishes_meanwhile(_ok3d_dir: Path) -> bool:
        upgrade.write_text("from=0.5.1\nto=v0.5.2\nstate=finished\nstep=done\n")
        return False

    monkeypatch.setattr(helper, "upgrading", finishes_meanwhile)
    helper.clear_stopped_upgrade(h)
    assert "state=finished" in upgrade.read_text()


def test_an_upgrade_that_starts_while_its_checked_isnt_marked_stopped(h: helper.Opened, monkeypatch: pytest.MonkeyPatch) -> None:
    # None is running when the helper first asks; a terminal upgrade then takes the lock and
    # writes its first state before the helper reads the file. Asked again, it's running.
    upgrade = h.folders.own / "upgrade"
    upgrade.write_text("from=0.5.1\nto=v0.5.2\nstate=running\nstep=Getting v0.5.2\n")
    answers = iter([False, True])
    monkeypatch.setattr(helper, "upgrading", lambda _ok3d_dir: next(answers))
    helper.clear_stopped_upgrade(h)
    assert "state=running" in upgrade.read_text()


def test_a_request_says_its_running_before_it_asks_about_an_upgrade(h: helper.Opened, monkeypatch: pytest.MonkeyPatch) -> None:
    # ./ok3d upgrade takes its lock, then reads the answer: had it taken it just as the helper
    # asked, it must find this request running, and wait for it.
    seen: list[dict[str, str]] = []

    def asked(_ok3d_dir: Path) -> bool:
        seen.append(result(h))  # the answer as an upgrade taking its lock just then would read it
        return False

    monkeypatch.setattr(helper, "upgrading", asked)
    send(h, f"id={ID}\naction=apply\n")
    helper.handle_once(h)
    assert seen and {"action": "apply", "state": "running"}.items() <= seen[0].items()
