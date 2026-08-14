"""ydr2xml - binary GTA V .ydr (RSC7 v165)  ->  RAGE interchange .ydr.xml

WHY THIS EXISTS
RUDE's importer already reads the interchange XML and is proven in-engine on 1,144 meshes with materials,
collision, LODs and textures. QUARRY was emitting raw BINARY, which RUDE cannot read - so work was
being duplicated rebuilding readers the XML pipeline already had. Emitting XML reuses all of it.
Nothing about the game is being modified: this converts the operator's own extracted files.

WHAT IS GROUNDED, AND IN WHAT
  * container + drawable graph + vertex declaration table: measured over all 3,479 real base-game
    v165 ydrs / 17,370 geometries (maintainer's engineering log, "ydr VERTEX DECLARATION"). Channels sit in
    ASCENDING BIT ORDER, offset = sum of sizes of lower set bits; the grcFvf u64 is a 16-slot TYPE
    TABLE indexed by channel bit (hence constant 0x7755555555996996 in 17,370/17,370).
  * XML shape: measured over 25,936 third-party reference exports (maintainer's log, "ydr.xml schema"). Their `Data` field order ==
    the `Layout` child order == ascending bit order, so the mapping is 1:1 with no reordering.
  * shader preset names: the binary stores only joaat(name), which is one-way, so names come from
    joaat_shaders.json (216 presets inverted from the operator's own third-party reference exports).
  * sampler (texture param) names + RenderBucket: derived from the shader struct itself and
    validated against 866 third-party full-parameter reference exports by joining params BY NAME -
    bucket 99.989% (9,166/9,167), texture names 99.960%, vector values 99.933%, arrays 100%
    (residuals = game-build drift). See read_shaders and reports/sampler_derivation_2026-07-28.md.

DELIBERATE OMISSIONS (safe - verified against the consumer, not guessed)
UE 5.8's FindChildNode is DIRECT-CHILDREN-ONLY, so a missing element yields nullptr and can never
silently match something deeper. We therefore emit the minimal set the importer actually reads and
skip: LodDist*/Flags*, Lights, Skeleton, Medium/Low LOD groups, Shaders/Item/FileName,
VertexBuffer/Flags, per-geometry bboxes, model RenderMask/Flags/HasSkin/BoneIndex/Unknown1, BoneIDs,
and every Vector/Array shader param.
Whitespace, float precision and indices-per-line are all free: FXmlFile treats every whitespace char
as a delimiter and rejoins content with single spaces, so only TOKEN COUNT and ORDER matter.

<Bounds> (embedded collision) IS EMITTED (2026-07-28): the phBound graph at drawable +0xC8,
faithful to the reference exports (ybn oracle: 183/183 name-matched pairs, 0 same-bits text
diffs, 87 files byte-identical, all residuals proven different-float32-bits build drift).
NO SILENT DEFAULTS: any unmeasured bound/polygon type code, set-but-unnamed flag bit, or
non-zero byte in a lane only ever measured zero REFUSES the file loudly (BoundsError).
✅ CONSUMER NOTE - RESOLVED 2026-07-31, KEPT AS A WARNING. 220 of 1,012 base-game bound-bearing
ydr have a NON-Composite root (Box 160 / Sphere 53 / Cylinder 7; re-measured over all 3,479 base
ydr on 2026-08-02) which this emitter reproduces faithfully. ExportYtyp used to read collidability
off Bounds/Children, which only a Composite root has, so a fifth of all collidable props exported
with the bit clear. It now treats any known non-Composite root as collision
(RudeToolset.cpp:3925-3938, read 2026-08-03). ⛔ DO NOT "fix" this emitter-side by wrapping
primitives in a Composite: it would defeat the now-correct consumer rule AND fabricate
CompositeFlags the source never carried, i.e. invented filter bits in exported collision.

Usage:
    python ydr2xml.py <in.ydr> [more.ydr ...] --out <dir>
    python ydr2xml.py --selftest      # convert + reparse, no files written
"""
import argparse
import collections
import json
import os
import struct
import sys
import zlib

from meta2xml import fmt_num, joaat   # THE proven float-text rule (7->9 sig digits,
                                      # ties away from zero) - single implementation

# ---------------------------------------------------------------- refusal accounting

# ⛔ A DROP WITH NO COUNTER IS INDISTINGUISHABLE FROM "NOTHING TO DO" (2026-08-03).
# Every place this module declined to emit something used to do it silently: a bare `continue`,
# a `return []`, or `except Exception: return []`. Measured today the rate is ZERO on real data
# (3,479 base ydr: 13,693 declared geometries / 13,693 kept, 1,180/1,180 embedded dictionaries
# decoded; 3,000 base yft: 12,032/12,032 main + 568/568 child geometries) - so what follows costs
# nothing and buys the one thing the silence removed: the ability to tell a clean run from a
# lossy one. The importer already fixed this shape on its side (RudeToolset.cpp:1745-1780,
# "a skip with no counter is indistinguishable from nothing to do"); this is the emitter half.
# ⭐ COUNTERS ARE PROCESS-GLOBAL AND ACCUMULATE ACROSS A WHOLE RUN. quarry surfaces them with a
# single call - see report_refusals() for the exact line.
REFUSALS = collections.Counter()
REFUSAL_NOTES = []                    # sample "<key>: <detail>" lines, for humans
_NOTES_PER_KEY = 3                    # per KEY, not global: one noisy counter must not crowd
_NOTED = collections.Counter()        # the one rare decline you actually needed to see


def _refuse(key, detail=None):
    """Count a decline-to-emit, and keep a few named examples per kind.
    Never raises - the caller decides whether the drop is survivable."""
    REFUSALS[key] += 1
    if detail is not None and _NOTED[key] < _NOTES_PER_KEY:
        _NOTED[key] += 1
        REFUSAL_NOTES.append("%s: %s" % (key, detail))


def report_refusals(stats=None, stream=None):
    """Fold the run-global emitter counters into `stats` and print them. Prints NOTHING when
    every counter is zero, so a clean run stays clean. Covers ydd and yft too - both emit through
    drawable_lines, and yft2xml counts its own declines into the SAME table, so one call reports
    the whole interchange-XML lane rather than a third of it.

    ⭐ THE ONE LINE QUARRY NEEDS (quarry.py cmd_extract, inside `if getattr(a, 'xml', False):`,
    after the xml_errors loop):
            ydr2xml.report_refusals(stats)
    That is the whole wiring. The counters live here rather than being threaded through
    to_interchange_xml's per-file `stats` because a drop happens six frames below that call and
    the intermediate functions return lines, not diagnostics - passing a dict down all of them
    was the change most likely to be half-done and then trusted.

    ⚠ A COUNT IS A DECLINE, NOT A FILE. quarry's ydr branch reads the embedded dictionary once
    itself and once more inside to_xml, so one bad dictionary scores 2. Read these as "how much
    was declined", never as "how many assets are affected" - the notes carry the names.
    """
    if stats is not None:
        for k, v in REFUSALS.items():
            stats["emitter_" + k] = stats.get("emitter_" + k, 0) + v
        if REFUSAL_NOTES:
            stats.setdefault("emitter_refusal_notes", []).extend(REFUSAL_NOTES)
    if not REFUSALS:
        return
    out = stream if stream is not None else sys.stdout
    print("emitter declined to emit (run totals):", file=out)
    for k, v in sorted(REFUSALS.items()):
        print("    %-46s %d" % (k, v), file=out)
    for line in REFUSAL_NOTES:
        print("      e.g. %s" % line, file=out)


# ---------------------------------------------------------------- container

PAGE_BITS = {0: 27, 1: 26, 2: 25, 3: 24, 4: 17, 5: 11, 6: 7, 7: 5, 8: 4}
PAGE_MASK = {0: 1, 1: 1, 2: 1, 3: 1, 4: 0x7F, 5: 0x3F, 6: 0xF, 7: 3, 8: 1}


def seg_size(flags):
    """Total bytes described by an RSC7 flag word's page plan."""
    f = flags & 0x0FFFFFFF
    base = 0x200 << (f & 0xF)
    return sum(((f >> PAGE_BITS[k]) & PAGE_MASK[k]) * (base << k) for k in range(9))


class Res:
    """An inflated RSC7 resource: system + graphics segments, with tagged-pointer resolution."""

    @classmethod
    def from_bytes(cls, blob):
        """Parse an in-memory resource - used when converting during extraction, so a file never
        has to be written to disk just to be read back."""
        self = cls.__new__(cls)
        self._load(blob)
        return self

    name = None          # set when loaded from a path, so a refusal note can say WHICH file

    def __init__(self, path):
        self.name = os.path.basename(path)
        self._load(open(path, "rb").read())

    def _load(self, blob):
        if len(blob) < 16 or blob[:4] != b"RSC7":
            raise ValueError("not an RSC7 container")
        _, self.version, sysf, gfxf = struct.unpack_from("<4sIII", blob, 0)
        ssz, gsz = seg_size(sysf), seg_size(gfxf)
        raw = zlib.decompress(blob[16:], -15)
        if len(raw) < ssz:
            raise ValueError("inflated payload shorter than the declared system segment")
        self.sys = raw[:ssz]
        self.gfx = raw[ssz:ssz + gsz]

    def ptr(self, off):
        return struct.unpack_from("<I", self.sys, off)[0]

    def deref(self, tagged, need=0):
        """Tagged pointer -> (buffer, offset). High nibble 5 = system, 6 = graphics."""
        tag, o = tagged >> 28, tagged & 0x0FFFFFFF
        buf = self.sys if tag == 5 else (self.gfx if tag == 6 else None)
        if buf is None or o < 0 or o + need > len(buf):
            return None, 0
        return buf, o

    def u16(self, off):
        return struct.unpack_from("<H", self.sys, off)[0]

    def u32(self, off):
        return struct.unpack_from("<I", self.sys, off)[0]

    def cstr(self, tagged, limit=160):
        """⛔ TWO SILENT FAILURES USED TO LOOK LIKE A SHORT NAME (counted 2026-08-03). A pointer
        that does not resolve returned "", and a string with no NUL inside `limit` was TRUNCATED
        to 160 bytes and returned as if it were the name - so a shader texture binding, a bone or
        a fragment could be renamed by a decode failure and nothing anywhere would say so.
        Measured 0 of both over 9,342 strings (8,042 bone names + 800 fragment names + 500 ydr
        drawable names, drawlane/silentsites.py). A plain NULL pointer is NOT counted: it fires on
        100% of fragments (the +0xA8 drawable name) and a counter nobody can ever see at zero is
        worse than none."""
        if tagged == 0:
            return ""
        buf, o = self.deref(tagged, 1)
        if buf is None:
            _refuse("cstr_pointer_unresolved", "0x%08x in %s" % (tagged, self.name or "?"))
            return ""
        end = buf.find(b"\x00", o)
        if end < 0 or end - o > limit:
            _refuse("cstr_truncated_no_NUL_within_%d" % limit, self.name or "?")
            end = min(o + limit, len(buf))
        return buf[o:end].decode("latin-1")

    def require_version(self, want, what):
        """Version lives in the container but MEANS a type: 165 ydr, 43 ybn, 13 ytd, 2 meta.
        Checked by the per-type converter, not by _load, so one container class serves all."""
        if self.version != want:
            extra = " (159 = GTA V Enhanced, not Legacy)" if self.version == 159 else ""
            raise ValueError(f"RSC7 version {self.version} is not a {what}, want {want}{extra}")


# ---------------------------------------------------------------- vertex declaration

# bit -> (interchange Layout child name, token count). Ascending bit order IS the field order.
CHANNELS = {
    0:  ("Position", 3),
    1:  ("BlendWeights", 4),
    2:  ("BlendIndices", 4),
    3:  ("Normal", 3),
    4:  ("Colour0", 4),
    5:  ("Colour1", 4),
    6:  ("TexCoord0", 2), 7: ("TexCoord1", 2), 8: ("TexCoord2", 2), 9: ("TexCoord3", 2),
    10: ("TexCoord4", 2), 11: ("TexCoord5", 2), 12: ("TexCoord6", 2), 13: ("TexCoord7", 2),
    14: ("Tangent", 4),
    15: ("Binormal", 4),
}
# grcFvf nibble -> byte size. 5/6/7/9 measured over the map-prop corpus (17,370 geometries);
# 1/3/A measured over the whole-game yft+ydd corpus (79,830 files / 649,976 geometries,
# 2026-07-28) and VALUE-validated against 1,669 name-matched third-party reference exports:
#   0x1 = half2   (TexCoord0; size isolated in 743 stride equations; halves match the
#                  reference floats within half-ULP on 555k tokens)
#   0x3 = half4   (Tangent) and 0xA = signed-byte4 /127 (Normal) - the two always co-occur
#                  (1,074 equations, sizes sum to 12); the 4+8 split is fixed by Colour0
#                  realigning EXACTLY at Normal=4, and the Normal decode is bit-exact vs
#                  the reference in 91 whole files.
# Anything else must still REFUSE: guessing a size silently scrambles every vertex after
# the first.
NIBBLE_SIZE = {1: 4, 3: 8, 5: 8, 6: 12, 7: 16, 9: 4, 0xA: 4}
INT_CHANNELS = {1, 2, 4, 5}          # ubyte4: emitted as 0-255 INTEGERS, never 0-1 floats


