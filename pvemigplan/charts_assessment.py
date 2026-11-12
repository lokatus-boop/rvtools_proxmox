"""Gráficos del informe de solo análisis (infraestructura actual)."""
from __future__ import annotations

import os
from types import SimpleNamespace

from . import charts as base
from matplotlib.ticker import MaxNLocator

from .charts import C1, C2, C3, CRIT, GRID, INK2, NEUTRAL, SEQ_DARK, SEQ_LIGHT, SEQ_MID, SURFACE, WARN, _hbar_labels, _legend_below, _save, plt


def _int_axis(ax, axis="x"):
    (ax.xaxis if axis == "x" else ax.yaxis).set_major_locator(MaxNLocator(integer=True))


def _vbars(ax, labels, values, color=C1):
    _int_axis(ax, "y")
    bars = ax.bar(labels, values, color=color, width=0.6)
    ax.grid(axis="x", visible=False)
    top = max(values or [0]) or 1
    ax.set_ylim(0, top * 1.18)
    for r in bars:
        if r.get_height():
            ax.text(r.get_x() + r.get_width() / 2, r.get_height() + top * 0.02, f"{r.get_height():.0f}",
                    ha="center", va="bottom", fontsize=8, color=INK2)
    return bars


def kpi_state(a, folder):
    s = a.state_counts()
    items = [(k, v) for k, v in s.items() if v]
    if not items:
        return None
    colors = {"VMs encendidas": C1, "VMs apagadas": SEQ_LIGHT, "CTs encendidos": C3, "CTs apagados": "#a6dcc5", "Plantillas": NEUTRAL}
    fig, ax = plt.subplots(figsize=(7, 1.6))
    left = 0
    total = sum(v for _, v in items)
    for k, v in items:
        ax.barh([0], [v], left=left, color=colors[k], height=0.5, label=f"{k}: {v}", edgecolor=SURFACE, linewidth=1.5)
        if v / total > 0.06:
            ax.text(left + v / 2, 0, str(v), ha="center", va="center", fontsize=8, color="white" if colors[k] in (C1, C3) else INK2)
        left += v
    ax.set_xlim(0, total)
    ax.set_yticks([])
    ax.set_xticks([])
    ax.grid(False)
    ax.spines["bottom"].set_visible(False)
    ax.spines["left"].set_visible(False)
    ax.set_title(f"Estado de las {total} VMs, contenedores y plantillas")
    _legend_below(ax, ncol=3, gap=0.15)
    return _save(fig, folder, "estado_vms.png")


def node_usage(a, folder):
    rows = a.node_rows()
    if not rows:
        return None
    multi = len(a.an.clusters) > 1
    labels = [r["Nodo"] if not multi else f"{r['Nodo']}\n{str(r['Clúster']).replace(' (standalone)', '')[:18]}" for r in rows]
    fig, ax = plt.subplots(figsize=(7.5, max(2.2, 0.5 * len(rows) + 1.2)))
    y = list(range(len(rows)))
    h = 0.36
    cpu = [r["Uso CPU (%)"] or 0 for r in rows]
    ram = [r["Uso RAM (%)"] or 0 for r in rows]
    b1 = ax.barh([i - h / 2 for i in y], cpu, height=h, color=C1, label="Uso de CPU (%)")
    b2 = ax.barh([i + h / 2 for i in y], ram, height=h, color=C2, label="Uso de RAM (%)")
    ax.set_xlim(0, 110)
    ax.axvline(80, color=INK2, lw=1, ls="--")
    ax.set_yticks(y, labels)
    ax.invert_yaxis()
    _hbar_labels(ax, b1, "{:.0f} %")
    _hbar_labels(ax, b2, "{:.0f} %")
    ax.set_xlabel("% de uso en el momento del inventario · línea discontinua = 80 %")
    ax.set_title("Uso de CPU y memoria por nodo")
    ax.grid(axis="y", visible=False)
    _legend_below(ax, ncol=2, gap=0.75)
    return _save(fig, folder, "uso_nodos.png")


