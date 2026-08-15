"""ybd_write - ROUND-TRIP WRITER for .ybd bound dictionaries (RSC7 v40 / v42 / v43).

    inflated system segment -> value model -> written back -> MUST reproduce the original bytes

=============================================================================================
⛔⛔ WHAT `.ybd` IS, AND WHY THE "IT IS NOT PASSTHROUGH" TRAP DOES NOT APPLY TO THIS MEASURE.
`docs/LANE_CENSUS_20260814.md` F2 flags `.ybd` as a trap: quarry's `.ybd` branch writes the
INFLATED RESOURCE BODY under the ORIGINAL filename, so a filename-based classifier calls it "kept
binary" while the bytes on disk are not the archive's bytes -
    ped_props.ybd          disk  8,192 B   archive    337 B
    des_heli_biotech.ybd   disk 40,960 B   archive 24,285 B
    des_setpiece.ybd       disk 34,712 B   archive 34,604 B
⭐ THAT IS A STATEMENT ABOUT THE CORPUS EXPORT, NOT ABOUT THE FORMAT, and the ratio says so:
337 B of archive payload inflating to an 8,192 B system segment is a deflate stream expanding
24x, exactly like every other RSC7 resource in the game. Measured here on all four files: sys
8,192 / 57,344 / 40,960 / 8,192, gfx 0 / 0 / 0 / 0, and the "disk" sizes above are those inflated
system segments (`des_setpiece` 34,712 is that file's own truncation, not a second format).
⇒ ROUND-TRIP FOR `.ybd` MEANS THE SAME THING IT MEANS IN EVERY OTHER LANE: take the ARCHIVE
payload, inflate it, model it, write it back, compare the inflated system segment. Nothing about
this measure runs through the corpus export, so nothing about it is affected by what that export
names its output. The number below is not forced; the question was mis-scoped, not unanswerable.
⚠ WHAT REMAINS TRUE FROM F2, and it is a CORPUS defect worth fixing separately: the exported file
is not archive-identical, so a sha1 comparison against the archive will keep reporting 4 of 4
different, by design. That is the export's business.
=============================================================================================

`.ybd` is a **pgDictionary<phBound>** - the same shell as `.yed`/`.yld`/`.yfd`/`.ytd`/`.ydd`, with
phBound items. Population 2026-08-15, all 4 files / 10 bounds: type 3 box (3), type 4 geometry
(1), type 8 geometry-BVH (4), type 10 composite (2).

⚠⚠ THREE CONTAINER VERSIONS IN FOUR FILES (v43, v42 x2, v40) - the widest version spread of any
lane in this group, and it is not cosmetic: **THE GEOMETRY BLOCK AND THE RECORD SPAN BOTH MOVE**.
⛔ `was:` an early draft of this header said "every span matches the per-type table `ybn_write`
measured over 71,912 bounds ... type 8 room 336 = 0x150 (3 of 4; the 4th has 6,752 B of room,
i.e. slack, never less)". THAT WAS WRONG AND THE WRITER PROVED IT. The type-8 bounds in the v42
file sit 320 bytes apart, so 0x150 was not slack - it was a header claim running 16 bytes INTO
THE NEXT BOUND. It only looked like slack because the earlier probe measured room from each item
to the next ITEM rather than to the next ALLOCATION. See GEOM_LAYOUTS and `_fits`: the layout and
the span are now SELECTED per bound by a test that can refuse, and an ambiguous bound refuses
instead of being scored.
    v43   type 8 span 0x150   type 4 span 0x130   room measured 336
    v42   type 8 span 0x140   type 4 span 0x120*  room measured 320   (* unwitnessed)
    v40   type 8 span 0x150   type 4 span 0x130   room measured 336 / 304
    type 3 span 0x70 (room 112, 3/3)   type 10 span 0xB0 (room 176, 2/2)

MODEL, NOT MEMCPY: `pgdict_write.Model.carry()` is called ZERO times. The phBound headers are
claimed through `pgdict_write.tile`, which fills unnamed slots with u32 words - so the byte
account reports them as `value_words`, not as understanding.
=============================================================================================
COVERAGE AT POPULATION 2026-08-15 - THE LANE IS CLOSED. Every `.ybd` in the game:
    EXACT round-trip (every byte of the inflated system segment) : **4 / 4 = 100.0000%**
    mean coverage 100.0000%   min 100.000%   residual 0 bytes   refusals 0
  BYTE ACCOUNT (the split that decides whether the 100% is worth anything):
    VALUE  88,532 B = 77.1938% (85,870 NAMED + 2,662 unnamed WORDS)   re-encoded from a decoded value, never memcpy'd
    DERIVED 16 B = 0.0140%   the page-count word, COMPUTED from the RSC7 flags
    CARRIED 0 B = 0.0000% <- `Model.carry()` is called ZERO times in this lane
    ZERO-FILL 26,140 B = 22.7923%   never claimed; the ORIGINAL byte is zero (padding + block-map records)
    ZERO-RESIDUAL 0 bytes   never claimed and NON-ZERO in the original - the finding, and it is empty
  MUST-FAIL CONTROL (`python tools/pgdict_control.py --lane ybd --limit 500 --cap 0`):
    VALUE  ....... 9,968 / 9,968 moved the image (100.0000%)
    DROP   ....... 7,880 / 9,968 (79.05%); escapes are all-zero claims
    OFFSET ....... 7,876 / 9,968 (79.01%)
    STRIDE ....... span table: 2 broke / 2 NO SUBJECT | geom types: 1 broke / 3 NO SUBJECT.
           **0 ESCAPED.** A file holding no bound of the perturbed kind cannot react, and the
           control proves that by comparing CLAIM LISTS rather than assuming it.
> REPRODUCE: `python tools/roundtrip_coverage.py --lane ybd --limit 500 --cap 0`
=============================================================================================
ASCII output only.
"""
import os
import struct
import sys as _sys

_sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pgdict_write  # noqa: E402
from pgdict_write import Model, ModelError, tile  # noqa: E402

# per-type record spans - `ybn_write.BOUND_SPAN_BY_TYPE`, re-confirmed by the allocation here
BOUND_SPAN = {0: 0x70, 1: 0x80, 3: 0x70, 4: 0x130, 8: 0x150, 10: 0xB0, 13: 0x80}
_BOUND_FIELD_CACHE = {}


def bound_fields(btype, span):
    """The tiled field map for a phBound header of `span` bytes. Cached per (type, span) because
    the span is chosen per bound - see GEOM_LAYOUTS."""
    key = (btype, span)
    if key not in _BOUND_FIELD_CACHE:
        _BOUND_FIELD_CACHE[key] = tile({0x10: ('<B', 'bound_type')}, span, 'phBound %d' % btype)
    return _BOUND_FIELD_CACHE[key]
BVH_SPAN = 0x80
BVH_FIELDS = tile({0x00: ('<I', 'bvh_nodes_ptr'), 0x08: ('<I', 'bvh_node_count'),
                   0x0C: ('<I', 'bvh_node_capacity'),
                   0x70: ('<I', 'bvh_tree_ptr'), 0x78: ('<H', 'bvh_tree_count'),
                   0x7A: ('<H', 'bvh_tree_capacity')}, BVH_SPAN, 'BVH block')
GEOM_TYPES = (4, 8)

