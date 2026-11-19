"""Traducciones de PVE Inventory y PVE Migration Planner (es, en, de, fr, pt, it).

Uso en el código:

* ``_("Texto en castellano {x}", x=valor)``: devuelve el texto en el idioma activo (y lo formatea).
* ``N_("Texto")``: marca un texto que se traduce más tarde con ``_()`` (constantes de módulo).
* ``D("Plantilla {x}", x=valor)``: dato del inventario. Se guarda SIEMPRE en castellano (es el formato interno
  y el que entienden las comprobaciones) y se traduce al exportar o al mostrarlo con ``data_out()``.

El castellano es el idioma de referencia: los catálogos (``tr_catalog.py`` de cada aplicación) son diccionarios
``{texto en castellano: (en, de, fr, pt, it)}``. Un texto sin traducción se muestra en castellano.

Los Excel/CSV del inventario se escriben en el idioma elegido (cabeceras y valores como Sí/No) y se leen en
cualquiera de los seis: ``header_in()`` y ``data_in()`` los devuelven a la forma interna en castellano.
"""
from __future__ import annotations

import contextlib
import locale
import os
import re

LANGS = {"es": "Español", "en": "English", "de": "Deutsch", "fr": "Français", "pt": "Português", "it": "Italiano"}
ORDER = ("en", "de", "fr", "pt", "it")   # orden de las traducciones en los catálogos
DEFAULT = "es"
FALLBACK = "en"                          # idioma si el del sistema no está entre los seis

_lang = DEFAULT
_catalog: dict[str, tuple] = {}
_data_terms: set[str] = set()
_data_templates: set[str] = set()
_cache: dict = {}


# --------------------------------------------------------------------------- catálogos
def register(catalog: dict, data_terms=(), data_templates=()):
    """Añade un catálogo {castellano: (en, de, fr, pt, it)} y los textos que son datos del inventario."""
    _catalog.update(catalog)
    _data_terms.update(data_terms)
    _data_templates.update(data_templates)
    _cache.clear()


def catalog() -> dict:
    return _catalog


# --------------------------------------------------------------------------- idioma activo
def norm(code) -> str | None:
    """'de_DE', 'pt-BR', 'English', 'Deutsch'… → 'de', 'pt', 'en', 'de' (None si no es uno de los seis)."""
    if not code:
        return None
    c = str(code).strip()
    for k, v in LANGS.items():
        if c.lower() == v.lower():
            return k
    c = c.replace("-", "_").split("_")[0].split(".")[0].lower()
    aliases = {"spanish": "es", "castellano": "es", "english": "en", "german": "de", "french": "fr",
               "portuguese": "pt", "italian": "it", "deutsch": "de", "français": "fr", "francais": "fr",
               "português": "pt", "portugues": "pt", "italiano": "it", "español": "es", "espanol": "es"}
    c = aliases.get(c, c)
    return c if c in LANGS else None


def system_lang() -> str:
    """Idioma del sistema operativo (Windows: idioma de la interfaz del usuario)."""
    cands = []
    if os.name == "nt":
        try:
            import ctypes
            lcid = ctypes.windll.kernel32.GetUserDefaultUILanguage()  # type: ignore[attr-defined]
            cands.append(locale.windows_locale.get(lcid))
        except Exception:  # noqa: BLE001
            pass
    for var in ("LC_ALL", "LC_MESSAGES", "LANGUAGE", "LANG"):
        cands.append(os.environ.get(var, "").split(":")[0])
    try:
        cands.append(locale.getlocale()[0])
    except (ValueError, TypeError):
        pass
    for c in cands:
        n = norm(c)
        if n:
            return n
    return FALLBACK


def detect(saved: str | None = None) -> str:
    """Idioma a usar: variable de entorno PVE_LANG, el guardado en los ajustes o el del sistema."""
    return norm(os.environ.get("PVE_LANG")) or norm(saved) or system_lang()


def set_lang(code) -> str:
    global _lang
    _lang = norm(code) or DEFAULT
    return _lang


def get_lang() -> str:
    return _lang


@contextlib.contextmanager
def language(code):
    """Cambia el idioma temporalmente (p. ej. para generar un documento en otro idioma)."""
    prev = _lang
    set_lang(code or prev)
    try:
        yield
    finally:
        set_lang(prev)


