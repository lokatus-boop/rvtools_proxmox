"""Apartados finales del as-built: guía rápida (cheatsheet) de GUI y comandos, y contacto con soporte.

Los ejemplos usan los nombres reales del inventario (clúster, nodos, almacenamientos y una VM) cuando existen,
para que Postventa pueda copiarlos casi tal cual. No dependen de python-docx: solo construyen texto y filas.
"""
from __future__ import annotations

from pvetools.i18n import N_, _

from .loader import num

SUPPORT_CONTACT = [
    (N_("Email de contacto"), "cac.serv@fujitsu.com"),
    (N_("Teléfonos de contacto"), "914 521 035 / 914 521 036"),
    (N_("Web de soporte (descargas)"), "https://support.ts.fujitsu.com/download"),
    (N_("MySupport (portal de clientes)"), "https://support.ts.fujitsu.com/login"),
]

SUPPORT_CHECKLIST = [
    N_("Nombre del cliente y del clúster, y número de serie del servidor afectado (etiqueta del PRIMERGY o iRMC)."),
    N_("Descripción del problema, hora en que empezó y qué cambios se hicieron antes."),
    N_("Salida de «pveversion -v» y de «pvecm status» del nodo afectado."),
    N_("Informe del sistema: GUI → nodo → Subscription → System Report (o «pvereport > /tmp/pvereport.txt»)."),
    N_("Registros: «journalctl -b -p warning > /tmp/journal.txt» y, si es hardware, el log de eventos del iRMC."),
]


class Ctx:
    """Nombres reales del inventario para los ejemplos (o marcadores <...> si no hay datos)."""

    def __init__(self, sheets):
        hosts = sheets.get("vHost", [])
        clusters = [r for r in sheets.get("vCluster", []) if r.get("Tipo") == "Clúster"]
        self.cluster = str(clusters[0].get("Clúster / nodo")) if clusters else _("<clúster>")
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
        self.backup_store = self.pbs or _("<almacén-backup>")
        self.has_ceph = bool(self.rbd or pools)
        self.qdevice_useful = self.n_nodes == 2 or (self.n_nodes and self.n_nodes % 2 == 0)


def _table(doc, rows, size=7.5):
    doc.table([_("Tarea"), "GUI", _("Comando (shell del nodo, como root)")], rows, size=size)


