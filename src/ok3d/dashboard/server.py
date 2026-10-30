"""The Dashboard's web server: HTTPS only, behind its own sign-in.

It has the sign-in and six pages: Home (what's left to do, Check and Apply, releases and
upgrades, and What's next), Setup (ready-made setups and switches, switches.py), Settings,
Devices, Keys, and Maintenance (times when alerts don't notify you), plus the Upgrade page
that Home leads to. Each page reads what the helper
publishes, and each button leaves a request for it (helper_link.py).

Every page is made here, with every value escaped, and carries headers that keep it out of
frames, stop other sites' scripts, and keep it out of caches. A form is accepted only from
the Dashboard's own pages: every POST must come with an Origin header naming the Dashboard
(and, from browsers that send it, Sec-Fetch-Site: same-origin). GET never changes anything.

A slow or silent client can't hold it up for long: each connection's TLS handshake happens in
its own thread; every read has a time limit, a form's body has one of its own, and so does
each whole connection; and only so many connections run at once.
"""

from __future__ import annotations

import contextlib
import html
import re
import socket
import ssl
import threading
import time
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from ok3d import __version__
from ok3d import maintenance as rules
from ok3d.dashboard import helper_link, switches
from ok3d.dashboard.auth import SESSION_TTL, Auth, Paused

# __Host-: browsers accept it only over HTTPS, for this host and every path, so no other site
# or name can set it.
COOKIE = "__Host-ok3d_session"
# Seconds a connection may take for its handshake, and between reads and writes after.
TIMEOUT = 10
# The most connections served at once; the rest are closed straight away.
MAX_CONNECTIONS = 32
# The most of a form that's read. The sign-in form is a few dozen bytes; a settings or devices
# file may be 64 KB, which a browser may send at up to six times that (a line break goes as
# %0D%0A).
MAX_FORM = 4096
MAX_FILE_FORM = 6 * 64 * 1024 + 1024
# A body that's refused is read and thrown away first if it's at most this big (see
# discard_body). A bigger one is refused straight away.
MAX_DISCARD = 1024 * 1024
# Seconds a form's body may take to arrive, however it's sent (see read_body).
BODY_TIME = 30
# Where each release's notes are.
RELEASES_PAGE = "https://github.com/southsidedean/observability-k3d/releases/tag/"
# Seconds a whole connection may take, from the TLS handshake to the last byte of the answer
# (see Server.process_request_thread).
REQUEST_TIME = 60

HEADERS = {
    "Content-Security-Policy": "default-src 'none'; style-src 'self'; img-src 'self'; form-action 'self'; "
    "frame-ancestors 'none'; base-uri 'none'",
    "X-Content-Type-Options": "nosniff",
    # same-origin, not no-referrer: with no-referrer, browsers send "Origin: null" on a form,
    # and the Origin check below would refuse every one. Other sites still get no referrer.
    "Referrer-Policy": "same-origin",
    "Cache-Control": "no-store",
    "Cross-Origin-Opener-Policy": "same-origin",
}

STYLE = b"""
:root { color-scheme: light dark; --fg: #1d1d1f; --bg: #fafafa; --muted: #6b6b70; --card: #fff;
  --line: #d9d9de; --accent: #b86e00; --bad: #b3261e; --good: #2e7d32; }
@media (prefers-color-scheme: dark) { :root { --fg: #ececf0; --bg: #16161a; --muted: #a0a0a8;
  --card: #202026; --line: #34343c; --accent: #f0a63a; --bad: #f2867d; --good: #7cc47f; } }
body { font: 16px/1.5 system-ui, sans-serif; color: var(--fg); background: var(--bg); margin: 0; }
header { display: flex; align-items: center; justify-content: space-between; padding: 12px 16px;
  border-bottom: 1px solid var(--line); }
header h1 { font-size: 18px; margin: 0; }
main { max-width: 760px; margin: 0 auto; padding: 16px; }
section { background: var(--card); border: 1px solid var(--line); border-radius: 8px; padding: 16px;
  margin-bottom: 16px; }
h2 { font-size: 16px; margin: 0 0 8px; }
.muted { color: var(--muted); }
.bad { color: var(--bad); }
.good { color: var(--good); }
pre { overflow-x: auto; font-size: 13px; background: var(--bg); border: 1px solid var(--line);
  border-radius: 6px; padding: 8px; }
input[type=password] { font: inherit; padding: 8px; width: 100%; box-sizing: border-box;
  border: 1px solid var(--line); border-radius: 6px; background: var(--bg); color: var(--fg); }
button { font: inherit; padding: 8px 14px; border-radius: 6px; border: 1px solid var(--accent);
  background: var(--accent); color: #fff; cursor: pointer; }
button.plain { background: none; color: var(--fg); border-color: var(--line); }
form.inline { display: inline; }
details { margin-top: 8px; }
nav a { margin-right: 12px; color: var(--fg); }
h3 { font-size: 15px; margin: 12px 0 4px; }
textarea { font: 13px/1.4 ui-monospace, monospace; width: 100%; box-sizing: border-box; padding: 8px;
  border: 1px solid var(--line); border-radius: 6px; background: var(--bg); color: var(--fg); }
input[type=password] { max-width: 420px; }
button[disabled] { opacity: 0.5; cursor: not-allowed; }
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; }
.card { border: 1px solid var(--line); border-radius: 8px; padding: 12px; }
.card.chosen { border-color: var(--accent); }
.card p { margin: 4px 0 8px; }
ul.todo { padding-left: 20px; }
"""


@dataclass(frozen=True)
class Config:
    state: Path  # <data root>/dashboard, the Dashboard's own folder
    helper: Path  # <data root>/helper, read-only: the helper's answers
    # The Dashboard's own addresses, such as https://my-server.lan:8444. When given, a form's
    # Origin must be one of them; without, it must match the Host the browser asked for.
    origins: tuple[str, ...] = ()


def page(title: str, body: str, signed_in: bool = False) -> bytes:
    """A whole page. `body` must already be escaped."""
    sign_out = (
        '<form class="inline" method="post" action="/sign-out"><button class="plain">Sign out</button></form>'
        if signed_in
        else ""
    )
    return (
        "<!doctype html><html lang=en><meta charset=utf-8>"
        '<meta name=viewport content="width=device-width, initial-scale=1">'
        f"<title>{html.escape(title)} · ok3d</title><link rel=stylesheet href=/style.css>"
        f"<header><h1>ok3d</h1>{NAV if signed_in else ''}{sign_out}</header><main>{body}</main></html>"
    ).encode()


NAV = (
    '<nav><a href="/">Home</a> <a href="/setup">Setup</a> <a href="/settings">Settings</a> '
    '<a href="/devices">Devices</a> <a href="/keys">Keys</a> <a href="/maintenance">Maintenance</a></nav>'
)

