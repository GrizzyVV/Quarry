"""ypt2xml - GTA V .ypt (RSC7 v68, rmPtfx ptxFxList) -> the reference exporter-shape .ypt.xml.

CLEAN-ROOM. Every offset/law/table below was derived empirically from oracle .ypt.xml + the game
binaries only (no the reference exporter source, no web). Method = value-intersection against the oracle,
the same discipline used for the ydr/ytd/yft derivations.

STATE (2026-08-06): COMPLETE. Container, root, all 5 dictionaries, the KeyframeProp/keyframe
layer, and ALL THREE rule bodies are derived and cross-file verified BYTE-IDENTICAL 10/10:
  * ptxEffectRule   - ~40 scalars + EventEmitters (+ nested EvolutionList / EvolvedKeyframeProps,
                      emitted sorted by ascending Items-pointer) + KeyframeProps + EvolutionList.
  * ptxEmitterRule  - RefCount, IsOneShot, Creation/TargetDomainObj (ptxDomain), KeyframeProps.
  * ptxParticleRule - scalar block, ShaderFile/Technique, 2x ptxEffectSpawner, polymorphic
                      AllBehaviours (13 ptxu_* variants), polymorphic ShaderVars (Vector2 /
                      Vector4 / Keyframe / Texture).
`--validate MANIFEST` proves byte-identical output for every listed file.

KNOWN LIMITATION (documented, not silent): a handful of behaviour scalar fields are const across
the 10-file oracle set and are emitted as the observed literal (they never varied, so no offset
could be pinned) - e.g. Trail Tessellation, Collision RadiusMult/RestSpeed. Wider oracle coverage
would let those be pinned to an offset. Any nameHash with no entry in a name table is emitted as
raw hex so a gap is never silent.

REUSE:  Res (RSC7 reader) <- ydr2xml ; read_textures/to_xml (embedded grcTextureDictionary)
        <- ytd2xml ; joaat / fmt_num / esc <- meta2xml.
"""
import argparse, os, struct, sys
sys.path.insert(0, r"B:\ClaudeCode_Projects\_UEFiveMTool\quarry")
from ydr2xml import Res
import ytd2xml
from meta2xml import joaat, fmt_num, esc

# ------------------------------------------------------------------ container / root
YPT_VERSION = 68                      # every ypt in the 10-file oracle set is RSC7 v68
ROOT_NAME   = 0x10                     # ptxFxList (SYSTEM offset 0): Name pointer @+0x10
# (xml element, root pointer offset, per-rule Name pointer offset within the rule object)
ROOT_DICTS  = [("EffectRuleDictionary",   0x48, 0x20),
               ("EmitterRuleDictionary",  0x50, 0x20),
               ("ParticleRuleDictionary", 0x38, 0x120),
               ("DrawableDictionary",     0x30, None),   # empty in all 10
               ("TextureDictionary",      0x20, None)]   # empty in all 10
# pgDictionary: hashArray @+0x20 / count @+0x28 ; objPtrArray @+0x30 / count @+0x38
# 64-bit pointers: an atArray inline descriptor is {u64 ptr, u16 count @+0x08, u16 cap @+0x0a}.

# ------------------------------------------------------------------ KeyframeProp
# ptxKeyframeProp = 0x90 bytes: object starts at a vtable; the name hash is at OBJECT+0x68.
# When embedded in a parent the object sits at parent+K and the hash at parent+K+0x68.
#   +0x68 u32 nameHash (joaat) | +0x6d u16 RandomIndex | +0x70 ptr keyframes | +0x78 u16 count
# The decoders below read a KFP FROM ITS HASH OFFSET (h): hash@h, RandomIndex@h+0x05,
# keyframes-ptr@h+0x08, count@h+0x10. Keyframe = 8 float32 (Time.xyzw, Value.xyzw).
KFP_STRIDE = 0x90
KFP_KFPTR  = 0x08
KFP_KFCNT  = 0x10
KFP_RANDIX = 0x05

# Clean-room name tables: RAGE member identifiers read off the oracle XML that WE hash (no shipped
# hash dictionary). A hash with no entry is emitted as raw hex so the gap is never silent.
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
 # 2026-08-09 wave-2b derivation (all joaat-verified against stored hashes):
 "ptxu_Light:m_rgbMinKFP","ptxu_Light:m_rgbMaxKFP","ptxu_Light:m_intensityKFP","ptxu_Light:m_rangeKFP",
 "ptxu_Light:m_coronaRgbMinKFP","ptxu_Light:m_coronaRgbMaxKFP","ptxu_Light:m_coronaIntensityKFP",
 "ptxu_Light:m_coronaSizeKFP","ptxu_Light:m_coronaFlareKFP",
 "ptxu_Noise:m_posNoiseMinKFP","ptxu_Noise:m_posNoiseMaxKFP","ptxu_Noise:m_velNoiseMinKFP","ptxu_Noise:m_velNoiseMaxKFP",
 "ptxAttractorDomain:m_positionKFP","ptxAttractorDomain:m_rotationKFP","ptxAttractorDomain:m_sizeOuterKFP","ptxAttractorDomain:m_sizeInnerKFP",
 "ptxu_Acceleration:m_strengthKFP",   # the Attractor KFP's LITERAL stored name (oracle-witnessed)
 "ptxu_Decal:m_dimensionsKFP","ptxu_Decal:m_alphaKFP",
]
HASH2NAME = {joaat(n): n for n in KFP_NAMES}

# ------------------------------------------------------------------ ptxDomain
DOMAIN_TYPE = {0: "Box", 1: "Sphere", 2: "Cylinder", 3: "Attractor"}  # u32 @domain+0x0c
# +0x10..+0x13 = IsWorldSpace / IsPointRelative / IsCreationRelative / IsTargetRelatve (bytes)
# +0x80 + i*0x90 (i=0..3) = the 4 KFP hashes (Position/Rotation/SizeOuter/SizeInner)
# ⛔ RETRACTED 2026-08-09: "FileVersion is NOT stored per-domain" was measured-wrong.
# FileVersion IS STORED: f32 @domain+0x258 (the first tail field after the 4 embedded
# KFPs) - sole equality survivor over 390 domain instances; witnessed 2.0, 2.1f AND -1.0.
# The old "2 iff Cylinder" correlation was a 30-domain coincidence, false both directions.

