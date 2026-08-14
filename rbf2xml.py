"""RBF0 -> the reference exporter-shaped XML.

RBF ("RAGE Binary Format", magic `RBF0`) is RAGE's OLDER binary-XML serialisation - a
straight tokenised dump of an XML document, unrelated to the META/PSO ('PSIN') containers
that carry most .ymt. It is NOT an RSC7 resource: the magic sits at byte 0 of the file, so
the bytes are the container directly with no paging/decompression step.

⭐ DERIVATION (clean-room; evidence = the game's own binaries + the reference exporter oracle XML
for the one .ymt we hold a reference export of). Every rule below was measured, never
assumed - see the LAYOUT section. The measurement corpus is 71 RBF0 binaries pulled from
the Legacy build: 40 x `CMapTypes` destruction manifests (x64a.rpf/levels/gta5/destruction)
and 31 x `CMovieSubtitleContainer` (x64d moviesubs.rpf). ⚠ That is a SAMPLE, not a census -
it is every `des_*` / `bink*` .ymt in the base archives, and update.rpf was not swept - so
the type inventory below is a LOWER BOUND on what RBF can encode, and an unknown type
nibble raises rather than being rendered.

All 71 parse to the EXACT final byte with a balanced element stack, which is the structural
proof the layout is complete for what they contain: any wrong field width would
desynchronise the stream and land mid-record.


LAYOUT
------
  offset 0   char[4]  "RBF0"
  offset 4   a flat stream of RECORDS until EOF. No name table, no index, no sizes -
             the document is depth-first and self-delimiting.

RECORD = u16 token, little-endian.

  token == 0xFFFF          END: close the innermost open element.
  token == 0xFFFD          TEXT: u32 length, then `length` OPAQUE BYTES. It is the character
                           data of the element that encloses it. ⛔ THE LENGTH IS A BYTE
                           COUNT AND NOTHING MORE - see BINARY CHARACTER DATA below.
  otherwise                NAMED NODE:  type = token >> 12,  nameIndex = token & 0x0FFF.


BINARY CHARACTER DATA - the law this reader used to get wrong (corrected 2026-08-14)
------------------------------------------------------------------------------------
This reader used to require every TEXT payload to end with a NUL, on the strength of
"measured 4,766/4,766 NUL-terminated". That sample was drawn from two families only
(`CMapTypes` destruction manifests and `CMovieSubtitleContainer`), whose text is all strings -
so it measured the CONTENT, not the container, and 58 real `.ymt` refused against it.

MEASURED over EVERY RBF0 container the game archives yield - 117 files, 15,409 text records,
sample size printed by the probe:
  * 117/117 parse to the exact final byte with a balanced element stack when the payload is
    read as `length` opaque bytes. That is the structural proof: any wrong field width would
    desynchronise the stream and land mid-record.
  * 14,525 payloads are NUL-terminated printable strings (cName, child, parent, AnimName,
    fxObjName, ptFxTag, shaderVariableHashString, ...).
  * 884 are NOT strings at all. They are the `CCreatureMetaData` numeric members, and their
    payload length is FIXED PER MEMBER across the whole population:
        tracks      1 byte  x 235 records      types       1 byte  x 179 records
        components  1 byte  x 235 records      ids         2 bytes x 235 records
    A fixed width where every string member's length varies is what separates them.
  * ⭐ THE SAME MEMBER IS SOMETIMES NUL-TERMINATED AND SOMETIMES NOT, PURELY BY VALUE:
    `components` is one byte, and the 14 records whose value is 0 end with a NUL while the
    other 221 do not. NUL-termination was never a property of the record.
  * ⭐ `ids` IS LITTLE-ENDIAN u16, proved by the file's own data rather than assumed: the
    values b'\x17\xd7' / b'\x18\xd7' / b'\x19\xd7' and b'\xe8\xfc' / b'\xe9\xfc' / b'\xea\xfc'
    are CONSECUTIVE under little-endian (55063/55064/55065 and 64744/64745/64746) and stride
    256 under big-endian.

⭐⭐ THE FILE DECLARES THE ELEMENT WIDTH ITSELF, AND THIS READER ALREADY HAD IT.
The width is NOT schema knowledge and NOT a guess: every one of the 884 binary records sits on
an element carrying a real XML ATTRIBUTE that names its content type - `content="char_array"`
(1 byte per element) or `content="short_array"` (2 bytes per element). The attribute is an
ordinary RBF attribute record, so it was being parsed and emitted all along; it just was not
being CONSULTED. Correlation over the whole population, 15,409 of 15,409:
    content="char_array"   -> 649 records, payload length 1     (tracks, types, components)
    content="short_array"  -> 235 records, payload length 2     (ids)
    NO attribute at all    -> 14,525 records, all NUL-terminated printable strings
⇒ CLASSIFY ON THE DECLARED TYPE, never on a heuristic; the string/binary shape of the payload
is then a CROSS-CHECK that must agree, and a disagreement raises rather than picking a winner.
An unknown `content` value raises too - inventing a width for it would be exactly the guess
this reader exists to refuse.

SIGNEDNESS is the one thing left unpinned, and only for `short_array`: 4 of the 63 distinct
`ids` values exceed 32767, so the spelling is visible. Rendered UNSIGNED. Evidence: these ids
live in the same numeric space as this game's 16-bit bone TAGS, which every other reader in
this product decodes unsigned (yft2xml bone tag u16 @bone+0x44, values observed to 65245 on a
100-bone ped), and one `ids` value (19336) appears verbatim in a ped's bone-tag set. ⚠ AGENT
call, one word flips it; the record count is printed under
`rbf_typed_array_transcribed_short_array_unsigned`.

RENDERING: elements of the declared width, LITTLE-ENDIAN, as SPACE-SEPARATED DECIMALS - the
spelling the reference export uses for a byte array elsewhere in the same lane
(`<availComp>0 255 1 2 3 255 4 255 5 6 7 255</availComp>` in the PSO `hc_driver.ymt` oracle).
⛔ The old law rendered the 14 `components` records whose value is 0 - payload `b'\0'` - as an
EMPTY string, because a 1-byte zero looks exactly like a terminator with nothing before it.

NAME TABLE (implicit, built while reading): the first time a nameIndex is used it EQUALS
the number of names read so far, and the name follows inline as u16 length + that many
ASCII bytes (no NUL). Every later use of the same index is a back-reference and carries no
name. Measured: 1,473/1,473 inline names had length == bytes consumed; no index ever
appeared out of order, so a reader can simply append to a list.

TYPE NIBBLE (all six values observed; nothing else occurs in the 71-file corpus):

  0  ELEMENT   payload = u32 reserved + u16 attributeCount, then attributeCount records
               that are the element's XML ATTRIBUTES, then its child records, then 0xFFFF.
               The u32 is 0 in all 13,115 elements measured -> UNPINNED meaning, carried
               through as `reserved`.
               attributeCount measured in {0, 1, 4}: 4 = a quaternion written as
               <fxOffsetRot x= y= z= w= />, 1 = <Item type="CMovieSubtitleEventArg">.
  1  UINT32    payload = u32.   Rendered `value="0x%X"` - the reference exporter spells these HEX, and
               that is why <endPhase value="0x1" /> sits next to
               <startPhase value="0.08235294" />: the source XML held an integer literal
               there and RBF preserved the distinction.
  2  BOOL TRUE   no payload. Rendered `value="True"`.
  3  BOOL FALSE  no payload. Rendered `value="False"`.
               (The value lives in the TYPE, not in a byte - counted 1 x type-2 and
               23 x type-3 in des_heli_billboard against exactly 1 x "True" and
               23 x "False" in the oracle XML.)
  4  FLOAT32   payload = f32.   Rendered `value="..."` as a child, `name="..."` as an
               attribute, via the measured 7-else-9 significant-digit float law.
  5  FLOAT3    payload = 3 x f32. Rendered `x=".." y=".." z=".."` on one self-closing tag.
  6  STRING    payload = u16 length + that many bytes, NOT NUL-terminated. Only ever seen
               in an attribute slot (7,233/7,233), i.e. a real XML attribute string.

RENDERING (the oracle pins all of this except where noted UNPINNED):
  * `<?xml version="1.0" encoding="UTF-8"?>` header line; ONE SPACE of indent per depth.
  * self-closing tags are written `<tag ... />` - space before the slash.
  * an element whose only body is one TEXT record collapses to `<Name>text</Name>`.
  * no element in the corpus mixes text with element children, and no TEXT record is
    empty, so neither case is guessed at here - both raise rather than invent a spelling.
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from meta2xml import esc, fmt_num  # noqa: E402

MAGIC = b'RBF0'

TOK_END = 0xFFFF
TOK_TEXT = 0xFFFD

T_ELEMENT = 0
T_UINT32 = 1
T_TRUE = 2
T_FALSE = 3
T_FLOAT = 4
T_FLOAT3 = 5
T_STRING = 6


class RbfError(Exception):
    """The stream did not match the derived layout. Raised instead of guessing - a silent
    fallback here would emit plausible XML for a file we did not actually understand."""


def _refuse(key, detail=None):
    """Count a decline/downgrade into the ONE emitter counter table the interchange-XML lane
    already prints (quarry calls ydr2xml.report_refusals(stats) once). A counter nobody prints
    is the same as no counter - that is register item Z."""
    try:
        import ydr2xml
    except Exception:                                    # pragma: no cover - standalone use
        return
    ydr2xml._refuse(key, detail)


# `content` attribute value -> bytes per element. ⛔ ONLY the two the game's whole RBF0
# population declares. An unknown content type RAISES: the width would otherwise have to be
# guessed, and a wrong width silently renders the right bytes as the wrong numbers.
ARRAY_ELEMENT_WIDTH = {
    'char_array': 1,
    'short_array': 2,
}


def is_string_payload(raw):
    """Shape CROSS-CHECK, never the classifier. True when the payload looks like a
    NUL-terminated printable string. The authority is the element's `content` attribute -
    see BINARY CHARACTER DATA in the module docstring."""
    if len(raw) < 2 or not raw.endswith(b'\0'):
        return False
    return all(32 <= c < 127 or c in (9, 10, 13) for c in raw[:-1])


def content_type(node):
    """The element's declared character-data type, or None when it declares none."""
    for a in node.attrs:
        if a.name == 'content':
            return a.value
    return None


