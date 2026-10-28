# Trying ok3d on the simulated network

The simulated network is a small, made-up home network that runs on the same server as
ok3d: a router, a switch, two access points, a NAS, a printer, and a UniFi controller. Use it
to try ok3d before pointing it at your own network, or to see an alert fire without breaking
anything real. ok3d's own tests and the screenshots in these docs use it too.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../images/diagrams/demo-network-dark.png">
  <img src="../images/diagrams/demo-network-light.png" alt="The demo network, 198.51.100.0/24, is a Docker network on the server. The router at 198.51.100.1 connects to the office switch at 198.51.100.2, which connects the living room and upstairs access points (198.51.100.3 and .4), the NAS (198.51.100.20), the printer (198.51.100.30), and the UniFi controller (198.51.100.50), which serves UniFi metrics like unpoller. The router and the NAS answer HTTP, and every device answers ping. The cluster's node joins the demo network to ping, check, and scrape the devices.">
</picture>

## Start it

You need ok3d's settings (`settings.yaml`, from `settings.example.yaml`) and Docker. The
cluster doesn't have to exist yet: if it does, its node joins the demo network, and if it
doesn't, `./ok3d apply` connects it later.

```sh
./ok3d demo up
./ok3d demo status
```

Each device is a small container that answers ping. The router and the NAS also serve a web
page on port 80, and the UniFi controller serves UniFi metrics on port 9130, the way unpoller
does, with numbers that change over time so the graphs move.

To have ok3d watch it, use the demo's list of devices, then apply:

```sh
cp devices.demo.yaml devices.yaml
./ok3d apply
```

Within a minute, Prometheus is pinging every device, checking the router's and the NAS's
pages, and collecting the fake controller's UniFi metrics.

The addresses are in `198.51.100.0/24`, a range set aside for documentation, so they can't
clash with your own network.

## Break something

```sh
./ok3d demo fail upstairs-ap
```

The access point stops answering, and the fake controller stops reporting it, the way a real
controller loses a device. Within a minute its checks fail, and from the next 0.4 change, an alert fires. Bring it back
with:

```sh
./ok3d demo fix upstairs-ap
```

Any device can fail, the router and the controller included.

## Stop it

```sh
./ok3d demo down
```

This removes the devices, their network, and what the demo kept in the data root
(`demo/`). Nothing else changes.

## Under the hood

- The list of devices is `demo/network.tsv`. `./ok3d demo up` starts one container per line,
  and the fake controller reads the same list to know what to report.
- Every container runs a stock Python image, pinned by digest, as an unprivileged user, with
  a read-only filesystem, no capabilities, and small memory and process limits.
- The fake controller is `src/ok3d/demo_exporter.py`, and the devices' web page is
  `src/ok3d/demo_device.py`. Both use only Python's standard library.
- `./ok3d demo fail` writes the device's name to `demo/failed` in the data root, which the
  controller reads on every scrape, and stops the device's container.
- Docker picks addresses for anything else that joins the network (such as the cluster's node)
  only from `198.51.100.192` to `.223`, so a failed device's address is never handed out
  while it's down.
