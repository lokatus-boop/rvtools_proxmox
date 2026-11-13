"""Rellena la hoja de configuración de implementación («Proxmox VE on PRIMERGY – Customer Interview Configuration Sheet»).

Se parte de la plantilla que indique el usuario (no se incluye en el programa) y se completan los datos que se conocen
por el plan: puertos de los nodos, redes, switches, almacenamiento, PBS y datos generales. Las contraseñas nunca se rellenan.
"""
from __future__ import annotations

import re

from openpyxl import load_workbook
from openpyxl.styles import Font

from pvetools.safefile import atomic_save

PROPOSED = Font(color="1F4E78", italic=True)   # valores propuestos por el planificador (a confirmar)

NET_ROWS = {  # nombre en la plantilla → nombre de red del plan
    "OOB Management": "OOB Management (iRMC)",
    "Management": "Management",
    "Cluster (corosync) 1": "Cluster (corosync) 1",
    "Cluster (corosync) 2": "Cluster (corosync) 2",
    "Live Migration": "Live Migration",
    "iSCSI 1": "iSCSI 1",
    "iSCSI 2": "iSCSI 2",
    "Ceph Private": "Ceph Private",
    "Ceph Public": "Ceph Public",
    "Payload 1": "Payload (VMs)",
}


class TemplateError(Exception):
    pass


def _norm(v):
    return re.sub(r"\s*\*\)\s*$", "", str(v or "")).strip().lower()


def _find_row(ws, text, col=2, start=1, end=200):
    t = text.lower()
    for r in range(start, min(ws.max_row, end) + 1):
        v = _norm(ws.cell(r, col).value)
        if v == t:
            return r
    return None


def _set(ws, row, col, value, proposed=True):
    if row is None or value in (None, ""):
        return
    c = ws.cell(row, col)
    if type(c).__name__ == "MergedCell":
        return
    c.value = value
    if proposed:
        c.font = PROPOSED


def defaults_from_inventory(plan) -> dict:
    """DNS, dominio y zona horaria de los nodos de origen (si en el escenario no se indicaron)."""
    hs = plan.an.sheets.get("vHost", [])
    imp = dict(plan.sc.get("implementacion") or {})

    def first(col):
        for h in hs:
            if h.get(col):
                return str(h.get(col))
        return ""
    imp.setdefault("dominio", "")
    if not imp.get("dominio"):
        imp["dominio"] = first("Dominio búsqueda")
    if not imp.get("dns"):
        imp["dns"] = first("DNS")
    if not imp.get("zona_horaria"):
        imp["zona_horaria"] = first("Zona horaria") or "Europe/Madrid"
    if not imp.get("cluster"):
        words = re.findall(r"[a-z0-9]+", (plan.sc.get("cliente") or "").lower())
        base = (words[0] if words else "pve")[:12]
        imp["cluster"] = f"{base}-pve"
    return imp


