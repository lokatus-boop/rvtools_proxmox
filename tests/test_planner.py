"""Pruebas del planificador de migración. Ejecutar: python -m pytest tests/test_planner.py"""
import json
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from planner_sample import sample_sheets  # noqa: E402
from pvemigplan import scenario  # noqa: E402
from pvemigplan.loader import load  # noqa: E402
from pvemigplan.planner import Plan  # noqa: E402
from pvetools.export import to_csv, to_xlsx  # noqa: E402


def _inventory_files():
    d = tempfile.mkdtemp()
    sh = sample_sheets()
    to_xlsx(sh, os.path.join(d, "inv.xlsx"))
    to_csv(sh, os.path.join(d, "csv"))
    return d


def test_loader_xlsx_and_csv_match():
    d = _inventory_files()
    a, b = load(os.path.join(d, "inv.xlsx")), load(os.path.join(d, "csv"))
    assert len(a["vInfo"]) == len(b["vInfo"]) == 120
    pa, pb = Plan(a, scenario.new()), Plan(b, scenario.new())
    assert pa.summary()["vcpu"] == pb.summary()["vcpu"]
    assert round(pa.req.data_gib) == round(pb.req.data_gib)
    # cargar el mismo inventario dos veces no duplica VMs
    assert len(load([os.path.join(d, "inv.xlsx"), os.path.join(d, "csv")])["vInfo"]) == 120


@pytest.mark.parametrize("storage", ["ceph", "zfs", "san", "nfs"])
def test_advise_covers_needs(storage):
    sc = scenario.new()
    sc["almacenamiento"]["tipo"] = storage
    p = Plan(sample_sheets(), sc)
    assert p.options and p.eval["ok"], p.eval["problemas"]
    assert p.eval["cpu_pct_n1"] <= 100 and p.eval["ram_pct_n1"] <= 100
    assert p.eval["almacenamiento_util_gib"] >= p.req.data_gib
    assert len(p.placement) == len(p.an.guests)
    assert sum(len(w["guests"]) for w in p.waves) == len(p.an.guests)
    assert p.waves[0]["tipo"] == "Piloto"


def test_hardware_mode_detects_shortfall_and_ok():
    sc = scenario.new()
    sc["modo"] = "hardware"
    p = Plan(sample_sheets(), sc)          # 3 nodos de ejemplo: insuficiente para 120 VMs
    assert not p.eval["ok"] and any("CPU" in x for x in p.eval["problemas"])
    sc["hardware"]["servidores"][0]["cantidad"] = 8
    sc["hardware"]["servidores"][0]["discos"][1]["cantidad"] = 8
    p = Plan(sample_sheets(), sc)
    assert p.eval["ok"], p.eval["problemas"]


def test_pbs_and_method():
    sc = scenario.new()
    p = Plan(sample_sheets(), sc)
    assert p.pbs and p.pbs["util_necesario_gib"] > p.req.data_used_gib * sc["pbs"]["reduccion"]
    assert p.method["id"] == "pbs"
    sc["pbs"]["incluir"] = False
    p = Plan(sample_sheets(), sc)
    assert p.pbs is None and p.method["id"] == "remote-migrate"


def test_exclusions_and_issues():
    sc = scenario.new()
    sc["alcance"]["excluir"] = ["CLU-PROD/100", "CLU-PROD/101"]
    p = Plan(sample_sheets(), sc)
    keys = {g.key for g in p.an.guests}
    assert "CLU-PROD/100" not in keys and "CLU-PROD/102" in keys
    assert any(r["Severidad"] == "BLOQUEO" and r["Categoría"] == "Hardware" for r in p.issues)  # passthrough


def test_scenario_roundtrip():
    sc = scenario.new()
    sc["cliente"] = "ACME"
    p = os.path.join(tempfile.mkdtemp(), "e.json")
    scenario.save(sc, p)
    assert scenario.load(p)["cliente"] == "ACME"
    with open(p, "w", encoding="utf-8") as f:
        json.dump({"modo": "hardware"}, f)
    assert scenario.load(p)["capacidad"]["ratio_vcpu_core"] == 4.0   # se completan los valores por defecto


