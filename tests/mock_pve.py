"""Servidor HTTPS que simula la API de Proxmox VE para pruebas.

Escenarios: 'cluster' (2 nodos PVE 9, uno caído no; con Ceph, HA, backup) y 'standalone' (nodo PVE 8).
Uso: python mock_pve.py <puerto> <cluster|standalone> <cert.pem> <key.pem>
"""
import json
import re
import ssl
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

NOW = int(time.time())
G = 1024 ** 3


def cluster_data():
    return {
        "version": {"version": "9.0.10", "release": "9.0", "repoid": "abc"},
        "cluster/status": [
            {"type": "cluster", "name": "CLU-PROD", "quorate": 1, "nodes": 2, "version": 5},
            {"type": "node", "name": "pve1", "ip": "10.0.0.11", "online": 1},
            {"type": "node", "name": "pve2", "ip": "10.0.0.12", "online": 1},
        ],
        "nodes": [{"node": "pve1"}, {"node": "pve2"}],
        "cluster/resources": [
            {"type": "node", "node": "pve1", "status": "online", "cpu": 0.12, "maxcpu": 32, "mem": 100 * G, "maxmem": 128 * G, "uptime": 900000},
            {"type": "node", "node": "pve2", "status": "online", "cpu": 0.30, "maxcpu": 32, "mem": 120 * G, "maxmem": 128 * G, "uptime": 800000},
            {"type": "qemu", "node": "pve1", "vmid": 100, "name": "web01", "status": "running", "cpu": 0.05, "maxcpu": 4,
             "mem": 3 * G, "maxmem": 4 * G, "maxdisk": 32 * G, "uptime": 3600, "pool": "prod", "tags": "web;linux"},
            {"type": "qemu", "node": "pve2", "vmid": 101, "name": "db01", "status": "running", "cpu": 0.5, "maxcpu": 8,
             "mem": 15 * G, "maxmem": 16 * G, "maxdisk": 100 * G, "uptime": 7200},
            {"type": "qemu", "node": "pve2", "vmid": 9000, "name": "tpl-debian", "status": "stopped", "template": 1, "maxmem": 2 * G},
            {"type": "lxc", "node": "pve1", "vmid": 200, "name": "dns01", "status": "running", "cpu": 0.01, "maxcpu": 2,
             "mem": 200 * 1024 ** 2, "maxmem": 512 * 1024 ** 2, "disk": 2 * G, "maxdisk": 8 * G, "uptime": 99999},
            {"type": "storage", "node": "pve1", "storage": "local-lvm", "status": "available", "plugintype": "lvmthin",
             "disk": 400 * G, "maxdisk": 450 * G, "content": "images,rootdir", "shared": 0},
            {"type": "storage", "node": "pve2", "storage": "local-lvm", "status": "available", "plugintype": "lvmthin",
             "disk": 100 * G, "maxdisk": 450 * G, "content": "images,rootdir", "shared": 0},
            {"type": "storage", "node": "pve1", "storage": "ceph-vm", "status": "available", "plugintype": "rbd",
             "disk": 2000 * G, "maxdisk": 6000 * G, "content": "images", "shared": 1},
            {"type": "storage", "node": "pve2", "storage": "ceph-vm", "status": "available", "plugintype": "rbd",
             "disk": 2000 * G, "maxdisk": 6000 * G, "content": "images", "shared": 1},
            {"type": "storage", "node": "pve1", "storage": "pbs", "status": "available", "plugintype": "pbs",
             "disk": 1000 * G, "maxdisk": 4000 * G, "content": "backup", "shared": 1},
            {"type": "storage", "node": "pve2", "storage": "pbs", "status": "available", "plugintype": "pbs",
             "disk": 1000 * G, "maxdisk": 4000 * G, "content": "backup", "shared": 1},
        ],
        "storage": [
            {"storage": "local-lvm", "type": "lvmthin", "vgname": "pve", "thinpool": "data", "content": "images,rootdir"},
            {"storage": "ceph-vm", "type": "rbd", "pool": "vm", "content": "images", "shared": 1},
            {"storage": "pbs", "type": "pbs", "server": "10.0.0.50", "datastore": "store1", "content": "backup"},
        ],
        "nodes/pve1/storage/pbs/content": [
            {"volid": "pbs:backup/vm/100/2026-11-09T21:00:00Z", "vmid": 100, "ctime": NOW - 86400, "size": 5 * G, "verification": {"state": "ok"}},
            {"volid": "pbs:backup/vm/101/2026-10-01T21:00:00Z", "vmid": 101, "ctime": NOW - 86400 * 40, "size": 50 * G}],
        "cluster/ha/resources": [{"sid": "vm:101", "state": "started", "max_restart": 1, "max_relocate": 1}],
        "cluster/backup": [{"id": "backup-daily", "enabled": 1, "schedule": "21:00", "storage": "pbs", "mode": "snapshot",
                            "all": 1, "exclude": "9000", "prune-backups": "keep-daily=7"}],
        "cluster/backup-info/not-backed-up": [{"vmid": 200, "name": "dns01", "type": "lxc"}],
        "cluster/replication": [],
        # --- nodo
        "nodes/pve1/status": {"kversion": "Linux 6.14.8-2-pve", "cpuinfo": {"model": "AMD EPYC 7302", "sockets": 1, "cores": 16, "cpus": 32, "mhz": "3000"},
                              "memory": {"total": 128 * G, "used": 100 * G}, "swap": {"total": 8 * G, "used": 0},
                              "rootfs": {"total": 100 * G, "used": 20 * G}, "loadavg": ["0.5", "0.6", "0.7"],
                              "boot-info": {"mode": "efi", "secureboot": 1}},
        "nodes/pve2/status": {"kversion": "Linux 6.14.8-2-pve", "cpuinfo": {"model": "AMD EPYC 7302", "sockets": 1, "cores": 16, "cpus": 32, "mhz": "3000"},
                              "memory": {"total": 128 * G, "used": 120 * G}, "swap": {"total": 8 * G, "used": G},
                              "rootfs": {"total": 100 * G, "used": 85 * G}, "loadavg": ["2.5", "2.6", "2.7"]},
        "nodes/pve1/version": {"version": "9.0.10", "release": "9.0"},
        "nodes/pve2/version": {"version": "9.0.6", "release": "9.0"},
        "nodes/pve1/subscription": {"status": "active", "level": "c"},
        "nodes/pve2/subscription": {"status": "notfound"},
        "nodes/pve1/network": [
            {"iface": "vmbr0", "type": "bridge", "active": 1, "autostart": 1, "method": "static", "cidr": "10.0.0.11/24",
             "gateway": "10.0.0.1", "bridge_ports": "bond0", "bridge_vlan_aware": 1},
            {"iface": "bond0", "type": "bond", "active": 1, "slaves": "eno1 eno2", "bond_mode": "802.3ad"},
            {"iface": "eno1", "type": "eth", "active": 1}, {"iface": "eno2", "type": "eth", "active": 1},
        ],
        "nodes/pve2/network": [{"iface": "vmbr0", "type": "bridge", "active": 1, "cidr": "10.0.0.12/24", "bridge_ports": "eno1"},
                               {"iface": "eno1.50", "type": "vlan", "active": 1, "vlan-id": 50, "vlan-raw-device": "eno1", "cidr": "172.16.50.12/24"}],
        # --- SDN, corosync, firewall, acceso
        "cluster/sdn/zones": [{"zone": "zvlan", "type": "vlan", "bridge": "vmbr0"}, {"zone": "zempty", "type": "simple"}],
        "cluster/sdn/vnets": [{"vnet": "vnet100", "zone": "zvlan", "tag": 100, "alias": "dmz"}],
        "cluster/sdn/vnets/vnet100/subnets": [{"cidr": "192.168.100.0/24", "gateway": "192.168.100.1", "snat": 1}],
        "cluster/config/totem": {"cluster_name": "CLU-PROD", "config_version": 5, "link_mode": "passive", "secauth": "on"},
        "cluster/config/nodes": [{"name": "pve1", "nodeid": 1, "quorum_votes": 1, "ring0_addr": "10.0.0.11"},
                                 {"name": "pve2", "nodeid": 2, "quorum_votes": 1, "ring0_addr": "10.0.0.12"}],
        "cluster/firewall/options": {"enable": 0, "policy_in": "DROP"},
        "cluster/firewall/rules": [{"pos": 0, "type": "in", "action": "ACCEPT", "macro": "SSH", "source": "+mgmt", "enable": 1}],
        "cluster/firewall/groups": [{"group": "web", "comment": "HTTP"}],
        "cluster/firewall/groups/web": [{"pos": 0, "type": "in", "action": "ACCEPT", "proto": "tcp", "dport": "80,443", "enable": 1}],
        "cluster/firewall/aliases": [{"name": "gw", "cidr": "10.0.0.1"}],
        "cluster/firewall/ipset": [{"name": "mgmt"}],
        "cluster/firewall/ipset/mgmt": [{"cidr": "10.0.0.0/24"}],
        "access/users": [{"userid": "root@pam", "enable": 1, "realm-type": "pam"},
                         {"userid": "auditor@pve", "enable": 1, "realm-type": "pve", "tokens": [{"tokenid": "inv", "privsep": 0}]}],
        "access/acl": [{"path": "/", "type": "user", "ugid": "auditor@pve", "roleid": "PVEAuditor", "propagate": 1}],
        # --- Ceph y discos
        "cluster/ceph/status": {"health": {"status": "HEALTH_WARN", "checks": {"OSD_NEARFULL": {"summary": {"message": "1 nearfull osd(s)"}}}}},
        "nodes/pve1/ceph/osd": {"root": {"type": "root", "name": "default", "children": [
            {"type": "host", "name": "pve1", "children": [{"type": "osd", "name": "osd.0", "id": 0, "status": "up", "in": 1, "device_class": "ssd",
                                                          "total_space": 1000 * G, "bytes_used": 850 * G, "percent_used": 85.0}]},
            {"type": "host", "name": "pve2", "children": [{"type": "osd", "name": "osd.1", "id": 1, "status": "down", "in": 0, "device_class": "ssd"}]}]}},
        "nodes/pve1/ceph/pool": [{"pool_name": "vm", "size": 3, "min_size": 2, "pg_num": 128, "pg_autoscale_mode": "on",
                                  "bytes_used": 2000 * G, "percent_used": 0.33, "application_metadata": {"rbd": {}}}],
        "nodes/pve1/disks/list": [{"devpath": "/dev/sda", "type": "ssd", "model": "SAMSUNG MZ7", "serial": "S1", "size": 480 * G,
                                   "health": "PASSED", "wearout": 85, "used": "LVM"},
                                  {"devpath": "/dev/sdb", "type": "hdd", "model": "ST4000", "size": 4000 * G, "health": "FAILED", "wearout": "N/A"}],
        "nodes/pve2/disks/zfs": [{"name": "rpool", "size": 100 * G, "alloc": 90 * G, "free": 10 * G, "frag": 30, "dedup": 1.0, "health": "DEGRADED"}],
        # --- mantenimiento
        "nodes/pve1/apt/repositories": {"standard-repos": [{"handle": "enterprise", "name": "Enterprise", "status": 1},
                                                           {"handle": "no-subscription", "name": "No-Subscription", "status": 0}]},
        "nodes/pve2/apt/repositories": {"standard-repos": [{"handle": "enterprise", "name": "Enterprise", "status": 1},
                                                           {"handle": "test", "name": "Test", "status": 1}]},
        "nodes/pve1/apt/update": [],
        "nodes/pve2/apt/update": [{"Package": "pve-manager"}, {"Package": "qemu-server"}],
        "nodes/pve1/dns": {"search": "lab", "dns1": "10.0.0.1"},
        "nodes/pve1/time": {"timezone": "Europe/Madrid"},
        "nodes/pve1/certificates/info": [{"filename": "pve-ssl.pem", "subject": "CN=pve1", "issuer": "CN=PVE CA",
                                          "notbefore": NOW - 86400 * 700, "notafter": NOW + 86400 * 10,
                                          "fingerprint": "AA:BB:CC", "san": ["pve1", "10.0.0.11"]}],
        "nodes/pve2/certificates/info": [{"filename": "pve-ssl.pem", "subject": "CN=pve2", "notafter": NOW + 86400 * 700, "fingerprint": "DD:EE:FF"}],
        "cluster/tasks": [{"node": "pve1", "type": "vzdump", "id": "", "user": "root@pam", "starttime": NOW - 3600, "endtime": NOW - 3000, "status": "job errors"},
                          {"node": "pve1", "type": "qmstart", "id": "100", "user": "root@pam", "starttime": NOW - 600, "endtime": NOW - 590, "status": "OK"}],
        # --- invitados
        "nodes/pve1/qemu/100/config": {"name": "web01", "sockets": 1, "cores": 4, "memory": "4096", "ostype": "l26", "agent": "1",
                                       "scsi0": "ceph-vm:vm-100-disk-0,iothread=1,size=32G,ssd=1", "ide2": "local:iso/debian-12.iso,media=cdrom",
                                       "net0": "virtio=BC:24:11:AA:BB:01,bridge=vmbr0,firewall=1,tag=20", "onboot": 1,
                                       "bios": "ovmf", "efidisk0": "ceph-vm:vm-100-disk-1,efitype=4m,size=1M", "cpu": "x86-64-v2-AES",
                                       "meta": f"creation-qemu=9.0.2,ctime={NOW - 86400 * 300}"},
        "nodes/pve1/qemu/100/agent/network-get-interfaces": {"result": [
            {"name": "lo", "hardware-address": "00:00:00:00:00:00", "ip-addresses": [{"ip-address": "127.0.0.1"}]},
            {"name": "eth0", "hardware-address": "bc:24:11:aa:bb:01", "ip-addresses": [{"ip-address": "10.20.0.5"}, {"ip-address": "fe80::1"}]}]},
        "nodes/pve1/qemu/100/agent/get-osinfo": {"result": {"pretty-name": "Debian GNU/Linux 12 (bookworm)"}},
        "nodes/pve1/qemu/100/agent/get-host-name": {"result": {"host-name": "web01.lab"}},
        "nodes/pve1/qemu/100/snapshot": [{"name": "antes-update", "snaptime": NOW - 86400 * 30, "description": "pre upgrade"},
                                         {"name": "current", "parent": "antes-update"}],
        "nodes/pve2/qemu/101/config": {"name": "db01", "sockets": 2, "cores": 4, "memory": 16384, "balloon": 8192, "ostype": "win11",
                                       "agent": "enabled=1,fstrim_cloned_disks=1", "lock": "backup",
                                       "virtio0": "ceph-vm:vm-101-disk-0,size=100G", "unused0": "local-lvm:vm-101-disk-9",
                                       "net0": "e1000=BC:24:11:AA:BB:02,bridge=vmbr0", "net1": "virtio=BC:24:11:AA:BB:03,bridge=vmbr1,link_down=1",
                                       "hostpci0": "0000:41:00.0,pcie=1", "cpu": "host"},
        # agente de 101 no responde -> 500
        "nodes/pve2/qemu/101/snapshot": [{"name": "current"}],
        "nodes/pve2/qemu/9000/config": {"name": "tpl-debian", "template": 1, "cores": 2, "memory": 2048,
                                        "scsi0": "local-lvm:base-9000-disk-0,size=10G", "net0": "virtio=BC:24:11:AA:BB:09,bridge=vmbr0"},
        "nodes/pve2/qemu/9000/snapshot": [{"name": "current"}],
        "nodes/pve1/lxc/200/config": {"hostname": "dns01", "cores": 2, "memory": 512, "swap": 512, "ostype": "debian", "unprivileged": 1,
                                      "rootfs": "local-lvm:vm-200-disk-0,size=8G", "mp0": "local-lvm:vm-200-disk-1,mp=/data,size=4G,backup=1",
                                      "net0": "name=eth0,bridge=vmbr0,hwaddr=BC:24:11:CC:00:01,ip=10.0.0.53/24,gw=10.0.0.1,type=veth",
                                      "tags": "infra"},
        "nodes/pve1/lxc/200/interfaces": [{"name": "lo", "hwaddr": "00:00:00:00:00:00", "inet": "127.0.0.1/8"},
                                          {"name": "eth0", "hwaddr": "bc:24:11:cc:00:01", "inet": "10.0.0.53/24"}],
        "nodes/pve1/lxc/200/snapshot": [{"name": "current"}],
    }


