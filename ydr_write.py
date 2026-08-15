"""ydr_write - ROUND-TRIP WRITER for .ydr drawables. THE SHARED DRAWABLE-FAMILY WALKER
(`ydd_write` and `yft_write` subclass this class, so every change here pays or breaks THREE
lanes - always re-measure all three).

=========================== THIRD PASS, 2026-08-14 (LATEST) ================================
⭐⭐ THE SURPLUS POLYGON RECORDS ARE THE MESH'S OWN DE-DUPLICATED TRIANGLES - the `.ybn` rule,
PORTED. The second pass (below) left "~45 files short by 1-5 POLYGON RECORDS" and ruled the class
underivable, because it was asking for a LENGTH. It is not a length question: each surplus record
identifies itself as a copy of a counted triangle of the same mesh. See `_polytail`.

MEASURE 0 - **POPULATION, EVERY FILE** (`tools/roundtrip_population_all.py --run --lanes
ydr,ydd,yft,ytd --workers 6 --out output/_dq6_pop`, then `--report`):
    lane   census   BEFORE byte-exact       AFTER byte-exact        mean cov
    ydr    86,690   86,654  99.9585%     **86,687  99.9965%**       100.0000%
    ydd    23,081   23,080  99.9957%       23,080  99.9957%         100.0000%
    yft    61,430   61,422  99.9870%     **61,428  99.9967%**        99.9997%
    ytd    88,880   (untouched this pass) 88,876 of 88,879 graded   100.0000%
⭐⭐ **WHOLE-POPULATION PER-FILE DIFF, all 171,201 `ydr`+`ydd`+`yft` keys**
(`scratchpad/dq6_diff.py --before output/_dq_pop5 --after output/_dq6_pop`):
    **+39 byte-exact · 0 REGRESSIONS · 39 files better · 0 worse · net -1,828 unread bytes.**
MEASURE 1 - the 250-file boards: ydr 250/250 (unchanged), ydd 250/250 (unchanged),
yft **249/250 -> 250/250**. ⚠ The boards could not see this work: 250/250 was already the ydr
and ydd score BEFORE it. The subject list came from the population records, `exact == false`.
MEASURE 2 - the 45 population failures, cached locally (`scratchpad/dq6_pull.py` ->
`output/_dq6_subj`, graded by `scratchpad/dq6_look.py`) - the fast loop, and the only instrument
that can attribute a gain to ONE change:
    baseline ................................... 0 / 45   621,052 B residual
    `_polytail` alone .......................... 27 / 45  (ydd 0/1, ydr 22/36, yft 5/8)
    + the poly-material tail sized by `nclaim` . **39 / 45** (ydd 0/1, ydr 33/36, yft 6/8)

WHAT WAS CLOSED, each with the control that could have refused it:
 1. `_polytail` - the surplus polygon records. Control: **7,052** polygon arrays where the right
    answer is REFUSE; the shipped rule accepts **3 (0.043%)**, the same rule without its twin and
    adjacency clauses accepts **4,306 (61.06%)**. 0 over-claims on the subjects.
 2. THE POLY-MATERIAL ARRAY IS SIZED BY `nclaim`, NOT `npolys` - one material byte per polygon
    RECORD. Pinned by a count from a DIFFERENT array: on the 45 failures, 14 residual runs sit at
    a material-array tail and the run length equals `nclaim - npolys` on 13 of 14 (the 14th needs
    8 and shows 1 because 7 are zero). See `_polytail`'s tail block.
 3. `yft_write._child +0xB0` (a fixed 48-byte record, 8,890 targets) and `yft_write._lod_phys
    +0xC8` (a per-group pointer array, 5,923 arrays) - two live pointers the walk READ and never
    FOLLOWED. ⭐ **THEY BUY 0 BYTE-EXACT FILES AND ARE STILL THE MOST IMPORTANT CHANGE HERE:**
    both were already "covered" by the blind walk's unpinned 0x1000-byte windows, and a claim
    that cannot fail is the defect this measure exists to catch. See `yft_write._child`.
⛔⛔ THE CORRECTION THIS PASS OWES ITS PREDECESSOR, and it is a method point, not a detail: the
handover described 61 gaps as a "type-4 48-byte TRAILER" after the polygon array and 9 more as
"tagged-pointer arrays after the polygon array". **All 70 were POINTED AT** - `scratchpad/
dq6_who.py` scanned every tagged u32 in the segment for one targeting the gap's first byte and
found one for 72 of 72. They are allocations the packer placed after a polygon array, not tails
of it. Sized as tails they would have been a fill from one region's end to the next region's
start. ⇒ **BEFORE SIZING A GAP, ASK WHO POINTS AT IT.** A pointed-at gap is a reachability
defect with a NAMED SITE (`dq6_owner.py` traces the pointer back to the capture that owns it);
only an unpointed one can even be a tail.
⏭ WHAT REMAINS, 6 files, ALL ONE CLASS BAR ONE (`scratchpad/dq6_slack.py`):
   NON-ZERO BYTES IN ALLOCATION SLACK. Every region sits at the END of an allocation, is
   targeted by **0** tagged pointers, and begins 4,096-4,128 bytes past the last modelled
   structure - i.e. exactly where `CHASE_CAPTURE` ran out. Where the content has a twin at all it
   is a byte-copy of ANOTHER UNCLAIMED region, not of a live array: the packer's arena still
   holding an earlier write. Nothing in the file states its length, and claiming it is precisely
   the region-end-to-region-start fill this measure exists to catch.
     `des_fib_ceil2_root` 417 B · `des_hosp_ceil_root` 168 B · `des_smash_root_merge` 189 B -
       slack of a skeleton matrix array / a `_shaders` allocation; content is a partial copy of
       the skeleton's ChildIndices, repeated at decreasing lengths (the array rebuilt in place).
     `po1_07_slod1_2_children.ydd` 4 B - one float in the 28 bytes between a vertex buffer's end
       and the 0x1000 page boundary.
     `barracks_hi.yft` 2,696 B - page slack of a 970 x 60 vertex buffer; longest prefix found
       anywhere else in the file is 2 bytes, so it has no twin and no source.
     `xm_prop_auto_salvage_stromberg.yft` 615,750 B - NOT this class: a reachability defect,
       diagnosed under `yft_write._drawable_array` and deliberately unfixed there.
⛔ SEARCHED AND NOT FOUND, so the next pass does not repeat it: a tagged pointer targeting any of
those regions (0 of 6); an owning structure whose end they extend (they are all at an allocation
END, not a record end); a live array they copy (only other UNCLAIMED bytes). NOT SEARCHED: the
packer's own page-plan records as a source of slack extents, and whether the arena residue is
reproducible from the file's OTHER resources (it is a cross-file question this pass never opened).
============================================================================================

=========================== SECOND PASS, 2026-08-14 ========================================
⭐ WORKED FROM THE POPULATION RECORDS, NOT A SAMPLE. The 250-file draw already read 250/250 for
this lane, so it could not see the work: the files that fail are RARE and a 250-file draw misses
them entirely. The subject list was the 572 files the whole-game run graded short
(`output/roundtrip_population/results.w*.jsonl`, `exact == false`), 563 of which were re-fetched.

MEASURE 0 - **POPULATION, EVERY FILE OF ALL THREE LANES** (171,201 files, 100.00% of the census).
Re-run: `python tools/roundtrip_population_all.py --run --lanes ydr,ydd,yft --workers 6
--worker-id <i> --out output/_dq_pop2`, then `--report --out output/_dq_pop2`.
    lane   census   BEFORE byte-exact      AFTER byte-exact     mean coverage    refusals
    ydr    86,690   86,368  99.6286%       86,642  99.9585%     99.9983%         12
    ydd    23,081   23,066  99.9350%       23,080  99.9957%     100.0000%         0
    yft    61,430   61,195  99.6175%       61,422  99.9870%     99.9997%          0
    segments after: ydr sys 99.9983 / gfx 99.9967 · ydd sys 100.0000 / gfx 100.0000
                    yft sys 99.9996 / gfx 100.0000
⭐⭐ **+515 FILES BYTE-EXACT AND ZERO REGRESSIONS** - every one of the 171,201 keys was compared
against its record in the 2026-08-14 run and NOT ONE file that was byte-exact then is short now.
That control is the reason the per-type span tightening and the removed page-count write could be
shipped: both REMOVE claims, and only a whole-population diff can prove a removal cost nothing.
⏭ 57 files remain short (ydr 48, yft 8, ydd 1): 12 are extractor refusals, 4 are the `des_*`
bound-layout class, 41 are the small-residual class - all four itemised below.

MEASURE 1 - the 250-file sample, `python tools/roundtrip_coverage.py --lane <x> --limit 250`:
    lane   before this pass          after
    ydr    250/250  100.0000%        250/250  100.0000%   (sys 100.0000 / gfx 100.0000)
    ydd    250/250  100.0000%        250/250  100.0000%   <- see the WARNING below
    yft    247/250  100.0000%        249/250  100.0000%
⚠ THE `.ydd` 250/250 WAS NOT REAL AND THIS PASS PROVED IT. Removing the page-count write (see
`write`) dropped it to **243/250** - because on 7 of those files that write was reproducing a
block-map allocation NOTHING HAD READ. `_pagemap` now models the structure and earns the 250 back.
A number that only survives because a computed value is pasted over an unread region is a number
that measures the paste.

MEASURE 2 - the POPULATION WORK QUEUE (563 known-short files; `scratchpad/_dq_regrade.py`).
⚠ NOT a population figure: it grades ONLY the files that were failing, so "N exact" means N files
LEFT the queue.
    lane   byte-exact  residual bytes        ->   byte-exact  residual bytes
    ydr      0 / 320     2,195,612                272 / 320       882,716
    ydd      1 /  12            14                 11 /  12             4
    yft      0 / 231       650,060                223 / 231       618,524
    TOTAL    1 / 563                              506 / 563
`.yft`'s residual barely moves because ONE file, `xm_prop_auto_salvage_stromberg.yft`, is 615,750
of the 618,524 that remain.

WHAT WAS CLOSED, in the order applied, each measured on the queue:
 1. THE SHADER GROUP WAS NEVER READ AS A SHADER GROUP ....... yft 0 -> 189 exact
    `_texdict` treated `sg+0x10` as an array DESCRIPTOR; it is the shader POINTER ARRAY, whose
    count is a separate field at `sg+0x18`. The parameter table, its value blocks and its name
    hashes were left to the blind walk. `ydd_write` had a correct typed reader and its own
    docstring said it belonged here; it is now here, as `_shaders`, and `ydd_write`'s is
    SUPERSEDED. See `_shaders`.
 2. `write()` OVERWROTE A BYTE IT HAD ALREADY REPRODUCED .... 60 files (10 ydd/22 ydr/28 yft)
    The page-count law is not universal on this family. See `write` and `_pagemap`.
 3. THE `+0x130` "ARRAY DESCRIPTOR" WAS REFUTED, AND IT WAS A FILL ...... ydr 20 -> 78 exact
    ⭐ CONTROL RUN, the fill removed and NOTHING put back: ydr **20/320 exact, 22,703,202
    residual bytes** - i.e. the old reading was concealing 20.5 MB of unread data behind a claim
    that could not fail, and buying 2 byte-exact files for it. The real structure scores better
    than the fill ever did. See `_bvh`.
 4. COMPOSITE `+0xA8` BVH · VERTEX COLOURS `+0xB8` · MATERIAL COLOURS `+0xF8` ·
    THE TYPE CODE AS THE GEOMETRY DISCRIMINATOR ............. ydr 78 -> 254, yft 217 -> 223
 5. THE ROW PITCH OVERRULES THE FourCC ..................... ydr 254 -> 272 (all in GRAPHICS)
    18 embedded textures declare DXT1/DXT5 and store 4 bytes per pixel. See `_texdict`.
 6. PER-TYPE phBOUND RECORD SPANS (0x180 -> 0x70/0x80/0xB0/0x130/0x150) ..... 0 files, and that
    is the point: it removed an over-claim of up to 0x110 bytes per bound that ran past the next
    allocation on 10,322 of 10,322 boxes. See BOUND_SPAN_BY_TYPE.
⚠ (3), (4) and the `+0x130` refutation are the `.ybn` agent's derivation, RE-CONFIRMED here on
this lane's own subjects before adoption - see `_bvh` for the re-confirmation.

WHAT REMAINS, 60 of 563 - all characterised, none guessed:
  * 16 `.ydr` the EXTRACTOR cannot decode (12 refuse outright). Every one is RSC7 version 164
    (gfxFlags high nibble 4, not 5); their bodies come out of `quarry.payload`'s `stored-raw`
    last resort as HIGH-ENTROPY NOISE - `des_bridge_root.ydr` inflates to 396,498 B of noise
    against a 630,784 B page plan. NOT a writer defect; reported to the extractor's owner.
  * ~45 files short by 1-5 POLYGON RECORDS (13/16/32/48/64/80 bytes, `.ydr` and `.yft` alike).
    The polygon array runs past `npolys * 16` and stops exactly where the next allocation
    begins. RULED OUT as underivable for now - see the note under `_bound`.
  * `des_ranchsafe001_start/end.ydr`, 206,922 / 278,730 B in 9 and 15 runs. DIAGNOSED, NOT
    FIXED: the bound at 0x0cf5b0 in `_start` reads type 8 (geometry-BVH) with **nverts 0 and
    npolys 0**, so the geometry branch is skipped - yet its `+0x88` holds a live pointer to
    0x060000 and 73,072 bytes of well-formed polygon records sit there, reached only by the blind
    walk's first 0x1000. Its vtable is **0x405b5408**, not the 0x4062fae8 every correctly-read
    BVH bound in this pass carries. Reading the record 8 bytes lower gives plausible counts
    (2,844 verts / 4,823 polys = 77,168 B) but an implausible type byte, so the base or the field
    offsets differ for this class and it is NOT resolved here. ⛔ Do not shift the offsets on this
    evidence - it is two files.
  * `xm_prop_auto_salvage_stromberg.yft` 615,750 B (cause found - see `yft_write`) ·
    `barracks_hi.yft` 3,024 + 2,160 B, still unattributed.
============================================================================================

⚠ THE PASS BELOW IS THE EARLIER RECORD OF THE SAME DAY, kept because its findings still hold.
COVERAGE 2026-08-14 (250-file stratified sample): **100.0000%** overall - system 100.0000%,
graphics 100.0000%, and **250/250 files byte-EXACT**. Reproduce:
`python tools/roundtrip_coverage.py --lane ydr --limit 250`.
⚠ Δ SUPERSEDES "99.9808% / sys 99.9248% / 206 exact". FIVE defects closed in this pass, each
measured on its own (overall / system / byte-exact), in the order applied:
  1. `_chase` PRE-EMPTED THE TYPED WALK ...... 99.9106 -> 99.9476 | 99.8542 -> 99.9299 | 218
     The blind walk shared `_seen` with the typed walks and ran in the MIDDLE of `_drawable`, so
     it could mark a record the typed walk had not reached yet and that whole subtree was then
     skipped in silence. Now DEFERRED - see `_chase`. (min coverage 93.378% -> 97.340%.)
  2. CLAMP A FIXED SPAN, REFUSE A COUNT-DERIVED ONE  99.9478 -> 99.9532 | 99.9309 -> 99.9484 | 232
     `_put`/`_flat` threw away a whole region when it overran the segment end. See `_put`.
  3. THE SKELETON'S ARRAYS WERE NEVER WALKED .. 99.9532 -> 99.9978 | 99.9484 -> 99.9955 | 236
     Only the 0x80-byte header was captured; the arrays were left to the blind walk, which takes
     its window and stops. See `_skeleton`. (min 97.340% -> 99.625%.) THE BIGGEST SINGLE GAIN.
  4. THE BONE ARRAY'S 16-BYTE ALLOCATION PREFIX  99.9978 -> 99.9979 | 99.9955 | 236 -> 246 exact
     Worth ~0.0001% but TEN files: they were one byte short. See `_alloc_prefix`.
  5. phBOUND +0xC0/+0xC8 OCTANT MAP .......... 99.9979 -> 99.9997 | 99.9986 | 246 -> 249 exact
     and phBOUND +0x88 PER-CHILD AABB ARRAY ... 99.9997 -> 100.0000 | 100.0000 | 250/250 exact
     See `_octant_map` and the +0x88 note in `_bound`.
⭐ THE LANE'S "prop_snow_*" VARIANT SIGNATURE WAS NOT A FORMAT PROPERTY. Those files dominated
the worst-case list for two independent scans and were treated as a DLC-specific hazard; all 10
in the sample are byte-exact after (1) and (2), with no snow-specific code. The signature was the
two ordering/refusal defects, and reading it as a variant sent earlier passes hunting a constant.
⚠ Δ Two corrections carried forward from the previous pass, still true:
  1. the graphics segment was NEVER exactly 100% before - the harness printed 2 decimals, so
     99.9994% displayed as "100.00%" (fixed; it prints 4dp now). The 100.0000% above is measured
     at 4dp with 173 of 250 files carrying a graphics segment;
  2. the "vertex-count under-read" this file used to name as its one remaining defect **did not
     exist** - a mis-factorisation, retracted in full at the `vd = ...` line below.

    inflated system+graphics segments -> value model -> written back -> reproduce original bytes

WHY: `.ydr` is 86,690 files - the largest in-scope model lane and the last big one gating the
mapping milestone with no writer. Round-trip is the primary measure (Matt, 2026-08-13); a lane
with no writer is UNMEASURED, not passing.

⚠ DRAWABLES SPAN TWO SEGMENTS. Vertex and index data live in the GRAPHICS segment while the
graph lives in the system segment, so coverage is reported for BOTH - a writer that modelled only
`sys` would look far more complete than it is.

Chain (per `ydr2xml`, which derived it over 3,479 base-game drawables):
  +0x10 shader group · +0x18 skeleton · +0xB0/+0xB8 lights (n, stride 0xA8) · +0xC8 embedded bound
  LOD group slot -> {model-array ptr @+0x00, model count u16 @+0x08}
  model (0x30) -> {geometry-array ptr @+0x08, geo count u16 @+0x10, geo-bounds ptr @+0x18}
    geometry bounds = (ngeo+1 if ngeo>1 else ngeo) * 32
  geometry (0x80) -> {vertex buffer @+0x18, index buffer @+0x38,
                      index count u32 @+0x58, vertex count u16 @+0x60, stride u16 @+0x70}
  vertex buffer (0x40) -> {flags u16 @+0x0A, vertex data @+0x10, FVF @+0x30}
⛔ `stride` is a u16 - a u32 read yields 983,100 on skinned meshes (recorded in ydr2xml).

REMAINING GAP: none in this sample - 250/250 byte-exact, every segment 100.0000%.
⛔ THAT IS A STATEMENT ABOUT COMPLETENESS, NOT INTERPRETATION, and about 250 files, not 86,690.
The measure proves every byte was reached from a decoded pointer/count, never that each field is
correctly NAMED - mislabel a field and it still round-trips. Two structures here are honest
reachability with a name rather than a full reading: `_octant_map` pins the octant arrays' extent
by their own arithmetic without claiming what the indices address, and `_chase` proves bytes
belong to the drawable's graph without typing them. The next thing this lane needs is a WIDER
draw (and the variant axis the harness caps on), not another decimal.
ASCII output only.
"""
import os
import struct
import sys as _sys


_sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ydr2xml import Res  # noqa: E402
# ⭐ THE POLYGON-RECORD LAYOUT IS IMPORTED, NEVER COPIED. `ybn_write._PRIM_SLOTS` is the u16
# vertex-index slot map per primitive kind, derived on 451,091 COUNTED non-triangle records in
# 1,500 files - a derivation this lane has no reason to repeat and every reason not to fork.
# Same doctrine as `ydd_write`/`yft_write` importing this module rather than copying its walk.
# ⚠ `ybn_write` imports only `ydr2xml`, so there is no cycle.
import ybn_write  # noqa: E402

LOD_SLOTS = (0x50, 0x58, 0x60, 0x68)     # candidate LOD group slots; non-resolving ones no-op
DRAWABLE_SPAN = 0x100
# ⭐ MEASURED OPTIMUM, not chosen: how many bytes to capture at a node reached by the generic
# graph walk. Nodes out there run to several hundred bytes, so capturing only as far as we RECURSE
# leaves their tails unread. Sweep over 120 files (system-segment coverage):
#   0x80 -> 99.41% | 0x200 -> 99.58% | 0x800 -> 99.71% | 0x1000 -> 99.78% (BEST)
#   0x2000 -> 99.70% | 0x4000 -> 99.63%  <- both WORSE, re-measured after the later fixes too
# ⛔ Bigger is NOT better past 0x1000 - over-capture claims a neighbour's bytes and the visited
# set then blocks a better-typed read of that region. Re-measure before changing this.
CHASE_CAPTURE = 0x1000
# ⭐ SCAN WIDTH IS A SEPARATE KNOB FROM CAPTURE WIDTH, and conflating them hid a whole gap class.
# `_chase` captured CHASE_CAPTURE (0x1000) bytes at a node but scanned only 0x80 of it for
# pointers, so **any descriptor living past byte 128 of a captured node was never followed**.
# Measured 2026-08-14 by the pointer-site scan: 32 of 38 gap STARTS are pointed at from ground we
# already model - i.e. we hold the pointer and never chase it. Confirmed shape at those sites:
# `{u64 ptr, u32 count, u32 capacity}` -> a 16-BYTE-RECORD array (189 x 16 = 3,024 vs a 3,023 B
# measured span; 255 x 16 = 4,080 vs 4,079 - the odd byte is the last record's trailing zero).
# ⛔ Do NOT confuse this with widening CHASE_CAPTURE, which was swept and is WORSE past 0x1000
# (over-capture claims a neighbour's bytes and the visited set then blocks a better-typed read).
# Scanning wider claims NO extra bytes by itself - it only discovers more pointers to follow.
# ⭐ MEASURED SWEEP 2026-08-14, 250-file sample, the ONLY variable changed (overall / sys / exact):
#   0x80  99.9659 / 99.8458 / 192   <- the old hard-coded value
#   0x100 99.9775 / 99.9047 / 202
#   0x200 99.9807 / 99.9240 / 205
#   0x400 99.9808 / 99.9248 / 206   <== KEEP
#   0x800 99.9793 / 99.9177 / 205   (worse)
#   0x1000 99.9800 / 99.9230 / 205  (worse)
# ⛔ Wider is NOT better here either: past 0x400 the scan starts following FALSE tagged pointers
# out of dense vertex/float data, and the visited set then blocks a better-typed capture of the
# region they land in. Re-measure before changing this.
CHASE_SCAN = 0x400
# crBoneData stride - 80, measured by adjacent-offset stride over 150 files (`ydd_write` records
# the same 80 in 60/60 skeletons). Named here because `_skeleton` now lives in this module.
BONE_STRIDE = 0x50
# grcTexture reference stub - 80 bytes, measured by adjacent-offset stride over 150 .ydd files
# (675/675 minimal adjacent pairs). Named here because `_shaders` now lives in this module.
STUB_RECORD = 0x50

# ⭐⭐ A phBOUND RECORD'S SIZE IS ITS TYPE'S, NOT ONE FLAT 0x180.
# ⛔ `was:` `_put(off, 0x180)` for every bound. MEASURED 2026-08-14 over 150 files of the
# population work queue, taking each walked bound's room to the NEXT allocation in the segment
# (n = bounds of that type; the figure is the room, i.e. an upper bound on the record):
#     type  0 sphere ..... 0x70   7/7        type  8 geometry-BVH  0x150  259/270 (7 at 0x140)
#     type  1 capsule .... 0x80   406/406    type 10 composite .... 0x0B0  124/125
#     type  3 box ........ 0x70   10297/10322 (21 at 0x80)
#     type  4 geometry ... 0x130  13/13      type 13 cylinder ..... 0x080  465/465
# and the 0x180 span RAN PAST THE NEXT ALLOCATION on 10,322 of 10,322 boxes, 465 of 465
# cylinders, 406 of 406 capsules and 267 of 270 BVH bounds - i.e. on a box it claimed 0x180 for a
# 0x70 record and swallowed the next TWO bound records whole. It looked harmless only because
# those neighbours are usually bounds the walk visits anyway; where they are not, the over-claim
# is a fill that cannot fail. `.ybn` measured the same 0xB0 / 0x150 independently and found 0x180
# claimed 33,552 extra bytes for ZERO gain - two lanes, two samples, one table.
# ⚠ AN UNKNOWN TYPE FALLS BACK TO 0x180, which is the old over-claim: it is kept ONLY so a bound
# type this sample never saw cannot silently lose its whole record, and it fires on 17 of 11,626
# bounds here (types 6, 16 and 178). Re-measure before widening the table.
BOUND_SPAN_BY_TYPE = {0: 0x70, 1: 0x80, 3: 0x70, 4: 0x130, 8: 0x150, 10: 0xB0, 13: 0x80}