# ⭐⭐ THREE GEOMETRY LAYOUTS, ONE PER CONTAINER VERSION - AND THE FILE PICKS ITS OWN.
# `ybn_write` measured its map over 71,912 bounds, every one of them RSC7 v43. The `.ybd` lane
# holds v43, v42 AND v40, and the older two do NOT use that map: v43's `nverts @+0xD0` reads 0 on
# both, which is why importing the map refused them rather than mis-scoring them.
# Derived 2026-08-15 by dumping every non-zero slot of each geometry bound and matching pointer
# extents to the room to the next allocation (`des_setpiece` 505 verts x 6 = 3,030 B ending at
# 0x00CBD6 with the next structure at 0x00CBE0; `des_heli_biotech` 600 polys x 16 = 9,600 B
# ending EXACTLY on its neighbour).
# ⚠ DENOMINATOR, STATED PLAINLY: the v42 and v40 maps have ONE WITNESS FILE EACH (2 and 1
# geometry bounds). They are not general claims about those container versions - they are what
# these files contain. `_fits` is what keeps that honest: the layout is SELECTED by evidence per
# bound and an ambiguous bound refuses, so a wrong map cannot be applied silently to a file it
# does not describe.
GEOM_LAYOUTS = (
    dict(name='v43', polys=0x88, verts=0xB0, verts2=0x78, vcol=0xB8, nverts=0xD0,
         mats=0xF0, matcol=0xF8, polymats=0x118, nmat=0x120, bvh=0x130, sentinel=0x140,
         span8=0x150, span4=0x130),
    dict(name='v42', polys=0x88, verts=0xB0, verts2=0x78, vcol=0xB8, nverts=0xC8,
         mats=0xE0, matcol=0xE8, polymats=0x108, nmat=0x110, bvh=0x120, sentinel=0x130,
         span8=0x140, span4=0x120),
    dict(name='v40', polys=0x98, verts=0xC0, verts2=0x88, vcol=0xC8, nverts=0xD8,
         mats=0xF0, matcol=0xF8, polymats=0x118, nmat=0x120, bvh=0x130, sentinel=0x140,
         span8=0x150, span4=0x130),
)
# ⭐⭐ THE RECORD SPAN MOVES WITH THE LAYOUT TOO, and importing a fixed 0x150 CORRUPTED THE WALK
# rather than merely under-reading: `des_heli_biotech`'s two type-8 bounds sit at 0x8460 and
# 0x85A0 - 320 bytes apart - so a 0x150 (336 B) header claim ran 16 bytes INTO THE NEXT BOUND'S
# HEADER, and the claim-overlap guard is what caught it. Under the v42 map the record ends at the
# end sentinel + 0x10 = 0x140 = exactly 320, which is the room the allocation gives it.
# ⇒ `span8 == sentinel + 0x10` on all three maps (0x140+0x10=0x150, 0x130+0x10=0x140), and the
# rooms agree: v43 336, v42 320, v40 336, each equal to the distance to the next allocation.
# ⚠ `span4` for v42 is UNWITNESSED (no type-4 bound occurs in a v42 file here); it is carried as
# span8 - 0x20, the same relation v43/v40 show, and flagged rather than presented as measured.


