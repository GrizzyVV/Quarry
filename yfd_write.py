"""yfd_write - ROUND-TRIP WRITER for .yfd frame-filter dictionaries (RSC7 v4).

    inflated system segment -> value model -> written back -> MUST reproduce the original bytes

WHY: `.yfd` had a READER (`yfd2xml.py`) and no writer, which under the 2026-08-13 ruling makes it
**UNMEASURED, not passing** - `docs/LANE_CENSUS_20260814.md` row 14. It is only 4 files, so the
value here is not the count: it is the smallest complete proof that the shared pgDictionary shell
in `pgdict_write.py` is reusable, and it is the lane where a defect in that shell would be
easiest to see.

MODEL, NOT MEMCPY - and stronger than `ynd_write`'s per-record byte slices. EVERY byte this
writer reproduces was decoded through `Model.rd()` with a struct format and re-packed from the
decoded value; there is not one byte-range copy in this file (`Model.carry()` is called ZERO
times). The field maps below TILE their records, checked at import, so a byte inside a record
that no named field covers stays zero and counts against coverage. **The gaps are the finding.**

⚠ SCOPE: the INFLATED SYSTEM SEGMENT, not the compressed RSC7 container - reproducing the
container also means reproducing an exact deflate stream, a separate problem. `.yfd` carries no
graphics segment (4/4) and a non-empty one REFUSES rather than being ignored.

LAYOUT (derived 2026-08-15 over ALL 4 `.yfd` in the game / 173 filter items;
`scratchpad/probe_items.py`. The offsets are `yfd2xml`'s, re-measured here as a WRITER):
    dictionary shell 0x00..0x40 ......... pgdict_write.SHELL_FIELDS
    crFrameFilterMultiWeight, span 0x40:
      +0x00 u64 vtable       +0x08 u32 (=1)      +0x0C u32 signature   +0x10 u32 (=4)
      +0x18 Entries atArray : ptr @+0x18, count u16 @+0x20, capacity u16 @+0x22
      +0x28 Weights atArray : ptr @+0x28, count u16 @+0x30, capacity u16 @+0x32
    entry record 8 B : u8 reserved | u8 Track | u16 BoneId | u32 WeightIndex
    weight record 4 B : f32
⭐ THE SPAN IS PINNED BY THE ALLOCATION, not chosen: the ROOM from one item to the next live item
is exactly 0x40 in 131 of 173 records and never less than 0x40 - so 0x40 is the largest span that
can never claim a neighbour's bytes, and every wider guess over-runs on 131 records.
=============================================================================================
COVERAGE AT POPULATION 2026-08-15 - THE LANE IS CLOSED. Every `.yfd` in the game:
    EXACT round-trip (every byte of the inflated system segment) : **4 / 4 = 100.0000%**
    mean coverage 100.0000%   min 100.000%   residual 0 bytes   refusals 0
  BYTE ACCOUNT (the split that decides whether the 100% is worth anything):
    VALUE  100,048 B = 76.3306% (100% NAMED)   re-encoded from a decoded value, never memcpy'd
    DERIVED 16 B = 0.0122%   the page-count word, COMPUTED from the RSC7 flags
    CARRIED 0 B = 0.0000% <- `Model.carry()` is called ZERO times in this lane
    ZERO-FILL 31,008 B = 23.6572%   never claimed; the ORIGINAL byte is zero (padding + block-map records)
    ZERO-RESIDUAL 0 bytes   never claimed and NON-ZERO in the original - the finding, and it is empty
  MUST-FAIL CONTROL (`python tools/pgdict_control.py --lane yfd --limit 500 --cap 0`):
    VALUE  ....... 44,502 / 44,502 moved the image (100.0000%)
    DROP   ....... 27,468 / 44,502 (61.72%); escapes are all-zero claims
    OFFSET ....... 27,464 / 44,502 (61.71%)
    STRIDE ....... entry stride 8 and weight stride 4 each REFUSED all 4 files, 0 ESCAPED
> REPRODUCE: `python tools/roundtrip_coverage.py --lane yfd --limit 500 --cap 0`
=============================================================================================
ASCII output only.
"""
import os
import sys as _sys

_sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pgdict_write  # noqa: E402
from pgdict_write import Model, ModelError  # noqa: E402