# --------------------------------------------------------------------------- traducción
def tr(msg, lang=None, **kw):
    return _tr(msg, lang, kw)


def _tr(msg, lang, kw):
    # Los argumentos de formato van en un dict aparte para que un marcador llamado
    # {lang} (p. ej. «Idioma: {lang}») no choque con el parámetro de idioma.
    lang = lang or _lang
    text = msg
    if lang != DEFAULT and isinstance(msg, str):
        e = _catalog.get(msg)
        if e:
            text = e[ORDER.index(lang)] or msg
    if kw:
        try:
            return text.format(**kw)
        except (KeyError, IndexError, ValueError):
            return msg.format(**kw)
    return text


def _(msg, **kw):
    return _tr(msg, None, kw)


def N_(msg):
    return msg


def D(msg, **kw):
    """Dato del inventario: plantilla en castellano (forma interna). Se traduce al exportar/mostrar."""
    return msg.format(**kw) if kw else msg


def yes_no(v: bool) -> str:
    return _("Sí") if v else _("No")


_SEP = {"es": (".", ","), "de": (".", ","), "it": (".", ","), "pt": (".", ","), "fr": ("\u202f", ","), "en": (",", ".")}
_DATE = {"es": "%d/%m/%Y", "de": "%d.%m.%Y", "fr": "%d/%m/%Y", "it": "%d/%m/%Y", "pt": "%d/%m/%Y", "en": "%Y-%m-%d"}


def number(v, decimals=None, lang=None) -> str:
    """Número con los separadores de miles y decimales del idioma (1.234,5 · 1,234.5 · 1 234,5)."""
    th, dec = _SEP.get(lang or _lang, (".", ","))
    if decimals is None:
        decimals = 0 if isinstance(v, int) or float(v).is_integer() and abs(v) >= 100 else 1
    s = f"{v:,.{decimals}f}"
    return s.replace(",", "\0").replace(".", dec).replace("\0", th)


def fmt_date(d, lang=None) -> str:
    """Fecha corta en el formato habitual del idioma."""
    return d.strftime(_DATE.get(lang or _lang, "%d/%m/%Y")) if d else ""


# --------------------------------------------------------------------------- datos (valores de celdas)
_PH = re.compile(r"\{([A-Za-z_]\w*)(![rsa])?(:[^{}]*)?\}")


def _compile(tpl: str):
    """Plantilla → (regex, nombres). None si es demasiado genérica para reconocerla con seguridad."""
    out, names, pos = [], [], 0
    for m in _PH.finditer(tpl):
        out.append(re.escape(tpl[pos:m.start()].replace("{{", "{").replace("}}", "}")))
        name = m.group(1)
        if name in names:
            out.append(f"(?P={name})")
        else:
            out.append(f"(?P<{name}>.+?)")
            names.append(name)
        pos = m.end()
    out.append(re.escape(tpl[pos:].replace("{{", "{").replace("}}", "}")))
    literal = _PH.sub("", tpl)
    if sum(c.isalpha() for c in literal) < 3:
        return None
    return re.compile("^" + "".join(out) + "$", re.S), names


def _fill(tpl: str, values: dict) -> str:
    def rep(m):
        return str(values.get(m.group(1), m.group(0)))
    return _PH.sub(rep, tpl).replace("{{", "{").replace("}}", "}")


def _tables(src: str, dst: str):
    """Tablas de conversión de datos entre dos idiomas: (exactos, plantillas compiladas)."""
    key = (src, dst)
    if key in _cache:
        return _cache[key]

    def text(msg, lang):
        return tr(msg, lang=lang)

    exact = {}
    for t in _data_terms:
        a, b = text(t, src), text(t, dst)
        if a != b:
            exact.setdefault(a, b)
    tpls = []
    for t in _data_templates:
        a, b = text(t, src), text(t, dst)
        c = _compile(a)
        if c and a != b:
            tpls.append((c[0], b))
    tpls.sort(key=lambda x: -len(x[0].pattern))
    _cache[key] = (exact, tpls)
    return _cache[key]


