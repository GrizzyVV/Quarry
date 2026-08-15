"""pgdict_write - THE SHARED pgDictionary SHELL, and the byte-accounting image every writer in
this group builds on.

    inflated system segment -> value model -> written back -> MUST reproduce the original bytes

WHY THIS MODULE EXISTS RATHER THAN A FOURTH COPY OF THE SHELL. `.yed` (242), `.yld` (61),
`.yfd` (4) and `.ybd` (4) are 311 files that share ONE container structure - `yld2xml`'s own
header says "same as yed/yfd" - and `.ytd`/`.ydd` share it again. Copying it four times would
make the shell four claims instead of one, and a defect in it would then have to be found four
times. The shell is proven ONCE here and measured on all four lanes at population.

=============================================================================================
⭐⭐ THE THING THIS MODULE IS REALLY FOR: AN IMAGE THAT CAN BE BYTE-ACCOUNTED, AND A MODEL A
CONTROL CAN CORRUPT.

THE LAW (Matt, 2026-08-14): A CLAIMED REGION IS EVIDENCE ONLY IF A WRONG CLAIM COULD HAVE BEEN
REJECTED. The comparison image copies the ORIGINAL bytes at whatever offsets a writer claims, so
`img[off:off+n] = src[off:off+n]` round-trips PERFECTLY no matter how wrong `off` and `n` are.
Byte identity cannot see it. The `.ymt` lane round-tripped 2,326/2,326 with 11.66% of its bytes
carried verbatim, 12,400 of them non-zero, and that 100% was worth nothing.

SO EVERY READ IS A CLAIM, AND EVERY CLAIM IS TYPED. `Model.rd()` decodes a value with `struct`
and records the SAME format string as the claim - there is no path in this module that copies a
byte range it did not decode. The image is then packed from the decoded VALUES, not from the
source buffer. Two consequences, and both are the point:

  1. BYTE ACCOUNTING IS EXACT AND FALSIFIABLE, because the categories come from the claim list
     rather than from a narrative. `accounting()` returns
        VALUE   - packed back from a decoded scalar (`struct.pack`), never memcpy'd
        DERIVED - COMPUTED from something other than the bytes it overwrites (the page count)
        CARRIED - a verbatim byte copy. This module can express one (`carry()`), it names every
                  caller that uses one, and the three writers built on it use ZERO.
        ZERO    - never claimed. Stays zero, and is reported split by whether the ORIGINAL byte
                  was zero (padding we did not have to understand) or NON-ZERO (data we drop).
     `accounting()` also REFUSES on overlapping claims: two claims on one byte would make the
     totals add up to more than the file and silently inflate the VALUE share.

  2. A MUST-FAIL CONTROL IS GENERIC. `mutate(i)` perturbs decoded value #i and re-packs; if the
     image does not move, claim #i is a copy and not a model. `tools/pgdict_control.py` runs it
     over every claim of every file and reports the CATCH RATE. A control that never fires proves
     nothing - so it is reported as a rate with its denominator, never as "passed".
=============================================================================================

THE SHELL (measured 2026-08-15 over ALL 308 distinct payloads in the group - 241 yed + 59 yld +
4 yfd + 4 ybd - `scratchpad/probe_shell.py`; every figure below is 308/308 unless stated):
    sys+0x00  u64 vtable                                   (non-zero in 308/308)
    sys+0x08  u32 tagged ptr -> BLOCK MAP                  (tag 5 in 308/308)
    sys+0x0C  u32 zero        sys+0x10/0x14 u32 zero
    sys+0x18  u32 usageCount  sys+0x1C u32 zero
    sys+0x20  u32 tagged ptr -> Hashes (u32 joaat per item, ascending)
    sys+0x24  u32 zero (high half of the 64-bit pointer)
    sys+0x28  u16 count | sys+0x2A u16 capacity
    sys+0x2C  u32 zero
    sys+0x30  u32 tagged ptr -> Data (stride-8 tagged pointers, one per item)
    sys+0x34  u32 zero
    sys+0x38  u16 count | sys+0x3A u16 capacity
    sys+0x3C  u32 zero
  count == capacity on all four fields in 308/308 (max count 132, a `.yed`).

⛔ Δ 2026-08-15 - A READER DOCSTRING IN THIS GROUP IS WRONG AND IS CORRECTED HERE, NOT PATCHED
OVER. `yed2xml.py`'s container map calls sys+0x08 "u32 tagged ptr (parent dict; unused)".
It is the BLOCK MAP pointer, the same slot `ynd_write`, `ytd_write`, `ybn_write._pagemap` and
`yvr_write` all name - and the proof is a test that could have refused: the u32 at blockmap+8
equals `page_count(sysFlags) | page_count(gfxFlags) << 8` in **308 of 308** files across all four
extensions. A "parent dictionary pointer" has no reason to hold the resource's own page plan.
(The reader is not edited: it never follows the slot, so its output is unaffected and this module
is the place the correction is load-bearing.)

THE BLOCK MAP (same measurement, 308/308):
    +0x00 u32 zero   +0x04 u32 zero
    +0x08 u32 = page_count(sys) | page_count(gfx) << 8      <- DERIVED, never carried
    +0x0C u32 zero
    +0x10 .. one 8-byte record per page - and EVERY ONE OF THEM IS ZERO in 308/308
             (pages range 1..12; 1,124 records in total across the group)
⭐ SO THE RECORDS ARE DELIBERATELY NOT CLAIMED. They are zero, a zero-filled image reproduces
them for free, and claiming them would buy 8,992 bytes of "coverage" that no wrong claim could
ever have been rejected on. THE ZERO-FILL COLUMN IS WHERE THEY BELONG and the accounting says so.
⭐ THE PAGE-COUNT WORD IS THE OPPOSITE CASE and `ybn_write` paid for the lesson: it is the ONE
non-zero byte in that whole allocation, so a writer that stamps it can hide the fact that nothing
ever visited the block map. Here it is DERIVED (computed from the RSC7 flags) and it is the only
DERIVED region in the group - 4 bytes per file, disclosed on its own line.

ASCII output only.
"""
import os
import struct
import sys as _sys

_sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ydr2xml import Res  # noqa: E402
import meta_write        # noqa: E402  (page_count - the COMPUTED page record)

SHELL = 0x40
VALUE, DERIVED, CARRIED = 'value', 'derived', 'carried'

# ⛔⛔ FLOATS ARE CLAIMED AS THEIR IEEE-754 BIT PATTERN, AND THIS IS A CORRECTNESS FIX, NOT A
# DODGE. `struct.unpack('<f')` widens to a Python double and `pack` narrows back, and that round
# trip is NOT the identity for a SIGNALLING NaN: the quiet bit is set on the way through. GTA V
# uses signalling NaN as a padding value - `.yld` stores 0x7F800001 in the 4th lane of every
# composite AABB - so a `<f` field map re-encoded 0x7F800001 as 0x7FC00001 and MISSED A BYTE IN
# EVERY FILE. Measured on `.yld` before the fix: 307 bytes across 3 field kinds
# (`vertices_elem` 234, `composite_transform` 52, `arr10_elem` 21) on the first file alone.
# ⭐ THE VALUE IS STILL DECODED AND STILL RE-ENCODED - as a u32, which is exactly what a C++ port
# does with a float member (`QUARRY IS C++; the .py is the PROTOTYPE layer`). The SEMANTIC claim
# lives in the field NAME (`..._f32`), where it can be read, rather than in a struct code that
# silently corrupts one value class.
# ⚠ USE `<f` ONLY where a NaN cannot occur, and prefer these everywhere else. `.yed` round-trips
# 241/241 either way - it holds no signalling NaN - so this is a robustness change there and a
# correctness change in `.yld`.
F32, F32x2, F32x3, F32x4 = '<I', '<2I', '<3I', '<4I'

