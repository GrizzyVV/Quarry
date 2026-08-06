"""rel2xml - binary GTA V ``.rel`` (RAGE audio relationship / audio-config data) -> RAGE
interchange ``.rel.xml``.

CLEAN-ROOM: every offset, every field name and every field TYPE below was pinned by
value-intersecting the ONE oracle export (_Oracles/rel/00_base/dlcbeach_game.dat149.rel.xml)
against its game binary, then structurally re-checked against the other 39 .rel binaries this
install ships in 00_base/10_update.  No any third-party tool / RAGE source consulted, no web research of
the reference exporter or RAGE internals, nothing from _QUARANTINE_PRE_PLAN.

Reuses: joaat / fmt_num / esc from meta2xml (the proven hash + float-text + escape laws).

================================  CONTAINER LAYOUT  ================================
A .rel is FLAT - no RSC7 container, no compression, no encryption.  All little-endian.

  off      size      field
  0x00     u32       RelIdent          the "NNN" in <name>.datNNN.rel; also the XML root
                                       tag ("Dat149").  MEASURED over 40 files: always
                                       equals the filename's dat number.
  0x04     u32       DataLength        bytes of the data block that follows
  0x08     DataLength  DATA BLOCK      item offsets in the index are RELATIVE TO 0x08.
                                       Its first 4 bytes (data offset 0..3) are the
                                       VERSION stamp <Version value="..."/>; no item is
                                       ever placed there - the first item starts at
                                       data offset 4.
  0x08+DL  u32       NameTableLength   byte length of the name-table block below,
                                       INCLUDING its own count+offset words
           u32       NameTableCount    number of strings (0 for every dat149)
           u32[N]    NameTableOffsets  byte offsets into the string blob
           char[]    string blob       NUL-terminated (bank paths in a sounds.dat54;
                                       EMPTY in every game.dat149)
           u32       ItemCount
           {u32 NameHash, u32 Offset, u32 Length}[ItemCount]      the ITEM INDEX
           u32       ListACount ; u32[ListACount]     data offsets, purpose UNPINNED
           u32       ListBCount ; u32[ListBCount]     "            (0 in the oracle)
  (that consumes the file EXACTLY - verified on all 40 binaries)

ITEM RECORD (at DATA offset `Offset`, `Length` bytes INCLUDING this header):
  +0x00    u8        Type              the type tag (3, 4, 17, 76, 88 ... below)
  +0x01    u24       NameTableOffset   emitted verbatim as the XML `ntOffset` attribute.
                                       In a game.dat149 the name table is EMPTY, so this
                                       indexes a table that was stripped at build time -
                                       it is a preserved field, NOT a name source.
  +0x04    payload   fixed-size, per-type field list (below)

The XML lists items in ASCENDING DATA-OFFSET order (the file's index order is different -
measured: index order != offset order, and the oracle follows offset order).

An item's NAME comes from reversing its index NameHash (joaat, lowercase).  The hash
dictionary is an EXTERNAL input - the strings are in neither the .rel nor GTA5.exe
(grepped: "bifta", "null_sound", "ptl_sns", "_scanner_params" all absent from the exe).
`oracle_rel_audio_names.json` beside this file carries the 18 strings the oracle itself
spells; each is joaat-verified at import, same rule as oracle_ped_audio_names.json.

===============================  TYPE TAG -> SCHEMA  ===============================
  3   CarAudioSettings              256 B  (79 XML fields, 68 stored at this version)
  4   VehicleEngineAudioSettings    232 B  (57 XML fields, all stored)
  17  WeaponAudioSettings           144 B  (36 XML fields, 35 stored - `Version` is
                                            version-gated OUT and renders as 0)
  76  ScannerVehicleParams          variable: Flags, u32 count, count x 4 hashes
  88  GranularEngineAudioSettings   236 B  (60 XML fields, 58 stored)
Verified across the whole dat149 corpus: every type-3 item is exactly 256 B, every type-4
232 B, every type-17 144 B, every type-88 236 B, and every type-76 satisfies
4 + 4 + 4 + 16*count == Length (14/14).  Fixed-size records, no per-item variation.

Field kinds:  flags -> value="0x%08X" | int -> value="%d" (signed) | float -> value=fmt_num
              hash  -> element TEXT: resolved name, else "hash_%08X", else EMPTY when 0.
A field marked storage "-" is VERSION-GATED OUT at version 0x0050E44B: it consumes no
bytes and renders as its zero form.  (Proof it is gating and not truncation:
WeaponAudioSettings.Version sits in the MIDDLE of the field list, not at the end - and the
same file's dat150 sibling stores 13 more weapon fields and 1 more car field in items that
are 52 B / 4 B longer.)

======================  WRITE DIRECTION (authoring your own audio)  ======================
A .rel is the ROUTING layer: it names a thing and points it at other hashes.  For Matt's
"author my own sounds" lane the relevant chain is
      game.dat149  ->  <sound name hash>  ->  sounds.dat54  ->  bank path string
                                                              ->  .awc stream
A MINIMAL AUTHORED game.dat149 needs, and needs nothing else:
  1. header {149, DataLength} + a 4-byte version stamp at data offset 0 (write 0x0050E44B
     to get exactly this schema; a different stamp = a different field set),
  2. one item record per setting: u8 type | u24 ntOffset | fixed payload.  ntOffset may be
     0 for every item when the name table is empty - the game never needs it, the shipped
     files only carry it as build residue,
  3. an EMPTY name table: u32 NameTableLength=4, u32 NameTableCount=0,
  4. the index: u32 count then {joaat(name), dataOffset, length} per item.  THE HASH IS
     THE ONLY NAME THE GAME SEES, so the authored name must be joaat'd exactly as spelled
     (lowercase in every shipped example),
  5. u32 0, u32 0 for the two trailing lists.
Cross-file references (Engine, GranularEngine, ScannerVehicleSettings, FireSound...) are
plain joaat hashes with NO container qualifier, so an authored item can point at a stock
game sound (null_sound = 0xE38FCF16, silence = 0xD0D7570A) or at a sound you define in
your own sounds.dat54 - the .rel format itself does not care which file the target lives
in.  What this module does NOT yet give the write lane: the dat54 (sounds) and dat4
(speech) schemas, and the meaning of the two trailing offset lists (see UNPINNED).

==================================  UNPINNED  ==================================
  * Everything except RelIdent 149 at version 0x0050E44B.  dat150 / dat151 / dat54 / dat4 /
    dat10 / dat15 have no oracle, and dat150 demonstrably stores MORE fields per item, so
    they are REFUSED (RelError), never guessed.
  * dat149 type tags 50, 57, 62, 63, 66 and 90 occur in the corpus but in no oracle ->
    REFUSED, not guessed.
  * int-vs-float for 30 fields the oracle only ever shows as 0 (marked `int0` in the tables):
    both spellings render "0", so parity is unaffected here, but a non-zero value in some
    other file could be mis-spelled.  Six formerly-ambiguous fields WERE pinned to int by a
    census over the dat149 corpus (they carry negative values that are NaN as float):
    IdleMinPitch, InductionMinPitch, InductionMaxPitch, MasterTransmissionVolume,
    DecelVolume_PreSubmix, ShellCasing.
  * The 4th byte of the CarAudioSettings GPSVoice/AmbientRadioVol/RadioLeakage group is
    treated as padding: it is 0 in all 14 corpus items, so "pad" and "a field the reference exporter does not
    emit" are indistinguishable.
  * Signedness of the six u8 fields: every corpus value is <= 14, so u8 vs s8 is untested.
  * The two trailing offset lists (ListA/ListB): empty in the oracle, non-empty in other
    dat149s.  Parsed and length-checked, NOT emitted - whether the reference exporter writes them is unknown.
  * <Params /> rendering for a ScannerVehicleParams with 0 entries: unwitnessed
    (every corpus item has >= 1).
"""
import os, sys, json, struct

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from meta2xml import joaat, fmt_num, esc

