"""`.mrf` (RAGE MoVE network / motion-graph definition) -> reference-identical XML.

DERIVED 2026-08-06 by value-intersecting the ONE oracle
(`_Oracles/mrf/00_base/minigame_blowtorch.mrf.xml`, 42,149 B / 1,490 lines) against the
binary `x64c.rpf\\anim\\networkdefs.rpf\\minigame_blowtorch.mrf` (4,060 B). Every offset
below is pinned by a value that appears verbatim in the oracle text - nothing is guessed.
Where the oracle shows only ONE value for a field (so the encoding cannot be separated
from a constant), the bits are recorded as a WITNESS and any other bit pattern is refused
loudly (`UNPINNED_0x…` text, or `MrfUnpinned` when strict=True) instead of being spelled
with a value that was never measured.

FILE LAYOUT (all little-endian; "rel" = a signed 32-bit offset relative to the address of
the field that holds it - the classic RAGE self-relative pointer)

  0x00  4s   magic 'MoVE'
  0x04  u32  version (2 in every one of the 97 base-game .mrf)
  0x08  u32  0   \
  0x0C  u32  0    |  UNPINNED: two of these five drive <Unk1> and <UnkBytes>. All five are
  0x10  u32  0    |  zero in all 97 base-game files, so both elements are always empty and
  0x18  u32  0    |  which dword means what cannot be separated.
  0x1C  u32  0   /
  0x14  u32  payload size == filesize - 32   (measured on all 97)
  0x20       payload begins

  payload:
    u32                 trigger slot count N
    N * (u32 hash, u32 bitPosition)      <- OPEN-ADDRESSED table; empty slot hash 0xFFFFFFFF
    u32                 flag slot count M
    M * (u32 hash, u32 bitPosition)      <- same shape (M==0 in the oracle: shape UNPINNED)
    <root node>                          <- type 1 StateMachine, or type 27 State

NODE HEADER (every node type)
  +0x00 u16 type   +0x02 u16 nodeIndex   +0x04 u32 nameHash   +0x08 u32 flags

  StateMachine (type 1) - 0x20 + 8*numStates
    +0x08 rel  -> initial state          <InitialState ref="…">
    +0x0C u32  StateUnk3
    +0x10 u32  flags: bits16-23 = numStates, bits24-31 = numTransitions
    +0x14 u32  EntryParameterName hash (0 = empty)
    +0x18 u32  ExitParameterName  hash (0 = empty)
    +0x1C rel  -> transitions array
    +0x20      numStates * (u32 stateNameHash, rel -> State node)

  State (type 27) - 0x40 bytes
    +0x08 rel  -> InitialNode
    +0x0C u32  StateUnk3
    +0x10 u32  flags: bit0 = entry name present, bit8 = exit name present,
                      bits16-23 = node count in this state's own index space,
                      bits24-31 = numTransitions
    +0x14 u32  EntryParameterName hash
    +0x18 u32  ExitParameterName  hash
    +0x1C rel  -> transitions
    +0x20 rel / +0x24 u32 count  InputParameters   (12 B each)
    +0x28 rel / +0x2C u32 count  Events            ( 8 B each)
    +0x30 rel / +0x34 u32 count  OutputParameters  (12 B each)
    +0x38 rel / +0x3C u32 count  Operations        (variable)

  Transition - 0x18 bytes + conditions
    +0x00 u32  flags: bit2 = UnkFlag2_DetachUpdateObservers, bit18 = UnkFlag18,
                      bit19 = UnkFlag19, bits20-22 = condition count
               (the oracle only ever shows ONE condition, so bits20-22 vs bit20-alone is not
                separable from it. It was separated against the GAME BINARY instead:
                helicopterrappel.mrf @0x0D8 and @0x108 carry flags 0x20240300 and are each
                followed by exactly TWO 12-byte condition records, with the second transition
                starting exactly where the first ends - which bits29-31 would get wrong.)
    +0x04 u32  FrameFilter hash (0xFFFFFFFF = none)
    +0x08 f32  Duration
    +0x0C u32  DurationParameterName hash
    +0x10 u32  ProgressParameterName hash
    +0x14 rel  -> target State node
    +0x18      conditions: (u32 type, u32 a, u32 b) each
                 type 2 = MoveNetworkTrigger (a = BitPosition, b = Invert)
                 type 4 = EventOccurred      (a = ParameterName hash, b = Value)

  Clip (type 15) - 0x28 bytes as witnessed
    flags carry a 2-bit "source kind" per field, LSB first:
      bits0-1 Clip, bits2-3 Phase, bits4-5 Rate, bits6-7 Delta, bits8-9 tail
      kind 1 = inline value, kind 2 = parameter (the dword is a name hash)
    bit10 = UnkFlag10
    inline Clip occupies 3 dwords: containerType (1 = ClipSet), containerName hash, clip hash
    tail dword: bit24 = Looped

  BlendN (type 13) - 0x0C + 4*(numChildren+1) [+ pad]
    +0x08 flags: bits26-31 = numChildren; child pointers follow, then a 0 terminator
  AddSubtract (type 6) - 0x18 bytes
    +0x08 flags: bits0-1 = Weight source kind; bit6 UnkFlag6, bit7 UnkFlag7,
                 bit21 UnkFlag21, bit23 UnkFlag23, bit25 UnkFlag25
    +0x0C rel -> Child0   +0x10 rel -> Child1   +0x14 f32 Weight

  Operation item - 8 B header + an operator stream terminated by Finish
    +0x00 u16 NodeIndex  +0x02 u16 NodeParameterId
    +0x04 u16 0x18 (constant in all 25 witnessed items)  +0x06 u16 NodeParameterExtraArg
    operators: u32 type, then
      0 Finish          - no payload
      2 PushParameter   - u32 parameter name hash
      5 Remap           - u32 4, f32 Min, f32 Max, u32 nRanges, u32 4, u32 0,
                          nRanges * (f32 Percent, f32 Length, f32 Min, f32 0)

NAMES. A .mrf holds NO strings - every name is a lowercase joaat. `names` is the same
{hash:int -> str} table the rest of QUARRY passes around; anything it cannot resolve is
spelled `hash_XXXXXXXX`, exactly as the reference exporter does. Byte-parity with the oracle therefore
requires the 11 strings it resolved to be present in that table (see mrf2xml_names.json
beside this module for the witnessed set and its provenance).
"""

