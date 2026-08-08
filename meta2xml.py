"""meta2xml - the RAGE interchange `ytyp` / `ymap` XML EMITTER, plus a round-trip harness.

WHY THIS IS SEPARATE FROM THE BINARY READER: `ytyp`/`ymap` are RSC7 **v2 META**, a schema-driven
format structurally unlike `ydr`, and reverse-engineering it is its own job. The XML half, however,
is fully knowable TODAY from the operator's own third-party reference exports - so it is built and PROVEN first, against 1,707
ytyp and 11,052 ymap references. When the binary reader lands it only has to produce the plain dicts
below; the serialisation is already verified, so a decode bug cannot hide inside an unproven emitter.

    python meta2xml.py --roundtrip --census

THE ACCEPTANCE BAR is small and pinned (`RudeToolset.cpp:1938-2046`, LOG "ImportMapArea's ACTUAL XML
contract"). NOTE `FindChildNode` is DIRECT-CHILDREN-ONLY, so nesting depth is load-bearing:
  ytyp: root -> `<archetypes>` -> `<Item>` with `<name>`, `<assetName>`, `<assetType>`
  ymap: root -> `<entities>`   -> `<Item>` with `<archetypeName>`, `<position>`, `<rotation>`,
                                  `<lodLevel>`, `<scaleXY>`, `<scaleZ>`
Everything else here is faithfulness to the reference shape, which costs nothing and avoids a second
pass when more of the plugin starts reading these files.

ENUM TABLES MUST BE MEASURED, NEVER ASSUMED - same discipline as ytd's Usage table. A numeric code
whose string has not been observed in a matched pair must NOT be invented; see `--census`.

This file is deliberately ASCII-only: it gets processed by PowerShell on this machine, and a
UTF-8 read/write round-trip there corrupts non-ASCII bytes and prepends a BOM Python rejects.
"""
import argparse
import collections
import decimal
import glob
import os
import re
import struct
import sys
import xml.etree.ElementTree as ET

# Reference corpus for the verification harnesses (--roundtrip / --census / --verify-binary):
# a directory of reference XML exports laid out <corpus>/<kind>/*.<kind>.xml. This is personal
# to each machine, so it is NEVER a hardcoded path in this (public) file - pass --corpus or set
# QUARRY_CORPUS. Plain conversion (--convert) needs no corpus at all.
CORPUS = os.environ.get("QUARRY_CORPUS")

# `extract` renames a WITHIN-slot basename collision to `X~1`, `X~2`, ... ANCHORED to the end on
# purpose: a bare `'~' in stem` also matches a real game asset whose name merely contains a tilde.
_ALT_SUFFIX = re.compile(r"~\d+$")


# ================================================================ RSC7 v2 META reader
# THE UNLOCK: meta SCHEMA hashes (field names, struct names, enum member names) are
# **case-SENSITIVE** joaat - the string is hashed as written, NOT lowercased. Asset-name hashes
# stored in the DATA are the ordinary lowercase joaat. Getting this backwards makes every schema
# lookup miss and the format look undecodable.
def joaat(s, lower=True):
    h = 0
    for ch in (s.lower() if lower else s):
        h = (h + ord(ch)) & 0xFFFFFFFF
        h = (h + (h << 10)) & 0xFFFFFFFF
        h ^= h >> 6
    h = (h + (h << 3)) & 0xFFFFFFFF
    h ^= h >> 11
    return (h + (h << 15)) & 0xFFFFFFFF


def joaat_case(s):
    return joaat(s, lower=False)


# Field / struct / enum-member names we need to recognise. Hashing these ourselves means NO
# shipped hash dictionary is required for the schema half - the names are known constants.
SCHEMA_NAMES = (
    # CMapTypes / archetypes
    "CMapTypes", "CBaseArchetypeDef", "CTimeArchetypeDef", "CMloArchetypeDef", "archetypes",
    "extensions", "dependencies", "compositeEntityTypes",
    # CMapTypes txd-relationship container (2026-08-08): witnessed in the PSIN-container ytyps
    # (des_hosp_ceil2 / id2_17 oracles spell them; joaat_case verified: txdRelationships =
    # 069ADF93, CTxdRelationship = D9826A6F vs the stored hashes). Blast radius measured first:
    # 0 emitted sweep XMLs spell either hash_ form, and the filebase holds no pso.xml yet.
    "txdRelationships", "CTxdRelationship",
    # compositeEntityTypes vocabulary (2026-08-06): every one verified against the
    # des_jewel_cab4 record's own stored hashes before use - no guessed names.
    "CCompositeEntityType", "Animations", "CCompEntityAnims", "CCompEntityEffectsData",
    "StartModel", "EndModel", "StartImapFile", "EndImapFile", "PtFxAssetName",
    "AnimDict", "AnimName", "AnimatedModel", "punchInPhase", "punchOutPhase",
    "effectsData", "Name",
    # CCompEntityEffectsData members (2026-08-08): all 13 verified by exact-case joaat
    # against des_fib_ceiling's own stored member hashes (fxOffsetPos=DB2290B8,
    # fxOffsetRot=65FAB1EA, startPhase=C0097997, endPhase=5F6709A3, ptFxIsTriggered=CCB4D20A,
    # ptFxTag=967EF874, ptFxScale=5D68BA61, ptFxProbability=CD86F6E4, ptFxHasTint=D52DB495,
    # ptFxTintR=4DBA91CF, ptFxTintG=016BF8E7, ptFxTintB=84A07FB2, ptFxSize=4063C8F9);
    # fxType/boneTag were already resolving. Blast radius measured before the edit:
    # 0/573 emitted grade_sweep XMLs spell any of the 13 hash_ forms.
    "fxOffsetPos", "fxOffsetRot", "startPhase", "endPhase", "ptFxIsTriggered",
    "ptFxTag", "ptFxScale", "ptFxProbability", "ptFxHasTint",
    "ptFxTintR", "ptFxTintG", "ptFxTintB", "ptFxSize",
    "lodDist", "flags", "specialAttribute", "bbMin", "bbMax", "bsCentre", "bsRadius",
    "hdTextureDist", "name", "textureDictionary", "clipDictionary", "drawableDictionary",
    "physicsDictionary", "assetType", "assetName",
    # CTimeArchetypeDef: the one field it adds over the base archetype
    "timeFlags",
    # CMloArchetypeDef (interiors) - struct + field names measured over ALL 272 resolved MLO
    # binaries (probe 2026-07-28: exactly ONE schema layout per struct, hashes match the LOG:
    # CMloArchetypeDef 0x10506455, CMloRoomDef 0x0B1811F1, CMloPortalDef 0x995072CA,
    # CMloEntitySet 0xD6A799F9, CMloTimeCycleModifier 0x301D99A8).
    # NOTE "exteriorVisibiltyDepth" is R*'s own spelling (sic) - the hash only matches as written.
    "CMloRoomDef", "CMloPortalDef", "CMloEntitySet", "CMloTimeCycleModifier",
    "mloFlags", "rooms", "portals", "entitySets", "timeCycleModifiers",
    "blend", "timecycleName", "secondaryTimecycleName", "portalCount", "floorId",
    "exteriorVisibiltyDepth", "attachedObjects",
    "roomFrom", "roomTo", "mirrorPriority", "opacity", "audioOcclusion", "corners",
    "locations", "sphere", "percentage", "range", "startHour", "endHour",
    # Extension defs (archetype- and entity-attached) - struct + field names measured over
    # the resolved binaries (probe 2026-07-28: every candidate matched its stored hash;
    # the LightEffect `instances` element struct is CLightAttrDef, verified by refKey
    # 0xF54B227B). Reference oracle: 14 extension types, ~32k items.
    "CExtensionDefAudioCollisionSettings", "CExtensionDefAudioEmitter",
    "CExtensionDefBuoyancy", "CExtensionDefDoor", "CExtensionDefExplosionEffect",
    "CExtensionDefExpression", "CExtensionDefLadder", "CExtensionDefLightEffect",
    "CExtensionDefLightShaft", "CExtensionDefParticleEffect", "CExtensionDefProcObject",
    "CExtensionDefSpawnPoint", "CExtensionDefSpawnPointOverride",
    "CExtensionDefWindDisturbance", "CLightAttrDef",
    # ⭐ Cloth custom-bounds (2026-08-07): the ONE extension type that is not a C-prefixed class
    # name, which is why it stayed `hash_32818195` and refused 22 ymap conversions. Preimage from
    # the GAME's own plaintext data (common.rpf :: data/cloth/global_cloth_custombounds.xml -
    # its ROOT ELEMENT is the class name); the element-struct name is confirmed by the oracle's
    # itemType attribute. Both joaat_case-verified: 0x32818195 / 0x656F0305. Member names below
    # each self-verify against the hashes the 22 carriers store in their own schema blocks.
    "rage__phVerletClothCustomBounds", "rage__phCapsuleBoundDef",
    "CollisionData", "OwnerName", "Rotation", "Position", "Normal",
    "CapsuleRadius", "CapsuleLen", "CapsuleHalfHeight", "CapsuleHalfWidth", "Flags",
    "offsetPosition", "offsetRotation",
    "enableLimitAngle", "startsLocked", "canBreak", "limitAngle", "doorTargetRatio",
    "audioHash",
    "bottom", "top", "normal", "materialType", "template", "canGetOffAtTop",
    "canGetOffAtBottom",
    "fxName", "fxType", "boneTag", "scale", "probability", "color",
    "explosionName", "explosionTag", "explosionType",
    "disturbanceType", "size", "strength", "effectHash", "settings",
    "cornerA", "cornerB", "cornerC", "cornerD", "direction", "directionAmount", "length",
    "fadeInTimeStart", "fadeInTimeEnd", "fadeOutTimeStart", "fadeOutTimeEnd",
    "fadeDistanceStart", "fadeDistanceEnd", "intensity", "flashiness", "densityType",
    "volumeType", "softness", "scaleBySunIntensity",
    "spawnType", "pedType", "group", "interior", "requiredImap", "availableInMpSp",
    "timeTillPedLeaves", "radius", "start", "end", "highPri", "extendedRange",
    "shortRange",
    "ScenarioType", "iTimeStartOverride", "iTimeEndOverride", "Group", "ModelSet",
    "AvailabilityInMpSp", "Flags", "Radius", "TimeTillPedLeaves",
    "expressionDictionaryName", "expressionName", "creatureMetadataName",
    "initialiseOnCollision",
    "radiusInner", "radiusOuter", "spacing", "minScale", "maxScale", "minScaleZ",
    "maxScaleZ", "minZOffset", "maxZOffset", "objectHash",
    "instances", "posn", "colour", "lightType", "groupId", "falloff", "falloffExponent",
    "cullingPlane", "shadowBlur", "padding1", "padding2", "padding3", "volIntensity",
    "volSizeScale", "volOuterColour", "lightHash", "volOuterIntensity", "coronaSize",
    "volOuterExponent", "lightFadeDistance", "shadowFadeDistance", "specularFadeDistance",
    "volumetricFadeDistance", "shadowNearClip", "coronaIntensity", "coronaZBias",
    "tangent", "coneInnerAngle", "coneOuterAngle", "extents", "projectedTextureKey",
    # extension enum members - each verified against the file-carried enum tables
    "METAL_SOLID_LADDER", "METAL_LIGHT_LADDER", "WOODEN_LADDER",
    "LIGHTSHAFT_DENSITYTYPE_CONSTANT", "LIGHTSHAFT_DENSITYTYPE_SOFT",
    "LIGHTSHAFT_DENSITYTYPE_SOFT_SHADOW", "LIGHTSHAFT_DENSITYTYPE_SOFT_SHADOW_HD",
    "LIGHTSHAFT_DENSITYTYPE_LINEAR", "LIGHTSHAFT_DENSITYTYPE_LINEAR_GRADIENT",
    "LIGHTSHAFT_DENSITYTYPE_QUADRATIC", "LIGHTSHAFT_DENSITYTYPE_QUADRATIC_GRADIENT",
    "LIGHTSHAFT_VOLUMETYPE_SHAFT", "LIGHTSHAFT_VOLUMETYPE_CYLINDER",
    "kBoth", "kOnlySp", "kOnlyMp",
    "NoSpawn", "StationaryReactions",
    # Scenario point regions (.ymt) - struct + field names measured over ALL 204 extracted
    # region binaries (probe 2026-07-28: 13 structs, exactly ONE layout each; every candidate
    # matched its stored hash). The reference oracle for tag vocabulary is the 144 name-matched
    # <CScenarioPointRegion> exports. Six hashes stay UNRESOLVED here ON PURPOSE: the oracle
    # itself spells hash_9B1D60AB / hash_44F1B77A / hash_4151BB75 / hash_BA87159C /
    # hash_E529D603 (and never names the ClusterSphere struct 0x3F4F4469), so the degraded
    # hash_ spelling IS the reference spelling - resolving them would DIVERGE from the oracle
    # AND break the emitters below, which address these fields by their hash_ keys.
    # Four of the six ARE hash-pinned (joaat_case candidate search 2026-07-28), banked here
    # for the day a writer needs real names: 0x3F4F4469 = "rage__spdSphere",
    # 0x44F1B77A = "MaxUsers", 0x4151BB75 = "fNextSpawnAttemptDelay",
    # 0xE529D603 = "AccelGridNodeIndices". 0x9B1D60AB (node attachment-prop T_HASH) and
    # 0xBA87159C (cluster bool) remain unknown.
    "CScenarioPointRegion", "CScenarioPoint", "CScenarioPointContainer",
    "CScenarioChainingGraph", "CScenarioChainingNode", "CScenarioChainingEdge",
    "CScenarioChain", "CScenarioPointCluster", "CScenarioEntityOverride",
    "CScenarioPointLookUps", "rage__spdGrid2D",
    "VersionNumber", "Points", "LoadSavePoints", "MyPoints", "EntityOverrides",
    "ChainingGraph", "Nodes", "Edges", "Chains", "AccelGrid", "Clusters", "LookUps",
    "TypeNames", "PedModelSetNames", "VehicleModelSetNames", "GroupNames",
    "InteriorNames", "RequiredIMapNames",
    "iType", "ModelSetId", "iInterior", "iRequiredIMapId", "iProbability",
    "uAvailableInMpSp", "iRadius", "iTimeTillPedLeaves", "iScenarioGroup",
    "vPositionAndDirection",
    "EntityPosition", "EntityType", "ScenarioPoints", "EntityMayNotAlwaysExist",
    "SpecificallyPreventArtPoints",
    "Position", "HasIncomingEdges", "HasOutgoingEdges",
    "NodeIndexFrom", "NodeIndexTo", "Action", "NavMode", "NavSpeed", "EdgeIds",
    "MinCellX", "MaxCellX", "MinCellY", "MaxCellY", "CellDimX", "CellDimY",
    "ClusterSphere", "centerAndRadius",
    # CScenarioPoint flag-enum members (enum 0x29BE262A) - verified against the file-carried
    # enum table; bits 20/27 remain hash-only (never set in any of 162,544 measured values)
    "IgnoreMaxInRange", "OnlySpawnInSameInterior", "SpawnedPedIsArrestable",
    "ActivateVehicleSiren", "AggressiveVehicleDriving", "LandVehicleOnArrival",
    "IgnoreThreatsIfLosNotClear", "EventsInRadiusTriggerDisputes", "AerialVehiclePoint",
    "TerritorialScenario", "EndScenarioIfPlayerWithinRadius",
    "EventsInRadiusTriggerThreatResponse", "TaxiPlaneOnGround", "FlyOffToOblivion",
    "InWater", "AllowInvestigation", "OpenDoor", "PreciseUseTime",
    "NoVehicleSpawnMaxDistance", "ExtendedRange", "ShortRange", "HighPriority",
    "IgnoreLoitering", "UseSearchlight", "CheckCrossedArrivalPlane",
    "UseVehicleFrontForArrival", "IgnoreWeatherRestrictions",
    # CMapData / entities
    # The nine NON-entity containers are named here so the emitter can SEE whether one holds
    # content (see EMPTY_CONTAINERS). Every name PROVEN by hash-match against the root struct
    # descriptors of real ymap - probe 2026-08-03, 6 random binaries, ONE root layout, 26
    # entries: joaat_case(name) == the stored nameHash for all nine. Nothing is guessed here.
    "containerLods", "boxOccluders", "occludeModels", "physicsDictionaries", "instancedData",
    "carGenerators", "LODLightsSOA", "DistantLODLightsSOA",   # timeCycleModifiers: above
    # `LODLights` (0x4F0ED451) - the PSO-container ymap's own array, distinct from the SOA form
    # above. Added 2026-08-07 under the §6y rule and BOTH halves of it hold: it is spelled in an
    # oracle (`<LODLights itemType="CLODLight" />`, ymap/00_base/id2_17_strm_0.ymap.pso.xml) AND
    # joaat_case reproduces the exact hash the binary stores. ⚠ Its siblings `txdRelationships` /
    # `CTxdRelationship` / `DistantLODLights` hash-match too, but NO oracle spells them, so they
    # stay OUT - a hash match alone is guess-and-check, not a witness.
    "LODLights",
    # ...and the STRUCT + FIELD names INSIDE those containers, which is what the emitter needs
    # to write them instead of dropping them. Knowing the container name only told it whether
    # content existed; without these every field decoded as `hash_XXXXXXXX` and no faithful
    # element name could be written.
    # HOW EACH ONE IS PROVEN (probe 2026-08-04): the candidate string is taken from the
    # REFERENCE'S OWN element vocabulary - `reports/snapshots/ymap.json`, mined by
    # tools/schema_miner.py from 11,052 reference ymap XML exports - and then tested by exact
    # case-sensitive joaat preimage against the nameHash the binary descriptor actually stores.
    # 64 of 64 matched. NOTHING here is a guess; a name that had failed to hash-match would have
    # been left unresolved and its container left dropped, because an invented element name is
    # invisible to a consumer in a way an omission marker is not.
    # !! The census is ALPHABETICALLY SORTED, so it supplies names/nesting/attr-vs-text but NOT
    # child order. Order comes from the binary struct descriptor - see CONTAINER_EMITTERS.
    "CCarGen", "orientX", "orientY", "perpendicularLength", "carModel",
    "bodyColorRemap1", "bodyColorRemap2", "bodyColorRemap3", "bodyColorRemap4",
    "popGroup", "livery",
    "CTimeCycleModifier", "minExtents", "maxExtents",
    "BoxOccluder", "iCenterX", "iCenterY", "iCenterZ", "iCosZ", "iLength", "iWidth",
    "iHeight", "iSinZ",
    "OccludeModel", "bmin", "bmax", "dataSize", "verts", "numVertsInBytes", "numTris",
    "rage__fwInstancedMapData", "ImapLink", "PropInstanceList", "GrassInstanceList",
    "rage__fwPropInstanceListDef", "rage__fwGrassInstanceListDef",
    "rage__fwGrassInstanceListDef__InstanceData", "rage__fwContainerLodDef",
    "rage__spdAABB", "BatchAABB", "min", "max", "ScaleRange", "LodFadeStartDist",
    "LodInstFadeRange", "OrientToTerrain", "InstanceList",
    "NormalX", "NormalY", "Color", "Scale", "Ao", "Pad",
    "CLODLight", "timeAndStateFlags", "hash", "coneOuterAngleOrCapExt",
    "CDistantLODLight", "RGBI", "numStreetLights", "category",
    "FloatXYZ", "x", "y", "z",
    # CMloInstanceDef's own fields beyond CEntityDef (2026-08-07, Phase 5 Stage A spot-diff):
    # groupId/floorId were already in this table but never EMITTED; these three had no name at
    # all and decoded as hash_53DF8649 / hash_1F837FB7 / hash_E03B0CAA. Each is joaat_case-exact
    # for the hash its own binary stores AND is spelled by the oracle
    # (_Oracles/ymap/20_dlc_013_mpheist/hei_cs1_railwyb_interior_cs1_14brailway4.ymap.xml) - the
    # §6y standard, both halves. ⭐ These are INTERIOR placements: Stage C reads them.
    "defaultEntitySets", "numExitPortals", "MLOInstflags",
    "CMapData", "CEntityDef", "CMloInstanceDef", "entities", "parent", "contentFlags",
    "streamingExtentsMin", "streamingExtentsMax", "entitiesExtentsMin", "entitiesExtentsMax",
    "archetypeName", "guid", "position", "rotation", "scaleXY", "scaleZ", "parentIndex",
    "childLodDist", "lodLevel", "numChildren", "priorityLevel",
    "ambientOcclusionMultiplier", "artificialAmbientOcclusion", "tintValue",
    # CMapData/block - the export-provenance struct every CMapData ends with. Same proof standard
    # as everything above: each name is an EXACT case-sensitive joaat preimage of the nameHash the
    # binary descriptor stores - block E433D77D, version 68C27E33, exportedBy 76350055,
    # owner 8C060170, time 0F678E23 (flags/name were already in this table). NOTHING guessed.
    # BLAST RADIUS OF ADDING THEM, measured before the edit, because SCHEMA_NAMES renames tags
    # GLOBALLY: all five hashes grepped across every emitted .ytyp.xml / .ymt.xml / .ymap.xml in
    # F:/RUDE_Filebase_v2/_resolved -> 0 files each. No other lane spells these hashes.
    "block", "version", "exportedBy", "owner", "time",
    # enum members - measured from the corpus census, so the symbolic strings are reproducible
    "ASSET_TYPE_UNINITIALIZED", "ASSET_TYPE_FRAGMENT", "ASSET_TYPE_DRAWABLE",
    "ASSET_TYPE_DRAWABLEDICTIONARY", "ASSET_TYPE_ASSETLESS",
    # Listed in the enum's own VALUE order, which is NOT alphabetical: SLOD4 was appended after
    # ORPHANHD, so a later reader "tidying" it up next to SLOD3 would be teaching the wrong tier.
    # THE LADDER WAS MISSING ITS LAST RUNG (2026-08-03). SLOD4 was absent from this table, so
    # 77 entities across 71 ymap emitted `<lodLevel>hash_6F5D45B3</lodLevel>` - an unusable value
    # in the one field that decides which LOD tier an entity belongs to, and invisible to every
    # counter because a hash_ enum member is not a decode failure. MEASURED two independent ways
    # that agree: joaat_case("LODTYPES_DEPTH_SLOD4") == 0x6F5D45B3 (exact preimage, case-sensitive
    # like every schema name here), and the game's OWN per-file enum table 0x4B5ACC2F lists that
    # hash as member value 6 - HD 0, LOD 1, SLOD1 2, SLOD2 3, SLOD3 4, ORPHANHD 5, then this.
    # POPULATION, counted off the emitted .ymap.xml sitting beside all 19,157 ymap binaries and
    # re-decoded from the 71 binaries themselves: 71 files / 77 entities, every occurrence inside
    # <lodLevel>, and every file an h4_* - the mpheist4 (Cayo Perico) DLC, which is the release
    # that introduced the tier and therefore why it is the enum's last-added member.
    "LODTYPES_DEPTH_HD", "LODTYPES_DEPTH_LOD", "LODTYPES_DEPTH_SLOD1", "LODTYPES_DEPTH_SLOD2",
    "LODTYPES_DEPTH_SLOD3", "LODTYPES_DEPTH_ORPHANHD", "LODTYPES_DEPTH_SLOD4",
    "PRI_REQUIRED", "PRI_OPTIONAL_HIGH", "PRI_OPTIONAL_MEDIUM", "PRI_OPTIONAL_LOW",
    # roots we RECOGNISE but have no emitter for, so a refusal can name itself instead of
    # printing hash_%08X: streaming request lists (*_srl.ymt - cutscene prefetch data,
    # measured: gtao_intro_male_srl/mic_1_mcs_1_srl in update.rpf, 2026-07-31)
    "CStreamingRequestRecord",
    # ---- CStreamingRequestRecord emitter vocabulary (*_srl.ymt) ---------------------------
    # struct + field + enum-member names for the two roots wired 2026-08-06. EVERY name below
    # is an EXACT case-sensitive joaat preimage of a nameHash the binary descriptor stores
    # (proven by scratchpad/ymt_verify.py over hc_driver.ymt + hs3f_mul_rp2_srl.ymt); the
    # candidate strings are the ORACLE's own element/attr text - nothing guessed. Six hashes
    # stay UNRESOLVED on purpose (declared in the emitter): the clothData struct-TYPE 0x85559CF3
    # and propInfo struct-TYPE 0xAA681042 (their FIELD names resolve; the type names never appear
    # in the XML), and anchor-enum member 0x27ACDE7D (never used in any oracle sample).
    "CStreamingRequestFrame", "CStreamingRequestCommonSet",
    "Frames", "CommonSets", "NewStyle",
    "AddList", "RemoveList", "PromoteToHDList", "CamPos", "CamDir",
    "CommonAddSets", "Requests",
    # ---- CPedVariationInfo emitter vocabulary (ped .ymt, root hash_16760659) ---------------
    "CPedVariationInfo",
    "bHasTexVariations", "bHasDrawblVariations", "bHasLowLODs", "bIsSuperLOD",
    "availComp", "aComponentData3", "aSelectionSets", "compInfos", "propInfo", "dlcName",
    "CPVComponentData", "CPedSelectionSet", "CComponentInfo",
    "numAvailTex", "aDrawblData3",
    "CPVDrawblData", "propMask", "numAlternatives", "aTexData", "clothData",
    "CPVTextureData", "texId", "distribution", "ownsCloth",
    "pedXml_audioID", "pedXml_audioID2", "pedXml_expressionMods",
    "inclusions", "exclusions", "pedXml_vfxComps", "pedXml_flags",
    "pedXml_compIdx", "pedXml_drawblIdx",
    "numAvailProps", "aPropMetaData", "aAnchors",
    "CPedPropMetaData", "audioId", "expressionMods", "texData", "renderFlags",
    "propFlags", "anchorId", "propId", "stickyness",
    "CPedPropTexData", "inclusionId", "exclusionId",
    "CAnchorProps", "props", "anchor",
    # pedXml_vfxComps enum (0x34B4A664) members - the file-carried table reversed and verified
    "PV_COMP_INVALID", "PV_COMP_HEAD", "PV_COMP_BERD", "PV_COMP_HAIR", "PV_COMP_UPPR",
    "PV_COMP_LOWR", "PV_COMP_HAND", "PV_COMP_FEET", "PV_COMP_TEEF", "PV_COMP_ACCS",
    "PV_COMP_TASK", "PV_COMP_DECL", "PV_COMP_JBIB", "PV_COMP_MAX",
    # renderFlags bitset (0xFB1CEDD7) members
    "PRF_ALPHA", "PRF_DECAL", "PRF_CUTOUT",
    # anchor enum (0xA8F3C93D) members (member 0x27ACDE7D, value 13, stays hash_ - never used)
    "ANCHOR_HEAD", "ANCHOR_EYES", "ANCHOR_EARS", "ANCHOR_MOUTH", "ANCHOR_LEFT_HAND",
    "ANCHOR_RIGHT_HAND", "ANCHOR_LEFT_WRIST", "ANCHOR_RIGHT_WRIST", "ANCHOR_HIP",
    "ANCHOR_LEFT_FOOT", "ANCHOR_RIGHT_FOOT", "ANCHOR_PH_L_HAND", "ANCHOR_PH_R_HAND",
)
SCHEMA_BY_HASH = {joaat_case(n): n for n in SCHEMA_NAMES}


