"""Anonimización del inventario para que el cliente pueda enviarlo sin datos identificativos.

Sustituye por seudónimos consistentes (el mismo valor original da siempre el mismo seudónimo en todas las hojas)
los nombres de clústeres, nodos, VMs/CTs, almacenamientos, pools, etiquetas, usuarios, dominios, VNets, etc.,
y transforma IPs y MACs. Conserva todo lo que necesita el planificador de migración: CPU, RAM, discos, tamaños,
tipos de almacenamiento, estados, versiones, VLANs, bridges estándar (vmbrN) y las relaciones VM-nodo-red-almacenamiento.

Las IPv4 se transforman conservando la estructura de red (si dos IPs comparten subred, sus seudónimos también),
el primer octeto (10/172/192…) y el último (.1 sigue siendo .1), de modo que el diseño de red sigue siendo válido.

La correspondencia original → seudónimo se puede guardar en un fichero que se queda el cliente: permite revertir
los seudónimos y, si se reutiliza en otra ejecución, que los mismos valores reciban los mismos seudónimos.
"""
from __future__ import annotations

import copy
import hashlib
import hmac
import ipaddress
import os
import re
import secrets

MAP_FORMAT = 1
MAP_SHEET = "Correspondencia"
KEY_SHEET = "Clave"
ANON_MARK = "Sí"

# Prefijo y nº de dígitos del seudónimo por tipo de dato
KINDS = {
    "cluster": ("Clúster", "CLUSTER-", 2),
    "node": ("Nodo", "NODO-", 2),
    "vm": ("VM/CT", "VM-", 4),
    "storage": ("Almacenamiento", "STORAGE-", 2),
    "pool": ("Pool de recursos", "POOL-", 2),
    "tag": ("Etiqueta", "tag-", 2),
    "zfs": ("Pool ZFS", "zpool-", 2),
    "cephpool": ("Pool Ceph", "cephpool-", 2),
    "path": ("Ruta / destino de almacenamiento", "ruta-", 2),
    "server": ("Servidor externo", "servidor-", 2),
    "domain": ("Dominio", "dominio", 2),
    "user": ("Usuario", "usuario", 2),
    "group": ("Grupo", "grupo", 2),
    "realm": ("Realm", "realm", 2),
    "token": ("API token", "token", 2),
    "zone": ("Zona SDN", "zona", 2),
    "vnet": ("VNet SDN", "vnet-", 2),
    "fwobj": ("Objeto de firewall", "fwobj-", 2),
    "hagroup": ("Grupo / regla HA", "ha-", 2),
    "job": ("Job", "job-", 2),
    "snapshot": ("Snapshot", "snap-", 2),
    "iso": ("Imagen ISO", "iso-", 3),
    "serial": ("Nº de serie", "SN-", 4),
    "mapping": ("Mapping de dispositivo", "map-", 2),
    "ip": ("Dirección IP", "", 0),
    "mac": ("MAC", "", 0),
}

# Valores por defecto de Proxmox que no identifican al cliente: se conservan para que el informe sea legible
KEEP = {
    "storage": {"local", "local-lvm", "local-zfs", "local-btrfs"},
    "zfs": {"rpool"},
    "cephpool": {".mgr", "device_health_metrics"},
    "user": {"root"},
    "realm": {"pam", "pve"},
    "path": {"pve", "data", "/var/lib/vz", "rpool/data"},
    "snapshot": {"current"},
}
STD_IFACE = re.compile(r"^(vmbr|bond|eth|eno|ens|enp|enx|em|p\d|ib|vlan|ovs|tap|veth|lo$)[\w.:-]*$")
CLUSTER_SA = " (standalone)"
# Pistas de rol que usa el planificador para ordenar las olas (mismas expresiones que pvemigplan/planner.py):
# si el nombre, pool o etiqueta original es «crítico» (db, sql, sap, dc…) o «de pruebas» (test, dev, lab…),
# el seudónimo lleva el sufijo -crit / -test. Así el plan de olas no cambia y no se revela el nombre.
HINT_KINDS = ("vm", "pool", "tag")
CRIT_HINT = re.compile(r"(crit|core|erp|sql|oracle|\bdb|^db|dc\d*$|^dc|\bad\b|sap)", re.I)
TEST_HINT = re.compile(r"(test|dev|pre|lab|demo|qa|sandbox|temp)", re.I)

