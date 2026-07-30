"""ydr2xml - binary GTA V .ydr (RSC7 v165)  ->  RAGE interchange .ydr.xml

WHY THIS EXISTS
RUDE's importer already reads the interchange XML and is proven in-engine on 1,144 meshes with materials,
collision, LODs and textures. QUARRY was emitting raw BINARY, which RUDE cannot read - so work was
being duplicated rebuilding readers the XML pipeline already had. Emitting XML reuses all of it.
Nothing about the game is being modified: this converts the operator's own extracted files.

WHAT IS GROUNDED, AND IN WHAT
  * container + drawable graph + vertex declaration table: measured over all 3,479 real base-game
    v165 ydrs / 17,370 geometries (docs/ENGINEERING_LOG "ydr VERTEX DECLARATION"). Channels sit in
    ASCENDING BIT ORDER, offset = sum of sizes of lower set bits; the grcFvf u64 is a 16-slot TYPE
    TABLE indexed by channel bit (hence constant 0x7755555555996996 in 17,370/17,370).
  * XML shape: measured over 25,936 third-party reference exports (LOG "ydr.xml schema"). Their `Data` field order ==
    the `Layout` child order == ascending bit order, so the mapping is 1:1 with no reordering.
  * shader preset names: the binary stores only joaat(name), which is one-way, so names come from
    joaat_shaders.json (133 presets inverted from the operator's own third-party reference exports).
  * sampler (texture param) names + RenderBucket: derived from the shader struct itself and
    validated against 866 third-party full-parameter reference exports by joining params BY NAME -
    bucket 99.989% (9,166/9,167), texture names 99.960%, vector values 99.933%, arrays 100%
    (residuals = game-build drift). See read_shaders and reports/sampler_derivation_2026-07-28.md.

DELIBERATE OMISSIONS (safe - verified against the consumer, not guessed)
UE 5.8's FindChildNode is DIRECT-CHILDREN-ONLY, so a missing element yields nullptr and can never
silently match something deeper. We therefore emit the minimal set the importer actually reads and
skip: LodDist*/Flags*, Lights, Skeleton, Medium/Low LOD groups, Shaders/Item/FileName,
VertexBuffer/Flags, per-geometry bboxes, model RenderMask/Flags/HasSkin/BoneIndex/Unknown1, BoneIDs,
and every Vector/Array shader param.
Whitespace, float precision and indices-per-line are all free: FXmlFile treats every whitespace char
as a delimiter and rejoins content with single spaces, so only TOKEN COUNT and ORDER matter.

<Bounds> (embedded collision) IS EMITTED (2026-07-28): the phBound graph at drawable +0xC8,
faithful to the reference exports (ybn oracle: 183/183 name-matched pairs, 0 same-bits text
diffs, 87 files byte-identical, all residuals proven different-float32-bits build drift).
NO SILENT DEFAULTS: any unmeasured bound/polygon type code, set-but-unnamed flag bit, or
non-zero byte in a lane only ever measured zero REFUSES the file loudly (BoundsError).
⚠ CONSUMER NOTE: ExportYtyp marks an archetype collidable only when Bounds/Children >= 1;
220 of 1,012 base-game bound-bearing ydrs have a NON-Composite root (Box 160 / Sphere 53 /
Cylinder 7) which this emitter reproduces faithfully - those need the consumer-side rule
extended (or a wrap-in-Composite option) to be flagged collidable.

Usage:
    python ydr2xml.py <in.ydr> [more.ydr ...] --out <dir>
    python ydr2xml.py --selftest      # convert + reparse, no files written
"""
import argparse
import json
import os
import struct
import sys
import zlib

from meta2xml import fmt_num          # THE proven float-text rule (7->9 sig digits,
                                      # ties away from zero) - single implementation

# ---------------------------------------------------------------- container

PAGE_BITS = {0: 27, 1: 26, 2: 25, 3: 24, 4: 17, 5: 11, 6: 7, 7: 5, 8: 4}
PAGE_MASK = {0: 1, 1: 1, 2: 1, 3: 1, 4: 0x7F, 5: 0x3F, 6: 0xF, 7: 3, 8: 1}


def seg_size(flags):
    """Total bytes described by an RSC7 flag word's page plan."""
    f = flags & 0x0FFFFFFF
    base = 0x200 << (f & 0xF)
    return sum(((f >> PAGE_BITS[k]) & PAGE_MASK[k]) * (base << k) for k in range(9))


class Res:
    """An inflated RSC7 resource: system + graphics segments, with tagged-pointer resolution."""

    @classmethod
    def from_bytes(cls, blob):
        """Parse an in-memory resource - used when converting during extraction, so a file never
        has to be written to disk just to be read back."""
        self = cls.__new__(cls)
        self._load(blob)
        return self

    def __init__(self, path):
        self._load(open(path, "rb").read())

    def _load(self, blob):
        if len(blob) < 16 or blob[:4] != b"RSC7":
            raise ValueError("not an RSC7 container")
        _, self.version, sysf, gfxf = struct.unpack_from("<4sIII", blob, 0)
        ssz, gsz = seg_size(sysf), seg_size(gfxf)
        raw = zlib.decompress(blob[16:], -15)
        if len(raw) < ssz:
            raise ValueError("inflated payload shorter than the declared system segment")
        self.sys = raw[:ssz]
        self.gfx = raw[ssz:ssz + gsz]

    def ptr(self, off):
        return struct.unpack_from("<I", self.sys, off)[0]

    def deref(self, tagged, need=0):
        """Tagged pointer -> (buffer, offset). High nibble 5 = system, 6 = graphics."""
        tag, o = tagged >> 28, tagged & 0x0FFFFFFF
        buf = self.sys if tag == 5 else (self.gfx if tag == 6 else None)
        if buf is None or o < 0 or o + need > len(buf):
            return None, 0
        return buf, o

    def u16(self, off):
        return struct.unpack_from("<H", self.sys, off)[0]

    def u32(self, off):
        return struct.unpack_from("<I", self.sys, off)[0]

    def cstr(self, tagged, limit=160):
        buf, o = self.deref(tagged, 1)
        if buf is None:
            return ""
        end = buf.find(b"\x00", o)
        if end < 0 or end - o > limit:
            end = min(o + limit, len(buf))
        return buf[o:end].decode("latin-1")

    def require_version(self, want, what):
        """Version lives in the container but MEANS a type: 165 ydr, 43 ybn, 13 ytd, 2 meta.
        Checked by the per-type converter, not by _load, so one container class serves all."""
        if self.version != want:
            extra = " (159 = GTA V Enhanced, not Legacy)" if self.version == 159 else ""
            raise ValueError(f"RSC7 version {self.version} is not a {what}, want {want}{extra}")


