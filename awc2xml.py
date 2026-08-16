"""awc2xml - GTA V .awc (AudioWaveContainer) -> RAGE interchange .awc.xml

CLEAN-ROOM: derived ONLY from the 5 the reference exporter oracle XMLs, the game binaries (5 encrypted
dummy.awc + real plaintext awcs extracted from mp2023_01/dlc.rpf), and QUARRY's own code
(meta2xml.esc/joaat, keyderive.derive, ngcrypto). No the reference exporter source, no web research.

WHAT IS GROUNDED (measured on the real PLAINTEXT awcs mask_sfx.awc [5 streams] and
mp231_nh_halloween.awc [17 streams], both magic 'ADAT'):

  HEADER (16 B, little-endian)
    +0x00 u32  magic          = 0x54414441 'ADAT'      (encrypted files: header is ciphertext)
    +0x04 u16  version        = 1
    +0x06 u16  flags          = 0xFF0A / 0xFF0D observed (top byte 0xFF; low byte varies)
    +0x08 u32  streamCount
    +0x0C u32  dataChunkStart = absolute file offset where chunk DATA begins
                               = end of the chunk-index table (16 + tables ... == this value)
  STREAM NAME HASH TABLE : streamCount x u32 joaat(name) hashes, right after the header
    (variant B, seen on halloween: a streamCount x u16 "chunk count" table precedes the hashes)
  CHUNK-INDEX TABLE : one u64 per chunk, grouped per stream, running until dataChunkStart:
    offset = bits  0..27  (28) absolute file offset of this chunk's data
    size   = bits 28..55  (28) byte length of this chunk's data
    type   = bits 56..63  (8)  == (joaat(typeName) & 0xFF):  peak=0x36 data=0x55 format=0xFA
  Chunks are laid out in the file in the order data, format, peak; the reference exporter EMITS them
  sorted ASCENDING by type tag -> peak(0x36), data(0x55), format(0xFA).
  FORMAT CHUNK (24 B), pointed at by the 0xFA chunk:
    +0x00 u32  Samples        (validated: data-chunk bytes ~= Samples/2 for ADPCM)
    +0x04 i32  LoopPoint      (-1)
    +0x08 u16  SampleRate
    +0x0A i16  Headroom
    +0x0C u16  PlayBegin      (0)   +0x0E u16 PlayEnd (0)
    +0x10 u16  LoopBegin      (0)   +0x12 u16 LoopEnd (0)   [play/loop always 0 in evidence]
    +0x13 u8   Codec          (0x04 == ADPCM in all evidence)
    +0x14 u16  Peak-unk       (per-stream; 0 in the dummies)   +0x16 u16 = 0

⛔ BLOCKER (the 5 oracle dummies): all are WholeFileEncrypt=True. The whole file, header
included, is encrypted with a cipher NONE of QUARRY's key material inverts - proven with a
TWO-BLOCK KNOWN-PLAINTEXT test (blocks 1 and 98 of 069 reconstructed exactly from the format
layout + oracle values): no ECB/CBC/CTR/OFB/CFB under {NG x101, AES-256 tfit, AES-128 'awc'
magic-blob key} maps ciphertext<->plaintext. The nonce/mode is a RAGE-internal detail the
clean-room rule forbids sourcing. So this module CONVERTS PLAINTEXT ('ADAT') awcs and REFUSES
encrypted ones loudly. Deriving XML for the 5 oracles awaits the WholeFileEncrypt decryptor.

================================================================================================
⭐⭐ 2026-08-16 - THE INTERCHANGE PATH (`to_interchange`) IS A SECOND, MODEL-BASED EMITTER.
================================================================================================
WHY IT EXISTS. `parse`/`emit` below are a PRIVATE re-parse of the file, weaker than the value
model in `awc_write.Awc`, and the difference was not cosmetic. Measured 2026-08-16 over a walked
sample of 6,000 game `.awc` (2,566 `0x48` shape / 1,861 `0xFA` shape / 1,573 encrypted), on a
120-file sample of each shape:

    0x48 shape (THE MAJORITY) : emit() produces XML = 0.0380% of the source bytes, and every
                                0x48 / 0x55 / 0xA3 chunk lands as a bare <Type>unk_48</Type>
                                WITH NO FIELDS AT ALL.
    0xFA shape                : XML = 1.0370% of source bytes; data and peak chunks fieldless.
    both shapes               : every stream emits <FileName>0x........wav</FileName> naming a
                                sidecar THAT NOTHING WRITES.

⇒ Wiring `emit()` into `quarry.py` would have registered the lane while shipping an empty one.
So the wired path emits from `awc_write.Awc` - the model that the population round-trip actually
exercised (5,642/5,642 byte-exact) - and carries the payload in real sidecars.

⛔ THE TWO MEASURES ARE DIFFERENT AND THE SECOND DOES NOT INHERIT THE FIRST.
  * `awc_write`'s round-trip proves the BINARY MODEL is complete:  blob -> Awc -> blob.
  * THIS module's round-trip proves the EXPORT IS LOSSLESS:        blob -> XML+sidecars -> blob.
A file can pass the first and fail the second - that is exactly the state this lane was in.
`tools/awc_xml_roundtrip.py` measures the second, with its own must-fail control.

⭐ OFFSETS ARE COMPUTED, NOT WRITTEN. `dataStart` and `streamCount` follow `awc_write`'s law, and
each chunk's file offset is rebuilt by walking <Layout> from dataStart adding the recorded
zero-fill pads. So a WRONG <Size> or a wrong layout order MOVES every later chunk and the
round-trip REJECTS it, instead of agreeing with a stored number.

⚠ THIS XML IS NOT ORACLE-DERIVED, AND CANNOT BE. Every `.awc` oracle in `_Oracles/awc/` is
WholeFileEncrypt, so no reference spelling of these elements exists for the plaintext class. The
element names here are OURS. If reference parity is ever reinstated as a cross-check, this whole
schema is the first thing to re-verify - do not read it as witnessed.
"""
import argparse
import os
import struct

