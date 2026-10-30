"""Tests for src/ok3d/maintenance.py: maintenance windows as Alertmanager silences."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from ok3d import helper, maintenance

ROOT = Path(__file__).resolve().parent.parent
NOW = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def server_time(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """The server's own time zone, fixed for the tests: an hour ahead of UTC in winter."""
    monkeypatch.setenv("TZ", "Europe/Paris")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


@pytest.fixture
def devices(tmp_path: Path) -> Path:
    path = tmp_path / "devices.yaml"
    path.write_text("devices:\n  - name: router  # the one by the door\n    address: 192.168.1.1\n  - name: nas\n"
                    "    address: 192.168.1.20\n")
    return path


def test_all_of_ok3d_leaves_the_dead_mans_switch_alone(devices: Path) -> None:
    args = maintenance.add("all", "2h", "Router firmware update", devices, NOW)
    assert args == ['alertname=~".+"', "alertname!=Watchdog", "--start=2026-11-01T12:00:00Z",
                    "--end=2026-11-01T14:00:00Z", "--author=ok3d", "--comment=ok3d: Router firmware update"]  # fmt: skip


def test_devices_are_matched_by_name(devices: Path) -> None:
    args = maintenance.add("router,nas", "30m", "", devices, NOW)
    assert args[0] == 'device=~"nas|router"' and args[-1] == "--comment=ok3d"


def test_a_device_not_in_devices_yaml_is_refused(devices: Path) -> None:
    with pytest.raises(maintenance.Refused, match=r"Not in devices\.yaml: printer"):
        maintenance.add("router,printer", "1h", "", devices, NOW)


def test_start_and_end_are_the_servers_own_time(devices: Path) -> None:
    args = maintenance.add("all", "2026-11-03T02:00/2026-11-03T04:00", "", devices, NOW)
    assert "--start=2026-11-03T01:00:00Z" in args and "--end=2026-11-03T03:00:00Z" in args


def test_a_window_already_started_starts_now(devices: Path) -> None:
    args = maintenance.add("all", "2026-11-01T10:00/2026-11-01T15:00", "", devices, NOW)
    assert "--start=2026-11-01T12:00:00Z" in args and "--end=2026-11-01T14:00:00Z" in args


@pytest.mark.parametrize(("what", "when", "reason", "says"), [
    ("Router", "2h", "", "What is all"),
    ("all", "2 hours", "", "When is a length"),
    ("all", "0h", "", "When is a length"),
    ("all", "31d", "", "at most 30 days"),
    ("all", "2026-11-03T04:00/2026-11-03T02:00", "", "ends before it starts"),
    ("all", "2026-11-01T08:00/2026-11-01T09:00", "", "already ended"),
    ("all", "2028-01-01T00:00/2028-01-01T01:00", "", "a year from now"),
    ("all", "2026-02-30T00:00/2026-03-01T01:00", "", "can read"),
    ("all", "2h", "a;b", "The reason"),
    ("all", "2h", "-x", "The reason"),
    ("all", "2h", "x" * 101, "The reason"),
])  # fmt: skip
def test_a_window_that_cant_be_set_says_why(devices: Path, what: str, when: str, reason: str, says: str) -> None:
    with pytest.raises(maintenance.Refused, match=says):
        maintenance.add(what, when, reason, devices, NOW)


def silence(**changes: object) -> dict[str, object]:
    """A silence as amtool silence query -o json shows it."""
    base: dict[str, object] = {
        "id": "54c2bf37-5a0a-45d7-91a0-30e0c9b716b6", "status": {"state": "pending"}, "comment": "ok3d: router firmware",
        "createdBy": "ok3d", "startsAt": "2026-11-03T01:00:00.000Z", "endsAt": "2026-11-03T03:00:00.000Z",
        "matchers": [{"isEqual": True, "isRegex": True, "name": "alertname", "value": ".+"},
                     {"isEqual": False, "isRegex": False, "name": "alertname", "value": "Watchdog"}],
    }  # fmt: skip
    return base | changes


def test_ok3ds_windows_are_listed_in_both_times() -> None:
    lines = maintenance.windows([silence()], NOW)
    assert lines == ["window=54c2bf37-5a0a-45d7-91a0-30e0c9b716b6;all;2026-11-03T01:00:00Z;2026-11-03T03:00:00Z;"
                     "2026-11-03 02:00 CET;2026-11-03 04:00 CET;router firmware"]  # fmt: skip


