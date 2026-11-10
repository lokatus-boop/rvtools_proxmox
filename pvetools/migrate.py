"""Planificador de migración entre entornos Proxmox VE (solo lectura).

Compara el inventario de origen con el de destino, comprueba cada VM/CT, propone el
método de migración y genera los comandos para que el administrador los revise y ejecute.
No ejecuta nada contra ningún servidor.
"""
from __future__ import annotations

import datetime as dt
import os
import re
from collections import defaultdict

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

from . import APP_NAME, __version__
from .collector import parse_kv

BLOQUEO, AVISO, INFO = "BLOQUEO", "AVISO", "INFO"
SEV_ORDER = {BLOQUEO: 0, AVISO: 1, INFO: 2}
NET_RE = re.compile(r"^net\d+$")
QEMU_DISK_RE = re.compile(r"^(scsi|virtio|sata|ide)\d+$|^efidisk\d+$|^tpmstate\d+$")
LXC_DISK_RE = re.compile(r"^rootfs$|^mp\d+$")
MAC_RE = re.compile(r"^[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5}$")
TOKEN_ID_DEFAULT = "migracion@pve!migra"

METHODS = [
    ("remote-migrate en caliente", "qm remote-migrate --online",
     "La VM sigue encendida y se copia por la red al otro clúster (disco + memoria). Corte de segundos. "
     "Requiere PVE ≥ 7.3 en ambos lados y un API token en destino. Proxmox la marca como experimental."),
    ("remote-migrate en frío", "qm/pct remote-migrate",
     "Igual que la anterior pero con la VM/CT apagada. Corte = tiempo de copia de los discos."),
    ("remote-migrate con reinicio (CT)", "pct remote-migrate --restart",
     "Los contenedores no se migran en caliente: se apagan, se copian y se arrancan en destino."),
    ("Backup y restauración vía PBS compartido", "vzdump → qmrestore / pct restore",
     "Backup en origen a un Proxmox Backup Server que también ve el destino, y restauración allí. "
     "Muy fiable; con 'live-restore' la VM arranca mientras se restaura."),
    ("Backup y restauración (vzdump)", "vzdump + copia del fichero + qmrestore / pct restore",
     "Sin PBS común: backup a fichero, copiarlo al destino (scp/NFS) y restaurar. El más sencillo, con más corte."),
    ("Replicación de almacenamiento", "zfs send/recv, rbd export-diff/mirror",
     "Para discos muy grandes: sincronización incremental del almacenamiento y luego mover la configuración. Manual."),
    ("Ampliar el clúster", "pvecm add + migración en caliente dentro del clúster",
     "Si los nodos de destino están vacíos y en la misma red: unirlos al clúster actual, migrar en caliente "
     "y retirar los nodos antiguos. Lo más limpio en una renovación de hardware."),
]


# ============================================================================ utilidades
def _target_label(tgt_sheets):
    labels = [c["Clúster / nodo"] for c in tgt_sheets["vCluster"]]
    return labels[0] if labels else None


def _content_ok(row, kind):
    content = str(row.get("Contenido") or "")
    return ("images" in content) if kind == "qemu" else ("rootdir" in content)


def _cpu_vendor(model):
    m = str(model or "").lower()
    return "amd" if "amd" in m else "intel" if "intel" in m else None


def _ver_tuple(v):
    return tuple(int(x) for x in re.findall(r"\d+", str(v or ""))[:3]) or (0,)