def build_decl(mask, nibbles, declared_stride):
    """-> (fields, stride). fields = [(bit, name, tokens, offset, size, nibble)] in ascending
    bit order."""
    fields, off = [], 0
    for bit in range(16):
        if not (mask >> bit) & 1:
            continue
        nb = (nibbles >> (bit * 4)) & 0xF
        size = NIBBLE_SIZE.get(nb)
        if size is None:
            raise ValueError(f"unsupported channel type: mask 0x{mask:x} bit {bit} nibble 0x{nb:x}")
        if bit not in CHANNELS:
            raise ValueError(f"unknown channel bit {bit} in mask 0x{mask:x}")
        name, tokens = CHANNELS[bit]
        fields.append((bit, name, tokens, off, size, nb))
        off += size
    if off != declared_stride:
        raise ValueError(f"computed stride {off} != declared {declared_stride} (mask 0x{mask:x})")
    return fields, off


def fmt_float(v):
    """Delegates to THE float-text law (meta2xml.fmt_num): 7-else-9 significant digits,
    ties away from zero, %G fixed/scientific thresholds, uppercase signed exponent.

    ⛔ The old body - `repr(round(v, 8))` - was a REAL SHIPPED DEFECT twice over
    (measured 2026-08-05 against the oracle set, 128,289/128,289 paired spellings):
    wrong spelling on every non-integral value, AND real precision loss below ~1e-4
    (8 DECIMAL places turns -1.62920685E-07 into 2 significant digits). 1,772 vertex
    Data-stream values in one sweep alone did not round-trip to their own float32.
    fmt_num snaps to float32 itself; ints and strings pass through it unchanged."""
    return fmt_num(v)


