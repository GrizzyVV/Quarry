"""yed2xml - GTA V .yed (rage::crExpressionDictionary, RSC7 v25) -> byte-identical RAGE .yed.xml.

CLEAN-ROOM: derived from the oracle XML + game binary + our own quarry code only.

CONTAINER (RSC7 v25; all data in the system segment, gfx empty) - pgDictionary shell:
  sys+0x00  u64 vtable
  sys+0x08  u32 tagged ptr  (parent dict; unused)
  sys+0x18  u32 usageCount (=1)
  sys+0x20  Hashes atArray : ptr @+0x20, count u16 @+0x28   (u32 name-hashes, sorted asc)
  sys+0x30  Data   atArray : ptr @+0x30, count u16 @+0x38   (stride-8 tagged ptrs -> item)
  XML item order == DATA-array order (NOT hash order); the Name is stored in each item
  as a string, so no hash table is needed.

crExpression item struct:
  +0x00 u64 vtable
  +0x20 Streams atArray : ptr @+0x20, count u16 @+0x28  (stride-8 tagged ptrs -> stream)
  +0x30 Tracks  atArray : ptr @+0x30, count u16 @+0x38  (stride-4 records)
  +0x60 u32 tagged ptr -> Name string ("pack:/....expr")
  +0x70 u32  (=1)            not emitted
  +0x74 u32  Signature
  +0x78 u32  (per-item int)  not emitted
  +0x7c u32  Unk7C

Track record (4 bytes): u16 BoneId | u8 Track | u8 (Format = &0x7F, UnkFlag = &0x80)

crExpressionStream struct:
  +0x00 u32 name hash (emitted hash_%08X)
  +0x04 u32 vecPoolBytes  (= 16 * #PushVector)
  +0x08 u32 mainPoolBytes
  +0x0c u16 instruction count
  +0x0e u16 Depth
  +0x10 vector pool (vecPoolBytes) : 16-byte xyzw floats, one per PushVector, in order
        main pool  (mainPoolBytes) : per-instruction operands, in order
        opcode array (count bytes) : 1 opcode byte per instruction
Operand kinds by opcode:
  track record (8B: u16 TrackIndex, u16 BoneId, u8 Track, u8 Format, u8 ComponentIndex,
                u8 UseDefaults) - TrackGetOffsetComp/TrackSet/TrackSetComp/TrackSetOffset
  float  (4B)  - PushFloat
  vector (16B, from vector pool) - PushVector
  jump   (12B: 3 u32, only the 3rd = InstructionOffset is emitted) - Jump/JumpIfTrue
  none   - all others
"""
import os
import struct
import sys

sys.path.insert(0, r"B:\ClaudeCode_Projects\_UEFiveMTool\quarry")
from ydr2xml import Res                       # noqa: E402  (RSC7 container reader)
from meta2xml import fmt_num, esc             # noqa: E402  (float-text law, XML escape)

# opcode byte -> (TypeName, operand-kind). Derived by aligning every stream's opcode array
# against the oracle's instruction-type sequence. Original 24: ig_lestercrest (5 streams /
# 471 opcodes, 0 conflicts). 2026-08-09 EXTENSION (+9): the SAME alignment over ALL 24
# oracle files - 39 streams / 49,491 instructions, every vote unanimous (incl. re-votes of
# the original 24), and the pool accounting balanced EXACTLY on 39/39 streams under the
# operand rules below (168,346 float spellings reproduced in the derivation harness).
# ⚠ The one-file derivation base was the trap: ig_lestercrest simply never uses these 9.
OPS = {
    0x00: ("End", None),          0x01: ("Pop", None),
    0x03: ("Push0", None),        0x04: ("Push1", None),
    0x05: ("PushFloat", "f"),     0x07: ("TrackGetComp", "t"),
    0x09: ("TrackGetOffsetComp", "t"),
    0x0b: ("PushVector", "v"),    0x0e: ("DefineSpring", "s"),
    0x10: ("VectorNeg", None),
    0x1d: ("VectorDeg2Rad", None),0x1e: ("VectorRad2Deg", None),
    0x21: ("FromEuler", None),    0x26: ("TrackSet", "t"),
    0x27: ("TrackSetComp", "t"),  0x28: ("TrackSetOffset", "t"),
    0x2b: ("Jump", "j"),          0x2c: ("JumpIfTrue", "j"),
    0x2e: ("VectorAdd", None),    0x2f: ("VectorSub", None),
    0x30: ("VectorMul", None),    0x31: ("VectorMin", None),
    0x32: ("VectorMax", None),    0x33: ("QuatMul", None),
    0x35: ("VectorGreaterThan", None), 0x36: ("VectorLessThan", None),
    0x37: ("VectorGreaterEqual", None), 0x38: ("VectorLessEqual", None),
    0x39: ("VectorClamp", None),  0x3b: ("VectorMad", None),
    0x3d: ("ToVector", None),
    0x44: ("BlendVector", "b"),   0x45: ("BlendQuaternion", "b"),
}
# main-pool bytes; "v" consumes 16 from the vector pool, "s" (spring) a fixed 176 (11x16B
# slots), "b" (blend) a SELF-SIZED vector-pool payload (u32 total-bytes header at the
# cursor). vecPoolBytes = 16*#PushVector + 176*#DefineSpring + sum(blend payloads) -
# the old "16 x #PushVector" doc line was the single-file view.
OPSIZE = {"f": 4, "t": 8, "j": 12}


