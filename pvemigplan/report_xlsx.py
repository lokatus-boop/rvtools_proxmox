"""Plan en Excel (hojas de trabajo para el equipo técnico)."""
from __future__ import annotations

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from . import APP_NAME, __version__
from .branding import COMPANY, DISCLAIMER, asset_path
from .catalog import TB_TO_GIB
from .scenario import STORAGE_TYPES

HEADER_FILL = PatternFill("solid", fgColor="1F4E78")
HEADER_FONT = Font(bold=True, color="FFFFFF")
SEV_FILL = {"BLOQUEO": PatternFill("solid", fgColor="F8CBAD"), "AVISO": PatternFill("solid", fgColor="FFE699"),
            "INFO": PatternFill("solid", fgColor="DDEBF7")}


def _table(wb, name, rows, widths=None):
    ws = wb.create_sheet(name[:31])
    if not rows:
        ws.append(["(sin datos)"])
        return ws
    cols = list(rows[0].keys())
    ws.append(cols)
    for r in rows:
        ws.append([r.get(c) for c in cols])
    for c in ws[1]:
        c.fill, c.font = HEADER_FILL, HEADER_FONT
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    for i, c in enumerate(cols, 1):
        w = max([len(str(c))] + [len(str(r.get(c) if r.get(c) is not None else "")) for r in rows[:300]])
        ws.column_dimensions[get_column_letter(i)].width = (widths or {}).get(c, min(max(w + 2, 8), 70))
    if "Severidad" in cols:
        sc = cols.index("Severidad")
        for row in ws.iter_rows(min_row=2):
            f = SEV_FILL.get(row[sc].value)
            if f:
                for cell in row:
                    cell.fill = f
    return ws


def _kv(wb, name, pairs, title=None):
    ws = wb.create_sheet(name[:31])
    ws.column_dimensions["A"].width = 46
    ws.column_dimensions["B"].width = 90
    r = 1
    if title:
        ws.cell(1, 1, title).font = Font(bold=True, size=13, color="1F4E78")
        r = 3
    for k, v in pairs:
        if k and v is None:
            ws.cell(r, 1, k).font = Font(bold=True, color="1F4E78")
        else:
            ws.cell(r, 1, k).font = Font(bold=True)
            c = ws.cell(r, 2, v)
            c.alignment = Alignment(wrap_text=True, vertical="top")
        r += 1
    return ws


def _notice(ws, plan):
    ws.title = "Aviso"
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
    ws.cell(row, 1, f"{APP_NAME} {__version__} — Plan de migración a Proxmox VE · {COMPANY}").font = Font(bold=True, size=14)
    ws.cell(row + 1, 1, f"Cliente: {plan.sc.get('cliente') or '-'} · Generado: {plan.generated:%Y-%m-%d %H:%M}").font = Font(italic=True, color="666666")
    r = row + 3
    for line in DISCLAIMER.split("\n"):
        c = ws.cell(r, 1, line)
        c.alignment = Alignment(wrap_text=True, vertical="top")
        if line.isupper():
            c.font = Font(bold=True, color="1F4E78")
        r += 1


def node_rows(plan):
    rows = []
    for n in plan.nodes:
        s = n["spec"]
        rows.append({"Nodo": n["name"], "Modelo": s.model, "Referencia": s.reference, "CPU": s.cpu_label,
                     "Sockets": s.sockets, "Cores": s.cores, "Hilos": s.threads, "GHz": s.ghz, "RAM (GiB)": s.ram_gib,
                     "RAM para VMs (GiB)": round(n["ram_usable"]), "Discos arranque": s.boot,
                     "Discos datos": f"{s.data_disks}× {s.data_disk_tb:g} TB {s.data_disk_type}" if s.data_disks else "-",
                     "Red": ", ".join(f"{x['puertos']}× {x['gbps']} GbE ({x.get('uso', '')})" for x in s.nics),
                     "VMs asignadas": len(n["guests"]), "vCPU asignadas": n["vcpu"], "RAM asignada (GiB)": round(n["ram"], 1),
                     "Ocupación RAM (%)": round(n["ram"] / n["ram_usable"] * 100, 1) if n["ram_usable"] else None,
                     "Ratio vCPU:core": round(n["vcpu"] / s.cores, 2) if s.cores else None})
    return rows


