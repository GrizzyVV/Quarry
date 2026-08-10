"""yvr2xml - binary GTA V .yvr (VehicleRecordList, RSC7 v1)  ->  RAGE interchange .yvr.xml

Clean-room: derived ONLY from oracle XML + game binaries + our own quarry code (Res reader,
meta2xml.fmt_num float law). No any third-party tool / RAGE-internal source consulted.

CONTAINER: RSC7 version 1, system segment only (gfx empty). System-segment layout:
    0x00  u64   vtable (unresolved runtime pointer - ignored)
    0x08  ptr   tagged -> byte just past the record array (unused)
    0x10  ptr   tagged -> RECORD ARRAY (tag 5 = system segment)
    0x18  u16   record COUNT      0x1a u16 capacity
The record array is a flat fixed-stride table. STRIDE = 32 bytes:
    +0x00 i32   Time (ms)
    +0x04 i16   Velocity.x      +0x06 i16 Velocity.y   +0x08 i16 Velocity.z   (* VEL_SCALE)
    +0x0A i8    Right.x         +0x0B i8  Right.y       +0x0C i8  Right.z      (/ 127)
    +0x0D i8    Forward.x       +0x0E i8  Forward.y     +0x0F i8  Forward.z    (/ 127)
    +0x10 i8    Steering        (* 0.05 - pinned 2026-08-09, pilotschool140)
    +0x11 u8    GasPedal        (/ 100)
    +0x12 u8    BrakePedal      (/ 100 - all 0 in evidence)
    +0x13 u8    Handbrake       (0 -> "False", nonzero -> "True")
    +0x14 f32   Position.x      +0x18 f32 Position.y    +0x1C f32 Position.z

SCALES (empirically pinned by value-intersection against the oracle):
  Velocity: int16 * (1/273.05828857421875) -- a DOUBLE constant; no float32 multiplier
            reproduces the oracle. Interval re-pinned 2026-08-09 over 11,511 samples /
            7,602 distinct raws (8 pilotschool + 5 base witnesses): admissible multiply
            interval [0.0036622217373970226, 0.0036622217374240669]; the previous constant
            0.0036622217367 (from a 228-pair interval) sat BELOW it and rounded 20 raws one
            float32 step low. 1/273.05828857421875 = 0.0036622217374229038 is inside and
            reproduces all 11,511 spellings exactly (273.05828857421875 is float32-exact).
  Forward/Right: int8 * (1/127.0)     -- 0/456 mismatches.
  Steering: int8 * 0.05               -- pinned 2026-08-09 on pilotschool140 (the first
            witness with nonzero steering: raws {-1,1,2,3} -> oracle -0.05/0.05/0.1/0.15;
            the old 1/127 guess produced 0.007874016). Larger raws unwitnessed.
  GasPedal: u8 / 100.0                -- e.g. 100->1, 95->0.95, 64->0.64.
EMPTY LIST: count==0 emits the self-closing root '<VehicleRecordList />' (measured: all six
  58-byte stub yvr oracles, both slots).
"""
import os
import struct
import sys

QUARRY = r"B:\ClaudeCode_Projects\_UEFiveMTool\quarry"
sys.path.insert(0, QUARRY)
from ydr2xml import Res          # noqa: E402  (RSC7 container reader - REUSED)
from meta2xml import fmt_num     # noqa: E402  (float spelling law - REUSED)

VEL_SCALE = 1.0 / 273.05828857421875   # double; see header - inside the 11,511-sample interval
DIR_SCALE = 1.0 / 127.0
STEER_SCALE = 0.05
GAS_SCALE = 1.0 / 100.0


def yvr_to_xml(res):
    """`res` is a Res (RSC7). Returns the .yvr.xml text with LF newlines + trailing LF."""
    if res.version != 1:
        raise ValueError("yvr expects RSC7 version 1, got %d" % res.version)
    b = res.sys
    arr = res.u32(0x10) & 0x0FFFFFFF
    count = res.u16(0x18)
    if count == 0:
        return ('<?xml version="1.0" encoding="UTF-8"?>\n'
                '<VehicleRecordList />\n')
    out = ['<?xml version="1.0" encoding="UTF-8"?>', '<VehicleRecordList>']
    for i in range(count):
        o = arr + i * 32
        time = struct.unpack_from('<i', b, o)[0]
        vx, vy, vz = struct.unpack_from('<3h', b, o + 0x04)
        rx, ry, rz = struct.unpack_from('<3b', b, o + 0x0A)
        fx, fy, fz = struct.unpack_from('<3b', b, o + 0x0D)
        steer = struct.unpack_from('<b', b, o + 0x10)[0]
        gas, brake, hbrake = struct.unpack_from('<3B', b, o + 0x11)
        px, py, pz = struct.unpack_from('<3f', b, o + 0x14)
        out.append(' <Item>')
        out.append('  <Time value="%d" />' % time)
        out.append('  <Position x="%s" y="%s" z="%s" />' % (fmt_num(px), fmt_num(py), fmt_num(pz)))
        out.append('  <Velocity x="%s" y="%s" z="%s" />'
                   % (fmt_num(vx * VEL_SCALE), fmt_num(vy * VEL_SCALE), fmt_num(vz * VEL_SCALE)))
        out.append('  <Forward x="%s" y="%s" z="%s" />'
                   % (fmt_num(fx * DIR_SCALE), fmt_num(fy * DIR_SCALE), fmt_num(fz * DIR_SCALE)))
        out.append('  <Right x="%s" y="%s" z="%s" />'
                   % (fmt_num(rx * DIR_SCALE), fmt_num(ry * DIR_SCALE), fmt_num(rz * DIR_SCALE)))
        out.append('  <Steering value="%s" />' % fmt_num(steer * STEER_SCALE))
        out.append('  <GasPedal value="%s" />' % fmt_num(gas * GAS_SCALE))
        out.append('  <BrakePedal value="%s" />' % fmt_num(brake * GAS_SCALE))
        out.append('  <Handbrake value="%s" />' % ('True' if hbrake else 'False'))
        out.append(' </Item>')
    out.append('</VehicleRecordList>')
    return '\n'.join(out) + '\n'


if __name__ == '__main__':
    r = Res(sys.argv[1])
    txt = yvr_to_xml(r)
    if len(sys.argv) > 2:
        open(sys.argv[2], 'w', encoding='utf-8', newline='\n').write(txt)
    else:
        sys.stdout.write(txt)
