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
  patcher refuses and the build fails; `rpmbuild --without monitor_patch` builds an unpatched
  (virtual-monitor) package by hand.
- **Releases the portal session on disconnect.** Upstream keeps the session (and KDE's
  "remote control active" indicator) open after the client leaves. `crd-session-reaper`
  ends the idle desktop process 10 s after the last authenticated client disconnects.
- **Updates itself, once approved.** An hourly timer looks for a newer SSH-signed release
  tag in this repo, verifies it, builds that tag's recipe against the matching `.deb` from
  Google's signed apt repo, and installs it once no session is active. A CI workflow
  watches Google's repo and files an issue when a new upstream release appears.

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

Upstream releases reach the machine only through a signed release tag
`v<upstream version>-<release>`, for example `v159.0.8154.7-2`:

1. `.github/workflows/upstream.yml` checks Google's repo every 6 hours. When upstream is
   newer than the newest tag, it builds the release with the recipe and files an issue:
   "builds clean, test it, then tag" or "fails to build". On a failure, Claude drafts a
   fix on a `claude/upstream-<version>` branch. Nothing built in CI is uploaded.
2. Test the build on the machine (`./build.sh` and `sudo dnf upgrade dist/*.rpm`), then
   approve it with `git tag -s v<version>-<release> && git push origin v<version>-<release>`.
   A recipe-only change gets the same treatment with a higher release.

`chrome-remote-desktop-update.timer` starts together with the daemon. Each run:

1. Installs an RPM built by an earlier run, if it is still newer than the installed
   package and no session is active.
2. Lists this repo's tags and picks the newest well-formed one. If that is newer than the
   installed package, it clones the tag and checks the signature against
   `/usr/share/chrome-remote-desktop-rpm/allowed_signers` from the installed package. An
   unsigned or foreign-signed newest tag fails the run; it never falls back to an older tag.
3. Fetches `Release` and `Release.gpg`, verifies them against Google's Linux signing key
   (pinned by primary fingerprint `EB4C1BFD4F042F6DDDCCEC917721F63BD38B4796`), then checks
   the SHA-256 of `Packages` and of the tagged version's `.deb`. Google keeps only the two
   newest versions; if the tagged one is gone, the run waits for a newer tag.
4. Builds the tagged recipe as a sandboxed `DynamicUser`.

The signing key is effectively root on the machine: a tag it signs gets built and
installed. To run this from a fork, change `git_url` in `crd-update` and put your own
key in `allowed_signers`.

Logs: `journalctl -u chrome-remote-desktop-update`. There is no rollback; if a release
installs but doesn't start, fix it at the machine.

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
