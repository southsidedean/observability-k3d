"""Takes the docs' screenshots: the shots in docs/screenshots.json, in light and dark, with a
headless Chromium. scripts/screenshots.sh runs it in Playwright's container image, on a
machine running ok3d on the simulated network, and says how; it isn't meant to be run by hand.

Each picture is saved to <out>/<name>-<theme>.png with its metadata chunks taken out, and
<out>/sources.json records the ok3d version each was taken with.
"""

from __future__ import annotations

import argparse
import json
import struct
import zlib
from pathlib import Path
from typing import Any

# The PNG chunks kept: the picture itself and how its colours are meant. Everything else
# (text, times, Exif) goes, since none of it helps and some of it could say where it came from.
KEEP = {b"IHDR", b"PLTE", b"tRNS", b"IDAT", b"IEND", b"sRGB", b"gAMA", b"cHRM", b"pHYs"}
SIGNATURE = b"\x89PNG\r\n\x1a\n"
THEMES = ("light", "dark")
SITES = ("dashboard", "grafana")


def chunks(data: bytes) -> list[tuple[bytes, bytes]]:
    """A PNG's chunks, as (type, data). Raises ValueError for anything that isn't a whole PNG."""
    if not data.startswith(SIGNATURE):
        raise ValueError("not a PNG")
    out, at = [], len(SIGNATURE)
    while at < len(data):
        if at + 8 > len(data):
            raise ValueError("a chunk is cut short")
        length, kind = struct.unpack(">I4s", data[at : at + 8])
        body = data[at + 8 : at + 8 + length]
        crc = data[at + 8 + length : at + 12 + length]
        if len(body) != length or len(crc) != 4 or struct.unpack(">I", crc)[0] != zlib.crc32(kind + body):
            raise ValueError(f"the {kind!r} chunk is damaged")
        out.append((kind, body))
        at += 12 + length
    if not out or out[-1][0] != b"IEND":
        raise ValueError("no end")
    return out


def strip(data: bytes) -> bytes:
    """The PNG with only the chunks in KEEP."""
    kept = b"".join(
        struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))
        for kind, body in chunks(data)
        if kind in KEEP
    )
    return SIGNATURE + kept


def load_shots(path: Path) -> dict[str, Any]:
    """docs/screenshots.json, checked: unique names, known sites, and a path on the site."""
    config: dict[str, Any] = json.loads(path.read_text())
    names = [shot["name"] for shot in config["shots"]]
    if len(names) != len(set(names)):
        raise ValueError("a shot's name is used twice")
    for shot in config["shots"]:
        if shot["site"] not in SITES or not shot["path"].startswith("/"):
            raise ValueError(f"{shot['name']}: site must be one of {SITES}, and path must start with /")
        if not all(c.isalnum() or c == "-" for c in shot["name"]):
            raise ValueError(f"{shot['name']}: a name is letters, digits, and -")
    return config


def wait_for(page: Any, url: str, selector: str, timeout: int) -> None:
    """Loads the page every few seconds until the selector is on it, since the Dashboard's
    pages don't refresh themselves (the helper's answer arrives on Home later)."""
    import time

    deadline = time.monotonic() + timeout
    while True:
        page.goto(url)
        if page.locator(selector).count():
            return
        if time.monotonic() > deadline:
            raise TimeoutError(f"{selector} wasn't on {url} after {timeout} seconds")
        page.wait_for_timeout(5000)


def take(args: argparse.Namespace) -> None:
    from playwright.sync_api import sync_playwright  # type: ignore[import-not-found]  # only in its image

    config = load_shots(args.shots)
    dashboard = f"https://dashboard.{args.domain}:{args.dashboard_port}"
    grafana = f"https://grafana.{args.domain}:{args.https_port}"
    sources: dict[str, str] = {}
    with sync_playwright() as p:
        # Every name under the domain goes to this machine, whatever DNS says, so the browser
        # can't reach anything but the ok3d running here.
        browser = p.chromium.launch(args=[f"--host-resolver-rules=MAP *.{args.domain} 127.0.0.1"])
        for theme in THEMES:
            # The certificates are from ok3d's own authority, which this browser doesn't trust;
            # it only ever talks to this machine (above).
            context = browser.new_context(color_scheme=theme, viewport=config["viewport"], device_scale_factor=2,
                                          ignore_https_errors=True)  # fmt: skip
            page = context.new_page()
            page.goto(f"{grafana}/login")
            page.fill("input[name='user']", "admin")
            page.fill("input[name='password']", args.grafana_password.read_text().strip())
            page.click("button[type='submit']")
            page.wait_for_url(lambda url: "/login" not in url)
            signed_out = browser.new_context(color_scheme=theme, viewport=config["viewport"], device_scale_factor=2,
                                             ignore_https_errors=True).new_page()  # fmt: skip
            signed_in = False
            for shot in config["shots"]:
                on = page if shot.get("signed_in", True) else signed_out
                # A shot may want a wider window than the rest, such as a Grafana dashboard.
                on.set_viewport_size(shot.get("viewport", config["viewport"]))
                if shot["site"] == "dashboard" and shot.get("signed_in", True) and not signed_in:
                    page.goto(f"{dashboard}/sign-in")
                    page.fill("input[name='password']", args.dashboard_password.read_text().strip())
                    page.click("button")
                    page.wait_for_url(f"{dashboard}/")
                    signed_in = True
                if shot["site"] == "dashboard":
                    url = dashboard + shot["path"]
                else:
                    url = grafana + shot["path"] + ("&" if "?" in shot["path"] else "?") + f"theme={theme}"
                on.goto(url)
                for step in shot.get("before", []):
                    if "click" in step:
                        on.click(step["click"])
                        on.wait_for_load_state()
                    else:
                        wait_for(on, url, step["wait"], step.get("timeout", 30))
                on.goto(url)
                on.wait_for_selector(shot["wait"], timeout=60_000)
                on.wait_for_load_state("networkidle")
                # Grafana draws its panels after the data arrives.
                on.wait_for_timeout(3000 if shot["site"] == "grafana" else 300)
                target = on.locator(shot["crop"]).first if "crop" in shot else on
                name = f"{shot['name']}-{theme}.png"
                (args.out / name).write_bytes(strip(target.screenshot()))
                sources[name] = args.version
                print(f"images/screenshots/{name}", flush=True)
            context.close()
        browser.close()
    (args.out / "sources.json").write_text(json.dumps(sources, indent=2, sort_keys=True) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Takes the docs' screenshots (scripts/screenshots.sh runs this).")
    parser.add_argument("--shots", type=Path, required=True, help="docs/screenshots.json")
    parser.add_argument("--out", type=Path, required=True, help="where the pictures go")
    parser.add_argument("--version", required=True, help="the ok3d version they're taken with")
    parser.add_argument("--domain", required=True)
    parser.add_argument("--https-port", required=True)
    parser.add_argument("--dashboard-port", required=True)
    parser.add_argument("--dashboard-password", type=Path, required=True, help="a file holding it")
    parser.add_argument("--grafana-password", type=Path, required=True, help="a file holding it")
    take(parser.parse_args())


if __name__ == "__main__":
    main()
