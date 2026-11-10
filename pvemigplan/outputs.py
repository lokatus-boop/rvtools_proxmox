"""Generación de todos los entregables de un plan."""
from __future__ import annotations

import os


def generate(plan, folder, base="plan_migracion", xlsx=True, design=True, impl=True, charts=False, config_template=None):
    """Devuelve la lista de ficheros generados en «folder»."""
    os.makedirs(folder, exist_ok=True)
    out = []
    if xlsx:
        from .report_xlsx import to_xlsx
        out.append(to_xlsx(plan, os.path.join(folder, f"{base}.xlsx")))
    if design:
        from .report_docx import to_docx
        cdir = None
        if charts:
            cdir = os.path.join(folder, f"{base}_graficos")
            os.makedirs(cdir, exist_ok=True)
        out.append(to_docx(plan, os.path.join(folder, f"{base}_diseno_cliente.docx"), cdir))
    if impl:
        from .report_impl import to_impl_docx
        out.append(to_impl_docx(plan, os.path.join(folder, f"{base}_guia_implementacion.docx")))
    if config_template:
        from .config_sheet import fill
        out.append(fill(plan, config_template, os.path.join(folder, f"{base}_hoja_configuracion.xlsx")))
    return out
