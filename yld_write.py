"""yld_write - ROUND-TRIP WRITER for .yld cloth dictionaries (RSC7 v8).

    inflated system segment -> value model -> written back -> MUST reproduce the original bytes

WHY: `.yld` had a READER (`yld2xml.py`) and no writer, which under the 2026-08-13 ruling makes it
**UNMEASURED, not passing** - `docs/LANE_CENSUS_20260814.md` row 12, 61 files.

MODEL, NOT MEMCPY: every byte reproduced was decoded with a struct format and re-packed from the
decoded value. `pgdict_write.Model.carry()` - the only verbatim-copy primitive in the group - is
called ZERO times in this file.

⚠ AND THE HONEST HALF OF THAT: this lane is where `value_named` and `value_words` diverge. A
characterCloth's sub-structures are 0xF0/0x140/0x180 bytes each and `yld2xml` names roughly a
third of their slots; the rest are claimed as UNNAMED WORDS through `pgdict_write.tile`, which
proves the SPAN was reached and proves nothing about what the bytes mean. The byte account keeps
the two columns apart precisely so that distinction cannot be quietly rounded away.

⭐ EVERY SPAN BELOW IS PINNED BY THE ALLOCATION, measured over ALL 59 distinct `.yld` in the game
(`scratchpad/probe_yld.py`); the room from each structure to the next live pointer target is the
same value on 59 of 59 with no slack anywhere, so a wider span over-runs on every file:
    characterCloth item .... 0xD0     clothController ... 0xF0
    BridgeSimGfx ........... 0x140    VerletCloth1 ...... 0x180
    phBoundComposite root .. 0xB0     (the same 0xB0 `ybn_write` measured on 15,139 files)

⭐⭐ WHAT THE WRITER FOUND THAT THE READER COULD NOT - THREE MORE ARRAYS.
`yld2xml`'s map has no entry for any of these; each is a live pointer with a live count on the
population, so a writer that trusted the reader's map would leave their payloads at zero:
    characterCloth +0x10 ... live on  9 of 59 items, element stride 16
    VerletCloth1  +0x130 ... live on 59 of 59, element stride 16
    VerletCloth1  +0x140 ... live on 59 of 59, element stride 16
A reader may omit a field; a writer cannot.

⚠ SCOPE: the INFLATED SYSTEM SEGMENT, not the compressed RSC7 container. `.yld` carries no
graphics segment (59/59) and a non-empty one REFUSES.
=============================================================================================
COVERAGE AT POPULATION 2026-08-15 - THE LANE IS CLOSED. Every `.yld` in the game:
    EXACT round-trip (every byte of the inflated system segment) : **61 / 61 = 100.0000%**
    mean coverage 100.0000%   min 100.000%   residual 0 bytes   refusals 0
  BYTE ACCOUNT (the split that decides whether the 100% is worth anything):
    VALUE  1,822,330 B = 87.9258% (1,705,059 NAMED + 117,271 unnamed WORDS - see the note above)   re-encoded from a decoded value, never memcpy'd
    DERIVED 244 B = 0.0118%   the page-count word, COMPUTED from the RSC7 flags
    CARRIED 0 B = 0.0000% <- `Model.carry()` is called ZERO times in this lane
    ZERO-FILL 250,002 B = 12.0624%   never claimed; the ORIGINAL byte is zero (padding + block-map records)
    ZERO-RESIDUAL 0 bytes   never claimed and NON-ZERO in the original - the finding, and it is empty
  MUST-FAIL CONTROL (`python tools/pgdict_control.py --lane yld --limit 500 --cap 0`):
    VALUE  ....... 321,528 / 321,528 moved the image (100.0000%)
    DROP   ....... 277,251 / 321,528 (86.23%); escapes are all-zero claims
    OFFSET ....... 277,190 / 321,528 (86.21%)
    STRIDE ....... 3 mutations, **0 ESCAPED**: Vec4 16, BoneWeights 32, constraint 16 each
           REFUSED all 61 files when perturbed
> REPRODUCE: `python tools/roundtrip_coverage.py --lane yld --limit 500 --cap 0`
=============================================================================================
ASCII output only.
"""
import os
import struct
import sys as _sys

_sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pgdict_write  # noqa: E402
from pgdict_write import Model, ModelError, tile, F32, F32x4  # noqa: E402

