"""keyderive - obtain the NG key material on THIS machine, with no the reference exporter dependency.

WHAT THIS IS
QUARRY consumes a local `resources/magic.dat` when present (maintainer decision 2026-07-27,
option A). The blob is GAME-GATED: it is inert without a 32-byte AES key that
only exists inside a genuine installed copy of the game. This module finds that key in the user's own
executable and uses it to open the blob.

PROVENANCE / ATTRIBUTION (read before touching this file)
  * ALGORITHM: derived from `Neodymium146/gta-toolkit` — `GTA5Encryption.cs`, `GTA5Constants.cs`,
    `HashSearch.cs`, **MIT License, Copyright (c) 2015/2017 Neodymium**. That per-file MIT header IS
    the grant (the repo has no root LICENSE), and it must be reproduced verbatim in NOTICE.
    ⛔ We cite THAT lineage, never the reference exporter — gta-toolkit predates the reference exporter and the reference exporter is
    downstream of it.
  * `magic.dat`: **Rockstar-derived key material. We do not license it and do not claim to.**
    ⛔ Do NOT repeat the widespread community claim that this blob is "MIT licensed" — the reference exporter has
    no licence at all, and no third party's MIT can license Rockstar's material. The honest basis is:
    it is game-gated, and this is the long-standing norm in this space.
  * The SHA-1 constants below are one-way digests, not keys. gta-toolkit's own comment:
    "This file contains only SHA1 hashes of all interesting values. There is NO key."

⭐ BUILT FOR THE CONTINGENCY: the blob is a RUNTIME INPUT, never compiled in. Deleting
`resources/magic.dat` switches this module to "supply your own" mode with no code change — that is
the pre-planned pivot to option B if a takedown ever lands.
"""
import hashlib
import os
import struct
import zlib

# --- the one-way anchors (see attribution above; digests, not keys) -----------------------------
PC_AES_KEY_HASH = bytes.fromhex("A0796128A775720AC204D9819F68C172E3952C6D")

NG_KEY_LEN, NG_KEY_COUNT = 272, 101          # 0x110 = 17 rounds x 4 words of expanded round keys
NG_TABLE_LEN, NG_TABLE_COUNT = 1024, 272     # 256 u32 entries per table
LUT_LEN, AWC_LEN = 256, 16
MAGIC_PAYLOAD = NG_KEY_LEN * NG_KEY_COUNT + NG_TABLE_LEN * NG_TABLE_COUNT + LUT_LEN + AWC_LEN


# --- .NET Framework System.Random, reimplemented -----------------------------------------------
# The blob is obfuscated with four byte streams drawn from a .NET `Random` seeded by the AES key's
# Jenkins hash. Our own log previously asserted this "cannot be safely reimplemented" (which is why
# an earlier script was written in PowerShell to borrow the real .NET one) — that was WRONG, and
# `EverythingSuckz/kosatka` (MIT) demonstrates it in TypeScript. Reimplementing it removes the last
# platform dependency and unblocks a future C port.
# Knuth subtractive generator, matching .NET Framework exactly.
def _i32(v: int) -> int:
    """Wrap to signed 32-bit. ⚠ LOAD-BEARING: .NET does this arithmetic in int32 and OVERFLOWS;
    Python ints are unbounded and would not. Without this the generator agrees with .NET for small
    seeds (42, 12345, -7 all matched byte-for-byte) and silently DIVERGES for large-magnitude ones -
    which is exactly the case here, since the real seed is joaat(AES key) cast to int32
    (-1,785,108,663). Verified against real System.Random on both small and large seeds."""
    return ((v + 0x80000000) & 0xFFFFFFFF) - 0x80000000