REL_IDENT = 149                 # the only .rel family with an oracle
REL_VERSION = 0x0050E44B        # 5301323 - the only version with an oracle


class RelError(Exception):
    """This .rel is outside the measured envelope. Refuse loudly; never guess a field."""


def _spec(text):
    """'Tag kind storage' lines -> [(tag, kind, storage)]. storage: u32 | u8 | u8x2 | -"""
    out = []
    for line in text.strip().splitlines():
        parts = line.split()
        if not parts:
            continue
        out.append((parts[0], parts[1], parts[2]))
    return tuple(out)


_T = {}

_T[3] = ('CarAudioSettings', _spec("""
Flags                                      flags  u32
Engine                                     hash   u32
GranularEngine                             hash   u32
HornSounds                                 hash   u32
DoorOpenSound                              hash   u32
DoorCloseSound                             hash   u32
BootOpenSound                              hash   u32
BootCloseSound                             hash   u32
RollSound                                  hash   u32
BrakeSqueekFactor                          float  u32
SuspensionUp                               hash   u32
SuspensionDown                             hash   u32
MinSuspCompThresh                          float  u32
MaxSuspCompThresh                          float  u32
VehicleCollisions                          hash   u32
CarMake                                    int0   u32
CarModel                                   int0   u32
CarCategory                                int0   u32
ScannerVehicleSettings                     hash   u32
JumpLandSound                              hash   u32
DamagedJumpLandSound                       hash   u32
JumpLandMinThresh                          int    u32
JumpLandMaxThresh                          int    u32
VolumeCategory                             int    u8
GPSType                                    int    u8
RadioType                                  int    u8
RadioGenre                                 int    u8
IndicatorOn                                hash   u32
IndicatorOff                               hash   u32
Handbrake                                  hash   u32
GPSVoice                                   int    u8
AmbientRadioVol                            int    u8
RadioLeakage                               int    u8x2
ParkingTone                                hash   u32
RoofStuckSound                             hash   u32
FreewayPassbyTyreBumpFront                 hash   u32
FreewayPassbyTyreBumpBack                  hash   u32
FireAudio                                  hash   u32
StartupRevs                                hash   u32
WindNoise                                  hash   u32
FreewayPassbyTyreBumpFrontSide             hash   u32
FreewayPassbyTyreBumpBackSide              hash   u32
MaxRollOffScalePlayer                      float  u32
MaxRollOffScaleNPC                         float  u32
ConvertibleRoofSoundSet                    hash   u32
OffRoadRumbleSoundVolume                   int0   u32
SirenSounds                                hash   u32
AlternativeGranularEngines                 hash   u32
AlternativeGranularEngineProbability       int0   u32
StopStartProb                              int0   u32
NPCRoadNoise                               hash   u32
NPCRoadNoiseHighway                        hash   u32
ForkliftSounds                             hash   u32
TurretSounds                               hash   u32
ClatterType                                int    u32
DiggerSounds                               hash   u32
TowTruckSounds                             hash   u32
EngineType                                 int0   u32
ElectricEngine                             hash   u32
Openness                                   float  u32
ReverseWarning                             hash   u32
RandomDamage                               int    u32
WindClothSound                             hash   u32
CarSpecificShutdownSound                   hash   u32
ClatterSensitivityScalar                   float  u32
ClatterVolumeBoost                         int0   u32
ChassisStressSensitivityScalar             float  u32
ChassisStressVolumeBoost                   int0   u32
VehicleRainSound                           hash   -
AdditionalRevsIncreaseSmoothing            int0   -
AdditionalRevsDecreaseSmoothing            int0   -
AdditionalGearChangeSmoothing              int0   -
AdditionalGearChangeSmoothingTime          int0   -
ConvertibleRoofInteriorSoundSet            hash   -
VehicleRainSoundInterior                   hash   -
CabinToneLoop                              hash   -
InteriorViewEngineOpenness                 int0   -
JumpLandSoundInterior                      hash   -
DamagedJumpLandSoundInterior               hash   -
"""))

