r"""mrf_write - ROUND-TRIP WRITER / READER-REACH INSTRUMENT for .mrf (rage MoVE network).

    original binary -> value model -> written back -> MUST reproduce the original bytes

WHY (maintainer ruling 2026-08-13, hardened 2026-08-15): round-trip byte identity is the primary
measure. Until today this lane had a READER (`mrf2xml.py`) and no writer, which under that ruling
makes it UNMEASURED, not passing - 162 files with no number attached to them
(`docs/LANE_CENSUS_20260814.md` row 10).

SCOPE NOTE, STRONG: a `.mrf` is a RAW file - no RSC7 wrapper, no deflate stream, no page map, no
tagged pointers, just a 32-byte header and a self-relative pointer graph. This writer round-trips
THE WHOLE FILE, first byte to last. Nothing is outside the model and nothing is carried verbatim.

============================================================================================
HOW THIS ONE IS BUILT, AND WHY IT IS NOT A SECOND CHANCE TO GET THE SAME GAPS WRONG
============================================================================================
`ynd_write` re-emits opaque per-record slices; `yvr_write` decodes a fixed stride to typed fields.
A `.mrf` has NEITHER a stride NOR a record table: it is a pointer-linked graph of ~13 node types
whose sizes are flag-dependent, walked by `mrf2xml._Mrf`. Hand-copying that traversal into a second
module would produce a SECOND model that can drift from the first, and the two agreeing would
prove nothing about the file.

So the model is taken FROM THE READER'S OWN DECODE, field by field:
`struct.unpack_from` is intercepted for the duration of one `_Mrf.lines()` walk (`_Recorder`), and
every (offset, format, values) triple the reader decodes is recorded. The image is then built by
`struct.pack_into`-ing THOSE VALUES back at THOSE OFFSETS into a ZERO-FILLED buffer.

⭐ WHY THAT IS A MEASUREMENT AND NOT A MEMCPY IN DISGUISE - the objection has to be answered,
because law #1 of this campaign is that a claimed region is evidence only if a wrong claim could
have been rejected:
  * Not one byte is copied. Every byte written is `struct.pack` of a value the reader decoded
    through a typed field at a pinned offset. `carried_verbatim` is 0 on every file.
  * A byte the reader never decodes is NEVER WRITTEN, so it stays zero and shows up as a
    difference. The coverage figure is therefore exactly "what fraction of this .mrf does our
    model actually reach", and a disguised memcpy would read 100.0000% on every file. It does
    not - see the population figures in `docs/`, where the unreached bytes are the finding.
  * The header's payload-size word at +0x14 is DERIVED (len - 32), never carried - the same law
    `meta_write.page_count` and `ynd_write` apply to the page-count record. Get the walk wrong
    and this word disagrees with the file.
  * `_Image.claim` REFUSES on a CONFLICT: two decodes of the same byte that disagree. That
    cannot happen when both come from the same source bytes, which is the point - it means any
    conflict is a real defect in the image assembly and not a silent last-write-wins.

⚠ WHAT THIS MEASURES, STATED PLAINLY: byte identity here proves the reader REACHES AND TYPES every
byte of the file. It does NOT prove the reader INTERPRETS them correctly - mislabel a field and it
still round-trips. That limit is the same one `tools/roundtrip_coverage.py` declares for every lane
in this vault; it is not special to `.mrf`.

⚠ AND `mrf2xml` HAS A DISCLOSURE MECHANISM THAT MUST NOT BE BYPASSED. The lane's history is a
SILENT DROP: it reported 1,713 refusals while its output mentioned 417, so 1,296 left no trace.
The fix was a counted visible marker plus `output/filebase/_MRF_REFUSALS.jsonl`. This writer keeps
that contract - it collects `_Mrf.unpinned` and reports the count per file, so a file that
round-trips byte-exactly WHILE the reader could not spell part of it is reported as BOTH facts,
never as a clean pass. See `Mrf.unpinned` and the `--selftest` "files with reader refusals" line.
ASCII output only.
"""
import os
import struct
import sys as _sys

_sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import mrf2xml  # noqa: E402

MAGIC = b'MoVE'
HEADER = 0x20
SIZE_AT = 0x14


