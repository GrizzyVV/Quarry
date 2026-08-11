#!/usr/bin/env python3
"""pso_manifest.py — PSO (PSIN) reader/patcher for GTA V sp_manifest.ymt (CScenarioPointManifest).

Proposed QUARRY module (scratchpad build 2026-07-28; not yet installed).

Scope: exactly the four structs the scenario manifest uses. This is NOT a general PSO
codec — every offset below was measured on the 3 samples (x64a, update.rpf, nopixel
production manifest) and field-validated against the common.rpf XML oracle. Anything
not measured refuses loudly.

Container (all integers BIG-ENDIAN):
  file = concatenation of sections, each {u32 fourcc, u32 size incl. 8-byte header}:
    PSIN  data section. payload = "blocks" (instance pools) at PMAP-given offsets.
    PMAP  block map. payload = {u32 rootBlockIndex(1-based), u16 numBlocks, u16 pad(0x7070)}
          then numBlocks x {u32 blockId, u32 fileOffset, u32 zero, u32 byteSize}.
          blockId = struct hash for struct pools, 0x0C for the pointer-pair pool,
          0x06 for the u32-hash pool.
    PSCH  schema. payload = {u32 numStructs} then numStructs x {u32 structHash,
          u32 sectionRelOffset}; each def = {u32 numEntries, u32 instanceSize, u32 zero}
          then numEntries x {u32 nameHash, u8 type, u8 subtype, u16 offset, u32 extra}.
          Array fields (type 0x0D) use extra = index of their element-descriptor entry
          (nameHash 0x00000100) within the same def. Struct fields (0x0C) use
          extra = element struct hash.
    PSIG  16-byte signature payload (vanilla only; semantics unmapped).
    STRF  plaintext string pool, NUL-terminated, zero-padded to section size.
          Holds the region path strings; data references them by joaat(lowercase).
    STRE  encrypted string pool (vanilla only; group/interior name strings; unmapped,
          not needed: data stores the joaat hashes, names recoverable from oracle XML).
    CHKS  {u32 totalFileSize, u32 checksum(algorithm unmapped), u32 0x79707070}
          (vanilla only).

Pointers: u32, low 12 bits = 1-based block index, high 20 bits = byte offset in block.
Arrays (16 B): {u32 ptr, u32 pad, u16 count, u16 capacity, u32 pad}.

CScenarioPointManifest (0x38): +0 unknown 4d0537bb type05 (=0 in all 3 samples; refuse
  if nonzero), +8 RegionDefs array(ptr->CScenarioPointRegionDef), +0x18 Groups
  array(ptr->CScenarioPointGroup), +0x28 InteriorNames array(u32 hash).
CScenarioPointRegionDef (0x40): +0 Name u32 joaat_lower (bytes 4..15 zero),
  +0x10 AABB inline rage__spdAABB.
rage__spdAABB (0x20): +0 min float4 BE, +0x10 max float4 BE.
CScenarioPointGroup (8): +0 Name u32 joaat_lower, +4 EnabledByDefault u8 bool, +5..7 zero.

Writer emits the production-proven interchange layout (nopixel_visuals): sections
PSIN+PMAP+PSCH+STRF only, blocks ordered [RegionDefs, ptrs, Groups, hashes, manifest],
tightly packed, strings in RegionDefs-array order. Byte-validated against the nopixel
manifest (see validate_pso_manifest.py).
"""
import struct
from collections import OrderedDict

# ---------------------------------------------------------------- joaat
def joaat(data):
    if isinstance(data, str):
        data = data.encode('latin1')
    h = 0
    for c in data:
        h = (h + c) & 0xFFFFFFFF
        h = (h + (h << 10)) & 0xFFFFFFFF
        h ^= h >> 6
    h = (h + (h << 3)) & 0xFFFFFFFF
    h ^= h >> 11
    h = (h + (h << 15)) & 0xFFFFFFFF
    return h

def joaat_lower(s):
    return joaat(s.lower())

