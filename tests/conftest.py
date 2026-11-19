"""Las pruebas comprueban textos en castellano: fijar el idioma de referencia (el del sistema podría ser otro)."""
import os

os.environ["PVE_LANG"] = "es"

from pvetools.i18n import set_lang  # noqa: E402

set_lang("es")

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _castellano():
    """Cada prueba empieza y termina en castellano (una CLI con --lang cambia el idioma global)."""
    set_lang("es")
    yield
    set_lang("es")
