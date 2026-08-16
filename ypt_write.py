"""ypt_write - ROUND-TRIP WRITER for .ypt rmPtfx particle-effect lists (RSC7 v68).

    inflated system+graphics segments -> value model -> written back -> MUST reproduce the bytes

WHY (maintainer ruling 2026-08-13): round-trip byte identity is the primary measure, and a lane
with no writer is UNMEASURED, not passing. `.ypt` had a 1,022-line READER (`ypt2xml.py`) whose
header claims "COMPLETE ... verified BYTE-IDENTICAL 10/10" - that is reference-parity on a TEN-FILE
board for a 1,240-file lane, and its own KNOWN LIMITATION section admits behaviour scalars are
emitted as observed literals because no offset was ever pinned for them. This file is what turns
every .ypt in the game into an oracle at no cost, because you cannot rebuild what you never read.

MODEL, NOT MEMCPY, and stronger than `ynd_write` (which re-emits opaque per-record slices):
every object is rebuilt from a DECLARED FIELD MAP into a ZERO-FILLED image, and `_check_maps()`
REFUSES AT IMPORT if any map overlaps itself or runs past its declared object size. Whatever the
model never reaches stays zero and shows up as a difference. **The gaps are the finding.**

⭐⭐ THE VTABLE IS DERIVED FROM THE DECODED CLASS, NOT CARRIED. Every RAGE polymorphic object in
this format stores an 8-byte vtable at +0x00, and measured over the population it is CONSTANT PER
CLASS. So the writer looks the value up BY THE CLASS IT DECIDED THE OBJECT IS - and a mis-decoded
behaviour type, domain type or shadervar type writes the wrong 8 bytes and the round-trip REJECTS
it. That is the property the measure needs: a wrong claim COULD have been refused. `ptxDomain`
and the shadervar family are polymorphic and their vtable IS the discriminator, so this is not a
formality - it is the tightest test in the file. `Ypt.vt_mismatch` counts every disagreement.

⭐⭐ COVERAGE AT POPULATION 2026-08-15 - THE LANE IS CLOSED. Every `.ypt` in the game, 1,240 files
(equal to the census in `output/view/VIEW_SUMMARY.json` to the file), one walk, 550 s:
    python tools/ypt_population.py --control
    EXACT round-trip (every byte of BOTH segments) : 1,240 / 1,240 = 100.0000%
    system   segment : 278,167,552 / 278,167,552 = 100.000000%
    graphics segment : 272,105,472 / 272,105,472 = 100.000000%
    vtable mismatches 0 | interior-nonzero 0 | OVERLAPPING CLAIMS 0 | reader errors 0
    (overlapping claims must read 0 or the control battery is meaningless: where two claims cover
     a byte the later one hides the earlier, and corrupting the earlier cannot move the image.)
⛔ AND THE NUMBER IS ONLY WORTH WHAT ITS BYTE ACCOUNT SAYS, so quote them together. Over the
NON-ZERO bytes of the system segment - the informative denominator, because 49.5% of a .ypt system
segment is zero padding and an all-bytes split flatters every writer equally:
    VALUE 78.5120%  |  DERIVED 16.3786%  |  CARRIED-VERBATIM 5.1095%   (49,785,116 non-zero bytes)
    all bytes:  ZERO 49.5149% | VALUE 43.8994% | DERIVED 4.7299% | CARRIED 1.8557%
    graphics segment: 80.89% CARRIED - it is the embedded TEXTURE PIXELS and decoding a
    BC-compressed texel block is not what this measure is about. 100% here means the RAGE
    structure is rebuilt, NOT that we model the pixels. The other 19.11% is zero.
    Of VALUE, 82.93% sits at a NAMED field (101,271,003 B) and 17.07% at a declared-but-unnamed
    `unk` slot (20,844,788 B) - a slot that is decoded and re-encoded at a declared width inside a
    declared class, but for which no semantic has been derived. Stated, not hidden.
⭐ MUST-FAIL CONTROL, 7 families, WORST CATCH RATE 100.000% (`--control`): flip a decoded scalar,
flip a derived vtable, flip a carried blob, mislabel every behaviour class, retune the 0x90
KeyframeProp stride, retune the 32-byte keyframe stride, drop a declared field. A control with no
subject (an empty .ypt has no behaviours to mislabel) is REPORTED, never scored as a miss.

⛔⛔ AND THE CONTROL IS NOT DECORATION - IT CAUGHT A LIVE REGRESSION THIS LANE COULD NOT OTHERWISE
SEE. Class-qualifying the field labels broke the `raw == 'vtable'` guard in `_emit_fields`, so
every vtable was re-emitted as a VERBATIM VALUE COPY on top of the DERIVED claim. The lane stayed
at 1,240/1,240 and 100.000000% throughout, because a copy reproduces the same bytes. Only the
control moved: `derived_vtable` fell from 100.000% to 1.667%. **Byte identity cannot tell the
strongest claim in a writer from a memcpy of it.**

⚠ SCOPE: round-trips the INFLATED segments, not the compressed RSC7 container - reproducing the
container also means reproducing an exact deflate stream, which is a separate problem.
⚠ TWO SEGMENTS, REPORTED SEPARATELY (the ydr lesson): the effect graph lives in `sys` and the
embedded texture PIXELS live in `gfx`, which is 49.4% of the lane's bytes. A blended number would
hide which half is modelled.
ASCII output only.
"""
import os
import struct
import sys as _sys

_sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ydr2xml import Res       # noqa: E402
import meta_write             # noqa: E402  (page_count - the COMPUTED page record)
import ypt2xml                # noqa: E402  (BEH_TYPEHASH / SV_TYPE - the decode tables)

YPT_VERSION = 68

# --------------------------------------------------------------------------- byte accounting
# VALUE   - re-encoded with struct.pack from a value decoded through a declared, width-typed
#           field of a declared class map. Refutable: mutate the decoded value and the image moves.
# DERIVED - computed from something OTHER than the bytes themselves: a vtable from the decoded
#           class, the page-count record, an array count driven by the walk.
# CARRIED - an opaque blob copied verbatim. The model does not know what is inside.
# (anything unclaimed stays ZERO and is only correct where the original is zero)
VALUE, DERIVED, CARRIED = 1, 2, 3
# --------------------------------------------------------------------------- the name class
# ⭐ MEASURED, and the first version of this line was NOT - it claimed to be a population census
# and was actually a guess (it allowed `- . space + @ #`, none of which occur, and disallowed the
# one byte that does). `tools/ypt_name_charset.py` counts the bytes of every POINTED-AT name in
# every .ypt in the game: 3,844,444 characters over 1,240 files, and the set is EXACTLY these 65
# printable characters with ZERO non-printable bytes.
NAME_BYTES_MEASURED = frozenset(bytes(
    b'()/0123456789ABCDEFGHIJKLMNOPRSTUVWXYZ_abcdefghijklmnopqrstuvwxyz'))
# ⛔ AND ONE DELIBERATE WIDENING, DECLARED RATHER THAN SLIPPED IN. `scr_kh_prep.ypt` (3 copies)
# stores an UNREFERENCED name `scr_kh_prep_panel_sparks_smoke	` - the same name it stores again,
# correctly, 32 bytes later. A stray TAB in Rockstar's own build data. 0x09 is witnessed ZERO
# times in a referenced name, so it is not part of the measured class; it is admitted here because
# the byte exists and has to come back, and the cost of admitting it is bounded and stated: it
# converts 3 files / 93 bytes from refused to claimed and nothing else in the population changes.
# MEASURED BOTH WAYS at population rather than asserted: with the widening 1,240/1,240 files are
# byte-exact; with the measured-65 class alone, 3 files miss by 93 bytes and nothing else moves.
# 27 claimed runs game-wide contain the byte, counted as
# `notes['packed_run_outside_measured_class']`, so the next agent can see how load-bearing this is
# instead of trusting this comment.
NAME_BYTES = NAME_BYTES_MEASURED | frozenset({0x09})
KINDNAME = {0: 'ZERO', VALUE: 'VALUE', DERIVED: 'DERIVED', CARRIED: 'CARRIED'}

