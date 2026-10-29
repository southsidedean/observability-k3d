#!/bin/sh
# Takes the docs' screenshots: every shot in docs/screenshots.json, in light and dark, saved to
# images/screenshots/<name>-<theme>.png, with images/screenshots/sources.json recording the
# ok3d version they were taken with. Run it on a throwaway machine, such as a test VM fresh
# from its snapshot, never on one watching a real network:
#
#   scripts/screenshots.sh --setup   # on a fresh machine: set ok3d up on the simulated network first
#   scripts/screenshots.sh           # ok3d is up on the simulated network already: just take them
#
# --setup makes settings.yaml from the example and devices.yaml from the demo's; starts the
# simulated network; builds the Dashboard's image from this checkout; runs ./ok3d install and
# ./ok3d apply; and waits for Grafana to have a few minutes of graphs. It switches no alerts on:
# with nowhere real to send them, Alertmanager would fire alerts about failing to send, and
# they'd show in Grafana. The data root must be there already, and yours.
#
# Either way, it refuses to run unless settings.yaml is exactly what --setup makes and
# devices.yaml is the demo's, so a screenshot can't show a real network, address, or name. The
# browser is Playwright's Chromium, from a container image pinned by digest; every name under
# the domain goes to this machine, and every other name fails. It writes your home folder as
# ~ in what it shows, and stops if a home folder is still on a page. Look at every picture
# before committing them (CLAUDE.md).
set -eu
cd "$(dirname "$0")/.."

# Playwright 1.64.0 for Python, on Ubuntu 24.04, for amd64 and arm64. Renovate proposes newer versions.
image=mcr.microsoft.com/playwright/python:v1.64.0-noble@sha256:684df257a1fa0ef3fa288239819984008f560e8f8db5b635ee9e2a50cbcd2e23
settings=${OK3D_SETTINGS:-settings.yaml}
devices=${OK3D_DEVICES:-devices.yaml}
# How long Grafana gets to collect something to draw, after a new Apply, in seconds.
graphs_wait=${OK3D_SCREENSHOTS_WAIT:-600}

stop() {
	printf '%s\n' "$*" >&2
	exit 1
}

case "${1:-}" in
--setup) setup=true ;;
"") setup=false ;;
*) stop "Usage: scripts/screenshots.sh [--setup]" ;;
esac
command -v docker >/dev/null 2>&1 || stop "This needs Docker."

# The settings --setup makes: the example's, as they are.
screenshot_settings() {
	cat settings.example.yaml
}

if $setup; then
	for file in "$settings" "$devices" .env; do
		[ ! -e "$file" ] || stop "--setup is for a fresh machine, and $file is here already. Run without --setup to use it."
	done
	screenshot_settings >"$settings"
	cp devices.demo.yaml "$devices"
	chmod 600 "$settings"
fi

# Exactly the settings --setup makes, so nothing of a real network (an email address, a
# server, a domain) can be in the Settings or Setup pictures.
screenshot_settings | cmp -s - "$settings" ||
	stop "$settings isn't the one scripts/screenshots.sh --setup makes: screenshots are taken only on the simulated network."
# What the settings say, read the simple way, since they're exactly the ones above.
setting() { sed -n "s/^$1: *//p" "$settings" | head -n 1 | sed "s/^[\"']//; s/[\"'] *\$//; s/ *#.*//"; }
domain=$(setting '  domain')
data_root=$(setting '  dataRoot')
https_port=$(setting '    https')
dashboard_port=$(setting '    dashboard')
[ "$domain" = noc.home.arpa ] ||
	stop "The settings' domain is ${domain:-not set}, not noc.home.arpa: screenshots are taken only on the simulated network."
cmp -s "$devices" devices.demo.yaml ||
	stop "$devices isn't devices.demo.yaml: screenshots are taken only on the simulated network."
[ -n "$data_root" ] || stop "The settings have no host.dataRoot."

if $setup; then
	./ok3d demo up
	docker build --quiet --file Dockerfile.dashboard --tag ok3d-dashboard:screenshots . >/dev/null
	OK3D_DASHBOARD_IMAGE=ok3d-dashboard:screenshots ./ok3d install
	./ok3d apply
	echo "Waiting $graphs_wait seconds, so Grafana has something to draw."
	sleep "$graphs_wait"
fi

for file in "$data_root/dashboard/password" "$data_root/admin-password"; do
	[ -r "$file" ] || stop "There's no $file: is ok3d installed and applied here? (scripts/screenshots.sh --setup does both.)"
done
version=$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' src/ok3d/__init__.py)
mkdir -p images/screenshots
# --network host, so the browser reaches the Dashboard and the gateway on this machine; it's
# told to send every name under the domain here (scripts/screenshots.py).
# The image has the browsers but not Playwright's Python package, which goes in first, at the
# versions and hashes in scripts/screenshots-requirements.txt.
docker run --rm --network host --ipc host --user "$(id -u):$(id -g)" --env HOME=/tmp \
	--volume "$PWD/docs/screenshots.json:/shots.json:ro" \
	--volume "$PWD/scripts/screenshots.py:/screenshots.py:ro" \
	--volume "$PWD/scripts/screenshots-requirements.txt:/requirements.txt:ro" \
	--volume "$PWD/images/screenshots:/out" \
	--volume "$data_root/dashboard/password:/dashboard-password:ro" \
	--volume "$data_root/admin-password:/grafana-password:ro" \
	"$image" sh -c 'python3 -m pip install --quiet --disable-pip-version-check --no-deps --require-hashes \
		--only-binary :all: --target /tmp/packages --requirement /requirements.txt &&
		PYTHONPATH=/tmp/packages exec python3 -P /screenshots.py "$@"' screenshots \
	--shots /shots.json --out /out --version "$version" \
	--domain "$domain" --https-port "${https_port:-8443}" --dashboard-port "${dashboard_port:-8444}" \
	--home-folder "$HOME" --dashboard-password /dashboard-password --grafana-password /grafana-password
echo "Done. Look at each picture in images/screenshots/ before committing them, with IMAGES_CHECKED=1."
