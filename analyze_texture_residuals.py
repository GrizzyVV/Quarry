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
  B UNSUPPORTED_BY_MASTER - the sampler maps to a parameter THE MASTER THIS DRAWABLE ACTUALLY GETS
                          does not have, so the bind is a silent no-op. Fix = add the parameter to
                          that master (a material authoring gap). This is the one that renders as
                          flat saturated colour.
  C UNMAPPED_SAMPLER    - the sampler has no entry in GSamplerBinds at all, so nothing even tries.
                          Fix = decide the semantic and add a table row (a coverage decision).

⛔ THERE IS NO BUCKET D ANY MORE (removed 2026-08-03). `D UNKNOWN_MASTER_SUPPORT` was structurally
unreachable: it fired only for a parameter that was neither in `CONFIRMED_ABSENT` nor in ANY
master's set, and MEASURED over the 41 distinct sampler names in a 3,000-drawable sample,
`resolve_param` emits exactly 14 parameters and the escape set is EMPTY - 0 references, both
shipped runs printed `0`. A row that can only ever print 0 reads as a PASSED CHECK ("nothing is
unverified anywhere"), which is a gate passing on zero evidence, and it lent false confidence to
the very master table whose staleness is the defect above. B is now decided against the master the
drawable actually gets, all of which are built in readable C++, so "unverified master support" is
no longer a category. If one is ever wanted for authored `.uasset` masters it must be keyed on the
master NAME, not on the parameter name - and it must be able to fire.

⚠ WHAT THIS TOOL MODELS. Every master parameter set below is read from the `Ensure*Master()` bodies
in `RudeToolset.cpp` - i.e. what the code WILL emit. Those functions `LoadObject` an existing asset
first, so if a stale `/RUDE/Masters/*` asset with a poorer parameter list is already on disk, the
real bind set can differ. Confirming that needs a running editor and is out of this tool's reach.

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
# ✅ re-read against RudeToolset.cpp:2028-2037 on 2026-08-03 - all 8 rows identical.
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

# ⛔⛔ WHICH MASTER *THIS* DRAWABLE GETS. Cause B is "the master this drawable will be parented to
# has no such parameter", and that question is meaningless against a fixed list of masters.
#
# ⚠ WHAT WAS WRONG BEFORE (corrected 2026-08-03), because it put a fabricated number in a banked
# report. The previous version decided B from a hardcoded `CONFIRMED_ABSENT = {Detail, TintPalette,
# Dirt}` plus a UNION of six master parameter sets. Both had gone stale under the 2026-07-30
# material generator:
#   * `EnsureGeneratedMaster()` (RudeToolset.cpp:294-466) EMITS a `Detail` parameter whenever the
#     shader binds a `Detail*` sampler and a `TintPalette` parameter whenever it binds
#     `TintPalette*`. Every Detail / TintPalette residual the tool reported was a bind that now
#     LANDS - it was reporting a defect that had already been fixed.
#   * a UNION test cannot see the real failure. A decal or foliage drawable binding `SpecSampler`
#     gets M_RUDE_DecalGeo / M_RUDE_Foliage, and neither exposes `Specular` (RudeToolset.cpp:69-126
#     and 131-172 - both build exactly {Diffuse, Normal}). Those genuine silent no-ops were counted
#     as SUCCESSFUL BINDS, because some *other* master in the union had a `Specular`.
# COST, measured per REFERENCE on an identical 3,000 random real .ydr.xml (seed 20260803): the old
# rule reported **841** B references (`Detail` 774 + `TintPalette` 67); the corrected rule reports
# **676**. Only **40** references are B under both. So **801 of 841 (95.2%) were false** — binds
# that now land — and **636 genuine silent no-ops were counted as SUCCESSFUL binds**, 634 of them
# `Specular` onto DecalGeo/Foliage. HOW MEASURED: both rules evaluated on the same reference stream
# (scratchpad probe_bset.py), with the master each shader block actually selects replicated from
# RudeToolset.cpp:2054-2062 + MasterForPreset:1957-1992 + MasterForDef:1939-1955.
#
# SOURCE for every parameter set below: the `Ensure*Master()` bodies, read 2026-08-03. Nothing here
# is inferred from a `.uasset`, and nothing is inferred from a comment.
SPECIAL_MASTER_PARAMS = {
    # EnsureTerrainMaster()  RudeToolset.cpp:668-673
    'M_RUDE_Terrain':  {f'{k}{i}' for k in ('Diffuse', 'Normal') for i in range(4)},
    # EnsureDecalGeoMaster() RudeToolset.cpp:84-91  ('Visible' is a SCALAR, not a texture param, and
    # ImportYdr checks texture params only - GetAllTextureParameterInfo at :2106)
    'M_RUDE_DecalGeo': {'Diffuse', 'Normal'},
    # EnsureFoliageMaster()  RudeToolset.cpp:147-153
    'M_RUDE_Foliage':  {'Diffuse', 'Normal'},
}
# EnsureGeneratedMaster() exposes exactly the capabilities the shader's OWN samplers imply:
# Diffuse always (:341), then Detail (:363), TintPalette (:394), Normal (:404), Specular (:411).
# The flag test is MasterForDef's StartsWith ladder (:1946-1949) - first match wins, hence `break`.
# ⛔ `Specular` when `bSpec` is false is a SCALAR parameter (:427), so a Specular TEXTURE bind would
# still be unsupported; it cannot arise, because the same `Spec*` sampler that would bind it is what
# sets bSpec.
GEN_FLAGS = (('bump', 'Normal'), ('spec', 'Specular'),
             ('detail', 'Detail'), ('tintpalette', 'TintPalette'))


def master_for(preset, bucket, samplers):
    """-> (master name, set of TEXTURE parameters it exposes). Mirrors RudeToolset.cpp:2054-2062.

    Note which branches are absent: `MasterForPreset`'s detail / cutout / M_RUDE_Opaque-fallback
    arms (:1973-1991) are unreachable from the drawable path, because `bSpecialCase` (:2055-2059)
    only admits terrain / bucket-2 / decal / trees / grass / foliage / plant, and the terrain,
    decal and foliage arms consume all of those. Measured over the 10,935 shader blocks in the
    3,000 sampled drawables: GENERATED 7,737 · DecalGeo 2,344 · Terrain 698 · Foliage 156 ·
    Opaque/Cutout/Detail/Water 0. The report prints this histogram every run, so the day one of
    those arms does become reachable, it shows up as a number rather than as a stale comment.
    """
    p = preset.lower()
    terrain = p.startswith('terrain')
    special = (terrain or bucket == 2 or 'decal' in p or p.startswith('trees')
               or p.startswith('grass') or 'foliage' in p or 'plant' in p)
    if not special:                                  # MasterForDef -> EnsureGeneratedMaster
        ps = {'Diffuse'}
        for s in samplers:
            sl = s.lower()
            for pfx, param in GEN_FLAGS:
                if sl.startswith(pfx):
                    ps.add(param)
                    break
        return 'GENERATED', ps
    if terrain:
        return 'M_RUDE_Terrain', SPECIAL_MASTER_PARAMS['M_RUDE_Terrain']
    if bucket == 2 or 'decal' in p:
        return 'M_RUDE_DecalGeo', SPECIAL_MASTER_PARAMS['M_RUDE_DecalGeo']
    return 'M_RUDE_Foliage', SPECIAL_MASTER_PARAMS['M_RUDE_Foliage']


# ⛔ ANCHORED INSIDE <Shaders>, and that anchor is the whole fix. Unanchored, the first `<Item>` a
# drawable offers is the first entry of its embedded `<ShaderGroup><TextureDictionary>`, so the
# first shader block of every such drawable was labelled with a TEXTURE NAME instead of its preset.
# COST, measured on the same 3,000-drawable sample: 1,049 (35.0%) carry a non-empty embedded TxD,
# 1,047 shader blocks were labelled with a texture name, and 2,683 texture references were
# attributed to a preset that does not exist (e.g. `icons2_prop_mk_lines.ydr.xml` labelled
# `prop_base_white_full` when the preset is `radar`). That label IS the "seen on presets" column,
# i.e. the entire deliverable of cause C - it is what tells you the semantic to give an unmapped
# sampler, so a GSamplerBinds decision made from it was grounded in nothing. HOW MEASURED: the
# structure confirmed by hand in 02gate3_l.ydr.xml (`<ShaderGroup><TextureDictionary>` precedes
# `<Shaders>`), then anchored vs unanchored block labels diffed per file.
SHADERS_RE = re.compile(r'<Shaders>(.*?)</Shaders>', re.S)
SHADER_ITEM = re.compile(r'<Item>\s*<Name>([^<]*)</Name>(.*?)</Parameters>', re.S)
BUCKET_RE = re.compile(r'<RenderBucket\s+value="(\d+)"')
TEX_ITEM = re.compile(r'<Item\s+name="([^"]+)"\s+type="Texture"\s*(?:/>|>(.*?)</Item>)', re.S)
NAME_RE = re.compile(r'<Name>([^<]*)</Name>')

HEAD_CAP = 4 * 1024 * 1024


def parse_drawable(path):
    """-> [(preset, render_bucket, [(sampler, texture_name), ...]), ...], or None if not a drawable.

    Returning None rather than [] separates "this file is not a drawable at all" from "this drawable
    declares no texture parameters" (water / vfx / proxy shaders). The old code collapsed both into
    one uncounted `continue`, so a parse regression that zeroed out real drawables would have looked
    exactly like manifests being skipped.
    """
    try:
        # ⭐ HEAD READ. Only the ShaderGroup is needed; the rest of a .ydr.xml is vertex data.
        # Mean .ydr.xml is 512 KB (3,000-file sample) => 41.4 GB to read the corpus whole, which is
        # why every published residual figure so far came from a truncated alphabetical --limit
        # slice instead of a real sample. MEASURED over the 200 LARGEST .ydr.xml in the corpus:
        # `</ShaderGroup>` ends at most 99,573 bytes in (97.2 KB), and is present within 4 MB in
        # 200/200. The 4 MB cap is 42x that worst case. Head-read vs full-read parsing produced
        # identical output on 200 random sampled drawables (0 mismatches).
        buf = b''
        with open(path, 'rb') as fh:
            while len(buf) < HEAD_CAP:
                c = fh.read(262144)
                if not c:
                    break
                buf += c
                if b'</ShaderGroup>' in buf:
                    break
        txt = buf.decode('utf-8', 'replace')
    except OSError:
        return None
    m = SHADERS_RE.search(txt)
    if m is None:
        return None
    out = []
    for blk in SHADER_ITEM.finditer(m.group(1)):
        body = blk.group(2)
        bm = BUCKET_RE.search(body)
        tex = []
        for it in TEX_ITEM.finditer(body):
            nm = NAME_RE.search(it.group(2) or '')
            tex.append((it.group(1).strip(), nm.group(1).strip() if nm else ''))
        out.append((blk.group(1).strip(), int(bm.group(1)) if bm else 0, tex))
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

    if not os.path.isdir(a.textures):
        print(f'ERROR: --textures {a.textures!r} is not a directory', file=sys.stderr)
        return 2

    # every imported texture, by lowercased leaf name
    have = set()
    for dp, _, fs in os.walk(a.textures):
        for f in fs:
            if f.endswith('.uasset'):
                have.add(os.path.splitext(f)[0].lower())
    print(f'imported textures visible : {len(have):,}')
    if not have:
        print('WARNING: no .uasset textures found - EVERY reference will be counted as cause A',
              file=sys.stderr)

    skipped_ytd = 0
    if a.list:
        with open(a.list, encoding='utf-8', errors='replace') as fh:
            files = [l.strip() for l in fh if l.strip()]
    else:
        d = os.path.join(a.corpus, 'ydr')
        if not os.path.isdir(d):
            alt = os.path.join(a.corpus, '_resolved', 'ydr')
            hint = (f" (did you mean --corpus {os.path.join(a.corpus, '_resolved')} ?)"
                    if os.path.isdir(alt) else '')
            print(f'ERROR: no ydr/ under --corpus {a.corpus!r}, expected {d}{hint}', file=sys.stderr)
            return 2
        # ⛔ `*.xml` ALSO MATCHES the `__embedded.ytd.xml` texture-dictionary manifests that sit
        # beside the drawables: 29,638 of the 110,541 *.xml entries = 26.8%. MEASURED cost: the
        # shipped run printed "drawables to analyse: 2,000" when the first 2,000 entries are 1,579
        # drawables + 421 manifests, so every per-drawable rate in that report was off by a quarter
        # and every --limit sample was silently a quarter smaller than requested.
        names = os.listdir(d)
        files = [os.path.join(d, f) for f in names if f.lower().endswith('.ydr.xml')]
        skipped_ytd = sum(1 for f in names
                          if f.lower().endswith('.xml') and not f.lower().endswith('.ydr.xml'))
        print(f'non-drawable *.xml beside them (skipped): {skipped_ytd:,}')
    if a.limit:
        files = files[:a.limit]
    print(f'drawables to analyse      : {len(files):,}')
    if not files:
        print('ERROR: no drawables selected', file=sys.stderr)
        return 2

    causes = Counter()
    overlap = Counter()             # what the ORDERING hides - one reference can have >1 cause
    by_sampler = Counter()          # cause C: which sampler names are unmapped
    by_param_missing = Counter()    # cause B: parameter @ the master that lacks it
    missing_tex = Counter()         # cause A: which textures are absent
    preset_of_unmapped = defaultdict(Counter)
    master_hist = Counter()         # which master each shader block actually selects
    bound = 0
    scanned = 0
    blocks_seen = 0
    not_a_drawable = 0              # no <Shaders> block at all
    no_texture_params = 0           # a real drawable that binds no textures
    empty_tex_name = 0              # <Name> present but blank - ImportYdr drops these at :2112
    literal_null_name = 0           # 'null'/'none' as a texture NAME; ImportYdr treats it as real

    for p in files:
        bl = parse_drawable(p)
        if bl is None:
            not_a_drawable += 1
            continue
        scanned += 1
        if not any(t for _, _, t in bl):
            no_texture_params += 1
        for preset, bucket, tex in bl:
            blocks_seen += 1
            mname, mparams = master_for(preset, bucket, [s for s, _ in tex])
            master_hist[mname] += 1
            for sampler, t in tex:
                if not t:
                    empty_tex_name += 1
                    continue
                if t.lower() in ('null', 'none'):
                    literal_null_name += 1      # counted, NOT skipped: ImportYdr does not skip it
                param = resolve_param(sampler)
                missing = t.lower() not in have
                unsupported = param is not None and param not in mparams
                # ⭐ ORDER IS C -> A -> B, which is what RudeToolset.cpp does: the GSamplerBinds
                # lookup and its `++UnmappedSamplers; continue;` (:2150-2154) run BEFORE BindTex,
                # and BindTex counts MissingTextures (:2114) before UnsupportedByMaster (:2116).
                # The overlap counters below make the masking a NUMBER instead of prose.
                if param is None:
                    causes['C_UNMAPPED_SAMPLER'] += 1
                    by_sampler[sampler] += 1
                    preset_of_unmapped[sampler][preset] += 1
                    if missing:
                        overlap['C also names a texture that is not imported'] += 1
                    continue
                if missing:
                    causes['A_MISSING_TEXTURE'] += 1
                    missing_tex[t.lower()] += 1
                    if unsupported:
                        overlap['A would ALSO be unsupported once imported'] += 1
                    continue
                if unsupported:
                    causes['B_UNSUPPORTED_BY_MASTER'] += 1
                    by_param_missing[f'{param} @ {mname}'] += 1
                    continue
                bound += 1

    total = sum(causes.values())
    lines = []
    w = lines.append
    w('# Texture residuals, split by CAUSE')
    w('')
    w(f'Drawables analysed: **{scanned:,}** ({blocks_seen:,} shader blocks) · '
      f'texture references that would bind: **{bound:,}** · residuals: **{total:,}**')
    w('')
    w(f'Files skipped: **{not_a_drawable:,}** had no `<Shaders>` block (not drawables) · '
      f'**{no_texture_params:,}** are drawables that declare no texture parameter · '
      f'**{empty_tex_name:,}** texture references carry a blank `<Name>`'
      + (f' · **{literal_null_name:,}** are literally named `null`/`none` (counted, not skipped — '
         f'ImportYdr does not skip them either)' if literal_null_name else '') + '.')
    if skipped_ytd:
        w(f'Non-drawable `*.xml` in `ydr/` excluded from the file list: **{skipped_ytd:,}**.')
    w('')
    w('⚠ **Causes are tested C → A → B, the order `RudeToolset.cpp` uses** — the GSamplerBinds miss')
    w('short-circuits before `BindTex`, and `BindTex` counts a missing texture before it checks the')
    w('master. So **C masks A and B**, and **A masks B**, for the same reference. (An earlier version')
    w('of this report claimed A→B→C, i.e. the masking running the other way. It contradicted both the')
    w('code above it and the importer.) The counts are a partition, not independent totals — the')
    w('overlap table is what the partition hides.')
    w('')
    w('| cause | count | the fix |')
    w('|---|---:|---|')
    w(f'| A MISSING_TEXTURE | {causes["A_MISSING_TEXTURE"]:,} | import the txd holding it (data coverage) |')
    w(f'| B UNSUPPORTED_BY_MASTER | {causes["B_UNSUPPORTED_BY_MASTER"]:,} | add the parameter to the master THIS drawable gets (material authoring) |')
    w(f'| C UNMAPPED_SAMPLER | {causes["C_UNMAPPED_SAMPLER"]:,} | decide the semantic, add a GSamplerBinds row |')
    w('')
    w('| masked by the C→A→B ordering | references |')
    w('|---|---:|')
    for k, v in overlap.most_common():
        w(f'| {k} | {v:,} |')
    if not overlap:
        w('| (none) | 0 |')
    w('')
    w('## Which master each shader block actually selects')
    w('')
    w('| master | shader blocks | share |')
    w('|---|---:|---:|')
    for k, v in master_hist.most_common():
        w(f'| `{k}` | {v:,} | {100.0*v/max(1, blocks_seen):.1f}% |')
    w('')
    if by_param_missing:
        w("## B — binds the drawable's OWN master cannot accept (silent no-ops)")
        w('')
        w('| parameter @ master | references |')
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
    for _s in (sys.stdout, sys.stderr):
        try: _s.reconfigure(errors='replace')
        except Exception: pass
    sys.exit(main())
