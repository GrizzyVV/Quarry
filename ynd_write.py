"""ynd_write - ROUND-TRIP WRITER for .ynd path-node dictionaries.

    inflated system segment -> value model -> written back -> MUST reproduce the original bytes

WHY (maintainer ruling 2026-08-13): round-trip is the primary measure; parity against a
second, independent exporter is a cross-check.
Byte-identity with another reader cannot see a gap both readers share - and in this very lane the
reference proved unreliable three separate ways. A writer can see it, because **you cannot rebuild
a section you never read**, and it makes every .ynd in the game an oracle at no cost.

⛔⛔ BYTE ACCOUNT (added 2026-08-16, `regions()`), AND IT CORRECTS THE PARAGRAPH BELOW IT.
Measured 2026-08-16 over the 259 files this lane's archive list reaches (`x64e.rpf`; a BOARD -
the census is 1,027, so this is 25.2% of the lane, and the identity below held on 259 of 259):
    VALUE 0.0000% (0 B) | DERIVED 0.0158% (1,036 B) | ZERO-FILL 23.4819% | CARRIED 76.5023%
    CARRIED OF THE BYTES ACTUALLY EMITTED (value+derived+carried) = **99.9794%**
**`value` IS ZERO.** This writer decodes nothing into typed fields: `_recs` slices whole records
out of `res.sys` and `write()` assigns those slices straight back, so the "per-record values"
claim below is true only in the sense of per-record COPIES. The one modelled byte-group in the
whole file is the 4-byte page-count word, which is COMPUTED - 4 bytes per file, 1,036 in 6.56 MB.
⚠ Read carried against the EMITTED denominator, not the image. A .ynd is padded to an 8/16/24/32
KB page and roughly a quarter of the image is empty page, so zero-fill deflates carried's share of
the whole file to 76.5% while the writer's own output is 99.98% photocopy. Quote `regions()` next
to the coverage figure, never instead of it, and never quote carried-of-image alone.

MODEL, NOT MEMCPY - ⚠ ASPIRATIONAL, NOT WHAT THE CODE DOES; see the byte account above. Every
array is walked PER RECORD and re-emitted into a ZERO-FILLED image. Anything the model never
reaches stays zero and shows up as a difference, so a byte we do not understand is LOUD rather
than silently carried. **The gaps are the finding.** What the per-record walk buys is that a wrong
stride, a wrong count or a wrong array offset is REJECTABLE; what it does not buy is any claim
about the CONTENT of a node, a link, a junction or the heightmap.

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

# Byte-account kinds for `Ynd.regions()`. _ZERO is the DEFAULT so an unclaimed byte can never be
# credited to a bucket by omission; _VALUE exists and is never painted, which is the finding.
_ZERO, _VALUE, _DERIVED, _CARRIED = 0, 1, 2, 3


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

    # ------------------------------------------------------------------ byte account
    def _paint(self):
        """Kind-per-byte mark array over the image `write()` produces.

        ⛔ IT MIRRORS `write()` STATEMENT FOR STATEMENT, in the SAME ORDER and with the SAME SLICE
        EXPRESSIONS, so a later assignment overwrites an earlier claim exactly as it overwrites the
        bytes - and so a slice that would grow or shrink the image grows or shrinks the mark by the
        same amount. That is what makes `len(mark) == len(write())` an identity rather than a hope.
        Slice-assigned, never looped per byte: this runs at population over 1,027 files.
        """
        mark = bytearray(self.size)                      # _ZERO until something claims it
        mark[:HEADER] = bytes([_CARRIED]) * len(self.header)
        for (off, recs), stride in ((self.nodes, NODE), (self.links, LINK),
                                    (self.juncs, JUNC), (self.jrefs, JREF)):
            if off is None:
                continue
            for i, rec in enumerate(recs):
                mark[off + i * stride: off + (i + 1) * stride] = bytes([_CARRIED]) * len(rec)
        hoff, hm = self.hmap
        if hoff is not None and hm:
            mark[hoff:hoff + len(hm)] = bytes([_CARRIED]) * len(hm)
        # The page-count record is the ONE thing this writer computes; mirror `write()`'s guard
        # AND its try/except so the mark agrees with the bytes even when the import or the deref
        # fails and `write()` leaves the word zero.
        try:
            import meta_write
            buf, o = self.res.deref(self.res.ptr(0x08), 16)
            if buf is not None and o + 12 <= len(mark):
                _val = ((meta_write.page_count(self.sys_flags) & 0xFF)      # noqa: F841
                        | ((meta_write.page_count(self.gfx_flags) & 0xFF) << 8))
                mark[o + 8:o + 12] = bytes([_DERIVED]) * 4
        except Exception:
            pass
        return mark

    def regions(self):
        """(value, derived, zero_fill, carried) byte split of the reproduced image.

        ⛔⛔ THE HONEST HEADLINE, AND IT IS THE WORST ONE IN THE REGISTRY: **`value` IS ZERO ON
        EVERY FILE.** This writer decodes NOTHING into typed fields. `_recs` slices whole records
        out of `res.sys` and `write()` assigns those slices straight back; the header is a 0x70
        memcpy; the heightmap is a blob copy. The only byte in the image that is not a photocopy is
        the 4-byte page-count word, which is COMPUTED (`derived`). Everything else the model
        reproduces is CARRIED - so 99.9794% of the bytes this lane actually emits could not have
        failed on their own content, and the 259/259 byte-exact figure is a statement about the
        LAYOUT (offsets, counts and strides land where the model says) and NOT about the format.
        ⭐ WHAT THE 100% DOES BUY, stated so it is not read as nothing: the per-RECORD copy makes
        an off-by-one stride or a wrong count REJECTABLE, and the page-count word is a genuine
        must-recompute. Quote carried WITH the coverage figure, never instead of it.
        ⚠ AND DO NOT READ THE CARRIED PERCENTAGE AS "MOSTLY UNDERSTOOD BECAUSE IT IS SMALL". A
        .ynd is padded to an 8/16/24/32 KB page and a quarter of the image is empty page, so
        zero_fill deflates carried's share of the WHOLE FILE to 76.50%. Against the bytes the
        writer actually reproduces (value + derived + carried) the carried share is 99.9794%.
        """
        mark = self._paint()
        carried = mark.count(_CARRIED)
        derived = mark.count(_DERIVED)
        value = mark.count(_VALUE)                       # 0 by construction - nothing is decoded
        zero_fill = len(mark) - carried - derived - value
        return (value, derived, zero_fill, carried)


def read_ynd(src):
    """The RSC7 segment FLAGS are needed to recompute the page-count record, and Res does not
    keep them - so they are parsed from the container header here and handed to the model."""
    blob = bytes(src) if isinstance(src, (bytes, bytearray)) else open(src, 'rb').read()
    _magic, _ver, sysf, gfxf = struct.unpack_from('<4sIII', blob, 0)
    return Ynd(Res.from_bytes(blob), (sysf, gfxf))
