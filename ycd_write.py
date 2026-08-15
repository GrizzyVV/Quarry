"""ycd_write - ROUND-TRIP WRITER for .ycd (rage::crClipDictionary, RSC7 v46).

    inflated system segment -> value model -> written back -> MUST reproduce the original bytes

⛔⛔ READ THIS BEFORE QUOTING A NUMBER FROM THIS MODULE - IT REPORTS **TWO** FIGURES AND THEY
    ARE NOT INTERCHANGEABLE:

      (1) BYTE-EXACT / COVERAGE - how much of the container this model rebuilds.
      (2) THE UNDECODED INLINE-QuantizeFloat POOL - how many animation CHANNELS we still cannot
          reconstruct, by (selector, W) variant cell.

    ⛔ A byte-exact score MUST NEVER be quoted as "the ycd lane is done" while (2) is non-zero.
    They can both be large at once, because an undecoded channel's payload is CARRIED VERBATIM
    here: byte identity is satisfied by copying it, and copying it is exactly what Matt's ruling
    rejects - *"if we can't discern how to reconstruct the data, then the file is useless"*. The
    carry is deliberate (a file must not fail wholesale over one channel) and it is COUNTED in
    `regions()` under `carried`, per-channel in `qz_census()`. Matt's other half of the ruling -
    *"byte exact is at the least, half the battle, at least we can see the shape of it"* - is why
    the carry exists at all instead of a refusal.

MEASURED AT POPULATION 2026-08-15 - command, result, date:
    python tools/roundtrip_coverage.py --lane ycd --limit 30000 --cap 0
    (the figures below come from the equivalent local-corpus run over all 24,844 extracted files,
     823.8 s on 14 workers; the harness draw returns the same 24,844 straight from the archives)

  (1) BYTE-EXACT  24,836 / 24,840 v46 files = 99.9839%   mean 100.0000%   min 99.9998%
      on NON-ZERO original bytes only (the honest denominator - 21.4% of a .ycd segment is zero
      page padding): mean 100.0000%, min 99.9998%.
      BYTE ACCOUNT over 3,538,853,888 segment bytes:
          value      3,191,538,829   90.1857%   re-encoded from decoded values
          derived       46,526,826    1.3147%   computed (page count, bucket chains, sentinels)
          pointer       40,591,384    1.1470%   re-encoded from walked offsets - SELF-CONSISTENT
          carried       11,219,398    0.3170%   verbatim: inline-QZ trailing PADDING bits only
          zero_fill    248,977,451    7.0355%   never written, and zero in the original too
          unclaimed non-zero: 0        overlap: 0
      ⭐ 0.3170% CARRIED is the number to read next to the 99.98%. It is entirely the padding
      bits after the last Rice code in an inline-QZ payload - no animation DATA is carried.
      THE WHOLE RESIDUAL IS 4 BYTES IN 4 FILES: one page-count byte each, counted as
      `pagecount_stored_differs_from_computed` (see write()).
  (2) INLINE-QuantizeFloat VARIANT CENSUS - 4,732,238 channels examined at population:
          DECODED AND RE-ENCODED 4,732,238 (100.0000%)   UNDECODED 0   carried payload 0 B
          953 distinct (W, numBits, selector) cells; 96 distinct (selector, W) cells
      ⛔ Do not merge (1) and (2). They answer different questions and this module reports both.
  MUST-FAIL CONTROL over a 900-file draw, 8,718 / 8,734 mutations caught = 99.8168%:
          atmap_key            884/884   100.0000%    map_list_entry     884/884   100.0000%
          pagecount_computed   900/900   100.0000%    boneid_record      884/884   100.0000%
          packed_block_bit     884/884   100.0000%    count_table_entry  884/884   100.0000%
          static_pool_word     884/884   100.0000%    seq_trailer_record 870/870   100.0000%
          inline_qz_seed       760/760   100.0000%
          stride_overrun_LEDGER 884/900   98.2222%
      EVERY DATA REGION CATCHES AT 100%. ⚠ The one control below 100% is the ledger's OWN test -
      it widens the ANIM field map by 16 bytes and demands `overlap` fire. On 16 of 900 files the
      animation object is the LAST allocation in the arena, so the extra 16 bytes land in free
      space and collide with nothing: the ledger cannot see an over-claim that overruns into
      padding rather than into a neighbour. That is a REAL LIMIT OF THE INSTRUMENT, stated rather
      than rounded away - it is why struct strides are also argued from the histogram of what
      occupies the bytes (see TAGSCONT), not from the ledger alone.
      ⚠ A SECOND CONTROL LIMIT, from the game-drawn run (`python tools/ycd_control.py --limit 60`,
      542/543 = 99.8158%): `seq_trailer_record` scored 22/23 there. The mutation writes at a fixed
      offset inside the trailer without asking whether the model CLAIMED that byte, and a trailer
      cut short by the next allocation leaves it unclaimed - so the miss is the control aiming at
      an unmodelled byte, not a copied region. Left uncorrected on purpose: tuning a control until
      it passes is how a control stops being one.

WHY THIS EXISTS (2026-08-15). `ycd` is 24,844 files, the LARGEST UNMEASURED THING IN THE GAME
(`docs/LANE_CENSUS_20260814.md` section 3 row 1), and under the standing measure a lane with NO
WRITER is UNMEASURED, not passing. `ycd2xml.py` had only ever been scored against 57 hand-exported
oracles; nobody knew what fraction of a .ycd we actually reach. A writer answers that across ALL
24,844 files at no extra cost, because **you cannot rebuild a section you never read**.

MODEL, NOT MEMCPY. Every structure is decoded to typed fields and re-encoded into a ZERO-FILLED
image, so a byte the model never reaches stays zero and is LOUD. **The gaps are the finding.**

⭐⭐ THE CLAIM LEDGER - THIS IS THE PART THAT MAKES THE NUMBER MEAN ANYTHING.
This vault's law: *a claimed region is evidence only if a WRONG claim could have been REJECTED.*
The image copies original bytes at whatever offsets a writer claims, so two failures are invisible
to byte identity and both are checked here instead:
  * AN OVER-LONG STRIDE IS SELF-FULFILLING. If a struct claims 0x80 bytes when it is 0x70, the
    extra 16 bytes are re-encoded from the source at the same offsets and still match. So every
    write is recorded in `self.mark`, and a byte claimed TWICE raises the `overlap` counter -
    two structs cannot both own a byte. Overlap is reported, never absorbed.
  * A FIELD MAP WITH A HOLE IS A SILENT CARRY. `_check_tiling` runs AT IMPORT for every struct
    below and refuses unless the map tiles its stride with no hole and no overlap.

⭐ WHAT IS ACTUALLY PINNED (a wrong model FAILS these; they are not copies):
  * THE PAGE-COUNT RECORD is COMPUTED from the RSC7 segment flags via `meta_write.page_count`,
    never carried - the law proven on META (250/250), 259 .ynd and 9,145 .yvr/.ywr. Holds here.
  * THE atMap BUCKET ARRAY AND CHAIN LINKAGE ARE COMPUTED, not copied: bucket = key %% nbuckets.
    Measured 14,022 / 14,022 chain entries over a 400-file draw before this writer existed, then
    at population by this writer. A wrong key, a wrong bucket count or a wrong walk order writes
    the chain into the wrong bucket and the round-trip rejects it.
  * THE FRAME-MAJOR BIT-PACKED BLOCK IS RE-PACKED FROM DECODED INTEGERS, bit by bit. That pins
    channel ORDER, per-channel WIDTH, the DWORD-aligned frame stride, and the RawFloat-at-front
    geometry all at once - an off-by-one in any of them scrambles every later frame.
  * THE INLINE-QuantizeFloat PAYLOAD IS RE-ENCODED, not copied: the Rice codes are regenerated
    from the decoded raws and the per-block bit OFFSETS are RECOMPUTED from the encoder's own
    output. A decode that merely "looked plausible" cannot survive that - the offsets it writes
    would not match the offsets the file stores.
  * THE MAP-LIST PAD SENTINELS are computed as nBones*4, not copied.

⚠ SCOPE - the same boundary every writer in this tree declares: this round-trips the INFLATED
SYSTEM SEGMENT, not the compressed RSC7 container (reproducing an exact deflate stream is a
separate problem, and mixing them would make a compression difference look like a format defect).
.ycd carries NO graphics segment - 24,844/24,844 measured 2026-08-15 - and a non-empty one REFUSES
rather than being ignored.
⚠ POINTERS ARE RE-ENCODED FROM THE OFFSETS THE MODEL WALKED TO, which is a SELF-CONSISTENT claim,
not an independent one: it pins the tag nibble and that we walked where the file points, and it
does NOT prove we could lay out a new file. They are counted SEPARATELY in `regions()` (`pointer`)
and folded into DERIVED only when the four-bucket split is quoted. Never quote them as VALUE.

ASCII output only.
"""
import os
import struct
import sys as _sys

_sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ydr2xml import Res      # noqa: E402  (RSC7 container reader)
import meta_write            # noqa: E402  (page_count - COMPUTED, never carried)

# ------------------------------------------------------------------ byte-account kinds
VALUE, DERIVED, POINTER, CARRIED = 1, 2, 3, 4
KIND_NAME = {VALUE: 'value', DERIVED: 'derived', POINTER: 'pointer', CARRIED: 'carried'}
# Translation tables for the byte account - see regions(). Each maps a byte to 0x01 / 0x00 so the
# two masks can be ANDed as one big integer instead of looped over in Python.
_TBL_IS_ZERO = bytes([1] + [0] * 255)
_TBL_NONZERO = bytes([0] + [1] * 255)


def _check_tiling(fields, stride, what):
    """⛔ AN UNTILED FIELD MAP IS A SILENT CARRY, and an over-long one is a SELF-FULFILLING CLAIM.
    Run at import so "every byte of this struct is modelled" is refuted here rather than showing
    up later as coverage nobody can account for."""
    at = 0
    for off, code, _kind in fields:
        if off != at:
            raise ValueError('%s field map: hole/overlap at 0x%02x (expected 0x%02x)'
                             % (what, off, at))
        at += struct.calcsize(code)
    if at != stride:
        raise ValueError('%s field map covers %d of %d stride bytes' % (what, at, stride))
    return fields


# ------------------------------------------------------------------ struct field maps
# Each entry is (offset, struct code, byte-account kind). Field SEMANTICS live in `ycd2xml.py`;
# what a round-trip needs is the STORED form and, above all, that these maps TILE their stride.
# ⚠ EVERY STRIDE BELOW IS A CLAIM THE OVERLAP LEDGER CAN REJECT - if one is too long it collides
# with its neighbour in the arena and `overlap` fires.

ROOT = _check_tiling((
    (0x00, '<Q', VALUE),      # vtable
    (0x08, '<I', POINTER),    # -> block map (carries the COMPUTED page-count record)
    (0x0C, '<I', VALUE),
    (0x10, '<Q', VALUE),
    (0x18, '<I', POINTER),    # -> animation-dictionary object
    (0x1C, '<I', VALUE),
    (0x20, '<I', VALUE),
    (0x24, '<I', VALUE),
    (0x28, '<I', POINTER),    # -> clips bucket array (INLINE atMap)
    (0x2C, '<I', VALUE),
    (0x30, '<H', VALUE),      # nbuckets
    (0x32, '<H', VALUE),      # nentries
    (0x34, '<I', VALUE),
    (0x38, '<Q', VALUE),
), 0x40, 'root')

ANIMDICT = _check_tiling((
    (0x00, '<Q', VALUE),      # vtable
    (0x08, '<Q', VALUE),
    (0x10, '<Q', VALUE),
    (0x18, '<I', POINTER),    # -> bucket array
    (0x1C, '<I', VALUE),
    (0x20, '<H', VALUE),      # nbuckets
    (0x22, '<H', VALUE),      # nentries
    (0x24, '<I', VALUE),
    (0x28, '<Q', VALUE),
), 0x30, 'animdict')

# atMap entry node. `next` is COMPUTED from the chain the model rebuilt, `val` is a walked pointer.
NODE = _check_tiling((
    (0x00, '<I', VALUE),      # key (joaat / dictionary key) - DRIVES the bucket, see write()
    (0x04, '<I', VALUE),
    (0x08, '<I', POINTER),    # -> value object
    (0x0C, '<I', VALUE),
    (0x10, '<I', DERIVED),    # -> next node, recomputed from the rebuilt chain
    (0x14, '<I', VALUE),
), 0x18, 'atmap_node')

CLIP = _check_tiling((
    (0x00, '<Q', VALUE),      # vtable
    (0x08, '<Q', VALUE),
    (0x10, '<I', VALUE),      # Type 1=Animation 2=AnimationList
    (0x14, '<I', VALUE),
    (0x18, '<I', POINTER),    # -> name "pack:/<stem>.clip"
    (0x1C, '<I', VALUE),
    (0x20, '<H', VALUE),      # name atArray count (strlen)
    (0x22, '<H', VALUE),      # name atArray size  (strlen+1)
    (0x24, '<I', VALUE),
    (0x28, '<Q', VALUE),
    (0x30, '<I', VALUE),      # Unknown30
    (0x34, '<I', VALUE),
    (0x38, '<I', POINTER),    # -> crTags container
    (0x3C, '<I', VALUE),
    (0x40, '<I', POINTER),    # -> crProperties container
    (0x44, '<I', VALUE),
    (0x48, '<Q', VALUE),
    (0x50, '<I', POINTER),    # -> crAnimation (Type 1) or the inline ref array (Type 2)
    (0x54, '<I', VALUE),
    (0x58, '<I', VALUE),      # StartTime f32 (T1) / u16 count + u16 cap (T2)
    (0x5C, '<I', VALUE),      # EndTime f32 (T1)
    (0x60, '<I', VALUE),      # Rate f32 (T1) / Duration f32 (T2)
    (0x64, '<I', VALUE),
    (0x68, '<Q', VALUE),
), 0x70, 'clip')

# crClipAnimationList inline reference, stride 0x18 (Start@0, End@4, Rate@8, animptr@0x10).
CLIPREF = _check_tiling((
    (0x00, '<I', VALUE),      # StartTime f32
    (0x04, '<I', VALUE),      # EndTime f32
    (0x08, '<I', VALUE),      # Rate f32
    (0x0C, '<I', VALUE),
    (0x10, '<I', POINTER),    # -> crAnimation
    (0x14, '<I', VALUE),
), 0x18, 'clipref')

# crProperties container shell: {bucketptr, u16 nbuckets@+8, u16 nentries@+0x0A}. STRIDE 0x10 -
# measured: the 16 bytes at +0x10 hold the NEXT object (4 distinct contents in 53 samples), so a
# 0x20 claim here would be the same self-fulfilling over-claim the ANIM map made.
CONT = _check_tiling((
    (0x00, '<I', POINTER),
    (0x04, '<I', VALUE),
    (0x08, '<H', VALUE),
    (0x0A, '<H', VALUE),
    (0x0C, '<I', VALUE),
), 0x10, 'container')

# crTags container. ⭐ STRIDE 0x20, NOT 0x10, and the difference is a REAL FIELD the reader never
# reads: `ycd2xml.emit_tags` stops at the count. The writer found it as the last unclaimed
# non-zero run in the segment, and it is a two-valued field - +0x10..+0x20 is all-zero on 863
# containers and `01 00 00 00` + zeros on 384, with nothing else occurring (1,247 samples).
TAGSCONT = _check_tiling((
    (0x00, '<I', POINTER),
    (0x04, '<I', VALUE),
    (0x08, '<H', VALUE),
    (0x0A, '<H', VALUE),
    (0x0C, '<I', VALUE),
    (0x10, '<I', VALUE),
    (0x14, '<I', VALUE),
    (0x18, '<Q', VALUE),
), 0x20, 'tags_container')

