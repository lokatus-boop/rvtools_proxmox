"""Interfaz gráfica del planificador (tkinter)."""
from __future__ import annotations

import copy
import json
import os
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import APP_NAME, __version__
from .branding import COMPANY, DISCLAIMER, DISCLAIMER_TITLE, DISCLAIMER_VERSION, SHORT_NOTICE, asset_path
from .loader import InventoryError, format_warnings, load
from .scenario import PVE_VERSIONS, STORAGE_TYPES, load as load_scenario, new, save as save_scenario
from pvetools.safefile import default_folder, ensure_ext, explain, reveal, safe_filename

CONFIG_DIR = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~/.config"), "PVEMigrationPlanner")
SETTINGS_FILE = os.path.join(CONFIG_DIR, "settings.json")

STORAGE_KEYS = list(STORAGE_TYPES)
METHODS = {"auto": "Automático (PBS si se incluye; si no, remote-migrate)", "pbs": "Backup/restore con PBS",
           "remote-migrate": "qm/pct remote-migrate"}

# (ruta en el escenario, etiqueta, tipo, ancho)
CAPACITY_FIELDS = [
    (("capacidad", "crecimiento_pct"), "Crecimiento previsto (%)", float),
    (("capacidad", "ratio_vcpu_core"), "Ratio vCPU : core físico", float),
    (("capacidad", "cpu_max_pct"), "Ocupación máx. CPU (%)", float),
    (("capacidad", "ram_max_pct"), "Ocupación máx. RAM (%)", float),
    (("capacidad", "n_mas"), "Nodos de reserva (N+…)", int),
    (("capacidad", "nodos_min"), "Mínimo de nodos", int),
    (("capacidad", "reserva_snapshots_pct"), "Reserva snapshots (%)", float),
    (("almacenamiento", "replicas"), "Réplicas Ceph", int),
    (("almacenamiento", "llenado_max_pct"), "Llenado máx. almacenamiento (%)", float),
]
PBS_FIELDS = [
    (("pbs", "retencion", "diaria"), "Copias diarias", int),
    (("pbs", "retencion", "semanal"), "Copias semanales", int),
    (("pbs", "retencion", "mensual"), "Copias mensuales", int),
    (("pbs", "retencion", "anual"), "Copias anuales", int),
    (("pbs", "cambio_diario_pct"), "Cambio diario (%)", float),
    (("pbs", "reduccion"), "Reducción (dedup+compr., 0-1)", float),
    (("pbs", "llenado_max_pct"), "Llenado máx. datastore (%)", float),
]
PBS_HW_FIELDS = [
    (("pbs", "hardware", "modelo"), "Modelo", str),
    (("pbs", "hardware", "cores"), "Cores", int),
    (("pbs", "hardware", "ram_gib"), "RAM (GiB)", int),
    (("pbs", "hardware", "capacidad_util_tib"), "Capacidad útil (TiB)", float),
    (("pbs", "hardware", "discos"), "Discos (texto libre)", str),
]
MIG_FIELDS = [
    (("migracion", "mbps_por_flujo"), "MB/s por migración", float),
    (("migracion", "flujos"), "Migraciones simultáneas", int),
    (("migracion", "max_vms_ola"), "Máx. VMs por ola", int),
    (("migracion", "max_gib_ola"), "Máx. GiB por ola", float),
    (("migracion", "olas_por_semana"), "Olas por semana", int),
    (("migracion", "inicio"), "Fecha de inicio (AAAA-MM-DD)", str),
]
EXT_FIELDS = [
    (("hardware", "almacenamiento_externo", "modelo"), "Cabina / NAS (modelo)", str),
    (("hardware", "almacenamiento_externo", "capacidad_util_tib"), "Capacidad útil (TiB)", float),
]
SUPPLIERS = {"fsas": "Fsas Technologies", "cliente": "Cliente (existentes o compra propia)"}
SWITCH_MODELS = {
    "servicio": ["Juniper QFX5120-48Y (48× 1/10/25 GbE SFP28 + 8× 100 GbE)", "Juniper QFX5120-32C (32× 40/100 GbE QSFP28)"],
    "almacenamiento": ["Juniper QFX5120-48Y (48× 1/10/25 GbE SFP28 + 8× 100 GbE)", "Switch FC 32 Gb de 24-48 puertos (p. ej. Brocade G620)"],
    "oob": ["Juniper EX2300-48T (48× 1 GbE + 4× 10 GbE)", "Juniper EX2300-24T (24× 1 GbE + 4× 10 GbE)"],
}
IMPL_FIELDS = [
    (("implementacion", "cluster"), "Nombre del clúster", str),
    (("implementacion", "patron_hostname"), "Patrón de nombres ({nn} = 01, 02…)", str),
    (("implementacion", "dominio"), "Dominio DNS", str),
    (("implementacion", "dns"), "Servidores DNS", str),
    (("implementacion", "ntp"), "Servidores NTP", str),
    (("implementacion", "zona_horaria"), "Zona horaria", str),
]


def _get(d, path):
    for p in path:
        d = d[p]
    return d


def _set(d, path, v):
    for p in path[:-1]:
        d = d.setdefault(p, {})
    d[path[-1]] = v


