"""QUARRY - build a working project folder from a RAGE game install.

The companion to RUDE, deliberately a SEPARATE tool:
  QUARRY  = reads the user's own game archives -> a sorted, precedence-aware project folder
  RUDE    = a UE plugin that consumes that folder, and contains no archive/crypto code

They meet only at a folder contract (_FILEBASE.json + 00_base / 10_update / 20_dlc),
so neither depends on the other's internals - and the DCC stays clean-room.

Title-aware from day one: the same contract is intended to cover GTA V Legacy,
GTA V Enhanced, and later RAGE titles (RDR2/RedM, GTA VI).

Status of the pieces:
  * RPF7 container, TOC walk, entry decode, deflate/Oodle .......... implemented
  * project folder build + precedence sorting + manifest .......... implemented
  * AES key recovery from the user's own executable ............... implemented (SHA1 scan)
  * NG block cipher ............................................... implemented (ngcrypto)
  * NG key/table DATA ............................................. OPERATOR-SUPPLIED, see --keys
QUARRY ships no key material.

Usage:
  quarry.py scan    --game <install>
  quarry.py init    --game <install> --out <project>
  quarry.py extract --game <install> --out <project> --keys <dir> [--only x64a.rpf]
"""
import argparse, glob, json, os, re, shutil, struct, sys, zlib
from datetime import datetime

import ngcrypto
# The RSC7 page plan is the only statement of a resource's real length that does not come from
# the TOC, which makes it the one thing that can VOUCH for a decoded body - see payload().
from ydr2xml import seg_size

MAGIC = b'7FPR'
DIR_IDENT = 0x7FFFFF00
ENC_OPEN, ENC_AES, ENC_NG = 0x00000000, 0x0FFFFFF9, 0x0FEFFFFF
SIZE_SATURATED = 0xFFFFFF     # a u24 FileSize field that ran out of bits: real length >= 16MB

TYPES_CORE = ('ydr', 'ydd', 'ytd', 'ybn', 'ytyp', 'ymap')


# ------------------------------------------------------------------ install discovery
def detect_title(game_root):
    if os.path.isfile(os.path.join(game_root, 'GTA5_Enhanced.exe')):
        return 'gtav-enhanced', 'GTA5_Enhanced.exe'
    if os.path.isfile(os.path.join(game_root, 'GTA5.exe')):
        return 'gtav-legacy', 'GTA5.exe'
    if os.path.isfile(os.path.join(game_root, 'RDR2.exe')):
        return 'rdr2', 'RDR2.exe'
    return 'unknown', ''


def find_sources(game_root):
    """Base archives, the update archive(s), and DLC packs - by directory listing only."""
    base = sorted(os.path.basename(p) for p in glob.glob(os.path.join(game_root, '*.rpf')))
    upd = sorted(glob.glob(os.path.join(game_root, 'update', '*.rpf')))
    dlc = sorted(d for d in glob.glob(os.path.join(game_root, 'update', 'x64', 'dlcpacks', '*'))
                 if os.path.isdir(d))

    def year_key(p):
        n = os.path.basename(p)
        for y in range(2013, 2036):
            if str(y) in n:
                return (y, n)
        return (0, n)
    dlc.sort(key=year_key)
    return base, upd, dlc


def oodle_dll(game_root, explicit=None):
    """Locate the operator's own Oodle DLL.

    ⚠ A GTA V *Legacy* install does NOT ship oo2core - the DLL arrives with *Enhanced*. So
    searching only under --game silently yields None on exactly the title QUARRY targets, and
    every Oodle-packed entry then fails. Accept an explicit --oodle path and, failing that,
    look across the sibling Rockstar installs on this machine. QUARRY still never ships or
    copies the DLL: it binds the operator's own file, wherever it already lives.
    """
    if explicit:
        return explicit if os.path.isfile(explicit) else None
    roots = [game_root]
    parent = os.path.dirname(game_root.rstrip('\\/'))
    if parent and os.path.isdir(parent):
        roots.append(parent)          # ...\Rockstar Games\  -> covers the Enhanced install
    for root in roots:
        for pat in ('oo2core_*_win64.dll', 'oo2core_*.dll'):
            hits = glob.glob(os.path.join(root, '**', pat), recursive=True)
            if hits:
                return hits[0]
    return None


def _deflate_span(buf):
    """(input bytes consumed, output bytes produced) for the raw-DEFLATE stream that starts at
    buf[0], or None when buf does not hold one COMPLETE stream.

    ⚠ Must validate the WHOLE stream, not a prefix. A 4KB probe was tried first and gave a
    FALSE POSITIVE: NG-decrypted garbage decoded far enough to look plausible, and the file
    was written anyway (`parachute_decals.ytd` - "invalid distance too far back" at byte 0
    on a full decode). Since the whole point of this gate is that a rebuilt RSC7 header
    cannot vouch for the payload, a gate that only checks a prefix reintroduces the bug.

    ⛔⛔ 2026-07-27 - AND THE STREAM MUST ACTUALLY END. This returned
    `d.eof or not d.unconsumed_tail`, and `unconsumed_tail` is only ever non-empty when
    max_length is passed to decompress() - so on a TRUNCATED body it is b'' and the second
    clause declared the truncated body VALID. That is how seven >=16MB .ytd files were written
    at exactly 16,777,215 bytes while the run reported zero failures: the one gate that could
    have caught it was the thing that waved it through. `d.eof` is the only proof that a body
    is whole, and the consumed count is what makes the written body byte-exact rather than
    merely long enough.
    Streamed in chunks so a large resource never doubles peak memory - the inflated bytes are
    measured and dropped, never accumulated.
    """
    if not buf:
        return None
    d = zlib.decompressobj(-15)
    mv = memoryview(buf)
    used = made = 0
    try:
        for i in range(0, len(mv), 1 << 16):
            chunk = bytes(mv[i:i + (1 << 16)])
            made += len(d.decompress(chunk))
            if d.eof:
                return used + len(chunk) - len(d.unused_data), made
            used += len(chunk)
    except zlib.error:
        return None
    return None                       # input exhausted with no end-of-stream marker: TRUNCATED


