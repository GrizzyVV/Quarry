"""ytd_write - ROUND-TRIP WRITER for .ytd texture dictionaries (RSC7 v13).

    inflated system+graphics segments -> value model -> written back -> reproduce original bytes

WHY: `.ytd` is 88,880 files - the LARGEST lane in GTA V. A lane with no writer is UNMEASURED,
not passing (Matt, 2026-08-13).

COVERAGE 2026-08-14, over 1,519 unique .ytd from 24 archives (x64a..x64v, update.rpf, one DLC
pack), 9,997 textures, 2.35 GB of inflated segments:
    EXACT round-trip (every byte) : 1,517 / 1,518        (+1 container REFUSED, see `read_ytd`)
    system   segment : 12,795,252 / 12,795,904 B    = 99.994905%
    graphics segment : 2,336,563,200 / 2,336,563,200 B = 100.000000%  (ZERO bytes differ)
    overall          : 2,349,358,452 / 2,349,359,104 B = 99.999972%
⭐ The graphics figure is a counted zero-difference, not a rounded 99.99. Reproduce:
    python tools/roundtrip_coverage.py --lane ytd            (needs the LANES entry, see below)
which on x64a/x64b/x64c at --limit 250 reports 248/249 exact, sys 99.9680%, gfx 100.0000%.
⚠ `tools/roundtrip_coverage.py::LANES` does not yet carry this lane; it is another agent's file
and was NOT edited. The entry it needs is:
    'ytd': ('ytd_write', 'read_ytd', ('x64a.rpf', 'x64b.rpf', 'x64c.rpf')),

⚠ TWO SEGMENTS. The dictionary graph lives in `sys`; the PIXELS live in `gfx` and are 99.5% of the
bytes, so coverage is reported per segment - a blended number would hide which half is modelled.

STRUCTURE (the root of a .ytd IS a pgDictionary<grcTexture> - the same structure `ydr_write._texdict`
walks at ShaderGroup+0x08, which is why the shape is shared rather than re-derived):
  dict @ sys 0x00, 0x40 bytes
    +0x08 blockmap ptr (the page-count record - see `write()`)
    +0x20 hash array ptr   -> count * 4   (u32 joaat(name) per texture, ASCENDING)
    +0x28 (capacity<<16) | count          (capacity == count in 1,519/1,519)
    +0x30 pointer array ptr -> count * 8  (one 64-bit tagged pointer per texture)
    +0x38 (capacity<<16) | count again, for the pointer list
  grcTexture (0x90) - offsets from `ytd2xml`, measured over 1,199 archive files + the oracle set:
    +0x28 name* (cstr) · +0x40 usage/usage-flags · +0x50 w · +0x52 h · +0x58 format ·
    +0x5D mips · +0x70 pixel data* (GRAPHICS segment)
⛔ There is NO stored pixel length. It is COMPUTED from w/h/mips/format - see
`stored_mipchain_bytes`, which is NOT `ytd2xml.mipchain_bytes` and the difference is a format law.
Never guess the span; never fill from one region's end to the next region's start.

MEASURED CONSTANTS (swept, not chosen - 300 files, system-segment coverage):
  TEX_SPAN   0x60 -> 99.8679%  |  0x80 / 0x90 / 0xA0 / 0xC0 / 0x100 -> 99.9734% (all IDENTICAL)
  DICT_SPAN  0x30 -> 99.9167%  |  0x40 / 0x50 / 0x80             -> 99.9734% (all IDENTICAL)
⭐ Past 0x80 / 0x40 the sweep is FLAT, so a wider span buys nothing and can only claim a
neighbour's bytes. Both values are therefore taken from STRUCTURE, not from the sweep:
0x90 is the measured spacing of consecutive grcTexture records (1,113 of 1,117 consecutive pairs
in the sample are exactly 144 bytes apart, and 144 is the MINIMUM observed - no record is denser),
and 0x40 is where the first record begins.
  page-count law ON -> 298/299 byte-exact | OFF -> 0/299. It is the single unreproduced u32/file.
  stored mip chain: block-rounded -> 298/299 exact, gfx 100.000000%
                    quarter chain -> 271/299 exact, gfx  99.999551%
ASCII output only.
"""
import collections
import os
import struct
import sys as _sys

_sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ydr2xml import Res, seg_size  # noqa: E402
import ytd2xml  # noqa: E402


class ContainerError(ValueError):
    """The RSC7 container did not decode to the segment plan its own flags declare. Raised rather
    than modelled: every count and pointer read from a short buffer is garbage, and a garbage
    count produces a garbage model that then gets reported as a format finding."""

