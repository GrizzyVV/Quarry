"""yed_write - ROUND-TRIP WRITER for .yed expression dictionaries (RSC7 v25).

    inflated system segment -> value model -> written back -> MUST reproduce the original bytes

WHY: `.yed` had a READER (`yed2xml.py`) and no writer, which under the 2026-08-13 ruling makes it
**UNMEASURED, not passing** - `docs/LANE_CENSUS_20260814.md` row 9, 242 files.

MODEL, NOT MEMCPY, and there is not one byte-range copy in this file: every byte reproduced was
decoded through `pgdict_write.Model.rd()` with a struct format and re-packed from the decoded
value (`Model.carry()` is called ZERO times). Each record's field map TILES its stride, checked
at import, so a byte inside a record that no field covers stays zero. **The gaps are the finding.**

⚠ SCOPE: the INFLATED SYSTEM SEGMENT, not the compressed RSC7 container. `.yed` carries no
graphics segment (241/241 distinct payloads) and a non-empty one REFUSES.

=============================================================================================
⭐⭐ WHAT THE WRITER FOUND THAT THE READER COULD NOT - TWO WHOLE ARRAYS AND FOUR SCALARS.
`yed2xml`'s crExpression map runs +0x00 vtable / +0x20 Streams / +0x30 Tracks / +0x60 Name /
+0x70 (=1) / +0x74 Signature / +0x78 / +0x7c Unk7C, and that is everything the XML needs. Slot-
censused over ALL 241 distinct `.yed` in the game / **2,330 crExpression items**
(`scratchpad/probe_yed.py`), the record also carries:
    +0x40  atArray, LIVE on 100 of 2,330 items, capacity == count on 100/100
    +0x50  atArray, LIVE on   9 of 2,330 items, capacity == count on   9/9
    +0x68  u32, non-zero on 2,330/2,330 (a second signature-like hash)
    +0x6C/+0x80/+0x84/+0x88/+0x8C  u32, zero on 2,330/2,330
A reader may omit a field. A WRITER CANNOT - an omitted array is 100 items' worth of bytes left
at zero, and it is precisely the kind of gap a reader-only lane can never report.
⭐ THE RECORD SPAN IS PINNED BY THE ALLOCATION, not chosen: the room from an item to the next
live pointer target in its own file is EXACTLY 0x90 on **2,330 of 2,330** items - no item has
more room and none has less, so 0x90 is the only span that neither over-claims nor under-reads.
=============================================================================================

LAYOUT (all figures 2026-08-15, population = every `.yed` in the game):
    dictionary shell 0x00..0x40 ........ pgdict_write.SHELL_FIELDS
    crExpression, span 0x90 ............ ITEM_FIELDS below
    track record 4 B ................... u16 BoneId | u8 Track | u8 Format/UnkFlag
    crExpressionStream header 0x10 ..... u32 nameHash | u32 vecPoolBytes | u32 mainPoolBytes |
                                         u16 instructionCount | u16 Depth
      then: vector pool (vecPoolBytes) | main pool (mainPoolBytes) | opcode array (count bytes)
    ⭐ THE POOLS ARE WALKED PER INSTRUCTION, NOT CLAIMED AS TWO BLOBS. The opcode drives the
    operand kind (`yed2xml.OPS`), the kind drives how many bytes are decoded and AS WHAT, and
    both cursors must land EXACTLY on the declared pool ends or the file REFUSES. That is what
    makes byte identity here a statement about the INSTRUCTION SET rather than about two memcpys:
    a wrong opcode table desynchronises the cursors and the file refuses instead of passing.
=============================================================================================
COVERAGE AT POPULATION 2026-08-15 - THE LANE IS CLOSED. Every `.yed` in the game:
    EXACT round-trip (every byte of the inflated system segment) : **242 / 242 = 100.0000%**
    mean coverage 100.0000%   min 100.000%   residual 0 bytes   refusals 0
  BYTE ACCOUNT (the split that decides whether the 100% is worth anything):
    VALUE  37,608,521 B = 92.8014% (100% of it through NAMED fields)   re-encoded from a decoded value, never memcpy'd
    DERIVED 968 B = 0.0024%   the page-count word, COMPUTED from the RSC7 flags
    CARRIED 0 B = 0.0000% <- `Model.carry()` is called ZERO times in this lane
    ZERO-FILL 2,916,335 B = 7.1962%   never claimed; the ORIGINAL byte is zero (padding + block-map records)
    ZERO-RESIDUAL 0 bytes   never claimed and NON-ZERO in the original - the finding, and it is empty
  MUST-FAIL CONTROL (`python tools/pgdict_control.py --lane yed --limit 500 --cap 0`):
    VALUE  flip a decoded field ....... 12,007,232 / 12,007,232 moved the image (100.0000%)
    DROP   delete a claim ............. 6,323,226 / 12,007,232 (52.66%); every escape is a
           claim covering ONLY ZERO bytes - `blend_plane` 17.7 MB of zero float planes leads it
    OFFSET shift a claim one byte ..... 6,322,984 / 12,007,232 (52.66%), same population
    STRIDE patch a record stride ...... 4 mutations, **0 ESCAPED** on 242 files
           (spring table 160: 39 refused / 203 no subject | stream header 0x10: 242 refused |
            track stride 4: 7 broke + 235 refused | stream ptr stride 8: 179 refused / 63 none)
> REPRODUCE: `python tools/roundtrip_coverage.py --lane yed --limit 500 --cap 0`
=============================================================================================
ASCII output only.
"""
import os
import struct
import sys as _sys

_sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pgdict_write  # noqa: E402
from pgdict_write import Model, ModelError  # noqa: E402
from yed2xml import OPS  # noqa: E402  (opcode -> (name, operand kind); derived over 262,209
                         # instructions, every vote unanimous - see that module's header)

ITEM = 0x90
STREAM_HDR = 0x10

ITEM_FIELDS = (
    (0x00, '<Q', 'vtable'),
    (0x08, '<I', 'pad08'), (0x0C, '<I', 'pad0C'),
    (0x10, '<I', 'pad10'), (0x14, '<I', 'pad14'),
    (0x18, '<I', 'pad18'), (0x1C, '<I', 'pad1C'),
    (0x20, '<I', 'streams_ptr'), (0x24, '<I', 'streams_ptr_hi'),
    (0x28, '<H', 'streams_count'), (0x2A, '<H', 'streams_capacity'), (0x2C, '<I', 'pad2C'),
    (0x30, '<I', 'tracks_ptr'), (0x34, '<I', 'tracks_ptr_hi'),
    (0x38, '<H', 'tracks_count'), (0x3A, '<H', 'tracks_capacity'), (0x3C, '<I', 'pad3C'),
    (0x40, '<I', 'arr40_ptr'), (0x44, '<I', 'arr40_ptr_hi'),
    (0x48, '<H', 'arr40_count'), (0x4A, '<H', 'arr40_capacity'), (0x4C, '<I', 'pad4C'),
    (0x50, '<I', 'arr50_ptr'), (0x54, '<I', 'arr50_ptr_hi'),
    (0x58, '<H', 'arr50_count'), (0x5A, '<H', 'arr50_capacity'), (0x5C, '<I', 'pad5C'),
    (0x60, '<I', 'name_ptr'), (0x64, '<I', 'name_ptr_hi'),
    (0x68, '<I', 'unk68'), (0x6C, '<I', 'pad6C'),
    (0x70, '<I', 'unk70'), (0x74, '<I', 'signature'),
    (0x78, '<I', 'unk78'), (0x7C, '<I', 'unk7C'),
    (0x80, '<I', 'pad80'), (0x84, '<I', 'pad84'),
    (0x88, '<I', 'pad88'), (0x8C, '<I', 'pad8C'),
)

STREAM_FIELDS = (
    (0x00, '<I', 'name_hash'),
    (0x04, '<I', 'vec_pool_bytes'),
    (0x08, '<I', 'main_pool_bytes'),
    (0x0C, '<H', 'instruction_count'),
    (0x0E, '<H', 'depth'),
)

TRACK_FIELDS = (
    (0x00, '<H', 'bone_id'),
    (0x02, '<B', 'track'),
    (0x03, '<B', 'format_flags'),
)

# main-pool operand records, each TILED against the size `yed2xml.OPSIZE` declares
TRACK_OPERAND = (
    (0x00, '<H', 'track_index'), (0x02, '<H', 'op_bone_id'),
    (0x04, '<B', 'op_track'), (0x05, '<B', 'op_format'),
    (0x06, '<B', 'component_index'), (0x07, '<B', 'use_defaults'),
)
JUMP_OPERAND = ((0x00, '<I', 'jump0'), (0x04, '<I', 'jump1'), (0x08, '<I', 'instr_offset'))
VAR_OPERAND = ((0x00, '<I', 'var_hash'), (0x04, '<I', 'var_slot'))

