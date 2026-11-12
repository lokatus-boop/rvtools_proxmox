"""Guía de implementación para Servicios Profesionales (Word)."""
from __future__ import annotations

import os
import tempfile

from .branding import COMPANY
from .config_sheet import defaults_from_inventory
from .report_docx import GREY, Doc
from .sdn_commands import sdn_commands
from .scenario import PBS_VERSIONS, STORAGE_TYPES

BLANK = "________"


class ImplDoc(Doc):
    TITLE = "Guía de implementación Proxmox VE"

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
            print(f"Aviso: diagrama de red no generado: {exc}")

        self.cover("Guía de implementación", f"Proxmox VE {sc['pve_version']}" + (f" + Proxmox Backup Server {PBS_VERSIONS.get(sc['pve_version'], '4.x')}" if plan.pbs else ""),
                   [f"Cliente: {sc.get('cliente') or '—'}", f"Fecha: {plan.generated:%d/%m/%Y}", f"Preparado por: {sc.get('autor') or COMPANY}",
                    "Destinatarios: Servicios Profesionales / Implementación"],
                   "Documento de trabajo interno. Completar los campos marcados con ________ con los datos acordados con el cliente "
                   "(hoja de configuración). No anotar contraseñas en este documento.")

        # 1. Resumen
        self.h("1. Resumen del diseño")
        self.kv([
            ("Clúster", f"{imp['cluster']} · {len(plan.nodes)} nodos {spec.model}"),
            ("Versión", f"Proxmox VE {sc['pve_version']}"),
            ("Almacenamiento", STORAGE_TYPES.get(typ, typ) + (f" ({net.proto})" if typ == "san" else "")),
            ("Backup", f"Proxmox Backup Server · {plan.pbs['util_necesario_gib'] / 1024:.1f} TiB útiles" if plan.pbs else "Sin PBS en el alcance"),
            ("Switches", "; ".join(f"{w['tipo']}: {w['cantidad']}× {w['modelo']} ({w['suministra']})" for w in net.switches)),
            ("Migración", f"{plan.method['nombre']} · {len(plan.waves)} olas"),
        ])
        self.p("Documentos relacionados: documento de diseño para el cliente, Excel del plan (hojas «Cableado», «Puertos nodo», "
               "«Ubicación VMs», «Olas detalle») y hoja de configuración del cliente.", italic=True, color=GREY)

        # 2. Datos generales
        self.h("2. Datos generales")
        self.kv([("Nombre del clúster", imp["cluster"]), ("Patrón de nombres", imp.get("patron_hostname") or "pve{nn}"),
                 ("Dominio DNS", imp.get("dominio") or BLANK), ("Servidores DNS", imp.get("dns") or BLANK),
                 ("Servidores NTP", imp.get("ntp") or BLANK), ("Zona horaria", imp.get("zona_horaria") or "Europe/Madrid"),
                 ("Proxy / SMTP / SNMP", "Según hoja de configuración")])
        corosync2 = any(n["red"] == "Cluster (corosync) 2" for n in plan.networks)
        cols = ["Nodo", "IP gestión", "IP iRMC", "IP corosync 1"] + (["IP corosync 2"] if corosync2 else []) + ["Nº serie"]
        self.table(cols, [[n["name"]] + [BLANK] * (len(cols) - 1) for n in plan.nodes]
                   + ([["pbs01"] + [BLANK] * (len(cols) - 1)] if plan.pbs else []), size=8.5)

        # 3. Hardware y preparación
        self.h("3. Hardware y preparación de los servidores")
        self.kv([("Servidor", f"{len(plan.nodes)}× {spec.model}"), ("CPU", spec.cpu_label or f"{spec.sockets}× {spec.cores_per_socket} cores"),
                 ("RAM", f"{spec.ram_gib} GiB"), ("Arranque", spec.boot),
                 ("Discos de datos", f"{spec.data_disks}× {spec.data_disk_tb:g} TB {spec.data_disk_type}" if spec.data_disks else "No"),
                 ("Red", ", ".join(f"{x['puertos']}× {x['gbps']:g} {'Gb FC' if x.get('uso') == 'fc' else 'GbE'} ({x.get('uso')})" for x in spec.nics))])
        self.checklist([
            "Actualizar firmware (BIOS, iRMC, controladoras, NICs, discos) a la versión soportada.",
            "iRMC: IP, usuario de administración y licencia; comprobar acceso a la consola remota.",
            "BIOS: virtualización (VT-x/AMD-V) y VT-d/IOMMU activados; perfil de energía de rendimiento; arranque UEFI.",
            "Arranque: 2 discos en espejo (ZFS RAID1 desde el instalador o RAID1 por hardware).",
            ("Discos de datos en modo HBA/JBOD (sin RAID) para Ceph." if typ == "ceph" else
             "Discos de datos en modo HBA/JBOD para ZFS." if typ == "zfs" else "Sin discos de datos locales (almacenamiento externo)."),
            "Etiquetar cada servidor y cable según la tabla de cableado.",
        ])

        # 4. Cableado
        self.orientation(True)
        self.h("4. Cableado y switches")
        if "destino_red" in charts:
            self.img(charts, "destino_red", 24.5, "Esquema físico de red")
        self.orientation(False)
        self.h("Puertos de cada nodo (nombres fijos de interfaz)", 3)
        self.table(["Enlace", "Adaptador", "Puerto", "Nombre", "Bond", "Uso"],
                   [[r["Host Link"], r["Adapter"], r["Port No."], r["Device Name"], r["Bond No."], r["Usage"]] for r in net.host_ports], size=8)
        self.p("Fijar los nombres de interfaz (pinning) para que no cambien con actualizaciones de kernel o firmware; "
               "usar los nombres de la columna «Nombre».")
        self.h("Asignación de puertos de switch (orientativa)", 3)
        self.table(["Switch", "Puerto", "Equipo", "Uso", "Velocidad"],
                   [[r["Switch"], r["Puerto"], r["Equipo"], r["Uso"], r["Velocidad"]] for r in net.switch_port_map()], size=7.5)
        self.h("Configuración de los switches", 3)
        vl = next((n["vlan"] for n in plan.networks if n["red"] == "Payload (VMs)"), "")
        self.checklist([
            "Switches de servicio en MLAG/stack (o Virtual Chassis); uplinks hacia la red del cliente según lo acordado.",
            "Por cada nodo: LAG LACP (802.3ad, modo activo) con un puerto en cada switch para bond1"
            + (" y bond2" if typ in ("ceph", "nfs") else "") + "; bond0 (gestión) en active-backup sin LAG.",
            f"VLANs en los LAG de VMs: {vl or 'según inventario'} + migración, corosync 2" + (" y backup" if plan.pbs else "") + ".",
            "MTU 9216 en puertos y LAG con jumbo frames (almacenamiento, migración, backup).",
            "Puertos iRMC en el switch OOB, VLAN de gestión fuera de banda.",
        ] + (["Zoning FC por WWPN (un HBA por fabric) hacia ambas controladoras."] if net.fc else [])
          + (["iSCSI: dos VLANs/subredes independientes, una por switch, sin LAG."] if typ == "san" and not net.fc else []))

        # 5. Instalación
        self.h("5. Instalación de Proxmox VE")
        self.checklist([
            f"Instalar Proxmox VE {sc['pve_version']} desde la ISO en cada nodo (ZFS RAID1 en los discos de arranque).",
            "Nombre FQDN y IP de gestión según la tabla de datos generales.",
            "Repositorios: enterprise + clave de suscripción de cada nodo (hoja «PVE Subscriptions»); actualizar el sistema.",
            "Configurar NTP (chrony), DNS y, si aplica, proxy y servidor SMTP para notificaciones.",
        ])
        self.code("pvesubscription set <CLAVE>\napt update && apt full-upgrade -y\nreboot")
        self.h("Red del nodo (ejemplo para el primer nodo)", 3)
        self.code(self._interfaces(plan, imp))

        # 6. Clúster
        self.h("6. Creación del clúster")
        n1 = plan.nodes[0]["name"]
        self.code(f"# en {n1}\npvecm create {imp['cluster']} --link0 <IP-COROSYNC1-{n1}>" + (f" --link1 <IP-COROSYNC2-{n1}>" if corosync2 else "")
                  + "\n\n# en cada uno de los demás nodos\npvecm add <IP-GESTION-" + n1 + "> --link0 <IP-COROSYNC1-NODO>"
                  + (" --link1 <IP-COROSYNC2-NODO>" if corosync2 else "") + "\n\npvecm status")
        self.checklist(["Datacenter → Opciones → Red de migración: subred de Live Migration.",
                        "Datacenter → Opciones: teclado, política de apagado HA, notificaciones por correo.",
                        "Usuarios y roles del cliente (realm LDAP/AD si aplica); 2FA para administradores."])

        # 7. Almacenamiento
        self.h("7. Almacenamiento")
        self.code(self._storage_cmds(plan))

        # 8. SDN
        an = plan.an
        if plan.vlan_map or an.has_sdn():
            self.h("8. Redes de las VMs (SDN)")
            if an.has_sdn():
                self.p(f"El entorno actual tiene SDN ({an.sdn_summary()}). Se recrea con los mismos nombres, tags/VNI y subredes "
                       "para que las VMs migradas se conecten a la misma VNet. Los valores entre < > se completan con los datos "
                       "del nuevo entorno (IPs de los nodos, tokens y claves, que nunca se incluyen en el inventario).")
                self.sdn_tables(an, level=3, size=7)
            else:
                self.p("Crear una zona VLAN sobre vmbr1 y una VNet por cada VLAN usada por las VMs del entorno actual:")
            self.code(sdn_commands(plan))
            checks = ["Datacenter → SDN: estado «available» en todos los nodos tras aplicar.",
                      "Comprobar desde una VM de prueba en cada VNet: gateway, DNS y salida a la red."]
            if any(z["type"] in ("evpn", "vxlan") for z in an.sdn()["zones"]):
                checks.append("EVPN/VXLAN: «vtysh -c 'show bgp l2vpn evpn summary'» con todos los peers establecidos y MTU "
                              "de la red física suficiente para VXLAN.")
            self.checklist(checks)
            untagged = [r for r in plan.vlan_map if not str(r["VLAN origen"]).isdigit() and not r.get("Tipo zona SDN origen")]
            if untagged:
                self.p("Redes sin VLAN en origen (definir VLAN explícita con el cliente): "
                       + ", ".join(f"{r['Bridge origen']} ({r['NICs de VMs']} NICs)" for r in untagged) + ".")

        # 9. PBS
        if plan.pbs:
            p = plan.pbs
            r = sc["pbs"]["retencion"]
            self.h("9. Proxmox Backup Server")
            self.kv([("Hardware", f"{p['propuesta']['cores']} cores · {p['propuesta']['ram_gib']} GiB RAM"),
                     ("Datastore", f"{p['util_necesario_gib'] / 1024:.1f} TiB útiles · {p['propuesta']['discos']}"),
                     ("Retención", f"keep-daily={r['diaria']}, keep-weekly={r['semanal']}, keep-monthly={r['mensual']}"
                      + (f", keep-yearly={r['anual']}" if r.get("anual") else ""))])
            self.code("# en el PBS\nproxmox-backup-manager datastore create store1 /mnt/datastore/store1\n"
                      "proxmox-backup-manager user create pve-backup@pbs\n"
                      "proxmox-backup-manager acl update /datastore/store1 DatastoreBackup --auth-id pve-backup@pbs\n\n"
                      "# en el clúster Proxmox VE\npvesm add pbs pbs01 --server <IP-PBS> --datastore store1 --username pve-backup@pbs "
                      "--fingerprint <HUELLA> --password\n"
                      f"# Job de backup diario (GUI: Datacenter → Backup) y en el PBS: verify semanal, prune "
                      f"(keep-daily={r['diaria']} keep-weekly={r['semanal']} keep-monthly={r['mensual']}) y garbage collection")
            if sc["pbs"].get("offsite"):
                self.p("Copia externa: segundo PBS con «remote» y «sync job» desde store1.")

        # 10. Migración
        self.h("10. Migración (runbook)")
        self.p(plan.method["nombre"] + ".", bold=True)
        self.numbered(plan.method["pasos"])
        self.code(self._migration_cmds(plan))
        issues = {}
        for it in plan.issues:
            if it["VMID"]:
                issues.setdefault(f"{it['Clúster']}/{it['VMID']}", []).append(it["Categoría"])
        for w in plan.waves:
            self.h(f"{w['nombre']}" + (f" · {w['fecha']:%d/%m/%Y}" if w.get("fecha") else f" · día {w['dia']}"), 3)
            self.table(["VMID", "Nombre", "Tipo", "Datos (GiB)", "Nodo destino", "Revisar", "OK"],
                       [[g.vmid, g.name, g.kind, round(g.disk_effective_gib), plan.placement.get(g.key),
                         ", ".join(sorted(set(issues.get(g.key, [])))), "☐"] for g in w["guests"]], size=7.5)
        ha = [g for g in plan.an.guests if g.ha]
        if ha:
            self.p("Tras migrar, dar de alta en HA: " + ", ".join(f"{g.name} ({g.vmid})" for g in ha[:60]) + ".")

        # 11. Pruebas
        self.h("11. Pruebas de aceptación")
        self.checklist([
            "Quórum y estado del clúster (pvecm status) con los enlaces corosync redundantes.",
            "Caída de un enlace de cada bond y de un switch: sin pérdida de servicio.",
            "Migración en caliente de una VM entre todos los nodos.",
            "HA: apagado forzado de un nodo y rearranque de sus VMs en otro.",
        ] + (["Ceph: HEALTH_OK; fallo de un OSD y de un nodo; tiempo de recuperación."] if typ == "ceph" else [])
          + (["Multipath: caída de un camino/controladora sin pérdida de acceso."] if typ == "san" else [])
          + (["Backup y restauración (completa, de ficheros y live-restore) desde el PBS."] if plan.pbs else [])
          + ["Notificaciones por correo y alertas.", "Entrega de credenciales al cliente por canal seguro."])

        # 12. Entrega
        self.h("12. Entrega a postventa")
        self.p("Al terminar, ejecutar PVE Inventory contra el nuevo clúster" + (" y el PBS" if plan.pbs else "")
               + " y generar con el planificador la documentación «as-built» para el departamento de postventa.")
        self.d.save(path)
        if not charts_dir:
            for f in charts.values():
                try:
                    os.remove(f)
                except OSError:
                    pass
        return path

    # ------------------------------------------------------------------ fragmentos
    @staticmethod
    def _interfaces(plan, imp):
        net = plan.net
        hp = net.host_ports
        dev = lambda prefix: [r["Device Name"] for r in hp if r["Device Name"].startswith(prefix)]  # noqa: E731
        mtu = 9000 if plan.sc["red"].get("jumbo", True) else 1500
        out = ["auto lo", "iface lo inet loopback", ""]
        for d in sorted({r["Device Name"] for r in hp if not r["Device Name"].startswith("fc_")}):
            m = mtu if not d.startswith("mgmt") else 1500
            out += [f"iface {d} inet manual", f"    mtu {m}", ""]
        out += ["auto bond0", "iface bond0 inet manual", f"    bond-slaves {' '.join(dev('mgmt'))}", "    bond-mode active-backup",
                "    bond-miimon 100", f"    bond-primary {dev('mgmt')[0] if dev('mgmt') else ''}", "",
                "auto vmbr0", "iface vmbr0 inet static", "    address <IP-GESTION>/<prefijo>", "    gateway <GATEWAY>",
                "    bridge-ports bond0", "    bridge-stp off", "    bridge-fd 0", "",
                "auto bond1", "iface bond1 inet manual", f"    bond-slaves {' '.join(dev('payload'))}", "    bond-mode 802.3ad",
                "    bond-xmit-hash-policy layer3+4", "    bond-miimon 100", f"    mtu {mtu}", "",
                "auto vmbr1", "iface vmbr1 inet manual", "    bridge-ports bond1", "    bridge-stp off", "    bridge-fd 0",
                "    bridge-vlan-aware yes", "    bridge-vids 2-4094", f"    mtu {mtu}", ""]
        sto = dev("storage")
        if sto:
            out += ["auto bond2", "iface bond2 inet manual", f"    bond-slaves {' '.join(sto)}", "    bond-mode 802.3ad",
                    "    bond-xmit-hash-policy layer3+4", "    bond-miimon 100", f"    mtu {mtu}", ""]
        for n in plan.networks:
            if n["interfaz"].endswith(".<vlan>"):
                base = n["interfaz"].split(".")[0]
                name = n["red"].split("(")[0].strip().lower().replace(" ", "-")
                out += [f"# {n['red']}", f"auto {base}.<VLAN-{name}>", f"iface {base}.<VLAN-{name}> inet static",
                        f"    address <IP-{name}>/<prefijo>", f"    mtu {n['mtu']}", ""]
        for d in dev("iscsi"):
            out += [f"# {d}", f"auto {d}", f"iface {d} inet static", f"    address <IP-{d}>/<prefijo>", f"    mtu {mtu}", ""]
        return "\n".join(out).rstrip()

    @staticmethod
    def _storage_cmds(plan):
        typ = plan.storage_type
        sc = plan.sc
        if typ == "ceph":
            spec = plan.nodes[0]["spec"]
            osd = "\n".join(f"pveceph osd create /dev/nvme{i}n1" for i in range(min(spec.data_disks, 12)))
            return ("# en todos los nodos\npveceph install --repository enterprise\n\n# en el primer nodo\n"
                    "pveceph init --network <CIDR-CEPH-PUBLIC> --cluster-network <CIDR-CEPH-PRIVATE>\n\n"
                    "# en 3 nodos (monitores y managers)\npveceph mon create\npveceph mgr create\n\n"
                    f"# en cada nodo, un OSD por disco NVMe de datos ({spec.data_disks} por nodo)\n{osd}\n\n"
                    f"pveceph pool create vm-pool --size {sc['almacenamiento'].get('replicas', 3)} --min_size 2 --add_storages\nceph -s")
        if typ == "san":
            if plan.net.fc:
                head = "# FC: zoning hecho en los switches; comprobar que cada nodo ve los LUNs por 2 caminos\nlsblk; multipath -ll\n"
            else:
                head = ("# iSCSI: en cada nodo (un portal por controladora y red)\n"
                        "iscsiadm -m discovery -t sendtargets -p <IP-CTRL-A-ISCSI1>\n"
                        "iscsiadm -m discovery -t sendtargets -p <IP-CTRL-B-ISCSI2>\n"
                        "iscsiadm -m node --login\niscsiadm -m node --op update -n node.startup -v automatic\n")
            return (head + "\napt install multipath-tools\n# /etc/multipath.conf según el fabricante de la cabina; añadir WWIDs\n"
                    "multipath -ll\n\n# en un solo nodo\npvcreate /dev/mapper/<WWID>\nvgcreate vg_san /dev/mapper/<WWID>\n"
                    "pvesm add lvm san-vm --vgname vg_san --shared 1 --content images,rootdir\n"
                    "# PVE 9: opción --snapshot-as-volume-chain 1 para snapshots (vista previa tecnológica)")
        if typ == "nfs":
            return ("pvesm add nfs nas-vm --server <IP-NAS> --export <RUTA-EXPORT> --content images,rootdir,iso,vztmpl "
                    "--options vers=4.2\npvesm status")
        spec = plan.nodes[0]["spec"]
        disks = " ".join(f"/dev/nvme{i}n1" for i in range(min(spec.data_disks, 12)))
        return (f"# en cada nodo: espejos (RAID10) con los discos de datos\nzpool create -o ashift=12 tank mirror {disks}\n"
                "pvesm add zfspool local-tank --pool tank --content images,rootdir --sparse 1\n\n"
                "# replicación por VM hacia otro nodo (cada 15 min)\npvesr create-local-job <VMID>-0 <NODO-DESTINO> --schedule '*/15'")

    @staticmethod
    def _migration_cmds(plan):
        st = {"ceph": "vm-pool", "zfs": "local-tank", "san": "san-vm", "nfs": "nas-vm"}[plan.storage_type]
        if plan.method["id"] == "pbs":
            return ("# en el clúster de ORIGEN (PBS nuevo añadido como almacenamiento «pbs-new»)\n"
                    "vzdump <VMID> --storage pbs-new --mode snapshot           # días antes (copia inicial)\n"
                    "qm shutdown <VMID> && vzdump <VMID> --storage pbs-new --mode stop   # ventana: copia final\n\n"
                    "# en el clúster de DESTINO\n"
                    f"qmrestore pbs01:backup/vm/<VMID>/<FECHA> <VMID> --storage {st} --live-restore 1\n"
                    f"pct restore <VMID> pbs01:backup/ct/<VMID>/<FECHA> --storage {st}     # contenedores\n"
                    "qm set <VMID> --net0 virtio=<MAC>,bridge=vlan<VLAN>                 # si cambia bridge/VLAN")
        return ("# token en DESTINO con permisos de migración; huella del certificado del destino\n"
                f"qm remote-migrate <VMID> <VMID> 'host=<IP-DESTINO>,apitoken=PVEAPIToken=<ID>=<SECRETO>,fingerprint=<HUELLA>' "
                f"--target-bridge vmbr1 --target-storage {st} --online\n"
                f"pct remote-migrate <VMID> <VMID> '<mismo endpoint>' --target-bridge vmbr1 --target-storage {st} --restart")


def to_impl_docx(plan, path, charts_dir=None):
    return ImplDoc(plan).build(path, charts_dir)