IPV4_RE = re.compile(r"(?<![\w.:])(\d{1,3}(?:\.\d{1,3}){3})(/\d{1,2})?(?![\w.])")
IPV6_RE = re.compile(r"(?<![\w:.])([0-9A-Fa-f]{0,4}(?::[0-9A-Fa-f]{0,4}){2,7})(/\d{1,3})?(?![\w:.])")
MAC_RE = re.compile(r"(?<![0-9A-Fa-f:])([0-9A-Fa-f]{2}(?:[:-][0-9A-Fa-f]{2}){5})(?![0-9A-Fa-f:])")
SPLIT_RE = re.compile(r"(\s*[,;]\s*|\s+)")
NAME_CHARS = r"[\w.-]"
USER_RE = re.compile(r"(?<![\w.@-])[\w.-]+@[\w.-]*[\w](?:![\w.-]+)?")


class Anonymizer:
    def __init__(self, key: str | None = None, keep_ips: bool = False, role_hints: bool = True):
        self.key = key or secrets.token_hex(32)
        self.keep_ips = keep_ips
        self.role_hints = role_hints
        self.maps: dict[str, dict[str, str]] = {k: {} for k in KINDS}
        self._used: dict[str, set] = {k: set() for k in KINDS}
        self._bitcache: dict[str, int] = {}
        self._text_re = None

    # ------------------------------------------------------------ seudónimos
    def alias(self, kind: str, value):
        if value is None or value == "":
            return value
        v = str(value).strip()
        if not v:
            return value
        if v in KEEP.get(kind, ()):
            return v
        m = self.maps[kind]
        if v not in m:
            _label, prefix, width = KINDS[kind]
            suffix = os.path.splitext(v)[1] if kind == "iso" else ""
            if self.role_hints and kind in HINT_KINDS:
                suffix = ("-crit" if CRIT_HINT.search(v) else "") + ("-test" if TEST_HINT.search(v) else "")
            n = len(m) + 1
            while f"{prefix}{n:0{width}d}{suffix}" in self._used[kind]:
                n += 1
            m[v] = f"{prefix}{n:0{width}d}{suffix}"
            self._used[kind].add(m[v])
            self._text_re = None
        return m[v]

    def alias_list(self, kind: str, value, item=None):
        """Lista separada por comas, punto y coma o espacios, conservando los separadores."""
        if value is None or value == "":
            return value
        fn = item or (lambda t: self.alias(kind, t))
        return "".join(p if (i % 2 or not p) else fn(p) for i, p in enumerate(SPLIT_RE.split(str(value))))

    def cluster(self, value):
        if not value:
            return value
        v = str(value)
        if v.endswith(CLUSTER_SA):
            return self.node(v[: -len(CLUSTER_SA)]) + CLUSTER_SA
        return self.alias("cluster", v)

    def node(self, value):
        return self.alias("node", value)

    def nodes(self, value):
        """'pve1,pve2' o 'pve1:2,pve2:1' (grupos HA) o 'pve1 pve2'."""
        def one(t):
            name, sep, prio = t.partition(":")
            return self.node(name) + sep + prio
        return self.alias_list("node", value, one)

    def storage_ref(self, value):
        """'almacenamiento:resto' (volúmenes) conservando el resto (vm-100-disk-0)."""
        if not value or ":" not in str(value):
            return self.alias("storage", value)
        st, rest = str(value).split(":", 1)
        if rest.startswith("iso/") or rest.startswith("vztmpl/"):
            folder, _, fname = rest.partition("/")
            return f"{self.alias('storage', st)}:{folder}/{self.alias('iso', fname)}"
        return f"{self.alias('storage', st)}:{rest}"

    def media(self, value):
        if not value or str(value) in ("none", "cdrom") or str(value).startswith("/dev/"):
            return value
        return ", ".join(self.storage_ref(p.strip()) for p in str(value).split(","))

    def bridge(self, value):
        """Los bridges estándar (vmbr0…) se conservan; las VNets de SDN (nombres libres) se anonimizan."""
        if not value or STD_IFACE.match(str(value)) or str(value).startswith("("):
            return value
        return self.alias("vnet", value)

    def hostname(self, value):
        """'web01' o 'web01.cliente.local': el nombre corto como VM y el dominio aparte."""
        if not value:
            return value
        v = str(value).strip()
        if self._is_ip(v):
            return self.ip_text(v)
        short, dot, domain = v.partition(".")
        return self.alias("vm", short) + (dot + self.alias("domain", domain) if domain else "")

    def server(self, value):
        """IPs o nombres de servidores externos (NFS, iSCSI, PBS, monitores Ceph)."""
        def one(t):
            host, sep, port = t, "", ""
            if t.count(":") == 1 and not self._is_ip(t):
                host, sep, port = t.partition(":")
            if self._is_ip(host):
                return self.ip_text(host) + sep + port
            short, dot, domain = host.partition(".")
            if short in self.maps["node"]:
                return self.node(short) + (dot + self.alias("domain", domain) if domain else "") + sep + port
            return self.alias("server", short) + (dot + self.alias("domain", domain) if domain else "") + sep + port
        return self.alias_list("server", value, one)

    def user(self, value):
        """'usuario@realm' o 'usuario@realm!token'."""
        if not value:
            return value
        v = str(value)
        uid, bang, tok = v.partition("!")
        name, at, realm = uid.rpartition("@")
        if not at:
            name, realm = uid, ""
        out = self.alias("user", name) + (at + self.alias("realm", realm) if at else "")
        return out + (bang + self.alias("token", tok) if bang else "")

    def acl_path(self, value):
        if not value:
            return value
        parts = str(value).split("/")
        kinds = {"pool": "pool", "storage": "storage", "nodes": "node", "zones": "zone", "vnets": "vnet",
                 "mapping": "mapping"}
        out, prev = [], ""
        for p in parts:
            if prev in kinds and p:
                k = kinds[prev]
                p = self.node(p) if k == "node" else self.alias(k, p)
            out.append(p)
            prev = p if p in kinds else ("mapping" if prev == "mapping" else "")
        return "/".join(out)

    def tags(self, value):
        return self.alias_list("tag", value)

    # ------------------------------------------------------------ IPs y MACs
    @staticmethod
    def _is_ip(s: str) -> bool:
        try:
            ipaddress.ip_address(s.split("/")[0])
            return True
        except ValueError:
            return False

    def _bits(self, data: str, n: int) -> int:
        """Bits pseudoaleatorios deterministas (HMAC con la clave)."""
        k = f"{data}|{n}"
        if k not in self._bitcache:
            d = hmac.new(bytes.fromhex(self.key), data.encode(), hashlib.sha256).digest()
            self._bitcache[k] = int.from_bytes(d, "big") >> (256 - n) if n else 0
        return self._bitcache[k]

    def ipv4(self, addr: str) -> str:
        """Transformación que conserva prefijos (tipo Crypto-PAn) en los octetos 2 y 3.

        Dos IPs que comparten los k primeros bits siguen compartiéndolos, así que las subredes y gateways
        siguen siendo coherentes. Se conservan el primer octeto y el último.
        """
        ip = int(ipaddress.IPv4Address(addr))
        first, mid, last = ip >> 24, (ip >> 8) & 0xFFFF, ip & 0xFF
        out = 0
        for i in range(16):
            bit = (mid >> (15 - i)) & 1
            prefix = f"v4|{first}|{mid >> (16 - i) if i else 0}|{i}"
            out = (out << 1) | (bit ^ self._bits(prefix, 1))
        res = str(ipaddress.IPv4Address((first << 24) | (out << 8) | last))
        self.maps["ip"][addr] = res
        return res

    def ipv6(self, addr: str) -> str:
        a = ipaddress.IPv6Address(addr)
        if a.is_link_local or a.is_loopback or a.is_unspecified:
            iid = self._bits(f"v6iid|{int(a) & ((1 << 64) - 1)}", 64)
            res = str(ipaddress.IPv6Address(((int(a) >> 64) << 64) | iid))
        else:
            net = self._bits(f"v6net|{int(a) >> 64}", 56)
            iid = self._bits(f"v6iid|{int(a) & ((1 << 64) - 1)}", 64) if int(a) & ((1 << 64) - 1) > 0xFFFF \
                else int(a) & 0xFFFF  # ::1, ::10… (gateways y direcciones fijas) se conservan
            res = str(ipaddress.IPv6Address((0xFD << 120) | (net << 64) | iid))
        self.maps["ip"][addr] = res
        return res

    def ip_text(self, value):
        """Sustituye todas las IPv4/IPv6 (con o sin /prefijo) y MACs que aparezcan en un texto."""
        if value is None or not isinstance(value, str) or self.keep_ips:
            return self.mac_text(value) if isinstance(value, str) else value

        def v4(m):
            try:
                return self.ipv4(m.group(1)) + (m.group(2) or "")
            except ValueError:
                return m.group(0)

        def v6(m):
            s = m.group(1)
            if s.count(":") < 2 or not any(c.isdigit() or c.isalpha() for c in s):
                return m.group(0)
            try:
                return self.ipv6(s) + (m.group(2) or "")
            except ValueError:
                return m.group(0)

        out = self.mac_text(value)
        out = IPV4_RE.sub(v4, out)
        return IPV6_RE.sub(v6, out)

    def mac(self, value):
        """Conserva el fabricante (OUI, p. ej. BC:24:11 de Proxmox) y transforma el resto."""
        if not value:
            return value
        v = str(value)
        sep = "-" if "-" in v else ":"
        parts = re.split(r"[:-]", v)
        tail = self._bits("mac|" + "".join(parts).upper(), 24)
        new = parts[:3] + [f"{(tail >> s) & 0xFF:02X}" for s in (16, 8, 0)]
        res = sep.join(p.upper() if v == v.upper() else p.lower() for p in new)
        self.maps["mac"][v] = res
        return res

    def mac_text(self, value):
        if not isinstance(value, str):
            return value
        return MAC_RE.sub(lambda m: self.mac(m.group(1)), value)

    # ------------------------------------------------------------ texto libre
    def text(self, value):
        """Textos libres (avisos, objetos, ámbitos): sustituye nombres ya conocidos, IPs y MACs."""
        if not isinstance(value, str) or not value:
            return value
        if self._text_re is None:
            names = {}  # si un mismo texto es de varios tipos, gana el primero de esta lista
            for kind in ("node", "cluster", "vm", "storage", "fwobj", "hagroup", "zone", "vnet", "pool", "snapshot",
                         "iso", "server", "domain", "mapping", "zfs", "cephpool", "path", "job", "tag"):
                for orig, al in self.maps[kind].items():
                    if len(orig) >= 2 and orig != al:
                        names.setdefault(orig, al)
            for orig, al in self.maps["user"].items():
                if orig != al and len(orig) >= 3:
                    names.setdefault(orig, al)
            if names:
                alt = "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True))
                self._text_re = (re.compile(rf"(?<!{NAME_CHARS})({alt})(?!\w|[.-]\w)"), names)
            else:
                self._text_re = (None, {})
        out = USER_RE.sub(lambda m: self.user(m.group(0)), self.ip_text(value))
        rx, names = self._text_re
        return rx.sub(lambda m: names[m.group(1)], out) if rx else out

    # ------------------------------------------------------------ hojas
    def anonymize(self, sheets: dict) -> dict:
        """Devuelve una copia anonimizada del inventario ({hoja: [filas]}). No modifica el original."""
        out = copy.deepcopy(sheets)
        # Los seudónimos nuevos se numeran en el orden alfabético de los originales: así se mantiene el orden de
        # los listados (y del plan de olas, que agrupa por clúster, pool y nombre)
        seed = {"cluster": set(), "node": set(), "vm": set(), "pool": set(), "storage": set()}
        for r in out.get("vHost", []) + out.get("vInfo", []):
            c = str(r.get("Clúster") or "")
            if c and not c.endswith(CLUSTER_SA):
                seed["cluster"].add(c)
            for kind, col in (("node", "Nodo"), ("vm", "Nombre"), ("pool", "Pool")):
                if r.get(col):
                    seed[kind].add(str(r[col]).strip())
        for r in out.get("vDatastore", []):
            if r.get("Almacenamiento"):
                seed["storage"].add(str(r["Almacenamiento"]).strip())
        for kind, vals in seed.items():
            for v in sorted(vals, key=str.lower):
                self.alias(kind, v)
        # 1º los datos estructurados (rellenan las tablas de correspondencia), 2º los textos libres
        first = ("vHost", "vCluster", "vInfo", "vDatastore", "vFirewallObj")
        order = [s for s in first if s in out] + [s for s in out if s not in first]
        done = {}
        for sheet in order:
            for row in out.get(sheet, []):
                done[id(row)] = self._row(sheet, row)
        for sheet in order:
            for row in out.get(sheet, []):
                for col in list(row):
                    if col in done[id(row)]:
                        continue
                    if col in TEXT_COLS or (sheet, col) in TEXT_COLS:
                        row[col] = self.text(row[col])
                    elif isinstance(row[col], str):  # red de seguridad: ninguna IP/MAC se escapa
                        row[col] = self.ip_text(row[col])
        for row in out.get("vSource", []):
            row["Anonimizado"] = ANON_MARK + (" (IPs conservadas)" if self.keep_ips else "")
        return out

    def _row(self, sheet: str, row: dict) -> set:
        handled = set()
        for col in list(row):
            fn = SHEET_RULES.get((sheet, col), RULES.get(col))
            if fn is None or row[col] is None or row[col] == "":
                continue
            row[col] = fn(self, row[col], row) if fn.__code__.co_argcount == 3 else fn(self, row[col])
            handled.add(col)
        return handled

    # ------------------------------------------------------------ fichero de correspondencia
    def rows(self) -> list[dict]:
        out = []
        for kind, m in self.maps.items():
            for orig, al in m.items():
                if orig != al:
                    out.append({"Tipo": KINDS[kind][0], "Clave tipo": kind, "Original": orig, "Seudónimo": al})
        return out

    def save(self, path: str):
        """Guarda la correspondencia (Excel). Es la única forma de revertir: la conserva el cliente."""
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Font, PatternFill
        wb = Workbook()
        ws = wb.active
        ws.title = MAP_SHEET
        ws.append(["CONFIDENCIAL — Correspondencia de la anonimización del inventario. Este fichero se queda en el "
                   "cliente: NO lo envíes junto al inventario anonimizado."])
        ws["A1"].font = Font(bold=True, color="C00000")
        ws.append([])
        cols = ["Tipo", "Clave tipo", "Original", "Seudónimo"]
        ws.append(cols)
        for c in ws[3]:
            c.fill, c.font = PatternFill("solid", fgColor="1F4E78"), Font(bold=True, color="FFFFFF")
            c.alignment = Alignment(vertical="center")
        for r in self.rows():
            ws.append([r[c] for c in cols])
        ws.freeze_panes = "A4"
        ws.auto_filter.ref = f"A3:D{ws.max_row}"
        for col, w in zip("ABCD", (30, 12, 50, 30)):
            ws.column_dimensions[col].width = w
        ks = wb.create_sheet(KEY_SHEET)
        ks.append(["Formato", MAP_FORMAT])
        ks.append(["Clave IP/MAC", self.key])
        ks.append(["IPs conservadas", "Sí" if self.keep_ips else "No"])
        ks.append([])
        ks.append(["Reutiliza este fichero en la próxima anonimización para que los mismos valores reciban los "
                   "mismos seudónimos (p. ej. al inventariar otro clúster del mismo cliente)."])
        ks.sheet_state = "hidden"
        wb.save(path)
        return path

    @classmethod
    def load(cls, path: str, keep_ips: bool | None = None) -> "Anonymizer":
        """Carga un fichero de correspondencia anterior para continuar con los mismos seudónimos."""
        from openpyxl import load_workbook
        wb = load_workbook(path, read_only=True, data_only=True)
        if MAP_SHEET not in wb.sheetnames or KEY_SHEET not in wb.sheetnames:
            raise ValueError(f"{os.path.basename(path)} no es un fichero de correspondencia de PVE Inventory")
        meta = {r[0]: r[1] for r in wb[KEY_SHEET].iter_rows(values_only=True) if r and r[0]}
        prev_keep = str(meta.get("IPs conservadas")) == "Sí"
        a = cls(key=str(meta["Clave IP/MAC"]), keep_ips=prev_keep if keep_ips is None else keep_ips)
        for r in wb[MAP_SHEET].iter_rows(min_row=4, values_only=True):
            if not r or len(r) < 4 or r[1] not in a.maps or r[2] is None:
                continue
            a.maps[r[1]][str(r[2])] = str(r[3])
            a._used[r[1]].add(str(r[3]))
        wb.close()
        return a


