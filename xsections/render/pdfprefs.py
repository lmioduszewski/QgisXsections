"""Ask PDF viewers to default the print dialog to 'Actual size'.

Adds  /ViewerPreferences << /PrintScaling /None /PickTrayByPDFSize true >>  to the catalog
(and /Version /1.7, since PickTrayByPDFSize is PDF 1.7).

With pypdf (it ships with QGIS on Windows): a FULL rewrite (PdfWriter(clone_from=...)). pypdf's
incremental mode is avoided on purpose: it appends an xref stream to classic-xref files, which
Ghostscript then refuses. Without pypdf: our own incremental update (_pdf_incremental), which keeps
the original bytes and appends a section of the same xref kind. pypdf is imported only when used.
"""
from __future__ import annotations

import io
import os
import tempfile
from typing import Optional

from ._pdf_incremental import append_print_prefs, read_viewer_prefs


def add_print_prefs(path: str) -> bool:
    """Rewrite `path` in place with print preferences.

    True when written. False, with the file left exactly as it was, when the PDF is encrypted or
    cannot be parsed. Only file errors (reading or replacing `path`) raise.
    """
    with open(path, "rb") as fh:
        data = fh.read()
    try:
        new = _with_prefs(data)
    except Exception:                    # a PDF we cannot handle is still a valid, to-scale PDF
        return False
    if new is None:
        return False
    folder = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(prefix=".xsec_", suffix=".pdf", dir=folder)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(new)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
    return True


def _with_prefs(data: bytes) -> Optional[bytes]:
    """The new file contents; None for an encrypted PDF. Raises for a PDF that cannot be parsed."""
    try:
        from pypdf import PdfReader, PdfWriter
        from pypdf.generic import BooleanObject, DictionaryObject, NameObject
    except ImportError:
        new = append_print_prefs(data)
        if read_viewer_prefs(new).get("/PrintScaling") != "/None":     # read our update back
            raise ValueError("the print preferences did not read back")
        return new
    reader = PdfReader(io.BytesIO(data))
    if reader.is_encrypted:
        return None
    writer = PdfWriter(clone_from=reader)
    root = writer.root_object
    vp = root.get("/ViewerPreferences")
    vp = vp.get_object() if vp is not None else DictionaryObject()
    vp[NameObject("/PrintScaling")] = NameObject("/None")
    vp[NameObject("/PickTrayByPDFSize")] = BooleanObject(True)
    root[NameObject("/ViewerPreferences")] = vp
    header = writer.pdf_header.decode("latin-1") if isinstance(writer.pdf_header, bytes) else str(writer.pdf_header)
    if header < "%PDF-1.7":
        root[NameObject("/Version")] = NameObject("/1.7")
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def read_print_prefs(path: str) -> dict:
    """The catalog's /ViewerPreferences as a plain dict (for checks and tests). Needs pypdf."""
    from pypdf import PdfReader
    from pypdf.generic import BooleanObject
    root = PdfReader(path).trailer["/Root"].get_object()
    vp = root.get("/ViewerPreferences")
    if vp is None:
        return {}
    return {str(k): (bool(v.value) if isinstance(v, BooleanObject) else str(v)) for k, v in vp.get_object().items()}
