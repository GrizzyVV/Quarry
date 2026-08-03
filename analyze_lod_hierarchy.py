#!/usr/bin/env python3
"""Measure the REAL LOD/SLOD hierarchy the game ships, as the foundation for generating one.

WHY: `BENCHMARK_ADDON_CITY.md` calls LOD/SLOD generation "the biggest structural gap" - we DECODE
the hierarchy fields (`lodLevel`, `parentIndex`, `numChildren`, `lodDist`, `childLodDist`) and
generate nothing, so an exported district vanishes two blocks out. Before writing a generator, the
shipped structure has to be measured rather than assumed: how many levels, what the branching factor
actually is, what distances each level uses, and whether `parentIndex` is intra-ymap or cross-ymap.

⛔ This measures ONLY. It makes no claim about how to generate - that decision needs these numbers
first, and guessing the distances is exactly how an exported city ends up popping.

⛔ AND IT MUST NOT ASSERT WHAT IT DID NOT CHECK. Every conclusion this script prints is built from
`verdict`, which is built from the per-tier table, which is built from the run. A tier with no
resolved link in scope gets an explicit "no claim made" line, not a sentence of confident prose.

Usage:
  python analyze_lod_hierarchy.py --corpus <filebase>/_resolved [--prefix dt1_] [--out r.md]
"""
import argparse, os, re, sys
from collections import Counter, defaultdict

# ⛔ CMloInstanceDef IS AN ENTITY. The previous regex matched `type="CEntityDef"` only, so every MLO
# instance was invisible - to the census, to the lodLevel histogram, to the parentIndex totals, AND
# to the per-file entity count each index is checked against. MLO instances are the INTERIORS, so a
# generator specified from that report would emit no LOD linkage for any interior and the popping
# would get blamed on distances. COST, measured over the whole 11,081-ymap corpus: 1,105 entities
# dropped, 547 of them HD children carrying a real parentIndex (shipped 1,688,993 entities /
# 859,005 set parentIndex / HD 692,942; corrected 1,690,098 / 859,552 / 693,489).
# ⚠ `parentIndex` indexes the FULL entities array, so a file that mixes the two types would shift
# every index. HOW MEASURED: this regex's (type, lodLevel, parentIndex) sequence was diffed against
# `xml.etree.ElementTree` on 300 random ymaps / 50,751 entities - 0 mismatches, so index positions
# are exact. Nothing in the code enforces that; `skipped_item_types` below is the tripwire.
ENTITIES_BLOCK = re.compile(r'<entities>(.*?)</entities>', re.S)
ENT = re.compile(r'<Item\s+type="(CEntityDef|CMloInstanceDef)"[^>]*>(.*?)</Item>', re.S)
ANY_ITEM_TYPE = re.compile(r'<Item\s+type="([A-Za-z]+)"')

# ⭐ THE LADDER IS FIVE DEEP, AND THE FIFTH RUNG WAS HIDING BEHIND A HASH (decoded 2026-08-03).
# 77 entities corpus-wide carry the un-hashed lodLevel `hash_6F5D45B3`, and
# joaat("LODTYPES_DEPTH_SLOD4") == 0x6F5D45B3 exactly - case-sensitive, in the same uppercase form
# every other tier name uses. WHAT IT COST while undecoded: all 77 SLOD3 links looked like they
# resolved against NEITHER candidate target, so the report printed SLOD3 as "undetermined" and the
# headline as 99.99%. They in fact resolve 77/77 against their OWN file, onto the SLOD4 block -
# i.e. SLOD3 is self-contained exactly like LOD and SLOD2, which is a rule a generator needs.
# HOW MEASURED: the 77 links resolved at both targets (own file -> `hash_6F5D45B3` ×77, declared
# `<parent>` -> no such file ×77), and there are exactly 77 `hash_6F5D45B3` entities corpus-wide.
LOD_LEVEL_ALIAS = {'hash_6F5D45B3': 'LODTYPES_DEPTH_SLOD4'}

# The tier ladder a child's parent must be on. This is what makes the check a TEST rather than a
# restatement of an assumption - see the block above `score()`. A tier absent from this map scores
# CHILD_TIER_HAS_NO_PARENT_TIER, which is NOT tier-correct: the top of the ladder must never be
# able to launder an unexplained link into the headline.
PARENT_TIER = {
    'LODTYPES_DEPTH_HD':    'LODTYPES_DEPTH_LOD',
    'LODTYPES_DEPTH_LOD':   'LODTYPES_DEPTH_SLOD1',
    'LODTYPES_DEPTH_SLOD1': 'LODTYPES_DEPTH_SLOD2',
    'LODTYPES_DEPTH_SLOD2': 'LODTYPES_DEPTH_SLOD3',
    'LODTYPES_DEPTH_SLOD3': 'LODTYPES_DEPTH_SLOD4',
}


