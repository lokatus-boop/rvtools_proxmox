"""Inventario sintético (formato de PVE Inventory) para probar el planificador: 2 clústeres, ~120 VMs/CTs."""
import random

from pvetools.schema import SCHEMA


def _row(sheet, **kw):
    return {c: kw.get(c) for c in SCHEMA[sheet]}


def sample_sheets(seed=7, n_guests=120):
    rnd = random.Random(seed)
    sh = {s: [] for s in SCHEMA}
    clusters = {"CLU-PROD": ["pve1", "pve2", "pve3", "pve4"], "pve-dmz (standalone)": ["pve-dmz"]}
    for c, nodes in clusters.items():
        for n in nodes:
            big = c == "CLU-PROD"
            sh["vHost"].append(_row("vHost", **{"Clúster": c, "Nodo": n, "Estado": "online", "Versión PVE": "8.3.2" if big else "7.4-17",
                                                "Modelo CPU": "Intel(R) Xeon(R) Gold 6230 CPU @ 2.10GHz" if big else "AMD EPYC 7302",
                                                "Sockets": 2 if big else 1, "Cores": 40 if big else 16, "Hilos": 80 if big else 32,
                                                "MHz": "2100", "Uso CPU (%)": rnd.randint(25, 55),
                                                "RAM total (GiB)": 512.0 if big else 128.0, "RAM usada (GiB)": 380.0 if big else 70.0}))
            sh["vBridge"].append(_row("vBridge", **{"Clúster": c, "Nodo": n, "Bridge": "vmbr0", "Tipo": "Linux bridge", "Puertos": "bond0",
                                                    "VLAN aware": "Sí", "CIDR": f"10.0.{0 if big else 9}.{11 + nodes.index(n)}/24"}))
            sh["vHostNIC"].append(_row("vHostNIC", **{"Clúster": c, "Nodo": n, "Interfaz": "bond1", "Tipo": "bond", "MTU": 9000 if big else None,
                                                      "CIDR": "10.10.10.%d/24" % (11 + nodes.index(n)) if big else None}))
        if c == "CLU-PROD":
            sh["vDatastore"].append(_row("vDatastore", **{"Clúster": c, "Nodo": "pve1", "Almacenamiento": "ceph-vm", "Tipo": "rbd",
                                                          "Compartido": "Sí", "Total (GiB)": 30000.0, "Usado (GiB)": 16000.0, "Uso (%)": 53.3}))
            sh["vDatastore"].append(_row("vDatastore", **{"Clúster": c, "Nodo": "pve1", "Almacenamiento": "pbs-old", "Tipo": "pbs",
                                                          "Compartido": "Sí", "Total (GiB)": 40000.0, "Usado (GiB)": 21000.0, "Uso (%)": 52.5}))
        else:
            sh["vDatastore"].append(_row("vDatastore", **{"Clúster": c, "Nodo": "pve-dmz", "Almacenamiento": "local-zfs", "Tipo": "zfspool",
                                                          "Compartido": "No", "Total (GiB)": 3500.0, "Usado (GiB)": 1900.0, "Uso (%)": 54.0}))
    sh["vSDN"].append(_row("vSDN", **{"Clúster": "CLU-PROD", "Zona": "zvlan", "Tipo zona": "vlan", "VNet": "vnet100", "Tag / VNI": 100,
                                      "Subred": "192.168.100.0/24"}))
    names = ["web", "app", "db", "sql", "dc", "file", "mail", "erp", "test", "dev", "mon", "proxy", "ci", "vdi"]
    oss = ["l26"] * 5 + ["win10", "win11", "win11", "win8", "w2k8"]
    for i in range(n_guests):
        c = "CLU-PROD" if i < n_guests - 12 else "pve-dmz (standalone)"
        node = rnd.choice(clusters[c])
        vmid = 100 + i
        kind = "CT" if rnd.random() < 0.15 else "VM"
        base = rnd.choice(names)
        name = f"{base}{i:02d}"
        vcpu = rnd.choice([1, 2, 2, 2, 4, 4, 4, 8, 8, 16])
        ram = rnd.choice([1, 2, 4, 4, 8, 8, 16, 16, 32, 64]) * 1024
        disk = rnd.choice([16, 32, 50, 80, 100, 200, 500, 1000, 2000])
        used = round(disk * rnd.uniform(0.3, 0.8), 1) if rnd.random() < 0.8 else None
        running = rnd.random() < 0.85
        ostype = rnd.choice(oss) if kind == "VM" else rnd.choice(["debian", "ubuntu", "centos"])
        vlan = rnd.choice(["10", "20", "20", "30", "40", "", "100"]) if c == "CLU-PROD" else "50"
        bridge = "vnet100" if vlan == "100" else "vmbr0"
        vlan = "" if vlan == "100" else vlan
        sh["vInfo"].append(_row("vInfo", **{
            "Clúster": c, "Nodo": node, "VMID": vmid, "Nombre": name, "Tipo": kind, "Estado": "running" if running else "stopped",
            "Plantilla": "Sí" if i == 5 else "No", "HA": "started" if base in ("db", "dc", "erp") and c == "CLU-PROD" else None,
            "Pool": "prod" if base not in ("test", "dev") else "lab", "Etiquetas": base, "Tipo SO": ostype,
            "vCPU": vcpu, "Memoria (MiB)": ram, "Discos": 1, "Disco aprovisionado (GiB)": float(disk), "Disco usado (GiB)": used,
            "NICs": 1, "Snapshots": 1 if rnd.random() < 0.1 else 0, "Arranque automático": "Sí" if running else "No",
            "Agente QEMU": "Sí" if used else "No", "Passthrough": "hostpci0" if i == 17 else None,
            "Último backup": "2026-11-09 21:00:00" if rnd.random() < 0.9 else None}))
        sh["vCPU"].append(_row("vCPU", **{"Clúster": c, "VMID": vmid, "Nombre": name, "Tipo CPU": "host" if i % 9 == 0 else "x86-64-v2-AES",
                                          "Uso CPU (%)": rnd.randint(1, 60)}))
        sh["vDisk"].append(_row("vDisk", **{"Clúster": c, "Nodo": node, "VMID": vmid, "Nombre": name, "Tipo": kind, "Disco": "scsi0",
                                            "Almacenamiento": "ceph-vm" if c == "CLU-PROD" else "local-zfs", "Tamaño (GiB)": float(disk),
                                            "Sin usar": "No"}))
        sh["vNetwork"].append(_row("vNetwork", **{"Clúster": c, "Nodo": node, "VMID": vmid, "Nombre": name, "Tipo": kind,
                                                  "Interfaz": "net0", "Bridge": bridge, "VLAN": vlan}))
        if i % 23 == 0:
            sh["vCD"].append(_row("vCD", **{"Clúster": c, "VMID": vmid, "Nombre": name, "Dispositivo": "ide2", "Medio": "local:iso/virtio-win.iso"}))
        if used:
            sh["vBackupStatus"].append(_row("vBackupStatus", **{"Clúster": c, "VMID": vmid, "Nombre": name, "Nº copias": 7,
                                                                "Tamaño último (GiB)": round(used * 0.6, 1), "Almacenamiento": "pbs-old"}))
    sh["vHealth"].append(_row("vHealth", **{"Severidad": "CRÍTICO", "Clúster": "CLU-PROD", "Objeto": "pve2", "Mensaje": "RAM 92 %"}))
    sh["vSource"].append(_row("vSource", **{"Host conectado": "10.0.0.11", "Versión formato": 1, "Estado": "OK"}))
    return sh
