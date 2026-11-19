"""Lectura del inventario exportado por PVE Inventory (Excel o CSV).

Se aceptan uno o varios orígenes (por ejemplo, un Excel por clúster): las hojas se concatenan.
"""
from __future__ import annotations

import csv
import glob
import os

from pvetools.i18n import _, data_in, guess_lang, rows_in
from pvetools.schema import FORMAT_VERSION, SCHEMA

REQUIRED = ("vInfo",)
USEFUL = ("vInfo", "vDisk", "vNetwork", "vHost", "vDatastore", "vBridge", "vCluster")


class InventoryError(Exception):
    pass


def num(v, default=None):
    """Convierte a número los valores leídos de CSV/Excel ('4', '32.0', '1.234,5', '')."""
    if v is None or v == "":
        return default
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, (int, float)):
        return v
    s = str(v).strip().replace(" ", "")
    if not s:
        return default
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        pass
    if "," in s:  # formato español
        try:
            return float(s.replace(".", "").replace(",", "."))
        except ValueError:
            pass
    return default


def yes(v) -> bool:
    return str(v or "").strip().lower() in ("sí", "si", "yes", "true", "1", "ja", "oui", "sim", "sì")


def _clean(v):
    if isinstance(v, str):
        v = v.strip()
        return v if v != "" else None
    return v


def read_xlsx(path: str) -> dict:
    import zipfile
    from openpyxl import load_workbook
    try:
        wb = load_workbook(path, read_only=True, data_only=True)
    except (zipfile.BadZipFile, OSError, KeyError) as e:
        with open(path, "rb") as f:
            head = f.read(4096)
        why = (_("está vacío (solo contiene ceros): no llegó a guardarse bien o se dañó al copiarlo/sincronizarlo")
               if not head.strip(b"\0") else _("no es un Excel válido o está dañado"))
        raise InventoryError(_("{basename} {why}. Vuelve a exportarlo desde PVE Inventory. ({e})", basename=os.path.basename(path), why=why, e=e)) from e
    sheets = {}
    for ws in wb.worksheets:
        if ws.title not in SCHEMA:
            continue
        rows = ws.iter_rows(values_only=True)
        try:
            header = [str(h).strip() if h is not None else "" for h in next(rows)]
        except StopIteration:
            sheets[ws.title] = []
            continue
        if header and data_in(header[0]) == "(sin datos)":
            sheets[ws.title] = []
            continue
        data = []
        for row in rows:
            if row is None or all(c is None or c == "" for c in row):
                continue
            data.append({h: _clean(c) for h, c in zip(header, row) if h})
        sheets[ws.title] = data
    wb.close()
    return _normalize(sheets)


def read_csv_folder(folder: str) -> dict:
    sheets = {}
    for p in glob.glob(os.path.join(folder, "*.csv")):
        base = os.path.splitext(os.path.basename(p))[0]
        # admite prefijos (p. ej. "cliente_vInfo.csv")
        name = next((s for s in SCHEMA if base == s or base.endswith("_" + s) or base.endswith("-" + s)), None)
        if not name:
            continue
        with open(p, encoding="utf-8-sig", newline="") as f:
            sample = f.read(4096)
            f.seek(0)
            delim = ";" if sample.count(";") >= sample.count(",") else ","
            rows = [{k.strip(): _clean(v) for k, v in r.items() if k} for r in csv.DictReader(f, delimiter=delim)]
        if rows and len(rows[0]) == 1 and data_in(list(rows[0].keys())[0]) == "(sin datos)":
            rows = []
        sheets.setdefault(name, []).extend(rows)
    return _normalize(sheets)


def _normalize(sheets: dict) -> dict:
    """Un export en inglés, alemán, francés, portugués o italiano se pasa a la forma interna (castellano)."""
    lang = guess_lang({h for rows in sheets.values() for h in (rows[0].keys() if rows else ())})
    return {k: rows_in(k, v, lang) for k, v in sheets.items()}


def load(paths) -> dict:
    """Carga uno o varios Excel / carpetas CSV / ficheros CSV y devuelve {hoja: [filas]}."""
    if isinstance(paths, str):
        paths = [paths]
    merged: dict = {}
    for p in paths:
        if os.path.isdir(p):
            sh = read_csv_folder(p)
        elif p.lower().endswith((".xlsx", ".xlsm")):
            sh = read_xlsx(p)
        elif p.lower().endswith(".csv"):
            sh = read_csv_folder(os.path.dirname(os.path.abspath(p)))
        else:
            raise InventoryError(_("Formato no reconocido: {p} (usa el Excel o la carpeta de CSV de PVE Inventory)", p=p))
        if not sh:
            raise InventoryError(_("{basename} no contiene hojas de PVE Inventory", basename=os.path.basename(p)))
        for k, v in sh.items():
            merged.setdefault(k, []).extend(v)
    missing = [s for s in REQUIRED if s not in merged]
    if missing:
        raise InventoryError(_("Falta la hoja {sheets}: ¿es un export de PVE Inventory?", sheets=", ".join(missing)))
    for s in SCHEMA:
        merged.setdefault(s, [])
    _dedupe(merged)
    return merged


def _dedupe(sheets: dict):
    """Si se cargó dos veces el mismo clúster, deja una sola fila por VM y por nodo."""
    seen, out = set(), []
    for r in sheets["vInfo"]:
        k = (r.get("Clúster"), str(r.get("VMID")))
        if k not in seen:
            seen.add(k)
            out.append(r)
    sheets["vInfo"] = out
    seen, out = set(), []
    for r in sheets["vHost"]:
        k = (r.get("Clúster"), r.get("Nodo"))
        if k not in seen:
            seen.add(k)
            out.append(r)
    sheets["vHost"] = out


def format_warnings(sheets: dict) -> list[str]:
    """Avisos sobre la versión de formato o columnas que faltan (no bloquean)."""
    warns = []
    versions = {str(r.get("Versión formato")) for r in sheets.get("vSource", []) if r.get("Versión formato")}
    if versions and versions != {str(FORMAT_VERSION)}:
        warns.append(_("El inventario usa la versión de formato {versions} y esta herramienta espera la {FORMAT_VERSION}: revisa los resultados.", versions=', '.join(sorted(versions)), FORMAT_VERSION=FORMAT_VERSION))
    anon = {str(r.get("Anonimizado") or "") for r in sheets.get("vSource", []) if r.get("Anonimizado")}
    if any(a.startswith("Sí") for a in anon):
        warns.append(_("Inventario anonimizado: los nombres (clústeres, nodos, VMs, almacenamientos…) son seudónimos y las "
                     "IPs están transformadas. El cálculo no cambia; los documentos mostrarán los seudónimos. El cliente "
                     "puede revertirlos con su fichero de correspondencia (PVE Inventory → «Revertir anonimización»)."))
    for s in USEFUL:
        rows = sheets.get(s) or []
        if not rows:
            if s != "vInfo":
                warns.append(_("La hoja {s} está vacía o no existe: parte del análisis será menos preciso.", s=s))
            continue
        cols = set(rows[0].keys())
        miss = [c for c in SCHEMA[s] if c not in cols]
        if miss:
            warns.append(_("En {s} faltan columnas: {miss}", s=s, miss=', '.join(miss[:6]) + ('…' if len(miss) > 6 else '')))
    return warns