def convert(value, src: str, dst: str, depth: int = 0, templates: bool = True):
    """Traduce un valor de celda (Sí/No, estados, avisos de vHealth…) de un idioma a otro."""
    if src == dst or not isinstance(value, str) or not value:
        return value
    exact, tpls = _tables(src, dst)
    if value in exact:
        return exact[value]
    if depth > 2 or not templates:
        return value
    for rx, target in tpls:
        m = rx.match(value)
        if m:
            vals = {k: convert(v, src, dst, depth + 1) for k, v in m.groupdict().items()}
            return _fill(target, vals)
    return value


def data_out(value, lang=None):
    """Valor interno (castellano) → idioma activo (o «lang»)."""
    return convert(value, DEFAULT, lang or _lang)


def data_in(value, lang=None):
    """Valor leído de un Excel/CSV en cualquier idioma → forma interna en castellano."""
    if not isinstance(value, str) or not value:
        return value
    if lang:
        return convert(value, lang, DEFAULT)
    for code in ORDER:
        exact, tpls = _tables(code, DEFAULT)
        if value in exact:
            return exact[value]
    for code in ORDER:
        out = convert(value, code, DEFAULT)
        if out != value:
            return out
    return value


def _col_mode(sheet, col):
    """Qué se traduce en una columna del inventario: 2 = términos y frases, 1 = solo términos, 0 = nada."""
    from .schema import NAME_COLUMNS, TEXT_COLUMNS
    if col in TEXT_COLUMNS.get(sheet, ()):
        return 2
    return 0 if col in NAME_COLUMNS else 1


def cell_out(sheet, col, value, lang=None):
    """Valor de una celda del inventario (castellano) → idioma de exportación."""
    lang = lang or _lang
    if lang == DEFAULT or not isinstance(value, str):
        return value
    mode = _col_mode(sheet, col)
    return convert(value, DEFAULT, lang, templates=mode == 2) if mode else value


def cell_in(sheet, col, value, lang):
    """Valor leído de un export en «lang» → forma interna (castellano)."""
    if not lang or lang == DEFAULT or not isinstance(value, str):
        return value
    mode = _col_mode(sheet, col)
    return convert(value, lang, DEFAULT, templates=mode == 2) if mode else value


def rows_in(sheet, rows, lang=None):
    """Filas de una hoja leída de un Excel/CSV en cualquier idioma → cabeceras y valores internos.

    «lang» es el idioma del fichero (si no se indica, se deduce de las cabeceras)."""
    from .schema import SCHEMA
    cols = SCHEMA.get(sheet)
    if not rows or not cols:
        return rows
    lang = lang or guess_lang(rows[0].keys()) or DEFAULT
    hmap = {h: header_in(cols, h) for h in rows[0].keys()}
    if lang == DEFAULT and all(k == v for k, v in hmap.items()):
        return rows
    out = []
    for r in rows:
        out.append({hmap.get(k) or header_in(cols, k): cell_in(sheet, hmap.get(k) or k, v, lang) for k, v in r.items()})
    return out


def header_in(sheet_cols, header: str):
    """Cabecera en cualquier idioma → nombre interno (castellano) de la columna de esa hoja."""
    key = ("h", tuple(sheet_cols))
    if key not in _cache:
        m = {}
        for c in sheet_cols:
            m[c.lower()] = c
            for code in ORDER:
                m.setdefault(tr(c, lang=code).lower(), c)
        _cache[key] = m
    return _cache[key].get(str(header).strip().lower(), header)


def guess_lang(headers) -> str | None:
    """Idioma en el que está escrito un export a partir de sus cabeceras (None si no se sabe)."""
    hs = {str(h).strip() for h in headers if h}
    best, score = None, 0
    for code in (DEFAULT,) + ORDER:
        n = sum(1 for h in hs if h in _header_index(code))
        if n > score:
            best, score = code, n
    return best


def _header_index(code):
    """Cabeceras propias de un idioma: las de otro idioma que no coinciden con el castellano; para el
    castellano, las que no existen en ningún otro idioma."""
    key = ("hi", code)
    if key not in _cache:
        from .schema import SCHEMA
        cols = [c for cs in SCHEMA.values() for c in cs]
        sets = {lg: {tr(c, lang=lg) for c in cols} for lg in (DEFAULT,) + ORDER}
        if code == DEFAULT:
            _cache[key] = sets[DEFAULT] - set().union(*(sets[lg] for lg in ORDER))
        else:
            _cache[key] = sets[code] - sets[DEFAULT]
    return _cache[key]