def _u16(S, o): return struct.unpack_from("<H", S, o)[0]
def _u32(S, o): return struct.unpack_from("<I", S, o)[0]
def _u64(S, o): return struct.unpack_from("<Q", S, o)[0]
def _f32(S, o): return struct.unpack_from("<f", S, o)[0]
def _arr(S, base): return (_u32(S, base) & 0x0FFFFFFF, _u16(S, base + 8))   # (ptr, count)


def _spring_operand(S, vo, out, ind):
    """DefineSpring: 176 vector-pool bytes = 11 16-byte slots (derived 2026-08-09, 14
    witnesses). Slots 0-8: Vector01..09 (f32 x,y,z @+0/4/8; u16 a @+12, u16 b @+14).
    Slot 9: Gravity xyz + u16 BoneTag @+12 (+14 = 0 in all 14). Slot 10: u32 BoneTrackRot,
    u32 BoneTrackPos (rest 0 in all 14). XML: vectors, Gravity, Ushort pairs, tags."""
    for i in range(9):
        o = vo + i * 16
        out.append('%s<Vector%02d x="%s" y="%s" z="%s" />'
                   % (ind, i + 1, fmt_num(_f32(S, o)), fmt_num(_f32(S, o + 4)),
                      fmt_num(_f32(S, o + 8))))
    g = vo + 9 * 16
    out.append('%s<Gravity x="%s" y="%s" z="%s" />'
               % (ind, fmt_num(_f32(S, g)), fmt_num(_f32(S, g + 4)), fmt_num(_f32(S, g + 8))))
    for i in range(9):
        o = vo + i * 16
        out.append('%s<Ushort%02da value="%d" />' % (ind, i + 1, _u16(S, o + 12)))
        out.append('%s<Ushort%02db value="%d" />' % (ind, i + 1, _u16(S, o + 14)))
    out.append('%s<BoneTag value="%d" />' % (ind, _u16(S, g + 12)))
    t = vo + 10 * 16
    out.append('%s<BoneTrackRot value="%d" />' % (ind, _u32(S, t)))
    out.append('%s<BoneTrackPos value="%d" />' % (ind, _u32(S, t + 4)))