_T[4] = ('VehicleEngineAudioSettings', _spec("""
MasterVolume                               int    u32
MaxConeAttenuation                         int    u32
FXCompensation                             int    u32
NonPlayerFXComp                            int    u32
LowEngineLoop                              hash   u32
HighEngineLoop                             hash   u32
LowExhaustLoop                             hash   u32
HighExhaustLoop                            hash   u32
RevsOffLoop                                hash   u32
MinPitch                                   int    u32
MaxPitch                                   int    u32
IdleEngineSimpleLoop                       hash   u32
IdleExhaustSimpleLoop                      hash   u32
IdleMinPitch                               int    u32
IdleMaxPitch                               int    u32
InductionLoop                              hash   u32
InductionMinPitch                          int    u32
InductionMaxPitch                          int    u32
TurboWhine                                 hash   u32
TurboMinPitch                              int    u32
TurboMaxPitch                              int    u32
DumpValve                                  hash   u32
DumpValveProb                              int    u32
TurboSpinupSpeed                           int    u32
GearTransLoop                              hash   u32
GearTransMinPitch                          int0   u32
GearTransMaxPitch                          int    u32
GTThrottleVol                              int    u32
Ignition                                   hash   u32
EngineShutdown                             hash   u32
CoolingFan                                 hash   u32
ExhaustPops                                hash   u32
StartLoop                                  hash   u32
MasterTurboVolume                          int0   u32
MasterTransmissionVolume                   int    u32
EngineStartUp                              hash   u32
EngineSynthDef                             hash   u32
EngineSynthPreset                          hash   u32
ExhaustSynthDef                            hash   u32
ExhaustSynthPreset                         hash   u32
EngineSubmixVoice                          hash   u32
ExhaustSubmixVoice                         hash   u32
UpgradedTransmissionVolumeBoost            int    u32
UpgradedGearChangeInt                      hash   u32
UpgradedGearChangeExt                      hash   u32
UpgradedEngineVolumeBoost_PostSubmix       int0   u32
UpgradedEngineSynthDef                     int0   u32
UpgradedEngineSynthPreset                  int0   u32
UpgradedExhaustVolumeBoost_PostSubmix      int0   u32
UpgradedExhaustSynthDef                    int0   u32
UpgradedExhaustSynthPreset                 int0   u32
UpgradedDumpValve                          hash   u32
UpgradedTurboVolumeBoost                   int    u32
UpgradedGearTransLoop                      hash   u32
UpgradedTurboWhine                         hash   u32
UpgradedInductionLoop                      hash   u32
UpgradedExhaustPops                        hash   u32
"""))

