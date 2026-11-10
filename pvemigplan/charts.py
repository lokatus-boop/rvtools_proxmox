"""Gráficos (PNG) para la documentación del cliente."""
from __future__ import annotations

import os
import textwrap

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyBboxPatch  # noqa: E402

# Paleta categórica validada (orden fijo) y colores de estado
C1, C2, C3 = "#2a78d6", "#eb6834", "#1baf7a"
SEQ_LIGHT, SEQ_MID, SEQ_DARK = "#b7d3f6", "#5598e7", "#184f95"
GOOD, WARN, SERIOUS, CRIT = "#0ca30c", "#fab219", "#ec835a", "#d03b3b"
NEUTRAL = "#d9d8d4"
INK, INK2, GRID = "#0b0b0b", "#52514e", "#e6e5e1"
SURFACE = "#fcfcfb"
BRAND = "#1F4E78"

plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 9, "axes.edgecolor": GRID, "axes.labelcolor": INK2,
    "xtick.color": INK2, "ytick.color": INK2, "axes.titlesize": 11, "axes.titleweight": "bold",
    "axes.titlecolor": INK, "axes.spines.top": False, "axes.spines.right": False, "figure.facecolor": SURFACE,
    "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE, "axes.grid": True, "grid.color": GRID,
    "grid.linewidth": 0.6, "axes.axisbelow": True, "legend.frameon": False,
})


def _save(fig, folder, name):
    p = os.path.join(folder, name)
    fig.savefig(p, dpi=170, bbox_inches="tight")
    plt.close(fig)
    return p


def _hbar_labels(ax, bars, fmt="{:.0f}", pad=0.01):
    xmax = ax.get_xlim()[1]
    for b in bars:
        w = b.get_width()
        if w:
            ax.text(w + xmax * pad, b.get_y() + b.get_height() / 2, fmt.format(w), va="center", fontsize=8, color=INK2)


# ------------------------------------------------------------------ situación actual
def source_hosts(plan, folder):
    hs = plan.an.hosts
    if not hs:
        return None
    by_node = {}
    for g in plan.an.guests:
        if g.running:
            d = by_node.setdefault((g.cluster, g.node), [0.0, 0.0])
            d[0] += g.vcpu
            d[1] += g.ram_gib
    labels = [h.node if len(plan.an.clusters) == 1 else f"{h.node}\n{h.cluster.replace(' (standalone)', '')[:18]}" for h in hs]
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(9, max(2.2, 0.45 * len(hs) + 1.2)))
    y = range(len(hs))
    h = 0.36
    a1.barh([i - h / 2 for i in y], [x.threads for x in hs], height=h, color=SEQ_LIGHT, label="Hilos físicos")
    b = a1.barh([i + h / 2 for i in y], [by_node.get((x.cluster, x.node), [0, 0])[0] for x in hs], height=h, color=C1, label="vCPU asignadas (encendidas)")
    a1.set_yticks(list(y), labels)
    a1.invert_yaxis()
    a1.set_title("CPU por nodo de origen")
    _hbar_labels(a1, b)
    a1.legend(loc="upper center", bbox_to_anchor=(0.5, -0.12), ncol=2, fontsize=8)
    a2.barh([i - h / 2 for i in y], [x.ram_gib for x in hs], height=h, color=SEQ_LIGHT, label="RAM física (GiB)")
    b = a2.barh([i + h / 2 for i in y], [x.ram_used_gib for x in hs], height=h, color=C1, label="RAM usada (GiB)")
    a2.set_yticks(list(y), [""] * len(hs))
    a2.invert_yaxis()
    a2.set_title("Memoria por nodo de origen")
    _hbar_labels(a2, b)
    a2.legend(loc="upper center", bbox_to_anchor=(0.5, -0.12), ncol=2, fontsize=8)
    fig.tight_layout()
    return _save(fig, folder, "origen_nodos.png")


def os_distribution(plan, folder):
    c = plan.an.os_detail().most_common()
    if not c:
        return None
    if len(c) > 9:
        c = c[:8] + [("Otros", sum(v for _, v in c[8:]))]
    fig, ax = plt.subplots(figsize=(6.2, 0.36 * len(c) + 0.9))
    bars = ax.barh([k for k, _ in c], [v for _, v in c], color=C1, height=0.6)
    ax.invert_yaxis()
    ax.set_title("VMs/CTs por sistema operativo")
    ax.grid(axis="y", visible=False)
    ax.set_xlim(0, max(v for _, v in c) * 1.15)
    _hbar_labels(ax, bars)
    return _save(fig, folder, "origen_so.png")