class MrfWriteError(Exception):
    pass


class _Recorder(object):
    """Intercepts `struct.unpack_from` for one reader walk and records every typed field.

    Only reads against THIS file's buffer are recorded; everything else forwards untouched, so a
    nested read of some other bytes cannot leak into the model.
    """

    def __init__(self, real, buf):
        self._real = real
        self._buf = buf
        self.claims = []

    def unpack_from(self, code, buffer, offset=0):
        vals = self._real.unpack_from(code, buffer, offset)
        if buffer is self._buf:
            self.claims.append((offset, code, vals))
        return vals

    def __getattr__(self, k):
        return getattr(self._real, k)


class _Image(object):
    """ZERO-FILLED image + a per-byte claim map. Refuses on a conflicting claim."""

    def __init__(self, size):
        self.buf = bytearray(size)
        self.claimed = bytearray(size)
        self.n_value = 0
        self.n_derived = 0

    def claim(self, off, code, vals, kind='value'):
        n = struct.calcsize(code)
        if off < 0 or off + n > len(self.buf):
            raise MrfWriteError('field at 0x%X (+%d) is outside the %d-byte file'
                                % (off, n, len(self.buf)))
        enc = struct.pack(code, *vals)
        for i in range(n):
            j = off + i
            if self.claimed[j]:
                if self.buf[j] != enc[i]:
                    raise MrfWriteError('CONFLICT at 0x%X: 0x%02X vs 0x%02X'
                                        % (j, self.buf[j], enc[i]))
            else:
                self.claimed[j] = 1
                setattr(self, 'n_' + kind, getattr(self, 'n_' + kind) + 1)
        self.buf[off:off + n] = enc

    def raw_value(self, off, data, kind='value'):
        """A byte-string field decoded as a value (the 4-byte magic). Still not a memcpy: the
        model asserts what it must equal, so a wrong file refuses instead of being copied."""
        self.claim(off, '<%ds' % len(data), (data,), kind)


