"""rbf_write - ROUND-TRIP WRITER for the RAGE RBF0 binary-XML container.

    original file bytes -> value model -> written back -> MUST reproduce the original bytes

WHY (maintainer ruling 2026-08-13): round-trip byte identity is the primary measure, and a lane
with a READER and no WRITER is **UNMEASURED, not passing**. `.ymt` is a container zoo - 2,326
RSC7-META (closed by `meta_write`) + 2,190 PSIN (closed by `pso_write`) + **197 RBF0** - and the
RBF0 third had `rbf2xml.py` (a reader) and nothing that could rebuild a byte. `.ymf` carries 3
more. This writer addresses that remainder.

SCOPE IS THE WHOLE FILE. RBF0 is not an RSC7 resource: the magic sits at byte 0, there is no
paging, no compression and no system/graphics segment. So the measure here is the FILE, with no
"inflated segment" caveat.

ALL INTEGERS ARE LITTLE-ENDIAN (unlike its sibling `pso_write`, where every integer is big-endian
- the two containers share the `.ymt` extension and agree on nothing else).

MODEL, NOT MEMCPY - and this container makes the claim unusually falsifiable, because it has no
offset table at all. Nothing can be "claimed" at a copied offset: the stream is a depth-first,
self-delimiting concatenation, so **every byte's position is a consequence of every byte before
it**. Drop one field and the whole tail moves.

  1. A TREE, not a record slab. The END token (0xFFFF) is NOT stored in the model - it is emitted
     from the tree's own shape, so a mis-modelled element boundary cannot be papered over.
  2. THE NAME TABLE IS REBUILT, NOT CARRIED. RBF has no name section: the first use of a name
     index carries the name inline (u16 length + bytes) and every later use is a bare
     back-reference. The writer re-derives `name -> index` by FIRST-USE ORDER from the tree and
     re-emits the inline names itself. And the derivation is CHECKED: `parse` records which
     records the FILE spelled inline, `write` computes which records SHOULD be inline, and
     `_check_name_derivation` REFUSES when they disagree. That is what makes the index a derived
     value and not a copied one.
  3. EVERY RECORD IS WIDTH-CHECKED AT PARSE. `_reemit_len` states, per record, how many bytes the
     model will write back; `parse` compares that against the bytes the record actually consumed
     and REFUSES on any disagreement. This is `yvr_write._check_tiling` applied per record instead
     of per stride: it proves the field map tiles the stream with no hole and no overlap, for
     every record of every file, before any comparison is made.
  4. LENGTH PREFIXES ARE COMPUTED, NEVER CARRIED - the inline-name u16, the STRING u16 and the
     TEXT u32 are all `len(the thing this model rebuilt)`. A payload rebuilt one byte short moves
     every following byte in the file.
  5. Payload values are decoded to TYPED values (u32, f32, f32[3], str, int arrays at the width
     the element's own `content` attribute declares) and re-encoded from those values.

⛔ IT DOES NOT IMPORT `rbf2xml`, AND THAT IS DELIBERATE. Two reasons, both of them this vault's
own law. (1) `rbf2xml` REFUSES several shapes on purpose - an undeclared `content` type, an
element that mixes text with children, a payload that is neither - and a refusal is the right
answer for an XML EXPORT and the wrong answer for a MEASURE, where a file that cannot be modelled
must be counted, not dropped from the sample. (2) *byte identity with a second reader cannot see
a gap both readers share* - the `pso_write` sub-0x04 finding is the witnessed case, 242 bytes of
live data that nothing in the type walk touched in a file whose XML export looked clean. So the
parse here is independent and the only thing taken from `rbf2xml` is `ARRAY_ELEMENT_WIDTH`, which
was derived there against the whole population and is cited, not re-derived.

WHAT IS CARRIED, AND IT IS DECLARED (see `regions()` - quote it next to any coverage figure):
  - NOTHING, on the game's population. The only carry path in this file is a TEXT payload that
    neither declares a `content` type nor parses as a NUL-terminated printable string; it is
    re-encoded as raw bytes and COUNTED as `text_carried_bytes`, and `regions()` reports it.
    Measured over the population it is 0 bytes - but the path exists so that an unmeasured
    payload shape is reported rather than crashing the lane.
  - A float whose bit pattern does not survive decode->encode (a signalling NaN) is re-encoded as
    the stored word and counted as `float_reencoded_as_word` - reproduced, but tagged UNTYPED
    because "we reproduced it" and "we understand it" are different claims.

MEASURED AT POPULATION 2026-08-15 (one walk of all 179 top-level archives, AES key bound, zero
archive errors; the walk returns .ymt 4,713 and .ymf 1,795 - equal to `VIEW_MANIFEST.jsonl` for
both, so the draw provably reaches the whole lane). Reproduce with either of:
    python tools/roundtrip_coverage.py --lane ymt_rbf --limit 9000 --cap 0    (and ymf_rbf)
    python quarry/rbf_write.py --all
  lane      files  BYTE-EXACT         mean cov   min cov   VALUE  UNTYP   DERIV  CARR  ZERO
  ymt_rbf     197    197 (100.0000%)  100.0000%  100.0000% 84.813% 0.000% 15.187% 0.00% 0.00%
  ymf_rbf       3      3 (100.0000%)  100.0000%  100.0000% 78.363% 0.000% 21.637% 0.00% 0.00%
  TOTAL       200    200 (100.0000%)                       over 1,845,656 bytes
⭐ AND THE SPLIT IS WHY THAT 100% MEANS SOMETHING: 0 bytes carried, 0 bytes zero-fill. Every byte
of every file is either re-encoded from a decoded value (84.8%) or computed from a rule (15.2%:
the magic, the END tokens, and every length prefix). There is no region in this lane the measure
cannot speak to - which is not a property of the writer, it is a property of a container that has
no offset table and no padding.

⭐ MUST-FAIL CONTROL, 200 files, 3,471 model mutations: 3,471 CAUGHT (100.00%), eight classes,
none excluded:
    value 1,149/1,149   name 400/400   nameorder 400/400   nattr 400/400
    drop    400/400     reserved 400/400   text 286/286    nibble 36/36
⛔ `pso_write`'s battery has to exclude 552,502 writes aimed at regions the original leaves zero,
because a mutation there is undetectable by construction. THIS battery excludes nothing, for the
same reason the accounting shows no zero-fill.

STRUCTURE WALKED, so the sample can be argued rather than asserted: 135,376 named records
(48,357 element / 38,021 u32 / 24,804 string / 22,876 f32 / 722 f32[3] / 184 true / 412 false),
25,996 attributes, 21,169 character-data records (18,317 strings + 2,852 typed arrays +
**0 carried**), 3,116 distinct names rebuilt by first-use order.

⚠ SPACE SEARCHED / NOT SEARCHED. This lane is defined as the RBF0 containers carried by the
`.ymt` and `.ymf` extensions, because those are the two the container census covers. RBF0 files
under some OTHER extension would not appear in either draw - the magic of every file in the game
has not been classified, only the magic of every `.ymt`, `.ymf`, `.cut` and `.pso`.

ASCII output only.
"""
import os
import struct
import sys as _sys

_sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

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

# Type nibble -> the fixed number of PAYLOAD bytes that follow the token (before any inline name).
# ⛔ THE TABLE MUST COVER EVERY NIBBLE THE STREAM CAN CARRY, WITH NO HOLE. A nibble absent here is
# a width this model does not know, and guessing one would silently re-read the whole rest of the
# file at the wrong offset - the exact failure mode `rbf2xml` refuses at read time. Variable-width
# records (ELEMENT, STRING, and the TEXT pseudo-record) are marked None and compute their own
# width from decoded values; that is checked per record by `_reemit_len`, not asserted here.
FIXED_PAYLOAD = {
    T_ELEMENT: None,     # u32 reserved + u16 attributeCount
    T_UINT32: 4,
    T_TRUE: 0,           # the value lives in the TYPE nibble, not in a byte
    T_FALSE: 0,
    T_FLOAT: 4,
    T_FLOAT3: 12,
    T_STRING: None,      # u16 length + that many bytes
}

# `content` attribute value -> bytes per element of a typed character-data array.
# Taken unchanged from `rbf2xml.ARRAY_ELEMENT_WIDTH`, where it was derived and measured over the
# whole RBF0 population (649 char_array records at 1 B, 235 short_array records at 2 B, correlated
# 15,409 of 15,409 against the declared attribute). Nothing new is asserted here.
ARRAY_ELEMENT_WIDTH = {'char_array': 1, 'short_array': 2}


def _check_type_table():
    """REFUSE AT IMPORT unless the nibble table tiles the 3-bit type space with no hole.

    The `yvr_write._check_tiling` idea, applied to the one thing that is fixed in this container.
    A nibble the stream can spell but this table does not name is a record width nobody derived,
    and a writer that discovers that at run time discovers it as a wrong number rather than as an
    error. The nibble is `token >> 12` and the token's low 12 bits are the name index, so the
    spellable range is 0..0xE (0xF is reserved by the END/TEXT sentinels).
    """
    named = set(FIXED_PAYLOAD)
    if named != set(range(T_ELEMENT, T_STRING + 1)):
        raise ImportError('rbf_write: FIXED_PAYLOAD does not tile the modelled nibble range '
                          '%r' % sorted(named))
    for k, v in FIXED_PAYLOAD.items():
        if v is not None and (not isinstance(v, int) or v < 0):
            raise ImportError('rbf_write: nibble %d has a nonsense width %r' % (k, v))


_check_type_table()


class RbfWriteError(Exception):
    """The stream did not match the derived layout, or the model could not be rebuilt from it.

    Raised rather than guessed. A silent fallback here would produce a plausible file for a
    container we did not actually understand, which is the one outcome this measure exists to
    make impossible.
    """


def _is_string_payload(raw):
    """Shape CROSS-CHECK, never the classifier (the element's `content` attribute is the
    authority - see `rbf2xml`'s BINARY CHARACTER DATA note). True when the payload is a
    NUL-terminated printable string."""
    if len(raw) < 2 or not raw.endswith(b'\x00'):
        return False
    return all(32 <= c < 127 or c in (9, 10, 13) for c in raw[:-1])


class Node(object):
    """One named record of the tree.

    `items` is the element's body in FILE ORDER and holds both child Nodes and Text records; the
    first `nattr` NAMED items are the element's XML attributes (TEXT never counts toward the
    attribute quota - that is the file's own rule, mirrored from `rbf2xml.parse`).
    """

    __slots__ = ('name', 'kind', 'u32', 'f32', 'f3', 'text', 'reserved', 'nattr', 'items',
                 'inline', 'word')

    def __init__(self, name, kind):
        self.name = name
        self.kind = kind
        self.u32 = None          # T_UINT32 value
        self.f32 = None          # T_FLOAT value
        self.f3 = None           # T_FLOAT3 value
        self.text = None         # T_STRING value (str, latin-1 bijection)
        self.reserved = 0        # T_ELEMENT: the u32 whose meaning is unpinned
        self.nattr = 0           # T_ELEMENT: declared attribute count
        self.items = []          # T_ELEMENT: ordered body
        self.inline = False      # did the FILE spell this record's name inline?
        self.word = None         # T_FLOAT: stored word, when the float does not survive f32


