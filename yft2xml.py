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
from ydr2xml import (Res, drawable_lines, esc, fmt_float, read_geometries, _refuse,
                     _bound_lines, _model_group_lines, DRAWABLE_MODEL_GROUPS)
# The 2026-08-06 byte-identical build reuses the float-text law + the yld cloth helpers.
from meta2xml import fmt_num as _F, num_list, scalar_list
from yld2xml import _vec4_block

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


# =====================================================================================
# BYTE-IDENTICAL FRAGMENT BUILD (2026-08-06) - oracle-derived, token+byte validated against
# the 10 _Oracles/yft pairs (10/10). Non-cloth map: WAL §6m + scratchpad validate_physics.py /
# validate_fraghdr.py (fragment header 10/10, BoneTransforms/Physics/GlassWindows OK on all 7
# non-cloth). Cloth map: derived 2026-08-06 (array @frag+0x60, controller offsets == yld's, with
# a MorphController the yld lacks and a BBMin @verlet+0x30); the VerletCloth1/BridgeSimGfx/
# Constraints decoders are lifted from yld2xml.
# ⛔ The pre-oracle "extras" path (read_skeleton/read_physics/_tag_of/skeleton_lines/physics_lines,
# above) is SUPERSEDED - it emitted geometry-bearing child <Drawable> sidecars and DERIVED BoneTag
# via a name join, both of which the reference exporter oracle disproves (child drawables are header-only
# stubs; BoneTag is STORED @child+0x12). Kept above, unwired, for the measurements they carry.
# =====================================================================================

def _yU(r, o): return struct.unpack_from("<I", r.sys, o)[0]
def _yM(v): return v & 0x0FFFFFFF
def _yf(r, o): return struct.unpack_from("<f", r.sys, o)[0]
def _yv3(r, o): return struct.unpack_from("<3f", r.sys, o)
def _yv4(r, o): return struct.unpack_from("<4f", r.sys, o)

_PHYS_LOD_SLOT, _LOD1_SLOT, _CLOTH_ARR = 0xF0, 0x10, 0x60


def _lod1_base(r):
    """Physics LOD1 = deref(deref(fragroot+0xF0)+0x10), or None when fragroot+0xF0 is NULL - the
    MEASURED "this fragment has no physics" shape. Named UNPINNED offsets carry WAL §6m tags.

    ⛔⛔ THIS USED TO RETURN A SILENT 0, and it cost the yft lane 1,290 files (95% of all its
    failures). `Res.deref` answers (None, 0) for a pointer it cannot resolve, and both lines here
    threw the buffer away - so a fragment with NO physics group returned system offset 0 and
    `_emit_physics` walked the FRAGMENT ROOT as if it were a phys-LOD struct. It never read as a
    decode failure because exactly one dword in that region is non-zero: fragroot+0x4C is
    0xFFFFFFFF in 870/870 fragments measured (including ones that DO have physics and convert
    fine). Its second byte tripped `_bound_header_lines`' zero-lane guard, which then reported
    `BoundsError: archetype: header byte +0x4d = 0xff` - a message naming a bound that does not
    exist. One identical value across 1,290 files is the signature of a constant, not a field.
    ⭐ The guard itself was right and stays: +0x4D is genuinely never non-zero in a REAL bound
    (8,444 bounds across 916 yft + 1,200 ybn, all zero-lanes clean). The caller was wrong.
    ⚠ Deliberate asymmetry: only a LITERAL NULL counts as absence - that is the only shape
    measured (1,072/1,072 refused files read exactly 0x00000000). Any OTHER unresolvable pointer
    now raises, so a real decode failure stays loud instead of silently walking offset 0."""
    p = _yU(r, _PHYS_LOD_SLOT)
    if p == 0:                                  # MEASURED absence, not a decode failure
        return None
    buf, ph = r.deref(p, _LOD1_SLOT + 4)
    if buf is None:
        raise ValueError("physics LOD group pointer 0x%08x does not resolve" % p)
    q = _yU(r, ph + _LOD1_SLOT)
    buf, l1 = r.deref(q, 0x200)
    if buf is None:
        raise ValueError("physics LOD1 pointer 0x%08x does not resolve" % q)
    return l1


def _frag_header(r):
    """Fragment-root scalars @ system offset 0 (validate_fraghdr, 10/10 text-exact)."""
    cx, cy, cz = _yv3(r, 0x20)
    L = [' <BoundingSphereCenter x="%s" y="%s" z="%s" />' % (_F(cx), _F(cy), _F(cz)),
         ' <BoundingSphereRadius value="%s" />' % _F(_yf(r, 0x2C))]
    for tag, o in (("UnknownB0", 0xB0), ("UnknownB8", 0xB8), ("UnknownBC", 0xBC),
                   ("UnknownC0", 0xC0), ("UnknownC4", 0xC4), ("UnknownCC", 0xCC)):
        L.append(' <%s value="%s" />' % (tag, _F(_yU(r, o))))
    L.append(' <GravityFactor value="%s" />' % _F(_yf(r, 0xD0)))
    L.append(' <BuoyancyFactor value="%s" />' % _F(_yf(r, 0xD4)))
    return L


def _bone_count(r, base):
    """Bone count from the drawable's crSkeletonData (drawable+0x18 -> +0x5E u16), 0 when none."""
    sk = _yU(r, base + 0x18)
    if (sk >> 28) != 5:
        return 0
    _, so = r.deref(sk, 0x60)
    return 0 if so is None else struct.unpack_from("<H", r.sys, so + 0x5E)[0]


def _bone_transforms(r, nb):
    """<BoneTransforms unk="0"> @ fragroot+0xA8: count == bone count, +0x20 stride 0x30, 3x4 rows."""
    if not nb:
        return []
    p = _yU(r, 0xA8)
    if (p >> 28) != 5:
        return []
    _, bt = r.deref(p, 0x20 + nb * 0x30)
    # `unk` was hardcoded "0" - true for most fragments, which is exactly why it survived the
    # 10-file oracle set. It is a u16 in the array header at +0x12 (derived 2026-08-07 against
    # the wave-2 oracles). Reading it costs nothing and a wrong constant is invisible to every
    # gate that never saw a non-zero one.
    L = [' <BoneTransforms unk="%d">' % struct.unpack_from("<H", r.sys, bt + 0x12)[0]]
    for i in range(nb):
        b = bt + 0x20 + i * 0x30
        L.append("  <Item>")
        for row in range(3):
            m = _yv4(r, b + row * 0x10)
            L.append("   %s %s %s %s" % (_F(m[0]), _F(m[1]), _F(m[2]), _F(m[3])))
        L.append("  </Item>")
    L.append(" </BoneTransforms>")
    return L


