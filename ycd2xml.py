r"""ycd2xml - GTA V .ycd (rage::crClipDictionary, RSC7 v46) -> RAGE .ycd.xml.

CLEAN-ROOM: derived from oracle XML + game binary + our own quarry code only.

⭐⭐ STATUS SUPERSEDED 2026-08-15 - MEASURED AT POPULATION BY A WRITER, NOT AGAINST ORACLES.
  `quarry/ycd_write.py` round-trips this lane's own reader results across ALL 24,844 .ycd:
  24,836 / 24,840 v46 files BYTE-EXACT (99.9839%), mean coverage 100.0000%, and the entire
  residual is FOUR page-count bytes in four files.
  ⛔ THE "OPEN" PARAGRAPH BELOW IS THE PART THAT IS WRONG, AND IT WAS ALREADY WRONG WHEN WRITTEN
  AGAINST THIS FILE'S OWN CODE - `INLINE_QZ_PROVEN` and `_decode_inline_qz` (the 64-frame block
  Rice codec, selectors 0..13) had already replaced the "proven only for selector 0" rule the
  header still describes. Measured over the POPULATION rather than 57 oracles:
      4,732,238 inline-QuantizeFloat channels, 100.0000% decoded - ZERO undecoded -
      across 953 distinct (W, numBits, selector) cells / 96 distinct (selector, W) cells.
  And decoded is now the weaker claim: the writer RE-ENCODES each payload's Rice stream and
  recomputes its per-block bit offsets, and the code stream reproduces the file's own bytes.
  So "the whole remaining gap is INLINE QuantizeFloat" and "game-wide that pool is 3.7M channels"
  are both retired. ⚠ A DOCSTRING IS NOT A MEASUREMENT: this header sat two derivations behind
  the code under it for five days. Re-measure or do not assert.

⛔ SUPERSEDED, KEPT VERBATIM BELOW THIS LINE:
STATUS (2026-08-10, measured against ALL 57 oracles): 25/57 byte-identical, 0 MISSING.
  `was:` "measured against all 10 oracles: 10/10 FULLY byte-identical" - a TRUE statement about
  a 10-oracle board that read as a completeness claim once 47 more oracles existed. The same
  trap the ynv lane hit (a 2-oracle base hid an entire Portals/Points surface). Re-measure or
  do not assert.
  CLOSED and byte-exact: container, both dictionaries, both clip types, Properties/Tags/
  Attributes (incl. Bool and HashString), animation headers, BoneIds, sequence framing, the
  nine-pool count table and per-item map, StaticVector3/StaticFloat, StaticQuaternion
  (3f + f32-reconstructed w), CachedQuaternion1/2, RawFloat (frame-major, unmixed),
  QuantizeFloat and IndirectQuantizeFloat (compact AND inline-palette).
  OPEN - the whole remaining gap, and the ONLY cause of the 32 non-passing positions:
  INLINE QuantizeFloat. Its variant space over the 57 oracles is 68 distinct (selector, W)
  cells across 4,163 channels; the double-integration + single-REST rule below is proven ONLY
  for selector 0 with W in {7,8,9}, and even there it decoded 20 channels exactly while getting
  5 WRONG. Game-wide that pool is 3.7M channels. Undecoded channels emit a counted, visible
  RESIDUAL - never an invented number.

CONTAINER (RSC7 v46, all data in system segment):
  sys+0x00 u64 vtable
  sys+0x18 -> Animations map object ; obj+0x18 bucketptr, obj+0x20 (u16 nbuckets,u16 nentries)
  sys+0x28 -> Clips buckets (INLINE atMap) ; sys+0x30 (u16 nbuckets,u16 nentries)
  atMap: bucket array stride 8 (tagged ptr) ; entry node = {u32 key, u32 pad, u64 val, u64 next}
  XML order == bucket-index then linked-list order.  Clips keyed by joaat(name-stem),
  Animations keyed by their hash.

CLIP (crClipAnimation / crClipAnimationList):
  +0x10 u32 Type (1=Animation, 2=AnimationList)   +0x18 -> Name "pack:/<stem>.clip"
  +0x30 u32 Unknown30      +0x38 -> crTags {atArray ptr@+0, u16 count@+8} of crTag*
  +0x40 -> crProperties {atMap bucketptr@+0, count@+8}
  Animation:      +0x50 -> crAnimation ; +0x58 StartTime f32 ; +0x5C EndTime ; +0x60 Rate
  AnimationList:  +0x50 -> ref[] (inline, stride 0x18: Start@0,End@4,Rate@8,animptr@0x10) ;
                  +0x58 u16 count ; +0x60 Duration f32
  <Hash> = the CLIPS-dictionary KEY through the name table (NOT joaat(name-stem): they differ,
  e.g. cs2_05.ycd stores key 0xF5B0F874 while joaat of its stem is 0x8DA8CB7E and the oracle
  spells the key) ; <Name> = the full "pack:/<stem>.clip" ;
  <AnimationHash> = key of the referenced crAnimation.
crProperty / crTag:  +0x18 NameHash ; +0x20 Attributes atArray(ptr,count@+0x28) ; +0x38 UnkHash
  crTag also: +0x40 StartPhase f32 ; +0x44 EndPhase f32
crPropertyAttribute: +0x08 Type (1=Float,2=Int,3=Bool,6=Vector3,8=Vector4,12=HashString) ;
  +0x18 NameHash ; +0x20 Value.  HashString is the ONE kind spelled as ELEMENT TEXT
  (<Value>name</Value>), every other kind is attribute-form value=.
  Int=i32@+0x20 ; Float=f32@+0x20 ; Vector3=xyz@+0x20 + Unknown2C f32@+0x2C ; Vector4=xyzw@+0x20

ANIMATION (crAnimation):
  +0x10 u8 Unknown10 (+0x11 = 0x01 flag) ; +0x14 u16 FrameCount ; +0x16 u16 SequenceFrameLimit
  +0x18 Duration f32 ; +0x1C u32 Unknown1C hash
  +0x40 -> Sequences ptr[] , count u16 @+0x48
  +0x50 -> BoneIds  , count u16 @+0x58 ; record 4B = {u16 BoneId, u8 Unk0, u8 Track}

SEQUENCE (crAnimSequence) @ seq :
  +0x00 u32 Hash ; +0x04 u32 total-size ; +0x0C u32 quantOffset (from data@seq+0x20) ;
  +0x16 u16 FrameCount.  Data region begins at seq+0x20 in fixed pool order:
    StaticQuaternion pool (3 f32 each; w reconstructed in STRICT float32:
        w = f32(sqrt(f32(1 - f32(f32(f32(x*x)+f32(y*y))+f32(z*z)))))  [VERIFIED 9/9])
    StaticVector3 pool (3 f32) [VERIFIED 11/11] ; StaticFloat pool (1 f32) [VERIFIED 3/3]
    QuantizeFloat descriptors (12B each: u32 numBits, f32 Quantum, f32 Offset)
    QuantizeFloat packed frames @ seq+0x20+quantOffset :
        frame-major, each frame DWORD-aligned (framebits = roundup(sum(numBits),32)),
        LSB-first bitstream, channels in descriptor order ;
        value = float32(Offset + raw*Quantum).                          [VERIFIED 9/9]
    FLOAT LAW (2026-08-10, 7,413/7,413 channels exact): the RAW INTEGER is rounded to float32
    BEFORE the multiply - value = f32(f32(Offset) + f32(f32(raw) * Quantum)), i.e. the C++
    (float)(Offset + (float)((float)raw * Quantum)).  `was:` f32(Offset + f32(raw*Quantum)),
    which scored 7,410/7,413 - the three misses need raw >= 2^24 (numBits >= 25).
  After the packed block: the count table then the per-item MAP region.
COUNT TABLE - NINE u16 (2026-08-10; 442/442 sequences over 53 oracles, zero NO_FIT, every
    tuple equal to the oracle's own per-sequence channel tallies):
    [numStaticQuat, numStaticVec3, numStaticFloat, numRawFloat, numQuantizeFloat,
     numIndirectQuantizeFloat, numInlineQuantizeFloat, numCachedQuaternion1,
     numCachedQuaternion2].
    `was:` "EIGHT u16 followed by a u16 separator(0)" - which is the SAME BYTES whenever
    numInlineQuantizeFloat == 0 and numCachedQuaternion2 == 0, because the 8-view reads the
    ninth count as its required-zero separator. That coincidence is why the earlier reading
    survived a 10-file board and still refused 33,778 sequences game-wide. What distinguishes
    a CachedQuaternion1 channel from a CachedQuaternion2 one behaviourally is NOT derived -
    only that they are two separate lists, and reproducing them as such is byte-exact.
    LOCATED by three constraints with a UNIQUENESS requirement, not a first match: the size
    equation c + (9 + Sum rup(c_i))*2 == seq_end leaves 2-3 candidates on 15 of 442 sequences
    and its lowest-offset candidate is WRONG in 14 of them, so the descriptor walk (must land
    exactly on quantOffset) and the packed-block extent (packed + (framebits//8 + nRawFloat*4)
    * FrameCount == c) are required too, and an ambiguous sequence REFUSES.
PER-ITEM MAP region - ends at seq+0x10 (total size); it is [9 counts] then one list per pool in
    count-table order (quat, vec, flt, RAW, quant, indirect, INLINE-quant, cached1, cached2);
    each list = one u16 per channel = (BoneId-item-index*4 + component),
    padded to a multiple of 4 entries with sentinel (numBones*4).  component 0..2 for a split
    x/y/z channel (or the QuatIndex for a Cached entry), 0 for a whole static vector/quat.
    Reconstruct: group channels by item, order by component, append the Cached channel last.
POOL LAYOUT / descriptor region (data..packed), in order: StaticQuaternion pool(12B ea),
    StaticVector3(12B), StaticFloat(4B), [RawFloat has NO descriptor - see RAWFLOAT below],
    QuantizeFloat descriptors(12B: numBits,Q,Off - packed in the frame-major block),
    IndirectQuantizeFloat descriptors(variable, in the frame-major block), then the INLINE
    QuantizeFloat descriptors.  The frame-major block width = Sum(quant numBits)+Sum(indirect
    slotBits); the inline-QZ pool is NOT in that block - its per-frame data is inline.
IndirectQuantizeFloat descriptor (variable, 0x14 + nPalWords*4): u32 slotBits, u32 paletteBits,
    u32 nPalWords, f32 Quantum, f32 Offset, u32 palette[nPalWords].  palette entries =
    min((nPalWords*32)//paletteBits, (1<<slotBits)-1); value = f32(Offset + f32(raw*Quantum));
    <Frames> = slotBits-wide slot (frame-major, DWORD-aligned).  Both the compact (nPalWords=1)
    and inline-palette (nPalWords>1) forms close.
RAWFLOAT (derived 2026-08-10) - the pool has NO descriptor at all, and it sits at the FRONT of
    every packed frame:
        value(channel c, frame f) = f32 at packed + f*(framebits//8 + nRawFloat*4) + c*4
    and the BIT-PACKED channels of that frame therefore start at bit nRawFloat*32, not bit 0.
    The frame stride grows by nRawFloat*4 bytes, which is also the third locator constraint.
    `was (MEASURED WRONG, and it emitted invented numbers):` "laid after that frame's bit-packed
    channels". Under that model the QuantizeFloat channels of a mixed sequence read from a cursor
    short by nRawFloat*32 bits and printed wrong values, while a `rawfloat_mixed_block` refusal
    suppressed only the RawFloat channels - a refusal scoped to the wrong thing. Adjudicated
    against lab oracles over the COMPLETE game-wide mixed population (3 sequences:
    bunk_int_p4_t04, bunk_int_p4a1_t04, bunk_int_p6_t06): raw-FIRST makes all three whole-file
    byte-identical; raw-last and raw-after-roundup32 both differ.
    `was:` earlier still, the pool was assumed zero-sized and its map list was READ AND DISCARDED
    - 20,734 channels across 98 files vanished with NOTHING counted, and every later descriptor
    base was off, usually surfacing as a mis-named "indirect_descriptors_unpinned" refusal.
    ❓ UNWITNESSED: RawFloat alongside INLINE QuantizeFloat (nr > 0 with n6 > 0) has ZERO
    occurrences game-wide, so that combination refuses (`rawfloat_with_inline_qz`).
INLINE QuantizeFloat descriptor (variable) [emits <Type>QuantizeFloat</Type>] - SOLVED:
    u32 sizeWords(=total descriptor size in u32, incl this 16B header), u32 B,
    f32 Quantum, f32 Offset, then payload = (sizeWords-4) u32 words.
    B is THREE bytes, not (numBits<<8)|8:
        B & 0xFF        = W, the width of each of the 3 payload PROLOGUE fields (8 here)
        (B>>8) & 0xFF   = numBits, the width of the 3 SEEDED values
        (B>>16) & 0xFF  = a further selector (0 in this file; 0..9 seen game-wide)
    Payload bit layout (LSB-first throughout): 3 W-bit prologue fields, then
        f0 = raw[0] ; f1 = raw[1] ; f2 = the value at the REST frame   (numBits each),
    then the code stream at bit 3*W + 3*numBits.  numBits is only wide enough to hold
    f0/f1/f2 - the DECODED values routinely exceed it (a nb=3 channel here spans 0..15).
    Codes: '1' -> 0 ; '0'*z '1' <sign> -> -z if sign else +z (z = leading-zero run).
    The stream carries exactly FrameCount-3 codes; trailing payload zeros are padding.
    DOUBLE-INTEGRATION with a single REST:
        raw[0] = f0 ; raw[1] = f1 ; V = f1 ; D = f1 - f0
        for each code c:
            if (not yet rested) and V == f2 and c == D:      # the REST
                emit V (the frame is duplicated) ; D = 0 ; rested = True
            D += c ; V += D ; emit V
    FRAME BUDGET closes exactly and is the structural proof of the rule:
        2 seeded frames + (FrameCount-3) codes + 1 rest == FrameCount.
    So f2 is NOT 'the last value' - it is the value at the one duplicated frame.  In a
    channel with a flat tail the rest lands in that tail and is invisible (which is why
    f2 == raw[FrameCount-1] there); in a fine per-2-frame staircase channel it lands
    mid-stream, at the point where the encoder wrote a code equal to the current velocity.
    VERIFIED byte-exact for all 7 inline-QZ channels of the mpsecurity drinking_shots
    sequence (numBits 3..6, W=8, selector 0), and the rest fires exactly once in each,
    with no padding-fill fallback.  A descriptor whose budget does NOT close (an unproven
    variant) yields None and the emitter writes a visible RESIDUAL comment, never values.
"""
import json
import math
import os
import struct
import sys

