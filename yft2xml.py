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
    skeleton bone, and that bone's Tag is the child's BoneTag. ⚠ The "376/376 children, 16
    vehicles" figure this line used to carry described a SAMPLE in which group name == bone name;
    format-wide the join needs case folding and two suffix transforms - see _tag_of, which
    measures 99.90% over 4,934 name-matched children where exact-case scored 91.9%.
    A child drawable has NO ShaderGroup of its own: its <ShaderIndex> values index the
    FRAGMENT's shader group (measured - 0 shaders read at every child base, and the reference
    corpus child <Drawable>s carry no <ShaderGroup> either). The sidecar therefore splices the
    FRAGMENT's ShaderGroup in, or every wheel would import on the default material.

KNOWN V1 GAPS (documented, not silent):
    * ✅ CLOSED 2026-07-31 - embedded ShaderGroup TextureDictionary pixels ARE exported. This line
      used to say they were not, which was true when it was written and had outlived the fix:
      quarry's yft branch rebases the ydr embedded-texture pass onto the fragment's main drawable
      and writes <stem>__embedded.ytd.xml beside the XML. Re-verified by RUNNING the pipeline
      entry point on 120 random fragments (2026-08-03): 34 emit <TextureDictionary> in the XML and
      the same 34 emit the sidecar - no file gets one without the other. Over a wider 400-fragment
      draw, 119 carry a dictionary at ShaderGroup+0x08 and 118 decode; ⚠ ONE REFUSES
      (futo2_hoodk.yft, ytd2xml "texture 0 pointer is out of bounds"), which is a real live loss
      in the ytd reader that only became visible when the swallowed exception there was given a
      counter - not a fragment-lane gap.
    * ⛔ fragment collision is NOT emitted at all, and it is worth stating positively because the
      code makes it look conditional: bounds_lines drops out on the drawable+0xCC guard for 800 of
      800 sampled fragments, so no .yft.xml has ever carried a <Bounds>.
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
# _refuse is shared deliberately: ONE counter table for the whole interchange-XML lane, so
# quarry's single ydr2xml.report_refusals(stats) call reports fragment declines too. A second
# private table here would be a second thing to remember to surface.
from ydr2xml import Res, drawable_lines, esc, fmt_float, read_geometries, _refuse

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
    """-> [bone dicts] in skeleton order, [] when the drawable carries no skeleton. A NON-NULL
    skeleton pointer that does not resolve is not ordinary and refuses.

    ⚠ THIS DOCSTRING USED TO SAY "No skeleton is ordinary (most map props)" - CONTRADICTED BY
    MEASUREMENT (2026-08-03). Over 800 random base-game fragments every single one carries a
    non-NULL skeleton pointer with a non-zero bone count (drawlane/silentsites.py; the 1c audit
    got the same answer over 3,900). The empty return is therefore a path nobody has ever taken,
    which matters because that sentence was the reason to believe it was exercised. It is kept
    (a null pointer is a legal encoding) but both empty exits are now COUNTED, so "it never
    happens" stays a measurement rather than becoming folklore."""
    sp = res.u32(dbase + SKEL_SLOT)
    if sp == 0:
        _refuse("skeleton_pointer_NULL", res.name or "fragment")
        return []
    sbuf, s = res.deref(sp, SKEL_BONES + 4)
    if sbuf is None:
        raise FragmentError("skeleton pointer 0x%08x does not resolve" % sp)
    n = res.u16(s + SKEL_COUNT)
    if n == 0:
        _refuse("skeleton_present_but_bone_count_zero", res.name or "fragment")
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
    """-> (group_names, [(group_index, child_drawable_base or None)]), or (None, None) when the
    fragment carries no physics LOD group.

    ⛔ FOUR SITUATIONS USED TO SHARE ONE SILENT (None, None) (split 2026-08-03). The docstring
    described only the first - "a legitimate shape, some props" - so a fragment whose physics
    pointer was SET but unreachable produced no groups, no children and no wheels while reporting
    complete success, and read the same as a prop that genuinely has none. read_skeleton has always
    REFUSED on exactly that shape (a non-NULL pointer that does not resolve); this did the
    opposite, which is the asymmetry being closed. Censused over 2,500 random base-game fragments
    (scratchpad drawlane/physcensus.py, seed 'phys-2026-08-03'):
        physics pointer NULL ................ 86    legitimate, stays silent
        physics pointer set, unresolvable ...  0    was silent -> now refuses
        LOD1 pointer NULL ...................  0    was silent -> now counted, not refused
        LOD1 pointer set, unresolvable ......  0    was silent -> now refuses
        resolves ............................ 2,414
    So today this changes no output at all; what it buys is that the first fragment that DOES take
    one of the middle three paths says which one. The two refusals raise FragmentError on purpose -
    that is the exception quarry's yft branch already downgrades and COUNTS (yft_extras_refused),
    so the fragment keeps its visual drawable and the loss lands in a counter instead of vanishing.
    ⚠ A NULL LOD1 pointer is COUNTED rather than refused: a null is an "absent" encoding, and with
    0 observations there is no measurement saying it is a failure. If that counter ever moves, what
    it means is still open."""
    pp = res.u32(PHYS_SLOT)
    if pp == 0:
        return None, None
    pbuf, ph = res.deref(pp, LOD1_SLOT + 4)
    if pbuf is None:
        raise FragmentError("physics LOD group pointer 0x%08x does not resolve" % pp)
    lp = res.u32(ph + LOD1_SLOT)
    if lp == 0:
        _refuse("physics_LOD1_pointer_NULL", res.name or "fragment")
        return None, None
    lbuf, l1 = res.deref(lp, CHILD_COUNT + 2)
    if lbuf is None:
        raise FragmentError("physics LOD1 pointer 0x%08x does not resolve" % lp)
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
        if 0 <= end - eo <= 63:
            groups.append(ebuf[eo:end].decode("latin-1"))
        else:
            # A blanked group name is not cosmetic: it is the JOIN KEY. _tag_of resolves BoneTag
            # through it and convert() derives the child sidecar's filename from it, so a silent ""
            # would emit BoneTag -1 and refuse the sidecar for a reason that names no cause.
            # 0 of 2,372 group names over 800 random fragments needed this (drawlane/
            # silentsites.py) - the guard is right, the silence was not.
            _refuse("physics_group_name_unterminated_or_over_63B", "group %d" % gi)
            groups.append("")
    if ng and not nc:
        # <Groups> is populated but there are no children to hang it on, and convert()'s
        # `if children:` then drops the whole <Physics> element. 0 of 2,414 fragments with a
        # resolvable LOD1 (drawlane/physcensus.py) - counted so that stays a measurement.
        _refuse("physics_groups_present_but_zero_children", "%d groups" % ng)
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
        if not (0 <= gi < len(groups)):
            # Both consumers of this index (physics_lines' <BoneTag> lookup and convert()'s
            # sidecar filename) silently substitute "" for an out-of-range GroupIndex, which
            # downstream reads as "this child names no group" rather than "we could not read the
            # index". Counted once here so it cannot be double-counted by the two call sites.
            # 0 of 3,002 children over 800 random fragments (drawlane/silentsites.py).
            _refuse("child_GroupIndex_out_of_range", "child %d -> group %d of %d"
                    % (ci, gi, len(groups)))
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
    """Bone tag by name - the group<->bone join.

    ⛔ EXACT, CASE-SENSITIVE MATCHING IS NOT THE RULE (measured 2026-08-03, 700 fragments /
    4,934 children name-matched against the reference oracle). The old one-liner compared
    b["name"] == name and returned -1 otherwise, with a comment calling -1 "real: a physics group
    can describe a collision-only part with no bone of its own". THE ORACLE EMITS -1 ON 0 OF
    4,934 CHILDREN - so -1 was never the data's answer, it was always ours, and the comment was
    what made 400 wrong answers read as legitimate. Exact-case scored 4,534/4,934 = 91.9%.
    The docstring's "376/376 children, 16 vehicles" is a SAMPLE-DESCRIPTIVE number, not a format
    law: those 16 vehicles happened to be the case where group name == bone name.
    Every mismatch is one of three authoring transforms, censused over the same 4,934:
        case drift only ...................... 199   (cs2_02_tunnel_cloth_10 vs CS2_02_Tunnel_Cloth_10)
        bone carries an `_ng` suffix ......... 138   (group tenf_skirt_bc2 -> bone tenf_skirt_bc2_ng)
        group is <bone>physicsbody ........... 58    (skel_pelvisphysicsbody -> SKEL_Pelvis)
    Case-insensitive first, then the two suffix transforms: 4,929/4,934 = 99.90%, -1 emitted 5.
    Re-validated on a FRESH sample (seed 777777, 800 fragments / 5,795 children): 5,794/5,795 =
    99.983%, -1 emitted 1.
    ⚠ ONE UNEXPLAINED RESIDUAL CLASS REMAINS, and it is small: a full extras run over 1,500
    fragments / 8,594 children emitted -1 exactly 4 times (0.047%), on groups "root",
    "slod_human" and "slod_small_quadped" - a group whose name matches no bone under any of the
    three transforms. In every instance checked the oracle answers 0, which is bones[0]["tag"]
    (SKEL_ROOT on slod_human/slod_small_quadped; the lone bone on cs1_11_banner_ng_01), i.e.
    "a group that names no bone hangs off the root". That hypothesis fits 3/3 files and is
    STILL NOT IMPLEMENTED: three files is how a wrong rule gets written into a format, and
    bones[0] vs "tag 0" cannot be told apart while every observed root tag is 0. The -1 is
    COUNTED instead (bone_tag_unresolved) - if that counter climbs the rule is incomplete
    rather than the data being odd, and the root hypothesis is the first thing to test."""
    ln = name.lower()
    for b in bones:
        if b["name"].lower() == ln:
            return b["tag"]
    key = ln[:-11] if ln.endswith("physicsbody") else ln
    for b in bones:
        bn = b["name"].lower()
        if bn.endswith("_ng"):
            bn = bn[:-3]
        if bn == key:
            return b["tag"]
    _refuse("bone_tag_unresolved", "group %r matches no bone" % name)
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


