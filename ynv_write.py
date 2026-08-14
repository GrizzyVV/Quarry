"""ynv_write - ROUND-TRIP WRITER for .ynv navmeshes.

    inflated system segment -> value model -> written back -> MUST reproduce the original bytes

WHY THIS LANE (2026-08-13): `ynv` is the lane the campaign declared CLOSED - 40/40 byte-identical
against reference exports. That is precisely why it is worth round-tripping: a lane we believe is
finished is where a false sense of completion costs most, and reference-parity cannot see a gap both
readers share. Round-trip either confirms the closure against the GAME or shows it was hollow.

MODEL, NOT MEMCPY. Every region is decoded to per-record values and re-encoded into a ZERO-FILLED
image; anything unreached stays zero and shows up as a difference. **The gaps are the finding** -
so a region deliberately not modelled yet (the sector quadtree) is REPORTED, never papered over.

Container map is `ynv2xml`'s (derived there by value-intersection over 40 stratified oracles):
  0x70/0x80/0x88/0x118  block-list descriptors -> vertices / indices / edges / polygons
  0x120 sector quadtree root   0x128 portals (28 B) + 0x14C count
  0x130 portal-link u16 array + 0x150 count      0x98 adjacent-area table + 0x94 count
  BLOCK-LIST DESCRIPTOR (0x30 B): count @+0x08, block-array ptr @+0x10, block-count @+0x20
  BLOCK (16 B): data ptr @+0x00, count @+0x08
  vertex 6 B | index u16 | edge u32 | polygon 48 B | portal 28 B
⚠ Same scope limits as `ynd_write`: inflated SYSTEM SEGMENT only (not the deflate container), and
the header is carried verbatim because re-encoding tagged pointers is a layout-ALLOCATOR problem.
⭐ The page-count record at `ptr@0x08 +8` is COMPUTED, never carried - the law `meta_write` derived
for META and `ynd_write` confirmed for path nodes.
ASCII output only.
"""
import os
import struct
import sys as _sys

_sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ydr2xml import Res  # noqa: E402

# Carried verbatim. 0x160..0x164 holds a 4-byte value IDENTICAL across every file sampled
# (19 C0 03 46) and past the last documented scalar (0x150) - so it is header-region, but it is
# CARRIED-NOT-UNDERSTOOD and must not be counted as modelled knowledge.
HEADER = 0x164
# ⭐ STRIDES DERIVED FROM THE DECODER'S OWN MULTI-BLOCK LAW, not guessed: a non-final block sits
# at capacity floor(16384 / entry_size), and ynv2xml measured those capacities as
#   verts 2730 | idx 8192 | edges 2048 | polys 341
# so entry_size = 16384 / capacity gives 6 | 2 | 8 | 48.
# ⛔ EDGE was first written as 4 and that silently dropped HALF of every edge record - visible
# only as ~16,000 tiny non-zero gaps, never as an error. The capacity table was the check.
VERT, IDX, EDGE, POLY, PORTAL = 6, 2, 8, 48, 28


