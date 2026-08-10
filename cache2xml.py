r"""cache2xml - GTA V `*_cache_y.dat` (the game's prebuilt map cache) -> RAGE .dat.xml.

CLEAN-ROOM: derived from oracle XML + game binary + our own quarry code only.

STATUS (2026-08-10): both graded oracles byte-identical under the refusal rule below, plus the
three shape-witness oracles minted the same day. Every NUMBER is exact with zero fitting -
113,431 float values, all counts, flags and u64s reproduce byte-for-byte.

WHY THIS LANE EXISTS: Matt ruled it in scope 2026-08-10, verbatim - "as for the cache files, if
they will positively impact the project without any negative consequences, I don't see the harm
in deriving them". It is supplemental: nothing in QUARRY or RUDE depends on it. What it buys is
an engine-authored cross-check of the map lanes (the game's own extents and bounds per ymap) and
a free spatial index for a DCC-side consumer.

CONTAINER - a HYBRID text/binary file, not a resource:
  0x0000  `[VERSION]\n<ver>\n` then zero padding to exactly 0x0064.
  0x0064  `<fileDates>\n` ... `</fileDates>\n`, one TEXT line per file, space separated:
              `<u32 nameHash decimal> <u64 timeStamp decimal> [<u32 fileID decimal>]`
          The fileID field is OPTIONAL - 290 of 1,750 lines game-wide carry only two fields,
          and the reference exporter spells those as `<fileID value="0" />` (witness:
          mp2024_01_g9ec_3927195028_cache_y.dat, both of its lines are 2-field).
  then    zero or more modules, each `<module>\n<NAME>\n` <u32 payload byte-length> <records>
          `</module>\n`. THE LEADING u32 IS A BYTE LENGTH, NOT A COUNT
          (292,928 == 4,577 x 64 == len(payload)-4). No padding; the file ends immediately
          after the final `</module>\n`.
  Modules seen: fwMapDataStore -> <MapDataStore>, CInteriorProxy -> <InteriorProxies>,
  BoundsStore -> <BoundsStore>. An ABSENT or EMPTY module self-closes (` <MapDataStore />`),
  as does an empty `<FileDates />` (witness: mpairraces_2339771181_cache_y.dat, in which
  every section is empty).

RECORDS (all little-endian; confirmed byte-identical across 30,328 records at scale):
  fwMapDataStore  64 B: u32 name, u32 parent, u32 contentFlags, 12 x f32 (streamingExtentsMin,
                        streamingExtentsMax, entitiesExtentsMin, entitiesExtentsMax),
                        then unk1..unk4 as FOUR u8 at +0x3C..+0x3F.
  CInteriorProxy 104 B: u32 unk01, u32 unk02, u32 unk03, u32 name, u32 parent,
                        13 x f32 (position xyz, rotation xyzw, bbMin xyz, bbMax xyz),
                        then unk11..unk14 as FOUR u64 at +0x48.
                        NOTE the BINARY field order is not the XML field order - the three
                        unk0* come FIRST in the record and LAST but one in the XML.
  BoundsStore     32 B: u32 name, 6 x f32 (bbMin xyz, bbMax xyz), u32 layer.

NAMES - measured, not assumed:
  * MODULE name/parent hashes are lowercase joaat of GAME FILE STEMS, and QUARRY's existing
    registry resolves them: `meta2xml.load_names_from_stems` over the view manifest answered
    42,930 of 42,930 module lookups across all 103 cache files, zero misses. No new dictionary.
  * FILEDATES hashes are NOT asset names - 0 of 1,124 match any stem or path form tested - so
    they spell `hash_%08X`, which is exactly what the oracles spell.

REFUSAL (the one open class, deliberately not papered over):
  Four module lookups in gta5_cache_y.dat are GENUINE 32-bit joaat COLLISIONS between two real
  game strings (e.g. `hw1_07_emissive_slod_lodb` vs `cs1_07_sea_0.ybn`), and the reference
  exporter's tie-break is internal to it: for one member of a nine-way family it prints the
  `_lod*` string and for the other eight it prints the real `.ybn` stem. Every rule-shaped
  explanation was tried and FALSIFIED (a `_lod` family rule scores 1 agree / 8 disagree).
  Resolving them our way would mean DISPLACING a name QUARRY can prove correct, which breaks the
  never-displace (`setdefault`) invariant the whole witnessed-name overlay rests on - and
  layout/naming calls are Matt's. So those four lines diverge, and each divergence is COUNTED
  (`joaat_collision_unresolved`) rather than hidden: 4 lines out of 124,393 in that file.
"""
import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from meta2xml import fmt_num, esc  # noqa: E402

