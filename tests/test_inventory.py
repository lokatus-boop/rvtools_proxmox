"""Prueba de extremo a extremo contra el Proxmox simulado. Ejecutar: python -m pytest tests  (o python tests/test_inventory.py)"""
import os
import ssl
import subprocess
import sys
import tempfile
import threading
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))
os.environ["NO_PROXY"] = os.environ["no_proxy"] = "127.0.0.1,localhost"

import mock_pve  # noqa: E402
from pvetools.collector import Inventory  # noqa: E402
from pvetools.export import to_csv, to_xlsx  # noqa: E402


def serve(data):
    d = tempfile.mkdtemp()
    cert, key = os.path.join(d, "c.pem"), os.path.join(d, "k.pem")
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", key, "-out", cert,
                    "-days", "1", "-subj", "/CN=localhost"], check=True, capture_output=True)
    handler = type("H", (mock_pve.Handler,), {"data": data})
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(cert, key)
    srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return f"127.0.0.1:{srv.server_address[1]}"


def test_cluster_and_standalone():
    clu, sa = serve(mock_pve.cluster_data()), serve(mock_pve.standalone_data())
    tok = {"user": "auditor@pve", "token_id": "inv", "token_secret": "secret"}
    sheets = Inventory(query_agent=True).collect([
        {**tok, "host": clu}, {**tok, "host": clu},                      # duplicado -> se omite
        {"host": sa, "user": "root@pam", "password": "pw"},              # login por contraseña
        {"host": "127.0.0.1:1", "user": "root@pam", "password": "pw"},   # host caído -> error controlado
    ])
    assert len(sheets["vInfo"]) == 5
    assert {c["Tipo"] for c in sheets["vCluster"]} == {"Clúster", "Nodo independiente"}
    assert [s["Estado"].split()[0] for s in sheets["vSource"]] == ["OK", "Omitido", "OK", "ERROR:"]
    web = next(v for v in sheets["vInfo"] if v["Nombre"] == "web01")
    assert web["IPs"] == "10.20.0.5" and web["vCPU"] == 4 and web["Snapshots"] == 1
    assert any("95.0%" in h["Mensaje"] and h["Severidad"] == "CRÍTICO" for h in sheets["vHealth"])
    out = tempfile.mkdtemp()
    to_xlsx(sheets, os.path.join(out, "inv.xlsx"))
    assert len(to_csv(sheets, out)) == len(sheets) + 1  # + LEEME_AVISO.txt


if __name__ == "__main__":
    test_cluster_and_standalone()
    print("OK")


def test_password_login_edge_cases():
    import pytest
    from pvetools.api import PVEClient, PVEError
    sa = serve(mock_pve.standalone_data())
    # contraseña pegada con espacio final -> se reintenta sin espacios
    assert PVEClient(host=sa, user="root@pam", password="pw ").get("version")["version"] == "8.4.1"
    with pytest.raises(PVEError, match="incorrectos"):
        PVEClient(host=sa, user="root@pam", password="mala")
    with pytest.raises(PVEError, match="realm"):
        PVEClient(host=sa, user="root", password="pw")



def test_export_matches_schema():
    """Lo que se exporta coincide con el formato estable documentado (schema.py)."""
    from pvetools.collector import SHEETS
    from pvetools.schema import SCHEMA
    assert list(SCHEMA) == SHEETS
    tok = {"user": "auditor@pve", "token_id": "inv", "token_secret": "secret"}
    sheets = Inventory().collect([{**tok, "host": serve(mock_pve.cluster_data())},
                                  {**tok, "host": serve(mock_pve.standalone_data())}])
    for name, rows in sheets.items():
        for r in rows:
            extra = set(r) - set(SCHEMA[name])
            assert not extra, f"{name}: columnas fuera del formato {extra} (añádelas al final en schema.py)"


