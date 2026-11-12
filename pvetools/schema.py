"""Formato estable de exportación (hojas y columnas).

Las aplicaciones que leen el Excel/CSV (p. ej. el planificador de migración) dependen de estos nombres.
Reglas: no renombrar ni quitar columnas sin subir FORMAT_VERSION; las columnas nuevas se añaden al final.
"""

FORMAT_VERSION = 1

SHEET_DESCRIPTIONS = {
    'vInfo': 'Una fila por VM/CT con sus datos generales',
    'vCPU': 'CPU de cada VM/CT',
    'vMemory': 'Memoria de cada VM/CT',
    'vDisk': 'Un disco por fila (VMs y CTs; incluye discos sin usar)',
    'vCD': 'Unidades CD-ROM de VMs',
    'vNetwork': 'Una NIC de VM/CT por fila',
    'vSnapshot': 'Una snapshot por fila',
    'vPassthrough': 'Dispositivos PCI/USB/serie pasados a VMs/CTs',
    'vBackupStatus': 'Estado de backups por VM/CT',
    'vHost': 'Un nodo por fila',
    'vHostNIC': 'Todas las interfaces de red de los nodos',
    'vBond': 'Bonds (teaming)',
    'vBridge': 'Bridges Linux/OVS',
    'vHostVLAN': 'Interfaces VLAN de los nodos',
    'vSDN': 'SDN: una fila por subred (o VNet/zona sin subred)',
    'vSDNObj': 'SDN: controladores (EVPN/BGP/ISIS), IPAM, DNS y fabrics',
    'vCorosync': 'Enlaces corosync por nodo',
    'vDatastore': 'Un almacenamiento por nodo y fila',
    'vPhysicalDisk': 'Discos físicos de los nodos',
    'vZFS': 'Pools ZFS',
    'vCephOSD': 'OSDs de Ceph',
    'vCephPool': 'Pools de Ceph',
    'vCluster': 'Una fila por clúster o nodo independiente',
    'vHA': 'Recursos, grupos (PVE 8) y reglas (PVE 9) de HA',
    'vBackup': 'Jobs de backup',
    'vReplication': 'Jobs de replicación',
    'vTasks': 'Tareas con error de los últimos 7 días',
    'vFirewall': 'Reglas de firewall',
    'vFirewallObj': 'Alias, IPSets y security groups',
    'vUsers': 'Usuarios y API tokens',
    'vACL': 'Permisos',
    'vRepo': 'Repositorios APT de Proxmox',
    'vCert': 'Certificados de los nodos',
    'vHealth': 'Avisos calculados',
    'vSource': 'Conexiones realizadas, versión de la herramienta y del formato (y si el inventario está anonimizado)',
}

