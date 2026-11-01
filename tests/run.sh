#!/bin/bash
# Fast checks for the updater and reaper logic. With a .deb argument it also
# checks the monitor patch against that release:
#   tests/run.sh [chrome-remote-desktop_<ver>_amd64.deb]
set -uo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
deb=${1:-}
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
fail=0
check() {  # check NAME EXPECTED ACTUAL
    if [[ $2 == "$3" ]]; then echo "ok   $1"; else echo "FAIL $1: expected [$2], got [$3]"; fail=1; fi
}

# shellcheck source=../crd-update
source "$root/crd-update"
set +e

for c in "158.0.1 157.0.8103.19 y" "157.0.8103.19 157.0.8103.19 n" "157.0.8103.100 157.0.8103.19 y" \
         "155.0.8059.19 157.0.8103.19 n" "157.0.8103.19-4.fc44 157.0.8103.19-3.fc44 y" "157.0.8103.19 0 y"; do
    set -- $c
    newer "$1" "$2" && got=y || got=n
    check "newer $1 > $2" "$3" "$got"
done

cat > "$tmp/Packages" <<'EOF'
Package: chrome-remote-desktop-beta
Version: 999.0
Filename: pool/x.deb
SHA256: aa

Package: chrome-remote-desktop
Version: 1:157.0.8103.19-1
Filename: pool/main/c/chrome-remote-desktop/chrome-remote-desktop_157.0.8103.19-1_amd64.deb
SHA256: bb

Package: chrome-remote-desktop
Version: 155.0.8059.19
Filename: pool/main/c/chrome-remote-desktop/chrome-remote-desktop_155.0.8059.19_amd64.deb
SHA256: cc
EOF
check "latest_stanza skips other packages, strips epoch/revision" \
    "157.0.8103.19 pool/main/c/chrome-remote-desktop/chrome-remote-desktop_157.0.8103.19-1_amd64.deb bb" \
    "$(latest_stanza "$tmp/Packages")"

# Reaper: a fake pkill records kills; events are fed on stdin with a 1 s quiet period.
mkdir "$tmp/bin"
printf '#!/bin/sh\necho kill >> "%s/kills"\n' "$tmp" > "$tmp/bin/pkill"
chmod +x "$tmp/bin/pkill"
reap() {  # reap EVENTS...: "c" connect, "d" disconnect, "s" sleep 1.5 s
    rm -f "$tmp/kills"
    for e in "$@"; do
        case $e in
            c) echo "Client connected: x" ;;
            d) echo "Client disconnected: x" ;;
            s) sleep 1.5 ;;
        esac
    done | PATH=$tmp/bin:$PATH CRD_REAPER_QUIET=1 "$root/crd-session-reaper" -
    if [[ -f $tmp/kills ]]; then wc -l < "$tmp/kills"; else echo 0; fi
}
check "reaper kills after the last client leaves" 1 "$(reap c s d s)"
check "reaper survives a reconnect within the quiet period" 0 "$(reap c d c s)"
check "reaper keeps a session while another client stays" 0 "$(reap c c d s)"
check "reaper ignores a disconnect without a connect, then clamps" 1 "$(reap d s)"

if [[ $deb ]]; then
    ar p "$deb" data.tar.xz > "$tmp/data.tar.xz"
    python3 -c 'import sys, tarfile; tarfile.open(sys.argv[1]).extract(
        "./opt/google/chrome-remote-desktop/libremoting_core.so", sys.argv[2], filter="data")' \
        "$tmp/data.tar.xz" "$tmp/x"
    lib=$tmp/x/opt/google/chrome-remote-desktop/libremoting_core.so
    cp "$lib" "$tmp/orig.so"
    python3 "$root/patch-monitor-source.py" "$lib" >/dev/null && got=patched || got=refused
    check "monitor patch applies" patched "$got"
    check "patch changes exactly 8 bytes" 8 "$(cmp -l "$tmp/orig.so" "$lib" | wc -l)"
    check "PipeWire fd test je became jmp" 1 "$(cmp -l "$tmp/orig.so" "$lib" | grep -c ' 164 353$')"
    python3 "$root/patch-monitor-source.py" "$lib" >/dev/null 2>&1 && got=patched || got=refused
    check "patcher refuses an already patched lib" refused "$got"
    # Undo only the jmp, so the types-select check alone has to refuse.
    off=$(cmp -l "$tmp/orig.so" "$lib" | awk '$3 == 353 {print $1 - 1}')
    printf '\x74' | dd of="$lib" bs=1 seek="$off" conv=notrunc status=none
    python3 "$root/patch-monitor-source.py" "$lib" >/dev/null 2>&1 && got=patched || got=refused
    check "patcher refuses a lib with only the types select patched" refused "$got"
fi

exit $fail