# ------------------------------------------------------------------ RPF7 container
class Rpf:
    def __init__(self, path, keys=None, tables=None, data=None, name=None):
        """path may be a real file, OR pass data=<bytes> for an archive NESTED inside
        another archive (most of the game's map assets live one level down)."""
        self.path = path
        self.data = open(path, 'rb').read() if data is None else data
        # The archive's TOC key is derived from the archive's OWN name + its OWN total
        # size. For a nested archive that is the entry name and the blob length - NOT the
        # containing file's - so both are captured here rather than read from the fs.
        self.name = name if name is not None else os.path.basename(path)
        magic, self.count, self.names_len, self.enc = struct.unpack_from('<4sIII', self.data, 0)
        if magic != MAGIC:
            raise ValueError(f'{path}: not RPF7 ({magic!r})')
        self.keys, self.tables = keys, tables
        self.entries = []
        self.names = b''

    def _decrypt(self, blob):
        if self.enc == ENC_OPEN:
            return blob
        if self.enc == ENC_NG:
            if self.keys is None or self.tables is None:
                raise KeyError('NG-encrypted; supply --keys (see README)')
            ki = ngcrypto.key_index(ngcrypto.joaat(self.name), len(self.data))
            return ngcrypto.decrypt(blob, self.keys[ki], self.tables)
        if self.enc == ENC_AES:
            # self.aes_key was NEVER assigned anywhere, so this path used to raise a bare
            # AttributeError that read like a QUARRY bug. It is a MISSING CAPABILITY: the
            # 32-byte AES key is not part of the recovered NG key data (ng_keys.bin holds the
            # 101 NG keys only) - it lives in the executable and is a separate recovery step.
            #
            # ⛔ THIS MESSAGE USED TO CLAIM "only affects vehicle *_mods.rpf, out of scope for
            # RUDE (no vehicles)". BOTH HALVES WERE WRONG (corrected 2026-07-29):
            #   1. The observed skips include des_setpiece.rpf, des_jetsteal.rpf and
            #      des_heli_billboard/biotech/highway/mansion/scrapyard.rpf, plus ~27 more - MAP
            #      set-piece archives, not vehicle mods.
            #   2. "no vehicles" cites a scope decision Matt RETRACTED on 2026-07-27; an agent made
            #      that call, not him, and .yft/vehicles are explicitly back in scope.
            # A skip that announces itself as harmless is the dangerous kind - it is how the Cayo
            # dlc.rpf hole hid 7.2 GB. State what is skipped and let the caller judge; never encode
            # a scope conclusion here.
            raise KeyError('AES-encrypted archive: no AES key available. This is a separate key '
                           'from the NG set and is not yet recovered, so this archive and its '
                           'contents are SKIPPED. Affected archives include map set-piece rpf '
                           '(des_*), not only vehicle *_mods.rpf - if content appears missing '
                           'downstream, suspect this first')
        raise ValueError(f'unknown encryption 0x{self.enc:08x}')

    def read_toc(self):
        toc = self._decrypt(self.data[16:16 + self.count * 16])
        self.names = self._decrypt(
            self.data[16 + self.count * 16: 16 + self.count * 16 + self.names_len])
        self.entries = []
        # RPF7 entry, 16 bytes - layout derived from real archive data:
        #   u16 @0  name offset into the names blob
        #   u24 @2  size ON DISK (0 = stored uncompressed, use usize; 0xFFFFFF = SATURATED,
        #           i.e. >=16MB and the field cannot hold it - payload() resolves it, and a
        #           consumer must never treat 0xFFFFFF as a length)
        #   u24 @5  bit23 = IS-RESOURCE flag; bits 0..22 = offset in 512-byte sectors
        #   u32 @8  binary: uncompressed size   | resource: system flags
        #   u32 @12 binary: encryption flag     | resource: graphics flags
        # A directory entry is identified by 0x7FFFFF00 in the second dword.
        for i in range(self.count):
            e = toc[i * 16:(i + 1) * 16]
            w0, w1, w2, w3 = struct.unpack('<IIII', e)
            noff = struct.unpack_from('<H', e, 0)[0]
            end = self.names.find(b'\x00', noff)
            name = self.names[noff:end if end >= 0 else noff].decode('latin-1', 'replace')
            if w1 == DIR_IDENT:
                self.entries.append({'name': name, 'dir': True, 'idx': w2, 'n': w3})
                continue
            size = e[2] | (e[3] << 8) | (e[4] << 16)
            offraw = e[5] | (e[6] << 8) | (e[7] << 16)
            self.entries.append({
                'name': name, 'dir': False,
                'size': size,
                'off': (offraw & 0x7FFFFF) * 512,
                'resource': bool(offraw & 0x800000),
                'usize': w2,      # binary: uncompressed size | resource: system flags
                'gfx': w3,        # resource: graphics flags
            })
        return self.entries

    def sane(self):
        return bool(self.entries) and self.entries[0]['dir']

    def _inflate(self, raw, usize, oodle):
        try:
            return zlib.decompress(raw, -15)      # raw DEFLATE - the common case
        except zlib.error:
            pass
        if oodle and usize:
            try:
                return oodle(raw, usize)
            except Exception:
                pass
        return None

    def _ng(self, blob, name, size):
        if self.keys is None or self.tables is None:
            return blob
        ki = ngcrypto.key_index(ngcrypto.joaat(name), size)
        return ngcrypto.decrypt(blob, self.keys[ki], self.tables)

    def _saturated_size(self, off):
        """On-disk length of a resource whose TOC FileSize saturated - read from the file data.

        The real length is carried in the 16-byte block the entry points at (the block payload()
        skips because it rebuilds the RSC7 header from the entry flags) as a little-endian u32
        assembled from bytes 7, 14, 5, 2 - scattered, not a plain field.

        EMPIRICAL, and derived the hard way rather than assumed: for every one of the 50
        saturated entries in the GTA V Legacy base archives (12 of the 24, all of them big
        terrain/road texture dictionaries) the length zlib actually consumes was measured, then
        bit-solved against that block - all 32 bits of the length land on those 4 byte positions
        in all 50 cases, while the block's other 12 bytes carry ~50 distinct values each and
        remain unexplained. The SAME decode on a non-saturated entry yields nonsense, so it is
        applied only when the field has saturated, and it is only ever a WINDOW: the exact end
        of the body comes from the DEFLATE stream, and the page plan is what vouches for it.
        """
        b = self.data[off:off + 0x10]
        n = b[7] | (b[14] << 8) | (b[5] << 16) | (b[2] << 24)
        return min(n, len(self.data) - off)       # never read past the end of the archive

    def payload(self, e, oodle=None):
        """Reconstruct one file.

        RESOURCE entries: a 16-byte header SLOT sits at the offset and the DEFLATE-compressed
        body follows it - that is exactly what a .ydr/.ytd looks like on disk, so rebuilt
        header + body IS the finished file (do not inflate it). The body's length is NOT
        simply FileSize-0x10: FileSize is a u24 and saturates - see the 2026-07-27 note.
        Key size input differs by entry type: resources key on FileSize, binary entries
        on FileUncompressedSize.
        """
        off, size = e['off'], e['size']
        if size == 0:                                  # stored plain, length from usize
            n = e['usize'] or 0
            return self.data[off:off + n] if n else b''

        if e['resource']:
            # The 16 bytes at the offset are NOT the RSC7 header - they are skipped and
            # the header is REBUILT from the entry's own flags:
            #   version = (sysFlags>>28)<<4 | (gfxFlags>>28)
            # cross-checked against RUDE's own writers: ytd 0x0/0xd -> 13,
            # ybn 0x2/0xb -> 43, ydr 0xa/0x5 -> 165. The body stays DEFLATE-compressed,
            # which is exactly the on-disk form of a .ytd/.ydr.
            #
            # ⛔⛔ FIXED 2026-07-26 - THIS WAS SILENTLY CORRUPTING EVERY RESOURCE.
            # The body was NG-decrypted UNCONDITIONALLY, but in an NG archive the TOC is
            # encrypted while most resource DATA is not: decrypting plain deflate produces
            # garbage. It went unnoticed because the RSC7 header is REBUILT from the entry
            # flags, so the file ALWAYS looks like a valid, correctly-versioned resource no
            # matter how mangled the body is - the exact failure mode the log warns about
            # ("decrypting the header along with the body looks exactly like a wrong key").
            # Measured before the fix: 63 of 64 extracted .ytd bodies would not inflate.
            # Now SELF-VERIFYING: a resource body must be valid DEFLATE, so try it plain,
            # then NG-decrypted, and keep whichever actually inflates. Neither = report it
            # rather than writing a plausible-looking corrupt file.
            #
            # ⛔⛔ FIXED 2026-07-27 - EVERY RESOURCE >=16MB WAS TRUNCATED, SILENTLY.
            # FileSize is a u24, so an entry of 16MB or more cannot state its length at all: it
            # stores 0xFFFFFF, a SATURATION MARKER. Taken literally it cut the body at
            # 0xFFFFFF-0x10 bytes, so the file landed on disk at exactly 16,777,215 B and could
            # not inflate - 50 entries game-wide, 7 of them in x64g alone. The length therefore
            # comes from the data (_saturated_size), and because DEFLATE is self-terminating the
            # stream's own end is what the body is trimmed to, which makes an over-long window
            # harmless and an over-short one impossible to mistake for success.
            # The gate is now the RSC7 PAGE PLAN, not just "is it deflate": a body must inflate
            # to EXACTLY the bytes its sysFlags+gfxFlags page plan declares (verified on 4,176
            # resources across x64a/x64g - every single one exact). That is the only check the
            # entry cannot lie to, since the rebuilt header parrots those same flags.
            if size == SIZE_SATURATED:
                size = self._saturated_size(off)
            want = seg_size(e['usize']) + seg_size(e['gfx'])
            raw = memoryview(self.data)[off + 0x10: off + size]
            span, how = _deflate_span(raw), 'plain'
            if span is None or span[1] != want:
                dec = self._ng(bytes(raw), e['name'], size)
                span, how = _deflate_span(dec), 'ng'
                if span is None or span[1] != want:
                    raise ValueError(
                        f'resource body does not inflate to its RSC7 page plan ({want} B) '
                        'either plain or NG-decrypted - refusing to write it (unknown '
                        'compression, e.g. Oodle-packed resource, or a bad length)')
                raw = memoryview(dec)
            body = bytes(raw[:span[0]])
            e['_how'] = how
            sysf, gfxf = e['usize'], e['gfx']
            version = (((sysf >> 28) & 0xF) << 4) | ((gfxf >> 28) & 0xF)
            return struct.pack('<4sIII', b'RSC7', version, sysf, gfxf) + body

        if size == SIZE_SATURATED:
            # The same u24 saturation as above, but a binary entry has no page plan to check a
            # recovered length against, and its last resort below is to return the raw bytes -
            # which for a truncated window is a corrupt file that looks like a success. So guess
            # nothing and report it. (No such entry exists in GTA V Legacy: all 50 saturated
            # entries in the base archives are resources.)
            raise ValueError('binary entry >=16MB: FileSize saturated at 0xFFFFFF and a binary '
                             'entry carries no page plan to recover the real length from')
        raw = self.data[off:off + size]
        dec = self._ng(raw, e['name'], e['usize'])
        got = self._inflate(dec, e['usize'], oodle)
        if got is not None:
            return got
        got = self._inflate(raw, e['usize'], oodle)     # unencrypted entry
        return got if got is not None else raw


