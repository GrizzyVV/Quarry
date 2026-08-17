#!/usr/bin/env python3
"""nametable2xml - GTA V `X.datNNN.nametable` -> RAGE interchange XML.

WHY THIS EXISTS (2026-08-16). The lane had a round-trip writer scoring 229/229 and carrying 0%,
and NO EXPORTER AT ALL - `nametable2xml.py` did not exist and `nametable` appears zero times in
`quarry.py`. Step 2 (`tools/step2_nametable.py`) charged the lane **100.000% ABSENT**: a lane can
measure perfectly and ship nothing.

⛔ AND THE OMISSION BROKE A SIBLING LANE. `rel2xml` emits `ntOffset="%d"` (rel2xml.py:544) - a raw
byte offset INTO THIS BLOB - and never resolves it. With no nametable export, **every ntOffset in
every .rel export points into a table the consumer does not have.** Measured before writing this:
`AUDIO_ITEM_GUSENBERG`, `BTYPE_GRANULAR_ENGINE`, `BTYPE_ENGINE` appear in **0** emitted XML files.
So this is not a duplicate of data already downstream - it is the other half of a dangling
reference.

=============================== WHAT THE FILE IS ===============================
A bare NUL-separated ASCII string blob. NO header, no count, no offset array - byte 0 is already
the first character of the first name (`quarry/nametable_write.py`, measured over the whole lane:
133,651 strings across 229 files; **224 of 229 end with a NUL, 5 do not**, and 5 strings are
empty).

⭐ THE OFFSET IS THE PAYLOAD, NOT DECORATION. `ntOffset` indexes bytes, so an exported name is
useless without the byte offset it lives at. Every <Item> therefore carries `offset`, and the
round-trip rebuilds the blob from (offset, text) alone. Emitting the strings in order WITHOUT
their offsets would look complete and still leave `rel`'s references unresolvable.

⭐ `trailingNul` IS RECORDED, NOT ASSUMED. 5 of 229 files do not end with one. Writing a NUL
unconditionally would corrupt those 5 and, because they are 2% of the lane, a small draw would
never show it.

⚠ THE ELEMENT NAMES ARE OURS. This lane has no reference export to copy a schema from - the
oracle set contains `.nametable` only as raw dumps. Nothing here is claimed as witnessed.

ASCII output only.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from meta2xml import esc  # noqa: E402


def parse(blob):
    """-> (list of (offset, text), trailing_nul). Offsets are ABSOLUTE byte positions."""
    items = []
    off = 0
    n = len(blob)
    while off < n:
        end = blob.find(b'\x00', off)
        if end < 0:                      # no terminator: the tail IS the last string
            items.append((off, blob[off:]))
            off = n
            break
        items.append((off, blob[off:end]))
        off = end + 1
    return items, (n > 0 and blob[-1:] == b'\x00')


def to_xml_bytes(name, blob):
    """`quarry.to_interchange_xml` entry point - takes a name and a blob, never a path."""
    items, trailing = parse(blob)
    EOL = '\r\n'
    out = ['<?xml version="1.0" encoding="UTF-8"?>', '<NameTable>']
    out.append(' <TrailingNul value="%s" />' % ('True' if trailing else 'False'))
    out.append(' <Items>')
    for off, s in items:
        # ⛔ STRICT ASCII, and a non-ASCII byte REFUSES rather than being mangled through a
        # replacement char - the same rule nametable_write applies on the way in. A silently
        # substituted byte would round-trip wrong and look like a decode success.
        try:
            txt = s.decode('ascii')
        except UnicodeDecodeError:
            raise ValueError('%s: non-ASCII byte in name table at offset %d' % (name, off))
        out.append('  <Item offset="%d">%s</Item>' % (off, esc(txt)))
    out.append(' </Items>')
    out.append('</NameTable>')
    return (EOL.join(out) + EOL).encode('utf-8')


def from_xml_bytes(xml):
    """XML -> the original blob. Here so the export is REVERSIBLE BY CONSTRUCTION, and so
    `tools/step2_nametable.py` measures the shipped emitter rather than a private copy of it."""
    import xml.etree.ElementTree as ET
    root = ET.fromstring(xml)
    trailing = (root.findtext('TrailingNul') or
                (root.find('TrailingNul').get('value') if root.find('TrailingNul') is not None
                 else 'False')) == 'True'
    items = []
    for it in root.find('Items'):
        items.append((int(it.get('offset')), (it.text or '').encode('ascii')))
    if not items:
        return b''
    size = max(o + len(s) for o, s in items) + (1 if trailing else 0)
    # a NUL sits between every pair, so the image is zero-filled and only the text is written
    buf = bytearray(size)
    for o, s in items:
        buf[o:o + len(s)] = s
    return bytes(buf)


def to_xml(path):
    return to_xml_bytes(os.path.basename(path), open(path, 'rb').read()).decode('utf-8')


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('files', nargs='+')
    a = ap.parse_args()
    for f in a.files:
        print(to_xml(f))