# vector-pool operand records
SPRING_SLOT = ((0x00, '<f', 'sx'), (0x04, '<f', 'sy'), (0x08, '<f', 'sz'),
               (0x0C, '<H', 'sa'), (0x0E, '<H', 'sb'))
SPRING_TAIL = ((0x00, '<I', 'bone_track_rot'), (0x04, '<I', 'bone_track_pos'),
               (0x08, '<I', 'spring_tail2'), (0x0C, '<I', 'spring_tail3'))
LOOKAT_VEC = ((0x00, '<f', 'la_x'), (0x04, '<f', 'la_y'), (0x08, '<f', 'la_z'),
              (0x0C, '<f', 'la_w'))
LOOKAT_ENUM = ((0x00, '<I', 'lookat_axis'), (0x04, '<I', 'up_axis'),
               (0x08, '<I', 'origin'), (0x0C, '<I', 'lookat_pad'))
BLEND_HDR = ((0x00, '<I', 'blend_payload'), (0x04, '<I', 'blend_nsrc'),
             (0x08, '<I', 'blend_nsw'), (0x0C, '<I', 'blend_pad'))
BLEND_SRC = ((0x00, '<H', 'blend_track_index'), (0x02, '<H', 'blend_component_offset'))

SPRING_BYTES = 176
LOOKAT_BYTES = 32
SPRING_TABLE_STRIDE = 160        # the +0x40 array: DefineSpring's ten slots, without its 11th
# ⭐ NAMED SO THE CONTROL CAN PATCH THEM (`tools/pgdict_control.py`). A stride nothing can perturb
# is a stride nobody measured.
TRACK_STRIDE = 4
STREAM_PTR_STRIDE = 8
KEY50_STRIDE = 4


