"""Marca y aviso de Fsas Technologies (reutiliza el logo de la herramienta de inventario)."""
from __future__ import annotations

from pvetools.branding import COMPANY, asset_path  # noqa: F401  (mismos logos)

DISCLAIMER_VERSION = 1
DISCLAIMER_TITLE = "Aviso de uso"
DISCLAIMER = (
    "USO EXCLUSIVO PARA PROYECTOS DE FSAS TECHNOLOGIES\n"
    "Esta herramienta es de uso interno y está destinada exclusivamente a proyectos de Fsas Technologies. "
    "No está permitida su distribución a clientes ni su uso fuera de ese ámbito.\n\n"
    "PRIVACIDAD Y DATOS\n"
    "• Se ejecuta íntegramente en tu equipo y no sube nada a la nube.\n"
    "• No se conecta a ningún servidor: solo lee el Excel/CSV exportado por PVE Inventory.\n"
    "• No envía datos a Fsas Technologies ni a terceros y no incluye telemetría.\n"
    "• Los planes y documentos se guardan únicamente donde tú decidas. Contienen información del cliente: "
    "trátalos según la política de confidencialidad del proyecto.\n\n"
    "SIN GARANTÍA\n"
    "Los dimensionamientos son estimaciones basadas en el inventario y en los supuestos indicados. "
    "Revísalos y valídalos (compatibilidad y configuraciones con el fabricante) antes de presentarlos o "
    "de comprometer una oferta."
)
SHORT_NOTICE = "Uso exclusivo para proyectos de Fsas Technologies · Ejecución local, sin envío de datos a la nube"
