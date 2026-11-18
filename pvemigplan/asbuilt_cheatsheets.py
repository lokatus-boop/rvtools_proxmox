"""Apartados finales del as-built: guía rápida (cheatsheet) de GUI y comandos, y contacto con soporte.

Los ejemplos usan los nombres reales del inventario (clúster, nodos, almacenamientos y una VM) cuando existen,
para que Postventa pueda copiarlos casi tal cual. No dependen de python-docx: solo construyen texto y filas.
"""
from __future__ import annotations

from .loader import num

SUPPORT_CONTACT = [
    ("Email de contacto", "cac.serv@fujitsu.com"),
    ("Teléfonos de contacto", "914 521 035 / 914 521 036"),
    ("Web de soporte (descargas)", "https://support.ts.fujitsu.com/download"),
    ("MySupport (portal de clientes)", "https://support.ts.fujitsu.com/login"),
]

SUPPORT_CHECKLIST = [
    "Nombre del cliente y del clúster, y número de serie del servidor afectado (etiqueta del PRIMERGY o iRMC).",
    "Descripción del problema, hora en que empezó y qué cambios se hicieron antes.",
    "Salida de «pveversion -v» y de «pvecm status» del nodo afectado.",
    "Informe del sistema: GUI → nodo → Subscription → System Report (o «pvereport > /tmp/pvereport.txt»).",
    "Registros: «journalctl -b -p warning > /tmp/journal.txt» y, si es hardware, el log de eventos del iRMC.",
]


class Ctx:
    """Nombres reales del inventario para los ejemplos (o marcadores <...> si no hay datos)."""

    def __init__(self, sheets):
        hosts = sheets.get("vHost", [])
        clusters = [r for r in sheets.get("vCluster", []) if r.get("Tipo") == "Clúster"]
        self.cluster = str(clusters[0].get("Clúster / nodo")) if clusters else "<clúster>"
        cl_hosts = [r for r in hosts if not clusters or r.get("Clúster") == self.cluster] or hosts
        names = [str(r.get("Nodo")) for r in cl_hosts if r.get("Nodo")]
        self.n_nodes = len(names)
        self.node1 = names[0] if names else "<nodo1>"
        self.node2 = names[1] if len(names) > 1 else "<nodo2>"
        self.ip2 = next((str(r.get("IP")) for r in cl_hosts[1:2] if r.get("IP")), "<IP-nodo2>")
        st = sheets.get("vDatastore", [])
        self.zfs = next((str(r["Almacenamiento"]) for r in st if r.get("Tipo") == "zfspool"), None)
        self.rbd = next((str(r["Almacenamiento"]) for r in st if r.get("Tipo") == "rbd"), None)
        self.pbs = next((str(r["Almacenamiento"]) for r in st if r.get("Tipo") == "pbs"), None)
        pools = sheets.get("vCephPool", [])
        self.ceph_pool = str(pools[0].get("Pool")) if pools else (self.rbd or "<pool>")
        zp = sheets.get("vZFS", [])
        self.zpool = str(zp[0].get("Pool")) if zp else "rpool"
        vms = [r for r in sheets.get("vInfo", []) if r.get("Tipo") == "VM" and str(r.get("Plantilla")).lower() not in ("sí", "si", "true", "1")]
        self.vmid = str(vms[0].get("VMID")) if vms else "100"
        self.store = self.zfs or self.rbd or "<almacenamiento>"
        self.backup_store = self.pbs or "<almacén-backup>"
        self.has_ceph = bool(self.rbd or pools)
        self.qdevice_useful = self.n_nodes == 2 or (self.n_nodes and self.n_nodes % 2 == 0)


def _table(doc, rows, size=7.5):
    doc.table(["Tarea", "GUI", "Comando (shell del nodo, como root)"], rows, size=size)


