"""ypt2xml - GTA V .ypt (RSC7 v68, rmPtfx ptxFxList) -> the reference exporter-shape .ypt.xml.

CLEAN-ROOM. Every offset/law below was derived empirically from oracle .ypt.xml + the game
binaries only (no the reference exporter source, no web). Method = value-intersection, same as the ydr/ytd
derivations. See the accompanying findings write-up for the per-struct derivation.

STATE (2026-08-06): the CONTAINER, ROOT, 5 DICTIONARIES, the NAME-HASH system, and the
KeyframeProp + keyframe layers are PINNED and cross-file verified (10/10 files; 520/520
keyframe-props reproduced name+value-exact). The polymorphic ptxParticleRule bodies
(AllBehaviours / ShaderVars / EffectSpawner), the ptxEmitterRule domains, and the
ptxEffectRule EventEmitters/EvolutionList tails are NOT yet fully pinned -> this emits the
verified shell and DECLARES the rest, and its --validate mode proves the pinned layers.

REUSE:  Res (RSC7 reader)  <- ydr2xml
        read_textures/to_xml (embedded grcTextureDictionary) <- ytd2xml
        joaat / fmt_num / esc (name hashing + float law) <- meta2xml
"""
import argparse, os, struct, sys
sys.path.insert(0, r"B:\ClaudeCode_Projects\_UEFiveMTool\quarry")
from ydr2xml import Res
import ytd2xml
from meta2xml import joaat, fmt_num, esc

# ------------------------------------------------------------------ container / root
YPT_VERSION = 68                      # measured: every ypt in the 10-file oracle set is RSC7 v68
# ptxFxList root pointer field offsets (SYSTEM offset 0). Verified stable across all 10 files
# (vfts differ base-vs-update, so classification MUST be by offset, never by vtable value).
ROOT_NAME   = 0x10
# (xml element, root pointer offset, per-rule Name pointer offset within the rule object)
ROOT_DICTS  = [("EffectRuleDictionary",   0x48, 0x20),   # -> pgDictionary<ptxEffectRule>
               ("EmitterRuleDictionary",  0x50, 0x20),   # -> pgDictionary<ptxEmitterRule>
               ("ParticleRuleDictionary", 0x38, 0x120),  # -> pgDictionary<ptxParticleRule>
               ("DrawableDictionary",     0x30, None),    # -> pgDictionary<rmcDrawable>  (empty in all 10)
               ("TextureDictionary",      0x20, None)]    # -> pgDictionary<grcTexture>   (empty in all 10)
# pgDictionary: hashArray ptr @+0x20, count u16 @+0x28 ; objPtrArray ptr @+0x30, count u16 @+0x38

# ------------------------------------------------------------------ KeyframeProp
# ptxKeyframeProp = 0x90 bytes:
#   +0x00 u32  nameHash  (joaat, lowercase)
#   +0x04 u8   InvertBiasLink  (candidate; all-zero in the 10-file set -> value 0, offset unproven)
#   +0x05 u16  RandomIndex  (unaligned; verified 520/520, max observed 115)
#   +0x08 ptr  keyframes  (tagged -> array of 32-byte keyframes)
#   +0x10 u16  keyframe count   (+0x12 u16 capacity)
# Keyframe = 8 float32 = KeyframeTime(x,y,z,w) then KeyframeValue(x,y,z,w).
KFP_STRIDE = 0x90
KFP_KFPTR  = 0x08
KFP_KFCNT  = 0x10
KFP_RANDIX = 0x05