def main_drawable_base(res):
    """System-segment offset of the fragment's MAIN visual drawable (+0x30), or None when the
    pointer does not resolve. Exposed so callers (quarry's embedded-texture pass) can reuse the
    measured offset instead of restating it."""
    buf, base = res.deref(res.u32(DRAWABLE_SLOT), 0xD0)
    return None if buf is None else base


def convert(res, stem, extras=None):
    """-> (xml text, [(sidecar relpath, bytes)]). THE entry point; to_xml() is the text-only
    wrapper the existing callers already use."""
    if extras is None:
        extras = EMIT_EXTRAS
    res.require_version(YFT_VERSION, "Legacy fragment")
    frag_name = res.cstr(res.u32(NAME_SLOT))
    if not frag_name:
        # A fabricated <Name> is indistinguishable from a read one once it is in the XML, so the
        # substitution is counted. 800 of 800 random fragments carry a real "pack:/<stem>" here
        # (drawlane/silentsites.py), i.e. this has never yet been the source of a name.
        _refuse("fragment_name_absent_stem_substituted", stem)
        frag_name = "pack:/" + stem
    dp = res.u32(DRAWABLE_SLOT)
    buf, base = res.deref(dp, 0xD0)
    if buf is None:
        raise ValueError("main drawable pointer (+0x30) does not resolve")
    # ⚠ NOT A RARE FALLBACK - IT IS THE ONLY PATH (measured 2026-08-03). The `or "skel"` reads like
    # a guard for an odd file; in fact the fragment drawable's name pointer at +0xA8 is NULL in
    # 800 of 800 random base-game fragments, so every fragment we have ever emitted took it. The
    # literal is right rather than merely harmless: the reference export prints
    # <Drawable><Name>skel</Name> in 400 of 400 sampled yft. Left uncounted deliberately - a
    # counter that fires on 100% of files is noise, and this one would hide the counters that mean
    # something. Scripts: drawlane/silentsites.py, and the oracle check in the same folder.
    inner = res.cstr(res.ptr(base + 0xA8)) or "skel"
    try:
        body = drawable_lines(res, inner, base=base)
    except ValueError as ex:
        # ⛔ AN EMPTY MAIN DRAWABLE IS A LEGAL SHAPE, NOT A DECODE FAILURE (measured 2026-08-03).
        # A handful of base-game fragments carry ZERO geometry in the visual drawable and all of
        # it in a PHYSICS CHILD. drawable_lines raised "no geometry decoded", convert() died here
        # before extras ever ran, and the fragment lost EVERYTHING - no .yft.xml, no skeleton, no
        # child sidecar - while quarry filed it in the generic xml_failed bucket beside genuinely
        # corrupt files, so "the yft lane converts 100% of what it sees" still read as true. The
        # oracle export agrees the mesh is there (enduro_ex_2: DrawableModelsHigh 0 geometries,
        # 2 children, child geometry counts [1, 0]). Tolerated ONLY with extras on, because only
        # the extras lane can still deliver that mesh; a shortfall inside a NON-empty drawable
        # (the "%d of %d geometries did not resolve" refusal) is a different message and still
        # propagates.
        if not extras or "no geometry decoded" not in str(ex):
            raise
        _refuse("main_drawable_empty_geometry_in_child", "%s: %s" % (stem, ex))
        body = drawable_lines(res, inner, base=base, allow_empty=True)

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
    import ydr2xml
    ydr2xml.report_refusals()      # shared table: bone-tag and empty-drawable declines land here
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