def schema_name(h):
    return SCHEMA_BY_HASH.get(h, "hash_%08X" % h)


PAGE_BITS = {0: 27, 1: 26, 2: 25, 3: 24, 4: 17, 5: 11, 6: 7, 7: 5, 8: 4}
PAGE_MASK = {0: 1, 1: 1, 2: 1, 3: 1, 4: 0x7F, 5: 0x3F, 6: 0xF, 7: 3, 8: 1}


def seg_size(flags):
    f = flags & 0x0FFFFFFF
    base = 0x200 << (f & 0xF)
    return sum(((f >> PAGE_BITS[k]) & PAGE_MASK[k]) * (base << k) for k in range(9))


class MetaFile:
    """RSC7 v2 META: the file carries its OWN schema (structure infos + enum infos + data
    blocks), which is why one generic walker serves ytyp AND ymap - they share this header
    byte for byte. Root is a 1-BASED data-block index at +0x1C.
    """

    def __init__(self, blob):
        import zlib
        if len(blob) < 16 or blob[:4] != b"RSC7":
            raise ValueError("not an RSC7 container")
        _, self.version, sysf, gfxf = struct.unpack_from("<4sIII", blob, 0)
        if self.version != 2:
            raise ValueError("RSC7 version %d is not META (ytyp/ymap), want 2" % self.version)
        ssz, gsz = seg_size(sysf), seg_size(gfxf)
        raw = zlib.decompress(blob[16:], -15)
        self.sys, self.gfx = raw[:ssz], raw[ssz:ssz + gsz]

        self.root_block = self.u32(0x1C)                  # 1-based
        p_struct, p_enum, p_blocks = self.u64(0x20), self.u64(0x28), self.u64(0x30)
        n_struct, n_enum = self.u16(0x48), self.u16(0x4A)
        n_blocks = self.u32(0x4C)
        # +0x40 is a real pointer to an unidentified high-entropy blob present in every file and
        # never represented in the XML. Provably NOT needed to reproduce the XML, so it is
        # skipped - but a WRITER would have to know what it is, so do not drop it silently there.

        self.structs, self.enums, self.blocks = {}, {}, []
        t, o = self.deref(p_struct)
        if t == 5:
            for i in range(n_struct):
                s = self._struct_info(o + i * 32)
                self.structs[s["nameHash"]] = s
        t, o = self.deref(p_enum)
        if t == 5:
            for i in range(n_enum):
                e = self._enum_info(o + i * 24)
                self.enums[e["nameHash"]] = e
        t, o = self.deref(p_blocks)
        if t == 5:
            for i in range(n_blocks):
                self.blocks.append(self._block(o + i * 16))

    # -- primitive access over the system segment
    def u8(self, o):
        return self.sys[o]

    def u16(self, o):
        return struct.unpack_from("<H", self.sys, o)[0]

    def i16(self, o):
        return struct.unpack_from("<h", self.sys, o)[0]

    def u32(self, o):
        return struct.unpack_from("<I", self.sys, o)[0]

    def i32(self, o):
        return struct.unpack_from("<i", self.sys, o)[0]

    def u64(self, o):
        return struct.unpack_from("<Q", self.sys, o)[0]

    def deref(self, tagged):
        """Tagged pointer -> (tag, offset). 5 = system segment, 6 = graphics."""
        if not tagged:
            return None, 0
        return (tagged >> 28) & 0xF, tagged & 0x0FFFFFFF

    def _struct_info(self, o):
        info = dict(nameHash=self.u32(o + 0x00), length=self.i32(o + 0x18),
                    count=self.u16(o + 0x1E), entries=[])
        t, eo = self.deref(self.u64(o + 0x10))
        if t == 5:
            for i in range(info["count"]):
                b = eo + i * 16
                info["entries"].append(dict(
                    nameHash=self.u32(b + 0x00), offset=self.i32(b + 0x04),
                    type=self.u8(b + 0x08), refTypeIdx=self.i16(b + 0x0A),
                    refKey=self.u32(b + 0x0C)))
        return info

    def _enum_info(self, o):
        info = dict(nameHash=self.u32(o + 0x00), members={})
        n = self.i32(o + 0x10)
        t, eo = self.deref(self.u64(o + 0x08))
        if t == 5:
            for i in range(n):
                info["members"][self.i32(eo + i * 8 + 4)] = self.u32(eo + i * 8)
        return info

    def _block(self, o):
        length, ptr = self.i32(o + 0x04), self.u64(o + 0x08)
        t, off = self.deref(ptr)
        buf = self.sys if t == 5 else (self.gfx if t == 6 else b"")
        return dict(structNameHash=self.u32(o + 0x00), length=length,
                    data=buf[off:off + length] if t in (5, 6) else b"")


# entry type codes, measured over 21,293 descriptors across 270 real files
T_STRUCT, T_STRING, T_ARRAY, T_FIXEDARR = 0x05, 0x44, 0x52, 0x50
T_HASH, T_ENUM, T_FLAGS, T_PTR = 0x4A, 0x62, 0x65, 0x07
# 0x60 = BYTE-stored enum, so far seen only on scenario chaining-edge Action/NavMode/NavSpeed
# (204-file probe 2026-07-28). The reference oracle spells all 122,697 occurrences as the raw
# NUMBER (its dictionary reverses none of the 22 member-name hashes), so that is the measured
# rendering; the file-carried member table exists but a symbolic form is UNOBSERVED.
T_ENUM_U8 = 0x60
# 0x59 = RAW BYTE-BUFFER POINTER. Eight bytes in the record: {u32 metaPOINTER, u32 zero}. The
# descriptor carries NO count, and none is needed - the payload fills its target block exactly, so
# the LENGTH COMES FROM THE BLOCK TABLE and nothing is inferred.
# MEASURED over every ytyp/ymap/ymt binary in the whole-game filebase (9,270 files, 2026-08-04):
# type 0x59 is declared in exactly ONE place in the whole corpus - OccludeModel.verts, in 183 ymap
# - and across all 1,702 records: block length == the sibling `dataSize` 1,702/1,702, the target
# block's own struct hash is 0x00000011 (= the u8 primitive) 1,702/1,702, the metaPOINTER's byte
# offset is 0 and the second u32 is 0 in every one. The same shape was reached independently by
# meta_write.py (`T_DATAPTR`, same 0x59, same 8-byte {ptr, 0} descriptor, length from the block).
# What the PAYLOAD holds is measured at the OccludeModel commentary below; the Walker deliberately
# returns the bytes UNINTERPRETED, because splitting them needs sibling fields that value() cannot
# see and inventing a split at this layer would be a guess wearing a decoder's clothes.
T_DATAPTR = 0x59
# 0x40 = INLINE FIXED-LENGTH CHAR ARRAY: `refKey` bytes stored in the struct itself,
# NUL-padded, no pointer. Identified 2026-08-06 from CCompositeEntityType's own member
# table (Name / StartModel / EndModel, all type 0x40 refKey 64, at struct offsets
# 0/136/200) - it was the source of every `unhandled type 0x40` warning (9 per sweep),
# i.e. three real strings silently returning None on every composite record.
T_CHARARRAY = 0x40
# 0x64 = 16-bit ENUM, rendered SYMBOLICALLY as a single member name (like T_ENUM but a u16
# slot). 0x63 = 32-bit BITSET, rendered like T_FLAGS (member VALUE = bit index; stored 0 ->
# empty string, else the set-bit member names). BOTH MEASURED 2026-08-06 on the ped-variation
# .ymt (root CPedVariationInfo, hash_16760659): pedXml_vfxComps is 0x64 in a 2-byte struct slot
# whose enum (0x34B4A664) reverses stored 0 -> PV_COMP_HEAD, matching the oracle; renderFlags is
# 0x63 in a 4-byte slot whose enum (0xFB1CEDD7) reverses stored 1 -> PRF_ALPHA (member value 0 =
# bit 0), matching the oracle's <renderFlags>PRF_ALPHA</renderFlags> vs <renderFlags /> for 0.
# Both were previously the source of `unhandled type 0x63/0x64` warns (the fields decoded to
# None) and appear in NO other lane's binaries - adding them cannot regress ytyp/ymap/ymt.
T_ENUM_U16 = 0x64
T_FLAGS_U32B = 0x63
PRIM = {
    0x01: (1, "?"), 0x10: (1, "b"), 0x11: (1, "B"), 0x12: (2, "h"), 0x13: (2, "H"),
    0x14: (4, "i"), 0x15: (4, "I"), 0x21: (4, "f"), 0x33: (12, "3f"), 0x34: (16, "4f"),
}
ELEM_NAME_HASH = 0x00000100          # a synthetic entry marking the element type; never a field


class Walker:
    """Decodes a META file into plain nested dicts using ONLY the file's own schema."""

    def __init__(self, meta, names=None):
        self.m = meta
        self.names = names or {}      # lowercase-joaat -> asset name, for T_HASH fields
        self.warn = collections.Counter()

    def asset_name(self, h):
        """T_HASH holds a ONE-WAY lowercase joaat of an asset name.

        Unknown -> `hash_XXXXXXXX`, which is deliberately still USABLE: ImportMapArea joins a
        ymap `archetypeName` to a ytyp `name` by string equality, and the same asset hashes the
        same on both sides, so the join survives the degraded form. Only `assetName` must truly
        resolve, because it becomes a FILENAME lookup - and that one is covered by hashing the
        asset filenames the archive itself yields.
        """
        if h == 0:
            return ""
        n = self.names.get(h)
        if n is None:
            self.warn["unresolved asset-name hash"] += 1
            return "hash_%08X" % h
        return n

    def block(self, i):
        return self.m.blocks[i] if 0 <= i < len(self.m.blocks) else None

    @staticmethod
    def metaptr(v):
        """MetaPOINTER u32: low 12 bits = 1-based block index, high 20 = byte offset."""
        return (None, 0) if v == 0 else ((v & 0xFFF) - 1, v >> 12)

    def root(self):
        b = self.block(self.m.root_block - 1)
        if b is None:
            raise ValueError("root block index %d out of range" % self.m.root_block)
        return schema_name(b["structNameHash"]), self.struct(b["structNameHash"], b["data"], 0)

    def struct(self, shash, buf, base):
        s = self.m.structs.get(shash)
        if s is None:
            self.warn["no schema for struct %08X" % shash] += 1
            return {}
        out = {}
        for e in s["entries"]:
            if e["nameHash"] == ELEM_NAME_HASH:
                continue
            out[schema_name(e["nameHash"])] = self.value(s, e, buf, base)
        return out

    def value(self, s, e, buf, base):
        o, t = base + e["offset"], e["type"]
        try:
            if t == T_ARRAY:
                return self.array(s, e, buf, base)
            if t == T_FIXEDARR:
                ed = self.elem(s, e)
                if ed is None or ed["type"] not in PRIM:
                    # COUNTED, NEVER SILENT (2026-08-03): this was a bare `return None`, so a
                    # fixed array of non-primitives dropped the whole field out of the XML with
                    # no warn - structurally invisible, exactly like the T_PTR case below.
                    # 0 occurrences in 499 real ytyp/ymap/ymt, so this is a latch on a latent
                    # path, not a live loss.
                    self.warn["fixed-array element type 0x%02X unsupported"
                              % (ed["type"] if ed else -1)] += 1
                    return None
                sz, f = PRIM[ed["type"]]
                return [struct.unpack_from("<" + f, buf, o + i * sz)[0]
                        for i in range(e["refKey"])]
            if t == T_CHARARRAY:
                raw = bytes(buf[o:o + e["refKey"]])
                return raw.split(b"\x00", 1)[0].decode("latin-1")
            if t == T_STRUCT:
                return self.struct(e["refKey"], buf, o)
            if t == T_DATAPTR:
                return self.dataptr(buf, o)
            if t == T_STRING:
                return self.string(buf, o)
            if t == T_HASH:
                return self.asset_name(struct.unpack_from("<I", buf, o)[0])
            if t in (T_ENUM, T_FLAGS):
                return self.enum(e, struct.unpack_from("<I", buf, o)[0], t)
            if t == T_ENUM_U16:                    # 16-bit enum -> single symbolic member
                return self.enum(e, struct.unpack_from("<H", buf, o)[0], T_ENUM)
            if t == T_FLAGS_U32B:                  # 32-bit bitset -> T_FLAGS rendering
                return self.enum(e, struct.unpack_from("<I", buf, o)[0], T_FLAGS)
            if t == T_ENUM_U8:
                # measured rendering is the raw stored byte (see T_ENUM_U8 above); the enum
                # table is still consulted so an out-of-table value surfaces as a warn
                v = buf[o]
                info = self.m.enums.get(e["refKey"])
                if info is not None and v not in info["members"]:
                    self.warn["enum-u8 value %d absent from its member table" % v] += 1
                return v
            if t in PRIM:
                sz, f = PRIM[t]
                v = struct.unpack_from("<" + f, buf, o)
                return v[0] if len(v) == 1 else v
        except struct.error:
            self.warn["short read"] += 1
            return None
        self.warn["unhandled type 0x%02X" % t] += 1
        return None

    def enum(self, e, stored, t):
        """Rendered SYMBOLICALLY from the file's own enum table.

        Caveat banked from the derivation: every enum in this corpus has members valued 0..N-1,
        so `stored == member.value` and `stored == ordinal` are indistinguishable here. Member
        value is what the record actually stores, so that is what is used.
        ⚠ T_FLAGS multi-bit rendering is UNVERIFIED - all 28 observed instances hold 0. A
        non-zero value therefore returns the raw number rather than a guessed bitset.
        """
        info = self.m.enums.get(e["refKey"])
        if info is None:
            return stored
        if t == T_FLAGS:
            # MEASURED 2026-07-28 (binary<->reference spawn-point pairs): a T_FLAGS member's
            # VALUE is a BIT INDEX, stored 0 renders as the empty string, and a set bit
            # renders as that bit's member name (stored 2 -> "NoSpawn" [bit 1], stored
            # 4 -> "StationaryReactions" [bit 2]).
            # MULTI-BIT JOIN MEASURED 2026-07-28 (scenario-region lane): the reference
            # spells multi-bit values as the member names joined with ", " in ASCENDING
            # bit order ("NoSpawn, ExtendedRange" = bits 1,22) - proven over 12,238
            # multi-bit occurrences / 181 distinct values in the 204-region field diff.
            # A set bit whose member name does NOT resolve still returns the raw NUMBER
            # (honest, not guessed) and is counted in warn; the two hash-only members of
            # the scenario flag enum (bits 20/27) are never set in any measured value.
            if stored == 0:
                return ""
            parts = []
            for bit in range(32):
                if stored & (1 << bit):
                    h = info["members"].get(bit)
                    nm = schema_name(h) if h is not None else "hash_"
                    if nm.startswith("hash_"):
                        self.warn["T_FLAGS value without verified symbolic form: %d"
                                  % stored] += 1
                        return stored
                    parts.append(nm)
            return ", ".join(parts)
        h = info["members"].get(stored)
        return schema_name(h) if h is not None else stored

    def elem(self, s, e):
        i = e["refTypeIdx"]
        return s["entries"][i] if 0 <= i < len(s["entries"]) else None

    def dataptr(self, buf, o):
        """T_DATAPTR (0x59) -> the target block's bytes, RAW and uninterpreted.

        Length is the block's own declared length minus the pointer's byte offset - the payload
        fills its block, which is why the descriptor needs no count (see T_DATAPTR above).
        Returns b"" for a null pointer, which is an honest "no payload" and NOT the same value as
        the None this used to return: None meant "this decoder does not know what this is".

        Every deviation from the measured shape is COUNTED rather than absorbed, so a file that
        does not look like the 1,702 measured records says so instead of quietly handing back a
        differently-shaped buffer.
        """
        pv, hi = struct.unpack_from("<II", buf, o)
        if hi:
            self.warn["data pointer second u32 not zero"] += 1
        if not pv:
            return b""
        bi, bo = self.metaptr(pv)
        b = self.block(bi)
        if b is None:
            self.warn["data pointer targets a missing block"] += 1
            return b""
        if bo > len(b["data"]):
            self.warn["data pointer offset overruns its block"] += 1
            return b""
        return b["data"][bo:]

    def string(self, buf, o):
        pv = struct.unpack_from("<I", buf, o)[0]
        n = struct.unpack_from("<H", buf, o + 8)[0]
        if not pv or not n:
            return ""
        bi, bo = self.metaptr(pv)
        b = self.block(bi)
        if b is None:
            self.warn["string pointer out of range"] += 1
            return ""
        if bo + n > len(b["data"]):
            # An in-range block with an out-of-range OFFSET used to slice short (or to "") and
            # return a truncated/empty name that reads like a legitimately empty field. Counted
            # so a truncated block can never masquerade as blank data. 0 occurrences in 499 real
            # files - a latch, not a live loss.
            self.warn["string overruns its block"] += 1
            return ""
        return b["data"][bo:bo + n].split(b"\x00")[0].decode("utf-8", "replace")

    def array(self, s, e, buf, base):
        o = base + e["offset"]
        pv = struct.unpack_from("<I", buf, o)[0]
        count = struct.unpack_from("<H", buf, o + 8)[0]
        if not count:
            return []
        bi, bo = self.metaptr(pv)
        b = self.block(bi)
        ed = self.elem(s, e)
        if b is None or ed is None:
            self.warn["array pointer/descriptor missing"] += 1
            return []
        et, items = ed["type"], []
        if et == T_PTR:                       # array of struct POINTERS
            for i in range(count):
                p = struct.unpack_from("<I", b["data"], bo + i * 8)[0]
                tbi, tbo = self.metaptr(p)
                tb = self.block(tbi)
                if tb is None:
                    # COUNTED, NEVER SILENT (2026-08-03): the None was appended and then quietly
                    # filtered out by the `if not item: continue` guards in archetypes_from /
                    # entities_from / entityset_from / ext_from, so a dropped entity produced a
                    # SHORTER <entities> list with no error anywhere - indistinguishable from a
                    # map area that legitimately has fewer props. 0 occurrences in 499 real
                    # files, so this is a latch on a latent path.
                    self.warn["array pointer element targets a missing block"] += 1
                items.append(None if tb is None else
                             (schema_name(tb["structNameHash"]),
                              self.struct(tb["structNameHash"], tb["data"], tbo)))
        elif et == T_STRUCT:                  # array of INLINE structs
            sub = self.m.structs.get(ed["refKey"])
            stride = sub["length"] if sub else 0
            for i in range(count):
                items.append((schema_name(ed["refKey"]),
                              self.struct(ed["refKey"], b["data"], bo + i * stride)))
        elif et == 0x33:
            # MEASURED (LOG "MLO INTERIORS"): VECTOR3 **array elements** have a 16-byte
            # stride, not the 12 bytes an inline VEC3 field occupies. Each record is
            # x,y,z float32 plus a 4th float; portal corners hold the constant
            # 0x7F800001 there, which the reference XML spells literally as NaN, so all
            # FOUR floats are kept. Proven over 381 files / 12,948 corners, 0 exceptions.
            for i in range(count):
                items.append(struct.unpack_from("<4f", b["data"], bo + i * 16))
        elif et in PRIM:
            sz, f = PRIM[et]
            for i in range(count):
                items.append(struct.unpack_from("<" + f, b["data"], bo + i * sz)[0])
        elif et == T_HASH:
            for i in range(count):
                items.append(self.asset_name(
                    struct.unpack_from("<I", b["data"], bo + i * 4)[0]))
        else:
            self.warn["array element type 0x%02X" % et] += 1
        return items

# Measured over 1,707 corpus ytyp: assetType is the SYMBOLIC name in 99.99% of rows (the numeric
# "-1" occurs 13 times and is passed through verbatim). Only ASSET_TYPE_DRAWABLE is consumed today;
# ImportMapArea deliberately skips the rest (ydd/fragment archetypes stay proxy cubes) - about 51%
# of all archetypes, so a "missing" mesh after import is usually this, not a decode failure.
ASSET_TYPES = ("ASSET_TYPE_DRAWABLE", "ASSET_TYPE_DRAWABLEDICTIONARY", "ASSET_TYPE_FRAGMENT",
               "ASSET_TYPE_ASSETLESS")


def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def f32(x):
    """Round-trip through IEEE single. These files store float32, so the text must spell THAT."""
    return struct.unpack("<f", struct.pack("<f", float(x)))[0]


def fmt_num(v):
    """MEASURED float spelling: **7 significant digits, widening to 9 only when 7 does not
    round-trip back to the identical float32.** Uppercase E, %G's own scientific threshold.

    ⛔ THIS WAS A REAL SHIPPED DEFECT (found 2026-07-27). It used `repr(float(v))`, which spells
    the full double - `14.15194034576416` where the reference writes `9.836426`-style 7-digit text -
    so EVERY non-integral value in every emitted ytyp/ymap disagreed with the reference.
    ⚠⚠ AND BOTH OF MY GATES WERE BLIND TO IT, which is the more important lesson:
      * the round-trip harness parses reference text into STRINGS and re-emits those same strings,
        and fmt_num passes strings through untouched - so it is lossless by construction and can
        never see a formatting bug. It only exercises the emitter's SHAPE.
      * `verify_binary` compared numbers with a float TOLERANCE, so correct values spelled
        differently scored as matches.
    A defect visible to neither gate is the signature of testing the wrong thing. `verify_binary`
    now counts TEXT-exact separately from value-equal so this class of bug cannot hide again.
    """
    if isinstance(v, str):
        return v
    if v is None:
        return "0"
    if isinstance(v, bool):
        # type 0x01 fields (door/ladder/spawn booleans). MEASURED: the reference spells
        # lowercase true/false; str(True) would emit "True". Must precede the int branch,
        # because bool is an int subclass.
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    f = f32(v)
    if f != f:
        return "NaN"          # measured: the reference writes NaN literally (portal corner w)
    if f == 0.0:
        return "0"            # also normalises -0.0, which the reference never spells
    s = _sig(f, 7)
    if f32(float(s)) != f:
        s = _sig(f, 9)
    return s


def _sig(f, digits):
    """`f` to `digits` significant digits, **ties AWAY FROM ZERO**, in %G's fixed-vs-scientific
    style (scientific iff exponent < -4 or >= digits).

    ⚠ Why not just `"%.*G"`: C/Python round ties HALF-TO-EVEN, the reference rounds ties away from
    zero. That single difference was the whole residual after the 7/9-digit rule went in - 94
    components spelled `...562` where the reference says `...563`. `Decimal(float)` is the exact
    binary value, so quantising it with ROUND_HALF_UP reproduces the reference's choice.
    """
    d = decimal.Decimal(f)
    if d == 0:
        return "0"
    exp = d.adjusted()
    r = d.quantize(decimal.Decimal(1).scaleb(exp - digits + 1), rounding=decimal.ROUND_HALF_UP)
    exp = r.adjusted()                      # rounding can carry (9.99 -> 10.0)
    if exp < -4 or exp >= digits:
        mant = format(r.scaleb(-exp), "f").rstrip("0").rstrip(".")
        return "%sE%s%02d" % (mant, "+" if exp >= 0 else "-", abs(exp))
    s = format(r, "f")
    return s.rstrip("0").rstrip(".") if "." in s else s