def test_sdn_collected():
    """SDN: zonas, VNets, subredes, controladores, IPAM y DNS (sin secretos) y NICs de VMs por VNet."""
    tok = {"user": "auditor@pve", "token_id": "inv", "token_secret": "secret"}
    sheets = Inventory().collect([{**tok, "host": serve(mock_pve.cluster_data())}])
    sdn = {r["VNet"]: r for r in sheets["vSDN"]}
    assert set(sdn) == {"vnet100", "tenant1", "(sin VNets)"}
    assert sdn["vnet100"]["NICs de VMs/CTs"] == 1 and sdn["vnet100"]["SNAT"] == "Sí"
    t = sdn["tenant1"]
    assert (t["Tipo zona"], t["Controlador"], t["Exit nodes"], t["VRF VXLAN"]) == ("evpn", "evpnctl", "pve1,pve2", 10000)
    assert t["Rango DHCP"] == "10.50.0.100-10.50.0.200" and t["Pendiente de aplicar"].startswith("Sí")
    objs = {(r["Objeto"], r["Nombre"]): r for r in sheets["vSDNObj"]}
    assert objs[("Controlador", "evpnctl")]["ASN"] == 65000
    assert objs[("IPAM", "netbox1")]["URL / servidor"] == "https://ipam01.cliente.local/api"
    assert "SECRETO" not in str(sheets["vSDNObj"])
    assert any(h["Objeto"] == "SDN" and "pendientes de aplicar" in h["Mensaje"] for h in sheets["vHealth"])


def test_password_login_with_2fa():
    """Cuentas con 2FA: desafío de PVE + segunda llamada con «totp:<código>» o «recovery:<código>»."""
    import pytest
    from pvetools.api import PVEClient, PVETFAError, tfa_methods, tfa_response
    sa = serve(mock_pve.standalone_data())
    assert tfa_methods(mock_pve.Handler.TFA_USERS["tfa@pam"]["challenge"]) == ["totp", "recovery"]
    assert tfa_response(" 123 456 ", ["totp"]) == "totp:123456"
    assert tfa_response("abcd-ef01-2345-6789", ["totp", "recovery"]) == "recovery:abcd-ef01-2345-6789"

    # código indicado de antemano (--totp)
    api = PVEClient(host=sa, user="tfa@pam", password="pw", otp="123456")
    assert api.get("version")["version"] == "8.4.1" and api.auth_method == "Contraseña + 2FA (TOTP)"
    # código de recuperación
    assert PVEClient(host=sa, user="tfa@pam", password="pw", otp="abcd-ef01-2345-6789").auth_method.endswith("(código de recuperación)")
    # se pide con el callback; el primer código es erróneo y se vuelve a pedir con el motivo
    asked = []

    def ask(host, user, methods, error):
        asked.append(error)
        return "000000" if len(asked) == 1 else "123456"
    assert PVEClient(host=sa, user="tfa@pam", password="pw", tfa_callback=ask).get("version")
    assert asked[0] is None and "rechazado" in asked[1]
    # sin código ni forma de pedirlo -> mensaje claro que recomienda API token
    with pytest.raises(PVETFAError, match="API token"):
        PVEClient(host=sa, user="tfa@pam", password="pw")
    with pytest.raises(PVETFAError, match="cancelado"):
        PVEClient(host=sa, user="tfa@pam", password="pw", tfa_callback=lambda *a: None)
    with pytest.raises(PVETFAError, match="rechazado"):
        PVEClient(host=sa, user="tfa@pam", password="pw", otp="999999")
    # solo llave FIDO/WebAuthn -> no se puede, recomendar token
    with pytest.raises(PVETFAError, match="WebAuthn.*API token"):
        PVEClient(host=sa, user="fido@pam", password="pw", tfa_callback=ask)
    # en el inventario queda anotado cómo se autenticó
    sheets = Inventory().collect([{"host": sa, "user": "tfa@pam", "password": "pw", "otp": "123456"}])
    assert sheets["vSource"][0]["Estado"] == "OK"
    assert sheets["vSource"][0]["Autenticación"] == "Contraseña + 2FA (TOTP)"
