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
# The within-slot collision suffix file_into writes: `<stem>~<n>`. ANCHORED - a tilde anywhere
# else in a name is part of the asset's real name and must not be read as an alternate.
_ALT_RE = re.compile(r'~\d+$')

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
    def __init__(self, path, keys=None, tables=None, data=None, name=None, aes_key=None):
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
        self.aes_key = aes_key
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
            # ⭐⭐ AND THEN THE "MISSING CAPABILITY" TURNED OUT NOT TO EXIST (2026-08-03).
            # The 32-byte key is the SAME PC AES key keyderive.find_aes_key() already pulls from
            # the user's own executable on every run to open the magic blob - it is also the
            # ARCHIVE key, one AES-256-ECB pass over the TOC + name table. The refusal above was
            # a claim of ABSENCE that the code itself disproved, and it cost the corpus 2,075
            # files nobody counted (1,886 ydr + 84 yft + 18 ytyp + 5 ymap across 34 archives).
            # ⛔ THE LESSON, and it is the same one as bit 31: "not yet recovered" described what
            # WE HAD LOOKED FOR, not what was available. A capability gap asserted in a comment
            # is not evidence - go and try it.
            if self.aes_key is None:
                raise KeyError('AES-encrypted archive: no AES key supplied to Rpf(aes_key=). '
                               'Pass keyderive.acquire_aes(game_root) - the key comes from the '
                               "operator's own executable, the same one the NG path uses")
            import keyderive
            return keyderive.aes256_ecb_decrypt(blob[:len(blob) // 16 * 16], self.aes_key)
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
        # ⛔ NEVER WRITE THE COMPRESSED BYTES AS IF THEY WERE THE FILE (2026-08-03).
        # This used to `return got if got is not None else raw` - so an entry that decoded no way
        # at all was written to disk as its own still-compressed body, with no counter and no way
        # to tell it apart from a legitimately stored file. A corrupt file that looks like a
        # success is strictly worse than a loud refusal: the refusal is counted in `failures` and
        # the file is simply absent, which every downstream check can see.
        if got is None:
            raise ValueError('binary entry did not inflate plain, NG-decrypted, or via Oodle - '
                             'refusing to write the compressed bytes as if they were the file')
        # And the length the TOC declares is a free integrity check we were not taking.
        if e['usize'] and len(got) != e['usize']:
            raise ValueError(f'binary entry inflated to {len(got)} B but its TOC declares '
                             f'{e["usize"]} B - refusing a body that disagrees with its own entry')
        return got


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


def embedded_texture_sidecars(res, stem, textures, base=0, bases=None):
    """A drawable's OWN texture dictionary (ShaderGroup+0x08) as sidecars: the
    `<stem>__embedded.ytd.xml` manifest plus pixel files. Shared by the ydr, yft AND ydd branches
    - the full naming contract (why `__embedded`, why a sibling dictionary at all) is documented
    at the ydr branch of to_interchange_xml, which established it.

    `bases` = several drawable offsets to merge into ONE sibling dictionary, which is what a ydd
    needs: a drawable DICTIONARY holds many drawables and each may carry its own textures.
    De-duplicated by name, because entries in one dictionary routinely share a texture.
    """
    import ydr2xml
    import ytd2xml
    emb, seen = [], set()
    for b in (bases if bases is not None else [base]):
        for t in ydr2xml.embedded_textures(res, base=b):
            k = t['name'].lower()
            if k not in seen:
                seen.add(k)
                emb.append(t)
    if not emb:
        return []
    emb_stem = stem + '__embedded'
    sidecars = [(emb_stem + '.ytd.xml', ytd2xml.to_xml(emb).encode('utf-8'))]
    if textures != 'none':
        sidecars.extend(ytd2xml.sidecars(emb, emb_stem, want_png=(textures != 'dds'),
                                         want_dds=(textures != 'png')))
    return sidecars


def to_interchange_xml(name, blob, textures='both', stats=None):
    """One asset -> (xml filename, xml bytes, [(sidecar relpath, bytes)]), or None when no
    converter exists for that type yet.

    THE CONTRACT: RUDE's importer reads the RAGE interchange XML, so this is where a raw archive
    resource becomes something the plugin can consume. Registering a type here is all that is
    needed to connect it end-to-end - see quarry/README.md "Export EVERYTHING through the XML
    pipeline".

    `stats` (optional dict) receives counters for anything this function declines to emit -
    a downgrade with no counter is indistinguishable from full success, and that is how the
    extras lane stayed invisible.
    """
    t = type_of(name)
    stem = os.path.splitext(name)[0]
    if t == 'ydr':
        import ydr2xml, ytd2xml
        res = ydr2xml.Res.from_bytes(blob)
        inner = res.cstr(res.ptr(0xA8)) or (stem + '.#dr')
        # ⭐ A drawable can carry its OWN textures (ShaderGroup+0x08). 33.9% of them do, and 18.2%
        # of all texture requests are satisfiable only from there - see ydr2xml.embedded_textures.
        # The XML lists them; these sidecars are the pixels behind those names, written to the same
        # "<stem>/" folder convention ImportYtd already loads from, so the pair is self-describing.
        emb = ydr2xml.embedded_textures(res)
        sidecars = []
        if emb:
            # ⭐ THE EMBEDDED DICTIONARY IS ALSO WRITTEN AS A SIBLING "<stem>.ytd.xml".
            # Deliberate design choice: it makes the drawable's own textures a NORMAL texture
            # dictionary on disk, so the existing, in-engine-proven ImportYtd consumes them with no
            # new import code - the alternative was duplicating ~80 lines of texture-import C++ that
            # would then be a second thing to keep correct. The contract is discoverable by name:
            # for any X.ydr.xml, an X.ytd.xml beside it holds X's embedded textures, with pixels in
            # the X/ folder - the same pairing ImportYtd already expects.
            # ⛔ NAME IT ".embedded.ytd.xml", NOT "<stem>.ytd.xml". file_into files by EXTENSION,
            # so a sibling called X.ytd.xml lands in <slot>/ytd/ - the same folder as the STANDALONE
            # X.ytd, and a drawable and a texture dictionary sharing a name is not rare, it is the
            # normal case (an archetype's textureDictionary is usually named after the drawable).
            # The collision path then keeps the first and renames the loser to X~1.ytd.xml, which
            # nothing looks for: the embedded textures would vanish silently. The ".embedded" infix
            # cannot collide with a real dictionary name and stays discoverable - for X.ydr.xml, look
            # for X.embedded.ytd.xml with its pixels in X.embedded/.
            # ⛔ "__embedded", NOT ".embedded". The stem becomes a UE PACKAGE PATH segment
            # (/Game/RUDE/Textures/<stem>/...), and a DOT IS ILLEGAL in a long package name - UE
            # uses it to separate package from object. ImportYtd's IsValidLongPackageName check
            # therefore rejected every texture and `continue`d SILENTLY: 1,943 manifests imported
            # with 0 textures and no error (2026-07-30). A double underscore is equally
            # collision-proof against a real dictionary name and is a legal path segment.
            sidecars.extend(embedded_texture_sidecars(res, stem, textures))
        return stem + '.ydr.xml', ydr2xml.to_xml(res, inner).encode('utf-8'), tuple(sidecars)
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
    if t == 'ybn':
        # ⛔ THIS BRANCH DID NOT EXIST until 2026-07-29, and its absence is the whole lesson.
        # ydr2xml.boundsfile_lines() has been BUILT AND ORACLE-VALIDATED the entire time - 183/183
        # name-matched reference exports, zero differences - but nothing ever CALLED it, so
        # `extract --types ybn --xml` wrote raw binary and the capability was unreachable. It was
        # written as the oracle for the embedded-<Bounds> derivation and then left dangling.
        # A capability that exists but is not wired is indistinguishable from one that was never
        # built - which is exactly how it came to be described as "the ybn converter is unbuilt".
        # Check the WIRING, never the presence of a file.
        import ydr2xml
        res = ydr2xml.Res.from_bytes(blob)
        body = '\n'.join(ydr2xml.boundsfile_lines(res, stem)) + '\n'
        return stem + '.ybn.xml', body.encode('utf-8'), ()
    if t == 'ydd':
        import ydd2xml
        res = ydd2xml.Res.from_bytes(blob)
        # names={}: the joaat reverse table is a meta-pass artifact and does not exist at extract
        # time, so entry names are emitted hash_%08X here and RESOLVED LATER by `quarry meta`
        # (the same second pass that names ytyp/ymap hashes). Dictionary joins are hash-to-hash,
        # so nothing downstream depends on the resolution - it is for humans and by-name lookups.
        xml, _n = ydd2xml.to_xml(res, {})
        # ⭐ A DICTIONARY'S ENTRIES CARRY EMBEDDED TEXTURES TOO (2026-08-03). This branch was the
        # last of the three drawable lanes still hardcoding `[]`: ydr got sidecars 07-30, yft
        # 07-31, and ydd was simply never revisited - the same "built for one lane, never wired
        # for the next" shape as the ybn converter and the yft extras before it.
        # The cost was not zero-but-invisible: `drawable_lines` emits <ShaderGroup>
        # <TextureDictionary> for EVERY entry, so a .ydd.xml NAMED textures whose pixels were
        # never written - the XML advertised files that do not exist. Measured over 600 real
        # dictionaries: 35.3% contain at least one entry with an embedded dictionary.
        # Each entry is a gtaDrawable at its own offset, so all of them are merged into ONE
        # sibling `<stem>__embedded.ytd.xml`, de-duplicated by name.
        try:
            bases = [off for _h, off in ydd2xml.entry_offsets(res)]
        except Exception:
            bases = []
        sidecars = embedded_texture_sidecars(res, stem, textures, bases=bases) if bases else []
        return stem + '.ydd.xml', xml.encode('utf-8'), sidecars
    if t == 'yft':
        # ⭐ EXTRAS ARE PIPELINE-WIRED (2026-07-30). yft2xml.convert() has emitted the skeleton,
        # the physics group/child join and one importable <stem>/<group>.ydr.xml sidecar per
        # geometry-bearing child since 07-28 - but this branch called the text-only to_xml()
        # wrapper and hardcoded [] for the sidecars, so `extract` could not produce any of it.
        # Same defect class as the ybn branch above: built, validated, unreachable.
        import yft2xml
        res = yft2xml.Res.from_bytes(blob)
        try:
            xml, sidecars = yft2xml.convert(res, stem, extras=True)
        except yft2xml.FragmentError as ex:
            # ⛔ COUNTED downgrade, never a silent one: an extras refusal (a value the emitter
            # has no measurement for) must not cost the map lane its visual drawable, but a
            # fallback with no counter would make "extras always work" indistinguishable from
            # "extras quietly failed everywhere".
            if stats is not None:
                stats['yft_extras_refused'] = stats.get('yft_extras_refused', 0) + 1
                stats.setdefault('yft_extras_errors', []).append(f'{name}: {ex}')
            xml, sidecars = yft2xml.convert(res, stem, extras=False)
        # ⭐ FRAGMENT EMBEDDED TEXTURES (2026-07-31). Same mechanism as the ydr branch, rebased
        # to the fragment's MAIN drawable: measured over all 6,026 base-game binary yft, 1,558
        # (25.9%) carry a dictionary at ShaderGroup+0x08 - 5,723 textures - and the sampled
        # carriers request ONLY textures that dictionary holds (9/9, 12/12, 1/1), i.e. exactly
        # the fragments that imported untextured before this. Child drawables have no
        # ShaderGroup of their own (they index the fragment's), so the main drawable's
        # dictionary is the whole story.
        dbase = yft2xml.main_drawable_base(res)
        if dbase is not None:
            sidecars = list(sidecars) + embedded_texture_sidecars(res, stem, textures,
                                                                  base=dbase)
        return stem + '.yft.xml', xml.encode('utf-8'), sidecars
    return None


def file_into(out_root, slot, name, blob, stats=None, skip_existing=False):
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
        # ⭐ RESUME: with skip_existing, an identical target name is treated as ALREADY DONE rather
        # than as a collision. Added 2026-07-30 after a whole-game extract was lost twice - once to a
        # double-writer, once because it had to be restarted from zero - and each restart is hours.
        # ⛔ OPT-IN ONLY, and never the default: the collision path exists to protect
        # build-accuracy (two same-named files in ONE slot are genuinely different assets and the
        # loser must be kept as ~N). Silently skipping them would quietly drop real data, so resume
        # is something the operator asks for when continuing a known-interrupted run.
        if skip_existing:
            # ⛔ 'ALREADY PRESENT' AND 'A DIFFERENT ASSET WITH THE SAME BASENAME' ARE NOT THE SAME
            # EVENT (2026-08-03). Both used to hit this branch, so on a resumed run the 2nd..Nth
            # distinct copy of a colliding name was DROPPED - and the summary still printed
            # `collisions: 0`, because the collision path never ran. Resume may only skip a file
            # whose bytes we would have written anyway; anything else falls through to the
            # collision path and is kept as ~N and counted.
            try:
                same = os.path.getsize(target) == len(blob)
            except OSError:
                same = False
            if same:
                if stats is not None:
                    stats['resumed'] = stats.get('resumed', 0) + 1
                return None
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
                # the AES key rides down the recursion: AES archives are always NESTED
                sub = Rpf(f'{path}/{name}', r.keys, r.tables, data=blob, name=name,
                          aes_key=getattr(r, 'aes_key', None))
                sub.read_toc()
                if not sub.sane():
                    raise ValueError('nested TOC did not decode')
            except Exception as ex:
                if stats is not None:
                    # ⛔ A KNOWN, EXPECTED SKIP IS NOT A FAILURE — separate buckets (2026-08-03).
                    # AES-encrypted archives (41 game-wide, all map set-pieces) landed in the SAME
                    # counter as genuine TOC-decode failures, so "failed to open: 41" was both the
                    # normal state AND what a real regression would look like. With the buckets
                    # split, `nested_aes_skipped == 0` becomes a usable regression gate for the
                    # AES work, and any non-zero `nested_failed` is a real problem again.
                    aes = isinstance(ex, KeyError) and 'AES-encrypted archive' in str(ex)
                    k = 'nested_aes_skipped' if aes else 'nested_failed'
                    stats[k] = stats.get(k, 0) + 1
                    if not aes:
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
    entry legitimately overrides an earlier one.

    ⛔ THE DLC LIST COMES FROM THE MANIFEST, NOT FROM listdir (2026-08-03). The numbered names
    encode load order ONLY if they all came from ONE extraction. This used to lexically sort
    whatever directories existed, and B:/RUDE_Filebase_Full held 175 dirs for 92 packs - 83 left
    over from an earlier HEURISTIC-ordered extract, so ordinal 001 existed twice (001_mpheist AND
    001_mpairraces) and the merged sort was NEITHER ordering. Precedence silently stopped meaning
    load order while `_RESOLVED.json` kept stamping dlcOrderAuthoritative: true - i.e. the one
    field a consumer checks to decide whether to trust the winner was lying.
    A directory not named by the manifest is REPORTED and excluded, never silently included.
    """
    slots = [s for s in ('00_base', '10_update') if os.path.isdir(os.path.join(out_root, s))]
    dlc_root = os.path.join(out_root, '20_dlc')
    if os.path.isdir(dlc_root):
        on_disk = {d for d in os.listdir(dlc_root)
                   if os.path.isdir(os.path.join(dlc_root, d))}
        packs = []
        try:
            with open(os.path.join(out_root, '_FILEBASE.json')) as f:
                packs = json.load(f).get('dlcPacks') or []
        except Exception:
            packs = []
        if packs:
            named = []
            for p in packs:
                d = '%03d_%s' % (p['order'], p['name']) if isinstance(p, dict) else str(p)
                if d in on_disk:
                    named.append(d)
            extra = sorted(on_disk - set(named))
            if extra:
                print(f'! {len(extra)} DLC director{"y" if len(extra) == 1 else "ies"} under '
                      f'20_dlc are NOT in this project\'s manifest and are EXCLUDED from '
                      f'precedence (stale from an earlier extract): '
                      + ', '.join(extra[:6]) + (' …' if len(extra) > 6 else ''))
            slots += [os.path.join('20_dlc', d) for d in named]
        else:
            # No manifest (hand-assembled folder): fall back to the lexical read, but SAY so -
            # the caller is entitled to know the ordering is unverified.
            print('! no _FILEBASE.json dlcPacks - DLC precedence falls back to a lexical sort of '
                  '20_dlc, which is only load order if one extraction produced every directory')
            slots += [os.path.join('20_dlc', d) for d in sorted(on_disk)]
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

    for mod, what in (('ydr2xml', 'ydr -> XML (+ ybn, embedded textures)'),
                      ('meta2xml', 'ytyp/ymap/ymt -> XML'),
                      ('ydd2xml', 'ydd -> XML (drawable dictionaries)'),
                      ('yft2xml', 'yft -> XML (fragments + extras sidecars)'),
                      ('meta_write', 'META writer (XML value model -> binary; standalone)'),
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
              '--types ydr,ydd,yft,ytd,ybn,ytyp,ymap,ymt')
        print('  Then:         quarry.py meta --out "<project>"   and   quarry.py resolve --out '
              '"<project>"')
    return 1 if bad else 0


def cmd_meta(a):
    """Convert every binary .ytyp/.ymap/.ymt in the project to interchange XML, then resolve
    the hash_%08X entry names that `extract` had to leave in the .ydd.xml files.

    ⭐ WHY THIS IS A SECOND PASS rather than part of `extract`: a ytyp stores its archetype and
    asset names as ONE-WAY joaat hashes, and the reverse table is built by hashing the asset
    FILENAMES the archives yield. During extraction most of those files have not landed yet, so
    converting inline would resolve far fewer names. Running after extraction means the table is
    complete and `assetName` - the one name that MUST resolve, because RUDE turns it into a
    `<CorpusRoot>/ydr/<assetName>.ydr.xml` lookup - resolves from the user's own data.
    The same argument covers ydd ENTRY names: they are joaat hashes of names that are usually
    asset filenames, so they resolve here or never.

    ⭐ .ymt was ADDED 2026-07-30: meta2xml has decoded CScenarioPointRegion the whole time, but
    this loop only walked ('ytyp', 'ymap') - so an extracted scenario .ymt stayed binary forever
    and the scenario lane needed hand-run conversions. Same defect class as the unwired ybn
    branch: the emitter existed, the pipeline stage did not. ⚠ Not every .ymt is META: the
    sp_manifest class is a PSO ('PSIN') container, which is COUNTED and skipped here, not failed
    (see pso_manifest.py for that format).

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

    ok = fail = pso = rbf = 0
    unresolved = 0
    why, noemit, warn_classes = {}, {}, {}
    # ⛔⛔ STALE OUTPUT IS INVISIBLE UNLESS SOMEONE LOOKS FOR IT (2026-08-04). This loop writes an
    # .xml ONLY on success, and never touches the file a previous run left behind - so a binary
    # that converted last week and FAILS today keeps its week-old .xml, `resolve` hardlinks that
    # into `_resolved`, and RUDE joins against a corpus that silently mixes converter generations.
    # HOW IT WAS FOUND: Layer-4 Area C measured 1,264 map entities landing as proxy cubes because
    # their ymap `archetypeName` was still `hash_XXXXXXXX` even though the real name was on disk.
    # It was not a resolver bug - all 183 of those names ARE in today's names table (checked
    # against load_names over B:/RUDE_Filebase_Full: 183/183 present). The XML holding the hashes
    # was written 2026-07-27 by an emitter that dropped <extensions> entirely; today's meta2xml
    # raises `unknown extension type 'hash_32818195' - refusing to emit a guess` on the very same
    # binary (B:/RUDE_Filebase_Full/00_base/ymap/po1_07_strm_1.ymap, 207 entities), so this run
    # cannot replace it and says nothing. COST: a downstream audit spent its budget designing a
    # plugin-side hash-recovery for entities that a re-convert would have fixed for free.
    # ⛔ NOTHING IS DELETED (preserve-don't-delete): the file is COUNTED and NAMED, and the
    # operator decides. Deleting it would also destroy the only copy of that ymap's placements.
    stale, stale_examples = 0, []

    def _prior_xml(d, stem):
        """Any .xml this stem already has on disk, whatever kind it was emitted as - a .ymt whose
        root is CMapData is written `<stem>.ymap.xml`, so checking only `<stem>.<kind>.xml` would
        miss exactly the mislabelled files the root-struct dispatch exists to handle."""
        return ['%s.%s.xml' % (stem, k) for k in ('ytyp', 'ymap', 'ymt')
                if os.path.isfile(os.path.join(d, '%s.%s.xml' % (stem, k)))]

    for slot in slots:
        for kind in ('ytyp', 'ymap', 'ymt'):
            d = os.path.join(out, slot, kind)
            if not os.path.isdir(d):
                continue
            for fn in sorted(os.listdir(d)):
                if not fn.lower().endswith('.' + kind):
                    continue
                src = os.path.join(d, fn)
                stem = fn[:-(len(kind) + 1)]

                def _note_stale(reason):
                    prior = _prior_xml(d, stem)
                    if not prior:
                        return
                    nonlocal stale
                    stale += 1
                    if len(stale_examples) < 8:
                        stale_examples.append((os.path.join(slot, kind, prior[0]), reason))

                if kind == 'ymt':
                    # ⚠ Not every .ymt is META, and neither of these is a decode failure -
                    # count them apart from real failures or the summary cries wolf on every
                    # run. Measured over update.rpf (733 ymt, 2026-07-31): 634 PSO ('PSIN',
                    # the sp_manifest class - see pso_manifest.py) and 35 RBF ('RBF0', the
                    # old binary-XML container, all bink_cnt_* video metadata - no reader
                    # here and nothing map-relevant inside).
                    with open(src, 'rb') as fh:
                        magic = fh.read(4)
                    if magic == b'PSIN':
                        pso += 1
                        _note_stale('PSO (PSIN) container - not META, never emitted by this pass')
                        continue
                    if magic == b'RBF0':
                        rbf += 1
                        _note_stale('RBF0 container - not META, never emitted by this pass')
                        continue
                try:
                    xml, got_kind, w = meta2xml.convert(src, names)
                except meta2xml.UnsupportedRoot as ex:
                    # a recognised boundary: well-formed META, no emitter for its root
                    # (e.g. CStreamingRequestRecord - cutscene streaming request lists)
                    noemit[ex.root_name] = noemit.get(ex.root_name, 0) + 1
                    _note_stale(f'no emitter for root {ex.root_name}')
                    continue
                except Exception as ex:
                    msg = f'{type(ex).__name__}: {ex}'
                    why[msg] = why.get(msg, 0) + 1
                    fail += 1
                    _note_stale(msg)
                    continue
                with open(os.path.join(d, f'{stem}.{got_kind}.xml'), 'w',
                          encoding='utf-8') as fh:
                    fh.write(xml)
                unresolved += w.warn.get('unresolved asset-name hash', 0)
                # ⛔ SURFACE EVERY warn CLASS, not just the one we happened to read (2026-08-03).
                # Walker.warn is a real decode-failure detector that was wired to NOTHING: seven
                # classes are raised and exactly one was ever read, so "unhandled type 0x40" fired
                # ~970 times per run and reached no human. A detector nobody reads is not a
                # detector - it is a comment that costs CPU.
                for _k, _n in w.warn.items():
                    if _k != 'unresolved asset-name hash':
                        warn_classes[_k] = warn_classes.get(_k, 0) + _n
                ok += 1

    print(f'converted {ok} ytyp/ymap/ymt -> XML, {fail} failed'
          + (f', {pso} PSO (PSIN) .ymt skipped - a different container, see pso_manifest.py'
             if pso else '')
          + (f', {rbf} RBF0 (binary-XML) .ymt skipped - a different container, no reader here'
             if rbf else ''))
    for rn, n in sorted(noemit.items(), key=lambda kv: -kv[1]):
        print(f'  {n:5}x  recognised META root {rn} - well-formed, no emitter (counted, not failed)')
    if warn_classes:
        print('decoder warnings (each one is data the walker did not fully understand):')
        for _k, _n in sorted(warn_classes.items(), key=lambda kv: -kv[1]):
            print(f'  {_n:7,}x  {_k}')
    if unresolved:
        print(f'  unresolved name hashes: {unresolved:,} -> emitted as hash_XXXXXXXX. The '
              f'ymap<->ytyp join still holds (same hash both sides); only an assetName needs a '
              f'real name, and those come from the asset files themselves.')
    for m, n in sorted(why.items(), key=lambda kv: -kv[1])[:8]:
        print(f'  {n:5}x  {m}')
    # ⭐ ydd ENTRY NAMES (added 2026-07-30). extract writes them as hash_%08X because this
    # table did not exist yet - resolve them now, in place. The entry-level <Name> is the ONLY
    # line in a .ydd.xml indented exactly two spaces (" <Item>" + one-space body lines), so an
    # anchored rewrite cannot touch shader, texture or any deeper <Name>, which all sit at four
    # spaces or more. Unresolved entries stay hash_%08X - the dictionary join is hash-to-hash,
    # so an unresolved name costs nothing downstream; it is counted, never guessed.
    ydd_pat = re.compile(r'^(  <Name>)hash_([0-9A-F]{8})(</Name>)$', re.MULTILINE)
    ydd_files = ydd_hits = ydd_left = 0
    for slot in slots:
        d = os.path.join(out, slot, 'ydd')
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            if not fn.lower().endswith('.ydd.xml'):
                continue
            p = os.path.join(d, fn)
            with open(p, 'r', encoding='utf-8') as fh:
                text = fh.read()
            counts = {'hit': 0, 'left': 0}

            def _sub(m):
                nm = names.get(int(m.group(2), 16))
                if nm is None:
                    counts['left'] += 1
                    return m.group(0)
                counts['hit'] += 1
                nm = nm.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                return m.group(1) + nm + m.group(3)

            new = ydd_pat.sub(_sub, text)
            if counts['hit']:
                with open(p, 'w', encoding='utf-8', newline='') as fh:
                    fh.write(new)
                ydd_files += 1
            ydd_hits += counts['hit']
            ydd_left += counts['left']
    if ydd_hits or ydd_left:
        print(f'ydd entry names: resolved {ydd_hits:,} across {ydd_files:,} dictionaries; '
              f'{ydd_left:,} stay hash_%08X (no asset filename hashes to them - the join is '
              f'hash-to-hash, so nothing breaks)')

    # ⛔ PRINTED LAST ON PURPOSE. A `meta` run over the whole game prints thousands of lines; a
    # warning in the middle of that is a warning nobody reads. This is the one thing that makes
    # the NEXT step produce a corpus that lies, so it sits directly above the next-step line.
    if stale:
        print(f'\n⛔ STALE OUTPUT: {stale:,} .xml file(s) on disk were emitted by an EARLIER '
              f'converter run and THIS run could not reproduce them. `resolve` will hardlink them '
              f'into _resolved and RUDE will join against a MIXTURE of converter generations - '
              f'which reads as corpus damage (missing archetypes, hash_ names that a current run '
              f'would resolve), not as a converter boundary.'.replace('⛔', '!!'))
        for _p, _r in stale_examples:
            print(f'    {_p}  <- {_r}')
        if stale > len(stale_examples):
            print(f'    ... and {stale - len(stale_examples):,} more')
        print('  Nothing was deleted. Either fix the emitter and re-run `meta`, or delete those '
              '.xml files yourself so the gap is HONEST (a missing file is a countable hole; a '
              'stale one is a wrong answer with no counter).')

    print('\n  next: quarry.py resolve --out "<project>"   (flatten for RUDE)')
    return 0


# ⭐ Texture dictionaries do not live only in ytd/ any more. A drawable can carry its own, and
# QUARRY writes that as a sibling "<stem>.ytd.xml" in the DRAWABLE's folder with pixels in
# "<stem>/" beside it (see to_interchange_xml). Any tool that reports on or prunes texture pixels
# must look in all of these, or it is blind to a third of the textures in the game and will happily
# report "0 unused" while missing them entirely - or worse, prune what it cannot see the reference
# for. Measured: 1,180 of 3,479 base drawables (33.9%) carry an embedded dictionary.
TXD_BEARING_DIRS = ('ytd', 'ydr', 'ydd', 'yft')


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
    kinds_seen = set()
    for root in ref_roots:
        for kind in ('ydr', 'ydd', 'yft'):
            d = os.path.join(root, kind)
            if not os.path.isdir(d):
                continue
            kinds_seen.add(kind)
            for fn in os.listdir(d):
                if not fn.lower().endswith('.xml'):
                    continue
                # Sibling embedded-texture manifests share this folder now. They are not drawables,
                # and counting them inflated "drawables scanned" to 12 for 6 files.
                if fn.lower().endswith('.ytd.xml'):
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
      for sub in TXD_BEARING_DIRS:
        d = os.path.join(root, sub)
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
      for sub in TXD_BEARING_DIRS:
        d = os.path.join(root, sub)
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
        print('\nSTOP - REFUSING TO PRUNE: scanned %d drawables and %d ytd manifests. With no drawable'
              ' XML to read, every dictionary looks unreferenced and this would delete them all.'
              '\n   Run `quarry extract --xml` then `quarry resolve` for this project first.'
              % (drawables, manifests))
        return 1
    # ⛔ PRESENCE IS NOT COVERAGE (2026-08-03). The zero-check above catches a binary-only
    # project; a PARTIAL one sailed straight through. `resolve --types ydr,ytd` leaves _resolved
    # with no ydd/ and no yft/ at all, so `wanted` never learns the textures those drawables name
    # - and --prune then deletes those pixels from the SLOTS as well as from _resolved. Every
    # drawable lane that can reference a texture must be present before deletion is allowed.
    missing_kinds = sorted({'ydr', 'ydd', 'yft'} - kinds_seen)
    if missing_kinds:
        print('\nSTOP - REFUSING TO PRUNE: no %s drawable folder in the reference roots. Those '
              'drawables reference textures too, so their names are missing from the keep set and '
              'pruning would delete pixels that ARE used.\n   Resolve every drawable type first '
              '(`quarry resolve --out <project>` with no --types), then prune.'
              % '/'.join(missing_kinds))
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
                # ⛔ ANCHOR THE TEST (2026-08-03). `'~' in stem` dropped ANY asset whose name
                # merely contains a tilde and miscounted it as a collision alternate. The suffix
                # this is looking for is the one file_into writes: `~<n>` at the END.
                base = stem[:-len('__embedded')] if stem.endswith('__embedded') else stem
                if _ALT_RE.search(base):
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
    blocked = []
    for (type_dir, fname), slot in sorted(winner.items()):
        src = os.path.join(out, slot, type_dir, fname)
        dst = os.path.join(dest_root, type_dir, fname)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        # ⛔ A LOCKED FILE MUST NOT ABORT THE WHOLE RESOLVE (2026-08-04). This died with
        # PermissionError [WinError 32] partway through a whole-game run because ONE file was open
        # in another process (an analysis reading the corpus). Dying midway is the worst outcome
        # available: `_resolved` is left half-rebuilt and the manifest is never written at all, so
        # the tree ends up in a state neither the old nor the new resolve describes - strictly
        # worse than not having run. Skip the file, COUNT it, and finish; the summary names them.
        try:
            if os.path.exists(dst):
                os.remove(dst)
            if a.copy:
                raise OSError('copy requested')
            os.link(src, dst)
            linked += 1
        except PermissionError as ex:
            blocked.append(f'{type_dir}/{fname}: {ex.strerror or ex}')
            continue
        except OSError:
            try:
                shutil.copy2(src, dst)
                copied += 1
            except PermissionError as ex:
                blocked.append(f'{type_dir}/{fname}: {ex.strerror or ex}')
                continue
        # a converted asset's payload folder must follow its winning XML or the XML points at
        # nothing (ytd) - resolve it from the SAME slot, never from a mix
        # ⛔ CLEAR A STALE DESTINATION FOLDER EVEN WHEN THE WINNER HAS NONE (2026-08-03). The
        # rmtree used to live INSIDE `if os.path.isdir(side_src)`, so when the new winner carried
        # no payload folder, a folder left by a previous resolve (from a slot that used to win)
        # survived in _resolved - pairing one dictionary's manifest with ANOTHER dictionary's
        # pixels, which is exactly the mix-up the same-slot rule exists to prevent.
        side_name = split_type_ext(fname)[0]
        side_src = os.path.join(out, slot, type_dir, side_name)
        side_dst = os.path.join(dest_root, type_dir, side_name)
        if os.path.isdir(side_dst):
            shutil.rmtree(side_dst)
        if os.path.isdir(side_src):
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

    # ⭐ A TYPE-SCOPED RUN MERGES into the existing record (2026-07-31). This used to rewrite
    # _RESOLVED.json from ONLY this run's winners, so `resolve --types ymt` after a whole-game
    # resolve replaced the 100k-file record with a 62-entry one - every other type's files were
    # still on disk but the manifest had forgotten them, and a consumer trusting perType would
    # conclude the corpus is nearly empty. No --types stays the full authoritative rewrite;
    # with --types, entries for types OUTSIDE the filter are carried forward unchanged.
    man_path = os.path.join(dest_root, '_RESOLVED.json')
    merged = {}
    if want is not None and os.path.isfile(man_path):
        try:
            with open(man_path) as f:
                prior = json.load(f).get('winners', {})
            merged = {k: v for k, v in prior.items()
                      if k.split('/', 1)[0].lower() not in want}
        except Exception as ex:
            print(f'  ! could not carry forward the existing _RESOLVED.json ({ex}) - the new '
                  f'record holds this run\'s types only')
    merged.update({f'{t}/{n}': s for (t, n), s in winner.items()})
    per_type = {}
    for k in merged:
        t = k.split('/', 1)[0]
        per_type[t] = per_type.get(t, 0) + 1
    with open(man_path, 'w') as f:
        json.dump({'quarryVersion': 1,
                   'note': 'Flat build-accurate view of the precedence tree. Point RUDE\'s '
                           'CorpusRoot here.',
                   'slotsInAscendingPrecedence': slots,
                   # Carried from the project manifest rather than hardcoded: whether the winner of
                   # a contested name is TRUSTWORTHY depends entirely on whether the DLC order came
                   # from the game's own dlclist.xml, and a consumer needs to know which it got.
                   'dlcOrderAuthoritative': manifest_flag(out),
                   # counts other than 'files' describe THIS run (a type-scoped run reports its
                   # own work, not history)
                   'counts': {'files': len(merged), 'overriddenByHigherSlot': overridden,
                              'withinSlotAlternatesSkipped': ambiguous, 'sidecars': sidecars},
                   'perType': per_type,
                   'winners': dict(sorted(merged.items()))},
                  f, indent=1)

    print(f'resolved -> {dest_root}')
    print(f'  slots walked (ascending precedence): {len(slots)}')
    # ⚠ Say WHICH number is which. A scoped run resolves only its own types but the manifest (and
    # therefore per_type) is the MERGED record, so printing both on one line without labels read
    # as an arithmetic error ("files: 639" beside types summing to 2,737).
    if want is not None:
        print(f'  files resolved THIS RUN: {len(winner):,}   ({",".join(sorted(want))})')
        print(f'  manifest now records {sum(per_type.values()):,} across all types:   '
              + '  '.join(f'{t}={n:,}' for t, n in sorted(per_type.items())))
    else:
        print(f'  files: {len(winner):,}   '
              + '  '.join(f'{t}={n:,}' for t, n in sorted(per_type.items())))
    print(f'  overridden by a higher slot: {overridden:,}   (this is precedence doing its job)')
    print(f'  pixel sidecars carried: {sidecars:,}')
    print(f'  hardlinked {linked:,}, copied {copied:,}')
    if blocked:
        print(f'  ! {len(blocked):,} file(s) SKIPPED - locked by another process. _resolved is '
              f'complete except for these; re-run when nothing else is reading the corpus:')
        for b in blocked[:6]:
            print(f'      {b}')
        if len(blocked) > 6:
            print(f'      ... and {len(blocked) - 6} more')
    if ambiguous:
        print(f'  ! within-slot name alternates SKIPPED: {ambiguous:,} - the un-suffixed copy won.'
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
    # with the AES key found in the user's OWN executable (maintainer decision 2026-07-27, option A).
    # ⚠ ORDER MATTERS: this now runs BEFORE the project tree is written, because reading the game's
    # real DLC load order out of update.rpf needs the keys, and the tree encodes that order in its
    # folder names - building it first would bake in the guess.
    keys = tables = aes_key = None
    try:
        import keyderive
        raw_k, raw_t = keyderive.acquire(a.game, a.keys, getattr(a, 'magic', None))
        keys, tables = ngcrypto.keys_from_bytes(raw_k), ngcrypto.tables_from_bytes(raw_t)
    except Exception as e:
        print(f'keys     : UNAVAILABLE - {e}')
        print('keys     : encrypted archives will be SKIPPED (nothing will be silently mis-read)')
    try:
        import keyderive
        aes_key = keyderive.acquire_aes(a.game)
        print(f'aes key  : {"recovered from your own executable - AES archives WILL open" if aes_key else "not found - AES archives will be skipped"}')
    except Exception as e:
        print(f'aes key  : UNAVAILABLE - {e}')

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
            print(f'  ! {names[i]}: no dlc*.rpf found in {d} - nothing to extract from this pack')
            continue
        if len(found) > 1:
            print(f'  {names[i]}: {len(found)} archives -> {", ".join(found)}')
        for f in found:
            jobs.append((os.path.join(d, f),
                         os.path.join('20_dlc', '%03d_%s' % (i + 1, names[i]))))
    if a.only:
        avail = sorted({os.path.basename(j[0]) for j in jobs})
        jobs = [j for j in jobs if os.path.basename(j[0]).lower() == a.only.lower()]
        if not jobs:
            # Fail HERE with the available names rather than walking zero archives and calling it
            # a clean run - a typo in --only used to be indistinguishable from an empty game.
            print(f'STOP --only {a.only!r} matched NO archive. Available ({len(avail)}): '
                  + ', '.join(avail[:24]) + (' …' if len(avail) > 24 else ''))
            return 2

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
                print('textures    : ytd -> .ytd.xml + .dds  ! NO .png, and ImportYtd reads .png '
                      '- this folder is an archive, not an importable one')
            elif ytd2xml.png_available():
                print(f'textures    : ytd -> .ytd.xml + {" + ".join(parts)}'
                      f'   (ImportYtd reads the .png)')
            else:
                print('textures    : ! texture2ddecoder/Pillow NOT installed - ytd folders will '
                      'hold .dds ONLY, and ImportYtd reads .png. `pip install texture2ddecoder '
                      'Pillow` to make the texture lane usable.')
        except Exception as e:
            print(f'textures    : ytd converter unavailable - {e}')

    total = skipped = 0
    stats = {}
    for path, slot in jobs:
        try:
            r = Rpf(path, keys, tables, aes_key=aes_key)
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
                    written_path = None
                    try:
                        conv = to_interchange_xml(name, blob,
                                                 getattr(a, 'textures', 'both'), stats)
                        if conv is not None:
                            xml_name, xml_bytes, extras = conv
                            written = file_into(a.out, slot, xml_name, xml_bytes, stats,
                                                getattr(a, 'resume', False))
                            if written is None:
                                # ⛔ do NOT count a resumed skip as an extracted file: `total` is
                                # read as "files this run produced", and counting skips made a
                                # resumed run report work it never did.
                                continue
                            written_path = os.path.join(a.out, slot, type_of(name), written)
                            # The pixel folder must follow the XML that was ACTUALLY written: on
                            # a basename collision the XML becomes foo~1.ytd.xml, and a sidecar
                            # folder still called `foo` would hand one dictionary's XML another
                            # dictionary's textures - silently, since both are valid files.
                            folder = split_type_ext(written)[0]
                            orig = split_type_ext(xml_name)[0]
                            for rel, payload in extras:
                                # ⛔ RE-STEM BY PREFIX, not by slash position. This used to do
                                # rel[rel.index('/'):], which assumed every sidecar lives INSIDE a
                                # "<stem>/" folder. The embedded-texture manifest is a top-level
                                # sidecar ("X.embedded.ytd.xml", no slash), so index() raised
                                # ValueError, the outer handler swallowed it as xml_failed, and the
                                # code fell through to writing the raw BINARY - 3,688 of them before
                                # this was caught. Prefix-swapping handles both shapes and leaves
                                # anything unrecognised untouched instead of crashing.
                                if orig and rel.startswith(orig):
                                    rel = folder + rel[len(orig):]
                                sidecar_into(a.out, slot, type_of(name), rel, payload)
                                stats['xml_sidecars'] = stats.get('xml_sidecars', 0) + 1
                            stats['xml_ok'] = stats.get('xml_ok', 0) + 1
                            n += 1
                            continue
                    except Exception as ex:
                        stats['xml_failed'] = stats.get('xml_failed', 0) + 1
                        stats.setdefault('xml_errors', []).append(f'{name}: {type(ex).__name__}: {ex}')
                        # ⛔ UNWIND THE HALF-WRITTEN XML (2026-08-03). If the failure happened
                        # AFTER file_into wrote the XML - i.e. anywhere in the sidecar loop - the
                        # fallback below wrote the raw binary too, leaving BOTH artifacts on disk
                        # for the same asset. `resolve` then picks by extension and a consumer
                        # reads an XML whose pixel/child sidecars are missing or partial, while
                        # the run reports "kept binary" and looks handled.
                        if written_path:
                            for p in (written_path, split_type_ext(written_path)[0]):
                                try:
                                    if os.path.isdir(p):
                                        shutil.rmtree(p)
                                    elif os.path.exists(p):
                                        os.remove(p)
                                except OSError:
                                    pass
                            stats['xml_unwound'] = stats.get('xml_unwound', 0) + 1
                        # fall through and keep the binary rather than losing the asset
                file_into(a.out, slot, name, blob, stats, getattr(a, 'resume', False))
                n += 1
            except Exception as ex:
                stats['failed'] = stats.get('failed', 0) + 1
                stats.setdefault('failures', []).append(f'{name}: {type(ex).__name__}')
        total += n
        # ⛔ REPORT CONVERSION FAILURES PER ARCHIVE, not only in the final summary. They WERE
        # counted and printed - but only after the whole run, which on a whole-game extract is
        # hours. A systemic converter bug (every drawable with an embedded dictionary failing and
        # silently falling back to raw binary) therefore looked exactly like a healthy run for the
        # entire time it was destroying the output. A defect has to be visible while there is still
        # a decision to make about it.
        failed_now = stats.get('xml_failed', 0)
        delta = failed_now - locals().get('_prev_failed', 0)
        note = f'   ⚠ {delta} conversion FAILED (kept binary)' if delta else ''
        _prev_failed = failed_now
        print(f'  {os.path.basename(path):<28} -> {slot:<28} {n} files{note}')

    print(f'\nextracted {total} files'
          + (f' ({stats["resumed"]:,} already present, skipped)' if stats.get('resumed') else '')
          + f'; {skipped} archive(s) skipped')
    if stats.get('xml_unwound'):
        print(f'half-written XML unwound after a mid-sidecar failure: {stats["xml_unwound"]}')
    print(f'nested archives opened: {stats.get("nested_opened", 0)}'
          f'   failed to open: {stats.get("nested_failed", 0)}'
          f'   AES-encrypted (no key, expected): {stats.get("nested_aes_skipped", 0)}'
          f'   past max-depth: {stats.get("nested_skipped", 0)}')
    if getattr(a, 'xml', False):
        print(f'XML converted: {stats.get("xml_ok", 0)}   conversion failed (kept binary): '
              f'{stats.get("xml_failed", 0)}'
              + (f'   pixel sidecars: {stats["xml_sidecars"]}' if stats.get('xml_sidecars')
                 else ''))
        for line in stats.get('xml_errors', [])[:8]:
            print(f'    {line}')
        # ⛔ THE EMITTERS' OWN REFUSAL COUNTERS, SURFACED (2026-08-03). ydr2xml/yft2xml count every
        # decline they make - an embedded dictionary that would not decode, a NaN snapped to zero,
        # a geometry shortfall - into one run-global table. Without this call that table is a
        # detector wired to nothing, which is the exact defect we found in Walker.warn hours
        # earlier: raised seven classes, read one. A downgrade that never reaches a human is a
        # silent one no matter how carefully it was counted.
        try:
            import ydr2xml
            ydr2xml.report_refusals(stats)
        except Exception as ex:
            print(f'  (refusal report unavailable: {type(ex).__name__}: {ex})')
        if stats.get('yft_extras_refused'):
            print(f'yft extras refused (fell back to the visual drawable, counted): '
                  f'{stats["yft_extras_refused"]}')
            for line in stats.get('yft_extras_errors', [])[:8]:
                print(f'    {line}')
    if stats.get('resumed'):
        print(f'resumed (already present, skipped): {stats["resumed"]}')
    print(f'name collisions (kept first, suffixed the rest): {stats.get("collisions", 0)}')
    print(f'files that failed to extract: {stats.get("failed", 0)}')
    for line in stats.get('failures', [])[:15]:
        print(f'    {line}')
    if len(stats.get('failures', [])) > 15:
        print(f'    ... and {len(stats["failures"]) - 15} more')
    # ⛔⛔ A RUN THAT DID NOTHING IS NOT A SUCCESS (2026-08-03). This returned 0 unconditionally,
    # so `--only <typo>`, a `--types` filter that matches nothing, and a run that acquired no keys
    # and skipped every archive ALL printed a clean summary and exited 0. That is the deepest
    # version of the failure this whole triage is about: a gate incapable of failing makes every
    # green result above it meaningless. Zero work = exit 2; work attempted but nothing landed
    # while archives were skipped = exit 1.
    # ⚠ A FULLY-RESUMED RUN IS A LEGITIMATE NO-OP, not a failure. Caught while testing the
    # zero-work gate above: with everything already on disk, `total` is 0 and the gate cried wolf.
    # A gate that fires on a healthy run gets disabled by whoever hits it, which would put us
    # straight back to the un-failable gate this was meant to fix.
    if total == 0 and not stats.get('resumed'):
        print('\nSTOP - ZERO files were extracted. This is a FAILURE, not an empty success - check '
              '--only/--types spelling, and whether key material was available (see the "keys" '
              'line above).')
        return 2
    if total == 0:
        print('\nnothing new to do - every target was already present (resume).')
    return 0


REGRESS_BASELINE = '_regress_baseline.json'
REGRESS_TYPES = ('ydr', 'ybn', 'ydd', 'yft', 'ytd')
# ⛔⛔ THE META LANE WAS OUTSIDE THE GATE UNTIL 2026-08-04. `regress` measured everything through
# to_interchange_xml, which has no ytyp/ymap/ymt branch at all - so the LARGEST emitter surface in
# the tool (meta2xml.py, 2,251 lines, and the one that changes most often) was completely
# unguarded while the gate printed "OK - every fixture produced byte-identical output. No churn."
# That sentence was true and misleading at the same time, which is the exact failure the blind-type
# declaration below already exists to prevent - committed one lane over. PRESENCE IS NOT COVERAGE.
REGRESS_META_TYPES = ('ytyp', 'ymap', 'ymt')
# ⚠ Not every .ymt is META (see cmd_meta): PSIN = PSO container, RBF0 = old binary-XML. Filtering
# them at SAMPLE time, not at convert time, keeps the sample deterministic AND keeps a legitimate
# non-META file out of the error list, where it would fail the gate on every run forever.
_NON_META_YMT_MAGIC = (b'PSIN', b'RBF0')
REGRESS_NAMES_KEY = 'meta:_names_table'


def _regress_fixtures(root, per_type, seed):
    """A DETERMINISTIC sample of real binaries from the operator's own filebase.

    Deterministic matters more than large: the same command must pick the same files on every
    run, or a passing gate proves nothing about the run before it. Sorted names + a fixed seed
    give that without recording any game data.
    """
    import random
    out = []
    for t in REGRESS_TYPES:
        found = []
        for slot in precedence_slots(root):
            d = os.path.join(root, slot, t)
            if not os.path.isdir(d):
                continue
            found += [os.path.join(d, f) for f in sorted(os.listdir(d))
                      if f.lower().endswith('.' + t)]
        if not found:
            continue
        rng = random.Random(f'{seed}:{t}')
        out += sorted(rng.sample(found, min(per_type, len(found))))
    return out


def _regress_signature(path):
    """(xml sha256, [(sidecar name, sha256)]) for one binary, through the REAL pipeline entry
    point - so the gate measures what extract would actually write, not a private code path."""
    import hashlib
    blob = open(path, 'rb').read()
    conv = to_interchange_xml(os.path.basename(path), blob, 'none', None)
    if conv is None:
        return {'converted': False}
    _n, xml_bytes, sidecars = conv
    # ⛔ JSON-STABLE BY CONSTRUCTION. The first version stored tuples; json.load returns them as
    # LISTS, so the signature never equalled its own baseline and the gate failed the run
    # immediately after blessing it. A gate that cries wolf on a healthy run gets switched off by
    # whoever hits it - the same failure mode as the zero-work gate earlier today. Anything stored
    # here must survive a dump/load round trip unchanged.
    return {
        'converted': True,
        'xml': hashlib.sha256(xml_bytes).hexdigest(),
        'bytes': len(xml_bytes),
        'sidecars': [[rel, hashlib.sha256(p).hexdigest()]
                     for rel, p in sorted(sidecars or [])],
    }


def _regress_meta_fixtures(root, per_type, seed):
    """The same deterministic sample, for the META lane (ytyp/ymap/ymt binaries).

    Kept separate from _regress_fixtures because the two lanes have different entry points
    (to_interchange_xml vs meta2xml.convert) and different prerequisites (the meta lane needs the
    joaat names table), NOT because meta deserves weaker guarding - it is sampled, hashed, keyed
    and blessed exactly the same way.
    """
    import random
    out = []
    for t in REGRESS_META_TYPES:
        found = []
        for slot in precedence_slots(root):
            d = os.path.join(root, slot, t)
            if not os.path.isdir(d):
                continue
            for f in sorted(os.listdir(d)):
                if not f.lower().endswith('.' + t):
                    continue
                p = os.path.join(d, f)
                if t == 'ymt':
                    try:
                        with open(p, 'rb') as fh:
                            if fh.read(4) in _NON_META_YMT_MAGIC:
                                continue
                    except OSError:
                        continue
                found.append(p)
        if not found:
            continue
        rng = random.Random(f'{seed}:{t}')
        out += sorted(rng.sample(found, min(per_type, len(found))))
    return out


def _regress_meta_signature(path, names):
    """(kind, xml sha256) for one ytyp/ymap/ymt, through meta2xml.convert - the same call cmd_meta
    makes, with the same names table, so the gate measures what `quarry meta` would actually write.

    `kind` is part of the signature on purpose: it comes from the ROOT STRUCT, so a decoder change
    that starts reading a CMapData as something else moves the hash AND says which way it moved.
    """
    import hashlib
    import meta2xml
    try:
        xml, kind, _w = meta2xml.convert(path, names)
    except meta2xml.UnsupportedRoot as ex:
        # A recognised boundary, not a failure - and a real thing to guard: the day an emitter
        # appears for that root, this entry moves and has to be blessed like any other change.
        return {'converted': False, 'noEmitter': ex.root_name}
    return {'converted': True, 'kind': kind,
            'xml': hashlib.sha256(xml.encode('utf-8')).hexdigest(), 'bytes': len(xml)}


def cmd_regress(a):
    """⛔⛔ THE CHURN GATE. Converter OUTPUT may not change unless someone says why.

    Matt, 2026-08-03: "are we actually doing triage ... or just shuffling things around?" The
    difference is measurable and therefore mechanizable: a genuine fix changes output ONLY where
    a defect was measured, while churn changes output somewhere nobody predicted. Left to
    attention, that check happens when a human happens to ask - which is exactly when it is
    least likely to happen.

    So: a fixed, deterministic sample of the operator's OWN binaries is converted through the
    real pipeline entry point and hashed. Any hash that moves FAILS the run and prints what
    moved. Accepting a change requires `--bless --reason "<why>"`, which records the reason and
    the date beside the new hash - so the next reader sees a justification, not a mystery.

    TWO LANES, ONE BASELINE (meta added 2026-08-04):
      binary lane  ydr/ybn/ydd/yft/ytd  ->  to_interchange_xml   keyed  <slot>/<type>/<file>
      meta lane    ytyp/ymap/ymt        ->  meta2xml.convert     keyed  meta:<slot>/<type>/<file>
    Same sample rule, same hash, same --bless/--reason contract, same file. The meta lane also
    records the SIZE of the joaat names table it ran with, because that table is an input to the
    emitted XML.

    ⛔ The baseline lives in the project folder and is NEVER committed: it is derived from the
    operator's own install (the same rule as every other artifact here).
    """
    import datetime
    root = a.out
    if not os.path.isdir(root):
        print(f'no project folder at {root}')
        return 2
    bl_path = os.path.join(root, REGRESS_BASELINE)
    baseline = {}
    if os.path.isfile(bl_path):
        try:
            with open(bl_path) as f:
                baseline = json.load(f)
        except Exception as e:
            print(f'baseline unreadable ({e}) - treating as absent')
    fixtures = _regress_fixtures(root, a.per_type, a.seed)
    # ⛔ THE META LANE MAY LIVE IN A DIFFERENT PROJECT, and saying so beats pretending otherwise.
    # No single project on this machine holds binaries of all eight types: RUDE_Fixtures is the
    # binary set for the five to_interchange_xml converters and has ZERO ytyp/ymap/ymt, while
    # RUDE_Filebase_Full was extracted --xml and has almost no ydr/ytd binaries left. Rather than
    # let --strict be un-passable (which gets it dropped from the command line, and then the gate
    # is off), --meta-from names the project the META fixtures come from. Its own path is what
    # gets keyed, so the two lanes cannot collide in the baseline.
    meta_root = a.meta_from or root
    meta_fixtures = []
    if os.path.isdir(meta_root):
        meta_fixtures = _regress_meta_fixtures(meta_root, a.per_type, a.seed)
    elif a.meta_from:
        print(f'STOP - --meta-from {a.meta_from} is not a directory')
        return 2
    if not fixtures and not meta_fixtures:
        print(f'STOP - no binary fixtures found under {root}. The gate needs real binaries; a '
              f'--xml extract leaves none for converted types. Extract at least one archive '
              f'WITHOUT --xml first (e.g. --types ydr,ytd --only x64a.rpf).')
        return 2
    # ⛔⛔ A GATE MUST DECLARE WHAT IT CANNOT SEE (2026-08-04). The first version of this gate
    # silently covered whatever binaries happened to exist: pointed at RUDE_Filebase_Test2 it saw
    # ydr and ybn ONLY, so five agents ran it, all got a green "no churn", and yft/ydd/ytd went
    # completely unguarded. That is the same defect this gate exists to catch, committed by the
    # gate itself - and worse than no gate, because a green result was being read as coverage.
    # PRESENCE IS NOT COVERAGE, the same law `--prune` already follows.
    by_type = {}
    for p in fixtures:
        by_type[os.path.splitext(p)[1].lstrip('.').lower()] = \
            by_type.get(os.path.splitext(p)[1].lstrip('.').lower(), 0) + 1
    for p in meta_fixtures:
        t = os.path.splitext(p)[1].lstrip('.').lower()
        by_type[t] = by_type.get(t, 0) + 1
    covered = ', '.join(f'{t}={by_type[t]}' for t in sorted(by_type))
    blind = [t for t in REGRESS_TYPES + REGRESS_META_TYPES if t not in by_type]
    print(f'fixtures  : {len(fixtures) + len(meta_fixtures)} binaries (seed {a.seed}, '
          f'{a.per_type}/type)  [{covered}]')
    if blind:
        print(f'⚠ BLIND to {"/".join(blind)} - this project holds no binaries of those types, so '
              f'their converters are NOT guarded by this run. A --xml extract leaves no binaries '
              f'behind; keep a small binary-only project (extract WITHOUT --xml) to cover them.'
              .replace('⚠', '!'))
        if [t for t in REGRESS_META_TYPES if t in blind]:
            print(f'  the meta lane (ytyp/ymap/ymt -> meta2xml) reads from {meta_root} - point '
                  f'--meta-from at a project that still holds those binaries.')
        if a.strict:
            print('STOP - --strict was requested and the gate cannot see every converter.')
            return 2

    sigs, errors = {}, {}
    for p in fixtures:
        key = os.path.relpath(p, root).replace(os.sep, '/')
        try:
            sigs[key] = _regress_signature(p)
        except Exception as ex:
            errors[key] = f'{type(ex).__name__}: {ex}'

    if meta_fixtures:
        import meta2xml
        # ⭐ THE NAMES TABLE IS AN INPUT TO THE OUTPUT, so it is part of what gets compared. A ytyp
        # emits `<assetName>hash_F186ED33</assetName>` or the real name depending ONLY on whether
        # some asset FILENAME in the project hashes to it, so adding or removing files from the
        # meta project moves meta output with no code change at all. Recording the table SIZE as
        # its own baseline entry turns that from "22 meta fixtures changed, why?" into one line
        # naming the cause - and it is one entry, not a field on every fixture, so a corpus change
        # cannot make every meta fixture cry wolf at once.
        names = meta2xml.load_names(*[os.path.join(meta_root, s)
                                      for s in precedence_slots(meta_root)])
        print(f'names     : {len(names):,} joaat names available to the meta lane (from '
              f'{meta_root})')
        sigs[REGRESS_NAMES_KEY] = {'names': len(names)}
        for p in meta_fixtures:
            key = 'meta:' + os.path.relpath(p, meta_root).replace(os.sep, '/')
            try:
                sigs[key] = _regress_meta_signature(p, names)
            except Exception as ex:
                errors[key] = f'{type(ex).__name__}: {ex}'

    if a.bless:
        if not a.reason:
            print('STOP - --bless requires --reason "<why the output changed>". A baseline moved '
                  'without a recorded reason is indistinguishable from churn, which is the '
                  'entire thing this gate exists to catch.')
            return 2
        stamp = a.date or datetime.date.today().isoformat()
        moved = sum(1 for k, v in sigs.items() if baseline.get(k, {}).get('sig') != v)
        for k, v in sigs.items():
            prev = baseline.get(k, {})
            if prev.get('sig') != v:
                hist = prev.get('history', [])
                hist.append({'date': stamp, 'reason': a.reason})
                baseline[k] = {'sig': v, 'history': hist[-10:]}
        with open(bl_path, 'w') as f:
            json.dump(baseline, f, indent=1, sort_keys=True)
        print(f'blessed {moved} fixture(s) -> {bl_path}\n  reason: {a.reason}')
        return 0

    if not baseline:
        print('STOP - no baseline yet. Record one with:\n'
              f'    quarry.py regress --out "{root}" --bless --reason "initial baseline"\n'
              '  and commit nothing - the baseline is derived from your own install.')
        return 2

    changed, missing, new = [], [], []
    for k, v in sigs.items():
        if k not in baseline:
            new.append(k)
        elif baseline[k].get('sig') != v:
            changed.append(k)
    for k in baseline:
        if k not in sigs and k not in errors:
            missing.append(k)

    print(f'compared  : {len(sigs)} fixtures against the baseline')
    if errors:
        print(f'\nSTOP - {len(errors)} fixture(s) FAILED TO CONVERT that the baseline expects:')
        for k, e in list(errors.items())[:8]:
            print(f'    {k}: {e}')
    if changed:
        print(f'\nSTOP - OUTPUT CHANGED for {len(changed)} fixture(s):')
        for k in changed[:12]:
            was, now = baseline[k]['sig'], sigs[k]
            bits = []
            if was.get('xml') != now.get('xml'):
                bits.append(f'xml {was.get("bytes")}B -> {now.get("bytes")}B')
            if was.get('sidecars') != now.get('sidecars'):
                bits.append(f'sidecars {len(was.get("sidecars") or [])} -> '
                            f'{len(now.get("sidecars") or [])}')
            if was.get('converted') != now.get('converted'):
                bits.append(f'converted {was.get("converted")} -> {now.get("converted")}')
            if was.get('kind') != now.get('kind'):
                bits.append(f'root struct {was.get("kind")} -> {now.get("kind")}')
            if was.get('noEmitter') != now.get('noEmitter'):
                bits.append(f'noEmitter {was.get("noEmitter")} -> {now.get("noEmitter")}')
            if was.get('names') != now.get('names'):
                bits.append('joaat names table %s -> %s' % (was.get('names'), now.get('names')))
            print(f'    {k}: ' + ', '.join(bits or ['content differs']))
        if len(changed) > 12:
            print(f'    ... and {len(changed) - 12} more')
        if REGRESS_NAMES_KEY in changed:
            # Name the cause before the reader starts bisecting meta2xml.py: the meta emitter is
            # a function of the names table as much as of its own code, and a changed table means
            # the PROJECT changed, not the converter.
            print('\n  ⚠ the joaat names table moved, so meta output can change with no code '
                  'change at all - files were added to or removed from the meta project. Confirm '
                  'that first; a meta-only diff with this entry in it is a CORPUS change.'
                  .replace('⚠', '!'))
        print('\n  If this change is INTENDED, say why and record it:\n'
              f'    quarry.py regress --out "{root}" --bless --reason "<what defect this fixes>"')
    if missing:
        print(f'\n! {len(missing)} baseline fixture(s) are no longer in the sample (corpus '
              f'changed?): ' + ', '.join(missing[:4]) + (' ...' if len(missing) > 4 else ''))
    if new:
        print(f'! {len(new)} fixture(s) have no baseline entry yet: ' + ', '.join(new[:4])
              + (' ...' if len(new) > 4 else ''))
    # ⛔ AN UNBASELINED FIXTURE IS NOT COVERAGE EITHER (2026-08-04). A fixture with no baseline
    # entry is compared against nothing, so it can never fail - it is a green line that guards
    # zero. Harmless as a note, fatal as a claim; and adding the meta lane created 75 of them at
    # once, which is exactly the moment someone reads "OK - no churn" as "meta is guarded".
    # --strict therefore refuses until they are recorded. Same law as BLIND, one step later.
    if new and a.strict and not (changed or errors):
        print(f'\nSTOP - --strict was requested and {len(new)} fixture(s) are compared against '
              f'nothing. Record them first:\n'
              f'    quarry.py regress --out "{root}"'
              + (f' --meta-from "{a.meta_from}"' if a.meta_from else '')
              + ' --bless --reason "record baseline for <what these cover>"')
        return 2
    if changed or errors:
        return 1
    print('\nOK - every fixture produced byte-identical output. No churn.')
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
                            'the RUDE importer reads (ydr/ydd/yft/ytd/ybn here; ytyp/ymap/ymt in the '
                            '`meta` pass, which needs the complete name table). Types with '
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
        p.add_argument('--resume', action='store_true',
                       help='continue an INTERRUPTED run: treat an already-present output file as '
                            'done instead of as a name collision. ⛔ Opt-in only - the collision '
                            'path protects build-accuracy (two same-named files in one slot are '
                            'different assets), so this is for resuming a run you know was cut '
                            'short, never for a fresh one')
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

    pm = sub.add_parser('meta', help='convert binary ytyp/ymap/ymt to interchange XML and resolve '
                                     'ydd entry names (run AFTER extract, so the joaat name table '
                                     'is complete)')
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

    pr = sub.add_parser('regress', help='THE CHURN GATE: converter output may not change '
                                        'unless someone records why')
    pr.add_argument('--out', required=True, help='project folder holding real BINARY fixtures')
    pr.add_argument('--meta-from', dest='meta_from',
                    help='project folder the ytyp/ymap/ymt fixtures come from, when the --out '
                         'project holds no meta binaries (default: --out)')
    pr.add_argument('--per-type', type=int, default=25, dest='per_type',
                    help='fixtures sampled per type (default 25)')
    pr.add_argument('--seed', default='rude', help='sample seed - changing it changes the sample')
    pr.add_argument('--bless', action='store_true',
                    help='accept the current output as the new baseline (requires --reason)')
    pr.add_argument('--reason', help='WHY the output changed - recorded beside the new hash')
    pr.add_argument('--date', help='override the recorded date (tests)')
    pr.add_argument('--strict', action='store_true',
                    help='FAIL if the project holds no binaries for some converter, instead of '
                         'reporting a green pass that only covered the types it could see')
    pr.set_defaults(fn=cmd_regress)

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