ITEM, CTRL, BRIDGE, VERLET = 0xD0, 0xF0, 0x140, 0x180
# ⭐ NAMED SO THE CONTROL CAN PATCH THEM (`tools/pgdict_control.py`). The four SPANS above are
# consumed by `tile()` at import, so they are pinned by `check_tiling`; these STRIDES are what a
# runtime perturbation can bite on.
VEC4_STRIDE = 16
BONEWEIGHT_STRIDE = 32
CONSTRAINT_STRIDE = 16

# ---- sparse maps: {offset: (code, name)}; `tile` fills every gap with UNNAMED u32 words, so the
# record span is claimed in full while the accounting still separates named fields from filler.
ITEM_FIELDS = tile({
    0x00: ('<Q', 'vtable'),
    0x10: ('<I', 'arr10_ptr'), 0x18: ('<H', 'arr10_count'), 0x1A: ('<H', 'arr10_capacity'),
    0x20: ('<I', 'controller_ptr'),
    0x28: ('<I', 'bounds_ptr'),
    0x30: ('<I', 'bones_ptr'), 0x38: ('<H', 'bones_count'), 0x3A: ('<H', 'bones_capacity'),
    # ⭐ +0x90 - A THIRD ITEM ARRAY, and it is BEHIND the 4x4 Transform block (0x50..0x90) that
    # `yld2xml` reads, which is why a map built from the XML stops just short of it. Found by the
    # residual: one file left 28 bytes of small ascending u32 (2, 1, 9, 19, 20, 21, 22) with a
    # live pointer at item+0x90 and a count of 7 at +0x98 - a bone-tag-shaped list.
    0x90: ('<I', 'arr90_ptr'), 0x98: ('<H', 'arr90_count'), 0x9A: ('<H', 'arr90_capacity'),
}, ITEM, 'characterCloth')

CTRL_FIELDS = tile({
    0x10: ('<I', 'bridge_ptr'),
    0x20: ('<I', 'verlet_ptr'),
    0x50: ('<I', 'type'),
    0x78: (F32, 'unk78_f32'),
    0x80: ('<I', 'indices_ptr'), 0x88: ('<H', 'indices_count'),
    0x8A: ('<H', 'indices_capacity'),
    0x90: ('<I', 'vertices_ptr'), 0x98: ('<H', 'vertices_count'),
    0x9A: ('<H', 'vertices_capacity'),
    0xA0: (F32, 'unkA0_f32'),
    0xB0: ('<I', 'unkB0_ptr'), 0xB8: ('<H', 'unkB0_count'), 0xBA: ('<H', 'unkB0_capacity'),
    0xC0: ('<I', 'weights_ptr'), 0xC8: ('<H', 'weights_count'),
    0xCA: ('<H', 'weights_capacity'),
    0xDC: (F32, 'unkDC_f32'),
    0xE0: ('<I', 'boneids_ptr'), 0xE8: ('<H', 'boneids_count'),
    0xEA: ('<H', 'boneids_capacity'),
}, CTRL, 'clothController')
# ⛔ +0x58 IS AN INLINE NAME STRING inside the controller record, so it is NOT in the sparse map
# above - `tile` would claim it as u32 words, which round-trips but says the wrong thing. It is
# read by `_controller` as a cstr AFTER the tiled claim, which is why the tiled map deliberately
# stops naming there. See the NAME note in `_controller`.
CTRL_NAME_OFF = 0x58

BRIDGE_FIELDS = tile({
    0x10: ('<I', 'vertex_count'), 0x14: ('<I', 'unk14'), 0x18: ('<I', 'unk18'),
    0x20: ('<I', 'unk20_ptr'), 0x28: ('<H', 'unk20_count'), 0x2A: ('<H', 'unk20_capacity'),
    0x60: ('<I', 'unk60_ptr'), 0x68: ('<H', 'unk60_count'), 0x6A: ('<H', 'unk60_capacity'),
    0xA0: ('<I', 'unkA0_ptr'), 0xA8: ('<H', 'unkA0_count'), 0xAA: ('<H', 'unkA0_capacity'),
    0xE0: ('<I', 'unkE0_ptr'), 0xE8: ('<H', 'unkE0_count'), 0xEA: ('<H', 'unkE0_capacity'),
    0x128: ('<I', 'bitset_ptr'), 0x130: ('<H', 'bitset_words'),
    0x132: ('<H', 'bitset_bits'),
}, BRIDGE, 'BridgeSimGfx')