# ⭐⭐ THE OLDER-BUILD phBoundGeometryBVH: A 0x140 RECORD, NOT 0x150 (2026-08-14).
# `des_ranchsafe001_start/end.ydr` carry type-8 bounds whose vtable is 0x405b5408, a value that
# appears in NEITHER of the vtable sets the population census found (type 8: 0x4062dab8/fab8/
# fac8/fae8, type 10: 0x40629aa8/b5d8/baa8/bac8, disjoint, 0 overlap in 71,912 bounds). Their
# companion composite carries 0x405b1cd8, likewise outside the known set. It is a DIFFERENT
# BUILD of the same classes: the record is 0x10 bytes shorter, and every field from the material
# array onward keeps its relative spacing exactly.
#     field            standard   this class
#     nverts / npolys   +0xD0/D4   +0xC8/CC     (8 B earlier)
#     materials         +0xF0      +0xE0        (0x10 earlier, and so is everything after it)
#     material colours  +0xF8      +0xE8
#     poly-materials    +0x118     +0x108
#     nmat / nmatcol    +0x120/121 +0x110/111
#     BVH block         +0x130     +0x120
#     0xffff terminator +0x140     +0x130   -> record span 0x140, and the three records in
#                                             `_start` are packed at exactly 0x140 stride
#     polys +0x88 · verts +0xB0 · vertex colours +0xB8 · second vertex array +0x78 - UNCHANGED,
#     read identically in both and confirmed against a same-archive v165 control.
# ⭐ PINNED BY A TEST THAT COULD HAVE REJECTED IT, on 7 of 7 records across the 2 files:
#   * read at the STANDARD offsets the record gives nverts 0 / npolys 0 and a BVH pointer of
#     0x0000ffff, which does not resolve - i.e. the standard reading is refutable and IS refuted;
#   * read at these offsets, the BVH block found at +0x120 passes ALL FOUR `_bvh` laws
#     (zero block · scale*scaleinv == 1 · (max-min)*scaleinv == 65535 · tree count == capacity);
#   * and `max(first + count)` over that block's leaf nodes equals the npolys read at +0xCC
#     EXACTLY - 3225, 4823, 43, 4823, 4834, 495, 162 - a seven-way identity between two
#     independently-read structures that no offset guess produces by accident.
# ⛔ GATED ON THE VTABLE, never on the file name or the count plausibility. A name cluster is a
# lead about WHERE a defect lands, never a format variant - that mistake has been made three
# times in this campaign. A vtable is the class's own identity. And every span below still goes
# through `_flat`, which REFUSES on overrun, so a wrong match cannot fill - it can only decline.
BOUND_FIELDS_STD = {'span': 0x150, 'nverts': 0xD0, 'npolys': 0xD4, 'mats': 0xF0,
                    'matcol': 0xF8, 'polymat': 0x118, 'nmat': 0x120, 'nmatcol': 0x121,
                    'bvh': 0x130}
BOUND_FIELDS_OLDBUILD = {'span': 0x140, 'nverts': 0xC8, 'npolys': 0xCC, 'mats': 0xE0,
                         'matcol': 0xE8, 'polymat': 0x108, 'nmat': 0x110, 'nmatcol': 0x111,
                         'bvh': 0x120}
BOUND_VTABLE_OLDBUILD = frozenset((0x405B5408,))      # type 8 only; the composite reads standard
BOUND_SPAN_DEFAULT = 0x180


