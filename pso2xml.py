#!/usr/bin/env python3
"""pso2xml.py - GENERIC RAGE PSO (PSIN) -> reference-identical XML.

Clean-room: derived purely from oracle XML + game binaries + QUARRY's own code.
The reader is driven by the FILE'S OWN embedded schema (PSCH), so one codec serves
every PSO root struct (CPackFileMetaData / .cut / PSO-root .ymt). It generalises the
region-specific pso_manifest.py; it hardcodes NO schema.

CONTAINER (all integers BIG-ENDIAN):
  file = concatenation of sections {u32 fourcc, u32 sizeInclHeader}. First section is
  always 'PSIN' at offset 0.
    PSIN  data. First 8 payload bytes are 0x70 padding; then the data blocks.
    PMAP  block map: {u32 rootBlockIdx(1-based), u16 nBlocks, u16 pad(0x7070)} then
          nBlocks x {u32 blockId, u32 fileOffset, u32 zero, u32 byteSize}.
          fileOffset is relative to the PSIN section start (== file start).
    PSCH  schema: {u32 nDefs} then nDefs x {u32 hash, u32 secRelOffset}. A def is EITHER
          a struct or an enum (told apart by reference context, never guessed):
            struct def @ (secRelOffset-8): {u32 count, u32 instSize, u32 zero} then
              count x {u32 nameHash, u8 type, u8 sub, u16 offset, u32 extra}.
            enum   def @ (secRelOffset-8): {u32 header} then N x {u32 memberHash, i32 value};
              N = header & 0xFFFF (high half constant 0x0100 in the corpus, unmapped).
    STRF  plaintext NUL-terminated string pool (rare in ymf).
    STRE  ENCRYPTED string pool - NOT decrypted here (see notes). Hash-string values are
          resolved via the caller-supplied joaat(lower) name dict instead, exactly as the reference exporter
          resolves them from its global filename index; a shipped game data-file token
          index (game_pso_names.json, see token_names) is the fallback where the filename
          universe cannot reverse a hash; still unknown -> hash_XXXXXXXX.
    PSIG  16-byte signature (semantics unmapped, not needed for XML).
    CHKS  {u32 totalSize, u32 checksum, u32 0x79707070} (unmapped, not needed).

METAPOINTER (u32): low 12 bits = 1-based block index, high 20 bits = byte offset in block.
ARRAY storage (type 0x0d) is TWO shapes, told apart by the field's own .sub:
  .sub 0x00  POINTER array: 16-B descriptor at the field offset {u32 metaptr, u32 pad,
             u16 count, u16 cap, u32 pad}; element data in the pointed block. count from the
             descriptor. (Every CPackFileMetaData/.ymf array; .cut pointer lists.)
  .sub 0x01/0x02/0x04/0x81  INLINE array: element data stored inline AT the field offset in
             THIS struct; COUNT = extra>>16 (a fixed/capacity array, NOT in any descriptor);
             the 16-bit offset is used RAW (no high-bit reconstruction - measured against
             junctions AutoJunctionAdjustments @0x99b0). (junctions Entries/Entrances/
             PhaseTimings/TrafficLightLocations/vJunctionNodePositions/AutoJunctionAdjustments;
             .cut concatDataList/iCutsceneFlags.) The .sub value (01 vs 02 vs 81) carries
             storage nuance we do not need: all render identically given (count, element).
ARRAY ELEMENT (refTypeIdx = extra & 0xFFFF -> a sibling schema entry, name 0x100) drives XML:
  struct (0x0c)     -> <name itemType="ElemStruct"> <Item>..</Item> .. </name>  (stride = size)
  struct-ptr (0x0c/sub03, pointer lane only) -> <Item type="PolyStruct"> per pointed block id
  vec3 (0x09/0x14)  -> one "x, y, z" per line (fmt_num, ", "-joined), indented; no <Item>
  hash-string(0x0b) -> <Item>name</Item> per element (no itemType)
  scalar(0x00/02/03/05/06/07) -> space-joined in the tag body, one line ("268452352 0 0 0"; "3")

MEMBER TYPE CODES (schema entry .type), with the reference exporter XML rendering:
  0x00 bool            <X value="true|false" />         (scenario EnabledByDefault; cut IsChild)
  0x02 u8   (1 byte)   <X value="N" />                  (cut attributeList UserData1/2)
  0x03 i16  (2 bytes)  <X value="N" />                  (firingpatterns NumberOfBursts = -1)
  0x05 int32 (4B)      <X value="N" /> signed           (cut iObjectId/iRangeStart)
  0x06 int32 (4B)      sub 0x00 <X value="N" /> SIGNED (cut AnimStreamingBase = -175977911);
                       sub 0x01 <X value="0xNNNNNNNN" /> packed colour (cut fadeInColor)
  0x07 float32 (4B)    <X value="fmt_num" />            (firingpatterns TimeBetween... = 2.5)
  0x09 vec3            <X x=".." y=".." z=".." /> 3 BE floats in a 16-B slot; 4th word = pad
  0x0b string          see STRING SUBTYPES
  0x0c struct          tagged by the FIELD name (not the struct's own name):
                       sub 0x00 inline struct at field offset (extra = struct hash);
                       sub 0x03 POINTER to a struct (null -> empty; block id gives the type);
                       sub 0x04 / extra 0 -> empty <X /> (cut cutfAttributes)
  0x0d array           see ARRAY STORAGE / ARRAY ELEMENT above
  0x0e enum            extra = enum def hash; renders member NAME as element text
  0x0f flags           extra low16 = refTypeIdx of enum element-desc; 0 -> empty, else " "-joined
  0x14 vec3            same XML as 0x09 (cut vLocation) - shares one renderer
  0x15 float4/vec4     <X x y z w /> (scenario AABB min/max)

STRING SUBTYPES (type 0x0b .sub):
  0x00 inline fixed char[len], len = extra>>16, NUL-terminated       (cFaceDir, targetAsset, HDTxd)
  0x03 POINTER to a NUL-terminated inline string in a block          (cut cName "UNDER_INT_4.WAV")
  0x07 / 0x08 joaat(lower) hash -> name via dict, else hash_%08X     (imapName, StreamingName, ..)
"""
import struct

M32 = 0xFFFFFFFF
ELEM = 0x00000100          # synthetic element-descriptor name; never a real field


# ---------------------------------------------------------------- hashing
def joaat(s, lower=True):
    h = 0
    for ch in (s.lower() if lower else s):
        h = (h + ord(ch)) & M32
        h = (h + (h << 10)) & M32
        h ^= h >> 6
    h = (h + (h << 3)) & M32
    h ^= h >> 11
    return (h + (h << 15)) & M32


def joaat_case(s):
    return joaat(s, lower=False)


