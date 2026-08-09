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
import argparse, fnmatch, glob, hashlib, json, os, re, shutil, struct, sys, zlib
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
                    # ⭐ 2026-08-06: the RESOURCE path used to raise HERE while blaming Oodle
                    # in the message - and never actually tried Oodle. `oodle` was threaded in
                    # and used only by the BINARY branch below, so an Oodle-packed RESOURCE
                    # could never decode no matter what DLL the operator supplied. Try it now,
                    # on both the plain and the NG-decrypted body; a page plan gives us an
                    # exact expected length, so a wrong guess cannot pass silently.
                    if oodle is not None:
                        for cand, tag in ((bytes(raw), 'oodle'), (dec, 'oodle-ng')):
                            try:
                                out = oodle(cand, want)
                            except Exception:
                                continue
                            if out is not None and len(out) == want:
                                e['_how'] = tag
                                sysf, gfxf = e['usize'], e['gfx']
                                version = ((((sysf >> 28) & 0xF) << 4)
                                           | ((gfxf >> 28) & 0xF))
                                return (struct.pack('<4sIII', b'RSC7', version, sysf, gfxf)
                                        + out)
                    raise ValueError(
                        f'resource body does not inflate to its RSC7 page plan ({want} B) '
                        'either plain, NG-decrypted, or via Oodle'
                        + ('' if oodle is not None else
                           ' (NO OODLE DLL BOUND - pass --oodle oo2core_*_win64.dll)')
                        + ' - refusing to write it')
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
        # ⛔⛔ AES-ENCRYPTED BINARY ENTRY (fixed 2026-08-07, THE_PLAN Phase 5 Stage A).
        # The binary branch tried NG and plain only - never the archive's OWN scheme - so a
        # flagged entry inside an AES archive could NEVER decode, no matter the key material.
        # Same defect SHAPE as the resource branch's missing Oodle route (fcc8f14): the route
        # existed for one entry kind and was never wired for the other.
        # MEASURED, not assumed: the discriminator is the PAIR (archive is AES) AND (the
        # entry's own w3 encryption flag is set) - flag alone is worthless, 32,218 flagged
        # entries live in NG archives and decode plain/NG today. Game-wide the pair matches
        # exactly 19 entries (10 ymf, 3 cut, 2 ymap, 2 ytyp, 2 mrf) in 15 archives.
        # ⚠ The cipher covers COMPLETE 16-byte blocks only; the trailing <16 B stay plaintext.
        # Truncating to a block multiple (what the TOC path does, where it is harmless) drops
        # the deflate stream's tail and inflates SHORT - which is why the first probe read
        # 3,605 of 3,632 B. Keeping the tail lands EXACTLY on the declared usize, verified on
        # all 5 reachable cases with a valid PSIN/RBF0 magic in the output.
        if self.enc == ENC_AES and e.get('gfx') and self.aes_key is not None:
            import keyderive
            nblk = len(raw) // 16 * 16
            aes_dec = keyderive.aes256_ecb_decrypt(raw[:nblk], self.aes_key) + raw[nblk:]
            got = self._inflate(aes_dec, e['usize'], oodle)
            if got is not None:
                if e['usize'] and len(got) != e['usize']:
                    raise ValueError(f'AES binary entry inflated to {len(got)} B but its TOC '
                                     f'declares {e["usize"]} B - refusing a body that '
                                     f'disagrees with its own entry')
                return got
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
        inner = os.path.splitext(name)[0]
        ext = os.path.splitext(inner)[1].lstrip('.').lower()
        # A container INFIX is not the asset's type: `x.ytyp.pso.xml` / `x.ymt.rbf.xml` are a
        # ytyp / ymt whose source container happens to be PSO/RBF (the reference exporter's own
        # filename convention, kept). Filing them under pso/ would break the <slot>/<asset-type>/
        # layout the grader and every consumer read (2026-08-08; zero .pso.xml/.rbf.xml existed
        # in any corpus before this, measured before the edit).
        if ext in ('pso', 'rbf'):
            ext = (os.path.splitext(os.path.splitext(inner)[0])[1].lstrip('.').lower()
                   or ext)
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

    ⭐ THE PIXELS LAND IN **`<stem>/`** AS WELL AS `<stem>__embedded/` (2026-08-06), because the
    drawable's OWN XML already names them there and nothing was writing them there.
    X.ydr.xml / X.yft.xml / X.ydd.xml each carry an inline <ShaderGroup><TextureDictionary> whose
    every <FileName> is a bare `<tex>.dds` - so the folder those names resolve against is `X/`,
    the sibling of the XML. We only ever wrote `X__embedded/`, so **every drawable with embedded
    textures advertised pixel files that did not exist beside it** - the exact defect the ydd
    branch was fixed for in 2026-08-03, one level up. MEASURED against the oracle set: 13 sidecar
    DDS across 4 assets (des_fib_frame 9, task_000_u 2, cs_remote_01 1, vb_05_b3rail_lod 1) were
    graded MISSING for this and this alone - the bytes in `X__embedded/` were already
    byte-identical to the oracle's, 9/9 on des_fib_frame. It is a placement bug, not a decode one.

    ⛔ `<stem>__embedded/` IS KEPT, NOT MOVED. It is not redundant naming: `manifest_source_name`
    reads the `__embedded` suffix to decide which BINARY a manifest was decoded from, the
    decode-later lane (`quarry textures`) writes into `<kind>/<manifest stem>/`, and RUDE's shipped
    ImportYtd pairing is in-engine-proven against that layout. Renaming it to satisfy a folder
    comparison would break a working contract to fix a missing file. So the pixels are written
    twice when pixels are asked for at all.
    ⚠ THE COST IS REAL AND BOUNDED: embedded pixel bytes double under `--textures dds|png|both`.
    It is zero for the whole-game path, which runs `--textures none` and fills only
    `<stem>__embedded/` later via `quarry textures` (that lane plans from `.ytd.xml` manifests, and
    `X/` is named by X.ydr.xml, not by any manifest - so it never populates `X/`). ⇒ the two lanes
    now DISAGREE about what a complete `X/` looks like. Flagged, not hidden: the clean end state is
    one copy plus a pixel-folder argument, and that is a RUDE-side decision, not a QUARRY one.
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
        want_png, want_dds = textures != 'dds', textures != 'png'
        sidecars.extend(ytd2xml.sidecars(emb, emb_stem, want_png=want_png, want_dds=want_dds))
        sidecars.extend(ytd2xml.sidecars(emb, stem, want_png=want_png, want_dds=want_dds))
    return sidecars


def to_interchange_xml(name, blob, textures='both', stats=None, names=None):
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
    if t == 'ycd':
        # ⚠ Undecoded channels emit a visible <!-- RESIDUAL/UNPINNED --> marker in the XML - but
        # a file can carry markers and still score xml_ok, so the count must ALSO reach the
        # printed summary (THE_PLAN 5.0; the 51,463-channel lesson: only 2,109 provably decode).
        import ydr2xml, ycd2xml
        ycd2xml.RESIDUALS.clear()
        xml = ycd2xml.ycd_to_xml(ydr2xml.Res.from_bytes(blob)).encode('utf-8')
        if ycd2xml.RESIDUALS and stats is not None:
            for k, n in ycd2xml.RESIDUALS.items():
                key = 'ycd %s (marker emitted, nothing invented)' % k
                stats[key] = stats.get(key, 0) + n
        return stem + '.ycd.xml', xml, ()
    if t == 'yed':
        import ydr2xml, yed2xml
        return stem + '.yed.xml', yed2xml.yed_to_xml(
            ydr2xml.Res.from_bytes(blob)).encode('utf-8'), ()
    if t == 'yld':
        import ydr2xml, yld2xml
        return stem + '.yld.xml', yld2xml.yld_to_xml(
            ydr2xml.Res.from_bytes(blob)).encode('utf-8'), ()
    if t == 'yfd':
        import ydr2xml, yfd2xml
        return stem + '.yfd.xml', yfd2xml.yfd_to_xml(
            ydr2xml.Res.from_bytes(blob)).encode('utf-8'), ()
    if t == 'ynd':
        import ydr2xml, ynd2xml
        return stem + '.ynd.xml', ynd2xml.convert(
            ydr2xml.Res.from_bytes(blob)).encode('utf-8'), ()
    if t == 'ynv':
        import ynv2xml
        return stem + '.ynv.xml', ynv2xml.convert(name, blob, names=names).encode('utf-8'), ()
    if t == 'ypdb':
        import ypdb2xml
        return stem + '.ypdb.xml', ypdb2xml.decode(blob).encode('utf-8'), ()
    if t == 'ypt':
        # rmPtfx ptxFxList (RSC7 v68) -> reference-identical .ypt.xml. Container + all 5
        # dictionaries + KFP layer + all 3 polymorphic rule bodies derived clean-room and
        # verified byte-identical 10/10 (2026-08-06). See ypt2xml docstring.
        # ⚠ 40 behaviour scalars are emitted from UNPINNED CONSTANTS (const across all 10
        # oracles, so no offset was derivable). They reproduce the oracle set exactly but
        # would be WRONG for a file whose real value differs - so every one is COUNTED into
        # stats rather than passing silently. A rising count at scale = go widen the oracles.
        import ydr2xml, ypt2xml
        ypt2xml.CONST_EMITS.clear()
        xml = ypt2xml.convert_res(ydr2xml.Res.from_bytes(blob)).encode('utf-8')
        n_const = sum(ypt2xml.CONST_EMITS.values())
        if n_const and stats is not None:
            stats['ypt behaviour scalars emitted from UNPINNED constants'] = \
                stats.get('ypt behaviour scalars emitted from UNPINNED constants', 0) + n_const
        return stem + '.ypt.xml', xml, ()
    if t == 'yvr':
        import ydr2xml, yvr2xml
        return stem + '.yvr.xml', yvr2xml.yvr_to_xml(
            ydr2xml.Res.from_bytes(blob)).encode('utf-8'), ()
    if t == 'ywr':
        import ydr2xml, ywr2xml
        return stem + '.ywr.xml', ywr2xml.ywr_to_xml(
            ydr2xml.Res.from_bytes(blob)).encode('utf-8'), ()
    if blob[:4] == b'RBF0':
        # RBF0 = RAGE's OLDER binary-XML container - unrelated to META/PSO and NOT an RSC7
        # resource (magic sits at byte 0). Self-delimiting depth-first record stream: u16
        # token = 0xFFFF END / 0xFFFD TEXT / else (type=tok>>12, nameIndex=tok&0x0FFF) with
        # an IMPLICIT name table (first use of an index carries the name inline). Derived in
        # rbf2xml; 71/71 game binaries parse to the exact final byte with a balanced stack.
        # the reference exporter keeps a ".rbf" infix exactly as it keeps ".pso" for a PSIN container.
        import rbf2xml
        ext = type_of(name) or 'rbf'
        return ('%s.%s.rbf.xml' % (stem, ext),
                rbf2xml.convert(name, blob, names=names).encode('utf-8'), ())
    if t == 'fxc':
        # rage compiled shader effect ('rgxe'). the reference exporter does NOT inline the DXBC bytecode: each
        # shader becomes a "<stem>/<ShaderName>.cso" sidecar the XML points at via <File>.
        import fxc2xml
        return (stem + '.fxc.xml', fxc2xml.convert(name, blob).encode('utf-8'),
                fxc2xml.sidecars(name, blob))
    if t == 'mrf':
        # MoVE network (.mrf) -> reference-identical XML. convert_with_report, because the decoder
        # RECORDS every UNPINNED residual and plain convert() threw the list away - the report
        # variant had ZERO callers (THE_PLAN 5.0 audit). Counted, never dropped.
        import mrf2xml
        xml, unpinned = mrf2xml.convert_with_report(name, blob, names=names)
        if stats is not None:
            if unpinned:
                stats['mrf UNPINNED values emitted as markers (single-oracle gaps)'] = \
                    stats.get('mrf UNPINNED values emitted as markers (single-oracle gaps)', 0) \
                    + len(unpinned)
            if mrf2xml.FALLBACK_SIDECAR_ERROR:
                stats['mrf name sidecar unreadable - sidecar-only names degrade to hash_'] = \
                    stats.get('mrf name sidecar unreadable - sidecar-only names degrade to hash_', 0) + 1
        return stem + '.mrf.xml', xml.encode('utf-8'), ()
    if t == 'rel':
        # .rel audio config. RelError = an UNMEASURED family/type: a COUNTED refusal
        # (None == "no converter yet"), never a guessed export.
        import rel2xml
        try:
            return (stem + '.rel.xml',
                    rel2xml.convert(name, blob, names=names, stats=stats).encode('utf-8'), ())
        except rel2xml.RelError as ex:
            if stats is not None:
                stats['rel refused - unmeasured family/type'] = \
                    stats.get('rel refused - unmeasured family/type', 0) + 1
            return None
    if t == 'ybd':
        # A .ybd is a pgDictionary of phBound - and the reference exporter has NO XML export for it,
        # so its "export" is a RAW dump of the DECOMPRESSED resource, not the stored file.
        # MEASURED 2026-08-06 (des_heli_biotech): oracle 40,960 B == Res(blob).sys exactly,
        # while the stored RSC7 is 24,285 B. So parity = emit the inflated segment under
        # the ORIGINAL name (no .xml). gfx is empty in the witnessed case; concatenating
        # sys+gfx reduces to it, and a gfx-carrying ybd is UNWITNESSED (flagged, not guessed).
        import ydr2xml
        r = ydr2xml.Res.from_bytes(blob)
        if r.gfx and stats is not None:
            stats['ybd with a graphics segment - concatenation order UNWITNESSED'] = \
                stats.get('ybd with a graphics segment - concatenation order UNWITNESSED', 0) + 1
        return name, bytes(r.sys) + bytes(r.gfx or b''), ()
    if t == 'ymf' or (blob[:4] == b'PSIN'):
        # PSO ('PSIN') container -> reference-identical XML via the generic pso2xml
        # (schema-driven from the file's own PSCH). MEASURED 2026-08-06 against the oracle
        # set: 38/38 ymf + 2/2 pso + 3/3 PSIN-ymt byte-identical.
        # Name-carrying hash fields (imapName/itypName/Bounds) resolve via the same joaat
        # names dict export already holds; the reference exporter output filename keeps its .pso infix.
        # The last 3 ymf (venice/cityhills_02/cityhills_03 _metadata) closed on ONE string
        # the filename index cannot reverse - see pso2xml.token_names(); its hits are
        # counted into stats, never silent.
        import pso2xml
        xml, warn = pso2xml.pso_to_xml(blob, names=names)
        for k, n in (warn or {}).items():
            if stats is not None:
                stats[k] = stats.get(k, 0) + n
        ext = type_of(name) or 'pso'
        return '%s.%s.pso.xml' % (stem, ext), xml.encode('utf-8'), ()
    if t in ('ytyp', 'ymap', 'ymt'):
        # ⭐ THE EXTRACT/EXPORT CONVERTER SPLIT, CLOSED (2026-08-08, OPEN_ITEMS #000 / Stage C).
        # This branch did not exist: `extract --xml` reported "no converter" for ymap/ytyp
        # while the conformance sweep graded the SAME types byte-identical through `export` -
        # two routes disagreeing about which lanes exist, in the one pipeline whose 2.5.3/5.5
        # guarantee is that targeted and at-scale run the SAME code. The conversion itself is
        # meta2xml.convert_bytes - the identical call `export` and the `meta` pass make.
        # NAMES-GATED by design, not capability: a ytyp stores archetype/asset names as one-way
        # joaat hashes and the reverse table is built from the whole-game filename universe
        # (view manifest). Without it, converting here would bake hash_%08X into names the
        # `meta` pass resolves - so extract WITHOUT --view keeps the binary for `meta`
        # (behaviour unchanged), extract WITH --view converts inline. Container catches
        # (PSIN/RBF0) sit ABOVE this branch - the container decides, not the extension.
        if names is None:
            if stats is not None:
                k = ('meta kept binary (no names table - run `meta` after, or pass '
                     '--view): .' + t)
                stats[k] = stats.get(k, 0) + 1
            return None
        import meta2xml
        try:
            xml, got_kind, w = meta2xml.convert_bytes(blob, stem, names)
        except meta2xml.UnsupportedRoot as ex:
            # a recognised boundary, same as the `meta` pass: well-formed META, no emitter
            # for its root - counted, kept binary, never guessed
            if stats is not None:
                k = 'meta kept binary (no emitter for root %s)' % ex.root_name
                stats[k] = stats.get(k, 0) + 1
            return None
        for k, n in (getattr(w, 'warn', None) or {}).items():
            if stats is not None:
                stats[k] = stats.get(k, 0) + n
        return '%s.%s.xml' % (stem, got_kind), xml.encode('utf-8'), ()
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
        # names: at EXTRACT time the joaat table does not exist yet, so callers pass None
        # and entry names emit hash_%08X, resolved later by `quarry meta` (unchanged).
        # `quarry export` DOES have the table (view-manifest-derived) and passes it -
        # the 2026-08-06 wiring fix: this call hardcoded {} and the export sweep's ydd
        # lane emitted its own stem as hash_F19DE766.
        xml, _n = ydd2xml.to_xml(res, names or {})
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
            # ⚠ DEAD PATH (AST-verified 2026-08-06, THE_PLAN 5.0 audit): every FragmentError
            # raise site now lives in yft2xml's superseded pre-oracle functions, unreachable
            # from convert() - this except cannot fire. Kept per Preserve-Don't-Delete pending
            # Matt's removal ruling. (If it ever revives, note the retry below calls
            # convert(extras=False), which ignores `extras` and would raise identically.)
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
    # No branch matched: genuinely no converter for this type. The CAUSE is counted HERE so
    # callers' generic kept-binary counters can stay cause-neutral - the META branch above
    # returns None for a names-gated reason with its own counter, and labelling that as
    # "no converter" in the caller was a false statement (2026-08-08).
    if stats is not None:
        k = 'no converter for this type yet: .' + (t or '?')
        stats[k] = stats.get(k, 0) + 1
    return None


_TAG_SAFE = re.compile(r'[^a-z0-9]+')