# What each page says about saving: the helper checks first, and keeps your old file.
SAVE_NOTE = (
    "<p class=muted>Saving sends this to the helper, which checks it with <code>./ok3d validate</code> "
    "and saves it only if it passes, keeping a copy of the old one. Home shows the answer.</p>"
)


def answer_section(config: Config) -> str:
    last = helper_link.answer(config.helper)
    if last is None:
        return "<section><h2>The helper's last answer</h2><p class=muted>None yet.</p></section>"
    state = last.state or "unknown"
    status = {"finished": "good" if last.passed else "bad", "refused": "bad", "failed": "bad"}
    words = {
        "running": "is running",
        "finished": f"finished with exit status {last.fields.get('exit', '?')}",
        "refused": f"was refused: {last.fields.get('reason', '')}",
        "failed": f"couldn't run: {last.fields.get('reason', '')}",
    }
    what = last.action or "a request"
    if last.fields.get("name"):
        what += f" {last.fields['name']}"
    when = f" at {last.fields['finished']}" if "finished" in last.fields else ""
    return (
        "<section><h2>The helper's last answer</h2>"
        f'<p class="{status.get(state, "muted")}">{html.escape(what)} '
        f"{html.escape(words.get(state, state))}{html.escape(when)}.</p>"
        + (f"<pre>{html.escape(last.output)}</pre>" if last.output.strip() else "")
        + "</section>"
    )


def home(config: Config, message: str = "") -> str:
    """Home: the helper, Check and Apply, releases and upgrades, and the helper's last answer."""
    note = f"<p class=bad>{html.escape(message)}</p>" if message else ""
    if helper_link.upgrading(config.helper):
        return (f"<section><h2>ok3d {html.escape(__version__)}</h2>{note}<p>Check, Apply, and saving are "
                "off until the upgrade below is done.</p></section>" + release_section(config))  # fmt: skip
    if not helper_link.alive(config.helper):
        helper = (
            "<p class=bad>The helper isn't running, so Check, Apply, and saving can't happen from "
            "here. On the server: <code>systemctl --user status ok3d-helper</code>.</p>"
        )
    else:
        helper = "<p class=good>The helper is running.</p>"
    apply_note = (
        ""
        if helper_link.can_apply(config.state, config.helper)
        else "<p class=muted>Apply turns on once a Check finds no problems, and off again when anything "
        "else is sent.</p>"
    )
    disabled = "" if helper_link.can_apply(config.state, config.helper) else " disabled"
    return (
        f"<section><h2>ok3d {html.escape(__version__)}</h2>{note}{maintenance_note(config)}{helper}"
        "<p>Check that the server and your settings are ready, then Apply to make the cluster and "
        "deploy, or bring it up to date with your settings.</p>"
        '<form class="inline" method="post" action="/check"><button>Check</button></form> '
        f'<form class="inline" method="post" action="/apply"><button{disabled}>Apply</button></form>'
        f"{apply_note}{plan_section(config)}"
        "<p class=muted>On the server: <code>./ok3d check</code>, then <code>./ok3d apply</code>.</p>"
        "</section>" + todo_section(config) + next_section(config)
        + answer_section(config)
        + release_section(config)
    )


def plan_list(plan: helper_link.ApplyPlan) -> str:
    """What Apply would change, as a list, each part already escaped."""
    items = [f"<li>Restart {html.escape(p)}</li>" for p in plan.restart]
    items += [f"<li>Stop {html.escape(p)}</li>" for p in plan.stop]
    items += [f"<li>Start {html.escape(p)}</li>" for p in plan.start]
    if plan.hidden:
        items.append(f"<li>Restart, stop, or start {plan.hidden} more part(s), whose names can't be shown here: "
                     "<code>./ok3d check</code> on the server names them</li>")  # fmt: skip
    if plan.other:
        items.append(f"<li>{plan.other} other change(s), such as alert rules or dashboards, which stop nothing</li>")
    return f"<ul class=todo>{''.join(items)}</ul>" if items else ""


def plan_section(config: Config) -> str:
    """Under Apply, once a Check has passed: what Apply would change in the running cluster."""
    plan = helper_link.apply_plan(config.helper)
    if plan is None or not helper_link.can_apply(config.state, config.helper):
        return ""
    if plan.state == "new":
        return "<p class=muted>Apply will make what's missing and deploy ok3d.</p>"
    if plan.state == "none":
        return "<p class=muted>Apply will change nothing that's running.</p>"
    if plan.state == "unknown":
        return "<p class=muted>Check couldn't tell what Apply would change, so Apply asks first.</p>"
    return "<p>What Apply will change:</p>" + plan_list(plan)


def apply_asks_page(config: Config, message: str = "") -> str:
    """Before an Apply that would restart or stop part of the running cluster: which, and why
    that matters, with the button that goes ahead."""
    plan = helper_link.apply_plan(config.helper)
    note = f"<p class=bad>{html.escape(message)}</p>" if message else ""
    if plan is None or plan.state == "unknown":
        what = "<p>Check couldn't tell what Apply would change in the running cluster.</p>"
    else:
        what = "<p>Apply will:</p>" + plan_list(plan)
    return (
        f"<section><h2>Apply?</h2>{note}{what}"
        "<p>A part that restarts is unavailable for a minute or so: Grafana's pages, say, or alerts while "
        "Alertmanager restarts. A part that stops is gone until you turn it on again. Prometheus's "
        "history and Grafana's dashboards are kept.</p>"
        f'<form class="inline" method="post" action="/apply"><input type="hidden" name="confirm" value="yes">'
        '<button>Apply anyway</button></form> <a href="/">Back to Home</a>'
        "<p class=muted>The same on the server: <code>./ok3d apply</code>, which asks too.</p></section>"
    )


def who(what: str) -> str:
    """What a maintenance window covers, in words, escaped."""
    return "all of ok3d" if what == "all" else html.escape(what.replace(",", ", "))


def maintenance_note(config: Config) -> str:
    """On Home, while a maintenance window is on: what's silenced, and until when."""
    found = helper_link.maintenance(config.helper)
    now = datetime.now(UTC)
    on = [w for w in (found[1] if found else []) if w.on(now)]
    return "".join(f'<p class=bad>Maintenance: alerts for {who(w.what)} don\'t notify you until '
                   f'{html.escape(w.end_here)} (<a href="/maintenance">Maintenance</a>).</p>' for w in on)  # fmt: skip


# The lengths offered for a window that starts now, as (value, words).
LENGTHS = (("30m", "30 minutes"), ("1h", "1 hour"), ("2h", "2 hours"), ("4h", "4 hours"), ("8h", "8 hours"),
           ("1d", "1 day"))  # fmt: skip
# A device's name in devices.yaml.
DEVICE_NAMES = re.compile(rf"^\s*(?:-\s+)?name:\s*['\"]?({rules.DEVICE})['\"]?\s*$", re.MULTILINE)


