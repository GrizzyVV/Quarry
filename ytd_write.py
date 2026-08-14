"""ytd_write - ROUND-TRIP WRITER for .ytd texture dictionaries (RSC7 v13).

    inflated system+graphics segments -> value model -> written back -> reproduce original bytes

WHY: `.ytd` is 88,880 files - the LARGEST lane in GTA V. A lane with no writer is UNMEASURED,
not passing (Matt, 2026-08-13).

COVERAGE AT POPULATION 2026-08-14 - every `.ytd` in the game, 88,880 files / 335,752 textures:
    EXACT round-trip (every byte) : 88,876 / 88,879      (1 container REFUSED, see `read_ytd`)
    mean coverage 99.999996%   system segment 99.999796%   graphics segment 100.000000%
    ⭐ the graphics figure is a COUNTED zero-difference over 88,826 files, not a rounded 99.99.
TWO INDEPENDENT CHANGES LANDED THE SAME DAY; keep them apart, because they move the same number:
  * THE STRIDE LAW here (`stored_mipchain_bytes`): +3 files. Isolated by a control that graded
    every file in the lane under BOTH rules on identical inputs - 88,868 -> 88,871 byte-exact,
    31 files whose captured regions changed, coverage DOWN in 0, exact -> not-exact in 0. It
    takes the mean graphics segment from 99.999796% to a counted 100.000000%.
  * THE 0x18 HEADER SLOT in `quarry.py::Rpf.payload` (another agent, same day): +5 files, by
    making five containers decode that this reader had been refusing. Not this file's doing.
    See `read_ytd`, which had them diagnosed WRONG and now records what they actually are.
The 3 files still short are `peddamagedecals` / `hakuchou` / `innovation`, and the bytes they miss
are unreferenced build-tool source paths - DEAD SPACE, re-proven by a pointer-site scan over all
three (see `_cstr`). Their graphics segments are already 100.000000%.
Reproduce the board:  python tools/roundtrip_coverage.py --lane ytd --limit 250   -> 250/250.
Reproduce the population: tools/roundtrip_population_all.py --run --lanes ytd, then --report.

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
    +0x28 name* (cstr) · +0x40 usage/usage-flags · +0x50 w · +0x52 h · +0x54 depth ·
    +0x56 ROW PITCH (u16) · +0x58 format · +0x5D mips · +0x70 pixel data* (GRAPHICS segment)
⛔ There is no stored pixel-chain LENGTH; the chain is COMPUTED - see `stored_mipchain_bytes`,
which is NOT `ytd2xml.mipchain_bytes` and the difference is a format law. Never guess the span;
never fill from one region's end to the next region's start.
⭐ Δ 2026-08-14 - LEVEL 0 IS THE EXCEPTION AND IT IS STORED: `stride * h` at +0x56. `was:` "there
is NO stored pixel length ... COMPUTED from w/h/mips/format", which held for 335,697 of the lane's
335,729 textures and was wrong about the other 32 - every one a `script_rt_*` render target whose
FourCC says DXT1/DXT5 while its pitch says 4 bytes per pixel. The stored field wins. Full law,
population figures and refutation tests: `stored_mipchain_bytes`.

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


def stored_mipchain_bytes(w, h, mips, blk, bpp, stride=None):
    """Bytes the ARCHIVE stores for a mip chain: BLOCK-ROUNDED per level, dimensions floored at 1,
    with LEVEL 0 TAKEN FROM THE STORED ROW PITCH when one is present.

        size(level 0) = stride * h                                    [`stride` = u16 @ tex+0x56]
        size(level i) = ceil(max(1,w>>i)/4) * ceil(max(1,h>>i)/4) * blockBytes    [block formats]
        size(level i) = max(1,w>>i) * max(1,h>>i) * bytesPerPixel                 [linear formats]

    ============================================================================================
    THE STRIDE LAW (2026-08-14). THE PITCH IS STORED; THE LEVEL-0 SIZE IS NOT DERIVED FROM THE
    FourCC. Where the two disagree, the STORED FIELD is the authority and the FourCC is
    describing something the payload is not.

    MEASURED OVER THE WHOLE LANE - 88,880 `.ytd`, 335,729 textures (the population, not a draw):
        stride * h == block-rounded level 0 : 335,697   (99.99047%)
        disagree                            :      32
    and all 32 are ONE population, with no exception on any axis:
        * every name begins `script_rt_` - a script RENDER TARGET (32/32)
        ⛔ BUT THE NAME IS THE LEAD AND THE FIELD IS THE LAW, and the census says so out loud:
          the lane holds **184** `script_rt_*` textures and **152 of them AGREE** with their
          FourCC - ordinary compressed textures that merely carry a render-target name. Meanwhile
          **0 of the 335,568 non-`script_rt` textures disagree**. So the name is NECESSARY and NOT
          SUFFICIENT: keying this rule on the name would have widened 152 spans on no evidence.
          ⭐ AND THE PROOF IS INSIDE THE NAMES THEMSELVES: of the 41 distinct `script_rt_*` names
          in the lane, THREE appear BOTH WAYS - `script_rt_club_tv`, `script_rt_dials_cavalcade`
          and `script_rt_dials_truck` each ship in some dictionaries with a disagreeing stride and
          in others with an agreeing one. The same name, two storages. A name-keyed rule cannot
          even be stated for those three; the field decides every case.
          (This vault's own law: a filename cluster is a lead about WHERE a defect lands, never a
          format variant. Reproduce: `scratchpad/rt_name_census.py`.)
        * every one declares mips = 1 (32/32)
        * every one has stride == 4 * width EXACTLY, i.e. 4 bytes per pixel (32/32),
          over a block-compressed FourCC (31 DXT1, 1 DXT5) - the FourCC is the field that lies
        * so stride*h is 8x the FourCC level 0 for DXT1 and 4x for DXT5, never any other ratio

    WHY THIS IS EVIDENCE AND NOT A FILL (the test that could have REFUSED it, and did not):
      * NO OVER-RUN: over all 335,729 textures the claimed span never reaches past its segment
        and never touches the next payload allocation - 0 and 0. One overlap kills the law.
      * EXACT ABUTMENT: for 31 of the 32 the claim ENDS EXACTLY where the next allocation begins
        (28) or where the segment ends (3) - 0 bytes left over. A span guessed 1 byte wide either
        way could not land on 31 boundaries. The 32nd (`script_rt_club_tv`, a 4x4) is the last
        live allocation in its segment and leaves 81,856 trailing bytes, every one of them zero.
      * NOTHING LEFT BEHIND: 0 NON-ZERO bytes lie outside the claim anywhere in the lane. The
        old rule leaves non-zero bytes behind in exactly 3 textures (458,242 + 100,216 + 16 B).
      * NON-ZERO, never extent: 29 of the 32 render targets carry an all-zero surface, so the
        round-trip measure CANNOT vouch for their widened span - it is vouched for by the stored
        field, the abutment and the no-overlap test, and that distinction is stated, not blurred.

    WHAT THE EXTRA BYTES ARE IS **NOT** SETTLED, AND IS DELIBERATELY NOT CLAIMED. Only the SPAN
    is pinned. The three witnesses that carry data disagree about the content: `iwagen`'s region
    is `b0 b0 b0 ff` repeating (a uniform 32-bit BGRA surface), `sf_prop_sf_handler_01a`'s reads
    as float32 quads ending 00 00 80 3f (= 1.0f), and `h4_prop_battle_club_screen`'s 4x4 carries
    a 56-byte integer struct after its 8 pixel bytes:
        04 00 00 00 | 04 00 00 00 | 08 00 00 00 | 01 00 00 00 | 70 3e 8b 0b 00000000 |
        00 3e 8b 0b 00000000 | 13 00 00 00 | 08 00 00 00 | 04 00 00 00 | 04 00 00 00 | 04000000
    i.e. width, height, the FourCC level-0 size, the mip count, two 64-bit words, then five more.
    Enough to see it is a DESCRIPTOR, not enough to name its fields - so it is mapped here and
    nothing downstream re-labels the format. See the `ytd2xml` counter of the same name.

    LANE EFFECT, before -> after, per file over all 88,874 graded:
        byte-EXACT 88,868 -> 88,871      regressions 0      files whose output changed 31
    ▶ REPRODUCE (one walk, every file graded under BOTH rules, so before/after is per file and not
      two runs compared):
        python scratchpad/rt_ytd_stride_sweep.py --workers 6 --worker-id <0..5> --out <dir>
      Re-running it AFTER this edit is the equivalence control: `files_changed` must be 0 (the
      shipped rule and the measured rule are the same function) - it was, over all 88,879.
    28 of those 31 were already byte-exact (their render target is zero-filled, so the widened
    span costs and buys nothing); the 3 that flip are the only ones whose RT carries data.
    ⚠ UNWITNESSED SHAPES ARE COUNTED, NOT GUESSED. A disagreeing texture with mips > 1 would need
    a level-1+ rule this population contains no witness for, and a stride that SHRINKS the span
    has never been seen either. Both keep the block-rounded chain and raise a counter (both
    MEASURED 0 over 335,729 textures) rather than inventing a number.

    ⭐ CORROBORATED INDEPENDENTLY, ON A DIFFERENT LANE, THE SAME DAY. `ydr_write._texdict`
    (ydr_write.py ~1064) derived the same rule from `.ydr` EMBEDDED dictionaries - "the row pitch
    is stored and it overrules the FourCC", 623/623 on a fresh 250-file draw, and the 18 that
    disagree are exactly the script render targets its writer could not reach. Two lanes, two
    samples, two derivations, one field. Its 4x4 control is the sharpest single witness in either
    lane: the SAME dimensions and the SAME FourCC carry pitch 2 on an ordinary texture and pitch
    16 on a render target, so the FIELD and not the format is what separates them.
    ⚠ ONE DIVERGENCE, IN THE CORNER NEITHER LANE HAS A WITNESS FOR: for a disagreeing texture with
    mips > 1, `ydr_write` recomputes the WHOLE chain as a LINEAR format at `pitch/w` bytes per
    pixel, while this function keeps the block-rounded chain and counts. For mips == 1 - every
    witness in both lanes - the two are identical (`level_sizes(w,h,1,None,bpp)[0] == pitch*h`),
    so nothing observable depends on it today. Whoever gets a mipped render-target oracle should
    settle it in both files at once.
    ============================================================================================

    THE BLOCK-ROUNDED RULE ITSELF (levels 1+, and level 0 wherever no stride is stored):

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
            n = ((ww + 3) // 4) * ((hh + 3) // 4) * blk
        else:
            n = ww * hh * bpp
        if i == 0 and stride and stride * h != n:
            # THE STRIDE LAW, applied only in the shape all 32 witnesses share. Anything else is
            # COUNTED and left on the block-rounded chain - a visible gap beats an invented
            # number. Both counters MEASURED 0 over the lane's 335,729 textures.
            if mips > 1:
                REFUSALS['stride_disagrees_and_texture_is_MIPPED_no_witness'] += 1
                REFUSAL_NOTES.setdefault('mipped_stride_disagreement',
                                         '%dx%d mips=%d stride=%d' % (w, h, mips, stride))
            elif stride * h < n:
                REFUSALS['stride_would_SHRINK_the_span_no_witness'] += 1
                REFUSAL_NOTES.setdefault('shrinking_stride',
                                         '%dx%d stride=%d vs level0 %d' % (w, h, stride, n))
            else:
                n = stride * h
        t += n
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
        ⭐ Δ 2026-08-14 at POPULATION it is THREE files of 88,874, not one of 1,519, and all three
        are the same shape: `x64a.rpf::peddamagedecals.ytd` (652 B in 11 runs, system 92.041%),
        `mplts::hakuchou.ytd` (403 B in 5, 95.081%) and `mplts::innovation.ytd` (429 B in 5,
        94.763%). The graphics segment of all three is already 100.000000%; only these strings are
        missing, and the two DLC ones read `x:/gta5_dlc/mpPacks/mpLTS/assets/vehicles/textures/
        <car>/<texture>.dds` - the same build-tool residue in the same place.
        ⭐ THE POINTER-SITE SCAN WAS RE-RUN ON ALL THREE (2026-08-14), not just the first: every
        4-byte-aligned u32 in each 8,192 B system segment, 2,048 sites per file. TAG-5/TAG-6
        pointers landing anywhere in the dead band: **0, 0 and 0**. The only numeric coincidences
        (2 / 0 / 1) carry other tags, so they are values, not pointers.
        The `peddamagedecals` map below is the worked example; every run is one NUL-terminated
        ASCII source path:
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
        actually there rather than dropping the texture, and never past the segment end.

        ✅ CLOSED 2026-08-14 BY THE STRIDE LAW, NOT BY WIDENING THIS CAPTURE. The lane's entire
        remaining graphics-segment gap sat directly after this call and was a `script_rt_*` render
        target every time - three files, 558,474 non-zero bytes:
            iwagen.ytd                     script_rt_dials_cavalcade 512x256 m1 -> 458,242 B
            sf_prop_sf_handler_01a.ytd     script_rt_dials_truck     256x128 m1 -> 100,216 B
            h4_prop_battle_club_screen.ytd script_rt_club_tv           4x4   m1 ->      16 B
        `need` now comes from the STORED ROW PITCH (u16 @ tex+0x56) for level 0, which is a field
        of the file rather than a distance to the next thing - so the span is still DERIVED, and
        `stored_mipchain_bytes` still never claims a neighbour's bytes (0 over-runs, now measured
        over 335,729 textures rather than 2,969). The full law and its refutation tests are in
        that function's docstring; the population numbers are there too.
        ⛔ THE ORIGINAL WARNING STANDS FOR ANY FUTURE GAP: do not close one by filling to the next
        region. The reason this one could be closed is that a stored field turned out to state the
        answer - the fix was to find the field, not to widen the claim.
        """
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
            # +0x56 is the STORED ROW PITCH and it outranks the FourCC for level 0 - see the
            # stride law in `stored_mipchain_bytes`. Read here rather than inferred there so the
            # rule takes the file's own field and never a reconstruction of it.
            stride = struct.unpack_from('<H', s, tp + 0x56)[0]
            mips = max(1, s[tp + 0x5D])
            fmt = struct.unpack_from('<I', s, tp + 0x58)[0]
            _x, blk, bpp = ytd2xml.describe_format(fmt)
            need = stored_mipchain_bytes(w, h, mips, blk, bpp, stride)
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

    ⛔⛔ RETRACTED 2026-08-14 - **5 OF THE 6 ARE NOT BROKEN FILES. THE BODY IS BEING CUT IN THE
    WRONG PLACE, AND THE "GARBAGE" IS OURS.** `was:` this note read "SHORT-BODY GARBAGE (4)...
    entropy 7.94-7.98 bits/byte and a texture count that cannot fit an 8 KB system segment" and
    "51-BYTE STUB (2)... there is no dictionary here to read at all", concluding "neither shape is
    readable, so neither is fixable without inventing content". Both halves were wrong, and the
    evidence for them was an artifact of the extraction path.

    WHAT IS ACTUALLY TRUE (measured 2026-08-14, all 6 entries located in their own archives and
    every decode route tried - plain / NG at five different length inputs / AES-ECB / Oodle, from
    every start offset in 0..95):
      * 5 of the 6 live in **AES-encrypted archives** (`enc = 0x0ffffff9`) - the nested
        `des_*.rpf` under `x64f.rpf`. In all five, a raw-DEFLATE stream begins at entry offset
        **+0x18, not +0x10**, and inflates to EXACTLY the declared page plan, `d.eof` True,
        unused_input 0:
            v_des_truck_txd.ytd    188,416 B   des_hosp_ceil_txd.ytd  139,264 B
            v_des_ceil2_txd.ytd     49,152 B   des_hosp_ceil.ytd        8,192 B
            des_hosp_ceil2_txd.ytd   8,192 B
      * Cut there, all five READ AS DICTIONARIES with plausible names (`ss_v_ceilingtile1`,
        `tl_v_office_metal_burnt`, `rnbj_grafwall_0001`, `v_p_mi_marfrm_n1_aa_nm` ...) and all
        five ROUND-TRIP **BYTE-EXACT** through this writer, unchanged - 7, 5, 11, 0 and 0
        textures. The two "51-byte stubs" are legitimately EMPTY pgDictionaries: a 43-byte deflate
        stream of near-zeros expanding to an 8,192 B system segment, which is why their stored
        bodies are identical after the first 8 bytes.
      * The high entropy was manufactured downstream: the extraction path takes the body at +0x10,
        no route decodes it, and its last-resort `RESOURCE_STORED_RAW` fallback re-deflates the
        STILL-COMPRESSED bytes. Inflating that returns the compressed stream, which is of course
        7.9 bits/byte with all 256 values present and declares 9,368 textures.
      * `parachute_decals.ytd` is the ONE genuine unknown left. It is the only one in an **NG**
        archive (x64a.rpf), and NO start offset in 0..95 yields a deflate stream on any route. It
        stays refused, and honestly so.
    ⇒ A CONTAINER-HANDLING defect, not a file problem, and never confined to `.ytd`: every
    resource in those archives goes down the same path.
    ✅ FIXED THE SAME DAY IN `quarry.py::Rpf.payload` BY ITS OWNER, independently and more widely:
    the on-disk resource header slot is 0x18 bytes in SIX archives (`des_setpiece`, `des_hosp_ceil`,
    `des_hosp_ceil2`, `des_fib_ceiling2`, `des_bridge`, `x64j/id2_17`), 23 of 23 resources in them
    and 0 anywhere else, tied to an older BUILD (the v164 `.ydr` / v43 `.ycd` / v40 `.ybd` all live
    there). This file was NOT the one edited. Two independent derivations of the same offset, both
    gated on the page plan, is a real cross-check - and it is why all five now grade here.
    AFTER that fix, measured over the whole lane: graded 88,879, refused 1, byte-exact 88,876.
    ⚠ WHAT IS STILL REFUSED, AND HONESTLY: `parachute_decals.ytd` alone. It is the only one in an
    NG archive, it is not in the 0x18 set, and NO start offset in 0..95 yields a deflate stream on
    any route (plain / NG at five length inputs / AES-ECB / Oodle). Unexplained, not excused.
    ▶ REPRODUCE: `scratchpad/rt_refused_routes.py` (every route), `rt_refused_scan.py` (every start
      offset), `rt_refused_readback.py` (cut at +0x18, read the dictionary, grade the round-trip).

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
