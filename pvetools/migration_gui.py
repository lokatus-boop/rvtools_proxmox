"""Asistente de planificación de migración (solo lectura)."""
from __future__ import annotations

import os
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import APP_NAME
from .collector import Inventory
from .migrate import MigrationPlan

AUTO = "(automático)"


class MigrationDialog(tk.Toplevel):
    def __init__(self, app, src_inv):
        super().__init__(app)
        self.app, self.src = app, src_inv
        self.tgt = None
        self.msgs: queue.Queue = queue.Queue()
        self.title("Planificar migración a otro Proxmox")
        self.geometry("860x700")
        self.transient(app)
        self._build()
        self.after(150, self._poll)

    # ------------------------------------------------------------------ UI
    def _build(self):
        intro = ("El planificador lee el destino en modo solo lectura, comprueba cada VM/CT y genera un Excel con el plan "
                 "y los scripts de comandos (remote-migrate y backup/restauración) para que los revises y ejecutes tú. "
                 "No se ejecuta nada en ningún servidor.")
        ttk.Label(self, text=intro, wraplength=820, foreground="#444").pack(fill="x", padx=12, pady=(10, 6))

        f = ttk.LabelFrame(self, text="1. Proxmox de destino")
        f.pack(fill="x", padx=12, pady=4)
        self.v_host = tk.StringVar()
        self.v_user = tk.StringVar(value="root@pam")
        self.v_auth = tk.StringVar(value="password")
        self.v_tokid = tk.StringVar()
        self.v_secret = tk.StringVar()
        self.v_verify = tk.BooleanVar(value=False)
        ttk.Label(f, text="Host / IP[:puerto]").grid(row=0, column=0, sticky="w", padx=4, pady=2)
        ttk.Entry(f, textvariable=self.v_host, width=26).grid(row=0, column=1, sticky="we", padx=4)
        ttk.Label(f, text="Usuario").grid(row=0, column=2, sticky="w", padx=4)
        ttk.Entry(f, textvariable=self.v_user, width=20).grid(row=0, column=3, sticky="we", padx=4)
        ttk.Radiobutton(f, text="API token", value="token", variable=self.v_auth).grid(row=0, column=4, sticky="w")
        ttk.Radiobutton(f, text="Contraseña", value="password", variable=self.v_auth).grid(row=0, column=5, sticky="w")
        ttk.Label(f, text="Token ID").grid(row=1, column=0, sticky="w", padx=4, pady=2)
        ttk.Entry(f, textvariable=self.v_tokid, width=26).grid(row=1, column=1, sticky="we", padx=4)
        ttk.Label(f, text="Secreto / contraseña").grid(row=1, column=2, sticky="w", padx=4)
        ttk.Entry(f, textvariable=self.v_secret, show="•", width=20).grid(row=1, column=3, sticky="we", padx=4)
        ttk.Checkbutton(f, text="Verificar SSL", variable=self.v_verify).grid(row=1, column=4, columnspan=2, sticky="w")
        self.btn_conn = ttk.Button(f, text="Conectar y leer destino", command=self._connect)
        self.btn_conn.grid(row=2, column=0, columnspan=2, sticky="w", padx=4, pady=4)
        self.lbl_conn = ttk.Label(f, text="", foreground="#1F4E78")
        self.lbl_conn.grid(row=2, column=2, columnspan=4, sticky="w")
        for i in (1, 3):
            f.columnconfigure(i, weight=1)

        self.opts = ttk.LabelFrame(self, text="2. Opciones y mapeos")
        self.opts.pack(fill="both", expand=True, padx=12, pady=4)
        ttk.Label(self.opts, text="Conecta primero con el destino.", foreground="#777").pack(padx=8, pady=8)

        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=12, pady=(4, 12))
        self.btn_plan = ttk.Button(bar, text="3. Generar plan…", command=self._generate, state="disabled")
        self.btn_plan.pack(side="right")
        ttk.Button(bar, text="Cerrar", command=self.destroy).pack(side="right", padx=8)

    def _connect(self):
        host, user = self.v_host.get().strip(), self.v_user.get().strip()
        if not host or not user:
            messagebox.showwarning(APP_NAME, "Indica host y usuario del destino", parent=self)
            return
        conn = {"host": host, "user": user, "verify_ssl": self.v_verify.get()}
        if self.v_auth.get() == "token":
            conn.update(token_id=self.v_tokid.get().strip(), token_secret=self.v_secret.get().strip())
        else:
            conn["password"] = self.v_secret.get().strip("\r\n")
        self.btn_conn.configure(state="disabled")
        self.lbl_conn.configure(text="Leyendo el destino…")

        def work():
            try:
                inv = Inventory(progress=lambda m: self.msgs.put(("status", m)), query_agent=False)
                inv.collect([conn])
                err = next((s["Estado"] for s in inv.sheets["vSource"] if str(s.get("Estado", "")).startswith("ERROR")), None)
                self.msgs.put(("error", err) if err else ("done", inv))
            except Exception as e:  # noqa: BLE001
                self.msgs.put(("error", str(e)))

        threading.Thread(target=work, daemon=True).start()

    def _poll(self):
        try:
            while True:
                kind, payload = self.msgs.get_nowait()
                if kind == "status":
                    self.lbl_conn.configure(text=payload)
                elif kind == "error":
                    self.btn_conn.configure(state="normal")
                    self.lbl_conn.configure(text="")
                    messagebox.showerror(APP_NAME, payload, parent=self)
                elif kind == "done":
                    self.btn_conn.configure(state="normal")
                    self.tgt = payload
                    c = payload.sheets["vCluster"][0] if payload.sheets["vCluster"] else {}
                    self.lbl_conn.configure(text=f"Destino: {c.get('Clúster / nodo')} — {c.get('Nodos')} nodo(s), "
                                                 f"{c.get('VMs', 0)} VMs, {c.get('CTs', 0)} CTs")
                    self._build_options()
        except queue.Empty:
            pass
        if self.winfo_exists():
            self.after(150, self._poll)

    def _build_options(self):
        for w in self.opts.winfo_children():
            w.destroy()
        plan = MigrationPlan(self.src, self.tgt, self.v_host.get().strip())
        smap, bmap = plan.auto_maps()
        tst = sorted({s["Almacenamiento"] for s in plan.target_storages()
                      if "images" in str(s["Contenido"]) or "rootdir" in str(s["Contenido"])})
        tbr = sorted(plan.target_bridges())
        nodes = [AUTO] + [n["Nodo"] for n in plan.target_nodes()]

        top = ttk.Frame(self.opts)
        top.pack(fill="x", padx=6, pady=4)
        self.v_node = tk.StringVar(value=AUTO)
        self.v_vmids = tk.StringVar()
        self.v_keep = tk.BooleanVar(value=True)
        self.v_bw = tk.StringVar(value="1")
        self.v_tpl = tk.BooleanVar(value=True)
        self.v_stopped = tk.BooleanVar(value=True)
        ttk.Label(top, text="Nodo destino").grid(row=0, column=0, sticky="w", padx=4)
        ttk.Combobox(top, textvariable=self.v_node, values=nodes, state="readonly", width=18).grid(row=0, column=1, sticky="w")
        ttk.Label(top, text="VMIDs (vacío = todas; ej. 100,101,200-210)").grid(row=0, column=2, sticky="w", padx=(16, 4))
        ttk.Entry(top, textvariable=self.v_vmids, width=24).grid(row=0, column=3, sticky="w")
        ttk.Checkbutton(top, text="Mantener VMID si está libre", variable=self.v_keep).grid(row=1, column=0, columnspan=2, sticky="w", padx=4)
        ttk.Label(top, text="Ancho de banda (Gbit/s)").grid(row=1, column=2, sticky="w", padx=(16, 4))
        ttk.Entry(top, textvariable=self.v_bw, width=6).grid(row=1, column=3, sticky="w")
        ttk.Checkbutton(top, text="Incluir plantillas", variable=self.v_tpl).grid(row=2, column=0, columnspan=2, sticky="w", padx=4)
        ttk.Checkbutton(top, text="Incluir apagadas", variable=self.v_stopped).grid(row=2, column=2, columnspan=2, sticky="w", padx=(16, 4))

        maps = ttk.Frame(self.opts)
        maps.pack(fill="both", expand=True, padx=6, pady=4)
        sf = ttk.LabelFrame(maps, text="Almacenamiento origen → destino")
        sf.pack(side="left", fill="both", expand=True, padx=(0, 4))
        bf = ttk.LabelFrame(maps, text="Red (bridge / VNet) origen → destino")
        bf.pack(side="left", fill="both", expand=True, padx=(4, 0))
        self.smap_vars, self.bmap_vars = {}, {}
        for i, src in enumerate(plan.source_storages_used()):
            ttk.Label(sf, text=src).grid(row=i, column=0, sticky="w", padx=6, pady=2)
            v = tk.StringVar(value=smap.get(src, ""))
            ttk.Combobox(sf, textvariable=v, values=tst, width=20).grid(row=i, column=1, sticky="w", padx=6)
            self.smap_vars[src] = v
        for i, src in enumerate(plan.source_bridges_used()):
            ttk.Label(bf, text=src).grid(row=i, column=0, sticky="w", padx=6, pady=2)
            v = tk.StringVar(value=bmap.get(src, ""))
            ttk.Combobox(bf, textvariable=v, values=tbr, width=20).grid(row=i, column=1, sticky="w", padx=6)
            self.bmap_vars[src] = v
        self.btn_plan.configure(state="normal")

    def _parse_vmids(self):
        out = []
        for part in self.v_vmids.get().replace(" ", "").split(","):
            if not part:
                continue
            if "-" in part:
                a, b = part.split("-", 1)
                out += list(range(int(a), int(b) + 1))
            else:
                out.append(int(part))
        return out

    def _generate(self):
        try:
            vmids = self._parse_vmids()
            bw = float(self.v_bw.get().replace(",", "."))
        except ValueError:
            messagebox.showwarning(APP_NAME, "Revisa los VMIDs y el ancho de banda", parent=self)
            return
        opts = {
            "target_node": None if self.v_node.get() == AUTO else self.v_node.get(),
            "storage_map": {k: v.get() for k, v in self.smap_vars.items() if v.get()},
            "bridge_map": {k: v.get() for k, v in self.bmap_vars.items() if v.get()},
            "vmids": vmids, "keep_vmid": self.v_keep.get(), "bandwidth_gbps": bw,
            "include_templates": self.v_tpl.get(), "include_stopped": self.v_stopped.get(),
        }
        try:
            plan = MigrationPlan(self.src, self.tgt, self.v_host.get().strip(), opts).build()
        except ValueError as e:
            messagebox.showerror(APP_NAME, str(e), parent=self)
            return
        folder = filedialog.askdirectory(parent=self, title="Carpeta donde guardar el plan")
        if not folder:
            self.app.show_migration_plan(plan)
            return
        files = plan.write(folder)
        self.app.show_migration_plan(plan)
        s = plan.summary()
        msg = (f"Plan generado para {s['VMs/CTs en el plan']} VMs/CTs: {s['OK']} OK, {s['Con avisos']} con avisos, "
               f"{s['Bloqueadas']} bloqueadas.\n\nFicheros:\n" + "\n".join(os.path.basename(f) for f in files))
        if os.name == "nt" and messagebox.askyesno(APP_NAME, msg + "\n\n¿Abrir la carpeta?", parent=self):
            os.startfile(folder)  # noqa: S606
        elif os.name != "nt":
            messagebox.showinfo(APP_NAME, msg, parent=self)