class MigrationPlan:
    def __init__(self, src, tgt, target_host: str, options: dict | None = None):
        """src / tgt: objetos Inventory ya recolectados (sheets + raw)."""
        o = options or {}
        self.src, self.tgt = src, tgt
        self.target_host = target_host
        self.target_node = o.get("target_node") or None  # None = automático
        self.storage_map = dict(o.get("storage_map") or {})
        self.bridge_map = dict(o.get("bridge_map") or {})
        self.vmids = set(int(v) for v in o.get("vmids") or []) or None
        self.keep_vmid = o.get("keep_vmid", True)
        self.bandwidth_gbps = float(o.get("bandwidth_gbps") or 1.0)
        self.token_id = o.get("token_id") or TOKEN_ID_DEFAULT
        self.include_templates = o.get("include_templates", True)
        self.include_stopped = o.get("include_stopped", True)
        self.tlabel = _target_label(tgt.sheets)
        self.rows, self.checks, self.capacity, self.mappings = [], [], [], []
        self.pre_steps: dict = defaultdict(list)
        self.remote_cmds: dict = defaultdict(list)
        self.backup_cmds: dict = defaultdict(list)

    # ------------------------------------------------------------------ destino
    def target_nodes(self):
        return [h for h in self.tgt.sheets["vHost"] if h["Clúster"] == self.tlabel and h["Estado"] == "online"]

    def target_storages(self, node=None):
        rows = [s for s in self.tgt.sheets["vDatastore"] if s["Clúster"] == self.tlabel and s["Estado"] == "available"]
        return [s for s in rows if node is None or s["Nodo"] == node]

    def target_bridges(self, node=None):
        br = {b["Bridge"]: b for b in self.tgt.sheets["vBridge"] if b["Clúster"] == self.tlabel and (node is None or b["Nodo"] == node)}
        for v in self.tgt.sheets["vSDN"]:
            if v["Clúster"] == self.tlabel and v.get("VNet") and not str(v["VNet"]).startswith("("):
                br.setdefault(v["VNet"], {"Bridge": v["VNet"], "VLAN aware": v.get("VLAN aware"), "SDN": True})
        return br

    def source_storages_used(self):
        used = set()
        for d in self.src.sheets["vDisk"]:
            if d["Sin usar"] == "No" and d["Almacenamiento"]:
                used.add(d["Almacenamiento"])
        return sorted(used)

    def source_bridges_used(self):
        return sorted({n["Bridge"] for n in self.src.sheets["vNetwork"] if n["Bridge"]})

    def auto_maps(self):
        """Rellena los mapeos no indicados: mismo nombre si existe; si no, el de más espacio libre / vmbr0."""
        tst = {}
        for s in self.target_storages():
            cur = tst.get(s["Almacenamiento"])
            if not cur or (s["Libre (GiB)"] or 0) > (cur["Libre (GiB)"] or 0):
                tst[s["Almacenamiento"]] = s
        images = sorted([s for s in tst.values() if _content_ok(s, "qemu")], key=lambda s: -(s["Libre (GiB)"] or 0))
        for src in self.source_storages_used():
            if src in self.storage_map:
                continue
            if src in tst and (_content_ok(tst[src], "qemu") or _content_ok(tst[src], "lxc")):
                self.storage_map[src] = src
            elif images:
                self.storage_map[src] = images[0]["Almacenamiento"]
        tbr = self.target_bridges()
        for src in self.source_bridges_used():
            if src in self.bridge_map:
                continue
            if src in tbr:
                self.bridge_map[src] = src
            elif "vmbr0" in tbr:
                self.bridge_map[src] = "vmbr0"
            elif tbr:
                self.bridge_map[src] = sorted(tbr)[0]
        return self.storage_map, self.bridge_map

    # ------------------------------------------------------------------ plan
    def build(self):
        self.auto_maps()
        tnodes = self.target_nodes()
        if not tnodes:
            raise ValueError("El destino no tiene nodos online")
        ram_free = {h["Nodo"]: (h["RAM total (GiB)"] or 0) - (h["RAM usada (GiB)"] or 0) for h in tnodes}
        node_info = {h["Nodo"]: h for h in tnodes}
        tgt_version = max((_ver_tuple(h["Versión PVE"]) for h in tnodes), default=(0,))
        used_vmids = {int(v["VMID"]) for v in self.tgt.sheets["vInfo"]}
        next_free = [max([99] + list(used_vmids)) + 1]
        # libre por almacenamiento destino (clave: (nodo|*compartido, storage))
        st_free, st_total = {}, {}
        for s in self.target_storages():
            key = ("*", s["Almacenamiento"]) if s["Compartido"] == "Sí" else (s["Nodo"], s["Almacenamiento"])
            st_free[key] = s["Libre (GiB)"] or 0
            st_total[key] = s["Total (GiB)"] or 0
        st_need = defaultdict(float)
        tgt_pbs = {(c.get("server"), c.get("datastore")): sid for sid, c in
                   (self.tgt.raw_storage_cfg.get(self.tlabel) or {}).items() if c.get("type") == "pbs"}
        disks_by_vm = defaultdict(list)
        for d in self.src.sheets["vDisk"]:
            disks_by_vm[(d["Clúster"], d["VMID"])].append(d)
        nics_by_vm = defaultdict(list)
        for n in self.src.sheets["vNetwork"]:
            nics_by_vm[(n["Clúster"], n["VMID"])].append(n)
        pt_by_vm = defaultdict(list)
        for p in self.src.sheets["vPassthrough"]:
            pt_by_vm[(p["Clúster"], p["VMID"])].append(p)
        cd_by_vm = defaultdict(list)
        for c in self.src.sheets["vCD"]:
            cd_by_vm[(c["Clúster"], c["VMID"])].append(c)
        snaps = defaultdict(int)
        for s in self.src.sheets["vSnapshot"]:
            snaps[(s["Clúster"], s["VMID"])] += 1
        repl = defaultdict(list)
        for r in self.src.sheets["vReplication"]:
            repl[(r["Clúster"], str(r["VMID"]))].append(r["Job"])
        src_hosts = {(h["Clúster"], h["Nodo"]): h for h in self.src.sheets["vHost"]}
        src_shared_storage = {(s["Clúster"], s["Almacenamiento"]) for s in self.src.sheets["vDatastore"] if s["Compartido"] == "Sí"}

        for v in sorted(self.src.sheets["vInfo"], key=lambda x: (x["Clúster"], x["VMID"])):
            vmid, label = int(v["VMID"]), v["Clúster"]
            if self.vmids and vmid not in self.vmids:
                continue
            if v["Plantilla"] == "Sí" and not self.include_templates:
                continue
            if v["Estado"] != "running" and not self.include_stopped:
                continue
            raw = self.src.raw.get((label, v["VMID"])) or {}
            cfg, kind = raw.get("config") or {}, raw.get("type") or ("qemu" if v["Tipo"] == "VM" else "lxc")
            cmd = "qm" if kind == "qemu" else "pct"
            checks = []

            def chk(sev, msg, _c=checks, _v=v):
                _c.append((sev, msg))
                self.checks.append({"Severidad": sev, "Origen": _v["Clúster"], "VMID": _v["VMID"],
                                    "Nombre": _v["Nombre"], "Tipo": _v["Tipo"], "Comprobación": msg})

            mem_gib = (v["Memoria (MiB)"] or 0) / 1024
            running = v["Estado"] == "running"
            # --- nodo destino
            if self.target_node and self.target_node in ram_free:
                tnode = self.target_node
            else:
                tnode = max(ram_free, key=ram_free.get)
            if running and ram_free[tnode] < mem_gib:
                chk(AVISO, f"RAM libre en {tnode} insuficiente ({ram_free[tnode]:.1f} GiB libres, necesita {mem_gib:.1f} GiB)")
            if running:
                ram_free[tnode] -= mem_gib
            # --- VMID
            if self.keep_vmid and vmid not in used_vmids:
                new_id = vmid
            else:
                while next_free[0] in used_vmids:
                    next_free[0] += 1
                new_id = next_free[0]
                if self.keep_vmid:
                    chk(AVISO, f"El VMID {vmid} ya existe en destino: se usará {new_id}")
            used_vmids.add(new_id)
            # --- discos y almacenamiento
            size = 0.0
            st_pairs = {}
            for d in disks_by_vm[(label, v["VMID"])]:
                if d["Sin usar"] == "Sí":
                    chk(INFO, f"Disco sin usar {d['Volumen']}: no se migra (bórralo o adjúntalo antes)")
                    continue
                vol = str(d["Volumen"] or "")
                if not d["Almacenamiento"]:
                    if vol.startswith("/dev/"):
                        chk(BLOQUEO, f"{d['Disco']} es un disco físico pasado directamente ({vol}): no se puede migrar automáticamente")
                    elif kind == "lxc" and vol.startswith("/"):
                        chk(AVISO, f"{d['Disco']} es un bind mount ({vol}): no se copia, recréalo en destino")
                    continue
                dst = self.storage_map.get(d["Almacenamiento"])
                if not dst:
                    chk(BLOQUEO, f"Sin almacenamiento destino para '{d['Almacenamiento']}'")
                    continue
                st_pairs[d["Almacenamiento"]] = dst
                trow = next((s for s in self.target_storages(tnode) if s["Almacenamiento"] == dst), None)
                if not trow:
                    chk(BLOQUEO, f"El almacenamiento destino '{dst}' no está disponible en el nodo {tnode}")
                    continue
                if not _content_ok(trow, kind):
                    chk(BLOQUEO, f"El almacenamiento '{dst}' no admite {'discos de VM (images)' if kind == 'qemu' else 'contenedores (rootdir)'}")
                gib = d["Tamaño (GiB)"] or 0
                size += gib
                key = ("*", dst) if trow["Compartido"] == "Sí" else (tnode, dst)
                st_need[key] += gib
                if st_need[key] > st_free.get(key, 0):
                    chk(BLOQUEO, f"No cabe en '{dst}': se necesitan {st_need[key]:.0f} GiB acumulados y hay {st_free.get(key, 0):.0f} GiB libres")
            # --- red
            br_pairs = {}
            tbr = self.target_bridges(tnode)
            for n in nics_by_vm[(label, v["VMID"])]:
                b = n["Bridge"]
                if not b:
                    continue
                dst = self.bridge_map.get(b)
                if not dst or dst not in tbr:
                    chk(BLOQUEO, f"{n['Interfaz']}: no existe el bridge destino para '{b}' en {tnode}")
                    continue
                br_pairs[b] = dst
                if n["VLAN"] and tbr[dst].get("VLAN aware") == "No" and not tbr[dst].get("SDN"):
                    chk(AVISO, f"{n['Interfaz']} usa la VLAN {n['VLAN']} pero el bridge destino '{dst}' no es VLAN aware")
            # --- otros
            if v.get("Bloqueo"):
                chk(BLOQUEO, f"La {v['Tipo']} está bloqueada ({v['Bloqueo']}): desbloquéala ({cmd} unlock {vmid}) cuando termine la operación en curso")
            pts = [p for p in pt_by_vm[(label, v["VMID"])] if p["Tipo"] in ("PCI", "USB", "Dispositivo LXC")]
            unmapped = [p for p in pts if p["Mapeado"] != "Sí"]
            if unmapped:
                chk(AVISO, "Passthrough sin mapping (" + ", ".join(p["Clave"] for p in unmapped) +
                    "): no se puede migrar en caliente; quítalo antes y vuelve a configurarlo en destino")
            elif pts:
                chk(AVISO, "Usa resource mappings de PCI/USB: créalos con el mismo nombre en el destino")
            for c in cd_by_vm[(label, v["VMID"])]:
                if c["Conectado"] == "Sí":
                    chk(AVISO, f"ISO montada en {c['Dispositivo']} ({c['Medio']}): desmóntala antes de migrar")
                    self.pre_steps[label].append(f"qm set {vmid} --{c['Dispositivo']} none,media=cdrom   # desmontar ISO")
            if snaps[(label, v["VMID"])]:
                chk(AVISO, f"Tiene {snaps[(label, v['VMID'])]} snapshot(s): remote-migrate puede rechazarla según el "
                           "almacenamiento y un backup no las conserva. Consolídalas o elimínalas antes")
            if v.get("HA"):
                chk(AVISO, "Está en HA: quítala de HA antes de migrar y vuelve a añadirla en destino")
                self.pre_steps[label].append(f"ha-manager remove {'vm' if kind == 'qemu' else 'ct'}:{vmid}")
            for job in repl[(label, str(vmid))]:
                chk(AVISO, f"Tiene replicación ({job}): elimina el job antes de migrar")
                self.pre_steps[label].append(f"pvesr delete {job}")
            if v.get("Pool"):
                chk(INFO, f"Pertenece al pool '{v['Pool']}': los pools no se migran, añádela en destino")
            src_h = src_hosts.get((label, v["Nodo"]), {})
            dst_h = node_info.get(tnode, {})
            online_ok = kind == "qemu" and running
            if kind == "qemu" and str(cfg.get("cpu", "")).split(",")[0] == "host":
                sv, dv = _cpu_vendor(src_h.get("Modelo CPU")), _cpu_vendor(dst_h.get("Modelo CPU"))
                if sv and dv and sv != dv:
                    chk(AVISO, f"CPU tipo 'host' y fabricantes distintos ({src_h.get('Modelo CPU')} → {dst_h.get('Modelo CPU')}): "
                               "no se puede en caliente; migra en frío o cambia el tipo de CPU (p. ej. x86-64-v2-AES)")
                    online_ok = False
                elif src_h.get("Modelo CPU") != dst_h.get("Modelo CPU"):
                    chk(AVISO, f"CPU tipo 'host' con modelos distintos ({src_h.get('Modelo CPU')} → {dst_h.get('Modelo CPU')}): "
                               "la migración en caliente puede fallar")
            if unmapped:
                online_ok = False
            src_ver = _ver_tuple(src_h.get("Versión PVE"))
            if src_ver > tgt_version:
                chk(AVISO, f"El destino tiene una versión de PVE más antigua ({'.'.join(map(str, tgt_version))}) que el origen "
                           f"({src_h.get('Versión PVE')}): actualiza el destino antes")
            if min(src_ver[:2], tgt_version[:2]) < (7, 3):
                chk(BLOQUEO, "remote-migrate requiere PVE 7.3 o superior en origen y destino")
            if v["Plantilla"] == "Sí":
                chk(INFO, "Es una plantilla: se recomienda backup y restauración")

            # --- método
            blockers = [m for s, m in checks if s == BLOQUEO]
            src_pbs = [(sid, c) for sid, c in (self.src.raw_storage_cfg.get(label) or {}).items()
                       if c.get("type") == "pbs" and (c.get("server"), c.get("datastore")) in tgt_pbs]
            if blockers:
                method = "Manual (resolver bloqueos)"
            elif v["Plantilla"] == "Sí" or unmapped:
                method = "Backup y restauración vía PBS compartido" if src_pbs else "Backup y restauración (vzdump)"
            elif kind == "qemu":
                method = "remote-migrate en caliente" if online_ok else "remote-migrate en frío"
            else:
                method = "remote-migrate con reinicio (CT)" if running else "remote-migrate en frío"
            alt = "Backup y restauración vía PBS compartido" if src_pbs else "Backup y restauración (vzdump)"
            secs = size * 8 * 1.074 / (self.bandwidth_gbps * 0.7) if size else 0
            mins = round(secs / 60, 1)
            if method == "remote-migrate en caliente":
                downtime = "Segundos (conmutación final)"
            elif method == "remote-migrate con reinicio (CT)":
                downtime = f"≈ {mins} min + reinicio"
            elif method.startswith("Manual"):
                downtime = "—"
            else:
                downtime = f"≈ {mins} min (copia) " + ("+ restauración" if method.startswith("Backup") else "")

            # --- comandos
            endpoint = f'"$ENDPOINT_{re.sub(r"[^A-Za-z0-9]", "_", tnode)}"'
            st_arg = ",".join(f"{a}:{b}" for a, b in sorted(st_pairs.items()))
            br_arg = ",".join(f"{a}:{b}" for a, b in sorted(br_pairs.items()))
            remote = f"{cmd} remote-migrate {vmid} {new_id} {endpoint}"
            if br_arg:
                remote += f" --target-bridge {br_arg}"
            if st_arg:
                remote += f" --target-storage {st_arg}"
            if method == "remote-migrate en caliente":
                remote += " --online"
            elif method == "remote-migrate con reinicio (CT)":
                remote += " --restart"
            backup = self._backup_commands(v, kind, vmid, new_id, cfg, st_pairs, br_pairs, src_pbs, tgt_pbs, tnode,
                                           src_shared_storage)
            header = f"# {v['Tipo']} {vmid} '{v['Nombre']}' ({label} / {v['Nodo']}) -> {tnode} como {new_id} — {method}"
            if blockers:
                note = "# BLOQUEADA: " + " | ".join(blockers) + "\n# "
            elif method.startswith("Backup"):
                note = "# Método recomendado: backup y restauración (ver el otro script). Alternativa:\n# "
            else:
                note = ""
            self.remote_cmds[(label, v["Nodo"])].append(f"{header}\n{note}{remote}\n")
            self.backup_cmds[(label, v["Nodo"])].append(f"{header}\n" + "\n".join(backup) + "\n")

            worst = min((SEV_ORDER[s] for s, _ in checks), default=9)
            self.rows.append({
                "Origen": label, "Nodo origen": v["Nodo"], "VMID": vmid, "Nombre": v["Nombre"], "Tipo": v["Tipo"],
                "Estado": v["Estado"], "Plantilla": v["Plantilla"],
                "Resultado": {0: "BLOQUEADA", 1: "Con avisos", 2: "OK"}.get(worst, "OK"),
                "Método recomendado": method, "Alternativa": alt if not method.startswith("Backup") else "remote-migrate en frío",
                "Nodo destino": tnode, "VMID destino": new_id, "vCPU": v["vCPU"], "Memoria (GiB)": round(mem_gib, 2),
                "Datos a copiar (GiB)": round(size, 2), f"Tiempo copia @{self.bandwidth_gbps:g} Gbit/s (min)": mins,
                "Corte estimado": downtime,
                "Mapeo almacenamiento": ", ".join(f"{a}→{b}" for a, b in sorted(st_pairs.items())) or None,
                "Mapeo red": ", ".join(f"{a}→{b}" for a, b in sorted(br_pairs.items())) or None,
                "Bloqueos": len(blockers), "Avisos": len([1 for s, _ in checks if s == AVISO]),
                "Comando": remote,
            })

        for key, need in sorted(st_need.items()):
            free, total = st_free.get(key, 0), st_total.get(key, 0)
            self.capacity.append({
                "Tipo": "Almacenamiento", "Nodo": "(compartido)" if key[0] == "*" else key[0], "Recurso": key[1],
                "Necesario (GiB)": round(need, 1), "Libre actual (GiB)": round(free, 1),
                "Libre después (GiB)": round(free - need, 1),
                "Uso después (%)": round(100 * (total - free + need) / total, 1) if total else None,
                "Resultado": "NO CABE" if need > free else ("Justo (>85%)" if total and (total - free + need) / total > 0.85 else "OK"),
            })
        for n in tnodes:
            assigned = sum(r["Memoria (GiB)"] for r in self.rows if r["Nodo destino"] == n["Nodo"] and r["Estado"] == "running")
            free = (n["RAM total (GiB)"] or 0) - (n["RAM usada (GiB)"] or 0)
            vcpus = sum(r["vCPU"] or 0 for r in self.rows if r["Nodo destino"] == n["Nodo"] and r["Estado"] == "running")
            self.capacity.append({
                "Tipo": "RAM", "Nodo": n["Nodo"], "Recurso": f"{n['RAM total (GiB)']} GiB",
                "Necesario (GiB)": round(assigned, 1), "Libre actual (GiB)": round(free, 1),
                "Libre después (GiB)": round(free - assigned, 1),
                "Uso después (%)": round(100 * ((n["RAM total (GiB)"] or 0) - free + assigned) / n["RAM total (GiB)"], 1) if n["RAM total (GiB)"] else None,
                "Resultado": "NO CABE" if assigned > free else "OK",
                "vCPU añadidas": vcpus, "Hilos nodo": n.get("Hilos"),
            })
        for a, b in sorted(self.storage_map.items()):
            self.mappings.append({"Tipo": "Almacenamiento", "Origen": a, "Destino": b})
        for a, b in sorted(self.bridge_map.items()):
            self.mappings.append({"Tipo": "Red (bridge/VNet)", "Origen": a, "Destino": b})
        self.checks.sort(key=lambda c: (SEV_ORDER[c["Severidad"]], c["Origen"], c["VMID"]))
        return self

    def _backup_commands(self, v, kind, vmid, new_id, cfg, st_pairs, br_pairs, src_pbs, tgt_pbs, tnode, src_shared):
        cmd_restore = "qmrestore {arch} {new}" if kind == "qemu" else "pct restore {new} {arch}"
        dst_storage = sorted(set(st_pairs.values()))[0] if st_pairs else "local-lvm"
        out = []
        if src_pbs:
            sid, c = src_pbs[0]
            tsid = tgt_pbs[(c.get("server"), c.get("datastore"))]
            out.append(f"vzdump {vmid} --storage {sid} --mode {'snapshot' if v['Estado'] == 'running' else 'stop'}")
            out.append(f"# En el destino ({tnode}): localiza la copia con  pvesm list {tsid} --vmid {vmid}")
            arch = f"{tsid}:backup/{'vm' if kind == 'qemu' else 'ct'}/{vmid}/<FECHA>"
            restore = cmd_restore.format(arch=arch, new=new_id) + f" --storage {dst_storage}"
            if kind == "qemu":
                restore += "   # añade --live-restore 1 para arrancarla mientras se restaura"
            out.append(f"# [destino] {restore}")
        else:
            ext = "vma.zst" if kind == "qemu" else "tar.zst"
            typ = "qemu" if kind == "qemu" else "lxc"
            out.append(f"vzdump {vmid} --dumpdir /var/lib/vz/dump --compress zstd --mode {'snapshot' if v['Estado'] == 'running' else 'stop'}")
            out.append(f"scp /var/lib/vz/dump/vzdump-{typ}-{vmid}-*.{ext} root@<IP_{tnode}>:/var/lib/vz/dump/")
            arch = f"/var/lib/vz/dump/vzdump-{typ}-{vmid}-<FECHA>.{ext}"
            out.append(f"# [destino] {cmd_restore.format(arch=arch, new=new_id)} --storage {dst_storage}")
        if len(set(st_pairs.values())) > 1:
            out.append(f"# Nota: discos en varios almacenamientos destino ({', '.join(sorted(set(st_pairs.values())))}); "
                       "tras restaurar, muévelos con  qm disk move / pct move-volume")
        net_cmd = "qm set" if kind == "qemu" else "pct set"
        for k in sorted(cfg):
            if not NET_RE.match(k):
                continue
            n = parse_kv(cfg[k])
            b = n.get("bridge")
            if b and br_pairs.get(b) and br_pairs[b] != b:
                new_val = re.sub(r"(^|,)bridge=[^,]*", rf"\1bridge={br_pairs[b]}", cfg[k])
                out.append(f"# [destino] {net_cmd} {new_id} --{k} '{new_val}'")
        return out

    # ------------------------------------------------------------------ salida
    def summary(self):
        total = len(self.rows)
        by = defaultdict(int)
        for r in self.rows:
            by[r["Método recomendado"]] += 1
        res = defaultdict(int)
        for r in self.rows:
            res[r["Resultado"]] += 1
        return {
            "VMs/CTs en el plan": total, "OK": res["OK"], "Con avisos": res["Con avisos"], "Bloqueadas": res["BLOQUEADA"],
            "Datos a copiar (GiB)": round(sum(r["Datos a copiar (GiB)"] for r in self.rows), 1),
            "Destino": f"{self.tlabel} ({self.target_host})",
            **{f"Método: {k}": v for k, v in sorted(by.items())},
        }

    def endpoints(self):
        """Variables ENDPOINT por nodo destino (host = IP del nodo, huella de su certificado)."""
        lines = []
        certs = defaultdict(dict)
        for c in self.tgt.sheets["vCert"]:
            if c["Clúster"] == self.tlabel:
                certs[c["Nodo"]][c["Fichero"]] = c["Huella SHA256"]
        for n in self.target_nodes():
            fp = certs[n["Nodo"]].get("pveproxy-ssl.pem") or certs[n["Nodo"]].get("pve-ssl.pem") or "<HUELLA_SHA256>"
            var = re.sub(r"[^A-Za-z0-9]", "_", n["Nodo"])
            host = n.get("IP") or self.target_host
            lines.append(f'ENDPOINT_{var}="apitoken=PVEAPIToken=${{TOKEN_ID}}=${{TOKEN_SECRET}},host={host},fingerprint={fp}"')
        return lines

    def write(self, folder: str):
        os.makedirs(folder, exist_ok=True)
        stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        xlsx = os.path.join(folder, f"plan_migracion_{stamp}.xlsx")
        self._write_xlsx(xlsx)
        remote = os.path.join(folder, f"migracion_remote_{stamp}.sh")
        backup = os.path.join(folder, f"migracion_backup_restore_{stamp}.sh")
        self._write_script(remote, self.remote_cmds, remote=True)
        self._write_script(backup, self.backup_cmds, remote=False)
        return [xlsx, remote, backup]

    def _script_header(self, remote: bool):
        h = [
            "#!/bin/bash",
            f"# Generado por {APP_NAME} {__version__} el {dt.datetime.now():%Y-%m-%d %H:%M}",
            f"# Plan de migración hacia {self.tlabel} ({self.target_host}). REVISA CADA COMANDO ANTES DE EJECUTARLO.",
            "# Lanza los comandos uno a uno en el nodo de ORIGEN indicado en cada bloque",
            "# (las líneas '# [destino]' se ejecutan en el nodo destino).",
            "",
            "echo 'Este script es una guía: revísalo y ejecuta los comandos uno a uno.'; exit 1",
            "",
        ]
        if remote:
            h += [
                "# 1) En el DESTINO crea un token temporal con permisos para crear VMs (bórralo al terminar):",
                "#    pveum user add migracion@pve --comment 'Migración temporal'",
                "#    pveum acl modify / -user migracion@pve -role Administrator",
                "#    pveum user token add migracion@pve migra --privsep 0      # copia el secreto",
                "# 2) Rellena TOKEN_SECRET y comprueba las huellas (pvenode cert info en cada nodo destino).",
                "# 3) remote-migrate es una función 'experimental' de Proxmox: prueba primero con una VM no crítica.",
                "",
                f'TOKEN_ID="{self.token_id}"',
                'TOKEN_SECRET="PEGAR_AQUI_EL_SECRETO"',
                *self.endpoints(),
                "",
            ]
        return h

    def _write_script(self, path, cmds, remote: bool):
        lines = self._script_header(remote)
        for label, steps in self.pre_steps.items():
            lines.append(f"# ===== Pasos previos en {label} =====")
            lines += list(dict.fromkeys(steps))
            lines.append("")
        for (label, node), blocks in sorted(cmds.items()):
            lines.append(f"# ===================== Ejecutar en {label} / nodo {node} =====================")
            lines += blocks
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(lines) + "\n")

    def _write_xlsx(self, path):
        from .export import HEADER_FILL, HEADER_FONT, _notice_sheet, columns
        wb = Workbook()
        _notice_sheet(wb.active)
        fills = {"BLOQUEADA": "F8CBAD", "BLOQUEO": "F8CBAD", "NO CABE": "F8CBAD", "Con avisos": "FFE699",
                 "AVISO": "FFE699", "Justo (>85%)": "FFE699", "OK": "E2EFDA", "INFO": "DDEBF7"}
        summary = [{"Concepto": k, "Valor": v} for k, v in self.summary().items()]
        methods = [{"Método": a, "Comando": b, "Descripción": c} for a, b, c in METHODS]
        for name, rows, sevcol in (("Resumen", summary, None), ("Plan", self.rows, "Resultado"),
                                   ("Comprobaciones", self.checks, "Severidad"), ("Capacidad", self.capacity, "Resultado"),
                                   ("Mapeos", self.mappings, None), ("Métodos", methods, None)):
            ws = wb.create_sheet(name)
            cols = columns(rows) or ["(sin datos)"]
            ws.append(cols)
            for r in rows:
                ws.append([r.get(c) for c in cols])
            for cell in ws[1]:
                cell.fill, cell.font = HEADER_FILL, HEADER_FONT
            ws.freeze_panes = "A2"
            ws.auto_filter.ref = ws.dimensions
            for i, c in enumerate(cols, 1):
                width = max([len(str(c))] + [len(str(r.get(c) or "")) for r in rows[:300]])
                ws.column_dimensions[ws.cell(1, i).column_letter].width = min(max(width + 2, 8), 70)
            if name == "Métodos":
                for row in ws.iter_rows(min_row=2):
                    row[2].alignment = Alignment(wrap_text=True, vertical="top")
                ws.column_dimensions["C"].width = 100
            if sevcol:
                idx = cols.index(sevcol)
                for row in ws.iter_rows(min_row=2):
                    color = fills.get(row[idx].value)
                    if color:
                        row[idx].fill = PatternFill("solid", fgColor=color)
                        row[idx].font = Font(bold=True)
        wb.save(path)
