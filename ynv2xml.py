"""ynv2xml - binary GTA V .ynv (RSC7 v2, rage navmesh) -> RAGE interchange .ynv.xml

CLEAN-ROOM: every field below was pinned by value-intersection of oracle XML exports
against their game binaries. Originally derived from 2 oracles (freightgrain,
navmesh[105][288]); RE-DERIVED 2026-08-10 against 40 stratified oracles spanning block
counts 1..30, every ContentFlags value, Portals/Points carriers, all 19 slots and the
named vehicle family - 40/40 whole-file byte-identical in the derivation harness.
No third-party tool / RAGE source consulted.

⚠⚠ "40/40 BYTE-IDENTICAL" MEANS WE AGREE WITH THE REFERENCE - IT DOES NOT MEAN THE LANE IS
COMPLETE. Measured 2026-08-13 by ROUND-TRIP (binary -> model -> written back -> compare):
this lane started at 86.4% byte coverage, i.e. **13.6% of every .ynv was read by NEITHER
exporter**. Parity is blind to a gap both readers share. Two concrete examples from this very
file: the EDGE stride is 8 (derivable from the block-capacity table below - 16384/2048 - but a
writer first assumed 4 and silently dropped half of every edge record), and the sector POLY-ID
list documented "(not emitted)" was never read by anyone. See `quarry/ynv_write.py` and
`ENGINEERING_LOG § 2026-08-13`. The lane is now ~99.99% covered; the last 0.008% is OPEN_ITEMS M.

Reuses:  Res (RSC7 container + tagged-pointer deref) from ydr2xml;
         fmt_num / esc from meta2xml (the proven float-text + XML-escape laws).

CONTAINER MAP (system segment, 8-byte pointer slots, RSC7 version 2)
  0x10  u32   ContentFlags bitfield (bit0 Polygons, bit1 Portals, bit2 Vehicle;
              bits 3/4 spell the reference's own literals Unknown8/Unknown16)
  0x60  3f    BBSize (x,y,z)         (== BBMax-BBMin, stored; identity held 10,567/10,567)
  0x70  ptr   -> vertices block-list descriptor
  0x80  ptr   -> vertex-index block-list descriptor
  0x88  ptr   -> edge (adjacency) block-list descriptor (parallel to indices; the count
              identity hdr[0x90] == idxCount == edgeCount held population-wide)
  0x94  u32   adjacent-area table count
  0x98  u32[] adjacent-area table (16383 sentinel; tbl[0]==own AreaID is NOT a law -
              80.3% only - the emitted mechanism is always area_tbl[word & 0x1F])
  0x118 ptr   -> polygon block-list descriptor
  0x120 ptr   -> sector quadtree ROOT NODE (its +0x00/+0x10 vec4s are BBMin/BBMax, so
              the old "AABB struct" reads stay valid; see POINTS below)
  0x128 ptr   -> portal records (28 B each)      0x14C u32 portal count
  0x130 ptr   -> portal-link u16 array           0x150 u32 link count (== sum of the
              per-poly link-list lengths; NOT always 2x portal count - 129 files differ)
  0x138 u32   vertex count (== sum of vertex blocks, population-proven)
  0x13C u32   polygon count (== sum of polygon blocks, population-proven)
  0x140 u32   AreaID (this sector's own area id)
  0x144 u32   NOT emitted in XML (payload-size-ish scalar; unpinned, no parity impact)
  0x148 u32   total point count (== sum of per-sector point counts; cross-checked)

BLOCK-LIST DESCRIPTOR (0x30 B): count @+0x08, block-array ptr @+0x10, block-count @+0x20.
BLOCK (16 B): data ptr @+0x00, count @+0x08.
MULTI-BLOCK LAW (2026-08-10, 559 blocks over 40 witnesses; multi-block = 69% of the
population): assembly order = block-ARRAY order (content-proven - NOT address order);
every non-final block is exactly at capacity floor(16384/entry_size) (verts 2730,
idx 8192, edges 2048, polys 341 - measured maxima equal these exactly); final block =
remainder; per-block sums == descriptor count (enforced). All index spaces are GLOBAL
over the assembled streams - no per-block bases exist. Per-list block counts differ
within one file (measured maxima: verts 7, idx 6, edges 21, polys 30).

VERTEX (6 B): u16 x,y,z quantised;  pos = BBMin + f32(f32(u16/65535) * BBSize)  [float32].
POLYGON (48 B):
  +0x00 u8   Flags[0]
  +0x02 u16  (vertexCount << 5) | 0     -> vertexCount = word >> 5 (low-5 bits zero in
             all 19.19M polys game-wide)
  +0x04 u16  firstIndex (into the shared index/edge arrays)
  +0x24 u8   Flags[1]
  +0x25 u8   packed; Flags[2] = byte >> 1 - THE ORACLE'S OWN LAW (2026-08-10: verified
             per-poly on 65,486 polys incl. every odd-value carrier class; raw bit0 is
             internal and the reference never emits it anywhere)
  +0x28 u8   Flags[4]      +0x29 u8 Flags[5]      +0x2a u8 Flags[3]
  +0x2C u32  per-poly portal links: count = (w >> 12) & 7, first = w >> 15 into the
             0x130 u16 array; bits 0..11 internal, never emitted. Emits
             <Portals>i j ...</Portals> after </Edges>, OMITTED when count==0
             (no self-closing form; pinned on 211-carrier and 1/2/4-link witnesses)
EDGE (8 B): two u32 adjacency words; each word ->
  areaTableIndex = word & 0x1F  (-> adjacent-area table value)
  polyIndex      = (word >> 5) & 0x3FFF   (0x3FFF/16383 = no-neighbour sentinel)

PORTAL RECORD (28 B, flat array @0x128):
  +0x00 u8 Type ({1,2,3} witnessed)   +0x01 u8 Angle (quantised, law below)
  +0x02 u16 == 0 (all 337 records; not emitted)
  +0x04 u16[3] PositionFrom  +0x0A u16[3] PositionTo (vertex quantisation law)
  +0x10 u16 PolyFrom (+0x12 duplicate, ==, not emitted)
  +0x14 u16 PolyTo   (+0x16 duplicate, ==, not emitted)
  +0x18 u32 == (AreaID<<14)|AreaID (file-constant; not emitted)

POINTS: the 0x120 quadtree. Node: +0x00/+0x10 BBMin/BBMax vec4 (w = 0x7F800001),
  +0x2C ptr -> sector data (NULL on internal nodes in every witness), children u64
  slots @+0x34/+0x3C/+0x44/+0x4C. Sector data: +0x08 ptr -> u16 poly-ID list (not
  emitted), +0x10 ptr -> point records, +0x18 u16 polyCount, +0x1A u16 pointCount.
  POINT RECORD (8 B): u16 x,y,z (vertex quantisation) + u8 angle + u8 Type.
  EMISSION ORDER: DFS, own sector first, children visited 3->2->1->0 - proven on every
  multi-sector witness (25/25); indistinguishable from reverse-postorder because no
  internal node carries sector data in any witness (flagged, not a proven choice).

ANGLE LAW (portals + points): f32(f32(u8 * f32(2*pi)) / 255.0) - the sole survivor of
an 8-formula battery over all 252 distinct witnessed angle bytes; the naive
f32(u8/255*2pi) is +-1 ulp wrong on ~40% of bytes.

Section order: <Polygons> -> <Portals> -> <Points>; empty sections spell the
self-closing form. A file with 0x148==0 and 0x14C==0 is byte-identical to the
pre-2026-08-10 emitter's output (the two original oracles were exactly that class,
which is how the Portals/Points surface stayed invisible to a 2-oracle base).
"""
import sys, os, math, struct
sys.path.insert(0, r'B:\ClaudeCode_Projects\_UEFiveMTool\quarry')
from ydr2xml import Res
from meta2xml import fmt_num, esc

