"""Documentos sin migración (sin VMs o sin inventario) y proyectos guardados (.pveplan).
Ejecutar: python -m pytest tests/test_project.py"""
import json
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from planner_sample import sample_sheets  # noqa: E402
from test_planner import _fake_template  # noqa: E402
from pvemigplan import project, scenario  # noqa: E402
from pvemigplan.outputs import generate  # noqa: E402
from pvemigplan.planner import Plan  # noqa: E402


def _doc_text(path):
    import docx
    d = docx.Document(path)
    heads = [p.text for p in d.paragraphs if p.style.name.startswith("Heading")]
    text = "\n".join(p.text for p in d.paragraphs)
    return heads, text


def _hosts_only():
    sh = sample_sheets()
    for k in ("vInfo", "vDisk", "vNetwork", "vSnapshot", "vPartition"):
        if k in sh:
            sh[k] = []
    return sh


@pytest.mark.parametrize("sheets", [project.empty_sheets, _hosts_only], ids=["sin_inventario", "inventario_sin_vms"])
@pytest.mark.parametrize("modo", ["hardware", "aconsejar"])
def test_documentos_sin_vms(sheets, modo):
    pytest.importorskip("docx")
    from openpyxl import load_workbook
    sc = scenario.new()
    sc["modo"] = modo
    sc["cliente"] = "Acme Corp"
    p = Plan(sheets(), sc)
    assert not p.has_load and not p.migrate and p.waves == [] and p.method is None
    assert "sin plan de migración" in p.text_summary()
    assert any(r["Categoría"] == "Alcance" for r in p.issues)
    d = tempfile.mkdtemp()
    tmpl = os.path.join(d, "t.xlsx")
    _fake_template(tmpl)
    out = generate(p, d, "nuevo", config_template=tmpl)
    assert len(out) == 4 and all(os.path.getsize(f) > 5000 for f in out)
    heads, text = _doc_text(os.path.join(d, "nuevo_diseno_cliente.docx"))
    assert not any("migración" in h.lower() for h in heads), heads
    assert any("Puesta en marcha" in h for h in heads) and any("Capacidad de la plataforma" in h for h in heads)
    assert "Nueva plataforma Proxmox VE" in text and "No incluye migración" in text
    heads, _ = _doc_text(os.path.join(d, "nuevo_guia_implementacion.docx"))
    assert not any("runbook" in h.lower() for h in heads)
    nums = [int(h.split(".")[0]) for h in heads if h[:1].isdigit()]
    assert nums == list(range(1, len(nums) + 1)) and heads[-1].endswith("Entrega a postventa")   # numeración sin huecos
    wb = load_workbook(os.path.join(d, "nuevo.xlsx"))
    assert "Olas" not in wb.sheetnames and "Ubicación VMs" not in wb.sheetnames and "Nodos destino" in wb.sheetnames
    assert load_workbook(os.path.join(d, "nuevo_hoja_configuracion.xlsx"))["Cover Sheet"]["D5"].value == "Acme Corp"


def test_sin_migracion_con_vms():
    pytest.importorskip("docx")
    sc = scenario.new()
    sc["sin_migracion"] = True
    p = Plan(sample_sheets(), sc)
    assert p.has_load and not p.migrate and not p.waves and len(p.placement) == len(p.an.guests)
    assert p.summary()["vms"] > 0 and "Sin migración" in p.text_summary()
    d = tempfile.mkdtemp()
    generate(p, d, "x", impl=False)
    heads, text = _doc_text(os.path.join(d, "x_diseno_cliente.docx"))
    assert any("Situación actual" in h for h in heads) and any("Reparto previsto" in h for h in heads)
    assert not any("Plan de migración" in h for h in heads)
    assert "Carga prevista" in "\n".join(c.text for t in __import__("docx").Document(os.path.join(d, "x_diseno_cliente.docx")).tables
                                         for r in t.rows for c in r.cells)
    # con migración sigue igual que antes
    p = Plan(sample_sheets(), scenario.new())
    assert p.migrate and p.waves and p.method["id"] == "pbs"


