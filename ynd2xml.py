"""ynd2xml - binary GTA V .ynd (RSC7 v1, fwBasePathNodeDict / path nodes) -> RAGE interchange XML.

CLEAN-ROOM: every field below was pinned by value-intersection of the oracle XML against the
game binary (00_base + 10_update), or declared constant/derived where a field could not vary.
No any third-party tool / RAGE source consulted.

Reuses:  Res (RSC7 container + tagged-pointer deref) from ydr2xml;
         fmt_num / esc from meta2xml (the proven float-text + XML-escape laws).
"""
import sys, os, struct
sys.path.insert(0, r'B:\ClaudeCode_Projects\_UEFiveMTool\quarry')
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
    out.append(' <Junctions />')       # empty in both oracles (constant)
    out.append(' <JunctionRefs />')    # empty in both oracles (constant)
    out.append('</NodeDictionary>')
    return '\n'.join(out) + '\n'


def _pos_i(buf, off, scale):
    return fmt_num(struct.unpack_from('<h', buf, off)[0] * scale)


if __name__ == '__main__':
    for p in sys.argv[1:]:
        xml = convert(p)
        sys.stdout.write(xml)
