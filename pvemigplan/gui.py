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
    (("hardware", "almacenamiento_externo", "protocolo"), "Protocolo", str),
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
        self._tab_pbs()
        self._tab_migration()
        self._tab_result()
        self.status = tk.StringVar(value="Carga el Excel o la carpeta de CSV exportados con PVE Inventory.")
        ttk.Label(self, textvariable=self.status, anchor="w", relief="sunken").pack(fill="x", side="bottom")

    def _var(self, path, typ, parent, row, col, label, width=12, values=None):
        ttk.Label(parent, text=label).grid(row=row, column=col, sticky="w", padx=4, pady=2)
        var = tk.StringVar()
        if values:
            w = ttk.Combobox(parent, textvariable=var, values=values, width=width)
        else:
            w = ttk.Entry(parent, textvariable=var, width=width)
        w.grid(row=row, column=col + 1, sticky="we", padx=4, pady=2)
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
            self._var(path, typ, self.hw, 2, i * 2, lbl, 18, ["iSCSI", "FC", "NFS"] if path[-1] == "protocolo" else None)
        self._var(("hardware", "switches", "modelo"), str, self.hw, 3, 0, "Switches (modelo)", 18)
        self._var(("hardware", "switches", "cantidad"), int, self.hw, 3, 2, "Nº switches", 6)
        self._var(("hardware", "switches", "puertos"), int, self.hw, 3, 4, "Puertos por switch", 6)
        self.hw.columnconfigure(5, weight=1)
        self.hw.rowconfigure(0, weight=1)

    def _tab_pbs(self):
        t = ttk.Frame(self.nb, padding=8)
        self.nb.add(t, text="3 · Backup (PBS)")
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
        self.nb.add(t, text="4 · Migración")
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
        self.nb.add(t, text="5 · Plan y documentos")
        bar = ttk.Frame(t)
        bar.pack(fill="x")
        ttk.Button(bar, text="Calcular plan", command=self._calculate).pack(side="left")
        ttk.Button(bar, text="Generar Excel + Word…", command=lambda: self._export(True, True)).pack(side="left", padx=(16, 4))
        ttk.Button(bar, text="Solo Excel…", command=lambda: self._export(True, False)).pack(side="left")
        ttk.Button(bar, text="Solo Word…", command=lambda: self._export(False, True)).pack(side="left", padx=4)
        self.v_charts = tk.BooleanVar(value=False)
        ttk.Checkbutton(bar, text="Guardar también los gráficos (PNG)", variable=self.v_charts).pack(side="left", padx=12)
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
        self.nb.select(4)
        self.status.set("Plan calculado: " + ("capacidad OK." if self.plan.eval["ok"] else "¡capacidad insuficiente! Revisa el resumen."))
        return self.plan

    def _export(self, xlsx, docx):
        plan = self._calculate()
        if not plan:
            return
        base = (plan.sc.get("cliente") or "plan").strip().replace(" ", "_")
        if xlsx and docx:
            folder = filedialog.askdirectory(title="Carpeta donde guardar el plan")
            if not folder:
                return
            paths = (os.path.join(folder, f"Plan_migracion_{base}.xlsx"), os.path.join(folder, f"Plan_migracion_{base}.docx"))
        elif xlsx:
            p = filedialog.asksaveasfilename(defaultextension=".xlsx", initialfile=f"Plan_migracion_{base}.xlsx", filetypes=[("Excel", "*.xlsx")])
            if not p:
                return
            paths = (p, None)
        else:
            p = filedialog.asksaveasfilename(defaultextension=".docx", initialfile=f"Plan_migracion_{base}.docx", filetypes=[("Word", "*.docx")])
            if not p:
                return
            paths = (None, p)
        self.status.set("Generando documentos…")
        charts = self.v_charts.get()

        def work():
            try:
                out = []
                if paths[0]:
                    from .report_xlsx import to_xlsx
                    out.append(to_xlsx(plan, paths[0]))
                if paths[1]:
                    from .report_docx import to_docx
                    cdir = None
                    if charts:
                        cdir = os.path.splitext(paths[1])[0] + "_graficos"
                        os.makedirs(cdir, exist_ok=True)
                    out.append(to_docx(plan, paths[1], cdir))
                self.after(0, lambda: self._done(out))
            except Exception as exc:  # noqa: BLE001
                msg = f"No se pudo generar: {exc}"
                self.after(0, lambda: messagebox.showerror(APP_NAME, msg))

        threading.Thread(target=work, daemon=True).start()

    def _done(self, out):
        self.status.set("Generado: " + " · ".join(out))
        if messagebox.askyesno(APP_NAME, "Documentos generados:\n\n" + "\n".join(out) + "\n\n¿Abrir la carpeta?"):
            try:
                os.startfile(os.path.dirname(out[0]))  # type: ignore[attr-defined]
            except (AttributeError, OSError):
                pass

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
        p = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("Escenario", "*.json")])
        if p:
            save_scenario(sc, p)
            self.sc = sc

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


def main():
    App().mainloop()
    return 0
