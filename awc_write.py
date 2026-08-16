"""awc_write - ROUND-TRIP WRITER for .awc (AudioWaveContainer), plaintext 'ADAT' class.

    original binary -> value model -> written back -> MUST reproduce the original bytes

WHY (maintainer ruling 2026-08-13): round-trip byte identity is the primary measure. `.awc` is
**7,742 files and 42.54 GB of payload, the largest lane in the game by byte**, and until now it had
a READER (`awc2xml.py`) that WAS NEVER WIRED - the string `awc` appears zero times in `quarry.py` -
so the lane was UNMEASURED, and not even converted: the bytes fell through to a verbatim copy, and
byte-identity there was by NON-CONVERSION, not by a modelled round-trip.

⭐ THE OLD BLOCKER IS RETIRED, NOT WORKED AROUND. `awc2xml`'s docstring parks the lane because its
only oracles are encrypted, so the plaintext path had no reference witness. That mattered only
while reference-parity was the measure. **Under round-trip the file is its own oracle** and a lane needs
no external witness.

POPULATION RESULT (2026-08-15, `python tools/awc_population.py`, 435 s):
    SAMPLE SIZE 7,742 .awc walked from the GAME across 100 archives - EQUAL TO THE CENSUS
    (`output/view/VIEW_MANIFEST.jsonl`) TO THE FILE, verified by `tools/awc_reconcile.py`
    (shortfall 0, every archive reconciling).
      container gate : 2,100 ENCRYPTED (27.12%, 1.97 GB) - a COUNTED REFUSAL, named reason
      plaintext      : 5,642 / 5,642 byte-exact, mean 100.0000%, min 100.0000%, 40.56 GB
      BYTE ACCOUNT   : VALUE 1.5840% | DERIVED 0.0001% | ZERO-FILL 0.0031% | CARRIED 98.4128%
      must-fail control: `tools/awc_control.py`, 12 mutations, 3,872/3,872 caught (100.00%)
                         over a draw BALANCED across both file shapes (200 / 200)

⛔⛔ THE HONEST HEADLINE, STATED BEFORE ANY COVERAGE NUMBER: **98.41% OF THIS LANE IS CARRIED
VERBATIM.** The 0x55 audio payload is 99.9851% of the bytes; modelling the PCM part pulls the
carried share down only to 98.41%, because PCM is 555 of 224,378 data chunks. A writer that
carries the rest posts a flawless 100% that means almost nothing on its own - this vault's law is
that a lane at 100% with a large carried region has not been measured, it has been COPIED. What
the 100% DOES establish is that the CONTAINER is fully rebuilt: every structural byte is
re-encoded from decoded values and the must-fail control fires on all 12 model corruptions. Quote
the two together or neither. So:
  * codec 0x00 payload is **signed 16-bit PCM** - measured at EXACTLY 16.000 bits/sample over 359
    streams - and this writer DECODES IT TO INTEGER SAMPLES AND RE-ENCODES THEM. Those bytes are
    VALUE, not carry.
  * codec 0x04 payload is 4-bit block ADPCM (4.009 bits/sample over 383 streams). Its CONTENT IS
    NOT MODELLED and is counted as CARRIED. It is not dressed up as anything else.
    ⭐ SPACE SEARCHED, so the next agent does not repeat it: D = ceil(S/SPB)*B was fitted over
    383 (samples, data-size) pairs for B in {256,512,1024,2048,4096,8192} x SPB in
    {2B-16, 2B-14, 2B-12, 2B-8, 2B, B, B/2} - best fit 1.83%. Data sizes are a multiple of 4 on
    383/383 and nothing wider.
    ⭐ THE LIVE LEAD, WITH ITS DENOMINATOR: the 0x48 header's first two u32 look like
    (blockCount, blockSize) - `u32[0] * u32[1] == data chunk size` holds on **404 / 465 (86.88%)**
    and `u32[0]` divides the first data chunk on 458/465 (98.49%). NOT ADOPTED: a rule that fails
    13% of its own lane is not law, and encoding it would be exactly the kind of self-fulfilling
    claim this file exists to avoid. Pinning it would let the payload be walked per-BLOCK (which
    makes a wrong stride rejectable) but would NOT move bytes from CARRIED to VALUE - the nibbles
    themselves still need the codec.
    ⭐ NOT SEARCHED: variable block sizes, seek-table-driven (0xA3) block boundaries, and
    channel-interleave layouts where one stream spans several data chunks.
  * `regions()` returns the VALUE / DERIVED / ZERO / CARRIED split and `roundtrip_coverage`
    prints it. Quote it WITH the coverage figure, never instead of it.

LAYOUT - DERIVED FROM THE BYTES, NOT GUESSED. `awc2xml.parse` carried two guesses that nothing in
it could reject: it detected the per-stream table by "numStreams > 1 and first_u16 < 256", and it
split chunks across streams UNIFORMLY (`len(chunks) // numStreams`). Both are wrong. On a 10-stream
file holding 26 chunks (10 data + 10 format + 6 peak) the uniform split assigns 2 per stream and
SILENTLY DROPS SIX; and scored over 1,039 real files the two hand-written header hypotheses tiled
only 41.10% and 12.32% of the lane.
⭐ So the header width was SOLVED rather than guessed, against a constraint the file cannot lie
about - the chunk table must end exactly at `dataStart` and its (offset,size) pairs must tile
[dataStart, filesize). Scanning every 8-aligned candidate returned a UNIQUE width for every file
that solved and ZERO ambiguous ones, and the answer is a function of the flags word:

    per-stream header width = 4 + 2 * (flags & 1)      <- bit 0 = "u16 table present"

    +0x00 u32 magic 'ADAT'   +0x04 u16 version   +0x06 u16 flags
    +0x08 u32 streamCount    +0x0C u32 dataStart
    per-stream table  : [u16 chunkStartIndex x numStreams] (ONLY if flags&1)
                        followed by [u32 nameHash x numStreams]
                        - TWO SEPARATE ARRAYS, not interleaved records. Both readings span the
                          same bytes so the ROUND-TRIP CANNOT SEPARATE THEM; decided instead by
                          the monotonic chunk-start property, VALID 487/487 vs 4/487.
    chunk index table : one u64 per chunk until dataStart
                        offset = bits 0..27 | size = bits 28..55 | type = bits 56..63
    chunk bodies      : tile [dataStart, filesize), 16-B-aligned, gaps ZERO-FILLED

Measured on 739 plaintext files: the width rule gives an 8-aligned table ending exactly at
dataStart on 739/739, spans are ordered and non-overlapping on 739/739, no zero-size chunk exists,
the trailing gap is 0 on 739/739, and every inter-chunk gap is zero bytes (3,942 B in total).

⭐ THE HEADER IS NOT CARRIED. `ynd_write` and `yvr_write` both carry their first 0x20-0x70 bytes
verbatim because those hold tagged POINTERS whose re-encoding is a layout-allocator problem. The
AWC header holds no pointers - five plain scalars - so every one of its 16 bytes is re-encoded
from a decoded value here, and `dataStart` and `streamCount` are COMPUTED from the model rather
than copied (see write()). That is the `meta_write`/`ynd_write` page-count law applied to the one
field this format has that can carry it: a wrong chunk count moves `dataStart` and the round-trip
REJECTS it.

⚠ SCOPE / COUNTED REFUSALS. This module addresses the PLAINTEXT 'ADAT' class only. A .awc whose
first four bytes are not 'ADAT' raises `AwcEncrypted`, and the lane's gate in
`tools/roundtrip_coverage.py` turns those away and PRINTS the count - they are a different
(encrypted) form with no writer here, and blending "different format" with "writer failed" is how
a lane gets credit it has not earned.
ASCII output only.
"""
import os
import struct
import sys as _sys

_sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    import numpy as _np
except Exception:                                  # pragma: no cover
    _np = None

MAGIC = b'ADAT'
HEADER = 16

# chunk type tags, as (joaat(name) & 0xFF). Only the ones this writer models structurally are
# named; the rest are carried and COUNTED, never quietly renamed into something known.
T_PEAK, T_DATA, T_FORMAT = 0x36, 0x55, 0xFA
T_A3, T_48, T_BD, T_5C = 0xA3, 0x48, 0xBD, 0x5C

CODEC_PCM16 = 0x00          # measured EXACTLY 16.000 bits/sample over 359 streams
CODEC_ADPCM = 0x04          # measured 4.009 bits/sample over 383 streams - content NOT modelled

# ⭐⭐ THERE ARE TWO FILE SHAPES AND THEY ARE MUTUALLY EXCLUSIVE (measured over 739 plaintext
# files: 209 carry a 0xFA format chunk and no 0x48; 530 carry a 0x48 and no 0xFA). A writer that
# only knew the 0xFA shape would silently carry the entire payload of the OTHER 530 - 95% of the
# sample's bytes - while reporting a clean 100%. That is the exact "copied, not measured" failure
# this lane is most exposed to, so the second shape is modelled explicitly.
#
# The 0x48 chunk is a stream-format table: a 12-byte header whose third u32 is a RECORD COUNT,
# then that many 16-byte per-channel records. THE CHECK THAT COULD HAVE REFUSED IT: size must
# equal 12 + 16*count. Measured 530/530 exact. Every record in the census declared codec 0x04 and
# rate 48000, so the payload behind this shape is ADPCM - which is WHY it is carried, established
# rather than assumed.
C48_HEAD = (
    (0x00, '<I'),      # unk0 (small int, 1..9 in census)
    (0x04, '<I'),      # unk1 (0x00080000 / 0x0004B000 / 0x006E4000)
    (0x08, '<I'),      # record count
)
C48_REC = (
    (0x00, '<I'),      # name hash
    (0x04, '<I'),      # samples
    (0x08, '<h'),      # headroom
    (0x0A, '<H'),      # sample rate (48000 on 1,195/1,195)
    (0x0C, '<I'),      # codec (0x04 on 1,195/1,195)
)