class Ydr:
    # ⭐ THE TWO CHASE WIDTHS ARE CLASS ATTRIBUTES, NOT MODULE GLOBALS, so a subclass keeps its
    # OWN measured optimum without forking `_chase`. `yft_write` swept SCAN on its own 330-file
    # sample and landed on 0x1000 where this lane's sweep landed on 0x400 - two lanes, two
    # measurements, one implementation. Overriding a constant is evidence; copying a method is
    # drift.
    CHASE_CAPTURE = CHASE_CAPTURE
    CHASE_SCAN = CHASE_SCAN

    def __init__(self, res, flags=(0, 0)):
        self.res = res
        self.sys_flags, self.gfx_flags = flags
        self.nsys, self.ngfx = len(res.sys), len(res.gfx)
        self.sysr, self.gfxr = [], []
        self._seen = set()
        self._defer = []                 # see `_chase` - the blind walk runs LAST, never first
        self._bounds = []                # [(off, btype, fld)] - the typed walk's phBounds
        self._polyclaim = {}             # bound offset -> polygon records `_polytail` accounted
        self._pagemap()
        self._drawable(0)
        # ⭐ BEFORE the blind walk, deliberately: `_polytail`'s first clause refuses on ground
        # another MODELLED structure already owns, and a 0x1000-byte chase window is not one.
        # Running it after the flush would let an unpinned window pre-empt a pinned rule.
        self._polytail()
        self._flush_chase()

    # ---- segment-aware capture: a tagged pointer may resolve into EITHER segment
    #
    # ⭐⭐ CLAMP A FIXED SPAN; REFUSE A COUNT-DERIVED ONE. These two are NOT the same claim and
    # treating them alike is what made the capture sweep look non-monotonic.
    #   `_put`  takes a FIXED record/window span (DRAWABLE_SPAN, 0x180, CHASE_CAPTURE, 0x90 ...).
    #           A record that starts 0x40 before the segment end demonstrably IS 0x40 long - the
    #           format cannot address past the segment - so the right answer is to shorten the
    #           claim, not to throw the whole region away. Refusing lost REAL, reachable bytes at
    #           every page-edge allocation.
    #   `_putn` takes a COUNT-DERIVED span (`count * stride`). If that does not fit, the COUNT IS
    #           MISREAD - and clamping it would claim from a resolved pointer to the end of the
    #           segment, which is the fill this measure exists to catch. It still REFUSES.
    # MEASURED on the 250-file sample before changing anything (scratchpad/probe_clamp.py):
    #   fixed-span overruns  3,245 events, 7,891,969 B of in-segment room, p50 2,592 B, max 40,848
    #   count-derived        48 events,       842,848 B of room, p50 8,272 B, max 132,400 B
    #                        - e.g. a span asking 518,912 B with 386,512 B of overrun. That is not
    #                          an array straddling a page, it is a count that is wrong.
    # ⛔ Every capture is a VERBATIM COPY of the source, so ANY byte claimed trivially reproduces
    # and WIDENING A CLAIM ALWAYS INFLATES COVERAGE. That is the whole reason the split above is
    # drawn on evidence rather than on which option scores better.
    def _put(self, off, nbytes, seg=None):
        if off is None or nbytes <= 0:
            return
        if seg == 'gfx' or (seg is None and off >= self.nsys):
            o = off - self.nsys if off >= self.nsys else off
            n = min(nbytes, self.ngfx - o)
            if n > 0:
                self.gfxr.append((o, bytes(self.res.gfx[o:o + n])))
            return
        n = min(nbytes, self.nsys - off)
        if n > 0:
            self.sysr.append((off, bytes(self.res.sys[off:off + n])))

    def _putn(self, off, nbytes, seg=None):
        """A COUNT-DERIVED span at an already-resolved offset. Refuses rather than clamping - an
        overrun here is evidence the count is misread, and a clamped misread is a fill."""
        if off is None or nbytes <= 0:
            return
        if seg == 'gfx' or (seg is None and off >= self.nsys):
            o = off - self.nsys if off >= self.nsys else off
            if o + nbytes <= self.ngfx:
                self.gfxr.append((o, bytes(self.res.gfx[o:o + nbytes])))
        elif off + nbytes <= self.nsys:
            self.sysr.append((off, bytes(self.res.sys[off:off + nbytes])))

    def _res(self, tagged, nbytes=1):
        """Resolve a tagged pointer, returning (buffer, offset, which-segment)."""
        buf, off = self.res.deref(tagged, nbytes)
        if buf is None:
            return None, None, None
        return buf, off, ('gfx' if buf is self.res.gfx else 'sys')

    def _flat(self, tagged, nbytes):
        buf, off, seg = self._res(tagged, max(nbytes, 1))
        if buf is None:
            return
        if seg == 'gfx':
            if off + nbytes <= self.ngfx:
                self.gfxr.append((off, bytes(buf[off:off + nbytes])))
        elif off + nbytes <= self.nsys:
            self.sysr.append((off, bytes(buf[off:off + nbytes])))

    def _drawable(self, base):
        s = self.res.sys
        if base in self._seen:
            return
        self._seen.add(base)
        self._put(base, DRAWABLE_SPAN)
        self._flat(struct.unpack_from('<I', s, base + 0x10)[0], 0x40)     # shader group hdr
        self._texdict(struct.unpack_from('<I', s, base + 0x10)[0])        # embedded textures
        # +0xA8 drawable NAME string (a plain cstr; NULL on 100% of fragment children) and
        # +0xC8 the EMBEDDED phBOUND graph. Measured 2026-08-13 over 20 files: these two slots
        # reach the start of an unmodelled run in 17/20 and 10/20 respectively - between them,
        # the whole remaining system-segment gap.
        self._flat(struct.unpack_from('<I', s, base + 0xA8)[0], 64)
        self._bound(struct.unpack_from('<I', s, base + 0xC8)[0])
        # ⭐ FINAL SWEEP: enter the reachable graph from EVERY tagged pointer in the drawable
        # header. The named walks above model the structures we UNDERSTAND; this catches the
        # subtree the pointer-site scan proved we were never entering. Runs last so the typed
        # walks claim their regions first and this only picks up what they left.
        for q in range(0, DRAWABLE_SPAN, 4):
            if base + q + 4 > self.nsys:
                break
            try:
                self._chase(struct.unpack_from('<I', s, base + q)[0])
            except struct.error:
                break
        self._flat(struct.unpack_from('<I', s, base + 0x18)[0], 0x80)     # skeleton hdr
        self._skeleton(base)                                              # ...and its ARRAYS
        self._shaders(base)                                               # grmShaderGroup, TYPED
        n = struct.unpack_from('<H', s, base + 0xB8)[0]                   # lights
        if 0 < n < 4096:
            self._flat(struct.unpack_from('<I', s, base + 0xB0)[0], n * 0xA8)
        for slot in LOD_SLOTS:
            try:
                self._lod(struct.unpack_from('<I', s, base + slot)[0])
            except struct.error:
                pass

    def _pagemap(self):
        """`resource+0x08` -> THE BLOCK MAP: a 16-byte header plus one 8-byte record per page.

            +0x00 u32 / +0x04 u32 ..... zero in 360/360
            +0x08 u8 SYSTEM page count | +0x09 u8 GRAPHICS page count
            +0x10 .. one 8-byte record per page, `sysPages + gfxPages` of them

        ⛔⛔ WHY THIS EXISTS: `write()` used to OVERWRITE the +0x08 word with a value recomputed
        from the RSC7 flags, and on the files where the two agreed that write was reproducing an
        allocation NOTHING HAD READ. Removing the write exposed them: 7 of a 250-file `.ydd` draw
        went from "byte-exact" to one byte short, and in 7 of 7 the ENTIRE block-map allocation
        (48-224 bytes) was uncovered - only its single non-zero byte ever showed as a difference,
        because the comparison image is zero-filled. A computed value was standing in for a
        structure the model had never visited.
        ⭐ THE SIZE LAW IS PINNED BY THE ALLOCATION ITSELF, measured 2026-08-14 over 120 files of
        EACH lane drawn from the game (360 total, sample size printed by the probe):
            `16 + 8 * (sysPages + gfxPages)` fits inside the room to the next allocation  360/360
            ... and equals that room EXACTLY                                              266/360
            every byte between the computed end and the next allocation is ZERO           360/360
        The 94 that are not exact are padding to the next 16-byte boundary, and it is zero - so
        the arithmetic is confirmed by the extent in 266 cases and contradicted in none.
        ⚠ HONEST ABOUT WHAT IS AND IS NOT KNOWN: the per-page records are ZERO throughout this
        sample, so their 8-byte stride is pinned by the ALLOCATION EXTENT and not by content -
        this claims the block map's size, not a reading of its records. The padding beyond the
        computed end is deliberately NOT claimed.
        ⛔ The array span is COUNT-DERIVED, so it goes through `_putn` (refuses on overrun) while
        the fixed 16-byte header goes through `_put` - the split this module draws on evidence.
        """
        try:
            buf, o = self.res.deref(self.res.ptr(0x08), 16)
        except (struct.error, IndexError):
            return
        if buf is not self.res.sys:
            return
        self._put(o, 16)
        try:
            n = self.res.sys[o + 8] + self.res.sys[o + 9]
        except IndexError:
            return
        if 0 < n <= 512:
            self._putn(o + 16, n * 8)

    def _bound(self, tagged, depth=0):
        """The drawable's EMBEDDED collision graph at +0xC8 - the same phBound structure
        `ybn_write` walks, so the offsets are shared rather than re-derived:
          type u8  @+0x10 : 0 sphere · 1 capsule · 3 box · 4 geometry · 8 geometry-BVH ·
                            10 composite · 13 cylinder     (record size per type: BOUND_SPAN_*)
          composite: u16 child count @+0xA0 · children @+0x70 · transforms @+0x78 · flags @+0x90
                     BVH block @+0xA8 (optional)
          geometry : nverts @+0xD0 · npolys @+0xD4 · nmat u8 @+0x120 · nmatcol u8 @+0x121 ·
                     verts @+0xB0 · polys @+0x88 · materials @+0xF0 · poly-materials @+0x118 ·
                     vertex colours @+0xB8 · material colours @+0xF8 · BVH block @+0x130 (type 8)

        ⛔⛔ SUPERSEDED 2026-08-14 (THIRD PASS) - THE PARAGRAPH BELOW IS CORRECT AND ASKS THE
        WRONG QUESTION, which is why it is kept rather than deleted. Every search it records was
        for a LENGTH: a field stating how many extra records there are. There is none, and there
        does not need to be - the records IDENTIFY THEMSELVES as copies of this mesh's own
        counted triangles. `_polytail` reads them by content and closes the class: +33 `.ydr`
        and +6 `.yft` byte-exact at population, 0 regressions, control false-fire 0.043%.
        ⭐ THE TRANSFERABLE LESSON: three rigorous negatives on "where is the length stored" were
        all correct and all beside the point. When every denominator says NO, check whether the
        question is the one the format answers.

        ⏭ CHARACTERISED, NOT CLOSED - THE POLYGON ARRAY'S TRAILING SLACK. On 39 of 834 geometry
        bounds (300 files) the polygon allocation runs 1-5 records past `npolys * 16` and stops
        exactly where the next allocation starts; the extra records are well-formed polygons
        (`float area, u16 v0, v1, v2, 0xffff, 0xffffffff`). This is the whole of the 13/16/32/48/
        64-byte residual class in BOTH `.ydr` and `.yft`.
        ⭐ THE BVH SAYS THE EXTRAS ARE UNUSED: over the subjects, `max(first + count)` across all
        BVH leaf nodes equals `npolys` EXACTLY (793/793, 2699/2699, 1305/1305, 3539/3539) while
        the allocation holds 795 / 2703 / 1306 / 3544 records. So they are reserved-but-unreferenced
        slots, the same shape as the BVH node capacity slack.
        ⛔ RULED OUT, with the search that failed: no field states the real count. Searched every
        u16 (step 2) and u32 (step 4) in the bound record 0x000..0x220, and a 4/8/12/16/20/24/32
        -byte allocation prefix in front of the array, over all 39 cases - **ZERO hits**. Claiming
        the slack would be filling from one region's end to the next region's start, which is the
        one move this measure exists to catch. Left unclaimed on purpose.
        """
        if not tagged or depth > 16:
            return
        s = self.res.sys
        _b, off, seg = self._res(tagged, 0x180)
        if off is None or seg != 'sys' or off in self._seen:
            return
        self._seen.add(off)
        btype = s[off + 0x10] if off + 0x11 <= self.nsys else 0xFF
        # THE RECORD'S OWN CLASS IDENTITY picks the field map - see BOUND_FIELDS_OLDBUILD.
        vtable = struct.unpack_from('<I', s, off)[0] if off + 4 <= self.nsys else 0
        fld = (BOUND_FIELDS_OLDBUILD
               if btype == 8 and vtable in BOUND_VTABLE_OLDBUILD else BOUND_FIELDS_STD)
        # ⭐ THE BOUND LIST IS RECORDED HERE, NOT RECOVERED FROM `_seen`. `_seen` is shared with
        # `_drawable` and the blind walk, so it holds offsets that are not bounds at all; a
        # post-pass that re-derived "which of these is a bound" would be a second, weaker
        # discriminator beside the one this method already applied. See `_polytail`.
        self._bounds.append((off, btype, fld))
        self._put(off, fld['span'] if btype == 8
                  else BOUND_SPAN_BY_TYPE.get(btype, BOUND_SPAN_DEFAULT))
        self._octant_map(off)
        try:
            nverts = struct.unpack_from('<I', s, off + fld['nverts'])[0]
            npolys = struct.unpack_from('<I', s, off + fld['npolys'])[0]
            nmat = s[off + fld['nmat']]
        except (struct.error, IndexError):
            return
        # ⭐⭐ THE TYPE CODE IS THE DISCRIMINATOR; THE RANGE CHECKS ARE ONLY A SECOND GATE.
        # `was:` geometry decided purely by "do the counts look plausible". A plausibility test is
        # not a discriminator: the `.ybn` agent measured `cs2_04_0.ybn`, whose ROOT COMPOSITE reads
        # nverts 3 / npolys 589,832 / nmat 179 - every one inside the plausible window - so the
        # walker took a composite for a geometry bound and, because every composite read sits
        # behind `not geom`, SILENTLY SKIPPED that root's per-child AABB array and its BVH block.
        # ⚠ This matters MORE here than in `.ybn`: a drawable's embedded graph also carries Box,
        # Sphere, Capsule, Disc, Cylinder and Cloth bounds, so `not geom` covers many more types.
        # TYPE u8 @ +0x10: 4 = geometry, 8 = geometry-BVH, 10 = composite. VERIFIED on this lane
        # against the vtable, which is an independent witness: every bound whose `+0x130` held a
        # law-passing BVH block read type 8 and vtable 0x4062fae8, and every bound whose `+0xA8`
        # did read type 10 and vtable 0x4062bac8 (5 subjects, 7 blocks, no exceptions).
        geom = (btype in (4, 8)
                and 0 < nverts <= 0x8000 and 0 < npolys <= 0x100000 and nmat)
        if geom:
            self._flat(struct.unpack_from('<I', s, off + 0xB0)[0], nverts * 6)
            self._flat(struct.unpack_from('<I', s, off + 0x88)[0], npolys * 16)
            self._flat(struct.unpack_from('<I', s, off + fld['mats'])[0], nmat * 8)
            self._flat(struct.unpack_from('<I', s, off + fld['polymat'])[0], npolys)
            # ⭐ +0xB8 VERTEX COLOURS (nverts * 4) and +0xF8 MATERIAL COLOURS (u8 @+0x121 * 4).
            # Both were already decoded by `ydr2xml` and never wired into this writer - pointers
            # held and never followed, which is the one signature that has closed every gap in
            # this campaign. ⚠ THE TWO SIGNAL ABSENCE DIFFERENTLY: vertex colours have no count of
            # their own (the vertex count is always non-zero), so a NULL POINTER is what says the
            # array is absent; material colours carry their own count at +0x121, which is 0 when
            # they are absent. `_flat` already refuses a null pointer, so both are safe as written.
            self._flat(struct.unpack_from('<I', s, off + 0xB8)[0], nverts * 4)
            nmatcol = (s[off + fld['nmatcol']]
                       if off + fld['nmatcol'] + 1 <= self.nsys else 0)
            if nmatcol:
                self._flat(struct.unpack_from('<I', s, off + fld['matcol'])[0], nmatcol * 4)
            # ⭐ +0x78 ON A **GEOMETRY** BOUND IS A SECOND VERTEX ARRAY (nverts * 6), not the
            # composite child-transform array the block below reads it as. The two readings never
            # collide because they are gated by opposite discriminators - this one by the geometry
            # test above, that one by a live child count at +0xA0 - but the slot was previously
            # ONLY ever read as a composite's transforms, so on a geometry bound it was never
            # followed at all. Same shape as the main vertex array: 3 x i16 per vertex.
            # MEASURED over 150 files / 1,982 non-composite bounds carrying a live +0x78:
            #     +0x78 resolves to a DIFFERENT address than +0xB0 (the main array) ..... 1,979
            #     nverts * 6 fits the measured room to the next pointer target .......... 1,976
            #     +0x78 aliased to +0x80 (i.e. a mis-typed composite slot) ..............     0
            # ⭐ It lives HERE, in the walker `ydr_write`/`ydd_write`/`yft_write` share and
            # `ybn_write` mirrors, so all four lanes get it from one derivation - .ybn is 15,139
            # collision-only files where this slot costs far more than it does under a drawable.
            self._flat(struct.unpack_from('<I', s, off + 0x78)[0], nverts * 6)
        # ⛔⛔ REMOVED 2026-08-14 - THE `+0x130` "ARRAY DESCRIPTOR WITH RECORDS INLINE AT +0x20"
        # WAS REFUTED, NOT MERELY INCOMPLETE. `was:` `_put(d, 0x20)` then `_putn(d + 0x20,
        # cnt * 16)` plus `_flat(ptr@d, cnt * 16)`. The `.ybn` agent measured the descriptor's own
        # pointer against `d + 0x20` over 901 blocks in 268 files and it matched in **0 of 901** -
        # `+0x20` is a bounding BOX, not a record array. The claim it licensed took
        # **5,563,920 bytes across two samples of which only 47,136 lay inside the structure**,
        # i.e. 99.2% claimed on no basis, and it could not fail: the image copies the ORIGINAL
        # bytes at whatever offset is claimed, so an unpinned claim is self-fulfilling.
        # ⇒ It is replaced by `_bvh` below, which reads the real 0x80-byte block and refuses
        # unless four independent laws hold. See `_bvh` for the laws and the evidence.
        # ⛔ THE SLOT IS READ ONLY WHERE THE RECORD HAS ONE. A plain geometry bound (type 4) is
        # 0x130 bytes, so `+0x130` is the FIRST BYTE PAST IT - reading a BVH pointer there would be
        # reading the neighbour. Only type 8 carries the slot inside its 0x150 record.
        if btype == 8:
            self._bvh(struct.unpack_from('<I', s, off + fld['bvh'])[0]
                      if off + fld['bvh'] + 4 <= self.nsys else 0)
        # ⭐ A COMPOSITE CARRIES THE SAME BLOCK AT +0xA8, and it is OPTIONAL - 48 of 268 composites
        # in the `.ybn` sample have one. There is no flag saying which: the FOUR LAWS in `_bvh`
        # tell the cases apart, and a composite without one simply fails law 1 or 2 and is refused.
        # ⛔ That is the whole reason `_bvh` validates instead of trusting the slot - the same call
        # is made on every bound and only the real blocks are ever claimed.
        if btype == 10:
            self._bvh(struct.unpack_from('<I', s, off + 0xA8)[0]
                      if off + 0xAC <= self.nsys else 0)
        try:
            n = struct.unpack_from('<H', s, off + 0xA0)[0]
            carr = struct.unpack_from('<I', s, off + 0x70)[0]
            self._flat(carr, n * 8)
            self._flat(struct.unpack_from('<I', s, off + 0x78)[0], n * 64)
            self._flat(struct.unpack_from('<I', s, off + 0x90)[0], n * 8)
            # ⭐ +0x88 ON A **NON-GEOMETRY** BOUND IS A PER-CHILD AABB ARRAY, n * 32 - one
            # {vec3 min, u32}{vec3 max, float} pair per child. On a GEOMETRY bound the same slot
            # is the polygon array (read above, sized by npolys), so the two readings are gated by
            # opposite discriminators and cannot collide - which is exactly why this one was never
            # reached: a composite's +0x88 was only ever interpreted as polygons, and a composite
            # has none.
            # MEASURED over BOTH samples (250 .ydr + 147 .ybn, scratchpad/probe_childaabb.py):
            #   non-geometry bounds with a live +0x88 and a valid child count ...... 255
            #   n * 32 fits the segment, of those that resolve ................. 246 / 246
            #   aliased to the child-pointer array (+0x70) or the transforms (+0x78) .... 0
            #   currently uncovered ...................... 94 bounds, 13,536 bytes
            # Worked example, prop_off_chair_01 bound 0x0191c0: nverts/npolys/nmat all 0, child
            # count u16 @+0xA0 = 16, +0x88 -> 0x018fc0, and the block runs to 0x0191c0 = 512 B
            # = 16 x 32 EXACTLY. Records alternate sign-flipped vec3 pairs, i.e. min/max boxes.
            if not geom and 0 < n <= 4096:
                self._flat(struct.unpack_from('<I', s, off + 0x88)[0], n * 32)
        except struct.error:
            return
        if not n or n > 4096:
            return
        _b3, coff, cseg = self._res(carr, n * 8)
        if coff is None or cseg != 'sys':
            return
        for i in range(n):
            try:
                cp = struct.unpack_from('<I', s, coff + i * 8)[0]
            except struct.error:
                break
            if cp:
                self._bound(cp, depth + 1)

    # ------------------------------------------------------------------ the polygon tail
    def _coverage_map(self):
        """A byte map of everything the SYSTEM-segment walk has claimed so far."""
        cov = bytearray(self.nsys)
        for off, data in self.sysr:
            if off is not None and data:
                cov[off:off + len(data)] = b'\x01' * len(data)
        return cov

    def _polytail(self):
        """THE RECORDS PAST `npolys` ARE THIS MESH'S **REMOVED DUPLICATE TRIANGLES**.

        ⭐ PORTED FROM `ybn_write._polytail`, WHERE IT WAS DERIVED AND CONTROLLED. Two changes,
        both forced by this family carrying structures `.ybn` does not:
          * the type gate is `4 or 8`, not `8`. Over all 71,912 bounds in the `.ybn` population,
            type 4 (plain phBoundGeometry) occurs ZERO times; here it is the majority geometry
            type in a vehicle fragment. Six of this lane's own population failures sit on one.
          * `nverts`/`npolys`/`nmat` come from the per-bound FIELD MAP (`BOUND_FIELDS_OLDBUILD`
            shifts them by 8), because this family has an older-build phBoundGeometryBVH that
            `.ybn` never sees. The polygon pointer is `+0x88` in both maps - `_bound` already
            reads it unconditionally there.
        ⛔ NOTHING ELSE WAS RE-DERIVED. The record layout is `ybn_write._PRIM_SLOTS`, imported.

        THE REFRAME THAT MADE IT WORK, because five passes of "where is the length stored"
        answered correctly and beside the point: the surplus is not an unknown-length run to be
        SIZED, it is a set of records that IDENTIFY THEMSELVES. Each is a triangle this mesh
        already carries inside `npolys`. You recognise contents; you never size the array. That
        is why the rule is the same one here even though the containers differ.

        THE RULE, and every clause can refuse. A record at `po + j*16`, j >= `npolys`, is claimed
        only while ALL of these hold, and the walk stops at the FIRST record that fails:
            1. no byte of it is already claimed by another MODELLED structure
            2. it is not all zero
            3. its primitive kind (`byte0 & 7`) is one the format defines
            4. its vertex indices (low 15 bits - the 0x8000 bit is a flag) are all < `nverts`
            5. TRIANGLES: all three NEIGHBOUR indices at +0x0A are 0xFFFF, i.e. the record is
               OUTSIDE the mesh's adjacency graph
            6. TRIANGLES: its vertex triple, sorted, is one THIS bound's counted triangles carry
               OTHER PRIMITIVES: the 16 bytes are byte-identical to a counted record

        ⭐⭐ THE ADJACENCY LAW CLAUSE 5 RESTS ON, and it was previously mis-scored as noise: over
        the `.ybn` population's 54,807 exactly-sized arrays the largest neighbour index is NEVER
        >= `npolys` - **0 of 54,807** - ONCE THE 0x8000 INDEX FLAG IS MASKED. An earlier pass
        reported it "fires 25.7%" and discarded it; it had not masked the flag. It is a format
        LAW: the field reaches the top of the array and would have exposed a longer one.

        ⭐⭐ WHAT IT SCORES **ON THIS FAMILY** (`scratchpad/dq6_rule.py`), on a uniform mod-40
        draw of the whole game - 14,780 cached drawables, 8,607 `.ydr` + 6,173 `.yft`. Both the
        blind walk AND this method are disabled while the baseline coverage is built, or the
        probe would be scoring its own claims:
            NEGATIVE CONTROL - **7,052 polygon arrays** whose 16 bytes at `npolys*16` are not a
            subject, i.e. where the right answer is known to be REFUSE:
                the SHIPPED rule accepts ........................ 3 / 7,052 (**0.043%**)
                the same rule WITHOUT clauses 5 and 6 accepts ... 4,306 / 7,052 (**61.06%**)
            ⇒ a 1,435x discrimination, and it is entirely the two clauses that ask whether the
              record belongs to THIS mesh. 0.043% is also the rate the rule has on `.ybn`
              (0.04%) - the same number in a different container, which is what "the rule is
              about the RECORD, not the container" predicts.
            SUBJECTS - 15 allocations with non-zero content past `npolys*16` (bound types 8: 9,
            4: 6): 31 records / 496 bytes claimed, reaches the allocation end exactly on 13,
            stops short on 2, runs PAST an allocation on **0**.
          ⚠ THE SUBJECT COUNT IS 15 HERE AND WAS 85 BEFORE THIS PASS. The other 70 were never
            polygon surplus: 61 are `fragTypeChild +0xB0` records and 9 are the
            `fragPhysicsLOD +0xC8` array, both now modelled in `yft_write` at their own named
            slots. They only LOOKED like a tail because the packer put them straight after a
            polygon array - see `yft_write._child`.
        ⚠ WHAT THIS IS NOT. It does not recover the array's ALLOCATED LENGTH. That number is not
        in the file (`ybn_write` REMAINING GAP lists five search spaces with their denominators),
        and where the allocation is longer than the records it can pin, the remainder stays in
        the residual rather than being filled to the next structure.
        ⛔ IT RUNS BEFORE `_flush_chase`. Clause 1 must mean "another modelled structure", and a
        blind 0x1000-byte window is not one - see `__init__`.
        """
        s = self.res.sys
        cov = self._coverage_map()
        for off, btype, fld in self._bounds:
            if btype not in (4, 8):
                continue
            try:
                nverts = struct.unpack_from('<I', s, off + fld['nverts'])[0]
                npolys = struct.unpack_from('<I', s, off + fld['npolys'])[0]
                nmat = s[off + fld['nmat']]
                pp = struct.unpack_from('<I', s, off + 0x88)[0]
            except (struct.error, IndexError):
                continue
            # the SAME discriminator `_bound` uses to decide "this is a geometry bound"
            if not (0 < nverts <= 0x8000 and 0 < npolys <= 0x100000 and nmat):
                continue
            if npolys > 0x40000:
                continue                 # the counted sets below would be unbounded - refuse
            _b, po, seg = self._res(pp, 16)
            if po is None or seg != 'sys' or po + npolys * 16 > self.nsys:
                continue
            # ⭐ THE COUNTED SETS ARE BUILT ONLY ONCE THE CHEAP CLAUSES HAVE PASSED. They are
            # O(npolys) and this family carries millions of counted polygons; building them
            # unconditionally would cost the lane several times its runtime to answer a question
            # that is 'no' on the overwhelming majority of arrays before it is asked.
            triples = recs = None
            claimed = []
            j = npolys
            while True:
                a = po + j * 16
                if a + 16 > self.nsys or any(cov[a:a + 16]):            # 1
                    break
                r = bytes(s[a:a + 16])
                if not any(r):                                          # 2
                    break
                t = r[0] & 7
                if t not in ybn_write._PRIM_SLOTS:                      # 3
                    break
                try:
                    v = tuple(struct.unpack_from('<H', s, a + k)[0] & 0x7FFF
                              for k in ybn_write._PRIM_SLOTS[t])
                except struct.error:
                    break
                if max(v) >= nverts:                                    # 4
                    break
                if t == 0:
                    try:
                        nb = struct.unpack_from('<3H', s, a + 0x0A)
                    except struct.error:
                        break
                    if nb != (0xFFFF, 0xFFFF, 0xFFFF):                  # 5
                        break
                    if triples is None:
                        triples = set()
                        for i in range(npolys):
                            o = po + i * 16
                            if s[o] & 7:
                                continue
                            w = struct.unpack_from('<3H', s, o + 4)
                            triples.add(tuple(sorted((w[0] & 0x7FFF, w[1] & 0x7FFF,
                                                      w[2] & 0x7FFF))))
                    if tuple(sorted(v)) not in triples:                 # 6
                        break
                else:
                    if recs is None:
                        recs = set(bytes(s[po + i * 16:po + i * 16 + 16])
                                   for i in range(npolys))
                    if r not in recs:                                   # 6'
                        break
                claimed.append(a)
                j += 1
            for a in claimed:
                self._putn(a, 16)
                cov[a:a + 16] = b'\x01' * 16
            if not claimed:
                continue
            self._polyclaim[off] = npolys + len(claimed)
            # ⭐⭐ ONE MATERIAL BYTE PER POLYGON RECORD - SO THE MATERIAL ARRAY IS SIZED BY
            # `nclaim`, NOT BY `npolys`. `_bound` claims it as exactly `npolys` bytes; the
            # records `_polytail` just recovered have material bytes too, and they are the
            # 1-5 byte residual that was left in a dozen files after the polygon tail closed.
            # ⭐ WHY IT IS PINNED AND NOT A FILL: the LENGTH COMES FROM A DIFFERENT ARRAY, at a
            # different pointer, recovered by a rule that never looked at these bytes. A wrong
            # record count gives a wrong tail length, so the extent can disagree - and does not.
            #   ON THE POPULATION FAILURES (`scratchpad/dq6_pm.py`, 45 files): 14 residual runs
            #   sit at a material-array tail and the run length equals `nclaim - npolys` on
            #   13 of 14 - the 14th needs 8 bytes and shows 1 because the other 7 are zero.
            #   ON THE UNIFORM mod-40 DRAW (`scratchpad/dq6_pmtail.py`, 14,780 drawables):
            #     subjects (a surplus was pinned) ......................... 13 arrays
            #       the extra claim FITS before the next modelled structure .. 13 / 13
            #       it OVERRUNS one ........................................... 0
            #       last NON-ZERO byte after `npolys` lies inside it ......... 13 / 13
            # ⭐ ITS CONTROL FALSE-FIRE RATE IS `_polytail`'s, BY CONSTRUCTION. The extension
            # fires only where a surplus was pinned, so on the 5,498 exactly-sized polygon
            # arrays in that draw the claim is unchanged at `npolys` - it cannot fire at all.
            # ⚠ THAT SPLIT MATTERS: 89 of those 5,498 controls (1.6%) do carry a non-zero byte
            # immediately after `pm + npolys`, so "extend the material array wherever the next
            # byte is non-zero" WOULD have false-fired. Tying the length to the pinned record
            # count is what makes the difference.
            # ⚠ NOT CLAIMED, deliberately: `ybn_write._polymat_pad`'s 16-BYTE ALLOCATION
            # ROUNDING. That padding is zero, so claiming it cannot be scored - it would be
            # exactly the unpinned, self-fulfilling claim this measure exists to catch.
            try:
                mp = struct.unpack_from('<I', s, off + fld['polymat'])[0]
            except (struct.error, IndexError):
                continue         # the record is truncated at the segment end - REFUSE
            _b, pm, pseg = self._res(mp, 1)
            if pm is None or pseg != 'sys':
                continue
            extra = len(claimed)
            if pm + npolys + extra > self.nsys or any(cov[pm + npolys:pm + npolys + extra]):
                continue                 # REFUSE rather than clamp - see `_putn`
            self._putn(pm + npolys, extra)
            cov[pm + npolys:pm + npolys + extra] = b'\x01' * extra

    def _bvh(self, tagged):
        """phBound `+0x130` (geometry) / `+0xA8` (composite) -> THE BVH BLOCK, 0x80 bytes.

            +0x00 u64 ptr -> nodes | +0x08 u32 count | +0x0C u32 CAPACITY | +0x10 16 zero bytes
            +0x20 vec4 box min | +0x30 vec4 box max | +0x40 vec4 box centre
            +0x50 vec4 scale-INVERSE | +0x60 vec4 scale
            +0x70 u64 ptr -> trees | +0x78 u16 count | +0x7A u16 capacity
        Both arrays hold 16-byte records: a node is `{i16 min[3], i16 max[3], u32}` - the
        quantised AABB the +0x50/+0x60 scale pair decodes.

        ⭐⭐ FOUR LAWS, EACH ABLE TO REFUSE - derived by the `.ybn` agent over 901 blocks in 268
        files and RE-CONFIRMED HERE before use (see below):
          1. `+0x10 .. +0x20` is all zero ......................................... 901/901
          2. `scale[k] * scaleinv[k] == 1` (+/-1e-3) for k in 0..2 ................ 901/901
             - a reciprocal pair no box reading produces by accident
          3. `(max-min)[k] * scaleinv[k] == 65535` (+/-1%) ....................... 901/901
             - pins the BOX and the 16-bit quantisation together
          4. tree count == tree capacity ......................................... 901/901
        ⭐ RE-CONFIRMED ON THIS LANE before adopting the structure: a blind scan of five `.ydr`
        subjects for any 16-byte-aligned offset satisfying all four laws found 1, 1, 3, 1 and 1
        blocks respectively, EVERY ONE of them the target of exactly ONE tagged pointer, and every
        one of those pointer sites at either bound `+0x130` or bound `+0xA8`:
            ba_rig_dj_01_lights_03_b  blk 0x2c38c0  site 0x27fd80 = bound 0x27fc50 + 0x130
                                                    (bound vtable 0x4062fae8, type u8 @+0x10 = 8)
            tr_prop_tr_mod_lframe_01a blk 0x0bff80  site 0x07ffd8 = bound 0x07ff30 + 0x0A8
                                                    (bound vtable 0x4062bac8, type = 10)
        i.e. the two slots are the BVH-geometry one and the COMPOSITE one, and the vtable and the
        type byte agree with the slot in every case. That is why this is adopted rather than
        trusted.
        ⭐ THE NODE ARRAY IS SIZED BY **CAPACITY**, NOT COUNT (`+0x0C`, not `+0x08`). Worked
        example, gr_prop_bunker_bed_01: count 51, capacity 53; the unreached run measured 845
        bytes inside a 848 = 53 x 16 allocation, and 51 x 16 = 816 cannot reach it. The surplus
        records hold the uninitialised inverted box `01 80 01 80 01 80 ff 7f ff 7f ff 7f` -
        min = +32767, max = -32767 - which is what a reserved-but-unused node looks like.
        `capacity - count` is only ever 0, 1 or 2 over the 901 blocks.
        ⛔ Both arrays are COUNT-DERIVED spans, so they go through `_flat`, which REFUSES on
        overrun rather than clamping - a span that cannot fit proves the count is misread.
        """
        if not tagged:
            return
        s = self.res.sys
        _b, d, seg = self._res(tagged, 0x80)
        if d is None or seg != 'sys':
            return
        try:
            if any(s[d + 0x10:d + 0x20]):                       # LAW 1
                return
            mn = struct.unpack_from('<4f', s, d + 0x20)
            mx = struct.unpack_from('<4f', s, d + 0x30)
            si = struct.unpack_from('<4f', s, d + 0x50)
            sc = struct.unpack_from('<4f', s, d + 0x60)
            nptr = struct.unpack_from('<I', s, d + 0x00)[0]
            ncap = struct.unpack_from('<I', s, d + 0x0C)[0]
            ncnt = struct.unpack_from('<I', s, d + 0x08)[0]
            tptr = struct.unpack_from('<I', s, d + 0x70)[0]
            tcnt = struct.unpack_from('<H', s, d + 0x78)[0]
            tcap = struct.unpack_from('<H', s, d + 0x7A)[0]
        except (struct.error, IndexError):
            return
        if tcnt != tcap:                                        # LAW 4
            return
        for k in range(3):
            if not (0.999 <= sc[k] * si[k] <= 1.001):           # LAW 2
                return
            if not (64879.65 <= (mx[k] - mn[k]) * si[k] <= 66190.35):   # LAW 3 - 65535 +/-1%
                return
        if not (0 < ncap <= 0x200000) or ncap < ncnt:
            return
        self._put(d, 0x80)
        self._flat(nptr, ncap * 16)
        if 0 < tcnt <= 0x200000:
            self._flat(tptr, tcnt * 16)

    def _cstr(self, tagged, limit=256):
        """Capture EXACTLY one NUL-terminated string, terminator included.

        ⛔ NOT a fixed window. A flat 64-byte capture at a name pointer claims up to 63 bytes it
        never read; measuring the terminator claims only the string. Refuses a run with no NUL
        inside `limit` rather than capturing a guess.
        """
        if not tagged:
            return
        buf, off, seg = self._res(tagged, 1)
        if buf is None:
            return
        end = buf.find(b'\x00', off, off + limit)
        if end < 0:
            return
        self._put(off, end - off + 1, seg)

    def _octant_map(self, off, n=8):
        """phBound +0xC0 / +0xC8 - THE OCTANT MAP, and it is SELF-DESCRIBING.

            +0xC0 -> u32 counts[8]
            +0xC8 -> u64 pointer table[8], entry k -> a u32 index array of counts[k] elements

        ⭐ FOUND BY ASKING WHICH MODELLED SITE HELD A POINTER INTO THE GAP, not by guessing a
        stride. The sites landed at +0xC0 and +0xC8 of a 0x180-byte region - i.e. a phBound header
        - on every file that still had a gap (scratchpad/probe_owner.py):
            v_corp_bk_bust      bound 0x01c040  +0xC0 -> 0x01bb40   +0xC8 -> 0x01bb60
            v_ilev_arm_secdoor  bound 0x00aff0  +0xC0 -> 0x00ae60   +0xC8 -> 0x00ae80
            p_amb_brolly_01_s   same pair, +0xC0/+0xC8, 8 bytes apart
        ⭐ THE ARITHMETIC IS THE EVIDENCE, and it is checked at run time rather than trusted:
        `ptr[k+1] - ptr[k] == counts[k] * 4` for all k, and the payload begins immediately after
        the table. Measured on v_corp_bk_bust, counts [26, 22, 40, 42, 13, 13, 14, 20]:
        104 = 26*4, 88 = 22*4, 160 = 40*4, 168 = 42*4, 52 = 13*4 ... seven independent equations
        that all have to hold before a single byte is claimed. A search over N = 2..32 matched
        ONLY N = 8, on 3 of 3 files that carried the shape - 8 octants.
        ⛔ NOTHING IS CLAIMED WHEN THE LAW FAILS. This is the opposite of filling from one
        region's end to the next region's start: the structure states its own extent and we check
        the statement before believing it, so a misread costs coverage rather than inventing it.
        ⚠ REACHABILITY WITH A NAME, not a full interpretation: the arrays are per-octant index
        lists and the law pins their EXTENT exactly, but what each index addresses is not claimed
        here. (`yft_write` names the same structure as its best-evidenced hypothesis and records
        it as NOT CLOSED because the sizing field was not pinned. This pins it.)
        """
        s = self.res.sys
        try:
            cp = struct.unpack_from('<I', s, off + 0xC0)[0]
            tp = struct.unpack_from('<I', s, off + 0xC8)[0]
        except struct.error:
            return
        if not cp or not tp:
            return
        _b1, cb, cseg = self._res(cp, n * 4)
        _b2, tb, tseg = self._res(tp, n * 8)
        if cb is None or tb is None or cseg != 'sys' or tseg != 'sys':
            return
        try:
            counts = [struct.unpack_from('<I', s, cb + k * 4)[0] for k in range(n)]
            ptrs = [struct.unpack_from('<I', s, tb + k * 8)[0] for k in range(n)]
        except struct.error:
            return
        if any((p >> 28) != 5 for p in ptrs) or any(c > 0x100000 for c in counts):
            return
        offs = [p & 0x0FFFFFFF for p in ptrs]
        if offs[0] != tb + n * 8:                                  # payload follows the table
            return
        if any(offs[k + 1] - offs[k] != counts[k] * 4 for k in range(n - 1)):
            return                                                 # THE LAW - checked, not assumed
        if offs[-1] + counts[-1] * 4 > self.nsys:
            return
        self._put(cb, n * 4)
        self._put(tb, n * 8)
        for k in range(n):
            self._putn(offs[k], counts[k] * 4)

    def _alloc_prefix(self, tagged, count):
        """A 16-byte ALLOCATION PREFIX in front of an array, whose first u32 is its ELEMENT COUNT.

        ⭐ SELF-VALIDATING BY CONSTRUCTION, and that is the entire point. The prefix is claimed
        ONLY when the u32 at `base - 16` equals a count we already derived from a DIFFERENT field
        (the skeleton header). Claiming `base - 16` unconditionally would be exactly the
        fill-to-the-neighbour move this measure exists to catch - so the guard is not a safety
        belt, it is the evidence.

        MEASURED 2026-08-14 over the 109 skeleton-bearing drawables in the 250-file .ydr sample
        (scratchpad/probe_prefix.py), per slot rather than as a blanket law:
            skel+0x20 bone array   u32 @ B-16 == bone count ....... 109/109
                                   trailing 12 bytes all zero ..... 109/109
            skel+0x28 / +0x30 / +0x38 ........................ DIFFERS 109/109
            skel+0x40 child indices .......................... DIFFERS  25/25
        So only the bone array is prefixed; the others are packed adjacently and `B-16` there is a
        NEIGHBOUR'S TAIL. ⭐ This independently reproduces `ydd_write`'s finding on a different
        lane and a different sample (true 73/73 for the bone array, 219 mismatches for the other
        three) - two samples, two lanes, one law. It is applied to the one slot that earned it.
        """
        if not tagged or not count:
            return
        _b, off, seg = self._res(tagged, 1)
        if off is None or seg != 'sys' or off < 16:
            return
        try:
            if struct.unpack_from('<I', self.res.sys, off - 16)[0] == count:
                self._put(off - 16, 16)
        except struct.error:
            return

    def _skeleton(self, base):
        """`gtaDrawable+0x18` -> crSkeletonData, and the per-bone ARRAYS it points at.

        ⛔⛔ THIS MODULE USED TO CAPTURE THE 0x80-BYTE HEADER AND NOTHING ELSE. The arrays were
        reached only by the blind `_chase`, which takes its swept CHASE_CAPTURE window and stops -
        so every skeleton array was read for its first 4,096 bytes and the remainder counted
        against coverage. `ydd_write` and `yft_write` each hit this and each wrote their own
        `_skeleton`; the base class - the one both of them inherit - never had one.

        MEASURED 2026-08-14 on the 250-file .ydr sample (scratchpad/probe_skel.py), and the
        signature is unambiguous rather than fitted:
          109 of 250 drawables carry a skeleton; +0x20/+0x28/+0x30 resolve in 109/109.
          10 of those 109 had uncovered bytes, and in **10 of 10 the uncovered part began at
          EXACTLY `pointer + 0x1000`** - i.e. precisely where the chase window ran out. Total
          95,936 unreached bytes (43,200 bone records + 26,368 + 26,368 matrices).
          Worked example, des_vaultdoor001_root003: bones 0x04cd90 + 0x1000 = 0x04dd90, which is
          the gap run's start, and 0x1000 + 6,064 = 10,160 = 127 x 0x50 EXACTLY. Same for both
          matrix arrays (0x1000 + 4,032 = 8,128 = 127 x 0x40). The two matrix arrays are a
          rotation and its transpose - `93 1a 5a 39` against `93 1a 5a b9`, one float, sign bit
          flipped - which is what Transformations / TransformationsInverted must look like.

        ⭐ THE BONE COUNT IS u16 @+0x5E, NOT @+0x1A. Measured over the 109 skeletons: +0x1A is
        ZERO in 84 and equal to +0x5E in 25, and NEVER larger - it is the bone-tag MAP's entry
        count, which is 0 whenever the map is absent. +0x5E sizes all three arrays inside the
        segment in 109/109; +0x1A does so in only 25. (`ydd_write` reads +0x1A and cross-checks
        +0x5E, which is safe on the ped lane it measured - every ped skeleton carries a map - but
        would silently read ZERO bones on 84 of these 109 drawables. `yft_write` records the same
        correction.) ⛔ Never size a read from the field under test: the count comes from the
        HEADER, and the arrays it sizes are a different allocation.
        """
        s = self.res.sys
        try:
            sp = struct.unpack_from('<I', s, base + 0x18)[0]
        except struct.error:
            return
        buf, sk, seg = self._res(sp, 0x80)
        if buf is None or seg != 'sys':
            return
        try:
            nb = struct.unpack_from('<H', s, sk + 0x5e)[0]
            cap = struct.unpack_from('<H', s, sk + 0x18)[0]
            nmap = struct.unpack_from('<H', s, sk + 0x1a)[0]
            nchild = struct.unpack_from('<I', s, sk + 0x60)[0]
        except struct.error:
            return
        if 0 < nb <= 8192:
            ba = struct.unpack_from('<I', s, sk + 0x20)[0]
            self._flat(ba, nb * BONE_STRIDE)
            self._alloc_prefix(ba, nb)
            self._flat(struct.unpack_from('<I', s, sk + 0x28)[0], nb * 0x40)  # Transf. inverted
            self._flat(struct.unpack_from('<I', s, sk + 0x30)[0], nb * 0x40)  # Transformations
            self._flat(struct.unpack_from('<I', s, sk + 0x38)[0], nb * 2)     # ParentIndices
            # bone NAME strings live at bone_record+0x38, in their own block
            _bb, bao, bseg = self._res(ba, nb * BONE_STRIDE)
            if bao is not None and bseg == 'sys':
                for i in range(nb):
                    try:
                        self._cstr(struct.unpack_from('<I', s, bao + i * BONE_STRIDE + 0x38)[0])
                    except struct.error:
                        break
        if 0 < nchild <= 1 << 20:
            self._flat(struct.unpack_from('<I', s, sk + 0x40)[0], nchild * 2)  # ChildIndices
        # bone-tag hash map: `cap` u64 buckets, each the head of a chain of 16-byte nodes
        # {u32 key, u32 value, u64 next}. ⛔ Followed as a CHAIN with a visited set and a hop cap,
        # never by filling from the first node to the last - the nodes are SCATTERED, not an array.
        if 0 < cap <= 65536 and nmap:
            _tb, ta, tseg = self._res(struct.unpack_from('<I', s, sk + 0x10)[0], cap * 8)
            if ta is not None and tseg == 'sys':
                self._flat(struct.unpack_from('<I', s, sk + 0x10)[0], cap * 8)
                seen, hops = set(), 0
                for k in range(cap):
                    try:
                        node = struct.unpack_from('<I', s, ta + k * 8)[0]
                    except struct.error:
                        break
                    while node and hops < cap * 4:
                        _nb2, no, nseg = self._res(node, 16)
                        if no is None or nseg != 'sys' or no in seen:
                            break
                        seen.add(no)
                        hops += 1
                        self._put(no, 16)
                        try:
                            node = struct.unpack_from('<I', s, no + 0x08)[0]
                        except struct.error:
                            break

    def _shaders(self, base):
        """`gtaDrawable+0x10` -> grmShaderGroup -> shader blocks -> PARAMETER TABLE -> texture
        stubs -> their NAME strings. The typed read of the structure `_texdict` only ever probed.

        ⛔⛔ THIS MODULE HELD THE POINTER AND NEVER FOLLOWED IT. `_texdict` reads `sg+0x10` /
        `sg+0x20` as if each were an array DESCRIPTOR `{ptr @+0x00, u16 count @+0x08}`. `sg+0x10`
        is not a descriptor - it is the shader POINTER ARRAY itself, and its count is a separate
        field at `sg+0x18`. Worked example, `fur_hood_h.yft`: `sg` at 0x007e40 carries
        `ptr 0x007e80 | count 5` at +0x10/+0x18, and 0x007e80 is five 8-byte shader pointers.
        `_texdict` dereferenced 0x007e80 as the descriptor, so it read the SECOND pointer
        (0x50007ee0) as the count word, got 32,480, failed its `cnt > 4096` guard and captured
        nothing - the whole parameter subtree was left to the blind walk.

        LAYOUT - NOT re-derived. These are the offsets `ydr2xml.read_shaders` derived and
        validated (866 full-parameter reference exports; texture names 99.960%) and that
        `ydd_write` re-confirmed against raw bytes over 150 files / 341 shader groups:
            shader group +0x10 ptr -> shader array, +0x18 u16 count   (341/341 resolve)
            shader block  = 0x30 bytes (adjacent-offset stride 48 in 652/652 pairs)
                +0x00 ptr -> parameter table | +0x10 u32 low byte = param count
                +0x14 u16 = data size        | table + dsize = npar u32 name hashes
            param entry   = 16 bytes: byte 0 is the CLASS - 0 = texture, N>0 = N float4s at +0x08
            texture stub  = 0x50 bytes (adjacent stride 80 in 675 pairs)
                +0x28 ptr -> name cstr (printable in 1,828/1,828) | +0x30 u16 type word
        ⭐ THE THREE FIELDS CHECK EACH OTHER, which is why nothing here is a fitted span.
        `fur_hood_h.yft` shader 0 at 0x007eb0: `npar 27`, `dsize 800`, table 0x0169e0.
            27 entries x 16 B = 432 B of entry records ....... 0x0169e0 .. 0x016b8f
            the float4 blocks the entries point at = 368 B ... 0x016b90 .. 0x016cff
                (432 + 368 = 800 = dsize EXACTLY, so dsize is confirmed by the entries it sizes)
            npar x 4 = 108 B of joaat name hashes at table+dsize  0x016d00 .. 0x016d6b
        and the file's three unreached runs were 0x0169e8 (492 B), 0x016be7 (189 B) and 0x016d00
        (108 B) - i.e. exactly that span, to the byte. ⭐ One entry carries CLASS 2 and its
        pointer target is 32 bytes long: the next entry's target is 0x016cd0, not 0x016cc0. The
        class byte therefore SIZES the value block, which is what makes `cls * 16` a read rather
        than a guess.
        ⛔ `dsize` is the field that sizes the table, so it is bounded by an INDEPENDENT quantity
        (`npar * 16`) before it is trusted - never sized from itself.
        """
        s = self.res.sys
        try:
            sgp = struct.unpack_from('<I', s, base + 0x10)[0]
        except struct.error:
            return
        buf, sg = self.res.deref(sgp, 0x40)
        if buf is not s:
            return                      # ordinary: a child drawable carries no shader group
        self._put(sg, 0x40)
        try:
            arr = struct.unpack_from('<I', s, sg + 0x10)[0]
            nsh = struct.unpack_from('<H', s, sg + 0x18)[0]
        except struct.error:
            return
        if not (0 < nsh <= 4096):
            return
        self._flat(arr, nsh * 8)
        ab, ao = self.res.deref(arr, nsh * 8)
        if ab is not s:
            return
        for si in range(nsh):
            try:
                bp = struct.unpack_from('<I', s, ao + si * 8)[0]
            except struct.error:
                break
            bb, bo = self.res.deref(bp, 0x30)
            if bb is not s:
                continue
            self._put(bo, 0x30)
            try:
                npar = struct.unpack_from('<I', s, bo + 0x10)[0] & 0xFF
                dsize = struct.unpack_from('<H', s, bo + 0x14)[0]
                tp = struct.unpack_from('<I', s, bo + 0x00)[0]
            except struct.error:
                continue
            if not (0 < npar <= 96 and dsize >= npar * 16):
                continue
            self._flat(tp, dsize + npar * 4)     # entries + the trailing name-hash array
            tb, to = self.res.deref(tp, dsize + npar * 4)
            if tb is not s:
                continue
            for pi in range(npar):
                try:
                    cls = s[to + pi * 16]
                    ptr = struct.unpack_from('<I', s, to + pi * 16 + 8)[0]
                except (IndexError, struct.error):
                    break
                if cls:
                    if cls <= 64:
                        self._flat(ptr, cls * 16)        # cls float4s of value data
                    continue
                if not ptr:
                    continue                             # unbound sampler slot: nothing to read
                sb, so = self.res.deref(ptr, STUB_RECORD)
                if sb is not s:
                    continue
                self._put(so, STUB_RECORD)
                try:
                    self._cstr(struct.unpack_from('<I', s, so + 0x28)[0])
                except struct.error:
                    continue

    def _chase(self, tagged, depth=0):
        """Follow the REACHABLE POINTER GRAPH inside the shader/texture subtree.

        ⭐ WHY GENERIC RATHER THAN SLOT-BY-SLOT: the pointer-site scan proved the remaining gap is
        a SUBTREE - 15 of 21 pointers into it came from sites we had never entered - so fixing one
        named slot at a time moved coverage ~0.005% each (three attempts, three near-misses).
        Entering the graph and following what it actually points at unwinds every layer at once.
        Each newly entered node exposes the next, which is precisely the structure the scan showed.
        ⚠ This models REACHABILITY, not meaning: it proves the bytes belong to the drawable's own
        graph, not that we understand each field. Coverage earned this way is honest about
        completeness and silent about interpretation - the same caveat the whole measure carries.
        Bounded by a visited set and a depth cap so a cyclic or malformed graph terminates.

        ⛔⛔ THE ORDERING DEFECT THIS DEFERRAL FIXES - found in `.ydd`, then again in `.yft`, and
        present here the whole time. `_drawable`, `_bound` and `_chase` share ONE `_seen` set, and
        the blind walk used to run in the MIDDLE of `_drawable`'s own walk. A blind entry that
        landed on a record the TYPED walk had not reached yet put that offset in `_seen`, so when
        the typed walk arrived it returned immediately and **skipped that whole subtree silently**
        - LOD groups, models, geometries, vertex and index buffers, all unread, with no error and
        no unresolved pointer to show for it.
        MEASURED COST OF THE DEFECT ELSEWHERE, both on the same shared code:
          `.ydd` (400 files): overall 97.7154% -> 99.9472%, system 97.5906% -> 99.8258%,
                 graphics 99.3384% -> 100.0000%, byte-exact 310/400 -> 360/400.
          `.yft` (prop_gold_vault_gate_01): a 54,446-byte unreached run - 35% of the file - that
                 NO tagged pointer targeted, autocorrelation period 52, i.e. vertex data sitting
                 unreferenced because the walk that would have referenced it never ran.
        ⭐ THE FIX IS ORDERING, NOT A PER-SITE ESCAPE. Every blind entry is QUEUED and flushed
        only after every typed walk has finished, so reachability can only ever ADD to what the
        typed model claimed - it can never pre-empt it. A `_seen.discard` at one call site fixes
        one owned root; deferral fixes the hazard for every root at once, including the ones a
        subclass owns and this module has never heard of.
        """
        if self._defer is not None:
            if tagged and (tagged >> 28) == 5:
                self._defer.append(tagged)
            return
        if not tagged or depth > 24 or (tagged >> 28) != 5:
            return
        _b, off, seg = self._res(tagged, 0x80)
        if off is None or seg != 'sys' or off in self._seen:
            return
        self._seen.add(off)
        # capture WIDER than we recurse: nodes reached here run to several hundred bytes, but
        # scanning that far for pointers over-recurses. Both widths are swept - see the constants.
        self._put(off, self.CHASE_CAPTURE)
        s = self.res.sys
        for q in range(0, self.CHASE_SCAN, 4):
            if off + q + 4 > self.nsys:
                break
            try:
                nxt = struct.unpack_from('<I', s, off + q)[0]
            except struct.error:
                break
            if (nxt >> 28) == 5:
                self._chase(nxt, depth + 1)

    def _flush_chase(self):
        """Run the deferred blind walk. Called ONCE, after every typed walk has claimed its
        regions - see `_chase`. Idempotent: a second call finds an empty queue."""
        q, self._defer = self._defer or [], None
        for t in q:
            self._chase(t)

    def _texdict(self, sg_ptr):
        """The drawable's OWN embedded texture dictionary - `ShaderGroup+0x08`.

        ⭐ THIS IS WHERE THE GRAPHICS SEGMENT LIVES. A third of base drawables carry one
        (1,180/3,479, holding 4,845 textures that exist nowhere else), and their PIXELS sit in the
        graphics segment - which is why a first pass that modelled only the drawable graph read
        97.2% on `sys` and 38.7% on `gfx`.
        Layout (same pgDictionary<grcTexture> a .ytd root is, per ytd2xml):
            dict +0x28 u32 count (low 16 bits) | +0x30 ptr -> pointer array (8 B per texture)
            grcTexture +0x50/0x52 w/h | +0x58 format | +0x5D mip count | +0x70 pixel data (GFX)
        ⛔ There is NO stored pixel length - it is COMPUTED from w/h/mips/format, so the span is
        taken from `ytd2xml.mipchain_bytes`, never guessed.
        """
        if not sg_ptr:
            return
        s = self.res.sys
        _b, sg, sgseg = self._res(sg_ptr, 0x40)
        if sg is None or sgseg != 'sys':
            return
        try:
            dict_ptr = struct.unpack_from('<I', s, sg + 0x08)[0]
        except struct.error:
            return
        # ⭐ THE SHADER GROUP'S OWN ARRAYS (`sg+0x10`, `sg+0x20`) - found 2026-08-13 by asking
        # which slot inside an already-captured region lands on the START of an unmodelled run
        # (32 and 20 hits over 20 files). Each points at a descriptor of the same shape the model
        # group uses: {ptr @+0x00, u16 count @+0x08} -> a pointer array -> per-entry structs.
        for arr_slot in (0x10, 0x20):
            try:
                ap = struct.unpack_from('<I', s, sg + arr_slot)[0]
            except struct.error:
                continue
            _bd, dsc, dseg2 = self._res(ap, 0x20)
            if dsc is None or dseg2 != 'sys':
                continue
            self._put(dsc, 0x20)
            # ⭐ THE SUBTREE ENTRY POINTS. The pointer-site scan showed 15 of 21 pointers into the
            # remaining gap came from UNMODELLED sites - i.e. a subtree entered from only a few
            # known slots. `+0x08` and `+0x10` of this descriptor are two of them, and were never
            # followed. Entering them exposes the next layer, which is why this unwinds where
            # single-slot fixes did not.
            for sub in (0x08, 0x10):
                try:
                    sp = struct.unpack_from('<I', s, dsc + sub)[0]
                except struct.error:
                    continue
                self._chase(sp)
            try:
                cnt = struct.unpack_from('<H', s, dsc + 0x08)[0]
                pa = struct.unpack_from('<I', s, dsc + 0x00)[0]
            except struct.error:
                continue
            if not cnt or cnt > 4096:
                continue
            # ⛔ STRIDE IS 16, NOT 8. First guessed 8 by analogy with the model group's pointer
            # array and it moved coverage 99.15% -> 99.18% only. DUMPING the bytes settled it:
            #     <u32 tagged ptr> <u32 0> <u16 tag> <pad>   then the next pointer at +0x10
            # ⭐ The gap "runs" were 1-2 bytes because the image is ZERO-FILLED - only the
            # NON-ZERO bytes of an unmodelled region ever show as a difference, so a wrong stride
            # looks like scattered specks rather than a missing block. Read the bytes, do not
            # infer the shape from a sibling structure.
            self._flat(pa, cnt * 16)
            _bp, pao, pseg = self._res(pa, cnt * 16)
            if pao is None or pseg != 'sys':
                continue
            for k in range(cnt):
                try:
                    ep = struct.unpack_from('<I', s, pao + k * 16)[0]
                except struct.error:
                    break
                if ep:
                    self._flat(ep, 0x40)

        if not dict_ptr:
            return                      # ordinary: most drawables carry no embedded dictionary
        _b2, d, dseg = self._res(dict_ptr, 0x40)
        if d is None or dseg != 'sys':
            return
        self._put(d, 0x40)
        try:
            count = struct.unpack_from('<I', s, d + 0x28)[0] & 0xFFFF
            arr_ptr = struct.unpack_from('<I', s, d + 0x30)[0]
        except struct.error:
            return
        if not count or count > 4096:
            return
        self._flat(arr_ptr, count * 8)
        _b3, arr, aseg = self._res(arr_ptr, count * 8)
        if arr is None or aseg != 'sys':
            return
        import ytd2xml
        for i in range(count):
            try:
                tp_raw = struct.unpack_from('<I', s, arr + i * 8)[0]
            except struct.error:
                break
            _b4, tp, tseg = self._res(tp_raw, 0x90)
            if tp is None or tseg != 'sys':
                continue
            self._put(tp, 0x90)
            try:
                self._flat(struct.unpack_from('<I', s, tp + 0x28)[0], 64)     # name string
                w = struct.unpack_from('<H', s, tp + 0x50)[0]
                h = struct.unpack_from('<H', s, tp + 0x52)[0]
                pitch = struct.unpack_from('<H', s, tp + 0x56)[0]
                mips = max(1, s[tp + 0x5D])
                fmt = struct.unpack_from('<I', s, tp + 0x58)[0]
                _x, blk, bpp = ytd2xml.describe_format(fmt)
                # ⭐⭐ THE ROW PITCH IS STORED (`u16 @ +0x56`) AND IT OVERRULES THE FourCC.
                # `was:` the pixel span computed from w/h/format alone - right until a texture's
                # storage disagrees with the format word it declares, and 18 in this lane do.
                # MEASURED 2026-08-14, `pitch * h` against the format's own level-0 byte count:
                #     fresh 250-file .ydr draw from the game ............ 623 / 623 agree
                #     the 320 .ydr of the population work queue ....... 1,775 / 1,793 agree
                # and the 18 that disagree are EXACTLY the files whose pixels this writer could
                # not reach - SCRIPT RENDER TARGETS (`script_rt_*`, club computers, monitors,
                # TV/laptop props). Every one declares DXT1/DXT5 while storing 4 BYTES PER PIXEL:
                # h4_prop_h4_photo_fire_01a is 256x256 "DXT5" with pitch 1024, i.e. 262,144 B,
                # which is the file's ENTIRE graphics segment, against the 65,536 the FourCC
                # implies. The 4x4 "DXT1" case settles it: the same dimensions and the same FourCC
                # appear on an ORDINARY texture in this lane with pitch 2 and on a render target
                # with pitch 16, so the FIELD, not the format, is what separates them.
                # ⭐ THE OVERRIDE IS ONLY TAKEN WHEN IT FACTORS: `pitch % w == 0` and the implied
                # bytes-per-pixel is a real one, which is what makes this a READ of the row length
                # rather than a widening. All 18 factor as exactly 4 bytes per pixel.
                # ⛔ THE CHAIN RULE IS NOT RE-DERIVED HERE. `ytd2xml.level_sizes` is BLOCK-ROUNDED
                # per level, and substituting a shift-based chain cost 11 files in a 250-file draw
                # (measured: graphics 100.0000% -> 99.9996%). Only the FORMAT is overridden; the
                # per-level rule stays the one that module measured.
                lvl0_fmt = ytd2xml.level_sizes(w, h, mips, blk, bpp)[0]
                if pitch and w and pitch * h != lvl0_fmt and pitch % w == 0 \
                        and (pitch // w) in (1, 2, 4, 8, 16):
                    need = sum(ytd2xml.level_sizes(w, h, mips, None, pitch // w))
                else:
                    need = ytd2xml.mipchain_bytes(w, h, mips, blk, bpp)
                self._flat(struct.unpack_from('<I', s, tp + 0x70)[0], need)
            except Exception:
                # an unmapped format must cost THIS texture's pixels, never the dictionary
                continue

    def _lod(self, grp_ptr):
        if not grp_ptr:
            return
        s = self.res.sys
        buf, mh, seg = self._res(grp_ptr, 0x10)
        if buf is None or seg != 'sys':
            return
        self._put(mh, 0x10)
        marr, nmod = struct.unpack_from('<I', s, mh + 0x00)[0], \
            struct.unpack_from('<H', s, mh + 0x08)[0]
        if not nmod or nmod > 4096:
            return
        self._flat(marr, nmod * 8)
        _b, ma, _sg = self._res(marr, nmod * 8)
        if ma is None:
            return
        for mi in range(nmod):
            mp = struct.unpack_from('<I', s, ma + mi * 8)[0]
            _b2, m, sg2 = self._res(mp, 0x30)
            if m is None or sg2 != 'sys':
                continue
            self._put(m, 0x30)
            garr = struct.unpack_from('<I', s, m + 0x08)[0]
            ngeo = struct.unpack_from('<H', s, m + 0x10)[0]
            gbp = struct.unpack_from('<I', s, m + 0x18)[0]
            if not ngeo or ngeo > 4096:
                continue
            # ⭐ model+0x20 -> the per-geometry SHADER INDEX array (u16 per geometry).
            # Found by scanning every u32 in the segment for a tagged pointer landing on a gap
            # START, then asking which MODELLED region held the pointer: a 0x30-byte region (the
            # model record) at slot +0x20, 3 of the 6 modelled entry points. The rest of the gap
            # hung off it - the pointers into it came from UNMODELLED sites, i.e. a subtree we
            # never entered because its root was this one slot.
            self._flat(struct.unpack_from('<I', s, m + 0x20)[0], ngeo * 2)
            self._flat(gbp, (ngeo + 1 if ngeo > 1 else ngeo) * 32)
            self._flat(garr, ngeo * 8)
            _b3, ga, _s3 = self._res(garr, ngeo * 8)
            if ga is None:
                continue
            for gi in range(ngeo):
                self._geometry(struct.unpack_from('<I', s, ga + gi * 8)[0])

    def _geometry(self, gp):
        if not gp:
            return
        s = self.res.sys
        _b, g, sg = self._res(gp, 0x80)
        if g is None or sg != 'sys':
            return
        self._put(g, 0x80)
        vb_p, ib_p = struct.unpack_from('<I', s, g + 0x18)[0], \
            struct.unpack_from('<I', s, g + 0x38)[0]
        idx_count = struct.unpack_from('<I', s, g + 0x58)[0]
        vcnt = struct.unpack_from('<H', s, g + 0x60)[0]
        stride = struct.unpack_from('<H', s, g + 0x70)[0]   # u16! see module note
        # ⛔ DO NOT GATE ON WHICH SEGMENT THE BUFFER HEADER LIVES IN. `was:` `sgv == 'sys'`, which
        # skipped the vertex data ENTIRELY whenever the header resolved into graphics - and the
        # data it skipped is the mesh itself. Measured signature: 1,504 unreached runs of exactly
        # 13 bytes reading `01 80 01 80 AE 80 FF 7F ...` - packed vertex attributes on a 16-byte
        # stride (13 non-zero + 3 zero), which is why it showed as dust rather than a block.
        # `_put`/`_flat` are already segment-aware; the gate was pure loss.
        _b2, vb, sgv = self._res(vb_p, 0x40)
        if vb is not None:
            self._put(vb, 0x40, sgv)
            self._flat(struct.unpack_from('<I', s, vb + 0x30)[0], 0x10)      # FVF
            # ⭐ grcVertexBuffer carries a SECOND data reference at +0x38 (measured: a live
            # tagged pointer on files whose vertex block ran past vcnt*stride). Following it
            # covers the tail that `vcnt` under-counts.
            self._chase(struct.unpack_from('<I', s, vb + 0x38)[0])
            # ⛔⛔ RETRACTED 2026-08-14 - THE "vcnt UNDER-COUNTS" DEFECT DOES NOT EXIST.
            # This block previously asserted, as a format law, that the vertex block at sys 0xD0
            # in `prop_snow_diggerbkt` holds 1,872 vertices while `vcnt` reads 1,624, leaving 248
            # unread. **It was a MIS-FACTORISATION and everything downstream of it was fiction.**
            # MEASURED (scratchpad/ydr_tail_owner.py): that block is **vcnt 500 x stride 52 =
            # 26,000 B = 0x6590**, and `0xD0 + 0x6590` lands EXACTLY on `0x6660`. `1,624 x 16 =
            # 25,984` is SIXTEEN BYTES SHORT - a near-miss factorisation of the same span.
            # ⭐ The buffer header carries both fields and they AGREE with the geometry record:
            #   `vb+0x08 u32 = stride` (52) · `vb+0x10 = data ptr` · **`vb+0x18 u32 = count`**
            #   (500) · `vb+0x20` = the data ptr again · `vb+0x30` = the declaration.
            # So the old note "neither 1872 nor 1624 appears in the header" was true and useless:
            # the real count is 500 and it sits at +0x18. **`vcnt` never under-counted anything**,
            # and the three hypotheses "ruled out" here were ruled out against a phantom.
            # ⭐ THE LESSON: `1,872 = 248 + 1,624` is an arithmetic coincidence on ONE file. This
            # vault's law is *"a neat fit on two files is a coincidence generator"* - this was a
            # neat fit on one. **Verify a factorisation against the file's own stored fields
            # before deriving anything from it.**
            # ⇒ The real residual was `_chase` scanning 0x80 of each node it captured 0x1000 of;
            #   see CHASE_SCAN at the top of this file.
            vd = struct.unpack_from('<I', s, vb + 0x10)[0]
            # `max(index)+1` as a floor on the vertex count. ⚠ KEPT BUT DEMOTED: it was added to
            # chase the phantom above and measured **0.00% coverage change**, because
            # `max(index)+1 <= vcnt` always. It is retained only as a harmless lower-bound guard -
            # ⛔ do NOT cite it as evidence of anything, and do not re-derive it.
            real = vcnt
            try:
                _bi, io, isg = self._res(ib_p, 0x40)
                if io is not None and 0 < idx_count <= 0x1000000:
                    idp = struct.unpack_from('<I', s, io + 0x10)[0]
                    ibuf, ioff, iseg = self._res(idp, idx_count * 2)
                    if ibuf is not None:
                        mx = 0
                        for k in range(0, idx_count * 2, 2):
                            v = ibuf[ioff + k] | (ibuf[ioff + k + 1] << 8)
                            if v > mx:
                                mx = v
                        if mx + 1 > real:
                            real = mx + 1
            except Exception:
                pass
            if 0 < real <= 0x100000 and 0 < stride <= 0x400:
                self._flat(vd, real * stride)
            else:
                # ⛔ THE SANITY GUARD MUST NOT COST THE DATA. When vcnt/stride fail their bounds
                # the typed read is rightly refused - but refusing it left the MESH unread
                # (measured: 1,504 runs of 13 bytes, packed vertex attributes on a 16-B stride).
                # Fall back to the graph walk so the bytes are still covered, and be honest that
                # this is REACHABILITY, not a typed read.
                self._chase(vd)
        # ⭐ ENTER THE GRAPH FROM THE GEOMETRY RECORD ITSELF. The worst files (sys 91.6%) carry
        # 1,500-1,800 unreached runs of high-entropy data up to ~700 B - far too structured to be
        # padding and far too many to be one missing array. The typed walk above models the
        # buffers it UNDERSTANDS; this reaches whatever else a geometry points at.
        for q in range(0, 0x80, 4):
            try:
                self._chase(struct.unpack_from('<I', s, g + q)[0])
            except struct.error:
                break
        _b3, ib, sgi = self._res(ib_p, 0x40)
        if ib is not None:
            self._put(ib, 0x40, sgi)      # same fix as the vertex buffer: never gate on segment
            if 0 < idx_count <= 0x1000000:
                self._flat(struct.unpack_from('<I', s, ib + 0x10)[0], idx_count * 2)

    def write(self):
        """Lay every captured region into a zero-filled image. NOTHING IS SYNTHESISED HERE.

        ⛔⛔ THIS METHOD USED TO OVERWRITE 4 BYTES IT HAD ALREADY REPRODUCED. The page-count law
        (`ptr@0x08 +8` = `pageCount(sys) | pageCount(gfx) << 8`, derived on META 250/250 and
        confirmed on `ynd` 259/259) was applied here as a WRITE, and on the drawable family it is
        not always true - so the writer corrupted a byte the walk had already captured verbatim,
        and the file scored short for a defect that has nothing to do with reachability.
        MEASURED 2026-08-14 over the 563-file population work queue (every file the whole-game run
        graded short): **60 files - 10 `.ydd`, 22 `.ydr`, 28 `.yft` - had NO other difference at
        all**; their entire residual was this write. Worked examples, stored vs computed:
            cs1_roads_wallret003slod_children.ydd    2 vs  1
            cs3_08e_props_veg21_slod_children.ydd   40 vs 22
            cs1_rdprops_pb_p139_slod_children.ydd   47 vs 26
        ⭐ WHY THE LAW CANNOT HOLD IN GENERAL, and this is arithmetic rather than opinion:
        `seg_size` is invariant under RE-TILING but `page_count` is not. 16,384 bytes is one
        16 KB page (count 1) or two 8 KB pages (count 2) - identical size, different count. The
        RSC7 flags in the RPF entry describe the packer's page plan; the word at `blockmap+8` is
        the plan the resource's OWN block map records. When a file has been repacked the two
        agree on size and disagree on count, and no function of the flags can recover the count.
        ⇒ IT IS DATA, NOT A DERIVATION. It is read like every other byte, by the walk that
        captures the block-map allocation - measured covered in 60/60 files of a random draw from
        the queue, 0 uncovered bytes in the whole allocation.
        ⚠ The derivation is still correct where a file has not been re-tiled and is still what a
        real EXPORT must compute when it lays out fresh pages - `meta_write` keeps it. What it
        must not do is overwrite a byte a round-trip has already reproduced.
        ⛔ The same write is present in `ybn_write`, `ynd_write`, `ynv_write` and `ytd_write`;
        those are other agents' files this run - REPORTED, not edited.
        """
        si, gi = bytearray(self.nsys), bytearray(self.ngfx)
        for off, data in self.sysr:
            si[off:off + len(data)] = data
        for off, data in self.gfxr:
            gi[off:off + len(data)] = data
        return bytes(si), bytes(gi)

    def coverage(self):
        gs, gg = self.write()
        ns = sum(1 for i in range(self.nsys) if gs[i] == self.res.sys[i])
        ng = sum(1 for i in range(self.ngfx) if gg[i] == self.res.gfx[i]) if self.ngfx else 0
        tot = self.nsys + self.ngfx
        return (100.0 * (ns + ng) / tot if tot else 0.0,
                100.0 * ns / self.nsys if self.nsys else 0.0,
                100.0 * ng / self.ngfx if self.ngfx else None)


def read_ydr(src):
    blob = bytes(src) if isinstance(src, (bytes, bytearray)) else open(src, 'rb').read()
    _m, _v, sysf, gfxf = struct.unpack_from('<4sIII', blob, 0)
    return Ydr(Res.from_bytes(blob), (sysf, gfxf))
