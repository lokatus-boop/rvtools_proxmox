"""Documentación «as-built» para Postventa, a partir del inventario (PVE Inventory) del entorno ya implantado."""
from __future__ import annotations

from pvetools.i18n import N_, _, fmt_date

import datetime as dt
from collections import Counter

from .analysis import Analysis
from .asbuilt_cheatsheets import add_cheatsheets, add_contact
from .branding import COMPANY
from .loader import num, yes
from .report_docx import GREY, Doc
from pvetools.safefile import atomic_save

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
    TITLE = N_("Documentación de la plataforma Proxmox VE")

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
        self.cover(_("Documentación de la plataforma"), _("Proxmox VE · configuración implantada (as-built)"),
                   [_("Cliente: {v}", v=self.client or '—'), _("Fecha del inventario: ") + str((sh.get("vSource") or [{}])[0].get("Fecha") or fmt_date(now)),
                    _("Preparado por: {v}", v=self.author or COMPANY), _("Destinatarios: Postventa / Soporte")],
                   _("Generado a partir del inventario de PVE Inventory del entorno implantado. Contiene información sensible del "
                   "cliente (IPs, nombres, configuración): no contiene contraseñas."))

        # 1. Resumen
        t = an.totals()
        self.h(_("1. Resumen de la plataforma"))
        self.kv([
            (_("Clústeres / nodos independientes"), ", ".join(an.clusters) or "—"),
            ("Nodos", _("{hosts} · {host_cores} cores · {host_ram_gib:.0f} GiB RAM", hosts=t['hosts'], host_cores=t['host_cores'], host_ram_gib=t['host_ram_gib'])),
            (_("Versiones de Proxmox VE"), ", ".join(an.pve_versions()) or "—"),
            (_("Máquinas virtuales"), _("{vms} VMs y {cts} contenedores ({running} encendidos)", vms=t['vms'], cts=t['cts'], running=t['running'])),
            ("Almacenamiento", ", ".join(sorted({f"{r['Almacenamiento']} ({r['Tipo']})" for r in an.storage_usage()})) or "—"),
            ("Ceph", "Sí" if an.has_ceph() else "No"),
            ("SDN", an.sdn_summary()),
            ("Backup", f"{len(sh.get('vBackup', []))} job(s)" + (_(" · Proxmox Backup Server") if an.backup_summary()["uses_pbs"] else "")),
        ])
        if clusters:
            self.table(["Clúster / nodo", "Tipo", "Nodos", _("Online"), "Quórum", "VMs", "CTs", "Hilos", "RAM (GiB)"],
                       self.rows("vCluster", ["Clúster / nodo", "Tipo", "Nodos", "Nodos online", "Quórum", "VMs", "CTs", "Hilos CPU totales", "RAM total (GiB)"]), size=8)
        hc = an.health_counts()
        if hc:
            self.p(_("Estado en el momento del inventario: {get} avisos críticos, {get2} avisos (ver apartado 9).", get=hc.get('CRÍTICO', 0), get2=hc.get('AVISO', 0)), bold=bool(hc.get("CRÍTICO")))

        # 2. Nodos
        self.h(_("2. Nodos"))
        self.table(["Clúster", "Nodo", "IP", "PVE", "Kernel", "CPU", "Cores", "RAM (GiB)", "Suscripción"],
                   self.rows("vHost", ["Clúster", "Nodo", "IP", "Versión PVE", "Kernel", "Modelo CPU", "Cores", "RAM total (GiB)", "Nivel suscripción"]), size=7.5)
        subs = Counter(str(r.get("Suscripción") or _("sin datos")) for r in sh.get("vHost", []))
        self.p(_("Suscripciones: ") + ", ".join(f"{k}: {v}" for k, v in subs.items()) + ".")
        if sh.get("vRepo"):
            self.table(["Clúster", "Nodo", "Repositorio", "Estado"], self.rows("vRepo", ["Clúster", "Nodo", "Repositorio", "Estado"]), size=7.5)

        # 3. Red
        self.h(_("3. Red"))
        self.h(_("Bonds"), 3)
        self.table(["Nodo", "Bond", "Modo", "Esclavos", _("Hash"), "MTU", "Usado por"],
                   self.rows("vBond", ["Nodo", "Bond", "Modo", "Esclavos", "Hash (xmit_hash_policy)", "MTU", "Usado por"]), size=7.5)
        self.h(_("Bridges"), 3)
        self.table(["Nodo", "Bridge", "Puertos", "VLAN aware", "CIDR", "Gateway", "MTU", _("VLANs usadas")],
                   self.rows("vBridge", ["Nodo", "Bridge", "Puertos", "VLAN aware", "CIDR", "Gateway", "MTU", "VLANs usadas por VMs"]), size=7.5)
        if sh.get("vHostVLAN"):
            self.h(_("Interfaces VLAN"), 3)
            self.table(["Nodo", "Interfaz", "VLAN", "Dispositivo", "CIDR", "MTU"],
                       self.rows("vHostVLAN", ["Nodo", "Interfaz", "VLAN id", "Dispositivo base", "CIDR", "MTU"]), size=7.5)
        if an.has_sdn():
            self.h("SDN", 3)
            self.p(_("Configuración SDN: {sdn_summary}.", sdn_summary=an.sdn_summary()))
            self.sdn_tables(an, level=4)
        else:
            self.p(_("SDN: no configurado."))
        if sh.get("vCorosync"):
            self.h(_("Corosync"), 3)
            self.table(["Nodo", "ID", "Votos", "Enlaces", "Direcciones"],
                       self.rows("vCorosync", ["Nodo", "Node ID", "Votos", "Enlaces", "Direcciones"]), size=7.5)

        # 4. Almacenamiento
        self.h(_("4. Almacenamiento"))
        self.table(["Clúster", "Nodo", "Almacenamiento", "Tipo", "Compartido", "Contenido", "Total (GiB)", "Uso (%)"],
                   [[r["Clúster"], r["Nodo"], r["Almacenamiento"], r["Tipo"], r["Compartido"], r["Contenido"], r["Total (GiB)"], r["Uso (%)"]]
                    for r in an.storage_usage()], size=7.5)
        if sh.get("vCephPool"):
            self.h("Ceph", 3)
            self.table(["Pool", _("Réplicas"), _("Mín."), "PGs", "Autoscale", "Usado (GiB)", "Uso (%)"],
                       self.rows("vCephPool", ["Pool", "Réplicas (size)", "Mín. réplicas", "PGs", "Autoscale", "Usado (GiB)", "Uso (%)"]), size=8)
            osd = Counter((r.get("Host"), r.get("Clase")) for r in sh.get("vCephOSD", []))
            self.p(_("OSDs por nodo: ") + ", ".join(f"{h} ({c}): {n}" for (h, c), n in sorted(osd.items(), key=lambda x: str(x[0]))) + ".")
        if sh.get("vZFS"):
            self.h("ZFS", 3)
            self.table(["Nodo", "Pool", "Estado", "Tamaño (GiB)", "Uso (%)", "Fragmentación (%)"],
                       self.rows("vZFS", ["Nodo", "Pool", "Estado", "Tamaño (GiB)", "Uso (%)", "Fragmentación (%)"]), size=8)
        if sh.get("vPhysicalDisk"):
            self.h(_("Discos físicos"), 3)
            self.table(["Nodo", "Dispositivo", "Tipo", "Modelo", "Tamaño (GiB)", "SMART", "Desgaste (%)", "Uso"],
                       self.rows("vPhysicalDisk", ["Nodo", "Dispositivo", "Tipo", "Modelo", "Tamaño (GiB)", "SMART", "Desgaste (%)", "Uso"]), size=7)

        # 5. Alta disponibilidad y replicación
        self.h(_("5. Alta disponibilidad y replicación"))
        if sh.get("vHA"):
            self.table(["Elemento", "Recurso", "Estado", "Grupo", "Máx. reinicios", "Máx. reubicaciones"],
                       self.rows("vHA", ["Elemento", "Recurso", "Estado solicitado", "Grupo", "Máx. reinicios", "Máx. reubicaciones"]), size=8)
        else:
            self.p(_("No hay recursos de alta disponibilidad configurados."))
        if sh.get("vReplication"):
            cols = list(sh["vReplication"][0].keys())[:7]
            self.table(cols, self.rows("vReplication", cols), size=7.5)

        # 6. Backup
        self.h(_("6. Copias de seguridad"))
        if sh.get("vBackup"):
            self.table(["Job", "Habilitado", "Planificación", "Almacenamiento", "Modo", "Selección", "Retención"],
                       self.rows("vBackup", ["Job", "Habilitado", "Planificación", "Almacenamiento", "Modo", "Selección", "Retención"]), size=7.5)
        else:
            self.p(_("No hay trabajos de backup configurados."), bold=True)
        bk = an.backup_summary()
        self.p(_("VMs/CTs con copia: {with_backup} · sin copia registrada: {without_backup}.", with_backup=bk['with_backup'], without_backup=bk['without_backup']))
        nob = [r for r in sh.get("vBackupStatus", []) if not (num(r.get("Nº copias"), 0) or 0)]
        if nob:
            self.table(["Clúster", "VMID", "Nombre", "Estado"], [[r.get("Clúster"), r.get("VMID"), r.get("Nombre"), r.get("Estado VM")] for r in nob[:50]], size=7.5)

        # 7. Seguridad
        self.h(_("7. Seguridad y accesos"))
        users = sh.get("vUsers", [])
        self.p(_("Usuarios y tokens: {n_users} · reglas de firewall: {n_get} · objetos de firewall: {n_get2}.", n_users=len(users), n_get=len(sh.get('vFirewall', [])), n_get2=len(sh.get('vFirewallObj', []))))
        if users:
            self.table(["Tipo", "ID", "Habilitado", "Caduca", "Realm", "Grupos"], self.rows("vUsers", ["Tipo", "ID", "Habilitado", "Caduca", "Realm", "Grupos"]), size=7.5)
        if sh.get("vACL"):
            self.table(["Ruta", "Tipo", "Usuario / grupo", "Rol", "Propagar"], self.rows("vACL", ["Ruta", "Tipo", "Usuario / grupo", "Rol", "Propagar"]), size=7.5)
        if sh.get("vCert"):
            self.h(_("Certificados"), 3)
            self.table(["Nodo", "Fichero", "Emisor", "Válido hasta", "Días restantes"],
                       self.rows("vCert", ["Nodo", "Fichero", "Emisor", "Válido hasta", "Días restantes"]), size=7.5)

        # 8. VMs
        self.h(_("8. Máquinas virtuales y contenedores"))
        self.table(["Clúster", "Nodo", "VMID", "Nombre", "Tipo", "Estado", "vCPU", "RAM (GiB)", _("Disco (GiB)"), "HA", "Último backup"],
                   [[g.cluster, g.node, g.vmid, g.name, g.kind, _("plantilla") if g.template else ("on" if g.running else "off"), g.vcpu,
                     round(g.ram_gib, 1), round(g.disk_prov_gib), "Sí" if g.ha else "", g.last_backup[:10]] for g in an.all_guests], size=7)

        # 9. Salud
        self.h(_("9. Avisos en el momento del inventario"))
        hl = sh.get("vHealth", [])
        if hl:
            order = {"CRÍTICO": 0, "AVISO": 1, "INFO": 2}
            self.table(["Severidad", "Clúster", "Objeto", "Mensaje"],
                       [[r.get("Severidad"), r.get("Clúster"), r.get("Objeto"), r.get("Mensaje")]
                        for r in sorted(hl, key=lambda r: order.get(r.get("Severidad"), 3))], size=7.5)
        else:
            self.p(_("Sin avisos."))

        # 10. Operación
        self.h(_("10. Operación y mantenimiento"))
        ceph = an.has_ceph()
        self.h(_("Actualizar los nodos (uno a uno)"), 3)
        self.numbered([_("Comprobar que el clúster está sano (pvecm status") + (_(", ceph -s") if ceph else "") + ").",
                       _("Migrar las VMs del nodo (o usar el modo mantenimiento de HA: ha-manager crm-command node-maintenance enable <nodo>)."),
                       (_("Ceph: ceph osd set noout. ") if ceph else "") + _("apt update && apt full-upgrade; reiniciar si hay nuevo kernel."),
                       _("Volver a activar el nodo (node-maintenance disable") + (_(", ceph osd unset noout") if ceph else "") + _(") y pasar al siguiente.")])
        self.h(_("Comprobaciones periódicas"), 3)
        self.checklist([_("Estado del clúster y quórum."), _("Resultado de los backups y de las verificaciones del PBS."),
                        _("Ocupación de los almacenamientos (< 80 %).") + (_(" Estado de Ceph (HEALTH_OK).") if ceph else ""),
                        _("Caducidad de certificados y de suscripciones."), _("Avisos SMART y desgaste de discos."),
                        _("Actualizaciones pendientes (repositorio enterprise).")])
        self.h(_("Restaurar una VM"), 3)
        self.p(_("Almacenamiento de backup → seleccionar la copia → Restaurar (opción «live-restore» para arrancarla mientras se restaura). "
               "Para ficheros sueltos: «Restauración de ficheros»."))

        # 11. Datos de configuración (opcional)
        n = 11
        if self.config_path:
            try:
                cfg = read_config_sheet(self.config_path)
            except Exception as exc:  # noqa: BLE001
                cfg = []
                self.p(_("No se pudo leer la hoja de configuración: {exc}", exc=exc), italic=True, color=GREY)
            if cfg:
                self.h(_("{n}. Datos de configuración (hoja de implementación)", n=n))
                self.p(_("Valores de la hoja de configuración del proyecto (sin contraseñas ni claves)."), italic=True, color=GREY)
                self.kv(cfg, size=8.5)
                n += 1

        # Guía rápida (cheatsheet) y contacto
        self.page_break()
        add_cheatsheets(self, sh, n)
        self.page_break()
        add_contact(self, n + 1, self.author)
        path = atomic_save(path, self.d.save)
        return path


def to_asbuilt_docx(sheets, path, client="", author="", config_path=None):
    return AsBuiltDoc(sheets, client, author, config_path).build(path)


__all__ = ["to_asbuilt_docx", "read_config_sheet", "yes"]