def test_a_device_window_is_listed_with_its_devices() -> None:
    lines = maintenance.windows([silence(matchers=[{"isEqual": True, "isRegex": True, "name": "device", "value": "nas|router"}])], NOW)
    assert lines[0].split(";")[1] == "nas,router"


@pytest.mark.parametrize("other", [
    silence(createdBy="someone"),
    silence(endsAt="2026-11-01T11:00:00Z"),
    silence(matchers=[{"isEqual": True, "isRegex": False, "name": "severity", "value": "warning"}]),
    silence(id="not-an-id"),
    silence(matchers=[{"isEqual": True, "isRegex": True, "name": "device", "value": ".*"}]),
    "not a silence",
])  # fmt: skip
def test_only_ok3ds_windows_that_havent_ended_are_listed(other: object) -> None:
    assert maintenance.windows([other], NOW) == []


def test_a_reason_that_isnt_plain_text_is_left_out() -> None:
    assert maintenance.windows([silence(comment="ok3d: a;b")], NOW)[0].endswith(";")


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, "-I", str(ROOT / "src" / "ok3d" / "maintenance.py"), *args],
                          capture_output=True, text=True, check=False)  # fmt: skip


def test_it_runs_isolated(tmp_path: Path, devices: Path) -> None:
    (tmp_path / "none.json").write_text("[]")
    added = run("add", "all", "1h", "", str(devices), str(tmp_path / "none.json"))
    assert added.returncode == 0 and added.stdout.splitlines()[:2] == ['alertname=~".+"', "alertname!=Watchdog"]
    refused = run("add", "router;reboot", "1h", "", str(devices), str(tmp_path / "none.json"))
    assert refused.returncode == 2 and "What is all" in refused.stderr
    later = (datetime.now(UTC) + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    (tmp_path / "silences.json").write_text(json.dumps([silence(endsAt=later)]))
    listed = run("list", str(tmp_path / "silences.json"))
    assert listed.returncode == 0 and listed.stdout.startswith("window=54c2bf37")
    (tmp_path / "note").write_text(listed.stdout)
    assert "all of ok3d  (router firmware)" in run("table", str(tmp_path / "note")).stdout


def test_the_helper_checks_a_window_the_same_way() -> None:
    assert helper.MAINTENANCE_PATTERNS["what"].pattern == maintenance.WHAT.pattern
    assert helper.MAINTENANCE_PATTERNS["reason"].pattern == maintenance.REASON.pattern
    assert helper.MAINTENANCE_PATTERNS["window"].pattern == maintenance.SILENCE_ID.pattern
    assert helper.MAINTENANCE_PATTERNS["when"].pattern == f"{maintenance.LENGTH.pattern.replace('(', '').replace(')', '')}|{maintenance.RANGE.pattern.replace('(', '').replace(')', '')}"


def test_a_window_without_a_reason_is_listed_without_one() -> None:
    assert maintenance.windows([silence(comment="ok3d")], NOW)[0].endswith(";")


def test_a_window_across_the_clocks_going_back_has_the_right_length(devices: Path) -> None:
    # Paris goes from summer time (UTC+2) to winter time (UTC+1) at 03:00 on 2027-10-31.
    args = maintenance.add("all", "2027-10-31T01:00/2027-10-31T04:00", "", devices, datetime(2027, 10, 1, tzinfo=UTC))
    assert "--start=2027-10-30T23:00:00Z" in args and "--end=2027-10-31T03:00:00Z" in args


def test_at_most_twenty_windows_at_once(devices: Path) -> None:
    taken = [silence(id=f"54c2bf37-5a0a-45d7-91a0-30e0c9b716{n:02d}") for n in range(maintenance.MOST)]
    with pytest.raises(maintenance.Refused, match="20 maintenance windows already"):
        maintenance.add("all", "1h", "", devices, NOW, taken)
    assert maintenance.add("all", "1h", "", devices, NOW, taken[1:])  # one fewer is fine


def test_ending_takes_only_ok3ds_own_windows(tmp_path: Path) -> None:
    later = (datetime.now(UTC) + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    (tmp_path / "s.json").write_text(json.dumps([silence(endsAt=later), silence(id="0" * 8 + "-0000-0000-0000-" + "0" * 12,
                                                                                createdBy="you", endsAt=later)]))  # fmt: skip
    assert run("ours", "54c2bf37-5a0a-45d7-91a0-30e0c9b716b6", str(tmp_path / "s.json")).returncode == 0
    assert run("ours", "00000000-0000-0000-0000-000000000000", str(tmp_path / "s.json")).returncode == 2
    assert run("ours", "--all", str(tmp_path / "s.json")).returncode == 2