class AwcEncrypted(Exception):
    """Raised for a .awc with no 'ADAT' magic. NOT a writer failure - a different form."""


# ⭐ THE FORMAT-CHUNK FIELD MAP. Two body sizes exist in the game: 24 B (2,318 of 2,337) and
# 20 B (19). Field offsets are read off a per-byte-position value census over those 2,337 bodies,
# not off the old docstring: +0x03 is 00 on 2,337/2,337, +0x04..+0x07 are FF on 2,337/2,337
# (LoopPoint = -1 throughout), +0x0C..+0x12 are 00 on 2,337/2,337, and +0x16..+0x17 are 00 on
# 2,318/2,318 of the 24-B bodies.
FORMAT_FIELDS_24 = (
    (0x00, '<I'),      # Samples
    (0x04, '<i'),      # LoopPoint (-1 throughout the census)
    (0x08, '<H'),      # SampleRate
    (0x0A, '<h'),      # Headroom
    (0x0C, '<H'),      # PlayBegin
    (0x0E, '<H'),      # PlayEnd
    (0x10, '<H'),      # LoopBegin
    (0x12, '<B'),      # unk12  (00 on 2,337/2,337 - named as unknown, never dropped)
    (0x13, '<B'),      # Codec
    (0x14, '<H'),      # PeakUnk
    (0x16, '<H'),      # unk16
)
FORMAT_FIELDS_20 = FORMAT_FIELDS_24[:9]


def _check_tiling(fields, stride, what):
    """⛔ AN UNTILED FIELD MAP IS A SILENT CARRY. Run at import so the claim "every byte of this
    record is modelled" is refuted HERE rather than showing up later as mystery coverage.
    Copied deliberately from `yvr_write`, where it is what makes byte identity prove the field
    map is COMPLETE rather than merely consistent."""
    at = 0
    for off, code in fields:
        if off != at:
            raise ValueError('%s field map: hole/overlap at 0x%02x (expected 0x%02x)'
                             % (what, off, at))
        at += struct.calcsize(code)
    if at != stride:
        raise ValueError('%s field map covers %d of %d stride bytes' % (what, at, stride))