# --------------------------------------------------------------------------- vtables
# ⭐⭐ ONE ANCHOR PER FILE, AND EVERY OTHER VTABLE IS DERIVED FROM THE DECODED CLASS.
#
# THE FIRST ATTEMPT SHIPPED ABSOLUTE VTABLES AND THAT WAS WRONG - measured, not argued.
# `tools/ypt_vtable_census.py` over all 1,240 .ypt reported EVERY ONE of 43 classes carrying TWO
# distinct vtables, which reads as "the discriminator is broken" and is not: **the game ships .ypt
# built against TWO DIFFERENT EXECUTABLE IMAGES**, and the whole vtable block moves together.
#     ptxFxList vtable @sys+0x00 : 0x140603968 in 1,068 files | 0x140601948 in 172 files
#     constant delta 0x2020; the 172 are base-game x64d.rpf/ptfx.rpf plus two DLC packs.
# An absolute table would have been silently wrong for 13.9% of the lane.
#
# SO THE TABLE IS RELATIVE. The root object sits at sys+0x00, so its vtable is readable with no
# decoding at all and serves as the file's build anchor; every other class is anchor + a FIXED
# offset. Measured constant over the population: 42 of 43 classes, 1,092,000+ objects, BOTH
# builds - including 807,561 ptxKeyframeProp and 236,392 shadervar:Vector2.
#
# ⭐ WHY THIS IS THE TIGHTEST TEST IN THE FILE: the writer emits these 8 bytes FROM THE CLASS IT
# DECIDED THE OBJECT IS. Mis-read a behaviour's type hash, a ptxDomain's DomainType or a
# shadervar's Type u32 and the wrong offset is added and the round-trip REFUSES the file. Three of
# these class families are polymorphic and have no other discriminator, so this is not bookkeeping.
VTABLE_REL = {
    'ptxFxList':               0x00000,     # the anchor itself
    'pgDict:EffectRule':       0x00028,
    'pgDict:EmitterRule':      0x00050,
    'pgDict:ParticleRule':     0x00078,
    'pgDict:Drawable':         0x000A0,
    'pgDict:Texture':         -0x8A3B0,     # grcore, not the ptfx module - hence the sign
    'beh:Acceleration':        0x04A00,
    'beh:Age':                 0x04B70,
    'beh:AnimateTexture':      0x04E80,
    'beh:Attractor':           0x05000,
    'beh:Collision':           0x05320,
    'beh:Colour':              0x056B0,
    'beh:Dampening':           0x05950,
    'beh:MatrixWeight':        0x05B50,
    'beh:Noise':               0x05E60,
    'beh:Rotation':            0x06500,
    'beh:Size':                0x06830,
    'beh:Velocity':            0x069E0,
    'beh:Wind':                0x06C90,
    'beh:Sprite':              0x07070,
    'beh:Model':               0x07250,
    'beh:Trail':               0x07580,
    'beh:Decal':               0x1DE40,
    'beh:DecalPool':           0x1E040,
    'beh:FogVolume':           0x1E510,
    'beh:Light':               0x1EC70,
    'beh:Liquid':              0x1EFB0,
    'beh:River':               0x1F100,
    'beh:ZCull':               0x1F2F0,
    'domain:0':                0x09FC8,     # Box
    'domain:1':                0x0A000,     # Sphere
    'domain:2':                0x0A038,     # Cylinder
    'domain:3':                0x0A070,     # Attractor
    'ptxEffectRule':           0x083B0,
    'ptxEmitterRule':          0x08B30,
    'ptxParticleRule':         0x09160,
    'ptxKeyframeProp':         0x09228,
    'shadervar:Keyframe':      0x0C080,
    'shadervar:Vector2':       0x0C0F0,
    'shadervar:Vector4':       0x0C0F0,     # one class, two Type values - measured, not assumed
    'shadervar:Texture':       0x0C1A0,
    'ptxEventEmitter':         0x0CEF0,
}
# ⛔ `grcTexture` IS THE ONE CLASS WHOSE OFFSET FROM THE ANCHOR IS NOT UNIVERSAL - it relocates
# independently of the ptfx module, so it needs a per-BUILD entry keyed by the anchor itself.
# 1,069 instances at +0x15D00 and 223 at +0x15C20, split exactly along the two builds. An anchor
# this table does not know falls through to per-file LEARNING and is COUNTED, never guessed.
VTABLE_REL_BY_ANCHOR = {
    'grcTexture': {0x0000000140603968: 0x15D00, 0x0000000140601948: 0x15C20},
}

