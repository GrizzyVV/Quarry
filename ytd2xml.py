"""ytd2xml - binary .ytd (RSC7 v13, pgDictionary<grcTexture>) -> RAGE interchange
`<TextureDictionary>` XML + the pixel payload, ready for RUDE's `ImportYtd`.

WHY BOTH XML AND PIXELS: `ImportYtd(XmlPath, PixelFolder, DestFolder)` reads the XML for the
per-texture SEMANTICS (name + Usage, which is what a generic importer cannot infer) and the
pixels from a sibling folder. So a converted dictionary is two artifacts:

    <stem>.ytd.xml          the dictionary
    <stem>/<texture>.dds    the pixel payload, mips intact, byte-exact from the archive
    <stem>/<texture>.png    only with --png: decoded, which is what ImportYtd loads today

DDS is always written because it is a pure repackage - the archive's blocks with a 128-byte
header in front, no decode, no dependency, no loss. PNG needs a block decoder and is therefore
optional; when `texture2ddecoder` + `Pillow` are absent, the DDS still lands and the folder is
complete for any other consumer.

FIELD MAP - measured, not assumed. grcTexture (0x90 bytes), offsets confirmed two ways: against
RUDE's own in-game-validated `ExportYtdBinary` writer, and by decoding 1,199 real archive files.
    +0x00 VFT   +0x28 name*   +0x30 refcount
    +0x40 packed: bits 0..4 = USAGE, bits 5..29 = the UsageFlags symbols (USAGE_FLAG_BITS)
    +0x50 width(u16)  +0x52 height(u16)  +0x54 depth(u16)  +0x56 stride(u16)
    +0x58 format (D3DFMT enum, or a FourCC when > 0x1000000)   +0x5d mip count(u8)
    +0x70 pixel data* (graphics segment)
⛔ THE +0x40 FIELD IS NOT A LENGTH, and this map used to say bits 8..27 held "allocated pixel
bytes / 256". FALSIFIED 2026-08-06 on its own terms: one dword, 0x2000AC14, is carried by
128x64 mips=8, 128x128 mips=4 AND 256x128 mips=4 textures in the oracle set - three different
payload sizes, one value - and 9 of the 54 distinct dwords are similarly many-to-one. The bits
are the UsageFlags ladder, which the 224/224 oracle-string agreement below independently pins.
There is NO stored pixel-data length anywhere in grcTexture: the length is COMPUTED, and
`level_sizes` is the computation (237/237 exact against the oracle sidecars).
Dictionary header: +0x20 hash array*, +0x28 (count<<16)|count, +0x30 pointer array*.

⚠ The USAGE TABLE BELOW IS DERIVED FROM MEASUREMENT and covers only codes actually observed.
An unobserved code emits UNKNOWN rather than a guessed enum name - a wrong Usage silently
mis-authors a normal map as sRGB colour, which is worse than an honest UNKNOWN. Extend the
table by measuring against real files, never by assuming.
"""
import argparse
import collections
import os
import struct
import sys

from ydr2xml import Res, esc

# ---------------------------------------------------------------- pixel formats
# fourcc/enum -> (interchange <Format> string, bytes per 4x4 block or None, bytes per pixel)
BLOCK_FORMATS = {
    b"DXT1": ("D3DFMT_DXT1", 8),
    b"DXT3": ("D3DFMT_DXT3", 16),
    b"DXT5": ("D3DFMT_DXT5", 16),
    b"ATI1": ("D3DFMT_ATI1", 8),
    b"ATI2": ("D3DFMT_ATI2", 16),
    b"BC4U": ("D3DFMT_ATI1", 8),
    b"BC5U": ("D3DFMT_ATI2", 16),
    b"BC7 ": ("D3DFMT_BC7", 16),
}
# BC7 has NO legacy DDPF_FOURCC code - a .dds carrying b"BC7 " is unreadable by standard tools.
# It must be written with the DX10 extension header (fourCC "DX10" + DDS_HEADER_DXT10).
DXGI_BY_FOURCC = {b"BC7 ": 98}          # DXGI_FORMAT_BC7_UNORM
# D3DFMT enum values for the uncompressed formats the corpus actually contains
LINEAR_FORMATS = {
    21: ("D3DFMT_A8R8G8B8", 4),
    22: ("D3DFMT_X8R8G8B8", 4),
    25: ("D3DFMT_A1R5G5B5", 2),   # 2026-08-02, see note
    28: ("D3DFMT_A8", 1),
    32: ("D3DFMT_A8B8G8R8", 4),
    50: ("D3DFMT_L8", 1),
}
# ⭐ 25 = D3DFMT_A1R5G5B5 (16-bit, 2 bytes/pixel) — a PUBLICLY DOCUMENTED Direct3D 9 enum value,
# not a guess, and the only clean kind of source for a format name. Why it matters out of all
# proportion to one texture: `describe_format` raises inside `read_textures`, so ONE unmapped
# format aborted the WHOLE dictionary. `prop_muster_b1.ytd` carries 4 textures — one A1R5G5B5 and
# three perfectly good DXT1 — and all four were lost. That is also why it is the single surviving
# binary .ytd in a 40,078-dictionary corpus: it could never be converted.
# ⚠ The all-or-nothing shape is the deeper issue and is NOT fixed here: an unmapped format in
# texture N still costs textures 1..N-1. Registered rather than silently patched over.

