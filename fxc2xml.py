"""fxc2xml - binary GTA V .fxc (rage compiled shader effect, 'rgxe') -> RAGE interchange XML
plus one .cso sidecar per compiled shader.

CLEAN-ROOM: every field below was pinned by reading the oracle XML first and then
value-intersecting it against the game binary (_Oracles/fxc/00_base + 10_update,
common.rpf\\shaders\\win32_40_final\\water_foam.fxc and its update2.rpf twin). Structural
rules that the two oracles could not settle on their own were pinned against the 321 .fxc in
common.rpf using ONLY self-describing evidence carried by the files themselves - the DXBC
container's own program-type/version token. No any third-party tool or RAGE source was consulted.

WHOLE-FILE LAYOUT (all little-endian; "str" = uint8 length INCLUDING the NUL, then the bytes)

  0x00  char[4]   magic 'rgxe'
  0x04  uint32    vertexType bitfield -> the <VertexType> letters (see VTYPE_BITS)
  0x08  uint8     preset-param count, then that many param records (see rd_param)
        --- six shader arrays, in this order: VS, PS, CS, DS, GS, HS ---
        uint8     count, then `count` shader records.  Entry 0 is ALWAYS the placeholder
                  named "NULL" (size 0); technique indices are 1-based over the real
                  shaders because of it - which is what the reference exporter's OffsetBy1 attribute names.
        shader record:
              str        name
              uint8 n    n x str   - names of the variables the shader uses
              uint8 m    m x (str name, uint16 slot) - constant buffers it binds
              uint8      GEOMETRY-SHADER ARRAY ONLY: one extra byte (always 0, 764 obs)
              uint32     bytecode size
              byte[size] DXBC bytecode  -> written out verbatim as "<stem>/<name>.cso"
              uint8,uint8  VS/PS/GS ARRAYS ONLY, and only when size>0: shader model
                           major, minor.  MEASURED: equals the DXBC SHDR/SHEX version
                           token in 9,111 of 9,111 shaders.  CS/DS/HS records carry no
                           such pair - verified by the fact that all 321 files then
                           consume to their exact byte length.
        --- two constant-buffer tables + two variable tables ---
        uint8 count, then `count` cbuffer records:
              uint32 size, uint16[6] slots (VS,PS,CS,DS,GS,HS), str name
        uint8 count, then `count` variable records:
              uint8 type, uint8 Count, uint8 Slot, uint8 Group,
              str Name1, str Name2,
              uint8 Offset, uint8 Variant, uint16 reserved (0 in all 19,490 observed),
              ⭐ BOTH oracles spell <Count value="0"/>, so the oracle alone cannot say which
                 of those two always-zero-here fields is Count.  Settled independently: the
                 byte at +1 equals the DXBC RDEF element count of the same-named variable in
                 16,038 of 16,039 game-wide matches (the lone miss is `instanceData`, whose
                 1,280 elements do not fit a uint8), while the uint16 is 0 in all 19,490.
              uint32 joaat(buffer name) - 0 when the variable is not buffer-backed,
              uint8 p, p x param record,
              uint8 v, v x float32   -> <Values>
        --- techniques ---
        uint8 count, then: str name, uint8 passes, per pass:
              uint8[6]  shader indices into the VS,PS,CS,DS,GS,HS arrays
              uint8 p, p x (uint32 type, uint32 value)  -> <Params>

  param record:  str name, uint8 type, then
                   type 0 = Int    -> uint32  -> <Value value="N" />
                   type 1 = Float  -> float32 -> <Value value="N" />
                   type 2 = String -> str     -> <Value>text</Value>

WHAT THIS MODULE REFUSES RATHER THAN GUESS (see FxcUnpinned):
  * a vertexType bit other than 0/6 - the oracle only ever spells "PT", so only those two
    letters are known.  42/321 files stay inside it.
  * a variable type code outside TYPE_NAMES - 17 codes exist game-wide, 4 are witnessed.
  * a populated ComputeShaders/DomainShaders/GeometryShaders/HullShaders array, or a
    technique pass that references one - the element names/order the reference exporter writes there are
    unwitnessed.
  * a param type code above 2.
Each refusal names the exact missing datum so one more oracle export closes it.

Reuses: fmt_num / esc / joaat from meta2xml (the proven float-text + XML-escape laws).
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) or '.')
from meta2xml import esc, fmt_num, joaat

MAGIC = b'rgxe'

# Shader arrays, in file order.  The mapping was pinned from the DXBC program-type token
# inside each array's own bytecode across all 321 game .fxc: array 0 held 3,676 vertex
# shaders and nothing else, array 1 held 4,992 pixel shaders, array 2 held 32 compute,
# array 3 held 189 domain, array 4 held 443 geometry, array 5 held 189 hull - zero
# exceptions.  The XML element names come from the oracle, which lists exactly these six.
GROUPS = ('VertexShaders', 'PixelShaders', 'ComputeShaders',
          'DomainShaders', 'GeometryShaders', 'HullShaders')
GS_GROUP = 4                      # the array whose records carry the extra byte
VER_GROUPS = (0, 1, 4)            # the arrays whose records carry the trailing version pair

# <HullShaders OffsetBy1="True" /> - MEASURED CONSTANT, not read from the file.  Both
# oracles spell it identically and nothing in the binary varies with it; every array in
# every one of the 321 files begins with the same "NULL" placeholder, so if the attribute
# does encode "index 0 is a placeholder" it is universally true.  Emitted verbatim.
HULL_ATTR = ' OffsetBy1="True"'

# uint32 at 0x04 -> <VertexType> letters.  ONLY 0x41 ("PT") is oracle-witnessed, so only
# these two bits have a known letter; any other set bit is a refusal, not a guess.
VTYPE_BITS = {0: 'P', 6: 'T'}

# Variable type code -> <Type> text.  ORACLE-WITNESSED ONLY.  Game-wide the codes
# 2,3,4,5,6,7,8,9,11,14,15,17,18,19,20,21,22 all occur; the four below are the ones the
# two oracles actually spell.  (17/20 = Unused1/Unused4 makes 16+N look like the family
# rule, which would give 18=Unused2 and 19=Unused3 - NOT added, because inferring a name
# from two anchors is still inventing the other two.)
TYPE_NAMES = {4: 'Float3', 9: 'Float4x4', 17: 'Unused1', 20: 'Unused4'}

PARAM_TYPES = {0: 'Int', 1: 'Float', 2: 'String'}


class FxcUnpinned(ValueError):
    """A field exists in this file whose XML spelling no oracle has ever shown."""


class _R(object):
    def __init__(self, b):
        self.b, self.o = b, 0

    def u8(self):
        v = self.b[self.o]
        self.o += 1
        return v

    def u16(self):
        v = struct.unpack_from('<H', self.b, self.o)[0]
        self.o += 2
        return v

    def u32(self):
        v = struct.unpack_from('<I', self.b, self.o)[0]
        self.o += 4
        return v

    def f32(self):
        v = struct.unpack_from('<f', self.b, self.o)[0]
        self.o += 4
        return v

    def s(self):
        n = self.u8()
        raw = self.b[self.o:self.o + n]
        if len(raw) != n:
            raise ValueError('string runs past end of file at %#x' % (self.o - 1))
        self.o += n
        return raw.split(b'\0')[0].decode('latin-1')


def _rd_param(r):
    name = r.s()
    t = r.u8()
    if t == 0:
        return name, t, r.u32()
    if t == 1:
        return name, t, r.f32()
    if t == 2:
        return name, t, r.s()
    raise FxcUnpinned('param "%s" has type code %d at %#x - only 0/1/2 (Int/Float/String) '
                      'are witnessed, so its payload size is unknown' % (name, t, r.o - 1))


def _rd_shader(r, gi):
    name = r.s()
    variables = [r.s() for _ in range(r.u8())]
    buffers = [(r.s(), r.u16()) for _ in range(r.u8())]
    extra = r.u8() if gi == GS_GROUP else 0
    size = r.u32()
    data = bytes(r.b[r.o:r.o + size])
    if len(data) != size:
        raise ValueError('shader "%s" bytecode runs past end of file' % name)
    r.o += size
    ver = (r.u8(), r.u8()) if (size and gi in VER_GROUPS) else (0, 0)
    return dict(name=name, variables=variables, buffers=buffers, size=size,
                data=data, major=ver[0], minor=ver[1], extra=extra)


def _rd_cbuffer(r):
    size = r.u32()
    slots = [r.u16() for _ in range(6)]
    return dict(size=size, slots=slots, name=r.s())


def _rd_variable(r):
    v = dict(type=r.u8(), count=r.u8(), slot=r.u8(), group=r.u8())
    v['name1'] = r.s()
    v['name2'] = r.s()
    v['offset'] = r.u8()
    v['variant'] = r.u8()
    v['reserved'] = r.u16()
    v['bufhash'] = r.u32()
    v['params'] = [_rd_param(r) for _ in range(r.u8())]
    v['values'] = [r.f32() for _ in range(r.u8())]
    return v


def parse(blob):
    """Binary -> the whole effect as plain dicts.  Raises on anything it cannot account
    for; a parse that does not consume the file EXACTLY is a failed parse, not a warning."""
    if blob[:4] != MAGIC:
        raise ValueError('not an fxc: magic %r (expected %r)' % (blob[:4], MAGIC))
    r = _R(blob)
    r.o = 4
    d = {'vertex_type': r.u32()}
    d['preset'] = [_rd_param(r) for _ in range(r.u8())]
    d['groups'] = [[_rd_shader(r, gi) for _ in range(r.u8())] for gi in range(6)]
    d['cbuffers1'] = [_rd_cbuffer(r) for _ in range(r.u8())]
    d['variables1'] = [_rd_variable(r) for _ in range(r.u8())]
    d['cbuffers2'] = [_rd_cbuffer(r) for _ in range(r.u8())]
    d['variables2'] = [_rd_variable(r) for _ in range(r.u8())]
    techniques = []
    for _ in range(r.u8()):
        name = r.s()
        passes = []
        for _ in range(r.u8()):
            idx = [r.u8() for _ in range(6)]
            params = [(r.u32(), r.u32()) for _ in range(r.u8())]
            passes.append((idx, params))
        techniques.append((name, passes))
    d['techniques'] = techniques
    if r.o != len(blob):
        raise ValueError('fxc parse consumed %d of %d bytes - layout does not fit this file'
                         % (r.o, len(blob)))
    return d


def _vertex_type(bits):
    out = []
    for i in range(32):
        if bits & (1 << i):
            if i not in VTYPE_BITS:
                raise FxcUnpinned('vertexType %#x sets bit %d, whose <VertexType> letter is '
                                  'unwitnessed (only 0x41 -> "PT" is in the oracle set)'
                                  % (bits, i))
            out.append(VTYPE_BITS[i])
    return ''.join(out)


def _type_name(v):
    if v['type'] not in TYPE_NAMES:
        raise FxcUnpinned('variable "%s" has type code %d, whose <Type> text is unwitnessed '
                          '(witnessed: %s)'
                          % (v['name1'], v['type'],
                             ', '.join('%d=%s' % kv for kv in sorted(TYPE_NAMES.items()))))
    return TYPE_NAMES[v['type']]


def _param_lines(params, ind):
    """A <Params> block.  ind = indent of the <Params> tag itself."""
    p, i, c = ' ' * ind, ' ' * (ind + 1), ' ' * (ind + 2)
    out = ['%s<Params>' % p]
    for name, t, val in params:
        out.append('%s<Item>' % i)
        out.append('%s<Name>%s</Name>' % (c, esc(name)))
        out.append('%s<Type>%s</Type>' % (c, PARAM_TYPES[t]))
        if t == 2:
            out.append('%s<Value>%s</Value>' % (c, esc(val)))
        else:
            out.append('%s<Value value="%s" />' % (c, fmt_num(val)))
        out.append('%s</Item>' % i)
    out.append('%s</Params>' % p)
    return out


def _variable_lines(v, buffer_names):
    """One <Item> of Variables1 / Variables2 (indent 2, fields at 3)."""
    out = ['  <Item>',
           '   <Name1>%s</Name1>' % esc(v['name1']),
           '   <Name2>%s</Name2>' % esc(v['name2'])]
    if v['bufhash']:
        if v['bufhash'] not in buffer_names:
            raise FxcUnpinned('variable "%s" names constant buffer %#010x, which no CBuffers '
                              'entry in this file hashes to - the <Buffer> text is unknown'
                              % (v['name1'], v['bufhash']))
        out.append('   <Buffer>%s</Buffer>' % esc(buffer_names[v['bufhash']]))
    else:
        out.append('   <Buffer />')
    out.append('   <Type>%s</Type>' % _type_name(v))
    out.append('   <Count value="%d" />' % v['count'])
    out.append('   <Slot value="%d" />' % v['slot'])
    out.append('   <Group value="%d" />' % v['group'])
    out.append('   <Offset value="%d" />' % v['offset'])
    out.append('   <Variant value="%d" />' % v['variant'])
    if v['params']:
        out.extend(_param_lines(v['params'], 3))
    if v['values']:
        out.append('   <Values>%s</Values>' % ' '.join(fmt_num(x) for x in v['values']))
    out.append('  </Item>')
    return out


def _cbuffer_lines(cb):
    return ['  <Item>',
            '   <Name>%s</Name>' % esc(cb['name']),
            '   <Size value="%d" />' % cb['size']] + \
           ['   <Slot%s value="%d" />' % (tag, cb['slots'][i])
            for i, tag in enumerate(('VS', 'PS', 'CS', 'DS', 'GS', 'HS'))] + \
           ['  </Item>']


def _shader_lines(sh):
    """One <Item> of a shader array.  ⭐ The shader arrays indent their items by TWO, not
    one: <VertexShaders> sits at 2 and its <Item> at 4 (every other list steps by one).
    That is the oracle's spelling and it is load-bearing for byte identity."""
    out = ['    <Item>',
           '     <Name>%s</Name>' % esc(sh['name']),
           '     <File>%s.cso</File>' % esc(sh['name']),
           '     <VersionMajor value="%d" />' % sh['major'],
           '     <VersionMinor value="%d" />' % sh['minor']]
    if sh['variables']:
        out.append('     <Variables>')
        out.extend('      <Item>%s</Item>' % esc(n) for n in sh['variables'])
        out.append('     </Variables>')
    else:
        out.append('     <Variables />')
    if sh['buffers']:
        out.append('     <Buffers>')
        for name, slot in sh['buffers']:
            out.append('      <Item>')
            out.append('       <Name>%s</Name>' % esc(name))
            out.append('       <Slot value="%d" />' % slot)
            out.append('      </Item>')
        out.append('     </Buffers>')
    else:
        out.append('     <Buffers />')
    out.append('    </Item>')
    return out