def maintenance_page(config: Config, message: str = "") -> str:
    """Maintenance: the windows, and the form that adds one."""
    note = f"<p class=bad>{html.escape(message)}</p>" if message else ""
    found = helper_link.maintenance(config.helper)
    now = datetime.now(UTC)
    rows = []
    for w in found[1] if found else []:
        if w.end <= now:
            continue
        state = "<span class=bad>on now</span>" if w.on(now) else "<span class=muted>starts later</span>"
        rows.append(
            f"<li>{who(w.what)}, {html.escape(w.start_here)} to {html.escape(w.end_here)}: {state}"
            + (f" ({html.escape(w.reason)})" if w.reason else "")
            + f' <form class="inline" method="post" action="/maintenance/end"><input type="hidden" name="window" '
            f'value="{w.id}"><button class="plain">End now</button></form></li>'
        )
    listed = f"<ul class=todo>{''.join(rows)}</ul>" if rows else "<p class=muted>No maintenance windows.</p>"
    checked = (f"Read from Alertmanager at {html.escape(found[0])}." if found
               else "Not read from Alertmanager yet.")  # fmt: skip
    devices = DEVICE_NAMES.findall(helper_link.current(config.helper, "devices.yaml") or "")
    boxes = "".join(f'<label><input type="checkbox" name="device-{d}" value="on"> {d}</label> ' for d in devices)
    lengths = "".join(f'<option value="{v}"{" selected" if v == "2h" else ""}>{w}</option>' for v, w in LENGTHS)
    return (
        f"<section><h2>Maintenance windows</h2>{note}"
        "<p>While a window is on, the alerts it covers don't notify you: for all of ok3d, or for the devices "
        "you choose. They still fire and show in Grafana, and the dead man's switch keeps running.</p>"
        f"{listed}<p class=muted>{checked}</p>"
        '<form method="post" action="/maintenance/refresh"><button class="plain">Read them again</button></form>'
        "<p class=muted>On the server: <code>./ok3d maintenance</code></p></section>"
        '<section><h2>Add a window</h2><form method="post" action="/maintenance">'
        '<h3>For</h3><p><label><input type="radio" name="scope" value="all" checked> All of ok3d</label></p>'
        '<p><label><input type="radio" name="scope" value="devices"> These devices:</label> '
        + (boxes or "<span class=muted>none in devices.yaml yet</span>") + "</p>"
        '<h3>When</h3><p><label><input type="radio" name="timing" value="now" checked> From now, for</label> '
        f'<select name="length" aria-label="How long">{lengths}</select></p>'
        '<p><label><input type="radio" name="timing" value="later"> From</label> '
        '<input type="datetime-local" name="start" aria-label="From"> to '
        '<input type="datetime-local" name="end" aria-label="To"> '
        "<span class=muted>(the server's own time)</span></p>"
        '<h3>Why</h3><p><input type="text" name="reason" maxlength="100" aria-label="Why" '
        'placeholder="Router firmware update"></p>'
        "<p><button>Add window</button></p></form>"
        '<p class=muted>On the server: <code>./ok3d maintenance add all 2h "Router firmware update"</code>, or '
        "devices joined by commas instead of all, and START/END such as "
        "<code>2026-11-03T02:00/2026-11-03T04:00</code> instead of a length.</p></section>"
        + answer_section(config)
    )


def release_section(config: Config) -> str:
    """Releases: how the last upgrade went (or how this one is going), and whether a newer
    release is out, with the way to it."""
    last = helper_link.upgrade(config.helper)
    if last is not None and last.state == "running":
        f = {k: html.escape(v) for k, v in last.fields.items()}
        return (
            f"<section><h2>Upgrading</h2><p>From ok3d {f.get('from', '?')} to {f.get('to', '?')}, "
            f"started at {f.get('started', '?')}. Now: {f.get('step', '?')}.</p>"
            "<p class=muted>ok3d's pages are down until it's done. The Dashboard restarts partway, so "
            "you'll sign in again. Reload this page to see how it's going.</p>"
            f"<pre>{html.escape(last.output)}</pre></section>"
        )
    parts = []
    if last is not None:
        f = {k: html.escape(v) for k, v in last.fields.items()}
        what = f"The upgrade from ok3d {f.get('from', '?')} to {f.get('to', '?')}"
        if last.state == "finished":
            parts.append(f"<p class=good>{what} finished at {f.get('finished', '?')}.</p>")
        else:
            parts.append(f"<p class=bad>{what} stopped at {f.get('finished', '?')}: {f.get('step', '?')}</p>")
        if last.output.strip():
            parts.append(f"<details><summary>What it printed</summary><pre>{html.escape(last.output)}</pre></details>")
    newest = helper_link.newest_release(config.helper)
    if newest is not None and newest.release and helper_link.is_newer(newest.release, __version__):
        release = html.escape(newest.release)
        parts.append(
            f"<p>ok3d {release} is out. Read its notes first, especially Upgrading: "
            f'<a href="{RELEASES_PAGE}{release}">{RELEASES_PAGE}{release}</a></p>'
            f'<form method="get" action="/upgrade"><button>Upgrade to {release}</button></form>'
            f"<p class=muted>On the server: <code>./ok3d upgrade {release}</code></p>"
        )
    elif newest is not None:
        parts.append(f"<p>No newer release when ok3d last looked, at {html.escape(newest.checked)}.</p>")
    else:
        parts.append("<p>ok3d hasn't looked for a newer release yet.</p>")
    parts.append(
        '<form method="post" action="/look-for-release"><button class="plain">Look for a new release</button></form>'
        "<p class=muted>This asks GitHub for the list of ok3d's releases; ok3d never does on its own. "
        "On the server: <code>./ok3d upgrade</code></p>"
    )
    return "<section><h2>Releases</h2>" + "".join(parts) + "</section>"


def upgrade_page(config: Config, message: str = "") -> str:
    """Upgrade: what upgrading to the newer release does, and the button that starts it."""
    note = f"<p class=bad>{html.escape(message)}</p>" if message else ""
    newest = helper_link.newest_release(config.helper)
    if newest is None or not newest.release or not helper_link.is_newer(newest.release, __version__):
        return (f"<section><h2>Upgrade</h2>{note}<p>There's no newer release to upgrade to. Home can look "
                'for one: <a href="/">Home</a>.</p></section>')  # fmt: skip
    release = html.escape(newest.release)
    return (
        f"<section><h2>Upgrade to ok3d {release}</h2>{note}"
        f'<p>Read its notes first, especially Upgrading: <a href="{RELEASES_PAGE}{release}">'
        f"{RELEASES_PAGE}{release}</a>. If they say to change something first, do that, then come back.</p>"
        "<p>Upgrading:</p><ol>"
        f"<li>Checks that {release} is signed with ok3d's release key, and stops if it isn't.</li>"
        "<li>Copies your <code>settings.yaml</code>, <code>devices.yaml</code>, and <code>.env</code> to "
        "<code>local/backups/</code> in the ok3d folder.</li>"
        f"<li>Moves ok3d to {release}, checks your settings with it, and installs its helper and Dashboard. "
        "If that check or install fails, it moves back, and nothing else changes.</li>"
        "<li>Deletes the cluster, backs up the certificate authority, Grafana, and Alertmanager to "
        f"<code>backups/</code> in the data root, then makes the cluster again with {release}.</li></ol>"
        "<p>ok3d's pages are down until it's done: the new cluster downloads its images again, so it can "
        "take as long as your first Apply did. The Dashboard restarts partway, so you'll sign in again. "
        "Prometheus's history, Grafana's dashboards, Alertmanager's silences, and the certificate "
        "authority come through.</p>"
        f"<p class=muted>The same on the server: <code>./ok3d upgrade {release}</code></p>"
        f'<form method="post" action="/upgrade"><input type="hidden" name="version" value="{release}">'
        "<p><button>Upgrade now</button></p></form></section>"
    )


