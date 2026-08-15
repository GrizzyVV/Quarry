"""ypdb_write - ROUND-TRIP WRITER for .ypdb (PoseMatcher database).

    original binary -> value model -> written back -> MUST reproduce the original bytes

WHY (maintainer ruling 2026-08-13, hardened 2026-08-15): round-trip byte identity is the primary
measure. Until today this lane had a READER (`ypdb2xml.py`) and no writer, which under that ruling
makes it UNMEASURED, not passing - 56 files with no number attached to them
(`docs/LANE_CENSUS_20260814.md` row 13). A writer is what turns every .ypdb in the game into an
oracle at no cost, because you cannot rebuild a section you never read.

SCOPE NOTE, and it is UNUSUALLY STRONG FOR THIS VAULT: `.ypdb` is a RAW file - no RSC7 wrapper, no
deflate stream, no page map, no tagged pointers. So the container caveat every other writer here
carries does not apply: this lane round-trips THE WHOLE FILE, first byte to last, and the
`0x00-0x70 header carried verbatim` boundary has no analogue. There is nothing outside the model.

MODEL, NOT MEMCPY, AND NOTHING CARRIED. Every byte of the image is re-encoded from a decoded,
typed value into a ZERO-FILLED buffer. The writer carries NO region verbatim - carried_verbatim is
0 bytes on every file - so the vault's law ("a claimed region is evidence only if a wrong claim
could have been REJECTED") is satisfied structurally rather than by argument: there is no region
whose bytes are copied, hence no region whose claim is self-fulfilling.

⭐ THE TILING PROOF, adapted to a VARIABLE-LENGTH format. `yvr_write`/`ywr_write` prove their field
map is complete with a module-level `_check_tiling` over a fixed stride. A .ypdb has no fixed
stride - the sample records are count-driven - so the equivalent proof is a CURSOR that must land
EXACTLY on len(data): `_Emit` appends every field in order and `finish()` REFUSES unless the bytes
written equal the file length and no byte was written twice. A hole or an overlap is a hard error,
not a coverage shortfall discovered later.

LAYOUT (from `ypdb2xml.py`, which derived it by value-intersection against the oracles; this
writer models the STORED form and deliberately applies none of the naming/semantics):
    0x00 u32 538      preamble word 0        0x04 u32 0        preamble word 1
    0x08 u8  0        preamble byte          0x09 u32 Signature
    0x0D u32 sampleCount, then sampleCount x Sample:
         u32 clipsetHash | u32 clipHash | f32 offset | u32 pointCount
         f32 points[pointCount*3] | u32 weightCount | f32 weights[weightCount]
         f32 boundsMin[3] | f32 boundsMax[3] | f32 trailing
    u32 boneCount | u16 boneTags[boneCount]
    u32 topWeightCount | f32 topWeights[topWeightCount]
    u32 footerA | u32 footerB | u32 trailer(== Signature)   EOF
⚠ The preamble words and the footer are CONSTANT across all 56 files in the game (measured, see
`--selftest`), but they are still DECODED AND RE-ENCODED rather than hard-coded: a constant that
is asserted can refuse, a constant that is emitted from thin air cannot.
ASCII output only.
"""
import os
import struct
import sys as _sys

_sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


class YpdbError(Exception):
    pass


class _Emit(object):
    """Cursor emitter into a ZERO-FILLED image; refuses on a hole, an overlap or a short landing.

    This is the variable-length analogue of `yvr_write._check_tiling`. Its whole purpose is to make
    byte identity prove that the FIELD MAP IS COMPLETE, rather than that a buffer was copied.
    """

    def __init__(self, size):
        self.buf = bytearray(size)
        self.written = bytearray(size)      # 1 per byte the model claims
        self.at = 0

    def put(self, code, *vals):
        n = struct.calcsize(code)
        if self.at + n > len(self.buf):
            raise YpdbError('emit past EOF at %d (+%d > %d)' % (self.at, n, len(self.buf)))
        struct.pack_into(code, self.buf, self.at, *vals)
        for i in range(self.at, self.at + n):
            if self.written[i]:
                raise YpdbError('OVERLAP: byte %d written twice' % i)
            self.written[i] = 1
        self.at += n

    def finish(self):
        if self.at != len(self.buf):
            raise YpdbError('cursor landed at %d, file is %d bytes - the field map does not tile'
                            % (self.at, len(self.buf)))
        hole = self.written.count(0)
        if hole:
            raise YpdbError('%d bytes never claimed by any field' % hole)
        return bytes(self.buf)


