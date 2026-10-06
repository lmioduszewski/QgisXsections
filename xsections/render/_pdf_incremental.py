"""Print preferences for a PDF without third-party libraries, written as an incremental update.

The original bytes stay exactly as they are. A new revision of the document catalog, with

    /ViewerPreferences << /PrintScaling /None /PickTrayByPDFSize true >>

merged into any preferences already there, is appended together with a cross-reference section
for it, the way PDF editors save changes. Files older than PDF 1.7 also get the catalog entry
/Version /1.7 (PickTrayByPDFSize is PDF 1.7).

Reads classic xref tables, xref streams (Flate, PNG predictors), hybrid files and catalogs stored
in object streams. The appended section is of the same kind as the file's newest one: Ghostscript
refuses a classic-table file updated with an xref stream. Encrypted files are refused.

Used by pdfprefs.add_print_prefs when pypdf is not installed.
"""
from __future__ import annotations

import re
import zlib
from typing import Dict, List, Optional, Tuple

_WS = b" \t\r\n\f\x00"
_DELIM = b"()<>[]{}/%"
_REF_TAIL = re.compile(rb"\s*(\d+)\s+R(?![^\s()<>\[\]{}/%])")    # "0 R" after an object number
_OBJ_HEADER = re.compile(rb"(\d+)\s+(\d+)\s+obj")
_SUBSECTION = re.compile(rb"(\d+)\s+(\d+)")
_XREF_ROW = re.compile(rb"(\d{10})\s(\d{5})\s([nf])")

Entries = List[Tuple[bytes, bytes]]      # a dictionary as (key, raw value bytes), in file order

PREFS = [(b"/PrintScaling", b"/None"), (b"/PickTrayByPDFSize", b"true")]
NEEDS_VERSION = (1, 7)


class PdfError(ValueError):
    """A file this module cannot update: malformed, encrypted, or using an unsupported filter."""


# ------------------------------------------------------------------------------------ lexer
def _skip_ws(b: bytes, i: int) -> int:
    n = len(b)
    while i < n:
        if b[i] in _WS:
            i += 1
        elif b[i] == 0x25:                                   # '%' comment, to the end of the line
            while i < n and b[i] not in b"\r\n":
                i += 1
        else:
            break
    return i


def _end_of_token(b: bytes, i: int) -> int:
    n = len(b)
    while i < n and b[i] not in _WS and b[i] not in _DELIM:
        i += 1
    return i


def _scan(b: bytes, i: int) -> int:
    """Index just past the object that starts at b[i] (i is at a non-blank byte)."""
    if i >= len(b):
        raise PdfError("unexpected end of data")
    if b.startswith(b"<<", i):
        return _dict_entries(b, i)[1]
    c = b[i:i + 1]
    if c == b"[":
        i += 1
        while True:
            i = _skip_ws(b, i)
            if b[i:i + 1] == b"]":
                return i + 1
            i = _scan(b, i)
    if c == b"(":
        depth, i, n = 1, i + 1, len(b)
        while depth:
            if i >= n:
                raise PdfError("unterminated string")
            if b[i] == 0x5C:                                 # backslash escapes the next byte
                i += 2
                continue
            if b[i] == 0x28:                                 # nested '(' and ')' must balance
                depth += 1
            elif b[i] == 0x29:
                depth -= 1
            i += 1
        return i
    if c == b"<":
        end = b.find(b">", i)
        if end < 0:
            raise PdfError("unterminated hex string")
        return end + 1
    if c == b"/":
        return _end_of_token(b, i + 1)
    j = _end_of_token(b, i)                                  # number, true, false, null or "n g R"
    if j == i:
        raise PdfError(f"unexpected {c!r} at byte {i}")
    if b[i:j].isdigit():
        m = _REF_TAIL.match(b, j)
        if m:
            return m.end()
    return j