def source_tag(chain, blob):
    """A STABLE identity for one source instance: the archive it came from + 6 hex of its own
    content. ⛔ USED FOR THE PROVENANCE LEDGER ONLY - it must NEVER be written into a filename
    (Matt, 2026-08-07: the content keeps the name it has in the game files; identity belongs in
    the folder structure, and that layout is his call).

    ⭐ WHY (settled with Matt 2026-08-07, ENGINEERING_LOG § corpus identity). A flat
    <slot>/<ext>/<name> corpus cannot express WHICH archive an asset came from, and 22,826
    (slot,name) groups collide - 54,282 copies. It is overwhelmingly a PED/CLOTHING shape
    (ydd 25.8%, ytd 28.0%, vs <=0.5% in the mapping lanes): `head_000_r.ydd` exists 135 times
    because 135 PED MODELS each ship one, and the ped is exactly what the archive encodes.
    The old `~1, ~2 …` came from WALK ORDER, so the same asset could land on a different name
    between runs (the resume-duplication bug made that concrete) and no name could be cited.

    archive slug  -> readable: you can see which ped/pack an instance belongs to.
    content hash  -> makes it UNIQUE and ORDER-FREE: identical bytes always produce the same
                     tag, and two different assets from one archive still separate. (Archive
                     alone disambiguates only 81.7%; the inner directory the view manifest
                     records is not tracked by this walker, so content closes the rest.)
    """
    last = (chain or '').rstrip('/').split('/')[-1]
    if last.lower().endswith('.rpf'):
        last = last[:-4]
    slug = _TAG_SAFE.sub('_', last.lower()).strip('_')[:40] or 'src'
    return '%s_%s' % (slug, hashlib.sha1(blob).hexdigest()[:6])


_PROV_INDEX = None


def provenance_index(out_root):
    """(slot, type, filename) -> source archive chain, from the provenance ledger.

    Built once per run and kept in memory: --refresh has to answer "did the SAME source write
    this exact path?" for every file, and re-reading a 300k-line ledger per file is quadratic.
    """
    global _PROV_INDEX
    if _PROV_INDEX is None:
        idx = {}
        try:
            with open(os.path.join(out_root, '_PROVENANCE.jsonl'), 'r', encoding='utf-8') as f:
                for line in f:
                    try:
                        r = json.loads(line)
                    except ValueError:
                        continue
                    idx[(r.get('slot'), r.get('type'), r.get('file'))] = r.get('archive')
        except OSError:
            pass
        _PROV_INDEX = idx
    return _PROV_INDEX


def file_into(out_root, slot, name, blob, stats=None, skip_existing=False, chain=None,
              refresh=False, subdir=None, overwrite=False):
    """File one blob by type into a precedence slot.

    Filing is FLAT by basename inside <slot>/<ext>/, which means two same-named files from
    different archives in the SAME slot collide. That is not hypothetical: the 24 base
    archives share one namespace and there are ~84k ydrs across the game. Silently
    overwriting loses build-accurate data with no trace, so a collision now keeps the FIRST
    copy, writes the loser as <stem>~<n><ext>, and is COUNTED so the run reports it.
    (Load-order precedence ACROSS slots is still what the numbered tree encodes; this only
    disambiguates within one slot.)

    ⭐ `subdir` = the game's OWN in-archive folder for this leaf (per-ped-per-DLC layout,
    Matt's determined ruling): filing becomes <slot>/<ext>/<subdir>/<name> — identity in the
    FOLDER, the filename untouched. Same-named files of DIFFERENT peds stop colliding because
    the game itself files them apart; a collision INSIDE one subdir still takes the ~N path
    (same ped, same name, different bytes = still build-accurate data to keep).
    """
    d = os.path.join(out_root, slot, type_of(name))
    if subdir:
        d = os.path.join(d, subdir.replace('/', os.sep))
    os.makedirs(d, exist_ok=True)
    target = os.path.join(d, name)
    if overwrite:
        # ⭐ --overwrite: REGENERATE THE CORPUS IN PLACE (Matt's ruling 2026-08-09: "I don't
        # really care if you overwrite the old ones in place or delete them and export new
        # ones, it's all the same to me"). The FIRST write of a path in THIS run claims it
        # and overwrites whatever generation sat there; later writes of the SAME path in the
        # same run are genuine instance collisions and claim the next ~N slot - overwriting
        # the OLD generation's ~N of the same rank, because the archive walk is
        # deterministic (control-proven: qualified names identical across walk orders), so
        # rank-k this run IS rank-k last run. Old ~N beyond this run's instance count are
        # left in place and countable afterwards as pre-run-mtime leftovers - counted by
        # the post-run staleness sweep, never silently absorbed.
        # Byte-identical rewrites are SKIPPED (counted), so an overwrite run is idempotent
        # and cheap on the unchanged majority - and provenance is appended for EVERY file
        # it touches or verifies, rebuilding the ledger with full coverage.
        wset = stats.setdefault('_overwrite_written', set()) if stats is not None else set()
        stem0, ext0 = split_type_ext(name)
        tkey = target.lower()
        n = 0
        while tkey in wset:
            n += 1
            target = os.path.join(d, f'{stem0}~{n}{ext0}')
            tkey = target.lower()
        wset.add(tkey)
        existed = os.path.isfile(target)
        if existed:
            try:
                with open(target, 'rb') as _f:
                    if _f.read() == blob:
                        if stats is not None:
                            stats['overwrite: already current'] = \
                                stats.get('overwrite: already current', 0) + 1
                            if chain:
                                _s, _e = split_type_ext(name)
                                stats.setdefault('provenance', []).append(
                                    {'slot': slot, 'type': type_of(name),
                                     'file': (subdir + '/' if subdir else '')
                                             + os.path.basename(target),
                                     'qualifiedName': '%s~%s%s'
                                                      % (_s, source_tag(chain, blob), _e),
                                     'sourceName': name, 'archive': chain,
                                     'sha1': hashlib.sha1(blob).hexdigest()})
                        return None
            except OSError:
                pass
        with open(target, 'wb') as f:
            f.write(blob)
        if stats is not None:
            k = ('overwritten (superseded generation)' if existed
                 else 'written (new this generation)')
            stats[k] = stats.get(k, 0) + 1
            if chain:
                _s, _e = split_type_ext(name)
                stats.setdefault('provenance', []).append(
                    {'slot': slot, 'type': type_of(name),
                     'file': (subdir + '/' if subdir else '') + os.path.basename(target),
                     'qualifiedName': '%s~%s%s' % (_s, source_tag(chain, blob), _e),
                     'sourceName': name, 'archive': chain,
                     'sha1': hashlib.sha1(blob).hexdigest()})
        return os.path.basename(target)
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
            # ⛔ AND 'SAME LENGTH' IS NOT 'SAME BYTES' (fixed 2026-08-05). The rule three lines up is
            # already correct - resume may only skip a file whose bytes we would have written anyway -
            # but the test only compared os.path.getsize() to len(blob), so two genuinely different
            # assets that happen to be the same size read as "already present" and the loser was
            # dropped without ever reaching the collision path or the counter. MEASURED exposure on
            # the ped lane: 128 of 1,060 ytd collision groups (177 files) hold content-distinct
            # manifests sharing a byte length - e.g. accs_diff_000_b_uni, 20 files, 5 distinct sha256
            # across only 2 distinct sizes. That is the silent-drop class, and a size check cannot
            # see it. Compare the CONTENT; the size check stays only as the cheap reject that keeps
            # the read off the common path.
            try:
                same = os.path.getsize(target) == len(blob)
                if same:
                    with open(target, 'rb') as _f:
                        same = _f.read() == blob
            except OSError:
                same = False
            if same:
                if stats is not None:
                    stats['resumed'] = stats.get('resumed', 0) + 1
                return None
        # ⭐ --refresh: MOVE THE CORPUS TO A NEWER CONVERTER GENERATION (2026-08-07).
        # ⛔ THE PROBLEM IT SOLVES, control-test-proven: after a converter fix, re-extracting wrote
        # the new output as `<stem>~1<ext>` and left the UNSUFFIXED file - the one `resolve`
        # hardlinks and every consumer reads - holding the STALE bytes, reported only as a
        # benign-looking `collisions: 1`. There was NO supported way to bring a corpus up to date
        # short of deleting it, so a lane grade silently expired the moment its emitter changed.
        # ⚠ OPT-IN AND NARROW BY DESIGN: it overwrites ONLY the same file path from the SAME
        # source instance (`chain`), which is exactly the distinction the provenance ledger
        # records. Two genuinely different assets sharing a basename still take the ~N collision
        # path - refresh must never become a silent overwrite of build-accurate data.
        # ⛔⛔ THE SAME-SOURCE TEST IS THE WHOLE SAFETY PROPERTY - IT MUST BE MEASURED, NOT ASSUMED.
        # Shipped 2026-08-07 as `same_source = True  # no ledger yet -> first refresh is trusted`,
        # i.e. a hardcoded stub, so --refresh overwrote ANY existing file and the collision path
        # never ran. MEASURED DAMAGE from one run over ymap+ytyp: 11 of 11 collision groups
        # collapsed to identical (bh1_occl_00..07.ymap, cutsobjects/icons/ped_props.ytyp) - the
        # distinct FIRST copy was destroyed in every one, and the run printed `collisions: 0`.
        # The control test missed it because cases 3 and 4 BOTH passed refresh=False: the negative
        # control was run twice and neither exercised this branch.
        # ⇒ refresh may overwrite ONLY when the ledger proves the same source wrote this exact
        #   path. Unprovable is REFUSED (falls through to the collision path) and counted, because
        #   the safe default when identity is unknown is to keep both copies, not to guess.
        if refresh and chain:
            idx = provenance_index(out_root)
            # the ledger's `file` value carries the subdir for ped-foldered content, so the
            # refresh key must too - a bare basename would be ambiguous across ped folders again
            key = (slot, type_of(name),
                   (subdir + '/' if subdir else '') + os.path.basename(target))
            prior = idx.get(key)
            same_source = prior is not None and prior == chain
            if stats is not None and not same_source:
                k = ('refresh refused (no provenance record - cannot prove same source)'
                     if prior is None else
                     'refresh refused (different source instance - kept as collision)')
                stats[k] = stats.get(k, 0) + 1
            if same_source:
                # ⛔ "new converter output" is a CLAIM. Compare before asserting it: the first
                # version counted every file it touched, so a run that changed nothing still
                # reported 22,152 files "refreshed (new converter output)".
                try:
                    with open(target, 'rb') as _f:
                        unchanged = _f.read() == blob
                except OSError:
                    unchanged = False
                if unchanged:
                    if stats is not None:
                        stats['refresh: already current'] = \
                            stats.get('refresh: already current', 0) + 1
                    return None
                if stats is not None:
                    stats['refreshed (same source, new converter output)'] = \
                        stats.get('refreshed (same source, new converter output)', 0) + 1
                with open(target, 'wb') as f:
                    f.write(blob)
                written = os.path.basename(target)
                idx[key] = chain
                if stats is not None and chain:
                    _stem, _ext = split_type_ext(name)
                    stats.setdefault('provenance', []).append(
                        {'slot': slot, 'type': type_of(name),
                         'file': (subdir + '/' if subdir else '') + written,
                         'qualifiedName': '%s~%s%s' % (_stem, source_tag(chain, blob), _ext),
                         'sourceName': name, 'archive': chain,
                         'sha1': hashlib.sha1(blob).hexdigest()})
                return written
        stem, ext = split_type_ext(name)
        # ⛔⛔ RESUME MUST ALSO RECOGNISE ITS OWN COLLISION SIBLINGS (fixed 2026-08-07, Phase 5).
        # The resume check above only asked about the BASE name. A colliding asset is written as
        # <stem>~<n>, so on the next resumed run the base name existed with DIFFERENT bytes, the
        # code fell straight to the collision path, found ~1 taken, and wrote ~2 - A BYTE-FOR-BYTE
        # DUPLICATE OF ~1. Every resumed run then added another copy, unbounded, while the summary
        # reported them as fresh "collisions". MEASURED: a --resume pass over an already-extracted
        # ymap/ytyp lane produced icons~2.ytyp and ped_props~2.ytyp, sha256-identical to their ~1.
        # The rule the base-name branch states is the right one - resume may only skip a file whose
        # bytes we would have written anyway - it simply was not applied to the ~N namespace.
        if skip_existing:
            n = 1
            while True:
                sib = os.path.join(d, f'{stem}~{n}{ext}')
                if not os.path.exists(sib):
                    break
                try:
                    same = os.path.getsize(sib) == len(blob)
                    if same:
                        with open(sib, 'rb') as _f:
                            same = _f.read() == blob
                except OSError:
                    same = False
                if same:
                    if stats is not None:
                        stats['resumed'] = stats.get('resumed', 0) + 1
                    return None
                n += 1
        if stats is not None:
            stats['collisions'] = stats.get('collisions', 0) + 1
        # ⛔⛔ DO NOT PUT SOURCE IDENTITY IN THE FILENAME (Matt, 2026-08-07). A first cut wrote
        # `<stem>~<archiveslug>_<hash><ext>` here; he rejected it: **the content keeps the name it
        # has in the game files.** Identity belongs in the FOLDER STRUCTURE (a folder per ped per
        # DLC) - his direction - and the shape of that layout is HIS decision to make, not an
        # agent's. Until he rules, behaviour is unchanged from before: first writer keeps the
        # name, the rest get ~N, and every instance is recorded in _PROVENANCE.jsonl (which adds
        # information without touching any name).
        # ⚠ NOTE the `~N` spelling ALSO mutates a game name - that predates this work and is the
        # very thing the folder layout should retire.
        n = 1
        while os.path.exists(os.path.join(d, f'{stem}~{n}{ext}')):
            n += 1
        target = os.path.join(d, f'{stem}~{n}{ext}')
    with open(target, 'wb') as f:
        f.write(blob)
    written = os.path.basename(target)
    # PROVENANCE: every emitted file records where it came from, so "which DLC / which archive
    # is this instance" is answerable programmatically instead of by inspection. Buffered in
    # stats and written once at the end of the run (see cmd_extract) - one line per file.
    if stats is not None and chain:
        # ⚠ `file` is order-dependent BY DESIGN for exactly one copy: the first writer of a
        # colliding name keeps the bare <stem><ext>, because that is the slot-internal winner the
        # flat corpus (and RUDE's lookup) reads. Proven by control test: qualified names are
        # identical across walk orders, but WHICH instance is unqualified is not.
        # `qualifiedName` fixes that for citation - EVERY instance, winner included, gets the
        # same stable source-derived identity, so an asset can be named and re-found even when
        # its file on disk is the unqualified winner.
        stem, ext = split_type_ext(name)
        stats.setdefault('provenance', []).append(
            {'slot': slot, 'type': type_of(name),
             'file': (subdir + '/' if subdir else '') + written,
             'qualifiedName': f'{stem}~{source_tag(chain, blob)}{ext}',
             'sourceName': name, 'archive': chain,
             'sha1': hashlib.sha1(blob).hexdigest()})
    return written


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


def walk_archive(r, oodle, depth=0, max_depth=2, stats=None, path='', nested_only=None):
    """Yield (name, blob, chain, folder) for every FILE in this archive, DESCENDING into
    nested .rpf.

    `nested_only` = fnmatch pattern for NESTED archive names: when set, only matching nested
    archives are descended and top-level leaves are skipped — the staged-migration scalpel
    (regenerate ONE container class without touching the rest of a 2 GB parent archive).

    `chain` is the archive chain the file came from ("x64e.rpf/mp_f_freemode.rpf"). It was
    tracked here all along for error messages and simply never handed to the caller, which is
    why filing could not tell two same-named assets apart - see file_into's identity note.

    This is the difference between 624 files and the real corpus: the base archives are
    mostly containers - x64g.rpf is 2.4GB in FIVE top-level entries, all of them nested
    archives - and essentially every .ydr/.ybn/.ytyp/.ymap in the game lives at depth 2.
    A flat walk finds ZERO map assets, which is exactly what the first run produced.
    """
    # ⭐ PER-PED-PER-DLC (Matt, determined 2026-08-07, reaffirmed 2026-08-08): same-named ped
    # files are not copies — each belongs to a particular ped, and the game says WHOSE in its
    # own TOC: streamedpedprops-class archives file every leaf under a per-ped DIRECTORY
    # (player_zero_p/p_ears_000.ydd). The walk therefore yields that in-archive folder so
    # filing can MIRROR the game structure (folder identity, filenames untouched). Top-level
    # archives' folders (data/, levels/…) are organizational, not identity — the caller only
    # applies the folder for leaves of NESTED archives (depth ≥ 1).
    folders = _tree_paths(r.entries) if depth >= 1 else None
    for i, e in enumerate(r.entries):
        if e['dir']:
            continue
        name = e['name']
        if nested_only and not name.lower().endswith('.rpf'):
            continue        # scoped migration: leaves outside a matching container are skipped
                            # (the filter clears once a matching nested archive is entered)
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
            sub_filter = nested_only
            if nested_only:
                import fnmatch as _fn
                if _fn.fnmatch(name.lower(), nested_only.lower()):
                    sub_filter = None       # matched: the whole subtree is in scope
            yield from walk_archive(sub, oodle, depth + 1, max_depth, stats,
                                    f'{path}/{name}', sub_filter)
            continue
        yield name, blob, path, (folders[i] if folders else '')


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
    whatever directories existed, and the whole-game filebase held 175 dirs for 92 packs - 83 left
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

    if getattr(a, 'view', None):
        # ⭐ THE_PLAN 5 (2026-08-06): ONE names authority for targeted AND at-scale. A project
        # walk only knows the stems that were EXTRACTED, so a lane-scoped project (Stage A =
        # ymap+ytyp without ytd/ycd/...) resolves from a smaller universe than `export` did and
        # breaks oracle parity BY CONSTRUCTION (a ytyp's textureDictionary names ytd stems).
        # --view resolves from the same freshness-gated view manifest export uses - identical
        # rules, identical universe (same shared core: meta2xml.load_names_from_stems).
        if not getattr(a, 'game', None):
            print('STOP: --view needs --game to freshness-gate the manifest against the install')
            return 1
        print('names    : deriving the joaat table from the view manifest (freshness-gated) ...')
        names = _names_from_view(a.view, a.game)
    else:
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
    # against load_names over the whole-game filebase: 183/183 present). The XML holding the hashes
    # was written 2026-07-27 by an emitter that dropped <extensions> entirely; today's meta2xml
    # raises `unknown extension type 'hash_32818195' - refusing to emit a guess` on the very same
    # binary (the whole-game filebase, 00_base/ymap/po1_07_strm_1.ymap, 207 entities), so this run
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
                    # old binary-XML container).
                    # ⛔ CORRECTED 2026-08-06: this used to claim the RBF ymts were "all
                    # bink_cnt_* video metadata - nothing map-relevant inside". WRONG on both
                    # counts. Over 71 RBF0 binaries measured: 40 are CMapTypes composite-
                    # entity-type manifests under levels/gta5/destruction (lodDist, bbMin/
                    # bbMax, bsCentre, animations, particle effects = squarely map data), 31
                    # are CMovieSubtitleContainer. They ARE readable now (rbf2xml); this pass
                    # still counts-and-skips only because they are not META, like PSIN above.
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
# The three lanes whose XML can NAME a texture. Kept apart from TXD_BEARING_DIRS because they
# answer different questions: these are the askers, that is where the answers are stored.
DRAWABLE_DIRS = ('ydr', 'ydd', 'yft')