# ContentFlags bit -> name (oracle-witnessed across all 9 cf values, 38/38 string-exact;
# unknown bits render "Unknown<value>" which reproduces the reference's own
# Unknown8/Unknown16 literals exactly)
CONTENT_FLAG_NAMES = {0: 'Polygons', 1: 'Portals', 2: 'Vehicle'}

_SENTINEL = 16383            # 0x3FFF, the 14-bit "no neighbour" poly index


def _f32(x):
    return struct.unpack('<f', struct.pack('<f', float(x)))[0]


_TWO_PI = _f32(2 * math.pi)


def _angle(u8):
    # the pinned quantised-angle law (see header); double-rounded on purpose
    return _f32(_f32(u8 * _TWO_PI) / 255.0)


def _content_flags(v):
    names = []
    for bit in range(32):
        if (v >> bit) & 1:
            names.append(CONTENT_FLAG_NAMES.get(bit, 'Unknown%d' % (1 << bit)))
    return ', '.join(names)


def _ptr(s, off):
    return struct.unpack_from('<I', s, off)[0] & 0x0FFFFFFF


def _u32(s, off):
    return struct.unpack_from('<I', s, off)[0]


class _List:
    """Block-list assembled in block-ARRAY order (content-proven, 40 oracles,
    2026-08-10). Non-final blocks are always at capacity floor(16384/entry_size);
    per-block sums must equal the descriptor count - both enforced loudly."""
    def __init__(self, s, header_slot, entry_size, what):
        desc = _ptr(s, header_slot)
        self.count = _u32(s, desc + 0x08)
        blk_arr = _ptr(s, desc + 0x10)
        blk_count = _u32(s, desc + 0x20)
        self.esz = entry_size
        self.blocks = []
        cum = 0
        for b in range(blk_count):
            bo = blk_arr + 16 * b
            data = _ptr(s, bo)
            cnt = _u32(s, bo + 0x08)
            if data + cnt * entry_size > len(s):
                raise ValueError("ynv %s block %d runs past the system segment" % (what, b))
            self.blocks.append((data, cnt, cum))
            cum += cnt
        if cum != self.count:
            raise ValueError("ynv %s per-block sum %d != descriptor count %d"
                             % (what, cum, self.count))

    def off(self, i):
        for data, cnt, start in self.blocks:
            if i < start + cnt:
                return data + (i - start) * self.esz
        raise IndexError("ynv index %d past count %d" % (i, self.count))


