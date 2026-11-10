"""Catálogo de referencia para el modo «aconsejar hardware».

Son plantillas genéricas: los modelos citados son ejemplos orientativos. Valida siempre la configuración final
(CPU, DIMMs, bahías, tarjetas de red) con el configurador del fabricante antes de ofertar.
Se puede sustituir por un JSON propio con la misma estructura (opción --catalogo / menú Archivo).
"""
from __future__ import annotations

import copy
import json

TB_TO_GIB = 1e12 / 2**30   # 1 TB (decimal, como se venden los discos) = 931,3 GiB

DEFAULT_CATALOG = {
    "servidores": [
        {"id": "1u1s", "nombre": "1U monosocket", "referencia": "p. ej. PRIMERGY RX2530 M7 con 1 CPU",
         "sockets": 1, "bahias": 10, "ram_max_gib": 1024, "coste_base": 1.0},
        {"id": "1u2s", "nombre": "1U doble socket", "referencia": "p. ej. PRIMERGY RX2530 M7",
         "sockets": 2, "bahias": 10, "ram_max_gib": 2048, "coste_base": 1.25},
        {"id": "2u2s", "nombre": "2U doble socket", "referencia": "p. ej. PRIMERGY RX2540 M7",
         "sockets": 2, "bahias": 24, "ram_max_gib": 4096, "coste_base": 1.45},
    ],
    # cores por socket y frecuencia base orientativa
    "cpus": [
        {"cores": 16, "ghz": 2.6, "ejemplo": "Xeon Gold / EPYC de 16 cores", "coste_core": 0.040},
        {"cores": 24, "ghz": 2.4, "ejemplo": "Xeon Gold / EPYC de 24 cores", "coste_core": 0.036},
        {"cores": 32, "ghz": 2.3, "ejemplo": "Xeon Gold / EPYC de 32 cores", "coste_core": 0.034},
        {"cores": 48, "ghz": 2.2, "ejemplo": "Xeon Platinum / EPYC de 48 cores", "coste_core": 0.036},
        {"cores": 64, "ghz": 2.1, "ejemplo": "Xeon Platinum / EPYC de 64 cores", "coste_core": 0.040},
    ],
    "ram_gib": [128, 256, 384, 512, 768, 1024, 1536, 2048, 3072, 4096],
    "coste_gib_ram": 0.004,
    "coste_suscripcion_socket": 0.30,   # suscripción Proxmox VE: se licencia por socket de CPU
    "discos_datos_tb": [1.92, 3.84, 7.68, 15.36],
    "discos_pbs_tb": [8, 12, 16, 20, 24],
}


def load_catalog(path: str | None = None) -> dict:
    cat = copy.deepcopy(DEFAULT_CATALOG)
    if path:
        with open(path, encoding="utf-8") as f:
            cat.update(json.load(f))
    return cat
