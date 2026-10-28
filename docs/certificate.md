# Opening ok3d's pages

ok3d's pages are at names under its domain (`noc.home.arpa` unless you chose another), all on
one port, over HTTPS:

| Page | Address | Login |
|---|---|---|
| Grafana | `https://grafana.noc.home.arpa:8443/` | `admin`, and the admin password |
| Prometheus | `https://prometheus.noc.home.arpa:8443/` | the same |
| Alertmanager | `https://alertmanager.noc.home.arpa:8443/` | the same |
| The certificate authority | `https://ca.noc.home.arpa:8443/` | none: it's a download |
| The Dashboard (from 0.5) | `https://dashboard.noc.home.arpa:8444/` | its own password, which `./ok3d install` prints |

The admin password is `OK3D_ADMIN_PASSWORD` from `.env`, or, if you left that empty, the one
ok3d made the first time: it's in `admin-password` in the data root, readable only by you.

Two things make the pages open cleanly: your devices finding the names, and your devices
trusting ok3d's certificate authority.

## 1. Point the names at the server

The names need to lead to the server ok3d runs on. Add one record to your local DNS, on your
router or your network's DNS server, for every name under the domain:

```text
*.noc.home.arpa  ->  192.168.1.20   (the server's address)
```

- **UniFi:** Settings, Policy Engine (or Routing), DNS, Create Entry: type A record, domain
  `*.noc.home.arpa`, the server's address.
- **Pi-hole:** Local DNS, DNS Records. Pi-hole has no wildcard there, so add each name
  (`grafana.noc.home.arpa`, `prometheus.noc.home.arpa`, `alertmanager.noc.home.arpa`,
  `ca.noc.home.arpa`, `dashboard.noc.home.arpa`) with the server's address.
- **dnsmasq:** `address=/noc.home.arpa/192.168.1.20`.
- **No DNS of your own:** on one computer, add the names to its hosts file
  (`/etc/hosts`, or `C:\Windows\System32\drivers\etc\hosts`):

  ```text
  192.168.1.20  grafana.noc.home.arpa prometheus.noc.home.arpa alertmanager.noc.home.arpa ca.noc.home.arpa dashboard.noc.home.arpa
  ```

`home.arpa` is set aside for home networks, so it can never clash with a name on the
internet.

## 2. Trust ok3d's certificate authority

ok3d issues the pages' certificate from a certificate authority of its own, made the first
time you applied and kept in the data root, so it stays the same when the cluster is made
again. Until a device trusts it, its browser warns about every page. Trust it once on each
device:

1. Download it: open `https://ca.noc.home.arpa:8443/` and accept the warning this one time
   (it's the authority itself you're fetching), or copy `certs/ca.crt` from the data root.
2. Add it to the device:
   - **macOS:** double-click `ok3d-ca.crt`, add it to the System keychain, then in Keychain
     Access open it, expand Trust, and set "When using this certificate" to Always Trust.
   - **Windows:** double-click it, Install Certificate, Local Machine, "Place all certificates
     in the following store", Trusted Root Certification Authorities.
   - **iPhone and iPad:** open the download, then Settings, General, VPN & Device Management,
     install the profile; then Settings, General, About, Certificate Trust Settings, and
     switch it on.
   - **Android:** Settings, Security, Encryption & credentials, Install a certificate, CA
     certificate. (The wording differs between phone makers.)
   - **Linux (Ubuntu, Debian):** `sudo cp ok3d-ca.crt /usr/local/share/ca-certificates/ && sudo update-ca-certificates`.
   - **Firefox** keeps its own list: Settings, Privacy & Security, Certificates, View
     Certificates, Authorities, Import.

### Why trusting it is safe

The authority can only vouch for names under ok3d's domain: it carries a name constraint
that browsers enforce. Even if its key were ever stolen, it couldn't be used to pass off any
other site (your bank, say) on a device that trusts it.

Its key stays in the data root (`certs/ca.key`), readable only by you, and in the cluster as
the Secret cert-manager issues from. The page certificate cert-manager issues lasts 90 days
and renews itself a month before it runs out.

## If a page doesn't open

- **"This site can't be reached":** the name doesn't lead to the server yet (step 1). Check
  with `ping grafana.noc.home.arpa` from the device.
- **A certificate warning:** the device doesn't trust the authority yet (step 2).
- **"Not found":** the name is right but isn't one of ok3d's pages: check the spelling.
- **A login prompt that won't take the password:** it's `admin` and the admin password. After
  changing `OK3D_ADMIN_PASSWORD`, run `./ok3d apply`.