# ------------------------------------------------------------------ project folder
def slot_dirs(out_root, base_n, dlc_names):
    os.makedirs(os.path.join(out_root, '_manifest'), exist_ok=True)
    os.makedirs(os.path.join(out_root, '00_base'), exist_ok=True)
    os.makedirs(os.path.join(out_root, '10_update'), exist_ok=True)
    for i, n in enumerate(dlc_names):
        os.makedirs(os.path.join(out_root, '20_dlc', '%03d_%s' % (i + 1, n)), exist_ok=True)


def read_dlclist(game_root, keys, tables, oodle=None):
    """The game's OWN DLC load order, from `dlclist.xml` inside update.rpf. -> [pack names] or None.

    ⭐ WHY THIS MATTERS beyond tidiness (Matt, 2026-07-27): *"In a FiveM server, the DLC version the
    server runs overrides everything underneath it. Different servers run different DLCs, so editing
    at a specific DLC level will ensure proper override where it's needed."* Precedence is therefore
    a CORRECTNESS requirement, not a convenience - and until now our order was a heuristic
    (year-bearing names last, else alphabetical), so which DLC won was a guess. A guess is fine for
    "show me the newest copy" and NOT fine for "author an override that must land above pack X".

    Reads the TOC and inflates ONLY that one entry - update.rpf is multi-GB and walking it to find a
    2 KB file would cost minutes.
    """
    upd = os.path.join(game_root, 'update', 'update.rpf')
    if not os.path.isfile(upd):
        return None
    try:
        r = Rpf(upd, keys, tables)
        r.read_toc()
        if not r.sane():
            return None
        for e in r.entries:
            if e.get('dir') or e['name'].lower() != 'dlclist.xml':
                continue
            blob = r.payload(e, oodle)
            text = blob.decode('utf-8', 'replace')
            # <Item>dlcpacks:/mpbiker/</Item> - order in the file IS the load order.
            names = []
            for m in re.finditer(r'<Item>\s*([^<]+?)\s*</Item>', text, re.I):
                pack = m.group(1).strip().strip('/').split('/')[-1].split(':')[-1].strip()
                if pack and pack.lower() not in [n.lower() for n in names]:
                    names.append(pack)
            return names or None
    except Exception as e:
        # Best effort - a heuristic order beats refusing to build a project - but SAY SO. A bare
        # silent `return None` here hid a one-word bug (read_toc vs parse) behind a plausible
        # "heuristic" message, and the fallback looked like a legitimate outcome.
        print(f'dlc order: could not read dlclist.xml - {type(e).__name__}: {e}')
        return None
    print('dlc order: update.rpf parsed but contains no dlclist.xml entry')
    return None


def order_dlc(dlc_dirs, listed):
    """Reorder discovered DLC directories to the game's own load order.

    Packs the list does not mention keep their heuristic order and go AFTER the listed ones - they
    are installed but not loaded, so they cannot outrank anything the game actually loads.
    """
    if not listed:
        return dlc_dirs, False
    rank = {n.lower(): i for i, n in enumerate(listed)}
    known = [d for d in dlc_dirs if os.path.basename(d).lower() in rank]
    rest = [d for d in dlc_dirs if os.path.basename(d).lower() not in rank]
    known.sort(key=lambda d: rank[os.path.basename(d).lower()])
    return known + rest, True


def write_manifest(out_root, game_root, title, exe, base, dlc, authoritative=False):
    st = os.stat(os.path.join(game_root, exe)) if exe else None
    man = {
        'quarryVersion': 1,
        'title': title,
        'gameRoot': game_root,
        'build': ({'exe': exe, 'bytes': st.st_size,
                   'modified': datetime.fromtimestamp(st.st_mtime).isoformat()} if st else {}),
        'created': datetime.now().isoformat(timespec='seconds'),
        'precedence': ['00_base', '10_update', '20_dlc/<order>_<name>'],
        'precedenceNote': 'Later wins. A name in several sources resolves to the '
                          'highest-ordered copy - that is what keeps a project build-accurate.',
        'dlcOrderAuthoritative': bool(authoritative),
        'dlcOrderNote': ("Read from the game's own dlclist.xml inside update.rpf - this IS the "
                         'load order.' if authoritative else
                         'HEURISTIC (year-bearing names last, else alphabetical) - dlclist.xml '
                         'could not be read, so which DLC wins is a GUESS. Do not author an '
                         'override against this ordering.'),
        'baseArchives': base,
        'dlcPacks': [{'order': i + 1, 'name': n} for i, n in enumerate(dlc)],
    }
    with open(os.path.join(out_root, '_FILEBASE.json'), 'w') as f:
        json.dump(man, f, indent=1)
    return man


def type_of(name):
    ext = os.path.splitext(name)[1].lstrip('.').lower()
    if ext == 'xml':
        ext = os.path.splitext(os.path.splitext(name)[0])[1].lstrip('.').lower()
    return ext or 'other'


def sidecar_into(out_root, slot, type_dir, relpath, blob):
    """Write a companion file that belongs WITH a converted asset (a ytd's .dds payload) under
    the asset's own type folder. Kept separate from file_into because the type folder is the
    asset's, not the sidecar's - a .dds must not be filed under `dds/`, or the XML's relative
    FileName reference breaks."""
    target = os.path.join(out_root, slot, type_dir, relpath.replace('/', os.sep))
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, 'wb') as f:
        f.write(blob)


def to_interchange_xml(name, blob, textures='both'):
    """One asset -> (xml filename, xml bytes, [(sidecar relpath, bytes)]), or None when no
    converter exists for that type yet.

    THE CONTRACT: RUDE's importer reads the RAGE interchange XML, so this is where a raw archive
    resource becomes something the plugin can consume. Registering a type here is all that is
    needed to connect it end-to-end - see quarry/README.md "Export EVERYTHING through the XML
    pipeline".
    """
    t = type_of(name)
    stem = os.path.splitext(name)[0]
    if t == 'ydr':
        import ydr2xml
        res = ydr2xml.Res.from_bytes(blob)
        inner = res.cstr(res.ptr(0xA8)) or (stem + '.#dr')
        return stem + '.ydr.xml', ydr2xml.to_xml(res, inner).encode('utf-8'), []
    if t == 'ytd':
        import ytd2xml
        res = ytd2xml.Res.from_bytes(blob)
        res.require_version(13, 'texture dictionary')
        texs = ytd2xml.read_textures(res)
        # ⭐ textures='none' emits the MANIFEST ONLY. The manifest is what answers "which
        # dictionaries does anything reference" (~0.1 GB whole-game); the PIXELS are the 86 GB, and
        # decoding them for every texture in the game before knowing which are wanted is what filled
        # this volume to zero bytes. Decode later, filtered, via `quarry textures`.
        sidecars = () if textures == 'none' else ytd2xml.sidecars(
            texs, stem, want_png=(textures != 'dds'), want_dds=(textures != 'png'))
        return (stem + '.ytd.xml', ytd2xml.to_xml(texs).encode('utf-8'), sidecars)
    if t == 'ydd':
        import ydd2xml
        res = ydd2xml.Res.from_bytes(blob)
        # names={}: the joaat reverse table is a meta-pass artifact and does not exist at extract
        # time; hash_%08X entry names are the working contract (dictionary joins are hash-to-hash)
        xml, _n = ydd2xml.to_xml(res, {})
        return stem + '.ydd.xml', xml.encode('utf-8'), []
    if t == 'yft':
        import yft2xml
        res = yft2xml.Res.from_bytes(blob)
        return stem + '.yft.xml', yft2xml.to_xml(res, stem).encode('utf-8'), []
    return None