def _reverse_sub(mapping_path: str):
    a = Anonymizer.load(mapping_path)
    names = {}
    for m in a.maps.values():
        for orig, al in m.items():
            names.setdefault(al, orig)
    if not names:
        return lambda v: v
    alt = "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True))
    rx = re.compile(rf"(?<![\w.-])({alt})(?!\w|[.-]\w)")

    def sub(v):
        if not isinstance(v, str) or not v:
            return v
        if v.startswith(ANON_MARK) and v in (ANON_MARK, ANON_MARK + " (IPs conservadas)"):
            return v
        return rx.sub(lambda m: names[m.group(1)], v)
    return sub


def reverse(sheets: dict, mapping_path: str) -> dict:
    """Revierte (en lo posible) un inventario anonimizado ({hoja: [filas]}) con su fichero de correspondencia.

    Los campos que se vaciaron al anonimizar (descripciones, comentarios, emails…) no se pueden recuperar.
    """
    sub = _reverse_sub(mapping_path)
    out = copy.deepcopy(sheets)
    for rows in out.values():
        for row in rows:
            for col, v in row.items():
                row[col] = "Revertido" if col == "Anonimizado" and v else sub(v)
    return out


def reverse_file(path: str, mapping_path: str, out_path: str | None = None) -> str:
    """Revierte los seudónimos en cualquier Excel (inventario anonimizado o plan generado a partir de él) o CSV.

    Escribe una copia (por defecto «<nombre>_revertido.<ext>») y devuelve su ruta.
    """
    sub = _reverse_sub(mapping_path)
    base, ext = os.path.splitext(path)
    out_path = out_path or f"{base}_revertido{ext}"
    if ext.lower() in (".xlsx", ".xlsm"):
        from openpyxl import load_workbook
        wb = load_workbook(path)
        for ws in wb.worksheets:
            for row in ws.iter_rows():
                for c in row:
                    if isinstance(c.value, str) and not c.value.startswith("="):
                        c.value = sub(c.value)
        wb.save(out_path)
    elif ext.lower() in (".csv", ".txt"):
        with open(path, encoding="utf-8-sig") as f:
            data = f.read()
        with open(out_path, "w", encoding="utf-8-sig") as f:
            f.write("\n".join(sub(line) for line in data.split("\n")))
    else:
        raise ValueError("Solo se pueden revertir ficheros Excel (.xlsx) o CSV")
    return out_path