# fragGroup: name is an INLINE char[] @ group+0x80, so group base = namePtr - 0x80. Scalars below
# are float @ base+off (25 of them), plus 3 u8 (ParentIndex/GlassWindowIndex/GlassFlags).
_GROUP_F = [("Strength", 0x10), ("ForceTransmissionScaleUp", 0x14), ("ForceTransmissionScaleDown", 0x18),
            ("JointStiffness", 0x1C), ("MinSoftAngle1", 0x20), ("MaxSoftAngle1", 0x24), ("MaxSoftAngle2", 0x28),
            ("MaxSoftAngle3", 0x2C), ("RotationSpeed", 0x30), ("RotationStrength", 0x34), ("RestoringStrength", 0x38),
            ("RestoringMaxTorque", 0x3C), ("LatchStrength", 0x40), ("Mass", 0x44), ("MinDamageForce", 0x54),
            ("DamageHealth", 0x58), ("UnkFloat5C", 0x5C), ("UnkFloat60", 0x60), ("UnkFloat64", 0x64), ("UnkFloat68", 0x68),
            ("UnkFloat6C", 0x6C), ("UnkFloat70", 0x70), ("UnkFloat74", 0x74), ("UnkFloat78", 0x78), ("UnkFloatA8", 0xA8)]


def _emit_groups(r, l1):
    garr = _yM(_yU(r, l1 + 0xC0)); ng = r.sys[l1 + 0x11A]
    L = ["   <Groups>"]
    for gi in range(ng):
        nptr = _yM(_yU(r, garr + gi * 8)); base = nptr - 0x80
        end = r.sys.find(b"\x00", nptr); nm = r.sys[nptr:end].decode("latin-1")
        L.append("    <Item>")
        L.append("     <Name>%s</Name>" % esc(nm))
        L.append('     <ParentIndex value="%d" />' % r.sys[base + 0x4D])
        # ⛔ +0x4E IS THE GROUP'S FIRST-CHILD INDEX, NOT THE GLASS-WINDOW INDEX (fixed 2026-08-07).
        # It survived because in the only 10-file-set oracles with a non-zero GlassWindowIndex
        # (des_fib_frame 0-3, prop_dealer_win_01 0-1) group index == child index == window index,
        # so three different offsets all read the same number. Vehicles separate them: boattrailer
        # emitted 27..31 for groups 1..5 where the oracle says 0, and children 27..31 are exactly
        # the ones whose GroupIndex is 1..5. Brute-forcing every u8 in group+0x00..0xBF against
        # the oracle over 7 files / 69 groups leaves EXACTLY ONE surviving offset: +0x52.
        # Validated over 14 files / 104 groups: +0x52 = 104 ok / 0 bad, +0x4E = 18 ok / 86 bad.
        # (The same probe re-confirms ParentIndex @+0x4D and GlassFlags @+0x53 - both correct.)
        L.append('     <GlassWindowIndex value="%d" />' % r.sys[base + 0x52])
        L.append('     <GlassFlags value="%d" />' % r.sys[base + 0x53])
        for nm2, off in _GROUP_F:
            L.append('     <%s value="%s" />' % (nm2, _F(_yf(r, base + off))))
        L.append("    </Item>")
    L.append("   </Groups>")
    return L