# ---------------------------------------------------------------- schema (measured)
H_MANIFEST  = 0x54FA14DF   # CScenarioPointManifest
H_REGIONDEF = 0x4A9FA5CC   # CScenarioPointRegionDef
H_GROUP     = 0xC9AEDC3F   # CScenarioPointGroup
H_AABB      = 0xF377E8C8   # rage__spdAABB
H_NAME      = 0xACEC22BE   # Name
H_AABBFIELD = 0x635909D7   # AABB
H_MIN       = 0xFE30E6F3   # min
H_MAX       = 0x606068C4   # max
H_REGIONDEFS= 0xDD51866B   # RegionDefs
H_GROUPS    = 0x950FC840   # Groups
H_INTERIORS = 0x8F714584   # InteriorNames
H_ENABLED   = 0xE9B9019B   # EnabledByDefault
H_UNK0      = 0x4D0537BB   # unresolved manifest field @0 (type 0x05), value 0 in all samples
BLK_PTR     = 0x0000000C   # pointer-pair pool blockId
BLK_HASH    = 0x00000006   # u32-hash pool blockId

# struct defs exactly as measured; entries = (nameHash, type, subtype, offset, extra)
SCHEMA = {
    H_MANIFEST: (0x38, [
        (H_UNK0,       0x05, 0x00, 0x0000, 0x00000000),
        (0x00000100,   0x0C, 0x03, 0x0000, 0x00000000),
        (H_REGIONDEFS, 0x0D, 0x00, 0x0008, 0x00000001),
        (0x00000100,   0x0C, 0x03, 0x0000, 0x00000000),
        (H_GROUPS,     0x0D, 0x00, 0x0018, 0x00000003),
        (0x00000100,   0x0B, 0x07, 0x0000, 0x00000000),
        (H_INTERIORS,  0x0D, 0x00, 0x0028, 0x00000005),
    ]),
    H_REGIONDEF: (0x40, [
        (H_NAME,      0x0B, 0x08, 0x0000, 0x00000000),
        (H_AABBFIELD, 0x0C, 0x00, 0x0010, H_AABB),
    ]),
    H_AABB: (0x20, [
        (H_MIN, 0x15, 0x00, 0x0000, 0x00000000),
        (H_MAX, 0x15, 0x00, 0x0010, 0x00000000),
    ]),
    H_GROUP: (0x08, [
        (H_NAME,    0x0B, 0x07, 0x0000, 0x00000000),
        (H_ENABLED, 0x00, 0x00, 0x0004, 0x00000000),
    ]),
}
# Interchange (nopixel) PSCH struct emission order:
REFERENCE_SCHEMA_ORDER = [H_AABB, H_REGIONDEF, H_GROUP, H_MANIFEST]

class PsoError(Exception):
    pass

# ---------------------------------------------------------------- model
class Region:
    __slots__ = ('name', 'name_hash', 'mn', 'mx')
    def __init__(self, name, mn, mx, name_hash=None):
        self.name = name                       # str or None (hash-only)
        self.name_hash = name_hash if name_hash is not None else joaat_lower(name)
        self.mn = tuple(mn)                    # 4 floats (w always 0 in samples)
        self.mx = tuple(mx)
    def __repr__(self):
        return f'Region({self.name or hex(self.name_hash)}, {self.mn[:3]}, {self.mx[:3]})'

class Manifest:
    def __init__(self):
        self.regions = []            # [Region]
        self.groups = []             # [(nameHash, enabledBool)]
        self.interiors = []          # [nameHash]
        self.sections = []           # [(fourcc, off, size)] as read
        self.blocks = []             # [(blockId, off, size)] as read
        self.unk0 = 0                # manifest +0 field

# ---------------------------------------------------------------- reader
def _sections(d):
    out, off = [], 0
    while off < len(d):
        if off + 8 > len(d):
            raise PsoError(f'trailing {len(d)-off} bytes are not a section header')
        ident = d[off:off+4]
        size = struct.unpack('>I', d[off+4:off+8])[0]
        if size < 8 or off + size > len(d):
            raise PsoError(f'section {ident!r} at {off:#x} has bad size {size:#x}')
        out.append((ident.decode('ascii'), off, size))
        off += size
    return out

def _parse_pschema(payload):
    """Return {structHash: (size, [entries])} and the emission order."""
    n = struct.unpack('>I', payload[0:4])[0]
    table = [struct.unpack('>II', payload[4+8*i:12+8*i]) for i in range(n)]
    out, order = {}, []
    for shash, secoff in table:
        p = secoff - 8                       # offsets are section-relative (incl. header)
        cnt, size, zero = struct.unpack('>III', payload[p:p+12])
        if zero != 0:
            raise PsoError(f'struct def {shash:#x}: third header dword {zero:#x} != 0')
        ents = []
        for i in range(cnt):
            e = payload[p+12+12*i:p+24+12*i]
            nh, ty, sub, off_, extra = struct.unpack('>IBBHI', e)
            ents.append((nh, ty, sub, off_, extra))
        out[shash] = (size, ents)
        order.append(shash)
    return out, order