# Where Keys come from: the ones the Dashboard can set, and the rest, set only on the server.
def key_place(name: str) -> str:
    return "on the Keys page" if name in helper_link.ENV_NAMES else "in .env on the server"


# A device in devices.yaml: every one has a name.
DEVICE_NAME = re.compile(r"^\s*(?:-\s+)?name:\s*\S", re.MULTILINE)


def todo(config: Config) -> list[str]:
    """What's left before ok3d can do its job, each already escaped: settings, the keys each
    switched-on part needs, somewhere for alerts to go, and devices to watch."""
    settings = helper_link.current(config.helper, "settings.yaml")
    if settings is None:
        return ["There's no <code>settings.yaml</code> on the server yet. Make it there from "
                "<code>settings.example.yaml</code> (the installer does this for you)."]  # fmt: skip
    have = helper_link.env_set(config.helper)
    left = []
    for switch in switches.MODULES + switches.ALERTS:
        on = switches.flag(settings, switch.path)
        if not switch.available or on is False:
            continue
        if on is None:
            left.append(f"Setup can't tell whether {html.escape(switch.name)} is on: look at "
                        f"<code>{switch.setting}</code> on the Settings page.")  # fmt: skip
            continue
        left += [f"{html.escape(switch.name)} is on, and needs {html.escape(say)}." for say in switch.missing(settings)]
        keys = list(switch.keys)
        if switch.setting == "alerts.ntfy.enabled" and switches.flag(settings, ("alerts", "ntfy", "useToken")):
            keys.append("NTFY_TOKEN")
        left += [f"{html.escape(switch.name)} is on, and needs <code>{k}</code>: set it {key_place(k)}."
                 for k in keys if k not in have]  # fmt: skip
    if all(switches.flag(settings, ("alerts", way, "enabled")) is False for way in ("ntfy", "email")):
        left.append('Alerts go nowhere yet: turn on ntfy or email on <a href="/setup">Setup</a>.')
    if not DEVICE_NAME.search(helper_link.current(config.helper, "devices.yaml") or ""):
        left.append('There are no devices to watch yet: add them on <a href="/devices">Devices</a>.')
    return left


def todo_section(config: Config) -> str:
    left = todo(config)
    if not left:
        return "<section><h2>Before you Apply</h2><p class=good>Nothing's missing.</p></section>"
    items = "".join(f"<li>{item}</li>" for item in left)
    return f"<section><h2>Before you Apply</h2><ul class=todo>{items}</ul></section>"


# What a domain or a port may look like before it goes into a link.
DOMAIN = re.compile(r"[a-z0-9]([a-z0-9.-]{0,251}[a-z0-9])?")
PORT = re.compile(r"[1-9][0-9]{0,4}")


def pages_address(settings: str | None, name: str) -> str:
    """The address of one of ok3d's pages, such as https://grafana.noc.home.arpa:8443/."""
    domain = (switches.read(settings, ("tls", "domain")) or "noc.home.arpa").lower()
    port = switches.read(settings, ("cluster", "ports", "https")) or "8443"
    if not DOMAIN.fullmatch(domain) or not PORT.fullmatch(port):
        domain, port = "noc.home.arpa", "8443"
    return f"https://{name}.{domain}" + ("" if port == "443" else f":{port}") + "/"


def next_section(config: Config) -> str:
    """What's next, once an Apply has worked: the steps that make ok3d useful from your own
    devices, which the Dashboard can't do for you."""
    when = helper_link.applied(config.helper)
    if when is None:
        return ""
    settings = helper_link.current(config.helper, "settings.yaml")
    ca = html.escape(pages_address(settings, "ca"))
    grafana = html.escape(pages_address(settings, "grafana"))
    domain = html.escape(pages_address(settings, "x")[len("https://x."):].split(":")[0].rstrip("/"))
    return (
        f"<section><h2>What's next</h2><p class=good>The last Apply that worked finished at {html.escape(when)}.</p><ol>"
        f"<li>Point <code>*.{domain}</code> at this server, in your router or local DNS server "
        "(docs/certificate.md has the steps).</li>"
        f"<li>Trust ok3d's certificate authority on each device you'll use: download it from <a href=\"{ca}\">{ca}</a>.</li>"
        f'<li>Open Grafana at <a href="{grafana}">{grafana}</a>. Its user is <code>admin</code>, and its password '
        "is in <code>admin-password</code> in the data root.</li>"
        "<li>Send yourself a test alert: <code>./ok3d test-alert</code> on the server.</li>"
        '<li>Add the rest of your devices on <a href="/devices">Devices</a>, then Check and Apply again.</li>'
        "</ol></section>"
    )


def switch_form(switch: switches.Switch, settings: str, base: str, have: set[str]) -> str:
    """One switch: what it is, its setting, what it needs, and a button, or why there isn't one."""
    on = switches.flag(settings, switch.path)
    state = {True: "<span class=good>on</span>", False: "<span class=muted>off</span>",
             None: "<span class=bad>can't tell</span>"}[on]  # fmt: skip
    why = ""
    if not switch.available:
        why = f"Comes in {switch.since[0]}.{switch.since[1]}."
        state = ""
    elif switch.host_only:
        why = f"Changed only on the server: {switch.host_only}."
    elif on is None:
        why = "settings.yaml has this in a shape the Setup page can't change: change it on the Settings page."
    elif not on and switch.missing(settings):
        why = "Before it can go on, it needs " + "; and ".join(switch.missing(settings)) + "."
    keys = ""
    if switch.keys and switch.available:
        keys = "<p class=muted>Needs " + ", ".join(
            f"<code>{k}</code> ({'set' if k in have else 'not set'}, {key_place(k)})" for k in switch.keys) + ".</p>"  # fmt: skip
    written = {True: "true", False: "false", None: switches.read(settings, switch.path)}[on]
    button = (f"<p class=muted>{html.escape(why)}</p>" if why else
              f'<input type="hidden" name="base" value="{base}"><input type="hidden" name="switch" value="{switch.setting}">'
              f'<input type="hidden" name="on" value="{"false" if on else "true"}">'
              f"<p><button>{'Turn off' if on else 'Turn on'}</button></p>")  # fmt: skip
    return (
        f'<form method="post" action="/setup"><h3>{html.escape(switch.name)} {state}</h3>'
        f"<p class=muted>{html.escape(switch.about)}"
        + (f" In settings.yaml: <code>{switch.setting}: {html.escape(written)}</code>."
           if switch.available and written is not None else "")
        + "</p>"
        f"{keys}{button}</form>"
    )