def _emit_children(r, l1):
    carr = _yM(_yU(r, l1 + 0xD0)); nc = struct.unpack_from("<H", r.sys, l1 + 0x11E)[0]
    _, ufa = r.deref(_yU(r, l1 + 0x28), nc * 4)
    _, iva = r.deref(_yU(r, l1 + 0xF0), nc * 16)
    _, uva = r.deref(_yU(r, l1 + 0xF8), nc * 16)
    L = ["   <Children>"]
    for ci in range(nc):
        base = _yM(_yU(r, carr + ci * 8))
        gi = struct.unpack_from("<H", r.sys, base + 0x10)[0]
        bt = struct.unpack_from("<H", r.sys, base + 0x12)[0]    # BoneTag STORED (supersedes _tag_of)
        L.append("    <Item>")
        L.append('     <GroupIndex value="%d" />' % gi)
        L.append('     <BoneTag value="%d" />' % bt)
        L.append('     <PristineMass value="%s" />' % _F(_yf(r, base + 0x08)))
        L.append('     <DamagedMass value="%s" />' % _F(_yf(r, base + 0x0C)))
        L.append('     <UnkFloat value="%s" />' % _F(_yf(r, ufa + ci * 4)))
        L.append('     <UnkVec x="%s" y="%s" z="%s" w="%s" />' % tuple(_F(x) for x in _yv4(r, uva + ci * 16)))
        L.append('     <InertiaTensor x="%s" y="%s" z="%s" w="%s" />' % tuple(_F(x) for x in _yv4(r, iva + ci * 16)))
        if _yU(r, base + 0xB0) != 0:                            # EventSet gated by child+0xB0 ptr
            L.append("     <EventSet />")
        # 0x140, not 0x100: the model-group pointers live at +0x50..+0x68, but the window has to
        # reach the fields the geometry reader touches beyond +0x100.
        _, dbo = r.deref(_yU(r, base + 0xA0), 0x140)            # child drawable
        L.append("     <Drawable>")
        nm = r.cstr(_yU(r, dbo + 0xA8)) if dbo is not None else ""
        L.append("      <Name>%s</Name>" % esc(nm) if nm else "      <Name />")
        L.append("      <Matrix>")
        for row in range(4):
            m = _yv3(r, dbo + 0xB0 + row * 0x10) if dbo is not None else (0, 0, 0)
            L.append("       %s %s %s" % (_F(m[0]), _F(m[1]), _F(m[2])))
        L.append("      </Matrix>")
        # <Matrices> - DERIVED 2026-08-07 (WAL §13b), on the CHILD drawable, not the main one.
        # ptr @ dbo+0x108 GATES emission (only children that carry a block have it non-null);
        # COUNT = u16 @ dbo+0x110; per-matrix memory stride 0x40 with 4 rows at row*0x10, 3 floats
        # emitted per row - same shape as the child <Matrix> at dbo+0xB0.
        # ⛔ `id` and `capacity` are LITERALS the reference writes. capacity is NOT dbo+0x112,
        #   which reads 1 in all six oracles; id is 0 in all 53 items. Both are UNSEPARATED from a
        #   constant - if a future oracle shows either varying, this is where to look.
        # ⛔ STRIDE WAS THE TRAP: 0x30 reproduces 21 of 53 matrices - a clean pass on every
        #   identity-heavy file and wrong everywhere the data is real. Only 0x40 gives 53/53.
        #   Validated whole-rule 6/6 INCLUDING block order: boattrailer [26] cablecar [2]
        #   raketrailer [10,1,1] seashark [5] seashark2 [1] trflat [3,1,1,1,1].
        if dbo is not None and _yU(r, dbo + 0x108):
            nmat = struct.unpack_from("<H", r.sys, dbo + 0x110)[0]
            _, mp = r.deref(_yU(r, dbo + 0x108), nmat * 0x40)
            if mp is not None:
                L.append('      <Matrices capacity="64">')
                for mi in range(nmat):
                    L.append('       <Item id="0">')
                    for row in range(4):
                        m = _yv3(r, mp + mi * 0x40 + row * 0x10)
                        L.append("        %s %s %s" % (_F(m[0]), _F(m[1]), _F(m[2])))
                    L.append("       </Item>")
                L.append("      </Matrices>")
        if dbo is not None:
            sc = _yv3(r, dbo + 0x20); sr = _yf(r, dbo + 0x2C)
            bmin = _yv3(r, dbo + 0x30); bmax = _yv3(r, dbo + 0x40)
            ld = struct.unpack_from("<4f", r.sys, dbo + 0x70)
            fl = [r.sys[dbo + 0x80], r.sys[dbo + 0x84], r.sys[dbo + 0x88], r.sys[dbo + 0x8C]]
        else:
            sc = (0, 0, 0); sr = 0
            bmin = bmax = (0, 0, 0); ld = (0, 0, 0, 0); fl = [0, 0, 0, 0]
        L.append('      <BoundingSphereCenter x="%s" y="%s" z="%s" />' % tuple(_F(x) for x in sc))
        L.append('      <BoundingSphereRadius value="%s" />' % _F(sr))
        L.append('      <BoundingBoxMin x="%s" y="%s" z="%s" />' % tuple(_F(x) for x in bmin))
        L.append('      <BoundingBoxMax x="%s" y="%s" z="%s" />' % tuple(_F(x) for x in bmax))
        for t, vv in zip(("LodDistHigh", "LodDistMed", "LodDistLow", "LodDistVlow"), ld):
            L.append('      <%s value="%s" />' % (t, _F(vv)))
        for t, vv in zip(("FlagsHigh", "FlagsMed", "FlagsLow", "FlagsVlow"), fl):
            L.append('      <%s value="%d" />' % (t, vv))
        # ⛔ A CHILD DRAWABLE IS NOT ALWAYS A HEADER-ONLY STUB - that claim came from the 10-file
        # oracle set and the 31-file stratified draw killed it. Exactly ONE child per vehicle (the
        # wheel) carries its own LOD model groups at +0x50/58/60/68: measured non-zero on 1 child
        # of 32 (boattrailer), 1 of 19 (luiva), 1 of 23 (driftsentinel2), zero on every other.
        # That omission was >96% of the 380-727 KB vehicle gap. No new decoding was needed - the
        # existing ydr2xml model-group emitter reproduces the oracle block LINE-FOR-LINE
        # (2,238 / 4,374 / 3,290 lines exact), validated 14/14 over the local oracle pairs.
        if dbo is not None:
            for goff, tag in DRAWABLE_MODEL_GROUPS:
                if _yU(r, dbo + goff) == 0:
                    continue
                g = read_geometries(r, dbo, group_off=goff)
                if not g:
                    continue
                L += ["     " + ln for ln in _model_group_lines(fmt_float, tag, g)]
        L.append("     </Drawable>")
        L.append("    </Item>")
    L.append("   </Children>")
    return L


_ARTICULATED_JOINT_TYPES = {
    # joint vtable u32 -> <Item type=...>, witnessed UNANIMOUSLY across the animal oracles
    # (95 DOF3 + 11 DOF1 joints over 8 witnesses, animal_vtables.py 2026-08-08; both item
    # shapes print the same field set). An unwitnessed vtable still REFUSES loudly.
    0x4062BC40: "DOF3",
    0x4062BCB0: "DOF1",
}


