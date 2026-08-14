"""ydd_write - ROUND-TRIP WRITER for .ydd drawable dictionaries.

    inflated system+graphics segments -> value model -> written back -> reproduce original bytes

=========================== SECOND PASS, 2026-08-14 (LATEST) ===============================
SAMPLE (`python tools/roundtrip_coverage.py --lane ydd --limit 250`): **250/250 byte-exact,
100.0000%** - sys 100.0000%, gfx 100.0000% (63 files carry a graphics segment).
POPULATION WORK QUEUE (the 12 re-fetched `.ydd` the whole-game run graded short):
**11 of 12 byte-exact, 4 residual bytes**, up from 1 of 12 / 14 bytes.
⚠⚠ THE PREVIOUS 250/250 WAS NOT EARNED, AND THIS PASS PROVED IT RATHER THAN INHERITING IT.
`ydr_write.write()` used to overwrite the resource page-count word with a value recomputed from
the RSC7 flags. Removing that write dropped this lane to **243/250** - because on 7 of those 250
files the write was reproducing a BLOCK-MAP ALLOCATION (48-224 bytes) that nothing had ever read;
its single non-zero byte was the only thing that could ever have shown as a difference, since the
comparison image is zero-filled. `ydr_write._pagemap` now models the block map (`16 + 8 * pages`,
pinned by the allocation extent 266/360 and never overrun 360/360) and the 250 is earned.
⇒ 10 of this lane's 12 queue files were failing for that same write; it is gone, not fixed.
⛔ `_shaders` HAS MOVED to `ydr_write` - see the SUPERSEDED marker below. That is where this
module's own docstring said it belonged, and putting it there took `.yft` from 0 to 189 byte-exact
on the work queue in one step: the `.ydr` and `.yft` lanes had never read a shader group typed.
The remaining 1 file is `po1_07_slod1_2_children.ydd`, 4 bytes at 0x08fff0 (`7e 86 04 3f`, one
float) at the end of a page, not attributed.
============================================================================================

COVERAGE 2026-08-14 (LATEST, 250-file stratified draw from the game):
**100.0000%** overall - system 100.0000%, graphics 100.0000%, **250/250 byte-EXACT**.
Reproduce: `python tools/roundtrip_coverage.py --lane ydd --limit 250`.
⚠ Δ was **85/250 byte-exact** at 99.99992% on that same draw. NOTHING IN THIS MODULE CAUSED THE
GAIN and nothing in it was re-derived: the shared base class `ydr_write.Ydr` grew a `_skeleton`
that reads the bone count from the RIGHT field (+0x5E, not +0x1A - see the SUPERSEDED marker
below) and an `_alloc_prefix` implementing, exactly as specified and exactly as guarded, the
prefix law this module's REMAINING GAP section said it could not implement because it "may not
edit the shared `_flat`". This module's `_skeleton`/`_bonemap` are now marked SUPERSEDED.
⇒ THE REMAINING GAP RECORDED BELOW IS CLOSED ON THIS SAMPLE - both bullets. It is kept as the
record of how it was found, not as an open item.

EARLIER COVERAGE, two INDEPENDENT samples (both printed their sample size; neither was empty):
  sample 1  400 files, x64g/v/q/p/e/i/l   byte-weighted sys 99.9997308%  gfx 100.0000000%
            (285 unreached bytes of 105,857,024 sys; 0 of 57,876,480 gfx)  EXACT 371/400
  sample 2  500 files, x64r/n/o/s/t/u/j/k/m + mpheist/mppatchesng/mpgunrunning
            byte-weighted sys 99.9999844%  gfx 100.0000000%
            (19 unreached bytes of 121,430,016 sys; 0 of 14,532,608 gfx)   EXACT 496/500
⭐ BOTH GRAPHICS FIGURES ARE EXACT ZEROS, not a rounded 100 - every vertex, index and embedded
pixel byte in 900 files is reached. The system figures are NOT 100 and are not written as if they
were; the 304 residual bytes are itemised under REMAINING GAP below.

WHY: `.ydd` is 23,081 files (whole-game census, output/view/VIEW_MANIFEST.jsonl) - the ped and
prop-dictionary lane. Round-trip is the primary measure (Matt, 2026-08-13); a lane with no writer
is UNMEASURED, not passing.

⚠ DRAWABLE DICTIONARIES SPAN TWO SEGMENTS, so coverage is reported for BOTH. A sys-only number
would read nearly done while the mesh and pixel bytes were untouched - the mistake that nearly
closed `.ydr` at "97.2%" with 61% of its graphics segment unread.

WHAT THIS IS
A `.ydd` is `pgDictionary<gtaDrawable>` - the SAME container `ytd2xml` reads for
`pgDictionary<grcTexture>`, holding the SAME gtaDrawable `ydr_write` already walks. So this module
contributes exactly one thing: the container. Every drawable offset is IMPORTED from `ydr_write`
(class `Ydd` subclasses `ydr_write.Ydr`), never re-derived - one structure, one set of numbers, the
same discipline that lets `ydr_write`'s embedded-bound walk share `ybn_write`'s offsets.

CONTAINER, MEASURED 2026-08-14 over 400 real base-game .ydd (x64g/v/q/p/e/i/l; probe printed its
sample size and every figure below is N/400):
    RSC7 version 165 - the DRAWABLE-FAMILY version, 400/400
    +0x00  vtable / blockmap / parent-dict / ref-count words   (see _dictionary)
    +0x20  ptr  -> hash array,  u32 joaat per entry, ASCENDING in 400/400
    +0x28  u32  = count | capacity<<16   (atArray<u32> of the hash array)
    +0x30  ptr  -> entry array, 8 bytes per entry: low u32 tagged ptr, high u32 ZERO in 400/400
    +0x38  u32  = count | capacity<<16   (atArray<gtaDrawable*> of the entry array)
           ⭐ +0x28 and +0x38 are TWO SEPARATE atArray count words that happen to agree; they are
           read independently here and disagreement is survivable (the walk takes the larger count
           that still resolves) rather than silently dropping entries.
    header total 0x40 - +0x40..+0x48 read zero in 400/400 and the first entry follows.
⭐ gtaDrawable IS 0xD0 BYTES, not 0x100: consecutive entry offsets differ by exactly 208 in 1,706
of 1,809 adjacent pairs. `ydr_write.DRAWABLE_SPAN` is 0x100, which is right for a standalone .ydr
(the drawable is the resource root and nothing follows at +0xD0) but over-reaches by 0x30 per
entry here. Handled in `_dictionary` - see DRAWABLE_RECORD.

REMAINING GAP - ⭐ CLOSED 2026-08-14 by `ydr_write._alloc_prefix`; see the Δ note at the top.
Preserved verbatim below because the DIAGNOSIS was right and is what made the fix possible: it
named the structure, the guard the fix had to use, and the reason it could not be done here.
(304 bytes over 900 files; 33 files short of byte-exact) - STOPPED THEN ON THE THREE-STRIKES
RULE, and this was the record of what was left rather than a claim that it was closed:
  * 229 runs of ONE byte, every one at a 16-byte-aligned offset holding a small u32 followed by 12
    zero bytes (`e2 00 00 00 00..`, `46 00 00 00 00..`, `0d 00 00 00 00..`). MEASURED SHAPE: an
    array at base B is preceded by a 16-byte ALLOCATION PREFIX whose first u32 is the array's
    ELEMENT COUNT. Confirmed on the bone array in 73/73 skeletons (u32 at B-16 == bone count, and
    the trailing 12 bytes zero in 73/73). ⛔ The same test FAILS for skel+0x28/+0x30/+0x38
    (219 mismatches) - those arrays are packed adjacently with no prefix, so B-16 there is a
    neighbour's tail. Any fix must be GUARDED on `u32 @ B-16 == the count we already derived`,
    which makes it self-validating; claiming B-16 unconditionally would be exactly the
    fill-to-the-neighbour move this measure exists to catch. Generalising it needs a prefix-aware
    array helper in the SHARED `_flat`, which this module may not edit - hence not done.
  * 8 runs of exactly 8 bytes, high-entropy, 16-byte aligned, followed by 8 zero bytes
    (`85 32 6e 02 99 ee 5c ec`, `a2 9d e4 e1 d8 70 a2 ea`, `5a fa 0e 1f 40 05 ef d5`,
    `23 ee f4 47 ed dd 01 4e`). Best-evidenced hypothesis: a 64-bit signature/hash occupying the
    first half of an otherwise-zero 16-byte slot. UNIDENTIFIED - no pointer in the segment targets
    these offsets, so they are not the head of any reachable array.

Reproduce: `python tools/roundtrip_coverage.py --lane ydd` once the lane is registered there
(this module does not edit that harness - see the report; the entry it needs is
`'ydd': ('ydd_write', 'read_ydd', ('x64g.rpf', 'x64v.rpf', 'x64e.rpf'))`).
ASCII output only.
"""
import os
import struct
import sys as _sys

_sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ydr_write                       # noqa: E402  THE drawable walk - imported, never copied
from ydr2xml import Res                # noqa: E402

DICT_HEADER = 0x40      # measured: +0x40 onward is the first entry, not more header
# ⭐ MEASURED, not assumed: 208 = 0xD0 is the gap between adjacent drawable records in 1,706 of
# 1,809 adjacent pairs across the 400-file sample (next: 416 = 2*208, 42 pairs - one skipped
# record). `ydr_write` captures 0x100 at a drawable base because for a standalone .ydr nothing
# follows the root; inside a dictionary that claims 0x30 bytes of the NEXT record, and past the
# LAST record it claims 0x30 bytes nobody has modelled. Capped here.
DRAWABLE_RECORD = 0xD0
# both MEASURED by adjacent-offset stride over 150 files (see _shaders / _skeleton):
STUB_RECORD = 0x50      # grcTexture reference stub: 80, 675/675 minimal adjacent pairs
BONE_RECORD = 80        # crBoneData: skel+0x20 extent / bone count = 80 in 60/60 skeletons

# ⭐ THE TWO INHERITED CAPTURE WINDOWS WERE SWEPT ON THIS LANE (120 files of sample 1), because a
# constant you rely on but never measure is a constant you are guessing. `ydd_write` does NOT set
# them - they belong to ydr_write - but the sweep says the shared values are the right ones to
# inherit, and it independently reproduces ydr_write's own finding that OVER-capturing is worse:
#   CHASE_CAPTURE (SCAN 0x400):  0x400 -> 52 unreached B, 68/120 exact
#                                0x800 -> 21 B, 99/120   <- marginally best on this lane
#                                0x1000 (shared value) -> 36 B, 99/120
#                                0x2000 -> 1,756 B, 80/120     ⛔ WORSE
#                                0x4000 -> 5,063 B, 68/120     ⛔ WORSE
#     0x800 beats 0x1000 by 15 bytes with the SAME byte-exact file count, which is not worth
#     forking a shared constant over - so this lane inherits 0x1000 unchanged.
#   CHASE_SCAN (CAPTURE 0x1000): 0x80 / 0x200 / 0x400 / 0x800 / 0x1000 all identical
#                                (36 B, 99/120). SCAN is NOT load-bearing here: the typed walks
#                                below already reach what widening the scan would find.


