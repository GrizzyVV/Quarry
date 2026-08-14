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
              per-child AABB @+0x88 (n*32) · **BVH block @+0xA8** · header is 0xB0 bytes
  geometry:   nverts @+0xD0 · npolys @+0xD4 · nmat u8 @+0x120 · nmatcol u8 @+0x121
              vertices @+0xB0 (nverts*6) · polygons @+0x88 (npolys*16)
              materials @+0xF0 (nmat*8) · poly materials @+0x118 (npolys*1)
              **vertex colours @+0xB8 (nverts*4)** · **material colours @+0xF8 (nmatcol*4)**
              **BVH block @+0x130** · header is 0x150 bytes (u16 sentinel 0xFFFF at +0x140)
  BVH block:  0x80 bytes, self-validating - nodes @+0x00 sized by **capacity** @+0x0C,
              trees @+0x70 sized by capacity @+0x7A, both 16-B records. See `_bvh`.
⭐ The BVH block is ONE structure reached from TWO slots (+0x130 on geometry, +0xA8 on composite),
and it was the last whole structure missing from this lane.
⭐ AND THE BOUND TYPE IS THE DISCRIMINATOR (+0x10), not a plausibility test on the counts - see
`_bound`. A composite whose header bytes happened to look like counts was walked as a geometry
bound, which cost that root its AABB array and its BVH in silence.

⭐⭐ `ma@` WAS A DEFECT SIGNATURE, NOT A VARIANT. The 25 worst files in the population were all
`ma@*` composite map collision, clustered at 85-88%, and that looked like a variant worth naming.
**Zero `ma@`-specific code was written.** At population `ma@` is now the BEST-performing prefix -
992 of 1,025 byte-exact (96.8%) vs 94.9% unprefixed and 92.2% `hi@`, mean 99.9993% - because the
composites are simply where the missing composite BVH and the mis-discriminated type both bit
hardest. ⛔ A worst-list that shares a name is a lead about WHERE a defect lands, never evidence
that the format has a special case.
COVERAGE 2026-08-14, second pass. Reproduce:
`python tools/roundtrip_coverage.py --lane ybn --limit 147`      (the lane sample)
`python tools/roundtrip_population_all.py --run --lanes ybn --out <dir>` then `--report` (all of it)
                                 was                      now
    lane sample, 147 files       99.4653%  19/147     **100.0000%  147/147 byte-exact**
    POPULATION, all 15,139       98.2798%  589 (3.89%) **99.9987%  14,255 (94.16%)**, 0 errors
    population min               85.2824%              **99.3774%**
    population bytes unreached   64,511,592            **44,356** of 3,795,976,192 (99.9988%)
⚠ Δ IS NOT ALL GAIN. See BLIND FILL below: a third of a percentage point of the old sample number,
and **every one of its 19 byte-exact files**, rested on an unpinned claim. Removing it and pinning
nothing else reads **99.1327% / 0-of-147** - that is the honest baseline this pass started from.

⛔⛔ THE SECOND SAMPLE EXISTS BECAUSE THE FIRST ONE COULD NOT SEE THE LANE. `roundtrip_coverage`
draws `.ybn` from x64c/x64a/x64d, and **every one of the population's 25 worst files lives in
x64i/j/k/l/m** (the `_citye`/`_cityw` map packs). The sanctioned sample read 99.4653% while the
population read 98.2798%, and the whole 85-88% tail - the composite map-collision files - was
invisible to it. The adversarial sample is rebuilt from the population grade by
`scratchpad/ybn_hard_cache.py` (worst 60 + a seeded random control, so a fix cannot be tuned to
the worst files alone). ⭐ A LANE'S ARCHIVE LIST IS PART OF ITS SAMPLE DESIGN.

