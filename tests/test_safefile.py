"""Guardado seguro de ficheros. Ejecutar: python -m pytest tests/test_safefile.py"""
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from planner_sample import sample_sheets  # noqa: E402
from pvetools.export import to_csv, to_xlsx  # noqa: E402
from pvetools.safefile import (SaveError, atomic_save, atomic_text, ensure_ext, explain,  # noqa: E402
                               safe_filename, verify)


def _leftovers(d):
    return [f for f in os.listdir(d) if f.startswith(".~")]


def test_safe_filename():
    assert safe_filename("ACME: Madrid/Norte") == "ACME_Madrid_Norte"
    assert safe_filename('a<b>c"d|e?f*g\\h') == "a_b_c_d_e_f_g_h"
    assert safe_filename("ACME S.A.") == "ACME_S.A"
    assert safe_filename("  . ") == "informe"
    assert safe_filename("", "plan") == "plan"
    assert safe_filename("CON") == "_CON"
    assert safe_filename("Cliente Ñandú") == "Cliente_Ñandú"


def test_ensure_ext():
    assert ensure_ext("inv.v2", ".xlsx") == "inv.v2.xlsx"
    assert ensure_ext("inv.XLSX", ".xlsx") == "inv.XLSX"


def test_xlsx_atomico_y_valido():
    d = tempfile.mkdtemp()
    p = to_xlsx(sample_sheets(), os.path.join(d, "inv.xlsx"))
    assert os.path.isabs(p) and os.path.isfile(p)
    verify(p)
    assert not _leftovers(d)


def test_fallo_al_escribir_conserva_el_anterior():
    d = tempfile.mkdtemp()
    p = os.path.join(d, "inv.xlsx")
    to_xlsx(sample_sheets(), p)
    before = open(p, "rb").read()

    def broken(tmp):
        with open(tmp, "wb") as f:
            f.write(b"PK\x03\x04 a medias")
        raise OSError("se cortó la escritura")

    with pytest.raises(OSError):
        atomic_save(p, broken)
    assert open(p, "rb").read() == before
    assert not _leftovers(d)


def test_detecta_zip_danado_y_ceros():
    d = tempfile.mkdtemp()
    p = os.path.join(d, "x.xlsx")
    with pytest.raises(SaveError):
        atomic_save(p, lambda t: open(t, "wb").write(b"\x00" * 65536))
    with pytest.raises(SaveError):
        atomic_save(p, lambda t: open(t, "wb").write(b"PK\x03\x04" + b"\x01" * 100))
    assert not os.path.exists(p) and not _leftovers(d)


def test_texto_atomico():
    d = tempfile.mkdtemp()
    p = os.path.join(d, "a.csv")
    with atomic_text(p, encoding="utf-8-sig") as f:
        f.write("x;y\n")
    assert open(p, encoding="utf-8-sig").read() == "x;y\n"
    with pytest.raises(ValueError):
        with atomic_text(p) as f:
            f.write("roto")
            raise ValueError
    assert open(p, encoding="utf-8-sig").read() == "x;y\n"
    assert not _leftovers(d)
    paths = to_csv(sample_sheets(), os.path.join(d, "csv"))
    assert paths and not _leftovers(os.path.join(d, "csv"))


def test_mensajes():
    assert "abierto en Excel" in explain(PermissionError(13, "denied"), "C:/x/inv.xlsx")
    assert "no es válida" in explain(FileNotFoundError(2, "no"), "C:/x/inv.xlsx")
