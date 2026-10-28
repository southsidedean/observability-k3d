# Checks for your own files

Two small charts that `./ok3d` uses to check `settings.yaml` and `devices.yaml` before anything
else reads them. They're never installed. Helm parses each file with its own YAML parser, so
anchors, merge keys, and flow style are read exactly as `./ok3d apply` would read them.

- `settings/`: a settings file may hold only your settings (`settingsVersion`, `cluster`,
  `host`, `tls`, `modules`, `metrics`, `unifi`, `alerts`), never the chart's own sections
  (`kube-prometheus-stack`, `prometheus-blackbox-exporter`, `gateway`, `global`), which choose
  images and how pods run. Its template prints the settings only you may change on the
  server, which the helper compares before it saves settings the Dashboard sent.
- `devices/`: a devices file may hold only `devices`.

`chart/ok3d/values.schema.json` still checks every value; these only check which sections a
file may have.