def overcommit(a, folder):
    rows = [r for r in a.node_rows() if r["Hilos"] or r["RAM física (GiB)"]]
    if not rows:
        return None
    labels = [r["Nodo"] for r in rows]
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(9, max(2.2, 0.42 * len(rows) + 1.2)))
    ratio = [r["Ratio vCPU:hilo"] or 0 for r in rows]
    cols = [CRIT if v > 8 else WARN if v > 4 else C1 for v in ratio]
    b = a1.barh(labels, ratio, color=cols, height=0.6)
    a1.axvline(4, color=INK2, lw=1, ls="--")
    a1.set_xlim(0, max(ratio + [5]) * 1.25)
    _hbar_labels(a1, b, "{:.1f}:1")
    a1.invert_yaxis()
    a1.set_title("Ratio vCPU : hilo (encendidas)")
    a1.set_xlabel("línea discontinua = 4:1")
    a1.grid(axis="y", visible=False)
    pct = [r["RAM asignada encendidas (GiB)"] / r["RAM física (GiB)"] * 100 if r["RAM física (GiB)"] else 0 for r in rows]
    cols = [CRIT if v > 100 else WARN if v > 85 else C1 for v in pct]
    b = a2.barh(labels, pct, color=cols, height=0.6)
    a2.axvline(100, color=CRIT, lw=1.2)
    a2.set_xlim(0, max(pct + [100]) * 1.25)
    _hbar_labels(a2, b, "{:.0f} %")
    a2.set_yticks(range(len(rows)), [""] * len(rows))
    a2.invert_yaxis()
    a2.set_title("RAM asignada / RAM física")
    a2.set_xlabel("línea roja = 100 %")
    a2.grid(axis="y", visible=False)
    fig.tight_layout()
    return _save(fig, folder, "sobreasignacion.png")


def vms_per_node(a, folder):
    rows = a.node_rows()
    if not rows:
        return None
    labels = [r["Nodo"] for r in rows]
    on = [r["Encendidas"] for r in rows]
    off = [r["VMs/CTs"] - r["Encendidas"] for r in rows]
    fig, ax = plt.subplots(figsize=(7, max(2.0, 0.4 * len(rows) + 1)))
    ax.barh(labels, on, color=C1, height=0.6, label="Encendidas")
    ax.barh(labels, off, left=on, color=SEQ_LIGHT, height=0.6, label="Apagadas", edgecolor=SURFACE, linewidth=1.5)
    for i, r in enumerate(rows):
        ax.text(on[i] + off[i], i, f"  {r['VMs/CTs']}", va="center", fontsize=8, color=INK2)
    ax.set_xlim(0, max([x + y for x, y in zip(on, off)] + [1]) * 1.15)
    ax.invert_yaxis()
    ax.set_title("VMs y contenedores por nodo")
    _int_axis(ax)
    ax.grid(axis="y", visible=False)
    _legend_below(ax, ncol=2, gap=0.45)
    return _save(fig, folder, "vms_nodo.png")


def os_family(a, folder):
    c = a.an.os_distribution().most_common()
    if not c:
        return None
    fig, ax = plt.subplots(figsize=(5.2, 2.6))
    colors = {"Linux": C1, "Windows": C2, "Linux (CT)": C3, "Otros": NEUTRAL}
    bars = ax.barh([k for k, _ in c], [v for _, v in c], color=[colors.get(k, NEUTRAL) for k, _ in c], height=0.6)
    ax.invert_yaxis()
    ax.set_xlim(0, max(v for _, v in c) * 1.18)
    ax.set_title("Familia de sistema operativo")
    _int_axis(ax)
    ax.grid(axis="y", visible=False)
    _hbar_labels(ax, bars)
    return _save(fig, folder, "so_familia.png")


def ram_sizes(a, folder):
    b = a.ram_buckets()
    fig, ax = plt.subplots(figsize=(5.2, 2.6))
    _vbars(ax, list(b), list(b.values()))
    ax.set_title("Tamaño de las VMs (memoria)")
    return _save(fig, folder, "tamanos_ram.png")


def storage_types(a, folder):
    d = a.storage_by_type()
    d = {k: v for k, v in d.items() if v[0]}
    if not d:
        return None
    items = sorted(d.items(), key=lambda kv: -kv[1][0])
    labels = [k for k, _ in items]
    used = [v[1] / 1024 for _, v in items]
    free = [max(v[0] - v[1], 0) / 1024 for _, v in items]
    fig, ax = plt.subplots(figsize=(6.5, 0.45 * len(items) + 1.1))
    ax.barh(labels, used, color=C1, height=0.6, label="Usado")
    ax.barh(labels, free, left=used, color=SEQ_LIGHT, height=0.6, label="Libre", edgecolor=SURFACE, linewidth=1.5)
    for i in range(len(items)):
        tot = used[i] + free[i]
        ax.text(tot, i, f"  {tot:.1f} TiB · {used[i] / tot * 100 if tot else 0:.0f} %", va="center", fontsize=8, color=INK2)
    ax.set_xlim(0, max(u + f for u, f in zip(used, free)) * 1.35)
    ax.invert_yaxis()
    ax.set_xlabel("TiB")
    ax.set_title("Capacidad por tipo de almacenamiento")
    ax.grid(axis="y", visible=False)
    _legend_below(ax, ncol=2)
    return _save(fig, folder, "almacenamiento_tipos.png")


