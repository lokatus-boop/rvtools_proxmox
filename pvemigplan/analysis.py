"""Análisis de la situación actual a partir del inventario."""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from .loader import num, yes

GIB_PER_TIB = 1024

OS_FAMILY = {
    "l26": "Linux", "l24": "Linux (kernel 2.4)", "win11": "Windows 11 / Server 2022-2025", "win10": "Windows 10 / Server 2016-2019",
    "win8": "Windows 8 / Server 2012", "win7": "Windows 7 / Server 2008 R2", "w2k8": "Windows Vista / Server 2008",
    "w2k3": "Windows XP / Server 2003", "wxp": "Windows XP / Server 2003", "w2k": "Windows 2000", "wvista": "Windows Vista / Server 2008",
    "solaris": "Solaris", "other": "Otro",
}
LEGACY_OS = {"l24", "w2k", "wxp", "w2k3", "w2k8", "wvista", "win7", "win8"}
CT_OS = {"debian", "ubuntu", "centos", "fedora", "opensuse", "archlinux", "alpine", "gentoo", "nixos", "devuan", "unmanaged"}


@dataclass
class Guest:
    cluster: str
    node: str
    vmid: str
    name: str
    kind: str  # VM / CT
    running: bool
    template: bool
    vcpu: float
    ram_gib: float
    disk_prov_gib: float
    disk_used_gib: float | None
    ostype: str
    guest_os: str
    ha: bool
    pool: str
    tags: str
    snapshots: int
    passthrough: str
    bios: str
    cpu_type: str = ""
    cpu_use_pct: float | None = None
    mem_use_pct: float | None = None
    startup_order: str = ""
    onboot: bool = False
    nics: list = field(default_factory=list)          # [(bridge, vlan)]
    storages: list = field(default_factory=list)      # [(storage, GiB)]
    cdrom_iso: list = field(default_factory=list)
    lock: str = ""
    last_backup: str = ""
    unprivileged: bool = False
    agent: bool = False

    @property
    def key(self):
        return f"{self.cluster}/{self.vmid}"

    @property
    def os_label(self):
        if self.kind == "CT":
            return f"Linux CT ({self.ostype})" if self.ostype else "Linux CT"
        return OS_FAMILY.get(self.ostype, self.ostype or "Desconocido")

    @property
    def os_family(self):
        if self.kind == "CT":
            return "Linux (CT)"
        if self.ostype.startswith("w"):
            return "Windows"
        if self.ostype.startswith("l"):
            return "Linux"
        return "Otros"

    @property
    def disk_effective_gib(self):
        """Ocupación real si se conoce; si no, el tamaño aprovisionado."""
        if self.disk_used_gib:
            return min(self.disk_used_gib, self.disk_prov_gib) if self.disk_prov_gib else self.disk_used_gib
        return self.disk_prov_gib


@dataclass
class Host:
    cluster: str
    node: str
    online: bool
    pve_version: str
    cpu_model: str
    sockets: int
    cores: int
    threads: int
    mhz: float
    cpu_use_pct: float
    ram_gib: float
    ram_used_gib: float

    @property
    def vendor(self):
        m = self.cpu_model.lower()
        return "AMD" if "amd" in m else ("Intel" if "intel" in m or "xeon" in m else "")


