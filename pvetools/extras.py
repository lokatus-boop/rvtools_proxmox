"""Pestañas adicionales: red avanzada (bonds, bridges, VLAN, SDN, corosync), firewall,
usuarios/ACL, Ceph, discos físicos, ZFS, repositorios/actualizaciones, certificados,
estado de backups y tareas fallidas."""
from __future__ import annotations

import time
from collections import defaultdict

from .api import q

EXTRA_SHEETS = ["vBond", "vBridge", "vHostVLAN", "vSDN", "vCorosync", "vFirewall", "vFirewallObj",
                "vUsers", "vACL", "vCephOSD", "vCephPool", "vPhysicalDisk", "vZFS", "vPassthrough",
                "vRepo", "vCert", "vBackupStatus", "vTasks"]

BACKUP_AGE_WARN_DAYS = 7
CERT_WARN_DAYS = 30


def _b2gib(b):
    try:
        return round(float(b) / 1024 ** 3, 2)
    except (TypeError, ValueError):
        return None


def _flag(v):
    return "Sí" if str(v) in ("1", "True", "true", "yes", "on") else "No"


def _ts(epoch):
    import datetime as dt
    try:
        return dt.datetime.fromtimestamp(int(epoch)).strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError, OSError):
        return None


def _days_from_now(epoch):
    try:
        return round((int(epoch) - time.time()) / 86400, 1)
    except (TypeError, ValueError):
        return None


# ============================================================================ red
def network(inv, label, node, ifaces):
    """Bonds, bridges y VLANs del nodo, a partir de /nodes/{n}/network."""
    nics = [n for n in inv.sheets["vNetwork"] if n["Clúster"] == label and n["Nodo"] == node]
    for i in sorted(ifaces, key=lambda x: x.get("iface", "")):
        t, name = i.get("type"), i.get("iface")
        common = {"Clúster": label, "Nodo": node}
        if t == "bond":
            used_by = [b.get("iface") for b in ifaces
                       if b.get("type") in ("bridge", "OVSBridge") and name in str(b.get("bridge_ports", "")).split()]
            used_by += [v.get("iface") for v in ifaces if v.get("type") == "vlan" and v.get("vlan-raw-device") == name]
            inv.sheets["vBond"].append({
                **common, "Bond": name, "Modo": i.get("bond_mode"), "Esclavos": i.get("slaves"),
                "Nº esclavos": len(str(i.get("slaves") or "").split()),
                "Hash (xmit_hash_policy)": i.get("bond_xmit_hash_policy"), "Primario": i.get("bond-primary"),
                "Activo": _flag(i.get("active")), "MTU": i.get("mtu"), "CIDR": i.get("cidr"),
                "Usado por": ", ".join(used_by) or None, "Comentario": (i.get("comments") or "").strip() or None,
            })
        elif t in ("bridge", "OVSBridge"):
            on_bridge = [n for n in nics if n["Bridge"] == name]
            tags = sorted({str(n["VLAN"]) for n in on_bridge if n["VLAN"]}, key=lambda x: int(x) if x.isdigit() else 0)
            inv.sheets["vBridge"].append({
                **common, "Bridge": name, "Tipo": "Linux bridge" if t == "bridge" else "OVS bridge",
                "Puertos": i.get("bridge_ports") or i.get("ovs_ports"), "VLAN aware": _flag(i.get("bridge_vlan_aware")),
                "VLANs permitidas": i.get("bridge_vids"), "STP": i.get("bridge_stp"),
                "Activo": _flag(i.get("active")), "Método": i.get("method"), "CIDR": i.get("cidr"),
                "Gateway": i.get("gateway"), "CIDR IPv6": i.get("cidr6"), "MTU": i.get("mtu"),
                "NICs de VMs/CTs": len(on_bridge), "VLANs usadas por VMs": ", ".join(tags) or None,
                "Comentario": (i.get("comments") or "").strip() or None,
            })
        elif t in ("vlan", "OVSIntPort") or (t == "eth" and "." in str(name)):
            inv.sheets["vHostVLAN"].append({
                **common, "Interfaz": name, "VLAN id": i.get("vlan-id") or (str(name).rsplit(".", 1)[-1] if "." in str(name) else None),
                "Dispositivo base": i.get("vlan-raw-device") or (str(name).rsplit(".", 1)[0] if "." in str(name) else None),
                "Protocolo": i.get("vlan-protocol"), "Activo": _flag(i.get("active")), "CIDR": i.get("cidr"),
                "Gateway": i.get("gateway"), "MTU": i.get("mtu"), "Comentario": (i.get("comments") or "").strip() or None,
            })