def file_into(out_root, slot, name, blob, stats=None):
    """File one blob by type into a precedence slot.

    Filing is FLAT by basename inside <slot>/<ext>/, which means two same-named files from
    different archives in the SAME slot collide. That is not hypothetical: the 24 base
    archives share one namespace and there are ~84k ydrs across the game. Silently
    overwriting loses build-accurate data with no trace, so a collision now keeps the FIRST
    copy, writes the loser as <stem>~<n><ext>, and is COUNTED so the run reports it.
    (Load-order precedence ACROSS slots is still what the numbered tree encodes; this only
    disambiguates within one slot.)
    """
    d = os.path.join(out_root, slot, type_of(name))
    os.makedirs(d, exist_ok=True)
    target = os.path.join(d, name)
    if os.path.exists(target):
        if stats is not None:
            stats['collisions'] = stats.get('collisions', 0) + 1
        stem, ext = split_type_ext(name)
        n = 1
        while os.path.exists(os.path.join(d, f'{stem}~{n}{ext}')):
            n += 1
        target = os.path.join(d, f'{stem}~{n}{ext}')
    with open(target, 'wb') as f:
        f.write(blob)
    return os.path.basename(target)


def split_type_ext(name):
    """('foo', '.ytd.xml') - the DOUBLE extension is kept whole.

    Load-bearing for collisions: naive splitext turns `foo.ytd.xml` into `foo.ytd~1.xml`, and
    every consumer globs for `*.ytd.xml` / looks up `<assetName>.ydr.xml` exactly, so the
    renamed copy becomes invisible - the collision would be "handled" and the asset still lost.
    """
    stem, ext = os.path.splitext(name)
    if ext.lower() == '.xml':
        stem2, ext2 = os.path.splitext(stem)
        if ext2:
            return stem2, ext2 + ext
    return stem, ext


def walk_archive(r, oodle, depth=0, max_depth=2, stats=None, path=''):
    """Yield (name, blob) for every FILE in this archive, DESCENDING into nested .rpf.

    This is the difference between 624 files and the real corpus: the base archives are
    mostly containers - x64g.rpf is 2.4GB in FIVE top-level entries, all of them nested
    archives - and essentially every .ydr/.ybn/.ytyp/.ymap in the game lives at depth 2.
    A flat walk finds ZERO map assets, which is exactly what the first run produced.
    """
    for e in r.entries:
        if e['dir']:
            continue
        name = e['name']
        try:
            blob = r.payload(e, oodle)
        except Exception as ex:
            if stats is not None:
                stats['failed'] = stats.get('failed', 0) + 1
                # The MESSAGE, not just the class: these are the rejections that stop a corrupt
                # body being written, so the run has to say WHICH invariant the entry failed -
                # a bare "ValueError" is indistinguishable from a crash and gets ignored.
                stats.setdefault('failures', []).append(
                    f'{path}/{name}: {type(ex).__name__}: {ex}')
            continue
        if name.lower().endswith('.rpf'):
            if depth >= max_depth:
                if stats is not None:
                    stats['nested_skipped'] = stats.get('nested_skipped', 0) + 1
                continue
            try:
                # key inputs for a nested archive = its OWN entry name + its OWN blob length
                sub = Rpf(f'{path}/{name}', r.keys, r.tables, data=blob, name=name)
                sub.read_toc()
                if not sub.sane():
                    raise ValueError('nested TOC did not decode')
            except Exception as ex:
                if stats is not None:
                    stats['nested_failed'] = stats.get('nested_failed', 0) + 1
                    stats.setdefault('failures', []).append(
                        f'{path}/{name} (nested): {type(ex).__name__}: {ex}')
                continue
            if stats is not None:
                stats['nested_opened'] = stats.get('nested_opened', 0) + 1
            yield from walk_archive(sub, oodle, depth + 1, max_depth, stats, f'{path}/{name}')
            continue
        yield name, blob


# ------------------------------------------------------------------ commands
def manifest_flag(out_root, key='dlcOrderAuthoritative', default=False):
    """Read one field out of the project's _FILEBASE.json, so downstream artifacts inherit what the
    extraction actually established instead of restating a guess."""
    try:
        with open(os.path.join(out_root, '_FILEBASE.json')) as f:
            return json.load(f).get(key, default)
    except Exception:
        return default


def precedence_slots(out_root):
    """Every slot in ASCENDING load order - the order the game itself resolves in, so a later
    entry legitimately overrides an earlier one."""
    slots = [s for s in ('00_base', '10_update') if os.path.isdir(os.path.join(out_root, s))]
    dlc_root = os.path.join(out_root, '20_dlc')
    if os.path.isdir(dlc_root):
        # names are NNN_<pack>, so lexical sort IS load order
        slots += [os.path.join('20_dlc', d) for d in sorted(os.listdir(dlc_root))
                  if os.path.isdir(os.path.join(dlc_root, d))]
    return slots


def cmd_doctor(a):
    """Preflight: tell a NEW USER exactly what on their machine is ready and what is not.

    Foundation step 1/2 says a new user must be able to download the tool and prepare a project
    folder. Today the failure modes are silent and each one looks like a different bug: no numpy
    (the cipher hangs), no PNG decoders (the texture lane writes a folder RUDE cannot read), a
    Legacy install with no oo2core, or simply not enough disk for a whole-game run. Diagnose all of
    it up front and say what to do, rather than letting the user discover it mid-extract.
    """
    ok = warn = bad = 0

    def line(state, label, detail):
        nonlocal ok, warn, bad
        mark = {'ok': ' OK ', 'warn': 'WARN', 'bad': 'FAIL'}[state]
        if state == 'ok':
            ok += 1
        elif state == 'warn':
            warn += 1
        else:
            bad += 1
        print(f'  [{mark}] {label:<26} {detail}')

    print('QUARRY preflight\n')
    v = sys.version_info
    line('ok' if v >= (3, 8) else 'bad', 'python',
         f'{v.major}.{v.minor}.{v.micro}' + ('' if v >= (3, 8) else '  -> need 3.8+'))

    try:
        import numpy
        line('ok', 'numpy', f'{numpy.__version__}')
    except Exception:
        line('bad', 'numpy', 'MISSING -> pip install numpy   (the NG cipher needs it; the '
                             'scalar fallback hangs on real archives)')

    try:
        import ytd2xml
        if ytd2xml.png_available():
            line('ok', 'texture decoders', 'texture2ddecoder + Pillow present')
        else:
            line('warn', 'texture decoders',
                 'MISSING -> pip install texture2ddecoder Pillow   (without them ytd folders '
                 'hold .dds only, and RUDE\'s ImportYtd reads .png)')
    except Exception as e:
        line('bad', 'ytd converter', f'{type(e).__name__}: {e}')

    for mod, what in (('ydr2xml', 'ydr -> XML'), ('meta2xml', 'ytyp/ymap -> XML'),
                      ('ydd2xml', 'ydd -> XML (drawable dictionaries)'),
                      ('yft2xml', 'yft -> XML (fragments, visual drawable)'),
                      ('ngcrypto', 'NG cipher'), ('keyderive', 'key derivation')):
        try:
            __import__(mod)
            line('ok', mod, what)
        except Exception as e:
            line('bad', mod, f'{type(e).__name__}: {e}')

    # ---- the game install: the thing everything else depends on ----
    game = a.game
    if not game:
        line('warn', 'game install', 'not given -> pass --game "<install path>" to check it')
    elif not os.path.isdir(game):
        line('bad', 'game install', f'not a directory: {game}')
    else:
        title, exe = detect_title(game)
        if title == 'unknown':
            line('bad', 'game install', f'no known executable found in {game}')
        else:
            line('ok', 'game install', f'{title}  ({exe})')
            base, upd, dlc = find_sources(game)
            line('ok' if base else 'bad', 'archives',
                 f'{len(base)} base, {len(upd)} update, {len(dlc)} dlc packs')
            try:
                import contextlib
                import io as _io
                import keyderive
                # acquire() narrates its own progress, which would break this aligned report -
                # swallow it here only; every other caller still wants to see it.
                with contextlib.redirect_stdout(_io.StringIO()):
                    raw_k, raw_t = keyderive.acquire(game, getattr(a, 'keys', None),
                                                     getattr(a, 'magic', None))
                line('ok', 'key material',
                     f'derived from your own {exe}  ({len(raw_k):,} B keys + {len(raw_t):,} B '
                     f'tables) - no --keys needed')
            except Exception as e:
                line('bad', 'key material',
                     f'{e}  -> encrypted archives would be SKIPPED, not silently mis-read')
            dll = oodle_dll(game, getattr(a, 'oodle', None))
            if dll:
                line('ok', 'oodle', os.path.basename(dll))
            else:
                line('warn', 'oodle',
                     'not found. A GTA V *Legacy* install ships none (Enhanced does). Only '
                     'Oodle-packed BINARY entries need it; pass --oodle <oo2core_*_win64.dll>')

    # ---- disk, against the measured cost of a real run ----
    out = getattr(a, 'out', None)
    probe = out if out else os.getcwd()
    try:
        free = shutil.disk_usage(os.path.splitdrive(os.path.abspath(probe))[0] + os.sep).free
        gb = free / (1 << 30)
        # measured on x64i.rpf: ydr.xml avg 469 KB over ~84k ydr, plus 23 GB dds + 33 GB png
        note = ('enough for a whole-game run with textures (~94 GB)' if gb > 110 else
                'enough for a MAP-ONLY run (~38 GB); use --textures png or skip ytd' if gb > 45 else
                'enough for a few archives only' if gb > 8 else 'TIGHT - extract one archive at a time')
        line('ok' if gb > 45 else 'warn', 'free disk',
             f'{gb:,.1f} GB on {os.path.splitdrive(os.path.abspath(probe))[0]}  -> {note}')
    except Exception as e:
        line('warn', 'free disk', f'could not determine: {e}')

    print(f'\n  {ok} ok, {warn} warning(s), {bad} blocker(s)')
    if bad:
        print('  Fix the FAIL lines before extracting; QUARRY reports rather than guessing, so a '
              'blocker means skipped archives, not corrupt output.')
    else:
        print('  Ready. Next:  quarry.py extract --game "<install>" --out "<project>" --xml '
              '--types ydr,ytd,ytyp,ymap')
        print('  Then:         quarry.py meta --out "<project>"   and   quarry.py resolve --out '
              '"<project>"')
    return 1 if bad else 0