SCHEMA = {
    'vInfo': [
        'Clúster', 'Nodo', 'VMID', 'Nombre', 'Tipo', 'Estado', 'Plantilla', 'HA', 'Pool', 'Etiquetas', 'Tipo SO',
        'SO invitado (agente)', 'Hostname', 'IPs', 'vCPU', 'Memoria (MiB)', 'Discos', 'Disco aprovisionado (GiB)',
        'Disco usado (GiB)', 'NICs', 'Snapshots', 'Uptime', 'Arranque automático', 'Orden arranque', 'BIOS',
        'Máquina', 'Agente QEMU', 'Agente responde', 'Sin privilegios', 'Protección', 'Bloqueo', 'Creada',
        'Firewall VM', 'Passthrough', 'Descripción', 'Último backup',
    ],
    'vCPU': [
        'Clúster', 'Nodo', 'VMID', 'Nombre', 'Tipo', 'Estado', 'Sockets', 'Cores', 'vCPU', 'Tipo CPU', 'Límite CPU',
        'CPU units', 'Afinidad', 'NUMA', 'Uso CPU (%)',
    ],
    'vMemory': [
        'Clúster', 'Nodo', 'VMID', 'Nombre', 'Tipo', 'Estado', 'Memoria (MiB)', 'Balloon mín. (MiB)', 'Swap (MiB)',
        'Shares', 'Hugepages', 'Memoria usada (MiB)', 'Uso memoria (%)',
    ],
    'vDisk': [
        'Clúster', 'Nodo', 'VMID', 'Nombre', 'Tipo', 'Disco', 'Almacenamiento', 'Volumen', 'Tamaño (GiB)',
        'Formato', 'Punto de montaje', 'Caché', 'Discard', 'SSD', 'IO thread', 'Backup', 'Replicar', 'Sin usar',
    ],
    'vCD': [
        'Clúster', 'Nodo', 'VMID', 'Nombre', 'Tipo', 'Dispositivo', 'Medio', 'Conectado',
    ],
    'vNetwork': [
        'Clúster', 'Nodo', 'VMID', 'Nombre', 'Tipo', 'Interfaz', 'Nombre en invitado', 'Modelo', 'MAC', 'Bridge',
        'VLAN', 'Trunks', 'Firewall', 'Desconectada', 'MTU', 'Límite (MB/s)', 'IP config', 'IPs',
    ],
    'vSnapshot': [
        'Clúster', 'Nodo', 'VMID', 'Nombre', 'Tipo', 'Snapshot', 'Padre', 'Descripción', 'Fecha',
        'Antigüedad (días)', 'Con RAM',
    ],
    'vPassthrough': [
        'Clúster', 'Nodo', 'VMID', 'Nombre', 'Tipo VM', 'Clave', 'Tipo', 'Dispositivo', 'Mapeado', 'PCIe',
        'ROM-Bar', 'GPU principal', 'Config',
    ],
    'vBackupStatus': [
        'Clúster', 'Nodo', 'VMID', 'Nombre', 'Tipo', 'Estado VM', 'Nº copias', 'Último backup', 'Antigüedad (días)',
        'Tamaño último (GiB)', 'Almacenamiento', 'Verificado', 'Protegido', 'Almacenamientos con copias',
    ],
    'vHost': [
        'Clúster', 'Nodo', 'Estado', 'IP', 'Versión PVE', 'Release', 'Kernel', 'Modelo CPU', 'Sockets', 'Cores',
        'Hilos', 'MHz', 'Uso CPU (%)', 'RAM total (GiB)', 'RAM usada (GiB)', 'Uso RAM (%)', 'Swap total (GiB)',
        'Swap usada (GiB)', 'Root FS (GiB)', 'Root FS uso (%)', 'Uptime', 'Load avg', 'Arranque', 'VMs', 'CTs',
        'Encendidas', 'vCPU asignadas (encendidas)', 'Ratio vCPU:hilo', 'RAM asignada encendidas (GiB)',
        'Suscripción', 'Nivel suscripción', 'Actualizaciones pendientes', 'DNS', 'Dominio búsqueda', 'Zona horaria',
    ],
    'vHostNIC': [
        'Clúster', 'Nodo', 'Interfaz', 'Tipo', 'Activa', 'Autostart', 'Método', 'CIDR', 'Gateway', 'CIDR IPv6',
        'Puertos bridge', 'VLAN aware', 'Esclavos bond', 'Modo bond', 'VLAN id', 'VLAN raw device', 'MTU',
        'Comentario',
    ],
    'vBond': [
        'Clúster', 'Nodo', 'Bond', 'Modo', 'Esclavos', 'Nº esclavos', 'Hash (xmit_hash_policy)', 'Primario',
        'Activo', 'MTU', 'CIDR', 'Usado por', 'Comentario',
    ],
    'vBridge': [
        'Clúster', 'Nodo', 'Bridge', 'Tipo', 'Puertos', 'VLAN aware', 'VLANs permitidas', 'STP', 'Activo', 'Método',
        'CIDR', 'Gateway', 'CIDR IPv6', 'MTU', 'NICs de VMs/CTs', 'VLANs usadas por VMs', 'Comentario',
    ],
    'vHostVLAN': [
        'Clúster', 'Nodo', 'Interfaz', 'VLAN id', 'Dispositivo base', 'Protocolo', 'Activo', 'CIDR', 'Gateway',
        'MTU', 'Comentario',
    ],
    'vSDN': [
        'Clúster', 'Zona', 'Tipo zona', 'Bridge zona', 'Nodos zona', 'MTU', 'IPAM', 'VNet', 'Alias', 'Tag / VNI',
        'VLAN aware', 'Subred', 'Gateway', 'SNAT', 'Rango DHCP', 'Pendiente de aplicar', 'Controlador', 'Peers VXLAN',
        'Exit nodes', 'VRF VXLAN', 'Servicio VLAN (QinQ)', 'Fabric', 'DNS', 'DNS inverso', 'Zona DNS', 'DHCP',
        'Aislar puertos', 'Servidor DNS (DHCP)', 'NICs de VMs/CTs',
    ],
    'vSDNObj': [
        'Clúster', 'Objeto', 'Nombre', 'Tipo', 'Nodo', 'ASN', 'Peers', 'URL / servidor', 'Detalles', 'Pendiente de aplicar',
    ],
    'vCorosync': [
        'Clúster', 'Nodo', 'Node ID', 'Votos', 'Enlaces', 'Direcciones', 'Modo enlaces', 'Versión config',
        'Secauth', 'IP version',
    ],
    'vDatastore': [
        'Clúster', 'Nodo', 'Almacenamiento', 'Tipo', 'Estado', 'Compartido', 'Contenido', 'Total (GiB)',
        'Usado (GiB)', 'Libre (GiB)', 'Uso (%)', 'Ruta / destino', 'Servidor', 'Nodos permitidos', 'Deshabilitado',
    ],
    'vPhysicalDisk': [
        'Clúster', 'Nodo', 'Dispositivo', 'Tipo', 'Modelo', 'Fabricante', 'Serie', 'Tamaño (GiB)', 'RPM', 'SMART',
        'Desgaste (%)', 'Uso', 'GPT', 'OSD Ceph',
    ],
    'vZFS': [
        'Clúster', 'Nodo', 'Pool', 'Estado', 'Tamaño (GiB)', 'Asignado (GiB)', 'Libre (GiB)', 'Uso (%)',
        'Fragmentación (%)', 'Dedup',
    ],
    'vCephOSD': [
        'Clúster', 'Host', 'OSD', 'Estado', 'In', 'Clase', 'Tipo', 'Peso CRUSH', 'Tamaño (GiB)', 'Usado (GiB)',
        'Uso (%)', 'Latencia apply (ms)', 'Latencia commit (ms)', 'Versión',
    ],
    'vCephPool': [
        'Clúster', 'Pool', 'Réplicas (size)', 'Mín. réplicas', 'PGs', 'Autoscale', 'Regla CRUSH', 'Usado (GiB)',
        'Uso (%)', 'Aplicación',
    ],
    'vCluster': [
        'Clúster / nodo', 'Tipo', 'Conectado vía', 'Nodos', 'Nodos online', 'Quórum', 'Versión config', 'VMs',
        'CTs', 'Plantillas', 'Encendidas', 'Hilos CPU totales', 'RAM total (GiB)', 'Almacenamiento total (GiB)',
        'Almacenamiento usado (GiB)', 'Ceph',
    ],
    'vHA': [
        'Clúster', 'Elemento', 'Recurso', 'Estado solicitado', 'Grupo', 'Máx. reinicios', 'Máx. reubicaciones',
        'Fallback', 'Nodos', 'Restringido', 'Recursos afectados', 'Afinidad', 'Habilitada', 'Comentario',
    ],
    'vBackup': [
        'Clúster', 'Job', 'Habilitado', 'Planificación', 'Almacenamiento', 'Modo', 'Compresión', 'Selección',
        'Nodo', 'Retención', 'Notificación', 'Comentario',
    ],
    'vReplication': [
        'Clúster', 'Job', 'VMID', 'Destino', 'Planificación', 'Límite (MB/s)', 'Habilitado', 'Comentario',
    ],
    'vFirewall': [
        'Clúster', 'Ámbito', 'Pos', 'Dirección', 'Acción', 'Macro', 'Origen', 'Destino', 'Protocolo',
        'Puerto destino', 'Puerto origen', 'Interfaz', 'Log', 'Habilitada', 'Comentario',
    ],
    'vFirewallObj': [
        'Clúster', 'Tipo', 'Nombre', 'Valor', 'Comentario',
    ],
    'vUsers': [
        'Clúster', 'Tipo', 'ID', 'Habilitado', 'Caduca', 'Nombre', 'Email', 'Grupos', 'Realm',
        'Privilegios separados', 'Comentario',
    ],
    'vACL': [
        'Clúster', 'Ruta', 'Tipo', 'Usuario / grupo', 'Rol', 'Propagar',
    ],
    'vRepo': [
        'Clúster', 'Nodo', 'Repositorio', 'Handle', 'Estado',
    ],
    'vCert': [
        'Clúster', 'Nodo', 'Fichero', 'Sujeto', 'Emisor', 'Válido desde', 'Válido hasta', 'Días restantes', 'SAN',
        'Huella SHA256',
    ],
    'vTasks': [
        'Clúster', 'Nodo', 'Tipo', 'Objeto', 'Usuario', 'Inicio', 'Fin', 'Estado', 'Gravedad',
    ],
    'vHealth': [
        'Severidad', 'Clúster', 'Objeto', 'Mensaje',
    ],
    'vSource': [
        'Host conectado', 'Usuario', 'Autenticación', 'Fecha', 'Versión herramienta', 'Versión formato',
        'Versión PVE', 'Clúster / nodo', 'Estado', 'Duración (s)', 'Anonimizado',
    ],
}
