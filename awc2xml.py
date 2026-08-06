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
"""
import argparse
import os
import struct

from meta2xml import joaat, esc

MAGIC = b'ADAT'
TAG = {joaat(n) & 0xFF: n for n in ('data', 'format', 'peak', 'name', 'seek', 'loop', 'markers')}
CODEC = {0x04: 'ADPCM'}
# minimal name dictionary; the reference exporter resolves joaat hashes it knows, else emits hash_XXXXXXXX
KNOWN_NAMES = {joaat(n): n for n in ('dummy',)}


class AwcEncrypted(Exception):
    pass


def parse(plain, was_encrypted=False):
    if plain[:4] != MAGIC:
        raise AwcEncrypted('not an ADAT plaintext AWC (encrypted header?)')
    version = struct.unpack_from('<H', plain, 4)[0]
    flags = struct.unpack_from('<H', plain, 6)[0]
    numStreams = struct.unpack_from('<I', plain, 8)[0]
    dataStart = struct.unpack_from('<I', plain, 12)[0]
    off = 16
    # variant B (measured on halloween, flags low byte bit 0x04 set): a streamCount x u16
    # chunk-count table precedes the u32 hashes. Detect by the first u16 being small (a name
    # hash's low word is ~random/large; a chunk count is < 256). Single-stream files (the
    # dummies) are always variant A.
    first_u16 = struct.unpack_from('<H', plain, 16)[0]
    if numStreams > 1 and first_u16 < 256:
        off += 2 * numStreams
    hashes = [struct.unpack_from('<I', plain, off + 4 * i)[0] for i in range(numStreams)]
    off += 4 * numStreams
    # chunk-index table: u64 each until dataStart
    all_chunks = []
    o = off
    while o < dataStart:
        v = struct.unpack_from('<Q', plain, o)[0]
        all_chunks.append({'type': TAG.get((v >> 56) & 0xFF, 'unk_%02x' % ((v >> 56) & 0xFF)),
                           'size': (v >> 28) & 0x0FFFFFFF, 'offset': v & 0x0FFFFFFF})
        o += 8
    # distribute chunks to streams. Evidence: uniform chunk-count per stream; infer per-stream
    per = len(all_chunks) // numStreams if numStreams else 0
    streams = []
    for s in range(numStreams):
        cks = all_chunks[s * per:(s + 1) * per] if per else []
        streams.append({'hash': hashes[s], 'chunks': cks})
    return {'version': version, 'flags': flags, 'was_encrypted': was_encrypted,
            'numStreams': numStreams, 'streams': streams}


def _fmt_fields(plain, chunk):
    b = plain[chunk['offset']:chunk['offset'] + chunk['size']]
    codec_b = b[0x13] if len(b) > 0x13 else 0x04
    # PlayBegin/PlayEnd/LoopBegin/LoopEnd are packed in bytes +0x0C..+0x12 and are 0 in ALL
    # evidence (5 mask streams + 5 dummy oracles). The exact bit packing is UNPINNED (no
    # non-zero sample), so they are emitted as 0 rather than guessed.
    return {
        'Codec': CODEC.get(codec_b),
        'Samples': struct.unpack_from('<I', b, 0)[0],
        'LoopPoint': struct.unpack_from('<i', b, 4)[0],
        'SampleRate': struct.unpack_from('<H', b, 8)[0],
        'Headroom': struct.unpack_from('<h', b, 10)[0],
        'PlayBegin': 0, 'PlayEnd': 0, 'LoopBegin': 0, 'LoopEnd': 0,
        'PeakUnk': struct.unpack_from('<H', b, 0x14)[0],
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
                out.append('     <Peak unk="%d" />' % f['PeakUnk'])
            out.append('    </Item>')
        out.append('   </Chunks>')
        out.append('  </Item>')
    out.append(' </Streams>')
    out.append('</AudioWaveContainer>')
    return EOL.join(out) + EOL


def to_xml(path, game_root=None):
    blob = open(path, 'rb').read()
    if blob[:4] == b'RSC7':
        raise ValueError('RSC7 resource, not a raw AWC')
    if blob[:4] != MAGIC:
        raise AwcEncrypted(
            '%s: WholeFileEncrypt - encrypted header (no ADAT magic). No QUARRY key/cipher '
            'inverts it (see module docstring). Supply a decryptor to close this file.'
            % os.path.basename(path))
    parsed = parse(blob, was_encrypted=False)
    return emit(parsed, blob)


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
