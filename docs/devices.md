# Your devices

ok3d watches the devices you list in `devices.yaml`. Each one gets the checks you ask for,
and, if it serves metrics, Prometheus collects them.

## Make the list

Copy the example and edit it:

```sh
cp devices.example.yaml devices.yaml
```

`devices.yaml` is yours: it's never committed. To try ok3d on the simulated network first,
copy `devices.demo.yaml` instead ([trying ok3d on the simulated network](demo.md)).

Each device is a few lines:

```yaml
devices:
  - name: nas
    address: 192.168.1.20
    role: nas
    behind: office-switch
    checks: [ping, https, tcp:22]
    metrics: ["9100"]
    protected: true
```

| Field | What it's for |
|---|---|
| `name` | What you call it, shown on the board and in alerts: lowercase letters, digits, and dashes. |
| `address` | Its IP address or host name. |
| `role` | `gateway`, `switch`, `access-point`, `server`, `nas`, `ups`, `camera`, `printer`, `controller`, or `other`. |
| `behind` | The device it connects through, by name. When that one fails, you get one alert for it instead of one for every device behind it. UniFi gear reports this by itself. |
| `checks` | What to check, every 30 seconds (below). |
| `metrics` | Ports where it serves Prometheus metrics, such as `9100` for node_exporter, or `9100/metrics` with a path. |
| `protected` | `true` means no action may ever touch it, even with your approval (from 0.9). |

Run `./ok3d check` after editing: it says what's wrong with any device, by field, before
anything changes. Then `./ok3d apply`.

## The checks

| Check | Passes when |
|---|---|
| `ping` | The device answers ping. |
| `http` | `http://<address>/` answers with a 2xx status, after any redirects. |
| `https` | `https://<address>/` answers with a 2xx status over TLS. The certificate isn't checked, since most home devices have a self-signed one. |
| `tcp:<port>` | The port accepts a connection, such as `tcp:22` for SSH. |

Each result carries the device's name, role, and the device it's behind, which the alerts
and the NOC board use.

## Your servers' own numbers

To see a computer's processor, memory, disks, and temperatures, run node_exporter on it and
list its port under `metrics`. On Ubuntu or Debian:

```sh
sudo apt install prometheus-node-exporter
```

Then add `metrics: ["9100"]` to that device. This includes the server ok3d runs on: ok3d
doesn't run node_exporter inside its cluster, since it would need more access to the server
than ok3d gives anything.

## UniFi

With UniFi gear, ok3d can also read your UniFi controller for each device's load, ports,
clients, and the internet link's traffic.

1. On the controller, make an admin with view-only access, then make an API key for it
   (Settings, Control Plane, Integrations). View-only means ok3d can read and change nothing.
2. In `.env`, set `UNIFI_API_KEY` to the key, and make the file yours alone:
   `chmod 600 .env`.
3. In `settings.yaml`:

   ```yaml
   modules:
     unifi: true
   unifi:
     url: https://192.168.1.1
   ```

4. `./ok3d apply`.

The key goes only to the one part of ok3d that reads the controller (unpoller). Per-client
app traffic (DPI) stays off: it multiplies the data many times over for detail few homes need.
