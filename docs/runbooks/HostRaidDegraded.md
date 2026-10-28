# HostRaidDegraded

**Severity:** critical

A disk in a computer's software RAID has failed. The array still works, but with no spare: another failure loses data.

## What to check

1. See which disk: `cat /proc/mdstat` and `sudo mdadm --detail /dev/<array>`.
2. Back up anything you can't lose, now, before anything else.
3. Replace the failed disk and add the new one to the array (`sudo mdadm --manage /dev/<array> --add /dev/<new disk>`). The rebuild takes hours.
4. Check the other disks' health while you're there: `sudo smartctl -a /dev/<disk>`.

## When it clears

It clears on its own when the array has no failed disks.

To keep it quiet while you work on it, add a silence in Alertmanager. That arrives on the Dashboard in 0.5; until then, [docs/alerts.md](../alerts.md#silencing-an-alert) shows the command.
