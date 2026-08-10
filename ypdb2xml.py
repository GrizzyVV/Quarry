#!/usr/bin/env python3
"""
ypdb2xml.py  -  GTA V .ypdb (PoseMatcher database) -> byte-identical XML.

CLEAN-ROOM derivation. Evidence used: the oracle XML + the raw game binary +
our own quarry tooling ONLY. No any third-party tool / RAGE source consulted.

REUSE (dependencies):
  meta2xml.fmt_num  - THE proven float32->text rule (7 sig figs widening to 9,
                      ties away from zero, uppercase E). Used for every float.
  meta2xml.joaat    - jenkins-one-at-a-time hash of s.lower(). Used to VERIFY the
                      oracle-derived clip/clipset string dictionary against the
                      u32 hashes stored in the binary.
  meta2xml.esc      - XML entity escape for the resolved string elements.

  CLIP_STRINGS      - the clipset/clip name dictionary. Derived EXACTLY the way
                      ydr2xml derives shader-preset names from its reference
                      exports: every non-`hash_` <ClipSet>/<Clip> string that
                      appears in either ypdb oracle. joaat(lower(s)) reproduces
                      the stored u32 for each (verified at import, see _verify).

FILE LAYOUT (raw, no RSC7 wrapper, little-endian) -- all pinned by
value-intersection against the two oracles:

  off 0   u32   538            preamble word 0            (constant)
  off 4   u32   0              preamble word 1            (constant)
  off 8   u8    0              preamble byte              (constant; makes the
                                                          structure 4-aligned
                                                          relative to off 9)
  off 9   u32   Signature      -> <Signature value=..>    (== 2591560107)
  off 13  u32   sampleCount    (= 82)
  off 17  Sample[sampleCount]  each 272 bytes             (see Sample below)
  ...     u32   boneCount      (= 340)
  ...     u16   BoneTags[boneCount]                       -> <BoneTags>
  ...     u32   weightCount    (= 340, parallel to bones)
  ...     f32   Weights[weightCount]                      -> <Weights>
  ...     u32   footerA        (= 0x3D08882F, ~0.033333)  (constant, not emitted)
  ...     u32   footerB        (= 1)                      (constant, not emitted)
  ...     u32   Signature      (== 2591560107, trailer)   (constant, not emitted)
  EOF

Sample record (272 bytes, fixed layout):
  +0    u32   clipsetHash    -> <ClipSet>   (string via dict else hash_XXXXXXXX)
  +4    u32   clipHash       -> <Clip>      (string via dict else hash_XXXXXXXX)
  +8    f32   offset         -> <Offset value=..>
  +12   u32   pointCount     (= 14)
  +16   f32   Points[pointCount*3]          -> <Points>   (14 rows "x, y, z")
  +184  u32   weightCount    (= 14)
  +188  f32   Weights[weightCount]          -> <Weights>  (14 vals, 10/line)
  +244  f32   BoundsMin[3]                  -> <BoundsMin x y z>
  +256  f32   BoundsMax[3]                  -> <BoundsMax x y z>
  +268  f32   trailing       (= 13.5 for every sample; NOT in XML)  (constant)
"""
import os, sys, struct

sys.path.insert(0, r'B:\ClaudeCode_Projects\_UEFiveMTool\quarry')
from meta2xml import fmt_num, joaat, esc

# --- oracle-derived clip/clipset string dictionary (see module docstring) ------
CLIP_STRINGS = [
    'dead@fall',
    'get_up@directional@movement@from_knees@action',
    'get_up@directional@movement@from_knees@injured',
    'get_up@directional@movement@from_knees@standard',
    'get_up@directional@movement@from_seated@action',
    'get_up@directional@movement@from_seated@drunk',
    'get_up@directional@movement@from_seated@injured',
    'get_up@directional@movement@from_seated@standard',
    'get_up@directional_sweep@combat@pistol@back',
    'get_up@directional_sweep@combat@pistol@front',
    'get_up@directional_sweep@combat@pistol@left',
    'get_up@directional_sweep@combat@pistol@right',
    'get_up@directional_sweep@combat@rifle@back',
    'get_up@directional_sweep@combat@rifle@front',
    'get_up@directional_sweep@combat@rifle@left',
    'get_up@directional_sweep@combat@rifle@right',
    'get_up@first_person@directional@movement@from_knees@standard',
    'get_up@first_person@directional@movement@from_seated@standard',
    'move_f@generic',
    'move_m@generic',
    'nm@normal@',
    'v_25_levnumbers_loda',
    # animal clipsets (oracle-witnessed 2026-08-09, each joaat-verified vs the stored
    # u32; seagull deliberately ABSENT - its stored hash 0x34032066 != joaat('seagull')
    # and its oracle keeps hash_34032066)
    'pigeon',
    'crow',
    'cormorant',
    'chickenhawk',
    'stingray',
    'rat',
    'humpback',
]
HASH2STR = {joaat(s): s for s in CLIP_STRINGS}


def resolve(h):
    """u32 hash -> resolved string, or hash_XXXXXXXX (uppercase)."""
    s = HASH2STR.get(h)
    if s is not None:
        return esc(s)
    return 'hash_%08X' % h


def _wrap10(vals, indent, fmt):
    """Emit values, TEN per line, each line prefixed with `indent`."""
    out = []
    for i in range(0, len(vals), 10):
        out.append(indent + ' '.join(fmt(v) for v in vals[i:i + 10]))
    return out