class Analysis:
    def __init__(self, sheets: dict, include_stopped=True, include_templates=False, exclude: set | None = None):
        self.sheets = sheets
        self.exclude = exclude or set()
        self.all_guests = self._guests()
        self.guests = [g for g in self.all_guests
                       if (include_templates or not g.template)
                       and (include_stopped or g.running or g.template)
                       and g.key not in self.exclude]
        self.hosts = self._hosts()
        self.clusters = sorted({g.cluster for g in self.all_guests} | {h.cluster for h in self.hosts})

    # -------------------------------------------------------------- parsing
    def _guests(self):
        sh = self.sheets
        by_key = lambda rows: {(r.get("Clúster"), str(r.get("VMID"))): r for r in rows}  # noqa: E731
        cpu, mem = by_key(sh.get("vCPU", [])), by_key(sh.get("vMemory", []))
        nets, stor, cds = defaultdict(list), defaultdict(lambda: defaultdict(float)), defaultdict(list)
        for r in sh.get("vNetwork", []):
            nets[(r.get("Clúster"), str(r.get("VMID")))].append((r.get("Bridge") or "?", str(num(r.get("VLAN"), "") or "")))
        for r in sh.get("vDisk", []):
            if yes(r.get("Sin usar")):
                continue
            stor[(r.get("Clúster"), str(r.get("VMID")))][r.get("Almacenamiento") or "?"] += num(r.get("Tamaño (GiB)"), 0) or 0
        for r in sh.get("vCD", []):
            m = str(r.get("Medio") or "")
            if m and m not in ("none", "cdrom") and ":" in m:
                cds[(r.get("Clúster"), str(r.get("VMID")))].append(m)
        out = []
        for r in sh.get("vInfo", []):
            k = (r.get("Clúster"), str(r.get("VMID")))
            c, m = cpu.get(k, {}), mem.get(k, {})
            out.append(Guest(
                cluster=str(r.get("Clúster") or "?"), node=str(r.get("Nodo") or "?"), vmid=str(r.get("VMID")),
                name=str(r.get("Nombre") or r.get("VMID")), kind="CT" if str(r.get("Tipo")).upper().startswith("CT") else "VM",
                running=str(r.get("Estado") or "").lower() == "running", template=yes(r.get("Plantilla")),
                vcpu=num(r.get("vCPU"), 1) or 1, ram_gib=(num(r.get("Memoria (MiB)"), 0) or 0) / 1024,
                disk_prov_gib=num(r.get("Disco aprovisionado (GiB)"), 0) or 0, disk_used_gib=num(r.get("Disco usado (GiB)")),
                ostype=str(r.get("Tipo SO") or ""), guest_os=str(r.get("SO invitado (agente)") or ""),
                ha=bool(r.get("HA")) and str(r.get("HA")).lower() not in ("no", "ignored"),
                pool=str(r.get("Pool") or ""), tags=str(r.get("Etiquetas") or ""),
                snapshots=int(num(r.get("Snapshots"), 0) or 0), passthrough=str(r.get("Passthrough") or ""),
                bios=str(r.get("BIOS") or ""), cpu_type=str(c.get("Tipo CPU") or ""),
                cpu_use_pct=num(c.get("Uso CPU (%)")), mem_use_pct=num(m.get("Uso memoria (%)")),
                startup_order=str(r.get("Orden arranque") or ""), onboot=yes(r.get("Arranque automático")),
                nics=nets.get(k, []), storages=sorted(stor.get(k, {}).items()), cdrom_iso=cds.get(k, []),
                lock=str(r.get("Bloqueo") or ""), last_backup=str(r.get("Último backup") or ""),
                unprivileged=yes(r.get("Sin privilegios")), agent=yes(r.get("Agente QEMU")),
            ))
        return out

    def _hosts(self):
        out = []
        for r in self.sheets.get("vHost", []):
            out.append(Host(
                cluster=str(r.get("Clúster") or "?"), node=str(r.get("Nodo") or "?"),
                online=str(r.get("Estado") or "").lower() == "online", pve_version=str(r.get("Versión PVE") or ""),
                cpu_model=str(r.get("Modelo CPU") or ""), sockets=int(num(r.get("Sockets"), 0) or 0),
                cores=int(num(r.get("Cores"), 0) or 0), threads=int(num(r.get("Hilos"), 0) or 0),
                mhz=num(r.get("MHz"), 0) or 0, cpu_use_pct=num(r.get("Uso CPU (%)"), 0) or 0,
                ram_gib=num(r.get("RAM total (GiB)"), 0) or 0, ram_used_gib=num(r.get("RAM usada (GiB)"), 0) or 0,
            ))
        return out

    # -------------------------------------------------------------- totals
    def totals(self) -> dict:
        g = self.guests
        run = [x for x in g if x.running]
        return {
            "vms": sum(1 for x in g if x.kind == "VM"), "cts": sum(1 for x in g if x.kind == "CT"),
            "running": len(run), "stopped": len(g) - len(run),
            "vcpu": sum(x.vcpu for x in g), "vcpu_running": sum(x.vcpu for x in run),
            "ram_gib": sum(x.ram_gib for x in g), "ram_running_gib": sum(x.ram_gib for x in run),
            "disk_prov_gib": sum(x.disk_prov_gib for x in g), "disk_eff_gib": sum(x.disk_effective_gib for x in g),
            "disk_used_known": sum(1 for x in g if x.disk_used_gib),
            "excluded": len(self.all_guests) - len(g),
            "hosts": len(self.hosts), "clusters": len(self.clusters),
            "host_cores": sum(h.cores for h in self.hosts), "host_threads": sum(h.threads for h in self.hosts),
            "host_ram_gib": sum(h.ram_gib for h in self.hosts), "host_ram_used_gib": sum(h.ram_used_gib for h in self.hosts),
            "host_sockets": sum(h.sockets for h in self.hosts),
        }

    def observed_cpu_cores(self) -> float:
        """Cores físicos efectivamente consumidos (uso CPU de cada nodo × cores)."""
        return sum(h.cores * h.cpu_use_pct / 100 for h in self.hosts)

    def by_cluster(self) -> list[dict]:
        rows = []
        for c in self.clusters:
            gs = [g for g in self.guests if g.cluster == c]
            hs = [h for h in self.hosts if h.cluster == c]
            rows.append({"Clúster / nodo": c, "Nodos": len(hs), "Versión PVE": ", ".join(sorted({h.pve_version for h in hs if h.pve_version})),
                         "VMs": sum(1 for g in gs if g.kind == "VM"), "CTs": sum(1 for g in gs if g.kind == "CT"),
                         "Encendidas": sum(1 for g in gs if g.running), "vCPU": sum(g.vcpu for g in gs),
                         "RAM asignada (GiB)": round(sum(g.ram_gib for g in gs), 1),
                         "Disco aprov. (GiB)": round(sum(g.disk_prov_gib for g in gs), 1),
                         "Cores físicos": sum(h.cores for h in hs), "RAM física (GiB)": round(sum(h.ram_gib for h in hs), 1)})
        return rows

    def os_distribution(self) -> Counter:
        return Counter(g.os_family for g in self.guests)

    def os_detail(self) -> Counter:
        return Counter(g.os_label for g in self.guests)

    def size_buckets(self) -> dict:
        b = {"≤2 vCPU": 0, "3-4 vCPU": 0, "5-8 vCPU": 0, "9-16 vCPU": 0, ">16 vCPU": 0}
        for g in self.guests:
            v = g.vcpu
            k = "≤2 vCPU" if v <= 2 else "3-4 vCPU" if v <= 4 else "5-8 vCPU" if v <= 8 else "9-16 vCPU" if v <= 16 else ">16 vCPU"
            b[k] += 1
        return b

    def storage_usage(self) -> list[dict]:
        """Almacenamientos únicos (los compartidos solo una vez) con su uso y tipo."""
        seen, rows = {}, []
        for r in self.sheets.get("vDatastore", []):
            shared = yes(r.get("Compartido"))
            key = (r.get("Clúster"), r.get("Almacenamiento")) if shared else (r.get("Clúster"), r.get("Nodo"), r.get("Almacenamiento"))
            if key in seen:
                continue
            seen[key] = True
            rows.append({"Clúster": r.get("Clúster"), "Nodo": "(compartido)" if shared else r.get("Nodo"),
                         "Almacenamiento": r.get("Almacenamiento"), "Tipo": r.get("Tipo"), "Compartido": "Sí" if shared else "No",
                         "Contenido": r.get("Contenido"), "Total (GiB)": num(r.get("Total (GiB)"), 0) or 0,
                         "Usado (GiB)": num(r.get("Usado (GiB)"), 0) or 0, "Uso (%)": num(r.get("Uso (%)"), 0) or 0})
        return rows

    def guest_storage_by_type(self) -> dict:
        """GiB de discos de VMs por tipo de almacenamiento de origen (rbd, zfspool, lvmthin, nfs…)."""
        types = {}
        for r in self.sheets.get("vDatastore", []):
            types[(r.get("Clúster"), r.get("Almacenamiento"))] = r.get("Tipo") or "?"
        out = defaultdict(float)
        for g in self.guests:
            for st, gib in g.storages:
                out[types.get((g.cluster, st), "?")] += gib
        return dict(out)

    # -------------------------------------------------------------- network
    def vlan_usage(self) -> list[dict]:
        """VLANs/bridges usados por las VMs del alcance."""
        use = defaultdict(lambda: {"vms": set(), "clusters": set()})
        for g in self.guests:
            for br, vlan in g.nics:
                k = (br, vlan or "")
                use[k]["vms"].add(g.key)
                use[k]["clusters"].add(g.cluster)
        sdn = {}
        for r in self.sheets.get("vSDN", []):
            if r.get("VNet"):
                sdn[r.get("VNet")] = r
        rows = []
        for (br, vlan), d in sorted(use.items(), key=lambda kv: (kv[0][0], int(kv[0][1]) if kv[0][1].isdigit() else -1)):
            s = sdn.get(br)
            rows.append({"bridge": br, "vlan": vlan, "vms": len(d["vms"]), "clusters": sorted(d["clusters"]),
                         "sdn": bool(s), "sdn_tag": str(num(s.get("Tag / VNI"), "") or "") if s else "",
                         "subnet": s.get("Subred") if s else "", "zone": s.get("Zona") if s else ""})
        return rows

    def host_networks(self) -> list[dict]:
        rows = []
        for r in self.sheets.get("vBridge", []):
            rows.append({"Clúster": r.get("Clúster"), "Nodo": r.get("Nodo"), "Bridge": r.get("Bridge"),
                         "Puertos": r.get("Puertos"), "CIDR": r.get("CIDR"), "VLAN aware": r.get("VLAN aware"),
                         "MTU": r.get("MTU")})
        return rows

    def subnets(self) -> list[str]:
        out = set()
        for r in self.sheets.get("vBridge", []) + self.sheets.get("vHostVLAN", []) + self.sheets.get("vHostNIC", []):
            c = r.get("CIDR")
            if c and "/" in str(c):
                ip, pre = str(c).split("/")[:2]
                parts = ip.split(".")
                if len(parts) == 4 and pre.isdigit() and int(pre) >= 8:
                    p = int(pre)
                    n = sum(int(x) << (24 - 8 * i) for i, x in enumerate(parts)) & ((0xFFFFFFFF << (32 - p)) & 0xFFFFFFFF)
                    out.add(".".join(str((n >> (24 - 8 * i)) & 255) for i in range(4)) + f"/{p}")
        return sorted(out)

    def mtu_jumbo(self) -> bool:
        return any((num(r.get("MTU"), 0) or 0) > 1500 for r in self.sheets.get("vHostNIC", []))

    def has_ceph(self) -> bool:
        return bool(self.sheets.get("vCephOSD")) or any(str(r.get("Tipo")) in ("rbd", "cephfs") for r in self.sheets.get("vDatastore", []))

    def backup_summary(self) -> dict:
        bs = self.sheets.get("vBackupStatus", [])
        keys = {g.key for g in self.guests}
        rel = [r for r in bs if f"{r.get('Clúster')}/{r.get('VMID')}" in keys]
        with_bk = [r for r in rel if (num(r.get("Nº copias"), 0) or 0) > 0]
        last_sizes = [num(r.get("Tamaño último (GiB)"), 0) or 0 for r in with_bk]
        stores = Counter()
        for r in with_bk:
            if r.get("Almacenamiento"):
                stores[r.get("Almacenamiento")] += 1
        types = {r.get("Almacenamiento"): r.get("Tipo") for r in self.sheets.get("vDatastore", [])}
        return {"with_backup": len({(r.get('Clúster'), r.get('VMID')) for r in with_bk}),
                "without_backup": len(self.guests) - len({(r.get('Clúster'), r.get('VMID')) for r in with_bk}),
                "last_total_gib": sum(last_sizes), "stores": dict(stores),
                "uses_pbs": any(t == "pbs" for t in types.values()), "jobs": len(self.sheets.get("vBackup", []))}

    def health_counts(self) -> Counter:
        return Counter(str(r.get("Severidad") or "") for r in self.sheets.get("vHealth", []))

    def pve_versions(self) -> list[str]:
        return sorted({h.pve_version for h in self.hosts if h.pve_version}, key=_vkey)

    def cpu_vendors(self) -> set:
        return {h.vendor for h in self.hosts if h.vendor}

    def max_guest(self) -> tuple[float, float]:
        return (max((g.vcpu for g in self.guests), default=0), max((g.ram_gib for g in self.guests), default=0))


def _vkey(v):
    return tuple(int(x) if x.isdigit() else 0 for x in re.split(r"[.\-]", v))