def placement_rows(plan):
    rows = []
    for g in sorted(plan.an.guests, key=lambda g: (g.cluster, int(g.vmid) if g.vmid.isdigit() else 0)):
        wave = next((w["nombre"] for w in plan.waves if g in w["guests"]), "")
        rows.append({"Clúster origen": g.cluster, "Nodo origen": g.node, "VMID": int(g.vmid) if g.vmid.isdigit() else g.vmid,
                     "Nombre": g.name, "Tipo": g.kind, "Encendida": "Sí" if g.running else "No", "SO": g.os_label,
                     "vCPU": g.vcpu, "RAM (GiB)": round(g.ram_gib, 1), "Disco aprov. (GiB)": round(g.disk_prov_gib, 1),
                     "Disco usado (GiB)": round(g.disk_used_gib, 1) if g.disk_used_gib else None,
                     "Redes (bridge/VLAN)": ", ".join(f"{b}/{v}" if v else b for b, v in g.nics),
                     "HA": "Sí" if g.ha else "No", "Nodo destino": plan.placement.get(g.key), "Ola": wave,
                     "Puntos a revisar": sum(1 for r in plan.issues if r["Clúster"] == g.cluster and str(r["VMID"]) == g.vmid)})
    return rows


def wave_rows(plan):
    rows = []
    for w in plan.waves:
        for g in w["guests"]:
            rows.append({"Ola": w["nombre"], "Fecha": w["fecha"].isoformat() if w.get("fecha") else f"Día {w['dia']}",
                         "Clúster": g.cluster, "VMID": int(g.vmid) if g.vmid.isdigit() else g.vmid, "Nombre": g.name,
                         "Tipo": g.kind, "Datos (GiB)": round(g.disk_effective_gib, 1),
                         "Método": ("pct" if g.kind == "CT" else "qm") + " remote-migrate" if plan.method["id"] == "remote-migrate"
                         else "Backup PBS + restore", "Nodo destino": plan.placement.get(g.key),
                         "Bridge/VLAN destino": ", ".join(f"vmbr1 VLAN {v}" if v else f"{b} (revisar)" for b, v in g.nics)})
    return rows


