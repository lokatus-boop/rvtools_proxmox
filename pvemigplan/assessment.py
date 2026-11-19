"""Análisis de la infraestructura actual (modo «solo análisis», tipo health check).

Solo describe lo que hay en el inventario: capacidad, uso, distribución, almacenamiento, red, backup y
hallazgos. No propone migración, hardware ni olas.
"""
from __future__ import annotations

import datetime as dt
import re
from collections import Counter, defaultdict

from pvetools.i18n import N_, _, data_out

from .analysis import LEGACY_OS, Analysis
from .loader import num, yes

CRIT, WARN, INFO = "CRÍTICO", "AVISO", "INFO"
SEV_ORDER = {CRIT: 0, WARN: 1, INFO: 2}

# Ciclo de vida de Proxmox VE (fin de soporte publicado por Proxmox)
PVE_EOL = {5: N_("julio de 2020"), 6: N_("julio de 2022"), 7: N_("julio de 2024"), 8: N_("agosto de 2026")}
PVE_EOL_DATE = {5: dt.date(2020, 7, 31), 6: dt.date(2022, 7, 31), 7: dt.date(2024, 7, 31), 8: dt.date(2026, 8, 31)}

# Avisos de la hoja vHealth (PVE Inventory) agrupados en hallazgos: (patrón, categoría, título, recomendación)
HEALTH_RULES = [
    (r"no tiene quórum", N_("Clúster"), N_("Clúster sin quórum"),
     N_("Recuperar el quórum (nodos caídos, red de corosync) antes de cualquier cambio.")),
    (r"^Nodo en estado", N_("Nodos"), N_("Nodos fuera de línea"), N_("Revisar el nodo y su conectividad con el clúster.")),
    (r"Uso de RAM al", N_("Capacidad"), N_("Nodos con uso de memoria muy alto (≥ 90 %)"),
     N_("Repartir carga entre nodos, reducir memoria asignada o ampliar RAM.")),
    (r"Disco raíz al", N_("Nodos"), N_("Disco del sistema de los nodos casi lleno"),
     N_("Liberar espacio (logs, kernels antiguos, ISOs/backups locales) en el disco del sistema.")),
    (r"Sobreasignación de CPU", N_("Capacidad"), N_("Sobreasignación de CPU superior a 4:1"),
     N_("Revisar el rendimiento (CPU ready / steal) y equilibrar las vCPU entre nodos.")),
    (r"^Suscripción", N_("Soporte"), N_("Nodos sin suscripción activa"),
     N_("Activar la suscripción para tener repositorio enterprise y soporte del fabricante.")),
    (r"Versiones de PVE mezcladas", N_("Versiones"), N_("Versiones de Proxmox VE mezcladas en un clúster"),
     N_("Igualar la versión de todos los nodos del clúster.")),
    (r"^Ocupado al", N_("Almacenamiento"), N_("Almacenamientos con ocupación alta"),
     N_("Liberar espacio o ampliar el almacenamiento; no superar el 80 % de ocupación.")),
    (r"^Estado '", N_("Almacenamiento"), N_("Almacenamientos no disponibles"), N_("Revisar la conexión o configuración del almacenamiento.")),
    (r"^Snapshot '", N_("Snapshots"), N_("Snapshots antiguas"), N_("Consolidar o eliminar las snapshots que ya no se necesiten.")),
    (r"Guest agent no habilitado", N_("VMs"), N_("VMs encendidas sin agente QEMU"),
     N_("Instalar y habilitar qemu-guest-agent (apagados limpios, IPs, consistencia de backups).")),
    (r"Guest agent habilitado pero no responde", N_("VMs"), N_("Agente QEMU habilitado pero sin respuesta"),
     N_("Instalar o arrancar el servicio qemu-guest-agent dentro de la VM.")),
    (r"^Bloqueada", N_("VMs"), N_("VMs/CTs bloqueadas"), N_("Revisar la tarea que dejó el bloqueo y liberarlo (qm unlock / pct unlock).")),
    (r"^Disco sin usar", N_("Almacenamiento"), N_("Discos sin usar asociados a VMs"), N_("Eliminar los discos huérfanos para recuperar espacio.")),
    (r"^ISO montada", N_("VMs"), N_("ISOs montadas en las VMs"), N_("Desmontar las ISOs que no se usen (impiden migraciones en vivo).")),
    (r"ningún job de backup", N_("Backup"), N_("VMs/CTs fuera de cualquier trabajo de backup"), N_("Incluirlas en un trabajo de backup.")),
    (r"Sin ninguna copia de backup", N_("Backup"), N_("VMs/CTs sin ninguna copia de backup"), N_("Revisar los trabajos de backup y su resultado.")),
    (r"Último backup hace", N_("Backup"), N_("Copias de backup antiguas"), N_("Revisar por qué fallan o no se ejecutan los trabajos de backup.")),
    (r"verificación del último backup", N_("Backup"), N_("Verificación de backup fallida"), N_("Revisar el datastore del PBS y repetir la copia.")),
    (r"^HEALTH_", N_("Ceph"), N_("Ceph no está en estado HEALTH_OK"), N_("Revisar «ceph -s» y resolver los avisos.")),
    (r"^OSD .*in=", N_("Ceph"), N_("OSDs de Ceph caídos o fuera"), N_("Revisar el disco y el servicio del OSD.")),
    (r"^OSD al", N_("Ceph"), N_("OSDs de Ceph con ocupación alta"), N_("Ampliar capacidad o rebalancear (Ceph se bloquea al 95 %).")),
    (r"^SMART", N_("Discos físicos"), N_("Discos con SMART en error"), N_("Sustituir el disco cuanto antes.")),
    (r"Desgaste del SSD", N_("Discos físicos"), N_("SSD con desgaste alto (≥ 80 %)"), N_("Planificar la sustitución de los SSD.")),
    (r"Pool en estado", N_("ZFS"), N_("Pools ZFS degradados"), N_("Sustituir el disco afectado y revisar «zpool status».")),
    (r"Pool ocupado", N_("ZFS"), N_("Pools ZFS por encima del 80 %"), N_("Liberar espacio o ampliar el pool.")),
    (r"Cambios de SDN pendientes", N_("Red"), N_("Cambios de SDN pendientes de aplicar"),
     N_("Revisar los cambios y aplicarlos (Datacenter → SDN → Aplicar) o descartarlos: la red activa no es la configurada.")),
    (r"no aparecen como bridge ni como VNet", N_("Red"), N_("VMs en redes que el inventario no puede ver (¿SDN sin permiso?)"),
     N_("Dar el permiso SDN.Audit al usuario o token del inventario y repetir la recogida.")),
    (r"Bond con una sola", N_("Red"), N_("Bonds sin redundancia"), N_("Añadir una segunda interfaz al bond.")),
    (r"corosync", N_("Clúster"), N_("Corosync con un solo enlace"), N_("Configurar un segundo enlace de corosync en una red independiente.")),
    (r"Firewall de datacenter", N_("Seguridad"), N_("Firewall de datacenter deshabilitado"),
     N_("Valorar activar el firewall de Proxmox VE con reglas explícitas.")),
    (r"Token sin privilegios", N_("Seguridad"), N_("Tokens de API con todos los permisos del usuario"),
     N_("Usar tokens con privilegios separados y solo los permisos necesarios.")),
    (r"tareas con error", N_("Operación"), N_("Tareas con error o avisos en los últimos 7 días"),
     N_("Revisar el registro de tareas (hoja vTasks del inventario).")),
    (r"passthrough sin mapping", N_("VMs"), N_("Passthrough PCI sin mapeo de recursos"),
     N_("Crear un mapeo de recursos (Datacenter → Resource Mappings) para el dispositivo.")),
    (r"Repositorio .* sin suscripción", N_("Actualizaciones"), N_("Repositorio enterprise sin suscripción"),
     N_("Activar la suscripción o configurar el repositorio no-subscription.")),
    (r"Repositorio de pruebas", N_("Actualizaciones"), N_("Repositorio de pruebas habilitado"), N_("Deshabilitar el repositorio de pruebas en producción.")),
    (r"actualizaciones pendientes", N_("Actualizaciones"), N_("Nodos con actualizaciones pendientes"),
     N_("Aplicar las actualizaciones nodo a nodo en una ventana de mantenimiento.")),
    (r"^Caducado", N_("Certificados"), N_("Certificados caducados"), N_("Renovar los certificados.")),
    (r"^Caduca en", N_("Certificados"), N_("Certificados próximos a caducar"), N_("Renovar los certificados antes de su caducidad.")),
]