class Ydd(ydr_write.Ydr):
    """`pgDictionary<gtaDrawable>`.

    ⭐ SUBCLASS RATHER THAN RE-IMPLEMENT. `_drawable`/`_lod`/`_model`/`_geometry`/`_texdict`/
    `_bound`/`_chase`/`write`/`coverage` are all inherited verbatim from `ydr_write.Ydr`, so this
    lane cannot drift from the .ydr lane's offsets: a fix there is a fix here.
    ⚠ The one duplicated thing is the five lines of state setup, because `Ydr.__init__` walks a
    drawable at offset 0 unconditionally and a dictionary has no drawable there. See the report -
    a one-line hook in `ydr_write` would remove even that, and this module deliberately does not
    make that edit.
    """

    def __init__(self, res, flags=(0, 0)):
        self.res = res
        self.sys_flags, self.gfx_flags = flags
        self.nsys, self.ngfx = len(res.sys), len(res.gfx)
        self.sysr, self.gfxr = [], []
        self._seen = set()
        self._defer = []                # `ydr_write._chase` now DEFERS - see there for why
        self.entries = []               # [(joaat, sys offset)] - the dictionary's own index
        self._pagemap()                 # the resource BLOCK MAP - see ydr_write._pagemap
        self._dictionary()
        # ⭐ the blind walk runs once, AFTER every entry's typed walk. This is the general form of
        # the `_seen.discard` below: deferral protects EVERY typed walk, not just the entry roots.
        self._flush_chase()

    # ---------------------------------------------------------------- the container
    def _count(self, off):
        """One atArray count word: `count | capacity<<16`. Returns (count, capacity)."""
        try:
            w = struct.unpack_from('<I', self.res.sys, off)[0]
        except struct.error:
            return 0, 0
        return w & 0xFFFF, (w >> 16) & 0xFFFF

    def _dictionary(self):
        s = self.res.sys
        self._put(0, DICT_HEADER)
        n_hash, _cap_h = self._count(0x28)
        n_ent, _cap_e = self._count(0x38)
        try:
            hash_p = struct.unpack_from('<I', s, 0x20)[0]
            arr_p = struct.unpack_from('<I', s, 0x30)[0]
        except struct.error:
            return
        # ⛔ NEVER SIZE A READ FROM THE FIELD UNDER TEST. Both count words are candidates for the
        # entry count and they agree in 400/400 - so instead of PICKING one (which is a guess the
        # data cannot yet settle, see ydd2xml's note on the same pair) take the largest count that
        # still RESOLVES against the segment. On agreement that is the agreed value; on the first
        # file that disagrees it reads the whole array instead of silently truncating it.
        n = 0
        for cand in sorted({n_hash, n_ent}, reverse=True):
            if cand and self.res.deref(arr_p, cand * 8)[0] is not None:
                n = cand
                break
        if not n:
            return
        self._flat(hash_p, n * 4)
        self._flat(arr_p, n * 8)
        hbuf, ho = self.res.deref(hash_p, n * 4)
        abuf, ao = self.res.deref(arr_p, n * 8)
        if abuf is None:
            return
        for i in range(n):
            try:
                dp = struct.unpack_from('<I', abuf, ao + i * 8)[0]
            except struct.error:
                break
            buf, off = self.res.deref(dp, DRAWABLE_RECORD)
            if buf is None or buf is not s:
                continue                # an entry outside the system segment is not a drawable
            h = 0
            if hbuf is not None:
                try:
                    h = struct.unpack_from('<I', hbuf, ho + i * 4)[0]
                except struct.error:
                    h = 0
            self.entries.append((h, off))
            # ⛔⛔ THE BIG ONE, MEASURED 2026-08-14. `ydr_write._drawable` opens with
            # `if base in self._seen: return`, and `_seen` is SHARED with `_chase`/`_bound`. In a
            # dictionary the generic chase run for entry i routinely lands on entry j's drawable
            # record (the records are 0xD0 apart in one contiguous block), which SILENTLY SKIPS
            # entry j's entire typed walk - its LOD groups, geometries, vertex and index buffers.
            # Proven on dt1_01_superlod_children.ydd: 2 entries, `_drawable` called twice,
            # `base in _seen` True on the second -> both of its geometries' vertex (161,568 +
            # 150,552 B) and index (14,274 + 12,918 B) reads never ran, leaving only 4,096-byte
            # chase stubs at 0x000040 / 0x034d50 / 0x038520 / 0x040000. MEASURED whole-sample cost
            # of the defect (400 files): overall 97.7154% -> 99.9472%, system 97.5906% ->
            # 99.8258%, graphics 99.3384% -> 100.0000%, exact round-trip 310/400 -> 360/400.
            # ⭐ A dictionary ENTRY is an owned root, never a chase byproduct, so clearing its
            # visited mark asserts exactly that. Re-capturing a region is free (every capture is a
            # verbatim copy of the source), so this can only add reach.
            self._seen.discard(off)
            # ⭐ THE PROVEN WALK, UNCHANGED. Everything the drawable owns - LOD groups, models,
            # geometries, vertex/index buffers (GRAPHICS segment), shader group, embedded texture
            # dictionary (GRAPHICS pixels), embedded phBound - is reached by ydr_write's code.
            self._drawable(off)
            self._skeleton(off)
            self._shaders(off)
            # ⛔ ydr_write captures DRAWABLE_SPAN (0x100) at `off`; the record is 0xD0 here. Drop
            # the 0x30-byte over-reach so this writer never claims a byte it did not model. The
            # regions list is append-only, so the fix is to remove the offending capture rather
            # than to shrink it in place.
            self._trim(off)

    # ---------------------------------------------------------------- strings
    def _cstr(self, tagged):
        """Capture EXACTLY one NUL-terminated string, terminator included.

        ⛔ NOT a fixed window. `ydr_write` captures a flat 64 bytes at the drawable-name pointer,
        which claims up to 63 bytes it never read; measuring the terminator claims only the string.
        Refuses a run with no NUL inside 256 bytes rather than capturing a guess.
        """
        if not tagged:
            return
        buf, off, seg = self._res(tagged, 1)
        if buf is None:
            return
        end = buf.find(b'\x00', off, off + 256)
        if end < 0:
            return
        self._put(off, end - off + 1, seg)

    # ---------------------------------------------------------------- shader group
    # ⛔⛔ SUPERSEDED 2026-08-14 - THIS IS NOW `ydr_write.Ydr._shaders`, WHICH ALL THREE LANES
    # INHERIT. PRESERVED, NOT DELETED (renamed, so `self._shaders(off)` in `_dictionary` falls
    # through to the base class); revert by renaming back. The derivation below is unchanged and
    # is what the base class implements - this module's own note ("⛔ THIS BELONGS IN `ydr_write`
    # so both lanes share one implementation") was right, and moving it was worth **0 -> 189
    # byte-exact `.yft`** on the population work queue, because `.ydr` and `.yft` had never read a
    # shader group with a typed reader at all: `_texdict` mistook the shader POINTER ARRAY for an
    # array descriptor and captured nothing. Nothing here changed except where it lives.
    def _shaders_SUPERSEDED(self, base):
        """`gtaDrawable+0x10` -> grmShaderGroup -> shader blocks -> parameter table -> texture
        stubs -> their NAME strings.

        ⭐ WHY IT IS HERE AND NOT INHERITED: `ydr_write._texdict` reaches the shader group only to
        find the embedded texture dictionary and then walks two slots (`sg+0x10`, `sg+0x20`) as
        untyped descriptors, capturing 0x40 per entry - documented there as a reachability probe,
        not a typed read. That leaves the PARAMETER TABLE, the texture stubs and every stub's name
        string unmodelled; on small ped components (`feet_000_u.ydd`, 8 KB system segment) the
        generic chase does not reach them either, and they are the whole residual.

        OFFSETS ARE NOT RE-DERIVED - they are the ones `ydr2xml.read_shaders` derived and
        validated (866 full-parameter reference exports; texture names 99.960%), RE-CONFIRMED here
        against raw bytes over 150 files / 341 shader groups before being used:
            shader group +0x10 ptr -> shader array,  +0x18 u16 count   (341/341 resolve)
            shader block  = 0x30 bytes (adjacent-offset stride 48 in 652/652 pairs)
                +0x00 ptr -> parameter table | +0x10 u32 low byte = param count
                +0x14 u16 = data size        | table + dsize = npar u32 name hashes
            param entry   = 16 bytes: byte 0 is the CLASS - 0 = texture, N>0 = N float4s at +0x08
            texture stub  = 0x50 bytes (adjacent stride 80 in 675 pairs; the rest are multiples)
                +0x28 ptr -> name cstr (printable in 1,828/1,828) | +0x30 u16 type word (1 in
                1,828/1,828)
        ⛔ THIS BELONGS IN `ydr_write` so both lanes share one implementation - see the report.
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
            bp = struct.unpack_from('<I', s, ao + si * 8)[0]
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
            # ⛔ dsize is the field that SIZES the table, so it is bounded by an independent
            # quantity (npar * 16) before it is trusted - never sized from itself.
            if not (0 < npar <= 96 and dsize >= npar * 16):
                continue
            self._flat(tp, dsize + npar * 4)     # entries + the trailing name-hash array
            tb, to = self.res.deref(tp, dsize + npar * 4)
            if tb is not s:
                continue
            for pi in range(npar):
                cls = s[to + pi * 16]
                try:
                    ptr = struct.unpack_from('<I', s, to + pi * 16 + 8)[0]
                except struct.error:
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
                self._cstr(struct.unpack_from('<I', s, so + 0x28)[0])

    # ---------------------------------------------------------------- crSkeletonData
    # ⛔⛔ SUPERSEDED 2026-08-14 - `ydr_write.Ydr._skeleton` NOW DOES THIS, AND DOES IT BETTER.
    # PRESERVED, NOT DELETED (renamed `_skeleton_SUPERSEDED` / `_bonemap_SUPERSEDED` so the walk
    # falls through to the base class), because the derivation below is real evidence and the
    # change is reversible by renaming them back.
    # ⭐ WHY THE BASE WINS - MEASURED ON THIS LANE'S OWN 250-FILE SAMPLE, the only variable being
    # which `_skeleton` runs:
    #     this module's :  EXACT  85/250   mean 99.999920%   sys 99.999913%   min 99.9997%
    #     ydr_write's   :  EXACT 250/250   mean 100.000000%  sys 100.000000%  min 100.0000%
    # Two reasons, both structural rather than incidental:
    #   1. THE BONE COUNT FIELD. This module reads u16 @+0x1A and cross-checks +0x5E. That is safe
    #      on the ped lane it was measured against - every ped skeleton carries a bone-tag map, so
    #      +0x1A is populated and the two agree (60/60 here). It is NOT the bone count: +0x1A is
    #      the MAP's entry count, which is 0 whenever the map is absent. Measured over the 109
    #      skeletons in the .ydr sample, +0x1A is ZERO in 84 and equal to +0x5E in 25, and never
    #      larger. `ydr_write` reads +0x5E, which sizes all three arrays into the segment 109/109.
    #   2. THE 16-BYTE ALLOCATION PREFIX. The gap this module documented as "229 runs of ONE byte
    #      ... any fix must be GUARDED on `u32 @ B-16 == the count we already derived` ...
    #      Generalising it needs a prefix-aware array helper in the SHARED `_flat`, which this
    #      module may not edit - hence not done" is now DONE, in the shared class, exactly as
    #      specified and exactly as guarded: `ydr_write._alloc_prefix`. That closes those runs,
    #      which is why the byte-exact count moves 85 -> 250 while the byte figure barely moves -
    #      those files were ONE BYTE short.
    # ⇒ The REMAINING GAP section in this module's header docstring is now closed on this sample.
    def _skeleton_SUPERSEDED(self, base):
        """The drawable's SKELETON at `gtaDrawable+0x18`, whose big per-bone arrays nothing
        modelled. `ydr_write._drawable` captures 0x80 of the skeleton HEADER only; the arrays it
        points at are reached by the generic `_chase`, which captures its swept 0x1000 window and
        stops - so on a skinned ped drawable the arrays were read for their first 4,096 bytes and
        the remainder counted against coverage.
        ⭐ HOW THIS WAS FOUND, not guessed: cluster the unreached runs and ask what lies at each
        cluster's start. Every cluster in the worst ped files began at EXACTLY `base + 0x1000`
        of a pointer target, and those pointers all lived at skeleton_header + 0x20/0x28/0x30
        (feet_000_r.ydd: sites +0x02bf00/+0x02bf08/+0x02bf10 under a skeleton at +0x02bee0).

        LAYOUT, MEASURED 2026-08-14 over the 60 skeleton-bearing drawables in the first 60 files
        of the sample (skel_probe: extent-to-next-allocation divided by each candidate count):
            u16 @+0x1a  = BONE COUNT.  Cross-checked by u16 @+0x5e, which carries the same value
                          in 60/60 - two independent fields, so the count is not taken on faith
                          from the one field whose array is under test.
            +0x20 ptr -> bone records, stride 80   (60/60)
            +0x28 ptr -> 64-byte matrices          (60/60)
            +0x30 ptr -> 64-byte matrices          (59/60)
            +0x40 ptr -> u16 per element, count = u32 @+0x60   (60/60)
        ⚠ +0x10 and +0x38 also hold live pointers and are NOT modelled here - their extents did
        not divide by any header count consistently (best: 26/60 and 22/60). They stay reached by
        `_chase` only, and are named in the gap map rather than covered by a fitted stride.
        ⛔ NOT closed by filling to the next allocation: every span below is count * stride.
        """
        s = self.res.sys
        try:
            sp = struct.unpack_from('<I', s, base + 0x18)[0]
        except struct.error:
            return
        buf, so = self.res.deref(sp, 0x80)
        if buf is not s:
            return
        try:
            n = struct.unpack_from('<H', s, so + 0x1a)[0]
            n2 = struct.unpack_from('<H', s, so + 0x5e)[0]
            nchild = struct.unpack_from('<I', s, so + 0x60)[0]
        except struct.error:
            return
        # ⛔ NEVER SIZE A READ FROM THE FIELD UNDER TEST - so when the two count fields disagree,
        # believe neither blindly: take the larger only if it still resolves, else the smaller.
        for cand in sorted({n, n2}, reverse=True):
            if 0 < cand <= 4096:
                n = cand
                break
        else:
            n = 0
        if 0 < n <= 4096:
            bones = struct.unpack_from('<I', s, so + 0x20)[0]
            self._flat(bones, n * BONE_RECORD)
            self._flat(struct.unpack_from('<I', s, so + 0x28)[0], n * 64)
            self._flat(struct.unpack_from('<I', s, so + 0x30)[0], n * 64)
            # ⭐ BONE NAME STRINGS at bone record +0x38 - 1,303 of 1,303 bone records over 150
            # files point there at a printable NUL-terminated string (`SKEL_L_Finger41`,
            # `FACIAL_R_noseLowerThickness`). No other slot in the 80-byte record ever did, so the
            # slot is measured rather than picked. The records themselves are captured above; the
            # strings they own live in their own block and were the largest remaining residual.
            bb, bao = self.res.deref(bones, n * BONE_RECORD)
            if bb is s:
                for bi in range(n):
                    try:
                        self._cstr(struct.unpack_from('<I', s, bao + bi * BONE_RECORD + 0x38)[0])
                    except struct.error:
                        break
            # ⭐ +0x38 -> PARENT INDICES, one u16 per bone, 0xffff = root. Structural proof rather
            # than a stride fit: over the 73 skeletons in the sample whose +0x38 resolves, all
            # `nbones` values are either < nbones or 0xffff in 73/73, and the number of 0xffff
            # entries is EXACTLY ONE in 73/73 - a single-rooted tree, which is what a parent list
            # must be and what an arbitrary u16 block would not be.
            # (accs_005_u_1.ydd, 13 bones: ffff 0 1 1 0 4 5 6 7 8 7 10 7, then zeros.)
            self._flat(struct.unpack_from('<I', s, so + 0x38)[0], n * 2)
        if 0 < nchild <= 0x10000:
            self._flat(struct.unpack_from('<I', s, so + 0x40)[0], nchild * 2)
        self._bonemap_SUPERSEDED(so)   # kept consistent so the preserved pair still reverses cleanly

    def _bonemap_SUPERSEDED(self, so):
        """The skeleton's BONE-TAG MAP - an `atMap` whose nodes are the last residual in the lane.

        LAYOUT, READ OFF THE BYTES (teef_000_u.ydd, skeleton at sys+0x011ca0):
            skel+0x10 ptr -> BUCKET ARRAY, 8 bytes per bucket
            skel+0x18 u16 = BUCKET COUNT (107 there; NOT the bone count, which is 70 at +0x1a -
                      why an earlier extent/count fit for this slot scored only 26/60)
            bucket    = tagged pointer to the head of a chain, or 0 for an empty bucket
            node (16) = {u32 key, u32 value, u64 next}   e.g. +0x013190:
                        `5a 10 00 00 | 1f 00 00 00 | f0 1e 01 50 00 00 00 00`
                        key 0x105a, value 0x1f (< bone count), next -> sys+0x011ef0
        ⭐ THE NODES ARE SCATTERED, NOT AN ARRAY - which is why nothing that assumed a contiguous
        `count * stride` block ever reached them and why the residual read as 4-byte specks: only
        the two non-zero words of each 16-byte node differ from a zero-filled image.
        ⛔ Followed as a CHAIN, one 16-byte node per hop, with a visited set and a hop cap - never
        by filling from the first node to the last.
        """
        s = self.res.sys
        try:
            barr = struct.unpack_from('<I', s, so + 0x10)[0]
            nb = struct.unpack_from('<H', s, so + 0x18)[0]
        except struct.error:
            return
        if not (0 < nb <= 0x10000):
            return
        self._flat(barr, nb * 8)
        bb, bo = self.res.deref(barr, nb * 8)
        if bb is not s:
            return
        seen = set()
        for i in range(nb):
            try:
                node = struct.unpack_from('<I', s, bo + i * 8)[0]
            except struct.error:
                break
            hops = 0
            while node and hops < 0x10000:
                nbuf, no = self.res.deref(node, 16)
                if nbuf is not s or no in seen:
                    break
                seen.add(no)
                self._put(no, 16)
                try:
                    node = struct.unpack_from('<I', s, no + 0x08)[0]
                except struct.error:
                    break
                hops += 1

    def _trim(self, off):
        """Replace the 0x100-byte drawable-header capture at `off` with the measured 0xD0 record.

        ⛔ WHY THIS EXISTS RATHER THAN A SMALLER CONSTANT: `ydr_write.DRAWABLE_SPAN` is a shared
        module's tuned constant (its own sweep table is recorded there) and this module does not
        edit shared modules. Trimming our own captured region afterwards is the local fix.
        """
        for k in range(len(self.sysr) - 1, -1, -1):
            o, data = self.sysr[k]
            if o == off and len(data) == ydr_write.DRAWABLE_SPAN:
                self.sysr[k] = (o, data[:DRAWABLE_RECORD])
                return


def read_ydd(src):
    blob = bytes(src) if isinstance(src, (bytes, bytearray)) else open(src, 'rb').read()
    _m, _v, sysf, gfxf = struct.unpack_from('<4sIII', blob, 0)
    return Ydd(Res.from_bytes(blob), (sysf, gfxf))