⭐⭐ TWO STRUCTURES PORTED FROM THE DRAWABLE LANE PROVED **ABSENT** HERE, and the negative result
is the finding - a lane's bounds are not the same animal as a drawable's embedded bounds.
Measured over 697 bounds in the 147-file sample (scratchpad probes, sizes printed):
    +0x78 second vertex array : live on 147 bounds - EXACTLY the 147 composite ROOTS, where it
                                is the child-transform array and was already read. NULL on all
                                550 geometry bounds. Expected to "matter far more for .ybn" than
                                for .ydr; measured worth **ZERO bytes**, coverage identical to 4dp.
    +0xC0/+0xC8 octant map    : live on the 147 roots, NULL on all 550 geometry bounds, and the
                                self-validating law never fires - so nothing is claimed.
⇒ Standalone map collision carries neither; both belong to bounds embedded under a drawable or a
fragment. Both are still implemented here, because when the law does not hold they cost nothing.

⛔⛔ THE BLIND FILL, and it is the lesson of this pass. `+0x130` was read as "an array descriptor
whose records sit INLINE at +0x20", so the writer claimed `count * 16` bytes starting there. It is
refuted: `+0x20` is a BOUNDING BOX (see `_bvh`), and the descriptor's own pointer equals `+0x20`
in **0 of 853** blocks. Over the two samples that claim covered **5,563,920 bytes of which only
47,136 (0x60 per block) were inside the structure it was reading** - 99.2% of it claimed on no
basis whatever. ⭐ It could not fail: the comparison image is built by copying the ORIGINAL bytes
at whatever offsets are claimed, so **an unpinned claim always "matches"**. It also hid a real
gap - the material-colour arrays read as already-covered underneath it.
⇒ **A region claimed without a count derived from the file is indistinguishable from
understanding, and reads as success.** Every capture in this file is now either count-derived or
law-guarded, and the header span is measured per type rather than being generous.

REMAINING GAP - **ONE CAUSE, and it is the whole of it.** At population: 884 of 15,139 files,
44,356 bytes, median 34 B per affected file, max 952. Split byte-by-byte over the **34 worst
files of the post-fix population grade** (`scratchpad/ybn_hard3`, every one of which still has a
mismatch, so the sample is the residual itself): **94.7% polygon-array tail, 5.3% poly-material
tail, 0.0% anything else.** Every run is 1-10 extra 16-byte polygon records sitting immediately
past the end of a polygon array, with the matching per-polygon material bytes after theirs.
  * they are REAL triangles of that mesh - valid float + three vertex indices inside `nverts`,
    continuing the index sequence of the last counted polygon;
  * the poly-material array is longer by the same record count, which is the file's own
    cross-check: one material byte per polygon;
  * the BVH does NOT reference them: `max(itemId + itemCount)` over the leaves is **4849 on a
    bound whose npolys is 4849**, so the BVH covers exactly the counted polygons;
  * ⛔ **no scalar sizes them.** Every u8/u16/u32 in the 0x150-byte header and in the 0x80-byte
    BVH block was tested against `npolys + surplus` on all 7 - **none matches on all 7, and none
    matches on more than 1.** The totals share no modulus (1051 is odd, 4436 even), so it is not
    alignment either.
  * BEST-EVIDENCED HYPOTHESIS: allocated-but-uncounted trailing slots - the same
    capacity-exceeds-count pattern the BVH node array has, but with no capacity field located.
  * ⛔ **NOT CLOSED BY FILLING** to the next region, which would read 100% and understand nothing.

