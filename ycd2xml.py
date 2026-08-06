r"""ycd2xml - GTA V .ycd (rage::crClipDictionary, RSC7 v46) -> RAGE .ycd.xml.

CLEAN-ROOM: derived from oracle XML + game binary + our own quarry code only.

STATUS (measured against all 10 oracles):
  * SHELL = 100% byte-identical: container, both dictionaries, both clip types,
    Properties/Tags/Attributes, animation headers, BoneIds, sequence Hash+FrameCount.
    Every file's first divergence is at the SequenceData channel body.
  * QuantizeFloat channel body FULLY DECODED (verify_quant.py: 9/9 channels byte-exact).
  * Remaining GAP = the per-item channel-TYPE/layout table (which pooled channels group
    into each SequenceData <Item>) + IndirectQuantizeFloat palette-count/Frames packing.
    See emit_sequence() and the CHANNEL notes below.

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
  <Hash> = name-stem = Name[6:-5] ; <AnimationHash> = key of the referenced crAnimation.
crProperty / crTag:  +0x18 NameHash ; +0x20 Attributes atArray(ptr,count@+0x28) ; +0x38 UnkHash
  crTag also: +0x40 StartPhase f32 ; +0x44 EndPhase f32
crPropertyAttribute: +0x08 Type (2=Int,6=Vector3,8=Vector4,1=Float) ; +0x18 NameHash ; +0x20 Value
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
    (tail) channel-count table @end: u16 numStaticQuat,numStaticVec3,numStaticFloat,...
IndirectQuantizeFloat descriptor (24B): u32=2, u32 paletteBits, u32 indexBits,
    f32 Quantum, f32 Offset, u32 packedPalette (little-palette values packed paletteBits each,
    value=Offset+raw*Quantum).  Frames = per-frame indexBits index into the palette. GAP: the
    palette-entry count and the Frames bit-packing offset are not yet pinned.
"""
import os
import struct
import sys

sys.path.insert(0, r"B:\ClaudeCode_Projects\_UEFiveMTool\quarry")
from ydr2xml import Res                 # noqa: E402  (RSC7 container reader)
from meta2xml import fmt_num, esc, joaat  # noqa: E402


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


ATTR_TYPE = {2: "Int", 6: "Vector3", 8: "Vector4", 1: "Float"}


class Ycd:
    def __init__(self, path):
        self.r = Res(path)
        self.r.require_version(46, "ycd")
        self.S = self.r.sys
        S = self.S
        # ---- dictionaries ----
        self.clips_bp = P(u32(S, 0x28)); self.clips_n = u16(S, 0x30)   # inline atMap
        aobj = P(u32(S, 0x18))
        self.anims_bp = P(u32(S, aobj + 0x18)); self.anims_n = u16(S, aobj + 0x20)
        self.a2k = {av: k for k, av in atmap(S, self.anims_bp, self.anims_n)}  # anim ptr -> hash
        # ---- name dictionary (for reversible <Hash>) built from clip name-stems ----
        self.names = {}
        for _, cv in atmap(S, self.clips_bp, self.clips_n):
            nm = cstr(S, P(u32(S, cv + 0x18)))          # "pack:/<stem>.clip"
            stem = nm[6:-5] if nm.startswith("pack:/") and nm.endswith(".clip") else nm
            self.names[joaat(stem)] = stem

    def hstr(self, h):
        return self.names.get(h, "hash_%08X" % h)

    # ---------------------------------------------------------------- clips
    def emit_clips(self, out):
        S = self.S
        out.append(" <Clips>")
        for _, cv in atmap(S, self.clips_bp, self.clips_n):
            self.emit_clip(out, cv)
        out.append(" </Clips>")

    def emit_clip(self, out, cv):
        S = self.S
        typ = u32(S, cv + 0x10)                          # 1=Animation 2=AnimationList
        name = cstr(S, P(u32(S, cv + 0x18)))
        stem = name[6:-5] if name.startswith("pack:/") and name.endswith(".clip") else name
        out.append("  <Item>")
        out.append("   <Hash>%s</Hash>" % esc(stem))
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
            tn = ATTR_TYPE.get(t, "type%d" % t)
            out.append("      <Item>")
            out.append("       <NameHash>%s</NameHash>" % self.hstr(nh))
            out.append('       <Type value="%s" />' % tn)
            if tn == "Int":
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
        out.append(" <Animations>")
        for key, av in atmap(S, self.anims_bp, self.anims_n):
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
        S = self.S
        out.append("    <Item>")
        out.append("     <Hash>%s</Hash>" % self.hstr(u32(S, seq)))
        out.append('     <FrameCount value="%d" />' % u16(S, seq + 0x16))
        # ---- SequenceData: shell closes here; the per-item channel-TYPE table is the
        #      declared GAP.  The channel BODIES are decodable (static pools + the verified
        #      decode_quantize below), but assigning pooled channels to <Item>s needs the
        #      seq-tail type table which is not yet pinned. ----
        out.append("     <SequenceData>")
        out.append("      <!-- CHANNEL DATA UNPINNED: per-item channel-type table -->")
        out.append("     </SequenceData>")
        out.append("    </Item>")

    @staticmethod
    def decode_quantize(S, packed, framecount, chans):
        """VERIFIED (9/9 byte-exact on compactgl). `chans` = [(numBits,Quantum,Offset), ...] in
        descriptor order.  Frame-major, each frame DWORD-aligned; LSB-first bitstream.
        Returns [ [f32 value per frame] per channel ]."""
        from meta2xml import f32 as _f32
        framebits = ((sum(c[0] for c in chans) + 31) // 32) * 32
        out = [[] for _ in chans]
        for fr in range(framecount):
            bit = fr * framebits
            for ci, (nb, q, off) in enumerate(chans):
                raw = 0
                for i in range(nb):
                    pos = bit + i
                    raw |= ((S[packed + (pos >> 3)] >> (pos & 7)) & 1) << i
                bit += nb
                out[ci].append(_f32(off + raw * q))
        return out


def ycd_to_xml(path):
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
