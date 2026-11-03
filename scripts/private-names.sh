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
# anything but 0 means don't post. patterns exits 3 only when there's no list at all (a fresh
# clone, or CI), and 2 when there's one it can't use: it can't be read, it has no pattern in it
# (emptied, or all comments), or a pattern isn't valid. The hooks skip the check on 3 and
# refuse the commit on 2, so a list that's there but broken never turns the check off.
#
# A line in the list is a pattern (grep -E, case ignored), and lines starting with # are
# comments. A line that's a plain name (letters, digits, spaces, - and _) also matches the
# ways it gets written: up to three other characters may stand between its parts, which
# are split at its own separators, where letters meet digits, and where a small letter meets
# a capital. So media-box matches media_box, mediabox, media.box, media - box, and Media Box;
# box9 matches box-9; and MediaBox matches media-box. List a name with its parts apart
# (media-box, not mediabox): a name written as one word can't be split. Anything else, like an
# address, is used as written. Matching is line by line, so a name broken across two lines
# isn't found here; tests/test_privacy.py, which reads whole files, finds it.
set -eu

usage() {
	echo "Usage: scripts/private-names.sh check FILE... | patterns" >&2
	exit 2
}

# Where the main repository's list is, from a worktree too, where .git is a file. Outside a
# git repository there's none.
list_file() {
	common=$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null) || return 0
	printf '%s\n' "$common/hooks/private-names"
}

# The list's lines, without comments and blanks. Windows line endings and trailing blanks are
# dropped, so a list edited anywhere matches the same.
list() {
	tr -d '\r' <"$1" | sed 's/[[:space:]]*$//' | grep -v -e '^#' -e '^[[:space:]]*$' || true
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
	file=$(list_file)
	if [ -z "$file" ] || { [ ! -e "$file" ] && [ ! -L "$file" ]; }; then
		return 3
	fi
	if [ ! -f "$file" ] || [ ! -r "$file" ]; then
		echo "Your private-names list (.git/hooks/private-names) can't be read, so nothing was checked." >&2
		return 2
	fi
	found=$(list "$file" | expand)
	if [ -z "$found" ]; then
		echo "Your private-names list (.git/hooks/private-names) has no pattern in it, so nothing was" >&2
		echo "checked. Put your names back in it, or delete it if you mean to have none." >&2
		return 2
	fi
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
		echo "There's no private-names list (.git/hooks/private-names), so nothing was checked." >&2
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