# --------------------------------------------------------------------------- field maps
# name -> (declared object size, ((offset, struct code, label), ...)).
# A label starting 'unk' is an UNNAMED slot: decoded and re-encoded at a declared width, but with
# no semantic derived for it. Counted separately in the byte account so the split is never hidden.
MAPS = {
    'ptxFxList': (0x60, (
        (0x00, '<Q', 'vtable'),
        (0x08, '<Q', 'blockmap*'),
        (0x10, '<Q', 'Name*'),
        (0x20, '<Q', 'TextureDictionary*'),
        (0x30, '<Q', 'DrawableDictionary*'),
        (0x38, '<Q', 'ParticleRuleDictionary*'),
        (0x48, '<Q', 'EffectRuleDictionary*'),
        (0x50, '<Q', 'EmitterRuleDictionary*'),
    )),
    'pgDictionary': (0x40, (
        (0x00, '<Q', 'vtable'),
        (0x08, '<Q', 'blockmap*'),
        (0x18, '<I', 'unk18'),
        (0x20, '<Q', 'hashArray*'),
        (0x28, '<H', 'hashCount'), (0x2A, '<H', 'hashCapacity'),
        (0x30, '<Q', 'objArray*'),
        (0x38, '<H', 'objCount'), (0x3A, '<H', 'objCapacity'),
    )),
    'ptxKeyframeProp': (0x90, (
        (0x00, '<Q', 'vtable'),
        (0x68, '<I', 'nameHash'),
        (0x6C, '<B', 'InvertBiasLink'),
        (0x6D, '<H', 'RandomIndex'),
        (0x70, '<Q', 'keyframes*'),
        (0x78, '<H', 'kfCount'), (0x7A, '<H', 'kfCapacity'),
    )),
    'ptxEffectRule': (0x3B0, (
        (0x00, '<Q', 'vtable'),
        (0x10, '<I', 'RefCount'),
        (0x18, '<f', 'FileVersion'),
        (0x20, '<Q', 'Name*'),
        (0x28, '<I', 'unk28'),
        (0x30, '<I', 'unk30'), (0x34, '<I', 'unk34'),
        (0x38, '<Q', 'EventEmitters*'),
        (0x40, '<H', 'eeCount'), (0x42, '<H', 'eeCapacity'),
        (0x48, '<Q', 'EvolutionList*'),
        (0x50, '<I', 'NumLoops'),
        (0x54, '<B', 'SortEventsByDistance'), (0x55, '<B', 'DrawListID'),
        (0x56, '<B', 'IsShortLived'), (0x57, '<B', 'HasNoShadows'),
        (0x58, '<4f', 'VRandomOffsetPos'),
        (0x68, '<2f', 'unk68'),
        (0x70, '<f', 'PreUpdateTime'), (0x74, '<f', 'PreUpdateTimeInterval'),
        (0x78, '<f', 'DurationMin'), (0x7C, '<f', 'DurationMax'),
        (0x80, '<f', 'PlaybackRateScalarMin'), (0x84, '<f', 'PlaybackRateScalarMax'),
        (0x88, '<8B', 'cullingFlags'),
        (0x90, '<4f', 'ViewportCullingSphereOffset'),
        (0xA0, '<f', 'ViewportCullingSphereRadius'), (0xA4, '<f', 'DistanceCullingFadeDist'),
        (0xA8, '<f', 'DistanceCullingCullDist'), (0xAC, '<f', 'LodEvoDistanceMin'),
        (0xB0, '<f', 'LodEvoDistanceMax'), (0xB4, '<f', 'CollisionRange'),
        (0xB8, '<f', 'CollisionProbeDistance'),
        (0xBC, '<4B', 'collisionFlags'),
        # 0xC0 .. 0x390 = five embedded ptxKeyframeProp at 0xC0 + i*0x90
        (0x390, '<Q', 'KeyframeProps*'),
        (0x398, '<H', 'kfpCount'), (0x39A, '<H', 'kfpCapacity'),
        (0x3A0, '<B', 'ColourTintMaxEnable'), (0x3A1, '<B', 'UseDataVolume'),
        (0x3A2, '<B', 'DataVolumeType'),
        (0x3A8, '<f', 'ZoomLevel'),
    )),
    'ptxEmitterRule': (0x630, (
        (0x00, '<Q', 'vtable'),
        (0x10, '<I', 'RefCount'),
        (0x18, '<I', 'unk18'),
        (0x20, '<Q', 'Name*'),
        (0x38, '<Q', 'CreationDomain*'),
        (0x48, '<Q', 'TargetDomain*'),
        (0x58, '<Q', 'AttractorDomain*'),
        # 0x78 .. 0x618 = ten embedded ptxKeyframeProp at 0x78 + i*0x90
        (0x618, '<Q', 'KeyframeProps*'),
        (0x620, '<H', 'kfpCount'), (0x622, '<H', 'kfpCapacity'),
        (0x628, '<B', 'IsOneShot'),
    )),
    'ptxDomain': (0x270, (
        (0x00, '<Q', 'vtable'),
        (0x08, '<I', 'unk08'),
        (0x0C, '<I', 'DomainType'),
        (0x10, '<B', 'IsWorldSpace'), (0x11, '<B', 'IsPointRelative'),
        (0x12, '<B', 'IsCreationRelative'), (0x13, '<B', 'IsTargetRelatve'),
        # 0x18 .. 0x258 = four embedded ptxKeyframeProp at 0x18 + i*0x90
        (0x258, '<f', 'FileVersion'),
        (0x260, '<Q', 'KeyframeProps*'),
        (0x268, '<H', 'kfpCount'), (0x26A, '<H', 'kfpCapacity'),
    )),
    'ptxEventEmitter': (0x70, (
        (0x00, '<Q', 'vtable'),
        (0x08, '<I', 'unk08'),
        (0x10, '<f', 'StartRatio'), (0x14, '<f', 'EndRatio'),
        (0x18, '<Q', 'EvolutionList*'),
        (0x30, '<Q', 'EmitterRuleName*'),
        (0x38, '<Q', 'ParticleRuleName*'),
        (0x40, '<Q', 'EmitterRule*'),
        (0x48, '<Q', 'ParticleRule*'),
        (0x50, '<f', 'PlaybackRateScalarMin'), (0x54, '<f', 'PlaybackRateScalarMax'),
        (0x58, '<f', 'ZoomScalarMin'), (0x5C, '<f', 'ZoomScalarMax'),
        (0x60, '<I', 'ColourTintMin'), (0x64, '<I', 'ColourTintMax'),
    )),
    'ptxEvolutionList': (0x40, (
        (0x00, '<Q', 'Evolutions*'),
        (0x08, '<H', 'evCount'), (0x0A, '<H', 'evCapacity'),
        (0x10, '<Q', 'EvolvedKeyframeProps*'),
        (0x18, '<H', 'ekCount'), (0x1A, '<H', 'ekCapacity'),
        (0x20, '<Q', 'unk20'),
        (0x28, '<Q', 'SortedIndex*'),
        (0x30, '<H', 'siCount'), (0x32, '<H', 'siCapacity'),
        (0x38, '<Q', 'unk38'),
    )),
    'ptxEvolution': (0x18, (
        (0x00, '<Q', 'Name*'),
        (0x08, '<I', 'unk08'), (0x0C, '<I', 'unk0C'),
        (0x10, '<I', 'unk10'), (0x14, '<I', 'unk14'),
    )),
    'ptxEvolvedKFP': (0x18, (
        (0x00, '<Q', 'Items*'),
        (0x08, '<H', 'itemCount'), (0x0A, '<H', 'itemCapacity'),
        (0x10, '<I', 'nameHash'), (0x14, '<I', 'BlendMode'),
    )),
    'ptxEvolvedItem': (0x30, (
        (0x00, '<Q', 'keyframes*'),
        (0x08, '<H', 'kfCount'), (0x0A, '<H', 'kfCapacity'),
        (0x10, '<Q', 'unk10'),
        (0x18, '<Q', 'unk18'),
        (0x20, '<I', 'EvolutionID'), (0x24, '<I', 'IsLodEvolution'),
        (0x28, '<Q', 'unk28'),
    )),
    'ptxBiasLink': (0x58, (
        (0x00, '<64s', 'Name'),
        (0x40, '<Q', 'KeyframePropIDs*'),
        (0x48, '<H', 'idCount'), (0x4A, '<H', 'idCapacity'),
        (0x50, '<I', 'RandomIndex'), (0x54, '<I', 'unk54'),
    )),
    'ptxDrawableEntry': (0x30, (
        (0x00, '<f', 'BoundBoxWidth'), (0x04, '<f', 'BoundBoxHeight'),
        (0x08, '<f', 'BoundBoxDepth'), (0x0C, '<f', 'BoundingSphereRadius'),
        (0x10, '<Q', 'Name*'),
        (0x18, '<Q', 'Drawable*'),
        (0x20, '<I', 'nameHash'), (0x24, '<I', 'unk24'),
        (0x28, '<Q', 'unk28'),
    )),
    'ptxShaderVar': (0x40, (
        (0x00, '<Q', 'vtable'),
        (0x08, '<Q', 'unk08'),
        (0x10, '<I', 'nameHash'), (0x14, '<I', 'Type'),
        (0x18, '<I', 'ShaderVarID'), (0x1C, '<I', 'IsKeyframeable'),
        (0x20, '<Q', 'unk20'),
    )),
    'ptxParticleRule': (0x230, (
        (0x00, '<Q', 'vtable'),
        (0x10, '<I', 'RefCount'),
        (0x18, '<I', 'unk18'),
        (0x20, '<I', 'unk20'), (0x24, '<I', 'unk24'),
        (0x28, '<I', 'unk28'), (0x2C, '<I', 'unk2C'),
        (0x30, '<I', 'unk30'), (0x34, '<I', 'unk34'),
        # EffectSpawnerAtRatio: min block 0x38, max block 0x58, name* 0x80, tail 0x88
        (0x38, '<f', 'AtRatio.DurationScalarMin'), (0x3C, '<f', 'AtRatio.PlaybackRateScalarMin'),
        (0x40, '<I', 'AtRatio.ColourTintScalarMin'), (0x44, '<f', 'AtRatio.ZoomScalarMin'),
        (0x48, '<I', 'AtRatio.FlagsMin'), (0x4C, '<I', 'AtRatio.unk4C'),
        (0x50, '<Q', 'AtRatio.unk50'),
        (0x58, '<f', 'AtRatio.DurationScalarMax'), (0x5C, '<f', 'AtRatio.PlaybackRateScalarMax'),
        (0x60, '<I', 'AtRatio.ColourTintScalarMax'), (0x64, '<f', 'AtRatio.ZoomScalarMax'),
        (0x68, '<I', 'AtRatio.FlagsMax'), (0x6C, '<I', 'AtRatio.unk6C'),
        (0x70, '<Q', 'AtRatio.unk70'), (0x78, '<Q', 'AtRatio.unk78'),
        (0x80, '<Q', 'AtRatio.EffectRuleName*'),
        (0x88, '<f', 'AtRatio.TriggerInfo'),
        (0x8C, '<B', 'AtRatio.InheritsPointLife'), (0x8D, '<B', 'AtRatio.TracksPointPos'),
        (0x8E, '<B', 'AtRatio.TracksPointDir'), (0x8F, '<B', 'AtRatio.TracksPointNegDir'),
        (0x90, '<Q', 'AtRatio.unk90'), (0x98, '<Q', 'AtRatio.unk98'),
        (0xA0, '<Q', 'AtRatio.unkA0'),
        # EffectSpawnerOnCollision: min 0xA8, max 0xC8, name* 0xF0, tail 0xF8
        (0xA8, '<f', 'OnColl.DurationScalarMin'), (0xAC, '<f', 'OnColl.PlaybackRateScalarMin'),
        (0xB0, '<I', 'OnColl.ColourTintScalarMin'), (0xB4, '<f', 'OnColl.ZoomScalarMin'),
        (0xB8, '<I', 'OnColl.FlagsMin'), (0xBC, '<I', 'OnColl.unkBC'),
        (0xC0, '<Q', 'OnColl.unkC0'),
        (0xC8, '<f', 'OnColl.DurationScalarMax'), (0xCC, '<f', 'OnColl.PlaybackRateScalarMax'),
        (0xD0, '<I', 'OnColl.ColourTintScalarMax'), (0xD4, '<f', 'OnColl.ZoomScalarMax'),
        (0xD8, '<I', 'OnColl.FlagsMax'), (0xDC, '<I', 'OnColl.unkDC'),
        (0xE0, '<Q', 'OnColl.unkE0'), (0xE8, '<Q', 'OnColl.unkE8'),
        (0xF0, '<Q', 'OnColl.EffectRuleName*'),
        (0xF8, '<f', 'OnColl.TriggerInfo'),
        (0xFC, '<B', 'OnColl.InheritsPointLife'), (0xFD, '<B', 'OnColl.TracksPointPos'),
        (0xFE, '<B', 'OnColl.TracksPointDir'), (0xFF, '<B', 'OnColl.TracksPointNegDir'),
        (0x100, '<I', 'CullMode'), (0x104, '<I', 'BlendSet'), (0x108, '<I', 'LightingMode'),
        (0x10C, '<B', 'DepthWrite'), (0x10D, '<B', 'DepthTest'), (0x10E, '<B', 'AlphaBlend'),
        (0x10F, '<B', 'unk10F'),
        (0x110, '<I', 'unk110'), (0x114, '<I', 'unk114'),
        (0x118, '<I', 'TexFrameIDMin'), (0x11C, '<I', 'TexFrameIDMax'),
        (0x120, '<Q', 'Name*'),
        (0x128, '<Q', 'AllBehaviours*'),
        (0x130, '<H', 'behCount'), (0x132, '<H', 'behCapacity'),
        (0x138, '<Q', 'BehList1*'), (0x140, '<H', 'bl1Count'), (0x142, '<H', 'bl1Capacity'),
        (0x148, '<Q', 'BehList2*'), (0x150, '<H', 'bl2Count'), (0x152, '<H', 'bl2Capacity'),
        (0x158, '<Q', 'BehList3*'), (0x160, '<H', 'bl3Count'), (0x162, '<H', 'bl3Capacity'),
        (0x168, '<Q', 'BehList4*'), (0x170, '<H', 'bl4Count'), (0x172, '<H', 'bl4Capacity'),
        (0x188, '<Q', 'BiasLinks*'), (0x190, '<H', 'blCount'), (0x192, '<H', 'blCapacity'),
        (0x1B0, '<I', 'unk1B0'), (0x1B4, '<I', 'unk1B4'),
        (0x1B8, '<Q', 'ShaderFile*'),
        (0x1C0, '<Q', 'ShaderTechnique*'),
        (0x1D0, '<I', 'ShaderTemplateTechniqueID'), (0x1D4, '<I', 'unk1D4'),
        (0x1D8, '<I', 'unk1D8'), (0x1DC, '<I', 'unk1DC'),
        (0x1E0, '<I', 'DiffuseMode'), (0x1E4, '<I', 'ProjectionMode'),
        (0x1E8, '<B', 'IsLit'), (0x1E9, '<B', 'IsSoft'), (0x1EA, '<B', 'IsScreenSpace'),
        (0x1EB, '<B', 'IsRefract'), (0x1EC, '<B', 'IsNormalSpec'), (0x1ED, '<B', 'unk1ED'),
        (0x1F0, '<Q', 'ShaderVars*'), (0x1F8, '<H', 'svCount'), (0x1FA, '<H', 'svCapacity'),
        (0x200, '<I', 'unk200'), (0x204, '<I', 'unk204'),
        (0x208, '<Q', 'DrawableHashes*'),
        (0x210, '<Q', 'Drawables*'), (0x218, '<H', 'drwCount'), (0x21A, '<H', 'drwCapacity'),
        (0x220, '<B', 'SortType'), (0x221, '<B', 'DrawType'),
    )),
}

