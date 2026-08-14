"""ybn_write - ROUND-TRIP WRITER for .ybn standalone collision bounds (RSC7 v43).

    inflated system segment -> value model -> written back -> MUST reproduce the original bytes

WHY THIS LANE: `.ybn` is 15,139 files and gates the mapping milestone - collision is not optional
for an authoring tool. And after `ynv` (declared CLOSED at 40/40, then measured 13.6% unread by
BOTH exporters) no lane's status should be believed until round-trip has spoken.

MODEL, NOT MEMCPY: regions are captured from decoded pointers/counts into a ZERO-FILLED image.
Whatever is unreached stays zero and is REPORTED. **The gaps are the finding.**

Structure per `ydr2xml`'s phBound decoder (root phBound at system offset 0):
  composite:  u16 child count @+0xA0 · children ptr array @+0x70 (n*8)
              transforms @+0x78 (n*64) · flags @+0x90 (n*8, OMITTED when absent)
  geometry:   nverts @+0xD0 · npolys @+0xD4 · nmat u8 @+0x120
              vertices @+0xB0 (nverts*6) · polygons @+0x88 (npolys*16)
              materials @+0xF0 (nmat*8) · poly materials @+0x118 (npolys*1)
⚠ Same scope as the other writers: inflated SYSTEM SEGMENT only; the page-count record at
`ptr@0x08 +8` is COMPUTED (the law from `meta_write`, confirmed on ynd and ynv).
⚠ FIRST PASS: the per-type bound header size is not pinned, so a generous span is captured per
bound. That inflates coverage slightly and is stated here rather than presented as knowledge -
the number to trust is the SHAPE of what remains unreached, not the last decimal.
ASCII output only.
"""
import os
import struct
import sys as _sys

_sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ydr2xml import Res  # noqa: E402

# ⛔ WAS 0x130 - which stopped EXACTLY at the slot that matters. Measured 2026-08-13 over 40
# files: a pointer at bound+0x130 lands on the START of an unreached run in 132 bounds, by far
# the dominant hit, and the writer could not even see the slot. Extended to 0x180 so the header
# is covered; the STRUCTURE it points to is identified but still unfollowed (its element count
# does not factor as any header scalar * 16/32/64 - see the log).
BOUND_SPAN = 0x180


class Ybn:
    def __init__(self, res, flags=(0, 0)):
        self.res = res
        self.sys_flags, self.gfx_flags = flags
        self.size = len(res.sys)
        self.regions = []
        self._seen = set()
        self._bound(0)

    def _off(self, ptr):
        buf, off = self.res.deref(ptr, 1)
        return off if buf is not None else None

    def _flat(self, tagged, nbytes):
        if not tagged or nbytes <= 0:
            return
        off = self._off(tagged)
        if off is not None and off + nbytes <= self.size:
            self.regions.append((off, bytes(self.res.sys[off:off + nbytes])))

    def _flat_at(self, off, nbytes):
        """Capture a span at an ABSOLUTE offset (already resolved), not via a tagged pointer."""
        if nbytes > 0 and off + nbytes <= self.size:
            self.regions.append((off, bytes(self.res.sys[off:off + nbytes])))

    def _bound(self, off, depth=0):
        """Walk one phBound; recurse into composite children. Depth-capped and visit-tracked so a
        malformed graph terminates on evidence rather than recursing forever."""
        s = self.res.sys
        if off in self._seen or depth > 32 or off + 8 > self.size:
            return
        self._seen.add(off)
        self.regions.append((off, bytes(s[off:min(off + BOUND_SPAN, self.size)])))

        # geometry payloads - guarded by the same sanity bounds the decoder uses, so a
        # misread type cannot make us claim a megabyte of coverage from a garbage count
        try:
            nverts, npolys = struct.unpack_from('<I', s, off + 0xD0)[0], \
                struct.unpack_from('<I', s, off + 0xD4)[0]
            nmat = s[off + 0x120]
        except (struct.error, IndexError):
            nverts = npolys = nmat = 0
        if 0 < nverts <= 0x8000 and 0 < npolys <= 0x100000 and nmat:
            self._flat(struct.unpack_from('<I', s, off + 0xB0)[0], nverts * 6)
            self._flat(struct.unpack_from('<I', s, off + 0x88)[0], npolys * 16)
            self._flat(struct.unpack_from('<I', s, off + 0xF0)[0], nmat * 8)
            self._flat(struct.unpack_from('<I', s, off + 0x118)[0], npolys)

        # ⭐ THE +0x130 STRUCTURE - an ARRAY DESCRIPTOR, not an array.
        # This was the dominant unreached region in .ybn (132 of the bounds sampled), and the
        # writer could not see it because BOUND_SPAN stopped at exactly 0x130.
        # Decoded 2026-08-13 by dumping the target rather than guessing a stride:
        #     +0x00 tagged ptr | +0x08 u32 count | +0x0C u32 capacity (== count) | +0x20 records
        # which is the same {ptr, pad, count, capacity} shape meta_write documents for META
        # arrays. Records are 16 B - three floats plus four bytes (the `01 00 80 7F` tail seen
        # in the gap dumps).
        # ⚠ Both placements are captured because which one holds the data is not yet pinned:
        # inline at +0x20, and via the descriptor's own pointer. Whichever is wrong contributes
        # nothing rather than corrupting - and if BOTH land, coverage would double-count, so the
        # number is cross-checked against the gap shrinking, never taken on faith.
        try:
            desc = struct.unpack_from('<I', s, off + 0x130)[0]
        except struct.error:
            desc = 0
        if desc:
            d = self._off(desc)
            if d is not None and d + 0x20 <= self.size:
                self.regions.append((d, bytes(s[d:d + 0x20])))
                try:
                    cnt = struct.unpack_from('<I', s, d + 0x08)[0]
                    cap = struct.unpack_from('<I', s, d + 0x0C)[0]
                    if 0 < cnt <= 0x200000 and cap >= cnt:
                        self._flat_at(d + 0x20, cnt * 16)
                        self._flat(struct.unpack_from('<I', s, d + 0x00)[0], cnt * 16)
                except struct.error:
                    pass

        # composite children
        try:
            n = struct.unpack_from('<H', s, off + 0xA0)[0]
            carr, tr, fl = (struct.unpack_from('<I', s, off + 0x70)[0],
                            struct.unpack_from('<I', s, off + 0x78)[0],
                            struct.unpack_from('<I', s, off + 0x90)[0])
        except struct.error:
            return
        if not n or n > 4096:
            return
        self._flat(carr, n * 8)
        self._flat(tr, n * 64)
        self._flat(fl, n * 8)
        coff = self._off(carr)
        if coff is None:
            return
        for i in range(n):
            try:
                cp = struct.unpack_from('<I', s, coff + i * 8)[0]
            except struct.error:
                break
            if cp:
                c = self._off(cp)
                if c is not None:
                    self._bound(c, depth + 1)

    def write(self):
        img = bytearray(self.size)
        for off, data in self.regions:
            if off is not None and data:
                img[off:off + len(data)] = data
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


def read_ybn(src):
    blob = bytes(src) if isinstance(src, (bytes, bytearray)) else open(src, 'rb').read()
    _m, _v, sysf, gfxf = struct.unpack_from('<4sIII', blob, 0)
    return Ybn(Res.from_bytes(blob), (sysf, gfxf))
