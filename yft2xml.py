"""yft2xml - binary GTA V .yft (fragment)  ->  RAGE interchange .yft.xml, VISUAL DRAWABLE ONLY.

WHY THIS EXISTS
18.4% of all map entities (299,565 of 1,627,754 - the whole-game census, the single largest
unimported bucket) reference ASSET_TYPE_FRAGMENT archetypes and spawn as proxy cubes. For MAP
fidelity the fragment's intact visual drawable is what matters; breakage physics, child pieces
and cloth are deliberately out of this converter's v1 scope (proposed to Matt 2026-07-28 -
a proposal, not a ruling; extend when he calls for it).

FIELD MAP - MEASURED over 300 base-game fragments (yft_probe.py, 2026-07-28):
    RSC7 version 162 (300/300)
    +0x30  main gtaDrawable* (drawable-shaped in 300/300; same layout ydr2xml walks - the
           shader group / bounds / model offsets verified by the shape check itself)
    +0x58  fragment name cstr "pack:/<stem>"
    The embedded drawable reuses ydr2xml.drawable_lines(base=...) wholesale - the A/B-proven
    walk; only the fixed header offsets rebase, tagged pointers are segment-absolute.

--------------------------------------------------------------------------------------------
EXTRAS (2026-07-28, agent - the VEHICLE SHOWROOM lane). A fragment is more than one drawable:
a car's WHEEL is a separate CHILD drawable that the game instances at each wheel BONE, so a
vehicle imported as "the main drawable" is a body with no wheels. extras=True additionally
emits, in the reference corpus's own element names and nesting:
    <Drawable><Skeleton><Bones>   every bone: name, tag, index, parent/sibling, flags, T/R/S
    <Physics><LOD1><Groups>       group NAMES only - the group<->bone join behind BoneTag
    <Physics><LOD1><Children>     GroupIndex + BoneTag per child, plus the child <Drawable>
                                  for the children that actually carry geometry
and writes one SIDECAR per geometry-bearing child: a standalone, directly importable
<Drawable> document at `<stem>/<groupName>.ydr.xml`. That is the pixel-sidecar contract ytd
already uses, so quarry.sidecar_into and cmd_resolve carry a `<stem>/` folder with its winning
XML for free - nothing downstream needs teaching.

EXTRAS IS OFF BY DEFAULT AND THE LEGACY PATH IS UNTOUCHED: every new line is inside
`if extras:`, to_xml(res, stem) still means exactly what it meant, and the whole-corpus extract
keeps producing the bytes it produces today. Turn it on per file from the CLI (--extras) or
corpus-wide by flipping EMIT_EXTRAS.

FIELD MAP FOR THE EXTRAS - all MEASURED 2026-07-28 against the reference _processed oracle
(scratchpad lane3 probe_skel / probe_children / probe_childfields / probe_childdraw):
    drawable +0x18 -> crSkeletonData: bone array ptr +0x20, BONE COUNT u16 +0x5E
      ⛔ CORRECTION to LOG "VEHICLE yft RECON", which pinned the count at +0x1A: that offset
         is the count of a DIFFERENT array (the one at crSkeletonData +0x10) and is simply
         ZERO whenever that array is absent. Over 900 random fragments +0x1A is 0 in 751 and
         equals +0x5E in the other 149 - never a third value - so the earlier reading held
         only because it was validated on VEHICLES, exactly the ~17% that carry the aux
         array. Trusting it silently drops the skeleton of every mod part, prop and cloth
         fragment (123 of 156 oracle-comparable files in the first A/B). Against the oracle
         +0x5E is right on 153/156; all three residuals are explained and none is a decode
         error: cyclone2(_hi)'s corpus copy is genuinely a 1-bone model whose bone is named
         "stub", and sc1_23_bunting_v5 / sc1_10_cloth_02 have one real bone that the
         reference export chose not to write. The bone array resolves at the +0x5E count in
         900/900.
    bone = 0x50 B: rot quat +0x00 | translation +0x10 | scale +0x20 | sibling i16 +0x30 |
                   parent i16 +0x32 | name ptr +0x38 | flags u16 +0x40 | TAG u16 +0x44 |
                   index u16 +0x46
      -> 20,837 of 20,895 field checks agree with the oracle across 22 vehicles (99.72%).
         Every residual is one file (adder) whose corpus binary orders three bones
         differently from the oracle export; the bone NAME SETS are identical, so it is
         build drift - the same residual class the ydr and ybn lanes already document.
    fragType +0xF0 -> fragPhysicsLODGroup, +0x10 -> LOD1 (fragPhysicsLOD)
    LOD1 +0xC0 group array ptr (8 B/entry) | +0x11A group count u8    (19/19 files)
    LOD1 +0xD0 child array ptr (8 B/entry) | +0x11E child count u16   (12/12 files)
    fragTypeChild +0x10 GroupIndex u16 (every child of 24 files) | +0xA0 child gtaDrawable*
      -> walking that chain reproduces the oracle's child index, geometry count, index count
         and per-geometry ShaderIndex on 16/16 vehicles (zentorno excepted = build drift).
    BoneTag is NOT stored on the child. It is DERIVED: Groups[GroupIndex].Name names a
    skeleton bone, and that bone's Tag is the child's BoneTag - 376/376 children, 16 vehicles.
    A child drawable has NO ShaderGroup of its own: its <ShaderIndex> values index the
    FRAGMENT's shader group (measured - 0 shaders read at every child base, and the reference
    corpus child <Drawable>s carry no <ShaderGroup> either). The sidecar therefore splices the
    FRAGMENT's ShaderGroup in, or every wheel would import on the default material.

KNOWN V1 GAPS (documented, not silent):
    * embedded ShaderGroup TextureDictionary pixels are not exported yet - fragments whose
      textures live INSIDE the yft import untextured until that lands (same class as the
      per-area texture pass gap).
    * damaged drawables, cloth, the Med/Low/VLow LOD groups, the fragment <BoneTransforms>
      array, <Joints>, <VehicleGlassWindows> and the full per-group physics record: not read.
      The reference corpus retains them for the day they are in scope. (The root
      BoneTransforms array has never been located in the binary - LOG "VEHICLE yft RECON" -
      and the wheel lane does not need it: bone T/R/S composes the same frame.)

Usage:
    python yft2xml.py <in.yft> [...] --out <dir> [--extras]
    python yft2xml.py <in.yft> [...] --selftest [--extras]
"""
import argparse
import os
import re
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ydr2xml import Res, drawable_lines, esc, fmt_float, read_geometries