# Behaviour classes: type name -> (object size, extra tail fields). Every behaviour shares the
# head (vtable, typeHash, the KeyframeProps pointer array) and carries `nkfp` embedded
# ptxKeyframeProp at 0x30 + i*0x90; the tail begins right after them. `nkfp` is NOT declared here
# - it is taken from `ypt2xml.BEH_SPEC`, so the writer and the reader cannot drift apart.
BEH_HEAD = (
    (0x00, '<Q', 'vtable'),
    (0x08, '<I', 'typeHash'), (0x0C, '<I', 'unk0C'),
    (0x10, '<Q', 'KeyframeProps*'),
    (0x18, '<H', 'kfpCount'), (0x1A, '<H', 'kfpCapacity'),
)


def _kfp_count(t):
    return sum(1 for f in ypt2xml.BEH_SPEC.get(t, ()) if f[0] == 'kfp')


def _check_maps():
    """⛔ Refuse at import if a declared field map overlaps itself or overruns its object size.

    Same instrument as `yvr_write._check_tiling`, adapted to a format whose classes are NOT
    densely tiled (a RAGE class has genuine internal padding, and claiming it would be inventing
    content). The demand here is NO OVERLAP and NO OVERRUN; the padding claim is then tested AT
    POPULATION by `Ypt.interior_nonzero()`, which counts every unclaimed byte INSIDE a claimed
    object extent that is not zero. A map that quietly skipped a live field shows up there rather
    than as mystery coverage.
    """
    for name, (size, fields) in MAPS.items():
        seen = bytearray(size)
        for off, code, label in fields:
            n = struct.calcsize(code)
            if off < 0 or off + n > size:
                raise ValueError('%s: field %s 0x%X+%d runs past size 0x%X'
                                 % (name, label, off, n, size))
            for k in range(off, off + n):
                if seen[k]:
                    raise ValueError('%s: field map overlaps at 0x%X (%s)' % (name, k, label))
                seen[k] = 1


_check_maps()