def standalone_data():
    return {
        "version": {"version": "8.4.1", "release": "8.4"},
        "cluster/status": [{"type": "node", "name": "pve-sa", "ip": "192.168.1.10", "online": 1, "local": 1}],
        "nodes": [{"node": "pve-sa"}],
        "cluster/resources": [
            {"type": "node", "node": "pve-sa", "status": "online", "cpu": 0.05, "maxcpu": 8, "mem": 10 * G, "maxmem": 32 * G, "uptime": 50000},
            {"type": "qemu", "node": "pve-sa", "vmid": 100, "name": "fw", "status": "stopped", "maxmem": 2 * G, "maxdisk": 16 * G},
            {"type": "storage", "node": "pve-sa", "storage": "local", "status": "available", "plugintype": "dir",
             "disk": 95 * G, "maxdisk": 100 * G, "content": "iso,backup,vztmpl"},
        ],
        "storage": [{"storage": "local", "type": "dir", "path": "/var/lib/vz", "content": "iso,backup,vztmpl"}],
        "cluster/ha/resources": [],
        "cluster/backup": [],
        "cluster/backup-info/not-backed-up": [{"vmid": 100, "name": "fw", "type": "qemu"}],
        "cluster/replication": [],
        "nodes/pve-sa/status": {"kversion": "Linux 6.8.12-9-pve", "cpuinfo": {"model": "Intel Xeon E-2236", "sockets": 1, "cores": 6, "cpus": 12},
                                "memory": {"total": 32 * G, "used": 10 * G}, "rootfs": {"total": 50 * G, "used": 10 * G}},
        "nodes/pve-sa/version": {"version": "8.4.1", "release": "8.4"},
        "nodes/pve-sa/subscription": {"status": "notfound"},
        "nodes/pve-sa/network": [{"iface": "vmbr0", "type": "bridge", "active": 1, "cidr": "192.168.1.10/24", "bridge_ports": "enp1s0"}],
        "nodes/pve-sa/qemu/100/config": {"name": "fw", "cores": 2, "memory": 2048, "ostype": "other",
                                         "sata0": "local:100/vm-100-disk-0.qcow2,size=16G",
                                         "net0": "virtio=BC:24:11:00:00:AA,bridge=vmbr0", "net1": "virtio=BC:24:11:00:00:AB,bridge=vmbr0,tag=99"},
        "nodes/pve-sa/qemu/100/snapshot": [{"name": "current"}],
    }


