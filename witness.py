"""⛔⛔ WITNESS TOPICS — what the churn gate must be able to SEE, for EVERY type.

THE DEFECT THIS GENERALISES (#32d, 2026-08-05). The whole `occludeModels` emitter shipped under a
green "OK - no churn": only 2 of the 67 ymap in the fixture project carry an occluder and the
seeded 25-file sample drew NEITHER. The fix was PINNED WITNESSES - fixtures unioned with the
sample and never sampled from - and it worked, but the topic list it was driven from
(`meta2xml.YMAP_WITNESS_TOPICS`) covered YMAP CONTAINERS ONLY. `ytyp compositeEntityTypes` (47 of
1,711 files, 2.7%) was blind in exactly the same way, and so was every optional structure of
ytyp/ymt/ydr/ydd/yft/ybn.

⛔ A HAND-MAINTAINED TOPIC LIST IS A FUTURE SILENT GAP, which is the reason this module exists at
all. The list is derived THREE ways, from three independent directions, and a topic only has to
appear in ONE of them to be guarded:

  1. SOURCE (live, computed on every gate run from the emitter modules' own AST). Every XML tag
     literal an emitter can write, plus every constant handed to a tag-parametrised helper
     (`_val("flags", ...)`, `_container("rooms", ...)`, `_bound_lines(..., "Bounds", ...)`) -
     the helper's tag parameter is itself found by looking for a `<%s` hole in its format string,
     so nothing here is a list someone has to remember to update.
  2. CENSUS (baked, `<project>/_pinned/_TOPICS.json`, built by `quarry.py witness`). Every tag
     the emitters ACTUALLY WROTE across the operator's whole emitted corpus - 262k real game
     files - with a carrier count and the smallest carriers. This is what catches the
     table-driven tags source analysis cannot see (`EXT_SPECS` alone contributes 140+ ytyp field
     names), and it is the receipt behind every exemption.
  3. LIVE (this run). Any content-bearing tag in ANY fixture's output - sampled or pinned. If a
     fixture emits something no topic covers, the topic list is behind the code and says so.

A topic the census has never seen a CARRIER for is EXEMPT, printed every run with its census
receipt - never silenced. (`containerLods` is the precedent: 0 populated in 11,084 ymap.) A topic
with carriers and no pinned witness is a --strict FAILURE, because that is #32d exactly.

⛔ THE WITNESS RULE IS "CONTENT-BEARING", NOT "PRESENT". `<occludeModels itemType="OccludeModel"
/>` is emitted by EVERY ymap; the populated form by 227. A presence test would have called the
container covered on day one and the emitter would still be shipping unseen. So a tag counts as
witnessed only when a file shows it carrying something: a closing tag, a value-bearing attribute,
or - for a container the emitter deliberately refuses - its `QUARRY DROPPED` marker, which is the
only output a dropped container has.
"""
import ast
import json
import os
import re

QUARRY_DIR = os.path.dirname(os.path.abspath(__file__))

# The artifact this module reads, relative to the fixture project. It lives BESIDE _PINNED.json
# and is NEVER committed, for the same reason the baseline is not: it is derived from the
# operator's own extraction of their own copy of the game.
CENSUS_FILE = os.path.join('_pinned', '_TOPICS.json')
CENSUS_VERSION = 1

# ------------------------------------------------------------------ the witness rule
_CLOSE = re.compile(r'</([A-Za-z_][\w.\-]*)>')
_SELF = re.compile(r'<([A-Za-z_][\w.\-]*)((?:\s+[\w:.\-]+="[^"]*")*)\s*/>')
_ATTR = re.compile(r'([\w:.\-]+)="')
_MARK = re.compile(r'QUARRY DROPPED ([A-Za-z_][\w.\-]*)')
# `itemType` is the ONE attribute that does not count as content: the empty form of every RAGE
# container carries it (`<carGenerators itemType="CCarGen" />`) and treating that as a witness is
# precisely the blindness #32d was.
_NOT_CONTENT = {'itemType'}


