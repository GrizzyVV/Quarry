"""yft_write - ROUND-TRIP WRITER for .yft fragments (RSC7 v162 / v160).

=========================== FOURTH PASS, 2026-08-15 (LATEST) ===============================
POPULATION, EVERY ONE OF THE 61,430 FILES (`tools/roundtrip_population_all.py --run --lanes yft
--out output/_z6_yftpop`): **61,429 / 61,430 byte-exact = 99.9984%**, was 61,428. Whole-population
per-file diff against `output/_dq6_pop` (`scratchpad/dq6_diff.py`): **0 REGRESSIONS**, 1 gain,
net **-615,750 bytes** - the single largest residual in the lane's history, gone.
⭐ THE GAIN IS `xm_prop_auto_salvage_stromberg.yft`, and the change is `_drawable_array`'s GUARDED
EXTRA ENTRY - see that method for the complete 61,430-file census that pinned it (the predicate
fires on 1 of the game's 352 drawable tables, and on 0 of 352 at the decoy index).
⏭ ONE FILE LEFT: `barracks_hi.yft`, 2,696 B. Characterised under `_drawable_array`'s neighbour
note and in the session report - a 3,024-byte float run at 0x44f360 that NOTHING in the file
points at (0 tagged pointers in 5,251,072 bytes of system segment), whose bytes also occur in
`barracks.yft`, its own LOD twin in the same archive, running 7,120 bytes and landing inside a
region `_bound` claims there. Same asset, two detail builds; not slack we can size, and not an
arena - a structure this file gives no route to.
⚠ THAT POPULATION RUN PREDATES `ydr_write._texdict`'s key-array claim, which landed the same
session and which this lane also inherits. That claim is purely ADDITIVE (it copies original bytes
at an offset the file's own count and hashes pin), so the byte-exact count cannot fall; measured
per-file on the 6,173-`yft` slice of the 14,780-file uniform whole-game draw
(`scratchpad/z9_drwgrade.py`, before = the writers at HEAD): **0 regressions**.
============================================================================================

=========================== THIRD PASS, 2026-08-14 =========================================
POPULATION, EVERY ONE OF THE 61,430 FILES (`--out output/_dq6_pop`): **61,428 / 61,430 byte-exact
= 99.9967%**, was 61,422. SAMPLE: **250 / 250**, was 249/250. Whole-population per-file diff over
all 171,201 `ydr`+`ydd`+`yft` keys: **0 REGRESSIONS** (`scratchpad/dq6_diff.py`).
The six gains are `kamacho` x2, `scarab3_hi`, `airbus_hi`, `bus_hi`, `eurosx32_hi` - the
"6 vehicles short by 13 bytes, ONE polygon record of trailing slack" the pass below ruled
underivable. It was not a length question: see `ydr_write._polytail`, ported from `ybn_write`.

⭐⭐ TWO STRUCTURES OF THIS LANE'S OWN ARE NOW MODELLED, AND THEY BUY **ZERO** BYTE-EXACT FILES.
That is the point of them. Both were already "covered" by `_chase`'s unpinned 0x1000-byte
windows, and **a claim that cannot fail is exactly the defect the round-trip measure exists to
catch** - the image copies the ORIGINAL bytes at whatever offset is claimed.
  * `_child +0xB0` -> a FIXED 48-byte record. 8,890 live uncovered targets in a uniform mod-40
    draw of the whole game; the room to the next structure is 48 B on 8,886 (99.955%), bytes
    +0x08..+0x30 are zero on 8,890/8,890 and `u32 @+0x04 == 1` on 8,890/8,890.
  * `_lod_phys +0xC8` -> a SECOND PER-GROUP POINTER ARRAY, `ng * 8`. 5,923 arrays; `ceil(ng*8/16)
    *16` equals the room on 99.88% while K=32 and K=64 overrun on 96.6% and 98.3%; every one of
    the 12,030 entries is a tagged system pointer with a zero high word (100.00%).
⛔ HOW THEY WERE FOUND, because the method transfers and staring at the record did not: the
handover called these "a type-4 48-byte trailer after the polygon array" and "tagged-pointer
arrays after the polygon array". `scratchpad/dq6_who.py` asked instead **which unmodelled gaps
are POINTED AT** - 72 of 72 were - and `dq6_owner.py` traced each pointer back to the capture
that already owned the bytes holding it, which named these two slots outright. A gap that begins
where another array ends is not part of that array.
============================================================================================

=========================== SECOND PASS, 2026-08-14 ========================================
POPULATION, **EVERY ONE OF THE 61,430 FILES** (`tools/roundtrip_population_all.py --run --lanes
ydr,ydd,yft --out output/_dq_pop2`, then `--report`): **61,422 / 61,430 byte-exact = 99.9870%**,
mean coverage **99.9997%** (min 83.2221%), sys 99.9996%, gfx 100.0000% (16,972 carry one),
0 refusals. Was 61,195 / 61,430 = 99.6175%. **ZERO regressions** against the previous run.
⚠ The min is one file - `xm_prop_auto_salvage_stromberg.yft`, diagnosed below.
SAMPLE (`python tools/roundtrip_coverage.py --lane yft --limit 250`): **249/250 byte-exact,
100.0000%** - sys 100.0000%, gfx 100.0000% (96 files carry a graphics segment). Was 247/250.
POPULATION WORK QUEUE (the 231 re-fetched `.yft` the whole-game run graded short):
**223 of 231 byte-exact**, up from 0 of 231; residual 650,060 -> 618,524 bytes.
⚠ THE RESIDUAL BARELY MOVES BECAUSE ONE FILE IS ALL OF IT: `xm_prop_auto_salvage_stromberg.yft`
holds 615,750 of the 618,524 bytes left. Byte-exact COUNT is the honest headline for this lane.
EVERY GAIN CAME FROM THE SHARED BASE CLASS, not from this module:
  * `ydr_write._shaders` - the typed shader-group read this lane never had. `_texdict` mistook
    the shader POINTER ARRAY at `sg+0x10` for an array descriptor, so the parameter table, its
    float4 value blocks and its joaat name-hash array were left to the blind walk. Worth
    **0 -> 189** byte-exact on the queue, in one step.
  * `ydr_write.write()` no longer overwrites the resource page-count word: **28** `.yft` had NO
    other difference at all.
  * `ydr_write._bvh` replaced the refuted `+0x130` fill, plus composite `+0xA8`, vertex colours
    `+0xB8`, material colours `+0xF8` and the bound TYPE CODE as the geometry discriminator:
    **217 -> 223**.
⏭ WHAT REMAINS IN THIS LANE, 8 files:
  * `xm_prop_auto_salvage_stromberg.yft` 615,750 B - ⭐ CAUSE FOUND AND NOT FIXED, ON PURPOSE.
    `_drawable_array` computes `n = total - 1` from the u8 at `deref(fragroot+0xA8)+0x10`. This
    file reads `total = 1`, so `n = 0` and the table is skipped whole - yet ENTRY 0 of that table
    (0x25f2a0) holds a real extra drawable at 0x25c310, whose LOD group (0x25a140) -> model ->
    geometry -> vertex buffer (0x25d280: stride 52 @+0x08, count 5,038 @+0x18, data -> 0x080000)
    is 261,976 bytes of vertex data. `5038 x 52` accounts for the largest run to the byte, and
    the blind walk captured only its first 0x1000. The four biggest runs all start on a 0x1000
    page boundary for exactly that reason - `CHASE_CAPTURE` ran out.
    ⛔ WHY IT IS LEFT ALONE: only SIX files in the whole 231-file work queue carry a drawable
    table at all, and on those six the CURRENT `total - 1` reading puts a real drawable at the
    last index in 3 (n/a in 1, false in 2) while reading it as `total` would add a bogus entry in
    5 of 6. **A six-file sample cannot carry a change to a shared count reading, and this is a
    neat fit on ONE file** - the exact shape of the mis-factorisation this codebase retracted
    earlier the same day. It needs a draw big enough to contain many tables, which this pass did
    not have. Recorded here so the next pass starts at the answer instead of the symptom.
  * `barracks_hi.yft` - the SAME 3,024-byte float run this module already documented as gap
    shape (2), at 0x44f360, plus a second 2,160-byte run at 0x44f6c0. Still unattributed.
  * 6 vehicles short by 13 bytes (`kamacho`, `scarab3_hi`, `airbus_hi`, `bus_hi`, `eurosx32_hi`)
    - ONE polygon record of trailing slack, the class ruled out under `ydr_write._bound`.
⛔ `_skeleton_SUPERSEDED` stays superseded; nothing in this pass revived it.
============================================================================================

COVERAGE 2026-08-14 (LATEST, 250-file stratified draw from the game via the shared harness):
**100.0000%** overall - system 100.0000%, graphics 100.0000%, **247 / 250 byte-exact**.
Reproduce: `python tools/roundtrip_coverage.py --lane yft --limit 250`.
⚠ Δ was 234/250 byte-exact on the same draw. Both gains came from the SHARED base class, not
from this module:
  * `ydr_write._octant_map` - phBound +0xC0 counts[8] / +0xC8 pointer table[8]. That is gap
    shape (1) below, which this docstring records as the OCTANT MAP hypothesis and marks NOT
    CLOSED "because the count field that sizes them is not pinned". IT IS NOW PINNED, and the
    structure validates its own extent: `ptr[k+1] - ptr[k] == counts[k] * 4` for all k.
  * `ydr_write._skeleton` + `_alloc_prefix` - supersedes this module's `_skeleton` (see the
    SUPERSEDED marker below; measured 236 -> 247 byte-exact, and running BOTH scores the same as
    the base alone, so this module's version reached nothing extra).
EARLIER: 99.9990% / 235 of 330 byte-exact over a stratified sample (120 vehicles / 155 props /
55 peds from x64e, x64c, x64f, x64g, x64a, x64d).

    inflated system+graphics segments -> value model -> written back -> reproduce the bytes

WHY THIS LANE: `.yft` is 61,430 files - vehicles and breakable props - and 18.4% of all map
entities reference ASSET_TYPE_FRAGMENT archetypes. A lane with no writer is UNMEASURED, not
passing (Matt, 2026-08-13).

⛔⛔ MEASURE THIS LANE ON A STRATIFIED SAMPLE OR THE NUMBER IS A BOARD, NOT A POPULATION.
`roundtrip_coverage.harvest` walks its archive list depth-first from a LIFO stack; for `.yft`
that reaches `x64e/componentpeds_*.rpf` first, so a plain `--limit 250` draw is **243 of 250
PEDS** and scores **250/250 byte-exact, 100.0000%** - while vehicles, the hard variant, are
absent from it entirely. The honest figure is the stratified one above. Vehicles and props are
structurally different fragments and peds are the EASIEST of the three.

WHAT A FRAGMENT IS, STRUCTURALLY: a DRAWABLE + a phBOUND graph + a fragment physics wrapper.
Two of those three are already modelled, so they are IMPORTED rather than re-derived:
`ydr_write.Ydr` supplies `_drawable/_lod/_geometry/_texdict/_bound/_chase/write/coverage`, and
`_bound` is itself the `ybn_write` phBound walker's offsets. One structure, one set of numbers.
The derivation here is the fragment WRAPPER only.

OFFSETS - every one below is READ from `yft2xml`, which measured them against the reference
exporter's oracle set; none is invented here. See that module for the per-offset evidence.
  fragType @ sys 0: +0x30 main drawable · +0x38 DrawableArray table · +0x58 name cstr
      +0x60 cloth pgArray (u16 count @+0x68) · +0xA8 BoneTransforms array desc
      +0xD9 u8 glass count / +0xE0 glass ptr array · +0xF0 fragPhysicsLODGroup
      +0x110 lights ptr / u16 count @+0x118 · +0x120 vehicle-glass 'HWGV' manager
  fragPhysicsLODGroup: +0x10/+0x18/+0x20 = LOD1/2/3   (LOD2/3 are NULL on the base game -
      counted, see LODG_SLOTS)
  fragPhysicsLOD (LOD1): +0x20 ArticulatedBody · +0x28 UnkFloat[nc] · +0xC0 group ptr array
      (u8 count @+0x11A) · +0xD0 child ptr array (u16 count @+0x11E) · +0xD8/+0xE0 Archetype/2
      +0xF0 InertiaTensor[nc*16] · +0xF8 UnkVec[nc*16] · +0x100 Transforms (u32 count @+0x10,
      records @+0x20 stride 0x40) · +0x108/+0x110 u8 index tables (counts @+0x118/+0x119)
  fragGroup: the NAME is an INLINE char[] @ group+0x80, so the record base is namePtr-0x80.
  fragTypeChild: +0x10 GroupIndex · +0x12 BoneTag · +0xA0 drawable · +0xA8 DAMAGED drawable
      (Drawable2) · +0xB0 EventSet
  archetype: +0x18 name · +0x20 phBound (-> the shared `_bound` walker) · +0x40.. inertia
  FragDrawable is LONGER than a .ydr drawable: +0x90 Joints, +0xB0 4x4 matrix, +0x108 Matrices
      ptr with u16 count @+0x110 stride 0x40. `ydr_write.DRAWABLE_SPAN` (0x100) stops short of
      the last two, so this module captures its own span and chases the tail slots.
  crSkeletonData (drawable+0x18) - DERIVED HERE, and the single largest gap in the lane.
      `ydr_write` captures only the 0x80-byte header (a .ydr rarely has a skeleton at all);
      EVERY fragment has one (330/330 measured) and a ped's is ~30 KB. Layout, pinned over the
      330-file sample rather than a witness pair:
        +0x10 bone-tag hash BUCKET array (u64 slots) · u16 capacity @+0x18 · u16 count @+0x1A
              bucket -> node {u32 BoneTag, u32 BoneIndex, u64 next} = 16 B, chained
        +0x20 bone array, stride 0x50, count = u16 @+0x5E  (fits in the measured room 330/330)
        +0x28 TransformationsInverted, stride 0x40   (325/330; the 5 are a pointer landing
        +0x30 Transformations,         stride 0x40    INSIDE the array, not an overrun)
        +0x38 ParentIndices, u16 per bone (330/330)
        +0x40 ChildIndices,  u16, count = u32 @+0x60
      ⛔ The bone count is +0x5E, NOT +0x1A - +0x1A is the hash map's ENTRY count and is 0
      whenever the map is absent (yft2xml records the same correction).
  vehicle glass manager: u16 count @+0x06 and **u32 totalSize @+0x08** - the manager block is
      SELF-DESCRIBING, so its shatter-map rasters are captured by their own stored length and
      never by filling to the next region.

THE REMAINING GAP AS IT STOOD BEFORE 2026-08-14 - ⭐ SHAPE (1) IS NOW CLOSED (the octant map;
see the Δ note at the top). Preserved because the diagnosis is what made the fix findable: it
named the structure and said precisely what was missing (the sizing field), and the fix supplied
exactly that. Shape (2) is not yet attributed.
(0.0010% of system bytes, VEHICLES ONLY - props read 99.9999%, peds 100%).
Worst file `barracks_hi` 99.939% (4,358 B unreached of 5,251,072). Two shapes:
  1. u32 ARRAYS OF SMALL INTEGERS (values 1..13), runs of ~170-380 B, many ending just short
     of a 0x1000 page boundary. e.g. benson 0x001AFE30 len 377
     `0d000000 0d000000 08000000 08000000 0b000000 08000000 04000000 06000000`
     Reached from a 16-BYTE RECORD TABLE that is itself unmodelled - context dumped at
     barracks_hi 0x4BC3A8 and bati 0x7F288 is a run of
     `{u64 tagged ptr, u8 0x01, u8 <index, DECREMENTING>, 6 x 00}`
     whose pointers step by exactly 0x10, i.e. a table indexing 16-byte items.
     BEST-EVIDENCED HYPOTHESIS: the phBoundGeometry OCTANT MAP (per-octant vertex counts +
     index lists). Supporting sighting: on a bound already walked here, +0x80 / +0xE0 / +0x140
     each resolve to `0000 0100 0200 0300 0400 0500 0600 0700` - a plain ascending u16 index
     run, which is what an octant index list looks like. NOT CLOSED: the count field that
     sizes them is not pinned, and 8 octants does not factor the observed 60-95 entries.
  2. ONE 3,024 B float run, barracks_hi 0x0044F360
     `cdc93b3e 80d7393f 68b0b93d 00507a3b 32ff7f3f 82ff0436 00002d37 00c091b8` - unattributed.
⛔ NOT CLOSED BY FILLING. Every byte above is left unclaimed on purpose: filling from a
region's end to the next region's start would report ~100% while understanding none of it.

ASCII output only.
"""
import os
import struct
import sys as _sys

_sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ydr_write  # noqa: E402
from ydr2xml import Res  # noqa: E402

# --- spans. A span is a CLAIM about a record's size; each was swept, table in the module log.
FRAG_SPAN = 0x140          # fragType root
FRAGDRAW_SPAN = 0x140      # FragDrawable (ydr's 0x100 misses +0x108 Matrices / +0x110 count)
LODG_SPAN = 0x30           # fragPhysicsLODGroup header
LOD_SPAN = 0x130           # fragPhysicsLOD  (+0x11E child count is the last field read)
GROUP_SPAN = 0xB0          # fragGroup (name inline @+0x80, last float @+0xA8)
CHILD_SPAN = 0xC0          # fragTypeChild (last pointer read is +0xB0)
CHILD_EVENTSET_SPAN = 48   # fragTypeChild +0xB0 -> a FIXED 48-byte record; see `_child`
ARCH_SPAN = 0xB0           # phArchetypeDamp
ARTB_SPAN = 0xA0           # articulated body struct (ItemFlags[22] ends at +0xA0)
JOINT_SPAN = 0xF0          # one articulated joint item
CLOTH_ITEM_SPAN = 0x80
CLOTH_CTRL_SPAN = 0xA0     # the controller NAME is an inline char[] @+0x58
CLOTH_BRIDGE_SPAN = 0x140
CLOTH_VERLET_SPAN = 0x160