def add_cheatsheets(doc, sheets, n):
    """Añade el apartado «n. Guía rápida (cheatsheet)» con sus cinco subapartados."""
    c = Ctx(sheets)
    vm, n1, n2 = c.vmid, c.node1, c.node2
    doc.h(_("{n}. Guía rápida (cheatsheet): GUI y comandos", n=n))
    doc.p(_("Resumen práctico para las tareas habituales de Postventa. Las rutas de la GUI usan los nombres en inglés de la interfaz web (https://<IP-nodo>:8006). Los comandos se ejecutan como root en la shell de un nodo (GUI → nodo → Shell, o SSH). Los ejemplos usan los nombres de esta plataforma (clúster «{cluster}», nodos «{n1}» y «{n2}», VM {vm}); sustituir los valores entre <...>.", cluster=c.cluster, n1=n1, n2=n2, vm=vm), size=9.5)

    # ---------------------------------------------------------------- QDevice
    doc.h(_("{n}.1 QDevice (voto externo de quórum)", n=n), 2)
    estado = (_("La plataforma tiene {n_nodes} nodo(s) en el clúster: ", n_nodes=c.n_nodes)
              + (_("con un número par de nodos se recomienda un QDevice para no perder el quórum si cae la mitad de los nodos.")
                 if c.qdevice_useful else
                 _("con un número impar de nodos no se recomienda QDevice (Proxmox lo desaconseja y obliga a usar --force).")))
    doc.p(_("El QDevice es un servicio (corosync-qnetd) en un equipo externo al clúster, normalmente una VM o un equipo Debian "
          "pequeño en otra ubicación o en otro host, que aporta un voto adicional. ") + estado, size=9.5)
    doc.p(_("No tiene asistente en la GUI: se configura por comandos. El resultado se ve en GUI → Datacenter → Cluster y "
          "en Datacenter → Summary (quórum)."), size=9.5)
    doc.h(_("Añadir un QDevice"), 3)
    doc.code(_("# 1) En el equipo externo (Debian), accesible por SSH como root y con el puerto TCP 5403 abierto\napt update && apt install corosync-qnetd\n\n# 2) En TODOS los nodos del clúster\napt update && apt install corosync-qdevice\n\n# 3) Desde UN nodo del clúster (pide la contraseña de root del equipo externo)\npvecm qdevice setup <IP-QDEVICE>\n\n# 4) Comprobar: debe aparecer «Qdevice» en Membership information y Flags: Quorate Qdevice\npvecm status\ncorosync-qdevice-tool -sv          # en un nodo\ncorosync-qnetd-tool -l             # en el equipo externo", ))
    doc.h(_("Quitar un QDevice"), 3)
    doc.code(_("# Desde un nodo del clúster\n"
             "pvecm qdevice remove\n"
             "pvecm status                       # ya no debe aparecer el Qdevice\n\n"
             "# Opcional: desinstalar los paquetes\n"
             "apt purge corosync-qdevice         # en cada nodo\n"
             "apt purge corosync-qnetd           # en el equipo externo"))
    doc.bullets([
        _("Antes de añadir o quitar nodos del clúster hay que quitar el QDevice y volver a configurarlo después."),
        _("Para sustituir el equipo del QDevice: «pvecm qdevice remove» y luego «pvecm qdevice setup <IP-nueva>»."),
        _("Si el QDevice deja de responder, el clúster sigue funcionando mientras tenga mayoría de nodos; revisarlo cuanto antes."),
    ])

    # ---------------------------------------------------------------- Réplicas
    doc.h(_("{n}.2 Réplicas de almacenamiento (pvesr)", n=n), 2)
    doc.p(_("La replicación copia periódicamente los discos de una VM o CT de un almacenamiento ZFS local a otro nodo, con "
          "envíos incrementales de snapshots ZFS. Permite migraciones muy rápidas y arrancar la VM en el otro nodo si cae "
          "el suyo, perdiendo como máximo los datos desde la última sincronización (RPO = intervalo de la réplica)."), size=9.5)
    if c.zfs:
        doc.p(_("Requisito: los discos deben estar en un almacenamiento ZFS local con el mismo nombre en origen y destino (en esta plataforma: «{zfs}»).", zfs=c.zfs), size=9.5)
    else:
        doc.p(_("Requisito: los discos deben estar en un almacenamiento ZFS local con el mismo nombre en origen y destino. "
              "En el inventario no hay almacenamiento ZFS local, por lo que hoy no se puede usar."), size=9.5, bold=True)
    if c.has_ceph:
        doc.p(_("Con Ceph (almacenamiento compartido) la replicación no hace falta: HA arranca la VM en otro nodo sin pérdida de datos."),
              size=9.5, italic=True)
    reps = sheets.get("vReplication", [])
    if reps:
        doc.p(_("Trabajos de replicación configurados en el momento del inventario: {n_reps} (ver apartado 5).", n_reps=len(reps)), size=9.5)
    doc.h(_("Añadir, consultar y gestionar"), 3)
    _table(doc, [
        [_("Crear réplica"), _("VM {vm} → Replication → Add: Target = {n2}, Schedule (*/15 por defecto), Rate limit", vm=vm, n2=n2),
         _("pvesr create-local-job {vm}-0 {n2} --schedule '*/15' --rate 100", vm=vm, n2=n2)],
        [_("Ver todas las réplicas"), _("Datacenter → Replication (o nodo → Replication)"), _("pvesr list\npvesr status")],
        [_("Lanzar ahora"), _("VM → Replication → seleccionar → Schedule now"), _("pvesr schedule-now {vm}-0", vm=vm)],
        [_("Cambiar planificación"), _("VM → Replication → Edit"), _("pvesr update {vm}-0 --schedule '*/5'", vm=vm)],
        [_("Pausar / reanudar"), _("VM → Replication → Edit → Enabled"), _("pvesr disable {vm}-0\npvesr enable {vm}-0", vm=vm)],
        [_("Borrar réplica"), _("VM → Replication → Remove"), _("pvesr delete {vm}-0              # borra también la copia del destino\npvesr delete {vm}-0 --keep 1     # conserva la copia del destino", vm=vm)],
        [_("Ver el log"), _("Replication → seleccionar → Log"), _("pvesr status --guest {vm}\njournalctl -u pvescheduler", vm=vm)],
    ])
    doc.p(_("Formatos de planificación: «*/15» (cada 15 min), «*/5», «hourly», «22:30», «mon..fri 8..18/30». El identificador "
          "del trabajo es <VMID>-<nº> (100-0, 100-1…). Una VM puede replicarse a varios nodos (un trabajo por destino)."), size=9)
    doc.h(_("Funcionamiento en caso de desastre (caída de un nodo)"), 3)
    doc.bullets([
        _("Con HA: la VM debe estar en HA y sus nodos permitidos (grupo HA en PVE 8, regla de afinidad de nodo en PVE 9) deben "
        "ser los que tienen réplica. Tras el aislamiento (fencing, unos 2-3 minutos) HA la arranca sola en el nodo con réplica."),
        _("Sin HA: hay que mover la configuración a mano al nodo con réplica (el clúster debe tener quórum) y arrancarla:"),
    ])
    doc.code(_("# En {n2} (nodo con la réplica), con {n1} caído y apagado de verdad\nmv /etc/pve/nodes/{n1}/qemu-server/{vm}.conf /etc/pve/nodes/{n2}/qemu-server/{vm}.conf\nqm start {vm}\n# Para un contenedor: /etc/pve/nodes/<nodo>/lxc/<CTID>.conf y «pct start <CTID>»", n2=n2, n1=n1, vm=vm))
    doc.p(_("Importante: no arrancar la VM en el nodo de réplica si el nodo original sigue encendido (riesgo de dos copias activas). "
          "Se pierden los cambios hechos desde la última réplica correcta (ver «pvesr status»)."), size=9, bold=True)
    doc.h(_("Revertir (volver al nodo original)"), 3)
    doc.numbered([
        _("Recuperar {n1} y comprobar que vuelve al clúster con «pvecm status». La VM ya no está en su configuración, así que no arranca allí.", n1=n1),
        _("Revisar Datacenter → Replication: el trabajo de la VM apunta ahora al nodo donde corre ({n2}) y dará error. Borrarlo («pvesr delete {vm}-0 --force 1») para crear uno nuevo hacia {n1}.", n2=n2, vm=vm, n1=n1),
        _("En {n1} quedan los discos antiguos de la VM. Comprobar que son los antiguos y borrarlos: «zfs list | grep vm-{vm}-» y «zfs destroy -r {zpool}/data/vm-{vm}-disk-0» (ajustar el nombre del dataset).", n1=n1, vm=vm, zpool=c.zpool),
        _("Crear la réplica de {n2} a {n1} («pvesr create-local-job {vm}-0 {n1} --schedule '*/15'») y esperar a la primera sincronización completa.", n2=n2, n1=n1, vm=vm),
        _("Migrar la VM de vuelta en caliente: «qm migrate {vm} {n1} --online» (o GUI → Migrate). Como hay réplica, solo se copia lo cambiado y el trabajo de replicación invierte su sentido automáticamente.", vm=vm, n1=n1),
        _("Con HA: si el grupo/regla tiene prioridad por nodo, HA la devuelve sola al nodo preferido salvo que la vuelta automática esté desactivada (nofailback en PVE 8, failback=0 en PVE 9)."),
    ])

    # ---------------------------------------------------------------- Gestión
    doc.h(_("{n}.3 Comandos de gestión", n=n), 2)
    doc.h(_("Clúster y alta disponibilidad"), 3)
    _table(doc, [
        [_("Estado del clúster y quórum"), _("Datacenter → Summary / Cluster"), _("pvecm status\npvecm nodes")],
        [_("Estado de HA"), _("Datacenter → HA"), _("ha-manager status")],
        [_("Poner una VM en HA"), _("Datacenter → HA → Resources → Add"), _("ha-manager add vm:{vm} --state started", vm=vm)],
        [_("Quitar una VM de HA"), _("Datacenter → HA → Resources → Remove"), _("ha-manager remove vm:{vm}", vm=vm)],
        [_("Mantenimiento de un nodo (vacía sus VMs HA)"), "—",
         _("ha-manager crm-command node-maintenance enable {n1}\nha-manager crm-command node-maintenance disable {n1}", n1=n1)],
        [_("Recursos del clúster"), _("Datacenter → Search"), _("pvesh get /cluster/resources --type vm")],
        [_("Quórum de emergencia (solo con la mayoría de nodos caídos y sabiendo lo que se hace)"), "—", _("pvecm expected 1")],
    ])
    doc.h("Nodos", 3)
    _table(doc, [
        [_("Versiones"), _("nodo → Summary"), _("pveversion -v")],
        [_("Actualizar"), _("nodo → Updates → Refresh / Upgrade"), _("apt update && apt full-upgrade")],
        ["Suscripción", _("nodo → Subscription"), _("pvesubscription get")],
        [_("Servicios de Proxmox"), _("nodo → System"), _("systemctl status pve-cluster pvedaemon pveproxy pvestatd corosync")],
        [_("Reiniciar la GUI web"), _("nodo → System → pveproxy → Restart"), _("systemctl restart pveproxy")],
        [_("Tareas y registros"), _("nodo → Task History / Syslog"), _("pvenode task list\njournalctl -b -p warning")],
        [_("Certificados"), _("nodo → System → Certificates"), _("pvenode cert info")],
        [_("Red (aplicar cambios)"), _("nodo → System → Network → Apply Configuration"), _("ifreload -a\nip -br a\ncat /proc/net/bonding/bond0")],
    ])
    doc.h(_("Máquinas virtuales y contenedores"), 3)
    _table(doc, [
        [_("Listar"), _("Datacenter → Search"), _("qm list\npct list")],
        [_("Arrancar / apagar / parar"), _("VM → Start / Shutdown / Stop"), _("qm start {vm}\nqm shutdown {vm}\nqm stop {vm}", vm=vm)],
        [_("Ver configuración"), _("VM → Hardware / Options"), _("qm config {vm}", vm=vm)],
        [_("Migrar en caliente"), _("VM → Migrate"), _("qm migrate {vm} {n2} --online\npct migrate <CTID> {n2} --restart", vm=vm, n2=n2)],
        [_("Desbloquear (tras una tarea fallida)"), "—", _("qm unlock {vm}", vm=vm)],
        [_("Ampliar un disco"), _("VM → Hardware → Disk Action → Resize"), _("qm disk resize {vm} scsi0 +20G", vm=vm)],
        [_("Mover un disco de almacenamiento"), _("VM → Hardware → Disk Action → Move Storage"),
         _("qm disk move {vm} scsi0 {store} --delete 1", vm=vm, store=c.store)],
        [_("Cambiar memoria / vCPU"), _("VM → Hardware → Edit"), _("qm set {vm} --memory 8192 --cores 4", vm=vm)],
        [_("Consola / entrar en un CT"), _("VM → Console"), _("qm terminal <VMID>   (requiere puerto serie)\npct enter <CTID>")],
    ])
    doc.h(_("Almacenamiento y copias de seguridad"), 3)
    rows = [
        [_("Estado de los almacenamientos"), _("Datacenter → Storage / nodo → Disks"), _("pvesm status")],
        [_("Contenido de un almacenamiento"), _("almacenamiento → VM Disks / Backups"), _("pvesm list {backup_store}", backup_store=c.backup_store)],
        ["ZFS", _("nodo → Disks → ZFS"), _("zpool status -x\nzpool list\nzfs list")],
    ]
    if c.has_ceph:
        rows.append(["Ceph", _("nodo → Ceph"), _("ceph -s\nceph health detail\nceph osd tree\nceph df")])
    rows += [
        [_("Backup manual"), _("VM → Backup → Backup now"), _("vzdump {vm} --storage {backup_store} --mode snapshot", vm=vm, backup_store=c.backup_store)],
        [_("Restaurar a una VM nueva"), _("almacenamiento de backup → seleccionar copia → Restore"),
         _("qmrestore <volid-copia> <VMID-nuevo> --storage {store}", store=c.store)],
        [_("Ver jobs de backup"), _("Datacenter → Backup"), _("pvesh get /cluster/backup")],
    ]
    _table(doc, rows)

    # ---------------------------------------------------------------- Pruebas
    doc.h(_("{n}.4 Comandos de pruebas", n=n), 2)
    doc.p(_("Pruebas para validar la plataforma tras la implantación o tras un cambio. Las de rendimiento se lanzan fuera de "
          "horario de producción."), size=9.5)
    rows = [
        [_("Clúster y quórum"), _("pvecm status\ncorosync-quorumtool -s", ), _("Quorate: Yes y todos los nodos presentes")],
        [_("Enlaces de corosync"), _("corosync-cfgtool -s"), _("Todos los enlaces «connected» en cada nodo")],
        [_("Conectividad y MTU (jumbo 9000)"), _("ping -c 5 {ip2}\nping -M do -s 8972 -c 5 <IP-red-almacenamiento>", ip2=c.ip2),
         _("Sin pérdidas; si falla el de 8972 la MTU no es 9000 en todo el camino")],
        [_("Ancho de banda entre nodos"), _("apt install iperf3\niperf3 -s                      # en {n2}\niperf3 -c <IP-{n2}> -P 4 -t 30   # en {n1}", n2=n2, n1=n1),
         _("Cercano a la velocidad del enlace (p. ej. > 9 Gbit/s en 10 GbE)")],
        [_("Bonds y enlaces"), _("cat /proc/net/bonding/bond0\nethtool <interfaz>"), _("Todos los esclavos «up» y a la velocidad prevista")],
        [_("Disco local (rendimiento básico)"), _("pveperf /var/lib/vz"), _("FSYNCS/SECOND alto (> 1000 con SSD)")],
        [_("Rendimiento de E/S (en una VM o ruta de prueba)"),
         _("fio --name=prueba --filename=/root/fio.test --size=4G --rw=randrw --bs=4k --iodepth=32 \\\n"
         "    --ioengine=libaio --direct=1 --runtime=60 --time_based --group_reporting\nrm /root/fio.test"),
         _("IOPS y latencia acordes al diseño; nunca apuntar fio a un disco en uso")],
        [_("Salud de discos"), _("smartctl -a /dev/<disco>\nzpool scrub ") + c.zpool + _(" ; zpool status"), _("SMART PASSED, sin errores")],
    ]
    if c.has_ceph:
        rows.append([_("Rendimiento de Ceph (pool de pruebas)"),
                     _("rados bench -p {ceph_pool} 30 write --no-cleanup\nrados bench -p {ceph_pool} 30 seq\nrados -p {ceph_pool} cleanup\nceph osd perf", ceph_pool=c.ceph_pool),
                     _("HEALTH_OK antes y después; latencias de OSD homogéneas")])
    rows += [
        [_("Migración en caliente"), _("qm migrate {vm} {n2} --online", vm=vm, n2=n2), _("Sin cortes en la VM (ping continuo)")],
        [_("Réplica"), _("pvesr schedule-now {vm}-0 ; pvesr status", vm=vm), _("Estado OK y duración razonable")],
        [_("Backup y restauración"), _("vzdump {vm} --storage {backup_store}\nqmrestore <volid> <VMID-prueba> --storage {store}", vm=vm, backup_store=c.backup_store, store=c.store),
         _("La copia restaurada arranca; borrar la VM de prueba después")],
        [_("HA (prueba de caída)"), _("ha-manager status\n# apagar {n2} desde el iRMC (corte en frío)", n2=n2),
         _("Las VMs HA arrancan en otro nodo en 2-3 min")],
    ]
    doc.table([_("Prueba"), _("Comando"), _("Resultado esperado")], rows, size=7.5)

    # ---------------------------------------------------------------- Snapshots
    doc.h(_("{n}.5 Snapshots (configuración y réplicas)", n=n), 2)
    doc.p(_("Una snapshot guarda el estado de los discos (y opcionalmente de la RAM) de una VM o CT para poder volver atrás, "
          "por ejemplo antes de una actualización. No es una copia de seguridad: está en el mismo almacenamiento que la VM. "
          "Funciona en ZFS, Ceph RBD, LVM-thin y discos qcow2 (directorio, NFS, CIFS); en LVM normal (no thin) no "
          "está disponible salvo la vista previa técnica de PVE 9."), size=9.5)
    _table(doc, [
        [_("Crear"), _("VM → Snapshots → Take Snapshot (Name, Include RAM, Description)"),
         _("qm snapshot {vm} antes_update --description 'Antes de actualizar' --vmstate 1\npct snapshot <CTID> antes_update", vm=vm)],
        [_("Listar"), _("VM → Snapshots"), _("qm listsnapshot {vm}\npct listsnapshot <CTID>", vm=vm)],
        [_("Volver a una snapshot"), _("VM → Snapshots → Rollback"), _("qm rollback {vm} antes_update\npct rollback <CTID> antes_update", vm=vm)],
        [_("Borrar"), _("VM → Snapshots → Remove"), _("qm delsnapshot {vm} antes_update\npct delsnapshot <CTID> antes_update", vm=vm)],
        [_("Ver espacio que ocupan"), "—",
         _("zfs list -t snapshot -o name,used,creation | grep vm-{vm}-", vm=vm) + (_("\nrbd snap ls {ceph_pool}/vm-{vm}-disk-0", ceph_pool=c.ceph_pool, vm=vm) if c.has_ceph else "")],
    ])
    doc.bullets([
        _("Incluir RAM («Include RAM» / --vmstate 1) permite volver con la VM encendida tal como estaba; sin RAM la VM vuelve apagada. "
        "Para que los datos sean coherentes sin RAM, instalar el QEMU Guest Agent en la VM."),
        _("En ZFS solo se puede volver a la snapshot más reciente: para volver a una anterior hay que borrar antes las posteriores."),
        _("Las snapshots crecen con los cambios: no mantenerlas más de unos días y borrarlas tras validar el cambio."),
        _("Proxmox no tiene snapshots programadas en la GUI. Para tenerlas hay que usar cron con «qm snapshot» y un borrado de las "
        "antiguas, o herramientas de terceros (no soportadas por Proxmox). Para protección diaria se usan los jobs de backup."),
    ])
    doc.h(_("Snapshots y réplicas"), 3)
    doc.bullets([
        _("La replicación (apartado anterior) se basa en snapshots ZFS con nombre «__replicate_<trabajo>_<fecha>__». No borrarlas a mano: "
        "si se borran, la siguiente réplica tiene que copiar el disco completo o falla."),
        _("Si una réplica falla porque el destino tiene datos que no coinciden, borrar el trabajo, borrar los discos del destino y volver a crearlo."),
        _("Réplica de copias fuera de la plataforma: en Proxmox Backup Server, Datastore → Sync Jobs (o Remotes) copia los backups "
        "a un segundo PBS, por ejemplo en otra ubicación."),
    ])
    doc.code(_("# Snapshots de réplica de la VM {vm} (en el nodo origen o destino)\nzfs list -t snapshot | grep vm-{vm}- | grep __replicate_\npvesr status --guest {vm}", vm=vm))
    snaps = sheets.get("vSnapshot", [])
    if snaps:
        doc.h(_("Snapshots existentes en el momento del inventario"), 3)
        old = [r for r in snaps if (num(r.get("Antigüedad (días)"), 0) or 0) > 7]
        doc.p(_("{n_snaps} snapshot(s); {n_old} con más de 7 días.", n_snaps=len(snaps), n_old=len(old)), size=9.5, bold=bool(old))
        doc.table(["Clúster", "Nodo", "VMID", "Nombre", "Snapshot", "Fecha", _("Días"), "RAM"],
                  [[r.get("Clúster"), r.get("Nodo"), r.get("VMID"), r.get("Nombre"), r.get("Snapshot"), r.get("Fecha"),
                    r.get("Antigüedad (días)"), r.get("Con RAM")] for r in snaps[:60]], size=7.5)


def add_contact(doc, n, author=""):
    """Añade el apartado «n. Contacto y soporte»."""
    doc.h(_("{n}. Contacto y soporte", n=n))
    doc.p(_("Para abrir una incidencia o hacer una consulta sobre la plataforma, contactar con el soporte de Fsas Technologies:"), size=9.5)
    doc.kv(SUPPORT_CONTACT)
    doc.h(_("Datos a tener preparados al abrir una incidencia"), 3)
    doc.checklist(SUPPORT_CHECKLIST)
    doc.h(_("Contactos del proyecto"), 3)
    doc.kv([(_("Cliente: responsable técnico"), "________"),
            (_("Fsas Technologies: proyecto / preventa"), author or "________")])
