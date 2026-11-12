"""Análisis de la infraestructura actual (modo «solo análisis», tipo health check).

Solo describe lo que hay en el inventario: capacidad, uso, distribución, almacenamiento, red, backup y
hallazgos. No propone migración, hardware ni olas.
"""
from __future__ import annotations

import datetime as dt
import re
from collections import Counter, defaultdict

from .analysis import LEGACY_OS, Analysis
from .loader import num, yes

CRIT, WARN, INFO = "CRÍTICO", "AVISO", "INFO"
SEV_ORDER = {CRIT: 0, WARN: 1, INFO: 2}

# Ciclo de vida de Proxmox VE (fin de soporte publicado por Proxmox)
PVE_EOL = {5: "julio de 2020", 6: "julio de 2022", 7: "julio de 2024", 8: "agosto de 2026"}
PVE_EOL_DATE = {5: dt.date(2020, 7, 31), 6: dt.date(2022, 7, 31), 7: dt.date(2024, 7, 31), 8: dt.date(2026, 8, 31)}

# Avisos de la hoja vHealth (PVE Inventory) agrupados en hallazgos: (patrón, categoría, título, recomendación)
HEALTH_RULES = [
    (r"no tiene quórum", "Clúster", "Clúster sin quórum",
     "Recuperar el quórum (nodos caídos, red de corosync) antes de cualquier cambio."),
    (r"^Nodo en estado", "Nodos", "Nodos fuera de línea", "Revisar el nodo y su conectividad con el clúster."),
    (r"Uso de RAM al", "Capacidad", "Nodos con uso de memoria muy alto (≥ 90 %)",
     "Repartir carga entre nodos, reducir memoria asignada o ampliar RAM."),
    (r"Disco raíz al", "Nodos", "Disco del sistema de los nodos casi lleno",
     "Liberar espacio (logs, kernels antiguos, ISOs/backups locales) en el disco del sistema."),
    (r"Sobreasignación de CPU", "Capacidad", "Sobreasignación de CPU superior a 4:1",
     "Revisar el rendimiento (CPU ready / steal) y equilibrar las vCPU entre nodos."),
    (r"^Suscripción", "Soporte", "Nodos sin suscripción activa",
     "Activar la suscripción para tener repositorio enterprise y soporte del fabricante."),
    (r"Versiones de PVE mezcladas", "Versiones", "Versiones de Proxmox VE mezcladas en un clúster",
     "Igualar la versión de todos los nodos del clúster."),
    (r"^Ocupado al", "Almacenamiento", "Almacenamientos con ocupación alta",
     "Liberar espacio o ampliar el almacenamiento; no superar el 80 % de ocupación."),
    (r"^Estado '", "Almacenamiento", "Almacenamientos no disponibles", "Revisar la conexión o configuración del almacenamiento."),
    (r"^Snapshot '", "Snapshots", "Snapshots antiguas", "Consolidar o eliminar las snapshots que ya no se necesiten."),
    (r"Guest agent no habilitado", "VMs", "VMs encendidas sin agente QEMU",
     "Instalar y habilitar qemu-guest-agent (apagados limpios, IPs, consistencia de backups)."),
    (r"Guest agent habilitado pero no responde", "VMs", "Agente QEMU habilitado pero sin respuesta",
     "Instalar o arrancar el servicio qemu-guest-agent dentro de la VM."),
    (r"^Bloqueada", "VMs", "VMs/CTs bloqueadas", "Revisar la tarea que dejó el bloqueo y liberarlo (qm unlock / pct unlock)."),
    (r"^Disco sin usar", "Almacenamiento", "Discos sin usar asociados a VMs", "Eliminar los discos huérfanos para recuperar espacio."),
    (r"^ISO montada", "VMs", "ISOs montadas en las VMs", "Desmontar las ISOs que no se usen (impiden migraciones en vivo)."),
    (r"ningún job de backup", "Backup", "VMs/CTs fuera de cualquier trabajo de backup", "Incluirlas en un trabajo de backup."),
    (r"Sin ninguna copia de backup", "Backup", "VMs/CTs sin ninguna copia de backup", "Revisar los trabajos de backup y su resultado."),
    (r"Último backup hace", "Backup", "Copias de backup antiguas", "Revisar por qué fallan o no se ejecutan los trabajos de backup."),
    (r"verificación del último backup", "Backup", "Verificación de backup fallida", "Revisar el datastore del PBS y repetir la copia."),
    (r"^HEALTH_", "Ceph", "Ceph no está en estado HEALTH_OK", "Revisar «ceph -s» y resolver los avisos."),
    (r"^OSD .*in=", "Ceph", "OSDs de Ceph caídos o fuera", "Revisar el disco y el servicio del OSD."),
    (r"^OSD al", "Ceph", "OSDs de Ceph con ocupación alta", "Ampliar capacidad o rebalancear (Ceph se bloquea al 95 %)."),
    (r"^SMART", "Discos físicos", "Discos con SMART en error", "Sustituir el disco cuanto antes."),
    (r"Desgaste del SSD", "Discos físicos", "SSD con desgaste alto (≥ 80 %)", "Planificar la sustitución de los SSD."),
    (r"Pool en estado", "ZFS", "Pools ZFS degradados", "Sustituir el disco afectado y revisar «zpool status»."),
    (r"Pool ocupado", "ZFS", "Pools ZFS por encima del 80 %", "Liberar espacio o ampliar el pool."),
    (r"Bond con una sola", "Red", "Bonds sin redundancia", "Añadir una segunda interfaz al bond."),
    (r"corosync", "Clúster", "Corosync con un solo enlace", "Configurar un segundo enlace de corosync en una red independiente."),
    (r"Firewall de datacenter", "Seguridad", "Firewall de datacenter deshabilitado",
     "Valorar activar el firewall de Proxmox VE con reglas explícitas."),
    (r"Token sin privilegios", "Seguridad", "Tokens de API con todos los permisos del usuario",
     "Usar tokens con privilegios separados y solo los permisos necesarios."),
    (r"tareas con error", "Operación", "Tareas con error o avisos en los últimos 7 días",
     "Revisar el registro de tareas (hoja vTasks del inventario)."),
    (r"passthrough sin mapping", "VMs", "Passthrough PCI sin mapeo de recursos",
     "Crear un mapeo de recursos (Datacenter → Resource Mappings) para el dispositivo."),
    (r"Repositorio .* sin suscripción", "Actualizaciones", "Repositorio enterprise sin suscripción",
     "Activar la suscripción o configurar el repositorio no-subscription."),
    (r"Repositorio de pruebas", "Actualizaciones", "Repositorio de pruebas habilitado", "Deshabilitar el repositorio de pruebas en producción."),
    (r"actualizaciones pendientes", "Actualizaciones", "Nodos con actualizaciones pendientes",
     "Aplicar las actualizaciones nodo a nodo en una ventana de mantenimiento."),
    (r"^Caducado", "Certificados", "Certificados caducados", "Renovar los certificados."),
    (r"^Caduca en", "Certificados", "Certificados próximos a caducar", "Renovar los certificados antes de su caducidad."),
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
        b = {"≤ 7 días": 0, "8-30 días": 0, "31-90 días": 0, "> 90 días": 0, "Sin fecha": 0}
        for r in self.sheets.get("vSnapshot", []):
            if str(r.get("Snapshot")) == "current":
                continue
            a = num(r.get("Antigüedad (días)"))
            k = "Sin fecha" if a is None else "≤ 7 días" if a <= 7 else "8-30 días" if a <= 30 else "31-90 días" if a <= 90 else "> 90 días"
            b[k] += 1
        if not sum(b.values()):
            b["Sin fecha"] = sum(g.snapshots for g in self.an.guests)
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
            out.append({"Severidad": sev, "Categoría": cat, "Hallazgo": title, "Afectados": len(objs) or "",
                        "Objetos": objs, "Recomendación": rec})

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
            add(str(r.get("Severidad") or INFO), "Otros", str(r.get("Mensaje") or ""), [self._obj(r, False)], "Revisar.")

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
                add(CRIT if expired else WARN, "Versiones",
                    f"Proxmox VE {m} " + (f"sin soporte desde {PVE_EOL[m]}" if expired else f"llega a fin de soporte en {PVE_EOL[m]}"),
                    nodes, "Actualizar a una versión de Proxmox VE con soporte (sin actualizaciones de seguridad desde el fin de soporte).")
        hot_cpu = [f"{h.node} ({h.cpu_use_pct:.0f} %)" for h in an.hosts if h.cpu_use_pct >= 80]
        if hot_cpu:
            add(WARN, "Capacidad", "Nodos con uso de CPU alto (≥ 80 %)", hot_cpu, "Repartir la carga entre nodos o ampliar CPU.")
        over_ram = [f"{r['Nodo']} ({r['RAM asignada encendidas (GiB)']:.0f} de {r['RAM física (GiB)']:.0f} GiB)"
                    for r in self.node_rows() if r["RAM física (GiB)"] and r["RAM asignada encendidas (GiB)"] > r["RAM física (GiB)"]]
        if over_ram:
            add(WARN, "Capacidad", "Memoria asignada a VMs encendidas superior a la RAM física del nodo", over_ram,
                "Depende de ballooning/KSM: vigilar el uso real y evitar swap en el host.")
        for r in self.cluster_resilience():
            if r["Resiste la caída de un nodo"] == "No":
                add(WARN, "Capacidad", "El clúster no resiste la caída de un nodo (memoria)",
                    [f"{r['Clúster']}: {r['Ocupación con un nodo caído (%)']:.0f} % de la RAM restante"],
                    "Mantener reserva de memoria para reiniciar en otros nodos las VMs de un nodo caído (N+1).")
        for c in an.clusters:
            hs = [h for h in an.hosts if h.cluster == c and h.ram_gib]
            if len(hs) >= 2:
                pcts = [h.ram_used_gib / h.ram_gib * 100 for h in hs]
                if max(pcts) - min(pcts) >= 30:
                    add(INFO, "Capacidad", "Carga de memoria desequilibrada entre nodos",
                        [f"{c}: entre {min(pcts):.0f} % y {max(pcts):.0f} %"], "Redistribuir VMs entre los nodos del clúster.")
        two = [r.get("Clúster / nodo") for r in self.sheets.get("vCluster", [])
               if str(r.get("Tipo") or "").lower().startswith("cl") and int(num(r.get("Nodos"), 0) or 0) == 2]
        if two:
            add(WARN, "Clúster", "Clústeres de 2 nodos", two,
                "Añadir un QDevice (voto externo) o un tercer nodo para no perder el quórum si cae un nodo.")
        alone = sorted({h.cluster for h in an.hosts if sum(1 for x in an.hosts if x.cluster == h.cluster) == 1})
        if alone:
            add(INFO, "Clúster", "Nodos independientes (sin clúster)", alone, "Sin alta disponibilidad ni migración en vivo entre nodos.")
        legacy = [f"{g.name} ({g.os_label})" for g in an.guests if g.kind == "VM" and g.ostype in LEGACY_OS]
        if legacy:
            add(WARN, "Sistemas operativos", "VMs con sistemas operativos antiguos o fuera de soporte", legacy,
                "Planificar la actualización del sistema operativo invitado.")
        pt = [f"{g.name} ({g.passthrough})" for g in an.guests if g.passthrough]
        if pt and not any("passthrough" in str(r.get("Mensaje") or "").lower() for r in self.sheets.get("vHealth", [])):
            add(INFO, "VMs", "VMs con dispositivos en passthrough", pt, "No admiten migración en vivo ni HA entre nodos sin hardware equivalente.")
        vend = defaultdict(set)
        for h in an.hosts:
            if h.vendor:
                vend[h.cluster].add(h.vendor)
        host_cpu = [g.name for g in an.guests if g.cpu_type == "host" and len(vend.get(g.cluster, ())) > 1]
        if host_cpu:
            add(WARN, "VMs", "VMs con CPU «host» en un entorno con distintos fabricantes de CPU", host_cpu,
                "Usar un modelo de CPU genérico (x86-64-v2-AES / v3) para poder moverlas entre nodos.")
        if not self.sheets.get("vBackup"):
            add(CRIT, "Backup", "No hay trabajos de backup programados", ["(general)"], "Definir trabajos de backup para todas las VMs/CTs.")
        local_bk = [str(r.get("Job")) for r in self.sheets.get("vBackup", [])
                    if str(self._storage_type(r.get("Almacenamiento"))) in ("dir", "lvm", "lvmthin", "zfspool") and yes(r.get("Habilitado") or "Sí")]
        if local_bk:
            add(WARN, "Backup", "Trabajos de backup a almacenamiento local de los nodos", local_bk,
                "Guardar las copias fuera de los nodos (Proxmox Backup Server o almacenamiento externo).")
        ha_c = {g.cluster for g in an.guests if g.ha}
        no_ha = [c for c in an.clusters if c not in ha_c and sum(1 for h in an.hosts if h.cluster == c) >= 3]
        if no_ha:
            add(INFO, "Alta disponibilidad", "Clústeres sin ningún recurso en alta disponibilidad", no_ha,
                "Valorar HA para los servicios críticos.")
        big = [f"{g.name} ({g.ram_gib:.0f} GiB)" for g in an.guests
               for h in [min((x for x in an.hosts if x.cluster == g.cluster and x.ram_gib), key=lambda x: x.ram_gib, default=None)]
               if h and g.ram_gib > h.ram_gib * 0.5]
        if big:
            add(INFO, "Capacidad", "VMs con más de la mitad de la RAM del nodo más pequeño", big,
                "Limitan dónde se pueden reiniciar o mover; tenerlo en cuenta en mantenimientos.")
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
            s += f" ({detail[0]})"
        return s

    def severity_counts(self) -> Counter:
        return Counter(f["Severidad"] for f in self.findings)

    def score(self) -> str:
        c = self.severity_counts()
        if c.get(CRIT):
            return "Requiere atención"
        if c.get(WARN, 0) > 5:
            return "Mejorable"
        return "Correcto"

    # ------------------------------------------------------------------ resumen
    def text_summary(self) -> str:
        an = self.an
        t = an.totals()
        c = self.severity_counts()
        lines = [
            "INFORME DE LA INFRAESTRUCTURA ACTUAL (solo análisis)",
            f"Clústeres / nodos independientes: {t['clusters']} · Nodos: {t['hosts']} · Proxmox VE {', '.join(an.pve_versions()) or '?'}",
            f"Capacidad física: {t['host_cores']} cores / {t['host_threads']} hilos · {t['host_ram_gib']:.0f} GiB RAM "
            f"({t['host_ram_used_gib']:.0f} GiB en uso)",
            f"VMs: {t['vms']} · CTs: {t['cts']} · encendidas: {t['running']} · plantillas: {self.templates}",
            f"Asignado: {t['vcpu']:.0f} vCPU · {t['ram_gib']:.0f} GiB RAM · {t['disk_prov_gib'] / 1024:.1f} TiB de disco aprovisionado",
            f"Almacenamiento: {sum(r['Total (GiB)'] for r in an.storage_usage()) / 1024:.1f} TiB en total, "
            f"{sum(r['Usado (GiB)'] for r in an.storage_usage()) / 1024:.1f} TiB usados",
            f"Hallazgos: {c.get(CRIT, 0)} críticos · {c.get(WARN, 0)} avisos · {c.get(INFO, 0)} informativos → {self.score()}",
        ]
        if self.anonymized:
            lines.append("Inventario anonimizado: los nombres e IPs son seudónimos.")
        lines.append("")
        for f in self.findings[:15]:
            lines.append(f"[{f['Severidad']}] {f['Categoría']}: {f['Hallazgo']}" + (f" ({f['Afectados']})" if f["Afectados"] else ""))
        if len(self.findings) > 15:
            lines.append(f"… y {len(self.findings) - 15} hallazgos más en el informe.")
        return "\n".join(lines)