class DotNetRandom:
    MBIG = 0x7FFFFFFF
    MSEED = 161803398

    def __init__(self, seed: int):
        # seed arrives as an UNCHECKED int32 cast of a uint32 hash - sign matters
        seed = struct.unpack("<i", struct.pack("<I", seed & 0xFFFFFFFF))[0]
        sub = self.MBIG if seed == -2147483648 else abs(seed)
        mj = _i32(self.MSEED - sub)
        self.s = [0] * 56
        self.s[55] = mj
        mk = 1
        for i in range(1, 55):
            ii = (21 * i) % 55
            self.s[ii] = mk
            mk = _i32(mj - mk)
            if mk < 0:
                mk = _i32(mk + self.MBIG)
            mj = self.s[ii]
        for _ in range(1, 5):
            for i in range(1, 56):
                self.s[i] = _i32(self.s[i] - self.s[1 + (i + 30) % 55])
                if self.s[i] < 0:
                    self.s[i] = _i32(self.s[i] + self.MBIG)
        self.inext, self.inextp = 0, 21

    def _sample(self) -> int:
        a, b = self.inext, self.inextp
        a = 1 if a + 1 >= 56 else a + 1
        b = 1 if b + 1 >= 56 else b + 1
        v = _i32(self.s[a] - self.s[b])
        if v == self.MBIG:
            v -= 1
        if v < 0:
            v = _i32(v + self.MBIG)
        self.s[a] = v
        self.inext, self.inextp = a, b
        return v

    def next_bytes(self, n: int) -> bytearray:
        return bytearray(self._sample() % 256 for _ in range(n))


def joaat(data: bytes) -> int:
    """Jenkins one-at-a-time over RAW BYTES (the AES key), not a lowercased string."""
    h = 0
    for b in data:
        h = (h + b) & 0xFFFFFFFF
        h = (h + (h << 10)) & 0xFFFFFFFF
        h ^= h >> 6
    h = (h + (h << 3)) & 0xFFFFFFFF
    h ^= h >> 11
    return (h + (h << 15)) & 0xFFFFFFFF


# --- minimal AES-256 decryption (ECB, no padding) ----------------------------------------------
# Self-contained so QUARRY needs no crypto dependency.
_SBOX = bytes.fromhex(
    "637c777bf26b6fc53001672bfed7ab76ca82c97dfa5947f0add4a2af9ca472c0"
    "b7fd9326363ff7cc34a5e5f171d8311504c723c31896059a071280e2eb27b275"
    "09832c1a1b6e5aa0523bd6b329e32f8453d100ed20fcb15b6acbbe394a4c58cf"
    "d0efaafb434d338545f9027f503c9fa851a3408f929d38f5bcb6da2110fff3d2"
    "cd0c13ec5f974417c4a77e3d645d197360814fdc222a908846eeb814de5e0bdb"
    "e0323a0a4906245cc2d3ac629195e479e7c8376d8dd54ea96c56f4ea657aae08"
    "ba78252e1ca6b4c6e8dd741f4bbd8b8a703eb5664803f60e613557b986c11d9e"
    "e1f8981169d98e949b1e87e9ce5528df8ca1890dbfe6426841992d0fb054bb16")
_INV = [0] * 256
for _i, _v in enumerate(_SBOX):
    _INV[_v] = _i
_INV = bytes(_INV)
_RCON = [0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x1B, 0x36, 0x6C, 0xD8, 0xAB, 0x4D]


def _xt(a, b):                                     # GF(2^8) multiply
    p = 0
    for _ in range(8):
        if b & 1:
            p ^= a
        hi = a & 0x80
        a = (a << 1) & 0xFF
        if hi:
            a ^= 0x1B
        b >>= 1
    return p