def cmd_meta(a):
    """Convert every binary .ytyp/.ymap in the project to interchange XML.

    ⭐ WHY THIS IS A SECOND PASS rather than part of `extract`: a ytyp stores its archetype and
    asset names as ONE-WAY joaat hashes, and the reverse table is built by hashing the asset
    FILENAMES the archives yield. During extraction most of those files have not landed yet, so
    converting inline would resolve far fewer names. Running after extraction means the table is
    complete and `assetName` - the one name that MUST resolve, because RUDE turns it into a
    `<CorpusRoot>/ydr/<assetName>.ydr.xml` lookup - resolves from the user's own data.

    Order is therefore:  extract  ->  meta  ->  resolve
    """
    import meta2xml
    out = a.out
    if not os.path.isdir(out):
        print(f'no project folder at {out}')
        return 1
    slots = precedence_slots(out)
    if not slots:
        print(f'no precedence slots under {out} - run `extract` first')
        return 1

    print('names    : hashing every asset filename in the project for the joaat reverse table ...')
    names = meta2xml.load_names(*[os.path.join(out, s) for s in slots])
    print(f'names    : {len(names):,} distinct asset names available')

    ok = fail = 0
    unresolved = 0
    why = {}
    for slot in slots:
        for kind in ('ytyp', 'ymap'):
            d = os.path.join(out, slot, kind)
            if not os.path.isdir(d):
                continue
            for fn in sorted(os.listdir(d)):
                if not fn.lower().endswith('.' + kind):
                    continue
                src = os.path.join(d, fn)
                try:
                    xml, got_kind, w = meta2xml.convert(src, names)
                except Exception as ex:
                    msg = f'{type(ex).__name__}: {ex}'
                    why[msg] = why.get(msg, 0) + 1
                    fail += 1
                    continue
                stem = fn[:-(len(kind) + 1)]
                with open(os.path.join(d, f'{stem}.{got_kind}.xml'), 'w',
                          encoding='utf-8') as fh:
                    fh.write(xml)
                unresolved += w.warn.get('unresolved asset-name hash', 0)
                ok += 1

    print(f'converted {ok} ytyp/ymap -> XML, {fail} failed')
    if unresolved:
        print(f'  unresolved name hashes: {unresolved:,} -> emitted as hash_XXXXXXXX. The '
              f'ymap<->ytyp join still holds (same hash both sides); only an assetName needs a '
              f'real name, and those come from the asset files themselves.')
    for m, n in sorted(why.items(), key=lambda kv: -kv[1])[:8]:
        print(f'  {n:5}x  {m}')
    print('\n  next: quarry.py resolve --out "<project>"   (flatten for RUDE)')
    return 0


