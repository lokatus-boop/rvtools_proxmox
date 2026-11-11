"""Modelo físico y lógico de red del nuevo entorno: switches (fabrics), equipos conectados, puertos de cada nodo y redes."""
from __future__ import annotations

import math

USO_LABEL = {"gestion": "Gestión", "vms": "VMs", "almacenamiento": "Almacenamiento", "fc": "FC", "backup": "Backup",
             "bmc": "OOB / iRMC", "corosync": "Corosync"}

# Modelos propuestos cuando Fsas Technologies suministra los switches y no se indica modelo (orientativos)
SWITCH_SUGGEST = {
    "servicio": [(25, 48, "Juniper QFX5120-48Y (48× 1/10/25 GbE SFP28 + 8× 100 GbE)"),
                 (100, 32, "Juniper QFX5120-32C (32× 40/100 GbE QSFP28)")],
    "almacenamiento_eth": [(25, 48, "Juniper QFX5120-48Y (48× 1/10/25 GbE SFP28 + 8× 100 GbE)"),
                           (100, 32, "Juniper QFX5120-32C (32× 40/100 GbE QSFP28)")],
    "almacenamiento_fc": [(32, 48, "Switch FC 32 Gb de 24-48 puertos (p. ej. Brocade G620)")],
    "oob": [(1, 48, "Juniper EX2300-48T (48× 1 GbE + 4× 10 GbE)")],
}


def _suggest(kind, gbps):
    opts = SWITCH_SUGGEST[kind]
    for g, ports, name in opts:
        if gbps <= g:
            return name, ports
    return opts[-1][2], opts[-1][1]


def _fmt_g(g):
    return f"{g:g}"