def default_map_path(export_path: str) -> str:
    base = os.path.splitext(export_path.rstrip("/\\"))[0]
    return base + "_correspondencia_CONFIDENCIAL.xlsx"


# ---------------------------------------------------------------- reglas por columna
def _blank(_a, _v):
    return None


def _keep_or_blank_issuer(a, v):
    s = str(v)
    return v if re.search(r"Proxmox|PVE|Let's Encrypt|R\d+|E\d+", s) else "(anonimizado)"


def _cert_names(a, v):
    out = []
    for t in re.split(r"\s*,\s*", str(v)):
        pre, eq, val = t.rpartition("=") if "=" in t else ("", "", t)
        if a._is_ip(val):
            val = a.ip_text(val)
        elif val in a.maps["node"]:
            val = a.node(val)
        elif "." in val:
            short, _, dom = val.partition(".")
            short = a.node(short) if short in a.maps["node"] else ("*" if short == "*" else a.alias("server", short))
            val = f"{short}.{a.alias('domain', dom)}"
        elif val:
            val = a.node(val) if val in a.maps["node"] else a.alias("server", val)
        out.append(pre + eq + val)
    return ", ".join(out)


def _acl_who(a, v, row):
    t = str(row.get("Tipo") or "")
    if t == "Grupo":
        return a.alias("group", v)
    return a.user(v)