def vm_sizes(plan, folder):
    b = plan.an.size_buckets()
    fig, ax = plt.subplots(figsize=(5.2, 2.6))
    bars = ax.bar(list(b), list(b.values()), color=C1, width=0.6)
    ax.set_title("Tamaño de las VMs (vCPU)")
    ax.grid(axis="x", visible=False)
    for r in bars:
        if r.get_height():
            ax.text(r.get_x() + r.get_width() / 2, r.get_height(), f"{r.get_height():.0f}", ha="center", va="bottom", fontsize=8, color=INK2)
    return _save(fig, folder, "origen_tamanos.png")


def source_storage(plan, folder):
    rows = [r for r in plan.an.storage_usage() if r["Total (GiB)"]]
    rows.sort(key=lambda r: r["Total (GiB)"], reverse=True)
    rows = rows[:14]
    if not rows:
        return None
    labels = [f"{r['Almacenamiento']} ({r['Tipo']})" + ("" if r["Nodo"] == "(compartido)" else f" · {r['Nodo']}") for r in rows]
    used = [r["Usado (GiB)"] / 1024 for r in rows]
    free = [max(r["Total (GiB)"] - r["Usado (GiB)"], 0) / 1024 for r in rows]
    fig, ax = plt.subplots(figsize=(7.5, 0.38 * len(rows) + 1.0))
    ax.barh(labels, used, color=C1, height=0.6, label="Usado")
    ax.barh(labels, free, left=used, color=SEQ_LIGHT, height=0.6, label="Libre", edgecolor=SURFACE, linewidth=1.5)
    for i, r in enumerate(rows):
        ax.text(used[i] + free[i], i, f"  {r['Uso (%)']:.0f} %", va="center", fontsize=8, color=INK2)
    ax.invert_yaxis()
    ax.set_xlabel("TiB")
    ax.set_title("Almacenamientos de origen")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.3), ncol=3, fontsize=8)
    ax.grid(axis="y", visible=False)
    return _save(fig, folder, "origen_almacenamiento.png")


# ------------------------------------------------------------------ destino
def capacity(plan, folder):
    e = plan.eval
    cap = plan.sc["capacidad"]
    spare = cap["n_mas"]
    labels = ["CPU", "RAM", "Almacenamiento"]
    normal = [e["cpu_pct"], e["ram_pct"], e["alm_pct_real"]]
    n1 = [e["cpu_pct_n1"], e["ram_pct_n1"], e["alm_pct_real"]]
    limits = [cap["cpu_max_pct"], cap["ram_max_pct"], plan.sc["almacenamiento"]["llenado_max_pct"]]
    fig, ax = plt.subplots(figsize=(7, 2.6))
    y = range(3)
    h = 0.34
    ax.barh([i - h / 2 for i in y], normal, height=h, color=C1, label="Todos los nodos")
    ax.barh([i + h / 2 for i in y], n1, height=h, color=C2, label=f"Con {spare} nodo(s) caído(s)")
    for i in y:
        ax.text(normal[i] + 1, i - h / 2, f"{normal[i]:.0f} %", va="center", fontsize=8, color=INK2)
        ax.text(n1[i] + 1, i + h / 2, f"{n1[i]:.0f} %", va="center", fontsize=8, color=INK2)
        ax.plot([100, 100], [i - 0.45, i + 0.45], color=CRIT, lw=1.2)
        ax.plot([limits[i], limits[i]], [i - 0.45, i + 0.45], color=INK2, lw=1, ls="--")
    ax.set_yticks(list(y), labels)
    ax.invert_yaxis()
    ax.set_xlim(0, max(110, max(n1) * 1.15))
    ax.set_xlabel("% de ocupación prevista (con crecimiento) · línea discontinua = objetivo · roja = 100 %")
    ax.set_title("Ocupación del nuevo entorno")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.32), ncol=2, fontsize=8)
    ax.grid(axis="y", visible=False)
    return _save(fig, folder, "destino_capacidad.png")


