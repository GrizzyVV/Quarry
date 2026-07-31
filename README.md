# QUARRY — RAGE archive → working project folder

The companion tool to **RUDE**.

## ⛔ ZERO THIRD-PARTY TOOL AFFILIATION (Matt's requirement, 2026-07-27 — HARD)
**Neither QUARRY nor RUDE may be affiliated with the reference exporter in any way.** QUARRY's code never was:
`quarry.py` and `ngcrypto.py` contain **no the reference exporter reference at all** (the word "magic" in
`quarry.py` is the RPF7 file magic `7FPR`, unrelated). The single touchpoint was one optional helper,
`unpack_magic.ps1`, which read the `magic` resource out of a local `the third-party exporter's core library` — **removed
2026-07-27** to `_archive/`. QUARRY is now the reference exporter-free in code and in dependency.

**Consequence, stated plainly: QUARRY ships no keys and no key extractor.** `ng_keys.bin` and
`ng_tables.bin` are **entirely operator-supplied**; how an operator obtains them is outside this
tool's scope and is not documented here. 🔴 **This leaves end-user key acquisition an OPEN PRODUCT
QUESTION** — an operator who already has the two files is fully served; a new user is not. Do not
close that gap by reintroducing a third-party tool dependency.

| | |
|---|---|
| **QUARRY** | reads your own game archives → a sorted, precedence-aware project folder |
| **RUDE** | a UE plugin that consumes that folder — contains no archive or crypto code |

They meet only at a **folder contract** (`_FILEBASE.json` + `00_base` / `10_update` /
`20_dlc/NNN_name`). Neither depends on the other's internals, so the DCC stays clean-room
and either can be replaced without touching the other.

⚠ **Separate ≠ disjoint, and an unmanaged contract bites.** On 2026-07-27 QUARRY was emitting raw
binary while RUDE's importer reads only the interchange **XML** — with nothing to announce the mismatch.
Contract obligations, therefore: emit what RUDE actually consumes (the interchange XML), carry a
`contractVersion` in `_FILEBASE.json` that RUDE validates, and keep the numbered precedence tree
meaningful (see the flat-basename collision caveat in the status table).

**Title-aware from day one** — the same contract is meant to cover GTA V Legacy, GTA V
Enhanced, and later RAGE titles (RDR2/RedM, GTA VI). The manifest records which.

## Quickstart

    pip install -r requirements.txt
    python quarry.py doctor --game "<install>" --out "<project>"     # <- run this FIRST

`doctor` is the preflight: it reports python/numpy, the texture decoders, every converter, your game
install and its archive counts, whether key material derives from **your own** executable, Oodle,
and whether the target volume has room for the run you intend — and it says what to do about each
gap. Every failure it catches is one that would otherwise surface mid-extract looking like a
different bug. Then:

    python quarry.py extract --game "<install>" --out "<project>" --xml --textures none --types ydr,ydd,yft,ytd,ybn,ytyp,ymap,ymt
    python quarry.py meta    --out "<project>"      # ytyp/ymap/ymt -> XML + resolve ydd entry names
    python quarry.py resolve --out "<project>"      # flatten -> point RUDE's CorpusRoot at _resolved
    python quarry.py textures --out "<project>"     # then decode ONLY the pixels something references

## Commands

    quarry.py doctor  [--game "<install>"] [--out "<project>"]  # preflight; safe with no args
    quarry.py scan    --game "<install>"                       # what's there, what encryption
    quarry.py init    --game "<install>" --out "<project>"     # build the empty project tree
    quarry.py extract --game "<install>" --out "<project>" --xml --types ydr,ydd,yft,ytd,ybn,ytyp,ymap,ymt
                      [--keys <dir>] [--magic <file>] [--only x64a.rpf]
                      [--textures both|png|dds|none] [--max-depth 2] [--resume]
                      [--oodle "<oo2core_*_win64.dll>"]

    quarry.py meta    --out "<project>"                        # ytyp/ymap/ymt -> XML + ydd names  (AFTER extract)
    quarry.py resolve --out "<project>" [--types ydr,ytd,ytyp,ymap] [--copy]
    quarry.py textures --out "<project>" [--prune]             # decode/keep only REFERENCED pixels