# ---------------------------------------------------------------- schema-name dictionary
# struct / field / enum-member names are CASE-SENSITIVE joaat, hashed as written. Every
# name below verified against its stored hash in a real binary before use (clean-room:
# the string is the case-sensitive joaat preimage of the descriptor hash).
SCHEMA_NAMES = (
    # carcols enum members (2026-08-08): all 27 oracle spellings joaat_case-verified against
    # the file's OWN enum-def member hashes (metallicID 0x157C285E / audioColor 0x2070C98C /
    # audioPrefix 0x7B21D8F4) - the §6y both-halves rule; 'none' is the metallic -1 member.
    "EVehicleModelColorMetallic_normal", "EVehicleModelColorMetallic_1",
    "EVehicleModelColorMetallic_2", "EVehicleModelColorMetallic_3",
    "EVehicleModelColorMetallic_4", "EVehicleModelColorMetallic_5",
    "EVehicleModelColorMetallic_6", "EVehicleModelColorMetallic_7",
    "EVehicleModelColorMetallic_8", "EVehicleModelColorMetallic_9", "none",
    "POLICE_SCANNER_COLOUR_beige", "POLICE_SCANNER_COLOUR_black",
    "POLICE_SCANNER_COLOUR_blue", "POLICE_SCANNER_COLOUR_brown",
    "POLICE_SCANNER_COLOUR_graphite", "POLICE_SCANNER_COLOUR_green",
    "POLICE_SCANNER_COLOUR_grey", "POLICE_SCANNER_COLOUR_orange",
    "POLICE_SCANNER_COLOUR_pink", "POLICE_SCANNER_COLOUR_red",
    "POLICE_SCANNER_COLOUR_silver", "POLICE_SCANNER_COLOUR_white",
    "POLICE_SCANNER_COLOUR_yellow", "POLICE_SCANNER_PREFIX_bright",
    "POLICE_SCANNER_PREFIX_dark", "POLICE_SCANNER_PREFIX_light",
    # carcols member name (2026-08-08): joaat 1B60404D, oracle spells <id value=".." />
    "id",
    # CPackFileMetaData tree
    "CPackFileMetaData", "MapDataGroups", "CMapDataGroup", "HDTxdBindingArray",
    "CHDTxdAssetBinding", "imapDependencies", "CImapDependency", "imapDependencies_2",
    "CImapDependencies", "itypDependencies_2", "CItypDependencies", "Interiors",
    "CInteriorBoundsFiles",
    "assetType", "targetAsset", "HDTxd", "imapName", "manifestFlags", "itypDepArray",
    "itypName", "packFileName", "Name", "Bounds",
    # CMapDataGroup extra fields
    "Flags", "WeatherTypes", "HoursOnOff",
    # eAssetType enum members (verified as enum-table member hashes)
    "AT_TXD", "AT_DRB", "AT_DWD", "AT_FRG", "AT_DWD_PHYS", "AT_ASSETLESS",
    # manifestFlags / CMapDataGroup Flags members
    "INTERIOR_DATA", "TIME_DEPENDENT", "WEATHER_DEPENDENT",
    # firingpatterns (bonus)
    "CFiringPatternInfoManager", "Infos", "CFiringPatternInfo",
    "NumberOfBurstsMin", "NumberOfBurstsMax", "NumberOfShotsPerBurstMin",
    "NumberOfShotsPerBurstMax", "TimeBetweenShotsMin", "TimeBetweenShotsMax",
    "TimeBetweenShotsAbsoluteMin", "TimeBetweenBurstsMin", "TimeBetweenBurstsMax",
    "TimeBetweenBurstsAbsoluteMin", "TimeBeforeFiringMin", "TimeBeforeFiringMax",
    # CJunctionTemplateArray (junctions.pso) tree
    "CJunctionTemplateArray", "Entries", "CJunctionTemplate", "AutoJunctionAdjustments",
    "CAutoJunctionAdjustment", "CJunctionTemplate__CEntrance", "CJunctionTemplate__CPhaseTiming",
    "CJunctionTemplate__CTrafficLightLocation",
    "iFlags", "iNumJunctionNodes", "iNumEntrances", "iNumPhases", "iNumTrafficLightLocations",
    "fSearchDistance", "fPhaseOffset", "vJunctionMin", "vJunctionMax", "vJunctionNodePositions",
    "Entrances", "PhaseTimings", "TrafficLightLocations", "vNodePosition", "iPhase",
    "fStoppingDistance", "fOrientation", "fAngleFromCenter", "bCanTurnRightOnRedLight",
    "bLeftLaneIsAheadOnly", "bRightLaneIsRightOnly", "iLeftFilterLanePhase", "fStartTime",
    "fDuration", "iPosX", "iPosY", "iPosZ", "vLocation", "fCycleOffset", "fCycleDuration",
    # rage__cutfCutsceneFile2 (.cut) tree - struct/object type names
    "rage__cutfCutsceneFile2", "rage__cutfCutsceneFile2__SConcatData", "vHaltFrequency",
    "rage__cutfAssetManagerObject", "rage__cutfAnimationManagerObject", "rage__cutfAudioObject",
    "rage__cutfPedModelObject", "rage__cutfCameraObject", "rage__cutfObjectIdEvent",
    "rage__cutfLoadSceneEventArgs", "rage__cutfObjectIdListEventArgs", "rage__cutfNameEventArgs",
    "rage__cutfObjectIdNameEventArgs",
    # .cut field names
    "fTotalDuration", "cFaceDir", "iCutsceneFlags", "vOffset", "fRotation", "vTriggerOffset",
    "pCutsceneObjects", "pCutsceneLoadEventList", "pCutsceneEventList", "pCutsceneEventArgsList",
    "attributes", "cutfAttributes", "iRangeStart", "iRangeEnd", "iAltRangeEnd",
    "fSectionByTimeSliceDuration", "fFadeOutCutsceneDuration", "fFadeInGameDuration", "fadeInColor",
    "iBlendOutCutsceneDuration", "iBlendOutCutsceneOffset", "fFadeOutGameDuration",
    "fFadeInCutsceneDuration", "fadeOutColor", "DayCoCHours", "cameraCutList", "sectionSplitList",
    "concatDataList", "discardFrameList", "cSceneName", "fPitch", "fRoll", "bValidForPlayBack",
    "frames", "iObjectId", "attributeList", "UserData1", "UserData2", "cName", "StreamingName",
    "AnimStreamingBase", "fOffset", "fNearDrawDistance", "fFarDrawDistance", "fTime", "iEventId",
    "iEventArgsIndex", "pChildEvents", "StickyId", "IsChild", "iObjectIdList",
    "cAnimExportCtrlSpecFile", "cFaceExportCtrlSpecFile", "cAnimCompressionFile", "cHandle",
    "typeFile", "overrideFaceAnimationFilename", "bFoundFaceAnimation", "bFaceAndBodyAreMerged",
    "bOverrideFaceAnimation", "faceAnimationNodeName", "faceAttributesFilename",
    # ---- ORACLE-WITNESSED schema vocabulary (harvested 2026-08-06) ----
    # Every name below is spelled by a reference exporter oracle XML in _Oracles/{ymt,pso,cut}
    # and joaat_case-VERIFIED to hash to the slot the binary stores. the reference exporter resolves schema
    # names GLOBALLY, so a string it spells in one file is one it knows everywhere -
    # which is why importing them cannot make us print a name where the reference exporter prints hash_.
    # Closes the naOcclusion (1741652604) + firingpatterns .ymt.pso lanes.
    "AccelGrid", "AddList", "AlphabeticOffset", "AnimDict", "AnimName", "AnimatedModel",
    "Animations", "BurstCooldownOnUnset", "CAnchorProps", "CComponentInfo",
    "CExtensionDefSpawnPoint", "CMapTypes", "CPVComponentData", "CPVDrawblData",
    "CPVTextureData", "CPedPropMetaData", "CPedPropTexData", "CPedSelectionSet",
    "CPedVariationInfo", "CScenarioChain", "CScenarioChainingEdge", "CScenarioChainingNode",
    "CScenarioEntityOverride", "CScenarioPoint", "CScenarioPointCluster",
    "CScenarioPointRegion", "CStreamingRequestCommonSet", "CStreamingRequestFrame",
    "CStreamingRequestRecord", "CVehicleKit", "CVehicleKit__sSlotNameOverride",
    "CVehicleMetallicSetting", "CVehicleModLink", "CVehicleModStat", "CVehicleModVisible",
    "CVehicleModelColor", "CVehicleModelInfoPlateTextureSet", "CVehicleModelInfoVarGlobal",
    "CVehicleWheel", "CVehicleWindowColor", "CamDir", "CamPos", "CellDimX", "CellDimY",
    "ChainingGraph", "Chains", "Clusters", "Colors", "CommonAddSets", "CommonSets",
    "DefaultTexureIndex", "DestInteriorHash", "DestRoomIdx", "DiffuseMapName", "Edges",
    "EndModel", "EntityModelHashkey", "EntityOverrides", "FontColor", "FontExtents",
    "FontOutlineColor", "FontOutlineMinMaxDepth", "Frames", "GlobalVariationData",
    "GroupNames", "InteriorNames", "InteriorProxyHash", "IsDoor", "IsFontOutlineEnabled",
    "IsGlass", "Item", "Key", "Kits", "Lights", "LinkType", "LoadSavePoints", "LookUps",
    "MaxCellX", "MaxCellY", "MaxLettersOnPlate", "MaxOcclusion", "MetallicSettings",
    "MinCellX", "MinCellY", "MyPoints", "NewStyle", "Nodes", "NormalMapName", "NumRandomChar",
    "NumericOffset", "PathNodeChildList", "PathNodeKey", "PathNodeList", "PedModelSetNames",
    "Points", "PortalEntityList", "PortalIdx", "PortalInfoIdx", "PortalInfoList",
    "PromoteToHDList", "RandomCharOffset", "RemoveList", "Requests", "RequiredIMapNames",
    "RoomIdx", "Sirens", "SpaceOffset", "StartModel", "TextureSetName", "Textures",
    "TypeNames", "VehicleModelSetNames", "VehiclePlates", "VersionNumber", "Wheels",
    "WindowColors", "aAnchors", "aComponentData3", "aDrawblData3", "aPropMetaData",
    "aSelectionSets", "aTexData", "allowBonnetSlide", "anchor", "anchorId", "audioApply",
    "audioColor", "audioColorHash", "audioId", "audioPrefix", "audioPrefixHash", "availComp",
    "availableInMpSp", "bHasDrawblVariations", "bHasLowLODs", "bHasTexVariations",
    "bIsSuperLOD", "bbMax", "bbMin", "bone", "boneTag", "bsCentre", "bsRadius", "cameraPos",
    "castShadows", "clothData", "collisionBone", "color", "colorName", "compInfos",
    "compositeEntityTypes", "corona", "delta", "direction", "disableBonnetCamera",
    "distBetweenCoronas", "distBetweenCoronas_far", "distribution", "dlcName", "effectsData",
    "emmissiveBoost", "end", "endPhase", "exclusionId", "exclusions", "expressionMods",
    "extendedRange", "faceCamera", "falloffExponent", "falloffMax", "flags", "flash",
    "flashiness", "frontIndicatorCorona", "fxObjName", "fxOffsetPos", "fxOffsetRot", "fxType",
    "group", "headLight", "headLightCorona", "highPri", "identifier", "inclusionId",
    "inclusions", "indicator", "innerConeAngle", "intensity", "intensity_far", "interior",
    "kitName", "kitType", "leftHeadLight", "leftHeadLightMultiples", "leftTailLight",
    "leftTailLightMultiples", "light", "lightFalloffExponent", "lightFalloffMax", "lightGroup",
    "lightInnerConeAngle", "lightOffset", "lightOuterConeAngle", "linkMods", "linkedModels",
    "liveryNames", "lodDist", "metallicID", "mirrorTexture", "modShopLabel", "modelName",
    "modifier", "multiples", "naOcclusionInteriorMetadata", "naOcclusionPathNodeChildMetadata",
    "naOcclusionPathNodeMetadata", "naOcclusionPortalEntityMetadata",
    "naOcclusionPortalInfoMetadata", "name", "numAlternatives", "numAvailProps", "numAvailTex",
    "numCoronas", "offsetPosition", "offsetRotation", "outerConeAngle", "ownsCloth", "pedType",
    "pedXml_audioID", "pedXml_audioID2", "pedXml_compIdx", "pedXml_drawblIdx",
    "pedXml_expressionMods", "pedXml_flags", "pedXml_vfxComps", "probability", "propFlags",
    "propId", "propInfo", "propMask", "props", "ptFxHasTint", "ptFxIsTriggered",
    "ptFxProbability", "ptFxScale", "ptFxSize", "ptFxTag", "ptFxTintB", "ptFxTintG",
    "ptFxTintR", "pull", "pullCoronaIn", "radius", "rear", "rearIndicatorCorona",
    "renderFlags", "requiredImap", "reversingLight", "reversingLightCorona", "rightHeadLight",
    "rightHeadLightMultiples", "rightTailLight", "rightTailLightMultiples", "rimRadius",
    "rotate", "rotation", "scale", "scaleFactor", "sequencer", "sequencerBpm", "shortRange",
    "sirenLight", "sirenSettings", "sirens", "size", "size_far", "slot", "slotNames",
    "spawnType", "specFalloff", "specFresnel", "specInt", "specialAttribute", "speed",
    "spotLight", "start", "startPhase", "statMods", "stickyness", "syncToBpm", "tailLight",
    "tailLightCorona", "tailLightMiddleCorona", "texData", "texId", "textureName",
    "timeMultiplier", "timeTillPedLeaves", "turnOffBones", "turnOffExtra", "type",
    "useRealLights", "vehicleLightSettings", "visibleMods", "weight", "wheelName",
    "wheelVariation", "xRotation", "xenonCoronaColor", "xenonCoronaIntensityModifier",
    "xenonLightColor", "xenonLightIntensityModifier", "yRotation", "zBias", "zRotation",
)
SCHEMA_BY_HASH = {joaat_case(n): n for n in SCHEMA_NAMES}

