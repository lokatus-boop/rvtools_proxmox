# Formato de exportación de PVE Inventory

**Versión de formato: 1** (aparece en la hoja *Aviso* y en la columna *Versión formato* de *vSource*).

Este documento describe las hojas del Excel y los ficheros CSV que genera la herramienta, para las aplicaciones
que los leen (por ejemplo, el planificador de migración). Se genera con `python tools/gen_format_doc.py`.

## Reglas

* **Excel:** la primera hoja es *Aviso* (logo y aviso de uso). Después va una hoja por pestaña, con el nombre exacto de la tabla.
  La fila 1 contiene las cabeceras y los datos empiezan en la fila 2.
* **CSV:** un fichero `<hoja>.csv` por hoja, en UTF-8 con BOM, separador `;`, con las mismas cabeceras. Incluye además `LEEME_AVISO.txt`.
* Una hoja sin datos se exporta igualmente con sus cabeceras.
* **Valores:**
  * Los vacíos se dejan en blanco.
  * Los booleanos se escriben como `Sí` / `No`.
  * Las fechas usan el formato `AAAA-MM-DD hh:mm:ss`, en hora local del equipo que ejecuta la herramienta.
  * Los tamaños van en GiB o MiB, según indique la cabecera, y los porcentajes de 0 a 100.
* La columna `Clúster` identifica el clúster, o `<nodo> (standalone)` si es un nodo independiente. Las VMs/CTs se
  identifican por (`Clúster`, `VMID`) y los nodos por (`Clúster`, `Nodo`).
* **Inventario anonimizado:** la columna `Anonimizado` de *vSource* vale `Sí` (o `Sí (IPs conservadas)`). Los nombres
  son seudónimos consistentes en todas las hojas (`CLUSTER-01`, `NODO-01`, `VM-0001`, `STORAGE-01`…; sufijos `-crit`/`-test`
  como pista de rol), las IPs están transformadas conservando subredes y los textos libres vacíos. El resto de columnas no cambia.
* **Estabilidad:**
  * No se renombran ni se eliminan columnas sin subir la versión de formato.
  * Las columnas nuevas se añaden al final de su hoja.
  * Las hojas nuevas pueden aparecer en cualquier posición: localízalas por su nombre.

## Hojas

### Máquinas virtuales

#### vInfo

Una fila por VM/CT con sus datos generales

| # | Columna |
|---|---|
| 1 | Clúster |
| 2 | Nodo |
| 3 | VMID |
| 4 | Nombre |
| 5 | Tipo |
| 6 | Estado |
| 7 | Plantilla |
| 8 | HA |
| 9 | Pool |
| 10 | Etiquetas |
| 11 | Tipo SO |
| 12 | SO invitado (agente) |
| 13 | Hostname |
| 14 | IPs |
| 15 | vCPU |
| 16 | Memoria (MiB) |
| 17 | Discos |
| 18 | Disco aprovisionado (GiB) |
| 19 | Disco usado (GiB) |
| 20 | NICs |
| 21 | Snapshots |
| 22 | Uptime |
| 23 | Arranque automático |
| 24 | Orden arranque |
| 25 | BIOS |
| 26 | Máquina |
| 27 | Agente QEMU |
| 28 | Agente responde |
| 29 | Sin privilegios |
| 30 | Protección |
| 31 | Bloqueo |
| 32 | Creada |
| 33 | Firewall VM |
| 34 | Passthrough |
| 35 | Descripción |
| 36 | Último backup |

#### vCPU

CPU de cada VM/CT

| # | Columna |
|---|---|
| 1 | Clúster |
| 2 | Nodo |
| 3 | VMID |
| 4 | Nombre |
| 5 | Tipo |
| 6 | Estado |
| 7 | Sockets |
| 8 | Cores |
| 9 | vCPU |
| 10 | Tipo CPU |
| 11 | Límite CPU |
| 12 | CPU units |
| 13 | Afinidad |
| 14 | NUMA |
| 15 | Uso CPU (%) |

#### vMemory

Memoria de cada VM/CT

| # | Columna |
|---|---|
| 1 | Clúster |
| 2 | Nodo |
| 3 | VMID |
| 4 | Nombre |
| 5 | Tipo |
| 6 | Estado |
| 7 | Memoria (MiB) |
| 8 | Balloon mín. (MiB) |
| 9 | Swap (MiB) |
| 10 | Shares |
| 11 | Hugepages |
| 12 | Memoria usada (MiB) |
| 13 | Uso memoria (%) |

#### vDisk

Un disco por fila (VMs y CTs; incluye discos sin usar)