# grcTexture+0x40 bits 0..4 -> interchange <Usage>. Every row below was measured against
# a third-party export of the same asset; the count is how many textures agreed, with zero
# disagreements. Codes absent here were never observed and deliberately fall through to UNKNOWN.
USAGE_BY_CODE = {
    0: "UNKNOWN",      # 3/3
    1: "DEFAULT",      # ⚠ RE-MEASURED 2026-08-05 against the oracle set: script_rt_dials_race
                       # spells DEFAULT. The old "DIFFUSE 12/12" third-party measurement now has
                       # a direct oracle counter-witness; the oracle set is the spec, so DEFAULT
                       # wins. (Old claim kept here as the record of the conflict.)
    2: "TERRAIN",      # 1/1 third-party + 9 oracle witnesses 2026-08-05
    5: "CABLE",        # 3/3 oracle 2026-08-05 (plg_01_cables, cs1_09 wires)
    6: "FENCE",        # 2/2
    9: "WATERFLOW",    # 1/1 oracle 2026-08-05
    11: "WATERFOG",    # 1/1 oracle 2026-08-05
    12: "WATEROCEAN",  # 2/2 oracle 2026-08-05
    20: "DIFFUSE",     # 157/157 (+192 oracle 2026-08-05)
    22: "NORMAL",      # 61/61 (+6 oracle)   <-- drives ImportYtd's normal-map handling
    23: "SPECULAR",    # 50/50 (+6 oracle)   <-- drives ImportYtd's specular handling
    26: "SKIPPROCESSING",  # 3/3 oracle 2026-08-05 (nxg_im_ground_cover LODs)
}
# Codes 8, 21, 24 still occur in real archives with no oracle witness yet - they emit UNKNOWN
# until a reference export containing one is measured (the 2026-08-05 oracle set closed
# 5/9/11/12/26 exactly this way).

# grcTexture+0x40 bits 5+ -> the <UsageFlags> symbol per bit. Derived by exact co-occurrence
# over all 224 oracle-matched textures (2026-08-05): each symbol's indicator set equals exactly
# one bit's indicator set; 224/224 oracle strings reproduced. Spelled in ascending bit order,
# ", "-joined. UNK24 (bit 29) was set on all 224 - its bit is chosen as the only candidate
# consistent with the rest of the header map; a texture without UNK24 would pin it uncontested.
# ⭐ bit 20 = Y1024 added 2026-08-06 - the 224-texture ytd sample never set it, so it was
# unnamed; a fragment embedded texture (des_fib_frame climbmiss_a, 1024x1024, dword 0x20156014,
# bits [2,4,13,14,16,18,20,29]) is the counter-witness: bit 20 is the ONLY unnamed set bit and the
# oracle prints "Y1024" exactly where ascending-bit order places bit 20 (after Y512=18, before
# UNK24=29). It completes the Y power-ladder (Y512=18 -> Y1024=20, mirroring X512=17 -> X1024=19).
# Strictly additive: no passing oracle set bit 20, so no ytd/ydr/ydd file can change.
USAGE_FLAG_BITS = (
    (5, "NOT_HALF"), (6, "HD_SPLIT"), (9, "Y4"), (10, "X8"), (11, "X16"), (12, "X32"),
    (13, "X64"), (14, "Y64"), (15, "X128"), (16, "X256"), (17, "X512"), (18, "Y512"),
    (19, "X1024"), (20, "Y1024"), (21, "X2048"), (29, "UNK24"),
)


def usage_flags_text(dword):
    syms = [s for bit, s in USAGE_FLAG_BITS if dword & (1 << bit)]
    return ", ".join(syms) if syms else "0"

DDS_MAGIC = b"DDS "
DDPF_ALPHAPIXELS, DDPF_FOURCC, DDPF_RGB, DDPF_LUMINANCE, DDPF_ALPHA = 0x1, 0x4, 0x40, 0x20000, 0x2