def sdn(inv, api, label):
    zones = {z.get("zone"): z for z in api.try_get("cluster/sdn/zones", []) or []}
    vnets = api.try_get("cluster/sdn/vnets", []) or []
    used = set()
    for v in sorted(vnets, key=lambda x: x.get("vnet", "")):
        z = zones.get(v.get("zone"), {})
        used.add(v.get("zone"))
        subnets = api.try_get(f"cluster/sdn/vnets/{q(v.get('vnet'))}/subnets", []) or [{}]
        for s in subnets:
            dhcp = s.get("dhcp-range")
            if isinstance(dhcp, list):
                dhcp = ", ".join(f"{d.get('start-address')}-{d.get('end-address')}" if isinstance(d, dict) else str(d) for d in dhcp)
            inv.sheets["vSDN"].append({
                "Clúster": label, "Zona": v.get("zone"), "Tipo zona": z.get("type"), "Bridge zona": z.get("bridge"),
                "Nodos zona": z.get("nodes"), "MTU": z.get("mtu"), "IPAM": z.get("ipam"),
                "VNet": v.get("vnet"), "Alias": v.get("alias"), "Tag / VNI": v.get("tag"),
                "VLAN aware": _flag(v.get("vlanaware")), "Subred": s.get("cidr") or s.get("subnet"),
                "Gateway": s.get("gateway"), "SNAT": _flag(s.get("snat")) if s else None, "Rango DHCP": dhcp,
                "Pendiente de aplicar": "Sí" if (v.get("state") or z.get("state")) else "No",
            })
    for name, z in sorted(zones.items()):
        if name not in used:
            inv.sheets["vSDN"].append({"Clúster": label, "Zona": name, "Tipo zona": z.get("type"),
                                       "Bridge zona": z.get("bridge"), "Nodos zona": z.get("nodes"),
                                       "MTU": z.get("mtu"), "IPAM": z.get("ipam"), "VNet": "(sin VNets)"})


def corosync(inv, api, label, clustered):
    if not clustered:
        return
    totem = api.try_get("cluster/config/totem", {}) or {}
    for n in sorted(api.try_get("cluster/config/nodes", []) or [], key=lambda x: x.get("name", "")):
        links = {k: v for k, v in n.items() if k.startswith("ring") or k.startswith("link")}
        addrs = [f"{k.replace('_addr', '')}: {v}" for k, v in sorted(links.items())]
        inv.sheets["vCorosync"].append({
            "Clúster": label, "Nodo": n.get("name") or n.get("node"), "Node ID": n.get("nodeid"),
            "Votos": n.get("quorum_votes"), "Enlaces": len(links), "Direcciones": ", ".join(addrs) or None,
            "Modo enlaces": totem.get("link_mode"), "Versión config": totem.get("config_version"),
            "Secauth": totem.get("secauth"), "IP version": totem.get("ip_version"),
        })


