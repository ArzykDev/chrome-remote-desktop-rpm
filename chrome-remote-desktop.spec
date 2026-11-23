# Repackages Google's official chrome-remote-desktop .deb; nothing is rebuilt.
%global debug_package %{nil}
%global _build_id_links none
%global __strip /bin/true
%global crd_dir /opt/google/chrome-remote-desktop
%global recipe_dir %{_datadir}/chrome-remote-desktop-rpm
# build.sh falls back to --without monitor_patch when the patcher refuses.
%bcond_without monitor_patch
# Bundled libs are private ($ORIGIN rpath), so don't export or require them.
%global __provides_exclude_from ^%{crd_dir}/.*$
%global __requires_exclude ^libremoting_core\\.so.*$

Name:           chrome-remote-desktop
Version:        %{crd_version}
# Packaging revision; build.sh passes RELEASE (default 1) per upstream version.
Release:        %{?crd_release}%{!?crd_release:1}%{?dist}
Summary:        Chrome Remote Desktop host (repackaged official Debian build)
License:        LicenseRef-Google-Chrome-Remote-Desktop
URL:            https://remotedesktop.google.com/
Source0:        chrome-remote-desktop_%{version}_amd64.deb
Source1:        chrome-remote-desktop.pam
Source2:        chrome-remote-desktop.sysusers
Source3:        patch-monitor-source.py
Source4:        crd-session-reaper
Source5:        chrome-remote-desktop-reaper.service
Source6:        chrome-remote-desktop.spec
Source7:        build.sh
Source8:        crd-update
Source9:        chrome-remote-desktop-update.service
Source10:       chrome-remote-desktop-update.timer
Source11:       chrome-remote-desktop-pipewire.conf
ExclusiveArch:  x86_64

BuildRequires:  binutils
BuildRequires:  python3
BuildRequires:  systemd-rpm-macros
Requires:       python3
# The updater rebuilds this package from the recipe shipped in %%{recipe_dir}.
Requires:       binutils
Requires:       curl
Requires:       gnupg2
Requires:       rpm-build
Requires:       systemd-rpm-macros
Requires:       python3-dbus
Requires:       python3-packaging
Requires:       python3-psutil
Requires:       python3-pyxdg
Requires:       polkit
Requires:       procps-ng
Requires(posttrans): procps-ng
Requires(posttrans): systemd
Requires:       xdg-utils
Requires:       pipewire
%{?sysusers_requires_compat}
# Only the legacy virtual-session mode (chrome-remote-desktop@.service) needs X.
Suggests:       xorg-x11-server-Xvfb
Suggests:       xorg-x11-xauth

%description
Host component of Chrome Remote Desktop, extracted unmodified from Google's
official .deb. Adds a Fedora PAM stack and sysusers config, and drops the
Debian-only apt repository cron job.

