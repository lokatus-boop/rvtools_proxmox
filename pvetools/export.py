"""Exportación del inventario a Excel (una hoja por pestaña) y CSV."""
from __future__ import annotations

import csv
import os

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

HEADER_FILL = PatternFill("solid", fgColor="1F4E78")
HEADER_FONT = Font(bold=True, color="FFFFFF")
SEV_FILL = {"CRÍTICO": PatternFill("solid", fgColor="F8CBAD"),
            "AVISO": PatternFill("solid", fgColor="FFE699"),
            "INFO": PatternFill("solid", fgColor="DDEBF7")}


def columns(rows: list[dict]) -> list[str]:
    cols: list[str] = []
    for r in rows:
        for k in r:
            if k not in cols:
                cols.append(k)
    return cols


def to_xlsx(sheets: dict, path: str):
    wb = Workbook()
    wb.remove(wb.active)
    for name, rows in sheets.items():
        ws = wb.create_sheet(name[:31])
        cols = columns(rows)
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


def to_csv(sheets: dict, folder: str, prefix: str = ""):
    os.makedirs(folder, exist_ok=True)
    paths = []
    for name, rows in sheets.items():
        p = os.path.join(folder, f"{prefix}{name}.csv")
        cols = columns(rows)
        # utf-8-sig + ';' para que Excel en español lo abra directamente
        with open(p, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=cols or ["(sin datos)"], delimiter=";")
            w.writeheader()
            w.writerows(rows)
        paths.append(p)
    return paths