from meta2xml import joaat, esc

MAGIC = b'ADAT'
TAG = {joaat(n) & 0xFF: n for n in ('data', 'format', 'peak', 'name', 'seek', 'loop', 'markers')}
# ⭐ CODEC 0x00 ADDED 2026-08-15. The old map held ADPCM only, so every PCM stream raised
# "unknown codec byte 0x00" - 30 of 739 files in a walk sample died on it. The identification is
# MEASURED, not guessed: pairing each data chunk with its format chunk and dividing data bytes by
# declared samples gives EXACTLY 16.000 bits/sample over 359 streams (ADPCM gives 4.009), and the
# payload head decodes as a smooth int16 waveform (2, 12, 22, 29, 42, 49, 55, 62, ...).
# ⚠ THE STRING 'PCM16' IS OUR LABEL, NOT AN ORACLE-WITNESSED ONE. Every oracle for this lane is
# encrypted, so no reference spelling of this element exists to copy. If reference-parity is ever
# reinstated as a cross-check, this name is the first thing to re-verify.
CODEC = {0x00: 'PCM16', 0x04: 'ADPCM'}
# minimal name dictionary; the reference exporter resolves joaat hashes it knows, else emits hash_XXXXXXXX
KNOWN_NAMES = {joaat(n): n for n in ('dummy',)}


class AwcEncrypted(Exception):
    pass