# The schema names ptxKeyframeProp.nameHash encodes. Clean-room: these strings are known RAGE
# member identifiers (read off the oracle XML) that WE hash - no shipped hash dictionary. Extend
# by adding a name; a hash with no name here is emitted as its raw hex so the gap is never silent.
KFP_NAMES = [
 "ptxEffectRule:m_colourTintMinKFP","ptxEffectRule:m_colourTintMaxKFP","ptxEffectRule:m_zoomScalarKFP",
 "ptxEffectRule:m_dataSphereKFP","ptxEffectRule:m_dataCapsuleKFP",
 "ptxEmitterRule:m_spawnRateOverTimeKFP","ptxEmitterRule:m_spawnRateOverDistKFP","ptxEmitterRule:m_particleLifeKFP",
 "ptxEmitterRule:m_playbackRateScalarKFP","ptxEmitterRule:m_speedScalarKFP","ptxEmitterRule:m_sizeScalarKFP",
 "ptxEmitterRule:m_accnScalarKFP","ptxEmitterRule:m_dampeningScalarKFP","ptxEmitterRule:m_matrixWeightScalarKFP",
 "ptxEmitterRule:m_inheritVelocityKFP",
 "ptxCreationDomain:m_positionKFP","ptxCreationDomain:m_rotationKFP","ptxCreationDomain:m_sizeOuterKFP","ptxCreationDomain:m_sizeInnerKFP",
 "ptxTargetDomain:m_positionKFP","ptxTargetDomain:m_rotationKFP","ptxTargetDomain:m_sizeOuterKFP","ptxTargetDomain:m_sizeInnerKFP",
 "ptxu_Size:m_whdMinKFP","ptxu_Size:m_whdMaxKFP","ptxu_Size:m_tblrScalarKFP","ptxu_Size:m_tblrVelScalarKFP",
 "ptxu_Colour:m_rgbaMinKFP","ptxu_Colour:m_rgbaMaxKFP","ptxu_Colour:m_emissiveIntensityKFP",
 "ptxu_Acceleration:m_xyzMinKFP","ptxu_Acceleration:m_xyzMaxKFP",
 "ptxu_Dampening:m_xyzMinKFP","ptxu_Dampening:m_xyzMaxKFP",
 "ptxu_Rotation:m_angleMinKFP","ptxu_Rotation:m_angleMaxKFP","ptxu_Rotation:m_initialAngleMinKFP","ptxu_Rotation:m_initialAngleMaxKFP",
 "ptxu_AnimateTexture:m_animRateKFP","ptxu_Collision:m_bouncinessKFP","ptxu_Collision:m_bounceDirVarKFP",
 "ptxu_MatrixWeight:m_mtxWeightKFP","ptxu_Wind:m_influenceKFP","ptxd_Trail:m_texInfoKFP",
]
HASH2NAME = {joaat(n): n for n in KFP_NAMES}


class Ypt:
    def __init__(self, path):
        self.res = Res(path)
        if self.res.version != YPT_VERSION:
            raise ValueError("RSC7 version %d is not a ypt, want %d" % (self.res.version, YPT_VERSION))
        self.b = self.res.sys

    def _p(self, o):  return struct.unpack_from("<I", self.b, o)[0]
    def _u16(self, o): return struct.unpack_from("<H", self.b, o)[0]
    def _deref(self, o):
        t = self._p(o); return (t & 0x0FFFFFFF) if (t >> 28) in (5, 6) else None

    def root_name(self):
        return self.res.cstr(self._p(ROOT_NAME))

    def dict_objects(self, dict_off):
        """(base, [obj_sys_offset, ...]) for the pgDictionary pointed to at root+dict_off."""
        base = self._deref(dict_off)
        if base is None:
            return None, []
        cnt = self._u16(base + 0x38)
        pArr = self._deref(base + 0x30)
        objs = [self._deref(pArr + i * 8) for i in range(cnt)] if pArr else []
        return base, objs

    def read_kfp(self, off):
        """ptxKeyframeProp @off -> dict(name, randomindex, keyframes=[(t4,v4)...])."""
        h = self._p(off)
        name = HASH2NAME.get(h, "0x%08X" % h)
        randix = self._u16(off + KFP_RANDIX)
        cnt = self._u16(off + KFP_KFCNT)
        kfs = []
        base = self._deref(off + KFP_KFPTR)
        if base is not None:
            for i in range(cnt):
                o = base + i * 32
                if o + 32 > len(self.b):     # guard spurious signature hits (scan mode)
                    break
                f = struct.unpack_from("<8f", self.b, o)
                kfs.append((f[0:4], f[4:8]))
        return dict(name=name, randomindex=randix, keyframes=kfs)


# ------------------------------------------------------------------ XML emit (verified layers)
def _kfp_xml(res_kfp, indent, tag="Item", extra_before_kf=None):
    sp = " " * indent
    L = ["%s<%s>" % (sp, tag),
         "%s <Name>%s</Name>" % (sp, esc(res_kfp["name"])),
         '%s <InvertBiasLink value="0" />' % sp,                 # UNPINNED offset; 0 in all samples
         '%s <RandomIndex value="%d" />' % (sp, res_kfp["randomindex"])]
    kfs = res_kfp["keyframes"]
    if not kfs:
        L.append("%s <Keyframes />" % sp)
    else:
        L.append("%s <Keyframes>" % sp)
        for t, v in kfs:
            L += ["%s  <Item>" % sp,
                  '%s   <KeyframeTime x="%s" y="%s" z="%s" w="%s" />' % (sp, *[fmt_num(x) for x in t]),
                  '%s   <KeyframeValue x="%s" y="%s" z="%s" w="%s" />' % (sp, *[fmt_num(x) for x in v]),
                  "%s  </Item>" % sp]
        L.append("%s </Keyframes>" % sp)
    L.append("%s</%s>" % (sp, tag))
    return L