def card_html(card: switches.Card, settings: str, base: str) -> str:
    chosen = card.available and all(switches.flag(settings, SWITCH_PATHS[k]) == v for k, v in card.changes().items())
    missing = [say for k in sorted(card.on) for say in switches.SWITCHES[k].missing(settings)]
    if not card.available:
        action = f"<p class=muted>Comes in {card.since[0]}.{card.since[1]}.</p>"
    elif chosen:
        action = "<p class=good>Your setup now.</p>"
    elif missing:
        action = f"<p class=muted>Before you can choose it, it needs {html.escape('; and '.join(missing))}.</p>"
    else:
        action = (f'<form method="post" action="/setup"><input type="hidden" name="base" value="{base}">'
                  f'<input type="hidden" name="card" value="{card.id}"><button>Choose</button></form>')  # fmt: skip
    # What choosing it writes, as the lines you'd set in settings.yaml on the server.
    lines = ", ".join(f"<code>{s}: {'true' if on else 'false'}</code>" for s, on in card.changes().items())
    return (
        f'<div class="card{" chosen" if chosen else ""}"><h3>{html.escape(card.name)}</h3>'
        f"<p>{html.escape(card.about)}</p><p class=muted>Needs: {html.escape(card.needs)}</p>"
        + (f"<p class=muted>In settings.yaml: {lines}.</p>" if card.available and lines else "")
        + f"{action}</div>"
    )


SWITCH_PATHS = {s.setting: s.path for s in switches.MODULES + switches.ALERTS}


def setup_page(config: Config, message: str = "") -> str:
    """Setup: a ready-made setup, or each part switched on or off, and where alerts go. Each
    choice is saved to settings.yaml through the helper, which checks it first."""
    settings = helper_link.current(config.helper, "settings.yaml")
    note = f"<p class=bad>{html.escape(message)}</p>" if message else ""
    if settings is None:
        return (f"<section><h2>Setup</h2>{note}<p class=bad>There's no settings.yaml on the server yet. "
                "Make it there first, from settings.example.yaml.</p></section>")  # fmt: skip
    base = helper_link.fingerprint(settings)
    have = helper_link.env_set(config.helper)
    cards = "".join(card_html(c, settings, base) for c in switches.CARDS)
    modules = "".join(switch_form(s, settings, base, have) for s in switches.MODULES)
    alerts = "".join(switch_form(s, settings, base, have) for s in switches.ALERTS)
    return (
        f"<section><h2>Ready-made setups</h2>{note}<p>Choose one, or switch the parts on and off "
        "yourself below. Metrics, alerts, and ok3d's pages are always on. Each says the line it writes "
        "in settings.yaml; a dot means one setting inside another, so <code>modules.unifi: true</code> is "
        "<code>unifi: true</code> under <code>modules:</code>.</p>"
        f'<div class="cards">{cards}</div>{SAVE_NOTE}</section>'
        f"<section><h2>Parts</h2>{modules}</section>"
        f"<section><h2>Where alerts go</h2>{alerts}</section>"
    )


def file_page(config: Config, name: str, message: str = "") -> str:
    """Settings or Devices: the file as it is on the server, to change and save."""
    title = {"settings.yaml": "Settings", "devices.yaml": "Devices"}[name]
    text = helper_link.current(config.helper, name)
    about = {
        "settings.yaml": (
            "<p>Your <code>settings.yaml</code>. <code>settings.example.yaml</code> explains every "
            "setting. Some settings decide where ok3d keeps its data and where it sends your keys "
            "and passwords: those you change in the file on the server, and a save here that "
            "changes them is refused (docs/helper-under-the-hood.md lists them).</p>"
        ),
        "devices.yaml": (
            "<p>Your <code>devices.yaml</code>: every device ok3d watches. "
            "<code>devices.example.yaml</code> and docs/devices.md explain each field.</p>"
        ),
    }[name]
    base = helper_link.fingerprint(text)
    if text is None:
        if name == "settings.yaml":
            return (f"<section><h2>{title}</h2>{about}<p class=bad>There's no settings.yaml on the "
                    "server yet. Make it there first, from settings.example.yaml; after that you can "
                    "change it here.</p></section>")  # fmt: skip
        text = "devices: []\n"
    note = f"<p class=bad>{html.escape(message)}</p>" if message else ""
    return (
        f"<section><h2>{title}</h2>{about}{note}"
        f'<form method="post" action="/{title.lower()}"><input type="hidden" name="base" value="{base}">'
        # The newline after <textarea> is one HTML drops, so a file that starts with a blank line keeps it.
        f'<p><textarea name="file" rows="24" spellcheck="false" aria-label="{name}">\n{html.escape(text)}</textarea></p>'
        f"{SAVE_NOTE}<p class=muted>On the server: edit <code>{name}</code> in the ok3d folder, then "
        "<code>./ok3d check</code>.</p><p><button>Save</button></p></form></section>"
    )


# What each line of .env on the Keys page is, as (name, what it is) pairs.
KEY_ABOUT = (
    ("UNIFI_API_KEY", "The UniFi controller's API key, from a view-only admin."),
    ("NTFY_TOPIC", "Your ntfy topic: a long, random name, since anyone who knows it can read your alerts."),
    ("NTFY_TOKEN", "The ntfy topic's access token, if it needs one."),
    ("SMTP_PASSWORD", "The password of the mailbox alerts are sent from."),
)


def keys_page(config: Config, message: str = "") -> str:
    """Keys: set the lines of .env the Dashboard may set. It never shows a value back."""
    have = helper_link.env_set(config.helper)
    note = f"<p class=bad>{html.escape(message)}</p>" if message else ""
    rows = []
    for name, about in KEY_ABOUT:
        state = "<span class=good>set</span>" if name in have else "<span class=muted>not set</span>"
        rows.append(
            f'<form method="post" action="/keys"><h3><code>{name}</code> {state}</h3>'
            f"<p class=muted>{html.escape(about)} On the server: the line <code>{name}=</code> in "
            "<code>.env</code>.</p>"
            f'<input type="hidden" name="name" value="{name}">'
            f'<p><input type="password" name="value" autocomplete="off" aria-label="{name}"> '
            "<button>Save</button></p></form>"
        )
    others = ", ".join(
        f"<code>{n}</code> ({'set' if n in have else 'not set'})"
        for n in ("OK3D_ADMIN_PASSWORD", "DEADMAN_URL", "ANTHROPIC_API_KEY")
    )
    return (
        f"<section><h2>Keys and passwords</h2>{note}"
        "<p>Each goes into <code>.env</code> on the server. The Dashboard never shows one back: "
        "only whether it's set. Saving an empty value clears it. A value is one line of letters, "
        "digits, and symbols, with no spaces, quotes, backslashes, <code>$</code>, or backticks; "
        "one with those goes into <code>.env</code> by hand.</p>"
        + "".join(rows)
        + f"<p class=muted>Set only on the server, in <code>.env</code>: {others}.</p></section>"
    )