def parse(plain, was_encrypted=False):
    """⛔ SUPERSEDED 2026-08-16 FOR THE EXPORT PATH - kept, not deleted.

    `to_interchange` (the wired path) emits from `awc_write.Awc` instead; see the module
    docstring for the measurement that forced it. This function and `emit` remain because
    `scratchpad/awc_probe25.py` calls them directly and because they are the provenance of the
    width rule derived below. ⛔ DO NOT wire these into `quarry.py`.

    ⛔⛔ REWRITTEN 2026-08-15 - THE TWO ORIGINAL RULES HERE WERE BOTH WRONG AT SCALE, AND BOTH
    FAILED SILENTLY. Measured over 1,039 real plaintext .awc drawn from the game:

      (1) TABLE DETECTION was `numStreams > 1 and first_u16 < 256` - a heuristic nothing in this
          module could reject. The real discriminator is BIT 0 OF THE FLAGS WORD, solved against
          a constraint the file cannot lie about (the u64 chunk table must end EXACTLY at
          dataStart and its spans must tile [dataStart, filesize)):
              per-stream header width = 4 + 2 * (flags & 1)
          Scanning every 8-aligned candidate width returned a UNIQUE answer per file and ZERO
          ambiguous ones; the rule then held on 739 / 739. The two hand-written hypotheses this
          replaced tiled only 41.10% and 12.32% of the lane.

      (2) CHUNK DISTRIBUTION was `per = len(chunks) // numStreams`, a uniform split. It DROPS
          CHUNKS: a 10-stream file carrying 26 chunks (10 data + 10 format + 6 peak) gets
          per = 2 and SIX CHUNKS VANISH from the XML with no error. Real grouping comes from the
          u16 array, which is a per-stream CHUNK-START INDEX (monotonic from 0, valid 487/487).

      (3) The per-stream table is TWO SEPARATE ARRAYS - [u16 x n] then [u32 hash x n] - not
          interleaved {u16,u32} records. Both span the same bytes, so this is invisible to a
          round-trip; decided on the monotonic property (487/487 vs 4/487).

    ⛔ NO CHUNK IS EVER DROPPED NOW. Files with no u16 table (flags bit 0 clear) have no stated
    grouping, so they fall back to a uniform split ONLY when it divides exactly; otherwise every
    chunk is attached to the first stream and the file is FLAGGED in `parsed['ungrouped']` rather
    than being quietly truncated. Measured: 18 of 452 no-table files do not divide evenly.
    """
    if plain[:4] != MAGIC:
        raise AwcEncrypted('not an ADAT plaintext AWC (encrypted header?)')
    version = struct.unpack_from('<H', plain, 4)[0]
    flags = struct.unpack_from('<H', plain, 6)[0]
    numStreams = struct.unpack_from('<I', plain, 8)[0]
    dataStart = struct.unpack_from('<I', plain, 12)[0]
    width = 4 + 2 * (flags & 1)
    tbl = 16 + numStreams * width
    if tbl > dataStart or (dataStart - tbl) % 8:
        raise ValueError('awc header width %d B/stream puts the chunk table at %d, not an '
                         '8-aligned run ending at dataStart %d' % (width, tbl, dataStart))
    starts = ([struct.unpack_from('<H', plain, 16 + 2 * i)[0] for i in range(numStreams)]
              if width == 6 else None)
    hbase = 16 + (2 * numStreams if width == 6 else 0)
    hashes = [struct.unpack_from('<I', plain, hbase + 4 * i)[0] for i in range(numStreams)]
    all_chunks = []
    o = tbl
    while o + 8 <= dataStart:
        v = struct.unpack_from('<Q', plain, o)[0]
        all_chunks.append({'type': TAG.get((v >> 56) & 0xFF, 'unk_%02x' % ((v >> 56) & 0xFF)),
                           'size': (v >> 28) & 0x0FFFFFFF, 'offset': v & 0x0FFFFFFF})
        o += 8
    streams = []
    ungrouped = False
    if starts is not None and numStreams:
        bounds = list(starts) + [len(all_chunks)]
        for s in range(numStreams):
            a, b = bounds[s], bounds[s + 1]
            streams.append({'hash': hashes[s], 'chunks': all_chunks[a:b]})
    elif numStreams and len(all_chunks) % numStreams == 0:
        per = len(all_chunks) // numStreams
        for s in range(numStreams):
            streams.append({'hash': hashes[s], 'chunks': all_chunks[s * per:(s + 1) * per]})
    else:
        ungrouped = True
        for s in range(numStreams):
            streams.append({'hash': hashes[s], 'chunks': all_chunks if s == 0 else []})
    return {'version': version, 'flags': flags, 'was_encrypted': was_encrypted,
            'numStreams': numStreams, 'streams': streams, 'ungrouped': ungrouped,
            'chunkCount': len(all_chunks)}