def decode_vertices(res, vdata_tagged, count, stride, fields):
    buf, base = res.deref(vdata_tagged, count * stride)
    if buf is None:
        raise ValueError("vertex data does not resolve")
    lines = []
    for v in range(count):
        vb = base + v * stride
        groups = []
        for bit, _name, tokens, off, size, nb in fields:
            at = vb + off
            if bit in INT_CHANNELS:
                # ⛔ THE (CHANNEL, NIBBLE) PAIRING WAS NEVER CHECKED (fixed 2026-08-03). This
                # branch fired on the channel BIT alone and read `tokens` bytes; the float branch
                # below read tokens*4 bytes - both regardless of the nibble's declared `size`,
                # which is the ONLY thing build_decl uses for offsets and the stride equation.
                # So a file pairing e.g. nibble 9 (4 B) with Position (3 float32 = 12 B) would
                # read 8 bytes past the field into the next channel, `off == declared_stride`
                # would still balance, and the file would convert as a clean success with
                # scrambled vertices - invisible to import ok:true, geometry counts and bbox
                # alike. MEASURED over 3,479 base ydr + 3,000 base yft (16,600 geometries,
                # every pairing the game actually ships): bits 1/2/4/5 are ubyte4 nibble 9 in
                # 100% of cases, so this guard has never fired and costs nothing.
                if nb != 9 or tokens > size:
                    raise ValueError("channel bit %d (%s) is ubyte4 x%d but nibble 0x%x "
                                     "declares %d bytes" % (bit, _name, tokens, nb, size))
                vals = [str(buf[at + i]) for i in range(tokens)]
            else:
                if nb in (1, 3):
                    # half-float pair/quad (cloth TexCoord0 / Tangent) - value-validated
                    # against third-party reference exports within half-ULP
                    if size // 2 < tokens:
                        raise ValueError("nibble 0x%x holds %d halves, channel bit %d (%s) "
                                         "wants %d" % (nb, size // 2, bit, _name, tokens))
                    raw = struct.unpack_from("<%de" % (size // 2), buf, at)
                elif nb == 0xA:
                    # signed-byte4 normalized /127 (cloth Normal) - bit-exact vs the reference; the
                    # channel emits 3 tokens, the 4th byte (w) is dropped below
                    if size < 4:
                        raise ValueError("nibble 0xA reads 4 bytes but declares %d" % size)
                    raw = [max(by - 256 if by > 127 else by, -127) / 127.0
                           for by in buf[at:at + 4]]
                elif nb in (5, 6, 7):
                    # float32 xN. `size` MUST cover the read or the unpack walks into the next
                    # channel - see the ubyte4 note above; measured true in 16,600/16,600.
                    if size != tokens * 4:
                        raise ValueError("nibble 0x%x is %d B but channel bit %d (%s) wants "
                                         "%d float32" % (nb, size, bit, _name, tokens))
                    raw = struct.unpack_from("<%df" % tokens, buf, at)
                else:
                    # NIBBLE_SIZE knows this nibble's width (build_decl passed it) but this
                    # decoder has no rule for its CONTENT - guessing float32 is how a whole
                    # drawable family would emit scrambled vertices as a success.
                    raise ValueError("channel bit %d (%s) nibble 0x%x has no decode rule"
                                     % (bit, _name, nb))
                # real shipped assets contain literal NaN (e.g. prop_dock_crane_01) and UE's mesh
                # builder chokes on NaN UVs, so neutralise here rather than downstream.
                # ⛔ COUNTED BY CHANNEL, AND POSITION REFUSES (2026-08-03). The substitution used
                # to be an invisible inline conditional. Measured: 1,333 substitutions over
                # 3,479 base ydr (933 Tangent + 400 TexCoord0, all in prop_dock_crane_01) and
                # 5,320 over 3,000 base yft (all TexCoord1, 7 `_hi` vehicles) - ZERO in Position
                # in either. A NaN normal or UV neutralises to something harmless; a NaN POSITION
                # would silently snap a vertex to the world origin and stretch a triangle across
                # the map, readable downstream as a placement or importer bug rather than as
                # corrupt source data. Nothing measured is lost by refusing it.
                # Token COUNT follows the declaration's component count, not the CHANNELS
                # default. nibble 0xA (signed-byte4) carries 4 components and the reference exporter emits all 4:
                # the yft-cloth GTAV2 oracle spells its byte4 Normal as "1 0 0 0" (4 tokens),
                # not "1 0 0" (2026-08-06, plg_01_* fragments). The old drop-the-w behaviour was
                # tuned to a since-deleted reference; it is unwitnessed by any current oracle
                # (all 264 ydr/ydd oracle layouts are GTAV1 = float3 normals, nibble 6 - none use
                # nibble 0xA), so widening 0xA to 4 tokens cannot touch a passing ydr/ydd file.
                emit_n = 4 if nb == 0xA else tokens
                vals = []
                for x in raw[:emit_n]:
                    if x != x or abs(x) == float("inf"):
                        # ⭐ NaN AND Infinity ARE WITNESSED VERBATIM (densify oracles
                        # 2026-08-08: gt750 TexCoord1 prints `Infinity`; polbuffalo TexCoord
                        # prints `NaN`) — the old substitute-0-for-NaN rule was a parity
                        # break; its boards simply carried no NaN witness. Faithful
                        # interchange here; consumers handle non-finite UVs at import.
                        # COUNTED so the class stays visible; Position still refuses loudly
                        # (no witness of a non-finite Position exists).
                        if _name == "Position":
                            raise ValueError("NaN/inf in the Position channel (vertex %d)" % v)
                        _refuse("nonfinite_emitted_verbatim:" + _name)
                        vals.append("NaN" if x != x else
                                    ("Infinity" if x > 0 else "-Infinity"))
                        continue
                    vals.append(fmt_float(x))
            groups.append(" ".join(vals))
        lines.append("   ".join(groups))
    return lines


# ---------------------------------------------------------------- shader names

_SHADERS = None

# ⛔ THE NAME TABLES USED TO FAIL OPEN (fixed 2026-08-03). Both resolvers wrapped their load in a
# bare `except`, so a missing or corrupt table made EVERY preset and EVERY value parameter degrade
# to hash_%08X while the conversion still reported success, exit 0. Proven by patching json.load
# to raise: preset_name(0x2f8bc40d) returned 'hash_2F8BC40D' with no exception, no warning and no
# counter. That is not a cosmetic loss - RUDE GENERATES its materials from the preset name, so an
# absent joaat_shaders.json silently routes the whole corpus to fallback masters and the only
# symptom is "everything looks generic", which reads as a material-quality problem rather than a
# missing file. It would also reset the "100% named value params" figure to 0% with every gate
# still green.
# The two tables are NOT equally optional, and that distinction is the fix:
#   joaat_shaders.json      216 presets, THE ONLY source of preset names -> absent = 100%
#                           degradation with no fallback at all -> REQUIRED, refuse.
#   shader_param_names.json 5,058 generated names -> absent leaves the 50 hand-verified
#                           VALUE_PARAM_NAMES working, a real if partial fallback -> counted,
#                           warned, and flagged; never silent.
# Either table PRESENT BUT UNREADABLE always refuses: a corrupt table is a broken install, not a
# lean one.
NAME_TABLES_DEGRADED = []             # names of optional tables that were missing this run


class NameTableError(RuntimeError):
    """A shipped name table is missing (when required) or unreadable. Loud on purpose: naming
    every hash `hash_XXXXXXXX` and exiting 0 is the failure this class exists to prevent."""


def _load_name_table(fname, required):
    """-> dict, or None when an OPTIONAL table is simply absent (counted + warned)."""
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), fname)
    if not os.path.exists(p):
        if required:
            raise NameTableError(
                "%s is missing - it is the only source of shader preset names, so every "
                "material would be generated from hash_XXXXXXXX. Refusing." % fname)
        if fname not in NAME_TABLES_DEGRADED:
            NAME_TABLES_DEGRADED.append(fname)
            print("WARN %s is missing: value-parameter naming falls back to the %d "
                  "hand-verified names only" % (fname, len(VALUE_PARAM_NAMES)),
                  file=sys.stderr)
        _refuse("name_table_MISSING:" + fname)
        return None
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        raise NameTableError("%s is present but does not load (%s: %s) - a corrupt name table "
                             "silently renames every shader. Refusing."
                             % (fname, type(e).__name__, e))


def preset_name(hash32):
    """joaat is one-way, so recover the preset name from the table built off third-party reference exports."""
    global _SHADERS
    if _SHADERS is None:
        _SHADERS = _load_name_table("joaat_shaders.json", required=True)
        # oracle-derived preset names (2026-08-06): presets the 216-name table lacks
        # but the reference exports SPELL (clouds_animsoft etc.) - the oracle is the
        # spec, so its own strings are first-class vocabulary
        osn = _load_name_table("oracle_shader_names.json", required=False) or {}
        for n in osn.get("names", []):
            _SHADERS.setdefault("0x%08x" % _joaat(n.lower()), n)
    nm = _SHADERS.get("0x%08x" % hash32)
    if nm:
        return nm
    # Not a failure by itself - 53 of ~33k shader items across 3,479 base ydr resolve to no
    # known preset (10 distinct hashes) and the consumer clamps them to a fallback master. It IS
    # the number that would jump to "all of them" if the table ever stopped loading, so it is
    # counted rather than assumed.
    _refuse("preset_name_unresolved", "0x%08X" % hash32)
    return "hash_%08X" % hash32


_SPS = None


def sps_filename(hash32, preset):
    """Shader entry +0x18 holds joaat of the preset FILENAME - the '.sps' extension is
    INSIDE the hashed string, and it is stored separately from the +0x08 name hash.
    Derived 2026-08-05: plg_01_props_dtr1_002's shader has Name=default (+0x08 =
    joaat('default') @sys+3096) with joaat('cutout.sps') 16 bytes later; across the
    oracle set 188/192 shaders spell FileName == Name + '.sps' and 4 (the cutout
    defaults) do not, so the filename can never be derived from the name. Resolved from
    the same preset table with '.sps' appended; an unresolved hash is COUNTED and
    emitted as hash text - never guessed."""
    global _SPS
    if _SPS is None:
        tab = _load_name_table("joaat_shaders.json", required=True)
        _SPS = {joaat(n + ".sps"): n + ".sps" for n in tab.values()}
        # ⭐ GAME-SOURCED FILENAMES WIN (2026-08-07). The preset table above is seeded from
        # REFERENCE EXPORTS - names transcribed from another tool's output - and covers 216
        # presets. The game itself SHIPS the .sps files (common.rpf/shaders/db 391 +
        # update2.rpf/common/shaders/db 26 = 415 registered in the whole-game manifest), so the
        # string is the file's OWN NAME rather than a transcription. That is both better
        # provenance and ~2x the coverage: emissive_alpha.sps and cloth_spec_cutout.sps are
        # shipped by the game and were emitting hash_XXXXXXXX.sps.
        # Additive by construction - a hash already known keeps its entry, so this can only turn
        # a hash_ into a name, never change a name we already spelled.
        try:
            p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "game_sps_names.json")
            if os.path.isfile(p):
                with open(p, "r", encoding="utf-8") as fh:
                    for n in json.load(fh).get("names") or ():
                        _SPS.setdefault(joaat(n), n)
        except Exception as ex:                    # counted, never silent
            _refuse("sps_game_table_unreadable:%s" % type(ex).__name__, str(ex)[:80])
        osn = _load_name_table("oracle_shader_names.json", required=False) or {}
        for fn in osn.get("filenames", []):
            _SPS.setdefault(joaat(fn), fn)
        for n in osn.get("names", []):
            _SPS.setdefault(joaat(n + ".sps"), n + ".sps")
    if hash32 == 0:
        # measured (farlods default shader): a zero sps hash spells <FileName />
        return ""
    got = _SPS.get(hash32)
    if got is None:
        _refuse("sps_filename_unresolved", "%s: 0x%08X" % (preset, hash32))
        return "hash_%08X.sps" % hash32
    return got


# ---------------------------------------------------------------- drawable walk

# Shader param NAMES are in the binary as joaat(lowercase(name)): a u32 array of npar hashes
# at param_table + data_size, one per 16-byte param entry, in entry order. Derived and
# validated 2026-07-28 (reports/sampler_derivation_2026-07-28.md):
#   * u32 @shader+0x10 packs u8 param count (lo) + u8 RenderBucket (next) - the old "&0xFFFF
#     reads 269/520/778" mystery was count|bucket<<8 (0x10D = 13 params, bucket 1)
#   * u16 @shader+0x14 = data_size = 16*npar + 16*sum(vec4 counts): held 43,872/43,872
#   * entry byte 0 is the class: 0 = texture, N>0 = vec4 count of a value param
#   * per-index pairing hash[i]<->entry[i] proven by joining params BY NAME against 866 third-party
#     full-parameter reference exports: vector values 99.933%, arrays 100.000%, bound
#     texture names 99.960% - residuals are game-build drift, not decode error.
# joaat is one-way, so names come from this table (corpus sampler names + joaat-cracked
# lane hashes); an unresolved hash emits as hash_%08X, which the importer skips harmlessly.
SAMPLER_NAMES = [
    "AnisoNoiseSpecSampler", "BumpSampler", "BumpSampler2", "BumpSampler_layer0",
    "BumpSampler_layer1", "BumpSampler_layer2", "BumpSampler_layer3",
    "ComboHeightSamplerFur01", "ComboHeightSamplerFur23", "ComboHeightSamplerFur45",
    "ComboHeightSamplerFur67", "DamageSampler", "DetailSampler", "DiffuseHfSampler",
    "DiffuseSampler", "DiffuseSampler2", "DirtBumpSampler", "DirtSampler",
    "EnvironmentSampler", "FlowSampler", "FoamSampler", "FogSampler",
    "FontNormalSampler", "FontSampler", "FurMaskSampler", "NoiseSampler",
    "PlateBgBumpSampler", "PlateBgSampler", "SfxWindSampler3D", "SnowSampler",
    "SnowSampler0", "SnowSampler1", "SpecSampler", "StarFieldSampler",
    "StippleSampler", "TextureSamp", "TextureSampler_layer0", "TextureSampler_layer1",
    "TextureSampler_layer2", "TextureSampler_layer3", "TintPaletteSampler",
    "VolumeSampler", "WrinkleMaskSampler_0", "WrinkleMaskSampler_1",
    "WrinkleMaskSampler_2", "WrinkleMaskSampler_3", "WrinkleMaskSampler_4",
    "WrinkleMaskSampler_5", "WrinkleSampler_A", "WrinkleSampler_B", "bumptex",
    "diffusetex", "dirttex", "ditherSampler", "distanceMapSampler",
    "heightMapSamplerLayer0", "heightMapSamplerLayer1", "heightMapSamplerLayer2",
    "heightMapSamplerLayer3", "heightSampler", "highDetailSampler", "lookupSampler",
    "moonSampler", "perlinSampler", "speculartex",
]

# ⭐ VALUE (non-texture) shader parameter names, 2026-07-29. Every one below was identified by
# hashing the candidate name and matching it against a hash read out of a REAL binary (dt1_00_5.ydr
# and friends) - not by reading anyone's source. Unmatched hashes are still EMITTED as
# hash_XXXXXXXX: the values are the operator's data and dropping them silently is how
# `detailSettings` went missing for months while DetailSampler was bound 6,264 times.
VALUE_PARAM_NAMES = [
    "bumpiness", "detailSettings", "specularFalloffMult", "specularIntensityMult",
    "specMapIntMask", "wetnessMultiplier", "useTessellation", "hardAlphaBlend",
    "globalAnimUV0", "globalAnimUV1", "alphaScale", "emissiveMultiplier",
    "parallaxScaleBias", "heightScale", "heightBias", "envEffThickness", "envEffScale",
    "reflectivePower", "normalMapScale", "TextureSharpness", "DirtDecalMask",
    "specDesaturateExponent", "specDesaturateIntensity", "FresnelCoeff",
    "matMaterialColorScale", "umGlobalParams", "materialWetnessMultiplier",
    "bumpSelfShadowAmount", "tintPaletteSelector", "detailScale",
    # Terrain/PXM parallax, identified 2026-07-29 the same way (hash-matched against real files).
    # ⭐ These are the settings for cause C's unmapped heightMapSamplerLayer0-3.
    "heightScale0", "heightScale1", "heightScale2", "heightScale3",
    "heightBias0", "heightBias1", "heightBias2", "heightBias3",
    "parallaxSelfShadowAmount",
    # Identified 2026-07-30 by the same hash-match-against-real-files method. specularFresnel alone
    # accounts for 9,094 of the previously-unnamed bindings.
    "specularFresnel", "shadowFalloff", "alphaTest", "SelfShadowing", "WindGlobalParams",
    "DirtColor", "dirtLevelMod", "matDiffuseColor", "matWheelWorld",
    "TyreDeformParams2", "tyreDeformParams",
]

_VALUE_PARAMS = None


def value_param_name(hash32):
    """Resolve a shader value-parameter hash to its name.

    ⭐ THE NAME TABLE IS DERIVED FROM THE GAME'S OWN COMPILED SHADERS (2026-07-30, Matt's lead:
    "I saw something that defined these values"). Every identifier in the 321 `.fxc` files under
    common.rpf is hashed once into `shader_param_names.json` - 5,058 of them - so a parameter is
    named because the shader that consumes it says so, not because someone guessed a spelling.
    That closed the last 7 unknowns instantly (envEffTexTileUV, specular2Color_DirLerp,
    matWheelWorldViewProj, UseTreeNormals, fillColor, furShadow03/47).
    VALUE_PARAM_NAMES remains as the hand-verified core and is consulted FIRST, so a name we
    measured ourselves always wins over a same-hash identifier picked out of a shader blob.
    """
    global _VALUE_PARAMS
    if _VALUE_PARAMS is None:
        _VALUE_PARAMS = {_joaat(n.lower()): n for n in VALUE_PARAM_NAMES}
        # ⛔ WAS `except Exception: pass` with the comment "the hand-verified core still works
        # without the generated table" - true, but the core is 50 names against 5,058, and
        # nothing said which one you were running. Absent = counted + warned (see
        # _load_name_table); corrupt = refuse.
        gen = _load_name_table("shader_param_names.json", required=False)
        for _h, _n in (gen or {}).items():
            _VALUE_PARAMS.setdefault(int(_h, 16), _n)
        # ORACLE CASING OVERLAY (2026-08-06): joaat is case-insensitive but the emitted
        # TEXT is not - the reference spells HardAlphaBlend/dirtColor where the
        # fxc-derived table had drifted case. The 113 param spellings observed across
        # the oracle set override any same-hash entry; the oracle IS the spec.
        cased = _load_name_table("oracle_param_casing.json", required=False)
        if isinstance(cased, list):
            for _n in cased:
                _VALUE_PARAMS[_joaat(_n.lower())] = _n
    nm = _VALUE_PARAMS.get(hash32)
    if nm:
        return nm
    _refuse("value_param_unresolved", "0x%08X" % hash32)
    return "hash_%08X" % hash32


_SAMPLERS = None


def _joaat(s):
    h = 0
    for c in s.encode("latin-1"):
        h = (h + c) & 0xFFFFFFFF
        h = (h + ((h << 10) & 0xFFFFFFFF)) & 0xFFFFFFFF
        h ^= h >> 6
    h = (h + ((h << 3) & 0xFFFFFFFF)) & 0xFFFFFFFF
    h ^= h >> 11
    return (h + ((h << 15) & 0xFFFFFFFF)) & 0xFFFFFFFF


def sampler_name(hash32):
    """⛔ THE ONLY ONE OF THE THREE HASH RESOLVERS THAT DID NOT COUNT ITS MISSES (2026-08-03).
    preset_name and value_param_name both _refuse on an unresolved hash; this one returned
    hash_%08X in silence, so an unnamed sampler - a texture bound to a slot RUDE cannot map to a
    material input - was invisible in exactly the lane where texture coverage is being measured.
    Same string out, so no emitted byte moves; what changes is that the number exists."""
    global _SAMPLERS
    if _SAMPLERS is None:
        _SAMPLERS = {_joaat(n.lower()): n for n in SAMPLER_NAMES}
        # WIRING FIX 2026-08-06 (agent-2 measurement): shader_param_names.json already
        # holds thousands of fxc-derived sampler names (DetailDensitySampler...) under
        # their joaat keys, and this resolver never consulted it - 6 of the sweep's
        # unresolved hashes were sitting in a table we ship. Hand-verified tuple wins
        # on any overlap; the generated table only fills gaps.
        gen = _load_name_table("shader_param_names.json", required=False) or {}
        for k, n in gen.items():
            try:
                _SAMPLERS.setdefault(int(k, 16), n)
            except (TypeError, ValueError):
                pass
        # oracle casing overlay - see value_param_name; same rule, same source
        cased = _load_name_table("oracle_param_casing.json", required=False)
        if isinstance(cased, list):
            for n in cased:
                _SAMPLERS[_joaat(n.lower())] = n
    nm = _SAMPLERS.get(hash32)
    if nm:
        return nm
    _refuse("sampler_name_unresolved", "0x%08X" % hash32)
    return "hash_%08X" % hash32


def embedded_textures(res, base=0, what=None):
    """The drawable's OWN texture dictionary -> ytd2xml texture dicts (name/format/pixels), or [].
    `what`: a name for refusal notes (quarry loads from bytes, so res.name is often unset).

    ⛔ WHY THIS EXISTS (2026-07-29). A gtaDrawable can carry its textures INTERNALLY, at
    ShaderGroup+0x08, instead of referencing a standalone .ytd. Nothing here read it, so those
    textures did not exist as far as RUDE was concerned. Measured over 3,479 real binaries:
    **1,180 (33.9%) carry a non-empty embedded dictionary** holding 4,845 textures, and **18.2% of
    all texture requests are satisfiable ONLY from there**. The visible symptoms were
    TintPaletteSampler at 100% unresolved (1,736 references, 0 present - palettes are almost always
    embedded) and drawables that render completely untextured because they carry every texture they
    use. PROOF: ce_xr_ctr2.ydr's embedded dictionary holds 28 textures and satisfies 28 of 28 of
    that drawable's own requests, including ce_xr_ctr2_lod_pal.

    The dictionary is the same pgDictionary<grcTexture> a .ytd's root is, so ytd2xml.read_textures
    reads it verbatim once told where it lives - no second implementation to drift.
    """
    sg = res.ptr(base + 0x10)
    if sg == 0:
        return []                      # legitimate: fragment child drawables carry no ShaderGroup
    buf, o = res.deref(sg, 0x40)
    if buf is None:
        # read_shaders RAISES on this same pointer, but quarry calls embedded_textures directly
        # before to_xml, so it would be reached first and must not vanish here either.
        _refuse("embedded_dict_shadergroup_unresolved", "0x%08x" % sg)
        return []
    tp = res.u32(o + 0x08)
    if not tp:
        return []                      # ordinary: 2,299 of 3,479 base ydr carry no dictionary
    tbuf, to = res.deref(tp, 0x40)
    if tbuf is None:
        # non-NULL pointer that does not resolve: the drawable SAYS it carries textures and we
        # cannot reach them. Distinct from tp == 0 above, which is the ordinary "no embedded
        # dictionary" shape (2,299 of 3,479 base ydr). Measured 0 on real data.
        _refuse("embedded_dict_ptr_unresolved", "0x%08x" % tp)
        return []
    try:
        import ytd2xml
        return ytd2xml.read_textures(res, base=to)
    except Exception as e:
        # A malformed embedded dictionary must not lose the whole drawable - the geometry and
        # shader data are still good, so this stays a downgrade rather than a refusal.
        # ⛔ IT USED TO BE A SILENT ONE (fixed 2026-08-03). `except Exception: return []` emitted
        # a fully "successful" .ydr.xml with no <TextureDictionary>, no message, no counter,
        # exit 0 - while the shader Parameters still NAMED every one of those textures. Proven
        # by monkeypatching ytd2xml.read_textures to raise on ce_xr_ctr2.ydr: embedded count
        # 28 -> 0, <TextureDictionary> present -> absent, 2,512,630 B -> 2,503,351 B, nothing on
        # stdout or stderr. The cost is not the file, it is the MEASUREMENT: an untextured
        # drawable becomes indistinguishable from one whose .ytd is genuinely missing, so
        # "our decoder refused" lands in the corpus's missingTextures residual instead.
        # Rate on real data is 0 (1,180/1,180 dictionaries decode across 3,479 base ydr,
        # 794/794 across 3,000 base yft) - but OPEN_ITEMS #29 records this exact failure live
        # (describe_format raising on an unmapped pixel enum loses the whole dictionary), and
        # this except is what hid it. The exception TYPE is in the key so a systemic breakage
        # (an ImportError on every file) cannot read as scattered bad data.
        _refuse("embedded_dict_refused:" + type(e).__name__,
                "%s: %s" % (what or res.name or "drawable at +0x%x" % base, e))
        print("WARN embedded texture dictionary refused (%s: %s) - the drawable's own textures "
              "are NOT in this XML" % (type(e).__name__, e), file=sys.stderr)
        return []


def read_shaders(res, base=0):
    """base = system offset of the gtaDrawable (0 for a standalone ydr; a dictionary entry's
    offset for ydd/yft reuse). Only the FIXED header offsets rebase - tagged pointers are
    segment-absolute and need nothing.
    -> [(preset, render_bucket, [(sampler, texture_name), ...], [(param, [(x,y,z,w), ...]), ...])]

    ⛔ THE FOURTH ELEMENT EXISTS BECAUSE IT WAS MISSING (2026-07-29). This function used to read the
    16-byte param entry's CLASS BYTE, `continue` on anything non-zero, and emit textures only - so
    EVERY scalar/vector shader parameter in the game was dropped: detail tiling, specular intensity
    and falloff, bump scale, wetness, tint selectors, terrain blend weights. The visible cost was
    that `DetailSampler` bound 6,264 times with no `detailSettings` to tile it by, which makes a
    faithful detail map impossible and is not fixable downstream.
    MEASURED LAYOUT: class byte 0 = texture; N>0 = a count of float4s, and the entry's +0x08 field
    is a TAGGED POINTER to N*16 bytes of float data (verified by dereferencing it, not by assuming
    it sits at the data-region offset - the two happen to coincide and only one is the contract).

    ⛔ AN UNREADABLE SHADER GROUP IS NOT A DRAWABLE WITH NO SHADERS (2026-08-03). Both early exits
    below used to `return out` empty, and drawable_lines then substituted ONE ("default",0,[],[])
    while the geometries kept ShaderIndex values up to N-1 - the consumer clamps
    (RudeToolset.cpp:1843), so every geometry silently rendered on the default material. The two
    causes are now split by MEASUREMENT: a NULL pointer at +0x10 is the ordinary shape of a
    fragment CHILD drawable (19,493 of 19,493 children over 3,000 base yft read exactly 0 there -
    children index the FRAGMENT's group, which yft2xml splices in), while a non-NULL pointer that
    does not resolve was seen 0 times in 3,479 base ydr + 3,000 base yft and is a decode failure."""
    out = []
    sg = res.ptr(base + 0x10)
    if sg == 0:
        return out                     # legitimate: fragment child drawables carry no ShaderGroup
    buf, o = res.deref(sg, 0x40)
    if buf is None:
        raise ValueError("ShaderGroup pointer 0x%08x does not resolve" % sg)
    arr_p, nsh = res.u32(o + 0x10), res.u16(o + 0x18)
    if nsh == 0:
        _refuse("shader_group_declares_zero_shaders")
        return out
    abuf, ao = res.deref(arr_p, nsh * 8)
    if abuf is None:
        raise ValueError("shader array of %d entries at 0x%08x does not resolve" % (nsh, arr_p))
    for si in range(nsh):
        bp = res.u32(ao + si * 8)
        bbuf, bo = res.deref(bp, 0x30)
        if bbuf is None:
            # Keep the slot so every later ShaderIndex still points at the right material, but
            # say so: this entry's preset, bucket, textures and value params are all gone.
            _refuse("shader_block_unresolved_default_substituted", "shader %d ptr 0x%08x"
                    % (si, bp))
            out.append(("default", 0, [], []))
            continue
        preset = preset_name(res.u32(bo + 0x08))
        spsfn = sps_filename(res.u32(bo + 0x18), preset)
        w10 = res.u32(bo + 0x10)
        npar, bucket = w10 & 0xFF, (w10 >> 8) & 0xFF
        dsize = res.u16(bo + 0x14)
        tbl_p = res.u32(bo + 0x00)
        # ordered param list, BINARY ENTRY ORDER - the oracle interleaves texture and
        # vector items exactly as the parameter table stores them (wheel2: dirtColor
        # vector sits between samplers); split texs/vals lists destroyed that order
        params = []
        # max npar measured in the lane is 32; clamp keeps a corrupt count from walking off.
        # A texture is any class-0 entry whose stub derefs, whose type word's low u16 is 1,
        # and whose +0x28 name is printable - unbound slots (NULL ptr) simply do not emit.
        # ⛔ THE TYPE-WORD COMMENT WAS A CLAIM NOBODY COULD REPRODUCE (corrected 2026-08-03). It
        # read "0x0002=external ref, 0x0080=embedded, measured". Re-measured here: 48,339 of
        # 48,339 stubs across 3,479 base ydr + a 600-file ydd sample read exactly 0x0001, so
        # neither of those two values occurs anywhere reachable. They may still exist in a bucket
        # nobody has sampled - and every such binding used to vanish with a bare `continue`, which
        # would have charged the loss to the texture corpus rather than to this reader. UNMEASURED
        # values are now COUNTED BY VALUE, so the first file that carries one says so by name.
        if 0 < npar <= 96 and dsize >= npar * 16:
            tbuf, to = res.deref(tbl_p, dsize + npar * 4)
            if tbuf is None:
                _refuse("shader_param_table_unresolved",
                        "%s: %d params, %d B" % (preset, npar, dsize))
            else:
                hashes = struct.unpack_from("<%dI" % npar, tbuf, to + dsize)
                for pi in range(npar):
                    cls = tbuf[to + pi * 16]
                    if cls != 0:
                        # A VALUE param: cls = how many float4s, +0x08 = tagged pointer to them.
                        # Clamped: a corrupt count must not turn into a huge read.
                        if cls > 64:
                            _refuse("value_param_count_implausible", "%s: cls=%d" % (preset, cls))
                            continue
                        vp = struct.unpack_from("<I", tbuf, to + pi * 16 + 8)[0]
                        vbuf, vo = res.deref(vp, cls * 16) if vp else (None, 0)
                        if vbuf is None:
                            _refuse("value_param_data_unresolved" if vp else
                                    "value_param_data_NULL",
                                    "%s: %s" % (preset, value_param_name(hashes[pi])))
                            continue
                        params.append(("vec", value_param_name(hashes[pi]),
                                       [struct.unpack_from("<4f", vbuf, vo + k * 16)
                                        for k in range(cls)]))
                        continue
                    sp = struct.unpack_from("<I", tbuf, to + pi * 16 + 8)[0]
                    if sp == 0:
                        # unbound sampler slot: the oracle spells it as a SELF-CLOSING
                        # texture Item (task_000_u TextureSamplerDiffPal) - skipping it
                        # was a real omission, and order is the binary entry order
                        params.append(("tex", sampler_name(hashes[pi]), None))
                        continue
                    sbuf, so = res.deref(sp, 0x34)
                    if sbuf is None:
                        _refuse("texture_stub_unresolved", "%s: 0x%08x" % (preset, sp))
                        continue
                    tw = struct.unpack_from("<H", sbuf, so + 0x30)[0]
                    if tw != 1:
                        _refuse("texture_stub_typeword_0x%04x" % tw, preset)
                        continue
                    nm = res.cstr(struct.unpack_from("<I", sbuf, so + 0x28)[0])
                    if not (nm and all(31 < ord(ch) < 127 for ch in nm)):
                        _refuse("texture_name_unusable", "%s: %r" % (preset, nm[:24]))
                        continue
                    params.append(("tex", sampler_name(hashes[pi]), nm))
        elif npar:
            _refuse("shader_param_header_implausible",
                    "%s: npar=%d dsize=%d" % (preset, npar, dsize))
        out.append((preset, spsfn, bucket, params))
    return out


class GeometryList(list):
    """A plain list of geometry dicts that also remembers how many the BINARY DECLARED.

    ⛔ WHY A SUBCLASS AND NOT A (list, int) PAIR: read_geometries has three callers
    (drawable_lines here, yft2xml.read_physics's truthiness test, and any future one), and a
    changed return shape is exactly the kind of edit that gets applied to two of the three.
    Every existing caller keeps working - it is a list - while drawable_lines can ask
    `geos.declared` and refuse a shortfall."""
    declared = 0


_LAYOUT_TABLE_NAMES = {
    # <Layout type="GTAVn"> keyed on the WHOLE 64-bit grcFvf nibble TABLE - measured 2026-08-08:
    # two declarations with IDENTICAL used-channel masks (0x59) carry different labels, so the
    # channel heuristic cannot be the discriminator; the raw table value is.
    0x7755555555996996: "GTAV1",   # full-float table - all 264 ydr/ydd oracle layouts
    0x030000000199A006: "GTAV2",   # compressed cloth, byte4 Normal (plg_01/vb_34 witnesses)
    0x0300000001996006: "GTAV3",   # compressed cloth, float3 Normal (id2_21_c_clothdca witness
                                   #  - graded GTAV1 by the old heuristic while byte-equal in
                                   #  every DATA byte: label-only diff, the wave-2 cloth class)
}


def _layout_type(nibbles, fields):
    """the reference exporter's <Layout type="GTAVn"> classifies the vertex declaration BY ITS
    RAW 64-bit nibble table (witnessed identities above). An unwitnessed table falls back to
    the old channel heuristic AND IS COUNTED - a mislabel must surface in the run summary and
    the spot-diff, never silently."""
    name = _LAYOUT_TABLE_NAMES.get(nibbles)
    if name:
        return name
    _refuse("layout_table_unwitnessed_fell_back_to_channel_heuristic", "0x%016X" % nibbles)
    for bit, _name, _tokens, _off, _size, nb in fields:
        if bit == 3 and nb == 0xA:
            return "GTAV2"
    return "GTAV1"


def read_geometries(res, base=0, group_off=0x50):
    """One DrawableModels LOD group -> its geometries. group_off selects the LOD:
    +0x50 High, +0x58 Medium, +0x60 Low, +0x68 VeryLow (derived 2026-08-06, WAL §skel).
    +0xA0 is a byte-identical ALIAS of +0x50 and must NOT be walked (it would double
    every mesh). Default High keeps every existing caller (yft truthiness) unchanged.
    base: see read_shaders.

    -> GeometryList; `.declared` is the count the file's own model records claim. Every drop below
    is COUNTED and the shortfall is what drawable_lines refuses on: a partially decoded mesh used
    to be indistinguishable from a genuinely smaller one at every level above (corpus counter,
    import verdict, geometry count, visual check). Measured shortfall today is ZERO - 13,693 of
    13,693 over 3,479 base ydr, 12,032/12,032 main + 568/568 child over 3,000 base yft - so this
    is the SHAPE being closed, not a live loss."""
    geos = GeometryList()
    geos.models = []
    mh_p = res.ptr(base + group_off)
    if mh_p == 0:
        # No group at this LOD. Ordinary for a fragment child that carries only
        # collision (19,102 of 19,493 child drawables over 3,000 base yft) - and for a MAIN
        # drawable's High group it is caught by drawable_lines, which refuses empty geometry.
        return geos
    buf, mh = res.deref(mh_p, 0x10)
    if buf is None:
        _refuse("model_group_unresolved", "0x%08x" % mh_p)
        return geos
    marr_p, nmod = res.u32(mh + 0x00), res.u16(mh + 0x08)
    mbuf, ma = res.deref(marr_p, nmod * 8)
    if mbuf is None:
        _refuse("model_array_unresolved", "%d models at 0x%08x" % (nmod, marr_p))
        return geos
    for mi in range(nmod):
        mp = res.u32(ma + mi * 8)
        _b, m = res.deref(mp, 0x30)
        if _b is None:
            _refuse("model_unresolved", "model %d ptr 0x%08x" % (mi, mp))
            continue
        garr_p, ngeo = res.u32(m + 0x08), res.u16(m + 0x10)
        geos.declared += ngeo
        gb_p = res.u32(m + 0x18)
        # model header bytes: Unknown1 u8@+0x28, BoneIndex u8@+0x2B, RenderMask u8@+0x2C,
        # Flags u8@+0x2D. ⛔ BoneIndex was +0x2F (always 0) until the animlight pair caught
        # it: model[1] carries 0x01 at +0x2B where +0x2F stays 0 (2026-08-06).
        geos.models.append({"mask": _b[m + 0x2C], "flags": _b[m + 0x2D],
                            "unknown1": _b[m + 0x28], "boneindex": _b[m + 0x2B]})
        # per-geometry bounds: float4 (min,max) pairs @ model+0x18; [union]+per-geo
        # when ngeo>1 (probed: 0089 entry0 == union of entries 1..n)
        gb_list = None
        n_ent = ngeo + 1 if ngeo > 1 else ngeo
        gbb, gbo = res.deref(gb_p, n_ent * 32)
        if gbb is not None:
            gb_list = [struct.unpack_from("<8f", gbb, gbo + k * 32)
                       for k in range(n_ent)]
            if ngeo > 1:
                gb_list = gb_list[1:]
        else:
            _refuse("geometry_bounds_unresolved", "model %d" % mi)
        gbuf, ga = res.deref(garr_p, ngeo * 8)
        if gbuf is None:
            _refuse("geometry_array_unresolved", "model %d: %d geometries" % (mi, ngeo))
            continue
        for gi in range(ngeo):
            gp = res.u32(ga + gi * 8)
            _b2, g = res.deref(gp, 0x80)
            if _b2 is None:
                _refuse("geometry_unresolved", "model %d geometry %d" % (mi, gi))
                continue
            vb_p, ib_p = res.u32(g + 0x18), res.u32(g + 0x38)
            idx_count = res.u32(g + 0x58)
            vcnt = res.u16(g + 0x60)
            stride = res.u16(g + 0x70)      # U16 - a u32 read yields 983,100 on skinned meshes
            _b3, vb = res.deref(vb_p, 0x40)
            if _b3 is None:
                _refuse("vertex_buffer_unresolved", "model %d geometry %d" % (mi, gi))
                continue
            # VertexBuffer <Flags> = u16 @ grcVertexBuffer+0x0A. It was hardcoded "0" - true for
            # almost everything, which is why it survived: MEASURED 1,014/1,014 geometries over
            # 249 base-game ydr read 0, while 76/76 head-morph ydr in the mppatches pack read
            # 1024, and the oracle set splits exactly the same way (225 zeros, 2 x 1024, both
            # micro_*). A constant that is right 93% of the time is the hardest kind of wrong.
            vb_flags = res.u16(vb + 0x0A)
            vdata_p, fvf_p = res.u32(vb + 0x10), res.u32(vb + 0x30)
            _b4, fvf = res.deref(fvf_p, 0x10)
            if _b4 is None:
                _refuse("vertex_declaration_unresolved", "model %d geometry %d" % (mi, gi))
                continue
            mask = res.u32(fvf + 0x00)
            nibbles = struct.unpack_from("<Q", res.sys, fvf + 0x08)[0]
            fields, _ = build_decl(mask, nibbles, stride)
            vlines = decode_vertices(res, vdata_p, vcnt, stride, fields)
            _b5, ib = res.deref(ib_p, 0x20)
            if _b5 is None:
                _refuse("index_buffer_unresolved", "model %d geometry %d" % (mi, gi))
                continue
            idata_p = res.u32(ib + 0x10)
            ibuf, io = res.deref(idata_p, idx_count * 2)
            if ibuf is None:
                _refuse("index_data_unresolved",
                        "model %d geometry %d: %d indices" % (mi, gi, idx_count))
                continue
            indices = list(struct.unpack_from("<%dH" % idx_count, ibuf, io))
            # BoneIDs: geometry+0x68 ptr -> u16[count], count u16 @ +0x72 (derived
            # 2026-08-06). Absent (element entirely omitted) when the ptr is NULL - no
            # self-closing form is ever emitted (wheel2's 4 NULL geometries witness it).
            boneids = None
            bid_p, bid_n = res.u32(g + 0x68), res.u16(g + 0x72)
            if bid_p and bid_n:
                bbuf, bo = res.deref(bid_p, bid_n * 2)
                if bbuf is not None:
                    boneids = list(struct.unpack_from("<%dH" % bid_n, bbuf, bo))
                else:
                    _refuse("boneids_unresolved", "model %d geometry %d" % (mi, gi))
            # shaderMap: u16 per geometry -> shader index (often non-identity in real files)
            # ⛔ THE FALLBACK IS A GUESS THAT LOOKS LIKE DATA (counted 2026-08-03). When the map
            # does not resolve, `shader_idx = gi` assumes geometry i uses shader i - and the
            # measurement says that assumption is wrong for a large minority: 355 of 2,142 ydr
            # geometries (16.6%) and 1,147 of 2,823 yft geometries (40.6%) have a NON-identity
            # map (drawlane/silentsites.py, 500 ydr + 800 yft). So if this ever fired, roughly
            # one geometry in four would render on someone else's material, with every count and
            # every gate still green - the exact silent-wrong shape this triage keeps finding.
            # It has never fired: pointer NULL 0, unresolvable 0, across those same 4,965
            # geometries. Counted rather than refused because a shaderMap-less model may be a
            # legal shape nobody has met yet, and a refusal would then throw away a whole mesh
            # over an index we may still be able to bound.
            shader_idx = gi
            smap_p = res.u32(m + 0x20)
            sbuf, so = res.deref(smap_p, ngeo * 2)
            if sbuf is not None:
                shader_idx = struct.unpack_from("<H", sbuf, so + gi * 2)[0]
            else:
                _refuse("shadermap_absent_shader_index_assumed_identity"
                        if smap_p == 0 else "shadermap_unresolved_shader_index_assumed_identity",
                        "model %d geometry %d" % (mi, gi))
            geos.append({
                "shader": shader_idx,
                "layout": [f[1] for f in fields],
                "ltype": _layout_type(nibbles, fields),
                "verts": vlines,
                "indices": indices,
                "model": mi,
                "bbox": gb_list[gi] if gb_list and gi < len(gb_list) else None,
                "boneids": boneids,
                "vbflags": vb_flags,
            })
    return geos


def read_bounds(res, base=0):
    """Drawable-level bounds/sphere - ExportYtyp FAILS ENTIRELY without these three."""
    f = lambda o: struct.unpack_from("<f", res.sys, base + o)[0]
    return {
        "sphere_c": (f(0x20), f(0x24), f(0x28)),
        "sphere_r": f(0x2C),
        "bb_min": (f(0x30), f(0x34), f(0x38)),
        "bb_max": (f(0x40), f(0x44), f(0x48)),
    }


BONE_FLAG_BITS = (
    # bits 3/7 (LimitRotation/LimitTranslation) added 2026-08-08: the table was derived from
    # map-prop bones, which never carry limits, so the 47/47 ydr grade could not see the gap -
    # cablecar's door bones (0xF7) spell "... TransZ, LimitTranslation, Unk0" in the reference.
    # Same vocabulary yft2xml.BONE_FLAG_BITS already carries; bones with limits are also the
    # ones the <Joints> section describes (cablecar BoneId 60963 = the LimitTranslation door).
    (0, "RotX"), (1, "RotY"), (2, "RotZ"), (3, "LimitRotation"),
    (4, "TransX"), (5, "TransY"), (6, "TransZ"), (7, "LimitTranslation"),
    (8, "ScaleX"), (9, "ScaleY"), (10, "ScaleZ"), (12, "Unk0"),
)


def _bone_flags(v):
    syms = [s for bit, s in BONE_FLAG_BITS if v & (1 << bit)]
    return ", ".join(syms)


def skeleton_lines(res, base=0):
    """<Skeleton> - crSkeletonData @ drawable+0x18 (NULL = no skeleton element at all).
    Layout + bone struct + Flags vocabulary derived 2026-08-06: 60/60 header + 155/155
    bone-int + 434/434 float checks. TransformUnk comes from the +0x30 per-bone matrix
    array's w column (indices 3,7,11,15), not from the bone struct."""
    sk_p = res.ptr(base + 0x18)
    if not sk_p:
        return []
    buf, o = res.deref(sk_p, 0x68)
    if buf is None:
        _refuse("skeleton_unresolved", "0x%08x" % sk_p)
        return []
    u32 = lambda at: struct.unpack_from("<I", buf, o + at)[0]
    nb = struct.unpack_from("<H", buf, o + 0x5E)[0]
    bone_p = u32(0x20)
    tu_p = u32(0x30)
    bb, bo = res.deref(bone_p, nb * 0x50)
    if bb is None:
        _refuse("skeleton_bones_unresolved", "%d bones" % nb)
        return []
    tub, tuo = res.deref(tu_p, nb * 0x40) if tu_p else (None, 0)
    ff = fmt_num
    L = [" <Skeleton>",
         '  <Unknown1C value="%d" />' % u32(0x1C),
         '  <Unknown50 value="%d" />' % u32(0x50),
         '  <Unknown54 value="%d" />' % u32(0x54),
         '  <Unknown58 value="%d" />' % u32(0x58),
         "  <Bones>"]
    for i in range(nb):
        b = bo + i * 0x50
        rot = struct.unpack_from("<4f", bb, b + 0x00)
        trans = struct.unpack_from("<3f", bb, b + 0x10)
        scale = struct.unpack_from("<3f", bb, b + 0x20)
        sib, par = struct.unpack_from("<hh", bb, b + 0x30)
        flags = struct.unpack_from("<H", bb, b + 0x40)[0]
        tag = struct.unpack_from("<H", bb, b + 0x44)[0]
        idx = struct.unpack_from("<H", bb, b + 0x46)[0]
        nm = res.cstr(struct.unpack_from("<I", bb, b + 0x38)[0])
        if tub is not None:
            mtx = struct.unpack_from("<16f", tub, tuo + i * 0x40)
            tu = (mtx[3], mtx[7], mtx[11], mtx[15])
        else:
            tu = (0.0, 0.0, 0.0, 0.0)
        L += ["   <Item>",
              "    <Name>%s</Name>" % esc(nm or ""),
              '    <Tag value="%d" />' % tag,
              '    <Index value="%d" />' % idx,
              '    <ParentIndex value="%d" />' % par,
              '    <SiblingIndex value="%d" />' % sib,
              "    <Flags>%s</Flags>" % _bone_flags(flags),
              '    <Translation x="%s" y="%s" z="%s" />' % tuple(ff(x) for x in trans),
              '    <Rotation x="%s" y="%s" z="%s" w="%s" />' % tuple(ff(x) for x in rot),
              '    <Scale x="%s" y="%s" z="%s" />' % tuple(ff(x) for x in scale),
              '    <TransformUnk x="%s" y="%s" z="%s" w="%s" />' % tuple(ff(x) for x in tu),
              "   </Item>"]
    L += ["  </Bones>", " </Skeleton>"]
    return L


DRAWABLE_MODEL_GROUPS = (
    (0x50, "DrawableModelsHigh"), (0x58, "DrawableModelsMedium"),
    (0x60, "DrawableModelsLow"), (0x68, "DrawableModelsVeryLow"),
)


def _model_group_lines(ff, tag, geos):
    """One <DrawableModels*> group. Model grouping preserved; per-model quintet;
    per-geometry bbox + BoneIDs. ⚠ VeryLow's tag spelling has ZERO oracle witnesses -
    no drawable in the set carries a +0x68 group - so if one ever appears this name is
    a guess and the sweep will flag it."""
    L = [" <%s>" % tag]
    models = getattr(geos, "models", None) or [{}]
    for mi, mm in enumerate(models):
        mg = [g for g in geos if g.get("model", 0) == mi]
        if not mg:
            continue
        has_skin = any("BlendWeights" in g["layout"] for g in mg)
        L += ["  <Item>",
              '   <RenderMask value="%d" />' % mm.get("mask", 255),
              '   <Flags value="%d" />' % mm.get("flags", 0),
              '   <HasSkin value="%d" />' % int(has_skin),
              '   <BoneIndex value="%d" />' % mm.get("boneindex", 0),
              '   <Unknown1 value="%d" />' % mm.get("unknown1", 0),
              "   <Geometries>"]
        for g in mg:
            L.append("    <Item>")
            L.append('     <ShaderIndex value="%d" />' % g["shader"])
            bb = g.get("bbox")
            if bb is not None:
                L.append('     <BoundingBoxMin x="%s" y="%s" z="%s" w="%s" />'
                         % tuple(ff(v) for v in bb[:4]))
                L.append('     <BoundingBoxMax x="%s" y="%s" z="%s" w="%s" />'
                         % tuple(ff(v) for v in bb[4:]))
            if g.get("boneids"):
                L.append("     <BoneIDs>%s</BoneIDs>"
                         % ", ".join(str(x) for x in g["boneids"]))
            L += ["     <VertexBuffer>",
                  '      <Flags value="%d" />' % g.get("vbflags", 0),
                  '      <Layout type="%s">' % g.get("ltype", "GTAV1")]
            for nm in g["layout"]:
                L.append("       <%s />" % nm)
            L += ["      </Layout>", "      <Data>"]
            L.extend("       " + v for v in g["verts"])
            L += ["      </Data>", "     </VertexBuffer>", "     <IndexBuffer>"]
            idx = g["indices"]
            if len(idx) <= 24:
                L.append("      <Data>%s</Data>" % " ".join(str(x) for x in idx))
            else:
                L.append("      <Data>")
                for i in range(0, len(idx), 24):
                    L.append("       " + " ".join(str(x) for x in idx[i:i + 24]))
                L.append("      </Data>")
            L += ["     </IndexBuffer>", "    </Item>"]
        L += ["   </Geometries>", "  </Item>"]
    L.append(" </%s>" % tag)
    return L


LIGHT_TYPES = {1: "Point", 2: "Spot"}   # observed codes only - others refuse, never guess


def lights_lines(res, base=0):
    """<Lights> - LightAttrs array @ drawable+0xB0 (tagged ptr) / +0xB8 (u16 count),
    stride 0xA8. Layout + 36-element XML order derived 2026-08-06 from the 4
    light-bearing oracle pairs: 315/315 field checks (WAL §6i). Two sample-ambiguities
    are documented there (volume five-pack bijection; Falloff vs CullingPlaneOffset,
    equal in every sample) - the assignment below reproduces every observed byte, and a
    future divergent sample surfaces as a visible diff, never silent corruption."""
    n = res.u16(base + 0xB8)
    lp = res.u32(base + 0xB0)
    if not n or not lp:
        return [" <Lights />"]
    buf, off = res.deref(lp, n * 0xA8)
    if buf is None:
        _refuse("lights_array_unresolved", "%d lights" % n)
        return [" <Lights />"]
    return light_items_lines(buf, off, n)


def light_items_lines(buf, off, n):
    """The <Lights> element for n LightAttrs records @ buf/off (stride 0xA8) — shared by the
    drawable slot pair (+0xB0/+0xB8) and the FRAGMENT slot pair (fragroot +0x110/+0x118,
    witnessed 2026-08-08 by the m26 interior screens)."""
    ff = fmt_num
    L = [" <Lights>"]
    for i in range(n):
        o = off + i * 0xA8
        f = lambda at: struct.unpack_from("<f", buf, o + at)[0]
        u32 = lambda at: struct.unpack_from("<I", buf, o + at)[0]
        v3 = lambda at: struct.unpack_from("<3f", buf, o + at)
        tcode = buf[o + 38]
        tname = LIGHT_TYPES.get(tcode)
        if tname is None:
            _refuse("light_type_unmeasured", str(tcode))
            tname = str(tcode)
        L += ["  <Item>",
              '   <Position x="%s" y="%s" z="%s" />' % tuple(ff(x) for x in v3(8)),
              '   <Colour r="%d" g="%d" b="%d" />' % (buf[o + 24], buf[o + 25], buf[o + 26]),
              '   <Flashiness value="0" />',
              '   <Intensity value="%s" />' % ff(f(28)),
              '   <Flags value="%d" />' % u32(32),
              '   <BoneId value="%d" />' % struct.unpack_from("<H", buf, o + 36)[0],
              "   <Type>%s</Type>" % tname,
              '   <GroupId value="%d" />' % buf[o + 39],
              '   <TimeFlags value="%d" />' % u32(40),
              '   <Falloff value="%s" />' % ff(f(44)),
              '   <FalloffExponent value="%s" />' % ff(f(48)),
              '   <CullingPlaneNormal x="%s" y="%s" z="%s" />' % tuple(ff(x) for x in v3(52)),
              '   <CullingPlaneOffset value="%s" />' % ff(f(64)),
              '   <Unknown45 value="0" />',
              '   <Unknown46 value="0" />',
              '   <VolumeIntensity value="%s" />' % ff(f(76)),
              '   <VolumeSizeScale value="%s" />' % ff(f(80)),
              '   <VolumeOuterColour r="%d" g="%d" b="%d" />'
              % (buf[o + 84], buf[o + 85], buf[o + 86]),
              '   <LightHash value="%d" />' % buf[o + 87],
              '   <VolumeOuterIntensity value="%s" />' % ff(f(88)),
              '   <CoronaSize value="%s" />' % ff(f(92)),
              '   <VolumeOuterExponent value="%s" />' % ff(f(96)),
              '   <LightFadeDistance value="%d" />' % buf[o + 100],
              '   <ShadowBlur value="%d" />' % buf[o + 68],
              '   <ShadowFadeDistance value="%d" />' % buf[o + 101],
              '   <SpecularFadeDistance value="%d" />' % buf[o + 102],
              '   <VolumetricFadeDistance value="%d" />' % buf[o + 103],
              '   <ShadowNearClip value="%s" />' % ff(f(104)),
              '   <CoronaIntensity value="%s" />' % ff(f(108)),
              '   <CoronaZBias value="%s" />' % ff(f(112)),
              '   <Direction x="%s" y="%s" z="%s" />' % tuple(ff(x) for x in v3(116)),
              '   <Tangent x="%s" y="%s" z="%s" />' % tuple(ff(x) for x in v3(128)),
              '   <ConeInnerAngle value="%s" />' % ff(f(140)),
              '   <ConeOuterAngle value="%s" />' % ff(f(144)),
              '   <Extent x="%s" y="%s" z="%s" />' % tuple(ff(x) for x in v3(148)),
              '   <ProjectedTextureHash />',
              "  </Item>"]
    L.append(" </Lights>")
    return L


# ---------------------------------------------------------------- embedded collision

# phBound TYPE codes, all MEASURED (LOG "ydr EMBEDDED phBOUND - DECODED" + the 2026-07-28
# bounds derivation: codes 1/12 named via 571/214 unambiguous yft binary<->reference joins).
# ⭐ 15 = Cloth, MEASURED 2026-08-03 - and the reason it was missing is the recurring lesson.
# The table's own note said codes 2/5/6/7/9/11/>13 "have never been measured", which is a
# statement about the ydr/ybn SAMPLE, not about the format: the reference oracle prints
# type="Cloth" on fragment cloth bounds (19 files in a 3,000-file yft oracle sample), a type this
# table had no code for at all. Unreachable today - a cloth bound hangs off the fragment's
# <Cloth><Controller><VerletCloth1>, not off drawable+0xC8 - so nothing refused and nothing
# noticed. Wiring fragment collision would have refused every cloth-bearing yft wholesale, and the
# refusal would have read as a corrupt file, which is exactly what the missing bit-31 name cost
# (15% of ybn on x64p) one level up.
# HOW THE CODE WAS OBTAINED, since the oracle prints the NAME and never the number: the oracle
# also prints that bound's header, so its BoxCenter triple is an anchor into the inflated system
# segment. Searching for it found EXACTLY ONE header per file whose other 10 printed fields also
# agree, and the byte at +0x10 there reads 15 in 19/19 files. Two independent cross-checks, both
# 6/6: the PARENT bound found by back-tracking the pointer that points at the cloth bound reads 10
# (which is what the oracle calls it, so +0x10 really is the type lane in this context), and the
# +0x00 vtable slot separates the classes (Composite 0x4062b5d8, Cloth 0x4062fe48). Emitting is
# also verified rather than assumed: _bound_lines run on those 19 bounds agrees with the oracle on
# 494/494 header field values with 0 mismatches and 0 _BOUND_HEADER_ZERO_BYTES violations, and
# emits no element the oracle does not have. Scripts: scratchpad drawlane/cloth_code.py,
# cloth_parent.py, cloth_verify.py.
# With Cloth in, the 3,000-file yft oracle sample names NO bound type this table lacks (Geometry
# 3,170 / Composite 2,962 / None 2,740 / Box 1,760 / Disc 633 / Capsule 246 / Cylinder 101 /
# Cloth 19 / Sphere 18 / GeometryBVH 10), and neither does the ybn oracle (all 13,482 exports:
# Composite + GeometryBVH only). That is a LOWER BOUND on the format, not a closure.
# Codes 2/5/6/7/9/11/14 have never been measured -> BoundsError, never a guess. ⛔ Read that as
# "no instrument here has seen one", NOT as "the format has none" - Cloth is what that distinction
# costs when it is forgotten.
BOUND_TYPE_NAMES = {0: "Sphere", 1: "Capsule", 3: "Box", 4: "Geometry", 8: "GeometryBVH",
                    10: "Composite", 12: "Disc", 13: "Cylinder", 15: "Cloth"}
_BOUND_GEOMETRY_TYPES = (4, 8)

# CompositeFlags1/2 share ONE enum; 26 bits named from measured (value, name-list) pairs with
# zero conflicts, and popcount==len(names) proves the names render in ASCENDING BIT ORDER.
# ⭐ BIT 31 = MAP_DEEP_SURFACE, added 2026-07-31 — and the way it surfaced is the lesson.
# The first 1,080 measured files came from archives where bit 31 never occurs, so this table
# called it "never observed set" and the emitter (correctly) REFUSED rather than drop a filter
# bit. That turned one missing name into a 15% conversion failure on x64p (131 of 870 ybn, all
# carrying the identical 0x80000002), and ~879 ybn game-wide by oracle count. The name is not a
# guess: 0x80000002 = bit1 + bit31, and the reference export of the same asset prints exactly
# "MAP_WEAPON, MAP_DEEP_SURFACE" — so the oracle names the bit. ⛔ A "never observed" note is a
# statement about the SAMPLE, never about the format: catalogue is a lower bound.
# Bits 0/8/14/18/28/29 remain unobserved — same rule applies to them.
BOUND_COMPOSITE_FLAG_BITS = {
    1: "MAP_WEAPON", 2: "MAP_DYNAMIC", 3: "MAP_ANIMAL", 4: "MAP_COVER", 5: "MAP_VEHICLE",
    6: "VEHICLE_NOT_BVH", 7: "VEHICLE_BVH", 9: "PED", 10: "RAGDOLL", 11: "ANIMAL",
    12: "ANIMAL_RAGDOLL", 13: "OBJECT", 15: "PLANT", 16: "PROJECTILE", 17: "EXPLOSION",
    19: "FOLIAGE", 20: "FORKLIFT_FORKS", 21: "TEST_WEAPON", 22: "TEST_CAMERA", 23: "TEST_AI",
    24: "TEST_SCRIPT", 25: "TEST_VEHICLE_WHEEL", 26: "GLASS", 27: "MAP_RIVER", 30: "MAP_STAIRS",
    31: "MAP_DEEP_SURFACE",
}

# material Flags = bits 24-39 of the 8-byte material record (8,813 measured pairs, zero
# conflicts). Bit 11 has never been seen set - over the 8,813 pairs here and over all 13,482 ybn
# reference exports (2026-08-02 vocabulary scan, 16 distinct flag names, every one already in this
# table). ⛔ Read that as "no instrument has met one", not "the format has none": bit 31 of the
# COMPOSITE table read exactly this way for 1,080 files and then cost a 15% conversion failure on
# x64p. The unnamed-bit refusal in _bound_flags_text is what makes that survivable.
BOUND_MATERIAL_FLAG_BITS = {
    0: "FLAG_STAIRS", 1: "FLAG_NOT_CLIMBABLE", 2: "FLAG_SEE_THROUGH", 3: "FLAG_SHOOT_THROUGH",
    4: "FLAG_NOT_COVER", 5: "FLAG_WALKABLE_PATH", 6: "FLAG_NO_CAM_COLLISION",
    7: "FLAG_SHOOT_THROUGH_FX", 8: "FLAG_NO_DECAL", 9: "FLAG_NO_NAVMESH", 10: "FLAG_NO_RAGDOLL",
    12: "FLAG_NO_PTFX", 13: "FLAG_TOO_STEEP_FOR_PLAYER", 14: "FLAG_NO_NETWORK_SPAWN",
    15: "FLAG_NO_CAM_COLLISION_ALLOW_CLIPPING",
}

# header bytes with no bound XML field: only zero ever measured (the four still-unbound
# always-0 XML fields live somewhere here, so a non-zero byte would make an emitted 0 wrong).
# ⚠ SCOPE OF "ever measured", so nobody quotes it as game-wide: 1,012 ydr embedded bounds, 183
# local ybn (all dt1_*/fwy_*/hi@* - one map area, 1.4% of the game's 13,482 ybn), and 19 fragment
# CLOTH bounds (2026-08-03) - 0 non-zero bytes in any of them. The oracle cannot widen this: it
# only prints fields, and these lanes have none.
_BOUND_HEADER_ZERO_BYTES = (0x11, 0x12, 0x13, 0x18, 0x19, 0x1A, 0x1B, 0x1C, 0x1D, 0x1E, 0x1F,
                            0x4D, 0x4E, 0x5D, 0x5E, 0x5F)


class BoundsError(ValueError):
    """Loud refusal - the input holds a value this emitter has no measurement for."""


def _bound_entry_list(tag, rows, ind):
    """MEASURED: comma-tuple list elements (Vertices/MaterialColours/VertexColours) render
    INLINE with one entry, block with one entry per line at ind+1 otherwise."""
    if len(rows) == 1:
        return ["%s<%s>%s</%s>" % (ind, tag, rows[0], tag)]
    return (["%s<%s>" % (ind, tag)] + ["%s %s" % (ind, r) for r in rows]
            + ["%s</%s>" % (ind, tag)])


def _bound_flags_text(value, table, what, ctx):
    if value == 0:
        return "NONE"
    names = []
    for b in range(32):
        if (value >> b) & 1:
            n = table.get(b)
            if n is None:
                raise BoundsError(f"{ctx}: {what} bit {b} set (value 0x{value:08x}) but "
                                  f"UNNAMED - refusing rather than dropping a filter bit")
            names.append(n)
    return ", ".join(names)


def _bound_deref(res, tagged, need, what, ctx):
    buf, o = res.deref(tagged, need)
    if buf is None:
        raise BoundsError(f"{ctx}: {what} pointer 0x{tagged:08x} does not resolve")
    return buf, o


def _bound_header_lines(res, off, ind, ctx):
    """The 17 header elements every bound type carries, in reference order. Bindings:
    +0x14 SphereRadius | +0x20 BoxMax +0x2C Margin | +0x30 BoxMin +0x3C u32 UnkType |
    +0x40 BoxCenter +0x4C u8 MaterialIndex +0x4F u8 UnkFlags | +0x50 SphereCenter
    +0x5C u8 PolyFlags | +0x60 Inertia +0x6C Volume (all measured - see the LOG entry)."""
    for b in _BOUND_HEADER_ZERO_BYTES:
        if res.sys[off + b]:
            raise BoundsError(f"{ctx}: header byte +0x{b:02x} = 0x{res.sys[off + b]:02x} "
                              f"(only zero ever measured there)")
    f = lambda o: struct.unpack_from("<f", res.sys, off + o)[0]
    v3 = lambda o: struct.unpack_from("<3f", res.sys, off + o)
    L = []
    for tag, o in (("BoxMin", 0x30), ("BoxMax", 0x20), ("BoxCenter", 0x40),
                   ("SphereCenter", 0x50)):
        x, y, z = v3(o)
        L.append('%s<%s x="%s" y="%s" z="%s" />' % (ind, tag, fmt_num(x), fmt_num(y),
                                                    fmt_num(z)))
    L.append('%s<SphereRadius value="%s" />' % (ind, fmt_num(f(0x14))))
    L.append('%s<Margin value="%s" />' % (ind, fmt_num(f(0x2C))))
    L.append('%s<Volume value="%s" />' % (ind, fmt_num(f(0x6C))))
    ix, iy, iz = v3(0x60)
    L.append('%s<Inertia x="%s" y="%s" z="%s" />' % (ind, fmt_num(ix), fmt_num(iy),
                                                     fmt_num(iz)))
    L.append('%s<MaterialIndex value="%d" />' % (ind, res.sys[off + 0x4C]))
    for tag in ("MaterialColourIndex", "ProceduralID", "RoomID", "PedDensity"):
        L.append('%s<%s value="0" />' % (ind, tag))        # zero-checked lanes above
    L.append('%s<UnkFlags value="%d" />' % (ind, res.sys[off + 0x4F]))
    L.append('%s<PolyFlags value="%d" />' % (ind, res.sys[off + 0x5C]))
    L.append('%s<UnkType value="%d" />' % (ind, res.u32(off + 0x3C)))
    return L


def _bound_geometry_lines(res, off, ind, ctx):
    """Geometry / GeometryBVH payload. Record map (all measured): +0x88 polys (16 B) ·
    +0x90 Quantum vec3 (.w = UnkFloat1) · +0xA0 CenterGeom (.w = UnkFloat2) · +0xB0 verts
    (s16 x3; world_rel = s16 * Quantum in float32) · +0xB8 VertexColours · +0xD0/+0xD4
    vert/poly counts · +0xF0 materials (8 B) · +0xF8 MaterialColours · +0x118 per-poly
    material u8 · +0x120/+0x121 u8 material/materialcolour counts. Polygon type = low 3
    bits of byte 0: 0 Triangle / 1 Sphere / 2 Capsule / 3 Box / 4 Cylinder."""
    f = lambda o: struct.unpack_from("<f", res.sys, off + o)[0]
    gx, gy, gz = struct.unpack_from("<3f", res.sys, off + 0xA0)
    L = ['%s<GeometryCenter x="%s" y="%s" z="%s" />' % (ind, fmt_num(gx), fmt_num(gy),
                                                        fmt_num(gz)),
         '%s<UnkFloat1 value="%s" />' % (ind, fmt_num(f(0x9C))),
         '%s<UnkFloat2 value="%s" />' % (ind, fmt_num(f(0xAC)))]
    nverts, npolys = res.u32(off + 0xD0), res.u32(off + 0xD4)
    nmat, nmatcol = res.sys[off + 0x120], res.sys[off + 0x121]
    if not (0 < nverts <= 0x8000) or not (0 < npolys <= 0x100000) or nmat == 0:
        raise BoundsError(f"{ctx}: implausible counts verts={nverts} polys={npolys} "
                          f"mats={nmat}")
    mb, mo = _bound_deref(res, res.u32(off + 0xF0), nmat * 8, "materials", ctx)
    L.append("%s<Materials>" % ind)
    for i in range(nmat):
        u = struct.unpack_from("<Q", mb, mo + i * 8)[0]
        L += ["%s <Item>" % ind,
              '%s  <Type value="%d" />' % (ind, u & 0xFF),
              '%s  <ProceduralID value="%d" />' % (ind, (u >> 8) & 0xFF),
              '%s  <RoomID value="%d" />' % (ind, (u >> 16) & 0x1F),
              '%s  <PedDensity value="%d" />' % (ind, (u >> 21) & 0x7),
              "%s  <Flags>%s</Flags>" % (ind, _bound_flags_text(
                  (u >> 24) & 0xFFFF, BOUND_MATERIAL_FLAG_BITS, "material flag", ctx)),
              '%s  <MaterialColourIndex value="%d" />' % (ind, (u >> 40) & 0xFF),
              '%s  <Unk value="%d" />' % (ind, u >> 48),
              "%s </Item>" % ind]
    L.append("%s</Materials>" % ind)
    mc_p = res.u32(off + 0xF8)
    if nmatcol or mc_p:
        if not (nmatcol and mc_p):
            raise BoundsError(f"{ctx}: MaterialColours count/pointer disagree")
        cb, co = _bound_deref(res, mc_p, nmatcol * 4, "material colours", ctx)
        L += _bound_entry_list("MaterialColours",
                               ["%d, %d, %d, %d" % tuple(cb[co + i * 4: co + i * 4 + 4])
                                for i in range(nmatcol)], ind)
    q = struct.unpack_from("<3f", res.sys, off + 0x90)
    vb, vo = _bound_deref(res, res.u32(off + 0xB0), nverts * 6, "vertices", ctx)
    rows = []
    for i in range(nverts):
        sx, sy, sz = struct.unpack_from("<3h", vb, vo + i * 6)
        rows.append("%s, %s, %s" % (fmt_num(sx * q[0]), fmt_num(sy * q[1]),
                                    fmt_num(sz * q[2])))
    L += _bound_entry_list("Vertices", rows, ind)
    vc_p = res.u32(off + 0xB8)
    if vc_p:
        cb, co = _bound_deref(res, vc_p, nverts * 4, "vertex colours", ctx)
        L += _bound_entry_list("VertexColours",
                               ["%d, %d, %d, %d" % tuple(cb[co + i * 4: co + i * 4 + 4])
                                for i in range(nverts)], ind)
    pb, po = _bound_deref(res, res.u32(off + 0x88), npolys * 16, "polygons", ctx)
    pmb, pmo = _bound_deref(res, res.u32(off + 0x118), npolys, "poly materials", ctx)
    L.append("%s<Polygons>" % ind)
    for i in range(npolys):
        rec = po + i * 16
        m = pmb[pmo + i]
        w = struct.unpack_from("<8H", pb, rec)
        ptype = pb[rec] & 7
        if ptype == 0:
            v = [(w[2 + j] & 0x7FFF, w[2 + j] >> 15) for j in range(3)]
            L.append('%s <Triangle m="%d" v1="%d" v2="%d" v3="%d" f1="%d" f2="%d" f3="%d" />'
                     % (ind, m, v[0][0], v[1][0], v[2][0], v[0][1], v[1][1], v[2][1]))
        elif ptype == 1:
            L.append('%s <Sphere m="%d" v="%d" radius="%s" />'
                     % (ind, m, w[1], fmt_num(struct.unpack_from("<f", pb, rec + 4)[0])))
        elif ptype == 2:
            L.append('%s <Capsule m="%d" v1="%d" v2="%d" radius="%s" />'
                     % (ind, m, w[1], w[4], fmt_num(struct.unpack_from("<f", pb, rec + 4)[0])))
        elif ptype == 3:
            L.append('%s <Box m="%d" v1="%d" v2="%d" v3="%d" v4="%d" />'
                     % (ind, m, w[2], w[3], w[4], w[5]))
        elif ptype == 4:
            L.append('%s <Cylinder m="%d" v1="%d" v2="%d" radius="%s" />'
                     % (ind, m, w[1], w[4], fmt_num(struct.unpack_from("<f", pb, rec + 4)[0])))
        else:
            raise BoundsError(f"{ctx}: polygon {i} has UNMEASURED type code {ptype}")
    L.append("%s</Polygons>" % ind)
    return L


def _bound_lines(res, off, ind, tag, ctx, extra=None, depth=0, absent_flags_text=None):
    """`absent_flags_text`: what CompositeFlags1/2 print when the flags ARRAY is absent
    (fl_p == 0). None = OMIT the elements — measured on yft PHYSICS bounds, whose reference
    omits them. The yft CLOTH custom bound (verlet+0x18) measures the OTHER way: 3/3 witness
    oracles print <CompositeFlags1>NONE</CompositeFlags1> for every child while the flags
    pointer is null — so that caller passes "NONE". The presence rule is CONTEXT-dependent
    and each caller states its measured context; there is no universal default."""
    if depth > 4:
        raise BoundsError(f"{ctx}: composite nesting depth {depth} never measured")
    t = res.sys[off + 0x10]
    name = BOUND_TYPE_NAMES.get(t)
    if name is None:
        raise BoundsError(f"{ctx}: UNMEASURED bound type code {t} at sys+0x{off:x}")
    L = ['%s<%s type="%s">' % (ind, tag, name)]
    inner = ind + " "
    L += _bound_header_lines(res, off, inner, ctx)
    if extra:
        L += extra
    if t in _BOUND_GEOMETRY_TYPES:
        L += _bound_geometry_lines(res, off, inner, ctx)
    elif t == 10:
        n = res.u16(off + 0xA0)
        carr_p, tr_p, fl_p = res.u32(off + 0x70), res.u32(off + 0x78), res.u32(off + 0x90)
        cb, co = _bound_deref(res, carr_p, n * 8, "composite children", ctx)
        if tr_p:
            tb, to = _bound_deref(res, tr_p, n * 64, "composite transforms", ctx)
        elif n:
            raise BoundsError(f"{ctx}: composite has {n} children but no transform array")
        fb = fo = None
        if fl_p:                       # flags OMITTED entirely when absent (measured: yft)
            fb, fo = _bound_deref(res, fl_p, n * 8, "composite flags", ctx)
        L.append("%s<Children>" % inner)
        for i in range(n):
            cp = struct.unpack_from("<I", cb, co + i * 8)[0]
            if cp == 0:
                L.append('%s <Item type="None" />' % inner)
                continue
            _, ch = _bound_deref(res, cp, 0x70, f"child {i}", ctx)
            ci2 = inner + "  "
            mv = struct.unpack_from("<16f", tb, to + i * 64)
            extra_i = ["%s<CompositeTransform>" % ci2]
            for r in range(4):         # stored 4x(3f+pad); 4th column SYNTHESISED 0,0,0,1
                extra_i.append("%s %s %s %s %s" % (ci2, fmt_num(mv[r * 4]),
                                                   fmt_num(mv[r * 4 + 1]),
                                                   fmt_num(mv[r * 4 + 2]),
                                                   "1" if r == 3 else "0"))
            extra_i.append("%s</CompositeTransform>" % ci2)
            if fb is not None:
                f1, f2 = struct.unpack_from("<II", fb, fo + i * 8)
                extra_i.append("%s<CompositeFlags1>%s</CompositeFlags1>" % (
                    ci2, _bound_flags_text(f1, BOUND_COMPOSITE_FLAG_BITS,
                                           "CompositeFlags1", ctx)))
                extra_i.append("%s<CompositeFlags2>%s</CompositeFlags2>" % (
                    ci2, _bound_flags_text(f2, BOUND_COMPOSITE_FLAG_BITS,
                                           "CompositeFlags2", ctx)))
            elif absent_flags_text is not None:
                extra_i.append("%s<CompositeFlags1>%s</CompositeFlags1>"
                               % (ci2, absent_flags_text))
                extra_i.append("%s<CompositeFlags2>%s</CompositeFlags2>"
                               % (ci2, absent_flags_text))
            L += _bound_lines(res, ch, inner + " ", "Item", f"{ctx} child {i}",
                              extra=extra_i, depth=depth + 1,
                              absent_flags_text=absent_flags_text)
        L.append("%s</Children>" % inner)
    # primitives (Sphere/Capsule/Box/Disc/Cylinder) and Cloth: header only - measured. Cloth was
    # checked the same way the primitives were, against the reference export of the same bound:
    # 19 cloth bounds, 494/494 header fields agree, 0 elements the oracle does not also carry.
    L.append("%s</%s>" % (ind, tag))
    return L


def bounds_lines(res, base=0, name="?"):
    """The <Bounds> element lines for the drawable at system offset `base`, [] when it has
    no bound. Raises BoundsError - loudly, naming the file - on anything unmeasured."""
    tagged = res.u32(base + 0xC8)
    if res.u32(base + 0xCC):
        # The +0xC8 bound-pointer law was measured on STANDALONE ydr (high dword 0 in
        # 3,479/3,479). Fragment-embedded drawables carry other data in this slot - their
        # collision lives in the fragment's own phys structures, not the drawable tail - so a
        # non-zero high dword means "not a ydr-style bound here", never a bound to refuse.
        # On real ydr this branch is unreachable by measurement. On FRAGMENTS it is the ONLY
        # path: 800 of 800 random base-game yft main drawables have a non-zero high dword
        # (drawlane/silentsites.py), so no .yft.xml has ever carried a <Bounds> element. That is
        # also why BOUND_TYPE_NAMES' new Cloth entry changes no output today - fragment collision
        # is not routed through here at all. Left UNCOUNTED on purpose: a counter that fires on
        # 100% of one file type reports the file type, not a problem.
        return []
    if tagged == 0:
        return []
    _, off = _bound_deref(res, tagged, 0x70, "root bound", name)
    return _bound_lines(res, off, " ", "Bounds", name)


def boundsfile_lines(res, name="?"):
    """Standalone bound (.ybn, RSC7 v43; root phBound at system offset 0) as a full
    BoundsFile document - oracle-validated against 183 name-matched reference exports."""
    res.require_version(43, "bounds file")
    L = ['<?xml version="1.0" encoding="UTF-8"?>', "<BoundsFile>"]
    L += _bound_lines(res, 0, " ", "Bounds", name)
    L.append("</BoundsFile>")
    return L


# ---------------------------------------------------------------- emit

def esc(s):
    for a, b in (("&", "&amp;"), ("<", "&lt;"), (">", "&gt;"), ('"', "&quot;")):
        s = s.replace(a, b)
    return s


def drawable_lines(res, name, base=0, allow_empty=False, include_bounds=True,
                   include_lights=True):
    """The <Drawable> BODY (Name/bounds/ShaderGroup/DrawableModelsHigh) as lines with the standalone
    file's one-space indent. Shared: the ydr wrapper adds declaration+root; a dictionary converter
    (ydd/yft) wraps each entry as <Item> and re-indents. Whitespace is free to the consumer -
    FXmlFile tokenises on any whitespace - so only token count and order matter.

    allow_empty: emit a drawable with NO geometry instead of refusing. Only yft2xml sets it, and
    only for the measured case where a fragment's visual mesh lives entirely in a physics child -
    see the comment at its call site.
    include_bounds/include_lights: the ypt lane sets both False (measured 2026-08-10 on the
    store's one non-empty DrawableDictionary, wpn_amrifle: +0xC8 holds non-bound tail data the
    +0xCC escape does not catch, and the oracle emits neither <Bounds> nor <Lights />). The
    defaults keep the ydr/ydd/yft lanes byte-stable."""
    shaders = read_shaders(res, base)
    geos = read_geometries(res, base)
    if not geos and not allow_empty:
        raise ValueError("no geometry decoded")
    # ⛔ 9 OF 10 GEOMETRIES USED TO BE "COMPLETE SUCCESS" (2026-08-03). The only geometry gate here
    # was `if not geos`, so every partial loss inside read_geometries was invisible - the XML, the
    # corpus counter, the import verdict and the geometry count all agreed with a file that simply
    # had fewer meshes. Refusing on the shortfall is what makes them disagree.
    if len(geos) != geos.declared:
        raise ValueError("%d of %d geometries did not resolve"
                         % (geos.declared - len(geos), geos.declared))
    b = read_bounds(res, base)
    ff = fmt_float
    L = []
    L.append(" <Name>%s</Name>" % esc(name))
    L.append(' <BoundingSphereCenter x="%s" y="%s" z="%s" />' % tuple(ff(v) for v in b["sphere_c"]))
    L.append(' <BoundingSphereRadius value="%s" />' % ff(b["sphere_r"]))
    L.append(' <BoundingBoxMin x="%s" y="%s" z="%s" />' % tuple(ff(v) for v in b["bb_min"]))
    L.append(' <BoundingBoxMax x="%s" y="%s" z="%s" />' % tuple(ff(v) for v in b["bb_max"]))
    # LodDist quartet: consecutive float32 @ drawable+0x70..0x7C - derived 2026-08-05 by
    # oracle-value/offset intersection over 8 binaries (wheel2_bkr_01p discriminates High;
    # the rest follow in struct order). Flags quartet: the bitmask of RenderBuckets used
    # by that LOD's geometries - COMPUTED, not read: no aligned header field holds it, and
    # the computed mask matches 170/172 oracle drawables. The 2 exceptions carry a stored
    # Med bit with NO Med models (wheel2_bkr_01p, task_000_u) - a named residual the sweep
    # keeps visible until the stored field is located; never guessed.
    ld = struct.unpack_from("<4f", res.sys, base + 0x70)
    for tag, v in zip(("LodDistHigh", "LodDistMed", "LodDistLow", "LodDistVlow"), ld):
        L.append(' <%s value="%s" />' % (tag, ff(v)))
    # Flags quartet: STORED u8 @ base+0x80/84/88/8C (4-byte stride; the second byte is
    # 0xFF when the LOD is active). Probed 2026-08-06: wheel2 `01 FF|01 FF|00|00` reads
    # (1,1,0,0) exactly - including the Med flag its emitted models can't compute, which
    # is what disproved the earlier computed-bucket-mask shortcut (right 170/172 by
    # coincidence: stored usually equals the mask).
    for tag, off in zip(("FlagsHigh", "FlagsMed", "FlagsLow", "FlagsVlow"),
                        (0x80, 0x84, 0x88, 0x8C)):
        L.append(' <%s value="%d" />' % (tag, res.sys[base + off]))
    L.append(" <ShaderGroup>")
    emb = embedded_textures(res, base, what=name)
    if emb:
        # The drawable's own textures, emitted so a consumer can see and import them. Pixel
        # sidecars are written alongside by the caller (quarry.to_interchange_xml).
        L.append("  <TextureDictionary>")
        for t in emb:
            L += ["   <Item>",
                  "    <Name>%s</Name>" % esc(t["name"]),
                  '    <Unk32 value="%d" />' % t.get("unk32", 0),
                  "    <Usage>%s</Usage>" % t["usage"],
                  "    <UsageFlags>%s</UsageFlags>" % t.get("usage_flags", "0"),
                  '    <ExtraFlags value="%d" />' % t.get("extra_flags", 0),
                  '    <Width value="%d" />' % t["width"],
                  '    <Height value="%d" />' % t["height"],
                  '    <MipLevels value="%d" />' % t["mips"],
                  "    <Format>%s</Format>" % t["xml_fmt"],
                  "    <FileName>%s.dds</FileName>" % esc(t["name"]),
                  "   </Item>"]
        L.append("  </TextureDictionary>")
    L.append("  <Shaders>")
    if not shaders:
        # One default material for geometries whose ShaderIndex may run up to N-1; the consumer
        # clamps (RudeToolset.cpp:1843). For a fragment CHILD drawable this is the CORRECT and
        # measured shape - it has no ShaderGroup pointer at all and yft2xml splices the
        # fragment's group into the sidecar - so only the other cause is counted: a drawable
        # that HAS a shader group and still yielded nothing is silently rendering everything on
        # the default material.
        if res.ptr(base + 0x10):
            _refuse("shader_group_yielded_nothing_default_substituted", name)
        # FileName "" -> <FileName /> : the only oracle-observed default-shader spelling
        # (farlods.ydd) carries an EMPTY FileName, not "default.sps"
        shaders = [("default", "", 0, [])]
    # Shader item shape measured against the 2026-08-05 oracle set: FileName after Name
    # (the +0x18 hash - NOT derivable from the name, see sps_filename); texture params
    # as a 3-line Item; single-float4 value params INLINE as attributes; multi-row
    # params as type="Array" with <Value> children. `count=` is never spelled (0
    # occurrences corpus-wide).
    for preset, spsfn, bucket, params in shaders:
        L.append("   <Item>")
        L.append("    <Name>%s</Name>" % esc(preset))
        L.append("    <FileName>%s</FileName>" % esc(spsfn) if spsfn
                 else "    <FileName />")
        L.append('    <RenderBucket value="%d" />' % bucket)
        L.append("    <Parameters>")
        for kind, pname, payload in params:
            if kind == "tex":
                if payload is None:      # unbound sampler slot - oracle self-closing form
                    L.append('     <Item name="%s" type="Texture" />' % pname)
                else:
                    L.append('     <Item name="%s" type="Texture">' % pname)
                    L.append("      <Name>%s</Name>" % esc(payload))
                    L.append("     </Item>")
            elif len(payload) == 1:
                x, y, z, wv = payload[0]
                L.append('     <Item name="%s" type="Vector" x="%s" y="%s" z="%s" w="%s" />'
                         % (pname, ff(x), ff(y), ff(z), ff(wv)))
            else:
                L.append('     <Item name="%s" type="Array">' % pname)
                for (x, y, z, wv) in payload:
                    L.append('      <Value x="%s" y="%s" z="%s" w="%s" />'
                             % (ff(x), ff(y), ff(z), ff(wv)))
                L.append("     </Item>")
        L.append("    </Parameters>")
        L.append("   </Item>")
    L.append("  </Shaders>")
    L.append(" </ShaderGroup>")
    # <Skeleton> sits between ShaderGroup and the model groups (sniper oracle order);
    # NULL @+0x18 -> no element at all.
    L.extend(skeleton_lines(res, base))
    # DrawableModels{High,Medium,Low,VeryLow} from ptrs +0x50/58/60/68; an absent group
    # is OMITTED (never self-closed). The High group already read above is reused; the
    # rest are read per-LOD. RenderMask/Flags/HasSkin/BoneIndex/Unknown1 quintet, plus
    # per-geometry bbox + BoneIDs; VertexBuffer opens with <Flags value="0">.
    for goff, tag in DRAWABLE_MODEL_GROUPS:
        g = geos if goff == 0x50 else read_geometries(res, base, group_off=goff)
        if goff != 0x50 and (not g or len(g) != g.declared):
            if g and len(g) != g.declared:
                raise ValueError("%s: %d of %d geometries did not resolve"
                                 % (tag, g.declared - len(g), g.declared))
            continue
        L.extend(_model_group_lines(ff, tag, g))
    # embedded collision - flows to ydd2xml/yft2xml automatically since they call
    # drawable_lines with their entry's base offset (the bound ptr is base-relative
    # at +0xC8; a drawable without a bound contributes nothing)
    if include_bounds:
        L.extend(bounds_lines(res, base, name))
    # <Lights> comes AFTER Bounds (oracle order, caught by the golddisc pair); the
    # LightAttrs decoder emits the populated form (animlight family + des_tvsmash)
    if include_lights:
        L.extend(lights_lines(res, base))
    return L


def drawable_name_slot(res):
    """The `<Name>` string at drawable+0xA8 - and the ONE field v164 does not have.

    ⭐⭐ v164 = THE OLDER-BUILD DRAWABLE STAMP, SAME LAYOUT AS v165 (measured 2026-08-15).
    The game holds exactly 13 v164 `.ydr` against 86,677 v165 (whole-game RSC7 version census,
    347,980 resource entries; the census key set reconciles EXACTLY with the 86,690-key
    population enumeration, 0 difference either way). All 13 sit in the six older-build
    0x18-header archives; none outside. ⚠ The scoped-run figure of "14 in x64f" is REFUTED -
    x64f holds 12, x64j holds 1.

    THE LAYOUT IS v165's, and the tests that could have refused it did not:
      * every tagged header pointer resolves inside the segment its tag names (13/13)
      * every model count == its capacity, every geometry count <= its capacity, and every
        model/geometry array fits the space its count claims (13/13)
      * BoundingBoxMin <= Max on all three axes, sphere radius plausible, and the LodDist
        quartet reads 0x461C3800 == 9998.0 - the same constant the v165 controls carry
      * `+0xA0` is the byte-identical alias of `+0x50` in both versions
      * ROUND-TRIP, the primary measure, through the COMPLETELY UNMODIFIED writer
        (`ydr_write.read_ydr` has no version check at all): **10 of 13 byte-exact**; the other
        three leave 168 / 417 / 189 residual bytes, i.e. the small-residual class the v165
        population also shows - not a structural failure.
      * every one of the 13 converts with its geometry count equal to what its own model
        records declare (`drawable_lines` refuses on any shortfall; none refused)
    ⭐ PRECEDENT IN THE SAME FAMILY: `yft2xml` already accepts v160 beside v162, and all 66
    v160 fragments in the game are byte-exact at population. The version nibble is a BUILD
    stamp, not a resource shape.

    ⛔ THE ONE REAL DIFFERENCE, and why this function exists: **a v164 drawable carries no name.**
    `.#dr` appears nowhere in any of the 13 system segments, while all four v165 controls hold it
    exactly at the `+0xA8` target. The v164 `+0xA8` holds a small 16-byte-aligned UNTAGGED
    integer (288/528/736/1536/1952/2112/2672/4224/31680) that is not a pointer: read as a raw
    system offset it lands on float data in some files and on an array descriptor in another, and
    it equals none of nverts / nindices / index bytes / geometry count / segment length on all 13.
    ⛔ Do NOT resolve it as a pointer - `cstr` would count 13 false `cstr_pointer_unresolved`
    declines for a field that is not a string pointer in this version. The stem substitution is
    the CORRECT reading, and it is COUNTED so the class stays visible."""
    if res.version != 165:
        _refuse("drawable_v164_has_no_name_field_stem_substituted", res.name or "?")
        return ""
    return res.cstr(res.ptr(0xA8))


def to_xml(res, name):
    # v164 = the older-build drawable stamp: SAME layout as 165, measured 13/13 - see
    # drawable_name_slot for the whole derivation. Accepted AND COUNTED, exactly as
    # yft2xml.convert accepts the v160 mod-part stamp, so a rising count stays visible.
    try:
        res.require_version(165, "Legacy drawable")
    except ValueError:
        res.require_version(164, "Legacy drawable (v164 older-build stamp)")
        _refuse("drawable_v164_accepted_same_layout_as_165", res.name or name)
    L = ['<?xml version="1.0" encoding="UTF-8"?>', "<Drawable>"]
    L.extend(drawable_lines(res, name))
    L.append("</Drawable>")
    return "\n".join(L) + "\n"


def convert(path):
    res = Res(path)
    stem = os.path.splitext(os.path.basename(path))[0]
    # real drawables name themselves "<stem>.#dr"; keep the convention
    inner = drawable_name_slot(res) or (stem + ".#dr")
    return to_xml(res, inner), stem


def main():
    ap = argparse.ArgumentParser(prog="ydr2xml")
    ap.add_argument("files", nargs="*")
    ap.add_argument("--out", help="output directory for <stem>.ydr.xml")
    ap.add_argument("--selftest", action="store_true",
                    help="convert and re-parse in memory; write nothing")
    a = ap.parse_args()
    if not a.files:
        ap.error("give at least one .ydr")
    ok = fail = 0
    for p in a.files:
        try:
            xml, stem = convert(p)
        except Exception as e:
            print(f"FAIL {os.path.basename(p)}: {type(e).__name__}: {e}")
            fail += 1
            continue
        if a.selftest:
            import xml.etree.ElementTree as ET
            root = ET.fromstring(xml)
            ng = len(root.findall("./DrawableModelsHigh/Item/Geometries/Item"))
            ns = len(root.findall("./ShaderGroup/Shaders/Item"))
            print(f"OK   {os.path.basename(p):<44} {ng:3} geos  {ns:3} shaders  "
                  f"{len(xml):>10,} B xml")
        else:
            if not a.out:
                ap.error("--out is required unless --selftest")
            os.makedirs(a.out, exist_ok=True)
            dst = os.path.join(a.out, stem + ".ydr.xml")
            open(dst, "w", encoding="utf-8", newline="\n").write(xml)
            print(f"OK   {os.path.basename(p)} -> {dst}  ({len(xml):,} B)")
        ok += 1
    print(f"\n{ok} converted, {fail} failed")
    report_refusals()          # a downgrade that never reaches a human is still a silent one
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
