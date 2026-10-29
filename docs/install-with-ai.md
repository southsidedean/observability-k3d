# Installing ok3d with an AI assistant

If you use an AI assistant that can run commands on your server, such as Claude Code, it can
install ok3d for you. It installs what ok3d needs, runs the installer, and tells you how to
open the Dashboard, where you set everything else up yourself.

Open the assistant in a terminal on the server, as yourself (not root), and paste in the
prompt from [the README](../README.md#install). It points the assistant at this page, at
ok3d's newest release, and the steps below are what it follows.

## What it does, and what it won't

- It tells you what the server is missing before it installs anything.
- It shows you every command that needs `sudo`, and waits for your yes.
- It never reads, prints, or asks for a password or key. The installer doesn't print the
  Dashboard's password when an assistant runs it, so you get it from its file yourself.
- It stops once the Dashboard is running. Your settings, devices, and keys are yours to set,
  on the Dashboard.
- When a step fails, it shows you the error and stops, without working around it.

It's been tested with Claude Code, on a fresh Ubuntu 24.04 server. Other assistants that can
run commands and read web pages should manage it too, but haven't been tested. Whichever you
use, read each `sudo` command before you say yes. If it goes wrong, the
[steps by hand](dashboard.md#install) are short.

## The steps, for the assistant

Follow these in order, as written. Don't change ok3d's files, write `settings.yaml`,
`devices.yaml`, or `.env`, or run `./ok3d` commands other than the ones here.

1. **Check the server.** It must be Linux with systemd, and you must be running as an
   ordinary user, not root. Check for each of these, and list what's missing, with how you'd
   install each, before installing anything:
   - about 8 GB of memory free;
   - `git`, `curl`, and `openssl`;
   - Docker, running, and usable without `sudo` (`docker info` works). If the user isn't in
     the `docker` group, adding them takes effect only after they log in again: say so, and
     stop until they have;
   - [k3d](https://k3d.io) 5.9 or newer, [Helm](https://helm.sh), and `kubectl`. Install
     each the way its own docs say for this Linux distribution.
2. **Ask before `sudo`.** Show the user each command that needs `sudo`, say what it does,
   and wait for their yes. Never run `sudo` without it, and never change how `sudo` works.
3. **Make the data folder**, owned by the user (with `sudo`, so ask first):

   ```sh
   sudo install -d -o "$USER" -m 0755 /srv/ok3d
   ```

4. **Run the installer**, as the user, not with `sudo`:

   ```sh
   curl -fsSL https://raw.githubusercontent.com/southsidedean/observability-k3d/main/install.sh | sh
   ```

   It installs ok3d's newest release in `~/ok3d` and starts the Dashboard. If it prints a
   `sudo loginctl enable-linger` command, that keeps the Dashboard's helper running after the
   user logs out and after a restart: ask, then run it.
5. **Check it's running.** `docker ps` shows `ok3d-dashboard`, and
   `systemctl --user is-active ok3d-helper` says `active`.
6. **Tell the user**, and stop:
   - the Dashboard's address, from the installer's last lines;
   - that its password is in `/srv/ok3d/dashboard/password`, and they can see it with
     `cat /srv/ok3d/dashboard/password`. Don't read that file yourself;
   - that to open the Dashboard from another computer, they point the names under ok3d's
     domain at this server and trust ok3d's certificate authority:
     [Opening ok3d's pages](certificate.md) has the steps;
   - that they set up the rest on the Dashboard: [Setting up from the Dashboard](dashboard.md).

If any step fails, show the user the command and its exact error, and stop. Don't edit
ok3d's files or its settings, turn off a check, or try another way around it.
