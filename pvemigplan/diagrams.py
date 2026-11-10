"""Diagramas de arquitectura y de red (con iconos de servidores, switches y cabinas)."""
from __future__ import annotations

import textwrap

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyBboxPatch, Rectangle  # noqa: E402

from .charts import BRAND, INK, INK2, SURFACE, _save  # noqa: E402
from .network import USO_LABEL  # noqa: E402

DARK = "#2b3440"
DARK2 = "#1d242c"
CARD = "#ffffff"
EDGE = "#c9d3de"
HEAD = {"servidor": "#1F4E78", "pbs": "#c2562a", "cabina": "#5b47c9"}


# ------------------------------------------------------------------ utilidades
def fit_text(ax, x, y, w, h, text, fs=10, min_fs=6, ha="center", va="center", **kw):
    """Escribe el texto dentro de la caja (x, y, w, h) en coordenadas de datos: ajusta saltos de línea y tamaño."""
    fig = ax.figure
    fig.canvas.draw_idle()
    r = fig.canvas.get_renderer()
    inv = ax.transData.inverted()
    attempts = [(sz, 200) for sz in _sizes(fs, max(min_fs, fs * 0.75))]
    attempts += [(sz, wd) for sz in _sizes(fs, min_fs) for wd in (90, 70, 56, 46, 38, 32, 26, 22, 18, 14, 12)]
    for size, width in attempts:
        wrapped = "\n".join(textwrap.fill(p, width) if p else "" for p in text.split("\n"))
        t = ax.text(0, 0, wrapped, fontsize=size, ha=ha, va=va, **kw)
        bb = t.get_window_extent(renderer=r)
        (x0, y0), (x1, y1) = inv.transform([(bb.x0, bb.y0), (bb.x1, bb.y1)])
        t.remove()
        if abs(x1 - x0) <= w * 0.94 and abs(y1 - y0) <= h * 0.92:
            px = x + (w / 2 if ha == "center" else (0.03 * w if ha == "left" else w * 0.97))
            py = y + (h / 2 if va == "center" else (h if va == "top" else 0))
            return ax.text(px, py, wrapped, fontsize=size, ha=ha, va=va, **kw)
    px = x + (w / 2 if ha == "center" else 0.03 * w)
    return ax.text(px, y + h / 2, textwrap.fill(text, 12), fontsize=min_fs, ha=ha, va="center", **kw)


def _sizes(hi, lo):
    out, v = [], hi
    while v >= lo:
        out.append(v)
        v -= 0.5
    return out


def rbox(ax, x, y, w, h, fc, ec=EDGE, lw=1.0, r=8, z=1):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle=f"round,pad=0,rounding_size={r}", fc=fc, ec=ec, lw=lw, zorder=z))


def draw_switch(ax, x, y, w, h, used, total, color, label=""):
    rbox(ax, x, y, w, h, DARK, ec=DARK2, r=4, z=3)
    if label:
        ax.text(x + 6, y + h - 8, label, color="white", fontsize=6, fontweight="bold", va="center", zorder=4)
    cols = 12
    pw, ph = (w - 16) / cols, (h - 22) / 2
    n = 0
    frac = min(used / total, 1) if total else 0
    for r in range(2):
        for c in range(cols):
            on = n < round(frac * cols * 2)
            ax.add_patch(Rectangle((x + 8 + c * pw + 1, y + 5 + r * (ph + 2)), pw - 2.5, ph - 1, fc=color if on else "#46515e",
                                   ec="#8a96a3", lw=0.4, zorder=4))
            n += 1
    ax.add_patch(plt.Circle((x + w - 7, y + h - 8), 1.8, color="#7fd0ff", zorder=4))


def draw_server(ax, x, y, w, h, label="PRIMERGY"):
    rbox(ax, x, y, w, h, DARK, ec=DARK2, r=3, z=3)
    ax.text(x + w * 0.42, y + h - 6, label, color="white", fontsize=5.5, fontweight="bold", ha="center", va="center", zorder=4)
    bays = 3
    bw = (w * 0.72) / bays
    for i in range(bays):
        ax.add_patch(Rectangle((x + 6 + i * bw, y + 4), bw - 2, h - 15, fc="#141a21", ec="#9aa6b2", lw=0.6, zorder=4))
    ax.add_patch(plt.Circle((x + w - 8, y + h / 2), 1.6, color="#7fd0ff", zorder=4))