# ⭐ THE MAP-LANE VOCABULARY IS SHARED WITH META (2026-08-07, Phase 5 Stage A).
# A PSIN-container .ymap/.ytyp holds the SAME schema structs as its RSC7-META twin - CMapTypes,
# archetypes, CBaseArchetypeDef, textureDictionary, extensions ... - but pso2xml's vocabulary was
# built from the ymf/pso/ymt corpus and had none of them, so those files emitted
# `<hash_018A3B1B>` where the oracle spells `<archetypes>`. MEASURED on the first stratified
# spot-diff: 5 of 8 DIFFs were nothing but this.
# Importing is SAFE by the §6y rule that already governs SCHEMA_NAMES: these are SCHEMA
# struct/field names, each joaat_case-verified to hash to the slot the binary stores, and the reference exporter
# resolves schema names GLOBALLY - a string it spells in any file it spells everywhere - so an
# import can never make us print a name where the reference exporter prints hash_. (Contrast per-file CONTENT names,
# which stay forbidden - see the `exportcamera` refusal.) meta2xml's table is itself
# oracle-witnessed, so this shares one vocabulary rather than forking a second copy.
# setdefault: pso2xml's own entries WIN on the (measured-zero) chance of a hash collision.
try:
    import meta2xml as _m2x
    for _n in _m2x.SCHEMA_NAMES:
        SCHEMA_BY_HASH.setdefault(_m2x.joaat_case(_n), _n)
except Exception:                                   # standalone use without the sibling module
    pass