class Yed(Model):
    def __init__(self, res, flags=(0, 0)):
        Model.__init__(self, res, flags, version=25, what='yed')
        self.items = self.read_shell()
        self.nexpr = self.nstream = self.ninstr = self.ntrack = 0
        for off in self.items:
            self._expression(off)

    # ------------------------------------------------------------------ crExpression
    def _expression(self, off):
        if not self.once(off):
            raise ModelError('yed: two dictionary entries point at the same expression 0x%x' % off)
        self.nexpr += 1
        f = self.rd_fields(off, ITEM_FIELDS, ITEM, 'crExpression')
        # THE NAME. A cstr claim stops at its own NUL, so a wrong start yields a different string
        # and a different length - it cannot silently absorb a neighbour.
        nptr = self.deref(f['name_ptr'], 1)
        if nptr is None:
            raise ModelError('yed: expression name pointer does not resolve')
        self.cstr(nptr, tag='expr_name')

        self._array(f, 'tracks', TRACK_STRIDE, self._track)
        self._array(f, 'streams', STREAM_PTR_STRIDE, self._stream_ptr)
        # ⭐ THE TWO ARRAYS `yed2xml` NEVER READS - see SPRING_TABLE / the +0x50 note.
        self._array(f, 'arr40', SPRING_TABLE_STRIDE, self._spring_table)
        self._array(f, 'arr50', KEY50_STRIDE, self._key50)

    def _array(self, f, name, stride, fn):
        """Decode one atArray of the crExpression record and hand each element to `fn`.

        ⭐ THE COUNT DRIVES THE WALK - a wrong count writes the wrong number of records and the
        round-trip rejects it. CAPACITY is claimed as its own field and sizes nothing: it equals
        count on every live array in the lane (2,108 streams/tracks + 100 + 9), and sizing a read
        off a field under test is how a garbage count becomes garbage coverage."""
        cnt, cap, ptr = f[name + '_count'], f[name + '_capacity'], f[name + '_ptr']
        if not cnt:
            if ptr:
                raise ModelError('yed: %s array count 0 with a live pointer (unwitnessed)' % name)
            return
        if cap != cnt:
            raise ModelError('yed: %s capacity %d != count %d (unwitnessed)' % (name, cap, cnt))
        base = self.deref(ptr, cnt * stride)
        if base is None:
            raise ModelError('yed: %s array (%d x %d B) does not fit the segment'
                             % (name, cnt, stride))
        for i in range(cnt):
            fn(base + i * stride)

    def _track(self, off):
        self.rd_fields(off, TRACK_FIELDS, 4, 'crExpression track')
        self.ntrack += 1

    def _stream_ptr(self, off):
        p = self.rd1(off, '<Q', 'stream_ptr')
        o = self.deref(p & 0xFFFFFFFF, STREAM_HDR)
        if o is None:
            raise ModelError('yed: stream pointer 0x%x does not resolve' % p)
        self._stream(o)

    def _spring_table(self, off):
        """+0x40 - A SPRING DEFINITION TABLE, INLINE, STRIDE 160.

        ⛔⛔ THE FIRST VERSION OF THIS WRITER GUESSED "stride-8 tagged pointers", the shape every
        other array in this group uses, AND THE REFUSAL MESSAGE CARRIED ITS OWN REFUTATION: the
        "pointers" printed 0x42480000 / 0x43160000 / 0x42c80000, i.e. float32 50.0 / 150.0 /
        100.0. Inline records, not pointers - and the reason a wrong guess surfaced instead of
        scoring is that `deref` refuses a pointer that is not tag-5.
        ⭐ THE STRIDE IS PINNED BY THE ALLOCATION, over ALL 100 live arrays in the game
        (`scratchpad/probe_yed2.py`): room-to-next-allocation / count is EXACTLY 160 on every one
        - (320,2) x64, (160,1) x22, (640,4) x7, (1120,7) x4, (480,3) x2, (800,5) x1. No slack, so
        no other stride fits and a wrong one over-runs a neighbour on the first array it meets.
        ⭐ AND THE RECORD IS NOT A NEW STRUCTURE - it is `DefineSpring`'s operand minus its track
        slot. 160 = 10 slots of 16, laid out exactly like `yed2xml._spring_operand`'s first ten:
        nine {f32 x, f32 y, f32 z, u16, u16} vectors then a GRAVITY slot, and the gravity slot's
        z reads 9.8 in the worked example. `DefineSpring` is 176 = the same ten plus an eleventh
        {u32 BoneTrackRot, u32 BoneTrackPos} slot.
        ⚠ WHAT IS CLAIMED IS THE SPAN AND THE TILING, NOT THE SEMANTICS: the tail dword of a slot
        is int-shaped on 45 of 100 arrays and float-shaped on 10, so it is decoded as the same
        {u16, u16} pair `_spring_operand` uses and NOT named beyond that. Round-trip identity is
        unaffected by the label; over-labelling it would be a claim nothing here can refute."""
        for i in range(10):
            self.rd_fields(off + i * 16, SPRING_SLOT, 16, 'spring slot')

    def _key50(self, off):
        """+0x50 - a stride-4 u32 table, live on 9 of 2,330 items (counts 93 x8 and 3 x1).

        The values ASCEND STRICTLY within each array (0x01d5e3e3, 0x02af663e, 0x03e0c9ed, ...),
        which is the same shape as the dictionary's own Hashes array and is why they are read as
        u32 keys rather than as floats - as floats they would be a denormal staircase.
        ⚠ NOT NAMED FURTHER. What the keys index is not established by anything measured here,
        and the round-trip cannot settle it."""
        self.rd(off, '<I', 'key50')

    # ------------------------------------------------------------------ crExpressionStream
    def _stream(self, off):
        if not self.once(off):
            raise ModelError('yed: stream 0x%x reached twice' % off)
        self.nstream += 1
        h = self.rd_fields(off, STREAM_FIELDS, STREAM_HDR, 'crExpressionStream')
        vbytes, mbytes, cnt = h['vec_pool_bytes'], h['main_pool_bytes'], h['instruction_count']
        vec0 = off + STREAM_HDR
        main0 = vec0 + vbytes
        op0 = main0 + mbytes
        if op0 + cnt > self.size:
            raise ModelError('yed: stream pools run past the segment')
        vo, mo = vec0, main0
        for j in range(cnt):
            code = self.rd1(op0 + j, '<B', 'opcode')
            if code not in OPS:
                raise ModelError('yed: unknown expression opcode 0x%02x (instr %d)' % (code, j))
            kind = OPS[code][1]
            if kind is None:
                pass
            elif kind == 't':
                self.rd_fields(mo, TRACK_OPERAND, 8, 'track operand'); mo += 8
            elif kind == 'f':
                self.rd(mo, '<f', 'push_float'); mo += 4
            elif kind == 'j':
                self.rd_fields(mo, JUMP_OPERAND, 12, 'jump operand'); mo += 12
            elif kind == 'var':
                self.rd_fields(mo, VAR_OPERAND, 8, 'variable operand'); mo += 8
            elif kind == 'v':
                self.rd(vo, '<4f', 'push_vector'); vo += 16
            elif kind == 's':
                self._spring(vo); vo += SPRING_BYTES
            elif kind == 'la':
                self.rd_fields(vo, LOOKAT_VEC, 16, 'lookat offset')
                self.rd_fields(vo + 16, LOOKAT_ENUM, 16, 'lookat enums')
                vo += LOOKAT_BYTES
            elif kind == 'b':
                vo += self._blend(vo)
            else:
                raise ModelError('yed: operand kind %r has no writer' % kind)
            self.ninstr += 1
        # ⭐ THE SELF-CHECK THAT MAKES THE OPCODE TABLE FALSIFIABLE. Both cursors must land
        # EXACTLY on the declared pool ends. A wrong operand size for any opcode desynchronises
        # them, and the file REFUSES rather than reporting a plausible coverage number.
        if mo != main0 + mbytes:
            raise ModelError('yed: main pool consumed %d of %d bytes' % (mo - main0, mbytes))
        if vo != vec0 + vbytes:
            raise ModelError('yed: vector pool consumed %d of %d bytes' % (vo - vec0, vbytes))

    def _spring(self, vo):
        """DefineSpring: 176 vector-pool bytes = 11 slots of 16 (`yed2xml._spring_operand`,
        derived over 14 witnesses). Slots 0..9 are {f32 x,y,z, u16, u16}; slot 10 is four u32."""
        for i in range(10):
            self.rd_fields(vo + i * 16, SPRING_SLOT, 16, 'spring slot')
        self.rd_fields(vo + 160, SPRING_TAIL, 16, 'spring tail')

    def _blend(self, vo):
        """BlendVector / BlendQuaternion: a SELF-SIZED vector-pool payload.

        header 16 B {u32 payloadBytes (total, incl. header), u32 numSources, u32 numSourceWeights,
        u32 0}; then `numSources` x {u16 TrackIndex, u16 componentByteOffset} padded up to a
        16-byte boundary; then float planes filling the rest of the payload.
        ⭐ THE PAYLOAD FIELD IS WHAT THE MODEL USES FOR THE SPAN, and it is REFUTABLE: the pool
        cursor has to land exactly on `vecPoolBytes` at the end of the stream, so a payload read
        one byte wrong desynchronises the walk and the file refuses.
        ⭐ THE PADDING IS CLAIMED, NOT SKIPPED. `yed2xml` computes `src_area` and steps over the
        slack; a writer that did the same would leave those bytes at zero and they would show up
        as residual - which is exactly how this model is supposed to behave, so they are decoded
        as bytes and re-encoded."""
        h = self.rd_fields(vo, BLEND_HDR, 16, 'blend header')
        payload, nsrc = h['blend_payload'], h['blend_nsrc']
        if payload < 16 or payload % 4 or vo + payload > self.size:
            raise ModelError('yed: blend payload %d is not a usable span' % payload)
        src_area = ((nsrc * 4 + 15) // 16) * 16
        for i in range(nsrc):
            self.rd_fields(vo + 16 + i * 4, BLEND_SRC, 4, 'blend source')
        for k in range(nsrc * 4, src_area):
            self.rd(vo + 16 + k, '<B', 'blend_src_pad')
        rest = payload - 16 - src_area
        if rest < 0:
            raise ModelError('yed: blend source area %d overruns payload %d' % (src_area, payload))
        self.rd_array(vo + 16 + src_area, '<f', rest // 4, 'blend_plane')
        return payload

    # ------------------------------------------------------------------ the byte account
    def regions(self):
        """(value, derived, zero_fill, carried) byte split of the reproduced image.

        ⭐ DISCLOSURE, NOT DECORATION. Byte identity alone cannot tell a REBUILT region from a
        COPIED one: a writer that memcpy's a span it does not understand still scores 100%. This
        method is the lane saying which of its bytes it actually understood, and it is the number
        to quote NEXT TO the coverage figure - never instead of it.

            value      re-encoded from a decoded value (`Model.rd`, one struct claim per record)
            derived    COMPUTED from the model, not read from the bytes it overwrites - here that
                       is exactly the 4-byte page-count word `Model._stamp_pagecount` recomputes
                       from the RSC7 segment flags
            zero_fill  never claimed; the image leaves the byte at zero
            carried    VERBATIM copies out of the source buffer (`Model.carry`)

        ⭐ `carried` IS 0 BY CONSTRUCTION IN THIS LANE, and that is a structural fact rather than
        a claim. `pgdict_write.Model.carry` is the ONLY verbatim-copy path this model has, it is
        the only thing that files a CARRIED claim, and this writer never invokes it - the module
        header's "Model.carry() is called ZERO times" line is the same statement. There is no
        slice of the source buffer anywhere in this file either, so there is no region whose
        claim could be self-fulfilling, and `carried` cannot become non-zero without a new call
        site that the accounting would then count.

        ⚠ SCOPE, and it is the same scope the round-trip measures: the INFLATED SYSTEM SEGMENT
        that `Model.write()` produces, not the compressed RSC7 container. The identity checked
        below is therefore against `self.size` == `len(self.write())`.

        ⚠ ZERO_FILL IS NOT ALL PADDING. It is `zero_pad` (never claimed, and the ORIGINAL byte is
        zero - padding we did not have to understand) PLUS `zero_residual` (never claimed and
        NON-ZERO in the original - data we DROP, which is the finding this campaign exists to
        surface). They are folded here because both are zero in the produced image and the tuple
        has four slots; they stay separated in `accounting()`. Measured 2026-08-16 on two
        stratified boards: `zero_residual` 0 on 25/25 and on 75/75 - consistent with the module
        header's population figure of 0 residual bytes over 242/242 exact. Read them apart with:
            a = m.accounting(); a['zero_pad'], a['zero_residual'], a['value_named']
        `accounting()` also splits VALUE into NAMED fields vs untyped tiling words - on both
        boards every VALUE byte was NAMED (14,653,927 named / 0 untyped on the 75) - which
        `regions()` cannot express and which is the stronger statement of the two.

        ⛔ AND ZERO-FILL IS NOT UNDERSTANDING EITHER. `carried` being 0 does NOT mean the lane
        understood 100% of the image. Measured 2026-08-16, 75-file stratified board, 16,007,168
        image bytes: VALUE 91.5460% / DERIVED 0.0019% (the 4-byte page-count word, 75 x 4 B) /
        ZERO-FILL 8.4521% / CARRIED 0.0000%. Those 8.45% pass because the ORIGINAL byte is zero,
        not because anything modelled them - a wrong claim over them could not have been
        rejected, which is the same objection `carried` exists to raise. Quote both or neither.
        ⚠ A BOARD IS NOT THE POPULATION, and the VALUE/ZERO ratio moves with the draw: the
        25-file board reads VALUE 86.9641% / ZERO-FILL 13.0309%, the 75-file board 91.5460% /
        8.4521%, the header's population account 92.8014% / 7.1962%. CARRIED is 0 in all three,
        and it is the only column of the four that does not move with the sample.
        ⚠ AND THE RSC7 CONTAINER IS OUTSIDE THIS ACCOUNT ENTIRELY, exactly as it is outside the
        round-trip: those 75 files are 2,864,551 bytes on disk and 16,007,168 bytes inflated.
        The container is not counted as carried because it is not reproduced here at all.
        """
        a = self.accounting()
        value = a['value_named'] + a['value_words']
        derived = a['derived']
        zero_fill = a['zero_pad'] + a['zero_residual']
        carried = a['carried']
        # ⛔ THE ACCOUNTING IDENTITY IS THE CHECK, AND IT REFUSES RATHER THAN FUDGES A BUCKET.
        # `accounting()` already refuses on an overlapping claim; this re-states the sum against
        # the image length so a future edit that adds a bucket cannot quietly lose bytes.
        if value + derived + zero_fill + carried != self.size:
            raise ModelError('yed: byte account %d + %d + %d + %d != image %d'
                             % (value, derived, zero_fill, carried, self.size))
        return (value, derived, zero_fill, carried)


def read_yed(src):
    return pgdict_write.read(src, Yed)


if __name__ == '__main__':
    import glob
    root = _sys.argv[1] if len(_sys.argv) > 1 else '.'
    fs = sorted(glob.glob(os.path.join(root, '*.yed')))
    print('SAMPLE SIZE %d' % len(fs))
    if not fs:
        raise SystemExit('REFUSING: empty sample')
    ok = 0
    for p in fs:
        try:
            m = read_yed(p)
            ok += (m.unreached()[0] == 0)
        except Exception as ex:
            print('%-44s %s: %s' % (os.path.basename(p), type(ex).__name__, str(ex)[:60]))
    print('byte-exact %d / %d' % (ok, len(fs)))
