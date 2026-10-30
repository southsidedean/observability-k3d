# Setting up ok3d from the Dashboard

From 0.5, you set ok3d up on a web page, the Dashboard, instead of editing files and running
commands. The installer starts it, and gives you its address and, on a terminal, its password.
[Installing with an AI assistant](install-with-ai.md) has a prompt that does all this for you.
[The Dashboard under the hood](dashboard-under-the-hood.md) says how it works and what keeps
it safe.

## Install

On the server, as yourself (not root), with Docker, k3d, Helm, and `kubectl` installed:

```sh
sudo install -d -o "$USER" -m 0755 /srv/ok3d   # the data folder, owned by you
curl -fsSL https://raw.githubusercontent.com/southsidedean/observability-k3d/main/install.sh | sh
```

The installer puts ok3d in `~/ok3d`, makes your `settings.yaml`, starts the Dashboard, and
prints its address, `https://dashboard.noc.home.arpa:8444/` with the example settings, and
its password (when you run it yourself, in a terminal). To open it, point
`dashboard.noc.home.arpa` (or every name under your domain) at the server, and trust ok3d's
certificate authority on your computer:
[Opening ok3d's pages](certificate.md) has the steps for both.

## Sign in

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../images/screenshots/dashboard-sign-in-dark.png">
  <img src="../images/screenshots/dashboard-sign-in-light.png" alt="The Dashboard's sign-in page: a password box and a Sign in button, with a note that the password is in dashboard/password in the data root, and that the installer showed it too if you ran it yourself." width="700">
</picture>

The password is the one the installer printed. It's also in `dashboard/password` in the data
root, readable only by you: `cat /srv/ok3d/dashboard/password` shows it, with the example
settings. (When an AI assistant ran the installer for you, it usually isn't printed: get it
from that file yourself.) After five wrong tries from one computer, sign-in pauses for a
minute.

## Home

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../images/screenshots/dashboard-home-dark.png">
  <img src="../images/screenshots/dashboard-home-light.png" alt="The Dashboard's Home page: ok3d 0.5.1, the helper running, the Check and Apply buttons with a note that Apply will change nothing that's running and the same commands on the server, a Before you Apply list saying alerts go nowhere yet, What's next with five steps and links to the certificate authority and Grafana, the helper's last answer, a Check that finished with exit status 0, with what ok3d check printed, and Releases, with a Look for a new release button." width="700">
</picture>

Each page also says what its buttons do on the server, as the command or the line in a file
you'd use there instead, so anything you do here you can also do over SSH.

Home is where you start and finish each change:

1. **Before you Apply** lists what's still missing: a key a part you switched on needs,
   somewhere for alerts to go, or devices to watch.
2. **Check** asks the server whether it's ready and your settings are valid. It changes
   nothing. Its answer appears under **The helper's last answer**: reload the page to see it
   arrive.
3. **Apply** turns on once a Check finds no problems. The first Apply makes the cluster and
   takes about 20 minutes; later ones bring it up to date with your settings, and are
   quicker. Once a cluster is running, Check also lists what Apply would change: the parts
   it would restart (Grafana, say, after a change to its settings), stop (a part you
   switched off), or start. If Apply would restart or stop anything, it asks first: a page
   names those parts, and **Apply anyway** goes ahead.
4. **What's next** appears once an Apply has worked: the steps on your own devices that the
   Dashboard can't do for you, such as trusting the certificate authority and opening
   Grafana.
5. **Releases** says whether a newer release of ok3d is out, once you've pressed **Look for a
   new release**, and how your last upgrade went ([Upgrading](#upgrading), below).

## Upgrading

From 0.5.1, the Dashboard can move ok3d to a newer release:

1. On Home, press **Look for a new release**. This asks GitHub for the list of ok3d's
   releases; ok3d never does on its own.
2. If one is out, Home links to its notes. Read them first, especially anything under
   "Upgrading", and do what they say before you go on.
3. Press **Upgrade to** the release. The Upgrade page says what happens; press **Upgrade
   now** to start.
4. Home shows each step as it happens: reload the page to follow it. Partway through, the
   Dashboard restarts with the new release, so you'll sign in again.

ok3d's pages (Grafana, Prometheus, Alertmanager) are down while the cluster is made again,
which can take as long as your first Apply did. If the new release's check or install fails,
ok3d moves back and nothing else changes. [Upgrading](upgrading.md) has the details, the
backups it makes, and what to do if an upgrade stops partway.

## Setup

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../images/screenshots/dashboard-setup-dark.png">
  <img src="../images/screenshots/dashboard-setup-light.png" alt="The Dashboard's Setup page, each choice with the settings.yaml line it writes: four ready-made setups as cards (Basic NOC, marked as the setup now; Network NOC, which needs the UniFi controller's address first; NOC with logs, coming in 0.6; and NOC with agents, coming in 0.9), then each part (UniFi, off until its controller's address is set, and the rest coming in later releases), then where alerts go: ntfy, email, and the dead man's switch, each off, with a Turn on button." width="700">
</picture>

Choose a ready-made setup, or switch the parts on and off yourself:

- **Basic NOC** watches your devices and your internet link.
- **Network NOC** adds your UniFi network. It needs your UniFi controller's address in
  `settings.yaml` on the server (`unifi.url`) and a view-only API key on the Keys page.
  [Your devices](devices.md#unifi) says how to make the key.
- **Where alerts go**: ntfy, email, and the dead man's switch. Each says which keys it needs.
  [Alerts](alerts.md) has the steps for each.

Each choice is saved to `settings.yaml`, and then Home shows the answer. A part that comes in
a later release says which one.

## Settings and Devices

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../images/screenshots/dashboard-devices-dark.png">
  <img src="../images/screenshots/dashboard-devices-light.png" alt="The Dashboard's Devices page: devices.yaml in a text box, listing the simulated network's router, switch, access points, NAS, printer, and UniFi controller, with the same edit on the server and a Save button." width="700">
</picture>

These show `settings.yaml` and `devices.yaml` as they are on the server, to change and save.
`settings.example.yaml` explains every setting, and [Your devices](devices.md) every field
of a device. A save is checked first and refused if anything's wrong, and the old file is
kept in `local/backups/` on the server. Some settings decide where ok3d keeps its data and
where it sends your keys; a save that changes those is refused, and you change them in the
file on the server.

## Maintenance

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../images/screenshots/dashboard-maintenance-dark.png">
  <img src="../images/screenshots/dashboard-maintenance-light.png" alt="The Dashboard's Maintenance page: no maintenance windows yet, a button to read them again from Alertmanager, and a form to add one: for all of ok3d or ticked devices from the simulated network, from now for a length or between two times in the server's own time, and why, with the same command on the server." width="700">
</picture>

**Maintenance** lists the maintenance windows: times when alerts don't notify you, for all of
ok3d or for the devices you choose. Add one from now for a length, or between two times in
the server's own time, with a reason if you like; **End now** ends one early. Home says while
one is on. [Alerts](alerts.md#maintenance-windows-keeping-alerts-quiet-while-you-work) has the
details.

## Keys

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../images/screenshots/dashboard-keys-dark.png">
  <img src="../images/screenshots/dashboard-keys-light.png" alt="The Dashboard's Keys page: the UniFi API key, the ntfy topic and token, and the mail password, each saying whether it's set and which line of .env it goes into on the server, with a box to type a new one and a Save button." width="700">
</picture>

Keys and passwords go into `.env` on the server. The Dashboard shows only whether each one is
set, never its value. Saving an empty value clears it. The admin password, the dead man's
switch's address, and the Anthropic API key are set only in `.env` on the server.

## Grafana

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../images/screenshots/grafana-devices-dark.png">
  <img src="../images/screenshots/grafana-devices-light.png" alt="Grafana's ok3d Devices dashboard on the simulated network: counts of devices up and down, failing checks, and firing alerts, a table of every check with its state, and a graph of how long each ping takes." width="700">
</picture>

Once an Apply has worked, Grafana is at `https://grafana.noc.home.arpa:8443/` with the
example settings. Sign in as `admin`, with the password in `admin-password` in the data
root. The **ok3d: Devices** dashboard shows every device and check.