DICT_SPAN = 0x40
TEX_SPAN = 0x90
NAME_LIMIT = 160

# ⛔ A DROP WITH NO COUNTER IS INDISTINGUISHABLE FROM "NOTHING TO DO" - the same idiom `ydr2xml`
# and `ytd2xml` use. Process-global, accumulates across a run; read it to report the gap.
# MEASURED 2026-08-14 over 1,519 archive .ytd / 9,997 textures: every counter ZERO.
REFUSALS = collections.Counter()
REFUSAL_NOTES = {}


def stored_mipchain_bytes(w, h, mips, blk, bpp):
    """Bytes the ARCHIVE stores for a mip chain: BLOCK-ROUNDED per level, dimensions floored at 1.

        size(level i) = ceil(max(1,w>>i)/4) * ceil(max(1,h>>i)/4) * blockBytes    [block formats]
        size(level i) = max(1,w>>i) * max(1,h>>i) * bytesPerPixel                 [linear formats]

    ⛔ THIS IS NOT `ytd2xml.mipchain_bytes`, AND THE DIFFERENCE IS A REAL FORMAT LAW, not a tweak.
    `ytd2xml.level_sizes` quarters mip-0's byte count per level (`top >> 2i`), which is what the
    reference EXPORTER writes into its sidecar .dds - 237/237 against those sidecars. But the
    sidecar is the exporter's own output, so agreeing with it only proves we match the exporter.
    ROUND-TRIP IS THE COUNTER-WITNESS: measured 2026-08-14 over 2,969 textures in 684 archive
    dictionaries, comparing each payload against the last NON-ZERO byte before the next texture's
    payload starts, and against the space actually available before that payload:
        quarter chain   : UNDER-READS 291 / 2969,  over-runs 0,  exact 2370
        block-rounded   : under-reads   0 / 2969,  over-runs 0,  exact 2652
    (the 317 non-exact block-rounded cases end in a genuinely zero byte, which a last-non-zero
    probe cannot see; ZERO over-runs proves the rule never claims a neighbour's bytes, which is
    the property that separates a format law from a fill-to-the-next-region.)
    The two rules agree while every level's dimensions stay >= 4 and divide evenly, and diverge in
    the TAIL: e.g. 256x256 DXT5 mips=9 stores 87,408 B, the quarter chain computes 87,381 - the
    last three levels are 4x4-block MINIMA (16 B each), not 16/4/1. Every gap in the graphics
    segment of the first pass was exactly this tail.
    ⚠ CONSEQUENCE FOR THE OTHER LANES, MEASURED BUT NOT FIXED HERE - `ytd2xml.mipchain_bytes` is
    also what `ydr_write._texdict` (ydr2xml.py:349) and `ytd2xml._read_one_texture` (the .dds
    sidecar payload for the WHOLE extraction pipeline) use. Monkeypatching this rule in at runtime
    over 150 base-game `.ydr` from x64c/x64a (2026-08-14, `crosslane.py`; neither file edited):
        quarter chain : byte-exact 112/150, gfx 80,993,788 / 80,994,304 = 99.999363%
        block-rounded : byte-exact 135/150, gfx 80,994,304 / 80,994,304 = 100.000000%
    i.e. it closes ydr's ENTIRE remaining graphics-segment gap (516 B -> 0) and 23 more files
    round-trip exactly. The edit belongs in `ytd2xml.level_sizes`; that file is another agent's.
    ⭐ THE DISAGREEMENT WAS ALREADY INSTRUMENTED AND WRONGLY EXEMPTED. `tools/pixel_repackage_
    check.py::expected_bytes` is an independent implementation of exactly this block-floor rule,
    and its run reports "276 of 711 textures match the MEASURED shift law (expected) ... ZERO
    unexplained: PASS". Round-trip inverts that verdict: the two rules differ only in the tail, and
    the tail bytes ARE IN THE ARCHIVE, so the shift law is the one that is short. A green board
    with a standing exemption is how this stayed invisible.
    """
    t = 0
    for i in range(max(1, mips)):
        ww, hh = max(1, w >> i), max(1, h >> i)
        if blk is not None:
            t += ((ww + 3) // 4) * ((hh + 3) // 4) * blk
        else:
            t += ww * hh * bpp
    return t


class Ytd:
    def __init__(self, res, flags=(0, 0)):
        self.res = res
        self.sys_flags, self.gfx_flags = flags
        self.nsys, self.ngfx = len(res.sys), len(res.gfx)
        self.sysr, self.gfxr = [], []
        self.ntex = 0
        self._dict(0)

    # ---- segment-aware capture (same shape as ydr_write: a tagged pointer may land in either)
    def _put(self, off, nbytes, seg='sys'):
        if off is None or nbytes <= 0:
            return
        if seg == 'gfx':
            if off + nbytes <= self.ngfx:
                self.gfxr.append((off, bytes(self.res.gfx[off:off + nbytes])))
        elif off + nbytes <= self.nsys:
            self.sysr.append((off, bytes(self.res.sys[off:off + nbytes])))

    def _res(self, tagged, nbytes=1):
        buf, off = self.res.deref(tagged, nbytes)
        if buf is None:
            return None, None, None
        return buf, off, ('gfx' if buf is self.res.gfx else 'sys')

    def _flat(self, tagged, nbytes):
        buf, off, seg = self._res(tagged, max(nbytes, 1))
        if buf is None:
            return
        self._put(off, nbytes, seg)

    def _cstr(self, tagged):
        """Capture a NUL-terminated name INCLUDING its terminator - and no further. Capturing a
        fixed 64 bytes here would claim whatever follows the string, which on a packed string
        table is the NEXT name; that is the fill-to-the-next-region failure in miniature.

        ⏭ THE ENTIRE REMAINING GAP IN THIS LANE LIVES BESIDE THIS CALL - and it is UNREACHABLE.
        1 file of 1,519 has any unreproduced byte: `x64a.rpf::peddamagedecals.ytd`, 652 B in 11
        runs (system 92.041%), and every run is one NUL-terminated ASCII source path:
            0x0730 len 66 | 0x0780 len 68 | 0x07D0 len 66 | 0x0820 len 57 | 0x0860 len 55
            0x08A0 len 58 | 0x08E0 len 57 | 0x0920 len 60 | 0x0960 len 57 | 0x09A0 len 53
            0x09E0 len 55
        every one begins 78 3a 5c 67 74 61 35 5c ("x:\gta5\") and reads
            x:\gta5\art\ng\Textures\peddamagedecals\<texture>.dds
        One per texture, on a 0x40/0x50 pitch in a block at 0x0730..0x0A4F, i.e. immediately
        BEFORE the short-name block at 0x0A50 that the +0x28 name pointers do reach.
        ⛔ RULED OUT - IT IS DEAD SPACE, NOT A MISSED STRUCTURE. A pointer-site scan over every
        4-byte-aligned u32 in the whole system segment finds ZERO tag-5/tag-6 pointers into
        0x0730..0x0A4F; the dictionary's own highest live targets are 0x0A20 (hash array) and
        0x0A50..0x0AF9 (the 11 short names). The only two numeric coincidences carry tag 0, so
        they are values, not pointers. Nothing in the resource references these strings: they are
        build-tool residue left in the page. No walk can ever reach them, and reaching them would
        require claiming bytes on no evidence - which is the failure this measure exists to catch.
        DO NOT "close" this gap.
        """
        buf, off, seg = self._res(tagged, 1)
        if buf is None:
            return
        end = buf.find(b'\x00', off)
        if end < 0 or end - off > NAME_LIMIT:
            end = min(off + NAME_LIMIT, len(buf)) - 1
        self._put(off, end - off + 1, seg)

    def _pixels(self, tagged, need):
        """The mip chain. If the declared chain runs past the end of its segment the payload is
        TRUNCATED (`ytd2xml` sees the same shape and keeps the levels that fit) - capture what is
        actually there rather than dropping the texture, and never past the segment end."""
        buf, off, seg = self._res(tagged, 1)
        if buf is None:
            return
        self._put(off, min(need, len(buf) - off), seg)

    def _dict(self, base):
        s = self.res.sys
        self._put(base, DICT_SPAN)
        try:
            count = struct.unpack_from('<I', s, base + 0x28)[0] & 0xFFFF
            hash_p = struct.unpack_from('<I', s, base + 0x20)[0]
            arr_p = struct.unpack_from('<I', s, base + 0x30)[0]
        except struct.error:
            return
        if not count:
            return                             # an empty dictionary is ordinary, not a failure
        self._flat(hash_p, count * 4)          # u32 joaat per texture
        self._flat(arr_p, count * 8)           # 64-bit pointer per texture
        _b, arr, aseg = self._res(arr_p, count * 8)
        if arr is None or aseg != 'sys':
            # ⛔ NEVER SIZE A READ FROM THE FIELD UNDER TEST AND THEN TRUST IT. `count` is the
            # field being tested; if the pointer array it claims does not fit the segment the
            # count is wrong, so nothing downstream of it is read - and `ntex` is not advertised.
            REFUSALS['pointer_array_does_not_fit_declared_count'] += 1
            return
        self.ntex = count
        for i in range(count):
            try:
                tp_raw = struct.unpack_from('<I', s, arr + i * 8)[0]
            except struct.error:
                break
            self._texture(tp_raw)

    def _texture(self, tagged):
        s = self.res.sys
        _b, tp, seg = self._res(tagged, TEX_SPAN)
        if tp is None or seg != 'sys':
            return
        self._put(tp, TEX_SPAN)
        try:
            self._cstr(struct.unpack_from('<I', s, tp + 0x28)[0])
            w = struct.unpack_from('<H', s, tp + 0x50)[0]
            h = struct.unpack_from('<H', s, tp + 0x52)[0]
            mips = max(1, s[tp + 0x5D])
            fmt = struct.unpack_from('<I', s, tp + 0x58)[0]
            _x, blk, bpp = ytd2xml.describe_format(fmt)
            need = stored_mipchain_bytes(w, h, mips, blk, bpp)
            self._pixels(struct.unpack_from('<I', s, tp + 0x70)[0], need)
        except Exception as ex:
            # an unmapped format must cost THIS texture's pixels, never the dictionary - and the
            # drop is COUNTED, because a silent skip is indistinguishable from nothing to do.
            REFUSALS['texture_pixels_%s' % type(ex).__name__] += 1
            REFUSAL_NOTES.setdefault(type(ex).__name__, str(ex)[:90])
            return

    def write(self):
        si, gi = bytearray(self.nsys), bytearray(self.ngfx)
        for off, data in self.sysr:
            si[off:off + len(data)] = data
        for off, data in self.gfxr:
            gi[off:off + len(data)] = data
        # THE PAGE-COUNT LAW: a COMPUTED field, not a carried one. Skipping it leaves exactly one
        # unreproduced u32 in every file.
        try:
            import meta_write
            buf, o = self.res.deref(self.res.ptr(0x08), 16)
            if buf is not None and o + 12 <= len(si):
                val = ((meta_write.page_count(self.sys_flags) & 0xFF)
                       | ((meta_write.page_count(self.gfx_flags) & 0xFF) << 8))
                si[o + 8:o + 12] = struct.pack('<I', val)
        except Exception:
            pass
        return bytes(si), bytes(gi)

    @staticmethod
    def _same(a, b):
        """How many bytes of `a` equal `b`. Identical result to a per-byte loop, ~100x faster:
        XOR the two buffers as one big integer and count the ZERO bytes of the difference.
        `.ytd` is the pixel lane - a 4 MB graphics segment per file over a 250-file harness run is
        ~1 GB of comparisons, and the naive loop made the sweep table unaffordable to measure.
        (Cross-checked against the loop on the first 40 files of the sample: identical counts.)"""
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


def read_ytd(src):
    """bytes | path -> Ytd. REFUSES a container whose inflated payload is shorter than its own
    declared segment plan.

    ⛔ WHY A REFUSAL AND NOT A BEST EFFORT: measured 1 of 300 archive `.ytd` (2026-08-14,
    `x64a.rpf::parachute_decals.ytd`): flags declare sys 8,192 + gfx 786,432, the raw-deflate
    stream inflates cleanly and completely (unused_input = 0) to 73,349 bytes, and every byte of
    it is high-entropy (7.937 bits/byte, all 256 values present, no `RSC7`/`DXT` substring). Read
    as a dictionary it declares **9,368 textures inside an 8 KB system segment**. Modelling that
    yields a number (0.318%) that describes nothing. `ytd2xml.read_textures` already refuses the
    same file loudly ("texture pointer array is out of bounds"), so this matches the lane's
    existing behaviour rather than inventing an exemption. The refusal is COUNTED by the harness,
    never silent.
    """
    blob = bytes(src) if isinstance(src, (bytes, bytearray)) else open(src, 'rb').read()
    _m, _v, sysf, gfxf = struct.unpack_from('<4sIII', blob, 0)
    res = Res.from_bytes(blob)
    want_s, want_g = seg_size(sysf), seg_size(gfxf)
    if len(res.sys) < want_s or len(res.gfx) < want_g:
        raise ContainerError(
            'inflated payload %d+%d B is short of the declared plan %d+%d B'
            % (len(res.sys), len(res.gfx), want_s, want_g))
    return Ytd(res, (sysf, gfxf))
