"""pso_write - ROUND-TRIP WRITER for the RAGE PSO (PSIN) container family.

    original file bytes -> value model -> written back -> MUST reproduce the original bytes

ONE WRITER SERVES FOUR LANES, because one CONTAINER serves them: `.ymf` (1,795) + `.cut` (816) +
the PSIN half of `.ymt` (2,190) + `.pso` (2). They are the same file format with different root
structs, and the root struct is not hardcoded anywhere here - the reader is driven by the FILE'S
OWN EMBEDDED SCHEMA (the PSCH section), exactly as `pso2xml.py` is.

WHY (maintainer ruling 2026-08-13): round-trip byte identity is the primary measure, and a lane
with a READER and no WRITER is **UNMEASURED, not passing**. All four lanes above sat in
`docs/LANE_CENSUS_20260814.md` section 3 with the word UNMEASURED against them - 4,803 files with
no number attached. A writer turns every one of them into an oracle at no cost, because **you
cannot rebuild a section you never read**.

* SCOPE IS THE WHOLE FILE, not a segment. Unlike every RSC7 lane in this tree (`ynd`, `yvr`,
  `ybn`, ...) a PSO file is NOT a compressed resource container: it is plain, uncompressed,
  section-concatenated bytes. So there is no deflate stream to reproduce and no "inflated system
  segment" caveat - the measure here is the FILE.

* ALL INTEGERS ARE BIG-ENDIAN. Every other lane in this project is little-endian. The one
  little-endian thing in a PSO file is nothing at all; even the metapointers are BE.

MODEL, NOT MEMCPY - and stronger here than in `ynd_write` (opaque per-record slices) or
`yvr_write` (typed fields against one fixed stride). Here the STRIDE AND THE FIELD MAP BOTH COME
OUT OF THE FILE, so a round-trip proves we walked the file's own declared type graph:

  1. The image is ZERO-FILLED. Anything the model never reaches stays zero and is LOUD.
  2. Section OFFSETS and SIZES are COMPUTED, never carried: offset[0] = 0, offset[i] =
     offset[i-1] + size[i-1], and size = 8 + len(the payload this model rebuilt). A section whose
     content we rebuild one byte short moves every later section and wrecks the file.
  3. BLOCK OFFSETS are COMPUTED, never carried. Measured over 3,000 files: the first block sits at
     +16 and each next at align16(prev end) - 3,000/3,000, no exceptions - and the PSIN section
     size equals the last block's end EXACTLY (3,000/3,000, no trailing pad). So the PMAP's
     `fileOffset` column is REBUILT from the layout law and a wrong block size shifts every
     following block. That is what pins the size column: it is not a claim the image can copy.
  4. INTER-BLOCK PADDING IS 0x70, derived not carried (94,087/94,087 pad bytes measured, one
     value). RAGE pads this container with 'p'; the PMAP's own reserved u16 is 0x7070 and the PSIN
     payload opens with eight 0x70 bytes.
  5. BLOCK CONTENT is rebuilt by walking the file's declared TYPE GRAPH from the root struct -
     every member decoded to a typed value and re-encoded from that value. A byte inside a struct
     that no schema member covers stays zero and counts against coverage. **The gaps are the
     finding.**

WHAT IS CARRIED, AND IT IS DECLARED (see `regions()` - quote it next to any coverage figure):
  - STRE, the ENCRYPTED string pool. Not decrypted here. Its bytes are carried verbatim; a
    carried region is NOT a measured one, and `regions()` reports its exact size per file.
  - PSIG, the signature blob (payload 8..104 B; its leading words repeat across thousands of
    files, so it is a per-schema constant rather than per-file entropy). Carried, declared.
  - CHKS's middle word, the 4-byte checksum. The other two words of CHKS are COMPUTED: the first
    is the total file size and the third is the constant 0x79707070. The checksum resisted a
    56-hypothesis battery (8 algorithms x 7 byte-ranges; see `docs/` writeup) - so 4 bytes per
    file are carried and counted, and the space searched is named rather than called a ceiling.

⛔⛔ THE FIRST POPULATION FIGURE THIS FILE CARRIED WAS DRAWN FROM 78.5% OF ONE OF ITS LANES, AND
NOTHING PRINTED AN ERROR. It read `ymt_psin 1,719 files, 1,709 byte-exact (99.4183%)`. The lane
holds 2,190. The missing 471 all live in `x64\audio\occlusion.rpf`, a top-level archive the
`_pso_archives()` list could not name because it globbed `GAME\x64*.rpf` - which matches the 23
archives sitting BESIDE the `x64` folder and nothing inside it. Fixed 2026-08-15 (see
`roundtrip_coverage._loose_archives`); the numbers below are the RE-MEASURE, and the corrected
walk returns .ymt 4,713 / .ymf 1,795 / .cut 816 / .pso 2 - equal to `VIEW_MANIFEST.jsonl` for all
four extensions, so the draw provably reaches the whole family now.

MEASURED AT POPULATION 2026-08-15 (one walk of all 179 top-level archives, AES key bound, zero
archive errors). Reproduce with either of:
    python tools/roundtrip_coverage.py --lane ymf --limit 9000 --cap 0     (and cut / pso /
                                                                            ymt_psin)
    python quarry/pso_write.py --all
  lane      files  BYTE-EXACT           mean cov     min cov    VALUE  UNTYP  DERIV  CARR   ZERO
  ymf       1,792  1,792 (100.0000%)  100.000000%  100.0000%   44.32%  0.00%  3.15%  9.17% 43.35%
  cut         816    815 ( 99.8775%)   99.989602%   91.5151%   58.20%  1.98%  0.83%  6.20% 32.79%
  pso           2      2 (100.0000%)  100.000000%  100.0000%   77.81%  9.12%  0.05%  0.01% 13.01%
  ymt_psin  2,190  2,180 ( 99.5434%)   99.998394%   97.5781%   78.78%  0.71%  1.43%  5.05% 14.03%
  TOTAL     4,800  4,789 ( 99.7708%)
⭐ AND QUOTE THE CARRIED BREAKDOWN WITH THE MEAN, because 100% over a carried region is not a
measurement (`regions()` produces it; the driver prints it per lane):
  lane      STRE (the ENCRYPTED string pool)       PSIG            CHKS checksum word
  ymf         510,816 B in   549 of 1,792 (8.64%)   25,288 B/1,792    6,064 B/1,516
  cut       2,595,520 B in   815 of   816 (5.98%)   82,200 B/  816    1,396 B/  349
  pso               0 B in     0 of     2               48 B/    2            0 B/    0
  ymt_psin    946,128 B in   107 of 2,190 (4.78%)   43,272 B/2,189    8,704 B/2,176
  FAMILY    4,052,464 B in 1,471 of 4,800 = 5.835% of the family's 69,452,000 bytes
⭐ AND THE CARRIED CLASS RECONCILES TO THE BYTE, so nothing hides inside it:
  ymf       542,168 = 510,816 + 25,288 + 6,064  ->      0 unaccounted
  pso            48 =       0 +     48 +     0  ->      0 unaccounted
  cut     2,690,081 = 2,595,520 + 82,200 + 1,396 -> 10,965 unaccounted
  ymt_psin  999,616 = 946,128 + 43,272 + 8,704  ->  1,512 unaccounted
The unaccounted remainder is `psch_def_carried_bytes` - PSCH def bodies that `classify()` could
resolve to NEITHER struct nor enum, by reference context or by the extent test, and therefore
carried rather than guessed (12,477 B family-wide, 0.018%). The family's ONLY other carry path is
an unmodelled section, and there is exactly ONE in 4,800 files: `x64a.rpf/rockfordwest.ymt`
carries an `STRS` section whose payload is **ZERO bytes long**, so it contributes nothing to the
carried class - the 8-byte header is COMPUTED like every other section header.
  (Section presence measured over a 724-file PSIN .ymt draw across 7 archives:
   PSIN/PMAP/PSCH 724 · PSIG 723 · CHKS 714 · STRE 97 · STRF 4 · STRS 1.)
⭐⭐ NO BYTE OF THE ROUND-TRIP DEPENDS ON RE-ENCRYPTING STRE. The section is reproduced by being
carried, so byte identity holds without touching the cipher - but those 4,052,464 bytes are
REPRODUCED, NOT MEASURED, and the count above is the honest size of that hole. Decrypting STRE
would convert ~5.8% of the family from CARRIED to VALUE; it would not change a single coverage
figure, which is exactly why the split has to be printed next to the figure.

⭐ MUST-FAIL CONTROL, 602 files, 5,127 model mutations: 4,525 caught. Every miss is the `schema`
class, which is DESIGNED not to fire (it reclassifies a PSCH def as carried, and a carried region
reproduces itself - that 0/602 is the cleanest demonstration in this tree of what "carried" costs).
Across the five classes that can fire - value, drop, untyped, layout, root - the catch rate is
4,525 / 4,525. Writes aimed at regions the original leaves zero are EXCLUDED from the battery and
counted separately (a mutation there is undetectable by construction); that exclusion is 552,502
writes and it is reported, not hidden.
⚠ ZERO-FILL IS THE OTHER HALF OF THAT SENTENCE AND IT IS LARGE: 43.35% of `.ymf` and 32.79% of
`.cut` by byte is region the model never writes and that happens to be zero in the original. Those
bytes are reproduced by construction, and the battery says so by having to exclude them.

⚠ THE RESIDUAL IS ONE CAUSE, NOT ELEVEN - and 2026-08-15 that stopped being an assertion. Every
one of the 11 non-exact files was split BY CAUSE against the writer's own `writes` list and
`reached` set, per byte, and the answer is unanimous:

  file                        size      differing   cause                          printable
  ac_ig_3_p3_b.cut            68,816        5,839   100% field-map hole              85.9%
  physicstasks.ymt           190,208          365   100% field-map hole              41.4%
  physicstasks.ymt           188,160          314   100% field-map hole              54.1%
  clip_sets.ymt              970,520          138   100% field-map hole              72.5%
  wantedtuning.ymt             5,120          124   100% field-map hole              98.4%
  clip_sets.ymt              895,000          108   100% field-map hole                 -
  pedpersonality.ymt          45,176           49   100% field-map hole              20.4%
  pedpersonality.ymt          45,064           48   100% field-map hole                 -
  cameras.ymt                828,312           34   100% field-map hole              14.7%
  cameras.ymt                425,080           34   100% field-map hole                 -
  rockfordwest.ymt               828            4   100% field-map hole               0.0%
  ⇒ 7,057 differing bytes across 11 files, and **0 of them lie in a region the writer wrote**
    (no value is WRONG, only absent) and **0 lie outside a reached instance** (nothing in these
    files is unreachable through the declared type graph).

RE-VERIFIED for the worst file - `x64c.rpf/anim/cutscene/cuts_random_event.rpf/ac_ig_3_p3_b.cut`
(68,816 B, 91.5151%, the `cut` lane's only non-exact file of 816):
    5,839 / 5,839 differing bytes lie INSIDE a struct instance the walk REACHED, at an offset no
          schema member covers
        0 lie outside a reached instance (nothing is unreachable through the type graph)
        0 lie inside a region the writer wrote (no value is WRONG, only absent)
  the holes cluster at in-instance offsets 0,1,2,3,4 then 6,7,14,15,17,18,19; the carriers are
  instance sizes 240 (3,925 B), 5,296 (874), 96 (744), 416 (147), 368 (68), 208 (36), 32/104 (20).
Reproduce: the by-cause split is a ~40-line probe over the writer's own `writes` list and
`reached` set; both are public on the model.

⭐⭐ AND THE RESIDUAL HAS NO SEMANTICS TO RECOVER - it is BUILD-TIME UNINITIALISED HEAP. Assembled
in file order, the 5,839 bytes are **684 discontiguous runs** (modal length 5 B; 82 runs are a
single byte) that are **85.9% printable ASCII**, and the text is RAGE's OWN TOOLING MEMORY, not
cutscene data:
    'rsion="1?><!--This fa>\\r\\n...rSchema>' ... '<enumval name="MATRIX44"' ...
    '::rage::parMember' ... 'CTAB' ... 'gCloudLayerAnimScale' 'gViewInverse' 'gWorld'
    'globalFogColor' ... '<float name="m_breakPiecesSizeMax"' ... 'DecalTextureScale'
i.e. fragments of a `<ParserSchema>` XML document, a D3D shader constant table and shader
parameter names - three things that have nothing to do with a `.cut`, interleaved at 1-17 byte
granularity.
⭐ AND THE SAME SIGNATURE APPEARS IN THE OTHER TEN FILES, WHICH IS THREE DIFFERENT FILE TYPES
CORROBORATING ONE READING:
    wantedtuning.ymt   98.4% printable  'base=iour" cstructdet' 'rockstargerSchem' '<structdef'
    clip_sets.ymt      72.5% printable  'specular' 'ExtAmbie' 'gColorN' 'alFogCol' 'ewInvers'
    physicstasks.ymt   41.4% printable  'he ragdot end ure applyew exple directe exploity and it'
The `clip_sets` fragments are the SAME shader-parameter vocabulary as the `.cut` one, in a file
authored by a different tool for a different subsystem.
🧠 THE READING IS AN INFERENCE, and it is labelled one: what is PROVEN is (a) every residual byte
sits in a declared-field-map hole inside a REACHED instance, (b) the printable fraction, (c) the
content is unrelated to each file's subject, (d) the runs are short and discontiguous, (e) the
same vocabulary recurs across unrelated file types. What that implies - that the exporter
serialised struct padding without clearing it - is the only reading consistent with all five, but
it is not witnessed.
⇒ SO THE WRITER LEAVES THEM ZERO, DELIBERATELY. Carrying them would buy 11 files of "100%" by
copying bytes that are not data, and would hide the one honest statement available here: **11 of
4,800 files in this family carry 5,839 + ~1,100 bytes of content nothing in the format declares,
and 4,789 files have zeroes in the same slots.** If byte-identical re-export of those 11 files
ever becomes a product requirement, the fix is a declared carry with its own accounting row - not
a silent memcpy, and not a claim that the bytes were understood.

⚠ THE RESIDUAL IS ONE CAUSE, NOT ELEVEN (original note). All 11 files fail on bytes that
lie in HOLES OF THE FILE'S OWN DECLARED FIELD MAP - the 8-byte slot at the head of every struct
instance, inter-member padding, and the tail of a map entry table. Verified by rebuilding each
carrier's member coverage from its PSCH entries: `pedpersonality` F977FFB7 leaves 21 of 184 bytes
undeclared and the differing byte is at +95, one of them; `cameras` 030A2ECB leaves 35 of 72;
`ac_ig_3_p3_b.cut` FA42E9D7 carries ASCII XML text in the +0..+7 head slot of 141 instances. These
bytes are NOT reachable through the declared type graph at all, so the writer leaves them ZERO and
LOUD rather than carrying them - carrying would buy 11 files of "100%" and lose the finding.

ASCII output only.
"""
import os
import struct
import sys as _sys

_sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pso2xml as _pso  # noqa: E402

PSIN_PAD = 0x70          # RAGE pads this container with 'p'; derived, never carried
ELEM = _pso.ELEM         # 0x100 - the synthetic element-descriptor name, occupies no storage

# Storage width of every scalar member type this container uses, keyed by the schema's own type
# code. These come from `pso2xml.py`'s decoded type table (its Emitter reads at exactly these
# widths); nothing new is asserted here.
SCALAR_FMT = {
    0x00: ('>B', 1),     # bool  (stored as one byte)
    0x01: ('>B', 1),     # 1-byte member; 3 schema carriers, slot 1 (census 2026-08-15)
    0x02: ('>B', 1),     # u8
    0x03: ('>h', 2),     # i16
    0x04: ('>H', 2),     # u16
    0x05: ('>i', 4),     # i32
    0x06: ('>I', 4),     # i32 / packed colour - re-encoded as the stored word
    0x07: ('>f', 4),     # f32
    0x1e: ('>H', 2),     # 2-byte member; 30 carriers, ALL slot 2, three at consecutive
                         # offsets 20/22/24 of one 56-byte struct - the adjacency IS the width
}
VEC = {0x08: 2, 0x09: 3, 0x0a: 4, 0x14: 3, 0x15: 4}   # type -> float count
VEC_SLOT = {0x08: 8, 0x09: 16, 0x0a: 16, 0x14: 16, 0x15: 16}

