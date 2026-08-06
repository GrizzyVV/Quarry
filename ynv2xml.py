"""ynv2xml - binary GTA V .ynv (RSC7 v2, rage navmesh) -> RAGE interchange .ynv.xml

CLEAN-ROOM: every field below was pinned by value-intersection of the two oracle XML
exports against their game binaries (freightgrain.ynv, navmesh[105][288].ynv). No
any third-party tool / RAGE source consulted, no web research of reference/RAGE internals.

Reuses:  Res (RSC7 container + tagged-pointer deref) from ydr2xml;
         fmt_num / esc from meta2xml (the proven float-text + XML-escape laws).

CONTAINER MAP (system segment, 8-byte pointer slots, RSC7 version 2)
  0x10  u32   ContentFlags bitfield  (bit0 Polygons, bit2 Vehicle; others "Unknown<value>")
  0x60  3f    BBSize (x,y,z)         (== BBMax-BBMin, stored)
  0x70  ptr   -> vertices block-list descriptor   (46 / 62 entries)
  0x80  ptr   -> vertex-index block-list descriptor (84 / 154 entries)
  0x88  ptr   -> edge (adjacency) block-list descriptor (parallel to indices)
  0x94  u32   adjacent-area table count
  0x98  u32[] adjacent-area table (own AreaID + neighbours + 16383 sentinel)
  0x118 ptr   -> polygon block-list descriptor    (21 / 30 entries)
  0x120 ptr   -> AABB struct: BBMin (vec4) @+0x00, BBMax (vec4) @+0x10
  0x140 u32   AreaID (this sector's own area id)

BLOCK-LIST DESCRIPTOR (0x30 B): count @+0x08, block-array ptr @+0x10, block-count @+0x20.
BLOCK (16 B): data ptr @+0x00, count @+0x08.  Both oracles carry exactly one block per list.

VERTEX (6 B): u16 x,y,z quantised;  pos = BBMin + f32(f32(u16/65535) * BBSize)  [float32].
POLYGON (48 B):
  +0x00 u8   Flags[0]
  +0x02 u16  (vertexCount << 5) | 0     -> vertexCount = word >> 5
  +0x04 u16  firstIndex (into the shared index/edge arrays)
  +0x06 u16  AreaID (this poly's area; == file AreaID for interior polys)
  +0x24 u8   Flags[1]
  +0x25 u8   packed; Flags[2] = byte >> 1   (observed 0->0, 8->4)
  +0x28 u8   Flags[4]
  +0x29 u8   Flags[5]
  +0x2a u8   Flags[3]
  poly vertices = index[firstIndex .. +vertexCount] -> vertex pool
  poly edges    = edge [firstIndex .. +vertexCount]  (parallel to indices)
EDGE (8 B): two u32 adjacency words; each word ->
  areaTableIndex = word & 0x1F  (-> adjacent-area table value)
  polyIndex      = (word >> 5) & 0x3FFF   (0x3FFF/16383 = no-neighbour sentinel)
  (high bits >= bit19 are internal edge data, not emitted)

UNPINNED (neither oracle exercises these; not guessed):
  - ContentFlags names for bits other than 0 (Polygons) and 2 (Vehicle); emitted as
    "Unknown<1<<bit>" which reproduces the observed "Unknown8" (bit3).
  - Poly Flags[2] exact bit layout beyond the observed {0,8}->{0,4} halving.
  - Portals / Points contents: empty in both oracles -> emitted as self-closing tags.
  - Multi-block navmeshes (block-count > 1): REFUSED rather than mis-indexed.
"""
import sys, os, struct
sys.path.insert(0, r'B:\ClaudeCode_Projects\_UEFiveMTool\quarry')
from ydr2xml import Res
from meta2xml import fmt_num, esc

# ContentFlags bit -> name (pinned bits only; unknown bits render "Unknown<value>")
CONTENT_FLAG_NAMES = {0: 'Polygons', 2: 'Vehicle'}

_SENTINEL = 16383            # 0x3FFF, the 14-bit "no neighbour" poly index


def _f32(x):
    return struct.unpack('<f', struct.pack('<f', float(x)))[0]


def _content_flags(v):
    names = []
    for bit in range(32):
        if (v >> bit) & 1:
            names.append(CONTENT_FLAG_NAMES.get(bit, 'Unknown%d' % (1 << bit)))
    return ', '.join(names)


def _ptr(s, off):
    return struct.unpack_from('<I', s, off)[0] & 0x0FFFFFFF


