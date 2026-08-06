"""ywr2xml - binary GTA V .ywr (WaypointRecordList, RSC7 v1)  ->  RAGE interchange .ywr.xml

Clean-room: derived ONLY from oracle XML + game binaries + our own quarry code (Res reader,
meta2xml.fmt_num float law). No any third-party tool / RAGE-internal source consulted.

CONTAINER: RSC7 version 1, system segment only (gfx empty). System-segment layout:
    0x00  u64   vtable (unresolved runtime pointer - ignored)
    0x08  ptr   tagged -> byte just past the record array (unused)
    0x18  ptr   tagged -> RECORD ARRAY (tag 5 = system segment)
    0x20  u16   record COUNT
The record array is a flat fixed-stride table. STRIDE = 20 bytes:
    +0x00 f32   Position.x   +0x04 f32 Position.y   +0x08 f32 Position.z
    +0x0C u16   Unk0   (always 128 in evidence)
    +0x0E u16   Unk1
    +0x10 u16   Unk2   (always 0 in evidence)
    +0x12 u16   Unk3   (always 0 in evidence)

Unk0..Unk3 are emitted as plain integers. Unk0/Unk2/Unk3 constant in the evidence, so their
exact width (u16 vs signed/other) is UNPINNED beyond "reproduces these files"; Unk1 spans
1518..27057 which fits and requires an unsigned 16-bit read.
"""
import os
import struct
import sys

QUARRY = r"B:\ClaudeCode_Projects\_UEFiveMTool\quarry"
sys.path.insert(0, QUARRY)
from ydr2xml import Res          # noqa: E402  (RSC7 container reader - REUSED)
from meta2xml import fmt_num     # noqa: E402  (float spelling law - REUSED)


def ywr_to_xml(res):
    """`res` is a Res (RSC7). Returns the .ywr.xml text with LF newlines + trailing LF."""
    if res.version != 1:
        raise ValueError("ywr expects RSC7 version 1, got %d" % res.version)
    b = res.sys
    arr = res.u32(0x18) & 0x0FFFFFFF
    count = res.u16(0x20)
    out = ['<?xml version="1.0" encoding="UTF-8"?>', '<WaypointRecordList>']
    for i in range(count):
        o = arr + i * 20
        px, py, pz = struct.unpack_from('<3f', b, o)
        u0, u1, u2, u3 = struct.unpack_from('<4H', b, o + 0x0C)
        out.append(' <Item>')
        out.append('  <Position x="%s" y="%s" z="%s" />' % (fmt_num(px), fmt_num(py), fmt_num(pz)))
        out.append('  <Unk0 value="%d" />' % u0)
        out.append('  <Unk1 value="%d" />' % u1)
        out.append('  <Unk2 value="%d" />' % u2)
        out.append('  <Unk3 value="%d" />' % u3)
        out.append(' </Item>')
    out.append('</WaypointRecordList>')
    return '\n'.join(out) + '\n'


if __name__ == '__main__':
    r = Res(sys.argv[1])
    txt = ywr_to_xml(r)
    if len(sys.argv) > 2:
        open(sys.argv[2], 'w', encoding='utf-8', newline='\n').write(txt)
    else:
        sys.stdout.write(txt)