# ⭐ TYPE 0x10 IS A MAP, and the file says so. DERIVED 2026-08-15 from `vfxvehicleinfo.ymt`,
# whose ROOT struct has exactly one real member (type 0x10) - so the whole file hung off a type
# nothing here modelled, and the lane's worst file read 67.8%.
#   member slot, 24 B:  {u32 mode, u32 pad, u32 entriesPtr, u32 pad, u16 count, u16 capacity,
#                        u32 pad}
#   entry, 16 B:        {KEY at +0, u32 unmapped word at +4, VALUE at +8}
#   `extra` = (KEY descriptor entry index << 16) | VALUE descriptor entry index - the same
#   sibling-descriptor addressing arrays already use, and it is what proves the reading: in
#   vfxvehicleinfo the key desc is 0x0b/0x07 (a joaat hash-string) and the value desc is
#   0x0c/0x03 (a pointer to a struct), the entry table is count*16 = 49*16 = 784 B = block 3
#   EXACTLY, and the 49 value pointers walk block 2 at a stride of 880 = that struct's own
#   declared instance size. Keys ascend monotonically across the table: it is a sorted binary map.
MAP_TYPE = 0x10
MAP_SLOT = 24
MAP_VALUE_OFF = 8       # the value sits INLINE at +8; the stride is 8 + the value's width

# Types whose meaning is unmapped but whose WIDTH is not. Re-encoding a composite as N big-endian
# words reproduces its bytes without claiming to understand it - so these are counted into
# `unmapped_composite_bytes` and reported as CARRIED in `regions()`, never as VALUE.
#   0x20 sub 0x00 - 1 carrier in the whole family, slot 8 (vfxfogvolumeinfo.ymt hash_23808D4E @88)
COMPOSITE = {0x20: 8}


