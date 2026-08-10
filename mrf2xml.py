"""mrf2xml - GTA V .mrf (rage MoVE network) -> RAGE .mrf.xml.

CLEAN-ROOM: derived from oracle XML + game binary + our own quarry code only.

STATUS (2026-08-10): 37/37 oracles byte-identical, 0 refusals. `was:` 1 PASS / 32 refused on a
ONE-oracle base, whose single named refusal ("Clip node sources its clip by kind 2") turned out
to be 1 of 8 real gaps a node-type census over the 162-file population exposed - the recurring
lesson that a refusal message names ONE cause and you must size the work from oracle coverage
instead.

Everything here is pinned by a value that appears verbatim in an oracle. Nothing is guessed;
anything still unseparated raises MrfUnpinned and is counted, never invented.
"""
import json
import os
import struct

import meta2xml

_SIDECAR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'oracle_mrf_names.json')
_FALLBACK_NAMES = None
FALLBACK_SIDECAR_ERROR = None


def fallback_names():
    global _FALLBACK_NAMES
    if _FALLBACK_NAMES is None:
        out = {}
        try:
            with open(_SIDECAR, 'r', encoding='utf-8') as f:
                doc = json.load(f)
            for key in ('clipsets', 'parameters'):
                for s in doc.get(key) or ():
                    out[meta2xml.joaat(s)] = s
        except Exception as ex:
            global FALLBACK_SIDECAR_ERROR
            FALLBACK_SIDECAR_ERROR = '%s: %s' % (type(ex).__name__, ex)
            out = {}
        _FALLBACK_NAMES = out
    return _FALLBACK_NAMES


MAGIC = b'MoVE'
EMPTY_SLOT = 0xFFFFFFFF

NODE_TYPES = {
    1: 'StateMachine', 2: 'Tail', 3: 'InlinedStateMachine', 5: 'Blend', 6: 'AddSubtract',
    7: 'Filter', 13: 'BlendN', 15: 'Clip', 19: 'Expression', 24: 'Merge', 27: 'State',
    28: 'Invalid', 30: 'SubNetwork',
}

CONTAINER_TYPES = {0: 'VariableClipSet', 1: 'ClipSet', 2: 'ClipDictionary', 3: 'Unk3'}

CONDITION_TYPES = {
    0: 'ParameterInsideRange', 1: 'ParameterOutsideRange',
    2: 'MoveNetworkTrigger', 3: 'MoveNetworkFlag', 4: 'EventOccurred',
    5: 'ParameterGreaterThan', 6: 'ParameterGreaterOrEqual',
    8: 'ParameterLessOrEqual', 9: 'TimeGreaterThan', 12: 'BoolParameterEquals',
}

OPERATOR_TYPES = {0: 'Finish', 2: 'PushParameter', 5: 'Remap'}

KIND_NONE, KIND_VALUE, KIND_PARAMETER = 0, 1, 2

PASSTHROUGH = False
SYNC_BIT = 0x00100000       # set => "None", clear => "Phase"   (77 BlendN + 17 AddSub + 17 Merge)

# --- TRANSITION FLAGS (derived 2026-08-10 over 321 transitions in the 37 oracles) --------
# bit2       UnkFlag2_DetachUpdateObservers
# bits18-19  UnkFlag18 / UnkFlag19
# bits20-22  condition count
# bits24-28  BlendModifier      0 -> SlowInSlowOut (318 witnesses), 1 -> SlowOut (3)
# bit29      SynchronizerType   1 -> None (320), 0 -> Phase (1)
# bits 1,3,6,7,8,9   present in the corpus, provably NOT emitted: every combination of them
#                    below appears in an oracle whose output is byte-identical without them.
BLEND_MODIFIERS = {0: 'SlowInSlowOut', 1: 'SlowOut'}
TRANSITION_BM_SHIFT, TRANSITION_BM_MASK = 24, 0x1F
TRANSITION_SYNC_BIT = 0x20000000
TRANSITION_INERT_BITS = 0x000003CA          # bits 1,3,6,7,8,9 - witnessed, no emission effect
TRANSITION_KNOWN_BITS = (0x00700004 | 0x000C0000 | TRANSITION_INERT_BITS
                         | (TRANSITION_BM_MASK << TRANSITION_BM_SHIFT) | TRANSITION_SYNC_BIT)