def scalar_list(tag, vals, indent):
    """MEASURED rendering for whitespace-separated scalar arrays (e.g. a room's attachedObjects):
    empty -> self-closing; <=10 values -> one line inside the element; >=11 -> newline, then TEN
    per line indented one deeper, then newline + indent before the close tag. Emitting <Item>
    children instead would be mis-parsed by the consumer."""
    if not vals:
        return ["%s<%s />" % (indent, tag)]
    if len(vals) <= 10:
        return ["%s<%s>%s</%s>" % (indent, tag, " ".join(str(int(x)) for x in vals), tag)]
    out = ["%s<%s>" % (indent, tag)]
    for i in range(0, len(vals), 10):
        out.append("%s %s" % (indent, " ".join(str(int(x)) for x in vals[i:i + 10])))
    out.append("%s</%s>" % (indent, tag))
    return out


def num_list(tag, vals, indent):
    """Whitespace-separated NUMERIC array - scalar_list's measured layout law, but formatted
    through fmt_num instead of int().

    WHY A SECOND FUNCTION INSTEAD OF REUSING scalar_list: scalar_list spells every value
    `str(int(x))`. Two of CLODLight's eight members are float32 arrays, and they are genuinely
    fractional - MEASURED over all 625 lodlights-family ymap in the whole-game filebase
    (2026-08-04): 29,663 of 311,414 falloff / falloffExponent values, 9.5%, across 313 files, are
    non-integral. Reusing scalar_list would have truncated every one of them to an integer and
    still produced well-formed XML - the exact profile of a loss no gate sees. scalar_list is
    left byte-for-byte alone because the ytyp/ymt lanes are measured against it.

    THE LAYOUT LAW IS RE-MEASURED, not assumed (2026-08-04). scalar_list's `<=10 on one line,
    then TEN per line indented one deeper` was measured on the scenario oracle; it is confirmed
    again here on the SURVIVING reference exports, and for floats as well as ints:
    `ymt` EdgeIds / CommonAddSets, `yld` Unknown60 / Unknown20, `ycd` Values - all render exactly
    ten values per line, single-space separated, continuation lines one indent deeper than the
    tag. (`yld` CompositeTransform and `ypt` Data break the rule at 4 and 12 per line, but both
    are STRUCTURED blocks - matrix rows and interleaved vertex channels - not scalar arrays, and
    neither shape occurs in CMapData.)
    """
    if not vals:
        return ["%s<%s />" % (indent, tag)]
    s = [fmt_num(v) for v in vals]
    if len(s) <= 10:
        return ["%s<%s>%s</%s>" % (indent, tag, " ".join(s), tag)]
    out = ["%s<%s>" % (indent, tag)]
    for i in range(0, len(s), 10):
        out.append("%s %s" % (indent, " ".join(s[i:i + 10])))
    out.append("%s</%s>" % (indent, tag))
    return out


def pick(d, key, default):
    """`dict.get(k, default)` is WRONG here: a parsed field is PRESENT-but-None when the source tag
    was absent, so .get returns None and hands it straight to the formatter."""
    v = d.get(key)
    return default if v is None else v


def require(d, key, ctx):
    """For MLO / time-archetype fields there is NO honest default: the field exists in every
    measured schema (probe 2026-07-28 over all 272 resolved MLO binaries found exactly one
    layout per struct), so a missing key means the DECODE failed, and writing a made-up 0
    would forge bytes into the output. Refuse loudly instead."""
    v = d.get(key)
    if v is None:
        raise ValueError("%s: required field %r missing from decode" % (ctx, key))
    return v


def _vec(tag, v, indent, comps="xyz"):
    if v is None:
        v = ("0",) * len(comps)
    attrs = " ".join('%s="%s"' % (c, fmt_num(v[i])) for i, c in enumerate(comps))
    return "%s<%s %s />" % (indent, tag, attrs)


def _val(tag, v, indent):
    return '%s<%s value="%s" />' % (indent, tag, fmt_num(v))


def _txt(tag, v, indent):
    if v is None or v == "":
        return "%s<%s />" % (indent, tag)
    return "%s<%s>%s</%s>" % (indent, tag, esc(v), tag)


def _txt_pair(tag, v, indent):
    """A type-0x40 INLINE char array (refKey-sized storage lives in the struct itself, so
    the string is PRESENT even when empty): the reference spells an EMPTY one as an
    open+close pair - `<StartModel></StartModel>` (des_gassign oracle, 2026-08-08) - while
    a zero HASH field (0x4A) in the SAME record spells self-closing (`<PtFxAssetName />`).
    Same absent-vs-empty family as the ymap block owner/exportedBy rule. Populated forms
    render identically to `_txt`."""
    if v is None or v == "":
        return "%s<%s></%s>" % (indent, tag, tag)
    return "%s<%s>%s</%s>" % (indent, tag, esc(v), tag)


# ---------------------------------------------------------------- ytyp
def archetype_xml(a):
    """One `<Item>`. `a` is a plain dict; an absent key takes the reference default, so a partial
    decode still yields a file the importer accepts rather than a malformed one."""
    L = ['  <Item type="%s">' % esc(pick(a, "type", "CBaseArchetypeDef"))]
    L.append(_val("lodDist", pick(a, "lodDist", 0), "   "))
    L.append(_val("flags", pick(a, "flags", 0), "   "))
    L.append(_val("specialAttribute", pick(a, "specialAttribute", 0), "   "))
    L.append(_vec("bbMin", a.get("bbMin"), "   "))
    L.append(_vec("bbMax", a.get("bbMax"), "   "))
    L.append(_vec("bsCentre", a.get("bsCentre"), "   "))
    L.append(_val("bsRadius", pick(a, "bsRadius", 0), "   "))
    L.append(_val("hdTextureDist", pick(a, "hdTextureDist", 0), "   "))
    L.append(_txt("name", a.get("name"), "   "))
    L.append(_txt("textureDictionary", a.get("textureDictionary"), "   "))
    L.append(_txt("clipDictionary", a.get("clipDictionary"), "   "))
    L.append(_txt("drawableDictionary", a.get("drawableDictionary"), "   "))
    L.append(_txt("physicsDictionary", a.get("physicsDictionary"), "   "))
    # assetType is SIGNED when it is numeric. The module comment above already recorded that a
    # numeric "-1" occurs and is "passed through verbatim" - but the decode hands back an
    # UNSIGNED dword, so verbatim spelled it 4294967295 where the reference writes -1. Caught
    # 2026-08-07 by grading the corpus against wave-2 oracles (bh1_emissive_test.ytyp, 3 rows).
    # Symbolic values (ASSET_TYPE_*) are strings and pass through untouched.
    # ⛔ ABSENT IS NOT EMPTY. Some CBaseArchetypeDef carry no assetType/assetName at all - the
    # keys are simply not in the struct - and the reference OMITS both elements. We emitted
    # `<assetType />` `<assetName />`, which is a FORGED EMPTY: it reads as "provided, and empty"
    # to a consumer that cannot tell the difference. Same defect family as the ymap containers,
    # and the same trap as the MLO fields: the projection in archetype_from sets every key with
    # .get(), so absence arrives here as None and only None can distinguish it.
    # Measured on des_gassign (1 archetype) and sp_flightschool_props (7): the decode has neither
    # key and the oracle writes neither element - 0 occurrences of each.
    _at = a.get("assetType")
    if _at is not None:
        if isinstance(_at, int) and _at > 0x7FFFFFFF:
            _at = _at - 0x100000000
        L.append(_txt("assetType", _at, "   "))
    if a.get("assetName") is not None:
        L.append(_txt("assetName", a.get("assetName"), "   "))
    L += extensions_xml(a.get("extensions") or [], "   ")
    # padding0/padding1 are NOT emitted: measured against the 2026-08-05 oracle set,
    # ZERO archetype Items carry them (they were exporter-synthesised by an OLDER the reference exporter
    # build - the stale-oracle reproducibility sample caught exactly this drift).
    # CExtensionDefLightEffect keeps its padding1/2/3 - that is a different struct,
    # measured 12/12 against the same oracles.
    kind = pick(a, "type", "CBaseArchetypeDef")
    if kind == "CTimeArchetypeDef":
        # measured: every CTimeArchetypeDef in the corpus (3,980 items) carries timeFlags,
        # placed after padding1. No default: an absent value is a decode gap, not a zero.
        L.append(_val("timeFlags", require(a, "timeFlags", "CTimeArchetypeDef"), "   "))
    if kind == "CMloArchetypeDef":
        L += mlo_xml(a)
    L.append("  </Item>")
    return L


def _container(tag, items, item_type, indent, render):
    """An interchange typed container: empty -> self-closing WITH its itemType attribute
    (measured on portals/entitySets/timeCycleModifiers across the reference corpus; an
    empty <rooms> is UNOBSERVED - every MLO has >= 2 rooms - so its empty form follows
    the same measured pattern rather than a guess of its own)."""
    if not items:
        return ['%s<%s itemType="%s" />' % (indent, tag, item_type)]
    out = ["%s<%s itemType=\"%s\">" % (indent, tag, item_type)]
    for it in items:
        out += render(it, indent + " ")
    out.append("%s</%s>" % (indent, tag))
    return out


def room_xml(r, ind):
    """One CMloRoomDef <Item> (NO type attribute - measured, unlike entities). `name` is a
    literal string in the binary (entry type 0x44), not a hash."""
    f = ind + " "
    L = ["%s<Item>" % ind]
    L.append(_txt("name", r.get("name"), f))
    L.append(_vec("bbMin", r.get("bbMin"), f))
    L.append(_vec("bbMax", r.get("bbMax"), f))
    L.append(_val("blend", require(r, "blend", "CMloRoomDef"), f))
    L.append(_txt("timecycleName", r.get("timecycleName"), f))
    L.append(_txt("secondaryTimecycleName", r.get("secondaryTimecycleName"), f))
    L.append(_val("flags", require(r, "flags", "CMloRoomDef"), f))
    L.append(_val("portalCount", require(r, "portalCount", "CMloRoomDef"), f))
    L.append(_val("floorId", require(r, "floorId", "CMloRoomDef"), f))
    L.append(_val("exteriorVisibiltyDepth",
                  require(r, "exteriorVisibiltyDepth", "CMloRoomDef"), f))
    L += scalar_list("attachedObjects", r.get("attachedObjects") or [], f)
    L.append("%s</Item>" % ind)
    return L


def portal_xml(p, ind):
    """One CMloPortalDef <Item>. Corners render as text items `x, y, z, w` where w is the
    constant NaN (0x7F800001) - spelled literally, measured on 12,948 reference corners."""
    f = ind + " "
    L = ["%s<Item>" % ind]
    for t in ("roomFrom", "roomTo", "flags", "mirrorPriority", "opacity", "audioOcclusion"):
        L.append(_val(t, require(p, t, "CMloPortalDef"), f))
    corners = p.get("corners") or []
    if corners:
        L.append("%s<corners>" % f)
        for c in corners:
            body = c if isinstance(c, str) else ", ".join(fmt_num(x) for x in c)
            L.append("%s <Item>%s</Item>" % (f, body))
        L.append("%s</corners>" % f)
    else:
        # unobserved in the corpus (every portal has exactly 4 corners); the empty form
        # follows the corpus-wide empty-container pattern rather than a guess of its own
        L.append("%s<corners />" % f)
    L += scalar_list("attachedObjects", p.get("attachedObjects") or [], f)
    L.append("%s</Item>" % ind)
    return L


def entityset_xml(s, ind):
    """One CMloEntitySet <Item>: `locations` is strictly parallel to `entities` (one u32 per
    entity, measured 1,963/1,963 sets); the entities are full CEntityDef records."""
    f = ind + " "
    L = ["%s<Item>" % ind]
    L.append(_txt("name", s.get("name"), f))
    L += scalar_list("locations", s.get("locations") or [], f)
    ents = s.get("entities") or []
    if ents:
        L.append("%s<entities>" % f)
        for e in ents:
            L += entity_xml(e, f + " ")
        L.append("%s</entities>" % f)
    else:
        L.append("%s<entities />" % f)
    L.append("%s</Item>" % ind)
    return L


def tcmod_xml(t, ind):
    """One CMloTimeCycleModifier <Item>. `sphere` is a VEC4 (x,y,z,w=radius); percentage and
    range are float32 in the binary, so fmt_num spells them exactly as the reference does."""
    f = ind + " "
    L = ["%s<Item>" % ind]
    L.append(_txt("name", t.get("name"), f))
    L.append(_vec("sphere", t.get("sphere"), f, "xyzw"))
    for k in ("percentage", "range", "startHour", "endHour"):
        L.append(_val(k, require(t, k, "CMloTimeCycleModifier"), f))
    L.append("%s</Item>" % ind)
    return L


# Extension emit specs: tag order and render form per type, MEASURED from the reference
# oracle (every occurrence of each type shares one tag order; forms: val = value attr,
# txt = element text, vec3/vec4 = x/y/z[/w] attrs, list = space-joined scalars as text,
# instances = nested CLightAttrDef <Item>s). The names spelled here double as the
# schema-hash sources, so a typo would surface as a hash_ key, not silent data loss.
EXT_SPECS = {
    "CExtensionDefAudioCollisionSettings": (
        ("name", "txt"), ("offsetPosition", "vec3"), ("settings", "txt")),
    "CExtensionDefAudioEmitter": (
        ("name", "txt"), ("offsetPosition", "vec3"), ("offsetRotation", "vec4"),
        ("effectHash", "val")),
    "CExtensionDefBuoyancy": (("name", "txt"), ("offsetPosition", "vec3")),
    "CExtensionDefDoor": (
        ("name", "txt"), ("offsetPosition", "vec3"), ("enableLimitAngle", "val"),
        ("startsLocked", "val"), ("canBreak", "val"), ("limitAngle", "val"),
        ("doorTargetRatio", "val"), ("audioHash", "txt")),
    "CExtensionDefExplosionEffect": (
        ("name", "txt"), ("offsetPosition", "vec3"), ("offsetRotation", "vec4"),
        ("explosionName", "txt"), ("boneTag", "val"), ("explosionTag", "val"),
        ("explosionType", "val"), ("flags", "val")),
    "CExtensionDefExpression": (
        ("name", "txt"), ("offsetPosition", "vec3"),
        ("expressionDictionaryName", "txt"), ("expressionName", "txt"),
        ("creatureMetadataName", "txt"), ("initialiseOnCollision", "val")),
    "CExtensionDefLadder": (
        ("name", "txt"), ("offsetPosition", "vec3"), ("bottom", "vec3"), ("top", "vec3"),
        ("normal", "vec3"), ("materialType", "txt"), ("template", "txt"),
        ("canGetOffAtTop", "val"), ("canGetOffAtBottom", "val")),
    "CExtensionDefLightEffect": (
        ("name", "txt"), ("offsetPosition", "vec3"), ("instances", "instances")),
    "CExtensionDefLightShaft": (
        ("name", "txt"), ("offsetPosition", "vec3"), ("cornerA", "vec3"),
        ("cornerB", "vec3"), ("cornerC", "vec3"), ("cornerD", "vec3"),
        ("direction", "vec3"), ("directionAmount", "val"), ("length", "val"),
        ("fadeInTimeStart", "val"), ("fadeInTimeEnd", "val"), ("fadeOutTimeStart", "val"),
        ("fadeOutTimeEnd", "val"), ("fadeDistanceStart", "val"),
        ("fadeDistanceEnd", "val"), ("color", "hex"), ("intensity", "val"),
        ("flashiness", "val"), ("flags", "val"), ("densityType", "txt"),
        ("volumeType", "txt"), ("softness", "val"), ("scaleBySunIntensity", "val")),
    "CExtensionDefParticleEffect": (
        ("name", "txt"), ("offsetPosition", "vec3"), ("offsetRotation", "vec4"),
        ("fxName", "txt"), ("fxType", "val"), ("boneTag", "val"), ("scale", "val"),
        ("probability", "val"), ("flags", "val"), ("color", "hex")),
    "CExtensionDefProcObject": (
        ("name", "txt"), ("offsetPosition", "vec3"), ("radiusInner", "val"),
        ("radiusOuter", "val"), ("spacing", "val"), ("minScale", "val"),
        ("maxScale", "val"), ("minScaleZ", "val"), ("maxScaleZ", "val"),
        ("minZOffset", "val"), ("maxZOffset", "val"), ("objectHash", "val"),
        ("flags", "val")),
    "CExtensionDefSpawnPoint": (
        ("name", "txt"), ("offsetPosition", "vec3"), ("offsetRotation", "vec4"),
        ("spawnType", "txt"), ("pedType", "txt"), ("group", "txt"), ("interior", "txt"),
        ("requiredImap", "txt"), ("availableInMpSp", "txt"), ("probability", "val"),
        ("timeTillPedLeaves", "val"), ("radius", "val"), ("start", "val"),
        ("end", "val"), ("flags", "txt"), ("highPri", "val"), ("extendedRange", "val"),
        ("shortRange", "val")),
    # ⭐ The ONE extension type whose name is not a C-prefixed class: it refused 22 ymap
    # conversions as `unknown extension type 'hash_32818195'` until 2026-08-07. The preimage came
    # from the GAME's own plaintext data - common.rpf :: data/cloth/global_cloth_custombounds.xml,
    # whose ROOT ELEMENT is the class name - and joaat_case() reproduces 0x32818195 exactly. Its
    # ten member names self-verify against the hashes the 22 carriers store in their own schema
    # blocks. (Search note for the next hunt: the name contains no "Extension", so a
    # pattern-scoped scan MISSES it; the exhaustive identifier sweep over the game's text files
    # is what found it.) The element ORDER below is the game XML's own order, and the oracle
    # confirms it byte-for-byte.
    "rage__phVerletClothCustomBounds": (
        ("name", "txt"), ("CollisionData", "clothbounds")),
    "CExtensionDefSpawnPointOverride": (
        ("name", "txt"), ("offsetPosition", "vec3"), ("ScenarioType", "txt"),
        ("iTimeStartOverride", "val"), ("iTimeEndOverride", "val"), ("Group", "txt"),
        ("ModelSet", "txt"), ("AvailabilityInMpSp", "txt"), ("Flags", "txt"),
        ("Radius", "val"), ("TimeTillPedLeaves", "val")),
    "CExtensionDefWindDisturbance": (
        ("name", "txt"), ("offsetPosition", "vec3"), ("offsetRotation", "vec4"),
        ("disturbanceType", "val"), ("boneTag", "val"), ("size", "vec4"),
        ("strength", "val"), ("flags", "val")),
}
# CLightAttrDef: the LightEffect instance record. posn/colour/cullingPlane/volOuterColour/
# direction/tangent/extents are FIXED arrays (type 0x50) rendered as space-joined text.
LIGHT_INSTANCE_SPEC = (
    ("posn", "list"), ("colour", "list"), ("flashiness", "val"), ("intensity", "val"),
    ("flags", "val"), ("boneTag", "val"), ("lightType", "val"), ("groupId", "val"),
    ("timeFlags", "val"), ("falloff", "val"), ("falloffExponent", "val"),
    ("cullingPlane", "list"), ("shadowBlur", "val"), ("padding1", "val"),
    ("padding2", "val"), ("padding3", "val"), ("volIntensity", "val"),
    ("volSizeScale", "val"), ("volOuterColour", "list"), ("lightHash", "val"),
    ("volOuterIntensity", "val"), ("coronaSize", "val"), ("volOuterExponent", "val"),
    ("lightFadeDistance", "val"), ("shadowFadeDistance", "val"),
    ("specularFadeDistance", "val"), ("volumetricFadeDistance", "val"),
    ("shadowNearClip", "val"), ("coronaIntensity", "val"), ("coronaZBias", "val"),
    ("direction", "list"), ("tangent", "list"), ("coneInnerAngle", "val"),
    ("coneOuterAngle", "val"), ("extents", "list"), ("projectedTextureKey", "val"))


# One capsule inside rage__phVerletClothCustomBounds/CollisionData. Field order and forms are
# the carriers' own schema order (OwnerName STRING @0, Rotation vec4 @16, Position vec3 @32,
# Normal vec3 @48, four f32 @64..76, Flags FLAGS @80) - identical in all 22 carriers, and the
# order the game's global_cloth_custombounds.xml lists them in.
CLOTH_BOUND_SPEC = (
    ("OwnerName", "txt"), ("Rotation", "vec4"), ("Position", "vec3"), ("Normal", "vec3"),
    ("CapsuleRadius", "val"), ("CapsuleLen", "val"), ("CapsuleHalfHeight", "val"),
    ("CapsuleHalfWidth", "val"), ("Flags", "txt"))


def _list_txt(tag, v, indent):
    """A fixed-count scalar array as element text: `<posn>0 0 0.042</posn>`. Parse-side
    strings pass through verbatim; decode-side lists are fmt_num-joined."""
    body = v if isinstance(v, str) else " ".join(fmt_num(x) for x in v)
    return "%s<%s>%s</%s>" % (indent, tag, body, tag)


def _spec_fields(d, spec, f, ctx):
    L = []
    for tag, form in spec:
        if form == "val":
            L.append(_val(tag, require(d, tag, ctx), f))
        elif form == "hex":
            # MEASURED: `color` is the ONLY hex-spelled value in the whole ytyp oracle
            # (27,714/27,714 as 0x + eight UPPERCASE digits; every other tag is decimal)
            v = require(d, tag, ctx)
            L.append(_val(tag, v if isinstance(v, str) else "0x%08X" % v, f))
        elif form == "txt":
            v = d.get(tag)
            if v is None:
                raise ValueError("%s: required field %r missing from decode" % (ctx, tag))
            L.append(_txt(tag, v if isinstance(v, str) else fmt_num(v), f))
        elif form == "vec3":
            L.append(_vec(tag, require(d, tag, ctx), f))
        elif form == "vec4":
            L.append(_vec(tag, require(d, tag, ctx), f, "xyzw"))
        elif form == "list":
            L.append(_list_txt(tag, require(d, tag, ctx), f))
        elif form == "clothbounds":
            # `<CollisionData itemType="rage__phCapsuleBoundDef">` holding one `<Item>` per
            # capsule. itemType = the element-struct hash 0x656F0305 the carriers store;
            # joaat_case('rage__phCapsuleBoundDef') reproduces it, and the oracle
            # (_Oracles/ymap/00_base/bh1_47_joshhse_burnt.ymap.xml, exported 2026-08-07)
            # spells exactly that. Empty renders self-closing, the corpus-wide empty-container
            # style used by `instances` directly below.
            items = d.get("CollisionData") or []
            if not items:
                L.append('%s<CollisionData itemType="rage__phCapsuleBoundDef" />' % f)
            else:
                L.append('%s<CollisionData itemType="rage__phCapsuleBoundDef">' % f)
                for li in items:
                    # Array-of-struct items decode as (structName, fields) - the same shape the
                    # `extensions` container itself uses, NOT the bare dict `instances` yields.
                    li = li[1] if isinstance(li, tuple) else li
                    L.append("%s <Item>" % f)
                    L += _spec_fields(li, CLOTH_BOUND_SPEC, f + "  ",
                                      "rage__phCapsuleBoundDef")
                    L.append("%s </Item>" % f)
                L.append("%s</CollisionData>" % f)
        elif form == "instances":
            insts = d.get("instances") or []
            if not insts:
                # unobserved in the corpus (every LightEffect carries instances); rendered
                # in the corpus-wide empty-container style rather than a guess of its own
                L.append('%s<instances itemType="CLightAttrDef" />' % f)
            else:
                L.append('%s<instances itemType="CLightAttrDef">' % f)
                for li in insts:
                    L.append("%s <Item>" % f)
                    L += _spec_fields(li, LIGHT_INSTANCE_SPEC, f + "  ",
                                      "CLightAttrDef")
                    L.append("%s </Item>" % f)
                L.append("%s</instances>" % f)
    return L


def ext_xml(x, ind):
    """One `<Item type="CExtensionDef...">`. An UNKNOWN extension type refuses loudly:
    silently dropping it would forge "this asset has no such extension" into the output."""
    kind = x.get("type")
    spec = EXT_SPECS.get(kind)
    if spec is None:
        raise ValueError("unknown extension type %r - refusing to emit a guess" % kind)
    L = ['%s<Item type="%s">' % (ind, esc(kind))]
    L += _spec_fields(x, spec, ind + " ", kind)
    L.append("%s</Item>" % ind)
    return L


def extensions_xml(exts, indent):
    """The `<extensions>` container: empty -> self-closing WITHOUT itemType (measured -
    unlike rooms/portals); non-empty -> plain open tag with typed Items."""
    if not exts:
        return ["%s<extensions />" % indent]
    L = ["%s<extensions>" % indent]
    for x in exts:
        L += ext_xml(x, indent + " ")
    L.append("%s</extensions>" % indent)
    return L