def _emit_articulated(r, l1):
    """<ArticulatedBody> @ LOD1+0x20 (NULL = absent - the a_c_fish class: animal ragdoll
    physics). Derivation 2026-08-08 (probes artbody_*.py), single witness a_c_fish,
    validated by whole-file byte-compare:
    body struct BS = deref(l1+0x20): ItemIndices INLINE u32[nLinks] @ BS+0x10 · joints
    pointer-table ptr @ BS+0x78 (u64 slots, EMIT ORDER - the item array itself is stored in a
    DIFFERENT order and one item can sit outside the stride walk entirely) · UnknownVectors
    ptr @ BS+0x80 (16B each) · bodies u8 @ BS+0x88 (= vector count) · joints u8 @ BS+0x89 ·
    ItemFlags u8[nLinks] @ BS+0x8A. nLinks = ItemIndices/ItemFlags length = 22 in the witness;
    read from the LINK count u8 @ BS+0x8A? NO - measured: the two arrays are bounded by the
    struct layout, and the witness count equals the fragment's physics-children count, which
    the caller supplies implicitly through the byte-compare gate.
    Joint item: vtable u32 @+0x00 (type, table above) · Unknown10 f32 @+0x10 · FragIndex1 u8
    @+0x16 · FragIndex2 u8 @+0x17 · Unknown20..UnknownA0 vec4 @+0x20..0xA0 (w prints as
    stored; 0x50/0x90 carry NaN w in the witness)."""
    p = _yU(r, l1 + 0x20)
    if (p >> 28) != 5:
        return []
    _, bs = r.deref(p, 0x90)
    n_bodies = r.sys[bs + 0x88]
    n_joints = r.sys[bs + 0x89]
    # nLinks = 22, a FIXED capacity of the articulated-body struct: the inline index region
    # spans BS+0x10..BS+0x68 = exactly 22 u32 slots, and the reference prints ALL of them.
    # Two earlier count theories both died on a second witness (bones: fish 22 bones/22
    # entries was a coincidence - sharkhammer has 19 bones and still 22 entries; children and
    # groups counts likewise). No stored count field exists in BS or l1 for it (scanned).
    n_links = 22
    idx = [str(_yU(r, bs + 0x10 + i * 4)) for i in range(n_links)]
    flg = [str(r.sys[bs + 0x8A + i]) for i in range(n_links)]
    L = ["   <ArticulatedBody>"]
    L.append("    <ItemIndices>%s</ItemIndices>" % " ".join(idx))
    L.append("    <ItemFlags>%s</ItemFlags>" % " ".join(flg))
    L.append("    <UnknownVectors>")
    _, vecs = r.deref(_yU(r, bs + 0x80), n_bodies * 16)
    for i in range(n_bodies):
        v = [_yf(r, vecs + i * 16 + c * 4) for c in range(4)]
        L.append("     %s" % ", ".join(_F(x) for x in v))
    L.append("    </UnknownVectors>")
    L.append("    <Joints>")
    _, tab = r.deref(_yU(r, bs + 0x78), n_joints * 8)
    for i in range(n_joints):
        _, it = r.deref(_yU(r, tab + i * 8), 0xF0)
        vt = _yU(r, it)
        typ = _ARTICULATED_JOINT_TYPES.get(vt)
        if typ is None:
            raise ValueError("articulated joint %d: UNWITNESSED vtable 0x%08X - refusing to "
                             "guess its DOF type" % (i, vt))
        L.append('     <Item type="%s">' % typ)
        L.append('      <FragIndex1 value="%d" />' % r.sys[it + 0x16])
        L.append('      <FragIndex2 value="%d" />' % r.sys[it + 0x17])
        L.append('      <Unknown10 value="%s" />' % _F(_yf(r, it + 0x10)))
        for tag, off in (("Unknown20", 0x20), ("Unknown30", 0x30), ("Unknown40", 0x40),
                         ("Unknown50", 0x50), ("Unknown60", 0x60), ("Unknown70", 0x70),
                         ("Unknown80", 0x80), ("Unknown90", 0x90), ("UnknownA0", 0xA0)):
            v = [_yf(r, it + off + c * 4) for c in range(4)]
            L.append('      <%s x="%s" y="%s" z="%s" w="%s" />'
                     % ((tag,) + tuple(_F(x) for x in v)))
        L.append("     </Item>")
    L.append("    </Joints>")
    L.append("   </ArticulatedBody>")
    return L


def _emit_physics(r):
    l1 = _lod1_base(r)
    if l1 is None:
        # MEASURED: fragroot+0xF0 == 0 -> no phys-LOD group -> the reference export omits
        # <Physics> ENTIRELY (the file keeps Name/BoundingSphere/Unknown*/Gravity/Buoyancy/
        # Drawable/BoneTransforms/Lights and nothing else). 4 of the 77 yft oracles are this
        # shape and all 4 have fragroot+0xF0 == 0, while every oracle that HAS <Physics> carries
        # a live tagged pointer there - a 1:1 correlation with no exceptions.
        return []
    L = [" <Physics>", "  <LOD1>"]
    L.append('   <Unknown14 value="%s" />' % _F(_yf(r, l1 + 0x14)))
    L.append('   <Unknown18 value="%s" />' % _F(_yf(r, l1 + 0x18)))
    L.append('   <Unknown1C value="%s" />' % _F(_yf(r, l1 + 0x1C)))
    L.append('   <PositionOffset x="%s" y="%s" z="%s" />' % tuple(_F(x) for x in _yv3(r, l1 + 0x30)))
    L.append('   <Unknown40 x="%s" y="%s" z="%s" />' % tuple(_F(x) for x in _yv3(r, l1 + 0x40)))
    L.append('   <Unknown50 x="%s" y="%s" z="%s" />' % tuple(_F(x) for x in _yv3(r, l1 + 0x50)))
    for nm, off in (("DampingLinearC", 0x60), ("DampingLinearV", 0x70), ("DampingLinearV2", 0x80),
                    ("DampingAngularC", 0x90), ("DampingAngularV", 0xA0), ("DampingAngularV2", 0xB0)):
        L.append('   <%s x="%s" y="%s" z="%s" />' % ((nm,) + tuple(_F(x) for x in _yv3(r, l1 + off))))
    _, ab = r.deref(_yU(r, l1 + 0xD8), 0x80)                    # Archetype
    L.append("   <Archetype>")
    L.append("    <Name>%s</Name>" % esc(r.cstr(_yU(r, ab + 0x18))))
    L.append('    <Mass value="%s" />' % _F(_yf(r, ab + 0x40)))
    L.append('    <MassInv value="%s" />' % _F(_yf(r, ab + 0x44)))
    L.append('    <Unknown48 value="%s" />' % _F(_yf(r, ab + 0x48)))
    L.append('    <Unknown4C value="%s" />' % _F(_yf(r, ab + 0x4C)))
    L.append('    <Unknown50 value="%s" />' % _F(_yf(r, ab + 0x50)))
    L.append('    <Unknown54 value="%s" />' % _F(_yf(r, ab + 0x54)))
    L.append('    <InertiaTensor x="%s" y="%s" z="%s" />' % tuple(_F(x) for x in _yv3(r, ab + 0x60)))
    L.append('    <InertiaTensorInv x="%s" y="%s" z="%s" />' % tuple(_F(x) for x in _yv3(r, ab + 0x70)))
    _, bo = r.deref(_yU(r, ab + 0x20), 0x70)                    # phBound composite -> REUSE _bound_lines
    L += _bound_lines(r, bo, "    ", "Bounds", "archetype")
    L.append("   </Archetype>")
    L += _emit_articulated(r, l1)
    _, to = r.deref(_yU(r, l1 + 0x100), 0x200); tn = _yU(r, to + 0x10)    # Transforms
    L.append("   <Transforms>")
    for i in range(tn):
        b = to + 0x20 + i * 0x40
        L.append("    <Item>")
        for row in range(4):
            m = _yv4(r, b + row * 0x10)
            L.append("     %s %s %s %s" % (_F(m[0]), _F(m[1]), _F(m[2]), _F(m[3])))
        L.append("    </Item>")
    L.append("   </Transforms>")
    L += _emit_groups(r, l1)
    L += _emit_children(r, l1)
    # UnknownData1/2 — u8 index tables (the articulated animals' last section, 2026-08-08):
    # ptrs @ l1+0x108 / l1+0x110, counts u8 @ l1+0x118 / l1+0x119 (hen: both 69, matching its
    # oracle arrays exactly; a file can carry either or both — presence = non-null ptr).
    # Rendering: 10 values per line.
    for tag, poff, coff in (("UnknownData1", 0x108, 0x118), ("UnknownData2", 0x110, 0x119)):
        p = _yU(r, l1 + poff)
        if (p >> 28) != 5:
            continue
        n = r.sys[l1 + coff]
        if n == 0:
            continue    # absent != empty: cormorant carries a live ptr with count 0 and the
                        # reference omits the element entirely
        _, arr = r.deref(p, n)
        L.append("   <%s>" % tag)
        for i in range(0, n, 10):
            L.append("    " + " ".join(str(r.sys[arr + j]) for j in range(i, min(i + 10, n))))
        L.append("   </%s>" % tag)
    L += ["  </LOD1>", " </Physics>"]
    return L


