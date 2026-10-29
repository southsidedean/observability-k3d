"""Tests for the Setup page's settings editor (src/ok3d/dashboard/switches.py): every change
it makes means, to a YAML parser, exactly the switch it was asked to set and nothing else,
and it refuses settings in a shape it can't follow rather than guess.

PyYAML (a test dependency only) is the judge: the Dashboard itself has no YAML library.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
import yaml
from hypothesis import given, settings
from hypothesis import strategies as st

from ok3d.dashboard import switches

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = (ROOT / "settings.example.yaml").read_text()


def with_set(data: dict[str, Any] | None, path: tuple[str, ...], on: bool) -> dict[str, Any]:
    """What the settings should mean once the switch is set."""
    out = copy.deepcopy(data) if data else {}
    here = out
    for key in path[:-1]:
        here = here.setdefault(key, {})
    here[path[-1]] = on
    return out


@pytest.mark.parametrize("switch", switches.SWITCHES.values(), ids=switches.SWITCHES.keys())
@pytest.mark.parametrize("on", [True, False])
def test_each_switch_on_the_example_settings(switch: switches.Switch, on: bool) -> None:
    new = switches.set_flag(EXAMPLE, switch.path, on)
    assert yaml.safe_load(new) == with_set(yaml.safe_load(EXAMPLE), switch.path, on)
    assert switches.flag(new, switch.path) is on
    # Only lines were added: every comment and setting of the example is still there.
    assert EXAMPLE.rstrip("\n") in new or all(line in new.split("\n") for line in EXAMPLE.split("\n"))


def test_a_switch_thats_written_keeps_its_line_and_comment() -> None:
    text = "settingsVersion: 1\nmodules:\n  # UniFi, yes\n  unifi: false   # for now\n  plex: false\n"
    new = switches.set_flag(text, ("modules", "unifi"), True)
    assert new == "settingsVersion: 1\nmodules:\n  # UniFi, yes\n  unifi: true   # for now\n  plex: false\n"


def test_a_missing_switch_goes_after_its_mappings_last_setting_not_after_the_next_comment() -> None:
    text = "alerts:\n    email:\n        to: you@example.com\n\n# The modules.\nmodules:\n  unifi: true\n"
    new = switches.set_flag(text, ("alerts", "ntfy", "enabled"), True)
    assert new == ("alerts:\n    email:\n        to: you@example.com\n    ntfy:\n        enabled: true\n"
                   "\n# The modules.\nmodules:\n  unifi: true\n")  # fmt: skip


def test_an_empty_file_gets_the_switch() -> None:
    assert switches.set_flag("", ("modules", "unifi"), True) == "modules:\n  unifi: true\n"


def test_a_mapping_with_nothing_under_it_gets_the_switch() -> None:
    new = switches.set_flag("modules:\nmetrics:\n  retention: 30d\n", ("modules", "unifi"), True)
    assert yaml.safe_load(new) == {"modules": {"unifi": True}, "metrics": {"retention": "30d"}}


def test_a_value_it_cant_read_is_replaced() -> None:
    new = switches.set_flag("modules:\n  unifi: yes\n", ("modules", "unifi"), False)
    assert new == "modules:\n  unifi: false\n"
    assert switches.flag("modules:\n  unifi: yes\n", ("modules", "unifi")) is None


# Settings in shapes the editor won't follow: it refuses rather than guess where the switch is.
REFUSED = {
    "flow style": "modules: {unifi: true}\n",
    "an anchor": "modules: &m\n  unifi: false\n",
    "a merge key": "x: &x\n  unifi: true\nmodules:\n  <<: *x\n",
    "a key twice": "modules:\n  unifi: false\nmodules:\n  unifi: true\n",
    "a switch twice": "modules:\n  unifi: false\n  unifi: true\n",
    "tabs": "modules:\n\tunifi: false\n",
    "a quoted key": 'modules:\n  "unifi": false\n',
    "a quoted parent": '"modules":\n  unifi: false\n',
    "a list in place of a mapping": "modules:\n  - unifi\n",
    "a block scalar": "modules: |\n  unifi: false\n",
    "a document marker": "---\nmodules:\n  unifi: false\n",
    "uneven indenting": "modules:\n    plex: false\n  unifi: false\n",
    "the switch as a mapping": "modules:\n  unifi:\n    on: true\n",
    "a value that runs onto the next line": "modules:\n  unifi: false\n    true\n",
}


@pytest.mark.parametrize("text", REFUSED.values(), ids=REFUSED.keys())
def test_shapes_it_cant_follow_are_refused(text: str) -> None:
    with pytest.raises(switches.CantEdit):
        switches.set_flag(text, ("modules", "unifi"), True)
    assert switches.flag(text, ("modules", "unifi")) in (None, False)


def test_reading_values() -> None:
    text = 'tls:\n  domain: "noc.example.org"  # mine\ncluster:\n  ports:\n    https: 9443\nunifi:\n  url: \'\'\n'
    assert switches.read(text, ("tls", "domain")) == "noc.example.org"
    assert switches.read(text, ("cluster", "ports", "https")) == "9443"
    assert switches.read(text, ("unifi", "url")) == ""
    assert switches.read(text, ("unifi", "verifyTls")) is None
    assert switches.read(None, ("tls", "domain")) is None
    assert switches.read("tls: {domain: x}\n", ("tls", "domain")) is None


def test_a_switch_thats_not_written_is_off() -> None:
    assert switches.flag("settingsVersion: 1\n", ("alerts", "ntfy", "enabled")) is False
    assert switches.flag(None, ("modules", "unifi")) is False


# Settings files as a person might write them: nested mappings, comments, blank lines, and
# indents of two or four spaces.
NAMES = st.sampled_from(["modules", "alerts", "ntfy", "email", "unifi", "plex", "enabled", "metrics", "to", "x"])
VALUES = st.one_of(st.booleans(), st.integers(0, 99), st.sampled_from(["30d", "a b", "https://192.168.1.1"]))
TREES = st.recursive(VALUES, lambda inner: st.dictionaries(NAMES, inner, min_size=1, max_size=4), max_leaves=12)


def dump(tree: dict[str, Any], indent: int, comments: list[bool]) -> str:
    text = yaml.safe_dump(tree, default_flow_style=False, indent=indent, sort_keys=False)
    out = []
    for line, comment in zip(text.splitlines(), comments + [False] * len(text), strict=False):
        if comment:
            out.append(" " * (len(line) - len(line.lstrip())) + "# a note")
            out.append("")
        out.append(line)
    return "\n".join(out) + "\n"


@settings(max_examples=300, deadline=None)
@given(
    tree=st.dictionaries(NAMES, TREES, min_size=0, max_size=4),
    indent=st.sampled_from([2, 4]),
    comments=st.lists(st.booleans(), max_size=30),
    switch=st.sampled_from(list(switches.SWITCHES.values())),
    on=st.booleans(),
)
def test_any_change_means_exactly_the_switch(tree: dict[str, Any], indent: int, comments: list[bool],
                                              switch: switches.Switch, on: bool) -> None:  # fmt: skip
    text = dump(tree, indent, comments) if tree else ""
    try:
        new = switches.set_flag(text, switch.path, on)
    except switches.CantEdit:
        return  # a value where a mapping should be, say: refused, which is safe
    assert yaml.safe_load(new) == with_set(yaml.safe_load(text), switch.path, on)
    assert switches.flag(new, switch.path) is on


@settings(max_examples=300, deadline=None)
@given(text=st.text(alphabet=" \t\n#:-abcdefgmnu{}[]&*|'\"", max_size=80), on=st.booleans())
def test_whatever_it_writes_means_the_switch(text: str, on: bool) -> None:
    # Odd text: either refused, or the result parses to the original with the switch set.
    try:
        before = yaml.safe_load(text)
    except yaml.YAMLError:
        before = "unparseable"
    try:
        new = switches.set_flag(text, ("modules", "unifi"), on)
    except switches.CantEdit:
        return
    if before == "unparseable" or not isinstance(before, (dict, type(None))):
        # The file was broken before; ./ok3d validate refuses it when it's saved.
        return
    if isinstance(before, dict) and not isinstance(before.get("modules", {}), (dict, type(None))):
        return
    assert yaml.safe_load(new) == with_set(before, ("modules", "unifi"), on)


def test_cards_change_only_switches_the_dashboard_may_change() -> None:
    for card in switches.CARDS:
        for setting in card.changes():
            assert not switches.SWITCHES[setting].host_only
            assert switches.SWITCHES[setting].available
        assert card.on <= switches.SWITCHES.keys()


def test_what_comes_later_isnt_offered_yet() -> None:
    assert switches.release() == (0, 5)
    assert [c.id for c in switches.CARDS if c.available] == ["basic", "network"]
    assert [s.setting for s in switches.MODULES if s.available and not s.host_only] == ["modules.unifi"]
