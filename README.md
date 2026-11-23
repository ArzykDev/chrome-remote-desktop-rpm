# chrome-remote-desktop-rpm

A build recipe that turns Google's official Chrome Remote Desktop host `.deb` into
a Fedora RPM. The resulting host attaches to your **existing** KDE Plasma (Wayland)
session rather than starting a separate virtual desktop.

This repository contains **only the recipe**. It never ships Google's binaries:
you download the `.deb` from Google and build the package on your own machine,
the same way an AUR package works. The CRD host has no redistribution licence;
Google's Terms of Service grant a personal, non-assignable licence and forbid
copying, modifying or distributing the software. Don't publish built RPMs.

## What it does

- **Repackages** the `.deb` for Fedora: systemd units under `/usr/lib/systemd`, a
  Fedora `password-auth` PAM stack, sysusers config instead of `adduser`, and no
  Debian apt-repo cron job.
- **Attaches to your session.** It uses upstream's multi-process host (`--type=daemon`),
  which routes connections into a logged-in user's session when
  `/etc/chrome-remote-desktop/session_routing.json` exists. On non-GNOME Wayland it uses the
  xdg-desktop-portal RemoteDesktop and ScreenCast portals, with libei for input.
- **Captures your real monitors.** Upstream asks the portal for a *virtual* screen. On KDE that
  adds a new output, and KScreen then re-enables monitors you had turned off.
  `patch-monitor-source.py` changes 8 bytes in `libremoting_core.so` so the host requests
  `MONITOR` instead, and gives each monitor's stream its own PipeWire connection (sharing
  one hangs the host with two or more monitors). If a future release changes that code, the
  patcher refuses and the build continues without it (virtual-monitor mode) instead of
  holding back the update.
- **Releases the portal session on disconnect.** Upstream keeps the session (and KDE's
  "remote control active" indicator) open after the client leaves. `crd-session-reaper`
  ends the idle desktop process 10 s after the last authenticated client disconnects.
- **Updates itself.** Every installed RPM carries this recipe in
  `/usr/share/chrome-remote-desktop-rpm/`. An hourly timer checks Google's apt repo,
  verifies the signed metadata, rebuilds the RPM, and installs it once no session is
  active. Nothing is fetched from anywhere but Google.

## Requirements

Fedora (tested on 44), KDE Plasma 6.3+ on Wayland, x86_64. GNOME should also work,
because upstream supports it directly, but it is untested here.

## Install

```sh
./build.sh                       # downloads Google's current .deb, builds into dist/
sudo dnf install dist/chrome-remote-desktop-*.rpm
echo '{"sessionUser": "'"$USER"'"}' | sudo tee /etc/chrome-remote-desktop/session_routing.json
```

Register the host:

1. Open <https://remotedesktop.google.com/headless>, choose **Begin → Next →
   Authorize**, and copy the **Debian Linux** command.
2. Append `--host-type=gdm-managed` and run it. That flag selects the
   multi-process host; without it you get the legacy virtual-session host.
   Don't use "Set up remote access" on the regular `/access` page, which also sets up
   the legacy host.

Skip KDE's "Allow remote control?" dialog (needed for unattended access):

```sh
flatpak permission-set kde-authorized remote-desktop com.google.ChromeRemoteDesktop yes
```

Since 159 the host registers this app ID with the portal (the journal shows
"Host.Registry.Register succeeded"). Before that it ran with an empty app ID and
needed `""` authorized instead, which also let any other unidentified process
(for example from SSH logins) use remote control without a prompt. Once on 159,
drop that with `flatpak permission-remove kde-authorized remote-desktop ""`.

## Updates

`chrome-remote-desktop-update.timer` is started together with the daemon, so it
needs no enabling. Each run:

1. Installs an RPM built by an earlier run, if it is still newer than the installed
   package and no session is active.
2. Fetches `Release` and `Release.gpg` and verifies them against Google's Linux signing
   key, pinned by primary fingerprint `EB4C1BFD4F042F6DDDCCEC917721F63BD38B4796`. It then
   checks the SHA-256 of `Packages` and of the `.deb`.
3. If the upstream version is newer, builds the RPM as a sandboxed `DynamicUser`.

Logs: `journalctl -u chrome-remote-desktop-update`. There is no rollback. If a
new upstream release installs but doesn't start, fix it at the machine.

Recipe changes (anything in this repo) are not picked up automatically. Rebuild
with a higher `RELEASE` and install by hand:

```sh
RELEASE=5 ./build.sh && sudo dnf upgrade dist/chrome-remote-desktop-*.rpm
```

## Uninstall

```sh
sudo dnf remove chrome-remote-desktop
sudo rm -rf /etc/chrome-remote-desktop
flatpak permission-remove kde-authorized remote-desktop com.google.ChromeRemoteDesktop
```

Then remove the machine at <https://remotedesktop.google.com/access>.

## License

The recipe in this repository is MIT-licensed (see `LICENSE`). That covers only
these files, not Google's Chrome Remote Desktop software, which stays under
Google's terms.
