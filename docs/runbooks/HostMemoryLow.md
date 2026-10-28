# HostMemoryLow

**Severity:** warning

A computer has had less than 5% of its memory free for 15 minutes.

## What to check

1. Find what's using it: `top`, sorted by memory (press M).
2. On a server running VMs or containers, a single one can take it all: check each one's limits.
3. If it's always tight, the computer needs more memory, or less running on it.

## When it clears

It clears on its own when more memory is free.

To keep it quiet while you work on it, add a silence in Alertmanager. That arrives on the Dashboard in 0.5; until then, [docs/alerts.md](../alerts.md#silencing-an-alert) shows the command.