def draw_storage(ax, x, y, w, h, label="STORAGE"):
    rbox(ax, x, y, w, h, DARK, ec=DARK2, r=3, z=3)
    ax.text(x + w / 2, y + h - 6, label, color="white", fontsize=5.5, fontweight="bold", ha="center", va="center", zorder=4)
    n = 12
    bw = (w - 12) / n
    for i in range(n):
        ax.add_patch(Rectangle((x + 6 + i * bw, y + 4), bw - 1.2, h - 15, fc="#141a21", ec="#9aa6b2", lw=0.5, zorder=4))


def _brand(model):
    m = (model or "").upper()
    for b in ("PRIMERGY", "ETERNUS", "NETAPP", "DELL", "HPE", "LENOVO", "CISCO", "JUNIPER"):
        if b in m:
            return b
    return "SERVER"


# ------------------------------------------------------------------ diagrama de red
def network_diagram(plan, folder):
    net = plan.net
    fabrics, eps = net.fabrics, net.endpoints
    W, H = 1366, 700
    fig, ax = plt.subplots(figsize=(13.66, 7.0))
    ax.set_xlim(0, W)
    ax.set_ylim(0, H)
    ax.axis("off")
    fig.subplots_adjust(0, 0, 1, 1)
    ax.add_patch(Rectangle((0, 0), W, H, fc="#f6f8fb", ec="none", zorder=0))
    ax.add_patch(Rectangle((0, H - 4), W, 4, fc=BRAND, ec="none", zorder=1))

    # red corporativa
    rbox(ax, 20, 640, W - 40, 46, "#eaf1f8", ec="#c5d5e6")
    cli = plan.sc.get("cliente") or "CLIENTE"
    ax.text(40, 663, f"RED CORPORATIVA / INFRAESTRUCTURA {cli.upper()}", fontsize=12, fontweight="bold", color=BRAND, va="center")
    fit_text(ax, W * 0.52, 642, W * 0.46, 42, "Uplinks de los switches: nº de enlaces, velocidades y tipo de interconexión por definir con el cliente",
             fs=9, color=INK2, ha="right")

    # switches
    nf = len(fabrics)
    cw = min(230, (W - 40 - (nf - 1) * 20) / nf)
    gap = (W - 40 - nf * cw) / max(nf - 1, 1)
    sw_x = {}
    for i, f in enumerate(fabrics):
        x = 20 + i * (cw + gap)
        sw_x[f["id"]] = x + cw / 2
        rbox(ax, x, 455, cw, 165, CARD, ec=EDGE)
        rbox(ax, x + 8, 585, cw - 16, 28, f["color"], ec=f["color"], r=5, z=2)
        unit = "Gb FC" if f["nombre"].startswith("FC") else "GbE"
        title = (f"GESTIÓN OOB · {f['gbps']:g} {unit}" if f["rol"] == "oob" else
                 f"{'SERVICIO' if f['rol'] == 'servicio' else ('SAN' if unit == 'Gb FC' else 'STORAGE')} · {f['nombre']} · {f['gbps']:g} {unit.replace(' FC', '')}")
        fit_text(ax, x + 8, 585, cw - 16, 28, title, fs=10, color="white", fontweight="bold", zorder=3)
        sw_per = max(1, f.get("switches", 1))
        total = 48 * sw_per
        brand = _brand(f.get("modelo"))
        draw_switch(ax, x + 22, 535, cw - 44, 42, f["puertos"], total, f["color"],
                    brand if brand != "SERVER" else ("FC 32G" if unit == "Gb FC" else "SWITCH"))
        fit_text(ax, x + 6, 512, cw - 12, 20, f"{f['puertos']} puertos requeridos" + (f" · {sw_per} switches" if sw_per > 1 else ""),
                 fs=9, color=INK, fontweight="bold")
        fit_text(ax, x + 6, 478, cw - 12, 32, f.get("modelo") or "", fs=8, color=INK2)
        sup = "Suministra Fsas Technologies" if f.get("suministra") == "fsas" else "Switch del cliente"
        fit_text(ax, x + 6, 458, cw - 12, 18, sup, fs=7.5, color=f["color"], fontweight="bold")
        ax.plot([x + cw / 2, x + cw / 2], [620, 640], color=f["color"], lw=1, ls=(0, (3, 3)), zorder=1)

    # buses (una línea horizontal por fabric)
    bus_y = {}
    for i, f in enumerate(fabrics):
        yb = 430 - i * 16
        bus_y[f["id"]] = yb
        ax.plot([20, W - 20], [yb, yb], color=f["color"], lw=1.6, zorder=2)
        ax.plot([sw_x[f["id"]], sw_x[f["id"]]], [455, yb], color=f["color"], lw=1.6, zorder=2)
        ax.add_patch(plt.Circle((sw_x[f["id"]], yb), 4, color=f["color"], zorder=5))
    low_bus = min(bus_y.values())
    ax.text(22, low_bus - 18, "Cada línea horizontal representa una red física (fabric) compartida. Los números indican puertos por equipo; no son cables dibujados.",
            fontsize=7.5, color=INK2, va="center", zorder=6, bbox=dict(fc="#f6f8fb", ec="none", pad=1.5))

    # equipos
    ne = len(eps)
    bw = min(430, (W - 40 - (ne - 1) * 22) / ne)
    gap = (W - 40 - ne * bw) / max(ne - 1, 1) if ne > 1 else 0
    top = low_bus - 40
    max_rows = max(len(ep["links"]) for ep in eps) if eps else 1
    bh = 40 + 60 + max_rows * 30 + 45
    bottom = top - bh
    ax.set_ylim(bottom - 10, H)
    fig.set_size_inches(13.66, 7.0 * (H - bottom + 10) / H)
    ax.add_patch(Rectangle((0, bottom - 10), W, H, fc="#f6f8fb", ec="none", zorder=0))
    fab_by_id = {f["id"]: f for f in fabrics}
    for i, ep in enumerate(eps):
        x = 20 + i * (bw + gap) if ne > 1 else (W - bw) / 2
        kind = "pbs" if ep["id"] == "pbs" else ep["tipo"]
        head = HEAD.get(kind, BRAND)
        rbox(ax, x, bottom, bw, bh, CARD, ec=EDGE, r=12)
        rbox(ax, x + 8, top - 40, bw - 16, 34, head, ec=head, r=8, z=2)
        fit_text(ax, x + 8, top - 40, bw - 16, 34, ep["titulo"].upper(), fs=12, color="white", fontweight="bold", zorder=3)
        # icono + modelo
        iy = top - 95
        if ep["tipo"] == "cabina":
            draw_storage(ax, x + 18, iy, 125, 40, _brand(ep["modelo"]))
        else:
            draw_server(ax, x + 18, iy, 125, 40, _brand(ep["modelo"]))
        fit_text(ax, x + 152, iy, bw - 165, 40, ep["detalle"], fs=12, color=INK, fontweight="bold", ha="left")
        # puertos
        fabs_used = []
        rows = []
        for ln in ep["links"]:
            for fid in (ln["fa"], ln["fb"]):
                if fid and fid not in fabs_used:
                    fabs_used.append(fid)
            if ln["fb"] and ln["b"]:
                txt = f"{ln['a']} + {ln['b']} puertos ({fab_by_id[ln['fa']]['nombre']} / {fab_by_id[ln['fb']]['nombre']})"
            else:
                txt = f"{ln['a']} puerto{'s' if ln['a'] > 1 else ''} ({fab_by_id[ln['fa']]['nombre']})"
            unit = "Gb"
            rows.append((fab_by_id[ln["fa"]]["color"], f"{USO_LABEL.get(ln['uso'], ln['uso'])} {ln['gbps']:g} {unit}", txt))
        rh = 30
        for k, (col, a, b) in enumerate(rows):
            ry = iy - 14 - (k + 1) * rh
            ax.add_patch(Rectangle((x + 18, ry + rh * 0.2), 7, rh * 0.6, fc=col, ec="none", zorder=3))
            fit_text(ax, x + 32, ry, bw * 0.36, rh, a, fs=10, color=INK, fontweight="bold", ha="left")
            fit_text(ax, x + 32 + bw * 0.36, ry, bw * 0.58, rh, b, fs=10, color=INK, ha="left")
        if ep.get("nota"):
            fit_text(ax, x + 8, bottom + 4, bw - 16, 18, ep["nota"], fs=8, color=INK2, style="italic")
        # bajadas desde los buses
        for k, fid in enumerate(fabs_used):
            px = x + (k + 0.5) * bw / len(fabs_used)
            col = fab_by_id[fid]["color"]
            ax.plot([px, px], [bus_y[fid], top], color=col, lw=1.6, zorder=2)
            ax.add_patch(plt.Circle((px, bus_y[fid]), 4, color=col, zorder=5))
            ax.add_patch(plt.Circle((px, top), 4, color=col, zorder=5))
    return _save(fig, folder, "destino_red.png")


