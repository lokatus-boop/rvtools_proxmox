"""Dimensionado: necesidades de capacidad, propuestas de hardware y validación del hardware introducido."""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .catalog import TB_TO_GIB

PVE_OVERHEAD_GIB = 8          # sistema + servicios de Proxmox VE por nodo
CEPH_OSD_GIB = 5              # osd_memory_target (4 GiB) + margen, por OSD
CEPH_MON_MGR_GIB = 4


@dataclass
class Requirements:
    vcpu: float
    ram_gib: float
    cores: float            # cores físicos necesarios (con crecimiento y ocupación máxima)
    ram_need_gib: float     # RAM para invitados (con crecimiento y ocupación máxima)
    data_gib: float         # datos a alojar (con crecimiento y reserva)
    data_used_gib: float    # datos reales (para backup)
    max_vcpu: float
    max_ram_gib: float
    notes: list = field(default_factory=list)


@dataclass
class NodeSpec:
    model: str
    reference: str
    sockets: int
    cores_per_socket: int
    ghz: float
    ram_gib: int
    count: int
    cpu_label: str = ""
    data_disks: int = 0
    data_disk_tb: float = 0.0
    data_disk_type: str = "NVMe"
    boot: str = "2× SSD M.2 480 GB en espejo (ZFS RAID1)"
    nics: list = field(default_factory=list)   # [{"puertos", "gbps", "uso"}]
    bays: int = 24
    cost: float = 0.0

    @property
    def cores(self):
        return self.sockets * self.cores_per_socket

    @property
    def threads(self):
        return self.cores * 2

    @property
    def raw_data_gib(self):
        return self.data_disks * self.data_disk_tb * TB_TO_GIB


def requirements(an, sc) -> Requirements:
    cap = sc["capacidad"]
    t = an.totals()
    g = 1 + cap["crecimiento_pct"] / 100
    notes = []
    vcpu = t["vcpu"]
    cores_alloc = vcpu * g / cap["ratio_vcpu_core"] / (cap["cpu_max_pct"] / 100)
    if cap["base_cpu"] == "observado" and an.hosts:
        # pico estimado = 1,5 × uso instantáneo observado (el inventario es una foto, no una serie temporal)
        obs = an.observed_cpu_cores() * 1.5 * g / (cap["cpu_max_pct"] / 100)
        cores = max(obs, vcpu / (cap["ratio_vcpu_core"] * 2))
        notes.append(f"CPU dimensionada por uso observado: {an.observed_cpu_cores():.1f} cores en uso × 1,5 de pico. "
                     "El inventario es una foto puntual: confírmalo con métricas de varias semanas.")
    else:
        cores = cores_alloc
    ram = t["ram_gib"]
    ram_need = ram * g / (cap["ram_max_pct"] / 100)
    base = t["disk_eff_gib"] if cap["base_disco"] == "usado" else t["disk_prov_gib"]
    if cap["base_disco"] == "usado" and t["disk_used_known"] < len(an.guests) * 0.5:
        notes.append("Menos de la mitad de las VMs informan del espacio usado (agente QEMU): para esas se toma el tamaño aprovisionado.")
    data = base * g * (1 + cap["reserva_snapshots_pct"] / 100)
    mv, mr = an.max_guest()
    return Requirements(vcpu=vcpu, ram_gib=ram, cores=cores, ram_need_gib=ram_need, data_gib=data,
                        data_used_gib=t["disk_eff_gib"] * g, max_vcpu=mv, max_ram_gib=mr, notes=notes)


def node_overhead_gib(ram_gib, storage_type, osds=0):
    o = PVE_OVERHEAD_GIB
    if storage_type == "ceph":
        o += osds * CEPH_OSD_GIB + CEPH_MON_MGR_GIB
    elif storage_type == "zfs":
        o += min(16, ram_gib * 0.10) * 2  # ARC (PVE ≥ 8.1: 10 % de la RAM hasta 16 GiB) con margen
    else:
        o += 2
    return o


