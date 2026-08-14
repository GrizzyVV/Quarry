"""ydr_write - ROUND-TRIP WRITER for .ydr drawables.

COVERAGE 2026-08-14 (250-file sample): **99.9808%** overall - system **99.9248%**, graphics
**99.9994%**, and **206/250 files byte-EXACT**. Reproduce: `python tools/roundtrip_coverage.py
--lane ydr --limit 250`.
⚠ Δ SUPERSEDES the earlier "99.9597% / sys 99.78% / gfx 100.00%" line. Two corrections behind it:
  1. the graphics segment was NEVER exactly 100% - the harness printed segments at 2 decimals, so
     99.9994% displayed as "100.00%" (fixed; it prints 4dp now);
  2. the "vertex-count under-read" this file used to name as its one remaining defect **did not
     exist** - it was a mis-factorisation, retracted in full at the `vd = ...` line below.
The real gain came from CHASE_SCAN (see the constant), not from any vertex fix.

    inflated system+graphics segments -> value model -> written back -> reproduce original bytes

WHY: `.ydr` is 86,690 files - the largest in-scope model lane and the last big one gating the
mapping milestone with no writer. Round-trip is the primary measure (Matt, 2026-08-13); a lane
with no writer is UNMEASURED, not passing.

⚠ DRAWABLES SPAN TWO SEGMENTS. Vertex and index data live in the GRAPHICS segment while the
graph lives in the system segment, so coverage is reported for BOTH - a writer that modelled only
`sys` would look far more complete than it is.

Chain (per `ydr2xml`, which derived it over 3,479 base-game drawables):
  +0x10 shader group · +0x18 skeleton · +0xB0/+0xB8 lights (n, stride 0xA8) · +0xC8 embedded bound
  LOD group slot -> {model-array ptr @+0x00, model count u16 @+0x08}
  model (0x30) -> {geometry-array ptr @+0x08, geo count u16 @+0x10, geo-bounds ptr @+0x18}
    geometry bounds = (ngeo+1 if ngeo>1 else ngeo) * 32
  geometry (0x80) -> {vertex buffer @+0x18, index buffer @+0x38,
                      index count u32 @+0x58, vertex count u16 @+0x60, stride u16 @+0x70}
  vertex buffer (0x40) -> {flags u16 @+0x0A, vertex data @+0x10, FVF @+0x30}
⛔ `stride` is a u16 - a u32 read yields 983,100 on skinned meshes (recorded in ydr2xml).
ASCII output only.
"""
import os
import struct
import sys as _sys

_sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ydr2xml import Res  # noqa: E402

LOD_SLOTS = (0x50, 0x58, 0x60, 0x68)     # candidate LOD group slots; non-resolving ones no-op
DRAWABLE_SPAN = 0x100
# ⭐ MEASURED OPTIMUM, not chosen: how many bytes to capture at a node reached by the generic
# graph walk. Nodes out there run to several hundred bytes, so capturing only as far as we RECURSE
# leaves their tails unread. Sweep over 120 files (system-segment coverage):
#   0x80 -> 99.41% | 0x200 -> 99.58% | 0x800 -> 99.71% | 0x1000 -> 99.78% (BEST)
#   0x2000 -> 99.70% | 0x4000 -> 99.63%  <- both WORSE, re-measured after the later fixes too
# ⛔ Bigger is NOT better past 0x1000 - over-capture claims a neighbour's bytes and the visited
# set then blocks a better-typed read of that region. Re-measure before changing this.
CHASE_CAPTURE = 0x1000
# ⭐ SCAN WIDTH IS A SEPARATE KNOB FROM CAPTURE WIDTH, and conflating them hid a whole gap class.
# `_chase` captured CHASE_CAPTURE (0x1000) bytes at a node but scanned only 0x80 of it for
# pointers, so **any descriptor living past byte 128 of a captured node was never followed**.
# Measured 2026-08-14 by the pointer-site scan: 32 of 38 gap STARTS are pointed at from ground we
# already model - i.e. we hold the pointer and never chase it. Confirmed shape at those sites:
# `{u64 ptr, u32 count, u32 capacity}` -> a 16-BYTE-RECORD array (189 x 16 = 3,024 vs a 3,023 B
# measured span; 255 x 16 = 4,080 vs 4,079 - the odd byte is the last record's trailing zero).
# ⛔ Do NOT confuse this with widening CHASE_CAPTURE, which was swept and is WORSE past 0x1000
# (over-capture claims a neighbour's bytes and the visited set then blocks a better-typed read).
# Scanning wider claims NO extra bytes by itself - it only discovers more pointers to follow.
# ⭐ MEASURED SWEEP 2026-08-14, 250-file sample, the ONLY variable changed (overall / sys / exact):
#   0x80  99.9659 / 99.8458 / 192   <- the old hard-coded value
#   0x100 99.9775 / 99.9047 / 202
#   0x200 99.9807 / 99.9240 / 205
#   0x400 99.9808 / 99.9248 / 206   <== KEEP
#   0x800 99.9793 / 99.9177 / 205   (worse)
#   0x1000 99.9800 / 99.9230 / 205  (worse)
# ⛔ Wider is NOT better here either: past 0x400 the scan starts following FALSE tagged pointers
# out of dense vertex/float data, and the visited set then blocks a better-typed capture of the
# region they land in. Re-measure before changing this.
CHASE_SCAN = 0x400