# ⭐ ORACLE-WITNESSED strings ALSO feed schema_name() (2026-08-08): enum MEMBERS render via
# SCHEMA_BY_HASH, not the asset-names dict, so a witnessed spelling (VMT_ENGINE, misc_d,
# MKT_SPORT - carcols <type>/<bone>/<marketType> members) must land here too or it resolves
# in one context and prints hash_ in the other. Same safety as every other entry: setdefault
# only, and a name only ever fires where its joaat equals the stored hash. One witnessed
# source (oracle_witnessed_names.json) serves both tables.
try:
    import json as _json
    import os as _os
    _p = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                       'oracle_witnessed_names.json')
    if _os.path.isfile(_p):
        for _n in _json.load(open(_p, encoding='utf-8')).get('names', []):
            SCHEMA_BY_HASH.setdefault(joaat_case(_n), _n)
            SCHEMA_BY_HASH.setdefault(joaat(_n), _n)
except Exception:
    pass


def schema_name(h):
    return SCHEMA_BY_HASH.get(h, "hash_%08X" % h)


# ---------------------------------------------------------------- float spelling (from meta2xml)
import decimal


def f32(x):
    return struct.unpack("<f", struct.pack("<f", float(x)))[0]


def _sig(f, digits):
    d = decimal.Decimal(f)
    if d == 0:
        return "0"
    exp = d.adjusted()
    r = d.quantize(decimal.Decimal(1).scaleb(exp - digits + 1), rounding=decimal.ROUND_HALF_UP)
    exp = r.adjusted()
    if exp < -4 or exp >= digits:
        mant = format(r.scaleb(-exp), "f").rstrip("0").rstrip(".")
        return "%sE%s%02d" % (mant, "+" if exp >= 0 else "-", abs(exp))
    s = format(r, "f")
    return s.rstrip("0").rstrip(".") if "." in s else s


def fmt_num(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    f = f32(v)
    if f != f:
        return "NaN"
    if f == 0.0:
        return "0"
    s = _sig(f, 7)
    if f32(float(s)) != f:
        s = _sig(f, 9)
    return s


def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


class PsoError(Exception):
    pass


# ---------------------------------------------------------------- container
class Pso:
    def __init__(self, blob):
        if blob[:4] != b"PSIN":
            raise PsoError("not a PSO container (missing PSIN magic)")
        self.d = blob
        self.sections = self._sections()
        self.sec = {n: (o, s) for n, o, s in self.sections}
        for need in ("PMAP", "PSCH"):
            if need not in self.sec:
                raise PsoError("missing section %s" % need)
        self._read_pmap()
        self._read_psch()
        self._struct_cache, self._enum_cache = {}, {}

    def _sections(self):
        d, out, off = self.d, [], 0
        while off + 8 <= len(d):
            ident = d[off:off + 4]
            size = struct.unpack(">I", d[off + 4:off + 8])[0]
            if size < 8 or off + size > len(d):
                raise PsoError("bad section %r size %#x at %#x" % (ident, size, off))
            out.append((ident.decode("latin1"), off, size))
            off += size
        return out

    def _read_pmap(self):
        d = self.d
        po, ps = self.sec["PMAP"]
        self.root_idx, self.nblk = struct.unpack(">IH", d[po + 8:po + 14])
        self.blocks = []
        for i in range(self.nblk):
            bid, boff, z, bsz = struct.unpack(">IIII", d[po + 16 + 16 * i:po + 32 + 16 * i])
            self.blocks.append((bid, boff, bsz))

    def _read_psch(self):
        d = self.d
        so, ss = self.sec["PSCH"]
        self.psch_base = so + 8
        payload = d[so + 8:so + ss]
        n = struct.unpack(">I", payload[0:4])[0]
        self.def_off = {}     # hash -> payload offset of the def body
        for i in range(n):
            h, secoff = struct.unpack(">II", payload[4 + 8 * i:12 + 8 * i])
            self.def_off[h] = secoff - 8      # relative to PSCH payload
        self.psch = payload

    # -- defs (lazy; parsed as struct OR enum by the referencing context)
    def struct_def(self, h):
        if h in self._struct_cache:
            return self._struct_cache[h]
        if h not in self.def_off:
            raise PsoError("no schema def for struct %#010x" % h)
        p = self.def_off[h]
        pl = self.psch
        cnt, size, zero = struct.unpack(">III", pl[p:p + 12])
        if zero != 0:
            raise PsoError("struct %#x header word3 %#x != 0" % (h, zero))
        ents = []
        for i in range(cnt):
            e = pl[p + 12 + 12 * i:p + 24 + 12 * i]
            nh, ty, sub, off_, extra = struct.unpack(">IBBHI", e)
            ents.append(dict(name=nh, type=ty, sub=sub, off=off_, extra=extra))
        info = dict(hash=h, size=size, entries=ents)
        self._struct_cache[h] = info
        return info

    def enum_def(self, h):
        if h in self._enum_cache:
            return self._enum_cache[h]
        if h not in self.def_off:
            raise PsoError("no schema def for enum %#010x" % h)
        p = self.def_off[h]
        pl = self.psch
        header = struct.unpack(">I", pl[p:p + 4])[0]
        cnt = header & 0xFFFF                      # low 16 bits = member count
        members = {}                               # value -> memberHash
        for i in range(cnt):
            mh, val = struct.unpack(">Ii", pl[p + 4 + 8 * i:p + 12 + 8 * i])
            members[val] = mh
        info = dict(hash=h, members=members, header=header)
        self._enum_cache[h] = info
        return info

    def block_data(self, one_based_idx):
        if not (1 <= one_based_idx <= len(self.blocks)):
            raise PsoError("block index %d out of range" % one_based_idx)
        bid, boff, bsz = self.blocks[one_based_idx - 1]
        return self.d[boff:boff + bsz]

    @staticmethod
    def metaptr(v):
        return (v & 0xFFF), (v >> 12)              # (1-based block, byte offset)

    def root(self):
        bid, boff, bsz = self.blocks[self.root_idx - 1]
        return bid, self.d[boff:boff + bsz]


# ------------------------------------------------- game data-file token index (fallback)
# the reference exporter resolves PSO data hash-strings against a string index WIDER than the game's
# filename universe, so a handful of hashes it spells our filename-derived table cannot
# reverse.  MEASURED over the entire 38-file ymf oracle set, that delta is exactly ONE
# string: 54A69840, which the reference exporter spells `rain` (it is a WeatherTypes member of three
# map-metadata manifests: venice/cityhills_02/cityhills_03).  The preimage is recovered
# FROM THE GAME, never from a reference export - `game_pso_names.json` is generated by
# hashing the key-NAMESPACE tokens of common.rpf/data/visualsettings.dat (`rain.gravity.x`,
# `raincollision.waterspeed`, ...); see its own `_provenance` and pso2xml.py --derive-names.
#
# ⚠ UNPINNED - and honest about which half is unpinned.  The NAME is pinned: joaat('rain')
# == 54A69840 is arithmetic, and the string is shipped in the game.  What is NOT derivable
# is the reference exporter's SELECTION rule: why its index holds `rain` but not `snow`/`overcast`/`extrasunny`,
# which sit beside it in the SAME field and which the reference exporter leaves as raw hashes.  Every broader
# game-data corpus tried over-resolves those (all ASCII tokens of common.rpf plaintext ->
# all 14 weather hashes; XML element names -> <Rain> AND <Snow>), so the corpus is kept to
# the one file whose namespaces contain `rain` and none of the other 13.  Because the rule
# is fitted rather than proven, every hit is COUNTED into stats instead of passing silently:
# a rising count at scale = go widen the oracles before trusting it.
_TOKEN_NAMES = None


def token_names():
    """joaat(lower) -> name, from game_pso_names.json beside this file. {} if absent."""
    global _TOKEN_NAMES
    if _TOKEN_NAMES is None:
        import json
        import os
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "game_pso_names.json")
        try:
            with open(p, encoding="utf-8") as f:
                raw = json.load(f).get("names", {})
            # self-check: the file is a hash->name map and the hash must BE the joaat of
            # the name, so a mistyped or tampered entry can never silently name a hash.
            _TOKEN_NAMES = {int(h, 16): n for h, n in raw.items()
                            if int(h, 16) == joaat(n)}
        except (OSError, ValueError):
            _TOKEN_NAMES = {}
    return _TOKEN_NAMES


