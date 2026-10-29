#!/bin/sh
# Every check that doesn't need a cluster, the same ones CI runs: the shell scripts, the
# Python's lint, security, and type checks, the workflows, Renovate's settings, the tests
# (privacy, docs, the git hooks, the charts, and the ok3d command among them), and the
# charts' objects. The pre-push hook runs it; run it yourself
# any time:
#   scripts/check.sh
#
# Needs python3 with the dev tools installed (python3 -m pip install -e '.[dev]', ideally in
# a .venv, which this script uses when it finds one), plus shellcheck, actionlint, npx, helm,
# and kubeconform. The alert rules' and Alertmanager's tests also use promtool and amtool
# (CONTRIBUTING.md says where to get the versions ok3d runs); without them, those tests skip.
# A tool that isn't installed here is skipped with a note; CI sets CI=true, which turns a
# missing tool into a failure, so nothing is skipped there.
set -eu
cd "$(dirname "$0")/.."

# The Python to use: the project's .venv if there is one, so the pinned tools are found.
python=python3
[ -x .venv/bin/python ] && python=.venv/bin/python

failures=0
pass() { echo "PASS  $1"; }
fail() {
	echo "FAIL  $1"
	failures=$((failures + 1))
}
missing() {
	if [ "${CI:-}" = true ]; then
		fail "$1 (not installed)"
	else
		echo "SKIP  $1: not installed here; CI runs it"
	fi
}
# has_module NAME: whether the chosen Python can run "python -m NAME".
has_module() { "$python" -c "import importlib.util, sys; sys.exit(importlib.util.find_spec('$1') is None)" 2>/dev/null; }
# tool NAME: prints the command's path, from the .venv first, then PATH; nothing if missing.
tool() {
	if [ -x ".venv/bin/$1" ]; then echo ".venv/bin/$1"; elif command -v "$1" >/dev/null 2>&1; then echo "$1"; fi
}

# 1. The shell scripts are POSIX sh and shellcheck clean.
if command -v shellcheck >/dev/null 2>&1; then
	if shellcheck -s sh ok3d install.sh scripts/check.sh scripts/diagrams.sh .githooks/*; then
		pass "1. the shell scripts are shellcheck clean"
	else
		fail "1. shellcheck found problems (above)"
	fi
else
	missing "1. shell scripts (shellcheck)"
fi

# 2. ruff: bugs and risky code, with the rules in pyproject.toml.
if has_module ruff; then
	if "$python" -m ruff check src tests scripts; then pass "2. ruff"; else fail "2. ruff (above)"; fi
else
	missing "2. ruff"
fi

# 3. bandit: security problems in the package's own code.
if has_module bandit; then
	if "$python" -m bandit -q -c pyproject.toml -r src; then pass "3. bandit"; else fail "3. bandit (above)"; fi
else
	missing "3. bandit"
fi

# 4. mypy, strict: types, for the package and the tests.
if has_module mypy; then
	if "$python" -m mypy; then pass "4. mypy"; else fail "4. mypy (above)"; fi
else
	missing "4. mypy"
fi

# 5. zizmor: the workflows' security (pinned actions, permissions, injection).
zizmor=$(tool zizmor)
if [ -n "$zizmor" ]; then
	if "$zizmor" --offline --min-severity medium .github/workflows; then
		pass "5. zizmor"
	else
		fail "5. zizmor (above)"
	fi
else
	missing "5. zizmor"
fi

# 6. actionlint: mistakes in the workflows that zizmor doesn't look for.
if command -v actionlint >/dev/null 2>&1; then
	if actionlint; then pass "6. actionlint"; else fail "6. actionlint (above)"; fi
else
	missing "6. actionlint"
fi

# 7. Renovate's settings are valid. The version is pinned, so the check doesn't change under
# us; Renovate itself proposes moving it.
if command -v npx >/dev/null 2>&1; then
	if npx --yes --package renovate@44.155.1 -- renovate-config-validator --strict >/dev/null 2>&1; then
		pass "7. renovate.json5 is valid"
	else
		fail "7. renovate.json5 isn't valid: npx --package renovate@44.155.1 -- renovate-config-validator --strict"
	fi
else
	missing "7. Renovate's settings (npx)"
fi

# 8. The tests: privacy, docs, the git hooks, and every part's own tests.
if has_module pytest; then
	if "$python" -m pytest -q; then pass "8. the tests"; else fail "8. the tests (above)"; fi
else
	missing "8. the tests (pytest)"
fi

# fetch_chart_dependencies: both charts' dependencies, at the versions in their Chart.lock
# files, unless they're already here.
fetch_chart_dependencies() {
	for chart in chart/ok3d-platform chart/ok3d; do
		helm dependency list "$chart" 2>/dev/null | grep -q -e missing -e "wrong version" || continue
		helm repo add jetstack https://charts.jetstack.io --force-update >/dev/null &&
			helm repo add prometheus-community https://prometheus-community.github.io/helm-charts --force-update >/dev/null &&
			helm dependency build "$chart" >/dev/null || return 1
	done
}

# 9. The charts: both lint, and every object they render is valid for the cluster's
# Kubernetes version, the custom resources too (checked against the CRDs catalog). The
# platform chart's dependencies are fetched first, at the versions in its Chart.lock.
# cert-manager's own CustomResourceDefinitions are skipped: there's no schema to check them
# against, and cert-manager's chart validates them upstream.
if command -v helm >/dev/null 2>&1 && command -v kubeconform >/dev/null 2>&1; then
	k8s=$(sed -n 's/^  k3sImage: rancher\/k3s:v\([0-9.]*\)-.*/\1/p' chart/ok3d/values.yaml)
	if fetch_chart_dependencies &&
		helm lint --strict chart/ok3d --values settings.example.yaml >/dev/null &&
		helm lint chart/ok3d-platform >/dev/null &&
		{
			helm template ok3d chart/ok3d --namespace monitoring --values settings.example.yaml --values devices.demo.yaml
			helm template ok3d-platform chart/ok3d-platform --namespace cert-manager
		} | kubeconform -strict -summary -kubernetes-version "$k8s" -skip CustomResourceDefinition \
			-schema-location default \
			-schema-location 'https://raw.githubusercontent.com/datreeio/CRDs-catalog/main/{{.Group}}/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json'; then
		pass "9. the charts lint, and every object is valid Kubernetes $k8s"
	else
		fail "9. the charts (above)"
	fi
else
	missing "9. the charts (helm and kubeconform)"
fi

if [ "$failures" -gt 0 ]; then
	echo "$failures check(s) failed."
	exit 1
fi
echo "All checks passed."