_TEX_REF_RE = re.compile(r'type="Texture">\s*<Name>([^<]+)</Name>', re.S)
_XML_NAME_RE = re.compile(r'<Name>([^<]+)</Name>')


def _scope_match(stem, fn, patterns):
    """True when this drawable is inside the requested scope. Patterns are fnmatch, matched
    case-insensitively against BOTH the asset stem (`dt1_13_build1`) and the full filename, so
    `dt1_13_*` and `dt1_13_build1.ydr.xml` both work."""
    import fnmatch
    s, f = stem.lower(), fn.lower()
    return any(fnmatch.fnmatchcase(s, p) or fnmatch.fnmatchcase(f, p) for p in patterns)


def scan_drawable_references(ref_roots, scope=None):
    """Every texture NAME the drawables ask for -> (wanted, drawables_scanned, kinds_seen).

    ⭐ SHARED BY `--prune` AND `--decode-referenced` DELIBERATELY. They are the two halves of one
    answer - prune deletes what is not referenced, decode writes what is - so two implementations
    would eventually disagree and a decode would be followed by a prune that deletes exactly what
    it had just written. One function is the only way that stays impossible.

    `scope` = None for the whole corpus, or a list of fnmatch patterns (see _scope_match). A scope
    is what makes a referenced-pixel decode cheap FOREVER: you pay for the area you are authoring,
    not for the game. `kinds_seen` records which drawable lanes EXIST in the roots (directory
    presence, not match count) - prune's coverage guard depends on that distinction.
    """
    wanted, drawables, kinds_seen, stems = set(), 0, set(), set()
    for root in ref_roots:
        for kind in DRAWABLE_DIRS:
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
                stem = split_type_ext(fn)[0]
                if scope and not _scope_match(stem, fn, scope):
                    continue
                try:
                    with open(os.path.join(d, fn), encoding='utf-8', errors='replace') as fh:
                        txt = fh.read()
                except OSError:
                    continue
                drawables += 1
                stems.add(stem.lower())
                wanted.update(t.strip().lower() for t in _TEX_REF_RE.findall(txt))
    return wanted, drawables, kinds_seen, stems


TXD_NAME_INDEX = '_TXDNAMES.json'
TXD_NAME_INDEX_VERSION = 1


def _manifest_fingerprint(ref_roots):
    """A cheap, HONEST identity for the set of emitted `.ytd.xml` manifests -> (sha256, count).

    Every manifest's name, byte size and mtime, from ONE directory read per lane (os.scandir
    carries the stat data on Windows, so this costs a listing, not 84,000 opens). Anything added,
    removed, re-emitted or resized changes the digest.

    ⛔ WHY A DIGEST AND NOT A TIMESTAMP: the cache it keys feeds `--prune`, which DELETES. A cache
    keyed on "is it newer than the folder" would happily survive a re-`meta` that rewrote every
    manifest in place, and prune would then delete pixels against a stale keep set. A mismatch here
    forces a rebuild rather than printing a warning nobody reads.
    """
    h = hashlib.sha256()
    n = 0
    for root in ref_roots:
        for sub in TXD_BEARING_DIRS:
            d = os.path.join(root, sub)
            if not os.path.isdir(d):
                continue
            rows = []
            # ⭐ RECURSIVE since the per-ped layout: manifests can live one (or more) folder
            # levels down (<kind>/<ped>/<stem>.ytd.xml). The row key carries the relative path
            # so a ped-folder rename changes the digest exactly like a stem rename does.
            for dp, _dirs, fs in os.walk(d):
                relbase = os.path.relpath(dp, d)
                for fn in fs:
                    if not fn.lower().endswith('.ytd.xml'):
                        continue
                    try:
                        st = os.stat(os.path.join(dp, fn))
                    except OSError:
                        continue
                    rel = fn if relbase == '.' else f'{relbase}/{fn}'
                    rows.append('%s|%d|%d' % (rel.replace(os.sep, '/').lower(),
                                              st.st_size, int(st.st_mtime)))
            rows.sort()
            n += len(rows)
            # ⚠ NORMALISE THE ROOT. Caught 2026-08-05 by watching a 23-second index rebuild that
            # should have been a cache hit: the same folder reached as "F:/x/_resolved" and
            # "F:/x\\_resolved" hashed differently, so the cache missed on every run whose caller
            # spelled the path with a different separator - a silent, permanent 23 s tax that
            # looked like the cache simply not working.
            h.update(('\n%s|%s\n' % (os.path.normcase(os.path.abspath(root)), sub))
                     .encode('utf-8'))
            h.update('\n'.join(rows).encode('utf-8'))
    return h.hexdigest(), n


def txd_name_index(ref_roots, out_root=None, verbose=True):
    """{'<kind>/<stem>': [texture names, manifest order and casing]} for every emitted dictionary.

    ⭐ CACHED, because this is the join that makes a SCOPED decode possible and it is the only
    expensive part of it: answering "which dictionary holds texture T" means reading every
    `.ytd.xml` in the corpus - 84,000 files on the current one - and a scoped run needs a handful.
    Paying that once and keying the cache on `_manifest_fingerprint` is what makes the second and
    every later scoped run cheap. `out_root=None` disables the cache entirely (always re-read).
    """
    fp, count = _manifest_fingerprint(ref_roots)
    cache = os.path.join(out_root, '_manifest', TXD_NAME_INDEX) if out_root else None
    if cache and os.path.isfile(cache):
        try:
            with open(cache, encoding='utf-8') as f:
                doc = json.load(f)
            if (doc.get('version') == TXD_NAME_INDEX_VERSION
                    and doc.get('fingerprint') == fp):
                if verbose:
                    print(f'txd name index    : {count:,} manifests (cached, fingerprint match)')
                return doc['dicts'], count
        except Exception:
            pass
    if verbose:
        print(f'txd name index    : reading {count:,} manifests (first run for this corpus '
              f'state; cached afterwards) ...', flush=True)
    dicts = {}
    for root in ref_roots:
        for sub in TXD_BEARING_DIRS:
            d = os.path.join(root, sub)
            if not os.path.isdir(d):
                continue
            # recursive: per-ped folders hold manifests one level down; the key carries the
            # ped-relative path ("<kind>/<ped>/<stem>") so two peds' same-named dictionaries
            # stay distinct entries instead of the last one read silently winning
            for dp, _dirs, fs in os.walk(d):
                relbase = os.path.relpath(dp, d)
                for fn in fs:
                    if not fn.lower().endswith('.ytd.xml'):
                        continue
                    try:
                        with open(os.path.join(dp, fn), encoding='utf-8',
                                  errors='replace') as fh:
                            txt = fh.read()
                    except OSError:
                        continue
                    rel = fn if relbase == '.' else \
                        f'{relbase}/{fn}'.replace(os.sep, '/')
                    dicts['%s/%s' % (sub, rel[:-len('.ytd.xml')])] = \
                        [n.strip() for n in _XML_NAME_RE.findall(txt)]
    if cache:
        try:
            os.makedirs(os.path.dirname(cache), exist_ok=True)
            tmp = cache + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump({'version': TXD_NAME_INDEX_VERSION, 'fingerprint': fp,
                           'roots': list(ref_roots), 'dicts': dicts}, f)
            os.replace(tmp, cache)
        except OSError as e:
            print(f'  ! could not cache the txd name index ({e}) - it will be rebuilt next run')
    return dicts, count


def scan_txd_manifests(ref_roots, wanted, out_root=None, verbose=True):
    """Which dictionaries hold the wanted textures -> (holdings, manifests_scanned).

    holdings maps "<kind>/<stem-lower>" -> {'kind','stem','total','needed'} where `needed` is the
    SUBSET of that dictionary's texture names the drawables actually asked for, in manifest order
    and with the manifest's own casing (the casing becomes a filename).

    ⭐ The per-dictionary SUBSET is the whole point of the decode lane. `--prune` only ever needed
    the yes/no ("is this dictionary referenced at all"), so it threw the subset away; decoding a
    referenced dictionary in full would still decode textures nothing names - measured on the
    current corpus that is most of them, because a ytd is a shared pool.
    """
    dicts, manifests = txd_name_index(ref_roots, out_root, verbose)
    holdings = {}
    for key, names in dicts.items():
        need = [n for n in names if n.lower() in wanted]
        if not need:
            continue
        sub, rel = key.split('/', 1)
        # per-ped layout: rel may be "<ped>/<stem>" - keep the STEM bare (it is the source-name
        # join and the pixel-folder name) and carry the ped dir separately
        pdir, _, stem = rel.rpartition('/')
        holdings['%s/%s' % (sub, rel.lower())] = {
            'kind': sub, 'stem': stem, 'dir': pdir, 'total': len(names), 'needed': need}
    return holdings, manifests


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

    # 1) every texture NAME the drawables ask for
    #    2) which dictionaries hold them
    # Both are the shared scans - see scan_drawable_references for why they are not inlined here.
    if getattr(a, 'decode_referenced', False):
        return decode_referenced(a, out, resolved, ref_roots)
    wanted, drawables, kinds_seen, _stems = scan_drawable_references(ref_roots)
    print(f'drawables scanned : {drawables:,}   distinct textures referenced: {len(wanted):,}')
    holdings, manifests = scan_txd_manifests(ref_roots, wanted, out)
    needed = {h['stem'].lower() for h in holdings.values()}
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


# ------------------------------------------------------------------ referenced-pixel decode
# ⭐⭐ WHY THIS LANE EXISTS (Matt's decision, 2026-08-05, verbatim):
#   "if this is to create the MM then we'll do option 1. If its simply to create the MI for the use
#    in engine, we'll do option 3 (C). RUDE should be able to build the Material Instances as
#    needed on import and project build."
# The proof that C is the right answer is on disk today: the 38 generated master materials exist
# RIGHT NOW while the corpus holds ZERO texture pixels. Masters are generated from the shader .fxc
# vocabulary (sampler signatures), not from image data - so pixels are needed ONLY to build the
# Texture2D assets an MI binds at import time. That makes the correct decode SELECTIVE and
# ON-DEMAND, which is exactly what `quarry/README.md` said did not exist yet:
#   "Decoding ONLY the referenced pixels from a manifests-only run is not implemented yet - today
#    the choices are extract-with-pixels-then-prune, or a targeted re-extract."
DECODE_LEDGER = '_DECODED.json'
# Bump when ANYTHING that changes the bytes of a written pixel file changes (ytd2xml.decode_png,
# dds_header, safe_name). Every ledger row carries it and a row whose contract differs is treated
# as unverified: the texture is re-decoded and byte-compared instead of trusted.
DECODE_CONTRACT = 1
SRC_INDEX_DIR = '_srcindex'
SRC_INDEX_VERSION = 1
# The binaries a `.ytd.xml` manifest can have been decoded FROM. A standalone dictionary comes from
# a .ytd; an `X__embedded.ytd.xml` comes from X's own drawable binary (ShaderGroup+0x08).
SRC_EXTS = ('.ytd', '.ydr', '.ydd', '.yft')
EMBEDDED_INFIX = '__embedded'


def _sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def _sha256_file(p):
    h = hashlib.sha256()
    try:
        with open(p, 'rb') as f:
            for chunk in iter(lambda: f.read(1 << 20), b''):
                h.update(chunk)
    except OSError:
        return None
    return h.hexdigest()


def manifest_source_name(kind, stem):
    """The BINARY that a `<stem>.ytd.xml` sitting in `<kind>/` was decoded from, or None.

    Returning None is a REFUSAL, not a fallback: guessing a source would decode some other asset's
    pixels into this dictionary's folder, and both files are valid so nothing downstream could see
    it. The caller counts the refusal by class.
    """
    if kind == 'ytd':
        # A standalone dictionary. An `__embedded` manifest never lands here (extract files it in
        # the DRAWABLE's folder precisely so it cannot collide with a real dictionary of the same
        # name), so one in `ytd/` is a shape we cannot attribute to a source type.
        return None if stem.lower().endswith(EMBEDDED_INFIX) else stem + '.ytd'
    if kind in DRAWABLE_DIRS:
        if not stem.lower().endswith(EMBEDDED_INFIX):
            return None
        return stem[:-len(EMBEDDED_INFIX)] + '.' + kind
    return None


def read_source_dictionary(kind, blob):
    """The texture dicts behind one manifest, read from its source binary.

    ⭐ Every branch here calls the SAME reader the extract path uses (ytd2xml.read_textures, via
    ydr2xml.embedded_textures for the drawable lanes) at the SAME offsets, and the ydd merge
    repeats embedded_texture_sidecars' de-duplication rule exactly - because the names it produces
    become the FILENAMES the manifest already advertises. A second implementation that drifted by
    one de-dup would write pixels under names nothing looks for.
    """
    import ytd2xml
    if kind == 'ytd':
        res = ytd2xml.Res.from_bytes(blob)
        res.require_version(13, 'texture dictionary')
        return ytd2xml.read_textures(res)
    import ydr2xml
    if kind == 'ydr':
        return ydr2xml.embedded_textures(ydr2xml.Res.from_bytes(blob))
    if kind == 'yft':
        import yft2xml
        res = yft2xml.Res.from_bytes(blob)
        dbase = yft2xml.main_drawable_base(res)
        if dbase is None:
            raise ValueError('fragment main drawable pointer does not resolve')
        return ydr2xml.embedded_textures(res, base=dbase)
    if kind == 'ydd':
        import ydd2xml
        res = ydd2xml.Res.from_bytes(blob)
        out, seen = [], set()
        for _h, off in ydd2xml.entry_offsets(res):
            for t in ydr2xml.embedded_textures(res, base=off):
                k = t['name'].lower()
                if k not in seen:
                    seen.add(k)
                    out.append(t)
        return out
    raise ValueError(f'no source reader for kind {kind!r}')


def slot_archives(out_root, game_root):
    """{slot: [archive paths]} - which archives each precedence slot was extracted FROM, in the
    same order `extract` walked them.

    ⭐ The DLC order comes from THIS PROJECT'S `_FILEBASE.json`, not from a fresh derivation. The
    slot names on disk encode the order that ran; re-deriving it could disagree (that is exactly
    the 175-directories-for-92-packs failure `precedence_slots` documents) and we would then open
    the wrong pack's archive for a name.
    """
    base, upd, dlc_dirs = find_sources(game_root)
    man = {}
    try:
        with open(os.path.join(out_root, '_FILEBASE.json')) as f:
            man = json.load(f)
    except Exception:
        pass
    m = {'00_base': [os.path.join(game_root, n) for n in base], '10_update': list(upd)}
    by_name = {os.path.basename(d).lower(): d for d in dlc_dirs}
    for p in (man.get('dlcPacks') or []):
        if not isinstance(p, dict):
            continue
        d = by_name.get(str(p.get('name', '')).lower())
        if not d:
            continue
        found = sorted((f for f in os.listdir(d)
                        if f.lower().startswith('dlc') and f.lower().endswith('.rpf')
                        and os.path.isfile(os.path.join(d, f))),
                       key=lambda f: (len(f), f.lower()))
        m[os.path.join('20_dlc', '%03d_%s' % (p['order'], p['name']))] = \
            [os.path.join(d, f) for f in found]
    return m


def _index_one(r, oodle, entries, arch_key, depth=0, max_depth=2, path=''):
    """Record name -> location for every FILE of interest, WITHOUT inflating the leaves.

    ⛔ THE TRAVERSAL ORDER IS LOAD-BEARING and is walk_archive's, entry by entry, recursing inline.
    `extract` files the FIRST copy of a colliding basename under the plain name and renames the
    rest to `~N`, and `resolve` then keeps the un-suffixed one - so "first in this order" IS the
    file that became `_resolved/<kind>/<stem>`. A different order (a LIFO stack, say) silently
    indexes a DIFFERENT asset under the same name, and every byte it then decodes is wrong while
    looking perfectly healthy. setdefault is what makes first win.
    """
    for e in r.entries:
        if e['dir']:
            continue
        name = e['name']
        low = name.lower()
        if low.endswith('.rpf'):
            if depth >= max_depth:
                continue
            try:
                blob = r.payload(e, oodle)
                sub = Rpf(f'{path}/{name}', r.keys, r.tables, data=blob, name=name,
                          aes_key=getattr(r, 'aes_key', None))
                sub.read_toc()
                if not sub.sane():
                    continue
            except Exception:
                continue        # AES packs and unreadable nests are reported by `extract`, and a
                                # name we cannot index simply stays a counted decode refusal later
            _index_one(sub, oodle, entries, arch_key, depth + 1, max_depth, f'{path}/{name}')
            continue
        if low.endswith(SRC_EXTS):
            entries.setdefault(low, arch_key)


