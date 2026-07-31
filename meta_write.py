"""meta_write - the RSC7 **v2 META WRITER** (binary `ytyp` / `ymap` / scenario `ymt`).

WHY THIS EXISTS: `quarry/meta2xml.py` reads v2 META and is fully validated. Everything RUDE
still cannot ship - binary interior `ytyp` (MLO) and authored scenario region `ymt` - needs the
other direction. This module is the writer, derived the only way a writer can be proven without
an oracle: **read a real binary into a value model, write it back, demand the bytes match.**

THE MODEL IS VALUE-LEVEL, NOT A MEMCPY. `read_meta` decodes every field to a Python value and
records the cell that produced it; `write_meta` re-encodes each cell from that value into a
zero-filled image. So byte identity proves the ENCODERS, not that we copied a buffer. Anything
the walk never reaches is recorded separately as an unreached-gap so the residual is always
attributable (see `roundtrip.py`, which reports gap bytes and whether they are non-zero).

WHAT WAS DERIVED HERE (all measured over the corpus, see the report):
  * header +0x08 -> a 24-byte page-count record; its u32 at +8 is
    **pageCount(system) | pageCount(graphics) << 8** - 250/250 exact. COMPUTED, not carried.
  * array descriptor  = {u32 metaPtr, u32 0, u16 count, u16 capacity==count, u32 0} (15,023/15,023)
  * string descriptor = {u32 metaPtr, u32 0, u16 len, u16 len+1, u32 0}     (394/394 non-empty)
  * struct-info +0x04 `key` and +0x08 class word are per-struct CONSTANTS - 700 files, 51
    struct types and 11 enum types, ZERO with more than one key/class/length/layout - carried
    in a harvested table (`writer_constants.json`), which is sound because a writer only emits
    struct types it has read. NOT derivable from the name (proven by seed inversion; see report).
  * header +0x40 -> {u32 BE size, payload}, payload always a multiple of 16, high entropy,
    **and NULL in 180/180 community-authored files that load in game** => optional. Carried
    verbatim, or dropped for authoring. Never invented.

⚠ LAYOUT: this writer PINS the source's own region offsets. That is what makes the round-trip
gate meaningful, and it is enough for read->edit->write of an existing file, but it is NOT a
layout ALLOCATOR: emitting a brand-new interior or region from scratch still needs one. R*'s
allocation ORDER is not derived (a real file interleaves entry tables, block data, the struct
table and the blob - it is not "tables then blocks"). A fresh self-consistent layout is legal
(pointers are explicit, and the community files prove another writer's layout loads), so this
is remaining engineering, not remaining reversing.

ASCII-only on purpose, like meta2xml.py: PowerShell round-trips corrupt non-ASCII here.
"""
import collections
import struct
import zlib

# ------------------------------------------------------------------ RSC7 container
PAGE_BITS = {0: 27, 1: 26, 2: 25, 3: 24, 4: 17, 5: 11, 6: 7, 7: 5, 8: 4}
PAGE_MASK = {0: 1, 1: 1, 2: 1, 3: 1, 4: 0x7F, 5: 0x3F, 6: 0xF, 7: 3, 8: 1}
MAXPAGE = 0x400000
SEG_SYS, SEG_GFX = 5, 6


def seg_size(flags):
    f = flags & 0x0FFFFFFF
    base = 0x200 << (f & 0xF)
    return sum(((f >> PAGE_BITS[k]) & PAGE_MASK[k]) * (base << k) for k in range(9))


def page_count(flags):
    f = flags & 0x0FFFFFFF
    return sum((f >> PAGE_BITS[k]) & PAGE_MASK[k] for k in range(9))


