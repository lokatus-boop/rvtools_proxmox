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
from pvetools.i18n import LANGS, N_, _, data_out, fmt_date, number, tr, yes_no
from pvetools.safefile import atomic_save

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
    if isinstance(v, bool):
        return yes_no(v)
    if isinstance(v, float):
        return number(v, 1)
    if isinstance(v, int):
        return number(v, 0)
    return "" if v is None else data_out(str(v))


class Doc:
    TITLE = N_("Plan de migración a Proxmox VE")

    def __init__(self, plan, client=None):
        self.plan = plan
        self.client = client if client is not None else (plan.sc.get("cliente") if plan else "") or ""
        self.d = Document()
        st = self.d.styles["Normal"]
        st.font.name = "Calibri"
        st.font.size = Pt(10.5)
        for name, size in (("Heading 1", 16), ("Heading 2", 13), ("Heading 3", 11), ("Heading 4", 10)):
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
        title = _(self.TITLE)
        if self.TITLE == Doc.TITLE and self.plan is not None and not getattr(self.plan, "migrate", True):
            title = _("Diseño de la plataforma Proxmox VE")
        r = hp.add_run(f"\t\t{title} · {self.client}")
        r.font.size, r.font.color.rgb = Pt(8), GREY
        fp = sec.footer.paragraphs[0]
        fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = fp.add_run(_("{COMPANY} · Confidencial · Página ", COMPANY=COMPANY))
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
            r = c.paragraphs[0].add_run(_(str(h)))
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
            t.autofit = False
            for row in t.rows:
                for i, w in enumerate(widths):
                    row.cells[i].width = Cm(w)
        self.d.add_paragraph()
        return t

    def sdn_tables(self, an, level=3, size=7.5):
        """Tablas de la configuración SDN del inventario (zonas, VNets/subredes y controladores/IPAM/DNS/fabrics)."""
        t = an.sdn_tables()
        for key, title in (("zones", _("Zonas SDN")), ("vnets", _("VNets y subredes SDN")),
                           ("objects", _("Controladores, IPAM, DNS y fabrics de SDN"))):
            rows = t[key]
            if key == "objects":
                rows = [r for r in rows if not (r["Objeto"] == "IPAM" and r["Tipo"] == "pve")]
            if not rows:
                continue
            cols = [c for c in rows[0] if any(r.get(c) not in (None, "") for r in rows) and not (key == "vnets" and c == "Tipo zona")]
            self.h(title, level)
            self.table(cols, [[r.get(c) for c in cols] for r in rows], size=size)
        return bool(t["zones"] or t["objects"])

    def kv(self, pairs, size=9.5):
        t = self.d.add_table(rows=0, cols=2)
        t.style = "Table Grid"
        for k, v in pairs:
            cells = t.add_row().cells
            cells[0].text, cells[1].text = "", ""
            r = cells[0].paragraphs[0].add_run(_(k))
            r.bold, r.font.size = True, Pt(size)
            _shade(cells[0], "E8F0F9")
            r = cells[1].paragraphs[0].add_run(_fmt(v))
            r.font.size = Pt(size)
            cells[0].width, cells[1].width = Cm(5.5), Cm(11)
        self.d.add_paragraph()

    def img(self, charts, key, width=16, caption=None):
        if key in charts:
            self.nfig = getattr(self, "nfig", 0) + 1
            caption = _("Figura {nfig}. {caption}", nfig=self.nfig, caption=caption) if caption else None
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
        for _i in range(5):
            self.d.add_paragraph()
        self.p(title, bold=True, size=24, color=BRAND)
        self.p(subtitle, size=14, color=GREY)
        self.d.add_paragraph()
        for ln in lines:
            self.p(ln, size=12)
        for _i in range(6):
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
            par = self.d.add_paragraph(f"☐  {_(it)}")
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
        load, mig = plan.has_load, plan.migrate

        # Portada
        try:
            self.d.add_picture(asset_path("fsas_logo.png"), width=Cm(7))
        except Exception:  # noqa: BLE001
            self.p(COMPANY, bold=True, size=20, color=BRAND)
        for _i in range(5):
            self.d.add_paragraph()
        title = sc.get("proyecto") or ""
        if not title or (not mig and title in {tr(DEFAULT_TITLE, lang=lg) for lg in LANGS}):
            title = _("Plan de migración a Proxmox VE") if mig else _("Nueva plataforma Proxmox VE")
        self.p(title, bold=True, size=24, color=BRAND)
        self.p(_("Diseño de la nueva plataforma Proxmox VE {pve_version}", pve_version=sc['pve_version']) + (_(" y plan de migración") if mig else ""), size=14, color=GREY)
        self.d.add_paragraph()
        self.p(_("Cliente: {v}", v=sc.get('cliente') or '—'), size=12)
        self.p(_("Fecha: {generated}", generated=fmt_date(plan.generated)), size=12)
        if sc.get("autor"):
            self.p(_("Preparado por: {autor} · {COMPANY}", autor=sc['autor'], COMPANY=COMPANY), size=12)
        else:
            self.p(_("Preparado por: {COMPANY}", COMPANY=COMPANY), size=12)
        for _i in range(6):
            self.d.add_paragraph()
        self.p(_("Documento confidencial. Las capacidades y configuraciones son estimaciones basadas en ")
               + (_("el inventario facilitado") if load else _("el hardware indicado")) + _(" y en los supuestos descritos; deben validarse "
               "antes de la implantación."), italic=True, size=8.5, color=GREY)
        self.page_break()

        # 1. Resumen ejecutivo
        num = iter(range(1, 50))
        self.h(_("{next}. Resumen ejecutivo", next=next(num)))
        if load:
            self.p(_("Se ha analizado el inventario de la plataforma Proxmox VE actual ({clusters_origen} clúster(es) o nodos independientes, {hosts_origen} servidores) con {vms} máquinas virtuales y {cts} contenedores. ", clusters_origen=s['clusters_origen'], hosts_origen=s['hosts_origen'], vms=s['vms'], cts=s['cts'])
                   + (_("A partir de él se propone el hardware necesario para la nueva plataforma, ") if sc["modo"] == "aconsejar"
                      else _("Se ha validado el hardware previsto para la nueva plataforma, "))
                   + _("el diseño de red y almacenamiento") + (_(", la solución de copias de seguridad con Proxmox Backup Server") if plan.pbs else "")
                   + (_(" y un plan de migración por olas.") if mig else _(". Este documento no incluye migración: describe la nueva plataforma.")))
        else:
            self.p(_("Este documento describe el diseño de la nueva plataforma Proxmox VE: hardware, red, almacenamiento")
                   + (_(", copias de seguridad con Proxmox Backup Server") if plan.pbs else "")
                   + _(" y su puesta en marcha. No incluye migración de máquinas virtuales."))
        n0 = plan.nodes[0]["spec"]
        pairs = [
            (_("Carga a migrar") if mig else _("Carga prevista"), _("{vms} VMs + {cts} CTs · {vcpu:.0f} vCPU · {ram_gib:.0f} GiB RAM · {disk_eff_tib:.1f} TiB de datos", vms=s['vms'], cts=s['cts'], vcpu=s['vcpu'], ram_gib=s['ram_gib'], disk_eff_tib=s['disk_eff_tib'])),
            (_("Plataforma propuesta"), _("Clúster Proxmox VE {pve_version} de {nodos} nodos ({model}", pve_version=sc['pve_version'], nodos=s['nodos'], model=n0.model) + (f", {n0.reference}" if n0.reference else "") + ")"),
            (_("Capacidad total"), _("{cores} cores físicos · {ram} GiB RAM · {tib:.1f} TiB útiles", cores=s['cores'], ram=number(s['ram_dest_gib']), tib=s['util_tib'])),
            ("Almacenamiento", s["almacenamiento"]),
            (_("Ocupación prevista"), _("CPU {cpu_pct:.0f} % · RAM {ram_pct:.0f} % (con un nodo caído: CPU {cpu_pct_n1:.0f} % · RAM {ram_pct_n1:.0f} %)", cpu_pct=s['cpu_pct'], ram_pct=s['ram_pct'], cpu_pct_n1=s['cpu_pct_n1'], ram_pct_n1=s['ram_pct_n1'])),
            (_("Alta disponibilidad"), _("N+{n_mas}: el servicio continúa con {n_mas} nodo(s) fuera de servicio", n_mas=cap['n_mas'])),
        ]
        if not load:
            pairs = [x for x in pairs if x[0] not in (_("Carga prevista"), _("Ocupación prevista"))]
        if plan.pbs:
            pairs.append((_("Copias de seguridad"), _("Proxmox Backup Server {pbs_ver} · {util_necesario_gib:.1f} TiB útiles", pbs_ver=s['pbs_ver'], util_necesario_gib=plan.pbs['util_necesario_gib'] / 1024)
                                                  + (_(" · copia externa sincronizada") if sc["pbs"].get("offsite") else "")))
        if mig:
            pairs.append((_("Migración"), _("{nombre} · {olas} olas", nombre=plan.method['nombre'], olas=s['olas']) + (_(" · ~{semanas} semanas", semanas=s['semanas']) if s.get("semanas") else "")))
        pairs.append((_("Suscripciones Proxmox VE"), _("{suscripciones_pve} (se licencian por socket de CPU)", suscripciones_pve=s['suscripciones_pve'])
                                                   + (_(" + 1 Proxmox Backup Server") if plan.pbs else "")))
        self.kv(pairs)
        if not e["ok"]:
            self.p(_("Atención: el hardware indicado no cubre todas las necesidades:"), bold=True, color=RGBColor(0xC0, 0x00, 0x00))
            self.bullets(e["problemas"])
        self.img(charts, "destino_arquitectura", 16.5, _("Arquitectura propuesta"))
        self.page_break()

        # 2. Situación actual (solo si hay carga en el inventario)
        t = plan.an.totals()
        if load:
            self._current(plan, charts, t, next(num))

        # 3. Requisitos
        self._requirements(plan, charts, e, cap, st, next(num))

        # 4. Hardware
        self._hardware(plan, charts, sc, next(num))

        # 5. Red
        self._network(plan, charts, next(num))

        # 6. Almacenamiento
        self._storage(plan, sc, e, st, next(num))

        # 7. PBS
        if plan.pbs:
            self._pbs(plan, charts, sc, s, next(num))
        self.page_break()

        if mig:
            self._migration(plan, charts, sc, next(num))
        else:
            self._startup(plan, next(num))

        # Riesgos
        self._risks(plan, charts, next(num))

        # Anexos
        if load:
            self.page_break()
            self.h(_("Anexo A. Ubicación inicial de las VMs") if mig else _("Anexo A. Reparto previsto de la carga"))
            rows = []
            for g in sorted(plan.an.guests, key=lambda g: (plan.placement.get(g.key) or "", g.name.lower())):
                row = [g.name, g.vmid, g.kind, round(g.vcpu), round(g.ram_gib, 1), round(g.disk_effective_gib), plan.placement.get(g.key)]
                if mig:
                    row.append(next((w["nombre"] for w in plan.waves if g in w["guests"]), ""))
                rows.append(row)
            self.table(["Nombre", "VMID", "Tipo", "vCPU", "RAM (GiB)", _("Disco (GiB)"), "Nodo destino"] + (["Ola"] if mig else []), rows, size=7.5)
        self.h((_("Anexo B. ") if load else _("Anexo. ")) + _("Supuestos y limitaciones"), 2)
        self.bullets(([
            _("El inventario es una foto en un instante: el uso de CPU y memoria debe confirmarse con métricas de varias semanas.")] if load else [])
            + [_("Los modelos y configuraciones de servidor son orientativos y deben validarse con el configurador del fabricante.")]
            + ([_("Los tiempos de migración dependen del rendimiento real de red y almacenamiento; la ola piloto permite ajustarlos.")] if mig else [])
            + [_("Documento generado ") + (_("a partir del inventario de PVE Inventory ") if load else "") + _("el {generated}.", generated=fmt_date(plan.generated))])
        path = atomic_save(path, self.d.save)
        for f in ([] if charts_dir else charts.values()):
            try:
                os.remove(f)
            except OSError:
                pass
        return path

    # ------------------------------------------------------------------ secciones
    def _current(self, plan, charts, t, n):
        self.h(_("{n}. Situación actual", n=n))
        self.p(_("El inventario incluye {n_all_guests} VMs/CTs; quedan dentro del alcance {n_guests} ({running} encendidas y {stopped} apagadas)", n_all_guests=len(plan.an.all_guests), n_guests=len(plan.an.guests), running=t['running'], stopped=t['stopped'])
               + (_("; {excluded} se han excluido (plantillas, apagadas o exclusiones manuales).", excluded=t['excluded']) if t["excluded"] else "."))
        rows = [[r["Clúster / nodo"], r["Nodos"], r["Versión PVE"], r["VMs"], r["CTs"], r["vCPU"], r["RAM asignada (GiB)"],
                 r["Disco aprov. (GiB)"], r["Cores físicos"], r["RAM física (GiB)"]] for r in plan.an.by_cluster()]
        self.table(["Clúster / nodo", "Nodos", "PVE", "VMs", "CTs", "vCPU", _("RAM asig. (GiB)"), "Disco aprov. (GiB)", "Cores", "RAM física (GiB)"], rows, size=8)
        self.img(charts, "origen_nodos", 16.5, _("Recursos de los servidores actuales"))
        self.img(charts, "origen_so", 12.5, _("Sistemas operativos"))
        self.img(charts, "origen_tamanos", 10.5, _("Distribución de tamaños"))
        self.img(charts, "origen_almacenamiento", 15, _("Almacenamiento actual"))
        bk = plan.an.backup_summary()
        self.p(_("Copias de seguridad actuales: {with_backup} VMs/CTs con copia y {without_backup} sin copia registrada; {jobs} trabajo(s) de backup", with_backup=bk['with_backup'], without_backup=bk['without_backup'], jobs=bk['jobs']) + (_(" (con Proxmox Backup Server).") if bk["uses_pbs"] else "."))
        hc = plan.an.health_counts()
        if hc:
            self.p(_("Estado de salud del entorno actual: {get} avisos críticos y {get2} avisos.", get=hc.get('CRÍTICO', 0), get2=hc.get('AVISO', 0)))
        self.page_break()

    def _requirements(self, plan, charts, e, cap, st, n):
        if not plan.has_load:
            self.h(_("{n}. Capacidad de la plataforma", n=n))
            self.p(_("No hay carga de VMs/CTs que dimensionar: se indica la capacidad que ofrece la plataforma con los criterios de ocupación (CPU {cpu_max_pct} %, RAM {ram_max_pct} %) y tolerancia a fallos N+{n_mas}.", cpu_max_pct=cap['cpu_max_pct'], ram_max_pct=cap['ram_max_pct'], n_mas=cap['n_mas']))
            self.table(["Recurso", _("Total"), _("Con nodo caído")], [
                [_("CPU (cores físicos)"), e["cores"], e["cores_n1"]],
                [_("vCPU recomendadas (ratio ") + _("{ratio_vcpu_core:g}:1, ocupación máx.)", ratio_vcpu_core=cap['ratio_vcpu_core']),
                 round(e["cores"] * cap["ratio_vcpu_core"] * cap["cpu_max_pct"] / 100),
                 round(e["cores_n1"] * cap["ratio_vcpu_core"] * cap["cpu_max_pct"] / 100)],
                ["RAM para VMs (GiB)", round(e["ram_util_gib"]), round(e["ram_n1_gib"])],
                ["Almacenamiento útil (TiB)", round(e["almacenamiento_util_gib"] / 1024, 1), round(e["almacenamiento_util_gib"] / 1024, 1)],
            ])
            if e["avisos"]:
                self.p(_("Observaciones:"), bold=True)
                self.bullets(e["avisos"])
            return
        self.h(_("{n}. Requisitos de capacidad", n=n))
        self.p(_("Las necesidades se calculan con los siguientes criterios:"))
        self.kv([
            (_("Crecimiento previsto"), f"{cap['crecimiento_pct']} %"),
            ("CPU", _("vCPU asignadas con un ratio de {ratio_vcpu_core:g} vCPU por core físico y ocupación máxima del {cpu_max_pct} %", ratio_vcpu_core=cap['ratio_vcpu_core'], cpu_max_pct=cap['cpu_max_pct'])
             if cap["base_cpu"] == "asignado" else _("Uso observado × 1,5 (pico) con ocupación máxima del {cpu_max_pct} %", cpu_max_pct=cap['cpu_max_pct'])),
            (_("Memoria"), _("RAM asignada sin sobresuscripción, ocupación máxima del {ram_max_pct} % y reserva para Proxmox VE", ram_max_pct=cap['ram_max_pct'])
             + (_(" y Ceph") if st == "ceph" else _(" y ZFS") if st == "zfs" else "")),
            ("Disco", (_("espacio usado por cada VM (o aprovisionado si no se conoce)") if cap["base_disco"] == "usado" else _("espacio aprovisionado"))
             + _(" + {reserva_snapshots_pct} % de reserva para snapshots", reserva_snapshots_pct=cap['reserva_snapshots_pct'])),
            (_("Tolerancia a fallos"), _("N+{n_mas}, mínimo {nodos_min} nodos", n_mas=cap['n_mas'], nodos_min=cap['nodos_min'])),
        ])
        self.table(["Recurso", "Necesario", "Disponible", _("Ocupación"), _("Con nodo caído")], [
            [_("CPU (cores físicos)"), round(plan.req.cores), e["cores"], f"{e['cpu_pct']:.0f} %", f"{e['cpu_pct_n1']:.0f} %"],
            ["RAM (GiB)", round(plan.req.ram_need_gib), round(e["ram_util_gib"]), f"{e['ram_pct']:.0f} %", f"{e['ram_pct_n1']:.0f} %"],
            ["Almacenamiento útil (TiB)", round(plan.req.data_gib / 1024, 1), round(e["almacenamiento_util_gib"] / 1024, 1),
             f"{e['alm_pct_real']:.0f} %", f"{e['alm_pct_real']:.0f} %"],
        ])
        self.img(charts, "destino_capacidad", 15.5, _("Ocupación prevista del nuevo entorno"))
        if e["avisos"]:
            self.p(_("Observaciones:"), bold=True)
            self.bullets(e["avisos"])

    def _hardware(self, plan, charts, sc, n):
        self.h(_("{n}. Plataforma propuesta", n=n))
        if plan.options:
            self.p(_("Se han evaluado distintas configuraciones de servidor. La opción 1 es la recomendada por equilibrio entre "
                   "capacidad, número de nodos y número de sockets (las suscripciones de Proxmox VE se licencian por socket). "
                   "La valoración económica se realiza aparte."))
            rows = []
            for i, o in enumerate(plan.options, 1):
                n, ev = o["nodos"][0], o["eval"]
                rows.append([f"{i}", f"{n.count}× {n.model}", _("{sockets}× {cores_per_socket} cores (~{ghz:g} GHz)", sockets=n.sockets, cores_per_socket=n.cores_per_socket, ghz=n.ghz), f"{n.ram_gib} GiB",
                             _("{data_disks}× {data_disk_tb:g} TB", data_disks=n.data_disks, data_disk_tb=n.data_disk_tb) if n.data_disks else "—",
                             f"{ev['cpu_pct_n1']:.0f} % / {ev['ram_pct_n1']:.0f} %", ev["sockets"]])
            self.table(["Opción", "Nodos", "CPU por nodo", "RAM", "Discos datos", _("CPU/RAM N-1"), "Sockets"], rows, size=8)
        groups = {}
        for nd in plan.nodes:
            groups.setdefault(id(nd["spec"]), [nd["spec"], 0])[1] += 1
        for spec, cnt in groups.values():
            self.h(f"{cnt}× {spec.model}" + (f" ({spec.reference})" if spec.reference else ""), 3)
            self.kv([(_("Procesador"), spec.cpu_label or _("{sockets}× {cores_per_socket} cores", sockets=spec.sockets, cores_per_socket=spec.cores_per_socket)),
                     (_("Cores / hilos por nodo"), f"{spec.cores} / {spec.threads}"),
                     (_("Memoria por nodo"), f"{spec.ram_gib} GiB"),
                     ("Arranque", spec.boot),
                     (_("Discos de datos"), _("{data_disks}× {data_disk_tb:g} TB {data_disk_type}", data_disks=spec.data_disks, data_disk_tb=spec.data_disk_tb, data_disk_type=spec.data_disk_type) if spec.data_disks else _("No (almacenamiento externo)")),
                     ("Red", ", ".join(f"{x['puertos']}× {x['gbps']:g} {'Gb FC' if x.get('uso') == 'fc' else 'GbE'} ({_(USO_LABEL.get(x.get('uso'), x.get('uso', '')))})"
                             for x in spec.nics) + _(" + iRMC 1 GbE")),
                     (_("Software"), _("Proxmox VE {pve_version} con suscripción (repositorio enterprise y soporte)", pve_version=sc['pve_version']))])
        if plan.has_load:
            self.img(charts, "destino_reparto", 15, _("Reparto inicial de la carga entre los nodos"))
        self.page_break()

    def _network(self, plan, charts, n):
        net = plan.net
        self.orientation(True)
        self.h(_("{n}. Diseño de red", n=n))
        self.p(_("Cada nodo separa el tráfico por función y reparte sus puertos entre dos switches (A/B) para que la caída de un "
               "switch, un puerto o un cable no afecte al servicio. La gestión fuera de banda (iRMC) va a un switch independiente."))
        self.img(charts, "destino_red", 24.5, _("Esquema físico de red: switches, equipos y puertos por red"))
        self.orientation(False)
        self.h(_("Switches"), 3)
        self.table(["Función", "Suministra", "Modelo", "Nº", "Puertos/switch", "Puertos necesarios", "Velocidad"],
                   [[w["tipo"], w["suministra"], w["modelo"], w["cantidad"], w["puertos_por_switch"], w["puertos_necesarios"], w["velocidad"]]
                    for w in net.switches], size=8)
        if any(w["suministra"] == _("Cliente") and w["modelo"] == _("(por indicar)") for w in net.switches):
            self.p(_("Pendiente: confirmar con el cliente el modelo de los switches que aporta, su capacidad libre y la configuración de MLAG/stack."),
                   italic=True, color=GREY)
        self.h(_("Redes lógicas"), 3)
        self.table(["Red", "VLAN", "Interfaz", "Puertos", "Modo", "MTU", "Notas"],
                   [[n["red"], n["vlan"] or _("por definir"), n["interfaz"], n["puertos"], n["modo"], n["mtu"], n["nota"]] for n in plan.networks], size=7.5)
        self.h(_("Puertos de cada nodo"), 3)
        self.table([_("Enlace"), _("Adaptador"), "Puerto", "Nombre", "Bond", "Uso"],
                   [[r["Host Link"], r["Adapter"], r["Port No."], r["Device Name"], r["Bond No."], r["Usage"]] for r in net.host_ports], size=8)
        if plan.vlan_map:
            self.h(_("Correspondencia de redes de las VMs"), 3)
            self.p(_("Las redes que usan hoy las VMs se recrean en el nuevo clúster con la misma VLAN (o la misma VNet de SDN), de "
                   "modo que las VMs conservan su direccionamiento IP. Se recomienda definirlas como VNets de SDN para "
                   "gestionarlas a nivel de clúster."))
            self.table(["Bridge origen", "VLAN", "Clústeres", "NICs", "Destino propuesto"],
                       [[r["Bridge origen"], r["VLAN origen"], r["Clústeres"], r["NICs de VMs"], r["Destino propuesto"]] for r in plan.vlan_map], size=8)
        an = plan.an
        self.h(_("SDN (Software Defined Network)"), 3)
        if an.has_sdn():
            sdn = an.sdn()
            types = {z["type"] for z in sdn["zones"]}
            self.p(_("El entorno actual tiene SDN configurado ({sdn_summary}). La misma configuración (zonas, VNets, subredes, IPAM y DNS) se recrea en el nuevo clúster antes de migrar, con los mismos nombres, tags/VNI y subredes, de modo que las VMs siguen conectadas a la misma VNet y conservan su direccionamiento IP.", sdn_summary=an.sdn_summary()))
            notes = []
            if types & {"vlan", "qinq"}:
                notes.append(_("Zonas VLAN/QinQ: se asocian al bridge de las VMs del nuevo diseño (vmbr1); las VLANs deben estar "
                             "permitidas en los puertos de los switches de servicio."))
            if "vxlan" in types:
                notes.append(_("Zonas VXLAN: la lista de peers pasa a ser las IPs de los nodos nuevos; la MTU de la red física debe "
                             "admitir los 50 bytes de cabecera VXLAN (MTU de las VMs 1450 o jumbo frames en la red)."))
            if "evpn" in types:
                notes.append(_("Zonas EVPN: hay que recrear el controlador EVPN (ASN y peers con las IPs de los nodos nuevos), elegir "
                             "los exit nodes entre los nodos nuevos y, si hay peering BGP con los routers del cliente, revisarlo con "
                             "el equipo de red."))
            if "simple" in types:
                notes.append(_("Zonas simples: son locales a cada nodo; si sus subredes usan SNAT, la VM sale con la IP del nodo "
                             "donde se ejecuta."))
            if any(o["object"] in ("IPAM", "DNS") and o["type"] != "pve" for o in sdn["objects"]):
                notes.append(_("IPAM/DNS externos (NetBox, phpIPAM, PowerDNS): el nuevo clúster necesita acceso a esos servicios y un "
                             "token/clave propios."))
            if any(o["object"].startswith(("Fabric", "Nodo de fabric")) for o in sdn["objects"]):
                notes.append(_("Fabrics SDN (Proxmox VE 9): se definen de nuevo con las interfaces e IPs de los nodos nuevos."))
            if notes:
                self.bullets(notes)
            self.sdn_tables(an, level=4)
        elif not plan.vlan_map:
            self.p(_("Se propone definir las redes de las VMs como una zona SDN de tipo VLAN sobre vmbr1, con una VNet por cada "
                   "VLAN de servicio acordada con el cliente, para que se definan una sola vez para todo el clúster."))
        else:
            self.p(_("El entorno actual no tiene SDN configurado: las VMs se conectan directamente a los bridges de cada nodo. "
                   "En el nuevo clúster se propone una zona SDN de tipo VLAN con una VNet por cada VLAN de la tabla anterior, "
                   "para que las redes se definan una sola vez para todo el clúster."))
        subnets = plan.an.subnets()
        if subnets:
            self.p(_("Subredes de los servidores actuales (referencia para el plan de direccionamiento): ") + ", ".join(subnets[:20]) + ".")

    def _storage(self, plan, sc, e, st, n):
        self.h(_("{n}. Almacenamiento", n=n))
        self.p(_(STORAGE_TYPES.get(st, st)) + ".", bold=True)
        if st == "ceph":
            self.bullets([
                _("Ceph con {get} réplicas (tolera la pérdida de un nodo completo sin pérdida de datos).", get=sc['almacenamiento'].get('replicas', 3)),
                _("Capacidad útil: {almacenamiento_util_gib:.1f} TiB con un llenado máximo del {llenado_max_pct} % y espacio para recuperar las réplicas de un nodo caído.", almacenamiento_util_gib=e['almacenamiento_util_gib'] / 1024, llenado_max_pct=sc['almacenamiento']['llenado_max_pct']),
                _("Discos NVMe de clase empresarial con protección ante pérdida de energía (PLP); un OSD por disco."),
                _("Red Ceph dedicada de 25 GbE o superior con jumbo frames; pools RBD para VMs y CephFS opcional para ISOs/plantillas."),
            ])
        elif st == "zfs":
            self.bullets([
                _("ZFS en espejo (RAID10) en cada nodo y replicación asíncrona de las VMs a otro nodo para alta disponibilidad."),
                _("En caso de fallo de un nodo, las VMs replicadas arrancan en otro nodo con los datos de la última replicación (1-15 min)."),
                _("Capacidad útil del conjunto: {almacenamiento_util_gib:.1f} TiB (contando la copia replicada).", almacenamiento_util_gib=e['almacenamiento_util_gib'] / 1024),
            ])
        elif st == "san":
            mdl = sc["hardware"]["almacenamiento_externo"].get("modelo") if sc["modo"] == "hardware" else ""
            self.bullets([
                _("Cabina externa{v} de doble controladora con {almacenamiento_util_gib:.1f} TiB útiles ({almacenamiento_util_gib2:.1f} TiB al {llenado_max_pct} % de llenado).", v=(' ' + mdl) if mdl else '', almacenamiento_util_gib=e['almacenamiento_util_gib'] / 1024 / (sc['almacenamiento']['llenado_max_pct'] / 100), almacenamiento_util_gib2=e['almacenamiento_util_gib'] / 1024, llenado_max_pct=sc['almacenamiento']['llenado_max_pct']),
                _("LUNs presentadas a todos los nodos por iSCSI o FC con multipath y LVM compartido."),
                _("Proxmox VE 9 añade snapshots sobre LVM compartido (vista previa tecnológica); si se necesitan snapshots, "
                "valorar su uso o apoyarse en las copias de PBS."),
            ])
        else:
            self.bullets([
                _("NAS NFS de alta disponibilidad con {almacenamiento_util_gib:.1f} TiB útiles (al {llenado_max_pct} %).", almacenamiento_util_gib=e['almacenamiento_util_gib'] / 1024, llenado_max_pct=sc['almacenamiento']['llenado_max_pct']),
                _("Discos de VM en formato qcow2 (permite snapshots). Red NFS dedicada con jumbo frames."),
            ])
        bt = plan.an.guest_storage_by_type()
        if bt:
            self.p(_("Origen de los discos de las VMs por tipo de almacenamiento actual: ")
                   + ", ".join(f"{k}: {v / 1024:.1f} TiB" for k, v in sorted(bt.items(), key=lambda kv: -kv[1])) + ".")

    def _pbs(self, plan, charts, sc, s, n):
        p = plan.pbs
        self.h(_("{n}. Copias de seguridad con Proxmox Backup Server", n=n))
        ret = sc["pbs"]["retencion"]
        self.p(_("Se incorpora un servidor Proxmox Backup Server {pbs_ver} dedicado. Realiza copias incrementales deduplicadas y comprimidas, verificación periódica, cifrado opcional y restauración de ficheros individuales.", pbs_ver=s['pbs_ver']))
        load = plan.has_load
        self.kv([
            ("Retención", _("{diaria} diarias, {semanal} semanales, {mensual} mensuales", diaria=ret['diaria'], semanal=ret['semanal'], mensual=ret['mensual'])
                          + (_(", {anual} anuales", anual=ret['anual']) if ret.get("anual") else "")),
            (_("Datos protegidos"), f"{p['datos_origen_gib'] / 1024:.1f} TiB" if load else _("Las VMs que se desplieguen en la nueva plataforma")),
            (_("Capacidad útil del datastore"), (_("{util_necesario_gib:.1f} TiB (cambio diario {cambio_diario_pct:g} %, reducción {reduccion:g})", util_necesario_gib=p['util_necesario_gib'] / 1024, cambio_diario_pct=sc['pbs']['cambio_diario_pct'], reduccion=sc['pbs']['reduccion']))
             if load else f"{p['util_necesario_gib'] / 1024:.1f} TiB" + ("" if p.get("definido") else
                                                                         _(" (configuración mínima; ampliar según la carga prevista)"))),
            ("Servidor", (sc["pbs"]["hardware"].get("modelo") + " · " if sc["pbs"]["hardware"].get("definido") else "")
             + _("{cores} cores · {ram_gib} GiB RAM", cores=p['propuesta']['cores'], ram_gib=p['propuesta']['ram_gib'])),
            ("Discos", _("{get} TiB útiles ({v})", get=sc['pbs']['hardware'].get('capacidad_util_tib'), v=sc['pbs']['hardware'].get('discos') or _('según configuración'))
             if sc["pbs"]["hardware"].get("definido") else p["propuesta"]["discos"]),
            ("Red", p["propuesta"]["red"]),
        ] + ([(_("Ventana de backup"), _("Primera copia completa ~{horas_full:.0f} h; incrementales diarias ~{horas_incremental:.1f} h", horas_full=p['horas_full'], horas_incremental=max(p['horas_incremental'], 0.1)))]
              if load else []))
        if load:
            self.img(charts, "pbs_capacidad", 15, _("Ocupación estimada del datastore"))
        extra = [_("Jobs de backup diarios fuera de horario, verificación semanal y prune/garbage collection automáticos."),
                 _("Notificaciones por correo de errores de backup y verificación."),
                 _("Restauración «live-restore»: la VM arranca mientras se restaura desde el PBS.")]
        if sc["pbs"].get("offsite"):
            extra.append(_("Segundo PBS en otra ubicación con sincronización (sync job) para cumplir la regla 3-2-1."))
        else:
            extra.append(_("Recomendado: copia fuera del CPD (segundo PBS con sync job o cinta LTO) para cumplir la regla 3-2-1."))
        self.bullets(extra)

    def _startup(self, plan, n):
        self.h(_("{n}. Puesta en marcha", n=n))
        self.p(_("No se migran máquinas virtuales: la plataforma se entrega instalada, configurada y probada."))
        self.numbered([
            _("Preparación: instalación del hardware, cableado y configuración de los switches."),
            _("Instalación de Proxmox VE en todos los nodos, creación del clúster, red y almacenamiento")
            + (_(", y del Proxmox Backup Server") if plan.pbs else "") + ".",
            _("Pruebas de aceptación: alta disponibilidad, caída de enlaces y switches, rendimiento")
            + (_(", backup y restauración") if plan.pbs else "") + ".",
            _("Entrega: documentación as-built (generada con PVE Inventory sobre el nuevo entorno) y traspaso a postventa."),
        ])

    def _migration(self, plan, charts, sc, sec):
        self.h(_("{sec}. Plan de migración", sec=sec))
        self.p(plan.method["nombre"] + ".", bold=True)
        self.numbered(plan.method["pasos"])
        self.p(_("Ventajas: ") + plan.method["ventajas"])
        self.p(_("Parada estimada: ") + plan.method["parada"])
        self.h(_("Fases"), 3)
        self.numbered([
            _("Preparación: instalación del hardware, Proxmox VE, red, almacenamiento") + (_(" y PBS") if plan.pbs else "") + _("; pruebas de HA y de rendimiento."),
            _("Ola piloto con VMs no críticas para validar el procedimiento y los tiempos."),
            _("Olas estándar agrupadas por clúster y servicio, en ventanas acordadas."),
            _("Olas críticas (alta disponibilidad, bases de datos, controladores de dominio…) con plan de vuelta atrás."),
            _("Cierre: verificación, alta en HA y backup, retirada de las VMs de origen y desmantelamiento del entorno antiguo."),
        ])
        mig = sc["migracion"]
        self.p(_("Rendimiento supuesto: {mbps_por_flujo} MB/s por migración y {flujos} migraciones simultáneas; hasta {max_vms_ola} VMs y {max_gib_ola:.1f} TiB por ola; {olas_por_semana} olas por semana.", mbps_por_flujo=mig['mbps_por_flujo'], flujos=mig['flujos'], max_vms_ola=mig['max_vms_ola'], max_gib_ola=mig['max_gib_ola'] / 1024, olas_por_semana=mig['olas_por_semana']))
        self.table(["Ola", "Fecha", "VMs", "vCPU", "RAM (GiB)", _("Datos (TiB)"), _("Transferencia (h)")],
                   [[w["nombre"], fmt_date(w["fecha"]) if w.get("fecha") else _("Día {dia}", dia=w['dia']), len(w["guests"]),
                     round(w["vcpu"]), round(w["ram"]), round(w["gib"] / 1024, 2), round(w["horas"], 1)] for w in plan.waves], size=8)
        self.img(charts, "migracion_olas", 16, _("Calendario de olas"))
        self.h(_("Vuelta atrás"), 3)
        self.p(_("Las VMs de origen no se eliminan hasta el cierre de cada ola: si una VM no funciona correctamente en destino, "
               "se apaga y se vuelve a arrancar la original. Los cambios de datos realizados en destino durante ese tiempo se evalúan caso a caso."))

    def _risks(self, plan, charts, n):
        mig = plan.migrate
        self.h(_("{n}. Riesgos y puntos a revisar", n=n))
        if plan.has_load:
            self.img(charts, "riesgos", 14.5, _("Puntos a revisar por categoría"))
        bl = [r for r in plan.issues if r["Severidad"] == "BLOQUEO"]
        av = [r for r in plan.issues if r["Severidad"] == "AVISO"]
        if bl:
            self.p(_("Bloqueos (resolver antes de migrar):") if mig else _("Bloqueos (resolver antes de la implantación):"), bold=True)
            self.table(["VM", "Categoría", "Detalle"], [[f"{r['Nombre']} ({r['VMID']})" if r["VMID"] else r["Clúster"], r["Categoría"], r["Detalle"]]
                                                       for r in bl[:40]], size=8)
        if av:
            from collections import Counter
            c = Counter(r["Categoría"] for r in av)
            self.p(_("Avisos más frecuentes: ") + ", ".join(f"{k} ({v})" for k, v in c.most_common()) + _(". El detalle está en el Excel del plan."))
        if mig:
            self.bullets([
                _("Compatibilidad de CPU: usar un tipo de CPU virtual genérico (x86-64-v2-AES / v3) si cambia la generación o el fabricante."),
                _("Licencias de software que dependan del hardware (MAC, UUID, número de cores): revisar con los fabricantes."),
                _("Coordinar con los responsables de cada aplicación las ventanas de parada y las pruebas de validación."),
            ])
        else:
            self.bullets([
                _("Confirmar con el cliente direccionamiento IP, VLANs, DNS, NTP y la configuración de los switches antes de la instalación."),
                _("Usar un tipo de CPU virtual genérico (x86-64-v2-AES / v3) si en el futuro se añaden nodos de otra generación."),
                _("Validar el rendimiento y la alta disponibilidad con las pruebas de aceptación antes de alojar servicios productivos."),
            ])


DEFAULT_TITLE = N_("Migración a nueva plataforma Proxmox VE")


def to_docx(plan, path, charts_dir=None):
    """Genera el Word; si se indica charts_dir, deja allí los PNG (útiles para presentaciones)."""
    return Doc(plan).build(path, charts_dir)


__all__ = ["to_docx", "PBS_VERSIONS"]