def _dict_entries(b: bytes, i: int) -> Tuple[Entries, int]:
    """b[i:] starts with '<<'. Returns ([(key, value bytes)], index just past '>>')."""
    if not b.startswith(b"<<", i):
        raise PdfError(f"expected a dictionary at byte {i}")
    i += 2
    out: Entries = []
    while True:
        i = _skip_ws(b, i)
        if b.startswith(b">>", i):
            return out, i + 2
        if b[i:i + 1] != b"/":
            raise PdfError(f"bad dictionary key at byte {i}")
        k_end = _end_of_token(b, i + 1)
        v0 = _skip_ws(b, k_end)
        v1 = _scan(b, v0)
        out.append((b[i:k_end], b[v0:v1]))
        i = v1


def _get(entries: Entries, key: bytes, default: Optional[bytes] = None) -> Optional[bytes]:
    for k, v in entries:
        if k == key:
            return v
    return default


def _ref(value: Optional[bytes]) -> Optional[Tuple[int, int]]:
    m = re.fullmatch(rb"(\d+)\s+(\d+)\s+R", value.strip()) if value is not None else None
    return (int(m.group(1)), int(m.group(2))) if m else None


def _ints(value: bytes) -> List[int]:
    return [int(x) for x in re.findall(rb"-?\d+", value)]


def _build_dict(entries: Entries) -> bytes:
    return b"<<" + b"".join(b"\n" + k + b" " + v for k, v in entries) + b"\n>>"


# ------------------------------------------------------------------------------------ streams
def _png_unpredict(data: bytes, columns: int) -> bytes:
    """Undo PNG predictors (one filter-type byte per row), as used by xref streams."""
    row = columns + 1
    prev = bytearray(columns)
    out = bytearray()
    for r in range(0, len(data), row):
        kind, cur = data[r], bytearray(data[r + 1:r + row])
        for x in range(len(cur)):
            a = cur[x - 1] if x else 0
            up = prev[x]
            c = prev[x - 1] if x else 0
            if kind == 1:
                cur[x] = (cur[x] + a) & 255
            elif kind == 2:
                cur[x] = (cur[x] + up) & 255
            elif kind == 3:
                cur[x] = (cur[x] + ((a + up) >> 1)) & 255
            elif kind == 4:
                p = a + up - c
                pa, pb, pc = abs(p - a), abs(p - up), abs(p - c)
                cur[x] = (cur[x] + (a if pa <= pb and pa <= pc else up if pb <= pc else c)) & 255
        out += cur
        prev = cur
    return bytes(out)