def _vha_resource(a, v, row):
    s = str(v)
    if re.match(r"^(vm|ct):\d+$", s):
        return v
    return a.alias("hagroup", s)


def _backup_sel(a, v):
    s = str(v)
    if s.startswith("Pool "):
        return "Pool " + a.alias("pool", s[5:])
    return v


def _vcd_media(a, v):
    return a.media(v)


def _fw_scope(a, v):
    s = str(v)
    for word, fn in (("Grupo ", lambda x: a.alias("fwobj", x)), ("Nodo ", a.node)):
        if s.startswith(word):
            return word + fn(s[len(word):])
    return a.text(s)


def _pass_dev(a, v, row):
    return a.alias("mapping", v) if str(row.get("Mapeado")) == "Sí" else v


def _ds_path(a, v, row):
    t = str(row.get("Tipo") or "")
    if t in ("rbd", "cephfs"):
        return a.alias("cephpool", v)
    if t == "zfspool":
        head, sl, rest = str(v).partition("/")
        return a.alias("zfs", head) + sl + rest if head not in KEEP["zfs"] else v
    return a.alias("path", v)


def _zfs_obj(a, v):
    return a.alias("zfs", v)


RULES = {
    "Clúster": lambda a, v: a.cluster(v),
    "Clúster / nodo": lambda a, v: a.cluster(v),
    "Nodo": lambda a, v: a.node(v),
    "Host": lambda a, v: a.node(v),
    "Nombre": lambda a, v: a.alias("vm", v),
    "Hostname": lambda a, v: a.hostname(v),
    "Pool": lambda a, v: a.alias("pool", v),
    "Etiquetas": lambda a, v: a.tags(v),
    "Descripción": _blank,
    "Comentario": _blank,
    "Email": _blank,
    "Almacenamiento": lambda a, v: a.alias("storage", v),
    "Almacenamientos con copias": lambda a, v: a.alias_list("storage", v),
    "Volumen": lambda a, v: a.storage_ref(v),
    "Medio": _vcd_media,
    "Ruta / destino": lambda a, v: a.alias("path", v),
    "Servidor": lambda a, v: a.server(v),
    "Nodos permitidos": lambda a, v: a.nodes(v),
    "Nodos zona": lambda a, v: a.nodes(v),
    "Bridge": lambda a, v: a.bridge(v),
    "Bridge zona": lambda a, v: a.bridge(v),
    "VNet": lambda a, v: a.bridge(v),
    "Zona": lambda a, v: a.alias("zone", v),
    "Alias": _blank,
    "Snapshot": lambda a, v: a.alias("snapshot", v),
    "Padre": lambda a, v: a.alias("snapshot", v),
    "Serie": lambda a, v: a.alias("serial", v),
    "Host conectado": lambda a, v: a.server(v),
    "Conectado vía": lambda a, v: a.server(v),
    "Usuario": lambda a, v: a.user(v),
    "Dominio búsqueda": lambda a, v: a.alias_list("domain", v),
    "MAC": lambda a, v: a.mac(v),
    "Grupo": lambda a, v: a.alias("hagroup", v),
    "Destino": lambda a, v: a.node(v),
    "Selección": _backup_sel,
    "Huella SHA256": _blank,
}