def mlo_xml(a):
    """The CMloArchetypeDef tail: mloFlags + the five containers, in the measured order
    entities, rooms, portals, entitySets, timeCycleModifiers. The archetype's own
    `<entities>` renders untyped/self-closing when empty (measured, e.g. v_int_75)."""
    L = [_val("mloFlags", require(a, "mloFlags", "CMloArchetypeDef"), "   ")]
    ents = a.get("entities") or []
    if ents:
        L.append("   <entities>")
        for e in ents:
            L += entity_xml(e, "    ")
        L.append("   </entities>")
    else:
        L.append("   <entities />")
    L += _container("rooms", a.get("rooms") or [], "CMloRoomDef", "   ", room_xml)
    L += _container("portals", a.get("portals") or [], "CMloPortalDef", "   ", portal_xml)
    L += _container("entitySets", a.get("entitySets") or [], "CMloEntitySet", "   ",
                    entityset_xml)
    L += _container("timeCycleModifiers", a.get("timeCycleModifiers") or [],
                    "CMloTimeCycleModifier", "   ", tcmod_xml)
    return L


def ytyp_dropped_from(root, w=None):
    """`extensions` and `dependencies` are populated in 0 of 930 real ytyp binaries
    (census 2026-08-03) and 0 of the 1,707 reference exports, so their hardcoded empty
    form is HONEST. compositeEntityTypes is SERIALISED since 2026-08-06 (composite_xml,
    oracle-shaped off des_jewel_cab4) - nothing left to count here; the renderer itself
    markers any sub-shape it has no oracle witness for (populated effectsData)."""
    _ = (root, w)
    return {}


def composite_xml(items):
    """<compositeEntityTypes> - shape read off the des_jewel_cab4 oracle (2026-08-06):
    Name/StartModel/EndModel are inline char-arrays (walker type 0x40, mixed case
    preserved); an EMPTY 0x40 spells as an open+close pair while a zero 0x4A hash
    field spells self-closing (the des_gassign witness pair - see `_txt_pair`).
    Populated effectsData
    (2026-08-08): field set + order read off the des_fib_ceiling oracle, all member
    names joaat-verified against the stored hashes (SCHEMA_NAMES block); records
    arrive fully decoded from the walker, so this is pure serialisation."""
    f, g, h = "  ", "   ", "    "
    L = [' <compositeEntityTypes itemType="CCompositeEntityType">']
    for _kind, c in items:
        L.append(f + "<Item>")
        L.append(_txt_pair("Name", c.get("Name"), g))
        L.append(_val("lodDist", pick(c, "lodDist", 0), g))
        L.append(_val("flags", pick(c, "flags", 0), g))
        L.append(_val("specialAttribute", pick(c, "specialAttribute", 0), g))
        L.append(_vec("bbMin", c.get("bbMin"), g))
        L.append(_vec("bbMax", c.get("bbMax"), g))
        L.append(_vec("bsCentre", c.get("bsCentre"), g))
        L.append(_val("bsRadius", pick(c, "bsRadius", 0), g))
        L.append(_txt_pair("StartModel", c.get("StartModel"), g))
        L.append(_txt_pair("EndModel", c.get("EndModel"), g))
        L.append(_txt("StartImapFile", c.get("StartImapFile"), g))
        L.append(_txt("EndImapFile", c.get("EndImapFile"), g))
        L.append(_txt("PtFxAssetName", c.get("PtFxAssetName"), g))
        anims = c.get("Animations") or []
        if anims:
            L.append(g + '<Animations itemType="CCompEntityAnims">')
            for _ak, a in anims:
                L.append(h + "<Item>")
                L.append(_txt_pair("AnimDict", a.get("AnimDict"), h + " "))
                L.append(_txt_pair("AnimName", a.get("AnimName"), h + " "))
                L.append(_txt_pair("AnimatedModel", a.get("AnimatedModel"), h + " "))
                L.append(_val("punchInPhase", pick(a, "punchInPhase", 0), h + " "))
                L.append(_val("punchOutPhase", pick(a, "punchOutPhase", 0), h + " "))
                fx = a.get("effectsData") or []
                if fx:
                    i5, i6, i7 = h + " ", h + "  ", h + "   "
                    L.append(i5 + '<effectsData itemType="CCompEntityEffectsData">')
                    for _fk, r in fx:
                        L.append(i6 + "<Item>")
                        L.append(_val("fxType", pick(r, "fxType", 0), i7))
                        L.append(_vec("fxOffsetPos", r.get("fxOffsetPos"), i7))
                        L.append(_vec("fxOffsetRot", r.get("fxOffsetRot"), i7,
                                      comps="xyzw"))
                        L.append(_val("boneTag", pick(r, "boneTag", 0), i7))
                        L.append(_val("startPhase", pick(r, "startPhase", 0), i7))
                        L.append(_val("endPhase", pick(r, "endPhase", 0), i7))
                        L.append(_val("ptFxIsTriggered",
                                      pick(r, "ptFxIsTriggered", False), i7))
                        L.append(_txt_pair("ptFxTag", r.get("ptFxTag"), i7))
                        L.append(_val("ptFxScale", pick(r, "ptFxScale", 0), i7))
                        L.append(_val("ptFxProbability",
                                      pick(r, "ptFxProbability", 0), i7))
                        L.append(_val("ptFxHasTint", pick(r, "ptFxHasTint", False), i7))
                        L.append(_val("ptFxTintR", pick(r, "ptFxTintR", 0), i7))
                        L.append(_val("ptFxTintG", pick(r, "ptFxTintG", 0), i7))
                        L.append(_val("ptFxTintB", pick(r, "ptFxTintB", 0), i7))
                        L.append(_vec("ptFxSize", r.get("ptFxSize"), i7))
                        L.append(i6 + "</Item>")
                    L.append(i5 + "</effectsData>")
                else:
                    L.append(h + ' <effectsData itemType="CCompEntityEffectsData" />')
                L.append(h + "</Item>")
            L.append(g + "</Animations>")
        else:
            L.append(g + '<Animations itemType="CCompEntityAnims" />')
        L.append(f + "</Item>")
    L.append(" </compositeEntityTypes>")
    return L


def ytyp_xml(name, archetypes, dropped=None, composite=None):
    L = ['<?xml version="1.0" encoding="UTF-8"?>', "<CMapTypes>", " <extensions />"]
    if archetypes:
        L.append(" <archetypes>")
        for a in archetypes:
            L += archetype_xml(a)
        L.append(" </archetypes>")
    else:
        L.append(" <archetypes />")
    L.append(_txt("name", name, " "))
    L.append(" <dependencies />")
    if composite:
        L += composite_xml(composite)
    else:
        L.append(' <compositeEntityTypes itemType="CCompositeEntityType" />')
    L.append("</CMapTypes>")
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------- ymap
def entity_xml(e, ind="  "):
    """One CEntityDef <Item>. `ind` is the Item's own indent: "  " inside a ymap (the
    original call sites, unchanged), deeper when nested inside an MLO archetype."""
    f = ind + " "
    L = ['%s<Item type="%s">' % (ind, esc(pick(e, "type", "CEntityDef")))]
    L.append(_txt("archetypeName", e.get("archetypeName"), f))
    L.append(_val("flags", pick(e, "flags", 0), f))
    L.append(_val("guid", pick(e, "guid", 0), f))
    L.append(_vec("position", e.get("position"), f))
    L.append(_vec("rotation", pick(e, "rotation", ("0", "0", "0", "1")), f, "xyzw"))
    L.append(_val("scaleXY", pick(e, "scaleXY", 1), f))
    L.append(_val("scaleZ", pick(e, "scaleZ", 1), f))
    L.append(_val("parentIndex", pick(e, "parentIndex", -1), f))
    L.append(_val("lodDist", pick(e, "lodDist", 0), f))
    L.append(_val("childLodDist", pick(e, "childLodDist", 0), f))
    L.append(_txt("lodLevel", e.get("lodLevel"), f))
    L.append(_val("numChildren", pick(e, "numChildren", 0), f))
    L.append(_txt("priorityLevel", e.get("priorityLevel"), f))
    L += extensions_xml(e.get("extensions") or [], f)
    L.append(_val("ambientOcclusionMultiplier", pick(e, "ambientOcclusionMultiplier", 255), f))
    L.append(_val("artificialAmbientOcclusion", pick(e, "artificialAmbientOcclusion", 255), f))
    L.append(_val("tintValue", pick(e, "tintValue", 0), f))
    # padding0 NOT emitted - zero CEntityDef Items in the 2026-08-05 oracle set carry it
    # ⭐ CMloInstanceDef adds FIVE fields after tintValue (2026-08-07). The walker decoded all
    # five all along - groupId/floorId by name, the other three as hash_53DF8649/1F837FB7/
    # E03B0CAA - and the emitter simply closed the Item without them, so every interior
    # PLACEMENT in the corpus was missing its group/floor/entity-set data. Found by the Stage A
    # stratified spot-diff (no ledger oracle covered an MLO instance); field order and forms are
    # the oracle's. Emitted ONLY for the subclass, so a plain CEntityDef is untouched.
    if pick(e, "type", "CEntityDef") == "CMloInstanceDef":
        L.append(_val("groupId", pick(e, "groupId", 0), f))
        L.append(_val("floorId", pick(e, "floorId", 0), f))
        sets = e.get("defaultEntitySets")
        if sets:
            L.append("%s<defaultEntitySets>" % f)
            for s in sets:
                L.append("%s <Item>%s</Item>" % (f, esc(s if isinstance(s, str) else str(s))))
            L.append("%s</defaultEntitySets>" % f)
        else:
            L.append("%s<defaultEntitySets />" % f)
        L.append(_val("numExitPortals", pick(e, "numExitPortals", 0), f))
        L.append(_val("MLOInstflags", pick(e, "MLOInstflags", 0), f))
    L.append("%s</Item>" % ind)
    return L


# The measured EMPTY spelling of the nine non-entity CMapData containers, in reference child
# order - keyed by container so ymap_xml can tell an honest empty apart from a drop.
#
# ** EIGHT OF THE NINE ARE NOW SERIALISED FOR REAL (seven on 2026-08-04, occludeModels on
# 2026-08-05) - see CONTAINER_EMITTERS below. This tuple is no longer "containers we cannot write";
# it is the empty form each one takes when the binary genuinely holds none of it. The one still
# unwritten is containerLods (0 records in the whole corpus, so its empty form is never wrong).
#
# HARD - A FORGED EMPTY IS DATA LOSS THE CONSUMER CANNOT SEE (2026-08-03). This tuple used to be
# appended VERBATIM to every emitted ymap, so `<carGenerators itemType="CCarGen" />` was written
# even when the binary held 11 of them and the Walker had decoded all 11: "the binary has none",
# "we dropped it" and "we never decoded it" all rendered as the same self-closing element, and not
# one counter fired.
# MEASURED over ALL 7,563 ymap binaries in the whole-game filebase (2026-08-03, 0 decode errors,
# counts taken from the decoded root through container_records):
#   physicsDictionaries 4,715 files /  33,266   instancedData         386 /  66,481
#   carGenerators         700 files /  18,295   timeCycleModifiers    390 /   4,733
#   boxOccluders          146 files /  15,120   occludeModels         173 /   1,535
#   LODLightsSOA          320 files / 154,914   DistantLODLightsSOA   320 / 154,914
#   containerLods           0 files (never populated anywhere in this corpus)
#   ^ the DistantLODLightsSOA cell was overwritten with 304 / 153,582 by the correction below and
#     is RESTORED here; that correction is withdrawn - see it for why.
# = 449,258 records across 5,929 of 7,563 files (78%). 1,215 ymap hold ZERO entities and 1,203 of
# those carry content in a dropped container - i.e. one ymap in six converted to a syntactically
# valid, COMPLETELY CONTENTLESS file and was counted as a successful conversion.
#
# TWO CORRECTIONS TO THE ROW ABOVE (2026-08-04), because a census is only worth what its scope is:
#  * [WITHDRAWN - THE CORRECTION WAS THE ERROR. Kept in full because the way it went wrong is the
#    lesson.] It read: "DistantLODLightsSOA was recorded as 320 / 154,914, a duplicate of the
#    LODLightsSOA row beside it. RE-MEASURED over every lodlights-named ymap in the same 7,563
#    (624 files - the only files that can hold either container): 320 files/154,914 for
#    LODLightsSOA, which reproduces exactly, and 304 files/153,582 for DistantLODLightsSOA, which
#    does not. The two containers are also DISJOINT - 0 of the 624 carry both - so equal counts
#    were never expected. Total corrected 449,258 -> 447,926."
#    RE-RUN AT THAT EXACT SCOPE (2026-08-04): 304 / 153,582 reproduces, so the arithmetic was
#    fine - the FILE FILTER was not. "the only files that can hold either container" is false:
#    `"lodlights" in name` matches lodlights_* and distlodlights_* but MISSES the 16 ymap named
#    *_distantlights.ymap (prologue_distantlights, hei_carrier_distantlights,
#    apa_ch2_04_mansion_*_distantlights, ...), which hold 1,332 DistantLODLightsSOA records
#    between them. 304 + 16 = 320 files and 153,582 + 1,332 = 154,914 records, so the ORIGINAL
#    row was right and the total goes back to 449,258. The two containers ARE disjoint (0 of
#    8,076 carry both, re-measured) and their totals ARE equal, because R* ships lodlights_X and
#    distlodlights_X as PAIRS describing one light set at two LOD tiers - equal counts are
#    evidence OF the pairing, not of a copy-paste. Both agents reasoned from a shape ("equal
#    numbers look copied") instead of from the population, and a name-pattern filter is exactly
#    where a census silently stops being a census. Full scope, no filter, is the row below.
#  * The scope line read "00_base + 10_update + 20_dlc". It is 00_base (4,588) + 10_update (2,975)
#    ONLY; 20_dlc's 513 ymap were never censused. That matters more than it looks - the DLC is
#    where the map's newest data lives (all 71 LODTYPES_DEPTH_SLOD4 ymap are in 20_dlc/mpheist4,
#    and 20_dlc/053_mpheist4/island_lodlights.ymap alone adds 793 LODLightsSOA records on top of
#    the figures above), so every number here is a LOWER BOUND on the real corpus.
#
# RE-MEASURED AT FULL SCOPE - ALL 8,076 ymap, 00_base + 10_update + 20_dlc (2026-08-04, 0 decode
# failures). This is the BEFORE number for the serialisation work below, and it supersedes both
# rows above because it is the first census taken over the whole corpus:
#   physicsDictionaries 4,867 files /  34,225   instancedData         396 /  69,142
#   carGenerators         702 files /  18,342   timeCycleModifiers    396 /   5,288
#   boxOccluders          155 files /  15,414   occludeModels         183 /   1,702
#   LODLightsSOA          321 files / 155,707   DistantLODLightsSOA   321 / 155,707
#   containerLods           0 files (never populated - the struct is not even registered in any
#                                    ymap's schema table, so its empty form can never be wrong)
# = 455,527 records. The instancedData row counts grass BATCHES; the batches hold 30,535,076
# individual instances, which is the number that actually leaves the emitter.
#
# THE RULE: empty in the binary -> the measured empty element (honest). Content in the binary and
# no emitter -> OMIT the element and leave a marker, because `FindChildNode` is
# direct-children-only and returns nullptr for a missing element (LOG "ImportMapArea's ACTUAL XML
# contract"), so an omission reads as "not provided" while a forged empty reads as "provided, and
# it is empty".
#
# ** THE "NO EMITTER" HALF IS NOW MOSTLY CLOSED (2026-08-04) - see CONTAINER_EMITTERS. The block
# above used to end "serialising them for real needs a reference ymap XML export and this machine
# has none, so writing one now would be a guess." The ORACLE EXISTS, just not as XML: the reference
# corpus was mined into `reports/snapshots/ymap.json` (tools/schema_miner.py, 11,052 reference ymap
# exports) before it was deleted, and it records every element path, its nesting, whether each
# field is a value= attribute / an x,y,z attribute / element text, and each container's itemType.
# What it does NOT record is CHILD ORDER, because to_json() writes `sorted(stats.items())`.
# Order is supplied by a SEPARATE measured rule - see CONTAINER_EMITTERS.
EMPTY_CONTAINERS = (
    ("containerLods", (' <containerLods itemType="rage__fwContainerLodDef" />',)),
    ("boxOccluders", (' <boxOccluders itemType="BoxOccluder" />',)),
    ("occludeModels", (' <occludeModels itemType="OccludeModel" />',)),
    ("physicsDictionaries", (" <physicsDictionaries />",)),
    ("instancedData", (" <instancedData>",
                       "  <ImapLink />",
                       '  <PropInstanceList itemType="rage__fwPropInstanceListDef" />',
                       '  <GrassInstanceList itemType="rage__fwGrassInstanceListDef" />',
                       " </instancedData>")),
    ("timeCycleModifiers", (' <timeCycleModifiers itemType="CTimeCycleModifier" />',)),
    ("carGenerators", (' <carGenerators itemType="CCarGen" />',)),
    ("LODLightsSOA", (" <LODLightsSOA>",
                      '  <direction itemType="FloatXYZ" />',
                      "  <falloff />", "  <falloffExponent />", "  <timeAndStateFlags />",
                      "  <hash />", "  <coneInnerAngle />", "  <coneOuterAngleOrCapExt />",
                      "  <coronaIntensity />",
                      " </LODLightsSOA>")),
    ("DistantLODLightsSOA", (" <DistantLODLightsSOA>",
                             '  <position itemType="FloatXYZ" />', "  <RGBI />",
                             '  <numStreetLights value="0" />', '  <category value="0" />',
                             " </DistantLODLightsSOA>")),
)


def _omitted(container, n, ind=" "):
    """The marker that replaces a container this emitter cannot write faithfully.

    An XML COMMENT is deliberate: UE's own parser culls comments before tokenising
    (`Unreal's XmlFile.cpp (XmlParser), Cull-any-text-node logic`, "Cull any text
    inside of comments" -> WhiteOut), so the marker is invisible to FindChildNode - the element
    is genuinely ABSENT for a consumer - while a human reading the file is told what was lost and
    how much. Never emit "--" inside it; that is illegal in an XML comment.
    """
    return ["%s<!-- QUARRY DROPPED %s: %d record(s) present in this binary, NOT serialised by "
            "this emitter. The element is omitted, not written empty, so it cannot be read as "
            "'the binary holds none'. -->" % (ind, container, n)]


def container_records(v):
    """Record count of one decoded CMapData container.

    A plain array counts its items. The struct containers (instancedData / LODLightsSOA /
    DistantLODLightsSOA) hold PARALLEL arrays, so the record count is the LONGEST member, not the
    sum: distlodlights_small017.ymap has 401 lights spread over 2 arrays, not 802 records.
    """
    if isinstance(v, list):
        return len(v)
    if isinstance(v, dict):
        return max([len(x) for x in v.values() if isinstance(x, list)] or [0])
    return 0


# ------------------------------------------------ the seven serialised CMapData containers
#
# WHERE EVERY PART OF THESE SHAPES COMES FROM (nothing below is invented; 2026-08-04):
#
#  ELEMENT NAMES  - the reference's own vocabulary in `reports/snapshots/ymap.json`, then each one
#                   CONFIRMED by exact case-sensitive joaat preimage against the nameHash the
#                   binary descriptor stores. 64/64 matched (see the SCHEMA_NAMES block). A name
#                   that had failed to match would have left its container dropped.
#  NESTING        - the census path (`CMapData/<c>/Item/<field>`), which agrees with the binary
#                   struct graph in every case.
#  attr vs TEXT   - the census: `attrs=['value']` -> `<f value="x" />`, `attrs=['x','y','z']` ->
#                   `<f x= y= z= />`, `text=['string']` -> element text, `text=['numlist']` ->
#                   the num_list law. `<Item>` carries NO type attribute here - the miner rewrites
#                   `Item` to `Item[T]` when a type attribute exists, and every census path under
#                   these containers is a bare `Item` (unlike `entities/Item[CEntityDef]`).
#  CHILD ORDER    - THE BINARY STRUCT-DESCRIPTOR ORDER, which is a MEASURED rule, not an
#                   assumption. Tested by pairing 928 surviving reference ytyp exports with their
#                   binaries and comparing, per struct, the XML child order against the descriptor
#                   order: 23 struct types, every one with exactly ONE observed XML order across
#                   all 928 files, and ZERO relative-order disagreements. The only deviation is
#                   that CBaseArchetypeDef / CTimeArchetypeDef / CMloArchetypeDef / CEntityDef
#                   emit exporter-synthesised `padding0` / `padding1` elements the descriptor does
#                   not carry - extra elements, never a reordering.
#                   THE RULE IS THEN CONFIRMED THREE MORE TIMES INSIDE THIS VERY LANE: the
#                   already-measured empty forms of instancedData (ImapLink, PropInstanceList,
#                   GrassInstanceList), LODLightsSOA (direction, falloff, falloffExponent,
#                   timeAndStateFlags, hash, coneInnerAngle, coneOuterAngleOrCapExt,
#                   coronaIntensity) and DistantLODLightsSOA (position, RGBI, numStreetLights,
#                   category) reproduce their binary descriptor order EXACTLY - and those empty
#                   forms were measured off real reference ymap XML, so this is ymap evidence,
#                   not ytyp evidence carried across.
#
# !! WHAT IS STILL DEGRADED, AND IT IS NOT SMALL. T_HASH fields hold a one-way lowercase joaat and
# resolve only against the names the user's own extraction yields, so where the reference spells a
# string this writes `hash_XXXXXXXX`. MEASURED over all 8,076 ymap in the whole-game filebase:
#   physicsDictionaries entries  10,828 / 34,225 unresolved (32%)   - ybn dictionaries not extracted
#   timeCycleModifiers name       5,283 /  5,288 unresolved (99.9%) - timecycle names live in
#                                 timecycle_mods_*.xml, which is NOT an archive filename, so this
#                                 table can never resolve them; a name source would have to be added
#   carGenerators carModel/popGroup - vehicle model + popgroup names, same story
# This is honest and counted (`unresolved asset-name hash` in the Walker's warn), and it is
# strictly more information than dropping the record - the extents, hours, flags and geometry all
# survive - but do NOT read a round-tripped file as byte-faithful to the reference.
#
# HOW THIS WAS VERIFIED, because `quarry.py regress` CANNOT SEE THIS LANE (its fixture project
# holds zero ytyp/ymap/ymt binaries, so a green regress run says nothing about meta2xml). Four
# measurements, all over the whole-game filebase, 2026-08-04:
#  1. RECORD COUNTS. Every ymap decoded -> expected count per container off the value model; the
#     emitted XML then re-read with a stock ElementTree iterparse (an independent reader keyed on
#     the FULL element path, so a field written at the wrong depth counts as a different path and
#     shows up as a miss). 8,066 files, 16 paths, 32,234,352 records: EMITTED == DECODED on every
#     path, 0 files disagreeing, and 0 XML parse failures.
#     (10 of 8,076 do not emit at all - a PRE-EXISTING refusal, `unknown extension type
#     hash_32818195`, in the entity extension path. Not touched here; still open.)
#  2. SHAPE COMPLETENESS. Every element path the reference census records under these nine
#     containers vs every path this emitter produces: 90 census paths, 82 emitted, and the 8
#     missing are ALL occludeModels/* - the container deliberately left dropped. ZERO paths are
#     emitted that the reference never had, and ZERO attribute-set disagreements across all 82
#     shared paths (value= vs x,y,z vs w vs itemType vs bare text).
#     RE-MEASURED 2026-08-05 with occludeModels serialised: 9 census paths exist under
#     CMapData/occludeModels (the container + Item + its 7 children) and all 9 are now emitted,
#     with 0 emitted that the census never had - so this reads 90/90.
#  3. NO COLLATERAL. ytyp and ymt output is BYTE-IDENTICAL across this change - 600 ytyp + 124
#     ymt re-emitted and sha256-compared before/after - which matters because adding names to
#     SCHEMA_NAMES changes schema_name() globally and could have renamed a tag in another lane.
#     The ytyp oracle diff also still reads 366,250/366,250 text-exact.
#  4. COST. The seven containers add 39.2M lines / 1.03 GB across a 1,152-file sample. 93% of that
#     is grass: 35 files exceed +10 MB and the largest single ymap goes 1.4 KB -> 49.4 MB. Those
#     1.4 KB files are the "syntactically valid, COMPLETELY CONTENTLESS" case named above - the
#     size IS the defect being repaired - but a 49 MB ymap XML is a real operational fact for
#     whatever reads these, and it is recorded here rather than quietly capped. A cap would be the
#     forged-empty defect again, one level up.


def _floatxyz_array(tag, items, ind):
    """A FloatXYZ array (LODLightsSOA/direction, DistantLODLightsSOA/position).

    MEASURED (census, 11,052 reference ymap): the container carries itemType="FloatXYZ" and each
    <Item> spells x/y/z as CHILD ELEMENTS with a value attribute - `CMapData/LODLightsSOA/
    direction/Item/x` has attrs=['value']. That is the OPPOSITE of CEntityDef's
    `<position x= y= z= />`, and it follows the binary: FloatXYZ is a real 3-field struct with its
    own descriptor here, not a VEC3 field. Writing the attribute form would have been the natural
    guess and it would have been wrong."""
    items = _inline_items(items)
    if not items:
        return ['%s<%s itemType="FloatXYZ" />' % (ind, tag)]
    L = ['%s<%s itemType="FloatXYZ">' % (ind, tag)]
    for d in items:
        L.append("%s <Item>" % ind)
        for c in "xyz":
            L.append(_val(c, pick(d, c, 0), ind + "  "))
        L.append("%s </Item>" % ind)
    L.append("%s</%s>" % (ind, tag))
    return L