# crProperty (and crTag, which extends it with StartPhase/EndPhase at +0x40).
PROP = _check_tiling((
    (0x00, '<Q', VALUE),      # vtable
    (0x08, '<Q', VALUE),
    (0x10, '<Q', VALUE),
    (0x18, '<I', VALUE),      # NameHash
    (0x1C, '<I', VALUE),
    (0x20, '<I', POINTER),    # -> attribute pointer array
    (0x24, '<I', VALUE),
    (0x28, '<H', VALUE),      # attribute count
    (0x2A, '<H', VALUE),      # attribute capacity
    (0x2C, '<I', VALUE),
    (0x30, '<Q', VALUE),
    (0x38, '<I', VALUE),      # UnkHash
    (0x3C, '<I', VALUE),
), 0x40, 'property')

TAG_EXTRA = _check_tiling((
    (0x00, '<I', VALUE),      # StartPhase f32
    (0x04, '<I', VALUE),      # EndPhase f32
    (0x08, '<Q', VALUE),
), 0x10, 'tag_extra')

ATTR = _check_tiling((
    (0x00, '<Q', VALUE),      # vtable
    (0x08, '<I', VALUE),      # Type (1 Float 2 Int 3 Bool 4 String 6 Vec3 8 Vec4 12 HashString)
    (0x0C, '<I', VALUE),
    (0x10, '<Q', VALUE),
    (0x18, '<I', VALUE),      # NameHash
    (0x1C, '<I', VALUE),
    (0x20, '<I', VALUE),      # Value word 0  (or, for Type 4, a pointer - see write())
    (0x24, '<I', VALUE),
    (0x28, '<I', VALUE),
    (0x2C, '<I', VALUE),
), 0x30, 'attribute')

ANIM = _check_tiling((
    (0x00, '<Q', VALUE),      # vtable
    (0x08, '<Q', VALUE),
    (0x10, '<B', VALUE),      # Unknown10
    (0x11, '<B', VALUE),
    (0x12, '<H', VALUE),
    (0x14, '<H', VALUE),      # FrameCount
    (0x16, '<H', VALUE),      # SequenceFrameLimit
    (0x18, '<I', VALUE),      # Duration f32
    (0x1C, '<I', VALUE),      # Unknown1C hash
    (0x20, '<Q', VALUE),
    (0x28, '<Q', VALUE),
    (0x30, '<Q', VALUE),
    (0x38, '<I', VALUE),
    (0x3C, '<I', VALUE),
    (0x40, '<I', POINTER),    # -> sequence pointer array
    (0x44, '<I', VALUE),
    (0x48, '<H', VALUE),      # sequence count
    (0x4A, '<H', VALUE),      # sequence capacity
    (0x4C, '<I', VALUE),
    (0x50, '<I', POINTER),    # -> BoneIds array
    (0x54, '<I', VALUE),
    (0x58, '<H', VALUE),      # BoneId count
    (0x5A, '<H', VALUE),      # BoneId capacity
    (0x5C, '<I', VALUE),
    # ⛔⛔ STRIDE 0x60, NOT 0x70 - AND ONLY THE OVERLAP LEDGER COULD EVER HAVE SAID SO.
    # This map first claimed 0x70. Every byte of the extra 16 still round-tripped, because the
    # writer re-encoded them from the same offsets it read them from: A CLAIM THAT CANNOT FAIL.
    # The ledger failed it - those 16 bytes are the NEXT allocation, and they collided with live
    # props/clips bucket arrays, BoneId arrays, sequence headers and the following crAnimation
    # (4,352 + 2,800 + 208 + 96 bytes on a 30-file draw). This is the vault's own law biting a
    # writer: *a claimed region is evidence only if a wrong claim could have been REJECTED.*
), 0x60, 'animation')

# crAnimSequence header. The data region begins at seq+0x20.
SEQHDR = _check_tiling((
    (0x00, '<I', VALUE),      # Hash
    (0x04, '<I', VALUE),
    (0x08, '<I', VALUE),
    (0x0C, '<I', VALUE),      # quantOffset, from data@seq+0x20
    (0x10, '<I', VALUE),      # total size (seq_end = seq + this)
    (0x14, '<H', VALUE),
    (0x16, '<H', VALUE),      # FrameCount
    (0x18, '<I', VALUE),
    (0x1C, '<I', VALUE),
), 0x20, 'seq_header')

# The trailing per-channel table after a sequence - see Ycd._emit_seq_trailer for how it was
# found and, more importantly, for what about it is NOT derived.
TRAILER_REC = _check_tiling((
    (0x00, '<B', VALUE),      # pool index, same nine-pool order as the count table
    (0x01, '<B', VALUE),      # component 0..3
    (0x02, '<H', VALUE),
    (0x04, '<H', VALUE),
), 0x06, 'seq_trailer_record')

BONEID = _check_tiling((
    (0x00, '<H', VALUE),      # BoneId
    (0x02, '<B', VALUE),      # Unk0
    (0x03, '<B', VALUE),      # Track
), 0x04, 'boneid')