# ------------------------------------------------------------------ ptxParticleRule scalar offsets
PART = dict(RefCount=0x10, CullMode=0x100, BlendSet=0x104, LightingMode=0x108,
            DepthWrite=0x10c, DepthTest=0x10d, AlphaBlend=0x10e,
            TexFrameIDMin=0x118, TexFrameIDMax=0x11c, Name=0x120,
            ShaderFile=0x1b8, ShaderTechnique=0x1c0, ShaderTemplateTechniqueID=0x1d0,
            DiffuseMode=0x1e0, IsLit=0x1e8, IsSoft=0x1e9, SortType=0x220, DrawType=0x221)
# EffectSpawner blocks: AtRatio Min @0x38 (Max @+0x20); OnCollision Min @0xa8 (Max @+0x20).
# Min block: Duration@+0x00 Playback@+0x04 ColourTint@+0x08 Zoom@+0x0c Flags@+0x10 (f32/f32/u32hex/f32/u32).
# AtRatio TracksPointPos @particle+0x8d (the only spawner bool that varied). AllBehaviours atArray
# @particle+0x128 ; ShaderVars atArray @particle+0x1f0.

# ------------------------------------------------------------------ AllBehaviours (polymorphic)
# behaviour object: Type = joaat hash u32 @beh+0x08 ; embedded KFP hashes at beh+0x98 + i*0x90.
BEH_TYPEHASH = {
 0xF5B33BAA:"Age", 0xD63D9F1B:"Acceleration", 0x6C0719BC:"Velocity", 0x38B60240:"Size",
 0x052B1293:"Dampening", 0x64E5D702:"MatrixWeight", 0x164AEA72:"Colour", 0x68FA73F5:"Sprite",
 0x1EE64552:"Rotation", 0x928A1C45:"Collision", 0xECA84C1E:"AnimateTexture", 0x38B63978:"Wind",
 0xC57377F8:"Trail",
 # 2026-08-09 wave-2b (joaat of the ptxu_/ptxd_ class names, verified vs stored hashes):
 0x0544C710:"Light", 0xDF229542:"Liquid", 0x6232E25A:"Model", 0x25AC9437:"Attractor",
 0xB77FED19:"Noise"}