ITEM = 0x40
# ⭐ THE ARRAY STRIDES ARE NAMED CONSTANTS, NOT CALL-SITE LITERALS, so `tools/pgdict_control.py`
# can patch them and demand the lane break. A stride nothing can perturb is a stride nobody
# measured. (`ITEM` itself is consumed by `Model.rd_fields`'s tiling check at first use, so it is
# pinned by `check_tiling` rather than by the stride control - see that control's output.)
ENTRY_STRIDE = 8
WEIGHT_STRIDE = 4

# TILES 0x00..0x40 with no hole and no overlap - `Model.rd_fields` checks it on first use.
# Named where `yfd2xml` names it; `padNN` where the slot is zero in 173/173 records and the
# format gives us no other handle. ⛔ A `pad` name is a statement about the MEASUREMENT, not a
# claim that the slot is meaningless - it is still decoded and re-encoded like any other field.
FILTER_FIELDS = (
    (0x00, '<Q', 'vtable'),
    (0x08, '<I', 'unk08'),
    (0x0C, '<I', 'signature'),
    (0x10, '<I', 'unk10'),
    (0x14, '<I', 'pad14'),
    (0x18, '<I', 'entries_ptr'),
    (0x1C, '<I', 'entries_ptr_hi'),
    (0x20, '<H', 'entries_count'),
    (0x22, '<H', 'entries_capacity'),
    (0x24, '<I', 'pad24'),
    (0x28, '<I', 'weights_ptr'),
    (0x2C, '<I', 'weights_ptr_hi'),
    (0x30, '<H', 'weights_count'),
    (0x32, '<H', 'weights_capacity'),
    (0x34, '<I', 'pad34'),
    (0x38, '<I', 'pad38'),
    (0x3C, '<I', 'pad3C'),
)

# entry record, 8 B, tiled
ENTRY_FIELDS = (
    (0x00, '<B', 'reserved'),
    (0x01, '<B', 'track'),
    (0x02, '<H', 'bone_id'),
    (0x04, '<I', 'weight_index'),
)


class Yfd(Model):
    def __init__(self, res, flags=(0, 0)):
        Model.__init__(self, res, flags, version=4, what='yfd')
        self.items = self.read_shell()
        self.nfilters = 0
        self.nentries = 0
        self.nweights = 0
        for off in self.items:
            self._filter(off)

    def _filter(self, off):
        if not self.once(off):
            raise ModelError('yfd: two dictionary entries point at the same filter 0x%x' % off)
        self.nfilters += 1
        f = self.rd_fields(off, FILTER_FIELDS, ITEM, 'crFrameFilter')
        # ⭐ THE COUNTS DRIVE THE WALK, which is what pins them: a wrong count writes the wrong
        # number of records and the round-trip rejects it. Capacity is claimed as its own field
        # and is NOT used to size anything - it equals count in 173/173, and sizing a read off a
        # field we are also testing is how a garbage count becomes garbage coverage.
        ec, wc = f['entries_count'], f['weights_count']
        if f['entries_capacity'] != ec or f['weights_capacity'] != wc:
            # UNWITNESSED SHAPE, counted rather than absorbed: cap != count means the tail
            # records past `count` belong to nobody in this model and would show as residual.
            raise ModelError('yfd: array capacity %d/%d != count %d/%d (unwitnessed)'
                             % (f['entries_capacity'], f['weights_capacity'], ec, wc))
        if ec:
            base = self.deref(f['entries_ptr'], ec * ENTRY_STRIDE)
            if base is None:
                raise ModelError('yfd: entry array (%d x %d B) does not fit the segment'
                                 % (ec, ENTRY_STRIDE))
            for i in range(ec):
                self.rd_fields(base + i * ENTRY_STRIDE, ENTRY_FIELDS, ENTRY_STRIDE,
                               'crFrameFilter entry')
            self.nentries += ec
        if wc:
            base = self.deref(f['weights_ptr'], wc * WEIGHT_STRIDE)
            if base is None:
                raise ModelError('yfd: weight array (%d x %d B) does not fit the segment'
                                 % (wc, WEIGHT_STRIDE))
            # per-RECORD, never one slab
            self.rd_array(base, '<f', wc, 'weight', stride=WEIGHT_STRIDE)
            self.nweights += wc


def read_yfd(src):
    return pgdict_write.read(src, Yfd)