_T[88] = ('GranularEngineAudioSettings', _spec("""
Flags                                      flags  u32
MasterVolume                               int0   u32
EngineAccel                                hash   u32
ExhaustAccel                               hash   u32
EngineVolume_PreSubmix                     int0   u32
ExhaustVolume_PreSubmix                    int0   u32
AccelVolume_PreSubmix                      int0   u32
DecelVolume_PreSubmix                      int    u32
IdleVolume_PreSubmix                       int0   u32
EngineRevsVolume_PreSubmix                 int0   u32
ExhaustRevsVolume_PreSubmix                int0   u32
EngineThrottleVolume_PreSubmix             int0   u32
ExhaustThrottleVolume_PreSubmix            int0   u32
EngineVolume_PostSubmix                    int    u32
ExhaustVolume_PostSubmix                   int    u32
EngineMaxConeAttenuation                   int    u32
ExhaustMaxConeAttenuation                  int    u32
EngineRevsVolume_PostSubmix                int    u32
ExhaustRevsVolume_PostSubmix               int    u32
EngineThrottleVolume_PostSubmix            int    u32
ExhaustThrottleVolume_PostSubmix           int    u32
GearChangeWobbleLength                     int    u32
GearChangeWobbleLengthVariance             float  u32
GearChangeWobbleSpeed                      float  u32
GearChangeWobbleSpeedVariance              float  u32
GearChangeWobblePitch                      float  u32
GearChangeWobblePitchVariance              float  u32
GearChangeWobbleVolume                     float  u32
GearChangeWobbleVolumeVariance             float  u32
EngineClutchAttenuation_PostSubmix         int    u32
ExhaustClutchAttenuation_PostSubmix        int    u32
EngineSynthDef                             hash   u32
EngineSynthPreset                          hash   u32
ExhaustSynthDef                            hash   u32
ExhaustSynthPreset                         hash   u32
NPCEngineAccel                             hash   u32
NPCExhaustAccel                            hash   u32
RevLimiterPopSound                         hash   u32
MinRPMOverride                             int0   u32
MaxRPMOverride                             int0   u32
EngineSubmixVoice                          hash   u32
ExhaustSubmixVoice                         hash   u32
ExhaustProximityVolume_PostSubmix          int    u32
RevLimiterGrainsToPlay                     int    u32
RevLimiterGrainsToSkip                     int    u32
SynchronisedSynth                          hash   u32
UpgradedEngineVolumeBoost_PostSubmix       int0   u32
UpgradedEngineSynthDef                     hash   u32
UpgradedEngineSynthPreset                  hash   u32
UpgradedExhaustVolumeBoost_PostSubmix      int0   u32
UpgradedExhaustSynthDef                    hash   u32
UpgradedExhaustSynthPreset                 hash   u32
DamageSynthHashList                        hash   u32
UpgradedRevLimiterPop                      hash   u32
EngineIdleVolume_PostSubmix                int    u32
ExhaustIdleVolume_PostSubmix               int    u32
StartupRevsVolumeBoostEngine_PostSubmix    int    u32
StartupRevsVolumeBoostExhaust_PostSubmix   int    u32
RevLimiterApplyType                        int0   -
RevLimiterVolumeCut                        int0   -
"""))

