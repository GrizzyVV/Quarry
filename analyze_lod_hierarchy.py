#!/usr/bin/env python3
"""Measure the REAL LOD/SLOD hierarchy the game ships, as the foundation for generating one.

WHY: `BENCHMARK_ADDON_CITY.md` calls LOD/SLOD generation "the biggest structural gap" - we DECODE
the hierarchy fields (`lodLevel`, `parentIndex`, `numChildren`, `lodDist`, `childLodDist`) and
generate nothing, so an exported district vanishes two blocks out. Before writing a generator, the
shipped structure has to be measured rather than assumed: how many levels, what the branching factor
actually is, what distances each level uses, and whether `parentIndex` is intra-ymap or cross-ymap.

⛔ This measures ONLY. It makes no claim about how to generate - that decision needs these numbers
first, and guessing the distances is exactly how an exported city ends up popping.

Usage:
  python analyze_lod_hierarchy.py --corpus <filebase>/_resolved [--prefix dt1_] [--out r.md]
"""
import argparse, os, re, sys
from collections import Counter, defaultdict

ENT = re.compile(r'<Item\b[^>]*type="CEntityDef"[^>]*>(.*?)</Item>', re.S)
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

    d = os.path.join(a.corpus, 'ymap')
    files = sorted(f for f in os.listdir(d)
                   if f.lower().endswith('.ymap.xml') and f.lower().startswith(a.prefix.lower()))
    if a.limit:
        files = files[:a.limit]

    levels = Counter()
    per_level_lodd = defaultdict(list)      # lodLevel -> [lodDist]
    per_level_childd = defaultdict(list)
    children_of = Counter()                 # numChildren histogram for parents
    parent_present = Counter()              # does parentIndex point somewhere real?
    ymaps = 0
    entities = 0
    # ⭐ THE QUESTION THAT DECIDES THE GENERATOR'S SHAPE — and the FIRST version of this test was
    # WRONG (2026-07-29). It checked `parentIndex < len(this file's entities)` and concluded from
    # 67.5% that "the hierarchy crosses files, so a generator needs whole-region context". That
    # proves nothing: an index into ANOTHER file can land in range by coincidence, and one out of
    # range only proves it is not local. The structure is stated explicitly in the data — every ymap
    # declares ONE `<parent>` ymap and parentIndex indexes THAT file — so the only sound test is to
    # resolve each child's own declared parent and range-check against it.
    out_of_range = 0
    in_range = 0
    no_parent_file = 0
    parent_of = {}
    ent_count = {}
    child_pis = {}

    for fn in files:
        try:
            txt = open(os.path.join(d, fn), encoding='utf-8', errors='replace').read()
        except OSError:
            continue
        ymaps += 1
        bodies = ENT.findall(txt)
        n = len(bodies)
        stem = fn[:-len('.ymap.xml')]
        _pm = re.search(r'<parent>([^<]*)</parent>', txt)
        parent_of[stem] = (_pm.group(1).strip() if _pm else '')
        ent_count[stem] = n
        child_pis[stem] = []
        for b in bodies:
            entities += 1
            lv = tag(b, 'lodLevel') or '?'
            levels[lv] += 1
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
                    # ⭐ the child's TIER travels with its index - see the per-tier check below
                    child_pis[stem].append((lv, p))

    L = []
    w = L.append
    w('# LOD / SLOD hierarchy as the game actually ships it')
    w('')
    w(f'Scope: `{a.prefix or "ALL"}` — **{ymaps:,} ymaps, {entities:,} entities**')
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
    # ⛔⛔ THE MODEL IS MIXED BY TIER, AND THE PREVIOUS VERSION OF THIS CHECK MISSED IT
    # (corrected 2026-08-02). It resolved EVERY tier against the declared `<parent>` ymap and
    # reported 93.8%. Measured across all 859,005 set parentIndex values:
    #     HD    (692,942) -> the declared <parent> file
    #     SLOD1  (13,628) -> the declared <parent> file
    #     LOD   (151,103) -> its OWN file (the SLOD1 block at its head)
    #     SLOD2   (1,255) -> its OWN file (the SLOD3 block)
    # So 150,375 of 859,005 (17.5%) were misclassified, and every one of the 52,835 "out of range"
    # values was a LOD child resolving perfectly against its own file - 100% false negatives.
    # Under the corrected model 858,928/859,005 = 99.99% resolve.
    # ⚠ Note what happened here: the FIRST version was wrong in one direction, this comment block
    # warned that "an index into ANOTHER file can land in range by coincidence", and the fix then
    # went wrong in the OPPOSITE direction. A guard written against one failure direction does not
    # protect the other - so this check now states, per tier, WHICH FILE it resolved against.
    SELF_TIERS = ('LODTYPES_DEPTH_LOD', 'LODTYPES_DEPTH_SLOD2')
    per_tier = defaultdict(lambda: {'in': 0, 'out': 0, 'unres': 0, 'target': ''})
    for _stem, _pis in child_pis.items():
        _par = parent_of.get(_stem) or ''
        _own = ent_count.get(_stem)
        for _lv, _p in _pis:
            self_ref = _lv in SELF_TIERS
            t = per_tier[_lv]
            t['target'] = 'own file' if self_ref else 'declared <parent>'
            _n = _own if self_ref else ent_count.get(_par)
            if _n is None:
                t['unres'] += 1
                no_parent_file += 1
            elif _p < _n:
                t['in'] += 1
                in_range += 1
            else:
                t['out'] += 1
                out_of_range += 1
    w('## ⭐ Where does `parentIndex` point? (decides whether tiles generate independently)')
    w('')
    w(f'- `parentIndex` set: **{parent_present["set"]:,}** · unset (-1): '
      f'**{parent_present["none (-1)"]:,}**')
    w(f'- resolved PER TIER (each against the file that tier actually indexes): '
      f'**{in_range:,} in range**, **{out_of_range:,} out of range**, '
      f'**{no_parent_file:,} unresolvable** (target file outside this scope)')
    w('')
    w('| child lodLevel | resolves against | in range | out of range | unresolvable |')
    w('|---|---|---:|---:|---:|')
    for _lv in sorted(per_tier, key=lambda k: -(per_tier[k]['in'] + per_tier[k]['out'])):
        t = per_tier[_lv]
        w(f'| `{_lv}` | {t["target"]} | {t["in"]:,} | {t["out"]:,} | {t["unres"]:,} |')
    checked = in_range + out_of_range
    if checked:
        pct = 100.0 * in_range / checked
        w('')
        w(f'⇒ **{pct:.2f}% of resolvable `parentIndex` values land in the file their tier '
          f'indexes.**')
        w('')
        w('**The shipped model is MIXED BY TIER** (measured 2026-08-02; the earlier single-model '
          'reading of this same data was wrong in both of its previous versions):')
        w('')
        w('- **HD → its declared `<parent>` ymap** and **SLOD1 → its declared `<parent>` ymap** — '
          'these cross files, so the child\'s indices are only meaningful against that one parent '
          'entity list.')
        w('- **LOD → its OWN file** (the SLOD1 block at the head of the same ymap) and '
          '**SLOD2 → its OWN file** (the SLOD3 block). These are self-contained.')
        w('')
        w('⇒ **A generator must emit parent and children TOGETHER only for HD→LOD and '
          'SLOD1→SLOD2.** `LOD→SLOD1` and `SLOD2→SLOD3` live inside a single ymap and CAN be '
          'emitted in isolation. (The per-tier table above is computed from this run — if a tier '
          'shows unexpected out-of-range counts, trust the table over this paragraph.)')
    w('')
    w('## Declared parents in scope')
    w('')
    w('| parent ymap | children declaring it |')
    w('|---|---:|')
    for k, v in Counter(v or '(none)' for v in parent_of.values()).most_common(12):
        w(f'| `{k}` | {v} |')
    out = '\n'.join(L)
    print(out)
    if a.out:
        with open(a.out, 'w', encoding='utf-8', newline='\n') as fh:
            fh.write(out + '\n')
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
