"""Cliente mínimo de solo lectura para la API REST de Proxmox VE (PVE 8 y 9)."""
from __future__ import annotations

import urllib.parse
import warnings

import requests

DEFAULT_PORT = 8006


class PVEError(Exception):
    pass


class PVEClient:
    """Conexión a un nodo Proxmox VE.

    Autenticación:
      * API token:  user="auditor@pve", token_id="inventario", token_secret="uuid"
      * Contraseña: user="root@pam", password="..."  (opcional otp para 2FA TOTP)
    """

    def __init__(self, host: str, user: str, password: str | None = None,
                 token_id: str | None = None, token_secret: str | None = None,
                 verify_ssl: bool = False, timeout: float = 20, otp: str | None = None):
        self.host, self.port = self._split_host(host)
        self.base = f"https://{self.host}:{self.port}/api2/json"
        self.user = user
        self.timeout = timeout
        self.session = requests.Session()
        self.session.verify = verify_ssl
        if not verify_ssl:
            warnings.filterwarnings("ignore", message="Unverified HTTPS request")
        if token_id:
            if "!" in user:  # el usuario ya incluye el token: user@realm!tokenid
                full = user
            else:
                full = f"{user}!{token_id}"
            self.session.headers["Authorization"] = f"PVEAPIToken={full}={token_secret}"
        elif password is not None:
            self._login(password, otp)
        else:
            raise PVEError("Falta contraseña o API token")

    @staticmethod
    def _split_host(host: str):
        host = host.strip()
        for prefix in ("https://", "http://"):
            if host.startswith(prefix):
                host = host[len(prefix):]
        host = host.split("/")[0]
        if host.startswith("["):  # IPv6 [::1]:8006
            h, _, rest = host[1:].partition("]")
            port = rest.lstrip(":") or DEFAULT_PORT
            return f"[{h}]", int(port)
        if host.count(":") == 1:
            h, p = host.split(":")
            return h, int(p)
        return host, DEFAULT_PORT

    def _login(self, password: str, otp: str | None):
        data = {"username": self.user, "password": password}
        if otp:
            data["otp"] = otp
        try:
            r = self.session.post(f"{self.base}/access/ticket", data=data, timeout=self.timeout,
                                  verify=self.session.verify)
        except requests.RequestException as e:
            raise PVEError(f"No se puede conectar con {self.host}:{self.port}: {e}") from e
        if r.status_code != 200:
            raise PVEError(f"Login fallido en {self.host} ({r.status_code}): {r.reason}")
        d = r.json().get("data") or {}
        if d.get("NeedTFA"):
            raise PVEError("La cuenta requiere segundo factor (2FA): usa un API token")
        self.session.cookies.set("PVEAuthCookie", d["ticket"])
        self.session.headers["CSRFPreventionToken"] = d.get("CSRFPreventionToken", "")

    def get(self, path: str, **params):
        url = self.base + "/" + path.lstrip("/")
        try:
            r = self.session.get(url, params=params or None, timeout=self.timeout,
                                 verify=self.session.verify)
        except requests.RequestException as e:
            raise PVEError(f"Error de red en {path}: {e}") from e
        if r.status_code == 401:
            raise PVEError("No autorizado (401): revisa credenciales/token")
        if r.status_code != 200:
            raise PVEError(f"{path}: HTTP {r.status_code} {r.reason}")
        return r.json().get("data")

    def try_get(self, path: str, default=None, **params):
        """GET que no lanza excepción (permisos, nodo caído, endpoint inexistente)."""
        try:
            data = self.get(path, **params)
            return default if data is None else data
        except PVEError:
            return default


def q(s) -> str:
    return urllib.parse.quote(str(s), safe="")
