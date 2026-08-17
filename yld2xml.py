"""yld2xml - GTA V .yld (rage::clothDictionary / characterCloth, RSC7 v8) -> byte-identical
RAGE .yld.xml.

CLEAN-ROOM: derived from the oracle XML + game binary + our own quarry code only.

CONTAINER (RSC7 v8; all data in system segment) - pgDictionary shell (same as yed/yfd):
  sys+0x20 Hashes atArray ; sys+0x30 Data atArray (stride-8 tagged ptrs -> characterCloth item)

characterCloth item struct:
  +0x00 u64 vtable
  +0x20 tagged ptr -> Controller (clothController)
  +0x28 tagged ptr -> Bounds     (phBoundComposite root)
  +0x30 Unknown30 atArray : u32[] bone tags (count @+0x38)
  +0x50 Transform : 16 float32, row-major 4x4 (last row 0 0 0 0)
  (item carries NO Name field; the ITEM <Name> resolves the pgDictionary Hashes entry
  (sys+0x20) - falsified 2026-08-09 the old "XML Name == Controller.Name" claim:
  a_f_y_beach_01.yld stores hash joaat('accs_000_u') != joaat(controller string
  'a_f_y_beach_01') and the oracle spells accs_000_u for the Item, the controller string
  for <Controller><Name>. The claim held only while every witnessed dictionary hash
  equalled joaat(controller name).)

clothController struct:
  +0x10 ptr -> BridgeSimGfx      +0x20 ptr -> VerletCloth1
  +0x50 u32 Type                 +0x58 inline char[] Name
  +0x78 f32 Unknown78            +0x80 Indices atArray u16[]
  +0x90 Vertices atArray Vec4    +0xA0 f32 UnknownA0
  +0xB0 UnknownB0 atArray u32[]  +0xC0 BoneWeightsIndices atArray (stride 32)
  +0xDC f32 UnknownDC            +0xE0 BoneIDs atArray u32[]

BridgeSimGfx: +0x10 u32 VertexCount +0x14 u32 Unknown14 +0x18 u32 Unknown18
  +0x20 Unknown20 f32[]  +0x60 Unknown60 f32[]  +0xA0 UnknownA0 f32[]
  +0xE0 UnknownE0 u16[]  +0x128 Unknown128 arr (count@+0x130)

VerletCloth1: +0x10 BBMin Vec3 +0x20 BBMax Vec3 +0x3C u32 Unknown3C +0x4C u32 Unknown4C
  +0x50 f32 Unknown50 +0x70 Vertices2 atArray Vec4 +0x80 Vertices atArray Vec4
  +0xA8 f32 UnknownA8 +0xAC f32 UnknownAC +0xE8 u32 UnknownE8 +0xFA u16 UnknownFA
  +0x100 Constraints2 atArray (stride 16, SAME record schema - measured 2026-08-09 on
         a_f_y_beach_01 (88 items) + uppr_000_u (248 items); null/count-0 in every
         passing witness and the element is then OMITTED - null-vs-empty-but-allocated
         unwitnessed, they co-occur in the corpus)
  +0x110 Constraints atArray (stride 16) +0x148 u16 Unknown148 +0x158 f32 Unknown158
  (Unknown140 and Behaviour render as constant-empty elements)

Constraint record (16B): u16 Unknown0 | u16 Unknown2 | f32 Unknown4 | f32 Unknown8 | f32 UnknownC
BoneWeightsIndices record (32B): 4 f32 Weights | 4 u32 Index0..3
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ydr2xml import (Res, _bound_lines, _bound_deref, _bound_header_lines,     # noqa: E402
                     _bound_flags_text, BOUND_COMPOSITE_FLAG_BITS)
from meta2xml import fmt_num, esc, num_list, scalar_list, joaat  # noqa: E402


def _yld_bounds(r, off, ind, name):
    """phBoundComposite root for a .yld. Mirrors ydr2xml's composite branch, but the
    TypeAndIncludeFlags (CompositeFlags1/2) pointer lives at composite+0x88 here, not +0x90
    as in the ydr/yft lane (measured: yld +0x90 = 0, +0x88 -> a per-child u32,u32 array;
    the +0x80 pointer is the per-child AABB array). Children (primitives) delegate to the
    shared _bound_lines, which emits header-only for a Capsule."""
    S = r.sys
    inner = ind + " "
    L = ['%s<Bounds type="Composite">' % ind]
    L += _bound_header_lines(r, off, inner, name)
    n = r.u16(off + 0xA0)
    cb, co = _bound_deref(r, r.u32(off + 0x70), n * 8, "composite children", name)
    tb, to = _bound_deref(r, r.u32(off + 0x78), n * 64, "composite transforms", name)
    fb = fo = None
    fl_p = r.u32(off + 0x88)
    if fl_p:
        fb, fo = _bound_deref(r, fl_p, n * 8, "composite flags", name)
    L.append("%s<Children>" % inner)
    for i in range(n):
        cp = struct.unpack_from("<I", cb, co + i * 8)[0]
        if cp == 0:
            L.append('%s <Item type="None" />' % inner)
            continue
        _, ch = _bound_deref(r, cp, 0x70, "child %d" % i, name)
        ci2 = inner + "  "
        mv = struct.unpack_from("<16f", tb, to + i * 64)
        extra_i = ["%s<CompositeTransform>" % ci2]
        for rr in range(4):
            extra_i.append("%s %s %s %s %s" % (ci2, fmt_num(mv[rr * 4]), fmt_num(mv[rr * 4 + 1]),
                                               fmt_num(mv[rr * 4 + 2]), "1" if rr == 3 else "0"))
        extra_i.append("%s</CompositeTransform>" % ci2)
        if fb is not None:
            f1, f2 = struct.unpack_from("<II", fb, fo + i * 8)
            extra_i.append("%s<CompositeFlags1>%s</CompositeFlags1>" % (
                ci2, _bound_flags_text(f1, BOUND_COMPOSITE_FLAG_BITS, "CompositeFlags1", name)))
            extra_i.append("%s<CompositeFlags2>%s</CompositeFlags2>" % (
                ci2, _bound_flags_text(f2, BOUND_COMPOSITE_FLAG_BITS, "CompositeFlags2", name)))
        L += _bound_lines(r, ch, inner + " ", "Item", "%s child %d" % (name, i),
                          extra=extra_i, depth=1)
    L.append("%s</Children>" % inner)
    L.append("%s</Bounds>" % ind)
    return L


def _u16(S, o): return struct.unpack_from("<H", S, o)[0]
def _u32(S, o): return struct.unpack_from("<I", S, o)[0]
def _u64(S, o): return struct.unpack_from("<Q", S, o)[0]
def _f32(S, o): return struct.unpack_from("<f", S, o)[0]
def _arr(S, base): return (_u32(S, base) & 0x0FFFFFFF, _u16(S, base + 8))


def _floats(S, ptr, n): return [_f32(S, ptr + i * 4) for i in range(n)]
def _u16s(S, ptr, n): return [_u16(S, ptr + i * 2) for i in range(n)]
def _u32s(S, ptr, n): return [_u32(S, ptr + i * 4) for i in range(n)]


def _vec4_block(S, ptr, n, tag, ind):
    """Vec4 array rendered as 'x, y, z, w' comma-tuples, one per line at ind+1 (block if >1)."""
    rows = [", ".join(fmt_num(_f32(S, ptr + i * 16 + j * 4)) for j in range(4)) for i in range(n)]
    if len(rows) == 1:
        return ["%s<%s>%s</%s>" % (ind, tag, rows[0], tag)]
    return ["%s<%s>" % (ind, tag)] + ["%s %s" % (ind, r) for r in rows] + ["%s</%s>" % (ind, tag)]


def yld_to_xml(path, names=None):
    r = path if hasattr(path, 'sys') else Res(path)
    r.require_version(8, "yld")
    S = r.sys
    hp, hc = _arr(S, 0x20)                             # pgDictionary Hashes (parallel)
    dp, dc = _arr(S, 0x30)

    out = ['<?xml version="1.0" encoding="UTF-8"?>', "<ClothDictionary>"]
    for it in range(dc):
        b = _u64(S, dp + it * 8) & 0x0FFFFFFF          # item struct
        ctrl = _u32(S, b + 0x20) & 0x0FFFFFFF
        name = S[ctrl + 0x58: S.find(b"\x00", ctrl + 0x58)].decode("latin-1")
        # ITEM name = the dictionary entry hash resolved (see header - the controller
        # string is a DIFFERENT field and only coincidentally equal in most witnesses)
        ihash = _u32(S, hp + it * 4) if it < hc else 0
        if ihash == joaat(name.lower()):
            iname = name
        elif names and ihash in names:
            iname = names[ihash]
        else:
            iname = 'hash_%08X' % ihash

        out.append(" <Item>")
        out.append("  <Name>%s</Name>" % esc(iname))
        # Transform: 4x4 row-major, 4 per line at 3-space content
        tf = _floats(S, b + 0x50, 16)
        out.append("  <Transform>")
        for rrow in range(4):
            out.append("   %s" % " ".join(fmt_num(tf[rrow * 4 + c]) for c in range(4)))
        out.append("  </Transform>")
        # ⭐ Unknown10 (item) - ADDED 2026-08-17. This array had NO XML TAG AT ALL, and it was
        # **82.4% of this lane's entire export loss**: 150,752 B of the 183,020 B that
        # `tools/step2_yld.py` charged ABSENT at population (61/61 files). The binary round-trip
        # could not see it - `yld_write` carries 0% and scores 61/61 - because the writer READS
        # the array; only the emitter dropped it.
        # MEASURED before choosing a type, not assumed: 9 of 61 items carry a live array, 9,422
        # records of 16 B, and every sampled record decodes as FOUR PLAUSIBLE float32
        # (e.g. -0.185, 0.2641, 0.2666, 0.0) - never as sane u32. Per-item counts
        # 226/260/318/352/354/1700/1872/2000/2340.
        # ⚠ THE NAME IS A PLACEHOLDER and follows this module's existing convention
        # (Unknown30/Unknown14/Unknown78). Nothing here claims to know what the field IS - it is
        # emitted so the value is not lost. Naming it needs an invariant test.
        # ⭐ Many rows are all-negative-zero, so this tag depends on the 2026-08-16 fmt_num fix
        # that stopped spelling -0.0 as "0"; without it these would export as +0.0.
        a10p, a10c = _arr(S, b + 0x10)
        if a10c:
            out.append("  <Unknown10>")
            for _i in range(a10c):
                _v = _floats(S, a10p + _i * 16, 4)
                out.append("   %s" % " ".join(fmt_num(_x) for _x in _v))
            out.append("  </Unknown10>")
        else:
            out.append("  <Unknown10 />")

        # Unknown30 (item) : u32[] inline
        u30p, u30c = _arr(S, b + 0x30)
        out += scalar_list("Unknown30", _u32s(S, u30p, u30c), "  ")

        # ---------------- Controller ----------------
        out.append("  <Controller>")
        out.append("   <Name>%s</Name>" % esc(name))
        out.append('   <Type value="%d" />' % _u32(S, ctrl + 0x50))
        out.append('   <Unknown78 value="%s" />' % fmt_num(_f32(S, ctrl + 0x78)))

        # BridgeSimGfx
        bg = _u32(S, ctrl + 0x10) & 0x0FFFFFFF
        out.append("   <BridgeSimGfx>")
        out.append('    <VertexCount value="%d" />' % _u32(S, bg + 0x10))
        out.append('    <Unknown14 value="%d" />' % _u32(S, bg + 0x14))
        out.append('    <Unknown18 value="%d" />' % _u32(S, bg + 0x18))
        for tag, ao in (("Unknown20", 0x20), ("Unknown60", 0x60), ("UnknownA0", 0xA0)):
            p, c = _arr(S, bg + ao)
            out += num_list(tag, _floats(S, p, c), "    ")
        ep, ec = _arr(S, bg + 0xE0)
        out += scalar_list("UnknownE0", _u16s(S, ep, ec), "    ")
        p128, c128 = _arr(S, bg + 0x128)
        out += scalar_list("Unknown128", _u32s(S, p128, c128), "    ")
        out.append("   </BridgeSimGfx>")

        # VerletCloth1
        vc = _u32(S, ctrl + 0x20) & 0x0FFFFFFF
        out.append("   <VerletCloth1>")
        for tag, vo in (("BBMin", 0x10), ("BBMax", 0x20)):
            out.append('    <%s x="%s" y="%s" z="%s" />' % (
                tag, fmt_num(_f32(S, vc + vo)), fmt_num(_f32(S, vc + vo + 4)),
                fmt_num(_f32(S, vc + vo + 8))))
        out.append('    <Unknown3C value="%d" />' % _u32(S, vc + 0x3C))
        out.append('    <Unknown4C value="%d" />' % _u32(S, vc + 0x4C))
        out.append('    <Unknown50 value="%s" />' % fmt_num(_f32(S, vc + 0x50)))
        out.append('    <UnknownA8 value="%s" />' % fmt_num(_f32(S, vc + 0xA8)))
        out.append('    <UnknownAC value="%s" />' % fmt_num(_f32(S, vc + 0xAC)))
        out.append('    <UnknownE8 value="%d" />' % _u32(S, vc + 0xE8))
        out.append('    <UnknownFA value="%d" />' % _u16(S, vc + 0xFA))
        out.append('    <Unknown148 value="%d" />' % _u16(S, vc + 0x148))
        out.append('    <Unknown158 value="%s" />' % fmt_num(_f32(S, vc + 0x158)))
        out.append("    <Unknown140 />")
        out.append("    <Behaviour />")
        vp, vcnt = _arr(S, vc + 0x80)          # XML Vertices  (memory +0x80)
        out += _vec4_block(S, vp, vcnt, "Vertices", "    ")
        v2p, v2cnt = _arr(S, vc + 0x70)         # XML Vertices2 (memory +0x70)
        out += _vec4_block(S, v2p, v2cnt, "Vertices2", "    ")
        def _constraint_block(tag, base_off):
            p, cnt = _arr(S, vc + base_off)
            if base_off == 0x100 and (p == 0 or cnt == 0):
                return []           # Constraints2 OMITTED when null/empty (oracle-witnessed)
            blk = ["    <%s>" % tag]
            for k in range(cnt):
                o = p + k * 16
                blk.append("     <Item>")
                blk.append('      <Unknown0 value="%d" />' % _u16(S, o))
                blk.append('      <Unknown2 value="%d" />' % _u16(S, o + 2))
                blk.append('      <Unknown4 value="%s" />' % fmt_num(_f32(S, o + 4)))
                blk.append('      <Unknown8 value="%s" />' % fmt_num(_f32(S, o + 8)))
                blk.append('      <UnknownC value="%s" />' % fmt_num(_f32(S, o + 12)))
                blk.append("     </Item>")
            blk.append("    </%s>" % tag)
            return blk
        out += _constraint_block("Constraints", 0x110)
        out += _constraint_block("Constraints2", 0x100)   # second array @+0x100, after Constraints
        out.append("   </VerletCloth1>")

        # controller tail
        out.append('   <UnknownA0 value="%s" />' % fmt_num(_f32(S, ctrl + 0xA0)))
        out.append('   <UnknownDC value="%s" />' % fmt_num(_f32(S, ctrl + 0xDC)))
        cvp, cvc = _arr(S, ctrl + 0x90)
        out += _vec4_block(S, cvp, cvc, "Vertices", "   ")
        ip, ic = _arr(S, ctrl + 0x80)
        out += scalar_list("Indices", _u16s(S, ip, ic), "   ")
        bp, bc = _arr(S, ctrl + 0xB0)
        out += scalar_list("UnknownB0", _u32s(S, bp, bc), "   ")
        bidp, bidc = _arr(S, ctrl + 0xE0)
        out += scalar_list("BoneIDs", _u32s(S, bidp, bidc), "   ")
        # BoneWeightsIndices
        wp, wc = _arr(S, ctrl + 0xC0)
        out.append("   <BoneWeightsIndices>")
        for k in range(wc):
            o = wp + k * 32
            out.append("    <Item>")
            out.append('     <Weights x="%s" y="%s" z="%s" w="%s" />' % (
                fmt_num(_f32(S, o)), fmt_num(_f32(S, o + 4)),
                fmt_num(_f32(S, o + 8)), fmt_num(_f32(S, o + 12))))
            for gi in range(4):
                out.append('     <Index%d value="%d" />' % (gi, _u32(S, o + 16 + gi * 4)))
            out.append("    </Item>")
        out.append("   </BoneWeightsIndices>")
        out.append("  </Controller>")

        # ---------------- Bounds (phBoundComposite; flags @ +0x88 in the yld lane) --------
        _, boff = _bound_deref(r, _u32(S, b + 0x28), 0x70, "cloth bounds", name)
        out += _yld_bounds(r, boff, "  ", name)

        out.append(" </Item>")
    out.append("</ClothDictionary>")
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    scr = os.path.dirname(os.path.abspath(__file__))
    binp = os.path.join(scr, "dict_bins", "accs_000_u.yld")
    orc = r"B:\ClaudeCode_Projects\_UEFiveMTool\_Oracles\yld\00_base\accs_000_u.yld.xml"
    got = yld_to_xml(binp)
    ref = open(orc, encoding="utf-8").read().replace("\r\n", "\n")
    if got == ref:
        print("PASS  accs_000_u.yld  (%d bytes, byte-identical)" % len(got))
    else:
        gl, ol = got.split("\n"), ref.split("\n")
        print("FAIL  got %d lines / oracle %d lines" % (len(gl), len(ol)))
        for j in range(min(len(gl), len(ol))):
            if gl[j] != ol[j]:
                print("  first diff at line %d:\n    got: %r\n    orc: %r" % (j + 1, gl[j], ol[j]))
                break
        open(os.path.join(scr, "yld_got.xml"), "w", encoding="utf-8", newline="\n").write(got)