def _expand(key: bytes):
    nk, nr = 8, 14
    w = [list(key[4 * i:4 * i + 4]) for i in range(nk)]
    for i in range(nk, 4 * (nr + 1)):
        t = list(w[i - 1])
        if i % nk == 0:
            t = t[1:] + t[:1]
            t = [_SBOX[x] for x in t]
            t[0] ^= _RCON[i // nk - 1]
        elif i % nk == 4:
            t = [_SBOX[x] for x in t]
        w.append([w[i - nk][j] ^ t[j] for j in range(4)])
    return [sum(w[4 * r:4 * r + 4], []) for r in range(nr + 1)]


def aes256_ecb_decrypt_block(block: bytes, rk) -> bytes:
    s = [block[i] ^ rk[14][i] for i in range(16)]
    for rnd in range(13, -1, -1):
        # InvShiftRows
        t = list(s)
        for r in range(1, 4):
            for c in range(4):
                t[r + 4 * ((c + r) % 4)] = s[r + 4 * c]
        s = [_INV[x] for x in t]                                  # InvSubBytes
        s = [s[i] ^ rk[rnd][i] for i in range(16)]                # AddRoundKey
        if rnd:                                                   # InvMixColumns
            o = list(s)
            for c in range(4):
                col = s[4 * c:4 * c + 4]
                o[4 * c + 0] = _xt(col[0], 14) ^ _xt(col[1], 11) ^ _xt(col[2], 13) ^ _xt(col[3], 9)
                o[4 * c + 1] = _xt(col[0], 9) ^ _xt(col[1], 14) ^ _xt(col[2], 11) ^ _xt(col[3], 13)
                o[4 * c + 2] = _xt(col[0], 13) ^ _xt(col[1], 9) ^ _xt(col[2], 14) ^ _xt(col[3], 11)
                o[4 * c + 3] = _xt(col[0], 11) ^ _xt(col[1], 13) ^ _xt(col[2], 9) ^ _xt(col[3], 14)
            s = o
    return bytes(s)


def aes256_ecb_decrypt(data: bytes, key: bytes) -> bytes:
    """Decrypt WHOLE 16-byte blocks only; any trailing remainder passes through VERBATIM.

    ⚠ LOAD-BEARING: the blob is 154,069 bytes = 9,629 blocks + a 5-byte tail. Dropping that tail
    yields a deflate stream that starts decoding and then dies with "incomplete or truncated stream"
    - i.e. it looks like a cipher/keying bug when it is actually a length bug. The tail is part of
    the compressed payload and is not encrypted.
    """
    rk = _expand(key)
    whole = len(data) - (len(data) % 16)
    out = b"".join(aes256_ecb_decrypt_block(data[i:i + 16], rk) for i in range(0, whole, 16))
    return out + data[whole:]


# --- AES key discovery in the user's OWN executable ---------------------------------------------
def find_aes_key(exe_path: str, chunk: int = 1 << 22):
    """Locate the 32-byte AES key by SHA-1 anchor. Verified working on current Legacy AND Enhanced
    builds. Returns (key_bytes, offset) or (None, -1)."""
    size = os.path.getsize(exe_path)
    with open(exe_path, "rb") as f:
        base, prev = 0, b""
        while True:
            buf = prev + f.read(chunk)
            if len(buf) <= 32:
                break
            for i in range(len(buf) - 32 + 1):
                if hashlib.sha1(buf[i:i + 32]).digest() == PC_AES_KEY_HASH:
                    return bytes(buf[i:i + 32]), base + i
            keep = 31
            base += len(buf) - keep
            prev = buf[-keep:]
            if base + keep >= size:
                break
    return None, -1


_AES_CACHE = {}


def find_aes_key_cached(exe_path: str):
    """find_aes_key scans the whole executable (~43 s). Cache it: extract calls it once for the
    magic blob and now once per AES archive, and the answer cannot change mid-run."""
    if exe_path not in _AES_CACHE:
        _AES_CACHE[exe_path] = find_aes_key(exe_path)
    return _AES_CACHE[exe_path]


def acquire_aes(game_root: str):
    """The 32-byte RAGE PC AES key from the user's OWN executable -> bytes, or None.

    ⭐ THIS IS THE SAME KEY QUARRY ALREADY RECOVERS ON EVERY RUN to open the magic blob. It is
    ALSO the archive key: ONE AES-256-ECB pass over an AES-flagged rpf's TOC + name table opens
    it. The code said 'no AES key available … a separate recovery step' - a claim of ABSENCE that
    the code itself disproved, and it cost the corpus 2,075 files (34 archives, 1,886 ydr + 84 yft
    + 18 ytyp + 5 ymap) that no completeness number ever counted.
    Verified 2026-08-03 on a live Legacy install: 34/34 archives decrypt to a sane TOC with real
    filenames, and 2,028 of 2,051 resource bodies pass the page-plan gate exactly.
    ⛔ Nothing about the tool's posture changes: no key is shipped, nothing is dumped from a
    running process, and the source is the operator's own install - identical to the NG path.
    """
    for exe in game_executables(game_root):
        key, _off = find_aes_key_cached(exe)
        if key is not None:
            return key
    return None


def game_executables(game_root: str):
    """Both titles share ONE NG key set; gen9 only changes which exe holds the AES key."""
    out = []
    for name in ("GTA5.exe", "GTA5_Enhanced.exe", "GTA5_Enhanced_BE.exe"):
        p = os.path.join(game_root, name)
        if os.path.isfile(p):
            out.append(p)
    return out


# --- the derive chain ---------------------------------------------------------------------------
def deobfuscate(blob: bytes, aes_key: bytes) -> bytes:
    """Subtract four .NET-Random byte streams (mod 256), seeded by joaat(AES key)."""
    rng = DotNetRandom(joaat(aes_key))
    acc = bytearray(blob)
    for _ in range(4):
        stream = rng.next_bytes(len(blob))
        for i in range(len(blob)):
            acc[i] = (acc[i] - stream[i]) & 0xFF
    return bytes(acc)


def split_payload(payload: bytes):
    if len(payload) < MAGIC_PAYLOAD:
        raise ValueError(f"payload {len(payload)} B is shorter than the expected {MAGIC_PAYLOAD} B")
    o = 0
    keys = payload[o:o + NG_KEY_LEN * NG_KEY_COUNT]; o += len(keys)
    tables = payload[o:o + NG_TABLE_LEN * NG_TABLE_COUNT]; o += len(tables)
    lut = payload[o:o + LUT_LEN]; o += LUT_LEN
    awc = payload[o:o + AWC_LEN]
    return keys, tables, lut, awc


def derive(magic_blob: bytes, aes_key: bytes):
    """magic + AES key -> (ng_keys, ng_tables, lut, awc). Raises on any step failing."""
    de = deobfuscate(magic_blob, aes_key)
    dec = aes256_ecb_decrypt(de, aes_key)
    try:
        payload = zlib.decompress(dec, -15)
    except zlib.error as e:
        raise ValueError(f"inflate failed after AES ({e}) - wrong AES key or a corrupt blob") from e
    return split_payload(payload)


def bundled_magic_path():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "resources", "magic.dat")