class Text(object):
    """One 0xFFFD character-data record.

    Exactly one of `s` (a decoded string), `arr` (typed integer elements at `width`) or `raw`
    (carried bytes, counted) is set - and `raw` is the only path that is not a value.
    """

    __slots__ = ('s', 'arr', 'width', 'raw', 'owner')

    def __init__(self):
        self.s = None
        self.arr = None
        self.width = 1
        self.raw = None
        self.owner = None


# Byte-accounting tags. A write says WHAT KIND OF EVIDENCE its bytes are, so `regions()` reports
# the split instead of estimating it.
T_VALUE = 1        # re-encoded from a decoded, typed value
T_UNTYPED = 2      # reproduced at a pinned position, semantics unmapped
T_DERIVED = 3      # computed from a rule, never read at that position
T_CARRIED = 4      # copied bytes; the round-trip could not have rejected them


class RbfRT(object):
    """The value model of one RBF0 file, and the writer that rebuilds it."""

    def __init__(self, blob):
        blob = bytes(blob)
        if blob[:4] != MAGIC:
            raise RbfWriteError('not an RBF0 container (magic %r)' % blob[:4])
        self.blob = blob
        self.size = len(blob)
        self.acct = {}
        self.notes = {}
        self.root = None
        self.file_names = []        # the name table as the FILE spelled it, for the check below
        self._parse()
        self._check_name_derivation()

    # ------------------------------------------------------------------ bookkeeping
    def _bump(self, k, n=1):
        self.acct[k] = self.acct.get(k, 0) + n

    def _note(self, k):
        self.notes[k] = self.notes.get(k, 0) + 1

    # ------------------------------------------------------------------ the field map
    @staticmethod
    def _reemit_len(rec, inline):
        """How many bytes this model will WRITE BACK for one record. THIS IS THE FIELD MAP.

        `parse` compares it against the bytes the record actually consumed, per record, and
        REFUSES on a mismatch - so byte identity here proves the field map is complete rather
        than merely that the bytes were copied.
        """
        if isinstance(rec, Text):
            if rec.s is not None:
                n = len(rec.s.encode('latin-1')) + 1        # + the NUL this model re-adds
            elif rec.arr is not None:
                n = len(rec.arr) * rec.width
            else:
                n = len(rec.raw)
            return 2 + 4 + n                                # token + u32 length + payload
        n = 2                                               # the token
        if inline:
            n += 2 + len(rec.name.encode('latin-1'))        # u16 length + the name bytes
        k = rec.kind
        if k == T_ELEMENT:
            n += 4 + 2                                      # reserved + attributeCount
        elif k == T_STRING:
            n += 2 + len(rec.text.encode('latin-1'))
        else:
            n += FIXED_PAYLOAD[k]
        return n

    # ------------------------------------------------------------------ parse
    def _parse(self):
        blob = self.blob
        n = len(blob)
        p = 4
        names = []
        stack = []                  # open elements
        named_seen = []             # per open element: how many NAMED items so far
        root = None

        while p < n:
            at = p
            if p + 2 > n:
                raise RbfWriteError('truncated token at %d' % p)
            tok = struct.unpack_from('<H', blob, p)[0]
            p += 2

            if tok == TOK_END:
                if not stack:
                    raise RbfWriteError('close with no open element at %d' % at)
                stack.pop()
                named_seen.pop()
                continue

            if tok == TOK_TEXT:
                if p + 4 > n:
                    raise RbfWriteError('truncated text length at %d' % at)
                ln = struct.unpack_from('<I', blob, p)[0]
                p += 4
                if p + ln > n:
                    raise RbfWriteError('truncated text (%d B) at %d' % (ln, at))
                raw = blob[p:p + ln]
                p += ln
                if not stack:
                    raise RbfWriteError('text outside any element at %d' % at)
                owner = stack[-1]
                t = Text()
                t.owner = owner
                ctype = self._content_type(owner)
                if ctype is not None and ctype in ARRAY_ELEMENT_WIDTH:
                    w = ARRAY_ELEMENT_WIDTH[ctype]
                    if ln % w:
                        raise RbfWriteError('text at %d: %r declares %r but %d B is not a whole '
                                            'number of %d-byte elements'
                                            % (at, owner.name, ctype, ln, w))
                    t.width = w
                    t.arr = [int.from_bytes(raw[i:i + w], 'little')
                             for i in range(0, ln, w)]
                    self._bump('typed_array_elements', len(t.arr))
                elif _is_string_payload(raw):
                    t.s = raw[:-1].decode('latin-1')
                else:
                    # ⛔ COUNTED, NEVER SILENT. A payload with no declared content type that is
                    # not a NUL-terminated printable string is a shape this model has not
                    # derived a width for. It is reproduced as raw bytes and reported as CARRIED
                    # - a carried region is not a measured one.
                    t.raw = raw
                    self._bump('text_carried_bytes', ln)
                    self._note('text payload undeclared and non-string (%d B, element %r)'
                               % (ln, owner.name))
                got = self._reemit_len(t, False)
                if got != p - at:
                    raise RbfWriteError('TEXT record at %d consumed %d B but the model re-emits '
                                        '%d - the field map has a hole or an overlap'
                                        % (at, p - at, got))
                owner.items.append(t)
                continue

            kind = tok >> 12
            idx = tok & 0x0FFF
            inline = False
            if idx == len(names):
                inline = True
                if p + 2 > n:
                    raise RbfWriteError('truncated name length at %d' % at)
                ln = struct.unpack_from('<H', blob, p)[0]
                p += 2
                if p + ln > n:
                    raise RbfWriteError('truncated name (%d B) at %d' % (ln, at))
                names.append(blob[p:p + ln].decode('latin-1'))
                p += ln
            elif idx > len(names):
                raise RbfWriteError('name index %d ahead of the table (%d) at %d'
                                    % (idx, len(names), at))
            if kind not in FIXED_PAYLOAD:
                raise RbfWriteError('unknown RBF type nibble 0x%X (%r) at %d'
                                    % (kind, names[idx], at))
            node = Node(names[idx], kind)
            node.inline = inline

            if kind == T_ELEMENT:
                if p + 6 > n:
                    raise RbfWriteError('truncated element header at %d' % at)
                node.reserved = struct.unpack_from('<I', blob, p)[0]
                node.nattr = struct.unpack_from('<H', blob, p + 4)[0]
                p += 6
                if node.reserved:
                    # UNPINNED meaning; 0 in all 13,115 elements `rbf2xml` measured. Re-encoded
                    # from the decoded word either way, and counted when it is not zero so a
                    # surprise is reported rather than absorbed.
                    self._bump('element_reserved_nonzero')
            elif kind == T_UINT32:
                if p + 4 > n:
                    raise RbfWriteError('truncated u32 at %d' % at)
                node.u32 = struct.unpack_from('<I', blob, p)[0]
                p += 4
            elif kind in (T_TRUE, T_FALSE):
                pass                                        # the value IS the nibble
            elif kind == T_FLOAT:
                if p + 4 > n:
                    raise RbfWriteError('truncated f32 at %d' % at)
                node.f32 = struct.unpack_from('<f', blob, p)[0]
                if struct.pack('<f', node.f32) != blob[p:p + 4]:
                    # A signalling-NaN payload that does not survive decode->encode. Reproduce
                    # the stored WORD and COUNT it rather than quietly rewriting the bits.
                    node.word = struct.unpack_from('<I', blob, p)[0]
                    self._bump('float_reencoded_as_word')
                p += 4
            elif kind == T_FLOAT3:
                if p + 12 > n:
                    raise RbfWriteError('truncated f32[3] at %d' % at)
                node.f3 = list(struct.unpack_from('<3f', blob, p))
                if struct.pack('<3f', *node.f3) != blob[p:p + 12]:
                    node.word = list(struct.unpack_from('<3I', blob, p))
                    self._bump('float3_reencoded_as_words')
                p += 12
            elif kind == T_STRING:
                if p + 2 > n:
                    raise RbfWriteError('truncated string length at %d' % at)
                ln = struct.unpack_from('<H', blob, p)[0]
                p += 2
                if p + ln > n:
                    raise RbfWriteError('truncated string (%d B) at %d' % (ln, at))
                node.text = blob[p:p + ln].decode('latin-1')
                p += ln

            got = self._reemit_len(node, inline)
            if got != p - at:
                raise RbfWriteError('record %r (nibble %d) at %d consumed %d B but the model '
                                    're-emits %d - the field map has a hole or an overlap'
                                    % (node.name, kind, at, p - at, got))

            if stack:
                stack[-1].items.append(node)
                named_seen[-1] += 1
            elif root is None:
                root = node
            else:
                raise RbfWriteError('second root record %r at %d' % (node.name, at))

            if kind == T_ELEMENT:
                stack.append(node)
                named_seen.append(0)

        if stack:
            raise RbfWriteError('%d element(s) never closed' % len(stack))
        if p != n:
            raise RbfWriteError('%d trailing byte(s)' % (n - p))
        if root is None:
            raise RbfWriteError('empty container')
        self.root = root
        self.file_names = names
        if len(set(names)) != len(names):
            # The write side re-derives the index from the NAME TEXT, so a table holding the same
            # text twice would collapse two indices into one. REFUSE and COUNT rather than emit a
            # file whose name indices are quietly wrong.
            raise RbfWriteError('name table holds %d duplicate name(s) - the first-use '
                                'derivation cannot address them'
                                % (len(names) - len(set(names))))

    @staticmethod
    def _content_type(owner):
        """The element's declared character-data type, read off its own attribute records."""
        seen = 0
        for it in owner.items:
            if isinstance(it, Text):
                continue
            if seen >= owner.nattr:
                break
            seen += 1
            if it.name == 'content' and it.kind == T_STRING:
                return it.text
        return None

    # ------------------------------------------------------------------ the derivation check
    def _walk_nodes(self):
        """Every Node in FILE ORDER (depth-first, body order). Iterative: the destruction
        manifests nest deeply enough that recursion is a real risk on the worst file."""
        out = []
        stack = [self.root]
        while stack:
            nd = stack.pop()
            out.append(nd)
            if nd.kind == T_ELEMENT:
                kids = [it for it in nd.items if not isinstance(it, Text)]
                stack.extend(reversed(kids))
        return out

    def _derive_names(self):
        """name -> index by FIRST-USE ORDER, plus the set of Nodes that must spell it inline."""
        index = {}
        order = []
        inline = set()
        for nd in self._walk_nodes():
            if nd.name not in index:
                index[nd.name] = len(order)
                order.append(nd.name)
                inline.add(id(nd))
        return index, order, inline

    def _check_name_derivation(self):
        """REFUSE unless the rebuilt name table matches the one the FILE spelled.

        ⭐ THIS IS WHAT MAKES THE NAME INDEX A DERIVED VALUE AND NOT A COPIED ONE. Without it the
        writer could re-emit whatever index it parsed and the round-trip would agree with itself.
        The check compares BOTH the table contents in order AND which records carry the inline
        name, so a first-use order this model gets wrong is an error, not a silent pass.
        """
        _index, order, inline = self._derive_names()
        if order != self.file_names:
            raise RbfWriteError('rebuilt name table (%d entries) disagrees with the file (%d) - '
                                'first divergence at %d'
                                % (len(order), len(self.file_names),
                                   next((i for i, (a, b) in
                                         enumerate(zip(order, self.file_names)) if a != b), -1)))
        for nd in self._walk_nodes():
            if nd.inline != (id(nd) in inline):
                raise RbfWriteError('record %r: file spells the name inline=%s but the '
                                    'first-use derivation says %s'
                                    % (nd.name, nd.inline, id(nd) in inline))

    # ------------------------------------------------------------------ the writer
    def _emit_text(self, out, tags, t):
        if t.s is not None:
            pay = t.s.encode('latin-1') + b'\x00'
            tag = T_VALUE
        elif t.arr is not None:
            pay = b''.join(int(v).to_bytes(t.width, 'little') for v in t.arr)
            tag = T_VALUE
        else:
            pay = t.raw
            tag = T_CARRIED
        out += struct.pack('<H', TOK_TEXT)
        tags += bytes([T_DERIVED]) * 2
        out += struct.pack('<I', len(pay))
        tags += bytes([T_DERIVED]) * 4                  # len() of the thing we rebuilt
        out += pay
        tags += bytes([tag]) * len(pay)

    def write(self, want_tags=False):
        """Rebuild the whole file. Every length prefix is COMPUTED as we go."""
        index, _order, inline_ids = self._derive_names()
        out = bytearray(MAGIC)
        tags = bytearray([T_DERIVED]) * 4               # the constant magic
        stack = [(self.root, 0)]
        while stack:
            it, phase = stack.pop()
            if isinstance(it, Text):
                self._emit_text(out, tags, it)
                continue
            if phase == 1:
                out += struct.pack('<H', TOK_END)
                tags += bytes([T_DERIVED]) * 2
                continue
            inline = id(it) in inline_ids
            out += struct.pack('<H', (it.kind << 12) | index[it.name])
            tags += bytes([T_VALUE]) * 2
            if inline:
                nb = it.name.encode('latin-1')
                out += struct.pack('<H', len(nb))
                tags += bytes([T_DERIVED]) * 2
                out += nb
                tags += bytes([T_VALUE]) * len(nb)
            k = it.kind
            if k == T_ELEMENT:
                out += struct.pack('<IH', it.reserved, it.nattr)
                tags += bytes([T_VALUE]) * 6
                stack.append((it, 1))
                for sub in reversed(it.items):
                    stack.append((sub, 0))
            elif k == T_UINT32:
                out += struct.pack('<I', it.u32)
                tags += bytes([T_VALUE]) * 4
            elif k in (T_TRUE, T_FALSE):
                pass
            elif k == T_FLOAT:
                if it.word is None:
                    out += struct.pack('<f', it.f32)
                    tags += bytes([T_VALUE]) * 4
                else:
                    out += struct.pack('<I', it.word)
                    tags += bytes([T_UNTYPED]) * 4
            elif k == T_FLOAT3:
                if it.word is None:
                    out += struct.pack('<3f', *it.f3)
                    tags += bytes([T_VALUE]) * 12
                else:
                    out += struct.pack('<3I', *it.word)
                    tags += bytes([T_UNTYPED]) * 12
            elif k == T_STRING:
                sb = it.text.encode('latin-1')
                out += struct.pack('<H', len(sb))
                tags += bytes([T_DERIVED]) * 2
                out += sb
                tags += bytes([T_VALUE]) * len(sb)
        if want_tags:
            return bytes(out), bytes(tags)
        return bytes(out)

    # ------------------------------------------------------------------ the measure
    def unreached(self):
        """(differing bytes, of which non-zero in the original).

        ⛔ THERE IS NO ZERO-FILL IN THIS CONTAINER. The image is a concatenation, not a sized
        buffer, so a dropped field does not leave a quiet zero hole - it shifts the whole tail and
        the difference count explodes. That is the intended loudness: this format cannot hide an
        omission behind padding the way a paged resource can.
        """
        got, orig = self.write(), self.blob
        n = min(len(got), len(orig))
        try:
            import numpy as _np
            a = _np.frombuffer(got[:n], dtype=_np.uint8)
            b = _np.frombuffer(orig[:n], dtype=_np.uint8)
            d = a != b
            bad = int(d.sum()) + abs(len(got) - len(orig))
            nz = int(((b != 0) & d).sum())
        except ImportError:
            bad = nz = 0
            for i in range(n):
                if got[i] != orig[i]:
                    bad += 1
                    if orig[i] != 0:
                        nz += 1
            bad += abs(len(got) - len(orig))
        return bad, nz

    # ------------------------------------------------------------------ byte accounting
    def regions(self):
        """The exact VALUE / UNTYPED / DERIVED / CARRIED / ZERO split of the rebuilt image.

        ⭐ DISCLOSURE, NOT DECORATION. Byte identity alone cannot tell a rebuilt region from a
        copied one, so every byte is tagged AS IT IS PRODUCED and the tags are counted. `.ymt`
        round-tripped 2,326/2,326 once with 11.66% of the image carried verbatim, and that 100%
        was worthless.

        ZERO is reported for symmetry with the other lanes and is structurally 0 here: this
        writer never allocates a byte it does not write.
        """
        img, tags = self.write(want_tags=True)
        out = {'total': len(img), 'value': 0, 'value_untyped': 0,
               'derived': 0, 'carried': 0, 'zero_fill': 0}
        try:
            import numpy as _np
            cnt = _np.bincount(_np.frombuffer(tags, dtype=_np.uint8), minlength=5)
            out['zero_fill'] = int(cnt[0])
            out['value'] = int(cnt[T_VALUE])
            out['value_untyped'] = int(cnt[T_UNTYPED])
            out['derived'] = int(cnt[T_DERIVED])
            out['carried'] = int(cnt[T_CARRIED])
        except ImportError:
            key = {0: 'zero_fill', T_VALUE: 'value', T_UNTYPED: 'value_untyped',
                   T_DERIVED: 'derived', T_CARRIED: 'carried'}
            for t in tags:
                out[key[t]] += 1
        return out

    # ------------------------------------------------------------------ structure census
    def stats(self):
        """Per-file structure counts, so a population run can say what it actually walked."""
        import collections
        c = collections.Counter()
        c['names'] = len(self.file_names)
        for nd in self._walk_nodes():
            c['nodes'] += 1
            c['kind_%d' % nd.kind] += 1
            if nd.kind == T_ELEMENT:
                c['attrs'] += nd.nattr
                for it in nd.items:
                    if isinstance(it, Text):
                        c['text'] += 1
                        if it.arr is not None:
                            c['text_typed_array'] += 1
                        elif it.s is not None:
                            c['text_string'] += 1
                        else:
                            c['text_carried'] += 1
        return c