class Node(object):
    """One named record. `kind` is the raw type nibble; `value` is the decoded payload
    (None for elements/bools, int, float, (x, y, z) or str). `attrs`/`kids` are only
    populated for elements and are already split by the stored attributeCount.

    `text` is the element's character data when it is a string; `blob` holds the raw payload
    when it is binary (the two are mutually exclusive and both are None otherwise)."""

    __slots__ = ('name', 'kind', 'value', 'attrs', 'kids', 'text', 'blob', 'blob_width',
                 'reserved')

    def __init__(self, name, kind, value=None):
        self.name = name
        self.kind = kind
        self.value = value
        self.attrs = []
        self.kids = []
        self.text = None
        self.blob = None
        self.blob_width = 1
        self.reserved = 0


# ---------------------------------------------------------------------------- parsing

def parse(blob):
    """bytes -> root Node. Consumes the whole file; anything left over is an error, because
    a trailing remainder means a field width is wrong somewhere upstream."""
    if blob[:4] != MAGIC:
        raise RbfError('not an RBF0 container (magic %r)' % blob[:4])
    p = 4
    n = len(blob)
    names = []
    root = None
    stack = []

    def _u16():
        nonlocal p
        if p + 2 > n:
            raise RbfError('truncated u16 at %d' % p)
        v = struct.unpack_from('<H', blob, p)[0]
        p += 2
        return v

    def _u32():
        nonlocal p
        if p + 4 > n:
            raise RbfError('truncated u32 at %d' % p)
        v = struct.unpack_from('<I', blob, p)[0]
        p += 4
        return v

    while p < n:
        at = p
        tok = _u16()

        if tok == TOK_END:
            if not stack:
                raise RbfError('close with no open element at %d' % at)
            stack.pop()
            continue

        if tok == TOK_TEXT:
            ln = _u32()
            if p + ln > n:
                raise RbfError('truncated text (%d bytes) at %d' % (ln, at))
            raw = blob[p:p + ln]
            p += ln
            if not stack:
                raise RbfError('text outside any element at %d' % at)
            owner = stack[-1]
            if owner.text is not None or owner.blob is not None:
                raise RbfError('element %r has two text records (UNPINNED spelling)'
                               % owner.name)
            # ⛔ NOT "must end with NUL". The payload is `ln` bytes whose TYPE the element
            # declares in its `content` attribute; 884 of the game's 15,409 text records are
            # typed numeric arrays, one of which (`components`) is NUL-terminated or not
            # depending on its VALUE. See BINARY CHARACTER DATA in the module docstring.
            ctype = content_type(owner)
            if ctype is None:
                if not is_string_payload(raw):
                    raise RbfError('text at %d: element %r declares no content type and the '
                                   'payload is not a NUL-terminated string (%d B)'
                                   % (at, owner.name, ln))
                owner.text = _decode(raw[:-1])
                continue
            width = ARRAY_ELEMENT_WIDTH.get(ctype)
            if width is None:
                raise RbfError('text at %d: element %r declares UNMEASURED content type %r - '
                               'refusing rather than guessing an element width'
                               % (at, owner.name, ctype))
            if ln % width:
                raise RbfError('text at %d: element %r is %r but %d bytes is not a whole '
                               'number of %d-byte elements' % (at, owner.name, ctype, ln, width))
            owner.blob = raw
            owner.blob_width = width
            _refuse('rbf_typed_array_transcribed_%s_unsigned' % ctype,
                    '%s (%d B)' % (owner.name, ln))
            continue

        kind = tok >> 12
        idx = tok & 0x0FFF
        if idx == len(names):
            ln = _u16()
            if p + ln > n:
                raise RbfError('truncated name (%d bytes) at %d' % (ln, at))
            names.append(_decode(blob[p:p + ln]))
            p += ln
        elif idx > len(names):
            raise RbfError('name index %d ahead of the table (%d) at %d'
                           % (idx, len(names), at))
        node = Node(names[idx], kind)

        if kind == T_ELEMENT:
            node.reserved = _u32()
            nattr = _u16()
        elif kind == T_UINT32:
            node.value = _u32()
        elif kind in (T_TRUE, T_FALSE):
            node.value = (kind == T_TRUE)
        elif kind == T_FLOAT:
            if p + 4 > n:
                raise RbfError('truncated f32 at %d' % at)
            node.value = struct.unpack_from('<f', blob, p)[0]
            p += 4
        elif kind == T_FLOAT3:
            if p + 12 > n:
                raise RbfError('truncated f32[3] at %d' % at)
            node.value = struct.unpack_from('<3f', blob, p)
            p += 12
        elif kind == T_STRING:
            ln = _u16()
            if p + ln > n:
                raise RbfError('truncated string (%d bytes) at %d' % (ln, at))
            node.value = _decode(blob[p:p + ln])
            p += ln
        else:
            raise RbfError('unknown RBF type nibble 0x%X (%r) at %d'
                           % (kind, node.name, at))

        if stack:
            owner = stack[-1]
            # the first `attributeCount` records inside an element ARE its attributes.
            if len(owner.attrs) < owner.value:
                owner.attrs.append(node)
            else:
                owner.kids.append(node)
        elif root is None:
            root = node
        else:
            raise RbfError('second root record %r at %d' % (node.name, at))

        if kind == T_ELEMENT:
            node.value = nattr          # attribute count, consumed by the split above
            stack.append(node)

    if stack:
        raise RbfError('%d element(s) never closed' % len(stack))
    if p != n:
        raise RbfError('%d trailing byte(s)' % (n - p))
    if root is None:
        raise RbfError('empty container')
    return root


