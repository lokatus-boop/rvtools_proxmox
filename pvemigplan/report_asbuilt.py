"""Documentación «as-built» para Postventa, a partir del inventario (PVE Inventory) del entorno ya implantado."""
from __future__ import annotations

import datetime as dt
from collections import Counter

from .analysis import Analysis
from .branding import COMPANY
from .loader import num, yes
from .report_docx import GREY, Doc

SKIP_WORDS = ("password", "contraseña", "secret", "token", "key", "clave", "voucher")


def read_config_sheet(path: str) -> list[tuple[str, str]]:
    """Valores de la hoja «Settings» (sin contraseñas ni claves)."""
    from openpyxl import load_workbook
    wb = load_workbook(path, data_only=True)
    if "Settings" not in wb.sheetnames:
        return []
    ws = wb["Settings"]
    out, section = [], ""
    for r in range(3, ws.max_row + 1):
        k, v = ws.cell(r, 2).value, ws.cell(r, 3).value
        if not k:
            continue
        k = str(k).strip()
        if v in (None, "") and ws.cell(r + 1, 2).value:
            section = k
            continue
        if any(w in k.lower() for w in SKIP_WORDS) or v in (None, ""):
            continue
        out.append((f"{section} · {k}" if section and k.lower() in ("host name", "ip address", "netmask", "gateway", "vm name",
                                                                     "switch name", "port", "username") else k, str(v)))
    return out