def physdict_xml(v, ind=" "):
    """<physicsDictionaries> - a flat T_HASH array, each entry a ybn dictionary name.

    NO itemType on the container (census: `CMapData/physicsDictionaries` has no attrs in any of
    11,052 files) and each entry is bare element text. This one matters most per line of code:
    the in-game world-collision pass loads ybn through exactly this list (LOG 2026-07-24,
    Matt-witnessed), so every map this emitter round-tripped previously lost all of its
    collision references."""
    L = ["%s<physicsDictionaries>" % ind]
    for s in v or []:
        L.append(_txt("Item", s, ind + " "))
    L.append("%s</physicsDictionaries>" % ind)
    return L


def cargen_item_xml(d, ind):
    f = ind + " "
    L = ["%s<Item>" % ind]
    L.append(_vec("position", d.get("position"), f))
    L.append(_val("orientX", pick(d, "orientX", 0), f))
    L.append(_val("orientY", pick(d, "orientY", 0), f))
    L.append(_val("perpendicularLength", pick(d, "perpendicularLength", 0), f))
    L.append(_txt("carModel", d.get("carModel"), f))
    L.append(_val("flags", pick(d, "flags", 0), f))
    for i in range(1, 5):
        L.append(_val("bodyColorRemap%d" % i, pick(d, "bodyColorRemap%d" % i, -1), f))
    L.append(_txt("popGroup", d.get("popGroup"), f))
    L.append(_val("livery", pick(d, "livery", -1), f))
    L.append("%s</Item>" % ind)
    return L


def cargens_xml(v, ind=" "):
    return _container("carGenerators", _inline_items(v), "CCarGen", ind, cargen_item_xml)


def map_tcmod_item_xml(d, ind):
    """One CMapData <timeCycleModifiers> Item. NOT the same struct as the MLO
    CMloTimeCycleModifier that tcmod_xml writes - that one is (name, sphere, percentage, range,
    startHour, endHour); this one is (name, minExtents, maxExtents, percentage, range, startHour,
    endHour) and its name is a HASH, not a string."""
    f = ind + " "
    L = ["%s<Item>" % ind]
    L.append(_txt("name", d.get("name"), f))
    L.append(_vec("minExtents", d.get("minExtents"), f))
    L.append(_vec("maxExtents", d.get("maxExtents"), f))
    L.append(_val("percentage", pick(d, "percentage", 0), f))
    L.append(_val("range", pick(d, "range", 0), f))
    L.append(_val("startHour", pick(d, "startHour", 0), f))
    L.append(_val("endHour", pick(d, "endHour", 0), f))
    L.append("%s</Item>" % ind)
    return L


def map_tcmods_xml(v, ind=" "):
    return _container("timeCycleModifiers", _inline_items(v), "CTimeCycleModifier", ind,
                      map_tcmod_item_xml)


BOX_OCCLUDER_FIELDS = ("iCenterX", "iCenterY", "iCenterZ", "iCosZ",
                       "iLength", "iWidth", "iHeight", "iSinZ")


def boxoccluder_item_xml(d, ind):
    L = ["%s<Item>" % ind]
    for k in BOX_OCCLUDER_FIELDS:
        L.append(_val(k, pick(d, k, 0), ind + " "))
    L.append("%s</Item>" % ind)
    return L


def boxoccluders_xml(v, ind=" "):
    return _container("boxOccluders", _inline_items(v), "BoxOccluder", ind, boxoccluder_item_xml)


# ---------------------------------------------------------------- occludeModels
# THE ENCODING THAT BLOCKED THIS CONTAINER IS NOW MEASURED, NOT GUESSED (2026-08-05).
# Everything about the PAYLOAD was already decoded and proven (see check_occlude_models and the
# CONTAINER_EMITTERS commentary); the single missing fact was how the reference spells `<verts>`
# as text, and the file above this one refused to guess it. Matt supplied five reference ymap
# exports that carry the container -
#   the (retired) pre-plan reference export set, ymap/
#     apa_ss1_occl_00 (10 items), apa_ss1_occl_03 (10), bh1_occl_00 (10),
#     bkr_id1_occl_02 (6), hei_bh1_occl_00 (10)
# - and the spelling is READ OFF ALL 46 ITEMS, not off one:
#   * child order bmin, bmax, dataSize, verts, numVertsInBytes, numTris, flags  46/46
#     (= the binary struct-descriptor order, so it also obeys the measured CHILD ORDER rule)
#   * `dataSize` == the RAW BYTE COUNT of the verts text, exactly                46/46
#     (dataSize ranges 873..3930 across the five files; it is NOT a character count and NOT a
#     vertex count - numVertsInBytes is the vertex half of the same blob)
#   * every token is exactly two UPPERCASE hex digits, single-space separated    46/46
#     (156,915 tokens; zero lowercase, zero 0x prefixes, zero separators but the single space)
#   * exactly 32 BYTES PER LINE, the final line holding the remainder            46/46
#     (last-line lengths observed 1,2,3,4,5,7,8,9,10,12,14,15,16,17,19,20,22,24,26,27,29,30,31,32
#     - i.e. the whole residue range, so the 32 is a hard wrap, not a coincidence of these files;
#     a ds%32==0 record ends on a FULL 32-byte line with no trailing blank line, seen 4 times)
#   * the byte lines sit at 4 spaces, one deeper than `<verts>` at 3             46/46
#     which is the same one-space-per-level ladder every other element here uses
# So this is hex - the candidate the old note said "would fit what survives" - and the guess it
# refused to make is now a reading. NOTHING ELSE about the container changed; the bytes written
# are the Walker's T_DATAPTR payload verbatim, uninterpreted.
OCCLUDE_HEX_PER_LINE = 32


def _hexdump_lines(raw, ind, per_line=OCCLUDE_HEX_PER_LINE):
    """Opaque byte payload -> the measured text form: space-separated uppercase two-digit hex,
    `per_line` bytes per line, each line at `ind`. No padding on the last line."""
    return ["%s%s" % (ind, " ".join("%02X" % b for b in raw[i:i + per_line]))
            for i in range(0, len(raw), per_line)]


def occlude_model_item_xml(d, ind):
    """One OccludeModel <Item>. The <verts> payload is the raw block the T_DATAPTR field points
    at, re-spelled as hex - never re-derived from the decoded vertices/indices, so a wrong reading
    of the vertex split cannot leak into the bytes this writes."""
    f = ind + " "
    raw = d.get("verts")
    L = ["%s<Item>" % ind]
    L.append(_vec("bmin", d.get("bmin"), f))
    L.append(_vec("bmax", d.get("bmax"), f))
    # the binary's OWN dataSize field, not len(raw): the two are only ever written together when
    # they already agree (occlude_models_unserialisable refuses the container otherwise), so
    # substituting the measured length here could only ever hide a decode fault.
    L.append(_val("dataSize", pick(d, "dataSize", 0), f))
    L.append("%s<verts>" % f)
    L += _hexdump_lines(raw, f + " ")
    L.append("%s</verts>" % f)
    L.append(_val("numVertsInBytes", pick(d, "numVertsInBytes", 0), f))
    L.append(_val("numTris", pick(d, "numTris", 0), f))
    L.append(_val("flags", pick(d, "flags", 0), f))
    L.append("%s</Item>" % ind)
    return L


def occludemodels_xml(v, ind=" "):
    return _container("occludeModels", _inline_items(v), "OccludeModel", ind,
                      occlude_model_item_xml)


def occlude_models_unserialisable(items):
    """Reason this decoded occludeModels container may NOT be written, or None.

    A PRECONDITION, not a validator: the three cases below are ones where writing the container
    would need an invention, so the container is DROPPED with its marker instead and the reason is
    counted. Anything else wrong with the payload (index width, the numTris high bit, the
    bmin/bmax agreement) is caught by check_occlude_models and does NOT block writing, because
    this emitter copies the bytes verbatim and never re-encodes them - a misread of the vertex
    split cannot change one byte of the output.

    * not bytes           - nothing to spell; the T_DATAPTR decode failed.
    * len != dataSize     - the two are written as separate elements and a consumer reads
                            dataSize to size the parse, so emitting them in disagreement would
                            produce a file that is internally inconsistent and still well-formed.
                            MEASURED equal on 3,019/3,019 records over the whole unfiltered
                            F:/RUDE_Filebase_v2 ymap set, so this never fires today.
    * empty payload       - the reference's spelling of an EMPTY <verts> is UNOBSERVED: all 1,994
                            records in the 11,052-file census carry one, min numVertsInBytes 36,
                            and none of the 46 read items is empty. `<verts />` would be the house
                            style and it would still be a guess.
    """
    for it in _inline_items(items):
        raw = it.get("verts")
        if not isinstance(raw, bytes):
            return "verts did not decode to bytes"
        if len(raw) != pick(it, "dataSize", 0):
            return "verts payload length != dataSize"
        if not raw:
            return "verts payload is empty and the empty spelling is unobserved"
    return None


def lodlights_soa_xml(v, ind=" "):
    """CLODLight: eight PARALLEL arrays, so the record count is the longest member (see
    container_records), and any member may be shorter than the others - each renders its own
    measured empty form when it is."""
    v = v or {}
    f = ind + " "
    L = ["%s<LODLightsSOA>" % ind]
    L += _floatxyz_array("direction", v.get("direction"), f)
    for tag in ("falloff", "falloffExponent", "timeAndStateFlags", "hash",
                "coneInnerAngle", "coneOuterAngleOrCapExt", "coronaIntensity"):
        L += num_list(tag, v.get(tag) or [], f)
    L.append("%s</LODLightsSOA>" % ind)
    return L


def distlodlights_soa_xml(v, ind=" "):
    v = v or {}
    f = ind + " "
    L = ["%s<DistantLODLightsSOA>" % ind]
    L += _floatxyz_array("position", v.get("position"), f)
    L += num_list("RGBI", v.get("RGBI") or [], f)
    L.append(_val("numStreetLights", pick(v, "numStreetLights", 0), f))
    L.append(_val("category", pick(v, "category", 0), f))
    L.append("%s</DistantLODLightsSOA>" % ind)
    return L


def grass_instance_xml(d, ind):
    """One rage__fwGrassInstanceListDef__InstanceData <Item>.

    Every value is spelled RAW - the stored integer, not a decoded world-space float. MEASURED:
    the census value inventories for Ao (22..255), NormalX/NormalY (23..231) and Scale span the
    u8 range, and Position is a fixed[3] u16 rendered as a numlist. Normalising here would put
    plausible-looking wrong numbers in every instance."""
    f = ind + " "
    L = ["%s<Item>" % ind]
    L += num_list("Position", d.get("Position") or [], f)
    L.append(_val("NormalX", pick(d, "NormalX", 0), f))
    L.append(_val("NormalY", pick(d, "NormalY", 0), f))
    L += num_list("Color", d.get("Color") or [], f)
    L.append(_val("Scale", pick(d, "Scale", 0), f))
    L.append(_val("Ao", pick(d, "Ao", 0), f))
    L += num_list("Pad", d.get("Pad") or [], f)
    L.append("%s</Item>" % ind)
    return L


def grass_batch_xml(d, ind):
    """One rage__fwGrassInstanceListDef <Item> (a grass BATCH).

    BatchAABB is a nested rage__spdAABB whose min/max are VEC4 - the census records a `w`
    attribute on both, always 0 - so they take the four-component attribute form while
    ScaleRange, a plain VEC3 field, takes three."""
    f = ind + " "
    aabb = d.get("BatchAABB") or {}
    L = ["%s<Item>" % ind]
    L.append("%s<BatchAABB>" % f)
    L.append(_vec("min", aabb.get("min"), f + " ", "xyzw"))
    L.append(_vec("max", aabb.get("max"), f + " ", "xyzw"))
    L.append("%s</BatchAABB>" % f)
    L.append(_vec("ScaleRange", d.get("ScaleRange"), f))
    L.append(_txt("archetypeName", d.get("archetypeName"), f))
    L.append(_val("lodDist", pick(d, "lodDist", 0), f))
    L.append(_val("LodFadeStartDist", pick(d, "LodFadeStartDist", 0), f))
    L.append(_val("LodInstFadeRange", pick(d, "LodInstFadeRange", 0), f))
    L.append(_val("OrientToTerrain", pick(d, "OrientToTerrain", 0), f))
    L += _container("InstanceList", _inline_items(d.get("InstanceList")),
                    "rage__fwGrassInstanceListDef__InstanceData", f, grass_instance_xml)
    L.append("%s</Item>" % ind)
    return L


def instanceddata_xml(v, ind=" "):
    """<instancedData> - a rage__fwInstancedMapData STRUCT (not an array), so its three children
    are always present.

    PropInstanceList is written EMPTY, never guessed: it holds zero items in all 11,052 reference
    exports AND no ymap binary in the whole-game filebase even registers a
    rage__fwPropInstanceListDef in its schema table, so there is no oracle for its Item shape. If
    one ever decodes non-empty, ymap_dropped_from raises the marker for it rather than letting
    this write an invented element - a wrong shape is invisible, an omission is not."""
    v = v or {}
    f = ind + " "
    L = ["%s<instancedData>" % ind]
    L.append(_txt("ImapLink", v.get("ImapLink"), f))
    props = _inline_items(v.get("PropInstanceList"))
    if props:
        L += _omitted("instancedData/PropInstanceList", len(props), f)
    else:
        L.append('%s<PropInstanceList itemType="rage__fwPropInstanceListDef" />' % f)
    L += _container("GrassInstanceList", _inline_items(v.get("GrassInstanceList")),
                    "rage__fwGrassInstanceListDef", f, grass_batch_xml)
    L.append("%s</instancedData>" % ind)
    return L


# container -> renderer. A container ABSENT here is one this emitter still cannot write
# faithfully, and ymap_xml leaves its omission marker instead.
#
# occludeModels IS NOW WRITTEN FOR REAL (2026-08-05) - see occlude_model_item_xml for the read of
# Matt's reference exports that closed it. THE BLOCKING FACT WAS NEVER THE FORMAT, IT WAS THE
# REFERENCE'S TEXT SPELLING OF <verts>, and the history below is kept verbatim because the shape of
# the block - "decoded, proven, and still not written, because one encoding was unknown" - is the
# thing to repeat, not to be embarrassed by. What was already true when it was still dropped:
# 0x59 is a raw byte-buffer pointer, the Walker returns the bytes, and `unhandled type 0x59` no
# longer fires. What the bytes
# MEAN is measured too, over all 1,702 records in 183 ymap of the whole-game filebase, 0 exceptions:
#
#   payload := numVertsInBytes bytes of VERTICES, then 3*(numTris & 0x7FFF) bytes of INDICES
#   * len(payload) == dataSize                                      1,702/1,702
#   * dataSize == numVertsInBytes + 3*(numTris & 0x7FFF)            1,702/1,702  (u8 indices)
#   * numVertsInBytes % 12 == 0, i.e. numVerts = numVertsInBytes/12 1,702/1,702  (float32 x,y,z)
#   * every index < numVerts                                        1,702/1,702
#   * numTris always has bit 15 set; the count is the low 15 bits   1,702/1,702
#   * THE FREE ORACLE, and the one that proves the floats really are world-space vertices:
#     min/max of the decoded triplets reproduces the record's OWN bmin/bmax to 1e-4 on all three
#     axes                                                          1,702/1,702
#   (largest numVerts observed is 231, which is why one byte per index is enough; a corpus with a
#   >255-vertex occluder would need this re-measured, and the latch in ymap_dropped_from says so.)
#
# ** RE-MEASURED ON THE LIVE CORPUS, AND ONE NUMBER MOVED TO THE EDGE (2026-08-05). Every ymap in
# F:/RUDE_Filebase_v2 00_base+10_update+20_dlc - 19,385 binaries, NO name filter, 2 pre-existing
# decode failures - yields 337 files / 3,019 occludeModels records. Every invariant above still
# holds 3,019/3,019 (0 non-bytes, 0 length disagreements, 0 zero-length payloads; dataSize spans
# 39..4017; flags is 0 on 2,923 and 1 on 96, which is exactly the {0,1} the reference census
# records). BUT THE LARGEST numVerts IS 255, NOT 231 - the u8 index width is not comfortably
# sufficient, it is EXACTLY saturated, and the reference census agrees (max numVertsInBytes 3060 =
# 255 verts). One more vertex in any future DLC breaks the u8 reading. That is what
# check_occlude_models' >255 branch is for and why it must keep running now that the container
# ships; do not read "0 exceptions" as headroom.
#
# [CLOSED 2026-08-05 - the paragraph below is the state of knowledge BEFORE Matt's reference export
# arrived, kept because its last sentence is the rule that made the close possible: "the omission
# marker stays until a reference `<verts>` payload can be read; when it can, everything needed to
# write it is already decoded and measured above." That is exactly what happened - the decode never
# had to be revisited, only the spelling read. Note also that the argument below EXCLUDED base64
# and "positively identifies none", and the answer turned out to be the hex it called merely a
# candidate: an elimination is not an identification, and it was right not to be treated as one.]
# WHAT IS STILL MISSING IS NOT THE FORMAT - IT IS THE REFERENCE'S TEXT SPELLING OF ONE ELEMENT.
# The census (`reports/snapshots/ymap.json`, 11,052 reference ymap) records
# `CMapData/occludeModels/Item/verts` as element TEXT classified 'string' with NO sample values,
# and that is everything it knows. Read for all it is worth:
#   * 'string' means the payload is NOT numeric text - the same miner classifies ydr's
#     VertexBuffer/Data and IndexBuffer/Data as 'numlist', so a number list was possible and this
#     field is not one. `verts` is the ONLY opaque text payload in the entire reference ymap
#     census, so there is no house style to appeal to either.
#   * the miner banks any 'string' payload of <=60 chars as a sample and banked NONE, so every one
#     of the 1,994 reference payloads exceeds 60 characters. The smallest record in our corpus is
#     dataSize 39 (cs2_occl_03, cs5_occl_02 x2, po1_occl_03 - 3 verts, 1 triangle), and 39 bytes
#     of base64 is 52 characters, which WOULD have been sampled. So base64 is excluded - PROVIDED
#     the reference corpus (2,003 records / 224 files, a superset in size of our 1,702 / 183)
#     covered one of those three base-game files. That last step is an INFERENCE, not a
#     measurement, and it is the whole strength of the argument: it eliminates one candidate and
#     positively identifies none.
# Hex would fit what survives. So would several other opaque encodings. No reference ymap XML
# exists on this machine to read one from, and no public spec found says which. Writing the
# geometry under a guessed encoding would put 1,702 correct-looking, wrongly-encoded occluder
# meshes into the corpus with nothing to mark them - the exact defect this section exists to
# prevent, one level down. The omission marker stays until a reference `<verts>` payload can be
# read; when it can, everything needed to write it is already decoded and measured above.
# [end of the superseded paragraph]
#
# containerLods is the ONLY container still absent from the map below, and for the opposite reason
# - 0 records in all 8,076 ymap, so its empty form is never wrong and it can never reach a
# renderer. occludeModels can still be dropped at RUNTIME by occlude_models_unserialisable, which
# is a different thing from having no emitter: the marker then names which precondition failed.
CONTAINER_EMITTERS = {
    "boxOccluders": boxoccluders_xml,
    "occludeModels": occludemodels_xml,
    "physicsDictionaries": physdict_xml,
    "instancedData": instanceddata_xml,
    "timeCycleModifiers": map_tcmods_xml,
    "carGenerators": cargens_xml,
    "LODLightsSOA": lodlights_soa_xml,
    "DistantLODLightsSOA": distlodlights_soa_xml,
}


def container_has_content(cname, v):
    """Whether a container is worth rendering at all.

    NOT the same question as container_records, and the difference is a real trap:
    container_records counts ARRAY records, which is the right number to put in a marker but the
    wrong test for two struct containers. instancedData's `ImapLink` and DistantLODLightsSOA's
    `numStreetLights` / `category` are SCALAR fields, so a file carrying only those scores zero
    records, takes the empty form, and has them silently rewritten to nothing / 0.

    !! THIS IS A LATCH, NOT A LIVE FIX, and saying so is the point - measured over all 8,076 ymap
    in the whole-game filebase (2026-08-04): ImapLink is non-empty in 0 files, and of the 266 files
    whose numStreetLights/category are non-zero, 0 have an empty position array. So the two
    predicates agree on every file that exists today and this changes no output. It is here
    because the failure it prevents is silent, and because the shape of the data - not its
    current contents - is what says the guard is needed.
    """
    if container_records(v):
        return True
    if not isinstance(v, dict):
        return False
    if cname == "instancedData":
        return bool(v.get("ImapLink"))
    if cname == "DistantLODLightsSOA":
        return bool(v.get("numStreetLights")) or bool(v.get("category"))
    return False


def ymap_containers_from(root):
    """The nine non-entity CMapData containers, straight off the decoded root.

    Deliberately NOT normalised into plain dicts the way entities_from does: the renderers
    unwrap with _inline_items at the point of use, so there is exactly one place per container
    that knows its shape and no intermediate model to drift out of step with the decode."""
    return {cname: root.get(cname) for cname, _lines in EMPTY_CONTAINERS}


def check_occlude_models(items, w):
    """Re-assert the measured OccludeModel payload law on every file this tool ever reads.

    The law is written out at CONTAINER_EMITTERS and held on all 1,702 records of
    the whole-game filebase with 0 exceptions. That makes it a MEASUREMENT, and a measurement taken
    once over one corpus is exactly the kind of claim that rots silently: the user's install is not
    this corpus, and a DLC that ever ships a >255-vertex occluder (u8 indices could not address it)
    or a 16-bit index form would satisfy every other check in this file and be noticed by nobody.
    So it is CHECKED rather than remembered, and a violation is COUNTED - it changes no output,
    because occludeModels is dropped either way, but it converts "we measured this in August" into
    "this file agrees with what we measured".
    """
    for it in _inline_items(items):
        raw = it.get("verts")
        ds = pick(it, "dataSize", 0)
        nvib = pick(it, "numVertsInBytes", 0)
        ntris = pick(it, "numTris", 0) & 0x7FFF
        if not isinstance(raw, bytes):
            w.warn["OccludeModel verts did not decode to bytes"] += 1
            continue
        if len(raw) != ds:
            w.warn["OccludeModel payload length != dataSize"] += 1
        if ds != nvib + 3 * ntris:
            w.warn["OccludeModel dataSize != numVertsInBytes + 3*numTris"] += 1
        if nvib % 12:
            w.warn["OccludeModel numVertsInBytes is not a multiple of 12"] += 1
        elif nvib // 12 > 255:
            # u8 indices cannot address it, so the index width would have to be re-measured
            w.warn["OccludeModel has more than 255 vertices"] += 1


def ymap_dropped_from(root, w=None):
    """container -> record count, for the CMapData containers this emitter STILL drops.

    Counted off the DECODED root, so the number can never disagree with what was emitted, and
    pushed into the Walker's warn counter so `--convert` (and quarry's meta stage) print it.
    A container with a renderer in CONTAINER_EMITTERS is NOT listed here - it is written for real
    - which is precisely why the marker disappearing from a file is a claim this function makes,
    not a claim the caller makes.
    """
    out = {}
    for cname, _lines in EMPTY_CONTAINERS:
        if cname in CONTAINER_EMITTERS:
            continue
        n = container_records(root.get(cname))
        if n:
            out[cname] = n
            if w is not None:
                w.warn["DROPPED ymap container %s (emitter does not serialise it)" % cname] += n
    # occludeModels has a renderer now, so the loop above SKIPS it and this block is what keeps
    # its law asserted. It was previously gated on `out.get("occludeModels")` - i.e. on the
    # container being dropped - which means registering the emitter would have silently switched
    # check_occlude_models off on every file. A gate that stops running when the thing it guards
    # starts shipping is the worst possible time for it to stop running.
    occ = root.get("occludeModels")
    if container_records(occ):
        if w is not None:
            check_occlude_models(occ, w)
        reason = occlude_models_unserialisable(occ)
        if reason:
            n = container_records(occ)
            out["occludeModels"] = n
            if w is not None:
                w.warn["DROPPED ymap container occludeModels (%s)" % reason] += n
    # the one sub-container with a renderer above it but no oracle of its own
    props = (root.get("instancedData") or {}).get("PropInstanceList") or []
    if props and w is not None:
        w.warn["DROPPED ymap container instancedData/PropInstanceList "
               "(emitter does not serialise it)"] += len(props)
    return out


# ---------------------------------------------------------------- witness coverage (churn gate)
#
# ⛔⛔ WHY THIS LIVES HERE AND NOT IN THE GATE (#32d, 2026-08-05). The churn gate shipped the
# ENTIRE occludeModels emitter under a green "No churn" it could not have produced: only 2 of the
# 67 ymap in the binary fixture set carry an occluder and the 25-file random sample drew NEITHER, so the
# baseline could not move. A random per-type sample cannot guarantee that any given CONTAINER is
# represented, and raising --per-type does not fix it (past the population size the sample
# re-rolls and silently demotes previously-blessed fixtures without failing).
# The fix is PINNED WITNESSES, and the list of things needing a witness belongs to the module that
# owns the containers: add a renderer to CONTAINER_EMITTERS and this tuple grows with it, so the
# gate's coverage report can never quietly fall behind the emitter.
#
# `block` is a topic here even though it is not a container: it is a CMapData child the emitter is
# responsible for, and it is the very next thing that was found being dropped (#32c).
YMAP_WITNESS_TOPICS = tuple(c for c, _l in EMPTY_CONTAINERS) + ("block",)