class Handler(BaseHTTPRequestHandler):
    data = {}
    TOKEN = "PVEAPIToken=auditor@pve!inv=secret"

    def log_message(self, *a):
        pass

    def _send(self, code, payload=None):
        body = json.dumps({"data": payload}).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path.endswith("/access/ticket"):
            n = int(self.headers.get("Content-Length", 0))
            form = parse_qs(self.rfile.read(n).decode())
            if form.get("username") == ["root@pam"] and form.get("password") == ["pw"]:
                return self._send(200, {"ticket": "PVE:root@pam:TICKET", "CSRFPreventionToken": "csrf", "username": "root@pam"})
            return self._send(401)
        self._send(501)

    def do_GET(self):
        auth = self.headers.get("Authorization") == self.TOKEN or "PVEAuthCookie=PVE:root@pam:TICKET" in (self.headers.get("Cookie") or "")
        if not auth:
            return self._send(401)
        path = re.sub(r"^/api2/json/", "", urlparse(self.path).path)
        if path in self.data:
            return self._send(200, self.data[path])
        if "/agent/" in path:
            return self._send(500)  # agente no responde
        self._send(501 if path.startswith("nodes/") else 404)


if __name__ == "__main__":
    port, scen, cert, key = int(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4]
    Handler.data = {"cluster": cluster_data, "standalone": standalone_data}[scen]()
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(cert, key)
    srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    srv.serve_forever()