⭐ **`--textures none` at extract time is the recommended flow**: the manifests (~0.1 GB) are enough
to know which dictionaries anything references; `quarry textures` then decodes just those pixels
instead of the whole game's ~86 GB. `--prune` deletes pixels nothing references — and refuses to
run when it scanned no evidence, because "no references found" and "nothing looked" are different.
⭐ **`--resume`** continues an interrupted extract: files already present are counted and skipped
rather than treated as collisions (added after two whole-game runs were lost to restarts-from-zero).

⭐ **The order is `extract` → `meta` → `resolve`.** `meta` is a second pass on purpose: a ytyp stores
its names as one-way joaat hashes, and the reverse table is built by hashing the asset FILENAMES the
archives yield — during extraction most of those files have not landed yet, so converting inline
would resolve far fewer names.

    ytd2xml.py <file.ytd | dir> --out "<dir>" [--png]     # one type, standalone
    ydr2xml.py <file.ydr> --out "<dir>"
    yft2xml.py <file.yft> --out "<dir>" [--extras]        # fragment + skeleton/physics/child sidecars
    ydd2xml.py <file.ydd> --out "<dir>" [--project <fb>]  # dictionary; --project resolves entry names
    meta2xml.py --convert <paths> --out "<dir>"           # ytyp/ymap/ymt, standalone
    meta2xml.py --roundtrip --census --corpus <dir>       # emitter proof + enum surfaces (or QUARRY_CORPUS)
    meta_write.py --selftest --root <filebase>            # META WRITER gate: write(read(x)) == x

⭐ **`resolve` is what makes the folder openable by RUDE.** RUDE reads a **FLAT** corpus
(`ImportMapArea` globs `<root>/ytyp/*.xml`, `<root>/ymap/<prefix>*.xml`, and looks up
`<root>/ydr/<assetName>.ydr.xml`), while extraction writes numbered precedence slots — so without
this step the plugin cannot open a project folder at all. `resolve` walks the slots in ascending
load order and materialises `_resolved/<type>/` with ONE build-accurate file per name; point RUDE's
`CorpusRoot` there. Hardlinks by default, so it costs almost no extra disk (`--copy` for a
cross-volume destination). Resolving belongs to QUARRY because QUARRY is what knows load order.

⭐ **`--keys` is OPTIONAL** — with an installed copy of the game, QUARRY derives its own key material.
⭐ **`--xml` emits what RUDE's importer already reads.** Verified end-to-end 2026-07-27: a no-`--keys`
run over `x64i.rpf` produced 3,479 `.ydr.xml` with **0 conversion failures**, and RUDE's `ImportYdr`
consumed them — including `dt1_13_build1` (a 5 MB downtown building: 14 geometries, 31,285 verts,
35,858 tris, 5 textures bound, all 14 shader presets resolved from `joaat_shaders.json`).

⚠ **Use `--types`.** Nested archives are descended into by default, and an unfiltered full run is
**~376,800 files**. Map authoring wants `ydr,ydd,yft,ytd,ybn,ytyp,ymap,ymt`.

⭐ **Embedded texture dictionaries** (33.9% of drawables carry one): for any `X.ydr.xml`, the
sibling `X__embedded.ytd.xml` holds X's own textures, pixels in `X__embedded/`. The `__embedded`
infix (double underscore, NOT a dot) is load-bearing — the stem becomes a UE package-path segment
and a dot is illegal there — and it cannot collide with a real dictionary name.

## ⚠ Plan for disk before a whole-game run — MEASURED, not guessed

| Artifact | measured on `x64i.rpf` | whole-game estimate |
|---|---|---|
| `ydr.xml` | 1.56 GB / 3,479 files (avg 469 KB) | **~38 GB** (~84,000 ydr) |
| ytd `.dds` | 1.62 GB / 7,148 textures | ~23 GB |
| ytd `.png` | 2.35 GB / 7,148 textures | ~33 GB |
| `ytyp.xml` + `ymap.xml` | 0.01 GB | negligible |