def acquire(game_root: str, keys_dir: str = None, magic_path: str = None, verbose=True):
    """Full acquisition, in priority order. Returns (ng_keys, ng_tables) or raises.

    1. already-materialised key files in keys_dir (fastest, and the option-B path)
    2. a magic blob (bundled by default; overridable) + the AES key from the user's own exe
    """
    def say(m):
        if verbose:
            print(m)

    if keys_dir:
        kp = os.path.join(keys_dir, "ng_keys.bin")
        tp = os.path.join(keys_dir, "ng_tables.bin")
        if os.path.isfile(kp) and os.path.isfile(tp):
            say(f"keys      : using existing files in {keys_dir}")
            return open(kp, "rb").read(), open(tp, "rb").read()

    blob_path = magic_path or bundled_magic_path()
    if not os.path.isfile(blob_path):
        raise FileNotFoundError(
            "no key material available.\n"
            f"  Looked for ng_keys.bin/ng_tables.bin in: {keys_dir or '(not given)'}\n"
            f"  Looked for a magic blob at: {blob_path}\n"
            "  QUARRY needs either (a) ng_keys.bin (27,472 B) + ng_tables.bin (278,528 B), or\n"
            "  (b) a magic blob, PLUS an installed copy of the game to open it.\n"
            "  Supply one with --keys <dir> or --magic <file>.")

    exes = game_executables(game_root)
    if not exes:
        raise FileNotFoundError(f"no game executable found under {game_root} - the blob cannot be "
                                "opened without one (it is inert on its own)")
    for exe in exes:
        say(f"aes key   : searching {os.path.basename(exe)} ...")
        key, off = find_aes_key(exe)
        if key is None:
            continue
        say(f"aes key   : found at 0x{off:08x} in {os.path.basename(exe)}")
        ng_keys, ng_tables, _lut, _awc = derive(open(blob_path, "rb").read(), key)
        say(f"derived   : {len(ng_keys):,} B keys + {len(ng_tables):,} B tables")
        return ng_keys, ng_tables
    raise ValueError("could not locate the AES key in any game executable - is this a genuine, "
                     "unmodified install?")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(prog="keyderive",
                                 description="Obtain NG key material from your own game install.")
    ap.add_argument("--game", required=True)
    ap.add_argument("--keys")
    ap.add_argument("--magic")
    ap.add_argument("--out", help="write ng_keys.bin + ng_tables.bin here")
    a = ap.parse_args()
    k, t = acquire(a.game, a.keys, a.magic)
    if a.out:
        os.makedirs(a.out, exist_ok=True)
        open(os.path.join(a.out, "ng_keys.bin"), "wb").write(k)
        open(os.path.join(a.out, "ng_tables.bin"), "wb").write(t)
        print(f"wrote ng_keys.bin + ng_tables.bin -> {a.out}")
