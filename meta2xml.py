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
    "CMapData", "CEntityDef", "CMloInstanceDef", "entities", "parent", "contentFlags",
    "streamingExtentsMin", "streamingExtentsMax", "entitiesExtentsMin", "entitiesExtentsMax",
    "archetypeName", "guid", "position", "rotation", "scaleXY", "scaleZ", "parentIndex",
    "childLodDist", "lodLevel", "numChildren", "priorityLevel",
    "ambientOcclusionMultiplier", "artificialAmbientOcclusion", "tintValue",
    # enum members - measured from the corpus census, so the symbolic strings are reproducible
    "ASSET_TYPE_UNINITIALIZED", "ASSET_TYPE_FRAGMENT", "ASSET_TYPE_DRAWABLE",
    "ASSET_TYPE_DRAWABLEDICTIONARY", "ASSET_TYPE_ASSETLESS",
    "LODTYPES_DEPTH_HD", "LODTYPES_DEPTH_LOD", "LODTYPES_DEPTH_SLOD1", "LODTYPES_DEPTH_SLOD2",
    "LODTYPES_DEPTH_SLOD3", "LODTYPES_DEPTH_ORPHANHD",
    "PRI_REQUIRED", "PRI_OPTIONAL_HIGH", "PRI_OPTIONAL_MEDIUM", "PRI_OPTIONAL_LOW",
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
                    return None
                sz, f = PRIM[ed["type"]]
                return [struct.unpack_from("<" + f, buf, o + i * sz)[0]
                        for i in range(e["refKey"])]
            if t == T_STRUCT:
                return self.struct(e["refKey"], buf, o)
            if t == T_STRING:
                return self.string(buf, o)
            if t == T_HASH:
                return self.asset_name(struct.unpack_from("<I", buf, o)[0])
            if t in (T_ENUM, T_FLAGS):
                return self.enum(e, struct.unpack_from("<I", buf, o)[0], t)
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
    L.append(_txt("assetType", a.get("assetType"), "   "))
    L.append(_txt("assetName", a.get("assetName"), "   "))
    L += extensions_xml(a.get("extensions") or [], "   ")
    L.append(_val("padding0", pick(a, "padding0", 0), "   "))
    L.append(_val("padding1", pick(a, "padding1", 0), "   "))
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


def ytyp_xml(name, archetypes):
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
    L.append(_val("padding0", pick(e, "padding0", 0), f))
    L.append("%s</Item>" % ind)
    return L


EMPTY_CONTAINERS = (
    ' <containerLods itemType="rage__fwContainerLodDef" />',
    ' <boxOccluders itemType="BoxOccluder" />',
    ' <occludeModels itemType="OccludeModel" />',
    " <physicsDictionaries />",
    " <instancedData>",
    "  <ImapLink />",
    '  <PropInstanceList itemType="rage__fwPropInstanceListDef" />',
    '  <GrassInstanceList itemType="rage__fwGrassInstanceListDef" />',
    " </instancedData>",
    ' <timeCycleModifiers itemType="CTimeCycleModifier" />',
    ' <carGenerators itemType="CCarGen" />',
    " <LODLightsSOA>",
    '  <direction itemType="FloatXYZ" />',
    "  <falloff />", "  <falloffExponent />", "  <timeAndStateFlags />", "  <hash />",
    "  <coneInnerAngle />", "  <coneOuterAngleOrCapExt />", "  <coronaIntensity />",
    " </LODLightsSOA>",
    " <DistantLODLightsSOA>",
    '  <position itemType="FloatXYZ" />', "  <RGBI />",
    '  <numStreetLights value="0" />', '  <category value="0" />',
    " </DistantLODLightsSOA>",
)


def ymap_xml(name, entities, meta=None):
    m = meta or {}
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
    L += list(EMPTY_CONTAINERS)
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