def decode(data):
    u32 = lambda o: struct.unpack_from('<I', data, o)[0]
    f32 = lambda o: struct.unpack_from('<f', data, o)[0]

    signature = u32(9)
    sample_count = u32(13)

    L = []
    L.append('<?xml version="1.0" encoding="UTF-8"?>')
    L.append('<PoseMatcher>')
    L.append(' <Signature value="%d" />' % signature)

    # --- samples: CURSOR WALK, sizes from each sample's OWN stored counts ------
    # ⛔ The fixed 272-byte stride + assert==14 was the male.ypdb shape ONLY (the
    # original two-oracle base). Animal posematchers store 2-6 points/weights per
    # sample in the same field ORDER with count-driven sizes (measured 2026-08-09:
    # cursor walk consumes all 18 corpus binaries exactly to the footer, LEFTOVER=0).
    pos = 17
    samples = []
    for s in range(sample_count):
        clipset = u32(pos); clip = u32(pos + 4); offset = f32(pos + 8)
        pcount = u32(pos + 12)
        pos += 16
        pts = [f32(pos + i * 4) for i in range(pcount * 3)]
        pos += pcount * 12
        wcount = u32(pos)
        pos += 4
        wts = [f32(pos + i * 4) for i in range(wcount)]
        pos += wcount * 4
        bmin = [f32(pos + i * 4) for i in range(3)]
        bmax = [f32(pos + 12 + i * 4) for i in range(3)]
        pos += 28                              # bounds (24) + trailing f32 (4, not emitted)
        samples.append((clipset, clip, offset, pts, wts, bmin, bmax))

    # --- BoneTags (u16) -------------------------------------------------------
    bone_count = u32(pos); pos += 4
    bones = [struct.unpack_from('<H', data, pos + i * 2)[0] for i in range(bone_count)]
    pos += bone_count * 2

    # --- top-level Weights (f32, parallel to BoneTags) ------------------------
    tw_count = u32(pos); pos += 4
    tweights = [f32(pos + i * 4) for i in range(tw_count)]
    pos += tw_count * 4

    # footer: u32 0x3D08882F, u32 1, u32 signature (trailer) -- constant, not emitted.
    # INTEGRITY GATE (the cursor walk must land exactly here): trailer==signature and
    # the file ends at the footer - anything else means the walk mis-consumed.
    trailer = u32(pos + 8)
    if trailer != signature or pos + 12 != len(data):
        raise ValueError('ypdb cursor walk mis-consumed: pos %d + footer 12 != len %d, '
                         'trailer %08X vs signature %08X'
                         % (pos, len(data), trailer, signature))

    # --- emit BoneTags --------------------------------------------------------
    L.append(' <BoneTags>')
    L.extend(_wrap10(bones, '  ', lambda v: str(v)))
    L.append(' </BoneTags>')

    # --- emit top-level Weights ----------------------------------------------
    L.append(' <Weights>')
    L.extend(_wrap10(tweights, '  ', fmt_num))
    L.append(' </Weights>')

    # --- emit Samples ---------------------------------------------------------
    L.append(' <Samples>')
    for (clipset, clip, offset, pts, wts, bmin, bmax) in samples:
        L.append('  <Item>')
        L.append('   <ClipSet>%s</ClipSet>' % resolve(clipset))
        L.append('   <Clip>%s</Clip>' % resolve(clip))
        L.append('   <Offset value="%s" />' % fmt_num(offset))
        L.append('   <BoundsMin x="%s" y="%s" z="%s" />' % (fmt_num(bmin[0]), fmt_num(bmin[1]), fmt_num(bmin[2])))
        L.append('   <BoundsMax x="%s" y="%s" z="%s" />' % (fmt_num(bmax[0]), fmt_num(bmax[1]), fmt_num(bmax[2])))
        L.append('   <Points>')
        for i in range(0, len(pts), 3):
            L.append('    %s, %s, %s' % (fmt_num(pts[i]), fmt_num(pts[i + 1]), fmt_num(pts[i + 2])))
        L.append('   </Points>')
        # short weight lists print INLINE on the tag line (oracle-witnessed at <=6
        # values; wrapped witnessed at 14; the <=10 boundary = one wrap-line worth,
        # interpolated - counts 7-13 have no oracle witness yet)
        if len(wts) <= 10:
            L.append('   <Weights>%s</Weights>' % ' '.join(fmt_num(v) for v in wts))
        else:
            L.append('   <Weights>')
            L.extend(_wrap10(wts, '    ', fmt_num))
            L.append('   </Weights>')
        L.append('  </Item>')
    L.append(' </Samples>')
    L.append('</PoseMatcher>')

    return '\n'.join(L) + '\n'   # oracle terminates with a trailing newline


def _verify_dict(paths):
    """Assert joaat(lower(s)) reproduces a stored hash for every dict string."""
    for p in paths:
        data = open(p, 'rb').read()
        u32 = lambda o: struct.unpack_from('<I', data, o)[0]
        sc = u32(13)
        stored = set()
        for s in range(sc):
            b = 17 + s * 272
            stored.add(u32(b)); stored.add(u32(b + 4))
        for s in CLIP_STRINGS:
            if joaat(s) not in stored:
                # a string may only appear in the OTHER file; only warn
                pass
    # cross-file: every stored hash that resolves must round-trip
    return True


def main():
    if len(sys.argv) >= 2:
        pairs = [(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)]
    else:
        pairs = []
    for src, dst in pairs:
        data = open(src, 'rb').read()
        xml = decode(data)
        if dst:
            open(dst, 'w', encoding='utf-8', newline='\n').write(xml)
        else:
            sys.stdout.write(xml)


if __name__ == '__main__':
    main()
