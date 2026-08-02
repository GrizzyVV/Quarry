#!/usr/bin/env python3
"""Split the ImportYdr texture residuals by CAUSE, offline.

WHY THIS IS A SCRIPT AND NOT A COUNTER: ImportYdr reports three residual totals
(unsupportedByMaster / missingTextures / unmappedSamplers). Totals say a defect exists but not
WHICH texture, WHICH sampler, or WHICH of three unrelated fixes applies - and "split residuals by
CAUSE" is the standing rule, because a single blended number invites one wrong fix for three
problems. Every input is already on disk (corpus XML + the imported texture tree), so this needs no
editor and no rebuild.

Causes, and why each is a DIFFERENT fix:
  A MISSING_TEXTURE     - the drawable names a texture that was never imported.
                          Fix = import the txd that holds it (a data-coverage gap).
  B UNSUPPORTED_BY_MASTER - the sampler maps to a master parameter that master does not have, so the
                          bind is a silent no-op. Fix = add the parameter to the master (a material
                          authoring gap). This is the one that renders as flat saturated colour.
  C UNMAPPED_SAMPLER    - the sampler has no entry in GSamplerBinds at all, so nothing even tries.
                          Fix = decide the semantic and add a table row (a coverage decision).

Usage:
  python analyze_texture_residuals.py --corpus <filebase>/_resolved
                                      --textures <UE project>/Content/RUDE/Textures
                                      [--list <file of ydr.xml paths>] [--limit N]
                                      [--out report.md]
"""
import argparse, os, re, sys
from collections import Counter, defaultdict

# Mirrors GSamplerBinds in RudeToolset.cpp. Kept here deliberately rather than parsed: if the two
# drift, the drift IS a finding, and a report that silently re-derives the table can never show it.
SAMPLER_BINDS = {
    'diffusesampler':     'Diffuse',
    'bumpsampler':        'Normal',
    'specsampler':        'Specular',
    'texturesamp':        'Diffuse',
    'distancemapsampler': 'Diffuse',
    'detailsampler':      'Detail',
    'tintpalettesampler': 'TintPalette',
    'dirtsampler':        'Dirt',
}
# Prefix rules (terrain's 4 blend layers are indexed, so matched by prefix not table entry).
PREFIX_BINDS = [('texturesampler_layer', 'Diffuse'), ('bumpsampler_layer', 'Normal')]

# What each master actually EXPOSES. ⛔ This is the crux of cause B: a bind to a parameter the
# master lacks is accepted silently by UE and does nothing.
#
# ⚠ PROVENANCE, because getting this wrong already cost an hour (2026-07-29). The first version of
# this table was written from `/Game/RUDE/Materials/MM_A_N*` - assets that are NOT the masters at
# all, just stale leftovers in local Content. The real masters are PLUGIN content
# (`/RUDE/Masters/M_RUDE_*`) plus the code-built `Ensure*Master()` functions.
#
# The entries below marked SOURCE are read from the `Ensure*Master()` bodies in RudeToolset.cpp -
# ground truth, because that code creates the parameters. The entries marked UNVERIFIED are authored
# `.uasset` masters whose parameter list cannot be read from source; they must be queried from a
# running editor over MCP (MaterialTools.get_expressions) before any claim rests on them.
MASTER_PARAMS = {
    # SOURCE: EnsureCutoutMaster()
    'M_RUDE_Cutout':  {'Diffuse', 'Normal', 'Specular', 'OpacityMask'},
    # SOURCE: EnsureDecalGeoMaster()
    'M_RUDE_DecalGeo': {'Diffuse', 'Normal', 'Visible'},
    # SOURCE: EnsureFoliageMaster()
    'M_RUDE_Foliage': {'Diffuse', 'Normal'},
    # ✅ VERIFIED 2026-07-29 over MCP (MaterialTools.get_expressions + ObjectTools.get_properties
    # against the running editor): exactly these four parameters exist, and NO 'Detail'. This is what
    # grounds cause B - previously it rested only on a source comment written by an agent.
    'M_RUDE_Opaque':  {'Diffuse', 'Normal', 'Specular', 'Roughness'},
    'M_RUDE_Terrain': {f'{k}{i}' for k in ('Diffuse', 'Normal') for i in range(4)},
    'M_RUDE_Water':   {'Diffuse', 'Normal'},
}

