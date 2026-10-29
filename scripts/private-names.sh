#!/bin/sh
# Finds your private names (host names, domains, addresses) in text, from the list in
# .git/hooks/private-names, which stays on your machine. The git hooks use it on every
# commit, and you use it on a pull request's text or release notes before posting them:
#
#   scripts/private-names.sh check FILE...   # exits 0 only when every file is clean
#   scripts/private-names.sh patterns        # the patterns it matches with, one a line
#
# check says only which file and line matched, never the text, so a match isn't shown
# wherever the output goes. It exits 1 on a match, and 2 when it couldn't check (no list, a
# list with no patterns, a pattern that isn't a valid regex, or a file it can't read), so
# anything but 0 means don't post. patterns exits 3 when there's no list or no pattern in it
# (a fresh clone, or CI), and 2 when a pattern isn't valid.
#
# A line in the list is a pattern (grep -E, case ignored), and lines starting with # are
# comments. A line that's a plain name (letters, digits, spaces, - and _) also matches the
# ways it gets written: up to three other characters may stand between its parts, which
# are split at its own separators, where letters meet digits, and where a small letter meets
# a capital. So media-box matches media_box, mediabox, media.box, media - box, and Media Box;
# box9 matches box-9; and MediaBox matches media-box. List a name with its parts apart
# (media-box, not mediabox): a name written as one word can't be split. Anything else, like an
# address, is used as written.
set -eu

usage() {
	echo "Usage: scripts/private-names.sh check FILE... | patterns" >&2
	exit 2
}

# The main repository's list, from a worktree too, where .git is a file. Windows line endings
# and trailing blanks are dropped, so a list edited anywhere matches the same.
list() {
	common=$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null) || return 0
	[ -f "$common/hooks/private-names" ] || return 0
	tr -d '\r' <"$common/hooks/private-names" | sed 's/[[:space:]]*$//' |
		grep -v -e '^#' -e '^[[:space:]]*$' || true
}

# Each plain name, with room for up to three other characters between its parts. The class is
# written out (not [:alnum:]) so Python's re, in tests/test_privacy.py, reads it the same way.
expand() {
	awk -v sep='[^A-Za-z0-9]{0,3}' '
		/^[A-Za-z0-9 _-]+$/ {
			out = ""; prev = ""; gap = 0
			for (i = 1; i <= length($0); i++) {
				c = substr($0, i, 1)
				if (c ~ /[ _-]/) { gap = 1; continue }
				if (out != "" && (gap || (prev ~ /[A-Za-z]/ && c ~ /[0-9]/) ||
					(prev ~ /[0-9]/ && c ~ /[A-Za-z]/) || (prev ~ /[a-z]/ && c ~ /[A-Z]/)))
					out = out sep
				out = out c; prev = c; gap = 0
			}
			if (out != "") print out
			next
		}
		{ print }'
}

# The patterns, each checked as a regex first: grep says 2 for one it can't read, and a
# pattern that can't be read matches nothing, so it would pass everything.
patterns() {
	found=$(list | expand)
	[ -n "$found" ] || return 3
	while IFS= read -r pattern; do
		valid=0
		printf '' | grep -E -e "$pattern" >/dev/null 2>&1 || valid=$?
		if [ "$valid" -gt 1 ]; then
			echo "A pattern in your private-names list isn't a valid regex (grep -E), so nothing was checked." >&2
			return 2
		fi
	done <<EOF
$found
EOF
	printf '%s\n' "$found"
}

case "${1:-}" in
patterns)
	[ $# -eq 1 ] || usage
	status=0
	patterns || status=$?
	exit "$status"
	;;
check)
	shift
	[ $# -gt 0 ] || usage
	status=0
	found=$(patterns) || status=$?
	if [ "$status" -eq 3 ]; then
		echo "There's no private-names list with a pattern in it, so nothing was checked." >&2
		exit 2
	fi
	[ "$status" -eq 0 ] || exit 2
	for file in "$@"; do
		if [ ! -f "$file" ] || [ ! -r "$file" ]; then
			echo "$file: can't read it" >&2
			status=2
			continue
		fi
		# One pattern at a time, so a bad pattern can't hide the others. LC_ALL=C and -a, so a
		# byte that isn't valid UTF-8 doesn't make grep take the file for binary and skip it.
		lines=""
		while IFS= read -r pattern; do
			hit=0
			matched=$(LC_ALL=C grep -n -a -i -E -e "$pattern" -- "$file" </dev/null) || hit=$?
			if [ "$hit" -gt 1 ]; then
				echo "$file: grep couldn't read it" >&2
				status=2
			elif [ "$hit" -eq 0 ]; then
				lines="$lines $(printf '%s\n' "$matched" | cut -d: -f1 | tr '\n' ' ')"
			fi
		done <<EOF
$found
EOF
		if [ -n "$(printf '%s' "$lines" | tr -d ' ')" ]; then
			# shellcheck disable=SC2086 # one line number per word, on purpose
			lines=$(printf '%s\n' $lines | sort -n -u | tr '\n' ' ')
			echo "$file: a private name on line ${lines% }" >&2
			[ "$status" -eq 2 ] || status=1
		fi
	done
	exit "$status"
	;;
*) usage ;;
esac