def node_distribution(plan, folder):
    ns = plan.nodes
    if not ns:
        return None
    fig, ax = plt.subplots(figsize=(7, max(2.0, 0.4 * len(ns) + 1)))
    names = [n["name"] for n in ns]
    used = [n["ram"] for n in ns]
    free = [max(n["ram_usable"] - n["ram"], 0) for n in ns]
    ax.barh(names, used, color=C1, height=0.6, label="RAM asignada a VMs (GiB)")
    ax.barh(names, free, left=used, color=SEQ_LIGHT, height=0.6, label="RAM disponible (GiB)", edgecolor=SURFACE, linewidth=1.5)
    for i, n in enumerate(ns):
        ax.text(used[i] + free[i], i, f"  {len(n['guests'])} VMs · {n['vcpu']:.0f} vCPU", va="center", fontsize=8, color=INK2)
    ax.invert_yaxis()
    ax.set_title("Reparto inicial de VMs por nodo de destino")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.18), ncol=3, fontsize=8)
    ax.grid(axis="y", visible=False)
    ax.set_xlim(0, max(u + f for u, f in zip(used, free)) * 1.3)
    return _save(fig, folder, "destino_reparto.png")


def options_compare(plan, folder):
    if not plan.options:
        return None
    labels = [f"Opción {i + 1}\n{o['nodos'][0].count}× {o['nodos'][0].model}" for i, o in enumerate(plan.options)]
    vals = [o["coste_rel"] for o in plan.options]
    fig, ax = plt.subplots(figsize=(6, 2.4))
    bars = ax.barh(labels, vals, color=[C1] + [SEQ_LIGHT] * (len(vals) - 1), height=0.55)
    ax.invert_yaxis()
    ax.set_xlim(0, max(vals) * 1.2)
    ax.set_title("Coste relativo estimado (opción 1 = 100)")
    ax.grid(axis="y", visible=False)
    _hbar_labels(ax, bars)
    return _save(fig, folder, "destino_opciones.png")


def architecture(plan, folder):
    """Esquema lógico: switches, nodos, almacenamiento, PBS y redes."""
    n = len(plan.nodes)
    shown = plan.nodes if n <= 8 else plan.nodes[:7]
    w = max(9, 1.25 * (len(shown) + 2))
    fig, ax = plt.subplots(figsize=(w * 0.8, 5.2))
    ax.set_xlim(0, w)
    ax.set_ylim(0, 6)
    ax.axis("off")

    def box(x, y, bw, bh, text, fc, ec=BRAND, fs=8, color=INK, bold=False):
        ax.add_patch(FancyBboxPatch((x, y), bw, bh, boxstyle="round,pad=0.02,rounding_size=0.08", fc=fc, ec=ec, lw=1))
        chars = max(int(bw * 0.8 * 72 / (fs * 0.62)), 8)   # caracteres que caben por línea (aprox.)
        text = "\n".join(textwrap.fill(t, chars) for t in text.split("\n"))
        ax.text(x + bw / 2, y + bh / 2, text, ha="center", va="center", fontsize=fs, color=color,
                fontweight="bold" if bold else "normal")

    # switches
    box(0.5, 4.9, w - 1, 0.6, "2× switch de servicio (MLAG/stack) · " + f"{plan.sc['red']['velocidad_gbps']} GbE · VLANs de VMs, migración, backup"
        + (" y almacenamiento" if plan.storage_type in ("ceph", "san", "nfs") else ""), "#e8f0f9", fs=8.5, bold=True)
    # nodos
    nx0 = 0.5
    step = (w - 1) / max(len(shown) + (1 if n > len(shown) else 0), 1)
    bw = min(step * 0.85, 1.6)
    spec = shown[0]["spec"]
    for i, nd in enumerate(shown):
        x = nx0 + i * step + (step - bw) / 2
        s = nd["spec"]
        box(x, 2.6, bw, 1.5, f"{nd['name']}\n{s.cores} cores\n{s.ram_gib} GiB"
            + (f"\n{s.data_disks}× {s.data_disk_tb:g} TB" if s.data_disks and plan.storage_type in ('ceph', 'zfs') else ""),
            "white", fs=7.5)
        ax.plot([x + bw / 2, x + bw / 2], [4.1, 4.9], color=C1, lw=1.6)
    if n > len(shown):
        x = nx0 + len(shown) * step + (step - bw) / 2
        box(x, 2.6, bw, 1.5, f"… +{n - len(shown)}\nnodos", "white", fs=8)
    ax.text(w / 2, 2.35, f"Clúster Proxmox VE {plan.sc['pve_version']} · {n} nodos · {spec.model}", ha="center", fontsize=9,
            color=BRAND, fontweight="bold")
    # almacenamiento
    typ = plan.storage_type
    if typ == "ceph":
        box(0.5, 1.2, w - 1, 0.7, f"Ceph (réplica {plan.sc['almacenamiento'].get('replicas', 3)}) distribuido en todos los nodos · "
            f"{plan.eval['almacenamiento_util_gib'] / 1024:.1f} TiB útiles · red dedicada", "#e6f6ef", ec=C3, fs=8.5)
    elif typ == "zfs":
        box(0.5, 1.2, w - 1, 0.7, f"ZFS local en cada nodo + replicación entre nodos · {plan.eval['almacenamiento_util_gib'] / 1024:.1f} TiB útiles",
            "#e6f6ef", ec=C3, fs=8.5)
    else:
        lbl = "Cabina SAN (iSCSI/FC, multipath)" if typ == "san" else "NAS NFS"
        box(0.5, 1.2, (w - 1) * (0.55 if plan.pbs else 1), 0.7, f"{lbl} · {plan.eval['almacenamiento_util_gib'] / 1024:.1f} TiB útiles",
            "#e6f6ef", ec=C3, fs=8.5)
    if plan.pbs:
        p = plan.pbs["propuesta"]
        x0 = 0.5 + (w - 1) * 0.6 if typ in ("san", "nfs") else w * 0.55
        bw2 = w - 0.5 - x0
        y0 = 1.2 if typ in ("san", "nfs") else 0.2
        box(x0, y0, bw2, 0.7, f"Proxmox Backup Server · {plan.pbs['util_necesario_gib'] / 1024:.1f} TiB · {p['cores']} cores · {p['ram_gib']} GiB",
            "#fdf0e9", ec=C2, fs=8)
    box(0.5, 0.2, w * 0.45, 0.7, "Red de gestión + Corosync (2 enlaces) · BMC/iRMC fuera de banda", "#f0efec", ec=INK2, fs=8)
    ax.set_title("Arquitectura propuesta", loc="left")
    return _save(fig, folder, "destino_arquitectura.png")