# Topics for which NO witness can exist, each with the measurement that says so. An entry here is
# an exemption from "every topic needs a carrier under gate" and therefore has to carry its
# receipt; anything NOT here and NOT witnessed is a gate FAILURE, not a note.
YMAP_TOPICS_WITHOUT_CARRIER = {
    "containerLods": "0 populated in all 11,084 _resolved ymap binaries (2026-08-05 census); "
                     "the struct is never registered in any ymap schema table",
}

# The six proven CMapData/block fields, in the reference's child order (25 of 25 exports agree,
# and it is also the binary descriptor order). Kinds: val = `value=` attribute, txt = element
# text. The RENDERER is #32c; this tuple is here because the gate needs the field list to answer
# "is this block populated" without knowing how to write one.
BLOCK_FIELDS = (("version", "val"), ("flags", "val"), ("name", "txt"),
                ("exportedBy", "txt"), ("owner", "txt"), ("time", "txt"))


def ymap_block_from(root):
    """The decoded `block` struct, or {} when the binary carries none.

    {} and None mean DIFFERENT things downstream and the difference is the point: {} is "this
    binary has no block struct" (never observed - 0 of 11,082 - but a census is a lower bound),
    None is "the caller never supplied one"."""
    b = root.get("block")
    return b if isinstance(b, dict) else {}


def block_populated(blk):
    """Whether a block carries anything a reader could tell apart from the all-empty form.

    ⛔ This is the predicate that proves the "always empty" claim FALSE. Measured over all 11,084
    _resolved ymap binaries (2026-08-05): name 1,406 | exportedBy 1,406 | time 1,406 |
    version 912 | flags 928 are non-empty. The register's "observed empty in all 5 reference
    files" was a LOWER BOUND read off five files, and 4 of Matt's 25 references contradict it."""
    if not isinstance(blk, dict):
        return False
    return any(blk.get(t) for t, _k in BLOCK_FIELDS)


def ymap_witnessed(root):
    """Which YMAP_WITNESS_TOPICS this decoded CMapData can actually TESTIFY about."""
    out = set()
    for cname, _l in EMPTY_CONTAINERS:
        if container_has_content(cname, root.get(cname)):
            out.add(cname)
    if block_populated(ymap_block_from(root)):
        out.add("block")
    return out


def ymap_witness_of(path):
    """ymap_witnessed() for a file on disk; empty set for anything that is not a CMapData."""
    with open(path, "rb") as fh:
        w = Walker(MetaFile(fh.read()))
    root_name, root = w.root()
    return ymap_witnessed(root) if root_name == "CMapData" else set()


# ---------------------------------------------------------------- CMapData/block
#
# THE DEFECT THIS CLOSES (#32c, 2026-08-05): `block` was decoded and thrown away with NO SIGNAL
# AT ALL - not the element, not an empty form, not a drop marker - because it is not a container,
# so `ymap_dropped_from` never saw it and nothing counted it. That is strictly WORSE than the
# occludeModels drop it was found beside: a marker tells a reader what is missing, silence does
# not, and this file was otherwise matching the reference line for line.
#
# ⛔ THE "PROBABLY ALWAYS EMPTY" ASSUMPTION WAS WRONG - and it was wrong because it was read off
# FIVE files. The register recorded "observed empty (all-zero/blank) in all 5 reference files"
# and correctly flagged it as a LOWER BOUND. It is one: re-read across ALL 25 of Matt's reference
# exports, FOUR carry real author strings (hw1_27 -> name "hw1_27", exportedBy "tim.fionda",
# time "29 October 2014 09:43") and TWO carry non-zero numbers (hei_carrier_distantlights ->
# version 1097112694, flags 255). CORPUS, all 11,084 ymap binaries in F:/RUDE_Filebase_v2/
# _resolved decoded with NO filter of any kind: block present in 11,082 of the 11,082 that decode
# (the 2 failures are the pre-existing "not an RSC7 container" id2_17 pair), ZERO unknown keys
# inside it, and POPULATED in
#     name 1,406 | exportedBy 1,406 | time 1,406 | version 912 | flags 928.
# ⇒ this needed SERIALISING, not an empty form. Emitting the all-empty shape would have silently
# stripped 1,406 files of their provenance while looking correct doing it.
#
# WHERE THE SHAPE COMES FROM (nothing invented):
#   ELEMENT NAMES - exact case-sensitive joaat preimages of the stored nameHashes (SCHEMA_NAMES).
#   CHILD ORDER   - version, flags, name, exportedBy, owner, time: identical in 25 of 25
#                   reference exports, and the same order the binary descriptor stores.
#   POSITION      - LAST child of CMapData, after DistantLODLightsSOA, in 25 of 25.
#   attr vs TEXT  - version/flags are `value=` attributes; the four strings are element TEXT, and
#                   an EMPTY one is spelled `<owner></owner>`, NOT `<owner />`.
#                   ⚠ That is the OPPOSITE of the file-level `_txt` rule (`<parent />` when empty,
#                   in the same reference file), which is why block gets its own text helper
#                   rather than reusing one that would have been wrong in 25 of 25 files.
#   TYPES         - version/flags int 11,082/11,082; the four strings str 11,082/11,082. No
#                   escaping was needed anywhere in the corpus (0 files with <>&" or non-ASCII),
#                   and esc() is applied anyway - a census proves existence, never absence.
# Characters XML 1.0 does not permit in element text at all (C0 controls except tab/LF/CR).
_XML_ILLEGAL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _block_txt(tag, v, ind):
    """`<tag>text</tag>`, and `<tag></tag>` when empty - the MEASURED block spelling."""
    return "%s<%s>%s</%s>" % (ind, tag, esc(v), tag)


def block_xml(blk, ind=" "):
    """`<block>` for one decoded CMapData. Refuses field-by-field rather than guessing.

    THREE marker paths, all counted in the emitted text, because none of them may be silent:
      * block is None   - the caller supplied none (the round-trip harness feeds parsed XML, not
                          a decoded binary). Omitted with a marker, never forged.
      * block is {}     - this binary carries no block struct. Never observed in 11,082 files,
                          which is exactly why it gets a branch: a census is a lower bound.
      * a bad TYPE      - that ONE field is omitted and named, with its decoded type. Coercing an
                          int into <time> would produce a plausible-looking wrong file.
      * an unknown key  - the six proven fields are still written (they are proven); the
                          unrecognised keys are NAMED, so a future schema addition surfaces as a
                          line in the file instead of vanishing the way this whole struct did.
    """
    if blk is None:
        return ["%s<!-- QUARRY: no block was supplied to this emitter (the caller passed parsed "
                "XML, not a decoded binary), so the element is omitted rather than forged "
                "empty. -->" % ind]
    if not blk:
        return ["%s<!-- QUARRY: this binary carries no block struct, so the element is omitted "
                "rather than forged empty. -->" % ind]
    known = {f for f, _k in BLOCK_FIELDS}
    unknown = sorted(k for k in blk if k not in known)
    L = ["%s<block>" % ind]
    bad = []
    f = ind + " "
    for tag, kind in BLOCK_FIELDS:
        v = blk.get(tag)
        if kind == "val":
            if isinstance(v, int) and not isinstance(v, bool):
                L.append(_val(tag, v, f))
            else:
                bad.append("%s (%s)" % (tag, type(v).__name__))
        elif not isinstance(v, str):
            bad.append("%s (%s)" % (tag, type(v).__name__))
        elif _XML_ILLEGAL.search(v):
            # esc() spells <>&" but cannot rescue a C0 control byte: XML 1.0 forbids those
            # outright, so writing one produces a file no parser will read. 0 of 11,082 corpus
            # blocks contain one - and 0 observed is a LOWER BOUND, which is the whole reason
            # this branch exists rather than a comment saying it cannot happen.
            bad.append("%s (control characters)" % tag)
        else:
            L.append(_block_txt(tag, v, f))
    L.append("%s</block>" % ind)
    if bad:
        L.append("%s<!-- QUARRY DROPPED block field(s): %d not serialised because the decoded "
                 "value is not one this emitter can spell faithfully (the reason is in "
                 "brackets; every corpus file holds int, int, str, str, str, str): %s. Omitted, "
                 "never coerced. -->" % (ind, len(bad), ", ".join(bad)))
    if unknown:
        L.append("%s<!-- QUARRY UNRESOLVED block field(s): %d key(s) this emitter has no proven "
                 "element name for: %s. The proven fields above ARE written. -->"
                 % (ind, len(unknown), ", ".join(unknown)))
    return L


def ymap_xml(name, entities, meta=None, dropped=None, containers=None, block=None):
    """`containers` = the decoded CMapData root's non-entity containers (ymap_containers_from);
    `dropped` = {container: record count} from ymap_dropped_from() for the ones with no renderer;
    `block` = ymap_block_from(). None means the caller supplied none, which block_xml REPORTS in
    the file instead of dropping silently - that silence was #32c.

    Omitting containers and dropped - which the round-trip harness does, since it feeds
    reference-PARSED dicts that never carried these containers - keeps the old all-empty
    behaviour, so that gate still measures exactly what it measured before."""
    m = meta or {}
    c = containers or {}
    L = ['<?xml version="1.0" encoding="UTF-8"?>', "<CMapData>"]
    L.append(_txt("name", name, " "))
    L.append(_txt("parent", m.get("parent"), " "))
    L.append(_val("flags", pick(m, "flags", 0), " "))
    L.append(_val("contentFlags", pick(m, "contentFlags", 0), " "))
    for t in ("streamingExtentsMin", "streamingExtentsMax",
              "entitiesExtentsMin", "entitiesExtentsMax"):
        L.append(_vec(t, m.get(t), " "))
    if entities:
        L.append(" <entities>")
        for e in entities:
            L += entity_xml(e)
        L.append(" </entities>")
    else:
        L.append(" <entities />")
    d = dropped or {}
    for cname, lines in EMPTY_CONTAINERS:
        n = d.get(cname, 0)
        if n:
            L += _omitted(cname, n)                       # content, still no emitter
            continue
        render = CONTAINER_EMITTERS.get(cname)
        if render is None or not container_has_content(cname, c.get(cname)):
            L += list(lines)                              # honestly empty (or nothing decoded)
            continue
        L += render(c.get(cname))
    L += block_xml(block)                     # LAST child of CMapData in 25 of 25 references
    L.append("</CMapData>")
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------- scenario regions (.ymt)
# Shapes measured over the 144 name-matched <CScenarioPointRegion> reference exports:
# root child order is VersionNumber, Points, EntityOverrides, ChainingGraph, AccelGrid,
# hash_E529D603, Clusters, LookUps in 144/144 files; every container empty-form is
# self-closing WITH its itemType (LookUps children: WITHOUT - they carry none when full
# either); EdgeIds / hash_E529D603 render in the scalar_list law (<=10 one line, then ten
# per line). The hash_ tags are the REFERENCE'S OWN spelling - see the SCHEMA_NAMES note.
def spawnpoint_item_xml(d, ind):
    """One CExtensionDefSpawnPoint <Item> inside LoadSavePoints / ScenarioPoints: the exact
    ytyp extension field set and order, but WITHOUT the type attribute (itemType on the
    container names the struct instead - measured, e.g. nw_countryside LoadSavePoints)."""
    L = ["%s<Item>" % ind]
    L += _spec_fields(d, EXT_SPECS["CExtensionDefSpawnPoint"], ind + " ",
                      "CExtensionDefSpawnPoint")
    L.append("%s</Item>" % ind)
    return L


SCEN_POINT_INTS = ("iType", "ModelSetId", "iInterior", "iRequiredIMapId", "iProbability",
                   "uAvailableInMpSp", "iTimeStartOverride", "iTimeEndOverride", "iRadius",
                   "iTimeTillPedLeaves", "iScenarioGroup")


def scen_point_xml(p, ind):
    """One CScenarioPoint <Item>: eleven numeric value-attr fields, then Flags as element
    text (multi-bit values are the measured ', ' join; a decode-degraded raw number is
    spelled as digits), then the packed position+direction VEC4."""
    f = ind + " "
    L = ["%s<Item>" % ind]
    for tag in SCEN_POINT_INTS:
        L.append(_val(tag, require(p, tag, "CScenarioPoint"), f))
    v = require(p, "Flags", "CScenarioPoint")
    L.append(_txt("Flags", v if isinstance(v, str) else fmt_num(v), f))
    L.append(_vec("vPositionAndDirection",
                  require(p, "vPositionAndDirection", "CScenarioPoint"), f, "xyzw"))
    L.append("%s</Item>" % ind)
    return L


def scen_points_xml(c, ind):
    """A CScenarioPointContainer: <Points> holding the LoadSavePoints and MyPoints typed
    containers. Never itself empty or attributed (1,153 reference occurrences)."""
    L = ["%s<Points>" % ind]
    L += _container("LoadSavePoints", (c or {}).get("LoadSavePoints") or [],
                    "CExtensionDefSpawnPoint", ind + " ", spawnpoint_item_xml)
    L += _container("MyPoints", (c or {}).get("MyPoints") or [],
                    "CScenarioPoint", ind + " ", scen_point_xml)
    L.append("%s</Points>" % ind)
    return L


def scen_override_xml(o, ind):
    f = ind + " "
    L = ["%s<Item>" % ind]
    L.append(_vec("EntityPosition", require(o, "EntityPosition",
                                            "CScenarioEntityOverride"), f))
    L.append(_txt("EntityType", o.get("EntityType"), f))
    L += _container("ScenarioPoints", o.get("ScenarioPoints") or [],
                    "CExtensionDefSpawnPoint", f, spawnpoint_item_xml)
    for tag in ("EntityMayNotAlwaysExist", "SpecificallyPreventArtPoints"):
        L.append(_val(tag, require(o, tag, "CScenarioEntityOverride"), f))
    L.append("%s</Item>" % ind)
    return L


def scen_node_xml(n, ind):
    """One CScenarioChainingNode <Item>. hash_9B1D60AB is a T_HASH the reference itself
    cannot name (empty for hash 0, else an attachment prop name such as prop_atm_01)."""
    f = ind + " "
    L = ["%s<Item>" % ind]
    L.append(_vec("Position", require(n, "Position", "CScenarioChainingNode"), f))
    L.append(_txt("hash_9B1D60AB", n.get("hash_9B1D60AB"), f))
    L.append(_txt("ScenarioType", n.get("ScenarioType"), f))
    for tag in ("HasIncomingEdges", "HasOutgoingEdges"):
        L.append(_val(tag, require(n, tag, "CScenarioChainingNode"), f))
    L.append("%s</Item>" % ind)
    return L


def scen_edge_xml(e, ind):
    """One CScenarioChainingEdge <Item>. Action/NavMode/NavSpeed are byte enums whose
    member names no dictionary reverses - the reference spells the raw number, so the
    decode already hands over plain ints (see T_ENUM_U8)."""
    f = ind + " "
    L = ["%s<Item>" % ind]
    for tag in ("NodeIndexFrom", "NodeIndexTo", "Action", "NavMode", "NavSpeed"):
        L.append(_val(tag, require(e, tag, "CScenarioChainingEdge"), f))
    L.append("%s</Item>" % ind)
    return L


def scen_chain_xml(c, ind):
    f = ind + " "
    L = ["%s<Item>" % ind]
    L.append(_val("hash_44F1B77A", require(c, "hash_44F1B77A", "CScenarioChain"), f))
    L += scalar_list("EdgeIds", c.get("EdgeIds") or [], f)
    L.append("%s</Item>" % ind)
    return L


def scen_cluster_xml(cl, ind):
    f = ind + " "
    L = ["%s<Item>" % ind]
    L += scen_points_xml(cl.get("Points"), f)
    L.append("%s<ClusterSphere>" % f)
    L.append(_vec("centerAndRadius", require(cl, "ClusterSphere", "CScenarioPointCluster"),
                  f + " ", "xyzw"))
    L.append("%s</ClusterSphere>" % f)
    L.append(_val("hash_4151BB75", require(cl, "hash_4151BB75", "CScenarioPointCluster"), f))
    L.append(_val("hash_BA87159C", require(cl, "hash_BA87159C", "CScenarioPointCluster"), f))
    L.append("%s</Item>" % ind)
    return L


LOOKUP_TAGS = ("TypeNames", "PedModelSetNames", "VehicleModelSetNames", "GroupNames",
               "InteriorNames", "RequiredIMapNames")


def scenario_xml(r):
    """A whole CScenarioPointRegion document from the decoded root dict."""
    ctx = "CScenarioPointRegion"
    L = ['<?xml version="1.0" encoding="UTF-8"?>', "<CScenarioPointRegion>"]
    L.append(_val("VersionNumber", require(r, "VersionNumber", ctx), " "))
    L += scen_points_xml(require(r, "Points", ctx), " ")
    L += _container("EntityOverrides", r.get("EntityOverrides") or [],
                    "CScenarioEntityOverride", " ", scen_override_xml)
    cg = require(r, "ChainingGraph", ctx)
    L.append(" <ChainingGraph>")
    L += _container("Nodes", cg.get("Nodes") or [], "CScenarioChainingNode", "  ",
                    scen_node_xml)
    L += _container("Edges", cg.get("Edges") or [], "CScenarioChainingEdge", "  ",
                    scen_edge_xml)
    L += _container("Chains", cg.get("Chains") or [], "CScenarioChain", "  ",
                    scen_chain_xml)
    L.append(" </ChainingGraph>")
    g = require(r, "AccelGrid", ctx)
    L.append(" <AccelGrid>")
    for tag in ("MinCellX", "MaxCellX", "MinCellY", "MaxCellY", "CellDimX", "CellDimY"):
        L.append(_val(tag, require(g, tag, "rage__spdGrid2D"), "  "))
    L.append(" </AccelGrid>")
    L += scalar_list("hash_E529D603", r.get("hash_E529D603") or [], " ")
    L += _container("Clusters", r.get("Clusters") or [], "CScenarioPointCluster", " ",
                    scen_cluster_xml)
    lu = require(r, "LookUps", ctx)
    L.append(" <LookUps>")
    for tag in LOOKUP_TAGS:
        vals = lu.get(tag) or []
        if not vals:
            L.append("  <%s />" % tag)       # measured: no itemType on LookUps children
        else:
            L.append("  <%s>" % tag)
            for s in vals:
                L.append(_txt("Item", s, "   "))
            L.append("  </%s>" % tag)
    L.append(" </LookUps>")
    L.append("</CScenarioPointRegion>")
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------- ped variation .ymt
# Two roots the meta lane used to REJECT (UnsupportedRoot) are wired below, 2026-08-06. The
# Walker already decodes both generically; these emitters render its dict to the oracle's exact
# XML shape (field order = the binary struct-descriptor order the Walker preserves; indent =
# one space per depth; helpers reused from the ytyp/ymap/ymt lanes). All element names are the
# verified SCHEMA_NAMES preimages added above.
def _inline_ints(tag, vals, indent):
    """A FIXED-length uint array on ONE line regardless of count. availComp is 12 bytes and
    scalar_list would wrap it at >10; the reference keeps all 12 inline."""
    return "%s<%s>%s</%s>" % (indent, tag, " ".join(str(int(x)) for x in (vals or ())), tag)


def _content_num(tag, v, indent):
    """A field the reference writes as element TEXT holding a bare number - inclusions /
    exclusions, a flags field with no symbolic table (T_FLAGS refKey 0 -> the raw int)."""
    return "%s<%s>%s</%s>" % (indent, tag, fmt_num(v), tag)


def _hash_items(tag, vals, indent):
    """A hash/string array with NO itemType attribute and <Item> children (AddList, RemoveList,
    PromoteToHDList, Requests) - the same measured shape as scenario LookUps; empty -> self-close."""
    if not vals:
        return ["%s<%s />" % (indent, tag)]
    out = ["%s<%s>" % (indent, tag)]
    for s in vals:
        out.append(_txt("Item", s, indent + " "))
    out.append("%s</%s>" % (indent, tag))
    return out


def _pv_selset_item(d, ind):
    # aSelectionSets (itemType CPedSelectionSet) is EMPTY in every measured ped .ymt, so its
    # populated item shape is UNPINNED. _container never calls this for an empty list; if a
    # populated set ever appears, refuse loudly rather than forge a shape.
    raise ValueError("CPedSelectionSet item shape UNPINNED - no populated sample in evidence")


def _pv_texdata_item(d, ind):
    f = ind + " "
    return ["%s<Item>" % ind,
            _val("texId", require(d, "texId", "CPVTextureData"), f),
            _val("distribution", require(d, "distribution", "CPVTextureData"), f),
            "%s</Item>" % ind]


def _pv_drawbl_item(d, ind):
    f = ind + " "
    L = ["%s<Item>" % ind,
         _val("propMask", require(d, "propMask", "CPVDrawblData"), f),
         _val("numAlternatives", require(d, "numAlternatives", "CPVDrawblData"), f)]
    L += _container("aTexData", _inline_items(d.get("aTexData")), "CPVTextureData", f,
                    _pv_texdata_item)
    cloth = d.get("clothData") or {}
    L.append("%s<clothData>" % f)
    L.append(_val("ownsCloth", require(cloth, "ownsCloth", "clothData"), f + " "))
    L.append("%s</clothData>" % f)
    L.append("%s</Item>" % ind)
    return L


def _pv_compdata_item(d, ind):
    f = ind + " "
    L = ["%s<Item>" % ind,
         _val("numAvailTex", require(d, "numAvailTex", "CPVComponentData"), f)]
    L += _container("aDrawblData3", _inline_items(d.get("aDrawblData3")), "CPVDrawblData", f,
                    _pv_drawbl_item)
    L.append("%s</Item>" % ind)
    return L


def _pv_compinfo_item(d, ind):
    f = ind + " "
    L = ["%s<Item>" % ind,
         _txt("pedXml_audioID", d.get("pedXml_audioID"), f),
         _txt("pedXml_audioID2", d.get("pedXml_audioID2"), f)]
    L += num_list("pedXml_expressionMods", d.get("pedXml_expressionMods") or [], f)
    L.append(_val("flags", require(d, "flags", "CComponentInfo"), f))
    L.append(_content_num("inclusions", require(d, "inclusions", "CComponentInfo"), f))
    L.append(_content_num("exclusions", require(d, "exclusions", "CComponentInfo"), f))
    L.append(_txt("pedXml_vfxComps", d.get("pedXml_vfxComps"), f))
    L.append(_val("pedXml_flags", require(d, "pedXml_flags", "CComponentInfo"), f))
    L.append(_val("pedXml_compIdx", require(d, "pedXml_compIdx", "CComponentInfo"), f))
    L.append(_val("pedXml_drawblIdx", require(d, "pedXml_drawblIdx", "CComponentInfo"), f))
    L.append("%s</Item>" % ind)
    return L


def _pp_texdata_item(d, ind):
    f = ind + " "
    return ["%s<Item>" % ind,
            _content_num("inclusions", require(d, "inclusions", "CPedPropTexData"), f),
            _content_num("exclusions", require(d, "exclusions", "CPedPropTexData"), f),
            _val("texId", require(d, "texId", "CPedPropTexData"), f),
            _val("inclusionId", require(d, "inclusionId", "CPedPropTexData"), f),
            _val("exclusionId", require(d, "exclusionId", "CPedPropTexData"), f),
            _val("distribution", require(d, "distribution", "CPedPropTexData"), f),
            "%s</Item>" % ind]


def _pp_meta_item(d, ind):
    f = ind + " "
    L = ["%s<Item>" % ind, _txt("audioId", d.get("audioId"), f)]
    L += num_list("expressionMods", d.get("expressionMods") or [], f)
    L += _container("texData", _inline_items(d.get("texData")), "CPedPropTexData", f,
                    _pp_texdata_item)
    L.append(_txt("renderFlags", d.get("renderFlags"), f))   # "" -> self-close, else PRF_*
    L.append(_val("propFlags", require(d, "propFlags", "CPedPropMetaData"), f))
    L.append(_val("flags", require(d, "flags", "CPedPropMetaData"), f))
    L.append(_val("anchorId", require(d, "anchorId", "CPedPropMetaData"), f))
    L.append(_val("propId", require(d, "propId", "CPedPropMetaData"), f))
    L.append(_val("stickyness", require(d, "stickyness", "CPedPropMetaData"), f))
    L.append("%s</Item>" % ind)
    return L


def _pp_anchor_item(d, ind):
    f = ind + " "
    L = ["%s<Item>" % ind]
    L += scalar_list("props", d.get("props") or [], f)
    L.append(_txt("anchor", d.get("anchor"), f))
    L.append("%s</Item>" % ind)
    return L


