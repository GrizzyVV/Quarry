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
  token == 0xFFFD          TEXT: u32 length, then `length` bytes of NUL-TERMINATED ASCII
                           (the length COUNTS the NUL). It is the character data of the
                           element that encloses it.
  otherwise                NAMED NODE:  type = token >> 12,  nameIndex = token & 0x0FFF.

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


class Node(object):
    """One named record. `kind` is the raw type nibble; `value` is the decoded payload
    (None for elements/bools, int, float, (x, y, z) or str). `attrs`/`kids` are only
    populated for elements and are already split by the stored attributeCount."""

    __slots__ = ('name', 'kind', 'value', 'attrs', 'kids', 'text', 'reserved')

    def __init__(self, name, kind, value=None):
        self.name = name
        self.kind = kind
        self.value = value
        self.attrs = []
        self.kids = []
        self.text = None
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
            if not raw.endswith(b'\0'):
                # measured 4,766/4,766 NUL-terminated; a non-terminated one would mean the
                # length is not what this reader thinks it is.
                raise RbfError('text at %d is not NUL-terminated' % at)
            if not stack:
                raise RbfError('text outside any element at %d' % at)
            owner = stack[-1]
            if owner.text is not None:
                raise RbfError('element %r has two text records (UNPINNED spelling)'
                               % owner.name)
            owner.text = _decode(raw[:-1])
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
        if node.text is not None:
            if node.kids:
                raise RbfError('element %r mixes text and children (UNPINNED spelling)'
                               % node.name)
            out.append('%s<%s>%s</%s>' % (pad, head, esc(node.text), node.name))
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