def witnessed_tags(xml):
    """Every tag this emitted document shows CARRYING SOMETHING - see the module docstring."""
    out = set(_CLOSE.findall(xml))
    for m in _SELF.finditer(xml):
        if set(_ATTR.findall(m.group(2))) - _NOT_CONTENT:
            out.add(m.group(1))
    out |= set(_MARK.findall(xml))
    return out


def empty_form_tags(xml):
    """Tags this document emits ONLY as an empty element (`<t />` / `<t itemType="X" />`).

    Kept separate from witnessed_tags because the difference IS the finding: a tag that the whole
    corpus only ever emits empty cannot be witnessed by content, and saying so with a count is
    the honest alternative to either failing forever or pretending it is covered."""
    out = set()
    for m in _SELF.finditer(xml):
        if not (set(_ATTR.findall(m.group(2))) - _NOT_CONTENT):
            out.add(m.group(1))
    return out


# ------------------------------------------------------------------ source-derived topics
_TAG_LIT = re.compile(r'<\s*/?\s*([A-Za-z_][A-Za-z0-9_.\-]*)')
# A struct format string starts with a byte-order char and holds only format codes. Without this
# `struct.unpack_from("<II", ...)` contributes a topic called `II`.
_STRUCT_FMT = re.compile(r'^[<>=!@]?[0-9bBhHiIlLqQnNefdspPx?\s]*$')
# Prose, not output: argparse text and anything printed. A `--out` help string mentioning
# `<stem>.ydr.xml` is not an emitter branch.
_PROSE_KW = {'help', 'description', 'metavar', 'prog', 'epilog'}
_PROSE_CALL = {'print', 'error', 'warn', 'warning', 'ArgumentParser', 'add_argument',
               'ArgumentTypeError', 'format_help'}


def _fmt_holes(fmt):
    """(position, conversion index) of every %-conversion in `fmt`. `%%` is not one."""
    out, i, n = [], 0, 0
    while i < len(fmt):
        if fmt[i] == '%':
            j = i + 1
            while j < len(fmt) and fmt[j] in '-+ #0123456789.*':
                j += 1
            if j < len(fmt) and fmt[j] == '%':
                i = j + 1
                continue
            out.append((i, n))
            n += 1
            i = j + 1
        else:
            i += 1
    return out


def _tag_param_indexes(fn):
    """Which of this function's parameters end up spelled AS AN ELEMENT NAME.

    Found by looking for a `%s` hole that sits immediately after a `<` or `</` and resolving it
    back to the parameter it interpolates. That is how `_container(tag, ...)`,
    `_val(tag, ...)` and `_bound_lines(res, off, ind, tag, ...)` are all discovered without
    anybody listing them - including `_bound_lines`, whose tag is the FOURTH argument."""
    params = [a.arg for a in fn.args.args]
    found = set()
    for node in ast.walk(fn):
        if not (isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod)
                and isinstance(node.left, ast.Constant)
                and isinstance(node.left.value, str)):
            continue
        fmt = node.left.value
        elts = node.right.elts if isinstance(node.right, ast.Tuple) else [node.right]
        for pos, k in _fmt_holes(fmt):
            pre = fmt[:pos]
            if not (pre.endswith('<') or pre.endswith('</')):
                continue
            if k < len(elts) and isinstance(elts[k], ast.Name) and elts[k].id in params:
                found.add(params.index(elts[k].id))
    return found


def _prose_constants(tree):
    """ids of the string Constants that are documentation or CLI text, not emitted XML."""
    skip = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if ast.get_docstring(node, clean=False) is not None and node.body \
                    and isinstance(node.body[0], ast.Expr):
                skip.add(id(node.body[0].value))
        if isinstance(node, ast.Call):
            fname = (node.func.id if isinstance(node.func, ast.Name)
                     else node.func.attr if isinstance(node.func, ast.Attribute) else '')
            if fname in _PROSE_CALL:
                skip |= {id(c) for c in ast.walk(node) if isinstance(c, ast.Constant)}
            for kw in node.keywords:
                if kw.arg in _PROSE_KW:
                    skip |= {id(c) for c in ast.walk(kw.value) if isinstance(c, ast.Constant)}
    return skip