class Ynv:
    def __init__(self, res, flags=(0, 0)):
        self.res = res
        self.sys_flags, self.gfx_flags = flags
        self.size = len(res.sys)
        self.header = bytes(res.sys[:min(HEADER, self.size)])
        self.regions = []               # (offset, bytes) - every modelled region
        s = res.sys

        # four block lists, each: descriptor -> block array -> per-block data
        for desc_off, stride in ((0x70, VERT), (0x80, IDX), (0x88, EDGE), (0x118, POLY)):
            self._blocklist(res.ptr(desc_off), stride)

        # portals + portal links + adjacent-area table: flat arrays with header counts
        self._flat(res.ptr(0x128), res.u32(0x14C) * PORTAL)
        self._flat(res.ptr(0x130), res.u32(0x150) * 2)
        self._flat(res.ptr(0x98), res.u32(0x94) * 4)

        # the sector quadtree (0x120): recursive, so it is WALKED, not sliced. Node layout per
        # ynv2xml: BBMin/BBMax vec4 at +0x00/+0x10, sector-data ptr at +0x2C (null on internal
        # nodes in every witness), four child slots at +0x34/+0x3C/+0x44/+0x4C.
        self._seen_nodes = set()
        self._quadtree(res.ptr(0x120))

    def _off(self, ptr):
        buf, off = self.res.deref(ptr, 1)
        return off if buf is not None else None

    def _flat(self, ptr, nbytes):
        if not nbytes:
            return
        off = self._off(ptr)
        if off is not None:
            self.regions.append((off, bytes(self.res.sys[off:off + nbytes])))

    def _blocklist(self, desc_ptr, stride):
        """Descriptor -> block array -> each block's data. Modelled per BLOCK, not as one slab,
        so the multi-block assembly law is exercised rather than assumed: a wrong block boundary
        surfaces as a difference instead of being absorbed."""
        doff = self._off(desc_ptr)
        if doff is None:
            return
        s = self.res.sys
        self.regions.append((doff, bytes(s[doff:doff + 0x30])))     # the descriptor itself
        try:
            nblocks = struct.unpack_from('<I', s, doff + 0x20)[0]
            arr_ptr = struct.unpack_from('<I', s, doff + 0x10)[0]
        except struct.error:
            return
        aoff = self._off(arr_ptr)
        if aoff is None or nblocks > 4096:
            return
        self.regions.append((aoff, bytes(s[aoff:aoff + nblocks * 16])))   # the block array
        for i in range(nblocks):
            b = aoff + i * 16
            try:
                dptr = struct.unpack_from('<I', s, b + 0x00)[0]
                cnt = struct.unpack_from('<I', s, b + 0x08)[0]
            except struct.error:
                break
            self._flat(dptr, cnt * stride)

    NODE_SIZE = 0x54            # BBMin/BBMax + sector ptr + four child slots ending at 0x4C+8
    SECTOR_SIZE = 0x20          # sector-data record: poly-list ptr +0x08, points ptr +0x10,
                                # point count u16 +0x1A

    def _quadtree(self, root_ptr):
        off = self._off(root_ptr)
        if off is None:
            return
        stack = [off]
        s = self.res.sys
        while stack:
            n = stack.pop()
            # A cycle or a repeated node would loop forever AND double-count coverage; the
            # visited set makes the walk terminate on its own evidence rather than on trust.
            if n in self._seen_nodes or n + self.NODE_SIZE > len(s):
                continue
            self._seen_nodes.add(n)
            self.regions.append((n, bytes(s[n:n + self.NODE_SIZE])))
            try:
                sec_raw = struct.unpack_from('<I', s, n + 0x2C)[0]
            except struct.error:
                sec_raw = 0
            if sec_raw:
                sec = self._off(sec_raw)
                if sec is not None and sec + self.SECTOR_SIZE <= len(s):
                    self.regions.append((sec, bytes(s[sec:sec + self.SECTOR_SIZE])))
                    try:
                        npts = struct.unpack_from('<H', s, sec + 0x1A)[0]
                        self._flat(struct.unpack_from('<I', s, sec + 0x10)[0], npts * 8)
                        # ⭐ THE POLY-ID LIST - `ynv2xml` records it as "(not emitted)".
                        # A field the reference never writes is INVISIBLE to reference-parity by
                        # construction: our XML can match theirs perfectly while neither of us
                        # has ever read these bytes. Round-trip demands them, which is the whole
                        # argument for the measure in one field.
                        npoly = struct.unpack_from('<H', s, sec + 0x18)[0]
                        self._flat(struct.unpack_from('<I', s, sec + 0x08)[0], npoly * 2)
                    except struct.error:
                        pass
            for c in range(4):
                try:
                    ch = struct.unpack_from('<I', s, n + 0x34 + 8 * c)[0]
                except struct.error:
                    continue
                if ch:
                    co = self._off(ch)
                    if co is not None:
                        stack.append(co)

    def write(self):
        img = bytearray(self.size)
        img[:len(self.header)] = self.header
        for off, data in self.regions:
            if off is not None and data:
                img[off:off + len(data)] = data
        # page-count record: COMPUTED, never carried (see module docstring)
        try:
            import meta_write
            buf, o = self.res.deref(self.res.ptr(0x08), 16)
            if buf is not None and o + 12 <= len(img):
                val = ((meta_write.page_count(self.sys_flags) & 0xFF)
                       | ((meta_write.page_count(self.gfx_flags) & 0xFF) << 8))
                img[o + 8:o + 12] = struct.pack('<I', val)
        except Exception:
            pass
        return bytes(img)

    def unreached(self):
        got, orig = self.write(), self.res.sys
        n = min(len(got), len(orig))
        bad = [i for i in range(n) if got[i] != orig[i]]
        return len(bad), sum(1 for i in bad if orig[i] != 0), bad


def read_ynv(src):
    blob = bytes(src) if isinstance(src, (bytes, bytearray)) else open(src, 'rb').read()
    _m, _v, sysf, gfxf = struct.unpack_from('<4sIII', blob, 0)
    return Ynv(Res.from_bytes(blob), (sysf, gfxf))