class _Pdf:
    """Just enough of a PDF reader to find the newest catalog and its cross-reference data."""

    def __init__(self, data: bytes):
        self.b = data
        m = re.match(rb"%PDF-(\d)\.(\d)", data)
        if not m:
            raise PdfError("not a PDF")
        self.header_version = (int(m.group(1)), int(m.group(2)))
        m = re.match(rb"startxref\s+(\d+)", data[data.rfind(b"startxref"):])
        if not m:
            raise PdfError("no startxref")
        self.startxref = int(m.group(1))
        self.xref: Dict[int, Tuple[str, int, int]] = {}   # num -> ('n', offset, gen) | ('o', objstm, index)
        self.trailer: Optional[Entries] = None             # the newest trailer
        self.newest_is_stream = False
        self._read_chain(self.startxref)

    def _read_chain(self, off: Optional[int]) -> None:
        seen = set()
        while off is not None and off not in seen:
            seen.add(off)
            i = _skip_ws(self.b, off)
            if self.b.startswith(b"xref", i):
                entries, trailer = self._classic(i)
                is_stream = False
            else:
                entries, trailer = self._xref_stream(i)
                is_stream = True
            if self.trailer is None:
                self.trailer, self.newest_is_stream = trailer, is_stream
            for k, v in entries.items():                      # newer sections win
                self.xref.setdefault(k, v)
            xs = _get(trailer, b"/XRefStm")                   # hybrid file: a stream adds entries
            if xs is not None:
                more, _ = self._xref_stream(_skip_ws(self.b, int(xs)))
                for k, v in more.items():
                    self.xref.setdefault(k, v)
            prev = _get(trailer, b"/Prev")
            off = int(prev) if prev is not None else None
        if self.trailer is None:
            raise PdfError("no cross-reference data")

    def _classic(self, i: int):
        b = self.b
        i = _skip_ws(b, i + 4)
        entries = {}
        while not b.startswith(b"trailer", i):
            m = _SUBSECTION.match(b, i)
            if not m:
                raise PdfError(f"bad xref subsection at byte {i}")
            start, count = int(m.group(1)), int(m.group(2))
            i = _skip_ws(b, m.end())
            for k in range(count):
                row = _XREF_ROW.match(b, i)
                if not row:
                    raise PdfError(f"bad xref entry at byte {i}")
                if row.group(3) == b"n":
                    entries.setdefault(start + k, ("n", int(row.group(1)), int(row.group(2))))
                i = _skip_ws(b, row.end())
        trailer, _ = _dict_entries(b, _skip_ws(b, i + 7))
        return entries, trailer

    def _stream_at(self, i: int):
        """The stream object at offset i: (dictionary entries, decoded bytes)."""
        b = self.b
        m = _OBJ_HEADER.match(b, i)
        if not m:
            raise PdfError(f"no object at byte {i}")
        ent, j = _dict_entries(b, _skip_ws(b, m.end()))
        j = _skip_ws(b, j)
        if not b.startswith(b"stream", j):
            raise PdfError(f"no stream at byte {j}")
        j += 6
        j += 2 if b[j:j + 2] == b"\r\n" else 1
        length = _get(ent, b"/Length", b"")
        r = _ref(length)
        n = int(self.object_bytes(r[0]).strip()) if r else int(length)
        raw = b[j:j + n]
        filters = re.findall(rb"/(\w+)", _get(ent, b"/Filter", b""))
        if filters == [b"FlateDecode"]:
            raw = zlib.decompress(raw)
        elif filters:
            raise PdfError(f"unsupported stream filter {filters}")
        parms = _get(ent, b"/DecodeParms", b"").strip()
        if parms.startswith(b"["):
            parms = parms[1:-1].strip()
        if parms.startswith(b"<<"):
            pe, _ = _dict_entries(parms, 0)
            if int(_get(pe, b"/Predictor", b"1")) >= 10:
                raw = _png_unpredict(raw, int(_get(pe, b"/Columns", b"1")))
        return ent, raw

    def _xref_stream(self, i: int):
        ent, data = self._stream_at(i)
        w = _ints(_get(ent, b"/W", b""))
        if len(w) != 3:
            raise PdfError("bad /W in xref stream")
        size = int(_get(ent, b"/Size"))
        index = _ints(_get(ent, b"/Index", b"[0 %d]" % size))
        rec = sum(w)
        entries, p = {}, 0

        def field(bs: bytes, default: int) -> int:
            return int.from_bytes(bs, "big") if bs else default

        for start, count in zip(index[0::2], index[1::2]):
            for k in range(count):
                r = data[p:p + rec]
                p += rec
                kind = field(r[:w[0]], 1)
                f2 = field(r[w[0]:w[0] + w[1]], 0)
                f3 = field(r[w[0] + w[1]:], 0)
                if kind == 1:
                    entries.setdefault(start + k, ("n", f2, f3))
                elif kind == 2:
                    entries.setdefault(start + k, ("o", f2, f3))
        return entries, ent

    def object_bytes(self, num: int) -> bytes:
        """The raw bytes of object `num`'s value (from the file, or from its object stream)."""
        e = self.xref.get(num)
        if e is None:
            raise PdfError(f"object {num} is not in the cross-reference data")
        if e[0] == "n":
            m = _OBJ_HEADER.match(self.b, _skip_ws(self.b, e[1]))
            if not m or int(m.group(1)) != num:
                raise PdfError(f"the xref offset of object {num} is wrong")
            v0 = _skip_ws(self.b, m.end())
            return self.b[v0:_scan(self.b, v0)]
        stm = self.xref.get(e[1])
        if stm is None or stm[0] != "n":
            raise PdfError(f"object stream {e[1]} not found")
        ent, data = self._stream_at(_skip_ws(self.b, stm[1]))
        n, first = int(_get(ent, b"/N")), int(_get(ent, b"/First"))
        nums = _ints(data[:first])
        for k in range(n):
            if nums[2 * k] == num:
                v0 = _skip_ws(data, first + nums[2 * k + 1])
                return data[v0:_scan(data, v0)]
        raise PdfError(f"object {num} is not in object stream {e[1]}")

    def catalog(self) -> Tuple[Tuple[int, int], Entries]:
        root = _ref(_get(self.trailer, b"/Root"))
        if root is None:
            raise PdfError("no /Root in the trailer")
        cat, _ = _dict_entries(self.object_bytes(root[0]).strip(), 0)
        return root, cat

    def viewer_prefs(self, cat: Entries) -> Entries:
        vp = _get(cat, b"/ViewerPreferences")
        if vp is None:
            return []
        r = _ref(vp)
        return _dict_entries((self.object_bytes(r[0]) if r else vp).strip(), 0)[0]