def ped_variation_xml(root):
    """A whole CPedVariationInfo document (ped .ymt) from the decoded root dict."""
    ctx = "CPedVariationInfo"
    L = ['<?xml version="1.0" encoding="UTF-8"?>', "<CPedVariationInfo>"]
    for tag in ("bHasTexVariations", "bHasDrawblVariations", "bHasLowLODs", "bIsSuperLOD"):
        L.append(_val(tag, require(root, tag, ctx), " "))
    L.append(_inline_ints("availComp", root.get("availComp") or [], " "))
    L += _container("aComponentData3", _inline_items(root.get("aComponentData3")),
                    "CPVComponentData", " ", _pv_compdata_item)
    L += _container("aSelectionSets", _inline_items(root.get("aSelectionSets")),
                    "CPedSelectionSet", " ", _pv_selset_item)
    L += _container("compInfos", _inline_items(root.get("compInfos")),
                    "CComponentInfo", " ", _pv_compinfo_item)
    pi = root.get("propInfo") or {}
    L.append(" <propInfo>")
    L.append(_val("numAvailProps", require(pi, "numAvailProps", "propInfo"), "  "))
    L += _container("aPropMetaData", _inline_items(pi.get("aPropMetaData")),
                    "CPedPropMetaData", "  ", _pp_meta_item)
    L += _container("aAnchors", _inline_items(pi.get("aAnchors")),
                    "CAnchorProps", "  ", _pp_anchor_item)
    L.append(" </propInfo>")
    L.append(_txt("dlcName", root.get("dlcName"), " "))
    L.append("</CPedVariationInfo>")
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------- streaming request .ymt
def _srr_frame_item(d, ind):
    f = ind + " "
    L = ["%s<Item>" % ind]
    L += _hash_items("AddList", d.get("AddList") or [], f)
    L += _hash_items("RemoveList", d.get("RemoveList") or [], f)
    L += _hash_items("PromoteToHDList", d.get("PromoteToHDList") or [], f)
    L.append(_vec("CamPos", require(d, "CamPos", "CStreamingRequestFrame"), f))
    L.append(_vec("CamDir", require(d, "CamDir", "CStreamingRequestFrame"), f))
    L += scalar_list("CommonAddSets", d.get("CommonAddSets") or [], f)
    L.append(_val("Flags", require(d, "Flags", "CStreamingRequestFrame"), f))
    L.append("%s</Item>" % ind)
    return L


def _srr_commonset_item(d, ind):
    f = ind + " "
    L = ["%s<Item>" % ind]
    L += _hash_items("Requests", d.get("Requests") or [], f)
    L.append("%s</Item>" % ind)
    return L


def streaming_request_xml(root):
    """A whole CStreamingRequestRecord document (*_srl.ymt) from the decoded root dict."""
    ctx = "CStreamingRequestRecord"
    L = ['<?xml version="1.0" encoding="UTF-8"?>', "<CStreamingRequestRecord>"]
    L += _container("Frames", _inline_items(root.get("Frames")),
                    "CStreamingRequestFrame", " ", _srr_frame_item)
    L += _container("CommonSets", _inline_items(root.get("CommonSets")),
                    "CStreamingRequestCommonSet", " ", _srr_commonset_item)
    L.append(_val("NewStyle", require(root, "NewStyle", ctx), " "))
    L.append("</CStreamingRequestRecord>")
    return "\n".join(L) + "\n"


# ================================================================ binary -> emitter dicts
def _xyz(v):
    """VECTOR3 and VECTOR4 both appear; the XML only ever writes x/y/z for a position/bound."""
    if v is None:
        return None
    return tuple(v[:3]) if len(v) >= 3 else None


def archetypes_from(root):
    out = []
    for item in root.get("archetypes") or []:
        if not item:
            continue
        kind, a = item
        d = dict(
            type=kind,
            lodDist=a.get("lodDist"), flags=a.get("flags"),
            specialAttribute=a.get("specialAttribute"),
            bbMin=_xyz(a.get("bbMin")), bbMax=_xyz(a.get("bbMax")),
            bsCentre=_xyz(a.get("bsCentre")), bsRadius=a.get("bsRadius"),
            hdTextureDist=a.get("hdTextureDist"),
            name=a.get("name"), textureDictionary=a.get("textureDictionary"),
            clipDictionary=a.get("clipDictionary"),
            drawableDictionary=a.get("drawableDictionary"),
            physicsDictionary=a.get("physicsDictionary"),
            assetType=a.get("assetType"), assetName=a.get("assetName"),
            extensions=[ext_from(i) for i in a.get("extensions") or [] if i])
        if kind == "CTimeArchetypeDef":
            d["timeFlags"] = a.get("timeFlags")
        if kind == "CMloArchetypeDef":
            d["mloFlags"] = a.get("mloFlags")
            d["entities"] = [entity_from(i) for i in a.get("entities") or [] if i]
            d["rooms"] = [room_from(r) for _k, r in
                          (i for i in a.get("rooms") or [] if i)]
            d["portals"] = [portal_from(p) for _k, p in
                            (i for i in a.get("portals") or [] if i)]
            d["entitySets"] = [entityset_from(s) for _k, s in
                               (i for i in a.get("entitySets") or [] if i)]
            d["timeCycleModifiers"] = [tcmod_from(t) for _k, t in
                                       (i for i in a.get("timeCycleModifiers") or [] if i)]
        out.append(d)
    return out


def room_from(r):
    return dict(name=r.get("name"), bbMin=_xyz(r.get("bbMin")), bbMax=_xyz(r.get("bbMax")),
                blend=r.get("blend"), timecycleName=r.get("timecycleName"),
                secondaryTimecycleName=r.get("secondaryTimecycleName"),
                flags=r.get("flags"), portalCount=r.get("portalCount"),
                floorId=r.get("floorId"),
                exteriorVisibiltyDepth=r.get("exteriorVisibiltyDepth"),
                attachedObjects=r.get("attachedObjects"))


def portal_from(p):
    # corners stay FOUR floats wide - the 4th is the measured NaN constant the XML spells
    return dict(roomFrom=p.get("roomFrom"), roomTo=p.get("roomTo"), flags=p.get("flags"),
                mirrorPriority=p.get("mirrorPriority"), opacity=p.get("opacity"),
                audioOcclusion=p.get("audioOcclusion"),
                corners=[tuple(c) for c in p.get("corners") or []],
                attachedObjects=p.get("attachedObjects"))


def entityset_from(s):
    return dict(name=s.get("name"), locations=s.get("locations"),
                entities=[entity_from(i) for i in s.get("entities") or [] if i])


def tcmod_from(t):
    sph = t.get("sphere")
    return dict(name=t.get("name"),
                sphere=tuple(sph[:4]) if sph and len(sph) >= 4 else None,
                percentage=t.get("percentage"), range=t.get("range"),
                startHour=t.get("startHour"), endHour=t.get("endHour"))


def ext_from(item):
    """(structName, walkerDict) -> emitter dict. Instances become plain dicts; every other
    field is carried verbatim - the EXT_SPECS table decides rendering, not this."""
    kind, x = item
    d = dict(x)
    d["type"] = kind
    if kind == "CExtensionDefLightEffect":
        d["instances"] = [dict(li) for _k, li in
                          (i for i in x.get("instances") or [] if i)]
    return d


def entity_from(item):
    kind, e = item
    rot = e.get("rotation")
    return dict(
        type=kind, archetypeName=e.get("archetypeName"),
        flags=e.get("flags"), guid=e.get("guid"),
        position=_xyz(e.get("position")),
        rotation=tuple(rot[:4]) if rot and len(rot) >= 4 else None,
        scaleXY=e.get("scaleXY"), scaleZ=e.get("scaleZ"),
        parentIndex=e.get("parentIndex"), lodDist=e.get("lodDist"),
        childLodDist=e.get("childLodDist"), lodLevel=e.get("lodLevel"),
        numChildren=e.get("numChildren"), priorityLevel=e.get("priorityLevel"),
        ambientOcclusionMultiplier=e.get("ambientOcclusionMultiplier"),
        artificialAmbientOcclusion=e.get("artificialAmbientOcclusion"),
        tintValue=e.get("tintValue"),
        # CMloInstanceDef's own five fields. This projection is EXPLICIT (a whitelist), so a
        # subclass field the Walker decoded perfectly well was dropped here before the emitter
        # ever saw it - which is why the emitter's `pick(e,"groupId",0)` wrote 0 while the decode
        # held 6. Carried for every entity; entity_xml emits them only for the subclass.
        groupId=e.get("groupId"), floorId=e.get("floorId"),
        defaultEntitySets=e.get("defaultEntitySets"),
        numExitPortals=e.get("numExitPortals"), MLOInstflags=e.get("MLOInstflags"),
        extensions=[ext_from(i) for i in e.get("extensions") or [] if i])


def entities_from(root):
    return [entity_from(item) for item in root.get("entities") or [] if item]


def ymap_meta_from(root):
    return dict(parent=root.get("parent"), flags=root.get("flags"),
                contentFlags=root.get("contentFlags"),
                streamingExtentsMin=_xyz(root.get("streamingExtentsMin")),
                streamingExtentsMax=_xyz(root.get("streamingExtentsMax")),
                entitiesExtentsMin=_xyz(root.get("entitiesExtentsMin")),
                entitiesExtentsMax=_xyz(root.get("entitiesExtentsMax")))


def _inline_items(seq):
    """Unwrap a Walker inline-struct array: [(structName, dict), ...] -> [dict, ...]."""
    return [d for _k, d in (i for i in seq or [] if i)]


def scen_container_from(c):
    c = c or {}
    return dict(LoadSavePoints=_inline_items(c.get("LoadSavePoints")),
                MyPoints=_inline_items(c.get("MyPoints")))


def scen_cluster_from(cl):
    sph = cl.get("ClusterSphere") or {}
    d = dict(cl)
    d["Points"] = scen_container_from(cl.get("Points"))
    # the sphere struct (hash 0x3F4F4469 - unnamed even in the reference) holds exactly one
    # VEC4; the XML flattens it to <ClusterSphere><centerAndRadius .../></ClusterSphere>
    d["ClusterSphere"] = sph.get("centerAndRadius")
    return d


def scen_override_from(o):
    d = dict(o)
    d["ScenarioPoints"] = _inline_items(o.get("ScenarioPoints"))
    return d


def scenario_from(root):
    cg = root.get("ChainingGraph") or {}
    return dict(
        VersionNumber=root.get("VersionNumber"),
        Points=scen_container_from(root.get("Points")),
        EntityOverrides=[scen_override_from(o)
                         for o in _inline_items(root.get("EntityOverrides"))],
        ChainingGraph=dict(Nodes=_inline_items(cg.get("Nodes")),
                           Edges=_inline_items(cg.get("Edges")),
                           Chains=_inline_items(cg.get("Chains"))),
        AccelGrid=root.get("AccelGrid"),
        hash_E529D603=root.get("hash_E529D603"),
        Clusters=[scen_cluster_from(cl) for cl in _inline_items(root.get("Clusters"))],
        LookUps=root.get("LookUps"))


class UnsupportedRoot(ValueError):
    """A WELL-FORMED META file whose root struct has no emitter here - a recognised boundary,
    not a decode failure. Typed so a pipeline caller can count it apart from real failures;
    .root_name says which root (schema-named where the hash is known, else hash_%08X)."""

    def __init__(self, root_name):
        super().__init__("no emitter for META root struct %r" % root_name)
        self.root_name = root_name


def convert_bytes(blob, stem, names=None):
    """binary ytyp/ymap/ymt -> (xml, kind, walker). Kind comes from the ROOT STRUCT, not the
    file extension, so a mislabelled file cannot be emitted as the wrong schema."""
    w = Walker(MetaFile(blob), names=names)
    root_name, root = w.root()
    if root_name == "CMapTypes":
        return (ytyp_xml(root.get("name") or stem, archetypes_from(root),
                         ytyp_dropped_from(root, w),
                         composite=root.get("compositeEntityTypes")), "ytyp", w)
    if root_name == "CMapData":
        return (ymap_xml(root.get("name") or stem, entities_from(root), ymap_meta_from(root),
                         ymap_dropped_from(root, w), ymap_containers_from(root),
                         ymap_block_from(root)), "ymap", w)
    if root_name == "CScenarioPointRegion":
        return scenario_xml(scenario_from(root)), "ymt", w
    if root_name == "CPedVariationInfo":
        return ped_variation_xml(root), "ymt", w
    if root_name == "CStreamingRequestRecord":
        return streaming_request_xml(root), "ymt", w
    raise UnsupportedRoot(root_name)


def convert(path, names=None):
    stem = os.path.basename(path)
    for ext in (".ytyp", ".ymap", ".ymt"):
        if stem.lower().endswith(ext):
            stem = stem[:-len(ext)]
            break
    with open(path, "rb") as fh:
        return convert_bytes(fh.read(), stem, names)


def load_names(*roots):
    """lowercase-joaat -> asset name, built by hashing the asset FILENAMES the archives yield.

    This is what keeps the tool self-sufficient: `assetName` is the only name that MUST resolve
    (it becomes a `<CorpusRoot>/ydr/<assetName>.ydr.xml` lookup), and it is always a real asset
    filename - so the user's own extraction supplies it. No shipped hash dictionary needed.

    ONLY NAMES THE GAME SHIPPED MAY ENTER THIS TABLE (2026-08-03). It used to hash EVERY filename
    in the tree, including the two kinds QUARRY invents itself:
      `X__embedded` - the sibling manifest written for a drawable's own texture dictionary
      `X~1`         - the rename applied to a within-slot basename collision
    No META hash can legitimately mean either, so their only possible effect is a FALSE
    resolution - and `setdefault` made which one won depend on os.walk order, with no counter.
    COST, measured over all 551,920 files in the whole-game filebase (00_base+10_update+20_dlc,
    284,750 distinct stems): TWO synthetic names collide with a real asset hash -
    joaat('ch3_04_d39x__embedded') == joaat('hei_country_03_metadata_001') == F4A44F28, and
    joaat('m24_1_mp2024_01_additions_carrmp_rigging__embedded') == joaat('sm_11_bld1+hidr') ==
    FFC94D14. The first one already fired: 10_update/ytyp/hei_country_03_metadata_001.ytyp.xml
    emitted `<name>ch3_04_d39x__embedded</name>` where the reference export says
    `hei_country_03_metadata_001`. It is invisible to the "unresolved asset-name hash" counter
    precisely BECAUSE the hash resolved - only an oracle export could catch it.

    Genuine name/name joaat collisions get no guess either: 0 exist in this corpus, but a
    first-writer-wins answer would be a coin flip emitted with full confidence, while
    hash_XXXXXXXX is honestly unresolved and the ymap<->ytyp join is hash-to-hash regardless.
    """
    def stems():
        for root in roots:
            if not root or not os.path.isdir(root):
                continue
            for _dirpath, _dirs, files in os.walk(root):
                for f in files:
                    yield f
    return load_names_from_stems(stems())


def load_names_from_stems(filenames):
    """The ONE implementation of the names-table rules, whatever supplies the filenames
    (an extracted tree via load_names, or the whole-game view manifest via `quarry
    export` - same rules by construction, so the two sources cannot drift):
      - stem = filename up to the first '.', lowercased
      - QUARRY-generated names (X__embedded, X~N) may NOT enter the table
      - a joaat collision between two DISTINCT real names resolves to NEITHER
    """
    names, collisions, synth_hashes = {}, {}, {}
    for f in filenames:
        stem = f.split(".")[0]
        if not stem:
            continue
        low = stem.lower()
        if low.endswith("__embedded") or _ALT_SUFFIX.search(low):
            synth_hashes.setdefault(joaat(low), low)
            continue
        h = joaat(low)
        prev = names.get(h)
        if prev is None:
            names[h] = low
        elif prev != low:
            collisions.setdefault(h, set()).update((prev, low))
    for h in collisions:
        names.pop(h, None)
    # DERIVED CANDIDATES (2026-08-06, measured by the names research pass: they resolve
    # 62 of the 70 REAL name gaps vs the oracle set, with 0 false-positive parity hits
    # even at 10M-candidate scale). Rules, each from an oracle-resolved witness family:
    #   stem + "_lod"                       (slod stand-in -> its lod source)
    #   strip _slod_children/_dslod_children -> base + "_lod" / "_N_lod" / "_NN_lod"
    #   stem minus its first "_" token      (DLC prefix: hei_x -> x)
    #   stem + "_s2a".."_s2j"               (sub-lod letter family)
    # A derived name NEVER displaces a real stem, a real collision, or a synth hash.
    real_stems = list(names.values())
    blocked = set(collisions) | set(synth_hashes)

    def _cand(c):
        h = joaat(c)
        if h not in names and h not in blocked:
            names[h] = c
    for s in real_stems:
        _cand(s + "_lod")
        for suf in ("_slod_children", "_dslod_children"):
            if s.endswith(suf):
                b = s[:-len(suf)]
                _cand(b + "_lod")
                for n in range(100):
                    _cand("%s_%d_lod" % (b, n))
                    _cand("%s_%02d_lod" % (b, n))
        # ⛔ the DLC-prefix-strip rule (s.split("_",1)[1]) was REMOVED 2026-08-06: its
        # only 3 measured hits were nested-archive basenames already supplied by the
        # archive-stems source, and at 3.6M-candidate scale it produced a confident
        # WRONG resolution the oracle spells as a hash (hash_7E996CAC ->
        # 'obankwindemovly008' in hei_heist_ornate_bank) - an over-resolution is a
        # parity break exactly like an under-resolution.
        # PLAIN "_children" strip (2026-08-07): a SLOD archetype's own name is carried only by
        # its children dictionary - `cs1_lod_08_slod2a` exists in the game ONLY as
        # `cs1_lod_08_slod2a_children.ydd` / `.ytd`. The two rules above strip the LONGER
        # `_slod_children` / `_dslod_children` forms and map to a `_lod` base, so a stem like
        # `…_slod2a_children` (letter before `_children`) matched neither. Witnessed by the
        # cs1_lod.ytyp oracle, which spells all 28 of these names.
        if s.endswith("_children"):
            _cand(s[:-len("_children")])
        for c in "abcdefghij":
            _cand(s + "_s2" + c)
    if collisions:
        print("names    : %d joaat COLLISION(S) between distinct asset names - left UNRESOLVED "
              "rather than guessed:" % len(collisions))
        for h, v in sorted(collisions.items())[:8]:
            print("             %08X  %s" % (h, " | ".join(sorted(v))))
    poisoned = [(h, n) for h, n in synth_hashes.items() if h in names]
    if poisoned:
        print("names    : %d QUARRY-generated filename(s) collide with a real asset hash and were "
              "kept OUT of the table (each would have been emitted as a confident wrong name):"
              % len(poisoned))
        for h, n in sorted(poisoned)[:8]:
            print("             %08X  %s  -> resolves to %s" % (h, n, names[h]))
    return names


# ---------------------------------------------------------------- round-trip harness
def _items(text, container):
    m = re.search(r"<%s>(.*?)</%s>" % (container, container), text, re.S)
    if not m:
        return []
    return re.findall(r'<Item type="([^"]+)">(.*?)</Item>', m.group(1), re.S)


def _txt_of(blk, tag):
    if re.search(r"<%s\s*/>" % tag, blk):
        return ""
    m = re.search(r"<%s>([^<]*)</%s>" % (tag, tag), blk)
    return m.group(1).strip() if m else None


def _val_of(blk, tag):
    m = re.search(r'<%s value="([^"]*)"' % tag, blk)
    return m.group(1) if m else None


def _vec_of(blk, tag, comps="xyz"):
    m = re.search(r"<%s\s+([^/>]*)/>" % tag, blk)
    if not m:
        return None
    at = dict(re.findall(r'(\w+)="([^"]*)"', m.group(1)))
    return tuple(at.get(c, "0") for c in comps)


def _e_val(item, tag):
    el = item.find(tag)
    return None if el is None else el.get("value")


def _e_txt(item, tag):
    el = item.find(tag)
    return None if el is None else (el.text or "").strip()


def _e_vec(item, tag, comps="xyz"):
    el = item.find(tag)
    return None if el is None else tuple(el.get(c, "0") for c in comps)


def _e_scalars(item, tag):
    el = item.find(tag)
    return None if el is None else (el.text or "").split()


def _e_items(item, tag):
    el = item.find(tag)
    return [] if el is None else el.findall("Item")


def _e_ext_fields(it):
    """Generic extension-item parse: value attr -> string, x/y/z[/w] attrs -> tuple,
    nested <Item>s -> instances list, else element text. `_order` keeps the tag sequence
    so the round-trip also proves the emitter's FIELD ORDER, not just the values."""
    d = {"_order": [c.tag for c in it]}
    for c in it:
        if len(c):                    # has element children -> instances-style container
            d[c.tag] = [_e_ext_fields(x) for x in c.findall("Item")]
        elif c.get("value") is not None:
            d[c.tag] = c.get("value")
        elif c.get("x") is not None:
            comps = ("x", "y", "z", "w") if c.get("w") is not None else ("x", "y", "z")
            d[c.tag] = tuple(c.get(k, "0") for k in comps)
        else:
            d[c.tag] = (c.text or "").strip()
    return d


def _e_ext(it):
    d = _e_ext_fields(it)
    d["type"] = it.get("type")
    return d


def _e_entity(it):
    d = dict(type=it.get("type"), position=_e_vec(it, "position"),
             rotation=_e_vec(it, "rotation", "xyzw"))
    for t in ("flags", "guid", "scaleXY", "scaleZ", "parentIndex", "lodDist", "childLodDist",
              "numChildren", "ambientOcclusionMultiplier", "artificialAmbientOcclusion",
              "tintValue", "padding0"):
        d[t] = _e_val(it, t)
    for t in ("archetypeName", "lodLevel", "priorityLevel"):
        d[t] = _e_txt(it, t)
    d["extensions"] = [_e_ext(x) for x in _e_items(it, "extensions")]
    return d


def _e_room(it):
    d = dict(name=_e_txt(it, "name"), bbMin=_e_vec(it, "bbMin"), bbMax=_e_vec(it, "bbMax"),
             timecycleName=_e_txt(it, "timecycleName"),
             secondaryTimecycleName=_e_txt(it, "secondaryTimecycleName"),
             attachedObjects=_e_scalars(it, "attachedObjects"))
    for t in ("blend", "flags", "portalCount", "floorId", "exteriorVisibiltyDepth"):
        d[t] = _e_val(it, t)
    return d


def _e_portal(it):
    d = dict(corners=[(c.text or "").strip() for c in _e_items(it, "corners")],
             attachedObjects=_e_scalars(it, "attachedObjects"))
    for t in ("roomFrom", "roomTo", "flags", "mirrorPriority", "opacity", "audioOcclusion"):
        d[t] = _e_val(it, t)
    return d


def _e_set(it):
    return dict(name=_e_txt(it, "name"), locations=_e_scalars(it, "locations"),
                entities=[_e_entity(x) for x in _e_items(it, "entities")])


def _e_tcm(it):
    d = dict(name=_e_txt(it, "name"), sphere=_e_vec(it, "sphere", "xyzw"))
    for t in ("percentage", "range", "startHour", "endHour"):
        d[t] = _e_val(it, t)
    return d


def parse_ytyp(text):
    """Reference (or emitted) XML -> the dicts the emitter takes. Values stay STRINGS so the
    round-trip compares byte-for-byte and cannot pass by accident through float reformatting.

    ElementTree, NOT the regex splitter: MLO archetypes nest <Item> elements (entities inside
    the archetype, entities inside each entity set), and the old non-recursive regex truncated
    an archetype at the FIRST nested </Item>, then scored the inner entities as top-level
    archetypes. It passed only because it made the same mistake on both sides of the compare.
    Element.find matches DIRECT children only, so every field stays at its right depth."""
    root = ET.fromstring(text)
    arch = root.find("archetypes")
    out = []
    for it in ([] if arch is None else arch.findall("Item")):
        d = dict(type=it.get("type"), bbMin=_e_vec(it, "bbMin"), bbMax=_e_vec(it, "bbMax"),
                 bsCentre=_e_vec(it, "bsCentre"))
        for t in ("lodDist", "flags", "specialAttribute", "bsRadius", "hdTextureDist",
                  "padding0", "padding1"):
            d[t] = _e_val(it, t)
        for t in ("name", "textureDictionary", "clipDictionary", "drawableDictionary",
                  "physicsDictionary", "assetType", "assetName"):
            d[t] = _e_txt(it, t)
        d["extensions"] = [_e_ext(x) for x in _e_items(it, "extensions")]
        if d["type"] == "CTimeArchetypeDef":
            d["timeFlags"] = _e_val(it, "timeFlags")
        if d["type"] == "CMloArchetypeDef":
            d["mloFlags"] = _e_val(it, "mloFlags")
            ents = it.find("entities")
            d["entities"] = ([] if ents is None else
                             [_e_entity(x) for x in ents.findall("Item")])
            d["rooms"] = [_e_room(x) for x in _e_items(it, "rooms")]
            d["portals"] = [_e_portal(x) for x in _e_items(it, "portals")]
            d["entitySets"] = [_e_set(x) for x in _e_items(it, "entitySets")]
            d["timeCycleModifiers"] = [_e_tcm(x) for x in _e_items(it, "timeCycleModifiers")]
        out.append(d)
    return out


def parse_ymap(text):
    out = []
    for kind, blk in _items(text, "entities"):
        d = dict(type=kind, position=_vec_of(blk, "position"),
                 rotation=_vec_of(blk, "rotation", "xyzw"))
        for t in ("flags", "guid", "scaleXY", "scaleZ", "parentIndex", "lodDist", "childLodDist",
                  "numChildren", "ambientOcclusionMultiplier", "artificialAmbientOcclusion",
                  "tintValue", "padding0"):
            d[t] = _val_of(blk, t)
        for t in ("archetypeName", "lodLevel", "priorityLevel"):
            d[t] = _txt_of(blk, t)
        out.append(d)
    return out