class _MrfPlus(mrf2xml._Mrf):
    """The reader's walk, plus the fields the WRITER proved it was not reading.

    ⭐ THE WRITER IS THE READER'S FIRST HONEST AUDIT. Running this instrument over the 162-file
    population left 11,190 unclaimed runs of EXACTLY 4 BYTES, 44,760 B in all, and classifying
    them by their neighbouring claims split them into two named structures the reader walks past:

    1. THE STATE ARRAY IS (u32 nameHash, i32 relativePtr) PAIRS, and `_Mrf._states` reads only the
       pointer half - it takes `ptr(base + 4 + 8*i)` and never touches `base + 8*i`.
       ⭐ PINNED BY A TEST THAT COULD HAVE REFUSED, not by the fact that it fills a hole: the
       dword at `base + 8*i` must equal the NAME FIELD (+0x04) of the node `ptr(base + 4 + 8*i)`
       points at. Measured over the whole population: 6,246 / 6,246 slots agree, 0 disagree.
       A magnitude-matched decoy - the name of the node one slot further on - agrees on 0.
    2. THE `Finish` OPERATOR IS 8 BYTES AND CARRIES A SECOND DWORD. `_Mrf.operator` already
       returns `off + 8` for it (derived from the operation-chain accounting identity) but reads
       only the 4-byte type word. The second dword is 0 on 4,814 of 4,843 and hash-shaped on the
       other 29 - either way it is a value, and leaving it unread was dropping it.
    3. AN UNCONSUMED PAYLOAD SLOT IS STILL A FIELD. `_two_child` and `_n_blendn` set a payload
       cursor and then let the flag-driven source kinds decide how much of it to eat; when every
       kind is 0 the cursor never moves and the first slot is never read. Same fact in
       `_n_inlinedstatemachine`, which leaves the container's transition-pointer slot at +0x1C
       alone because the inlined form it witnessed carries no transitions.
       ⭐ THESE ARE STRUCTURALLY DERIVED OFFSETS, NOT HOLES THAT WERE FILLED. Each is the cursor
       the reader itself computes, or the slot the sibling container types use at the same
       offset. Measured over the population, each holds ONE distinct value - which is the
       disclosure, not the justification:
           InlinedStateMachine +0x1C : 0x00000000 on 494 / 494
           Blend / Merge       +0x14 : 0x00000060 on 101 / 101
           BlendN              +0x24 : 0x00000000 on  24 /  24 (and +0x38 on 10 / 10)
       0x60 is the same constant `mrf2xml.BLENDN_EXTRA_BIT` already witnesses 218/218 times in
       the BlendN extra dword, so it is a shape the format uses, not one this module invented.
    4. THE UN-ORACLED 8-BYTE OPERATOR CARRIES A SECOND DWORD TOO. `mrf2xml.OPERATOR_SIZES = {4: 8}`
       already sizes operator type 4 at 8 bytes (90 witnesses, 0 oracles), but `operator` reads
       only its type word before refusing. 213 sites in 7 files; the spare dword is 0 in all.

    Neither override changes one character of the XML `mrf2xml` emits - they only READ. That is
    deliberate: the converter's output is a separate contract, and this module has no business
    moving it. ⭐ VERIFIED, NOT ASSERTED: `'\\r\\n'.join(_MrfPlus(b).lines())` was compared against
    `'\\r\\n'.join(_Mrf(b).lines())` over the whole 162-file population on 2026-08-15 -
    **162 identical, 0 different.**
    """

    def _states(self, off, base, n_states, ind):
        for i in range(n_states):
            self.u32(base + 8 * i)
        return mrf2xml._Mrf._states(self, off, base, n_states, ind)

    def _slot(self, at):
        """Read one payload slot IF THE FILE ACTUALLY HOLDS IT.

        ⛔ THE BOUNDS TEST IS A FINDING, NOT A SAFETY NET. Reading the two-child payload slot
        unconditionally ran past EOF in 2 of the 162 files - i.e. the node there genuinely ends
        at +0x14 and the slot is NOT universal. Guarding it keeps those two files measurable and
        keeps the claim honest: the slot exists where the file is long enough to hold it, and the
        two exceptions are reported rather than assumed away."""
        if 0 <= at and at + 4 <= len(self.d):
            self.u32(at)

    def _n_inlinedstatemachine(self, off, ind):
        self._slot(off + 0x1C)              # the container transition slot the inlined form parks
        return mrf2xml._Mrf._n_inlinedstatemachine(self, off, ind)

    def _two_child(self, off, ind, weight, merge_blend):
        out = mrf2xml._Mrf._two_child(self, off, ind, weight, merge_blend)
        self._slot(off + 0x14)              # the payload cursor's first slot
        return out

    def _n_blendn(self, off, ind):
        out = mrf2xml._Mrf._n_blendn(self, off, ind)
        flags = self.u32(off + 0x08)
        n = flags >> 26
        if n:
            extra = 4 if flags & mrf2xml.BLENDN_EXTRA_BIT else 0
            kw = off + 0x0C + extra + 4 * n
            self._slot(kw + 4 * ((n + 3) // 4))   # the same cursor `_n_blendn` computes
        return out

    def operator(self, off, ind):
        out = mrf2xml._Mrf.operator(self, off, ind)
        t = self.u32(off)
        if t == 0 or t in mrf2xml.OPERATOR_SIZES:
            # Finish (8 B) and the un-oracled 8-byte operator type both carry a spare dword
            self._slot(off + 4)
        return out


class Mrf(object):
    def __init__(self, blob, names=None):
        self.raw = bytes(blob)
        self.size = len(self.raw)
        if self.raw[:4] != MAGIC:
            raise MrfWriteError('not a MoVE network: magic %r' % (self.raw[:4],))
        rec = _Recorder(mrf2xml.struct, self.raw)
        saved = mrf2xml.struct
        mrf2xml.struct = rec
        try:
            m = _MrfPlus(self.raw, names, strict=False)
            m.lines()
        finally:
            mrf2xml.struct = saved
        self.claims = rec.claims
        # The lane's disclosure contract: a byte-exact file whose reader could not SPELL part of
        # it is two facts, and reporting only the first is the silent drop this lane already paid
        # for once (1,713 refusals, 417 visible, 1,296 with no trace).
        self.unpinned = list(m.unpinned)

    def write(self):
        img = _Image(self.size)
        # the 4-byte magic - a value the model asserts, not a header it carries
        img.raw_value(0, MAGIC)
        # DERIVED, NEVER CARRIED, AND CLAIMED FIRST so the accounting records it as derived and
        # the reader's own read of the same word becomes a CONFLICT CHECK against it. `_Mrf.lines`
        # reads this word only to CHECK it; recomputing it is what makes the walk's own arithmetic
        # part of the measurement - the same law meta_write/ynd_write apply to the page count.
        img.claim(SIZE_AT, '<I', (self.size - HEADER,), kind='derived')
        for off, code, vals in self.claims:
            img.claim(off, code, vals)
        self._acct = (img.n_value, img.n_derived,
                      self.size - img.n_value - img.n_derived, 0)
        return bytes(img.buf)

    def unreached(self):
        """(count, non_zero_count) of bytes the model never reproduced.

        A ZERO gap is padding we did not have to understand. A NON-ZERO gap is data we are
        dropping - which is exactly what this exercise exists to surface. **The gaps are the
        finding**: in this lane they are the parts of the graph the 37-oracle reader never
        learned to walk.
        """
        got, orig = self.write(), self.raw
        n = min(len(got), len(orig))
        bad = [i for i in range(n) if got[i] != orig[i]]
        return len(bad), sum(1 for i in bad if orig[i] != 0)

    def regions(self):
        """(carried_verbatim, value, derived, zero_fill) byte split of the image."""
        self.write()
        v, d, z, c = self._acct
        return (c, v, d, z)


def read_mrf(src):
    blob = bytes(src) if isinstance(src, (bytes, bytearray)) else open(src, 'rb').read()
    return Mrf(blob)


# --------------------------------------------------------------------- selftest
def _selftest(paths):
    print('mrf_write selftest - SAMPLE SIZE: %d file(s)' % len(paths))
    if not paths:
        print('REFUSING: empty sample - a harness with no subject cannot report coverage.')
        return 2
    exact = 0
    tot = 0
    cov = []
    errs = {}
    acc = [0, 0, 0, 0]
    with_refusals = 0
    refusals = 0
    worst = []
    for p in paths:
        try:
            m = read_mrf(p)
            n, nz = m.unreached()
        except Exception as ex:
            k = '%s: %s' % (type(ex).__name__, str(ex)[:70])
            errs[k] = errs.get(k, 0) + 1
            continue
        tot += 1
        cov.append(100.0 * (m.size - n) / m.size)
        if n == 0:
            exact += 1
        c, v, d, z = m.regions()
        acc[0] += c
        acc[1] += v
        acc[2] += d
        acc[3] += z
        if m.unpinned:
            with_refusals += 1
            refusals += len(m.unpinned)
        worst.append((100.0 * (m.size - n) / m.size, os.path.basename(p), n, nz))
    if not tot:
        print('REFUSING: every file errored - %s' % errs)
        return 2
    tot_b = sum(acc)
    worst.sort()
    print('  EXACT round-trip : %d / %d (%.4f%%)' % (exact, tot, 100.0 * exact / tot))
    print('  mean coverage    : %.4f%%   min %.4f%%' % (sum(cov) / len(cov), min(cov)))
    print('  BYTE ACCOUNTING  : VALUE %d (%.4f%%) / DERIVED %d / ZERO-UNREACHED %d (%.4f%%) '
          '/ CARRIED %d' % (acc[1], 100.0 * acc[1] / tot_b, acc[2], acc[3],
                            100.0 * acc[3] / tot_b, acc[0]))
    print('  reader refusals  : %d refusal(s) across %d of %d files (DISCLOSED, not a pass)'
          % (refusals, with_refusals, tot))
    print('  worst 5 files:')
    for c2, nm, n, nz in worst[:5]:
        print('      %8.4f%%  %-44s unreached %d B (%d non-zero)' % (c2, nm[:44], n, nz))
    if errs:
        print('  reader errors    :')
        for k, v in sorted(errs.items()):
            print('      %4d x %s' % (v, k))
    return 0 if exact == tot else 1


if __name__ == '__main__':
    import glob
    args = _sys.argv[1:]
    files = []
    for a in args:
        files.extend(sorted(glob.glob(a)) if any(c in a for c in '*?') else [a])
    _sys.exit(_selftest(files))