YFT_VERSION = 162       # measured 300/300 (yft_probe.py)
DRAWABLE_SLOT = 0x30    # measured 300/300
NAME_SLOT = 0x58        # measured; holds "pack:/<stem>"

# ---- extras: skeleton + physics-child chain (offsets measured - see the docstring) ---------

EMIT_EXTRAS = False     # corpus-wide default. OFF = today's bytes, exactly.

SKEL_SLOT = 0x18        # gtaDrawable -> crSkeletonData
SKEL_COUNT = 0x5E       # u16 bone count - see the CORRECTION note in the docstring
SKEL_BONES = 0x20       # -> bone array
BONE_STRIDE = 0x50
PHYS_SLOT = 0xF0        # fragType -> fragPhysicsLODGroup
LOD1_SLOT = 0x10        # fragPhysicsLODGroup -> LOD1
GROUP_ARR, GROUP_COUNT = 0xC0, 0x11A    # ptr / u8
CHILD_ARR, CHILD_COUNT = 0xD0, 0x11E    # ptr / u16
CHILD_GROUP_INDEX = 0x10                # u16 on fragTypeChild
CHILD_DRAWABLE = 0xA0                   # fragTypeChild -> child gtaDrawable*

# Bone flag bit -> name. DERIVED, not guessed: 1,242 bones over 20 vehicles gave 0 popcount
# mismatches and 0 conflicts against the oracle's <Flags> text (so the names really do render
# in ascending bit order), and bit 7 was pinned separately on prop_fnclink_02g/03e, whose
# 0xF7 bones read "... TransZ, LimitTranslation". Bits 11 and 13-15 have NEVER been observed
# set - if one appears, REFUSE rather than drop a flag the consumer may need.
BONE_FLAG_BITS = {
    0: "RotX", 1: "RotY", 2: "RotZ", 3: "LimitRotation",
    4: "TransX", 5: "TransY", 6: "TransZ", 7: "LimitTranslation",
    8: "ScaleX", 9: "ScaleY", 10: "ScaleZ", 12: "Unk0",
}

# A sidecar filename is derived from a GROUP NAME that came out of the file, i.e. untrusted
# input: anything outside this set could escape the folder or collide with a sibling.
_SAFE_NAME = re.compile(r"^[A-Za-z0-9_.\-]+$")