_T[17] = ('WeaponAudioSettings', _spec("""
Flags                                      flags  u32
Version                                    int0   -
FireSound                                  hash   u32
SuppressedFireSound                        hash   u32
AutoSound                                  hash   u32
ReportSound                                hash   u32
ReportVolumeDelta                          float  u32
ReportPredelayDelta                        int    u32
TailEnergyValue                            float  u32
EchoSound                                  hash   u32
SuppressedEchoSound                        hash   u32
ShellCasingSound                           hash   u32
SwipeSound                                 hash   u32
GeneralStrikeSound                         hash   u32
PedStrikeSound                             hash   u32
HeftSound                                  hash   u32
PutDownSound                               hash   u32
RattleSound                                hash   u32
RattleLandSound                            hash   u32
PickupSound                                hash   u32
ShellCasing                                int    u32
SafetyOn                                   hash   u32
SafetyOff                                  hash   u32
SpecialWeaponSoundSet                      hash   u32
BankSound                                  hash   u32
InteriorShotSound                          hash   u32
ReloadSounds                               hash   u32
IntoCoverSound                             hash   u32
OutOfCoverSound                            hash   u32
BulletImpactTimeFilter                     int0   u32
LastBulletImpactTime                       int0   u32
RattleAimSound                             hash   u32
SmallAnimalStrikeSound                     hash   u32
BigAnimalStrikeSound                       hash   u32
SlowMoFireSound                            hash   u32
HitPedSound                                hash   u32
"""))

