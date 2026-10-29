#!/bin/sh
# Finds your private names (host names, domains, addresses) in text, from the list in
# .git/hooks/private-names, which stays on your machine. The pre-commit hook uses it on what a
# commit adds, and you use it on a pull request's text or release notes before posting them:
#
#   scripts/private-names.sh check FILE...   # exits 0 only when every file is clean
#   scripts/private-names.sh patterns        # the patterns it matches with, one a line
#
# check says only which file and line matched, never the text, so a match isn't shown
# wherever the output goes. It exits 1 on a match, and 2 when it can't check at all (no
# list, a list with no patterns, or a file it can't read), so "not 0" always means don't post.
#
# A line in the list is a pattern (grep -E, case ignored), and lines starting with # are
# comments. A line that's a plain name (letters, digits, spaces, - and _) also matches the
# ways it gets written: media-box matches media_box, mediabox, media.box, and Media Box, and
# box9 matches box-9. Anything else is used as written.
set -eu

usage() {
	echo "Usage: scripts/private-names.sh check FILE... | patterns" >&2
	exit 2
}

# The main repository's list, from a worktree too, where .git is a file.
list() {
	common=$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null) || return 0
	[ -f "$common/hooks/private-names" ] || return 0
	grep -v -e '^#' -e '^[[:space:]]*$' "$common/hooks/private-names" || true
}

# Each plain name, with an optional separator wherever it has one and wherever letters
# change to digits or back.
patterns() {
	list | awk -v sep='[-_. ]?' '
		/^[A-Za-z0-9 _-]+$/ {
			out = ""; prev = ""; gap = 0
			for (i = 1; i <= length($0); i++) {
				c = substr($0, i, 1)
				if (c ~ /[ _-]/) { gap = 1; continue }
				if (out != "" && (gap || (prev ~ /[A-Za-z]/ && c ~ /[0-9]/) || (prev ~ /[0-9]/ && c ~ /[A-Za-z]/)))
					out = out sep
				out = out c; prev = c; gap = 0
			}
			print out
			next
		}
		{ print }'
}

case "${1:-}" in
patterns)
	[ $# -eq 1 ] || usage
	found=$(patterns)
	[ -n "$found" ] || exit 1
	printf '%s\n' "$found"
	;;
check)
	shift
	[ $# -gt 0 ] || usage
	found=$(patterns)
	if [ -z "$found" ]; then
		echo "There's no private-names list with a pattern in it, so nothing was checked." >&2
		exit 2
	fi
	status=0
	for file in "$@"; do
		if [ ! -r "$file" ] || [ -d "$file" ]; then
			echo "$file: can't read it" >&2
			status=2
			continue
		fi
		# One pattern at a time, so a bad pattern in the list can't hide the others.
		lines=$(printf '%s\n' "$found" | while IFS= read -r pattern; do
			grep -n -I -i -E -e "$pattern" "$file" | cut -d: -f1 || true
		done | sort -n -u | tr '\n' ' ')
		if [ -n "$lines" ]; then
			echo "$file: a private name on line ${lines% }" >&2
			[ "$status" -eq 2 ] || status=1
		fi
	done
	exit "$status"
	;;
*) usage ;;
esac
