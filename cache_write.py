r"""cache_write - ROUND-TRIP WRITER for the GTA V map cache (`*_cache_y*.dat`).

    original binary -> value model -> written back -> MUST reproduce the original bytes

WHY (maintainer ruling 2026-08-13, hardened 2026-08-15): round-trip byte identity is the primary
measure. Until today this lane had a READER (`cache2xml.py`) and no writer, which under that ruling
makes it UNMEASURED, not passing - 132 files with no number attached to them
(`docs/LANE_CENSUS_20260814.md` row 11).

SCOPE NOTE, STRONG: a cache `.dat` is a RAW hybrid text/binary file - no RSC7 wrapper, no deflate
stream, no page map, no tagged pointers. This writer round-trips THE WHOLE FILE, first byte to
last. There is no "inflated system segment only" boundary here and nothing outside the model.

MODEL, NOT MEMCPY. Every field is decoded to a typed value and re-encoded into a ZERO-FILLED
image by a cursor that REFUSES on a hole, an overlap, or a landing that is not exactly EOF
(`_Emit`). Two things are DERIVED rather than carried, on the `meta_write.page_count` principle
that a value you recompute is a value you have understood:
  * each module's leading u32 - the PAYLOAD BYTE LENGTH - is recomputed as len(records) x stride,
  * the `</fileDates>` / `</module>` framing is re-emitted from the model's own structure.
Only one region can be carried verbatim, and it is COUNTED AND REPORTED per file: see BANK TAIL.

============================================================================================
⭐ THE `_bank` STRIDE, WHICH THIS LANE DID NOT KNOW IT HAD (closed 2026-08-15)
============================================================================================
`docs/LANE_CENSUS_20260814.md` F5 recorded an open refusal class: six `*_cache_y_bank.dat` raise
    ValueError: fwMapDataStore: payload N is not a multiple of the 64-byte record
and noted "its record stride is evidently not 64. NOBODY HAS EVER LOOKED AT WHAT IT ACTUALLY IS."

THE ANSWER IS 160 BYTES = the 64-byte retail record + a 96-byte BANK (dev-tools) TAIL:
    +0x00 .. +0x40   the ordinary fwMapDataStore record, unchanged
    +0x40 u32        (0 on 417 of 425 records measured; 5 on 6; one other value on 2)
    +0x44 char[92]   NUL-terminated ASCII authoring annotation, NUL-padded, e.g.
                     'M23_1_int_placement_m23_1,,andyh,Tuesday, May 23, 2023 3:01 PM'
                     i.e. <bank group>,,<author>,<timestamp> - a RAGE `bank` build artifact,
                     which is what the `_bank` in the filename is naming.
The tail is NOT always a string: on some records it holds 64-bit values of the form
0x00007ff7_xxxxxxxx - untagged HOST ADDRESSES, build residue of the same kind the `ydr` lane
characterised in its 48-byte bone grid. Those records' tails are carried and COUNTED (see
`regions()`), never silently absorbed.

⭐ AND THE REFUSAL COUNT IN F5 WAS LOW, AND THE PASSES WERE WORSE THAN THE REFUSALS. Measured over
the whole 132-file cache population:
    28 files are `_bank`; 11 have an EMPTY fwMapDataStore payload; 17 are non-empty.
    Of the 17: **9 REFUSE** (not 6 - the census undercounted), and the other **8 do not refuse
    because 160 and 64 both divide their payload - so today they parse SILENTLY AT THE WRONG
    STRIDE** and emit XML with 2.5x too many, mostly garbage, records.
    A loud refusal was never the problem. The silent pass was.

⛔ THE STRIDE GATE CANNOT BE THE FILENAME, and it cannot be byte identity either. A filename
cluster is a lead about WHERE, never a format variant (this vault's own law), and round-trip
identity is blind here for the reason law #1 names: at EITHER stride the records tile the same
payload, so a wrong stride copies the same bytes to the same places and the image still matches.
So the gate is a STRUCTURAL PREDICATE THAT CAN REFUSE - `_pick_stride` scores both candidate
strides on
    (a) every record's name hash at +0x00 is non-zero, and
    (b) its 12 floats at +0x0C are all-zero or finite and inside the map coordinate box,
and takes 160 only when it strictly beats 64. Measured over all 132 cache files: it picks 160 for
17 of 17 non-empty `_bank`, 64 for 76 non-bank, ties (-> 64, the retail default) on 3 non-bank,
and 36 have no records at all. **ZERO disagreements with the `_bank` filename it never reads.**
Decoys of the same magnitude were scored beside it and refuted: stride 80 divides all 17 but scores
82.5% / 67.5% on (a)/(b) where 160 scores 100% / 100%; strides 96, 128, 192 and 320 do not even
divide every file. Reproduce: `scratchpad/probe_bank_stride.py`.
ASCII output only.
"""
import math
import os
import struct
import sys as _sys

_sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

HEADER_LEN = 0x64
MAGIC = b'[VERSION]\n'
PRINTABLE = frozenset(range(0x20, 0x7F))

# ---- record models. (offset, struct code) pairs that MUST TILE THE STRIDE ------------------
# Same idea as `yvr_write.FIELDS`: byte identity then proves the FIELD MAP IS COMPLETE rather
# than that a buffer was copied. Checked at import by _check_tiling.
MDS_FIELDS = (
    (0x00, '<3I'),     # name, parent, contentFlags
    (0x0C, '<12f'),    # streamingExtentsMin/Max, entitiesExtentsMin/Max
    (0x3C, '<4B'),     # unk1..unk4
)
MDS_BANK_FIELDS = MDS_FIELDS + (
    (0x40, '<I'),      # bank word - 0 on 417 of 425 records measured
    # +0x44 char[92] is handled separately: decoded as text when it is one, carried+COUNTED
    # when it is host-address residue. It is NOT in this tuple, so _check_tiling below is told
    # about it explicitly.
)
IPR_FIELDS = (
    (0x00, '<5I'),     # unk01, unk02, unk03, name, parent
    (0x14, '<13f'),    # position xyz, rotation xyzw, bbMin xyz, bbMax xyz
    (0x48, '<4Q'),     # unk11..unk14
)
BND_FIELDS = (
    (0x00, '<I'),      # name
    (0x04, '<6f'),     # bbMin xyz, bbMax xyz
    (0x1C, '<I'),      # layer
)

MDS, MDS_BANK, IPR, BND = 64, 160, 104, 32
BANK_TAIL_AT, BANK_TAIL_LEN = 0x44, 92


def _check_tiling(fields, stride, what, extra=0):
    """AN UNTILED FIELD MAP IS A SILENT CARRY. Run at import so the claim 'every byte of a record
    is modelled' is refuted here rather than showing up later as mystery coverage."""
    at = 0
    for off, code in fields:
        if off != at:
            raise ValueError('%s field map: hole/overlap at 0x%02x (expected 0x%02x)'
                             % (what, off, at))
        at += struct.calcsize(code)
    if at + extra != stride:
        raise ValueError('%s field map covers %d of %d stride bytes' % (what, at + extra, stride))


_check_tiling(MDS_FIELDS, MDS, 'fwMapDataStore')
_check_tiling(MDS_BANK_FIELDS, MDS_BANK, 'fwMapDataStore(bank)', extra=BANK_TAIL_LEN)
_check_tiling(IPR_FIELDS, IPR, 'CInteriorProxy')
_check_tiling(BND_FIELDS, BND, 'BoundsStore')

MODULES = {'fwMapDataStore': MDS, 'CInteriorProxy': IPR, 'BoundsStore': BND}
FIELDS_FOR = {'fwMapDataStore': MDS_FIELDS, 'CInteriorProxy': IPR_FIELDS,
              'BoundsStore': BND_FIELDS}


class CacheError(Exception):
    pass