def _fmt_fields(plain, chunk):
    b = plain[chunk['offset']:chunk['offset'] + chunk['size']]
    codec_b = b[0x13] if len(b) > 0x13 else 0x04
    # PlayBegin/PlayEnd/LoopBegin/LoopEnd are packed in bytes +0x0C..+0x12 and are 0 in ALL
    # evidence (5 mask streams + 5 dummy oracles). The exact bit packing is UNPINNED (no
    # non-zero sample), so they are emitted as 0 rather than guessed.
    # ⭐ THE 20-BYTE FORMAT CHUNK IS REAL. Bodies are 24 B on 2,318 of 2,337 and 20 B on 19, and
    # reading PeakUnk at +0x14 off a 20-byte body raised "unpack_from requires a buffer of at
    # least 22 bytes" - a hard crash on 1 file in a 900-file walk. Guarded rather than assumed
    # away, and the absence is reported as None instead of a fabricated 0.
    return {
        'Codec': CODEC.get(codec_b),
        'Samples': struct.unpack_from('<I', b, 0)[0],
        'LoopPoint': struct.unpack_from('<i', b, 4)[0],
        'SampleRate': struct.unpack_from('<H', b, 8)[0],
        'Headroom': struct.unpack_from('<h', b, 10)[0],
        'PlayBegin': 0, 'PlayEnd': 0, 'LoopBegin': 0, 'LoopEnd': 0,
        'PeakUnk': (struct.unpack_from('<H', b, 0x14)[0] if len(b) >= 0x16 else None),
        '_codec_byte': codec_b,
    }


def name_and_file(h):
    if h in KNOWN_NAMES:
        n = KNOWN_NAMES[h]
        return n, n + '.wav'
    return 'hash_%08X' % h, '0x%08X.wav' % h


def emit(parsed, plain):
    EOL = '\r\n'
    out = ['<?xml version="1.0" encoding="UTF-8"?>', '<AudioWaveContainer>']
    out.append(' <Version value="%d" />' % parsed['version'])
    out.append(' <ChunkIndices value="True" />')
    out.append(' <MultiChannelEncrypt value="%s" />' % ('True' if parsed['was_encrypted'] else 'False'))
    out.append(' <WholeFileEncrypt value="%s" />' % ('True' if parsed['was_encrypted'] else 'False'))
    out.append(' <Streams>')
    for st in parsed['streams']:
        name, fname = name_and_file(st['hash'])
        out.append('  <Item>')
        out.append('   <Name>%s</Name>' % esc(name))
        out.append('   <FileName>%s</FileName>' % esc(fname))
        out.append('   <Chunks>')
        # the reference exporter XML order = ascending type tag: peak(0x36) data(0x55) format(0xFA)
        order = {'peak': 0, 'data': 1, 'format': 2}
        for ck in sorted(st['chunks'], key=lambda c: order.get(c['type'], 99)):
            out.append('    <Item>')
            out.append('     <Type>%s</Type>' % ck['type'])
            if ck['type'] == 'format':
                f = _fmt_fields(plain, ck)
                if f['Codec'] is None:
                    raise ValueError('unknown codec byte 0x%02x' % f['_codec_byte'])
                out.append('     <Codec>%s</Codec>' % f['Codec'])
                out.append('     <Samples value="%d" />' % f['Samples'])
                out.append('     <SampleRate value="%d" />' % f['SampleRate'])
                out.append('     <Headroom value="%d" />' % f['Headroom'])
                out.append('     <PlayBegin value="%d" />' % f['PlayBegin'])
                out.append('     <PlayEnd value="%d" />' % f['PlayEnd'])
                out.append('     <LoopBegin value="%d" />' % f['LoopBegin'])
                out.append('     <LoopEnd value="%d" />' % f['LoopEnd'])
                out.append('     <LoopPoint value="%d" />' % f['LoopPoint'])
                if f['PeakUnk'] is not None:
                    out.append('     <Peak unk="%d" />' % f['PeakUnk'])
            out.append('    </Item>')
        out.append('   </Chunks>')
        out.append('  </Item>')
    out.append(' </Streams>')
    out.append('</AudioWaveContainer>')
    return EOL.join(out) + EOL


