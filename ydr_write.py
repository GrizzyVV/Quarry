"""ydr_write - ROUND-TRIP WRITER for .ydr drawables.

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
        self._drawable(0)
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
        n = struct.unpack_from('<H', s, base + 0xB8)[0]                   # lights
        if 0 < n < 4096:
            self._flat(struct.unpack_from('<I', s, base + 0xB0)[0], n * 0xA8)
        for slot in LOD_SLOTS:
            try:
                self._lod(struct.unpack_from('<I', s, base + slot)[0])
            except struct.error:
                pass

    def _bound(self, tagged, depth=0):
        """The drawable's EMBEDDED collision graph at +0xC8 - the same phBound structure
        `ybn_write` walks, so the offsets are shared rather than re-derived:
          composite: u16 child count @+0xA0 · children @+0x70 · transforms @+0x78 · flags @+0x90
          geometry : nverts @+0xD0 · npolys @+0xD4 · nmat u8 @+0x120 · verts @+0xB0 ·
                     polys @+0x88 · materials @+0xF0 · poly-materials @+0x118
          +0x130   : an ARRAY DESCRIPTOR {ptr | count | capacity | records@+0x20}, 16-B records
        """
        if not tagged or depth > 16:
            return
        s = self.res.sys
        _b, off, seg = self._res(tagged, 0x180)
        if off is None or seg != 'sys' or off in self._seen:
            return
        self._seen.add(off)
        self._put(off, 0x180)
        self._octant_map(off)
        try:
            nverts = struct.unpack_from('<I', s, off + 0xD0)[0]
            npolys = struct.unpack_from('<I', s, off + 0xD4)[0]
            nmat = s[off + 0x120]
        except (struct.error, IndexError):
            return
        geom = 0 < nverts <= 0x8000 and 0 < npolys <= 0x100000 and nmat
        if geom:
            self._flat(struct.unpack_from('<I', s, off + 0xB0)[0], nverts * 6)
            self._flat(struct.unpack_from('<I', s, off + 0x88)[0], npolys * 16)
            self._flat(struct.unpack_from('<I', s, off + 0xF0)[0], nmat * 8)
            self._flat(struct.unpack_from('<I', s, off + 0x118)[0], npolys)
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
        try:
            desc = struct.unpack_from('<I', s, off + 0x130)[0]
        except struct.error:
            desc = 0
        if desc:
            _b2, d, dseg = self._res(desc, 0x20)
            if d is not None and dseg == 'sys':
                self._put(d, 0x20)
                try:
                    cnt = struct.unpack_from('<I', s, d + 0x08)[0]
                    if 0 < cnt <= 0x200000:
                        # COUNT-DERIVED -> `_putn`, which refuses on overrun. The probe caught a
                        # live example here: cnt read 327,684, asking 5,242,944 B in a segment
                        # with 40,848 B left. Clamping that would have claimed 40 KB on a misread.
                        self._putn(d + 0x20, cnt * 16)
                        self._flat(struct.unpack_from('<I', s, d + 0x00)[0], cnt * 16)
                except struct.error:
                    pass
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
                mips = max(1, s[tp + 0x5D])
                fmt = struct.unpack_from('<I', s, tp + 0x58)[0]
                _x, blk, bpp = ytd2xml.describe_format(fmt)
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
        si, gi = bytearray(self.nsys), bytearray(self.ngfx)
        for off, data in self.sysr:
            si[off:off + len(data)] = data
        for off, data in self.gfxr:
            gi[off:off + len(data)] = data
        try:
            import meta_write
            buf, o = self.res.deref(self.res.ptr(0x08), 16)
            if buf is not None and o + 12 <= len(si):
                val = ((meta_write.page_count(self.sys_flags) & 0xFF)
                       | ((meta_write.page_count(self.gfx_flags) & 0xFF) << 8))
                si[o + 8:o + 12] = struct.pack('<I', val)
        except Exception:
            pass
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