def node_network(plan, folder):
    """Esquema de puertos → bonds → bridges/usos de un nodo tipo."""
    fig, ax = plt.subplots(figsize=(8.5, 3.6))
    ax.axis("off")
    ax.set_xlim(0, 10)
    nets = plan.networks
    phys = [x for x in nets if x["puertos"] not in ("-",)]
    ax.set_ylim(0, len(phys) + 0.5)
    for i, nt in enumerate(phys):
        y = len(phys) - i - 0.5
        for x, txt, fc in ((0.2, nt["puertos"], "#f0efec"), (3.0, nt["interfaz"], "#e8f0f9"), (6.3, nt["red"], "white")):
            ax.add_patch(FancyBboxPatch((x, y - 0.32), 3.1 if x == 6.3 else 2.5, 0.64, boxstyle="round,pad=0.02,rounding_size=0.06",
                                        fc=fc, ec=BRAND, lw=0.8))
            ax.text(x + (1.55 if x == 6.3 else 1.25), y, textwrap.fill(txt, 34 if x == 6.3 else 28), ha="center", va="center", fontsize=7.2)
        ax.annotate("", (3.0, y), (2.7, y), arrowprops=dict(arrowstyle="->", color=INK2, lw=0.8))
        ax.annotate("", (6.3, y), (5.5, y), arrowprops=dict(arrowstyle="->", color=INK2, lw=0.8))
    ax.text(1.45, len(phys) + 0.25, "Puertos físicos", ha="center", fontsize=8, color=INK2, fontweight="bold")
    ax.text(4.25, len(phys) + 0.25, "Bond / bridge", ha="center", fontsize=8, color=INK2, fontweight="bold")
    ax.text(7.85, len(phys) + 0.25, "Uso", ha="center", fontsize=8, color=INK2, fontweight="bold")
    return _save(fig, folder, "destino_red_nodo.png")