# =================================================================================================
# THE WIRED INTERCHANGE PATH - emits from awc_write.Awc. See the module docstring for why.
# =================================================================================================

WAV_HEADER = 44          # canonical RIFF/PCM header this module writes and strips back off

# Chunk tags named by awc_write's value model. A tag NOT in here is carried and COUNTED - it is
# never renamed into something known, and never silently dropped.
TAG_NAME = {0x36: 'peak', 0x48: 'streamtable', 0x55: 'data', 0xA3: 'seek',
            0xBD: 'table_bd', 0x5C: 'table_5c', 0xFA: 'format'}


def _wav_header(n_bytes, sample_rate, channels=1, bits=16):
    """A canonical 44-byte RIFF/PCM header.

    ⚠ CANONICAL ON PURPOSE: the rebuild strips exactly WAV_HEADER bytes back off, so this header
    must be fixed-size. A .wav that arrives with extra chunks (LIST/fact) is NOT accepted blindly
    on the way back in - `_wav_payload` locates 'data' properly and refuses what it cannot read.
    """
    if sample_rate is None or sample_rate <= 0:
        sample_rate = 48000                     # only reached when the file declares no rate;
        # the XML records rateKnown="False" so this substitution is never invisible.
    byte_rate = sample_rate * channels * bits // 8
    block_align = channels * bits // 8
    return (b'RIFF' + struct.pack('<I', 36 + n_bytes) + b'WAVE'
            + b'fmt ' + struct.pack('<IHHIIHH', 16, 1, channels, sample_rate,
                                    byte_rate, block_align, bits)
            + b'data' + struct.pack('<I', n_bytes))


def _wav_payload(blob):
    """The PCM bytes out of a .wav this module wrote (or any canonical one).

    ⛔ NOT `blob[44:]`. That is the assumption that silently corrupts a rebuild the day a tool
    writes a LIST chunk. The 'data' chunk is located by walking the RIFF chunk list, and anything
    unparseable RAISES rather than returning a plausible slice.
    """
    if blob[:4] != b'RIFF' or blob[8:12] != b'WAVE':
        raise ValueError('sidecar is not a RIFF/WAVE file')
    o = 12
    while o + 8 <= len(blob):
        cid = blob[o:o + 4]
        csz = struct.unpack_from('<I', blob, o + 4)[0]
        if cid == b'data':
            end = o + 8 + csz
            if end > len(blob):
                raise ValueError('wav data chunk declares %d B, file holds %d'
                                 % (csz, len(blob) - o - 8))
            return blob[o + 8:end]
        o += 8 + csz + (csz & 1)
    raise ValueError('no data chunk in wav sidecar')


def _stream_rate(model):
    """Declared sample rate per DATA chunk index, on either shape, or None where unstated.

    Mirrors `awc_write.Awc._codec_for` exactly - same pairing, same refusal to default. A rate is
    cosmetic for byte identity (the payload bytes are what rebuild) but wrong metadata makes an
    unusable .wav, so it is derived the same way rather than guessed.
    """
    datas = [c for c in model.chunks if c['type'] == 0x55]
    fmts = [c for c in model.chunks if c['type'] == 0xFA]
    c48s = [c for c in model.chunks if c['type'] == 0x48]
    rates = [None] * len(datas)
    if fmts and len(fmts) == len(datas):
        for i, f in enumerate(fmts):
            body = model.src[f['offset']:f['offset'] + f['size']]
            if len(body) >= 10:
                rates[i] = struct.unpack_from('<H', body, 8)[0]
    elif len(c48s) == 1 and 'c48' in c48s[0]:
        recs = c48s[0]['c48'][1]
        if len(recs) == len(datas):
            for i, r in enumerate(recs):
                rates[i] = r[3][0]
    return {id(c): rates[i] for i, c in enumerate(datas)}