def _decode(raw):
    try:
        return raw.decode('utf-8')
    except UnicodeDecodeError:
        # no non-ASCII byte occurs in the corpus; keep the bytes rather than lose them.
        return raw.decode('latin-1')


# --------------------------------------------------------------------------- rendering

def _attr_text(node):
    """A record standing in an XML attribute slot -> its value text. Measured: only
    FLOAT and STRING ever occupy an attribute slot (1,240 + 7,233 of 8,473); the scalar
    types below are rendered the same way they are as children, which is the only
    self-consistent extension. ELEMENT/FLOAT3 cannot be an attribute - that is a decode
    error, not a spelling question."""
    if node.kind == T_FLOAT:
        return fmt_num(node.value)
    if node.kind == T_STRING:
        return node.value
    if node.kind == T_UINT32:
        return '0x%X' % node.value
    if node.kind in (T_TRUE, T_FALSE):
        return 'True' if node.value else 'False'
    raise RbfError('type 0x%X (%r) cannot be an XML attribute' % (node.kind, node.name))


def _attr_pairs(node):
    return ''.join(' %s="%s"' % (a.name, esc(_attr_text(a))) for a in node.attrs)


def _emit(node, depth, out):
    pad = ' ' * depth
    if node.kind == T_ELEMENT:
        head = node.name + _attr_pairs(node)
        if node.text is not None or node.blob is not None:
            if node.kids:
                raise RbfError('element %r mixes text and children (UNPINNED spelling)'
                               % node.name)
            # A TYPED ARRAY renders as space-separated unsigned decimals at the width the
            # element's own `content` attribute declares - the same spelling the reference
            # export uses for a byte array.
            body = (esc(node.text) if node.text is not None
                    else ' '.join(str(int.from_bytes(node.blob[i:i + node.blob_width],
                                                     'little'))
                                  for i in range(0, len(node.blob), node.blob_width)))
            out.append('%s<%s>%s</%s>' % (pad, head, body, node.name))
            return
        if not node.kids:
            out.append('%s<%s />' % (pad, head))
            return
        out.append('%s<%s>' % (pad, head))
        for k in node.kids:
            _emit(k, depth + 1, out)
        out.append('%s</%s>' % (pad, node.name))
        return
    if node.kind == T_UINT32:
        out.append('%s<%s value="0x%X" />' % (pad, node.name, node.value))
    elif node.kind in (T_TRUE, T_FALSE):
        out.append('%s<%s value="%s" />' % (pad, node.name,
                                            'True' if node.value else 'False'))
    elif node.kind == T_FLOAT:
        out.append('%s<%s value="%s" />' % (pad, node.name, fmt_num(node.value)))
    elif node.kind == T_FLOAT3:
        x, y, z = node.value
        out.append('%s<%s x="%s" y="%s" z="%s" />'
                   % (pad, node.name, fmt_num(x), fmt_num(y), fmt_num(z)))
    elif node.kind == T_STRING:
        # UNPINNED: type 6 never appears outside an attribute slot in the corpus, so the
        # reference spelling for a standalone string node is unwitnessed. `value=` matches
        # every other scalar child.
        out.append('%s<%s value="%s" />' % (pad, node.name, esc(node.value)))
    else:
        raise RbfError('unknown RBF type nibble 0x%X (%r)' % (node.kind, node.name))


def to_xml(root):
    out = ['<?xml version="1.0" encoding="UTF-8"?>']
    _emit(root, 0, out)
    return '\n'.join(out) + '\n'


def convert(name, blob, names=None):
    """`name` and `names` exist for parity with the other converters: an RBF document
    carries every element and attribute name as text, so no joaat dictionary is needed and
    the filename never appears in the output."""
    return to_xml(parse(blob))


def root_name(blob):
    """Cheap peek at the document element - lets a caller route/label without a full parse
    (the two families in the game are CMapTypes and CMovieSubtitleContainer)."""
    return parse(blob).name


if __name__ == '__main__':
    for _p in sys.argv[1:]:
        with open(_p, 'rb') as _fh:
            sys.stdout.write(convert(os.path.basename(_p), _fh.read()))