# ---------------------------------------------------------------- emitter
class Emitter:
    def __init__(self, pso, names=None, extra_names=None):
        self.p = pso
        self.names = names or {}          # joaat(lower) -> asset name  (data hash-strings)
        # The token index is a FALLBACK only, and only once a real filename table exists:
        # with names=None (extract time, before the manifest is built) nothing resolves,
        # and resolving one lone string there would be inconsistent, not helpful.
        if extra_names is None:
            extra_names = token_names() if self.names else {}
        self.extra = extra_names or {}
        self.warn = {}

    def _warn(self, k):
        self.warn[k] = self.warn.get(k, 0) + 1

    def resolve_hashstring(self, h):
        """Data hash-string (joaat lower). Empty for 0; name if known; else hash_%08X."""
        if h == 0:
            return ""
        n = self.names.get(h)
        if n is None:
            n = self.extra.get(h)
            if n is not None:
                self._warn("data hash-string named from the game data-file token index "
                           "(the reference exporter string-index parity, UNPINNED - see pso2xml token_names)")
                return n
            self._warn("unresolved data hash-string")
            return "hash_%08X" % h
        return n

    def emit_file(self, newline="\r\n", trailing=True):
        """the reference exporter writes CRLF line endings and a trailing newline; defaults reproduce that
        byte-for-byte. Pass newline="\\n", trailing=False for LF/no-trailing."""
        bid, data = self.p.root()
        lines = ['<?xml version="1.0" encoding="UTF-8"?>']
        lines += self.emit_struct(bid, data, 0, 0)
        out = newline.join(lines)
        return out + newline if trailing else out

    def _struct_body(self, shash, buf, base, depth):
        """The field lines of a struct (no wrapping tag). Raises PsoError if no schema."""
        sdef = self.p.struct_def(shash)
        body = []
        for e in sdef["entries"]:
            if e["name"] == ELEM:
                continue
            body += self.emit_member(sdef, e, buf, base, depth)
        return body

    def emit_struct(self, shash, buf, base, depth):
        """Emit <StructName>..fields..</StructName> for a struct at buf[base:]."""
        return self._emit_named_struct(schema_name(shash), shash, buf, base, depth)

    def _emit_named_struct(self, tag, shash, buf, base, depth):
        """Emit <tag>..fields..</tag>; the tag is the CALLER's choice (a struct member uses
        its FIELD name, not the struct's own name - .cut's <attributes>/<attributeList> both
        wrap the same SUserAttributes struct)."""
        ind = " " * depth
        try:
            body = self._struct_body(shash, buf, base, depth + 1)
        except PsoError:
            self._warn("no schema for struct %#010x" % shash)
            return ["%s<%s />" % (ind, tag)]
        if not body:
            return ["%s<%s />" % (ind, tag)]
        return ["%s<%s>" % (ind, tag)] + body + ["%s</%s>" % (ind, tag)]

    def _struct_item(self, shash, buf, base, depth, type_attr=None):
        """Emit one <Item[ type="X"]> ... </Item> for a struct array element."""
        ind = " " * depth
        open_tag = '%s<Item type="%s">' % (ind, type_attr) if type_attr else "%s<Item>" % ind
        empty_tag = '%s<Item type="%s" />' % (ind, type_attr) if type_attr else "%s<Item />" % ind
        try:
            body = self._struct_body(shash, buf, base, depth + 1)
        except PsoError:
            self._warn("no schema for item struct %#010x" % shash)
            return [empty_tag]
        if not body:
            return [empty_tag]
        return [open_tag] + body + ["%s</Item>" % ind]

    # ---- scalar element helpers (shared by scalar members and scalar arrays) ----
    _SCALAR_SIZE = {0x00: 1, 0x02: 1, 0x03: 2, 0x05: 4, 0x06: 4, 0x07: 4}

    @staticmethod
    def _scalar_str(et, esub, buf, o):
        """One scalar rendered as the reference exporter spells it. 0x06 sub 0x01 is a packed colour (hex u32);
        every other int is decimal-signed; 0x07 float via fmt_num; 0x00 bool as true/false."""
        if et == 0x00:
            return "true" if buf[o] else "false"
        if et == 0x02:
            return str(buf[o])
        if et == 0x03:
            return str(struct.unpack_from(">h", buf, o)[0])
        if et == 0x07:
            return fmt_num(struct.unpack_from(">f", buf, o)[0])
        if et == 0x06 and esub == 0x01:
            return "0x%08X" % struct.unpack_from(">I", buf, o)[0]
        return str(struct.unpack_from(">i", buf, o)[0])          # 0x05 / 0x06 signed int32

    def emit_member(self, sdef, e, buf, base, depth):
        ind = " " * depth
        name = schema_name(e["name"])
        t, sub, off, extra = e["type"], e["sub"], e["off"], e["extra"]
        o = base + off
        if t == 0x0d:                              # ARRAY
            return self.emit_array(sdef, e, buf, base, depth, name, ind)
        if t == 0x0b:                              # STRING
            if sub == 0x00:                        # inline fixed char[]
                ln = extra >> 16
                raw = bytes(buf[o:o + ln]).split(b"\x00", 1)[0]
                s = raw.decode("latin1")
                return ["%s<%s />" % (ind, name)] if s == "" else \
                       ["%s<%s>%s</%s>" % (ind, name, esc(s), name)]
            if sub in (0x01, 0x02, 0x03):          # POINTER to a NUL-terminated inline string
                # metaptr -> block; the char data lives in a separate string block. Null -> empty.
                # (.cut rage__cutfAudioObject cName -> "UNDER_INT_4.WAV").
                # subs 0x01 + 0x02 PINNED 2026-08-08 from carcols.ymt: colorName (0x01, the
                # stored word decodes as a metaptr to block 3 and the pointed NUL-terminated
                # text reproduces the oracle's literal spelling incl. leading space and
                # trailing tabs) and the modShopLabel class (0x02, 4 members - the leaked
                # values were 0x0nnnn003 pointer words, oracle spells MNU_EXH4-style labels)
                # - both proven by the whole-file byte compare. Previously they fell through
                # to the joaat branch and printed hash_%08X of the POINTER value.
                mp = struct.unpack_from(">I", buf, o)[0]
                s = self._string_at_ptr(mp)
                return ["%s<%s />" % (ind, name)] if s == "" else \
                       ["%s<%s>%s</%s>" % (ind, name, esc(s), name)]
            # hash-string (sub 0x07 / 0x08): joaat(lower) -> name dict, else hash_%08X
            h = struct.unpack_from(">I", buf, o)[0]
            s = self.resolve_hashstring(h)
            return ["%s<%s />" % (ind, name)] if s == "" else \
                   ["%s<%s>%s</%s>" % (ind, name, esc(s), name)]
        if t == 0x0e:                              # ENUM (text)
            # storage width by SUB (PINNED 2026-08-08, carcols CVehicleModelColor: sub 0x02
            # members metallicID/audioColor/audioPrefix sit at CONSECUTIVE offsets 12/13/14 -
            # one byte each; the old unconditional u32 read produced 17039360 = 0x01040000,
            # i.e. FOUR packed u8 enums read as one word). sub 0x00 stays u32. u8 enums are
            # SIGNED for the -1 member (EVehicleModelColorMetallic none = -1 witnessed).
            if sub == 0x02:
                v = struct.unpack_from(">b", buf, o)[0]
            else:
                v = struct.unpack_from(">I", buf, o)[0]
            info = self.p.enum_def(extra)
            mh = info["members"].get(v)
            txt = schema_name(mh) if mh is not None else str(v)
            return ["%s<%s>%s</%s>" % (ind, name, esc(txt), name)]
        if t == 0x0f:                              # FLAGS
            v = struct.unpack_from(">I", buf, o)[0]
            ehash = sdef["entries"][extra & 0xFFFF]["extra"]
            info = self.p.enum_def(ehash)
            if v == 0:
                return ["%s<%s />" % (ind, name)]
            parts = []
            for bit in range(32):
                if v & (1 << bit):
                    mh = info["members"].get(bit)
                    if mh is None:
                        self._warn("flags bit without member")
                        parts.append("hash_%08X" % (1 << bit))
                    else:
                        parts.append(schema_name(mh))
            # MEASURED: PSO T_FLAGS joins set-bit member names with a SPACE, ascending bit
            # order (CMapDataGroup Flags -> "TIME_DEPENDENT WEATHER_DEPENDENT"). Note this
            # differs from RSC7-META's comma-join in meta2xml - a per-format rendering law.
            return ["%s<%s>%s</%s>" % (ind, name, esc(" ".join(parts)), name)]
        if t == 0x0c:                              # STRUCT member (tagged by FIELD name)
            if sub == 0x03:                        # POINTER to a single struct; null -> empty
                # the pointed block's own id gives the (polymorphic) struct type.
                # (.cut pChildEvents is always null here -> <pChildEvents />).
                mp = struct.unpack_from(">I", buf, o)[0]
                if mp == 0:
                    return ["%s<%s />" % (ind, name)]
                bidx, boff2 = self.p.metaptr(mp)
                tbid = self.p.blocks[bidx - 1][0]
                return self._emit_named_struct(name, tbid, self.p.block_data(bidx), boff2, depth)
            if sub == 0x04 or extra == 0:          # typed inline struct with no fields -> empty
                # (.cut cutfAttributes: the element struct hash reads 0 -> <cutfAttributes />).
                return ["%s<%s />" % (ind, name)]
            return self._emit_named_struct(name, extra, buf, o, depth)
        # scalars
        if t == 0x00:                              # bool
            return ['%s<%s value="%s" />' % (ind, name, "true" if buf[o] else "false")]
        if t == 0x02:                              # u8
            return ['%s<%s value="%d" />' % (ind, name, buf[o])]
        if t == 0x03:                              # i16
            v = struct.unpack_from(">h", buf, o)[0]
            return ['%s<%s value="%d" />' % (ind, name, v)]
        if t == 0x04:                              # u16 (2 bytes)
            # PINNED 2026-08-07 (Phase 5 Stage A) from the game's own binaries: the only carriers
            # are CDistantLODLight numStreetLights @0x28 / category @0x2A, whose 2-byte WIDTH is
            # proven by member adjacency (differing garbage in the tail padding). Signedness is
            # taken from the RSC7-META TWIN of the same struct (identical struct hash 793441F4,
            # identical offsets) where the member is META 0x13 = u16 and the reference exporter's existing oracle
            # spells its nonzero values as positive decimals - i.e. an oracle-witnessed
            # cross-container equivalence, not a guess.
            v = struct.unpack_from(">H", buf, o)[0]
            return ['%s<%s value="%d" />' % (ind, name, v)]
        if t == 0x05:                              # signed int32
            v = struct.unpack_from(">i", buf, o)[0]
            return ['%s<%s value="%d" />' % (ind, name, v)]
        if t == 0x06:                              # int32. MEASURED: the reference exporter renders sub 0x00 SIGNED
            # (naOcclusion EntityModelHashkey = -1033001619, stored 0xC26F7CAD; .cut AnimStreamingBase
            # = -175977911). sub 0x01 is a PACKED COLOUR -> hex u32 (.cut fadeInColor 0xFF000000).
            if sub == 0x01:
                return ['%s<%s value="0x%08X" />'
                        % (ind, name, struct.unpack_from(">I", buf, o)[0])]
            v = struct.unpack_from(">i", buf, o)[0]
            return ['%s<%s value="%d" />' % (ind, name, v)]
        if t == 0x07:                              # float32
            v = struct.unpack_from(">f", buf, o)[0]
            return ['%s<%s value="%s" />' % (ind, name, fmt_num(v))]
        if t == 0x09 or t == 0x14:                 # vec3 (3 BE floats in a 16-byte slot; x/y/z)
            # MEASURED: both codes render x/y/z only, 4th word is padding (.cut vOffset, junctions
            # vJunctionMin/vNodePosition = 0x09; junctions vLocation = 0x14). No observed difference
            # in XML form between the two, so they share one renderer.
            x, y, z = struct.unpack_from(">3f", buf, o)
            return ['%s<%s x="%s" y="%s" z="%s" />'
                    % (ind, name, fmt_num(x), fmt_num(y), fmt_num(z))]
        if t == 0x0a or t == 0x15:                 # vec4 / quaternion
            # 0x0a PINNED 2026-08-07: every instance sits in a 16-byte slot (CEntityDef.rotation,
            # CExtensionDefParticleEffect.offsetRotation, CCompEntityEffectsData.fxOffsetRot);
            # 26 of 36 are exactly (0,0,0,1) and all 10 non-trivial values are UNIT quaternions
            # (|q|^2 within 2.2e-7 of 1.0) - a 4th component that is padding could not do that.
            # The META twin of the same struct (hash CE501483, same offset 0x30) declares it as
            # META 0x34 = 4xf32 and the reference exporter's oracle spells it <rotation x y z w />. Shares the 0x15
            # renderer exactly as 0x09/0x14 share the vec3 one.
            x, y, z, w = struct.unpack_from(">4f", buf, o)
            return ['%s<%s x="%s" y="%s" z="%s" w="%s" />'
                    % (ind, name, fmt_num(x), fmt_num(y), fmt_num(z), fmt_num(w))]
        if t == 0x08:                              # vec2 (2 BE floats)
            # PINNED 2026-08-08 from carcols.ymt, the corpus's only carrier (12 occurrences,
            # CVehicleModelInfoPlateTextureSet.MaxLettersOnPlate @48 + FontOutlineMinMaxDepth
            # @68 in an 80-B struct = 8-B slots): the oracle spells <X x=".." y=".." />
            # (x="7" y="1" / x="0.475" y="0.5") and two BE f32 at the member offset reproduce
            # every value - proven by the whole-file byte compare.
            x, y = struct.unpack_from(">2f", buf, o)
            return ['%s<%s x="%s" y="%s" />' % (ind, name, fmt_num(x), fmt_num(y))]
        self._warn("unhandled member type %#04x" % t)
        return ["%s<%s />" % (ind, name)]

    def _string_at_ptr(self, mp):
        """Follow a metaptr to a block and read a NUL-terminated latin1 string. 0 -> ''."""
        if mp == 0:
            return ""
        bidx, off = self.p.metaptr(mp)
        bdata = self.p.block_data(bidx)
        return bytes(bdata[off:]).split(b"\x00", 1)[0].decode("latin1")

    # ---- array element renderers (shared by the pointer and inline lanes) ----
    def _emit_struct_array(self, name, ind, shash, buf, o, count, stride, depth):
        itype = schema_name(shash)
        if count == 0:
            return ['%s<%s itemType="%s" />' % (ind, name, itype)]
        out = ['%s<%s itemType="%s">' % (ind, name, itype)]
        for i in range(count):
            out += self._struct_item(shash, buf, o + i * stride, depth + 1)
        out.append("%s</%s>" % (ind, name))
        return out

    def _emit_vec3_array(self, name, ind, buf, o, count, depth):
        # MEASURED: a vec3 array renders ONE "x, y, z" per line (fmt_num, ", "-joined),
        # indented depth+1 (junctions vJunctionNodePositions). NO <Item> wrappers.
        if count == 0:
            return ["%s<%s />" % (ind, name)]
        f = " " * (depth + 1)
        out = ["%s<%s>" % (ind, name)]
        for i in range(count):
            x, y, z = struct.unpack_from(">3f", buf, o + i * 16)
            out.append("%s%s, %s, %s" % (f, fmt_num(x), fmt_num(y), fmt_num(z)))
        out.append("%s</%s>" % (ind, name))
        return out

    def _emit_hashstring_array(self, name, ind, buf, o, count, depth, esub=0x07):
        # esub dispatch PINNED 2026-08-08 (carcols liveryNames class): elements whose desc
        # sub is a POINTER form (0x01/0x02/0x03) are EIGHT-byte {u32 metaptr, u32 pad} slots
        # pointing at NUL-terminated text - MEASURED on live kit instances (SANC count=5:
        # words alternate real-pointer/zero at 4-byte reads; at 8-byte stride all five
        # pointers decode SANC_lV1..lV5 exactly as the oracle spells). A 4-byte walk read
        # the pads as null pointers - half the list emitted empty, the tail lost. joaat subs
        # (0x07/0x08) are 4-byte hash words and keep the dictionary route.
        if count == 0:
            return ["%s<%s />" % (ind, name)]
        f = " " * (depth + 1)
        out = ["%s<%s>" % (ind, name)]
        ptrform = esub in (0x01, 0x02, 0x03)
        stride = 8 if ptrform else 4
        for i in range(count):
            v = struct.unpack_from(">I", buf, o + i * stride)[0]
            s = self._string_at_ptr(v) if ptrform else self.resolve_hashstring(v)
            out.append("%s<Item>%s</Item>" % (f, esc(s)))
        out.append("%s</%s>" % (ind, name))
        return out

    def _emit_scalar_array(self, name, ind, et, esub, buf, o, count):
        # MEASURED: a scalar array renders space-joined in the tag body, one line
        # (.cut iCutsceneFlags "268452352 0 0 0"; iObjectIdList "3").
        if count == 0:
            return ["%s<%s />" % (ind, name)]
        sz = self._SCALAR_SIZE.get(et, 4)
        parts = [self._scalar_str(et, esub, buf, o + i * sz) for i in range(count)]
        return ["%s<%s>%s</%s>" % (ind, name, " ".join(parts), name)]

    def emit_array(self, sdef, e, buf, base, depth, name, ind):
        # refTypeIdx = low 16 bits of extra; the element descriptor is another entry of THIS
        # struct (its name is the synthetic 0x100). High 16 bits of extra = the element COUNT
        # for the inline subtypes (0 for every sub-0x00 pointer array, whose count is in the
        # descriptor). Guarded so an unrecognised array degrades to a warning, never a crash.
        ridx = e["extra"] & 0xFFFF
        if ridx >= len(sdef["entries"]):
            self._warn("array refTypeIdx %d out of range (extra=%#x)" % (ridx, e["extra"]))
            return ["%s<%s />" % (ind, name)]
        desc = sdef["entries"][ridx]               # element descriptor (name 0x100)
        et, esub, eextra = desc["type"], desc["sub"], desc["extra"]
        o = base + e["off"]

        if e["sub"] == 0x00:
            # POINTER array: 16-byte descriptor {u32 metaptr, u32 pad, u16 count, u16 cap, u32}.
            # Element data lives in the pointed block. (Every CPackFileMetaData/.ymf array.)
            ptr, _pad, count, cap = struct.unpack_from(">IIHH", buf, o)
            if et == 0x0c and esub == 0x03:        # array of POINTERS to structs
                # element block holds {u32 metaptr, u32 pad} pairs; each -> a struct block whose
                # own id gives the item's polymorphic type. No itemType attr; each <Item> carries
                # type="StructName" (firingpatterns Infos; .cut pCutsceneObjects/EventLists).
                if count == 0:
                    # ⭐ EMPTY carries an EMPTY itemType (2026-08-07): with zero items there is no
                    # polymorphic type to name, and the reference exporter writes the attribute anyway, blank. Only
                    # the map-lane PSO files exercise this - MEASURED: `itemType=""` appears 46
                    # times across the oracle set and in exactly 5 files, all PSIN ymap/ytyp
                    # (cs1_railwyc ×21, cs1_railwyc_long_0 ×9, cs1_railwyc.ytyp ×22 ... ), and
                    # NEVER in the 50 ymf/pso/ymt oracles that already pass byte-identical.
                    return ['%s<%s itemType="" />' % (ind, name)]
                bidx, boff = self.p.metaptr(ptr)
                bdata = self.p.block_data(bidx)
                out = ["%s<%s>" % (ind, name)]
                for i in range(count):
                    mp = struct.unpack_from(">I", bdata, boff + i * 8)[0]
                    tbidx, tboff = self.p.metaptr(mp)
                    tbid = self.p.blocks[tbidx - 1][0]
                    out += self._struct_item(tbid, self.p.block_data(tbidx), tboff,
                                             depth + 1, type_attr=schema_name(tbid))
                out.append("%s</%s>" % (ind, name))
                return out
            if et == 0x0c:                         # array of INLINE structs via pointer
                if count == 0:
                    return ['%s<%s itemType="%s" />' % (ind, name, schema_name(eextra))]
                if eextra not in self.p.def_off:
                    self._warn("inline-struct array element struct %#010x missing (sub=%#x)"
                               % (eextra, esub))
                    return ["%s<%s />" % (ind, name)]
                bidx, boff = self.p.metaptr(ptr)
                stride = self.p.struct_def(eextra)["size"]
                return self._emit_struct_array(name, ind, eextra, self.p.block_data(bidx),
                                               boff, count, stride, depth)
            if et == 0x0b:                         # array of strings (no itemType)
                if count == 0:
                    return ["%s<%s />" % (ind, name)]
                bidx, boff = self.p.metaptr(ptr)
                return self._emit_hashstring_array(name, ind, self.p.block_data(bidx),
                                                   boff, count, depth, esub=esub)
            if et in (0x09, 0x14):                 # array of vec3 via pointer
                if count == 0:
                    return ["%s<%s />" % (ind, name)]
                bidx, boff = self.p.metaptr(ptr)
                return self._emit_vec3_array(name, ind, self.p.block_data(bidx),
                                             boff, count, depth)
            if et in self._SCALAR_SIZE:            # array of scalars via pointer (iObjectIdList)
                if count == 0:
                    return ["%s<%s />" % (ind, name)]
                bidx, boff = self.p.metaptr(ptr)
                return self._emit_scalar_array(name, ind, et, esub, self.p.block_data(bidx),
                                               boff, count)
            if et == 0x0e:                         # array of ENUMS -> <Item>MemberName</Item>
                # PINNED 2026-08-08 from carcols.ymt, the corpus's only carrier
                # (CVehicleModVisible.turnOffBones, 750 arrays: 442 populated + 308 empty
                # matching the oracle's 442 open+close pairs + 308 self-closing exactly).
                # Elements are u32 BE enum values (same slot the 0x0e MEMBER renderer reads),
                # each spelled as the enum member name in an <Item>, hashstring-array layout.
                if count == 0:
                    return ["%s<%s />" % (ind, name)]
                bidx, boff = self.p.metaptr(ptr)
                bdata = self.p.block_data(bidx)
                info = self.p.enum_def(eextra)
                f = " " * (depth + 1)
                out = ["%s<%s>" % (ind, name)]
                for i in range(count):
                    v = struct.unpack_from(">I", bdata, boff + i * 4)[0]
                    mh = info["members"].get(v)
                    out.append("%s<Item>%s</Item>"
                               % (f, esc(schema_name(mh) if mh is not None else str(v))))
                out.append("%s</%s>" % (ind, name))
                return out
            self._warn("unhandled array element type %#04x" % et)
            return ["%s<%s />" % (ind, name)]

        # INLINE array (sub 0x01/0x02/0x04/0x81): element data is stored inline at base+off in
        # THIS buffer; count = extra>>16 (a fixed/capacity array). Verified against junctions
        # (Entries/Entrances/PhaseTimings/TrafficLightLocations/vJunctionNodePositions/
        # AutoJunctionAdjustments) and .cut (concatDataList/iCutsceneFlags), byte-identical.
        count = e["extra"] >> 16
        if et == 0x0c:
            if eextra not in self.p.def_off:
                self._warn("inline-struct array element struct %#010x missing (sub=%#x)"
                           % (eextra, e["sub"]))
                return ["%s<%s />" % (ind, name)]
            stride = self.p.struct_def(eextra)["size"]
            return self._emit_struct_array(name, ind, eextra, buf, o, count, stride, depth)
        if et in (0x09, 0x14):
            return self._emit_vec3_array(name, ind, buf, o, count, depth)
        if et == 0x0b:
            return self._emit_hashstring_array(name, ind, buf, o, count, depth, esub=esub)
        if et in self._SCALAR_SIZE:
            return self._emit_scalar_array(name, ind, et, esub, buf, o, count)
        if et == 0x0d:                             # inline fixed array OF pointer-arrays
            # PINNED 2026-08-08 from carcols.ymt, the corpus's only carrier
            # (CVehicleModelInfoVarGlobal.Wheels: 9 fixed slots = 8 populated + 1 empty,
            # matching the oracle's 8 <Item itemType="CVehicleWheel"> + 1 self-closing).
            # Each 16-B slot is the standard pointer-array descriptor {u32 metaptr, u32 pad,
            # u16 count, u16 cap, u32}; the inner element desc (type 0x0c, extra = struct
            # hash) gives the item struct. Outer <Item> carries itemType="StructName";
            # inner items are bare <Item> struct bodies.
            ridx2 = desc["extra"] & 0xFFFF
            if ridx2 >= len(sdef["entries"]):
                self._warn("nested-array inner refTypeIdx %d out of range" % ridx2)
                return ["%s<%s />" % (ind, name)]
            inner = sdef["entries"][ridx2]
            if inner["type"] != 0x0c or inner["extra"] not in self.p.def_off:
                self._warn("nested-array inner elem type %#04x unhandled (extra=%#010x)"
                           % (inner["type"], inner["extra"]))
                return ["%s<%s />" % (ind, name)]
            shash = inner["extra"]
            itype = schema_name(shash)
            stride = self.p.struct_def(shash)["size"]
            f = " " * (depth + 1)
            out = ["%s<%s>" % (ind, name)]
            for i in range(count):
                sptr, _spad, scount, _scap = struct.unpack_from(">IIHH", buf, o + i * 16)
                if scount == 0:
                    out.append('%s<Item itemType="%s" />' % (f, itype))
                    continue
                sbidx, sboff = self.p.metaptr(sptr)
                sdata = self.p.block_data(sbidx)
                out.append('%s<Item itemType="%s">' % (f, itype))
                for j in range(scount):
                    out += self._struct_item(shash, sdata, sboff + j * stride, depth + 2)
                out.append("%s</Item>" % f)
            out.append("%s</%s>" % (ind, name))
            return out
        self._warn("unhandled inline array element type %#04x (sub=%#x)" % (et, e["sub"]))
        return ["%s<%s />" % (ind, name)]