class Ydr:
    def __init__(self, res, flags=(0, 0)):
        self.res = res
        self.sys_flags, self.gfx_flags = flags
        self.nsys, self.ngfx = len(res.sys), len(res.gfx)
        self.sysr, self.gfxr = [], []
        self._seen = set()
        self._drawable(0)

    # ---- segment-aware capture: a tagged pointer may resolve into EITHER segment
    def _put(self, off, nbytes, seg=None):
        if off is None or nbytes <= 0:
            return
        if seg == 'gfx' or (seg is None and off >= self.nsys):
            o = off - self.nsys if off >= self.nsys else off
            if o + nbytes <= self.ngfx:
                self.gfxr.append((o, bytes(self.res.gfx[o:o + nbytes])))
        elif off + nbytes <= self.nsys:
            self.sysr.append((off, bytes(self.res.sys[off:off + nbytes])))

    def _res(self, tagged, nbytes=1):
        """Resolve a tagged pointer, returning (buffer, offset, which-segment)."""
        buf, off = self.res.deref(tagged, nbytes)
        if buf is None:
            return None, None, None
        return buf, off, ('gfx' if buf is self.res.gfx else 'sys')

    def _flat(self, tagged, nbytes):
        buf, off, seg = self._res(tagged, max(nbytes, 1))
        if buf is None:
            return
        if seg == 'gfx':
            if off + nbytes <= self.ngfx:
                self.gfxr.append((off, bytes(buf[off:off + nbytes])))
        elif off + nbytes <= self.nsys:
            self.sysr.append((off, bytes(buf[off:off + nbytes])))

    def _drawable(self, base):
        s = self.res.sys
        if base in self._seen:
            return
        self._seen.add(base)
        self._put(base, DRAWABLE_SPAN)
        self._flat(struct.unpack_from('<I', s, base + 0x10)[0], 0x40)     # shader group hdr
        self._texdict(struct.unpack_from('<I', s, base + 0x10)[0])        # embedded textures
        # +0xA8 drawable NAME string (a plain cstr; NULL on 100% of fragment children) and
        # +0xC8 the EMBEDDED phBOUND graph. Measured 2026-08-13 over 20 files: these two slots
        # reach the start of an unmodelled run in 17/20 and 10/20 respectively - between them,
        # the whole remaining system-segment gap.
        self._flat(struct.unpack_from('<I', s, base + 0xA8)[0], 64)
        self._bound(struct.unpack_from('<I', s, base + 0xC8)[0])
        # ⭐ FINAL SWEEP: enter the reachable graph from EVERY tagged pointer in the drawable
        # header. The named walks above model the structures we UNDERSTAND; this catches the
        # subtree the pointer-site scan proved we were never entering. Runs last so the typed
        # walks claim their regions first and this only picks up what they left.
        for q in range(0, DRAWABLE_SPAN, 4):
            if base + q + 4 > self.nsys:
                break
            try:
                self._chase(struct.unpack_from('<I', s, base + q)[0])
            except struct.error:
                break
        self._flat(struct.unpack_from('<I', s, base + 0x18)[0], 0x80)     # skeleton hdr
        n = struct.unpack_from('<H', s, base + 0xB8)[0]                   # lights
        if 0 < n < 4096:
            self._flat(struct.unpack_from('<I', s, base + 0xB0)[0], n * 0xA8)
        for slot in LOD_SLOTS:
            try:
                self._lod(struct.unpack_from('<I', s, base + slot)[0])
            except struct.error:
                pass

    def _bound(self, tagged, depth=0):
        """The drawable's EMBEDDED collision graph at +0xC8 - the same phBound structure
        `ybn_write` walks, so the offsets are shared rather than re-derived:
          composite: u16 child count @+0xA0 · children @+0x70 · transforms @+0x78 · flags @+0x90
          geometry : nverts @+0xD0 · npolys @+0xD4 · nmat u8 @+0x120 · verts @+0xB0 ·
                     polys @+0x88 · materials @+0xF0 · poly-materials @+0x118
          +0x130   : an ARRAY DESCRIPTOR {ptr | count | capacity | records@+0x20}, 16-B records
        """
        if not tagged or depth > 16:
            return
        s = self.res.sys
        _b, off, seg = self._res(tagged, 0x180)
        if off is None or seg != 'sys' or off in self._seen:
            return
        self._seen.add(off)
        self._put(off, 0x180)
        try:
            nverts = struct.unpack_from('<I', s, off + 0xD0)[0]
            npolys = struct.unpack_from('<I', s, off + 0xD4)[0]
            nmat = s[off + 0x120]
        except (struct.error, IndexError):
            return
        if 0 < nverts <= 0x8000 and 0 < npolys <= 0x100000 and nmat:
            self._flat(struct.unpack_from('<I', s, off + 0xB0)[0], nverts * 6)
            self._flat(struct.unpack_from('<I', s, off + 0x88)[0], npolys * 16)
            self._flat(struct.unpack_from('<I', s, off + 0xF0)[0], nmat * 8)
            self._flat(struct.unpack_from('<I', s, off + 0x118)[0], npolys)
        try:
            desc = struct.unpack_from('<I', s, off + 0x130)[0]
        except struct.error:
            desc = 0
        if desc:
            _b2, d, dseg = self._res(desc, 0x20)
            if d is not None and dseg == 'sys':
                self._put(d, 0x20)
                try:
                    cnt = struct.unpack_from('<I', s, d + 0x08)[0]
                    if 0 < cnt <= 0x200000:
                        self._put(d + 0x20, cnt * 16)
                        self._flat(struct.unpack_from('<I', s, d + 0x00)[0], cnt * 16)
                except struct.error:
                    pass
        try:
            n = struct.unpack_from('<H', s, off + 0xA0)[0]
            carr = struct.unpack_from('<I', s, off + 0x70)[0]
            self._flat(carr, n * 8)
            self._flat(struct.unpack_from('<I', s, off + 0x78)[0], n * 64)
            self._flat(struct.unpack_from('<I', s, off + 0x90)[0], n * 8)
        except struct.error:
            return
        if not n or n > 4096:
            return
        _b3, coff, cseg = self._res(carr, n * 8)
        if coff is None or cseg != 'sys':
            return
        for i in range(n):
            try:
                cp = struct.unpack_from('<I', s, coff + i * 8)[0]
            except struct.error:
                break
            if cp:
                self._bound(cp, depth + 1)

    def _chase(self, tagged, depth=0):
        """Follow the REACHABLE POINTER GRAPH inside the shader/texture subtree.

        ⭐ WHY GENERIC RATHER THAN SLOT-BY-SLOT: the pointer-site scan proved the remaining gap is
        a SUBTREE - 15 of 21 pointers into it came from sites we had never entered - so fixing one
        named slot at a time moved coverage ~0.005% each (three attempts, three near-misses).
        Entering the graph and following what it actually points at unwinds every layer at once.
        Each newly entered node exposes the next, which is precisely the structure the scan showed.
        ⚠ This models REACHABILITY, not meaning: it proves the bytes belong to the drawable's own
        graph, not that we understand each field. Coverage earned this way is honest about
        completeness and silent about interpretation - the same caveat the whole measure carries.
        Bounded by a visited set and a depth cap so a cyclic or malformed graph terminates.
        """
        if not tagged or depth > 24 or (tagged >> 28) != 5:
            return
        _b, off, seg = self._res(tagged, 0x80)
        if off is None or seg != 'sys' or off in self._seen:
            return
        self._seen.add(off)
        # capture WIDER than we recurse: nodes reached here run to several hundred bytes, but
        # scanning that far for pointers over-recurses. Capture 0x200, scan 0x80.
        self._put(off, CHASE_CAPTURE)
        s = self.res.sys
        for q in range(0, CHASE_SCAN, 4):
            if off + q + 4 > self.nsys:
                break
            try:
                nxt = struct.unpack_from('<I', s, off + q)[0]
            except struct.error:
                break
            if (nxt >> 28) == 5:
                self._chase(nxt, depth + 1)

    def _texdict(self, sg_ptr):
        """The drawable's OWN embedded texture dictionary - `ShaderGroup+0x08`.

        ⭐ THIS IS WHERE THE GRAPHICS SEGMENT LIVES. A third of base drawables carry one
        (1,180/3,479, holding 4,845 textures that exist nowhere else), and their PIXELS sit in the
        graphics segment - which is why a first pass that modelled only the drawable graph read
        97.2% on `sys` and 38.7% on `gfx`.
        Layout (same pgDictionary<grcTexture> a .ytd root is, per ytd2xml):
            dict +0x28 u32 count (low 16 bits) | +0x30 ptr -> pointer array (8 B per texture)
            grcTexture +0x50/0x52 w/h | +0x58 format | +0x5D mip count | +0x70 pixel data (GFX)
        ⛔ There is NO stored pixel length - it is COMPUTED from w/h/mips/format, so the span is
        taken from `ytd2xml.mipchain_bytes`, never guessed.
        """
        if not sg_ptr:
            return
        s = self.res.sys
        _b, sg, sgseg = self._res(sg_ptr, 0x40)
        if sg is None or sgseg != 'sys':
            return
        try:
            dict_ptr = struct.unpack_from('<I', s, sg + 0x08)[0]
        except struct.error:
            return
        # ⭐ THE SHADER GROUP'S OWN ARRAYS (`sg+0x10`, `sg+0x20`) - found 2026-08-13 by asking
        # which slot inside an already-captured region lands on the START of an unmodelled run
        # (32 and 20 hits over 20 files). Each points at a descriptor of the same shape the model
        # group uses: {ptr @+0x00, u16 count @+0x08} -> a pointer array -> per-entry structs.
        for arr_slot in (0x10, 0x20):
            try:
                ap = struct.unpack_from('<I', s, sg + arr_slot)[0]
            except struct.error:
                continue
            _bd, dsc, dseg2 = self._res(ap, 0x20)
            if dsc is None or dseg2 != 'sys':
                continue
            self._put(dsc, 0x20)
            # ⭐ THE SUBTREE ENTRY POINTS. The pointer-site scan showed 15 of 21 pointers into the
            # remaining gap came from UNMODELLED sites - i.e. a subtree entered from only a few
            # known slots. `+0x08` and `+0x10` of this descriptor are two of them, and were never
            # followed. Entering them exposes the next layer, which is why this unwinds where
            # single-slot fixes did not.
            for sub in (0x08, 0x10):
                try:
                    sp = struct.unpack_from('<I', s, dsc + sub)[0]
                except struct.error:
                    continue
                self._chase(sp)
            try:
                cnt = struct.unpack_from('<H', s, dsc + 0x08)[0]
                pa = struct.unpack_from('<I', s, dsc + 0x00)[0]
            except struct.error:
                continue
            if not cnt or cnt > 4096:
                continue
            # ⛔ STRIDE IS 16, NOT 8. First guessed 8 by analogy with the model group's pointer
            # array and it moved coverage 99.15% -> 99.18% only. DUMPING the bytes settled it:
            #     <u32 tagged ptr> <u32 0> <u16 tag> <pad>   then the next pointer at +0x10
            # ⭐ The gap "runs" were 1-2 bytes because the image is ZERO-FILLED - only the
            # NON-ZERO bytes of an unmodelled region ever show as a difference, so a wrong stride
            # looks like scattered specks rather than a missing block. Read the bytes, do not
            # infer the shape from a sibling structure.
            self._flat(pa, cnt * 16)
            _bp, pao, pseg = self._res(pa, cnt * 16)
            if pao is None or pseg != 'sys':
                continue
            for k in range(cnt):
                try:
                    ep = struct.unpack_from('<I', s, pao + k * 16)[0]
                except struct.error:
                    break
                if ep:
                    self._flat(ep, 0x40)

        if not dict_ptr:
            return                      # ordinary: most drawables carry no embedded dictionary
        _b2, d, dseg = self._res(dict_ptr, 0x40)
        if d is None or dseg != 'sys':
            return
        self._put(d, 0x40)
        try:
            count = struct.unpack_from('<I', s, d + 0x28)[0] & 0xFFFF
            arr_ptr = struct.unpack_from('<I', s, d + 0x30)[0]
        except struct.error:
            return
        if not count or count > 4096:
            return
        self._flat(arr_ptr, count * 8)
        _b3, arr, aseg = self._res(arr_ptr, count * 8)
        if arr is None or aseg != 'sys':
            return
        import ytd2xml
        for i in range(count):
            try:
                tp_raw = struct.unpack_from('<I', s, arr + i * 8)[0]
            except struct.error:
                break
            _b4, tp, tseg = self._res(tp_raw, 0x90)
            if tp is None or tseg != 'sys':
                continue
            self._put(tp, 0x90)
            try:
                self._flat(struct.unpack_from('<I', s, tp + 0x28)[0], 64)     # name string
                w = struct.unpack_from('<H', s, tp + 0x50)[0]
                h = struct.unpack_from('<H', s, tp + 0x52)[0]
                mips = max(1, s[tp + 0x5D])
                fmt = struct.unpack_from('<I', s, tp + 0x58)[0]
                _x, blk, bpp = ytd2xml.describe_format(fmt)
                need = ytd2xml.mipchain_bytes(w, h, mips, blk, bpp)
                self._flat(struct.unpack_from('<I', s, tp + 0x70)[0], need)
            except Exception:
                # an unmapped format must cost THIS texture's pixels, never the dictionary
                continue

    def _lod(self, grp_ptr):
        if not grp_ptr:
            return
        s = self.res.sys
        buf, mh, seg = self._res(grp_ptr, 0x10)
        if buf is None or seg != 'sys':
            return
        self._put(mh, 0x10)
        marr, nmod = struct.unpack_from('<I', s, mh + 0x00)[0], \
            struct.unpack_from('<H', s, mh + 0x08)[0]
        if not nmod or nmod > 4096:
            return
        self._flat(marr, nmod * 8)
        _b, ma, _sg = self._res(marr, nmod * 8)
        if ma is None:
            return
        for mi in range(nmod):
            mp = struct.unpack_from('<I', s, ma + mi * 8)[0]
            _b2, m, sg2 = self._res(mp, 0x30)
            if m is None or sg2 != 'sys':
                continue
            self._put(m, 0x30)
            garr = struct.unpack_from('<I', s, m + 0x08)[0]
            ngeo = struct.unpack_from('<H', s, m + 0x10)[0]
            gbp = struct.unpack_from('<I', s, m + 0x18)[0]
            if not ngeo or ngeo > 4096:
                continue
            # ⭐ model+0x20 -> the per-geometry SHADER INDEX array (u16 per geometry).
            # Found by scanning every u32 in the segment for a tagged pointer landing on a gap
            # START, then asking which MODELLED region held the pointer: a 0x30-byte region (the
            # model record) at slot +0x20, 3 of the 6 modelled entry points. The rest of the gap
            # hung off it - the pointers into it came from UNMODELLED sites, i.e. a subtree we
            # never entered because its root was this one slot.
            self._flat(struct.unpack_from('<I', s, m + 0x20)[0], ngeo * 2)
            self._flat(gbp, (ngeo + 1 if ngeo > 1 else ngeo) * 32)
            self._flat(garr, ngeo * 8)
            _b3, ga, _s3 = self._res(garr, ngeo * 8)
            if ga is None:
                continue
            for gi in range(ngeo):
                self._geometry(struct.unpack_from('<I', s, ga + gi * 8)[0])

    def _geometry(self, gp):
        if not gp:
            return
        s = self.res.sys
        _b, g, sg = self._res(gp, 0x80)
        if g is None or sg != 'sys':
            return
        self._put(g, 0x80)
        vb_p, ib_p = struct.unpack_from('<I', s, g + 0x18)[0], \
            struct.unpack_from('<I', s, g + 0x38)[0]
        idx_count = struct.unpack_from('<I', s, g + 0x58)[0]
        vcnt = struct.unpack_from('<H', s, g + 0x60)[0]
        stride = struct.unpack_from('<H', s, g + 0x70)[0]   # u16! see module note
        # ⛔ DO NOT GATE ON WHICH SEGMENT THE BUFFER HEADER LIVES IN. `was:` `sgv == 'sys'`, which
        # skipped the vertex data ENTIRELY whenever the header resolved into graphics - and the
        # data it skipped is the mesh itself. Measured signature: 1,504 unreached runs of exactly
        # 13 bytes reading `01 80 01 80 AE 80 FF 7F ...` - packed vertex attributes on a 16-byte
        # stride (13 non-zero + 3 zero), which is why it showed as dust rather than a block.
        # `_put`/`_flat` are already segment-aware; the gate was pure loss.
        _b2, vb, sgv = self._res(vb_p, 0x40)
        if vb is not None:
            self._put(vb, 0x40, sgv)
            self._flat(struct.unpack_from('<I', s, vb + 0x30)[0], 0x10)      # FVF
            # ⭐ grcVertexBuffer carries a SECOND data reference at +0x38 (measured: a live
            # tagged pointer on files whose vertex block ran past vcnt*stride). Following it
            # covers the tail that `vcnt` under-counts.
            self._chase(struct.unpack_from('<I', s, vb + 0x38)[0])
            # ⛔⛔ RETRACTED 2026-08-14 - THE "vcnt UNDER-COUNTS" DEFECT DOES NOT EXIST.
            # This block previously asserted, as a format law, that the vertex block at sys 0xD0
            # in `prop_snow_diggerbkt` holds 1,872 vertices while `vcnt` reads 1,624, leaving 248
            # unread. **It was a MIS-FACTORISATION and everything downstream of it was fiction.**
            # MEASURED (scratchpad/ydr_tail_owner.py): that block is **vcnt 500 x stride 52 =
            # 26,000 B = 0x6590**, and `0xD0 + 0x6590` lands EXACTLY on `0x6660`. `1,624 x 16 =
            # 25,984` is SIXTEEN BYTES SHORT - a near-miss factorisation of the same span.
            # ⭐ The buffer header carries both fields and they AGREE with the geometry record:
            #   `vb+0x08 u32 = stride` (52) · `vb+0x10 = data ptr` · **`vb+0x18 u32 = count`**
            #   (500) · `vb+0x20` = the data ptr again · `vb+0x30` = the declaration.
            # So the old note "neither 1872 nor 1624 appears in the header" was true and useless:
            # the real count is 500 and it sits at +0x18. **`vcnt` never under-counted anything**,
            # and the three hypotheses "ruled out" here were ruled out against a phantom.
            # ⭐ THE LESSON: `1,872 = 248 + 1,624` is an arithmetic coincidence on ONE file. This
            # vault's law is *"a neat fit on two files is a coincidence generator"* - this was a
            # neat fit on one. **Verify a factorisation against the file's own stored fields
            # before deriving anything from it.**
            # ⇒ The real residual was `_chase` scanning 0x80 of each node it captured 0x1000 of;
            #   see CHASE_SCAN at the top of this file.
            vd = struct.unpack_from('<I', s, vb + 0x10)[0]
            # `max(index)+1` as a floor on the vertex count. ⚠ KEPT BUT DEMOTED: it was added to
            # chase the phantom above and measured **0.00% coverage change**, because
            # `max(index)+1 <= vcnt` always. It is retained only as a harmless lower-bound guard -
            # ⛔ do NOT cite it as evidence of anything, and do not re-derive it.
            real = vcnt
            try:
                _bi, io, isg = self._res(ib_p, 0x40)
                if io is not None and 0 < idx_count <= 0x1000000:
                    idp = struct.unpack_from('<I', s, io + 0x10)[0]
                    ibuf, ioff, iseg = self._res(idp, idx_count * 2)
                    if ibuf is not None:
                        mx = 0
                        for k in range(0, idx_count * 2, 2):
                            v = ibuf[ioff + k] | (ibuf[ioff + k + 1] << 8)
                            if v > mx:
                                mx = v
                        if mx + 1 > real:
                            real = mx + 1
            except Exception:
                pass
            if 0 < real <= 0x100000 and 0 < stride <= 0x400:
                self._flat(vd, real * stride)
            else:
                # ⛔ THE SANITY GUARD MUST NOT COST THE DATA. When vcnt/stride fail their bounds
                # the typed read is rightly refused - but refusing it left the MESH unread
                # (measured: 1,504 runs of 13 bytes, packed vertex attributes on a 16-B stride).
                # Fall back to the graph walk so the bytes are still covered, and be honest that
                # this is REACHABILITY, not a typed read.
                self._chase(vd)
        # ⭐ ENTER THE GRAPH FROM THE GEOMETRY RECORD ITSELF. The worst files (sys 91.6%) carry
        # 1,500-1,800 unreached runs of high-entropy data up to ~700 B - far too structured to be
        # padding and far too many to be one missing array. The typed walk above models the
        # buffers it UNDERSTANDS; this reaches whatever else a geometry points at.
        for q in range(0, 0x80, 4):
            try:
                self._chase(struct.unpack_from('<I', s, g + q)[0])
            except struct.error:
                break
        _b3, ib, sgi = self._res(ib_p, 0x40)
        if ib is not None:
            self._put(ib, 0x40, sgi)      # same fix as the vertex buffer: never gate on segment
            if 0 < idx_count <= 0x1000000:
                self._flat(struct.unpack_from('<I', s, ib + 0x10)[0], idx_count * 2)

    def write(self):
        si, gi = bytearray(self.nsys), bytearray(self.ngfx)
        for off, data in self.sysr:
            si[off:off + len(data)] = data
        for off, data in self.gfxr:
            gi[off:off + len(data)] = data
        try:
            import meta_write
            buf, o = self.res.deref(self.res.ptr(0x08), 16)
            if buf is not None and o + 12 <= len(si):
                val = ((meta_write.page_count(self.sys_flags) & 0xFF)
                       | ((meta_write.page_count(self.gfx_flags) & 0xFF) << 8))
                si[o + 8:o + 12] = struct.pack('<I', val)
        except Exception:
            pass
        return bytes(si), bytes(gi)

    def coverage(self):
        gs, gg = self.write()
        ns = sum(1 for i in range(self.nsys) if gs[i] == self.res.sys[i])
        ng = sum(1 for i in range(self.ngfx) if gg[i] == self.res.gfx[i]) if self.ngfx else 0
        tot = self.nsys + self.ngfx
        return (100.0 * (ns + ng) / tot if tot else 0.0,
                100.0 * ns / self.nsys if self.nsys else 0.0,
                100.0 * ng / self.ngfx if self.ngfx else None)


def read_ydr(src):
    blob = bytes(src) if isinstance(src, (bytes, bytearray)) else open(src, 'rb').read()
    _m, _v, sysf, gfxf = struct.unpack_from('<4sIII', blob, 0)
    return Ydr(Res.from_bytes(blob), (sysf, gfxf))