# ------------------------------------------------------------------ almacenamiento
def storage_per_node(req: Requirements, sc, nodes: int, disk_sizes_tb, bays=24) -> dict:
    """Discos de datos por nodo y capacidad útil según el tipo de almacenamiento."""
    st = sc["almacenamiento"]
    typ, fill = st["tipo"], st["llenado_max_pct"] / 100
    if typ == "ceph":
        rep = st.get("replicas", 3)
        raw_total = req.data_gib * rep / fill
        per_node = raw_total / max(nodes - 1, 1)   # debe caber con un nodo caído
    elif typ == "zfs":
        # cada VM vive en un nodo y se replica a otro; discos en espejo (RAID10)
        per_node = req.data_gib * 2 * 2 / fill / max(nodes - 1, 1)
    else:
        return {"discos": 0, "tb": 0.0, "por_nodo_gib": 0.0, "externo_gib": req.data_gib / fill}
    pick = None
    for tb in disk_sizes_tb:
        n = max(4, math.ceil(per_node / (tb * TB_TO_GIB)))
        if typ == "zfs" and n % 2:
            n += 1
        if n <= min(8, bays):
            pick = (n, tb)
            break
    if not pick:
        tb = disk_sizes_tb[-1]
        n = math.ceil(per_node / (tb * TB_TO_GIB))
        pick = (min(n, bays), tb)
    return {"discos": pick[0], "tb": pick[1], "por_nodo_gib": per_node, "externo_gib": 0.0}


def usable_storage_gib(sc, nodes: list[NodeSpec], external_tib=0.0) -> float:
    st = sc["almacenamiento"]
    typ, fill = st["tipo"], st["llenado_max_pct"] / 100
    if typ == "ceph":
        raws = sorted(n.raw_data_gib for n in nodes)
        raw_minus_one = sum(raws) - (raws[-1] if raws else 0)   # tolera la caída del nodo mayor
        return raw_minus_one / st.get("replicas", 3) * fill
    if typ == "zfs":
        return sum(n.raw_data_gib for n in nodes) / 2 / 2 * fill
    return external_tib * 1024 * fill


# ------------------------------------------------------------------ propuestas
def advise(an, sc, cat) -> list[dict]:
    """Calcula alternativas de hardware y devuelve las tres mejores (la primera es la recomendada)."""
    req = requirements(an, sc)
    cap, typ = sc["capacidad"], sc["almacenamiento"]["tipo"]
    spare, min_nodes = int(cap["n_mas"]), int(cap["nodos_min"])
    cands = []
    for srv in cat["servidores"]:
        for cpu in cat["cpus"]:
            node_cores = srv["sockets"] * cpu["cores"]
            if node_cores * 2 < req.max_vcpu:      # la VM más grande debe caber en un nodo
                continue
            for ram in cat["ram_gib"]:
                if ram > srv["ram_max_gib"]:
                    continue
                # primera aproximación del nº de nodos para estimar OSDs y overhead
                n = max(min_nodes, math.ceil(req.cores / node_cores) + spare, 2)
                for _ in range(4):
                    sto = storage_per_node(req, sc, n, cat["discos_datos_tb"], srv["bahias"])
                    usable_ram = ram - node_overhead_gib(ram, typ, sto["discos"])
                    if usable_ram <= max(req.max_ram_gib, 16):
                        n = None
                        break
                    n_cpu = math.ceil(req.cores / node_cores)
                    n_ram = math.ceil(req.ram_need_gib / usable_ram)
                    n_new = max(n_cpu, n_ram, min_nodes - spare, 1) + spare
                    n_new = max(n_new, min_nodes)
                    if n_new == n:
                        break
                    n = n_new
                if not n or n > 32:
                    continue
                sto = storage_per_node(req, sc, n, cat["discos_datos_tb"], srv["bahias"])
                if typ in ("ceph", "zfs") and sto["discos"] * sto["tb"] * TB_TO_GIB < sto["por_nodo_gib"]:
                    continue   # no cabe en las bahías
                cost = n * (srv["coste_base"] + node_cores * cpu["coste_core"] + ram * cat["coste_gib_ram"]
                            + srv["sockets"] * cat["coste_suscripcion_socket"]
                            + sto["discos"] * sto["tb"] * 0.08)
                spec = NodeSpec(model=srv["nombre"], reference=srv["referencia"], sockets=srv["sockets"],
                                cores_per_socket=cpu["cores"], ghz=cpu["ghz"], ram_gib=ram, count=n,
                                cpu_label=f"{srv['sockets']}× {cpu['ejemplo']} (~{cpu['ghz']} GHz)",
                                data_disks=sto["discos"], data_disk_tb=sto["tb"], bays=srv["bahias"], cost=round(cost, 2),
                                nics=default_nics(sc, typ))
                cands.append(spec)
    if not cands:
        return []
    cands.sort(key=lambda s: (s.cost, s.count))
    picked, seen_counts = [], set()
    labels = ["Recomendada (menor coste estimado)", "Alternativa", "Alternativa"]
    for c in cands:
        key = (c.count, c.model)
        if key in seen_counts:
            continue
        seen_counts.add(key)
        picked.append(c)
        if len(picked) == 3:
            break
    # asegura que haya una opción «compacta» (menos nodos) si es distinta
    fewest = min(cands, key=lambda s: (s.count, s.cost))
    if fewest.count < min(p.count for p in picked):
        picked[-1] = fewest
    out = []
    for i, spec in enumerate(picked):
        ev = evaluate([spec], sc, req)
        out.append({"etiqueta": labels[i] if i < len(labels) else "Alternativa", "nodos": [spec], "eval": ev,
                    "coste": spec.cost})
    base = out[0]["coste"]
    for o in out:
        o["coste_rel"] = round(o["coste"] / base * 100) if base else 100
    return out