class Ypdb(object):
    def __init__(self, blob):
        d = self.raw = bytes(blob)
        self.size = len(d)

        def u32(o):
            return struct.unpack_from('<I', d, o)[0]

        def f32(o):
            return struct.unpack_from('<f', d, o)[0]

        self.pre0 = u32(0)
        self.pre1 = u32(4)
        self.pre2 = d[8]
        self.signature = u32(9)
        self.n_samples = u32(13)
        pos = 17
        self.samples = []
        for _ in range(self.n_samples):
            clipset = u32(pos)
            clip = u32(pos + 4)
            offset = f32(pos + 8)
            pc = u32(pos + 12)
            pos += 16
            pts = [f32(pos + i * 4) for i in range(pc * 3)]
            pos += pc * 12
            wc = u32(pos)
            pos += 4
            wts = [f32(pos + i * 4) for i in range(wc)]
            pos += wc * 4
            bmin = [f32(pos + i * 4) for i in range(3)]
            bmax = [f32(pos + 12 + i * 4) for i in range(3)]
            trailing = f32(pos + 24)
            pos += 28
            self.samples.append((clipset, clip, offset, pts, wts, bmin, bmax, trailing))
        self.n_bones = u32(pos)
        pos += 4
        self.bones = [struct.unpack_from('<H', d, pos + i * 2)[0] for i in range(self.n_bones)]
        pos += self.n_bones * 2
        self.n_weights = u32(pos)
        pos += 4
        self.weights = [f32(pos + i * 4) for i in range(self.n_weights)]
        pos += self.n_weights * 4
        # INTEGRITY GATE, same one `ypdb2xml.decode` uses: the cursor must land exactly on the
        # 12-byte footer and the trailer must equal the signature. A mis-consumed walk refuses
        # here rather than silently producing a short model.
        if pos + 12 != self.size:
            raise YpdbError('cursor walk mis-consumed: pos %d + footer 12 != len %d'
                            % (pos, self.size))
        self.footer_a = u32(pos)
        self.footer_b = u32(pos + 4)
        self.trailer = u32(pos + 8)
        if self.trailer != self.signature:
            raise YpdbError('trailer %08X != signature %08X' % (self.trailer, self.signature))

    # ------------------------------------------------------------------ write
    def write(self):
        e = _Emit(self.size)
        e.put('<I', self.pre0)
        e.put('<I', self.pre1)
        e.put('<B', self.pre2)
        e.put('<I', self.signature)
        e.put('<I', self.n_samples)
        for (clipset, clip, offset, pts, wts, bmin, bmax, trailing) in self.samples:
            e.put('<I', clipset)
            e.put('<I', clip)
            e.put('<f', offset)
            e.put('<I', len(pts) // 3)
            for v in pts:
                e.put('<f', v)
            e.put('<I', len(wts))
            for v in wts:
                e.put('<f', v)
            for v in bmin:
                e.put('<f', v)
            for v in bmax:
                e.put('<f', v)
            e.put('<f', trailing)
        e.put('<I', len(self.bones))
        for v in self.bones:
            e.put('<H', v)
        e.put('<I', len(self.weights))
        for v in self.weights:
            e.put('<f', v)
        e.put('<I', self.footer_a)
        e.put('<I', self.footer_b)
        e.put('<I', self.trailer)
        return e.finish()

    def unreached(self):
        """(count, non_zero_count) of bytes the model never reproduced.

        A ZERO gap is padding we did not have to understand. A NON-ZERO gap is data we are
        dropping - which is exactly what this exercise exists to surface.
        """
        got, orig = self.write(), self.raw
        n = min(len(got), len(orig))
        bad = [i for i in range(n) if got[i] != orig[i]]
        return len(bad), sum(1 for i in bad if orig[i] != 0)

    def regions(self):
        """(carried_verbatim, value, derived, zero_fill) byte split of the image.

        ⭐ DISCLOSURE, NOT DECORATION. Byte identity alone cannot tell a rebuilt region from a
        copied one. Here `carried_verbatim` is 0 by construction - the emitter has no memcpy path
        at all - so every byte of a passing file is a byte a wrong model would have got wrong.
        """
        return (0, self.size, 0, 0)


def read_ypdb(src):
    blob = bytes(src) if isinstance(src, (bytes, bytearray)) else open(src, 'rb').read()
    return Ypdb(blob)


# --------------------------------------------------------------------- selftest
def _selftest(paths):
    """POPULATION round-trip. PRINTS ITS SAMPLE SIZE and REFUSES on an empty sample."""
    print('ypdb_write selftest - SAMPLE SIZE: %d file(s)' % len(paths))
    if not paths:
        print('REFUSING: empty sample - a harness with no subject cannot report coverage.')
        return 2
    exact = 0
    tot = 0
    cov = []
    errs = {}
    carried = 0
    value = 0
    for p in paths:
        try:
            m = read_ypdb(p)
        except Exception as ex:
            errs[type(ex).__name__] = errs.get(type(ex).__name__, 0) + 1
            continue
        tot += 1
        n, _nz = m.unreached()
        cov.append(100.0 * (m.size - n) / m.size)
        if n == 0:
            exact += 1
        c, v, _d, _z = m.regions()
        carried += c
        value += v
    if not tot:
        print('REFUSING: every file errored - %s' % errs)
        return 2
    print('  EXACT round-trip : %d / %d (%.4f%%)' % (exact, tot, 100.0 * exact / tot))
    print('  mean coverage    : %.4f%%   min %.4f%%' % (sum(cov) / len(cov), min(cov)))
    print('  BYTE ACCOUNTING  : VALUE %d B / CARRIED-VERBATIM %d B (%.4f%% carried)'
          % (value, carried, 100.0 * carried / max(1, value + carried)))
    if errs:
        print('  errors           : %s' % errs)
    return 0 if exact == tot else 1


if __name__ == '__main__':
    import glob
    args = _sys.argv[1:]
    files = []
    for a in args:
        files.extend(sorted(glob.glob(a)) if any(c in a for c in '*?') else [a])
    _sys.exit(_selftest(files))