def cmd_textures(a):
    """Keep only the texture pixels something actually references.

    ⛔ THE PROBLEM THIS EXISTS FOR, MEASURED 2026-07-29: `--textures png` decodes a PNG for EVERY
    texture in the game - 335,452 files, 86.0 GB - because nothing ever asks which dictionaries the
    drawables actually use. On a real project the answer was **2,229 of 38,644**: 75.6 GB of the
    decode was for textures no mesh has ever named. That filled a 977 GB volume to zero bytes and
    stopped work.

    The reference is not a guess: a drawable's XML names its textures in its shader parameters, and
    every `.ytd.xml` manifest lists the textures it contains. Joining those two gives the exact set,
    which is the same computation RUDE's own txd import list uses.

    --prune deletes the pixels for everything unreferenced. It is safe by construction: the source
    is the operator's own game install, so a pruned texture is re-extractable, never lost. ⚠ It must
    delete from BOTH the slots AND `_resolved`, because `resolve` HARDLINKS - removing one link
    frees nothing (measured: deleting 75.6 GB of slot copies freed ~15 GB until the resolved links
    went too).
    """
    out = a.out
    if not os.path.isdir(out):
        print(f'no project folder at {out}')
        return 1
    resolved = os.path.join(out, '_resolved')
    slots = [os.path.join(out, s) for s in precedence_slots(out)]
    # ⚠ TWO DIFFERENT ROOT SETS, and conflating them is both slow and wrong.
    # READING references: `_resolved` alone when it exists - it IS the corpus contract (the
    # winning copy of every asset RUDE can reach). Adding the slots re-reads the SAME BYTES
    # (resolve hardlinks) for zero new references: ~115 GB of XML scanned twice.
    # DELETING pixels: every root, because a hardlink is not freed until its LAST name is gone.
    ref_roots = [resolved] if os.path.isdir(resolved) else list(slots)
    prune_roots = ([resolved] if os.path.isdir(resolved) else []) + slots

    tex_re = re.compile(r'type="Texture">\s*<Name>([^<]+)</Name>', re.S)
    name_re = re.compile(r'<Name>([^<]+)</Name>')

    # 1) every texture NAME the drawables ask for
    wanted = set()
    drawables = 0
    for root in ref_roots:
        for kind in ('ydr', 'ydd', 'yft'):
            d = os.path.join(root, kind)
            if not os.path.isdir(d):
                continue
            for fn in os.listdir(d):
                if not fn.lower().endswith('.xml'):
                    continue
                try:
                    with open(os.path.join(d, fn), encoding='utf-8', errors='replace') as fh:
                        txt = fh.read()
                except OSError:
                    continue
                drawables += 1
                wanted.update(t.strip().lower() for t in tex_re.findall(txt))
    print(f'drawables scanned : {drawables:,}   distinct textures referenced: {len(wanted):,}')

    # 2) which dictionaries hold them
    needed = set()
    manifests = 0
    for root in ref_roots:
        d = os.path.join(root, 'ytd')
        if not os.path.isdir(d):
            continue
        for fn in os.listdir(d):
            if not fn.lower().endswith('.ytd.xml'):
                continue
            manifests += 1
            try:
                with open(os.path.join(d, fn), encoding='utf-8', errors='replace') as fh:
                    txt = fh.read()
            except OSError:
                continue
            stem = fn[:-8].lower()
            if any(n.strip().lower() in wanted for n in name_re.findall(txt)):
                needed.add(stem)
    print(f'ytd manifests     : {manifests:,}   referenced dictionaries: {len(needed):,}')

    # 3) measure, and prune when asked
    keep_b = drop_b = 0
    keep_n = drop_n = 0
    victims = []
    # ⚠ COUNT EACH BYTE ONCE. A file reachable as both `20_dlc/.../x.png` and `_resolved/.../x.png`
    # is ONE file with two names - charging it twice is the same error that made robocopy report
    # this drive as far fuller than it is. Size is credited to the first name seen; every later
    # name still goes on the delete list, because the bytes are not freed until the last one goes.
    seen_ids = set()

    def charge(fp):
        try:
            st = os.stat(fp)
        except OSError:
            return 0
        key = (st.st_dev, st.st_ino)
        if st.st_ino and key in seen_ids:
            return 0
        if st.st_ino:
            seen_ids.add(key)
        return st.st_size
    for root in prune_roots:
        d = os.path.join(root, 'ytd')
        if not os.path.isdir(d):
            continue
        for entry in os.scandir(d):
            if not entry.is_dir():
                continue
            sz = 0
            n_new = 0
            pngs = []
            for dp, _, fs in os.walk(entry.path):
                for f in fs:
                    if not f.lower().endswith(('.png', '.dds')):
                        continue
                    fp = os.path.join(dp, f)
                    b = charge(fp)
                    sz += b
                    if b:
                        n_new += 1
                    pngs.append(fp)
            # File COUNTS follow the same once-per-inode rule as bytes (charge() returns 0 for a
            # name already seen), or the report says "72,815 files" for 37,144 files with two
            # names each - numbers that quietly contradict the byte column beside them.
            if entry.name.lower() in needed:
                keep_b += sz
                keep_n += n_new
            else:
                drop_b += sz
                drop_n += n_new
                victims.append(pngs)
    print(f'pixels REFERENCED : {keep_b / 1e9:7.1f} GB ({keep_n:,} files)')
    print(f'pixels UNUSED     : {drop_b / 1e9:7.1f} GB ({drop_n:,} files)')
    if not a.prune:
        print('\n(report only - pass --prune to delete the unused pixels. The source is your own '
              'game install, so anything pruned is re-extractable.)')
        return 0
    # ⛔ AN EMPTY REFERENCE SET IS A BROKEN QUESTION, NOT AN ANSWER OF "NOTHING IS USED".
    # A binary-only filebase (--xml never run, e.g. RUDE_Filebase_Test2) has no drawable XML to
    # read, so `wanted` comes back empty, every dictionary looks unreferenced, and a naive --prune
    # would cheerfully delete EVERY texture in the project. Refuse instead: this failure mode is
    # not recoverable in one step, and "I found no evidence" must never be silently promoted to
    # "there is nothing worth keeping".
    if not drawables or not manifests:
        print('\n⛔ REFUSING TO PRUNE: scanned %d drawables and %d ytd manifests. With no drawable'
              ' XML to read, every dictionary looks unreferenced and this would delete them all.'
              '\n   Run `quarry extract --xml` then `quarry resolve` for this project first.'
              % (drawables, manifests))
        return 1
    removed = 0
    for pngs in victims:
        for fp in pngs:
            try:
                os.remove(fp)
                removed += 1
            except OSError:
                pass
    print(f'\npruned {removed:,} files, {drop_b / 1e9:.1f} GB freed '
          f'(slots AND _resolved - hardlinks mean both must go)')
    return 0


def cmd_resolve(a):
    """Flatten the precedence tree into `_resolved/<type>/` - ONE build-accurate file per name.

    ⭐ WHY THIS EXISTS: RUDE reads a FLAT corpus (`ImportMapArea` globs `<root>/ytyp/*.xml`,
    `<root>/ymap/<prefix>*.xml` and looks up `<root>/ydr/<assetName>.ydr.xml`), while extraction
    writes numbered precedence slots. Without this step a QUARRY project folder cannot be opened
    by the plugin at all - foundation step 3 - and the two halves silently disagree, exactly the
    way emitting binary-vs-XML did. Resolving is QUARRY's job because QUARRY is what knows load
    order; the DCC should not have to.

    Point RUDE's CorpusRoot at `<project>/_resolved`. Hardlinks by default, so a whole-game
    resolve costs almost no extra disk; falls back to copying when the filesystem refuses.
    """
    out = a.out
    if not os.path.isdir(out):
        print(f'no project folder at {out}')
        return 1
    want = set(t.strip().lower() for t in a.types.split(',')) if a.types else None
    dest_root = os.path.join(out, '_resolved')
    slots = precedence_slots(out)
    if not slots:
        print(f'no precedence slots under {out} - run `extract` first')
        return 1

    # name -> (slot it came from). Walking slots in ascending order means the LAST writer wins,
    # which is the game's own rule; `overridden` counts how often that actually mattered.
    winner, overridden, ambiguous = {}, 0, 0
    for slot in slots:
        slot_dir = os.path.join(out, slot)
        for type_dir in sorted(os.listdir(slot_dir)):
            if want is not None and type_dir.lower() not in want:
                continue
            tp = os.path.join(slot_dir, type_dir)
            if not os.path.isdir(tp):
                continue
            for fname in sorted(os.listdir(tp)):
                if os.path.isdir(os.path.join(tp, fname)):
                    continue          # sidecar folders travel with their XML, handled below
                stem, ext = split_type_ext(fname)
                if '~' in stem:
                    # a WITHIN-slot basename collision: genuinely two different assets sharing
                    # one name. Which is canonical is unknowable from here, so the un-suffixed
                    # copy wins and the alternates are COUNTED, not silently flattened away.
                    ambiguous += 1
                    continue
                key = (type_dir, fname)
                if key in winner:
                    overridden += 1
                winner[key] = slot

    linked = copied = sidecars = 0
    for (type_dir, fname), slot in sorted(winner.items()):
        src = os.path.join(out, slot, type_dir, fname)
        dst = os.path.join(dest_root, type_dir, fname)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if os.path.exists(dst):
            os.remove(dst)
        try:
            if a.copy:
                raise OSError('copy requested')
            os.link(src, dst)
            linked += 1
        except OSError:
            shutil.copy2(src, dst)
            copied += 1
        # a converted asset's payload folder must follow its winning XML or the XML points at
        # nothing (ytd) - resolve it from the SAME slot, never from a mix
        side_src = os.path.join(out, slot, type_dir, split_type_ext(fname)[0])
        if os.path.isdir(side_src):
            side_dst = os.path.join(dest_root, type_dir, split_type_ext(fname)[0])
            if os.path.isdir(side_dst):
                shutil.rmtree(side_dst)
            os.makedirs(side_dst, exist_ok=True)
            for pf in sorted(os.listdir(side_src)):
                s, d = os.path.join(side_src, pf), os.path.join(side_dst, pf)
                try:
                    if a.copy:
                        raise OSError('copy requested')
                    os.link(s, d)
                except OSError:
                    shutil.copy2(s, d)
                sidecars += 1

    per_type = {}
    for (type_dir, _f) in winner:
        per_type[type_dir] = per_type.get(type_dir, 0) + 1
    with open(os.path.join(dest_root, '_RESOLVED.json'), 'w') as f:
        json.dump({'quarryVersion': 1,
                   'note': 'Flat build-accurate view of the precedence tree. Point RUDE\'s '
                           'CorpusRoot here.',
                   'slotsInAscendingPrecedence': slots,
                   # Carried from the project manifest rather than hardcoded: whether the winner of
                   # a contested name is TRUSTWORTHY depends entirely on whether the DLC order came
                   # from the game's own dlclist.xml, and a consumer needs to know which it got.
                   'dlcOrderAuthoritative': manifest_flag(out),
                   'counts': {'files': len(winner), 'overriddenByHigherSlot': overridden,
                              'withinSlotAlternatesSkipped': ambiguous, 'sidecars': sidecars},
                   'perType': per_type,
                   'winners': {f'{t}/{n}': s for (t, n), s in sorted(winner.items())}},
                  f, indent=1)

    print(f'resolved -> {dest_root}')
    print(f'  slots walked (ascending precedence): {len(slots)}')
    print(f'  files: {len(winner):,}   ' + '  '.join(f'{t}={n:,}' for t, n in sorted(per_type.items())))
    print(f'  overridden by a higher slot: {overridden:,}   (this is precedence doing its job)')
    print(f'  pixel sidecars carried: {sidecars:,}')
    print(f'  hardlinked {linked:,}, copied {copied:,}')
    if ambiguous:
        print(f'  ⚠ within-slot name alternates SKIPPED: {ambiguous:,} - the un-suffixed copy won.'
              f' They remain in the precedence tree; see _RESOLVED.json')
    print(f'\n  point RUDE at: {dest_root}')
    return 0