# type 76 is the one variable-length record in the measured set: Flags, then a counted
# list of 4-hash parameter blocks.
_SCANNER = 'ScannerVehicleParams'
_SCANNER_PARAM = ('Manufacturer', 'Model', 'Category', 'ColorOverride')

_STORE_SIZE = {'u32': 4, 'u8': 1, 'u8x2': 2, '-': 0}


def _overlay():
    """joaat -> string for the audio names the oracle spells but no filename can reverse.

    The mapping is not asserted here - it is PROVEN by the oracle comparison: a wrong
    string hashes to a different key, the real hash then renders "hash_XXXXXXXX", and the
    export stops being byte-identical. What IS checked here is the one failure the oracle
    cannot see: two distinct strings colliding onto one hash, which would make resolution
    depend on file order."""
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     'oracle_rel_audio_names.json')
    out = {}
    if os.path.isfile(p):
        with open(p, encoding='utf-8') as f:
            for n in json.load(f).get('names', []):
                prev = out.setdefault(joaat(n), n)
                if prev != n:
                    raise RelError('oracle_rel_audio_names.json: joaat collision between '
                                   '%r and %r' % (prev, n))
    return out


_OVERLAY = _overlay()


class _Rel(object):
    """The parsed container. Refuses (RelError) rather than half-reading."""

    def __init__(self, blob):
        self.b = blob
        if len(blob) < 20:
            raise RelError('.rel shorter than a header (%d B)' % len(blob))
        self.ident = self.u32(0)
        dl = self.u32(4)
        if 8 + dl > len(blob):
            raise RelError('.rel DataLength %d overruns the file (%d B)' % (dl, len(blob)))
        self.dbase = 8
        self.version = self.u32(8)
        p = 8 + dl
        ntlen = self.u32(p)
        ntbase = p + 4
        if ntlen < 4 or ntbase + ntlen > len(blob):
            raise RelError('.rel name table (len %d @%d) overruns the file' % (ntlen, ntbase))
        self.ntcount = self.u32(ntbase)
        self.ntoffsets = [self.u32(ntbase + 4 + 4 * i) for i in range(self.ntcount)]
        self.strings = blob[ntbase + 4 + 4 * self.ntcount: ntbase + ntlen]
        p = ntbase + ntlen
        n = self.u32(p)
        p += 4
        if p + 12 * n > len(blob):
            raise RelError('.rel item index (%d entries) overruns the file' % n)
        self.index = [struct.unpack_from('<III', blob, p + 12 * i) for i in range(n)]
        p += 12 * n
        # two trailing counted u32 lists; parsed only to prove the file is fully consumed
        self.lista_n = self.u32(p)
        p += 4 + 4 * self.lista_n
        self.listb_n = self.u32(p)
        p += 4 + 4 * self.listb_n
        if p != len(blob):
            raise RelError('.rel trailer did not consume the file exactly '
                           '(stopped at %d of %d)' % (p, len(blob)))

    def u32(self, o):
        if o + 4 > len(self.b):
            raise RelError('.rel read past end at %d' % o)
        return struct.unpack_from('<I', self.b, o)[0]


def _hash_text(h, names):
    if h == 0:
        return None                                   # -> self-closing element
    n = (names or {}).get(h) or _OVERLAY.get(h)
    return n if n else 'hash_%08X' % h


def _field_lines(spec, b, o, limit, names, ind):
    """Emit one item's fields; returns (lines, cursor). `limit` is the item's byte end."""
    L = []
    for tag, kind, store in spec:
        raw = 0
        if store != '-':
            if o + _STORE_SIZE[store] > limit:
                raise RelError('field %s runs past the item record' % tag)
            raw = struct.unpack_from('<I', b, o)[0] if store == 'u32' else b[o]
            o += _STORE_SIZE[store]
        if kind == 'hash':
            t = _hash_text(raw, names)
            L.append('%s<%s />' % (ind, tag) if t is None
                     else '%s<%s>%s</%s>' % (ind, tag, esc(t), tag))
        elif kind == 'flags':
            L.append('%s<%s value="0x%08X" />' % (ind, tag, raw))
        elif kind == 'float':
            f = struct.unpack('<f', struct.pack('<I', raw))[0]
            L.append('%s<%s value="%s" />' % (ind, tag, fmt_num(f)))
        else:                                          # int / int0
            v = struct.unpack('<i', struct.pack('<I', raw))[0] if store in ('u32', '-') else raw
            L.append('%s<%s value="%d" />' % (ind, tag, v))
    return L, o