SKEL_SPAN = 0x70           # crSkeletonData header
BONE_STRIDE = 0x50

# ⭐ MEASURED, not chosen. TWO separate knobs, because they trade off in opposite directions:
# CAPTURE = how many bytes to take at a node the blind walk reaches; SCAN = how far into that
# node to look for the next pointer. Conflating them (scan == 0x80 while capturing 0x1000) holds
# a node's tail without ever following the descriptors in it - the defect `ydr_write` records.
# SWEPT over the whole 330-file sample (overall coverage / byte-exact files), CAPTURE fixed at
# 0x1000, `python sweep.py CHASE_SCAN ...`:
#   SCAN 0x80 -> 99.9866% 195/330 | 0x100 -> 99.9938% 215 | 0x200 -> 99.9954% 220
#        0x400 -> 99.9962% 228 | 0x800 -> 99.9969% 230 | 0x1000 -> 99.9976% 232
#        0x2000 -> 99.9992% 249 | 0x4000 -> 99.9993% 252
# ⛔ THE CURVE DOES NOT TURN OVER, AND THE TOP OF IT IS REFUSED ON PURPOSE. Past 0x1000 the
# walk is reading POINTER VALUES OUT OF BYTES IT NEVER CAPTURED - it treats a node as 4 KB for
# capture and 16 KB for pointer-finding, which is not one claim about a structure, it is two
# contradictory ones. SCAN is therefore TIED TO CAPTURE: scan exactly what you claim. The
# 0x2000/0x4000 rows are recorded because they are real, not because they are earned - taking
# them would buy 0.0017% by degenerating the walk into "follow every tagged dword in the file".
CHASE_CAPTURE = 0x1000
CHASE_SCAN = CHASE_CAPTURE

LODG_SLOTS = (0x10, 0x18, 0x20)     # LOD1 / LOD2 / LOD3 - non-resolving ones no-op


def _u32(s, o):
    return struct.unpack_from('<I', s, o)[0]


def _u16(s, o):
    return struct.unpack_from('<H', s, o)[0]