# ============================================================================ seguridad
def firewall(inv, api, label, nodes):
    opts = api.try_get("cluster/firewall/options", {}) or {}
    inv._dc_firewall[label] = opts

    def rules(scope, path):
        for r in api.try_get(path, []) or []:
            inv.sheets["vFirewall"].append({
                "Clúster": label, "Ámbito": scope, "Pos": r.get("pos"), "Dirección": r.get("type"),
                "Acción": r.get("action"), "Macro": r.get("macro"), "Origen": r.get("source"),
                "Destino": r.get("dest"), "Protocolo": r.get("proto"), "Puerto destino": r.get("dport"),
                "Puerto origen": r.get("sport"), "Interfaz": r.get("iface"), "Log": r.get("log"),
                "Habilitada": _flag(r.get("enable")), "Comentario": r.get("comment"),
            })

    rules("Datacenter", "cluster/firewall/rules")
    for g in api.try_get("cluster/firewall/groups", []) or []:
        inv.sheets["vFirewallObj"].append({"Clúster": label, "Tipo": "Security group", "Nombre": g.get("group"),
                                           "Valor": None, "Comentario": g.get("comment")})
        rules(f"Grupo {g.get('group')}", f"cluster/firewall/groups/{q(g.get('group'))}")
    for a in api.try_get("cluster/firewall/aliases", []) or []:
        inv.sheets["vFirewallObj"].append({"Clúster": label, "Tipo": "Alias", "Nombre": a.get("name"),
                                           "Valor": a.get("cidr"), "Comentario": a.get("comment")})
    for s in api.try_get("cluster/firewall/ipset", []) or []:
        members = api.try_get(f"cluster/firewall/ipset/{q(s.get('name'))}", []) or []
        inv.sheets["vFirewallObj"].append({
            "Clúster": label, "Tipo": "IPSet", "Nombre": s.get("name"),
            "Valor": ", ".join(("!" if m.get("nomatch") else "") + str(m.get("cidr")) for m in members) or None,
            "Comentario": s.get("comment")})
    for n in nodes:
        if n.get("status") == "online":
            rules(f"Nodo {n.get('node')}", f"nodes/{q(n.get('node'))}/firewall/rules")


def access(inv, api, label):
    for u in sorted(api.try_get("access/users", [], full=1) or [], key=lambda x: x.get("userid", "")):
        inv.sheets["vUsers"].append({
            "Clúster": label, "Tipo": "Usuario", "ID": u.get("userid"), "Habilitado": _flag(u.get("enable", 1)),
            "Caduca": _ts(u.get("expire")) if u.get("expire") else "Nunca", "Nombre": " ".join(
                x for x in (u.get("firstname"), u.get("lastname")) if x) or None,
            "Email": u.get("email"), "Grupos": u.get("groups") if isinstance(u.get("groups"), str) else ", ".join(u.get("groups") or []) or None,
            "Realm": u.get("realm-type"), "Privilegios separados": None, "Comentario": u.get("comment"),
        })
        for t in u.get("tokens") or []:
            inv.sheets["vUsers"].append({
                "Clúster": label, "Tipo": "API token", "ID": f"{u.get('userid')}!{t.get('tokenid')}",
                "Habilitado": "Sí", "Caduca": _ts(t.get("expire")) if t.get("expire") else "Nunca",
                "Realm": u.get("realm-type"), "Privilegios separados": _flag(t.get("privsep", 1)),
                "Comentario": t.get("comment"),
            })
    for a in sorted(api.try_get("access/acl", []) or [], key=lambda x: (x.get("path", ""), x.get("ugid", ""))):
        inv.sheets["vACL"].append({
            "Clúster": label, "Ruta": a.get("path"), "Tipo": {"user": "Usuario", "group": "Grupo", "token": "Token"}.get(a.get("type"), a.get("type")),
            "Usuario / grupo": a.get("ugid"), "Rol": a.get("roleid"), "Propagar": _flag(a.get("propagate", 1)),
        })


# ============================================================================ almacenamiento / hardware
def ceph(inv, api, label, nodes):
    online = [n.get("node") for n in nodes if n.get("status") == "online"]
    if not online:
        return
    st = api.try_get("cluster/ceph/status")
    if not st:
        return
    health = (st.get("health") or {})
    inv._ceph[label] = {"status": health.get("status"),
                        "checks": {k: (v.get("summary") or {}).get("message") for k, v in (health.get("checks") or {}).items()}}
    node = online[0]
    tree = api.try_get(f"nodes/{q(node)}/ceph/osd", {}) or {}

    def walk(n, host=None):
        if n.get("type") == "host":
            host = n.get("name")
        if n.get("type") == "osd":
            inv.sheets["vCephOSD"].append({
                "Clúster": label, "Host": n.get("host") or host, "OSD": n.get("name"), "Estado": n.get("status"),
                "In": "Sí" if str(n.get("in", 1)) == "1" else "No", "Clase": n.get("device_class"),
                "Tipo": n.get("osdtype"), "Peso CRUSH": n.get("crush_weight"),
                "Tamaño (GiB)": _b2gib(n.get("total_space")), "Usado (GiB)": _b2gib(n.get("bytes_used")),
                "Uso (%)": round(float(n["percent_used"]), 1) if n.get("percent_used") is not None else None,
                "Latencia apply (ms)": n.get("apply_latency_ms"), "Latencia commit (ms)": n.get("commit_latency_ms"),
                "Versión": n.get("version"),
            })
        for c in n.get("children") or []:
            walk(c, host)

    if tree.get("root"):
        walk(tree["root"])
    for p in api.try_get(f"nodes/{q(node)}/ceph/pool", []) or api.try_get(f"nodes/{q(node)}/ceph/pools", []) or []:
        inv.sheets["vCephPool"].append({
            "Clúster": label, "Pool": p.get("pool_name"), "Réplicas (size)": p.get("size"), "Mín. réplicas": p.get("min_size"),
            "PGs": p.get("pg_num"), "Autoscale": p.get("pg_autoscale_mode"), "Regla CRUSH": p.get("crush_rule_name"),
            "Usado (GiB)": _b2gib(p.get("bytes_used")),
            "Uso (%)": round(float(p["percent_used"]) * 100, 1) if p.get("percent_used") is not None else None,
            "Aplicación": ", ".join((p.get("application_metadata") or {}).keys()) or None,
        })


