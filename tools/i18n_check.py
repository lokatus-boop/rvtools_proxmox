"""Comprueba las traducciones: lista los textos marcados en el código que no están en los catálogos.

uso: python tools/i18n_check.py [--json fichero]   (código de salida 1 si falta alguno)

Recoge los textos de _(), N_(), tr() y D(), las columnas del formato (pvetools/schema.py) y las cabeceras de las
tablas de los documentos del planificador (claves de las filas y listas de cabeceras).
"""
from __future__ import annotations

import ast
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

TABLE_FUNCS = {"table", "_table", "kv", "_kv", "checklist", "bullets", "_rows_table"}
HEADER_RE = re.compile(r"^[A-ZÁÉÍÓÚÑ¿(Nº]|[áéíóúñ]| ")


def _is_header(s: str) -> bool:
    return bool(s) and bool(HEADER_RE.search(s)) and not s.startswith(("http", "/")) and len(s) < 80


def collect(path: str):
    msgs, data = {}, {}
    src = open(path, encoding="utf-8").read()
    tree = ast.parse(src)
    planner = os.sep + "pvemigplan" + os.sep in path
    for n in ast.walk(tree):
        if isinstance(n, ast.Call):
            f = n.func
            name = f.id if isinstance(f, ast.Name) else (f.attr if isinstance(f, ast.Attribute) else "")
            if name in ("_", "N_", "tr", "D") and n.args and isinstance(n.args[0], ast.Constant) \
                    and isinstance(n.args[0].value, str):
                (data if name == "D" else msgs)[n.args[0].value] = f"{os.path.relpath(path, ROOT)}:{n.lineno}"
            if planner and name in TABLE_FUNCS:
                for a in n.args:
                    for c in ast.walk(a):
                        if isinstance(c, ast.Constant) and isinstance(c.value, str) and _is_header(c.value):
                            msgs.setdefault(c.value, f"{os.path.relpath(path, ROOT)}:{c.lineno}")
        if planner and isinstance(n, ast.Dict):
            for k in n.keys:
                if isinstance(k, ast.Constant) and isinstance(k.value, str) and _is_header(k.value) \
                        and not k.value.islower():
                    msgs.setdefault(k.value, f"{os.path.relpath(path, ROOT)}:{k.lineno}")
    return msgs, data


def all_texts():
    msgs, data = {}, {}
    for pkg in ("pvetools", "pvemigplan"):
        for fn in sorted(os.listdir(os.path.join(ROOT, pkg))):
            if fn.endswith(".py") and not fn.startswith("tr_catalog"):
                m, d = collect(os.path.join(ROOT, pkg, fn))
                for k, v in m.items():
                    msgs.setdefault(k, v)
                for k, v in d.items():
                    data.setdefault(k, v)
    from pvetools.schema import SCHEMA, SHEET_DESCRIPTIONS
    for cols in SCHEMA.values():
        for c in cols:
            msgs.setdefault(c, "pvetools/schema.py")
    for d in SHEET_DESCRIPTIONS.values():
        msgs.setdefault(d, "pvetools/schema.py")
    return msgs, data


def main():
    import pvemigplan  # noqa: F401 - registra el catálogo del planificador
    from pvetools.i18n import ORDER, catalog
    msgs, data = all_texts()
    cat = catalog()
    missing = {}
    for k, where in {**msgs, **data}.items():
        e = cat.get(k)
        if not e or len(e) != len(ORDER) or not all(e):
            missing[k] = where
    # marcadores {x} que no coinciden entre el original y la traducción
    bad = []
    ph = re.compile(r"\{(\w+)[^{}]*\}")
    for k, e in cat.items():
        want = sorted(ph.findall(k))
        for lang, t in zip(ORDER, e):
            if t and sorted(ph.findall(t)) != want:
                bad.append((k, lang, t))
    if "--json" in sys.argv:
        with open(sys.argv[sys.argv.index("--json") + 1], "w", encoding="utf-8") as f:
            json.dump(missing, f, ensure_ascii=False, indent=1)
    print(f"Textos: {len(msgs)} + {len(data)} datos · sin traducir: {len(missing)} · marcadores distintos: {len(bad)}")
    for k, lang, t in bad[:40]:
        print(f"  [{lang}] {k!r} → {t!r}")
    return 1 if missing or bad else 0


if __name__ == "__main__":
    sys.exit(main())
