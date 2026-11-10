"""Marca y aviso legal de Fsas Technologies."""
from __future__ import annotations

import os
import sys

COMPANY = "Fsas Technologies"
DISCLAIMER_VERSION = 1

DISCLAIMER_TITLE = "Aviso de uso"
DISCLAIMER = (
    "USO EXCLUSIVO PARA PROYECTOS DE FSAS TECHNOLOGIES\n"
    "Esta herramienta es de uso interno y está destinada exclusivamente a proyectos de Fsas Technologies. "
    "No está permitida su distribución ni su uso fuera de ese ámbito.\n\n"
    "PRIVACIDAD Y DATOS\n"
    "• Se ejecuta íntegramente en tu equipo y no sube nada a la nube.\n"
    "• Solo se conecta a los servidores Proxmox VE que tú indicas, a través de su API y en modo de solo lectura: "
    "no modifica ninguna configuración.\n"
    "• No envía datos a Fsas Technologies ni a terceros y no incluye telemetría.\n"
    "• No guarda contraseñas ni tokens en disco; solo recuerda la lista de hosts y usuarios.\n"
    "• Los informes (Excel/CSV) se guardan únicamente donde tú decidas. Pueden contener información sensible "
    "del cliente (IPs, nombres, configuración): trátalos según la política de confidencialidad del proyecto.\n\n"
    "SIN GARANTÍA\n"
    "Se proporciona \"tal cual\", sin garantía de ningún tipo. Revisa los datos antes de usarlos en entregables."
)
SHORT_NOTICE = "Uso exclusivo para proyectos de Fsas Technologies · Ejecución local, sin envío de datos a la nube"


def asset_path(name: str) -> str:
    """Ruta a un recurso, tanto en desarrollo como dentro del .exe de PyInstaller."""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return os.path.join(base, "pvetools", "assets", name)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", name)
