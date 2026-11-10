"""Construcción del plan completo: hardware, ubicación de VMs, redes, almacenamiento, PBS, olas y riesgos."""
from __future__ import annotations

import datetime as dt
import math
import re

from .analysis import LEGACY_OS, Analysis
from .catalog import load_catalog
from .scenario import PBS_VERSIONS, STORAGE_TYPES
from .sizing import advise, evaluate, expand, node_overhead_gib, nodes_from_hardware, pbs_sizing, requirements

CRIT_TAGS = re.compile(r"(crit|core|erp|sql|oracle|\bdb|^db|dc\d*$|^dc|\bad\b|sap)", re.I)
TEST_TAGS = re.compile(r"(test|dev|pre|lab|demo|qa|sandbox|temp)", re.I)
BLOQUEO, AVISO, INFO = "BLOQUEO", "AVISO", "INFO"


class PlanError(Exception):
    pass


class Plan:
    def __init__(self, sheets: dict, sc: dict, catalog_path: str | None = None):
        self.sc = sc
        self.cat = load_catalog(catalog_path)
        al = sc["alcance"]
        self.an = Analysis(sheets, al["incluir_apagadas"], al["incluir_plantillas"], set(al.get("excluir") or []))
        if not self.an.guests:
            raise PlanError("No hay VMs/CTs en el alcance (revisa los filtros).")
        self.req = requirements(self.an, sc)
        self.storage_type = sc["almacenamiento"]["tipo"]
        self.options = []
        if sc["modo"] == "aconsejar":
            self.options = advise(self.an, sc, self.cat)
            if not self.options:
                raise PlanError("Ninguna configuración del catálogo cubre las necesidades: revisa los parámetros.")
            self.groups = self.options[0]["nodos"]
            self.eval = self.options[0]["eval"]
        else:
            self.groups = nodes_from_hardware(sc)
            if not expand(self.groups):
                raise PlanError("Indica al menos un servidor de destino.")
            self.eval = evaluate(self.groups, sc, self.req)
        self.nodes = self._name_nodes()
        self.placement = self._place()
        self.pbs = pbs_sizing(self.req, sc, self.cat) if sc["pbs"]["incluir"] else None
        from .network import NetworkModel
        self.net = NetworkModel(self)
        self.networks = self.net.networks
        self.vlan_map = self._vlan_map()
        self.issues = self._issues()
        self.method = self._method()
        self.waves = self._waves()
        self.generated = dt.datetime.now()

    # ------------------------------------------------------------------ nodos y ubicación
    def _name_nodes(self):
        out = []
        pattern = (self.sc.get("implementacion", {}).get("patron_hostname") or "pve{nn}")
        for i, spec in enumerate(expand(self.groups), 1):
            osds = spec.data_disks if self.storage_type == "ceph" else 0
            try:
                name = pattern.format(nn=f"{i:02d}", n=i)
            except (KeyError, IndexError, ValueError):
                name = f"pve{i:02d}"
            out.append({"name": name, "spec": spec,
                        "ram_usable": spec.ram_gib - node_overhead_gib(spec.ram_gib, self.storage_type, osds),
                        "cores": spec.cores, "vcpu": 0.0, "ram": 0.0, "disk": 0.0, "guests": []})
        return out

    def _place(self):
        """Reparte las VMs entre los nodos (mayor primero, al nodo con más hueco relativo)."""
        cap = self.sc["capacidad"]
        ratio = cap["ratio_vcpu_core"]
        placement = {}
        guests = sorted(self.an.guests, key=lambda g: (g.ram_gib, g.vcpu), reverse=True)
        for g in guests:
            def score(n):
                rf = (n["ram"] + g.ram_gib) / n["ram_usable"] if n["ram_usable"] > 0 else 9
                cf = (n["vcpu"] + g.vcpu) / (n["cores"] * ratio) if n["cores"] else 9
                return max(rf, cf)
            ok = [n for n in self.nodes if n["spec"].threads >= g.vcpu]
            best = min(ok or self.nodes, key=score)
            best["vcpu"] += g.vcpu
            best["ram"] += g.ram_gib
            best["disk"] += g.disk_effective_gib
            best["guests"].append(g)
            placement[g.key] = best["name"]
        # anti-afinidad básica: VMs con el mismo nombre base (web01/web02) en nodos distintos
        return placement

    # ------------------------------------------------------------------ redes
    def port_summary(self):
        """Puertos de switch necesarios por fabric."""
        return {f["nombre"]: f["puertos"] for f in self.net.fabrics}

    def _vlan_map(self):
        rows = []
        for v in self.an.vlan_usage():
            if v["sdn"]:
                target = f"SDN VNet {v['bridge']} (tag {v['sdn_tag']})"
            elif v["vlan"]:
                target = f"vmbr1 · VLAN {v['vlan']}  (o VNet SDN «vlan{v['vlan']}»)"
            else:
                target = "vmbr1 · VLAN nativa → definir VLAN explícita"
            rows.append({"Bridge origen": v["bridge"], "VLAN origen": v["vlan"] or "(sin etiqueta)",
                         "Clústeres": ", ".join(v["clusters"]), "NICs de VMs": v["vms"],
                         "SDN origen": f"{v['zone']} / {v['subnet'] or ''}" if v["sdn"] else "",
                         "Destino propuesto": target})
        return rows

    # ------------------------------------------------------------------ riesgos
    def _issues(self):
        out = []
        tgt_vendor = ""
        labels = " ".join(n["spec"].cpu_label for n in self.nodes).lower()
        if "amd" in labels or "epyc" in labels:
            tgt_vendor = "AMD"
        elif "intel" in labels or "xeon" in labels:
            tgt_vendor = "Intel"
        src_vendors = self.an.cpu_vendors()
        target_major = int(str(self.sc["pve_version"]).split(".")[0] or 9)
        for g in self.an.guests:
            add = lambda sev, cat, msg: out.append({"Severidad": sev, "Clúster": g.cluster, "VMID": g.vmid, "Nombre": g.name,  # noqa: E731
                                                    "Categoría": cat, "Detalle": msg})
            if g.passthrough:
                add(BLOQUEO, "Hardware", f"Dispositivo PCI/USB en passthrough ({g.passthrough}): requiere hardware equivalente en destino y migración en frío.")
            if g.lock:
                add(BLOQUEO, "Estado", f"VM bloqueada ({g.lock}): resolver antes de migrar.")
            if g.snapshots:
                add(AVISO, "Snapshots", f"{g.snapshots} snapshot(s): la migración entre clústeres no las conserva; consolidarlas antes.")
            if g.cdrom_iso:
                add(AVISO, "CD-ROM", "ISO montada (" + ", ".join(g.cdrom_iso) + "): desmontar antes de migrar.")
            if g.cpu_type == "host" and (len(src_vendors) > 1 or (tgt_vendor and src_vendors and tgt_vendor not in src_vendors)):
                add(AVISO, "CPU", "Tipo de CPU «host» con cambio de fabricante/generación: cambiar a x86-64-v2-AES o x86-64-v3 (requiere reinicio).")
            elif g.cpu_type == "host":
                add(INFO, "CPU", "Tipo de CPU «host»: valida que el destino tiene la misma generación o usa un modelo genérico.")
            if g.kind == "VM" and g.ostype in LEGACY_OS:
                add(AVISO, "Sistema operativo", f"SO antiguo ({g.os_label}): drivers VirtIO y soporte limitados; probar en la ola piloto.")
            if g.kind == "CT" and target_major >= 9 and re.search(r"centos|el7|7\.", (g.ostype + " " + g.guest_os).lower()):
                add(AVISO, "Contenedor", "Contenedor con sistema antiguo: PVE 9 solo admite cgroup v2 (systemd moderno). Verificar que arranca.")
            if g.kind == "VM" and not g.agent:
                add(INFO, "Agente", "Sin agente QEMU: no se conocen IPs ni espacio usado y el apagado/fs-freeze es menos fiable.")
            if not g.last_backup:
                add(AVISO, "Backup", "Sin backup registrado: hacer copia antes de migrar.")
            if g.disk_prov_gib > 4096:
                add(INFO, "Tamaño", f"Disco grande ({g.disk_prov_gib/1024:.1f} TiB): planificar ventana amplia o migración en caliente.")
            if g.ha:
                add(INFO, "HA", "Recurso HA: retirarlo de HA en origen antes de migrar y darlo de alta en destino.")
        # generales
        gen = lambda sev, cat, msg: out.append({"Severidad": sev, "Clúster": "(general)", "VMID": "", "Nombre": "",  # noqa: E731
                                                "Categoría": cat, "Detalle": msg})
        for p in self.eval["problemas"]:
            gen(BLOQUEO, "Capacidad", p)
        for a in self.eval["avisos"]:
            gen(AVISO, "Capacidad", a)
        vers = self.an.pve_versions()
        if any(v.startswith(("6.", "7.")) for v in vers):
            gen(AVISO, "Versiones", f"Origen en PVE {', '.join(vers)}: «qm remote-migrate» requiere PVE 7.3 o superior; si no, backup/restore.")
        if self.pbs:
            for a in self.pbs["avisos"]:
                gen(AVISO, "PBS", a)
        h = self.an.health_counts()
        if h.get("CRÍTICO"):
            gen(AVISO, "Salud origen", f"El inventario tiene {h['CRÍTICO']} avisos críticos (hoja vHealth): revisar antes de migrar.")
        for n in self.req.notes:
            gen(INFO, "Dimensionado", n)
        order = {BLOQUEO: 0, AVISO: 1, INFO: 2}
        out.sort(key=lambda r: (order[r["Severidad"]], r["Clúster"], str(r["VMID"])))
        return out

    # ------------------------------------------------------------------ migración
    def _method(self):
        m = self.sc["migracion"]["metodo"]
        if m == "auto":
            m = "pbs" if self.pbs else "remote-migrate"
        if m == "pbs":
            return {"id": "pbs", "nombre": "Backup y restauración a través del nuevo Proxmox Backup Server",
                    "pasos": [
                        "Instalar el PBS nuevo y añadirlo como almacenamiento en el clúster de ORIGEN y en el de DESTINO.",
                        "Días antes: backup completo de cada VM al PBS nuevo (la deduplicación hace que los siguientes sean incrementales).",
                        "En la ventana: apagar la VM, backup final (solo bloques cambiados), restaurar en destino "
                        "(con «live-restore» la VM arranca mientras se restaura).",
                        "Ajustar bridge/VLAN si cambia, arrancar, validar y retirar la VM origen (no borrar hasta el cierre).",
                    ],
                    "ventajas": "No requiere conectividad directa entre clústeres; deja el backup del entorno nuevo funcionando desde el primer día; "
                                "permite volver atrás arrancando la VM de origen.",
                    "parada": "Minutos a horas por VM (backup final + restauración; con live-restore, solo el backup final)."}
        return {"id": "remote-migrate", "nombre": "Migración entre clústeres con «qm/pct remote-migrate»",
                "pasos": [
                    "Crear en DESTINO un usuario/API token con permisos de migración y obtener la huella del certificado.",
                    "Para cada VM: qm remote-migrate <vmid> <vmid-destino> 'host=<ip>,apitoken=PVEAPIToken=<id>=<secret>,fingerprint=<huella>' "
                    "--target-bridge vmbr1 --target-storage <almacenamiento> --online",
                    "Los contenedores se migran con «pct remote-migrate … --restart» (parada breve).",
                    "Validar, retirar HA en origen / darlo de alta en destino y eliminar la VM de origen tras el cierre.",
                ],
                "ventajas": "Migración en caliente de VMs (parada de segundos); no necesita almacenamiento intermedio.",
                "parada": "Segundos para VMs en caliente; reinicio para contenedores. Función marcada como experimental en Proxmox: probar en la ola piloto."}

    def _waves(self):
        mig = self.sc["migracion"]
        gibh = mig["mbps_por_flujo"] * 1e6 * 3600 / 2**30 * max(mig["flujos"], 1)
        blockers = {r["VMID"] and f"{r['Clúster']}/{r['VMID']}" for r in self.issues if r["Severidad"] == BLOQUEO}

        def crit(g):
            return g.ha or bool(CRIT_TAGS.search(g.tags) or CRIT_TAGS.search(g.name)) or bool(g.onboot and g.startup_order)

        def is_test(g):
            return bool(TEST_TAGS.search(f"{g.tags} {g.pool} {g.name}"))

        pool = list(self.an.guests)
        pilot_c = sorted([g for g in pool if not crit(g) and g.key not in blockers],
                         key=lambda g: (not is_test(g), g.running, g.disk_effective_gib))[:min(5, max(1, len(pool) // 10))]
        pilot_keys = {g.key for g in pilot_c}
        rest = [g for g in pool if g.key not in pilot_keys]
        # orden: no críticas primero, agrupadas por clúster/pool; críticas al final; bloqueadas en una ola aparte
        rest.sort(key=lambda g: (g.key in blockers, bool(crit(g)), g.cluster, g.pool, g.name.lower()))
        waves = []
        if pilot_c:
            waves.append({"nombre": "Ola 0 · Piloto", "tipo": "Piloto", "guests": pilot_c})
        cur, gib = [], 0.0
        cur_kind = None
        for g in rest:
            kind = "Con bloqueos" if g.key in blockers else ("Críticas" if crit(g) else "Estándar")
            if cur and (len(cur) >= mig["max_vms_ola"] or gib + g.disk_effective_gib > mig["max_gib_ola"] or kind != cur_kind):
                waves.append({"nombre": "", "tipo": cur_kind, "guests": cur})
                cur, gib = [], 0.0
            cur.append(g)
            gib += g.disk_effective_gib
            cur_kind = kind
        if cur:
            waves.append({"nombre": "", "tipo": cur_kind, "guests": cur})
        start = None
        try:
            if mig.get("inicio"):
                start = dt.date.fromisoformat(mig["inicio"])
        except ValueError:
            start = None
        per_week = max(int(mig["olas_por_semana"]), 1)
        gap = 7 / per_week
        for i, w in enumerate(waves):
            if not w["nombre"]:
                w["nombre"] = f"Ola {i}" + (f" · {w['tipo']}" if w["tipo"] != "Estándar" else "")
            data = sum(g.disk_effective_gib for g in w["guests"])
            w["gib"] = data
            w["horas"] = data / gibh if gibh else 0
            w["vcpu"] = sum(g.vcpu for g in w["guests"])
            w["ram"] = sum(g.ram_gib for g in w["guests"])
            if waves[0]["tipo"] == "Piloto" and i:
                w["dia"] = 7 + round((i - 1) * gap)   # una semana de observación tras el piloto
            else:
                w["dia"] = round(i * gap)
            w["fecha"] = (start + dt.timedelta(days=w["dia"])) if start else None
        return waves

    # ------------------------------------------------------------------ resumen
    def summary(self) -> dict:
        t = self.an.totals()
        e = self.eval
        s = {
            "cliente": self.sc.get("cliente") or "", "modo": self.sc["modo"], "pve": self.sc["pve_version"],
            "pbs_ver": PBS_VERSIONS.get(self.sc["pve_version"], "4.x"),
            "almacenamiento": STORAGE_TYPES.get(self.storage_type, self.storage_type),
            "vms": t["vms"], "cts": t["cts"], "vcpu": t["vcpu"], "ram_gib": t["ram_gib"],
            "disk_prov_tib": t["disk_prov_gib"] / 1024, "disk_eff_tib": t["disk_eff_gib"] / 1024,
            "hosts_origen": t["hosts"], "clusters_origen": t["clusters"],
            "nodos": e["nodos"], "cores": e["cores"], "ram_dest_gib": e["ram_gib"],
            "util_tib": e["almacenamiento_util_gib"] / 1024, "datos_tib": self.req.data_gib / 1024,
            "cpu_pct": e["cpu_pct"], "ram_pct": e["ram_pct"], "cpu_pct_n1": e["cpu_pct_n1"], "ram_pct_n1": e["ram_pct_n1"],
            "ok": e["ok"], "olas": len(self.waves), "metodo": self.method["nombre"],
            "bloqueos": sum(1 for r in self.issues if r["Severidad"] == BLOQUEO),
            "avisos": sum(1 for r in self.issues if r["Severidad"] == AVISO),
            "suscripciones_pve": e["sockets"],
        }
        if self.waves and self.waves[-1].get("dia") is not None:
            s["semanas"] = math.ceil((self.waves[-1]["dia"] + 1) / 7)
        return s

    def text_summary(self) -> str:
        s = self.summary()
        lines = [
            f"Origen: {s['vms']} VMs y {s['cts']} CTs en {s['hosts_origen']} nodos ({s['clusters_origen']} clúster(es)); "
            f"{s['vcpu']:.0f} vCPU, {s['ram_gib']:.0f} GiB RAM, {s['disk_eff_tib']:.1f} TiB de datos "
            f"({s['disk_prov_tib']:.1f} TiB aprovisionados).",
            f"Necesidades (con crecimiento): {self.req.cores:.0f} cores físicos, {self.req.ram_need_gib:.0f} GiB de RAM, "
            f"{self.req.data_gib/1024:.1f} TiB útiles.",
        ]
        if self.options:
            for o in self.options:
                n = o["nodos"][0]
                lines.append(f"• {o['etiqueta']}: {n.count}× {n.model} · {n.cpu_label} · {n.ram_gib} GiB"
                             + (f" · {n.data_disks}× {n.data_disk_tb} TB {n.data_disk_type}" if n.data_disks else "")
                             + f"  ({o['eval']['sockets']} sockets)")
        lines.append(f"Destino: {s['nodos']} nodos, {s['cores']} cores, {s['ram_dest_gib']} GiB RAM, "
                     f"{s['util_tib']:.1f} TiB útiles ({s['almacenamiento']}), Proxmox VE {s['pve']}.")
        lines.append(f"Ocupación: CPU {s['cpu_pct']:.0f} % ({s['cpu_pct_n1']:.0f} % con N-{self.sc['capacidad']['n_mas']}), "
                     f"RAM {s['ram_pct']:.0f} % ({s['ram_pct_n1']:.0f} % con N-{self.sc['capacidad']['n_mas']}).")
        lines.append("Capacidad: " + ("OK" if s["ok"] else "INSUFICIENTE → " + "; ".join(self.eval["problemas"])))
        if self.pbs:
            p = self.pbs
            lines.append(f"PBS {s['pbs_ver']}: {p['util_necesario_gib']/1024:.1f} TiB útiles · {p['propuesta']['cores']} cores · "
                         f"{p['propuesta']['ram_gib']} GiB RAM · {p['propuesta']['discos']}")
        lines.append(f"Migración: {s['metodo']} en {s['olas']} olas"
                     + (f" (~{s['semanas']} semanas)" if s.get("semanas") else "") + ".")
        lines.append(f"Riesgos: {s['bloqueos']} bloqueos, {s['avisos']} avisos (ver hoja/apartado de riesgos).")
        return "\n".join(lines)
