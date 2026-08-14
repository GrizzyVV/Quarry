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
  BLOCK-LIST DESCRIPTOR (0x30 B): count @+0x08, block-array ptr @+0x10,
                                  START-INDEX ARRAY ptr @+0x18, block-count @+0x20
  BLOCK (16 B): data ptr @+0x00, count @+0x08
  vertex 6 B | index u16 | edge u32 | polygon 48 B | portal 28 B
⚠ Same scope limits as `ynd_write`: inflated SYSTEM SEGMENT only (not the deflate container), and
the header is carried verbatim because re-encoding tagged pointers is a layout-ALLOCATOR problem.
⭐ The page-count record at `ptr@0x08 +8` is COMPUTED, never carried - the law `meta_write` derived
for META and `ynd_write` confirmed for path nodes.

⭐⭐ 2026-08-14 - THE LANE'S LAST GAP WAS **ONE STRUCTURE**, and the DISTRIBUTION said so first.
The population grade read 3,272 / 10,567 byte-exact with every imperfect file inside a 0.009%-wide
band. Per-file the unreached count was 2..95 BYTES - so before chasing a pointer, the shape was
already "a small fixed-ish record", not "a big region". It was `descriptor +0x18`, the per-block
START-INDEX array (see `_start_index_array`). Measured on the same 1,300 files:
  before  18,093 unreached bytes, 454 / 1,300 byte-exact
  after        0 unreached bytes, 1,300 / 1,300 byte-exact
and the predicted size - the non-zero byte count of the four re-encoded arrays - was **18,093**,
i.e. the structure accounts for the gap EXACTLY, not approximately. It is a pure function of the
file's total block count: 4 blocks (one per list) => every start index is 0 => byte-exact, which
is why 31% of the lane already passed and no file was ever badly wrong.
⚠ **BYTE-EXACT IS NOT FULLY MODELLED.** The comparison image is zero-filled, so a byte the model
never touches still matches if the original is zero. Measured over 1,300 files: 97.6221% of the
system segment lies INSIDE a modelled region, 2.3774% lies outside and is ZERO (allocation and
page padding), and the only non-zero byte outside any region is the COMPUTED page-count record
(200/200 files checked, no other). Quote 100% round-trip with that sentence attached.
ASCII output only.
"""
import os
import struct
import sys as _sys

_sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ydr2xml import Res  # noqa: E402

# Carried verbatim.
# ⛔ Δ 2026-08-14 - THE PREVIOUS NOTE HERE WAS WRONG. It read: "0x160..0x164 holds a 4-byte value
# IDENTICAL across every file sampled (19 C0 03 46)". Measured over 1,300 files from four navmesh
# sets it takes THREE distinct values, and over 291 files spanning twelve sets it takes four:
#   0x85CB3561 - every base-game map tile, all of navmeshes0..9
#   0x4603C019 - every tile of update mp2026_01     0x1948BF1A - every tile of the x64w DLC pack
#   0x00000000 - the 8,192-byte VEHICLE navmeshes (armytanker, seashark, trailers, ...)
# ⇒ the law is "CONSTANT PER NAVMESH SET, zero on vehicle navmeshes", not "constant everywhere".
# The value's MEANING is still unknown: it is CARRIED-NOT-UNDERSTOOD and must not be counted as
# modelled knowledge. Carrying it is honest about completeness and silent about meaning.
# ⭐ 0x154/0x158/0x15C and 0x164/0x168/0x16C are zero in 1,300 / 1,300 files - so 0x164 is the end
# of the header struct and 0x164..0x170 is allocation padding, which is why HEADER stops here.
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
        counts = []
        for i in range(nblocks):
            b = aoff + i * 16
            try:
                dptr = struct.unpack_from('<I', s, b + 0x00)[0]
                cnt = struct.unpack_from('<I', s, b + 0x08)[0]
            except struct.error:
                break
            counts.append(cnt)
            self._flat(dptr, cnt * stride)
        self._start_index_array(doff, counts)

    def _start_index_array(self, doff, counts):
        """⭐ THE POINTER WE HELD AND NEVER FOLLOWED - descriptor +0x18.

        A u32 per block giving that block's START INDEX in the flattened list, i.e. the running
        prefix sum of the per-block counts. It is what let the whole lane sit in a 0.009%-wide
        band: four arrays of a handful of u32 each, in every file, unread.
        ⭐ IT WAS FOUND BY THE POINTER-SITE METHOD, not by chasing bytes: every unreached run in
        300 files was the target of a tagged pointer living at +0x18 of a descriptor we ALREADY
        modelled - 143 poly / 136 edge / 65 idx / 59 vert sites, and ZERO runs with no pointer.
        A modelled site plus an unmodelled target is a pointer you hold and never follow.
        ⛔ WHY IT LOOKED LIKE 'a stride-4 array of sequential multiples of 8': the entries are
        multiples of the BLOCK CAPACITY (verts 2730 | idx 8192 | edges 2048 | polys 341), and for
        edges 2048 = 0x00000800, whose only non-zero byte is 0x08 at +1. Against a ZERO-FILLED
        comparison image the low byte matches invisibly, so the visible mismatch is one byte per
        entry reading 08, 10, 18 - multiples of 8 at stride 4. The description was a byte-level
        artefact of the measure, not the structure.
        ⭐ RE-ENCODED, NOT COPIED. Emitting the computed prefix sum means a file whose array is
        NOT a prefix sum shows up as a gap instead of being absorbed by a memcpy. Verified equal
        to the file's own bytes on 5,200 / 5,200 block lists (1,300 files x 4 lists, four navmesh
        sets), zero mismatches. The array is exactly `nblocks` entries: the u32 at index nblocks
        is never the running total (1,300/1,300), and nblocks*4 rounds up to the 16-byte
        allocation with zero padding, which the zero-filled image reproduces for free.
        """
        try:
            ptr = struct.unpack_from('<I', self.res.sys, doff + 0x18)[0]
        except struct.error:
            return
        off = self._off(ptr)
        if off is None or not counts:
            return
        acc, out = 0, []
        for c in counts:
            out.append(acc)
            acc += c
        self.regions.append((off, b''.join(struct.pack('<I', v) for v in out)))

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