def sign_in_page(message: str = "") -> str:
    note = f"<p class=bad>{html.escape(message)}</p>" if message else ""
    return (
        "<section><h2>Sign in</h2>"
        "<p class=muted>The Dashboard's password is in <code>dashboard/password</code> in the data "
        "root, readable only by you. If you ran the installer yourself, it showed it too.</p>"
        f'{note}<form method="post" action="/sign-in">'
        '<p><input type="password" name="password" autocomplete="current-password" required '
        'aria-label="Password" autofocus></p><p><button>Sign in</button></p></form></section>'
    )


def printable(text: str) -> str:
    """Text safe for the log: control characters (which could rewrite a terminal) escaped."""
    return "".join(c if c.isprintable() else f"\\x{ord(c):02x}" for c in text)


class Handler(BaseHTTPRequestHandler):
    # Each read and write after the handshake may wait this long, so a slow client gives up
    # its thread instead of keeping it.
    timeout = TIMEOUT

    # Set on the class by make_server().
    config: Config
    auth: Auth

    def setup(self) -> None:
        # The TLS handshake, here in the connection's own thread rather than where connections
        # are accepted, so a client that never finishes it holds up nobody else.
        self.request.settimeout(TIMEOUT)
        self.request.do_handshake()
        super().setup()

    # Names the server without its Python version, which would only help someone looking for holes.
    def version_string(self) -> str:
        return "ok3d-dashboard"

    def log_request(self, code: int | str = "-", size: int | str = "-") -> None:
        # One line a request, without the query string, which could hold anything.
        path = getattr(self, "path", "").split("?")[0]
        print(printable(f"{self.client_address[0]} {self.command} {path} {code}"), flush=True)

    def log_message(self, format: str, *args: object) -> None:  # the base class names it format
        print(printable(f"{self.client_address[0]} {format % args}"), flush=True)

    def send(self, status: int, body: bytes, content_type: str = "text/html; charset=utf-8",
             extra: dict[str, str] | None = None) -> None:  # fmt: skip
        self.send_response(status)
        for name, value in (HEADERS | (extra or {})).items():
            self.send_header(name, value)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def redirect(self, to: str, extra: dict[str, str] | None = None) -> None:
        self.send(303, b"", extra={"Location": to} | (extra or {}))

    def session(self) -> str | None:
        """The session cookie's value. Read by hand: Python's cookie parser drops every cookie
        after one it can't read, so another app's odd cookie on the same host would sign you out."""
        for header in self.headers.get_all("Cookie") or []:
            for part in header.split(";"):
                name, sep, value = part.strip().partition("=")
                if sep and name == COOKIE:
                    return value
        return None

    def signed_in(self) -> bool:
        return self.auth.valid(self.session())

    def same_origin(self) -> bool:
        """Whether a POST came from one of the Dashboard's own pages."""
        origin = (self.headers.get("Origin") or "").lower()
        host = (self.headers.get("Host") or "").lower()
        fetch_site = self.headers.get("Sec-Fetch-Site")
        if fetch_site not in (None, "same-origin") or not origin:
            return False
        if self.config.origins:
            return origin in (o.lower() for o in self.config.origins)
        return bool(host) and origin == f"https://{host}"

    def read_body(self, length: int) -> bytes | None:
        """A body of length bytes, or None if it hasn't all come within BODY_TIME seconds. Each
        read takes whatever has arrived, so the time is checked after every piece, and a client
        sending a byte at a time keeps a thread for BODY_TIME, plus TIMEOUT for the last read."""
        deadline = time.monotonic() + BODY_TIME
        parts, left = [], length
        while left > 0:
            if time.monotonic() >= deadline or not (chunk := self.rfile.read1(min(left, 65536))):
                return None
            parts.append(chunk)
            left -= len(chunk)
        return b"".join(parts)

    def discard_body(self) -> None:
        """Reads a body that won't be used, and throws it away. Refused and closed before the
        browser has sent it all, the connection would be reset, and the browser would show that
        instead of the refusal."""
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return
        if 0 < length <= MAX_DISCARD:
            self.read_body(length)

    def read_form(self, limit: int = 0, fields: int = 10) -> dict[str, str] | None:
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            return None
        if not 0 <= length <= (limit or MAX_FORM):
            self.discard_body()
            return None
        if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/x-www-form-urlencoded":
            self.discard_body()
            return None
        body = self.read_body(length)
        if body is None:
            return None
        try:
            found = urllib.parse.parse_qs(body.decode("ascii"), max_num_fields=fields, errors="strict")
        except (ValueError, UnicodeDecodeError):
            return None
        return {k: v[0] for k, v in found.items()}

    def do_GET(self) -> None:
        path = urllib.parse.urlsplit(self.path).path
        if path == "/style.css":
            self.send(200, STYLE, "text/css; charset=utf-8")
        elif path == "/sign-in":
            if self.signed_in():
                self.redirect("/")
            else:
                self.send(200, page("Sign in", sign_in_page()))
        elif path in PAGES:
            if not self.signed_in():
                self.redirect("/sign-in")
                return
            self.send(200, page(PAGES[path][0], PAGES[path][1](self.config, ""), signed_in=True))
        else:
            self.send(404, page("Not found", "<section><h2>Not found</h2></section>", self.signed_in()))

    def do_HEAD(self) -> None:
        self.do_GET()

    def do_POST(self) -> None:
        path = urllib.parse.urlsplit(self.path).path
        if not self.same_origin():
            self.discard_body()
            self.send(403, page("Refused", "<section><h2>Refused</h2><p>That form didn't come from "
                                "this Dashboard.</p></section>"))  # fmt: skip
            return
        if path == "/sign-in":
            self.sign_in()
        elif path == "/sign-out":
            self.auth.sign_out(self.session())
            self.redirect("/sign-in", {"Set-Cookie": f"{COOKIE}=; Path=/; Secure; HttpOnly; SameSite=Strict; Max-Age=0"})
        elif path in ACTIONS:
            if not self.signed_in():
                self.discard_body()
                self.redirect("/sign-in")
                return
            ACTIONS[path](self)
        else:
            self.discard_body()
            self.send(404, page("Not found", "<section><h2>Not found</h2></section>", self.signed_in()))

    def sign_in(self) -> None:
        form = self.read_form()
        if form is None:
            self.send(400, page("Sign in", sign_in_page("That didn't arrive in one piece. Try again.")))
            return
        try:
            session = self.auth.sign_in(form.get("password", ""), self.client_address[0])
        except Paused:
            self.send(429, page("Sign in", sign_in_page("Too many wrong passwords. Wait a minute, then try again.")))
            return
        if session is None:
            time.sleep(0.5)  # a little slower, for anyone guessing
            self.send(401, page("Sign in", sign_in_page("That's not the password.")))
            return
        cookie = f"{COOKIE}={session}; Path=/; Secure; HttpOnly; SameSite=Strict; Max-Age={SESSION_TTL}"
        self.redirect("/", {"Set-Cookie": cookie})

    def ask_helper(self, back: str, render: Callable[[Config, str], str], title: str, action: str,
                   name: str | None = None, body: bytes | None = None, base: str | None = None,
                   version: str | None = None, extra: dict[str, str] | None = None) -> None:  # fmt: skip
        """Leaves a request for the helper, then sends you Home to watch for the answer, or
        back to the page with what went wrong."""
        if not helper_link.alive(self.config.helper):
            self.send(503, page(title, render(self.config, "The helper isn't running, so nothing was sent."), True))
            return
        if helper_link.upgrading(self.config.helper):
            self.send(409, page(title, render(self.config, "An upgrade is running, so nothing was sent. "
                                              "Home shows how it's going."), True))  # fmt: skip
            return
        try:
            helper_link.send(self.config.state, self.config.helper, action, name, body, base, version, extra)
        except helper_link.Unavailable:
            self.send(503, page(title, render(self.config, "The Dashboard can't write its outbox, so nothing "
                                              "was sent. Check the Dashboard's folder on the server."), True))  # fmt: skip
            return
        except helper_link.Busy:
            self.send(409, page(title, render(self.config, "The helper is busy with the last request. "
                                              "Try again when Home shows its answer."), True))  # fmt: skip
            return
        self.redirect(back)

    def post_check(self) -> None:
        self.ask_helper("/", home, "Home", "check")

    def post_apply(self) -> None:
        form = self.read_form()
        if not helper_link.can_apply(self.config.state, self.config.helper):
            self.send(409, page("Home", home(self.config, "") + "<p class=bad>Run a Check that finds "
                                "no problems first.</p>", True))  # fmt: skip
            return
        # Asks first when Apply would restart or stop something, or Check couldn't tell: the
        # answer is the same form again, with confirm=yes.
        plan = helper_link.apply_plan(self.config.helper)
        if (plan is None or plan.asks) and (form or {}).get("confirm") != "yes":
            self.send(200, page("Apply?", apply_asks_page(self.config), True))
            return
        self.ask_helper("/", home, "Home", "apply")

    def post_look_for_release(self) -> None:
        self.discard_body()
        self.ask_helper("/", home, "Home", "look-for-release")

    def post_upgrade(self) -> None:
        form = self.read_form()
        version = (form or {}).get("version", "")
        newest = helper_link.newest_release(self.config.helper)
        # Only the release Home offered: one ./ok3d upgrade found, newer than this Dashboard.
        if (form is None or newest is None or version != newest.release
                or not helper_link.is_newer(version, __version__)):  # fmt: skip
            self.send(409, page("Upgrade", upgrade_page(self.config, "That isn't the release on offer any more. "
                                                        "Here's what is."), True))  # fmt: skip
            return
        self.ask_helper("/", upgrade_page, "Upgrade", "upgrade", version=version)

    def post_maintenance(self) -> None:
        """Adds a window: all of ok3d or the devices ticked, from now for a length or between two
        times, checked as ./ok3d maintenance will check them before anything is sent."""
        form = self.read_form(fields=60)

        def refuse(message: str) -> None:
            self.send(400, page("Maintenance", maintenance_page(self.config, message), True))

        if form is None:
            refuse("That didn't arrive in one piece. Try again.")
            return
        if form.get("scope") == "devices":
            what = ",".join(sorted(k.removeprefix("device-") for k in form if k.startswith("device-")))
            if not what:
                refuse("Tick at least one device, or choose all of ok3d.")
                return
        else:
            what = "all"
        if form.get("timing") == "later":
            when = f"{form.get('start', '')}/{form.get('end', '')}"
        else:
            when = form.get("length", "")
        reason = form.get("reason", "").strip()
        if not rules.WHAT.fullmatch(what):
            refuse("Those aren't devices from devices.yaml.")
        elif when not in {v for v, _ in LENGTHS} and not rules.RANGE.fullmatch(when):
            refuse("Choose how long, or both a start and an end.")
        elif not rules.REASON.fullmatch(reason):
            refuse("The reason may have letters, digits, spaces, and , . ' ( ) / : _ -, up to 100 of them.")
        else:
            extra = {"what": what, "when": when} | ({"reason": reason} if reason else {})
            self.ask_helper("/maintenance", maintenance_page, "Maintenance", "maintenance-add", extra=extra)

    def post_maintenance_end(self) -> None:
        form = self.read_form()
        window = (form or {}).get("window", "")
        if not rules.SILENCE_ID.fullmatch(window):
            self.send(400, page("Maintenance", maintenance_page(self.config, "That isn't a window's id."), True))
            return
        self.ask_helper("/maintenance", maintenance_page, "Maintenance", "maintenance-end", extra={"window": window})

    def post_maintenance_refresh(self) -> None:
        self.discard_body()
        self.ask_helper("/maintenance", maintenance_page, "Maintenance", "maintenance-list")

    def post_file(self, name: str, action: str, title: str) -> None:
        def render(config: Config, message: str) -> str:
            return file_page(config, name, message)

        try:
            if int(self.headers.get("Content-Length", "0")) > MAX_FILE_FORM:
                self.discard_body()
                self.send(413, page(title, render(self.config, "That's bigger than 64 KB."), True))
                return
        except ValueError:
            pass
        form = self.read_form(MAX_FILE_FORM)
        text = (form or {}).get("file")
        base = (form or {}).get("base", "")
        if text is None or not re.fullmatch(r"[0-9a-f]{64}|none", base):
            self.send(400, page(title, render(self.config, "That didn't arrive in one piece. Try again."), True))
            return
        # A browser sends a text box's lines with \r\n; the files use \n.
        data = text.replace("\r\n", "\n").encode("utf-8")
        if not data.endswith(b"\n"):
            data += b"\n"
        if len(data) > helper_link.MAX_FILE:
            self.send(413, page(title, render(self.config, "That's bigger than 64 KB."), True))
            return
        self.ask_helper("/", render, title, action, body=data, base=base)

    def post_settings(self) -> None:
        self.post_file("settings.yaml", "save-settings", "Settings")

    def post_devices(self) -> None:
        self.post_file("devices.yaml", "save-devices", "Devices")

    def post_setup(self) -> None:
        form = self.read_form()
        settings = helper_link.current(self.config.helper, "settings.yaml")
        if form is None or settings is None:
            self.send(400, page("Setup", setup_page(self.config, "That didn't arrive in one piece. Try again."), True))
            return
        if form.get("base") != helper_link.fingerprint(settings):
            self.send(409, page("Setup", setup_page(self.config, "Your settings changed since that page was "
                                                    "shown. Here they are as they are now."), True))  # fmt: skip
            return
        card = switches.CARD_IDS.get(form.get("card", ""))
        switch = switches.SWITCHES.get(form.get("switch", ""))
        if card is not None and card.available:
            changes = card.changes()
            missing = [say for k in sorted(card.on) for say in switches.SWITCHES[k].missing(settings)]
        elif (switch is not None and switch.available and not switch.host_only
              and form.get("on") in ("true", "false")):  # fmt: skip
            changes = {switch.setting: form["on"] == "true"}
            missing = switch.missing(settings) if changes[switch.setting] else []
        else:
            self.send(400, page("Setup", setup_page(self.config, "The Setup page can't change that."), True))
            return
        if missing:
            self.send(400, page("Setup", setup_page(self.config, "First it needs " + "; and ".join(missing) + "."), True))
            return
        new = settings
        try:
            for setting, on in changes.items():
                if switches.flag(new, SWITCH_PATHS[setting]) != on:
                    new = switches.set_flag(new, SWITCH_PATHS[setting], on)
        except switches.CantEdit as e:
            self.send(400, page("Setup", setup_page(self.config, f"settings.yaml has {setting} in a shape the Setup "
                                                    f"page can't change safely: {e}. Change it on the Settings "
                                                    "page."), True))  # fmt: skip
            return
        if new == settings:
            self.send(200, page("Setup", setup_page(self.config, "Your settings say that already."), True))
            return
        if len(new.encode("utf-8")) > helper_link.MAX_FILE:
            self.send(413, page("Setup", setup_page(self.config, "That would make settings.yaml bigger than 64 KB."), True))
            return
        self.ask_helper("/", setup_page, "Setup", "save-settings", body=new.encode("utf-8"), base=form["base"])

    def post_keys(self) -> None:
        form = self.read_form()
        name = (form or {}).get("name", "")
        value = (form or {}).get("value", "")
        if form is None or name not in helper_link.ENV_NAMES:
            self.send(400, page("Keys", keys_page(self.config, "That didn't arrive in one piece. Try again."), True))
            return
        if not helper_link.ENV_VALUE.fullmatch(value):
            self.send(400, page("Keys", keys_page(self.config, f"{name} has characters .env can't hold "
                                                  "safely (see above). Nothing was saved."), True))  # fmt: skip
            return
        self.ask_helper("/", keys_page, "Keys", "set-env", name=name, body=value.encode("ascii"))


