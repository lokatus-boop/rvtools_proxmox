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
    for f in ("plan_migracion.xlsx", "plan_migracion.docx"):
        assert os.path.getsize(os.path.join(out, f)) > 10000
    assert len(os.listdir(os.path.join(out, "plan_migracion_graficos"))) >= 10
    from openpyxl import load_workbook
    wb = load_workbook(os.path.join(out, "plan_migracion.xlsx"), read_only=True)
    assert {"Aviso", "Resumen", "Opciones hardware", "Ubicación VMs", "Redes", "VLANs", "PBS", "Olas", "Riesgos"} <= set(wb.sheetnames)