_check_tiling(FORMAT_FIELDS_24, 24, 'awc format24')
_check_tiling(FORMAT_FIELDS_20, 20, 'awc format20')
_check_tiling(C48_HEAD, 12, 'awc c48 header')
_check_tiling(C48_REC, 16, 'awc c48 record')

# Fixed-width table chunks: the element width is DECLARED here rather than picked by "whatever
# divides the size", so a body that does not divide by it is CARRIED AND COUNTED instead of being
# silently re-cut to a width that happens to fit. 0x36 is a peak/amplitude table (u16), 0xA3 a
# seek table (u32, constant stride in the census), 0xBD a 16-byte record, 0x5C unknown but
# 4-divisible throughout.
TABLE_UNIT = {T_PEAK: '<H', T_A3: '<I', T_BD: '<I', T_5C: '<I'}


class Awc:
    """Value model of one plaintext AWC.

    MODEL, NOT MEMCPY. Every structural byte is decoded to a value and re-encoded into a
    ZERO-FILLED image, so anything the model never reaches stays zero and shows up as a
    difference. **The gaps are the finding.**
    """

    def __init__(self, blob):
        blob = bytes(blob) if not isinstance(blob, (bytes, bytearray)) else blob
        if blob[:4] != MAGIC:
            raise AwcEncrypted('no ADAT magic (encrypted or non-AWC container)')
        self.size = len(blob)
        self.src = blob
        self.version, self.flags = struct.unpack_from('<HH', blob, 4)
        n_streams, data_start = struct.unpack_from('<II', blob, 8)
        self.data_start = data_start
        # ⭐ THE WIDTH IS THE DERIVED PART OF THE HEADER, and it is a claim that can FAIL:
        # if bit 0 of the flags did not mean "u16 table present", the chunk table would not be
        # 8-aligned against dataStart and this refuses rather than sliding to a fallback.
        self.width = 4 + 2 * (self.flags & 1)
        tbl = HEADER + n_streams * self.width
        if tbl > data_start or (data_start - tbl) % 8:
            raise ValueError(
                'awc header width %d B/stream puts the chunk table at %d, which is not an '
                '8-aligned run ending at dataStart %d - the flags-bit-0 rule does not hold on '
                'this file' % (self.width, tbl, data_start))
        # ⭐⭐ TWO SEPARATE ARRAYS, **NOT** INTERLEAVED {u16,u32} RECORDS - and the round-trip
        # CANNOT TELL THE DIFFERENCE, because both readings cover the identical n*width byte span
        # and write it back identically. This is the harness's own "proves COMPLETENESS, not
        # INTERPRETATION" caveat in its purest form: the first version of this writer used the
        # interleaved reading, round-tripped 5,642/5,642, and was structurally WRONG.
        # Decided by a property only the correct reading satisfies - under the separate-array
        # layout the u16 block is a per-stream CHUNK-START INDEX, so it must begin at 0, be
        # non-decreasing, and end no later than the chunk count:
        #     separate arrays [u16 x n][u32 x n] : VALID on 487 / 487 width-6 files
        #     interleaved     {u16, u32} x n     : valid on   4 / 487 (tiny files, by coincidence)
        # ⚠ It is decoded and re-encoded, not refused on: the monotonic property is an
        # INTERPRETATION, and refusing a file whose bytes we can rebuild would shrink the measure
        # over a naming question.
        self.stream_u16 = []
        self.stream_hash = []
        hash_base = HEADER + (2 * n_streams if self.width == 6 else 0)
        if self.width == 6:
            for i in range(n_streams):
                self.stream_u16.append(struct.unpack_from('<H', blob, HEADER + 2 * i)[0])
        for i in range(n_streams):
            self.stream_hash.append(struct.unpack_from('<I', blob, hash_base + 4 * i)[0])
        # chunk index table - per-RECORD, and decoded to the three packed fields so that a wrong
        # bit split cannot survive: it is re-encoded from (type,size,offset), not copied.
        self.chunks = []
        o = tbl
        while o + 8 <= data_start:
            v = struct.unpack_from('<Q', blob, o)[0]
            self.chunks.append({'type': (v >> 56) & 0xFF,
                                'size': (v >> 28) & 0x0FFFFFFF,
                                'offset': v & 0x0FFFFFFF})
            o += 8
        self._check_tile()
        self._decode_bodies()

    # ---------------------------------------------------------------- structural checks
    def _check_tile(self):
        """⛔ THE CHUNK TABLE MUST TILE THE FILE. This is the check that makes the carried audio
        payload a PINNED region instead of a self-fulfilling one: a wrong offset or size cannot
        pass it, because the spans have to meet end-to-end across [dataStart, filesize) with
        every gap zero-filled. Measured 739/739 on the plaintext lane."""
        spans = sorted((c['offset'], c['size']) for c in self.chunks)
        at = self.data_start
        self.pad_bytes = 0
        for off, size in spans:
            if size == 0 or off < self.data_start or off + size > self.size:
                raise ValueError('awc chunk (off=%d size=%d) does not lie inside the data region '
                                 '[%d, %d)' % (off, size, self.data_start, self.size))
            if off < at:
                raise ValueError('awc chunk spans OVERLAP at offset %d' % off)
            if off > at:
                gap = self.src[at:off]
                if any(gap):
                    # NO SILENT CARRY: a non-zero gap is data the model is not reaching, and it
                    # must be loud rather than absorbed.
                    raise ValueError('awc inter-chunk gap at %d carries %d NON-ZERO bytes - the '
                                     'model does not account for them' % (at, len(gap)))
                self.pad_bytes += off - at
            at = off + size
        if at != self.size:
            raise ValueError('awc chunks end at %d but the file is %d B - the table does not '
                             'tile the file' % (at, self.size))

    # ---------------------------------------------------------------- body decode
    def _decode_bodies(self):
        """Decode each chunk body to values where the structure is pinned; CARRY and COUNT the
        rest. Every carried byte is counted in `self.carried` and disclosed by `regions()`."""
        b = self.src
        self.value_bytes = 0
        self.carried = 0
        self.carry_by_type = {}
        # format chunks first - the codec they declare is what decides whether the paired data
        # chunk is modellable at all.
        fmts = [c for c in self.chunks if c['type'] == T_FORMAT]
        datas = [c for c in self.chunks if c['type'] == T_DATA]
        c48s = [c for c in self.chunks if c['type'] == T_48]
        for c in self.chunks:
            t, off, size = c['type'], c['offset'], c['size']
            body = b[off:off + size]
            if t == T_FORMAT and size in (20, 24):
                fields = FORMAT_FIELDS_24 if size == 24 else FORMAT_FIELDS_20
                c['fields'] = fields
                c['vals'] = [struct.unpack_from(code, body, fo) for fo, code in fields]
                c['kind'] = 'value'
                self.value_bytes += size
                continue
            if t == T_48 and size >= 12:
                n_rec = struct.unpack_from('<I', body, 8)[0]
                # ⛔ THE SIZE CHECK IS WHAT MAKES THE RECORD LAYOUT EVIDENCE. A count that does
                # not predict the body length refutes it, and the chunk is carried and COUNTED
                # rather than being cut to a stride that merely fits. 530/530 exact in census.
                if size == 12 + 16 * n_rec:
                    c['c48'] = ([struct.unpack_from(code, body, fo) for fo, code in C48_HEAD],
                                [[struct.unpack_from(code, body, 12 + 16 * k + fo)
                                  for fo, code in C48_REC] for k in range(n_rec)])
                    c['kind'] = 'value'
                    self.value_bytes += size
                    continue
            if t in TABLE_UNIT:
                # Fixed-width tables, walked per-ELEMENT rather than as a slab so a wrong stride
                # surfaces as a difference. The unit is DECLARED (see TABLE_UNIT), not chosen by
                # what happens to divide - a body that does not divide is carried and counted.
                code = TABLE_UNIT[t]
                w = struct.calcsize(code)
                if size % w == 0:
                    c['unit'] = code
                    c['vals'] = [struct.unpack_from(code, body, i * w)[0]
                                 for i in range(size // w)]
                    c['kind'] = 'value'
                    self.value_bytes += size
                    continue
            if t == T_DATA:
                codec = self._codec_for(c, fmts, datas, c48s)
                if codec == CODEC_PCM16 and size % 2 == 0 and _np is not None:
                    # ⭐ REAL VALUE MODELLING, NOT A REINTERPRET. The payload is decoded to
                    # 16-bit integer SAMPLES, WIDENED to int32 (so the decode is an actual
                    # conversion through a value domain and not a pointer cast), and narrowed
                    # back on write. A wrong element width, a wrong count or the wrong byte
                    # order fails immediately.
                    c['pcm'] = _np.frombuffer(body, dtype='<i2').astype(_np.int32)
                    c['kind'] = 'value'
                    self.value_bytes += size
                    continue
                c['kind'] = 'carry'
                c['raw'] = body
                self.carried += size
                self.carry_by_type[t] = self.carry_by_type.get(t, 0) + size
                continue
            c['kind'] = 'carry'
            c['raw'] = body
            self.carried += size
            self.carry_by_type[t] = self.carry_by_type.get(t, 0) + size

    def _codec_for(self, chunk, fmts, datas, c48s):
        """The codec declared for this data chunk, on EITHER file shape.

        Shape 1 pairs the i-th data chunk with the i-th 0xFA format chunk and reads its codec
        byte. That pairing is not taken on faith: pairing this way and dividing data bytes by
        declared samples returns EXACTLY 16.000 bits/sample for codec 0x00 (359 streams) and a
        tight 4.009 for codec 0x04 (383 streams). A wrong pairing would smear both figures.

        Shape 2 has NO format chunk (530 of 739 files) and declares the codec in the 0x48 stream
        table instead, one 16-byte record per channel. Without this branch the entire payload of
        the majority shape would be carried while the lane still printed 100%.

        ⛔ NO SILENT DEFAULT ANYWHERE: every path that cannot establish a codec returns None, and
        the caller then CARRIES AND COUNTS the payload rather than guessing it into the PCM path.
        """
        try:
            i = datas.index(chunk)
        except ValueError:
            return None
        if fmts and len(fmts) == len(datas):
            f = fmts[i]
            body = self.src[f['offset']:f['offset'] + f['size']]
            return body[0x13] if len(body) > 0x13 else None
        if len(c48s) == 1 and 'c48' in c48s[0]:
            recs = c48s[0]['c48'][1]
            if len(recs) == len(datas):
                return recs[i][4][0]          # the codec u32 of this channel's record
        return None

    # ---------------------------------------------------------------- write
    def write(self):
        img = bytearray(self.size)

        # ⭐ streamCount and dataStart are COMPUTED FROM THE MODEL, never carried. This is the
        # same law `meta_write` derived for the META formats ("250/250 exact, COMPUTED, not
        # carried") and `ynd_write` re-confirmed on 259/259 .ynd, applied to the one field this
        # format has that can carry it. A miscounted chunk table moves dataStart and the
        # round-trip REJECTS the file instead of quietly agreeing with itself.
        n_streams = len(self.stream_hash)
        data_start = HEADER + n_streams * self.width + 8 * len(self.chunks)
        struct.pack_into('<4sHHII', img, 0, MAGIC, self.version, self.flags,
                         n_streams, data_start)

        # Separate arrays, matching the parse - see the note there for why the round-trip alone
        # could not have told this apart from an interleaved reading.
        hash_base = HEADER + (2 * n_streams if self.width == 6 else 0)
        if self.width == 6:
            for i in range(n_streams):
                struct.pack_into('<H', img, HEADER + 2 * i, self.stream_u16[i])
        for i in range(n_streams):
            struct.pack_into('<I', img, hash_base + 4 * i, self.stream_hash[i])

        o = HEADER + n_streams * self.width
        for c in self.chunks:
            v = ((c['type'] & 0xFF) << 56) | ((c['size'] & 0x0FFFFFFF) << 28) \
                | (c['offset'] & 0x0FFFFFFF)
            struct.pack_into('<Q', img, o, v)
            o += 8

        for c in self.chunks:
            off, size = c['offset'], c['size']
            if c['kind'] == 'carry':
                img[off:off + size] = c['raw']
            elif 'pcm' in c:
                img[off:off + size] = c['pcm'].astype('<i2').tobytes()
            elif 'fields' in c:
                for (fo, code), vals in zip(c['fields'], c['vals']):
                    struct.pack_into(code, img, off + fo, *vals)
            elif 'c48' in c:
                head, recs = c['c48']
                for (fo, code), vals in zip(C48_HEAD, head):
                    struct.pack_into(code, img, off + fo, *vals)
                for k, rec in enumerate(recs):
                    for (fo, code), vals in zip(C48_REC, rec):
                        struct.pack_into(code, img, off + 12 + 16 * k + fo, *vals)
            elif 'unit' in c:
                w = struct.calcsize(c['unit'])
                for i, v in enumerate(c['vals']):
                    struct.pack_into(c['unit'], img, off + i * w, v)
        # Inter-chunk gaps are left ZERO on purpose - measured zero on 739/739 files. An
        # unreproduced byte must stay VISIBLE rather than be carried.
        return bytes(img)

    # ---------------------------------------------------------------- measures
    def unreached(self):
        """(count, non_zero_count) of bytes the model never reproduced.

        A ZERO gap is padding we did not have to understand. A NON-ZERO gap is data we are
        dropping - which is exactly what this exercise exists to surface.

        ⚠ VECTORISED ON PURPOSE, and it is not a micro-optimisation. The sibling writers compare
        with a Python-level `[i for i in range(n) if got[i] != orig[i]]`, which costs one
        interpreted iteration PER BYTE. Their segments are kilobytes; this lane is 42.54 GB, so
        the same loop would be ~42 billion iterations and the population run would never finish.
        The equality fast-path settles the overwhelmingly common case in C, and the numpy branch
        only runs on a file that actually differs - where the per-byte detail is worth paying for.
        """
        got, orig = self.write(), self.src
        if got == orig:
            return (0, 0)
        n = min(len(got), len(orig))
        if _np is not None:
            a = _np.frombuffer(got[:n], dtype=_np.uint8)
            b = _np.frombuffer(bytes(orig[:n]), dtype=_np.uint8)
            d = a != b
            return int(d.sum()), int((d & (b != 0)).sum())
        bad = [i for i in range(n) if got[i] != orig[i]]
        return len(bad), sum(1 for i in bad if orig[i] != 0)

    def regions(self):
        """(value, derived, zero_fill, carried) byte split of the file.

        ⭐ DISCLOSURE, NOT DECORATION. Byte identity alone cannot tell a rebuilt region from a
        copied one, and this vault's law is that a claimed region is evidence ONLY IF A WRONG
        CLAIM COULD HAVE BEEN REJECTED. `carried` is the part of a passing file that could not
        have failed on its own content; quote it next to the coverage figure, never instead.
        ⚠ For this lane `carried` is dominated by ADPCM audio, and it is the MAJORITY OF THE
        LANE. Say so out loud.
        """
        derived = 8                      # streamCount + dataStart, computed from the model
        header_value = HEADER - derived  # magic + version + flags
        tables = len(self.stream_hash) * self.width + 8 * len(self.chunks)
        value = header_value + tables + self.value_bytes
        return (value, derived, self.pad_bytes, self.carried)


def read_awc(src):
    """LANES entry point. Takes the raw file bytes (a .awc is a BINARY entry, not an RSC7
    resource, so there is no container to inflate and no segment to split)."""
    blob = bytes(src) if isinstance(src, (bytes, bytearray, memoryview)) else open(src, 'rb').read()
    return Awc(blob)