def source_topics(module_file):
    """{tag: sorted[why]} every tag the module's own source can spell. `why` is the site."""
    with open(os.path.join(QUARRY_DIR, module_file), encoding='utf-8') as fh:
        tree = ast.parse(fh.read())
    tagfns = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            idx = _tag_param_indexes(node)
            if idx:
                tagfns[node.name] = idx
    # A wrapper that forwards its own parameter into a helper's tag slot is a tag-parametrised
    # emitter too; iterate to a fixed point so a chain of them resolves.
    for _ in range(5):
        grew = False
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            params = [a.arg for a in node.args.args]
            for c in ast.walk(node):
                if not (isinstance(c, ast.Call) and isinstance(c.func, ast.Name)):
                    continue
                for i in tagfns.get(c.func.id, ()):
                    if i < len(c.args) and isinstance(c.args[i], ast.Name) \
                            and c.args[i].id in params:
                        j = params.index(c.args[i].id)
                        if j not in tagfns.get(node.name, set()):
                            tagfns.setdefault(node.name, set()).add(j)
                            grew = True
        if not grew:
            break
    skip = _prose_constants(tree)
    tags = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) in skip or _STRUCT_FMT.match(node.value):
                continue
            for m in _TAG_LIT.finditer(node.value):
                tags.setdefault(m.group(1), set()).add('%s:%d' % (module_file, node.lineno))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            for i in tagfns.get(node.func.id, ()):
                if i < len(node.args) and isinstance(node.args[i], ast.Constant) \
                        and isinstance(node.args[i].value, str):
                    tags.setdefault(node.args[i].value, set()).add(
                        '%s:%d %s()' % (module_file, node.lineno, node.func.id))
    return {k: sorted(v) for k, v in tags.items()}


def type_emitters():
    """{type: (emitter module file, ...)} READ OUT OF quarry.py's own dispatch.

    ⛔ Not a table someone keeps in step by hand: `to_interchange_xml` is a chain of
    `if t == '<type>':` branches whose `import` statements name the converter that branch uses,
    and `_regress_meta_signature` names the meta lane's. Registering a new type therefore
    extends this map by itself - the same property `CONTAINER_EMITTERS` gives the ymap list.
    Module-level imports of those modules are followed too (ydd2xml and yft2xml both build on
    ydr2xml.drawable_lines, so a ydd witnesses ydr2xml topics)."""
    with open(os.path.join(QUARRY_DIR, 'quarry.py'), encoding='utf-8') as fh:
        tree = ast.parse(fh.read())
    fns = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    out = {}

    # ⛔ The driver and this module are not emitters, and following a FUNCTION-level `import
    # quarry` out of a converter's CLI helper drags the whole tool in - which put `keyderive.py`
    # and its `<dir>` help text in the topic list. The closure below therefore follows
    # MODULE-LEVEL imports only, and never these two.
    not_emitters = {'quarry.py', 'witness.py'}

    def imports_in(node, top_only=False):
        got = []
        stmts = node.body if top_only else ast.walk(node)
        for c in stmts:
            if isinstance(c, ast.Import):
                got += [a.name + '.py' for a in c.names]
            elif isinstance(c, ast.ImportFrom) and c.module and not c.level:
                got.append(c.module + '.py')
        return [m for m in got if m not in not_emitters
                and os.path.isfile(os.path.join(QUARRY_DIR, m))]

    disp = fns.get('to_interchange_xml')
    if disp is not None:
        for node in ast.walk(disp):
            if not (isinstance(node, ast.If) and isinstance(node.test, ast.Compare)
                    and isinstance(node.test.left, ast.Name) and node.test.left.id == 't'
                    and len(node.test.comparators) == 1
                    and isinstance(node.test.comparators[0], ast.Constant)):
                continue
            t = node.test.comparators[0].value
            if isinstance(t, str):
                out.setdefault(t, []).extend(imports_in(node))
    meta = fns.get('_regress_meta_signature')
    meta_mods = imports_in(meta) if meta is not None else ['meta2xml.py']
    for t in _meta_types(tree):
        out.setdefault(t, []).extend(meta_mods)
    # transitive: a converter that calls another converter's renderer emits its tags too
    for t, mods in out.items():
        seen, queue = list(dict.fromkeys(mods)), list(mods)
        while queue:
            m = queue.pop()
            with open(os.path.join(QUARRY_DIR, m), encoding='utf-8') as fh:
                sub = ast.parse(fh.read())
            for f in imports_in(sub, top_only=True):
                if f not in seen:
                    seen.append(f)
                    queue.append(f)
        out[t] = tuple(seen)
    return out


