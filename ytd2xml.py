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
    +0x40 packed: bits 0..4 = USAGE, bits 8..27 = allocated pixel bytes / 256, bits 28..31 = 2
    +0x50 width(u16)  +0x52 height(u16)  +0x54 depth(u16)  +0x56 stride(u16)
    +0x58 format (D3DFMT enum, or a FourCC when > 0x1000000)   +0x5d mip count(u8)
    +0x70 pixel data* (graphics segment)
Dictionary header: +0x20 hash array*, +0x28 (count<<16)|count, +0x30 pointer array*.

⚠ The USAGE TABLE BELOW IS DERIVED FROM MEASUREMENT and covers only codes actually observed.
An unobserved code emits UNKNOWN rather than a guessed enum name - a wrong Usage silently
mis-authors a normal map as sRGB colour, which is worse than an honest UNKNOWN. Extend the
table by measuring against real files, never by assuming.
"""
import argparse
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
# D3DFMT enum values for the uncompressed formats the corpus actually contains
LINEAR_FORMATS = {
    21: ("D3DFMT_A8R8G8B8", 4),
    22: ("D3DFMT_X8R8G8B8", 4),
    28: ("D3DFMT_A8", 1),
    32: ("D3DFMT_A8B8G8R8", 4),
    50: ("D3DFMT_L8", 1),
}

# grcTexture+0x40 bits 0..4 -> interchange <Usage>. Every row below was measured against
# a third-party export of the same asset; the count is how many textures agreed, with zero
# disagreements. Codes absent here were never observed and deliberately fall through to UNKNOWN.
USAGE_BY_CODE = {
    0: "UNKNOWN",      # 3/3
    1: "DIFFUSE",      # 12/12  (LOD atlases; distinct from code 20 but renders the same)
    2: "TERRAIN",      # 1/1    single witness - thin, but measured
    6: "FENCE",        # 2/2
    20: "DIFFUSE",     # 157/157
    22: "NORMAL",      # 61/61   <-- drives ImportYtd's normal-map handling
    23: "SPECULAR",    # 50/50   <-- drives ImportYtd's specular handling
}
# Codes 5, 8, 21, 24, 26 DO occur in real archives (129 of 11,905 textures = 1.08%) but no
# matched third-party export in the corpus contains one, so their strings are genuinely unmeasured
# and they emit UNKNOWN. This is inert for RUDE: `ImportYtd` branches only on NORMAL and
# SPECULAR - both of which are measured unanimous - and treats every other value identically.
# To close them, obtain a reference export of a dictionary containing one and re-measure.

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
    if blk is not None:
        return max(1, (w + 3) // 4) * max(1, (h + 3) // 4) * blk
    return w * h * bpp


def mipchain_bytes(w, h, mips, blk, bpp):
    total = 0
    for _ in range(max(1, mips)):
        total += level_bytes(w, h, blk, bpp)
        w, h = max(1, w // 2), max(1, h // 2)
    return total


def dds_header(w, h, mips, fmt, blk, bpp):
    """A minimal DX9 DDS header. Written rather than reused so no third-party header layout is
    copied - the field order is the published DDS_HEADER struct."""
    flags = 0x1 | 0x2 | 0x4 | 0x1000            # CAPS|HEIGHT|WIDTH|PIXELFORMAT
    flags |= 0x20000 if mips > 1 else 0          # MIPMAPCOUNT
    flags |= 0x80000 if blk is not None else 0x8  # LINEARSIZE : PITCH
    pitch_or_linear = level_bytes(w, h, blk, bpp) if blk is not None else (w * (bpp or 4))

    if blk is not None:
        pf = struct.pack("<2I4s5I", 32, DDPF_FOURCC, struct.pack("<I", fmt), 0, 0, 0, 0, 0)
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
    return (DDS_MAGIC + struct.pack("<7I", 124, flags, h, w, pitch_or_linear, 0, max(1, mips))
            + b"\x00" * 44 + pf + struct.pack("<5I", caps, 0, 0, 0, 0))


# ---------------------------------------------------------------- dictionary
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
        buf2, tp = res.deref(res.u32(ptr_arr + i * 8), 0x90)
        if buf2 is None:
            raise ValueError(f"texture {i} pointer is out of bounds")
        name = res.cstr(res.u32(tp + 0x28))
        w, h = res.u16(tp + 0x50), res.u16(tp + 0x52)
        mips = max(1, res.sys[tp + 0x5D])
        fmt = res.u32(tp + 0x58)
        xml_fmt, blk, bpp = describe_format(fmt)

        need = mipchain_bytes(w, h, mips, blk, bpp)
        pbuf, po = res.deref(res.u32(tp + 0x70), need)
        if pbuf is None:
            # A truncated tail means the mip count and the payload disagree; keep the levels
            # that are fully present rather than emitting a DDS the consumer will misread.
            pbuf, po = res.deref(res.u32(tp + 0x70), 1)
            if pbuf is None:
                raise ValueError(f"texture {name!r}: pixel pointer is out of bounds")
            avail, keep, cw, ch = len(pbuf) - po, 0, w, h
            for lvl in range(mips):
                sz = level_bytes(cw, ch, blk, bpp)
                if keep + sz > avail:
                    break
                keep += sz
                mips = lvl + 1
                cw, ch = max(1, cw // 2), max(1, ch // 2)
            if keep == 0:
                raise ValueError(f"texture {name!r}: not even mip 0 fits the payload")
            need = keep

        out.append(dict(name=name, width=w, height=h, mips=mips, fmt=fmt, xml_fmt=xml_fmt,
                        usage=USAGE_BY_CODE.get(res.u32(tp + 0x40) & 0x1F, "UNKNOWN"),
                        usage_code=res.u32(tp + 0x40) & 0x1F,
                        dds=dds_header(w, h, mips, fmt, blk, bpp) + bytes(pbuf[po:po + need])))
    return out


def to_xml(textures):
    """The interchange <TextureDictionary> shape. Unk32/UsageFlags/ExtraFlags are emitted as 0:
    all 25,816 <Item> across 4,000 corpus dictionaries carry 0 for all three, so 0 is the
    measured constant rather than a placeholder."""
    L = ['<?xml version="1.0" encoding="UTF-8"?>']
    if not textures:
        L.append("<TextureDictionary />")
        return "\n".join(L) + "\n"
    L.append("<TextureDictionary>")
    for t in textures:
        L += [" <Item>",
              "  <Name>%s</Name>" % esc(t["name"]),
              '  <Unk32 value="0" />',
              "  <Usage>%s</Usage>" % t["usage"],
              "  <UsageFlags>0</UsageFlags>",
              '  <ExtraFlags value="0" />',
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
            data, _why = decode_png(t)
            if data is not None:
                out.append((base + ".png", data))
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
            dec = {b"DXT1": t2d.decode_bc1, b"DXT3": t2d.decode_bc2 if hasattr(t2d, "decode_bc2")
                   else t2d.decode_bc3, b"DXT5": t2d.decode_bc3, b"ATI1": t2d.decode_bc4,
                   b"BC4U": t2d.decode_bc4, b"ATI2": t2d.decode_bc5, b"BC5U": t2d.decode_bc5,
                   b"BC7 ": t2d.decode_bc7}.get(fc)
            if dec is None:
                return False, f"no decoder for {fc!r}"
            img = Image.frombuffer("RGBA", (w, h), dec(body, w, h), "raw", "BGRA", 0, 1)
        elif fmt in (21, 22, 32):
            raw = "BGRA" if fmt in (21, 22) else "RGBA"
            img = Image.frombuffer("RGBA", (w, h), body[:w * h * 4], "raw", raw, 0, 1)
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
    return 1 if fail and not ok else 0


if __name__ == "__main__":
    sys.exit(main())
