#!/bin/sh
# Takes the docs' screenshots: every shot in docs/screenshots.json, in light and dark, saved to
# images/screenshots/<name>-<theme>.png, with images/screenshots/sources.json recording the
# ok3d version they were taken with. Run it on a throwaway machine, such as a test VM fresh
# from its snapshot, never on one watching a real network:
#
#   scripts/screenshots.sh --setup   # on a fresh machine: set ok3d up on the simulated network first
#   scripts/screenshots.sh           # ok3d is up on the simulated network already: just take them
#
# --setup makes settings.yaml from the example (with email alerts to a mail server on the
# simulated network, which isn't there, so nothing is ever sent), devices.yaml from the
# demo's, and .env with a stand-in mail password; starts the simulated network; builds the
# Dashboard's image from this checkout; runs ./ok3d install and ./ok3d apply; and waits for
# Grafana to have a few minutes of graphs. The data root must be there already, and yours.
#
# Either way, it refuses to run unless the settings use the stand-in domain noc.home.arpa and
# devices.yaml is the demo's, so a screenshot can't show a real network. The browser is
# Playwright's Chromium, from a container image pinned by digest, and it can reach only this
# machine. Look at every picture before committing them (CLAUDE.md).
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

if $setup; then
	for file in "$settings" "$devices" .env; do
		[ ! -e "$file" ] || stop "--setup is for a fresh machine, and $file is here already. Run without --setup to use it."
	done
	cp settings.example.yaml "$settings"
	cat >>"$settings" <<-'EOF'

		# From scripts/screenshots.sh: email alerts, to a mail server on the simulated network
		# that isn't there, so the Dashboard shows them on and nothing is ever sent.
		alerts:
		  email:
		    enabled: true
		    to: you@example.com
		    from: ok3d@example.com
		    smarthost: 198.51.100.25:25
		    username: ok3d
	EOF
	cp devices.demo.yaml "$devices"
	(umask 077 && printf 'SMTP_PASSWORD=a-stand-in-for-the-screenshots\n' >.env)
	chmod 600 "$settings"
fi

# What the settings say, read the simple way, since they're the example's.
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
docker run --rm --network host --ipc host --user "$(id -u):$(id -g)" --env HOME=/tmp \
	--volume "$PWD/docs/screenshots.json:/shots.json:ro" \
	--volume "$PWD/scripts/screenshots.py:/screenshots.py:ro" \
	--volume "$PWD/images/screenshots:/out" \
	--volume "$data_root/dashboard/password:/dashboard-password:ro" \
	--volume "$data_root/admin-password:/grafana-password:ro" \
	"$image" python3 -I /screenshots.py --shots /shots.json --out /out --version "$version" \
	--domain "$domain" --https-port "${https_port:-8443}" --dashboard-port "${dashboard_port:-8444}" \
	--dashboard-password /dashboard-password --grafana-password /grafana-password
echo "Done. Look at each picture in images/screenshots/ before committing them, with IMAGES_CHECKED=1."