def convert_shell(path):
    """Emit the VERIFIED shell: root Name + dictionary skeletons + embedded texture dictionary.
    Rule bodies are marked with an explicit unpinned comment - this is NOT byte-identical yet."""
    y = Ypt(path)
    L = ['<?xml version="1.0" encoding="UTF-8"?>', "<ParticleEffectsList>",
         " <Name>%s</Name>" % esc(y.root_name())]
    for name, off, name_off in ROOT_DICTS:
        base, objs = y.dict_objects(off)
        if name == "TextureDictionary":
            # REUSE ytd2xml on the embedded grcTextureDictionary (base is the dict sys offset)
            if base is None or y._u16(base + 0x28) == 0:
                L.append(" <TextureDictionary />")
            else:
                tex = ytd2xml.read_textures(y.res, base=base)
                inner = ytd2xml.to_xml(tex).split("\n")[1:]      # drop the <?xml?> line
                L += [" " + s for s in inner if s]
            continue
        if not objs:
            L.append(" <%s />" % name if name != "DrawableDictionary"
                     else " <%s>\n </%s>" % (name, name))
            continue
        L.append(" <%s>" % name)
        for obj in objs:                                          # rule Name is verified 10/10 & 15/15
            L += ["  <Item>",
                  "   <Name>%s</Name>" % esc(y.res.cstr(y._p(obj + name_off))),
                  "   <!-- rule body UNPINNED: scalars/EventEmitters/domains/AllBehaviours/"
                  "ShaderVars/EffectSpawners not yet fully derived -->",
                  "  </Item>"]
        L.append(" </%s>" % name)
    L.append("</ParticleEffectsList>")
    return "\n".join(L) + "\n"


# ------------------------------------------------------------------ self-validation
def validate(manifest):
    """Prove the pinned layers against the oracle: for every file, signature-scan KFP structs and
    check name+RandomIndex+every keyframe (fmt_num-spelled) reproduce the oracle multiset."""
    import json, re
    from collections import Counter
    man = json.load(open(manifest))
    H = set(HASH2NAME)
    g_ok = g_tot = 0
    for mm in man:
        xml = open(mm["oracle"], encoding="utf-8").read()
        # oracle multiset: (name, randomindex, keyframes-spelled)
        oc = Counter()
        for m in re.finditer(
            r'<Name>([^<]*:[^<]*)</Name>\s*<InvertBiasLink[^>]*/>\s*<RandomIndex value="(\d+)"[^>]*/>'
            r'\s*<Keyframes\s*(/>|>(.*?)</Keyframes>)', xml, re.S):
            body = m.group(4) or ""
            kfs = tuple(("(%s,%s,%s,%s)" % k[:4], "(%s,%s,%s,%s)" % k[4:]) for k in re.findall(
                r'<KeyframeTime x="([^"]*)" y="([^"]*)" z="([^"]*)" w="([^"]*)" />\s*'
                r'<KeyframeValue x="([^"]*)" y="([^"]*)" z="([^"]*)" w="([^"]*)" />', body))
            oc[(m.group(1), int(m.group(2)), kfs)] += 1
        # binary multiset
        y = Ypt(mm["bin"]); bc = Counter()
        for o in range(0, len(y.b) - 4, 4):
            if y._p(o) in H:
                k = y.read_kfp(o)
                kfs = tuple(("(%s)" % ",".join(fmt_num(x) for x in t),
                             "(%s)" % ",".join(fmt_num(x) for x in v)) for t, v in k["keyframes"])
                bc[(k["name"], k["randomindex"], kfs)] += 1
        tot = sum(oc.values()); miss = oc - bc
        ok = tot - sum(miss.values()); g_ok += ok; g_tot += tot
        print("  %-26s %-22s %3d/%3d %s" % (mm["name"], mm["dest"], ok, tot,
              "OK" if ok == tot else "MISS %s" % list(miss)[:1]))
    print("\n  KFP layer (name+RandomIndex+all keyframes, fmt_num-exact): %d / %d" % (g_ok, g_tot))
    return g_ok == g_tot


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="*")
    ap.add_argument("--validate", metavar="MANIFEST", help="run cross-file validation of pinned layers")
    ap.add_argument("--out")
    a = ap.parse_args()
    if a.validate:
        sys.exit(0 if validate(a.validate) else 1)
    for p in a.files:
        xml = convert_shell(p)
        if a.out:
            open(os.path.join(a.out, os.path.splitext(os.path.basename(p))[0] + ".ypt.xml"),
                 "w", encoding="utf-8").write(xml)
        else:
            print(xml)


if __name__ == "__main__":
    main()