# ---------------------------------------------------------------------- must-fail control
# BYTE IDENTITY CANNOT TELL A PINNED CLAIM FROM A COPIED ONE. The answer is a control that MUST
# FAIL: corrupt the MODEL - not the file - and demand the rebuilt image stops matching. A mutation
# that is NOT caught names a region the measure cannot see.
#
# The classes attack DIFFERENT claims, because they fail differently:
#   value     - a decoded scalar's value (u32 / f32 / f32[3] / string / typed-array element).
#   name      - a name string. Catches "is the name table rebuilt, or replayed?" It also moves the
#               inline u16 length, so it tests the computed length prefix at the same time.
#   nameorder - the FIRST-USE derivation itself: move a subtree so a different record becomes the
#               first user of a name. If the index were carried rather than derived, this would
#               not move the image.
#   reserved  - the element's unpinned u32. Catches "is it written, or skipped?"
#   nibble    - TRUE <-> FALSE. The value lives in the TYPE, not in a byte; if the nibble were
#               carried the image could not notice.
#   nattr     - the declared attribute count.
#   drop      - a whole item removed from an element body. Catches "does this record's region
#               actually get written by the model?"
#   text      - a character-data payload.
# ⛔ Unlike `pso_write` there is NO zero-region exclusion here, and that is a property of the
# container, not a choice: this image is a concatenation with no zero-fill, so every modelled byte
# is a byte the comparison can speak to.
def _pick(xs, n):
    if not xs:
        return []
    if len(xs) <= n:
        return list(xs)
    step = max(1, len(xs) // n)
    return [xs[i * step] for i in range(n)]


def _all_items(m):
    """(parent, position) for every item in every element body."""
    out = []
    for nd in m._walk_nodes():
        if nd.kind == T_ELEMENT:
            for i in range(len(nd.items)):
                out.append((nd, i))
    return out


def control(m):
    """Run the must-fail battery. Returns (caught, total, {class: [caught, total]}).

    Only meaningful on a file that round-trips EXACTLY - "the image moved" is not evidence if the
    image was already wrong - so the caller must check that first.
    """
    base = m.write()
    nodes = m._walk_nodes()
    per = {}
    caught = total = 0

    def run(kind, apply_fn, undo_fn):
        nonlocal caught, total
        try:
            apply_fn()
        except Exception:
            return
        try:
            try:
                got = m.write()
            except Exception:
                got = None
            hit = (got is None) or (got != base)
            total += 1
            caught += 1 if hit else 0
            q = per.setdefault(kind, [0, 0])
            q[1] += 1
            q[0] += 1 if hit else 0
        finally:
            undo_fn()

    # ---- value: one of each scalar shape that the file actually carries
    for nd in _pick([x for x in nodes if x.kind == T_UINT32], 2):
        old = nd.u32
        run('value', lambda nd=nd: setattr(nd, 'u32', nd.u32 ^ 1),
            lambda nd=nd, old=old: setattr(nd, 'u32', old))
    for nd in _pick([x for x in nodes if x.kind == T_FLOAT and x.word is None], 2):
        old = nd.f32
        run('value', lambda nd=nd: setattr(nd, 'f32', (nd.f32 or 0.0) + 1.5),
            lambda nd=nd, old=old: setattr(nd, 'f32', old))
    for nd in _pick([x for x in nodes if x.kind == T_FLOAT3 and x.word is None], 2):
        old = list(nd.f3)
        run('value', lambda nd=nd: nd.f3.__setitem__(0, nd.f3[0] + 1.5),
            lambda nd=nd, old=old: setattr(nd, 'f3', list(old)))
    for nd in _pick([x for x in nodes if x.kind == T_STRING and x.text], 2):
        old = nd.text
        run('value', lambda nd=nd: setattr(nd, 'text', chr((ord(nd.text[0]) ^ 1) & 0x7F)
                                            + nd.text[1:]),
            lambda nd=nd, old=old: setattr(nd, 'text', old))
    texts = [t for nd in nodes if nd.kind == T_ELEMENT
             for t in nd.items if isinstance(t, Text)]
    for t in _pick([x for x in texts if x.arr], 2):
        old = list(t.arr)
        run('value', lambda t=t: t.arr.__setitem__(0, t.arr[0] ^ 1),
            lambda t=t, old=old: setattr(t, 'arr', list(old)))
    # ---- text: a string payload's bytes (also moves the computed u32 length when it grows)
    for t in _pick([x for x in texts if x.s], 2):
        old = t.s
        run('text', lambda t=t: setattr(t, 's', t.s + 'X'),
            lambda t=t, old=old: setattr(t, 's', old))
    # ---- name: the name text of a record (moves the inline u16 length too)
    for nd in _pick(nodes, 2):
        old = nd.name
        run('name', lambda nd=nd: setattr(nd, 'name', nd.name + '_Q'),
            lambda nd=nd, old=old: setattr(nd, 'name', old))
    # ---- reserved / nattr / nibble on elements
    els = [x for x in nodes if x.kind == T_ELEMENT]
    for nd in _pick(els, 2):
        old = nd.reserved
        run('reserved', lambda nd=nd: setattr(nd, 'reserved', nd.reserved ^ 1),
            lambda nd=nd, old=old: setattr(nd, 'reserved', old))
    for nd in _pick(els, 2):
        old = nd.nattr
        run('nattr', lambda nd=nd: setattr(nd, 'nattr', nd.nattr + 1),
            lambda nd=nd, old=old: setattr(nd, 'nattr', old))
    for nd in _pick([x for x in nodes if x.kind in (T_TRUE, T_FALSE)], 2):
        old = nd.kind
        run('nibble', lambda nd=nd: setattr(nd, 'kind',
                                            T_FALSE if nd.kind == T_TRUE else T_TRUE),
            lambda nd=nd, old=old: setattr(nd, 'kind', old))
    # ---- drop: remove one item from a body
    items = _all_items(m)
    for parent, i in _pick(items, 2):
        saved = list(parent.items)
        run('drop', lambda p=parent, i=i: p.items.pop(i),
            lambda p=parent, s=saved: setattr(p, 'items', list(s)))
    # ---- nameorder: reverse a body, so a different record first uses a name
    for parent, _i in _pick([x for x in items if len(x[0].items) > 1], 2):
        saved = list(parent.items)
        run('nameorder', lambda p=parent: setattr(p, 'items', list(reversed(p.items))),
            lambda p=parent, s=saved: setattr(p, 'items', list(s)))
    return caught, total, per


# ---------------------------------------------------------------------- refusal self-test
# ⛔ A CHECK THAT HAS NEVER FIRED IS NOT KNOWN TO WORK. This file carries three REFUSALS whose
# whole value is that they can reject - `_check_type_table` at import, `_reemit_len`'s per-record
# width comparison in `parse`, and `_check_name_derivation`. All three were silent across 200/200
# files, which is the correct outcome and also indistinguishable from a check that cannot fire.
# So each one is fired DELIBERATELY here, against a hand-built container, and the test fails if a
# refusal does NOT happen.
def _mini_rbf():
    """The smallest well-formed RBF0 document that exercises names, an element and a text record.

    Built from the layout, not copied from a file: <root><a>hi</a><a /></root>, where the second
    <a> is a BACK-REFERENCE to name index 1 and carries no inline name. That back-reference is
    what makes the name-derivation check meaningful on this fixture.
    """
    out = bytearray(MAGIC)

    def node(kind, idx, name=None):
        out.extend(struct.pack('<H', (kind << 12) | idx))
        if name is not None:
            nb = name.encode('latin-1')
            out.extend(struct.pack('<H', len(nb)))
            out.extend(nb)

    node(T_ELEMENT, 0, 'root')
    out.extend(struct.pack('<IH', 0, 0))
    node(T_ELEMENT, 1, 'a')
    out.extend(struct.pack('<IH', 0, 0))
    out.extend(struct.pack('<H', TOK_TEXT))
    out.extend(struct.pack('<I', 3))
    out.extend(b'hi\x00')
    out.extend(struct.pack('<H', TOK_END))
    node(T_ELEMENT, 1)                      # back-reference, no inline name
    out.extend(struct.pack('<IH', 0, 0))
    out.extend(struct.pack('<H', TOK_END))
    out.extend(struct.pack('<H', TOK_END))
    return bytes(out)


def selftest():
    """Fire every refusal in this file and REFUSE if one of them does not fire. ASCII only."""
    fixture = _mini_rbf()
    checks = []

    m = RbfRT(fixture)
    ok = (m.write() == fixture)
    checks.append(('fixture round-trips', ok))
    reg = m.regions()
    checks.append(('fixture carries nothing', reg['carried'] == 0 and reg['zero_fill'] == 0))

    # 1. the per-record width check must reject a stream whose field map has a hole
    bad = bytearray(fixture)
    bad[4 + 2 + 2] = ord('r')               # lengthen nothing, corrupt the inline name length
    bad[4 + 2] = 9                          # name length 9 where 4 bytes follow -> desync
    try:
        RbfRT(bytes(bad))
        checks.append(('_reemit_len / parse REFUSES a desynced stream', False))
    except RbfWriteError:
        checks.append(('_reemit_len / parse REFUSES a desynced stream', True))

    # 2. the name-derivation check must reject a tree whose first-use order moved
    m2 = RbfRT(fixture)
    m2.root.items.reverse()                 # the back-reference now comes first
    try:
        m2._check_name_derivation()
        checks.append(('_check_name_derivation REFUSES a moved first-use order', False))
    except RbfWriteError:
        checks.append(('_check_name_derivation REFUSES a moved first-use order', True))

    # 3. the import-time type table must reject a hole in the nibble space
    saved = dict(FIXED_PAYLOAD)
    try:
        del FIXED_PAYLOAD[T_FLOAT3]
        try:
            _check_type_table()
            checks.append(('_check_type_table REFUSES a hole in the nibble space', False))
        except ImportError:
            checks.append(('_check_type_table REFUSES a hole in the nibble space', True))
    finally:
        FIXED_PAYLOAD.clear()
        FIXED_PAYLOAD.update(saved)

    # 4. the must-fail battery must catch every mutation on the fixture
    caught, total, _per = control(RbfRT(fixture))
    checks.append(('must-fail battery on the fixture: %d/%d' % (caught, total),
                   total > 0 and caught == total))

    print('REFUSAL SELF-TEST - a check that never fires is not known to work')
    print('SAMPLE SIZE: 1 hand-built fixture (%d B), %d checks' % (len(fixture), len(checks)))
    for label, ok in checks:
        print('  %-56s %s' % (label, 'PASS' if ok else 'FAIL'))
    bad_n = sum(1 for _l, ok in checks if not ok)
    print('RESULT: %d / %d passed' % (len(checks) - bad_n, len(checks)))
    return 1 if bad_n else 0


# ---------------------------------------------------------------------- lane entry points
def read_rbf_any(src):
    blob = bytes(src) if isinstance(src, (bytes, bytearray)) else open(src, 'rb').read()
    return RbfRT(blob)


read_ymt_rbf = read_rbf_any
read_ymf_rbf = read_rbf_any
read_rbf = read_rbf_any


def _main():
    """Population measure + byte accounting + the must-fail control, in one command.

        python quarry/rbf_write.py --all

    Prints SAMPLE SIZE for every lane and REFUSES on an empty sample. ASCII output only.
    """
    import argparse
    import collections
    _sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), 'tools'))
    import roundtrip_coverage as RC
    LANES = ('ymt_rbf', 'ymf_rbf')
    ap = argparse.ArgumentParser()
    ap.add_argument('--lane', choices=LANES)
    ap.add_argument('--all', action='store_true')
    ap.add_argument('--limit', type=int, default=9000)
    ap.add_argument('--control', type=int, default=200)
    ap.add_argument('--selftest', action='store_true',
                    help='fire every refusal in this file and REFUSE if one does not fire')
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if not a.lane and not a.all:
        ap.error('pass --lane <name> or --all')
    lanes = LANES if a.all else (a.lane,)
    print('RBF0 CONTAINER - ROUND-TRIP AT POPULATION (the primary measure)')
    print('whole file -> value model -> written back -> compare.')
    bad = 0
    for ln in lanes:
        _mod, _fn, arcs = RC.LANES[ln]
        rep = {}
        files = RC.harvest(ln, arcs, a.limit, cap=0, gate=RC.GATES.get(ln), report=rep)
        print('')
        print('lane %-9s SAMPLE SIZE: %d   [NO CAP (population draw)]' % (ln, len(files)))
        print('  container gate  : %d OTHER-CONTAINER turned away (a different format, NOT a pass'
              ' for them)' % rep.get('rejected', 0))
        if not files:
            print('  REFUSING: empty sample - a harness with no subject cannot report coverage.')
            bad += 1
            continue
        exact = tot = 0
        cov = []
        acc = collections.Counter()
        st = collections.Counter()
        err = collections.Counter()
        notes = collections.Counter()
        cc = ct = nctl = 0
        cper = {}
        worst = None
        for nm, blob in files:
            try:
                m = RbfRT(blob)
                n, _nz = m.unreached()
            except Exception as ex:
                err['%s: %s' % (type(ex).__name__, str(ex)[:60])] += 1
                continue
            tot += 1
            c = 100.0 * (m.size - n) / m.size
            cov.append(c)
            if n == 0:
                exact += 1
            if worst is None or c < worst[0]:
                worst = (c, nm)
            for k, v in m.regions().items():
                acc[k] += v
            for k, v in m.stats().items():
                st[k] += v
            for k, v in m.notes.items():
                notes[k] += v
            if nctl < a.control and n == 0:
                nctl += 1
                a1, b1, p1 = control(m)
                cc += a1
                ct += b1
                for k, v in p1.items():
                    q = cper.setdefault(k, [0, 0])
                    q[0] += v[0]
                    q[1] += v[1]
        if not tot:
            print('  REFUSING: every file errored - %s' % dict(err))
            bad += 1
            continue
        print('  EXACT round-trip: %d / %d (%.4f%%)' % (exact, tot, 100.0 * exact / tot))
        print('  mean coverage   : %.6f%%   min %.4f%% (%s)'
              % (sum(cov) / len(cov), worst[0], worst[1]))
        t = acc['total'] or 1
        print('  BYTE ACCOUNTING over %d files, %d bytes:' % (tot, acc['total']))
        for k in ('value', 'value_untyped', 'derived', 'carried', 'zero_fill'):
            print('    %-14s %12d  %6.3f%%' % (k, acc[k], 100.0 * acc[k] / t))
        print('    carried       = could NOT have been rejected by this measure.')
        print('  STRUCTURE WALKED: %s' % dict(st.most_common()))
        if ct:
            print('  MUST-FAIL CONTROL on %d files: %d / %d mutations caught (%.2f%%)'
                  % (nctl, cc, ct, 100.0 * cc / ct))
            for k in sorted(cper):
                print('    %-10s %d / %d' % (k, cper[k][0], cper[k][1]))
        else:
            print('  MUST-FAIL CONTROL: NOT RUN - no exactly-round-tripping file to mutate.')
        if err:
            print('  REFUSALS (counted, named): %s' % dict(err))
        if notes:
            print('  model notes     : %s' % dict(notes.most_common(6)))
    return 1 if bad else 0


if __name__ == '__main__':
    _sys.exit(_main())