sys.path.insert(0, r"B:\ClaudeCode_Projects\_UEFiveMTool\quarry")
from ydr2xml import Res                 # noqa: E402  (RSC7 container reader)
from meta2xml import fmt_num, esc, joaat  # noqa: E402
from meta2xml import f32 as F             # noqa: E402  (the float32 rounding law)


def _rup(n):
    """Map lists are padded to a multiple of 4 entries."""
    return ((n + 3) // 4) * 4


# The conformant output for a .ycd whose RSC7 container is not version 46.
DECLINED_XML = '<?xml version="1.0" encoding="UTF-8"?>\n'

# INLINE QuantizeFloat: DERIVED for selector 0 (2026-08-10), REFUSED for every other selector.
# The earlier "double-integration with one REST" rule was fitted to a single file and was NOT a
# correctness test - measured against the oracles it decoded 20 channels exactly and 5 WRONG,
# with nothing in the descriptor separating the two. The real format is a 64-FRAME BLOCK CODEC
# (see _decode_inline_qz), and its accept test is STRUCTURAL: every inner block must land its bit
# cursor EXACTLY on the next stored block offset after exactly 64 frames. That is an arithmetic
# identity a wrong decode cannot satisfy by luck, which is why values may now be printed at all.
# Evidence: 1,964/1,964 sel=0 channels across the 57 oracles reproduce the oracle's exact values;
# 6,995/6,995 inner-block boundaries land exactly; 1,964/1,964 rebuilt <Item> blocks match the
# oracle text character for character. Non-zero selectors (1,810,562 channels game-wide) share
# the framing but not the code alphabet - they REFUSE and are counted.
INLINE_QZ_PROVEN = True


def declined_version(blob):
    """True when this .ycd's container version is one the reference exporter declines.

    Must be asked BEFORE the RSC7 reader inflates: the four 00_base destruction .ycd are
    version 43 and the reader dies inside inflate ("inflated payload shorter than the declared
    system segment") long before require_version could speak. The reference exporter declines
    them too - each of those four oracles is exactly 40 bytes, the XML declaration with NO root
    element (hexdump-verified on all four, 2026-08-10) - so emitting the declaration alone is
    byte-identical conformance, not a shortcut. Every decline is COUNTED by the caller, so the
    class is visible in the run summary rather than looking like a successful conversion.

    ⛔⛔ THE "DIES INSIDE INFLATE" HALF IS REFUTED (re-tested 2026-08-15 against today's container
    code, all four): they inflate CLEANLY - 7,122 / 32,552 / 62,559 / 133,225 B in produce
    16,384 / 65,536 / 98,304 / 172,032 B system segments, and `Res.from_bytes` succeeds on 4/4.
    They are also NOT a foreign container: all four carry the same crClipDictionary shape
    (11 buckets, 1 clip, 1 animation each) and `ycd_write` walks them, reaching 20.7%-56.5% of
    the segment. What is actually unmodelled is the SEQUENCE DATA REGION - `_locate_counts` finds
    no candidate on 1/1/3/5 of their sequences - so the honest label is "v43 sequence encoding
    underived", not "the reader dies inside inflate".
    ⚠ THE OTHER HALF - that the reference exporter also declines them - is UNTOUCHED by this and
    was NOT re-tested here; the reference declining a file is not evidence about the file.
    ⚠ THE DECLINE IS DELIBERATELY LEFT IN PLACE: emitting a real conversion needs the v43
    sequence encoding, which nobody has derived. This note exists so the next agent re-opens the
    right question. Related and already closed: the `.ybd` lane's single v40 file
    (`des_setpiece.ybd`) round-trips 100.0000% with 0 unreached bytes - measured 2026-08-15, so
    an old container version is not by itself a reason to decline.
    """
    if len(blob) < 8 or blob[:4] != b'RSC7':
        return False
    return struct.unpack_from('<I', blob, 4)[0] != 46

# THE_PLAN 5.0 (2026-08-06): every RESIDUAL/UNPINNED marker written into the XML is ALSO
# counted here, because a file full of markers still converts "ok" - the caller (quarry.py's
# ycd branch) clears this per file and folds it into the printed run summary. Without this,
# the markers were visible only to someone reading the emitted XML text.
RESIDUALS = {}


def u8(S, o):  return S[o]
def u16(S, o): return struct.unpack_from("<H", S, o)[0]
def u32(S, o): return struct.unpack_from("<I", S, o)[0]
def i32(S, o): return struct.unpack_from("<i", S, o)[0]
def f32(S, o): return struct.unpack_from("<f", S, o)[0]
def P(v):      return v & 0x0FFFFFFF


def cstr(S, ptr):
    if not ptr:
        return ""
    return S[ptr:S.find(b"\x00", ptr)].decode("latin-1")


def atmap(S, bucket_ptr, nbuckets):
    """Yield value-pointers in bucket-index then linked-list order (== XML order).
    Entry node = {u32 key, u32 pad, u64 valptr(tagged), u64 nextptr(tagged)}."""
    for b in range(nbuckets):
        node = u32(S, bucket_ptr + b * 8)
        while node & 0xF0000000:
            n = P(node)
            yield u32(S, n), P(u32(S, n + 8))
            node = u32(S, n + 0x10)


# crPropertyAttribute type codes. 3=Bool and 12=HashString were derived 2026-08-10 from the
# 57-oracle draw (14 witnesses): Bool reads u32 @attr+0x20 and spells `<Value value="%d" />`;
# HashString reads u32 @attr+0x20 and spells it as ELEMENT TEXT `<Value>%s</Value>` through the
# name table - it is the ONE attribute kind that is not attribute-form, so do not fold it into
# the generic path.
ATTR_TYPE = {2: "Int", 6: "Vector3", 8: "Vector4", 1: "Float", 3: "Bool", 4: "String",
             12: "HashString"}


def _witnessed_names():
    """The oracle-witnessed content-name overlay, shared with quarry.py and pso2xml.py.

    The reference exporter carries a hash->name index we cannot read; a string it spells that
    exists nowhere in the binary can only come from that index. The sanctioned proxy (maintainer
    call 2026-08-08, extended to this lane 2026-08-10) is what the ORACLES themselves spell:
    self-verifying, because an entry only ever fires where joaat(name) equals the hash actually
    stored in the file, so a wrong entry cannot mis-name anything - it is simply dead weight.
    REVERSIBLE: delete oracle_witnessed_names.json and every lane reverts to hash_%08X.
    """
    out = {}
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'oracle_witnessed_names.json')
    if os.path.isfile(p):
        try:
            for n in json.load(open(p, encoding='utf-8')).get('names', []):
                out.setdefault(joaat(n), n)
        except Exception:
            pass
    return out


