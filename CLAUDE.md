# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Roadmap

The repository is being rebuilt as **ok3d** (short for observability-k3d), a home network
operations center on k3d with AI agents. `PLAN.md` holds every decision, the roadmap from 0.3
to 1.x, the CI and quality rules, and the open questions. Read it before starting work, and
update it in the same pull request when a decision changes.

`docs/roadmap.md` is the status page: what's released, in progress, and planned, release by
release. The user reads it instead of asking, so every pull request that finishes, starts, or
changes a roadmap item updates it (a test checks it names the version the code is at).

- `v0.2.0` is the old stack's last version; its files are gone from 0.4 (`docs/upgrading.md`
  covers moving from it). Fix forward in ok3d, never by bringing them back.
- `v0.3.0` is released. 0.4 is in progress; `docs/roadmap.md` has where it stands.
- Before 1.0: a full independent review of every file (no spot checks) and an architectural
  review, written up in `docs/reviews/1.0-review.md`.

The user's servers, test VMs, and where production runs are in Claude's project memory, never
in this repository.

## Commands


```bash
./ok3d check          # is this machine ready, and are the settings valid? changes nothing
./ok3d apply          # make what's missing (data root folders, CA, cluster), then deploy
./ok3d delete --yes   # delete the cluster; the data root stays

python3 -m venv .venv && .venv/bin/python -m pip install -e '.[dev]'   # once
git config core.hooksPath .githooks                                    # once: the git hooks
scripts/check.sh                                   # every check that doesn't need a cluster
.venv/bin/python -m pytest tests/test_privacy.py   # one test file
.venv/bin/python -m pytest -k hooks                # tests by name
```


## Git and GitHub

- `main` is protected: pull requests only, squash merges, no force-pushes, and the release
  tags (`v*`) can't be moved or deleted. Actions are pinned by commit.
- One branch per change, `gh pr create`, wait for the checks, squash merge. Merge or push only
  when the user has said to.
- Stage files by name. Never `git add -A`: untracked screenshots in `images/` would go in.
  Check `git status --short` first.
- Images: look at every one before committing, strip its metadata, and commit with
  `IMAGES_CHECKED=1`. Screenshots come from `scripts/screenshots.sh` on the simulated
  network, never from a real network.
- Commit messages end with the Claude co-author line, and pull request bodies with the
  Claude Code line.
- Independent reviews: every pull request gets one before merging, and the user asks for a
  bigger one before major merges. The brief says no spot checks, every file in scope read in
  full, and a coverage table first.
- CodeQL reads names, not values: a function or variable named like `*password*` or
  `*secret*` (even a description of one) counts as a secret, and so does anything it flows
  into, such as a log line. Choose names accordingly.
- Releases: user-facing changes go under the next version in `CHANGELOG.md`, marked
  unreleased. The release pull request sets the version and the date; then the signed tag,
  `gh release create` with that changelog section as the notes, a check that both images were
  published for amd64 and arm64 and scanned, and a "Start X.Y.Z.dev0" pull request.

## Privacy (public repository)

No host names, domains, personal email addresses, home paths, LAN addresses, account names,
or ntfy topics in code, docs, screenshots, commit messages, pull request bodies, or release
notes. Examples use stand-ins: `192.168.1.20`, `192.0.2.x`, `fd00::5`, `my-server.lan`,
`noc.home.arpa`. The user's own names live in `.git/hooks/private-names`, which is never
committed. Check pull request bodies and release notes against it before posting.

The user's own settings (`settings.yaml`, `devices.yaml`, `.env`, `local/`) are gitignored,
and the repository carries a commented example of each.

## Docs

- Readers have some computer skills but aren't experts: plain words, steps first, enough
  context, no padding.
- Each subject goes from easy to advanced: the simplest path, then the options, then the
  advanced parts, then an "under the hood" page that describes the code as it is. Update an
  under-the-hood page in the same pull request as the code it describes.
- Use screenshots and diagrams wherever they help. Diagrams are Mermaid files in
  `docs/diagrams/`, rendered to light and dark PNGs by `scripts/diagrams.sh`. Screenshots come
  from `scripts/screenshots.sh`, which may stand up a VM or a container to take them. Every
  image has alt text.
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
- Tests come with every change. A bug fix starts with a test that fails without the fix.
- Shell scripts are POSIX `sh`. The Dashboard, the helper, and the in-cluster tools are
  Python.
- All environment config lives in the user's settings files, never hardcoded in scripts.