def _fragment_lights(r):
    """The fragment-level light array: ptr @ fragroot+0x110, u16 count @ +0x118, the same
    0xA8 LightAttrs records the drawable slot pair carries (m26 interior screens, 2026-08-08).
    Returns the drawable-style placeholder when absent so callers can substitute."""
    from ydr2xml import light_items_lines
    p = _yU(r, 0x110)
    n = struct.unpack_from("<H", r.sys, 0x118)[0]
    if (p >> 28) != 5 or not n:
        return [" <Lights />"]
    buf, off = r.deref(p, n * 0xA8)
    if buf is None:
        _refuse("fragment_lights_array_unresolved", "%d lights" % n)
        return [" <Lights />"]
    return light_items_lines(buf, off, n)


def _emit_vehicle_glass(r):
    """<VehicleGlassWindows> @ fragroot+0x120 — the breakable-glass manager ('HWGV'), a
    DIFFERENT array from <GlassWindows> @ +0xE0. [] when the pointer is absent.

    Derivation (2026-08-08, value-matched 15/15 windows across cablecar+driftsentinel2):
    manager: tag 'HWGV' · count u16 @+0x06 · totalSize u32 @+0x08 · count × (u32 ItemID,
    u32 recordOffset) pairs @+0x0C — the reference emits windows in TABLE order.
    record @ manager+offset: Projection f32 grid @+0x00, STORED TRANSPOSED — oracle[r][c]
    reads from `+ c*16 + r*4` · tag 'VGWC' @+0x40 · ItemID u16 @+0x44 (self-checked vs the
    table 15/15) · UnkUshort1 @+0x46 · ShatterMap dims u16 w @+0x48 / h @+0x4A · UnkFloat17
    @+0x58 · UnkFloat18 @+0x5C · UnkUshort4 @+0x60 · UnkUshort5 @+0x62 · CracksTextureTiling
    @+0x64. ShatterMap raster: u16 cumulative row-offset table @+0x72 with (h-1) entries,
    then rows stored CONSECUTIVELY: each = u8 firstCol, u8 lastCol, data[last-first+1],
    0xFF terminator (blob sizes reproduce the cumulative table with zero residue). Rendering:
    cells outside [first..last] = '##', byte 0xFF = '--', else uppercase hex."""
    p = _yU(r, 0x120)
    if (p >> 28) != 5:
        return []
    _, man = r.deref(p, 0x20)
    n = struct.unpack_from("<H", r.sys, man + 0x6)[0]
    if n == 0:
        return []
    L = [" <VehicleGlassWindows>"]
    for wi in range(n):
        item_id = _yU(r, man + 0x0C + wi * 8)
        rec = man + _yU(r, man + 0x10 + wi * 8)
        rec_id = struct.unpack_from("<H", r.sys, rec + 0x44)[0]
        if rec_id != item_id:
            raise ValueError("vehicle glass window %d: table ItemID %d != record ItemID %d"
                             % (wi, item_id, rec_id))
        L.append("  <Window>")
        L.append('   <ItemID value="%d" />' % item_id)
        L.append('   <UnkUshort1 value="%d" />'
                 % struct.unpack_from("<H", r.sys, rec + 0x46)[0])
        L.append('   <UnkUshort4 value="%d" />'
                 % struct.unpack_from("<H", r.sys, rec + 0x60)[0])
        L.append('   <UnkUshort5 value="%d" />'
                 % struct.unpack_from("<H", r.sys, rec + 0x62)[0])
        L.append("   <Projection>")
        for row in range(4):
            vals = [_yf(r, rec + c * 16 + row * 4) for c in range(4)]
            L.append("    %s %s %s %s" % tuple(_F(v) for v in vals))
        L.append("   </Projection>")
        L.append('   <UnkFloat17 value="%s" />' % _F(_yf(r, rec + 0x58)))
        L.append('   <UnkFloat18 value="%s" />' % _F(_yf(r, rec + 0x5C)))
        L.append('   <CracksTextureTiling value="%s" />' % _F(_yf(r, rec + 0x64)))
        w = struct.unpack_from("<H", r.sys, rec + 0x48)[0]
        h = struct.unpack_from("<H", r.sys, rec + 0x4A)[0]
        # dims (1,1) = the NO-ShatterMap sentinel: polbuffalo carries 12 such records and the
        # reference omits the raster for every one (12/12), while every >1x1 record has one.
        if w and h and (w, h) != (1, 1):
            L.append("   <ShatterMap>")
            pos = rec + 0x72 + (h - 1) * 2
            for _row in range(h):
                # A row = strictly-rightward SPANS: (first u8, last u8, data[last-first+1]).
                # Row boundary is EITHER an explicit 0xFF sentinel where the next `first`
                # would sit, OR IMPLICIT: a following span whose `first` does not continue
                # strictly rightward belongs to the NEXT row (the encoder omits the sentinel
                # exactly when that backtrack makes the boundary unambiguous — measured:
                # cablecar win0 rows 5/6 end at w-1 with no sentinel; win5 short rows keep
                # theirs). Rendering: unstored gap cells BETWEEN spans = '--', cells outside
                # every span = '##', and a STORED 0xFF byte prints as literal 'FF' (win4
                # row4: "...EBF7FF----" — the FF is data, the run is the gap).
                spans = []
                prev_last = -1
                while True:
                    if r.sys[pos] == 0xFF:
                        pos += 1                              # explicit row-end sentinel
                        break
                    first = r.sys[pos]
                    last = r.sys[pos + 1]
                    if first <= prev_last:
                        break             # implicit boundary: span belongs to the next row
                    if not (first <= last < w):
                        raise ValueError(
                            "vehicle glass window %d: shatter span %d..%d outside width %d"
                            % (wi, first, last, w))
                    spans.append((first, last,
                                  r.sys[pos + 2:pos + 2 + (last - first + 1)]))
                    prev_last = last
                    pos += 2 + (last - first + 1)
                cells = ["##"] * w
                if spans:
                    for c in range(spans[0][0], spans[-1][1] + 1):
                        cells[c] = "--"
                    for first, last, data in spans:
                        for k, b in enumerate(data):
                            cells[first + k] = "%02X" % b
                L.append("    " + "".join(cells))
            L.append("   </ShatterMap>")
        L.append("  </Window>")
    L.append(" </VehicleGlassWindows>")
    return L


