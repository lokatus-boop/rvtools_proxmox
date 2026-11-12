"""Modo línea de comandos.

Ejemplos:
  pveinventory.exe --host pve1.local --user auditor@pve --token-id inventario --token-secret XXXX -o inventario.xlsx
  pveinventory.exe --host pve1 --host pve2:8006 --user root@pam --password-env PVE_PASSWORD --csv .\\csv
  pveinventory.exe --host pve1 --user root@pam --anonimizar -o inventario_anonimo.xlsx
  pveinventory.exe --revertir plan.xlsx --correspondencia inventario_anonimo_correspondencia_CONFIDENCIAL.xlsx
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
from .anonymize import Anonymizer, default_map_path, reverse_file
from .export import to_csv, to_xlsx


def build_parser():
    p = argparse.ArgumentParser(prog="pveinventory", description=f"{APP_NAME} {__version__}: inventario de Proxmox VE 8/9 a Excel/CSV",
                                epilog=SHORT_NOTICE + ". Solo lectura: no modifica nada en Proxmox.")
    p.add_argument("--host", action="append",
                   help="Nodo PVE (nombre o IP, opcional :puerto). Repetible: un nodo por clúster basta; para nodos sueltos, uno por nodo")
    p.add_argument("--user", help="Usuario con realm, p. ej. root@pam o auditor@pve")
    auth = p.add_mutually_exclusive_group()
    auth.add_argument("--password", help="Contraseña (mejor usar --password-env o dejar que la pida)")
    auth.add_argument("--password-env", metavar="VAR", help="Variable de entorno con la contraseña")
    auth.add_argument("--token-id", help="ID del API token (la parte tras '!')")
    p.add_argument("--token-secret", help="Secreto del API token (o variable PVE_TOKEN_SECRET)")
    p.add_argument("--verify-ssl", action="store_true", help="Verificar certificado (por defecto se aceptan autofirmados)")
    p.add_argument("--no-agent", action="store_true", help="No consultar el QEMU guest agent (más rápido, sin IPs de VMs)")
    p.add_argument("-o", "--xlsx", help="Fichero Excel de salida (por defecto pve_inventory_FECHA.xlsx)")
    p.add_argument("--csv", metavar="CARPETA", help="Exportar además una carpeta con un CSV por hoja")
    an = p.add_argument_group("Anonimización", "Para que el cliente pueda enviar el inventario sin datos identificativos")
    an.add_argument("--anonimizar", action="store_true",
                    help="Sustituye nombres (clústeres, nodos, VMs, almacenamientos, usuarios, dominios…) por seudónimos "
                         "consistentes y transforma IPs/MACs conservando la estructura de red. Sigue sirviendo al planificador")
    an.add_argument("--conservar-ips", action="store_true", help="Con --anonimizar: no transformar las IPs ni las MACs")
    an.add_argument("--correspondencia", metavar="FICHERO",
                    help="Fichero Excel con la correspondencia real ↔ seudónimo (por defecto, junto al Excel: "
                         "<nombre>_correspondencia_CONFIDENCIAL.xlsx). Si ya existe se reutiliza, para que los mismos "
                         "valores reciban los mismos seudónimos en varias ejecuciones")
    an.add_argument("--sin-correspondencia", action="store_true",
                    help="No guardar la correspondencia (la anonimización no se podrá revertir)")
    an.add_argument("--revertir", metavar="FICHERO", action="append",
                    help="Revierte los seudónimos de un Excel/CSV (inventario anonimizado o plan del planificador) usando "
                         "--correspondencia. No se conecta a Proxmox. Repetible")
    p.add_argument("-q", "--quiet", action="store_true")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return p


def main(argv=None):
    parser = build_parser()
    a = parser.parse_args(argv)
    if a.revertir:
        if not a.correspondencia:
            parser.error("--revertir necesita --correspondencia")
        for f in a.revertir:
            print(f"Revertido: {os.path.abspath(reverse_file(f, a.correspondencia))}", file=sys.stderr)
        return 0
    if not a.host or not a.user:
        parser.error("indica --host y --user (o --revertir)")
    if (a.conservar_ips or a.correspondencia or a.sin_correspondencia) and not a.anonimizar:
        parser.error("--conservar-ips, --correspondencia y --sin-correspondencia requieren --anonimizar")
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
    inv = Inventory(progress=log, query_agent=not a.no_agent)
    sheets = inv.collect(conns)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    out = a.xlsx or f"pve_inventory_{stamp}{'_anonimo' if a.anonimizar else ''}.xlsx"
    errors = [s for s in sheets["vSource"] if str(s.get("Estado", "")).startswith("ERROR")]
    if a.anonimizar:
        map_path = a.correspondencia or default_map_path(out)
        anon = Anonymizer.load(map_path, keep_ips=a.conservar_ips) if os.path.exists(map_path) and not a.sin_correspondencia \
            else Anonymizer(keep_ips=a.conservar_ips)
        sheets = anon.anonymize(sheets)
        if not a.sin_correspondencia:
            anon.save(map_path)
            log(f"Correspondencia (CONFIDENCIAL, no la envíes) guardada en {os.path.abspath(map_path)}")
    to_xlsx(sheets, out)
    log(f"Excel{' anonimizado' if a.anonimizar else ''} guardado en {os.path.abspath(out)}")
    if a.csv:
        to_csv(sheets, a.csv)
        log(f"CSV guardados en {os.path.abspath(a.csv)}")
    return 2 if errors and len(errors) == len(sheets["vSource"]) else (1 if errors else 0)