def source_index(out_root, slot, archives, keys, tables, aes_key, oodle, wants, verbose=True):
    """{lowercase source filename: archive path} for one slot, built lazily and CACHED.

    ⭐ INCREMENTAL BY DESIGN. Indexing 00_base means reading 24 archives (~40 GB); a scoped decode
    usually needs one of them. So archives are indexed in extract order and the walk STOPS as soon
    as every wanted name is located, persisting what it learned. A later run needing a name that is
    not in the cache resumes from the next un-indexed archive. First-wins is preserved because the
    order is never revisited.
    """
    d = os.path.join(out_root, '_manifest', SRC_INDEX_DIR)
    os.makedirs(d, exist_ok=True)
    cache = os.path.join(d, slot.replace(os.sep, '_').replace('/', '_') + '.json')
    doc = {'version': SRC_INDEX_VERSION, 'indexed': [], 'entries': {}}
    try:
        with open(cache) as f:
            got = json.load(f)
        if got.get('version') == SRC_INDEX_VERSION:
            doc = got
    except Exception:
        pass
    entries = doc['entries']
    done = list(doc['indexed'])
    remaining = [p for p in archives if p not in done]
    outstanding = {w for w in wants if w not in entries}
    for p in remaining:
        if not outstanding:
            break
        if verbose:
            print(f'  index {slot}: {os.path.basename(p)} ...', flush=True)
        try:
            r = Rpf(p, keys, tables, aes_key=aes_key)
            r.read_toc()
            if not r.sane():
                raise ValueError('TOC did not decode')
        except Exception as ex:
            print(f'  ! index {slot}: {os.path.basename(p)} unreadable - '
                  f'{type(ex).__name__}: {ex}')
            done.append(p)
            continue
        _index_one(r, oodle, entries, p, 0, 2, os.path.basename(p))
        del r
        done.append(p)
        outstanding = {w for w in wants if w not in entries}
    doc['indexed'] = done
    doc['entries'] = entries
    tmp = cache + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(doc, f)
    os.replace(tmp, cache)
    return entries


def fetch_from_archive(path, wants, keys, tables, aes_key, oodle):
    """{lowercase name: blob} for the wanted leaf names in one archive.

    Only nested .rpf entries and the wanted leaves are ever inflated - the whole point of a
    targeted decode is not paying the extract's cost. Traversal order matches _index_one, so the
    blob returned for a colliding basename is the one the corpus was built from.

    ⛔ A want MAY BE PATH-QUALIFIED ("<in-archive dir>/<name>", e.g. "player_zero_p/
    p_ears_000.ydd"). A bare name is FIRST-WINS by design (the flat corpus contract) — but a
    per-instance decode addressing a specific ped's copy through a bare name silently gets the
    first instance instead, MEASURED 2026-08-08: all 12 ped folders received the first ped's
    pixels, byte-identical, while the run looked perfectly healthy. Qualified wants match the
    leaf's own TOC folder + name, so each instance decodes ITS OWN bytes.
    """
    got = {}
    qualified = any('/' in w for w in wants)

    def walk(r, depth, p):
        folders = _tree_paths(r.entries) if qualified else None
        for i, e in enumerate(r.entries):
            if e['dir']:
                continue
            name = e['name']
            low = name.lower()
            if low.endswith('.rpf'):
                if depth >= 2:
                    continue
                try:
                    blob = r.payload(e, oodle)
                    sub = Rpf(f'{p}/{name}', r.keys, r.tables, data=blob, name=name,
                              aes_key=getattr(r, 'aes_key', None))
                    sub.read_toc()
                    if not sub.sane():
                        continue
                except Exception:
                    continue
                walk(sub, depth + 1, f'{p}/{name}')
                continue
            keys_here = [low]
            if folders is not None and folders[i]:
                keys_here.append(f'{folders[i]}/{name}'.lower())
            for k in keys_here:
                if k in wants and k not in got:
                    try:
                        got[k] = r.payload(e, oodle)
                    except Exception as ex:
                        got[k] = ex
    r0 = Rpf(path, keys, tables, aes_key=aes_key)
    r0.read_toc()
    walk(r0, 0, os.path.basename(path))
    return got


def _link_or_copy(src, dst):
    """Hardlink `src` into `dst` (same volume) or copy. -> 'link' | 'copy' | None."""
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if os.path.exists(dst):
        try:
            os.remove(dst)
        except OSError:
            return None
    try:
        os.link(src, dst)
        return 'link'
    except OSError:
        pass
    try:
        shutil.copy2(src, dst)
        return 'copy'
    except OSError:
        return None


def _sibling_targets(out, resolved, slot, kind, stem, safe, ext, is_winner, pdir=''):
    """Every ADDITIONAL path a decoded pixel must exist at beyond its primary slot file.

    ⭐ An `__embedded` manifest's pixels ALSO land in the bare drawable folder `X/` — the
    drawable's own XML advertises them there (`embedded_texture_sidecars`' dual-write contract).
    The decode lane not doing this is what graded 14 byte-identical pixels MISSING in the
    2026-08-07 sidecar grade: right bytes, wrong folder.

    ⛔ THE `_resolved` TREE IS THE WINNER VIEW. Only the WINNING instance's pixels may be linked
    forward — linking a non-winner instance would replace what RUDE reads with a DIFFERENT
    asset that shares the name (w_lr_40mm: 00_base is 64x32, the patchday8ng winner 256x128).
    """
    outs = []
    emb = stem.lower().endswith(EMBEDDED_INFIX)
    base = stem[:-len(EMBEDDED_INFIX)] if emb else None
    pd = pdir.replace('/', os.sep) if pdir else ''
    if emb:
        outs.append(os.path.join(out, slot, kind, *( [pd] if pd else [] ),
                                 base, safe + ext))
    if is_winner and os.path.isdir(resolved):
        # _resolved keeps its FLAT winner contract (RUDE's shipped pairing) - ped-foldered
        # instances are never winners under the flat model, so pdir never reaches here today
        outs.append(os.path.join(resolved, kind, stem, safe + ext))
        if emb:
            outs.append(os.path.join(resolved, kind, base, safe + ext))
    return outs


def _parse_patterns(raw):
    """Comma-separated fnmatch patterns, or @file with one per line -> lowercase list."""
    if not raw:
        return []
    if raw.startswith('@'):
        with open(raw[1:], encoding='utf-8') as f:
            return [ln.strip().lower() for ln in f
                    if ln.strip() and not ln.lstrip().startswith('#')]
    return [s.strip().lower() for s in raw.split(',') if s.strip()]


def decode_referenced(a, out, resolved, ref_roots):
    """Decode ONLY the texture pixels something references, from a MANIFESTS-ONLY corpus.

    ⛔ WRITES INTO THE WINNING SLOT AND HARDLINKS FORWARD INTO `_resolved`, never into `_resolved`
    alone. `cmd_resolve` rmtree's `_resolved/<kind>/<stem>/` and re-materialises it from the slot,
    so a pixel that exists only in `_resolved` is deleted by the next `resolve` - silently, and
    long after the run that produced it. The slot is where a with-pixels extract would have put it.

    ⛔ NEVER EMITS A PLACEHOLDER PIXEL. Everything it cannot resolve - a manifest whose source
    binary is not in the archives, a texture the decoded dictionary does not contain, an unmapped
    pixel format - is COUNTED by class and left absent. A missing file is a hole every downstream
    check can see; an invented one is a wrong answer with no counter.
    """
    import ytd2xml
    game = getattr(a, 'game', None) or manifest_flag(out, 'gameRoot', None)
    if not game or not os.path.isdir(game):
        print('STOP - no game install. Pass --game "<install>", or run this against a project '
              'whose _FILEBASE.json records a gameRoot that still exists.')
        return 2
    want_png = not getattr(a, 'dds_only', False)
    want_dds = bool(getattr(a, 'dds', False)) or not want_png
    if want_png and not ytd2xml.png_available():
        # PNG is the file ImportYtd actually loads. Producing only .dds here would leave the lane
        # connected on paper and broken in practice - the exact failure the ytd sidecars document.
        print('STOP - texture2ddecoder/Pillow are NOT installed, and ImportYtd loads the .png. '
              '`pip install texture2ddecoder Pillow`, or pass --dds-only for the lossless archive '
              'form on its own.')
        return 2

    scope = None
    raw = getattr(a, 'scope', None)
    if raw:
        if raw.startswith('@'):
            with open(raw[1:], encoding='utf-8') as f:
                scope = [ln.strip().lower() for ln in f if ln.strip()
                         and not ln.lstrip().startswith('#')]
        else:
            scope = [s.strip().lower() for s in raw.split(',') if s.strip()]
    print(f'game      : {game}')
    print(f'scope     : {"whole corpus" if not scope else ", ".join(scope)}')

    wanted, drawables, _kinds, stems = scan_drawable_references(ref_roots, scope)
    print(f'drawables scanned : {drawables:,}   distinct textures referenced: {len(wanted):,}')
    # ⛔ "I found no evidence" must never be promoted to "there is nothing to do" - the same law
    # --prune already follows. A scope typo scans zero drawables and would otherwise exit 0 having
    # decoded nothing, which is indistinguishable from a corpus that is already complete.
    if not drawables:
        print('STOP - the scope matched NO drawable XML. That is a broken question, not an answer '
              'of "nothing is referenced". Check the pattern (fnmatch, e.g. "dt1_13_*").')
        return 2
    if not wanted:
        print('STOP - the scoped drawables name ZERO textures. Refusing to report a no-op as a '
              'complete decode.')
        return 2

    holdings, manifests = scan_txd_manifests(ref_roots, wanted, out)
    held = set()
    for h in holdings.values():
        held.update(n.lower() for n in h['needed'])
    print(f'ytd manifests     : {manifests:,}   dictionaries holding a referenced name: '
          f'{len(holdings):,}')

    refusals = {}
    examples = {}

    def refuse(cls, detail, n=1):
        refusals[cls] = refusals.get(cls, 0) + n
        examples.setdefault(cls, detail)

    orphan = wanted - held
    if orphan:
        refuse('texture_named_but_no_manifest_holds_it', sorted(orphan)[0], len(orphan))

    # ---- name ambiguity, stated rather than hidden -------------------------------------------
    # ⛔ A DRAWABLE NAMES A TEXTURE, NOT A DICTIONARY. Measured on this corpus: 8,791 of 22,405
    # distinct texture names live in more than one dictionary, so a name join answers "every
    # dictionary that COULD satisfy this drawable", not "the one that does" - for `dt1_13_build*`
    # that is 836 dictionaries for 43 textures. This is the same ambiguity RUDE's importer counts
    # as `texturesTieBroken` after scoping the lookup to the archetype's own <textureDictionary>,
    # and neither end can resolve it from a name alone.
    # THE DEFAULT IS THE COMPLETE SET, deliberately: decoding every candidate cannot bind the wrong
    # pixels (RUDE's scoped lookup then picks), while decoding one candidate CAN. `--candidates N`
    # trades that away knowingly, and the count of what it dropped is printed either way.
    holders = {}
    for key, h in holdings.items():
        for n in h['needed']:
            holders.setdefault(n.lower(), []).append(key)
    ambiguous = {n: v for n, v in holders.items() if len(v) > 1}
    worst = max((len(v) for v in holders.values()), default=0)
    print(f'name ambiguity    : {len(ambiguous):,} of {len(holders):,} referenced textures exist '
          f'in more than one dictionary (most-shared name: {worst:,} holders)')

    cand = int(getattr(a, 'candidates', 0) or 0)
    if cand > 0 and ambiguous:
        # Preference is DATA, not enumeration order: a dictionary belonging to one of the scoped
        # drawables (its `__embedded`, its `+hidr`) is the drawable's own and outranks a stranger
        # that merely shares the name; ties then break lexicographically so the choice is
        # reproducible. This is an APPROXIMATION and is reported as one.
        def rank(key):
            stem = key.split('/', 1)[1].lower()
            own = any(stem == s or stem.startswith(s) for s in stems)
            return (0 if own else 1, key)
        keep_pairs = set()
        for n, v in holders.items():
            for key in sorted(v, key=rank)[:cand]:
                keep_pairs.add((key, n))
        dropped_d = dropped_t = 0
        for key in list(holdings):
            need = [x for x in holdings[key]['needed'] if (key, x.lower()) in keep_pairs]
            dropped_t += len(holdings[key]['needed']) - len(need)
            if not need:
                del holdings[key]
                dropped_d += 1
            else:
                holdings[key]['needed'] = need
        print(f'candidate cap     : --candidates {cand} -> dropped {dropped_d:,} dictionaries and '
              f'{dropped_t:,} duplicate texture copies. ! APPROXIMATION: if RUDE binds a copy from '
              f'a dictionary this dropped, it reports missingPixels - re-run without --candidates')

    need_tex = sum(len(h['needed']) for h in holdings.values())
    have_tex = sum(h['total'] for h in holdings.values())
    print(f'to decode         : {need_tex:,} texture copies out of {have_tex:,} those '
          f'{len(holdings):,} dictionaries contain '
          f'({100.0 * need_tex / have_tex if have_tex else 0:.1f}% - the rest is never touched)')

    # ---- what is already on disk, decided by CONTENT ----------------------------------------
    # ⛔ NOT BY LENGTH. Commit af55e9f: `--resume` skipped a target whose SIZE matched, so two
    # content-distinct assets of equal length read as "already present" and the loser was dropped
    # with no counter. The rule is the same one stated there - a run may only skip a file whose
    # bytes it would have written anyway - and here it is enforced with sha256: a ledger row is
    # trusted only when the file on disk still hashes to what we recorded writing, under the same
    # decode contract. Anything else is re-decoded and byte-compared.
    ledger_path = os.path.join(out, '_manifest', DECODE_LEDGER)
    ledger = {}
    try:
        with open(ledger_path) as f:
            got = json.load(f)
        if got.get('contract') == DECODE_CONTRACT:
            ledger = got.get('files') or {}
    except Exception:
        pass

    winners = {}
    try:
        with open(os.path.join(resolved, '_RESOLVED.json')) as f:
            winners = json.load(f).get('winners') or {}
    except Exception:
        pass

    def slot_of(kind, stem):
        return winners.get('%s/%s.ytd.xml' % (kind, stem))

    jobs, present, relinked = {}, 0, 0
    skipped_dicts = 0

    def build_todo(slot, kind, stem, names, is_winner, pdir=''):
        """One implementation of "what does this dictionary still owe" for BOTH planning modes
        (winner-view and per-instance) — two copies would drift on the ledger/sibling rules.
        `pdir` = the per-ped folder (game-mirrored) the manifest lives under, '' for flat."""
        nonlocal present, relinked
        todo = []
        mid = ('%s/' % pdir) if pdir else ''
        for name in names:
            safe = ytd2xml.safe_name(name)
            for ext, want in (('.png', want_png), ('.dds', want_dds)):
                if not want:
                    continue
                rel = '%s/%s/%s%s/%s%s' % (slot.replace(os.sep, '/'), kind, mid, stem,
                                           safe, ext)
                dst = os.path.join(out, rel.replace('/', os.sep))
                row = ledger.get(rel)
                if row and os.path.isfile(dst) and _sha256_file(dst) == row.get('sha256'):
                    present += 1
                    # "Already present" includes every sibling placement. A byte-identical pixel
                    # in the wrong folder graded MISSING on 2026-08-07 — placement is part of
                    # done, not decoration.
                    for sdst in _sibling_targets(out, resolved, slot, kind, stem, safe, ext,
                                                 is_winner, pdir):
                        if not os.path.exists(sdst):
                            if _link_or_copy(dst, sdst):
                                relinked += 1
                    continue
                todo.append((name, safe, ext, rel, dst))
        return todo

    for key in sorted(holdings):
        h = holdings[key]
        kind, stem = h['kind'], h['stem']
        if h.get('dir'):
            # ped-foldered manifests are INSTANCE-layer: the flat winners table cannot address
            # them, so they are planned by the per-instance pass below (--all-instances /
            # scoped), never refused as winner-less here
            continue
        slot = slot_of(kind, stem)
        if slot is None:
            refuse('manifest_has_no_winning_slot', '%s/%s' % (kind, stem))
            continue
        src = manifest_source_name(kind, stem)
        if src is None:
            refuse('manifest_shape_unattributable_to_a_source', '%s/%s.ytd.xml' % (kind, stem))
            continue
        # slot came from the winners table, so this IS the winning instance by construction.
        todo = build_todo(slot, kind, stem, h['needed'], True)
        if not todo:
            skipped_dicts += 1
            continue
        jobs.setdefault((slot, src.lower()), {'slot': slot, 'src': src.lower(), 'kind': kind,
                                              'stem': stem, 'dir': '', 'todo': todo,
                                              'winner': True})

    # ---- per-instance planning: --all-instances (embedded) / --dicts (standalone, in full) --
    # ⛔ THE WINNER PLAN ABOVE IS STRUCTURALLY BLIND to two classes, measured 2026-08-07
    # (tools/sidecar_grade.py): a NON-WINNER slot instance's embedded pixels (its names never
    # enter `wanted`, because references are scanned from _resolved = the winner view), and a
    # dictionary NOTHING references (engine-referenced: waterfog). Both are planned here, each
    # instance decoding from ITS OWN slot's archives. `--textures dds` at extract time would
    # have written exactly this; doing it here is the no-re-extract route (Matt's Fix B ruling).
    inst_mode = bool(getattr(a, 'all_instances', False))
    dict_pats = _parse_patterns(getattr(a, 'dicts', None))
    if inst_mode or dict_pats:
        import fnmatch
        inst_dicts = 0
        for slot_name in precedence_slots(out):
            for kind in TXD_BEARING_DIRS:
                d = os.path.join(out, slot_name, kind)
                if not os.path.isdir(d):
                    continue
                # recursive: the per-ped layout files manifests under <kind>/<ped>/
                for dp, _dirs, fs in os.walk(d):
                    relbase = os.path.relpath(dp, d)
                    pdir = '' if relbase == '.' else relbase.replace(os.sep, '/')
                    for fn in fs:
                        if not fn.lower().endswith('.ytd.xml'):
                            continue
                        stem = fn[:-len('.ytd.xml')]
                        emb = stem.lower().endswith(EMBEDDED_INFIX)
                        base = stem[:-len(EMBEDDED_INFIX)] if emb else stem
                        if emb:
                            if not inst_mode:
                                continue
                            # scope narrows the embedded sweep; an explicitly NAMED --dicts
                            # entry is never scope-filtered (you asked for it by name).
                            if scope and not _scope_match(base, fn, scope):
                                continue
                        elif not (dict_pats and any(fnmatch.fnmatch(stem.lower(), p)
                                                    for p in dict_pats)):
                            continue
                        # ⛔ A `~N` collision stem is refused AT PLANNING, not at the archive
                        # index: the suffix is corpus-side (file_into invented it), so no
                        # archive holds a binary by that name — the job can never produce
                        # output, and 242 such jobs made a COMPLETE corpus trip the zero-work
                        # guard. Counted, never guessed; the ped-folder layout is what makes
                        # those instances addressable (they re-file WITHOUT the suffix).
                        if re.search(r'~\d+$', base):
                            refuse('instance_source_unattributable_collision_suffix',
                                   '%s/%s' % (kind, fn))
                            continue
                        src = manifest_source_name(kind, stem)
                        if src is None:
                            refuse('instance_source_unattributable', '%s/%s' % (kind, fn))
                            continue
                        if pdir:
                            # path-qualify: this instance's OWN entry, not the first same-named
                            # one the walk happens to meet (the defect measured 2026-08-08)
                            src = '%s/%s' % (pdir, src)
                        try:
                            with open(os.path.join(dp, fn), encoding='utf-8',
                                      errors='replace') as fh:
                                names = [n.strip() for n in _XML_NAME_RE.findall(fh.read())]
                        except OSError:
                            refuse('instance_manifest_unreadable', '%s/%s' % (kind, fn))
                            continue
                        if not names:
                            continue
                        is_winner = (not pdir and
                                     winners.get('%s/%s.ytd.xml' % (kind, stem)) == slot_name)
                        todo = build_todo(slot_name, kind, stem, names, is_winner, pdir)
                        if not todo:
                            skipped_dicts += 1
                            continue
                        inst_dicts += 1
                        jobs.setdefault(
                            (slot_name, src.lower(), pdir.lower(), stem.lower()),
                            {'slot': slot_name, 'src': src.lower(), 'kind': kind,
                             'stem': stem, 'dir': pdir, 'todo': todo, 'winner': is_winner})
        print(f'instance planning : {"embedded at every slot instance" if inst_mode else ""}'
              f'{" + " if inst_mode and dict_pats else ""}'
              f'{"--dicts full decode" if dict_pats else ""} -> {inst_dicts:,} additional '
              f'dictionaries to decode')
    limit = int(getattr(a, 'limit', 0) or 0)
    order = sorted(jobs)
    capped = len(order) > limit > 0
    if capped:
        order = order[:limit]
    print(f'dictionaries      : {len(holdings):,} referenced, {skipped_dicts:,} already complete, '
          f'{len(jobs):,} to decode' + (f' (capped to {limit:,} by --limit)' if capped else ''))
    print(f'pixel files       : {present:,} already present (content-verified)'
          + (f', {relinked:,} re-linked into _resolved' if relinked else ''))
    if not order:
        print('\nnothing to decode - every referenced pixel in scope is already present.')
        return _report_decode(0, 0, 0, present, False, refusals, examples)

    # ---- keys, oodle, and the per-slot source index ------------------------------------------
    keys = tables = aes_key = None
    try:
        import keyderive
        raw_k, raw_t = keyderive.acquire(game, getattr(a, 'keys', None), getattr(a, 'magic', None))
        keys, tables = ngcrypto.keys_from_bytes(raw_k), ngcrypto.tables_from_bytes(raw_t)
    except Exception as e:
        print(f'keys      : UNAVAILABLE - {e}')
    try:
        import keyderive
        aes_key = keyderive.acquire_aes(game)
    except Exception:
        aes_key = None
    dll = oodle_dll(game, getattr(a, 'oodle', None))
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

    smap = slot_archives(out, game)
    by_slot = {}
    for k in order:
        by_slot.setdefault(jobs[k]['slot'], []).append(jobs[k])

    decoded = rewritten = unchanged = 0
    linked = copied = 0
    written_bytes = 0
    for slot, items in sorted(by_slot.items()):
        archives = smap.get(slot)
        if not archives:
            refuse('slot_has_no_archive_on_this_install', slot, len(items))
            continue
        # the on-disk source index is keyed by BARE name (first-wins, the flat contract);
        # a qualified instance want resolves its ARCHIVE by tail, then fetch_from_archive
        # matches the qualified path inside it
        wants = {w.rsplit('/', 1)[-1] for w in {it['src'] for it in items}}
        idx = source_index(out, slot, archives, keys, tables, aes_key, oodle, wants)
        per_archive = {}
        for it in items:
            arch = idx.get(it['src']) or idx.get(it['src'].rsplit('/', 1)[-1])
            if arch is None:
                refuse('source_binary_not_found_in_archives', '%s (%s)' % (it['src'], slot))
                continue
            per_archive.setdefault(arch, []).append(it)
        for arch, group in sorted(per_archive.items()):
            print(f'  decode {slot}: {os.path.basename(arch)} '
                  f'-> {len(group):,} dictionar{"y" if len(group) == 1 else "ies"}', flush=True)
            blobs = fetch_from_archive(arch, {it['src'] for it in group},
                                       keys, tables, aes_key, oodle)
            for it in group:
                blob = blobs.get(it['src'])
                if blob is None:
                    refuse('source_entry_vanished_between_index_and_fetch', it['src'])
                    continue
                if isinstance(blob, Exception):
                    refuse('source_entry_would_not_decode', f'{it["src"]}: {blob}')
                    continue
                try:
                    texs = read_source_dictionary(it['kind'], blob)
                except Exception as ex:
                    refuse('dictionary_would_not_read', f'{it["src"]}: '
                                                       f'{type(ex).__name__}: {ex}')
                    continue
                by_name = {t['name'].lower(): t for t in texs}
                for name, safe, ext, rel, dst in it['todo']:
                    t = by_name.get(name.lower())
                    if t is None:
                        # The manifest advertises it and the binary does not hold it. That is a
                        # real gap (an unmapped format refused inside read_textures is the known
                        # cause) and it is counted, never papered over with a blank image.
                        refuse('texture_in_manifest_absent_from_source', f'{it["src"]}:{name}')
                        continue
                    if ext == '.dds':
                        data = t['dds']
                    else:
                        data, why = ytd2xml.decode_png(t)
                        if data is None:
                            refuse('png_decode_refused', f'{it["src"]}:{name}: {why}')
                            continue
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    if os.path.isfile(dst):
                        try:
                            with open(dst, 'rb') as f:
                                old = f.read()
                        except OSError:
                            old = None
                        if old == data:
                            unchanged += 1
                        else:
                            with open(dst, 'wb') as f:
                                f.write(data)
                            rewritten += 1
                            written_bytes += len(data)
                    else:
                        with open(dst, 'wb') as f:
                            f.write(data)
                        decoded += 1
                        written_bytes += len(data)
                    ledger[rel] = {'sha256': _sha256_bytes(data), 'bytes': len(data),
                                   'source': it['src'], 'slot': it['slot']}
                    for sdst in _sibling_targets(out, resolved, it['slot'], it['kind'],
                                                 it['stem'], safe, ext,
                                                 it.get('winner', True), it.get('dir', '')):
                        how = _link_or_copy(dst, sdst)
                        if how == 'link':
                            linked += 1
                        elif how == 'copy':
                            copied += 1
            del blobs

    os.makedirs(os.path.dirname(ledger_path), exist_ok=True)
    tmp = ledger_path + '.tmp'
    with open(tmp, 'w') as f:
        json.dump({'contract': DECODE_CONTRACT, 'files': ledger}, f)
    os.replace(tmp, ledger_path)

    print(f'\ndecoded {decoded:,} new pixel files ({written_bytes / 1e6:.1f} MB), '
          f'{rewritten:,} rewritten, {unchanged:,} byte-identical to what was already there')
    print(f'hardlinked into _resolved: {linked:,}   copied: {copied:,}')
    return _report_decode(decoded, rewritten, unchanged, present, True, refusals, examples)