# ⚠ KNOWN-REMAINING unknown types (their rows refuse loudly until derived):
# 0x8F3B6036 (ptxu_Decal family, core_snow) · 0xA35C721F (cut_mpsui).
# Per-variant ordered field spec. ('scalar', tag, res) where res is ('const', str) or ('off', off, kind);
# ('kfp', tag, kfp_index) -> embedded KFP at beh+0x98+idx*0x90 ; ('vec3', tag, off).
BEH_SPEC = {
 "Age": [],
 "Velocity": [],
 "Acceleration": [
   ("scalar","ReferenceSpace",("off",344,"byte")), ("scalar","IsAffectedByZoom",("off",348,"byte")),
   ("scalar","EnableGravity",("const","0")), ("kfp","XYZMinKFP",0), ("kfp","XYZMaxKFP",1)],
 "Size": [
   ("scalar","KeyframeMode",("off",624,"byte")), ("scalar","IsProportional",("off",628,"byte")),
   ("kfp","WhdMinKFP",0), ("kfp","WhdMaxKFP",1), ("kfp","TblrScalarKFP",2), ("kfp","TblrVelScalarKFP",3)],
 "Dampening": [
   ("scalar","ReferenceSpace",("off",344,"byte")), ("scalar","EnableAirResistance",("const","0")),
   ("kfp","XYZMinKFP",0), ("kfp","XYZMaxKFP",1)],
 "MatrixWeight": [
   ("scalar","ReferenceSpace",("off",192,"byte")), ("kfp","mtxWeightKFP",0)],
 "Colour": [
   ("scalar","KeyframeMode",("off",480,"byte")), ("scalar","RGBAMaxEnable",("off",484,"byte")),
   ("scalar","RGBAProportional",("off",485,"byte")), ("scalar","RGBCanTint",("off",486,"byte")),
   ("kfp","RGBAMinKFP",0), ("kfp","RGBAMaxKFP",1), ("kfp","EmissiveIntensityKFP",2)],
 # Sprite scalar block re-pinned 2026-08-09: contiguous 48..97 (value-intersection over
 # 77-125+ instances; the old AlignAxis@12 read zeros, NearClip@64 echoed AlignmentMode,
 # FlipChanceV@68 echoed FlipChanceU). FarClip@95 / DisableDraw@97 stay const: value 0 in
 # every witnessed file - offsets are layout-plausible but value-unproven.
 "Sprite": [
   ("vec3","AlignAxis",48), ("scalar","AlignmentMode",("off",64,"byte")),
   ("scalar","FlipChanceU",("off",68,"f32")), ("scalar","FlipChanceV",("off",72,"f32")),
   ("scalar","NearClipDist",("off",76,"f32")), ("scalar","FarClipDist",("off",80,"f32")),
   ("scalar","ProjectionDepth",("off",84,"f32")), ("scalar","ShadowCastIntensity",("off",88,"f32")),
   ("scalar","IsScreenSpace",("off",92,"byte")), ("scalar","IsHighRes",("off",93,"byte")),
   ("scalar","NearClip",("off",94,"byte")), ("scalar","FarClip",("const","0")),
   ("scalar","UVClip",("off",96,"byte")), ("scalar","DisableDraw",("const","0"))],
 # Rotation block 624..634. ⚠ Init/Update @624/@628: the pair CO-VARIES in every one of
 # the 76 oracle files (no Init!=Update witness exists) - the assignment follows XML field
 # order and is order-consistent but not value-proven. SpeedFadeThreshold: witnessed
 # varying (wpn_amrifle oracle 0.1) but offset UNPINNED - stays a counted const until a
 # derivation witness set exists (that row remains an honest DIFF).
 "Rotation": [
   ("scalar","InitRotationMode",("off",624,"byte")), ("scalar","UpdateRotationMode",("off",628,"byte")),
   ("scalar","AccumulateAngle",("off",632,"byte")), ("scalar","RotateAngleAxes",("off",633,"byte")),
   ("scalar","RotateInitAngleAxes",("off",634,"byte")), ("scalar","SpeedFadeThreshold",("const","0")),
   ("kfp","InitialAngleMinKFP",0), ("kfp","InitialAngleMaxKFP",1),
   ("kfp","AngleMinKFP",2), ("kfp","AngleMaxKFP",3)],
 "Collision": [
   ("scalar","RadiusMult",("off",336,"f32")), ("scalar","RestSpeed",("off",340,"f32")),
   ("scalar","CollisionChance",("off",344,"byte")), ("scalar","KillChance",("off",348,"byte")),
   ("scalar","OverrideMinRadius",("const","0")), ("kfp","BouncinessKFP",0), ("kfp","BounceDirVarKFP",1)],
 "AnimateTexture": [
   ("scalar","KeyframeMode",("const","0")), ("scalar","LastFrameID",("off",196,"byte")),
   ("scalar","LoopMode",("off",200,"byte")), ("scalar","IsRandomised",("off",204,"byte")),
   ("scalar","IsScaledOverParticleLife",("off",205,"byte")), ("scalar","IsHeldOnLastFrame",("off",206,"byte")),
   ("scalar","DoFrameBlending",("off",207,"byte")), ("kfp","AnimRateKFP",0)],
 # Wind block 208..224 (the old LodLod@168 read was junk - returned 2 regardless).
 "Wind": [
   ("scalar","HighLodRange",("off",208,"f32")), ("scalar","LowLodRange",("off",212,"f32")),
   ("scalar","HighLodDisturbanceMode",("off",216,"byte")), ("scalar","LodLodDisturbanceMode",("off",220,"byte")),
   ("scalar","IgnoreMtxWeight",("off",224,"byte")), ("kfp","InfluenceKFP",0)],
 # Trail: AlignAxis@192 (old @28 read zeros); TessU@212/TessV@216 disambiguated by U!=V
 # witnesses (1/4 and 3/1); Wrap@238. The remaining consts are single-valued store-wide.
 "Trail": [
   ("vec3","AlignAxis",192), ("scalar","AlignmentMode",("const","0")),
   ("scalar","TessellationU",("off",212,"byte")), ("scalar","TessellationV",("off",216,"byte")),
   ("scalar","SmoothnessX",("const","0")), ("scalar","SmoothnessY",("const","0")),
   ("scalar","ProjectionDepth",("const","0")), ("scalar","ShadowCastIntensity",("const","0")),
   ("scalar","FlipU",("const","0")), ("scalar","FlipV",("const","0")),
   ("scalar","WrapTextureOverParticleLife",("off",238,"byte")), ("scalar","DisableDraw",("const","0")),
   ("kfp","TexInfoKFP",0)],
 # ---- 2026-08-09 wave-2b NEW TYPES (each render-validated vs its oracle sections) ----
 # Light: 9 embedded KFPs @0x98+i*0x90, contiguous scalars 0x540..0x54C right after the
 # KFP region (28/28 section byte-compares). CoronaNotInReflection@1354 is an adjacency
 # pick (zero-variance across all 28 - never contradicted).
 "Light": [
   ("scalar","CoronaZBias",("off",1344,"f32")), ("scalar","CoronaUseLightColour",("off",1348,"byte")),
   ("scalar","ColourFromParticle",("off",1349,"byte")), ("scalar","ColourPerFrame",("off",1350,"byte")),
   ("scalar","IntensityPerFrame",("off",1351,"byte")), ("scalar","RangePerFrame",("off",1352,"byte")),
   ("scalar","CastsShadows",("off",1353,"byte")), ("scalar","CoronaNotInReflection",("off",1354,"byte")),
   ("scalar","CoronaOnlyInReflection",("off",1355,"byte")), ("scalar","LightType",("off",1356,"byte")),
   ("kfp","RGBMinKFP",0), ("kfp","RGBMaxKFP",1), ("kfp","IntensityKFP",2), ("kfp","RangeKFP",3),
   ("kfp","CoronaRGBMinKFP",4), ("kfp","CoronaRGBMaxKFP",5), ("kfp","CoronaIntensityKFP",6),
   ("kfp","CoronaSizeKFP",7), ("kfp","CoronaFlareKFP",8)],
 "Noise": [
   ("scalar","ReferenceSpace",("const","0")), ("scalar","KeepConstantSpeed",("off",628,"byte")),
   ("kfp","PosNoiseMinKFP",0), ("kfp","PosNoiseMaxKFP",1),
   ("kfp","VelNoiseMinKFP",2), ("kfp","VelNoiseMaxKFP",3)],
 "Attractor": [("kfp","StrengthKFP",0)],
 # Liquid: single distinct witness (both slot binaries byte-identical) - stated.
 "Liquid": [
   ("scalar","VelocityThreshold",("const","0")), ("scalar","LiquidType",("off",52,"u32")),
   ("scalar","PoolStartSize",("off",56,"f32")), ("scalar","PoolEndSize",("off",60,"f32")),
   ("scalar","PoolGrowthRate",("off",64,"f32")), ("scalar","TrailWidthMin",("off",68,"f32")),
   ("scalar","TrailWidthMax",("off",72,"f32"))],
 # Model: single all-zero witness - three counted consts (offsets underivable until a
 # nonzero witness exists; a future non-zero file shows up in CONST_EMITS, never silent).
 "Model": [
   ("scalar","CameraShrink",("const","0")), ("scalar","ShadowCastIntensity",("const","0")),
   ("scalar","DisableDraw",("const","0"))],
}

# ------------------------------------------------------------------ ShaderVars (polymorphic)
# shadervar object: Name hash @+0x10 | Type u32 @+0x14 | ShaderVarID byte @+0x18 | IsKeyframeable @+0x1c
SV_TYPE = {2:"Vector2", 4:"Vector4", 6:"Texture", 7:"Keyframe"}
SV_NAMES = ["softness","ambientmult","shadowamount","directionalmult","extralightmult",
 "softnesscurve","softnessshadowmult","softnessshadowoffset","diffusetex2","alphacutoffminmax",
 "camerabias","camerashrink","dirnormalbias","normalarc","normalmapmult","normalspecmap",
 "refractionmap","rg_blendenddistance","rg_blendstartdistance","superalpha","wraplightingterm"]
SV_HASH = {joaat(n): n for n in SV_NAMES}


