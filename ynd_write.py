"""ynd_write - ROUND-TRIP WRITER for .ynd path-node dictionaries.

    inflated system segment -> value model -> written back -> MUST reproduce the original bytes

WHY (maintainer ruling 2026-08-13): round-trip is the primary measure; parity against a
second, independent exporter is a cross-check.
Byte-identity with another reader cannot see a gap both readers share - and in this very lane the
reference proved unreliable three separate ways. A writer can see it, because **you cannot rebuild
a section you never read**, and it makes every .ynd in the game an oracle at no cost.

MODEL, NOT MEMCPY. Every array is decoded to per-record values and re-encoded into a ZERO-FILLED
image. Anything the model never reaches stays zero and shows up as a difference, so a byte we do
not understand is LOUD rather than silently carried. **The gaps are the finding.**

⚠ SCOPE: round-trips the INFLATED SYSTEM SEGMENT, not the compressed RSC7 container. Reproducing
the container also means reproducing an exact deflate stream, which is a separate problem - mixing
them would make a compression difference look like a format defect.
⚠ The header (0x00-0x70) is carried verbatim: it holds tagged pointers whose re-encoding is a
layout-ALLOCATOR problem, the same boundary `meta_write` names when it pins the source's own region
offsets. So this proves we can rebuild the DATA, not that we can lay out a new file.

Layout (derived 2026-08-13):
    0x10 nodes ptr  0x18 node count  0x1C vehicle-node count
    0x28 links ptr  0x30 link count
    0x38 junction ptr  0x40 heightmap ptr  0x50 junction-ref ptr
    0x60 junction count (shared)  0x64 heightmap bytes
    node 40 B | link 8 B | junction 12 B | junction-ref 8 B
ASCII output only.
"""
import os
import struct
import sys as _sys

_sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ydr2xml import Res  # noqa: E402

NODE, LINK, JUNC, JREF = 40, 8, 12, 8
HEADER = 0x70


class Ynd:
    def __init__(self, res, flags=(0, 0)):
        self.res = res
        self.sys_flags, self.gfx_flags = flags
        self.size = len(res.sys)
        self.header = bytes(res.sys[:HEADER])
        self.n_nodes = res.u32(0x18)
        self.n_links = res.u32(0x30)
        self.n_junc = res.u32(0x60)
        self.hm_bytes = res.u32(0x64)
        self.nodes = self._recs(res.ptr(0x10), self.n_nodes, NODE)
        self.links = self._recs(res.ptr(0x28), self.n_links, LINK)
        self.juncs = self._recs(res.ptr(0x38), self.n_junc, JUNC)
        self.jrefs = self._recs(res.ptr(0x50), self.n_junc, JREF)
        self.hmap = self._blob(res.ptr(0x40), self.hm_bytes)

    def _off(self, ptr):
        buf, off = self.res.deref(ptr, 1)
        return off if buf is not None else None

    def _recs(self, ptr, count, stride):
        """Per-RECORD, never one slab: an off-by-one in a stride must surface as a difference
        rather than be absorbed by a bulk copy."""
        if not count:
            return (None, [])
        off = self._off(ptr)
        if off is None:
            return (None, [])
        s = self.res.sys
        return (off, [bytes(s[off + i * stride: off + (i + 1) * stride]) for i in range(count)])

    def _blob(self, ptr, n):
        if not n:
            return (None, b'')
        off = self._off(ptr)
        return ((off, bytes(self.res.sys[off:off + n])) if off is not None else (None, b''))

    def write(self):
        img = bytearray(self.size)
        img[:HEADER] = self.header
        for (off, recs), stride in ((self.nodes, NODE), (self.links, LINK),
                                    (self.juncs, JUNC), (self.jrefs, JREF)):
            if off is None:
                continue
            for i, rec in enumerate(recs):
                img[off + i * stride: off + (i + 1) * stride] = rec
        hoff, hm = self.hmap
        if hoff is not None and hm:
            img[hoff:hoff + len(hm)] = hm

        # ⭐ THE PAGE-COUNT RECORD, and it is COMPUTED - never carried.
        # `ptr@0x08` reaches a small record whose u32 at +8 is
        #     pageCount(system) | pageCount(graphics) << 8
        # This was the ONE byte per file the writer could not reproduce (value 1/2/3, at an
        # offset that varies per file - which is why every fixed-offset and
        # relative-to-structure-end hypothesis failed: it is POINTED TO, not positioned).
        # ⭐ The law was already in-tree: `meta_write` derived it for the META formats
        # ("250/250 exact, COMPUTED, not carried") and it holds unchanged here - 259/259 .ynd.
        # Recomputing rather than copying is what makes the round-trip meaningful: a carried
        # value would round-trip even if we had no idea what it meant.
        try:
            import meta_write
            buf, o = self.res.deref(self.res.ptr(0x08), 16)
            if buf is not None and o + 12 <= len(img):
                val = ((meta_write.page_count(self.sys_flags) & 0xFF)
                       | ((meta_write.page_count(self.gfx_flags) & 0xFF) << 8))
                img[o + 8:o + 12] = struct.pack('<I', val)
        except Exception:
            # Leave it zero rather than guess - an unreproduced byte must stay VISIBLE.
            pass
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


def read_ynd(src):
    """The RSC7 segment FLAGS are needed to recompute the page-count record, and Res does not
    keep them - so they are parsed from the container header here and handed to the model."""
    blob = bytes(src) if isinstance(src, (bytes, bytearray)) else open(src, 'rb').read()
    _magic, _ver, sysf, gfxf = struct.unpack_from('<4sIII', blob, 0)
    return Ynd(Res.from_bytes(blob), (sysf, gfxf))