# The pages, by path: their title and what makes them.
PAGES: dict[str, tuple[str, Callable[[Config, str], str]]] = {
    "/": ("Home", home),
    "/setup": ("Setup", setup_page),
    "/settings": ("Settings", lambda c, m: file_page(c, "settings.yaml", m)),
    "/devices": ("Devices", lambda c, m: file_page(c, "devices.yaml", m)),
    "/keys": ("Keys", keys_page),
    "/upgrade": ("Upgrade", upgrade_page),
    "/maintenance": ("Maintenance", maintenance_page),
}

# What each form does, by path. Every one needs a session and the Dashboard's own Origin.
ACTIONS: dict[str, Callable[[Handler], None]] = {
    "/check": Handler.post_check,
    "/apply": Handler.post_apply,
    "/setup": Handler.post_setup,
    "/settings": Handler.post_settings,
    "/devices": Handler.post_devices,
    "/keys": Handler.post_keys,
    "/look-for-release": Handler.post_look_for_release,
    "/upgrade": Handler.post_upgrade,
    "/maintenance": Handler.post_maintenance,
    "/maintenance/end": Handler.post_maintenance_end,
    "/maintenance/refresh": Handler.post_maintenance_refresh,
}


def cut_off(request: socket.socket | tuple[bytes, socket.socket]) -> None:
    """Shuts a connection that has taken too long, from the timer's thread. socket.socket's
    own shutdown, not the TLS socket's, which would also drop the TLS state under the
    connection's own thread, mid-read."""
    if isinstance(request, socket.socket):
        with contextlib.suppress(OSError):  # closed already
            socket.socket.shutdown(request, socket.SHUT_RDWR)