# ------------------------------------------------------------------ arquitectura lógica
def architecture(plan, folder):
    W, H = 1200, 560
    fig, ax = plt.subplots(figsize=(12, 5.6))
    ax.set_xlim(0, W)
    ax.set_ylim(0, H)
    ax.axis("off")
    fig.subplots_adjust(0, 0, 1, 1)
    ax.add_patch(Rectangle((0, 0), W, H, fc=SURFACE, ec="none", zorder=0))
    net = plan.net
    svc = next(f for f in net.fabrics if f["rol"] == "servicio")
    unit = "GbE"
    rbox(ax, 30, 480, W - 60, 56, "#e8f0f9", ec=BRAND)
    fit_text(ax, 30, 480, W - 60, 56, f"2× switch de servicio (MLAG/stack) · {svc['gbps']:g} {unit} · "
             f"VLANs de VMs, migración" + (", backup" if plan.pbs else "") + (" y almacenamiento" if plan.storage_type in ("ceph", "nfs") or
                                                                               (plan.storage_type == "san" and not net.fc) else ""),
             fs=12, color=INK, fontweight="bold")
    nodes = plan.nodes
    shown = nodes if len(nodes) <= 8 else nodes[:7]
    extra = len(nodes) - len(shown)
    slots = len(shown) + (1 if extra else 0)
    sw = min(140, (W - 60 - (slots - 1) * 14) / slots)
    gap = (W - 60 - slots * sw) / max(slots - 1, 1) if slots > 1 else 0
    for i, nd in enumerate(shown):
        x = 30 + i * (sw + gap) if slots > 1 else (W - sw) / 2
        s = nd["spec"]
        ax.plot([x + sw / 2, x + sw / 2], [480, 430], color="#2a78d6", lw=2, zorder=1)
        rbox(ax, x, 270, sw, 160, "white", ec=BRAND)
        draw_server(ax, x + 10, 380, sw - 20, 38, _brand(s.model))
        txt = f"{nd['name']}\n{s.cores} cores · {s.ram_gib} GiB"
        if s.data_disks and plan.storage_type in ("ceph", "zfs"):
            txt += f"\n{s.data_disks}× {s.data_disk_tb:g} TB {s.data_disk_type}"
        fit_text(ax, x + 4, 276, sw - 8, 98, txt, fs=10, color=INK)
    if extra:
        x = 30 + len(shown) * (sw + gap)
        rbox(ax, x, 270, sw, 160, "white", ec=BRAND)
        fit_text(ax, x, 270, sw, 160, f"… +{extra}\nnodos", fs=12, color=INK)
    spec = nodes[0]["spec"]
    fit_text(ax, 30, 236, W - 60, 28, f"Clúster Proxmox VE {plan.sc['pve_version']} · {len(nodes)} nodos · {spec.model}",
             fs=12, color=BRAND, fontweight="bold")
    e = plan.eval
    typ = plan.storage_type
    st_txt = {"ceph": f"Ceph (réplica {plan.sc['almacenamiento'].get('replicas', 3)}) en todos los nodos · {e['almacenamiento_util_gib'] / 1024:.1f} TiB útiles · red dedicada",
              "zfs": f"ZFS local en cada nodo + replicación · {e['almacenamiento_util_gib'] / 1024:.1f} TiB útiles",
              "san": f"Cabina SAN ({net.proto}, multipath) · {e['almacenamiento_util_gib'] / 1024:.1f} TiB útiles",
              "nfs": f"NAS NFS · {e['almacenamiento_util_gib'] / 1024:.1f} TiB útiles"}[typ]
    half = (W - 60 - 20) / 2
    rbox(ax, 30, 130, half if plan.pbs else W - 60, 80, "#e6f6ef", ec="#1baf7a")
    fit_text(ax, 30, 130, half if plan.pbs else W - 60, 80, st_txt, fs=12, color=INK)
    if plan.pbs:
        p = plan.pbs
        rbox(ax, 50 + half, 130, half, 80, "#fdf0e9", ec="#eb6834")
        fit_text(ax, 50 + half, 130, half, 80, f"Proxmox Backup Server\n{p['util_necesario_gib'] / 1024:.1f} TiB útiles · "
                 f"{p['propuesta']['cores']} cores · {p['propuesta']['ram_gib']} GiB RAM", fs=12, color=INK)
    rbox(ax, 30, 25, W - 60, 80, "#f0efec", ec=INK2)
    oob = next(f for f in net.fabrics if f["rol"] == "oob")
    fit_text(ax, 30, 25, W - 60, 80, f"Red de gestión + Corosync (2 enlaces redundantes) · gestión fuera de banda (iRMC) en switch OOB"
             f" ({oob.get('modelo') or 'por indicar'})", fs=11, color=INK)
    return _save(fig, folder, "destino_arquitectura.png")
