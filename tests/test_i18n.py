"""Idiomas: catálogos completos, Excel/CSV en otro idioma que el planificador vuelve a leer, CLI con --lang.

Ejecutar: python -m pytest tests/test_i18n.py"""
import os
import subprocess
import sys
import tempfile

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(__file__))

import mock_pve  # noqa: E402
import pvemigplan  # noqa: E402,F401  (registra el catálogo del planificador)
from pvetools.i18n import LANGS, ORDER, catalog, guess_lang, header_in, language, set_lang, tr  # noqa: E402
from pvetools.schema import SCHEMA  # noqa: E402
from test_inventory import serve  # noqa: E402

TOK = {"user": "auditor@pve", "token_id": "inv", "token_secret": "secret"}


def test_catalogs_complete():
    """Todo texto marcado en el código tiene traducción a los cinco idiomas y con los mismos marcadores {x}."""
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import i18n_check
    assert i18n_check.main() == 0


@pytest.mark.parametrize("lang", list(LANGS))
def test_headers_unique_and_reversible(lang):
    """En cada idioma las cabeceras de una hoja son distintas entre sí y se reconocen al leer el fichero."""
    for sheet, cols in SCHEMA.items():
        heads = [tr(c, lang=lang) for c in cols]
        dup = {h for h in heads if heads.count(h) > 1}
        assert not dup, f"{lang} {sheet}: cabeceras repetidas {dup}"
        assert [header_in(cols, h) for h in heads] == cols, f"{lang} {sheet}"
    assert guess_lang([tr(c, lang=lang) for cols in SCHEMA.values() for c in cols]) == lang


def test_sheet_names_fit_excel():
    for es, tr5 in catalog().items():
        if len(es) <= 31 and es in {"Correspondencia", "Aviso", "LEEME_AVISO"}:
            assert all(len(t) <= 31 for t in tr5)


def _inventory():
    from pvetools.collector import Inventory
    return Inventory(query_agent=True).collect([{**TOK, "host": serve(mock_pve.cluster_data())},
                                               {**TOK, "host": serve(mock_pve.standalone_data())}])


def test_export_in_german_reads_back():
    """Un inventario exportado en alemán (Excel y CSV) se lee igual que el castellano en el planificador."""
    from openpyxl import load_workbook

    from pvemigplan import scenario
    from pvemigplan.assessment import Assessment
    from pvemigplan.loader import load
    from pvemigplan.planner import Plan
    from pvetools.export import to_csv, to_xlsx
    sh = _inventory()
    d = tempfile.mkdtemp()
    to_xlsx(sh, os.path.join(d, "es.xlsx"))
    to_csv(sh, os.path.join(d, "csv_es"))
    with language("de"):
        to_xlsx(sh, os.path.join(d, "de.xlsx"))
        to_csv(sh, os.path.join(d, "csv_de"))
    ws = load_workbook(os.path.join(d, "de.xlsx"), read_only=True)["vHealth"]
    rows = list(ws.iter_rows(values_only=True))
    head = [h for h in rows[0] if h]
    assert "Schweregrad" in head and "Meldung" in head
    sev = {r[head.index("Schweregrad")] for r in rows[1:] if r and r[0]}
    assert sev and sev <= {"KRITISCH", "WARNUNG", "INFO"}
    es, de, csv_es, csv = (load(os.path.join(d, p)) for p in ("es.xlsx", "de.xlsx", "csv_es", "csv_de"))
    for name in SCHEMA:        # mismos valores internos que el export en castellano (salvo vSource «Idioma»)
        if name != "vSource":
            assert de.get(name) == es.get(name), name
            assert csv.get(name) == csv_es.get(name), name
    for other in (de, csv):
        pa, pb = Plan(es, scenario.new()), Plan(other, scenario.new())
        assert pb.summary() == pa.summary()
        assert len(Assessment(other).findings) == len(Assessment(es).findings)
    assert es["vSource"][0]["Idioma"] == "es" and de["vSource"][0]["Idioma"] == "de"


@pytest.mark.parametrize("lang", ORDER)
def test_planner_documents_in_every_language(lang):
    """Excel y Word del planificador en cada idioma (sin textos en castellano en los títulos)."""
    pytest.importorskip("docx")
    pytest.importorskip("matplotlib")
    from docx import Document

    from planner_sample import sample_sheets
    from pvemigplan.cli import main
    from pvetools.export import to_xlsx
    d = tempfile.mkdtemp()
    inv = os.path.join(d, "inv.xlsx")
    to_xlsx(sample_sheets(), inv)
    out = os.path.join(d, "out")
    assert main([inv, "-o", out, "--customer", "Demo", "-q", "--lang", lang]) == 0
    files = sorted(os.listdir(out))
    assert files and not any(f.startswith("plan_migracion") for f in files)
    doc = next(f for f in files if f.endswith(tr("_diseno_cliente", lang=lang) + ".docx"))
    text = "\n".join(p.text for p in Document(os.path.join(out, doc)).paragraphs)
    assert tr("{next}. Resumen ejecutivo", lang=lang).split(". ", 1)[1] in text
    assert "Resumen ejecutivo" not in text and "Plataforma propuesta" not in text
    set_lang("es")
    assert main([inv, "--assessment", "-o", out, "-q", "--no-word", "--lang", lang]) == 0


@pytest.mark.parametrize("lang,word", [("en", "usage:"), ("de", "Aufruf:"), ("fr", "utilisation"), ("it", "uso:")])
def test_cli_lang(lang, word):
    for script in ("pveinventory_cli.py", "pvemigplan_cli.py"):
        r = subprocess.run([sys.executable, os.path.join(ROOT, script), "--lang", lang, "--help"],
                           capture_output=True, text=True, env={**os.environ, "PVE_LANG": "es"})
        assert r.returncode == 0 and word in r.stdout, (script, r.stdout[:200], r.stderr[-500:])
