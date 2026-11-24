# AGENTS.md

A recipe that repackages Google's Chrome Remote Desktop host `.deb` as a Fedora RPM,
with two KDE fixes (a monitor byte patch and a portal session reaper), a self-updater
that follows signed release tags, and a CI workflow that watches upstream. See README.md for the user-facing picture.

## Hard rules

- **Never commit, upload or publish built RPMs, `.deb`s or extracted binaries**
  (no release assets, CI artifacts, package repos, or binary dumps in public CI logs). Google's ToS forbids redistribution;
  this repo holds only our own files. `dist/` is gitignored.
- The updater fetches only from `dl.google.com` and this repo's GitHub URL, over https.
  It builds only the newest `v<version>-<release>` tag, and only after `verify_tag` passes:
  an SSH signature by a key in the *installed* `allowed_signers`, and a signed tag name equal
  to the ref. It then verifies `Release.gpg` → `Release` → `Packages` SHA-256 → `.deb`
  SHA-256. Don't loosen the pinned fingerprint, the signer check, version/tag/filename
  validation or `--proto =https`, and never fall back to an older tag when the newest fails.
- The tag-signing key is effectively root on the box: a tag it signs gets built and installed.
- A refusing monitor patch fails the build. Every version is approved by a human tag and
  CI sees the refusal first, so there is no unattended fallback.

## Commands

```sh
./build.sh                         # download current .deb, build into dist/ (RELEASE=1)
git tag -s v159.0.8154.7-2 && git push origin v159.0.8154.7-2   # approve: the box builds it
RELEASE=5 ./build.sh               # bump RELEASE for any recipe change to an already-built version
./build.sh path/to.deb outdir      # how crd-update calls it
tests/run.sh                       # fast checks: version compare, Packages parser, tags, reaper
tests/run.sh path/to/crd.deb       # also checks the monitor patch against that release
shellcheck -S warning crd-update crd-session-reaper build.sh tests/run.sh
```

Building needs `rpm-build`, `systemd-rpm-macros`, `binutils`, `python3` and `curl`;
the tests also need `git` and `ssh-keygen`.
No root is needed except for `dnf install`.

## Layout

All recipe files sit at the root: the spec lists them as `Source1..12`, `build.sh`
copies them into `SOURCES/`, and the RPM installs them into
`/usr/share/chrome-remote-desktop-rpm/` for the updater. A new recipe file must be added
in all three places (the spec `Source`/`%install` lines and the `cp` list in `build.sh`).

| File | Role |
|------|------|
| `chrome-remote-desktop.spec` | repackaging; `%bcond_without monitor_patch`; generates the `extras.conf` drop-in (`Wants=` reaper + timer) |
| `build.sh` | version normalisation, patch probe, rpmbuild |
| `patch-monitor-source.py` | VIRTUAL→MONITOR byte patch (anchored on the "ScreenCast.SelectSources failed" xrefs) and the per-stream PipeWire connection patch (anchored on "Failed to connect PipeWire context") |
| `crd-session-reaper` + `.service` | kills the idle `--type=desktop` process after the last authenticated client leaves |
| `chrome-remote-desktop-pipewire.conf` | PipeWire client `stream.rules`: capture streams wait for their screencast node instead of falling back to the webcam |
| `crd-update` + `chrome-remote-desktop-update.{service,timer}` | hourly: `install` (root, first), then `build` (DynamicUser) of the newest signed tag; `fetch_index`/`fetch_deb`/`stanza`/`pick_tag` are reused by CI and tests |
| `allowed_signers` | the SSH keys whose tags the updater builds (`ssh-keygen` format, `namespaces="git"`) |
| `.github/workflows/upstream.yml` | every 6 h: build a new upstream in `fedora:latest`, file an issue; on a new failure, claude-code-action pushes a `claude/upstream-<version>` branch |
| `tests/run.sh` | the fast checks above; `crd-update` is sourceable, and the reaper reads stdin with `-` |