VERLET_FIELDS = tile({
    0x70: ('<I', 'vertices2_ptr'), 0x78: ('<H', 'vertices2_count'),
    0x7A: ('<H', 'vertices2_capacity'),
    0x80: ('<I', 'vertices_ptr'), 0x88: ('<H', 'vertices_count'),
    0x8A: ('<H', 'vertices_capacity'),
    0x100: ('<I', 'constraints2_ptr'), 0x108: ('<H', 'constraints2_count'),
    0x10A: ('<H', 'constraints2_capacity'),
    0x110: ('<I', 'constraints_ptr'), 0x118: ('<H', 'constraints_count'),
    0x11A: ('<H', 'constraints_capacity'),
    0x130: ('<I', 'arr130_ptr'), 0x138: ('<H', 'arr130_count'),
    0x13A: ('<H', 'arr130_capacity'),
    0x140: ('<I', 'bitset_ptr'), 0x148: ('<H', 'bitset_words'),
    0x14A: ('<H', 'bitset_bits'),
}, VERLET, 'VerletCloth1')

# constraint record, 16 B, tiled (yld2xml: u16 | u16 | f32 | f32 | f32)
CONSTRAINT = ((0x00, '<H', 'c_unk0'), (0x02, '<H', 'c_unk2'), (0x04, F32, 'c_unk4_f32'),
              (0x08, F32, 'c_unk8_f32'), (0x0C, F32, 'c_unkC_f32'))
# BoneWeightsIndices record, 32 B, tiled
BONEWEIGHT = ((0x00, F32x4, 'bw_weights_f32'), (0x10, '<4I', 'bw_indices'))