def default_nics(sc, typ):
    g = sc["red"]["velocidad_gbps"]
    nics = [{"puertos": 2, "gbps": 1, "uso": "gestion"}, {"puertos": 2, "gbps": g, "uso": "vms"}]
    if typ in ("ceph", "san", "nfs"):
        nics.append({"puertos": 2, "gbps": g, "uso": "almacenamiento"})
    return nics


def nodes_from_hardware(sc) -> list[NodeSpec]:
    out = []
    for s in sc["hardware"]["servidores"]:
        data = [d for d in s.get("discos", []) if d.get("uso", "datos") == "datos"]
        boot = [d for d in s.get("discos", []) if d.get("uso") == "arranque"]
        nd = sum(int(d.get("cantidad", 0)) for d in data)
        raw_tb = sum(int(d.get("cantidad", 0)) * float(d.get("tb", 0)) for d in data)
        out.append(NodeSpec(
            model=s.get("modelo") or "Servidor", reference="", sockets=int(s.get("sockets", 2)),
            cores_per_socket=int(s.get("cores_por_socket", 16)), ghz=float(s.get("ghz", 2.0) or 0),
            ram_gib=int(s.get("ram_gib", 256)), count=int(s.get("cantidad", 1)), cpu_label=s.get("cpu", ""),
            data_disks=nd, data_disk_tb=(raw_tb / nd) if nd else 0.0,
            data_disk_type=", ".join(sorted({d.get("tipo", "") for d in data})) or "-",
            boot=", ".join(f"{d.get('cantidad')}× {d.get('tipo')} {d.get('tb')} TB" for d in boot) or "(no indicado)",
            nics=s.get("nics", [])))
    return out


def expand(nodes: list[NodeSpec]) -> list[NodeSpec]:
    """Una entrada por nodo físico."""
    out = []
    for n in nodes:
        for _ in range(max(n.count, 0)):
            out.append(n)
    return out