# ---------------------------------------------------------------- vertex declaration

# bit -> (interchange Layout child name, token count). Ascending bit order IS the field order.
CHANNELS = {
    0:  ("Position", 3),
    1:  ("BlendWeights", 4),
    2:  ("BlendIndices", 4),
    3:  ("Normal", 3),
    4:  ("Colour0", 4),
    5:  ("Colour1", 4),
    6:  ("TexCoord0", 2), 7: ("TexCoord1", 2), 8: ("TexCoord2", 2), 9: ("TexCoord3", 2),
    10: ("TexCoord4", 2), 11: ("TexCoord5", 2), 12: ("TexCoord6", 2), 13: ("TexCoord7", 2),
    14: ("Tangent", 4),
    15: ("Binormal", 4),
}
# grcFvf nibble -> byte size. 5/6/7/9 measured over the map-prop corpus (17,370 geometries);
# 1/3/A measured over the whole-game yft+ydd corpus (79,830 files / 649,976 geometries,
# 2026-07-28) and VALUE-validated against 1,669 name-matched third-party reference exports:
#   0x1 = half2   (TexCoord0; size isolated in 743 stride equations; halves match the
#                  reference floats within half-ULP on 555k tokens)
#   0x3 = half4   (Tangent) and 0xA = signed-byte4 /127 (Normal) - the two always co-occur
#                  (1,074 equations, sizes sum to 12); the 4+8 split is fixed by Colour0
#                  realigning EXACTLY at Normal=4, and the Normal decode is bit-exact vs
#                  the reference in 91 whole files.
# Anything else must still REFUSE: guessing a size silently scrambles every vertex after
# the first.
NIBBLE_SIZE = {1: 4, 3: 8, 5: 8, 6: 12, 7: 16, 9: 4, 0xA: 4}
INT_CHANNELS = {1, 2, 4, 5}          # ubyte4: emitted as 0-255 INTEGERS, never 0-1 floats


def build_decl(mask, nibbles, declared_stride):
    """-> (fields, stride). fields = [(bit, name, tokens, offset, size, nibble)] in ascending
    bit order."""
    fields, off = [], 0
    for bit in range(16):
        if not (mask >> bit) & 1:
            continue
        nb = (nibbles >> (bit * 4)) & 0xF
        size = NIBBLE_SIZE.get(nb)
        if size is None:
            raise ValueError(f"unsupported channel type: mask 0x{mask:x} bit {bit} nibble 0x{nb:x}")
        if bit not in CHANNELS:
            raise ValueError(f"unknown channel bit {bit} in mask 0x{mask:x}")
        name, tokens = CHANNELS[bit]
        fields.append((bit, name, tokens, off, size, nb))
        off += size
    if off != declared_stride:
        raise ValueError(f"computed stride {off} != declared {declared_stride} (mask 0x{mask:x})")
    return fields, off


def fmt_float(v):
    """Any parseable float is fine (FCString::Atof). Trim to keep files small and diffable."""
    if v == int(v) and abs(v) < 1e15:
        return str(int(v))
    return repr(round(v, 8))