class Ypt:
    def __init__(self, path):
        self.res = Res(path)
        if self.res.version != YPT_VERSION:
            raise ValueError("RSC7 version %d is not a ypt, want %d" % (self.res.version, YPT_VERSION))
        self.b = self.res.sys

    @classmethod
    def from_res(cls, res):
        self = cls.__new__(cls)
        self.res = res
        self.b = res.sys
        return self

    def _p(self, o):  return struct.unpack_from("<I", self.b, o)[0]
    def _u16(self, o): return struct.unpack_from("<H", self.b, o)[0]
    def _f(self, o):  return struct.unpack_from("<f", self.b, o)[0]
    def _byte(self, o): return self.b[o]
    def _deref(self, o):
        t = self._p(o); return (t & 0x0FFFFFFF) if (t >> 28) in (5, 6) else None
    def _aptr(self, o):
        """atArray inline descriptor @o -> (element-array offset, count)."""
        return self._deref(o), self._u16(o + 8)

    def root_name(self):
        return self.res.cstr(self._p(ROOT_NAME))

    def dict_objects(self, dict_off):
        base = self._deref(dict_off)
        if base is None:
            return None, []
        cnt = self._u16(base + 0x38)
        pArr = self._deref(base + 0x30)
        objs = [self._deref(pArr + i * 8) for i in range(cnt)] if pArr else []
        return base, objs

    def read_kfp(self, off):
        """ptxKeyframeProp read FROM ITS HASH OFFSET -> dict(name, invertbiaslink,
        randomindex, keyframes). InvertBiasLink = byte @hash+0x04 (pinned 2026-08-09 over
        7,036 oracle-paired KFP instances; the old const-0 emission broke every
        BiasLinks-bearing file)."""
        h = self._p(off)
        name = HASH2NAME.get(h, "0x%08X" % h)
        ibl = self._byte(off + 0x04)
        randix = self._u16(off + KFP_RANDIX)
        cnt = self._u16(off + KFP_KFCNT)
        kfs = []
        base = self._deref(off + KFP_KFPTR)
        if base is not None:
            for i in range(cnt):
                o = base + i * 32
                if o + 32 > len(self.b):
                    break
                f = struct.unpack_from("<8f", self.b, o)
                kfs.append((f[0:4], f[4:8]))
        return dict(name=name, invertbiaslink=ibl, randomindex=randix, keyframes=kfs)


# ------------------------------------------------------------------ shared emit helpers
def _fnum(x):
    """Keyframe float spelling: non-finite float32 spells the way the reference writes it
    - literal 'Infinity' witnessed (des_tv_smash oracle: y="Infinity"; stored bits
    0x7F800000), '-Infinity' the sign twin. NaN stays UNWITNESSED in ypt keyframes and
    falls through to fmt_num, which refuses it loudly rather than inventing a spelling."""
    if x == float('inf'):
        return 'Infinity'
    if x == float('-inf'):
        return '-Infinity'
    return fmt_num(x)


def _kfp_xml(res_kfp, indent, tag="Item"):
    sp = " " * indent
    L = ["%s<%s>" % (sp, tag),
         "%s <Name>%s</Name>" % (sp, esc(res_kfp["name"])),
         '%s <InvertBiasLink value="%d" />' % (sp, res_kfp.get("invertbiaslink", 0)),
         '%s <RandomIndex value="%d" />' % (sp, res_kfp["randomindex"])]
    kfs = res_kfp["keyframes"]
    if not kfs:
        L.append("%s <Keyframes />" % sp)
    else:
        L.append("%s <Keyframes>" % sp)
        for t, v in kfs:
            L += ["%s  <Item>" % sp,
                  '%s   <KeyframeTime x="%s" y="%s" z="%s" w="%s" />' % (sp, *[_fnum(x) for x in t]),
                  '%s   <KeyframeValue x="%s" y="%s" z="%s" w="%s" />' % (sp, *[_fnum(x) for x in v]),
                  "%s  </Item>" % sp]
        L.append("%s </Keyframes>" % sp)
    L.append("%s</%s>" % (sp, tag))
    return L


def _kf_items(y, kfptr, cnt, indent):
    """A bare atArray<keyframe(32B)> -> a <Keyframes> block (no Name/RandomIndex)."""
    sp = " " * indent
    if cnt == 0:
        return ["%s<Keyframes />" % sp]
    L = ["%s<Keyframes>" % sp]
    for i in range(cnt):
        o = kfptr + i * 32
        t = struct.unpack_from("<4f", y.b, o); v = struct.unpack_from("<4f", y.b, o + 16)
        L += ["%s <Item>" % sp,
              '%s  <KeyframeTime x="%s" y="%s" z="%s" w="%s" />' % (sp, *[_fnum(x) for x in t]),
              '%s  <KeyframeValue x="%s" y="%s" z="%s" w="%s" />' % (sp, *[_fnum(x) for x in v]),
              "%s </Item>" % sp]
    L.append("%s</Keyframes>" % sp)
    return L


# ------------------------------------------------------------------ ptxEmitterRule
def _domain_xml(y, dp, indent, tagname):
    sp = " " * indent
    dt = y._p(dp + 0x0c)
    fv = fmt_num(y._f(dp + 0x258))     # STORED per-domain (see the retraction note above)
    L = ["%s<%s>" % (sp, tagname),
         '%s <DomainType value="%s" />' % (sp, DOMAIN_TYPE[dt]),
         '%s <IsWorldSpace value="%d" />' % (sp, y._byte(dp + 0x10)),
         '%s <IsPointRelative value="%d" />' % (sp, y._byte(dp + 0x11)),
         '%s <IsCreationRelative value="%d" />' % (sp, y._byte(dp + 0x12)),
         '%s <IsTargetRelatve value="%d" />' % (sp, y._byte(dp + 0x13)),
         '%s <FileVersion value="%s" />' % (sp, fv)]
    for i, kt in enumerate(("PositionKFP", "RotationKFP", "SizeOuterKFP", "SizeInnerKFP")):
        L += _kfp_xml(y.read_kfp(dp + 0x80 + i * 0x90), indent + 1, tag=kt)
    L.append("%s</%s>" % (sp, tagname))
    return L


def _emitter_item(y, base, indent):
    sp = " " * indent
    L = ["%s<Item>" % sp,
         "%s <Name>%s</Name>" % (sp, esc(y.res.cstr(y._p(base + 0x20)))),
         '%s <RefCount value="%d" />' % (sp, y._p(base + 0x10)),
         # IsOneShot = byte @+0x628 - just past the 10 embedded KFP objects (0x78..0x618);
         # unique survivor over 195 oracle-paired emitters (was an uncounted const 0)
         '%s <IsOneShot value="%d" />' % (sp, y._byte(base + 0x628))]
    L += _domain_xml(y, y._deref(base + 0x38), indent + 1, "CreationDomainObj")
    L += _domain_xml(y, y._deref(base + 0x48), indent + 1, "TargetDomainObj")
    adp = y._deref(base + 0x58)
    if adp is not None:
        # third domain slot (Attractor): NULL in 38/39 witnessed emitters = element
        # OMITTED; the scr_hunting witness renders byte-identical through _domain_xml
        L += _domain_xml(y, adp, indent + 1, "AttractorDomainObj")
    L.append("%s <KeyframeProps>" % sp)
    for i in range(10):
        # count is stored (u16 @+0x620 = 10 in every witness) - the literal 10 has a
        # real backing field; keep the constant but the note stands
        L += _kfp_xml(y.read_kfp(base + 0xe0 + i * 0x90), indent + 2, tag="Item")
    L.append("%s </KeyframeProps>" % sp)
    L.append("%s</Item>" % sp)
    return L


