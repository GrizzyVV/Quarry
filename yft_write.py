"""yft_write - ROUND-TRIP WRITER for .yft fragments (RSC7 v162 / v160).

COVERAGE 2026-08-14: **99.9990%** overall - system 99.9990%, graphics 100.00% -
**235 / 330 files byte-exact** over a STRATIFIED sample (120 vehicles / 155 props / 55 peds
from x64e, x64c, x64f, x64g, x64a, x64d). Remaining defect: the gap map at the end of this
docstring.

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

THE REMAINING GAP (0.0010% of system bytes, VEHICLES ONLY - props read 99.9999%, peds 100%).
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

    def _skeleton(self, base):
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

    def _drawable_array(self):
        """fragroot+0x38 -> a table of EXTRA drawables (damage states). Entry stride 0x20:
        u64 drawable ptr, name INLINE at entry+0x10. The TOTAL drawable count is a u8 at
        deref(fragroot+0xA8)+0x10, so the extras count is total-1."""
        s = self.res.sys
        tab_p = self._p(0, 0x38)
        dsc = self._deref(self._p(0, 0xA8), 0x14)
        if not tab_p or dsc is None:
            return
        try:
            total = s[dsc + 0x10]
        except IndexError:
            return
        if total <= 1 or total > 256:
            return
        n = total - 1
        tab = self._deref(tab_p, n * 0x20)
        if tab is None:
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
        """fragTypeChild: +0xA0 drawable, +0xA8 the DAMAGED twin, +0xB0 EventSet."""
        if base is None:
            return
        self._put(base, CHILD_SPAN)
        for slot in (0xA0, 0xA8):
            self._fragdrawable(self._deref(self._p(base, slot), 0x40))
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
