"""Proyecto del planificador: un único fichero local (.pveplan) con todo lo necesario para retomar el trabajo.

Guarda el inventario ya cargado (las hojas, no solo la ruta: el Excel original puede moverse o borrarse), el
escenario completo (cliente, autor, hardware introducido, red, PBS, migración, «sin migración»…) y las opciones de
la interfaz (documentos marcados, plantilla de la hoja de configuración, datos del as-built y del informe de análisis).

El fichero es JSON en UTF-8 y nunca sale del equipo. Contiene los datos del inventario del cliente: trátalo con la
misma confidencialidad que el Excel de PVE Inventory.
"""
from __future__ import annotations

import datetime as dt
import json
import os

from . import APP_NAME, __version__
from .scenario import merge, new
from pvetools.safefile import atomic_text, ensure_ext
from pvetools.i18n import _
from pvetools.schema import SCHEMA

EXT = ".pveplan"
KIND = "PVE Migration Planner · proyecto"
FORMAT = 1


class ProjectError(Exception):
    pass


def _jsonable(v):
    if isinstance(v, (dt.datetime, dt.date, dt.time)):
        return v.isoformat(sep=" ") if isinstance(v, dt.datetime) else v.isoformat()
    if isinstance(v, (set, tuple)):
        return list(v)
    return str(v)


def save(path: str, scenario: dict, sheets: dict | None = None, files: list | None = None, ui: dict | None = None) -> str:
    """Guarda el proyecto de forma atómica y devuelve la ruta absoluta (con la extensión .pveplan)."""
    path = os.path.abspath(ensure_ext(os.path.normpath(path), EXT))
    data = {
        "tipo": KIND,
        "formato": FORMAT,
        "aplicacion": f"{APP_NAME} {__version__}",
        "guardado": dt.datetime.now().isoformat(timespec="seconds"),
        "escenario": scenario,
        "inventario": {
            "ficheros": [os.path.basename(str(f).rstrip("/\\")) for f in (files or [])],
            "rutas": [os.path.abspath(f) for f in (files or [])],
            "hojas": {k: v for k, v in (sheets or {}).items() if v} if sheets is not None else None,
        },
        "interfaz": ui or {},
    }
    with atomic_text(path, encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"), default=_jsonable)
    return path


def load(path: str) -> dict:
    """Lee un proyecto. Devuelve {"escenario", "hojas" (o None), "ficheros", "rutas", "interfaz", "aplicacion"}."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except UnicodeDecodeError as exc:
        raise ProjectError(_("{basename} no es un proyecto del planificador.", basename=os.path.basename(path))) from exc
    except json.JSONDecodeError as exc:
        raise ProjectError(_("{basename} está dañado o no es un proyecto del planificador ({exc}).", basename=os.path.basename(path), exc=exc)) from exc
    if not isinstance(data, dict) or data.get("tipo") != KIND:
        raise ProjectError(_("{basename} no es un proyecto de {APP_NAME}.", basename=os.path.basename(path), APP_NAME=APP_NAME))
    if int(data.get("formato") or 0) > FORMAT:
        raise ProjectError(_("El proyecto se guardó con una versión más reciente ({app}). Actualiza {APP_NAME} para abrirlo.", app=data.get('aplicacion'), APP_NAME=APP_NAME))
    inv = data.get("inventario") or {}
    hojas = inv.get("hojas")
    if hojas is not None:
        hojas = {k: list(v or []) for k, v in hojas.items()}
        for s in SCHEMA:
            hojas.setdefault(s, [])
    return {
        "escenario": merge(new(), data.get("escenario") or {}),
        "hojas": hojas,
        "ficheros": list(inv.get("ficheros") or []),
        "rutas": list(inv.get("rutas") or []),
        "interfaz": dict(data.get("interfaz") or {}),
        "aplicacion": data.get("aplicacion") or "",
        "guardado": data.get("guardado") or "",
    }


def empty_sheets() -> dict:
    """Inventario vacío: para documentar un clúster nuevo sin inventario de origen."""
    return {s: [] for s in SCHEMA}
