"""Anonimización del inventario. Ejecutar: python -m pytest tests/test_anonymize.py"""
import ipaddress
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

import mock_pve  # noqa: E402
from planner_sample import sample_sheets  # noqa: E402
from pvetools.anonymize import Anonymizer, default_map_path, reverse, reverse_file  # noqa: E402
from pvetools.collector import Inventory  # noqa: E402
from pvetools.export import to_csv, to_xlsx  # noqa: E402
from test_inventory import serve  # noqa: E402

TOK = {"user": "auditor@pve", "token_id": "inv", "token_secret": "secret"}


def _inventory():
    return Inventory(query_agent=True).collect([{**TOK, "host": serve(mock_pve.cluster_data())},
                                               {"host": serve(mock_pve.standalone_data()), "user": "root@pam", "password": "pw"}])


def _cells(sheets):
    for rows in sheets.values():
        for r in rows:
            for v in r.values():
                if isinstance(v, str):
                    yield v


def test_no_identifying_data_left():
    sh = _inventory()
    a = Anonymizer()
    out = a.anonymize(sh)
    text = "\n".join(_cells(out))
    # nombres reales del Proxmox simulado
    for real in ("web01", "db01", "dns01", "tpl-debian", "pve1", "pve2", "pve-sa", "CLU-PROD", "ceph-vm", "auditor",
                 "antes-update", "debian-12.iso", "mgmt", "zvlan", "vnet100", "dmz", "10.0.0.11", "10.20.0.5",
                 "192.168.1.10", "AA:BB:01", "web01.lab", "pre upgrade"):
        assert not re.search(rf"(?<![\w.-]){re.escape(real)}(?![\w-])", text), f"queda «{real}» en el export"
    # todo lo que se registró en la correspondencia ha desaparecido de la salida
    for kind, m in a.maps.items():
        for orig, al in m.items():
            if orig != al and len(orig) > 3:
                assert not re.search(rf"(?<![\w.-]){re.escape(orig)}(?![\w-])", text), (kind, orig)
    # el original no se modifica
    assert sh["vInfo"][0]["Nombre"] == "web01"
    assert all(r["Anonimizado"] == "Sí" for r in out["vSource"])


def test_consistent_and_structure_preserved():
    sh = _inventory()
    out = Anonymizer().anonymize(sh)
    # mismas filas, mismas columnas, mismas métricas
    for name, rows in sh.items():
        assert len(out[name]) == len(rows)
        for r0, r1 in zip(rows, out[name]):
            assert r0.keys() <= r1.keys()
            for col in ("VMID", "vCPU", "Memoria (MiB)", "Tamaño (GiB)", "Tipo", "VLAN", "Estado", "Tipo SO"):
                if col in r0:
                    assert r0[col] == r1[col], (name, col)
    # mismo valor -> mismo seudónimo en todas las hojas
    vm = {(r["Clúster"], r["VMID"]): (r["Nombre"], r["Nodo"]) for r in out["vInfo"]}
    for sheet in ("vDisk", "vNetwork", "vCPU", "vMemory", "vSnapshot"):
        for r in out[sheet]:
            assert vm[(r["Clúster"], r["VMID"])] == (r["Nombre"], r["Nodo"]), sheet
    nodes = {(r["Clúster"], r["Nodo"]) for r in out["vHost"]}
    assert {(r["Clúster"], r["Nodo"]) for r in out["vInfo"]} <= nodes
    assert any(c.endswith(" (standalone)") and c.startswith("NODO-") for c, _ in nodes)
    stores = {(r["Clúster"], r["Almacenamiento"]) for r in out["vDatastore"]}
    assert {(r["Clúster"], r["Almacenamiento"]) for r in out["vDisk"]} <= stores
    # las IPs conservan la subred: nodo, gateway y VM de la misma /24 siguen juntos
    br = next(r for r in out["vBridge"] if r["Gateway"])
    assert ipaddress.ip_interface(br["CIDR"]).network == ipaddress.ip_interface(br["Gateway"] + "/24").network
    host_ips = {r["IP"] for r in out["vHost"]}
    assert all(ipaddress.ip_interface(r["CIDR"]).ip.exploded in host_ips for r in out["vBridge"])
    # las VNets SDN se anonimizan igual en vSDN y en vNetwork
    assert out["vSDN"][0]["VNet"] != "vnet100" and out["vSDN"][0]["Alias"] is None
    # SDN: controladores, IPAM, DNS, zonas DNS y URLs se seudonimizan; el IPAM integrado «pve» se conserva
    sdn_text = str(out["vSDN"]) + str(out["vSDNObj"]) + str(out["vHealth"])
    for real in ("evpnctl", "netbox1", "pdns", "tenant1", "zvlan", "cliente.local", "ipam01", "10.0.0.53", "/api"):
        assert real not in sdn_text, real
    assert {r["Nombre"] for r in out["vSDNObj"] if r["Objeto"] == "IPAM"} >= {"pve"}


