"""Informe de solo análisis de la infraestructura actual (Word con gráficos + Excel con los datos).

No contiene propuesta de migración, hardware de destino ni olas: solo lo encontrado en el inventario.
"""
from __future__ import annotations

from pvetools.i18n import _

import os

from . import APP_NAME, __version__
from .assessment import CRIT, INFO, WARN, Assessment
from .branding import COMPANY, DISCLAIMER, asset_path
from pvetools.safefile import atomic_save


def to_assessment_docx(a: Assessment, path, charts_dir=None):
    from .report_assessment_docx import AssessmentDoc
    return AssessmentDoc(a).build(path, charts_dir)


def to_assessment_xlsx(a: Assessment, path):
    from openpyxl import Workbook
    from openpyxl.styles import Font

    from .report_xlsx import _kv, _table
    an = a.an
    t = an.totals()
    wb = Workbook()
    ws = wb.active
    ws.title = _("Aviso")
    ws.sheet_view.showGridLines = False
    ws.column_dimensions["A"].width = 120
    row = 1
    try:
        from openpyxl.drawing.image import Image as XLImage
        img = XLImage(asset_path("fsas_logo.png"))
        img.width, img.height = 260, 50
        ws.add_image(img, "A1")
        ws.row_dimensions[1].height = 45
        row = 3
    except Exception:  # noqa: BLE001
        pass
    ws.cell(row, 1, _("{APP_NAME} {__version__} — Informe de la infraestructura actual (solo análisis) · {COMPANY}", APP_NAME=APP_NAME, __version__=__version__, COMPANY=COMPANY)).font = Font(bold=True, size=14)
    ws.cell(row + 1, 1, _("Cliente: {v} · Generado: {generated}", v=a.client or '-', generated=f"{a.generated:%Y-%m-%d %H:%M}")
            + (_(" · Inventario anonimizado") if a.anonymized else "")).font = Font(italic=True, color="666666")
    for i, ln in enumerate(_(DISCLAIMER).split("\n"), start=row + 3):
        ws.cell(i, 1, ln)
    _kv(wb, _("Resumen"), [
        (_("Clústeres / nodos independientes"), ", ".join(an.clusters)), ("Nodos", t["hosts"]),
        (_("Versiones de Proxmox VE"), ", ".join(an.pve_versions())), (_("Cores / hilos físicos"), f"{t['host_cores']} / {t['host_threads']}"),
        ("RAM física (GiB)", round(t["host_ram_gib"])), (_("RAM en uso (GiB)"), round(t["host_ram_used_gib"])),
        ("VMs", t["vms"]), (_("Contenedores"), t["cts"]), ("Encendidas", t["running"]), ("Plantillas", a.templates),
        ("vCPU asignadas", t["vcpu"]), ("RAM asignada (GiB)", round(t["ram_gib"])),
        (_("Disco aprovisionado (TiB)"), round(t["disk_prov_gib"] / 1024, 2)),
        ("SDN", an.sdn_summary()),
        (_("Hallazgos críticos"), a.severity_counts().get(CRIT, 0)), (_("Avisos"), a.severity_counts().get(WARN, 0)),
        (_("Informativos"), a.severity_counts().get(INFO, 0)), (_("Valoración global"), a.score()),
    ], _("Informe de la infraestructura actual"))
    _table(wb, _("Hallazgos"), [{"Severidad": f["Severidad"], "Categoría": f["Categoría"], "Hallazgo": f["Hallazgo"],
                              "Afectados": f["Afectados"], "Recomendación": f["Recomendación"],
                              "Objetos": ", ".join(map(str, f["Objetos"]))} for f in a.findings], {"Objetos": 90, "Recomendación": 60})
    det = [{"Severidad": f["Severidad"], "Categoría": f["Categoría"], "Hallazgo": f["Hallazgo"], "Objeto": o}
           for f in a.findings for o in f["Objetos"]]
    _table(wb, _("Hallazgos (detalle)"), det)
    _table(wb, _("Uso por nodo"), a.node_rows())
    _table(wb, _("Tolerancia a fallo"), a.cluster_resilience())
    _table(wb, _("Por clúster"), an.by_cluster())
    _table(wb, _("Almacenamiento"), an.storage_usage())
    _table(wb, _("Redes de VMs"), [{"Bridge": r["bridge"], "VLAN": r["vlan"], "VMs/CTs": r["vms"], "Clústeres": ", ".join(r["clusters"]),
                                 "SDN": "Sí" if r["sdn"] else "", "Zona SDN": r["zone"], "Tipo zona": r["zone_type"],
                                 "Tag / VNI": r["sdn_tag"], "Subred SDN": r["subnet"]} for r in an.vlan_usage()])
    if an.has_sdn():
        sdn = an.sdn_tables()
        _table(wb, _("SDN zonas"), sdn["zones"], {"Red / underlay": 50, "IPAM / DNS": 40})
        _table(wb, _("SDN VNets"), sdn["vnets"])
        if sdn["objects"]:
            _table(wb, _("SDN objetos"), sdn["objects"], {"Detalles": 60})
    _table(wb, _("Sistemas operativos"), [{"Sistema operativo": k, "VMs/CTs": v} for k, v in an.os_detail().most_common()])
    _table(wb, _("Antigüedad backup"), [{"Antigüedad": k, "VMs/CTs": v} for k, v in a.backup_age().items()])
    _table(wb, "VMs", [{"Clúster": g.cluster, "Nodo": g.node, "VMID": g.vmid, "Nombre": g.name, "Tipo": g.kind,
                        "Estado": "plantilla" if g.template else ("encendida" if g.running else "apagada"), "vCPU": g.vcpu,
                        "RAM (GiB)": round(g.ram_gib, 1), "Disco aprov. (GiB)": round(g.disk_prov_gib, 1),
                        "Disco usado (GiB)": g.disk_used_gib, "SO": g.os_label, "HA": "Sí" if g.ha else "", "Pool": g.pool,
                        "Snapshots": g.snapshots, "Agente QEMU": "Sí" if g.agent else "No", "Tipo CPU": g.cpu_type,
                        "Uso CPU (%)": g.cpu_use_pct, "Uso memoria (%)": g.mem_use_pct, "Último backup": g.last_backup}
                       for g in an.all_guests])
    _table(wb, _("Avisos inventario (vHealth)"), list(a.sheets.get("vHealth", [])))
    return atomic_save(path, wb.save)


def generate(a: Assessment, folder, base=None, docx=True, xlsx=True, charts=False):
    base = base or _("analisis_infraestructura")
    os.makedirs(folder, exist_ok=True)
    out = []
    if docx:
        cdir = None
        if charts:
            cdir = os.path.join(folder, f"{base}{_('_graficos')}")
            os.makedirs(cdir, exist_ok=True)
        out.append(to_assessment_docx(a, os.path.join(folder, f"{base}.docx"), cdir))
    if xlsx:
        out.append(to_assessment_xlsx(a, os.path.join(folder, f"{base}.xlsx")))
    return out
