"""ywr_write - ROUND-TRIP WRITER for .ywr waypoint-recording lists (RSC7 v1).

    inflated system segment -> value model -> written back -> MUST reproduce the original bytes

WHY (maintainer ruling 2026-08-13, hardened 2026-08-15): round-trip byte identity is the primary
measure, and a lane with a reader but no writer is **UNMEASURED, not passing** - 1,612 files with
no number attached to them (`docs/LANE_CENSUS_20260814.md` row 5). This is the writer.

MODEL, NOT MEMCPY - stronger than the `ynd_write` template it follows. `ynd_write` re-emits each
record as an opaque per-record byte slice; this writer DECODES EVERY RECORD TO TYPED FIELDS and
re-encodes them from those values into a ZERO-FILLED image. The 20-byte stride is not copied, it
is REBUILT from `FIELDS`, and `FIELDS` is checked at import to tile 0x00..0x14 with no hole and no
overlap. A byte inside a record that no named field covers would stay zero and count against
coverage. **The gaps are the finding.**

⚠ SCOPE: round-trips the INFLATED SYSTEM SEGMENT, not the compressed RSC7 container. Reproducing
the container also means reproducing an exact deflate stream, which is a separate problem - mixing
them would make a compression difference look like a format defect. (`.ywr` carries NO graphics
segment: 1,612/1,612 measured 2026-08-15, and a non-empty one REFUSES rather than being ignored.)

⚠ The header (0x00-0x30) is carried verbatim - 48 bytes, i.e. 0.6% of the smallest (8,192 B)
segment in the lane. It holds a vtable u64, the tagged block-map pointer @0x08, the tagged array
pointer @0x18 and the count @0x20. Re-encoding the pointers is a layout ALLOCATOR problem, the
same boundary `meta_write` names when it pins the source's own region offsets - so this proves we
can rebuild the DATA, not that we can lay out a new file.
⭐ The COUNT is NOT an unpinned carried claim even though it sits inside that header: the writer
DRIVES the array off it, so a wrong count writes the wrong number of records and the round-trip
rejects it.
❓ COUNT WIDTH IS UNPINNED ABOVE 65535, and it is stated rather than assumed: the u16 at 0x22 is
0 on 1,612/1,612, so "u16 count + u16 capacity(0)" and "u32 count" are INDISTINGUISHABLE over the
whole population (max count observed 509). `.yvr`'s sibling field is unambiguously two u16s
(count == capacity, both non-zero, 7,533/7,533), which is the reason a u16 is read here. Nothing
in the game can currently decide it; a file with more than 65,535 waypoints would.

Layout (derived 2026-08-15 over all 1,612 .ywr in the game; see `ywr2xml.py` for the field
semantics, which this writer deliberately does NOT apply - it models the STORED form):
    0x00 u64 vtable   0x08 ptr -> block map   0x18 ptr -> record array (0x50000030, 1,612/1,612)
    0x20 count
    record array at 0x30, stride 20, immediately after the header (gap 0 on 1,612/1,612)
    block map at align16(array end) - the stride is 20, so the observed delta from the array's
    end is 0/4/8/12 (408/415/378/411 files), which is exactly a 16-byte alignment and nothing else
    everything past the block map is zero on 1,612/1,612 (non-zero run from the map = 9 bytes,
    i.e. the single page-count word at +8 and nothing else)
ASCII output only.
"""
import os
import struct
import sys as _sys

_sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ydr2xml import Res  # noqa: E402
import meta_write        # noqa: E402  (page_count - the COMPUTED page record, see write())

HEADER = 0x30
STRIDE = 20
ARR_PTR = 0x18
COUNT = 0x20
BLOCKMAP_PTR = 0x08

# ⭐ THE RECORD MODEL. Each entry is (offset-in-record, struct code). Field SEMANTICS belong to
# `ywr2xml.py`; what matters to a round-trip is the STORED form and, above all, that these fields
# TILE THE STRIDE. See _check_tiling. Unk0..Unk3 are read as four u16 because that is the width
# `ywr2xml` pinned (Unk1 spans 1,518..27,057, which requires an unsigned 16-bit read); their
# MEANING is unpinned and this writer does not need it - it re-encodes what it decoded.
FIELDS = (
    (0x00, '<3f'),     # Position x/y/z (float32)
    (0x0C, '<4H'),     # Unk0..Unk3
)


