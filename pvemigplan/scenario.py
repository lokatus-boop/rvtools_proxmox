"""Escenario de planificación: todos los parámetros que el usuario puede ajustar (se guarda como JSON)."""
from __future__ import annotations

import copy
import json

PVE_VERSIONS = ["9.1", "9.0", "8.4"]
PBS_VERSIONS = {"9.1": "4.1", "9.0": "4.0", "8.4": "3.4"}
STORAGE_TYPES = {
    "ceph": "Ceph hiperconvergente (discos NVMe en los nodos)",
    "zfs": "ZFS local en cada nodo + replicación",
    "san": "Cabina externa iSCSI / FC (LVM compartido)",
    "nfs": "NAS externa NFS",
}

DEFAULT = {
    "cliente": "",
    "proyecto": "Migración a nueva plataforma Proxmox VE",
    "autor": "",
    "modo": "aconsejar",            # aconsejar | hardware
    "pve_version": "9.1",
    "alcance": {"incluir_apagadas": True, "incluir_plantillas": False, "excluir": []},
    "capacidad": {
        "crecimiento_pct": 20,       # crecimiento previsto durante la vida útil
        "base_cpu": "asignado",      # asignado (vCPU / ratio) | observado (uso real de los nodos)
        "ratio_vcpu_core": 4.0,      # vCPU por core físico
        "cpu_max_pct": 75,           # ocupación máxima de CPU con todos los nodos en marcha
        "ram_max_pct": 85,           # ocupación máxima de RAM
        "n_mas": 1,                  # nodos de reserva (N+1)
        "nodos_min": 3,
        "base_disco": "usado",       # usado | aprovisionado
        "reserva_snapshots_pct": 10,
    },
    "almacenamiento": {"tipo": "ceph", "replicas": 3, "llenado_max_pct": 80},
    "red": {"velocidad_gbps": 25, "jumbo": True},
    "hardware": {
        "servidores": [
            {"modelo": "PRIMERGY RX2540 M7", "cantidad": 3, "cpu": "2× Xeon Gold 32 cores", "sockets": 2,
             "cores_por_socket": 32, "ghz": 2.3, "ram_gib": 768,
             "discos": [{"cantidad": 2, "tb": 0.48, "tipo": "SSD M.2", "uso": "arranque"},
                        {"cantidad": 6, "tb": 3.84, "tipo": "NVMe", "uso": "datos"}],
             "nics": [{"puertos": 2, "gbps": 1, "uso": "gestion"},
                      {"puertos": 2, "gbps": 25, "uso": "vms"},
                      {"puertos": 2, "gbps": 25, "uso": "almacenamiento"}]},
        ],
        "almacenamiento_externo": {"modelo": "", "capacidad_util_tib": 0, "protocolo": "iSCSI"},
        "switches": {"modelo": "", "cantidad": 2, "gbps": 25, "puertos": 48},
    },
    "pbs": {
        "incluir": True,
        "retencion": {"diaria": 14, "semanal": 8, "mensual": 12, "anual": 0},
        "cambio_diario_pct": 1.5,     # bloques únicos nuevos por día (sobre los datos usados)
        "reduccion": 0.6,            # datos guardados / datos de origen (deduplicación + compresión)
        "llenado_max_pct": 80,
        "offsite": False,            # segundo PBS de sincronización (copia fuera del CPD)
        "hardware": {"definido": False, "modelo": "PRIMERGY RX2540 M7", "cores": 16, "ram_gib": 128,
                     "capacidad_util_tib": 0, "discos": "", "gbps": 25},
    },
    "migracion": {
        "metodo": "auto",            # auto | pbs | remote-migrate
        "mbps_por_flujo": 300,       # MB/s efectivos por migración simultánea
        "flujos": 2,
        "max_vms_ola": 15,
        "max_gib_ola": 3072,
        "olas_por_semana": 2,
        "inicio": "",                # AAAA-MM-DD (vacío = sin fechas)
    },
}


def new() -> dict:
    return copy.deepcopy(DEFAULT)


def merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def load(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return merge(DEFAULT, json.load(f))


def save(sc: dict, path: str):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(sc, f, ensure_ascii=False, indent=2)