import json
import os
import struct

import meta2xml

_SIDECAR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'oracle_mrf_names.json')
_FALLBACK_NAMES = None


def fallback_names():
    """{joaat -> str} for the names a .mrf cannot supply itself. Read the sidecar's own
    _comment for provenance: the clipset entries are real asset filenames (so the normal
    QUARRY names table already covers them), the parameter entries were read off the oracle
    export and are the one non-independently-derived part of this converter."""
    global _FALLBACK_NAMES
    if _FALLBACK_NAMES is None:
        out = {}
        try:
            with open(_SIDECAR, 'r', encoding='utf-8') as f:
                doc = json.load(f)
            for key in ('clipsets', 'parameters'):
                for s in doc.get(key) or ():
                    out[meta2xml.joaat(s)] = s
        except Exception:
            out = {}
        _FALLBACK_NAMES = out
    return _FALLBACK_NAMES

MAGIC = b'MoVE'
EMPTY_SLOT = 0xFFFFFFFF

# Node type enum - PINNED from the `type="…"` attributes the oracle writes. Only these five
# appear in the one oracle; every other type id is UNPINNED by construction.
NODE_TYPES = {
    1: 'StateMachine',
    6: 'AddSubtract',
    13: 'BlendN',
    15: 'Clip',
    27: 'State',
}

# Clip <ContainerType>. Only value 1 is witnessed.
CONTAINER_TYPES = {1: 'ClipSet'}

# Transition <Conditions> item types, pinned from the oracle's `type="…"`.
CONDITION_TYPES = {2: 'MoveNetworkTrigger', 4: 'EventOccurred'}

# <Operators> item types, pinned from the oracle's `type="…"`.
OPERATOR_TYPES = {0: 'Finish', 2: 'PushParameter', 5: 'Remap'}

# Field-source kinds (2 bits per field in a node's flags word).
KIND_VALUE = 1
KIND_PARAMETER = 2