⚠ Same scope as the other writers: inflated SYSTEM SEGMENT only; the page-count record at
`ptr@0x08 +8` is COMPUTED (the law from `meta_write`, confirmed on ynd and ynv).
ASCII output only.
"""
import os
import struct
import sys as _sys

_sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ydr2xml import Res  # noqa: E402

# ⛔ WAS 0x130 - which stopped EXACTLY at the slot that matters. Measured 2026-08-13 over 40
# files: a pointer at bound+0x130 lands on the START of an unreached run in 132 bounds, by far
# the dominant hit, and the writer could not even see the slot.
#
# ⭐ Δ 2026-08-14 - THE SPAN IS NOW MEASURED PER TYPE, and the generous 0x180 is retired.
# A header span is a BLIND CLAIM: the comparison image copies the original bytes at whatever
# offsets are claimed, so an over-wide span always "matches" and quietly pays for structures
# nobody decoded. Swept over both samples (147-file lane sample + 121 population-worst),
# `scratchpad/ybn_span_sweep.py`:
#     span   147-sample            hard sample
#     0x140  0/147  99.99101%      0/121  99.99182%
#     0x150  147/147 100.00000%    114/121 99.99899%
#     0x180  147/147 100.00000%    114/121 99.99899%     <- 33,552 more bytes claimed, 0 gained
# ⇒ the result SATURATES at 0x150 and the extra 0x30 bought nothing. What the last step buys is
# exactly two bytes: `+0x140` is a u16 sentinel reading **65535 on all 853 geometry bounds**
# (never a count - it equals neither nverts nor npolys anywhere), and `+0x142..+0x14F` is zero on
# all 853. The 0x150 figure is corroborated independently by the LAYOUT: consecutive geometry
# bound headers sit exactly 0x150 apart.
# ⭐ A COMPOSITE IS A DIFFERENT SIZE, and the file says so: its last field is the BVH pointer at
# +0xA8, and in 5 of the 7 files whose layout was mapped by hand the very next object - a polygon
# array - begins at **0x0000B0**, immediately after the root composite at offset 0.
# ⚠ Only types 10 and 8 occur in this lane (268 and 853 in the measured 268 files). Any other
# type falls back to the largest MEASURED span rather than to a bigger guess, and that fallback is
# a statement about the sample, not about the format.
BOUND_SPAN = 0x150                       # fallback / largest measured
BOUND_SPAN_BY_TYPE = {10: 0x0B0, 4: 0x150, 8: 0x150}


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

    def _octant_map(self, off, n=8):
        """phBound +0xC0 / +0xC8 - THE OCTANT MAP, SELF-DESCRIBING.

            +0xC0 -> u32 counts[8] · +0xC8 -> u64 ptr table[8] -> u32 index array of counts[k]

        DERIVED IN `ydr_write._octant_map` (see there for the evidence: the entry pointers were
        found at +0xC0/+0xC8 of a 0x180-byte bound header on every drawable that still had a gap,
        and a search over N = 2..32 matched ONLY N = 8). Mirrored here because these two walkers
        are deliberately the same phBound offsets - if one changes, change both.
        ⭐ THE ARITHMETIC IS CHECKED BEFORE ANYTHING IS CLAIMED: `ptr[k+1] - ptr[k] ==
        counts[k] * 4` for all k, and the payload begins immediately after the table. When the law
        fails NOTHING is captured, so a misread costs coverage instead of inventing it.
        """
        s = self.res.sys
        try:
            cp = struct.unpack_from('<I', s, off + 0xC0)[0]
            tp = struct.unpack_from('<I', s, off + 0xC8)[0]
        except struct.error:
            return
        if not cp or not tp:
            return
        cb, tb = self._off(cp), self._off(tp)
        if cb is None or tb is None:
            return
        if cb + n * 4 > self.size or tb + n * 8 > self.size:
            return
        try:
            counts = [struct.unpack_from('<I', s, cb + k * 4)[0] for k in range(n)]
            ptrs = [struct.unpack_from('<I', s, tb + k * 8)[0] for k in range(n)]
        except struct.error:
            return
        if any((p >> 28) != 5 for p in ptrs) or any(c > 0x100000 for c in counts):
            return
        offs = [p & 0x0FFFFFFF for p in ptrs]
        if offs[0] != tb + n * 8:
            return
        if any(offs[k + 1] - offs[k] != counts[k] * 4 for k in range(n - 1)):
            return
        if offs[-1] + counts[-1] * 4 > self.size:
            return
        self._flat_at(cb, n * 4)
        self._flat_at(tb, n * 8)
        for k in range(n):
            self._flat_at(offs[k], counts[k] * 4)

    def _bvh(self, off, slot=0x130):
        """A **0x80-byte BVH BLOCK**, and the block is SELF-VALIDATING.

        TWO SLOTS CARRY ONE STRUCTURE (measured 2026-08-14):
            geometry / GeometryBVH bound  +0x130
            COMPOSITE bound               +0x0A8
        ⭐ The composite's BVH is a BVH over its CHILDREN and it was the last whole structure in
        this lane. It is the same block, byte for byte - all four laws below pass on it - so it is
        one reader, not two. Corroborated by the tree arithmetic on the file it was found in: a
        root with 7 children carries **13** nodes, which is 2*7-1, the node count of a binary tree
        over 7 leaves.

            +0x00 u64 ptr -> node array (count 16-B records) | +0x08 u32 count | +0x0C u32 capacity
            +0x10 16 zero bytes
            +0x20 vec4 box min | +0x30 vec4 box max | +0x40 vec4 box centre
            +0x50 vec4 scale inverse | +0x60 vec4 scale
            +0x70 u64 ptr -> tree array | +0x78 u16 count | +0x7A u16 capacity (16-B records)

        ⛔⛔ Δ 2026-08-14 - THIS SLOT WAS PREVIOUSLY READ AS "an array descriptor with its records
        INLINE at +0x20", and that reading is REFUTED, not refined. `+0x20` is the BOUNDING BOX,
        so `capture(desc+0x20, count*16)` was claiming up to 51,696 bytes of ground it had not
        decoded - a BLIND FILL. It could never show up as a failure, because the comparison image
        is built by copying the original bytes at whatever offsets are claimed, so **an unpinned
        claim always "matches"**. It inflated this lane's headline number and it swallowed the
        material-colour arrays (they read as already-covered), hiding a real gap underneath a
        fake one. ⭐ The general law, and it is the one this lane cost: **a region claimed without
        a count derived from the file is indistinguishable from understanding, and reads as
        success.**

        HOW THE REPLACEMENT IS PINNED - four laws, each able to refuse, all measured over
        **901 BVH blocks in 268 files** (853 from +0x130 on geometry bounds, 48 from +0xA8 on
        composites; sample = 121 population-worst + the 147-file lane sample):
            L1  +0x10..+0x20 is all zero .................... 901 / 901
            L2  scale[k] * scaleinv[k] == 1 (+-1e-3) ........ 901 / 901   <- pins +0x50/+0x60 as a
                                                                            reciprocal PAIR, which
                                                                            no bounding-box reading
                                                                            can produce by accident
            L3  (max-min)[k] * scaleinv[k] == 65535 (+-1%) .. 901 / 901   <- pins +0x20/+0x30 as the
                                                                            box AND states the 16-bit
                                                                            quantisation the node
                                                                            records are stored in
            L4  tree count == tree capacity ................ 901 / 901
        and the OLD reading was tested head-on in the same pass: the descriptor's own pointer
        equals `desc+0x20` in **0 / 901**. It always points somewhere else entirely.
        ⚠ 220 of the 268 composites carry NO BVH at +0xA8 - it is optional, and the laws are what
        tell the two cases apart rather than a presence flag anybody had to guess.
        ⭐ Self-validating: when a law fails NOTHING is captured, so a misread costs coverage
        instead of inventing it - the same discipline `_octant_map` already uses.
        ⚠ Record size 16 B is the file's own arithmetic, not a fitted stride: on the first three
        blocks dumped, `nodes_end == the next known structure's start` exactly (656 B = 41*16 ends
        at the following bound header; 2,064 B = 129*16 ends at the following tree array).
        """
        s = self.res.sys
        try:
            p = struct.unpack_from('<I', s, off + slot)[0]
        except struct.error:
            return
        if (p >> 28) != 5:
            return
        d = p & 0x0FFFFFFF
        if d + 0x80 > self.size:
            return
        if any(s[d + 0x10:d + 0x20]):                                   # L1
            return
        try:
            bmin = struct.unpack_from('<3f', s, d + 0x20)
            bmax = struct.unpack_from('<3f', s, d + 0x30)
            sinv = struct.unpack_from('<3f', s, d + 0x50)
            scl = struct.unpack_from('<3f', s, d + 0x60)
            cnt, cap = struct.unpack_from('<II', s, d + 0x08)
            tcnt, tcap = struct.unpack_from('<HH', s, d + 0x78)
        except struct.error:
            return
        if not all(abs(scl[k] * sinv[k] - 1.0) < 1e-3 for k in range(3)):        # L2
            return
        if not all(abs((bmax[k] - bmin[k]) * sinv[k] - 65535.0) < 655.35         # L3
                   for k in range(3)):
            return
        if tcnt != tcap:                                                          # L4
            return
        self._flat_at(d, 0x80)
        # ⭐⭐ THE NODE ARRAY IS SIZED BY **CAPACITY**, NOT COUNT - and that is not a guess, the
        # file states it. Found on `prologue01_10.ybn`: the last unclaimed run in the file is
        # EXACTLY 240 bytes and the block reads count 13, capacity 15 -> 15 * 16 = 240, count *
        # 16 = 208. The 2 surplus records carry the classic uninitialised inverted box
        # (`01 80 01 80 01 80 ff 7f ff 7f ff 7f`, i.e. min +32767 / max -32767 per lane), which
        # is what an allocated-but-unused BVH node looks like. ⚠ A count-sized read leaves those
        # records unreached and they are NOT zero, so they count against - which is precisely how
        # the run was found rather than reasoned about.
        # ⚠ THE CAPACITY READ IS BOUNDED AND CHECKED, not trusted: over **901 accepted blocks**
        # (853 geometry + 48 composite) `capacity - count` is only ever 0 (804), 1 (40) or 2 (57),
        # and the capacity TAIL - the bytes count-sizing would have left - overlaps another
        # modelled structure in **0 of 901**. So the extra records are nobody else's ground.
        if 0 < cap <= 0x200000 and cnt <= cap:
            self._flat(struct.unpack_from('<I', s, d + 0x00)[0], cap * 16)
        if tcap:
            self._flat(struct.unpack_from('<I', s, d + 0x70)[0], tcap * 16)

    def _bound(self, off, depth=0):
        """Walk one phBound; recurse into composite children. Depth-capped and visit-tracked so a
        malformed graph terminates on evidence rather than recursing forever."""
        s = self.res.sys
        if off in self._seen or depth > 32 or off + 8 > self.size:
            return
        self._seen.add(off)
        btype = s[off + 0x10] if off + 0x11 <= self.size else -1
        span = BOUND_SPAN_BY_TYPE.get(btype, BOUND_SPAN)
        self.regions.append((off, bytes(s[off:min(off + span, self.size)])))
        self._octant_map(off)

        # geometry payloads - guarded by the same sanity bounds the decoder uses, so a
        # misread type cannot make us claim a megabyte of coverage from a garbage count
        try:
            nverts, npolys = struct.unpack_from('<I', s, off + 0xD0)[0], \
                struct.unpack_from('<I', s, off + 0xD4)[0]
            nmat = s[off + 0x120]
        except (struct.error, IndexError):
            nverts = npolys = nmat = 0
        # ⛔⛔ THE TYPE CODE IS THE DISCRIMINATOR - THE PLAUSIBILITY TEST ALONE IS NOT.
        # `geom` used to be three range checks on +0xD0/+0xD4/+0x120, and on a COMPOSITE those
        # offsets are not counts at all: `cs2_04_0.ybn`'s root composite reads nverts 3,
        # npolys 589,832, nmat 179 - all three inside the "plausible" windows - so the walker
        # took a composite for a geometry bound. Cost: it ran the geometry captures with garbage
        # counts AND, because the composite work sits behind `not geom`, it silently skipped that
        # root's per-child AABB array and its BVH entirely. The residual it left is unmistakable
        # once seen - 32-byte records of `{vec3 min, margin 0.005}{vec3 max, ...}` repeating on a
        # 0x20 stride, i.e. the AABB array, sitting unclaimed in the middle of the file.
        # ⭐ `ydr2xml` has always keyed off +0x10 (`_BOUND_GEOMETRY_TYPES = (4, 8)`, 10 =
        # Composite). The writer inferring the same thing from value ranges is how the two
        # readers disagreed. The range checks are KEPT as a second gate: a correct type code with
        # a corrupt count must still not claim a megabyte.
        geom = (btype in (4, 8) and 0 < nverts <= 0x8000
                and 0 < npolys <= 0x100000 and nmat)
        if geom:
            self._flat(struct.unpack_from('<I', s, off + 0xB0)[0], nverts * 6)
            self._flat(struct.unpack_from('<I', s, off + 0x88)[0], npolys * 16)
            self._flat(struct.unpack_from('<I', s, off + 0xF0)[0], nmat * 8)
            self._flat(struct.unpack_from('<I', s, off + 0x118)[0], npolys)
            # ⭐ +0x78 ON A **GEOMETRY** BOUND IS A SECOND VERTEX ARRAY (nverts * 6). The
            # composite block below reads +0x78 as the child-TRANSFORM array (n * 64), so on a
            # geometry bound - where +0xA0 is not a child count - the slot was never followed.
            # The two readings are gated by opposite discriminators and cannot collide.
            # MEASURED over 150 files / 1,982 non-composite bounds carrying a live +0x78:
            #   different address from +0xB0 in 1,979 · nverts*6 fits the measured room in 1,976 ·
            #   aliased to +0x80 in 0. Same 3 x i16 shape as the main vertex array.
            # ⛔ DERIVED ONCE, IN `ydr_write._bound`, and mirrored here because these two walkers
            # are deliberately the same offsets - if one changes, change both.
            self._flat(struct.unpack_from('<I', s, off + 0x78)[0], nverts * 6)
            # ⭐ THE TWO COLOUR ARRAYS - NOT a new derivation. `ydr2xml._bound_geometry_lines`
            # has read both since the bounds work, and this writer simply never followed them:
            #     +0xB8 -> vertex colours,   nverts * 4      (same count as the vertex array)
            #     +0xF8 -> material colours, u8 @ +0x121 * 4 (the count sitting beside nmat)
            # ⚠ THE ASYMMETRY IS THE FORMAT, and getting it wrong is how the first probe misread
            # 185 bounds as a DISAGREEMENT: vertex colours are OPTIONAL with a count that is
            # always non-zero, so absence is signalled by the POINTER alone; material colours
            # carry their own count, and the decoder REFUSES when count and pointer disagree.
            # Measured over the same 268 files: +0xB8 live on 111 of 303 geometry bounds in the
            # hard sample, +0xF8 on 129 - so both are minority structures, which is exactly why a
            # sample drawn from one archive family could miss them.
            self._flat(struct.unpack_from('<I', s, off + 0xB8)[0], nverts * 4)
            nmatcol = s[off + 0x121]
            if nmatcol:
                self._flat(struct.unpack_from('<I', s, off + 0xF8)[0], nmatcol * 4)

        if geom:
            self._bvh(off)

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
        # ⭐ +0x88 ON A NON-GEOMETRY BOUND IS A PER-CHILD AABB ARRAY (n * 32): one
        # {vec3 min, u32}{vec3 max, float} pair per child. On a geometry bound the same slot is
        # the polygon array (read above, sized by npolys) - opposite discriminators, no collision.
        # DERIVED IN `ydr_write._bound`; measured over BOTH samples (250 .ydr + 147 .ybn):
        # 255 non-geometry bounds carry it, n * 32 fits in 246/246 that resolve, 0 aliased to
        # +0x70 or +0x78. Mirrored here because these two walkers are the same phBound offsets.
        if not geom and 0 < n <= 4096:
            self._flat(struct.unpack_from('<I', s, off + 0x88)[0], n * 32)
            # ⭐ AND +0xA8 ON A COMPOSITE IS THE SAME BVH BLOCK the geometry bounds carry at
            # +0x130 - a BVH over the CHILDREN. Same reader, same four laws. Gated on `not geom`
            # for the same reason the AABB array above is: on a geometry bound +0xA8 is inside the
            # GeometryCenter vec4, so the discriminators are opposite and cannot collide.
            self._bvh(off, 0xA8)
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