def _emit_glass(r):
    """<GlassWindows> @ fragroot+0xE0 (count u8 @+0xD9, stride 0x70). [] when absent."""
    cnt = r.sys[0xD9]; p = _yU(r, 0xE0)
    if (p >> 28) != 5 or cnt == 0:
        return []
    _, arr = r.deref(p, cnt * 8)
    L = [" <GlassWindows>"]
    for wi in range(cnt):
        base = _yM(_yU(r, arr + wi * 8))
        L.append("  <Item>")
        L.append('   <Flags value="%d" />' % struct.unpack_from("<H", r.sys, base + 0x56)[0])
        L.append("   <Projection>")
        for row in range(3):
            m = _yv3(r, base + row * 0x10)
            L.append("    %s %s %s" % (_F(m[0]), _F(m[1]), _F(m[2])))
        L.append("   </Projection>")
        for tag, off in (("UnkFloat13", 0x30), ("UnkFloat14", 0x34), ("UnkFloat15", 0x38),
                         ("UnkFloat16", 0x3C), ("Thickness", 0x50), ("UnkFloat18", 0x58),
                         ("UnkFloat19", 0x5C)):
            L.append('   <%s value="%s" />' % (tag, _F(_yf(r, base + off))))
        L.append('   <Tangent x="%s" y="%s" z="%s" />' % tuple(_F(x) for x in _yv3(r, base + 0x60)))
        L.append('   <Layout type="GTAV4">')
        for c in ("Position", "Normal", "Colour0", "TexCoord0", "TexCoord1"):
            L.append("    <%s />" % c)
        L.append("   </Layout>")
        L.append("  </Item>")
    L.append(" </GlassWindows>")
    return L


def _joints_lines(r, dbase, ind):
    """<Joints> @ drawable+0x90 — joint DOF limits (doors, rotors). NULL pointer = absent
    (2/2 controls). Header: RotationLimits ptr @ jo+0x10 · TranslationLimits ptr @ jo+0x18 ·
    counts u16 rot @ jo+0x30, trans @ jo+0x32 (cablecar 0/2, luiva 3/0 — both oracle-exact).
    ROTATION item, stride 0xC0: BoneId u32 @+0x08 · Min vec3 @+0x5C · Max vec3 @+0x68
    (luiva 3/3 field-matched incl. item2 Max.x=0.785398; the ±π fields around them are the
    engine's default-limit lattice, not emitted). TRANSLATION item, stride 0x40: BoneId @+0x08
    · Min vec3 @+0x20 · Max vec3 @+0x2C (contiguous, mirroring rotation's Min→Max adjacency;
    ⚠ unseparated-from-zero until a non-zero translation Max witness exists).
    UnknownA: zero in every witnessed rotation item — unseparated literal."""
    tagged = _yU(r, dbase + 0x90)
    if not (tagged & 0x0FFFFFFF):
        return []
    _, jo = r.deref(tagged, 0x40)
    rot_n = struct.unpack_from("<H", r.sys, jo + 0x30)[0]
    trans_n = struct.unpack_from("<H", r.sys, jo + 0x32)[0]
    L = [ind + "<Joints>"]
    if rot_n:
        _, rp = r.deref(_yU(r, jo + 0x10), rot_n * 0xC0)
        L.append(ind + " <RotationLimits>")
        for i in range(rot_n):
            b = rp + i * 0xC0
            L.append(ind + "  <Item>")
            L.append(ind + '   <BoneId value="%d" />' % _yU(r, b + 0x08))
            L.append(ind + '   <UnknownA value="0" />')
            L.append(ind + '   <Min x="%s" y="%s" z="%s" />'
                     % tuple(_F(x) for x in _yv3(r, b + 0x5C)))
            L.append(ind + '   <Max x="%s" y="%s" z="%s" />'
                     % tuple(_F(x) for x in _yv3(r, b + 0x68)))
            L.append(ind + "  </Item>")
        L.append(ind + " </RotationLimits>")
    if trans_n:
        _, tp = r.deref(_yU(r, jo + 0x18), trans_n * 0x40)
        L.append(ind + " <TranslationLimits>")
        for i in range(trans_n):
            b = tp + i * 0x40
            L.append(ind + "  <Item>")
            L.append(ind + '   <BoneId value="%d" />' % _yU(r, b + 0x08))
            L.append(ind + '   <Min x="%s" y="%s" z="%s" />'
                     % tuple(_F(x) for x in _yv3(r, b + 0x20)))
            L.append(ind + '   <Max x="%s" y="%s" z="%s" />'
                     % tuple(_F(x) for x in _yv3(r, b + 0x2C)))
            L.append(ind + "  </Item>")
        L.append(ind + " </TranslationLimits>")
    L.append(ind + "</Joints>")
    return L