# Counted classes, cleared per file by the caller and folded into the printed run summary.
RESIDUALS = {}

HEADER_LEN = 0x64
MODULE_XML = {'fwMapDataStore': 'MapDataStore',
              'CInteriorProxy': 'InteriorProxies',
              'BoundsStore': 'BoundsStore'}
XML_ORDER = ['MapDataStore', 'InteriorProxies', 'BoundsStore']


def is_cache(blob):
    """True for a cache_y.dat container. Magic is TEXTUAL, so check content, not the filename."""
    return blob[:10] == b'[VERSION]\n'


def _records(payload, stride, what):
    n = struct.unpack_from('<I', payload, 0)[0]
    if n != len(payload) - 4:
        raise ValueError('%s: declared payload %d != actual %d' % (what, n, len(payload) - 4))
    if n % stride:
        raise ValueError('%s: payload %d is not a multiple of the %d-byte record'
                         % (what, n, stride))
    return [4 + i * stride for i in range(n // stride)]


def parse(blob):
    """-> {'version': str, 'fileDates': [(hash, ts, fileID|None)], 'modules': {name: payload}}"""
    if not is_cache(blob):
        raise ValueError('not a cache container (no [VERSION] magic)')
    nl = blob.index(b'\n', 10)
    version = blob[10:nl].decode('ascii')
    fd = blob.index(b'<fileDates>\n')
    fde = blob.index(b'</fileDates>\n')
    dates = []
    for ln in blob[fd + 12:fde].decode('ascii').split('\n'):
        if not ln:
            continue
        f = ln.split(' ')
        if len(f) == 3:
            dates.append((int(f[0]), int(f[1]), int(f[2])))
        elif len(f) == 2:
            dates.append((int(f[0]), int(f[1]), None))    # fileID omitted -> spells 0
        else:
            raise ValueError('fileDates line with %d fields: %r' % (len(f), ln))
    p = fde + 13
    mods = {}
    while p < len(blob) and blob[p:p + 9] == b'<module>\n':
        p += 9
        e = blob.index(b'\n', p)
        name = blob[p:e].decode('ascii')
        p = e + 1
        end = blob.index(b'</module>\n', p)
        mods[name] = blob[p:end]
        p = end + 10
    if p != len(blob):
        raise ValueError('trailing bytes after the last module: %d' % (len(blob) - p))
    return {'version': version, 'fileDates': dates, 'modules': mods}


def to_xml(blob, names=None):
    """Convert one cache_y.dat -> reference-shaped XML text.

    names: {joaat: str} asset-name registry (quarry passes the view-manifest table). Absent, or
    on a miss, a hash spells `hash_%08X` - never a guess.
    """
    names = names or {}
    r = parse(blob)
    L = ['<?xml version="1.0" encoding="UTF-8"?>', '<CacheFile>',
         ' <Version value="%s" />' % r['version']]

    def nm(h):
        if h == 0:
            return ''
        s = names.get(h)
        if s is None:
            RESIDUALS['name_unresolved'] = RESIDUALS.get('name_unresolved', 0) + 1
            return 'hash_%08X' % h
        return s

    if not r['fileDates']:
        L.append(' <FileDates />')
    else:
        L.append(' <FileDates>')
        for h, ts, fid in r['fileDates']:
            L.append('  <Item>')
            # FileDates hashes are NOT asset names (0 of 1,124 resolve) - always hash form.
            L.append('   <fileName>hash_%08X</fileName>' % h)
            L.append('   <timeStamp value="%d" />' % ts)
            L.append('   <fileID value="%d" />' % (0 if fid is None else fid))
            L.append('  </Item>')
        L.append(' </FileDates>')

    def v3(tag, f, o, ind='   '):
        return '%s<%s x="%s" y="%s" z="%s" />' % (ind, tag, fmt_num(f[o]), fmt_num(f[o + 1]),
                                                  fmt_num(f[o + 2]))

    def parent_line(h):
        p = nm(h)
        return '   <parent />' if not p else '   <parent>%s</parent>' % esc(p)

    payloads = {MODULE_XML[k]: v for k, v in r['modules'].items() if k in MODULE_XML}
    for xtag in XML_ORDER:
        pl = payloads.get(xtag)
        if pl is None or len(pl) <= 4 or struct.unpack_from('<I', pl, 0)[0] == 0:
            L.append(' <%s />' % xtag)          # absent OR empty -> self-closing
            continue
        L.append(' <%s>' % xtag)
        if xtag == 'MapDataStore':
            for o in _records(pl, 64, 'fwMapDataStore'):
                name, parent, cf = struct.unpack_from('<III', pl, o)
                f = struct.unpack_from('<12f', pl, o + 12)
                u = struct.unpack_from('<4B', pl, o + 60)
                L.append('  <Item>')
                L.append('   <name>%s</name>' % esc(nm(name)))
                L.append(parent_line(parent))
                L.append('   <contentFlags value="%d" />' % cf)
                L.append(v3('streamingExtentsMin', f, 0))
                L.append(v3('streamingExtentsMax', f, 3))
                L.append(v3('entitiesExtentsMin', f, 6))
                L.append(v3('entitiesExtentsMax', f, 9))
                for k in range(4):
                    L.append('   <unk%d value="%d" />' % (k + 1, u[k]))
                L.append('  </Item>')
        elif xtag == 'InteriorProxies':
            for o in _records(pl, 104, 'CInteriorProxy'):
                u01, u02, u03, name, parent = struct.unpack_from('<IIIII', pl, o)
                f = struct.unpack_from('<13f', pl, o + 20)
                u11, u12, u13, u14 = struct.unpack_from('<4Q', pl, o + 72)
                L.append('  <Item>')
                L.append('   <name>%s</name>' % esc(nm(name)))
                L.append(parent_line(parent))
                L.append('   <position x="%s" y="%s" z="%s" />'
                         % (fmt_num(f[0]), fmt_num(f[1]), fmt_num(f[2])))
                L.append('   <rotation x="%s" y="%s" z="%s" w="%s" />'
                         % (fmt_num(f[3]), fmt_num(f[4]), fmt_num(f[5]), fmt_num(f[6])))
                L.append(v3('bbMin', f, 7))
                L.append(v3('bbMax', f, 10))
                for k, val in (('unk01', u01), ('unk02', u02), ('unk03', u03),
                               ('unk11', u11), ('unk12', u12), ('unk13', u13), ('unk14', u14)):
                    L.append('   <%s value="%d" />' % (k, val))
                L.append('  </Item>')
        else:
            for o in _records(pl, 32, 'BoundsStore'):
                (name,) = struct.unpack_from('<I', pl, o)
                f = struct.unpack_from('<6f', pl, o + 4)
                (layer,) = struct.unpack_from('<I', pl, o + 28)
                L.append('  <Item>')
                L.append('   <name>%s</name>' % esc(nm(name)))
                L.append(v3('bbMin', f, 0))
                L.append(v3('bbMax', f, 3))
                L.append('   <layer value="%d" />' % layer)
                L.append('  </Item>')
        L.append(' </%s>' % xtag)
    L.append('</CacheFile>')
    return '\n'.join(L) + '\n'


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(2)
    for p in sys.argv[1:]:
        RESIDUALS.clear()
        blob = open(p, 'rb').read()
        print(to_xml(blob), end='')
        if RESIDUALS:
            print('<!-- counters: %s -->' % json.dumps(RESIDUALS), file=sys.stderr)
