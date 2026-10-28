"""The docs hold together: every link leads somewhere, every image says what it shows, and
the house style holds (no em or en dashes).

The vendored Grafana dashboards are left out of the style check: they're Grafana.com's text,
not ours.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENDORED = "manifests/monitoring/dashboards/"

# Markdown links and images: [text](target) and ![alt](target). HTML images: <img ... >.
LINK = re.compile(r"(!?)\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
HTML_IMG = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
HTML_ALT = re.compile(r"\balt=\"([^\"]*)\"", re.IGNORECASE)
HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
# The em dash and the en dash, built from their code points so this file doesn't contain them.
DASHES = re.compile(f"[{chr(0x2014)}{chr(0x2013)}]")


def tracked(pattern: str = "") -> list[str]:
    args = ["git", "ls-files", "-z"] + ([pattern] if pattern else [])
    out = subprocess.run(args, cwd=ROOT, capture_output=True, check=True).stdout
    return [name for name in out.decode().split("\0") if name and (ROOT / name).is_file()]


def slug(heading: str) -> str:
    """The anchor GitHub gives a heading: lower case, punctuation dropped, spaces to hyphens."""
    text = re.sub(r"`|\*|_(?=\w)|(?<=\w)_", "", heading.strip().lower())
    return re.sub(r"[^\w\- ]", "", text).replace(" ", "-")


def anchors(path: Path) -> set[str]:
    found: set[str] = set()
    counts: dict[str, int] = {}
    in_code = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("```"):
            in_code = not in_code
        match = None if in_code else HEADING.match(line)
        if match:
            base = slug(match.group(2))
            n = counts.get(base, 0)
            found.add(base if n == 0 else f"{base}-{n}")
            counts[base] = n + 1
    return found


def links(path: Path) -> list[tuple[str, str, str]]:
    """(is it an image, its text or alt, its target) for each link outside code blocks."""
    text = re.sub(r"```.*?```", "", path.read_text(encoding="utf-8"), flags=re.DOTALL)
    text = re.sub(r"`[^`\n]*`", "", text)
    return LINK.findall(text)


def test_every_link_leads_somewhere() -> None:
    broken = []
    for name in tracked("*.md"):
        source = ROOT / name
        for _, _, target in links(source):
            if re.match(r"^[a-z][a-z0-9+.-]*:", target):
                continue  # https:, mailto:, and other schemes are outside the repository
            path, _, fragment = target.partition("#")
            dest = (source.parent / path).resolve() if path else source
            if not dest.exists():
                broken.append(f"{name}: {target}")
            elif fragment and dest.suffix == ".md" and fragment not in anchors(dest):
                broken.append(f"{name}: {target} (no such heading)")
    assert not broken, f"links that lead nowhere: {broken}"


def test_every_image_says_what_it_shows() -> None:
    missing = []
    for name in tracked("*.md"):
        source = ROOT / name
        missing += [f"{name}: {target}" for is_image, alt, target in links(source) if is_image and not alt.strip()]
        for tag in HTML_IMG.findall(source.read_text(encoding="utf-8")):
            alt = HTML_ALT.search(tag)
            if not alt or not alt.group(1).strip():
                missing.append(f"{name}: {tag}")
    assert not missing, f"images without alt text: {missing}"


def test_no_em_or_en_dashes() -> None:
    found = []
    for name in tracked():
        if name.startswith(VENDORED):
            continue
        try:
            text = (ROOT / name).read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        found += [f"{name}:{n}" for n, line in enumerate(text.splitlines(), 1) if DASHES.search(line)]
    assert not found, f"em or en dashes (the house style uses commas, colons, or periods): {found}"


def test_slugs_match_github() -> None:
    assert slug("The review before 1.0") == "the-review-before-10"
    assert slug("0.3: Groundwork") == "03-groundwork"
    assert slug("North/south: `agentgateway`") == "northsouth-agentgateway"
