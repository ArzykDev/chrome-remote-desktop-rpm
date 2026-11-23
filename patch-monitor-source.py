#!/usr/bin/env python3
"""Make the portal host capture real monitors instead of a virtual one.

PortalCaptureStreamManager::Init() computes the ScreenCast source type as
`create_virtual_monitor ? VIRTUAL(4) : MONITOR(1)`, which clang emits as
`lea rX,[rax+rax*2]; inc rX`. Only it2me turns the virtual monitor off, so
me2me on KDE always gets a new virtual output. The pair is replaced with
`mov rX,1` (mov leaves CF alone, like lea).

With MONITOR, KDE returns one stream per screen, and webrtc connects each one
with pw_context_connect_fd() on a dup of the same portal fd; the second pw_core
never gets its sync reply and the host hangs (see AGENTS.md). The `je` taken
when fd == -1 becomes `jmp`, so every stream uses the default PipeWire socket.

Fails loudly if the code shape changes.
"""
import re
import struct
import subprocess
import sys

path = sys.argv[1]
data = bytearray(open(path, "rb").read())

out = subprocess.run(["readelf", "-lW", path], capture_output=True, text=True, check=True).stdout
segments = [
    (int(off, 16), int(va, 16), int(size, 16), "E" in flags)
    for off, va, size, flags in re.findall(
        r"LOAD\s+(0x\w+)\s+(0x\w+)\s+\S+\s+(0x\w+)\s+\S+\s+([RWE ]+?)\s+0x", out
    )
]


def vaddr(file_off):
    for off, va, size, _ in segments:
        if off <= file_off < off + size:
            return va + file_off - off
    raise SystemExit(f"offset {file_off:#x} not in a LOAD segment")


def xrefs_to(string):
    found = [m.start() for m in re.finditer(re.escape(string), data)]
    if len(found) != 1:
        raise SystemExit(f"expected one {string!r}, found {len(found)}")
    target = vaddr(found[0])
    refs = []
    for off, va, size, executable in segments:
        if not executable:
            continue
        text = bytes(data[off : off + size])
        for m in re.finditer(rb"[\x48\x4c]\x8d[\x05\x0d\x15\x1d\x25\x2d\x35\x3d]", text):
            i = m.start()
            if i + 7 <= len(text) and va + i + 7 + struct.unpack_from("<i", text, i + 3)[0] == target:
                refs.append(off + i)
    if not refs or refs[-1] - refs[0] > 0x1000:
        raise SystemExit(f"xrefs to {string!r} missing or not in one function: {[hex(x) for x in refs]}")
    return refs


xrefs = xrefs_to(b"ScreenCast.SelectSources failed\0")
pw_xref = xrefs_to(b"Failed to connect PipeWire context\0")[0]
# cmp edi,-1; je else; mov esi,F_DUPFD_CLOEXEC: the fd != kInvalidPipeWireFd test.
# Since 159 the fd lives on the stack: cmp [rbp+d],-1; je; mov edi,[rbp+d]; mov esi,...
base = pw_xref - 0x200
fd_test = list(re.finditer(
    rb"\x83(?:[\xf8-\xff]|\xbd(....))\xff(\x74).(?:\x8b\xbd\1)?\xbe\x06\x04\x00\x00", data[base:pw_xref], re.S
))
if len(fd_test) != 1:
    raise SystemExit(f"expected one PipeWire fd test before its error, found {len(fd_test)}")
je_off = base + fd_test[0].start(2)

lo = xrefs[0] - 0x400
window = bytes(data[lo : xrefs[-1] + 0x400])
# lea r32,[rax+rax*2] then inc of the same register.
pattern = rb"([\x40-\x4f]?)\x8d([\x04\x0c\x14\x1c\x24\x2c\x34\x3c])\x40([\x40-\x4f]?)\xff([\xc0-\xc7])"
hits = []
for m in re.finditer(pattern, window):
    lea_rex = m.group(1)[0] if m.group(1) else 0
    inc_rex = m.group(3)[0] if m.group(3) else 0
    reg = ((m.group(2)[0] >> 3) & 7) | (8 if lea_rex & 0x4 else 0)
    inc_reg = (m.group(4)[0] & 7) | (8 if inc_rex & 0x1 else 0)
    if reg == inc_reg:
        hits.append((m, reg))
if len(hits) != 1:
    raise SystemExit(f"expected exactly one types select near anchor, found {len(hits)}")

m, reg = hits[0]
start, length = lo + m.start(), m.end() - m.start()
mov = (b"\x41" if reg >= 8 else b"") + bytes([0xB8 + (reg & 7)]) + struct.pack("<I", 1)
data[start : start + length] = mov + b"\x90" * (length - len(mov))
data[je_off] = 0xEB
open(path, "wb").write(data)
print(f"patched types select at file offset {start:#x}, PipeWire fd test at {je_off:#x}")