class MrfError(Exception):
    pass


class MrfUnpinned(MrfError):
    pass


def _f(v):
    return meta2xml.fmt_num(struct.unpack('<f', struct.pack('<I', v))[0])


def _b(v):
    return 'True' if v else 'False'


class _Mrf(object):
    def __init__(self, blob, names=None, strict=False):
        self.d = blob
        self.names = names or {}
        self.strict = strict
        self.unpinned = []

    def u16(self, o): return struct.unpack_from('<H', self.d, o)[0]
    def u32(self, o): return struct.unpack_from('<I', self.d, o)[0]
    def i32(self, o): return struct.unpack_from('<i', self.d, o)[0]
    def ptr(self, o): return o + self.i32(o)

    def nm(self, h):
        if h == 0:
            return ''
        s = self.names.get(h) or fallback_names().get(h)
        return s if s else 'hash_%08X' % h

    def unpin_text(self, what, value):
        msg = '%s: value 0x%X was never witnessed by the oracle' % (what, value)
        self.unpinned.append(msg)
        if self.strict:
            raise MrfUnpinned(msg)
        return 'UNPINNED_0x%X' % value

    def refuse(self, msg):
        self.unpinned.append(msg)
        if self.strict:
            raise MrfUnpinned(msg)

    def txt(self, ind, tag, s):
        return ['%s<%s />' % (ind, tag)] if not s else \
               ['%s<%s>%s</%s>' % (ind, tag, meta2xml.esc(s), tag)]

    def sync(self, ind, flags):
        return self.txt(ind, 'SynchronizerType', 'None' if flags & SYNC_BIT else 'Phase')

    # -- sourceable fields -----------------------------------------------------------
    def f_scalar(self, ind, tag, kind, p, boolean=False):
        """kind 0 -> <tag />, 1 -> value, 2 -> parameter. Returns (lines, next cursor)."""
        if kind == KIND_NONE:
            return ['%s<%s />' % (ind, tag)], p
        v = self.u32(p)
        if kind == KIND_VALUE:
            s = _b(v) if boolean else _f(v)
            return ['%s<%s value="%s" />' % (ind, tag, s)], p + 4
        if kind == KIND_PARAMETER:
            return ['%s<%s parameter="%s" />' % (ind, tag, meta2xml.esc(self.nm(v)))], p + 4
        self.refuse('%s source kind %d at 0x%X was never witnessed' % (tag, kind, p))
        return ['%s<%s value="UNPINNED_KIND_%d" />' % (ind, tag, kind)], p + 4

    def f_pair(self, ind, tag, kind, p):
        """A dictionary+name field (FrameFilter, Expression).
        kind 0 -> <tag />, 1 -> block with DictionaryName+Name (2 dwords), 2 -> parameter."""
        if kind == KIND_NONE:
            return ['%s<%s />' % (ind, tag)], p
        if kind == KIND_VALUE:
            out = ['%s<%s>' % (ind, tag)]
            out.extend(self.txt(ind + ' ', 'DictionaryName', self.nm(self.u32(p))))
            out.extend(self.txt(ind + ' ', 'Name', self.nm(self.u32(p + 4))))
            out.append('%s</%s>' % (ind, tag))
            return out, p + 8
        if kind == KIND_PARAMETER:
            return ['%s<%s parameter="%s" />' % (ind, tag, meta2xml.esc(self.nm(self.u32(p))))], p + 4
        self.refuse('%s source kind %d at 0x%X was never witnessed' % (tag, kind, p))
        return ['%s<%s />' % (ind, tag)], p + 4

    # -- hash tables -----------------------------------------------------------------
    def slot_table(self, off):
        n = self.u32(off)
        out = [struct.unpack_from('<II', self.d, off + 4 + 8 * i) for i in range(n)]
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

    # -- nodes -----------------------------------------------------------------------
    def node(self, off, tag, ind):
        t = self.u16(off)
        kind = NODE_TYPES.get(t)
        if kind is None:
            raise MrfUnpinned('node type %d at 0x%X is not in the oracle-pinned enum '
                              '(%s)' % (t, off, ', '.join(sorted(set(NODE_TYPES.values())))))
        body = getattr(self, '_n_' + kind.lower())(off, ind + ' ')
        return ['%s<%s type="%s">' % (ind, tag, kind)] + body + ['%s</%s>' % (ind, tag)]

    def head(self, off, ind):
        return self.txt(ind, 'Name', self.nm(self.u32(off + 4))) + \
            ['%s<NodeIndex value="%d" />' % (ind, self.u16(off + 2))]

    # leaves
    def _n_tail(self, off, ind):
        return self.head(off, ind)

    def _n_invalid(self, off, ind):
        return self.head(off, ind)

    def _n_subnetwork(self, off, ind):
        return self.head(off, ind) + \
            self.txt(ind, 'SubNetworkParameterName', self.nm(self.u32(off + 0x08)))

    # containers
    def _container_head(self, off, ind):
        flags = self.u32(off + 0x10)
        if flags & 0x0000FEFE:
            self.unpin_text('state flags low half', flags & 0xFFFF)
        return (self.head(off, ind)
                + ['%s<StateUnk3 value="%d" />' % (ind, self.u32(off + 0x0C))]
                + self.txt(ind, 'EntryParameterName', self.nm(self.u32(off + 0x14)))
                + self.txt(ind, 'ExitParameterName', self.nm(self.u32(off + 0x18))))

    def _states(self, off, base, n_states, ind):
        out = []
        if not n_states:
            out.append('%s<States />' % ind)
        else:
            out.append('%s<States>' % ind)
            for i in range(n_states):
                out.extend(self.node(self.ptr(base + 4 + 8 * i), 'Item', ind + ' '))
            out.append('%s</States>' % ind)
        return out

    def _n_statemachine(self, off, ind):
        flags = self.u32(off + 0x10)
        n_states, n_trans = (flags >> 16) & 0xFF, (flags >> 24) & 0xFF
        out = self._container_head(off, ind)
        out.append('%s<InitialState ref="%s" />'
                   % (ind, meta2xml.esc(self.nm(self.u32(self.ptr(off + 0x08) + 4)))))
        out.extend(self._states(off, off + 0x20, n_states, ind))
        out.extend(self.transitions(self.ptr(off + 0x1C), n_trans, ind))
        return out

    def _n_inlinedstatemachine(self, off, ind):
        flags = self.u32(off + 0x10)
        n_states, n_trans = (flags >> 16) & 0xFF, (flags >> 24) & 0xFF
        if n_trans:
            self.refuse('InlinedStateMachine at 0x%X carries %d transition(s) - the oracle '
                        'only witnessed the transition-free form' % (off, n_trans))
        out = self._container_head(off, ind)
        out.append('%s<InitialState ref="%s" />'
                   % (ind, meta2xml.esc(self.nm(self.u32(self.ptr(off + 0x08) + 4)))))
        out.extend(self._states(off, off + 0x24, n_states, ind))
        out.extend(self.node(self.ptr(off + 0x20), 'FallbackNode', ind))
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

    # leaves with payload
    def _n_clip(self, off, ind):
        flags = self.u32(off + 0x08)
        if flags & ~0x7FF:
            self.unpin_text('clip flags', flags & ~0x7FF)
        p = off + 0x0C
        out = self.head(off, ind)
        k = flags & 3
        if k == KIND_VALUE:
            ct, cname = self.u32(p), self.u32(p + 4)
            # MEASURED (mpheist minigame_drilling_bag, 17/17 clips): ContainerType 3 stores
            # only (type, containerName) - 2 dwords - and the reference exporter always
            # writes <Name /> for it. Reading a third dword ran the LAST clip past EOF.
            if ct == 3:
                clip = 0
                p += 8
            else:
                clip = self.u32(p + 8)
                p += 12
            ctxt = CONTAINER_TYPES.get(ct) or self.unpin_text('Clip ContainerType', ct)
            out.append('%s<Clip>' % ind)
            out.extend(self.txt(ind + ' ', 'ContainerType', ctxt))
            out.extend(self.txt(ind + ' ', 'ContainerName', self.nm(cname)))
            out.extend(self.txt(ind + ' ', 'Name', self.nm(clip)))
            out.append('%s</Clip>' % ind)
        elif k == KIND_PARAMETER:
            out.append('%s<Clip parameter="%s" />' % (ind, meta2xml.esc(self.nm(self.u32(p)))))
            p += 4
        else:
            raise MrfUnpinned('Clip node at 0x%X sources its clip by kind %d - the oracle '
                              'witnessed only inline (1) and parameter (2)' % (off, k))
        for i, tag in ((1, 'Phase'), (2, 'Rate'), (3, 'Delta')):
            lines, p = self.f_scalar(ind, tag, (flags >> (2 * i)) & 3, p)
            out.extend(lines)
        lines, p = self.f_scalar(ind, 'Looped', (flags >> 8) & 3, p, boolean=True)
        out.extend(lines)
        out.append('%s<UnkFlag10 value="%d" />' % (ind, (flags >> 10) & 1))
        return out

    def _n_filter(self, off, ind):
        flags = self.u32(off + 0x08)
        out = self.head(off, ind)
        out.extend(self.node(self.ptr(off + 0x0C), 'Child', ind))
        lines, _ = self.f_pair(ind, 'FrameFilter', flags & 3, off + 0x10)
        out.extend(lines)
        return out

    def _n_expression(self, off, ind):
        flags = self.u32(off + 0x08)
        out = self.head(off, ind)
        out.extend(self.node(self.ptr(off + 0x0C), 'Child', ind))
        p = off + 0x10
        expr, p = self.f_pair(ind, 'Expression', flags & 3, p)
        weight, p = self.f_scalar(ind, 'Weight', (flags >> 2) & 3, p)
        out.extend(weight)
        out.extend(expr)
        out.append('%s<Variables />' % ind)
        return out

    def _n_blendn(self, off, ind):
        flags = self.u32(off + 0x08)
        n = flags >> 26
        resid = flags & 0x03FFFFFF & ~SYNC_BIT
        if resid:
            self.unpin_text('BlendN flags', resid)
        out = self.head(off, ind)
        out.append('%s<FrameFilter />' % ind)
        out.extend(self.sync(ind, flags))
        out.append('%s<ZeroDestination value="False" />' % ind)
        if not n:
            out.append('%s<Children />' % ind)
            return out
        # PER-CHILD SOURCE KINDS. After the n child pointers comes a byte per child
        # (packed 4 per dword): bits0-1 = Weight kind, bits4-5 = FrameFilter kind. It reads
        # 0 whenever every child is plain, which is why it looked like "a 0 terminator".
        # MEASURED: taskambientlowriderarm BlendN @0x1C0 - ptrs 0x1CC/0x1D0, kinds 0x1D4 =
        # 0x00002020 (both children FrameFilter kind 2), payloads 0x1D8/0x1DC = 0x3273E937.
        kw = off + 0x0C + 4 * n
        nkw = (n + 3) // 4
        p = kw + 4 * nkw
        kinds = []
        for i in range(n):
            kinds.append((self.u32(kw + 4 * (i // 4)) >> (8 * (i % 4))) & 0xFF)
        if n > 4 and any(kinds):
            self.refuse('BlendN at 0x%X has %d children AND a non-zero child-kind word - '
                        'only the <=4-child packing was witnessed' % (off, n))
        out.append('%s<Children>' % ind)
        for i in range(n):
            kb = kinds[i]
            if kb & ~0x33:
                self.unpin_text('BlendN child kind byte', kb)
            out.append('%s <Item>' % ind)
            wl, p = self.f_scalar(ind + '  ', 'Weight', kb & 3, p)
            fl, p = self.f_pair(ind + '  ', 'FrameFilter', (kb >> 4) & 3, p)
            out.extend(wl)
            out.extend(fl)
            out.extend(self.node(self.ptr(off + 0x0C + 4 * i), 'Node', ind + '  '))
            out.append('%s </Item>' % ind)
        out.append('%s</Children>' % ind)
        return out

    def _two_child(self, off, ind, weight, merge_blend):
        flags = self.u32(off + 0x08)
        out = self.head(off, ind)
        out.extend(self.node(self.ptr(off + 0x0C), 'Child0', ind))
        out.extend(self.node(self.ptr(off + 0x10), 'Child1', ind))
        out.extend(self.txt(ind, 'Child0InfluenceOverride', 'None'))
        out.extend(self.txt(ind, 'Child1InfluenceOverride', 'None'))
        p = off + 0x14
        if weight:
            wl, p = self.f_scalar(ind, 'Weight', flags & 3, p)
            out.extend(wl)
            ffk = (flags >> 2) & 3
        else:
            ffk = flags & 3
        ff, p = self.f_pair(ind, 'FrameFilter', ffk, p)
        out.extend(ff)
        out.extend(self.sync(ind, flags))
        if merge_blend:
            out.append('%s<MergeBlend value="False" />' % ind)
        out.append('%s<UnkFlag6 value="%s" />' % (ind, _b((flags >> 6) & 1)))
        out.append('%s<UnkFlag7 value="%d" />' % (ind, (flags >> 7) & 1))
        out.append('%s<UnkFlag21 value="%d" />' % (ind, (flags >> 21) & 1))
        if merge_blend:
            out.append('%s<UnkFlag23 value="%d" />' % (ind, (flags >> 23) & 1))
            out.append('%s<UnkFlag25 value="%s" />' % (ind, _b((flags >> 25) & 1)))
        return out

    def _n_addsubtract(self, off, ind):
        return self._two_child(off, ind, weight=True, merge_blend=True)

    def _n_blend(self, off, ind):
        return self._two_child(off, ind, weight=True, merge_blend=True)

    def _n_merge(self, off, ind):
        return self._two_child(off, ind, weight=False, merge_blend=False)

    # -- state sub-arrays --------------------------------------------------------------
    def cond_stride(self, off):
        """Condition records are VARIABLE width, by shape:
             8 B  value_float  (TimeGreaterThan)     MEASURED weapon.mrf 0x42C..0x434
            12 B  bit / param_bool / param_float
            16 B  param_range  (Min AND Max)         MEASURED mpheist task_mp_pointing 0x1E8
        A fixed 12 walked the next record into garbage in both directions."""
        shape = COND_SHAPE.get(CONDITION_TYPES.get(self.u32(off)))
        return {'value_float': 8, 'param_range': 16}.get(shape, 12)

    def cond_block(self, off, n):
        """-> [(offset, stride)] for the n conditions starting at off, and the end offset."""
        out = []
        for _ in range(n):
            s = self.cond_stride(off)
            out.append(off)
            off += s
        return out, off

    def transitions(self, off, n, ind):
        if not n:
            return ['%s<Transitions />' % ind]
        out = ['%s<Transitions>' % ind]
        for _ in range(n):
            out.extend(self.transition(off, ind + ' '))
            _, end = self.cond_block(off + 0x18, (self.u32(off) >> 20) & 7)
            off = end
        out.append('%s</Transitions>' % ind)
        return out

    def transition(self, off, ind):
        flags = self.u32(off)
        n_cond = (flags >> 20) & 7
        resid = flags & ~TRANSITION_KNOWN_BITS
        if PASSTHROUGH:
            w = {'BlendModifier': 'R%08X' % resid, 'SynchronizerType': 'S%08X' % resid}
        else:
            if resid:
                self.refuse('Transition at 0x%X: flag bits 0x%08X outside the derived '
                            'layout were never witnessed' % (off, resid))
            bm = (flags >> TRANSITION_BM_SHIFT) & TRANSITION_BM_MASK
            bmt = BLEND_MODIFIERS.get(bm)
            if bmt is None:
                self.refuse('Transition at 0x%X: BlendModifier %d was never witnessed '
                            '(only 0=SlowInSlowOut, 1=SlowOut)' % (off, bm))
                bmt = 'UNPINNED_BM_%d' % bm
            w = {'BlendModifier': bmt,
                 'SynchronizerType': 'None' if flags & TRANSITION_SYNC_BIT else 'Phase'}
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
            offs, _ = self.cond_block(off + 0x18, n_cond)
            for o in offs:
                out.extend(self.condition(o, i2 + ' '))
            out.append('%s</Conditions>' % i2)
        out.append('%s</Item>' % ind)
        return out

    def condition(self, off, ind):
        t, a, b = struct.unpack_from('<III', self.d, off)
        kind = CONDITION_TYPES.get(t)
        if kind is None:
            raise MrfUnpinned('transition condition type %d at 0x%X is not in the '
                              'oracle-pinned enum' % (t, off))
        out = ['%s<Item type="%s">' % (ind, kind)]
        shape = COND_SHAPE[kind]
        if shape == 'bit':
            out.append('%s <BitPosition value="%d" />' % (ind, a))
            out.append('%s <Invert value="%s" />' % (ind, _b(b)))
        elif shape == 'param_bool':
            out.extend(self.txt(ind + ' ', 'ParameterName', self.nm(a)))
            out.append('%s <Value value="%s" />' % (ind, _b(b)))
        elif shape == 'param_float':
            out.extend(self.txt(ind + ' ', 'ParameterName', self.nm(a)))
            out.append('%s <Value value="%s" />' % (ind, _f(b)))
        elif shape == 'param_range':
            # MEASURED (mpheist task_mp_pointing @0x1E8/0x7EC/0xE18): the record stores
            # MAX at +0x08 and MIN at +0x0C - the reverse of the emitted order.
            out.extend(self.txt(ind + ' ', 'ParameterName', self.nm(a)))
            out.append('%s <Min value="%s" />' % (ind, _f(self.u32(off + 12))))
            out.append('%s <Max value="%s" />' % (ind, _f(b)))
        elif shape == 'value_float':
            out.append('%s <Value value="%s" />' % (ind, _f(a)))
        out.append('%s</Item>' % ind)
        return out

    def params(self, off, n, ind, tag, name_tag, side):
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
            return (['%s<Item type="Finish">' % ind, '%s</Item>' % ind], off + 4, True)
        if kind == 'PushParameter':
            out = ['%s<Item type="PushParameter">' % ind]
            out.extend(self.txt(ind + ' ', 'ParameterName', self.nm(self.u32(off + 4))))
            out.append('%s</Item>' % ind)
            return out, off + 8, False
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


COND_SHAPE = {
    'MoveNetworkTrigger': 'bit', 'MoveNetworkFlag': 'bit',
    'EventOccurred': 'param_bool', 'BoolParameterEquals': 'param_bool',
    'ParameterGreaterThan': 'param_float', 'ParameterGreaterOrEqual': 'param_float',
    'ParameterLessThan': 'param_float', 'ParameterLessOrEqual': 'param_float',
    'ParameterInsideRange': 'param_range', 'ParameterOutsideRange': 'param_range',
    'TimeGreaterThan': 'value_float', 'TimeLessThan': 'value_float',
}


def convert(name, blob, names=None, strict=False):
    m = _Mrf(blob, names, strict)
    return '\r\n'.join(m.lines()) + '\r\n'


def convert_with_report(name, blob, names=None, strict=False):
    m = _Mrf(blob, names, strict)
    return '\r\n'.join(m.lines()) + '\r\n', list(m.unpinned)