def test_proyecto_ida_y_vuelta():
    d = tempfile.mkdtemp()
    sc = scenario.new()
    sc.update({"cliente": "Acme Corp", "autor": "Preventa", "modo": "hardware", "sin_migracion": True})
    sc["hardware"]["servidores"][0]["cantidad"] = 5
    sc["alcance"]["excluir"] = ["CLU-PROD/100"]
    sh = sample_sheets()
    ui = {"salidas": {"xlsx": True, "design": False}, "plantilla_hoja_config": "C:/plantillas/hoja.xlsx",
          "asbuilt": {"cliente": "Acme", "autor": "PS"}}
    path = project.save(os.path.join(d, "acme"), sc, sh, [os.path.join(d, "inv.xlsx")], ui)
    assert path.endswith(".pveplan") and os.path.exists(path)
    pj = project.load(path)
    assert pj["escenario"]["cliente"] == "Acme Corp" and pj["escenario"]["sin_migracion"] is True
    assert pj["escenario"]["hardware"]["servidores"][0]["cantidad"] == 5
    assert pj["escenario"]["alcance"]["excluir"] == ["CLU-PROD/100"]
    assert pj["ficheros"] == ["inv.xlsx"] and pj["interfaz"] == ui
    assert len(pj["hojas"]["vInfo"]) == len(sh["vInfo"])
    a, b = Plan(sh, sc), Plan(pj["hojas"], pj["escenario"])
    assert a.summary() == b.summary() and a.placement == b.placement
    # un proyecto antiguo sin claves nuevas se completa con los valores por defecto
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    del raw["escenario"]["sin_migracion"], raw["escenario"]["pbs"]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(raw, f)
    pj = project.load(path)
    assert pj["escenario"]["sin_migracion"] is False and pj["escenario"]["pbs"]["incluir"] is True


def test_proyecto_sin_inventario_y_errores():
    d = tempfile.mkdtemp()
    p = project.save(os.path.join(d, "nuevo.pveplan"), scenario.new(), project.empty_sheets(), [], {})
    pj = project.load(p)
    assert pj["hojas"] is not None and not any(pj["hojas"].values())
    bad = os.path.join(d, "otro.pveplan")
    with open(bad, "w", encoding="utf-8") as f:
        json.dump({"cliente": "x"}, f)
    with pytest.raises(project.ProjectError):
        project.load(bad)
    with open(bad, "wb") as f:
        f.write(b"\0" * 100)
    with pytest.raises(project.ProjectError):
        project.load(bad)
    newer = os.path.join(d, "nuevo2.pveplan")
    with open(newer, "w", encoding="utf-8") as f:
        json.dump({"tipo": project.KIND, "formato": project.FORMAT + 1}, f)
    with pytest.raises(project.ProjectError, match="más reciente"):
        project.load(newer)


def test_cli_sin_inventario_y_proyecto():
    pytest.importorskip("docx")
    from pvemigplan.cli import main
    from pvetools.export import to_xlsx
    d = tempfile.mkdtemp()
    assert main(["-o", d, "-n", "nuevo", "--modo", "hardware", "--guardar-proyecto", os.path.join(d, "nuevo"), "-q"]) == 0
    assert {"nuevo.xlsx", "nuevo_diseno_cliente.docx", "nuevo_guia_implementacion.docx", "nuevo.pveplan"} <= set(os.listdir(d))
    to_xlsx(sample_sheets(), os.path.join(d, "inv.xlsx"))
    assert main([os.path.join(d, "inv.xlsx"), "-o", d, "-n", "a", "--sin-migracion", "--cliente", "Acme",
                 "--guardar-proyecto", os.path.join(d, "a.pveplan"), "-q"]) in (0, 1)
    os.remove(os.path.join(d, "inv.xlsx"))      # el proyecto lleva el inventario dentro
    assert main(["-p", os.path.join(d, "a.pveplan"), "-o", d, "-n", "b", "-q"]) in (0, 1)
    _, text = _doc_text(os.path.join(d, "b_diseno_cliente.docx"))
    assert "Acme" in text and "plan de migración por olas" not in text