def _scanner_lines(b, o, limit, names, ind):
    L = ['%s<Flags value="0x%08X" />' % (ind, struct.unpack_from('<I', b, o)[0])]
    o += 4
    n = struct.unpack_from('<I', b, o)[0]
    o += 4
    if o + 16 * n != limit:
        raise RelError('ScannerVehicleParams list (%d entries) does not fill the record' % n)
    if n == 0:
        L.append('%s<Params />' % ind)                 # UNPINNED: unwitnessed
        return L, o
    L.append('%s<Params>' % ind)
    for _ in range(n):
        L.append('%s <Item>' % ind)
        for tag in _SCANNER_PARAM:
            t = _hash_text(struct.unpack_from('<I', b, o)[0], names)
            L.append('%s  <%s />' % (ind, tag) if t is None
                     else '%s  <%s>%s</%s>' % (ind, tag, esc(t), tag))
            o += 4
        L.append('%s </Item>' % ind)
    L.append('%s</Params>' % ind)
    return L, o


def convert(name, blob, names=None, stats=None):
    """binary .rel -> reference-identical .rel.xml text (LF newlines, trailing LF).

    `names`: joaat -> string, the caller's name table (quarry's view-manifest registry);
             the oracle_rel_audio_names.json overlay fills what filenames cannot reverse.
    Raises RelError for any .rel family / version / item type outside the measured
    envelope - a refusal the caller must COUNT, never a guessed export.
    """
    r = _Rel(bytes(blob))
    if r.ident != REL_IDENT or r.version != REL_VERSION:
        raise RelError('unmeasured .rel family: %s is dat%d version 0x%08X; only dat%d '
                       'version 0x%08X has an oracle'
                       % (name, r.ident, r.version, REL_IDENT, REL_VERSION))
    for _h, off, ln in r.index:
        t = r.u32(r.dbase + off) & 0xFF
        if t != 76 and t not in _T:
            raise RelError('unmeasured .rel item type %d in %s' % (t, name))

    L = ['<?xml version="1.0" encoding="UTF-8"?>',
         '<Dat%d>' % r.ident,
         ' <Version value="%d" />' % r.version,
         ' <Items>']
    for h, off, ln in sorted(r.index, key=lambda e: e[1]):
        base = r.dbase + off
        hdr = r.u32(base)
        typ, ntoff = hdr & 0xFF, hdr >> 8
        tname = _SCANNER if typ == 76 else _T[typ][0]
        L.append('  <Item type="%s" ntOffset="%d">' % (tname, ntoff))
        nm = _hash_text(h, names)
        L.append('   <Name />' if nm is None else '   <Name>%s</Name>' % esc(nm))
        if typ == 76:
            body, o = _scanner_lines(r.b, base + 4, base + ln, names, '   ')
        else:
            body, o = _field_lines(_T[typ][1], r.b, base + 4, base + ln, names, '   ')
            if o != base + ln:
                raise RelError('%s schema consumed %d of %d payload bytes'
                               % (tname, o - base, ln))
        L.extend(body)
        L.append('  </Item>')
    L.append(' </Items>')
    L.append('</Dat%d>' % r.ident)
    if stats is not None and (r.lista_n or r.listb_n):
        k = 'rel trailing offset lists present - not emitted (UNPINNED)'
        stats[k] = stats.get(k, 0) + 1
    return '\n'.join(L) + '\n'
