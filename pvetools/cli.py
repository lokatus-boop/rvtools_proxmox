"""Modo línea de comandos.

Ejemplos:
  pveinventory.exe --host pve1.local --user auditor@pve --token-id inventario --token-secret XXXX -o inventario.xlsx
  pveinventory.exe --host pve1 --host pve2:8006 --user root@pam --password-env PVE_PASSWORD --csv .\\csv
"""
from __future__ import annotations

import argparse
import datetime as dt
import getpass
import os
import sys

from . import APP_NAME, __version__
from .branding import SHORT_NOTICE
from .collector import Inventory
from .export import to_csv, to_xlsx


def build_parser():
    p = argparse.ArgumentParser(prog="pveinventory", description=f"{APP_NAME} {__version__}: inventario de Proxmox VE 8/9 a Excel/CSV",
                                epilog=SHORT_NOTICE + ". Solo lectura: no modifica nada en Proxmox.")
    p.add_argument("--host", action="append", required=True,
                   help="Nodo PVE (nombre o IP, opcional :puerto). Repetible: un nodo por clúster basta; para nodos sueltos, uno por nodo")
    p.add_argument("--user", required=True, help="Usuario con realm, p. ej. root@pam o auditor@pve")
    auth = p.add_mutually_exclusive_group()
    auth.add_argument("--password", help="Contraseña (mejor usar --password-env o dejar que la pida)")
    auth.add_argument("--password-env", metavar="VAR", help="Variable de entorno con la contraseña")
    auth.add_argument("--token-id", help="ID del API token (la parte tras '!')")
    p.add_argument("--token-secret", help="Secreto del API token (o variable PVE_TOKEN_SECRET)")
    p.add_argument("--verify-ssl", action="store_true", help="Verificar certificado (por defecto se aceptan autofirmados)")
    p.add_argument("--no-agent", action="store_true", help="No consultar el QEMU guest agent (más rápido, sin IPs de VMs)")
    p.add_argument("-o", "--xlsx", help="Fichero Excel de salida (por defecto pve_inventory_FECHA.xlsx)")
    p.add_argument("--csv", metavar="CARPETA", help="Exportar además una carpeta con un CSV por hoja")
    p.add_argument("-q", "--quiet", action="store_true")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return p


def main(argv=None):
    a = build_parser().parse_args(argv)
    base = {"user": a.user, "verify_ssl": a.verify_ssl}
    if a.token_id:
        base["token_id"] = a.token_id
        base["token_secret"] = a.token_secret or os.environ.get("PVE_TOKEN_SECRET")
        if not base["token_secret"]:
            base["token_secret"] = getpass.getpass("Secreto del API token: ")
    else:
        pw = a.password or (os.environ.get(a.password_env) if a.password_env else None)
        base["password"] = pw if pw is not None else getpass.getpass(f"Contraseña de {a.user}: ")
    conns = [{**base, "host": h} for h in a.host]
    log = (lambda m: None) if a.quiet else (lambda m: print(m, file=sys.stderr))
    log(f"{APP_NAME} {__version__} — {SHORT_NOTICE}")
    sheets = Inventory(progress=log, query_agent=not a.no_agent).collect(conns)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    out = a.xlsx or f"pve_inventory_{stamp}.xlsx"
    to_xlsx(sheets, out)
    log(f"Excel guardado en {os.path.abspath(out)}")
    if a.csv:
        to_csv(sheets, a.csv)
        log(f"CSV guardados en {os.path.abspath(a.csv)}")
    errors = [s for s in sheets["vSource"] if str(s.get("Estado", "")).startswith("ERROR")]
    return 2 if errors and len(errors) == len(sheets["vSource"]) else (1 if errors else 0)