class Ypt:
    """The value model. Walks the object graph, claiming every byte it can rebuild."""

    def __init__(self, res, flags=(0, 0)):
        if res.version != YPT_VERSION:
            raise ValueError('ypt expects RSC7 version %d, got %d' % (YPT_VERSION, res.version))
        self.res = res
        self.sys_flags, self.gfx_flags = flags
        self.b = res.sys
        self.g = res.gfx
        self.nsys, self.ngfx = len(res.sys), len(res.gfx)
        self.size = self.nsys
        self.claims = []          # (offset, bytes, kind, label)   system segment
        self.gclaims = []         # (offset, bytes, kind, label)   graphics segment
        self.extents = []         # (offset, size, class)          for interior_nonzero()
        self.vt_mismatch = 0
        self.notes = {}
        self._strings = set()
        self._drawable_claims = []   # (offset, bytes, seg) - applied LAST, and only to gaps
        self._vt_learn = {}       # class -> vtable learned from this file's first instance
        # THE BUILD ANCHOR: the root object's own vtable. Read once, before the walk, because
        # every other vtable in the file is DERIVED from it (see `vtable`).
        self._anchor = struct.unpack_from('<Q', res.sys, 0)[0] if len(res.sys) >= 8 else 0
        self.mutate = None        # set by the must-fail control; see _mut()
        self._walk()

    # ------------------------------------------------------------------ primitive readers
    def _u8(self, o):  return self.b[o]

    def _u16(self, o): return struct.unpack_from('<H', self.b, o)[0]

    def _u32(self, o): return struct.unpack_from('<I', self.b, o)[0]

    def _u64(self, o): return struct.unpack_from('<Q', self.b, o)[0]

    def _deref(self, o):
        if o + 4 > self.nsys:
            return None
        t = self._u32(o)
        return (t & 0x0FFFFFFF) if (t >> 28) == 5 else None

    def _note(self, k, n=1):
        self.notes[k] = self.notes.get(k, 0) + n

    # ------------------------------------------------------------------ claim helpers
    def _mut(self, data, label):
        """THE MUST-FAIL CONTROL HOOK. `self.mutate` is (predicate, transform); when it fires the
        emitted bytes are corrupted, and the harness DEMANDS the written image change. A control
        that cannot fire proves nothing, so `ypt_control.py` counts firings, not just outcomes."""
        m = self.mutate
        if m is not None and m[0](label, data):
            return m[1](data)
        return data

    def put(self, off, data, kind=VALUE, label='?'):
        if off is None or not data or off < 0 or off + len(data) > self.nsys:
            return
        self.claims.append((off, self._mut(data, label), kind, label))

    def putg(self, off, data, kind=CARRIED, label='?'):
        if off is None or not data or off < 0 or off + len(data) > self.ngfx:
            return
        self.gclaims.append((off, self._mut(data, label), kind, label))

    def copy(self, off, n, label='blob'):
        if off is None or n <= 0 or off + n > self.nsys:
            return
        self.put(off, bytes(self.b[off:off + n]), CARRIED, label)

    def obj(self, base, cls, extra=()):
        """Re-encode every declared field of a class from its DECODED value - never a slice copy.
        Registers the object's extent so `interior_nonzero()` can test the padding claim."""
        size, fields = MAPS[cls]
        self._emit_fields(base, fields, cls)
        if extra:
            self._emit_fields(base, extra, cls)
        self.extents.append((base, size, cls))
        return size

    def _emit_fields(self, base, fields, cls=''):
        """⭐ LABELS ARE CLASS-QUALIFIED, and that is not cosmetics. `unk20` exists in both
        `ptxShaderVar` and `ptxEvolutionList`; with bare labels the field-drop control checked
        "does any claim called unk20 hold data?", found the evolution list's, and then reported
        the shadervar's all-zero slot as a MISSED catch on 60 of 212 drops. A label that names two
        different fields makes every per-field measurement wrong in a direction nobody can see."""
        for off, code, raw in fields:
            # ⛔⛔ THE SKIP IS TESTED ON THE RAW LABEL, BEFORE QUALIFYING - and getting that
            # backwards for one revision is the sharpest lesson in this file. Qualifying first
            # made the guard `label == 'vtable'` never true, so `_emit_fields` re-emitted every
            # vtable as a VERBATIM VALUE COPY on top of the DERIVED claim `vtable()` had just
            # written. The lane stayed at 1,240/1,240 and 100.000000% throughout: the copy
            # reproduces the same bytes, so BYTE IDENTITY CANNOT SEE THE DIFFERENCE between the
            # strongest claim in the writer and a memcpy of it. Only the must-fail control saw
            # it - `derived_vtable` fell from 100.000% to 1.667%. This is the whole reason the
            # control exists.
            if raw == 'vtable':
                continue                        # written by vtable(), from the class
            label = (cls + '.' + raw) if cls else raw
            o = base + off
            n = struct.calcsize(code)
            if o < 0 or o + n > self.nsys:
                continue
            enc = struct.pack(code, *struct.unpack_from(code, self.b, o))
            if enc != self.b[o:o + n]:
                # ⛔ THE VALUE DID NOT SURVIVE ITS OWN TYPE, so claiming it as a decoded value
                # would be a lie the round-trip could not catch. The only cause measured in this
                # lane is a SIGNALLING NaN in a float32 slot: CPython quiets 0x7F800001 to
                # 0x7FC00001 on repack, so the stored payload cannot pass through a Python float.
                # The bytes are emitted verbatim and COUNTED as carried rather than dressed up.
                self._note('bits_not_representable:' + label)
                self.put(o, bytes(self.b[o:o + n]), CARRIED, label + '.bits')
                continue
            self.put(o, enc, VALUE, label)

    def vtable(self, base, cls, table=None):
        """⭐ WRITTEN FROM THE CLASS THE WALKER DECIDED, NOT COPIED - anchor + the class's fixed
        offset. A wrong discriminator adds the wrong offset, writes 8 wrong bytes, and the
        round-trip REFUSES the file.

        The ANCHOR is the root object's own vtable at sys+0x00. It is the one vtable in the file
        that cannot be derived from anything else - it IS the build identity - so it is CARRIED,
        8 bytes per file, and labelled as such. Everything else is DERIVED from it.
        A class this table does not know is LEARNED per file (first instance carried, the rest
        derived) so the writer still works on a build nobody has measured, and every learn is
        COUNTED in `notes` rather than passing silently.
        """
        if base + 8 > self.nsys:
            return
        got = self._u64(base)
        anchor = self._anchor
        if cls == 'ptxFxList':
            self.put(base, struct.pack('<Q', anchor), CARRIED, 'vtable.anchor')
            return
        rel = VTABLE_REL.get(cls)
        if rel is None:
            per = VTABLE_REL_BY_ANCHOR.get(cls)
            if per is not None:
                rel = per.get(anchor)
                if rel is None:
                    self._note('vtable_anchor_unknown:' + str(cls))
        if rel is None:
            want = self._vt_learn.get(cls)
            if want is None:
                self._vt_learn[cls] = got
                self._note('vtable_learned:' + str(cls))
                self.put(base, struct.pack('<Q', got), CARRIED, 'vtable.learn')
                return
        else:
            want = (anchor + rel) & 0xFFFFFFFFFFFFFFFF
        if got != want:
            self.vt_mismatch += 1
            self._note('vtable_mismatch:' + str(cls))
        self.put(base, struct.pack('<Q', want), DERIVED, 'vtable')

    def cstr(self, ptr_off):
        """Claim a NUL-terminated string INCLUDING its terminator, and no further. Claiming a
        fixed span here would swallow whatever follows, which on a packed string table is the
        NEXT name - the fill-to-the-next-region failure in miniature."""
        o = self._deref(ptr_off)
        if o is None or o in self._strings:
            return
        end = self.b.find(b'\x00', o)
        if end < 0 or end >= self.nsys:
            return
        self._strings.add(o)
        self.put(o, bytes(self.b[o:end + 1]), VALUE, 'string')

    def ptr_array(self, desc_off, count, label):
        """A tagged-pointer array: `count` 64-bit slots, each re-encoded from its decoded value."""
        base = self._deref(desc_off)
        if base is None or count <= 0:
            return None
        for i in range(count):
            o = base + i * 8
            if o + 8 > self.nsys:
                break
            self.put(o, struct.pack('<Q', self._u64(o)), VALUE, label)
        self.extents.append((base, count * 8, label))
        return base

    def u32_array(self, desc_off, count, label):
        base = self._deref(desc_off)
        if base is None or count <= 0:
            return None
        for i in range(count):
            o = base + i * 4
            if o + 4 > self.nsys:
                break
            self.put(o, struct.pack('<I', self._u32(o)), VALUE, label)
        self.extents.append((base, count * 4, label))
        return base

    # ------------------------------------------------------------------ the walk
    def _walk(self):
        self.vtable(0x00, 'ptxFxList')
        self.obj(0x00, 'ptxFxList')
        self.cstr(0x10)
        self._dict(0x48, 'EffectRule', self._effect_rule)
        self._dict(0x50, 'EmitterRule', self._emitter_rule)
        self._dict(0x38, 'ParticleRule', self._particle_rule)
        self._dict(0x30, 'Drawable', self._drawable)
        self._texture_dict(0x20)
        self._apply_drawable()
        self._packed_names()

    def _apply_drawable(self):
        """Emit the embedded drawable's verbatim spans ONLY where the typed model claimed nothing.
        See `_drawable` for why this runs last and what it cost when it did not."""
        if not self._drawable_claims:
            return
        taken = bytearray(self.nsys)
        for off, data, _k, _l in self.claims:
            taken[off:off + len(data)] = b'' * len(data)
        gtaken = bytearray(self.ngfx)
        for off, data, _k, _l in self.gclaims:
            gtaken[off:off + len(data)] = b'' * len(data)
        for off, data, seg in self._drawable_claims:
            mark = taken if seg == 'sys' else gtaken
            lim = self.nsys if seg == 'sys' else self.ngfx
            i = 0
            n = len(data)
            while i < n:
                if off + i >= lim or mark[off + i]:
                    i += 1
                    continue
                j = i
                while j < n and off + j < lim and not mark[off + j]:
                    j += 1
                run = data[i:j]
                if seg == 'sys':
                    self.put(off + i, run, CARRIED, 'drawable')
                else:
                    self.putg(off + i, run, CARRIED, 'drawable.gfx')
                mark[off + i:off + j] = b'' * (j - i)
                i = j

    def _packed_names(self):
        """⭐ THE NAME TABLE IS PACKED, AND UNREFERENCED ENTRIES SIT INSIDE IT.

        Measured on the population: a .ypt name table stores NUL-terminated names back to back,
        and a minority of entries have NO POINTER ANYWHERE IN THE FILE - 28 of 362 in
        `scr_apartment_mp`, 2 of 28 in `weap_revolver`. Every one of them is the name of a real
        rule, so they are data, not padding, and a writer that leaves them zero cannot close the
        lane. `ytd_write._source_paths` hit the same shape and drew the transferable lesson:
        "nothing points at it" ends the search for an OWNER and says nothing about whether the
        content can be PINNED.

        ⛔⛔ AND HERE IS THE PIN, WHICH IS THE ONLY REASON THIS IS ALLOWED TO CLAIM ANYTHING.
        A gap between two REFERENCED names (whose offsets came from pointers, independently of
        this rule) must be EXACTLY TILED by whole NUL-terminated strings: start at the previous
        name's terminator + 1, read runs, and the last one must end precisely one byte before the
        next referenced name. If the tiling overshoots, undershoots, or meets a non-printable
        byte, THE GAP IS REFUSED AND LEFT ZERO - counted in `notes` as `packed_gap_refused`. So a
        wrong packing law does not quietly copy bytes into place, it fails and shows up as
        missing coverage. That is the difference between evidence and a self-fulfilling claim.

        ⚠ ONLY INTERIOR GAPS ARE ELIGIBLE. A run of unreferenced names AFTER the last referenced
        one has no closing landmark, so nothing could reject a wrong claim there and it is left
        alone; `packed_tail_unclaimed` counts what that costs.
        """
        claimed = bytearray(self.nsys)
        for off, data, _k, _l in self.claims:
            claimed[off:off + len(data)] = b'\1' * len(data)
        i = 0
        while i < self.nsys:
            if claimed[i]:
                i += 1
                continue
            h0 = i
            while i < self.nsys and not claimed[i]:
                i += 1
            self._tile_hole(h0, i)

    def _tile_hole(self, h0, h1):
        """THE TILING TEST, applied to ONE hole left by the typed walk.

        ⛔ IT RUNS ON HOLES, NOT ON GAPS BETWEEN STRINGS, and that is a correction that mattered:
        the first version measured the gap between two referenced NAMES and refused 86 of 172
        because a claimed structure - an AllBehaviours pointer array - sat in the middle of the
        gap and its pointer bytes are not name characters. A rule that cannot tell "I do not
        understand this" from "someone else already owns this" refuses the wrong things.

        A hole passes only if EVERY non-zero byte in it belongs to a NUL-terminated run drawn from
        the RAGE name character class. One byte outside that and the WHOLE hole is refused and
        left zero, counted as `packed_hole_refused`. So the rule can fail, and when it fails it
        costs coverage instead of quietly copying bytes into place.
        """
        if h1 - h0 < 2:
            return
        runs = []
        o = h0
        while o < h1:
            c = self.b[o]
            if c == 0:
                o += 1
                continue
            if c not in NAME_BYTES:
                self._note('packed_hole_refused')
                self._note('packed_hole_refused_bytes', h1 - h0)
                return
            e = o
            while e < h1 and self.b[e] != 0 and self.b[e] in NAME_BYTES:
                e += 1
            if e >= h1 or self.b[e] != 0:
                self._note('packed_hole_refused')
                self._note('packed_hole_refused_bytes', h1 - h0)
                return
            runs.append((o, e))
            o = e + 1
        if not runs:
            return
        self._note('packed_hole_tiled')
        for o, e in runs:
            self._strings.add(o)
            if any(c not in NAME_BYTES_MEASURED for c in self.b[o:e]):
                self._note('packed_run_outside_measured_class')
            self.put(o, bytes(self.b[o:e + 1]), VALUE, 'string.packed')

    def _dict(self, root_off, kind, item_fn):
        base = self._deref(root_off)
        if base is None:
            return
        self.vtable(base, 'pgDict:' + kind)
        self.obj(base, 'pgDictionary')
        n = self._u16(base + 0x38)
        self.u32_array(base + 0x20, self._u16(base + 0x28), 'dictHash')
        arr = self.ptr_array(base + 0x30, n, 'dictObj')
        if arr is None:
            return
        for i in range(n):
            o = self._deref(arr + i * 8)
            if o is not None:
                item_fn(o)

    # -- ptxKeyframeProp ------------------------------------------------
    def _kfp(self, base):
        self.vtable(base, 'ptxKeyframeProp')
        self.obj(base, 'ptxKeyframeProp')
        cnt = self._u16(base + 0x78)
        cap = self._u16(base + 0x7A)
        self._keyframes(base + 0x70, max(cnt, cap))

    def _keyframes(self, desc_off, n):
        """A bare keyframe array: 8 float32 per element (Time.xyzw, Value.xyzw), stride 32.
        ⭐ THE STRIDE IS PINNED HERE, not assumed: element i is written at base + i*32, so a
        wrong stride mis-places every element after the first and the round-trip refuses it."""
        base = self._deref(desc_off)
        if base is None or n <= 0:
            return
        for i in range(n):
            o = base + i * 32
            if o + 32 > self.nsys:
                break
            self.put(o, struct.pack('<8f', *struct.unpack_from('<8f', self.b, o)),
                     VALUE, 'keyframe')
        self.extents.append((base, n * 32, 'keyframes'))

    # -- ptxEffectRule --------------------------------------------------
    def _effect_rule(self, base):
        self.vtable(base, 'ptxEffectRule')
        self.obj(base, 'ptxEffectRule')
        self.cstr(base + 0x20)
        for i in range(5):
            self._kfp(base + 0xC0 + i * 0x90)
        self.ptr_array(base + 0x390, self._u16(base + 0x398), 'kfpPtr')
        ee = self.ptr_array(base + 0x38, self._u16(base + 0x40), 'eePtr')
        if ee is not None:
            for i in range(self._u16(base + 0x40)):
                o = self._deref(ee + i * 8)
                if o is not None:
                    self._event_emitter(o)
        el = self._deref(base + 0x48)
        if el is not None:
            self._evolution_list(el)

    def _event_emitter(self, base):
        self.vtable(base, 'ptxEventEmitter')
        self.obj(base, 'ptxEventEmitter')
        self.cstr(base + 0x30)
        self.cstr(base + 0x38)
        el = self._deref(base + 0x18)
        if el is not None:
            self._evolution_list(el)

    def _evolution_list(self, base):
        self.obj(base, 'ptxEvolutionList')
        n = self._u16(base + 0x08)
        ev = self._deref(base + 0x00)
        if ev is not None:
            for i in range(n):
                self.obj(ev + i * 0x18, 'ptxEvolution')
                self.cstr(ev + i * 0x18)
            self.extents.append((ev, n * 0x18, 'evolutions'))
        m = self._u16(base + 0x18)
        ek = self._deref(base + 0x10)
        if ek is not None:
            for i in range(m):
                eo = ek + i * 0x18
                self.obj(eo, 'ptxEvolvedKFP')
                ic = self._u16(eo + 0x08)
                io = self._deref(eo + 0x00)
                if io is None:
                    continue
                for j in range(ic):
                    it = io + j * 0x30
                    self.obj(it, 'ptxEvolvedItem')
                    self._keyframes(it + 0x00, max(self._u16(it + 0x08), self._u16(it + 0x0A)))
                self.extents.append((io, ic * 0x30, 'evolvedItems'))
            self.extents.append((ek, m * 0x18, 'evolvedKFPs'))
        self._sorted_index(base, ek, m)

    def _sorted_index(self, base, ek, m):
        """⛔ THE `+0x28` INDEX IS AN ARRAY OF {hash, POINTER}, NOT A HASH ARRAY. `ypt2xml` calls
        it "a redundant hash-sorted index (228/228 lists verified) - never emitted", and never
        emitting it is exactly why its SHAPE was never tested: read as u32 hashes it round-trips
        the first quarter of every element and leaves the pointer behind. Element = 16 bytes:
            +0x00 u32 joaat(name)   +0x04 pad   +0x08 u64 -> the EvolvedKeyframeProps ELEMENT

        ⭐ AND THE POINTER IS DERIVED, NOT COPIED. Each entry addresses element j of the
        EvolvedKeyframeProps array, so the writer recomputes it as `ekBase + j*0x18` from the
        decoded index. A wrong array base or a wrong 0x18 stride therefore writes a wrong pointer
        and the round-trip refuses it - which is the property a claim needs to be evidence.
        An entry that does not land on an element boundary is COUNTED and written from its value
        rather than silently derived.
        """
        n = self._u16(base + 0x30)
        arr = self._deref(base + 0x28)
        if arr is None or n <= 0:
            return
        for i in range(n):
            e = arr + i * 0x10
            if e + 16 > self.nsys:
                break
            self.put(e, struct.pack('<I', self._u32(e)), VALUE, 'siHash')
            self.put(e + 4, struct.pack('<I', self._u32(e + 4)), VALUE, 'siPad')
            t = self._deref(e + 8)
            if t is not None and ek is not None and m and ek <= t < ek + m * 0x18 \
                    and (t - ek) % 0x18 == 0:
                j = (t - ek) // 0x18
                self.put(e + 8, struct.pack('<Q', 0x50000000 | (ek + j * 0x18)),
                         DERIVED, 'siTarget')
            else:
                self._note('sorted_index_target_off_element')
                self.put(e + 8, struct.pack('<Q', self._u64(e + 8)), VALUE, 'siTarget')
        self.extents.append((arr, n * 0x10, 'evSortedIndex'))

    # -- ptxEmitterRule -------------------------------------------------
    def _emitter_rule(self, base):
        self.vtable(base, 'ptxEmitterRule')
        self.obj(base, 'ptxEmitterRule')
        self.cstr(base + 0x20)
        for i in range(10):
            self._kfp(base + 0x78 + i * 0x90)
        self.ptr_array(base + 0x618, self._u16(base + 0x620), 'kfpPtr')
        for off in (0x38, 0x48, 0x58):
            d = self._deref(base + off)
            if d is not None:
                self._domain(d)

    def _domain(self, base):
        """⭐ ptxDomain IS POLYMORPHIC and its vtable is the DomainType discriminator - four
        classes behind one pointer. Writing the vtable from the DECODED DomainType is therefore
        a real test: mis-read the type u32 and eight bytes go wrong."""
        dt = self._u32(base + 0x0C)
        self.vtable(base, 'domain:%d' % dt)
        self.obj(base, 'ptxDomain')
        for i in range(4):
            self._kfp(base + 0x18 + i * 0x90)
        self.ptr_array(base + 0x260, self._u16(base + 0x268), 'kfpPtr')

    # -- ptxParticleRule ------------------------------------------------
    def _particle_rule(self, base):
        self.vtable(base, 'ptxParticleRule')
        self.obj(base, 'ptxParticleRule')
        self.cstr(base + 0x120)
        self.cstr(base + 0x80)
        self.cstr(base + 0xF0)
        self.cstr(base + 0x1B8)
        self.cstr(base + 0x1C0)
        nb = self._u16(base + 0x130)
        ab = self.ptr_array(base + 0x128, nb, 'behPtr')
        if ab is not None:
            for i in range(nb):
                o = self._deref(ab + i * 8)
                if o is not None:
                    self._behaviour(o)
        # The four categorised behaviour sub-lists: pointer arrays into the SAME behaviour
        # objects the AllBehaviours array owns. Modelled as pointer arrays, not walked twice.
        for p, c in ((0x138, 0x140), (0x148, 0x150), (0x158, 0x160), (0x168, 0x170)):
            self.ptr_array(base + p, self._u16(base + c), 'behListPtr')
        ns = self._u16(base + 0x1F8)
        sv = self.ptr_array(base + 0x1F0, ns, 'svPtr')
        if sv is not None:
            for i in range(ns):
                o = self._deref(sv + i * 8)
                if o is not None:
                    self._shadervar(o)
        self._bias_links(base)
        self._drawable_entries(base)

    def _behaviour(self, base):
        th = self._u32(base + 0x08)
        t = ypt2xml.BEH_TYPEHASH.get(th)
        if t is None:
            self._note('behaviour_type_unknown:0x%08X' % th)
            self.vtable(base, 'beh:0x%08X' % th)
            self._emit_fields(base, BEH_HEAD, 'beh:?')
            return
        self.vtable(base, 'beh:' + t)
        self._emit_fields(base, BEH_HEAD, 'beh:' + t)
        nk = _kfp_count(t)
        for i in range(nk):
            self._kfp(base + 0x30 + i * 0x90)
        tail = 0x30 + nk * 0x90
        size, fields = BEH_TAIL.get(t, (tail, ()))
        self._emit_fields(base, fields, 'beh:' + t)
        self.ptr_array(base + 0x10, self._u16(base + 0x18), 'kfpPtr')
        self.extents.append((base, size, 'beh:' + t))

    def _shadervar(self, base):
        """⭐ POLYMORPHIC, and the union at +0x28 is discriminated by the Type u32 at +0x14.
        Reading the type wrong writes the wrong vtable AND the wrong union shape."""
        ty = self._u32(base + 0x14)
        name = ypt2xml.SV_TYPE.get(ty)
        self.vtable(base, 'shadervar:' + (name or '0x%X' % ty))
        self.obj(base, 'ptxShaderVar')
        if name in ('Vector2', 'Vector4'):
            self._emit_fields(base, SV_VECTOR, 'ptxShaderVar')
        elif name == 'Texture':
            self._emit_fields(base, SV_TEXTURE, 'ptxShaderVar')
            self.cstr(base + 0x30)
        elif name == 'Keyframe':
            self._emit_fields(base, SV_KEYFRAME, 'ptxShaderVar')
            n = max(self._u16(base + 0x30), self._u16(base + 0x32))
            o = self._deref(base + 0x28)
            if o is not None:
                for i in range(n):
                    e = o + i * 0x20
                    if e + 0x20 > self.nsys:
                        break
                    self.put(e, struct.pack('<8f', *struct.unpack_from('<8f', self.b, e)),
                             VALUE, 'svKeyframe')
                self.extents.append((o, n * 0x20, 'svKeyframes'))
        else:
            self._note('shadervar_type_unknown:0x%X' % ty)

    def _bias_links(self, base):
        n = self._u16(base + 0x190)
        arr = self._deref(base + 0x188)
        if arr is None or n <= 0:
            return
        for i in range(n):
            e = arr + i * 0x58
            self.obj(e, 'ptxBiasLink')
            self.u32_array(e + 0x40, self._u16(e + 0x48), 'kfpIDs')
        self.extents.append((arr, n * 0x58, 'biasLinks'))

    def _drawable_entries(self, base):
        n = self._u16(base + 0x218)
        arr = self._deref(base + 0x210)
        if arr is None or n <= 0:
            return
        for i in range(n):
            e = arr + i * 0x30
            self.obj(e, 'ptxDrawableEntry')
            self.cstr(e + 0x10)
        self.extents.append((arr, n * 0x30, 'drawableEntries'))
        self.u32_array(base + 0x208, n, 'drawableHashes')

    # -- the two embedded dictionaries ----------------------------------
    def _drawable(self, base):
        """A gtaDrawable inside the root DrawableDictionary.

        ⛔ `ypt2xml.drawable_dict` states "single non-empty witness = wpn_amrifle". REFUTED at a
        sample of twelve: `scr_apartment_mp.ypt` carries one too, and the population count is
        reported by `tools/ypt_population.py` rather than asserted here.

        A drawable is `ydr_write`'s subject, not this file's, so this delegates to that model
        rather than growing a second, weaker copy of it - and EVERY BYTE IT CONTRIBUTES IS
        ACCOUNTED **CARRIED**, because `ydr_write` captures verbatim spans (its own header:
        "Every capture is a VERBATIM COPY of the source, so ANY byte claimed trivially
        reproduces"). Calling that a model would be exactly the dressing-up the byte account
        exists to prevent, so the drawable's share is reported separately and never folded into
        the VALUE figure.
        """
        self._note('drawable_object')
        try:
            import ydr_write
        except Exception:
            self._note('drawable_ydr_write_unavailable')
            return
        try:
            d = ydr_write.Ydr.__new__(ydr_write.Ydr)
            d.res = self.res
            d.sys_flags, d.gfx_flags = self.sys_flags, self.gfx_flags
            d.nsys, d.ngfx = self.nsys, self.ngfx
            d.sysr, d.gfxr = [], []
            d._seen = set()
            d._defer = []
            d._bounds = []
            d._polyclaim = {}
            d._bonecounts = []
            # ⛔⛔ THE TYPED WALK ONLY. `ydr_write` follows `_drawable` with `_polytail`,
            # `_buildgrid` and `_flush_chase` - and `_flush_chase` is a BLIND POINTER CHASE that
            # captures a fixed window behind every tagged pointer it can find. Run here it does
            # not stay inside the drawable: measured on 14 files it claimed 1,557,712 of
            # 1,818,624 system bytes (85.7%) and took this lane's reported coverage to 99.9982%
            # while three name-table gaps this writer had REFUSED to claim were quietly filled
            # underneath it. That is precisely the failure the byte account exists to catch - the
            # image copies the original bytes at whatever offsets a writer claims, so an unpinned
            # window is self-fulfilling and the round-trip cannot reject it. The typed walk stays;
            # the blind one is not allowed to lend this lane a number it did not earn.
            d._drawable(base)
        except Exception as ex:
            self._note('drawable_walk_failed:' + type(ex).__name__)
            return
        # ⛔ DEFERRED, NOT EMITTED HERE. `ydr_write` captures FIXED SPANS (DRAWABLE_SPAN, 0x180,
        # 0x90 ...) that overrun the structures they describe, and emitted in walk order they
        # LANDED ON TOP OF this writer's typed claims: measured over the population, 924,046 bytes
        # were double-claimed, 100,384 of them over `svPtr`, 68,792 over derived vtables. A byte
        # served by a verbatim copy is a byte whose typed claim is never tested - and the
        # must-fail control proved it, reporting `derived_vtable MISSED` and `class_mislabel
        # MISSED` on exactly the files with a drawable. So the drawable's spans are applied at the
        # END and ONLY WHERE NOTHING ELSE CLAIMED, which keeps the typed model the authority and
        # keeps CARRIED honest about how much ground it actually holds.
        for off, data in d.sysr:
            self._drawable_claims.append((off, data, 'sys'))
        for off, data in d.gfxr:
            self._drawable_claims.append((off, data, 'gfx'))

    def _texture_dict(self, root_off):
        """The embedded grcTextureDictionary. The records are decoded to typed fields; the PIXEL
        SPANS in the graphics segment are CARRIED and accounted as such - decoding a BC-compressed
        texel block is not what this measure is about, and calling a copy a model would be the
        exact thing the byte account exists to prevent."""
        base = self._deref(root_off)
        if base is None:
            return
        self.vtable(base, 'pgDict:Texture')
        self.obj(base, 'pgDictionary')
        n = self._u16(base + 0x38)
        self.u32_array(base + 0x20, self._u16(base + 0x28), 'texHash')
        arr = self.ptr_array(base + 0x30, n, 'texPtr')
        if arr is None:
            return
        for i in range(n):
            o = self._deref(arr + i * 8)
            if o is None:
                continue
            self._texture(o)

    def _texture(self, base):
        self.vtable(base, 'grcTexture')
        self._emit_fields(base, TEXTURE_MAP, 'grcTexture')
        self.extents.append((base, 0x90, 'grcTexture'))
        self.cstr(base + 0x28)
        # pixel data: a tagged pointer into the GRAPHICS segment
        t = self._u32(base + 0x70)
        if (t >> 28) != 6:
            return
        off = t & 0x0FFFFFFF
        n = self._mip_bytes(base)
        if n and off + n <= self.ngfx:
            self.putg(off, bytes(self.g[off:off + n]), CARRIED, 'pixels')
        elif off < self.ngfx:
            self._note('texture_pixel_span_unknown')

    def _mip_bytes(self, base):
        """Stored mip-chain length, computed from the record - there is no stored length.
        Delegates to `ytd_write.stored_mipchain_bytes`, the rule that closed the 88,880-file
        `.ytd` lane, rather than re-deriving a second version of the same law here."""
        try:
            import ytd_write
            import ytd2xml
        except Exception:
            return 0
        w = self._u16(base + 0x50)
        h = self._u16(base + 0x52)
        stride = self._u16(base + 0x56)
        mips = self.b[base + 0x5D]
        fmt = self._u32(base + 0x58)
        try:
            _x, blk, bpp = ytd2xml.describe_format(fmt)
            return ytd_write.stored_mipchain_bytes(w, h, mips, blk, bpp, stride)
        except Exception:
            self._note('texture_format_undescribed:0x%X' % fmt)
            return 0

    # ------------------------------------------------------------------ output
    def write(self):
        si, gi = bytearray(self.nsys), bytearray(self.ngfx)
        for off, data, _k, _l in self.claims:
            si[off:off + len(data)] = data
        for off, data, _k, _l in self.gclaims:
            gi[off:off + len(data)] = data
        # ⭐ THE PAGE-COUNT RECORD, COMPUTED - never carried. `ptr@0x08` reaches a small record
        # whose u32 at +8 is pageCount(system) | pageCount(graphics) << 8. The law was derived on
        # META, holds on 259 ynd and 9,145 yvr/ywr, and holds here. Recomputing rather than
        # copying is what makes this byte meaningful: a carried value would round-trip even if we
        # had no idea what it meant.
        try:
            buf, o = self.res.deref(self.res.ptr(0x08), 16)
            if buf is not None and o + 12 <= len(si):
                val = ((meta_write.page_count(self.sys_flags) & 0xFF)
                       | ((meta_write.page_count(self.gfx_flags) & 0xFF) << 8))
                si[o + 8:o + 12] = struct.pack('<I', val)
        except Exception:
            pass                       # leave it zero rather than guess - a gap must stay VISIBLE
        return bytes(si), bytes(gi)

    def kindmap(self):
        """Per-byte provenance of the written image: 0 ZERO / 1 VALUE / 2 DERIVED / 3 CARRIED."""
        ks, kg = bytearray(self.nsys), bytearray(self.ngfx)
        for off, data, k, _l in self.claims:
            ks[off:off + len(data)] = bytes([k]) * len(data)
        for off, data, k, _l in self.gclaims:
            kg[off:off + len(data)] = bytes([k]) * len(data)
        try:
            buf, o = self.res.deref(self.res.ptr(0x08), 16)
            if buf is not None and o + 12 <= len(ks):
                ks[o + 8:o + 12] = bytes([DERIVED]) * 4
        except Exception:
            pass
        return bytes(ks), bytes(kg)

    def regions(self):
        """(value, derived, zero_fill, carried) byte split of the reproduced image.

        ⭐ DISCLOSURE, NOT DECORATION. Byte identity alone cannot tell a rebuilt region from a
        copied one, and this vault's law is that a claimed region is evidence ONLY IF A WRONG
        CLAIM COULD HAVE BEEN REJECTED. `carried` is the part of a passing file that could not
        have failed on its own content; quote it next to the 100.0000% figure, never instead.

        ⛔ THE DENOMINATOR IS BOTH SEGMENTS, so the number is LARGE and that is the correct
        answer. `write()` produces (system, graphics) and this counts every byte of both:
            value + derived + zero_fill + carried == len(sys image) + len(gfx image)
        The graphics segment is ~49% of this lane's bytes and it is ~81% CARRIED, because it is
        the embedded TEXTURE PIXELS - a BC-compressed texel block is not what this measure is
        about. So the COMBINED carried figure is dominated by pixels, not by the effect graph.
        The system segment - where the rmPtfx object model actually lives - reads 1.86% carried
        over all bytes / 5.11% over its non-zero bytes (population figures, module header).
        Per-segment splits are available from `kindmap()`, which this is the summary of.

        WHERE THE CARRIED BYTES COME FROM, all of them labelled at the claim site:
          `pixels`        - texture mip chains in the graphics segment (the bulk)
          `drawable`      - `ydr_write`'s verbatim spans for an embedded gtaDrawable, applied
                            only where the typed model claimed nothing (see `_apply_drawable`)
          `vtable.anchor` - 8 B/file, the build identity; nothing else in the file derives it
          `vtable.learn`  - first instance of a class this build's table does not know
          `*.bits`        - a value that did not survive its own type (signalling NaN), emitted
                            verbatim rather than dressed up as a decoded value
        """
        ks, kg = self.kindmap()
        value = ks.count(VALUE) + kg.count(VALUE)
        derived = ks.count(DERIVED) + kg.count(DERIVED)
        carried = ks.count(CARRIED) + kg.count(CARRIED)
        # Everything the model never claimed stays zero in the written image. It is only CORRECT
        # where the original is zero too - `unreached()` is what tests that, not this split.
        zero_fill = ks.count(0) + kg.count(0)
        return (value, derived, zero_fill, carried)

    @staticmethod
    def _same(a, b):
        n = min(len(a), len(b))
        if not n:
            return 0
        x = int.from_bytes(a[:n], 'little') ^ int.from_bytes(b[:n], 'little')
        return x.to_bytes(n, 'little').count(0)

    def coverage(self):
        gs, gg = self.write()
        ns = self._same(gs, self.res.sys)
        ng = self._same(gg, self.res.gfx) if self.ngfx else 0
        tot = self.nsys + self.ngfx
        return (100.0 * (ns + ng) / tot if tot else 0.0,
                100.0 * ns / self.nsys if self.nsys else 0.0,
                100.0 * ng / self.ngfx if self.ngfx else None)

    def unreached(self):
        gs, gg = self.write()
        bad = (self.nsys - self._same(gs, self.res.sys)) + (self.ngfx - self._same(gg, self.res.gfx))
        return bad

    def interior_nonzero(self):
        """Bytes INSIDE a claimed object extent that the field map never claimed and that are not
        zero in the original - i.e. live data a declared map is silently skipping. Zero here is
        what turns 'the map has gaps' into 'the map's gaps are padding'."""
        ks, _kg = self.kindmap()
        marked = bytearray(self.nsys)
        for off, size, _c in self.extents:
            if off is None or size <= 0 or off >= self.nsys:
                continue
            end = min(off + size, self.nsys)
            marked[off:end] = b'\1' * (end - off)
        n = 0
        for i in range(self.nsys):
            if marked[i] and not ks[i] and self.b[i]:
                n += 1
        return n