def _drawable_body(res, base, wrap):
    """drawable_lines(base) with the fragment <Matrix> (drawable+0xB0, 4x3, NaN 4th col dropped)
    spliced after <Name>, the trailing <Lights> element RELOCATED out (returned separately), and
    every line re-indented by `wrap`. -> (body_lines, lights_lines)."""
    inner = res.cstr(res.ptr(base + 0xA8)) or "skel"           # +0xA8 name ptr NULL -> "skel" (all yft)
    try:
        body = drawable_lines(res, inner, base=base)
    except ValueError as ex:
        if "no geometry decoded" not in str(ex):
            raise
        _refuse("main_drawable_empty_geometry_in_child", "%s" % ex)
        body = drawable_lines(res, inner, base=base, allow_empty=True)
    # <Joints> sits between </Skeleton> and the model groups (oracle order). Presence-gated on
    # drawable+0x90; a joints struct with no skeleton element is an unwitnessed shape -> counted.
    jl = _joints_lines(res, base, " ")
    if jl:
        for i, ln in enumerate(body):
            if ln.strip() == "</Skeleton>":
                body[i + 1:i + 1] = jl
                break
        else:
            _refuse("joints_present_but_no_skeleton_element", inner)
    lights = [" <Lights />"]
    if body and body[-1].strip() == "<Lights />":
        lights = [body.pop()]
    elif body and body[-1].strip() == "</Lights>":
        for i in range(len(body) - 1, -1, -1):
            if body[i].strip() == "<Lights>":
                lights = body[i:]; del body[i:]; break
    mtx = [" <Matrix>"]
    for row in range(4):
        m = _yv3(res, base + 0xB0 + row * 0x10)
        mtx.append("  %s %s %s" % (_F(m[0]), _F(m[1]), _F(m[2])))
    mtx.append(" </Matrix>")
    body = body[:1] + mtx + body[1:]
    return [wrap + ln for ln in body], lights


def _is_cloth(r):
    """A cloth fragment carries a populated environmentCloth pgArray @ fragroot+0x60 (count @+0x68)."""
    return (_yU(r, _CLOTH_ARR) >> 28) == 5 and struct.unpack_from("<H", r.sys, 0x68)[0] > 0


