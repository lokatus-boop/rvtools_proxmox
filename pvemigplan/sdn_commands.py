"""Comandos pvesh para recrear el SDN en el nuevo clúster (sin python-docx: se prueba en el CI del inventario)."""
from __future__ import annotations

from pvetools.i18n import _

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
            out.append(_("pvesh create /cluster/sdn/dns --dns {_arg} --type {v} --url {url} --key <CLAVE-API>", _arg=_arg(o['name']), v=o['type'] or 'powerdns', url=url) + (f" --ttl {det['ttl']}" if det.get("ttl") else ""))
        elif o["object"] == "IPAM":
            out.append(_("pvesh create /cluster/sdn/ipams --ipam {_arg} --type {v} --url {url} --token <TOKEN>", _arg=_arg(o['name']), v=o['type'] or 'netbox', url=url) + (f" --section {det['section']}" if det.get("section") else ""))
        elif o["object"] == "Controlador":
            base = _("pvesh create /cluster/sdn/controllers --controller {_arg} --type {type}", _arg=_arg(o['name']), type=o['type'])
            if o["type"] == "evpn":
                out.append(_("{base} --asn {v} --peers {node_ips}", base=base, v=o['asn'] or '<ASN>', node_ips=node_ips))
            elif o["type"] == "bgp":
                out.append(_("{base} --node <NODO-NUEVO> --asn {v} --peers {_arg}", base=base, v=o['asn'] or '<ASN>', _arg=_arg(o['peers'] or '<PEERS>'))
                           + (f" --ebgp {det['ebgp']}" if det.get("ebgp") else "")
                           + _("   # origen: nodo {v}", v=o['node'] or '?'))
            elif o["type"] == "isis":
                out.append(_("{base} --node <NODO-NUEVO> --isis-domain {_arg} --isis-net {_arg2} --isis-ifaces <INTERFACES>   # origen: nodo {v}", base=base, _arg=_arg(det.get('isis-domain', '<DOMINIO>')), _arg2=_arg(det.get('isis-net', '<NET>')), v=o['node'] or '?'))
            else:
                out.append(_("# controlador {name} ({type}): recrear manualmente", name=o['name'], type=o['type']))
        elif o["object"] == "Fabric":
            out.append(_("# Fabric {name} ({type}): recrear en Datacenter → SDN → Fabrics con las interfaces e IPs de los nodos nuevos", name=o['name'], type=o['type']) + (f" ({o['details']})" if o["details"] else ""))
    if out:
        out.insert(0, _("# Servicios y controladores de SDN"))
        out.append("")

    zl = []
    for z in sdn["zones"]:
        if z["zone"] in zones_done:
            zl.append(_("# zona {zone} de {cluster}: ya creada con este nombre; revisar si su configuración coincide", zone=z['zone'], cluster=z['cluster']))
            continue
        zones_done.add(z["zone"])
        cmd = _("pvesh create /cluster/sdn/zones --zone {_arg} --type {type}", _arg=_arg(z['zone']), type=z['type'])
        if z["type"] in ("vlan", "qinq"):
            cmd += _(" --bridge vmbr1") + (f" --tag {z['qinq_tag']}" if z["type"] == "qinq" and z["qinq_tag"] else "")
        elif z["type"] == "vxlan":
            cmd += f" --peers {node_ips}"
        elif z["type"] == "evpn":
            cmd += _(" --controller {_arg} --vrf-vxlan {v}", _arg=_arg(z['controller'] or _('<CONTROLADOR>')), v=z['vrf_vxlan'] or '<VNI-VRF>')
            cmd += " --exitnodes " + ",".join(new_nodes[:2] or ["<NODO>"])
        elif z["type"] == "simple" and z["dhcp"]:
            cmd += f" --dhcp {z['dhcp']}"
        for opt, key in (("mtu", "mtu"), ("ipam", "ipam"), ("dns", "dns"), ("reversedns", "reversedns"), ("dnszone", "dnszone")):
            if z[key]:
                cmd += f" --{opt} {_arg(z[key])}"
        if z["type"] in ("vlan", "qinq") and z["bridge"] and z["bridge"] != "vmbr1":
            cmd += _("   # en origen: {bridge}", bridge=z['bridge'])
        zl.append(cmd)
        for v in z["vnets"]:
            if v["vnet"] in vnets_done:
                continue
            vnets_done.add(v["vnet"])
            vc = _("pvesh create /cluster/sdn/vnets --vnet {_arg} --zone {_arg2}", _arg=_arg(v['vnet']), _arg2=_arg(z['zone']))
            if v["tag"]:
                vc += f" --tag {v['tag']}"
            if v["alias"]:
                vc += f" --alias {_arg(v['alias'])}"
            if v["vlanaware"]:
                vc += _(" --vlanaware 1")
            if v["isolate"]:
                vc += _(" --isolate-ports 1")
            zl.append(vc)
            for sn in v["subnets"]:
                sc = _("pvesh create /cluster/sdn/vnets/{vnet}/subnets --type subnet --subnet {_arg}", vnet=v['vnet'], _arg=_arg(sn['cidr']))
                if sn["gateway"]:
                    sc += f" --gateway {sn['gateway']}"
                if sn["snat"]:
                    sc += _(" --snat 1")
                for rng in [x.strip() for x in sn["dhcp"].split(",") if "-" in x]:
                    a, b = rng.split("-", 1)
                    sc += _(" --dhcp-range start-address={a},end-address={b}", a=a, b=b)
                if sn["dns_server"]:
                    sc += f" --dhcp-dns-server {sn['dns_server']}"
                zl.append(sc)
    if zl:
        out += [_("# Zonas, VNets y subredes del SDN actual")] + zl + [""]

    vlans = sorted({r["VLAN origen"] for r in plan.vlan_map
                    if str(r["VLAN origen"]).isdigit() and not r.get("Tipo zona SDN origen")}, key=int)
    if vlans:
        zone = "vmnet"
        i = 2
        while zone in zones_done:
            zone, i = f"vmnet{i}", i + 1
        out += [_("# VLANs de las VMs que hoy no están en SDN: zona VLAN con una VNet por VLAN"),
                _("pvesh create /cluster/sdn/zones --type vlan --zone {zone} --bridge vmbr1", zone=zone)]
        for v in vlans:
            name = f"vlan{v}"
            if name in vnets_done:
                name = f"{zone}v{v}"
            out.append(_("pvesh create /cluster/sdn/vnets --vnet {name} --zone {zone} --tag {v}", name=name, zone=zone, v=v))
        out.append("")
    out.append(_("pvesh set /cluster/sdn   # aplicar"))
    return "\n".join(out)
