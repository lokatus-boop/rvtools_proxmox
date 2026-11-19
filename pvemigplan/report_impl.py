"""Guía de implementación para Servicios Profesionales (Word)."""
from __future__ import annotations

from pvetools.i18n import N_, _, fmt_date

import os
import tempfile

from .branding import COMPANY
from .config_sheet import defaults_from_inventory
from .network import USO_LABEL
from .report_docx import GREY, Doc
from .sdn_commands import sdn_commands
from .scenario import PBS_VERSIONS, STORAGE_TYPES
from pvetools.safefile import atomic_save

BLANK = "________"


class ImplDoc(Doc):
    TITLE = N_("Guía de implementación Proxmox VE")

    def build(self, path, charts_dir=None):
        plan, sc = self.plan, self.plan.sc
        net = plan.net
        imp = defaults_from_inventory(plan)
        typ = plan.storage_type
        spec = plan.nodes[0]["spec"]
        tmp = charts_dir or tempfile.mkdtemp(prefix="pvemigplan_")
        from .diagrams import network_diagram
        charts = {}
        try:
            charts["destino_red"] = network_diagram(plan, tmp)
        except Exception as exc:  # noqa: BLE001
            print(_("Aviso: diagrama de red no generado: {exc}", exc=exc))

        self.cover(_("Guía de implementación"), _("Proxmox VE {pve_version}", pve_version=sc['pve_version']) + (_(" + Proxmox Backup Server {get}", get=PBS_VERSIONS.get(sc['pve_version'], '4.x')) if plan.pbs else ""),
                   [_("Cliente: {v}", v=sc.get('cliente') or '—'), _("Fecha: {generated}", generated=fmt_date(plan.generated)), _("Preparado por: {v}", v=sc.get('autor') or COMPANY),
                    _("Destinatarios: Servicios Profesionales / Implementación")],
                   _("Documento de trabajo interno. Completar los campos marcados con ________ con los datos acordados con el cliente "
                   "(hoja de configuración). No anotar contraseñas en este documento."))

        num = iter(range(1, 50))
        mig = plan.migrate
        # 1. Resumen
        self.h(_("{next}. Resumen del diseño", next=next(num)))
        self.kv([
            ("Clúster", _("{cluster} · {n_nodes} nodos {model}", cluster=imp['cluster'], n_nodes=len(plan.nodes), model=spec.model)),
            ("Versión", _("Proxmox VE {pve_version}", pve_version=sc['pve_version'])),
            ("Almacenamiento", _(STORAGE_TYPES.get(typ, typ)) + (f" ({net.proto})" if typ == "san" else "")),
            ("Backup", _("Proxmox Backup Server · {util_necesario_gib:.1f} TiB útiles", util_necesario_gib=plan.pbs['util_necesario_gib'] / 1024) if plan.pbs else _("Sin PBS en el alcance")),
            (_("Switches"), "; ".join(f"{w['tipo']}: {w['cantidad']}× {w['modelo']} ({w['suministra']})" for w in net.switches)),
        ] + [(_("Migración"), _("{nombre} · {n_waves} olas", nombre=plan.method['nombre'], n_waves=len(plan.waves)) if mig else _("No incluida (solo implantación de la plataforma)"))])
        self.p(_("Documentos relacionados: documento de diseño para el cliente, Excel del plan (hojas «Cableado», «Puertos nodo»")
               + (_(", «Ubicación VMs», «Olas detalle»") if mig else "") + _(") y hoja de configuración del cliente."), italic=True, color=GREY)

        # 2. Datos generales
        self.h(_("{next}. Datos generales", next=next(num)))
        self.kv([(_("Nombre del clúster"), imp["cluster"]), (_("Patrón de nombres"), imp.get("patron_hostname") or "pve{nn}"),
                 (_("Dominio DNS"), imp.get("dominio") or BLANK), (_("Servidores DNS"), imp.get("dns") or BLANK),
                 (_("Servidores NTP"), imp.get("ntp") or BLANK), ("Zona horaria", imp.get("zona_horaria") or "Europe/Madrid"),
                 (_("Proxy / SMTP / SNMP"), _("Según hoja de configuración"))])
        corosync2 = any(n["red"] == "Cluster (corosync) 2" for n in plan.networks)
        cols = ["Nodo", _("IP gestión"), _("IP iRMC"), _("IP corosync 1")] + ([_("IP corosync 2")] if corosync2 else []) + [_("Nº serie")]
        self.table(cols, [[n["name"]] + [BLANK] * (len(cols) - 1) for n in plan.nodes]
                   + ([["pbs01"] + [BLANK] * (len(cols) - 1)] if plan.pbs else []), size=8.5)

        # 3. Hardware y preparación
        self.h(_("{next}. Hardware y preparación de los servidores", next=next(num)))
        self.kv([("Servidor", f"{len(plan.nodes)}× {spec.model}"), ("CPU", spec.cpu_label or _("{sockets}× {cores_per_socket} cores", sockets=spec.sockets, cores_per_socket=spec.cores_per_socket)),
                 ("RAM", f"{spec.ram_gib} GiB"), ("Arranque", spec.boot),
                 (_("Discos de datos"), _("{data_disks}× {data_disk_tb:g} TB {data_disk_type}", data_disks=spec.data_disks, data_disk_tb=spec.data_disk_tb, data_disk_type=spec.data_disk_type) if spec.data_disks else "No"),
                 ("Red", ", ".join(f"{x['puertos']}× {x['gbps']:g} {'Gb FC' if x.get('uso') == 'fc' else 'GbE'} ({_(USO_LABEL.get(x.get('uso'), x.get('uso', '')))})" for x in spec.nics))])
        self.checklist([
            _("Actualizar firmware (BIOS, iRMC, controladoras, NICs, discos) a la versión soportada."),
            _("iRMC: IP, usuario de administración y licencia; comprobar acceso a la consola remota."),
            _("BIOS: virtualización (VT-x/AMD-V) y VT-d/IOMMU activados; perfil de energía de rendimiento; arranque UEFI."),
            _("Arranque: 2 discos en espejo (ZFS RAID1 desde el instalador o RAID1 por hardware)."),
            (_("Discos de datos en modo HBA/JBOD (sin RAID) para Ceph.") if typ == "ceph" else
             _("Discos de datos en modo HBA/JBOD para ZFS.") if typ == "zfs" else _("Sin discos de datos locales (almacenamiento externo).")),
            _("Etiquetar cada servidor y cable según la tabla de cableado."),
        ])

        # 4. Cableado
        self.orientation(True)
        self.h(_("{next}. Cableado y switches", next=next(num)))
        if "destino_red" in charts:
            self.img(charts, "destino_red", 24.5, _("Esquema físico de red"))
        self.orientation(False)
        self.h(_("Puertos de cada nodo (nombres fijos de interfaz)"), 3)
        self.table([_("Enlace"), _("Adaptador"), "Puerto", "Nombre", "Bond", "Uso"],
                   [[r["Host Link"], r["Adapter"], r["Port No."], r["Device Name"], r["Bond No."], r["Usage"]] for r in net.host_ports], size=8)
        self.p(_("Fijar los nombres de interfaz (pinning) para que no cambien con actualizaciones de kernel o firmware; "
               "usar los nombres de la columna «Nombre»."))
        self.h(_("Asignación de puertos de switch (orientativa)"), 3)
        self.table(["Switch", "Puerto", "Equipo", "Uso", "Velocidad"],
                   [[r["Switch"], r["Puerto"], r["Equipo"], r["Uso"], r["Velocidad"]] for r in net.switch_port_map()], size=7.5)
        self.h(_("Configuración de los switches"), 3)
        vl = next((n["vlan"] for n in plan.networks if n["red"] == "Payload (VMs)"), "")
        self.checklist([
            _("Switches de servicio en MLAG/stack (o Virtual Chassis); uplinks hacia la red del cliente según lo acordado."),
            _("Por cada nodo: LAG LACP (802.3ad, modo activo) con un puerto en cada switch para bond1")
            + (_(" y bond2") if typ in ("ceph", "nfs") else "") + _("; bond0 (gestión) en active-backup sin LAG."),
            _("VLANs en los LAG de VMs: {v} + migración, corosync 2", v=vl or (_('según inventario') if plan.has_load else _('según hoja de configuración'))) + (_(" y backup") if plan.pbs else "") + ".",
            _("MTU 9216 en puertos y LAG con jumbo frames (almacenamiento, migración, backup)."),
            _("Puertos iRMC en el switch OOB, VLAN de gestión fuera de banda."),
        ] + ([_("Zoning FC por WWPN (un HBA por fabric) hacia ambas controladoras.")] if net.fc else [])
          + ([_("iSCSI: dos VLANs/subredes independientes, una por switch, sin LAG.")] if typ == "san" and not net.fc else []))

        # 5. Instalación
        self.h(_("{next}. Instalación de Proxmox VE", next=next(num)))
        self.checklist([
            _("Instalar Proxmox VE {pve_version} desde la ISO en cada nodo (ZFS RAID1 en los discos de arranque).", pve_version=sc['pve_version']),
            _("Nombre FQDN y IP de gestión según la tabla de datos generales."),
            _("Repositorios: enterprise + clave de suscripción de cada nodo (hoja «PVE Subscriptions»); actualizar el sistema."),
            _("Configurar NTP (chrony), DNS y, si aplica, proxy y servidor SMTP para notificaciones."),
        ])
        self.code(_("pvesubscription set <CLAVE>\napt update && apt full-upgrade -y\nreboot"))
        self.h(_("Red del nodo (ejemplo para el primer nodo)"), 3)
        self.code(self._interfaces(plan, imp))

        # 6. Clúster
        self.h(_("{next}. Creación del clúster", next=next(num)))
        n1 = plan.nodes[0]["name"]
        self.code(_("# en {n1}\npvecm create {cluster} --link0 <IP-COROSYNC1-{n1}>", n1=n1, cluster=imp['cluster']) + (_(" --link1 <IP-COROSYNC2-{n1}>", n1=n1) if corosync2 else "")
                  + _("\n\n# en cada uno de los demás nodos\npvecm add <IP-GESTION-") + n1 + _("> --link0 <IP-COROSYNC1-NODO>")
                  + (_(" --link1 <IP-COROSYNC2-NODO>") if corosync2 else "") + _("\n\npvecm status"))
        self.checklist([_("Datacenter → Opciones → Red de migración: subred de Live Migration."),
                        _("Datacenter → Opciones: teclado, política de apagado HA, notificaciones por correo."),
                        _("Usuarios y roles del cliente (realm LDAP/AD si aplica); 2FA para administradores.")])

        # 7. Almacenamiento
        self.h(_("{next}. Almacenamiento", next=next(num)))
        self.code(self._storage_cmds(plan))

        # 8. SDN
        an = plan.an
        if plan.vlan_map or an.has_sdn():
            self.h(_("{next}. Redes de las VMs (SDN)", next=next(num)))
            if an.has_sdn():
                self.p(_("El entorno actual tiene SDN ({sdn_summary}). Se recrea con los mismos nombres, tags/VNI y subredes para que las VMs migradas se conecten a la misma VNet. Los valores entre < > se completan con los datos del nuevo entorno (IPs de los nodos, tokens y claves, que nunca se incluyen en el inventario).", sdn_summary=an.sdn_summary()))
                self.sdn_tables(an, level=3, size=7)
            else:
                self.p(_("Crear una zona VLAN sobre vmbr1 y una VNet por cada VLAN usada por las VMs del entorno actual:"))
            self.code(sdn_commands(plan))
            checks = [_("Datacenter → SDN: estado «available» en todos los nodos tras aplicar."),
                      _("Comprobar desde una VM de prueba en cada VNet: gateway, DNS y salida a la red.")]
            if any(z["type"] in ("evpn", "vxlan") for z in an.sdn()["zones"]):
                checks.append(_("EVPN/VXLAN: «vtysh -c 'show bgp l2vpn evpn summary'» con todos los peers establecidos y MTU "
                              "de la red física suficiente para VXLAN."))
            self.checklist(checks)
            untagged = [r for r in plan.vlan_map if not str(r["VLAN origen"]).isdigit() and not r.get("Tipo zona SDN origen")]
            if untagged:
                self.p(_("Redes sin VLAN en origen (definir VLAN explícita con el cliente): ")
                       + ", ".join(f"{r['Bridge origen']} ({r['NICs de VMs']} NICs)" for r in untagged) + ".")

        # 9. PBS
        if plan.pbs:
            p = plan.pbs
            r = sc["pbs"]["retencion"]
            self.h(_("{next}. Proxmox Backup Server", next=next(num)))
            self.kv([(_("Hardware"), _("{cores} cores · {ram_gib} GiB RAM", cores=p['propuesta']['cores'], ram_gib=p['propuesta']['ram_gib'])),
                     (_("Datastore"), _("{util_necesario_gib:.1f} TiB útiles · {discos}", util_necesario_gib=p['util_necesario_gib'] / 1024, discos=p['propuesta']['discos'])),
                     ("Retención", _("keep-daily={diaria}, keep-weekly={semanal}, keep-monthly={mensual}", diaria=r['diaria'], semanal=r['semanal'], mensual=r['mensual'])
                      + (_(", keep-yearly={anual}", anual=r['anual']) if r.get("anual") else ""))])
            self.code(_("# en el PBS\nproxmox-backup-manager datastore create store1 /mnt/datastore/store1\nproxmox-backup-manager user create pve-backup@pbs\nproxmox-backup-manager acl update /datastore/store1 DatastoreBackup --auth-id pve-backup@pbs\n\n# en el clúster Proxmox VE\npvesm add pbs pbs01 --server <IP-PBS> --datastore store1 --username pve-backup@pbs --fingerprint <HUELLA> --password\n# Job de backup diario (GUI: Datacenter → Backup) y en el PBS: verify semanal, prune (keep-daily={diaria} keep-weekly={semanal} keep-monthly={mensual}) y garbage collection", diaria=r['diaria'], semanal=r['semanal'], mensual=r['mensual']))
            if sc["pbs"].get("offsite"):
                self.p(_("Copia externa: segundo PBS con «remote» y «sync job» desde store1."))

        # 10. Migración
        if mig:
            self._runbook(plan, next(num))

        # 11. Pruebas
        self._acceptance(plan, typ, next(num))

        # 12. Entrega
        self.h(_("{next}. Entrega a postventa", next=next(num)))
        self.p(_("Al terminar, ejecutar PVE Inventory contra el nuevo clúster") + (_(" y el PBS") if plan.pbs else "")
               + _(" y generar con el planificador la documentación «as-built» para el departamento de postventa."))
        path = atomic_save(path, self.d.save)
        if not charts_dir:
            for f in charts.values():
                try:
                    os.remove(f)
                except OSError:
                    pass
        return path

    def _runbook(self, plan, n):
        self.h(_("{n}. Migración (runbook)", n=n))
        self.p(plan.method["nombre"] + ".", bold=True)
        self.numbered(plan.method["pasos"])
        self.code(self._migration_cmds(plan))
        issues = {}
        for it in plan.issues:
            if it["VMID"]:
                issues.setdefault(f"{it['Clúster']}/{it['VMID']}", []).append(it["Categoría"])
        for w in plan.waves:
            self.h(f"{w['nombre']}" + (" · " + fmt_date(w['fecha']) if w.get("fecha") else _(" · día {dia}", dia=w['dia'])), 3)
            self.table(["VMID", "Nombre", "Tipo", "Datos (GiB)", "Nodo destino", _("Revisar"), "OK"],
                       [[g.vmid, g.name, g.kind, round(g.disk_effective_gib), plan.placement.get(g.key),
                         ", ".join(sorted(set(issues.get(g.key, [])))), "☐"] for g in w["guests"]], size=7.5)
        ha = [g for g in plan.an.guests if g.ha]
        if ha:
            self.p(_("Tras migrar, dar de alta en HA: ") + ", ".join(f"{g.name} ({g.vmid})" for g in ha[:60]) + ".")

    def _acceptance(self, plan, typ, n):
        self.h(_("{n}. Pruebas de aceptación", n=n))
        self.checklist([
            _("Quórum y estado del clúster (pvecm status) con los enlaces corosync redundantes."),
            _("Caída de un enlace de cada bond y de un switch: sin pérdida de servicio."),
            _("Migración en caliente de una VM entre todos los nodos."),
            _("HA: apagado forzado de un nodo y rearranque de sus VMs en otro."),
        ] + ([_("Ceph: HEALTH_OK; fallo de un OSD y de un nodo; tiempo de recuperación.")] if typ == "ceph" else [])
          + ([_("Multipath: caída de un camino/controladora sin pérdida de acceso.")] if typ == "san" else [])
          + ([_("Backup y restauración (completa, de ficheros y live-restore) desde el PBS.")] if plan.pbs else [])
          + [_("Notificaciones por correo y alertas."), _("Entrega de credenciales al cliente por canal seguro.")])

    @staticmethod
    def _interfaces(plan, imp):
        net = plan.net
        hp = net.host_ports
        dev = lambda prefix: [r["Device Name"] for r in hp if r["Device Name"].startswith(prefix)]  # noqa: E731
        mtu = 9000 if plan.sc["red"].get("jumbo", True) else 1500
        out = [_("auto lo"), _("iface lo inet loopback"), ""]
        for d in sorted({r["Device Name"] for r in hp if not r["Device Name"].startswith("fc_")}):
            m = mtu if not d.startswith("mgmt") else 1500
            out += [_("iface {d} inet manual", d=d), f"    mtu {m}", ""]
        out += [_("auto bond0"), _("iface bond0 inet manual"), f"    bond-slaves {' '.join(dev('mgmt'))}", _("    bond-mode active-backup"),
                _("    bond-miimon 100"), f"    bond-primary {dev('mgmt')[0] if dev('mgmt') else ''}", "",
                _("auto vmbr0"), _("iface vmbr0 inet static"), _("    address <IP-GESTION>/<prefijo>"), _("    gateway <GATEWAY>"),
                _("    bridge-ports bond0"), _("    bridge-stp off"), _("    bridge-fd 0"), "",
                _("auto bond1"), _("iface bond1 inet manual"), f"    bond-slaves {' '.join(dev('payload'))}", _("    bond-mode 802.3ad"),
                _("    bond-xmit-hash-policy layer3+4"), _("    bond-miimon 100"), f"    mtu {mtu}", "",
                _("auto vmbr1"), _("iface vmbr1 inet manual"), _("    bridge-ports bond1"), _("    bridge-stp off"), _("    bridge-fd 0"),
                _("    bridge-vlan-aware yes"), _("    bridge-vids 2-4094"), f"    mtu {mtu}", ""]
        sto = dev("storage")
        if sto:
            out += [_("auto bond2"), _("iface bond2 inet manual"), f"    bond-slaves {' '.join(sto)}", _("    bond-mode 802.3ad"),
                    _("    bond-xmit-hash-policy layer3+4"), _("    bond-miimon 100"), f"    mtu {mtu}", ""]
        for n in plan.networks:
            if n["interfaz"].endswith(".<vlan>"):
                base = n["interfaz"].split(".")[0]
                name = n["red"].split("(")[0].strip().lower().replace(" ", "-")
                out += [f"# {n['red']}", _("auto {base}.<VLAN-{name}>", base=base, name=name), _("iface {base}.<VLAN-{name}> inet static", base=base, name=name),
                        _("    address <IP-{name}>/<prefijo>", name=name), f"    mtu {n['mtu']}", ""]
        for d in dev("iscsi"):
            out += [f"# {d}", f"auto {d}", _("iface {d} inet static", d=d), _("    address <IP-{d}>/<prefijo>", d=d), f"    mtu {mtu}", ""]
        return "\n".join(out).rstrip()

    @staticmethod
    def _storage_cmds(plan):
        typ = plan.storage_type
        sc = plan.sc
        if typ == "ceph":
            spec = plan.nodes[0]["spec"]
            osd = "\n".join(f"pveceph osd create /dev/nvme{i}n1" for i in range(min(spec.data_disks, 12)))
            return (_("# en todos los nodos\npveceph install --repository enterprise\n\n# en el primer nodo\npveceph init --network <CIDR-CEPH-PUBLIC> --cluster-network <CIDR-CEPH-PRIVATE>\n\n# en 3 nodos (monitores y managers)\npveceph mon create\npveceph mgr create\n\n# en cada nodo, un OSD por disco NVMe de datos ({data_disks} por nodo)\n{osd}\n\npveceph pool create vm-pool --size {get} --min_size 2 --add_storages\nceph -s", data_disks=spec.data_disks, osd=osd, get=sc['almacenamiento'].get('replicas', 3)))
        if typ == "san":
            if plan.net.fc:
                head = _("# FC: zoning hecho en los switches; comprobar que cada nodo ve los LUNs por 2 caminos\nlsblk; multipath -ll\n")
            else:
                head = (_("# iSCSI: en cada nodo (un portal por controladora y red)\n"
                        "iscsiadm -m discovery -t sendtargets -p <IP-CTRL-A-ISCSI1>\n"
                        "iscsiadm -m discovery -t sendtargets -p <IP-CTRL-B-ISCSI2>\n"
                        "iscsiadm -m node --login\niscsiadm -m node --op update -n node.startup -v automatic\n"))
            return (head + _("\napt install multipath-tools\n# /etc/multipath.conf según el fabricante de la cabina; añadir WWIDs\n"
                    "multipath -ll\n\n# en un solo nodo\npvcreate /dev/mapper/<WWID>\nvgcreate vg_san /dev/mapper/<WWID>\n"
                    "pvesm add lvm san-vm --vgname vg_san --shared 1 --content images,rootdir\n"
                    "# PVE 9: opción --snapshot-as-volume-chain 1 para snapshots (vista previa tecnológica)"))
        if typ == "nfs":
            return (_("pvesm add nfs nas-vm --server <IP-NAS> --export <RUTA-EXPORT> --content images,rootdir,iso,vztmpl "
                    "--options vers=4.2\npvesm status"))
        spec = plan.nodes[0]["spec"]
        disks = " ".join(f"/dev/nvme{i}n1" for i in range(min(spec.data_disks, 12)))
        return (_("# en cada nodo: espejos (RAID10) con los discos de datos\nzpool create -o ashift=12 tank mirror {disks}\npvesm add zfspool local-tank --pool tank --content images,rootdir --sparse 1\n\n# replicación por VM hacia otro nodo (cada 15 min)\npvesr create-local-job <VMID>-0 <NODO-DESTINO> --schedule '*/15'", disks=disks))

    @staticmethod
    def _migration_cmds(plan):
        st = {"ceph": "vm-pool", "zfs": "local-tank", "san": "san-vm", "nfs": "nas-vm"}[plan.storage_type]
        if plan.method["id"] == "pbs":
            return (_("# en el clúster de ORIGEN (PBS nuevo añadido como almacenamiento «pbs-new»)\nvzdump <VMID> --storage pbs-new --mode snapshot           # días antes (copia inicial)\nqm shutdown <VMID> && vzdump <VMID> --storage pbs-new --mode stop   # ventana: copia final\n\n# en el clúster de DESTINO\nqmrestore pbs01:backup/vm/<VMID>/<FECHA> <VMID> --storage {st} --live-restore 1\npct restore <VMID> pbs01:backup/ct/<VMID>/<FECHA> --storage {st}     # contenedores\nqm set <VMID> --net0 virtio=<MAC>,bridge=vlan<VLAN>                 # si cambia bridge/VLAN", st=st))
        return (_("# token en DESTINO con permisos de migración; huella del certificado del destino\nqm remote-migrate <VMID> <VMID> 'host=<IP-DESTINO>,apitoken=PVEAPIToken=<ID>=<SECRETO>,fingerprint=<HUELLA>' --target-bridge vmbr1 --target-storage {st} --online\npct remote-migrate <VMID> <VMID> '<mismo endpoint>' --target-bridge vmbr1 --target-storage {st} --restart", st=st))


def to_impl_docx(plan, path, charts_dir=None):
    return ImplDoc(plan).build(path, charts_dir)