def evaluate(groups: list[NodeSpec], sc, req: Requirements) -> dict:
    """Capacidad del hardware frente a las necesidades, con N+1."""
    cap, typ = sc["capacidad"], sc["almacenamiento"]["tipo"]
    nodes = expand(groups)
    spare = int(cap["n_mas"])
    n = len(nodes)
    by_size = sorted(nodes, key=lambda x: (x.cores, x.ram_gib), reverse=True)
    survivors = by_size[spare:] if n > spare else []
    cores_total = sum(x.cores for x in nodes)
    cores_n1 = sum(x.cores for x in survivors)
    osds = lambda x: x.data_disks if typ == "ceph" else 0  # noqa: E731
    ram_total_usable = sum(x.ram_gib - node_overhead_gib(x.ram_gib, typ, osds(x)) for x in nodes)
    ram_n1 = sum(x.ram_gib - node_overhead_gib(x.ram_gib, typ, osds(x)) for x in survivors)
    ext = float(sc["hardware"]["almacenamiento_externo"].get("capacidad_util_tib") or 0) if sc["modo"] == "hardware" else 0
    if typ in ("san", "nfs") and sc["modo"] != "hardware":
        ext = req.data_gib / (sc["almacenamiento"]["llenado_max_pct"] / 100) / 1024
    usable = usable_storage_gib(sc, nodes, ext)
    # ocupación real de CPU/RAM con todos los nodos y con N-spare
    cpu_eff = req.cores * cap["cpu_max_pct"] / 100     # cores realmente consumidos (sin el margen)
    ram_eff = req.ram_need_gib * cap["ram_max_pct"] / 100
    res = {
        "nodos": n, "sockets": sum(x.sockets for x in nodes), "cores": cores_total, "hilos": sum(x.threads for x in nodes),
        "ram_gib": sum(x.ram_gib for x in nodes), "ram_util_gib": ram_total_usable,
        "cores_n1": cores_n1, "ram_n1_gib": ram_n1,
        "cpu_pct": cpu_eff / cores_total * 100 if cores_total else 999,
        "cpu_pct_n1": cpu_eff / cores_n1 * 100 if cores_n1 else 999,
        "ram_pct": ram_eff / ram_total_usable * 100 if ram_total_usable else 999,
        "ram_pct_n1": ram_eff / ram_n1 * 100 if ram_n1 else 999,
        "vcpu_ratio": req.vcpu * (1 + cap["crecimiento_pct"] / 100) / cores_total if cores_total else 0,
        "almacenamiento_util_gib": usable, "datos_gib": req.data_gib,
        "alm_pct": req.data_gib / usable * 100 if usable else 999,
        # ocupación sobre la capacidad bruta útil (el «usable» ya descuenta el llenado máximo)
        "alm_pct_real": req.data_gib / usable * sc["almacenamiento"]["llenado_max_pct"] if usable else 999,
        "problemas": [], "avisos": [],
    }
    if n < 3:
        res["avisos"].append("Con menos de 3 nodos el clúster necesita un QDevice externo para mantener el quórum.")
    if typ == "ceph" and n < 3:
        res["problemas"].append("Ceph necesita al menos 3 nodos (recomendado 4 o más para recuperarse tras un fallo).")
    if res["cpu_pct_n1"] > 100:
        res["problemas"].append(f"CPU insuficiente con {spare} nodo(s) caído(s): {res['cpu_pct_n1']:.0f} % de ocupación.")
    elif res["cpu_pct_n1"] > cap["cpu_max_pct"] + 10:
        res["avisos"].append(f"CPU ajustada con N-{spare}: {res['cpu_pct_n1']:.0f} %.")
    if res["ram_pct_n1"] > 100:
        res["problemas"].append(f"RAM insuficiente con {spare} nodo(s) caído(s): {res['ram_pct_n1']:.0f} % de ocupación.")
    elif res["ram_pct_n1"] > 95:
        res["avisos"].append(f"RAM muy ajustada con N-{spare}: {res['ram_pct_n1']:.0f} %.")
    if usable and res["alm_pct"] > 100:
        res["problemas"].append(f"Almacenamiento insuficiente: se necesitan {req.data_gib/1024:.1f} TiB útiles y hay {usable/1024:.1f} TiB.")
    elif not usable:
        res["problemas"].append("No se ha indicado capacidad de almacenamiento para las VMs.")
    if nodes and max(x.threads for x in nodes) < req.max_vcpu:
        res["problemas"].append(f"La VM más grande ({req.max_vcpu:.0f} vCPU) no cabe en ningún nodo.")
    if nodes and max(x.ram_gib for x in nodes) * 0.9 < req.max_ram_gib:
        res["problemas"].append(f"La VM más grande ({req.max_ram_gib:.0f} GiB de RAM) no cabe en ningún nodo.")
    if typ == "ceph":
        osd_total = sum(x.data_disks for x in nodes)
        if osd_total and osd_total < 12:
            res["avisos"].append(f"Solo {osd_total} OSDs en total: el rendimiento y la recuperación de Ceph mejoran con más discos.")
        speeds = [max([nc.get("gbps", 0) for nc in x.nics if nc.get("uso") == "almacenamiento"] or [0]) for x in nodes]
        if speeds and min(speeds) < 25:
            res["avisos"].append("Ceph sobre NVMe necesita red dedicada de 25 GbE o más (recomendado 2×25 GbE por nodo).")
    if len({(x.sockets, x.cores_per_socket) for x in nodes}) > 1:
        res["avisos"].append("Nodos con CPUs distintas: usa un tipo de CPU virtual común (x86-64-v3 o el modelo más antiguo) para la migración en caliente.")
    if req.cores and sum(x.ghz * x.cores for x in nodes) and min(x.ghz for x in nodes) < 1.8:
        res["avisos"].append("Frecuencia de CPU baja: revisa el rendimiento por hilo frente a los servidores actuales.")
    res["ok"] = not res["problemas"]
    return res


