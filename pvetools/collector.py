"""Recolecta el inventario de uno o varios clústeres / nodos Proxmox VE.

Devuelve un dict ordenado {nombre_hoja: [filas(dict)]}, al estilo de RVTools.
"""
from __future__ import annotations

import datetime as dt
import re
import time
from concurrent.futures import ThreadPoolExecutor

from . import __version__
from . import extras
from .schema import FORMAT_VERSION
from .api import PVEClient, PVEError, q

SHEETS = ["vInfo", "vCPU", "vMemory", "vDisk", "vCD", "vNetwork", "vSnapshot", "vPassthrough",
          "vBackupStatus", "vHost", "vHostNIC", "vBond", "vBridge", "vHostVLAN", "vSDN", "vCorosync",
          "vDatastore", "vPhysicalDisk", "vZFS", "vCephOSD", "vCephPool", "vCluster", "vHA", "vBackup",
          "vReplication", "vFirewall", "vFirewallObj", "vUsers", "vACL", "vRepo", "vCert", "vTasks",
          "vHealth", "vSource"]

# Agrupación para la navegación de la GUI
SHEET_GROUPS = [
    ("Máquinas virtuales", ["vInfo", "vCPU", "vMemory", "vDisk", "vCD", "vNetwork", "vSnapshot", "vPassthrough", "vBackupStatus"]),
    ("Hosts", ["vHost", "vPhysicalDisk", "vRepo", "vCert"]),
    ("Red", ["vHostNIC", "vBond", "vBridge", "vHostVLAN", "vSDN", "vCorosync"]),
    ("Almacenamiento", ["vDatastore", "vZFS", "vCephOSD", "vCephPool"]),
    ("Clúster", ["vCluster", "vHA", "vBackup", "vReplication", "vTasks"]),
    ("Seguridad", ["vFirewall", "vFirewallObj", "vUsers", "vACL"]),
    ("Resumen", ["vHealth", "vSource"]),
]

SNAPSHOT_AGE_WARN_DAYS = 7
STORAGE_WARN, STORAGE_CRIT = 80, 90
MAC_RE = re.compile(r"^[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5}$")
QEMU_DISK_RE = re.compile(r"^(scsi|virtio|sata|ide)\d+$|^efidisk\d+$|^tpmstate\d+$|^unused\d+$")
LXC_DISK_RE = re.compile(r"^rootfs$|^mp\d+$|^unused\d+$")
NET_RE = re.compile(r"^net\d+$")


# --------------------------------------------------------------------------- utilidades
def parse_kv(value: str, first_key: str | None = None) -> dict:
    """'local-lvm:vm-100-disk-0,size=32G,ssd=1' -> {first_key: 'local-lvm:...', 'size': '32G', ...}"""
    out = {}
    for i, part in enumerate(str(value).split(",")):
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = v.strip()
        elif i == 0 and first_key:
            out[first_key] = part.strip()
    return out


def size_to_gib(s) -> float | None:
    if s in (None, ""):
        return None
    m = re.match(r"^\s*([\d.]+)\s*([KMGTP]?)", str(s), re.I)
    if not m:
        return None
    n = float(m.group(1))
    unit = m.group(2).upper()
    factor = {"": 1 / 1024 ** 3, "K": 1 / 1024 ** 2, "M": 1 / 1024, "G": 1, "T": 1024, "P": 1024 ** 2}[unit]
    return round(n * factor, 3)


def b2gib(b) -> float | None:
    return None if b in (None, "") else round(float(b) / 1024 ** 3, 2)


def b2mib(b) -> float | None:
    return None if b in (None, "") else round(float(b) / 1024 ** 2, 0)


def pct(used, total) -> float | None:
    try:
        return round(100.0 * float(used) / float(total), 1) if float(total) else None
    except (TypeError, ValueError):
        return None


def ts(epoch) -> str | None:
    try:
        return dt.datetime.fromtimestamp(int(epoch)).strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError, OSError):
        return None


def uptime_str(sec) -> str | None:
    try:
        sec = int(sec)
    except (TypeError, ValueError):
        return None
    if sec <= 0:
        return None
    d, rem = divmod(sec, 86400)
    h, rem = divmod(rem, 3600)
    return f"{d}d {h:02d}h {rem // 60:02d}m"


def flag(v) -> str:
    return "Sí" if str(v) in ("1", "True", "true", "yes", "on") else "No"