def describe_format(fmt):
    """(xml name, block bytes | None, bytes per pixel | None). Raises on anything unmapped -
    guessing a format silently produces garbage pixels."""
    if fmt > 0x1000000:
        fc = struct.pack("<I", fmt)
        if fc in BLOCK_FORMATS:
            name, blk = BLOCK_FORMATS[fc]
            return name, blk, None
        raise ValueError(f"unmapped texture FourCC {fc!r}")
    if fmt in LINEAR_FORMATS:
        name, bpp = LINEAR_FORMATS[fmt]
        return name, None, bpp
    raise ValueError(f"unmapped D3DFMT enum {fmt}")


def level_bytes(w, h, blk, bpp):
    """The DDS HEADER's mip-0 size field - dwPitchOrLinearSize, the block-ROUNDED figure the
    published DDS_HEADER struct asks for. This is the DDS *addressing* rule and it is used for
    the header ONLY; how many bytes the archive actually STORES is `level_sizes` below, and the
    two genuinely differ (they are the same number for every power-of-two mip 0, which is why
    one function stood in for both until 2026-08-06). Keep them apart: dds_header is validated
    byte-for-byte against the oracle set and must not move."""
    if blk is not None:
        return max(1, (w + 3) // 4) * max(1, (h + 3) // 4) * blk
    return w * h * bpp


def level_sizes(w, h, mips, blk, bpp):
    """[bytes stored per mip level] - the STORED payload layout, level 0 first.

    ⭐ THE RULE, MEASURED 2026-08-06 over all 237 oracle sidecar DDS (every .dds the reference exporter
    wrote into a per-asset folder in `_Oracles/`, paired 1:1 with its own grcTexture header):

        size(level i) = (w * h * blockBytes / 16) >> (2 * i)          [block formats]
        size(level i) = (w * h * bytesPerPixel)  >> (2 * i)           [linear formats]

    i.e. mip 0's byte count, QUARTERED per level with integer truncation - a pure byte-count
    halving, never a per-level dimension computation. It bottoms out at ... 16, 4, 1, 0, 0
    rather than clamping at one 4x4 block, and a level's size legitimately reaches 0.
    (`x >> 2 >> 2 == x >> 4` exactly, so "quarter the previous level" and "shift mip 0 by 2i"
    are the same function - there is no truncation-order ambiguity to pin.)

    SCORES over those 237, all four rules run against the same headers:
        block-rounded per level      207/237
        unclamped, dims floored at 1 227/237
        dims shifted, zero when 0    233/237
        THIS (mip-0 bytes >> 2i)     237/237      <- exact, no residual, no special case
    The last four the shift rule missed are the shapes that separate them: `slod_prop_tree_
    cedar_02/_03/_03_b` and `slod_prop_w_r_cedar_03` (128x512 and 64x256 DXT5). Once a
    dimension shifts to 0 the per-dimension product is 0 for every remaining level, while the
    stored chain still carries a 1-byte level - so ANY per-dimension rule is off by exactly 1
    there, and only the byte-count halving lands.

    ⛔ RETRACTED, SAME DAY, BY THIS MEASUREMENT: the note that used to sit here claimed "NO
    DIMENSION-BASED FORMULA CAN BE CORRECT", on the evidence that `test2_decal.dds` and
    `slod_prop_tree_eucalip_01_3.dds` are both 512x512 DXT5 mips=10 with payloads of 349552 vs
    349525. That comparison was invalid: `test2_decal.dds` is `common.rpf\\data\\glass\\
    test2_decal.dds` - a .dds FILE shipped in the archive and copied out verbatim (items.json
    `result: raw`), not a sidecar exported from a grcTexture. Its header proves it: dwDepth=0
    and flags 0x000A1007, neither of which the oracle exporter writes. It is a DCC-authored
    DDS following the DDS addressing rule; 349552 is exactly the block-rounded chain. Comparing
    it to an exporter's output compared two different producers - the wrong property. Over the
    genuine sidecars alone the stored length is fully determined by the header, as above.

    ⚠ SCOPE OF THE WITNESS: every one of the 237 has power-of-two dimensions, and so does every
    texture in x64i.rpf (13,221 measured). Exactly 1 of 555 in x64a.rpf does not (640x640).
    For a non-power-of-two texture this rule and the block-rounded one diverge below the point
    where a dimension stops dividing evenly, and NO oracle witness exists either way - flagged
    here rather than special-cased. Falsification checks that DID run over those 13,776
    non-oracle textures: the quarter chain never runs past the graphics segment and never
    overlaps the next payload (0/13,221 and 0/555). It is also <= the block-rounded chain for
    every shape measured, so it cannot over-read anywhere the old rule did not.
    """
    top = (w * h * blk) // 16 if blk is not None else w * h * bpp
    return [top >> (2 * i) for i in range(max(1, mips))]


def mipchain_bytes(w, h, mips, blk, bpp):
    return sum(level_sizes(w, h, mips, blk, bpp))


def dds_header(w, h, mips, fmt, blk, bpp):
    """A minimal DX9 DDS header. Written rather than reused so no third-party header layout is
    copied - the field order is the published DDS_HEADER struct."""
    # ⭐ 2026-08-06 - MEASURED against the oracle sidecars, which had never been graded until
    # now (every sweep ran --textures none, so the XML was verified and the PIXEL FILES were
    # not). 194 of 224 oracle DDS differed from ours in the header ALONE, in exactly two
    # fields, and both are set here:
    #   * MIPMAPCOUNT (0x20000) is set even for a single-level texture - the oracle writes it
    #     unconditionally, we only wrote it when mips > 1 (byte 10 of the header: 0x0A vs 0x08).
    #   * dwDepth is 1, not 0 (byte 24). A 2D texture is depth-1, and that is what the reference exporter writes.
    # Both are cosmetic to the pixels but break byte-parity - and the sidecar IS the deliverable
    # for a DCC, so parity matters here exactly as much as it does in the XML.
    flags = 0x1 | 0x2 | 0x4 | 0x1000            # CAPS|HEIGHT|WIDTH|PIXELFORMAT
    flags |= 0x20000                             # MIPMAPCOUNT - always, per the oracle
    flags |= 0x80000 if blk is not None else 0x8  # LINEARSIZE : PITCH
    pitch_or_linear = level_bytes(w, h, blk, bpp) if blk is not None else (w * (bpp or 4))

    # ⛔ BC7 HAS NO LEGACY FourCC. Writing b"BC7 " into the DDPF_FOURCC slot produces a file no
    # standard DDS reader can open (measured: Pillow raises "Unimplemented pixel format" on a real
    # 64x64 BC7 from char_progress_hub.ytd, while every other FourCC we emit opens fine) - and
    # write_all counted it as written. BC7 requires the DX10 extension header.
    dxgi = DXGI_BY_FOURCC.get(struct.pack("<I", fmt)) if blk is not None else None
    if blk is not None:
        fourcc = b"DX10" if dxgi else struct.pack("<I", fmt)
        pf = struct.pack("<2I4s5I", 32, DDPF_FOURCC, fourcc, 0, 0, 0, 0, 0)
    elif fmt == 25:
        # ⛔ A1R5G5B5 IS 16 bpp AND MUST NOT FALL THROUGH TO THE 32-bit else-branch (fixed
        # 2026-08-02, same day the enum was mapped). Mapping the enum made the dictionary
        # CONVERT while the header still declared RGBBitCount=32 with 8-bit masks over a
        # 2-bytes-per-pixel payload: internally inconsistent (pitch*h = 131,072 vs
        # bits/8*w*h = 262,144), and Pillow "opens" it - so it looked like success and
        # produced wrong pixels. Mapping a format is THREE edits, not one: the size table,
        # the DDS header, and the renderer.
        pf = struct.pack("<3I5I", 32, DDPF_RGB | DDPF_ALPHAPIXELS, 0, 16,
                         0x7C00, 0x03E0, 0x001F, 0x8000)
    elif fmt == 28:                              # A8
        pf = struct.pack("<3I5I", 32, DDPF_ALPHA, 0, 8, 0, 0, 0, 0xFF)
    elif fmt == 50:                              # L8
        pf = struct.pack("<3I5I", 32, DDPF_LUMINANCE, 0, 8, 0xFF, 0, 0, 0)
    elif fmt == 32:                              # A8B8G8R8
        pf = struct.pack("<3I5I", 32, DDPF_RGB | DDPF_ALPHAPIXELS, 0, 32,
                         0x000000FF, 0x0000FF00, 0x00FF0000, 0xFF000000)
    else:                                        # A8R8G8B8 / X8R8G8B8
        alpha = 0xFF000000 if fmt == 21 else 0
        pf = struct.pack("<3I5I", 32, DDPF_RGB | (DDPF_ALPHAPIXELS if alpha else 0), 0, 32,
                         0x00FF0000, 0x0000FF00, 0x000000FF, alpha)

    caps = 0x1000 | (0x400008 if mips > 1 else 0)  # TEXTURE | COMPLEX|MIPMAP
    return (DDS_MAGIC + struct.pack("<7I", 124, flags, h, w, pitch_or_linear, 1, max(1, mips))
            + b"\x00" * 44 + pf + struct.pack("<5I", caps, 0, 0, 0, 0))


# ---------------------------------------------------------------- dictionary
# Refused TEXTURES, counted so the gap is never silent. Same idiom as ydr2xml.REFUSALS: the key is
# the CLASS of refusal (so a new unmapped format shows up as its own line with a count), the detail
# names one example. A caller that wants to report them reads TEXTURE_REFUSALS.
TEXTURE_REFUSALS = collections.Counter()
TEXTURE_REFUSAL_EXAMPLE = {}

# Textures EMITTED under a shape `level_sizes` has no oracle witness for. Not a refusal - the
# pixels are still written - but the one place its rule could be wrong, made countable instead
# of left in a docstring. `level_sizes` is a pure byte-count halving, so a block texture whose
# mip-0 dimension is not a multiple of 4 gets FEWER bytes than a whole 4x4 block grid needs,
# and no oracle sidecar exercises that shape. MEASURED 2026-08-06 over 13,776 real textures
# (x64a.rpf 555 + x64i.rpf 13,221): ZERO. Exactly one texture in either archive is not a power
# of two at all (640x640) and 640 is a multiple of 4, so even it is unaffected at mip 0.
# A rising count here is the signal to go get an oracle for that shape.
SIZE_RULE_UNWITNESSED = collections.Counter()


def _refuse_texture(err):
    msg = str(err)
    key = ("unmapped_format" if "unmapped" in msg
           else "pixel_pointer_out_of_bounds" if "pixel pointer" in msg
           else "mip0_does_not_fit" if "not even mip 0" in msg
           else "texture_pointer_out_of_bounds" if "pointer is out of bounds" in msg
           else "other")
    TEXTURE_REFUSALS[key] += 1
    TEXTURE_REFUSAL_EXAMPLE.setdefault(key, msg)


def read_textures(res, base=0):
    """pgDictionary<grcTexture> -> one dict per texture, pixels sliced out.

    base = the dictionary's SYSTEM OFFSET. 0 for a standalone .ytd, where the dictionary IS the
    resource root. ⭐ A drawable also carries its own dictionary at ShaderGroup+0x08, and a third of
    them use it (measured 2026-07-29: 1,180/3,479, holding 4,845 textures that exist nowhere else).
    Passing that offset here reuses this reader - the pixel slicing, mip-truncation tolerance and
    format handling are all identical, because it is the same structure in a different place.
    """
    count = res.u32(base + 0x28) & 0xFFFF
    if not count:
        return []
    buf, ptr_arr = res.deref(res.ptr(base + 0x30), 8 * count)
    if buf is None:
        raise ValueError("texture pointer array is out of bounds")

    out = []
    for i in range(count):
        # ONE BAD TEXTURE MUST NOT COST THE WHOLE DICTIONARY (fixed 2026-08-05). Every raise in this
        # loop used to escape read_textures, so texture N's unmapped format also threw away textures
        # 1..N-1 that had already decoded correctly. MEASURED cost of the shape: D3DFMT enum 25
        # (A1R5G5B5) was a single unmapped value and it took `prop_muster_b1`'s ENTIRE dictionary with
        # it - and by the catalogue-is-a-lower-bound law there will be more such values, because
        # "never observed" describes our sample and not the format.
        # ⛔ The refusal itself is KEPT, and deliberately: guessing a pixel format silently produces
        # garbage, and a wrong texture is worse than an absent one. What changes is the BLAST RADIUS -
        # refuse the texture, count it, keep the dictionary. Callers read `refused` to report it, so
        # this is a counted gap and never a silent one.
        try:
            out.append(_read_one_texture(res, ptr_arr, i))
        except ValueError as e:
            _refuse_texture(e)
    return out


def _read_one_texture(res, ptr_arr, i):
    """One grcTexture -> its dict. Raises ValueError; read_textures turns that into a counted skip."""
    if True:
        buf2, tp = res.deref(res.u32(ptr_arr + i * 8), 0x90)
        if buf2 is None:
            raise ValueError(f"texture {i} pointer is out of bounds")
        name = res.cstr(res.u32(tp + 0x28))
        w, h = res.u16(tp + 0x50), res.u16(tp + 0x52)
        mips = max(1, res.sys[tp + 0x5D])
        fmt = res.u32(tp + 0x58)
        xml_fmt, blk, bpp = describe_format(fmt)
        if blk is not None and (w % 4 or h % 4):
            SIZE_RULE_UNWITNESSED["mip0 dimension is not a multiple of 4"] += 1

        need = mipchain_bytes(w, h, mips, blk, bpp)
        pbuf, po = res.deref(res.u32(tp + 0x70), need)
        if pbuf is None:
            # A truncated tail means the mip count and the payload disagree; keep the levels
            # that are fully present rather than emitting a DDS the consumer will misread.
            pbuf, po = res.deref(res.u32(tp + 0x70), 1)
            if pbuf is None:
                raise ValueError(f"texture {name!r}: pixel pointer is out of bounds")
            # ⛔ THE SAME per-level rule the full read uses (level_sizes), not a second one.
            # This loop used to walk block-ROUNDED levels while `need` above was a chain sum -
            # so a truncated texture kept a DIFFERENT amount than the untruncated path would,
            # and the mip count it reported did not describe the bytes it emitted.
            avail, keep = len(pbuf) - po, 0
            for lvl, sz in enumerate(level_sizes(w, h, mips, blk, bpp)):
                if keep + sz > avail:
                    break
                keep += sz
                mips = lvl + 1
            if keep == 0:
                raise ValueError(f"texture {name!r}: not even mip 0 fits the payload")
            need = keep

        return dict(name=name, width=w, height=h, mips=mips, fmt=fmt, xml_fmt=xml_fmt,
                    usage=USAGE_BY_CODE.get(res.u32(tp + 0x40) & 0x1F, "UNKNOWN"),
                    usage_code=res.u32(tp + 0x40) & 0x1F,
                    # measured 2026-08-05 (224/224 oracle textures): Unk32 = u16 @ +0x32
                    # (the high half of the dword whose low half is the +0x30 refcount);
                    # UsageFlags = bits 5+ of the same +0x40 dword the usage code lives in;
                    # ExtraFlags = u32 @ +0x48
                    unk32=res.u16(tp + 0x32),
                    usage_flags=usage_flags_text(res.u32(tp + 0x40)),
                    extra_flags=res.u32(tp + 0x48),
                    dds=dds_header(w, h, mips, fmt, blk, bpp) + bytes(pbuf[po:po + need]))


def to_xml(textures):
    """The interchange <TextureDictionary> shape.

    ⛔ RETRACTED 2026-08-05: this docstring used to claim Unk32/UsageFlags/ExtraFlags are a
    "measured constant 0" over 25,816 corpus Items. The oracle set contradicts it outright -
    0 of 224 matched textures carry Unk32=0 (values 128/32/64) and every one carries real
    UsageFlags symbols. The old claim was measured against OUR OWN emissions, not references -
    the wrong property. All three now come from the header fields named in read_texture."""
    L = ['<?xml version="1.0" encoding="UTF-8"?>']
    if not textures:
        L.append("<TextureDictionary />")
        return "\n".join(L) + "\n"
    L.append("<TextureDictionary>")
    for t in textures:
        L += [" <Item>",
              "  <Name>%s</Name>" % esc(t["name"]),
              '  <Unk32 value="%d" />' % t.get("unk32", 0),
              "  <Usage>%s</Usage>" % t["usage"],
              "  <UsageFlags>%s</UsageFlags>" % t.get("usage_flags", "0"),
              '  <ExtraFlags value="%d" />' % t.get("extra_flags", 0),
              '  <Width value="%d" />' % t["width"],
              '  <Height value="%d" />' % t["height"],
              '  <MipLevels value="%d" />' % t["mips"],
              "  <Format>%s</Format>" % t["xml_fmt"],
              "  <FileName>%s.dds</FileName>" % esc(t["name"]),
              " </Item>"]
    L.append("</TextureDictionary>")
    return "\n".join(L) + "\n"


def safe_name(name):
    """A texture name becomes a filename, so strip anything a filesystem would reject. RAGE
    names are ASCII in practice; this is a backstop, not the mechanism."""
    return "".join(c if c.isalnum() or c in "._- " else "_" for c in name) or "unnamed"


def sidecars(textures, stem, want_png=True, want_dds=True):
    """[(relative path under the type folder, bytes)] - the pixel payload that travels with the
    XML. Shared by the CLI and by quarry's in-line extraction so both lay out identically.

    ⚠ PNG IS THE ONE `ImportYtd` ACTUALLY LOADS (`<PixelFolder>/<TexName>.png`); DDS is the
    lossless archive form for every other consumer. Emitting only DDS would leave the texture
    lane connected on paper and broken in practice, so both are written by default whenever the
    decoders are present - and `png_available()` is the thing to report when they are not.

    ⚠ BOTH COSTS REAL DISK AT GAME SCALE. Measured on `x64i.rpf`: 7,148 textures = 1.62 GB dds +
    2.35 GB png. Across the whole game that is roughly 23 GB + 33 GB on top of ~38 GB of ydr.xml,
    which will not fit a 104 GB volume - hence `want_dds` / `want_png` and quarry's `--textures`.
    """
    out = []
    for t in textures:
        base = f"{stem}/{safe_name(t['name'])}"
        if want_dds:
            out.append((base + ".dds", t["dds"]))
        if want_png:
            data, why = decode_png(t)
            if data is not None:
                out.append((base + ".png", data))
            else:
                # THE_PLAN 5.0: a dropped png left NO trace while the XML manifest advertised
                # the file (cmd_textures counts this same event as png_decode_refused; the
                # extract/export lane did not). Counted; rides the TEXTURE_REFUSALS report.
                TEXTURE_REFUSALS["png_sidecar_refused"] += 1
                TEXTURE_REFUSAL_EXAMPLE.setdefault("png_sidecar_refused",
                                                   "%s: %s" % (t["name"], why))
    return out


def convert(path):
    res = Res(path)
    res.require_version(13, "texture dictionary")
    textures = read_textures(res)
    stem = os.path.splitext(os.path.basename(path))[0]
    return to_xml(textures), textures, stem


# ---------------------------------------------------------------- optional PNG
_PNG = None


def png_available():
    """ImportYtd loads PNG today, so offer it - but only when the decoders are installed."""
    global _PNG
    if _PNG is None:
        try:
            import texture2ddecoder
            from PIL import Image
            _PNG = (texture2ddecoder, Image)
        except Exception:
            _PNG = False
    return _PNG


def decode_png(t):
    """(png bytes, '') or (None, why). Mip 0 only - UE regenerates the chain."""
    mod = png_available()
    if not mod:
        return None, "texture2ddecoder/Pillow not installed"
    _t2d, _Image = mod
    import io
    buf = io.BytesIO()
    ok, why = _render(t, buf)
    return (buf.getvalue(), "") if ok else (None, why)


def write_png(t, path):
    data, why = decode_png(t)
    if data is None:
        return False, why
    with open(path, "wb") as fh:
        fh.write(data)
    return True, ""


def _decode_bc2(t2d, body, w, h):
    """BC2 = BC1 colour half + 16 EXPLICIT 4-bit alphas per block. texture2ddecoder ships no BC2
    decoder, and BC3's INTERPOLATED-alpha algorithm over BC2 bytes yields wrong alpha silently.
    The colour half sits at the same offset in both, so only the alpha half is redone here."""
    out = bytearray(t2d.decode_bc3(body, w, h))          # BGRA; colour half is correct
    bx = (w + 3) // 4
    for blk in range(len(body) // 16):
        alphas = body[blk * 16: blk * 16 + 8]
        ox, oy = (blk % bx) * 4, (blk // bx) * 4
        for py in range(4):
            for px in range(4):
                x, y = ox + px, oy + py
                if x >= w or y >= h:
                    continue
                i = py * 4 + px
                nib = alphas[i >> 1]
                a4 = (nib & 0x0F) if (i & 1) == 0 else (nib >> 4)
                out[(y * w + x) * 4 + 3] = a4 * 17       # 4-bit -> 8-bit (0x0->0, 0xF->255)
    return bytes(out)


def _render(t, sink):
    mod = png_available()
    if not mod:
        return False, "texture2ddecoder/Pillow not installed"
    t2d, Image = mod
    w, h, fmt = t["width"], t["height"], t["fmt"]
    body = t["dds"][128:]
    try:
        if fmt > 0x1000000:
            fc = struct.pack("<I", fmt)
            # ⛔ BC2 (DXT3) MUST NOT BE DECODED AS BC3. texture2ddecoder has no decode_bc2, and
            # the old `decode_bc2 if hasattr(...) else decode_bc3` ALWAYS took the BC3 fallback.
            # BC2 stores 16 EXPLICIT 4-bit alphas; BC3 interpolates from two endpoints, so the
            # alpha comes out wrong while the colour half - at the same block offset in both -
            # comes out right. That is exactly why it survived every eyeball check: measured over
            # x64a+x64b, 19 of 20 DXT3 textures had wrong alpha, mean 42% of pixels, max delta 255.
            dec = {b"DXT1": t2d.decode_bc1, b"DXT3": _decode_bc2, b"DXT5": t2d.decode_bc3,
                   b"ATI1": t2d.decode_bc4, b"BC4U": t2d.decode_bc4, b"ATI2": t2d.decode_bc5,
                   b"BC5U": t2d.decode_bc5, b"BC7 ": t2d.decode_bc7}.get(fc)
            if dec is None:
                return False, f"no decoder for {fc!r}"
            raw = dec(t2d, body, w, h) if dec is _decode_bc2 else dec(body, w, h)
            img = Image.frombuffer("RGBA", (w, h), raw, "raw", "BGRA", 0, 1)
        elif fmt in (21, 22, 32):
            raw = "BGRA" if fmt in (21, 22) else "RGBA"
            img = Image.frombuffer("RGBA", (w, h), body[:w * h * 4], "raw", raw, 0, 1)
        elif fmt == 25:                          # A1R5G5B5 - 16 bpp, see dds_header
            px = struct.unpack_from("<%dH" % (w * h), body, 0)
            buf = bytearray()
            for p in px:                         # expand 5/5/5/1 to 8/8/8/8, replicating high bits
                r = ((p >> 10) & 0x1F) * 255 // 31
                g = ((p >> 5) & 0x1F) * 255 // 31
                b = (p & 0x1F) * 255 // 31
                buf += bytes((b, g, r, 0xFF if (p & 0x8000) else 0))
            img = Image.frombuffer("RGBA", (w, h), bytes(buf), "raw", "BGRA", 0, 1)
        elif fmt in (28, 50):
            img = Image.frombuffer("L", (w, h), body[:w * h], "raw", "L", 0, 1).convert("RGBA")
        else:
            return False, f"no decoder for D3DFMT {fmt}"
        img.save(sink, format="PNG")
        return True, ""
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


# ---------------------------------------------------------------- CLI
def write_all(stem, xml, textures, out_dir, want_png=False):
    """Write <stem>.ytd.xml plus the <stem>/ pixel folder. Returns (n_dds, n_png, notes)."""
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, stem + ".ytd.xml"), "w", encoding="utf-8") as fh:
        fh.write(xml)
    if not textures:
        return 0, 0, []
    pix = os.path.join(out_dir, stem)
    os.makedirs(pix, exist_ok=True)
    ndds = npng = 0
    notes = []
    for t in textures:
        safe = safe_name(t["name"])
        with open(os.path.join(pix, safe + ".dds"), "wb") as fh:
            fh.write(t["dds"])
        ndds += 1
        if want_png:
            ok, why = write_png(t, os.path.join(pix, safe + ".png"))
            npng += 1 if ok else 0
            if not ok and why not in notes:
                notes.append(why)
    return ndds, npng, notes


def main():
    ap = argparse.ArgumentParser(prog="ytd2xml", description=__doc__.split("\n")[0])
    ap.add_argument("files", nargs="*", help="one or more .ytd, or a directory of them")
    ap.add_argument("--out", help="output directory")
    ap.add_argument("--png", action="store_true",
                    help="also decode each texture to PNG (what ImportYtd loads today)")
    ap.add_argument("--selftest", action="store_true", help="convert in memory, write nothing")
    a = ap.parse_args()
    if not a.files:
        ap.error("give at least one .ytd")
    if not a.out and not a.selftest:
        ap.error("--out is required unless --selftest")

    # a directory argument expands to the .ytd inside it - a batch is the normal case, and a
    # 1,400-file command line exceeds the Windows limit
    targets = []
    for p in a.files:
        if os.path.isdir(p):
            targets += sorted(os.path.join(p, f) for f in os.listdir(p)
                              if f.lower().endswith(".ytd"))
        else:
            targets.append(p)

    ok = fail = tex = 0
    unmapped = {}
    for p in targets:
        try:
            xml, textures, stem = convert(p)
        except Exception as e:
            msg = f"{type(e).__name__}: {e}"
            unmapped[msg] = unmapped.get(msg, 0) + 1
            print(f"FAIL {os.path.basename(p)}: {msg}")
            fail += 1
            continue
        ok += 1
        tex += len(textures)
        if a.selftest:
            import xml.etree.ElementTree as ET
            n = len(ET.fromstring(xml).findall("./Item"))
            unk = sum(1 for t in textures if t["usage"] == "UNKNOWN")
            print(f"OK   {os.path.basename(p):<44} {n:3} textures  "
                  f"{sum(len(t['dds']) for t in textures):>10,} B pixels"
                  + (f"  ({unk} usage UNKNOWN)" if unk else ""))
        else:
            nd, np_, notes = write_all(stem, xml, textures, a.out, a.png)
            print(f"OK   {os.path.basename(p):<44} {len(textures):3} textures  {nd:3} dds"
                  + (f"  {np_:3} png" if a.png else "")
                  + (f"   [{'; '.join(notes)}]" if notes else ""))
    print(f"\nconverted {ok}, failed {fail}, {tex:,} textures")
    if unmapped:
        print("failure reasons:")
        for m, n in sorted(unmapped.items(), key=lambda kv: -kv[1]):
            print(f"  {n:5}x  {m}")
    # ⛔ PARTIAL FAILURE IS FAILURE, and zero subjects is not a pass (2026-08-03). This returned 0
    # unless EVERY file failed, so 999 failures out of 1,000 exited 0; and a directory holding no
    # .ytd printed "converted 0, failed 0" and exited 0 - silent success on a no-op.
    if not ok and not fail:
        print("⛔ no .ytd found - a run with nothing to convert is not a success")
        return 2
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
