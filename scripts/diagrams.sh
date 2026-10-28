#!/bin/sh
# Renders the docs' diagrams: each docs/diagrams/<name>.mmd (Mermaid) becomes
# images/diagrams/<name>-light.png and <name>-dark.png, which the docs show with a <picture>
# tag, so GitHub picks the one for the reader's theme. Images rather than Mermaid blocks:
# they look the same everywhere, a blog post or a printout included.
#
# mermaid-cli runs from a container image pinned by digest, so every machine draws the same
# picture. Needs Docker. Run it after changing a diagram:
#   scripts/diagrams.sh
#
# Each source's SHA-256 goes in images/diagrams/sources.json. tests/test_docs.py fails when an
# image no longer matches its source, or has no source.
set -eu
cd "$(dirname "$0")/.."

# mermaid-cli 12.0.0. Renovate proposes newer versions.
image=minlag/mermaid-cli:12.0.0@sha256:fa995339034aae7e5cd4f61482248b7f5c51be355b1a6f6eda11a2bbf8401f5f

sha256() {
	if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1"; else shasum -a 256 "$1"; fi | cut -d' ' -f1
}

mkdir -p images/diagrams
manifest=images/diagrams/sources.json
printf '{\n' >"$manifest.tmp"
first=true
for src in docs/diagrams/*.mmd; do
	name=$(basename "$src" .mmd)
	for theme in light dark; do
		# The light version on white, the dark one on GitHub's dark background, each at twice
		# the size so text stays sharp on high-density screens.
		if [ "$theme" = light ]; then mermaid_theme=default background=white; else mermaid_theme=dark background='#0d1117'; fi
		docker run --rm --user "$(id -u):$(id -g)" --volume "$PWD:/data" "$image" \
			--quiet --theme "$mermaid_theme" --backgroundColor "$background" --scale 2 \
			--input "/data/$src" --output "/data/images/diagrams/$name-$theme.png"
		echo "images/diagrams/$name-$theme.png"
	done
	$first || printf ',\n' >>"$manifest.tmp"
	first=false
	printf '  "%s": "%s"' "$src" "$(sha256 "$src")" >>"$manifest.tmp"
done
printf '\n}\n' >>"$manifest.tmp"
mv "$manifest.tmp" "$manifest"
