"""Modo línea de comandos.

Ejemplos:
  pveinventory.exe --host pve1.local --user auditor@pve --token-id inventario --token-secret XXXX -o inventario.xlsx
  pveinventory.exe --host pve1 --host pve2:8006 --user root@pam --password-env PVE_PASSWORD --csv .\\csv
  pveinventory.exe --host pve1 --user admin@pam --totp 123456      (cuenta con 2FA; sin --totp lo pregunta)
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
from .i18n import LANGS, _, get_lang, setup_cli
from .collector import Inventory
from .anonymize import Anonymizer, default_map_path, reverse_file
from .export import to_csv, to_xlsx


def _ask_tfa(host, user, methods, error):
    """Pregunta el código 2FA en la consola (el código no se muestra ni se guarda)."""
    if error:
        print(f"  {error}", file=sys.stderr)
    what = _("código TOTP") if "totp" in methods else _("código")
    if "recovery" in methods:
        what += _(" o de recuperación")
    try:
        return getpass.getpass(_("{user} en {host} tiene 2FA. {what} (vacío = cancelar): ", user=user, host=host, what=what)).strip() or None
    except (EOFError, KeyboardInterrupt):
        return None


def build_parser():
    p = argparse.ArgumentParser(prog="pveinventory", description=_("{app} {version}: inventario de Proxmox VE 8/9 a Excel/CSV", app=APP_NAME, version=__version__),
                                epilog=_(SHORT_NOTICE) + _(". Solo lectura: no modifica nada en Proxmox."))
    p.add_argument("--host", action="append",
                   help=_("Nodo PVE (nombre o IP, opcional :puerto). Repetible: un nodo por clúster basta; para nodos sueltos, uno por nodo"))
    p.add_argument("--user", help=_("Usuario con realm, p. ej. root@pam o auditor@pve"))
    auth = p.add_mutually_exclusive_group()
    auth.add_argument("--password", help=_("Contraseña (mejor usar --password-env o dejar que la pida)"))
    auth.add_argument("--password-env", metavar="VAR", help=_("Variable de entorno con la contraseña"))
    auth.add_argument("--token-id", help=_("ID del API token (la parte tras '!')"))
    p.add_argument("--token-secret", help=_("Secreto del API token (o variable PVE_TOKEN_SECRET)"))
    p.add_argument("--totp", metavar=_("CÓDIGO"),
                   help=_("Cuentas con 2FA: código TOTP de 6 dígitos o código de recuperación. Si la cuenta lo pide y no "
                        "se indica, se pregunta (en consola interactiva). Con API token no hace falta"))
    p.add_argument("--verify-ssl", action="store_true", help=_("Verificar certificado (por defecto se aceptan autofirmados)"))
    p.add_argument("--no-agent", action="store_true", help=_("No consultar el QEMU guest agent (más rápido, sin IPs de VMs)"))
    p.add_argument("-o", "--xlsx", help=_("Fichero Excel de salida (por defecto pve_inventory_FECHA.xlsx)"))
    p.add_argument("--csv", metavar=_("CARPETA"), help=_("Exportar además una carpeta con un CSV por hoja"))
    an = p.add_argument_group(_("Anonimización"), _("Para que el cliente pueda enviar el inventario sin datos identificativos"))
    an.add_argument("--anonimizar", "--anonymize", action="store_true",
                    help=_("Sustituye nombres (clústeres, nodos, VMs, almacenamientos, usuarios, dominios…) por seudónimos "
                         "consistentes y transforma IPs/MACs conservando la estructura de red. Sigue sirviendo al planificador"))
    an.add_argument("--conservar-ips", "--keep-ips", action="store_true", help=_("Con --anonimizar: no transformar las IPs ni las MACs"))
    an.add_argument("--correspondencia", "--mapping", metavar=_("FICHERO"),
                    help=_("Fichero Excel con la correspondencia real ↔ seudónimo (por defecto, junto al Excel: "
                         "<nombre>_correspondencia_CONFIDENCIAL.xlsx). Si ya existe se reutiliza, para que los mismos "
                         "valores reciban los mismos seudónimos en varias ejecuciones"))
    an.add_argument("--sin-correspondencia", "--no-mapping", action="store_true",
                    help=_("No guardar la correspondencia (la anonimización no se podrá revertir)"))
    an.add_argument("--revertir", "--revert", metavar=_("FICHERO"), action="append",
                    help=_("Revierte los seudónimos de un Excel/CSV (inventario anonimizado o plan del planificador) usando "
                         "--correspondencia. No se conecta a Proxmox. Repetible"))
    p.add_argument("--lang", "--idioma", choices=list(LANGS), default=get_lang(),
                   help=_("Idioma de los mensajes y del Excel/CSV (es, en, de, fr, pt, it). Por defecto, el del sistema"))
    p.add_argument("-q", "--quiet", action="store_true", help=_("Sin mensajes de progreso"))
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return p


def main(argv=None):
    setup_cli(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    a = parser.parse_args(argv)
    if a.revertir:
        if not a.correspondencia:
            parser.error(_("--revertir necesita --correspondencia"))
        for f in a.revertir:
            print(_("Revertido: {abspath}", abspath=os.path.abspath(reverse_file(f, a.correspondencia))), file=sys.stderr)
        return 0
    if not a.host or not a.user:
        parser.error(_("indica --host y --user (o --revertir)"))
    if a.totp and a.token_id:
        parser.error(_("--totp solo se usa con contraseña: el API token no pide 2FA"))
    if (a.conservar_ips or a.correspondencia or a.sin_correspondencia) and not a.anonimizar:
        parser.error(_("--conservar-ips, --correspondencia y --sin-correspondencia requieren --anonimizar"))
    base = {"user": a.user, "verify_ssl": a.verify_ssl}
    if a.token_id:
        base["token_id"] = a.token_id
        base["token_secret"] = a.token_secret or os.environ.get("PVE_TOKEN_SECRET")
        if not base["token_secret"]:
            base["token_secret"] = getpass.getpass(_("Secreto del API token: "))
    else:
        pw = a.password or (os.environ.get(a.password_env) if a.password_env else None)
        base["password"] = pw if pw is not None else getpass.getpass(_("Contraseña de {user}: ", user=a.user))
        if a.totp:
            base["otp"] = a.totp
        if sys.stdin and sys.stdin.isatty():
            base["tfa_callback"] = _ask_tfa
    conns = [{**base, "host": h} for h in a.host]
    log = (lambda m: None) if a.quiet else (lambda m: print(m, file=sys.stderr))
    log(f"{APP_NAME} {__version__} — {_(SHORT_NOTICE)}")
    inv = Inventory(progress=log, query_agent=not a.no_agent)
    sheets = inv.collect(conns)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    out = a.xlsx or f"pve_inventory_{stamp}{_('_anonimo') if a.anonimizar else ''}.xlsx"
    errors = [s for s in sheets["vSource"] if str(s.get("Estado", "")).startswith("ERROR")]
    if a.anonimizar:
        map_path = a.correspondencia or default_map_path(out)
        anon = Anonymizer.load(map_path, keep_ips=a.conservar_ips) if os.path.exists(map_path) and not a.sin_correspondencia \
            else Anonymizer(keep_ips=a.conservar_ips)
        sheets = anon.anonymize(sheets)
        if not a.sin_correspondencia:
            anon.save(map_path)
            log(_("Correspondencia (CONFIDENCIAL, no la envíes) guardada en {abspath}", abspath=os.path.abspath(map_path)))
    to_xlsx(sheets, out)
    log((_("Excel anonimizado guardado en {path}") if a.anonimizar else _("Excel guardado en {path}")).format(path=os.path.abspath(out)))
    if a.csv:
        to_csv(sheets, a.csv)
        log(_("CSV guardados en {abspath}", abspath=os.path.abspath(a.csv)))
    return 2 if errors and len(errors) == len(sheets["vSource"]) else (1 if errors else 0)

