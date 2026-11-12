"""Cliente mínimo de solo lectura para la API REST de Proxmox VE (PVE 8 y 9)."""
from __future__ import annotations

import json
import re
import urllib.parse
import warnings

import requests

DEFAULT_PORT = 8006


class PVEError(Exception):
    pass


TOKEN_HINT = ("Alternativa recomendada: un API token de solo lectura, que no pide segundo factor "
              "(ver README, «usuario y API token de solo lectura»)")


class PVETFAError(PVEError):
    """La cuenta tiene segundo factor (2FA) y no se ha podido completar."""


def tfa_methods(challenge_ticket: str) -> list[str]:
    """Métodos de 2FA que ofrece el desafío de PVE («PVE:!tfa!<json>:<hora>::<firma>»).

    Devuelve p. ej. ["totp", "recovery"]. Si no se puede leer, asume TOTP y recuperación."""
    m = re.search(r"!tfa!([^:]*)", challenge_ticket or "")
    try:
        data = json.loads(urllib.parse.unquote(m.group(1))) if m else None
    except ValueError:
        data = None
    if not isinstance(data, dict):
        return ["totp", "recovery"]
    return [k for k in ("totp", "recovery", "yubico", "webauthn", "u2f") if data.get(k)]


def tfa_response(code: str, methods: list[str]) -> str:
    """Convierte lo que escribe el usuario en la respuesta que espera PVE (totp:/recovery:/yubico:)."""
    code = re.sub(r"\s+", "", code or "")
    if re.match(r"^(totp|recovery|yubico):", code):
        return code
    if code.isdigit():
        return f"totp:{code}"
    if "yubico" in methods and len(code) == 44 and re.fullmatch(r"[cbdefghijklnrtuv]+", code):
        return f"yubico:{code}"
    return f"recovery:{code}"


METHOD_NAMES = {"totp": "TOTP (app de autenticación)", "recovery": "código de recuperación",
                "yubico": "Yubico OTP", "webauthn": "llave WebAuthn/FIDO", "u2f": "llave U2F"}


class PVEClient:
    """Conexión a un nodo Proxmox VE.

    Autenticación:
      * API token:  user="auditor@pve", token_id="inventario", token_secret="uuid"
      * Contraseña: user="root@pam", password="..."
        Si la cuenta tiene 2FA, el código se toma de ``otp`` (TOTP o código de recuperación) o se pide
        con ``tfa_callback(host, user, methods, error) -> str | None`` (None = cancelar).
    """

    def __init__(self, host: str, user: str, password: str | None = None,
                 token_id: str | None = None, token_secret: str | None = None,
                 verify_ssl: bool = False, timeout: float = 20, otp: str | None = None,
                 tfa_callback=None):
        self.host, self.port = self._split_host(host)
        self.base = f"https://{self.host}:{self.port}/api2/json"
        self.user = user
        self.timeout = timeout
        self.auth_method = "API token" if token_id else "Contraseña"
        self.session = requests.Session()
        # Proxmox está en la red local: ignorar proxies del sistema/variables de entorno,
        # que en redes corporativas pueden interceptar o romper la conexión.
        self.session.trust_env = False
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
            self._login(password, otp, tfa_callback)
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

    def _post_ticket(self, password: str, challenge: str | None = None):
        data = {"username": self.user, "password": password}
        if challenge:
            data["tfa-challenge"] = challenge
        try:
            return self.session.post(f"{self.base}/access/ticket", data=data, timeout=self.timeout,
                                     verify=self.session.verify)
        except requests.RequestException as e:
            raise PVEError(f"No se puede conectar con {self.host}:{self.port}: {e}") from e

    def _login(self, password: str, otp: str | None, tfa_callback=None):
        r = self._post_ticket(password)
        if r.status_code == 401 and password != password.strip():
            # típico al pegar la contraseña: espacio o salto de línea al principio/final
            r = self._post_ticket(password.strip())
        if r.status_code == 401:
            if "@" not in self.user:
                hint = "falta el realm en el usuario (p. ej. root@pam)"
            else:
                hint = "usuario, realm (@pam / @pve) o contraseña incorrectos"
            raise PVEError(f"Login rechazado por {self.host} (401): {hint}")
        if r.status_code != 200:
            raise PVEError(f"Login fallido en {self.host} ({r.status_code}): {r.reason}")
        d = r.json().get("data") or {}
        if d.get("NeedTFA"):
            d = self._second_factor(d.get("ticket", ""), otp, tfa_callback)
        self.session.cookies.set("PVEAuthCookie", d["ticket"])
        self.session.headers["CSRFPreventionToken"] = d.get("CSRFPreventionToken", "")

    def _second_factor(self, challenge: str, otp: str | None, tfa_callback, max_attempts: int = 3) -> dict:
        """Completa el login de una cuenta con 2FA respondiendo al desafío de PVE (segunda llamada a /access/ticket)."""
        methods = tfa_methods(challenge)
        if not {"totp", "recovery", "yubico"} & set(methods):
            names = ", ".join(METHOD_NAMES.get(m, m) for m in methods) or "desconocido"
            raise PVETFAError(f"La cuenta {self.user} usa como segundo factor {names}, que esta herramienta no "
                              f"puede usar. {TOKEN_HINT}")
        error = None
        for attempt in range(max_attempts):
            if attempt == 0 and otp:
                code = otp
            elif tfa_callback:
                code = tfa_callback(self.host, self.user, methods, error)
                if not code:
                    raise PVETFAError(f"Login cancelado: la cuenta {self.user} tiene 2FA y no se indicó el código. "
                                      f"{TOKEN_HINT}")
            elif otp:
                break  # el código indicado de antemano fue rechazado y no hay forma de pedir otro
            else:
                raise PVETFAError(f"La cuenta {self.user} tiene segundo factor (2FA): indica el código TOTP o de "
                                  f"recuperación (en la línea de comandos, --totp). {TOKEN_HINT}")
            response = tfa_response(code, methods)
            r = self._post_ticket(response, challenge)
            d = (r.json().get("data") or {}) if r.status_code == 200 else {}
            if d.get("ticket") and not d.get("NeedTFA"):
                self.auth_method = ("Contraseña + 2FA (código de recuperación)" if response.startswith("recovery:")
                                    else "Contraseña + 2FA (Yubico)" if response.startswith("yubico:")
                                    else "Contraseña + 2FA (TOTP)")
                return d
            error = ("Código rechazado: comprueba que es el actual (caduca cada 30 s) y que la hora del equipo es "
                     "correcta. Tras varios fallos Proxmox bloquea temporalmente el 2FA de la cuenta")
        raise PVETFAError(f"Segundo factor rechazado por {self.host} para {self.user}. {error or ''} {TOKEN_HINT}".replace("  ", " "))

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
