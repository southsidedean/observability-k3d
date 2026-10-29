# Contributing

Thanks for helping. This page covers setting up, making a change, the checks it has to
pass, and how releases happen. [PLAN.md](PLAN.md) has the roadmap and the reasons behind
each decision.

## Setting up

You need git, Python 3.12 or newer, and shellcheck. For the workflow checks, also
[actionlint](https://github.com/rhysd/actionlint) and Node.js (for `npx`).

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
git config core.hooksPath .githooks
```

For the alert rules' and Alertmanager's tests, put promtool (from Prometheus v3.15.0) and
amtool (from Alertmanager v0.34.1) in `.venv/bin/`, from their releases on GitHub; the tests
skip without them, and CI always has them.

The last line turns on the git hooks. Before each commit, they refuse a commit on `main`,
your own settings files, secrets, private names, and images nobody has looked at. Before
each push, they run every check.

### Your private names

Make a file at `.git/hooks/private-names` with your own host names, domains, and addresses,
one pattern per line (`#` starts a comment). It stays on your machine. The pre-commit hook
and the privacy tests refuse anything that matches it:

```text
# my own names
myserver
mydomain\.example
192\.168\.42\.
```

In the repository, examples use stand-ins instead: addresses like `192.168.1.20`,
`192.0.2.10`, and `fd00::5`, and names like `my-server.lan` and `noc.home.arpa`.

## Making a change

1. Make a branch from `main`, one per change.
2. Write the change, with its tests. A bug fix starts with a test that fails without the fix.
3. Comment the code and configuration. Each file starts by saying what it's for, and
   comments say why wherever the code doesn't make it obvious. That goes for scripts,
   Python, chart templates, values, the settings schema, alert rules, dashboards, and
   workflows.
4. Update the docs in the same pull request. That includes the "under the hood" pages when
   the code they describe changes.
5. Add a line to `CHANGELOG.md`, under the next version, if users will notice the change,
   and update `docs/roadmap.md` with what the change finishes, starts, or changes.
6. Stage files by name (`git add path/to/file`), never with `git add -A`, so nothing
   untracked goes in by mistake.
7. Run `scripts/check.sh`. The pre-push hook runs it too.
8. Open a pull request. Every pull request gets an independent review before it merges.

### Writing

Docs and everything else people read are written for someone with some computer skills who
isn't an expert: plain words, short sentences, steps before reasons. No em or en dashes. Text
people read (docs, comments, commit messages, pull request descriptions, release notes, and
the Dashboard's own words) is reviewed for AI writing patterns before it's committed. The
`humanizer` skill for Claude Code does this.

### Pictures

Diagrams start as Mermaid files in `docs/diagrams/` and are rendered to PNG by a script.
Screenshots are taken by a script on the test VM, using the simulated network, never a real
one. Look at every image before committing it, strip its metadata, and commit with
`IMAGES_CHECKED=1`. Every image in the docs has alt text that says what it shows.

## The checks

`scripts/check.sh` runs everything that doesn't need a cluster, the same checks CI runs:

| Check | What it looks at |
|---|---|
| shellcheck | the scripts and git hooks, as POSIX `sh` |
| ruff, bandit, mypy | the Python: bugs, security problems, and types (strict) |
| zizmor, actionlint | the GitHub workflows |
| Renovate's validator | `renovate.json5` |
| pytest | the tests, including privacy (no real network details), docs (links, alt text, style), the git hooks, and the network fence that keeps tests offline |

CI also runs CodeQL, dependency review on pull requests, and OpenSSF Scorecard.

## The test VM

Changes that need a cluster are tested on a VM made from
[tests/vm/cloud-init.yaml](tests/vm/cloud-init.yaml): a generic Ubuntu server with ok3d's
prerequisites. Take a snapshot called `base` right after making it, and restore it before
each install test or screenshot run, so each one starts clean. The file's comments have the
commands.

## Releasing

1. User-facing changes collect in `CHANGELOG.md` under the next version, marked unreleased.
2. A release pull request sets the version (`src/ok3d/__init__.py`, and `version` and
   `appVersion` in `chart/ok3d/Chart.yaml` and `chart/ok3d-platform/Chart.yaml`), the date
   in the changelog, and the release's status in `docs/roadmap.md`.
3. After it merges: a signed tag (`git tag -s vX.Y.Z`), then `gh release create` with that
   version's changelog section as the notes.
4. Check that the Dashboard's image (and, once it exists, the in-cluster one) was published
   for amd64 and arm64, and scanned.
5. A "Start X.Y.Z.dev0" pull request moves the version on.

Each release is installed on the test VM from its `base` snapshot, and upgraded from the
release before, before it reaches anyone's production.