def to_interchange(name, blob, audio='both'):
    """.awc -> (xml bytes, [(sidecar relpath, bytes)]) from the ROUND-TRIP-PROVEN value model.

    `audio` mirrors quarry's `textures` argument and means the same thing:
        'none'  manifest only - NO payload written. The XML says so per chunk
                (<Payload kind="none" bytes="N" />) so a lossy export is never mistaken for a
                complete one, and `stats` gets a counter.
        'wav'   PCM16 payload as importable mono .wav; non-PCM payload still needs raw, so it is
                written as .bin (dropping it would be a silent loss).
        'raw'   every payload chunk as raw .bin - the exact chunk bytes.
        'both'  PCM16 as .wav, everything else as .bin. THE DEFAULT and the only lossless-and-
                useful setting.

    ⭐ THE SIDECAR SET IS THE CARRIED-VERBATIM REGION MADE PHYSICAL. Everything this module can
    model lands in the XML as values; everything it cannot lands in a sidecar. So `sum(sidecar
    bytes) / len(blob)` IS this lane's carried share, per file, with no separate bookkeeping to
    drift out of date.
    """
    import awc_write
    model = awc_write.read_awc(blob)
    rate_of = _stream_rate(model)
    stem = os.path.splitext(os.path.basename(name))[0]

    EOL = '\r\n'
    out = ['<?xml version="1.0" encoding="UTF-8"?>', '<AudioWaveContainer>']
    out.append(' <Version value="%d" />' % model.version)
    # ⭐ FLAGS IS EMITTED. Bit 0 decides the per-stream table width, so a rebuild without it
    # cannot place the chunk table. `emit()` above never wrote it - that alone made its XML
    # non-invertible.
    out.append(' <Flags value="%d" />' % model.flags)
    out.append(' <ChunkIndices value="True" />')
    out.append(' <MultiChannelEncrypt value="False" />')
    out.append(' <WholeFileEncrypt value="False" />')

    out.append(' <Streams>')
    for i, h in enumerate(model.stream_hash):
        nm, _fn = name_and_file(h)
        out.append('  <Item>')
        out.append('   <Name>%s</Name>' % esc(nm))
        out.append('   <NameHash value="%d" />' % h)
        if model.width == 6:
            # per-stream CHUNK-START INDEX into <Chunks>; absent shapes state no grouping at all
            out.append('   <ChunkStart value="%d" />' % model.stream_u16[i])
        out.append('  </Item>')
    out.append(' </Streams>')

    sidecars = []
    n_none = 0
    out.append(' <Chunks>')
    for idx, c in enumerate(model.chunks):
        t = c['type']
        out.append('  <Item index="%d">' % idx)
        out.append('   <Type>%s</Type>' % TAG_NAME.get(t, 'unk_%02x' % t))
        out.append('   <TypeTag value="%d" />' % t)
        out.append('   <Size value="%d" />' % c['size'])
        if 'fields' in c:                                   # 0xFA format chunk, 20 B or 24 B
            names24 = ('Samples', 'LoopPoint', 'SampleRate', 'Headroom', 'PlayBegin', 'PlayEnd',
                       'LoopBegin', 'Unk12', 'Codec', 'PeakUnk', 'Unk16')
            for nm2, vals in zip(names24, c['vals']):
                out.append('   <%s value="%d" />' % (nm2, vals[0]))
            cb = [v for n2, v in zip(names24, c['vals']) if n2 == 'Codec']
            if cb:
                out.append('   <CodecName>%s</CodecName>'
                           % (CODEC.get(cb[0][0]) or 'unk_%02x' % cb[0][0]))
        elif 'c48' in c:                                    # 0x48 stream table
            head, recs = c['c48']
            out.append('   <StreamTable unk0="%d" unk1="%d">' % (head[0][0], head[1][0]))
            for r in recs:
                out.append('    <Item nameHash="%d" samples="%d" headroom="%d" '
                           'sampleRate="%d" codec="%d" />'
                           % (r[0][0], r[1][0], r[2][0], r[3][0], r[4][0]))
            out.append('   </StreamTable>')
        elif 'unit' in c:                                   # fixed-width table (peak/seek/...)
            out.append('   <Table unit="%s" count="%d">%s</Table>'
                       % (c['unit'], len(c['vals']), ' '.join(str(v) for v in c['vals'])))
        elif 'pcm' in c:                                    # PCM16 payload -> real .wav
            rate = rate_of.get(id(c))
            raw = c['pcm'].astype('<i2').tobytes()
            if audio == 'none':
                out.append('   <Payload kind="none" bytes="%d" />' % len(raw))
                n_none += 1
            elif audio == 'raw':
                fn = '%04d.bin' % idx
                sidecars.append(('%s/%s' % (stem, fn), raw))
                out.append('   <Payload kind="raw" file="%s" bytes="%d" />' % (fn, len(raw)))
            else:
                fn = '%04d.wav' % idx
                sidecars.append(('%s/%s' % (stem, fn),
                                 _wav_header(len(raw), rate) + raw))
                out.append('   <Payload kind="pcm16" file="%s" bytes="%d" sampleRate="%s" '
                           'rateKnown="%s" />'
                           % (fn, len(raw), rate if rate else 48000,
                              'True' if rate else 'False'))
        elif 'raw' in c:                                    # carried: ADPCM + unmodelled tags
            if audio == 'none':
                out.append('   <Payload kind="none" bytes="%d" />' % len(c['raw']))
                n_none += 1
            else:
                fn = '%04d.bin' % idx
                sidecars.append(('%s/%s' % (stem, fn), c['raw']))
                out.append('   <Payload kind="raw" file="%s" bytes="%d" />' % (fn, len(c['raw'])))
        out.append('  </Item>')
    out.append(' </Chunks>')

    # ⭐ LAYOUT: file order + the zero-fill pad before each chunk. Offsets are REBUILT from this,
    # never stored, so a wrong Size cannot pass (it moves every later chunk).
    order = sorted(range(len(model.chunks)), key=lambda i: model.chunks[i]['offset'])
    out.append(' <Layout>')
    at = model.data_start
    for i in order:
        c = model.chunks[i]
        out.append('  <Item chunk="%d" pad="%d" />' % (i, c['offset'] - at))
        at = c['offset'] + c['size']
    out.append(' </Layout>')
    out.append('</AudioWaveContainer>')

    xml = (EOL.join(out) + EOL).encode('utf-8')
    return xml, tuple(sidecars), n_none


