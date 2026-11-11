"""Documento Word para presentar al cliente (editable), con gráficos."""
from __future__ import annotations

import os
import tempfile

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

from .branding import COMPANY, asset_path
from .charts import all_charts
from .network import USO_LABEL
from .scenario import PBS_VERSIONS, STORAGE_TYPES

BRAND = RGBColor(0x1F, 0x4E, 0x78)
GREY = RGBColor(0x55, 0x55, 0x55)


def _shade(cell, hex_color):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_color)
    tcPr.append(shd)


def _fmt(v):
    if isinstance(v, float):
        return f"{v:,.1f}".replace(",", "X").replace(".", ",").replace("X", ".")
    if isinstance(v, int):
        return f"{v:,}".replace(",", ".")
    return "" if v is None else str(v)


class Doc:
    TITLE = "Plan de migración a Proxmox VE"

    def __init__(self, plan, client=None):
        self.plan = plan
        self.client = client if client is not None else (plan.sc.get("cliente") if plan else "") or ""
        self.d = Document()
        st = self.d.styles["Normal"]
        st.font.name = "Calibri"
        st.font.size = Pt(10.5)
        for name, size in (("Heading 1", 16), ("Heading 2", 13), ("Heading 3", 11)):
            s = self.d.styles[name]
            s.font.color.rgb = BRAND
            s.font.size = Pt(size)
            s.font.name = "Calibri"
        sec = self.d.sections[0]
        sec.left_margin = sec.right_margin = Cm(2.2)
        sec.top_margin = Cm(2.0)
        sec.bottom_margin = Cm(1.8)
        self._header_footer()

    def _header_footer(self):
        sec = self.d.sections[0]
        sec.different_first_page_header_footer = True
        hp = sec.header.paragraphs[0]
        try:
            hp.add_run().add_picture(asset_path("fsas_logo_small.png"), height=Cm(0.8))
        except Exception:  # noqa: BLE001
            hp.add_run(COMPANY).bold = True
        r = hp.add_run(f"\t\t{self.TITLE} · {self.client}")
        r.font.size, r.font.color.rgb = Pt(8), GREY
        fp = sec.footer.paragraphs[0]
        fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = fp.add_run(f"{COMPANY} · Confidencial · Página ")
        r.font.size, r.font.color.rgb = Pt(8), GREY
        self._field(fp, "PAGE")

    @staticmethod
    def _field(p, code):
        r = p.add_run()
        r.font.size = Pt(8)
        for tag, attr in (("w:fldChar", "begin"), ("w:instrText", code), ("w:fldChar", "end")):
            el = OxmlElement(tag)
            if tag == "w:fldChar":
                el.set(qn("w:fldCharType"), attr)
            else:
                el.set(qn("xml:space"), "preserve")
                el.text = attr
            r._r.append(el)

    # ------------------------------------------------------------------ helpers
    def h(self, text, level=1):
        return self.d.add_heading(text, level)

    def p(self, text="", bold=False, italic=False, size=None, color=None, align=None):
        par = self.d.add_paragraph()
        r = par.add_run(text)
        r.bold, r.italic = bold, italic
        if size:
            r.font.size = Pt(size)
        if color:
            r.font.color.rgb = color
        if align:
            par.alignment = align
        return par

    def bullets(self, items):
        for it in items:
            self.d.add_paragraph(it, style="List Bullet")

    def numbered(self, items):
        # numeración manual: «List Number» continúa la cuenta entre listas en Word
        for i, it in enumerate(items, 1):
            par = self.d.add_paragraph(f"{i}. {it}")
            par.paragraph_format.left_indent = Cm(0.9)
            par.paragraph_format.first_line_indent = Cm(-0.5)

    def table(self, header, rows, widths=None, size=8.5):
        t = self.d.add_table(rows=1, cols=len(header))
        t.style = "Table Grid"
        t.alignment = WD_TABLE_ALIGNMENT.CENTER
        for i, h in enumerate(header):
            c = t.rows[0].cells[i]
            c.text = ""
            r = c.paragraphs[0].add_run(str(h))
            r.bold, r.font.size, r.font.color.rgb = True, Pt(size), RGBColor(0xFF, 0xFF, 0xFF)
            _shade(c, "1F4E78")
        for k, row in enumerate(rows):
            cells = t.add_row().cells
            for i, v in enumerate(row):
                cells[i].text = ""
                r = cells[i].paragraphs[0].add_run(_fmt(v))
                r.font.size = Pt(size)
                if k % 2:
                    _shade(cells[i], "F2F6FA")
        if widths:
            for row in t.rows:
                for i, w in enumerate(widths):
                    row.cells[i].width = Cm(w)
        self.d.add_paragraph()
        return t

    def kv(self, pairs, size=9.5):
        t = self.d.add_table(rows=0, cols=2)
        t.style = "Table Grid"
        for k, v in pairs:
            cells = t.add_row().cells
            cells[0].text, cells[1].text = "", ""
            r = cells[0].paragraphs[0].add_run(k)
            r.bold, r.font.size = True, Pt(size)
            _shade(cells[0], "E8F0F9")
            r = cells[1].paragraphs[0].add_run(_fmt(v))
            r.font.size = Pt(size)
            cells[0].width, cells[1].width = Cm(5.5), Cm(11)
        self.d.add_paragraph()

    def img(self, charts, key, width=16, caption=None):
        if key in charts:
            self.nfig = getattr(self, "nfig", 0) + 1
            caption = f"Figura {self.nfig}. {caption}" if caption else None
            self.d.add_picture(charts[key], width=Cm(width))
            self.d.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
            if caption:
                self.p(caption, italic=True, size=8.5, color=GREY, align=WD_ALIGN_PARAGRAPH.CENTER)

    def orientation(self, landscape):
        from docx.enum.section import WD_ORIENT, WD_SECTION
        cur = self.d.sections[-1]
        sec = self.d.add_section(WD_SECTION.NEW_PAGE)
        w, h = cur.page_width, cur.page_height
        if landscape and w < h or not landscape and w > h:
            sec.page_width, sec.page_height = h, w
        sec.orientation = WD_ORIENT.LANDSCAPE if landscape else WD_ORIENT.PORTRAIT
        sec.different_first_page_header_footer = False
        return sec

    def cover(self, title, subtitle, lines, note):
        try:
            self.d.add_picture(asset_path("fsas_logo.png"), width=Cm(7))
        except Exception:  # noqa: BLE001
            self.p(COMPANY, bold=True, size=20, color=BRAND)
        for _ in range(5):
            self.d.add_paragraph()
        self.p(title, bold=True, size=24, color=BRAND)
        self.p(subtitle, size=14, color=GREY)
        self.d.add_paragraph()
        for ln in lines:
            self.p(ln, size=12)
        for _ in range(6):
            self.d.add_paragraph()
        self.p(note, italic=True, size=8.5, color=GREY)
        self.page_break()

    def code(self, text, size=8):
        par = self.d.add_paragraph()
        par.paragraph_format.left_indent = Cm(0.4)
        r = par.add_run(text)
        r.font.name = "Consolas"
        r.font.size = Pt(size)
        r._element.rPr.rFonts.set(qn("w:eastAsia"), "Consolas")
        pPr = par._p.get_or_add_pPr()
        shd = OxmlElement("w:shd")
        shd.set(qn("w:val"), "clear")
        shd.set(qn("w:color"), "auto")
        shd.set(qn("w:fill"), "F2F2F2")
        pPr.append(shd)
        return par

    def checklist(self, items):
        for it in items:
            par = self.d.add_paragraph(f"☐  {it}")
            par.paragraph_format.left_indent = Cm(0.5)

    def page_break(self):
        self.d.add_paragraph().add_run().add_break(WD_BREAK.PAGE)

    # ------------------------------------------------------------------ documento
    def build(self, path, charts_dir=None):
        plan, sc = self.plan, self.plan.sc
        s = plan.summary()
        tmp = charts_dir or tempfile.mkdtemp(prefix="pvemigplan_")
        charts = all_charts(plan, tmp)
        st = sc["almacenamiento"]["tipo"]
        e = plan.eval
        cap = sc["capacidad"]

        # Portada
        try:
            self.d.add_picture(asset_path("fsas_logo.png"), width=Cm(7))
        except Exception:  # noqa: BLE001
            self.p(COMPANY, bold=True, size=20, color=BRAND)
        for _ in range(5):
            self.d.add_paragraph()
        self.p(sc.get("proyecto") or "Plan de migración a Proxmox VE", bold=True, size=24, color=BRAND)
        self.p(f"Diseño de la nueva plataforma Proxmox VE {sc['pve_version']} y plan de migración", size=14, color=GREY)
        self.d.add_paragraph()
        self.p(f"Cliente: {sc.get('cliente') or '—'}", size=12)
        self.p(f"Fecha: {plan.generated:%d/%m/%Y}", size=12)
        if sc.get("autor"):
            self.p(f"Preparado por: {sc['autor']} · {COMPANY}", size=12)
        else:
            self.p(f"Preparado por: {COMPANY}", size=12)
        for _ in range(6):
            self.d.add_paragraph()
        self.p("Documento confidencial. Las capacidades y configuraciones son estimaciones basadas en el inventario "
               "facilitado y en los supuestos descritos; deben validarse antes de la implantación.", italic=True, size=8.5, color=GREY)
        self.page_break()

        # 1. Resumen ejecutivo
        self.h("1. Resumen ejecutivo")
        self.p(f"Se ha analizado el inventario de la plataforma Proxmox VE actual ({s['clusters_origen']} clúster(es) o nodos "
               f"independientes, {s['hosts_origen']} servidores) con {s['vms']} máquinas virtuales y {s['cts']} contenedores. "
               + ("A partir de él se propone el hardware necesario para la nueva plataforma, " if sc["modo"] == "aconsejar"
                  else "Se ha validado el hardware previsto para la nueva plataforma, ")
               + "el diseño de red y almacenamiento" + (", la solución de copias de seguridad con Proxmox Backup Server" if plan.pbs else "")
               + " y un plan de migración por olas.")
        n0 = plan.nodes[0]["spec"]
        pairs = [
            ("Carga a migrar", f"{s['vms']} VMs + {s['cts']} CTs · {s['vcpu']:.0f} vCPU · {s['ram_gib']:.0f} GiB RAM · {s['disk_eff_tib']:.1f} TiB de datos"),
            ("Plataforma propuesta", f"Clúster Proxmox VE {sc['pve_version']} de {s['nodos']} nodos ({n0.model}" + (f", {n0.reference}" if n0.reference else "") + ")"),
            ("Capacidad total", f"{s['cores']} cores físicos · {s['ram_dest_gib']:,} GiB RAM · {s['util_tib']:.1f} TiB útiles".replace(",", ".")),
            ("Almacenamiento", s["almacenamiento"]),
            ("Ocupación prevista", f"CPU {s['cpu_pct']:.0f} % · RAM {s['ram_pct']:.0f} % (con un nodo caído: CPU {s['cpu_pct_n1']:.0f} % · RAM {s['ram_pct_n1']:.0f} %)"),
            ("Alta disponibilidad", f"N+{cap['n_mas']}: el servicio continúa con {cap['n_mas']} nodo(s) fuera de servicio"),
        ]
        if plan.pbs:
            pairs.append(("Copias de seguridad", f"Proxmox Backup Server {s['pbs_ver']} · {plan.pbs['util_necesario_gib'] / 1024:.1f} TiB útiles"
                                                  + (" · copia externa sincronizada" if sc["pbs"].get("offsite") else "")))
        pairs.append(("Migración", f"{plan.method['nombre']} · {s['olas']} olas" + (f" · ~{s['semanas']} semanas" if s.get("semanas") else "")))
        pairs.append(("Suscripciones Proxmox VE", f"{s['suscripciones_pve']} (se licencian por socket de CPU)"
                                                   + (" + 1 Proxmox Backup Server" if plan.pbs else "")))
        self.kv(pairs)
        if not e["ok"]:
            self.p("Atención: el hardware indicado no cubre todas las necesidades:", bold=True, color=RGBColor(0xC0, 0x00, 0x00))
            self.bullets(e["problemas"])
        self.img(charts, "destino_arquitectura", 16.5, "Arquitectura propuesta")
        self.page_break()

        # 2. Situación actual
        self.h("2. Situación actual")
        t = plan.an.totals()
        self.p(f"El inventario incluye {len(plan.an.all_guests)} VMs/CTs; quedan dentro del alcance {len(plan.an.guests)} "
               f"({t['running']} encendidas y {t['stopped']} apagadas)"
               + (f"; {t['excluded']} se han excluido (plantillas, apagadas o exclusiones manuales)." if t["excluded"] else "."))
        rows = [[r["Clúster / nodo"], r["Nodos"], r["Versión PVE"], r["VMs"], r["CTs"], r["vCPU"], r["RAM asignada (GiB)"],
                 r["Disco aprov. (GiB)"], r["Cores físicos"], r["RAM física (GiB)"]] for r in plan.an.by_cluster()]
        self.table(["Clúster / nodo", "Nodos", "PVE", "VMs", "CTs", "vCPU", "RAM asig. (GiB)", "Disco aprov. (GiB)", "Cores", "RAM física (GiB)"], rows, size=8)
        self.img(charts, "origen_nodos", 16.5, "Recursos de los servidores actuales")
        self.img(charts, "origen_so", 12.5, "Sistemas operativos")
        self.img(charts, "origen_tamanos", 10.5, "Distribución de tamaños")
        self.img(charts, "origen_almacenamiento", 15, "Almacenamiento actual")
        bk = plan.an.backup_summary()
        self.p(f"Copias de seguridad actuales: {bk['with_backup']} VMs/CTs con copia y {bk['without_backup']} sin copia registrada; "
               f"{bk['jobs']} trabajo(s) de backup" + (" (con Proxmox Backup Server)." if bk["uses_pbs"] else "."))
        hc = plan.an.health_counts()
        if hc:
            self.p(f"Estado de salud del entorno actual: {hc.get('CRÍTICO', 0)} avisos críticos y {hc.get('AVISO', 0)} avisos.")
        self.page_break()

        # 3. Requisitos
        self.h("3. Requisitos de capacidad")
        self.p("Las necesidades se calculan con los siguientes criterios:")
        self.kv([
            ("Crecimiento previsto", f"{cap['crecimiento_pct']} %"),
            ("CPU", f"vCPU asignadas con un ratio de {cap['ratio_vcpu_core']:g} vCPU por core físico y ocupación máxima del {cap['cpu_max_pct']} %"
             if cap["base_cpu"] == "asignado" else f"Uso observado × 1,5 (pico) con ocupación máxima del {cap['cpu_max_pct']} %"),
            ("Memoria", f"RAM asignada sin sobresuscripción, ocupación máxima del {cap['ram_max_pct']} % y reserva para Proxmox VE"
             + (" y Ceph" if st == "ceph" else " y ZFS" if st == "zfs" else "")),
            ("Disco", ("espacio usado por cada VM (o aprovisionado si no se conoce)" if cap["base_disco"] == "usado" else "espacio aprovisionado")
             + f" + {cap['reserva_snapshots_pct']} % de reserva para snapshots"),
            ("Tolerancia a fallos", f"N+{cap['n_mas']}, mínimo {cap['nodos_min']} nodos"),
        ])
        self.table(["Recurso", "Necesario", "Disponible", "Ocupación", "Con nodo caído"], [
            ["CPU (cores físicos)", round(plan.req.cores), e["cores"], f"{e['cpu_pct']:.0f} %", f"{e['cpu_pct_n1']:.0f} %"],
            ["RAM (GiB)", round(plan.req.ram_need_gib), round(e["ram_util_gib"]), f"{e['ram_pct']:.0f} %", f"{e['ram_pct_n1']:.0f} %"],
            ["Almacenamiento útil (TiB)", round(plan.req.data_gib / 1024, 1), round(e["almacenamiento_util_gib"] / 1024, 1),
             f"{e['alm_pct_real']:.0f} %", f"{e['alm_pct_real']:.0f} %"],
        ])
        self.img(charts, "destino_capacidad", 15.5, "Ocupación prevista del nuevo entorno")
        if e["avisos"]:
            self.p("Observaciones:", bold=True)
            self.bullets(e["avisos"])

        # 4. Hardware
        self.h("4. Plataforma propuesta")
        if plan.options:
            self.p("Se han evaluado distintas configuraciones de servidor. La opción 1 es la recomendada por equilibrio entre "
                   "capacidad, número de nodos y número de sockets (las suscripciones de Proxmox VE se licencian por socket). "
                   "La valoración económica se realiza aparte.")
            rows = []
            for i, o in enumerate(plan.options, 1):
                n, ev = o["nodos"][0], o["eval"]
                rows.append([f"{i}", f"{n.count}× {n.model}", f"{n.sockets}× {n.cores_per_socket} cores (~{n.ghz:g} GHz)", f"{n.ram_gib} GiB",
                             f"{n.data_disks}× {n.data_disk_tb:g} TB" if n.data_disks else "—",
                             f"{ev['cpu_pct_n1']:.0f} % / {ev['ram_pct_n1']:.0f} %", ev["sockets"]])
            self.table(["Opción", "Nodos", "CPU por nodo", "RAM", "Discos datos", "CPU/RAM N-1", "Sockets"], rows, size=8)
        groups = {}
        for nd in plan.nodes:
            groups.setdefault(id(nd["spec"]), [nd["spec"], 0])[1] += 1
        for spec, cnt in groups.values():
            self.h(f"{cnt}× {spec.model}" + (f" ({spec.reference})" if spec.reference else ""), 3)
            self.kv([("Procesador", spec.cpu_label or f"{spec.sockets}× {spec.cores_per_socket} cores"),
                     ("Cores / hilos por nodo", f"{spec.cores} / {spec.threads}"),
                     ("Memoria por nodo", f"{spec.ram_gib} GiB"),
                     ("Arranque", spec.boot),
                     ("Discos de datos", f"{spec.data_disks}× {spec.data_disk_tb:g} TB {spec.data_disk_type}" if spec.data_disks else "No (almacenamiento externo)"),
                     ("Red", ", ".join(f"{x['puertos']}× {x['gbps']:g} {'Gb FC' if x.get('uso') == 'fc' else 'GbE'} ({USO_LABEL.get(x.get('uso'), x.get('uso', ''))})"
                             for x in spec.nics) + " + iRMC 1 GbE"),
                     ("Software", f"Proxmox VE {sc['pve_version']} con suscripción (repositorio enterprise y soporte)")])
        self.img(charts, "destino_reparto", 15, "Reparto inicial de la carga entre los nodos")
        self.page_break()

        # 5. Red
        net = plan.net
        self.orientation(True)
        self.h("5. Diseño de red")
        self.p("Cada nodo separa el tráfico por función y reparte sus puertos entre dos switches (A/B) para que la caída de un "
               "switch, un puerto o un cable no afecte al servicio. La gestión fuera de banda (iRMC) va a un switch independiente.")
        self.img(charts, "destino_red", 24.5, "Esquema físico de red: switches, equipos y puertos por red")
        self.orientation(False)
        self.h("Switches", 3)
        self.table(["Función", "Suministra", "Modelo", "Nº", "Puertos/switch", "Puertos necesarios", "Velocidad"],
                   [[w["tipo"], w["suministra"], w["modelo"], w["cantidad"], w["puertos_por_switch"], w["puertos_necesarios"], w["velocidad"]]
                    for w in net.switches], size=8)
        if any(w["suministra"] == "Cliente" and w["modelo"] == "(por indicar)" for w in net.switches):
            self.p("Pendiente: confirmar con el cliente el modelo de los switches que aporta, su capacidad libre y la configuración de MLAG/stack.",
                   italic=True, color=GREY)
        self.h("Redes lógicas", 3)
        self.table(["Red", "VLAN", "Interfaz", "Puertos", "Modo", "MTU", "Notas"],
                   [[n["red"], n["vlan"] or "por definir", n["interfaz"], n["puertos"], n["modo"], n["mtu"], n["nota"]] for n in plan.networks], size=7.5)
        self.h("Puertos de cada nodo", 3)
        self.table(["Enlace", "Adaptador", "Puerto", "Nombre", "Bond", "Uso"],
                   [[r["Host Link"], r["Adapter"], r["Port No."], r["Device Name"], r["Bond No."], r["Usage"]] for r in net.host_ports], size=8)
        if plan.vlan_map:
            self.h("Correspondencia de redes de las VMs", 3)
            self.p("Las redes que usan hoy las VMs se recrean en el nuevo clúster con la misma VLAN, de modo que las VMs conservan "
                   "su direccionamiento IP. Se recomienda definirlas como VNets de SDN (zona VLAN) para gestionarlas a nivel de clúster.")
            self.table(["Bridge origen", "VLAN", "Clústeres", "NICs", "Destino propuesto"],
                       [[r["Bridge origen"], r["VLAN origen"], r["Clústeres"], r["NICs de VMs"], r["Destino propuesto"]] for r in plan.vlan_map], size=8)
        subnets = plan.an.subnets()
        if subnets:
            self.p("Subredes de los servidores actuales (referencia para el plan de direccionamiento): " + ", ".join(subnets[:20]) + ".")

        # 6. Almacenamiento
        self.h("6. Almacenamiento")
        self.p(STORAGE_TYPES.get(st, st) + ".", bold=True)
        if st == "ceph":
            self.bullets([
                f"Ceph con {sc['almacenamiento'].get('replicas', 3)} réplicas (tolera la pérdida de un nodo completo sin pérdida de datos).",
                f"Capacidad útil: {e['almacenamiento_util_gib'] / 1024:.1f} TiB con un llenado máximo del {sc['almacenamiento']['llenado_max_pct']} % "
                "y espacio para recuperar las réplicas de un nodo caído.",
                "Discos NVMe de clase empresarial con protección ante pérdida de energía (PLP); un OSD por disco.",
                "Red Ceph dedicada de 25 GbE o superior con jumbo frames; pools RBD para VMs y CephFS opcional para ISOs/plantillas.",
            ])
        elif st == "zfs":
            self.bullets([
                "ZFS en espejo (RAID10) en cada nodo y replicación asíncrona de las VMs a otro nodo para alta disponibilidad.",
                "En caso de fallo de un nodo, las VMs replicadas arrancan en otro nodo con los datos de la última replicación (1-15 min).",
                f"Capacidad útil del conjunto: {e['almacenamiento_util_gib'] / 1024:.1f} TiB (contando la copia replicada).",
            ])
        elif st == "san":
            mdl = sc["hardware"]["almacenamiento_externo"].get("modelo") if sc["modo"] == "hardware" else ""
            self.bullets([
                f"Cabina externa{(' ' + mdl) if mdl else ''} de doble controladora con {e['almacenamiento_util_gib'] / 1024 / (sc['almacenamiento']['llenado_max_pct'] / 100):.1f} TiB útiles "
                f"({e['almacenamiento_util_gib'] / 1024:.1f} TiB al {sc['almacenamiento']['llenado_max_pct']} % de llenado).",
                "LUNs presentadas a todos los nodos por iSCSI o FC con multipath y LVM compartido.",
                "Proxmox VE 9 añade snapshots sobre LVM compartido (vista previa tecnológica); si se necesitan snapshots, "
                "valorar su uso o apoyarse en las copias de PBS.",
            ])
        else:
            self.bullets([
                f"NAS NFS de alta disponibilidad con {e['almacenamiento_util_gib'] / 1024:.1f} TiB útiles (al {sc['almacenamiento']['llenado_max_pct']} %).",
                "Discos de VM en formato qcow2 (permite snapshots). Red NFS dedicada con jumbo frames.",
            ])
        bt = plan.an.guest_storage_by_type()
        if bt:
            self.p("Origen de los discos de las VMs por tipo de almacenamiento actual: "
                   + ", ".join(f"{k}: {v / 1024:.1f} TiB" for k, v in sorted(bt.items(), key=lambda kv: -kv[1])) + ".")

        # 7. PBS
        if plan.pbs:
            p = plan.pbs
            self.h("7. Copias de seguridad con Proxmox Backup Server")
            ret = sc["pbs"]["retencion"]
            self.p(f"Se incorpora un servidor Proxmox Backup Server {s['pbs_ver']} dedicado. Realiza copias incrementales "
                   "deduplicadas y comprimidas, verificación periódica, cifrado opcional y restauración de ficheros individuales.")
            self.kv([
                ("Retención", f"{ret['diaria']} diarias, {ret['semanal']} semanales, {ret['mensual']} mensuales"
                              + (f", {ret['anual']} anuales" if ret.get("anual") else "")),
                ("Datos protegidos", f"{p['datos_origen_gib'] / 1024:.1f} TiB"),
                ("Capacidad útil del datastore", f"{p['util_necesario_gib'] / 1024:.1f} TiB "
                                                 f"(cambio diario {sc['pbs']['cambio_diario_pct']:g} %, reducción {sc['pbs']['reduccion']:g})"),
                ("Servidor", (sc["pbs"]["hardware"].get("modelo") + " · " if sc["pbs"]["hardware"].get("definido") else "")
                 + f"{p['propuesta']['cores']} cores · {p['propuesta']['ram_gib']} GiB RAM"),
                ("Discos", f"{sc['pbs']['hardware'].get('capacidad_util_tib')} TiB útiles ({sc['pbs']['hardware'].get('discos') or 'según configuración'})"
                 if sc["pbs"]["hardware"].get("definido") else p["propuesta"]["discos"]),
                ("Red", p["propuesta"]["red"]),
                ("Ventana de backup", f"Primera copia completa ~{p['horas_full']:.0f} h; incrementales diarias ~{max(p['horas_incremental'], 0.1):.1f} h"),
            ])
            self.img(charts, "pbs_capacidad", 15, "Ocupación estimada del datastore")
            extra = ["Jobs de backup diarios fuera de horario, verificación semanal y prune/garbage collection automáticos.",
                     "Notificaciones por correo de errores de backup y verificación.",
                     "Restauración «live-restore»: la VM arranca mientras se restaura desde el PBS."]
            if sc["pbs"].get("offsite"):
                extra.append("Segundo PBS en otra ubicación con sincronización (sync job) para cumplir la regla 3-2-1.")
            else:
                extra.append("Recomendado: copia fuera del CPD (segundo PBS con sync job o cinta LTO) para cumplir la regla 3-2-1.")
            self.bullets(extra)
        self.page_break()

        # 8. Migración
        sec = 8 if plan.pbs else 7
        self.h(f"{sec}. Plan de migración")
        self.p(plan.method["nombre"] + ".", bold=True)
        self.numbered(plan.method["pasos"])
        self.p("Ventajas: " + plan.method["ventajas"])
        self.p("Parada estimada: " + plan.method["parada"])
        self.h("Fases", 3)
        self.numbered([
            "Preparación: instalación del hardware, Proxmox VE, red, almacenamiento" + (" y PBS" if plan.pbs else "") + "; pruebas de HA y de rendimiento.",
            "Ola piloto con VMs no críticas para validar el procedimiento y los tiempos.",
            "Olas estándar agrupadas por clúster y servicio, en ventanas acordadas.",
            "Olas críticas (alta disponibilidad, bases de datos, controladores de dominio…) con plan de vuelta atrás.",
            "Cierre: verificación, alta en HA y backup, retirada de las VMs de origen y desmantelamiento del entorno antiguo.",
        ])
        mig = sc["migracion"]
        self.p(f"Rendimiento supuesto: {mig['mbps_por_flujo']} MB/s por migración y {mig['flujos']} migraciones simultáneas; "
               f"hasta {mig['max_vms_ola']} VMs y {mig['max_gib_ola'] / 1024:.1f} TiB por ola; {mig['olas_por_semana']} olas por semana.")
        self.table(["Ola", "Fecha", "VMs", "vCPU", "RAM (GiB)", "Datos (TiB)", "Transferencia (h)"],
                   [[w["nombre"], w["fecha"].strftime("%d/%m/%Y") if w.get("fecha") else f"Día {w['dia']}", len(w["guests"]),
                     round(w["vcpu"]), round(w["ram"]), round(w["gib"] / 1024, 2), round(w["horas"], 1)] for w in plan.waves], size=8)
        self.img(charts, "migracion_olas", 16, "Calendario de olas")
        self.h("Vuelta atrás", 3)
        self.p("Las VMs de origen no se eliminan hasta el cierre de cada ola: si una VM no funciona correctamente en destino, "
               "se apaga y se vuelve a arrancar la original. Los cambios de datos realizados en destino durante ese tiempo se evalúan caso a caso.")

        # 9. Riesgos
        self.h(f"{sec + 1}. Riesgos y puntos a revisar")
        self.img(charts, "riesgos", 14.5, "Puntos a revisar por categoría")
        bl = [r for r in plan.issues if r["Severidad"] == "BLOQUEO"]
        av = [r for r in plan.issues if r["Severidad"] == "AVISO"]
        if bl:
            self.p("Bloqueos (resolver antes de migrar):", bold=True)
            self.table(["VM", "Categoría", "Detalle"], [[f"{r['Nombre']} ({r['VMID']})" if r["VMID"] else r["Clúster"], r["Categoría"], r["Detalle"]]
                                                       for r in bl[:40]], size=8)
        if av:
            from collections import Counter
            c = Counter(r["Categoría"] for r in av)
            self.p("Avisos más frecuentes: " + ", ".join(f"{k} ({v})" for k, v in c.most_common()) + ". El detalle por VM está en el Excel del plan.")
        self.bullets([
            "Compatibilidad de CPU: usar un tipo de CPU virtual genérico (x86-64-v2-AES / v3) si cambia la generación o el fabricante.",
            "Licencias de software que dependan del hardware (MAC, UUID, número de cores): revisar con los fabricantes.",
            "Coordinar con los responsables de cada aplicación las ventanas de parada y las pruebas de validación.",
        ])

        # Anexo
        self.page_break()
        self.h("Anexo A. Ubicación inicial de las VMs")
        rows = []
        for g in sorted(plan.an.guests, key=lambda g: (plan.placement.get(g.key) or "", g.name.lower())):
            wave = next((w["nombre"] for w in plan.waves if g in w["guests"]), "")
            rows.append([g.name, g.vmid, g.kind, round(g.vcpu), round(g.ram_gib, 1), round(g.disk_effective_gib), plan.placement.get(g.key), wave])
        self.table(["Nombre", "VMID", "Tipo", "vCPU", "RAM (GiB)", "Disco (GiB)", "Nodo destino", "Ola"], rows, size=7.5)
        self.h("Anexo B. Supuestos y limitaciones", 2)
        self.bullets([
            "El inventario es una foto en un instante: el uso de CPU y memoria debe confirmarse con métricas de varias semanas.",
            "Los modelos y configuraciones de servidor son orientativos y deben validarse con el configurador del fabricante.",
            "Los tiempos de migración dependen del rendimiento real de red y almacenamiento; la ola piloto permite ajustarlos.",
            f"Documento generado a partir del inventario de PVE Inventory el {plan.generated:%d/%m/%Y}.",
        ])
        self.d.save(path)
        for f in ([] if charts_dir else charts.values()):
            try:
                os.remove(f)
            except OSError:
                pass
        return path


def to_docx(plan, path, charts_dir=None):
    """Genera el Word; si se indica charts_dir, deja allí los PNG (útiles para presentaciones)."""
    return Doc(plan).build(path, charts_dir)


__all__ = ["to_docx", "PBS_VERSIONS"]