def convert_bytes(blob, stem, names=None):
    """binary ytyp/ymap/ymt -> (xml, kind, walker). Kind comes from the ROOT STRUCT, not the
    file extension, so a mislabelled file cannot be emitted as the wrong schema."""
    w = Walker(MetaFile(blob), names=names)
    root_name, root = w.root()
    if root_name == "CMapTypes":
        return ytyp_xml(root.get("name") or stem, archetypes_from(root)), "ytyp", w
    if root_name == "CMapData":
        return (ymap_xml(root.get("name") or stem, entities_from(root), ymap_meta_from(root)),
                "ymap", w)
    if root_name == "CScenarioPointRegion":
        return scenario_xml(scenario_from(root)), "ymt", w
    raise ValueError("unexpected META root struct %r" % root_name)


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
    """
    names = {}
    for root in roots:
        if not root or not os.path.isdir(root):
            continue
        for dirpath, _dirs, files in os.walk(root):
            for f in files:
                stem = f.split(".")[0]
                if stem:
                    names.setdefault(joaat(stem), stem.lower())
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
    parse = parse_ytyp if kind == "ytyp" else parse_ymap
    emit = ytyp_xml if kind == "ytyp" else ymap_xml
    _container, must = CONTRACT[kind]

    nfile = nitem = count_bad = 0
    field_bad = collections.Counter()
    contract_bad = collections.Counter()
    for f in files:
        text = open(f, encoding="utf-8", errors="replace").read()
        src = parse(text)
        if not src:
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
    return 0 if not contract_bad and not count_bad else 1


def census(kind, limit):
    """Enumerate the enum-valued fields, so the decoder knows exactly which strings it must be able
    to produce - and so an unobserved code is recognised as unmeasured rather than guessed."""
    tags = ("lodLevel", "priorityLevel") if kind == "ymap" else ("assetType",)
    seen = {t: collections.Counter() for t in tags}
    types = collections.Counter()
    for f in sorted(glob.glob(os.path.join(CORPUS, kind, "*.%s.xml" % kind)))[:limit]:
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


def verify_binary(kind, bin_dir, limit, names, strict=False):
    """Decode real BINARY ytyp/ymap and diff the emitted XML against the reference export for the
    same asset - the real test, and the one that can catch a decode error the round-trip cannot.

    Scored on the contract fields plus the numeric ones. Rows are only compared where both sides
    describe the same item, and a name that could not be reversed is reported separately rather
    than counted as a mismatch: an unresolved hash is a KNOWN, bounded degradation, not a bug.
    """
    files = sorted(glob.glob(os.path.join(bin_dir, "*.%s" % kind)))[:limit]
    if not files:
        print("=== %s binary verify: no files in %s ===" % (kind, bin_dir))
        return 0
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
    decode_fail = collections.Counter()
    for f in files:
        ref = os.path.join(CORPUS, kind, os.path.basename(f) + ".xml")
        if not os.path.exists(ref):
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
            if m.get(key) and t.get(key) and m[key] != t[key] and not m[key].startswith("hash_"):
                bad["PAIRING: %s %r vs %r" % (key, m[key], t[key])] += 1
                continue
            matched += 1
            for fld in numeric + strings + vectors:
                if t.get(fld) is None:
                    continue
                a_, b_ = m.get(fld), t.get(fld)
                same = (a_ == b_)
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
    if unresolved:
        print("  unresolved asset-name hashes: %s (degrade to hash_XXXXXXXX; the ymap<->ytyp "
              "join still holds, only assetName lookups need a real name)" % f"{unresolved:,}")
    if bad:
        print("  top mismatches:")
        for k, n in bad.most_common(8):
            print("    %5dx %s" % (n, k))
    return 0


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
        for p in targets:
            try:
                xml, kind, _w = convert(p, names)
            except Exception as e:
                why["%s: %s" % (type(e).__name__, e)] += 1
                nfail += 1
                continue
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
        return 1 if nfail and not nok else 0

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