def _report_decode(decoded, rewritten, unchanged, present, attempted, refusals, examples):
    """Print the refusal table and pick the exit code.

    ⛔ A REFUSAL IS NOT A FAILURE OF THE RUN, but silence about it would be - so they are always
    printed, by class, with an example. The EXIT CODE follows the zero-work law `extract` already
    obeys: a run that was asked to decode and produced not one pixel is a FAILURE, not an empty
    success (that is what a broken join, a wrong install or a bad key set looks like), while a run
    that had nothing left to do is legitimately green.
    """
    # THE_PLAN 5.0: the emitter + texture MODULE counters (ydr2xml.REFUSALS fired inside
    # read_source_dictionary, ytd2xml.TEXTURE_REFUSALS) must print here too - the local
    # registry below only covers this lane's own classes, not the cause classes inside them.
    report_lane_counters({})
    if refusals:
        print(f'\nREFUSED (counted, nothing invented): {sum(refusals.values()):,}')
        for k in sorted(refusals, key=lambda k: -refusals[k]):
            print(f'  {refusals[k]:>8,}  {k}   e.g. {examples.get(k, "")[:90]}')
    else:
        print('\nrefusals: 0')
    if attempted and not (decoded or rewritten or unchanged):
        print('STOP - this run had dictionaries to decode and produced ZERO pixel files. That is a '
              'failure, not an empty success - read the refusal table above.')
        return 1
    if not (decoded or rewritten or unchanged or present):
        print('STOP - the run decoded nothing and found nothing already present.')
        return 1
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


# ------------------------------------------------------------------ view (the whole-game manifest)
VIEW_DEPTH_CAP = 16   # cycle guard only - the game nests archives 2-3 deep in practice


def _tree_paths(entries):
    """In-archive directory path for every entry, from the TOC's OWN tree (root = entry 0).

    RPF7 stores a flat entry list; a directory entry carries (idx, n) = the slice holding its
    children. `extract` never needed paths (it files by basename), but a whole-game register
    does: a file's folder (levels/gta5/..., x64/models/...) is classification evidence the
    basename alone does not carry. Returns None when the structure is not actually a tree
    (an index reachable twice, a slice out of range) - the caller falls back to flat names
    and COUNTS the fallback, never guesses a path.
    """
    n = len(entries)
    if not n or not entries[0].get('dir'):
        return None
    paths = [''] * n
    seen = {0}
    stack = [(0, '')]
    while stack:
        i, base = stack.pop()
        e = entries[i]
        lo, hi = e['idx'], e['idx'] + e['n']
        if lo < 0 or hi > n:
            return None
        for k in range(lo, hi):
            if k in seen:
                return None
            seen.add(k)
            c = entries[k]
            if c['dir']:
                stack.append((k, f'{base}/{c["name"]}' if base else c['name']))
            else:
                paths[k] = base
    return paths


def _view_walk(r, oodle, emit, slot, chain, depth, max_depth, stats):
    """Register every FILE entry, descending into nested .rpf - leaves are NEVER inflated.

    The only payload() calls are on nested archives themselves (their TOC cannot be read
    without their bytes); every leaf is recorded from its 16-byte TOC entry alone. That is
    what makes a whole-game view cost minutes and ~0 disk where extract costs hours and
    ~136 GB. Every failure and every depth-cap skip is counted AND itemized - a register
    that silently misses an archive would poison every phase built on it.
    """
    stats['maxDepthSeen'] = max(stats.get('maxDepthSeen', 0), depth)
    paths = _tree_paths(r.entries)
    if paths is None:
        stats['treeFallback'] = stats.get('treeFallback', 0) + 1
        paths = [''] * len(r.entries)
    for idx, e in enumerate(r.entries):
        if e['dir']:
            continue
        name = e['name']
        dirp = paths[idx]
        low = name.lower()
        if low.endswith('.rpf'):
            if depth >= (max_depth or VIEW_DEPTH_CAP):
                stats['nestedSkippedDepth'] = stats.get('nestedSkippedDepth', 0) + 1
                stats.setdefault('failures', []).append(
                    f'{chain}/{dirp}/{name}: SKIPPED at depth cap {max_depth or VIEW_DEPTH_CAP}')
                continue
            try:
                blob = r.payload(e, oodle)
                sub = Rpf(f'{chain}/{name}', r.keys, r.tables, data=blob, name=name,
                          aes_key=getattr(r, 'aes_key', None))
                sub.read_toc()
                if not sub.sane():
                    raise ValueError('nested TOC did not decode')
            except Exception as ex:
                stats['nestedFailed'] = stats.get('nestedFailed', 0) + 1
                stats.setdefault('failures', []).append(
                    f'{chain}/{dirp}/{name}: {type(ex).__name__}: {ex}')
                continue
            stats['nestedOpened'] = stats.get('nestedOpened', 0) + 1
            # The chain keeps the nested archive's FOLDER inside its parent, not just its name:
            # `x64g.rpf/levels/gta5/generic/cutsprops.rpf`, not `x64g.rpf/cutsprops.rpf`. The
            # containing folder is classification + association evidence (levels vs vehicles vs
            # anim) that the flat leaf archives themselves no longer carry.
            hop = f'{dirp}/{name}' if dirp else name
            _view_walk(sub, oodle, emit, slot, f'{chain}/{hop}', depth + 1, max_depth, stats)
            continue
        ext = low.rsplit('.', 1)[1] if '.' in low else ''
        rec = {'slot': slot, 'archive': chain, 'path': dirp, 'name': name, 'ext': ext,
               'depth': depth, 'resource': e['resource']}
        if e['resource']:
            # FileSize is a u24 and saturates at >=16MB; recovering the real length reads file
            # data, which the view deliberately does not do - record the saturation instead.
            if e['size'] == SIZE_SATURATED:
                rec['disk'], rec['saturated'] = None, True
            else:
                rec['disk'] = e['size']
        else:
            rec['disk'] = e['size'] or e['usize']
            rec['usize'] = e['usize']
        emit(rec)


def cmd_view(a):
    """ONE manifest, period: every file in every archive, registered from TOCs alone."""
    import time
    t0 = time.time()
    title, exe = detect_title(a.game)
    base, upd, dlc = find_sources(a.game)

    keys = tables = aes_key = None
    try:
        import keyderive
        raw_k, raw_t = keyderive.acquire(a.game, a.keys, getattr(a, 'magic', None))
        keys, tables = ngcrypto.keys_from_bytes(raw_k), ngcrypto.tables_from_bytes(raw_t)
    except Exception as e:
        print(f'keys     : UNAVAILABLE - {e}')
        print('keys     : every NG archive TOC would be unreadable - refusing to run a view '
              'that cannot actually see the game')
        return 2
    try:
        import keyderive
        aes_key = keyderive.acquire_aes(a.game)
    except Exception:
        aes_key = None
    print(f'aes key  : ' + ('recovered - AES nested archives will open' if aes_key else
                            'NOT FOUND - AES nested archives will fail, and be counted'))

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

    # Source set = EXACTLY extract's job list, including every dlc*.rpf in a pack (the Cayo
    # lesson: mpheist4 ships dlc.rpf + dlc1.rpf + dlc2.rpf; taking only dlc.rpf silently
    # dropped 7.2 GB). A view whose source set differs from extract's would certify the
    # wrong universe.
    names = [os.path.basename(d) for d in dlc]
    jobs = [(os.path.join(a.game, n), '00_base') for n in base]
    jobs += [(p, '10_update') for p in upd]
    for i, d in enumerate(dlc):
        found = sorted((f for f in os.listdir(d)
                        if f.lower().startswith('dlc') and f.lower().endswith('.rpf')
                        and os.path.isfile(os.path.join(d, f))),
                       key=lambda f: (len(f), f.lower()))
        if not found:
            print(f'  ! {names[i]}: no dlc*.rpf found in {d} - this pack registers NOTHING')
            continue
        for f in found:
            jobs.append((os.path.join(d, f),
                         os.path.join('20_dlc', '%03d_%s' % (i + 1, names[i]))))
    if a.only:
        avail = sorted({os.path.basename(j[0]) for j in jobs})
        jobs = [j for j in jobs if os.path.basename(j[0]).lower() == a.only.lower()]
        if not jobs:
            print(f'STOP --only {a.only!r} matched NO archive. Available ({len(avail)}): '
                  + ', '.join(avail[:24]) + (' …' if len(avail) > 24 else ''))
            return 2

    os.makedirs(a.out, exist_ok=True)
    man_path = os.path.join(a.out, 'VIEW_MANIFEST.jsonl')
    sum_path = os.path.join(a.out, 'VIEW_SUMMARY.json')
    stats, per_ext, per_slot = {}, {}, {}
    total = 0
    arch_failed = []
    with open(man_path, 'w', encoding='utf-8') as mf:
        def emit(rec):
            nonlocal total
            total += 1
            per_ext[rec['ext']] = per_ext.get(rec['ext'], 0) + 1
            per_slot[rec['slot']] = per_slot.get(rec['slot'], 0) + 1
            mf.write(json.dumps(rec) + '\n')

        for path, slot in jobs:
            base_n = os.path.basename(path)
            try:
                r = Rpf(path, keys, tables, aes_key=aes_key)
                r.read_toc()
                if not r.sane():
                    raise ValueError('TOC did not decode (wrong keys?)')
            except Exception as ex:
                arch_failed.append(f'{slot}/{base_n}: {type(ex).__name__}: {ex}')
                print(f'  FAIL {slot}/{base_n}: {ex}')
                continue
            before = total
            _view_walk(r, oodle, emit, slot, base_n, 0, a.max_depth, stats)
            del r
            print(f'  {slot}/{base_n}: {total - before:,} files  (cumulative {total:,})',
                  flush=True)

    failures = stats.get('failures', [])
    summary = {
        'game': a.game, 'title': title, 'exe': exe,
        'created': datetime.now().isoformat(timespec='seconds'),
        # The install fingerprint ties every downstream consumer of this manifest (names
        # derivation in `export`, categorization, specimen picks) to the exact install
        # state it was read from - a stat-level stamp, cheap to re-check, loud when the
        # game updates underneath a stored manifest.
        'installFingerprint': _install_fingerprint(a.game),
        'jobs': len(jobs),
        'archivesRead': len(jobs) - len(arch_failed),
        'archivesFailed': arch_failed,
        'filesTotal': total,
        'perSlot': per_slot,
        'perExt': dict(sorted(per_ext.items(), key=lambda kv: -kv[1])),
        'nestedOpened': stats.get('nestedOpened', 0),
        'nestedFailed': stats.get('nestedFailed', 0),
        'nestedSkippedDepth': stats.get('nestedSkippedDepth', 0),
        'treeFallback': stats.get('treeFallback', 0),
        'maxDepthSeen': stats.get('maxDepthSeen', 0),
        'failures': failures,
        'elapsedSec': round(time.time() - t0, 1),
    }
    with open(sum_path, 'w', encoding='utf-8') as f:
        json.dump(summary, f, indent=1)
    print(f'\nwrote {man_path}\n      {sum_path}')
    print(f'files    : {total:,} across {summary["archivesRead"]} top-level archives '
          f'({summary["nestedOpened"]:,} nested opened, max depth {summary["maxDepthSeen"]}) '
          f'in {summary["elapsedSec"]}s')
    ex_top = ', '.join(f'{k or "(none)"} {v:,}' for k, v in list(summary['perExt'].items())[:12])
    print(f'top exts : {ex_top}')
    bad = len(arch_failed) + summary['nestedFailed'] + summary['nestedSkippedDepth']
    if bad:
        # ⛔ The exit code must carry the verdict: a register with holes exiting 0 is exactly
        # the "ok":true-on-a-failed-batch defect this project has already paid for.
        print(f'!! INCOMPLETE VIEW: {len(arch_failed)} top-level archive(s) failed, '
              f'{summary["nestedFailed"]} nested failed, {summary["nestedSkippedDepth"]} '
              f'skipped at the depth cap - every one itemized in the summary')
        for line in (arch_failed + failures)[:20]:
            print(f'   {line}')
        return 1
    print('OK       : every archive opened, every entry registered - 0 skipped')
    return 0