class FragmentError(ValueError):
    """Loud refusal - the fragment holds a value this emitter has no measurement for."""


def _f(buf, off, n):
    return struct.unpack_from("<%df" % n, buf, off)


def read_skeleton(res, dbase):
    """-> [bone dicts] in skeleton order, [] when the drawable carries no skeleton.
    No skeleton is ordinary (most map props). A NON-NULL skeleton pointer that does not
    resolve is not ordinary and refuses."""
    sp = res.u32(dbase + SKEL_SLOT)
    if sp == 0:
        return []
    sbuf, s = res.deref(sp, SKEL_BONES + 4)
    if sbuf is None:
        raise FragmentError("skeleton pointer 0x%08x does not resolve" % sp)
    n = res.u16(s + SKEL_COUNT)
    if n == 0:
        return []
    if n > 4096:                       # 354 (a ped) is the largest ever measured
        raise FragmentError("implausible bone count %d" % n)
    bbuf, bo = res.deref(res.u32(s + SKEL_BONES), n * BONE_STRIDE)
    if bbuf is None:
        raise FragmentError("bone array of %d bones does not resolve" % n)
    out = []
    for i in range(n):
        o = bo + i * BONE_STRIDE
        flags = struct.unpack_from("<H", bbuf, o + 0x40)[0]
        names = []
        for b in range(16):
            if (flags >> b) & 1:
                nm = BONE_FLAG_BITS.get(b)
                if nm is None:
                    raise FragmentError(
                        "bone %d: flag bit %d set (0x%04x) but UNNAMED - refusing rather "
                        "than dropping a flag" % (i, b, flags))
                names.append(nm)
        out.append({
            "name": res.cstr(struct.unpack_from("<I", bbuf, o + 0x38)[0]),
            "tag": struct.unpack_from("<H", bbuf, o + 0x44)[0],
            "index": struct.unpack_from("<H", bbuf, o + 0x46)[0],
            "sibling": struct.unpack_from("<h", bbuf, o + 0x30)[0],
            "parent": struct.unpack_from("<h", bbuf, o + 0x32)[0],
            "flags": names,
            "rot": _f(bbuf, o + 0x00, 4),
            "transl": _f(bbuf, o + 0x10, 3),
            "scale": _f(bbuf, o + 0x20, 3),
        })
    return out


def read_physics(res):
    """-> (group_names, [(group_index, child_drawable_base or None)]), or (None, None) when
    the fragment has no physics LOD group at all (a legitimate shape - some props)."""
    pp = res.u32(PHYS_SLOT)
    if pp == 0:
        return None, None
    pbuf, ph = res.deref(pp, LOD1_SLOT + 4)
    if pbuf is None:
        return None, None
    lbuf, l1 = res.deref(res.u32(ph + LOD1_SLOT), CHILD_COUNT + 2)
    if lbuf is None:
        return None, None
    ng, nc = res.sys[l1 + GROUP_COUNT], res.u16(l1 + CHILD_COUNT)
    groups = []
    gbuf, go = res.deref(res.u32(l1 + GROUP_ARR), ng * 8) if ng else (None, 0)
    for gi in range(ng):
        if gbuf is None:
            raise FragmentError("physics group array of %d entries does not resolve" % ng)
        ebuf, eo = res.deref(struct.unpack_from("<I", gbuf, go + gi * 8)[0], 1)
        if ebuf is None:
            raise FragmentError("physics group %d does not resolve" % gi)
        end = ebuf.find(b"\x00", eo)          # the name is an INLINE char[] at group+0x00
        groups.append(ebuf[eo:end].decode("latin-1") if 0 <= end - eo <= 63 else "")
    children = []
    cbuf, co = res.deref(res.u32(l1 + CHILD_ARR), nc * 8) if nc else (None, 0)
    for ci in range(nc):
        if cbuf is None:
            raise FragmentError("physics child array of %d entries does not resolve" % nc)
        xbuf, ch = res.deref(struct.unpack_from("<I", cbuf, co + ci * 8)[0],
                             CHILD_DRAWABLE + 4)
        if xbuf is None:
            raise FragmentError("physics child %d does not resolve" % ci)
        gi = struct.unpack_from("<H", res.sys, ch + CHILD_GROUP_INDEX)[0]
        dp = res.u32(ch + CHILD_DRAWABLE)
        dbase = None
        if dp:
            dbuf, db = res.deref(dp, 0xD0)
            # A child drawable that resolves but decodes to no geometry is the NORMAL case
            # (17 of the adder's 18 children are collision-only stubs), so an empty child is
            # a skip, never an error.
            if dbuf is not None and read_geometries(res, db):
                dbase = db
        children.append((gi, dbase))
    return groups, children