class Ybd(Model):
    def __init__(self, res, flags=(0, 0)):
        Model.__init__(self, res, flags, what='ybd')
        if res.version not in (40, 42, 43):
            raise ModelError('ybd expects RSC7 version 40/42/43, got %d' % res.version)
        self.aliased = {}          # tag -> how many arrays aliased an existing one
        self.absent = {}           # tag -> how many arrays are NULL-pointer-absent
        self.layouts = {}          # geometry layout name -> how many bounds chose it
        self._targets = None
        self.items = self.read_shell()
        self.nbound = 0
        for off in self.items:
            self._bound(off)

    def _flat(self, tagged, code, count, tag):
        """One pointed array, decoded PER RECORD.

        ⭐ ALIASING IS A REAL FEATURE OF THIS FORMAT AND IS HANDLED EXPLICITLY, NOT SWALLOWED.
        A geometry bound's +0x78 slot is a SECOND vertex array, and `ybn_write` measured it
        pointing somewhere OTHER than +0xB0 on 1,979 of 1,982 bounds - i.e. on the other 3 the two
        slots point at the SAME allocation. In `.ybd` that case is the majority, and the first
        run of this writer raised on it at 0x160.
        ⛔ THE SKIP IS GATED ON **FULL** COVERAGE. If the span is entirely claimed already, the
        two pointers name one allocation and re-claiming it would double-count. If it is only
        PARTIALLY claimed, that is a stride or offset error and `rd` refuses - which is the whole
        reason the guard is at the claim rather than at the total."""
        if not count:
            return
        if not tagged:
            # ⭐ A NULL POINTER WITH A LIVE COUNT MEANS THE ARRAY IS ABSENT, and that is the
            # format's own idiom rather than a tolerance: `ybn_write` records that vertex colours
            # are "OPTIONAL with a count that is always non-zero, so absence is signalled by the
            # POINTER alone". Counted, never silent - `self.absent` is reported by the harness.
            self.absent[tag] = self.absent.get(tag, 0) + 1
            return
        n = count * struct.calcsize(code)
        base = self.deref(tagged, n)
        if base is None:
            raise ModelError('ybd: %s (%d records) does not fit the segment' % (tag, count))
        if self.covered(base, n):
            self.aliased[tag] = self.aliased.get(tag, 0) + 1
            return
        self.rd_array(base, code, count, tag)   # stride == record size in this lane

    def _bound(self, off, depth=0):
        if depth > 32 or not self.once(off):
            return
        s = self.res.sys
        btype = s[off + 0x10]
        span = BOUND_SPAN.get(btype)
        if span is None:
            raise ModelError('ybd: unwitnessed phBound type %d at 0x%x' % (btype, off))
        self.nbound += 1
        if btype in GEOM_TYPES:
            ok = [L for L in GEOM_LAYOUTS if self._fits(L, off, btype)]
            if len(ok) != 1:
                raise ModelError('ybd: %d of %d geometry layouts fit the bound at 0x%x - a bound '
                                 'whose layout is ambiguous is not measured, it is guessed'
                                 % (len(ok), len(GEOM_LAYOUTS), off))
            span = ok[0]['span8'] if btype == 8 else ok[0]['span4']
        self.rd_fields(off, bound_fields(btype, span), span, 'phBound type %d' % btype)
        self._octant_map(off)
        if btype in GEOM_TYPES:
            self._geometry(off)
        if btype == 8:
            self._bvh(off, self._bvh_slot(off))
        if btype != 10:
            return
        # ---- composite
        n = struct.unpack_from('<H', s, off + 0xA0)[0]
        if not n:
            return
        carr = self.deref(struct.unpack_from('<I', s, off + 0x70)[0], n * 8)
        if carr is None:
            raise ModelError('ybd: composite child array does not fit')
        kids = [v[0] for v in self.rd_array(carr, '<Q', n, 'composite_child_ptr')]
        # ⛔ THE AABB STRIDE IS RE-MEASURED PER LANE, NEVER INHERITED. `.yld` (RSC7 v8) stores
        # n * 64 at +0x80 - two AABBs per child - while `ybn_write` (v43) measured n * 32 at
        # +0x88 and the flags at +0x90. Which slot and which stride a container version uses is
        # the kind of thing that must come from the file, so both candidates are tried against
        # the ALLOCATION and only the one that fits is claimed (see `_composite_arrays`).
        self._composite_arrays(off, n)
        self._bvh(off, 0xA8)
        for k in kids:
            if not k:
                continue
            c = self.deref(k & 0xFFFFFFFF, 1)
            if c is not None:
                self._bound(c, depth + 1)

    def _composite_arrays(self, off, n):
        """⭐ THE `.ybd` COMPOSITE USES `ybn_write`'s v43 MAP, NOT `.yld`'s - AABB at +0x88 with
        stride 32, flags at +0x90. The one composite in the lane (des_coroner_window, RSC7 v42)
        proved it by REFUSING the other reading: claimed as n*8 flags, +0x88 left 24 of its 32
        bytes as residual, and those bytes read as the second half of an AABB pair -
        {-0.01, -0.7, -0.478, 1} then {0.01, 0.7, 0.478, 0.0025}, a min/max vec4 pair.
        ⚠ DENOMINATOR: 1 composite, in 1 file. That is the whole population of composites in this
        lane and it is stated rather than dressed up - `ybn_write`'s 15,139-file measurement is
        what carries the weight here, and this file agrees with it."""
        s = self.res.sys
        for slot, stride, tag in ((0x78, 64, 'composite_transform'),
                                  (0x88, 32, 'composite_aabb'),
                                  (0x90, 8, 'composite_flags')):
            p = struct.unpack_from('<I', s, off + slot)[0]
            if not p:
                continue
            self._flat(p, '<%dI' % (stride // 4), n, tag)

    def _bvh_slot(self, off):
        """The BVH slot moves with the geometry layout (it is the last field before the end
        sentinel). Selected by the same refutable test; a bound with no unambiguous layout gets
        NO BVH read at all rather than a read at a guessed offset."""
        ok = [L for L in GEOM_LAYOUTS if self._fits(L, off, self.res.sys[off + 0x10])]
        return ok[0]['bvh'] if len(ok) == 1 else None

    def _room(self, o):
        """Distance from `o` to the next live allocation in the file - the upper bound any span
        has to respect. Computed once per file from every tag-5 pointer site."""
        if self._targets is None:
            s, t = self.res.sys, set()
            for k in range(0, self.size - 4, 4):
                v = struct.unpack_from('<I', s, k)[0]
                if (v >> 28) == 5 and 0 < (v & 0x0FFFFFFF) < self.size:
                    t.add(v & 0x0FFFFFFF)
            self._targets = sorted(t)
        for x in self._targets:
            if x > o:
                return x - o
        return self.size - o

    def _fits(self, L, off, btype):
        """Does geometry layout `L` describe the bound at `off`? EVERY clause can refuse.

        ⭐⭐ THIS IS A SELECTION, NOT A VERSION SWITCH, and that is deliberate. Three of the four
        `.ybd` in the game carry three DIFFERENT geometry layouts, one per RSC7 version, on a
        sample of ONE FILE EACH. Keying off `res.version` would therefore be a rule fitted to a
        single witness per branch - it would "work" on this lane and tell nobody whether it is
        true. Instead the file is asked to CHOOSE its own layout, and the choice has to be
        UNAMBIGUOUS: exactly one candidate may pass, or the bound REFUSES.
        The clauses are the ones a wrong layout fails on:
          * both counts inside the witnessed range (a float read as a count is astronomically
            large, a pointer read as a count carries the 0x5 tag in its top nibble)
          * the u16 END SENTINEL is 0xFFFF at the layout's own offset (`ybn_write` names it at
            +0x140 for v43; it sits at +0x130 in the v42 map)
          * every array pointer is tag-5 AND its extent fits the ROOM to the next live allocation
        On this lane the sentinel alone separates all three candidates, and the extent tests then
        confirm the choice independently.
        """
        s = self.res.sys
        span = L['span8'] if btype == 8 else L['span4']
        if span > self._room(off):
            return False           # the record would run into the next allocation
        try:
            # ⛔ THE SENTINEL CLAUSE ONLY APPLIES WHERE THE RECORD HAS ONE. A type-4 bound ENDS
            # at span4, before the sentinel offset, so testing it there would read the next
            # structure - the same "aim a read at ground the record does not own" mistake
            # `ybn_write` corrected for its +0x130 slot. Type 4 is separated by the extent tests
            # alone, and on the one type-4 bound in the lane exactly one layout still fits.
            if L['sentinel'] + 2 <= span:
                if struct.unpack_from('<H', s, off + L['sentinel'])[0] != 0xFFFF:
                    return False
            elif btype == 8:
                return False
            nverts = struct.unpack_from('<I', s, off + L['nverts'])[0]
            npolys = struct.unpack_from('<I', s, off + L['nverts'] + 4)[0]
            nmat = s[off + L['nmat']]
        except struct.error:
            return False
        if not (0 < nverts <= 0x8000 and 0 < npolys <= 0x100000 and 0 < nmat <= 0xFF):
            return False
        for slot, need in ((L['verts'], nverts * 6), (L['polys'], npolys * 16),
                           (L['polymats'], npolys), (L['mats'], nmat * 8)):
            p = struct.unpack_from('<I', s, off + slot)[0]
            if (p >> 28) != 5:
                return False
            o = p & 0x0FFFFFFF
            if o + need > self.size or need > self._room(o):
                return False
        return True

    def _geometry(self, off):
        """A geometry bound's payload arrays.

        ⛔⛔ THE GEOMETRY BLOCK MOVED BETWEEN CONTAINER VERSIONS, AND IMPORTING v43's MAP REFUSED
        BOTH OLDER FILES. `ybn_write` measured `nverts @+0xD0 / npolys @+0xD4 / polygons @+0x88 /
        vertices @+0xB0` over 71,912 bounds - every one of them RSC7 v43. In the v40 and v42
        `.ybd` those slots read 0/0 and the writer said so instead of scoring: the counts are at
        **+0xD8 / +0xDC** and the array pointers at **+0x98 / +0xC0**.
        ⭐ AND EACH MAP IS PINNED BY THE ALLOCATION, not by which numbers looked plausible.
        `des_setpiece.ybd` bound 0: nverts 505 at +0xD8, vertices pointer 0x00C000 at +0xC0, and
        505 * 6 = 3,030 bytes ends at 0x00CBD6 - with the NEXT live structure, that bound's own
        header, beginning at 0x00CBE0. A wrong count or a wrong slot cannot land on a boundary
        10 bytes away; the v43 reading does not even produce a non-zero count.
        ⚠ DENOMINATOR: 3 geometry bounds across 2 files is the entire v40/v42 population of this
        lane. It is a small sample and it is the whole sample.

        THE COUNTS COME FROM THE RECORD, so a wrong offset yields a count that does not fit the
        segment and REFUSES rather than claiming ground."""
        ok = [L for L in GEOM_LAYOUTS if self._fits(L, off, self.res.sys[off + 0x10])]
        if len(ok) != 1:
            raise ModelError('ybd: %d of %d geometry layouts fit the bound at 0x%x - a bound '
                             'whose layout is ambiguous is not measured, it is guessed'
                             % (len(ok), len(GEOM_LAYOUTS), off))
        L = ok[0]
        self.layouts[L['name']] = self.layouts.get(L['name'], 0) + 1
        s = self.res.sys
        nverts = struct.unpack_from('<I', s, off + L['nverts'])[0]
        npolys = struct.unpack_from('<I', s, off + L['nverts'] + 4)[0]
        nmat = s[off + L['nmat']]
        nmatcol = s[off + L['nmat'] + 1]
        g = lambda o: struct.unpack_from('<I', s, off + o)[0]      # noqa: E731
        self._flat(g(L['verts']), '<3h', nverts, 'bound_vertex')
        self._flat(g(L['verts2']), '<3h', nverts, 'bound_vertex2')
        self._flat(g(L['vcol']), '<4B', nverts, 'bound_vertex_colour')
        self._flat(g(L['polys']), '<16B', npolys, 'bound_polygon')
        self._flat(g(L['mats']), '<2I', nmat, 'bound_material')
        self._flat(g(L['polymats']), '<B', npolys, 'bound_poly_material')
        self._flat(g(L['matcol']), '<4B', nmatcol, 'bound_material_colour')

    def _octant_map(self, off, n=8):
        """phBound +0xC0 / +0xC8 - the octant map, SELF-DESCRIBING (`ybn_write._octant_map`).
        The arithmetic `ptr[k+1] - ptr[k] == counts[k] * 4` is checked BEFORE anything is
        claimed; when the law fails NOTHING is claimed, so a misread costs coverage rather than
        inventing it."""
        s = self.res.sys
        if off + 0xD0 > self.size:
            return
        cp, tp = struct.unpack_from('<I', s, off + 0xC0)[0], struct.unpack_from('<I', s, off + 0xC8)[0]
        if not cp or not tp:
            return
        cb, tb = self.deref(cp, n * 4), self.deref(tp, n * 8)
        if cb is None or tb is None:
            return
        counts = [struct.unpack_from('<I', s, cb + k * 4)[0] for k in range(n)]
        ptrs = [struct.unpack_from('<I', s, tb + k * 8)[0] for k in range(n)]
        if any((p >> 28) != 5 for p in ptrs) or any(c > 0x100000 for c in counts):
            return
        offs = [p & 0x0FFFFFFF for p in ptrs]
        if offs[0] != tb + n * 8:
            return
        if any(offs[k + 1] - offs[k] != counts[k] * 4 for k in range(n - 1)):
            return
        if offs[-1] + counts[-1] * 4 > self.size:
            return
        self.rd_array(cb, '<I', n, 'octant_count')
        self.rd_array(tb, '<Q', n, 'octant_ptr')
        for k in range(n):
            self.rd_array(offs[k], '<I', counts[k], 'octant_index')

    def _bvh(self, off, slot):
        """The 0x80-byte BVH block, SELF-VALIDATING - `ybn_write._bvh`'s four laws, every one of
        which can refuse. When a law fails NOTHING is claimed."""
        if slot is None:
            return
        s = self.res.sys
        if off + slot + 4 > self.size:
            return
        p = struct.unpack_from('<I', s, off + slot)[0]
        if (p >> 28) != 5:
            return
        d = self.deref(p, BVH_SPAN)
        if d is None or not self.once(d):
            return
        if any(s[d + 0x10:d + 0x20]):                                             # L1
            return
        bmin = struct.unpack_from('<3f', s, d + 0x20)
        bmax = struct.unpack_from('<3f', s, d + 0x30)
        sinv = struct.unpack_from('<3f', s, d + 0x50)
        scl = struct.unpack_from('<3f', s, d + 0x60)
        cnt, cap = struct.unpack_from('<II', s, d + 0x08)
        tcnt, tcap = struct.unpack_from('<HH', s, d + 0x78)
        if not all(abs(scl[k] * sinv[k] - 1.0) < 1e-3 for k in range(3)):         # L2
            return
        if not all(abs((bmax[k] - bmin[k]) * sinv[k] - 65535.0) < 655.35          # L3
                   for k in range(3)):
            return
        if tcnt != tcap:                                                          # L4
            return
        self.rd_fields(d, BVH_FIELDS, BVH_SPAN, 'BVH block')
        # capacity sizes the node array - `ybn_write` measured `capacity - count` in {0,1,2} over
        # 901 blocks and the capacity TAIL overlapping another modelled structure in 0 of 901.
        if 0 < cap <= 0x200000 and cnt <= cap:
            self._flat(struct.unpack_from('<I', s, d + 0x00)[0], '<16B', cap, 'bvh_node')
        if tcap:
            self._flat(struct.unpack_from('<I', s, d + 0x70)[0], '<16B', tcap, 'bvh_tree')


def read_ybd(src):
    return pgdict_write.read(src, Ybd)