| # | Columna |
|---|---|
| 1 | Clúster |
| 2 | Nodo |
| 3 | VMID |
| 4 | Nombre |
| 5 | Tipo |
| 6 | Disco |
| 7 | Almacenamiento |
| 8 | Volumen |
| 9 | Tamaño (GiB) |
| 10 | Formato |
| 11 | Punto de montaje |
| 12 | Caché |
| 13 | Discard |
| 14 | SSD |
| 15 | IO thread |
| 16 | Backup |
| 17 | Replicar |
| 18 | Sin usar |

#### vCD

Unidades CD-ROM de VMs

| # | Columna |
|---|---|
| 1 | Clúster |
| 2 | Nodo |
| 3 | VMID |
| 4 | Nombre |
| 5 | Tipo |
| 6 | Dispositivo |
| 7 | Medio |
| 8 | Conectado |

#### vNetwork

Una NIC de VM/CT por fila

| # | Columna |
|---|---|
| 1 | Clúster |
| 2 | Nodo |
| 3 | VMID |
| 4 | Nombre |
| 5 | Tipo |
| 6 | Interfaz |
| 7 | Nombre en invitado |
| 8 | Modelo |
| 9 | MAC |
| 10 | Bridge |
| 11 | VLAN |
| 12 | Trunks |
| 13 | Firewall |
| 14 | Desconectada |
| 15 | MTU |
| 16 | Límite (MB/s) |
| 17 | IP config |
| 18 | IPs |

#### vSnapshot

Una snapshot por fila

| # | Columna |
|---|---|
| 1 | Clúster |
| 2 | Nodo |
| 3 | VMID |
| 4 | Nombre |
| 5 | Tipo |
| 6 | Snapshot |
| 7 | Padre |
| 8 | Descripción |
| 9 | Fecha |
| 10 | Antigüedad (días) |
| 11 | Con RAM |

#### vPassthrough

Dispositivos PCI/USB/serie pasados a VMs/CTs

| # | Columna |
|---|---|
| 1 | Clúster |
| 2 | Nodo |
| 3 | VMID |
| 4 | Nombre |
| 5 | Tipo VM |
| 6 | Clave |
| 7 | Tipo |
| 8 | Dispositivo |
| 9 | Mapeado |
| 10 | PCIe |
| 11 | ROM-Bar |
| 12 | GPU principal |
| 13 | Config |

#### vBackupStatus

Estado de backups por VM/CT

| # | Columna |
|---|---|
| 1 | Clúster |
| 2 | Nodo |
| 3 | VMID |
| 4 | Nombre |
| 5 | Tipo |
| 6 | Estado VM |
| 7 | Nº copias |
| 8 | Último backup |
| 9 | Antigüedad (días) |
| 10 | Tamaño último (GiB) |
| 11 | Almacenamiento |
| 12 | Verificado |
| 13 | Protegido |
| 14 | Almacenamientos con copias |

### Hosts

#### vHost

Un nodo por fila

| # | Columna |
|---|---|
| 1 | Clúster |
| 2 | Nodo |
| 3 | Estado |
| 4 | IP |
| 5 | Versión PVE |
| 6 | Release |
| 7 | Kernel |
| 8 | Modelo CPU |
| 9 | Sockets |
| 10 | Cores |
| 11 | Hilos |
| 12 | MHz |
| 13 | Uso CPU (%) |
| 14 | RAM total (GiB) |
| 15 | RAM usada (GiB) |
| 16 | Uso RAM (%) |
| 17 | Swap total (GiB) |
| 18 | Swap usada (GiB) |
| 19 | Root FS (GiB) |
| 20 | Root FS uso (%) |
| 21 | Uptime |
| 22 | Load avg |
| 23 | Arranque |
| 24 | VMs |
| 25 | CTs |
| 26 | Encendidas |
| 27 | vCPU asignadas (encendidas) |
| 28 | Ratio vCPU:hilo |
| 29 | RAM asignada encendidas (GiB) |
| 30 | Suscripción |
| 31 | Nivel suscripción |
| 32 | Actualizaciones pendientes |
| 33 | DNS |
| 34 | Dominio búsqueda |
| 35 | Zona horaria |

#### vPhysicalDisk

Discos físicos de los nodos

| # | Columna |
|---|---|
| 1 | Clúster |
| 2 | Nodo |
| 3 | Dispositivo |
| 4 | Tipo |
| 5 | Modelo |
| 6 | Fabricante |
| 7 | Serie |
| 8 | Tamaño (GiB) |
| 9 | RPM |
| 10 | SMART |
| 11 | Desgaste (%) |
| 12 | Uso |
| 13 | GPT |
| 14 | OSD Ceph |

#### vRepo

Repositorios APT de Proxmox

| # | Columna |
|---|---|
| 1 | Clúster |
| 2 | Nodo |
| 3 | Repositorio |
| 4 | Handle |
| 5 | Estado |

#### vCert

Certificados de los nodos

