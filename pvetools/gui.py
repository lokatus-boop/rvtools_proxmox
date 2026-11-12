"""Interfaz gráfica (tkinter, incluida en Python: no requiere dependencias extra)."""
from __future__ import annotations

import datetime as dt
import json
import os
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import APP_NAME, __version__
from .branding import COMPANY, DISCLAIMER, DISCLAIMER_TITLE, DISCLAIMER_VERSION, SHORT_NOTICE, asset_path
from .collector import SHEET_GROUPS, SHEETS, Inventory
from .anonymize import Anonymizer, default_map_path, reverse_file
from .export import columns, to_csv, to_xlsx

CONFIG_DIR = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~/.config"), "PVEInventory")
CONFIG_FILE = os.path.join(CONFIG_DIR, "connections.json")
SETTINGS_FILE = os.path.join(CONFIG_DIR, "settings.json")


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_NAME} {__version__} — Inventario Proxmox VE · {COMPANY}")
        self.geometry("1280x820")
        self.minsize(900, 560)
        self.connections: list[dict] = []  # los secretos solo se guardan en memoria
        self.sheets: dict = {}
        self.inv = None
        self.msgs: queue.Queue = queue.Queue()
        self._build()
        self._load_saved()
        self.after(150, self._poll)
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

        header = tk.Frame(self, bg="white", highlightthickness=1, highlightbackground="#d0d0d0")
        header.pack(fill="x")
        try:
            self._images["logo"] = tk.PhotoImage(file=asset_path("fsas_logo_small.png"))
            tk.Label(header, image=self._images["logo"], bg="white").pack(side="left", padx=12, pady=6)
        except tk.TclError:
            tk.Label(header, text=COMPANY, bg="white", font=("Segoe UI", 16, "bold")).pack(side="left", padx=12, pady=6)
        titles = tk.Frame(header, bg="white")
        titles.pack(side="left", padx=10)
        tk.Label(titles, text=f"{APP_NAME} — Inventario de Proxmox VE", bg="white",
                 font=("Segoe UI", 13, "bold"), fg="#1F4E78").pack(anchor="w")
        tk.Label(titles, text=SHORT_NOTICE, bg="white", fg="#555", font=("Segoe UI", 9)).pack(anchor="w")
        tk.Button(header, text="Aviso de uso", relief="flat", bg="white", fg="#1F4E78", cursor="hand2",
                  font=("Segoe UI", 9, "underline"), command=self._show_notice).pack(side="right", padx=12)

        top = ttk.LabelFrame(self, text="Conexión")
        top.pack(fill="x", padx=8, pady=(8, 4))

        self.v_host = tk.StringVar()
        self.v_user = tk.StringVar(value="root@pam")
        self.v_auth = tk.StringVar(value="token")
        self.v_tokid = tk.StringVar()
        self.v_secret = tk.StringVar()
        self.v_verify = tk.BooleanVar(value=False)
        self.v_agent = tk.BooleanVar(value=True)
        self.v_anon = tk.BooleanVar(value=False)
        self.v_keepip = tk.BooleanVar(value=False)

        r = 0
        ttk.Label(top, text="Host / IP[:puerto]").grid(row=r, column=0, sticky="w", padx=4, pady=2)
        ttk.Entry(top, textvariable=self.v_host, width=28).grid(row=r, column=1, sticky="we", padx=4)
        ttk.Label(top, text="Usuario (user@realm)").grid(row=r, column=2, sticky="w", padx=4)
        ttk.Entry(top, textvariable=self.v_user, width=22).grid(row=r, column=3, sticky="we", padx=4)
        auth = ttk.Frame(top)
        auth.grid(row=r, column=4, columnspan=2, sticky="w", padx=4)
        ttk.Radiobutton(auth, text="API token", value="token", variable=self.v_auth, command=self._auth_changed).pack(side="left")
        ttk.Radiobutton(auth, text="Contraseña", value="password", variable=self.v_auth, command=self._auth_changed).pack(side="left", padx=6)
        r += 1
        self.lbl_tokid = ttk.Label(top, text="Token ID")
        self.lbl_tokid.grid(row=r, column=0, sticky="w", padx=4, pady=2)
        self.ent_tokid = ttk.Entry(top, textvariable=self.v_tokid, width=28)
        self.ent_tokid.grid(row=r, column=1, sticky="we", padx=4)
        self.lbl_secret = ttk.Label(top, text="Secreto del token")
        self.lbl_secret.grid(row=r, column=2, sticky="w", padx=4)
        sec = ttk.Frame(top)
        sec.grid(row=r, column=3, sticky="we", padx=4)
        self.ent_secret = ttk.Entry(sec, textvariable=self.v_secret, show="•", width=22)
        self.ent_secret.pack(side="left", fill="x", expand=True)
        self.v_show = tk.BooleanVar(value=False)
        ttk.Checkbutton(sec, text="Mostrar", variable=self.v_show,
                        command=lambda: self.ent_secret.configure(show="" if self.v_show.get() else "•")).pack(side="left", padx=(4, 0))
        ttk.Checkbutton(top, text="Verificar certificado SSL", variable=self.v_verify).grid(row=r, column=4, sticky="w", padx=4)
        ttk.Checkbutton(top, text="Consultar guest agent (IPs, SO)", variable=self.v_agent).grid(row=r, column=5, sticky="w", padx=4)
        r += 1
        btns = ttk.Frame(top)
        btns.grid(row=r, column=0, columnspan=6, sticky="we", pady=4)
        ttk.Button(btns, text="Añadir a la lista", command=self._add_conn).pack(side="left", padx=4)
        ttk.Button(btns, text="Quitar seleccionada", command=self._del_conn).pack(side="left", padx=4)
        self.btn_run = ttk.Button(btns, text="▶ Inventariar", command=self._run)
        self.btn_run.pack(side="left", padx=16)
        ttk.Button(btns, text="Exportar Excel…", command=self._export_xlsx).pack(side="left", padx=4)
        ttk.Button(btns, text="Exportar CSV…", command=self._export_csv).pack(side="left", padx=4)
        ttk.Label(btns, text="Un nodo por clúster basta; los nodos sueltos, uno a uno.",
                  foreground="#555").pack(side="right", padx=4)
        r += 1
        anon = ttk.Frame(top)
        anon.grid(row=r, column=0, columnspan=6, sticky="we", pady=(0, 4))
        ttk.Checkbutton(anon, text="Anonimizar al exportar (nombres → seudónimos, IPs/MACs transformadas)",
                        variable=self.v_anon, command=self._anon_changed).pack(side="left", padx=4)
        self.chk_keepip = ttk.Checkbutton(anon, text="Conservar IPs", variable=self.v_keepip)
        self.chk_keepip.pack(side="left", padx=8)
        ttk.Button(anon, text="¿Qué se anonimiza?", command=self._anon_help).pack(side="left", padx=4)
        ttk.Button(anon, text="Revertir anonimización…", command=self._revert).pack(side="left", padx=4)
        self._anon_changed()
        r += 1
        self.conn_list = ttk.Treeview(top, columns=("host", "user", "auth"), show="headings", height=3)
        for c, t, w in (("host", "Host", 260), ("user", "Usuario / token", 260), ("auth", "Autenticación", 140)):
            self.conn_list.heading(c, text=t)
            self.conn_list.column(c, width=w, anchor="w")
        self.conn_list.grid(row=r, column=0, columnspan=6, sticky="we", padx=4, pady=(0, 4))
        self.conn_list.bind("<<TreeviewSelect>>", self._select_conn)
        for i in (1, 3):
            top.columnconfigure(i, weight=1)

        paned = ttk.PanedWindow(self, orient="horizontal")
        paned.pack(fill="both", expand=True, padx=8, pady=4)
        navf = ttk.Frame(paned)
        self.nav = ttk.Treeview(navf, show="tree", selectmode="browse")
        self.nav.column("#0", width=210)
        nys = ttk.Scrollbar(navf, orient="vertical", command=self.nav.yview)
        self.nav.configure(yscrollcommand=nys.set)
        self.nav.pack(side="left", fill="both", expand=True)
        nys.pack(side="right", fill="y")
        self.nav.bind("<<TreeviewSelect>>", self._nav_select)
        self.content = ttk.Frame(paned)
        self.content.rowconfigure(0, weight=1)
        self.content.columnconfigure(0, weight=1)
        paned.add(navf, weight=0)
        paned.add(self.content, weight=1)
        self.tabs = {}
        for group, names in SHEET_GROUPS:
            gid = self.nav.insert("", "end", text=group, open=True)
            for name in names:
                self._make_sheet(name, gid)
        self._show_sheet("vInfo")

        self.status = tk.StringVar(value="Añade una conexión y pulsa Inventariar.")
        ttk.Label(self, textvariable=self.status, relief="sunken", anchor="w").pack(fill="x", side="bottom")
        self._auth_changed()

    # ------------------------------------------------------------------ hojas
    def _make_sheet(self, name, parent_id, data_key=None):
        frame = ttk.Frame(self.content)
        frame.grid(row=0, column=0, sticky="nsew")
        bar = ttk.Frame(frame)
        bar.pack(fill="x")
        title = ttk.Label(bar, text=name, font=("Segoe UI", 11, "bold"))
        title.pack(side="left", padx=(4, 12), pady=2)
        ttk.Label(bar, text="Filtro:").pack(side="left", padx=4, pady=2)
        fv = tk.StringVar()
        ttk.Entry(bar, textvariable=fv, width=40).pack(side="left")
        count = ttk.Label(bar, text="")
        count.pack(side="left", padx=10)
        holder = ttk.Frame(frame)
        holder.pack(fill="both", expand=True)
        tree = ttk.Treeview(holder, show="headings")
        ys = ttk.Scrollbar(holder, orient="vertical", command=tree.yview)
        xs = ttk.Scrollbar(holder, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)
        tree.grid(row=0, column=0, sticky="nsew")
        ys.grid(row=0, column=1, sticky="ns")
        xs.grid(row=1, column=0, sticky="we")
        holder.rowconfigure(0, weight=1)
        holder.columnconfigure(0, weight=1)
        for tag, color in (("CRÍTICO", "#F8CBAD"), ("BLOQUEO", "#F8CBAD"), ("BLOQUEADA", "#F8CBAD"), ("NO CABE", "#F8CBAD"),
                           ("AVISO", "#FFE699"), ("Con avisos", "#FFE699"), ("INFO", "#DDEBF7"), ("OK", "#E2EFDA")):
            tree.tag_configure(tag, background=color)
        nav_id = self.nav.insert(parent_id, "end", text=name, values=(name,))
        self.tabs[name] = {"tree": tree, "filter": fv, "count": count, "sort": (None, False), "frame": frame,
                           "nav": nav_id, "key": data_key or name}
        fv.trace_add("write", lambda *_a, n=name: self._fill(n))

    def _show_sheet(self, name):
        t = self.tabs.get(name)
        if not t:
            return
        t["frame"].tkraise()
        if self.nav.selection() != (t["nav"],):
            self.nav.selection_set(t["nav"])
            self.nav.see(t["nav"])

    def _nav_select(self, _e=None):
        sel = self.nav.selection()
        if sel:
            vals = self.nav.item(sel[0], "values")
            if vals:
                self._show_sheet(vals[0])

    def _update_nav_counts(self):
        for name, t in self.tabs.items():
            n = len(self.sheets.get(t["key"], []))
            self.nav.item(t["nav"], text=f"{name} ({n})" if n else name)

    # ------------------------------------------------------------------ aviso
    def _show_notice(self, first_run: bool = False):
        win = tk.Toplevel(self)
        win.title(DISCLAIMER_TITLE)
        win.transient(self)
        win.resizable(False, False)
        win.configure(bg="white")
        if "logo" in self._images:
            tk.Label(win, image=self._images["logo"], bg="white").pack(anchor="w", padx=16, pady=(14, 4))
        msg = tk.Message(win, text=DISCLAIMER, width=560, bg="white", font=("Segoe UI", 10))
        msg.pack(padx=16, pady=8)
        bar = tk.Frame(win, bg="white")
        bar.pack(fill="x", padx=16, pady=(0, 14))
        result = {"ok": not first_run}

        def accept():
            result["ok"] = True
            win.destroy()

        if first_run:
            ttk.Button(bar, text="Acepto", command=accept).pack(side="right")
            ttk.Button(bar, text="Salir", command=win.destroy).pack(side="right", padx=8)
            win.protocol("WM_DELETE_WINDOW", win.destroy)
        else:
            ttk.Button(bar, text="Cerrar", command=win.destroy).pack(side="right")
        win.update_idletasks()
        x = self.winfo_rootx() + (self.winfo_width() - win.winfo_width()) // 2
        y = self.winfo_rooty() + 60
        win.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        win.grab_set()
        self.wait_window(win)
        return result["ok"]

    def _first_run_notice(self):
        settings = self._read_settings()
        if settings.get("disclaimer_accepted") == DISCLAIMER_VERSION:
            return
        if not self._show_notice(first_run=True):
            self.destroy()
            return
        settings["disclaimer_accepted"] = DISCLAIMER_VERSION
        self._write_settings(settings)

    def _read_settings(self) -> dict:
        try:
            with open(SETTINGS_FILE, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def _write_settings(self, data: dict):
        try:
            os.makedirs(CONFIG_DIR, exist_ok=True)
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except OSError:
            pass

    def _auth_changed(self):
        tok = self.v_auth.get() == "token"
        self.lbl_secret.configure(text="Secreto del token" if tok else "Contraseña")
        self.ent_tokid.configure(state="normal" if tok else "disabled")

    # ------------------------------------------------------------------ conexiones
    def _current(self) -> dict | None:
        host, user = self.v_host.get().strip(), self.v_user.get().strip()
        if not host or not user:
            messagebox.showwarning(APP_NAME, "Indica host y usuario")
            return None
        c = {"host": host, "user": user, "verify_ssl": self.v_verify.get()}
        if self.v_auth.get() == "token":
            c["token_id"] = self.v_tokid.get().strip()
            c["token_secret"] = self.v_secret.get().strip()
        else:
            c["password"] = self.v_secret.get().strip("\r\n")
        return c

    def _add_conn(self):
        c = self._current()
        if not c:
            return
        self.connections = [x for x in self.connections if x["host"] != c["host"]] + [c]
        self._refresh_conns()
        self._save()
        self.v_host.set("")

    def _del_conn(self):
        sel = self.conn_list.selection()
        if sel:
            host = self.conn_list.item(sel[0], "values")[0]
            self.connections = [x for x in self.connections if x["host"] != host]
            self._refresh_conns()
            self._save()

    def _select_conn(self, _e=None):
        sel = self.conn_list.selection()
        if not sel:
            return
        host = self.conn_list.item(sel[0], "values")[0]
        c = next((x for x in self.connections if x["host"] == host), None)
        if c:
            self.v_host.set(c["host"])
            self.v_user.set(c["user"])
            self.v_auth.set("token" if c.get("token_id") else "password")
            self.v_tokid.set(c.get("token_id", ""))
            self.v_secret.set(c.get("token_secret") or c.get("password") or "")
            self.v_verify.set(c.get("verify_ssl", False))
            self._auth_changed()

    def _refresh_conns(self):
        self.conn_list.delete(*self.conn_list.get_children())
        for c in self.connections:
            who = f"{c['user']}!{c['token_id']}" if c.get("token_id") else c["user"]
            has = bool(c.get("token_secret") or c.get("password"))
            auth = ("API token" if c.get("token_id") else "Contraseña") + ("" if has else " (falta secreto)")
            self.conn_list.insert("", "end", values=(c["host"], who, auth))

    def _save(self):
        try:
            os.makedirs(CONFIG_DIR, exist_ok=True)
            safe = [{k: v for k, v in c.items() if k not in ("password", "token_secret")} for c in self.connections]
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(safe, f, indent=2)
        except OSError:
            pass

    def _load_saved(self):
        try:
            with open(CONFIG_FILE, encoding="utf-8") as f:
                self.connections = json.load(f)
            self._refresh_conns()
        except (OSError, ValueError):
            pass

    # ------------------------------------------------------------------ inventario
    def _run(self):
        conns = list(self.connections)
        if not conns:
            c = self._current()
            if not c:
                return
            conns = [c]
        missing = [c["host"] for c in conns if not (c.get("token_secret") or c.get("password"))]
        if missing:
            messagebox.showwarning(APP_NAME, "Falta el secreto/contraseña de: " + ", ".join(missing) +
                                   "\nSelecciónala en la lista, escríbelo y pulsa 'Añadir a la lista'.")
            return
        self.btn_run.configure(state="disabled")
        agent = self.v_agent.get()

        def worker():
            try:
                inv = Inventory(progress=lambda m: self.msgs.put(("status", m)), query_agent=agent)
                inv.collect(conns)
                self.msgs.put(("done", (inv, inv.sheets)))
            except Exception as e:  # noqa: BLE001
                self.msgs.put(("error", str(e)))

        threading.Thread(target=worker, daemon=True).start()

    def _poll(self):
        try:
            while True:
                kind, payload = self.msgs.get_nowait()
                if kind == "status":
                    self.status.set(payload)
                elif kind == "done":
                    self.inv, self.sheets = payload
                    for n in SHEETS:
                        self._fill(n)
                    self._update_nav_counts()
                    payload = self.sheets
                    errs = [s for s in payload["vSource"] if str(s.get("Estado", "")).startswith("ERROR")]
                    vms = len(payload["vInfo"])
                    self.status.set(f"Inventario completado: {vms} VMs/CTs, {len(payload['vHost'])} nodos"
                                    + (f" — {len(errs)} conexión(es) con error (ver vSource)" if errs else ""))
                    self.btn_run.configure(state="normal")
                    if errs:
                        self._show_sheet("vSource")
                elif kind == "error":
                    self.status.set("Error: " + payload)
                    messagebox.showerror(APP_NAME, payload)
                    self.btn_run.configure(state="normal")
        except queue.Empty:
            pass
        self.after(150, self._poll)

    # ------------------------------------------------------------------ tablas
    def _fill(self, name):
        t = self.tabs[name]
        tree = t["tree"]
        rows = self.sheets.get(t["key"], [])
        cols = columns(rows, t["key"])
        tree.delete(*tree.get_children())
        tree["columns"] = cols
        for c in cols:
            tree.heading(c, text=c, command=lambda c=c, n=name: self._sort(n, c))
            w = max([len(c)] + [len(str(r.get(c) or "")) for r in rows[:200]]) * 7 + 16
            tree.column(c, width=min(max(w, 60), 380), anchor="w", stretch=False)
        f = t["filter"].get().strip().lower()
        col, rev = t["sort"]
        if col in cols:
            rows = sorted(rows, key=lambda r: (r.get(col) is None, _sort_key(r.get(col))), reverse=rev)
        shown = 0
        for r in rows:
            vals = ["" if r.get(c) is None else r.get(c) for c in cols]
            if f and f not in " ".join(str(v) for v in vals).lower():
                continue
            tree.insert("", "end", values=vals, tags=(str(r.get("Severidad") or r.get("Resultado") or ""),))
            shown += 1
        t["count"].configure(text=f"{shown} de {len(self.sheets.get(t['key'], []))} filas")

    def _sort(self, name, col):
        prev, rev = self.tabs[name]["sort"]
        self.tabs[name]["sort"] = (col, not rev if prev == col else False)
        self._fill(name)

    # ------------------------------------------------------------------ exportar
    def _need_data(self):
        if not self.sheets:
            messagebox.showinfo(APP_NAME, "Primero lanza un inventario.")
            return False
        return True

    def _anon_changed(self):
        self.chk_keepip.configure(state="normal" if self.v_anon.get() else "disabled")

    def _anon_help(self):
        messagebox.showinfo(APP_NAME, ANON_HELP)

    def _export_sheets(self, target: str):
        """Hojas a exportar: las reales o, si se pidió, las anonimizadas (y guarda la correspondencia)."""
        if not self.v_anon.get():
            return self.sheets, None
        map_path = default_map_path(target)
        anon = Anonymizer.load(map_path, keep_ips=self.v_keepip.get()) if os.path.exists(map_path) \
            else Anonymizer(keep_ips=self.v_keepip.get())
        sheets = anon.anonymize(self.sheets)
        anon.save(map_path)
        return sheets, map_path

    def _anon_done(self, what: str, map_path: str):
        messagebox.showinfo(APP_NAME, f"{what} anonimizado guardado.\n\nLa correspondencia con los datos reales está en:\n"
                                      f"{map_path}\n\nEse fichero es CONFIDENCIAL: guárdalo y NO lo envíes junto al "
                                      "inventario. Sirve para revertir los seudónimos (botón «Revertir anonimización…»).")

    def _export_xlsx(self):
        if not self._need_data():
            return
        suffix = "_anonimo" if self.v_anon.get() else ""
        default = f"pve_inventory_{dt.datetime.now():%Y%m%d_%H%M%S}{suffix}.xlsx"
        p = filedialog.asksaveasfilename(defaultextension=".xlsx", initialfile=default,
                                         filetypes=[("Excel", "*.xlsx")])
        if p:
            sheets, map_path = self._export_sheets(p)
            to_xlsx(sheets, p)
            self.status.set(f"Excel{' anonimizado' if map_path else ''} guardado en {p}")
            if map_path:
                self._anon_done("Excel", map_path)
            if os.name == "nt" and messagebox.askyesno(APP_NAME, "Excel guardado. ¿Abrirlo ahora?"):
                os.startfile(p)  # noqa: S606

    def _export_csv(self):
        if not self._need_data():
            return
        d = filedialog.askdirectory()
        if d:
            sheets, map_path = self._export_sheets(d)
            to_csv(sheets, d)
            self.status.set(f"CSV{' anonimizados' if map_path else ''} guardados en {d}")
            if map_path:
                self._anon_done("CSV", map_path)

    def _revert(self):
        files = filedialog.askopenfilenames(title="Excel/CSV anonimizado (inventario o plan) a revertir",
                                            filetypes=[("Excel o CSV", "*.xlsx *.csv"), ("Todos", "*.*")])
        if not files:
            return
        m = filedialog.askopenfilename(title="Fichero de correspondencia (…_correspondencia_CONFIDENCIAL.xlsx)",
                                       filetypes=[("Excel", "*.xlsx")])
        if not m:
            return
        try:
            out = [reverse_file(f, m) for f in files]
        except Exception as e:  # noqa: BLE001
            messagebox.showerror(APP_NAME, f"No se pudo revertir: {e}")
            return
        self.status.set(f"Revertido: {', '.join(out)}")
        messagebox.showinfo(APP_NAME, "Ficheros con los nombres reales:\n\n" + "\n".join(out) +
                            "\n\nLos comentarios y descripciones que se vaciaron al anonimizar no se pueden recuperar.")


ANON_HELP = (
    "Al exportar con «Anonimizar», el Excel/CSV no contiene datos identificativos del cliente:\n\n"
    "• Nombres de clústeres, nodos, VMs/CTs, hostnames, dominios, almacenamientos, pools, etiquetas, usuarios, "
    "grupos, zonas/VNets/controladores/IPAM/DNS de SDN, objetos de firewall, snapshots, ISOs y nº de serie → seudónimos (CLUSTER-01, "
    "NODO-01, VM-0001, STORAGE-01…). El mismo valor recibe siempre el mismo seudónimo en todas las hojas.\n"
    "• IPs: se transforman conservando la estructura de red (subredes, gateways .1). MACs: se conserva el fabricante.\n"
    "• Descripciones, comentarios, emails, alias SDN y huellas de certificados: se vacían.\n\n"
    "Se conservan CPU, RAM, discos, tamaños, tipos de almacenamiento, SO, estados, versiones, VLANs, bridges "
    "(vmbrN), los nombres por defecto de Proxmox (local, local-lvm, root@pam…) y las relaciones VM-nodo-red-"
    "almacenamiento, de modo que el inventario anonimizado sirve igual para planificar la migración.\n\n"
    "La correspondencia real ↔ seudónimo se guarda en un fichero aparte («…_correspondencia_CONFIDENCIAL.xlsx») "
    "que se queda el cliente. Si exportas de nuevo con el mismo nombre, se reutiliza y los seudónimos no cambian."
)


def _sort_key(v):
    if isinstance(v, (int, float)):
        return (0, v, "")
    return (1, 0, str(v).lower())


def main():
    App().mainloop()