def _meta_types(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == 'REGRESS_META_TYPES' for t in node.targets):
            if isinstance(node.value, ast.Tuple):
                return [e.value for e in node.value.elts if isinstance(e, ast.Constant)]
    return ['ytyp', 'ymap', 'ymt']


# ------------------------------------------------------------------ the baked census
def census_path(project_root):
    return os.path.join(project_root, CENSUS_FILE)


def load_census(project_root):
    p = census_path(project_root)
    if not os.path.isfile(p):
        return None
    try:
        with open(p) as fh:
            c = json.load(fh)
    except Exception:
        return None
    return c if c.get('quarryWitnessVersion') == CENSUS_VERSION else None


def topics_for(census, t):
    """(topics that NEED a witness, topics that CANNOT have one) for one type.

    The first set unions both evidence bases: what the whole emitted corpus shows this type
    writing with content, and what re-converting the available binaries THROUGH THE CURRENT CODE
    shows. Neither alone is enough - the corpus is large but was written by whatever the emitters
    were on census day, and the binary pool is code-current but small."""
    d = (census or {}).get('types', {}).get(t) or {}
    need = set(d.get('content') or {}) | set(d.get('pinnable') or {})
    return need, set(d.get('emptyOnly') or {}) - need


def exemption_reason(census, t, tag):
    """The measured receipt for a topic no pin can witness, or None if it needs one."""
    d = (census or {}).get('types', {}).get(t) or {}
    if tag in (d.get('content') or {}) or tag in (d.get('pinnable') or {}):
        return None
    n = (d.get('emptyOnly') or {}).get(tag)
    if n is None:
        return None
    return ('emitted ONLY in its empty form - %s of %s emitted %s carry <%s />, 0 carry content '
            '(%s census)' % (f'{n:,}', f'{d.get("emittedFiles", 0):,}', t, tag,
                             (census or {}).get('built', '?')[:10]))


def source_leftover(census):
    """{module: {tag: receipt}} - tags the emitters can spell that the census never saw ANY
    carrier for. These are the `containerLods` shape one level up: real code, zero real files."""
    return (census or {}).get('sourceLeftover') or {}


# ------------------------------------------------------------------ building the census
#
# TWO EVIDENCE BASES, because they answer two different questions and neither answers both:
#
#   EMITTED CORPUS (`--emitted`, e.g. F:/RUDE_Filebase_v2/_resolved) - every .<type>.xml the
#     converter has already written for the whole game. This is the only thing large enough to
#     support a "zero carriers" claim, and it is what every exemption receipt quotes.
#   BINARY POOL (the fixture project's own slots, plus `--binaries`) - re-converted HERE, through
#     the CURRENT emitters. This is the only evidence that is code-current, and it is what can
#     actually be pinned: a pin has to be a binary the gate can convert, and the smallest carrier
#     in the emitted corpus is usually a file whose binary nobody kept.
#
# ⛔ A CATALOGUE IS A LOWER BOUND. Everything written here is phrased as "N of M files", never
# "always" or "never" - the register lost a day to "observed empty in all 5 references" when
# reading all 25 found four populated.
_WORKER = {}


def _scan_emitted(path):
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as fh:
            x = fh.read()
    except OSError:
        return None
    return os.path.getsize(path), os.path.basename(path), witnessed_tags(x), empty_form_tags(x)