def to_xml_bytes(name, blob):
    """Convert an in-memory .awc. THE ENTRY POINT `quarry.to_interchange_xml` NEEDS - the
    pipeline hands converters a name and a blob, never a path, which is part of why this module
    was never wired.

    ⭐ NOW ROUTES THROUGH `to_interchange` (the model-based emitter). Callers that want the
    payload must call `to_interchange` directly - this returns the XML only.

    Raises AwcEncrypted for the whole-file-encrypted class so the caller can record it as a
    COUNTED REFUSAL with a named reason rather than emitting a broken XML.
    """
    if blob[:4] == b'RSC7':
        raise ValueError('RSC7 resource, not a raw AWC')
    if blob[:4] != MAGIC:
        raise AwcEncrypted(
            '%s: whole-file encrypted (no ADAT magic). 2,100 of the game 7,742 .awc are in this '
            'class (27.12%%, 1.97 GB), measured 2026-08-15. No QUARRY key material inverts it: '
            'AES-128 both directions with the magic-blob awc key, the blob 256-byte LUT both '
            'ways, AES-256 with the PC key iterated 1..16, and NG across all 101 keys, all '
            'scored against the 4-byte crib ADAT.' % name)
    xml, _sidecars, _n_none = to_interchange(name, blob, audio='none')
    return xml


def to_xml(path, game_root=None):
    blob = open(path, 'rb').read()
    return to_xml_bytes(os.path.basename(path), blob).decode('utf-8')


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('files', nargs='+')
    ap.add_argument('--out')
    a = ap.parse_args()
    for f in a.files:
        try:
            xml = to_xml(f)
        except AwcEncrypted as e:
            print('BLOCKED:', e)
            continue
        if a.out:
            os.makedirs(a.out, exist_ok=True)
            op = os.path.join(a.out, os.path.basename(f) + '.xml')
            open(op, 'wb').write(xml.encode('utf-8'))
            print('wrote', op)
        else:
            print(xml)