def node_hardware(inv, api, label, node):
    for d in sorted(api.try_get(f"nodes/{q(node)}/disks/list", [], **{"include-partitions": 0}) or [], key=lambda x: x.get("devpath", "")):
        inv.sheets["vPhysicalDisk"].append({
            "Clúster": label, "Nodo": node, "Dispositivo": d.get("devpath"), "Tipo": d.get("type"),
            "Modelo": d.get("model"), "Fabricante": (d.get("vendor") or "").strip() or None, "Serie": d.get("serial"),
            "Tamaño (GiB)": _b2gib(d.get("size")), "RPM": d.get("rpm") or None, "SMART": d.get("health"),
            "Desgaste (%)": None if d.get("wearout") in (None, "N/A", "") else d.get("wearout"),
            "Uso": d.get("used"), "GPT": _flag(d.get("gpt")), "OSD Ceph": d.get("osdid") if str(d.get("osdid", -1)) != "-1" else None,
        })
    for z in api.try_get(f"nodes/{q(node)}/disks/zfs", []) or []:
        size, alloc = z.get("size"), z.get("alloc")
        inv.sheets["vZFS"].append({
            "Clúster": label, "Nodo": node, "Pool": z.get("name"), "Estado": z.get("health"),
            "Tamaño (GiB)": _b2gib(size), "Asignado (GiB)": _b2gib(alloc), "Libre (GiB)": _b2gib(z.get("free")),
            "Uso (%)": round(100 * alloc / size, 1) if size and alloc is not None else None,
            "Fragmentación (%)": z.get("frag"), "Dedup": z.get("dedup"),
        })


def node_maintenance(inv, api, label, node, host_row):
    repos = api.try_get(f"nodes/{q(node)}/apt/repositories", {}) or {}
    for r in repos.get("standard-repos", []) or []:
        status = r.get("status")
        inv.sheets["vRepo"].append({
            "Clúster": label, "Nodo": node, "Repositorio": r.get("name"), "Handle": r.get("handle"),
            "Estado": "Habilitado" if status == 1 else ("Deshabilitado" if status == 0 else "No configurado"),
        })
    updates = api.try_get(f"nodes/{q(node)}/apt/update")
    if host_row is not None:
        host_row["Actualizaciones pendientes"] = len(updates) if isinstance(updates, list) else None
        dns = api.try_get(f"nodes/{q(node)}/dns", {}) or {}
        host_row["DNS"] = ", ".join(x for x in (dns.get("dns1"), dns.get("dns2"), dns.get("dns3")) if x) or None
        host_row["Dominio búsqueda"] = dns.get("search")
        host_row["Zona horaria"] = (api.try_get(f"nodes/{q(node)}/time", {}) or {}).get("timezone")
    for c in api.try_get(f"nodes/{q(node)}/certificates/info", []) or []:
        days = _days_from_now(c.get("notafter"))
        inv.sheets["vCert"].append({
            "Clúster": label, "Nodo": node, "Fichero": c.get("filename"), "Sujeto": c.get("subject"),
            "Emisor": c.get("issuer"), "Válido desde": _ts(c.get("notbefore")), "Válido hasta": _ts(c.get("notafter")),
            "Días restantes": days, "SAN": ", ".join(c.get("san") or []) or None, "Huella SHA256": c.get("fingerprint"),
        })