CONTRACT = {
    "ytyp": ("archetypes", ("name", "assetName", "assetType")),
    "ymap": ("entities", ("archetypeName", "position", "rotation", "lodLevel",
                          "scaleXY", "scaleZ")),
}


def roundtrip(kind, limit):
    """Reference XML -> dicts -> emit -> re-parse -> compare EVERY field, and separately assert the
    ImportMapArea contract fields survived, since those are what actually gate an import."""
    files = sorted(glob.glob(os.path.join(CORPUS, kind, "*.%s.xml" % kind)))[:limit]
    # ⛔ ZERO EVIDENCE IS NOT A PASS (2026-07-31). This printed "0 reference files, 0 items" and
    # returned success, so `--roundtrip --kind ymap` against a corpus holding no ymap/ dir
    # reported a clean gate having compared NOTHING - the same shape as a --prune that deletes
    # everything because it found no references. A harness that cannot see its subject must FAIL.
    if not files:
        print("=== %s round-trip: REFUSING - no reference files under %s/%s ===\n"
              "    A harness with no subject cannot pass. Point --corpus (or QUARRY_CORPUS) at a\n"
              "    reference tree that actually contains %s/*.%s.xml."
              % (kind, CORPUS, kind, kind, kind))
        return 1
    parse = parse_ytyp if kind == "ytyp" else parse_ymap
    emit = ytyp_xml if kind == "ytyp" else ymap_xml
    _container, must = CONTRACT[kind]

    nfile = nitem = count_bad = nempty = 0
    field_bad = collections.Counter()
    contract_bad = collections.Counter()
    for f in files:
        text = open(f, encoding="utf-8", errors="replace").read()
        src = parse(text)
        if not src:
            # HARD - A SKIPPED FILE IS NOT A PASSED FILE (2026-08-03). This was a bare `continue`,
            # a corpus whose files exist but parse to zero items compared NOTHING and still
            # printed the full green banner - proven by monkeypatching parse_ytyp to return []
            # against the real 1,707-file oracle: rc=0, "every field byte-identical".
            nempty += 1
            continue
        nfile += 1
        stem = os.path.basename(f)[:-len(".%s.xml" % kind)]
        back = parse(emit(stem, src))
        if len(back) != len(src):
            count_bad += 1
            continue
        for a, b in zip(src, back):
            nitem += 1
            for k in a:
                if a[k] is None:
                    continue          # tag absent in the reference; the emitter writes a default
                if a[k] != b.get(k):
                    # MLO fields are nested lists; a full repr would be pages long
                    field_bad[("%s: %r -> %r" % (k, a[k], b.get(k)))[:220]] += 1
            for k in must:
                if a.get(k) is not None and b.get(k) != a.get(k):
                    contract_bad[k] += 1

    print("=== %s round-trip: %s reference files, %s items ===" % (kind, f"{nfile:,}", f"{nitem:,}"))
    if nempty:
        print("  reference files that parsed to ZERO items (nothing compared): %d" % nempty)
    if nitem == 0:
        print("  STOP - REFUSING: %d reference file(s) present, but NOT ONE item was compared.\n"
              "     The zero-evidence law from the glob guard above applies to the ITEM count\n"
              "     too: a parser regression that returns [] must FAIL this gate, not pass it."
              % len(files))
        return 1
    print("  item-count mismatches : %d" % count_bad)
    print("  CONTRACT fields (%s): %s" % (", ".join(must),
          "ALL PRESERVED" if not contract_bad else "BROKEN %s" % dict(contract_bad)))
    if field_bad:
        print("  field differences (%s across %d distinct):"
              % (f"{sum(field_bad.values()):,}", len(field_bad)))
        for k, n in field_bad.most_common(12):
            print("    %6dx  %s" % (n, k))
    else:
        print("  every field byte-identical")
    # A DIFFERENCE THIS GATE PRINTED BUT DID NOT ACT ON (2026-08-03). `field_bad` was excluded from
    # the verdict, so an emitter regression outside the six CONTRACT tags - a dropped extension
    # field, a mis-spelled float, a reordered MLO room - printed its own diff and still exited 0,
    # and the printed line is the only thing that would have caught it. It is now fatal, which is
    # only safe because it was MEASURED first: across the whole 1,707-file / 159,034-item ytyp
    # oracle field_bad is 0, so this makes the gate stricter without making it red today. (ymap has
    # no reference tree on this machine, so its round-trip refuses on the glob guard regardless.)
    return 0 if not contract_bad and not count_bad and not field_bad else 1


def census(kind, limit):
    """Enumerate the enum-valued fields, so the decoder knows exactly which strings it must be able
    to produce - and so an unobserved code is recognised as unmeasured rather than guessed."""
    tags = ("lodLevel", "priorityLevel") if kind == "ymap" else ("assetType",)
    seen = {t: collections.Counter() for t in tags}
    types = collections.Counter()
    census_files = sorted(glob.glob(os.path.join(CORPUS, kind, "*.%s.xml" % kind)))[:limit]
    if not census_files:
        # same law as roundtrip: an empty census is "nothing looked", not "nothing there"
        print("=== %s enum census: REFUSING - no reference files under %s/%s ==="
              % (kind, CORPUS, kind))
        return 1
    for f in census_files:
        text = open(f, encoding="utf-8", errors="replace").read()
        for k, blk in _items(text, CONTRACT[kind][0]):
            types[k] += 1
            for t in tags:
                v = _txt_of(blk, t)
                if v is not None:
                    seen[t][v or "(empty)"] += 1
    print("=== %s enum census ===" % kind)
    print("  Item type= : " + ", ".join("%s(%s)" % (k, f"{n:,}") for k, n in types.most_common(6)))
    for t in tags:
        print("  %-14s " % t + ", ".join("%s(%s)" % (k, f"{n:,}")
                                         for k, n in seen[t].most_common(12)))
    return 0


def _hash_degraded(ours, theirs):
    """Which side of a name pair is the KNOWN `hash_XXXXXXXX` degradation - PROVEN, not assumed.

    Returns "ours", "ref", or None (a genuine disagreement that must still be scored).

    An unresolved name is a bounded degradation, not a decode error, so it must not be scored as a
    mismatch. But "starts with hash_" alone is NOT proof of that: a decoder that read the WRONG
    four bytes also emits a hash_ string, and simply excusing every hash_ would hide exactly the
    class of bug this harness exists to catch. So the excuse is earned by re-hashing the side that
    DID resolve and requiring it to equal the unresolved side's hash.
    """
    def _h(v):
        if isinstance(v, str) and v.startswith("hash_"):
            try:
                return int(v[5:], 16)
            except ValueError:
                return None
        return None
    ho, ht = _h(ours), _h(theirs)
    if ho is not None and ht is None and isinstance(theirs, str) and theirs:
        return "ours" if joaat(theirs) == ho else None
    if ht is not None and ho is None and isinstance(ours, str) and ours:
        return "ref" if joaat(ours) == ht else None
    return None


def verify_binary(kind, bin_dir, limit, names, strict=False):
    """Decode real BINARY ytyp/ymap and diff the emitted XML against the reference export for the
    same asset - the real test, and the one that can catch a decode error the round-trip cannot.

    Scored on the contract fields plus the numeric ones. Rows are only compared where both sides
    describe the same item, and a name that could not be reversed is reported separately rather
    than counted as a mismatch: an unresolved hash is a KNOWN, bounded degradation, not a bug.
    """
    files = sorted(glob.glob(os.path.join(bin_dir, "*.%s" % kind)))[:limit]
    if not files:
        # ⛔ ZERO SUBJECTS IS A BROKEN QUESTION (2026-08-03). This printed "no files" and returned
        # SUCCESS, so the harness the docstring calls "the real test, and the one that can catch a
        # decode error the round-trip cannot" has been reporting a clean pass while comparing
        # NOTHING - the ymap lane in particular ran compared-nothing for an unknown period.
        # ASCII-ONLY IS LOAD-BEARING IN A PRINT (2026-08-03): this line shipped with a U+26D4
        # glyph and every one of its runs died with UnicodeEncodeError on this machine's cp1252
        # console - the refusal text was destroyed and the deliberate `return 2` became a
        # traceback exit 1, i.e. a refusal that looked like an ordinary failure. Measured by
        # running --verify-binary at an empty dir. Keep printed strings ASCII (module docstring).
        print("STOP - %s binary verify: NO BINARIES in %s - a verification with no subject cannot "
              "pass. (A --xml extract leaves no binaries for converted types; point --verify-binary"
              " at a filebase extracted WITHOUT --xml for this kind.)" % (kind, bin_dir))
        return 2
    parse = parse_ytyp if kind == "ytyp" else parse_ymap
    key = "name" if kind == "ytyp" else "archetypeName"
    numeric = (("lodDist", "flags", "bsRadius", "hdTextureDist") if kind == "ytyp"
               else ("flags", "lodDist", "childLodDist", "numChildren", "scaleXY", "scaleZ"))
    strings = ("assetType", "assetName", "textureDictionary") if kind == "ytyp" \
        else ("lodLevel", "priorityLevel")
    # Vectors are compared too: a bsRadius that disagrees while bbMin/bbMax AGREE would mean a
    # decode error, whereas all of them moving together means the geometry changed between builds.
    vectors = ("bbMin", "bbMax", "bsCentre") if kind == "ytyp" else ("position", "rotation")

    nfile = matched = 0
    counts_ok = counts_bad = 0
    ok = collections.Counter()
    bad = collections.Counter()
    text_exact = collections.Counter()
    text_differs = collections.Counter()
    fmt_wrong = collections.Counter()
    drift_bits = collections.Counter()
    unresolved = 0
    # THE HEADLINE NUMBER WAS WRONG, NOT THE DECODER (2026-08-03). The docstring above promised
    # "a name that could not be reversed is reported separately rather than counted as a
    # mismatch", but only the PAIRING check honoured it - the field loop scored every
    # hash_XXXXXXXX against the oracle's resolved name as a defect. COST, measured on the 80-file
    # ytyp run against the reference exports: it printed "121,880 exact, 6,331 mismatched =
    # 95.062%" when the truth is 121,889 exact / 1 genuine (99.999%), the 6,330 excluded ones all
    # being names this filebase has no file for (assetName 6,324, textureDictionary 6). A standing
    # 5% error rate on the format's primary lane invites a hunt for a decode bug that is not there.
    degraded = collections.Counter()      # OUR value unresolved, proven equal by re-hashing theirs
    degraded_ref = collections.Counter()  # the ORACLE's value unresolved and ours resolved
    pair_degraded = collections.Counter()
    decode_fail = collections.Counter()
    # A BINARY WITH NO ORACLE WAS SKIPPED WITH NO COUNTER (2026-08-03), so "119 files paired" left
    # the reader to work out that 1 of the 120 asked for was never compared - and in the ymap lane,
    # where the oracle directory does not exist at all, EVERY file took this branch and the run
    # still printed a clean banner. Counted, so the size of what went unscored is on the report.
    no_oracle = 0
    for f in files:
        ref = os.path.join(CORPUS, kind, os.path.basename(f) + ".xml")
        if not os.path.exists(ref):
            no_oracle += 1
            continue
        try:
            xml, got_kind, w = convert(f, names)
        except Exception as e:
            decode_fail["%s: %s" % (type(e).__name__, e)] += 1
            continue
        if got_kind != kind:
            decode_fail["root struct says %s" % got_kind] += 1
            continue
        nfile += 1
        unresolved += w.warn.get("unresolved asset-name hash", 0)
        mine = parse(xml)
        theirs = parse(open(ref, encoding="utf-8", errors="replace").read())
        # PAIRING IS LOAD-BEARING. Matching by name is WRONG for ymap: one ymap holds many
        # entities sharing an archetypeName (50 copies of a lamppost), so a name lookup compares
        # instance A against an unrelated instance B and invents mismatches in scale/lodDist/
        # flags. When the counts agree, ARRAY ORDER is the true correspondence; only fall back to
        # name pairing (ytyp archetype names are unique within a file) when they do not.
        if len(mine) == len(theirs):
            counts_ok += 1
            pairs = list(zip(mine, theirs))
        else:
            counts_bad += 1
            if strict:
                # A differing item count PROVES the two sides describe different builds of the
                # asset. Scoring such a file measures corpus drift, not decoder accuracy.
                continue
            by_key = {t[key]: t for t in theirs if t.get(key)}
            pairs = [(m, by_key.get(m.get(key))) for m in mine]
        for m, t in pairs:
            if t is None:
                continue
            if m.get(key) and t.get(key) and m[key] != t[key]:
                # The old test excused OUR hash_ names unconditionally and excused the ORACLE's
                # not at all, so a reference export that itself degraded (ours
                # 'bh1_33_shop_lod', ref 'hash_C855767A') was thrown out as a pairing failure and
                # its whole item - ~10 fields - went unscored. Both sides are now excused only
                # when re-hashing the resolved side proves they name the same asset.
                side = _hash_degraded(m[key], t[key])
                if side is None:
                    bad["PAIRING: %s %r vs %r" % (key, m[key], t[key])] += 1
                    continue
                pair_degraded[side] += 1
            matched += 1
            for fld in numeric + strings + vectors:
                if t.get(fld) is None:
                    continue
                a_, b_ = m.get(fld), t.get(fld)
                same = (a_ == b_)
                if not same:
                    side = _hash_degraded(a_, b_)
                    if side == "ours":
                        degraded[fld] += 1
                        continue      # KNOWN bounded degradation - excluded from BOTH scores
                    if side == "ref":
                        degraded_ref[fld] += 1
                        continue
                # TEXT-exactness is scored separately from value-equality. A tolerant comparison
                # alone hid a real formatting defect in fmt_num for an entire session.
                if same:
                    text_exact[fld] += 1
                elif a_ is not None:
                    text_differs[fld] += 1
                    # THE DECISIVE SPLIT: does the reference's text parse back to the SAME
                    # float32 we decoded? Same bits => our FORMAT rule is wrong (our bug).
                    # Different bits => the two builds genuinely hold different bytes (drift).
                    # Without this split a raw text-diff percentage reads as a decoder defect.
                    for x, y in (zip(a_, b_) if isinstance(b_, tuple) else ((a_, b_),)):
                        if x == y:
                            # A vector is compared whole, so one bad component flags the tuple -
                            # attributing its MATCHING components too would inflate the count.
                            continue
                        try:
                            if f32(float(x)) == f32(float(y)):
                                fmt_wrong["%s: ours %s / ref %s" % (fld, x, y)] += 1
                            else:
                                drift_bits[fld] += 1
                        except (TypeError, ValueError):
                            pass
                if not same and a_ is not None:
                    try:                     # float TEXT differs in spelling, not in value
                        if isinstance(b_, tuple):
                            same = (len(a_) == len(b_) and all(
                                abs(float(x) - float(y)) <= max(1e-3, abs(float(y)) * 1e-4)
                                for x, y in zip(a_, b_)))
                        else:
                            same = abs(float(a_) - float(b_)) <= max(1e-4, abs(float(b_)) * 1e-5)
                    except (TypeError, ValueError):
                        same = False
                if same:
                    ok[fld] += 1
                else:
                    bad["%s: got %r want %r" % (fld, a_, b_)] += 1

    print("=== %s BINARY verify: %d files paired with a reference export ===" % (kind, nfile))
    if decode_fail:
        print("  DECODE FAILURES:")
        for k, n in decode_fail.most_common(6):
            print("    %4dx %s" % (n, k))
    print("  item-count agreement : %d files exact, %d differ" % (counts_ok, counts_bad))
    print("  items matched by %-14s %s" % (key, f"{matched:,}"))
    tot_ok, tot_bad = sum(ok.values()), sum(bad.values())
    print("  FIELD COMPARISONS    : %s exact, %s mismatched = %.3f%%"
          % (f"{tot_ok:,}", f"{tot_bad:,}", 100.0 * tot_ok / max(1, tot_ok + tot_bad)))
    te, td = sum(text_exact.values()), sum(text_differs.values())
    print("  TEXT-EXACT (spelling): %s of %s = %.3f%%   <- a tolerant compare alone cannot see "
          "a formatting defect" % (f"{te:,}", f"{te + td:,}", 100.0 * te / max(1, te + td)))
    nfmt, ndrift = sum(fmt_wrong.values()), sum(drift_bits.values())
    if nfmt or ndrift:
        print("    of the differing components: %s are SAME float32 bits spelled differently "
              "(OUR FORMAT RULE - a real bug), %s are DIFFERENT bits (build drift, not ours)"
              % (f"{nfmt:,}", f"{ndrift:,}"))
        for k, v in fmt_wrong.most_common(6):
            print("      FORMAT %5dx %s" % (v, k))
    for fld in numeric + strings + vectors:
        n_ok = ok[fld]
        n_bad = sum(v for k, v in bad.items() if k.startswith(fld + ":"))
        if n_ok or n_bad:
            print("    %-26s %7s ok  %5s bad" % (fld, f"{n_ok:,}", f"{n_bad:,}"))
    nd, ndr = sum(degraded.values()), sum(degraded_ref.values())
    if nd or ndr or pair_degraded:
        print("  EXCLUDED as the KNOWN hash_XXXXXXXX degradation (each one PROVEN by re-hashing "
              "the side that resolved - an unproven hash_ is still scored as a mismatch):")
        if nd:
            print("    ours unresolved, oracle resolved : %s  %s"
                  % (f"{nd:,}", dict(degraded)))
        if ndr:
            print("    ORACLE unresolved, ours resolved : %s  %s  <- we know more than the export"
                  % (f"{ndr:,}", dict(degraded_ref)))
        if pair_degraded:
            print("    item-pairing key excused         : %s"
                  % dict(pair_degraded))
    if unresolved:
        print("  unresolved asset-name hashes: %s (degrade to hash_XXXXXXXX; the ymap<->ytyp "
              "join still holds, only assetName lookups need a real name)" % f"{unresolved:,}")
    if bad:
        print("  top mismatches:")
        for k, n in bad.most_common(8):
            print("    %5dx %s" % (n, k))
    field_bad = sum(v for k, v in bad.items() if not k.startswith("PAIRING:"))
    pairing_bad = sum(v for k, v in bad.items() if k.startswith("PAIRING:"))
    if bad:
        print("    ^ of those %d: %d item-PAIRING (corpus build drift, NOT scored as our defect), "
              "%d field disagreement(s)" % (pairing_bad + field_bad, pairing_bad, field_bad))
    print("  binaries with no reference export: %d (read, never scored)" % no_oracle)

    # THE VERDICT. This function ended in a bare `return 0`: the harness its own docstring calls
    # "the real test, and the one that can catch a decode error the round-trip cannot" passed
    # whatever it found. Measured 2026-08-03: a ytyp run printing "6,331 mismatched = 95.062%"
    # exited 0, and so did a --kind ymap run that paired ZERO files, which is the state the ymap
    # lane has actually been in on this machine (no ymap/ oracle directory exists here).
    #
    # WHAT MAY FAIL IT is only what is provably OURS. Measured over the ytyp lane at --limit 400
    # (763,319 comparisons): every scored field was 0-bad, and all 6 entries in `bad` were item
    # PAIRING - two builds disagreeing about which archetype sits at an index, e.g. 'cs1_13_houses'
    # against 'sc1_props_combo0804_77_lod'. Failing on that would leave a healthy decoder
    # permanently red, and a gate that cries wolf is switched off by whoever hits it - which is how
    # the real regression later walks through. So pairing drift is reported and NOT fatal, while a
    # decode exception, a field that disagrees, a float spelled wrong for identical bits, and zero
    # evidence all are.
    if nfile == 0:
        print("  STOP - REFUSING: %d binary/binaries were read, but NOT ONE paired with a "
              "reference export under %s/%s. A verification that compared nothing cannot pass."
              % (len(files), CORPUS, kind))
        return 1
    return 1 if (decode_fail or field_bad or fmt_wrong) else 0


def main():
    ap = argparse.ArgumentParser(prog="meta2xml", description=__doc__.split("\n")[0])
    ap.add_argument("--roundtrip", action="store_true",
                    help="prove the emitter against the reference corpus")
    ap.add_argument("--census", action="store_true", help="enumerate enum-valued fields")
    ap.add_argument("--verify-binary", metavar="FILEBASE",
                    help="decode real binary ytyp/ymap under <FILEBASE>/00_base and diff the "
                         "emitted XML against the reference export for the same asset")
    ap.add_argument("--convert", nargs="*", metavar="PATH",
                    help="convert .ytyp/.ymap files (or a directory of them)")
    ap.add_argument("--out", help="output directory for --convert")
    ap.add_argument("--names", metavar="DIR", nargs="*", default=None,
                    help="directory tree(s) whose asset FILENAMES seed the joaat reverse table. "
                         "Include a tree holding the ytd, or textureDictionary cannot resolve.")
    ap.add_argument("--strict", action="store_true",
                    help="score ONLY files whose item count matches the reference; a differing "
                         "count proves build drift, so including them measures the corpus, not us")
    ap.add_argument("--kind", choices=("ytyp", "ymap", "both"), default="both")
    ap.add_argument("--limit", type=int, default=400)
    ap.add_argument("--corpus", metavar="DIR",
                    help="reference corpus root for --roundtrip/--census/--verify-binary "
                         "(default: the QUARRY_CORPUS environment variable)")
    a = ap.parse_args()
    global CORPUS
    if a.corpus:
        CORPUS = a.corpus
    kinds = ("ytyp", "ymap") if a.kind == "both" else (a.kind,)

    if a.convert is not None:
        if not a.out:
            ap.error("--convert needs --out")
        names = load_names(*a.names) if a.names else {}
        targets = []
        for p in a.convert:
            if os.path.isdir(p):
                targets += sorted(glob.glob(os.path.join(p, "*.ytyp")) +
                                  glob.glob(os.path.join(p, "*.ymap")) +
                                  glob.glob(os.path.join(p, "*.ymt")))
            else:
                targets.append(p)
        os.makedirs(a.out, exist_ok=True)
        nok = nfail = 0
        why = collections.Counter()
        warns = collections.Counter()
        for p in targets:
            try:
                xml, kind, w = convert(p, names)
            except Exception as e:
                why["%s: %s" % (type(e).__name__, e)] += 1
                nfail += 1
                continue
            warns.update(w.warn)
            stem = os.path.basename(p)
            for ext in (".ytyp", ".ymap", ".ymt"):
                if stem.lower().endswith(ext):
                    stem = stem[:-len(ext)]
            with open(os.path.join(a.out, "%s.%s.xml" % (stem, kind)), "w",
                      encoding="utf-8") as fh:
                fh.write(xml)
            nok += 1
        print("converted %d, failed %d -> %s" % (nok, nfail, a.out))
        for k, n in why.most_common(8):
            print("  %5dx %s" % (n, k))
        # HARD - A COUNTER NOBODY PRINTS IS A SILENT FAILURE (2026-08-03). `Walker.warn` is a real
        # decode-failure detector - dropped containers, unhandled types, short reads, missing
        # blocks - and this loop used to throw the walker away entirely (`_w`), so a file could
        # lose a whole container and still be reported as "converted". A conversion that dropped
        # data is NOT a clean conversion, so the loss is named and counted here, at the exit.
        unresolved = warns.pop("unresolved asset-name hash", 0)
        if warns:
            print("  DATA NOT CARRIED INTO THE XML - %s record(s)/field(s) dropped or undecoded:"
                  % f"{sum(warns.values()):,}")
            for k, n in warns.most_common(12):
                print("    %10s  %s" % (f"{n:,}", k))
        if unresolved:
            print("  unresolved asset-name hashes: %s (KNOWN bounded degradation to "
                  "hash_XXXXXXXX, not a decode failure)" % f"{unresolved:,}")
        # ⛔ PARTIAL FAILURE IS FAILURE (2026-08-03). This returned 0 unless EVERY file failed, so
        # 999 conversions failing out of 1,000 exited 0 and any CI or driver above it saw success.
        # And zero targets - a glob that matched nothing - also exited 0, the zero-evidence pass.
        if not targets:
            # ASCII (see the verify_binary refusal above): a non-ASCII glyph here killed this
            # refusal with UnicodeEncodeError on the cp1252 console instead of printing it.
            print("STOP - no .ytyp/.ymap/.ymt matched: a run with nothing to convert is not a "
                  "pass")
            return 2
        return 1 if nfail else 0

    if not (a.roundtrip or a.census or a.verify_binary):
        ap.error("give --roundtrip, --census, --verify-binary or --convert")
    if not (CORPUS and os.path.isdir(CORPUS)):
        ap.error("the verification harnesses need the reference corpus: pass --corpus DIR or "
                 "set QUARRY_CORPUS (layout: <corpus>/<kind>/*.<kind>.xml)")
    rc = 0
    for k in kinds:
        if a.census:
            rc |= census(k, a.limit)
        if a.roundtrip:
            rc |= roundtrip(k, a.limit)
        if a.verify_binary:
            names = load_names(*(a.names or [a.verify_binary]))
            rc |= verify_binary(k, os.path.join(a.verify_binary, "00_base", k), a.limit,
                                names, a.strict)
    return rc


if __name__ == "__main__":
    sys.exit(main())