def _tag_of(bones, name):
    """Bone tag by name - the group<->bone join. -1 when the group names no bone, which is
    real: a physics group can describe a collision-only part with no bone of its own."""
    for b in bones:
        if b["name"] == name:
            return b["tag"]
    return -1


def skeleton_lines(bones, ind=" "):
    ff = fmt_float
    L = ["%s<Skeleton>" % ind, "%s <Bones>" % ind]
    for b in bones:
        L.append("%s  <Item>" % ind)
        L.append("%s   <Name>%s</Name>" % (ind, esc(b["name"])))
        L.append('%s   <Tag value="%d" />' % (ind, b["tag"]))
        L.append('%s   <Index value="%d" />' % (ind, b["index"]))
        L.append('%s   <ParentIndex value="%d" />' % (ind, b["parent"]))
        L.append('%s   <SiblingIndex value="%d" />' % (ind, b["sibling"]))
        L.append("%s   <Flags>%s</Flags>" % (ind, ", ".join(b["flags"]) or "NONE"))
        L.append('%s   <Translation x="%s" y="%s" z="%s" />'
                 % ((ind,) + tuple(ff(v) for v in b["transl"])))
        L.append('%s   <Rotation x="%s" y="%s" z="%s" w="%s" />'
                 % ((ind,) + tuple(ff(v) for v in b["rot"])))
        L.append('%s   <Scale x="%s" y="%s" z="%s" />'
                 % ((ind,) + tuple(ff(v) for v in b["scale"])))
        L.append("%s  </Item>" % ind)
    L.append("%s </Bones>" % ind)
    L.append("%s</Skeleton>" % ind)
    return L


def _shader_group_span(body):
    """The fragment's own <ShaderGroup> lines, sliced out of the drawable_lines body already
    produced - so a child sidecar can never drift from what the fragment itself emits."""
    try:
        a = body.index(" <ShaderGroup>")
        b = body.index(" </ShaderGroup>")
    except ValueError:
        raise FragmentError("main drawable emitted no <ShaderGroup> to share with its children")
    return body[a:b + 1]


def physics_lines(res, bones, groups, children, body_by_child, ind=" "):
    """<Physics><LOD1> carrying the Groups NAME table and the Children join. Deliberately
    partial: masses, inertia tensors, joints, glass and the rest of the per-group physics
    record are NOT read (v1 scope), and a consumer using FindChildNode gets nullptr for them
    rather than a fabricated value."""
    L = ["%s<Physics>" % ind, "%s <LOD1>" % ind, "%s  <Groups>" % ind]
    for g in groups:
        L.append("%s   <Item>" % ind)
        L.append("%s    <Name>%s</Name>" % (ind, esc(g)))
        L.append("%s   </Item>" % ind)
    L.append("%s  </Groups>" % ind)
    L.append("%s  <Children>" % ind)
    for ci, (gi, _dbase) in enumerate(children):
        gname = groups[gi] if 0 <= gi < len(groups) else ""
        L.append("%s   <Item>" % ind)
        L.append('%s    <GroupIndex value="%d" />' % (ind, gi))
        L.append('%s    <BoneTag value="%d" />' % (ind, _tag_of(bones, gname)))
        cbody = body_by_child.get(ci)
        if cbody is not None:
            L.append("%s    <Drawable>" % ind)
            L.extend("%s    %s" % (ind, ln) for ln in cbody)
            L.append("%s    </Drawable>" % ind)
        L.append("%s   </Item>" % ind)
    L.append("%s  </Children>" % ind)
    L.append("%s </LOD1>" % ind)
    L.append("%s</Physics>" % ind)
    return L


