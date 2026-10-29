# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Roadmap

The repository is being rebuilt as **ok3d** (short for observability-k3d), a home network
operations center on k3d with AI agents. `PLAN.md` holds every decision, the roadmap from 0.3
to 1.x, the CI and quality rules, and the open questions. Read it before starting work, and
update it in the same pull request when a decision changes.

`docs/roadmap.md` is the status page: what's released, in progress, and planned, release by
release. The user reads it instead of asking, so every pull request that finishes, starts, or
changes a roadmap item updates it (a test checks it names the version the code is at). A pull
request that finishes an item marks it Done with its own number.

- `v0.2.0` is the old stack's last version; its files are gone from 0.4 (`docs/upgrading.md`
  covers moving from it). Fix forward in ok3d, never by bringing them back.
- `v0.4.0` is released. 0.5 (the Dashboard) is in progress; `docs/roadmap.md` has where it
  stands.
- Before 1.0: a full independent review of every file (no spot checks) and an architectural
  review, written up in `docs/reviews/1.0-review.md`.

The user's servers, test VMs, and where production runs are in Claude's project memory, never
in this repository.

## How it fits together

- `ok3d` (POSIX `sh`) is the command everything goes through: it reads `settings.yaml`,
  `devices.yaml`, and `.env`, checks them, makes the data root's folders and the certificate
  authority, creates the k3d cluster, and deploys. Every setting comes from those files.
- `chart/`: `ok3d-platform` (cert-manager and the Prometheus operator's custom resource
  definitions, installed first) and `ok3d` (everything else, one umbrella chart with pinned
  dependencies and a values schema). `chart/ok3d-files` holds two charts that are never
  installed: they check `settings.yaml` and `devices.yaml` before anything else reads them.
- The Dashboard (`src/ok3d/dashboard/`, a container outside the cluster) and the helper
  (`src/ok3d/helper.py`, a systemd user service running as the user) are Python with only the
  standard library. The Dashboard never runs anything itself: it leaves one request at a time
  in its outbox, and the helper checks it and runs `./ok3d` (`check`, `apply`, saves through
  `./ok3d validate --from-dashboard`). `docs/dashboard-under-the-hood.md` and
  `docs/helper-under-the-hood.md` describe both.
- `install.sh` (for `curl ... | sh`) checks out the latest release into `~/ok3d` and runs
  `./ok3d install`, which sets up the helper and the Dashboard.
- `demo/` and `./ok3d demo` are the simulated network that CI, the screenshots, and the docs'
  examples watch, so none of them show a real one.

## Commands

```bash
./ok3d check          # is this machine ready, and are the settings valid? changes nothing
./ok3d apply          # make what's missing (data root folders, CA, cluster), then deploy
./ok3d install        # the helper and the Dashboard (Linux with systemd)
./ok3d delete --yes   # delete the cluster; the data root stays
./ok3d demo up        # the simulated network (also down, status, fail, fix)
./ok3d test-alert     # check that alerts reach you
./ok3d validate settings FILE [--from-dashboard]   # what the helper runs before a save

python3 -m venv .venv && .venv/bin/python -m pip install -e '.[dev]'   # once
git config core.hooksPath .githooks                                    # once: the git hooks
scripts/check.sh                                   # every check that doesn't need a cluster
.venv/bin/python -m pytest tests/test_privacy.py   # one test file
.venv/bin/python -m pytest -k hooks                # tests by name
scripts/diagrams.sh                                # after changing docs/diagrams/*.mmd
scripts/screenshots.sh [--setup]                   # on a fresh test VM only (see Docs)
```

- ruff checks `src`, `tests`, and `scripts`, at 110 characters a line. Don't run
  `ruff format`: the project doesn't use it, and it rewrites files you didn't touch.
- The tests can't reach the network (`tests/conftest.py` fences them), and each has 60
  seconds (pytest-timeout).
- When piping test output (`pytest ... | tail`), use `set -o pipefail`, or put no commit or
  push after the pipe: otherwise a failing test doesn't stop the chain.
- The test VM is made from `tests/vm/cloud-init.yaml`, and restored to its clean snapshot
  before each install test or screenshot run. Cluster tests (Check and Apply for real, the
  installer, upgrades) run there, not in CI.

## Git and GitHub

- `main` is protected: pull requests only, squash merges, no force-pushes, and the release
  tags (`v*`) can't be moved or deleted. Actions are pinned by commit.
- One branch per change, `gh pr create`, wait for the checks, squash merge. Merge or push only
  when the user has said to. Fix a pull request with new commits, and bring it up to date by
  merging `main` into it, not by rebasing.
