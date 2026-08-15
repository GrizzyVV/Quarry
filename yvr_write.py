"""yvr_write - ROUND-TRIP WRITER for .yvr vehicle-recording lists (RSC7 v1).

    inflated system segment -> value model -> written back -> MUST reproduce the original bytes

WHY (maintainer ruling 2026-08-13, hardened 2026-08-15): round-trip byte identity is the primary
measure. Until today this lane had a READER (`yvr2xml.py`) and no writer, which under that ruling
makes it **UNMEASURED, not passing** - 7,533 files with no number attached to them
(`docs/LANE_CENSUS_20260814.md` row 2). A writer is what turns every .yvr in the game into an
oracle at no cost, because **you cannot rebuild a section you never read**.

MODEL, NOT MEMCPY - and here that is stronger than in `ynd_write`, the template this follows.
`ynd_write` re-emits each record as an opaque per-record byte slice; this writer DECODES EVERY
RECORD TO TYPED FIELDS and re-encodes them from those values into a ZERO-FILLED image. So the
32-byte stride is not copied, it is REBUILT from `FIELDS` - and `FIELDS` is checked at import to
tile 0x00..0x20 with no hole and no overlap. A byte inside a record that no named field covers
would stay zero and count against coverage. **The gaps are the finding.**

⚠ SCOPE: round-trips the INFLATED SYSTEM SEGMENT, not the compressed RSC7 container. Reproducing
the container also means reproducing an exact deflate stream, which is a separate problem - mixing
them would make a compression difference look like a format defect. (`.yvr` carries NO graphics
segment: 7,533/7,533 measured 2026-08-15, and a non-empty one REFUSES rather than being ignored.)

⚠ The header (0x00-0x20) is carried verbatim - 32 bytes, i.e. 0.4% of the smallest (8,192 B)
segment in the lane. It holds a vtable u64, the tagged block-map pointer @0x08, the tagged array
pointer @0x10 and {u16 count, u16 capacity} @0x18. Re-encoding the two pointers is a layout
ALLOCATOR problem, the same boundary `meta_write` names when it pins the source's own region
offsets - so this proves we can rebuild the DATA, not that we can lay out a new file.
⭐ The COUNT is NOT an unpinned carried claim even though it sits inside that header: the writer
DRIVES the array off it, so a wrong count writes the wrong number of records and the round-trip
rejects it. count == capacity on 7,533/7,533 (max count 8,336, so both fit a u16 with room).

Layout (derived 2026-08-15 over all 7,533 .yvr in the game; see `yvr2xml.py` for the field
semantics, which this writer deliberately does NOT apply - it models the STORED form):
    0x00 u64 vtable   0x08 ptr -> block map   0x10 ptr -> record array
    0x18 u16 count    0x1A u16 capacity
    record array at 0x20, stride 32, immediately after the header (gap 0 on 7,527/7,527 non-empty)
    block map at the array's end (delta 0 on 7,527/7,527; at 0x20 on the 6 empty stubs)
    everything past the block map is zero on 7,533/7,533 (non-zero run from the map = 9 bytes,
    i.e. the single page-count word at +8 and nothing else)
ASCII output only.
"""
import os
import struct
import sys as _sys

_sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ydr2xml import Res  # noqa: E402
import meta_write        # noqa: E402  (page_count - the COMPUTED page record, see write())

HEADER = 0x20
STRIDE = 32
ARR_PTR = 0x10
COUNT = 0x18
BLOCKMAP_PTR = 0x08

# ⭐ THE RECORD MODEL. Each entry is (offset-in-record, struct code). Field SEMANTICS (the
# fixed-point scales, the pedal divisors) belong to `yvr2xml.py`; what matters to a round-trip is
# the STORED form and, above all, that these fields TILE THE STRIDE. See _check_tiling.
FIELDS = (
    (0x00, '<i'),      # Time (ms)
    (0x04, '<3h'),     # Velocity  x/y/z   (int16 fixed-point)
    (0x0A, '<3b'),     # Right     x/y/z   (int8)
    (0x0D, '<3b'),     # Forward   x/y/z   (int8)
    (0x10, '<b'),      # Steering          (int8)
    (0x11, '<3B'),     # GasPedal, BrakePedal, Handbrake (uint8)
    (0x14, '<3f'),     # Position  x/y/z   (float32)
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


_check_tiling(FIELDS, STRIDE, 'yvr')


class Yvr:
    def __init__(self, res, flags=(0, 0)):
        if res.version != 1:
            raise ValueError('yvr expects RSC7 version 1, got %d' % res.version)
        if len(res.gfx):
            # NO SILENT DEFAULTS: the lane is system-segment-only in 7,533/7,533. A file that
            # broke that would be silently half-measured if this were a warning.
            raise ValueError('yvr carries no graphics segment; got %d bytes' % len(res.gfx))
        self.res = res
        self.sys_flags, self.gfx_flags = flags
        self.size = len(res.sys)
        self.header = bytes(res.sys[:HEADER])
        self.count = res.u16(COUNT)
        self.capacity = res.u16(COUNT + 2)
        self.arr = None
        self.records = []
        if self.count:
            buf, off = res.deref(res.ptr(ARR_PTR), self.count * STRIDE)
            if buf is None:
                raise ValueError('yvr record array (%d x %d B) does not resolve inside the '
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
        # ⭐ The law was already in-tree twice: `meta_write` derived it for the META formats
        # ("250/250 exact, COMPUTED, not carried") and `ynd_write` re-confirmed it on 259/259
        # .ynd. It holds unchanged here - measured 7,533/7,533 .yvr before this writer existed.
        # Recomputing rather than copying is what makes the round-trip meaningful: a carried
        # value would round-trip even if we had no idea what it meant.
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


def read_yvr(src):
    """The RSC7 segment FLAGS are needed to recompute the page-count record, and Res does not
    keep them - so they are parsed from the container header here and handed to the model."""
    blob = bytes(src) if isinstance(src, (bytes, bytearray)) else open(src, 'rb').read()
    _magic, _ver, sysf, gfxf = struct.unpack_from('<4sIII', blob, 0)
    return Yvr(Res.from_bytes(blob), (sysf, gfxf))