# Parameters CONFIRMED absent from every master, so a bind to them is provably inert. Kept separate
# from MASTER_PARAMS so cause B never rests on the UNVERIFIED rows above: a residual is only reported
# as B when the parameter is in this list.
CONFIRMED_ABSENT = {'Detail', 'TintPalette', 'Dirt'}

TEX_RE = re.compile(r'<Item>\s*<Name>([^<]*)</Name>.*?type="Texture".*?</Item>', re.S)
PARAM_RE = re.compile(
    r'<Item\b[^>]*type="Texture"[^>]*>(.*?)</Item>', re.S)
NAME_RE = re.compile(r'<Name>([^<]*)</Name>')


def parse_drawable(path):
    """-> [(shader_preset, sampler, texture_name), ...].

    Parsed PER SHADER BLOCK, not globally: the preset is a `<Name>` inside each shader `<Item>`
    (e.g. normal_spec, spec, terrain_cb_w_4lyr), and knowing which preset an unmapped sampler came
    from is the whole point - it is what tells you the semantic to give it.
    """
    try:
        with open(path, encoding='utf-8', errors='replace') as fh:
            txt = fh.read()
    except OSError:
        return []
    out = []
    for blk in re.finditer(
            r'<Item>\s*<Name>([^<]+)</Name>(.*?)</Parameters>', txt, re.S):
        preset = blk.group(1).strip()
        for it in re.finditer(
                r'<Item\s+name="([^"]+)"\s+type="Texture"\s*(?:/>|>(.*?)</Item>)',
                blk.group(2), re.S):
            sampler = it.group(1).strip()
            inner = it.group(2) or ''
            nm = NAME_RE.search(inner)
            out.append((preset, sampler, nm.group(1).strip() if nm else ''))
    return out