def convert(res, stem, extras=None):
    """-> (xml text, [(sidecar relpath, bytes)]). THE entry point; to_xml() is the text-only
    wrapper the existing callers already use."""
    if extras is None:
        extras = EMIT_EXTRAS
    res.require_version(YFT_VERSION, "Legacy fragment")
    frag_name = res.cstr(res.u32(NAME_SLOT)) or ("pack:/" + stem)
    dp = res.u32(DRAWABLE_SLOT)
    buf, base = res.deref(dp, 0xD0)
    if buf is None:
        raise ValueError("main drawable pointer (+0x30) does not resolve")
    inner = res.cstr(res.ptr(base + 0xA8)) or "skel"
    body = drawable_lines(res, inner, base=base)

    extra_lines, sidecars = [], []
    if extras:
        bones = read_skeleton(res, base)
        if bones:
            # reference element ORDER: ShaderGroup, then Skeleton, then the model groups
            cut = body.index(" </ShaderGroup>") + 1
            body = body[:cut] + skeleton_lines(bones) + body[cut:]
        groups, children = read_physics(res)
        if children:
            shared_sg = _shader_group_span(body)
            body_by_child, used = {}, set()
            for ci, (gi, dbase) in enumerate(children):
                if dbase is None:
                    continue
                gname = groups[gi] if 0 <= gi < len(groups) else ""
                if not _SAFE_NAME.match(gname):
                    raise FragmentError(
                        "child %d carries geometry but its group name %r is not a safe "
                        "sidecar filename" % (ci, gname))
                if gname in used:
                    raise FragmentError(
                        "two geometry children share the group name %r - one sidecar would "
                        "overwrite the other" % gname)
                used.add(gname)
                cbody = drawable_lines(res, gname, base=dbase)
                body_by_child[ci] = cbody
                # the sidecar is that SAME body with the fragment's shader group spliced in:
                # a standalone <Drawable> document ImportYdr consumes unchanged
                a = cbody.index(" <ShaderGroup>")
                b = cbody.index(" </ShaderGroup>")
                doc = (['<?xml version="1.0" encoding="UTF-8"?>', "<Drawable>"]
                       + cbody[:a] + shared_sg + cbody[b + 1:] + ["</Drawable>"])
                sidecars.append(("%s/%s.ydr.xml" % (stem, gname),
                                 ("\n".join(doc) + "\n").encode("utf-8")))
            if groups or body_by_child:
                extra_lines = physics_lines(res, bones, groups, children, body_by_child)

    L = ['<?xml version="1.0" encoding="UTF-8"?>', "<Fragment>"]
    L.append(" <Name>%s</Name>" % esc(frag_name))
    L.append(" <Drawable>")
    L.extend(" " + ln for ln in body)
    L.append(" </Drawable>")
    L.extend(extra_lines)
    L.append("</Fragment>")
    return "\n".join(L) + "\n", sidecars


def to_xml(res, stem, extras=None):
    """Text only - the shape every existing caller (quarry.to_interchange_xml) already uses.
    With extras off this returns byte-for-byte what it returned before extras existed."""
    return convert(res, stem, extras)[0]


def main():
    ap = argparse.ArgumentParser(prog="yft2xml")
    ap.add_argument("files", nargs="*")
    ap.add_argument("--out")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--extras", action="store_true",
                    help="also emit the skeleton, the physics group/child join and one "
                         "standalone <stem>/<group>.ydr.xml sidecar per geometry-bearing "
                         "child (the vehicle wheel lane)")
    a = ap.parse_args()
    if not a.files:
        ap.error("give at least one .yft")
    ok = fail = 0
    for p in a.files:
        stem = os.path.splitext(os.path.basename(p))[0]
        try:
            xml, sidecars = convert(Res(p), stem, extras=a.extras)
        except Exception as e:
            print(f"FAIL {os.path.basename(p)}: {type(e).__name__}: {e}")
            fail += 1
            continue
        if a.selftest:
            import xml.etree.ElementTree as ET
            root = ET.fromstring(xml)
            ng = len(root.findall("./Drawable/DrawableModelsHigh/Item/Geometries/Item"))
            nb = len(root.findall("./Drawable/Skeleton/Bones/Item"))
            nc = len(root.findall("./Physics/LOD1/Children/Item/Drawable"))
            print(f"OK   {os.path.basename(p):<40} {ng:3} geos  {nb:4} bones  "
                  f"{nc:2} child drawables  {len(xml):>10,} B")
        else:
            if not a.out:
                ap.error("--out is required unless --selftest")
            os.makedirs(a.out, exist_ok=True)
            open(os.path.join(a.out, stem + ".yft.xml"), "w", encoding="utf-8",
                 newline="\n").write(xml)
            for rel, blob in sidecars:
                dst = os.path.join(a.out, rel.replace("/", os.sep))
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                open(dst, "wb").write(blob)
            print(f"OK   {os.path.basename(p)}"
                  + (f"  (+{len(sidecars)} sidecar)" if sidecars else ""))
        ok += 1
    print(f"\n{ok} converted, {fail} failed")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