def test_mapping_roundtrip_and_reverse():
    sh = _inventory()
    d = tempfile.mkdtemp()
    a = Anonymizer()
    out = a.anonymize(sh)
    mp = default_map_path(os.path.join(d, "inv.xlsx"))
    a.save(mp)
    # reutilizar la correspondencia da exactamente los mismos seudónimos
    again = Anonymizer.load(mp).anonymize(sh)
    assert again == out
    # revertir
    back = reverse(out, mp)
    assert [r["Nombre"] for r in back["vInfo"]] == [r["Nombre"] for r in sh["vInfo"]]
    assert [r["IP"] for r in back["vHost"]] == [r["IP"] for r in sh["vHost"]]
    assert back["vDisk"][0]["Volumen"] == sh["vDisk"][0]["Volumen"]
    to_xlsx(out, os.path.join(d, "inv.xlsx"))
    rev = reverse_file(os.path.join(d, "inv.xlsx"), mp)
    from openpyxl import load_workbook
    ws = load_workbook(rev)["vInfo"]
    assert "web01" in [c.value for c in ws["D"]]


def test_keep_ips():
    out = Anonymizer(keep_ips=True).anonymize(_inventory())
    assert out["vHost"][0]["IP"] == "10.0.0.11" and out["vHost"][0]["Nodo"] != "pve1"
    assert out["vSource"][0]["Anonimizado"].startswith("Sí")


def test_cli_anonymize_and_revert(capsys):
    from pvetools.cli import main
    d = tempfile.mkdtemp()
    out = os.path.join(d, "anon.xlsx")
    rc = main(["--host", serve(mock_pve.cluster_data()), "--user", "auditor@pve", "--token-id", "inv",
               "--token-secret", "secret", "--no-agent", "-q", "--anonimizar", "-o", out, "--csv", os.path.join(d, "csv")])
    assert rc == 0 and os.path.exists(out) and os.path.exists(default_map_path(out))
    with open(os.path.join(d, "csv", "LEEME_AVISO.txt"), encoding="utf-8-sig") as f:
        assert "ANONIMIZADO" in f.read()
    assert main(["--revertir", out, "--correspondencia", default_map_path(out)]) == 0
    assert os.path.exists(os.path.join(d, "anon_revertido.xlsx"))


def test_planner_reads_anonymized_export():
    """El planificador produce el mismo plan con el inventario real y con el anonimizado."""
    from pvemigplan import scenario
    from pvemigplan.loader import format_warnings, load
    from pvemigplan.outputs import generate
    from pvemigplan.planner import Plan
    d = tempfile.mkdtemp()
    real = sample_sheets()
    anon = Anonymizer().anonymize(real)
    to_xlsx(real, os.path.join(d, "real.xlsx"))
    to_xlsx(anon, os.path.join(d, "anon.xlsx"))
    to_csv(anon, os.path.join(d, "csv"))
    a, b, c = (load(os.path.join(d, p)) for p in ("real.xlsx", "anon.xlsx", "csv"))
    assert any("anonimizado" in w for w in format_warnings(b))
    pa, pb, pc = Plan(a, scenario.new()), Plan(b, scenario.new()), Plan(c, scenario.new())
    for p in (pb, pc):
        assert p.summary() == pa.summary()
        # mismo plan de olas (las pistas -crit/-test y el orden de los seudónimos lo conservan)
        assert [[g.vmid for g in w["guests"]] for w in p.waves] == [[g.vmid for g in w["guests"]] for w in pa.waves]
        assert round(p.req.data_gib) == round(pa.req.data_gib)
        assert p.eval["ok"] == pa.eval["ok"] and len(p.options) == len(pa.options)
        assert len(p.placement) == len(pa.placement) and len(p.waves) == len(pa.waves)
        assert len(p.an.vlan_usage()) == len(pa.an.vlan_usage())
        assert len(p.an.subnets()) == len(pa.an.subnets())
        assert p.an.guest_storage_by_type() == pa.an.guest_storage_by_type()
        assert p.method["id"] == pa.method["id"]
    try:  # los Word necesitan python-docx y matplotlib (requirements-planner.txt); el Excel no
        import docx  # noqa: F401
        import matplotlib  # noqa: F401
        docs = True
    except ImportError:
        docs = False
    files = generate(pb, os.path.join(d, "plan"), design=docs, impl=docs)
    assert files and all(os.path.getsize(f) > 0 for f in files)
    names = {g.name for g in pb.an.guests}
    assert names and all(n.startswith("VM-") for n in names)
