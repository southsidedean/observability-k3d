"""Nothing in the repository describes a real home network: examples use stand-ins.

The stand-ins are documentation and example values nobody's network uses for real:
192.168.1.0/24 (the usual home example), the RFC 5737 ranges (192.0.2.0/24, 198.51.100.0/24,
203.0.113.0/24), fd00::/48, my-server.lan, noc.home.arpa and its subdomains, Kubernetes'
own cluster.local names, and example.com addresses.

On your own machine, the patterns in .git/hooks/private-names (your host names, domains,
and addresses; never committed) are checked too.
"""

from __future__ import annotations

import ipaddress
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

ALLOWED_NETWORKS = [
    ipaddress.ip_network(n)
    for n in ("192.168.1.0/24", "192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24", "fd00::/48")
]
# Private and shared address space, where a real home network's addresses live. 100.64/10 is
# where Tailscale gives out addresses.
PRIVATE_NETWORKS = [
    ipaddress.ip_network(n)
    for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10", "fc00::/7")
]
ALLOWED_NAMES = re.compile(r"(^|\.)(my-server\.lan|noc\.home\.arpa|cluster\.local)$", re.IGNORECASE)
ALLOWED_EMAIL = re.compile(
    r"^(noreply@anthropic\.com|[\w.+-]+@users\.noreply\.github\.com|[\w.+-]+@example\.(com|org|net))$",
    re.IGNORECASE,
)

IPV4 = re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.]*\d)")
IPV6_ULA = re.compile(r"(?<![\w:])f[cd][0-9a-f]{2}:[0-9a-f:]*[0-9a-f]", re.IGNORECASE)
# Longer suffixes first, so "x.home.arpa" isn't read as "x.home".
LOCAL_NAME = re.compile(r"\b[\w.-]+\.(?:home\.arpa|ts\.net|internal|local|lan|home)\b(?!\.)", re.IGNORECASE)
# Ends in a top-level domain of letters, so "package@1.2.3" (a pinned version) isn't one.
EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)*\.[A-Za-z]{2,}\b")
HOME_PATH = re.compile(r"/(?:Users|home)/(?!ubuntu\b|runner\b|<)[\w.-]+")


# Files whose made-up private names and addresses are the point: these tests and the hook's
# tests feed them to the checks on purpose.
SAMPLE_FILES = {"tests/test_privacy.py", "tests/test_hooks.py"}


def tracked_text_files() -> dict[str, str]:
    """Every tracked file that's text, by path, with its contents (the sample files aside)."""
    names = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True
    ).stdout.split(b"\0")
    files = {}
    for name in filter(None, names):
        if name.decode() in SAMPLE_FILES:
            continue
        path = ROOT / name.decode()
        try:
            files[name.decode()] = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, FileNotFoundError, IsADirectoryError):
            continue  # images and other binary files
    return files


def private_addresses(text: str) -> list[str]:
    found = []
    for match in IPV4.findall(text) + IPV6_ULA.findall(text):
        try:
            address = ipaddress.ip_address(match)
        except ValueError:
            continue  # a version number that looks like an address, say
        if any(address in n for n in PRIVATE_NETWORKS) and not any(address in n for n in ALLOWED_NETWORKS):
            found.append(match)
    return found


def test_no_private_addresses() -> None:
    found = {path: hits for path, text in tracked_text_files().items() if (hits := private_addresses(text))}
    assert not found, f"use a stand-in such as 192.168.1.20 or 192.0.2.10 instead: {found}"


def test_no_local_host_names() -> None:
    found = {
        path: hits
        for path, text in tracked_text_files().items()
        if (hits := [n for n in LOCAL_NAME.findall(text) if not ALLOWED_NAMES.search(n)])
    }
    assert not found, f"use a stand-in such as my-server.lan or noc.home.arpa instead: {found}"


def test_no_personal_email_addresses() -> None:
    found = {
        path: hits
        for path, text in tracked_text_files().items()
        if (hits := [e for e in EMAIL.findall(text) if not ALLOWED_EMAIL.match(e)])
    }
    assert not found, f"use an example.com address instead: {found}"


def test_no_home_folders() -> None:
    found = {path: hits for path, text in tracked_text_files().items() if (hits := HOME_PATH.findall(text))}
    assert not found, f"use a placeholder such as ~/ok3d instead of a real home folder: {found}"


def test_nothing_from_the_private_names_list() -> None:
    names_file = ROOT / ".git" / "hooks" / "private-names"
    if not names_file.is_file():
        return  # CI and fresh clones have no list; the generic checks above still ran
    patterns = [
        line.strip()
        for line in names_file.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    files = tracked_text_files()
    found = {
        pattern: [path for path, text in files.items() if re.search(pattern, text, re.IGNORECASE)]
        for pattern in patterns
    }
    found = {pattern: paths for pattern, paths in found.items() if paths}
    assert not found, f"private names in tracked files: {found}"


def test_the_checks_catch_what_they_should() -> None:
    # The patterns themselves, against made-up text, so a broken pattern can't pass silently.
    assert private_addresses("ssh 192.168.77.5 and 10.0.0.1 and 100.101.102.103")
    assert not private_addresses("example 192.168.1.20, docs 192.0.2.10, version 1.37.1, k3s 0.0.0.0")
    assert private_addresses("fd12:3456::1")
    assert not private_addresses("fd00::5")
    names = [n for n in LOCAL_NAME.findall("nas.lan my-server.lan grafana.noc.home.arpa x.ts.net")]
    assert [n for n in names if not ALLOWED_NAMES.search(n)] == ["nas.lan", "x.ts.net"]
    assert HOME_PATH.findall("/Users/someone/projects and /home/ubuntu/ok3d") == ["/Users/someone"]