def waves_gantt(plan, folder):
    ws = plan.waves
    if not ws:
        return None
    fig, ax = plt.subplots(figsize=(8, 0.34 * len(ws) + 1.2))
    color = {"Piloto": C3, "Estándar": C1, "Críticas": C2, "Con bloqueos": CRIT}
    for i, w in enumerate(ws):
        dur = max(w["horas"] / 24 * 3, 0.6)  # ventana + validación
        ax.barh(i, dur, left=w["dia"], color=color.get(w["tipo"], C1), height=0.55)
        ax.text(w["dia"] + dur + 0.3, i, f"{len(w['guests'])} VMs · {w['gib'] / 1024:.1f} TiB · ~{w['horas']:.1f} h",
                va="center", fontsize=7.5, color=INK2)
    ax.set_yticks(range(len(ws)), [w["nombre"] for w in ws])
    ax.invert_yaxis()
    last = max(w["dia"] for w in ws) + 7
    ax.set_xlim(-0.5, last + 6)
    ax.set_xlabel("Días desde el inicio de la migración")
    ax.set_title("Calendario de olas de migración")
    ax.grid(axis="y", visible=False)
    handles = [plt.Rectangle((0, 0), 1, 1, color=c) for k, c in color.items() if any(w["tipo"] == k for w in ws)]
    ax.legend(handles, [k for k in color if any(w["tipo"] == k for w in ws)], loc="upper center", bbox_to_anchor=(0.5, -0.12), ncol=4, fontsize=8)
    return _save(fig, folder, "migracion_olas.png")


def pbs_capacity(plan, folder):
    if not plan.pbs:
        return None
    p = plan.pbs
    full = p["datos_origen_gib"] * plan.sc["pbs"]["reduccion"] / 1024
    inc = p["guardado_gib"] / 1024 - full
    margin = p["util_necesario_gib"] / 1024 - full - inc
    fig, ax = plt.subplots(figsize=(7, 1.7))
    parts = [("Copia completa inicial", full, C1), ("Cambios retenidos", inc, SEQ_MID), ("Margen de llenado", margin, NEUTRAL)]
    left = 0
    for lbl, v, c in parts:
        ax.barh([0], [v], left=left, color=c, height=0.5, label=f"{lbl}: {v:.1f} TiB", edgecolor=SURFACE, linewidth=1.5)
        left += v
    ax.set_yticks([])
    ax.set_xlabel("TiB útiles en el datastore")
    ax.set_title("Capacidad estimada del PBS")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.45), ncol=3, fontsize=8)
    ax.grid(axis="y", visible=False)
    return _save(fig, folder, "pbs_capacidad.png")


def risks(plan, folder):
    from collections import Counter
    c = Counter((r["Categoría"], r["Severidad"]) for r in plan.issues)
    cats = sorted({k[0] for k in c}, key=lambda k: -sum(v for (cc, _), v in c.items() if cc == k))
    if not cats:
        return None
    fig, ax = plt.subplots(figsize=(7, 0.35 * len(cats) + 1.1))
    left = [0] * len(cats)
    for sev, col in (("BLOQUEO", CRIT), ("AVISO", WARN), ("INFO", SEQ_LIGHT)):
        vals = [c.get((k, sev), 0) for k in cats]
        ax.barh(cats, vals, left=left, color=col, height=0.6, label=sev.capitalize(), edgecolor=SURFACE, linewidth=1.5)
        left = [a + b for a, b in zip(left, vals)]
    for i, v in enumerate(left):
        ax.text(v, i, f"  {v}", va="center", fontsize=8, color=INK2)
    ax.invert_yaxis()
    ax.set_title("Puntos a revisar por categoría")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.18), ncol=3, fontsize=8)
    ax.grid(axis="y", visible=False)
    return _save(fig, folder, "riesgos.png")


def all_charts(plan, folder) -> dict:
    os.makedirs(folder, exist_ok=True)
    out = {}
    for name, fn in (("origen_nodos", source_hosts), ("origen_so", os_distribution), ("origen_tamanos", vm_sizes),
                     ("origen_almacenamiento", source_storage), ("destino_capacidad", capacity),
                     ("destino_reparto", node_distribution), ("destino_opciones", options_compare),
                     ("destino_arquitectura", architecture), ("destino_red_nodo", node_network),
                     ("migracion_olas", waves_gantt), ("pbs_capacidad", pbs_capacity), ("riesgos", risks)):
        try:
            p = fn(plan, folder)
        except Exception as exc:  # noqa: BLE001  (un gráfico fallido no impide el documento)
            print(f"Aviso: no se pudo generar el gráfico {name}: {exc}")
            p = None
        if p:
            out[name] = p
    return out