def _block(s, header_slot, entry_size, what):
    """Resolve a block-list at `header_slot` -> (data_offset, count). REFUSES a
    multi-block list (never mis-indexes across blocks)."""
    desc = _ptr(s, header_slot)
    count = struct.unpack_from('<I', s, desc + 0x08)[0]
    blk_arr = _ptr(s, desc + 0x10)
    blk_count = struct.unpack_from('<I', s, desc + 0x20)[0]
    if count == 0:
        return None, 0
    if blk_count != 1:
        raise ValueError("ynv %s uses %d blocks; multi-block layout is UNPINNED" % (what, blk_count))
    data = _ptr(s, blk_arr)
    b0 = struct.unpack_from('<I', s, blk_arr + 0x08)[0]
    if b0 != count:
        raise ValueError("ynv %s block count %d != descriptor count %d" % (what, b0, count))
    if data + count * entry_size > len(s):
        raise ValueError("ynv %s data runs past the system segment" % what)
    return data, count


def convert(name, blob, names=None):
    """(name, blob) -> RAGE interchange XML string. `names` is accepted for signature
    parity with the other converters and is unused (ynv carries no hash-name fields)."""
    res = blob if hasattr(blob, "sys") else Res.from_bytes(blob)
    res.require_version(2, "navmesh")
    s = res.sys

    content_flags = struct.unpack_from('<I', s, 0x10)[0]
    area_id = struct.unpack_from('<I', s, 0x140)[0]
    bbsz = struct.unpack_from('<3f', s, 0x60)

    aabb = _ptr(s, 0x120)
    bbmin = struct.unpack_from('<3f', s, aabb + 0x00)
    bbmax = struct.unpack_from('<3f', s, aabb + 0x10)

    at_count = struct.unpack_from('<I', s, 0x94)[0]
    area_tbl = [struct.unpack_from('<I', s, 0x98 + 4 * k)[0] for k in range(at_count)]

    verts, vcount = _block(s, 0x70, 6, "vertices")
    idx, icount = _block(s, 0x80, 2, "indices")
    edges, ecount = _block(s, 0x88, 8, "edges")
    polys, pcount = _block(s, 0x118, 48, "polygons")

    def vertex_xyz(vi):
        u = struct.unpack_from('<3H', s, verts + vi * 6)
        return tuple(_f32(mn + _f32(_f32(u[c] / 65535.0) * sz))
                     for c, (mn, sz) in enumerate(zip(bbmin, bbsz)))

    def edge_ref(word):
        aidx = word & 0x1F
        poly = (word >> 5) & 0x3FFF
        area = area_tbl[aidx] if aidx < len(area_tbl) else _SENTINEL
        return '%d:%d' % (area, poly)

    L = ['<?xml version="1.0" encoding="UTF-8"?>', '<NavMesh>']
    L.append(' <ContentFlags>%s</ContentFlags>' % esc(_content_flags(content_flags)))
    L.append(' <AreaID value="%d" />' % area_id)
    L.append(' <BBMin x="%s" y="%s" z="%s" />' % (fmt_num(bbmin[0]), fmt_num(bbmin[1]), fmt_num(bbmin[2])))
    L.append(' <BBMax x="%s" y="%s" z="%s" />' % (fmt_num(bbmax[0]), fmt_num(bbmax[1]), fmt_num(bbmax[2])))
    L.append(' <BBSize x="%s" y="%s" z="%s" />' % (fmt_num(bbsz[0]), fmt_num(bbsz[1]), fmt_num(bbsz[2])))

    if pcount:
        L.append(' <Polygons>')
        for pi in range(pcount):
            po = polys + pi * 48
            f0 = s[po + 0x00]
            word02 = struct.unpack_from('<H', s, po + 0x02)[0]
            vc = word02 >> 5
            first = struct.unpack_from('<H', s, po + 0x04)[0]
            f1 = s[po + 0x24]
            f2 = s[po + 0x25] >> 1
            f4 = s[po + 0x28]
            f5 = s[po + 0x29]
            f3 = s[po + 0x2a]
            L.append('  <Item>')
            L.append('   <Flags>%d %d %d %d %d %d</Flags>' % (f0, f1, f2, f3, f4, f5))
            if vc:
                L.append('   <Vertices>')
                for k in range(vc):
                    vi = struct.unpack_from('<H', s, idx + (first + k) * 2)[0]
                    x, y, z = vertex_xyz(vi)
                    L.append('    %s, %s, %s' % (fmt_num(x), fmt_num(y), fmt_num(z)))
                L.append('   </Vertices>')
                L.append('   <Edges>')
                for k in range(vc):
                    eo = edges + (first + k) * 8
                    w0, w1 = struct.unpack_from('<II', s, eo)
                    L.append('    %s, %s' % (edge_ref(w0), edge_ref(w1)))
                L.append('   </Edges>')
            else:
                L.append('   <Vertices />')
                L.append('   <Edges />')
            L.append('  </Item>')
        L.append(' </Polygons>')
    else:
        L.append(' <Polygons />')

    L.append(' <Portals />')      # empty in both oracles (contents UNPINNED)
    L.append(' <Points />')       # empty in both oracles (contents UNPINNED)
    L.append('</NavMesh>')
    return '\n'.join(L) + '\n'


if __name__ == '__main__':
    for p in sys.argv[1:]:
        sys.stdout.write(convert(os.path.basename(p), open(p, 'rb').read()))
