"""Exportación del inventario a Excel (una hoja por pestaña) y CSV."""
from __future__ import annotations

import csv
import os

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from . import APP_NAME, __version__
from .branding import COMPANY, DISCLAIMER, asset_path
from .i18n import N_, _, cell_out, get_lang
from .schema import FORMAT_VERSION, SCHEMA
from .safefile import atomic_save, atomic_text

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


def _cell(sheet, col, row):
    """Valor de una celda en el idioma de exportación (vSource «Idioma» = idioma del fichero)."""
    if sheet == "vSource" and col == "Idioma":
        return get_lang()
    return cell_out(sheet, col, row.get(col))


def to_xlsx(sheets: dict, path: str):
    wb = Workbook()
    _notice_sheet(wb.active, is_anonymized(sheets))
    for name, rows in sheets.items():
        ws = wb.create_sheet(name[:31])
        cols = columns(rows, name)
        if not cols:
            ws.append([_("(sin datos)")])
            continue
        ws.append(headers(cols))
        for r in rows:
            ws.append([_cell(name, c, r) for c in cols])
        for cell in ws[1]:
            cell.fill, cell.font = HEADER_FILL, HEADER_FONT
            cell.alignment = Alignment(vertical="center")
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions
        for i, c in enumerate(cols, 1):
            width = max([len(_(c))] + [len(str(r.get(c) or "")) for r in rows[:500]])
            ws.column_dimensions[get_column_letter(i)].width = min(max(width + 2, 8), 60)
        if name == "vHealth" and "Severidad" in cols:
            for row, r in zip(ws.iter_rows(min_row=2), rows):
                fill = SEV_FILL.get(r.get("Severidad"))
                if fill:
                    for cell in row:
                        cell.fill = fill
    return atomic_save(path, wb.save)


ANON_NOTICE = N_("INVENTARIO ANONIMIZADO: los nombres de clústeres, nodos, VMs, almacenamientos, usuarios, dominios, etc. "
               "se han sustituido por seudónimos y las IPs/MACs están transformadas. La correspondencia con los "
               "valores reales solo está en el fichero de correspondencia que conserva el cliente.")


def headers(cols: list[str]) -> list[str]:
    """Cabeceras en el idioma activo (sin repetir: si dos traducciones coinciden, se deja el original)."""
    out, seen = [], set()
    for c in cols:
        h = _(c)
        if h in seen:
            h = c
        seen.add(h)
        out.append(h)
    return out


def is_anonymized(sheets: dict) -> bool:
    return any(str(r.get("Anonimizado") or "").startswith("Sí") for r in sheets.get("vSource", []))


def _notice_sheet(ws, anon: bool = False):
    """Primera hoja: logo y aviso de uso."""
    import datetime as dt
    ws.title = _("Aviso")[:31]
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
    ws.cell(row, 1, _("{app} {version} — Inventario de Proxmox VE · {company}", app=APP_NAME, version=__version__,
                      company=COMPANY)).font = Font(bold=True, size=14)
    ws.cell(row + 1, 1, _("Generado: {date} · Versión de formato: {fmt}", date=f"{dt.datetime.now():%Y-%m-%d %H:%M:%S}",
                          fmt=FORMAT_VERSION)).font = \
        Font(italic=True, color="666666")
    r = row + 3
    if anon:
        ws.cell(r, 1, _(ANON_NOTICE)).font = Font(bold=True, color="C00000")
        ws.cell(r, 1).alignment = Alignment(wrap_text=True, vertical="top")
        ws.row_dimensions[r].height = 45
        r += 2
    for line in _(DISCLAIMER).split("\n"):
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
        with atomic_text(p, encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(headers(cols) if cols else [_("(sin datos)")])
            for r in rows:
                w.writerow([_cell(name, c, r) for c in cols])
        paths.append(p)
    p = os.path.join(folder, f"{prefix}{_('LEEME_AVISO')}.txt")
    with atomic_text(p, encoding="utf-8-sig") as f:
        f.write(f"{APP_NAME} {__version__} - {COMPANY}\n\n")
        if is_anonymized(sheets):
            f.write(_(ANON_NOTICE) + "\n\n")
        f.write(_(DISCLAIMER) + "\n")
    paths.append(p)
    return paths