def _walk_points(s, node_off, out):
    """DFS the sector quadtree: own sector's points first, children 3->2->1->0 (the
    pinned oracle order; see the header note on the postorder indistinguishability)."""
    if _u32(s, node_off + 0x2C) != 0:
        sec = _ptr(s, node_off + 0x2C)
        n_pts = struct.unpack_from('<H', s, sec + 0x1A)[0]
        pts = _ptr(s, sec + 0x10)
        for k in range(n_pts):
            out.append(pts + 8 * k)
    for c in (3, 2, 1, 0):
        ch = _u32(s, node_off + 0x34 + 8 * c)
        if ch != 0:
            _walk_points(s, ch & 0x0FFFFFFF, out)


def convert(name, blob, names=None):
    """(name, blob) -> RAGE interchange XML string. `names` is accepted for signature
    parity with the other converters and is unused (ynv carries no hash-name fields)."""
    res = blob if hasattr(blob, "sys") else Res.from_bytes(blob)
    res.require_version(2, "navmesh")
    s = res.sys

    content_flags = _u32(s, 0x10)
    area_id = _u32(s, 0x140)
    bbsz = struct.unpack_from('<3f', s, 0x60)

    tree_root = _ptr(s, 0x120)
    bbmin = struct.unpack_from('<3f', s, tree_root + 0x00)
    bbmax = struct.unpack_from('<3f', s, tree_root + 0x10)

    at_count = _u32(s, 0x94)
    area_tbl = [_u32(s, 0x98 + 4 * k) for k in range(at_count)]

    verts = _List(s, 0x70, 6, "vertices")
    idx = _List(s, 0x80, 2, "indices")
    edges = _List(s, 0x88, 8, "edges")
    polys = _List(s, 0x118, 48, "polygons")

    n_portals = _u32(s, 0x14C)
    n_links = _u32(s, 0x150)
    n_points = _u32(s, 0x148)
    portals = _ptr(s, 0x128) if n_portals else 0
    links = _ptr(s, 0x130) if n_links else 0

    def dq(u, c):
        return _f32(bbmin[c] + _f32(_f32(u / 65535.0) * bbsz[c]))

    def vertex_xyz(vi):
        u = struct.unpack_from('<3H', s, verts.off(vi))
        return tuple(dq(u[c], c) for c in range(3))

    def edge_ref(word):
        aidx = word & 0x1F
        poly = (word >> 5) & 0x3FFF
        area = area_tbl[aidx] if aidx < len(area_tbl) else _SENTINEL
        return '%d:%d' % (area, poly)

    L = ['<?xml version="1.0" encoding="UTF-8"?>', '<NavMesh>']
    L.append(' <ContentFlags>%s</ContentFlags>' % esc(_content_flags(content_flags)))
    L.append(' <AreaID value="%d" />' % area_id)
    L.append(' <BBMin x="%s" y="%s" z="%s" />' % tuple(fmt_num(v) for v in bbmin))
    L.append(' <BBMax x="%s" y="%s" z="%s" />' % tuple(fmt_num(v) for v in bbmax))
    L.append(' <BBSize x="%s" y="%s" z="%s" />' % tuple(fmt_num(v) for v in bbsz))

    if polys.count:
        L.append(' <Polygons>')
        for pi in range(polys.count):
            po = polys.off(pi)
            f0 = s[po + 0x00]
            word02 = struct.unpack_from('<H', s, po + 0x02)[0]
            vc = word02 >> 5
            first = struct.unpack_from('<H', s, po + 0x04)[0]
            f1 = s[po + 0x24]
            f2 = s[po + 0x25] >> 1
            f4 = s[po + 0x28]
            f5 = s[po + 0x29]
            f3 = s[po + 0x2a]
            w2c = _u32(s, po + 0x2C)
            pl_count = (w2c >> 12) & 0x7
            pl_first = w2c >> 15
            L.append('  <Item>')
            L.append('   <Flags>%d %d %d %d %d %d</Flags>' % (f0, f1, f2, f3, f4, f5))
            if vc:
                L.append('   <Vertices>')
                for k in range(vc):
                    gi = struct.unpack_from('<H', s, idx.off(first + k))[0]
                    x, y, z = vertex_xyz(gi)
                    L.append('    %s, %s, %s' % (fmt_num(x), fmt_num(y), fmt_num(z)))
                L.append('   </Vertices>')
                L.append('   <Edges>')
                for k in range(vc):
                    w0, w1 = struct.unpack_from('<II', s, edges.off(first + k))
                    L.append('    %s, %s' % (edge_ref(w0), edge_ref(w1)))
                L.append('   </Edges>')
            else:
                L.append('   <Vertices />')
                L.append('   <Edges />')
            if pl_count:
                vals = [struct.unpack_from('<H', s, links + 2 * (pl_first + k))[0]
                        for k in range(pl_count)]
                L.append('   <Portals>%s</Portals>' % ' '.join('%d' % v for v in vals))
            L.append('  </Item>')
        L.append(' </Polygons>')
    else:
        L.append(' <Polygons />')

    if n_portals:
        L.append(' <Portals>')
        for k in range(n_portals):
            ro = portals + 0x1C * k
            pf = struct.unpack_from('<3H', s, ro + 0x04)
            pt = struct.unpack_from('<3H', s, ro + 0x0A)
            L.append('  <Item>')
            L.append('   <Type value="%d" />' % s[ro + 0x00])
            L.append('   <Angle value="%s" />' % fmt_num(_angle(s[ro + 0x01])))
            L.append('   <PolyFrom value="%d" />' % struct.unpack_from('<H', s, ro + 0x10)[0])
            L.append('   <PolyTo value="%d" />' % struct.unpack_from('<H', s, ro + 0x14)[0])
            L.append('   <PositionFrom x="%s" y="%s" z="%s" />'
                     % tuple(fmt_num(dq(pf[c], c)) for c in range(3)))
            L.append('   <PositionTo x="%s" y="%s" z="%s" />'
                     % tuple(fmt_num(dq(pt[c], c)) for c in range(3)))
            L.append('  </Item>')
        L.append(' </Portals>')
    else:
        L.append(' <Portals />')

    pt_offs = []
    _walk_points(s, tree_root, pt_offs)
    if len(pt_offs) != n_points:
        # the header count is the cross-check the tree walk must satisfy (population-
        # proven identity) - a mismatch means an unwitnessed tree shape, refuse loudly
        raise ValueError("ynv point walk found %d points, header 0x148 says %d (%s)"
                         % (len(pt_offs), n_points, name))
    if pt_offs:
        L.append(' <Points>')
        for ro in pt_offs:
            u = struct.unpack_from('<3H', s, ro)
            L.append('  <Item>')
            L.append('   <Type value="%d" />' % s[ro + 7])
            L.append('   <Angle value="%s" />' % fmt_num(_angle(s[ro + 6])))
            L.append('   <Position x="%s" y="%s" z="%s" />'
                     % tuple(fmt_num(dq(u[c], c)) for c in range(3)))
            L.append('  </Item>')
        L.append(' </Points>')
    else:
        L.append(' <Points />')
    L.append('</NavMesh>')
    return '\n'.join(L) + '\n'


if __name__ == '__main__':
    for p in sys.argv[1:]:
        sys.stdout.write(convert(os.path.basename(p), open(p, 'rb').read()))