def _blend_operand(S, vo, out, ind):
    """BlendVector/BlendQuaternion: self-sized vector-pool payload (derived 2026-08-09,
    484 blends, size law verified on every one). Header 16B: u32 payloadBytes (total incl.
    header), u32 numSources, u32 numSourceWeights, u32 0 (REFUSED if nonzero - unwitnessed).
    Source records @+16: nsrc x (u16 TrackIndex, u16 componentByteOffset; ComponentIndex =
    offset/4), area padded to 16. Float planes in 4-source blocks: per weight-set w:
    W.X W.Y W.Z O.X O.Y O.Z planes (+T.X T.Y T.Z when w < nsw-1), one 16B float4 per
    plane, lane = source % 4. Returns consumed byte count."""
    payload = _u32(S, vo)
    nsrc = _u32(S, vo + 4)
    nsw = _u32(S, vo + 8)
    if _u32(S, vo + 12) != 0:
        raise ValueError("blend header dword3 nonzero (unwitnessed shape) @0x%x" % vo)
    src0 = vo + 16
    src_area = ((nsrc * 4 + 15) // 16) * 16
    planes0 = src0 + src_area
    per_block = 9 * nsw - 3                     # planes per 4-source block

    def plane(block, pidx, lane):
        return _f32(S, planes0 + (block * per_block + pidx) * 16 + lane * 4)

    out.append('%s<NumSourceWeights value="%d" />' % (ind, nsw))
    out.append('%s<Sources>' % ind)
    for s in range(nsrc):
        so = src0 + s * 4
        block, lane = s // 4, s % 4
        out.append('%s <Item>' % ind)
        out.append('%s  <TrackIndex value="%d" />' % (ind, _u16(S, so)))
        out.append('%s  <ComponentIndex value="%d" />' % (ind, _u16(S, so + 2) // 4))
        for ax, axoff in (("X", 0), ("Y", 1), ("Z", 2)):
            w_vals = [plane(block, 9 * w + axoff, lane) for w in range(nsw)]
            o_vals = [plane(block, 9 * w + 3 + axoff, lane) for w in range(nsw)]
            t_vals = [plane(block, 9 * w + 6 + axoff, lane) for w in range(nsw - 1)]
            out.append('%s  <%s>' % (ind, ax))
            out.append('%s   <Weights>%s</Weights>' % (ind, ' '.join(fmt_num(v) for v in w_vals)))
            out.append('%s   <Offsets>%s</Offsets>' % (ind, ' '.join(fmt_num(v) for v in o_vals)))
            out.append('%s   <Thresholds>%s</Thresholds>' % (ind, ' '.join(fmt_num(v) for v in t_vals))
                       if t_vals else '%s   <Thresholds />' % ind)
            out.append('%s  </%s>' % (ind, ax))
        out.append('%s </Item>' % ind)
    out.append('%s</Sources>' % ind)
    return payload


def _track_operand(S, o, out, ind):
    """Emit the shared 6-field track record used by the Track* instructions."""
    ti = _u16(S, o); bone = _u16(S, o + 2)
    trk = S[o + 4]; fmt = S[o + 5]; comp = S[o + 6]; usedef = S[o + 7]
    out.append('%s<TrackIndex value="%d" />' % (ind, ti))
    out.append('%s<BoneId value="%d" />' % (ind, bone))
    out.append('%s<Track value="%d" />' % (ind, trk))
    out.append('%s<Format value="%d" />' % (ind, fmt))
    out.append('%s<ComponentIndex value="%d" />' % (ind, comp))
    out.append('%s<UseDefaults value="%s" />' % (ind, "True" if usedef else "False"))


def yed_to_xml(path):
    r = path if hasattr(path, 'sys') else Res(path)
    r.require_version(25, "yed")
    S = r.sys
    dp, dc = _arr(S, 0x30)                      # data array (item pointers), XML order

    out = ['<?xml version="1.0" encoding="UTF-8"?>', "<ExpressionDictionary>"]
    for i in range(dc):
        b = _u64(S, dp + i * 8) & 0x0FFFFFFF    # item struct
        name = r.cstr(_u32(S, b + 0x60))
        sig = _u32(S, b + 0x74)
        unk7c = _u32(S, b + 0x7c)
        out.append(" <Item>")
        out.append("  <Name>%s</Name>" % esc(name))
        out.append('  <Signature value="%d" />' % sig)
        out.append('  <Unk7C value="%d" />' % unk7c)

        # ---- Tracks (stride-4 records) ----
        tp, tc = _arr(S, b + 0x30)
        out.append("  <Tracks>")
        for k in range(tc):
            o = tp + k * 4
            bone = _u16(S, o); trk = S[o + 2]; fb = S[o + 3]
            out.append("   <Item>")
            out.append('    <BoneId value="%d" />' % bone)
            out.append('    <Track value="%d" />' % trk)
            out.append('    <Format value="%d" />' % (fb & 0x7F))
            out.append('    <UnkFlag value="%s" />' % ("True" if fb & 0x80 else "False"))
            out.append("   </Item>")
        out.append("  </Tracks>")

        # ---- Streams (stride-8 pointers to bytecode structs) ----
        sp, sc = _arr(S, b + 0x20)
        out.append("  <Streams>")
        for k in range(sc):
            s0 = _u64(S, sp + k * 8) & 0x0FFFFFFF
            name_hash = _u32(S, s0)
            vbytes = _u32(S, s0 + 0x04)
            mbytes = _u32(S, s0 + 0x08)
            cnt = _u16(S, s0 + 0x0c)
            depth = _u16(S, s0 + 0x0e)
            vec_off = s0 + 0x10                 # vector pool
            main_off = vec_off + vbytes         # main operand pool
            op_off = main_off + mbytes          # opcode array
            out.append("   <Item>")
            out.append("    <Name>hash_%08X</Name>" % name_hash)
            out.append('    <Depth value="%d" />' % depth)
            out.append("    <Instructions>")
            mo = main_off                       # cursor into main pool
            vo = vec_off                        # cursor into vector pool
            for j in range(cnt):
                code = S[op_off + j]
                if code not in OPS:
                    # the file identifier must be Res-safe: os.path.basename(path) raised
                    # TypeError when the dispatch passed a Res, BURYING the real refusal
                    # behind an opaque error (measured 2026-08-09 - all 23 stage-D yed
                    # rows reported the TypeError instead of the opcode)
                    fid = (path if isinstance(path, str)
                           else getattr(path, 'name', None) or type(path).__name__)
                    raise ValueError("unknown expression opcode 0x%02x (%s instr %d)"
                                     % (code, os.path.basename(str(fid)), j))
                tname, kind = OPS[code]
                if kind is None:
                    out.append('     <Item type="%s" />' % tname)
                    continue
                out.append('     <Item type="%s">' % tname)
                ind = "      "
                if kind == "t":
                    _track_operand(S, mo, out, ind); mo += 8
                elif kind == "f":
                    out.append('%s<Value value="%s" />' % (ind, fmt_num(_f32(S, mo)))); mo += 4
                elif kind == "v":
                    x = fmt_num(_f32(S, vo)); y = fmt_num(_f32(S, vo + 4))
                    z = fmt_num(_f32(S, vo + 8)); w = fmt_num(_f32(S, vo + 12))
                    out.append('%s<Value x="%s" y="%s" z="%s" w="%s" />' % (ind, x, y, z, w))
                    vo += 16
                elif kind == "j":
                    ioff = _u32(S, mo + 8)      # 3rd u32 = InstructionOffset
                    out.append('%s<InstructionOffset value="%d" />' % (ind, ioff)); mo += 12
                elif kind == "s":
                    _spring_operand(S, vo, out, ind); vo += 176
                elif kind == "b":
                    vo += _blend_operand(S, vo, out, ind)
                out.append("     </Item>")
            # self-check: operands must exactly fill both pools
            if mo != main_off + mbytes:
                raise ValueError("main pool underrun %d/%d (%s)" % (mo - main_off, mbytes, path))
            if vo != vec_off + vbytes:
                raise ValueError("vector pool underrun %d/%d (%s)" % (vo - vec_off, vbytes, path))
            out.append("    </Instructions>")
            out.append("   </Item>")
        out.append("  </Streams>")
        out.append(" </Item>")
    out.append("</ExpressionDictionary>")
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    scr = os.path.dirname(os.path.abspath(__file__))
    binp = os.path.join(scr, "dict_bins", "ig_lestercrest.yed")
    orc = r"B:\ClaudeCode_Projects\_UEFiveMTool\_Oracles\yed\00_base\ig_lestercrest.yed.xml"
    got = yed_to_xml(binp)
    ref = open(orc, encoding="utf-8").read().replace("\r\n", "\n")
    if got == ref:
        print("PASS  ig_lestercrest.yed  (%d bytes, byte-identical)" % len(got))
    else:
        gl, ol = got.split("\n"), ref.split("\n")
        print("FAIL  got %d lines / oracle %d lines" % (len(gl), len(ol)))
        for j in range(min(len(gl), len(ol))):
            if gl[j] != ol[j]:
                print("  first diff at line %d:\n    got: %r\n    orc: %r" % (j + 1, gl[j], ol[j]))
                break
        open(os.path.join(scr, "yed_got.xml"), "w", encoding="utf-8", newline="\n").write(got)
