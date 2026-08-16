"""ynd2xml - binary GTA V .ynd (RSC7 v1, fwBasePathNodeDict / path nodes) -> RAGE interchange XML.

CLEAN-ROOM: every field below was pinned by value-intersection of the oracle XML against the
game binary (00_base + 10_update), or declared constant/derived where a field could not vary.
No any third-party tool / RAGE source consulted.

Reuses:  Res (RSC7 container + tagged-pointer deref) from ydr2xml;
         fmt_num / esc from meta2xml (the proven float-text + XML-escape laws).
"""
import sys, os, struct

# Counted refusal classes, cleared per file by the caller and folded into the run summary.
RESIDUALS = {}
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ydr2xml import Res
from meta2xml import fmt_num, esc

# ---- position scales (derived: raw s16 * scale reproduces every oracle coord exactly) ----
XY_SCALE = 0.25          # PosX/PosY = s16 / 4     (frac steps of 0.25)
Z_SCALE  = 1.0 / 32.0    # PosZ      = s16 / 32    (frac steps of 0.03125)


def convert(path):
    r = path if hasattr(path, "sys") else Res(path)
    r.require_version(1, ".ynd path node dictionary")

    # -- root fwBasePathNodeDict header (sys offset 0) --
    nodes_ptr = r.ptr(0x10)                 # tagged sys ptr -> node records
    total_nodes = r.u32(0x18)               # node array count (== capacity @0x1c)
    veh_count = r.u32(0x1C)                 # VehicleNodeCount
    ped_count = total_nodes - veh_count     # PedNodeCount (derived; oracle stores no distinct 0)
    links_ptr = r.ptr(0x28)                 # tagged sys ptr -> link records
    total_links = r.u32(0x30)               # link array count

    nbuf, noff = r.deref(nodes_ptr, total_nodes * 40)
    lbuf, loff = r.deref(links_ptr, total_links * 8)
    if nbuf is None:
        raise ValueError("node array does not resolve")
    if lbuf is None and total_links:
        raise ValueError("link array does not resolve")

    out = ['<?xml version="1.0" encoding="UTF-8"?>', '<NodeDictionary>']
    out.append(' <VehicleNodeCount value="%d" />' % veh_count)
    out.append(' <PedNodeCount value="%d" />' % ped_count)
    out.append(' <Nodes>')

    for i in range(total_nodes):
        o = noff + i * 40
        area = struct.unpack_from('<H', nbuf, o + 0x10)[0]
        nid = struct.unpack_from('<H', nbuf, o + 0x12)[0]
        street = struct.unpack_from('<I', nbuf, o + 0x14)[0]
        px = struct.unpack_from('<h', nbuf, o + 0x1C)[0] * XY_SCALE
        py = struct.unpack_from('<h', nbuf, o + 0x1E)[0] * XY_SCALE
        pz = struct.unpack_from('<h', nbuf, o + 0x22)[0] * Z_SCALE
        f0 = nbuf[o + 0x20]
        f1 = nbuf[o + 0x21]            # constant 0 in oracle (unpinned; placed by adjacency)
        f2 = nbuf[o + 0x24]            # constant 0 in oracle (unpinned; placed by adjacency)
        b25 = nbuf[o + 0x25]           # packed: (LinkCount << 3) | Flags5
        f5 = b25 & 0x07
        link_count = b25 >> 3
        f3 = nbuf[o + 0x26]
        f4 = nbuf[o + 0x27]
        link_start = struct.unpack_from('<H', nbuf, o + 0x1A)[0]

        out.append('  <Item>')
        out.append('   <AreaID value="%d" />' % area)
        out.append('   <NodeID value="%d" />' % nid)
        # zero hash = NO street name: the reference writes a self-closing empty element,
        # not hash_00000000 (measured 2026-08-09, 11/11 stage-D witnesses byte-identical
        # once spelled this way; nonzero spelling re-witnessed by nodes555 both slots)
        out.append('   <StreetName />' if street == 0
                   else '   <StreetName>hash_%08X</StreetName>' % street)
        out.append('   <Position x="%s" y="%s" z="%s" />' % (_pos_i(nbuf, o + 0x1C, XY_SCALE),
                                                             _pos_i(nbuf, o + 0x1E, XY_SCALE),
                                                             _pos_i(nbuf, o + 0x22, Z_SCALE)))
        out.append('   <Flags0 value="%d" />' % f0)
        out.append('   <Flags1 value="%d" />' % f1)
        out.append('   <Flags2 value="%d" />' % f2)
        out.append('   <Flags3 value="%d" />' % f3)
        out.append('   <Flags4 value="%d" />' % f4)
        out.append('   <Flags5 value="%d" />' % f5)
        if link_count:
            out.append('   <Links>')
            for li in range(link_start, link_start + link_count):
                lo = loff + li * 8
                out.append('    <Item>')
                out.append('     <ToAreaID value="%d" />' % struct.unpack_from('<H', lbuf, lo + 0x00)[0])
                out.append('     <ToNodeID value="%d" />' % struct.unpack_from('<H', lbuf, lo + 0x02)[0])
                out.append('     <Flags0 value="%d" />' % lbuf[lo + 0x04])
                out.append('     <Flags1 value="%d" />' % lbuf[lo + 0x05])
                out.append('     <Flags2 value="%d" />' % lbuf[lo + 0x06])
                out.append('     <LinkLength value="%d" />' % lbuf[lo + 0x07])
                out.append('    </Item>')
            out.append('   </Links>')
        else:
            out.append('   <Links />')
        out.append('  </Item>')

    out.append(' </Nodes>')
    # ⛔ NOT A CONSTANT - THIS LANE IS KNOWINGLY INCOMPLETE (2026-08-11).
    # `was:` "empty in both oracles (constant)". Both halves of that were wrong at population:
    # the full-population census measured 738 of 1,027 files carrying 12,273 junctions and 372
    # files carrying 40,197 ped nodes, and ALL 13 oracles happen to have none - which is exactly
    # why byte-identity could never see it. A converter that drops a section still matches its
    # oracle whenever the oracle lacks that section.
    # The junction/ped-node SECTIONS ARE NOT DECODED: the header field that declares them has
    # never been located, so we cannot even say per-file whether this one carries any. Emitting
    # the empty element preserves parity with the 13 witnesses; the COUNTER is what stops it
    # being a silent lie. It fires on every file, unconditionally, because the honest statement
    # is "this lane does not read these sections at all" - not "this file had none".
    # ✅ JUNCTION + JUNCTION-REF SECTIONS - DECODED 2026-08-13.
    # `was:` both emitted empty with a counted residual, because "the header field that declares
    # them has never been located". It was never a format problem: ALL 13 oracles happened to
    # carry zero junctions, so byte-identity was structurally blind to a section we did not read
    # (738 of 1,027 files carry 12,273 of them). The full-game sweep produced 728 references that
    # DO carry them, and the layout fell out of value-intersection against those.
    #
    #   0x38 -> junction array, 12-byte records      0x50 -> junction-ref array, 8-byte records
    #   0x40 -> heightmap blob                       0x60 -> count (SHARED by both arrays)
    #   0x64 -> total heightmap bytes
    #
    # Junction record:
    #   +0x00 s16 MaxZ/32 | +0x02 s16 PosX*0.25 | +0x04 s16 PosY*0.25 | +0x06 s16 MinZ/32
    #   +0x08 u16 heightmap offset | +0x0A u8 SizeX | +0x0B u8 SizeY
    # ⭐ MaxZ is the FIRST field, which is why it hid: a search for the coordinates lands 2 bytes
    # into the record, so the "spare" u16 at the end was the NEXT record's MaxZ.
    # ⭐ MinZ/MaxZ are SIGNED - a real junction sits below zero and overflowed an unsigned read.
    # ⭐ The heightmap offset is self-proving: offsets run 0, 36, 60 for 6*6, 4*6, 8*6 grids, and
    # the running total equals 0x64 exactly.
    njunc = r.u32(0x60)
    jbuf, joff = r.deref(r.ptr(0x38), njunc * 12) if njunc else (None, 0)
    hbuf, hoff = r.deref(r.ptr(0x40), r.u32(0x64)) if njunc else (None, 0)
    rbuf, roff = r.deref(r.ptr(0x50), njunc * 8) if njunc else (None, 0)
    if njunc and (jbuf is None or rbuf is None):
        # REFUSE rather than emit a half-read section - and COUNT it, so the run says so.
        RESIDUALS['ynd_junction_array_did_not_resolve'] = \
            RESIDUALS.get('ynd_junction_array_did_not_resolve', 0) + 1
        out.append(' <Junctions />')
        out.append(' <JunctionRefs />')
    elif not njunc:
        out.append(' <Junctions />')
        out.append(' <JunctionRefs />')
    else:
        out.append(' <Junctions>')
        for i in range(njunc):
            p = joff + i * 12
            maxz = struct.unpack_from('<h', jbuf, p + 0x00)[0] * Z_SCALE
            px = struct.unpack_from('<h', jbuf, p + 0x02)[0] * XY_SCALE
            py = struct.unpack_from('<h', jbuf, p + 0x04)[0] * XY_SCALE
            minz = struct.unpack_from('<h', jbuf, p + 0x06)[0] * Z_SCALE
            hmo = struct.unpack_from('<H', jbuf, p + 0x08)[0]
            sx, sy = jbuf[p + 0x0A], jbuf[p + 0x0B]
            out.append('  <Item>')
            out.append('   <Position x="%s" y="%s" />' % (fmt_num(px), fmt_num(py)))
            out.append('   <MinZ value="%s" />' % fmt_num(minz))
            out.append('   <MaxZ value="%s" />' % fmt_num(maxz))
            out.append('   <SizeX value="%d" />' % sx)
            out.append('   <SizeY value="%d" />' % sy)
            out.append('   <Heightmap>')
            for row in range(sy):
                s = hoff + hmo + row * sx
                out.append('    ' + ' '.join('%02X' % b for b in hbuf[s:s + sx]))
            out.append('   </Heightmap>')
            out.append('  </Item>')
        out.append(' </Junctions>')
        out.append(' <JunctionRefs>')
        for i in range(njunc):
            p = roff + i * 8
            a, nd, jid, u0 = struct.unpack_from('<HHHH', rbuf, p)
            out.append('  <Item>')
            out.append('   <AreaID value="%d" />' % a)
            out.append('   <NodeID value="%d" />' % nd)
            out.append('   <JunctionID value="%d" />' % jid)
            out.append('   <Unk0 value="%d" />' % u0)
            out.append('  </Item>')
        out.append(' </JunctionRefs>')
    out.append('</NodeDictionary>')
    return '\n'.join(out) + '\n'


def _pos_i(buf, off, scale):
    return fmt_num(struct.unpack_from('<h', buf, off)[0] * scale)


if __name__ == '__main__':
    for p in sys.argv[1:]:
        xml = convert(p)
        sys.stdout.write(xml)
