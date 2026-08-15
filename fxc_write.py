"""fxc_write - ROUND-TRIP WRITER for .fxc (rage compiled shader effect, 'rgxe').

    original binary -> value model -> written back -> MUST reproduce the original bytes

WHY (maintainer ruling 2026-08-13): round-trip byte identity is the primary measure; parity
against a second exporter is a cross-check. Until today this lane had a READER (`fxc2xml.py`) and
NO WRITER, which under that ruling makes it UNMEASURED, not passing - 1,446 files, 407.8 MB of
payload, with no number attached to them.

⭐ THIS WRITER IS SEQUENTIAL, AND THAT IS THE POINT. `.fxc` is NOT an RSC7 resource: it is a flat
byte stream with no pointers, no page table and no compressed container, so there is no
"inflated system segment" to scope down to and no header full of tagged pointers to carry. The
image is built by APPEND from offset 0. That is a STRONGER shape than the zero-filled image the
`ynd`/`yvr` writers use:

    a zero-filled image can absorb an unmodelled byte (it stays zero and shows up as ONE
    difference); an appended image CANNOT. Miss a field, mis-size a string, drop a record and
    every byte after it SHIFTS - the file diverges from that offset to the end and the length
    changes too. There is no offset at which this writer can copy original bytes into place,
    which is exactly the self-fulfilling claim the vault's first law warns about.

⛔ THE FIRST LAW: a claimed region is evidence ONLY IF A WRONG CLAIM COULD HAVE BEEN REJECTED.
So `spans()` accounts for every byte this writer emits, in four kinds, and the caller is expected
to quote the split next to the coverage figure:
    VALUE    - re-encoded from a decoded value (scalar, string text, float list)
    DERIVED  - COMPUTED from the model's shape and never read from the file: every array count,
               every string length byte, every bytecode size word, the magic. A wrong model
               shape therefore writes a wrong count and the round-trip rejects it.
    CARRIED  - opaque bytes copied verbatim. In this lane that is the DXBC shader bytecode and
               NOTHING else: a nested Microsoft container, out of scope for a RAGE format
               decode. It is length-pinned (the u32 before it is DERIVED from len()) and
               position-pinned (sequential emission), so a wrong length or a lost blob still
               fails - but its INTERNAL bytes are not evidence about our model, and they are
               reported separately for exactly that reason.
    ZERO     - 0 bytes, always, by construction. Nothing is pre-allocated.

⭐ THE STRING LAW IS WHERE A WRITER EARNS ITS KEEP. `fxc2xml._R.s()` reads `u8 n` then
`raw.split(b'\\0')[0]` - it TRUNCATES at the first NUL and silently discards anything after it.
A reader cannot see that; it just yields a clean name. This writer re-encodes as
`u8(len(text)+1) | text | NUL`, so any file that pads a string, or stores a length that is not
minimal, DIVERGES. Measured at population 2026-08-15: 1,446/1,446 byte-exact, so no shipped .fxc
does either - the truncation is lossless on this game, and that is now a measured fact rather
than an assumption baked into a reader.

MEASURED 2026-08-15, POPULATION (all 1,446 .fxc in the game, `common.rpf` + `update\\update2.rpf`;
reproduce with `tools/roundtrip_coverage.py --lane fxc --limit 2000 --cap 0`):
    byte-exact 1,446 / 1,446 (100.0000%)   mean coverage 100.0000%   min 100.0000%
    byte account, 407,764,671 B emitted:
        VALUE   50,756,407 B  12.45%      DERIVED  3,108,088 B   0.76%
        CARRIED 353,900,176 B 86.79%      ZERO             0 B   0.00%
        7,387,112 modelled fields re-encoded | 44,989 opaque DXBC blobs carried
    must-fail control: 8 mutations, 1,294 applied, 1,294 caught = 100.0000%.

⚠ QUOTE BOTH NUMBERS OR NEITHER. 86.79% of this lane BY BYTE is DXBC bytecode - a nested
Microsoft container we do not claim to decode - so "fxc round-trips 100%" on its own would be
the exact overclaim this vault's second law exists to stop. BY FIELD the picture inverts:
7,387,112 modelled fields are re-encoded from decoded values against 44,989 carried blobs, and
every one of those blobs is length-pinned (`truncate a DXBC blob by 4 B` is caught 181/181) and
position-pinned. The lane is both things at once and the honest report says both.
ASCII output only.
"""
import os
import struct
import sys as _sys

_sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fxc2xml  # noqa: E402

MAGIC = fxc2xml.MAGIC
GS_GROUP = fxc2xml.GS_GROUP
VER_GROUPS = fxc2xml.VER_GROUPS

VALUE, DERIVED, CARRIED = 'value', 'derived', 'carried'


class _W(object):
    """Append-only emitter that ACCOUNTS FOR EVERY BYTE IT WRITES.

    Every put goes through a `kind`, so the byte split is produced by the act of writing rather
    than asserted afterwards by a human reading the code. There is deliberately no `seek`: this
    class cannot place bytes at an offset, so it cannot make an unpinned claim.
    """

    def __init__(self):
        self.b = bytearray()
        self.acct = {VALUE: 0, DERIVED: 0, CARRIED: 0}
        self.fields = 0          # modelled scalars/strings re-encoded from a decoded value
        self.blobs = 0           # opaque regions carried verbatim

    def raw(self, data, kind):
        self.b += data
        self.acct[kind] += len(data)
        if kind == CARRIED:
            self.blobs += 1
        else:
            self.fields += 1

    def u8(self, v, kind=VALUE):
        self.raw(struct.pack('<B', v), kind)

    def u16(self, v, kind=VALUE):
        self.raw(struct.pack('<H', v), kind)

    def u32(self, v, kind=VALUE):
        self.raw(struct.pack('<I', v), kind)

    def f32(self, v, kind=VALUE):
        self.raw(struct.pack('<f', v), kind)

    def s(self, text):
        """`u8 length INCLUDING the NUL` then the bytes. The LENGTH is DERIVED from the decoded
        text - never carried - so a name we shortened, lengthened or lost fails immediately."""
        raw = text.encode('latin-1') + b'\0'
        if len(raw) > 255:
            raise ValueError('string %r does not fit a uint8 length' % text[:40])
        self.u8(len(raw), DERIVED)
        self.raw(raw, VALUE)

    def count(self, seq):
        """Array counts are DERIVED from len(). This is what makes a dropped record impossible
        to hide: the count and the records disagree and every later byte shifts."""
        n = len(seq)
        if n > 255:
            raise ValueError('count %d does not fit a uint8' % n)
        self.u8(n, DERIVED)
        return n


def _wr_param(w, p):
    name, t, val = p
    w.s(name)
    w.u8(t)
    if t == 0:
        w.u32(val)
    elif t == 1:
        w.f32(val)
    elif t == 2:
        w.s(val)
    else:
        raise ValueError('param type %d has no witnessed payload size' % t)


def _wr_shader(w, sh, gi):
    w.s(sh['name'])
    w.count(sh['variables'])
    for n in sh['variables']:
        w.s(n)
    w.count(sh['buffers'])
    for n, slot in sh['buffers']:
        w.s(n)
        w.u16(slot)
    if gi == GS_GROUP:
        w.u8(sh['extra'])
    # ⭐ SIZE IS DERIVED FROM THE BLOB, NOT COPIED FROM THE FILE. The bytecode itself is the one
    # region this writer carries verbatim; pinning its length to len(data) is what stops that
    # carry from being an unpinned claim.
    w.u32(len(sh['data']), DERIVED)
    if sh['data']:
        w.raw(sh['data'], CARRIED)
    if sh['size'] and gi in VER_GROUPS:
        w.u8(sh['major'])
        w.u8(sh['minor'])


def _wr_cbuffer(w, cb):
    w.u32(cb['size'])
    for s in cb['slots']:
        w.u16(s)
    w.s(cb['name'])


def _wr_variable(w, v):
    w.u8(v['type'])
    w.u8(v['count'])
    w.u8(v['slot'])
    w.u8(v['group'])
    w.s(v['name1'])
    w.s(v['name2'])
    w.u8(v['offset'])
    w.u8(v['variant'])
    w.u16(v['reserved'])
    w.u32(v['bufhash'])
    w.count(v['params'])
    for p in v['params']:
        _wr_param(w, p)
    w.count(v['values'])
    for f in v['values']:
        # ⛔ RE-ENCODED FROM THE DECODED FLOAT, and that is a real risk this writer accepts on
        # purpose: a float32 that is a signalling NaN or a denormal could in principle not
        # survive the trip through a Python float. Measured over all 1,446 files it does -
        # 1,446/1,446 byte-exact - so the round-trip is what proves the decode is lossless.
        w.f32(f)