def to_xml(d):
    for gi in (2, 3, 4, 5):
        real = [s['name'] for s in d['groups'][gi] if s['size']]
        if real:
            raise FxcUnpinned('%s holds %d compiled shader(s) (%s); no oracle shows how the reference exporter '
                              'writes a populated non-VS/PS array (or whether HullShaders '
                              'keeps its OffsetBy1 attribute when populated)'
                              % (GROUPS[gi], len(real), ', '.join(real[:3])))

    buffer_names = {}
    for cb in d['cbuffers1'] + d['cbuffers2']:
        buffer_names[joaat(cb['name'])] = cb['name']

    out = ['<?xml version="1.0" encoding="UTF-8"?>', '<Effects>']
    out.append(' <VertexType>%s</VertexType>' % _vertex_type(d['vertex_type']))

    if d['preset']:
        out.append(' <PresetParams>')
        for name, t, val in d['preset']:
            out.append('  <Item>')
            out.append('   <Name>%s</Name>' % esc(name))
            # The oracle's only preset param is an Int and carries NO <Type> element -
            # unlike a variable's params, which do.
            if t == 2:
                raise FxcUnpinned('preset param "%s" is a String; the oracle only ever shows '
                                  'an Int preset param, so its <Value> spelling is unknown'
                                  % name)
            out.append('   <Value value="%s" />' % fmt_num(val))
            out.append('  </Item>')
        out.append(' </PresetParams>')
    else:
        out.append(' <PresetParams />')

    out.append(' <Shaders>')
    for gi, tag in enumerate(GROUPS):
        attr = HULL_ATTR if tag == 'HullShaders' else ''
        items = [s for s in d['groups'][gi] if s['size']]
        if not items:
            out.append('  <%s%s />' % (tag, attr))
            continue
        out.append('  <%s%s>' % (tag, attr))
        for sh in items:
            out.extend(_shader_lines(sh))
        out.append('  </%s>' % tag)
    out.append(' </Shaders>')

    for tag, cbs, vars_ in (('1', d['cbuffers1'], d['variables1']),
                            ('2', d['cbuffers2'], d['variables2'])):
        if cbs:
            out.append(' <CBuffers%s>' % tag)
            for cb in cbs:
                out.extend(_cbuffer_lines(cb))
            out.append(' </CBuffers%s>' % tag)
        else:
            out.append(' <CBuffers%s />' % tag)
        if vars_:
            out.append(' <Variables%s>' % tag)
            for v in vars_:
                out.extend(_variable_lines(v, buffer_names))
            out.append(' </Variables%s>' % tag)
        else:
            out.append(' <Variables%s />' % tag)

    if d['techniques']:
        out.append(' <Techniques>')
        for name, passes in d['techniques']:
            out.append('  <Item>')
            out.append('   <Name>%s</Name>' % esc(name))
            if not passes:
                out.append('   <Passes />')
                out.append('  </Item>')
                continue
            out.append('   <Passes>')
            for idx, params in passes:
                for gi in (2, 3, 4, 5):
                    if idx[gi]:
                        raise FxcUnpinned(
                            'technique "%s" binds a %s at index %d; the element name and '
                            'ordering the reference exporter writes for a non-VS/PS stage are unwitnessed'
                            % (name, GROUPS[gi], idx[gi]))
                for gi in (0, 1):
                    if not idx[gi]:
                        raise FxcUnpinned(
                            'technique "%s" leaves %s at the NULL placeholder (index 0); '
                            'how the reference exporter spells an unbound stage is unwitnessed'
                            % (name, GROUPS[gi]))
                out.append('    <Item>')
                out.append('     <VertexShader>%s</VertexShader>'
                           % esc(d['groups'][0][idx[0]]['name']))
                out.append('     <PixelShader>%s</PixelShader>'
                           % esc(d['groups'][1][idx[1]]['name']))
                if params:
                    out.append('     <Params>')
                    for ptype, pval in params:
                        out.append('      <Item>')
                        out.append('       <Type value="%d" />' % ptype)
                        out.append('       <Value value="%d" />' % pval)
                        out.append('      </Item>')
                    out.append('     </Params>')
                else:
                    out.append('     <Params />')
                out.append('    </Item>')
            out.append('   </Passes>')
            out.append('  </Item>')
        out.append(' </Techniques>')
    else:
        out.append(' <Techniques />')

    out.append('</Effects>')
    return '\n'.join(out) + '\n'


def convert(name, blob, names=None):
    """`name` is only carried for parity with the other converters; the XML holds no
    filename. `names` (joaat dictionary) is unused - an fxc stores every name as text."""
    return to_xml(parse(blob))


def sidecars(name, blob):
    """[(relative path, bytes)] - the compiled bytecode.  ⭐ the reference exporter does NOT inline it: each
    shader is a separate "<stem>/<ShaderName>.cso" holding the DXBC verbatim, and the XML
    points at it by <File>.  MEASURED against the oracle tree: water_foam.fxc.xml sits
    beside water_foam/VSRiverWater.cso (1,364 B) and water_foam/PS_Foam.cso (808 B), each
    byte-identical to the blob stored in the container."""
    stem = os.path.splitext(os.path.basename(name))[0]
    out = []
    for group in parse(blob)['groups']:
        for sh in group:
            if sh['size']:
                out.append(('%s/%s.cso' % (stem, sh['name']), sh['data']))
    return tuple(out)


if __name__ == '__main__':
    for p in sys.argv[1:]:
        sys.stdout.write(convert(os.path.basename(p), open(p, 'rb').read()))