def _rup(n):
    """Map lists are padded to a multiple of 4 entries."""
    return ((n + 3) // 4) * 4


P = lambda v: v & 0x0FFFFFFF


# ------------------------------------------------------------------ bit I/O
class BitReader:
    """LSB-first bit reader over a bytes-like, sliced rather than looped.

    ⚠ Deliberately NOT the per-bit loop `ycd2xml` uses. Same values, ~40x faster - and speed is a
    correctness issue here, because a slow lane is what pushes a measurement into sampling and
    this lane has to be reported at POPULATION (24,844 files)."""

    __slots__ = ('b', 'base', 'nbits')

    def __init__(self, buf, base, nbits):
        self.b = buf
        self.base = base
        self.nbits = nbits

    def fld(self, pos, n):
        if n <= 0:
            return 0
        byte = self.base + (pos >> 3)
        sh = pos & 7
        nb = (n + sh + 7) >> 3
        return (int.from_bytes(self.b[byte:byte + nb], 'little') >> sh) & ((1 << n) - 1)

    def unary(self, pos):
        """-> (zero_run, position_after_the_terminating_1) or (None, None) past the end."""
        z = 0
        while pos < self.nbits:
            byte = self.base + (pos >> 3)
            sh = pos & 7
            chunk = int.from_bytes(self.b[byte:byte + 8], 'little') >> sh
            if chunk == 0:
                step = 64 - sh
                z += step
                pos += step
                continue
            t = (chunk & -chunk).bit_length() - 1
            if pos + t >= self.nbits:
                return None, None
            return z + t, pos + t + 1
        return None, None


class BitWriter:
    """LSB-first bit writer. Accumulates into one integer per stream, emitted once."""

    __slots__ = ('acc', 'n')

    def __init__(self):
        self.acc = 0
        self.n = 0

    def put(self, val, nbits):
        if nbits <= 0:
            return
        self.acc |= (val & ((1 << nbits) - 1)) << self.n
        self.n += nbits

    def zeros(self, nbits):
        self.n += nbits

    def to_bytes(self, nbytes):
        return self.acc.to_bytes(max(nbytes, (self.n + 7) // 8), 'little')[:nbytes]


# ------------------------------------------------------------------ inline QuantizeFloat codec
def decode_inline_raw(S, desc, framecount):
    """The 64-frame block Rice codec of `ycd2xml._decode_inline_qz`, returning the RAW quantiser
    integers instead of floats, plus the descriptor split - because a WRITER has to re-encode
    them and floats cannot be re-encoded.

    ⚠ THIS IS A SECOND IMPLEMENTATION OF A RULE THAT ALREADY EXISTS, and that is a real risk: two
    copies drift. It is deliberate and it is CROSS-CHECKED - `--xcheck` re-derives the floats from
    these raws and compares them value-for-value against `ycd2xml._decode_inline_qz` on the same
    channels, and REFUSES on the first disagreement. A shared raw-returning entry point would be
    better; changing `ycd2xml`'s signature under a lane being measured today would not.

    -> (raws, (W, nb, k), None) on success, or (None, (W, nb, k), reason) on refusal.
    """
    A = struct.unpack_from('<I', S, desc)[0]
    B = struct.unpack_from('<I', S, desc + 4)[0]
    W = B & 0xFF
    nb = (B >> 8) & 0xFF
    k = (B >> 16) & 0xFF
    cell = (W, nb, k)
    if (B >> 24) != 0:
        return None, cell, 'hi_byte_set'
    if k > 13:
        return None, cell, 'selector_unwitnessed'
    base = desc + 16
    end = desc + A * 4
    if A < 4 or end > len(S):
        return None, cell, 'descriptor_out_of_range'
    nbits = (end - base) * 8
    if framecount < 1 or nbits <= 0:
        return None, cell, 'empty_payload'
    br = BitReader(S, base, nbits)
    N = (framecount + 63) // 64
    hdr = N * (W + nb)
    if hdr > nbits:
        return None, cell, 'header_overruns_payload'
    offs = [br.fld(i * W, W) for i in range(N)]
    seeds = [br.fld(N * W + i * nb, nb) for i in range(N)]
    if offs[0] != 0:
        return None, cell, 'first_block_offset_nonzero'
    for i in range(N - 1):
        if offs[i] >= offs[i + 1]:
            return None, cell, 'block_offsets_not_increasing'
    if hdr + offs[-1] > nbits:
        return None, cell, 'last_block_starts_past_payload'
    raw = []
    for j in range(N):
        nfr = min(64, framecount - j * 64)
        p = hdr + offs[j]
        V = seeds[j]
        Dv = 0
        raw.append(V)
        for _ in range(nfr - 1):
            if p + k > nbits:
                return None, cell, 'code_overruns_payload'
            rem = br.fld(p, k) if k else 0
            p += k
            z, p2 = br.unary(p)
            if z is None:
                return None, cell, 'unary_overruns_payload'
            p = p2
            m = (z << k) | rem
            if m:
                if p >= nbits:
                    return None, cell, 'sign_overruns_payload'
                c = -m if br.fld(p, 1) else m
                p += 1
            else:
                c = 0
            Dv += c
            V += Dv
            if V < 0:
                return None, cell, 'negative_quantiser_index'
            raw.append(V)
        if j + 1 < N:
            if p != hdr + offs[j + 1]:
                # STRUCTURAL GATE: a 64-frame block must land its cursor EXACTLY on the next
                # stored block offset. An arithmetic identity a wrong decode cannot satisfy.
                return None, cell, 'block_did_not_land'
        elif not (0 <= nbits - p <= 31):
            return None, cell, 'tail_not_word_padding'
    if len(raw) != framecount:
        return None, cell, 'frame_budget_did_not_close'
    return raw, cell, None


def encode_inline_payload(raws, framecount, W, nb, k, nwords):
    """Re-encode the inline-QZ payload from the decoded raws. THE BLOCK OFFSETS ARE RECOMPUTED.

    ⭐ This is what turns the decode from a plausible story into a claim byte identity can reject.
    A decoder that produced *almost* the right raws still writes different Rice codes, so the
    per-block bit offsets it recomputes differ from the ones the file stores, and the image moves.
    -> (payload bytes of length nwords*4, bits actually used) or (None, 0).

    ⚠ THE ENCODER PADS WITH ZEROS AND THE GAME DOES NOT ALWAYS. Measured on a 60-file draw:
    7,802 of 7,934 channels re-encode byte-identically outright, and ALL 132 that do not differ
    ONLY inside the final 4-byte word - the code stream is byte-identical on 7,934/7,934. So the
    codec is not in question; what is undecided is what the encoder left in the padding bits after
    the last code. The caller carries exactly those bits and COUNTS them (`inline_qz_pad_carried`)
    rather than inventing a rule for them.
    """
    N = (framecount + 63) // 64
    hdr = N * (W + nb)
    seeds, streams = [], []
    for j in range(N):
        nfr = min(64, framecount - j * 64)
        blk = raws[j * 64: j * 64 + nfr]
        seeds.append(blk[0])
        bw = BitWriter()
        V = blk[0]
        Dv = 0
        for i in range(1, nfr):
            newV = blk[i]
            newD = newV - V
            c = newD - Dv
            m = -c if c < 0 else c
            bw.put(m & ((1 << k) - 1) if k else 0, k)
            bw.zeros(m >> k)                       # the unary quotient's zero run
            bw.put(1, 1)                           # its terminating 1
            if m:
                bw.put(1 if c < 0 else 0, 1)
            Dv = newD
            V = newV
        streams.append(bw)
    offs = []
    at = 0
    for bw in streams:
        offs.append(at)
        at += bw.n
    lim_w = (1 << W) - 1
    lim_b = (1 << nb) - 1
    for o in offs:
        if o > lim_w:
            return None, 0
    for s in seeds:
        if s > lim_b:
            return None, 0
    out = BitWriter()
    for o in offs:
        out.put(o, W)
    for s in seeds:
        out.put(s, nb)
    for bw in streams:
        out.acc |= bw.acc << out.n
        out.n += bw.n
    if out.n > nwords * 4 * 8:
        return None, 0
    return out.to_bytes(nwords * 4), out.n


# ------------------------------------------------------------------ the model
class Ycd:
    def __init__(self, res, flags=(0, 0)):
        res.require_version(46, 'ycd')
        if len(res.gfx):
            # NO SILENT DEFAULTS: the lane is system-segment-only in 24,844/24,844. A file that
            # broke that would be silently half-measured if this were a warning.
            raise ValueError('ycd carries no graphics segment; got %d bytes' % len(res.gfx))
        self.res = res
        self.S = res.sys
        self.size = len(res.sys)
        self.sys_flags, self.gfx_flags = flags
        self.img = None
        self.mark = None
        self.overlap = 0
        self.done = set()        # (label, offset) already emitted - see _once()
        self._pending = []       # (anim, sequences) - trailers run last, see _emit_trailers
        self.notes = {}          # counted refusals / carries, by kind
        self.qz_cells = {}       # (selector, W) -> {'ok': n, 'bad': n, 'bad_bytes': n, ...}
        self.labels = {}         # label -> claimed byte count (for the residual report)
        self._build()

    # ---------------------------------------------------------- image primitives
    def _note(self, key, n=1):
        self.notes[key] = self.notes.get(key, 0) + n

    def _claim(self, off, n, kind, label):
        """Record a write. ⛔ A byte claimed twice is an OVER-LONG STRIDE, which byte identity
        cannot see - so it is counted here instead of being absorbed."""
        if off < 0 or off + n > self.size:
            self._note('write_out_of_range')
            return False
        m = self.mark
        seg = m[off:off + n]
        if seg.count(0) != n:
            self.overlap += n - seg.count(0)
            self._note('overlap_' + label)
        m[off:off + n] = bytes([kind]) * n
        self.labels[label] = self.labels.get(label, 0) + n
        return True

    def _once(self, label, off):
        """One OBJECT reached twice is still one object - emit it once.

        ⛔ AND IT IS NOT A CONVENIENCE, IT IS WHAT KEEPS THE OVERLAP LEDGER HONEST. A shared
        crAnimation (two dictionary keys, one object) re-emitted would collide with itself and
        raise `overlap`, which is the counter that exists to catch an OVER-LONG STRIDE. A ledger
        that fires on a legal aliasing cannot be trusted when it fires on a real one.
        Measured 2026-08-15: 350 of the 8,072 first-pass overlap bytes on a 40-file draw were this
        exact aliasing, not a stride defect.
        """
        k = (label, off)
        if k in self.done:
            return False
        self.done.add(k)
        return True

    def put(self, off, code, vals, kind, label):
        n = struct.calcsize(code)
        if not self._claim(off, n, kind, label):
            return
        struct.pack_into(code, self.img, off, *vals)

    def put_bytes(self, off, data, kind, label):
        if not self._claim(off, len(data), kind, label):
            return
        self.img[off:off + len(data)] = data

    def emit_struct(self, base, fields, label, overrides=None):
        """Re-encode one struct THROUGH ITS FIELD MAP - decode each field from the source, write it
        back typed. The map tiles its stride (checked at import), so nothing inside is carried."""
        S = self.S
        for off, code, kind in fields:
            o = base + off
            if o + struct.calcsize(code) > self.size:
                self._note('struct_past_segment_' + label)
                return
            if overrides is not None and off in overrides:
                v, kind = overrides[off]
                self.put(o, code, (v,) if not isinstance(v, tuple) else v, kind, label)
                continue
            self.put(o, code, struct.unpack_from(code, S, o), kind, label)

    # ---------------------------------------------------------- the walk
    def _atmap(self, bp, nb):
        """-> [(node_off, key, val_off)] in bucket-index then linked-list order (== XML order)."""
        S = self.S
        out = []
        for b in range(nb):
            node = struct.unpack_from('<I', S, bp + b * 8)[0]
            guard = 0
            while node & 0xF0000000:
                n = P(node)
                if n + 0x18 > self.size:
                    self._note('atmap_node_past_segment')
                    break
                out.append((n, struct.unpack_from('<I', S, n)[0],
                            P(struct.unpack_from('<I', S, n + 8)[0])))
                node = struct.unpack_from('<I', S, n + 0x10)[0]
                guard += 1
                if guard > 65535:
                    self._note('atmap_chain_runaway')
                    break
        return out

    def _build(self):
        S = self.S
        self.clips_bp = P(struct.unpack_from('<I', S, 0x28)[0])
        self.clips_nb = struct.unpack_from('<H', S, 0x30)[0]
        self.aobj = P(struct.unpack_from('<I', S, 0x18)[0])
        self.anims_bp = P(struct.unpack_from('<I', S, self.aobj + 0x18)[0])
        self.anims_nb = struct.unpack_from('<H', S, self.aobj + 0x20)[0]
        self.clips = self._atmap(self.clips_bp, self.clips_nb)
        self.anims = self._atmap(self.anims_bp, self.anims_nb)

    # ---------------------------------------------------------- the image
    def write(self):
        if self.img is not None:
            return bytes(self.img)
        S = self.S
        self.img = bytearray(self.size)
        self.mark = bytearray(self.size)
        self.emit_struct(0, ROOT, 'root')
        self.emit_struct(self.aobj, ANIMDICT, 'animdict')

        # ⭐ THE PAGE-COUNT RECORD - COMPUTED, never carried (meta 250/250, ynd 259/259,
        # yvr/ywr 9,145/9,145). ptr@0x08 reaches the block map; its u32 at +8 is
        #     pageCount(system) | pageCount(graphics) << 8
        buf, o = self.res.deref(struct.unpack_from('<I', S, 0x08)[0], 12)
        if buf is not None:
            val = ((meta_write.page_count(self.sys_flags) & 0xFF)
                   | ((meta_write.page_count(self.gfx_flags) & 0xFF) << 8))
            self.put(o, '<Q', (0,), DERIVED, 'blockmap')
            self.put(o + 8, '<I', (val,), DERIVED, 'blockmap_pagecount')
            # ⭐ DIAGNOSIS ONLY - THE COMPUTED VALUE IS STILL WHAT GETS WRITTEN. Naming this
            # disagreement turns the lane's entire residual from an anonymous byte into a counted
            # class. Measured at POPULATION 2026-08-15: the computed value equals the stored one
            # on 24,836 of 24,840 v46 .ycd; FOUR files store exactly ONE MORE system page than
            # their own flag word describes, and those 4 bytes are the lane's whole residual.
            # ⛔ NOT "impossible" - here is the space SEARCHED and the space NOT searched.
            #   searched: extra inflated payload past the declared segment (0 B on 4/4);
            #             base-shift correlation (220 files share base shift 2, 3 of them fail);
            #             flag bits 28-31 (uniform (0x2, 0xE) across all 24,837 v46 files);
            #             field saturation (72<127, 32<63, 6<15 - no count is near its mask);
            #             graphics contribution (gfx flags 0xE0000000 -> 0 pages on all).
            #   NOT searched: whether the SAME +1 appears in other lanes (a cheap next test - if
            #             .ydr/.yft/.ybn show it, it is an allocator rule, not a .ycd quirk), and
            #             whether these four were repacked by a different build's RSC7 writer.
            if o + 12 <= self.size and (struct.unpack_from('<I', S, o + 8)[0] & 0xFFFF) != val:
                self._note('pagecount_stored_differs_from_computed')

        self._emit_dict(self.clips_bp, self.clips_nb, self.clips, 'clips')
        self._emit_dict(self.anims_bp, self.anims_nb, self.anims, 'anims')
        for _n, _k, cv in self.clips:
            self._emit_clip(cv)
        for _n, _k, av in self.anims:
            self._emit_anim(av)
        self._emit_trailers()
        return bytes(self.img)

    def _emit_dict(self, bp, nb, entries, label):
        """⭐ THE BUCKET ARRAY AND THE CHAIN ARE COMPUTED FROM THE KEYS, not copied.
        bucket = key %% nbuckets (14,022/14,022 on the derivation draw). A wrong key, a wrong
        bucket count or a wrong walk order puts a chain in the wrong bucket and the image moves."""
        if not nb:
            return
        heads = {}
        chain = {}
        prev = {}
        for node, key, _val in entries:
            b = key % nb
            if b not in heads:
                heads[b] = node
            else:
                chain[prev[b]] = node
            prev[b] = node
        for b in range(nb):
            self.put(bp + b * 8, '<Q', (0x50000000 | heads[b] if b in heads else 0,),
                     DERIVED, label + '_buckets')
        for node, _key, val in entries:
            nxt = chain.get(node, 0)
            self.emit_struct(node, NODE, label + '_node', overrides={
                0x08: (0x50000000 | val, POINTER),
                0x10: (0x50000000 | nxt if nxt else 0, DERIVED),
            })

    # ---------------------------------------------------------- clips
    def _emit_clip(self, cv):
        S = self.S
        if not self._once('clip', cv):
            return
        self.emit_struct(cv, CLIP, 'clip')
        # name string "pack:/<stem>.clip" - the atArray count at +0x20 is strlen, +0x22 strlen+1
        np_ = P(struct.unpack_from('<I', S, cv + 0x18)[0])
        cnt = struct.unpack_from('<H', S, cv + 0x20)[0]
        if np_ and np_ + cnt + 1 <= self.size:
            self.put_bytes(np_, bytes(S[np_:np_ + cnt]) + b'\x00', VALUE, 'clip_name')
        typ = struct.unpack_from('<I', S, cv + 0x10)[0]
        if typ == 2:
            arr = P(struct.unpack_from('<I', S, cv + 0x50)[0])
            n = struct.unpack_from('<H', S, cv + 0x58)[0]
            for i in range(n):
                self.emit_struct(arr + i * 0x18, CLIPREF, 'clip_ref')
        self._emit_container(cv + 0x38, 'tags', True)
        self._emit_props(cv + 0x40)

    def _emit_container(self, at, label, is_tags):
        """crTags: clip+0x38 -> container {atArray<crTag*> ptr@+0, u16 count@+8}."""
        S = self.S
        cont = P(struct.unpack_from('<I', S, at)[0])
        if not cont or cont + 0x10 > self.size:
            return
        if not self._once(label + '_cont', cont):
            return
        self.emit_struct(cont, TAGSCONT if is_tags else CONT, label + '_cont')
        ap = P(struct.unpack_from('<I', S, cont)[0])
        n = struct.unpack_from('<H', S, cont + 8)[0]
        if not ap:
            return
        for i in range(n):
            if ap + i * 8 + 8 > self.size:
                self._note('tag_ptr_past_segment')
                return
            self.put(ap + i * 8, '<Q', (struct.unpack_from('<Q', S, ap + i * 8)[0],),
                     POINTER, label + '_ptrarray')
            tv = P(struct.unpack_from('<I', S, ap + i * 8)[0])
            if not self._once('tag', tv):
                continue
            self.emit_struct(tv, PROP, 'tag')
            if is_tags:
                self.emit_struct(tv + 0x40, TAG_EXTRA, 'tag_extra')
            self._emit_attrs(tv)

    def _emit_props(self, at):
        """crProperties = atMap<crProperty> {bucketptr, u16 nbuckets@+8, u16 nentries@+0x0A}."""
        S = self.S
        ms = P(struct.unpack_from('<I', S, at)[0])
        if not ms or ms + 0x10 > self.size:
            return
        if not self._once('props_cont', ms):
            return
        self.emit_struct(ms, CONT, 'props_cont')
        bp = P(struct.unpack_from('<I', S, ms)[0])
        nb = struct.unpack_from('<H', S, ms + 8)[0]
        ne = struct.unpack_from('<H', S, ms + 0x0A)[0]
        # ⛔ AN EMPTY atMap STILL DECLARES A BUCKET COUNT, AND WALKING IT CLAIMS BYTES THAT ARE
        # NOT ITS OWN. `ycd2xml.emit_properties` returns `<Properties />` on ne == 0 and never
        # touches the bucket pointer; this writer did walk it, and the stale `bp` landed on top of
        # live crAnimation objects - 552 of the 8,072 first-pass overlap bytes on a 40-file draw.
        # The overlap ledger is what surfaced it: byte identity could not, because the bytes it
        # wrote were read from the same offsets it wrote them to.
        if not nb or not ne or not bp:
            return
        entries = self._atmap(bp, nb)
        self._emit_dict(bp, nb, entries, 'props')
        for _n, _k, pv in entries:
            if not self._once('property', pv):
                continue
            self.emit_struct(pv, PROP, 'property')
            self._emit_attrs(pv)

    def _emit_attrs(self, pv):
        S = self.S
        ap = P(struct.unpack_from('<I', S, pv + 0x20)[0])
        ac = struct.unpack_from('<H', S, pv + 0x28)[0]
        if not ap:
            return
        for i in range(ac):
            if ap + i * 8 + 8 > self.size:
                self._note('attr_ptr_past_segment')
                return
            self.put(ap + i * 8, '<Q', (struct.unpack_from('<Q', S, ap + i * 8)[0],),
                     POINTER, 'attr_ptrarray')
            a = P(struct.unpack_from('<I', S, ap + i * 8)[0])
            if not self._once('attribute', a):
                continue
            self.emit_struct(a, ATTR, 'attribute')
            # Type 4 = String: atArray<char> at +0x20 (u64 ptr, u16 Count=strlen, u16 Size=+1).
            if struct.unpack_from('<I', S, a + 8)[0] == 4:
                # ⛔ THE LENGTH IS AT +0x28, NOT +0x24. atArray<char> at +0x20 is {u64 ptr,
                # u16 Count = strlen, u16 Size = Count+1}, so the count sits 8 bytes past the
                # pointer. Reading +0x24 returned 0 on 6/6 type-4 attributes and claimed ONE byte
                # of a 539-byte string, which is why `trv_4_mcs_2-0.ycd` left 3,234 unclaimed
                # bytes - the single largest residual on the 400-file board.
                # ⭐ AND THE LENGTH IS CHECKED, not trusted: the byte at ptr+Count must be NUL.
                # That is `ycd2xml`'s own control for this field, and a wrong Count fails it.
                sp = P(struct.unpack_from('<I', S, a + 0x20)[0])
                sc = struct.unpack_from('<H', S, a + 0x28)[0]
                if sp and sp + sc + 1 <= self.size:
                    if S[sp + sc] != 0:
                        self._note('attr_string_count_not_nul_terminated')
                        continue
                    self.put_bytes(sp, bytes(S[sp:sp + sc]) + b'\x00', VALUE, 'attr_string')

    # ---------------------------------------------------------- animations
    def _emit_anim(self, av):
        S = self.S
        if not self._once('animation', av):
            return
        self.emit_struct(av, ANIM, 'animation')
        bp = P(struct.unpack_from('<I', S, av + 0x50)[0])
        bc = struct.unpack_from('<H', S, av + 0x58)[0]
        if bp:
            for i in range(bc):
                self.emit_struct(bp + i * 4, BONEID, 'boneid')
        sp = P(struct.unpack_from('<I', S, av + 0x40)[0])
        sc = struct.unpack_from('<H', S, av + 0x48)[0]
        if not sp:
            return
        seqs = []
        for i in range(sc):
            if sp + i * 8 + 8 > self.size:
                self._note('seq_ptr_past_segment')
                return
            self.put(sp + i * 8, '<Q', (struct.unpack_from('<Q', S, sp + i * 8)[0],),
                     POINTER, 'seq_ptrarray')
            seqs.append(P(struct.unpack_from('<I', S, sp + i * 8)[0]))
        for s in seqs:
            self._emit_sequence(s, bc)
        # ⛔ DEFERRED ON PURPOSE - see _emit_trailers. A trailer is bounded by the NEXT allocation,
        # and "the next allocation" is not knowable until every object in the file is claimed.
        self._pending.append((av, seqs))

    def _emit_seq_trailer(self, av, seqs):
        """THE TRAILING CHANNEL TABLE - the one region of a .ycd that `ycd2xml` never reads.

        Found 2026-08-15 by this writer, exactly the way a writer is supposed to find things: it
        is the only unclaimed NON-ZERO run left in the segment, it sits immediately after a
        sequence's declared end (`seq + seq[+0x10]`), and NOTHING POINTS AT IT - a scan of every
        aligned u32 in the segment found 0 tagged pointers into it, so it is reached by
        ARITHMETIC.

        ⭐ THE EXTENT RULE, and it is ONE rule for every animation:
                trailer = anim[+0x38] - MAX(seq[+0x10])          [per sequence]
        `+0x38` is the animation's CHUNK ALLOCATION SIZE - the largest sequence plus its trailer -
        not the sum of its sequences. Every sequence in the animation then carries a trailer of
        that same size. Multiple of 6 on 250/250 multi-sequence animations and 1,712/1,712
        single-sequence ones.

        ⛔ SUPERSEDED, KEPT SO IT IS NOT RE-DERIVED: the first rule read
        `trailer = anim[+0x38] - SUM(seq[+0x10])`. It is the SAME ARITHMETIC whenever an animation
        has exactly one sequence, which is 1,712 of 1,962 - so it passed its board and then went
        NEGATIVE on 635 multi-sequence animations, because a sum over several sequences overshoots
        an allocation size that only ever covered the biggest one. A second, more elaborate
        hypothesis (propose per-sequence lengths by walking record-shaped bytes, then check the
        proposed lengths sum to the total) was built and is also superseded: it inherited the same
        wrong total, so its check could never pass. Both were sized off single-sequence data.

        RECORD SHAPE (derived from the bytes, 6 B, tiled and checked at import):
            u8 pool index (0..8, the SAME nine-pool order as the count table:
               quat/vec3/float/raw/quant/indirect/inline/cached1/cached2)
            u8 component (0..3)
            u16, u16
        Within a run the first u16 advances by the channel's bit width and the second by a
        larger step - consistent with a per-channel (bit offset, byte offset) acceleration table.

        ⛔ WHAT IS **NOT** DERIVED, STATED PLAINLY: what selects WHICH channels appear here.
        Four hypotheses were tested against 1,712 single-sequence animations and ALL FOUR were
        refuted - it is not item 0's channel list (0/1,712), not the count of non-empty pools
        (matched 2 of 8 spot checks), not `anim+0x3C`, and not a function of nBones. So the
        record COUNT is taken from `anim+0x38` rather than computed, and this region is reported
        as `derived_extent`, never as an independent pin.

        RECORD SHAPE is TRAILER_REC (6 B, tiled and checked at import).

        ⚠ T IS AN UPPER BOUND PER SEQUENCE, NOT AN EXACT LENGTH, and only the overlap ledger said
        so. Writing T bytes after EVERY sequence scored 381/399 byte-exact and looked finished -
        while claiming 5,416 bytes that belonged to the next allocation (plus 883 sequence headers
        and 404 BoneId arrays). The allocation size is set by the LARGEST sequence; a smaller one
        is followed by the next object sooner. So a trailer is written only into bytes no other
        structure claims, and a trailer cut short by its neighbour is COUNTED
        (`seq_trailer_bounded_by_next_allocation`) rather than forced.
        """
        S = self.S
        if not seqs:
            return
        totals = []
        for s in seqs:
            if s + 0x14 > self.size:
                return
            totals.append(struct.unpack_from('<I', S, s + 0x10)[0])
        a38 = struct.unpack_from('<I', S, av + 0x38)[0]
        for s, total in zip(seqs, totals):
            # ⭐ THE BOUND IS PER SEQUENCE: `+0x38` is the chunk allocation size, so a sequence of
            # `total` bytes can be followed by at most `a38 - total` bytes of table. Using
            # `a38 - MAX(total)` instead - one uniform size for the whole animation - is a LOWER
            # bound, and it left 321 non-zero bytes unclaimed across a 600-file board because the
            # shorter sequences of an animation carry the LONGER tables.
            extra = a38 - total
            if extra <= 0:
                if extra < 0:
                    self._note('seq_trailer_total_negative')
                continue
            at = s + total
            # ⛔⛔ NO VERBATIM CARRY OF THIS RANGE. A first version carried `extra` bytes whenever
            # `extra % 6`, which for a SHORT sequence in a big animation is thousands of bytes -
            # it claimed 4,650,371 bytes that other structures already owned and pushed `carried`
            # from 0.30% to 4.91% while the byte-exact score went UP to 98%. That is precisely the
            # failure this vault names: a large carried region turns a measurement into a copy,
            # and only the overlap ledger could see it, because every one of those bytes matched.
            n = 0
            # Two terminators, and BOTH are needed. The claim map stops the table at the next
            # live allocation; the all-zero record stops it at the arena padding, which would
            # otherwise be claimed as "modelled" for free and flatter the byte account.
            while (n * 6 < extra and at + n * 6 + 6 <= self.size
                   and self.mark[at + n * 6: at + n * 6 + 6].count(0) == 6
                   and any(S[at + n * 6: at + n * 6 + 6])):
                n += 1
            if n * 6 != extra:
                self._note('seq_trailer_bounded_by_next_allocation')
            for i in range(n):
                self.emit_struct(at + i * 6, TRAILER_REC, 'seq_trailer')

    def _emit_trailers(self):
        """Run every deferred trailer AFTER the whole file is claimed - see _emit_seq_trailer."""
        for av, seqs in self._pending:
            self._emit_seq_trailer(av, seqs)

    def _emit_sequence(self, seq, nbones):
        S = self.S
        if seq + 0x20 > self.size:
            self._note('seq_past_segment')
            return
        if not self._once('seq_header', seq):
            return
        self.emit_struct(seq, SEQHDR, 'seq_header')
        data = seq + 0x20
        quant_off = struct.unpack_from('<I', S, seq + 0x0C)[0]
        packed = data + quant_off
        seq_end = seq + struct.unpack_from('<I', S, seq + 0x10)[0]
        framecount = struct.unpack_from('<H', S, seq + 0x16)[0]
        cands = self._locate_counts(seq, nbones)
        if len(cands) != 1:
            # ⛔ COUNT-TABLE REFUSAL. The data region is CARRIED VERBATIM and COUNTED - a
            # sequence we cannot parse must not fail the whole file, and must not look modelled.
            self._note('count_table_not_located_%s'
                       % ('none' if not cands else 'ambiguous_%d' % len(cands)))
            if data < seq_end <= self.size:
                self.put_bytes(data, bytes(S[data:seq_end]), CARRIED, 'seq_data_carried')
            return
        co, counts, qz_d, ind_d, inl_d, framebits = cands[0]
        nq, nv, nf, nr, nqz, ni, n6, nc1, nc2 = counts

        # --- static pools: re-encoded from their stored words
        base = data
        for pool, stride, lbl in ((nq, 12, 'static_quat'), (nv, 12, 'static_vec3'),
                                  (nf, 4, 'static_float')):
            for i in range(pool):
                o = base + i * stride
                self.put(o, '<%dI' % (stride // 4),
                         struct.unpack_from('<%dI' % (stride // 4), S, o), VALUE, lbl)
            base += pool * stride

        # --- QuantizeFloat descriptors: numBits, Quantum, Offset
        for d in qz_d:
            self.put(d, '<3I', struct.unpack_from('<3I', S, d), VALUE, 'qz_descriptor')
        # --- IndirectQuantizeFloat descriptors: header + inline palette words
        for d in ind_d:
            self.put(d, '<5I', struct.unpack_from('<5I', S, d), VALUE, 'iq_descriptor')
            npw = struct.unpack_from('<I', S, d + 8)[0]
            for w in range(npw):
                self.put(d + 0x14 + w * 4, '<I',
                         struct.unpack_from('<I', S, d + 0x14 + w * 4), VALUE, 'iq_palette')

        # --- INLINE QuantizeFloat: header modelled, payload RE-ENCODED from decoded raws
        for d in inl_d:
            self._emit_inline_qz(d, framecount)

        # --- the frame-major packed block, RE-PACKED bit by bit from decoded integers
        self._emit_packed(packed, co, qz_d, ind_d, nr, framebits, framecount)

        # --- the nine counts, then the nine map lists with COMPUTED pad sentinels
        self.put(co, '<9H', counts, VALUE, 'count_table')
        m = co + 18
        sentinel = nbones * 4
        for cnt in counts:
            for i in range(cnt):
                self.put(m + i * 2, '<H', struct.unpack_from('<H', S, m + i * 2), VALUE, 'map_list')
            for i in range(cnt, _rup(cnt)):
                self.put(m + i * 2, '<H', (sentinel,), DERIVED, 'map_pad')
            m += _rup(cnt) * 2

    def _emit_inline_qz(self, d, framecount):
        S = self.S
        A = struct.unpack_from('<I', S, d)[0]
        self.put(d, '<4I', struct.unpack_from('<4I', S, d), VALUE, 'inline_qz_header')
        raws, cell, why = decode_inline_raw(S, d, framecount)
        c = self.qz_cells.setdefault(cell, {'ok': 0, 'bad': 0, 'bad_bytes': 0, 'why': {}})
        payload_bytes = (A - 4) * 4
        if raws is None:
            # ⛔ UNDECODED. Payload CARRIED VERBATIM and COUNTED - never invented, never silent.
            c['bad'] += 1
            c['bad_bytes'] += payload_bytes
            c['why'][why] = c['why'].get(why, 0) + 1
            self._note('inline_qz_undecoded')
            if d + 16 + payload_bytes <= self.size:
                self.put_bytes(d + 16, bytes(S[d + 16:d + 16 + payload_bytes]),
                               CARRIED, 'inline_qz_payload_carried')
            return
        W, nb, k = cell
        enc, used = encode_inline_payload(raws, framecount, W, nb, k, A - 4)
        if enc is None:
            c['bad'] += 1
            c['bad_bytes'] += payload_bytes
            c['why']['reencode_did_not_fit'] = c['why'].get('reencode_did_not_fit', 0) + 1
            self._note('inline_qz_reencode_failed')
            if d + 16 + payload_bytes <= self.size:
                self.put_bytes(d + 16, bytes(S[d + 16:d + 16 + payload_bytes]),
                               CARRIED, 'inline_qz_payload_carried')
            return
        c['ok'] += 1
        if d + 16 + payload_bytes > self.size:
            self._note('inline_qz_payload_past_segment')
            return
        # ⭐ THE RE-ENCODED CODE STREAM IS VALUE. THE PADDING AFTER THE LAST CODE IS CARRIED, AND
        # THE SPLIT IS AT A BYTE BOUNDARY IN THE **CONSERVATIVE** DIRECTION: the byte that holds
        # the last code bit is counted as CARRIED too, so `value` can never be flattered by a
        # partial byte. `used // 8` full bytes are re-encoded; the rest is the file's own.
        full = used // 8
        if full:
            self.put_bytes(d + 16, enc[:full], VALUE, 'inline_qz_payload')
        rest = payload_bytes - full
        if rest > 0:
            tail = bytearray(S[d + 16 + full:d + 16 + payload_bytes])
            # keep the encoder's bits inside the boundary byte; the padding bits are the file's
            keep = used - full * 8
            if keep:
                mask = (1 << keep) - 1
                tail[0] = (enc[full] & mask) | (tail[0] & ~mask & 0xFF)
            self.put_bytes(d + 16 + full, bytes(tail), CARRIED, 'inline_qz_pad_carried')
            c['pad_bytes'] = c.get('pad_bytes', 0) + rest

    def _emit_packed(self, packed, co, qz_d, ind_d, nr, framebits, framecount):
        """RE-PACK the frame-major block from decoded integers.

        ⭐ THE STRONGEST PIN IN THE FILE. Channel order, per-channel bit width, the DWORD-aligned
        frame stride and the RawFloat-at-the-front geometry are all re-derived here; an off-by-one
        in any one of them scrambles every frame after the first, so byte identity can reject it.
        """
        S = self.S
        stride = framebits // 8 + nr * 4
        if stride <= 0:
            return
        widths = [struct.unpack_from('<I', S, d)[0] for d in qz_d]
        widths += [struct.unpack_from('<I', S, d)[0] for d in ind_d]
        for fr in range(framecount):
            fo = packed + fr * stride
            if fo + stride > self.size:
                self._note('packed_block_past_segment')
                return
            # RawFloat sits at the FRONT of every frame (raw-first: whole-file byte-identical on
            # the complete game-wide mixed population; raw-last and raw-after-roundup32 differ).
            for c in range(nr):
                self.put(fo + c * 4, '<I', struct.unpack_from('<I', S, fo + c * 4),
                         VALUE, 'rawfloat')
            br = BitReader(S, fo, stride * 8)
            bw = BitWriter()
            bit = nr * 32
            bw.zeros(bit)
            for w in widths:
                bw.put(br.fld(bit, w), w)
                bit += w
            body = bw.to_bytes(stride)
            self.put_bytes(fo + nr * 4, body[nr * 4:], VALUE, 'packed_frame')

    def _locate_counts(self, seq, nbones):
        """Every surviving count-table candidate under the four constraints proven in
        `ycd2xml._locate_counts` (size equation, descriptor walk, packed-block extent, map-list
        range+sentinel). The caller requires exactly ONE survivor - an ambiguous sequence refuses
        rather than silently taking the first fit."""
        S = self.S
        data = seq + 0x20
        quant_off = struct.unpack_from('<I', S, seq + 0x0C)[0]
        packed = data + quant_off
        seq_end = seq + struct.unpack_from('<I', S, seq + 0x10)[0]
        framecount = struct.unpack_from('<H', S, seq + 0x16)[0]
        cands = []
        if seq_end > self.size or packed > self.size:
            return cands
        for c in range(packed, seq_end - 18, 2):
            cc = struct.unpack_from('<9H', S, c)
            if nbones and max(cc) > nbones * 4:
                continue
            if c + (9 + sum(_rup(x) for x in cc)) * 2 != seq_end:
                continue
            nq, nv, nf, nr, nqz, ni, n6, nc1, nc2 = cc
            o = data + nq * 12 + nv * 12 + nf * 4
            qz_dd = [o + kk * 12 for kk in range(nqz)]
            o += nqz * 12
            ind_dd = []
            bad = False
            for _ in range(ni):
                if o + 0x14 > len(S):
                    bad = True
                    break
                ind_dd.append(o)
                o += 0x14 + struct.unpack_from('<I', S, o + 8)[0] * 4
            if bad:
                continue
            inl_dd = []
            for _ in range(n6):
                if o + 16 > len(S):
                    bad = True
                    break
                sw = struct.unpack_from('<I', S, o)[0]
                if sw < 4 or o + sw * 4 > len(S):
                    bad = True
                    break
                inl_dd.append(o)
                o += sw * 4
            if bad or o - data != quant_off:
                continue
            fb = sum(struct.unpack_from('<I', S, d)[0] for d in qz_dd) \
                + sum(struct.unpack_from('<I', S, d)[0] for d in ind_dd)
            framebits = ((fb + 31) // 32) * 32
            if packed + (framebits // 8 + nr * 4) * framecount != c:
                continue
            if nbones:
                m = c + 18
                ok = True
                for cnt in cc:
                    if m + _rup(cnt) * 2 > len(S):
                        ok = False
                        break
                    if any(struct.unpack_from('<H', S, m + i * 2)[0] >= nbones * 4
                           for i in range(cnt)):
                        ok = False
                        break
                    if any(struct.unpack_from('<H', S, m + i * 2)[0] != nbones * 4
                           for i in range(cnt, _rup(cnt))):
                        ok = False
                        break
                    m += _rup(cnt) * 2
                if not ok:
                    continue
            cands.append((c, cc, qz_dd, ind_dd, inl_dd, framebits))
        return cands

    # ---------------------------------------------------------- the measure
    def unreached(self):
        """(count, non_zero_count) of bytes the model never reproduced.

        A ZERO gap is padding we did not have to understand. A NON-ZERO gap is data we are
        dropping - which is exactly what this exercise exists to surface.
        """
        got, orig = self.write(), self.S
        if got == orig:                     # the common case at population - do not scan 400 KB
            return 0, 0
        n = min(len(got), len(orig))
        bad = [i for i in range(n) if got[i] != orig[i]]
        return len(bad), sum(1 for i in bad if orig[i] != 0)

    def regions(self):
        """Byte account of the image: {'value','derived','pointer','carried','zero_fill', ...}.

        ⭐ DISCLOSURE, NOT DECORATION. Byte identity alone cannot tell a rebuilt region from a
        copied one. `carried` is the part of a passing file that COULD NOT HAVE FAILED; quote it
        next to the coverage figure, never instead of it. `pointer` is re-encoded from offsets the
        model walked to - self-consistent, not independent - and is reported apart from `value` so
        it can never be counted as one.
        ⭐ `nonzero_orig` is the honest denominator: 25.65%% of a .ycd system segment is zero in
        the ORIGINAL (page padding), and reproducing a zero by not writing it proves nothing.
        """
        self.write()
        cnt = {KIND_NAME[k]: self.mark.count(k) for k in KIND_NAME}
        claimed = sum(cnt.values())
        cnt['zero_fill'] = self.size - claimed
        cnt['size'] = self.size
        cnt['overlap'] = self.overlap
        cnt['nonzero_orig'] = self.size - self.S.count(0)
        # How many ORIGINAL non-zero bytes sit in the unclaimed remainder - THE TRUE GAP.
        # Done with translate + one big-int AND rather than a per-byte loop: at population this
        # runs over 3.1 GB of segment and a Python loop made the measurement, not the model, the
        # cost of the lane.
        unclaimed = self.mark.translate(_TBL_IS_ZERO)      # 1 where nothing claimed the byte
        nonzero = self.S.translate(_TBL_NONZERO)           # 1 where the ORIGINAL byte is non-zero
        both = (int.from_bytes(unclaimed, 'little') & int.from_bytes(nonzero, 'little'))
        cnt['unclaimed_nonzero'] = bin(both).count('1')
        return cnt

    def qz_census(self):
        """The SECOND number, and it is NOT the coverage figure: per (W, numBits, selector) cell,
        how many inline-QuantizeFloat channels decode and how many do not, with the bytes the
        undecoded ones carry. This is the unit of work Matt named - the variant, not the lane."""
        return self.qz_cells


def read_ycd(src):
    """The RSC7 segment FLAGS are needed to recompute the page-count record, and Res does not keep
    them - so they are parsed from the container header here and handed to the model."""
    blob = bytes(src) if isinstance(src, (bytes, bytearray)) else open(src, 'rb').read()
    _magic, _ver, sysf, gfxf = struct.unpack_from('<4sIII', blob, 0)
    return Ycd(Res.from_bytes(blob), (sysf, gfxf))
