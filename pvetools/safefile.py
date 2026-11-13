"""Guardado seguro de los ficheros que generan las herramientas (Excel, Word, CSV, JSON).

Problemas que evita:

* **Ficheros corruptos o «llenos de ceros».** openpyxl y python-docx escriben directamente sobre el destino; si el
  programa se cierra, el equipo se apaga, OneDrive/antivirus bloquea el fichero a mitad o falla la red (carpetas
  compartidas), queda un .xlsx/.docx a medias que Excel no abre. Aquí se escribe primero en un temporal de la misma
  carpeta, se fuerza a disco (fsync), se comprueba que el ZIP es válido y solo entonces se renombra al nombre final
  (operación atómica): o queda el fichero completo, o el anterior intacto.
* **Ficheros «que no aparecen».** Nombres con caracteres no válidos en Windows (``:`` crea un flujo alternativo NTFS
  invisible, ``/`` o ``\\`` mandan el fichero a otra carpeta), extensión que falta y rutas relativas.
* **Errores silenciosos.** Las causas habituales (fichero abierto en Excel, carpeta protegida por Windows,
  disco lleno…) se traducen a un mensaje claro.
"""
from __future__ import annotations

import contextlib
import errno
import os
import re
import tempfile
import time
import zipfile

_INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
ZIP_EXT = (".xlsx", ".xlsm", ".docx", ".pptx", ".zip")


class SaveError(OSError):
    """Error al guardar con un mensaje pensado para el usuario."""


def safe_filename(name: str, fallback: str = "informe", max_len: int = 120) -> str:
    """Convierte un texto (p. ej. el nombre del cliente) en un nombre de fichero válido en Windows."""
    s = _INVALID.sub("_", str(name or "")).strip().rstrip(". ").strip()
    s = re.sub(r"\s+", "_", s)
    s = re.sub(r"_{2,}", "_", s)
    if not s:
        s = fallback
    if s.split(".")[0].upper() in _RESERVED:
        s = "_" + s
    return s[:max_len].rstrip(". ") or fallback


def ensure_ext(path: str, ext: str) -> str:
    """Añade la extensión si falta (p. ej. el usuario escribió «inventario.v2»)."""
    return path if path.lower().endswith(ext.lower()) else path + ext


def explain(exc: BaseException, path: str) -> str:
    """Mensaje comprensible para un error al guardar «path»."""
    if isinstance(exc, SaveError):
        return str(exc)
    name = os.path.basename(path) or path
    folder = os.path.dirname(os.path.abspath(path))
    if isinstance(exc, PermissionError) or getattr(exc, "errno", None) in (errno.EACCES, errno.EPERM):
        return (f"No se pudo escribir «{name}» en {folder}.\n\n"
                "Causas habituales:\n"
                "• El fichero está abierto en Excel/Word: ciérralo y vuelve a intentarlo.\n"
                "• La carpeta está protegida («Acceso controlado a carpetas» de Windows Defender suele bloquear "
                "Documentos y Escritorio a programas nuevos; mira si salió un aviso de Windows Security).\n"
                "• No tienes permiso de escritura en esa carpeta (p. ej. Archivos de programa o una unidad de red).\n\n"
                f"Detalle: {exc}")
    if getattr(exc, "errno", None) == errno.ENOSPC:
        return f"No hay espacio en disco para guardar «{name}» en {folder}."
    if isinstance(exc, (FileNotFoundError, NotADirectoryError)) or getattr(exc, "errno", None) in (errno.ENOENT, errno.EINVAL):
        return (f"La ruta «{path}» no es válida o la carpeta ya no existe (¿unidad de red desconectada, "
                f"o carpeta temporal de un ZIP abierto sin descomprimir?).\n\nDetalle: {exc}")
    return f"No se pudo guardar «{name}» en {folder}: {exc}"


