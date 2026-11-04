#!/bin/bash
# Builds the RPM from the official .deb. Without arguments it downloads the
# current .deb into ./dist (manual use); crd-update passes a verified .deb.
# Usage: build.sh [deb [outdir]]
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
out=${2:-$here/dist}
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

if [[ ${1:-} ]]; then
    cp "$1" "$work/crd.deb"
else
    curl -sSfL -o "$work/crd.deb" https://dl.google.com/linux/direct/chrome-remote-desktop_current_amd64.deb
fi
(cd "$work" && ar p crd.deb control.tar.xz | tar -xJ ./control)
version=$(sed -n 's/^Version: //p' "$work/control")
# RPM Version can't hold a Debian epoch or revision.
version=${version#*:}
version=${version%%-*}
[[ $version =~ ^[0-9][0-9.]*$ ]] || { echo "unexpected upstream version: $version" >&2; exit 1; }
mkdir -p "$work/SOURCES"
mv "$work/crd.deb" "$work/SOURCES/chrome-remote-desktop_${version}_amd64.deb"
cp "$here"/{chrome-remote-desktop.{spec,pam,sysusers},patch-monitor-source.py,crd-session-reaper,crd-update,build.sh,chrome-remote-desktop-pipewire.conf,*.service,*.timer} \
    "$work/SOURCES/"

# Try the patch on a scratch copy first: if it refuses, build unpatched, since a
# security update must not wait on the cosmetic patch. Other failures still fail.
patch_opt=()
ar p "$work/SOURCES/chrome-remote-desktop_${version}_amd64.deb" data.tar.xz > "$work/data.tar.xz"
python3 -c 'import sys, tarfile; tarfile.open(sys.argv[1]).extract(
    "./opt/google/chrome-remote-desktop/libremoting_core.so", sys.argv[2], filter="data")' \
    "$work/data.tar.xz" "$work/probe"
if ! python3 "$here/patch-monitor-source.py" "$work/probe/opt/google/chrome-remote-desktop/libremoting_core.so"; then
    echo "WARNING: monitor patch no longer applies; building without it (virtual-monitor mode)" >&2
    patch_opt=(--without monitor_patch)
fi
rm -rf "$work/data.tar.xz" "$work/probe"

rpmbuild -bb --define "_topdir $work" --define "crd_version $version" \
    --define "crd_release ${RELEASE:-1}" "${patch_opt[@]}" "$work/SOURCES/chrome-remote-desktop.spec"
mkdir -p "$out"
cp "$work"/RPMS/x86_64/*.rpm "$out/"
echo "Built $version"