def fill(plan, template_path: str, out_path: str) -> str:
    wb = load_workbook(template_path)
    needed = {"Host Ports", "Networks", "Settings"}
    if not needed <= set(wb.sheetnames):
        raise TemplateError("La plantilla no tiene las hojas «Host Ports», «Networks» y «Settings».")
    net = plan.net
    sc = plan.sc
    imp = defaults_from_inventory(plan)
    pattern = (imp.get("patron_hostname") or "pve{nn}").replace("{nn}", "XX").replace("{n}", "X")
    dom = imp.get("dominio") or ""
    spec = plan.nodes[0]["spec"]

    # Portada
    if "Cover Sheet" in wb.sheetnames:
        ws = wb["Cover Sheet"]
        r = _find_row(ws, "company name:")
        if r:
            _set(ws, r, 4, sc.get("cliente") or None)

    # Host Ports: filas desde la cabecera «Host Link» hasta el ejemplo
    ws = wb["Host Ports"]
    hdr = _find_row(ws, "host link") or 2
    ex = _find_row(ws, "example:") or (hdr + 30)
    for r in range(hdr + 1, ex - 1):
        for c in range(3, 8):
            cell = ws.cell(r, c)
            if type(cell).__name__ != "MergedCell":
                cell.value = None
    for i, row in enumerate(net.host_ports):
        r = hdr + 1 + i
        if r >= ex - 1:
            break
        _set(ws, r, 3, row["Adapter"])
        _set(ws, r, 4, row["Port No."])
        _set(ws, r, 5, row["Device Name"])
        _set(ws, r, 6, int(row["Bond No."]) if str(row["Bond No."]).isdigit() else None)
        _set(ws, r, 7, row["Usage"])

    # Networks
    ws = wb["Networks"]
    nets = {n["red"]: n for n in plan.networks}
    end = _find_row(ws, "network sensitivity & traffic characteristics") or 19
    for r in range(3, end):
        key = _norm(ws.cell(r, 2).value)
        if not key:
            continue
        tmpl = next((k for k in NET_ROWS if k.lower() == key), None)
        n = nets.get(NET_ROWS.get(tmpl, "")) if tmpl else None
        if tmpl == "OOB Management":
            n = nets.get("OOB Management (iRMC)")
            _set(ws, r, 6, 1500)
            _set(ws, r, 7, "1 GbE")
            _set(ws, r, 11, f"{pattern}-irmc.{dom}" if dom else f"{pattern}-irmc")
            continue
        if not n:
            if tmpl or key.startswith("payload"):
                _set(ws, r, 3, "n/a")
            continue
        if n.get("vlan") and n["vlan"] not in ("-", "según inventario"):
            _set(ws, r, 3, n["vlan"])
        _set(ws, r, 6, n["mtu"] if n["mtu"] != "-" else None)
        _set(ws, r, 7, f"{n['gbps']:g} GbE")
        links = net.links_of(n["enlace"])
        link_txt = ",".join(map(str, links)) + (f"/{n['enlace']}" if n["enlace"].startswith("bond") else "")
        _set(ws, r, 8, link_txt or n["enlace"])
        _set(ws, r, 9, net.bond_type(n["enlace"]) or None)
        if tmpl == "Management":
            _set(ws, r, 11, f"{pattern}.{dom}" if dom else pattern)
    sens = end + 1 if end else None
    if sens:
        text = (f"Clúster de {len(plan.nodes)} nodos {spec.model}. "
                + " ".join(f"{h['Device Name']}: {h['Usage']}." for h in net.host_ports[::2])
                + f" Almacenamiento: {plan.storage_type.upper()}. "
                + ("Incluye Proxmox Backup Server en la red de backup (VLAN en bond1). " if plan.pbs else "")
                + "VLANs de VMs (Payload) trasladadas del entorno actual: " + (nets.get("Payload (VMs)", {}).get("vlan") or "-") + ".")
        _set(ws, sens, 2, text)

    # Settings
    ws = wb["Settings"]
    st = {
        "pve nodes": f"{len(plan.nodes)}× {spec.model}",
        "cluster name": imp.get("cluster"),
        "mangement domain name": dom, "management domain name": dom,
        "timezone": imp.get("zona_horaria"),
    }
    for label, val in st.items():
        _set(ws, _find_row(ws, label), 3, val)
    dns = [x for x in re.split(r"[,\s;]+", imp.get("dns") or "") if x]
    ntp = [x for x in re.split(r"[,\s;]+", imp.get("ntp") or "") if x]
    _set(ws, _find_row(ws, "primary dns server ip address"), 3, dns[0] if dns else None)
    _set(ws, _find_row(ws, "secondary dns server ip address"), 3, dns[1] if len(dns) > 1 else None)
    _set(ws, _find_row(ws, "ntp server ip address 1"), 3, ntp[0] if ntp else None)
    _set(ws, _find_row(ws, "ntp server ip address 2"), 3, ntp[1] if len(ntp) > 1 else None)
    sws = {w["tipo"]: w for w in net.switches}
    svc = next((w for k, w in sws.items() if k.startswith("Servicio")), None)
    oob = next((w for k, w in sws.items() if "OOB" in k), None)
    for label, w in (("tor#1 switch", svc), ("tor#2 switch", svc), ("mgmt switch", oob)):
        if w:
            _set(ws, _find_row(ws, label), 3, f"{w['modelo']} ({w['suministra']})")
    if plan.storage_type in ("san", "nfs"):
        ext = sc["hardware"]["almacenamiento_externo"].get("modelo") if sc["modo"] == "hardware" else ""
        _set(ws, _find_row(ws, "storage system"), 3, ext or ("Cabina SAN " + net.proto if plan.storage_type == "san" else "NAS NFS"))
    elif plan.storage_type == "ceph":
        _set(ws, _find_row(ws, "storage system"), 3, "n/a (Ceph hiperconvergente)")
    if plan.pbs:
        r = _find_row(ws, "backup server (pbs)")
        if r:
            _set(ws, r + 1, 3, "pbs01" + (f".{dom}" if dom else ""))
    # Suscripciones: nombres de los nodos
    if "PVE Subscriptions" in wb.sheetnames:
        ws = wb["PVE Subscriptions"]
        hdr = _find_row(ws, "host") or 5
        for i, n in enumerate(plan.nodes):
            _set(ws, hdr + 1 + i, 2, n["name"])
    out_path = atomic_save(out_path, wb.save)
    return out_path