def _check_tiling(fields, stride, what):
    """⛔ AN UNTILED FIELD MAP IS A SILENT CARRY. Run at import so the claim "every byte of a
    record is modelled" is refuted here rather than showing up as mystery coverage later."""
    at = 0
    for off, code in fields:
        if off != at:
            raise ValueError('%s field map: hole/overlap at 0x%02x (expected 0x%02x)'
                             % (what, off, at))
        at += struct.calcsize(code)
    if at != stride:
        raise ValueError('%s field map covers %d of %d stride bytes' % (what, at, stride))


_check_tiling(FIELDS, STRIDE, 'ywr')


class Ywr:
    def __init__(self, res, flags=(0, 0)):
        if res.version != 1:
            raise ValueError('ywr expects RSC7 version 1, got %d' % res.version)
        if len(res.gfx):
            # NO SILENT DEFAULTS: the lane is system-segment-only in 1,612/1,612.
            raise ValueError('ywr carries no graphics segment; got %d bytes' % len(res.gfx))
        self.res = res
        self.sys_flags, self.gfx_flags = flags
        self.size = len(res.sys)
        self.header = bytes(res.sys[:HEADER])
        self.count = res.u16(COUNT)
        self.arr = None
        self.records = []
        if self.count:
            buf, off = res.deref(res.ptr(ARR_PTR), self.count * STRIDE)
            if buf is None:
                raise ValueError('ywr record array (%d x %d B) does not resolve inside the '
                                 'system segment' % (self.count, STRIDE))
            self.arr = off
            s = res.sys
            # per-RECORD, never one slab: an off-by-one in the stride must surface as a
            # difference rather than be absorbed by a bulk copy.
            for i in range(self.count):
                o = off + i * STRIDE
                self.records.append(tuple(struct.unpack_from(c, s, o + fo) for fo, c in FIELDS))

    def write(self):
        img = bytearray(self.size)
        img[:HEADER] = self.header
        if self.arr is not None:
            for i, rec in enumerate(self.records):
                o = self.arr + i * STRIDE
                for (fo, code), vals in zip(FIELDS, rec):
                    struct.pack_into(code, img, o + fo, *vals)

        # ⭐ THE PAGE-COUNT RECORD, and it is COMPUTED - never carried.
        # `ptr@0x08` reaches the block map; its u32 at +8 is
        #     pageCount(system) | pageCount(graphics) << 8
        # ⭐ Third independent confirmation of a law `meta_write` derived for the META formats
        # and `ynd_write` re-confirmed on 259/259 .ynd; measured 1,612/1,612 .ywr before this
        # writer existed. A carried value would round-trip even if we had no idea what it meant.
        buf, o = self.res.deref(self.res.ptr(BLOCKMAP_PTR), 12)
        if buf is not None and o + 12 <= len(img):
            val = ((meta_write.page_count(self.sys_flags) & 0xFF)
                   | ((meta_write.page_count(self.gfx_flags) & 0xFF) << 8))
            img[o + 8:o + 12] = struct.pack('<I', val)
        # No else-branch that guesses: an unreproduced byte must stay VISIBLE as a zero.
        return bytes(img)

    def unreached(self):
        """(count, non_zero_count) of bytes the model never reproduced.

        A ZERO gap is padding we did not have to understand. A NON-ZERO gap is data we are
        dropping - which is exactly what this exercise exists to surface.
        """
        got, orig = self.write(), self.res.sys
        n = min(len(got), len(orig))
        bad = [i for i in range(n) if got[i] != orig[i]]
        return len(bad), sum(1 for i in bad if orig[i] != 0)

    def regions(self):
        """(carried_verbatim, modelled, computed, zero_fill) byte split of the segment.

        ⭐ DISCLOSURE, NOT DECORATION. Byte identity alone cannot tell a rebuilt region from a
        copied one, and this vault's own law is that a claimed region is evidence ONLY IF A WRONG
        CLAIM COULD HAVE BEEN REJECTED. `carried_verbatim` is the part of a passing file that
        could not have failed; quote it next to the coverage figure, never instead of it.
        """
        modelled = self.count * STRIDE
        return (HEADER, modelled, 4, self.size - HEADER - modelled - 4)


def read_ywr(src):
    """The RSC7 segment FLAGS are needed to recompute the page-count record, and Res does not
    keep them - so they are parsed from the container header here and handed to the model."""
    blob = bytes(src) if isinstance(src, (bytes, bytearray)) else open(src, 'rb').read()
    _magic, _ver, sysf, gfxf = struct.unpack_from('<4sIII', blob, 0)
    return Ywr(Res.from_bytes(blob), (sysf, gfxf))