# ---------------------------------------------------------------- API
def pso_to_xml(blob, names=None, extra_names=None):
    """names: joaat(lower) -> asset name (the filename index).
    extra_names: optional fallback dict consulted only where `names` misses. Left None it
    defaults to the shipped game data-file token index (and to {} when names is empty);
    pass {} to switch the fallback off entirely."""
    p = Pso(blob)
    em = Emitter(p, names=names, extra_names=extra_names)
    return em.emit_file(), em.warn


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 2 and sys.argv[1] == "--derive-names":
        # Regenerate game_pso_names.json from a live install (see token_names above for
        # the rule and why the corpus is that one file). Imports quarry lazily - quarry
        # imports this module, so a top-level import would be circular.
        import ctypes
        import json
        import os
        import re
        import quarry
        import keyderive
        import ngcrypto
        game = sys.argv[2]
        rk, rt = keyderive.acquire(game, None, None)
        keys, tables = ngcrypto.keys_from_bytes(rk), ngcrypto.tables_from_bytes(rt)
        aes = keyderive.acquire_aes(game)
        dll, oodle = quarry.oodle_dll(game), None
        if dll:
            _lib = ctypes.CDLL(dll)
            _fn = _lib.OodleLZ_Decompress
            _fn.restype = ctypes.c_int64

            def oodle(src, outsz):
                buf = ctypes.create_string_buffer(outsz)
                n = _fn(ctypes.c_char_p(src), ctypes.c_int64(len(src)), buf,
                        ctypes.c_int64(outsz), 0, 0, 0, None, None, None, None, None,
                        None, 3)
                if n <= 0:
                    raise RuntimeError("oodle failed")
                return buf.raw[:n]
        SRC = "data/visualsettings.dat"
        r = quarry.Rpf(os.path.join(game, "common.rpf"), keys, tables, aes_key=aes)
        r.read_toc()
        paths = quarry._tree_paths(r.entries)
        blob = next((r.payload(e, oodle) for i, e in enumerate(r.entries)
                     if not e["dir"] and (paths[i] + "/" + e["name"]).lower() == SRC), None)
        if blob is None:
            raise SystemExit("STOP: %s not found in common.rpf" % SRC)
        ident, toks = re.compile(r"[a-z][a-z0-9_]*\Z"), set()
        for line in blob.decode("latin-1").splitlines():
            line = line.strip()
            if not line or line[0] in "#/":
                continue
            t = re.split(r"\s", line, 1)[0].split(".")[0].lower()
            if t and ident.match(t):
                toks.add(t)
        tbl = {"%08X" % joaat(t): t for t in sorted(toks)}
        if len(tbl) != len(toks):
            raise SystemExit("STOP: joaat collision inside the token corpus")
        out = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "game_pso_names.json")
        with open(out, encoding="utf-8") as f:
            doc = json.load(f)
        doc["names"] = dict(sorted(tbl.items()))
        with open(out, "w", encoding="utf-8") as f:
            json.dump(doc, f, indent=1)
        print("wrote %s: %d tokens" % (out, len(tbl)))
        raise SystemExit(0)
    xml, warn = pso_to_xml(open(sys.argv[1], "rb").read())
    print(xml)
    if warn:
        sys.stderr.write("warnings: %r\n" % warn)
