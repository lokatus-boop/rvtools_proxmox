"""Línea de comandos: pvemigplan-cli inventario.xlsx [opciones]"""
from __future__ import annotations

import argparse
import json
import os
import sys

from . import APP_NAME, __version__
from .branding import COMPANY, SHORT_NOTICE
from .loader import InventoryError, format_warnings, load
from .planner import Plan, PlanError
from .scenario import STORAGE_TYPES, load as load_scenario, new, save as save_scenario


def build_parser():
    ap = argparse.ArgumentParser(prog="pvemigplan-cli", description=f"{APP_NAME} {__version__} · {COMPANY}. {SHORT_NOTICE}")
    ap.add_argument("inventario", nargs="+", help="Excel de PVE Inventory, carpeta con los CSV o un CSV (se pueden indicar varios)")
    ap.add_argument("-e", "--escenario", help="JSON del escenario (parámetros y hardware); se crea uno de ejemplo con --guardar-escenario")
    ap.add_argument("-o", "--salida", default=".", help="Carpeta de salida (por defecto, la actual)")
    ap.add_argument("-n", "--nombre", default="plan_migracion", help="Nombre base de los ficheros")
    ap.add_argument("--cliente", help="Nombre del cliente")
    ap.add_argument("--modo", choices=["aconsejar", "hardware"], help="aconsejar hardware o validar el del escenario")
    ap.add_argument("--almacenamiento", choices=list(STORAGE_TYPES), help="Tipo de almacenamiento de destino")
    ap.add_argument("--pve", help="Versión de Proxmox VE de destino (p. ej. 9.1)")
    ap.add_argument("--sin-pbs", action="store_true", help="No incluir Proxmox Backup Server")
    ap.add_argument("--catalogo", help="JSON con un catálogo de hardware propio")
    ap.add_argument("--sin-word", action="store_true", help="No generar el documento Word")
    ap.add_argument("--graficos", action="store_true", help="Guardar también los gráficos PNG")
    ap.add_argument("--guardar-escenario", metavar="RUTA", help="Guarda el escenario usado (útil como plantilla)")
    ap.add_argument("-q", "--quiet", action="store_true")
    ap.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")
    return ap


def main(argv=None):
    a = build_parser().parse_args(argv)
    sc = load_scenario(a.escenario) if a.escenario else new()
    if a.cliente:
        sc["cliente"] = a.cliente
    if a.modo:
        sc["modo"] = a.modo
    if a.almacenamiento:
        sc["almacenamiento"]["tipo"] = a.almacenamiento
    if a.pve:
        sc["pve_version"] = a.pve
    if a.sin_pbs:
        sc["pbs"]["incluir"] = False
    try:
        sheets = load(a.inventario)
        for w in format_warnings(sheets):
            print("Aviso:", w, file=sys.stderr)
        plan = Plan(sheets, sc, a.catalogo)
    except (InventoryError, PlanError, OSError, json.JSONDecodeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    os.makedirs(a.salida, exist_ok=True)
    from .report_xlsx import to_xlsx
    out = [to_xlsx(plan, os.path.join(a.salida, a.nombre + ".xlsx"))]
    if not a.sin_word:
        from .report_docx import to_docx
        cdir = os.path.join(a.salida, a.nombre + "_graficos") if a.graficos else None
        if cdir:
            os.makedirs(cdir, exist_ok=True)
        out.append(to_docx(plan, os.path.join(a.salida, a.nombre + ".docx"), cdir))
    if a.guardar_escenario:
        save_scenario(sc, a.guardar_escenario)
        out.append(a.guardar_escenario)
    if not a.quiet:
        print(plan.text_summary())
        print()
        for p in out:
            print("Generado:", p)
    return 0 if plan.eval["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