# ------------------------------------------------------------------------------------ public
def append_print_prefs(data: bytes) -> bytes:
    """`data` plus an incremental update that sets the print preferences (see the module doc).

    Raises PdfError for a file it cannot update; the caller keeps the original then.
    """
    pdf = _Pdf(data)
    tr = pdf.trailer
    if _get(tr, b"/Encrypt") is not None:
        raise PdfError("encrypted PDF")
    root, cat = pdf.catalog()
    new_keys = dict(PREFS)
    vp = [(k, v) for k, v in pdf.viewer_prefs(cat) if k not in new_keys] + PREFS

    version = pdf.header_version
    m = re.match(rb"/(\d)\.(\d)", (_get(cat, b"/Version") or b"").strip())
    if m:
        version = max(version, (int(m.group(1)), int(m.group(2))))
    cat = [(k, v) for k, v in cat if k != b"/ViewerPreferences"] + [(b"/ViewerPreferences", _build_dict(vp))]
    if version < NEEDS_VERSION:
        cat = [(k, v) for k, v in cat if k != b"/Version"] + [(b"/Version", b"/%d.%d" % NEEDS_VERSION)]

    entry = pdf.xref[root[0]]
    gen = entry[2] if entry[0] == "n" else 0
    out = bytearray(data)
    if not out.endswith(b"\n"):
        out += b"\n"
    cat_off = len(out)
    out += b"%d %d obj\n" % (root[0], gen) + _build_dict(cat) + b"\nendobj\n"
    stream_keys = (b"/Prev", b"/XRefStm", b"/Size", b"/Type", b"/W", b"/Index", b"/Length", b"/Filter",
                   b"/DecodeParms", b"/F", b"/FFilter", b"/FDecodeParms", b"/DL")
    keep = [(k, v) for k, v in tr if k not in stream_keys]
    size = int(_get(tr, b"/Size"))
    xref_off = len(out)
    if not pdf.newest_is_stream:                              # classic xref section and trailer
        out += b"xref\n0 1\n0000000000 65535 f \n%d 1\n%010d %05d n \n" % (root[0], cat_off, gen)
        out += b"trailer\n" + _build_dict(keep + [(b"/Size", b"%d" % size), (b"/Prev", b"%d" % pdf.startxref)])
        out += b"\nstartxref\n%d\n%%%%EOF\n" % xref_off
    else:                                                     # xref stream, one new object: itself
        num = size
        rows = (b"\x01" + cat_off.to_bytes(4, "big") + gen.to_bytes(2, "big")
                + b"\x01" + xref_off.to_bytes(4, "big") + (0).to_bytes(2, "big"))
        d = keep + [(b"/Type", b"/XRef"), (b"/Size", b"%d" % (num + 1)), (b"/Prev", b"%d" % pdf.startxref),
                    (b"/W", b"[1 4 2]"), (b"/Index", b"[%d 1 %d 1]" % (root[0], num)),
                    (b"/Length", b"%d" % len(rows))]
        out += b"%d 0 obj\n" % num + _build_dict(d) + b"\nstream\n" + rows + b"\nendstream\nendobj\n"
        out += b"startxref\n%d\n%%%%EOF\n" % xref_off
    return bytes(out)


def read_viewer_prefs(data: bytes) -> Dict[str, str]:
    """The newest catalog's /ViewerPreferences as {'/Key': 'raw value'}; {} when it has none."""
    pdf = _Pdf(data)
    _, cat = pdf.catalog()
    return {k.decode("latin-1"): v.decode("latin-1") for k, v in pdf.viewer_prefs(cat)}