- If a couple of minutes after a push a pull request still shows no checks, GitHub missed it:
  push an empty commit (`git commit --allow-empty`) to start them.
- Stage files by name. Never `git add -A`: untracked screenshots in `images/` would go in.
  Check `git status --short` first.
- Never use `git checkout <file>` to undo a small change: it throws away everything
  uncommitted in that file. Undo with an edit.
- Images: look at every one before committing, strip its metadata, and commit with
  `IMAGES_CHECKED=1`. Screenshots come from `scripts/screenshots.sh` on the simulated
  network, never from a real network.
- Commit messages end with the Claude co-author line, and pull request bodies with the
  Claude Code line.
- Independent reviews: every pull request gets one before merging, and the user asks for a
  bigger one before major merges. The brief says no spot checks, every file in scope read in
  full, and a coverage table first. Fixes go in as new commits, each re-reviewed.
- CodeQL reads names, not values: a function or variable named like `*password*` or
  `*secret*` (even a description of one) counts as a secret, and so does anything it flows
  into, such as a log line. Choose names accordingly.
- Releases: user-facing changes go under the next version in `CHANGELOG.md`, marked
  unreleased. The release pull request sets the version (`src/ok3d/__init__.py`) and the
  date; then the signed tag, `gh release create` with that changelog section as the notes, a
  check that both images were published for amd64 and arm64 and scanned, and a "Start
  X.Y.Z.dev0" pull request.

## Privacy (public repository)

No host names, domains, personal email addresses, home paths, LAN addresses, account names,
or ntfy topics in code, docs, screenshots, commit messages, pull request bodies, or release
notes. Examples use stand-ins: `192.168.1.20`, `192.0.2.x`, `fd00::5`, `my-server.lan`,
`noc.home.arpa`. The user's own names live in `.git/hooks/private-names`, which is never
committed.

Check pull request bodies and release notes against it before posting, and post only when
grep finds nothing (status 1); status 0 is a match, and 2 means the check itself failed:

```sh
grep -v -e '^#' -e '^[[:space:]]*$' .git/hooks/private-names | grep -i -E -f - body.md; [ $? -eq 1 ]
```

Never show raw logs or command output from a machine watching a real network: they can hold
the UniFi key, the ntfy topic, the mail password, or addresses. Redact first, or say what
they show. The test VM's simulated network is fine to show as it is.

The user's own settings (`settings.yaml`, `devices.yaml`, `.env`, `local/`) are gitignored,
and the repository carries a commented example of each.

## Docs

- Readers have some computer skills but aren't experts: plain words, steps first, enough
  context, no padding.
- Each subject goes from easy to advanced: the simplest path, then the options, then the
  advanced parts, then an "under the hood" page that describes the code as it is. Update an
  under-the-hood page in the same pull request as the code it describes.
- Use screenshots and diagrams wherever they help. Diagrams are Mermaid files in
  `docs/diagrams/`, rendered to light and dark PNGs by `scripts/diagrams.sh`. Screenshots are
  listed in `docs/screenshots.json` and taken by `scripts/screenshots.sh` (Playwright's
  Chromium in a pinned container) on a test VM: `--setup` sets ok3d up there on the example
  settings and the simulated network first, and it refuses to run on anything else. Every
  image has alt text, and a change to a page's text means retaking its screenshot.
- Everything a person reads goes through the `humanizer` skill before it's committed or
  posted: docs, the README, `PLAN.md`, runbooks, the CHANGELOG, comments, commit messages,
  pull request bodies, release notes, the Dashboard's text, and alert and notification text.
  Do the humanizer pass last, after every other edit.
- No em or en dashes. Check that examples are real before using them.

## Code

- Code and configuration are well commented. Each file starts by saying what it's for, and
  comments say why wherever the code doesn't make it obvious. That covers scripts, Python,
  chart templates, values files, the values schema (every setting has a description), settings
  examples, alert rules (summary, description, runbook link), dashboards (each panel says what
  it shows), and workflows. Match the surrounding file's style.
- Tests come with every change. A bug fix starts with a test that fails without the fix, and a
  test that could pass by luck (a race, a clock, a timeout) is made to fail for the right
  reason instead.
- Shell scripts are POSIX `sh`. The Dashboard, the helper, and the in-cluster tools are
  Python, with only the standard library.
- Anything a stranger or another program can send (a form, a file the Dashboard saves, the
  helper's requests) is untrusted: check it whole, with `re.fullmatch` (a `$` lets a final
  line break through), and put a limit on its size and on how long it may take.
- All environment config lives in the user's settings files, never hardcoded in scripts.