# --------------------------------------------------------------------------- behaviour tails
# ⭐ SIZE PER BEHAVIOUR CLASS. Measured, not assumed: for the five classes that carry NO embedded
# KeyframeProps the size is the gap from the object base to the next allocation in the file
# (Age/Velocity 0x30, Model 0x40, Sprite 0x70 - all read straight off the population), and for the
# rest it is the end of the embedded KFP block (0x30 + nkfp*0x90) plus the class's own scalar tail,
# 16-byte aligned. `interior_nonzero()` tests every one of them at population: a size set too
# small leaves live bytes unowned, a tail map with a hole leaves them unclaimed inside the extent.
BEH_SIZE = {
    'Age': 0x30, 'Velocity': 0x30, 'Model': 0x40, 'River': 0x40, 'Sprite': 0x70,
    'DecalPool': 0x50, 'Liquid': 0x50, 'MatrixWeight': 0xD0, 'Attractor': 0xC0,
    'AnimateTexture': 0xD0, 'Wind': 0xF0, 'Trail': 0xF0,
    'Acceleration': 0x160, 'Dampening': 0x160, 'Collision': 0x160, 'ZCull': 0x160,
    'Decal': 0x180, 'Colour': 0x1F0, 'Size': 0x280, 'Rotation': 0x280, 'Noise': 0x280,
    'FogVolume': 0x430, 'Light': 0x550,
}