def verify(path: str) -> None:
    """Comprueba que el fichero no está vacío, ni lleno de ceros, y que un .xlsx/.docx es un ZIP íntegro."""
    size = os.path.getsize(path)
    if size == 0:
        raise SaveError(f"El fichero «{os.path.basename(path)}» se ha quedado vacío al guardarlo.")
    with open(path, "rb") as f:
        head = f.read(4096)
    if not head.strip(b"\x00"):
        raise SaveError(f"El fichero «{os.path.basename(path)}» se ha escrito solo con ceros (el disco o la carpeta "
                        "sincronizada no ha guardado los datos).")
    if path.lower().endswith(ZIP_EXT) or head[:2] == b"PK":
        try:
            with zipfile.ZipFile(path) as z:
                bad = z.testzip()
        except zipfile.BadZipFile as exc:
            raise SaveError(f"El fichero «{os.path.basename(path)}» ha quedado dañado al guardarlo ({exc}).") from exc
        if bad:
            raise SaveError(f"El fichero «{os.path.basename(path)}» ha quedado dañado al guardarlo (parte {bad}).")


def _fsync(path: str) -> None:
    try:
        with open(path, "rb+") as f:
            os.fsync(f.fileno())
    except OSError:
        pass  # algunas unidades de red no lo admiten; no es motivo para fallar


def _replace(src: str, dst: str, attempts: int = 8) -> None:
    """os.replace con reintentos: en Windows el antivirus, el indexador u OneDrive bloquean el fichero unos instantes."""
    for i in range(attempts):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if i == attempts - 1:
                raise SaveError(f"No se pudo sustituir «{os.path.basename(dst)}»: está abierto en Excel/Word u otro "
                                f"programa lo tiene bloqueado.\nCiérralo y vuelve a intentarlo.\n\nCarpeta: "
                                f"{os.path.dirname(dst)}") from None
            time.sleep(0.25 * (i + 1))


def atomic_save(path: str, write, check: bool = True) -> str:
    """Guarda de forma atómica: ``write(ruta_temporal)`` escribe el contenido; devuelve la ruta absoluta final.

    Ejemplos::

        atomic_save("inv.xlsx", wb.save)
        atomic_save("plan.docx", document.save)
    """
    path = os.path.abspath(path)
    folder = os.path.dirname(path)
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".~" + os.path.basename(path)[:60] + ".", suffix=".tmp", dir=folder)
    os.close(fd)
    try:
        write(tmp)
        _fsync(tmp)
        if check:
            verify(tmp)
        _replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    return path


@contextlib.contextmanager
def atomic_text(path: str, encoding: str = "utf-8", newline: str | None = None):
    """Gestor de contexto para escribir texto (CSV, JSON, TXT) de forma atómica."""
    path = os.path.abspath(path)
    folder = os.path.dirname(path)
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".~" + os.path.basename(path)[:60] + ".", suffix=".tmp", dir=folder)
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline=newline) as f:
            yield f
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass
        _replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def default_folder(remembered: str | None = None) -> str:
    """Carpeta inicial de los diálogos: la última usada si existe; si no, Documentos (nunca el directorio de trabajo,
    que en el .exe puede ser una carpeta temporal o la del ZIP abierto sin descomprimir)."""
    if remembered and os.path.isdir(remembered):
        return remembered
    home = os.path.expanduser("~")
    for c in (os.path.join(home, "Documents"), os.path.join(home, "Documentos"), home):
        if os.path.isdir(c):
            return c
    return home


def reveal(path: str) -> None:
    """Abre el Explorador con el fichero seleccionado (o la carpeta)."""
    import subprocess
    import sys
    path = os.path.abspath(path)
    try:
        if os.name == "nt":
            if os.path.isfile(path):
                subprocess.Popen(["explorer", "/select,", path])  # noqa: S603,S607
            else:
                os.startfile(path if os.path.isdir(path) else os.path.dirname(path))  # type: ignore[attr-defined]  # noqa: S606
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", path])  # noqa: S603,S607
        else:
            subprocess.Popen(["xdg-open", path if os.path.isdir(path) else os.path.dirname(path)])  # noqa: S603,S607
    except OSError:
        pass