def test_reports():
    pytest.importorskip("matplotlib")
    pytest.importorskip("docx")
    from pvemigplan.cli import main
    d = _inventory_files()
    out = os.path.join(d, "out")
    rc = main([os.path.join(d, "inv.xlsx"), "-o", out, "--cliente", "Demo", "--graficos", "-q"])
    assert rc == 0
    for f in ("plan_migracion.xlsx", "plan_migracion_diseno_cliente.docx", "plan_migracion_guia_implementacion.docx"):
        assert os.path.getsize(os.path.join(out, f)) > 10000
    assert len(os.listdir(os.path.join(out, "plan_migracion_graficos"))) >= 10
    from openpyxl import load_workbook
    wb = load_workbook(os.path.join(out, "plan_migracion.xlsx"), read_only=True)
    assert {"Aviso", "Resumen", "Opciones hardware", "Ubicación VMs", "Redes", "VLANs", "PBS", "Olas", "Riesgos"} <= set(wb.sheetnames)
    assert {"Switches", "Puertos nodo", "Cableado"} <= set(wb.sheetnames)


def test_network_model():
    p = Plan(sample_sheets(), scenario.new())
    names = {n["red"] for n in p.networks}
    assert {"Management", "Cluster (corosync) 1", "Payload (VMs)", "Ceph Private"} <= names
    assert p.net.host_ports and all(h["Device Name"] for h in p.net.host_ports)
    tipos = {w["tipo"] for w in p.net.switches}
    assert any(t.startswith("Servicio") for t in tipos) and any("OOB" in t for t in tipos)
    sc = scenario.new()
    sc["switches"]["servicio"].update(suministra="cliente", modelo="Cisco Nexus 93180YC-FX")
    p = Plan(sample_sheets(), sc)
    svc = next(w for w in p.net.switches if w["tipo"].startswith("Servicio"))
    assert "Cisco" in svc["modelo"] and "cliente" in svc["suministra"].lower()


def _fake_template(path):
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "Cover Sheet"
    ws["B5"], ws["B6"] = "Company Name:", "Password"
    ws = wb.create_sheet("Host Ports")
    ws["B2"], ws["B30"] = "Host Link", "Example:"
    ws = wb.create_sheet("Networks")
    for i, n in enumerate(["Management", "Cluster (corosync) 1", "Payload 1", "Network sensitivity & traffic characteristics"]):
        ws.cell(4 + i, 2, n)
    ws = wb.create_sheet("Settings")
    for i, n in enumerate(["Cluster Name", "Timezone", "Root Password", "Primary DNS Server IP Address"]):
        ws.cell(3 + i, 2, n)
    wb.save(path)


def test_config_sheet_and_asbuilt():
    pytest.importorskip("docx")
    from openpyxl import load_workbook
    from pvemigplan.config_sheet import fill
    from pvemigplan.report_asbuilt import to_asbuilt_docx
    d = tempfile.mkdtemp()
    tmpl, out = os.path.join(d, "t.xlsx"), os.path.join(d, "o.xlsx")
    _fake_template(tmpl)
    sc = scenario.new()
    sc["cliente"] = "Acme Corp"
    fill(Plan(sample_sheets(), sc), tmpl, out)
    wb = load_workbook(out)
    assert wb["Cover Sheet"]["D5"].value == "Acme Corp"
    assert wb["Cover Sheet"]["D6"].value is None              # contraseñas nunca
    assert wb["Settings"]["C3"].value == "acme-pve"
    assert wb["Settings"]["C5"].value is None
    assert wb["Host Ports"]["E3"].value
    assert wb["Networks"]["G4"].value.endswith("GbE")
    doc = to_asbuilt_docx(sample_sheets(), os.path.join(d, "ab.docx"), "Acme", "PS", out)
    assert os.path.getsize(doc) > 10000


def test_loader_damaged_file_message():
    from pvemigplan.loader import InventoryError
    p = os.path.join(tempfile.mkdtemp(), "roto.xlsx")
    with open(p, "wb") as f:
        f.write(b"\0" * 1000)
    with pytest.raises(InventoryError, match="vacío"):
        load(p)