def tag(body, name, attr=None):
    if attr:
        m = re.search(r'<%s[^>]*\b%s="([^"]*)"' % (name, attr), body)
        return m.group(1) if m else None
    m = re.search(r'<%s>([^<]*)</%s>' % (name, name), body)
    return m.group(1).strip() if m else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--corpus', required=True)
    ap.add_argument('--prefix', default='')
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--out')
    a = ap.parse_args()

    # A wrong --corpus is the single most likely way to run this tool wrong (corpus root vs
    # `_resolved`), and it used to die with `FileNotFoundError [WinError 3]` on the listdir - which
    # reads as "the corpus is broken" rather than "wrong path".
    d = os.path.join(a.corpus, 'ymap')
    if not os.path.isdir(d):
        alt = os.path.join(a.corpus, '_resolved', 'ymap')
        hint = (f"\n  (did you mean --corpus {os.path.join(a.corpus, '_resolved')} ?)"
                if os.path.isdir(alt) else '')
        print(f'ERROR: no ymap/ directory under --corpus {a.corpus!r}\n'
              f'  expected: {d}{hint}', file=sys.stderr)
        return 2

    files = sorted(f for f in os.listdir(d)
                   if f.lower().endswith('.ymap.xml') and f.lower().startswith(a.prefix.lower()))
    if not files:
        # An empty file list used to produce a confident-looking "0 ymaps, 0 entities" report.
        print(f'ERROR: no *.ymap.xml under {d} matching prefix {a.prefix!r}', file=sys.stderr)
        return 2
    if a.limit:
        files = files[:a.limit]

    levels = Counter()
    per_level_lodd = defaultdict(list)      # lodLevel -> [lodDist]
    per_level_childd = defaultdict(list)
    children_of = Counter()                 # numChildren histogram for parents
    parent_present = Counter()              # does parentIndex point somewhere real?
    skipped_item_types = Counter()          # an entity class this parser does NOT model
    aliased_levels = Counter()              # raw hashed lodLevel -> the name it was decoded to
    unreadable = 0
    ymaps = 0
    entities = 0
    parent_of = {}
    ent_levels = {}                         # stem -> [lodLevel per entity index]
    child_pis = {}

    for fn in files:
        try:
            txt = open(os.path.join(d, fn), encoding='utf-8', errors='replace').read()
        except OSError:
            unreadable += 1                 # a dropped file is counted, never silent
            continue
        ymaps += 1
        stem = fn[:-len('.ymap.xml')]
        _pm = re.search(r'<parent>([^<]*)</parent>', txt)
        parent_of[stem] = (_pm.group(1).strip() if _pm else '')
        _eb = ENTITIES_BLOCK.search(txt)
        block = _eb.group(1) if _eb else ''
        for t in ANY_ITEM_TYPE.findall(block):
            # CExtension* items are nested INSIDE an entity, not entities themselves. Anything else
            # is an entity class we do not parse - and it would silently shift every parentIndex in
            # the file, so it is reported in the header rather than dropped.
            if t not in ('CEntityDef', 'CMloInstanceDef') and not t.startswith('CExtension'):
                skipped_item_types[t] += 1
        ent_levels[stem] = []
        child_pis[stem] = []
        for _t, b in ENT.findall(block):
            entities += 1
            lv = tag(b, 'lodLevel') or '?'
            if lv in LOD_LEVEL_ALIAS:
                aliased_levels[f'{lv} → {LOD_LEVEL_ALIAS[lv]}'] += 1
                lv = LOD_LEVEL_ALIAS[lv]
            levels[lv] += 1
            # ⭐ the TIER at every index, not just how many indices exist - this is what turns the
            # resolution check below from a range test into a real test.
            ent_levels[stem].append(lv)
            ld, cd = tag(b, 'lodDist', 'value'), tag(b, 'childLodDist', 'value')
            if ld:
                try: per_level_lodd[lv].append(float(ld))
                except ValueError: pass
            if cd:
                try: per_level_childd[lv].append(float(cd))
                except ValueError: pass
            nc = tag(b, 'numChildren', 'value')
            if nc and nc.isdigit() and int(nc) > 0:
                children_of[int(nc)] += 1
            pi = tag(b, 'parentIndex', 'value')
            if pi is not None:
                try: p = int(pi)
                except ValueError: p = -1
                if p < 0:
                    parent_present['none (-1)'] += 1
                else:
                    parent_present['set'] += 1
                    child_pis[stem].append((lv, p))   # the child's TIER travels with its index

    L = []
    w = L.append
    w('# LOD / SLOD hierarchy as the game actually ships it')
    w('')
    w(f'Scope: `{a.prefix or "ALL"}` — **{ymaps:,} ymaps, {entities:,} entities** '
      f'(`CEntityDef` + `CMloInstanceDef`)')
    if unreadable:
        w(f'- ⚠ **{unreadable:,} ymap(s) could not be read and are excluded from every count below.**')
    if skipped_item_types:
        w('- ⚠ **entity item types this parser does NOT model** (each one shifts every later '
          '`parentIndex` in its file): '
          + ', '.join(f'`{k}`×{v:,}' for k, v in skipped_item_types.most_common()))
    if aliased_levels:
        w('- hashed `lodLevel` names decoded by joaat and counted under the decoded name: '
          + ', '.join(f'`{k}` ×{v:,}' for k, v in aliased_levels.most_common()))
    w('')
    w('## Levels present')
    w('')
    w('| lodLevel | entities | share | median lodDist | median childLodDist |')
    w('|---|---:|---:|---:|---:|')
    for lv, c in levels.most_common():
        def med(xs):
            xs = sorted(xs)
            return f'{xs[len(xs)//2]:.0f}' if xs else '—'
        w(f'| `{lv}` | {c:,} | {100.0*c/max(1,entities):.1f}% | {med(per_level_lodd[lv])} | '
          f'{med(per_level_childd[lv])} |')
    w('')
    w('## Branching (numChildren, parents only)')
    w('')
    if children_of:
        tot = sum(children_of.values())
        wsum = sum(k*v for k, v in children_of.items())
        w(f'- parents: **{tot:,}**, total child links: **{wsum:,}**, '
          f'mean fan-out **{wsum/max(1,tot):.1f}**')
        w('')
        w('| children | parents |')
        w('|---:|---:|')
        for k in sorted(children_of)[:12]:
            w(f'| {k} | {children_of[k]:,} |')
    else:
        w('- no parents found')
    w('')

    # ⛔⛔ THE QUESTION THAT DECIDES THE GENERATOR'S SHAPE, AND IT HAS NOW BEEN ANSWERED WRONGLY
    # TWICE - in OPPOSITE directions - because the check could not tell a right model from a wrong
    # one. v1 (2026-07-29) range-checked every parentIndex against its OWN file, got 67.5% and
    # concluded the hierarchy crosses files. v2 (2026-08-02) range-checked every tier against the
    # declared `<parent>` ymap, got 93.8%, and banked that number in a report that drove a design
    # rule. Both were RANGE checks (`p < len(entities)`), and a range check AGREES WITH WHATEVER
    # ROUTING IS HARDCODED, by construction: an index into the wrong file lands in range by
    # coincidence all the time.
    # HOW MEASURED (500 random ymaps, seed 1234): route HD at its OWN file and 17,942 of 31,455
    # links land IN RANGE - and ZERO of them are tier-correct (13,781 land on another HD, 4,161 on
    # ORPHANHD). Route SLOD1 at its own file: 586 in range, 0 tier-correct. A range check would
    # have scored those 57% and 92% "resolved" for a demonstrably wrong model.
    # THE FIX: score BOTH candidate targets by whether the entity the index lands on is EXACTLY ONE
    # TIER ABOVE the child, and let the run pick the winner. The routing is now measured per tier
    # and printed per tier; it is no longer a constant this file asserts.
    def score(lv, p, tstem):
        lst = ent_levels.get(tstem)
        if lst is None:
            return 'NO_FILE'                        # target ymap is outside this scope
        if p >= len(lst):
            return 'OUT_OF_RANGE'
        want = PARENT_TIER.get(lv)
        if want is None:
            return 'CHILD_TIER_HAS_NO_PARENT_TIER'
        return 'TIER_OK' if lst[p] == want else 'WRONG_TIER:' + lst[p]

    per_tier = defaultdict(lambda: defaultdict(Counter))
    for _stem, _pis in child_pis.items():
        _par = parent_of.get(_stem) or ''
        for _lv, _p in _pis:
            per_tier[_lv]['own'][score(_lv, _p, _stem)] += 1
            per_tier[_lv]['parent'][score(_lv, _p, _par)] += 1

    w('## ⭐ Where does `parentIndex` point? (decides whether tiles generate independently)')
    w('')
    w(f'- `parentIndex` set: **{parent_present["set"]:,}** · unset (-1): '
      f'**{parent_present["none (-1)"]:,}**')
    w('')
    w('Each tier is resolved against BOTH candidate targets and scored on whether the entity it '
      'lands on is **exactly one tier above the child**. A pure range check passes on coincidence, '
      'so it cannot tell the two models apart — and it agreed with the previous two routings, both '
      'of which were wrong.')
    w('')
    w('| child lodLevel | links | own file: tier-correct | declared `<parent>`: tier-correct | '
      'measured target |')
    w('|---|---:|---:|---:|---|')
    verdict = {}
    tier_ok_total = 0
    total_links = 0
    for _lv in sorted(per_tier, key=lambda k: -sum(per_tier[k]['own'].values())):
        n = sum(per_tier[_lv]['own'].values())
        o = per_tier[_lv]['own']['TIER_OK']
        p = per_tier[_lv]['parent']['TIER_OK']
        if max(o, p) == 0:
            tgt = '**undetermined** — no link resolved either way'
        elif o >= p:
            tgt = f'own file ({100.0*o/n:.2f}% of {n:,})'
            verdict[_lv] = 'own file'
        else:
            tgt = f'declared `<parent>` ({100.0*p/n:.2f}% of {n:,})'
            verdict[_lv] = 'declared <parent>'
        tier_ok_total += max(o, p)
        total_links += n
        w(f'| `{_lv}` | {n:,} | {o:,} | {p:,} | {tgt} |')
    w('')
    if total_links:
        # ⛔ THE DENOMINATOR IS EVERY SET parentIndex IN SCOPE, not just the ones that resolved.
        # It used to be `in_range + out_of_range`, which DROPPED the unresolvable links entirely -
        # so the whole-corpus headline printed 100.00% where the honest figure is 99.99%, and a
        # narrow scope could print 100.00% off two links. Unresolved links must dilute the number,
        # not disappear from it.
        w(f'⇒ **{100.0*tier_ok_total/total_links:.2f}% of the {total_links:,} set `parentIndex` '
          f'values in scope resolve to an entity exactly one tier above the child**, each against '
          f'the target measured for its own tier. Anything not tier-correct — out of range, wrong '
          f'tier, or a target file outside this scope — counts against this figure.')
        w('')
    # The conclusion is WRITTEN FROM `verdict`, so it cannot describe a run that did not happen.
    # It used to be unconditional prose asserting a complete four-tier model: `--prefix dt1_02`
    # printed SLOD1 as 0 in range / 0 out of range / 2 unresolvable and then stated
    # "SLOD1 → its declared <parent> ymap" anyway, and described SLOD2 too on zero links. A scoped
    # run is exactly how someone sanity-checks one district before generating LODs for it.
    # MEASURED on that same `--prefix dt1_02`: the headline goes 100.00% (of 23 hand-picked links)
    # -> 92.31% (of all 26), and SLOD1 now reads "undetermined - no claim made".
    cross = sorted(k for k, v in verdict.items() if v == 'declared <parent>')
    self_ = sorted(k for k, v in verdict.items() if v == 'own file')
    silent = sorted(k for k in per_tier if k not in verdict)
    if cross:
        w('- **Cross-file** (the index is only meaningful against the declared `<parent>` ymap): '
          + ', '.join(f'`{k}`' for k in cross))
    if self_:
        w('- **Self-contained** (the index is into this same ymap): '
          + ', '.join(f'`{k}`' for k in self_))
    if silent:
        w('- ⚠ **No evidence in this scope, so NO claim is made for:** '
          + ', '.join(f'`{k}`' for k in silent)
          + ' — widen `--prefix` before concluding anything about these tiers.')
    if cross:
        w('')
        w('⇒ A generator must emit parent and children TOGETHER for '
          + ', '.join(f'`{k}`→its children' for k in cross)
          + '. The self-contained tiers above live inside a single ymap and CAN be emitted in '
            'isolation.')
    w('')
    w('## Declared parents in scope')
    w('')
    w('| parent ymap | children declaring it |')
    w('|---|---:|')
    for k, v in Counter(v or '(none)' for v in parent_of.values()).most_common(12):
        w(f'| `{k}` | {v:,} |')
    out = '\n'.join(L)
    # Write the durable artifact BEFORE the console print - the same law analyze_texture_residuals
    # learned the hard way when a cp1252 stdout killed a finished run before it wrote its file.
    if a.out:
        with open(a.out, 'w', encoding='utf-8', newline='\n') as fh:
            fh.write(out + '\n')
    print(out)
    if a.out:
        print(f'\nwritten -> {a.out}')
    return 0


if __name__ == '__main__':
    # A default Windows console is cp1252 and cannot encode the report glyphs, so a run that did all
    # its work correctly dies on the FINAL PRINT. quarry.py already learned this; every reporting
    # script needs it. Degrade characters, never the run.
    for _s in (sys.stdout, sys.stderr):
        try: _s.reconfigure(errors='replace')
        except Exception: pass
    sys.exit(main())