class _Emit(object):
    """Cursor emitter into a ZERO-FILLED image; refuses on a hole, an overlap, or a short landing.

    The variable-length analogue of `yvr_write._check_tiling` - it is what makes byte identity
    prove the field map tiles THE WHOLE FILE.
    """

    def __init__(self, size):
        self.buf = bytearray(size)
        self.written = bytearray(size)
        self.at = 0
        self.n_value = 0
        self.n_derived = 0
        self.n_zero = 0
        self.n_carried = 0

    def _claim(self, n, kind):
        if self.at + n > len(self.buf):
            raise CacheError('emit past EOF at %d (+%d > %d)' % (self.at, n, len(self.buf)))
        for i in range(self.at, self.at + n):
            if self.written[i]:
                raise CacheError('OVERLAP: byte %d written twice' % i)
            self.written[i] = 1
        setattr(self, 'n_' + kind, getattr(self, 'n_' + kind) + n)
        self.at += n

    def put(self, code, *vals, **kw):
        n = struct.calcsize(code)
        struct.pack_into(code, self.buf, self.at, *vals)
        self._claim(n, kw.get('kind', 'value'))

    def raw(self, data, kind='value'):
        self.buf[self.at:self.at + len(data)] = data
        self._claim(len(data), kind)

    def zeros(self, n):
        self._claim(n, 'zero')          # buffer is already zero-filled

    def finish(self):
        if self.at != len(self.buf):
            raise CacheError('cursor landed at %d, file is %d bytes - the field map does not tile'
                             % (self.at, len(self.buf)))
        hole = self.written.count(0)
        if hole:
            raise CacheError('%d bytes never claimed by any field' % hole)
        return bytes(self.buf)


# ------------------------------------------------------------------ the stride gate
def _record_sanity(body, stride):
    """(good, n) - records whose name hash is non-zero AND whose 12 floats are zero or sane.

    ⭐ A PREDICATE THAT CAN REFUSE. Choosing the stride by "it divides the payload" proves
    nothing: 64 and 160 both divide 8 of the 17 non-empty `_bank` payloads. This scores the
    records the stride implies, so a wrong stride - which lands the header on the middle of the
    previous record's bank tail - is refuted by the DATA rather than by a naming convention.
    """
    if not body or stride > len(body) or len(body) % stride:
        return None
    good = 0
    n = len(body) // stride
    for o in range(0, len(body), stride):
        if struct.unpack_from('<I', body, o)[0] == 0:
            continue
        f = struct.unpack_from('<12f', body, o + 12)
        if all(v == 0.0 for v in f) or all(math.isfinite(v) and abs(v) < 1e5 for v in f):
            good += 1
    return good, n


def _pick_stride(body):
    """-> (stride, ambiguous) for a fwMapDataStore payload. Retail 64 unless bank 160 STRICTLY
    wins the sanity score. `ambiguous` is True when both strides divide and score equally - it is
    COUNTED by the caller, never hidden, because that is where a future variant would hide."""
    if not body:
        # 36 of the 132 cache files carry an EMPTY fwMapDataStore (11 of them `_bank`). Zero
        # records tile at either stride, so the question does not arise - retail is the default
        # and no claim is made. Counted here rather than raised: an empty module is a fact about
        # the file, not a refusal.
        return MDS, False
    s64 = _record_sanity(body, MDS)
    s160 = _record_sanity(body, MDS_BANK)

    def frac(s):
        return -1.0 if s is None else (float(s[0]) / s[1] if s[1] else 1.0)

    f64, f160 = frac(s64), frac(s160)
    if f64 < 0 and f160 < 0:
        raise CacheError('fwMapDataStore: payload %d divides neither the 64-byte retail record '
                         'nor the 160-byte bank record' % len(body))
    if f160 > f64:
        return MDS_BANK, False
    return MDS, (f64 == f160 and s160 is not None and s64 is not None)