class ServerDialog(tk.Toplevel):
    """Alta/edición de un grupo de servidores idénticos."""

    def __init__(self, master, srv=None):
        super().__init__(master)
        self.title("Servidor de destino")
        self.resizable(False, False)
        self.transient(master)
        self.result = None
        srv = copy.deepcopy(srv or new()["hardware"]["servidores"][0])
        data = next((d for d in srv.get("discos", []) if d.get("uso", "datos") == "datos"), {"cantidad": 0, "tb": 3.84, "tipo": "NVMe"})
        boot = next((d for d in srv.get("discos", []) if d.get("uso") == "arranque"), {"cantidad": 2, "tb": 0.48, "tipo": "SSD M.2"})
        nic = {n.get("uso"): n for n in srv.get("nics", [])}
        self.f = {}
        rows = [
            ("modelo", "Modelo", srv.get("modelo", "")), ("cantidad", "Nº de servidores", srv.get("cantidad", 3)),
            ("cpu", "CPU (descripción)", srv.get("cpu", "")), ("sockets", "Sockets", srv.get("sockets", 2)),
            ("cores_por_socket", "Cores por socket", srv.get("cores_por_socket", 32)), ("ghz", "GHz", srv.get("ghz", 2.3)),
            ("ram_gib", "RAM por servidor (GiB)", srv.get("ram_gib", 768)),
            ("boot_n", "Discos de arranque (nº)", boot.get("cantidad")), ("boot_tb", "  tamaño (TB)", boot.get("tb")),
            ("boot_t", "  tipo", boot.get("tipo")),
            ("data_n", "Discos de datos (nº)", data.get("cantidad")), ("data_tb", "  tamaño (TB)", data.get("tb")),
            ("data_t", "  tipo", data.get("tipo")),
            ("g_n", "Puertos gestión", nic.get("gestion", {}).get("puertos", 2)), ("g_g", "  velocidad (GbE)", nic.get("gestion", {}).get("gbps", 1)),
            ("v_n", "Puertos VMs", nic.get("vms", {}).get("puertos", 2)), ("v_g", "  velocidad (GbE)", nic.get("vms", {}).get("gbps", 25)),
            ("s_n", "Puertos almacenamiento", nic.get("almacenamiento", {}).get("puertos", 2)),
            ("s_g", "  velocidad (GbE)", nic.get("almacenamiento", {}).get("gbps", 25)),
        ]
        frm = ttk.Frame(self, padding=10)
        frm.pack(fill="both")
        for i, (k, lbl, v) in enumerate(rows):
            ttk.Label(frm, text=lbl).grid(row=i, column=0, sticky="w", pady=1)
            var = tk.StringVar(value="" if v is None else str(v))
            ttk.Entry(frm, textvariable=var, width=34).grid(row=i, column=1, sticky="we", padx=6, pady=1)
            self.f[k] = var
        b = ttk.Frame(frm)
        b.grid(row=len(rows), column=0, columnspan=2, pady=(8, 0), sticky="e")
        ttk.Button(b, text="Aceptar", command=self._ok).pack(side="left", padx=4)
        ttk.Button(b, text="Cancelar", command=self.destroy).pack(side="left")
        self.grab_set()

    def _ok(self):
        g = lambda k, t=float: t(self.f[k].get().replace(",", ".") or 0)  # noqa: E731
        try:
            srv = {"modelo": self.f["modelo"].get().strip() or "Servidor", "cantidad": g("cantidad", int), "cpu": self.f["cpu"].get().strip(),
                   "sockets": g("sockets", int), "cores_por_socket": g("cores_por_socket", int), "ghz": g("ghz"), "ram_gib": g("ram_gib", int),
                   "discos": [{"cantidad": g("boot_n", int), "tb": g("boot_tb"), "tipo": self.f["boot_t"].get(), "uso": "arranque"},
                              {"cantidad": g("data_n", int), "tb": g("data_tb"), "tipo": self.f["data_t"].get(), "uso": "datos"}],
                   "nics": [{"puertos": g("g_n", int), "gbps": g("g_g"), "uso": "gestion"},
                            {"puertos": g("v_n", int), "gbps": g("v_g"), "uso": "vms"}]}
            if g("s_n", int):
                srv["nics"].append({"puertos": g("s_n", int), "gbps": g("s_g"), "uso": "almacenamiento"})
            if not srv["cpu"]:
                srv["cpu"] = f"{srv['sockets']}× {srv['cores_por_socket']} cores {srv['ghz']} GHz"
        except ValueError:
            messagebox.showerror("Servidor", "Revisa los valores numéricos.", parent=self)
            return
        self.result = srv
        self.destroy()


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_NAME} {__version__} — Planificador de migración a Proxmox VE · {COMPANY}")
        self.geometry("1220x820")
        self.minsize(980, 640)
        self.sc = new()
        self.files: list[str] = []
        self.sheets = None
        self.plan = None
        self.catalog_path = None
        self.vars = {}
        self._busy = False
        self._build()
        self._from_scenario()
        self.after(300, self._first_run_notice)

    # ------------------------------------------------------------------ UI
    def _build(self):
        style = ttk.Style(self)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        self._images = {}
        try:
            self._images["icon"] = tk.PhotoImage(file=asset_path("fsas_icon.png"))
            self.iconphoto(True, self._images["icon"])
        except tk.TclError:
            pass
        menu = tk.Menu(self)
        m = tk.Menu(menu, tearoff=False)
        m.add_command(label="Añadir inventario Excel…", command=self._add_xlsx)
        m.add_command(label="Añadir carpeta de CSV…", command=self._add_csv)
        m.add_command(label="Informe de solo análisis (sin migración)…", command=self._goto_analysis)
        m.add_separator()
        m.add_command(label="Abrir escenario…", command=self._open_scenario)
        m.add_command(label="Guardar escenario…", command=self._save_scenario)
        m.add_command(label="Cargar catálogo de hardware…", command=self._load_catalog)
        m.add_separator()
        m.add_command(label="Salir", command=self.destroy)
        menu.add_cascade(label="Archivo", menu=m)
        h = tk.Menu(menu, tearoff=False)
        h.add_command(label="Aviso de uso", command=self._show_notice)
        h.add_command(label="Acerca de", command=lambda: messagebox.showinfo(APP_NAME, f"{APP_NAME} {__version__}\n{COMPANY}\n\n{SHORT_NOTICE}"))
        menu.add_cascade(label="Ayuda", menu=h)
        self.config(menu=menu)

        header = tk.Frame(self, bg="white", highlightthickness=1, highlightbackground="#d0d0d0")
        header.pack(fill="x")
        try:
            self._images["logo"] = tk.PhotoImage(file=asset_path("fsas_logo_small.png"))
            tk.Label(header, image=self._images["logo"], bg="white").pack(side="left", padx=12, pady=6)
        except tk.TclError:
            tk.Label(header, text=COMPANY, bg="white", font=("Segoe UI", 16, "bold")).pack(side="left", padx=12, pady=6)
        titles = tk.Frame(header, bg="white")
        titles.pack(side="left", padx=10)
        tk.Label(titles, text=f"{APP_NAME} — Planificador de migración a Proxmox VE", bg="white",
                 font=("Segoe UI", 13, "bold"), fg="#1F4E78").pack(anchor="w")
        tk.Label(titles, text=SHORT_NOTICE, bg="white", fg="#555", font=("Segoe UI", 9)).pack(anchor="w")
        tk.Button(header, text="Aviso de uso", relief="flat", bg="white", fg="#1F4E78", cursor="hand2",
                  font=("Segoe UI", 9, "underline"), command=self._show_notice).pack(side="right", padx=12)

        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=8, pady=8)
        self._tab_inventory()
        self._tab_target()
        self._tab_network()
        self._tab_pbs()
        self._tab_migration()
        self._tab_result()
        self._tab_asbuilt()
        self._tab_analysis()
        self.status = tk.StringVar(value="Carga el Excel o la carpeta de CSV exportados con PVE Inventory.")
        ttk.Label(self, textvariable=self.status, anchor="w", relief="sunken").pack(fill="x", side="bottom")

    def _var(self, path, typ, parent, row, col, label, width=12, values=None, sticky="we"):
        ttk.Label(parent, text=label).grid(row=row, column=col, sticky="w", padx=4, pady=2)
        var = tk.StringVar()
        if values:
            w = ttk.Combobox(parent, textvariable=var, values=values, width=width)
        else:
            w = ttk.Entry(parent, textvariable=var, width=width)
        w.grid(row=row, column=col + 1, sticky=sticky, padx=4, pady=2)
        self.vars[path] = (var, typ)
        return w

    def _tab_inventory(self):
        t = ttk.Frame(self.nb, padding=8)
        self.nb.add(t, text="1 · Inventario")
        bar = ttk.Frame(t)
        bar.pack(fill="x")
        ttk.Button(bar, text="Añadir Excel…", command=self._add_xlsx).pack(side="left")
        ttk.Button(bar, text="Añadir carpeta CSV…", command=self._add_csv).pack(side="left", padx=4)
        ttk.Button(bar, text="Vaciar", command=self._clear_files).pack(side="left")
        ttk.Button(bar, text="Solo análisis (informe sin migración)…", command=self._goto_analysis).pack(side="right")
        self.v_stopped = tk.BooleanVar(value=True)
        self.v_templates = tk.BooleanVar(value=False)
        ttk.Checkbutton(bar, text="Incluir VMs apagadas", variable=self.v_stopped, command=self._refresh_inventory).pack(side="left", padx=(20, 4))
        ttk.Checkbutton(bar, text="Incluir plantillas", variable=self.v_templates, command=self._refresh_inventory).pack(side="left")
        self.files_lbl = ttk.Label(t, text="Sin inventario cargado.", foreground="#555")
        self.files_lbl.pack(fill="x", pady=4)
        self.inv_summary = tk.Text(t, height=6, wrap="word", relief="flat", background="#f7f7f7")
        self.inv_summary.pack(fill="x")
        lf = ttk.LabelFrame(t, text="VMs y contenedores (doble clic o botón para excluir / incluir)")
        lf.pack(fill="both", expand=True, pady=(6, 0))
        cols = ("Incluida", "Clúster", "Nodo", "VMID", "Nombre", "Tipo", "Estado", "vCPU", "RAM (GiB)", "Disco (GiB)", "SO")
        self.vm_tree = ttk.Treeview(lf, columns=cols, show="headings", selectmode="extended")
        for c in cols:
            self.vm_tree.heading(c, text=c)
            self.vm_tree.column(c, width=80 if c not in ("Nombre", "Clúster", "SO") else 160, anchor="w")
        sb = ttk.Scrollbar(lf, orient="vertical", command=self.vm_tree.yview)
        self.vm_tree.configure(yscrollcommand=sb.set)
        self.vm_tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.vm_tree.bind("<Double-1>", lambda e: self._toggle_exclude())
        ttk.Button(t, text="Excluir / incluir seleccionadas", command=self._toggle_exclude).pack(anchor="e", pady=4)

    def _tab_target(self):
        t = ttk.Frame(self.nb, padding=8)
        self.nb.add(t, text="2 · Destino")
        top = ttk.LabelFrame(t, text="Proyecto")
        top.pack(fill="x")
        self._var(("cliente",), str, top, 0, 0, "Cliente", 30)
        self._var(("proyecto",), str, top, 0, 2, "Título del documento", 40)
        self._var(("autor",), str, top, 0, 4, "Preparado por", 24)

        mode = ttk.LabelFrame(t, text="Modo")
        mode.pack(fill="x", pady=6)
        self.v_mode = tk.StringVar(value="aconsejar")
        ttk.Radiobutton(mode, text="Aconsejar hardware (destino desconocido)", value="aconsejar", variable=self.v_mode,
                        command=self._mode_changed).grid(row=0, column=0, sticky="w", padx=4)
        ttk.Radiobutton(mode, text="Usar el hardware disponible / que se va a adquirir", value="hardware", variable=self.v_mode,
                        command=self._mode_changed).grid(row=0, column=1, sticky="w", padx=12)
        self._var(("pve_version",), str, mode, 1, 0, "Versión Proxmox VE destino", 8, PVE_VERSIONS)
        ttk.Label(mode, text="Almacenamiento").grid(row=2, column=0, sticky="w", padx=4)
        self.v_storage = tk.StringVar()
        ttk.Combobox(mode, textvariable=self.v_storage, values=[STORAGE_TYPES[k] for k in STORAGE_KEYS], state="readonly",
                     width=52).grid(row=2, column=1, sticky="w", padx=4, pady=2)
        self._var(("red", "velocidad_gbps"), float, mode, 3, 0, "Velocidad de red de servicio (GbE)", 8, ["10", "25", "40", "100"])
        self.v_jumbo = tk.BooleanVar(value=True)
        ttk.Checkbutton(mode, text="Jumbo frames (MTU 9000) en redes de almacenamiento/migración", variable=self.v_jumbo).grid(
            row=3, column=2, sticky="w", padx=8)

        cap = ttk.LabelFrame(t, text="Criterios de dimensionado")
        cap.pack(fill="x")
        for i, (path, lbl, typ) in enumerate(CAPACITY_FIELDS):
            self._var(path, typ, cap, i // 3, (i % 3) * 2, lbl, 8)
        r = len(CAPACITY_FIELDS) // 3 + 1
        ttk.Label(cap, text="Base de CPU").grid(row=r, column=0, sticky="w", padx=4)
        self.v_basecpu = tk.StringVar()
        ttk.Combobox(cap, textvariable=self.v_basecpu, values=["asignado", "observado"], state="readonly", width=10).grid(row=r, column=1, sticky="w", padx=4)
        ttk.Label(cap, text="Base de disco").grid(row=r, column=2, sticky="w", padx=4)
        self.v_basedisk = tk.StringVar()
        ttk.Combobox(cap, textvariable=self.v_basedisk, values=["usado", "aprovisionado"], state="readonly", width=12).grid(row=r, column=3, sticky="w", padx=4)

        self.hw = ttk.LabelFrame(t, text="Hardware de destino (modo «usar hardware»)")
        self.hw.pack(fill="both", expand=True, pady=6)
        cols = ("Cantidad", "Modelo", "CPU", "Cores", "RAM (GiB)", "Discos datos", "Red")
        self.srv_tree = ttk.Treeview(self.hw, columns=cols, show="headings", height=4)
        for c in cols:
            self.srv_tree.heading(c, text=c)
            self.srv_tree.column(c, width=90 if c in ("Cantidad", "Cores", "RAM (GiB)") else 200, anchor="w")
        self.srv_tree.grid(row=0, column=0, columnspan=6, sticky="nsew", padx=4, pady=4)
        self.srv_tree.bind("<Double-1>", lambda e: self._edit_server())
        bf = ttk.Frame(self.hw)
        bf.grid(row=1, column=0, columnspan=6, sticky="w")
        ttk.Button(bf, text="Añadir servidor…", command=self._add_server).pack(side="left", padx=4)
        ttk.Button(bf, text="Editar…", command=self._edit_server).pack(side="left")
        ttk.Button(bf, text="Quitar", command=self._del_server).pack(side="left", padx=4)
        for i, (path, lbl, typ) in enumerate(EXT_FIELDS):
            self._var(path, typ, self.hw, 2, i * 2, lbl, 18)
        self.hw.columnconfigure(5, weight=1)
        self.hw.rowconfigure(0, weight=1)

    def _tab_network(self):
        t = ttk.Frame(self.nb, padding=8)
        self.nb.add(t, text="3 · Red y switches")
        st = ttk.LabelFrame(t, text="Almacenamiento externo")
        st.pack(fill="x")
        self._var(("almacenamiento", "protocolo"), str, st, 0, 0, "Protocolo de la cabina SAN", 8, ["iSCSI", "FC"])
        ttk.Label(st, foreground="#555", text="FC añade HBAs en los nodos y una pareja de switches FC (fabrics A/B).").grid(row=0, column=2, sticky="w", padx=8)
        self.sw_vars = {}
        for r, (kind, title) in enumerate((("servicio", "Switches de servicio (ToR) · VMs, gestión, migración, backup"),
                                            ("almacenamiento", "Switches de almacenamiento dedicados (Ceph / iSCSI / NFS) o FC"),
                                            ("oob", "Switch de gestión fuera de banda (OOB / iRMC)"))):
            f = ttk.LabelFrame(t, text=title)
            f.pack(fill="x", pady=4)
            col = 0
            if kind == "almacenamiento":
                v = tk.BooleanVar()
                ttk.Checkbutton(f, text="Usar switches dedicados (con FC siempre)", variable=v).grid(row=0, column=0, columnspan=2, sticky="w", padx=4)
                self.sw_vars[(kind, "dedicados")] = v
                col = 0
                row = 1
            else:
                row = 0
            ttk.Label(f, text="¿Quién los suministra?").grid(row=row, column=col, sticky="w", padx=4)
            v = tk.StringVar()
            ttk.Combobox(f, textvariable=v, values=list(SUPPLIERS.values()), state="readonly", width=34).grid(row=row, column=col + 1, sticky="w", padx=4, pady=2)
            self.sw_vars[(kind, "suministra")] = v
            self._var(("switches", kind, "modelo"), str, f, row, col + 2, "Modelo (vacío = se propone)", 46, SWITCH_MODELS[kind])
            f2 = ttk.Frame(f)
            f2.grid(row=row + 1, column=0, columnspan=4, sticky="w")
            self._var(("switches", kind, "cantidad"), int, f2, 0, 0, "Nº de switches", 6, sticky="w")
            self._var(("switches", kind, "puertos"), int, f2, 0, 2, "Puertos por switch", 6, sticky="w")
            self._var(("switches", kind, "gbps"), float, f2, 0, 4, "Velocidad (Gb)", 6, ["1", "10", "25", "100", "32"], sticky="w")
        imp = ttk.LabelFrame(t, text="Datos para la implementación (opcional; si se dejan vacíos se proponen a partir del inventario)")
        imp.pack(fill="x", pady=4)
        for i, (path, lbl, typ) in enumerate(IMPL_FIELDS):
            self._var(path, typ, imp, i // 3, (i % 3) * 2, lbl, 22)

    def _tab_pbs(self):
        t = ttk.Frame(self.nb, padding=8)
        self.nb.add(t, text="4 · Backup (PBS)")
        self.v_pbs = tk.BooleanVar(value=True)
        ttk.Checkbutton(t, text="Incluir Proxmox Backup Server en el nuevo entorno", variable=self.v_pbs).pack(anchor="w")
        self.v_offsite = tk.BooleanVar(value=False)
        ttk.Checkbutton(t, text="Añadir copia externa (segundo PBS sincronizado en otra ubicación)", variable=self.v_offsite).pack(anchor="w")
        f = ttk.LabelFrame(t, text="Retención y supuestos")
        f.pack(fill="x", pady=6)
        for i, (path, lbl, typ) in enumerate(PBS_FIELDS):
            self._var(path, typ, f, i // 4, (i % 4) * 2, lbl, 8)
        h = ttk.LabelFrame(t, text="Hardware del PBS")
        h.pack(fill="x")
        self.v_pbs_hw = tk.BooleanVar(value=False)
        ttk.Checkbutton(h, text="Usar un PBS ya definido (si no, se aconseja uno)", variable=self.v_pbs_hw).grid(row=0, column=0, columnspan=4, sticky="w")
        for i, (path, lbl, typ) in enumerate(PBS_HW_FIELDS):
            self._var(path, typ, h, 1 + i // 3, (i % 3) * 2, lbl, 18)
        ttk.Label(t, foreground="#555", wraplength=900, justify="left", text=(
            "Capacidad = datos usados × reducción × (1 + cambio diario × días de cambios retenidos) / llenado máximo. "
            "Los días retenidos se ponderan: cada copia semanal cuenta como 2 días de cambios, la mensual como 4 y la anual como 8.")).pack(anchor="w", pady=8)

    def _tab_migration(self):
        t = ttk.Frame(self.nb, padding=8)
        self.nb.add(t, text="5 · Migración")
        f = ttk.LabelFrame(t, text="Método y olas")
        f.pack(fill="x")
        ttk.Label(f, text="Método").grid(row=0, column=0, sticky="w", padx=4)
        self.v_method = tk.StringVar()
        ttk.Combobox(f, textvariable=self.v_method, values=list(METHODS.values()), state="readonly", width=52).grid(row=0, column=1, columnspan=3, sticky="w", padx=4)
        for i, (path, lbl, typ) in enumerate(MIG_FIELDS):
            self._var(path, typ, f, 1 + i // 3, (i % 3) * 2, lbl, 12)
        ttk.Label(t, foreground="#555", wraplength=900, justify="left", text=(
            "La ola 0 es un piloto con VMs pequeñas y no críticas. Después se agrupan por clúster y pool; las críticas "
            "(HA, bases de datos, controladores de dominio, orden de arranque) van al final y las que tienen bloqueos en una ola aparte.")).pack(anchor="w", pady=8)

    def _tab_result(self):
        t = ttk.Frame(self.nb, padding=8)
        self.nb.add(t, text="6 · Plan y documentos")
        bar = ttk.Frame(t)
        bar.pack(fill="x")
        ttk.Button(bar, text="Calcular plan", command=self._calculate).pack(side="left")
        ttk.Button(bar, text="Generar documentos…", command=self._export).pack(side="left", padx=(16, 4))
        st = self._settings()
        self.v_out = {k: tk.BooleanVar(value=st.get("out_" + k, True)) for k in ("xlsx", "design", "impl")}
        self.v_out["config"] = tk.BooleanVar(value=bool(st.get("config_template")) and st.get("out_config", True))
        self.v_charts = tk.BooleanVar(value=st.get("out_charts", False))
        opts = ttk.LabelFrame(t, text="Documentos a generar")
        opts.pack(fill="x", pady=(6, 0))
        for i, (k, txt) in enumerate((("xlsx", "Excel del plan (preventa / arquitecto)"),
                                      ("design", "Word: diseño para el cliente"),
                                      ("impl", "Word: guía de implementación (servicios profesionales)"),
                                      ("config", "Hoja de configuración rellena (desde plantilla)"))):
            ttk.Checkbutton(opts, text=txt, variable=self.v_out[k]).grid(row=i // 2, column=i % 2, sticky="w", padx=6, pady=1)
        ttk.Checkbutton(opts, text="Guardar también los gráficos (PNG)", variable=self.v_charts).grid(row=2, column=0, sticky="w", padx=6, pady=1)
        ttk.Label(opts, text="Plantilla de la hoja de configuración:").grid(row=3, column=0, sticky="w", padx=6, pady=2)
        self.v_template = tk.StringVar(value=st.get("config_template", ""))
        tf = ttk.Frame(opts)
        tf.grid(row=3, column=1, sticky="we", padx=6, pady=2)
        ttk.Entry(tf, textvariable=self.v_template, width=60).pack(side="left", fill="x", expand=True)
        ttk.Button(tf, text="…", width=3, command=self._pick_template).pack(side="left", padx=2)
        opts.columnconfigure(1, weight=1)
        pw = ttk.PanedWindow(t, orient="vertical")
        pw.pack(fill="both", expand=True, pady=6)
        self.result_txt = tk.Text(pw, height=14, wrap="word", font=("Consolas", 10))
        pw.add(self.result_txt, weight=1)
        lf = ttk.LabelFrame(pw, text="Riesgos y puntos a revisar")
        cols = ("Severidad", "Clúster", "VMID", "Nombre", "Categoría", "Detalle")
        self.risk_tree = ttk.Treeview(lf, columns=cols, show="headings")
        for c in cols:
            self.risk_tree.heading(c, text=c)
            self.risk_tree.column(c, width=600 if c == "Detalle" else 100, anchor="w")
        self.risk_tree.tag_configure("BLOQUEO", background="#F8CBAD")
        self.risk_tree.tag_configure("AVISO", background="#FFE699")
        sb = ttk.Scrollbar(lf, orient="vertical", command=self.risk_tree.yview)
        self.risk_tree.configure(yscrollcommand=sb.set)
        self.risk_tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        pw.add(lf, weight=1)

    def _tab_asbuilt(self):
        t = ttk.Frame(self.nb, padding=10)
        self.nb.add(t, text="7 · As-built (postventa)")
        ttk.Label(t, foreground="#555", wraplength=980, justify="left", text=(
            "Documentación de lo que queda configurado, para el departamento de postventa. Tras la implementación, "
            "ejecuta PVE Inventory sobre el NUEVO entorno Proxmox y carga aquí su Excel (o carpeta de CSV). "
            "Opcionalmente añade la hoja de configuración ya completada por servicios profesionales: se incluyen sus datos "
            "salvo contraseñas, claves y tokens.")).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 10))
        self.v_ab_inv = tk.StringVar()
        self.v_ab_cfg = tk.StringVar()
        self.v_ab_client = tk.StringVar()
        self.v_ab_author = tk.StringVar(value=self._settings().get("author", ""))
        rows = (("Inventario del nuevo entorno:", self.v_ab_inv, self._pick_ab_inv),
                ("Hoja de configuración completada (opcional):", self.v_ab_cfg, self._pick_ab_cfg),
                ("Cliente:", self.v_ab_client, None), ("Autor (servicios profesionales):", self.v_ab_author, None))
        for i, (lbl, var, cmd) in enumerate(rows, start=1):
            ttk.Label(t, text=lbl).grid(row=i, column=0, sticky="w", padx=4, pady=3)
            ttk.Entry(t, textvariable=var, width=80).grid(row=i, column=1, sticky="we", padx=4, pady=3)
            if cmd:
                ttk.Button(t, text="…", width=3, command=cmd).grid(row=i, column=2, sticky="w")
        ttk.Button(t, text="Generar documentación as-built…", command=self._asbuilt).grid(row=6, column=1, sticky="w", padx=4, pady=12)
        t.columnconfigure(1, weight=1)

    def _tab_analysis(self):
        t = ttk.Frame(self.nb, padding=10)
        self.analysis_tab = t
        self.nb.add(t, text="8 · Solo análisis")
        ttk.Label(t, foreground="#555", wraplength=1100, justify="left", text=(
            "Informe de la infraestructura actual, como un RVTools / health check: capacidad, uso, distribución de VMs, "
            "almacenamiento, red, backup y hallazgos con recomendaciones, con gráficos. No propone migración, hardware ni olas. "
            "Usa el inventario cargado en la pestaña 1 (también vale un inventario anonimizado).")).pack(anchor="w", pady=(0, 8))
        st = self._settings()
        f = ttk.Frame(t)
        f.pack(fill="x")
        self.v_an_client = tk.StringVar()
        self.v_an_author = tk.StringVar(value=st.get("author", ""))
        ttk.Label(f, text="Cliente:").grid(row=0, column=0, sticky="w", padx=4, pady=2)
        ttk.Entry(f, textvariable=self.v_an_client, width=40).grid(row=0, column=1, sticky="w", padx=4)
        ttk.Label(f, text="Autor:").grid(row=0, column=2, sticky="w", padx=(16, 4))
        ttk.Entry(f, textvariable=self.v_an_author, width=30).grid(row=0, column=3, sticky="w", padx=4)
        self.v_an_docx = tk.BooleanVar(value=st.get("an_docx", True))
        self.v_an_xlsx = tk.BooleanVar(value=st.get("an_xlsx", True))
        self.v_an_charts = tk.BooleanVar(value=st.get("an_charts", False))
        ttk.Checkbutton(f, text="Word con gráficos", variable=self.v_an_docx).grid(row=1, column=0, columnspan=2, sticky="w", padx=4)
        ttk.Checkbutton(f, text="Excel con datos y hallazgos", variable=self.v_an_xlsx).grid(row=1, column=2, columnspan=2, sticky="w", padx=4)
        ttk.Checkbutton(f, text="Guardar también los gráficos (PNG)", variable=self.v_an_charts).grid(row=1, column=4, sticky="w", padx=4)
        bar = ttk.Frame(t)
        bar.pack(fill="x", pady=6)
        ttk.Button(bar, text="Analizar", command=self._analyze).pack(side="left")
        ttk.Button(bar, text="Generar informe…", command=self._export_analysis).pack(side="left", padx=8)
        pw = ttk.PanedWindow(t, orient="vertical")
        pw.pack(fill="both", expand=True)
        self.an_txt = tk.Text(pw, height=11, wrap="word", font=("Consolas", 10))
        pw.add(self.an_txt, weight=1)
        lf = ttk.LabelFrame(pw, text="Hallazgos")
        cols = ("Severidad", "Categoría", "Hallazgo", "Afectados", "Objetos", "Recomendación")
        self.an_tree = ttk.Treeview(lf, columns=cols, show="headings")
        for c in cols:
            self.an_tree.heading(c, text=c)
            self.an_tree.column(c, width={"Hallazgo": 300, "Objetos": 260, "Recomendación": 360, "Categoría": 120, "Afectados": 70}.get(c, 90), anchor="w")
        for tag, color in (("CRÍTICO", "#F8CBAD"), ("AVISO", "#FFE699"), ("INFO", "#DDEBF7")):
            self.an_tree.tag_configure(tag, background=color)
        sb = ttk.Scrollbar(lf, orient="vertical", command=self.an_tree.yview)
        self.an_tree.configure(yscrollcommand=sb.set)
        self.an_tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        pw.add(lf, weight=1)

    def _goto_analysis(self):
        self.nb.select(self.analysis_tab)
        if self.sheets:
            self._analyze()
        else:
            self._add_xlsx()
            if self.sheets:
                self._analyze()

    def _analyze(self):
        if not self.sheets:
            messagebox.showinfo(APP_NAME, "Primero carga el inventario (pestaña 1).")
            return None
        from .assessment import Assessment
        a = Assessment(self.sheets, self.v_an_client.get().strip(), self.v_an_author.get().strip())
        self.an_txt.delete("1.0", "end")
        self.an_txt.insert("end", a.text_summary())
        self.an_tree.delete(*self.an_tree.get_children())
        for f in a.findings:
            self.an_tree.insert("", "end", values=(f["Severidad"], f["Categoría"], f["Hallazgo"], f["Afectados"],
                                                   ", ".join(map(str, f["Objetos"][:20])), f["Recomendación"]), tags=(f["Severidad"],))
        self.status.set(f"Análisis: {len(a.findings)} hallazgos. Pulsa «Generar informe…» para crear el Word y el Excel.")
        return a

    def _export_analysis(self):
        a = self._analyze()
        if not a:
            return
        docx, xlsx, charts = self.v_an_docx.get(), self.v_an_xlsx.get(), self.v_an_charts.get()
        if not (docx or xlsx):
            messagebox.showwarning(APP_NAME, "Marca al menos un documento.")
            return
        folder = self._ask_folder("Carpeta donde guardar el informe")
        if not folder:
            return
        self._save_settings(author=self.v_an_author.get().strip(), an_docx=docx, an_xlsx=xlsx, an_charts=charts)
        base = "Analisis_infraestructura" + ("_" + safe_filename(a.client) if a.client else "")

        def job():
            from .report_assessment import generate
            return generate(a, folder, base, docx=docx, xlsx=xlsx, charts=charts and docx)

        self._run_job("Generando informe de análisis…", job, folder)

    def _pick_template(self):
        p = filedialog.askopenfilename(title="Plantilla de la hoja de configuración", filetypes=[("Excel", "*.xlsx")])
        if p:
            self.v_template.set(p)
            self.v_out["config"].set(True)

    def _pick_ab_inv(self):
        p = filedialog.askopenfilename(title="Inventario del nuevo entorno", filetypes=[("Excel", "*.xlsx"), ("Todos", "*.*")])
        if not p:
            p = filedialog.askdirectory(title="…o carpeta con los CSV")
        if p:
            self.v_ab_inv.set(p)

    def _pick_ab_cfg(self):
        p = filedialog.askopenfilename(title="Hoja de configuración completada", filetypes=[("Excel", "*.xlsx")])
        if p:
            self.v_ab_cfg.set(p)

    def _asbuilt(self):
        src = self.v_ab_inv.get().strip()
        if not src:
            messagebox.showwarning(APP_NAME, "Indica el inventario (Excel o carpeta de CSV) del nuevo entorno.")
            return
        try:
            sheets = load([src])
        except (InventoryError, OSError) as exc:
            messagebox.showerror(APP_NAME, str(exc))
            return
        client = self.v_ab_client.get().strip() or (self.sc.get("cliente") or "")
        default = "Documentacion_asbuilt" + ("_" + safe_filename(client) if client else "") + ".docx"
        p = filedialog.asksaveasfilename(defaultextension=".docx", initialfile=default, initialdir=self._out_dir(),
                                         filetypes=[("Word", "*.docx")])
        if not p:
            return
        p = os.path.abspath(ensure_ext(os.path.normpath(p), ".docx"))
        self._save_settings(author=self.v_ab_author.get().strip(), last_output_dir=os.path.dirname(p))
        cfg = self.v_ab_cfg.get().strip() or None
        author = self.v_ab_author.get().strip()

        def job():
            from .report_asbuilt import to_asbuilt_docx
            return [to_asbuilt_docx(sheets, p, client, author, cfg)]

        self._run_job("Generando documentación as-built…", job, p)

    # ------------------------------------------------------------------ escenario <-> UI
    def _from_scenario(self):
        sc = self.sc
        for path, (var, _typ) in self.vars.items():
            try:
                v = _get(sc, path)
            except (KeyError, TypeError):
                v = ""
            var.set("" if v is None else (f"{v:g}" if isinstance(v, float) else str(v)))
        self.v_mode.set(sc["modo"])
        self.v_storage.set(STORAGE_TYPES[sc["almacenamiento"]["tipo"]])
        self.v_jumbo.set(sc["red"].get("jumbo", True))
        for (kind, key), var in self.sw_vars.items():
            val = sc.get("switches", {}).get(kind, {}).get(key)
            var.set(bool(val) if key == "dedicados" else SUPPLIERS.get(val or "fsas"))
        self.v_basecpu.set(sc["capacidad"]["base_cpu"])
        self.v_basedisk.set(sc["capacidad"]["base_disco"])
        self.v_pbs.set(sc["pbs"]["incluir"])
        self.v_offsite.set(sc["pbs"].get("offsite", False))
        self.v_pbs_hw.set(sc["pbs"]["hardware"].get("definido", False))
        self.v_method.set(METHODS.get(sc["migracion"]["metodo"], METHODS["auto"]))
        self.v_stopped.set(sc["alcance"]["incluir_apagadas"])
        self.v_templates.set(sc["alcance"]["incluir_plantillas"])
        self._refresh_servers()
        self._mode_changed()

    def _to_scenario(self) -> dict:
        sc = copy.deepcopy(self.sc)
        for path, (var, typ) in self.vars.items():
            raw = var.get().strip()
            if typ is str:
                _set(sc, path, raw)
                continue
            try:
                _set(sc, path, typ(float(raw.replace(",", "."))) if raw else 0)
            except ValueError:
                raise ValueError(f"Valor no válido en «{path[-1]}»: {raw}") from None
        sc["modo"] = self.v_mode.get()
        sc["almacenamiento"]["tipo"] = next((k for k, v in STORAGE_TYPES.items() if v == self.v_storage.get()), "ceph")
        sc["red"]["jumbo"] = self.v_jumbo.get()
        for (kind, key), var in self.sw_vars.items():
            sc["switches"].setdefault(kind, {})[key] = (var.get() if key == "dedicados"
                                                        else next((k for k, v in SUPPLIERS.items() if v == var.get()), "fsas"))
        sc["capacidad"]["base_cpu"] = self.v_basecpu.get() or "asignado"
        sc["capacidad"]["base_disco"] = self.v_basedisk.get() or "usado"
        sc["pbs"]["incluir"] = self.v_pbs.get()
        sc["pbs"]["offsite"] = self.v_offsite.get()
        sc["pbs"]["hardware"]["definido"] = self.v_pbs_hw.get()
        sc["migracion"]["metodo"] = next((k for k, v in METHODS.items() if v == self.v_method.get()), "auto")
        sc["alcance"]["incluir_apagadas"] = self.v_stopped.get()
        sc["alcance"]["incluir_plantillas"] = self.v_templates.get()
        return sc

    def _mode_changed(self):
        state = "normal" if self.v_mode.get() == "hardware" else "disabled"
        for w in self.hw.winfo_children():
            for x in [w] + list(w.winfo_children()):
                try:
                    x.configure(state=state)
                except tk.TclError:
                    pass

    # ------------------------------------------------------------------ servidores
    def _refresh_servers(self):
        self.srv_tree.delete(*self.srv_tree.get_children())
        for i, s in enumerate(self.sc["hardware"]["servidores"]):
            data = [d for d in s.get("discos", []) if d.get("uso") == "datos" and d.get("cantidad")]
            self.srv_tree.insert("", "end", iid=str(i), values=(
                s.get("cantidad"), s.get("modelo"), s.get("cpu"), int(s.get("sockets", 0)) * int(s.get("cores_por_socket", 0)),
                s.get("ram_gib"), ", ".join(f"{d['cantidad']}× {d['tb']} TB {d.get('tipo', '')}" for d in data) or "-",
                ", ".join(f"{n['puertos']}×{n['gbps']:g}G {n.get('uso', '')}" for n in s.get("nics", []))))

    def _add_server(self):
        d = ServerDialog(self)
        self.wait_window(d)
        if d.result:
            self.sc["hardware"]["servidores"].append(d.result)
            self._refresh_servers()

    def _edit_server(self):
        sel = self.srv_tree.selection()
        if not sel:
            return
        i = int(sel[0])
        d = ServerDialog(self, self.sc["hardware"]["servidores"][i])
        self.wait_window(d)
        if d.result:
            self.sc["hardware"]["servidores"][i] = d.result
            self._refresh_servers()

    def _del_server(self):
        for iid in sorted((int(x) for x in self.srv_tree.selection()), reverse=True):
            del self.sc["hardware"]["servidores"][iid]
        self._refresh_servers()

    # ------------------------------------------------------------------ inventario
    def _add_xlsx(self):
        ps = filedialog.askopenfilenames(title="Inventario de PVE Inventory", filetypes=[("Excel", "*.xlsx"), ("Todos", "*.*")])
        if ps:
            self._load_files(self.files + list(ps))

    def _add_csv(self):
        p = filedialog.askdirectory(title="Carpeta con los CSV de PVE Inventory")
        if p:
            self._load_files(self.files + [p])

    def _clear_files(self):
        self.files, self.sheets, self.plan = [], None, None
        self.files_lbl.configure(text="Sin inventario cargado.")
        self.inv_summary.delete("1.0", "end")
        self.vm_tree.delete(*self.vm_tree.get_children())

    def _load_files(self, files):
        try:
            sheets = load(files)
        except (InventoryError, OSError, ValueError) as exc:
            messagebox.showerror("Inventario", str(exc))
            return
        self.files, self.sheets = files, sheets
        self.files_lbl.configure(text="Cargado: " + " · ".join(os.path.basename(f.rstrip("/\\")) for f in files))
        warns = format_warnings(sheets)
        if warns:
            messagebox.showwarning("Inventario", "\n".join(warns))
        self._refresh_inventory()
        self.status.set(f"Inventario cargado: {len(sheets['vInfo'])} VMs/CTs. Revisa el destino y calcula el plan.")

    def _refresh_inventory(self):
        if not self.sheets:
            return
        from .analysis import Analysis
        excl = set(self.sc["alcance"].get("excluir") or [])
        an = Analysis(self.sheets, self.v_stopped.get(), self.v_templates.get(), excl)
        t = an.totals()
        self.inv_summary.delete("1.0", "end")
        self.inv_summary.insert("end", (
            f"En el alcance: {t['vms']} VMs y {t['cts']} CTs ({t['running']} encendidas) · {t['vcpu']:.0f} vCPU · {t['ram_gib']:.0f} GiB RAM · "
            f"{t['disk_eff_gib'] / 1024:.1f} TiB usados ({t['disk_prov_gib'] / 1024:.1f} TiB aprovisionados). Excluidas: {t['excluded']}.\n"
            f"Origen: {t['clusters']} clúster(es)/nodos independientes, {t['hosts']} servidores, {t['host_cores']} cores, "
            f"{t['host_ram_gib']:.0f} GiB RAM · Proxmox VE {', '.join(an.pve_versions()) or '?'}.\n"
            f"Redes usadas por VMs: {len(an.vlan_usage())} combinaciones bridge/VLAN · Ceph en origen: {'sí' if an.has_ceph() else 'no'}."))
        in_scope = {g.key for g in an.guests}
        self.vm_tree.delete(*self.vm_tree.get_children())
        for g in an.all_guests:
            self.vm_tree.insert("", "end", iid=g.key, values=(
                "Sí" if g.key in in_scope else "No", g.cluster, g.node, g.vmid, g.name, g.kind,
                "plantilla" if g.template else ("encendida" if g.running else "apagada"), f"{g.vcpu:g}",
                f"{g.ram_gib:.1f}", f"{g.disk_effective_gib:.0f}", g.os_label))

    def _toggle_exclude(self):
        excl = set(self.sc["alcance"].get("excluir") or [])
        for k in self.vm_tree.selection():
            excl.symmetric_difference_update({k})
        self.sc["alcance"]["excluir"] = sorted(excl)
        self._refresh_inventory()

    # ------------------------------------------------------------------ cálculo
    def _calculate(self, quiet=False):
        if not self.sheets:
            messagebox.showinfo(APP_NAME, "Primero carga el inventario (pestaña 1).")
            return None
        try:
            sc = self._to_scenario()
        except ValueError as exc:
            messagebox.showerror(APP_NAME, str(exc))
            return None
        self.sc = sc
        from .planner import Plan, PlanError
        try:
            self.plan = Plan(self.sheets, sc, self.catalog_path)
        except PlanError as exc:
            messagebox.showerror(APP_NAME, str(exc))
            return None
        self.result_txt.delete("1.0", "end")
        self.result_txt.insert("end", self.plan.text_summary())
        self.risk_tree.delete(*self.risk_tree.get_children())
        for r in self.plan.issues:
            self.risk_tree.insert("", "end", values=tuple(r.values()), tags=(r["Severidad"],))
        self.nb.select(5)
        self.status.set("Plan calculado: " + ("capacidad OK." if self.plan.eval["ok"] else "¡capacidad insuficiente! Revisa el resumen."))
        return self.plan

    def _export(self):
        plan = self._calculate()
        if not plan:
            return
        sel = {k: v.get() for k, v in self.v_out.items()}
        tmpl = self.v_template.get().strip()
        if sel["config"] and not tmpl:
            if not messagebox.askyesno(APP_NAME, "No has indicado la plantilla de la hoja de configuración.\n¿Continuar sin ella?"):
                return
            sel["config"] = False
        if not any(sel.values()):
            messagebox.showwarning(APP_NAME, "Marca al menos un documento.")
            return
        folder = self._ask_folder("Carpeta donde guardar los documentos")
        if not folder:
            return
        self._save_settings(config_template=tmpl, out_charts=self.v_charts.get(), **{"out_" + k: v for k, v in sel.items()})
        base = "Plan_migracion_" + safe_filename(plan.sc.get("cliente") or "", "plan")
        charts = self.v_charts.get()

        def job():
            from .outputs import generate
            return generate(plan, folder, base, xlsx=sel["xlsx"], design=sel["design"], impl=sel["impl"],
                            charts=charts and sel["design"], config_template=tmpl if sel["config"] else None)

        self._run_job("Generando documentos…", job, folder)

    # ------------------------------------------------------------------ generación en segundo plano
    def _out_dir(self) -> str:
        return default_folder(self._settings().get("last_output_dir"))

    def _ask_folder(self, title: str):
        folder = filedialog.askdirectory(title=title, initialdir=self._out_dir())
        if not folder:
            return None
        folder = os.path.abspath(os.path.normpath(folder))
        self._save_settings(last_output_dir=folder)
        return folder

    def _run_job(self, label: str, fn, where: str):
        """Genera en un hilo aparte; impide lanzar dos generaciones a la vez (escribirían los mismos ficheros)."""
        if self._busy:
            messagebox.showinfo(APP_NAME, "Ya se están generando documentos. Espera a que termine.")
            return
        self._busy = True
        self.config(cursor="watch")
        self.status.set(label)

        def work():
            try:
                out = [os.path.abspath(p) for p in fn()]
            except Exception as exc:  # noqa: BLE001
                self.after(0, lambda e=exc: self._job_end(None, e, where))
            else:
                self.after(0, lambda: self._job_end(out, None, where))

        threading.Thread(target=work, daemon=True).start()

    def _job_end(self, out, exc, where):
        self._busy = False
        self.config(cursor="")
        if exc is not None:
            self.status.set("No se pudo generar: " + str(exc).splitlines()[0][:200])
            messagebox.showerror(APP_NAME, "No se pudo generar.\n\n" + explain(exc, where))
            return
        self._done(out)

    def _on_close(self):
        if self._busy and not messagebox.askyesno(
                APP_NAME, "Todavía se están generando documentos.\nSi cierras ahora, no se guardarán.\n\n¿Cerrar igualmente?"):
            return
        self.destroy()

    def _done(self, out):
        folder = os.path.dirname(out[0]) if out else ""
        self.status.set(f"Generado en {folder}: " + " · ".join(os.path.basename(p) for p in out))
        if messagebox.askyesno(APP_NAME, f"Documentos generados en:\n{folder}\n\n"
                               + "\n".join("• " + os.path.basename(p) for p in out) + "\n\n¿Mostrar en la carpeta?"):
            reveal(out[0])

    # ------------------------------------------------------------------ ficheros
    def _open_scenario(self):
        p = filedialog.askopenfilename(filetypes=[("Escenario", "*.json")])
        if p:
            try:
                self.sc = load_scenario(p)
            except (OSError, json.JSONDecodeError) as exc:
                messagebox.showerror(APP_NAME, str(exc))
                return
            self._from_scenario()
            self._refresh_inventory()

    def _save_scenario(self):
        try:
            sc = self._to_scenario()
        except ValueError as exc:
            messagebox.showerror(APP_NAME, str(exc))
            return
        p = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("Escenario", "*.json")],
                                         initialdir=self._out_dir())
        if p:
            p = os.path.abspath(ensure_ext(os.path.normpath(p), ".json"))
            try:
                save_scenario(sc, p)
            except Exception as exc:  # noqa: BLE001
                messagebox.showerror(APP_NAME, explain(exc, p))
                return
            self.sc = sc
            self.status.set(f"Escenario guardado en {p}")

    def _load_catalog(self):
        p = filedialog.askopenfilename(filetypes=[("Catálogo", "*.json")])
        if p:
            self.catalog_path = p
            self.status.set(f"Catálogo de hardware: {p}")

    # ------------------------------------------------------------------ aviso
    def _settings(self):
        try:
            with open(SETTINGS_FILE, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def _save_settings(self, **kw):
        try:
            os.makedirs(CONFIG_DIR, exist_ok=True)
            st = self._settings()
            st.update(kw)
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(st, f)
        except OSError:
            pass

    def _first_run_notice(self):
        if self._settings().get("disclaimer_accepted") != DISCLAIMER_VERSION:
            self._show_notice(first=True)

    def _show_notice(self, first=False):
        d = tk.Toplevel(self)
        d.title(DISCLAIMER_TITLE)
        d.transient(self)
        d.resizable(False, False)
        frm = tk.Frame(d, bg="white", padx=16, pady=12)
        frm.pack(fill="both", expand=True)
        if "logo" in self._images:
            tk.Label(frm, image=self._images["logo"], bg="white").pack(anchor="w")
        tk.Label(frm, text=DISCLAIMER, bg="white", justify="left", wraplength=560, font=("Segoe UI", 10)).pack(anchor="w", pady=8)

        def ok():
            if first:
                os.makedirs(CONFIG_DIR, exist_ok=True)
                s = self._settings()
                s["disclaimer_accepted"] = DISCLAIMER_VERSION
                with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                    json.dump(s, f)
            d.destroy()

        ttk.Button(frm, text="Acepto" if first else "Cerrar", command=ok).pack(anchor="e")
        if first:
            d.protocol("WM_DELETE_WINDOW", self.destroy)
        d.grab_set()


def _report_error(app):
    """El .exe no tiene consola: cualquier error no previsto se muestra en una ventana en lugar de perderse."""
    def handler(exc, val, tb):
        import traceback
        detail = "".join(traceback.format_exception(exc, val, tb))
        messagebox.showerror(APP_NAME, f"Error inesperado: {val}\n\n{detail[-1500:]}")
    app.report_callback_exception = handler


def main():
    app = App()
    _report_error(app)
    app.protocol("WM_DELETE_WINDOW", app._on_close)
    app.mainloop()
    return 0
