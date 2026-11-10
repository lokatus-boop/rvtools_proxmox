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
    m = p.add_argument_group("Planificación de migración (solo lectura; genera Excel y scripts, no ejecuta nada)")
    m.add_argument("--target-host", help="Nodo del Proxmox de destino: activa el planificador de migración")
    m.add_argument("--target-user", help="Usuario del destino (por defecto, el mismo que --user)")
    m.add_argument("--target-token-id", help="API token del destino (lectura)")
    m.add_argument("--target-token-secret", help="Secreto del token del destino (o variable PVE_TARGET_TOKEN_SECRET)")
    m.add_argument("--target-password-env", metavar="VAR", help="Variable de entorno con la contraseña del destino")
    m.add_argument("--target-node", help="Nodo destino fijo (por defecto, el de más RAM libre)")
    m.add_argument("--map-storage", action="append", default=[], metavar="ORIGEN=DESTINO", help="Mapeo de almacenamiento (repetible)")
    m.add_argument("--map-bridge", action="append", default=[], metavar="ORIGEN=DESTINO", help="Mapeo de bridge/VNet (repetible)")
    m.add_argument("--vmids", help="VMIDs a incluir, p. ej. 100,101,200-210 (por defecto, todas)")
    m.add_argument("--new-vmids", action="store_true", help="Asignar siempre VMIDs nuevos en destino")
    m.add_argument("--bandwidth", type=float, default=1.0, help="Ancho de banda entre clústeres en Gbit/s (estimación de tiempos)")
    m.add_argument("--plan-dir", default=".", help="Carpeta donde guardar el plan (Excel + scripts)")
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
    inv = Inventory(progress=log, query_agent=not a.no_agent)
    sheets = inv.collect(conns)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    out = a.xlsx or f"pve_inventory_{stamp}.xlsx"
    to_xlsx(sheets, out)
    log(f"Excel guardado en {os.path.abspath(out)}")
    if a.csv:
        to_csv(sheets, a.csv)
        log(f"CSV guardados en {os.path.abspath(a.csv)}")
    if a.target_host:
        plan_files = _plan(a, inv, log)
        if plan_files is None:
            return 2
    errors = [s for s in sheets["vSource"] if str(s.get("Estado", "")).startswith("ERROR")]
    return 2 if errors and len(errors) == len(sheets["vSource"]) else (1 if errors else 0)


def _kv(items):
    out = {}
    for it in items:
        if "=" not in it:
            raise SystemExit(f"Mapeo no válido (usa ORIGEN=DESTINO): {it}")
        k, v = it.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def _plan(a, src_inv, log):
    from .migrate import MigrationPlan
    conn = {"host": a.target_host, "user": a.target_user or a.user, "verify_ssl": a.verify_ssl}
    if a.target_token_id:
        conn["token_id"] = a.target_token_id
        conn["token_secret"] = a.target_token_secret or os.environ.get("PVE_TARGET_TOKEN_SECRET") \
            or getpass.getpass("Secreto del API token del destino: ")
    else:
        pw = os.environ.get(a.target_password_env) if a.target_password_env else None
        conn["password"] = pw if pw is not None else getpass.getpass(f"Contraseña de {conn['user']} en el destino: ")
    log(f"Leyendo el destino {a.target_host}…")
    tgt = Inventory(progress=log, query_agent=False)
    tgt.collect([conn])
    err = next((s["Estado"] for s in tgt.sheets["vSource"] if str(s.get("Estado", "")).startswith("ERROR")), None)
    if err:
        log(f"No se pudo leer el destino: {err}")
        return None
    vmids = []
    for part in (a.vmids or "").replace(" ", "").split(","):
        if part:
            if "-" in part:
                x, y = part.split("-", 1)
                vmids += list(range(int(x), int(y) + 1))
            else:
                vmids.append(int(part))
    plan = MigrationPlan(src_inv, tgt, a.target_host, {
        "target_node": a.target_node, "storage_map": _kv(a.map_storage), "bridge_map": _kv(a.map_bridge),
        "vmids": vmids, "keep_vmid": not a.new_vmids, "bandwidth_gbps": a.bandwidth}).build()
    files = plan.write(a.plan_dir)
    s = plan.summary()
    log(f"Plan de migración: {s['VMs/CTs en el plan']} VMs/CTs ({s['OK']} OK, {s['Con avisos']} con avisos, "
        f"{s['Bloqueadas']} bloqueadas)")
    for f in files:
        log(f"  {os.path.abspath(f)}")
    return files