class Yld(Model):
    def __init__(self, res, flags=(0, 0)):
        Model.__init__(self, res, flags, version=8, what='yld')
        self.items = self.read_shell()
        self.ncloth = self.nbound = 0
        for off in self.items:
            self._cloth(off)

    # ------------------------------------------------------------------ helpers
    def _arr(self, f, name, stride, code=None, fn=None, optional=True):
        """One atArray: `<name>_ptr` / `<name>_count` / `<name>_capacity`.

        THE COUNT DRIVES THE WALK, so a wrong count writes the wrong number of records and the
        round-trip rejects it. CAPACITY sizes nothing - it is claimed as its own field."""
        cnt, ptr = f[name + '_count'], f[name + '_ptr']
        cap = f.get(name + '_capacity', cnt)
        if not cnt:
            if ptr and not optional:
                raise ModelError('yld: %s count 0 with a live pointer' % name)
            return []
        if cap != cnt:
            raise ModelError('yld: %s capacity %d != count %d (unwitnessed)' % (name, cap, cnt))
        base = self.deref(ptr, cnt * stride)
        if base is None:
            raise ModelError('yld: %s (%d x %d B) does not fit the segment' % (name, cnt, stride))
        if fn is not None:
            for i in range(cnt):
                fn(base + i * stride)
            return []
        return self.rd_array(base, code, cnt, name + '_elem', stride=stride)

    # ------------------------------------------------------------------ characterCloth
    def _cloth(self, off):
        if not self.once(off):
            raise ModelError('yld: two dictionary entries point at the same cloth 0x%x' % off)
        self.ncloth += 1
        f = self.rd_fields(off, ITEM_FIELDS, ITEM, 'characterCloth')
        self._arr(f, 'bones', 4, '<I')
        self._arr(f, 'arr90', 4, '<I')
        # ⭐ +0x10 - AN ARRAY `yld2xml` HAS NO ENTRY FOR. Live on 9 of 59 items; its element
        # stride is pinned by the allocation at 16 on all 9 (room/count = 16 exactly:
        # 29952/1872, 32000/2000, 5632/352, 3616/226, 5664/354, 4160/260, 27200/1700,
        # 37440/2340, 5088/318 - no slack on any of them).
        self._arr(f, 'arr10', VEC4_STRIDE, F32x4)
        ctrl = self.deref(f['controller_ptr'], CTRL)
        if ctrl is None:
            raise ModelError('yld: controller pointer does not resolve')
        self._controller(ctrl)
        bnd = self.deref(f['bounds_ptr'], 1)
        if bnd is None:
            raise ModelError('yld: bounds pointer does not resolve')
        self._bound(bnd)

    def _controller(self, off):
        if not self.once(off):
            return
        f = self.rd_fields(off, CTRL_FIELDS, CTRL, 'clothController')
        # ⛔ THE NAME IS INLINE INSIDE THE RECORD, and the tiled map already claimed those bytes
        # as words - so re-reading it here would be a DOUBLE CLAIM and `accounting()` refuses on
        # overlap. The string is therefore read for the model's own use and NOT re-claimed; the
        # bytes are already accounted, as words rather than as a name. Saying so is the point:
        # this is one place where `value_words` is hiding something we do know.
        s = self.res.sys
        end = s.find(b'\x00', off + CTRL_NAME_OFF, off + CTRL)
        self.ctrl_name = (s[off + CTRL_NAME_OFF:end].decode('latin-1') if end > 0 else '')
        self._arr(f, 'indices', 2, '<H')
        self._arr(f, 'vertices', VEC4_STRIDE, F32x4)
        self._arr(f, 'unkB0', 4, '<I')
        self._arr(f, 'boneids', 4, '<I')
        self._arr(f, 'weights', BONEWEIGHT_STRIDE, fn=lambda o: self.rd_fields(o, BONEWEIGHT, 32,
                                                                'BoneWeightsIndices'))
        bg = self.deref(f['bridge_ptr'], BRIDGE)
        if bg is None:
            raise ModelError('yld: BridgeSimGfx pointer does not resolve')
        self._bridge(bg)
        vc = self.deref(f['verlet_ptr'], VERLET)
        if vc is None:
            raise ModelError('yld: VerletCloth1 pointer does not resolve')
        self._verlet(vc)

    def _bridge(self, off):
        if not self.once(off):
            return
        f = self.rd_fields(off, BRIDGE_FIELDS, BRIDGE, 'BridgeSimGfx')
        self._arr(f, 'unk20', 4, F32)
        self._arr(f, 'unk60', 4, F32)
        self._arr(f, 'unkA0', 4, F32)
        self._arr(f, 'unkE0', 2, '<H')
        self._bitset(f)

    def _bitset(self, f):
        """+0x128 IS AN atBitSet, NOT AN atArray - and the second u16 is a BIT COUNT, not a
        capacity.

        ⛔⛔ THE UNIFORM `capacity == count` RULE THIS WRITER APPLIES EVERYWHERE ELSE REFUSED ALL
        59 FILES HERE, and the refusal is what found the structure: the pairs it printed were
        (8, 234), (7, 207), (5, 147), (1, 18), (4, 99), (2, 40), (3, 71) ... a ratio near 25-30,
        which is no capacity policy anyone allocates by.
        ⭐ THE LAW, AND IT IS A TEST A WRONG READING FAILS: `words == ceil(bits / 32)`. Checked on
        every live bitset in the lane - **59 of 59, zero exceptions** - across 8 distinct word
        counts and 40 distinct bit counts, including the exact-multiple case (192 bits -> 6 words)
        and both neighbours of it (191 -> 6, 194 -> 7). Reading the field as a capacity, or the
        words as bytes, or the bits as a second count, all break the relation on the first file.
        `yld2xml` reads the word count as its element count and emits `Unknown128` from it, which
        is consistent with this - it simply never had to explain the other u16.
        ⚠ WHAT IS NOT CLAIMED: what the bits SELECT. The relation pins the SIZE, nothing else."""
        words, bits, ptr = f['bitset_words'], f['bitset_bits'], f['bitset_ptr']
        if not words:
            if ptr:
                raise ModelError('yld: bitset word count 0 with a live pointer')
            return
        if words != (bits + 31) // 32:
            raise ModelError('yld: bitset %d words does not match %d bits (ceil rule)'
                             % (words, bits))
        base = self.deref(ptr, words * 4)
        if base is None:
            raise ModelError('yld: bitset (%d x 4 B) does not fit the segment' % words)
        self.rd_array(base, '<I', words, 'bitset_word')

    def _verlet(self, off):
        if not self.once(off):
            return
        f = self.rd_fields(off, VERLET_FIELDS, VERLET, 'VerletCloth1')
        self._arr(f, 'vertices', VEC4_STRIDE, F32x4)
        self._arr(f, 'vertices2', VEC4_STRIDE, F32x4)
        con = lambda o: self.rd_fields(o, CONSTRAINT, 16, 'cloth constraint')  # noqa: E731
        self._arr(f, 'constraints', CONSTRAINT_STRIDE, fn=con)
        self._arr(f, 'constraints2', CONSTRAINT_STRIDE, fn=con)
        # ⭐ TWO MORE ARRAYS `yld2xml` HAS NO ENTRY FOR, live on 59 of 59.
        self._arr(f, 'arr130', VEC4_STRIDE, F32x4)
        # ⭐ +0x140 IS THE SAME atBitSet SHAPE as BridgeSimGfx +0x128 - same ceil rule, and on
        # every file the two report the SAME bit count, which is a cross-check neither could
        # have passed by accident. 59/59.
        self._bitset(f)

    # ------------------------------------------------------------------ phBound graph
    def _bound(self, off, depth=0):
        """The embedded phBound graph. Spans and slots are `ybn_write`'s, re-checked here rather
        than assumed - `.yld` is RSC7 v8 and `.ybn` is v43, and `yld2xml` already documents one
        real divergence in this lane (the composite flags array at +0x88, not +0x90)."""
        if depth > 32 or not self.once(off):
            return
        self.nbound += 1
        btype = self.res.sys[off + 0x10]
        span = BOUND_SPAN.get(btype)
        if span is None:
            raise ModelError('yld: unwitnessed phBound type %d at 0x%x' % (btype, off))
        self.rd_fields(off, BOUND_FIELDS[btype], span, 'phBound type %d' % btype)
        if btype != 10:
            return
        n = struct.unpack_from('<H', self.res.sys, off + 0xA0)[0]
        if not n:
            return
        carr = self.deref(struct.unpack_from('<I', self.res.sys, off + 0x70)[0], n * 8)
        if carr is None:
            raise ModelError('yld: composite child array does not fit')
        kids = [v[0] for v in self.rd_array(carr, '<Q', n, 'composite_child_ptr')]
        # ⭐ +0x80 IS n * 64, NOT n * 32 - TWO 32-byte AABBs per child (a current and a last
        # set), and the allocation is what says so: on file 0 the +0x80 target spans 0xF9B0 ..
        # 0xFCF0 = 832 bytes for 13 children = 64 each, with the next live structure (the
        # VerletCloth1) starting exactly at 0xFCF0. An n*32 claim left 416 bytes of pure
        # residual per file, i.e. HALF the array, in all 59.
        # ⛔ THIS CORRECTS A STRIDE IMPORTED FROM `ybn_write` ("+0x88 ... a PER-CHILD AABB ARRAY
        # (n * 32)"), which is measured on `.ybn` v43 and does NOT transfer to `.yld` v8 - the
        # same divergence `yld2xml` already documents for the FLAGS slot (+0x88 here, +0x90
        # there). Two lanes, two container versions: re-measure, never inherit.
        for slot, stride, tag in ((0x78, 64, 'composite_transform'),
                                  (0x80, 64, 'composite_aabb'),
                                  (0x88, 8, 'composite_flags')):
            p = struct.unpack_from('<I', self.res.sys, off + slot)[0]
            if not p:
                continue
            b = self.deref(p, n * stride)
            if b is None:
                raise ModelError('yld: composite array at +0x%x does not fit' % slot)
            self.rd_array(b, '<%dI' % (stride // 4), n, tag)
        for k in kids:
            if not k:
                continue
            c = self.deref(k & 0xFFFFFFFF, 1)
            if c is not None:
                self._bound(c, depth + 1)


# ⭐ PER-TYPE SPANS. `ybn_write.BOUND_SPAN_BY_TYPE` measured these over 71,912 bounds; the
# composite 0xB0 is re-confirmed on 59/59 roots here by the allocation. Types this lane never
# shows are absent rather than guessed - an unwitnessed type REFUSES.
BOUND_SPAN = {0: 0x70, 1: 0x80, 3: 0x70, 4: 0x130, 8: 0x150, 10: 0xB0, 13: 0x80}
BOUND_FIELDS = {t: tile({0x10: ('<B', 'bound_type')}, sp, 'phBound %d' % t)
                for t, sp in BOUND_SPAN.items()}


def read_yld(src):
    return pgdict_write.read(src, Yld)
