# PVE Migration Planner — Planificador de migración a Proxmox VE

Aplicación **de uso interno de Fsas Technologies** (no se entrega al cliente) que lee el Excel o los CSV exportados por
**PVE Inventory** y genera el diseño de la nueva plataforma Proxmox VE y el plan de migración:

* **Excel del plan** para el equipo técnico: opciones de hardware, nodos, capacidad, ubicación de cada VM, redes y VLANs,
  puertos de switch, almacenamiento, PBS, olas de migración y riesgos por VM.
* **Documento Word para el cliente** (editable, con portada y logo de Fsas Technologies) con gráficos: situación actual,
  requisitos, arquitectura propuesta, red, almacenamiento, copias con PBS, plan de migración por olas, riesgos y anexos.
  Opcionalmente guarda los gráficos en PNG para usarlos en una presentación.

Se ejecuta en local, no se conecta a ningún servidor y no envía nada a la nube. Al arrancar por primera vez muestra el aviso de uso.

![Destino](planificador_destino.png)

## Flujo de trabajo

1. El cliente ejecuta **PVE Inventory** y nos devuelve el Excel (o la carpeta de CSV). Si tiene varios clústeres puede
   enviar un fichero por clúster: el planificador acepta varios y los une (sin duplicar VMs si un clúster se carga dos veces).
2. En **PVEMigrationPlanner.exe**:
   * **1 · Inventario:** cargar los ficheros, decidir si entran VMs apagadas y plantillas, y excluir VMs concretas (doble clic).
   * **2 · Destino:** datos del cliente, versión de Proxmox VE, tipo de almacenamiento, velocidad de red y criterios de dimensionado.
     Elegir el modo:
     * **Aconsejar hardware** (destino desconocido): calcula alternativas de servidor y recomienda la de menor coste estimado.
     * **Usar el hardware disponible / que se va a adquirir:** se introducen los servidores (modelo, nº, CPU, RAM, discos,
       puertos de red), la cabina/NAS y los switches; el plan se centra en ese hardware y avisa si no es suficiente.
   * **3 · Backup (PBS):** incluir o no Proxmox Backup Server, retención, supuestos y, si ya se conoce, el hardware del PBS.
   * **4 · Migración:** método, rendimiento, tamaño de las olas, olas por semana y fecha de inicio.
   * **5 · Plan y documentos:** *Calcular plan* muestra el resumen y los riesgos; *Generar Excel + Word* crea los documentos.
3. El escenario (todos los parámetros y el hardware) se puede guardar como JSON (*Archivo → Guardar escenario*) para
   retomarlo o para usarlo desde la línea de comandos.

![Plan](planificador_plan.png)

## Cómo calcula

| Tema | Criterio (todos ajustables) |
|---|---|
| CPU | vCPU asignadas × (1 + crecimiento) / ratio vCPU:core (4) / ocupación máxima (75 %). Alternativa: uso observado × 1,5. |
| RAM | RAM asignada × (1 + crecimiento) / ocupación máxima (85 %) + reserva por nodo (8 GiB Proxmox VE; Ceph 5 GiB por OSD + 4 GiB; ZFS ARC). |
| Disco | Espacio usado (agente QEMU) o aprovisionado si no se conoce, × (1 + crecimiento) + 10 % de reserva para snapshots. |
| Alta disponibilidad | N+1 (configurable): CPU y RAM deben caber con el nodo mayor caído; mínimo 3 nodos. |
| Ceph | Bruto = datos × réplicas (3) / llenado máximo (80 %), repartido entre N-1 nodos (tolera la caída de un nodo). 4-8 NVMe por nodo. |
| ZFS local | Espejo (RAID10) + espacio para las réplicas de otro nodo. |
| SAN / NFS | Capacidad útil de la cabina = datos / llenado máximo. Multipath (iSCSI/FC) o NFS 4.x. |
| Opciones de hardware | Catálogo de plantillas (1U 1 socket, 1U 2 sockets, 2U 2 sockets) × CPUs de 16-64 cores × tamaños de RAM. Se ordenan por un **coste relativo orientativo** que incluye las suscripciones de Proxmox VE (por socket). El catálogo se puede sustituir por un JSON propio (*Archivo → Cargar catálogo*, ver `pvemigplan/catalog.py`). |
| Red | Gestión + Corosync (2 enlaces), VMs (bond LACP, bridge VLAN-aware o SDN), migración, Ceph/almacenamiento, backup y BMC. Tabla de correspondencia de VLANs origen → destino y nº de puertos de switch. |
| PBS | Datos usados × reducción (0,6) × (1 + cambio diario × días de cambios retenidos) / llenado (80 %). Semanales = 2 días, mensuales = 4, anuales = 8. Propone CPU, RAM (32 GiB + 1 GiB/TiB), discos (all-flash si es pequeño; HDD RAIDZ2 + special device si no) y red. Opción de copia externa. |
| Migración | Con PBS: backup previo + backup final incremental + restore (live-restore). Sin PBS: `qm/pct remote-migrate`. Ola 0 piloto, olas estándar por clúster/pool y críticas (HA, BD, DC, orden de arranque) al final. |
| Riesgos | Passthrough, bloqueos, snapshots, ISOs montadas, CPU «host» con cambio de fabricante, SO antiguos, CTs antiguos en PVE 9 (cgroup v2), sin agente, sin backup, discos grandes, HA, capacidad y versiones de origen. |

Las cifras son estimaciones: el inventario es una foto en un instante y los modelos de servidor son orientativos.
Valida la configuración con el configurador del fabricante antes de ofertar.

## Línea de comandos

```bat
pvemigplan-cli.exe inventario.xlsx -o C:\Planes\ACME --cliente "ACME" --graficos
pvemigplan-cli.exe inv_clu1.xlsx inv_clu2.xlsx --almacenamiento san --pve 9.1 --sin-pbs
pvemigplan-cli.exe inventario.xlsx -e escenario.json        :: hardware definido y parámetros guardados desde la GUI
```

Código de salida: 0 plan correcto, 1 el hardware no cubre las necesidades, 2 error.

## Compilar

`build_planner.bat` en Windows (Python 3.10+) o el workflow `.github/workflows/build-planner.yml`
(Actions → *Build migration planner exe*), que genera `PVEMigrationPlanner.exe` y `pvemigplan-cli.exe` y un plan de ejemplo.

## Desarrollo

```bash
pip install -r requirements.txt -r requirements-planner.txt pytest
python -m pvemigplan                       # GUI (sin argumentos) o CLI (con argumentos)
python -m pytest tests/test_planner.py     # usa un inventario sintético de 120 VMs (tests/planner_sample.py)
```

El código está en `pvemigplan/` y reutiliza de `pvetools/` solo el formato de exportación (`schema.py`) y el logo.