class Fxc(object):
    """The value model of one .fxc plus its re-serialisation."""

    def __init__(self, blob):
        self.orig = bytes(blob)
        self.size = len(self.orig)
        self.d = fxc2xml.parse(self.orig)   # REFUSES unless the parse consumes the file EXACTLY
        self._img = None
        self._acct = None
        # `.res` shim so `tools/roundtrip_population_all.py` (which reaches for `m.res.sys` on a
        # single-image lane) grades this lane without a special case. Same bytes, one name.
        self.res = type('_S', (), {'sys': self.orig, 'gfx': b''})()

    def write(self):
        if self._img is None:
            w = _W()
            d = self.d
            w.raw(MAGIC, DERIVED)          # validated at parse; a different magic is REFUSED
            w.u32(d['vertex_type'])
            w.count(d['preset'])
            for p in d['preset']:
                _wr_param(w, p)
            for gi in range(6):
                w.count(d['groups'][gi])
                for sh in d['groups'][gi]:
                    _wr_shader(w, sh, gi)
            for cbs, vs in ((d['cbuffers1'], d['variables1']),
                            (d['cbuffers2'], d['variables2'])):
                w.count(cbs)
                for cb in cbs:
                    _wr_cbuffer(w, cb)
                w.count(vs)
                for v in vs:
                    _wr_variable(w, v)
            w.count(d['techniques'])
            for name, passes in d['techniques']:
                w.s(name)
                w.count(passes)
                for idx, params in passes:
                    if len(idx) != 6:
                        raise ValueError('pass carries %d shader indices, expected 6' % len(idx))
                    for i in idx:
                        w.u8(i)
                    w.count(params)
                    for ptype, pval in params:
                        w.u32(ptype)
                        w.u32(pval)
            self._img = bytes(w.b)
            self._acct = dict(w.acct, fields=w.fields, blobs=w.blobs)
        return self._img

    def spans(self):
        """{value, derived, carried, zero, fields, blobs} - THE BYTE ACCOUNT.

        ⭐ DISCLOSURE, NOT DECORATION. Byte identity cannot tell a rebuilt region from a copied
        one, so a passing lane must publish how much of itself could never have failed.
        `zero` is 0 by construction here: an append-only emitter pre-allocates nothing, so there
        is no unreached region to fill - a missed field shifts the stream instead.
        """
        self.write()
        a = dict(self._acct)
        a['zero'] = 0
        a['total'] = a[VALUE] + a[DERIVED] + a[CARRIED]
        return a

    def exact(self):
        """Byte-EXACT means byte-exact: same LENGTH and same bytes.

        Length is checked explicitly because a prefix-style comparison over min(len) would score
        a truncated rebuild as perfect over everything it did emit.
        """
        return self.write() == self.orig

    def unreached(self):
        """(differing_bytes, non_zero_differing) - the shape `roundtrip_coverage` expects.

        For an append-only writer this is a DIVERGENCE count, not a gap count, and A LENGTH
        MISMATCH IS CHARGED IN FULL: bytes we never emitted are bytes we did not reproduce, and
        a comparison over min(len) would score a truncated rebuild as perfect over its prefix.

        The compare is the bigint XOR trick `roundtrip_population_all.same_bytes` uses, for its
        reason: a per-byte Python loop over this lane's 407.8 MB is ~100x slower and turns a
        two-minute population run into an afternoon.
        """
        got, orig = self.write(), self.orig
        n = min(len(got), len(orig))
        if n:
            x = int.from_bytes(got[:n], 'little') ^ int.from_bytes(orig[:n], 'little')
            same = x.to_bytes(n, 'little').count(0)
        else:
            same = 0
        bad = (n - same) + abs(len(got) - len(orig))
        if not bad:
            return 0, 0
        # The NON-ZERO share of a divergence - data we dropped, as opposed to padding we did not
        # have to understand. Only walked when something already failed, so the slow exact path
        # is fine here and the fast path above stays honest.
        nz = sum(1 for i in range(n) if got[i] != orig[i] and orig[i] != 0)
        nz += sum(1 for i in range(n, len(orig)) if orig[i] != 0)
        return bad, nz

    def first_diff(self):
        got = self.write()
        n = min(len(got), len(self.orig))
        for i in range(n):
            if got[i] != self.orig[i]:
                return i
        return None if len(got) == len(self.orig) else n


def read_fxc(src):
    blob = bytes(src) if isinstance(src, (bytes, bytearray)) else open(src, 'rb').read()
    return Fxc(blob)