| # | Columna |
|---|---|
| 1 | Clúster |
| 2 | Nodo |
| 3 | Fichero |
| 4 | Sujeto |
| 5 | Emisor |
| 6 | Válido desde |
| 7 | Válido hasta |
| 8 | Días restantes |
| 9 | SAN |
| 10 | Huella SHA256 |

### Red

#### vHostNIC

Todas las interfaces de red de los nodos

| # | Columna |
|---|---|
| 1 | Clúster |
| 2 | Nodo |
| 3 | Interfaz |
| 4 | Tipo |
| 5 | Activa |
| 6 | Autostart |
| 7 | Método |
| 8 | CIDR |
| 9 | Gateway |
| 10 | CIDR IPv6 |
| 11 | Puertos bridge |
| 12 | VLAN aware |
| 13 | Esclavos bond |
| 14 | Modo bond |
| 15 | VLAN id |
| 16 | VLAN raw device |
| 17 | MTU |
| 18 | Comentario |

#### vBond

Bonds (teaming)

| # | Columna |
|---|---|
| 1 | Clúster |
| 2 | Nodo |
| 3 | Bond |
| 4 | Modo |
| 5 | Esclavos |
| 6 | Nº esclavos |
| 7 | Hash (xmit_hash_policy) |
| 8 | Primario |
| 9 | Activo |
| 10 | MTU |
| 11 | CIDR |
| 12 | Usado por |
| 13 | Comentario |

#### vBridge

Bridges Linux/OVS

| # | Columna |
|---|---|
| 1 | Clúster |
| 2 | Nodo |
| 3 | Bridge |
| 4 | Tipo |
| 5 | Puertos |
| 6 | VLAN aware |
| 7 | VLANs permitidas |
| 8 | STP |
| 9 | Activo |
| 10 | Método |
| 11 | CIDR |
| 12 | Gateway |
| 13 | CIDR IPv6 |
| 14 | MTU |
| 15 | NICs de VMs/CTs |
| 16 | VLANs usadas por VMs |
| 17 | Comentario |

#### vHostVLAN

Interfaces VLAN de los nodos

| # | Columna |
|---|---|
| 1 | Clúster |
| 2 | Nodo |
| 3 | Interfaz |
| 4 | VLAN id |
| 5 | Dispositivo base |
| 6 | Protocolo |
| 7 | Activo |
| 8 | CIDR |
| 9 | Gateway |
| 10 | MTU |
| 11 | Comentario |

#### vSDN

SDN: una fila por subred (o VNet/zona sin subred)

| # | Columna |
|---|---|
| 1 | Clúster |
| 2 | Zona |
| 3 | Tipo zona |
| 4 | Bridge zona |
| 5 | Nodos zona |
| 6 | MTU |
| 7 | IPAM |
| 8 | VNet |
| 9 | Alias |
| 10 | Tag / VNI |
| 11 | VLAN aware |
| 12 | Subred |
| 13 | Gateway |
| 14 | SNAT |
| 15 | Rango DHCP |
| 16 | Pendiente de aplicar |

#### vCorosync

Enlaces corosync por nodo

| # | Columna |
|---|---|
| 1 | Clúster |
| 2 | Nodo |
| 3 | Node ID |
| 4 | Votos |
| 5 | Enlaces |
| 6 | Direcciones |
| 7 | Modo enlaces |
| 8 | Versión config |
| 9 | Secauth |
| 10 | IP version |

### Almacenamiento

#### vDatastore

Un almacenamiento por nodo y fila

| # | Columna |
|---|---|
| 1 | Clúster |
| 2 | Nodo |
| 3 | Almacenamiento |
| 4 | Tipo |
| 5 | Estado |
| 6 | Compartido |
| 7 | Contenido |
| 8 | Total (GiB) |
| 9 | Usado (GiB) |
| 10 | Libre (GiB) |
| 11 | Uso (%) |
| 12 | Ruta / destino |
| 13 | Servidor |
| 14 | Nodos permitidos |
| 15 | Deshabilitado |

#### vZFS

Pools ZFS

| # | Columna |
|---|---|
| 1 | Clúster |
| 2 | Nodo |
| 3 | Pool |
| 4 | Estado |
| 5 | Tamaño (GiB) |
| 6 | Asignado (GiB) |
| 7 | Libre (GiB) |
| 8 | Uso (%) |
| 9 | Fragmentación (%) |
| 10 | Dedup |

#### vCephOSD

OSDs de Ceph

| # | Columna |
|---|---|
| 1 | Clúster |
| 2 | Host |
| 3 | OSD |
| 4 | Estado |
| 5 | In |
| 6 | Clase |
| 7 | Tipo |
| 8 | Peso CRUSH |
| 9 | Tamaño (GiB) |
| 10 | Usado (GiB) |
| 11 | Uso (%) |
| 12 | Latencia apply (ms) |
| 13 | Latencia commit (ms) |
| 14 | Versión |

