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
=============== THIRD PASS, 2026-08-14 (superseded by the FOURTH PASS below) ================
⭐ ITS RESULT IS ZERO BYTES, AND THAT IS THE REPORT. Three claim-REMOVING changes were applied,
each measured on its own at POPULATION (all 15,139 files, not a draw). The lane's numbers did not
move by one byte, and the per-file diff is identical in all 15,139:
    population   BEFORE 14,255 / 15,139 (94.1608%), mean 99.9987%, min 99.3774%, 44,356 B unread
                 AFTER  14,255 / 15,139 (94.1608%), mean 99.9987%, min 99.3774%, 44,356 B unread
    board        BEFORE 208/250, mean 99.9961%, min 99.905%    AFTER  identical
⛔⛔ **BUT ONE OF THEM WAS LOAD-BEARING FOR EVERY FILE IN THE GAME, AND ONLY DELETING IT SHOWED
THAT.** `write()` stamped a computed page-count word over an allocation the walk had never
visited. Removing it and adding NOTHING: **14,255 -> 0 of 15,139 byte-exact**, residual 44,356 ->
59,495 bytes = **exactly one extra byte per file, 15,139 of 15,139**. Every byte-exact `.ybn` in
the population was resting on a synthesised value. `_pagemap` models the block map and earns all
14,255 back honestly. ⭐ THE MEAN MOVED 99.9987% -> 99.9974%: a defect one byte deep and PRESENT
IN EVERY FILE IS INVISIBLE TO A MEAN. Byte-exact count is what found it.
Each change, measured separately (population, byte-exact / mean / residual bytes):
 1. DELETE THE PAGE-COUNT WRITE, MODEL THE BLOCK MAP ..... 14,255 -> 0 -> 14,255, net 0 bytes
    Worth zero coverage and everything in trust. See `_pagemap`.
 2. PER-TYPE BOUND SPANS RE-MEASURED AT POPULATION ....... 0 files, 0 bytes
    ⭐ THE FINDING IS A NEGATIVE ONE: `.ybn` HAS ONLY TWO BOUND TYPES. Over **71,912 bounds in
    all 15,139 files**, type 8 (56,773) and type 10 (15,139) are the whole lane; sphere, capsule,
    box, geometry-4 and cylinder occur ZERO times. Both spans already equalled the room to the
    next allocation and over-claimed on **0 of 71,912**. The drawable lanes' table - where a flat
    0x180 ran past the next allocation on 10,322 of 10,322 BOXES - had nothing to fix here,
    because this lane has no boxes. See BOUND_SPAN_BY_TYPE.
 3. READ +0x130 ONLY ON TYPE 8, +0xA8 ONLY ON TYPE 10 .... 0 bounds, 0 bytes
    The `geom` plausibility gate and the type gate agree on 71,912 of 71,912. Applied anyway: a
    type-4 record ends AT 0x130, and these offsets are shared with `ydr_write`, where type 4 does
    occur. Pinned by a test that could have refused - see the +0x130 note in `_bound`.
⭐⭐ THE CONTROL THAT MAKES A CLAIM-REMOVING CHANGE SHIPPABLE: a WHOLE-POPULATION per-file diff,
**0 regressions in 15,139**, run across two independent instruments (a payload cache graded by
`scratchpad/ybn3_grade.py`, and `tools/roundtrip_population_all.py` walking the game itself). The
cache was proven free first: it reproduced the previous population checkpoint in 15,139 of 15,139
keys with zero divergence before it was used to measure anything.
⚠ **AND A CORRECTION TO A CLAIM IMPORTED FROM THE DRAWABLE LANE.** "type 8 == vtable 0x4062fae8,
type 10 == 0x4062bac8" (5 subjects) does NOT generalise: at population each type carries FOUR
distinct vtables. The two SETS are disjoint (overlap 0 of 71,912), so the vtable corroborates the
type byte - but it is not a constant, and THE TYPE BYTE IS THE DISCRIMINATOR.
⚠ THE REMAINDER IS UNCHANGED at 884 files / 44,356 bytes - see REMAINING GAP below.
  ⛔ Δ SUPERSEDED by the fourth pass: 884 files / **42,412 bytes**. Do not quote 44,356 as current.
============================================================================================

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

=========================== FOURTH PASS, 2026-08-14 (LATEST) ===============================
⭐ THE GAP IS NOW ATTRIBUTED TO THE BYTE WITH **NOTHING LEFT OVER**, and one of its two causes is
closed by a law. Reproduce: `scratchpad/ybn4_map.py` (attribution, all 884 short files),
`scratchpad/ybn4_polymat.py` (the law, all 15,139).
    population   BEFORE 14,255 / 15,139 (94.1608%), mean 99.9987%, min 99.3774%, 44,356 B unread
                 AFTER  14,255 / 15,139 (94.1608%), mean 99.9988%, min 99.4141%, 42,412 B unread
    per-file diff over all 15,139: **0 regressions**, 781 better, 14,358 unchanged, net -1,944 B.
⛔ THE BYTE-EXACT COUNT DID NOT MOVE, AND THAT IS THE HONEST RESULT: no file's residual was
poly-material alone, so closing that cause improves every affected file without finishing one.
⭐ Δ THE ATTRIBUTION ITSELF WAS WRONG BEFORE, and the correction matters. The previous split
(90.2 / 5.5 / **4.3% "other"**) measured each gap as a run starting at the first NON-ZERO uncovered
byte, so any tail whose first byte happened to be zero fell out of its own structure and into
"other". Measuring the gap EXACTLY - the uncovered run from the structure's end, zeros included -
leaves **no "other" at all**, over all 884 files and reconciling to the byte with the independently
measured residual (44,356 = 44,356):
    POLYGON array tail ....... 41,912 B (94.49%) in 1,054 runs
    POLY-MATERIAL array tail .. 2,444 B ( 5.51%) in   974 runs
    anything else .................. 0 B ( 0.00%) in     0 runs
⇒ **TWO STRUCTURES ACCOUNT FOR EVERY UNREAD NON-ZERO BYTE IN THIS LANE.** One is now modelled
(`_polymat_pad`, -1,944 B). The other has no field, and the paragraphs below are the evidence.
============================================================================================

⛔ Δ EVERYTHING FROM HERE TO THE FIFTH PASS IS THE HISTORY OF A QUESTION THE SIXTH PASS ANSWERED
DIFFERENTLY. It is kept because the searched spaces and their denominators are still true and
still worth not repeating - but "884 files / 42,412 bytes" and "one cause" are NOT current. See
the SIXTH PASS block above: 7 files / 116 bytes, and the cause is de-duplication.

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

⭐ Δ 2026-08-14 (third pass) - THE REMAINDER RE-MEASURED OVER **ALL 884 SHORT FILES**, not the 34
worst, and the attribution now RECONCILES TO THE BYTE with the independently-measured population
residual (`scratchpad/ybn3_probe_tail.py`; 44,356 = 44,356):
    polygon-array tail  40,020 B (90.2%)  ·  poly-material tail  2,429 B (5.5%)  ·  other 1,907 B