def agent_enabled(cfg: dict) -> bool:
    a = str(cfg.get("agent", "0"))
    return a.startswith("1") or "enabled=1" in a


# --------------------------------------------------------------------------- recolector
class Inventory:
    def __init__(self, progress=None, query_agent: bool = True, workers: int = 8):
        self.sheets = {name: [] for name in SHEETS}
        self.progress = progress or (lambda msg: None)
        self.query_agent = query_agent
        self.workers = workers
        self._seen_clusters: set[str] = set()
        self._seen_nodes: set[str] = set()
        self._dc_firewall: dict = {}
        self._ceph: dict = {}

    # ---------------------------------------------------------------- entrada
    def collect(self, connections: list[dict]):
        """connections: lista de kwargs para PVEClient (host, user, password|token_id+token_secret, verify_ssl)."""
        for conn in connections:
            host = conn["host"]
            started = time.time()
            src = {"Host conectado": host, "Usuario": conn.get("user"),
                   "Autenticación": "API token" if conn.get("token_id") else "Contraseña",
                   "Fecha": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                   "Versión herramienta": __version__, "Versión formato": FORMAT_VERSION}
            try:
                self.progress(f"Conectando a {host}…")
                api = PVEClient(**conn)
                ver = api.get("version")
                src["Versión PVE"] = ver.get("version")
                cluster_name, skipped = self._collect_one(api, host)
                src["Clúster / nodo"] = cluster_name
                src["Estado"] = "Omitido (ya inventariado por otra conexión)" if skipped else "OK"
            except PVEError as e:
                src["Estado"] = f"ERROR: {e}"
                self.progress(f"Error en {host}: {e}")
            except Exception as e:  # noqa: BLE001 - nunca abortar el inventario completo
                src["Estado"] = f"ERROR inesperado: {type(e).__name__}: {e}"
                self.progress(f"Error inesperado en {host}: {e}")
            src["Duración (s)"] = round(time.time() - started, 1)
            self.sheets["vSource"].append(src)
        self._health()
        self.progress("Inventario completado")
        return self.sheets

    # ---------------------------------------------------------------- por clúster/nodo
    def _collect_one(self, api: PVEClient, host: str):
        status = api.try_get("cluster/status", [])
        cl = next((s for s in status if s.get("type") == "cluster"), None)
        nodes_status = [s for s in status if s.get("type") == "node"]
        if cl:
            cname = cl.get("name")
            if cname in self._seen_clusters:
                return cname, True
            self._seen_clusters.add(cname)
        else:
            nodes = api.try_get("nodes", [])
            cname = nodes[0]["node"] if nodes else host
            if cname in self._seen_nodes:
                return cname, True
        label = cname if cl else f"{cname} (standalone)"

        resources = api.get("cluster/resources")
        nodes = [r for r in resources if r.get("type") == "node"]
        guests = [r for r in resources if r.get("type") in ("qemu", "lxc")]
        storages = [r for r in resources if r.get("type") == "storage"]
        for n in nodes:
            self._seen_nodes.add(n.get("node"))
        self.progress(f"{label}: {len(nodes)} nodo(s), {len(guests)} VM/CT, {len(storages)} almacenamiento(s)")

        ha = {r.get("sid"): r for r in api.try_get("cluster/ha/resources", [])}
        guest_rows = self._guests(api, label, guests, ha)
        self._hosts(api, label, nodes, nodes_status, guest_rows)
        self._storages(api, label, storages)
        self._cluster(api, label, cl, nodes, guests, storages, host)
        self._ha(api, label, ha)
        self._backup(api, label)
        self._replication(api, label)
        steps = [("SDN", lambda: extras.sdn(self, api, label)),
                 ("corosync", lambda: extras.corosync(self, api, label, bool(cl))),
                 ("firewall", lambda: extras.firewall(self, api, label, nodes)),
                 ("usuarios y permisos", lambda: extras.access(self, api, label)),
                 ("Ceph", lambda: extras.ceph(self, api, label, nodes)),
                 ("estado de backups", lambda: extras.backup_status(self, api, label, storages, guest_rows)),
                 ("tareas", lambda: extras.tasks(self, api, label))]
        for name, fn in steps:
            self.progress(f"{label}: {name}…")
            try:
                fn()
            except Exception as e:  # noqa: BLE001 - una sección opcional nunca aborta el inventario
                self.progress(f"{label}: no se pudo leer {name}: {e}")
        return label, False

    # ---------------------------------------------------------------- VMs y CTs
    def _guests(self, api, label, guests, ha):
        total = len(guests)
        done = [0]

        def work(g):
            res = self._guest(api, label, g, ha)
            done[0] += 1
            if done[0] % 10 == 0 or done[0] == total:
                self.progress(f"{label}: VMs/CTs {done[0]}/{total}")
            return res

        with ThreadPoolExecutor(max_workers=self.workers) as ex:
            results = list(ex.map(work, sorted(guests, key=lambda g: g.get("vmid", 0))))
        rows = []
        for r in results:
            for sheet, items in r.items():
                self.sheets[sheet].extend(items)
            rows.extend(r["vInfo"])
        return rows

    def _guest(self, api, label, g, ha):
        node, vmid, kind = g.get("node"), g.get("vmid"), g.get("type")
        base = f"nodes/{q(node)}/{kind}/{vmid}"
        cfg = api.try_get(f"{base}/config", {}) if g.get("status") != "unknown" else {}
        running = g.get("status") == "running"
        name = g.get("name") or cfg.get("name") or cfg.get("hostname")
        key = {"Clúster": label, "Nodo": node, "VMID": vmid, "Nombre": name, "Tipo": "VM" if kind == "qemu" else "CT"}
        out = {s: [] for s in ("vInfo", "vCPU", "vMemory", "vDisk", "vCD", "vNetwork", "vSnapshot", "vPassthrough")}
        for k in sorted(cfg):
            ptype = "PCI" if re.match(r"^hostpci\d+$", k) else "USB" if re.match(r"^usb\d+$", k) else \
                "Serie" if re.match(r"^serial\d+$", k) else "Dispositivo LXC" if re.match(r"^dev\d+$", k) else None
            if not ptype:
                continue
            d = parse_kv(cfg[k], first_key="host")
            dev = d.get("host") or d.get("path") or cfg[k]
            mapped = "mapping" in d
            out["vPassthrough"].append({
                "Clúster": label, "Nodo": node, "VMID": vmid, "Nombre": g.get("name") or cfg.get("name") or cfg.get("hostname"),
                "Tipo VM": "VM" if kind == "qemu" else "CT", "Clave": k, "Tipo": ptype,
                "Dispositivo": d.get("mapping") or dev, "Mapeado": "Sí" if mapped else ("N/A" if ptype == "Serie" else "No"),
                "PCIe": flag(d.get("pcie")) if ptype == "PCI" else None, "ROM-Bar": d.get("rombar"),
                "GPU principal": flag(d.get("x-vga")) if ptype == "PCI" else None, "Config": cfg[k],
            })
        fw = api.try_get(f"{base}/firewall/options", {}) if g.get("status") != "unknown" else {}

        # --- agente / interfaces del invitado
        guest_os = hostname = None
        ips_by_mac: dict[str, list[str]] = {}
        agent_ok = None
        if kind == "qemu" and running and self.query_agent and agent_enabled(cfg):
            ifs = api.try_get(f"{base}/agent/network-get-interfaces")
            agent_ok = ifs is not None
            for i in (ifs or {}).get("result", []) or []:
                mac = (i.get("hardware-address") or "").lower()
                for a in i.get("ip-addresses", []) or []:
                    ip = a.get("ip-address", "")
                    if ip and not ip.startswith(("127.", "::1", "fe80")):
                        ips_by_mac.setdefault(mac, []).append(ip)
            if agent_ok:
                osi = (api.try_get(f"{base}/agent/get-osinfo") or {}).get("result") or {}
                guest_os = osi.get("pretty-name") or osi.get("name")
                hostname = ((api.try_get(f"{base}/agent/get-host-name") or {}).get("result") or {}).get("host-name")
        elif kind == "lxc" and running:
            for i in api.try_get(f"{base}/interfaces", []) or []:
                mac = (i.get("hwaddr") or "").lower()
                for k in ("inet", "inet6"):
                    ip = (i.get(k) or "").split("/")[0]
                    if ip and not ip.startswith(("127.", "::1", "fe80")):
                        ips_by_mac.setdefault(mac, []).append(ip)
            hostname = cfg.get("hostname")

        # --- discos y CD-ROM
        disk_total = 0.0
        disk_re = QEMU_DISK_RE if kind == "qemu" else LXC_DISK_RE
        for k in sorted(cfg):
            if not disk_re.match(k):
                continue
            d = parse_kv(cfg[k], first_key="volume")
            vol = d.get("volume") or d.get("file", "")
            if d.get("media") == "cdrom":
                out["vCD"].append({**key, "Dispositivo": k, "Medio": vol,
                                   "Conectado": "No" if vol in ("none", "") else "Sí"})
                continue
            storage = vol.split(":", 1)[0] if ":" in vol else ""
            gib = size_to_gib(d.get("size"))
            if not k.startswith("unused") and gib:
                disk_total += gib
            out["vDisk"].append({
                **key, "Disco": k, "Almacenamiento": storage, "Volumen": vol,
                "Tamaño (GiB)": gib, "Formato": d.get("format") or (vol.rsplit(".", 1)[-1] if vol.endswith((".qcow2", ".raw", ".vmdk")) else None),
                "Punto de montaje": d.get("mp") or ("/" if k == "rootfs" else None),
                "Caché": d.get("cache"), "Discard": d.get("discard"), "SSD": flag(d.get("ssd")),
                "IO thread": flag(d.get("iothread")), "Backup": "No" if d.get("backup") == "0" else "Sí",
                "Replicar": "No" if d.get("replicate") == "0" else "Sí",
                "Sin usar": "Sí" if k.startswith("unused") else "No",
            })

        # --- red
        all_ips = []
        for k in sorted(cfg):
            if not NET_RE.match(k):
                continue
            n = parse_kv(cfg[k])
            if kind == "qemu":
                model = next((m for m, v in n.items() if MAC_RE.match(v)), n.get("model"))
                mac = n.get(model) if model in n and MAC_RE.match(n.get(model, "")) else n.get("macaddr")
            else:
                model, mac = "veth", n.get("hwaddr")
            ips = ips_by_mac.get((mac or "").lower(), [])
            all_ips.extend(ips)
            out["vNetwork"].append({
                **key, "Interfaz": k, "Nombre en invitado": n.get("name"), "Modelo": model, "MAC": mac,
                "Bridge": n.get("bridge"), "VLAN": n.get("tag"), "Trunks": n.get("trunks"),
                "Firewall": flag(n.get("firewall")), "Desconectada": flag(n.get("link_down")),
                "MTU": n.get("mtu"), "Límite (MB/s)": n.get("rate"),
                "IP config": ", ".join(x for x in (n.get("ip"), n.get("ip6")) if x) or None,
                "IPs": ", ".join(ips) or None,
            })
        if not all_ips:  # fallback: IPs del agente aunque no casen por MAC
            all_ips = [ip for v in ips_by_mac.values() for ip in v]

        # --- snapshots
        for s in api.try_get(f"{base}/snapshot", []) or []:
            if s.get("name") == "current":
                continue
            age = round((time.time() - int(s["snaptime"])) / 86400, 1) if s.get("snaptime") else None
            out["vSnapshot"].append({**key, "Snapshot": s.get("name"), "Padre": s.get("parent"),
                                     "Descripción": (s.get("description") or "").strip() or None,
                                     "Fecha": ts(s.get("snaptime")), "Antigüedad (días)": age,
                                     "Con RAM": flag(s.get("vmstate"))})

        # --- CPU / memoria
        if kind == "qemu":
            sockets, cores = int(cfg.get("sockets", 1)), int(cfg.get("cores", 1))
            vcpus = int(cfg.get("vcpus") or sockets * cores)
        else:
            sockets, cores = 1, int(cfg.get("cores") or g.get("maxcpu") or 0)
            vcpus = cores
        mem_mib = int(cfg.get("memory") or b2mib(g.get("maxmem")) or 0)
        ha_entry = ha.get(f"{'vm' if kind == 'qemu' else 'ct'}:{vmid}")
        meta = parse_kv(cfg.get("meta", ""))

        out["vInfo"].append({
            **key, "Estado": g.get("status"), "Plantilla": flag(g.get("template")),
            "HA": ha_entry.get("state") if ha_entry else None, "Pool": g.get("pool"),
            "Etiquetas": (g.get("tags") or cfg.get("tags") or "").replace(";", ", ") or None,
            "Tipo SO": cfg.get("ostype"), "SO invitado (agente)": guest_os, "Hostname": hostname,
            "IPs": ", ".join(dict.fromkeys(all_ips)) or None,
            "vCPU": vcpus, "Memoria (MiB)": mem_mib, "Discos": len([d for d in out["vDisk"] if d["Sin usar"] == "No"]),
            "Disco aprovisionado (GiB)": round(disk_total, 2) or b2gib(g.get("maxdisk")),
            "Disco usado (GiB)": b2gib(g.get("disk")) if kind == "lxc" else None,
            "NICs": len(out["vNetwork"]), "Snapshots": len(out["vSnapshot"]),
            "Uptime": uptime_str(g.get("uptime")), "Arranque automático": flag(cfg.get("onboot")),
            "Orden arranque": cfg.get("startup"), "BIOS": cfg.get("bios", "seabios") if kind == "qemu" else None,
            "Máquina": cfg.get("machine") if kind == "qemu" else None,
            "Agente QEMU": ("Sí" if agent_enabled(cfg) else "No") if kind == "qemu" else None,
            "Agente responde": None if agent_ok is None else flag(agent_ok),
            "Sin privilegios": flag(cfg.get("unprivileged")) if kind == "lxc" else None,
            "Protección": flag(cfg.get("protection")), "Bloqueo": cfg.get("lock") or g.get("lock"),
            "Creada": ts(meta.get("ctime")),
            "Firewall VM": flag(fw.get("enable")) if fw else None,
            "Passthrough": len(out["vPassthrough"]) or None,
            "Descripción": (cfg.get("description") or "").strip().splitlines()[0][:200] if cfg.get("description") else None,
        })
        out["vCPU"].append({
            **key, "Estado": g.get("status"), "Sockets": sockets, "Cores": cores, "vCPU": vcpus,
            "Tipo CPU": (cfg.get("cpu") or "por defecto (kvm64)") if kind == "qemu" else None,
            "Límite CPU": cfg.get("cpulimit"), "CPU units": cfg.get("cpuunits"), "Afinidad": cfg.get("affinity"),
            "NUMA": flag(cfg.get("numa")) if kind == "qemu" else None,
            "Uso CPU (%)": round(float(g.get("cpu") or 0) * 100, 1) if running else None,
        })
        out["vMemory"].append({
            **key, "Estado": g.get("status"), "Memoria (MiB)": mem_mib,
            "Balloon mín. (MiB)": cfg.get("balloon") if kind == "qemu" else None,
            "Swap (MiB)": cfg.get("swap") if kind == "lxc" else None,
            "Shares": cfg.get("shares"), "Hugepages": cfg.get("hugepages"),
            "Memoria usada (MiB)": b2mib(g.get("mem")) if running else None,
            "Uso memoria (%)": pct(g.get("mem"), g.get("maxmem")) if running else None,
        })
        return out

    # ---------------------------------------------------------------- hosts
    def _hosts(self, api, label, nodes, nodes_status, guest_rows):
        ip_by_node = {s.get("name"): s.get("ip") for s in nodes_status}
        for n in sorted(nodes, key=lambda x: x.get("node", "")):
            name = n.get("node")
            online = n.get("status") == "online"
            st = api.try_get(f"nodes/{q(name)}/status", {}) if online else {}
            ver = api.try_get(f"nodes/{q(name)}/version", {}) if online else {}
            sub = api.try_get(f"nodes/{q(name)}/subscription", {}) if online else {}
            cpu = st.get("cpuinfo", {}) or {}
            mem = st.get("memory", {}) or {}
            swap = st.get("swap", {}) or {}
            rootfs = st.get("rootfs", {}) or {}
            mine = [g for g in guest_rows if g["Nodo"] == name]
            vcpu_assigned = sum(g["vCPU"] or 0 for g in mine if g["Estado"] == "running")
            ram_assigned = sum(g["Memoria (MiB)"] or 0 for g in mine if g["Estado"] == "running")
            threads = cpu.get("cpus") or n.get("maxcpu")
            boot = st.get("boot-info", {}) or {}
            self.sheets["vHost"].append({
                "Clúster": label, "Nodo": name, "Estado": n.get("status"), "IP": ip_by_node.get(name),
                "Versión PVE": ver.get("version"), "Release": ver.get("release"),
                "Kernel": st.get("kversion") or (st.get("current-kernel") or {}).get("release"),
                "Modelo CPU": cpu.get("model"), "Sockets": cpu.get("sockets"), "Cores": cpu.get("cores"),
                "Hilos": threads, "MHz": cpu.get("mhz"),
                "Uso CPU (%)": round(float(n.get("cpu") or 0) * 100, 1) if online else None,
                "RAM total (GiB)": b2gib(mem.get("total") or n.get("maxmem")),
                "RAM usada (GiB)": b2gib(mem.get("used") or n.get("mem")),
                "Uso RAM (%)": pct(mem.get("used") or n.get("mem"), mem.get("total") or n.get("maxmem")),
                "Swap total (GiB)": b2gib(swap.get("total")), "Swap usada (GiB)": b2gib(swap.get("used")),
                "Root FS (GiB)": b2gib(rootfs.get("total")), "Root FS uso (%)": pct(rootfs.get("used"), rootfs.get("total")),
                "Uptime": uptime_str(n.get("uptime")),
                "Load avg": ", ".join(str(x) for x in st.get("loadavg", [])) or None,
                "Arranque": boot.get("mode") + (" (Secure Boot)" if boot.get("secureboot") else "") if boot.get("mode") else None,
                "VMs": len([g for g in mine if g["Tipo"] == "VM" and g["Plantilla"] == "No"]),
                "CTs": len([g for g in mine if g["Tipo"] == "CT" and g["Plantilla"] == "No"]),
                "Encendidas": len([g for g in mine if g["Estado"] == "running"]),
                "vCPU asignadas (encendidas)": vcpu_assigned,
                "Ratio vCPU:hilo": round(vcpu_assigned / threads, 2) if threads else None,
                "RAM asignada encendidas (GiB)": round(ram_assigned / 1024, 2),
                "Suscripción": sub.get("status"), "Nivel suscripción": sub.get("level"),
            })
            if online:
                ifaces = api.try_get(f"nodes/{q(name)}/network", []) or []
                extras.network(self, label, name, ifaces)
                extras.node_hardware(self, api, label, name)
                extras.node_maintenance(self, api, label, name, self.sheets["vHost"][-1])
                for i in sorted(ifaces, key=lambda x: x.get("iface", "")):
                    self.sheets["vHostNIC"].append({
                        "Clúster": label, "Nodo": name, "Interfaz": i.get("iface"), "Tipo": i.get("type"),
                        "Activa": flag(i.get("active")), "Autostart": flag(i.get("autostart")),
                        "Método": i.get("method"), "CIDR": i.get("cidr") or i.get("address"),
                        "Gateway": i.get("gateway"), "CIDR IPv6": i.get("cidr6"),
                        "Puertos bridge": i.get("bridge_ports"), "VLAN aware": flag(i.get("bridge_vlan_aware")),
                        "Esclavos bond": i.get("slaves"), "Modo bond": i.get("bond_mode"),
                        "VLAN id": i.get("vlan-id"), "VLAN raw device": i.get("vlan-raw-device"),
                        "MTU": i.get("mtu"), "Comentario": (i.get("comments") or "").strip() or None,
                    })

    # ---------------------------------------------------------------- almacenamiento
    def _storages(self, api, label, storages):
        cfg = {s.get("storage"): s for s in api.try_get("storage", []) or []}
        for s in sorted(storages, key=lambda x: (x.get("storage", ""), x.get("node", ""))):
            c = cfg.get(s.get("storage"), {})
            self.sheets["vDatastore"].append({
                "Clúster": label, "Nodo": s.get("node"), "Almacenamiento": s.get("storage"),
                "Tipo": s.get("plugintype") or c.get("type"), "Estado": s.get("status"),
                "Compartido": flag(s.get("shared") if s.get("shared") is not None else c.get("shared")),
                "Contenido": s.get("content") or c.get("content"),
                "Total (GiB)": b2gib(s.get("maxdisk")), "Usado (GiB)": b2gib(s.get("disk")),
                "Libre (GiB)": b2gib((s.get("maxdisk") or 0) - (s.get("disk") or 0)) if s.get("maxdisk") else None,
                "Uso (%)": pct(s.get("disk"), s.get("maxdisk")),
                "Ruta / destino": c.get("path") or c.get("export") or c.get("pool") or c.get("vgname")
                or c.get("thinpool") or c.get("datastore") or c.get("share"),
                "Servidor": c.get("server") or c.get("portal") or c.get("monhost"),
                "Nodos permitidos": c.get("nodes"), "Deshabilitado": flag(c.get("disable")),
            })

    # ---------------------------------------------------------------- clúster
    def _cluster(self, api, label, cl, nodes, guests, storages, host):
        real = [g for g in guests if not g.get("template")]
        shared = {}
        for s in storages:
            key = s.get("storage") if s.get("shared") else f"{s.get('node')}/{s.get('storage')}"
            shared[key] = s
        self.sheets["vCluster"].append({
            "Clúster / nodo": label, "Tipo": "Clúster" if cl else "Nodo independiente",
            "Conectado vía": host, "Nodos": len(nodes),
            "Nodos online": len([n for n in nodes if n.get("status") == "online"]),
            "Quórum": (flag(cl.get("quorate")) if cl else "N/A"), "Versión config": cl.get("version") if cl else None,
            "VMs": len([g for g in real if g.get("type") == "qemu"]),
            "CTs": len([g for g in real if g.get("type") == "lxc"]),
            "Plantillas": len(guests) - len(real),
            "Encendidas": len([g for g in real if g.get("status") == "running"]),
            "Hilos CPU totales": sum(n.get("maxcpu") or 0 for n in nodes),
            "RAM total (GiB)": b2gib(sum(n.get("maxmem") or 0 for n in nodes)),
            "Almacenamiento total (GiB)": b2gib(sum(s.get("maxdisk") or 0 for s in shared.values())),
            "Almacenamiento usado (GiB)": b2gib(sum(s.get("disk") or 0 for s in shared.values())),
            "Ceph": "Sí" if any((s.get("plugintype") == "rbd") for s in storages) else "No",
        })

    def _ha(self, api, label, ha):
        for sid, r in sorted(ha.items()):
            self.sheets["vHA"].append({
                "Clúster": label, "Elemento": "Recurso", "Recurso": sid, "Estado solicitado": r.get("state"),
                "Grupo": r.get("group"), "Máx. reinicios": r.get("max_restart"),
                "Máx. reubicaciones": r.get("max_relocate"), "Fallback": r.get("failback"),
                "Comentario": r.get("comment"),
            })
        # PVE 8: grupos HA ; PVE 9: reglas HA (sustituyen a los grupos)
        for g in api.try_get("cluster/ha/groups", []) or []:
            self.sheets["vHA"].append({"Clúster": label, "Elemento": "Grupo (PVE 8)", "Recurso": g.get("group"),
                                       "Nodos": g.get("nodes"), "Restringido": flag(g.get("restricted")),
                                       "Fallback": "No" if g.get("nofailback") else "Sí", "Comentario": g.get("comment")})
        for rl in api.try_get("cluster/ha/rules", []) or []:
            self.sheets["vHA"].append({"Clúster": label, "Elemento": f"Regla {rl.get('type', '')} (PVE 9)".replace("  ", " "),
                                       "Recurso": rl.get("rule"), "Recursos afectados": rl.get("resources"),
                                       "Nodos": rl.get("nodes"), "Afinidad": rl.get("affinity"),
                                       "Habilitada": "No" if rl.get("disable") else "Sí", "Comentario": rl.get("comment")})

    def _backup(self, api, label):
        for j in api.try_get("cluster/backup", []) or []:
            if j.get("all"):
                sel = "Todas" + (f" excepto {j.get('exclude')}" if j.get("exclude") else "")
            elif j.get("pool"):
                sel = f"Pool {j.get('pool')}"
            else:
                sel = j.get("vmid")
            self.sheets["vBackup"].append({
                "Clúster": label, "Job": j.get("id"), "Habilitado": "No" if str(j.get("enabled", 1)) == "0" else "Sí",
                "Planificación": j.get("schedule") or (f"{j.get('dow')} {j.get('starttime')}" if j.get("starttime") else None),
                "Almacenamiento": j.get("storage"), "Modo": j.get("mode"), "Compresión": j.get("compress"),
                "Selección": sel, "Nodo": j.get("node"),
                "Retención": j.get("prune-backups") or (f"maxfiles={j['maxfiles']}" if j.get("maxfiles") else None),
                "Notificación": j.get("mailnotification") or j.get("notification-mode"),
                "Comentario": j.get("comment"),
            })
        self._not_backed_up = getattr(self, "_not_backed_up", [])
        for g in api.try_get("cluster/backup-info/not-backed-up", []) or []:
            self._not_backed_up.append((label, g))

    def _replication(self, api, label):
        for r in api.try_get("cluster/replication", []) or []:
            self.sheets["vReplication"].append({
                "Clúster": label, "Job": r.get("id"), "VMID": r.get("guest"), "Destino": r.get("target"),
                "Planificación": r.get("schedule", "*/15"), "Límite (MB/s)": r.get("rate"),
                "Habilitado": "No" if r.get("disable") else "Sí", "Comentario": r.get("comment"),
            })

    # ---------------------------------------------------------------- salud
    def _health(self):
        h = self.sheets["vHealth"]

        def add(sev, label, obj, msg):
            h.append({"Severidad": sev, "Clúster": label, "Objeto": obj, "Mensaje": msg})

        for c in self.sheets["vCluster"]:
            if c["Quórum"] == "No":
                add("CRÍTICO", c["Clúster / nodo"], "Clúster", "El clúster no tiene quórum")
        for n in self.sheets["vHost"]:
            obj = f"Nodo {n['Nodo']}"
            if n["Estado"] != "online":
                add("CRÍTICO", n["Clúster"], obj, f"Nodo en estado '{n['Estado']}'")
            if (n["Uso RAM (%)"] or 0) >= 90:
                add("AVISO", n["Clúster"], obj, f"Uso de RAM al {n['Uso RAM (%)']}%")
            if (n["Root FS uso (%)"] or 0) >= STORAGE_WARN:
                add("AVISO", n["Clúster"], obj, f"Disco raíz al {n['Root FS uso (%)']}%")
            if (n["Ratio vCPU:hilo"] or 0) > 4:
                add("INFO", n["Clúster"], obj, f"Sobreasignación de CPU {n['Ratio vCPU:hilo']}:1")
            if n["Estado"] == "online" and n["Suscripción"] and n["Suscripción"].lower() != "active":
                add("INFO", n["Clúster"], obj, f"Suscripción: {n['Suscripción']}")
        versions = {}
        for n in self.sheets["vHost"]:
            if n["Versión PVE"]:
                versions.setdefault(n["Clúster"], set()).add(n["Versión PVE"])
        for label, vs in versions.items():
            if len(vs) > 1:
                add("AVISO", label, "Clúster", f"Versiones de PVE mezcladas: {', '.join(sorted(vs))}")
        for s in self.sheets["vDatastore"]:
            u = s["Uso (%)"] or 0
            obj = f"Almacenamiento {s['Almacenamiento']} ({s['Nodo']})"
            if u >= STORAGE_CRIT:
                add("CRÍTICO", s["Clúster"], obj, f"Ocupado al {u}%")
            elif u >= STORAGE_WARN:
                add("AVISO", s["Clúster"], obj, f"Ocupado al {u}%")
            if s["Estado"] not in ("available", None) and s["Deshabilitado"] == "No":
                add("AVISO", s["Clúster"], obj, f"Estado '{s['Estado']}'")
        for s in self.sheets["vSnapshot"]:
            if (s["Antigüedad (días)"] or 0) > SNAPSHOT_AGE_WARN_DAYS:
                add("AVISO", s["Clúster"], f"{s['Tipo']} {s['VMID']} {s['Nombre']}",
                    f"Snapshot '{s['Snapshot']}' con {s['Antigüedad (días)']} días")
        for v in self.sheets["vInfo"]:
            obj = f"{v['Tipo']} {v['VMID']} {v['Nombre']}"
            if v["Tipo"] == "VM" and v["Estado"] == "running" and v["Agente QEMU"] == "No":
                add("INFO", v["Clúster"], obj, "Guest agent no habilitado")
            if v["Agente responde"] == "No":
                add("AVISO", v["Clúster"], obj, "Guest agent habilitado pero no responde")
            if v["Bloqueo"]:
                add("AVISO", v["Clúster"], obj, f"Bloqueada ({v['Bloqueo']})")
        for d in self.sheets["vDisk"]:
            if d["Sin usar"] == "Sí":
                add("INFO", d["Clúster"], f"{d['Tipo']} {d['VMID']} {d['Nombre']}", f"Disco sin usar {d['Volumen']}")
        for c in self.sheets["vCD"]:
            if c["Conectado"] == "Sí":
                add("INFO", c["Clúster"], f"{c['Tipo']} {c['VMID']} {c['Nombre']}", f"ISO montada: {c['Medio']}")
        for label, g in getattr(self, "_not_backed_up", []):
            add("AVISO", label, f"{'VM' if g.get('type') == 'qemu' else 'CT'} {g.get('vmid')} {g.get('name') or ''}".strip(),
                "No está incluida en ningún job de backup")
        extras.health(self, add)
        order = {"CRÍTICO": 0, "AVISO": 1, "INFO": 2}
        h.sort(key=lambda r: (order.get(r["Severidad"], 9), r["Clúster"] or "", r["Objeto"]))