# ------------------------------------------------------------------ export (targeted lane)
def _view_jobs(game):
    """The view/export source universe - the same archive set the view walks, enumerated
    quietly (incl. every dlc*.rpf in a pack - the Cayo rule)."""
    base, upd, dlc = find_sources(game)
    dnames = [os.path.basename(d) for d in dlc]
    jobs = [(os.path.join(game, n), '00_base') for n in base]
    jobs += [(p, '10_update') for p in upd]
    for i, d in enumerate(dlc):
        found = sorted((f for f in os.listdir(d)
                        if f.lower().startswith('dlc') and f.lower().endswith('.rpf')
                        and os.path.isfile(os.path.join(d, f))),
                       key=lambda f: (len(f), f.lower()))
        for f in found:
            jobs.append((os.path.join(d, f),
                         os.path.join('20_dlc', '%03d_%s' % (i + 1, dnames[i]))))
    return jobs


def _install_fingerprint(game):
    """Stat-level stamp of the install: exe + every source archive's (relpath, size,
    mtime). Milliseconds to compute, no TOC reads - enough to catch a game update or a
    swapped install underneath a stored view manifest. Not a content hash by design:
    the point is a cheap PER-RUN check, and any real drift moves file stats."""
    _title, exe = detect_title(game)
    h = hashlib.sha256()
    paths = ([os.path.join(game, exe)] if exe else []) + sorted(
        j[0] for j in _view_jobs(game))
    for p in paths:
        st = os.stat(p)
        h.update(('%s|%d|%d' % (os.path.relpath(p, game).lower(),
                                st.st_size, st.st_mtime_ns)).encode())
    return {'exe': exe, 'archives': len(paths) - (1 if exe else 0),
            'statHash': h.hexdigest()}


def _names_from_view(view_dir, game):
    """The joaat names table, derived from the view manifest - the ONE registry - and
    freshness-gated against the live install. Refuses loudly rather than resolving
    names against a stale filename universe."""
    import meta2xml
    sum_p = os.path.join(view_dir, 'VIEW_SUMMARY.json')
    man_p = os.path.join(view_dir, 'VIEW_MANIFEST.jsonl')
    for p in (sum_p, man_p):
        if not os.path.isfile(p):
            raise SystemExit(f'STOP: no view manifest at {view_dir} - run `quarry view` first')
    with open(sum_p, encoding='utf-8') as f:
        s = json.load(f)
    stamp = s.get('installFingerprint')
    if not stamp:
        raise SystemExit('STOP: this view manifest predates the install fingerprint - '
                         're-run `quarry view` to refresh it')
    if os.path.normcase(os.path.abspath(s.get('game', ''))) != \
            os.path.normcase(os.path.abspath(game)):
        raise SystemExit(f'STOP: view manifest was built from a DIFFERENT install '
                         f'({s.get("game")}) - re-run `quarry view` against this one')
    now = _install_fingerprint(game)
    if now['statHash'] != stamp['statHash']:
        raise SystemExit('STOP: the game install changed since the view manifest was '
                         'built (fingerprint mismatch) - re-run `quarry view`')

    def stems():
        seen_arch = set()
        with open(man_p, encoding='utf-8') as fh:
            for line in fh:
                r = json.loads(line)
                yield r['name']
                # nested archive BASENAMES are legitimate name material too - a ytyp's
                # physicsDictionary can name the .rpf its bounds live in
                # (heist_ornate_bank), and those names exist only in the archive
                # chains, never as leaf-file records
                arch = r['archive']
                if arch not in seen_arch:
                    seen_arch.add(arch)
                    for comp in arch.split('/'):
                        if comp.lower().endswith('.rpf'):
                            yield comp
    names = meta2xml.load_names_from_stems(stems())
    # OVERLAY: ped-audio component names (CPedVariationInfo pedXml_audioID/audioId) are
    # NOT asset filenames, so the manifest-derived table cannot reverse them - the reference exporter resolves
    # them from its bundled string index. oracle_ped_audio_names.json is every such string
    # the ymt oracle set itself spells; each is reference-witnessed, so joaat-matching it is
    # byte-exact (same rule as the shader-name overlays). Additive: setdefault never
    # displaces a real filename hash.
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     'oracle_ped_audio_names.json')
    if os.path.isfile(p):
        import meta2xml as _m
        for n in json.load(open(p, encoding='utf-8')).get('names', []):
            names.setdefault(_m.joaat(n), n)
    # OVERLAY 2 (2026-08-08, maintainer call after Matt declined the ruling - function over
    # spelling purity): general oracle-witnessed CONTENT names - strings the oracle set itself
    # spells where the game stores only the hash and no in-scope file carries the text
    # (entitySet names, cutscene object names; both live in scripts or the reference
    # exporter's own index). Same self-verifying rule as above: joaat(name) must equal the
    # stored hash or the entry is dead weight that can never fire. REVERSIBLE: delete
    # oracle_witnessed_names.json and the corpus reverts to hash_%08X spellings on next regen.
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     'oracle_witnessed_names.json')
    if os.path.isfile(p):
        import meta2xml as _m
        for n in json.load(open(p, encoding='utf-8')).get('names', []):
            names.setdefault(_m.joaat(n), n)
    # ⛔ NO GLOBAL GAME-TEXTURE-NAME OVERLAY (tried and REVERTED 2026-08-08, same session).
    # A 122k-name harvest from the corpus ytd manifests DID resolve carcols' plate01-class
    # references - and immediately produced the INVERSE parity break: OUR output spelled
    # `vehiclelight_car_standardmodern` where the reference exporter prints hash_BCA6181A.
    # The boundary is the reference exporter's OWN string index, and the only sound proxy for
    # it is what the oracles themselves spell: a string witnessed spelled in ANY oracle is
    # spelled globally by the reference tool (its index is global), so importing it can never
    # make us print a name where the reference prints hash_ - while importing names from
    # ANY OTHER source (even clean game data) provably can, and would silently perturb every
    # graded lane at its next regeneration. Oracle-witnessed names live in
    # oracle_witnessed_names.json (loaded above); the harvest file game_texture_names.json
    # stays on disk as a tool artifact but is deliberately NOT loaded.
    return names


def _resolve_entry(game, entry, keys, tables, aes_key, oodle, cache=None):
    """One named source file, straight from the archives: entry is the reference exporter-style path
    relative to the install (fs dirs, top .rpf, nested .rpf chain, in-archive folders,
    leaf name). Opens ONLY the archives on that chain. -> (leaf_name, blob).

    cache: an optional single-slot dict {'path':, 'rpf':} - a batch whose entries are
    sorted by top archive then reads each multi-GB top exactly once."""
    parts = [p for p in entry.replace('/', '\\').split('\\') if p]
    i = next((k for k, p in enumerate(parts) if p.lower().endswith('.rpf')), None)
    if i is None:
        raise ValueError(f'entry has no .rpf component: {entry}')
    top = os.path.join(game, *parts[:i + 1])
    if cache is not None and cache.get('path') == top.lower():
        r = cache['rpf']
    else:
        if not os.path.isfile(top):
            raise FileNotFoundError(f'top archive not on disk: {top}')
        r = Rpf(top, keys, tables, aes_key=aes_key)
        r.read_toc()
        if not r.sane():
            raise ValueError(f'TOC did not decode: {top}')
        if cache is not None:
            cache['path'], cache['rpf'] = top.lower(), r
    rest = parts[i + 1:]
    while True:
        if not rest:
            raise FileNotFoundError(f'entry names an archive, not a file: {entry}')
        paths = _tree_paths(r.entries)
        if paths is None:
            raise ValueError(f'malformed TOC tree in {r.name}')
        j = next((k for k, p in enumerate(rest) if p.lower().endswith('.rpf')), None)
        dirp = '/'.join(rest[:j] if j is not None else rest[:-1]).lower()
        want = (rest[j] if j is not None else rest[-1]).lower()
        hit = None
        for idx, e in enumerate(r.entries):
            if not e['dir'] and e['name'].lower() == want and paths[idx].lower() == dirp:
                hit = e
                break
        if hit is None:
            raise FileNotFoundError(f'not found in {r.name}: '
                                    f'{"/".join(rest[:(j + 1) if j is not None else len(rest)])}')
        blob = r.payload(hit, oodle)
        if j is None:
            return hit['name'], blob
        sub = Rpf(f'{r.name}/{hit["name"]}', r.keys, r.tables, data=blob,
                  name=hit['name'], aes_key=aes_key)
        sub.read_toc()
        if not sub.sane():
            raise ValueError(f'nested TOC did not decode: {hit["name"]}')
        r = sub
        rest = rest[j + 1:]


def cmd_export(a):
    """TARGETED lane: convert exact named source files with the SAME conversion code the
    full pipeline runs (to_interchange_xml / meta2xml.convert_bytes) - a scoped
    invocation, not a fork. Meta lanes get their names from the view manifest,
    freshness-gated; no pre-built corpus is read, ever."""
    META_KINDS = ('ytyp', 'ymap', 'ymt')
    entries = list(a.entry or [])
    if a.list:
        with open(a.list, encoding='utf-8') as f:
            entries += [ln.strip() for ln in f
                        if ln.strip() and not ln.strip().startswith('#')]
    if not entries:
        print('STOP: nothing to export - pass --entry (repeatable) and/or --list')
        return 2

    keys = tables = aes_key = None
    try:
        import keyderive
        raw_k, raw_t = keyderive.acquire(a.game, a.keys, getattr(a, 'magic', None))
        keys, tables = ngcrypto.keys_from_bytes(raw_k), ngcrypto.tables_from_bytes(raw_t)
    except Exception as e:
        print(f'keys     : UNAVAILABLE - {e} - NG archive TOCs would be unreadable')
        return 2
    try:
        import keyderive
        aes_key = keyderive.acquire_aes(a.game)
    except Exception:
        aes_key = None

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

    names = None
    NAMES_KINDS = META_KINDS + ('ydd',)   # ydd entry names resolve from the same table
    if any(type_of(os.path.basename(e)) in NAMES_KINDS for e in entries):
        if not a.view:
            print('STOP: ytyp/ymap/ymt/ydd entries need --view <folder holding '
                  'VIEW_MANIFEST.jsonl> - the names source')
            return 2
        print('names    : deriving the joaat table from the view manifest '
              '(freshness-gated) ...')
        names = _names_from_view(a.view, a.game)
        print(f'names    : {len(names):,} distinct asset names')

    os.makedirs(a.out, exist_ok=True)
    import meta2xml
    ok = kept_binary = failed = 0
    stats = {}
    arch_cache = {}
    for eidx, entry in enumerate(entries, 1):
        # --split: each entry lands in its own numbered subfolder, so a batch that
        # includes several VERSIONS of the same filename (base + update + dlc patches)
        # cannot silently overwrite itself in a flat --out.
        out_dir = a.out
        if getattr(a, 'split', False):
            out_dir = os.path.join(a.out, '%04d' % eidx)
            os.makedirs(out_dir, exist_ok=True)
        try:
            name, blob = _resolve_entry(a.game, entry, keys, tables, aes_key, oodle,
                                        cache=arch_cache)
            kind = type_of(name)
            if kind in META_KINDS:
                # ⛔⛔ THE CONTAINER DECIDES, NOT THE EXTENSION (fixed 2026-08-07, Phase 5
                # Stage A). This used to test `kind == 'ymt'` before rerouting PSIN/RBF0, so a
                # PSIN .ymap or .ytyp fell through to the META reader and died with "not an RSC7
                # container" - while `extract` converted the same files perfectly, because it
                # calls to_interchange_xml, whose check is container-first. That is a
                # TARGETED-vs-AT-SCALE DIVERGENCE in the one guarantee THE_PLAN 2.5.3/5.5 exists
                # to prove, and no oracle could catch it: the 315-position sweep contains no PSIN
                # ymap/ytyp. Found only because the AES-binary fix made those files readable and
                # a targeted re-export of them failed. meta2xml's own docstring already states
                # the rule this now follows: "Kind comes from the ROOT STRUCT, not the file
                # extension, so a mislabelled file cannot be emitted as the wrong schema."
                # the reference exporter names them <stem>.<ext>.pso.xml / <stem>.<ext>.rbf.xml.
                if blob[:4] in (b'PSIN', b'RBF0'):
                    conv = to_interchange_xml(name, blob,
                                              getattr(a, 'textures', 'both'),
                                              stats, names=names)
                    if conv is not None:
                        xml_name, xml_bytes, _extras = conv
                        with open(os.path.join(out_dir, xml_name), 'wb') as fh:
                            fh.write(xml_bytes)
                        ok += 1
                        print(f'  {entry} -> {xml_name}')
                        continue
                    with open(os.path.join(out_dir, name), 'wb') as fh:
                        fh.write(blob)
                    kept_binary += 1
                    continue
                stem = name[:-(len(kind) + 1)]
                xml, got_kind, w = meta2xml.convert_bytes(blob, stem, names)
                out_p = os.path.join(out_dir, f'{stem}.{got_kind}.xml')
                with open(out_p, 'w', encoding='utf-8') as fh:
                    fh.write(xml)
                for _k, _n in w.warn.items():
                    stats[_k] = stats.get(_k, 0) + _n
                ok += 1
                print(f'  {entry} -> {os.path.basename(out_p)}')
            else:
                conv = to_interchange_xml(name, blob, getattr(a, 'textures', 'both'),
                                          stats, names=names)
                if conv is None:
                    with open(os.path.join(out_dir, name), 'wb') as fh:
                        fh.write(blob)
                    kept_binary += 1
                    print(f'  {name}: no converter for .{kind} yet - kept binary, '
                          'never dropped')
                    continue
                xml_name, xml_bytes, extras = conv
                with open(os.path.join(out_dir, xml_name), 'wb') as fh:
                    fh.write(xml_bytes)
                for rel, payload in (extras or []):
                    dst = os.path.join(out_dir, rel.replace('/', os.sep))
                    d = os.path.dirname(dst)
                    if d:
                        os.makedirs(d, exist_ok=True)
                    with open(dst, 'wb') as fh:
                        fh.write(payload)
                ok += 1
                print(f'  {entry} -> {xml_name}'
                      + (f' (+{len(extras)} sidecar file(s))' if extras else ''))
        except SystemExit:
            raise
        except Exception as ex:
            failed += 1
            print(f'  FAIL {entry}: {type(ex).__name__}: {ex}')

    print(f'\nexport: {ok} converted, {kept_binary} kept binary (counted), '
          f'{failed} failed, of {len(entries)} requested')
    # ⛔ THE_PLAN 5.0 (2026-08-06): the old block here sorted raw stats - TypeError the moment a
    # list-valued key appeared (verified) - and truncated to the top 10 with no overflow marker,
    # so refusal classes could silently vanish. And export NEVER called report_refusals, so all
    # ~40 emitter refusal classes were unprinted in this path. One reporter now, every path.
    report_lane_counters(stats)
    return 0 if failed == 0 else 1


# Keys the extract summary already prints by name - the generic reporter skips them.
NAMED_SUMMARY_KEYS = frozenset((
    'resumed', 'xml_unwound', 'nested_opened', 'nested_failed', 'nested_aes_skipped',
    'nested_skipped', 'xml_ok', 'xml_failed', 'xml_sidecars', 'collisions', 'failed',
    'yft_extras_refused',
))


