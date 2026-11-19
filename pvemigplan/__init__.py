__version__ = "1.0.0"
APP_NAME = "PVE Migration Planner"

from pvetools.i18n import register as _register  # noqa: E402

from .tr_catalog import CATALOG as _CATALOG  # noqa: E402

# Valores de las tablas del plan que se muestran en el idioma del documento (tipos de ola, antigüedad de backups…)
_register(_CATALOG, ("BLOQUEO", "Piloto", "Con bloqueos", "Críticas", "Estándar", "Sin copia", "≤ 1 día", "2-7 días", "8-30 días",
                     "> 30 días", "plantilla"))