# ============================================================================ backups y tareas
def backup_status(inv, api, label, storages, guest_rows):
    seen_shared = set()
    copies = defaultdict(list)
    for s in storages:
        if s.get("status") != "available" or "backup" not in str(s.get("content", "")):
            continue
        sid = s.get("storage")
        if s.get("shared"):
            if sid in seen_shared:
                continue
            seen_shared.add(sid)
        items = api.try_get(f"nodes/{q(s.get('node'))}/storage/{q(sid)}/content", [], content="backup") or []
        for it in items:
            if it.get("vmid") is not None:
                copies[int(it["vmid"])].append({**it, "_storage": sid})
    for g in guest_rows:
        if g["Plantilla"] == "Sí":
            continue
        cs = sorted(copies.get(int(g["VMID"]), []), key=lambda x: x.get("ctime") or 0)
        last = cs[-1] if cs else {}
        age = round((time.time() - int(last["ctime"])) / 86400, 1) if last.get("ctime") else None
        verif = (last.get("verification") or {}).get("state") if isinstance(last.get("verification"), dict) else None
        row = {
            "Clúster": label, "Nodo": g["Nodo"], "VMID": g["VMID"], "Nombre": g["Nombre"], "Tipo": g["Tipo"],
            "Estado VM": g["Estado"], "Nº copias": len(cs), "Último backup": _ts(last.get("ctime")),
            "Antigüedad (días)": age, "Tamaño último (GiB)": _b2gib(last.get("size")),
            "Almacenamiento": last.get("_storage"), "Verificado": verif, "Protegido": _flag(last.get("protected")) if last else None,
            "Almacenamientos con copias": ", ".join(sorted({c["_storage"] for c in cs})) or None,
        }
        inv.sheets["vBackupStatus"].append(row)
        g["Último backup"] = row["Último backup"]


def tasks(inv, api, label, days=7):
    since = time.time() - days * 86400
    for t in api.try_get("cluster/tasks", []) or []:
        st = t.get("status")
        if not st or st == "OK" or (t.get("starttime") or 0) < since:
            continue
        inv.sheets["vTasks"].append({
            "Clúster": label, "Nodo": t.get("node"), "Tipo": t.get("type"), "Objeto": t.get("id"),
            "Usuario": t.get("user"), "Inicio": _ts(t.get("starttime")), "Fin": _ts(t.get("endtime")),
            "Estado": st, "Gravedad": "AVISO" if str(st).startswith("WARNINGS") else "ERROR",
        })