def _ptr(v):
    return (v & 0xFFF), (v >> 12)            # (1-based block, byte offset)

def read_manifest(path_or_bytes, strict_schema=True):
    d = path_or_bytes if isinstance(path_or_bytes, (bytes, bytearray)) \
        else open(path_or_bytes, 'rb').read()
    m = Manifest()
    m.sections = _sections(d)
    sec = {s[0]: (s[1], s[2]) for s in m.sections}
    for need in ('PSIN', 'PMAP', 'PSCH'):
        if need not in sec:
            raise PsoError(f'missing section {need}')
    # PMAP
    po, ps = sec['PMAP']
    root_idx, nblk = struct.unpack('>IH', d[po+8:po+14])
    m.blocks = [struct.unpack('>IIII', d[po+16+16*i:po+32+16*i])[0:4] for i in range(nblk)]
    m.blocks = [(b[0], b[1], b[3]) for b in m.blocks]
    blocks = m.blocks
    if not (1 <= root_idx <= nblk):
        raise PsoError(f'root block index {root_idx} out of range')
    # PSCH — verify it matches the measured schema (semantically)
    so, ss = sec['PSCH']
    try:
        schema, _order = _parse_pschema(d[so+8:so+ss])
    except (struct.error, IndexError) as e:
        raise PsoError(f'PSCH does not parse as a manifest schema ({e}) — '
                       f'this PSO is not a CScenarioPointManifest') from None
    if strict_schema:
        for shash, (size, ents) in SCHEMA.items():
            if shash not in schema:
                raise PsoError(f'schema missing struct {shash:#x}')
            if schema[shash] != (size, ents):
                raise PsoError(f'schema for {shash:#x} differs from measured layout: '
                               f'{schema[shash]!r}')
    # STRF -> hash -> string
    strings = {}
    if 'STRF' in sec:
        fo, fs = sec['STRF']
        for s in d[fo+8:fo+fs].rstrip(b'\x00').split(b'\x00'):
            if s:
                strings[joaat(s.lower())] = s.decode('latin1')
    def bslice(idx1):
        # A NULL POINTER USED TO RESOLVE TO THE LAST BLOCK (2026-08-03). `_ptr(0)` yields block
        # index 0, and `blocks[0-1]` is Python's `blocks[-1]` - the u32-hash pool - so a zero
        # pointer silently dereferenced into unrelated data instead of being rejected.
        # COST, measured on the whole-game filebase, _resolved/ymt/sp_manifest.ymt: zeroing region[0]'s
        # entry in the pointer pool and the 12 incidental guard bytes made the read SUCCEED and
        # hand back Region(0x9bc3ca0a, min=(-87673.6, -1.05e+36, 3.06e-17),
        # max=(-1.8e-15, 53244.6, 8.07e+32)) - a fabricated scenario volume, no error anywhere.
        # Only the accidental `Name bytes 4..15 nonzero` padding check stopped the un-doctored
        # case. Vanilla data never hits this; an authored or damaged manifest can.
        if not (1 <= idx1 <= len(blocks)):
            raise PsoError('block index %d out of range 1..%d (null or corrupt pointer)'
                           % (idx1, len(blocks)))
        bid, boff, bsize = blocks[idx1-1]
        return boff, bsize
    def deref(ptrval, need_size):
        blk, off = _ptr(ptrval)
        boff, bsize = bslice(blk)
        if off + need_size > bsize:
            raise PsoError(f'pointer {ptrval:#x} overruns block {blk}')
        return boff + off
    # root CScenarioPointManifest
    rid, roff, rsize = blocks[root_idx-1]
    if rid != H_MANIFEST or rsize != 0x38:
        raise PsoError(f'root block is {rid:#x} size {rsize:#x}, expected manifest 0x38')
    m.unk0 = struct.unpack('>I', d[roff:roff+4])[0]
    if m.unk0 != 0 or d[roff+4:roff+8] != b'\x00'*4:
        raise PsoError(f'manifest field 4d0537bb nonzero ({d[roff:roff+8].hex()}) — unmapped')
    def read_array(aoff):
        ptrval, _pad, cnt, cap = struct.unpack('>IIHH', d[aoff:aoff+12])
        return ptrval, cnt, cap
    # RegionDefs: array of pointers to CScenarioPointRegionDef
    ptrval, cnt, cap = read_array(roff+0x08)
    if cnt != cap:
        raise PsoError(f'RegionDefs count {cnt} != capacity {cap}')
    pbase = deref(ptrval, cnt*8) if cnt else None
    for i in range(cnt):
        pv, pad = struct.unpack('>II', d[pbase+8*i:pbase+8*i+8])
        if pad:
            raise PsoError('pointer pad nonzero')
        io = deref(pv, 0x40)
        nh = struct.unpack('>I', d[io:io+4])[0]
        if d[io+4:io+16] != b'\x00'*12:
            raise PsoError(f'RegionDef[{i}] Name bytes 4..15 nonzero — unmapped')
        mn = struct.unpack('>4f', d[io+0x10:io+0x20])
        mx = struct.unpack('>4f', d[io+0x20:io+0x30])
        if d[io+0x30:io+0x40] != b'\x00'*16:
            raise PsoError(f'RegionDef[{i}] tail pad nonzero — unmapped')
        m.regions.append(Region(strings.get(nh), mn, mx, name_hash=nh))
    # Groups: array of pointers to CScenarioPointGroup
    ptrval, cnt, cap = read_array(roff+0x18)
    if cnt != cap:
        raise PsoError(f'Groups count {cnt} != capacity {cap}')
    pbase = deref(ptrval, cnt*8) if cnt else None
    for i in range(cnt):
        pv, pad = struct.unpack('>II', d[pbase+8*i:pbase+8*i+8])
        io = deref(pv, 8)
        nh, en = struct.unpack('>IB', d[io:io+5])
        if d[io+5:io+8] != b'\x00'*3 or en not in (0, 1):
            raise PsoError(f'Group[{i}] tail/bool bytes unexpected: {d[io:io+8].hex()}')
        m.groups.append((nh, bool(en)))
    # InteriorNames: array of u32 hashes
    ptrval, cnt, cap = read_array(roff+0x28)
    if cnt != cap:
        raise PsoError(f'InteriorNames count {cnt} != capacity {cap}')
    hbase = deref(ptrval, cnt*4) if cnt else None
    m.interiors = [struct.unpack('>I', d[hbase+4*i:hbase+4*i+4])[0] for i in range(cnt)]
    return m