def decode_vertices(res, vdata_tagged, count, stride, fields):
    buf, base = res.deref(vdata_tagged, count * stride)
    if buf is None:
        raise ValueError("vertex data does not resolve")
    lines = []
    for v in range(count):
        vb = base + v * stride
        groups = []
        for bit, _name, tokens, off, size, nb in fields:
            at = vb + off
            if bit in INT_CHANNELS:
                vals = [str(buf[at + i]) for i in range(tokens)]
            else:
                if nb in (1, 3):
                    # half-float pair/quad (cloth TexCoord0 / Tangent) - value-validated
                    # against third-party reference exports within half-ULP
                    raw = struct.unpack_from("<%de" % (size // 2), buf, at)
                elif nb == 0xA:
                    # signed-byte4 normalized /127 (cloth Normal) - bit-exact vs the reference; the
                    # channel emits 3 tokens, the 4th byte (w) is dropped below
                    raw = [max(by - 256 if by > 127 else by, -127) / 127.0
                           for by in buf[at:at + 4]]
                else:
                    raw = struct.unpack_from("<%df" % tokens, buf, at)
                if len(raw) < tokens:
                    raise ValueError("nibble 0x%x yields %d values, channel wants %d tokens"
                                     % (nb, len(raw), tokens))
                # real shipped assets contain literal NaN (e.g. prop_dock_crane_01) and UE's mesh
                # builder chokes on NaN UVs, so neutralise here rather than downstream
                vals = [fmt_float(x if x == x and abs(x) != float("inf") else 0.0)
                        for x in raw[:tokens]]
            groups.append(" ".join(vals))
        lines.append("   ".join(groups))
    return lines


# ---------------------------------------------------------------- shader names

_SHADERS = None


def preset_name(hash32):
    """joaat is one-way, so recover the preset name from the table built off third-party reference exports."""
    global _SHADERS
    if _SHADERS is None:
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "joaat_shaders.json")
        try:
            _SHADERS = json.load(open(p))
        except Exception:
            _SHADERS = {}
    return _SHADERS.get("0x%08x" % hash32) or "hash_%08X" % hash32


# ---------------------------------------------------------------- drawable walk

# Shader param NAMES are in the binary as joaat(lowercase(name)): a u32 array of npar hashes
# at param_table + data_size, one per 16-byte param entry, in entry order. Derived and
# validated 2026-07-28 (reports/sampler_derivation_2026-07-28.md):
#   * u32 @shader+0x10 packs u8 param count (lo) + u8 RenderBucket (next) - the old "&0xFFFF
#     reads 269/520/778" mystery was count|bucket<<8 (0x10D = 13 params, bucket 1)
#   * u16 @shader+0x14 = data_size = 16*npar + 16*sum(vec4 counts): held 43,872/43,872
#   * entry byte 0 is the class: 0 = texture, N>0 = vec4 count of a value param
#   * per-index pairing hash[i]<->entry[i] proven by joining params BY NAME against 866 third-party
#     full-parameter reference exports: vector values 99.933%, arrays 100.000%, bound
#     texture names 99.960% - residuals are game-build drift, not decode error.
# joaat is one-way, so names come from this table (corpus sampler names + joaat-cracked
# lane hashes); an unresolved hash emits as hash_%08X, which the importer skips harmlessly.
SAMPLER_NAMES = [
    "AnisoNoiseSpecSampler", "BumpSampler", "BumpSampler2", "BumpSampler_layer0",
    "BumpSampler_layer1", "BumpSampler_layer2", "BumpSampler_layer3",
    "ComboHeightSamplerFur01", "ComboHeightSamplerFur23", "ComboHeightSamplerFur45",
    "ComboHeightSamplerFur67", "DamageSampler", "DetailSampler", "DiffuseHfSampler",
    "DiffuseSampler", "DiffuseSampler2", "DirtBumpSampler", "DirtSampler",
    "EnvironmentSampler", "FlowSampler", "FoamSampler", "FogSampler",
    "FontNormalSampler", "FontSampler", "FurMaskSampler", "NoiseSampler",
    "PlateBgBumpSampler", "PlateBgSampler", "SfxWindSampler3D", "SnowSampler",
    "SnowSampler0", "SnowSampler1", "SpecSampler", "StarFieldSampler",
    "StippleSampler", "TextureSamp", "TextureSampler_layer0", "TextureSampler_layer1",
    "TextureSampler_layer2", "TextureSampler_layer3", "TintPaletteSampler",
    "VolumeSampler", "WrinkleMaskSampler_0", "WrinkleMaskSampler_1",
    "WrinkleMaskSampler_2", "WrinkleMaskSampler_3", "WrinkleMaskSampler_4",
    "WrinkleMaskSampler_5", "WrinkleSampler_A", "WrinkleSampler_B", "bumptex",
    "diffusetex", "dirttex", "ditherSampler", "distanceMapSampler",
    "heightMapSamplerLayer0", "heightMapSamplerLayer1", "heightMapSamplerLayer2",
    "heightMapSamplerLayer3", "heightSampler", "highDetailSampler", "lookupSampler",
    "moonSampler", "perlinSampler", "speculartex",
]

# ⭐ VALUE (non-texture) shader parameter names, 2026-07-29. Every one below was identified by
# hashing the candidate name and matching it against a hash read out of a REAL binary (dt1_00_5.ydr
# and friends) - not by reading anyone's source. Unmatched hashes are still EMITTED as
# hash_XXXXXXXX: the values are the operator's data and dropping them silently is how
# `detailSettings` went missing for months while DetailSampler was bound 6,264 times.
VALUE_PARAM_NAMES = [
    "bumpiness", "detailSettings", "specularFalloffMult", "specularIntensityMult",
    "specMapIntMask", "wetnessMultiplier", "useTessellation", "hardAlphaBlend",
    "globalAnimUV0", "globalAnimUV1", "alphaScale", "emissiveMultiplier",
    "parallaxScaleBias", "heightScale", "heightBias", "envEffThickness", "envEffScale",
    "reflectivePower", "normalMapScale", "TextureSharpness", "DirtDecalMask",
    "specDesaturateExponent", "specDesaturateIntensity", "FresnelCoeff",
    "matMaterialColorScale", "umGlobalParams", "materialWetnessMultiplier",
    "bumpSelfShadowAmount", "tintPaletteSelector", "detailScale",
    # Terrain/PXM parallax, identified 2026-07-29 the same way (hash-matched against real files).
    # ⭐ These are the settings for cause C's unmapped heightMapSamplerLayer0-3.
    "heightScale0", "heightScale1", "heightScale2", "heightScale3",
    "heightBias0", "heightBias1", "heightBias2", "heightBias3",
    "parallaxSelfShadowAmount",
]

_VALUE_PARAMS = None


def value_param_name(hash32):
    global _VALUE_PARAMS
    if _VALUE_PARAMS is None:
        _VALUE_PARAMS = {_joaat(n.lower()): n for n in VALUE_PARAM_NAMES}
    return _VALUE_PARAMS.get(hash32) or "hash_%08X" % hash32


_SAMPLERS = None


def _joaat(s):
    h = 0
    for c in s.encode("latin-1"):
        h = (h + c) & 0xFFFFFFFF
        h = (h + ((h << 10) & 0xFFFFFFFF)) & 0xFFFFFFFF
        h ^= h >> 6
    h = (h + ((h << 3) & 0xFFFFFFFF)) & 0xFFFFFFFF
    h ^= h >> 11
    return (h + ((h << 15) & 0xFFFFFFFF)) & 0xFFFFFFFF


def sampler_name(hash32):
    global _SAMPLERS
    if _SAMPLERS is None:
        _SAMPLERS = {_joaat(n.lower()): n for n in SAMPLER_NAMES}
    return _SAMPLERS.get(hash32) or "hash_%08X" % hash32


def embedded_textures(res, base=0):
    """The drawable's OWN texture dictionary -> ytd2xml texture dicts (name/format/pixels), or [].

    ⛔ WHY THIS EXISTS (2026-07-29). A gtaDrawable can carry its textures INTERNALLY, at
    ShaderGroup+0x08, instead of referencing a standalone .ytd. Nothing here read it, so those
    textures did not exist as far as RUDE was concerned. Measured over 3,479 real binaries:
    **1,180 (33.9%) carry a non-empty embedded dictionary** holding 4,845 textures, and **18.2% of
    all texture requests are satisfiable ONLY from there**. The visible symptoms were
    TintPaletteSampler at 100% unresolved (1,736 references, 0 present - palettes are almost always
    embedded) and drawables that render completely untextured because they carry every texture they
    use. PROOF: ce_xr_ctr2.ydr's embedded dictionary holds 28 textures and satisfies 28 of 28 of
    that drawable's own requests, including ce_xr_ctr2_lod_pal.

    The dictionary is the same pgDictionary<grcTexture> a .ytd's root is, so ytd2xml.read_textures
    reads it verbatim once told where it lives - no second implementation to drift.
    """
    sg = res.ptr(base + 0x10)
    buf, o = res.deref(sg, 0x40)
    if buf is None:
        return []
    tp = res.u32(o + 0x08)
    if not tp:
        return []
    tbuf, to = res.deref(tp, 0x40)
    if tbuf is None:
        return []
    try:
        import ytd2xml
        return ytd2xml.read_textures(res, base=to)
    except Exception:
        # A malformed embedded dictionary must not lose the whole drawable - the geometry and
        # shader data are still good. Report nothing rather than raising.
        return []


def read_shaders(res, base=0):
    """base = system offset of the gtaDrawable (0 for a standalone ydr; a dictionary entry's
    offset for ydd/yft reuse). Only the FIXED header offsets rebase - tagged pointers are
    segment-absolute and need nothing.
    -> [(preset, render_bucket, [(sampler, texture_name), ...], [(param, [(x,y,z,w), ...]), ...])]

    ⛔ THE FOURTH ELEMENT EXISTS BECAUSE IT WAS MISSING (2026-07-29). This function used to read the
    16-byte param entry's CLASS BYTE, `continue` on anything non-zero, and emit textures only - so
    EVERY scalar/vector shader parameter in the game was dropped: detail tiling, specular intensity
    and falloff, bump scale, wetness, tint selectors, terrain blend weights. The visible cost was
    that `DetailSampler` bound 6,264 times with no `detailSettings` to tile it by, which makes a
    faithful detail map impossible and is not fixable downstream.
    MEASURED LAYOUT: class byte 0 = texture; N>0 = a count of float4s, and the entry's +0x08 field
    is a TAGGED POINTER to N*16 bytes of float data (verified by dereferencing it, not by assuming
    it sits at the data-region offset - the two happen to coincide and only one is the contract)."""
    out = []
    sg = res.ptr(base + 0x10)
    buf, o = res.deref(sg, 0x40)
    if buf is None:
        return out
    arr_p, nsh = res.u32(o + 0x10), res.u16(o + 0x18)
    abuf, ao = res.deref(arr_p, nsh * 8)
    if abuf is None:
        return out
    for si in range(nsh):
        bp = res.u32(ao + si * 8)
        bbuf, bo = res.deref(bp, 0x30)
        if bbuf is None:
            out.append(("default", 0, [], []))
            continue
        preset = preset_name(res.u32(bo + 0x08))
        w10 = res.u32(bo + 0x10)
        npar, bucket = w10 & 0xFF, (w10 >> 8) & 0xFF
        dsize = res.u16(bo + 0x14)
        tbl_p = res.u32(bo + 0x00)
        texs = []
        vals = []
        # max npar measured in the lane is 32; clamp keeps a corrupt count from walking off.
        # A texture is any class-0 entry whose stub derefs, whose type word's low u16 is 1
        # (every real stub reads xxxx0001; 0x0002=external ref, 0x0080=embedded, measured),
        # and whose +0x28 name is printable - unbound slots (NULL ptr) simply do not emit.
        if 0 < npar <= 96 and dsize >= npar * 16:
            tbuf, to = res.deref(tbl_p, dsize + npar * 4)
            if tbuf is not None:
                hashes = struct.unpack_from("<%dI" % npar, tbuf, to + dsize)
                for pi in range(npar):
                    cls = tbuf[to + pi * 16]
                    if cls != 0:
                        # A VALUE param: cls = how many float4s, +0x08 = tagged pointer to them.
                        # Clamped: a corrupt count must not turn into a huge read.
                        if cls <= 64:
                            vp = struct.unpack_from("<I", tbuf, to + pi * 16 + 8)[0]
                            vbuf, vo = res.deref(vp, cls * 16) if vp else (None, 0)
                            if vbuf is not None:
                                vals.append((value_param_name(hashes[pi]),
                                             [struct.unpack_from("<4f", vbuf, vo + k * 16)
                                              for k in range(cls)]))
                        continue
                    sp = struct.unpack_from("<I", tbuf, to + pi * 16 + 8)[0]
                    sbuf, so = res.deref(sp, 0x34) if sp else (None, 0)
                    if sbuf is None or struct.unpack_from("<H", sbuf, so + 0x30)[0] != 1:
                        continue
                    nm = res.cstr(struct.unpack_from("<I", sbuf, so + 0x28)[0])
                    if nm and all(31 < ord(ch) < 127 for ch in nm):
                        texs.append((sampler_name(hashes[pi]), nm))
        out.append((preset, bucket, texs, vals))
    return out


def read_geometries(res, base=0):
    """All four LOD arrays are real; +0xa0 is a byte-identical ALIAS of +0x50 and must NOT be walked
    (it would double every mesh). We emit only the High group, which is what the importer reads.
    base: see read_shaders."""
    geos = []
    mh_p = res.ptr(base + 0x50)
    buf, mh = res.deref(mh_p, 0x10)
    if buf is None:
        return geos
    marr_p, nmod = res.u32(mh + 0x00), res.u16(mh + 0x08)
    mbuf, ma = res.deref(marr_p, nmod * 8)
    if mbuf is None:
        return geos
    for mi in range(nmod):
        mp = res.u32(ma + mi * 8)
        _b, m = res.deref(mp, 0x30)
        if _b is None:
            continue
        garr_p, ngeo = res.u32(m + 0x08), res.u16(m + 0x10)
        gb_p = res.u32(m + 0x18)
        gbuf, ga = res.deref(garr_p, ngeo * 8)
        if gbuf is None:
            continue
        for gi in range(ngeo):
            gp = res.u32(ga + gi * 8)
            _b2, g = res.deref(gp, 0x80)
            if _b2 is None:
                continue
            vb_p, ib_p = res.u32(g + 0x18), res.u32(g + 0x38)
            idx_count = res.u32(g + 0x58)
            vcnt = res.u16(g + 0x60)
            stride = res.u16(g + 0x70)      # U16 - a u32 read yields 983,100 on skinned meshes
            _b3, vb = res.deref(vb_p, 0x40)
            if _b3 is None:
                continue
            vdata_p, fvf_p = res.u32(vb + 0x10), res.u32(vb + 0x30)
            _b4, fvf = res.deref(fvf_p, 0x10)
            if _b4 is None:
                continue
            mask = res.u32(fvf + 0x00)
            nibbles = struct.unpack_from("<Q", res.sys, fvf + 0x08)[0]
            fields, _ = build_decl(mask, nibbles, stride)
            vlines = decode_vertices(res, vdata_p, vcnt, stride, fields)
            _b5, ib = res.deref(ib_p, 0x20)
            if _b5 is None:
                continue
            idata_p = res.u32(ib + 0x10)
            ibuf, io = res.deref(idata_p, idx_count * 2)
            if ibuf is None:
                continue
            indices = list(struct.unpack_from("<%dH" % idx_count, ibuf, io))
            # shaderMap: u16 per geometry -> shader index (often non-identity in real files)
            shader_idx = gi
            smap_p = res.u32(m + 0x20)
            sbuf, so = res.deref(smap_p, ngeo * 2)
            if sbuf is not None:
                shader_idx = struct.unpack_from("<H", sbuf, so + gi * 2)[0]
            geos.append({
                "shader": shader_idx,
                "layout": [f[1] for f in fields],
                "verts": vlines,
                "indices": indices,
            })
        # geoBounds is N+1 pairs (union first) when N>1 - not needed for the minimal XML
        _ = gb_p
    return geos


def read_bounds(res, base=0):
    """Drawable-level bounds/sphere - ExportYtyp FAILS ENTIRELY without these three."""
    f = lambda o: struct.unpack_from("<f", res.sys, base + o)[0]
    return {
        "sphere_c": (f(0x20), f(0x24), f(0x28)),
        "sphere_r": f(0x2C),
        "bb_min": (f(0x30), f(0x34), f(0x38)),
        "bb_max": (f(0x40), f(0x44), f(0x48)),
    }


# ---------------------------------------------------------------- embedded collision

# phBound TYPE codes, all MEASURED (LOG "ydr EMBEDDED phBOUND - DECODED" + the 2026-07-28
# bounds derivation: codes 1/12 named via 571/214 unambiguous yft binary<->reference joins).
# Codes 2/5/6/7/9/11/>13 have never been measured -> BoundsError, never a guess.
BOUND_TYPE_NAMES = {0: "Sphere", 1: "Capsule", 3: "Box", 4: "Geometry", 8: "GeometryBVH",
                    10: "Composite", 12: "Disc", 13: "Cylinder"}
_BOUND_GEOMETRY_TYPES = (4, 8)

# CompositeFlags1/2 share ONE enum; 25 bits named from 1,080 measured (value, name-list)
# pairs with zero conflicts, and popcount==len(names) in 1,080/1,080 proves the names render
# in ASCENDING BIT ORDER. Bits 0/8/14/18/28/29/31 exist but were never observed set.
BOUND_COMPOSITE_FLAG_BITS = {
    1: "MAP_WEAPON", 2: "MAP_DYNAMIC", 3: "MAP_ANIMAL", 4: "MAP_COVER", 5: "MAP_VEHICLE",
    6: "VEHICLE_NOT_BVH", 7: "VEHICLE_BVH", 9: "PED", 10: "RAGDOLL", 11: "ANIMAL",
    12: "ANIMAL_RAGDOLL", 13: "OBJECT", 15: "PLANT", 16: "PROJECTILE", 17: "EXPLOSION",
    19: "FOLIAGE", 20: "FORKLIFT_FORKS", 21: "TEST_WEAPON", 22: "TEST_CAMERA", 23: "TEST_AI",
    24: "TEST_SCRIPT", 25: "TEST_VEHICLE_WHEEL", 26: "GLASS", 27: "MAP_RIVER", 30: "MAP_STAIRS",
}

# material Flags = bits 24-39 of the 8-byte material record (8,813 measured pairs, zero
# conflicts). Window bit 11 was never observed set.
BOUND_MATERIAL_FLAG_BITS = {
    0: "FLAG_STAIRS", 1: "FLAG_NOT_CLIMBABLE", 2: "FLAG_SEE_THROUGH", 3: "FLAG_SHOOT_THROUGH",
    4: "FLAG_NOT_COVER", 5: "FLAG_WALKABLE_PATH", 6: "FLAG_NO_CAM_COLLISION",
    7: "FLAG_SHOOT_THROUGH_FX", 8: "FLAG_NO_DECAL", 9: "FLAG_NO_NAVMESH", 10: "FLAG_NO_RAGDOLL",
    12: "FLAG_NO_PTFX", 13: "FLAG_TOO_STEEP_FOR_PLAYER", 14: "FLAG_NO_NETWORK_SPAWN",
    15: "FLAG_NO_CAM_COLLISION_ALLOW_CLIPPING",
}

# header bytes with no bound XML field: only zero ever measured (the four still-unbound
# always-0 XML fields live somewhere here, so a non-zero byte would make an emitted 0 wrong).
_BOUND_HEADER_ZERO_BYTES = (0x11, 0x12, 0x13, 0x18, 0x19, 0x1A, 0x1B, 0x1C, 0x1D, 0x1E, 0x1F,
                            0x4D, 0x4E, 0x5D, 0x5E, 0x5F)


class BoundsError(ValueError):
    """Loud refusal - the input holds a value this emitter has no measurement for."""


def _bound_entry_list(tag, rows, ind):
    """MEASURED: comma-tuple list elements (Vertices/MaterialColours/VertexColours) render
    INLINE with one entry, block with one entry per line at ind+1 otherwise."""
    if len(rows) == 1:
        return ["%s<%s>%s</%s>" % (ind, tag, rows[0], tag)]
    return (["%s<%s>" % (ind, tag)] + ["%s %s" % (ind, r) for r in rows]
            + ["%s</%s>" % (ind, tag)])


def _bound_flags_text(value, table, what, ctx):
    if value == 0:
        return "NONE"
    names = []
    for b in range(32):
        if (value >> b) & 1:
            n = table.get(b)
            if n is None:
                raise BoundsError(f"{ctx}: {what} bit {b} set (value 0x{value:08x}) but "
                                  f"UNNAMED - refusing rather than dropping a filter bit")
            names.append(n)
    return ", ".join(names)


def _bound_deref(res, tagged, need, what, ctx):
    buf, o = res.deref(tagged, need)
    if buf is None:
        raise BoundsError(f"{ctx}: {what} pointer 0x{tagged:08x} does not resolve")
    return buf, o


def _bound_header_lines(res, off, ind, ctx):
    """The 17 header elements every bound type carries, in reference order. Bindings:
    +0x14 SphereRadius | +0x20 BoxMax +0x2C Margin | +0x30 BoxMin +0x3C u32 UnkType |
    +0x40 BoxCenter +0x4C u8 MaterialIndex +0x4F u8 UnkFlags | +0x50 SphereCenter
    +0x5C u8 PolyFlags | +0x60 Inertia +0x6C Volume (all measured - see the LOG entry)."""
    for b in _BOUND_HEADER_ZERO_BYTES:
        if res.sys[off + b]:
            raise BoundsError(f"{ctx}: header byte +0x{b:02x} = 0x{res.sys[off + b]:02x} "
                              f"(only zero ever measured there)")
    f = lambda o: struct.unpack_from("<f", res.sys, off + o)[0]
    v3 = lambda o: struct.unpack_from("<3f", res.sys, off + o)
    L = []
    for tag, o in (("BoxMin", 0x30), ("BoxMax", 0x20), ("BoxCenter", 0x40),
                   ("SphereCenter", 0x50)):
        x, y, z = v3(o)
        L.append('%s<%s x="%s" y="%s" z="%s" />' % (ind, tag, fmt_num(x), fmt_num(y),
                                                    fmt_num(z)))
    L.append('%s<SphereRadius value="%s" />' % (ind, fmt_num(f(0x14))))
    L.append('%s<Margin value="%s" />' % (ind, fmt_num(f(0x2C))))
    L.append('%s<Volume value="%s" />' % (ind, fmt_num(f(0x6C))))
    ix, iy, iz = v3(0x60)
    L.append('%s<Inertia x="%s" y="%s" z="%s" />' % (ind, fmt_num(ix), fmt_num(iy),
                                                     fmt_num(iz)))
    L.append('%s<MaterialIndex value="%d" />' % (ind, res.sys[off + 0x4C]))
    for tag in ("MaterialColourIndex", "ProceduralID", "RoomID", "PedDensity"):
        L.append('%s<%s value="0" />' % (ind, tag))        # zero-checked lanes above
    L.append('%s<UnkFlags value="%d" />' % (ind, res.sys[off + 0x4F]))
    L.append('%s<PolyFlags value="%d" />' % (ind, res.sys[off + 0x5C]))
    L.append('%s<UnkType value="%d" />' % (ind, res.u32(off + 0x3C)))
    return L


def _bound_geometry_lines(res, off, ind, ctx):
    """Geometry / GeometryBVH payload. Record map (all measured): +0x88 polys (16 B) ·
    +0x90 Quantum vec3 (.w = UnkFloat1) · +0xA0 CenterGeom (.w = UnkFloat2) · +0xB0 verts
    (s16 x3; world_rel = s16 * Quantum in float32) · +0xB8 VertexColours · +0xD0/+0xD4
    vert/poly counts · +0xF0 materials (8 B) · +0xF8 MaterialColours · +0x118 per-poly
    material u8 · +0x120/+0x121 u8 material/materialcolour counts. Polygon type = low 3
    bits of byte 0: 0 Triangle / 1 Sphere / 2 Capsule / 3 Box / 4 Cylinder."""
    f = lambda o: struct.unpack_from("<f", res.sys, off + o)[0]
    gx, gy, gz = struct.unpack_from("<3f", res.sys, off + 0xA0)
    L = ['%s<GeometryCenter x="%s" y="%s" z="%s" />' % (ind, fmt_num(gx), fmt_num(gy),
                                                        fmt_num(gz)),
         '%s<UnkFloat1 value="%s" />' % (ind, fmt_num(f(0x9C))),
         '%s<UnkFloat2 value="%s" />' % (ind, fmt_num(f(0xAC)))]
    nverts, npolys = res.u32(off + 0xD0), res.u32(off + 0xD4)
    nmat, nmatcol = res.sys[off + 0x120], res.sys[off + 0x121]
    if not (0 < nverts <= 0x8000) or not (0 < npolys <= 0x100000) or nmat == 0:
        raise BoundsError(f"{ctx}: implausible counts verts={nverts} polys={npolys} "
                          f"mats={nmat}")
    mb, mo = _bound_deref(res, res.u32(off + 0xF0), nmat * 8, "materials", ctx)
    L.append("%s<Materials>" % ind)
    for i in range(nmat):
        u = struct.unpack_from("<Q", mb, mo + i * 8)[0]
        L += ["%s <Item>" % ind,
              '%s  <Type value="%d" />' % (ind, u & 0xFF),
              '%s  <ProceduralID value="%d" />' % (ind, (u >> 8) & 0xFF),
              '%s  <RoomID value="%d" />' % (ind, (u >> 16) & 0x1F),
              '%s  <PedDensity value="%d" />' % (ind, (u >> 21) & 0x7),
              "%s  <Flags>%s</Flags>" % (ind, _bound_flags_text(
                  (u >> 24) & 0xFFFF, BOUND_MATERIAL_FLAG_BITS, "material flag", ctx)),
              '%s  <MaterialColourIndex value="%d" />' % (ind, (u >> 40) & 0xFF),
              '%s  <Unk value="%d" />' % (ind, u >> 48),
              "%s </Item>" % ind]
    L.append("%s</Materials>" % ind)
    mc_p = res.u32(off + 0xF8)
    if nmatcol or mc_p:
        if not (nmatcol and mc_p):
            raise BoundsError(f"{ctx}: MaterialColours count/pointer disagree")
        cb, co = _bound_deref(res, mc_p, nmatcol * 4, "material colours", ctx)
        L += _bound_entry_list("MaterialColours",
                               ["%d, %d, %d, %d" % tuple(cb[co + i * 4: co + i * 4 + 4])
                                for i in range(nmatcol)], ind)
    q = struct.unpack_from("<3f", res.sys, off + 0x90)
    vb, vo = _bound_deref(res, res.u32(off + 0xB0), nverts * 6, "vertices", ctx)
    rows = []
    for i in range(nverts):
        sx, sy, sz = struct.unpack_from("<3h", vb, vo + i * 6)
        rows.append("%s, %s, %s" % (fmt_num(sx * q[0]), fmt_num(sy * q[1]),
                                    fmt_num(sz * q[2])))
    L += _bound_entry_list("Vertices", rows, ind)
    vc_p = res.u32(off + 0xB8)
    if vc_p:
        cb, co = _bound_deref(res, vc_p, nverts * 4, "vertex colours", ctx)
        L += _bound_entry_list("VertexColours",
                               ["%d, %d, %d, %d" % tuple(cb[co + i * 4: co + i * 4 + 4])
                                for i in range(nverts)], ind)
    pb, po = _bound_deref(res, res.u32(off + 0x88), npolys * 16, "polygons", ctx)
    pmb, pmo = _bound_deref(res, res.u32(off + 0x118), npolys, "poly materials", ctx)
    L.append("%s<Polygons>" % ind)
    for i in range(npolys):
        rec = po + i * 16
        m = pmb[pmo + i]
        w = struct.unpack_from("<8H", pb, rec)
        ptype = pb[rec] & 7
        if ptype == 0:
            v = [(w[2 + j] & 0x7FFF, w[2 + j] >> 15) for j in range(3)]
            L.append('%s <Triangle m="%d" v1="%d" v2="%d" v3="%d" f1="%d" f2="%d" f3="%d" />'
                     % (ind, m, v[0][0], v[1][0], v[2][0], v[0][1], v[1][1], v[2][1]))
        elif ptype == 1:
            L.append('%s <Sphere m="%d" v="%d" radius="%s" />'
                     % (ind, m, w[1], fmt_num(struct.unpack_from("<f", pb, rec + 4)[0])))
        elif ptype == 2:
            L.append('%s <Capsule m="%d" v1="%d" v2="%d" radius="%s" />'
                     % (ind, m, w[1], w[4], fmt_num(struct.unpack_from("<f", pb, rec + 4)[0])))
        elif ptype == 3:
            L.append('%s <Box m="%d" v1="%d" v2="%d" v3="%d" v4="%d" />'
                     % (ind, m, w[2], w[3], w[4], w[5]))
        elif ptype == 4:
            L.append('%s <Cylinder m="%d" v1="%d" v2="%d" radius="%s" />'
                     % (ind, m, w[1], w[4], fmt_num(struct.unpack_from("<f", pb, rec + 4)[0])))
        else:
            raise BoundsError(f"{ctx}: polygon {i} has UNMEASURED type code {ptype}")
    L.append("%s</Polygons>" % ind)
    return L


def _bound_lines(res, off, ind, tag, ctx, extra=None, depth=0):
    if depth > 4:
        raise BoundsError(f"{ctx}: composite nesting depth {depth} never measured")
    t = res.sys[off + 0x10]
    name = BOUND_TYPE_NAMES.get(t)
    if name is None:
        raise BoundsError(f"{ctx}: UNMEASURED bound type code {t} at sys+0x{off:x}")
    L = ['%s<%s type="%s">' % (ind, tag, name)]
    inner = ind + " "
    L += _bound_header_lines(res, off, inner, ctx)
    if extra:
        L += extra
    if t in _BOUND_GEOMETRY_TYPES:
        L += _bound_geometry_lines(res, off, inner, ctx)
    elif t == 10:
        n = res.u16(off + 0xA0)
        carr_p, tr_p, fl_p = res.u32(off + 0x70), res.u32(off + 0x78), res.u32(off + 0x90)
        cb, co = _bound_deref(res, carr_p, n * 8, "composite children", ctx)
        if tr_p:
            tb, to = _bound_deref(res, tr_p, n * 64, "composite transforms", ctx)
        elif n:
            raise BoundsError(f"{ctx}: composite has {n} children but no transform array")
        fb = fo = None
        if fl_p:                       # flags OMITTED entirely when absent (measured: yft)
            fb, fo = _bound_deref(res, fl_p, n * 8, "composite flags", ctx)
        L.append("%s<Children>" % inner)
        for i in range(n):
            cp = struct.unpack_from("<I", cb, co + i * 8)[0]
            if cp == 0:
                L.append('%s <Item type="None" />' % inner)
                continue
            _, ch = _bound_deref(res, cp, 0x70, f"child {i}", ctx)
            ci2 = inner + "  "
            mv = struct.unpack_from("<16f", tb, to + i * 64)
            extra_i = ["%s<CompositeTransform>" % ci2]
            for r in range(4):         # stored 4x(3f+pad); 4th column SYNTHESISED 0,0,0,1
                extra_i.append("%s %s %s %s %s" % (ci2, fmt_num(mv[r * 4]),
                                                   fmt_num(mv[r * 4 + 1]),
                                                   fmt_num(mv[r * 4 + 2]),
                                                   "1" if r == 3 else "0"))
            extra_i.append("%s</CompositeTransform>" % ci2)
            if fb is not None:
                f1, f2 = struct.unpack_from("<II", fb, fo + i * 8)
                extra_i.append("%s<CompositeFlags1>%s</CompositeFlags1>" % (
                    ci2, _bound_flags_text(f1, BOUND_COMPOSITE_FLAG_BITS,
                                           "CompositeFlags1", ctx)))
                extra_i.append("%s<CompositeFlags2>%s</CompositeFlags2>" % (
                    ci2, _bound_flags_text(f2, BOUND_COMPOSITE_FLAG_BITS,
                                           "CompositeFlags2", ctx)))
            L += _bound_lines(res, ch, inner + " ", "Item", f"{ctx} child {i}",
                              extra=extra_i, depth=depth + 1)
        L.append("%s</Children>" % inner)
    # primitives (Sphere/Capsule/Box/Disc/Cylinder): header only - measured
    L.append("%s</%s>" % (ind, tag))
    return L


def bounds_lines(res, base=0, name="?"):
    """The <Bounds> element lines for the drawable at system offset `base`, [] when it has
    no bound. Raises BoundsError - loudly, naming the file - on anything unmeasured."""
    tagged = res.u32(base + 0xC8)
    if res.u32(base + 0xCC):
        # The +0xC8 bound-pointer law was measured on STANDALONE ydr (high dword 0 in
        # 3,479/3,479). Fragment-embedded drawables carry other data in this slot - their
        # collision lives in the fragment's own phys structures, not the drawable tail - so a
        # non-zero high dword means "not a ydr-style bound here", never a bound to refuse.
        # On real ydr this branch is unreachable by measurement.
        return []
    if tagged == 0:
        return []
    _, off = _bound_deref(res, tagged, 0x70, "root bound", name)
    return _bound_lines(res, off, " ", "Bounds", name)


def boundsfile_lines(res, name="?"):
    """Standalone bound (.ybn, RSC7 v43; root phBound at system offset 0) as a full
    BoundsFile document - oracle-validated against 183 name-matched reference exports."""
    res.require_version(43, "bounds file")
    L = ['<?xml version="1.0" encoding="UTF-8"?>', "<BoundsFile>"]
    L += _bound_lines(res, 0, " ", "Bounds", name)
    L.append("</BoundsFile>")
    return L


# ---------------------------------------------------------------- emit

def esc(s):
    for a, b in (("&", "&amp;"), ("<", "&lt;"), (">", "&gt;"), ('"', "&quot;")):
        s = s.replace(a, b)
    return s


def drawable_lines(res, name, base=0):
    """The <Drawable> BODY (Name/bounds/ShaderGroup/DrawableModelsHigh) as lines with the standalone
    file's one-space indent. Shared: the ydr wrapper adds declaration+root; a dictionary converter
    (ydd/yft) wraps each entry as <Item> and re-indents. Whitespace is free to the consumer -
    FXmlFile tokenises on any whitespace - so only token count and order matter."""
    shaders = read_shaders(res, base)
    geos = read_geometries(res, base)
    if not geos:
        raise ValueError("no geometry decoded")
    b = read_bounds(res, base)
    ff = fmt_float
    L = []
    L.append(" <Name>%s</Name>" % esc(name))
    L.append(' <BoundingSphereCenter x="%s" y="%s" z="%s" />' % tuple(ff(v) for v in b["sphere_c"]))
    L.append(' <BoundingSphereRadius value="%s" />' % ff(b["sphere_r"]))
    L.append(' <BoundingBoxMin x="%s" y="%s" z="%s" />' % tuple(ff(v) for v in b["bb_min"]))
    L.append(' <BoundingBoxMax x="%s" y="%s" z="%s" />' % tuple(ff(v) for v in b["bb_max"]))
    L.append(" <ShaderGroup>")
    emb = embedded_textures(res, base)
    if emb:
        # The drawable's own textures, emitted so a consumer can see and import them. Pixel
        # sidecars are written alongside by the caller (quarry.to_interchange_xml).
        L.append("  <TextureDictionary>")
        for t in emb:
            L += ["   <Item>",
                  "    <Name>%s</Name>" % esc(t["name"]),
                  '    <Unk32 value="0" />',
                  "    <Usage>%s</Usage>" % t["usage"],
                  "    <UsageFlags>0</UsageFlags>",
                  '    <ExtraFlags value="0" />',
                  '    <Width value="%d" />' % t["width"],
                  '    <Height value="%d" />' % t["height"],
                  '    <MipLevels value="%d" />' % t["mips"],
                  "    <Format>%s</Format>" % t["xml_fmt"],
                  "    <FileName>%s.dds</FileName>" % esc(t["name"]),
                  "   </Item>"]
        L.append("  </TextureDictionary>")
    L.append("  <Shaders>")
    if not shaders:
        shaders = [("default", 0, [], [])]
    for preset, bucket, texs, vals in shaders:
        L.append("   <Item>")
        L.append("    <Name>%s</Name>" % esc(preset))
        L.append('    <RenderBucket value="%d" />' % bucket)
        L.append("    <Parameters>")
        for sampler, t in texs:
            L.append('     <Item name="%s" type="Texture"><Name>%s</Name></Item>'
                     % (sampler, esc(t)))
        for pname, rows in vals:
            L.append('     <Item name="%s" type="Vector" count="%d">' % (pname, len(rows)))
            for (x, y, z, wv) in rows:
                L.append('      <Value x="%s" y="%s" z="%s" w="%s" />'
                         % (ff(x), ff(y), ff(z), ff(wv)))
            L.append("     </Item>")
        L.append("    </Parameters>")
        L.append("   </Item>")
    L.append("  </Shaders>")
    L.append(" </ShaderGroup>")
    L.append(" <DrawableModelsHigh>")
    L.append("  <Item>")
    L.append("   <Geometries>")
    for g in geos:
        L.append("    <Item>")
        L.append('     <ShaderIndex value="%d" />' % g["shader"])
        L.append("     <VertexBuffer>")
        L.append('      <Layout type="GTAV1">')
        for nm in g["layout"]:
            L.append("       <%s />" % nm)
        L.append("      </Layout>")
        L.append("      <Data>")
        L.extend("       " + v for v in g["verts"])
        L.append("      </Data>")
        L.append("     </VertexBuffer>")
        L.append("     <IndexBuffer>")
        idx = g["indices"]
        L.append("      <Data>")
        for i in range(0, len(idx), 24):
            L.append("       " + " ".join(str(x) for x in idx[i:i + 24]))
        L.append("      </Data>")
        L.append("     </IndexBuffer>")
        L.append("    </Item>")
    L.append("   </Geometries>")
    L.append("  </Item>")
    L.append(" </DrawableModelsHigh>")
    # embedded collision - flows to ydd2xml/yft2xml automatically since they call
    # drawable_lines with their entry's base offset (the bound ptr is base-relative
    # at +0xC8; a drawable without a bound contributes nothing)
    L.extend(bounds_lines(res, base, name))
    return L


def to_xml(res, name):
    res.require_version(165, "Legacy drawable")
    L = ['<?xml version="1.0" encoding="UTF-8"?>', "<Drawable>"]
    L.extend(drawable_lines(res, name))
    L.append("</Drawable>")
    return "\n".join(L) + "\n"


def convert(path):
    res = Res(path)
    stem = os.path.splitext(os.path.basename(path))[0]
    # real drawables name themselves "<stem>.#dr"; keep the convention
    inner = res.cstr(res.ptr(0xA8)) or (stem + ".#dr")
    return to_xml(res, inner), stem


def main():
    ap = argparse.ArgumentParser(prog="ydr2xml")
    ap.add_argument("files", nargs="*")
    ap.add_argument("--out", help="output directory for <stem>.ydr.xml")
    ap.add_argument("--selftest", action="store_true",
                    help="convert and re-parse in memory; write nothing")
    a = ap.parse_args()
    if not a.files:
        ap.error("give at least one .ydr")
    ok = fail = 0
    for p in a.files:
        try:
            xml, stem = convert(p)
        except Exception as e:
            print(f"FAIL {os.path.basename(p)}: {type(e).__name__}: {e}")
            fail += 1
            continue
        if a.selftest:
            import xml.etree.ElementTree as ET
            root = ET.fromstring(xml)
            ng = len(root.findall("./DrawableModelsHigh/Item/Geometries/Item"))
            ns = len(root.findall("./ShaderGroup/Shaders/Item"))
            print(f"OK   {os.path.basename(p):<44} {ng:3} geos  {ns:3} shaders  "
                  f"{len(xml):>10,} B xml")
        else:
            if not a.out:
                ap.error("--out is required unless --selftest")
            os.makedirs(a.out, exist_ok=True)
            dst = os.path.join(a.out, stem + ".ydr.xml")
            open(dst, "w", encoding="utf-8", newline="\n").write(xml)
            print(f"OK   {os.path.basename(p)} -> {dst}  ({len(xml):,} B)")
        ok += 1
    print(f"\n{ok} converted, {fail} failed")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