## Gotchas

- **No GNU tar in the sandbox for nested paths.** tar 1.35 resolves them via `openat2()`,
  which DynamicUser's implied `RestrictSUIDSGID` answers with ENOSYS ("mkdir: Function not
  implemented"). `%prep` and the probe use Python `tarfile`; `tar -xJ ./control` works only
  because it is top-level.
- **No apostrophes in comments inside the single-quoted awk program** in `crd-update`. They
  end the quote.
- **`newer()` evaluates its arguments as Lua.** Check anything from the network (tag names)
  against `tag_re` first; `pick_tag` does.
- **A tag signature covers the name inside the tag object, not the ref.** A signed object can
  be republished under a higher ref name; `verify_tag` compares the two.
- **`install()` discards RPMs without `allowed_signers`.** That blocks RPMs built by the
  pre-tag updater, which would otherwise bring it back.
- **GitHub disables the scheduled workflow after 60 days without repo activity** (it emails
  first). Re-enable it in the Actions tab.
- **The CI fix job uses `CLAUDE_CODE_OAUTH_TOKEN`** (from `claude setup-token`) and runs only
  for a newly filed failure issue. A final step deletes any `claude/*` branch that adds
  binary files.
- **Session detection:** a `--type=peer_connection` process exists only while a client is
  connected. The legacy `chrome-remote-desktop@` host has none (a known limit).
- **Reaper input:** connect/disconnect lines come from the `chromoting` syslog identifier
  (HostEventLogger), which logs only authenticated clients. `peer_session_impl` logs
  "Client disconnected" for failed PINs too; don't match on it.
- **Multi-monitor needs one PipeWire connection per stream.** With MONITOR, KDE returns a
  stream per screen; webrtc connects each via `pw_context_connect_fd` on a dup of the same
  portal fd, and the second `pw_core` sync never completes (host hangs after one "Stream N
  added"). The patcher forces the `pw_context_connect` (default socket) branch. Don't try
  `multiple: false` instead: KDE then sends one workspace stream with no `mapping_id`, and
  every pointer move is dropped ("No absolute pointer for the requested region").
- **Stream props belong in PipeWire's `client.conf.d`, not WirePlumber's.** WirePlumber's
  `stream.rules` only feed its audio state restore; the linking policy never sees them.
- **Interactive shells may export `SYSTEMD_COLORS=1`,** making `journalctl -o cat` show ANSI
  escapes that are not in the stored message.
- **The portal app ID is `com.google.ChromeRemoteDesktop`** since 159 (Host.Registry.Register,
  backed by the shipped `.desktop` file). Before that it was `""`, because the daemon moves
  the desktop process into `session-N.scope`.
- **Anything run under `pkexec` starts in `/root`,** so pass absolute paths.
- **The first tag after a change is the first live run** of the install path
  (`dnf install` as root). Test changes to `crd-update install` carefully.

## Testing a change

1. Run `tests/run.sh` (and with a `.deb` if the patcher or build changed).
2. To exercise the sandbox, run the build step in a matching transient unit.
   Make `installed()` return 0 in a world-readable copy of the recipe, then:
   `systemd-run --wait --pipe --collect -p DynamicUser=yes -p CacheDirectory=crd-update-test -p BindReadOnlyPaths=<copy>:/run/crd-test -p ProtectHome=yes -p NoNewPrivileges=yes /usr/bin/bash /run/crd-test/crd-update build`
   (as root). Clean `/var/cache/private/crd-update-test` afterwards.
3. Check `rpm -qpl dist/*.rpm` and the installed package's `rpm -ql` for unexpected path changes.

## Git

Conventional commits, 50/72. Bump the spec `%changelog` and use a new `RELEASE` for any
change that affects the installed package. The box picks it up only once the commit is
tagged `v<version>-<RELEASE>` with a signed tag; tag only what you have tested on the box.