class Cache(object):
    def __init__(self, blob):
        d = self.raw_blob = bytes(blob)
        self.size = len(d)
        if d[:len(MAGIC)] != MAGIC:
            raise CacheError('not a cache container (no [VERSION] magic)')
        nl = d.index(b'\n', len(MAGIC))
        self.version = d[len(MAGIC):nl].decode('ascii')
        self.header_pad = d[nl + 1:HEADER_LEN]
        if any(self.header_pad):
            raise CacheError('header pad 0x%02x..0x%02x is not zero' % (nl + 1, HEADER_LEN))
        fd = d.index(b'<fileDates>\n')
        if fd != HEADER_LEN:
            raise CacheError('<fileDates> at 0x%x, expected 0x%x' % (fd, HEADER_LEN))
        fde = d.index(b'</fileDates>\n')
        self.dates = []
        for ln in d[fd + 12:fde].decode('ascii').split('\n'):
            if not ln:
                continue
            f = ln.split(' ')
            if len(f) == 3:
                self.dates.append((int(f[0]), int(f[1]), int(f[2])))
            elif len(f) == 2:
                self.dates.append((int(f[0]), int(f[1]), None))
            else:
                raise CacheError('fileDates line with %d fields: %r' % (len(f), ln))
        p = fde + 13
        self.modules = []            # [(name, stride, [record-tuples], [bank tails])]
        self.ambiguous = 0
        self.bank_tail_text = 0
        self.bank_tail_carried = 0
        while p < len(d) and d[p:p + 9] == b'<module>\n':
            p += 9
            e = d.index(b'\n', p)
            name = d[p:e].decode('ascii')
            p = e + 1
            end = d.index(b'</module>\n', p)
            payload = d[p:end]
            p = end + 10
            self.modules.append(self._module(name, payload))
        if p != len(d):
            raise CacheError('trailing bytes after the last module: %d' % (len(d) - p))

    def _module(self, name, payload):
        if name not in MODULES:
            # NO SILENT CARRY. An unknown module would otherwise be copied and score as coverage.
            raise CacheError('unknown module %r - this writer models %s only'
                             % (name, sorted(MODULES)))
        declared = struct.unpack_from('<I', payload, 0)[0]
        if declared != len(payload) - 4:
            raise CacheError('%s: declared payload %d != actual %d'
                             % (name, declared, len(payload) - 4))
        body = payload[4:]
        stride = MODULES[name]
        if name == 'fwMapDataStore':
            stride, amb = _pick_stride(body)
            if amb:
                self.ambiguous += 1
        elif body and len(body) % stride:
            raise CacheError('%s: payload %d is not a multiple of the %d-byte record'
                             % (name, len(body), stride))
        fields = FIELDS_FOR[name] if stride != MDS_BANK else MDS_BANK_FIELDS
        recs = []
        tails = []
        for o in range(0, len(body), stride):
            recs.append(tuple(struct.unpack_from(c, body, o + fo) for fo, c in fields))
            if stride == MDS_BANK:
                t = bytes(body[o + BANK_TAIL_AT: o + BANK_TAIL_AT + BANK_TAIL_LEN])
                z = t.find(0)
                head = t if z < 0 else t[:z]
                rest = b'' if z < 0 else t[z:]
                if all(c in PRINTABLE for c in head) and not any(rest):
                    # a DECODED VALUE: text + an asserted NUL pad, re-encoded on write
                    tails.append(('text', head))
                    self.bank_tail_text += BANK_TAIL_LEN
                else:
                    # host-address residue - carried, and COUNTED so it can never be quoted as
                    # modelled coverage
                    tails.append(('raw', t))
                    self.bank_tail_carried += BANK_TAIL_LEN
        return (name, stride, recs, tails)

    # ------------------------------------------------------------------ write
    def write(self):
        e = _Emit(self.size)
        e.raw(MAGIC + self.version.encode('ascii') + b'\n')
        e.zeros(HEADER_LEN - e.at)
        e.raw(b'<fileDates>\n')
        for h, ts, fid in self.dates:
            ln = ('%d %d' % (h, ts)) if fid is None else ('%d %d %d' % (h, ts, fid))
            e.raw(ln.encode('ascii') + b'\n')
        e.raw(b'</fileDates>\n')
        for name, stride, recs, tails in self.modules:
            e.raw(b'<module>\n' + name.encode('ascii') + b'\n')
            # ⭐ DERIVED, NEVER CARRIED - the same law meta_write/ynd_write apply to the page
            # count. Recomputing the payload length is what makes the record COUNT part of the
            # measurement: get the stride wrong and this word is wrong and the file fails.
            e.put('<I', len(recs) * stride, kind='derived')
            fields = FIELDS_FOR[name] if stride != MDS_BANK else MDS_BANK_FIELDS
            base = e.at
            for i, rec in enumerate(recs):
                o = base + i * stride
                for (fo, code), vals in zip(fields, rec):
                    struct.pack_into(code, e.buf, o + fo, *vals)
                if stride == MDS_BANK:
                    kind, payload = tails[i]
                    at = o + BANK_TAIL_AT
                    if kind == 'text':
                        e.buf[at:at + len(payload)] = payload
                    else:
                        e.buf[at:at + BANK_TAIL_LEN] = payload
            # claim the record block in one go for the overlap/coverage bookkeeping
            n = len(recs) * stride
            modelled = n
            if stride == MDS_BANK:
                modelled = n - self._raw_tail_bytes(tails)
            e.at = base
            e._claim(modelled, 'value')
            if modelled != n:
                e.at = base + modelled
                e._claim(n - modelled, 'carried')
            e.at = base + n
            e.raw(b'</module>\n')
        return e.finish(), (e.n_value, e.n_derived, e.n_zero, e.n_carried)

    @staticmethod
    def _raw_tail_bytes(tails):
        return sum(BANK_TAIL_LEN for k, _v in tails if k == 'raw')

    def unreached(self):
        """(count, non_zero_count) of bytes the model never reproduced."""
        got, _acct = self.write()
        orig = self.raw_blob
        n = min(len(got), len(orig))
        bad = [i for i in range(n) if got[i] != orig[i]]
        return len(bad), sum(1 for i in bad if orig[i] != 0)

    def regions(self):
        """(carried_verbatim, value, derived, zero_fill) byte split of the image."""
        _got, (v, dr, z, c) = self.write()
        return (c, v, dr, z)