class Ycd:
    def __init__(self, path):
        self.r = path if hasattr(path, "sys") else Res(path)
        self.r.require_version(46, "ycd")
        self.S = self.r.sys
        S = self.S
        # ---- dictionaries ----
        self.clips_bp = P(u32(S, 0x28)); self.clips_n = u16(S, 0x30)   # inline atMap
        aobj = P(u32(S, 0x18))
        self.anims_bp = P(u32(S, aobj + 0x18)); self.anims_n = u16(S, aobj + 0x20)
        self.a2k = {av: k for k, av in atmap(S, self.anims_bp, self.anims_n)}  # anim ptr -> hash
        # ---- name dictionary (for reversible <Hash>) ----
        # Base layer = the oracle-witnessed overlay (vocabulary the reference exporter spells
        # from its own index; proven absent from this file's system segment by byte-search).
        # The file's OWN clip stems are layered ON TOP, so real in-file content always wins.
        self.names = _witnessed_names()
        for _, cv in atmap(S, self.clips_bp, self.clips_n):
            nm = cstr(S, P(u32(S, cv + 0x18)))          # "pack:/<stem>.clip"
            stem = nm[6:-5] if nm.startswith("pack:/") and nm.endswith(".clip") else nm
            self.names[joaat(stem)] = stem

    def hstr(self, h):
        return self.names.get(h, "hash_%08X" % h)

    # ---------------------------------------------------------------- clips
    def emit_clips(self, out):
        S = self.S
        items = list(atmap(S, self.clips_bp, self.clips_n))
        if not items:                       # an EMPTY dictionary self-closes (2 witnesses;
            out.append(" <Clips />")        # drf_mic_3_cs_2-100.ycd is 101 B in full)
            return
        out.append(" <Clips>")
        for ckey, cv in items:
            self.emit_clip(out, ckey, cv)
        out.append(" </Clips>")

    def emit_clip(self, out, ckey, cv):
        S = self.S
        typ = u32(S, cv + 0x10)                          # 1=Animation 2=AnimationList
        name = cstr(S, P(u32(S, cv + 0x18)))
        out.append("  <Item>")
        # <Hash> is the dictionary KEY reversed through the name table - NOT joaat of the stem.
        # They coincide for the ANIMATION dictionary but not for CLIPS: cs2_05.ycd stores key
        # 0xF5B0F874 while joaat("cs2_05_decal_003_uv_0") is 0x8DA8CB7E, and the oracle spells
        # the KEY. Measured on 7 witnesses, 2026-08-10.
        out.append("   <Hash>%s</Hash>" % esc(self.hstr(ckey)))
        out.append("   <Name>%s</Name>" % esc(name))
        out.append('   <Type value="%s" />' % ("Animation" if typ == 1 else "AnimationList"))
        out.append('   <Unknown30 value="%d" />' % u32(S, cv + 0x30))
        self.emit_tags(out, cv + 0x38)          # atArray<crTag*>
        self.emit_properties(out, cv + 0x40)    # atMap<crProperty>

        if typ == 1:                                     # crClipAnimation
            out.append("   <AnimationHash>%s</AnimationHash>" % self.hstr(self.a2k.get(P(u32(S, cv + 0x50)), 0)))
            out.append('   <StartTime value="%s" />' % fmt_num(f32(S, cv + 0x58)))
            out.append('   <EndTime value="%s" />' % fmt_num(f32(S, cv + 0x5C)))
            out.append('   <Rate value="%s" />' % fmt_num(f32(S, cv + 0x60)))
        else:                                            # crClipAnimationList
            arr = P(u32(S, cv + 0x50)); n = u16(S, cv + 0x58)  # inline refs, stride 0x18
            out.append('   <Duration value="%s" />' % fmt_num(f32(S, cv + 0x60)))
            out.append("   <Animations>")
            for i in range(n):
                e = arr + i * 0x18
                out.append("    <Item>")
                out.append("     <AnimationHash>%s</AnimationHash>" % self.hstr(self.a2k.get(P(u32(S, e + 0x10)), 0)))
                out.append('     <StartTime value="%s" />' % fmt_num(f32(S, e + 0x00)))
                out.append('     <EndTime value="%s" />' % fmt_num(f32(S, e + 0x04)))
                out.append('     <Rate value="%s" />' % fmt_num(f32(S, e + 0x08)))
                out.append("    </Item>")
            out.append("   </Animations>")
        out.append("  </Item>")

    def emit_tags(self, out, base):
        """Tags: clip+0x38 -> crTags container whose atArray<crTag*> is {ptr@+0, u16 count@+8}."""
        S = self.S
        cont = P(u32(S, base))
        if not cont:
            out.append("   <Tags />"); return
        ap = P(u32(S, cont)); n = u16(S, cont + 8)
        if n == 0:
            out.append("   <Tags />"); return
        out.append("   <Tags>")
        for i in range(n):
            tv = P(u32(S, ap + i * 8))
            out.append("    <Item>")
            out.append("     <NameHash>%s</NameHash>" % self.hstr(u32(S, tv + 0x18)))
            out.append("     <UnkHash>%s</UnkHash>" % self.hstr(u32(S, tv + 0x38)))
            self.emit_attrs(out, P(u32(S, tv + 0x20)), u16(S, tv + 0x28))
            out.append('     <StartPhase value="%s" />' % fmt_num(f32(S, tv + 0x40)))
            out.append('     <EndPhase value="%s" />' % fmt_num(f32(S, tv + 0x44)))
            out.append("    </Item>")
        out.append("   </Tags>")

    def emit_properties(self, out, base):
        """Properties = atMap<crProperty> at clip+0x40 -> {bucketptr, u16 nbuckets, u16 nentries}."""
        S = self.S
        ms = P(u32(S, base))
        if not ms:
            out.append("   <Properties />"); return
        bp = P(u32(S, ms)); nb = u16(S, ms + 8); ne = u16(S, ms + 0x0A)
        if ne == 0:
            out.append("   <Properties />"); return
        out.append("   <Properties>")
        for _, pv in atmap(S, bp, nb):
            out.append("    <Item>")
            out.append("     <NameHash>%s</NameHash>" % self.hstr(u32(S, pv + 0x18)))
            out.append("     <UnkHash>%s</UnkHash>" % self.hstr(u32(S, pv + 0x38)))
            self.emit_attrs(out, P(u32(S, pv + 0x20)), u16(S, pv + 0x28))
            out.append("    </Item>")
        out.append("   </Properties>")

    def emit_attrs(self, out, ap, ac):
        S = self.S
        if ac == 0:
            out.append("     <Attributes />"); return
        out.append("     <Attributes>")
        for i in range(ac):
            a = P(u32(S, ap + i * 8))
            t = u32(S, a + 0x08); nh = u32(S, a + 0x18)
            # ⛔ NO INVENTED TYPE NAMES. `was:` ATTR_TYPE.get(t, "type%d" % t), which spelled an
            # unwitnessed code as e.g. "type4" AND - because the if/elif chain below has no else -
            # dropped the <Value> element entirely, with nothing counted. Witnessed firing on
            # Type 4 (space_cannon): our file was 2 lines short of the oracle and RESIDUALS came
            # back empty. The 57-oracle board can never catch it (its type census is {1,2,3,6,8,12}).
            if t not in ATTR_TYPE:
                RESIDUALS["attr_type_unwitnessed"] = RESIDUALS.get("attr_type_unwitnessed", 0) + 1
                out.append("      <Item>")
                out.append("       <NameHash>%s</NameHash>" % self.hstr(nh))
                out.append('       <!-- RESIDUAL: crPropertyAttribute Type %d unwitnessed - no '
                           'oracle shows its name or value spelling -->' % t)
                out.append("      </Item>")
                continue
            tn = ATTR_TYPE[t]
            out.append("      <Item>")
            out.append("       <NameHash>%s</NameHash>" % self.hstr(nh))
            out.append('       <Type value="%s" />' % tn)
            if tn == "Bool":
                out.append('       <Value value="%d" />' % u32(S, a + 0x20))
            elif tn == "HashString":
                # one of TWO attribute kinds spelled as element TEXT, not a value= attribute
                out.append('       <Value>%s</Value>' % esc(self.hstr(u32(S, a + 0x20))))
            elif tn == "String":
                # Type 4 = String, derived 2026-08-12. It was the ONLY unwitnessed attribute code
                # in the whole game (234 markers in 60 files, all Type 4 — no second code exists).
                # LAYOUT, read off the bytes: atArray<char> at +0x20 — u64 ptr, u16 Count(=strlen),
                # u16 Size(=Count+1). Proven the hard way rather than assumed: for all 234 the
                # actual text length at the pointer equals the stored Count exactly and the byte
                # past it is NUL. Control: the same test run against the 3,613 HashString
                # attributes (whose value is a plain number, not a pointer) FAILS — so the test
                # discriminates and is not just agreeing with itself.
                # Spelled as element TEXT like HashString: <Clips> byte-exact on 6/6 oracles,
                # with `<Value value=...>` as the must-fail control at 0/6.
                _s = cstr(S, P(u32(S, a + 0x20)))
                if "\r" in _s or "\n" in _s:
                    # ⚠ CARVE-OUT, deliberately still refusing: 124 of the 234 game-wide values
                    # contain a raw 0x0D and NO reference export anywhere witnesses one (1,941
                    # oracle XML scanned: zero lone CR, zero &#xD;). esc() would write it bare and
                    # we would be guessing the reference's escaping. Refuse until an oracle lands.
                    RESIDUALS["attr_string_control_char"] = \
                        RESIDUALS.get("attr_string_control_char", 0) + 1
                    out.append('       <!-- RESIDUAL: String value contains a control byte; '
                               'no oracle shows how the reference escapes it -->')
                else:
                    out.append('       <Value>%s</Value>' % esc(_s))
            elif tn == "Int":
                out.append('       <Value value="%d" />' % i32(S, a + 0x20))
            elif tn == "Float":
                out.append('       <Value value="%s" />' % fmt_num(f32(S, a + 0x20)))
            elif tn == "Vector3":
                out.append('       <Value x="%s" y="%s" z="%s" />' % (
                    fmt_num(f32(S, a + 0x20)), fmt_num(f32(S, a + 0x24)), fmt_num(f32(S, a + 0x28))))
                out.append('       <Unknown2C value="%s" />' % fmt_num(f32(S, a + 0x2C)))
            elif tn == "Vector4":
                out.append('       <Value x="%s" y="%s" z="%s" w="%s" />' % (
                    fmt_num(f32(S, a + 0x20)), fmt_num(f32(S, a + 0x24)),
                    fmt_num(f32(S, a + 0x28)), fmt_num(f32(S, a + 0x2C))))
            out.append("      </Item>")
        out.append("     </Attributes>")

    # ---------------------------------------------------------------- animations
    def emit_anims(self, out):
        S = self.S
        items = list(atmap(S, self.anims_bp, self.anims_n))
        if not items:                            # empty dictionary self-closes, as for Clips
            out.append(" <Animations />")
            return
        out.append(" <Animations>")
        for key, av in items:
            self.emit_anim(out, key, av)
        out.append(" </Animations>")

    def emit_anim(self, out, key, av):
        S = self.S
        out.append("  <Item>")
        out.append("   <Hash>%s</Hash>" % self.hstr(key))
        out.append('   <Unknown10 value="%d" />' % u8(S, av + 0x10))
        out.append('   <FrameCount value="%d" />' % u16(S, av + 0x14))
        out.append('   <SequenceFrameLimit value="%d" />' % u16(S, av + 0x16))
        out.append('   <Duration value="%s" />' % fmt_num(f32(S, av + 0x18)))
        out.append("   <Unknown1C>%s</Unknown1C>" % self.hstr(u32(S, av + 0x1C)))
        # BoneIds : av+0x50 -> array (stride 4: u16 BoneId, u8 Track, u8 Unk0), count av+0x58
        bp = P(u32(S, av + 0x50)); bc = u16(S, av + 0x58)
        out.append("   <BoneIds>")
        for i in range(bc):
            o = bp + i * 4
            out.append("    <Item>")
            out.append('     <BoneId value="%d" />' % u16(S, o))
            out.append('     <Track value="%d" />' % u8(S, o + 3))
            out.append('     <Unk0 value="%d" />' % u8(S, o + 2))
            out.append("    </Item>")
        out.append("   </BoneIds>")
        # Sequences : av+0x40 -> array of ptrs, count av+0x48
        sp = P(u32(S, av + 0x40)); sc = u16(S, av + 0x48)
        out.append("   <Sequences>")
        for i in range(sc):
            seq = P(u32(S, sp + i * 8))
            self.emit_sequence(out, seq, bc)
        out.append("   </Sequences>")
        out.append("  </Item>")

    def emit_sequence(self, out, seq, nbones):
        """One crAnimSequence -> its <SequenceData>.

        THE COUNT TABLE IS NINE u16 (derived 2026-08-10 over 53 oracles / 442 sequences:
        442/442 fit with zero NO_FIT, and every tuple equals the oracle's own per-sequence
        channel tallies):
            [nStaticQuat, nStaticVec3, nStaticFloat, nRawFloat, nQuantizeFloat,
             nIndirectQuantizeFloat, nInlineQuantizeFloat, nCachedQuaternion1,
             nCachedQuaternion2]
        followed by NINE per-pool u16 map lists, each padded to a multiple of 4 entries.
        `was:` the reader treated this as EIGHT counts plus a "u16 must be 0" separator - which
        is byte-identical ONLY while nInlineQuantizeFloat == 0 AND nCachedQuaternion2 == 0, and
        which refused 33,778 sequences game-wide. The ninth pool is a SECOND cached-quaternion
        list; Cached1/Cached2 reproduce the oracle exactly, but what distinguishes them
        behaviourally is NOT derived - only that they are two separate lists.
        """
        S = self.S
        out.append("    <Item>")
        out.append("     <Hash>%s</Hash>" % self.hstr(u32(S, seq)))
        framecount = u16(S, seq + 0x16)
        out.append('     <FrameCount value="%d" />' % framecount)
        data = seq + 0x20
        packed = data + u32(S, seq + 0x0C)

        cands = self._locate_counts(seq, nbones)
        if len(cands) != 1:
            # UNIQUENESS IS THE TEST, not existence: the size equation alone leaves 2-3
            # candidates on 15 of 442 sequences and the lowest-offset one is WRONG in 14 of
            # them, so a first-match-wins scan emits a plausible, unmarked, WRONG channel map.
            # Refuse loudly instead, and say how many candidates survived.
            out.append("     <SequenceData>")
            # ⛔ THE OLD MESSAGE NAMED THE WRONG FAILURE. It read "(N candidates)" and the comment
            # above describes AMBIGUITY — but all 265 markers in the corpus reported ZERO, i.e.
            # nothing survived, the opposite problem. The lane was sized off a message that did
            # not measure what it printed. Say which failure it actually is.
            out.append("      <!-- count table not located (%s) -->"
                       % ("no candidate survived the constraints" if not cands
                          else "%d candidates survived; ambiguous" % len(cands)))
            RESIDUALS["count_table_not_located"] = RESIDUALS.get("count_table_not_located", 0) + 1
            out.append("     </SequenceData>")
            out.append("    </Item>")
            return True
        co, counts, qz_descs, ind_descs, inl_descs, framebits = cands[0]
        nq, nv, nf, nr, nqz, ni, n6, nc1, nc2 = counts
        quat_b = data
        vec_b = quat_b + nq * 12
        flt_b = vec_b + nv * 12

        def readbits(bit, n):
            v = 0
            for i in range(n):
                pp = bit + i
                v |= ((S[packed + (pp >> 3)] >> (pp & 7)) & 1) << i
            return v

        # RAWFLOAT HAS NO DESCRIPTOR. Its data is frame-major INSIDE the packed block, laid
        # after that frame's bit-packed channels, so the frame stride grows by nr*4 bytes.
        # `was:` the pool was assumed zero-sized and its map list was read and DISCARDED -
        # 20,734 channels across 98 files vanished from the XML with nothing counted, and every
        # later descriptor base was wrong, which usually surfaced as a MIS-NAMED
        # "indirect_descriptors_unpinned" refusal (a marker naming the wrong cause).
        stride_bits = (framebits // 8 + nr * 4) * 8
        qz_vals = [[] for _ in qz_descs]
        ind_raw = [[] for _ in ind_descs]
        for fr in range(framecount):
            # RawFloat sits at the FRONT of each frame, so the bit-packed channels start after
            # it. Measured on the complete game-wide mixed population (3 sequences): raw-first
            # is whole-file byte-identical, raw-last and raw-after-roundup32 both differ.
            bit = fr * stride_bits + nr * 32
            for k, d in enumerate(qz_descs):
                nb = u32(S, d)
                q = f32(S, d + 4)
                off = f32(S, d + 8)
                # FLOAT LAW: float32 the raw integer BEFORE the multiply (7,413/7,413 exact).
                qz_vals[k].append(F(F(off) + F(F(readbits(bit, nb)) * q)))
                bit += nb
            for k, d in enumerate(ind_descs):
                sb = u32(S, d)
                ind_raw[k].append(readbits(bit, sb))
                bit += sb

        # Every RawFloat witness (6 sequences / 5 files) carries NO bit-packed pool alongside,
        # so the interleave between the f32 array and a bitstream within one frame is
        # UNWITNESSED. Refuse that combination rather than guess a byte order.
        # `was:` raw_ok = (nqz == 0 and ni == 0 and n6 == 0) - a MIS-SCOPED refusal. It hid the
        # RawFloat channels of a mixed sequence while leaving the QuantizeFloat channels sharing
        # those frames to read from a cursor that was wrong by nr*32 bits, so the file still
        # emitted invented numbers and the counter pointed at the wrong thing. With the geometry
        # right there is nothing to suppress. The one combination nobody has witnessed is
        # RawFloat alongside INLINE QuantizeFloat (n6): zero occurrences game-wide, so it refuses.
        raw_ok = (n6 == 0)
        raw_vals = []
        if nr and raw_ok:
            raw_vals = [[F(f32(S, packed + fr * (stride_bits // 8) + k * 4))
                         for fr in range(framecount)] for k in range(nr)]

        m = co + 18                                   # nine counts, then the nine map lists

        def take(cnt):
            nonlocal m
            vals = [u16(S, m + i * 2) for i in range(cnt)]
            m += _rup(cnt) * 2
            return vals

        map_q = take(nq); map_v = take(nv); map_f = take(nf); map_r = take(nr)
        map_qz = take(nqz); map_ind = take(ni); map_inl = take(n6)
        map_c1 = take(nc1); map_c2 = take(nc2)

        items = {}

        def add(mapping, kind):
            for slot, val in enumerate(mapping):
                items.setdefault(val // 4, []).append((val % 4, kind, slot))

        add(map_q, "SQ"); add(map_v, "SV"); add(map_f, "SF"); add(map_r, "RF")
        add(map_qz, "QZ"); add(map_ind, "IQ"); add(map_inl, "Q6")
        cached = {}
        for val in map_c1:
            cached[val // 4] = ("CachedQuaternion1", val % 4)
        for val in map_c2:
            cached[val // 4] = ("CachedQuaternion2", val % 4)

        out.append("     <SequenceData>")
        for it in range(nbones):
            out.append("      <Item>")
            out.append("       <Channels>")
            for comp, kind, pl in sorted(items.get(it, [])):
                if kind == "SQ":
                    b = quat_b + pl * 12
                    x, y, z = f32(S, b), f32(S, b + 4), f32(S, b + 8)
                    w = F(math.sqrt(max(0.0, F(1.0 - F(F(F(x * x) + F(y * y)) + F(z * z))))))
                    out.append('        <Item>')
                    out.append('         <Type value="StaticQuaternion" />')
                    out.append('         <Value x="%s" y="%s" z="%s" w="%s" />' % (
                        fmt_num(x), fmt_num(y), fmt_num(z), fmt_num(w)))
                    out.append('        </Item>')
                elif kind == "SV":
                    b = vec_b + pl * 12
                    out.append('        <Item>')
                    out.append('         <Type value="StaticVector3" />')
                    out.append('         <Value x="%s" y="%s" z="%s" />' % (
                        fmt_num(f32(S, b)), fmt_num(f32(S, b + 4)), fmt_num(f32(S, b + 8))))
                    out.append('        </Item>')
                elif kind == "SF":
                    out.append('        <Item>')
                    out.append('         <Type value="StaticFloat" />')
                    out.append('         <Value value="%s" />' % fmt_num(f32(S, flt_b + pl * 4)))
                    out.append('        </Item>')
                elif kind == "RF":
                    out.append('        <Item>')
                    out.append('         <Type value="RawFloat" />')
                    if not raw_ok:
                        RESIDUALS["rawfloat_with_inline_qz"] = \
                            RESIDUALS.get("rawfloat_with_inline_qz", 0) + 1
                        out.append('         <!-- RESIDUAL: RawFloat alongside inline '
                                   'QuantizeFloat (nr=%d n6=%d): zero witnesses game-wide, '
                                   'interleave underived -->' % (nr, n6))
                    else:
                        self._emit_values(out, raw_vals[pl], "         ")
                    out.append('        </Item>')
                elif kind == "QZ":
                    d = qz_descs[pl]
                    out.append('        <Item>')
                    out.append('         <Type value="QuantizeFloat" />')
                    out.append('         <Quantum value="%s" />' % fmt_num(f32(S, d + 4)))
                    out.append('         <Offset value="%s" />' % fmt_num(f32(S, d + 8)))
                    self._emit_values(out, qz_vals[pl], "         ")
                    out.append('        </Item>')
                elif kind == "IQ":
                    self._emit_indirect(out, S, ind_descs[pl], ind_raw[pl])
                elif kind == "Q6":
                    d = inl_descs[pl]
                    out.append('        <Item>')
                    out.append('         <Type value="QuantizeFloat" />')
                    out.append('         <Quantum value="%s" />' % fmt_num(f32(S, d + 8)))
                    out.append('         <Offset value="%s" />' % fmt_num(f32(S, d + 0xC)))
                    vals = self._decode_inline_qz(d, framecount) if INLINE_QZ_PROVEN else None
                    if vals is None:
                        RESIDUALS["inline_quantize_undecoded"] = \
                            RESIDUALS.get("inline_quantize_undecoded", 0) + 1
                        out.append('         <!-- RESIDUAL: inline QuantizeFloat variant '
                                   'B=%#010x sizeWords=%d not decoded -->'
                                   % (u32(S, d + 4), u32(S, d)))
                    else:
                        self._emit_values(out, vals, "         ")
                    out.append('        </Item>')
            if it in cached:
                tn, qi = cached[it]
                out.append('        <Item>')
                out.append('         <Type value="%s" />' % tn)
                out.append('         <QuatIndex value="%d" />' % qi)
                out.append('        </Item>')
            out.append("       </Channels>")
            out.append("      </Item>")
        out.append("     </SequenceData>")
        out.append("    </Item>")
        return True

    def _locate_counts(self, seq, nbones):
        """Every surviving count-table candidate for one sequence, under THREE constraints.

        C1 size equation: c + (9 + sum(rup(count_i)))*2 == seq_end, with all nine counts <= 400.
        C2 descriptor walk: walking the pools from `data` must land EXACTLY on quantOffset.
        C3 packed-block extent: packed + (framebits//8 + nRawFloat*4) * FrameCount == c.
        C1 ALONE IS NOT SUFFICIENT - 15 of 442 sequences keep 2-3 candidates under it and the
        lowest-offset one is wrong in 14 of them. The caller requires exactly ONE survivor, so
        an ambiguous sequence refuses instead of silently taking the first fit.
        """
        S = self.S
        data = seq + 0x20
        quant_off = u32(S, seq + 0x0C)
        packed = data + quant_off
        seq_end = seq + u32(S, seq + 0x10)
        framecount = u16(S, seq + 0x16)
        cands = []
        for c in range(packed, seq_end - 18, 2):
            cc = tuple(u16(S, c + k * 2) for k in range(9))
            # ⛔ `was:` max(cc) > 400 — a MAGIC NUMBER with no meaning in the format, and the SOLE
            # cause of all 265 "count table not located" refusals across 51 files. Those files are
            # large destruction and cutscene animations whose real pool counts routinely exceed
            # it (largest measured: 889 channels on a 262-bone skeleton), so the TRUE table was
            # being discarded and nothing survived. The structural bound is the number of
            # addressable channel slots, because every map entry is itemIndex*4 + component.
            # Measured headroom: worst real ratio max(count)/(nBones*4) = 0.848 over 4,281
            # sequences.
            if nbones and max(cc) > nbones * 4:
                continue
            if c + (9 + sum(_rup(x) for x in cc)) * 2 != seq_end:
                continue
            nq, nv, nf, nr, nqz, ni, n6, nc1, nc2 = cc
            o = data + nq * 12 + nv * 12 + nf * 4      # NOTE: RawFloat has NO descriptor
            qz_d = [o + k * 12 for k in range(nqz)]
            o += nqz * 12
            ind_d = []
            bad = False
            for _ in range(ni):
                if o + 0x14 > len(S):
                    bad = True
                    break
                ind_d.append(o)
                o += 0x14 + u32(S, o + 8) * 4          # variable IQ descriptor
            if bad:
                continue
            inl_d = []
            for _ in range(n6):
                if o + 16 > len(S):
                    bad = True
                    break
                sw = u32(S, o)
                if sw < 4 or o + sw * 4 > len(S):
                    bad = True
                    break
                inl_d.append(o)
                o += sw * 4
            if bad or o - data != quant_off:
                continue
            fb = sum(u32(S, d) for d in qz_d) + sum(u32(S, d) for d in ind_d)
            framebits = ((fb + 31) // 32) * 32
            if packed + (framebits // 8 + nr * 4) * framecount != c:
                continue
            # C4 — MAP-LIST RANGE + SENTINEL. The constraint a wrong offset cannot satisfy by
            # luck, and the reason the cap above could be removed safely. DERIVED from reference
            # data, not assumed: walking the nine map lists from c+18 over the 57 ledgered
            # oracles' 442 sequences, all 3,782 PAD slots equal nBones*4 with NO other value
            # occurring at all, and 0 of 32,314 REAL entries ever reach it.
            # It SEPARATES rather than merely closing: against the size equation alone it
            # rejected 15 of 15 known-wrong candidates across 14 sequences with zero false
            # rejects, taking candidate counts from {1:428, 2:13, 3:1} to {1:442}.
            # ⚠ A STRICTER RULE THAT LOOKED STRUCTURAL WAS FALSE and only the control caught it:
            # also requiring sum(counts) <= nBones*4 cost a passing oracle
            # (switch@michael@on_set_w_jmy.ycd), because channels are NOT unique per
            # (item, component) — a cached quaternion can share a slot. Max-per-list holds; the
            # sum does not.
            if nbones:
                m = c + 18
                ok = True
                for cnt in cc:
                    if m + _rup(cnt) * 2 > len(S):
                        ok = False
                        break
                    if any(u16(S, m + i * 2) >= nbones * 4 for i in range(cnt)):
                        ok = False
                        break
                    if any(u16(S, m + i * 2) != nbones * 4 for i in range(cnt, _rup(cnt))):
                        ok = False
                        break
                    m += _rup(cnt) * 2
                if not ok:
                    continue
            cands.append((c, cc, qz_d, ind_d, inl_d, framebits))
        return cands

    def _decode_inline_qz(self, desc, framecount):
        """INLINE QuantizeFloat - 64-frame BLOCK codec, Rice(k = selector).

        Descriptor: u32 sizeWords, u32 B, f32 Quantum, f32 Offset, payload = sizeWords-4 u32.
            W   = B & 0xFF           bit width of each block bit-offset
            nb  = (B >> 8) & 0xFF    bit width of each block seed value
            sel = (B >> 16) & 0xFF   RICE PARAMETER k of the code alphabet
            hi  = (B >> 24) & 0xFF   0 on every witness -> refuse if set

        N = ceil(framecount / 64).  Payload is an LSB-first bitstream:
            N x W-bit block bit-offsets (off[0] == 0, strictly increasing; measured from
            the end of the header), then N x nb-bit block seeds, then the code stream.
            hdr = N * (W + nb).
        Block j covers frames [64j, min(64j+64, framecount)); it decodes independently
        from bit hdr+off[j] with V = seed[j] and D = 0 (the velocity RESETS every block):
            emit V, then (blockframes - 1) codes.  One code, k = sel:
                [k-bit remainder, LSB-first][unary quotient: q zeros then a 1][sign if m]
                m = (q << k) | rem ;  c = -m if signbit else +m ;  m == 0 carries NO sign
            per code: D += c ; V += D ; emit V
        k = 0 is exactly the previously proven selector-0 code (no remainder field).
        Returns None whenever anything fails to close -> a counted residual, never values.
        """
        S = self.S
        A = u32(S, desc); B = u32(S, desc + 4)
        q = f32(S, desc + 8); off = f32(S, desc + 0xC)
        W = B & 0xFF
        nb = (B >> 8) & 0xFF
        k = (B >> 16) & 0xFF
        if (B >> 24) != 0:                     # top byte UNDERIVED (0 on all 4,086 witnesses)
            return None
        if k > 13:                             # UNWITNESSED selector: the census tops out at
            return None                        # 13 and all 14 values have oracle witnesses
        base = desc + 16
        end = desc + A * 4
        if A < 4 or end > len(S):
            return None
        nbits = (end - base) * 8
        if framecount < 1 or nbits <= 0:
            return None

        def bit(i):
            return (S[base + (i >> 3)] >> (i & 7)) & 1

        def fld(pos, n):
            v = 0
            for i in range(n):
                v |= bit(pos + i) << i
            return v

        N = (framecount + 63) // 64
        hdr = N * (W + nb)
        if hdr > nbits:
            return None
        offs = [fld(i * W, W) for i in range(N)]
        seeds = [fld(N * W + i * nb, nb) for i in range(N)]
        if offs[0] != 0:
            return None
        for i in range(N - 1):
            if offs[i] >= offs[i + 1]:
                return None
        # ⛔ `>=` REFUSED A LEGAL LAYOUT — and the marker it produced named the wrong cause for
        # 724 channels across 274 files (derived + fixed 2026-08-12).
        #
        # The marker read "inline QuantizeFloat variant B=0x.. sizeWords=N not decoded", which
        # implied an undecoded FORMAT. It was not: B is already correctly split above into
        # W / nb / k, and the SAME (B, sizeWords) pairs decode fine elsewhere — 91 of 104
        # reproduced refusals share an identical pair with a channel that decodes, 99 of them in
        # the same file. There was never an unwitnessed variant to derive.
        #
        # THE REAL SHAPE: when FrameCount % 64 == 1 the final block holds exactly ONE frame — the
        # seed alone, zero codes, therefore ZERO BITS — so its stored start position legally
        # equals the payload's bit length. Roughly one time in 32 the payload also ends flush on a
        # 32-bit word, and then offs[-1] + hdr == nbits exactly. `>=` called that out of range.
        # Measured: ALL 724 corpus markers have FrameCount % 64 == 1 (base rate 21.5%), and the
        # overshoot `hdr + offs[-1] - nbits` is EXACTLY 0 on 104/104 reproduced refusals — one
        # distinct value, never positive. 104 of the 3,288 fc%64==1 channels = 3.16%, against the
        # 1/32 = 3.125% a zero-slack final word predicts.
        #
        # A genuinely overrunning block is still refused: the per-frame reads below bounds-check
        # in both the k>0 and k==0 paths, so relaxing only the boundary case cannot let a real
        # overrun through.
        # Evidence: 103/103 previously-refused channels now emit token-for-token what the
        # reference exporter wrote; 25/26 whole files byte-identical (the 26th differs only on a
        # name-table hash, not the codec); all 15,160 already-decoding channels unchanged.
        if hdr + offs[-1] > nbits:
            return None
        raw = []
        for j in range(N):
            nfr = min(64, framecount - j * 64)
            p = hdr + offs[j]
            V = seeds[j]; Dv = 0
            raw.append(V)
            for _ in range(nfr - 1):
                if p + k > nbits:
                    return None
                rem = fld(p, k) if k else 0
                p += k
                z = 0
                while p < nbits and not bit(p):
                    z += 1; p += 1
                if p >= nbits:
                    return None
                p += 1
                m = (z << k) | rem
                if m:
                    if p >= nbits:
                        return None
                    c = -m if bit(p) else m
                    p += 1
                else:
                    c = 0
                Dv += c; V += Dv
                if V < 0:                      # raws are unsigned quantiser indices:
                    return None                # measured >= 0 on 4,086/4,086 witnesses
                raw.append(V)
            if j + 1 < N:
                if p != hdr + offs[j + 1]:
                    return None      # STRUCTURAL GATE: a 64-frame block must land exactly
            elif not (0 <= nbits - p <= 31):
                return None          # tail may only be the u32 padding of the last word
        if len(raw) != framecount:
            return None
        from meta2xml import f32 as _F
        return [_F(_F(off) + _F(_F(rw) * q)) for rw in raw]

    def _emit_values(self, out, vals, ind):
        if len(vals) <= 10:
            out.append("%s<Values>%s</Values>" % (ind, " ".join(fmt_num(v) for v in vals)))
            return
        out.append("%s<Values>" % ind)
        for i in range(0, len(vals), 10):
            out.append("%s %s" % (ind, " ".join(fmt_num(v) for v in vals[i:i + 10])))
        out.append("%s</Values>" % ind)

    def _emit_indirect(self, out, S, desc, raws):
        from meta2xml import f32 as F
        slotbits = u32(S, desc); pbits = u32(S, desc + 4); npw = u32(S, desc + 8)
        q = f32(S, desc + 0xC); off = f32(S, desc + 0x10)
        # inline palette: npw u32 at desc+0x14, paletteBits each. Entry count = what the
        # nPalWords hold, CAPPED at (1<<slotBits)-1 (a frame index can address no more) -
        # the cap is what keeps the compact form right, and min(9,15) leaves the inline
        # 9-entry palette intact.
        big = int.from_bytes(bytes(S[desc + 0x14: desc + 0x14 + npw * 4]), "little")
        n_pal = min((npw * 32) // pbits, (1 << slotbits) - 1)
        pal = [F(F(off) + F(F((big >> (k * pbits)) & ((1 << pbits) - 1)) * q))
               for k in range(n_pal)]   # FLOAT LAW: float32 the raw int before the multiply
        out.append('        <Item>')
        out.append('         <Type value="IndirectQuantizeFloat" />')
        out.append('         <Quantum value="%s" />' % fmt_num(q))
        out.append('         <Offset value="%s" />' % fmt_num(off))
        if len(pal) <= 10:
            out.append('         <Values>%s</Values>' % " ".join(fmt_num(v) for v in pal))
        else:
            self._emit_values(out, pal, "         ")
        out.append('         <Frames>')
        for i in range(0, len(raws), 10):
            out.append('          %s' % " ".join(str(r) for r in raws[i:i + 10]))
        out.append('         </Frames>')
        out.append('        </Item>')


def ycd_to_xml(path):
    # RSC7 VERSION GATE, read from the raw header BEFORE the container inflates (2026-08-10).
    # Four 00_base destruction .ycd are version 43, not 46, and the RSC7 reader dies inside
    # inflate on them ("inflated payload shorter than the declared system segment") long before
    # require_version could speak. The REFERENCE EXPORTER also declines them: each of the four
    # oracles is exactly 40 bytes - `<?xml version="1.0" encoding="UTF-8"?>` and NO root element
    # at all (hexdump-verified on all four). So the conformant output for a non-v46 .ycd is the
    # declaration alone. It is COUNTED, never silent: an operator sees the class in the run
    # summary, and if a version-43 file ever needs real content this counter is what surfaces it.
    if isinstance(path, str) and os.path.isfile(path):
        with open(path, 'rb') as _f:
            _hdr = _f.read(8)
        if declined_version(_hdr):
            return DECLINED_XML
    y = Ycd(path)
    out = ['<?xml version="1.0" encoding="UTF-8"?>', "<ClipDictionary>"]
    y.emit_clips(out)
    y.emit_anims(out)
    out.append("</ClipDictionary>")
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    scr = os.path.dirname(os.path.abspath(__file__))
    BIN = os.path.join(scr, "ycd_bins")
    ORC = r"B:\ClaudeCode_Projects\_UEFiveMTool\_Oracles\ycd"
    import json
    man = json.load(open(os.path.join(BIN, "manifest.json"), encoding="utf-8"))
    target = sys.argv[1] if len(sys.argv) > 1 else None
    for local, meta in sorted(man.items()):
        if target and target not in local:
            continue
        orc = os.path.join(ORC, meta["dest"].replace("ycd/", "").replace("/", os.sep), meta["file"])
        ref = open(orc, encoding="utf-8").read().replace("\r\n", "\n")
        try:
            got = ycd_to_xml(os.path.join(BIN, local))
        except Exception as e:
            print("ERROR %-50s %s" % (meta["file"], e)); continue
        gl, ol = got.split("\n"), ref.split("\n")
        # first divergence
        diff = None
        for j in range(min(len(gl), len(ol))):
            if gl[j] != ol[j]:
                diff = j; break
        if got == ref:
            print("PASS  %s" % meta["file"])
        else:
            print("DIFF@L%-4s %s" % (diff + 1 if diff is not None else "?", meta["file"]))
            if "-v" in sys.argv and diff is not None:
                print("   got: %r" % gl[diff])
                print("   orc: %r" % ol[diff])