def emitted_xmls_of(t, path, meta_root=None):
    """Every XML document converting this binary produces, through the REAL pipeline entry
    point - the same call `extract`/`meta` make, so the census measures shipped code."""
    import quarry
    if t in ('ytyp', 'ymap', 'ymt'):
        import meta2xml
        names = _WORKER.get('names')
        if names is None:
            names = meta2xml.load_names(*[os.path.join(meta_root, s)
                                          for s in quarry.precedence_slots(meta_root)])
            _WORKER['names'] = names
        xml, _kind, _w = meta2xml.convert(path, names)
        return [xml]
    with open(path, 'rb') as fh:
        blob = fh.read()
    conv = quarry.to_interchange_xml(os.path.basename(path), blob, 'none', None)
    if conv is None:
        return []
    _n, xml_bytes, sidecars = conv
    out = [xml_bytes.decode('utf-8', 'replace')]
    for rel, data in (sidecars or ()):
        if rel.lower().endswith('.xml'):
            out.append(data.decode('utf-8', 'replace'))
    return out


def _scan_binary(job):
    t, path, meta_root = job
    try:
        xmls = emitted_xmls_of(t, path, meta_root)
    except Exception as ex:
        return t, path, None, '%s: %s' % (type(ex).__name__, ex)
    tags = set()
    for x in xmls:
        tags |= witnessed_tags(x)
    return t, path, tags, None


def _binary_pool(t, project_root, extra_roots):
    import quarry
    files = []
    for slot in quarry.precedence_slots(project_root):
        d = os.path.join(project_root, slot, t)
        if os.path.isdir(d):
            files += [os.path.join(d, f) for f in os.listdir(d)
                      if f.lower().endswith('.' + t)]
    for r in extra_roots:
        d = os.path.join(r, t)
        if os.path.isdir(d):
            files += [os.path.join(d, f) for f in os.listdir(d)
                      if f.lower().endswith('.' + t)]
    return sorted(set(files))