class NetworkModel:
    def __init__(self, plan):
        self.plan = plan
        sc = plan.sc
        self.sc = sc
        self.typ = plan.storage_type
        proto = str(sc["almacenamiento"].get("protocolo") or "iSCSI").strip().upper()
        self.proto = ("FC" if proto == "FC" else "iSCSI") if self.typ == "san" else ("NFS" if self.typ == "nfs" else "")
        sw = sc.get("switches") or {}
        self.sw = {k: dict(v) for k, v in sw.items()}
        groups = self._groups()
        self.fc = any(n.get("uso") == "fc" for spec, _ in groups for n in spec.nics) or (self.typ == "san" and self.proto == "FC")
        self.sto_dedicated = self.fc or bool(self.sw.get("almacenamiento", {}).get("dedicados"))
        self.fabrics = self._fabrics()
        self.endpoints = self._endpoints(groups)
        self._count_ports()
        self.networks = self._logical_networks(groups)
        self.host_ports = self._host_ports(groups[0][0]) if groups else []

    # ------------------------------------------------------------------ fabrics y equipos
    def _groups(self):
        out = {}
        for n in self.plan.nodes:
            out.setdefault(id(n["spec"]), [n["spec"], 0])[1] += 1
        return [tuple(v) for v in out.values()]

    def _fabrics(self):
        g = self.sc["red"]["velocidad_gbps"]
        svc = self.sw.get("servicio", {})
        fabrics = [
            {"id": "eth-a", "nombre": "ETH-A", "rol": "servicio", "gbps": svc.get("gbps") or g, "color": "#2a78d6"},
            {"id": "eth-b", "nombre": "ETH-B", "rol": "servicio", "gbps": svc.get("gbps") or g, "color": "#5598e7"},
        ]
        if self.sto_dedicated:
            sto = self.sw.get("almacenamiento", {})
            name = "FC" if self.fc else "STO"
            gb = 32 if self.fc else (sto.get("gbps") or g)
            fabrics += [{"id": "sto-a", "nombre": f"{name}-A", "rol": "almacenamiento", "gbps": gb, "color": "#6250d6"},
                        {"id": "sto-b", "nombre": f"{name}-B", "rol": "almacenamiento", "gbps": gb, "color": "#9085e9"}]
        fabrics.append({"id": "oob", "nombre": "OOB", "rol": "oob", "gbps": 1, "color": "#1baf7a"})
        return fabrics

    def _fabric_for(self, uso, side):
        if uso in ("fc",) or (uso == "almacenamiento" and self.sto_dedicated):
            return f"sto-{side}"
        if uso == "bmc":
            return "oob"
        return f"eth-{side}"

    def _endpoints(self, groups):
        eps = []
        for spec, cnt in groups:
            links = []
            for nic in spec.nics:
                p = int(nic.get("puertos", 0))
                if not p:
                    continue
                a, b = math.ceil(p / 2), p // 2
                uso = nic.get("uso", "vms")
                links.append({"uso": uso, "gbps": nic.get("gbps"), "a": a, "b": b,
                              "fa": self._fabric_for(uso, "a"), "fb": self._fabric_for(uso, "b")})
            links.append({"uso": "bmc", "gbps": 1, "a": 1, "b": 0, "fa": "oob", "fb": None})
            eps.append({"id": f"grp{len(eps)}", "tipo": "servidor", "titulo": "Clúster Proxmox VE",
                        "detalle": f"{cnt} × {spec.model}", "modelo": spec.model, "count": cnt, "links": links,
                        "nota": {"ceph": "Ceph: almacenamiento distribuido por Ethernet", "zfs": "ZFS local + replicación",
                                 "san": f"Cabina SAN · {self.proto} multipath", "nfs": "NAS NFS"}.get(self.typ, "")})
        if self.plan.pbs:
            g = max(self.sc["red"]["velocidad_gbps"], 10)
            mdl = self.sc["pbs"]["hardware"].get("modelo") if self.sc["pbs"]["hardware"].get("definido") else "Servidor PBS"
            eps.append({"id": "pbs", "tipo": "servidor", "titulo": "Proxmox Backup Server", "detalle": f"1 × {mdl}",
                        "modelo": mdl, "count": 1,
                        "links": [{"uso": "backup", "gbps": g, "a": 1, "b": 1, "fa": "eth-a", "fb": "eth-b"},
                                  {"uso": "bmc", "gbps": 1, "a": 1, "b": 0, "fa": "oob", "fb": None}],
                        "nota": f"{self.plan.pbs['util_necesario_gib'] / 1024:.1f} TiB útiles"})
        if self.typ in ("san", "nfs"):
            ext = self.sc["hardware"]["almacenamiento_externo"]
            mdl = (ext.get("modelo") if self.sc["modo"] == "hardware" else "") or ("Cabina SAN" if self.typ == "san" else "NAS NFS")
            gb = 32 if self.fc else self.sc["red"]["velocidad_gbps"]
            side = "sto" if self.sto_dedicated else "eth"
            eps.append({"id": "ext", "tipo": "cabina", "titulo": "Almacenamiento externo", "detalle": mdl, "modelo": mdl, "count": 1,
                        "links": [{"uso": "fc" if self.fc else "almacenamiento", "gbps": gb, "a": 2, "b": 2,
                                   "fa": f"{side}-a", "fb": f"{side}-b"},
                                  {"uso": "bmc", "gbps": 1, "a": 2, "b": 0, "fa": "oob", "fb": None}],
                        "nota": "2 controladoras × 2 puertos de datos"})
        return eps

    def _count_ports(self):
        for f in self.fabrics:
            f["puertos"] = 0
        by_id = {f["id"]: f for f in self.fabrics}
        for ep in self.endpoints:
            for ln in ep["links"]:
                if ln["fa"]:
                    by_id[ln["fa"]]["puertos"] += ln["a"] * ep["count"]
                if ln["fb"] and ln["b"]:
                    by_id[ln["fb"]]["puertos"] += ln["b"] * ep["count"]
        # switches: modelo propuesto / indicado y número necesario
        kinds = {"servicio": ["eth-a", "eth-b"], "almacenamiento": ["sto-a", "sto-b"], "oob": ["oob"]}
        self.switches = []
        for kind, ids in kinds.items():
            fs = [by_id[i] for i in ids if i in by_id]
            if not fs:
                continue
            cfg = self.sw.get(kind, {})
            supplier = cfg.get("suministra", "fsas")
            model = (cfg.get("modelo") or "").strip()
            per_sw = int(cfg.get("puertos") or 0)
            sugg = kind if kind != "almacenamiento" else ("almacenamiento_fc" if self.fc else "almacenamiento_eth")
            if not model and supplier == "fsas":
                model, sp = _suggest(sugg, fs[0]["gbps"])
                per_sw = per_sw or sp
            per_sw = per_sw or 48
            need = max(f["puertos"] for f in fs)
            n_per_fabric = max(1, math.ceil(need / max(per_sw - 4, 1)))  # reserva 4 puertos (uplinks/ISL)
            for f in fs:
                f["modelo"] = model or "(modelo del cliente por indicar)"
                f["suministra"] = supplier
                f["switches"] = n_per_fabric
            self.switches.append({"tipo": {"servicio": "Servicio (ToR)", "almacenamiento": "Almacenamiento" + (" FC" if self.fc else ""),
                                           "oob": "Gestión fuera de banda (OOB)"}[kind],
                                  "suministra": "Fsas Technologies" if supplier == "fsas" else "Cliente",
                                  "modelo": model or "(por indicar)", "cantidad": n_per_fabric * len(fs),
                                  "puertos_por_switch": per_sw,
                                  "puertos_necesarios": sum(f["puertos"] for f in fs),
                                  "velocidad": f"{_fmt_g(fs[0]['gbps'])} {'Gb FC' if kind == 'almacenamiento' and self.fc else 'GbE'}",
                                  "redundancia": "Pareja A/B (MLAG/stack o fabrics independientes)" if len(fs) > 1 else "Sin redundancia (red de gestión)"})

    # ------------------------------------------------------------------ redes lógicas
    def _logical_networks(self, groups):
        g = self.sc["red"]["velocidad_gbps"]
        mtu = 9000 if self.sc["red"].get("jumbo", True) else 1500
        vlans = sorted({int(v["vlan"]) for v in self.plan.an.vlan_usage() if v["vlan"].isdigit()})
        spec = groups[0][0] if groups else None
        has = {n.get("uso") for n in (spec.nics if spec else [])}
        speed = {n.get("uso"): n.get("gbps") for n in (spec.nics if spec else [])}
        sto_bond = "bond2" if "almacenamiento" in has and self.typ in ("ceph", "nfs") else None
        out = [
            {"red": "OOB Management (iRMC)", "vlan": "", "puertos": "1× 1 GbE dedicado", "interfaz": "iRMC", "modo": "-",
             "mtu": 1500, "gbps": 1, "enlace": "BMC", "nota": "Consola remota, encendido/apagado y fencing por hardware opcional."},
            {"red": "Management", "vlan": "", "puertos": f"2× {_fmt_g(speed.get('gestion', 1))} GbE", "interfaz": "bond0 → vmbr0",
             "modo": "active-backup", "mtu": 1500, "gbps": speed.get("gestion", 1), "enlace": "bond0",
             "nota": "GUI/API/SSH de Proxmox VE. IP fija por nodo."},
            {"red": "Cluster (corosync) 1", "vlan": "", "puertos": "en bond0", "interfaz": "vmbr0 (o VLAN propia)", "modo": "-",
             "mtu": 1500, "gbps": speed.get("gestion", 1), "enlace": "bond0",
             "nota": "Enlace 0 de corosync (knet). Baja latencia (< 5 ms); sin tráfico intenso."},
            {"red": "Cluster (corosync) 2", "vlan": "", "puertos": f"en {sto_bond or 'bond1'}", "interfaz": f"{sto_bond or 'bond1'}.<vlan>",
             "modo": "-", "mtu": 1500, "gbps": speed.get("almacenamiento" if sto_bond else "vms", g), "enlace": sto_bond or "bond1",
             "nota": "Enlace 1 de corosync en otra red física (redundancia)."},
            {"red": "Live Migration", "vlan": "", "puertos": "en bond1", "interfaz": "bond1.<vlan>", "modo": "-", "mtu": mtu,
             "gbps": speed.get("vms", g), "enlace": "bond1",
             "nota": "Datacenter → Opciones → Red de migración (tipo «insecure» si la red está aislada)."},
        ]
        if self.typ == "ceph":
            out += [{"red": "Ceph Public", "vlan": "", "puertos": "en bond2", "interfaz": "bond2.<vlan>", "modo": "802.3ad (LACP)",
                     "mtu": mtu, "gbps": speed.get("almacenamiento", g), "enlace": "bond2", "nota": "public_network de Ceph (MON/clientes)."},
                    {"red": "Ceph Private", "vlan": "", "puertos": "en bond2", "interfaz": "bond2.<vlan>", "modo": "802.3ad (LACP)",
                     "mtu": mtu, "gbps": speed.get("almacenamiento", g), "enlace": "bond2", "nota": "cluster_network de Ceph (replicación entre OSDs)."}]
        elif self.typ == "san" and not self.fc:
            out += [{"red": "iSCSI 1", "vlan": "", "puertos": f"1× {_fmt_g(speed.get('almacenamiento', g))} GbE (lado A)", "interfaz": "iscsi_A",
                     "modo": "sin bond (multipath)", "mtu": mtu, "gbps": speed.get("almacenamiento", g), "enlace": "iscsi_A",
                     "nota": "Camino 1 hacia ambas controladoras."},
                    {"red": "iSCSI 2", "vlan": "", "puertos": f"1× {_fmt_g(speed.get('almacenamiento', g))} GbE (lado B)", "interfaz": "iscsi_B",
                     "modo": "sin bond (multipath)", "mtu": mtu, "gbps": speed.get("almacenamiento", g), "enlace": "iscsi_B",
                     "nota": "Camino 2 hacia ambas controladoras."}]
        elif self.typ == "san":
            out += [{"red": "FC fabric A / B", "vlan": "-", "puertos": "2× FC 32 Gb (HBA)", "interfaz": "HBA", "modo": "multipath",
                     "mtu": "-", "gbps": 32, "enlace": "FC", "nota": "Zoning por WWPN hacia ambas controladoras."}]
        elif self.typ == "nfs":
            out += [{"red": "NFS", "vlan": "", "puertos": "en bond2", "interfaz": "bond2.<vlan>", "modo": "802.3ad (LACP)", "mtu": mtu,
                     "gbps": speed.get("almacenamiento", g), "enlace": "bond2", "nota": "NFS 4.1/4.2 (nconnect si la NAS lo soporta)."}]
        else:
            out += [{"red": "Replicación ZFS", "vlan": "", "puertos": "en bond1", "interfaz": "bond1.<vlan>", "modo": "-", "mtu": mtu,
                     "gbps": speed.get("vms", g), "enlace": "bond1", "nota": "Replicación asíncrona entre nodos (1-15 min)."}]
        if self.plan.pbs:
            out.append({"red": "Backup (PBS)", "vlan": "", "puertos": "en bond1", "interfaz": "bond1.<vlan>", "modo": "-", "mtu": mtu,
                        "gbps": speed.get("vms", g), "enlace": "bond1", "nota": "Tráfico hacia el Proxmox Backup Server."})
        out.append({"red": "Payload (VMs)", "vlan": ", ".join(map(str, vlans)) or "según inventario", "puertos": f"2× {_fmt_g(speed.get('vms', g))} GbE",
                    "interfaz": "bond1 → vmbr1 (VLAN aware)", "modo": "802.3ad (LACP) layer3+4", "mtu": 1500,
                    "gbps": speed.get("vms", g), "enlace": "bond1",
                    "nota": "VLANs de las VMs (mismas que en origen). Recomendado: SDN zona VLAN con una VNet por VLAN."})
        return out

    # ------------------------------------------------------------------ puertos del nodo
    def _host_ports(self, spec):
        """Tabla de puertos de un nodo tipo (como la hoja «Host Ports»)."""
        rows = []
        link = 1
        bond_of = {"gestion": "0", "vms": "1"}
        if self.typ in ("ceph", "nfs"):
            bond_of["almacenamiento"] = "2"
        uses = {}
        for n in self.networks:
            uses.setdefault(n["enlace"], []).append(n["red"])
        for i, nic in enumerate(spec.nics):
            uso = nic.get("uso", "vms")
            for p in range(int(nic.get("puertos", 0))):
                side = "A" if p % 2 == 0 else "B"
                if uso == "fc":
                    dev, bond, usage = f"fc_{side}", "", f"FC fabric {side}"
                elif uso == "almacenamiento" and self.typ == "san":
                    dev, bond, usage = f"iscsi_{side}", "", ", ".join(uses.get(f"iscsi_{side}", [])) or f"iSCSI {side}"
                else:
                    pref = {"gestion": "mgmt", "vms": "payload", "almacenamiento": "storage"}.get(uso, uso)
                    bond = bond_of.get(uso, "")
                    dev = f"{pref}_{side}"
                    usage = ", ".join(uses.get(f"bond{bond}", [])) if bond else USO_LABEL.get(uso, uso)
                rows.append({"Host Link": link, "Adapter": f"NIC {i + 1} ({nic.get('gbps'):g} {'Gb FC' if uso == 'fc' else 'GbE'})",
                             "Port No.": p, "Device Name": dev, "Bond No.": bond, "Usage": usage})
                link += 1
        return rows

    def bond_type(self, enlace):
        return {"bond0": "active-backup", "bond1": "802.3ad", "bond2": "802.3ad"}.get(enlace, "")

    def links_of(self, enlace):
        return [r["Host Link"] for r in self.host_ports if (enlace.startswith("bond") and r["Bond No."] == enlace[4:])
                or r["Device Name"] == enlace]

    def switch_port_map(self):
        """Asignación orientativa de puertos de switch: (switch, puerto, equipo, enlace)."""
        rows = []
        next_port = {f["id"]: 1 for f in self.fabrics}
        names = {f["id"]: f["nombre"] for f in self.fabrics}
        node_names = iter([n["name"] for n in self.plan.nodes])
        for ep in self.endpoints:
            for k in range(ep["count"]):
                if ep["id"].startswith("grp"):
                    host = next(node_names, f"nodo{k + 1}")
                elif ep["id"] == "ext":
                    host = ep["detalle"]
                else:
                    host = "pbs01"
                for ln in ep["links"]:
                    for side, (fab, n) in enumerate(((ln["fa"], ln["a"]), (ln["fb"], ln["b"]))):
                        if not fab:
                            continue
                        for _ in range(n):
                            rows.append({"Switch": names[fab], "Puerto": next_port[fab], "Equipo": host,
                                         "Uso": USO_LABEL.get(ln["uso"], ln["uso"]),
                                         "Velocidad": f"{ln['gbps']:g} {'Gb FC' if ln['uso'] == 'fc' else 'GbE'}"})
                            next_port[fab] += 1
        return rows
