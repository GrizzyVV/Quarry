"""ydd2xml - binary GTA V .ydd (drawable dictionary)  ->  RAGE interchange .ydd.xml

WHY THIS EXISTS
9.9% of all map entities (160,837 of 1,627,754 - the whole-game census) reference
ASSET_TYPE_DRAWABLEDICTIONARY archetypes and today spawn as proxy cubes: QUARRY had no ydd
converter, so RUDE has nothing to read. A ydd is pgDictionary<gtaDrawable> - the container walk
mirrors ytd2xml's pgDictionary<grcTexture> and every entry is the gtaDrawable that ydr2xml
already fully decodes (drawable_lines, base-offset form; A/B-proven byte-identical for ydr).

FIELD MAP - MEASURED (2026-07-30 corpus rebuild: 20,328 ydd converted through this walk):
      +0x20 hash array*      (u32 joaat per entry, ascending)
      +0x28 (count<<16)|count
      +0x30 pointer array*   (8-byte tagged pointers, upper dword 0)
    RSC7 version 165 - the DRAWABLE-FAMILY version (see YDD_VERSION below).
    entry names: the hash array carries joaat(name); the pipeline emits hash_%08X at extract
    time and `quarry meta` resolves them afterwards from the filename-derived reverse table
    (meta2xml.load_names). Unresolved entries stay hash_%08X, which is also the community
    convention - the ymap->ytyp->dictionary join is hash-to-hash, so unresolved names cost
    nothing downstream. Standalone runs can pass --project to resolve inline.

Usage:
    python ydd2xml.py --probe <file.ydd> [...]      # measure the header before trusting it
    python ydd2xml.py <in.ydd> [...] --out <dir> [--project <filebase>]
    python ydd2xml.py <in.ydd> [...] --selftest
"""
import argparse
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ydr2xml import Res, drawable_lines, esc

YDD_VERSION = 165       # measured: same RSC7 version as standalone ydr - 165 is the DRAWABLE
                        # FAMILY version, and the header at sys+0 (dictionary vs drawable) is what
                        # distinguishes the types, not the container version


def probe(path):
    """Dump the dictionary-header hypothesis against one real file. Prints evidence, not verdicts:
    the operator (or the harness) judges whether the fields hold before YDD_VERSION is pinned."""
    res = Res(path)
    name = os.path.basename(path)
    print(f"== {name}  version={res.version}  sys={len(res.sys):,}B gfx={len(res.gfx):,}B")
    for off in range(0x00, 0x48, 8):
        lo, hi = res.u32(off), res.u32(off + 4)
        print(f"   +0x{off:02x}: {lo:08x} {hi:08x}")
    cnt_pair = res.u32(0x28)
    n_lo, n_hi = cnt_pair & 0xFFFF, (cnt_pair >> 16) & 0xFFFF
    print(f"   count pair +0x28: lo={n_lo} hi={n_hi} {'AGREE' if n_lo == n_hi else 'DISAGREE'}")
    n = n_lo
    hbuf, ho = res.deref(res.u32(0x20), 4 * n)
    pbuf, po = res.deref(res.u32(0x30), 8 * n)
    if hbuf is None or pbuf is None or n == 0:
        print("   hash/pointer arrays DO NOT RESOLVE for this count")
        return
    hashes = list(struct.unpack_from("<%dI" % n, hbuf, ho))
    print(f"   hashes ascending: {hashes == sorted(hashes)}   first 3: "
          + " ".join(f"{h:08x}" for h in hashes[:3]))
    drawable_like = 0
    for i in range(n):
        dp = res.u32(po + i * 8)
        buf, o = res.deref(dp, 0xD0)
        if buf is None:
            continue
        # a gtaDrawable has its ShaderGroup pointer at +0x10 and model header at +0x50;
        # both tagged system pointers when the entry really is a drawable
        sg, mh = res.u32(o + 0x10), res.u32(o + 0x50)
        if (sg >> 28) == 5 and (mh >> 28) in (0, 5):
            drawable_like += 1
    print(f"   entries deref + look drawable-shaped: {drawable_like}/{n}")


def entry_offsets(res):
    """-> [(joaat, sys_offset)] for every dictionary entry."""
    cnt = res.u32(0x28) & 0xFFFF
    hbuf, ho = res.deref(res.u32(0x20), 4 * cnt)
    pbuf, po = res.deref(res.u32(0x30), 8 * cnt)
    if hbuf is None or pbuf is None:
        raise ValueError("dictionary hash/pointer arrays do not resolve")
    out = []
    for i in range(cnt):
        h = struct.unpack_from("<I", hbuf, ho + i * 4)[0]
        dp = res.u32(po + i * 8)
        buf, o = res.deref(dp, 0xD0)
        if buf is None:
            raise ValueError(f"entry {i} pointer does not resolve")
        out.append((h, o))
    return out


def to_xml(res, names=None):
    if YDD_VERSION is None:
        raise ValueError("ydd header not yet measured - run --probe and pin YDD_VERSION first")
    res.require_version(YDD_VERSION, "Legacy drawable dictionary")
    names = names or {}
    L = ['<?xml version="1.0" encoding="UTF-8"?>', "<DrawableDictionary>"]
    n_ok = 0
    for h, off in entry_offsets(res):
        nm = names.get(h) or "hash_%08X" % h
        body = drawable_lines(res, nm, base=off)
        L.append(" <Item>")
        L.extend(" " + ln for ln in body)
        L.append(" </Item>")
        n_ok += 1
    if n_ok == 0:
        raise ValueError("no dictionary entries decoded")
    L.append("</DrawableDictionary>")
    return "\n".join(L) + "\n", n_ok


def main():
    ap = argparse.ArgumentParser(prog="ydd2xml")
    ap.add_argument("files", nargs="*")
    ap.add_argument("--out")
    ap.add_argument("--probe", action="store_true", help="measure the header; convert nothing")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--project", help="filebase root - builds the joaat name table from its slots")
    a = ap.parse_args()
    if not a.files:
        ap.error("give at least one .ydd")
    if a.probe:
        for p in a.files:
            try:
                probe(p)
            except Exception as e:
                print(f"PROBE FAIL {os.path.basename(p)}: {type(e).__name__}: {e}")
        return 0
    names = {}
    if a.project:
        import meta2xml
        slots = [os.path.join(a.project, s) for s in sorted(os.listdir(a.project))
                 if os.path.isdir(os.path.join(a.project, s)) and s[:2].isdigit()]
        names = meta2xml.load_names(*slots)
    ok = fail = 0
    for p in a.files:
        stem = os.path.splitext(os.path.basename(p))[0]
        try:
            xml, n = to_xml(Res(p), names)
        except Exception as e:
            print(f"FAIL {os.path.basename(p)}: {type(e).__name__}: {e}")
            fail += 1
            continue
        if a.selftest:
            import xml.etree.ElementTree as ET
            root = ET.fromstring(xml)
            print(f"OK   {os.path.basename(p):<40} {n:3} drawables  "
                  f"{len(root.findall('./Item')):3} items  {len(xml):>10,} B")
        else:
            if not a.out:
                ap.error("--out is required unless --selftest/--probe")
            os.makedirs(a.out, exist_ok=True)
            open(os.path.join(a.out, stem + ".ydd.xml"), "w", encoding="utf-8",
                 newline="\n").write(xml)
            print(f"OK   {os.path.basename(p)} ({n} drawables)")
        ok += 1
    print(f"\n{ok} converted, {fail} failed")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