# ============================================================================ salud
def health(inv, add):
    for label, c in inv._ceph.items():
        if c["status"] and c["status"] != "HEALTH_OK":
            sev = "CRÍTICO" if c["status"] == "HEALTH_ERR" else "AVISO"
            add(sev, label, "Ceph", f"{c['status']}: " + "; ".join(f"{k}: {v}" for k, v in c["checks"].items())[:400])
    for o in inv.sheets["vCephOSD"]:
        if o["Estado"] != "up" or o["In"] == "No":
            add("CRÍTICO", o["Clúster"], f"Ceph {o['OSD']} ({o['Host']})", f"OSD {o['Estado']}, in={o['In']}")
        elif (o["Uso (%)"] or 0) >= 80:
            add("AVISO", o["Clúster"], f"Ceph {o['OSD']} ({o['Host']})", f"OSD al {o['Uso (%)']}%")
    for d in inv.sheets["vPhysicalDisk"]:
        obj = f"Disco {d['Dispositivo']} ({d['Nodo']})"
        if d["SMART"] and str(d["SMART"]).upper() not in ("PASSED", "OK", "UNKNOWN"):
            add("CRÍTICO", d["Clúster"], obj, f"SMART: {d['SMART']} ({d['Modelo']})")
        try:
            if d["Desgaste (%)"] is not None and float(d["Desgaste (%)"]) >= 80:
                add("AVISO", d["Clúster"], obj, f"Desgaste del SSD al {d['Desgaste (%)']}%")
        except (TypeError, ValueError):
            pass
    for z in inv.sheets["vZFS"]:
        obj = f"ZFS {z['Pool']} ({z['Nodo']})"
        if z["Estado"] and z["Estado"] != "ONLINE":
            add("CRÍTICO", z["Clúster"], obj, f"Pool en estado {z['Estado']}")
        if (z["Uso (%)"] or 0) >= 80:
            add("AVISO", z["Clúster"], obj, f"Pool ocupado al {z['Uso (%)']}% (ZFS se degrada por encima del 80%)")
    for b in inv.sheets["vBond"]:
        if b["Nº esclavos"] == 1:
            add("INFO", b["Clúster"], f"Bond {b['Bond']} ({b['Nodo']})", "Bond con una sola interfaz (sin redundancia)")
    by_cluster = defaultdict(list)
    for c in inv.sheets["vCorosync"]:
        by_cluster[c["Clúster"]].append(c)
    for label, rows in by_cluster.items():
        if all((r["Enlaces"] or 0) < 2 for r in rows):
            add("AVISO", label, "Corosync", "Un solo enlace de corosync: sin red de clúster redundante")
    for label, opts in inv._dc_firewall.items():
        if str(opts.get("enable", 0)) != "1":
            add("INFO", label, "Firewall", "Firewall de datacenter deshabilitado")
    for u in inv.sheets["vUsers"]:
        if u["Tipo"] == "API token" and u["Privilegios separados"] == "No":
            add("INFO", u["Clúster"], f"Token {u['ID']}", "Token sin privilegios separados (hereda todos los permisos del usuario)")
    subs = {(h["Clúster"], h["Nodo"]): str(h.get("Suscripción") or "").lower() for h in inv.sheets["vHost"]}
    for r in inv.sheets["vRepo"]:
        obj = f"Nodo {r['Nodo']}"
        if r["Estado"] == "Habilitado" and "enterprise" in str(r["Handle"]) and subs.get((r["Clúster"], r["Nodo"])) != "active":
            add("AVISO", r["Clúster"], obj, f"Repositorio {r['Repositorio']} habilitado sin suscripción activa (las actualizaciones fallarán)")
        if r["Estado"] == "Habilitado" and "test" in str(r["Handle"]):
            add("AVISO", r["Clúster"], obj, f"Repositorio de pruebas habilitado: {r['Repositorio']}")
    for h in inv.sheets["vHost"]:
        if h.get("Actualizaciones pendientes"):
            add("INFO", h["Clúster"], f"Nodo {h['Nodo']}", f"{h['Actualizaciones pendientes']} actualizaciones pendientes")
    for c in inv.sheets["vCert"]:
        d = c["Días restantes"]
        if d is None:
            continue
        obj = f"Certificado {c['Fichero']} ({c['Nodo']})"
        if d < 0:
            add("CRÍTICO", c["Clúster"], obj, f"Caducado el {c['Válido hasta']}")
        elif d < CERT_WARN_DAYS:
            add("AVISO", c["Clúster"], obj, f"Caduca en {d} días")
    for b in inv.sheets["vBackupStatus"]:
        obj = f"{b['Tipo']} {b['VMID']} {b['Nombre']}"
        if b["Nº copias"] == 0:
            add("AVISO", b["Clúster"], obj, "Sin ninguna copia de backup en los almacenamientos")
        elif (b["Antigüedad (días)"] or 0) > BACKUP_AGE_WARN_DAYS:
            add("AVISO", b["Clúster"], obj, f"Último backup hace {b['Antigüedad (días)']} días")
        if b["Verificado"] == "failed":
            add("CRÍTICO", b["Clúster"], obj, "La verificación del último backup ha fallado")
    for p in inv.sheets["vPassthrough"]:
        if p["Tipo"] in ("PCI", "USB") and p["Mapeado"] == "No":
            add("INFO", p["Clúster"], f"{p['Tipo VM']} {p['VMID']} {p['Nombre']}",
                f"{p['Tipo']} passthrough sin mapping ({p['Dispositivo']}): impide la migración en caliente")
    failed = defaultdict(int)
    for t in inv.sheets["vTasks"]:
        failed[t["Clúster"]] += 1
    for label, n in failed.items():
        add("INFO", label, "Tareas", f"{n} tareas con error o avisos en los últimos 7 días (ver vTasks)")