# --- WITNESSES ------------------------------------------------------------------------
# Residual flag bits whose meaning could not be separated because the oracle shows exactly
# one value for the fields they drive. The key is the residual; the value is the text the
# oracle spells. A residual that is not a key is refused, never guessed.
#
# transition: flags minus bit2/bit18/bit19 (named) and bits20-22 (condition count)
TRANSITION_RESIDUAL = {
    0x20000240: {'BlendModifier': 'SlowInSlowOut', 'SynchronizerType': 'None'},
}
TRANSITION_KNOWN_BITS = 0x00700004 | 0x000C0000        # cond count | UnkFlag2/18/19
# add/subtract: flags minus bits0-1 (weight kind) and bits 6,7,21,23,25 (named Unk flags)
ADDSUB_RESIDUAL = {
    0x00100000: {'Child0InfluenceOverride': 'None', 'Child1InfluenceOverride': 'None',
                 'FrameFilter': None, 'SynchronizerType': 'None', 'MergeBlend': False},
}
# blendN: flags minus bits26-31 (child count)
BLENDN_RESIDUAL = {
    0x00100000: {'FrameFilter': None, 'SynchronizerType': 'None', 'ZeroDestination': False,
                 'child_weight': None, 'child_framefilter': None},
}


class MrfError(Exception):
    """The blob is not a MoVE network this reader understands."""


class MrfUnpinned(MrfError):
    """A value exists in the file that the single oracle never showed - refused, not guessed."""


def _f(v):
    return meta2xml.fmt_num(struct.unpack('<f', struct.pack('<I', v))[0])


def _b(v):
    """the reference exporter spells .NET booleans - capitalised, not lowercase."""
    return 'True' if v else 'False'


