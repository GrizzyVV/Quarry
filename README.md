# QUARRY — RAGE archive → working project folder

QUARRY reads the GTA V archives **you already own** and turns them into a project folder a DCC
can open: interchange XML for every asset type it understands, pixels on demand, laid out in
load-order so the file that *wins* is the file the game would load.

It is the asset supply line for [RUDE](https://github.com/GrizzyVV/RUDE) (Unreal ↔ FiveM), but it
has no dependency on it — the output is plain XML and standard image files, useful to any tool.

**MIT licensed. Python 3.10+. No game data is redistributed — your own install is the only source.**

---

## ⛔ Clean room — zero third-party tool affiliation

**QUARRY is not affiliated with, derived from, or endorsed by any third-party GTA V tool, and no
third-party tool source was consulted.** Every format in this repository was derived from three
things only: the game's own binaries, XML produced by a reference exporter run over those same
binaries (used as a black-box *oracle* — output compared, never code read), and this project's own
measurements.

Where a docstring says an XML shape is "reference-identical", that is a statement about **file
compatibility for users** — the output can be consumed by the same tools that read the reference
format — not a statement of lineage.

Key material is **never shipped**: `keyderive.py` recovers it from *your* executable at runtime.

---

## Quickstart

```bash
python quarry.py doctor --game "<your GTA V install>"      # what's ready, what's missing
python quarry.py view   --game "<install>" --out proj      # register every file, extract nothing
python quarry.py extract --game "<install>" --out proj --xml \
       --types ydr,ydd,yft,ytd,ybn,ytyp,ymap --textures none
python quarry.py meta    --out proj --view proj --game "<install>"
```

Point your consumer at the project's slot tree (`00_base/`, `10_update/`, `20_dlc/<slot>/`) —
files stay exactly where the game ships them, in load order; sidecars sit beside their
drawable. Precedence is the slot ordering itself. Add pixels later, only for what you
actually use:

```bash
python quarry.py textures --out proj --decode-referenced --game "<install>"
```

---

## Commands

| command | what it does |
|---|---|
| `doctor` | preflight: interpreter, dependencies, converters, key derivation, archives, free disk |
| `view` | **the manifest** — registers every file in every archive from TOCs alone. Nothing extracted, ~0 disk |
| `scan` | archive inventory: how many base / update / DLC packs, and their encryption |
| `init` | derive keys, order the DLC list, write the project skeleton |
| `extract` | the bulk lane — convert whole types to XML, or keep binaries. `--types`, `--resume`, `--textures` |
| `export` | **targeted** — convert exactly the named entries, straight from the archives, same converters |
| `meta` | convert binary `ytyp`/`ymap`/`ymt` and resolve dictionary entry names. Run **after** `extract` |
| `resolve` | **retired** — the slot tree IS the corpus contract; nothing pre-flattens it (invoking prints the ruling and exits) |
| `textures` | the referenced-pixel lane: report, decode only what is referenced, prune the rest |
| `regress` | the churn gate — converter output may not change unless someone records why |
| `witness` | rebuild the topic census the churn gate reads |

Useful flags: `--view` (resolve names from the whole-game registry), `--oodle <oo2core dll>`,
`--split` (each targeted entry into its own numbered folder), `--textures none|dds|png|both`.

---

## What it converts

Every type below is **wired into the pipeline** and reproduces reference exports byte-for-byte on
the positions covered by the conformance suite.

| domain | types |
|---|---|
| map & placement | `ymap` `ytyp` `ymf` (+ PSO- and RBF-container variants) |
| geometry & collision | `ydr` `ydd` `yft` `ybn` `ybd` |
| textures | `ytd` (+ `.dds` / `.png` sidecars, mip chains intact) |
| animation & motion | `ycd` `ypt` `mrf` `yed` `ypdb` |
| navigation & routes | `ynv` `ynd` `yvr` `ywr` |
| audio & shaders & data | `rel` `fxc` `pso` `ymt` `yld` `yfd` |
| raw lanes | any type without a converter is kept **byte-exact**, counted, never dropped |

Containers are detected by **magic, not by extension** — a `PSIN` or `RBF0` file named `.ymap` is
routed to the right reader, so a mislabelled file cannot be emitted under the wrong schema.

---

## How correctness is established

This is the part that matters, and it is deliberately unglamorous.

**1 — Byte-identical or it doesn't count.** A conversion passes only if it matches a reference
export **byte for byte**, with exactly one sanctioned normalization: newline convention. Float
spelling, field order, whitespace, a dropped element — all defects.

**2 — The comparator must be able to fail.** `tools/grade.py selftest` mutates a known-good file
five ways and requires the diff to redden on all five, and to stay green on the two sanctioned
cases. A gate that has never failed is unproven.

**3 — Conformance is measured, not asserted.** The regression suite grades **318 positions:
318/318 byte-identical**, and has held there across every change since. Beyond the suite, the
full oracle board reads **1,263/1,263 across eight lanes at corpus scale**, targeted and
at-scale output are proven identical **keyed by source entry (276/276 pairable positions)**,
texture sidecars grade **288/290** (the 2 non-passes are a counted format-alias class and a
store artifact, both named), and the small-lane board — expressions, pose matchers, path
nodes, vehicle and waypoint records, cloth dictionaries, bounds dictionaries and particles —
reads **175/175 against fresh stratified reference draws, zero exceptions**, with those lanes
also extracted at corpus scale under format invariants. Every non-pass in history is named,
with its cause, below.

**4 — Oracles are a lower bound, so invariants run at corpus scale.** Passing the suite does not
prove correctness for the other 384,000 files. The tool therefore also checks properties the
*format itself* must obey across everything it emits — a parse must consume the file exactly, frame
budgets must close, XML must be well-formed with the expected root. This is not theoretical: it
caught an animation decoder that was padding-filling undecodable data and returning plausible
numbers. Ten of ten oracles passed either way; only the corpus-scale check saw it.

**5 — Uncertainty is counted, never hidden.** Where a value is fitted to observed data rather than
proven by a rule, the emitter **counts every such emission** and the run prints it. A rising counter
means "go widen the evidence", not "trust it". The same discipline applies to refusals: an
undecodable channel emits a visible `<!-- RESIDUAL -->` marker rather than an invented value, and
a file that will not decode is reported and left absent rather than written wrong.

**6 — Nothing silently skips.** Every refusal class reaches the printed summary of every path that
can produce it, and the full failure list is written to disk. A zero-work run exits non-zero: a run
that was asked to do something and produced nothing is a failure, not an empty success.

---

## Known limitations — the honest list

| area | status |
|---|---|
| `ypt` behaviour types | **complete** — a full-population census (1,240/1,240 particle files walked) found exactly 23 behaviour types game-wide, and all 23 are derived and byte-verified, including the densest particle file in the game (42 MB of XML, byte-identical). An unknown type hash now means the install itself changed, and still refuses loudly |
| remaining `ypt` constants | the behaviour scalars that vary in real data are read from their pinned offsets — a multi-instance stress pass over 1,605 particle rules promoted seven more from constants to offset reads. The remainder are single-valued across every witnessed file and **counted on every emission** so a future counter-example surfaces itself |
| `ybd` bounds dictionaries | the reference exporter produces no XML for this type at all, so the lane grades on raw parity — and is **proven byte-exact at its entire game population** (4/4) |
| animation channel variants | only provably-decodable channels emit values; the rest emit residual markers. Closing this lane against fresh oracles is the final derivation campaign |
| hash-only content names | a handful of names exist in no in-scope file (scripts are excluded). A **self-verifying overlay** harvested from reference exports resolves them: an entry only fires where its hash equals the value stored in the binary, so a wrong name cannot mis-fire; deleting the overlay reverts to hash spellings |
| encrypted audio containers | container fully decoded; whole-file-encrypted archives are refused loudly — the cipher is not recoverable clean-room |
| script files (`.ysc`) | excluded by maintainer policy |
| stored-uncompressed entries | a small class of resource entries stores its data uncompressed, shorter than the declared page plan — the plan states page *capacity*, not length. These are accepted verbatim (proven byte-equal to reference raw exports), and every acceptance is **counted in the run summary** |

---

## Roadmap

**Done — the city, its textures, and its interiors, at scale.** The map, geometry, collision,
fragment, texture and interior lanes are conformance-signed at corpus scale: one uniform
generation, full provenance ledger (which archive and which DLC every emitted file came from),
targeted-vs-at-scale identity proven per source entry, pixels converged on the one image form
downstream tools load. The corpus contract is the game's own layout: slot tree in load order,
content keeps its in-game name, per-container folders where the game itself nests them.

**Now — the last two campaigns.** Every small lane is closed: byte-identical against fresh
stratified reference draws (175/175) and extracted at corpus scale under format invariants —
including the complete particle type surface and the expression opcode surface, both of which
grew by derivation this cycle when at-scale runs surfaced structures the original draws never
witnessed. What remains is navmesh densification and the animation lane — the largest remaining
derivation surface — run the same way as everything else: fresh oracles first, derive,
byte-identical, then scale.

**Later — a C++ port.** The Python here is the prototype layer: the rule is *conform first, port
second, re-verify after*. Nothing gets ported until it is proven against the oracles.

---

## Repository layout — what is live, and what is not

Nothing here is dead weight by accident. Every file is in one of three states, and the state is
stated rather than left for a reader to guess.

**The pipeline** — `quarry.py` (CLI and dispatch), `keyderive.py` + `ngcrypto.py` (key material),
and the converters it calls: `meta2xml` `ydr2xml` `ydd2xml` `yft2xml` `ytd2xml` `pso2xml`
`rbf2xml` `ycd2xml` `ypt2xml` `ynv2xml` `rel2xml` `mrf2xml` `fxc2xml` `yed2xml` `yld2xml`
`yfd2xml` `ynd2xml` `ypdb2xml` `yvr2xml` `ywr2xml`, plus the JSON name tables they load.

**Standalone tools** — run on their own, deliberately not wired into the pipeline:

| file | why it stands alone |
|---|---|
| `meta_write.py` | the META **writer** (XML → binary). The authoring direction; the read path is what the pipeline needs today. Has its own `--selftest` |
| `awc2xml.py` | audio container decoder. Fully derived and round-trip proven on plaintext containers; deliberately unwired while the audio direction is decided |
| `analyze_lod_hierarchy.py`, `analyze_texture_residuals.py` | measurement scripts that produced findings recorded in the converters. Kept so the measurements are reproducible |

**Superseded** — kept for provenance, not called by anything:

| file | superseded by |
|---|---|
| `pso_manifest.py` | `pso2xml.py`, which is schema-driven from the file's own PSCH section and therefore serves every PSO root rather than one hardcoded shape |
| `oracle_pso_names.json` | `game_pso_names.json`, derived from the game's own data files rather than from reference output |

Preserving superseded code costs nothing and records how a decision was reached; deleting it
would erase the evidence trail that makes the derivations checkable.

## Dependencies

`numpy` (required) · `texture2ddecoder` + `Pillow` (only for PNG decoding; DDS always works
without them). `pip install -r requirements.txt`. Oodle-compressed entries need an `oo2core`
DLL you already own — pass it with `--oodle`.

---

## Keys

Derived on your machine from your own executable, every run. Nothing is shipped, nothing is
downloaded. See `keyderive.py`, whose attribution to the upstream MIT-licensed `gta-toolkit`
work is recorded in `NOTICE`.

---

## Boundaries

- Never redistributes game data. Your install is the only source.
- Never writes back to the archives. QUARRY reads; it does not modify your game.
- Refuses rather than guesses. A file that cannot be decoded correctly is reported, not invented.
