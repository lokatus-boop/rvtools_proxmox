"""Comandos pvesh para recrear el SDN en el nuevo clúster (sin python-docx: se prueba en el CI del inventario)."""
from __future__ import annotations

import shlex


def _arg(v) -> str:
    return shlex.quote(str(v))


def sdn_commands(plan) -> str:
    """Comandos pvesh para recrear en el nuevo clúster el SDN del inventario y las VLANs de las VMs sin SDN."""
    an = plan.an
    sdn = an.sdn()
    new_nodes = [n["name"] for n in plan.nodes]
    node_ips = ",".join(f"<IP-{n}>" for n in new_nodes)
    out, zones_done, vnets_done = [], set(), set()

    objs = [o for o in sdn["objects"] if not (o["object"] == "IPAM" and o["type"] == "pve")]
    seen = set()
    for o in objs:
        key = (o["object"], o["name"])
        if key in seen:
            continue
        seen.add(key)
        det = dict(x.split("=", 1) for x in o["details"].split("; ") if "=" in x) if o["details"] else {}
        url = _arg(o["url"]) if o["url"] else "<URL>"
        if o["object"] == "DNS":
            out.append(f"pvesh create /cluster/sdn/dns --dns {_arg(o['name'])} --type {o['type'] or 'powerdns'} --url {url} "
                       f"--key <CLAVE-API>" + (f" --ttl {det['ttl']}" if det.get("ttl") else ""))
        elif o["object"] == "IPAM":
            out.append(f"pvesh create /cluster/sdn/ipams --ipam {_arg(o['name'])} --type {o['type'] or 'netbox'} --url {url} "
                       f"--token <TOKEN>" + (f" --section {det['section']}" if det.get("section") else ""))
        elif o["object"] == "Controlador":
            base = f"pvesh create /cluster/sdn/controllers --controller {_arg(o['name'])} --type {o['type']}"
            if o["type"] == "evpn":
                out.append(f"{base} --asn {o['asn'] or '<ASN>'} --peers {node_ips}")
            elif o["type"] == "bgp":
                out.append(f"{base} --node <NODO-NUEVO> --asn {o['asn'] or '<ASN>'} --peers {_arg(o['peers'] or '<PEERS>')}"
                           + (f" --ebgp {det['ebgp']}" if det.get("ebgp") else "")
                           + f"   # origen: nodo {o['node'] or '?'}")
            elif o["type"] == "isis":
                out.append(f"{base} --node <NODO-NUEVO> --isis-domain {_arg(det.get('isis-domain', '<DOMINIO>'))} "
                           f"--isis-net {_arg(det.get('isis-net', '<NET>'))} --isis-ifaces <INTERFACES>   # origen: nodo {o['node'] or '?'}")
            else:
                out.append(f"# controlador {o['name']} ({o['type']}): recrear manualmente")
        elif o["object"] == "Fabric":
            out.append(f"# Fabric {o['name']} ({o['type']}): recrear en Datacenter → SDN → Fabrics con las interfaces e IPs "
                       "de los nodos nuevos" + (f" ({o['details']})" if o["details"] else ""))
    if out:
        out.insert(0, "# Servicios y controladores de SDN")
        out.append("")

    zl = []
    for z in sdn["zones"]:
        if z["zone"] in zones_done:
            zl.append(f"# zona {z['zone']} de {z['cluster']}: ya creada con este nombre; revisar si su configuración coincide")
            continue
        zones_done.add(z["zone"])
        cmd = f"pvesh create /cluster/sdn/zones --zone {_arg(z['zone'])} --type {z['type']}"
        if z["type"] in ("vlan", "qinq"):
            cmd += " --bridge vmbr1" + (f" --tag {z['qinq_tag']}" if z["type"] == "qinq" and z["qinq_tag"] else "")
        elif z["type"] == "vxlan":
            cmd += f" --peers {node_ips}"
        elif z["type"] == "evpn":
            cmd += f" --controller {_arg(z['controller'] or '<CONTROLADOR>')} --vrf-vxlan {z['vrf_vxlan'] or '<VNI-VRF>'}"
            cmd += " --exitnodes " + ",".join(new_nodes[:2] or ["<NODO>"])
        elif z["type"] == "simple" and z["dhcp"]:
            cmd += f" --dhcp {z['dhcp']}"
        for opt, key in (("mtu", "mtu"), ("ipam", "ipam"), ("dns", "dns"), ("reversedns", "reversedns"), ("dnszone", "dnszone")):
            if z[key]:
                cmd += f" --{opt} {_arg(z[key])}"
        if z["type"] in ("vlan", "qinq") and z["bridge"] and z["bridge"] != "vmbr1":
            cmd += f"   # en origen: {z['bridge']}"
        zl.append(cmd)
        for v in z["vnets"]:
            if v["vnet"] in vnets_done:
                continue
            vnets_done.add(v["vnet"])
            vc = f"pvesh create /cluster/sdn/vnets --vnet {_arg(v['vnet'])} --zone {_arg(z['zone'])}"
            if v["tag"]:
                vc += f" --tag {v['tag']}"
            if v["alias"]:
                vc += f" --alias {_arg(v['alias'])}"
            if v["vlanaware"]:
                vc += " --vlanaware 1"
            if v["isolate"]:
                vc += " --isolate-ports 1"
            zl.append(vc)
            for sn in v["subnets"]:
                sc = f"pvesh create /cluster/sdn/vnets/{v['vnet']}/subnets --type subnet --subnet {_arg(sn['cidr'])}"
                if sn["gateway"]:
                    sc += f" --gateway {sn['gateway']}"
                if sn["snat"]:
                    sc += " --snat 1"
                for rng in [x.strip() for x in sn["dhcp"].split(",") if "-" in x]:
                    a, b = rng.split("-", 1)
                    sc += f" --dhcp-range start-address={a},end-address={b}"
                if sn["dns_server"]:
                    sc += f" --dhcp-dns-server {sn['dns_server']}"
                zl.append(sc)
    if zl:
        out += ["# Zonas, VNets y subredes del SDN actual"] + zl + [""]

    vlans = sorted({r["VLAN origen"] for r in plan.vlan_map
                    if str(r["VLAN origen"]).isdigit() and not r.get("Tipo zona SDN origen")}, key=int)
    if vlans:
        zone = "vmnet"
        i = 2
        while zone in zones_done:
            zone, i = f"vmnet{i}", i + 1
        out += ["# VLANs de las VMs que hoy no están en SDN: zona VLAN con una VNet por VLAN",
                f"pvesh create /cluster/sdn/zones --type vlan --zone {zone} --bridge vmbr1"]
        for v in vlans:
            name = f"vlan{v}"
            if name in vnets_done:
                name = f"{zone}v{v}"
            out.append(f"pvesh create /cluster/sdn/vnets --vnet {name} --zone {zone} --tag {v}")
        out.append("")
    out.append("pvesh set /cluster/sdn   # aplicar")
    return "\n".join(out)