class AsBuiltDoc(Doc):
    TITLE = "Documentación de la plataforma Proxmox VE"

    def __init__(self, sheets, client="", author="", config_path=None):
        self.sheets = sheets
        self.an = Analysis(sheets, include_stopped=True, include_templates=True)
        self.author = author
        self.config_path = config_path
        super().__init__(None, client=client)

    def rows(self, sheet, cols, limit=None, filt=None):
        data = [r for r in self.sheets.get(sheet, []) if not filt or filt(r)]
        if limit:
            data = data[:limit]
        return [[r.get(c) for c in cols] for r in data]

    def build(self, path):
        sh, an = self.sheets, self.an
        now = dt.datetime.now()
        clusters = sh.get("vCluster", [])
        self.cover("Documentación de la plataforma", "Proxmox VE · configuración implantada (as-built)",
                   [f"Cliente: {self.client or '—'}", "Fecha del inventario: " + str((sh.get("vSource") or [{}])[0].get("Fecha") or f"{now:%d/%m/%Y}"),
                    f"Preparado por: {self.author or COMPANY}", "Destinatarios: Postventa / Soporte"],
                   "Generado a partir del inventario de PVE Inventory del entorno implantado. Contiene información sensible del "
                   "cliente (IPs, nombres, configuración): no contiene contraseñas.")

        # 1. Resumen
        t = an.totals()
        self.h("1. Resumen de la plataforma")
        self.kv([
            ("Clústeres / nodos independientes", ", ".join(an.clusters) or "—"),
            ("Nodos", f"{t['hosts']} · {t['host_cores']} cores · {t['host_ram_gib']:.0f} GiB RAM"),
            ("Versiones de Proxmox VE", ", ".join(an.pve_versions()) or "—"),
            ("Máquinas virtuales", f"{t['vms']} VMs y {t['cts']} contenedores ({t['running']} encendidos)"),
            ("Almacenamiento", ", ".join(sorted({f"{r['Almacenamiento']} ({r['Tipo']})" for r in an.storage_usage()})) or "—"),
            ("Ceph", "Sí" if an.has_ceph() else "No"),
            ("Backup", f"{len(sh.get('vBackup', []))} job(s)" + (" · Proxmox Backup Server" if an.backup_summary()["uses_pbs"] else "")),
        ])
        if clusters:
            self.table(["Clúster / nodo", "Tipo", "Nodos", "Online", "Quórum", "VMs", "CTs", "Hilos", "RAM (GiB)"],
                       self.rows("vCluster", ["Clúster / nodo", "Tipo", "Nodos", "Nodos online", "Quórum", "VMs", "CTs", "Hilos CPU totales", "RAM total (GiB)"]), size=8)
        hc = an.health_counts()
        if hc:
            self.p(f"Estado en el momento del inventario: {hc.get('CRÍTICO', 0)} avisos críticos, {hc.get('AVISO', 0)} avisos "
                   f"(ver apartado 9).", bold=bool(hc.get("CRÍTICO")))

        # 2. Nodos
        self.h("2. Nodos")
        self.table(["Clúster", "Nodo", "IP", "PVE", "Kernel", "CPU", "Cores", "RAM (GiB)", "Suscripción"],
                   self.rows("vHost", ["Clúster", "Nodo", "IP", "Versión PVE", "Kernel", "Modelo CPU", "Cores", "RAM total (GiB)", "Nivel suscripción"]), size=7.5)
        subs = Counter(str(r.get("Suscripción") or "sin datos") for r in sh.get("vHost", []))
        self.p("Suscripciones: " + ", ".join(f"{k}: {v}" for k, v in subs.items()) + ".")
        if sh.get("vRepo"):
            self.table(["Clúster", "Nodo", "Repositorio", "Estado"], self.rows("vRepo", ["Clúster", "Nodo", "Repositorio", "Estado"]), size=7.5)

        # 3. Red
        self.h("3. Red")
        self.h("Bonds", 3)
        self.table(["Nodo", "Bond", "Modo", "Esclavos", "Hash", "MTU", "Usado por"],
                   self.rows("vBond", ["Nodo", "Bond", "Modo", "Esclavos", "Hash (xmit_hash_policy)", "MTU", "Usado por"]), size=7.5)
        self.h("Bridges", 3)
        self.table(["Nodo", "Bridge", "Puertos", "VLAN aware", "CIDR", "Gateway", "MTU", "VLANs usadas"],
                   self.rows("vBridge", ["Nodo", "Bridge", "Puertos", "VLAN aware", "CIDR", "Gateway", "MTU", "VLANs usadas por VMs"]), size=7.5)
        if sh.get("vHostVLAN"):
            self.h("Interfaces VLAN", 3)
            self.table(["Nodo", "Interfaz", "VLAN", "Dispositivo", "CIDR", "MTU"],
                       self.rows("vHostVLAN", ["Nodo", "Interfaz", "VLAN id", "Dispositivo base", "CIDR", "MTU"]), size=7.5)
        if sh.get("vSDN"):
            self.h("SDN", 3)
            self.table(["Zona", "Tipo", "Bridge", "VNet", "Alias", "Tag", "Subred", "Gateway"],
                       self.rows("vSDN", ["Zona", "Tipo zona", "Bridge zona", "VNet", "Alias", "Tag / VNI", "Subred", "Gateway"]), size=7.5)
        if sh.get("vCorosync"):
            self.h("Corosync", 3)
            self.table(["Nodo", "ID", "Votos", "Enlaces", "Direcciones"],
                       self.rows("vCorosync", ["Nodo", "Node ID", "Votos", "Enlaces", "Direcciones"]), size=7.5)

        # 4. Almacenamiento
        self.h("4. Almacenamiento")
        self.table(["Clúster", "Nodo", "Almacenamiento", "Tipo", "Compartido", "Contenido", "Total (GiB)", "Uso (%)"],
                   [[r["Clúster"], r["Nodo"], r["Almacenamiento"], r["Tipo"], r["Compartido"], r["Contenido"], r["Total (GiB)"], r["Uso (%)"]]
                    for r in an.storage_usage()], size=7.5)
        if sh.get("vCephPool"):
            self.h("Ceph", 3)
            self.table(["Pool", "Réplicas", "Mín.", "PGs", "Autoscale", "Usado (GiB)", "Uso (%)"],
                       self.rows("vCephPool", ["Pool", "Réplicas (size)", "Mín. réplicas", "PGs", "Autoscale", "Usado (GiB)", "Uso (%)"]), size=8)
            osd = Counter((r.get("Host"), r.get("Clase")) for r in sh.get("vCephOSD", []))
            self.p("OSDs por nodo: " + ", ".join(f"{h} ({c}): {n}" for (h, c), n in sorted(osd.items(), key=lambda x: str(x[0]))) + ".")
        if sh.get("vZFS"):
            self.h("ZFS", 3)
            self.table(["Nodo", "Pool", "Estado", "Tamaño (GiB)", "Uso (%)", "Fragmentación (%)"],
                       self.rows("vZFS", ["Nodo", "Pool", "Estado", "Tamaño (GiB)", "Uso (%)", "Fragmentación (%)"]), size=8)
        if sh.get("vPhysicalDisk"):
            self.h("Discos físicos", 3)
            self.table(["Nodo", "Dispositivo", "Tipo", "Modelo", "Tamaño (GiB)", "SMART", "Desgaste (%)", "Uso"],
                       self.rows("vPhysicalDisk", ["Nodo", "Dispositivo", "Tipo", "Modelo", "Tamaño (GiB)", "SMART", "Desgaste (%)", "Uso"]), size=7)

        # 5. Alta disponibilidad y replicación
        self.h("5. Alta disponibilidad y replicación")
        if sh.get("vHA"):
            self.table(["Elemento", "Recurso", "Estado", "Grupo", "Máx. reinicios", "Máx. reubicaciones"],
                       self.rows("vHA", ["Elemento", "Recurso", "Estado solicitado", "Grupo", "Máx. reinicios", "Máx. reubicaciones"]), size=8)
        else:
            self.p("No hay recursos de alta disponibilidad configurados.")
        if sh.get("vReplication"):
            cols = list(sh["vReplication"][0].keys())[:7]
            self.table(cols, self.rows("vReplication", cols), size=7.5)

        # 6. Backup
        self.h("6. Copias de seguridad")
        if sh.get("vBackup"):
            self.table(["Job", "Habilitado", "Planificación", "Almacenamiento", "Modo", "Selección", "Retención"],
                       self.rows("vBackup", ["Job", "Habilitado", "Planificación", "Almacenamiento", "Modo", "Selección", "Retención"]), size=7.5)
        else:
            self.p("No hay trabajos de backup configurados.", bold=True)
        bk = an.backup_summary()
        self.p(f"VMs/CTs con copia: {bk['with_backup']} · sin copia registrada: {bk['without_backup']}.")
        nob = [r for r in sh.get("vBackupStatus", []) if not (num(r.get("Nº copias"), 0) or 0)]
        if nob:
            self.table(["Clúster", "VMID", "Nombre", "Estado"], [[r.get("Clúster"), r.get("VMID"), r.get("Nombre"), r.get("Estado VM")] for r in nob[:50]], size=7.5)

        # 7. Seguridad
        self.h("7. Seguridad y accesos")
        users = sh.get("vUsers", [])
        self.p(f"Usuarios y tokens: {len(users)} · reglas de firewall: {len(sh.get('vFirewall', []))} · "
               f"objetos de firewall: {len(sh.get('vFirewallObj', []))}.")
        if users:
            self.table(["Tipo", "ID", "Habilitado", "Caduca", "Realm", "Grupos"], self.rows("vUsers", ["Tipo", "ID", "Habilitado", "Caduca", "Realm", "Grupos"]), size=7.5)
        if sh.get("vACL"):
            self.table(["Ruta", "Tipo", "Usuario / grupo", "Rol", "Propagar"], self.rows("vACL", ["Ruta", "Tipo", "Usuario / grupo", "Rol", "Propagar"]), size=7.5)
        if sh.get("vCert"):
            self.h("Certificados", 3)
            self.table(["Nodo", "Fichero", "Emisor", "Válido hasta", "Días restantes"],
                       self.rows("vCert", ["Nodo", "Fichero", "Emisor", "Válido hasta", "Días restantes"]), size=7.5)

        # 8. VMs
        self.h("8. Máquinas virtuales y contenedores")
        self.table(["Clúster", "Nodo", "VMID", "Nombre", "Tipo", "Estado", "vCPU", "RAM (GiB)", "Disco (GiB)", "HA", "Último backup"],
                   [[g.cluster, g.node, g.vmid, g.name, g.kind, "plantilla" if g.template else ("on" if g.running else "off"), g.vcpu,
                     round(g.ram_gib, 1), round(g.disk_prov_gib), "Sí" if g.ha else "", g.last_backup[:10]] for g in an.all_guests], size=7)

        # 9. Salud
        self.h("9. Avisos en el momento del inventario")
        hl = sh.get("vHealth", [])
        if hl:
            order = {"CRÍTICO": 0, "AVISO": 1, "INFO": 2}
            self.table(["Severidad", "Clúster", "Objeto", "Mensaje"],
                       [[r.get("Severidad"), r.get("Clúster"), r.get("Objeto"), r.get("Mensaje")]
                        for r in sorted(hl, key=lambda r: order.get(r.get("Severidad"), 3))], size=7.5)
        else:
            self.p("Sin avisos.")

        # 10. Operación
        self.h("10. Operación y mantenimiento")
        ceph = an.has_ceph()
        self.h("Actualizar los nodos (uno a uno)", 3)
        self.numbered(["Comprobar que el clúster está sano (pvecm status" + (", ceph -s" if ceph else "") + ").",
                       "Migrar las VMs del nodo (o usar el modo mantenimiento de HA: ha-manager crm-command node-maintenance enable <nodo>).",
                       ("Ceph: ceph osd set noout. " if ceph else "") + "apt update && apt full-upgrade; reiniciar si hay nuevo kernel.",
                       "Volver a activar el nodo (node-maintenance disable" + (", ceph osd unset noout" if ceph else "") + ") y pasar al siguiente."])
        self.h("Comprobaciones periódicas", 3)
        self.checklist(["Estado del clúster y quórum.", "Resultado de los backups y de las verificaciones del PBS.",
                        "Ocupación de los almacenamientos (< 80 %)." + (" Estado de Ceph (HEALTH_OK)." if ceph else ""),
                        "Caducidad de certificados y de suscripciones.", "Avisos SMART y desgaste de discos.",
                        "Actualizaciones pendientes (repositorio enterprise)."])
        self.h("Restaurar una VM", 3)
        self.p("Almacenamiento de backup → seleccionar la copia → Restaurar (opción «live-restore» para arrancarla mientras se restaura). "
               "Para ficheros sueltos: «Restauración de ficheros».")

        # 11. Datos de configuración
        if self.config_path:
            try:
                cfg = read_config_sheet(self.config_path)
            except Exception as exc:  # noqa: BLE001
                cfg = []
                self.p(f"No se pudo leer la hoja de configuración: {exc}", italic=True, color=GREY)
            if cfg:
                self.h("11. Datos de configuración (hoja de implementación)")
                self.p("Valores de la hoja de configuración del proyecto (sin contraseñas ni claves).", italic=True, color=GREY)
                self.kv(cfg, size=8.5)
        self.h("Contactos y soporte", 2)
        self.kv([("Cliente: responsable técnico", "________"), ("Fsas Technologies: proyecto / preventa", self.author or "________"),
                 ("Soporte Proxmox (suscripción)", "Portal de clientes de Proxmox / Fsas Technologies"),
                 ("Soporte hardware", "Fsas Technologies (nº de serie en la hoja de configuración)")])
        self.d.save(path)
        return path


def to_asbuilt_docx(sheets, path, client="", author="", config_path=None):
    return AsBuiltDoc(sheets, client, author, config_path).build(path)


__all__ = ["to_asbuilt_docx", "read_config_sheet", "yes"]
