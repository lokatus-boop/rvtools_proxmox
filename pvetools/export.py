"""Exportación del inventario a Excel (una hoja por pestaña) y CSV."""
from __future__ import annotations

import csv
import os

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from . import APP_NAME, __version__
from .branding import COMPANY, DISCLAIMER, asset_path
from .schema import FORMAT_VERSION, SCHEMA

HEADER_FILL = PatternFill("solid", fgColor="1F4E78")
HEADER_FONT = Font(bold=True, color="FFFFFF")
SEV_FILL = {"CRÍTICO": PatternFill("solid", fgColor="F8CBAD"),
            "AVISO": PatternFill("solid", fgColor="FFE699"),
            "INFO": PatternFill("solid", fgColor="DDEBF7")}


def columns(rows: list[dict], sheet: str | None = None) -> list[str]:
    """Columnas de una hoja: las del formato estable (schema.py) y, al final, cualquier extra."""
    cols: list[str] = list(SCHEMA.get(sheet, [])) if sheet else []
    for r in rows:
        for k in r:
            if k not in cols:
                cols.append(k)
    return cols


def to_xlsx(sheets: dict, path: str):
    wb = Workbook()
    _notice_sheet(wb.active)
    for name, rows in sheets.items():
        ws = wb.create_sheet(name[:31])
        cols = columns(rows, name)
        if not cols:
            ws.append(["(sin datos)"])
            continue
        ws.append(cols)
        for r in rows:
            ws.append([r.get(c) for c in cols])
        for cell in ws[1]:
            cell.fill, cell.font = HEADER_FILL, HEADER_FONT
            cell.alignment = Alignment(vertical="center")
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions
        for i, c in enumerate(cols, 1):
            width = max([len(str(c))] + [len(str(r.get(c) or "")) for r in rows[:500]])
            ws.column_dimensions[get_column_letter(i)].width = min(max(width + 2, 8), 60)
        if name == "vHealth" and "Severidad" in cols:
            sev_col = cols.index("Severidad") + 1
            for row in ws.iter_rows(min_row=2):
                fill = SEV_FILL.get(row[sev_col - 1].value)
                if fill:
                    for cell in row:
                        cell.fill = fill
    wb.save(path)
    return path


def _notice_sheet(ws):
    """Primera hoja: logo y aviso de uso."""
    import datetime as dt
    ws.title = "Aviso"
    ws.sheet_view.showGridLines = False
    ws.column_dimensions["A"].width = 120
    row = 1
    try:  # el logo necesita Pillow; si no está, se omite
        from openpyxl.drawing.image import Image as XLImage
        img = XLImage(asset_path("fsas_logo.png"))
        img.width, img.height = 260, 50
        ws.add_image(img, "A1")
        ws.row_dimensions[1].height = 45
        row = 3
    except Exception:  # noqa: BLE001
        pass
    ws.cell(row, 1, f"{APP_NAME} {__version__} — Inventario de Proxmox VE · {COMPANY}").font = Font(bold=True, size=14)
    ws.cell(row + 1, 1, f"Generado: {dt.datetime.now():%Y-%m-%d %H:%M:%S} · Versión de formato: {FORMAT_VERSION}").font = \
        Font(italic=True, color="666666")
    r = row + 3
    for line in DISCLAIMER.split("\n"):
        c = ws.cell(r, 1, line)
        c.alignment = Alignment(wrap_text=True, vertical="top")
        if line.isupper():
            c.font = Font(bold=True, color="1F4E78")
        r += 1


def to_csv(sheets: dict, folder: str, prefix: str = ""):
    os.makedirs(folder, exist_ok=True)
    paths = []
    for name, rows in sheets.items():
        p = os.path.join(folder, f"{prefix}{name}.csv")
        cols = columns(rows, name)
        # utf-8-sig + ';' para que Excel en español lo abra directamente
        with open(p, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=cols or ["(sin datos)"], delimiter=";")
            w.writeheader()
            w.writerows(rows)
        paths.append(p)
    p = os.path.join(folder, f"{prefix}LEEME_AVISO.txt")
    with open(p, "w", encoding="utf-8-sig") as f:
        f.write(f"{APP_NAME} {__version__} - {COMPANY}\n\n{DISCLAIMER}\n")
    paths.append(p)
    return paths