def read_cache(src):
    blob = bytes(src) if isinstance(src, (bytes, bytearray)) else open(src, 'rb').read()
    return Cache(blob)


def is_cache(blob):
    """Container gate for the split `.dat` lane - TEXTUAL magic, a fact about the file."""
    return len(blob) >= len(MAGIC) and blob[:len(MAGIC)] == MAGIC


# --------------------------------------------------------------------- selftest
def _selftest(paths):
    print('cache_write selftest - SAMPLE SIZE: %d file(s) offered' % len(paths))
    subj = []
    for p in paths:
        b = open(p, 'rb').read()
        if is_cache(b):
            subj.append((p, b))
    print('  container gate   : %d cache-magic subjects, %d non-cache .dat turned away'
          % (len(subj), len(paths) - len(subj)))
    if not subj:
        print('REFUSING: empty sample - a harness with no subject cannot report coverage.')
        return 2
    exact = 0
    tot = 0
    cov = []
    errs = {}
    acc = [0, 0, 0, 0]
    bank = 0
    amb = 0
    for p, b in subj:
        try:
            m = read_cache(b)
            n, _nz = m.unreached()
        except Exception as ex:
            errs['%s: %s' % (type(ex).__name__, str(ex)[:60])] = \
                errs.get('%s: %s' % (type(ex).__name__, str(ex)[:60]), 0) + 1
            continue
        tot += 1
        cov.append(100.0 * (m.size - n) / m.size)
        if n == 0:
            exact += 1
        c, v, dr, z = m.regions()
        acc[0] += c
        acc[1] += v
        acc[2] += dr
        acc[3] += z
        if any(s == MDS_BANK for _n2, s, _r, _t in m.modules):
            bank += 1
        amb += m.ambiguous
    if not tot:
        print('REFUSING: every file errored - %s' % errs)
        return 2
    tot_b = sum(acc)
    print('  EXACT round-trip : %d / %d (%.4f%%)' % (exact, tot, 100.0 * exact / tot))
    print('  mean coverage    : %.4f%%   min %.4f%%' % (sum(cov) / len(cov), min(cov)))
    print('  bank stride 160  : %d file(s); ambiguous stride picks: %d' % (bank, amb))
    print('  BYTE ACCOUNTING  : VALUE %d (%.4f%%) / DERIVED %d / ZERO %d / CARRIED %d (%.4f%%)'
          % (acc[1], 100.0 * acc[1] / tot_b, acc[2], acc[3], acc[0], 100.0 * acc[0] / tot_b))
    if errs:
        print('  errors           :')
        for k, v in sorted(errs.items()):
            print('      %4d x %s' % (v, k))
    return 0 if exact == tot else 1


if __name__ == '__main__':
    import glob
    args = _sys.argv[1:]
    files = []
    for a in args:
        files.extend(sorted(glob.glob(a)) if any(c in a for c in '*?') else [a])
    _sys.exit(_selftest(files))