class Yft(ydr_write.Ydr):
    """A fragment. Inherits every drawable/bound/texture walk from `ydr_write.Ydr`; overrides
    only the ENTRY so the walk starts at the fragType root instead of a bare drawable."""

    def __init__(self, res, flags=(0, 0)):
        self.res = res
        self.sys_flags, self.gfx_flags = flags
        self.nsys, self.ngfx = len(res.sys), len(res.gfx)
        self.sysr, self.gfxr = [], []
        self._seen = set()
        self._defer = []            # see _chase - the blind walk runs LAST, never first
        self._bounds = []           # [(off, btype, fld)] - see ydr_write._polytail
        self._polyclaim = {}        # see ydr_write._polytail
        self._pagemap()             # the resource BLOCK MAP - see ydr_write._pagemap
        self._frag()

    # ⛔⛔ THE ORDERING DEFECT THIS FIXES, measured 2026-08-14 on prop_gold_vault_gate_01:
    # `_drawable`, `_bound` and `_chase` all share one `_seen` set, and the BLIND walk gets
    # there first. `ydr_write._drawable` runs its chase sweep in the MIDDLE of its own walk, so
    # by the time `_drawable_array` reached the fragment's "damaged" extra drawable at 0x22690,
    # the chase had already put that offset in `_seen` and the typed walk RETURNED IMMEDIATELY -
    # skipping its LOD/model/geometry chain entirely. Signature: a 54,446-byte unreached run
    # (35% of the file) that NO tagged pointer targets, whose autocorrelation period is 52 -
    # i.e. vertex data on a 52-byte stride, sitting there unreferenced because the walk that
    # would have referenced it never ran.
    # ⭐ FIX: `_chase` DEFERS. Every blind entry is queued and flushed after every typed walk
    # has finished, so reachability can only ever ADD to what the typed model claimed - it can
    # never pre-empt it. This is why the fix is here and not a `_seen.discard` at each call
    # site: the hazard lives inside the inherited ydr walk, which this override reaches.
    def _chase(self, tagged, depth=0):
        if self._defer is not None:
            if tagged and (tagged >> 28) == 5:
                self._defer.append(tagged)
            return
        if not tagged or depth > 24 or (tagged >> 28) != 5:
            return
        _b, off, seg = self._res(tagged, 0x40)
        if off is None or seg != 'sys' or off in self._seen:
            return
        self._seen.add(off)
        self._putc(off, CHASE_CAPTURE)      # CLAMPED - see _putc for why refusing loses more
        s = self.res.sys
        for q in range(0, CHASE_SCAN, 4):
            if off + q + 4 > self.nsys:
                break
            nxt = struct.unpack_from('<I', s, off + q)[0]
            if (nxt >> 28) == 5:
                self._chase(nxt, depth + 1)

    def _flush_chase(self):
        q, self._defer = self._defer, None
        for t in q:
            self._chase(t)

    # ⭐ phBOUND +0x78 ON A **GEOMETRY** BOUND IS A SECOND VERTEX ARRAY (nverts * 6).
    # The shared walker reads +0x78 only as the COMPOSITE child-transform array (n * 64), so on
    # a geometry bound - where the composite child count is not a count at all - the slot is
    # never followed. After the skeleton and chase-ordering fixes this was the single dominant
    # remaining site in the lane (8 of 11 attributed gap-start pointers).
    # MEASURED over 150 files / 1,982 non-composite bounds that carry a live +0x78:
    #     +0x78 resolves to a DIFFERENT address than +0xB0 (the main vertex array) .... 1,979
    #     nverts * 6 fits the measured room to the next pointer target ................ 1,976
    #     +0x78 == +0x80 (i.e. an aliased composite slot) ...............................  0
    # so it is a distinct array of the same 3 x i16 shape the main vertex array uses.
    # ⚠ THIS BELONGS IN THE SHARED WALKER, NOT HERE. `ybn_write._bound` and `ydr_write._bound`
    # have the same blind spot and .ybn is 15,139 collision-only files where it will cost far
    # more than it does here. It is implemented as an EXTENSION rather than a fork: the parent
    # walk still does all the traversal and still recurses through `self._bound`, so this hook
    # fires for every child too, and there is exactly one set of bound offsets in the codebase.
    # File ownership barred editing the shared module this run - reported instead.
    def _bound(self, tagged, depth=0):
        off = None
        if tagged:
            _b, off, seg = self._res(tagged, 0x180)
            if seg != 'sys':
                off = None
        fresh = off is not None and off not in self._seen
        super()._bound(tagged, depth)
        if not fresh:
            return
        s = self.res.sys
        try:
            nverts = _u32(s, off + 0xD0)
            npolys = _u32(s, off + 0xD4)
            nmat = s[off + 0x120]
        except (struct.error, IndexError):
            return
        # the SAME discriminator the parent uses to decide "this is a geometry bound" - so a
        # composite, whose +0x78 really is the transform array, can never take this path
        if 0 < nverts <= 0x8000 and 0 < npolys <= 0x100000 and nmat:
            self._flatc(self._p(off, 0x78), nverts * 6)

    # ---------------------------------------------------------------- helpers
    # ⭐ CLAMPED CAPTURE. `ydr_write._put`/`_flat` refuse the WHOLE region when it would run
    # past the segment end (`off + nbytes <= self.nsys`), so a span that overhangs the last
    # page loses every byte of a region that is mostly in range. That is also why ydr's
    # CHASE_CAPTURE sweep is NON-MONOTONIC (0x2000 measured WORSE than 0x1000) - bigger spans
    # fall off the end more often. Measured here: clamping instead of refusing is worth
    # +0.31% system coverage on this lane (sweep table in the module notes).
    def _putc(self, off, nbytes):
        if off is None or nbytes <= 0 or off >= self.nsys:
            return
        n = min(nbytes, self.nsys - off)
        self.sysr.append((off, bytes(self.res.sys[off:off + n])))

    def _flatc(self, tagged, nbytes):
        """Clamped `_flat`: resolves into EITHER segment, then clamps rather than refusing."""
        if not tagged or nbytes <= 0:
            return
        _b, off, seg = self._res(tagged, 1)
        if off is None:
            return
        if seg == 'gfx':
            n = min(nbytes, self.ngfx - off)
            if n > 0:
                self.gfxr.append((off, bytes(self.res.gfx[off:off + n])))
        else:
            self._putc(off, nbytes)

    def _p(self, off, slot):
        """Read a tagged pointer at an ABSOLUTE system offset, or 0 when out of range."""
        try:
            return _u32(self.res.sys, off + slot)
        except struct.error:
            return 0

    def _deref(self, tagged, need=1):
        """-> system offset, or None. Fragments are a system-segment structure; graphics only
        ever appears under the drawable, which `ydr_write` already handles segment-aware."""
        if not tagged:
            return None
        _b, off, seg = self._res(tagged, need)
        return off if (off is not None and seg == 'sys') else None

    def _cstr(self, tagged, limit=128):
        off = self._deref(tagged, 1)
        if off is None:
            return
        end = self.res.sys.find(b'\x00', off)
        n = limit if end < 0 else min(end - off + 1, limit)
        self._put(off, max(n, 1))

    # ---------------------------------------------------------------- fragType root
    def _frag(self):
        s = self.res.sys
        self._put(0, FRAG_SPAN)
        self._cstr(self._p(0, 0x58))                       # "pack:/<stem>"
        # main visual drawable
        main = self._deref(self._p(0, 0x30), 0x40)
        if main is not None:
            self._fragdrawable(main)
        self._drawable_array()
        self._bone_transforms()
        self._glass_windows()
        self._vehicle_glass()
        self._frag_lights()
        self._cloths()
        self._physics()
        # FINAL SWEEP - same doctrine as `ydr_write._drawable`: enter the reachable graph from
        # every tagged pointer in the root AFTER the typed walks have claimed their regions, so
        # this only picks up what they left.
        for q in range(0, FRAG_SPAN, 4):
            if q + 4 > self.nsys:
                break
            self._chase(self._p(0, q))
        # ⭐ the polygon tail runs on the TYPED coverage only - before the deferred blind walk
        # is flushed, so a 0x1000-byte window cannot pre-empt a pinned claim. See ydr_write.
        self._polytail()
        self._flush_chase()

    def _fragdrawable(self, base):
        """A fragment's drawable. `ydr_write._drawable` models a .ydr drawable (span 0x100);
        a FragDrawable carries +0x108 Matrices / +0x110 count beyond that, and +0x90 Joints
        inside it, so both the wider span and the tail chase are added here."""
        if base is None:
            return
        s = self.res.sys
        self._putc(base, FRAGDRAW_SPAN)
        self._skeleton(base)
        self._joints(base)
        # <Matrices> - ptr @+0x108 GATES it, u16 count @+0x110, memory stride 0x40 (yft2xml
        # measured 0x30 reproducing only 21/53 matrices; 0x40 gives 53/53).
        mp = self._deref(self._p(base, 0x108), 0x40)
        if mp is not None:
            n = _u16(s, base + 0x110) if base + 0x112 <= self.nsys else 0
            if 0 < n <= 4096:
                self._put(mp, n * 0x40)
        for q in range(ydr_write.DRAWABLE_SPAN, FRAGDRAW_SPAN, 4):
            self._chase(self._p(base, q))
        self._drawable(base)

    # ⛔⛔ SUPERSEDED 2026-08-14 - `ydr_write.Ydr._skeleton` now covers this, and covers more.
    # PRESERVED, NOT DELETED (renamed, so the walk falls through to the base class); revert by
    # renaming back. The derivation in the module docstring above still stands - the base class
    # implements the SAME layout, including this module's own correction that the bone count is
    # +0x5E and not +0x1A. What it adds is `_alloc_prefix`: the 16-byte allocation prefix in front
    # of the bone array, claimed ONLY when `u32 @ B-16` equals the count already derived from the
    # header (measured 109/109 on the .ydr sample, and FALSE 109/109 for +0x28/+0x30/+0x38, so it
    # is applied to the one slot that earned it).
    # ⭐ MEASURED ON THIS LANE'S 250-FILE SAMPLE, the only variable being which `_skeleton` runs:
    #     this module's :  EXACT 236/250   mean 99.999983%   sys 99.999961%
    #     ydr_write's   :  EXACT 247/250   mean 99.999992%   sys 99.999978%
    #     BOTH together :  EXACT 247/250   - identical to the base alone, i.e. this version
    #                      contributes NOTHING the base does not already reach. That control is
    #                      why this is a removal and not a preference.
    def _skeleton_SUPERSEDED(self, base):
        """crSkeletonData @ drawable+0x18 - see the module docstring for the derivation. Every
        count comes from the HEADER, never from the array being sized."""
        s = self.res.sys
        sk = self._deref(self._p(base, 0x18), SKEL_SPAN)
        if sk is None:
            return
        self._putc(sk, SKEL_SPAN)
        try:
            nb = _u16(s, sk + 0x5E)
            cap, cnt = _u16(s, sk + 0x18), _u16(s, sk + 0x1A)
            nci = _u32(s, sk + 0x60)
        except struct.error:
            return
        if 0 < nb <= 8192:
            ba = self._deref(self._p(sk, 0x20), BONE_STRIDE)
            if ba is not None:
                self._putc(ba, nb * BONE_STRIDE)
                for i in range(nb):
                    self._cstr(self._p(ba, i * BONE_STRIDE + 0x38))     # bone NAME
            self._flatc(self._p(sk, 0x28), nb * 0x40)      # TransformationsInverted
            self._flatc(self._p(sk, 0x30), nb * 0x40)      # Transformations
            self._flatc(self._p(sk, 0x38), nb * 2)         # ParentIndices
        if 0 < nci <= 1 << 20:
            self._flatc(self._p(sk, 0x40), nci * 2)        # ChildIndices
        # bone-tag hash map: `cap` u64 buckets, each a chain of 16-B nodes
        if 0 < cap <= 65536 and cnt:
            ta = self._deref(self._p(sk, 0x10), 8)
            if ta is not None:
                self._putc(ta, cap * 8)
                seen = 0
                for k in range(cap):
                    node = self._deref(self._p(ta, k * 8), 16)
                    while node is not None and seen < cap * 4:
                        seen += 1
                        self._putc(node, 16)
                        node = self._deref(self._p(node, 0x08), 16)

    def _joints(self, base):
        """drawable+0x90 -> joint DOF limits. rot ptr @+0x10 (stride 0xC0, u16 count @+0x30),
        trans ptr @+0x18 (stride 0x40, u16 count @+0x32)."""
        jo = self._deref(self._p(base, 0x90), 0x40)
        if jo is None:
            return
        s = self.res.sys
        self._put(jo, 0x40)
        try:
            rn, tn = _u16(s, jo + 0x30), _u16(s, jo + 0x32)
        except struct.error:
            return
        if 0 < rn <= 4096:
            self._flat(self._p(jo, 0x10), rn * 0xC0)
        if 0 < tn <= 4096:
            self._flat(self._p(jo, 0x18), tn * 0x40)

    def _entry_resolves(self, tab, i):
        """Does table entry `i` resolve to a drawable whose OWN stored fields describe a mesh?

        Every clause is a field the file states about itself, chained: entry pointer -> drawable
        -> LOD group -> model array -> geometry array -> vertex buffer, and the buffer's stride
        and count must fit inside the segment its data pointer lands in. A wrong pointer fails at
        one of those links; this cannot be talked into passing by an offset guess.
        """
        s = self.res.sys
        base = self._deref(self._p(tab, i * 0x20), 0x40)
        if base is None or base + ydr_write.DRAWABLE_SPAN > self.nsys:
            return 0
        best = 0
        for slot in ydr_write.LOD_SLOTS:
            _b, mh, seg = self._res(self._p(base, slot), 0x10)
            if mh is None or seg != 'sys':
                continue
            marr, nmod = _u32(s, mh), _u16(s, mh + 0x08)
            if not (0 < nmod <= 4096):
                continue
            _b, ma, seg = self._res(marr, nmod * 8)
            if ma is None or seg != 'sys':
                continue
            for mi in range(nmod):
                _b, mo, seg = self._res(_u32(s, ma + mi * 8), 0x30)
                if mo is None or seg != 'sys':
                    continue
                garr, ngeo = _u32(s, mo + 0x08), _u16(s, mo + 0x10)
                if not (0 < ngeo <= 4096):
                    continue
                _b, ga, seg = self._res(garr, ngeo * 8)
                if ga is None or seg != 'sys':
                    continue
                for gi in range(ngeo):
                    _b, g, seg = self._res(_u32(s, ga + gi * 8), 0x80)
                    if g is None or seg != 'sys':
                        continue
                    bv, vb, sgv = self._res(_u32(s, g + 0x18), 0x40)
                    if vb is None:
                        continue
                    stride = struct.unpack_from('<I', bv, vb + 0x08)[0]
                    cnt = struct.unpack_from('<I', bv, vb + 0x18)[0]
                    bd, vo, _sd = self._res(struct.unpack_from('<I', bv, vb + 0x10)[0], 1)
                    if bd is None or not (0 < stride <= 256 and 0 < cnt <= 1 << 22):
                        continue
                    if cnt * stride <= len(bd) - vo:
                        best = max(best, cnt * stride)
        return best

    def _drawable_array(self):
        """fragroot+0x38 -> a table of EXTRA drawables (damage states). Entry stride 0x20:
        u64 drawable ptr, name INLINE at entry+0x10. The TOTAL drawable count is a u8 at
        deref(fragroot+0xA8)+0x10, so the extras count is total-1.

        ⭐⭐⭐ THE GUARDED EXTRA ENTRY (2026-08-15), AND WHY IT IS NOT A COUNT REINTERPRETATION.
        `xm_prop_auto_salvage_stromberg.yft` reads `total = 1`, so `n = 0` and this walk models
        NOTHING - yet entry 0 holds a real drawable whose vertex buffer (stride 52 x count 5,038
        = 261,976 B) is the largest of that file's 615,750 unreproduced bytes, TO THE BYTE.
        ⛔ THE PREVIOUS PASS DECLINED TO ACT, AND ITS REASON WAS RIGHT AT THE TIME: it had six
        table-carrying files in a 231-file work queue, and *"a six-file sample cannot carry a
        change to a shared count reading"*. So the count reading is NOT changed. Entry `n` is
        modelled only when it RESOLVES - `_entry_resolves` above - and that predicate was scored
        on the whole game before it shipped.

        ⭐⭐ THE COMPLETE CENSUS, not a draw (`scratchpad/z2_pop2.py`, all 61,430 `.yft` read,
        0 refusals). 352 fragments carry a drawable table. Classifying the 0x20 bytes at index
        `n = total-1`, the first entry the count reading does not model:
              class                at index n     at index n+1 (the decoy)
              ZERO ...............     47              75
              NOPTR ..............    242             218
              GARBAGE ............     62              59
              DRAWABLE ...........  **1**           **0**
              TOTAL ..............    352             352
        **The predicate fires on 1 table in the game, and that one is the subject.** An unguarded
        "read one more entry" would have claimed 351 wrong ones; every one of them could have been
        accepted and was refused. The decoy column is the other half of it: at index n+1 nothing
        resolves, so this is not "there is always one more".
        ⚠ THE CENSUS IS DELIBERATELY CONSERVATIVE - it has no coverage map, so an entry whose
        bytes another structure already owns is still scored on its content. That can only ADD to
        the DRAWABLE count, so 1 of 352 is an UPPER BOUND on the false-fire rate.
        ⭐ `total = 1` WITH a table occurs on exactly ONE file game-wide; the other 351 read 2..27.
        """
        s = self.res.sys
        tab_p = self._p(0, 0x38)
        dsc = self._deref(self._p(0, 0xA8), 0x14)
        if not tab_p or dsc is None:
            return
        try:
            total = s[dsc + 0x10]
        except IndexError:
            return
        if total < 1 or total > 256:
            return
        n = total - 1
        tab = self._deref(tab_p, max(n, 1) * 0x20)
        if tab is None:
            return
        if self._entry_resolves(tab, n):
            n += 1
        if n <= 0:
            return
        self._put(tab, n * 0x20)
        for i in range(n):
            self._fragdrawable(self._deref(self._p(tab, i * 0x20), 0x40))

    def _bone_transforms(self):
        """fragroot+0xA8 -> array descriptor; records at +0x20, stride 0x30, one per BONE
        (crSkeletonData count, drawable+0x18 -> +0x5E u16). The count is taken from the
        SKELETON, never from the array under test."""
        s = self.res.sys
        bt = self._deref(self._p(0, 0xA8), 0x20)
        if bt is None:
            return
        self._put(bt, 0x20)
        main = self._deref(self._p(0, 0x30), 0x60)
        nb = 0
        if main is not None:
            sk = self._deref(self._p(main, 0x18), 0x60)
            if sk is not None:
                try:
                    nb = _u16(s, sk + 0x5E)
                except struct.error:
                    nb = 0
        if 0 < nb <= 4096:
            self._put(bt + 0x20, nb * 0x30)

    def _glass_windows(self):
        """fragroot+0xE0 -> ptr array (u8 count @+0xD9); each item is a 0x70 record."""
        s = self.res.sys
        try:
            cnt = s[0xD9]
        except IndexError:
            return
        arr = self._deref(self._p(0, 0xE0), 1)
        if arr is None or not cnt or cnt > 4096:
            return
        self._put(arr, cnt * 8)
        for i in range(cnt):
            b = self._deref(self._p(arr, i * 8), 0x70)
            if b is not None:
                self._put(b, 0x70)

    def _vehicle_glass(self):
        """fragroot+0x120 -> the 'HWGV' breakable-glass manager. ⭐ THE BLOCK IS
        SELF-DESCRIBING: u32 totalSize @+0x08 covers the whole manager INCLUDING every
        shatter-map raster, so the variable-length rasters are captured by their own stored
        length rather than by filling to the next region."""
        s = self.res.sys
        man = self._deref(self._p(0, 0x120), 0x10)
        if man is None:
            return
        try:
            n = _u16(s, man + 0x06)
            total = _u32(s, man + 0x08)
        except struct.error:
            return
        if 0 < total <= 0x1000000:
            self._put(man, total)
        else:
            self._put(man, 0x20)
        if not n or n > 4096:
            return
        self._put(man, 0x0C + n * 8)
        for i in range(n):
            try:
                rec = man + _u32(s, man + 0x10 + i * 8)
            except struct.error:
                break
            self._put(rec, 0x80)

    def _frag_lights(self):
        """fragroot+0x110 -> LightAttrs array, u16 count @+0x118, stride 0xA8 (the same
        records the drawable light slot pair carries)."""
        s = self.res.sys
        try:
            n = _u16(s, 0x118)
        except struct.error:
            return
        if 0 < n <= 4096:
            self._flat(self._p(0, 0x110), n * 0xA8)

    # ---------------------------------------------------------------- physics
    def _physics(self):
        g = self._deref(self._p(0, 0xF0), LODG_SPAN)
        if g is None:
            return
        self._put(g, LODG_SPAN)
        for slot in LODG_SLOTS:
            self._lod_phys(self._deref(self._p(g, slot), LOD_SPAN))
        for q in range(0, LODG_SPAN, 4):
            self._chase(self._p(g, q))

    def _lod_phys(self, l1):
        if l1 is None:
            return
        s = self.res.sys
        self._put(l1, LOD_SPAN)
        try:
            ng = s[l1 + 0x11A]
            nc = _u16(s, l1 + 0x11E)
        except (IndexError, struct.error):
            return
        # per-child parallel arrays - sized by the CHILD count, which is a different field
        # from the arrays themselves
        if 0 < nc <= 4096:
            self._flat(self._p(l1, 0x28), nc * 4)       # UnkFloat[nc]
            self._flat(self._p(l1, 0xF0), nc * 16)      # InertiaTensor[nc]
            self._flat(self._p(l1, 0xF8), nc * 16)      # UnkVec[nc]
        # ⭐⭐ +0xC8 IS A **SECOND PER-GROUP POINTER ARRAY**, `ng * 8` bytes - a slot the walk read
        # and never followed. It was NOT found by staring at the record: `scratchpad/dq6_who.py`
        # asked which unmodelled gaps are POINTED AT by a tagged pointer, and
        # `scratchpad/dq6_owner.py` traced the pointer back to the capture that already owned the
        # bytes holding it. That is the difference between "a gap after the polygon array" and
        # "a live pointer at `fragPhysicsLOD +0xC8`".
        # ⚠ THE HANDOVER CALLED THIS "tagged-pointer arrays after the polygon array". It is not
        # after the polygon array in any structural sense - it is an ALLOCATION the packer put
        # there, and all 9 of the gaps that led to it were POINTED AT. A gap that begins where
        # another array ends is not part of that array.
        # ⭐ MEASURED over 6,173 cached `.yft` (a uniform mod-40 draw of the whole game),
        # 5,923 arrays with room after them, blind walk disabled. Scoring `ceil(ng*8 / K) * K`
        # against the room to the next modelled structure OR next tagged-pointer target:
        #     K     FITS the room        EQUALS it exactly
        #      1    5,923 (100.00%)         211 ( 3.56%)
        #      2    5,923 (100.00%)         211 ( 3.56%)
        #      8    5,923 (100.00%)         211 ( 3.56%)
        #   **16**  5,923 (100.00%)     **5,916 (99.88%)**
        #     32      199 (  3.36%)         192 ( 3.24%)     <- overruns on 96.6%
        #     64       98 (  1.65%)          91 ( 1.54%)     <- overruns on 98.3%
        #   ⇒ the array holds EXACTLY `ng` entries and its allocation is rounded to 16 bytes.
        #     32 and 64 are refuted by the extent; 1/2/4/8 fit but explain 3.56% of it.
        # ⭐ AND A CONTENT LAW AGREES, independently of the extent: every 8-byte entry is a
        # TAGGED SYSTEM POINTER with a zero high word - **12,030 of 12,030 (100.00%)**.
        # ⚠ NOT CLAIMED, deliberately: the 16-byte allocation rounding. Non-zero bytes beyond
        # `ng * 8` measured **0** over all 5,923 arrays, so claiming the padding could not be
        # scored - it would be exactly the unpinned claim this measure exists to catch. The
        # table above is the evidence for `ng` entries of 8 bytes; the padding is left in place.
        # ⛔ COUNT-DERIVED, so it goes through `_flat`, which REFUSES rather than clamps.
        if 0 < ng <= 4096:
            self._flat(self._p(l1, 0xC8), ng * 8)
        # groups
        if 0 < ng <= 4096:
            garr = self._deref(self._p(l1, 0xC0), ng * 8)
            if garr is not None:
                self._put(garr, ng * 8)
                for i in range(ng):
                    nptr = self._deref(self._p(garr, i * 8), 1)
                    if nptr is not None and nptr >= 0x80:
                        self._put(nptr - 0x80, GROUP_SPAN)
        # children
        if 0 < nc <= 4096:
            carr = self._deref(self._p(l1, 0xD0), nc * 8)
            if carr is not None:
                self._put(carr, nc * 8)
                for i in range(nc):
                    self._child(self._deref(self._p(carr, i * 8), CHILD_SPAN))
        # archetypes (each owns a phBound graph -> the shared walker)
        for slot in (0xD8, 0xE0):
            self._archetype(self._deref(self._p(l1, slot), ARCH_SPAN))
        self._articulated(l1)
        # Transforms: u32 count @+0x10, records @+0x20 stride 0x40
        to = self._deref(self._p(l1, 0x100), 0x20)
        if to is not None:
            self._put(to, 0x20)
            try:
                tn = _u32(s, to + 0x10)
            except struct.error:
                tn = 0
            if 0 < tn <= 65536:
                self._put(to + 0x20, tn * 0x40)
        # UnknownData1/2 - u8 index tables
        for poff, coff in ((0x108, 0x118), (0x110, 0x119)):
            try:
                n = s[l1 + coff]
            except IndexError:
                continue
            if n:
                self._flat(self._p(l1, poff), n)
        for q in range(0, LOD_SPAN, 4):
            self._chase(self._p(l1, q))

    def _child(self, base):
        """fragTypeChild: +0xA0 drawable, +0xA8 the DAMAGED twin, +0xB0 EventSet.

        ⭐⭐ +0xB0 IS A FIXED 48-BYTE RECORD, and the walk had been reading the pointer without
        ever following it. `scratchpad/dq6_who.py` found the gaps by asking which unmodelled runs
        are POINTED AT rather than which ones look like a tail, and `dq6_owner.py` traced every
        one of the 61 subjects back to this single slot.
        ⚠ THE HANDOVER CALLED THIS A "type-4 48-byte trailer" after the polygon array. It is
        NOT a trailer: 61 of 61 were pointed at by a live tagged pointer, i.e. an allocation the
        packer happened to place after a polygon array. Sized as a tail it would have been a fill
        from one region's end to the next region's start.

        ⭐ MEASURED over 6,173 cached `.yft` (uniform mod-40 draw of the whole game), blind walk
        disabled - **8,890 live, uncovered +0xB0 targets**, scoring the room to the next modelled
        structure OR next tagged-pointer target:
            room == 48 bytes ..... 8,886 / 8,890 (99.955%)     room 80: 3   room 44: 1
        so any span wider than 48 overruns on essentially every record, which is what makes 48 a
        READ rather than a preference.
        ⭐ AND THE CONTENT IS CONSTANT, which the extent alone could not have told us:
            bytes +0x08..+0x30 all zero ......... 8,890 / 8,890 (100.00%)
            `u32 @ +0x04` == 1 .................. 8,890 / 8,890 (100.00%)
            non-zero bytes per record ........... 5.00 mean - the float at +0x00 plus that 1
        ⚠ WHAT THIS IS NOT: a reading of the record's MEANING. It claims a 48-byte allocation at
        a named slot. The float at +0x00 recurs verbatim across unrelated vehicles, which is a
        lead about what it is and is deliberately not turned into an interpretation here.
        ⛔ A FIXED SPAN, so it goes through `_put`, which CLAMPS at the segment end - see the
        `_put`/`_putn` split in `ydr_write`: a record that starts 44 bytes before the segment end
        demonstrably is 44 bytes long there.
        """
        if base is None:
            return
        self._put(base, CHILD_SPAN)
        for slot in (0xA0, 0xA8):
            self._fragdrawable(self._deref(self._p(base, slot), 0x40))
        self._put(self._deref(self._p(base, 0xB0), 8), CHILD_EVENTSET_SPAN)
        for q in range(0, CHILD_SPAN, 4):
            self._chase(self._p(base, q))

    def _archetype(self, ab):
        if ab is None:
            return
        self._put(ab, ARCH_SPAN)
        self._cstr(self._p(ab, 0x18))
        self._bound(self._p(ab, 0x20))          # the SHARED phBound walker (ybn offsets)
        for q in range(0, ARCH_SPAN, 4):
            self._chase(self._p(ab, q))

    def _articulated(self, l1):
        """LOD1+0x20 -> articulated body (animal ragdolls). ItemIndices inline u32[22] @+0x10,
        joint pointer TABLE @+0x78, UnknownVectors @+0x80 (16 B each), u8 bodies @+0x88,
        u8 joints @+0x89, ItemFlags u8[22] @+0x8A."""
        s = self.res.sys
        bs = self._deref(self._p(l1, 0x20), ARTB_SPAN)
        if bs is None:
            return
        self._put(bs, ARTB_SPAN)
        try:
            nb, nj = s[bs + 0x88], s[bs + 0x89]
        except IndexError:
            return
        if 0 < nb <= 256:
            self._flat(self._p(bs, 0x80), nb * 16)
        if 0 < nj <= 256:
            tab = self._deref(self._p(bs, 0x78), nj * 8)
            if tab is not None:
                self._put(tab, nj * 8)
                for i in range(nj):
                    it = self._deref(self._p(tab, i * 8), JOINT_SPAN)
                    if it is not None:
                        self._put(it, JOINT_SPAN)

    # ---------------------------------------------------------------- cloth
    def _cloths(self):
        """environmentCloth pgArray @ fragroot+0x60, u16 count @+0x68. The controller layout is
        the yld clothController's (yft2xml derived it from that module) plus a MorphController."""
        s = self.res.sys
        try:
            cnt = _u16(s, 0x68)
        except struct.error:
            return
        ap = self._deref(self._p(0, 0x60), 1)
        if ap is None or not cnt or cnt > 4096:
            return
        self._put(ap, cnt * 8)
        for i in range(cnt):
            item = self._deref(self._p(ap, i * 8), CLOTH_ITEM_SPAN)
            if item is None:
                continue
            self._put(item, CLOTH_ITEM_SPAN)
            self._fragdrawable(self._deref(self._p(item, 0x18), 0x40))
            ctrl = self._deref(self._p(item, 0x28), CLOTH_CTRL_SPAN)
            if ctrl is None:
                continue
            self._put(ctrl, CLOTH_CTRL_SPAN)         # name is INLINE at ctrl+0x58
            self._cloth_bridge(self._deref(self._p(ctrl, 0x10), CLOTH_BRIDGE_SPAN))
            self._cloth_morph(self._deref(self._p(ctrl, 0x18), 0x40))
            self._cloth_verlet(self._deref(self._p(ctrl, 0x20), CLOTH_VERLET_SPAN))
            for q in range(0, CLOTH_CTRL_SPAN, 4):
                self._chase(self._p(ctrl, q))

    def _arr(self, base, off, esize, cap=0x400000):
        """The pgArray shape used throughout cloth: {ptr @+0x00, u16 count @+0x08}."""
        s = self.res.sys
        try:
            n = _u16(s, base + off + 8)
        except struct.error:
            return
        if 0 < n <= cap:
            self._flat(self._p(base, off), n * esize)

    def _cloth_bridge(self, bg):
        if bg is None:
            return
        self._put(bg, CLOTH_BRIDGE_SPAN)
        for off, esz in ((0x20, 4), (0x60, 4), (0xA0, 4), (0xE0, 2), (0x128, 4)):
            self._arr(bg, off, esz)

    def _cloth_morph(self, mc):
        if mc is None:
            return
        self._put(mc, 0x40)
        u18 = self._deref(self._p(mc, 0x18), 0x200)
        if u18 is not None:
            self._put(u18, 0x200)
            self._morph_arrays(u18)

    def _morph_arrays(self, blk):
        """The morph block's OWN pgArrays - pointers this module held for 0x200 bytes and never
        followed. Same signature as every other gap this campaign has closed.

        ⭐ THE SUBJECT THAT FOUND IT, `barracks_hi.yft`: 3,024 bytes unreached, 0 tagged pointers
        appearing to target them - because the run does not START there. `_chase` covers the
        first 0x1000 of the array, so the residual is a TAIL and the pointer sits 4,096 bytes
        earlier. Walking the run backwards by its own content law gives 0x44e360 .. 0x44ff30 =
        7,120 B = 445 records, and the descriptor at `blk+0x50` reads
        `{ptr -> 0x44e360, u16 count 445, u16 capacity 445}` - 445 * 16 = 7,120 EXACTLY.
        ⚠ ITS TWIN `barracks.yft` HAS THE SAME BYTES AND SCORED EXACT, AND THAT WAS NOT EVIDENCE:
        they were inside a 442,368-byte `_bound` claim taken from `+0x90` on a **type-12** bound
        whose `u16 @+0xA0` read 55,296 - i.e. a self-fulfilling claim of the kind this measure
        exists to catch (see `ydr_write._bound`, reported not edited). "Owned in the other build"
        was an artefact, so the structure had to be found here rather than copied from there.

        LAYOUT - a pgArray descriptor, scanned on the 8-byte grid inside the block:
            +0x00 u64 tagged pointer | +0x08 u16 count | +0x0A u16 capacity | +0x0C u32 0
        ⛔ THE ELEMENT SIZE IS NOT DERIVABLE FROM THE ROOM, and that was measured before being
        abandoned: over 238 morph blocks the interval `room-15 <= count*esize <= room` admits a
        UNIQUE integer only sometimes and returns DIFFERENT integers for the same slot in
        different files (slot +0x50 gave 16 on eleven files and 36 on two). A room bound is an
        upper bound on the allocation, not on the array, so slot -> element size cannot be read
        off it. ⇒ the element size is decided by a law of the CONTENT, below.

        ⭐⭐ THE LAW, and it can REFUSE: every 16-byte record is `{float a, b, c, d}` with
        `|a + b + c - 1| <= 1e-3` - a barycentric triple (a point named by the triangle it lies
        on) plus a signed offset. Nothing is claimed unless it holds for ALL `count` records.
        MEASURED over 7,771 cached `.yft` (two whole-game draws), blind walk DISABLED,
        238 morph blocks, 164 descriptors passing the pgArray gate:
            subject passes ................. 26 / 164   (14 at +0x50, 12 at +0xA0, 0 elsewhere)
            subject FAILS at those slots ....  0
            records claimed ................ 2,353 x 16 B, 0 records violating the law
        FALSE-FIRE against EXACTLY-SIZED controls, evaluated at the site the rule is evaluated:
            an unrelated 16-aligned window of the same count*16 bytes ....  0 / 164   0.0000%
            the count*16 bytes immediately AFTER the array ...............  8 / 164   4.8780%
            the count*16 bytes immediately BEFORE the array ..............  8 / 164   4.8780%
        ⭐ The two neighbour decoys are not false fires, they are the SIBLING array: +0x50 and
        +0xA0 point at adjacent allocations, so each one's "neighbour window" is the other one's
        array. The control that is genuinely off-structure scores ZERO.
        ⛔ The gate is on the CONTENT, not on the slot number: +0x50 and +0xA0 are what this
        sample happens to use, and hard-coding them would be fitting the sample instead of
        reading the file.
        """
        s = self.res.sys
        for q in range(0, 0x200, 8):
            if blk + q + 16 > self.nsys:
                break
            p, hi, cnt, cap, tail = struct.unpack_from('<IIHHI', s, blk + q)
            if (p >> 28) != 5 or hi or tail or not cnt or cap != cnt:
                continue
            off = self._deref(p, cnt * 16)
            if off is None or off + cnt * 16 > self.nsys:
                continue
            if self._bary16(off, cnt):
                self._putn(off, cnt * 16)

    def _bary16(self, off, cnt):
        """`cnt` records of {float a,b,c,d} with a+b+c == 1. See `_morph_arrays` for the
        denominator and the false-fire rate; this is the test that lets the claim REFUSE."""
        s = self.res.sys
        for i in range(cnt):
            try:
                a, b, c, _d = struct.unpack_from('<4f', s, off + i * 16)
            except (struct.error, ValueError):
                return False
            if a != a or b != b or c != c:          # NaN never satisfies the law
                return False
            if abs((a + b + c) - 1.0) > 1e-3:
                return False
        return True

    def _cloth_verlet(self, vc):
        if vc is None:
            return
        self._put(vc, CLOTH_VERLET_SPAN)
        self._arr(vc, 0x80, 16)          # vertices (vec4)
        self._arr(vc, 0x110, 16)         # constraints
        self._bound(self._p(vc, 0x18))   # cloth CUSTOM bounds - a full composite phBound
        for q in range(0, CLOTH_VERLET_SPAN, 4):
            self._chase(self._p(vc, q))


def read_yft(src):
    blob = bytes(src) if isinstance(src, (bytes, bytearray)) else open(src, 'rb').read()
    _m, _v, sysf, gfxf = struct.unpack_from('<4sIII', blob, 0)
    return Yft(Res.from_bytes(blob), (sysf, gfxf))
