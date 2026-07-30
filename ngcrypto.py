"""ngcrypto - RAGE 'NG' block cipher + AES usage, implemented from a behavioural spec.

Written from a factual description of the algorithm (round structure, table indexing,
key selection), NOT copied from any implementation. Tables and key material are DATA and
are never bundled here - they are loaded from a path the operator supplies (see keys.py).

Structures this expects:
  ng_keys    : 101 x 68 uint32   (101 keys, each 17 subkeys x 4 uint32 = 272 bytes)
  ng_tables  : 17 x 16 x 256 uint32   (per round, per byte-position, per byte value)

Round structure (17 rounds):
  round A with subkey[0],  table set 0
  round A with subkey[1],  table set 1
  rounds B for k = 2..15,  subkey[k], table set k
  round A with subkey[16], table set 16

Round A - output uint i is built from four sequential byte positions:
  out[i] = T[4i+0][b[4i+0]] ^ T[4i+1][b[4i+1]] ^ T[4i+2][b[4i+2]] ^ T[4i+3][b[4i+3]] ^ key[i]

Round B - same, but the DATA byte positions are permuted while table slots stay
sequential:
  out[0] <- data bytes 0, 7,10,13
  out[1] <- data bytes 1, 4,11,14
  out[2] <- data bytes 2, 5, 8,15
  out[3] <- data bytes 3, 6, 9,12

Per-file key selection:  index = (hash(name) + filesize + 61) % 101
"""
import struct

import numpy as np

M32 = 0xFFFFFFFF

# byte positions feeding each output uint, per round type
ROUND_A_IDX = [(0, 1, 2, 3), (4, 5, 6, 7), (8, 9, 10, 11), (12, 13, 14, 15)]
ROUND_B_IDX = [(0, 7, 10, 13), (1, 4, 11, 14), (2, 5, 8, 15), (3, 6, 9, 12)]


def _round(block16, subkey4, tset, idx_map):
    """One NG round. tset is a (16,256) uint32 table set; idx_map picks data bytes.

    THE TABLE IS INDEXED BY BYTE POSITION, not by a sequential slot counter. The two are
    identical in round A (positions are 4i..4i+3) and diverge in round B, where the
    positions are permuted - which is exactly where a sequential index silently produces
    garbage. Verified against the root-directory oracle (try_variants.py)."""
    out = bytearray(16)
    for i in range(4):
        v = 0
        for dpos in idx_map[i]:
            v ^= int(tset[dpos][block16[dpos]])
        v = (v ^ subkey4[i]) & M32
        struct.pack_into('<I', out, i * 4, v)
    return bytes(out)


def decrypt_block(block16, key68, tables):
    """Decrypt one 16-byte block. key68 = 68 uint32; tables = (17,16,256) uint32."""
    b = block16
    b = _round(b, key68[0:4], tables[0], ROUND_A_IDX)
    b = _round(b, key68[4:8], tables[1], ROUND_A_IDX)
    for k in range(2, 16):
        b = _round(b, key68[k * 4:k * 4 + 4], tables[k], ROUND_B_IDX)
    b = _round(b, key68[64:68], tables[16], ROUND_A_IDX)
    return b


def decrypt(data, key68, tables):
    """Whole buffer, VECTORISED over blocks. Any trailing partial block passes through.

    The scalar path is ~256 table lookups per 16 bytes; on a megabyte file that is tens
    of millions of Python operations. Here every block is transformed simultaneously with
    numpy gathers, which is what makes bulk extraction practical rather than overnight.
    """
    nb = len(data) // 16
    if nb == 0:
        return data
    b = np.frombuffer(bytes(data[:nb * 16]), np.uint8).reshape(nb, 16)
    key = np.asarray(key68, dtype=np.uint32)
    order = [(0, ROUND_A_IDX), (1, ROUND_A_IDX)]
    order += [(k, ROUND_B_IDX) for k in range(2, 16)]
    order += [(16, ROUND_A_IDX)]
    for r, idx_map in order:
        tset = tables[r]
        out = np.empty((nb, 4), dtype=np.uint32)
        for i in range(4):
            acc = np.zeros(nb, dtype=np.uint32)
            for dpos in idx_map[i]:
                acc ^= tset[dpos][b[:, dpos]]
            out[:, i] = acc ^ key[r * 4 + i]
        b = out.view(np.uint8).reshape(nb, 16)
    tail = bytes(data[nb * 16:])
    return b.tobytes() + tail


def key_index(name_hash, file_size):
    """Which of the 101 keys a given file uses.

    ⚠ The sum is UINT32 arithmetic and MUST wrap before the modulo. Python ints are
    unbounded, so omitting the mask silently picks the wrong key whenever
    name_hash + file_size + 61 >= 2**32 - and a wrong key yields garbage that only shows
    up as a failed TOC sanity check, i.e. an archive that looks 'encrypted with keys we
    don't have'. Because 2**32 % 101 == 68, the unmasked index is off by exactly
    -68 == +33 (mod 101) in that case.
    Found 2026-07-26: 6 of the 24 base archives (x64c, x64e, x64j, x64k, x64q, x64u) were
    being silently skipped for this reason; masking fixes all six and is a NO-OP on every
    archive that already worked (123/123 decode after the fix).
    """
    return ((int(name_hash) + int(file_size) + 61) & M32) % 101


def joaat(s):
    """Jenkins one-at-a-time over the lowercased name (RAGE's usual name hash)."""
    h = 0
    for c in s.lower():
        h = (h + ord(c)) & M32
        h = (h + (h << 10)) & M32
        h ^= h >> 6
    h = (h + (h << 3)) & M32
    h ^= h >> 11
    return (h + (h << 15)) & M32


# ---------------------------------------------------------------- AES (for magic/AES rpfs)
def aes_decrypt(data, key32, passes=1):
    """AES-256 ECB, no padding, applied `passes` times over whole 16-byte blocks."""
    from Crypto.Cipher import AES
    c = AES.new(key32, AES.MODE_ECB)
    n = len(data) & ~0xF
    head, tail = data[:n], data[n:]
    for _ in range(passes):
        head = c.decrypt(head)
    return head + tail


def tables_from_bytes(raw):
    """(17,16,256) uint32 table set from 278,528 bytes in memory."""
    need = 17 * 16 * 256 * 4
    if len(raw) < need:
        raise ValueError(f'need {need} bytes of NG tables, got {len(raw)}')
    return np.frombuffer(bytes(raw), np.uint32, count=17 * 16 * 256).reshape(17, 16, 256)


def keys_from_bytes(raw):
    """(101,68) uint32 key table from 27,472 bytes in memory."""
    need = 101 * 272
    if len(raw) < need:
        raise ValueError(f'need {need} bytes of NG keys, got {len(raw)}')
    return np.frombuffer(bytes(raw), np.uint32, count=101 * 68).reshape(101, 68)


def load_tables(path):
    """(17,16,256) uint32 table set from a flat binary (278,528 bytes)."""
    return tables_from_bytes(open(path, 'rb').read())


def load_keys(path):
    """(101,68) uint32 key table from a flat binary (27,472 bytes)."""
    return keys_from_bytes(open(path, 'rb').read())