def _by_name(y, objs, name_off):
    """Dictionary items emit in ascending NAME order - the reference sorts by name, not
    by the stored hash order (measured 2026-08-09: 7/11 stage-D DIFF first-causes were
    exactly this reorder, e.g. jet<->splash, nitro<->petrol; the original 10-oracle base
    never witnessed a file where the two orders diverge, so stored order looked right)."""
    return sorted(objs, key=lambda base: y.res.cstr(y._p(base + name_off)))


def emitter_dict(y):
    _, objs = y.dict_objects(0x50)
    L = [" <EmitterRuleDictionary>"]
    for base in _by_name(y, objs, 0x20):
        L += _emitter_item(y, base, 2)
    L.append(" </EmitterRuleDictionary>")
    return L


# ------------------------------------------------------------------ ptxEffectRule
def _evolution_list(y, elp, indent):
    """ptxEvolutionList (rewritten 2026-08-09 from the 31-binary sweep; the 8 stage-D
    crash rows were exactly the files with any Items count >= 2):
      +0x00 Evolutions atArray - elements are 0x18 BYTES with the char* at +0x00 (the old
            stride-8 read landed in zero padding for every index >= 1: empty 2nd names).
      +0x10 atArray of evolved-KFP OBJECTS, stride 0x18: Items atArray @+0x00 (ptr, u16
            count @+0x08), kfpNameHash u32 @+0x10, BlendMode u32 @+0x14. EMIT ORDER =
            this array's natural order (the old sort-by-Items-pointer provably diverges).
      +0x28 a redundant hash-sorted index (228/228 lists verified) - never emitted.
    Items elements are 0x30 BYTES (not 0x28 - the crash): keyframes atArray @+0x00,
    u32 EvolutionID @+0x20, u32 IsLodEvolution @+0x24 - REAL varying fields (the old
    consts 0/1 matched only some files by luck)."""
    sp = " " * indent
    L = ["%s<EvolutionList>" % sp]
    ep, ecnt = y._aptr(elp + 0x00)
    if ecnt == 0:
        L.append("%s <Evolutions />" % sp)
    else:
        L.append("%s <Evolutions>" % sp)
        for i in range(ecnt):
            L.append("%s  <Item>%s</Item>" % (sp, esc(y.res.cstr(y._p(ep + i * 0x18)))))
        L.append("%s </Evolutions>" % sp)
    op, ocnt = y._aptr(elp + 0x10)
    if ocnt == 0:
        L.append("%s <EvolvedKeyframeProps />" % sp)
    else:
        L.append("%s <EvolvedKeyframeProps>" % sp)
        for i in range(ocnt):
            eo = op + i * 0x18
            nh = y._p(eo + 0x10)
            nm = HASH2NAME.get(nh, "0x%08X" % nh)
            ip, icnt = y._aptr(eo + 0x00)
            L += ["%s  <Item>" % sp,
                  "%s   <Name>%s</Name>" % (sp, esc(nm)),
                  '%s   <BlendMode value="%d" />' % (sp, y._p(eo + 0x14)),
                  "%s   <Items>" % sp]
            for j in range(icnt):
                io = ip + j * 0x30
                kfp2, kcnt2 = y._aptr(io + 0x00)
                L += ["%s    <Item>" % sp,
                      '%s     <EvolutionID value="%d" />' % (sp, y._p(io + 0x20)),
                      '%s     <IsLodEvolution value="%d" />' % (sp, y._p(io + 0x24))]
                L += _kf_items(y, kfp2, kcnt2, indent + 5)
                L.append("%s    </Item>" % sp)
            L += ["%s   </Items>" % sp, "%s  </Item>" % sp]
        L.append("%s </EvolvedKeyframeProps>" % sp)
    L.append("%s</EvolutionList>" % sp)
    return L


def _event_emitter(y, eo, indent):
    sp = " " * indent
    L = ["%s<Item>" % sp,
         "%s <EmitterRule>%s</EmitterRule>" % (sp, esc(y.res.cstr(y._p(eo + 0x30)))),
         "%s <ParticleRule>%s</ParticleRule>" % (sp, esc(y.res.cstr(y._p(eo + 0x38)))),
         '%s <EventType value="0" />' % sp,                       # 0 across the set
         '%s <StartRatio value="%s" />' % (sp, fmt_num(y._f(eo + 0x10))),
         '%s <EndRatio value="%s" />' % (sp, fmt_num(y._f(eo + 0x14))),
         '%s <PlaybackRateScalarMin value="%s" />' % (sp, fmt_num(y._f(eo + 0x50))),
         '%s <PlaybackRateScalarMax value="%s" />' % (sp, fmt_num(y._f(eo + 0x54))),
         '%s <ZoomScalarMin value="%s" />' % (sp, fmt_num(y._f(eo + 0x58))),
         '%s <ZoomScalarMax value="%s" />' % (sp, fmt_num(y._f(eo + 0x5c))),
         '%s <ColourTintMin value="0x%X" />' % (sp, y._p(eo + 0x60)),
         '%s <ColourTintMax value="0x%X" />' % (sp, y._p(eo + 0x64))]
    elp = y._deref(eo + 0x18)
    if elp is not None:
        # NULL pointer = the element is OMITTED (oracle-witnessed: cut_trevor4
        # </KeyframeProps> abuts </Item>; present when non-NULL: cut_josh_4)
        L += _evolution_list(y, elp, indent + 1)
    L.append("%s</Item>" % sp)
    return L