# ⭐ THE SHELL FIELD MAP, and it TILES 0x00..0x40 with no hole and no overlap - `_check_tiling`
# refuses at import if it ever stops doing so. That is what makes "the shell is modelled" a
# statement byte identity can test: a byte inside the shell that no field covers would stay zero.
SHELL_FIELDS = (
    (0x00, '<Q', 'vtable'),
    (0x08, '<I', 'blockmap_ptr'),
    (0x0C, '<I', 'pad0C'),
    (0x10, '<I', 'pad10'),
    (0x14, '<I', 'pad14'),
    (0x18, '<I', 'usage_count'),
    (0x1C, '<I', 'pad1C'),
    (0x20, '<I', 'hashes_ptr'),
    (0x24, '<I', 'hashes_ptr_hi'),
    (0x28, '<H', 'hashes_count'),
    (0x2A, '<H', 'hashes_capacity'),
    (0x2C, '<I', 'pad2C'),
    (0x30, '<I', 'data_ptr'),
    (0x34, '<I', 'data_ptr_hi'),
    (0x38, '<H', 'data_count'),
    (0x3A, '<H', 'data_capacity'),
    (0x3C, '<I', 'pad3C'),
)


def check_tiling(fields, span, what):
    """⛔ AN UNTILED FIELD MAP IS A SILENT CARRY. Lifted verbatim in spirit from `yvr_write`,
    where it is what makes byte identity prove the FIELD MAP is complete rather than that a
    buffer was copied. Run at IMPORT so the claim is refuted here, not later as mystery coverage.

    `fields` entries are (offset, struct-code[, name]); the name is ignored."""
    at = 0
    for f in fields:
        off, code = f[0], f[1]
        if off != at:
            raise ValueError('%s field map: hole/overlap at 0x%02x (expected 0x%02x)'
                             % (what, off, at))
        at += struct.calcsize(code)
    if at != span:
        raise ValueError('%s field map covers %d of %d bytes' % (what, at, span))


check_tiling(SHELL_FIELDS, SHELL, 'pgDictionary shell')


def tile(named, span, what):
    """Build a TILED field map from a SPARSE one: {offset: (struct-code, name)} + the record span
    -> the full tuple `rd_fields` wants, with every gap filled by unnamed u32/u8 words.

    ⭐ WHY THE GAPS ARE FILLED RATHER THAN SKIPPED, and why the filler is UNNAMED. A record whose
    named fields cover 60 of its 240 bytes is not 25% understood and 75% unknown - it is a record
    with 180 bytes nobody has looked at, and a writer that skips them leaves them ZERO, which the
    round-trip then reports as residual. Filling them with word claims makes the round-trip
    measure the SPAN (which is pinned by the allocation) instead of the naming.
    ⛔ AND THE ACCOUNTING KEEPS THE TWO APART. A filled word carries no name, so it lands in
    `value_words`, never in `value_named`. Both are "re-encoded from a decoded value" and only
    one of them is evidence that we know what the bytes ARE. Quoting a single VALUE percentage
    over a record that is mostly filler would be the same overstatement as quoting a coverage
    figure over a carried region.
    """
    out, at = [], 0
    for off in sorted(named):
        code, name = named[off]
        if off < at:
            raise ValueError('%s: sparse map overlaps at 0x%x' % (what, off))
        while at + 4 <= off:
            out.append((at, '<I', None))
            at += 4
        while at < off:
            out.append((at, '<B', None))
            at += 1
        out.append((off, code, name))
        at = off + struct.calcsize(code)
    while at + 4 <= span:
        out.append((at, '<I', None))
        at += 4
    while at < span:
        out.append((at, '<B', None))
        at += 1
    check_tiling(out, span, what)
    return tuple(out)


class ModelError(ValueError):
    """The model could not be built from the file. Raised, never worked around: a count read out
    of a short buffer produces a garbage model that then gets reported as a format finding."""


