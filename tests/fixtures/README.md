# Recorded metric names

The metric-name check (`tests/test_rules.py`) holds every alert rule to metrics that really
exist. These files list the names each exporter really serves, one per line, recorded from
the version ok3d runs. Re-record them when a version changes; Renovate's pull request for the
new version is the reminder.

- `node_exporter-v1.12.1.metrics`: the names in node_exporter's own end-to-end test output
  (`collector/fixtures/e2e-output.txt` at tag v1.12.1, which covers collectors such as mdadm
  that need special hardware), together with the names a live
  `quay.io/prometheus/node-exporter:v1.12.1` served (which add the filesystem and memory
  collectors the test output leaves out).
- `blackbox_exporter-v0.29.0.metrics`: the names a live
  `quay.io/prometheus/blackbox-exporter:v0.29.0` served for an HTTPS check, a TCP check, and a
  ping.

unpoller's names come from the vendored UniFi dashboards instead, which query what unpoller
really serves.