def _emit_cloths(r):
    """<Cloths> - the environmentCloth array @ fragroot+0x60. Controller offsets match the yld
    clothController; the VerletCloth1/BridgeSimGfx/Constraints decoders are the yld ones (BBMin is
    @verlet+0x30 here, not +0x10). MorphController is the fragment-only member the yld lacks."""
    S = r.sys
    def u32(o): return struct.unpack_from("<I", S, o)[0]
    def u16(o): return struct.unpack_from("<H", S, o)[0]
    def ff(o): return struct.unpack_from("<f", S, o)[0]
    def mk(o): return u32(o) & 0x0FFFFFFF
    def arr(o): return (mk(o), u16(o + 8))
    ap, cnt = arr(_CLOTH_ARR)
    L = [" <Cloths>"]
    for ci in range(cnt):
        item = mk(ap + ci * 8)
        ctrl = mk(item + 0x28)
        name = S[ctrl + 0x58:S.find(b"\x00", ctrl + 0x58)].decode("latin-1")
        L.append("  <Item>")
        L.append('   <Unknown78 value="%d" />' % u32(item + 0x78))
        L.append("   <Controller>")
        L.append("    <Name>%s</Name>" % esc(name))
        L.append('    <Type value="%d" />' % u32(ctrl + 0x50))
        L.append('    <Unknown78 value="%s" />' % _F(ff(ctrl + 0x78)))
        # BridgeSimGfx - arrays OMIT-EMPTY (cloth_01 has an empty Unknown20 -> no element at all)
        bg = mk(ctrl + 0x10)
        L.append("    <BridgeSimGfx>")
        L.append('     <VertexCount value="%d" />' % u32(bg + 0x10))
        L.append('     <Unknown14 value="%d" />' % u32(bg + 0x14))
        L.append('     <Unknown18 value="%d" />' % u32(bg + 0x18))
        for tag, ao, kind in (("Unknown20", 0x20, "f"), ("Unknown60", 0x60, "f"), ("UnknownA0", 0xA0, "f"),
                              ("UnknownE0", 0xE0, "u16"), ("Unknown128", 0x128, "u32")):
            p, c = arr(bg + ao)
            if not c:
                continue
            if kind == "f":
                L += num_list(tag, [ff(p + i * 4) for i in range(c)], "     ")
            elif kind == "u16":
                L += scalar_list(tag, [u16(p + i * 2) for i in range(c)], "     ")
            else:
                L += scalar_list(tag, [u32(p + i * 4) for i in range(c)], "     ")
        L.append("    </BridgeSimGfx>")
        # MorphController (fragment-only): ctrl+0x18 -> struct, +0x18 -> struct, +0x180 = Unknown180
        mc = mk(ctrl + 0x18); u18 = mk(mc + 0x18)
        L.append("    <MorphController>")
        L.append("     <Unknown18>")
        L.append('      <Unknown180 value="%d" />' % u32(u18 + 0x180))
        L.append("     </Unknown18>")
        L.append("    </MorphController>")
        # VerletCloth1
        vc = mk(ctrl + 0x20)
        L.append("    <VerletCloth1>")
        L.append('     <BBMin x="%s" y="%s" z="%s" />' % (_F(ff(vc + 0x30)), _F(ff(vc + 0x34)), _F(ff(vc + 0x38))))
        L.append('     <BBMax x="%s" y="%s" z="%s" />' % (_F(ff(vc + 0x40)), _F(ff(vc + 0x44)), _F(ff(vc + 0x48))))
        L.append('     <Unknown3C value="%d" />' % u32(vc + 0x3C))
        L.append('     <Unknown4C value="%d" />' % u32(vc + 0x4C))
        L.append('     <Unknown50 value="%s" />' % _F(ff(vc + 0x50)))
        L.append('     <UnknownA8 value="%s" />' % _F(ff(vc + 0xA8)))
        L.append('     <UnknownAC value="%s" />' % _F(ff(vc + 0xAC)))
        L.append('     <UnknownE8 value="%d" />' % u32(vc + 0xE8))
        L.append('     <UnknownFA value="%d" />' % u16(vc + 0xFA))
        L.append('     <Unknown148 value="%d" />' % u16(vc + 0x148))
        L.append('     <Unknown158 value="%s" />' % _F(ff(vc + 0x158)))
        L.append("     <Unknown140 />")
        L.append("     <Behaviour />")
        vp, vcnt = arr(vc + 0x80)
        L += _vec4_block(S, vp, vcnt, "Vertices", "     ")
        cp, ccnt = arr(vc + 0x110)
        L.append("     <Constraints>")
        for k in range(ccnt):
            o = cp + k * 16
            L.append("      <Item>")
            L.append('       <Unknown0 value="%d" />' % u16(o))
            L.append('       <Unknown2 value="%d" />' % u16(o + 2))
            L.append('       <Unknown4 value="%s" />' % _F(ff(o + 4)))
            L.append('       <Unknown8 value="%s" />' % _F(ff(o + 8)))
            L.append('       <UnknownC value="%s" />' % _F(ff(o + 12)))
            L.append("      </Item>")
        L.append("     </Constraints>")
        # Cloth CUSTOM BOUNDS - a full composite phBound @ verlet+0x18, emitted by the
        # reference as the LAST VerletCloth1 child (after Constraints). NULL pointer = the
        # element is OMITTED entirely (id2_21-class cloths carry none). Witnesses:
        # vb_34_hut_03_rib2 / vb_34_hut_04_rib / vb_36_hut_07_rib - the "small props ~2.6 KB
        # short" spot-diff class was exactly this drop. Same composite emitter the archetype
        # bound reuses; nothing cloth-specific to derive.
        cb = u32(vc + 0x18)
        if cb & 0x0FFFFFFF:
            _, cbo = r.deref(cb, 0x70)
            # absent_flags_text="NONE": the cloth bound's flags array is null in 3/3 witnesses
            # while the reference still prints NONE per child (physics bounds omit instead -
            # the presence rule is context-measured, see _bound_lines)
            L += _bound_lines(r, cbo, "     ", "Bounds", "verlet cloth custom bounds",
                              absent_flags_text="NONE")
        L.append("    </VerletCloth1>")
        L.append("   </Controller>")
        _, dbase = r.deref(u32(item + 0x18), 0xD0)              # cloth drawable == frag+0x30
        body, _lights = _drawable_body(r, dbase, "   ")
        L.append("   <Drawable>")
        L.extend(body)
        L.append("   </Drawable>")
        L.append("  </Item>")
    L.append(" </Cloths>")
    return L


def convert(res, stem, extras=None):
    """-> (xml text, []). THE entry point; byte-identical vs the reference exporter oracle. `extras` is
    accepted for call-site compatibility but no longer changes output - the full fragment is always
    built. Sidecars are [] here; quarry.to_interchange_xml still appends the embedded-texture ones."""
    # v160 = the vehicle-MOD-PART stamp (tampa/torn/serrano2 wings, polbuffalo, seashark3…):
    # SAME layout as 162 — three witnesses decode byte-identical against fresh oracles under
    # the 162 offsets (v160_probe.py, 2026-08-08), and every accepted file's own oracle
    # byte-compare is its per-file proof. Accepted AND COUNTED so a rising count stays visible.
    try:
        res.require_version(YFT_VERSION, "Legacy fragment")
    except ValueError:
        res.require_version(160, "Legacy fragment (v160 mod-part stamp)")
        _refuse("fragment_v160_accepted_same_layout_as_162", stem)
    frag_name = res.cstr(res.u32(NAME_SLOT))
    if not frag_name:
        _refuse("fragment_name_absent_stem_substituted", stem)
        frag_name = "pack:/" + stem
    _, draw_base = res.deref(res.u32(DRAWABLE_SLOT), 0xD0)
    if draw_base is None:
        raise ValueError("main drawable pointer (+0x30) does not resolve")
    nb = _bone_count(res, draw_base)

    L = ['<?xml version="1.0" encoding="UTF-8"?>', "<Fragment>"]
    L.append(" <Name>%s</Name>" % esc(frag_name))
    L += _frag_header(res)
    if _is_cloth(res):
        # cloth: NO top-level <Drawable>; the drawable is emitted under <Cloths><Item>
        L += _bone_transforms(res, nb)
        L += _emit_physics(res)
        L += _emit_vehicle_glass(res)
        L += _fragment_lights(res)
        L += _emit_cloths(res)
    else:
        body, lights = _drawable_body(res, draw_base, " ")
        L.append(" <Drawable>")
        L.extend(body)
        L.append(" </Drawable>")
        L += _bone_transforms(res, nb)
        L += _emit_physics(res)
        L += _emit_vehicle_glass(res)                          # oracle order: right after </Physics>
        L += _emit_glass(res)
        # the fragment's OWN light array (fragroot ptr @0x110, u16 count @0x118, the same
        # 0xA8 LightAttrs records — m26 interior screens witnessed 2026-08-08) replaces the
        # drawable's popped placeholder when present
        fl = _fragment_lights(res)
        L += fl if fl != [" <Lights />"] else lights
    L.append("</Fragment>")
    return "\n".join(L) + "\n", []


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
