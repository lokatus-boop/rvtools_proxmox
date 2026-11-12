"""Genera docs/FORMATO_EXPORTACION.md a partir de pvetools/schema.py.  Uso: python tools/gen_format_doc.py"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from pvetools.collector import SHEET_GROUPS  # noqa: E402
from pvetools.schema import FORMAT_VERSION, SCHEMA, SHEET_DESCRIPTIONS  # noqa: E402

out = [
    "# Formato de exportación de PVE Inventory",
    "",
    f"**Versión de formato: {FORMAT_VERSION}** (aparece en la hoja *Aviso* y en la columna *Versión formato* de *vSource*).",
    "",
    "Este documento describe las hojas del Excel y los ficheros CSV que genera la herramienta, para las aplicaciones",
    "que los leen (por ejemplo, el planificador de migración). Se genera con `python tools/gen_format_doc.py`.",
    "",
    "## Reglas",
    "",
    "* **Excel:** la primera hoja es *Aviso* (logo y aviso de uso). Después va una hoja por pestaña, con el nombre exacto de la tabla.",
    "  La fila 1 contiene las cabeceras y los datos empiezan en la fila 2.",
    "* **CSV:** un fichero `<hoja>.csv` por hoja, en UTF-8 con BOM, separador `;`, con las mismas cabeceras. Incluye además `LEEME_AVISO.txt`.",
    "* Una hoja sin datos se exporta igualmente con sus cabeceras.",
    "* **Valores:**",
    "  * Los vacíos se dejan en blanco.",
    "  * Los booleanos se escriben como `Sí` / `No`.",
    "  * Las fechas usan el formato `AAAA-MM-DD hh:mm:ss`, en hora local del equipo que ejecuta la herramienta.",
    "  * Los tamaños van en GiB o MiB, según indique la cabecera, y los porcentajes de 0 a 100.",
    "* La columna `Clúster` identifica el clúster, o `<nodo> (standalone)` si es un nodo independiente. Las VMs/CTs se",
    "  identifican por (`Clúster`, `VMID`) y los nodos por (`Clúster`, `Nodo`).",
    "* **Inventario anonimizado:** la columna `Anonimizado` de *vSource* vale `Sí` (o `Sí (IPs conservadas)`). Los nombres",
    "  son seudónimos consistentes en todas las hojas (`CLUSTER-01`, `NODO-01`, `VM-0001`, `STORAGE-01`…; sufijos `-crit`/`-test`",
    "  como pista de rol), las IPs están transformadas conservando subredes y los textos libres vacíos. El resto de columnas no cambia.",
    "* **Estabilidad:**",
    "  * No se renombran ni se eliminan columnas sin subir la versión de formato.",
    "  * Las columnas nuevas se añaden al final de su hoja.",
    "  * Las hojas nuevas pueden aparecer en cualquier posición: localízalas por su nombre.",
    "",
    "## Hojas",
    "",
]
for group, names in SHEET_GROUPS:
    out.append(f"### {group}")
    out.append("")
    for n in names:
        out.append(f"#### {n}")
        out.append("")
        out.append(SHEET_DESCRIPTIONS.get(n, ""))
        out.append("")
        out.append("| # | Columna |")
        out.append("|---|---|")
        for i, c in enumerate(SCHEMA[n], 1):
            out.append(f"| {i} | {c} |")
        out.append("")
with open(os.path.join(ROOT, "docs", "FORMATO_EXPORTACION.md"), "w", encoding="utf-8") as f:
    f.write("\n".join(out))
print("docs/FORMATO_EXPORTACION.md generado")