def report_lane_counters(stats):
    """⛔ THE_PLAN 5.0 DISCLOSURE LAW (2026-08-06): every counter ANY converter accumulates must
    reach the PRINTED run summary of EVERY converting path - export, extract, textures. Before
    this reporter: export never called ydr2xml.report_refusals (~40 emitter classes unprinted),
    extract never printed the generic lane counters (rel/ypt/pso/ybd), ytd2xml's
    TEXTURE_REFUSALS + SIZE_RULE_UNWITNESSED were read by NOTHING, and export's stats print
    crashed on a list value. A downgrade that never reaches a human is a silent one no matter
    how carefully it was counted."""
    stats = stats if stats is not None else {}
    try:
        import ydr2xml
        ydr2xml.report_refusals(stats)   # emitter table (ydr+ydd+yft) -> stats[emitter_*] + print
    except Exception as ex:
        print(f'  (emitter refusal report unavailable: {type(ex).__name__}: {ex})')
    try:
        import ytd2xml
        if ytd2xml.TEXTURE_REFUSALS:
            print('texture decode refused (counted, run totals):')
            for k in sorted(ytd2xml.TEXTURE_REFUSALS):
                print('    %-46s %7d   e.g. %s'
                      % (k, ytd2xml.TEXTURE_REFUSALS[k],
                         ytd2xml.TEXTURE_REFUSAL_EXAMPLE.get(k, '')))
        if ytd2xml.SIZE_RULE_UNWITNESSED:
            print('textures emitted under an ORACLE-UNWITNESSED size rule - go get an oracle:')
            for k in sorted(ytd2xml.SIZE_RULE_UNWITNESSED):
                print('    %-46s %7d' % (k, ytd2xml.SIZE_RULE_UNWITNESSED[k]))
    except Exception as ex:
        print(f'  (texture refusal report unavailable: {type(ex).__name__}: {ex})')
    rest = {k: v for k, v in stats.items()
            if isinstance(v, int) and v > 0
            and k not in NAMED_SUMMARY_KEYS and not k.startswith('emitter_')}
    if rest:
        print(f'lane counters ({len(rest)} class(es), untruncated):')
        for k, n in sorted(rest.items(), key=lambda kv: (-kv[1], kv[0])):
            print(f'  {n:7,}x  {k}')


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
    if getattr(a, 'only_path', None):
        want_p = os.path.normcase(os.path.abspath(a.only_path))
        jobs = [j for j in jobs if os.path.normcase(os.path.abspath(j[0])) == want_p]
        if not jobs:
            print(f'STOP --only-path {a.only_path!r} matched NO archive in the job list.')
            return 2

    want = None
    if getattr(a, 'types', None):
        want = {t.strip().lstrip('.').lower() for t in a.types.split(',') if t.strip()}
        print(f'type filter : {sorted(want)}')
    max_depth = getattr(a, 'max_depth', 2)
    print(f'max depth   : {max_depth}   (nested .rpf are descended into)')

    # ⭐ --view (2026-08-08, the extract/export split fix): the whole-game names registry lets
    # ytyp/ymap/ymt convert INLINE (to_interchange_xml META branch). Loaded ONCE up front -
    # the freshness gate inside _names_from_view refuses a stale manifest loudly rather than
    # resolving names against yesterday's filename universe. Without --view, those types keep
    # their binary for the later `meta` pass, exactly as before.
    view_names = None
    if getattr(a, 'view', None) and getattr(a, 'xml', False):
        print('names    : deriving the joaat table from the view manifest (freshness-gated) ...')
        view_names = _names_from_view(a.view, a.game)
        print(f'names    : {len(view_names):,} distinct asset names')

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
        for name, blob, chain, pedsub in walk_archive(r, oodle, 0, max_depth, stats,
                                                      os.path.basename(path),
                                                      getattr(a, 'nested_only', None)):
            if want is not None and type_of(name) not in want:
                continue
            if pedsub and stats is not None:
                stats['filed under game folder (per-ped layout)'] = \
                    stats.get('filed under game folder (per-ped layout)', 0) + 1
            try:
                # ⭐ --xml: convert to the RAGE interchange XML that RUDE's importer already reads,
                # so the pipeline is connected without any UE-side work. Binary is kept when a
                # converter for that type does not exist yet.
                if getattr(a, 'xml', False):
                    written_path = None
                    try:
                        conv = to_interchange_xml(name, blob,
                                                 getattr(a, 'textures', 'both'), stats,
                                                 names=view_names)
                        if conv is not None:
                            xml_name, xml_bytes, extras = conv
                            written = file_into(a.out, slot, xml_name, xml_bytes, stats,
                                                getattr(a, 'resume', False), chain=chain,
                                                refresh=getattr(a, 'refresh', False),
                                                subdir=pedsub or None,
                                                overwrite=getattr(a, 'overwrite', False))
                            if written is None:
                                # ⛔⛔ A RESUMED XML MUST NOT SKIP ITS SIDECARS (2026-08-04).
                                # This `continue` jumped past the ENTIRE sidecar loop, so a second
                                # pass adding PIXELS to a manifests-only corpus wrote NOTHING and
                                # printed "nothing new to do - every target was already present".
                                # PROVEN by running it on x64s.rpf: pass 1 `--textures none` -> 435
                                # XML / 0 PNG; pass 2 `--textures png --resume` -> 0 PNG, reported
                                # as success; a fresh no-resume control -> 6,493 PNG. The XML was
                                # present so the file "existed", while the pixels it names never
                                # did - the manifest advertised files that were not there.
                                # ⇒ resume skips the XML WRITE, not the asset's other artifacts.
                                # Sidecars are re-derived and written below; `file_into` skips any
                                # that are genuinely already present, so this stays idempotent.
                                if not extras:
                                    continue
                                written = xml_name
                                stats['resumed_sidecars'] = stats.get('resumed_sidecars', 0) + 1
                            written_path = os.path.join(
                                a.out, slot, type_of(name),
                                *( [pedsub.replace('/', os.sep)] if pedsub else [] ), written)
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
                                # sidecars live BESIDE their XML — under the same ped folder
                                sidecar_into(a.out, slot, type_of(name),
                                             (pedsub + '/' + rel) if pedsub else rel, payload)
                                stats['xml_sidecars'] = stats.get('xml_sidecars', 0) + 1
                            stats['xml_ok'] = stats.get('xml_ok', 0) + 1
                            n += 1
                            continue
                        else:
                            # THE_PLAN 5.0: kept-binary had NO per-class counter in extract, so
                            # a converter lane silently unregistering (the ybn wiring lesson,
                            # see the ybn branch comment) would leave no printed trace. Counted
                            # per extension; prints via report_lane_counters.
                            # ⚠ CAUSE-NEUTRAL by design (2026-08-08): to_interchange_xml counts
                            # WHY it declined (no converter / names-gated META / rel refusal) -
                            # this caller only knows THAT the binary was kept, and its old
                            # "(no converter)" label became a false statement the day META
                            # types gained a names-gated branch.
                            k = 'kept binary: .' + (type_of(name) or '?')
                            stats[k] = stats.get(k, 0) + 1
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
                file_into(a.out, slot, name, blob, stats, getattr(a, 'resume', False),
                          chain=chain, refresh=getattr(a, 'refresh', False),
                          subdir=pedsub or None,
                          overwrite=getattr(a, 'overwrite', False))
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
        # THE_PLAN 5.0: one reporter for every path - emitter table + ytd module counters +
        # every remaining int-valued stats class, untruncated (extract previously printed the
        # emitter table only; rel/ypt/pso/ybd/kept-binary counters were counted, never shown).
        report_lane_counters(stats)
        # ⚠ DEAD MECHANISM below (AST-verified 2026-08-06): FragmentError is unreachable from
        # yft2xml.convert(), so this counter can never fire. Kept per Preserve-Don't-Delete.
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
    # THE_PLAN 5.0: the FULL failure/error lists must survive the process - stdout truncates at
    # 15 and an at-scale triage needs every line WITH its reason (10 missing lane files cost a
    # re-probe because the "+32 more" died with the run). Overwritten per run, kept out of git.
    # PROVENANCE LEDGER: answers "which archive/DLC is this instance from" for every emitted
    # file. APPENDED, never rewritten, so a lane-scoped extract adds to the project's record
    # instead of erasing the lanes extracted before it (the same clobber trap the failure file
    # hit). One JSON object per line.
    prov = stats.get('provenance') or []
    if prov:
        pfile = os.path.join(a.out, '_PROVENANCE.jsonl')
        with open(pfile, 'a', encoding='utf-8') as fh:
            for rec in prov:
                fh.write(json.dumps(rec, separators=(',', ':')) + '\n')
        print(f'provenance: +{len(prov):,} records -> {pfile}')
    if stats.get('failures') or stats.get('xml_errors'):
        # ⚠ Name it per TYPE FILTER, not one fixed file: two extracts into the same project
        # (e.g. --types ymap,ytyp then --types ybn,ydd) would otherwise have the second run
        # CLOBBER the first run's failure list - losing disclosure is the one thing this file
        # exists to prevent.
        tag = (getattr(a, 'types', None) or 'all').replace(',', '-').replace(os.sep, '-')[:40]
        rep = os.path.join(a.out, f'_EXTRACT_FAILURES_{tag}.txt')
        with open(rep, 'w', encoding='utf-8') as fh:
            for section, key in (('failed to extract', 'failures'),
                                 ('xml conversion failed (kept binary)', 'xml_errors')):
                for line in stats.get(key, []):
                    fh.write(f'{section}\t{line}\n')
        print(f'full failure list -> {rep}')
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
# Pinned-witness directory, relative to the project root. See _regress_pinned_fixtures.
REGRESS_PINNED = '_pinned'


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


def _regress_signature(path, tags=None):
    """(xml sha256, [(sidecar name, sha256)]) for one binary, through the REAL pipeline entry
    point - so the gate measures what extract would actually write, not a private code path.

    `tags` (optional set) collects the WITNESS TOPICS this fixture's output actually carries -
    see witness.py. It is filled from the very bytes that get hashed, so a topic reported as
    witnessed is witnessed by the artifact under gate, not by a re-run of the converter."""
    import hashlib
    blob = open(path, 'rb').read()
    conv = to_interchange_xml(os.path.basename(path), blob, 'none', None)
    if conv is None:
        return {'converted': False}
    _n, xml_bytes, sidecars = conv
    if tags is not None:
        import witness
        tags |= witness.witnessed_tags(xml_bytes.decode('utf-8', 'replace'))
        for rel, data in (sidecars or ()):
            if rel.lower().endswith('.xml'):
                tags |= witness.witnessed_tags(data.decode('utf-8', 'replace'))
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


def _regress_pinned_fixtures(root):
    """⛔⛔ FIXTURES THE SAMPLER CANNOT REACH, BECAUSE A SAMPLE CANNOT GUARANTEE COVERAGE.

    THE DEFECT (#32d, 2026-08-05): the whole `occludeModels` emitter shipped under a green
    "OK - no churn" the gate was structurally incapable of producing. Of the 67 ymap in
    the binary fixture set exactly 2 carry an occluder, and the seeded 25-file sample drew NEITHER, so
    the baseline could not move and nothing was blessed. The change had to be proven by hand
    instead, by swapping the emitter out at runtime.

    ⛔ RAISING --per-type IS NOT THE FIX. Past the population size the sample re-rolls, and a
    previously-blessed fixture that falls out becomes a "no longer in the sample" NOTE that does
    not fail the run - i.e. turning the dial up silently removes coverage.

    THE FIX: a directory of hand-chosen carriers that is UNIONED with the sample and never
    sampled from. `<project>/_pinned/<type>/*.<type>`.

    ⭐ WHY `_pinned` SITS OUTSIDE THE SLOTS, which is the part that makes this safe: every other
    reader here walks precedence_slots() - `_regress_fixtures`, `_regress_meta_fixtures` and
    `load_names` all do - and NONE of them looks at a directory that is not 00_base / 10_update /
    20_dlc/<manifest pack>. So adding a pinned witness cannot change which files the random
    sample draws (random.sample re-rolls when its population changes) and cannot change the size
    of the joaat names table (which is itself an input to every meta signature). Pinning is
    therefore additive by construction: it can only ever ADD coverage, never disturb what is
    already blessed. Dropping these files into 00_base instead would have re-rolled the sample
    and demoted blessed fixtures - the exact trap above, self-inflicted.
    """
    out = []
    base = os.path.join(root, REGRESS_PINNED)
    if not os.path.isdir(base):
        return out
    for t in REGRESS_TYPES + REGRESS_META_TYPES:
        d = os.path.join(base, t)
        if not os.path.isdir(d):
            continue
        out += [os.path.join(d, f) for f in sorted(os.listdir(d))
                if f.lower().endswith('.' + t)]
    return out


def _regress_witness_report(pinned):
    """(covered, missing, unreadable) for the ymap container topics, off the PINNED binaries only.

    Deliberately not computed over the sampled fixtures: a topic that happens to be represented
    by this seed's draw is not coverage, it is luck, and luck is what #32d was. The topic list
    comes from meta2xml so a new renderer extends this report automatically.

    A pin that will not decode is returned SEPARATELY rather than folded into `covered` under some
    made-up key. A witness that cannot testify is not a witness, and the first draft of this
    function hid exactly that case in the covered dict where nothing would ever print it - the
    silent-drop shape, committed inside the fix for a silent drop.
    """
    import meta2xml
    covered, unreadable = {}, {}
    for p in pinned:
        if not p.lower().endswith('.ymap'):
            continue
        try:
            topics = meta2xml.ymap_witness_of(p)
        except Exception as ex:
            unreadable[os.path.basename(p)] = f'{type(ex).__name__}: {ex}'
            continue
        for t in topics:
            covered.setdefault(t, []).append(os.path.basename(p))
    missing = [t for t in meta2xml.YMAP_WITNESS_TOPICS if t not in covered]
    return covered, missing, unreadable


def _regress_meta_signature(path, names, tags=None):
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
    if tags is not None:
        import witness
        tags |= witness.witnessed_tags(xml)
    return {'converted': True, 'kind': kind,
            'xml': hashlib.sha256(xml.encode('utf-8')).hexdigest(), 'bytes': len(xml)}