The earlier 94.7 / 5.3 / 0.0 split came from the 34 WORST files and slightly over-weighted the
polygon tail; the shape of the finding is unchanged and 1,006 under-read polygon arrays were
located. Surplus is 1-4 records on 888 of them.
⛔ FOUR MORE HYPOTHESES TESTED AND **ALL FOUR REFUTED**, in a deliberately DIFFERENT search space
from the exhausted field-sweep (which is not repeated). Scored over all 1,006 arrays:
    H1 the ALLOCATION `(npolys+surplus)*16` rounds to K bytes ..... 32:52.6% 64:29.1% 128:12.8%
       256:8.5% 512:5.4% 1024:3.7% - HALVING AT EVERY STEP, which is exactly what CHANCE looks
       like for a rounding rule, not a law. (`npolys*16` is already 16-aligned, so "the totals
       share no modulus" had NOT ruled this out - it needed its own test.)
    H2 `(npolys+surplus)` is a multiple of K (would size the poly-material array too) .. same
       chance curve, 52.6% down to 3.7%.
    H3 ANOTHER BOUND SHARES THE ALLOCATION with a larger npolys - i.e. the surplus is somebody
       else's polygons and no field in THIS record would ever have stated it ....... 0 / 1,006
    H4 the BVH NODE-ARRAY CAPACITY predicts the surplus ........................... 0 / 1,006
⚠ AND A REVERSAL I ALMOST BANKED: scored by uncovered EXTENT, 19 arrays with 372-1,811 surplus
records looked like 87.5% of the residual and a whole second defect class. Counting the bytes the
MEASURE actually uses - non-zero only, since an uncovered ZERO byte still matches a zero-filled
image - they are **2.5%**, and the 1-99 class is 97.5%. Those big allocations are reserved space
that is almost entirely UNWRITTEN. ⭐ It is the same trap as an over-wide span: I measured a
property the measure does not use, and it manufactured a finding. (The `wellformed` test in the
probe had the twin of that flaw - an all-zero record passed every clause - and now rejects zero.)
⇒ The reservation is real and much larger than "1-10 slots" - up to 1,811 records - which
STRENGTHENS the allocated-but-uncounted reading while still locating no field that states it.

⛔⛔ Δ 2026-08-14 (fourth pass) - **THE SEARCH IS NOW CLOSED BY EVIDENCE RATHER THAN BY
EXHAUSTION, AND THE ANSWER IS THAT THE NUMBER IS NOT IN THE FILE.** Every measurement below uses
the EXACT surplus (the uncovered run from the array's end, which is a whole number of 16-byte
records on 1,054 of 1,054 and ends where the next modelled structure begins on 1,051 of 1,054),
not the approximate one the earlier hypotheses were scored against. Denominator throughout:
**1,054 under-read polygon arrays in all 884 short files.**
 A. **THE VALUE IS ABSENT** (`scratchpad/ybn4_exists.py`). Not "we swept these offsets" - the
    whole system segment was searched for the number itself, at every byte-aligned position:
        POSITIVE CONTROL, `npolys` found somewhere in the file .......... 1,054 / 1,054 (100.0%)
        `npolys + surplus` present as a u32 ANYWHERE .................... **150 / 1,054 (14.2%)**
        `(npolys + surplus) * 16` present as a u32 anywhere .............. 42 / 1,054 ( 4.0%)
    and the u32 hits land at unaligned scatter (+0x00F, +0x15F, +0x1DA...), never twice at one
    offset. The u16 figure (88.2%) is chance: a specific 16-bit value appears somewhere in a
    200 KB file with about that probability. ⭐ The positive control is what makes this a result
    - the same search finds `npolys` in every single file, so it is not failing to look.
 B. **PER-OFFSET, NOT "DID ANY WORD MATCH"** (`scratchpad/ybn4_hunt2.py`). The earlier sweep asked
    whether ANY word matched, and a small number matches somewhere in 0x220 bytes ~92% of the
    time by chance. Keyed by (space, offset, form) instead, over the bound record 0x000-0x220,
    the 0x80-byte BVH block, the PARENT COMPOSITE's header and THIS child's transform / AABB /
    flags records, and the 64 bytes before the array: the best offset in any space scores
    **472 / 1,054 (44.8%) - and 472 is exactly the number of arrays whose surplus is 1**. Every
    "candidate" is a constant that happens to equal 1. No field.
 C. **THE SURPLUS IS NOT A SEPARATE OBJECT.** Of every tagged system pointer in every file:
    points AT the first surplus record **0 / 1,054** · points INTO the surplus **0 / 1,054** ·
    points at the allocation END 1,051 / 1,054. ⇒ the gap is a TAIL, not an unmodelled structure
    the walk is missing - which is the other reading it could have had.
 D. **FIVE DERIVED PREDICTORS REFUTED** (`scratchpad/ybn4_predict.py`), each scored on BOTH sets -
    it must equal the surplus on the 1,054 subjects AND equal ZERO on 5,147 exactly-sized control
    arrays, so a predictor that merely correlates is visible:
                                     predicts surplus     fires on an exact array
        quad/box count (a merged pair frees a slot)   1.0%              43.5%
        non-triangle count                            0.8%              56.4%
        degenerate triangles                          0.0%               0.0%
        orphan vertices (left by a removed polygon)   9.5%              33.3%
        adjacency reaching past npolys                0.0%              25.7%
    ⚠ The mesh's own adjacency DOES reach past `npolys` on 266 of 1,054 arrays, which is further
    evidence the uncounted records are real geometry - but it never states how many.
 E. **ALLOCATION ROUNDING REFUTED PROPERLY**, with the exact surplus and the `_pagemap` scoring
    (fits the room / equals it), K = 32..4096: K=32 fits 100% but EQUALS the extent on only 19.8%,
    and every larger K overruns the next allocation on 27-89% of arrays. Nothing both fits
    everywhere and accounts for the extent - which is precisely what 16 DOES do one array over,
    on the poly-material side (see `_polymat_pad`). The contrast is the point: the test is capable
    of finding a granularity when there is one.
⇒ **CONCLUSION, and it is a finding rather than a failure: the polygon array's allocated size is
not recorded in the .ybn.** It is the resource builder's allocation, and the game never needs it -
it iterates `npolys`, and the BVH covers exactly `npolys` (`max(itemId+itemCount) == npolys`,
793/793, 2699/2699, 1305/1305, 3539/3539). The 41,912 bytes are real polygons of the same mesh
left in slots the count no longer reaches.
⛔⛔ AND THE ROUTE THAT LOOKS LIKE A FIX IS THE FORBIDDEN ONE - MEASURED, NOT ASSUMED
(`scratchpad/ybn4_control.py`). "Claim the leading records that look like well-formed polygons"
was tested before writing any of it:
    NEGATIVE CONTROL - polygon arrays whose end is ALREADY another structure (so the 16 bytes
    there are KNOWN not to be a surplus record), **4,390 of them across 1,200 files**:
    `wellformed()` ACCEPTS them **570 / 4,390 (12.98%)** - and 75.5% when the next object is
    another polygon array, 39.0% a material array, 24.6% a poly-material array.
    AND WORSE: of the 1,054 subjects, the rule stops at the GAP END on **934** - i.e. on 88.6% of
    them "claim what looks well-formed" is INDISTINGUISHABLE from "fill to the next allocation".
    It would have read 794 of 884 files byte-exact (40,518 B) and proved nothing.
⇒ Left unclaimed on purpose. **A CLAIMED REGION IS EVIDENCE ONLY IF A WRONG CLAIM COULD HAVE BEEN
REJECTED**, and the comparison image copies the ORIGINAL bytes at whatever offsets are claimed, so
this one would have "worked" exactly as the +0x130 blind fill did.
⚠ WHAT WOULD ACTUALLY SETTLE IT (for a later pass): the same surplus in the DRAWABLE lanes'
embedded bounds, where the same phBound record sits inside a different container - if a container
field states the polygon capacity there, it names the field here too.
  ⛔ Δ THE FIFTH PASS WENT AND LOOKED. The drawable container does NOT state it, and it could not
  have settled this anyway - the phenomenon is 84 arrays in 14,780 drawables. See below.

=========================== FIFTH PASS, 2026-08-14 (LATEST) ================================
⭐ NO BYTES CHANGED AND NO CODE CHANGED. Population identical before and after - 14,255 / 15,139
(94.1608%), mean 99.9988%, min 99.4141%, 42,412 B unread - and a whole-population per-file diff
over all 15,139 keys reads 0 regressions / 0 gains / 0 bytes moved. This pass is FOUR SEARCH
SPACES CLOSED WITH THEIR DENOMINATORS, and one candidate law that its own control destroyed.

⭐⭐ THE METHODOLOGICAL UPGRADE THAT MATTERS MOST - A MAGNITUDE-MATCHED DECOY.
The fourth pass reported "`npolys + surplus` present as a u32 ANYWHERE = 150/1,054 (14.2%)" and
called the u16 figure chance. It never MEASURED chance. `scratchpad/gap_class.py` now scores a
DECOY - `capacity + 1`, an equally plausible allocation of identical magnitude that is definitely
WRONG - beside the real value on the same subjects:
        capacity as u32 anywhere .. 13.6%   DECOY capacity+1 as u32 anywhere .. 10.9%
        capacity as u16 anywhere .. 87.4%   DECOY capacity+1 as u16 anywhere .. 87.8%
⇒ the value search is not weakly positive, it is EXACTLY chance, and now that is a measurement
rather than an assertion. (Denominator: 949 POLYLIKE arrays; positive control `npolys` 100%.)
⚠ An earlier decoy in this pass, `npolys + 977`, scored 0% and looked like a triumph. It is a
bigger, rarer number than the capacity - it scored 0 for reasons of MAGNITUDE alone. A decoy that
is not matched in magnitude measures nothing.

1. WHAT IS ACTUALLY IN THE GAP - CLASSIFIED, not described (`scratchpad/gap_class.py`, all 884
   short files, 1,053 of the 1,054 arrays re-found by an independent walk):
        POLYLIKE (every non-zero record's three u16 at +4 are < nverts) . 949 (90.1%)  38,039 nz B
        OTHER (records whose vertex indices are NOT valid) .............. 96 ( 9.1%)    3,732 nz B
        TRAILER (only the first 16 B non-zero, the rest of a huge gap zero)  8 ( 0.8%)     125 nz B
   ⭐ "the extra records are well-formed polygons" is true of 90%, NOT of all - and the 8 TRAILER
   arrays are the 67..1,672-record reservations: 66,944 bytes of gap carrying 125 non-zero bytes.
   Those are allocated-and-never-written, and they are not the same phenomenon as a 1-record tail.

2. SPACE: THE DRAWABLE LANES (`scratchpad/drw_cache.py` + `drw_polycap.py` + `gap_class.py`).
   A uniform, archive-blind draw - keep iff `crc32(key) % 10 == 0` - of **14,780 drawables (8,607
   `.ydr` + 6,173 `.yft`), 0 reader refusals**, walked with the blind chase DISABLED so every
   boundary is a typed structure or a tagged pointer target.
   ⛔⛔ THE FIRST RUN OF THAT PROBE FOUND 2 SUBJECTS AND WAS WORTHLESS: `ydr_write._chase`
   captures a 0x1000-byte window at every node, so the surplus read as already covered. A probe
   that inherits a blind walk cannot measure what the blind walk hides.
   ⭐ THE METHOD IS CONTROLLED: the same subject rule run on `.ybn` re-finds 1,053 of the
   independently measured 1,054 arrays before it is believed on another lane.
        exactly-sized polygon arrays (control) ....... 6,983
        subjects (allocation past npolys*16) ............ 84   - TRAILER 61 · POLYLIKE 13 ·
                                                                 PTRARRAY 9 · OTHER 1
        POLYLIKE, per-offset sweep of the bound record 0x000-0x220 for the capacity: best 1 / 13
        POLYLIKE, capacity as u32 anywhere 30.8% vs DECOY 15.4% (n = 13)
   ⇒ **NO CONTAINER FIELD**, and - the more useful half - THE DRAWABLE LANES COULD NEVER HAVE
   SETTLED IT: 13 polygon-surplus arrays in 14,780 files against 949 in 884 `.ybn`. The lead was
   sound and the data is not there.
   ⭐ TWO STRUCTURES FOUND WHILE LOOKING, and they belong to `ydr_write`/`yft_write`, not here:
     * 61 of 61 gaps after a TYPE-4 phBoundGeometry polygon array are a 48-byte trailer
       `{float, u32 = 1, 40 zero bytes}` - k = 3 records, CONSTANT on all 61;
     * 9 are arrays of TAGGED SYSTEM POINTERS immediately after the polygon array.
     Both are currently reached only by the blind walk. REPORTED, not edited - other agents' files.

3. SPACE: THE RPF ENTRY HEADER + THE RSC7 HEADER (`scratchpad/ybn5_entry_sibling.py`, 881 files /
   1,050 arrays). A RPF7 resource entry is SIXTEEN BYTES: name offset, on-disk size u24, sector
   offset u23 + is-resource bit, sysFlags u32, gfxFlags u32 - and the two flag words are already
   inside the blob, because `payload()` rebuilds the RSC7 header from them.
        capacity in an entry field ............. 0 / 1,050      CONTROL npolys ..... 0 / 1,050
        capacity in the RSC7 header's 16 bytes .. 0 / 1,050      CONTROL npolys ..... 0 / 1,050
   ⭐ THE CONTROL IS THE RESULT: the entry states no polygon-level count OF ANY KIND, not even the
   one we know is real. A 16-byte per-FILE record cannot size arrays a file has 4.9 of on average.

4. SPACE: THE PAGE PLAN (`scratchpad/ybn5_pageplan.py`, 884 files, 1,054 subjects, 3,187 controls).
   THE DECODE IS CONTROLLED FIRST: the page count `sysFlags` describes equals the block map's own
   `+0x08` byte in **884 / 884**. Then the reading "the array gets the rest of its page":
        predicts the surplus ................ 31 / 1,054 ( 2.9%)
        FALSE-FIRES on an exactly-sized array 3,047 / 3,187 (95.6%)
        no array spans more than one page ... 4,337 / 4,337
   ⇒ REFUTED by both halves at once.

5. SPACE: A SIBLING FILE (same probe; 1,128 siblings read - 1,021 `.ybn` LOD variants, 103 `.ytyp`,
   2 `.ydr`, 2 `.ycd`; 1,357 array x sibling pairs).
        capacity present ... 62.0%    DECOY capacity+1 ... 62.8%    CONTROL npolys ... 62.0%
        as a u32 ONLY:  capacity 0 / 1,357 · DECOY 0 / 1,357 · CONTROL npolys 0 / 1,357
   ⇒ chance, exactly, and the u32 line says it plainly: siblings carry NO polygon count at all.

6. NEW PER-OFFSET SPACES (`scratchpad/ybn5_hunt3.py`, 1,054 arrays) - the ones `ybn4_hunt2` never
   opened: the 64 bytes AT THE ALLOCATION END (a trailer, not a prefix), the ROOT bound record
   (hunt2 reached only the immediate parent), and the 64 bytes around the VERTEX, MATERIAL and
   POLY-MATERIAL arrays and after the BVH NODE array - the one array already known to be sized by
   a capacity - plus the BVH tree records.
        POSITIVE CONTROL  bound +0x0D4 == npolys .......... 1,054 / 1,054 (100.0%)
        MATCHED DECOY     best offset for capacity+1 ......     4 / 1,054 (  0.4%)  <- noise floor
        capacity          best offset (bound +0x00F) ......    13 / 1,054 (  1.2%)
        surplus k         best offset (+0x004 / +0x03C) ....   472 / 1,054 ( 44.8%)  = the known
                          constant-1 artefact, 472 is exactly the count of surplus-1 arrays
   ⇒ nothing anywhere clears the noise floor.

⛔⛔ AND THE ONE CANDIDATE THAT LOOKED LIKE THE ANSWER, KILLED BY ITS OWN CONTROL. Worth the space
because it is the most persuasive wrong answer this gap has produced:
    THE LAW: the polygon array holds `pm_last + 1` records, where `pm_last` is the last non-zero
    byte of the POLY-MATERIAL array - a different array, at a different pointer (+0x118), one
    material byte per polygon. Not a content test on the claimed bytes; not a fill to the next
    allocation. It first measured **956 / 1,054 (90.7%) exact agreement with the gap.**
  ⛔ THAT 90.7% WAS CIRCULAR: the probe scanned the poly-material array only as far as `capacity`,
    a number derived from the polygon gap, so "the last non-zero byte lands on capacity" meant no
    more than "the byte before capacity is non-zero". Re-run with the array's own allocation end:
        NEGATIVE CONTROL - polygon arrays whose end is ALREADY another structure, so their record
        count is KNOWN to be npolys: the law predicts MORE on **2,924 / 3,187 (91.7%)**
        on the subjects it OVERRUNS the next structure on 822 / 1,054 (78.0%)
        and equals the gap-measured capacity on 196 / 1,054 (18.6%)
    ⇒ REFUTED. It is not an independent witness; it is a scan that runs off the end of its array.
  ⭐ THE TRANSFERABLE LESSON, and it is the same one three times now: **a probe whose measurement
    window is derived from the thing it is measuring proves nothing.** The fix is always a control
    on the set where the answer is already known.
  ⚠ AND A BOUNDARY TRAP FOR ANY FUTURE GAP TOOL: `_polymat_pad` claims the poly-material array's
    16-byte padding as a region STARTING AT `pmo + npolys`, so "the next modelled region start
    after `pmo`" is a boundary INSIDE that very array. The first version of the control was capped
    at `npolys` by it and reported a flawless 0% false-fire rate for a law that false-fires on 92%.

⇒ THE FOURTH PASS'S CONCLUSION SURVIVES, now with the four named spaces closed and chance measured
rather than assumed: **the polygon array's allocated size is not recorded in the `.ybn`, nor in the
archive entry, nor in the page plan, nor in a sibling, nor in the drawable container.**
⛔ NOT SEARCHED, so that the next agent does not have to guess what "exhausted" covered: the
GRAPHICS segment of a drawable (searched only as "is the value anywhere", n = 84, never per-offset)
· `.ycd`/`.ypt`/`.yld` and the other lanes with no writer · the game EXECUTABLE's own tables · any
value that is not `capacity`, `capacity*16`, `surplus` or `surplus*16` in u8/u16/u32 · and the
OTHER class (96 arrays, 3,732 non-zero bytes) whose gap records are NOT valid polygons and which
nobody has yet identified.
============================================================================================

=========================== SIXTH PASS, 2026-08-14 (LATEST) ================================
⭐⭐ THE COUNT IS STILL NOT IN THE FILE - **AND THE RECORDS DID NOT NEED IT.** Five passes asked
"where is the number", because the surplus was described as an unknown-length tail. It is not a
tail of unknown things: it is **this mesh's own de-duplicated triangles**, and each one identifies
itself. Population, and the mean is at 100.0000% for the first time:
    BEFORE 14,255 / 15,139 (94.1608%), mean 99.9988%, min 99.4141%, 42,412 B unread
    AFTER  **15,132 / 15,139 (99.9538%)**, mean **100.0000%**, min 99.9950%, **116 B** unread
    whole-population per-file diff, all 15,139 keys: **0 REGRESSIONS**, 877 gains, 877 better,
    0 worse, net **-42,296 bytes**.  ⛔ 884 files short -> **7**.
Three changes, each measured on its own at population (`scratchpad/ybn3_grade.py --diff`):
  1. `_polytail`, triangles only ....... 14,255 -> 14,780   -31,197 B   0 regressions
  2. `_polymat_pad` sized by the recovered record count .. 14,780 -> 14,876  -402 B   0 regressions
  3. `_polytail` extended to the non-triangle primitives . 14,876 -> 15,132  -10,697 B  0 regressions
     (of which the corrected `_PRIM_SLOTS` layout is -3,531 B on its own)

=========================== SEVENTH PASS, 2026-08-15 (LATEST) ==============================
⭐⭐⭐ **THE LANE IS CLOSED AT POPULATION: 15,139 / 15,139 BYTE-EXACT (100.0000%).**
    BEFORE 15,132 / 15,139, 116 B unread in 7 files
    AFTER  **15,139 / 15,139**, **0 B unread**
    whole-population per-file diff, all 15,139 keys (`scratchpad/dq6_diff.py --before
    output/_ybn6_pop2 --after output/_z1_ybnpop`): **0 REGRESSIONS**, 7 gains, 7 better,
    0 worse, net **-116 bytes**.
ONE change: `_polytail` clause 6 now also accepts a record whose f32 at +0x00 is exactly 0.0 -
a DEGENERATE triangle, which a mesh cleaner deletes rather than de-duplicates, so it has no twin
for the original clause to pin it with. The sixth pass measured that clause and DECLINED it on a
seven-subject sample, correctly. What decided it was the DENOMINATOR, which had never been taken:
**0 of the game's 104,624,274 counted, live triangles has an area of exactly 0.0**, and at the
polygon array's own end - the only site the rule is evaluated at - the clause adds **0 false
fires in 55,719 control positions**. Full scoring under `_polytail`; reproduce with
`scratchpad/z1_area.py --report`.

⭐⭐⭐ THE MEASUREMENT THAT TURNED IT - A BASELINE, NOT A DESCRIPTION. "The extras are real
triangles of the same mesh" had been the working description for four passes and was never scored
against how often a COUNTED triangle repeats another counted triangle's vertex triple. Over all
15,139 files (`scratchpad/ybn6_fossil.py`):
        counted triangles repeating a counted triple .... 198,732 / 100,746,732 = **0.20%**
        SURPLUS records repeating a counted triple ......      1,981 /      2,666 = **74.31%**
A 370x enrichment. The counted array is de-duplicated; its tail is where the copies went.
⭐ AND A SECOND FIELD AGREES, with its own positive control (`scratchpad/ybn6_mesh.py`): a triangle
carries three NEIGHBOUR POLYGON indices at +0x0A, and over the 54,807 exactly-sized arrays the
largest is EXACTLY `npolys - 1` on 82.25% of those that have one and **NEVER >= npolys (0 /
54,807)**. The field reaches the top of the array and would have exposed a longer one; on the
subjects it still stops at the counted end, and 74.6% of surplus records carry no neighbour at all.
  ⛔ Δ THIS CORRECTS THE FOURTH PASS: "adjacency reaching past npolys ... fires on an exact array
  25.7%" is wrong. With the index masked (the 0x8000 bit on a vertex index is a flag, not part of
  the index) it fires on **0 of 54,807**. It is a format LAW that was scored as noise.

⛔⛔ ANGLE BY ANGLE, BECAUSE FOUR OF THE FIVE WERE DEAD ENDS AND EACH HAS A DENOMINATOR
(`scratchpad/ybn6_derive.py`, `ybn6_align.py`, `ybn6_meshlaw.py`; 56,773 arrays / 1,053 subjects /
54,807 exactly-sized controls, all 15,139 files):
  A. IS THE ALLOCATION A FUNCTION OF THE MESH?  Grouped by a BYTE-EXACT mesh fingerprint and
     re-scored with duplicate FILES removed (the same `.ybn` ships in patch archives - without that
     control this measures file duplication, not the format): 6,705 meshes appear in more than one
     distinct file, the allocation is constant across them on 6,611 (98.6%), and on **83 of 83**
     of the meshes that have a surplus-bearing copy. ⇒ the builder is deterministic - but that is
     what "same source asset, same tool" predicts, and 94 meshes DO carry different allocations in
     different files, so it is not a function of the final bytes.
  B. A FUNCTION OF THE COUNTS?  Keyed on `npolys`, **1,043 of 1,053 subjects share their `npolys`
     with an exactly-sized control** - refuted outright. Widening the key to
     npolys+nverts+nmat+nmatcol only makes it nearly unique (34,424 keys for 56,773 arrays).
  C. A BUCKETED ALLOCATOR?  Powers of two in records: predicts 2.6% of subjects, false-fires on
     92.7% of controls. `ceil(np/K)*K` for K=2..256 and a 1.5x size-class ladder: every one
     false-fires on 44-99.7% of controls. Refuted by the control half in every case.
  D. ALIGNMENT PADDING FOR THE **NEXT** ALLOCATION - a space the length-rounding tests never
     opened, since `po` is not itself K-aligned: `ceil((po + np*16)/K)*K` for K = 32..65536 peaks
     at 23.4% of subjects while false-firing on 51.2% of controls. Refuted. And the object that
     begins at the allocation end has the SAME type distribution for subjects and controls
     (vertex array 23.5/20.8%, polygon array 15.2/9.9%, poly-material 14.4/14.3%), so the slack
     is not padding in front of anything in particular.
  E. TWO BOUNDS IN ONE ALLOCATION - another bound's polygon array starts at `po + npolys*16` on
     5,427 of 56,773 bounds (9.6%), so the packer does pack them back to back - but every one of
     those is an exactly-sized array by definition. It is never a subject.
  F. DOES THE MESH STATE THE LENGTH?  `nverts` says the array uses N vertices, so the smallest
     prefix that references all of them is a count derived from a field: it OVER-claims past the
     allocation on 9.7% of subjects and false-fires on 7.1% of controls. Refuted.
⇒ **THE ALLOCATED LENGTH IS STILL NOT DERIVABLE.** `_polytail` does not derive it - on 294 of
1,053 subjects it stops short of the allocation end, and it never once ran past one.

⛔ THE REMAINDER, CHARACTERISED RATHER THAN COUNTED: **116 bytes in 7 files**, all of it seven
tail triangles whose vertex triple has NO twin in the counted run, every one with an area field of
exactly 0.0 - a DEGENERATE triangle, which a mesh cleaner deletes outright instead of
de-duplicating, so there is no twin to pin it with.
  ⚠ A CANDIDATE MEASURED AND DECLINED, so nobody re-derives it: adding "area == 0.0" as an
  alternative to the twin clause closes 4 of the 7 (112 B) and accepts 0 of the 114 control
  positions at a polygon array's end - but on the 186,942-position wider control below it accepts
  30, and its subject sample is SEVEN. A clause justified by seven subjects is the coincidence
  generator this lane has been bitten by before. Left unclaimed on purpose.

⭐⭐ THE WIDER NEGATIVE CONTROL (`scratchpad/ybn6_bigctl.py`), because one control site per array
is thin: the shipped rule was also scored at the END OF THE VERTEX, MATERIAL and POLY-MATERIAL
ARRAYS and the END OF THE BOUND RECORD - four more sites per bound where a different structure
follows, **186,942 positions in all 15,139 files**:
        the SHIPPED rule accepts ......... 621 (0.332%)
        the same rule WITHOUT the twin clause .. 194 (0.10%) - but it accepts 100% of the 114
        positions that matter, at a polygon array's own end, which is what refutes it
Its acceptances concentrate where the next object is a genuine polygon array of a related mesh
(vertex-array end 0.422%, bound-record end 0.457%), which is the honest limit of the rule: it
identifies a POLYGON OF THIS MESH, not the boundary of this array. The boundary is done by clause
1 - the coverage guard - and by the run stopping on content.
============================================================================================

⚠ Same scope as the other writers: inflated SYSTEM SEGMENT only. ⛔ Δ THE PAGE-COUNT RECORD AT
`ptr@0x08 +8` IS NO LONGER COMPUTED - it is READ, as part of the block map `_pagemap` models.
See `_pagemap` for why a computed value there was masking an unread allocation in every file.
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
# ⭐ Δ 2026-08-14 (third pass) - THE TABLE IS NOW RE-MEASURED AT **POPULATION**, and the headline
# result is a NEGATIVE one: the two spans this lane actually uses were already exact.
# `scratchpad/ybn3_probe_span.py`, ALL 15,139 files / **71,912 bounds** (not a draw - the whole
# lane), taking each walked bound's room to the next modelled structure:
#     type  8 geometry-BVH  0x150   room 0x150 in 56,455 of 56,773   min 0x150   over-claims 0
#     type 10 composite     0x0B0   room 0x0B0 in 15,139 of 15,139   min 0x0B0   over-claims 0
# ⇒ NEITHER span runs past the next allocation ANYWHERE in the game, and the 318 type-8 bounds
# with a wider room (0x160/0x170/0x180) are padding, not a bigger record.
# ⛔⛔ AND THE REAL FINDING: **`.ybn` CONTAINS ONLY TWO BOUND TYPES.** Sphere (0), capsule (1),
# box (3), geometry (4) and cylinder (13) occur **ZERO** times in 71,912 bounds. The per-type
# table the drawable lanes measured - where a flat 0x180 ran past the next allocation on 10,322
# of 10,322 boxes - has nothing to correct here, because this lane has no boxes. A table imported
# without re-measuring would have looked like a fix and been worth nothing.
# ⚠ THE ENTRIES BELOW FOR TYPES 0/1/3/4/13 ARE **NOT MEASURED IN THIS LANE** - they are the
# drawable lanes' figures (`ydr_write.BOUND_SPAN_BY_TYPE`, 11,626 bounds in 150 files), carried
# here so that a type this lane has never seen cannot fall back to a span 0xE0 too wide. They fire
# on 0 of 71,912 bounds today. ⛔ `4: 0x130` CORRECTS a stale `4: 0x150` that was never measured
# on any `.ybn`: a type-4 record is 0x130, so 0x150 claimed 0x20 bytes past its end - and +0x130
# is exactly where the type-8 BVH slot lives, which is why that slot is now gated on the type.
# ⚠ The fallback is the LARGEST MEASURED span, and that is a statement about the sample, not the
# format. Re-measure before widening the table.
BOUND_SPAN = 0x150                       # fallback / largest measured
BOUND_SPAN_BY_TYPE = {0: 0x70, 1: 0x80, 3: 0x70, 4: 0x130, 8: 0x150, 10: 0x0B0, 13: 0x80}

# ⭐ A POLYGON RECORD IS 16 BYTES AND ITS PRIMITIVE KIND IS `byte0 & 7`; the slots below are the
# u16 VERTEX-INDEX offsets each kind carries (the 0x8000 bit on an index is a flag, not part of
# the index). Kinds 5, 6 and 7 occur on no counted record in this lane and are deliberately
# absent - an unknown kind refuses.
#     0 triangle  (+ three NEIGHBOUR polygon indices at +0x0A)
#     1 sphere    2 capsule    3 box    4 cylinder
# ⭐⭐ DERIVED FROM COUNTED RECORDS ONLY, so it owes nothing to the gap it is used to read
# (`scratchpad/ybn6_primlayout.py`, 1,500 files evenly spaced across the population,
# **451,091 counted non-triangle records**). Every u16 slot in the record was scored on the one
# property an index must have - it is below `nverts` - and the answer is unambiguous:
#     type 1 sphere   n=  4,050   +0x02 100.0%  +0x08 100.0%   every other slot <= 26.8%
#     type 2 capsule  n= 86,703   +0x02 100.0%  +0x08 100.0%   every other slot <= 31.6%
#     type 3 box      n=355,164   +0x04 +0x06 +0x08 +0x0A all 100.0%   others <= 54.3%
#     type 4 cylinder n=  5,174   +0x02 100.0%  +0x08 100.0%   every other slot <= 37.1%
# and the two-index kinds are a vertex PAIR: `u16@+0x08 - u16@+0x02 == 1` on 86,582 / 86,703
# capsules (99.9%) and 4,923 / 5,174 cylinders (95.1%).
# ⛔ Δ A FIRST VERSION GUESSED `(8, 10)` FOR CAPSULE AND CYLINDER and `(8,)` for sphere. It cost
# nothing but coverage - `+0x0A` is 0xFFFF there, so the `< nverts` clause refused every one and
# 3,121 bytes of real capsule records stayed in the residual - which is the behaviour a wrong
# layout is supposed to have here, and is why the range check is applied to every slot.
_PRIM_SLOTS = {0: (4, 6, 8), 1: (2, 8), 2: (2, 8), 3: (4, 6, 8, 10), 4: (2, 8)}


class Ybn:
    def __init__(self, res, flags=(0, 0)):
        self.res = res
        self.sys_flags, self.gfx_flags = flags
        self.size = len(res.sys)
        self.regions = []
        self._seen = set()
        self._polyclaim = {}         # bound offset -> polygon records `_polytail` accounted for
        self._pagemap()
        self._bound(0)
        self._polytail()             # post-pass: needs the whole walk's coverage to refuse on it
        self._polymat_pad()          # post-pass: needs the whole walk's coverage to refuse on it

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

    def _pagemap(self):
        """`resource+0x08` -> THE BLOCK MAP: a 16-byte header plus one 8-byte record per page.

            +0x00 u32 / +0x04 u32 ..... zero in 400/400
            +0x08 u8 SYSTEM page count | +0x09 u8 GRAPHICS page count
            +0x10 .. one 8-byte record per page, `sysPages + gfxPages` of them

        ⛔⛔ WHY THIS EXISTS, and it is the same defect class the `+0x130` blind fill was.
        `write()` used to STAMP the +0x08 word with a value recomputed from the RSC7 flags. That
        write was not reproducing a byte the walk had read - it was standing in for an allocation
        the walk had NEVER VISITED, and it hid it perfectly, because the rest of the block map is
        zero and the comparison image is zero-filled, so only the single non-zero page-count byte
        could ever have shown as a difference.
        ⭐ MEASURED, and the number is the whole argument: deleting the write and adding NOTHING
        took this lane from **14,255 of 15,139 byte-exact to 0 of 15,139**, and the residual grew
        by exactly 15,139 bytes - ONE BYTE PER FILE, in every file in the game. Every byte-exact
        `.ybn` in the population was resting on a computed word rather than on a modelled
        structure. The mean coverage moved only 99.9987% -> 99.9974%, which is precisely why a
        mean cannot be trusted to find this: the defect is one byte deep and universal.
        ⭐ THE SIZE LAW IS PINNED BY THE ALLOCATION, and by a test THREE WRONG ANSWERS FAIL.
        Measured over 400 files drawn evenly across the cached population (probe prints its sample
        size), scoring four candidate strides against the room to the next modelled structure:
            stride    fits the room    EQUALS it exactly    tail all zero
              4 B       400 / 400          0 / 400            400 / 400
            **8 B**   **400 / 400**    **202 / 400**        **400 / 400**
             12 B        31 / 400          3 / 400             31 / 400
             16 B        27 / 400         20 / 400             27 / 400
        Only 8 both fits everywhere AND accounts for the extent; 12 and 16 overrun the next
        structure on more than 90% of files, and 4 never explains the extent at all. The 198 that
        are not exact are padding to the next 16-byte boundary (every observed room is a multiple
        of 16), and that padding is ZERO in 400/400 - so the arithmetic is confirmed by the extent
        and contradicted nowhere. The padding is deliberately NOT claimed.
        ⚠ HONEST ABOUT WHAT IS NOT KNOWN: the per-page records are zero in 400/400 here, so their
        8-byte stride is pinned by the ALLOCATION EXTENT, not by their content. This claims the
        block map's SIZE; it is not a reading of its records.
        ⚠ `.ybn` carries no graphics segment: `+0x09` is 0 in 400/400, so `sysPages + gfxPages`
        is `sysPages` in this lane. The sum is kept because it is the format's, not the lane's.
        ⛔ `_flat_at` REFUSES rather than clamps, so a misread count costs coverage instead of
        inventing it - the same discipline `_bvh` and `_octant_map` already use.
        """
        try:
            buf, o = self.res.deref(self.res.ptr(0x08), 16)
        except (struct.error, IndexError):
            return
        if buf is not self.res.sys:
            return
        self._flat_at(o, 16)
        try:
            n = self.res.sys[o + 8] + self.res.sys[o + 9]
        except IndexError:
            return
        if 0 < n <= 512:
            self._flat_at(o + 16, n * 8)

    def _polytail(self):
        """THE RECORDS PAST `npolys` ARE THIS MESH'S **REMOVED DUPLICATE TRIANGLES**.

        ⭐⭐ THE FINDING THIS RESTS ON, and it is a measurement with a baseline rather than a
        description. Over ALL 15,139 files / 56,773 polygon arrays (`scratchpad/ybn6_fossil.py`):
            counted triangles that repeat another COUNTED triangle's vertex triple, in the same
            array ....................... 198,732 of 100,746,732 (**0.20%**) on the 54,807
                                          exactly-sized arrays - the array is de-duplicated
            SURPLUS records that repeat a COUNTED triple .... 1,981 of 2,666 (**74.31%**)
        A 370x enrichment. The tail of the array is where the de-duplication pass put the copies
        it dropped: it kept one triangle, decremented `npolys`, and left the other in place.
        ⭐ CORROBORATED BY THE ADJACENCY, which is a second field agreeing (`ybn6_mesh.py`):
            a triangle record carries three NEIGHBOUR POLYGON indices at +0x0A. Over the 54,807
            exactly-sized arrays the largest neighbour index is **NEVER** >= `npolys`
            (0 / 54,807), and it is EXACTLY `npolys - 1` on 35,600 of the 43,285 that have any
            neighbour at all (82.25%) - so the field does reach the top of the array and WOULD
            have exposed a longer one. On the subjects it still stops at the counted end, and
            74.6% of the surplus records carry no neighbour at all (all three 0xFFFF): the
            dropped copies were unlinked from the mesh's topology.
          ⛔ Δ THIS CORRECTS THE FOURTH PASS, which reported "adjacency reaching past npolys ...
            fires on an exact array 25.7%" and scored it as a failed predictor. Measured over the
            whole population with the index masked (the 0x8000 bit on a vertex index is a flag,
            not part of the index) it fires on **0 of 54,807**. It is a format LAW, not noise.

        THE RULE, and every clause can refuse. A record at `po + j*16`, j >= `npolys`, is claimed
        only while ALL of these hold, and the walk stops at the first record that fails:
            1. no byte of it is already claimed by another modelled structure
            2. it is not all zero
            3. its type nibble (`byte0 & 7`) is 0, i.e. a triangle
            4. its three vertex indices (low 15 bits) are all below `nverts`
            5. all three NEIGHBOUR indices are 0xFFFF - it is outside the adjacency graph
            6. its vertex triple, sorted, is one THIS bound's counted triangles carry, **OR** the
               f32 at +0x00 reads exactly 0.0 - see THE DEGENERATE CLAUSE below

        ⭐⭐⭐ THE DEGENERATE CLAUSE (2026-08-15), AND THE DENOMINATOR THAT DECIDED IT.
        A de-duplication pass leaves a TWIN behind and clause 6 pins it. A mesh cleaner does not
        de-duplicate a DEGENERATE triangle - it deletes it outright - so a dropped degenerate has
        no twin and clause 6 cannot reach it. Seven records in the whole game were left unclaimed
        for exactly that reason, every one with an area field of 0.0.
        ⛔ THE PREVIOUS PASS DECLINED THIS CLAUSE, AND IT WAS RIGHT TO: it had SEVEN subjects, and
        a clause justified by seven subjects is this lane's own coincidence generator. What was
        never measured was the DENOMINATOR. Measured now over the whole population
        (`scratchpad/z1_area.py`, all 15,139 files / 56,773 geometry bounds):

            COUNTED, LIVE triangle records ...................... 104,624,274
            ... whose f32 at +0x00 reads exactly 0.0 ............ **0  (0.000000%)**
            ... with all three neighbours 0xFFFF ............... 190,580 (0.1822%)
            ... BOTH, i.e. the full clause ...................... **0  (0.000000%)**
            SURPLUS records past `npolys*16`, triangles ......... 1,988
            ... whose f32 at +0x00 reads exactly 0.0 ............ 7 (0.3521%)

        ⇒ **A LIVE TRIANGLE IN THIS GAME IS NEVER DEGENERATE - 0 in 104.6 million.** The clause is
        not "bytes that look plausible"; it is a shape the counted array never takes, and the
        denominator is large enough to say so. (The f32 at +0x00 carries the primitive type in its
        low three bits, so "exactly 0.0" also forces the type nibble to 0 - clause 3 for free.)

        ⭐ AND IT COSTS NOTHING AT THE SITE IT IS APPLIED. Same run, 242,661 control positions
        where the following bytes are known to belong to another structure:
            site (the rule only ever runs here)     positions   SHIPPED   with the clause
            end of an EXACTLY-SIZED polygon array      55,719    40           **40**  (+0)
            end of the vertex array                    47,123   199            229
            end of the material array                  34,030    77             77
            end of the poly-material allocation        49,944    90             90
            end of the bound record                    55,845   255            255
            TOTAL                                     242,661   661 (0.2724%)  691 (0.2848%)
        **At the polygon array's own end - the only site the rule is ever evaluated at - the
        clause adds ZERO false fires in 55,719 positions.** The +30 are at four sites the rule
        never visits; they are the generalisation control, and they are reported rather than
        hidden. And the greedy run still leaves every allocation alone: OVERRUN 2 before, 2 after
        (the same two, both refused by clause 1 in the shipped walk) - the clause adds none.

        ⭐⭐ HOW IT IS PINNED - THREE CONTROLS, because this lane has twice paid for a claim that
        could not fail (`+0x130`, the page-count write). Reproduce: `scratchpad/ybn6_rule.py`,
        `scratchpad/ybn6_decoy.py`.
          A. NEGATIVE CONTROL - the **54,807 exactly-sized arrays**, whose 16 bytes at
             `npolys*16` are KNOWN to belong to another structure. The rule ACCEPTS them on
             **23 / 54,807 (0.04%)**, and on every one of the 23 it stops after a single record:
             total exposure **368 bytes in the whole game**, all of it ground another modelled
             structure already owns, so clause 1 refuses it anyway.
             ⭐ The comparison is the point: "claim the leading records that LOOK like well-formed
             polygons" - the rule the fourth pass MEASURED AND REJECTED - accepts the same control
             on **12.98%**. Same family, 325x the discrimination, and the difference is clauses
             5 and 6.
          B. DECOY MESH - the same greedy run given ANOTHER geometry bound's triple set from the
             SAME file (same builder, same index magnitudes, definitely the wrong mesh), on the
             974 subjects whose file holds a second bound:
                 real triple set  -> reaches the allocation on 700 (71.9%), claims nothing on 254
                 DECOY triple set -> reaches the allocation on   2 ( 0.2%), claims nothing on 970
             ⇒ clause 6 is carrying the rule. A fill would not care whose triples it was given.
          C. IT NEVER RUNS PAST AN ALLOCATION. Over all **1,053 subjects**, scored with NO
             coverage guard at all so the run was free to overrun: it stops exactly at the
             allocation end on 759 (72.1%), short on 294 (274 of which claim nothing), and past
             it on **0**. 31,344 bytes claimed inside an allocation, **0 bytes past one**.
        ⚠ WHAT THIS IS NOT. It does not recover the array's ALLOCATED LENGTH - that number is not
        in the file (see REMAINING GAP), and on 294 of 1,053 subjects this rule stops short of it
        and those bytes stay in the residual. It recovers the RECORDS, on the evidence that they
        are this mesh's own dropped triangles.
        ⚠ GATED ON TYPE 8, like `_polymat_pad`, because that is the only geometry type this lane
        has: over all 71,912 bounds in the population, types 4, 0, 1, 3 and 13 occur ZERO times
        (third pass). A `.ydr`/`.yft` does carry type 4, so a writer sharing this code must widen
        the gate - and `scratchpad/ybn6_drw.py` has already measured what happens if it does.
        """
        s = self.res.sys
        cov = bytearray(self.size)
        for off, data in self.regions:
            if off is not None and data:
                cov[off:off + len(data)] = b'\x01' * len(data)
        for off in sorted(self._seen):
            if off + 0x150 > self.size or s[off + 0x10] != 8:
                continue
            try:
                nverts = struct.unpack_from('<I', s, off + 0xD0)[0]
                npolys = struct.unpack_from('<I', s, off + 0xD4)[0]
                nmat = s[off + 0x120]
                pp = struct.unpack_from('<I', s, off + 0x88)[0]
            except (struct.error, IndexError):
                continue
            if not (0 < nverts <= 0x8000 and 0 < npolys <= 0x100000 and nmat):
                continue
            po = self._off(pp)
            if po is None or po + npolys * 16 > self.size:
                continue
            if npolys > 0x40000:
                continue                 # the counted set below would be unbounded - refuse
            # ⭐ THE COUNTED SETS ARE BUILT ONLY WHEN THE CHEAP CLAUSES HAVE ALREADY PASSED. They
            # are O(npolys) and the population carries 100.7 million counted triangles, so
            # building them unconditionally would cost the lane several times its runtime to
            # answer a question that is 'no' on 53,754 of 54,807 arrays before it is asked.
            triples = recs = None
            claimed = []
            j = npolys
            while True:
                a = po + j * 16
                if a + 16 > self.size or any(cov[a:a + 16]):           # 1
                    break
                r = bytes(s[a:a + 16])
                if not any(r):                                         # 2
                    break
                t = r[0] & 7
                if t not in _PRIM_SLOTS:                               # 3
                    break
                try:
                    v = tuple(struct.unpack_from('<H', s, a + k)[0] & 0x7FFF
                              for k in _PRIM_SLOTS[t])
                except struct.error:
                    break
                if max(v) >= nverts:                                   # 4
                    break
                if t == 0:
                    try:
                        nb = struct.unpack_from('<3H', s, a + 0x0A)
                    except struct.error:
                        break
                    if nb != (0xFFFF, 0xFFFF, 0xFFFF):                 # 5
                        break
                    # 6a - DEGENERATE: the f32 at +0x00 is exactly 0.0, a shape 0 of the
                    # 104,624,274 counted triangles in the game takes. Checked before the
                    # counted-triple set is built because it is O(1) and the set is O(npolys).
                    if struct.unpack_from('<f', s, a)[0] != 0.0:
                        if triples is None:
                            triples = set()
                            for i in range(npolys):
                                o = po + i * 16
                                if s[o] & 7:
                                    continue
                                w = struct.unpack_from('<3H', s, o + 4)
                                triples.add(tuple(sorted((w[0] & 0x7FFF, w[1] & 0x7FFF,
                                                          w[2] & 0x7FFF))))
                        if tuple(sorted(v)) not in triples:            # 6b - TWIN
                            break
                else:
                    if recs is None:
                        recs = set(bytes(s[po + i * 16:po + i * 16 + 16])
                                   for i in range(npolys))
                    if r not in recs:                                  # 6'
                        break
                claimed.append(a)
                j += 1
            for a in claimed:
                self._flat_at(a, 16)
                cov[a:a + 16] = b'\x01' * 16
            if claimed:
                self._polyclaim[off] = npolys + len(claimed)

    def _polymat_pad(self):
        """THE POLY-MATERIAL ARRAY IS ALLOCATED IN 16-BYTE UNITS, not in `npolys` bytes.

        It is the one array in this record whose length is a BYTE COUNT rather than a record
        count, so it is the only one that is not naturally 16-aligned - and that is exactly what
        makes a granularity claim REFUTABLE here: a wrong granularity overruns the next allocation
        15 times out of 16, where on `npolys * 16` it never could.

        ⭐ MEASURED AT POPULATION - all 15,139 files, **53,952 poly-material arrays** that have any
        room after them (`scratchpad/ybn4_polymat.py`; the probe prints its sample size). Scoring
        `ceil(npolys / K) * K` against the room to the next modelled structure:
            K     FITS the room        EQUALS it        non-zero tail bytes it accounts for
             1    53,952 (100.00%)          0 ( 0.00%)          0 of 2,444
             2    53,952 (100.00%)      2,521 ( 4.67%)        493
             4    53,952 (100.00%)      7,569 (14.03%)      1,145
             8    53,952 (100.00%)     18,823 (34.89%)      1,594
          **16**  **53,952 (100.00%)**  **49,569 (91.88%)**  **1,944**
            32    28,884 ( 53.54%)     24,666 (45.72%)      2,154
            64    18,195 ( 33.72%)     14,077 (26.09%)      2,266
        ⇒ 32 and 64 are REJECTED outright: they run past the next allocation on 46% and 66% of
        arrays. 1, 2, 4 and 8 fit everywhere but leave most of the tail unaccounted for. Only 16
        both fits EVERYWHERE and accounts for the extent, which is the same shape of argument -
        and the same table - that pinned the block map's 8-byte page record in `_pagemap`.
        ⚠ HONEST ABOUT WHAT THIS IS NOT. It claims the array's ALLOCATED SIZE. It does NOT explain
        the material bytes that sit in that tail: those belong to the polygon records past
        `npolys`, and NOTHING IN THE FILE STATES HOW MANY OF THOSE THERE ARE (see REMAINING GAP).
        On 148 of 53,952 arrays a non-zero material byte lies BEYOND `ceil(npolys/16)*16` - the
        allocation there was plainly made for the larger polygon count - and this deliberately
        does NOT reach them. Those 500 bytes stay in the residual rather than being covered by a
        claim that is not pinned.
        ⛔ IT REFUSES ON OVERLAP rather than clamping: if any padding byte is already claimed by
        another modelled structure, nothing is captured for that array. That guard is what a wrong
        granularity would have tripped, so it stays even though it fires on 0 of 53,952 today.
        """
        s = self.res.sys
        cov = bytearray(self.size)
        for off, data in self.regions:
            if off is not None and data:
                cov[off:off + len(data)] = b'\x01' * len(data)
        for off in sorted(self._seen):
            if off + 0x150 > self.size or s[off + 0x10] != 8:
                continue
            try:
                nverts, npolys = (struct.unpack_from('<I', s, off + 0xD0)[0],
                                  struct.unpack_from('<I', s, off + 0xD4)[0])
                nmat = s[off + 0x120]
                mp = struct.unpack_from('<I', s, off + 0x118)[0]
            except (struct.error, IndexError):
                continue
            if not (0 < nverts <= 0x8000 and 0 < npolys <= 0x100000 and nmat):
                continue
            # ⭐ Δ 2026-08-14 (sixth pass) - THE ARRAY IS SIZED BY THE RECORD COUNT `_polytail`
            # ACCOUNTED FOR, not by `npolys`. It is one material byte per polygon, so a polygon
            # array carrying `nclaim` records carries `nclaim` material bytes, and the 16-byte
            # allocation law above then rounds THAT. `npolys` is used wherever `_polytail`
            # claimed nothing, which is 54,807 of 56,773 arrays.
            # ⚠ This is a claim DERIVED from another claim, so it inherits `_polytail`'s
            # evidence and nothing more - and the overlap guard below is what stops it
            # compounding an error: if the larger allocation is wrong it runs into the next
            # modelled structure and NOTHING is captured for that array.
            nclaim = self._polyclaim.get(off, npolys)
            pad = -(-nclaim // 16) * 16 - npolys
            if pad <= 0:
                continue
            mo = self._off(mp)
            if mo is None:
                continue
            a, b = mo + npolys, mo + npolys + pad
            if b > self.size or any(cov[a:b]):
                continue
            self._flat_at(a, pad)

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

        # ⛔ Δ 2026-08-14 (third pass) - THE SLOT IS READ ONLY WHERE THE RECORD HAS ONE.
        # `was:` `if geom: self._bvh(off)`, i.e. gated on the geometry PLAUSIBILITY flag, which
        # covers types 4 AND 8. A type-4 geometry record is **0x130 bytes**, so on a type 4
        # `+0x130` is the FIRST BYTE PAST THE RECORD and a pointer read there is a pointer read
        # out of the next structure. `_bvh`'s four laws would almost certainly refuse whatever
        # came back, but "the laws will probably catch it" is not a reason to make the read - a
        # claim must be aimed at ground the record actually owns.
        # ⭐ MEASURED over ALL 15,139 files / 71,912 bounds (`scratchpad/ybn3_probe_slots.py`),
        # and the change alters **ZERO bounds in this lane** - which is the finding, not a
        # disappointment:
        #     type-8 bounds where `geom` is TRUE (read either way) ....... 56,773 / 56,773
        #     type-8 bounds where `geom` is FALSE (would have been missed) ......... 0
        #     non-type-8 bounds the old gate would read +0x130 on .................. 0
        #     non-type-10 bounds the old gate would read +0xA8 on .................. 0
        # It is applied anyway because the gate is now a statement about the RECORD rather than
        # about how plausible its counts looked, and because these offsets are shared with
        # `ydr_write`, where a drawable's embedded graph does carry type 4.
        # ⭐⭐ AND THE SLOTS ARE PINNED BY A TEST THAT COULD HAVE REJECTED THEM. Every bound in the
        # population was checked for a LAW-PASSING BVH block at BOTH slots, so a block on the
        # wrong slot would have shown up:
        #     type  8 : +0x130 -> a block in 56,773 / 56,773 .... +0xA8 -> a block in 0
        #     type 10 : +0x130 -> a block in 0 .................. +0xA8 -> a block in 3,476 / 15,139
        # Each slot belongs to exactly one type and NEITHER ever carries a block on the other's
        # slot. (3,476 of 15,139 composites carry one; it is optional, and the laws are what tell
        # the two cases apart - there is no presence flag.)
        # ⭐ INDEPENDENT WITNESS, and it CORRECTS a narrower claim carried over from the drawable
        # lane. The vtable at `+0x00` is written by the game's packer, not by us. Over the same
        # 71,912 bounds the type-8 and type-10 vtable SETS ARE DISJOINT - overlap 0 - so the type
        # byte is corroborated by a field nobody chose. But there is NOT one vtable per type:
        #     type  8 : 0x4062dab8, 0x4062fab8, 0x4062fac8, 0x4062fae8   (four)
        #     type 10 : 0x40629aa8, 0x4062b5d8, 0x4062baa8, 0x4062bac8   (four)
        # ⛔ So "type 8 == vtable 0x4062fae8" (5 subjects, drawable lane) does not generalise: it
        # is one of four. THE TYPE BYTE IS THE DISCRIMINATOR; the vtable only corroborates it.
        if btype == 8:
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
            # +0x130 - a BVH over the CHILDREN. Same reader, same four laws.
            # ⛔ Δ 2026-08-14 (third pass) - gated on `btype == 10`, not on `not geom`. On a
            # GEOMETRY bound +0xA8 is inside the GeometryCentre vec4, and `not geom` is every type
            # that is not 4 or 8 *plus* any type-4/8 bound whose counts failed the plausibility
            # window - so the old gate could aim this read at the middle of a float. See the
            # population measurement in the +0x130 note above: the change alters 0 of 71,912
            # bounds here, and a law-passing block was found at +0xA8 on a non-composite in 0.
            if btype == 10:
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