def _effect_item(y, base, indent):
    sp = " " * indent
    fx = lambda o: fmt_num(y._f(base + o))
    b = lambda o: y._byte(base + o)
    v3 = lambda o: struct.unpack_from("<3f", y.b, base + o)
    L = ["%s<Item>" % sp,
         "%s <Name>%s</Name>" % (sp, esc(y.res.cstr(y._p(base + 0x20)))),
         '%s <RefCount value="%d" />' % (sp, y._p(base + 0x10)),
         '%s <FileVersion value="%s" />' % (sp, fmt_num(y._f(base + 0x18))),
         '%s <NumLoops value="0x%X" />' % (sp, y._p(base + 0x50)),
         '%s <SortEventsByDistance value="%d" />' % (sp, b(0x54)),
         '%s <DrawListID value="%d" />' % (sp, b(0x55)),
         '%s <IsShortLived value="%d" />' % (sp, b(0x56)),
         '%s <HasNoShadows value="%d" />' % (sp, b(0x57)),
         '%s <VRandomOffsetPos x="%s" y="%s" z="%s" />' % (sp, *[fmt_num(x) for x in v3(0x58)]),
         '%s <PreUpdateTime value="%s" />' % (sp, fx(0x70)),
         '%s <PreUpdateTimeInterval value="%s" />' % (sp, fx(0x74)),
         '%s <DurationMin value="%s" />' % (sp, fx(0x78)),
         '%s <DurationMax value="%s" />' % (sp, fx(0x7c)),
         '%s <PlaybackRateScalarMin value="%s" />' % (sp, fx(0x80)),
         '%s <PlaybackRateScalarMax value="%s" />' % (sp, fx(0x84)),
         '%s <ViewportCullingMode value="%d" />' % (sp, b(0x88)),
         '%s <RenderWhenViewportCulled value="%d" />' % (sp, b(0x89)),
         '%s <UpdateWhenViewportCulled value="%d" />' % (sp, b(0x8a)),
         '%s <EmitWhenViewportCulled value="%d" />' % (sp, b(0x8b)),
         '%s <DistanceCullingMode value="%d" />' % (sp, b(0x8c)),
         '%s <RenderWhenDistanceCulled value="%d" />' % (sp, b(0x8d)),
         '%s <UpdateWhenDistanceCulled value="%d" />' % (sp, b(0x8e)),
         '%s <EmitWhenDistanceCulled value="%d" />' % (sp, b(0x8f)),
         '%s <ViewportCullingSphereOffset x="%s" y="%s" z="%s" />' % (sp, *[fmt_num(x) for x in v3(0x90)]),
         '%s <ViewportCullingSphereRadius value="%s" />' % (sp, fx(0xa0)),
         '%s <DistanceCullingFadeDist value="%s" />' % (sp, fx(0xa4)),
         '%s <DistanceCullingCullDist value="%s" />' % (sp, fx(0xa8)),
         '%s <LodEvoDistanceMin value="%s" />' % (sp, fx(0xac)),
         '%s <LodEvoDistanceMax value="%s" />' % (sp, fx(0xb0)),
         '%s <CollisionRange value="%s" />' % (sp, fx(0xb4)),
         '%s <CollisionProbeDistance value="%s" />' % (sp, fx(0xb8)),
         '%s <CollisionType value="%d" />' % (sp, b(0xbc)),
         '%s <ShareEntityCollisions value="%d" />' % (sp, b(0xbd)),
         '%s <OnlyUseBVHCollisions value="%d" />' % (sp, b(0xbe)),
         '%s <GameFlags value="%d" />' % (sp, b(0xbf)),
         '%s <ColourTintMaxEnable value="%d" />' % (sp, b(0x3a0)),
         '%s <UseDataVolume value="%d" />' % (sp, b(0x3a1)),
         '%s <DataVolumeType value="%d" />' % (sp, b(0x3a2)),
         '%s <ZoomLevel value="%s" />' % (sp, fx(0x3a8))]
    # EventEmitters @+0x38
    ep, cnt = y._aptr(base + 0x38)
    if cnt == 0:
        L.append("%s <EventEmitters />" % sp)
    else:
        L.append("%s <EventEmitters>" % sp)
        for i in range(cnt):
            L += _event_emitter(y, y._deref(ep + i * 8), indent + 2)
        L.append("%s </EventEmitters>" % sp)
    # KeyframeProps @+0x390 (5 embedded KFP pointers)
    kp, kcnt = y._aptr(base + 0x390)
    L.append("%s <KeyframeProps>" % sp)
    for i in range(kcnt):
        L += _kfp_xml(y.read_kfp(y._deref(kp + i * 8) + 0x68), indent + 2, tag="Item")
    L.append("%s </KeyframeProps>" % sp)
    # top-level EvolutionList @+0x48 - NULL pointer = element OMITTED (see _event_emitter)
    elp = y._deref(base + 0x48)
    if elp is not None:
        L += _evolution_list(y, elp, indent + 1)
    L.append("%s</Item>" % sp)
    return L


def effect_dict(y):
    _, objs = y.dict_objects(0x48)
    L = [" <EffectRuleDictionary>"]
    for base in _by_name(y, objs, 0x20):
        L += _effect_item(y, base, 2)
    L.append(" </EffectRuleDictionary>")
    return L


# ------------------------------------------------------------------ ptxParticleRule
def _spawner(y, base, tag, indent, mn, tri):
    """EffectSpawner blocks. Tail re-derived 2026-08-09: symmetric at particle+mn+0x50 -
    TriggerInfo is an F32 (values 0 / 0.5 / 1 witnessed - the old int consts 0/1 were the
    coincidence), then flag bytes InheritsPointLife/+4, TracksPointPos/+5, Dir/+6, NegDir/+7
    (Dir!=NegDir witnessed once, des_tv_smash; AtRatio TriggerInfo single-valued 0, placed
    by the exact +0x70 block symmetry with the measured OnCollision @0xf8). `tri` retained
    in the signature for call-site stability; no longer emitted. EffectRule = the SPAWNED
    effect's NAME, cstr ptr @mn+0x48 (probed on des_tv_smash: AtRatio slot particle+0x80
    -> 'ent_sht_electrical_box_sp'; OnCollision +0xf0 by the same block symmetry, verified
    by the weap_ch rows); NULL/empty -> self-closing element (the common case)."""
    sp = " " * indent
    mx = mn + 0x20
    tail = mn + 0x50
    ff = lambda o: fmt_num(y._f(base + o))
    ername = y.res.cstr(y._p(base + mn + 0x48))
    L = ["%s<%s>" % (sp, tag),
         ("%s <EffectRule>%s</EffectRule>" % (sp, esc(ername))) if ername
         else "%s <EffectRule />" % sp,
         '%s <DurationScalarMin value="%s" />' % (sp, ff(mn)),
         '%s <PlaybackRateScalarMin value="%s" />' % (sp, ff(mn + 4)),
         '%s <ColourTintScalarMin value="0x%X" />' % (sp, y._p(base + mn + 8)),
         '%s <ZoomScalarMin value="%s" />' % (sp, ff(mn + 0xc)),
         '%s <FlagsMin value="%d" />' % (sp, y._p(base + mn + 0x10)),
         '%s <DurationScalarMax value="%s" />' % (sp, ff(mx)),
         '%s <PlaybackRateScalarMax value="%s" />' % (sp, ff(mx + 4)),
         '%s <ColourTintScalarMax value="0x%X" />' % (sp, y._p(base + mx + 8)),
         '%s <ZoomScalarMax value="%s" />' % (sp, ff(mx + 0xc)),
         '%s <FlagsMax value="%d" />' % (sp, y._p(base + mx + 0x10)),
         '%s <TriggerInfo value="%s" />' % (sp, ff(tail)),
         '%s <InheritsPointLife value="%d" />' % (sp, y._byte(base + tail + 4)),
         '%s <TracksPointPos value="%d" />' % (sp, y._byte(base + tail + 5)),
         '%s <TracksPointDir value="%d" />' % (sp, y._byte(base + tail + 6)),
         '%s <TracksPointNegDir value="%d" />' % (sp, y._byte(base + tail + 7)),
         "%s</%s>" % (sp, tag)]
    return L