Two KDE fixes: libremoting_core.so is byte-patched to capture the real
monitors instead of creating a virtual output (each monitor's stream then
connects to the user's default PipeWire socket rather than sharing the
portal's restricted one), and a reaper service ends the portal session when
the client disconnects.

An hourly timer verifies Google's signed apt metadata, rebuilds this package
from the recipe in %{recipe_dir} when a new version appears, and installs it
when no session is active. Nothing is downloaded from anywhere but Google.

%prep
%setup -c -T
ar x %{SOURCE0}
# Not tar: GNU tar 1.35 resolves nested paths via openat2(), which the
# updater's sandbox (RestrictSUIDSGID) answers with ENOSYS.
python3 -c 'import sys, tarfile; tarfile.open(sys.argv[1]).extractall("root", filter="data")' data.tar.*
%if %{with monitor_patch}
python3 %{SOURCE3} root%{crd_dir}/libremoting_core.so
%endif

%build

%install
cp -a root/opt %{buildroot}/
install -Dm644 -t %{buildroot}%{_sysconfdir}/opt/chrome/native-messaging-hosts \
    root/etc/opt/chrome/native-messaging-hosts/*.json
install -Dm644 -t %{buildroot}%{_prefix}/lib/mozilla/native-messaging-hosts \
    root/usr/lib/mozilla/native-messaging-hosts/*.json
# 159 moved the daemon unit from /lib to /usr/lib; the glob in %files would hide its loss.
find root/lib/systemd/system root/usr/lib/systemd/system -name '*.service' 2>/dev/null \
    -exec install -Dm644 -t %{buildroot}%{_unitdir} {} +
test -f %{buildroot}%{_unitdir}/chrome-remote-desktop.service
install -Dm644 -t %{buildroot}%{_userunitdir} root/usr/lib/systemd/user/*.service
install -Dm644 -t %{buildroot}%{_datadir}/wireplumber/wireplumber.conf.d \
    root/usr/share/wireplumber/wireplumber.conf.d/*.conf
install -Dm644 -t %{buildroot}%{_datadir}/applications \
    root/usr/share/applications/*.desktop
install -Dm644 %{SOURCE1} %{buildroot}%{_sysconfdir}/pam.d/chrome-remote-desktop
install -Dm644 %{SOURCE2} %{buildroot}%{_sysusersdir}/chrome-remote-desktop.conf
install -dm755 %{buildroot}%{_sysconfdir}/chrome-remote-desktop
install -Dm755 %{SOURCE4} %{buildroot}%{crd_dir}/crd-session-reaper
install -Dm644 -t %{buildroot}%{_unitdir} %{SOURCE5} %{SOURCE9} %{SOURCE10}
install -Dm644 %{SOURCE11} %{buildroot}%{_datadir}/pipewire/client.conf.d/chrome-remote-desktop.conf
install -Dm644 -t %{buildroot}%{recipe_dir} %{SOURCE1} %{SOURCE2} %{SOURCE5} %{SOURCE6} %{SOURCE9} %{SOURCE10} %{SOURCE11}
install -Dm755 -t %{buildroot}%{recipe_dir} %{SOURCE3} %{SOURCE4} %{SOURCE7} %{SOURCE8}
# Pull the reaper and updater in with the daemon, so upgrades need no enable step.
install -dm755 %{buildroot}%{_unitdir}/chrome-remote-desktop.service.d
printf '[Unit]\nWants=chrome-remote-desktop-reaper.service chrome-remote-desktop-update.timer\n' \
    > %{buildroot}%{_unitdir}/chrome-remote-desktop.service.d/extras.conf

%pre
%sysusers_create_compat %{SOURCE2}

%post
%systemd_post chrome-remote-desktop.service
# Debian enables this globally; it is a no-op outside CRD-created sessions.
if [ $1 -eq 1 ]; then
    systemctl --global enable chrome-remote-desktop-environment.service >/dev/null 2>&1 || :
fi

%preun
%systemd_preun chrome-remote-desktop.service chrome-remote-desktop-reaper.service chrome-remote-desktop-update.timer
if [ $1 -eq 0 ]; then
    systemctl stop 'chrome-remote-desktop@*' 'chrome-remote-desktop-x11-session@*' >/dev/null 2>&1 || :
    systemctl --global disable chrome-remote-desktop-environment.service >/dev/null 2>&1 || :
fi

%postun
%systemd_postun chrome-remote-desktop.service chrome-remote-desktop-reaper.service chrome-remote-desktop-update.timer

%posttrans
# Same as the .deb's postinst: SIGUSR2 makes host processes exit cleanly and
# their supervisors relaunch them on the new binaries; sessions survive.
pkill -USR2 -f '^%{crd_dir}/' >/dev/null 2>&1 || :
# The daemon unit is Restart=on-abnormal, so a clean exit needs a manual
# start. Wait for it to go down; restart also covers one that never exits.
if systemctl -q is-enabled chrome-remote-desktop.service 2>/dev/null; then
    for i in $(seq 60); do
        systemctl -q is-active chrome-remote-desktop.service || break
        sleep 0.5
    done
    systemctl daemon-reload >/dev/null 2>&1 || :
    systemctl restart chrome-remote-desktop.service >/dev/null 2>&1 || :
fi

%files
%{crd_dir}
%dir %{_sysconfdir}/chrome-remote-desktop
%config(noreplace) %{_sysconfdir}/pam.d/chrome-remote-desktop
%config(noreplace) %{_sysconfdir}/opt/chrome/native-messaging-hosts/*.json
%{_prefix}/lib/mozilla/native-messaging-hosts/*.json
%{_unitdir}/*.service
%{_unitdir}/chrome-remote-desktop-update.timer
%dir %{_unitdir}/chrome-remote-desktop.service.d
%{_unitdir}/chrome-remote-desktop.service.d/extras.conf
%{recipe_dir}
%{_userunitdir}/chrome-remote-desktop-environment.service
%{_datadir}/wireplumber/wireplumber.conf.d/chrome-remote-desktop.conf
%{_datadir}/pipewire/client.conf.d/chrome-remote-desktop.conf
%{_datadir}/applications/*.desktop
%{_sysusersdir}/chrome-remote-desktop.conf

%changelog
* Mon Nov 23 2026 ArzykDev <hello@arzyk.me> - 159.0.8154.7-1
- Package every .desktop file; 159 adds com.google.ChromeRemoteDesktop
  for portal app ID registration
- Match the PipeWire fd test when the fd is spilled to the stack
- Install units from /usr/lib too; 159 moved the daemon unit there

* Wed Nov 04 2026 ArzykDev <hello@arzyk.me> - 157.0.8103.19-7
- Stop capture streams falling back to the webcam when their
  screencast node is briefly missing

* Sun Nov 01 2026 ArzykDev <hello@arzyk.me> - 157.0.8103.19-6
- Give each screencast stream its own PipeWire connection; two
  monitors hung the host

* Wed Oct 28 2026 ArzykDev <hello@arzyk.me> - 157.0.8103.19-5
- Make crd-update sourceable and give the reaper a stdin mode for tests

* Wed Oct 28 2026 ArzykDev <hello@arzyk.me> - 157.0.8103.19-4
- Updater: install before build, skip stale RPMs, filter by package name
- Fall back to an unpatched build only when the patcher refuses
- Own the unit drop-in directory

* Wed Oct 28 2026 ArzykDev <hello@arzyk.me> - 157.0.8103.19-3
- Ship the build recipe and an hourly self-update timer
- Fall back to an unpatched build if the monitor patch no longer applies

* Wed Oct 28 2026 ArzykDev <hello@arzyk.me> - 157.0.8103.19-2
- Capture real monitors instead of a virtual output on non-GNOME Wayland
- Add reaper service that ends the portal session on client disconnect

* Wed Oct 28 2026 ArzykDev <hello@arzyk.me> - 157.0.8103.19-1
- Initial repackage of the official .deb