def to_xlsx(plan, path):
    wb = Workbook()
    _notice(wb.active, plan)
    cap, st = plan.sc["capacidad"], plan.sc["almacenamiento"]
    _kv(wb, "Resumen", [(line, "") for line in plan.text_summary().split("\n")], title="Resumen del plan")
    _kv(wb, "Supuestos", [
        ("Modo", "Aconsejar hardware (destino no definido)" if plan.sc["modo"] == "aconsejar" else "Hardware definido por el cliente / FSAS"),
        ("Versión Proxmox VE destino", plan.sc["pve_version"]),
        ("Almacenamiento", STORAGE_TYPES.get(st["tipo"], st["tipo"])),
        ("Alcance", f"Apagadas: {'incluidas' if plan.sc['alcance']['incluir_apagadas'] else 'excluidas'} · plantillas: "
                    f"{'incluidas' if plan.sc['alcance']['incluir_plantillas'] else 'excluidas'} · excluidas a mano: {len(plan.sc['alcance'].get('excluir') or [])}"),
        ("Crecimiento", f"{cap['crecimiento_pct']} %"),
        ("Base de CPU", "vCPU asignadas / ratio" if cap["base_cpu"] == "asignado" else "Uso observado × 1,5"),
        ("Ratio vCPU : core físico", cap["ratio_vcpu_core"]),
        ("Ocupación máxima CPU / RAM", f"{cap['cpu_max_pct']} % / {cap['ram_max_pct']} %"),
        ("Tolerancia a fallos", f"N+{cap['n_mas']} (mínimo {cap['nodos_min']} nodos)"),
        ("Base de disco", "Espacio usado (agente QEMU) o aprovisionado si no se conoce" if cap["base_disco"] == "usado" else "Espacio aprovisionado"),
        ("Reserva para snapshots", f"{cap['reserva_snapshots_pct']} %"),
        ("Llenado máximo del almacenamiento", f"{st['llenado_max_pct']} %" + (f" · réplicas Ceph: {st.get('replicas', 3)}" if st["tipo"] == "ceph" else "")),
        ("Reserva de RAM por nodo", "8 GiB Proxmox VE + 5 GiB por OSD y 4 GiB MON/MGR (Ceph) o ARC de ZFS"),
        ("Red", f"{plan.sc['red']['velocidad_gbps']} GbE · jumbo frames: {'sí' if plan.sc['red'].get('jumbo', True) else 'no'}"),
        ("Migración", f"{plan.method['nombre']} · {plan.sc['migracion']['mbps_por_flujo']} MB/s × {plan.sc['migracion']['flujos']} flujos · "
                      f"máx. {plan.sc['migracion']['max_vms_ola']} VMs / {plan.sc['migracion']['max_gib_ola']} GiB por ola"),
    ] + ([("PBS", f"Retención {plan.sc['pbs']['retencion']} · cambio diario {plan.sc['pbs']['cambio_diario_pct']} % · "
                  f"reducción {plan.sc['pbs']['reduccion']} · llenado máx. {plan.sc['pbs']['llenado_max_pct']} %")] if plan.pbs else []),
        title="Supuestos de cálculo")
    if plan.options:
        rows = []
        for i, o in enumerate(plan.options, 1):
            n, e = o["nodos"][0], o["eval"]
            rows.append({"Opción": i, "Descripción": o["etiqueta"], "Nodos": n.count, "Servidor": n.model, "Referencia": n.reference,
                         "CPU por nodo": n.cpu_label, "Cores por nodo": n.cores, "RAM por nodo (GiB)": n.ram_gib,
                         "Discos datos por nodo": f"{n.data_disks}× {n.data_disk_tb:g} TB" if n.data_disks else "-",
                         "Cores totales": e["cores"], "RAM total (GiB)": e["ram_gib"],
                         "Almacenamiento útil (TiB)": round(e["almacenamiento_util_gib"] / 1024, 1),
                         "CPU % (N-1)": round(e["cpu_pct_n1"]), "RAM % (N-1)": round(e["ram_pct_n1"]),
                         "Sockets (suscripciones PVE)": e["sockets"], "Coste relativo": o["coste_rel"]})
        _table(wb, "Opciones hardware", rows)
    _table(wb, "Nodos destino", node_rows(plan))
    e = plan.eval
    _table(wb, "Capacidad", [
        {"Recurso": "CPU (cores físicos)", "Necesario": round(plan.req.cores, 1), "Disponible": e["cores"], "Disponible N-1": e["cores_n1"],
         "Ocupación %": round(e["cpu_pct"], 1), "Ocupación N-1 %": round(e["cpu_pct_n1"], 1), "Objetivo %": cap["cpu_max_pct"]},
        {"Recurso": "RAM (GiB)", "Necesario": round(plan.req.ram_need_gib), "Disponible": round(e["ram_util_gib"]), "Disponible N-1": round(e["ram_n1_gib"]),
         "Ocupación %": round(e["ram_pct"], 1), "Ocupación N-1 %": round(e["ram_pct_n1"], 1), "Objetivo %": cap["ram_max_pct"]},
        {"Recurso": "Almacenamiento útil (TiB)", "Necesario": round(plan.req.data_gib / 1024, 2), "Disponible": round(e["almacenamiento_util_gib"] / 1024, 2),
         "Disponible N-1": round(e["almacenamiento_util_gib"] / 1024, 2), "Ocupación %": round(e["alm_pct_real"], 1),
         "Ocupación N-1 %": round(e["alm_pct_real"], 1), "Objetivo %": st["llenado_max_pct"]},
    ] + [{"Recurso": "Problema", "Necesario": p} for p in e["problemas"]] + [{"Recurso": "Aviso", "Necesario": a} for a in e["avisos"]])
    _table(wb, "Ubicación VMs", placement_rows(plan))
    _table(wb, "Redes", [{"Red": n["red"], "Interfaz": n["interfaz"], "Puertos por nodo": n["puertos"], "Modo": n["modo"],
                          "VLAN": n["vlan"], "MTU": n["mtu"], "Notas": n["nota"]} for n in plan.networks])
    _table(wb, "VLANs", plan.vlan_map)
    _table(wb, "Puertos switch", [{"Velocidad": f"{k} GbE" if k != "BMC" else "1 GbE (BMC/iRMC)", "Puertos": v,
                                   "Por switch (2 switches)": v if k == "BMC" else -(-v // 2)} for k, v in plan.port_summary().items()])
    sto = [{"Concepto": "Tipo", "Valor": STORAGE_TYPES.get(st["tipo"], st["tipo"])},
           {"Concepto": "Datos a alojar (TiB, con crecimiento y reserva)", "Valor": round(plan.req.data_gib / 1024, 2)},
           {"Concepto": "Capacidad útil (TiB)", "Valor": round(e["almacenamiento_util_gib"] / 1024, 2)}]
    if st["tipo"] in ("ceph", "zfs"):
        raw = sum(n["spec"].raw_data_gib for n in plan.nodes)
        sto.append({"Concepto": "Capacidad bruta (TiB)", "Valor": round(raw / 1024, 2)})
        sto.append({"Concepto": "Discos de datos", "Valor": ", ".join(sorted({f"{n['spec'].data_disks}× {n['spec'].data_disk_tb:g} TB por nodo" for n in plan.nodes}))})
    sto.append({"Concepto": "Origen por tipo (GiB)", "Valor": ", ".join(f"{k}: {v:.0f}" for k, v in plan.an.guest_storage_by_type().items())})
    _table(wb, "Almacenamiento", sto)
    _table(wb, "Almacenamiento origen", plan.an.storage_usage())
    if plan.pbs:
        p = plan.pbs
        rows = [{"Concepto": "Datos protegidos (TiB)", "Valor": round(p["datos_origen_gib"] / 1024, 2)},
                {"Concepto": "Datos guardados estimados (TiB)", "Valor": round(p["guardado_gib"] / 1024, 2)},
                {"Concepto": "Capacidad útil necesaria (TiB)", "Valor": round(p["util_necesario_gib"] / 1024, 2)},
                {"Concepto": "CPU propuesta", "Valor": f"{p['propuesta']['cores']} cores"},
                {"Concepto": "RAM propuesta", "Valor": f"{p['propuesta']['ram_gib']} GiB"},
                {"Concepto": "Discos propuestos", "Valor": p["propuesta"]["discos"]},
                {"Concepto": "Red", "Valor": p["propuesta"]["red"]},
                {"Concepto": "Primera copia completa (h)", "Valor": round(p["horas_full"], 1)},
                {"Concepto": "Copia incremental diaria (h)", "Valor": round(p["horas_incremental"], 2)}]
        if p.get("definido"):
            rows.append({"Concepto": "PBS indicado: capacidad útil (TiB)", "Valor": round(p["definido"]["util_gib"] / 1024, 2)})
            rows.append({"Concepto": "PBS indicado: ocupación prevista (%)", "Valor": round(p["definido"]["pct"], 1)})
        rows += [{"Concepto": "Aviso", "Valor": a} for a in p["avisos"]]
        _table(wb, "PBS", rows)
    _table(wb, "Olas", [{"Ola": w["nombre"], "Tipo": w["tipo"], "Fecha": w["fecha"].isoformat() if w.get("fecha") else f"Día {w['dia']}",
                         "VMs": len(w["guests"]), "vCPU": w["vcpu"], "RAM (GiB)": round(w["ram"]), "Datos (GiB)": round(w["gib"]),
                         "Transferencia estimada (h)": round(w["horas"], 1)} for w in plan.waves])
    _table(wb, "Olas detalle", wave_rows(plan))
    _table(wb, "Riesgos", plan.issues)
    _table(wb, "Origen", plan.an.by_cluster())
    wb.save(path)
    return path


__all__ = ["to_xlsx", "TB_TO_GIB"]
