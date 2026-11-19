"""Word del informe de solo análisis (con gráficos). Requiere python-docx y matplotlib."""
from __future__ import annotations

from pvetools.i18n import N_, _, fmt_date

import tempfile
from collections import Counter

from .assessment import CRIT, INFO, WARN, Assessment
from .branding import COMPANY
from .loader import num
from .report_docx import GREY, Doc, _shade
from pvetools.safefile import atomic_save

SEV_HEX = {CRIT: "F8CBAD", WARN: "FFE699", INFO: "DDEBF7"}
SEV_LABEL = {CRIT: N_("Crítico"), WARN: N_("Aviso"), INFO: N_("Informativo")}


def _objs(f, n=8):
    o = f["Objetos"]
    s = ", ".join(map(str, o[:n]))
    return s + (f" … (+{len(o) - n})" if len(o) > n else "")


class AssessmentDoc(Doc):
    TITLE = N_("Informe de la infraestructura Proxmox VE")

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
        inv_date = fmt_date(a.inventory_date) if a.inventory_date else "—"
        self.cover(_("Informe de la infraestructura"), _("Análisis de la plataforma Proxmox VE actual"),
                   [_("Cliente: {v}", v=a.client or '—'), _("Fecha del inventario: {inv_date}", inv_date=inv_date), _("Fecha del informe: {generated}", generated=fmt_date(a.generated)),
                    _("Preparado por: {v}{COMPANY}", v=a.author + ' · ' if a.author else '', COMPANY=COMPANY)],
                   _("Informe generado a partir del inventario de PVE Inventory. Describe el estado de la infraestructura en el "
                   "momento del inventario; no incluye propuestas de migración ni de hardware.")
                   + (_(" El inventario está anonimizado: nombres e IPs son seudónimos.") if a.anonymized else ""))

        # 1. Resumen ejecutivo
        c = a.severity_counts()
        self.h(_("1. Resumen ejecutivo"))
        self.p(_("La plataforma analizada consta de {clusters} clúster(es) o nodo(s) independiente(s) con {hosts} nodos Proxmox VE ({v}) que alojan {vms} máquinas virtuales y {cts} contenedores, de los que {running} estaban encendidos. Se han identificado {get} hallazgos críticos, {get2} avisos y {get3} puntos informativos. Valoración global: {lower}.", clusters=t['clusters'], hosts=t['hosts'], v=', '.join(an.pve_versions()) or _('versión desconocida'), vms=t['vms'], cts=t['cts'], running=t['running'], get=c.get(CRIT, 0), get2=c.get(WARN, 0), get3=c.get(INFO, 0), lower=a.score().lower()))
        st = an.storage_usage()
        st_tot = sum(r["Total (GiB)"] for r in st)
        st_used = sum(r["Usado (GiB)"] for r in st)
        self.kv([
            (_("Clústeres / nodos independientes"), ", ".join(an.clusters) or "—"),
            (_("Nodos físicos"), _("{hosts} · {host_sockets} sockets · {host_cores} cores · {host_threads} hilos", hosts=t['hosts'], host_sockets=t['host_sockets'], host_cores=t['host_cores'], host_threads=t['host_threads'])),
            (_("Memoria física"), _("{host_ram_gib:.0f} GiB ({host_ram_used_gib:.0f} GiB en uso, {v:.0f} %)", host_ram_gib=t['host_ram_gib'], host_ram_used_gib=t['host_ram_used_gib'], v=t['host_ram_used_gib'] / t['host_ram_gib'] * 100 if t['host_ram_gib'] else 0)),
            (_("Uso medio de CPU"), f"{sum(h.cpu_use_pct for h in an.hosts) / len(an.hosts):.0f} %" if an.hosts else "—"),
            (_("VMs / contenedores"), _("{vms} VMs · {cts} CTs · {running} encendidos · {templates} plantillas", vms=t['vms'], cts=t['cts'], running=t['running'], templates=a.templates)),
            (_("Recursos asignados"), _("{vcpu:.0f} vCPU · {ram_gib:.0f} GiB RAM · {disk_prov_gib:.1f} TiB de disco", vcpu=t['vcpu'], ram_gib=t['ram_gib'], disk_prov_gib=t['disk_prov_gib'] / 1024)),
            (_("Ratio vCPU:hilo (encendidas)"), f"{t['vcpu_running'] / t['host_threads']:.1f}:1" if t["host_threads"] else "—"),
            ("Almacenamiento", _("{st_tot:.1f} TiB en total · {st_used:.1f} TiB usados ({v:.0f} %) · Ceph: {v2}", st_tot=st_tot / 1024, st_used=st_used / 1024, v=st_used / st_tot * 100 if st_tot else 0, v2=_('sí') if an.has_ceph() else _('no'))),
            ("Backup", _("{n_get} trabajo(s) · {with_backup} VMs/CTs con copia", n_get=len(sh.get('vBackup', [])), with_backup=an.backup_summary()['with_backup'])
                       + (_(" · Proxmox Backup Server") if an.backup_summary()["uses_pbs"] else "")),
        ])
        self.img(ch, "estado_vms", 15, _("Estado de las VMs, contenedores y plantillas."))
        self.img(ch, "hallazgos", 15, _("Hallazgos por categoría y severidad."))
        top = [f for f in a.findings if f["Severidad"] in (CRIT, WARN)][:8]
        if top:
            self.h(_("Puntos principales"), 3)
            self.bullets([f"{_(SEV_LABEL[f['Severidad']])} · {f['Hallazgo']}" + (f" ({f['Afectados']})" if f["Afectados"] else "")
                          for f in top])

        # 2. Clústeres y nodos
        self.h(_("2. Clústeres y nodos"))
        if sh.get("vCluster"):
            self.table(["Clúster / nodo", "Tipo", "Nodos", _("Online"), "Quórum", "VMs", "CTs", "Hilos", "RAM (GiB)"],
                       [[r.get(k) for k in ("Clúster / nodo", "Tipo", "Nodos", "Nodos online", "Quórum", "VMs", "CTs",
                                            "Hilos CPU totales", "RAM total (GiB)")] for r in sh["vCluster"]], size=8)
        self.table(["Clúster", "Nodo", "PVE", "CPU", "Sockets", "Cores", "Hilos", "RAM (GiB)", "Suscripción"],
                   [[r.get(k) for k in ("Clúster", "Nodo", "Versión PVE", "Modelo CPU", "Sockets", "Cores", "Hilos", "RAM total (GiB)",
                                        "Suscripción")] for r in sh.get("vHost", [])], size=7.5)
        vend = Counter(h.vendor or "?" for h in an.hosts)
        self.p(_("Fabricantes de CPU: ") + ", ".join(f"{k} (" + _("{v} nodo(s)", v=v) + ")" for k, v in vend.items()) + "." if vend else "")

        # 3. Capacidad y uso
        self.h(_("3. Capacidad y uso de recursos"))
        self.p(_("Uso de CPU y memoria de cada nodo en el momento del inventario, y recursos asignados a las VMs encendidas."))
        self.img(ch, "uso_nodos", 15, _("Uso de CPU y memoria por nodo."))
        self.img(ch, "origen_nodos", 16, _("Capacidad física frente a recursos asignados y en uso."))
        self.img(ch, "sobreasignacion", 16, _("Sobreasignación de CPU y memoria por nodo."))
        nr = a.node_rows()
        self.table(["Nodo", _("Uso CPU %"), _("vCPU on"), "vCPU:hilo", _("RAM GiB"), _("Usada GiB"), _("Uso RAM %"), _("Asignada GiB"), "VMs/CTs"],
                   [[r["Nodo"], r["Uso CPU (%)"], r["vCPU encendidas"], r["Ratio vCPU:hilo"], r["RAM física (GiB)"], r["RAM usada (GiB)"],
                     r["Uso RAM (%)"], r["RAM asignada encendidas (GiB)"], r["VMs/CTs"]] for r in nr], size=7.5)
        res = a.cluster_resilience()
        if res:
            self.h(_("Tolerancia a la caída de un nodo"), 3)
            self.p(_("Ocupación de memoria que tendrían los nodos restantes si cayera el nodo con más RAM de cada clúster "
                   "(se considera suficiente hasta el 90 %)."))
            self.table(list(res[0].keys()), [list(r.values()) for r in res], size=8)

        # 4. Máquinas virtuales
        self.h(_("4. Máquinas virtuales y contenedores"))
        self.img(ch, "vms_nodo", 14, _("Distribución de VMs y contenedores por nodo."))
        self.img(ch, "so_familia", 11, _("Familia de sistema operativo."))
        self.img(ch, "origen_so", 14, _("Detalle por sistema operativo."))
        self.img(ch, "origen_tamanos", 11, _("Tamaño de las VMs por vCPU."))
        self.img(ch, "tamanos_ram", 11, _("Tamaño de las VMs por memoria."))
        self.h(_("VMs con más memoria asignada"), 3)
        self.table(["Clúster", "Nodo", "VMID", "Nombre", "Tipo", "Estado", "vCPU", "RAM (GiB)", _("Disco (GiB)"), "SO"],
                   [[g.cluster, g.node, g.vmid, g.name, g.kind, "on" if g.running else "off", g.vcpu, round(g.ram_gib, 1),
                     round(g.disk_prov_gib), g.os_label] for g in a.top_guests("ram")], size=7.5)
        self.h(_("VMs con más disco aprovisionado"), 3)
        self.table(["Clúster", "VMID", "Nombre", "Disco aprov. (GiB)", "Disco usado (GiB)", _("Almacenamientos")],
                   [[g.cluster, g.vmid, g.name, round(g.disk_prov_gib), round(g.disk_used_gib) if g.disk_used_gib else "—",
                     ", ".join(s for s, _ in g.storages)] for g in a.top_guests("disk")], size=7.5)
        ag = sum(1 for g in an.guests if g.kind == "VM" and g.agent)
        nvm = sum(1 for g in an.guests if g.kind == "VM")
        ha = sum(1 for g in an.guests if g.ha)
        self.p(_("Agente QEMU habilitado en {ag} de {nvm} VMs · {ha} VMs/CTs en alta disponibilidad · {n_v} snapshots · {n_v2} con passthrough.", ag=ag, nvm=nvm, ha=ha, n_v=sum(g.snapshots for g in an.guests), n_v2=sum(1 for g in an.guests if g.passthrough)))

        # 5. Almacenamiento
        self.h(_("5. Almacenamiento"))
        self.img(ch, "almacenamiento_tipos", 14, _("Capacidad por tipo de almacenamiento."))
        self.img(ch, "origen_almacenamiento", 15, _("Ocupación de cada almacenamiento."))
        self.table(["Clúster", "Nodo", "Almacenamiento", "Tipo", "Compartido", "Contenido", "Total (GiB)", "Usado (GiB)", "Uso (%)"],
                   [[r["Clúster"], r["Nodo"], r["Almacenamiento"], r["Tipo"], r["Compartido"], r["Contenido"], round(r["Total (GiB)"]),
                     round(r["Usado (GiB)"]), r["Uso (%)"]] for r in st], size=7.5)
        if sh.get("vCephPool"):
            self.h("Ceph", 3)
            self.table(["Pool", _("Réplicas"), _("Mín."), "PGs", "Autoscale", "Usado (GiB)", "Uso (%)"],
                       [[r.get(k) for k in ("Pool", "Réplicas (size)", "Mín. réplicas", "PGs", "Autoscale", "Usado (GiB)", "Uso (%)")]
                        for r in sh["vCephPool"]], size=8)
            osd = Counter(str(r.get("Clase") or "?") for r in sh.get("vCephOSD", []))
            self.p(_("OSDs: {n_values} (", n_values=sum(osd.values())) + ", ".join(f"{k}: {v}" for k, v in osd.items()) + ").")
        if sh.get("vZFS"):
            self.h("ZFS", 3)
            self.table(["Nodo", "Pool", "Estado", "Tamaño (GiB)", "Uso (%)", "Fragmentación (%)"],
                       [[r.get(k) for k in ("Nodo", "Pool", "Estado", "Tamaño (GiB)", "Uso (%)", "Fragmentación (%)")] for r in sh["vZFS"]], size=8)
        if sh.get("vPhysicalDisk"):
            pdc = Counter((str(r.get("Tipo") or "?")) for r in sh["vPhysicalDisk"])
            self.p(_("Discos físicos: {n_vphysicaldisk} (", n_vphysicaldisk=len(sh['vPhysicalDisk'])) + ", ".join(f"{k}: {v}" for k, v in pdc.items()) + ").")

        # 6. Red
        self.h(_("6. Red"))
        self.img(ch, "redes", 14, _("VMs y contenedores por red."))
        if sh.get("vBond"):
            self.h(_("Bonds"), 3)
            self.table(["Nodo", "Bond", "Modo", "Esclavos", _("Hash"), "MTU"],
                       [[r.get(k) for k in ("Nodo", "Bond", "Modo", "Esclavos", "Hash (xmit_hash_policy)", "MTU")] for r in sh["vBond"]], size=7.5)
        if sh.get("vBridge"):
            self.h(_("Bridges"), 3)
            self.table(["Nodo", "Bridge", "Puertos", "VLAN aware", "CIDR", "MTU", _("VLANs usadas")],
                       [[r.get(k) for k in ("Nodo", "Bridge", "Puertos", "VLAN aware", "CIDR", "MTU", "VLANs usadas por VMs")]
                        for r in sh["vBridge"]], size=7.5)
        sub = an.subnets()
        if sub:
            self.p(_("Subredes de gestión/infraestructura de los nodos: ") + ", ".join(sub) + ".")
        self.p(_("Jumbo frames en interfaces de los nodos: {v} · enlaces de corosync: {v2}.", v=_('sí') if an.mtu_jumbo() else _('no'), v2=max((int(num(r.get('Enlaces'), 0) or 0) for r in sh.get('vCorosync', [])), default=0) or '—'))
        self.h(_("SDN (Software Defined Network)"), 3)
        if an.has_sdn():
            sdn = an.sdn()
            on_sdn = sum(v["nics"] for v in sdn["vnets"])
            total = len(sh.get("vNetwork", []))
            self.p(_("El entorno tiene SDN configurado: {sdn_summary}. {on_sdn} de {total} interfaces de red de VMs/CTs están conectadas a VNets de SDN", sdn_summary=an.sdn_summary(), on_sdn=on_sdn, total=total)
                   + (_(" y el resto directamente a bridges de los nodos.") if on_sdn < total else "."))
            if any(z["pending"] for z in sdn["zones"]) or any(o["pending"] for o in sdn["objects"]):
                self.p(_("Hay cambios de SDN guardados que no se han aplicado: la red activa no coincide con la configurada."),
                       bold=True)
            self.sdn_tables(an, level=4)
        else:
            self.p(_("No hay SDN configurado (o el usuario del inventario no tenía el permiso SDN.Audit): las VMs se conectan "
                   "directamente a los bridges de cada nodo y las VLANs se definen en cada VM."))

        # 7. Backup, snapshots y HA
        self.h(_("7. Copias de seguridad, snapshots y alta disponibilidad"))
        self.img(ch, "backup_antiguedad", 12, _("Antigüedad del último backup de cada VM/CT."))
        if sh.get("vBackup"):
            self.table(["Job", "Habilitado", "Planificación", "Almacenamiento", "Modo", "Selección", "Retención"],
                       [[r.get(k) for k in ("Job", "Habilitado", "Planificación", "Almacenamiento", "Modo", "Selección", "Retención")]
                        for r in sh["vBackup"]], size=7.5)
        else:
            self.p(_("No hay trabajos de backup programados en Proxmox VE."), bold=True)
        self.img(ch, "snapshots", 11, _("Snapshots por antigüedad."))
        if sh.get("vHA"):
            states = Counter(str(r.get("Estado solicitado") or "?") for r in sh["vHA"] if r.get("Recurso"))
            self.p(_("Alta disponibilidad: {n_values} recursos (", n_values=sum(states.values())) + ", ".join(f"{k}: {v}" for k, v in states.items()) + ").")
        else:
            self.p(_("No hay recursos de alta disponibilidad configurados."))
        if sh.get("vReplication"):
            self.p(_("Trabajos de replicación: {n_vreplication}.", n_vreplication=len(sh['vReplication'])))

        # 8. Seguridad y mantenimiento
        self.h(_("8. Seguridad, soporte y mantenimiento"))
        subs = Counter(str(r.get("Suscripción") or _("sin datos")) for r in sh.get("vHost", []))
        pend = sum(int(num(r.get("Actualizaciones pendientes"), 0) or 0) for r in sh.get("vHost", []))
        certs = [r for r in sh.get("vCert", []) if num(r.get("Días restantes")) is not None]
        self.kv([(_("Suscripciones"), ", ".join(f"{k}: {v}" for k, v in subs.items()) or "—"),
                 (_("Actualizaciones pendientes (total nodos)"), str(pend)),
                 (_("Usuarios y tokens"), str(len(sh.get("vUsers", [])))),
                 (_("Reglas de firewall"), str(len(sh.get("vFirewall", [])))),
                 (_("Certificado más próximo a caducar"),
                  (lambda r: f"{r.get('Fichero')} ({r.get('Nodo')}): {r.get('Días restantes')} días")(min(certs, key=lambda r: num(r.get("Días restantes"))))
                  if certs else "—")])

        # 9. Hallazgos
        self.orientation(True)
        self.h(_("9. Hallazgos y recomendaciones"))
        self.p(_("Hallazgos agrupados por tema, ordenados por severidad. Incluyen los avisos detectados por PVE Inventory "
               "y las comprobaciones de este análisis. El detalle de cada objeto afectado está en el Excel del informe."),
               italic=True, color=GREY)
        if a.findings:
            t = self.table(["Severidad", "Categoría", "Hallazgo", "Nº", _("Objetos afectados"), "Recomendación"],
                           [[_(SEV_LABEL.get(f["Severidad"], f["Severidad"])), f["Categoría"], f["Hallazgo"], f["Afectados"], _objs(f),
                             f["Recomendación"]] for f in a.findings], widths=[1.9, 2.5, 5.2, 0.9, 7.2, 7.5], size=7.5)
            for i, f in enumerate(a.findings, start=1):
                _shade(t.rows[i].cells[0], SEV_HEX.get(f["Severidad"], "FFFFFF"))
        else:
            self.p(_("No se han encontrado hallazgos."))

        # Anexo
        self.h(_("Anexo. Inventario de VMs y contenedores"))
        self.table(["Clúster", "Nodo", "VMID", "Nombre", "Tipo", "Estado", "vCPU", "RAM (GiB)", _("Disco (GiB)"), "SO", "HA", "Último backup"],
                   [[g.cluster, g.node, g.vmid, g.name, g.kind, _("plantilla") if g.template else ("on" if g.running else "off"), g.vcpu,
                     round(g.ram_gib, 1), round(g.disk_prov_gib), g.os_label, "Sí" if g.ha else "", g.last_backup[:10]]
                    for g in an.all_guests], size=7)
        path = atomic_save(path, self.d.save)
        return path