def _flags_width(extra):
    """Byte width of a T_FLAGS member - READ OFF THE FILE, not guessed.

    `extra` = (BIT WIDTH << 16) | entry index of the sibling enum descriptor (the low half is
    already used that way by `pso2xml.Emitter`). Measured over the family: sub 0x00 always carries
    32 bits, sub 0x01 16, sub 0x02 8 or 5 - and the slot widths agree (4 / 2 / 1). Deriving the
    width from the declared bit count instead of the sub means a new sub cannot silently write
    four bytes over its neighbour.
    """
    bits = (extra >> 16) & 0xFFFF
    if bits == 0:
        return 4
    return max(1, (bits + 7) // 8)


def _str_elem_stride(esub):
    """Slot width of one element of a string ARRAY, by the element descriptor's own sub.

    Taken unchanged from `pso2xml.Emitter._emit_hashstring_array`, where 16-vs-8 was derived and
    measured (25/25 arrays over 331 .cut files at stride 16; 15/25 fail at stride 8).
    """
    if esub == 0x03:
        return 16
    if esub in (0x01, 0x02):
        return 8
    return 4


class PsoWriteError(Exception):
    pass


class _Schema(_pso.Pso):
    """`pso2xml.Pso` plus a record of HOW each schema def was used.

    A PSCH def is a struct OR an enum and the container never says which - it is told apart by
    reference context. To REBUILD the section we must decide for every def, including ones the
    type graph never reaches, so the classification is recorded as it happens and the leftovers
    fall back to an extent test that can REFUSE (see `classify`).
    """

    def __init__(self, blob):
        _pso.Pso.__init__(self, blob)
        self.used_struct = set()
        self.used_enum = set()

    def struct_def(self, h):
        self.used_struct.add(h)
        return _pso.Pso.struct_def(self, h)

    def enum_def(self, h):
        self.used_enum.add(h)
        return _pso.Pso.enum_def(self, h)

    def def_extents(self):
        """hash -> (body offset in the PSCH payload, byte extent).

        The extent of a def body is the distance to the next def body, or to the end of the
        section for the last one. It is what lets an unreferenced def be classified without
        guessing: a struct body is exactly 12 + 12*count bytes and an enum body exactly
        4 + 8*count, so at most one of the two can fit the extent.
        """
        offs = sorted(set(self.def_off.values()))
        end_of = {}
        _so, ss = self.sec['PSCH']
        for i, o in enumerate(offs):
            end_of[o] = offs[i + 1] if i + 1 < len(offs) else (ss - 8)
        return {h: (o, end_of[o] - o) for h, o in self.def_off.items()}

    def classify(self):
        """hash -> 'struct' | 'enum' | 'unknown'. 'unknown' is REPORTED, never guessed."""
        out = {}
        ext = self.def_extents()
        pl = self.psch
        for h, (o, extent) in ext.items():
            if h in self.used_struct and h not in self.used_enum:
                out[h] = 'struct'
                continue
            if h in self.used_enum and h not in self.used_struct:
                out[h] = 'enum'
                continue
            s_ok = e_ok = False
            if o + 12 <= len(pl):
                cnt, _size, zero = struct.unpack_from('>III', pl, o)
                s_ok = (zero == 0 and 12 + 12 * cnt == extent)
            if o + 4 <= len(pl):
                ecnt = struct.unpack_from('>I', pl, o)[0] & 0xFFFF
                e_ok = (4 + 8 * ecnt == extent)
            if s_ok and not e_ok:
                out[h] = 'struct'
            elif e_ok and not s_ok:
                out[h] = 'enum'
            elif h in self.used_struct:
                out[h] = 'struct'
            elif h in self.used_enum:
                out[h] = 'enum'
            else:
                out[h] = 'unknown'
        return out


class PsoRT:
    """The value model of one PSO file, and the writer that rebuilds it."""

    def __init__(self, blob):
        blob = bytes(blob)
        if blob[:4] != b'PSIN':
            raise PsoWriteError('not a PSO container (missing PSIN magic)')
        self.blob = blob
        self.size = len(blob)
        self.p = _Schema(blob)
        self.acct = {}
        self.notes = {}
        # --- container-level decode -------------------------------------------------------
        self.order = [n for n, _o, _s in self.p.sections]
        self.blocks = list(self.p.blocks)                 # (bid, orig_off, size)
        self.root_idx = self.p.root_idx
        po, _ps = self.p.sec['PSIN']
        self.pmap_pad = struct.unpack_from('>H', blob, self.p.sec['PMAP'][0] + 14)[0]
        self._orig_block = [blob[o:o + s] for _b, o, s in self.blocks]
        # --- the type graph ---------------------------------------------------------------
        self.writes = []          # (block index 0-based, offset, kind, payload)
        self.reached = set()
        self._walk()
        self.kind_of = self.p.classify()
        # --- the string pools --------------------------------------------------------------
        self.strf = None
        if 'STRF' in self.p.sec:
            o, s = self.p.sec['STRF']
            pay = blob[o + 8:o + s]
            self.strf = pay.split(b'\x00')[:-1] if pay else []
        self.stre = blob[self.p.sec['STRE'][0] + 8:
                         self.p.sec['STRE'][0] + self.p.sec['STRE'][1]] if 'STRE' in self.p.sec \
            else b''
        self.psig = blob[self.p.sec['PSIG'][0] + 8:
                         self.p.sec['PSIG'][0] + self.p.sec['PSIG'][1]] if 'PSIG' in self.p.sec \
            else b''
        self.chks_sum = None
        if 'CHKS' in self.p.sec:
            o, s = self.p.sec['CHKS']
            self.chks_sum = struct.unpack_from('>I', blob, o + 12)[0]
            self.chks_tail = blob[o + 16:o + s]
        # Any section this writer has no model for is carried whole and COUNTED - never silently
        # dropped and never quietly copied without appearing in the accounting.
        self.opaque = {}
        for n, o, s in self.p.sections:
            if n not in ('PSIN', 'PMAP', 'PSCH', 'PSIG', 'STRF', 'STRE', 'CHKS'):
                self.opaque[n] = blob[o + 8:o + s]
                self._note('unmodelled section %s' % n)

    # ------------------------------------------------------------------ bookkeeping
    def _bump(self, k, n=1):
        self.acct[k] = self.acct.get(k, 0) + n

    def _note(self, k):
        self.notes[k] = self.notes.get(k, 0) + 1

    # ------------------------------------------------------------------ type-graph walk
    def _blk(self, one_based):
        return self._orig_block[one_based - 1]

    # Byte-accounting tags. A write says WHAT KIND OF EVIDENCE its bytes are, so `regions()` can
    # report the split instead of estimating it.
    T_VALUE = 1        # re-encoded from a decoded, TYPED field value
    T_UNTYPED = 2      # re-encoded as a raw word at a schema-PINNED offset, semantics unmapped
    T_CARRIED = 4      # copied bytes: could not have been rejected by the round-trip

    def _w(self, bidx1, off, kind, payload, tag=1):
        self.writes.append((bidx1 - 1, off, kind, payload, tag))

    def _scalar(self, bidx1, off, et, esub):
        """Decode one scalar to a VALUE and schedule its re-encode. Returns its width."""
        fmt, wid = SCALAR_FMT[et]
        buf = self._blk(bidx1)
        if off + wid > len(buf):
            self._note('scalar past end of block')
            return wid
        raw = buf[off:off + wid]
        v = struct.unpack_from(fmt, buf, off)[0]
        if et == 0x07 and struct.pack('>f', v) != raw:
            # A float whose bit pattern does not survive decode->encode (NaN payloads). Keep byte
            # identity by re-encoding the stored WORD, and COUNT it rather than hide it.
            self._bump('float_reencoded_as_word')
            self._w(bidx1, off, 'p', ('>I', struct.unpack_from('>I', buf, off)[0]))
        else:
            self._w(bidx1, off, 'p', (fmt, v))
        return wid

    def _vec(self, bidx1, off, t):
        """A vector member, plus the 4th word of a 16-byte vec3 slot.

        ⭐ A vec3 (type 0x09 / 0x14) ALWAYS sits in a 16-byte slot - 9,407 of 9,407 carriers
        measured across the family - and the 4th word is NOT always zero: `.cut` stores
        0x7F800001 there and `junctions.pso` stores per-record values. Leaving it unclaimed cost
        `.cut` 6,069 differing bytes over 40 files, every one of them non-zero. It is re-encoded
        as the stored WORD, not as a float, because the values seen there are signalling-NaN bit
        patterns that a float decode would quietly rewrite.
        """
        n = VEC[t]
        for i in range(n):
            self._scalar(bidx1, off + 4 * i, 0x07, 0)
        slot = VEC_SLOT[t]
        buf = self._blk(bidx1)
        for i in range(n, slot // 4):
            o2 = off + 4 * i
            if o2 + 4 <= len(buf):
                self._w(bidx1, o2, 'p', ('>I', struct.unpack_from('>I', buf, o2)[0]),
                        self.T_UNTYPED)
                self._bump('vec_slot_word_bytes', 4)

    def _map(self, sdef, e, bidx, o, work):
        """A type-0x10 MAP member: a 24-byte descriptor plus a count-entry table in a block.

        THE ENTRY STRIDE IS NOT A CONSTANT. It is 8 + the VALUE type's own width, because the
        value is stored INLINE at +8 rather than behind a pointer. Derived 2026-08-15 from
        `clip_sets.ymt`, which carries five maps whose value descriptors differ, and whose entry
        blocks size themselves EXACTLY to that rule:
            value 0x0c/0x03 (pointer, 8 B)   -> stride 16   (blk9  map @104: 5 * 16 = 80)
            value 0x0c/0x00 struct 79FA5B49  -> stride 24   (blk12: 22 * 24 = 528)
            value 0x0c/0x00 struct 13BCCC13  -> stride 32   (blk11: 3,837 * 32 = 122,784)
        A fixed stride of 16 read the first map correctly and walked off the other two - 19,291
        bytes in one file, and every one of them non-zero. The block size is the check: it equals
        count * stride to the byte in all five, which is why the rule can be argued rather than
        fitted.
        """
        buf = self._blk(bidx)
        mode, p0, ptr, p1, cnt, cap, p2 = struct.unpack_from('>IIIIHHI', buf, o)
        self._w(bidx, o, 'p', ('>IIIIHHI', (mode, p0, ptr, p1, cnt, cap, p2)))
        ents = sdef['entries']
        kidx, vidx = (e['extra'] >> 16) & 0xFFFF, e['extra'] & 0xFFFF
        if kidx >= len(ents) or vidx >= len(ents):
            self._note('map key/value descriptor index out of range')
            return
        if not (cnt and ptr):
            return
        tb, to = self.p.metaptr(ptr)
        if not (1 <= tb <= len(self.blocks)):
            self._note('map entry table block out of range')
            return
        vwidth = self._elem_stride(ents[vidx], sdef)
        stride = MAP_VALUE_OFF + vwidth
        if vwidth <= 0:
            self._note('map value width unknown (type %#04x)' % ents[vidx]['type'])
            return
        data = self._blk(tb)
        for i in range(cnt):
            eo = to + i * stride
            if eo + stride > len(data):
                self._note('map entry past end of block')
                break
            # The +4 word is written FIRST so a key wider than 4 bytes overwrites it rather than
            # the other way round; on every carrier measured it holds a word of unmapped meaning,
            # so it is re-encoded as a word and COUNTED, never claimed as understood.
            self._w(tb, eo + 4, 'p', ('>I', struct.unpack_from('>I', data, eo + 4)[0]),
                    self.T_UNTYPED)
            self._bump('map_unmapped_word_bytes', 4)
            self._elements(tb, eo, 1, ents[kidx], sdef, work)
            self._elements(tb, eo + MAP_VALUE_OFF, 1, ents[vidx], sdef, work)

    def _composite(self, bidx1, off, width):
        """An unmapped composite: re-encoded as N big-endian words, and COUNTED as carried."""
        buf = self._blk(bidx1)
        for i in range(width // 4):
            o2 = off + 4 * i
            if o2 + 4 <= len(buf):
                self._w(bidx1, o2, 'p', ('>I', struct.unpack_from('>I', buf, o2)[0]),
                        self.T_UNTYPED)
        self._bump('unmapped_composite_bytes', width)

    def _string_at(self, mp):
        """Follow a metapointer to a NUL-terminated string and schedule its re-encode."""
        if mp == 0:
            return
        bidx, off = self.p.metaptr(mp)
        if not (1 <= bidx <= len(self.blocks)):
            self._note('string metaptr block out of range')
            return
        data = self._blk(bidx)
        end = data.find(b'\x00', off)
        if end < 0:
            self._note('unterminated string in block')
            return
        self._w(bidx, off, 's', data[off:end].decode('latin1'))

    def _walk(self):
        """Walk the file's own declared type graph from the root struct.

        An explicit worklist, not recursion: `.cut` event trees nest deep enough that Python's
        default recursion limit is a real risk, and a writer that dies on the deepest file in the
        lane would silently shrink the sample it is supposed to measure.
        """
        bid, _data = self.p.root()
        work = [(self.root_idx, 0, bid)]
        seen = set()
        while work:
            bidx, off, sh = work.pop()
            key = (bidx, off, sh)
            if key in seen:
                continue
            seen.add(key)
            try:
                sdef = self.p.struct_def(sh)
            except _pso.PsoError:
                self._note('no schema for struct %08X' % sh)
                continue
            self.reached.add((bidx, off, sdef['size']))
            real = self._offsets(sdef)
            for i, e in enumerate(sdef['entries']):
                if e['name'] == ELEM:
                    continue
                try:
                    self._member(sdef, e, bidx, off + (e['off'] if real is None else real[i]),
                                 work)
                except (struct.error, IndexError, _pso.PsoError):
                    self._note('member decode failed (type %#04x)' % e['type'])

    # ---- the field map: how wide is one member, and where does it really start ----
    def _elem_stride(self, desc, sdef):
        et, esub, eextra = desc['type'], desc['sub'], desc['extra']
        if et == 0x0c:
            if esub == 0x03:
                return 8
            try:
                return self.p.struct_def(eextra)['size']
            except _pso.PsoError:
                return 0
        if et == 0x0b:
            return _str_elem_stride(esub)
        if et in VEC:
            return VEC_SLOT[et]
        if et in SCALAR_FMT:
            return SCALAR_FMT[et][1]
        if et == 0x0e:
            return 4
        if et in COMPOSITE:
            return COMPOSITE[et]
        if et == 0x0d:
            return 16
        return 0

    def _span(self, sdef, e):
        """Bytes one member occupies. This IS the field map - the same claim `yvr_write`'s
        `_check_tiling` makes at import, except here it is per-struct and read off the file."""
        t, sub, extra = e['type'], e['sub'], e['extra']
        if t == 0x0d:
            if sub == 0x00:
                return 16
            ents = sdef['entries']
            ridx = extra & 0xFFFF
            if ridx >= len(ents):
                return 16
            n = (extra >> 16) * self._elem_stride(ents[ridx], sdef)
            return n + (4 if sub in (0x01, 0x02, 0x81) else 0)
        if t == 0x0b:
            if sub == 0x00:
                return extra >> 16
            if sub == 0x03:
                return 16
            return 8 if sub in (0x01, 0x02) else 4
        if t == 0x0c:
            if sub in (0x03, 0x04):
                return 8
            if extra == 0:
                return 0
            try:
                return self.p.struct_def(extra)['size']
            except _pso.PsoError:
                return 0
        if t == MAP_TYPE:
            return MAP_SLOT
        if t in VEC:
            return VEC_SLOT[t]
        if t in COMPOSITE:
            return COMPOSITE[t]
        if t in SCALAR_FMT:
            return SCALAR_FMT[t][1]
        if t == 0x0e:
            return 1 if sub == 0x02 else 4
        if t == 0x0f:
            return _flags_width(extra)
        return 4

    def _offsets(self, sdef):
        """Real member offsets. None means "the declared u16 offsets are the real ones".

        ⭐ THE SCHEMA'S MEMBER OFFSET IS A u16 AND IT WRAPS. A struct larger than 65,536 bytes
        cannot express its later members' offsets, so the high bits must be rebuilt. Measured
        across the family: exactly ONE struct def of 20,283 is that large - `junctions.pso`'s
        root 12B475A0 at 170,688 B - and its `AutoJunctionAdjustments` declares 0x99B0 while
        living at 0x299B0, i.e. declared + 2 * 65,536, EXACTLY. Reconstructed by taking the
        smallest wrap that puts the member at or after the previous member's end, which is why
        `_span` has to be right: an over- or under-stated span moves the member and the round-trip
        rejects it. Structs at or under 65,535 B are untouched - no rule is applied where none is
        needed.
        """
        key = sdef['hash']
        cache = getattr(self, '_offcache', None)
        if cache is None:
            cache = self._offcache = {}
        if key in cache:
            return cache[key]
        if sdef['size'] <= 0xFFFF:
            cache[key] = None
            return None
        out = {}
        cursor = 0
        for i, e in enumerate(sdef['entries']):
            if e['name'] == ELEM:
                continue
            off, k = e['off'], 0
            while off + k * 0x10000 < cursor and off + (k + 1) * 0x10000 <= sdef['size']:
                k += 1
            out[i] = off + k * 0x10000
            cursor = out[i] + self._span(sdef, e)
        cache[key] = out
        return out

    def _member(self, sdef, e, bidx, o, work):
        t, sub, extra = e['type'], e['sub'], e['extra']
        buf = self._blk(bidx)
        if t == 0x0d:
            return self._array(sdef, e, bidx, o, work)
        if t == 0x0b:
            if sub == 0x00:                                   # inline fixed char[len]
                ln = extra >> 16
                raw = bytes(buf[o:o + ln])
                cut = raw.find(b'\x00')
                if cut < 0:
                    self._w(bidx, o, 'b', raw, self.T_CARRIED)
                    self._bump('string_fixed_no_nul_bytes', ln)
                else:
                    self._w(bidx, o, 's', raw[:cut].decode('latin1'))
                    tail = raw[cut + 1:]
                    if tail.strip(b'\x00'):
                        # Trailing garbage inside a fixed char[] slot: carried, and counted so it
                        # can never pass as modelled.
                        self._w(bidx, o + cut + 1, 'b', tail, self.T_CARRIED)
                        self._bump('string_fixed_tail_carried', len(tail))
                return
            if sub in (0x01, 0x02, 0x03):                     # pointer to a string in a block
                # ⭐ SUB 0x03 IS A SIXTEEN-BYTE SLOT, not a bare pointer - the same
                # {u32 metaptr, u32 pad, u16 capacity, u16 length, u32 pad} record the string
                # ARRAY lane already models (`pso2xml` derived that stride for elements; the
                # MEMBER form has it too, 1,591 of 1,591 carriers measured at slot 16). Writing
                # only the pointer left the capacity/length pair zero and cost every `.cut` in
                # the game exactly 2 bytes - a defect small enough to look like rounding and
                # large enough to take the lane from 100% to 0% byte-exact.
                mp = struct.unpack_from('>I', buf, o)[0]
                if sub == 0x03:
                    p1, cap, ln, p2 = struct.unpack_from('>IHHI', buf, o + 4)
                    self._w(bidx, o, 'p', ('>IIHHI', (mp, p1, cap, ln, p2)))
                else:
                    self._w(bidx, o, 'p', ('>I', mp))
                self._string_at(mp)
                return
            self._w(bidx, o, 'p', ('>I', struct.unpack_from('>I', buf, o)[0]))   # joaat hash
            return
        if t == 0x0e:
            if sub == 0x02:
                self._w(bidx, o, 'p', ('>b', struct.unpack_from('>b', buf, o)[0]))
            else:
                self._w(bidx, o, 'p', ('>I', struct.unpack_from('>I', buf, o)[0]))
            try:
                self.p.enum_def(extra)          # record the def as an ENUM for PSCH rebuild
            except _pso.PsoError:
                self._note('no enum def %08X' % extra)
            return
        if t == 0x0f:
            w = _flags_width(extra)
            fmt = {1: '>B', 2: '>H', 4: '>I'}.get(w, '>I')
            self._w(bidx, o, 'p', (fmt, struct.unpack_from(fmt, buf, o)[0]))
            idx = extra & 0xFFFF
            ents = sdef['entries']
            if idx < len(ents):
                try:
                    self.p.enum_def(ents[idx]['extra'])
                except _pso.PsoError:
                    self._note('no enum def for flags member')
            return
        if t == 0x0c:
            if sub in (0x03, 0x04):
                # ⭐ SUB 0x04 IS A POINTER TOO, and that is a READER GAP the XML lane shares.
                # `pso2xml` renders sub 0x04 as an empty element because its `extra` is 0, so it
                # has no struct hash to NAME - but the 8-byte slot still holds a live metapointer
                # and the pointed block's own id supplies the type, exactly as it does for sub
                # 0x03. Found 2026-08-15 by round-trip: in `trv_dri_ext.cut` a `cutfAttributes`
                # slot reaches block 14, which is a 16-byte wrapper holding a 9-element pointer
                # array into block 12, which reaches blocks 1 and 18 - 242 bytes of live data
                # that NOTHING in the type walk touched, in a file whose XML export looks clean.
                # This is the vault's own law biting: byte identity with a second reader cannot
                # see a gap both readers share; a writer can, because you cannot rebuild a
                # section you never read. 15,757 schema carriers across the family.
                mp = struct.unpack_from('>I', buf, o)[0]
                pad = struct.unpack_from('>I', buf, o + 4)[0]
                self._w(bidx, o, 'p', ('>II', (mp, pad)))
                if mp:
                    tb, to = self.p.metaptr(mp)
                    if 1 <= tb <= len(self.blocks):
                        work.append((tb, to, self.blocks[tb - 1][0]))
                    else:
                        self._note('struct metaptr block out of range')
                return
            if extra == 0:
                return                                        # typed-but-empty; occupies nothing
            work.append((bidx, o, extra))                     # inline struct
            return
        if t in SCALAR_FMT:
            self._scalar(bidx, o, t, sub)
            return
        if t == MAP_TYPE:
            self._map(sdef, e, bidx, o, work)
            return
        if t in VEC:
            self._vec(bidx, o, t)
            return
        if t in COMPOSITE:
            self._composite(bidx, o, COMPOSITE[t])
            return
        self._note('unhandled member type %#04x' % t)

    def _elements(self, tb, to, count, desc, sdef, work):
        """Re-encode `count` array elements at block `tb`, offset `to`. Returns bytes consumed."""
        et, esub, eextra = desc['type'], desc['sub'], desc['extra']
        if et == 0x0c and esub == 0x03:                       # array of struct POINTERS
            data = self._blk(tb)
            for i in range(count):
                so = to + i * 8
                mp, pad = struct.unpack_from('>II', data, so)
                self._w(tb, so, 'p', ('>II', (mp, pad)))
                if mp:
                    b2, o2 = self.p.metaptr(mp)
                    if 1 <= b2 <= len(self.blocks):
                        work.append((b2, o2, self.blocks[b2 - 1][0]))
            return count * 8
        if et == 0x0c:                                        # array of inline structs
            if eextra not in self.p.def_off:
                self._note('array element struct %08X missing' % eextra)
                return 0
            stride = self.p.struct_def(eextra)['size']
            for i in range(count):
                work.append((tb, to + i * stride, eextra))
            return count * stride
        if et == 0x0b:                                        # array of strings
            stride = _str_elem_stride(esub)
            data = self._blk(tb)
            for i in range(count):
                so = to + i * stride
                if stride == 16:
                    mp, p1, cap, ln, p2 = struct.unpack_from('>IIHHI', data, so)
                    self._w(tb, so, 'p', ('>IIHHI', (mp, p1, cap, ln, p2)))
                    self._string_at(mp)
                elif stride == 8:
                    mp, p1 = struct.unpack_from('>II', data, so)
                    self._w(tb, so, 'p', ('>II', (mp, p1)))
                    self._string_at(mp)
                else:
                    self._w(tb, so, 'p', ('>I', struct.unpack_from('>I', data, so)[0]))
            return count * stride
        if et in VEC:
            slot = VEC_SLOT[et]
            for i in range(count):
                self._vec(tb, to + i * slot, et)
            return count * slot
        if et in COMPOSITE:
            for i in range(count):
                self._composite(tb, to + i * COMPOSITE[et], COMPOSITE[et])
            return count * COMPOSITE[et]
        if et in SCALAR_FMT:
            wid = SCALAR_FMT[et][1]
            for i in range(count):
                self._scalar(tb, to + i * wid, et, esub)
            return count * wid
        if et == 0x0e:                                        # array of enums (u32 values)
            data = self._blk(tb)
            for i in range(count):
                self._w(tb, to + i * 4, 'p', ('>I', struct.unpack_from('>I', data, to + i * 4)[0]))
            try:
                self.p.enum_def(eextra)
            except _pso.PsoError:
                self._note('no enum def %08X for array' % eextra)
            return count * 4
        if et == 0x0d:                                        # array OF pointer-arrays
            ridx2 = eextra & 0xFFFF
            ents = sdef['entries']
            if ridx2 >= len(ents):
                self._note('nested-array inner refTypeIdx out of range')
                return 0
            inner = ents[ridx2]
            data = self._blk(tb)
            for i in range(count):
                so = to + i * 16
                ptr, p1, cnt, cap = struct.unpack_from('>IIHH', data, so)
                p2 = struct.unpack_from('>I', data, so + 12)[0]
                self._w(tb, so, 'p', ('>IIHHI', (ptr, p1, cnt, cap, p2)))
                if cnt and ptr:
                    b2, o2 = self.p.metaptr(ptr)
                    if 1 <= b2 <= len(self.blocks):
                        self._elements(b2, o2, cnt, inner, sdef, work)
            return count * 16
        self._note('unhandled array element type %#04x' % et)
        return 0

    def _array(self, sdef, e, bidx, o, work):
        ents = sdef['entries']
        ridx = e['extra'] & 0xFFFF
        if ridx >= len(ents):
            self._note('array refTypeIdx out of range')
            return
        desc = ents[ridx]
        buf = self._blk(bidx)
        if e["sub"] == 0x00:                                  # POINTER array: 16-B descriptor
            ptr, p1, count, cap = struct.unpack_from('>IIHH', buf, o)
            p2 = struct.unpack_from('>I', buf, o + 12)[0]
            self._w(bidx, o, 'p', ('>IIHHI', (ptr, p1, count, cap, p2)))
            if count and ptr:
                tb, to = self.p.metaptr(ptr)
                if 1 <= tb <= len(self.blocks):
                    self._elements(tb, to, count, desc, sdef, work)
                else:
                    self._note('array metaptr block out of range')
            return
        count = e['extra'] >> 16                              # INLINE array
        used = self._elements(bidx, o, count, desc, sdef, work)
        # ⭐ AN INLINE ARRAY CARRIES ITS OWN COUNT WORD, immediately after its CAPACITY elements.
        # `extra >> 16` is the CAPACITY (the fixed slot count); the live element count is a u32
        # stored right past the last slot. Derived 2026-08-15 from two files that disagreed with
        # each other and agreed with this: `junctions.pso` Entries has capacity 150 and the word
        # after 150*1136 bytes reads 150; `trv_dri_ext.cut` concatDataList has capacity 40 and the
        # word after 40*64 bytes reads 1. Both were the ONLY non-zero byte the model was missing
        # in their file. Sub 0x04 has NO such word - its slots butt straight against the next
        # member (iCutsceneFlags: 4 elements of 4 B at 528, vOffset at 544) - so writing one there
        # would corrupt the neighbour rather than model anything.
        if e['sub'] in (0x01, 0x02, 0x81) and used:
            co = o + used
            if co + 4 <= len(buf):
                self._w(bidx, co, 'p', ('>I', struct.unpack_from('>I', buf, co)[0]))
                self._bump('inline_array_count_word_bytes', 4)   # a real value: the live count

    # ------------------------------------------------------------------ the writer
    def _block_images(self):
        imgs = [bytearray(s) for _b, _o, s in self.blocks]
        for bi, off, kind, payload, _tag in self.writes:
            img = imgs[bi]
            if kind == 'p':
                fmt, vals = payload
                if not isinstance(vals, tuple):
                    vals = (vals,)
                if off + struct.calcsize(fmt) > len(img):
                    continue
                struct.pack_into(fmt, img, off, *vals)
            elif kind == 's':
                raw = payload.encode('latin1') + b'\x00'
                img[off:off + len(raw)] = raw
            else:                                             # 'b' - carried bytes, counted
                img[off:off + len(payload)] = payload
        return imgs

    def _psin(self):
        """The PSIN payload, with block offsets COMPUTED from the layout law."""
        imgs = self._block_images()
        out = bytearray()
        out += bytes([PSIN_PAD]) * 8                          # derived, never carried
        self.block_off = []
        for i, (_bid, _oo, sz) in enumerate(self.blocks):
            at = (len(out) + 8 + 15) & ~15                    # +8 for this section's own header
            pad = at - 8 - len(out)
            out += bytes([PSIN_PAD]) * pad
            self.block_off.append(at)
            out += imgs[i][:sz].ljust(sz, b'\x00')
        return bytes(out)

    def _pmap(self):
        out = bytearray()
        out += struct.pack('>IHH', self.root_idx, len(self.blocks), self.pmap_pad)
        for i, (bid, _oo, sz) in enumerate(self.blocks):
            out += struct.pack('>IIII', bid, self.block_off[i], 0, sz)
        return bytes(out)

    def _psch(self):
        """Rebuild the schema section from decoded defs, with body offsets COMPUTED."""
        p, pl = self.p, self.p.psch
        order = [h for h, _ in sorted(p.def_off.items(), key=lambda kv: kv[1])]
        bodies = []
        for h in order:
            o = p.def_off[h]
            kind = self.kind_of.get(h, 'unknown')
            if kind == 'struct':
                cnt, size, _z = struct.unpack_from('>III', pl, o)
                b = bytearray(struct.pack('>III', cnt, size, 0))
                for i in range(cnt):
                    nh, ty, sub, off_, extra = struct.unpack_from('>IBBHI', pl, o + 12 + 12 * i)
                    b += struct.pack('>IBBHI', nh, ty, sub, off_, extra)
                bodies.append(bytes(b))
            elif kind == 'enum':
                hdr = struct.unpack_from('>I', pl, o)[0]
                b = bytearray(struct.pack('>I', hdr))
                for i in range(hdr & 0xFFFF):
                    mh, val = struct.unpack_from('>Ii', pl, o + 4 + 8 * i)
                    b += struct.pack('>Ii', mh, val)
                bodies.append(bytes(b))
            else:
                ext = p.def_extents()[h][1]
                bodies.append(bytes(pl[o:o + ext]))
                self._bump('psch_def_carried_bytes', ext)
        out = bytearray(struct.pack('>I', len(order)))
        at = 4 + 8 * len(order)
        heads = bytearray()
        for h, b in zip(order, bodies):
            heads += struct.pack('>II', h, at + 8)            # secRelOffset = body offset + 8
            at += len(b)
        out += heads
        for b in bodies:
            out += b
        return bytes(out)

    def _payload(self, name):
        if name == 'PSIN':
            return self._psin()
        if name == 'PMAP':
            return self._pmap()
        if name == 'PSCH':
            return self._psch()
        if name == 'PSIG':
            return self.psig
        if name == 'STRF':
            return b''.join(s + b'\x00' for s in self.strf) if self.strf is not None else b''
        if name == 'STRE':
            return self.stre
        if name == 'CHKS':
            # Two of three words COMPUTED. The middle one is carried and counted.
            return struct.pack('>II', self.size, self.chks_sum) + self.chks_tail
        return self.opaque.get(name, b'')

    def write(self):
        """Rebuild the whole file. Section offsets and sizes are COMPUTED as we go."""
        img = bytearray()
        self._sec_layout = []
        for name in self.order:
            pay = self._payload(name)
            self._sec_layout.append((name, len(img), len(pay)))
            img += name.encode('latin1')[:4].ljust(4, b'\x00')
            img += struct.pack('>I', len(pay) + 8)
            img += pay
        if len(img) < self.size:
            img += bytes(self.size - len(img))                # short -> the gap stays ZERO, LOUD
        return bytes(img)

    # ------------------------------------------------------------------ the measure
    def unreached(self):
        """(differing bytes, of which non-zero in the original).

        A ZERO gap is padding we did not have to understand. A NON-ZERO gap is data we are
        dropping - which is exactly what this exercise exists to surface.
        """
        got, orig = self.write(), self.blob
        n = min(len(got), len(orig))
        try:
            import numpy as _np
            a = _np.frombuffer(got[:n], dtype=_np.uint8)
            b = _np.frombuffer(orig[:n], dtype=_np.uint8)
            d = a != b
            bad = int(d.sum()) + abs(len(got) - len(orig))
            nz = int(((b != 0) & d).sum())
        except ImportError:
            bad = nz = 0
            for i in range(n):
                if got[i] != orig[i]:
                    bad += 1
                    if orig[i] != 0:
                        nz += 1
            bad += abs(len(got) - len(orig))
        return bad, nz

    # ------------------------------------------------------------------ byte accounting
    # ⭐ DISCLOSURE, NOT DECORATION. Byte identity alone cannot tell a rebuilt region from a copied
    # one: the vault's law is that a claimed region is evidence ONLY IF A WRONG CLAIM COULD HAVE
    # BEEN REJECTED. `.ymt` round-tripped 2,326/2,326 once with 11.66% of the image carried
    # verbatim, and that 100% was worthless. So this returns the SPLIT, exactly - not an estimate:
    # every byte of the rebuilt image is tagged as it is produced and the tags are counted.
    #   VALUE    re-encoded from a decoded, typed field value
    #   UNTYPED  re-encoded as a raw word at a schema-PINNED offset, semantics unmapped. A subset
    #            of VALUE for totalling; broken out because "we reproduced it" and "we understand
    #            it" are different claims and only the first is proven here.
    #   DERIVED  computed from a rule, never read at that position (section sizes and offsets,
    #            block offsets, the 0x70 padding, the PMAP zero column, the CHKS file size)
    #   CARRIED  copied bytes; the round-trip could not have rejected them
    #   ZERO     never written by the model; matches only because the original is zero there
    def regions(self):
        img = self.write()
        tags = bytearray(len(img))
        V, U, D, C = self.T_VALUE, self.T_UNTYPED, 3, self.T_CARRIED

        def paint(a, n, t):
            if n > 0:
                tags[a:a + n] = bytes([t]) * n

        # --- per-block tags from the type walk -------------------------------------------
        blk_tags = [bytearray(sz) for _b, _o, sz in self.blocks]
        for bi, off, kind, payload, tag in self.writes:
            if bi >= len(blk_tags):
                continue
            if kind == 'p':
                n = struct.calcsize(payload[0])
            elif kind == 's':
                n = len(payload) + 1
            else:
                n = len(payload)
            t = blk_tags[bi]
            end = min(off + n, len(t))
            for k in range(max(off, 0), end):
                t[k] = tag
        for name, at, paylen in self._sec_layout:
            paint(at, 8, D)                                   # every section header is COMPUTED
            po = at + 8
            if name == 'PSIN':
                paint(po, paylen, D)                          # lead pad + inter-block pad
                for i, (_b, _o, sz) in enumerate(self.blocks):
                    bo = self.block_off[i]
                    for k in range(sz):
                        tags[bo + k] = blk_tags[i][k]
            elif name == 'PMAP':
                paint(po, 4, V)                               # root block index
                paint(po + 4, 4, D)                           # nBlocks + reserved 0x7070
                for i in range(len(self.blocks)):
                    r = po + 8 + 16 * i
                    paint(r, 4, V)                            # block id
                    paint(r + 4, 8, D)                        # COMPUTED offset + the zero column
                    paint(r + 12, 4, V)                       # block byte size
            elif name == 'PSCH':
                n = len(self.p.def_off)
                paint(po, 4, D)                               # def count
                for i in range(n):
                    paint(po + 4 + 8 * i, 4, V)               # def hash
                    paint(po + 8 + 8 * i, 4, D)               # COMPUTED body offset
                paint(po + 4 + 8 * n, paylen - 4 - 8 * n, V)  # def bodies
                carried = self.acct.get('psch_def_carried_bytes', 0)
                if carried:
                    paint(po + paylen - carried, carried, C)
            elif name == 'STRF':
                paint(po, paylen, V)
            elif name == 'CHKS':
                paint(po, 4, D)                               # total file size, COMPUTED
                paint(po + 4, 4, C)                           # the checksum word
                paint(po + 8, paylen - 8, D)                  # the 0x79707070 constant
            else:                                             # PSIG / STRE / anything unmodelled
                paint(po, paylen, C)
        out = {'total': self.size, 'value': 0, 'value_untyped': 0,
               'derived': 0, 'carried': 0, 'zero_fill': 0}
        try:
            import numpy as _np
            a = _np.frombuffer(bytes(tags), dtype=_np.uint8)
            cnt = _np.bincount(a, minlength=5)
            out['zero_fill'] = int(cnt[0])
            out['value'] = int(cnt[V])
            out['value_untyped'] = int(cnt[U])
            out['derived'] = int(cnt[D])
            out['carried'] = int(cnt[C])
        except ImportError:
            for t in tags:
                out[{0: 'zero_fill', V: 'value', U: 'value_untyped',
                     D: 'derived', C: 'carried'}[t]] += 1
        return out


# ---------------------------------------------------------------------- must-fail control
# BYTE IDENTITY CANNOT TELL A PINNED CLAIM FROM A COPIED ONE. The comparison image copies the
# ORIGINAL bytes at whatever offsets a writer claims, so an unpinned claim is SELF-FULFILLING and
# a 100% score proves nothing on its own. The answer is a control that MUST FAIL: corrupt the
# MODEL - not the file - and demand the rebuilt image stops matching. A mutation that is NOT
# caught names a region the measure cannot see.
#
# The classes below attack DIFFERENT claims, because they fail differently:
#   value   - a decoded field's value. Catches "did we re-encode it, or copy it?"
#   drop    - a whole field write removed. Catches "does this field's region actually get written
#             by the model, or is it matching because the original happens to be zero there?"
#   layout  - a block's declared byte size. Every LATER block offset and the PSIN section size are
#             COMPUTED from it, so a wrong size must wreck the file. Catches "is the PMAP offset
#             column pinned, or is it a self-fulfilling copy?"
#   root    - the PMAP root block index. Catches "is the root a value or a copied word?"
#   schema  - a PSCH def reclassified as unknown-and-therefore-carried. THIS ONE IS EXPECTED NOT
#             TO FIRE: a carried body reproduces the same bytes, which is exactly what "carried"
#             means. It is kept because a battery containing only tests it passes is decoration,
#             and its 0% is the cleanest demonstration in this file of what a carried region is.
def _effective(m):
    """Per-block array naming, for every byte, the LAST write that touches it.

    Needed because writes can shadow each other - a map entry's filler word is written before the
    key that may cover it, and a struct instance reached twice writes twice. Mutating a SHADOWED
    write cannot move the image, so including one in the battery would manufacture a false
    negative about the writer rather than measure it.
    """
    last = [bytearray()] * 0
    last = [[-1] * sz for _b, _o, sz in m.blocks]
    for i, (bi, off, kind, payload, _t) in enumerate(m.writes):
        if bi >= len(last):
            continue
        if kind == 'p':
            n = struct.calcsize(payload[0])
        elif kind == 's':
            n = len(payload) + 1
        else:
            n = len(payload)
        row = last[bi]
        for k in range(max(off, 0), min(off + n, len(row))):
            row[k] = i
    return last


def _informative(m, tag, last):
    """Write indices that (a) carry this accounting tag, (b) are the LAST writer of at least one
    byte, and (c) that byte is NON-ZERO in the original.

    A mutation aimed at a region the original leaves zero is UNDETECTABLE BY CONSTRUCTION -
    zero-fill already reproduces it. Counting those as control failures would understate the
    measure; counting them as passes would overstate it. So they are excluded and REPORTED as
    `zero_region_writes`: they are the part of the model this measure cannot speak to.
    """
    out = []
    for i, (bi, off, kind, payload, t) in enumerate(m.writes):
        if kind != 'p' or t != tag or bi >= len(m._orig_block):
            continue
        n = struct.calcsize(payload[0])
        ob = m._orig_block[bi]
        row = last[bi]
        for k in range(off, min(off + n, len(row))):
            if row[k] == i and ob[k]:
                out.append(i)
                break
    return out


def _mutations(m):
    """(class, index) pairs, plus the count of writes excluded as zero-region."""
    out = []
    last = _effective(m)
    val = _informative(m, m.T_VALUE, last)
    unt = _informative(m, m.T_UNTYPED, last)
    npw = sum(1 for w in m.writes if w[2] == 'p')
    excluded = npw - len(val) - len(unt)
    for i in _pick(val, 3):
        out.append(('value', i))
    for i in _pick(val, 2):
        out.append(('drop', i))
    for i in _pick(unt, 2):
        out.append(('untyped', i))
    if len(m.blocks) > 1:
        # ⛔ BOTH OF THESE NEED MORE THAN ONE BLOCK TO MEAN ANYTHING. On a single-block file
        # flipping the root index has nowhere to go and resizing block 0 changes only the last
        # block, so the mutation would be a no-op and its miss would be an artefact of the
        # battery rather than a fact about the writer. A control must not manufacture its own
        # false negatives.
        out.append(('layout', 0))
        out.append(('root', 0))
    if m.kind_of:
        out.append(('schema', 0))
    return out, excluded


def _pick(xs, n):
    if not xs:
        return []
    if len(xs) <= n:
        return list(xs)
    step = max(1, len(xs) // n)
    return [xs[i * step] for i in range(n)]


def control(m):
    """Run the must-fail battery. Returns (caught, total, {class: [caught, total]}, excluded).

    Only meaningful on a file that round-trips EXACTLY - "the image moved" is not evidence if the
    image was already wrong - so the caller must check that first.
    """
    base = m.write()
    muts, excluded = _mutations(m)
    per = {}
    caught = total = 0
    for kind, idx in muts:
        saved_writes = list(m.writes)
        saved_blocks = list(m.blocks)
        saved_root = m.root_idx
        saved_kind = dict(m.kind_of)
        try:
            if kind in ('value', 'untyped'):
                bi, off, k, payload, tag = m.writes[idx]
                fmt, vals = payload
                vv = list(vals) if isinstance(vals, tuple) else [vals]
                try:
                    vv[0] = int(vv[0]) ^ 1
                except (TypeError, ValueError):
                    vv[0] = 1.0 if not vv[0] else 0.0
                m.writes[idx] = (bi, off, k, (fmt, tuple(vv)), tag)
            elif kind == 'drop':
                del m.writes[idx]
            elif kind == 'layout':
                bid, oo, sz = m.blocks[0]
                m.blocks[0] = (bid, oo, sz + 16)
            elif kind == 'root':
                m.root_idx = 1 if m.root_idx != 1 else 2
            elif kind == 'schema':
                m.kind_of[next(iter(m.kind_of))] = 'unknown'
            try:
                got = m.write()
            except Exception:
                got = None
            total += 1
            hit = (got is None) or (got != base)
            caught += 1 if hit else 0
            q = per.setdefault(kind, [0, 0])
            q[1] += 1
            q[0] += 1 if hit else 0
        finally:
            m.writes = saved_writes
            m.blocks = saved_blocks
            m.root_idx = saved_root
            m.kind_of = saved_kind
    return caught, total, per, excluded


# ---------------------------------------------------------------------- lane entry points
def read_pso_any(src):
    blob = bytes(src) if isinstance(src, (bytes, bytearray)) else open(src, 'rb').read()
    return PsoRT(blob)


read_ymf = read_pso_any
read_cut = read_pso_any
read_pso = read_pso_any
read_ymt_psin = read_pso_any


def _main():
    """Population measure + byte accounting + the must-fail control, in one command.

        python quarry/pso_write.py --all
        python quarry/pso_write.py --lane ymt_psin --limit 9000

    Prints SAMPLE SIZE for every lane and REFUSES on an empty sample - a clean result from a
    sample of zero is not a result. ASCII output only.
    """
    import argparse
    import collections
    _sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), 'tools'))
    import roundtrip_coverage as RC
    LANES = ('ymf', 'cut', 'pso', 'ymt_psin')
    ap = argparse.ArgumentParser()
    ap.add_argument('--lane', choices=LANES)
    ap.add_argument('--all', action='store_true')
    ap.add_argument('--limit', type=int, default=9000)
    ap.add_argument('--control', type=int, default=200,
                    help='how many exactly-round-tripping files to run the must-fail battery on')
    a = ap.parse_args()
    if not a.lane and not a.all:
        ap.error('pass --lane <name> or --all')
    lanes = LANES if a.all else (a.lane,)
    print('PSO/PSIN FAMILY - ROUND-TRIP AT POPULATION (the primary measure)')
    print('whole file -> value model -> written back -> compare. Unreached bytes count AGAINST.')
    bad = 0
    for ln in lanes:
        _mod, _fn, arcs = RC.LANES[ln]
        rep = {}
        files = RC.harvest(ln, arcs, a.limit, cap=0, gate=RC.GATES.get(ln), report=rep)
        print('')
        print('lane %-9s SAMPLE SIZE: %d   [NO CAP (population draw)]' % (ln, len(files)))
        print('  container gate  : %d OTHER-CONTAINER turned away (a different format, NOT a pass'
              ' for them)' % rep.get('rejected', 0))
        if not files:
            print('  REFUSING: empty sample - a harness with no subject cannot report coverage.')
            bad += 1
            continue
        exact = tot = 0
        cov = []
        acc = collections.Counter()
        err = collections.Counter()
        notes = collections.Counter()
        cc = ct = nctl = cex = 0
        cper = {}
        worst = None
        for nm, blob in files:
            try:
                m = PsoRT(blob)
                n, _nz = m.unreached()
            except Exception as ex:
                err[type(ex).__name__] += 1
                continue
            tot += 1
            c = 100.0 * (m.size - n) / m.size
            cov.append(c)
            if n == 0:
                exact += 1
            if worst is None or c < worst[0]:
                worst = (c, nm)
            for k, v in m.regions().items():
                acc[k] += v
            for k, v in m.notes.items():
                notes[k] += v
            if nctl < a.control and n == 0:
                nctl += 1
                a1, b1, p1, ex1 = control(m)
                cc += a1
                ct += b1
                cex += ex1
                for k, v in p1.items():
                    q = cper.setdefault(k, [0, 0])
                    q[0] += v[0]
                    q[1] += v[1]
        if not tot:
            print('  REFUSING: every file errored - %s' % dict(err))
            bad += 1
            continue
        print('  EXACT round-trip: %d / %d (%.4f%%)' % (exact, tot, 100.0 * exact / tot))
        print('  mean coverage   : %.4f%%   min %.4f%% (%s)'
              % (sum(cov) / len(cov), worst[0], worst[1]))
        t = acc['total'] or 1
        print('  BYTE ACCOUNTING over %d files, %d bytes:' % (tot, acc['total']))
        for k in ('value', 'value_untyped', 'derived', 'carried', 'zero_fill'):
            print('    %-14s %12d  %6.3f%%' % (k, acc[k], 100.0 * acc[k] / t))
        print('    value_untyped = reproduced at a schema-PINNED offset, semantics unmapped.')
        print('    carried       = could NOT have been rejected by this measure.')
        if ct:
            print('  MUST-FAIL CONTROL on %d files: %d / %d mutations caught (%.2f%%)'
                  % (nctl, cc, ct, 100.0 * cc / ct))
            for k in sorted(cper):
                print('    %-8s %d / %d' % (k, cper[k][0], cper[k][1]))
            print('    zero_region_writes excluded from the battery: %d  (a mutation there is'
                  ' undetectable BY CONSTRUCTION - zero-fill already reproduces it)' % cex)
        else:
            print('  MUST-FAIL CONTROL: NOT RUN - no exactly-round-tripping file to mutate.')
        if err:
            print('  errors          : %s' % dict(err))
        if notes:
            print('  model notes     : %s' % dict(notes.most_common(6)))
    return 1 if bad else 0


if __name__ == '__main__':
    _sys.exit(_main())