def flags_from_size(size):
    """Inverse of seg_size: tile into power-of-two pages, largest first, capped at 4 MB."""
    if size <= 0:
        return 0
    pages, rem = [], size
    while rem > 0:
        p = MAXPAGE
        while p > rem:
            p >>= 1
        pages.append(p)
        rem -= p
    base = min(pages) // 16
    flag = (base // 0x200).bit_length() - 1
    for psize, c in collections.Counter(pages).items():
        k = (psize // base).bit_length() - 1
        flag |= c << PAGE_BITS[k]
    return flag


# ------------------------------------------------------------------ hashing
M32 = 0xFFFFFFFF


def joaat(s, lower=True):
    h = 0
    for ch in (s.lower() if lower else s):
        h = (h + ord(ch)) & M32
        h = (h + (h << 10)) & M32
        h ^= h >> 6
    h = (h + (h << 3)) & M32
    h ^= h >> 11
    return (h + (h << 15)) & M32


def joaat_case(s):
    return joaat(s, lower=False)


# ------------------------------------------------------------------ META type codes
T_BOOL, T_S8, T_U8, T_S16, T_U16, T_S32, T_U32 = 0x01, 0x10, 0x11, 0x12, 0x13, 0x14, 0x15
T_FLOAT, T_VEC3, T_VEC4 = 0x21, 0x33, 0x34
T_STRUCT, T_PTR, T_STRING, T_HASH = 0x05, 0x07, 0x44, 0x4A
T_FIXEDARR, T_ARRAY, T_ENUM_U8, T_ENUM, T_FLAGS = 0x50, 0x52, 0x60, 0x62, 0x65
# 0x40 = INLINE CHAR BUFFER, `refKey` bytes wide, NUL-padded (found by the round-trip gate on
# compositeEntityTypes: three 0x40 fields at 0/136/200 with refKey 0x40 = char[64]). It is a
# VALUE, not a pointer - the text lives in the record itself.
T_CHARARR = 0x40
# 0x59 = RAW BYTE-BUFFER POINTER, 8 bytes {u32 metaPtr, u32 0}, no count in the descriptor.
# The payload fills its target block entirely: MEASURED over the occlusion ymaps, the sibling
# `dataSize` u32 equals the target block's declared length in every record (16/16 sampled), so
# the length is read from the BLOCK TABLE and nothing is inferred. Occluder vertex buffers.
T_DATAPTR = 0x59
PRIM = {
    T_BOOL: (1, "?"), T_S8: (1, "b"), T_U8: (1, "B"), T_S16: (2, "h"), T_U16: (2, "H"),
    T_S32: (4, "i"), T_U32: (4, "I"), T_FLOAT: (4, "f"), T_VEC3: (12, "3f"),
    T_VEC4: (16, "4f"),
}
VEC3_ARRAY_STRIDE = 16          # measured: vec3 ARRAY elements carry a 4th float
ELEM_NAME_HASH = 0x00000100     # synthetic entry marking an array's element type
STRBLOCK = 0x00000007           # block whose "struct" is the char pool


def metaptr(block_index0, offset):
    """MetaPOINTER u32: low 12 bits = 1-based block index, high 20 = byte offset."""
    if block_index0 is None:
        return 0
    return ((block_index0 + 1) & 0xFFF) | ((offset & 0xFFFFF) << 12)


def unmetaptr(v):
    return (None, 0) if v == 0 else ((v & 0xFFF) - 1, v >> 12)


def tagptr(seg, offset):
    return 0 if seg is None else ((seg << 28) | offset)


def untagptr(v):
    return (None, 0) if not v else ((v >> 28) & 0xF, v & 0x0FFFFFFF)


# ------------------------------------------------------------------ model
class StructDef(object):
    """One `parStructure`: identity + the constants the file carries for it + its entries."""
    __slots__ = ("name_hash", "key", "cls", "u0C", "length", "u1C", "entries")

    def __init__(self, name_hash, key, cls, u0C, length, u1C, entries):
        self.name_hash, self.key, self.cls = name_hash, key, cls
        self.u0C, self.length, self.u1C, self.entries = u0C, length, u1C, entries

    def entry(self, idx):
        return self.entries[idx] if 0 <= idx < len(self.entries) else None


Entry = collections.namedtuple("Entry", "name_hash offset type flags ref_type_idx ref_key")


def field_size(struct_def, e):
    """Bytes a declared field occupies IN the record.

    ⭐ MEASURED, not assumed: a T_VEC3 field occupies **16** bytes inline, not 12 - the
    round-trip gate found a 4-byte hole after every one of bbMin/bbMax/bsCentre. (The same
    16-byte stride already known for vec3 ARRAY elements, LOG "MLO INTERIORS".)
    """
    t = e.type
    if t == T_VEC3:
        return 16
    if t in PRIM:
        return PRIM[t][0]
    if t in (T_HASH, T_ENUM, T_FLAGS, T_PTR):
        return 4
    if t == T_ENUM_U8:
        return 1
    if t in (T_STRING, T_ARRAY):
        return 16
    if t == T_DATAPTR:
        return 8
    if t == T_CHARARR:
        return e.ref_key
    if t == T_STRUCT:
        sub = struct_def
        return sub.length if sub else 0
    if t == T_FIXEDARR:
        ed = struct_def.entry(e.ref_type_idx) if struct_def else None
        if ed is not None and ed.type in PRIM:
            return PRIM[ed.type][0] * e.ref_key
        return 0
    return 0


_PAD_CACHE = {}


def struct_pad_ranges(s):
    """Byte ranges of a record that no declared field covers (record head, alignment)."""
    key = (s.name_hash, s.length, tuple(s.entries))
    hit = _PAD_CACHE.get(key)
    if hit is not None:
        return hit
    claimed = bytearray(max(0, s.length))
    for e in s.entries:
        if e.name_hash == ELEM_NAME_HASH:
            continue
        sub = None
        if e.type == T_STRUCT:
            sub = _CURRENT_IMAGE[0].struct_by_hash(e.ref_key) if _CURRENT_IMAGE else None
        n = field_size(sub if e.type == T_STRUCT else s, e)
        for i in range(e.offset, min(e.offset + n, len(claimed))):
            claimed[i] = 1
    out, i = [], 0
    while i < len(claimed):
        if claimed[i]:
            i += 1
            continue
        j = i
        while j < len(claimed) and not claimed[j]:
            j += 1
        out.append((i, j - i))
        i = j
    _PAD_CACHE[key] = out
    return out


_CURRENT_IMAGE = []
EnumDef = collections.namedtuple("EnumDef", "name_hash key members u14")   # members [(hash,val)]
BlockDef = collections.namedtuple("BlockDef", "struct_hash seg length offset")


class Cell(object):
    """One primitive write: everything in the image is expressed as cells, so a byte that no
    cell covers is a MEASURED gap rather than a silent memcpy."""
    __slots__ = ("seg", "off", "fmt", "value", "kind")

    def __init__(self, seg, off, fmt, value, kind):
        self.seg, self.off, self.fmt, self.value, self.kind = seg, off, fmt, value, kind

    def size(self):
        return struct.calcsize("<" + self.fmt) if self.fmt else len(self.value)

    def pack(self):
        if not self.fmt:
            return bytes(self.value)
        v = self.value
        return struct.pack("<" + self.fmt, *(v if isinstance(v, tuple) else (v,)))


class MetaImage(object):
    """A whole v2 META file as values + layout. `write()` renders it to RSC7 bytes."""

    def __init__(self):
        self.version = 2
        self.sys_flags = 0
        self.gfx_flags = 0
        self.vft = 0                 # u64 at +0x00 (game vtable address; a per-build constant)
        self.unk10 = 0x50524430      # constant in 100% of files
        self.unk14 = 0x00010079      # build/version stamp (0x00000079 in some authored files)
        self.unk18 = 0
        self.unk38 = 0
        self.root_block = 1          # 1-based
        self.structs = []
        self.enums = []
        self.blocks = []
        self.blob40 = None
        self.blob40_off = None
        self.p08_off = None
        self.struct_table_off = None
        self.enum_table_off = None
        self.block_table_off = None
        self.entry_table_off = {}    # struct name hash -> offset
        self.member_table_off = {}   # enum name hash -> offset
        self.cells = []              # value cells inside block data
        self.gaps = []               # (seg, off, bytes) block bytes no cell covered
        self.root = None             # decoded value tree (for consumers)
        self.warn = collections.Counter()

    # -- schema access
    def struct_by_hash(self, h):
        for s in self.structs:
            if s.name_hash == h:
                return s
        return None

    def enum_by_hash(self, h):
        for e in self.enums:
            if e.name_hash == h:
                return e
        return None

    # ---------------------------------------------------------- rendering
    def image(self, include_gaps=True):
        """Render the decompressed system + graphics segments."""
        sysbuf = bytearray(seg_size(self.sys_flags))
        gfxbuf = bytearray(seg_size(self.gfx_flags))

        def buf(seg):
            return sysbuf if seg == SEG_SYS else gfxbuf

        def put(seg, off, data):
            b = buf(seg)
            if off + len(data) > len(b):
                self.warn["write past segment end"] += 1
                return
            b[off:off + len(data)] = data

        # --- header (+0x00 .. +0x50)
        put(SEG_SYS, 0x00, struct.pack("<Q", self.vft))
        put(SEG_SYS, 0x08, struct.pack("<Q", tagptr(SEG_SYS, self.p08_off)
                                       if self.p08_off is not None else 0))
        put(SEG_SYS, 0x10, struct.pack("<III", self.unk10, self.unk14, self.unk18))
        put(SEG_SYS, 0x1C, struct.pack("<I", self.root_block))
        put(SEG_SYS, 0x20, struct.pack("<Q", tagptr(SEG_SYS, self.struct_table_off)
                                       if self.structs else 0))
        put(SEG_SYS, 0x28, struct.pack("<Q", tagptr(SEG_SYS, self.enum_table_off)
                                       if self.enums else 0))
        put(SEG_SYS, 0x30, struct.pack("<Q", tagptr(SEG_SYS, self.block_table_off)
                                       if self.blocks else 0))
        put(SEG_SYS, 0x38, struct.pack("<Q", self.unk38))
        put(SEG_SYS, 0x40, struct.pack("<Q", tagptr(SEG_SYS, self.blob40_off)
                                       if self.blob40 is not None else 0))
        put(SEG_SYS, 0x48, struct.pack("<HHI", len(self.structs), len(self.enums),
                                       len(self.blocks)))

        # --- the +0x08 page record: DERIVED, never carried
        if self.p08_off is not None:
            rec = bytearray(24)
            struct.pack_into("<I", rec, 8,
                             (page_count(self.sys_flags) & 0xFF) |
                             ((page_count(self.gfx_flags) & 0xFF) << 8))
            put(SEG_SYS, self.p08_off, bytes(rec))

        # --- struct infos + entry tables
        for i, s in enumerate(self.structs):
            eoff = self.entry_table_off.get(s.name_hash)
            put(SEG_SYS, self.struct_table_off + i * 32,
                struct.pack("<IIIIQiHH", s.name_hash, s.key, s.cls, s.u0C,
                            tagptr(SEG_SYS, eoff) if s.entries else 0,
                            s.length, s.u1C, len(s.entries)))
            for j, e in enumerate(s.entries):
                put(SEG_SYS, eoff + j * 16,
                    struct.pack("<IiBBhI", e.name_hash, e.offset, e.type, e.flags,
                                e.ref_type_idx, e.ref_key))

        # --- enum infos + member tables
        for i, en in enumerate(self.enums):
            moff = self.member_table_off.get(en.name_hash)
            put(SEG_SYS, self.enum_table_off + i * 24,
                struct.pack("<IIQiI", en.name_hash, en.key,
                            tagptr(SEG_SYS, moff) if en.members else 0,
                            len(en.members), en.u14))
            for j, (mh, mv) in enumerate(en.members):
                put(SEG_SYS, moff + j * 8, struct.pack("<Ii", mh, mv))

        # --- block table
        for i, b in enumerate(self.blocks):
            put(SEG_SYS, self.block_table_off + i * 16,
                struct.pack("<IiQ", b.struct_hash, b.length, tagptr(b.seg, b.offset)))

        # --- block payloads, cell by cell (this is the part that proves the encoders)
        for c in self.cells:
            put(c.seg, c.off, c.pack())
        if include_gaps:
            for seg, off, data in self.gaps:
                put(seg, off, data)

        # --- the +0x40 blob (opaque; see module docstring)
        if self.blob40 is not None and self.blob40_off is not None:
            put(SEG_SYS, self.blob40_off,
                struct.pack(">I", len(self.blob40)) + self.blob40)
        return bytes(sysbuf), bytes(gfxbuf)

    def write(self, level=9, include_gaps=True, mem_level=9):
        """Full RSC7 file bytes.

        ⭐ `mem_level=9` is LOAD-BEARING for byte identity, and it is measured, not assumed:
        zlib's default memLevel is 8, and at 8 the deflate stream matches the shipped file only
        ~50% of the time. At **level 9 + memLevel 9 the stream is identical on 40/40 sampled
        ymap** - i.e. the container is reproducible too, not just the decompressed image.
        (Worth trying on QUARRY's other RSC7 writers, which are validated only at image level.)
        """
        s, g = self.image(include_gaps=include_gaps)
        co = zlib.compressobj(level, zlib.DEFLATED, -15, mem_level)
        payload = co.compress(s + g) + co.flush()
        return struct.pack("<4sIII", b"RSC7", self.version, self.sys_flags,
                           self.gfx_flags) + payload


# ------------------------------------------------------------------ reader -> model
class _Reader(object):
    def __init__(self, blob):
        magic, version, sysf, gfxf = struct.unpack_from("<4sIII", blob, 0)
        if magic != b"RSC7":
            raise ValueError("not an RSC7 container")
        if version != 2:
            raise ValueError("RSC7 version %d is not v2 META" % version)
        raw = zlib.decompress(blob[16:], -15)
        ssz, gsz = seg_size(sysf), seg_size(gfxf)
        self.sys, self.gfx = raw[:ssz], raw[ssz:ssz + gsz]
        self.img = MetaImage()
        self.img.version = version
        self.img.sys_flags, self.img.gfx_flags = sysf, gfxf
        self.covered = {SEG_SYS: bytearray(len(self.sys)), SEG_GFX: bytearray(len(self.gfx))}
        self.visited = set()

    def seg(self, s):
        return self.sys if s == SEG_SYS else self.gfx

    def cell(self, seg, off, fmt, value, kind):
        c = Cell(seg, off, fmt, value, kind)
        n = c.size()
        cov = self.covered[seg]
        for i in range(off, min(off + n, len(cov))):
            cov[i] = 1
        self.img.cells.append(c)
        return c

    # -------------------------------------------------- header + schema
    def parse(self):
        s, img = self.sys, self.img
        img.vft = struct.unpack_from("<Q", s, 0)[0]
        p08 = struct.unpack_from("<Q", s, 0x08)[0]
        img.unk10, img.unk14, img.unk18 = struct.unpack_from("<III", s, 0x10)
        img.root_block = struct.unpack_from("<I", s, 0x1C)[0]
        p_struct = struct.unpack_from("<Q", s, 0x20)[0]
        p_enum = struct.unpack_from("<Q", s, 0x28)[0]
        p_blocks = struct.unpack_from("<Q", s, 0x30)[0]
        img.unk38 = struct.unpack_from("<Q", s, 0x38)[0]
        p40 = struct.unpack_from("<Q", s, 0x40)[0]
        n_struct, n_enum = struct.unpack_from("<HH", s, 0x48)
        n_blocks = struct.unpack_from("<I", s, 0x4C)[0]

        seg, off = untagptr(p08)
        img.p08_off = off if seg == SEG_SYS else None
        self.p08_raw = s[off:off + 24] if seg == SEG_SYS else None

        seg, off = untagptr(p_struct)
        img.struct_table_off = off if seg == SEG_SYS else None
        for i in range(n_struct):
            b = off + i * 32
            nh, key, cls, u0C = struct.unpack_from("<4I", s, b)
            pE = struct.unpack_from("<Q", s, b + 16)[0]
            length = struct.unpack_from("<i", s, b + 24)[0]
            u1C, count = struct.unpack_from("<HH", s, b + 28)
            eseg, eoff = untagptr(pE)
            entries = []
            for j in range(count):
                entries.append(Entry(*struct.unpack_from("<IiBBhI", s, eoff + j * 16)))
            img.entry_table_off[nh] = eoff
            img.structs.append(StructDef(nh, key, cls, u0C, length, u1C, entries))

        seg, off = untagptr(p_enum)
        img.enum_table_off = off if seg == SEG_SYS else None
        for i in range(n_enum):
            b = off + i * 24
            nh, key = struct.unpack_from("<II", s, b)
            pM = struct.unpack_from("<Q", s, b + 8)[0]
            cnt = struct.unpack_from("<i", s, b + 16)[0]
            u14 = struct.unpack_from("<I", s, b + 20)[0]
            mseg, moff = untagptr(pM)
            members = [struct.unpack_from("<Ii", s, moff + j * 8) for j in range(cnt)]
            img.member_table_off[nh] = moff
            img.enums.append(EnumDef(nh, key, members, u14))

        seg, off = untagptr(p_blocks)
        img.block_table_off = off if seg == SEG_SYS else None
        for i in range(n_blocks):
            b = off + i * 16
            sh = struct.unpack_from("<I", s, b)[0]
            ln = struct.unpack_from("<i", s, b + 4)[0]
            bseg, boff = untagptr(struct.unpack_from("<Q", s, b + 8)[0])
            img.blocks.append(BlockDef(sh, bseg, ln, boff))

        seg, off = untagptr(p40)
        if seg == SEG_SYS:
            img.blob40_off = off
            size = struct.unpack_from(">I", s, off)[0]
            img.blob40 = s[off + 4:off + 4 + size]

        _CURRENT_IMAGE[:] = [img]
        self.walk_root()
        _CURRENT_IMAGE[:] = []
        self.collect_gaps()
        return img

    # -------------------------------------------------- value walk
    def block(self, i):
        bl = self.img.blocks
        return bl[i] if (i is not None and 0 <= i < len(bl)) else None

    def walk_root(self):
        b = self.block(self.img.root_block - 1)
        if b is None:
            self.img.warn["root block out of range"] += 1
            return
        self.img.root = (b.struct_hash, self.read_struct(b.struct_hash, b.seg, b.offset))

    def read_struct(self, shash, seg, base):
        s = self.img.struct_by_hash(shash)
        if s is None:
            self.img.warn["no schema for struct %08X" % shash] += 1
            return {}
        key = (seg, base, shash)
        if key in self.visited:
            return {}
        self.visited.add(key)
        out = {}
        for e in s.entries:
            if e.name_hash == ELEM_NAME_HASH:
                continue
            out[e.name_hash] = self.read_value(s, e, seg, base + e.offset)
        # every byte of the record that NO declared field claims is emitted as an explicit
        # `pad` cell, so nothing is absorbed silently. See struct_pad_ranges().
        for off, ln in struct_pad_ranges(s):
            raw = bytes(self.seg(seg)[base + off:base + off + ln])
            self.cell(seg, base + off, "", raw, "recordpad")
            if any(raw):
                self.img.warn["non-zero record padding in %08X" % shash] += 1
        return out

    def float_cell(self, seg, o, n, kind):
        """Floats are celled as their IEEE BIT PATTERN, never as a Python float.

        ⚠ LOAD-BEARING, and the round-trip gate is what found it: RAGE stores signalling NaNs
        (portal corners carry 0x7F800001), and unpack->float->pack QUIETS them to 0x7FC00001 -
        one byte per element, invisible to any tolerance-based check. Storing bits keeps the
        value decoded (bits ARE the value) and byte-exact.
        """
        buf = self.seg(seg)
        bits = struct.unpack_from("<%dI" % n, buf, o)
        self.cell(seg, o, "%dI" % n, bits if n > 1 else bits[0], kind)
        vals = struct.unpack_from("<%df" % n, buf, o)
        return vals[0] if n == 1 else vals

    def read_value(self, s, e, seg, o):
        buf, t = self.seg(seg), e.type
        try:
            if t == T_FLOAT:
                return self.float_cell(seg, o, 1, "float")
            if t == T_VEC3:
                # 16 bytes inline (measured); the 4th float is kept so nothing is lost
                return self.float_cell(seg, o, 4, "vec3")
            if t == T_VEC4:
                return self.float_cell(seg, o, 4, "vec4")
            if t == T_CHARARR:
                raw = bytes(buf[o:o + e.ref_key])
                self.cell(seg, o, "", raw, "charbuf")
                return raw.split(b"\0")[0].decode("utf-8", "replace")
            if t in PRIM:
                sz, fmt = PRIM[t]
                v = struct.unpack_from("<" + fmt, buf, o)
                v = v[0] if len(v) == 1 else v
                self.cell(seg, o, fmt, v, "prim")
                return v
            if t in (T_HASH, T_ENUM, T_FLAGS):
                v = struct.unpack_from("<I", buf, o)[0]
                self.cell(seg, o, "I", v, {T_HASH: "hash", T_ENUM: "enum",
                                           T_FLAGS: "flags"}[t])
                return v
            if t == T_ENUM_U8:
                v = buf[o]
                self.cell(seg, o, "B", v, "enum8")
                return v
            if t == T_STRUCT:
                return self.read_struct(e.ref_key, seg, o)
            if t == T_STRING:
                return self.read_string(seg, o)
            if t == T_ARRAY:
                return self.read_array(s, e, seg, o)
            if t == T_FIXEDARR:
                return self.read_fixed(s, e, seg, o)
            if t == T_PTR:
                v = struct.unpack_from("<I", buf, o)[0]
                bi, bo = unmetaptr(v)
                b = self.block(bi)
                self.cell(seg, o, "I", v, "ptr")
                if b is None:
                    return None
                return (b.struct_hash, self.read_struct(b.struct_hash, b.seg, b.offset + bo))
            if t == T_DATAPTR:
                pv, hi = struct.unpack_from("<II", buf, o)
                self.cell(seg, o, "II", (pv, hi), "dataptrdesc")
                bi, bo = unmetaptr(pv)
                b = self.block(bi)
                if b is None:
                    return None
                n = b.length - bo
                raw = bytes(self.seg(b.seg)[b.offset + bo:b.offset + bo + n])
                self.cell(b.seg, b.offset + bo, "", raw, "dataptr")
                return {"block": bi, "off": bo, "data": raw}
        except struct.error:
            self.img.warn["short read type 0x%02X" % t] += 1
            return None
        self.img.warn["unhandled type 0x%02X" % t] += 1
        return None

    def read_string(self, seg, o):
        buf = self.seg(seg)
        pv, mid = struct.unpack_from("<II", buf, o)
        ln, cap = struct.unpack_from("<HH", buf, o + 8)
        tail = struct.unpack_from("<I", buf, o + 12)[0]
        bi, bo = unmetaptr(pv)
        b = self.block(bi)
        text = ""
        if b is not None and ln:
            raw = self.seg(b.seg)[b.offset + bo:b.offset + bo + ln]
            text = raw.decode("utf-8", "replace")
            # the char pool itself is a value cell (NUL included)
            self.cell(b.seg, b.offset + bo, "", raw + b"\0", "strdata")
        self.cell(seg, o, "IIHHI", (pv, mid, ln, cap, tail), "strdesc")
        return {"text": text, "block": bi, "off": bo, "mid": mid, "tail": tail}

    def read_fixed(self, s, e, seg, o):
        ed = s.entry(e.ref_type_idx)
        if ed is None or ed.type not in PRIM:
            self.img.warn["fixed array elem 0x%02X" % (ed.type if ed else -1)] += 1
            return None
        sz, fmt = PRIM[ed.type]
        vals = []
        for i in range(e.ref_key):
            if ed.type in (T_FLOAT, T_VEC3, T_VEC4):
                vals.append(self.float_cell(seg, o + i * sz, sz // 4, "fixedelem"))
                continue
            v = struct.unpack_from("<" + fmt, self.seg(seg), o + i * sz)
            v = v[0] if len(v) == 1 else v
            self.cell(seg, o + i * sz, fmt, v, "fixedelem")
            vals.append(v)
        return vals

    def read_array(self, s, e, seg, o):
        buf = self.seg(seg)
        pv, mid = struct.unpack_from("<II", buf, o)
        count, cap = struct.unpack_from("<HH", buf, o + 8)
        tail = struct.unpack_from("<I", buf, o + 12)[0]
        self.cell(seg, o, "IIHHI", (pv, mid, count, cap, tail), "arrdesc")
        bi, bo = unmetaptr(pv)
        b = self.block(bi)
        ed = s.entry(e.ref_type_idx)
        items = []
        if not count or b is None or ed is None:
            return {"items": items, "block": bi, "off": bo, "elem": ed.type if ed else None,
                    "mid": mid, "cap": cap, "tail": tail}
        bseg, base = b.seg, b.offset + bo
        et = ed.type
        if et == T_STRUCT:
            sub = self.img.struct_by_hash(ed.ref_key)
            stride = sub.length if sub else 0
            for i in range(count):
                items.append((ed.ref_key, self.read_struct(ed.ref_key, bseg,
                                                           base + i * stride)))
        elif et == T_PTR:
            for i in range(count):
                p = struct.unpack_from("<I", self.seg(bseg), base + i * 8)[0]
                hi = struct.unpack_from("<I", self.seg(bseg), base + i * 8 + 4)[0]
                self.cell(bseg, base + i * 8, "II", (p, hi), "ptrelem")
                tbi, tbo = unmetaptr(p)
                tb = self.block(tbi)
                items.append(None if tb is None else
                             (tb.struct_hash,
                              self.read_struct(tb.struct_hash, tb.seg, tb.offset + tbo)))
        elif et == T_VEC3:
            for i in range(count):
                items.append(self.float_cell(bseg, base + i * VEC3_ARRAY_STRIDE, 4,
                                             "vec3elem"))
        elif et == T_STRING:
            for i in range(count):
                items.append(self.read_string(bseg, base + i * 16))
        elif et in (T_HASH, T_ENUM, T_FLAGS):
            for i in range(count):
                v = struct.unpack_from("<I", self.seg(bseg), base + i * 4)[0]
                self.cell(bseg, base + i * 4, "I", v, "hashelem")
                items.append(v)
        elif et in PRIM:
            sz, fmt = PRIM[et]
            for i in range(count):
                if et in (T_FLOAT, T_VEC4):
                    items.append(self.float_cell(bseg, base + i * sz, sz // 4, "primelem"))
                    continue
                v = struct.unpack_from("<" + fmt, self.seg(bseg), base + i * sz)
                v = v[0] if len(v) == 1 else v
                self.cell(bseg, base + i * sz, fmt, v, "primelem")
                items.append(v)
        else:
            self.img.warn["array elem type 0x%02X" % et] += 1
        return {"items": items, "block": bi, "off": bo, "elem": et, "mid": mid,
                "cap": cap, "tail": tail}

    # -------------------------------------------------- gaps
    def _mark(self, seg, off, n):
        cov = self.covered[seg]
        for i in range(off, min(off + n, len(cov))):
            cov[i] = 1

    def collect_gaps(self):
        """Every byte of both segments that NO cell and NO table covers.

        Two classes come out of this, and they are reported separately because they mean
        different things:
          * inside a declared block  -> record padding / unreached records
          * outside every block      -> ORPHAN bytes. Measured cause: dead strings left in
            the char pool that no descriptor points at (`p_dock_crane_cable_s`, `test`, ...
            in 2 of 933 ytyp) and, in third-party files, uninitialised 0xCD heap fill.
            Unreachable by definition, so a writer can only carry them.
        """
        img = self.img
        self._mark(SEG_SYS, 0, 0x50)
        if img.p08_off is not None:
            self._mark(SEG_SYS, img.p08_off, 24)
        if img.struct_table_off is not None:
            self._mark(SEG_SYS, img.struct_table_off, len(img.structs) * 32)
        for s in img.structs:
            off = img.entry_table_off.get(s.name_hash)
            if off is not None:
                self._mark(SEG_SYS, off, len(s.entries) * 16)
        if img.enum_table_off is not None:
            self._mark(SEG_SYS, img.enum_table_off, len(img.enums) * 24)
        for e in img.enums:
            off = img.member_table_off.get(e.name_hash)
            if off is not None:
                self._mark(SEG_SYS, off, len(e.members) * 8)
        if img.block_table_off is not None:
            self._mark(SEG_SYS, img.block_table_off, len(img.blocks) * 16)
        if img.blob40 is not None and img.blob40_off is not None:
            self._mark(SEG_SYS, img.blob40_off, len(img.blob40) + 4)

        inblock = {SEG_SYS: bytearray(len(self.sys)), SEG_GFX: bytearray(len(self.gfx))}
        for b in img.blocks:
            if b.seg in inblock:
                for i in range(b.offset, min(b.offset + b.length, len(inblock[b.seg]))):
                    inblock[b.seg][i] = 1
        for seg in (SEG_SYS, SEG_GFX):
            cov, data, ib = self.covered[seg], self.seg(seg), inblock[seg]
            i, end = 0, len(data)
            while i < end:
                if cov[i]:
                    i += 1
                    continue
                j = i
                while j < end and not cov[j]:
                    j += 1
                chunk = data[i:j]
                if any(chunk):
                    # keep only the non-zero span; the surrounding zeros need no cell
                    a, b_ = 0, len(chunk)
                    while a < b_ and not chunk[a]:
                        a += 1
                    while b_ > a and not chunk[b_ - 1]:
                        b_ -= 1
                    img.gaps.append((seg, i + a, chunk[a:b_]))
                    img.warn["orphan bytes %s block" %
                             ("inside" if ib[i + a] else "outside")] += (b_ - a)
                i = j


def read_meta(blob):
    return _Reader(blob).parse()


def write_meta(img, **kw):
    return img.write(**kw)


# ---------------------------------------------------------------- regression entry point
# `python meta_write.py --selftest [N] [--root <filebase>]`
# The ONLY honest gate for a writer with no oracle: read a real binary into the value model,
# write it back, demand the WHOLE RSC7 FILE matches byte for byte. Anything less proves nothing -
# a tolerant compare would pass a writer that quietly re-spells floats or quiets NaNs (both of
# which this writer was caught doing during derivation).
if __name__ == "__main__":
    import argparse
    import glob as _glob
    import random as _random
    import sys as _sys

    ap = argparse.ArgumentParser(prog="meta_write")
    ap.add_argument("--selftest", nargs="?", const=120, type=int, metavar="N",
                    help="round-trip N random binaries per type (default 120)")
    ap.add_argument("--root", required=True,
                    help="filebase to sample binaries from (your `quarry extract --out` folder; "
                         "no default - this path is personal to each machine)")
    ap.add_argument("--seed", type=int, default=11)
    a = ap.parse_args()
    if a.selftest is None:
        ap.error("nothing to do - pass --selftest")

    _random.seed(a.seed)
    rc = 0
    for kind in ("ytyp", "ymap"):
        files = [f for f in (_glob.glob(f"{a.root}/*/{kind}/*.{kind}")
                             + _glob.glob(f"{a.root}/*/*/{kind}/*.{kind}"))
                 if not f.endswith(".xml")]
        if not files:
            print(f"{kind}: no binaries under {a.root} - skipped")
            continue
        sample = _random.sample(files, min(a.selftest, len(files)))
        exact = diff = err = 0
        for p in sample:
            try:
                blob = open(p, "rb").read()
                if read_meta(blob).write() == blob:
                    exact += 1
                else:
                    diff += 1
                    if diff <= 3:
                        print(f"  DIFFERS: {p}")
            except Exception as e:
                err += 1
                if err <= 3:
                    print(f"  ERROR  : {p}: {type(e).__name__}: {e}")
        print(f"{kind}: {exact}/{len(sample)} byte-identical, {diff} differ, {err} error")
        if diff or err:
            rc = 1
    print("SELFTEST PASSED" if rc == 0 else "SELFTEST FAILED")
    _sys.exit(rc)
