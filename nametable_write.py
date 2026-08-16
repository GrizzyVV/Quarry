"""nametable_write - ROUND-TRIP WRITER for `X.datNNN.nametable`, the audio name tables that
ship BESIDE the `.rel` containers.

    original binary -> value model -> written back -> MUST reproduce the original bytes

229 files, 4,352,205 bytes, previously PASSTHROUGH - i.e. UNMEASURED, not passing.

=============================  WHAT THE FILE IS  =============================
A bare NUL-separated ASCII string blob. NO header, no count, no offset array - the census
(`tools/rel_census.py`) and a direct dump both show byte 0 is already the first character of the
first name. 133,651 strings over the 229 files; 224 of 229 end with a NUL, 5 do not, and 5
strings are empty.

⭐ IT IS THE `.rel` LANE'S NAME SOURCE, AND THAT IS MEASURED, NOT ASSUMED. An item record's
u24 `ntOffset` (record +0x01..+0x03) is a byte offset INTO THIS BLOB: take the NUL-terminated
string there, joaat it lowercased, and it equals the item's own index NameHash for
**91,355 / 91,355 items = 100.000%** across dat10/dat15/dat54/dat149/dat150/dat151, while the
same offsets read against the container's INLINE name table match **0 / 133,646**.
(`tools/rel_nametable_link.py`.) 84,502 distinct audio names fall out of that for free.

===========================  THE EPISTEMIC LIMIT, STATED  ===========================
⛔ BYTE IDENTITY IS A WEAK MEASURE ON A STRING TABLE and this docstring will not pretend
otherwise. `b'\\x00'.join(blob.split(b'\\x00'))` is an IDENTITY - it cannot fail - so a writer
built that way would report a self-fulfilling 100%. Three things make this one a model:
  1. every string is decoded to a Python `str` through STRICT ASCII and re-encoded from it, so a
     non-ASCII byte REFUSES rather than being carried;
  2. the separators are DERIVED, not copied - the image is zero-filled and each NUL is written
     from the model's own knowledge that strings are NUL-separated;
  3. `tools/rel_control.py` mutates one decoded string per file and DEMANDS the image move.
     A control that never fires proves nothing; this one fires on every file that holds a
     non-empty string.
The strong, independent pin on the CONTENT is the joaat cross-check above, which lives in the
`.rel` lane, not here.

ASCII output only.
"""
import os
import sys as _sys

_sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


class NametableError(Exception):
    """Outside the measured envelope. Refuse loudly; never half-read."""


class Nametable(object):
    def __init__(self, blob):
        b = bytes(blob)
        self.orig = b
        self.size = len(b)
        # ⭐ A ZERO-LENGTH .nametable IS A REAL FILE, NOT AN ERROR - 5 of the 229 are 0 bytes
        # (mplowrider2 / mpairraces / mpsmuggler speech + game tables). They are reported on
        # their own line rather than refused, because "the file is empty" and "the writer
        # failed" are different facts and blending them is how a lane gets credit it has not
        # earned. A 0-byte file also carries NO coverage figure: there is nothing to measure.
        self.empty_file = (self.size == 0)
        self.trailing_nul = b.endswith(b'\x00')
        parts = b.split(b'\x00') if self.size else []
        if self.trailing_nul:
            parts = parts[:-1]
        # STRICT ASCII: a byte outside 0x00..0x7F is NOT a name and must not be carried silently.
        self.names = []
        for i, s in enumerate(parts):
            try:
                self.names.append(s.decode('ascii'))
            except UnicodeDecodeError:
                raise NametableError('string %d is not ASCII (%r)' % (i, s[:24]))

    def write(self):
        img = bytearray(self.size)                  # ZERO-FILLED: unreached bytes stay LOUD
        at = 0
        for i, n in enumerate(self.names):
            e = n.encode('ascii')
            if at + len(e) > self.size:
                break
            img[at:at + len(e)] = e
            at += len(e)
            # the separator is DERIVED from the model (strings are NUL-separated), not copied.
            if i + 1 < len(self.names) or self.trailing_nul:
                if at < self.size:
                    img[at] = 0
                at += 1
        self.written = at
        return bytes(img)

    def unreached(self):
        got, orig = self.write(), self.orig
        n = min(len(got), len(orig))
        bad = [i for i in range(n) if got[i] != orig[i]]
        return len(bad), sum(1 for i in bad if orig[i] != 0)

    def regions(self):
        """(value, derived, zero_fill, carried) byte account.

        value   = the name characters, re-encoded from decoded `str`
        derived = the INTERIOR NUL separators, written from the model's own separation rule
        zero    = the FINAL NUL, see below
        carried = 0 - nothing in this file is copied

        ⛔ THE FINAL NUL IS NOT PINNED AND IS COUNTED AS ZERO-FILL, NOT AS DERIVED. The control
        `tools/rel_control.py` flips `trailing_nul` off and the image STILL MATCHES on 224 of 224
        files - because a byte the writer declines to write stays 0 in the zero-filled image and
        the original's last byte is 0 too. One byte per file, 224 of 4,352,205 = 0.0051% of the
        lane, and it is disclosed here rather than counted as understood. This is exactly the
        self-fulfilling-claim trap: byte identity cannot reject it, so it does not get credit.
        """
        chars = sum(len(n) for n in self.names)
        interior = (len(self.names) - 1) if self.names else 0
        return chars, interior, self.size - chars - interior, 0


def read_nametable(src):
    blob = bytes(src) if isinstance(src, (bytes, bytearray)) else open(src, 'rb').read()
    return Nametable(blob)