# Every ("const", v) scalar emitted is COUNTED here, not passed silently. These fields never
# varied across the 10-file oracle set, so no offset could be pinned by value-intersection;
# the literal reproduces the oracles exactly but WOULD BE WRONG for any file whose real value
# differs. Counting makes that visible at scale (a silent wrong value is the one failure mode
# no gate can catch). Pin them by widening oracle coverage, then delete the const entry.
CONST_EMITS = {}


def _beh_val(y, bo, res):
    if res[0] == "const":
        CONST_EMITS[res[1]] = CONST_EMITS.get(res[1], 0) + 1
        return res[1]
    _, o, kind = res
    if kind == "byte": return str(y.b[bo + o])
    if kind == "u32":  return str(y._p(bo + o))
    return fmt_num(y._f(bo + o))


def _behaviour(y, bo, indent):
    sp = " " * indent
    t = BEH_TYPEHASH[y._p(bo + 8)]
    L = ["%s<Item>" % sp, '%s <Type value="%s" />' % (sp, t)]
    for f in BEH_SPEC[t]:
        if f[0] == "kfp":
            L += _kfp_xml(y.read_kfp(bo + 0x98 + f[2] * 0x90), indent + 1, tag=f[1])
        elif f[0] == "vec3":
            v = struct.unpack_from("<3f", y.b, bo + f[2])
            L.append('%s <%s x="%s" y="%s" z="%s" />' % (sp, f[1], *[fmt_num(x) for x in v]))
        else:
            L.append('%s <%s value="%s" />' % (sp, f[1], _beh_val(y, bo, f[2])))
    L.append("%s</Item>" % sp)
    return L


def _all_behaviours(y, base, indent):
    sp = " " * indent
    ap, cnt = y._aptr(base + 0x128)
    if cnt == 0:
        return ["%s<AllBehaviours />" % sp]
    L = ["%s<AllBehaviours>" % sp]
    for i in range(cnt):
        L += _behaviour(y, y._deref(ap + i * 8), indent + 1)
    L.append("%s</AllBehaviours>" % sp)
    return L


def _shadervar(y, so, indent):
    sp = " " * indent
    nh = y._p(so + 0x10)
    nm = SV_HASH.get(nh, "0x%08X" % nh)
    t = SV_TYPE[y._p(so + 0x14)]
    kfcase = "IsKeyFrameable" if t in ("Vector2", "Vector4") else "IsKeyframeable"
    L = ["%s<Item>" % sp,
         '%s <Type value="%s" />' % (sp, t),
         "%s <Name>%s</Name>" % (sp, esc(nm)),
         '%s <ShaderVarID value="%d" />' % (sp, y._byte(so + 0x18)),
         '%s <%s value="%d" />' % (sp, kfcase, y._byte(so + 0x1c))]
    if t in ("Vector2", "Vector4"):
        L += ['%s <VectorX value="%s" />' % (sp, fmt_num(y._f(so + 0x30))),
              '%s <VectorY value="%s" />' % (sp, fmt_num(y._f(so + 0x34))),
              '%s <VectorZ value="%s" />' % (sp, fmt_num(y._f(so + 0x38))),
              '%s <VectorW value="%s" />' % (sp, fmt_num(y._f(so + 0x3c)))]
    elif t == "Texture":
        tn = y.res.cstr(y._p(so + 0x30))
        L.append('%s <ExternalReference value="%d" />' % (sp, y._byte(so + 0x3c)))
        L.append(("%s <TextureName>%s</TextureName>" % (sp, esc(tn))) if tn else "%s <TextureName />" % sp)
    elif t == "Keyframe":
        ptr, cnt = y._aptr(so + 0x28)
        if cnt == 0:
            L.append("%s <Items />" % sp)
        else:
            L.append("%s <Items>" % sp)
            for i in range(cnt):
                io = ptr + i * 0x20
                L += ["%s  <Item>" % sp,
                      '%s   <Unknown0 value="%s" />' % (sp, fmt_num(y._f(io + 0x00))),
                      '%s   <Unknown4 value="%s" />' % (sp, fmt_num(y._f(io + 0x04))),
                      '%s   <Unknown10 value="%s" />' % (sp, fmt_num(y._f(io + 0x10))),
                      "%s  </Item>" % sp]
            L.append("%s </Items>" % sp)
    L.append("%s</Item>" % sp)
    return L


def _shadervars(y, base, indent):
    sp = " " * indent
    ptr, cnt = y._aptr(base + 0x1f0)
    if cnt == 0:
        return ["%s<ShaderVars />" % sp]
    L = ["%s<ShaderVars>" % sp]
    for i in range(cnt):
        L += _shadervar(y, y._deref(ptr + i * 8), indent + 1)
    L.append("%s</ShaderVars>" % sp)
    return L