class Server(ThreadingHTTPServer):
    """A thread for each connection, up to MAX_CONNECTIONS at once."""

    daemon_threads = True

    def __init__(self, address: tuple[str, int], handler: type[Handler]) -> None:
        super().__init__(address, handler)
        self.slots = threading.BoundedSemaphore(MAX_CONNECTIONS)

    def process_request(self, request: socket.socket | tuple[bytes, socket.socket], client_address: object) -> None:
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.slots.release()
            raise

    def process_request_thread(self, request: socket.socket | tuple[bytes, socket.socket], client_address: object) -> None:
        # Each read has a time limit, but a client sending a byte just inside it, during the
        # handshake or the headers, would never finish. So the whole connection has one too:
        # after REQUEST_TIME the socket is shut, which ends any read or write waiting on it.
        # socketserver's own version of this, written out so the timer is stopped before the
        # socket is closed: shut after, its number might be a new connection's.
        timer = threading.Timer(REQUEST_TIME, cut_off, (request,))
        timer.daemon = True
        try:
            timer.start()  # inside the try: a thread that won't start mustn't lose the slot
            self.finish_request(request, client_address)
        except Exception:
            self.handle_error(request, client_address)
        finally:
            timer.cancel()
            if timer.ident is not None:
                timer.join()  # a cut_off already under way finishes first
            self.shutdown_request(request)
            self.slots.release()

    def handle_error(self, request: object, client_address: object) -> None:
        # A handshake that failed or timed out, or a client that went away: one line, not a traceback.
        address = client_address[0] if isinstance(client_address, tuple) else client_address
        print(printable(f"{address} connection dropped"), flush=True)


def make_server(config: Config, host: str, port: int, cert: Path, key: Path) -> Server:
    """The server, with TLS 1.2 or newer and the Dashboard's certificate. It serves nothing
    without TLS."""
    auth = Auth(config.state)
    if auth.ensure():
        print(f"ok3d-dashboard: made a password; it's in {config.state / 'password'}", flush=True)
    handler = type("DashboardHandler", (Handler,), {"config": config, "auth": auth})
    server = Server((host, port), handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(cert, key)
    # The handshake waits for each connection's own thread (Handler.setup).
    server.socket = context.wrap_socket(server.socket, server_side=True, do_handshake_on_connect=False)
    return server
