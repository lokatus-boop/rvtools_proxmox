"""Word del informe de solo análisis (con gráficos). Requiere python-docx y matplotlib."""
from __future__ import annotations

import tempfile
from collections import Counter

from .assessment import CRIT, INFO, WARN, Assessment
from .branding import COMPANY
from .loader import num
from .report_docx import GREY, Doc, _shade

SEV_HEX = {CRIT: "F8CBAD", WARN: "FFE699", INFO: "DDEBF7"}
SEV_LABEL = {CRIT: "Crítico", WARN: "Aviso", INFO: "Informativo"}


def _objs(f, n=8):
    o = f["Objetos"]
    s = ", ".join(map(str, o[:n]))
    return s + (f" … (+{len(o) - n})" if len(o) > n else "")


class AssessmentDoc(Doc):
    TITLE = "Informe de la infraestructura Proxmox VE"

    def __init__(self, a: Assessment):
        self.a = a
        super().__init__(None, client=a.client)

    def build(self, path, charts_dir=None):
        a, an = self.a, self.a.an
        sh = a.sheets
        t = an.totals()
        tmp = charts_dir or tempfile.mkdtemp(prefix="pvemigplan_analisis_")
        from .charts_assessment import all_charts
        ch = all_charts(a, tmp)
        inv_date = f"{a.inventory_date:%d/%m/%Y}" if a.inventory_date else "—"
        self.cover("Informe de la infraestructura", "Análisis de la plataforma Proxmox VE actual",
                   [f"Cliente: {a.client or '—'}", f"Fecha del inventario: {inv_date}", f"Fecha del informe: {a.generated:%d/%m/%Y}",
                    f"Preparado por: {a.author + ' · ' if a.author else ''}{COMPANY}"],
                   "Informe generado a partir del inventario de PVE Inventory. Describe el estado de la infraestructura en el "
                   "momento del inventario; no incluye propuestas de migración ni de hardware."
                   + (" El inventario está anonimizado: nombres e IPs son seudónimos." if a.anonymized else ""))

        # 1. Resumen ejecutivo
        c = a.severity_counts()
        self.h("1. Resumen ejecutivo")
        self.p(f"La plataforma analizada consta de {t['clusters']} clúster(es) o nodo(s) independiente(s) con {t['hosts']} nodos "
               f"Proxmox VE ({', '.join(an.pve_versions()) or 'versión desconocida'}) que alojan {t['vms']} máquinas virtuales y "
               f"{t['cts']} contenedores, de los que {t['running']} estaban encendidos. Se han identificado {c.get(CRIT, 0)} hallazgos "
               f"críticos, {c.get(WARN, 0)} avisos y {c.get(INFO, 0)} puntos informativos. Valoración global: {a.score().lower()}.")
        st = an.storage_usage()
        st_tot = sum(r["Total (GiB)"] for r in st)
        st_used = sum(r["Usado (GiB)"] for r in st)
        self.kv([
            ("Clústeres / nodos independientes", ", ".join(an.clusters) or "—"),
            ("Nodos físicos", f"{t['hosts']} · {t['host_sockets']} sockets · {t['host_cores']} cores · {t['host_threads']} hilos"),
            ("Memoria física", f"{t['host_ram_gib']:.0f} GiB ({t['host_ram_used_gib']:.0f} GiB en uso, "
                               f"{t['host_ram_used_gib'] / t['host_ram_gib'] * 100 if t['host_ram_gib'] else 0:.0f} %)"),
            ("Uso medio de CPU", f"{sum(h.cpu_use_pct for h in an.hosts) / len(an.hosts):.0f} %" if an.hosts else "—"),
            ("VMs / contenedores", f"{t['vms']} VMs · {t['cts']} CTs · {t['running']} encendidos · {a.templates} plantillas"),
            ("Recursos asignados", f"{t['vcpu']:.0f} vCPU · {t['ram_gib']:.0f} GiB RAM · {t['disk_prov_gib'] / 1024:.1f} TiB de disco"),
            ("Ratio vCPU:hilo (encendidas)", f"{t['vcpu_running'] / t['host_threads']:.1f}:1" if t["host_threads"] else "—"),
            ("Almacenamiento", f"{st_tot / 1024:.1f} TiB en total · {st_used / 1024:.1f} TiB usados "
                               f"({st_used / st_tot * 100 if st_tot else 0:.0f} %) · Ceph: {'sí' if an.has_ceph() else 'no'}"),
            ("Backup", f"{len(sh.get('vBackup', []))} trabajo(s) · {an.backup_summary()['with_backup']} VMs/CTs con copia"
                       + (" · Proxmox Backup Server" if an.backup_summary()["uses_pbs"] else "")),
        ])
        self.img(ch, "estado_vms", 15, "Estado de las VMs, contenedores y plantillas.")
        self.img(ch, "hallazgos", 15, "Hallazgos por categoría y severidad.")
        top = [f for f in a.findings if f["Severidad"] in (CRIT, WARN)][:8]
        if top:
            self.h("Puntos principales", 3)
            self.bullets([f"{SEV_LABEL[f['Severidad']]} · {f['Hallazgo']}" + (f" ({f['Afectados']})" if f["Afectados"] else "")
                          for f in top])

        # 2. Clústeres y nodos
        self.h("2. Clústeres y nodos")
        if sh.get("vCluster"):
            self.table(["Clúster / nodo", "Tipo", "Nodos", "Online", "Quórum", "VMs", "CTs", "Hilos", "RAM (GiB)"],
                       [[r.get(k) for k in ("Clúster / nodo", "Tipo", "Nodos", "Nodos online", "Quórum", "VMs", "CTs",
                                            "Hilos CPU totales", "RAM total (GiB)")] for r in sh["vCluster"]], size=8)
        self.table(["Clúster", "Nodo", "PVE", "CPU", "Sockets", "Cores", "Hilos", "RAM (GiB)", "Suscripción"],
                   [[r.get(k) for k in ("Clúster", "Nodo", "Versión PVE", "Modelo CPU", "Sockets", "Cores", "Hilos", "RAM total (GiB)",
                                        "Suscripción")] for r in sh.get("vHost", [])], size=7.5)
        vend = Counter(h.vendor or "?" for h in an.hosts)
        self.p("Fabricantes de CPU: " + ", ".join(f"{k} ({v} nodos)" for k, v in vend.items()) + "." if vend else "")

        # 3. Capacidad y uso
        self.h("3. Capacidad y uso de recursos")
        self.p("Uso de CPU y memoria de cada nodo en el momento del inventario, y recursos asignados a las VMs encendidas.")
        self.img(ch, "uso_nodos", 15, "Uso de CPU y memoria por nodo.")
        self.img(ch, "origen_nodos", 16, "Capacidad física frente a recursos asignados y en uso.")
        self.img(ch, "sobreasignacion", 16, "Sobreasignación de CPU y memoria por nodo.")
        nr = a.node_rows()
        self.table(["Nodo", "Uso CPU %", "vCPU on", "vCPU:hilo", "RAM GiB", "Usada GiB", "Uso RAM %", "Asignada GiB", "VMs/CTs"],
                   [[r["Nodo"], r["Uso CPU (%)"], r["vCPU encendidas"], r["Ratio vCPU:hilo"], r["RAM física (GiB)"], r["RAM usada (GiB)"],
                     r["Uso RAM (%)"], r["RAM asignada encendidas (GiB)"], r["VMs/CTs"]] for r in nr], size=7.5)
        res = a.cluster_resilience()
        if res:
            self.h("Tolerancia a la caída de un nodo", 3)
            self.p("Ocupación de memoria que tendrían los nodos restantes si cayera el nodo con más RAM de cada clúster "
                   "(se considera suficiente hasta el 90 %).")
            self.table(list(res[0].keys()), [list(r.values()) for r in res], size=8)

        # 4. Máquinas virtuales
        self.h("4. Máquinas virtuales y contenedores")
        self.img(ch, "vms_nodo", 14, "Distribución de VMs y contenedores por nodo.")
        self.img(ch, "so_familia", 11, "Familia de sistema operativo.")
        self.img(ch, "origen_so", 14, "Detalle por sistema operativo.")
        self.img(ch, "origen_tamanos", 11, "Tamaño de las VMs por vCPU.")
        self.img(ch, "tamanos_ram", 11, "Tamaño de las VMs por memoria.")
        self.h("VMs con más memoria asignada", 3)
        self.table(["Clúster", "Nodo", "VMID", "Nombre", "Tipo", "Estado", "vCPU", "RAM (GiB)", "Disco (GiB)", "SO"],
                   [[g.cluster, g.node, g.vmid, g.name, g.kind, "on" if g.running else "off", g.vcpu, round(g.ram_gib, 1),
                     round(g.disk_prov_gib), g.os_label] for g in a.top_guests("ram")], size=7.5)
        self.h("VMs con más disco aprovisionado", 3)
        self.table(["Clúster", "VMID", "Nombre", "Disco aprov. (GiB)", "Disco usado (GiB)", "Almacenamientos"],
                   [[g.cluster, g.vmid, g.name, round(g.disk_prov_gib), round(g.disk_used_gib) if g.disk_used_gib else "—",
                     ", ".join(s for s, _ in g.storages)] for g in a.top_guests("disk")], size=7.5)
        ag = sum(1 for g in an.guests if g.kind == "VM" and g.agent)
        nvm = sum(1 for g in an.guests if g.kind == "VM")
        ha = sum(1 for g in an.guests if g.ha)
        self.p(f"Agente QEMU habilitado en {ag} de {nvm} VMs · {ha} VMs/CTs en alta disponibilidad · "
               f"{sum(g.snapshots for g in an.guests)} snapshots · {sum(1 for g in an.guests if g.passthrough)} con passthrough.")

        # 5. Almacenamiento
        self.h("5. Almacenamiento")
        self.img(ch, "almacenamiento_tipos", 14, "Capacidad por tipo de almacenamiento.")
        self.img(ch, "origen_almacenamiento", 15, "Ocupación de cada almacenamiento.")
        self.table(["Clúster", "Nodo", "Almacenamiento", "Tipo", "Compartido", "Contenido", "Total (GiB)", "Usado (GiB)", "Uso (%)"],
                   [[r["Clúster"], r["Nodo"], r["Almacenamiento"], r["Tipo"], r["Compartido"], r["Contenido"], round(r["Total (GiB)"]),
                     round(r["Usado (GiB)"]), r["Uso (%)"]] for r in st], size=7.5)
        if sh.get("vCephPool"):
            self.h("Ceph", 3)
            self.table(["Pool", "Réplicas", "Mín.", "PGs", "Autoscale", "Usado (GiB)", "Uso (%)"],
                       [[r.get(k) for k in ("Pool", "Réplicas (size)", "Mín. réplicas", "PGs", "Autoscale", "Usado (GiB)", "Uso (%)")]
                        for r in sh["vCephPool"]], size=8)
            osd = Counter(str(r.get("Clase") or "?") for r in sh.get("vCephOSD", []))
            self.p(f"OSDs: {sum(osd.values())} (" + ", ".join(f"{k}: {v}" for k, v in osd.items()) + ").")
        if sh.get("vZFS"):
            self.h("ZFS", 3)
            self.table(["Nodo", "Pool", "Estado", "Tamaño (GiB)", "Uso (%)", "Fragmentación (%)"],
                       [[r.get(k) for k in ("Nodo", "Pool", "Estado", "Tamaño (GiB)", "Uso (%)", "Fragmentación (%)")] for r in sh["vZFS"]], size=8)
        if sh.get("vPhysicalDisk"):
            pdc = Counter((str(r.get("Tipo") or "?")) for r in sh["vPhysicalDisk"])
            self.p(f"Discos físicos: {len(sh['vPhysicalDisk'])} (" + ", ".join(f"{k}: {v}" for k, v in pdc.items()) + ").")

        # 6. Red
        self.h("6. Red")
        self.img(ch, "redes", 14, "VMs y contenedores por red.")
        if sh.get("vBond"):
            self.h("Bonds", 3)
            self.table(["Nodo", "Bond", "Modo", "Esclavos", "Hash", "MTU"],
                       [[r.get(k) for k in ("Nodo", "Bond", "Modo", "Esclavos", "Hash (xmit_hash_policy)", "MTU")] for r in sh["vBond"]], size=7.5)
        if sh.get("vBridge"):
            self.h("Bridges", 3)
            self.table(["Nodo", "Bridge", "Puertos", "VLAN aware", "CIDR", "MTU", "VLANs usadas"],
                       [[r.get(k) for k in ("Nodo", "Bridge", "Puertos", "VLAN aware", "CIDR", "MTU", "VLANs usadas por VMs")]
                        for r in sh["vBridge"]], size=7.5)
        sub = an.subnets()
        if sub:
            self.p("Subredes de gestión/infraestructura de los nodos: " + ", ".join(sub) + ".")
        self.p(f"Jumbo frames en interfaces de los nodos: {'sí' if an.mtu_jumbo() else 'no'} · SDN: "
               f"{'sí' if sh.get('vSDN') else 'no'} · enlaces de corosync: "
               f"{max((int(num(r.get('Enlaces'), 0) or 0) for r in sh.get('vCorosync', [])), default=0) or '—'}.")

        # 7. Backup, snapshots y HA
        self.h("7. Copias de seguridad, snapshots y alta disponibilidad")
        self.img(ch, "backup_antiguedad", 12, "Antigüedad del último backup de cada VM/CT.")
        if sh.get("vBackup"):
            self.table(["Job", "Habilitado", "Planificación", "Almacenamiento", "Modo", "Selección", "Retención"],
                       [[r.get(k) for k in ("Job", "Habilitado", "Planificación", "Almacenamiento", "Modo", "Selección", "Retención")]
                        for r in sh["vBackup"]], size=7.5)
        else:
            self.p("No hay trabajos de backup programados en Proxmox VE.", bold=True)
        self.img(ch, "snapshots", 11, "Snapshots por antigüedad.")
        if sh.get("vHA"):
            states = Counter(str(r.get("Estado solicitado") or "?") for r in sh["vHA"] if r.get("Recurso"))
            self.p(f"Alta disponibilidad: {sum(states.values())} recursos (" + ", ".join(f"{k}: {v}" for k, v in states.items()) + ").")
        else:
            self.p("No hay recursos de alta disponibilidad configurados.")
        if sh.get("vReplication"):
            self.p(f"Trabajos de replicación: {len(sh['vReplication'])}.")

        # 8. Seguridad y mantenimiento
        self.h("8. Seguridad, soporte y mantenimiento")
        subs = Counter(str(r.get("Suscripción") or "sin datos") for r in sh.get("vHost", []))
        pend = sum(int(num(r.get("Actualizaciones pendientes"), 0) or 0) for r in sh.get("vHost", []))
        certs = [r for r in sh.get("vCert", []) if num(r.get("Días restantes")) is not None]
        self.kv([("Suscripciones", ", ".join(f"{k}: {v}" for k, v in subs.items()) or "—"),
                 ("Actualizaciones pendientes (total nodos)", str(pend)),
                 ("Usuarios y tokens", str(len(sh.get("vUsers", [])))),
                 ("Reglas de firewall", str(len(sh.get("vFirewall", [])))),
                 ("Certificado más próximo a caducar",
                  (lambda r: f"{r.get('Fichero')} ({r.get('Nodo')}): {r.get('Días restantes')} días")(min(certs, key=lambda r: num(r.get("Días restantes"))))
                  if certs else "—")])

        # 9. Hallazgos
        self.orientation(True)
        self.h("9. Hallazgos y recomendaciones")
        self.p("Hallazgos agrupados por tema, ordenados por severidad. Incluyen los avisos detectados por PVE Inventory "
               "y las comprobaciones de este análisis. El detalle de cada objeto afectado está en el Excel del informe.",
               italic=True, color=GREY)
        if a.findings:
            t = self.table(["Severidad", "Categoría", "Hallazgo", "Nº", "Objetos afectados", "Recomendación"],
                           [[SEV_LABEL.get(f["Severidad"], f["Severidad"]), f["Categoría"], f["Hallazgo"], f["Afectados"], _objs(f),
                             f["Recomendación"]] for f in a.findings], widths=[1.9, 2.5, 5.2, 0.9, 7.2, 7.5], size=7.5)
            for i, f in enumerate(a.findings, start=1):
                _shade(t.rows[i].cells[0], SEV_HEX.get(f["Severidad"], "FFFFFF"))
        else:
            self.p("No se han encontrado hallazgos.")

        # Anexo
        self.h("Anexo. Inventario de VMs y contenedores")
        self.table(["Clúster", "Nodo", "VMID", "Nombre", "Tipo", "Estado", "vCPU", "RAM (GiB)", "Disco (GiB)", "SO", "HA", "Último backup"],
                   [[g.cluster, g.node, g.vmid, g.name, g.kind, "plantilla" if g.template else ("on" if g.running else "off"), g.vcpu,
                     round(g.ram_gib, 1), round(g.disk_prov_gib), g.os_label, "Sí" if g.ha else "", g.last_backup[:10]]
                    for g in an.all_guests], size=7)
        self.d.save(path)
        return path