# struct code per `ypt2xml.BEH_SPEC` scalar kind. The reader's WIDTH is honoured so the two
# cannot drift: if the reader calls a slot a byte, the writer writes a byte there.
_SPEC_CODE = {'byte': '<B', 'u32': '<I', 'i32': '<i', 'f32': '<f'}


def _beh_tail(t):
    """Build one behaviour's tail field map: the offsets `ypt2xml.BEH_SPEC` PINNED, plus a dense
    fill of every remaining byte between the embedded KFP block and the class size.

    ⭐ THE DENSE FILL IS THE POINT, not a shortcut. The reader's own KNOWN LIMITATION section says
    a handful of behaviour scalars "are const across the 10-file oracle set and are emitted as the
    observed literal (they never varied, so no offset could be pinned)" - Trail Tessellation,
    Collision RadiusMult/RestSpeed and friends. A reader may guess a constant; a WRITER may not,
    because the byte has to come back. So every unpinned byte of the tail becomes a declared
    `unk` slot and is reproduced from the file rather than from an oracle's habits, and the byte
    account reports named-vs-unnamed so the guesswork is visible instead of dressed up.
    """
    size = BEH_SIZE.get(t)
    if size is None:
        return None
    start = 0x30 + _kfp_count(t) * 0x90
    named = {}
    for f in ypt2xml.BEH_SPEC.get(t, ()):
        if f[0] == 'vec3':
            named[f[2]] = ('<3f', f[1])
        elif f[0] == 'scalar' and f[2][0] == 'off':
            named[f[2][1]] = (_SPEC_CODE[f[2][2]], f[1])
    out = []
    o = start
    while o < size:
        if o in named:
            code, label = named[o]
            out.append((o, code, label))
            o += struct.calcsize(code)
            continue
        nxt = min([k for k in named if k > o] + [size])
        room = nxt - o
        if room >= 4 and o % 4 == 0:
            out.append((o, '<I', 'unk%03X' % o))
            o += 4
        elif room >= 2 and o % 2 == 0:
            out.append((o, '<H', 'unk%03X' % o))
            o += 2
        else:
            out.append((o, '<B', 'unk%03X' % o))
            o += 1
    return (size, tuple(out))