class Model:
    """A zero-filled image of one inflated system segment, built ONLY from typed claims.

    THE ONE IDIOM: `rd(off, code)` decodes AND claims in the same call, so there is no way to
    reproduce a byte this model never read. Everything else here is bookkeeping for the
    accounting and for the must-fail control.
    """

    def __init__(self, res, flags=(0, 0), version=None, what='pgdict'):
        if version is not None and res.version != version:
            raise ModelError('%s expects RSC7 version %d, got %d' % (what, version, res.version))
        if len(res.gfx):
            # NO SILENT DEFAULTS: the whole group is system-segment-only (308/308 measured). A
            # file that broke that would be silently half-measured if this were a warning.
            raise ModelError('%s carries no graphics segment; got %d bytes' % (what, len(res.gfx)))
        self.res = res
        self.what = what
        self.sys_flags, self.gfx_flags = flags
        self.size = len(res.sys)
        self.claims = []          # (off, code, values, kind, tag)
        self._named = 0           # VALUE bytes whose claim carries a semantic field name
        self._seen = set()        # structure offsets already walked (cycle guard)
        self._cov = bytearray(self.size)   # 1 where a claim already owns the byte

    # ------------------------------------------------------------------ reading == claiming
    def rd(self, off, code, tag=None):
        """Decode `code` at `off` and CLAIM those bytes as VALUE. Returns the values tuple.

        ⛔ There is deliberately no `read without claiming` and no `claim without reading`."""
        n = struct.calcsize(code)
        if off < 0 or off + n > self.size:
            raise ModelError('%s: read %s at 0x%x runs past the %d B segment'
                             % (self.what, code, off, self.size))
        if any(self._cov[off:off + n]):
            # ⛔ THE OVERLAP IS CAUGHT AT THE CLAIM, NOT AT THE TOTAL. Two claims on one byte make
            # the byte account add to more than the file, and - worse - the second claim looks
            # like coverage it did not earn. Raising HERE names the field that collided, which is
            # what turns the guard into a lead instead of an arithmetic complaint.
            raise ModelError('%s: claim %r at 0x%x overlaps ground already claimed'
                             % (self.what, tag or code, off))
        vals = struct.unpack_from(code, self.res.sys, off)
        self._cov[off:off + n] = b'\x01' * n
        self.claims.append((off, code, vals, VALUE, tag))
        if tag:
            self._named += n
        return vals

    def covered(self, off, n):
        """True when EVERY byte of the span is already claimed - the test an ALIASED array needs.
        ⛔ Partial coverage is not aliasing, it is a stride or offset error, and the caller must
        let `rd` refuse rather than papering over it."""
        return n > 0 and all(self._cov[off:off + n])

    def rd1(self, off, code, tag=None):
        """`rd` for a single-value code."""
        return self.rd(off, code, tag)[0]

    def rd_fields(self, base, fields, span, what):
        """Decode a TILED field map at `base`. Returns {name: values}. The tiling is checked
        against `span` on the first call for this map, so a record whose named fields do not
        cover its stride cannot quietly pass."""
        key = id(fields)
        if key not in _TILED:
            check_tiling(fields, span, what)
            _TILED.add(key)
        out = {}
        for f in fields:
            off, code = f[0], f[1]
            name = f[2] if len(f) > 2 else None
            v = self.rd(base + off, code, name)
            if name is not None:            # unnamed filler words are claimed, not returned
                out[name] = v[0] if len(v) == 1 else v
        return out

    def rd_array(self, off, code, count, tag=None, stride=None):
        """Decode `count` records of `code`, ONE CLAIM PER RECORD - never one slab. An off-by-one
        in a stride must surface as a difference rather than be absorbed by a bulk copy.

        ⭐ `stride` IS EXPLICIT SO IT CAN BE PERTURBED. It defaults to the record size, which is
        the common case, but taking it as a parameter is what lets a caller keep the spacing in a
        NAMED CONSTANT that `tools/pgdict_control.py` can patch. That control found the reason:
        when the stride was implied by the struct code, mutating the caller's `WEIGHT_STRIDE`
        changed nothing and the control honestly reported `0 / 4 files broke` - a stride nothing
        can perturb is a stride nobody measured.
        ⛔ A stride SMALLER than the record would make consecutive claims overlap, and `rd`
        refuses on overlap - so a wrong stride surfaces as a refusal, not as coverage."""
        if stride is None:
            stride = struct.calcsize(code)
        return [self.rd(off + i * stride, code, tag) for i in range(count)]

    def deref(self, tagged, need=0):
        """Tagged pointer -> absolute system-segment offset, or None. GRAPHICS pointers refuse:
        this group has no graphics segment, so one would mean the model is misreading."""
        buf, o = self.res.deref(tagged, need)
        if buf is None:
            return None
        if buf is not self.res.sys:
            raise ModelError('%s: pointer 0x%08x resolves outside the system segment' %
                             (self.what, tagged))
        return o

    def cstr(self, off, limit=256, tag='string'):
        """Claim a NUL-TERMINATED string INCLUDING its terminator, and no further.

        ⛔ Claiming a fixed span here would take whatever follows the string, which on a packed
        string table is the NEXT name - the fill-to-the-next-region failure in miniature."""
        s = self.res.sys
        end = s.find(b'\x00', off, min(off + limit, self.size))
        if end < 0:
            raise ModelError('%s: unterminated string at 0x%x' % (self.what, off))
        return self.rd(off, '<%ds' % (end - off + 1), tag)[0][:-1]

    def carry(self, off, n, why):
        """⛔ A VERBATIM BYTE COPY. The ONLY claim in this module a wrong offset could not be
        rejected on, so it takes a REASON and is reported on its own line of the accounting.
        The three writers built on this module call it ZERO times; it exists so that a future
        one which must carry something has to say so out loud rather than reaching for a slice."""
        if n <= 0:
            return b''
        raw = bytes(self.res.sys[off:off + n])
        self.claims.append((off, '<%ds' % n, (raw,), CARRIED, why))
        return raw

    # ------------------------------------------------------------------ the shell
    def read_shell(self):
        """Decode sys+0x00..0x40 and the item pointer/hash arrays. Returns [item offsets].

        ⭐ WHY THE COUNT AND THE POINTERS ARE PINNED EVEN THOUGH THEY LOOK LIKE CARRIED HEADER
        BYTES: they DRIVE the walk. A wrong `data_count` writes the wrong number of records; a
        wrong `data_ptr` writes every item pointer at the wrong offset and leaves the right ones
        zero. Either way the round-trip REJECTS it. That is the difference between this and a
        header slice, and it is the whole reason the shell is decoded rather than copied.
        """
        h = self.rd_fields(0, SHELL_FIELDS, SHELL, 'pgDictionary shell')
        cnt = h['data_count']
        if h['hashes_count'] != cnt:
            raise ModelError('%s: hash count %d != data count %d'
                             % (self.what, h['hashes_count'], cnt))
        self.shell = h
        if not cnt:
            return []                       # an empty dictionary is ordinary, not a failure
        hp = self.deref(h['hashes_ptr'], cnt * 4)
        dp = self.deref(h['data_ptr'], cnt * 8)
        if hp is None or dp is None:
            raise ModelError('%s: hash/data array for %d items does not fit the segment'
                             % (self.what, cnt))
        self.hashes = [v[0] for v in self.rd_array(hp, '<I', cnt, 'item_hash')]
        self.item_ptrs = [v[0] for v in self.rd_array(dp, '<Q', cnt, 'item_ptr')]
        offs = []
        for p in self.item_ptrs:
            o = self.deref(p & 0xFFFFFFFF, 1)
            if o is None:
                raise ModelError('%s: item pointer 0x%x does not resolve' % (self.what, p))
            offs.append(o)
        return offs

    def once(self, off):
        """True the first time a structure offset is walked. A malformed graph must terminate on
        evidence rather than recurse forever, and a structure claimed twice would break the
        no-overlap rule the accounting depends on."""
        if off in self._seen:
            return False
        self._seen.add(off)
        return True

    # ------------------------------------------------------------------ image + measure
    def write(self):
        img = bytearray(self.size)
        for off, code, vals, kind, _tag in self.claims:
            struct.pack_into(code, img, off, *vals)
        self._stamp_pagecount(img)
        return bytes(img)

    def _stamp_pagecount(self, img):
        """⭐ THE PAGE-COUNT RECORD, COMPUTED - never carried.

        `ptr@0x08` reaches the block map; its u32 at +8 is
            page_count(system) | page_count(graphics) << 8
        The law was already in-tree three times (`meta_write` 250/250, `ynd_write` 259/259,
        `yvr_write` + `ywr_write` 9,145/9,145) and it holds unchanged across this whole group -
        308 of 308 files, all four extensions, measured BEFORE any writer existed.
        Recomputing rather than copying is what makes it meaningful: a carried value would
        round-trip even if we had no idea what it meant.
        ⛔ AND IT IS THE ONLY THING WRITTEN INTO THE BLOCK MAP. `ybn_write` learned the hard way
        that stamping this word can stand in for an allocation nothing ever visited - so the
        page-record body is left ZERO here, which is what the file actually holds (1,124 records
        across the group, every one zero), and the accounting counts it as zero-fill rather than
        as coverage."""
        o = self.deref(self.res.ptr(0x08), 12)
        if o is None:
            return                          # leave it zero: an unreproduced byte stays VISIBLE
        val = ((meta_write.page_count(self.sys_flags) & 0xFF)
               | ((meta_write.page_count(self.gfx_flags) & 0xFF) << 8))
        struct.pack_into('<I', img, o + 8, val)
        self._derived = (o + 8, 4)

    def unreached(self):
        """(count, non_zero_count) of bytes the model never reproduced."""
        got, orig = self.write(), self.res.sys
        n = min(len(got), len(orig))
        bad = [i for i in range(n) if got[i] != orig[i]]
        return len(bad), sum(1 for i in bad if orig[i] != 0)

    def residual_runs(self, limit=12):
        """Contiguous runs of unreproduced bytes, as (offset, length, nonzero) - the development
        loop for this whole group. A residual reported as a total is a number; reported as runs
        at offsets it is a lead."""
        got, orig = self.write(), self.res.sys
        runs, start = [], None
        for i in range(min(len(got), len(orig))):
            if got[i] != orig[i]:
                if start is None:
                    start = i
            elif start is not None:
                runs.append((start, i - start, sum(1 for k in range(start, i) if orig[k])))
                start = None
        if start is not None:
            n = min(len(got), len(orig))
            runs.append((start, n - start, sum(1 for k in range(start, n) if orig[k])))
        runs.sort(key=lambda r: -r[1])
        return runs[:limit]

    def accounting(self):
        """⭐ THE BYTE ACCOUNT. Returns a dict; every byte of the segment lands in exactly one
        column and the columns sum to `size` - checked, not asserted.

            value_named   - VALUE bytes claimed through a NAMED field (semantic map)
            value_words   - VALUE bytes claimed as untyped words/records (a tiling, not a name)
            derived       - COMPUTED, not read from the bytes it overwrites
            carried       - VERBATIM byte copies (see `carry`)
            zero_pad      - never claimed, and the ORIGINAL byte is zero
            zero_residual - never claimed, and the ORIGINAL byte is NON-ZERO  <- the finding

        ⛔ REFUSES ON OVERLAP. Two claims on one byte would make the columns add to more than the
        file and inflate the VALUE share - which is exactly the kind of quiet arithmetic this
        campaign keeps finding. `value_named` vs `value_words` is split because "re-encoded from
        a decoded value" is true of both and they are not equally strong evidence: a u32 read and
        written back proves the bytes were reached, a NAMED field proves we know what they are.
        """
        cov = bytearray(self.size)          # 0 unclaimed, 1 value-named, 2 value-words,
        for off, code, _v, kind, tag in self.claims:   # 3 derived, 4 carried
            n = struct.calcsize(code)
            mark = 4 if kind == CARRIED else (1 if tag else 2)
            for i in range(off, min(off + n, self.size)):
                if cov[i]:
                    raise ModelError('%s: claims overlap at 0x%x (a byte claimed twice makes '
                                     'the accounting add up to more than the file)'
                                     % (self.what, i))
                cov[i] = mark
        d = getattr(self, '_derived', None)
        if d is None:
            self.write()
            d = getattr(self, '_derived', None)
        if d:
            for i in range(d[0], min(d[0] + d[1], self.size)):
                if cov[i]:
                    raise ModelError('%s: the page-count word at 0x%x is also claimed as data'
                                     % (self.what, i))
                cov[i] = 3
        orig = self.res.sys
        out = {'size': self.size, 'value_named': 0, 'value_words': 0, 'derived': 0,
               'carried': 0, 'zero_pad': 0, 'zero_residual': 0}
        key = {1: 'value_named', 2: 'value_words', 3: 'derived', 4: 'carried'}
        for i in range(self.size):
            c = cov[i]
            if c:
                out[key[c]] += 1
            elif orig[i]:
                out['zero_residual'] += 1
            else:
                out['zero_pad'] += 1
        tot = sum(out[k] for k in key.values()) + out['zero_pad'] + out['zero_residual']
        if tot != self.size:
            raise ModelError('%s: byte account sums to %d, not %d' % (self.what, tot, self.size))
        return out

    # ------------------------------------------------------------------ the must-fail control
    def mutate_count(self):
        """How many claims a control can perturb."""
        return len(self.claims)

    def mutate(self, i):
        """⭐⭐ THE MUST-FAIL CONTROL. Perturb decoded value #i, re-pack, return the image.

        Byte identity cannot tell a pinned claim from a copied one, so the only way to show the
        model is load-bearing is to CORRUPT IT AND DEMAND THE IMAGE MOVE. If a mutated image is
        still byte-identical to the original, claim #i reproduces bytes it did not have to
        understand - and the caller reports that as a MISS, with its denominator.

        Perturbation is deterministic, so a re-run grades the same claims the same way, and it is
        done AT THE ENCODING rather than on the Python value:

        ⛔⛔ THE FIRST VERSION ADDED 1.0 TO FLOATS AND SCORED 1,256 MISSES ON `.yed`, EVERY ONE OF
        THEM A `blend_plane`. They were not misses - they were the CONTROL failing, not the model:
        in float32 a value above 2^24 absorbs `+1.0` exactly, so the "corrupted" model re-encoded
        to the identical bytes and the image could not move. A control that reports a defect it
        manufactured is worse than no control, so the perturbation now flips BITS of the encoded
        field and REQUIRES that the flip survives a decode/encode round trip; a field where no
        flip survives returns None and is counted as SKIPPED, never as a miss.
        """
        off, code, vals, kind, tag = self.claims[i]
        try:
            base = struct.pack(code, *vals)
        except struct.error:
            return None
        new = None
        for bit in (0x01, 0x80, 0xFF):
            for pos in range(len(base)):
                cand = bytearray(base)
                cand[pos] ^= bit
                try:
                    dec = struct.unpack(code, bytes(cand))
                    if struct.pack(code, *dec) != base:
                        new = dec
                        break
                except struct.error:
                    continue
            if new is not None:
                break
        if new is None:
            return None
        img = bytearray(self.size)
        for k, (o2, c2, v2, _k2, _t2) in enumerate(self.claims):
            try:
                struct.pack_into(c2, img, o2, *(new if k == i else v2))
            except struct.error:
                return None
        self._stamp_pagecount(img)
        return bytes(img)


_TILED = set()


def read(src, cls, version=None):
    """bytes | path -> model. The RSC7 segment FLAGS are needed to recompute the page-count
    record and `Res` does not keep them, so they are parsed from the container header here."""
    blob = bytes(src) if isinstance(src, (bytes, bytearray)) else open(src, 'rb').read()
    if len(blob) < 16 or blob[:4] != b'RSC7':
        raise ModelError('not an RSC7 container')
    _magic, _ver, sysf, gfxf = struct.unpack_from('<4sIII', blob, 0)
    m = cls(Res.from_bytes(blob), (sysf, gfxf))
    # ⭐ THE CONTAINER BYTES ARE KEPT so the STRIDE CONTROL (`tools/pgdict_control.py`) can re-read
    # the very same file under a mutated span constant. Re-harvesting from the archive instead
    # would let a walk-order difference masquerade as a control result.
    m.res_blob = blob
    return m