So `--types ydr,ytd,ytyp,ymap --textures both` over the whole game is **~94 GB**. Use `--textures`
to pick: **`png`** is what `ImportYtd` actually loads, **`dds`** is the lossless repackage, `both`
(default) writes each. A map-only run (`--types ydr,ytyp,ymap`) is ~38 GB and gives full placement
coverage — textures can be added per-area afterwards.

⚠ `resolve` **hardlinks**, so `_resolved/` costs almost nothing on disk — but `du`-style tools that
follow links will double-count it. A "11 GB" project folder measured that way was really ~5.5 GB.

## Dependencies

QUARRY's core — RPF reading, the NG cipher, key derivation, `ydr`/`ytd` → XML, `resolve` — is
**pure standard-library Python plus `numpy`** (the cipher needs vectorising; the scalar path hangs
on real archives). One thing is optional and, today, load-bearing:

    pip install texture2ddecoder Pillow      # required for the ytd .png sidecars

⚠ **Without it the texture lane does not work**, because `ImportYtd` loads
`<PixelFolder>/<TexName>.png`. QUARRY still writes the lossless `.dds` and **says so loudly on
startup** rather than producing a folder that silently can't be read. 🔴 The real fix is native BC
decode inside RUDE — then the PNG bridge and this dependency both disappear.

## Why the folder is numbered

The same asset name exists in the base game, in `update.rpf`, and in several DLC packs;
the game uses the **last one in load order**. The tree encodes that, so anything reading
it resolves the build-accurate copy by walking high → low:

    00_base/             base x64*.rpf / common.rpf
    10_update/           update.rpf — overrides base
    20_dlc/NNN_<name>/   DLC packs, higher NNN wins

Type folders (`ydr/ ytd/ ybn/ …`) are created as files land.

## 🎯 Where this is going (Matt's direction, 2026-07-27)

1. ⛔ **No the reference exporter affiliation, anywhere.** Done in code (above). Key acquisition stays the
   operator's business.
2. 🔴 **Port to a C language.** Python was a prototyping choice; C/C++ is the target. This was
   already intended in an earlier session and never landed. Note C++ makes the cipher *easier*, not
   harder — the numpy vectorisation that Python needed (the scalar path hangs on real archives) is
   just a plain loop in C++.
3. 🔴 **Export EVERYTHING through the XML pipeline.** ⭐ This is the
   insight that explains the wasted effort: RUDE's importer already reads the interchange XML and is proven
   on 1,144 Cayo meshes with materials, collision, LODs and textures. QUARRY emitting raw *binary*
   forced us to start rebuilding readers the XML pipeline already had. **Emit `*.ydr.xml`,
   `*.ytyp.xml`, `*.ymap.xml`, `*.ytd.xml` and the existing pipeline consumes them unchanged.**
   Helpers already built for this: `joaat_shaders.json` (216 shader presets, hash → name) and
   `shader_param_names.json` (5,058 value-parameter names, harvested from the game's own compiled
   shaders) — the binary stores only the joaat hash and XML needs the name.

## Status