# ------------------------------------------------------------------ PBS
def pbs_sizing(req: Requirements, sc, cat) -> dict:
    p = sc["pbs"]
    r = p["retencion"]
    base = req.data_used_gib
    red = p["reduccion"]
    change = p["cambio_diario_pct"] / 100
    # días de cambios distintos retenidos (las copias semanales/mensuales comparten parte de los cambios)
    eff_days = max(r["diaria"] - 1, 0) + r["semanal"] * 2 + r["mensual"] * 4 + r.get("anual", 0) * 8
    stored = base * red * (1 + change * eff_days)
    usable_need = stored / (p["llenado_max_pct"] / 100)
    tib = usable_need / 1024
    # discos HDD en RAIDZ2 (2 de paridad) + special device SSD en espejo; o all-flash si es pequeño
    if tib <= 20:
        disk_tb = next((d for d in cat["discos_datos_tb"] if (math.ceil(usable_need / (d * TB_TO_GIB)) + 2) <= 12), cat["discos_datos_tb"][-1])
        nd = max(4, math.ceil(usable_need / (disk_tb * TB_TO_GIB / 1)) + 2)
        layout = f"{nd}× SSD {disk_tb} TB en RAIDZ2 (all-flash: restauraciones y live-restore rápidos)"
        raw_usable = (nd - 2) * disk_tb * TB_TO_GIB
    else:
        disk_tb = next((d for d in cat["discos_pbs_tb"] if math.ceil(usable_need / (d * TB_TO_GIB)) + 2 <= 12), cat["discos_pbs_tb"][-1])
        data_disks = math.ceil(usable_need / (disk_tb * TB_TO_GIB))
        vdevs = max(1, math.ceil(data_disks / 8))
        nd = data_disks + 2 * vdevs
        layout = (f"{nd}× HDD {disk_tb} TB en {vdevs} vdev(s) RAIDZ2 + 2× SSD/NVMe en espejo como «special device» "
                  "(metadatos: imprescindible con HDD)")
        raw_usable = data_disks * disk_tb * TB_TO_GIB
    ram = 32 + math.ceil(tib) * 1
    ram = next((x for x in (32, 64, 96, 128, 192, 256, 384, 512) if x >= ram), ram)
    cores = 8 if tib < 30 else 16 if tib < 100 else 24
    mig = sc["migracion"]
    gibh = mig["mbps_por_flujo"] * 1e6 * 3600 / 2**30
    full_h = base * 1.0 / (gibh * max(mig["flujos"], 1))
    inc_h = base * change / (gibh * max(mig["flujos"], 1))
    out = {
        "datos_origen_gib": base, "guardado_gib": stored, "util_necesario_gib": usable_need,
        "dias_cambio_efectivos": eff_days,
        "propuesta": {"cores": cores, "ram_gib": ram, "discos": layout, "util_gib": raw_usable * 0.95,
                      "red": f"2× {max(sc['red']['velocidad_gbps'], 10)} GbE (bond) + 1 GbE gestión + BMC"},
        "horas_full": full_h, "horas_incremental": inc_h,
        "avisos": [],
    }
    hw = p.get("hardware", {})
    if hw.get("definido"):
        have = float(hw.get("capacidad_util_tib") or 0) * 1024
        out["definido"] = {"util_gib": have, "pct": usable_need / have * 100 if have else 999,
                           "ok": have >= usable_need, "ram_ok": (hw.get("ram_gib") or 0) >= ram}
        if have < usable_need:
            out["avisos"].append(f"El PBS indicado tiene {have/1024:.1f} TiB útiles y se estiman {tib:.1f} TiB.")
        if (hw.get("ram_gib") or 0) < ram:
            out["avisos"].append(f"RAM del PBS por debajo de la recomendada ({ram} GiB para ZFS con {tib:.0f} TiB).")
    if p.get("offsite"):
        out["avisos"].append("Copia externa: un segundo PBS (otro CPD o proveedor) con la misma capacidad y job de sincronización (sync job).")
    return out