SHEET_RULES = {
    ("vFirewallObj", "Nombre"): lambda a, v: a.alias("fwobj", v),
    ("vFirewall", "Destino"): None,
    ("vFirewall", "Ámbito"): _fw_scope,  # se trata como texto (IPs, alias, ipsets)
    ("vUsers", "Nombre"): _blank,
    ("vUsers", "ID"): lambda a, v: a.user(v),
    ("vUsers", "Grupos"): lambda a, v: a.alias_list("group", v),
    ("vUsers", "Realm"): lambda a, v: a.alias("realm", v),
    ("vACL", "Ruta"): lambda a, v: a.acl_path(v),
    ("vACL", "Usuario / grupo"): _acl_who,
    ("vHA", "Recurso"): _vha_resource,
    ("vHA", "Nodos"): lambda a, v: a.nodes(v),
    ("vBackup", "Job"): lambda a, v: a.alias("job", v),
    ("vZFS", "Pool"): _zfs_obj,
    ("vCephPool", "Pool"): lambda a, v: a.alias("cephpool", v),
    ("vDatastore", "Ruta / destino"): _ds_path,
    ("vCert", "Sujeto"): _cert_names,
    ("vCert", "SAN"): _cert_names,
    ("vCert", "Emisor"): _keep_or_blank_issuer,
    ("vPassthrough", "Dispositivo"): _pass_dev,
    ("vSource", "Usuario"): lambda a, v: a.user(v),
}

# Columnas de texto libre que pueden mencionar nombres ya anonimizados en otras hojas
TEXT_COLS = {
    "Objeto", "Mensaje", "Ámbito", "Origen", ("vFirewall", "Destino"), ("vFirewallObj", "Valor"),
    ("vSource", "Estado"), "Recursos afectados", "Direcciones", "IP config", ("vPassthrough", "Config"),
}