def _regress_topic_report(root, live_tags, pin_tags, types):
    """⛔⛔ WHAT THE GATE CANNOT SEE, FOR EVERY TYPE - printed on every run.

    #32d closed this for ymap containers and left the residual in writing: "the witness set
    covers ymap containers only - ytyp/ymt/ydr/ybn/ydd/yft features are still guarded by a
    random sample alone". This is that residual. A topic here is any tag an emitter can write
    with CONTENT; it is covered only when a PINNED fixture's own output carries it.

    Returns [] when everything is witnessed or receipted, else the reasons --strict must stop on.
    """
    import witness
    census = witness.load_census(root)
    stop = []
    if census is None:
        print(f'  ! NO TOPIC CENSUS at {witness.census_path(root)} - the gate can only speak '
              f'for the ymap containers above. Build it:\n'
              f'      quarry.py witness --out "{root}" --emitted <resolved corpus>')
        stop.append('no topic census')
        return stop
    print(f'topics    : census {census.get("built", "?")[:10]} from '
          f'{census.get("emittedCorpus") or "(binaries only)"}')
    known_all = set()
    for t in types:
        need, exempt = witness.topics_for(census, t)
        rec = (census.get('types') or {}).get(t) or {}
        known_all |= need | exempt
        live = live_tags.get(t, set())
        pin = pin_tags.get(t, set())
        # A tag a FIXTURE emitted is a topic whether or not the census knew about it: the census
        # is a snapshot of an older emitter, the fixture is this build.
        new_to_census = sorted(live - need - exempt)
        need |= set(new_to_census)
        missing = sorted(need - pin)
        line = (f'  {t:<5} {len(need):>3} topic(s), {len(need & pin):>3} witnessed by pins, '
                f'{len(missing):>3} NOT')
        if exempt:
            line += f', {len(exempt)} exempt'
        print(line)
        if exempt:
            # THE RECEIPT, EVERY RUN. `containerLods` is the precedent: a topic with no possible
            # witness is never silenced, it is printed with the measurement that says why.
            det = ' '.join('%s(%s)' % (tag, f'{(rec.get("emptyOnly") or {}).get(tag, 0):,}')
                           for tag in sorted(exempt))
            print(f'        EXEMPT - 0 content-bearing carriers in {rec.get("emittedFiles", 0):,} '
                  f'emitted {t}; the count is how many carry the EMPTY form: {det}')
        if new_to_census:
            print(f'        ! {len(new_to_census)} topic(s) a fixture emits that the census has '
                  f'never seen ({", ".join(new_to_census[:6])}) - the census predates this '
                  f'emitter; re-run `quarry.py witness`')
        if missing:
            for tag in missing[:8]:
                e = (rec.get('content') or {}).get(tag) or {}
                pn = (rec.get('pinnable') or {}).get(tag) or {}
                where = ''
                if e.get('smallest'):
                    where = ' (smallest emitted carrier %s, %s B)' % (
                        e['smallest'][0][1], f'{e["smallest"][0][0]:,}')
                if pn.get('smallest'):
                    where += ' (pin %s)' % os.path.basename(pn['smallest'])
                print(f'        ! NO PINNED WITNESS for {t} topic {tag}{where}')
            if len(missing) > 8:
                print(f'        ! ... and {len(missing) - 8} more')
            stop.append(f'{t}: {len(missing)} unwitnessed topic(s)')
    # The SOURCE half, re-derived live from the emitters' own AST every run - this is what makes
    # the list unable to fall behind the code. A tag the emitters can spell that the census has
    # never seen ANY carrier for is either a receipted zero-carrier topic or a sign the census is
    # stale; the two are told apart by whether the census recorded it as leftover.
    left = witness.source_leftover(census)
    nleft = sum(len(v) for v in left.values())
    if nleft:
        print(f'        EXEMPT - {nleft} source-only tag(s) with 0 carriers in any emitted file: '
              + ', '.join(sorted(t for v in left.values() for t in v))[:400])
    known_all |= {t for v in left.values() for t in v}
    unknown = {}
    for m in sorted({m for ms in witness.type_emitters().values() for m in ms}):
        for tag in sorted(set(witness.source_topics(m)) - known_all):
            unknown.setdefault(m, []).append(tag)
    if unknown:
        n = sum(len(v) for v in unknown.values())
        print(f'  ! {n} tag(s) the EMITTERS can write are unknown to this census '
              + '; '.join(f'{m}: {", ".join(v[:6])}' for m, v in unknown.items())[:300]
              + f'\n    the census is behind the code - re-run `quarry.py witness --out "{root}"`')
        stop.append(f'{n} emitter tag(s) not in the census')
    return stop


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

    ⭐ PLUS A THIRD, UNSAMPLED SET: PINNED WITNESSES (`<project>/_pinned/<type>/`, keyed
    `pinned:<type>/<file>`). A random sample proves nothing about a FEATURE that only ~2% of
    files carry - see _regress_pinned_fixtures for the occludeModels case (#32d) where the gate
    returned "No churn" over a change rewriting 227 files. Pinned fixtures are unioned with the
    sample, can never be dropped from it, and the run PRINTS which ymap container topics have a
    witness and which have none. Under --strict an unwitnessed topic (with no measured exemption
    in meta2xml.YMAP_TOPICS_WITHOUT_CARRIER) and a vanished pin are both failures, because
    silence about a container is the defect, not the report.

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
    pinned = _regress_pinned_fixtures(root)
    if not fixtures and not meta_fixtures and not pinned:
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
    for p in meta_fixtures + pinned:
        t = os.path.splitext(p)[1].lstrip('.').lower()
        by_type[t] = by_type.get(t, 0) + 1
    covered = ', '.join(f'{t}={by_type[t]}' for t in sorted(by_type))
    blind = [t for t in REGRESS_TYPES + REGRESS_META_TYPES if t not in by_type]
    print(f'fixtures  : {len(fixtures) + len(meta_fixtures) + len(pinned)} binaries (seed '
          f'{a.seed}, {a.per_type}/type + {len(pinned)} pinned)  [{covered}]')
    # ⛔⛔ THE COVERAGE LINE IS THE WHOLE POINT OF #32d - SILENCE ABOUT A CONTAINER IS THE DEFECT.
    # Printing "which topics have a witness" turns "the gate said green" into a claim a reader can
    # check, and printing "which have NONE" is what the previous gate could not do at all.
    wit_covered, wit_missing, wit_unreadable = _regress_witness_report(pinned)
    if pinned:
        import meta2xml as _m2
        shown = ', '.join('%s(%d)' % (t, len(wit_covered[t]))
                          for t in _m2.YMAP_WITNESS_TOPICS if t in wit_covered)
        print(f'pinned    : {len(pinned)} always-included fixture(s); ymap topics covered: '
              f'{shown or "NONE"}')
    for fn, why in sorted(wit_unreadable.items()):
        print(f'  ! pinned witness {fn} did NOT decode ({why}) - it testifies to nothing.')
    unexplained = []
    if wit_missing:
        import meta2xml as _m2
        for t in wit_missing:
            why = _m2.YMAP_TOPICS_WITHOUT_CARRIER.get(t)
            if why:
                print(f'  no witness for {t} - EXEMPT: {why}')
            else:
                print(f'  ! NO WITNESS for ymap topic {t} - nothing under gate carries it, so a '
                      f'change to its emitter would pass unseen (this is defect #32d).')
                unexplained.append(t)
    if unexplained and a.strict:
        print(f'STOP - --strict was requested and {len(unexplained)} ymap topic(s) have no '
              f'pinned witness: {", ".join(unexplained)}. Pin a carrier under '
              f'{os.path.join(root, REGRESS_PINNED, "ymap")} (or record a measured exemption in '
              f'meta2xml.YMAP_TOPICS_WITHOUT_CARRIER).')
        return 2
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

    # ⭐ TOPIC WITNESSES, ALL EIGHT TYPES (#32d part 2, 2026-08-05). `live` is what the whole
    # fixture set emits, `pin` is what the PINNED set emits. Only `pin` counts as coverage - a
    # topic the seeded sample happens to draw is luck, and luck is the defect - but `live` is
    # what catches a topic the census has never heard of, i.e. an emitter that grew since the
    # census was built.
    live_tags, pin_tags = {}, {}

    def _tagset(store, path):
        return store.setdefault(os.path.splitext(path)[1].lstrip('.').lower(), set())

    sigs, errors = {}, {}
    for p in fixtures:
        key = os.path.relpath(p, root).replace(os.sep, '/')
        seen = set()
        try:
            sigs[key] = _regress_signature(p, seen)
        except Exception as ex:
            errors[key] = f'{type(ex).__name__}: {ex}'
        _tagset(live_tags, p).update(seen)

    if meta_fixtures or pinned:
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
            seen = set()
            try:
                sigs[key] = _regress_meta_signature(p, names, seen)
            except Exception as ex:
                errors[key] = f'{type(ex).__name__}: {ex}'
            _tagset(live_tags, p).update(seen)
        # PINNED fixtures get their own key namespace ('pinned:<type>/<file>') so they can never
        # be confused with a sampled entry, and so a reader of the baseline can see at a glance
        # which entries are guaranteed present. They run through the SAME signature functions -
        # a pin that took a private code path would guard a code path nobody ships.
        pin_base = os.path.join(root, REGRESS_PINNED)
        for p in pinned:
            key = 'pinned:' + os.path.relpath(p, pin_base).replace(os.sep, '/')
            t = os.path.splitext(p)[1].lstrip('.').lower()
            seen = set()
            try:
                sigs[key] = (_regress_meta_signature(p, names, seen)
                             if t in REGRESS_META_TYPES else _regress_signature(p, seen))
            except Exception as ex:
                errors[key] = f'{type(ex).__name__}: {ex}'
            _tagset(live_tags, p).update(seen)
            _tagset(pin_tags, p).update(seen)

    witness_stop = _regress_topic_report(root, live_tags, pin_tags,
                                         REGRESS_TYPES + REGRESS_META_TYPES)

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
    # ⛔ A PIN THAT VANISHES IS NOT A NOTE. A sampled fixture can legitimately fall out of the
    # draw, which is why `missing` above is only a warning - but a PINNED fixture is in the
    # baseline precisely because something needs a permanent witness, so its disappearance is the
    # silent-demotion trap #32d is about, one directory over. It fails.
    lost_pins = sorted(k for k in missing if k.startswith('pinned:'))
    if lost_pins:
        print(f'\nSTOP - {len(lost_pins)} PINNED witness fixture(s) in the baseline are gone from '
              f'{os.path.join(root, REGRESS_PINNED)}: ' + ', '.join(lost_pins[:6])
              + (' ...' if len(lost_pins) > 6 else '')
              + '\n  A pin is a permanent witness; losing one silently removes the coverage it '
                'was added for. Restore the file, or drop its baseline entry on purpose.')
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
    # ⛔ AN UNWITNESSED TOPIC IN *ANY* TYPE FAILS, not just ymap (#32d part 2). Reported last so
    # a real output change is still the headline, but it is a refusal, not a note: a topic with
    # a carrier and no pin is a structure the gate is blind to, which is the whole defect.
    if witness_stop and a.strict:
        print(f'\nSTOP - --strict was requested and the topic gate is not satisfied: '
              + '; '.join(witness_stop)
              + f'\n  Pin the smallest carrier under {os.path.join(root, REGRESS_PINNED)}/<type>/ '
                f'and re-bless, or re-run `quarry.py witness` if the census is stale.')
        return 2
    if changed or errors or lost_pins:
        return 1
    print('\nOK - every fixture produced byte-identical output. No churn.')
    return 0


def cmd_witness(a):
    """Rebuild `<project>/_pinned/_TOPICS.json` - the topic census `regress` reads.

    ⛔ IT IS A DERIVED ARTIFACT AND IS NEVER COMMITTED, the same rule as the baseline: it is
    measured from the operator's own extraction of their own copy of the game.

    Re-run it whenever an EMITTER CHANGES. The gate does not need it to notice that the emitters
    grew - it re-derives the source half live on every run and fails on a tag it has never seen -
    but only this pass can say how many real files carry a new structure, and that count is what
    turns "unwitnessed" into either a pin or a receipted exemption.
    """
    import witness
    root = a.out
    if not os.path.isdir(root):
        print(f'no project folder at {root}')
        return 2
    types = a.types.split(',') if a.types else None
    print(f'building topic census from {root}'
          + (f' + emitted corpus {a.emitted}' if a.emitted else '')
          + (f' + binaries {a.binaries}' if a.binaries else ''))
    c = witness.build_census(root, a.emitted, tuple(a.binaries), types, a.workers,
                             prior=witness.load_census(root))
    p = witness.census_path(root)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, 'w') as fh:
        json.dump(c, fh, indent=1, sort_keys=True)
    ntop = sum(len(v['content']) + len(v['emptyOnly']) for v in c['types'].values())
    nleft = sum(len(v) for v in c['sourceLeftover'].values())
    print(f'wrote {p}\n  {ntop} topics across {len(c["types"])} types; '
          f'{nleft} source-only tag(s) with no carrier in any emitted file')
    if a.plan:
        for t in sorted(c['types']):
            pins, nocarrier = witness.plan_pins(c, t)
            tot = sum(os.path.getsize(x) for x in pins)
            print(f'-- {t}: {len(pins)} pin(s), {tot:,} B, '
                  f'{len(nocarrier)} topic(s) with no pinnable binary')
            for x in sorted(pins, key=lambda k: os.path.getsize(k)):
                print(f'     {os.path.getsize(x):>9,} B  {os.path.basename(x):<44} '
                      f'{len(pins[x])} topic(s)')
            if nocarrier:
                print('     NO PINNABLE CARRIER: ' + ' '.join(nocarrier))
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
        p.add_argument('--only-path', dest='only_path',
                       help='limit to ONE archive by its full path (basename matching is '
                            'ambiguous for DLC: every pack ships a dlc.rpf). The parallel '
                            'driver\'s per-worker scope.')
        p.add_argument('--nested-only', dest='nested_only',
                       help='limit to NESTED archives matching this fnmatch pattern (e.g. '
                            '"streamedpedprops*.rpf") - the staged-migration scalpel: '
                            'regenerate one container class without walking its 2 GB parent. '
                            'Leaves outside a matching container are skipped entirely.')
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
        p.add_argument('--refresh', action='store_true',
                       help='bring an EXISTING corpus up to the current converter: when a '
                            'file already present would now be written differently FROM THE '
                            'SAME source, overwrite it instead of filing the new output as a '
                            '~N collision and leaving consumers on the stale copy. Two '
                            'genuinely different assets sharing a basename still collide.')
        p.add_argument('--view', help='folder holding VIEW_MANIFEST.jsonl + VIEW_SUMMARY.json. '
                                      'With --xml, ytyp/ymap/ymt convert INLINE using this '
                                      'whole-game names registry (the same one `export` and '
                                      '`meta --view` use, freshness-gated). Without it those '
                                      'types are kept binary for the later `meta` pass - '
                                      'their names table needs the whole filename universe')
        p.add_argument('--overwrite', action='store_true',
                       help='REGENERATE the corpus in place (Matt 2026-08-09): the first '
                            'write of each path this run overwrites the superseded copy; '
                            'same-path collisions within the run claim ~N ranks, likewise '
                            'overwriting the old generation rank-for-rank (the walk is '
                            'deterministic). Byte-identical rewrites are skipped and '
                            'counted; provenance is appended for every file touched')
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

    pv = sub.add_parser('view', help='THE MANIFEST: register every file in every archive by '
                                     'reading TOCs only - nothing extracted, ~0 disk. Writes '
                                     'VIEW_MANIFEST.jsonl + VIEW_SUMMARY.json into --out')
    pv.add_argument('--game', required=True)
    pv.add_argument('--out', required=True, help='directory for the manifest files')
    pv.add_argument('--keys')
    pv.add_argument('--magic', help='override the bundled game-gated key blob')
    pv.add_argument('--oodle', help='path to your own oo2core_*_win64.dll (nested-archive '
                                    'payloads only; leaves are never inflated)')
    pv.add_argument('--only', help='limit to one archive basename, e.g. x64a.rpf (debug)')
    pv.add_argument('--max-depth', type=int, default=0, dest='max_depth',
                    help='nested-archive descent limit; default 0 = unlimited (hard cycle guard '
                         'at 16). extract stops at 2 - the view must see everything, so it '
                         'does not')
    pv.set_defaults(fn=cmd_view)

    pe = sub.add_parser('export', help='TARGETED export: convert exact named source '
                                       'file(s) straight from the archives with the same '
                                       'conversion code the full pipeline runs. Meta '
                                       'lanes derive names from the view manifest, '
                                       'freshness-gated')
    pe.add_argument('--game', required=True)
    pe.add_argument('--out', required=True, help='flat output folder')
    pe.add_argument('--entry', action='append',
                    help='path relative to the install, e.g. '
                         'x64c.rpf\\levels\\gta5\\_prologue\\plg_01.rpf\\plg_01.ymap '
                         '(repeatable)')
    pe.add_argument('--list', help='file with one entry path per line (# comments ok)')
    pe.add_argument('--view', help='folder holding VIEW_MANIFEST.jsonl + '
                                   'VIEW_SUMMARY.json - the names source, required for '
                                   'ytyp/ymap/ymt entries')
    pe.add_argument('--textures', choices=('both', 'png', 'dds', 'none'), default='both')
    pe.add_argument('--split', action='store_true',
                    help='write each entry into its own numbered subfolder of --out - '
                         'required when a batch carries several versions of the same '
                         'filename, which would otherwise overwrite each other')
    pe.add_argument('--keys')
    pe.add_argument('--magic', help='override the bundled game-gated key blob')
    pe.add_argument('--oodle')
    pe.set_defaults(fn=cmd_export)

    # `resolve` reads only the project folder, so it needs no --game and no keys
    pr = sub.add_parser('resolve', help='flatten the precedence tree into _resolved/ - the FLAT '
                                        'corpus layout RUDE actually reads')
    pr.add_argument('--out', required=True, help='the project folder built by init/extract')
    pr.add_argument('--types', help='comma-separated type folders to resolve, e.g. ydr,ytd,ytyp,ymap')
    pr.add_argument('--copy', action='store_true',
                    help='copy instead of hardlinking (use when the destination is another volume)')
    pr.set_defaults(fn=cmd_resolve)

    pt = sub.add_parser('textures', help='the referenced-pixel lane: report what is referenced, '
                                         '--decode-referenced to DECODE only that from the '
                                         'archives, --prune to delete what is not '
                                         '(run AFTER meta/resolve)')
    pt.add_argument('--out', required=True, help='the project folder built by init/extract')
    pt.add_argument('--prune', action='store_true',
                    help='actually delete the unreferenced png/dds sidecars. Safe: the source is '
                         'your own game install, so anything pruned is re-extractable')
    pt.add_argument('--decode-referenced', action='store_true', dest='decode_referenced',
                    help='decode ONLY the pixels the drawables reference, straight from your '
                         'archives, into the sidecar layout ImportYtd already reads. Works from a '
                         '`--textures none` (manifests-only) corpus with NO re-extract - that is '
                         'the point. Idempotent: a re-run skips what is already there by CONTENT.')
    pt.add_argument('--scope', help='limit to the drawables you are actually authoring: '
                                    'comma-separated fnmatch patterns against the asset stem '
                                    '(e.g. "dt1_13_*,prop_bench_*"), or @file with one per line. '
                                    'This is what makes the decode cheap forever - you pay for an '
                                    'area, not for the game. Omit = the whole corpus.')
    pt.add_argument('--candidates', type=int, default=0,
                    help='a drawable names a TEXTURE, not a dictionary, and most texture names '
                         'exist in several. Default 0 = decode EVERY dictionary that holds a '
                         'referenced name (complete: RUDE\'s scoped lookup then picks, and no '
                         'bind can be wrong). N>0 keeps only N candidates per texture - much '
                         'cheaper, but a bind RUDE resolves elsewhere becomes missingPixels')
    pt.add_argument('--limit', type=int, default=0,
                    help='decode at most N dictionaries this run (0 = no cap). Safe to use: the '
                         'run is resumable, so a capped run is a partial, not a wrong, corpus')
    pt.add_argument('--all-instances', action='store_true', dest='all_instances',
                    help='ALSO decode every EMBEDDED dictionary at every slot instance (not just '
                         'the _resolved winner), each from its own slot\'s archives - what a '
                         '--textures dds extract would have written. The default winner-only plan '
                         'cannot see a non-winner instance\'s pixels at all (the 2026-08-07 '
                         'sidecar-grade instance-axis class). Non-winner pixels are NEVER linked '
                         'into _resolved.')
    pt.add_argument('--dicts',
                    help='force-decode these STANDALONE dictionaries IN FULL (every texture, not '
                         'just referenced ones): comma-separated fnmatch patterns against the '
                         'dictionary stem, or @file with one per line. For engine-referenced '
                         'dictionaries no drawable names (waterfog) and oracle-graded positions. '
                         'With --all-instances, applies at every slot instance.')
    pt.add_argument('--dds', action='store_true',
                    help='also write the lossless .dds beside the .png (doubles the disk)')
    pt.add_argument('--dds-only', action='store_true', dest='dds_only',
                    help='write ONLY the .dds. ! ImportYtd loads the .png, so this produces an '
                         'archive, not an importable folder')
    pt.add_argument('--game', help='your game install (default: the gameRoot recorded in this '
                                   "project's _FILEBASE.json)")
    pt.add_argument('--keys')
    pt.add_argument('--magic')
    pt.add_argument('--oodle')
    pt.set_defaults(fn=cmd_textures)

    pm = sub.add_parser('meta', help='convert binary ytyp/ymap/ymt to interchange XML and resolve '
                                     'ydd entry names (run AFTER extract, so the joaat name table '
                                     'is complete)')
    pm.add_argument('--out', required=True, help='the project folder built by init/extract')
    pm.add_argument('--view', help='folder holding VIEW_MANIFEST.jsonl + VIEW_SUMMARY.json - '
                    'resolve names from the WHOLE-GAME registry (the same one `export` uses) '
                    'instead of a walk of this project. REQUIRED for lane-scoped projects, or '
                    'names resolve against a smaller universe than the oracles were graded under')
    pm.add_argument('--game', help='game install - required with --view (freshness gate)')
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

    pw = sub.add_parser('witness', help='rebuild the TOPIC CENSUS the churn gate reads: what '
                                        'every emitter can write, how many real files carry it, '
                                        'and which binary is the smallest carrier')
    pw.add_argument('--out', required=True, help='the fixture project (writes _pinned/_TOPICS.json)')
    pw.add_argument('--emitted', help='a corpus of ALREADY-EMITTED <type>/*.<type>.xml (e.g. a '
                                      'resolved filebase). This is the whole-game evidence base '
                                      'every exemption receipt quotes; without it the census can '
                                      'only speak for the binaries in --out')
    pw.add_argument('--binaries', action='append', default=[],
                    help='extra root holding <type>/ binaries to consider as pin candidates '
                         '(repeatable)')
    pw.add_argument('--types', help='comma-separated types (default: all eight)')
    pw.add_argument('--workers', type=int, default=6)
    pw.add_argument('--plan', action='store_true',
                    help='also print the pin set this census implies, smallest carrier per topic')
    pw.set_defaults(fn=cmd_witness)

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
