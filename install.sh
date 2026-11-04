#!/bin/sh
# Installs ok3d on this server, ready to set up from the Dashboard:
#
#   curl -fsSL https://raw.githubusercontent.com/southsidedean/observability-k3d/main/install.sh | sh
#
# It checks out the latest release of ok3d into ~/ok3d, makes settings.yaml from
# settings.example.yaml if you have none, and runs ./ok3d install, which starts the helper and
# the Dashboard and prints the Dashboard's address (and its password, when the output is a
# terminal). Run again on the same release, it installs that release again.
#
# To move to a newer release, use ./ok3d upgrade (or Upgrade now on the Dashboard's Home): it
# checks that the release's tag is signed by a key in deploy/release-signers and makes the
# cluster again, and this doesn't. So for a checkout that has ./ok3d upgrade (0.5.1 and newer),
# this refuses to move it and says so. One from before 0.5.1 has no upgrade command, so this
# brings it up to the release instead (docs/upgrading.md).
#
# What it reads, all optional:
#   OK3D_DIR        where ok3d goes (default ~/ok3d)
#   OK3D_VERSION    a release tag such as v0.5.0, or main (default: the latest release)
#   OK3D_DATA_ROOT  the data root, for a new settings.yaml (default /srv/ok3d)
#   OK3D_REPO       where to get ok3d from (default: its GitHub repository)
#
# It never uses sudo, and never needs a terminal. When something needs sudo (the data root,
# say), it says what to run.
#
# Everything is inside main(), called on the last line, so a download cut short runs nothing.
set -eu

main() {
repo=${OK3D_REPO:-https://github.com/southsidedean/observability-k3d.git}
dir=${OK3D_DIR:-${HOME:?HOME is not set: set OK3D_DIR to where ok3d should go}/ok3d}
data_root=${OK3D_DATA_ROOT:-/srv/ok3d}

say() { printf '%s\n' "$*"; }
stop() {
	printf '%s\n' "$*" >&2
	exit 1
}

for tool in git docker; do
	command -v "$tool" >/dev/null 2>&1 || stop "ok3d needs $tool. Install it, then run this again."
done
[ "$(id -u)" != 0 ] || stop "Run this as yourself, not as root: ok3d runs as you."

# The release: the newest vX.Y.Z tag (not a test tag like v1.2.3-rc1), unless you named one.
version=${OK3D_VERSION:-}
if [ -z "$version" ]; then
	version=$(git ls-remote --tags --refs "$repo" 'v*' |
		sed -n 's#.*refs/tags/\(v[0-9]\{1,6\}\.[0-9]\{1,6\}\.[0-9]\{1,6\}\)$#\1#p' |
		sort -t. -k1.2,1n -k2,2n -k3,3n | tail -n 1)
	[ -n "$version" ] || stop "Couldn't find ok3d's releases at $repo."
fi
case "$version" in
*[!a-z0-9.]*) stop "OK3D_VERSION should be a release tag such as v0.5.0, or main." ;;
main | v[0-9]*.[0-9]*.[0-9]*) ;;
*) stop "OK3D_VERSION should be a release tag such as v0.5.0, or main." ;;
esac

if [ -d "$dir/.git" ]; then
	if [ ! -f "$dir/ok3d" ] || ! grep -q '^# ok3d: ' "$dir/ok3d"; then
		stop "$dir is a git checkout, but not of ok3d. Move it, or set OK3D_DIR to another folder."
	fi
	[ -z "$(git -C "$dir" status --porcelain --untracked-files=no)" ] ||
		stop "$dir has changes of yours to ok3d's own files. Commit or stash them first (your settings are safe: they're not ok3d's)."
	at=$(git -C "$dir" describe --tags --exact-match HEAD 2>/dev/null || true)
	if [ "$version" != main ] && [ "$at" = "$version" ]; then
		say "$dir is on ok3d $version already."
	elif [ "$version" != main ] && grep -q '^upgrade)' "$dir/ok3d"; then
		stop "$dir has ok3d ${at:-from a branch}. To move it to $version, run ./ok3d upgrade there (or press
Upgrade now on the Dashboard's Home): it checks the release's signature and makes the cluster
again, and this installer doesn't."
	else
		say "Bringing $dir up to ok3d $version."
		# From the same place the version came from, whatever the checkout's origin is.
		if [ "$version" = main ]; then
			git -C "$dir" fetch --quiet "$repo" main
		else
			git -C "$dir" fetch --quiet "$repo" "refs/tags/$version:refs/tags/$version"
		fi
		# The tag by its full name, so a branch called the same can't be taken instead.
		git -C "$dir" -c advice.detachedHead=false checkout --quiet \
			"$([ "$version" = main ] && echo FETCH_HEAD || echo "refs/tags/$version")"
	fi
elif [ -e "$dir" ]; then
	stop "$dir is there already and isn't an ok3d checkout. Move it, or set OK3D_DIR to another folder."
else
	say "Getting ok3d $version into $dir."
	git clone --quiet --branch "$version" -c advice.detachedHead=false "$repo" "$dir"
fi
cd "$dir"
grep -q '^install)' ok3d || stop "ok3d $version has no installer; use v0.5.0 or newer."

if [ ! -f settings.yaml ]; then
	case "$data_root" in
	/*) ;;
	*) stop "OK3D_DATA_ROOT should be a full path, such as /srv/ok3d." ;;
	esac
	case "$data_root" in
	*[!A-Za-z0-9._/-]*) stop "OK3D_DATA_ROOT can have only letters, digits, and . _ / -." ;;
	esac
	sed "s#^  dataRoot: .*#  dataRoot: $data_root#" settings.example.yaml >settings.yaml
	chmod 600 settings.yaml
	say "Made settings.yaml, with the data root $data_root. You can change the rest on the Dashboard."
fi

data_root=$(sed -n 's/^  dataRoot: *//p' settings.yaml | head -n 1 | sed "s/^[\"']//; s/[\"']\$//")
if [ ! -d "$data_root" ] || [ ! -w "$data_root" ]; then
	stop "The data root $data_root needs to be there, and yours. Run this, then run the installer again:
  sudo install -d -o $(id -un) -m 0755 $data_root"
fi

exec ./ok3d install
}

main "$@"