class _Mrf(object):
    def __init__(self, blob, names=None, strict=False):
        self.d = blob
        self.names = names or {}
        self.strict = strict
        self.unpinned = []

    # -- primitives --------------------------------------------------------------------
    def u16(self, o):
        return struct.unpack_from('<H', self.d, o)[0]

    def u32(self, o):
        return struct.unpack_from('<I', self.d, o)[0]

    def i32(self, o):
        return struct.unpack_from('<i', self.d, o)[0]

    def ptr(self, o):
        """Self-relative pointer: the stored delta is measured FROM the field itself."""
        return o + self.i32(o)

    def nm(self, h):
        """joaat -> name, or the reference exporter's hash_XXXXXXXX spelling when unresolved.
        The caller's table WINS; the sidecar only fills what it does not carry."""
        if h == 0:
            return ''
        s = self.names.get(h) or fallback_names().get(h)
        return s if s else 'hash_%08X' % h

    # -- refusal -----------------------------------------------------------------------
    def pin(self, what, residual, table):
        got = table.get(residual)
        if got is None:
            msg = '%s: flag residual 0x%08X was never witnessed by the oracle' % (what, residual)
            self.unpinned.append(msg)
            if self.strict:
                raise MrfUnpinned(msg)
            return None
        return got

    def unpin_text(self, what, value):
        msg = '%s: value 0x%X was never witnessed by the oracle' % (what, value)
        self.unpinned.append(msg)
        if self.strict:
            raise MrfUnpinned(msg)
        return 'UNPINNED_0x%X' % value

    # -- elements ----------------------------------------------------------------------
    def txt(self, ind, tag, s):
        return ['%s<%s />' % (ind, tag)] if not s else \
               ['%s<%s>%s</%s>' % (ind, tag, meta2xml.esc(s), tag)]

    # -- hash tables (triggers / flags) ------------------------------------------------
    def slot_table(self, off):
        """(count, [(hash, bitPosition)]) for the open-addressed table at `off`."""
        n = self.u32(off)
        out = []
        for i in range(n):
            h, v = struct.unpack_from('<II', self.d, off + 4 + 8 * i)
            out.append((h, v))
        return off + 4 + 8 * n, out

    def table_lines(self, tag, rows, ind):
        live = [(h, v) for h, v in rows if h != EMPTY_SLOT]
        if not live:
            return ['%s<%s />' % (ind, tag)]
        out = ['%s<%s>' % (ind, tag)]
        for h, v in live:
            out.append('%s <Item>' % ind)
            out.extend(self.txt(ind + '  ', 'Name', self.nm(h)))
            out.append('%s  <BitPosition value="%d" />' % (ind, v))
            out.append('%s </Item>' % ind)
        out.append('%s</%s>' % (ind, tag))
        return out

    # -- nodes -------------------------------------------------------------------------
    def node(self, off, tag, ind):
        t = self.u16(off)
        kind = NODE_TYPES.get(t)
        if kind is None:
            raise MrfUnpinned('node type %d at 0x%X is not in the oracle-pinned enum '
                              '(%s)' % (t, off, ', '.join(sorted(NODE_TYPES.values()))))
        body = getattr(self, '_n_' + kind.lower())(off, ind + ' ')
        return (['%s<%s type="%s">' % (ind, tag, kind)] + body + ['%s</%s>' % (ind, tag)])

    def head(self, off, ind):
        return self.txt(ind, 'Name', self.nm(self.u32(off + 4))) + \
            ['%s<NodeIndex value="%d" />' % (ind, self.u16(off + 2))]

    # StateMachine and State share their first five emitted fields.
    def _container_head(self, off, ind):
        flags = self.u32(off + 0x10)
        if flags & 0x0000FEFE:
            self.unpin_text('state flags low half', flags & 0xFFFF)
        entry, exit_ = self.u32(off + 0x14), self.u32(off + 0x18)
        return (self.head(off, ind)
                + ['%s<StateUnk3 value="%d" />' % (ind, self.u32(off + 0x0C))]
                + self.txt(ind, 'EntryParameterName', self.nm(entry))
                + self.txt(ind, 'ExitParameterName', self.nm(exit_)))

    def _n_statemachine(self, off, ind):
        flags = self.u32(off + 0x10)
        n_states = (flags >> 16) & 0xFF
        n_trans = (flags >> 24) & 0xFF
        out = self._container_head(off, ind)
        out.append('%s<InitialState ref="%s" />'
                   % (ind, meta2xml.esc(self.nm(self.u32(self.ptr(off + 0x08) + 4)))))
        if not n_states:
            out.append('%s<States />' % ind)
        else:
            out.append('%s<States>' % ind)
            for i in range(n_states):
                out.extend(self.node(self.ptr(off + 0x24 + 8 * i), 'Item', ind + ' '))
            out.append('%s</States>' % ind)
        out.extend(self.transitions(self.ptr(off + 0x1C), n_trans, ind))
        return out

    def _n_state(self, off, ind):
        flags = self.u32(off + 0x10)
        n_trans = (flags >> 24) & 0xFF
        out = self._container_head(off, ind)
        out.extend(self.node(self.ptr(off + 0x08), 'InitialNode', ind))
        out.extend(self.transitions(self.ptr(off + 0x1C), n_trans, ind))
        out.extend(self.params(self.ptr(off + 0x20), self.u32(off + 0x24), ind,
                               'InputParameters', 'SourceParameterName', 'Target'))
        out.extend(self.params(self.ptr(off + 0x30), self.u32(off + 0x34), ind,
                               'OutputParameters', 'TargetParameterName', 'Source'))
        out.extend(self.events(self.ptr(off + 0x28), self.u32(off + 0x2C), ind))
        out.extend(self.operations(self.ptr(off + 0x38), self.u32(off + 0x3C), ind))
        return out

    def _n_clip(self, off, ind):
        flags = self.u32(off + 0x08)
        if flags & ~0x7FF:
            self.unpin_text('clip flags', flags & ~0x7FF)
        p = off + 0x0C
        out = self.head(off, ind)

        k = flags & 3
        if k == KIND_VALUE:
            ct = self.u32(p)
            cname, clip = self.u32(p + 4), self.u32(p + 8)
            p += 12
            ctxt = CONTAINER_TYPES.get(ct) or self.unpin_text('Clip ContainerType', ct)
            out.append('%s<Clip>' % ind)
            out.extend(self.txt(ind + ' ', 'ContainerType', ctxt))
            out.extend(self.txt(ind + ' ', 'ContainerName', self.nm(cname)))
            out.extend(self.txt(ind + ' ', 'Name', self.nm(clip)))
            out.append('%s</Clip>' % ind)
        else:
            raise MrfUnpinned('Clip node at 0x%X sources its clip by kind %d - the oracle only '
                              'witnessed the inline (kind 1) form' % (off, k))

        for i, tag in ((1, 'Phase'), (2, 'Rate'), (3, 'Delta')):
            k = (flags >> (2 * i)) & 3
            v = self.u32(p)
            p += 4
            if k == KIND_VALUE:
                out.append('%s<%s value="%s" />' % (ind, tag, _f(v)))
            elif k == KIND_PARAMETER:
                out.append('%s<%s parameter="%s" />'
                           % (ind, tag, meta2xml.esc(self.nm(v))))
            else:
                out.append('%s<%s value="%s" />'
                           % (ind, tag, self.unpin_text('%s source kind' % tag, k)))

        tail = self.u32(p)
        if tail & ~0x01000000:
            self.unpin_text('clip tail dword', tail)
        out.append('%s<Looped value="%s" />' % (ind, _b(tail & 0x01000000)))
        out.append('%s<UnkFlag10 value="%d" />' % (ind, (flags >> 10) & 1))
        return out

    def _n_blendn(self, off, ind):
        flags = self.u32(off + 0x08)
        n = flags >> 26
        w = self.pin('BlendN', flags & 0x03FFFFFF, BLENDN_RESIDUAL) or {}
        out = self.head(off, ind)
        out.extend(self.txt(ind, 'FrameFilter', w.get('FrameFilter')))
        out.extend(self.txt(ind, 'SynchronizerType', w.get('SynchronizerType')))
        out.append('%s<ZeroDestination value="%s" />' % (ind, _b(w.get('ZeroDestination'))))
        if not n:
            out.append('%s<Children />' % ind)
            return out
        out.append('%s<Children>' % ind)
        for i in range(n):
            out.append('%s <Item>' % ind)
            out.extend(self.txt(ind + '  ', 'Weight', w.get('child_weight')))
            out.extend(self.txt(ind + '  ', 'FrameFilter', w.get('child_framefilter')))
            out.extend(self.node(self.ptr(off + 0x0C + 4 * i), 'Node', ind + '  '))
            out.append('%s </Item>' % ind)
        out.append('%s</Children>' % ind)
        return out

    def _n_addsubtract(self, off, ind):
        flags = self.u32(off + 0x08)
        w = self.pin('AddSubtract', flags & ~0x00A000C3, ADDSUB_RESIDUAL) or {}
        out = self.head(off, ind)
        out.extend(self.node(self.ptr(off + 0x0C), 'Child0', ind))
        out.extend(self.node(self.ptr(off + 0x10), 'Child1', ind))
        out.extend(self.txt(ind, 'Child0InfluenceOverride', w.get('Child0InfluenceOverride')))
        out.extend(self.txt(ind, 'Child1InfluenceOverride', w.get('Child1InfluenceOverride')))
        k = flags & 3
        if k == KIND_VALUE:
            out.append('%s<Weight value="%s" />' % (ind, _f(self.u32(off + 0x14))))
        elif k == KIND_PARAMETER:
            out.append('%s<Weight parameter="%s" />'
                       % (ind, meta2xml.esc(self.nm(self.u32(off + 0x14)))))
        else:
            out.append('%s<Weight value="%s" />'
                       % (ind, self.unpin_text('AddSubtract Weight source kind', k)))
        out.extend(self.txt(ind, 'FrameFilter', w.get('FrameFilter')))
        out.extend(self.txt(ind, 'SynchronizerType', w.get('SynchronizerType')))
        out.append('%s<MergeBlend value="%s" />' % (ind, _b(w.get('MergeBlend'))))
        out.append('%s<UnkFlag6 value="%s" />' % (ind, _b((flags >> 6) & 1)))
        out.append('%s<UnkFlag7 value="%d" />' % (ind, (flags >> 7) & 1))
        out.append('%s<UnkFlag21 value="%d" />' % (ind, (flags >> 21) & 1))
        out.append('%s<UnkFlag23 value="%d" />' % (ind, (flags >> 23) & 1))
        out.append('%s<UnkFlag25 value="%s" />' % (ind, _b((flags >> 25) & 1)))
        return out

    # -- state sub-arrays --------------------------------------------------------------
    def transitions(self, off, n, ind):
        if not n:
            return ['%s<Transitions />' % ind]
        out = ['%s<Transitions>' % ind]
        for _ in range(n):
            out.extend(self.transition(off, ind + ' '))
            off += 0x18 + 12 * ((self.u32(off) >> 20) & 7)
        out.append('%s</Transitions>' % ind)
        return out

    def transition(self, off, ind):
        flags = self.u32(off)
        n_cond = (flags >> 20) & 7
        w = self.pin('Transition', flags & ~TRANSITION_KNOWN_BITS, TRANSITION_RESIDUAL) or {}
        ff = self.u32(off + 0x04)
        i2 = ind + ' '
        out = ['%s<Item>' % ind,
               '%s<TargetState ref="%s" />'
               % (i2, meta2xml.esc(self.nm(self.u32(self.ptr(off + 0x14) + 4)))),
               '%s<Duration value="%s" />' % (i2, _f(self.u32(off + 0x08)))]
        out.extend(self.txt(i2, 'DurationParameterName', self.nm(self.u32(off + 0x0C))))
        out.extend(self.txt(i2, 'ProgressParameterName', self.nm(self.u32(off + 0x10))))
        out.extend(self.txt(i2, 'BlendModifier', w.get('BlendModifier')))
        out.extend(self.txt(i2, 'SynchronizerType', w.get('SynchronizerType')))
        out.extend(self.txt(i2, 'FrameFilter', '' if ff == EMPTY_SLOT else self.nm(ff)))
        out.append('%s<UnkFlag2_DetachUpdateObservers value="%s" />' % (i2, _b((flags >> 2) & 1)))
        out.append('%s<UnkFlag18 value="%s" />' % (i2, _b((flags >> 18) & 1)))
        out.append('%s<UnkFlag19 value="%s" />' % (i2, _b((flags >> 19) & 1)))
        if not n_cond:
            out.append('%s<Conditions />' % i2)
        else:
            out.append('%s<Conditions>' % i2)
            for i in range(n_cond):
                out.extend(self.condition(off + 0x18 + 12 * i, i2 + ' '))
            out.append('%s</Conditions>' % i2)
        out.append('%s</Item>' % ind)
        return out

    def condition(self, off, ind):
        t, a, b = struct.unpack_from('<III', self.d, off)
        kind = CONDITION_TYPES.get(t)
        if kind is None:
            raise MrfUnpinned('transition condition type %d at 0x%X is not in the oracle-pinned '
                              'enum (%s)' % (t, off, ', '.join(sorted(CONDITION_TYPES.values()))))
        out = ['%s<Item type="%s">' % (ind, kind)]
        if kind == 'MoveNetworkTrigger':
            out.append('%s <BitPosition value="%d" />' % (ind, a))
            out.append('%s <Invert value="%s" />' % (ind, _b(b)))
        else:                                            # EventOccurred
            out.extend(self.txt(ind + ' ', 'ParameterName', self.nm(a)))
            out.append('%s <Value value="%s" />' % (ind, _b(b)))
        out.append('%s</Item>' % ind)
        return out

    def params(self, off, n, ind, tag, name_tag, side):
        """InputParameters / OutputParameters - same 12-byte record, mirrored element names."""
        if not n:
            return ['%s<%s />' % (ind, tag)]
        out = ['%s<%s>' % (ind, tag)]
        for i in range(n):
            h, idx, pid, extra = struct.unpack_from('<IHHI', self.d, off + 12 * i)
            out.append('%s <Item>' % ind)
            out.extend(self.txt(ind + '  ', name_tag, self.nm(h)))
            out.append('%s  <%sNodeIndex value="%d" />' % (ind, side, idx))
            out.append('%s  <%sNodeParameterId value="%d" />' % (ind, side, pid))
            out.append('%s  <%sNodeParameterExtraArg value="%d" />' % (ind, side, extra))
            out.append('%s </Item>' % ind)
        out.append('%s</%s>' % (ind, tag))
        return out

    def events(self, off, n, ind):
        if not n:
            return ['%s<Events />' % ind]
        out = ['%s<Events>' % ind]
        for i in range(n):
            idx, eid, h = struct.unpack_from('<HHI', self.d, off + 8 * i)
            out.append('%s <Item>' % ind)
            out.append('%s  <NodeIndex value="%d" />' % (ind, idx))
            out.append('%s  <NodeEventId value="%d" />' % (ind, eid))
            out.extend(self.txt(ind + '  ', 'ParameterName', self.nm(h)))
            out.append('%s </Item>' % ind)
        out.append('%s</Events>' % ind)
        return out

    def operations(self, off, n, ind):
        if not n:
            return ['%s<Operations />' % ind]
        out = ['%s<Operations>' % ind]
        for _ in range(n):
            idx, pid, mark, extra = struct.unpack_from('<HHHH', self.d, off)
            if mark != 0x18:
                self.unpin_text('operation header word at +4', mark)
            out.append('%s <Item>' % ind)
            out.append('%s  <NodeIndex value="%d" />' % (ind, idx))
            out.append('%s  <NodeParameterId value="%d" />' % (ind, pid))
            out.append('%s  <NodeParameterExtraArg value="%d" />' % (ind, extra))
            out.append('%s  <Operators>' % ind)
            p = off + 8
            while True:
                lines, p, done = self.operator(p, ind + '   ')
                out.extend(lines)
                if done:
                    break
            out.append('%s  </Operators>' % ind)
            out.append('%s </Item>' % ind)
            off = p
        out.append('%s</Operations>' % ind)
        return out

    def operator(self, off, ind):
        t = self.u32(off)
        kind = OPERATOR_TYPES.get(t)
        if kind is None:
            raise MrfUnpinned('operator type %d at 0x%X is not in the oracle-pinned enum '
                              '(%s)' % (t, off, ', '.join(sorted(OPERATOR_TYPES.values()))))
        if kind == 'Finish':
            # MEASURED: the reference exporter writes the open and close tags on their OWN lines for an
            # operator with no fields - it is NOT collapsed to a self-closing element.
            return (['%s<Item type="Finish">' % ind, '%s</Item>' % ind], off + 4, True)
        if kind == 'PushParameter':
            out = ['%s<Item type="PushParameter">' % ind]
            out.extend(self.txt(ind + ' ', 'ParameterName', self.nm(self.u32(off + 4))))
            out.append('%s</Item>' % ind)
            return out, off + 8, False
        # Remap
        a, mn, mx, cnt, b, c = struct.unpack_from('<IIIIII', self.d, off + 4)
        if (a, b, c) != (4, 4, 0):
            self.unpin_text('Remap constants', (a << 40) | (b << 8) | c)
        out = ['%s<Item type="Remap">' % ind,
               '%s <Min value="%s" />' % (ind, _f(mn)),
               '%s <Max value="%s" />' % (ind, _f(mx))]
        p = off + 28
        if not cnt:
            out.append('%s <Ranges />' % ind)
        else:
            out.append('%s <Ranges>' % ind)
            for i in range(cnt):
                pc, ln, rmn, pad = struct.unpack_from('<IIII', self.d, p + 16 * i)
                if pad:
                    self.unpin_text('Remap range trailing dword', pad)
                out.append('%s  <Item>' % ind)
                out.append('%s   <Percent value="%s" />' % (ind, _f(pc)))
                out.append('%s   <Min value="%s" />' % (ind, _f(rmn)))
                out.append('%s   <Length value="%s" />' % (ind, _f(ln)))
                out.append('%s  </Item>' % ind)
            out.append('%s </Ranges>' % ind)
        out.append('%s</Item>' % ind)
        return out, p + 16 * cnt, False

    # -- top level ---------------------------------------------------------------------
    def lines(self):
        if self.d[:4] != MAGIC:
            raise MrfError('not a MoVE network: magic %r' % (self.d[:4],))
        ver = self.u32(0x04)
        if ver != 2:
            raise MrfUnpinned('MoVE version %d - only version 2 is witnessed' % ver)
        size = self.u32(0x14)
        if size != len(self.d) - 32:
            raise MrfError('payload size %d does not match blob %d' % (size, len(self.d)))
        for o in (0x08, 0x0C, 0x10, 0x18, 0x1C):
            if self.u32(o):
                # Two of these five drive <Unk1>/<UnkBytes>; all are zero in every witnessed
                # file, so a non-zero one means the tail elements are NOT empty and this
                # emitter would silently drop their content.
                self.unpin_text('MoVE header dword at +0x%02X' % o, self.u32(o))
        p, trig = self.slot_table(0x20)
        p, flags = self.slot_table(p)
        out = ['<?xml version="1.0" encoding="UTF-8"?>', '<MoveNetwork>']
        out.extend(self.table_lines('MoveNetworkTriggers', trig, ' '))
        out.extend(self.table_lines('MoveNetworkFlags', flags, ' '))
        out.extend(self.node(p, 'RootState', ' '))
        out.append(' <Unk1 />')
        out.append(' <UnkBytes />')
        out.append('</MoveNetwork>')
        return out


def convert(name, blob, names=None, strict=False):
    """`.mrf` blob -> reference-identical XML text (CRLF, trailing newline).

    names  : {joaat:int -> str} - the same table the rest of QUARRY passes around.
    strict : refuse (raise MrfUnpinned) instead of writing an `UNPINNED_0x…` marker when a
             value appears that the single oracle never showed.
    """
    m = _Mrf(blob, names, strict)
    return '\r\n'.join(m.lines()) + '\r\n'


def convert_with_report(name, blob, names=None, strict=False):
    """convert(), plus the list of values that were refused rather than guessed."""
    m = _Mrf(blob, names, strict)
    return '\r\n'.join(m.lines()) + '\r\n', list(m.unpinned)