def cmd_scan(a):
    title, exe = detect_title(a.game)
    base, upd, dlc = find_sources(a.game)
    print(f'title    : {title}   exe: {exe or "?"}')
    print(f'base rpfs: {len(base)}   update rpfs: {len(upd)}   dlc packs: {len(dlc)}')
    print(f'oodle    : {oodle_dll(a.game, getattr(a, "oodle", None)) or "not found"}')
    enc = {}
    for n in base[:60]:
        try:
            with open(os.path.join(a.game, n), 'rb') as f:
                m, c, nl, e = struct.unpack('<4sIII', f.read(16))
            enc[e] = enc.get(e, 0) + 1
        except Exception:
            pass
    for e, c in enc.items():
        kind = {ENC_OPEN: 'OPEN', ENC_AES: 'AES', ENC_NG: 'NG'}.get(e, '?')
        print(f'  encryption 0x{e:08x} ({kind}) x{c}')
    return 0


def cmd_init(a):
    title, exe = detect_title(a.game)
    base, upd, dlc = find_sources(a.game)
    # Best-effort authoritative order here too: the slot NAMES encode load order, so getting it
    # right at init avoids a tree whose folder numbering contradicts the manifest.
    keys = tables = None
    try:
        import contextlib
        import io as _io
        import keyderive
        with contextlib.redirect_stdout(_io.StringIO()):
            raw_k, raw_t = keyderive.acquire(a.game, getattr(a, 'keys', None),
                                             getattr(a, 'magic', None))
        keys, tables = ngcrypto.keys_from_bytes(raw_k), ngcrypto.tables_from_bytes(raw_t)
    except Exception:
        pass
    dlc, authoritative = order_dlc(dlc, read_dlclist(a.game, keys, tables))
    names = [os.path.basename(d) for d in dlc]
    slot_dirs(a.out, len(base), names)
    write_manifest(a.out, a.game, title, exe, base, names, authoritative)
    print(f'project ready: {a.out}')
    print(f'  {len(base)} base archives, {len(dlc)} dlc slots, title={title}')
    print('  dlc order: ' + ('authoritative (dlclist.xml)' if authoritative else 'HEURISTIC'))
    return 0


def cmd_extract(a):
    title, exe = detect_title(a.game)
    base, upd, dlc = find_sources(a.game)

    # ---- key acquisition: NO --keys required for a normal user -------------------------------
    # Priority: existing key files (fast / the option-B path) -> the bundled game-gated blob opened
    # with the AES key found in the user's OWN executable. See docs/FOUNDATION.md §"DECIDED".
    # ⚠ ORDER MATTERS: this now runs BEFORE the project tree is written, because reading the game's
    # real DLC load order out of update.rpf needs the keys, and the tree encodes that order in its
    # folder names - building it first would bake in the guess.
    keys = tables = None
    try:
        import keyderive
        raw_k, raw_t = keyderive.acquire(a.game, a.keys, getattr(a, 'magic', None))
        keys, tables = ngcrypto.keys_from_bytes(raw_k), ngcrypto.tables_from_bytes(raw_t)
    except Exception as e:
        print(f'keys     : UNAVAILABLE - {e}')
        print('keys     : encrypted archives will be SKIPPED (nothing will be silently mis-read)')

    dlc, authoritative = order_dlc(dlc, read_dlclist(a.game, keys, tables))
    print('dlc order: ' + ('from the game\'s own dlclist.xml (authoritative)' if authoritative
                           else 'HEURISTIC - dlclist.xml unreadable, so which DLC wins is a guess'))
    names = [os.path.basename(d) for d in dlc]
    slot_dirs(a.out, len(base), names)
    write_manifest(a.out, a.game, title, exe, base, names, authoritative)

    dll = oodle_dll(a.game, getattr(a, 'oodle', None))
    oodle = None
    if dll:
        import ctypes
        lib = ctypes.CDLL(dll)
        fn = lib.OodleLZ_Decompress
        fn.restype = ctypes.c_int64

        def oodle(src, outsz):
            buf = ctypes.create_string_buffer(outsz)
            n = fn(ctypes.c_char_p(src), ctypes.c_int64(len(src)), buf,
                   ctypes.c_int64(outsz), 0, 0, 0, None, None, None, None, None, None, 3)
            if n <= 0:
                raise RuntimeError('oodle failed')
            return buf.raw[:n]

    jobs = [(os.path.join(a.game, n), '00_base') for n in base]
    jobs += [(p, '10_update') for p in upd]
    for i, d in enumerate(dlc):
        # ⛔⛔ A PACK CAN SHIP SEVERAL ARCHIVES, NOT JUST dlc.rpf. Measured 2026-07-29 on a real
        # install: mpheist4 (Cayo Perico) carries dlc.rpf + dlc1.rpf + dlc2.rpf, mpsecurity and
        # mpbattle and mptuner each carry a dlc1.rpf - **7.2 GB of DLC that this loop silently
        # skipped**, which is why Cayo and the security DLC extracted to ZERO files while the run
        # still reported success. Take every dlc*.rpf, in name order so dlc.rpf sorts first and
        # keeps its historical precedence within the pack.
        found = sorted(
            (f for f in os.listdir(d)
             if f.lower().startswith('dlc') and f.lower().endswith('.rpf')
             and os.path.isfile(os.path.join(d, f))),
            key=lambda f: (len(f), f.lower()))
        if not found:
            print(f'  ⚠ {names[i]}: no dlc*.rpf found in {d} - nothing to extract from this pack')
            continue
        if len(found) > 1:
            print(f'  {names[i]}: {len(found)} archives -> {", ".join(found)}')
        for f in found:
            jobs.append((os.path.join(d, f),
                         os.path.join('20_dlc', '%03d_%s' % (i + 1, names[i]))))
    if a.only:
        jobs = [j for j in jobs if os.path.basename(j[0]).lower() == a.only.lower()]

    want = None
    if getattr(a, 'types', None):
        want = {t.strip().lstrip('.').lower() for t in a.types.split(',') if t.strip()}
        print(f'type filter : {sorted(want)}')
    max_depth = getattr(a, 'max_depth', 2)
    print(f'max depth   : {max_depth}   (nested .rpf are descended into)')

    # ⚠ ImportYtd loads <PixelFolder>/<TexName>.png, NOT the .dds - so a --xml ytd run without the
    # decoders emits a texture folder the plugin cannot read. Say so up front rather than letting it
    # look like it worked.
    if getattr(a, 'xml', False) and (want is None or 'ytd' in want):
        try:
            import ytd2xml
            mode = getattr(a, 'textures', 'both')
            parts = ([] if mode == 'png' else ['.dds']) + ([] if mode == 'dds' else ['.png'])
            if mode == 'dds':
                print('textures    : ytd -> .ytd.xml + .dds  ⚠ NO .png, and ImportYtd reads .png '
                      '- this folder is an archive, not an importable one')
            elif ytd2xml.png_available():
                print(f'textures    : ytd -> .ytd.xml + {" + ".join(parts)}'
                      f'   (ImportYtd reads the .png)')
            else:
                print('textures    : ⚠ texture2ddecoder/Pillow NOT installed - ytd folders will '
                      'hold .dds ONLY, and ImportYtd reads .png. `pip install texture2ddecoder '
                      'Pillow` to make the texture lane usable.')
        except Exception as e:
            print(f'textures    : ytd converter unavailable - {e}')

    total = skipped = 0
    stats = {}
    for path, slot in jobs:
        try:
            r = Rpf(path, keys, tables)
            r.read_toc()
        except KeyError as e:
            print(f'  SKIP {os.path.basename(path)}: {e}')
            skipped += 1
            continue
        except Exception as e:
            print(f'  FAIL {os.path.basename(path)}: {e}')
            skipped += 1
            continue
        if not r.sane():
            print(f'  SKIP {os.path.basename(path)}: TOC did not decode (wrong keys?)')
            skipped += 1
            continue
        n = 0
        for name, blob in walk_archive(r, oodle, 0, max_depth, stats, os.path.basename(path)):
            if want is not None and type_of(name) not in want:
                continue
            try:
                # ⭐ --xml: convert to the RAGE interchange XML that RUDE's importer already reads,
                # so the pipeline is connected without any UE-side work. Binary is kept when a
                # converter for that type does not exist yet.
                if getattr(a, 'xml', False):
                    try:
                        conv = to_interchange_xml(name, blob,
                                                 getattr(a, 'textures', 'both'))
                        if conv is not None:
                            xml_name, xml_bytes, extras = conv
                            written = file_into(a.out, slot, xml_name, xml_bytes, stats)
                            # The pixel folder must follow the XML that was ACTUALLY written: on
                            # a basename collision the XML becomes foo~1.ytd.xml, and a sidecar
                            # folder still called `foo` would hand one dictionary's XML another
                            # dictionary's textures - silently, since both are valid files.
                            folder = split_type_ext(written)[0]
                            for rel, payload in extras:
                                rel = folder + rel[rel.index('/'):]
                                sidecar_into(a.out, slot, type_of(name), rel, payload)
                                stats['xml_sidecars'] = stats.get('xml_sidecars', 0) + 1
                            stats['xml_ok'] = stats.get('xml_ok', 0) + 1
                            n += 1
                            continue
                    except Exception as ex:
                        stats['xml_failed'] = stats.get('xml_failed', 0) + 1
                        stats.setdefault('xml_errors', []).append(f'{name}: {type(ex).__name__}: {ex}')
                        # fall through and keep the binary rather than losing the asset
                file_into(a.out, slot, name, blob, stats)
                n += 1
            except Exception as ex:
                stats['failed'] = stats.get('failed', 0) + 1
                stats.setdefault('failures', []).append(f'{name}: {type(ex).__name__}')
        total += n
        print(f'  {os.path.basename(path):<28} -> {slot:<28} {n} files')

    print(f'\nextracted {total} files; {skipped} archive(s) skipped')
    print(f'nested archives opened: {stats.get("nested_opened", 0)}'
          f'   failed to open: {stats.get("nested_failed", 0)}'
          f'   past max-depth: {stats.get("nested_skipped", 0)}')
    if getattr(a, 'xml', False):
        print(f'XML converted: {stats.get("xml_ok", 0)}   conversion failed (kept binary): '
              f'{stats.get("xml_failed", 0)}'
              + (f'   pixel sidecars: {stats["xml_sidecars"]}' if stats.get('xml_sidecars')
                 else ''))
        for line in stats.get('xml_errors', [])[:8]:
            print(f'    {line}')
    print(f'name collisions (kept first, suffixed the rest): {stats.get("collisions", 0)}')
    print(f'files that failed to extract: {stats.get("failed", 0)}')
    for line in stats.get('failures', [])[:15]:
        print(f'    {line}')
    if len(stats.get('failures', [])) > 15:
        print(f'    ... and {len(stats["failures"]) - 15} more')
    return 0


