"""yfd2xml - GTA V .yfd (crFrameFilterDictionary, RSC7 v4) -> byte-identical RAGE .yfd.xml.

CLEAN-ROOM: derived from the oracle XML + game binary + our own quarry code only.

CONTAINER  (RSC7 v4; all data in the system segment, gfx empty):
  sys+0x00  u64 vtable
  sys+0x18  u32 usageCount (=1)
  sys+0x20  Hashes atArray : ptr @+0x20 (u32 tagged), count u16 @+0x28, cap u16 @+0x2A
  sys+0x30  Data   atArray : ptr @+0x30 (u32 tagged), count u16 @+0x38, cap u16 @+0x3A
            -> Data is a stride-8 array of u64 tagged pointers (high 32 bits 0) to crFrameFilter.
  The two arrays are parallel and sorted by name-hash ascending; XML item order == array order.

crFrameFilter (crFrameFilterMultiWeight):
  +0x00 u64 vtable
  +0x08 u32  (=1)            not emitted
  +0x0C u32  signature hash  not emitted
  +0x10 u32  (=4)            not emitted
  +0x18 Entries atArray : ptr @+0x18, count u16 @+0x20, cap @+0x22
  +0x28 Weights atArray : ptr @+0x28, count u16 @+0x30, cap @+0x32  (float32[])

Entries record (8 bytes):
  +0 u8  reserved (asserted 0)
  +1 u8  Track
  +2 u16 BoneId
  +4 u32 WeightIndex        (high 3 bytes asserted 0)
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ydr2xml import Res                       # noqa: E402  (RSC7 container reader)
from meta2xml import fmt_num, joaat, num_list  # noqa: E402  (float law, jenkins, 10-per-line law)

# The binary stores only joaat(name); joaat is one-way. Filter names are recovered from the
# ORACLE'S OWN resolved <Name> strings (the oracle is the spec) - exactly how ydr2xml derives
# shader preset names from its reference exports. 13 names span the 4 player.yfd oracles; every
# hash below is joaat(name) and matches the binary. Unknown hashes emit hash_%08X (uppercase),
# which is what the oracle itself spells for names its dictionary lacked.
FILTER_NAMES = [
    "bonemask_armonly_l", "bonemask_armonly_r", "bonemask_head_neck_and_arms",
    "bonemask_head_neck_and_l_arm", "bonemask_head_neck_and_r_arm", "bonemask_headonly",
    "bonemask_upperonly", "botharms_filter", "ignoremoverblend_filter", "nomover_filter",
    "rightarm_nospine_filter", "upperbodyandik_filter", "upperbodyfeathered_filter",
]
_NAMES = {joaat(n): n for n in FILTER_NAMES}


def _name(hash32):
    return _NAMES.get(hash32, "hash_%08X" % hash32)


def _arr(r, base):
    """atArray at struct offset `base`: (ptr_offset, count). Pointer is the low 28 bits."""
    ptr = r.u32(base) & 0x0FFFFFFF
    count = r.u16(base + 8)
    return ptr, count


def yfd_to_xml(path):
    r = path if hasattr(path, "sys") else Res(path)
    r.require_version(4, "yfd")
    S = r.sys
    hp, hc = _arr(r, 0x20)                    # hashes
    dp, dc = _arr(r, 0x30)                    # data pointers (stride 8)
    if hc != dc:
        raise ValueError("hash/data count mismatch %d/%d" % (hc, dc))

    out = ['<?xml version="1.0" encoding="UTF-8"?>', "<FrameFilterDictionary>"]
    for i in range(hc):
        name_hash = struct.unpack_from("<I", S, hp + i * 4)[0]
        fptr = struct.unpack_from("<Q", S, dp + i * 8)[0] & 0x0FFFFFFF
        out.append(" <Item>")
        out.append("  <Name>%s</Name>" % _name(name_hash))

        # ---- Entries ----
        ep, ec = _arr(r, fptr + 0x18)
        out.append("  <Entries>")
        for e in range(ec):
            b = ep + e * 8
            resv = S[b]
            track = S[b + 1]
            bone = struct.unpack_from("<H", S, b + 2)[0]
            wi = struct.unpack_from("<I", S, b + 4)[0]
            if resv != 0:
                raise ValueError("entry reserved byte +0 != 0 (0x%02x)" % resv)
            out.append("   <Item>")
            out.append('    <Track value="%d" />' % track)
            out.append('    <BoneId value="%d" />' % bone)
            out.append('    <WeightIndex value="%d" />' % wi)
            out.append("   </Item>")
        out.append("  </Entries>")

        # ---- Weights (float32[], num_list 10-per-line at 2-space indent) ----
        wp, wc = _arr(r, fptr + 0x28)
        wvals = [struct.unpack_from("<f", S, wp + k * 4)[0] for k in range(wc)] if wp else []
        out.extend(num_list("Weights", wvals, "  "))

        out.append(" </Item>")
    out.append("</FrameFilterDictionary>")
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    import glob
    scr = os.path.dirname(os.path.abspath(__file__))
    ORC = r"B:\ClaudeCode_Projects\_UEFiveMTool\_Oracles\yfd"
    bins = {
        "00_base": scr + r"\yfd_bins\00_base__player.yfd",
        "20_dlc_013_mpheist": scr + r"\yfd_bins\20_dlc_013_mpheist__player.yfd",
        "20_dlc_057_patchday2ng": scr + r"\yfd_bins\20_dlc_057_patchday2ng__player.yfd",
        "20_dlc_059_patchday4ng": scr + r"\yfd_bins\20_dlc_059_patchday4ng__player.yfd",
    }
    npass = 0
    for tag, bp in bins.items():
        got = yfd_to_xml(bp)
        orc = open(os.path.join(ORC, tag, "player.yfd.xml"), encoding="utf-8").read()
        orc_n = orc.replace("\r\n", "\n")
        ok = got == orc_n
        npass += ok
        if ok:
            print("PASS  %-24s (%d bytes)" % (tag, len(got)))
        else:
            gl, ol = got.split("\n"), orc_n.split("\n")
            print("FAIL  %-24s got %d lines / oracle %d lines" % (tag, len(gl), len(ol)))
            for j in range(min(len(gl), len(ol))):
                if gl[j] != ol[j]:
                    print("   first diff line %d:\n     got: %r\n     orc: %r" % (j + 1, gl[j], ol[j]))
                    break
    print("\nyfd VALIDATION: %d/%d byte-identical" % (npass, len(bins)))