def build_census(project_root, emitted_root=None, extra_binaries=(), types=None, workers=6,
                 log=print, prior=None):
    """Measure both evidence bases and return the census dict `quarry witness` writes.

    `prior` carries forward the types this run was not asked to re-measure, so a whole-corpus
    pass can be done one type at a time. The zero-carrier list is always recomputed against the
    MERGED set - a receipt that quotes only the types measured today would be a smaller number
    than it claims to be."""
    import datetime
    import quarry
    from multiprocessing import Pool
    types = tuple(types or (quarry.REGRESS_TYPES + quarry.REGRESS_META_TYPES))
    out = {'quarryWitnessVersion': CENSUS_VERSION,
           'built': datetime.datetime.now().isoformat(timespec='seconds'),
           'project': os.path.abspath(project_root),
           'emittedCorpus': os.path.abspath(emitted_root) if emitted_root else None,
           'extraBinaries': [os.path.abspath(p) for p in extra_binaries],
           'types': dict((prior or {}).get('types') or {})}
    for t in types:
        rec = {'emittedFiles': 0, 'content': {}, 'emptyOnly': {}, 'pinnable': {},
               'binaries': 0, 'binaryErrors': 0}
        # -- phase 1: the whole emitted corpus
        d = os.path.join(emitted_root, t) if emitted_root else None
        if d and os.path.isdir(d):
            files = sorted(os.path.join(d, f) for f in os.listdir(d)
                           if f.endswith('.%s.xml' % t))
            rec['emittedFiles'] = len(files)
            cnt, small, empt = {}, {}, {}
            # ⛔ Pool.imap_unordered, NOT ProcessPoolExecutor.map: the executor submits every
            # future up front, so a 112,000-file type queues every completed chunk in the parent
            # until it is consumed in order. That run died with no output at all.
            with Pool(workers) as pool:
                for i, r in enumerate(pool.imap_unordered(_scan_emitted, files, chunksize=64)):
                    if i and i % 20000 == 0:
                        log('    %s %s/%s' % (t, f'{i:,}', f'{len(files):,}'))
                    if r is None:
                        continue
                    size, name, tags, empties = r
                    for tag in tags:
                        cnt[tag] = cnt.get(tag, 0) + 1
                        s = small.setdefault(tag, [])
                        s.append([size, name])
                        if len(s) > 40:
                            s.sort()
                            del s[6:]
                    for tag in empties - tags:
                        empt[tag] = empt.get(tag, 0) + 1
            for s in small.values():
                s.sort()
                del s[6:]
            rec['content'] = {k: {'carriers': cnt[k], 'smallest': small[k]}
                              for k in sorted(cnt)}
            rec['emptyOnly'] = {k: empt[k] for k in sorted(empt) if k not in cnt}
        # -- phase 2: the binaries we could actually pin, through the CURRENT emitters
        pool = _binary_pool(t, project_root, extra_binaries)
        pool = sorted((os.path.getsize(p), p) for p in pool)
        pin, errs = {}, 0
        if pool:
            jobs = [(t, p, project_root) for _s, p in pool]
            with Pool(workers) as wp:
                res = list(wp.imap_unordered(_scan_binary, jobs, chunksize=8))
            by_path = {p: (tags, err) for _t, p, tags, err in res}
            for size, p in pool:                      # ascending: first hit IS the smallest
                tags, err = by_path.get(p, (None, 'missing'))
                if tags is None:
                    errs += 1
                    continue
                for tag in tags:
                    e = pin.setdefault(tag, {'carriers': 0, 'smallest': p, 'bytes': size})
                    e['carriers'] += 1
        rec['binaries'] = len(pool)
        rec['binaryErrors'] = errs
        rec['pinnable'] = {k: pin[k] for k in sorted(pin)}
        out['types'][t] = rec
        log('  %-5s emitted %s files / %s content tags / %s empty-only ; binaries %s '
            '(%s unconvertible) / %s pinnable tags'
            % (t, f'{rec["emittedFiles"]:,}', len(rec['content']), len(rec['emptyOnly']),
               f'{len(pool):,}', errs, len(rec['pinnable'])))
    # -- phase 3: tags the SOURCE can spell that NO emitted file of ANY type ever carried.
    # ⛔ Deliberately global, not per-module. Attributing a module to a type means following
    # imports, and `from meta2xml import fmt_num` makes ydr2xml a "meta" module for a float
    # formatter - an attribution accurate enough for a report but not to base a refusal on. The
    # question that matters has no attribution in it: can the emitters spell this tag, and did
    # any real file ever carry it?
    # ⛔ `pinnable` BELONGS IN THIS UNION and leaving it out was a real error: the emitted corpus
    # was written by whatever the emitters were on EXTRACTION day, so anything serialised since
    # (`block` #32c and the `occludeModels` children #32b, both today) has zero corpus carriers
    # and would be reported as "code the game never exercises" - the exact opposite of the truth.
    # The binary pool is the code-current half; a tag either half has seen is not leftover.
    seen = set()
    for rec in out['types'].values():
        seen |= set(rec['content']) | set(rec['emptyOnly']) | set(rec.get('pinnable') or {})
    nfiles = sum(v.get('emittedFiles', 0) for v in out['types'].values())
    mods = sorted({m for ms in type_emitters().values() for m in ms})
    left = {}
    for m in mods:
        src = source_topics(m)
        for tag in sorted(set(src) - seen):
            left.setdefault(m, {})[tag] = (
                '0 of %s emitted files (all types) carry <%s> in any form; emitter site %s'
                % (f'{nfiles:,}', tag, ', '.join(src[tag][:2])))
    out['sourceLeftover'] = left
    out['emitterModules'] = {t: list(ms) for t, ms in sorted(type_emitters().items())}
    return out


def plan_pins(census, t):
    """{binary path: [topics it is the smallest carrier of]} - the pin set for one type.

    SMALLEST FIRST, because a witness has to be carried forever: the ymap nine total 8,736 bytes.
    A topic whose only carriers are files with no binary in the pool comes back in `nocarrier`
    rather than being quietly dropped - refusing with a counted reason beats inventing a pin."""
    rec = (census or {}).get('types', {}).get(t) or {}
    need, _exempt = topics_for(census, t)
    pins, nocarrier = {}, []
    for tag in sorted(need):
        e = (rec.get('pinnable') or {}).get(tag)
        if e is None:
            nocarrier.append(tag)
        else:
            pins.setdefault(e['smallest'], []).append(tag)
    return pins, nocarrier