#### vCephPool

Pools de Ceph

| # | Columna |
|---|---|
| 1 | Clúster |
| 2 | Pool |
| 3 | Réplicas (size) |
| 4 | Mín. réplicas |
| 5 | PGs |
| 6 | Autoscale |
| 7 | Regla CRUSH |
| 8 | Usado (GiB) |
| 9 | Uso (%) |
| 10 | Aplicación |

### Clúster

#### vCluster

Una fila por clúster o nodo independiente

| # | Columna |
|---|---|
| 1 | Clúster / nodo |
| 2 | Tipo |
| 3 | Conectado vía |
| 4 | Nodos |
| 5 | Nodos online |
| 6 | Quórum |
| 7 | Versión config |
| 8 | VMs |
| 9 | CTs |
| 10 | Plantillas |
| 11 | Encendidas |
| 12 | Hilos CPU totales |
| 13 | RAM total (GiB) |
| 14 | Almacenamiento total (GiB) |
| 15 | Almacenamiento usado (GiB) |
| 16 | Ceph |

#### vHA

Recursos, grupos (PVE 8) y reglas (PVE 9) de HA

| # | Columna |
|---|---|
| 1 | Clúster |
| 2 | Elemento |
| 3 | Recurso |
| 4 | Estado solicitado |
| 5 | Grupo |
| 6 | Máx. reinicios |
| 7 | Máx. reubicaciones |
| 8 | Fallback |
| 9 | Nodos |
| 10 | Restringido |
| 11 | Recursos afectados |
| 12 | Afinidad |
| 13 | Habilitada |
| 14 | Comentario |

#### vBackup

Jobs de backup

| # | Columna |
|---|---|
| 1 | Clúster |
| 2 | Job |
| 3 | Habilitado |
| 4 | Planificación |
| 5 | Almacenamiento |
| 6 | Modo |
| 7 | Compresión |
| 8 | Selección |
| 9 | Nodo |
| 10 | Retención |
| 11 | Notificación |
| 12 | Comentario |

#### vReplication

Jobs de replicación

| # | Columna |
|---|---|
| 1 | Clúster |
| 2 | Job |
| 3 | VMID |
| 4 | Destino |
| 5 | Planificación |
| 6 | Límite (MB/s) |
| 7 | Habilitado |
| 8 | Comentario |

#### vTasks

Tareas con error de los últimos 7 días

| # | Columna |
|---|---|
| 1 | Clúster |
| 2 | Nodo |
| 3 | Tipo |
| 4 | Objeto |
| 5 | Usuario |
| 6 | Inicio |
| 7 | Fin |
| 8 | Estado |
| 9 | Gravedad |

### Seguridad

#### vFirewall

Reglas de firewall

| # | Columna |
|---|---|
| 1 | Clúster |
| 2 | Ámbito |
| 3 | Pos |
| 4 | Dirección |
| 5 | Acción |
| 6 | Macro |
| 7 | Origen |
| 8 | Destino |
| 9 | Protocolo |
| 10 | Puerto destino |
| 11 | Puerto origen |
| 12 | Interfaz |
| 13 | Log |
| 14 | Habilitada |
| 15 | Comentario |

#### vFirewallObj

Alias, IPSets y security groups

| # | Columna |
|---|---|
| 1 | Clúster |
| 2 | Tipo |
| 3 | Nombre |
| 4 | Valor |
| 5 | Comentario |

#### vUsers

Usuarios y API tokens

| # | Columna |
|---|---|
| 1 | Clúster |
| 2 | Tipo |
| 3 | ID |
| 4 | Habilitado |
| 5 | Caduca |
| 6 | Nombre |
| 7 | Email |
| 8 | Grupos |
| 9 | Realm |
| 10 | Privilegios separados |
| 11 | Comentario |

#### vACL

Permisos

| # | Columna |
|---|---|
| 1 | Clúster |
| 2 | Ruta |
| 3 | Tipo |
| 4 | Usuario / grupo |
| 5 | Rol |
| 6 | Propagar |

### Resumen

#### vHealth

Avisos calculados

| # | Columna |
|---|---|
| 1 | Severidad |
| 2 | Clúster |
| 3 | Objeto |
| 4 | Mensaje |

#### vSource

Conexiones realizadas, versión de la herramienta y del formato (y si el inventario está anonimizado)

| # | Columna |
|---|---|
| 1 | Host conectado |
| 2 | Usuario |
| 3 | Autenticación |
| 4 | Fecha |
| 5 | Versión herramienta |
| 6 | Versión formato |
| 7 | Versión PVE |
| 8 | Clúster / nodo |
| 9 | Estado |
| 10 | Duración (s) |
| 11 | Anonimizado |