def test_solo_analisis_informe():
    """Modo solo análisis: Word + Excel sin plan de migración, también desde CLI y con inventario anonimizado."""
    from openpyxl import load_workbook

    from pvemigplan.assessment import Assessment
    from pvemigplan.cli import main
    from pvemigplan.report_assessment import generate
    sh = sample_sheets()
    a = Assessment(sh, "Cliente", "Autor")
    assert a.findings and all(f["Severidad"] in ("CRÍTICO", "AVISO", "INFO") for f in a.findings)
    assert any(f["Categoría"] == "Versiones" for f in a.findings)       # PVE 7.4 sin soporte
    assert sum(a.backup_age().values()) == len(a.an.guests)
    d = tempfile.mkdtemp()
    xl = generate(a, d, "inf", docx=False)[0]
    wb = load_workbook(xl, read_only=True)
    assert {"Resumen", "Hallazgos", "Uso por nodo", "VMs"} <= set(wb.sheetnames)
    assert not any("ola" in s.lower() or "destino" in s.lower() for s in wb.sheetnames)
    try:  # el Word necesita python-docx y matplotlib (no están en el CI del inventario)
        import docx  # noqa: F401
        import matplotlib  # noqa: F401
    except ImportError:
        docx = None
    if docx:
        out = generate(a, d, "inf", xlsx=False, charts=True)
        assert len(os.listdir(os.path.join(d, "inf_graficos"))) >= 10
        from docx import Document
        text = "\n".join(p.text for p in Document(out[0]).paragraphs).lower()
        assert "hallazgos" in text and "ola " not in text and "plan de migración" not in text
    # CLI con un inventario anonimizado
    from pvetools.anonymize import Anonymizer
    inv = os.path.join(d, "inv.xlsx")
    to_xlsx(Anonymizer().anonymize(sample_sheets()), inv)
    assert main([inv, "--analisis", "-o", d, "-q", "--sin-word"]) == 0
    assert os.path.exists(os.path.join(d, "analisis_infraestructura.xlsx"))
    assert Assessment(load(inv)).anonymized


def test_sdn_en_informes():
    """El SDN del inventario aparece en el análisis, en el plan (correspondencia de redes) y en los comandos de la guía."""
    from pvemigplan.assessment import Assessment
    from pvemigplan.report_impl import sdn_commands
    sh = sample_sheets()
    a = Assessment(sh, "Cliente", "Autor")
    sdn = a.an.sdn()
    assert {z["zone"] for z in sdn["zones"]} == {"zvlan", "evpn1"}
    assert {v["vnet"]: v["nics"] for v in sdn["vnets"]}["vnet100"] > 0
    assert "2 zonas" in a.an.sdn_summary() and "3 VNets" in a.an.sdn_summary()
    titles = {f["Hallazgo"] for f in a.findings}
    assert "Zonas SDN EVPN con menos de dos exit nodes" in titles and "VNets de SDN sin ninguna VM/CT conectada" in titles
    p = Plan(sh, scenario.new())
    row = next(r for r in p.vlan_map if r["Bridge origen"] == "vnet100")
    assert "zvlan" in row["Destino propuesto"] and row["Tipo zona SDN origen"] == "vlan"
    cmds = sdn_commands(p)
    for part in ("--controller evpnctl --type evpn --asn 65000", "--zone evpn1 --type evpn", "--vnet tenant1 --zone evpn1 --tag 11000",
                 "--dhcp-range start-address=10.50.0.100,end-address=10.50.0.200", "--type netbox", "--token <TOKEN>",
                 "--zone zvlan --type vlan --bridge vmbr1", "--zone vmnet --bridge vmbr1", "pvesh set /cluster/sdn"):
        assert part in cmds, part
    assert "vlan100" not in cmds  # la VLAN 100 ya es la VNet vnet100
    sin = {k: (v if k not in ("vSDN", "vSDNObj") else []) for k, v in sh.items()}
    a2 = Assessment(sin)
    assert not a2.an.has_sdn() and a2.an.sdn_summary() == "sin SDN configurado"
    assert "pvesh create /cluster/sdn/zones --type vlan --zone vmnet" in sdn_commands(Plan(sin, scenario.new()))
    try:
        import docx  # noqa: F401
        import matplotlib  # noqa: F401
    except ImportError:
        return
    from docx import Document

    from pvemigplan.report_assessment import generate
    d = tempfile.mkdtemp()
    out = generate(a, d, "inf", xlsx=False)[0]
    doc = Document(out)
    text = "\n".join(p.text for p in doc.paragraphs) + "\n".join(c.text for t in doc.tables for r in t.rows for c in r.cells)
    assert "Zonas SDN" in text and "evpnctl" in text and "tenant2" in text