def main():
    ap = argparse.ArgumentParser(prog='quarry')
    sub = ap.add_subparsers(dest='cmd', required=True)
    for name, fn in (('scan', cmd_scan), ('init', cmd_init), ('extract', cmd_extract)):
        p = sub.add_parser(name)
        p.add_argument('--game', required=True)
        p.add_argument('--out')
        p.add_argument('--keys')
        p.add_argument('--only', help='limit to one archive basename, e.g. x64a.rpf')
        p.add_argument('--types', help='comma-separated types to KEEP, e.g. '
                                      'ydr,ybn,ytyp,ymap,ytd. Omit = everything (~376k files '
                                      'for a full run - you almost always want this filter)')
        p.add_argument('--oodle', help='path to your own oo2core_*_win64.dll. A GTA V Legacy '
                                      'install does not ship one (Enhanced does); QUARRY binds '
                                      'your local file and never ships or copies it')
        p.add_argument('--magic', help='override the bundled game-gated key blob. The blob is inert '
                                      'without an installed copy of the game to open it')
        p.add_argument('--xml', action='store_true',
                       help='convert resources to the RAGE interchange XML on the way out, which is what '
                            'the RUDE importer reads (ydr + ytd today; ytyp/ymap pending). Types with '
                            'no converter yet are written as binary, never dropped')
        p.add_argument('--textures', choices=('both', 'png', 'dds', 'none'), default='both',
                       help='which ytd pixel sidecars to write. png = what ImportYtd loads; '
                            'dds = the lossless repackage. DISK: measured on x64i, 7,148 textures '
                            '= 1.62 GB dds + 2.35 GB png, so a whole-game run with "both" needs '
                            '~56 GB of textures on top of ~38 GB of ydr.xml. ⭐ none = write the '
                            '.ytd.xml MANIFEST ONLY and decode nothing: the manifests are ~0.1 GB '
                            'for the whole game, and they are all you need to answer WHICH '
                            'dictionaries matter. Pair with `quarry textures` to decode or prune '
                            'only what the drawables actually reference.')
        p.add_argument('--max-depth', type=int, default=2, dest='max_depth',
                       help='how deep to descend into nested .rpf (default 2; the game keeps '
                            'nearly all map assets one level down)')
        p.set_defaults(fn=fn)

    # `resolve` reads only the project folder, so it needs no --game and no keys
    pr = sub.add_parser('resolve', help='flatten the precedence tree into _resolved/ - the FLAT '
                                        'corpus layout RUDE actually reads')
    pr.add_argument('--out', required=True, help='the project folder built by init/extract')
    pr.add_argument('--types', help='comma-separated type folders to resolve, e.g. ydr,ytd,ytyp,ymap')
    pr.add_argument('--copy', action='store_true',
                    help='copy instead of hardlinking (use when the destination is another volume)')
    pr.set_defaults(fn=cmd_resolve)

    pt = sub.add_parser('textures', help='report - and with --prune, delete - the texture pixels no '
                                        'drawable references (run AFTER meta/resolve)')
    pt.add_argument('--out', required=True, help='the project folder built by init/extract')
    pt.add_argument('--prune', action='store_true',
                    help='actually delete the unreferenced png/dds sidecars. Safe: the source is '
                         'your own game install, so anything pruned is re-extractable')
    pt.set_defaults(fn=cmd_textures)

    pm = sub.add_parser('meta', help='convert binary ytyp/ymap to interchange XML (run AFTER '
                                     'extract, so the joaat name table is complete)')
    pm.add_argument('--out', required=True, help='the project folder built by init/extract')
    pm.set_defaults(fn=cmd_meta)

    # `doctor` must run with NOTHING configured - it is what a new user calls first, so --game is
    # optional here even though every other command requires it.
    pd = sub.add_parser('doctor', help='preflight: what on this machine is ready, and what to fix')
    pd.add_argument('--game', help='your game install, to check archives + key derivation')
    pd.add_argument('--out', help='a project path, to check free disk on the right volume')
    pd.add_argument('--keys')
    pd.add_argument('--magic')
    pd.add_argument('--oodle')
    pd.set_defaults(fn=cmd_doctor)

    a = ap.parse_args()
    if a.cmd in ('init', 'extract') and not a.out:
        ap.error('--out is required')
    return a.fn(a)


if __name__ == '__main__':
    # A default Windows console is cp1252, which cannot encode the report glyphs - a whole-game
    # run then dies at the FINAL SUMMARY PRINT (hit 2026-07-28: resolve finished its work and
    # crashed printing its own recap). Degrade characters, never the run.
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(errors='replace')
        except Exception:
            pass
    sys.exit(main())