# ---------------------------------------------------------------- writer (interchange)
def _emit_pschema(order=REFERENCE_SCHEMA_ORDER):
    head = struct.pack('>I', len(order))
    defs, offs = b'', {}
    base = 8 + 4 + 8*len(order)              # section-relative offset of first def
    for shash in order:
        size, ents = SCHEMA[shash]
        offs[shash] = base + len(defs)
        defs += struct.pack('>III', len(ents), size, 0)
        for nh, ty, sub, off_, extra in ents:
            defs += struct.pack('>IBBHI', nh, ty, sub, off_, extra)
    table = b''.join(struct.pack('>II', h, offs[h]) for h in order)
    payload = head + table + defs
    return b'PSCH' + struct.pack('>I', 8 + len(payload)) + payload

def write_manifest(m):
    """Emit interchange bytes: PSIN+PMAP+PSCH+STRF, blocks [regions, ptrs, groups,
    hashes, manifest], tightly packed, strings in RegionDefs order."""
    nreg, ngrp, nint = len(m.regions), len(m.groups), len(m.interiors)
    # block sizes
    sz_reg = 0x40 * nreg
    sz_ptr = 8 * (nreg + ngrp)
    sz_grp = 8 * ngrp
    sz_hsh = 4 * nint
    sz_man = 0x38
    off_reg = 0x10
    off_ptr = off_reg + sz_reg
    off_grp = off_ptr + sz_ptr
    off_hsh = off_grp + sz_grp
    off_man = off_hsh + sz_hsh
    psin_size = off_man + sz_man
    def ptrv(block, off):
        return (off << 12) | block
    # block payloads
    breg = b''.join(
        struct.pack('>I', r.name_hash) + b'\x00'*12 +
        struct.pack('>4f', *r.mn) + struct.pack('>4f', *r.mx) + b'\x00'*16
        for r in m.regions)
    bptr = b''.join(struct.pack('>II', ptrv(1, 0x40*i), 0) for i in range(nreg)) + \
           b''.join(struct.pack('>II', ptrv(3, 8*i), 0) for i in range(ngrp))
    bgrp = b''.join(struct.pack('>IB3x', nh, 1 if en else 0) for nh, en in m.groups)
    bhsh = b''.join(struct.pack('>I', h) for h in m.interiors)
    def arr(ptrval, cnt):
        return struct.pack('>IIHHI', ptrval, 0, cnt, cnt, 0)
    bman = struct.pack('>II', 0, 0) + \
           arr(ptrv(2, 0), nreg) + arr(ptrv(2, 8*nreg), ngrp) + arr(ptrv(4, 0), nint)
    psin = b'PSIN' + struct.pack('>I', psin_size) + b'\x00'*8 + \
           breg + bptr + bgrp + bhsh + bman
    assert len(psin) == psin_size
    # PMAP: root = block 5 (manifest), 5 blocks
    ents = [(H_REGIONDEF, off_reg, sz_reg), (BLK_PTR, off_ptr, sz_ptr),
            (H_GROUP, off_grp, sz_grp), (BLK_HASH, off_hsh, sz_hsh),
            (H_MANIFEST, off_man, sz_man)]
    pmap_payload = struct.pack('>IHH', 5, len(ents), 0x7070) + \
        b''.join(struct.pack('>IIII', bid, boff, 0, bsz) for bid, boff, bsz in ents)
    pmap = b'PMAP' + struct.pack('>I', 8 + len(pmap_payload)) + pmap_payload
    psch = _emit_pschema()
    # STRF: region name strings in array order
    for r in m.regions:
        if r.name is None:
            raise PsoError(f'region {r.name_hash:#x} has no name string — cannot emit STRF')
    spool = b''.join(r.name.encode('latin1') + b'\x00' for r in m.regions)
    strf = b'STRF' + struct.pack('>I', 8 + len(spool)) + spool
    return psin + pmap + psch + strf