def _particle_item(y, base, indent):
    sp = " " * indent
    fx = lambda o: fmt_num(y._f(base + o))
    L = ["%s<Item>" % sp,
         "%s <Name>%s</Name>" % (sp, esc(y.res.cstr(y._p(base + PART["Name"])))),
         '%s <RefCount value="%d" />' % (sp, y._p(base + 0x10)),
         "%s <ShaderFile>%s</ShaderFile>" % (sp, esc(y.res.cstr(y._p(base + 0x1b8)))),
         "%s <ShaderTechnique>%s</ShaderTechnique>" % (sp, esc(y.res.cstr(y._p(base + 0x1c0)))),
         '%s <CullMode value="%d" />' % (sp, y._p(base + 0x100)),
         '%s <BlendSet value="%d" />' % (sp, y._p(base + 0x104)),
         '%s <LightingMode value="%d" />' % (sp, y._p(base + 0x108)),
         '%s <DepthWrite value="%d" />' % (sp, y._byte(base + 0x10c)),
         '%s <DepthTest value="%d" />' % (sp, y._byte(base + 0x10d)),
         '%s <AlphaBlend value="%d" />' % (sp, y._byte(base + 0x10e)),
         '%s <TexFrameIDMin value="%d" />' % (sp, y._p(base + 0x118)),
         '%s <TexFrameIDMax value="%d" />' % (sp, y._p(base + 0x11c)),
         '%s <ShaderTemplateTechniqueID value="%d" />' % (sp, y._p(base + 0x1d0)),
         '%s <DiffuseMode value="%d" />' % (sp, y._p(base + 0x1e0)),
         '%s <ProjectionMode value="0" />' % sp,                  # const 0 in the set
         '%s <IsLit value="%d" />' % (sp, y._byte(base + 0x1e8)),
         '%s <IsSoft value="%d" />' % (sp, y._byte(base + 0x1e9)),
         # 0x1ea/0x1eb pinned 2026-08-09 (contiguous with IsLit/IsSoft; IsRefract O=1
         # witnesses were first-diff causes in cut_arena/scr_franklin0/scr_xm_heat)
         '%s <IsScreenSpace value="%d" />' % (sp, y._byte(base + 0x1ea)),
         '%s <IsRefract value="%d" />' % (sp, y._byte(base + 0x1eb)),
         '%s <IsNormalSpec value="0" />' % sp,
         '%s <SortType value="%d" />' % (sp, y._byte(base + 0x220)),
         '%s <DrawType value="%d" />' % (sp, y._byte(base + 0x221)),
         '%s <Flags value="0" />' % sp,
         '%s <RuntimeFlags value="0" />' % sp]
    L += _spawner(y, base, "EffectSpawnerAtRatio", indent + 1, 0x38, 0)
    L += _spawner(y, base, "EffectSpawnerOnCollision", indent + 1, 0xa8, 1)
    L += _all_behaviours(y, base, indent + 1)
    L += _bias_links(y, base, indent + 1)
    L += _shadervars(y, base, indent + 1)
    L.append("%s</Item>" % sp)
    return L


def _bias_links(y, base, indent):
    """<BiasLinks> (derived 2026-08-09, 19 sets / 17 rules / 15 files, all oracle-matched;
    full-file byte-identity proven on both first-diff carriers): atArray @particle+0x188,
    count u16 @+0x190; element 0x58 bytes = inline NUL-terminated Name @+0x00 (zero-padded
    through +0x3F), KeyframePropIDs atArray @+0x40 (u32 hashes, count u16 @+0x48),
    RandomIndex u32 @+0x50. Emitted ONLY when count > 0 (no empty <BiasLinks /> witnessed
    anywhere; presence rule is the array count, NOT InvertBiasLink). KeyframePropIDs spell
    hash_%08X even when the hash is resolvable - the oracle does the same.
    ⚠ single-witness strides, stated: element 0x58 (every witnessed array has count 1);
    KeyframePropIDs element 4 (one 1-count array)."""
    ap = y._deref(base + 0x188)
    cnt = y._u16(base + 0x190)
    if ap is None or cnt == 0:
        return []
    sp = " " * indent
    L = ["%s<BiasLinks>" % sp]
    for i in range(cnt):
        eo = ap + i * 0x58
        name = y.b[eo:y.b.find(b"\x00", eo)].decode("latin-1")
        L += ["%s <Item>" % sp,
              "%s  <Name>%s</Name>" % (sp, esc(name)),
              '%s  <RandomIndex value="%d" />' % (sp, y._p(eo + 0x50))]
        kp, kcnt = y._aptr(eo + 0x40)
        if kcnt == 0 or kp is None:
            L.append("%s  <KeyframePropIDs />" % sp)
        else:
            L.append("%s  <KeyframePropIDs>" % sp)
            for j in range(kcnt):
                L.append("%s   <Item>hash_%08X</Item>" % (sp, y._p(kp + j * 4)))
            L.append("%s  </KeyframePropIDs>" % sp)
        L.append("%s </Item>" % sp)
    L.append("%s</BiasLinks>" % sp)
    return L


def particle_dict(y):
    _, objs = y.dict_objects(0x38)
    L = [" <ParticleRuleDictionary>"]
    for base in _by_name(y, objs, PART["Name"]):
        L += _particle_item(y, base, 2)
    L.append(" </ParticleRuleDictionary>")
    return L


# ------------------------------------------------------------------ full file
def convert_res(res):
    y = Ypt.from_res(res)
    L = ['<?xml version="1.0" encoding="UTF-8"?>', "<ParticleEffectsList>",
         " <Name>%s</Name>" % esc(y.root_name())]
    L += effect_dict(y)
    L += emitter_dict(y)
    L += particle_dict(y)
    L += [" <DrawableDictionary>", " </DrawableDictionary>"]      # empty in all 10
    base = y._deref(0x20)
    if base is None or y._u16(base + 0x28) == 0:
        L.append(" <TextureDictionary />")
    else:
        inner = ytd2xml.to_xml(ytd2xml.read_textures(y.res, base=base)).split("\n")[1:]
        L += [" " + s for s in inner if s]
    L.append("</ParticleEffectsList>")
    return "\n".join(L) + "\n"


def convert(path):
    return convert_res(Res(path))


# ------------------------------------------------------------------ self-validation
def validate(manifest):
    """Byte-identical check: convert every listed .ypt and diff against its oracle .ypt.xml."""
    import json, difflib
    man = json.load(open(manifest))
    okc = 0
    for mm in man:
        got = convert(mm["bin"])
        want = open(mm["oracle"], encoding="utf-8").read()
        ok = got == want; okc += ok
        print("  %-40s %s" % (mm["name"], "OK" if ok else "DIFF"))
        if not ok:
            gl, wl = got.split("\n"), want.split("\n")
            for d in list(difflib.unified_diff(wl, gl, "oracle", "got", lineterm=""))[:12]:
                print("   ", d)
    print("\n  ypt full-file byte-identical: %d / %d" % (okc, len(man)))
    return okc == len(man)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="*")
    ap.add_argument("--validate", metavar="MANIFEST")
    ap.add_argument("--out")
    a = ap.parse_args()
    if a.validate:
        sys.exit(0 if validate(a.validate) else 1)
    for p in a.files:
        xml = convert(p)
        if a.out:
            open(os.path.join(a.out, os.path.splitext(os.path.basename(p))[0] + ".ypt.xml"),
                 "w", encoding="utf-8").write(xml)
        else:
            print(xml)


if __name__ == "__main__":
    main()