def networks(a, folder):
    rows = a.an.vlan_usage()
    if not rows:
        return None
    rows = sorted(rows, key=lambda r: -r["vms"])[:15]
    labels = [f"{r['bridge']}" + (f" · VLAN {r['vlan']}" if r["vlan"] else (" (SDN)" if r["sdn"] else " · sin VLAN")) for r in rows]
    fig, ax = plt.subplots(figsize=(6.5, 0.36 * len(rows) + 1.0))
    bars = ax.barh(labels, [r["vms"] for r in rows], color=C1, height=0.6)
    ax.invert_yaxis()
    ax.set_xlim(0, max(r["vms"] for r in rows) * 1.18)
    ax.set_title("VMs/CTs por red (bridge / VLAN)")
    _int_axis(ax)
    ax.grid(axis="y", visible=False)
    _hbar_labels(ax, bars)
    return _save(fig, folder, "redes.png")


def backup_age(a, folder):
    b = a.backup_age()
    if not sum(b.values()):
        return None
    fig, ax = plt.subplots(figsize=(5.6, 2.6))
    colors = [CRIT, C3, C1, WARN, C2]
    bars = ax.bar(list(b), list(b.values()), color=colors, width=0.6)
    top = max(b.values()) or 1
    ax.set_ylim(0, top * 1.18)
    ax.grid(axis="x", visible=False)
    for r in bars:
        if r.get_height():
            ax.text(r.get_x() + r.get_width() / 2, r.get_height() + top * 0.02, f"{r.get_height():.0f}", ha="center", va="bottom",
                    fontsize=8, color=INK2)
    ax.set_title("Antigüedad del último backup (VMs/CTs)")
    _int_axis(ax, "y")
    return _save(fig, folder, "backup_antiguedad.png")


def snapshot_age(a, folder):
    b = {k: v for k, v in a.snapshot_age().items() if v or k != "Sin fecha"}
    if not sum(b.values()):
        return None
    fig, ax = plt.subplots(figsize=(5.2, 2.4))
    _vbars(ax, list(b), list(b.values()), color=SEQ_MID)
    ax.set_title("Snapshots por antigüedad")
    return _save(fig, folder, "snapshots.png")


def findings(a, folder):
    from collections import Counter
    c = Counter()
    for f in a.findings:
        c[(f["Categoría"], f["Severidad"])] += 1
    cats = sorted({k[0] for k in c}, key=lambda k: -sum(v for (cc, _), v in c.items() if cc == k))
    if not cats:
        return None
    fig, ax = plt.subplots(figsize=(7, 0.35 * len(cats) + 1.1))
    left = [0] * len(cats)
    for sev, col, lbl in (("CRÍTICO", CRIT, "Crítico"), ("AVISO", WARN, "Aviso"), ("INFO", SEQ_LIGHT, "Informativo")):
        vals = [c.get((k, sev), 0) for k in cats]
        ax.barh(cats, vals, left=left, color=col, height=0.6, label=lbl, edgecolor=SURFACE, linewidth=1.5)
        left = [x + y for x, y in zip(left, vals)]
    for i, v in enumerate(left):
        ax.text(v, i, f"  {v}", va="center", fontsize=8, color=INK2)
    ax.set_xlim(0, max(left) * 1.15)
    ax.invert_yaxis()
    ax.set_title("Hallazgos por categoría y severidad")
    _int_axis(ax)
    ax.grid(axis="y", visible=False)
    _legend_below(ax, ncol=3)
    return _save(fig, folder, "hallazgos.png")


def all_charts(a, folder) -> dict:
    os.makedirs(folder, exist_ok=True)
    shim = SimpleNamespace(an=a.an)
    out = {}
    fns = (("estado_vms", kpi_state), ("uso_nodos", node_usage), ("sobreasignacion", overcommit), ("vms_nodo", vms_per_node),
           ("origen_nodos", lambda x, f: base.source_hosts(shim, f, "")), ("so_familia", os_family),
           ("origen_so", lambda x, f: base.os_distribution(shim, f)), ("origen_tamanos", lambda x, f: base.vm_sizes(shim, f)),
           ("tamanos_ram", ram_sizes), ("almacenamiento_tipos", storage_types),
           ("origen_almacenamiento", lambda x, f: base.source_storage(shim, f, "Almacenamientos (usado / libre)")), ("redes", networks),
           ("backup_antiguedad", backup_age), ("snapshots", snapshot_age), ("hallazgos", findings))
    for name, fn in fns:
        try:
            p = fn(a, folder)
        except Exception as exc:  # noqa: BLE001  (un gráfico fallido no impide el informe)
            print(f"Aviso: no se pudo generar el gráfico {name}: {exc}")
            p = None
        if p:
            out[name] = p
    return out


__all__ = ["all_charts", "GRID", "SEQ_DARK"]