# ---------------------------------------------------------------- patcher
def patch_manifest(vanilla, additions, replace_by_basename=True):
    """vanilla: path/bytes of a stock sp_manifest.ymt.
    additions: iterable of (regionPath, (minx,miny,minz), (maxx,maxy,maxz)) —
      regionPath e.g. 'compcache:/my_resource/my_region'.
    If replace_by_basename, an addition whose final path component matches a vanilla
    region's basename REPLACES it in place (that is how a streamed override must be
    routed: two manifest entries for one region silently break scenarios).
    Returns interchange bytes.  Conventions measured on the production nopixel manifest:
    names are lowercased; brand-new regions go FIRST (alphabetical), then the vanilla
    array order is preserved."""
    m = read_manifest(vanilla)
    def basename(p):
        return p.rsplit('/', 1)[-1].lower()
    regions = OrderedDict((basename(r.name), Region(r.name.lower(), r.mn, r.mx))
                          for r in m.regions)
    if len(regions) != len(m.regions):
        raise PsoError('vanilla manifest has duplicate region basenames')
    new = OrderedDict()
    for name, mn, mx in additions:
        name = name.lower()
        mn, mx = tuple(mn), tuple(mx)
        if len(mn) == 3: mn = mn + (0.0,)
        if len(mx) == 3: mx = mx + (0.0,)
        b = basename(name)
        if b in regions:
            if not replace_by_basename:
                raise PsoError(f'region basename {b} already routed; two entries for '
                               f'one region silently break scenarios')
            regions[b] = Region(name, mn, mx)
        else:
            new[b] = Region(name, mn, mx)
    out = Manifest()
    out.regions = [new[k] for k in sorted(new, key=str)] + list(regions.values())
    out.groups = list(m.groups)
    out.interiors = list(m.interiors)
    return write_manifest(out)

def _dump(path):
    """Human-readable inspection of one manifest (the module's original entry point)."""
    import json
    m = read_manifest(path)
    print(json.dumps({
        'sections': [(s[0], s[1], s[2]) for s in m.sections],
        'counts': {'regions': len(m.regions), 'groups': len(m.groups),
                   'interiors': len(m.interiors)},
        'regions': [{'name': r.name or f'{r.name_hash:#010x}',
                     'min': r.mn[:3], 'max': r.mx[:3]} for r in m.regions],
    }, indent=1))


