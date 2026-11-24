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
         "155.0.8059.19 157.0.8103.19 n" "157.0.8103.19-4.fc44 157.0.8103.19-3.fc44 y" "157.0.8103.19 0 y" \
         "159.0.8154.7-2 159.0.8154.7-2.fc45 n" "159.0.8154.7-3 159.0.8154.7-2.fc45 y"; do
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
check "stanza latest skips other packages, strips epoch/revision" \
    "157.0.8103.19 pool/main/c/chrome-remote-desktop/chrome-remote-desktop_157.0.8103.19-1_amd64.deb bb" \
    "$(stanza "$tmp/Packages" latest)"
check "stanza finds an exact version" \
    "155.0.8059.19 pool/main/c/chrome-remote-desktop/chrome-remote-desktop_155.0.8059.19_amd64.deb cc" \
    "$(stanza "$tmp/Packages" 155.0.8059.19)"
check "stanza is empty for a version not in the index" "" "$(stanza "$tmp/Packages" 154.0.1)"

check "pick_tag takes the newest well-formed tag, never evaluating the rest" v10.0-2 "$(pick_tag <<'EOF'
x	refs/tags/v2.0-1
x	refs/tags/v1'x-1
x	refs/tags/v99-1;x
x	refs/tags/v99')os.exit(1)--1
x	refs/tags/v10.0-1
x	refs/tags/v10.0-2
x	refs/tags/latest
EOF
)"
check "pick_tag is empty without release tags" "" "$(pick_tag <<< $'x\trefs/tags/foo')"

# Release tags: throwaway keys, and no user or system git config (no 1Password signer).
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1
ssh-keygen -q -t ed25519 -N '' -C '' -f "$tmp/good"
ssh-keygen -q -t ed25519 -N '' -C '' -f "$tmp/evil"
printf 'test namespaces="git" %s\n' "$(cut -d' ' -f1,2 "$tmp/good.pub")" > "$tmp/allowed"
# shellcheck disable=SC2034 # read by verify_tag
signers=$tmp/allowed
g() { git -C "$tmp/r" -c user.name=t -c user.email=t@t -c gpg.format=ssh "$@"; }
git init -q "$tmp/r"
g commit -q --allow-empty -m x
g -c user.signingkey="$tmp/good.pub" tag -s -m x v1.0-1
g -c user.signingkey="$tmp/evil.pub" tag -s -m x v2.0-1
g tag -a -m x v3.0-1
g update-ref refs/tags/v9.0-1 "$(g rev-parse v1.0-1)"  # a signed object replayed under a newer name
git clone -q --depth 1 --branch v1.0-1 "file://$tmp/r" "$tmp/shallow" 2>/dev/null
for c in "r v1.0-1 ok" "shallow v1.0-1 ok" "r v2.0-1 refused" "r v3.0-1 refused" "r v9.0-1 refused"; do
    set -- $c
    verify_tag "$tmp/$1" "$2" >/dev/null 2>&1 && got=ok || got=refused
    check "verify_tag $2 ($1)" "$3" "$got"
done

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