def add_cheatsheets(doc, sheets, n):
    """Añade el apartado «n. Guía rápida (cheatsheet)» con sus cinco subapartados."""
    c = Ctx(sheets)
    vm, n1, n2 = c.vmid, c.node1, c.node2
    doc.h(f"{n}. Guía rápida (cheatsheet): GUI y comandos")
    doc.p("Resumen práctico para las tareas habituales de Postventa. Las rutas de la GUI usan los nombres en inglés de la "
          "interfaz web (https://<IP-nodo>:8006). Los comandos se ejecutan como root en la shell de un nodo "
          "(GUI → nodo → Shell, o SSH). Los ejemplos usan los nombres de esta plataforma "
          f"(clúster «{c.cluster}», nodos «{n1}» y «{n2}», VM {vm}); sustituir los valores entre <...>.", size=9.5)

    # ---------------------------------------------------------------- QDevice
    doc.h(f"{n}.1 QDevice (voto externo de quórum)", 2)
    estado = (f"La plataforma tiene {c.n_nodes} nodo(s) en el clúster: "
              + ("con un número par de nodos se recomienda un QDevice para no perder el quórum si cae la mitad de los nodos."
                 if c.qdevice_useful else
                 "con un número impar de nodos no se recomienda QDevice (Proxmox lo desaconseja y obliga a usar --force)."))
    doc.p("El QDevice es un servicio (corosync-qnetd) en un equipo externo al clúster, normalmente una VM o un equipo Debian "
          "pequeño en otra ubicación o en otro host, que aporta un voto adicional. " + estado, size=9.5)
    doc.p("No tiene asistente en la GUI: se configura por comandos. El resultado se ve en GUI → Datacenter → Cluster y "
          "en Datacenter → Summary (quórum).", size=9.5)
    doc.h("Añadir un QDevice", 3)
    doc.code("# 1) En el equipo externo (Debian), accesible por SSH como root y con el puerto TCP 5403 abierto\n"
             "apt update && apt install corosync-qnetd\n\n"
             "# 2) En TODOS los nodos del clúster\n"
             "apt update && apt install corosync-qdevice\n\n"
             "# 3) Desde UN nodo del clúster (pide la contraseña de root del equipo externo)\n"
             f"pvecm qdevice setup <IP-QDEVICE>\n\n"
             "# 4) Comprobar: debe aparecer «Qdevice» en Membership information y Flags: Quorate Qdevice\n"
             "pvecm status\n"
             "corosync-qdevice-tool -sv          # en un nodo\n"
             "corosync-qnetd-tool -l             # en el equipo externo")
    doc.h("Quitar un QDevice", 3)
    doc.code("# Desde un nodo del clúster\n"
             "pvecm qdevice remove\n"
             "pvecm status                       # ya no debe aparecer el Qdevice\n\n"
             "# Opcional: desinstalar los paquetes\n"
             "apt purge corosync-qdevice         # en cada nodo\n"
             "apt purge corosync-qnetd           # en el equipo externo")
    doc.bullets([
        "Antes de añadir o quitar nodos del clúster hay que quitar el QDevice y volver a configurarlo después.",
        "Para sustituir el equipo del QDevice: «pvecm qdevice remove» y luego «pvecm qdevice setup <IP-nueva>».",
        "Si el QDevice deja de responder, el clúster sigue funcionando mientras tenga mayoría de nodos; revisarlo cuanto antes.",
    ])

    # ---------------------------------------------------------------- Réplicas
    doc.h(f"{n}.2 Réplicas de almacenamiento (pvesr)", 2)
    doc.p("La replicación copia periódicamente los discos de una VM o CT de un almacenamiento ZFS local a otro nodo, con "
          "envíos incrementales de snapshots ZFS. Permite migraciones muy rápidas y arrancar la VM en el otro nodo si cae "
          "el suyo, perdiendo como máximo los datos desde la última sincronización (RPO = intervalo de la réplica).", size=9.5)
    if c.zfs:
        doc.p(f"Requisito: los discos deben estar en un almacenamiento ZFS local con el mismo nombre en origen y destino "
              f"(en esta plataforma: «{c.zfs}»).", size=9.5)
    else:
        doc.p("Requisito: los discos deben estar en un almacenamiento ZFS local con el mismo nombre en origen y destino. "
              "En el inventario no hay almacenamiento ZFS local, por lo que hoy no se puede usar.", size=9.5, bold=True)
    if c.has_ceph:
        doc.p("Con Ceph (almacenamiento compartido) la replicación no hace falta: HA arranca la VM en otro nodo sin pérdida de datos.",
              size=9.5, italic=True)
    reps = sheets.get("vReplication", [])
    if reps:
        doc.p(f"Trabajos de replicación configurados en el momento del inventario: {len(reps)} (ver apartado 5).", size=9.5)
    doc.h("Añadir, consultar y gestionar", 3)
    _table(doc, [
        ["Crear réplica", f"VM {vm} → Replication → Add: Target = {n2}, Schedule (*/15 por defecto), Rate limit",
         f"pvesr create-local-job {vm}-0 {n2} --schedule '*/15' --rate 100"],
        ["Ver todas las réplicas", "Datacenter → Replication (o nodo → Replication)", "pvesr list\npvesr status"],
        ["Lanzar ahora", "VM → Replication → seleccionar → Schedule now", f"pvesr schedule-now {vm}-0"],
        ["Cambiar planificación", "VM → Replication → Edit", f"pvesr update {vm}-0 --schedule '*/5'"],
        ["Pausar / reanudar", "VM → Replication → Edit → Enabled", f"pvesr disable {vm}-0\npvesr enable {vm}-0"],
        ["Borrar réplica", "VM → Replication → Remove", f"pvesr delete {vm}-0              # borra también la copia del destino\n"
                                                         f"pvesr delete {vm}-0 --keep 1     # conserva la copia del destino"],
        ["Ver el log", "Replication → seleccionar → Log", f"pvesr status --guest {vm}\njournalctl -u pvescheduler"],
    ])
    doc.p("Formatos de planificación: «*/15» (cada 15 min), «*/5», «hourly», «22:30», «mon..fri 8..18/30». El identificador "
          "del trabajo es <VMID>-<nº> (100-0, 100-1…). Una VM puede replicarse a varios nodos (un trabajo por destino).", size=9)
    doc.h("Funcionamiento en caso de desastre (caída de un nodo)", 3)
    doc.bullets([
        "Con HA: la VM debe estar en HA y sus nodos permitidos (grupo HA en PVE 8, regla de afinidad de nodo en PVE 9) deben "
        "ser los que tienen réplica. Tras el aislamiento (fencing, unos 2-3 minutos) HA la arranca sola en el nodo con réplica.",
        "Sin HA: hay que mover la configuración a mano al nodo con réplica (el clúster debe tener quórum) y arrancarla:",
    ])
    doc.code(f"# En {n2} (nodo con la réplica), con {n1} caído y apagado de verdad\n"
             f"mv /etc/pve/nodes/{n1}/qemu-server/{vm}.conf /etc/pve/nodes/{n2}/qemu-server/{vm}.conf\n"
             f"qm start {vm}\n"
             "# Para un contenedor: /etc/pve/nodes/<nodo>/lxc/<CTID>.conf y «pct start <CTID>»")
    doc.p("Importante: no arrancar la VM en el nodo de réplica si el nodo original sigue encendido (riesgo de dos copias activas). "
          "Se pierden los cambios hechos desde la última réplica correcta (ver «pvesr status»).", size=9, bold=True)
    doc.h("Revertir (volver al nodo original)", 3)
    doc.numbered([
        f"Recuperar {n1} y comprobar que vuelve al clúster con «pvecm status». La VM ya no está en su configuración, así que no arranca allí.",
        f"Revisar Datacenter → Replication: el trabajo de la VM apunta ahora al nodo donde corre ({n2}) y dará error. Borrarlo "
        f"(«pvesr delete {vm}-0 --force 1») para crear uno nuevo hacia {n1}.",
        f"En {n1} quedan los discos antiguos de la VM. Comprobar que son los antiguos y borrarlos: «zfs list | grep vm-{vm}-» y "
        f"«zfs destroy -r {c.zpool}/data/vm-{vm}-disk-0» (ajustar el nombre del dataset).",
        f"Crear la réplica de {n2} a {n1} («pvesr create-local-job {vm}-0 {n1} --schedule '*/15'») y esperar a la primera sincronización completa.",
        f"Migrar la VM de vuelta en caliente: «qm migrate {vm} {n1} --online» (o GUI → Migrate). Como hay réplica, solo se copia "
        "lo cambiado y el trabajo de replicación invierte su sentido automáticamente.",
        "Con HA: si el grupo/regla tiene prioridad por nodo, HA la devuelve sola al nodo preferido salvo que la vuelta automática esté desactivada (nofailback en PVE 8, failback=0 en PVE 9).",
    ])

    # ---------------------------------------------------------------- Gestión
    doc.h(f"{n}.3 Comandos de gestión", 2)
    doc.h("Clúster y alta disponibilidad", 3)
    _table(doc, [
        ["Estado del clúster y quórum", "Datacenter → Summary / Cluster", "pvecm status\npvecm nodes"],
        ["Estado de HA", "Datacenter → HA", "ha-manager status"],
        ["Poner una VM en HA", "Datacenter → HA → Resources → Add", f"ha-manager add vm:{vm} --state started"],
        ["Quitar una VM de HA", "Datacenter → HA → Resources → Remove", f"ha-manager remove vm:{vm}"],
        ["Mantenimiento de un nodo (vacía sus VMs HA)", "—",
         f"ha-manager crm-command node-maintenance enable {n1}\nha-manager crm-command node-maintenance disable {n1}"],
        ["Recursos del clúster", "Datacenter → Search", "pvesh get /cluster/resources --type vm"],
        ["Quórum de emergencia (solo con la mayoría de nodos caídos y sabiendo lo que se hace)", "—", "pvecm expected 1"],
    ])
    doc.h("Nodos", 3)
    _table(doc, [
        ["Versiones", "nodo → Summary", "pveversion -v"],
        ["Actualizar", "nodo → Updates → Refresh / Upgrade", "apt update && apt full-upgrade"],
        ["Suscripción", "nodo → Subscription", "pvesubscription get"],
        ["Servicios de Proxmox", "nodo → System", "systemctl status pve-cluster pvedaemon pveproxy pvestatd corosync"],
        ["Reiniciar la GUI web", "nodo → System → pveproxy → Restart", "systemctl restart pveproxy"],
        ["Tareas y registros", "nodo → Task History / Syslog", "pvenode task list\njournalctl -b -p warning"],
        ["Certificados", "nodo → System → Certificates", "pvenode cert info"],
        ["Red (aplicar cambios)", "nodo → System → Network → Apply Configuration", "ifreload -a\nip -br a\ncat /proc/net/bonding/bond0"],
    ])
    doc.h("Máquinas virtuales y contenedores", 3)
    _table(doc, [
        ["Listar", "Datacenter → Search", "qm list\npct list"],
        ["Arrancar / apagar / parar", "VM → Start / Shutdown / Stop", f"qm start {vm}\nqm shutdown {vm}\nqm stop {vm}"],
        ["Ver configuración", "VM → Hardware / Options", f"qm config {vm}"],
        ["Migrar en caliente", "VM → Migrate", f"qm migrate {vm} {n2} --online\npct migrate <CTID> {n2} --restart"],
        ["Desbloquear (tras una tarea fallida)", "—", f"qm unlock {vm}"],
        ["Ampliar un disco", "VM → Hardware → Disk Action → Resize", f"qm disk resize {vm} scsi0 +20G"],
        ["Mover un disco de almacenamiento", "VM → Hardware → Disk Action → Move Storage",
         f"qm disk move {vm} scsi0 {c.store} --delete 1"],
        ["Cambiar memoria / vCPU", "VM → Hardware → Edit", f"qm set {vm} --memory 8192 --cores 4"],
        ["Consola / entrar en un CT", "VM → Console", "qm terminal <VMID>   (requiere puerto serie)\npct enter <CTID>"],
    ])
    doc.h("Almacenamiento y copias de seguridad", 3)
    rows = [
        ["Estado de los almacenamientos", "Datacenter → Storage / nodo → Disks", "pvesm status"],
        ["Contenido de un almacenamiento", "almacenamiento → VM Disks / Backups", f"pvesm list {c.backup_store}"],
        ["ZFS", "nodo → Disks → ZFS", "zpool status -x\nzpool list\nzfs list"],
    ]
    if c.has_ceph:
        rows.append(["Ceph", "nodo → Ceph", "ceph -s\nceph health detail\nceph osd tree\nceph df"])
    rows += [
        ["Backup manual", "VM → Backup → Backup now", f"vzdump {vm} --storage {c.backup_store} --mode snapshot"],
        ["Restaurar a una VM nueva", "almacenamiento de backup → seleccionar copia → Restore",
         f"qmrestore <volid-copia> <VMID-nuevo> --storage {c.store}"],
        ["Ver jobs de backup", "Datacenter → Backup", "pvesh get /cluster/backup"],
    ]
    _table(doc, rows)

    # ---------------------------------------------------------------- Pruebas
    doc.h(f"{n}.4 Comandos de pruebas", 2)
    doc.p("Pruebas para validar la plataforma tras la implantación o tras un cambio. Las de rendimiento se lanzan fuera de "
          "horario de producción.", size=9.5)
    rows = [
        ["Clúster y quórum", f"pvecm status\ncorosync-quorumtool -s", "Quorate: Yes y todos los nodos presentes"],
        ["Enlaces de corosync", "corosync-cfgtool -s", "Todos los enlaces «connected» en cada nodo"],
        ["Conectividad y MTU (jumbo 9000)", f"ping -c 5 {c.ip2}\nping -M do -s 8972 -c 5 <IP-red-almacenamiento>",
         "Sin pérdidas; si falla el de 8972 la MTU no es 9000 en todo el camino"],
        ["Ancho de banda entre nodos", f"apt install iperf3\niperf3 -s                      # en {n2}\niperf3 -c <IP-{n2}> -P 4 -t 30   # en {n1}",
         "Cercano a la velocidad del enlace (p. ej. > 9 Gbit/s en 10 GbE)"],
        ["Bonds y enlaces", "cat /proc/net/bonding/bond0\nethtool <interfaz>", "Todos los esclavos «up» y a la velocidad prevista"],
        ["Disco local (rendimiento básico)", "pveperf /var/lib/vz", "FSYNCS/SECOND alto (> 1000 con SSD)"],
        ["Rendimiento de E/S (en una VM o ruta de prueba)",
         "fio --name=prueba --filename=/root/fio.test --size=4G --rw=randrw --bs=4k --iodepth=32 \\\n"
         "    --ioengine=libaio --direct=1 --runtime=60 --time_based --group_reporting\nrm /root/fio.test",
         "IOPS y latencia acordes al diseño; nunca apuntar fio a un disco en uso"],
        ["Salud de discos", "smartctl -a /dev/<disco>\nzpool scrub " + c.zpool + " ; zpool status", "SMART PASSED, sin errores"],
    ]
    if c.has_ceph:
        rows.append(["Rendimiento de Ceph (pool de pruebas)",
                     f"rados bench -p {c.ceph_pool} 30 write --no-cleanup\nrados bench -p {c.ceph_pool} 30 seq\n"
                     f"rados -p {c.ceph_pool} cleanup\nceph osd perf",
                     "HEALTH_OK antes y después; latencias de OSD homogéneas"])
    rows += [
        ["Migración en caliente", f"qm migrate {vm} {n2} --online", "Sin cortes en la VM (ping continuo)"],
        ["Réplica", f"pvesr schedule-now {vm}-0 ; pvesr status", "Estado OK y duración razonable"],
        ["Backup y restauración", f"vzdump {vm} --storage {c.backup_store}\nqmrestore <volid> <VMID-prueba> --storage {c.store}",
         "La copia restaurada arranca; borrar la VM de prueba después"],
        ["HA (prueba de caída)", f"ha-manager status\n# apagar {n2} desde el iRMC (corte en frío)",
         "Las VMs HA arrancan en otro nodo en 2-3 min"],
    ]
    doc.table(["Prueba", "Comando", "Resultado esperado"], rows, size=7.5)

    # ---------------------------------------------------------------- Snapshots
    doc.h(f"{n}.5 Snapshots (configuración y réplicas)", 2)
    doc.p("Una snapshot guarda el estado de los discos (y opcionalmente de la RAM) de una VM o CT para poder volver atrás, "
          "por ejemplo antes de una actualización. No es una copia de seguridad: está en el mismo almacenamiento que la VM. "
          "Funciona en ZFS, Ceph RBD, LVM-thin y discos qcow2 (directorio, NFS, CIFS); en LVM normal (no thin) no "
          "está disponible salvo la vista previa técnica de PVE 9.", size=9.5)
    _table(doc, [
        ["Crear", "VM → Snapshots → Take Snapshot (Name, Include RAM, Description)",
         f"qm snapshot {vm} antes_update --description 'Antes de actualizar' --vmstate 1\npct snapshot <CTID> antes_update"],
        ["Listar", "VM → Snapshots", f"qm listsnapshot {vm}\npct listsnapshot <CTID>"],
        ["Volver a una snapshot", "VM → Snapshots → Rollback", f"qm rollback {vm} antes_update\npct rollback <CTID> antes_update"],
        ["Borrar", "VM → Snapshots → Remove", f"qm delsnapshot {vm} antes_update\npct delsnapshot <CTID> antes_update"],
        ["Ver espacio que ocupan", "—",
         f"zfs list -t snapshot -o name,used,creation | grep vm-{vm}-" + (f"\nrbd snap ls {c.ceph_pool}/vm-{vm}-disk-0" if c.has_ceph else "")],
    ])
    doc.bullets([
        "Incluir RAM («Include RAM» / --vmstate 1) permite volver con la VM encendida tal como estaba; sin RAM la VM vuelve apagada. "
        "Para que los datos sean coherentes sin RAM, instalar el QEMU Guest Agent en la VM.",
        "En ZFS solo se puede volver a la snapshot más reciente: para volver a una anterior hay que borrar antes las posteriores.",
        "Las snapshots crecen con los cambios: no mantenerlas más de unos días y borrarlas tras validar el cambio.",
        "Proxmox no tiene snapshots programadas en la GUI. Para tenerlas hay que usar cron con «qm snapshot» y un borrado de las "
        "antiguas, o herramientas de terceros (no soportadas por Proxmox). Para protección diaria se usan los jobs de backup.",
    ])
    doc.h("Snapshots y réplicas", 3)
    doc.bullets([
        "La replicación (apartado anterior) se basa en snapshots ZFS con nombre «__replicate_<trabajo>_<fecha>__». No borrarlas a mano: "
        "si se borran, la siguiente réplica tiene que copiar el disco completo o falla.",
        "Si una réplica falla porque el destino tiene datos que no coinciden, borrar el trabajo, borrar los discos del destino y volver a crearlo.",
        "Réplica de copias fuera de la plataforma: en Proxmox Backup Server, Datastore → Sync Jobs (o Remotes) copia los backups "
        "a un segundo PBS, por ejemplo en otra ubicación.",
    ])
    doc.code(f"# Snapshots de réplica de la VM {vm} (en el nodo origen o destino)\n"
             f"zfs list -t snapshot | grep vm-{vm}- | grep __replicate_\n"
             f"pvesr status --guest {vm}")
    snaps = sheets.get("vSnapshot", [])
    if snaps:
        doc.h("Snapshots existentes en el momento del inventario", 3)
        old = [r for r in snaps if (num(r.get("Antigüedad (días)"), 0) or 0) > 7]
        doc.p(f"{len(snaps)} snapshot(s); {len(old)} con más de 7 días.", size=9.5, bold=bool(old))
        doc.table(["Clúster", "Nodo", "VMID", "Nombre", "Snapshot", "Fecha", "Días", "RAM"],
                  [[r.get("Clúster"), r.get("Nodo"), r.get("VMID"), r.get("Nombre"), r.get("Snapshot"), r.get("Fecha"),
                    r.get("Antigüedad (días)"), r.get("Con RAM")] for r in snaps[:60]], size=7.5)


def add_contact(doc, n, author=""):
    """Añade el apartado «n. Contacto y soporte»."""
    doc.h(f"{n}. Contacto y soporte")
    doc.p("Para abrir una incidencia o hacer una consulta sobre la plataforma, contactar con el soporte de Fsas Technologies:", size=9.5)
    doc.kv(SUPPORT_CONTACT)
    doc.h("Datos a tener preparados al abrir una incidencia", 3)
    doc.checklist(SUPPORT_CHECKLIST)
    doc.h("Contactos del proyecto", 3)
    doc.kv([("Cliente: responsable técnico", "________"),
            ("Fsas Technologies: proyecto / preventa", author or "________")])