# ---------------------------------------------------------------- regression entry point
# `python pso_manifest.py --selftest`
# ⚠ THE RIGHT ORACLE IS A PRODUCTION MANIFEST, NOT A VANILLA ONE. This writer emits the
# layout a real server ships (PSIN+PMAP+PSCH+STRF); Rockstar's own files additionally carry
# PSIG/STRE/CHKS, which are absent from every working community manifest and whose formats are
# unrecovered. So a vanilla file round-trips SMALLER by design and that is NOT a defect - the
# meaningful proof is that a manifest known to load in game reproduces byte for byte.
if __name__ == "__main__":
    import argparse
    import os as _os
    import sys as _sys

    ap = argparse.ArgumentParser(prog="pso_manifest")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--dump", metavar="FILE", help="print one manifest as JSON")
    ap.add_argument("--manifest", action="append", default=[],
                    help="sp_manifest.ymt to round-trip (repeatable). Prefer a PRODUCTION one.")
    a = ap.parse_args()
    if a.dump:
        _dump(a.dump)
        _sys.exit(0)
    if not a.selftest:
        ap.error("nothing to do - pass --selftest [--manifest <file>] or --dump <file>")

    paths = list(a.manifest)
    if not paths:
        ap.error("no manifest given: pass --manifest <sp_manifest.ymt> (a server's own file is "
                 "the correct oracle; a vanilla Rockstar manifest legitimately round-trips "
                 "smaller because PSIG/STRE/CHKS are not emitted)")
    rc = noted = 0
    for p in paths:
        if not _os.path.isfile(p):
            print(f"  MISSING {p}")
            rc = 1
            continue
        blob = open(p, "rb").read()
        # A GATE THAT CRIES WOLF GETS IGNORED (fixed 2026-08-03). This used to score every file on
        # byte identity alone, so the stock Rockstar manifest - which the header above already
        # documents as legitimately round-tripping SMALLER - printed DIFF / SELFTEST FAILED and
        # exited 1. Measured on the whole-game filebase, _resolved/ymt/sp_manifest.ymt: input carries
        # PSIN+PMAP+PSCH+PSIG+STRF+STRE+CHKS (27,264 B), output PSIN+PMAP+PSCH+STRF (21,532 B), so
        # byte identity is impossible BY CONSTRUCTION. Cost: the only documented command for this
        # module reported the writer as broken when it was correct, which is how a REAL pso
        # regression gets waved through as "the expected failure". The two properties that ARE
        # meaningful on a vanilla file both hold and are what NOTE now asserts.
        try:
            m = read_manifest(blob)
            out = write_manifest(m)
            if out == blob:
                verdict = "OK  "
                note = ""
            elif any(s[0] in ("PSIG", "STRE", "CHKS") for s in m.sections):
                m2 = read_manifest(out)

                def _model(x):
                    return ([(r.name, r.name_hash, r.mn, r.mx) for r in x.regions],
                            list(x.groups), list(x.interiors), x.unk0)

                if _model(m) == _model(m2) and write_manifest(m2) == out:
                    verdict = "NOTE"
                    note = ("  (vanilla: PSIG/STRE/CHKS are unrecovered so the interchange layout "
                            "is emitted instead - model round-trip and writer fixpoint verified, "
                            f"{len(blob)} -> {len(out)} bytes)")
                else:
                    verdict = "DIFF"
                    note = "  (vanilla, and the model did NOT survive write->read - a real defect)"
            else:
                verdict = "DIFF"
                note = ""
        except Exception as e:
            print(f"  ERROR   {p}: {type(e).__name__}: {e}")
            rc = 1
            continue
        cc = sum(1 for r in m.regions
                 if str(getattr(r, "name", "")).lower().startswith("compcache"))
        print(f"  {verdict}  {_os.path.basename(p)}  regions={len(m.regions)} "
              f"compcache={cc} bytes={len(blob)}{note}")
        if verdict == "DIFF":
            rc = 1
        noted += (verdict == "NOTE")
    if rc == 0:
        print("SELFTEST PASSED" + (" (%d file(s) PASSED WITH NOTE - see above; byte identity is "
                                   "not achievable on a vanilla manifest)" % noted if noted else ""))
    else:
        print("SELFTEST FAILED")
    _sys.exit(rc)