def _check_beh_sizes():
    """⛔ A DECLARED SIZE THAT IS TOO LARGE IS A CLAIM ON SOMEBODY ELSE'S BYTES, and byte identity
    cannot see it: the overrun copies the same values the real owner would have written, so the
    round-trip agrees and the model is still wrong. Found by auditing OVERLAPPING CLAIMS at
    population - `beh:Attractor` was declared 0xD0 with an empty scalar tail, so 16 bytes of every
    instance reached into the following keyframe array and the evolution sorted index (1,760
    bytes over 6 files, 0 of them disagreeing, which is exactly why nothing else caught it).
    A class with no tail fields must end where its embedded KeyframeProps end.
    """
    for t, size in BEH_SIZE.items():
        start = 0x30 + _kfp_count(t) * 0x90
        ends = [0]
        for f in ypt2xml.BEH_SPEC.get(t, ()):
            if f[0] == 'vec3':
                ends.append(f[2] + 12)
            elif f[0] == 'scalar' and f[2][0] == 'off':
                ends.append(f[2][1] + struct.calcsize(_SPEC_CODE[f[2][2]]))
        need = max(start, max(ends))
        if size < need:
            raise ValueError('beh:%s size 0x%X is smaller than its own fields (0x%X)'
                             % (t, size, need))
        if size - need >= 16:
            raise ValueError('beh:%s size 0x%X overshoots its last field (0x%X) by >= 16 bytes '
                             '- that is a claim on the next allocation' % (t, size, need))


_check_beh_sizes()

BEH_TAIL = {}
for _t in set(ypt2xml.BEH_TYPEHASH.values()):
    _m = _beh_tail(_t)
    if _m is not None:
        BEH_TAIL[_t] = _m
        MAPS['beh:' + _t] = (_m[0], tuple(BEH_HEAD) + _m[1])
_check_maps()

SV_VECTOR = ((0x28, '<Q', 'unk28'), (0x30, '<4f', 'Vector'))
SV_TEXTURE = ((0x28, '<Q', 'unk28'), (0x30, '<Q', 'TextureName*'),
              (0x38, '<I', 'unk38'), (0x3C, '<I', 'ExternalReference'))
SV_KEYFRAME = ((0x28, '<Q', 'Items*'), (0x30, '<H', 'itemCount'), (0x32, '<H', 'itemCapacity'),
               (0x38, '<Q', 'unk38'))

# grcTexture, 0x90 - the same record `ytd_write` models; the offsets are not re-derived here.
TEXTURE_MAP = (
    (0x00, '<Q', 'vtable'), (0x08, '<Q', 'unk08'), (0x10, '<Q', 'unk10'), (0x18, '<Q', 'unk18'),
    (0x20, '<Q', 'unk20'), (0x28, '<Q', 'Name*'), (0x30, '<Q', 'unk30'), (0x38, '<Q', 'unk38'),
    (0x40, '<I', 'usage'), (0x44, '<I', 'usageFlags'), (0x48, '<Q', 'unk48'),
    (0x50, '<H', 'width'), (0x52, '<H', 'height'), (0x54, '<H', 'depth'), (0x56, '<H', 'stride'),
    (0x58, '<I', 'format'), (0x5C, '<B', 'unk5C'), (0x5D, '<B', 'mips'),
    (0x5E, '<B', 'unk5E'), (0x5F, '<B', 'unk5F'),
    (0x60, '<Q', 'unk60'), (0x68, '<Q', 'unk68'), (0x70, '<Q', 'pixels*'),
    (0x78, '<Q', 'unk78'), (0x80, '<Q', 'unk80'), (0x88, '<Q', 'unk88'),
)


def read_ypt(src):
    """bytes | path -> Ypt. The RSC7 segment FLAGS are parsed here because `Res` does not keep
    them and the page-count record cannot be recomputed without them."""
    blob = bytes(src) if isinstance(src, (bytes, bytearray)) else open(src, 'rb').read()
    _magic, _ver, sysf, gfxf = struct.unpack_from('<4sIII', blob, 0)
    return Ypt(Res.from_bytes(blob), (sysf, gfxf))