def _major(v: str) -> int | None:
    m = re.match(r"\s*(\d+)", str(v or ""))
    return int(m.group(1)) if m else None


def _parse_date(v):
    if isinstance(v, dt.datetime):
        return v
    if isinstance(v, dt.date):
        return dt.datetime(v.year, v.month, v.day)
    s = str(v or "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%d/%m/%Y %H:%M", "%d/%m/%Y"):
        try:
            return dt.datetime.strptime(s[:len(dt.datetime(2000, 1, 1).strftime(fmt))], fmt)
        except ValueError:
            continue
    return None


class Assessment:
    """Informe de la infraestructura actual a partir del inventario (sin plan de migración)."""

    def __init__(self, sheets: dict, client: str = "", author: str = ""):
        self.sheets = sheets
        self.client = client or ""
        self.author = author or ""
        self.generated = dt.datetime.now()
        self.an = Analysis(sheets, include_stopped=True, include_templates=False)
        src = (sheets.get("vSource") or [{}])
        self.anonymized = any(yes(r.get("Anonimizado")) for r in src)
        dates = [d for d in (_parse_date(r.get("Fecha")) for r in src) if d]
        self.inventory_date = max(dates) if dates else None
        self.ref_date = (self.inventory_date or self.generated).date()
        self.findings = self._findings()

    # ------------------------------------------------------------------ datos
    @property
    def templates(self) -> int:
        return sum(1 for g in self.an.all_guests if g.template)

    def node_rows(self) -> list[dict]:
        """Uso por nodo: hilos, vCPU asignadas, RAM física/usada/asignada."""
        assigned = defaultdict(lambda: [0, 0.0, 0.0, 0])  # vms, vcpu on, ram on, total guests
        for g in self.an.guests:
            d = assigned[(g.cluster, g.node)]
            d[3] += 1
            if g.running:
                d[0] += 1
                d[1] += g.vcpu
                d[2] += g.ram_gib
        rows = []
        for h in self.an.hosts:
            vms, vcpu, ram, total = assigned.get((h.cluster, h.node), [0, 0, 0, 0])
            rows.append({"Clúster": h.cluster, "Nodo": h.node, "Estado": "online" if h.online else "offline",
                         "PVE": h.pve_version, "CPU": h.cpu_model, "Sockets": h.sockets, "Cores": h.cores, "Hilos": h.threads,
                         "Uso CPU (%)": round(h.cpu_use_pct, 1), "vCPU encendidas": vcpu,
                         "Ratio vCPU:hilo": round(vcpu / h.threads, 2) if h.threads else None,
                         "RAM física (GiB)": round(h.ram_gib, 1), "RAM usada (GiB)": round(h.ram_used_gib, 1),
                         "Uso RAM (%)": round(h.ram_used_gib / h.ram_gib * 100, 1) if h.ram_gib else None,
                         "RAM asignada encendidas (GiB)": round(ram, 1),
                         "VMs/CTs": total, "Encendidas": vms})
        return rows

    def cluster_resilience(self) -> list[dict]:
        """¿Absorben los nodos restantes la memoria en uso si cae el mayor nodo de cada clúster?"""
        out = []
        for c in self.an.clusters:
            hs = [h for h in self.an.hosts if h.cluster == c and h.ram_gib]
            if len(hs) < 2:
                continue
            total = sum(h.ram_gib for h in hs)
            used = sum(h.ram_used_gib for h in hs)
            largest = max(h.ram_gib for h in hs)
            rest = total - largest
            pct = used / rest * 100 if rest else 999
            out.append({"Clúster": c, "Nodos": len(hs), "RAM física (GiB)": round(total), "RAM usada (GiB)": round(used),
                        "RAM sin el mayor nodo (GiB)": round(rest), "Ocupación con un nodo caído (%)": round(pct, 1),
                        "Resiste la caída de un nodo": "Sí" if pct <= 90 else "No"})
        return out

    def backup_age(self) -> dict:
        """VMs/CTs por antigüedad de la última copia (respecto a la fecha del inventario)."""
        b = {"Sin copia": 0, "≤ 1 día": 0, "2-7 días": 0, "8-30 días": 0, "> 30 días": 0}
        status = {(r.get("Clúster"), str(r.get("VMID"))): r for r in self.sheets.get("vBackupStatus", [])}
        for g in self.an.guests:
            r = status.get((g.cluster, g.vmid))
            age = num(r.get("Antigüedad (días)")) if r else None
            copies = num(r.get("Nº copias"), 0) if r else 0
            if age is None:
                last = _parse_date((r or {}).get("Último backup") or g.last_backup)
                if last:
                    age = max((self.ref_date - last.date()).days, 0)
            if age is None and not copies:
                b["Sin copia"] += 1
            elif age is None or age <= 1:
                b["≤ 1 día"] += 1
            elif age <= 7:
                b["2-7 días"] += 1
            elif age <= 30:
                b["8-30 días"] += 1
            else:
                b["> 30 días"] += 1
        return b

    def snapshot_age(self) -> dict:
        lbl = {k: _(k) for k in ("≤ 7 días", "8-30 días", "31-90 días", "> 90 días", "Sin fecha")}
        b = {v: 0 for v in lbl.values()}
        for r in self.sheets.get("vSnapshot", []):
            if str(r.get("Snapshot")) == "current":
                continue
            a = num(r.get("Antigüedad (días)"))
            k = "Sin fecha" if a is None else "≤ 7 días" if a <= 7 else "8-30 días" if a <= 30 else "31-90 días" if a <= 90 else "> 90 días"
            b[lbl[k]] += 1
        if not sum(b.values()):
            b[lbl["Sin fecha"]] = sum(g.snapshots for g in self.an.guests)
        return b

    def ram_buckets(self) -> dict:
        b = {"≤ 2 GiB": 0, "4 GiB": 0, "8 GiB": 0, "16 GiB": 0, "32 GiB": 0, "> 32 GiB": 0}
        for g in self.an.guests:
            r = g.ram_gib
            k = "≤ 2 GiB" if r <= 2 else "4 GiB" if r <= 4 else "8 GiB" if r <= 8 else "16 GiB" if r <= 16 else "32 GiB" if r <= 32 else "> 32 GiB"
            b[k] += 1
        return b

    def top_guests(self, key="ram", n=10) -> list:
        f = {"ram": lambda g: g.ram_gib, "vcpu": lambda g: g.vcpu, "disk": lambda g: g.disk_prov_gib}[key]
        return sorted(self.an.guests, key=f, reverse=True)[:n]

    def state_counts(self) -> dict:
        g = self.an.guests
        return {"VMs encendidas": sum(1 for x in g if x.kind == "VM" and x.running),
                "VMs apagadas": sum(1 for x in g if x.kind == "VM" and not x.running),
                "CTs encendidos": sum(1 for x in g if x.kind == "CT" and x.running),
                "CTs apagados": sum(1 for x in g if x.kind == "CT" and not x.running),
                "Plantillas": self.templates}

    def storage_by_type(self) -> dict:
        out = defaultdict(lambda: [0.0, 0.0])
        for r in self.an.storage_usage():
            out[str(r["Tipo"] or "?")][0] += r["Total (GiB)"]
            out[str(r["Tipo"] or "?")][1] += r["Usado (GiB)"]
        return {k: tuple(v) for k, v in out.items()}

    # ------------------------------------------------------------------ hallazgos
    def _findings(self) -> list[dict]:
        out = []

        def add(sev, cat, title, objs, rec):
            objs = [o for o in objs if o]
            out.append({"Severidad": sev, "Categoría": _(cat), "Hallazgo": _(title), "Afectados": len(objs) or "",
                        "Objetos": objs, "Recomendación": _(rec)})

        # 1) Avisos de PVE Inventory (hoja vHealth), agrupados
        groups = defaultdict(list)
        other = []
        for r in self.sheets.get("vHealth", []):
            msg = str(r.get("Mensaje") or "")
            for i, (pat, *_rest) in enumerate(HEALTH_RULES):
                if re.search(pat, msg, re.I):
                    groups[(i, str(r.get("Severidad") or INFO))].append(r)
                    break
            else:
                other.append(r)
        for (i, sev), rows in groups.items():
            _p, cat, title, rec = HEALTH_RULES[i]
            add(sev, cat, title, [self._obj(r) for r in rows], rec)
        for r in other:
            add(str(r.get("Severidad") or INFO), N_("Otros"), data_out(str(r.get("Mensaje") or "")), [self._obj(r, False)], _("Revisar."))

        # 2) Comprobaciones propias del análisis (no incluidas en vHealth)
        an = self.an
        majors = defaultdict(list)
        for h in an.hosts:
            m = _major(h.pve_version)
            if m:
                majors[m].append(f"{h.node} ({h.pve_version})")
        for m, nodes in sorted(majors.items()):
            if m in PVE_EOL:
                expired = self.ref_date > PVE_EOL_DATE[m]
                add(CRIT if expired else WARN, _("Versiones"),
                    (_("Proxmox VE {m} sin soporte desde {date}", m=m, date=_(PVE_EOL[m])) if expired
                     else _("Proxmox VE {m} llega a fin de soporte en {date}", m=m, date=_(PVE_EOL[m]))),
                    nodes, _("Actualizar a una versión de Proxmox VE con soporte (sin actualizaciones de seguridad desde el fin de soporte)."))
        hot_cpu = [f"{h.node} ({h.cpu_use_pct:.0f} %)" for h in an.hosts if h.cpu_use_pct >= 80]
        if hot_cpu:
            add(WARN, _("Capacidad"), _("Nodos con uso de CPU alto (≥ 80 %)"), hot_cpu, _("Repartir la carga entre nodos o ampliar CPU."))
        over_ram = [_("{nodo} ({ram_asignada_encendidas_:.0f} de {ram_fisica_gib:.0f} GiB)", nodo=r['Nodo'], ram_asignada_encendidas_=r['RAM asignada encendidas (GiB)'], ram_fisica_gib=r['RAM física (GiB)'])
                    for r in self.node_rows() if r["RAM física (GiB)"] and r["RAM asignada encendidas (GiB)"] > r["RAM física (GiB)"]]
        if over_ram:
            add(WARN, _("Capacidad"), _("Memoria asignada a VMs encendidas superior a la RAM física del nodo"), over_ram,
                _("Depende de ballooning/KSM: vigilar el uso real y evitar swap en el host."))
        for r in self.cluster_resilience():
            if r["Resiste la caída de un nodo"] == "No":
                add(WARN, _("Capacidad"), _("El clúster no resiste la caída de un nodo (memoria)"),
                    [_("{cluster}: {ocupacion_con_un_nodo_ca:.0f} % de la RAM restante", cluster=r['Clúster'], ocupacion_con_un_nodo_ca=r['Ocupación con un nodo caído (%)'])],
                    _("Mantener reserva de memoria para reiniciar en otros nodos las VMs de un nodo caído (N+1)."))
        for c in an.clusters:
            hs = [h for h in an.hosts if h.cluster == c and h.ram_gib]
            if len(hs) >= 2:
                pcts = [h.ram_used_gib / h.ram_gib * 100 for h in hs]
                if max(pcts) - min(pcts) >= 30:
                    add(INFO, _("Capacidad"), _("Carga de memoria desequilibrada entre nodos"),
                        [_("{c}: entre {pcts:.0f} % y {pcts2:.0f} %", c=c, pcts=min(pcts), pcts2=max(pcts))], _("Redistribuir VMs entre los nodos del clúster."))
        two = [r.get("Clúster / nodo") for r in self.sheets.get("vCluster", [])
               if str(r.get("Tipo") or "").lower().startswith("cl") and int(num(r.get("Nodos"), 0) or 0) == 2]
        if two:
            add(WARN, "Clúster", _("Clústeres de 2 nodos"), two,
                _("Añadir un QDevice (voto externo) o un tercer nodo para no perder el quórum si cae un nodo."))
        alone = sorted({h.cluster for h in an.hosts if sum(1 for x in an.hosts if x.cluster == h.cluster) == 1})
        if alone:
            add(INFO, "Clúster", _("Nodos independientes (sin clúster)"), alone, _("Sin alta disponibilidad ni migración en vivo entre nodos."))
        legacy = [f"{g.name} ({g.os_label})" for g in an.guests if g.kind == "VM" and g.ostype in LEGACY_OS]
        if legacy:
            add(WARN, _("Sistemas operativos"), _("VMs con sistemas operativos antiguos o fuera de soporte"), legacy,
                _("Planificar la actualización del sistema operativo invitado."))
        pt = [f"{g.name} ({g.passthrough})" for g in an.guests if g.passthrough]
        if pt and not any("passthrough" in str(r.get("Mensaje") or "").lower() for r in self.sheets.get("vHealth", [])):
            add(INFO, "VMs", _("VMs con dispositivos en passthrough"), pt, _("No admiten migración en vivo ni HA entre nodos sin hardware equivalente."))
        vend = defaultdict(set)
        for h in an.hosts:
            if h.vendor:
                vend[h.cluster].add(h.vendor)
        host_cpu = [g.name for g in an.guests if g.cpu_type == "host" and len(vend.get(g.cluster, ())) > 1]
        if host_cpu:
            add(WARN, "VMs", _("VMs con CPU «host» en un entorno con distintos fabricantes de CPU"), host_cpu,
                _("Usar un modelo de CPU genérico (x86-64-v2-AES / v3) para poder moverlas entre nodos."))
        if not self.sheets.get("vBackup"):
            add(CRIT, "Backup", _("No hay trabajos de backup programados"), [_("(general)")], _("Definir trabajos de backup para todas las VMs/CTs."))
        local_bk = [str(r.get("Job")) for r in self.sheets.get("vBackup", [])
                    if str(self._storage_type(r.get("Almacenamiento"))) in ("dir", "lvm", "lvmthin", "zfspool") and yes(r.get("Habilitado") or "Sí")]
        if local_bk:
            add(WARN, "Backup", _("Trabajos de backup a almacenamiento local de los nodos"), local_bk,
                _("Guardar las copias fuera de los nodos (Proxmox Backup Server o almacenamiento externo)."))
        sdn = an.sdn()
        unused = [f"{v['vnet']} ({v['zone']})" for v in sdn["vnets"] if not v["nics"]]
        if unused:
            add(INFO, "Red", _("VNets de SDN sin ninguna VM/CT conectada"), unused,
                _("Eliminar las VNets que ya no se usen o documentar para qué están reservadas."))
        evpn = [f"{z['zone']} ({z['exitnodes'] or 'ninguno'})" for z in sdn["zones"]
                if z["type"] == "evpn" and len([x for x in z["exitnodes"].replace(";", ",").split(",") if x.strip()]) < 2]
        if evpn:
            add(WARN, "Red", _("Zonas SDN EVPN con menos de dos exit nodes"), evpn,
                _("Configurar al menos dos exit nodes para que la salida de las VNets EVPN no dependa de un único nodo."))
        snat = [f"{v['vnet']} ({x['cidr']})" for v in sdn["vnets"] if v["zone_type"] == "simple" for x in v["subnets"] if x["snat"]]
        if snat:
            add(INFO, "Red", _("Subredes SDN con SNAT en zonas simples"), snat,
                _("La VM sale a la red con la IP del nodo donde se ejecuta: cambia al migrarla de nodo. Tenerlo en cuenta en firewalls."))
        for c in an.clusters:
            nodes = sum(1 for h in an.hosts if h.cluster == c)
            vlans = {vl for g in an.guests if g.cluster == c for _b, vl in g.nics if vl}
            if nodes >= 3 and len(vlans) >= 3 and not any(z["cluster"] == c for z in sdn["zones"]):
                add(INFO, "Red", _("Redes de VMs definidas nodo a nodo (sin SDN)"), [_("{c}: {n_vlans} VLANs", c=c, n_vlans=len(vlans))],
                    _("Valorar SDN (zona VLAN, una VNet por VLAN) para definir y controlar las redes una sola vez para todo el clúster."))
        ha_c = {g.cluster for g in an.guests if g.ha}
        no_ha = [c for c in an.clusters if c not in ha_c and sum(1 for h in an.hosts if h.cluster == c) >= 3]
        if no_ha:
            add(INFO, _("Alta disponibilidad"), _("Clústeres sin ningún recurso en alta disponibilidad"), no_ha,
                _("Valorar HA para los servicios críticos."))
        big = [_("{name} ({ram_gib:.0f} GiB)", name=g.name, ram_gib=g.ram_gib) for g in an.guests
               for h in [min((x for x in an.hosts if x.cluster == g.cluster and x.ram_gib), key=lambda x: x.ram_gib, default=None)]
               if h and g.ram_gib > h.ram_gib * 0.5]
        if big:
            add(INFO, _("Capacidad"), _("VMs con más de la mitad de la RAM del nodo más pequeño"), big,
                _("Limitan dónde se pueden reiniciar o mover; tenerlo en cuenta en mantenimientos."))
        out.sort(key=lambda r: (SEV_ORDER.get(r["Severidad"], 9), r["Categoría"], -(r["Afectados"] or 0)))
        return out

    def _storage_type(self, name):
        for r in self.sheets.get("vDatastore", []):
            if r.get("Almacenamiento") == name:
                return r.get("Tipo")
        return None

    @staticmethod
    def _obj(r, with_msg=True):
        o = str(r.get("Objeto") or "")
        c = str(r.get("Clúster") or "")
        msg = str(r.get("Mensaje") or "")
        detail = re.findall(r"\d+(?:[.,]\d+)?\s*(?:%|días)", msg)
        s = o if o and o not in ("Clúster", "Ceph", "Corosync", "Firewall") else c
        if with_msg and detail:
            s += f" ({detail[0].replace('días', _('días'))})"
        return data_out(s)

    def severity_counts(self) -> Counter:
        return Counter(f["Severidad"] for f in self.findings)

    def score(self) -> str:
        c = self.severity_counts()
        if c.get(CRIT):
            return _("Requiere atención")
        if c.get(WARN, 0) > 5:
            return _("Mejorable")
        return _("Correcto")

    # ------------------------------------------------------------------ resumen
    def text_summary(self) -> str:
        an = self.an
        t = an.totals()
        c = self.severity_counts()
        lines = [
            _("INFORME DE LA INFRAESTRUCTURA ACTUAL (solo análisis)"),
            _("Clústeres / nodos independientes: {clusters} · Nodos: {hosts} · Proxmox VE {v}", clusters=t['clusters'], hosts=t['hosts'], v=', '.join(an.pve_versions()) or '?'),
            _("Capacidad física: {host_cores} cores / {host_threads} hilos · {host_ram_gib:.0f} GiB RAM ({host_ram_used_gib:.0f} GiB en uso)", host_cores=t['host_cores'], host_threads=t['host_threads'], host_ram_gib=t['host_ram_gib'], host_ram_used_gib=t['host_ram_used_gib']),
            _("VMs: {vms} · CTs: {cts} · encendidas: {running} · plantillas: {templates}", vms=t['vms'], cts=t['cts'], running=t['running'], templates=self.templates),
            _("Asignado: {vcpu:.0f} vCPU · {ram_gib:.0f} GiB RAM · {disk_prov_gib:.1f} TiB de disco aprovisionado", vcpu=t['vcpu'], ram_gib=t['ram_gib'], disk_prov_gib=t['disk_prov_gib'] / 1024),
            _("Almacenamiento: {total:.1f} TiB en total, {used:.1f} TiB usados", total=sum(r['Total (GiB)'] for r in an.storage_usage()) / 1024, used=sum(r['Usado (GiB)'] for r in an.storage_usage()) / 1024),
            _("Hallazgos: {crit} críticos · {warn} avisos · {info} informativos → {score}", crit=c.get(CRIT, 0), warn=c.get(WARN, 0), info=c.get(INFO, 0), score=self.score()),
        ]
        if self.anonymized:
            lines.append(_("Inventario anonimizado: los nombres e IPs son seudónimos."))
        lines.append("")
        for f in self.findings[:15]:
            lines.append(f"[{f['Severidad']}] {f['Categoría']}: {f['Hallazgo']}" + (f" ({f['Afectados']})" if f["Afectados"] else ""))
        if len(self.findings) > 15:
            lines.append(_("… y {n_findings} hallazgos más en el informe.", n_findings=len(self.findings) - 15))
        return "\n".join(lines)