| Piece | State |
|---|---|
| 🏆🏆 **WHOLE-GAME RUN + CENSUS — done 2026-07-27** | `extract → meta → resolve` over all 24 base + 2 update + 92 DLC archives: **101,412 files extracted, 0 archives skipped, 79,844 ydr XML + 21,568 ytyp/ymap XML, ZERO conversion failures**. `resolve` → 100,422 flat files with **22,213 overridden by a higher slot** (precedence doing real work; a naive flat extract would have silently used base-game copies of 22k assets). ⭐⭐ **Census of all 1,627,754 map entities: 71.6% import as real meshes and that is the CEILING** — 18.4% fragment + 9.9% ydd + 0.1% MLO have **no importer yet**, and only **221 (0.014%)** are a real gap (all `des_*`, from the AES nested archives). **`archetype resolved but mesh absent` = 0.** The only extraction refusal is the known Oodle-packed resource, and it now fails **loudly with its reason** |
| ⛔ **FIXED: the float formatter was a SHIPPED DEFECT** (2026-07-27) | `fmt_num` used `repr(float)`, so every non-integral value in every emitted ytyp/ymap disagreed with the reference. **Both gates were blind:** the round-trip harness re-emits reference *strings* (lossless by construction) and `verify_binary` compared with float *tolerance*. Now: **7 sig digits widening to 9 only when 7 doesn't round-trip float32, ties AWAY FROM ZERO** (needs `decimal`; `%G` rounds half-to-even), `NaN` literal. Verifier scores TEXT-exactness separately and splits the residual by float32 bits — same bits = our bug, different bits = build drift. **0 format differences remain** |
| ◑ **MLO interiors DECODED** (2026-07-27) | `CMloArchetypeDef`/`CMloRoomDef` **100.000% over 18,084 field comparisons**; portals (4×16-byte corners, 4th float always `NaN`) and entity sets (`locations` parallel to `entities`; entities are 8-byte struct pointers) both decoded. ⚠ **VEC3 array stride is 16 bytes, not 12.** ✅ **EMITTED since 2026-07-28** — `meta2xml` writes `CMloArchetypeDef` with rooms, portals, entity sets, all 14 `CExtensionDef*` types and light instances (see the 07-28 additions table). Honest gaps (flag bit meanings, empty-`<rooms>` rendering, timecycle/ybn name coverage) in LOG §"MLO INTERIORS" |
| ✅ **`doctor` — the new-user preflight** (2026-07-27) | reports python/numpy, texture decoders, every converter, the game install + archive counts, whether key material derives from the user's **own** exe, Oodle, and free disk **against the measured cost of the run they intend** — and says what to do about each gap. Safe to run with no arguments. Every line it checks was previously a silent failure that surfaced mid-extract looking like a different bug. Plus `requirements.txt` |
| ✅✅ **KEY ACQUISITION — ONE-CLICK when the blob is present** (`keyderive.py`, 2026-07-27) | Consumes a local `resources/magic.dat` (option A) — **git-ignored, so a clone of this repo does NOT include it**; the operator supplies it (or `--keys`/`--magic`) and QUARRY opens it with the AES key found in the user's **own** exe by SHA-1 anchor. **Verified: derived keys match the published MIT SHA-1 constants AND are byte-identical to the known-good files.** Includes a from-scratch .NET `Random` (A/B'd against real `System.Random` on 7 seeds incl. both int32 boundaries), self-contained AES-256-ECB, and inflate — **no .NET, no the reference exporter, no crypto dependency**. Priority: existing key files → bundled blob. ⭐ blob is a RUNTIME INPUT: deleting it switches to option B with no code change |
| ⛔ **the reference exporter dependency** | **SEVERED 2026-07-27** — `unpack_magic.ps1` archived; no the reference exporter reference remains in code |
| ✅ **XML export — `ydr` DONE** (`ydr2xml.py`) | binary ydr → `*.ydr.xml` the existing RUDE importer reads unchanged. **Verified by diffing against the reference exporter's own XML for the same asset:** 3/3, 8/8, 17/17 geometry counts · 28/28 layouts · shader-preset lists identical · 27/28 vertex/index counts (the one gap is Enhanced-vs-Legacy source data, proven by a 3-way internal count cross-check). ⚠ `<Bounds>` not emitted yet → props import but are not flagged collidable |
| ✅ **XML export — `ytd` DONE** (`ytd2xml.py`) | binary ytd → `*.ytd.xml` **+ a `<stem>/` folder of `.dds` AND `.png`**, because `ImportYtd` takes the XML and the pixels as separate arguments — and **it loads the `.png`**, so DDS alone would leave the lane connected on paper and broken in practice. ✅ end-to-end: 1,455 XML / 7,100 dds / 7,100 png, all carried through `resolve`. DDS is a pure repackage (the archive's own blocks behind a 128-byte header — no decode, no dependency, no loss); `--png` also decodes but needs `texture2ddecoder`+`Pillow`. **Verified against the reference exporter's own XML for the same assets: Usage 360/360, FileName 360/360, Format 356/360** (the 4 are corpus build drift, proven by the files' own allocation fields). 1,455/1,456 real dictionaries convert. ⭐ `Usage` was **derived by measurement** over 285 agreeing rows, not from an assumed enum — and it independently confirmed the value RUDE's ytd writer had carried as "pending confirm" |
| ✅✅ **XML export — `ytyp` / `ymap` DONE, RSC7 v2 META SOLVED** (`meta2xml.py`, `quarry.py meta`) | **The city-import blocker is closed.** ✅ **In-engine, MCP-driven:** `ImportMapArea` consumed QUARRY's own ytyp+ymap+ydr XML — 63 entities → **60 meshes imported, 0 failed, 60 instances spawned**, actors placed along a curving freeway path with textured road geometry (not stacked at origin). ✅ **`ymap` verified at 100.000% — 169,780 field comparisons, 0 mismatched, 210/210 files item-count exact, including position AND rotation.** ✅ `ytyp` scalars/enums 2,600/2,600 exact on the drift-free subset; the ~2% geometry differences are build drift (bb + sphere move together). ⭐ The unlock: **META schema hashes are CASE-SENSITIVE joaat**, while asset-name hashes in the data are lowercase. ytyp and ymap share the header byte for byte, so one walker serves both. ◑ Carried forward (not needed for reading, but a WRITER must solve them): header +0x40 blob, struct-info secondary `key`, and the multi-bit `0x65` flag rendering |
| ✅ **XML export — `ydd` DONE** (`ydd2xml.py`, 2026-07-28) | binary ydd (pgDictionary\<gtaDrawable\>, RSC7 v165 = the drawable-family version) → `*.ydd.xml`. Reuses the ydr drawable walk via a `base` offset (refactor A/B-proven byte-identical, 200/200). **Oracle: 58/60 name-matched files structurally identical to reference exports; both residuals proven build drift. Scale gate: 14,447/14,447 converted, 0 failures, 86,138 drawables.** Entry names joaat-resolve where the table knows them, else `hash_%08X` (free downstream - dictionary joins are hash-to-hash) |
| ✅ **XML export — `yft` visual v1 DONE** (`yft2xml.py`, 2026-07-28) | fragment (RSC7 v162) → `<Fragment><Name/><Drawable>` XML carrying the MAIN VISUAL drawable (ptr at +0x30, measured 300/300). **Oracle: 54/60 full match, 0 structural.** ⚠ v1 scope: no breakage/cloth/child pieces, no embedded-texture pixel export. ⚠ Known boundary: packed CLOTH vertex nibbles refuse loudly (0x1 = 4 B solved; 0xa+0x3 pending) |
| ✅ **`ybn` → XML — built, oracle-validated, WIRED 2026-07-29** | `ydr2xml.boundsfile_lines` (the same walk that emits embedded `<Bounds>`): 183/183 name-matched reference exports identical. It existed unwired for a long time — the lesson is recorded at the branch itself (`quarry.py`, the ybn case): a capability that exists but is not wired is indistinguishable from one that was never built. ⚠ RUDE still has no importer for a *standalone* `.ybn.xml` (embedded `<Bounds>` in ydr is what the prop lane uses) — that consumer gap is RUDE-side |
| 🔴 **C/C++ port** | not started; Python is the prototype |
| RPF7 container, TOC walk, entry decode | implemented |
| **nested `.rpf` recursion** (`--max-depth`, default 2) | implemented 2026-07-26 — **required for map assets**; the base archives are mostly containers and nearly every `.ydr/.ybn/.ytyp/.ymap` lives one level down |
| **type filter** (`--types ydr,ybn,ytyp,ymap`) | implemented 2026-07-26 — a full unfiltered run is ~376,800 files |
| deflate | implemented |
| Oodle (via the `oo2core` DLL in **your** install) | implemented for binary entries. ⚠ **A GTA V *Legacy* install ships no `oo2core`** — the DLL comes with *Enhanced*, so pass **`--oodle <path>`** (QUARRY also searches sibling Rockstar installs). ⛔ the **resource** path does not use Oodle at all: a resource keeps its compressed body, and the on-disk form is DEFLATE, so an Oodle-packed resource would need decompress→re-deflate. Unbuilt — such entries are reported and skipped (1 of 64 in `x64a.rpf`) |
| project folder build, precedence sorting, manifest | implemented. ✅ **DLC order is AUTHORITATIVE (2026-07-27)** — `read_dlclist()` pulls the game's own `dlclist.xml` out of `update.rpf` (reads the TOC, inflates only that one 610 B entry) and `dlcOrderAuthoritative` is now `true`; `resolve` inherits the flag rather than restating a guess. ⚠ The old heuristic was **genuinely wrong**, not just unproven: it put `mpairraces` first where the real order starts `mpheist`. That matters because a FiveM server's DLC level decides what overrides what — an override authored against the wrong level **loses silently** |
| ✅ **`resolve` — precedence tree → the FLAT corpus RUDE reads** (2026-07-27) | closes the layout half of the contract gap: `_resolved/<type>/`, one build-accurate file per name, hardlinked. ✅ **verified on synthetic multi-slot data**: the highest slot wins the contested name, **its pixel sidecar comes from that same slot** (never a mix of two dictionaries), unique files from every slot are carried, and `_RESOLVED.json` records the winning slot per file. ⚠ the flat layout is inherently lossy where one name repeats **within** a slot — 843 of 1,893 `x64g` ytd (clothing/ped variants across nested archives); the un-suffixed copy wins and the alternates are counted, not silently dropped. Map types are unaffected in practice (0 collisions across 3,479 `x64i` ydr) |
| collision-safe filing | implemented 2026-07-26 — same-named files in one slot keep the first and suffix the rest, and collisions are **counted** (was a silent overwrite). ⛔ **fixed 2026-07-27:** the rename split the DOUBLE extension (`foo.ytd.xml` → `foo.ytd~1.xml`), which every consumer misses, so a "handled" collision still lost the asset; the suffix now lands on the stem (`foo~1.ytd.xml`) and a converted asset's sidecar folder follows the XML actually written |
| ✅ **24-bit size saturation — FIXED 2026-07-27** | The TOC's `FileSize` is a **u24**, so an entry of **≥16MB cannot state its length**: it stores `0xFFFFFF`, a **saturation marker**. Read as a literal length it cut every large `+hi` HD dictionary at `0xFFFFFF−0x10` B — 7 of 1,900 in `x64g`, **50 game-wide across 12 of the 24 base archives**. The real length was **derived from the bytes**: it is carried in the 16-byte header slot at the entry's offset as a LE u32 at bytes **7, 14, 5, 2** (bit-solved against the length zlib actually consumes, 50/50; the slot's other 12 bytes are high-entropy and unexplained; the same decode on a non-saturated entry is nonsense). That is only the read WINDOW — DEFLATE self-terminates, so the body is trimmed to the stream's own end. ✅ verified: all 7 extract at their true length (17.0–41.4 MB), inflate, and convert (`ytd2xml --selftest`: **410 textures**); `x64c`'s 4 likewise (**355 textures**); **1,900/1,900 `x64g` + 1,748/1,748 `x64c`** are now complete-deflate, page-plan-exact, zero trailing bytes |
| NG block cipher (17 rounds, A/B round structure, table-driven) | implemented |
| per-file key selection `((hash(name) + size + 61) & 0xFFFFFFFF) % 101` | implemented — ⚠ the **uint32 mask is mandatory**; without it 6 of 24 base archives silently fail their TOC check and look like "wrong keys" |
| resource-body integrity | implemented 2026-07-26 — bodies are validated as real DEFLATE (plain **or** NG-decrypted, whichever inflates) and an unrecognised body is **reported, never written**. Necessary because the RSC7 header is *rebuilt* from entry flags, so output always *looks* valid. ⛔ **hardened 2026-07-27:** the gate returned `d.eof or not d.unconsumed_tail`, and `unconsumed_tail` is only non-empty when `max_length` is used — so a **truncated** body satisfied the second clause and was waved through, which is exactly how the 7 saturated files were written while the run reported **zero failures**. It now requires `d.eof` **and** that the body inflate to **exactly** its RSC7 page-plan total (`sysFlags`+`gfxFlags` — the one number the rebuilt header cannot fake; exact on **4,176/4,176** resources measured across `x64a`/`x64g`), and the failure line now carries the **reason**, not just `ValueError` |
| AES-256 ECB path | ⛔ **not available** — the AES key is not part of the NG key data, and recovering it is a separate step from the NG keys. ⚠ The earlier claim here ("only affects vehicle `*_mods.rpf`, out of scope") was **wrong on both halves** — `des_setpiece.rpf`, `des_jetsteal.rpf`, `des_heli_*` and ~30 more map set-piece archives are AES-encrypted too. They are **reported and counted as skipped**, never mis-read; closing the gap is an open item |
| **NG key + table DATA** | **operator-supplied — QUARRY ships none** |

## Keys

QUARRY contains **no key material**. `--keys <dir>` expects:

    ng_keys.bin     101 × 272 bytes  =  27,472 bytes
    ng_tables.bin   17 × 16 × 256 × uint32  =  278,528 bytes

Without them, unencrypted archives still extract and everything else works; encrypted
archives are reported as skipped rather than silently producing garbage. The TOC sanity
check (`entry 0 must be the root directory`) means wrong keys are detected immediately
instead of writing corrupt files.

## Boundaries

- Never redistribute game data or key material. Everything QUARRY reads comes from the
  operator's own installation, on their own machine.
- No anti-tamper circumvention: QUARRY does not attach to, dump, or modify a running
  game process. (`GTA5.exe` is packed — `.text` entropy 7.999 — so keys are not
  statically recoverable from it; that route is closed by design, not oversight.)

## 2026-07-28 additions (detail: vault ENGINEERING_LOG 07-28 sections)
| Piece | State |
|---|---|
| ✅ **`ydd` → XML** (`ydd2xml.py`) | pgDictionary<gtaDrawable>, v165; oracle 58/60 identical (2 proven build-drift); whole-corpus 0 failures |
| ✅ **`yft` → XML, visual v1** (`yft2xml.py`) | v162, main drawable @ +0x30; oracle 54/60, 0 structural; cloth vertex formats (half2/half4/sbyte4) VALUE-validated |
| ✅ **ydr fidelity upgrades** (`ydr2xml.py`) | embedded `<Bounds>` emitted (Capsule measured; ybn-oracle 183/183, 0 format bugs) · REAL sampler names + RenderBucket (diffuse recovery 57.5→97.3%, mislabels→0) |
| ✅ **MLO + extensions emission** (`meta2xml.py`) | rooms/portals/entity sets + all 14 CExtensionDef types + light instances; 1.96M comparisons, FMT_BUG=0 |
| ✅ **Scenario regions → XML** (`meta2xml.py`) | CScenarioPointRegion full shape; 204/204, 5.5M comparisons, FMT_BUG=0; multi-bit flag join measured |
| ✅✅ **RSC7 v2 META **WRITER** — standalone module** (`meta_write.py` + `writer_constants.json`; not called by `quarry.py` — its gate is its own `--selftest`, and `doctor` checks it imports) | The other direction at last: binary `ytyp`/`ymap`/scenario `ymt` can now be WRITTEN, not just read. Value-level model - every byte is re-encoded from a decoded cell, so byte identity proves the ENCODERS rather than a buffer copy. Gate: `python meta_write.py --selftest` (write(read(x)) == x over random real binaries; 240/240 byte-identical from the installed location, and 2,637 files during derivation). ⭐ zlib **memLevel=9** reproduces R*'s deflate exactly. ⛔ The header `+0x40` blob is OPTIONAL - 180/180 community-authored files leave it NULL and load in game - so authoring does not need its (still unrecovered) cipher. 🔴 A from-scratch layout allocator is the remaining piece before brand-new interiors/regions can be emitted; read->edit->write works today. |
| ✅ **sp_manifest PSO reader/patcher — standalone module** (`pso_manifest.py`; not called by `quarry.py`) | The manifest half of scenario deployment. Reads/writes the `PSIN` container for `CScenarioPointManifest` and can ADD regions (`compcache:/<resource>/<region>` + AABB) to a vanilla manifest. Gate: `python pso_manifest.py --selftest --manifest <sp_manifest.ymt>` - **a PRODUCTION manifest round-trips BYTE-IDENTICALLY** (160 regions, 54 compcache-routed, 23,270 B). ⚠ A VANILLA Rockstar manifest legitimately round-trips SMALLER: it carries `PSIG`/`STRE`/`CHKS` sections that no working community manifest has and whose formats are unrecovered - so the correct oracle is a manifest known to LOAD, not one shipped by R*. ⛔ Only ONE sp_manifest can be active server-side, so "add a region" means REBUILDING the single manifest with every region. `--dump` prints one as JSON. |
| 📄 **Enhanced (Gen9)** | the Enhanced install OPENS with Legacy-derived keys (73/73 payloads verified); v159/v171/v5 samples banked; decode = future |

## 2026-07-29/30 additions (detail: vault ENGINEERING_LOG 07-29/30 sections)
| Piece | State |
|---|---|
| ✅ **`ybn` → XML wired into `extract`** | the already-oracle-validated emitter (183/183) is now reachable; see the Status row above |
| ✅ **Embedded texture dictionaries exported** | 33.9% of drawables carry their own textures; each emits a sibling `X__embedded.ytd.xml` + pixels. In-engine effect: missingTextures 4,633 → 4 across downtown |
| ✅ **Shader value params decoded + named** | 104,178 emitted, 100% named via `shader_param_names.json` — 5,058 hash→name entries harvested from the 321 `.fxc` files in the user's own `common.rpf` |
| ✅ **`extract --resume`** | an interrupted whole-game run continues instead of restarting from zero; resumed files are counted |
| ✅ **`textures` subcommand** (`--prune`) | decode-what's-referenced instead of decode-everything (the 86 GB problem); prune refuses to act on zero evidence |
| ✅ **yft EXTRAS wired into `extract`** (2026-07-30) | skeleton + physics group/child join + one importable `<stem>/<group>.ydr.xml` sidecar per geometry-bearing child (the vehicle wheel lane) now come out of the pipeline, not just the standalone CLI. A refusal (unmeasured value) falls back to the visual drawable and is **counted**, never silent. Verified byte-identical to the standalone path on vehicle + prop fragments |
| ✅ **`.ymt` in the `meta` pass** (2026-07-30) | scenario regions (`CScenarioPointRegion`) convert in the pipeline; PSO (`PSIN`) manifests are counted-skipped, not failed (see `pso_manifest.py`) |
| ✅ **ydd entry names resolved by `meta`** (2026-07-30) | `extract` writes `hash_%08X` (the reverse table doesn't exist yet at that point); `meta` now resolves them in place from the filename-derived table. Unresolved entries stay `hash_%08X` — the dictionary join is hash-to-hash, so nothing downstream depends on it |
| ✅ **Fragment (`yft`) embedded textures exported** (2026-07-31) | the same `X__embedded.ytd.xml` + pixels contract as ydr, rebased to the fragment's MAIN drawable (children have no ShaderGroup of their own). Measured over all 6,026 base-game binary yft: **1,558 (25.9%) carry an embedded dictionary — 5,723 textures** — and sampled carriers request *only* textures that dictionary holds, i.e. exactly the fragments that imported untextured. ⚠ In-engine binding not yet re-verified: existing filebases need a yft re-extract to gain the sidecars |
