# Installing ok3d with an AI assistant

If you use an AI assistant that can run commands on your server, such as Claude Code, it can
install ok3d for you. It installs what ok3d needs, runs the installer, and tells you how to
open the Dashboard, where you set everything else up yourself.

Open the assistant in a terminal on the server, as yourself (not root), and paste in the
prompt from [the README](../README.md#install). It points the assistant at this page, at
ok3d's latest release, and the rules and steps below are what it follows.

## What it does, and what it won't

- It tells you what the server is missing before it installs anything.
- It's told never to run `sudo` itself. When something needs `sudo`, it shows you the
  command and what it does, and you run it in a terminal of your own on the server. So you
  see every command that changes the system, and the assistant doesn't hold `sudo`.
- It's told never to read, print, or ask for a password, API key, or other secret. And when
  the installer's output isn't going to a terminal, as with Claude Code, the installer says
  where the Dashboard's password is instead of printing it. So the password stays out of the
  conversation. Other assistants may run commands in a terminal, and then the installer
  prints it.
- It stops once the Dashboard is running. Your settings, devices, and keys are yours to set,
  on the Dashboard.
- When a step fails, it shows you the error and stops, without working around it.

Before each release, it's tested with Claude Code on a fresh Ubuntu 24.04 server. Other
assistants that can run commands and read web pages should manage it too, but haven't been
tested. Whichever you use, leave its approval prompts on (don't let it run commands without
asking), and read each command before you approve it. If it goes wrong, the
[steps by hand](dashboard.md#install) are short.

## The rules, for the assistant

- **Never run `sudo`.** You can't type the user's password, and you shouldn't hold `sudo`.
  For each command that needs it, show the command, say what it does, and ask the user to
  run it in a terminal of their own on the server. Carry on when they say it's done, and
  check that it worked.
- **Never read, print, or ask for a password, API key, or other secret.** That includes the
  files `dashboard/password` and `admin-password` in the data folder, and `.env`.
- **Change only what the steps say.** Don't edit ok3d's files, don't write `settings.yaml`,
  `devices.yaml`, or `.env`, and run no `ok3d` command but the `check` in step 6.
- **If a step fails, stop.** Show the user the command and its exact error. Don't turn off a
  check or try another way around it.

## The steps, for the assistant

Follow these in order. Every step is safe to repeat.

1. **Check the server**, and list what's missing, with how you'd install each, before
   installing anything:
   - Linux with systemd, and you're running as an ordinary user, not root;
   - about 8 GB of memory free;
   - `git`, `curl`, `openssl`, and Python 3 at `/usr/bin/python3`;
   - Docker, running, and usable without `sudo` (`docker info` works);
   - [k3d](https://k3d.io) 5.9 or newer, [Helm](https://helm.sh), and `kubectl`;
   - the inotify limits: `/proc/sys/fs/inotify/max_user_instances` at least 1024, and
     `/proc/sys/fs/inotify/max_user_watches` at least 1048576.
2. **Install what's missing**, with the user running each `sudo` command:
   - Docker from Docker's own packages
     ([docs.docker.com/engine/install](https://docs.docker.com/engine/install/)), not the
     snap. To use it without `sudo`, the user joins the `docker` group
     (`sudo usermod -aG docker "$USER"`), which works only after they log out and in again.
     Tell them to do that, then start you again and paste the same prompt: you'll pick up
     from here.
   - k3d, Helm, and `kubectl`: from a package manager that checks what it downloads, such
     as Homebrew (which runs on Linux too) or the distribution's own, or from each project's
     release page, checking the download against its published checksum. Not by piping a
     script from a project's main branch into a shell, as k3d's README suggests: that runs
     whatever is on main that day.
   - The inotify limits, which k3d's clusters need:

     ```sh
     printf 'fs.inotify.max_user_instances = 1024\nfs.inotify.max_user_watches = 1048576\n' |
       sudo tee /etc/sysctl.d/60-ok3d.conf && sudo sysctl --system
     ```

3. **The data folder**, owned by the user (the user runs this):

   ```sh
   sudo install -d -o "$USER" -m 0755 /srv/ok3d
   ```

4. **Run the installer** yourself, as the user, without `sudo`:

   ```sh
   curl -fsSL https://raw.githubusercontent.com/southsidedean/observability-k3d/main/install.sh | sh
   ```

   It installs ok3d's latest release in `~/ok3d` and starts the Dashboard. If it prints a
   `sudo loginctl enable-linger` command, that keeps the Dashboard's helper running after the
   user logs out and after a restart: the user runs it.
5. **Check it's running.** `docker ps` shows `ok3d-dashboard`, and
   `systemctl --user is-active ok3d-helper` says `active`.
6. **Check the server is ready**, with `~/ok3d/ok3d check`. It changes nothing. Show the user
   any line that starts with `FAIL`, and what it says to do. Two warnings are expected, that
   there's no `devices.yaml` and that no alert destination is on: the user sets up both on
   the Dashboard.
7. **Tell the user**, and stop:
   - the Dashboard's address, from the installer's last lines;
   - that its password is in `/srv/ok3d/dashboard/password`, and they can see it by running
     `cat /srv/ok3d/dashboard/password` themselves;
   - that to open the Dashboard from another computer, they point the names under ok3d's
     domain at this server and trust ok3d's certificate authority:
     [Opening ok3d's pages](certificate.md) has the steps;
   - that they set up the rest on the Dashboard: [Setting up from the Dashboard](dashboard.md).
