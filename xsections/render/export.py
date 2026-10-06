"""Write the planned sheets to PDF (one file, one page per sheet), PNG or SVG (one file per sheet)."""
from __future__ import annotations

import os
from typing import List

import matplotlib
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.figure import Figure

from ..core.model import Plan, SectionError, SectionModel, Settings
from .figure import RC, draw_page
from .pdfprefs import add_print_prefs
from .scales import pretty_label

FORMATS = ("pdf", "png", "svg")
MAX_PNG_MEGAPIXELS = 300.0          # one Agg buffer is 4 bytes per pixel: 300 MP is 1.2 GB


def output_paths(path: str, fmt: str, count: int) -> List[str]:
    """PDF: [path]. PNG/SVG: [path] for one sheet, else path_sheet1.png ... path_sheetN.png."""
    base, ext = os.path.splitext(path)
    if ext.lower().lstrip(".") != fmt:
        if ext.lower().lstrip(".") in FORMATS:
            ext = "." + fmt                    # 'x.pdf' asked as png -> 'x.png'
        else:
            base, ext = path, "." + fmt        # no or unknown extension: append
    if fmt == "pdf" or count == 1:
        return [base + ext]
    return [f"{base}_sheet{i}{ext}" for i in range(1, count + 1)]


def png_megapixels(plan: Plan, dpi: int) -> float:
    return max((p.page_w * dpi) * (p.page_h * dpi) for p in plan.pages) / 1e6 if plan.pages else 0.0


def export(model: SectionModel, settings: Settings, plan: Plan, path: str, fmt: str = "pdf",
           dpi: int = 300) -> List[str]:
    """Write every sheet of `plan`; returns the files written.

    Raises SectionError when the plan does not fit (nothing is ever shrunk to fit), for an
    unknown format, or when a PNG sheet would exceed MAX_PNG_MEGAPIXELS.
    """
    fmt = (fmt or "pdf").lower().lstrip(".")
    if fmt not in FORMATS:
        raise SectionError(f"Unknown export format '{fmt}'. Use PDF, PNG or SVG.")
    if not plan.fits or not plan.pages:
        raise SectionError(plan.message or "The section does not fit the sheet, so nothing was exported.")
    dpi = int(dpi)
    if fmt == "png":
        if dpi <= 0:
            raise SectionError("The PNG resolution must be a positive number of dots per inch.")
        mp = png_megapixels(plan, dpi)
        if mp > MAX_PNG_MEGAPIXELS:
            p = plan.pages[0]
            raise SectionError(f"A {p.page_w:g} × {p.page_h:g} in sheet at {dpi} dpi is {mp:,.0f} megapixels "
                               f"(limit {MAX_PNG_MEGAPIXELS:,.0f}). Export PDF instead, or use a lower resolution.")
    outs = output_paths(path, fmt, len(plan.pages))
    folder = os.path.dirname(os.path.abspath(outs[0]))
    os.makedirs(folder, exist_ok=True)
    title = (f"Cross section {pretty_label(settings.start_label)}–{pretty_label(settings.end_label)}"
             + (f" · {settings.title}" if settings.title else ""))

    with matplotlib.rc_context(RC):
        if fmt == "pdf":
            with PdfPages(outs[0], metadata={"Title": title, "Creator": "XSections (QGIS plugin)"}) as pdf:
                for page in plan.pages:
                    fig = Figure(figsize=(page.page_w, page.page_h), dpi=72)
                    draw_page(fig, model, settings, plan, page)
                    pdf.savefig(fig, facecolor="white")
            add_print_prefs(outs[0])
            return outs
        for page, out in zip(plan.pages, outs):
            fig = Figure(figsize=(page.page_w, page.page_h), dpi=dpi if fmt == "png" else 72)
            draw_page(fig, model, settings, plan, page)
            if fmt == "png":
                fig.savefig(out, format="png", dpi=dpi, facecolor="white",
                            metadata={"Title": title, "Software": "XSections (QGIS plugin)"})
            else:
                fig.savefig(out, format="svg", facecolor="white", metadata={"Title": title})
    return outs
