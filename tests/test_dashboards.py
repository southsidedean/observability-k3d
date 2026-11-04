"""Tests for Grafana's dashboards in chart/ok3d/dashboards/: ok3d's own, and the UniFi ones
vendored from unpoller's, with ok3d's changes made in place. These read the files alone, so
they run without Helm."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

DASHBOARDS = sorted((Path(__file__).resolve().parent.parent / "chart" / "ok3d" / "dashboards").glob("*.json"))

# The panel types Grafana itself ships. graph, singlestat, and table-old are its old Angular
# panels, which it turns into timeseries, stat, and table as it loads them. Any other type is
# a plugin, which ok3d's Grafana doesn't install, so the panel would say "plugin not found".
CORE = {"row", "text", "stat", "gauge", "bargauge", "timeseries", "table", "piechart", "heatmap",
        "graph", "singlestat", "table-old"}  # fmt: skip
# The old pie chart plugin's own settings. Grafana's core pie chart ignores them, and moves
# them over only for a panel whose type is still the plugin's.
OLD_PIE = {"pieType", "legendType", "breakPoint", "combine", "valueName", "strokeWidth", "fontSize"}


def panels(within: list[dict[str, Any]]) -> Iterator[dict[str, Any]]:
    for panel in within:
        yield panel
        yield from panels(panel.get("panels", []))


def every_panel() -> list[tuple[str, dict[str, Any]]]:
    return [(path.name, panel) for path in DASHBOARDS for panel in panels(json.loads(path.read_text())["panels"])]


def test_there_are_dashboards() -> None:
    assert len(DASHBOARDS) == 6


@pytest.mark.parametrize(("name", "panel"), every_panel(), ids=lambda v: v if isinstance(v, str) else str(v.get("id")))
def test_every_panel_says_what_it_shows(name: str, panel: dict[str, Any]) -> None:
    # CLAUDE.md: each panel says what it shows, in the description Grafana shows on hover.
    if panel.get("type") != "row":
        assert str(panel.get("description", "")).strip(), f"{name}: panel {panel.get('id')} {panel.get('title')!r}"


def test_every_panel_is_one_grafana_has() -> None:
    plugins = [(name, panel.get("title"), panel.get("type"))
               for name, panel in every_panel() if panel.get("type") not in CORE]  # fmt: skip
    assert not plugins


def test_no_dashboard_asks_for_a_plugin() -> None:
    for path in DASHBOARDS:
        wanted = json.loads(path.read_text()).get("__requires", [])
        assert not [r["id"] for r in wanted if r.get("type") == "panel" and r.get("id") not in CORE], path.name


def test_pie_charts_use_the_core_pie_charts_settings() -> None:
    for name, panel in every_panel():
        if panel.get("type") == "piechart":
            assert not OLD_PIE & set(panel), f"{name}: {panel.get('title')!r} still has the old plugin's settings"
            assert panel.get("options", {}).get("pieType") in ("pie", "donut"), f"{name}: {panel.get('title')!r}"


def test_links_go_to_unpollers_own_site() -> None:
    # unpoller moved from golift.io to unpoller.com.
    for path in DASHBOARDS:
        assert "golift.io" not in path.read_text(), path.name