# --------------------------------------------------------------------------- argparse
_ARGPARSE = {   # inglés (argparse) → (es, de, fr, pt, it)
    "usage: ": ("uso: ", "Aufruf: ", "utilisation : ", "uso: ", "uso: "),
    "options": ("opciones", "Optionen", "options", "opções", "opzioni"),
    "positional arguments": ("argumentos posicionales", "Positionsargumente", "arguments positionnels", "argumentos posicionais", "argomenti posizionali"),
    "show this help message and exit": ("muestra esta ayuda y sale", "diese Hilfe anzeigen und beenden", "affiche cette aide et quitte", "mostra esta ajuda e sai", "mostra questo aiuto ed esce"),
    "show program's version number and exit": ("muestra la versión y sale", "Versionsnummer anzeigen und beenden", "affiche la version et quitte", "mostra a versão e sai", "mostra la versione ed esce"),
    "the following arguments are required: %s": ("faltan argumentos obligatorios: %s", "folgende Argumente sind erforderlich: %s", "les arguments suivants sont obligatoires : %s", "os seguintes argumentos são obrigatórios: %s", "i seguenti argomenti sono obbligatori: %s"),
    "%(prog)s: error: %(message)s\n": ("%(prog)s: error: %(message)s\n", "%(prog)s: Fehler: %(message)s\n", "%(prog)s : erreur : %(message)s\n", "%(prog)s: erro: %(message)s\n", "%(prog)s: errore: %(message)s\n"),
    "unrecognized arguments: %s": ("argumentos no reconocidos: %s", "unbekannte Argumente: %s", "arguments non reconnus : %s", "argumentos não reconhecidos: %s", "argomenti non riconosciuti: %s"),
    "expected one argument": ("se esperaba un valor", "ein Wert erwartet", "une valeur attendue", "esperava-se um valor", "previsto un valore"),
    "argument %(argument_name)s: %(message)s": ("argumento %(argument_name)s: %(message)s", "Argument %(argument_name)s: %(message)s", "argument %(argument_name)s : %(message)s", "argumento %(argument_name)s: %(message)s", "argomento %(argument_name)s: %(message)s"),
    "invalid choice: %(value)r (choose from %(choices)s)": ("opción no válida: %(value)r (elige entre %(choices)s)", "ungültige Auswahl: %(value)r (wähle aus %(choices)s)", "choix invalide : %(value)r (choisir parmi %(choices)s)", "opção inválida: %(value)r (escolha entre %(choices)s)", "scelta non valida: %(value)r (scegliere tra %(choices)s)"),
    "not allowed with argument %s": ("no se permite con el argumento %s", "nicht erlaubt mit Argument %s", "non autorisé avec l'argument %s", "não permitido com o argumento %s", "non consentito con l'argomento %s"),
    "one of the arguments %s is required": ("se necesita uno de los argumentos %s", "eines der Argumente %s ist erforderlich", "l'un des arguments %s est obligatoire", "é necessário um dos argumentos %s", "è richiesto uno degli argomenti %s"),
}


def translate_argparse():
    """Traduce los textos propios de argparse («usage:», «options»…) al idioma activo."""
    import argparse
    import gettext

    def g(s):
        e = _ARGPARSE.get(s)
        if e and _lang != "en":
            return e[("es", "de", "fr", "pt", "it").index(_lang)]
        return gettext.gettext(s)
    argparse._ = g  # type: ignore[attr-defined]


def lang_from_argv(argv) -> str | None:
    """Lee --lang/--idioma de la línea de comandos antes de construir el parser (los textos de ayuda se traducen)."""
    argv = list(argv or [])
    for i, a in enumerate(argv):
        for opt in ("--lang", "--idioma"):
            if a == opt and i + 1 < len(argv):
                return norm(argv[i + 1])
            if a.startswith(opt + "="):
                return norm(a.split("=", 1)[1])
    return None


def setup_cli(argv) -> str:
    """Idioma de la CLI: --lang, PVE_LANG o el del sistema."""
    code = set_lang(lang_from_argv(argv) or detect())
    translate_argparse()
    return code


# Catálogo del inventario (se registra al importar el módulo)
from .tr_catalog import CATALOG as _CAT, DATA_TEMPLATES as _DT, DATA_TERMS as _DTERMS  # noqa: E402

register(_CAT, _DTERMS, _DT)