def resolve_param(sampler):
    s = sampler.lower()
    if s in SAMPLER_BINDS:
        return SAMPLER_BINDS[s]
    for pfx, base in PREFIX_BINDS:
        if s.startswith(pfx):
            idx = s[len(pfx):]
            return f'{base}{idx}' if idx.isdigit() else base
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--corpus', required=True)
    ap.add_argument('--textures', required=True)
    ap.add_argument('--list')
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--out')
    a = ap.parse_args()

    # every imported texture, by lowercased leaf name
    have = set()
    for dp, _, fs in os.walk(a.textures):
        for f in fs:
            if f.endswith('.uasset'):
                have.add(os.path.splitext(f)[0].lower())
    print(f'imported textures visible : {len(have):,}')

    if a.list:
        with open(a.list, encoding='utf-8', errors='replace') as fh:
            files = [l.strip() for l in fh if l.strip()]
    else:
        d = os.path.join(a.corpus, 'ydr')
        files = [os.path.join(d, f) for f in os.listdir(d) if f.lower().endswith('.xml')]
    if a.limit:
        files = files[:a.limit]
    print(f'drawables to analyse      : {len(files):,}')

    causes = Counter()
    by_sampler = Counter()          # cause C: which sampler names are unmapped
    by_param_missing = Counter()    # cause B: which params the masters lack
    missing_tex = Counter()         # cause A: which textures are absent
    preset_of_unmapped = defaultdict(Counter)
    bound = 0
    scanned = 0

    for p in files:
        triples = parse_drawable(p)
        if not triples:
            continue
        scanned += 1
        for preset, sampler, tex in triples:
            if not tex or tex.lower() in ('null', 'none'):
                continue
            param = resolve_param(sampler)
            if param is None:
                causes['C_UNMAPPED_SAMPLER'] += 1
                by_sampler[sampler] += 1
                preset_of_unmapped[sampler][preset] += 1
                continue
            if tex.lower() not in have:
                causes['A_MISSING_TEXTURE'] += 1
                missing_tex[tex.lower()] += 1
                continue
            # Would ANY master accept this parameter? If no master exposes it, the bind is inert
            # no matter which master this drawable selects.
            # Only CONFIRMED_ABSENT counts as B. Inferring "no master has it" from a table with
            # UNVERIFIED rows would let a wrong assumption manufacture a defect - which is how this
            # analysis got its master list wrong the first time.
            if param in CONFIRMED_ABSENT:
                causes['B_UNSUPPORTED_BY_MASTER'] += 1
                by_param_missing[param] += 1
                continue
            if not any(param in ps for ps in MASTER_PARAMS.values()):
                causes['D_UNKNOWN_MASTER_SUPPORT'] += 1
                by_param_missing[param + ' (unverified)'] += 1
                continue
            bound += 1

    total = sum(causes.values())
    lines = []
    w = lines.append
    w('# Texture residuals, split by CAUSE')
    w('')
    w(f'Drawables analysed: **{scanned:,}** · texture references that would bind: **{bound:,}** ·')
    w(f'residuals: **{total:,}**')
    w('')
    w('⚠ **Causes are tested in order A→B→C, so A MASKS B for the same reference:** a texture that')
    w('is both absent AND bound to a parameter no master exposes is counted only as A. Expect some of')
    w('A to reappear as B once the missing textures are imported. The counts are a partition of the')
    w('residuals, not independent totals.')
    w('')
    w('| cause | count | the fix |')
    w('|---|---:|---|')
    w(f'| A MISSING_TEXTURE | {causes["A_MISSING_TEXTURE"]:,} | import the txd holding it (data coverage) |')
    w(f'| B UNSUPPORTED_BY_MASTER | {causes["B_UNSUPPORTED_BY_MASTER"]:,} | add the parameter to the master (material authoring) |')
    w(f'| C UNMAPPED_SAMPLER | {causes["C_UNMAPPED_SAMPLER"]:,} | decide the semantic, add a GSamplerBinds row |')
    w(f'| D UNKNOWN_MASTER_SUPPORT | {causes["D_UNKNOWN_MASTER_SUPPORT"]:,} | query the master over MCP - support is UNVERIFIED, not known-absent |')
    w('')
    if by_param_missing:
        w('## B — parameters NO master exposes (silent no-op binds)')
        w('')
        w('| parameter | references |')
        w('|---|---:|')
        for k, v in by_param_missing.most_common():
            w(f'| `{k}` | {v:,} |')
        w('')
    if by_sampler:
        w('## C — sampler names with no table entry')
        w('')
        w('| sampler | references | seen on presets |')
        w('|---|---:|---|')
        for k, v in by_sampler.most_common(40):
            tops = ', '.join(f'{p or "?"}({n})' for p, n in preset_of_unmapped[k].most_common(3))
            w(f'| `{k}` | {v:,} | {tops} |')
        w('')
    if missing_tex:
        w('## A — most-referenced absent textures')
        w('')
        w('| texture | references |')
        w('|---|---:|')
        for k, v in missing_tex.most_common(40):
            w(f'| `{k}` | {v:,} |')
        w('')
    out = '\n'.join(lines)
    # ⛔ WRITE THE FILE BEFORE PRINTING (2026-08-02). It was the other way round, and the console
    # print raised UnicodeEncodeError on the first non-ASCII glyph under a cp1252 stdout — so
    # `--out` NEVER produced a file and the run exited 1 after doing all the work. Hours of disk
    # reading, then nothing to show for it. The durable artifact is written first; the console is
    # best-effort and can never cost the report.
    if a.out:
        with open(a.out, 'w', encoding='utf-8', newline='\n') as fh:
            fh.write(out + '\n')
    print()
    try:
        print(out[:4000])
    except UnicodeEncodeError:
        print(out[:4000].encode('ascii', 'replace').decode('ascii'))
    if a.out:
        print(f'\nwritten -> {a.out}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
