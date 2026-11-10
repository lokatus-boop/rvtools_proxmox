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
from .collector import SHEETS, Inventory
from .export import columns, to_csv, to_xlsx

CONFIG_DIR = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~/.config"), "PVEInventory")
CONFIG_FILE = os.path.join(CONFIG_DIR, "connections.json")


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_NAME} {__version__} — Inventario Proxmox VE")
        self.geometry("1280x780")
        self.minsize(900, 560)
        self.connections: list[dict] = []  # los secretos solo se guardan en memoria
        self.sheets: dict = {}
        self.msgs: queue.Queue = queue.Queue()
        self._build()
        self._load_saved()
        self.after(150, self._poll)

    # ------------------------------------------------------------------ UI
    def _build(self):
        style = ttk.Style(self)
        if "vista" in style.theme_names():
            style.theme_use("vista")

        top = ttk.LabelFrame(self, text="Conexión")
        top.pack(fill="x", padx=8, pady=(8, 4))

        self.v_host = tk.StringVar()
        self.v_user = tk.StringVar(value="root@pam")
        self.v_auth = tk.StringVar(value="token")
        self.v_tokid = tk.StringVar()
        self.v_secret = tk.StringVar()
        self.v_verify = tk.BooleanVar(value=False)
        self.v_agent = tk.BooleanVar(value=True)

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
        ttk.Entry(top, textvariable=self.v_secret, show="•", width=22).grid(row=r, column=3, sticky="we", padx=4)
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
        ttk.Label(btns, text="Un nodo por clúster es suficiente; añade cada nodo independiente por separado.",
                  foreground="#555").pack(side="right", padx=4)
        r += 1
        self.conn_list = ttk.Treeview(top, columns=("host", "user", "auth"), show="headings", height=3)
        for c, t, w in (("host", "Host", 260), ("user", "Usuario / token", 260), ("auth", "Autenticación", 140)):
            self.conn_list.heading(c, text=t)
            self.conn_list.column(c, width=w, anchor="w")
        self.conn_list.grid(row=r, column=0, columnspan=6, sticky="we", padx=4, pady=(0, 4))
        self.conn_list.bind("<<TreeviewSelect>>", self._select_conn)
        for i in (1, 3):
            top.columnconfigure(i, weight=1)

        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=8, pady=4)
        self.tabs = {}
        for name in SHEETS:
            frame = ttk.Frame(self.nb)
            self.nb.add(frame, text=name)
            bar = ttk.Frame(frame)
            bar.pack(fill="x")
            ttk.Label(bar, text="Filtro:").pack(side="left", padx=4, pady=2)
            fv = tk.StringVar()
            ent = ttk.Entry(bar, textvariable=fv, width=40)
            ent.pack(side="left")
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
            tree.tag_configure("CRÍTICO", background="#F8CBAD")
            tree.tag_configure("AVISO", background="#FFE699")
            tree.tag_configure("INFO", background="#DDEBF7")
            self.tabs[name] = {"tree": tree, "filter": fv, "count": count, "sort": (None, False)}
            fv.trace_add("write", lambda *_a, n=name: self._fill(n))

        self.status = tk.StringVar(value="Añade una conexión y pulsa Inventariar.")
        ttk.Label(self, textvariable=self.status, relief="sunken", anchor="w").pack(fill="x", side="bottom")
        self._auth_changed()

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
            c["password"] = self.v_secret.get()
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
                sheets = Inventory(progress=lambda m: self.msgs.put(("status", m)), query_agent=agent).collect(conns)
                self.msgs.put(("done", sheets))
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
                    self.sheets = payload
                    for n in SHEETS:
                        self._fill(n)
                    errs = [s for s in payload["vSource"] if str(s.get("Estado", "")).startswith("ERROR")]
                    vms = len(payload["vInfo"])
                    self.status.set(f"Inventario completado: {vms} VMs/CTs, {len(payload['vHost'])} nodos"
                                    + (f" — {len(errs)} conexión(es) con error (ver vSource)" if errs else ""))
                    self.btn_run.configure(state="normal")
                    if errs:
                        self.nb.select(SHEETS.index("vSource"))
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
        rows = self.sheets.get(name, [])
        cols = columns(rows)
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
            tree.insert("", "end", values=vals, tags=(r.get("Severidad", ""),))
            shown += 1
        t["count"].configure(text=f"{shown} de {len(self.sheets.get(name, []))} filas")

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

    def _export_xlsx(self):
        if not self._need_data():
            return
        default = f"pve_inventory_{dt.datetime.now():%Y%m%d_%H%M%S}.xlsx"
        p = filedialog.asksaveasfilename(defaultextension=".xlsx", initialfile=default,
                                         filetypes=[("Excel", "*.xlsx")])
        if p:
            to_xlsx(self.sheets, p)
            self.status.set(f"Excel guardado en {p}")
            if os.name == "nt" and messagebox.askyesno(APP_NAME, "Excel guardado. ¿Abrirlo ahora?"):
                os.startfile(p)  # noqa: S606

    def _export_csv(self):
        if not self._need_data():
            return
        d = filedialog.askdirectory()
        if d:
            to_csv(self.sheets, d)
            self.status.set(f"CSV guardados en {d}")


def _sort_key(v):
    if isinstance(v, (int, float)):
        return (0, v, "")
    return (1, 0, str(v).lower())


def main():
    App().mainloop()
