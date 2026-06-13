import io
import os
import urllib.request
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

ALG_DARK   = colors.HexColor("#1B4332")
ALG_MID    = colors.HexColor("#2D6A4F")
ALG_GOLD   = colors.HexColor("#E8B931")
ALG_LIGHT  = colors.HexColor("#D8F3DC")
GRAY_LIGHT = colors.HexColor("#F5F5F3")
GRAY_TEXT  = colors.HexColor("#4A4A4A")
WHITE      = colors.white


def _register_fonts():
    """Register Unicode-capable fonts. Try DejaVu, then FreeSans, then fallback."""
    # 1. Try DejaVu (present on many Linux systems)
    dejavu_paths = [
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf"),
    ]
    for regular, bold, oblique in dejavu_paths:
        if all(os.path.exists(p) for p in [regular, bold, oblique]):
            pdfmetrics.registerFont(TTFont("MainFont",        regular))
            pdfmetrics.registerFont(TTFont("MainFont-Bold",   bold))
            pdfmetrics.registerFont(TTFont("MainFont-Italic", oblique))
            return "MainFont"

    # 2. Try FreeSans (available on Ubuntu/Debian)
    freesans_paths = [
        ("/usr/share/fonts/truetype/freefont/FreeSans.ttf",
         "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
         "/usr/share/fonts/truetype/freefont/FreeSansOblique.ttf"),
    ]
    for regular, bold, oblique in freesans_paths:
        if all(os.path.exists(p) for p in [regular, bold, oblique]):
            pdfmetrics.registerFont(TTFont("MainFont",        regular))
            pdfmetrics.registerFont(TTFont("MainFont-Bold",   bold))
            pdfmetrics.registerFont(TTFont("MainFont-Italic", oblique))
            return "MainFont"

    # 3. Try to download DejaVu at runtime (Streamlit Cloud)
    try:
        font_dir = "/tmp/alg_fonts"
        os.makedirs(font_dir, exist_ok=True)
        base = "https://cdn.jsdelivr.net/npm/dejavu-fonts-ttf@2.37.3/ttf"
        font_files = [
            ("DejaVuSans.ttf",        f"{base}/DejaVuSans.ttf"),
            ("DejaVuSans-Bold.ttf",   f"{base}/DejaVuSans-Bold.ttf"),
            ("DejaVuSans-Oblique.ttf",f"{base}/DejaVuSans-Oblique.ttf"),
        ]
        downloaded = []
        for fname, url in font_files:
            fpath = os.path.join(font_dir, fname)
            if not os.path.exists(fpath):
                urllib.request.urlretrieve(url, fpath)
            downloaded.append(fpath)
        pdfmetrics.registerFont(TTFont("MainFont",        downloaded[0]))
        pdfmetrics.registerFont(TTFont("MainFont-Bold",   downloaded[1]))
        pdfmetrics.registerFont(TTFont("MainFont-Italic", downloaded[2]))
        return "MainFont"
    except Exception:
        pass

    # 4. Fallback to Helvetica (no accents but won't crash)
    return "Helvetica"


FONT_BASE = _register_fonts()
FONT      = FONT_BASE
FONT_BOLD = FONT_BASE + "-Bold" if FONT_BASE != "Helvetica" else "Helvetica-Bold"
FONT_ITAL = FONT_BASE + "-Italic" if FONT_BASE != "Helvetica" else "Helvetica-Oblique"


class NumberedCanvas(canvas.Canvas):
    lang = "pt"  # class-level default, overridden per report

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self._draw_footer(num_pages)
            canvas.Canvas.showPage(self)
        canvas.Canvas.save(self)

    def _draw_footer(self, page_count):
        self.setStrokeColor(ALG_GOLD)
        self.setLineWidth(1.5)
        self.line(1.5*cm, 1.5*cm, A4[0]-1.5*cm, 1.5*cm)
        self.setFillColor(ALG_MID)
        self.setFont(FONT, 8)
        self.drawString(1.5*cm, 1.0*cm,
                        "Algoritimado — Transfer Pricing Intelligence Platform  |  algoritimado.com")
        self.setFillColor(colors.HexColor("#888888"))
        if NumberedCanvas.lang == "pt":
            page_txt = "Página " + str(self._pageNumber) + " de " + str(page_count)
        else:
            page_txt = "Page " + str(self._pageNumber) + " of " + str(page_count)
        self.drawRightString(A4[0]-1.5*cm, 1.0*cm, page_txt)


def _v(val, fallback="—"):
    """Return value or fallback if empty/None."""
    if val is None or str(val).strip() in ("", "—", "None"):
        return fallback
    return str(val).strip()


def _esc_xml(s):
    """Escape XML special chars for ReportLab Paragraph markup."""
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _fmt_mi(v, lang):
    """Format a USD/BRL figure in millions with localized thousands separator."""
    s = "{:,.0f}".format(v / 1e6)
    return s.replace(",", ".") if lang == "pt" else s


def _breakdown_text(bd, lang):
    """One-line audit trail: numerator / denominator = margin (or markup), from
    the same filing. Denominator is revenue for margins, COGS for markup (MCL)."""
    cur = {"USD": "US$", "BRL": "R$"}.get(bd.get("currency", "USD"), "")
    pt = (lang == "pt")
    # kind -> (numerator_pt, numerator_en, denominator_pt, denominator_en)
    labels = {
        "operating": ("Lucro operacional", "Operating income", "Receita", "Revenue"),
        "net":       ("Lucro líquido",     "Net income",       "Receita", "Revenue"),
        "gross":     ("Lucro bruto",       "Gross profit",     "Receita", "Revenue"),
        "ebitda":    ("EBIT + D&A",        "EBIT + D&A",       "Receita", "Revenue"),
        "markup":    ("Lucro bruto",       "Gross profit",     "CMV",     "COGS"),
    }
    nl_pt, nl_en, dl_pt, dl_en = labels.get(bd.get("kind"), ("", "", "Receita", "Revenue"))
    num_lbl = nl_pt if pt else nl_en
    den_lbl = dl_pt if pt else dl_en
    unit    = "mi" if pt else "M"
    margin  = "{:.2f}".format(bd.get("margin", 0))
    if pt:
        margin = margin.replace(".", ",")
    return "{nl} {c} {n} {u} ÷ {dl} {c} {d} {u} = {m}%".format(
        nl=num_lbl, dl=den_lbl, c=cur, u=unit, m=margin,
        n=_fmt_mi(bd["num"], lang), d=_fmt_mi(bd["den"], lang))


def _pct(v, lang):
    """Percentage with 2 decimals, localized decimal separator."""
    s = "{:.2f}".format(v)
    return (s.replace(".", ",") if lang == "pt" else s) + "%"


def _cr_adjustment_text(cr, lang):
    """One-line audit trail for the Anexo II country-risk adjustment:
    (CRP tested − CRP comparable) × capital employed = adjustment, added to
    operating income → margin before → after. Full precision upstream;
    display rounding only (half-up at 2 decimals matches the official table)."""
    cur = {"USD": "US$", "BRL": "R$"}.get(cr.get("currency", "USD"), "")
    unit = "mi" if lang == "pt" else "M"
    ce = "{} {} {}".format(cur, _fmt_mi(cr["capital_employed"], lang), unit)
    adj = "{}{} {} {}".format("+" if cr["adjustment"] >= 0 else "−",
                              cur, _fmt_mi(abs(cr["adjustment"]), lang), unit)
    if lang == "pt":
        return ("Ajuste risco-país (Anexo II): ({} − {}) × capital empregado {} "
                "= {} no lucro operacional → margem {} → {}").format(
            _pct(cr["crp_tested_pct"], lang), _pct(cr["crp_comparable_pct"], lang),
            ce, adj, _pct(cr["margin_before"], lang), _pct(cr["adjusted_margin"], lang))
    return ("Country-risk adj. (Annex II): ({} − {}) × capital employed {} "
            "= {} to operating income → margin {} → {}").format(
        _pct(cr["crp_tested_pct"], lang), _pct(cr["crp_comparable_pct"], lang),
        ce, adj, _pct(cr["margin_before"], lang), _pct(cr["adjusted_margin"], lang))


def generate_report(analysis_data: dict) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=1.8*cm, rightMargin=1.8*cm,
        topMargin=2.0*cm, bottomMargin=2.5*cm,
        title="Relatório de Preços de Transferência — Algoritimado"
    )

    lang = analysis_data.get("language", "pt")
    iqr  = analysis_data.get("iqr_result")
    story = []

    # Styles
    S = {
        "title":   ParagraphStyle("t",  fontName=FONT_BOLD,  fontSize=17, textColor=ALG_DARK,  spaceAfter=6),
        "section": ParagraphStyle("s",  fontName=FONT_BOLD,  fontSize=12, textColor=ALG_DARK,  spaceBefore=12, spaceAfter=6),
        "body":    ParagraphStyle("b",  fontName=FONT,       fontSize=10, textColor=GRAY_TEXT, spaceAfter=4,  leading=15),
        "small":   ParagraphStyle("sm", fontName=FONT,       fontSize=9,  textColor=colors.HexColor("#888888"), spaceAfter=2),
        "al_yes":  ParagraphStyle("ay", fontName=FONT_BOLD,  fontSize=13, textColor=colors.HexColor("#1A6B3C")),
        "al_no":   ParagraphStyle("an", fontName=FONT_BOLD,  fontSize=13, textColor=colors.HexColor("#B91C1C")),
        "disc":    ParagraphStyle("d",  fontName=FONT_ITAL,  fontSize=8,  textColor=colors.HexColor("#888888"), leading=12),
        "hdr":     ParagraphStyle("h",  fontName=FONT_BOLD,  fontSize=20, textColor=WHITE, spaceAfter=0),
        "hdr2":    ParagraphStyle("h2", fontName=FONT,       fontSize=9,  textColor=ALG_LIGHT, spaceAfter=0, alignment=2),
    }

    # ── HEADER ────────────────────────────────────────────────────────────────
    hdr_table = Table([[
        Paragraph("ALGORITIMADO", S["hdr"]),
        Paragraph("Transfer Pricing<br/>Intelligence Platform", S["hdr2"])
    ]], colWidths=[9*cm, 8*cm])
    hdr_table.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,-1), ALG_DARK),
        ("TOPPADDING",    (0,0), (-1,-1), 14),
        ("BOTTOMPADDING", (0,0), (-1,-1), 14),
        ("LEFTPADDING",   (0,0), (0,-1), 14),
        ("RIGHTPADDING",  (-1,0), (-1,-1), 14),
        ("VALIGN",        (0,0), (-1,-1), "MIDDLE"),
    ]))
    story.append(hdr_table)
    story.append(Spacer(1, 0.3*cm))
    story.append(HRFlowable(width="100%", thickness=3, color=ALG_GOLD, spaceAfter=8))

    # ── MASTER FILE (Arquivo Global) — separate deliverable, art. 58 ─────────
    # The Global File is a group-level qualitative document, required for every
    # obligated taxpayer (>= R$15M; art. 57 §1º only waives it below R$15M). It
    # is filed as its OWN attachment at e-CAC, so it gets its own PDF here.
    if analysis_data.get("doc_type") == "master_file":
        _mf_title = ("Arquivo Global (Master File)" if lang == "pt"
                     else "Global File (Master File)")
        story.append(Paragraph(_mf_title, S["title"]))
        story.append(Spacer(1, 0.15*cm))
        _grp = str(analysis_data.get("mf_group") or analysis_data.get("company_name") or "—").strip()
        _date = analysis_data.get("analysis_date", "")
        story.append(Paragraph(
            ("<b>Grupo multinacional:</b> {}  ·  <b>Data:</b> {}  ·  "
             "<b>Legislação:</b> art. 58 da IN RFB 2.161/2023"
             if lang == "pt" else
             "<b>Multinational group:</b> {}  ·  <b>Date:</b> {}  ·  "
             "<b>Legislation:</b> art. 58 of IN RFB 2.161/2023").format(
                _esc_xml(_grp), _esc_xml(str(_date))),
            ParagraphStyle("mfh", fontName=FONT, fontSize=9.5,
                           textColor=colors.HexColor("#555555"), spaceAfter=4)))
        story.append(HRFlowable(width="100%", thickness=0.5,
                                color=colors.HexColor("#DDDDDD"), spaceBefore=4, spaceAfter=10))
        _mf_secs = [
            ("mf_org", "I — Estrutura organizacional",
             "I — Organizational structure",
             "Organograma do grupo multinacional e localização geográfica das entidades.",
             "Organization chart of the multinational group and geographic location of entities."),
            ("mf_activities", "II — Atividades do grupo",
             "II — Group activities",
             "Atividades que mais geram lucro, análise funcional resumida, cadeia de suprimentos "
             "dos 5 maiores produtos/serviços, principais contratos de serviços e reestruturações.",
             "Profit-driving activities, brief functional analysis, supply chain of the 5 largest "
             "products/services, main service contracts, and restructurings."),
            ("mf_intangibles", "III — Intangíveis",
             "III — Intangibles",
             "Estratégia de desenvolvimento/propriedade/exploração, intangíveis relevantes e seus "
             "titulares, contratos, políticas de TP e transferências intragrupo no exercício.",
             "Development/ownership/exploitation strategy, relevant intangibles and owners, "
             "contracts, TP policies, and intra-group transfers in the year."),
            ("mf_financial", "IV — Operações financeiras",
             "IV — Financial operations",
             "Política de financiamento do grupo e entidades que centralizam as funções financeiras.",
             "Group financing policy and entities centralizing financial functions."),
            ("mf_apa", "V — Acordos prévios e rulings",
             "V — Advance agreements and rulings",
             "Lista e descrição de APAs unilaterais, rulings e demais acordos com administrações "
             "tributárias que afetem a alocação de renda entre países.",
             "List and description of unilateral APAs, rulings and other agreements with tax "
             "administrations affecting income allocation between countries."),
            ("mf_financials", "VI — Demonstrações financeiras consolidadas",
             "VI — Consolidated financial statements",
             "Demonstrações financeiras consolidadas mais recentes do grupo (anexar à parte).",
             "Most recent consolidated financial statements of the group (attach separately)."),
        ]
        _any = False
        for _k, _pt, _en, _hint_pt, _hint_en in _mf_secs:
            _val = str(analysis_data.get(_k) or "").strip()
            story.append(Paragraph(
                ("{} (art. 58)".format(_pt) if lang == "pt" else "{} (art. 58)".format(_en)),
                S["section"]))
            if _val:
                _any = True
                story.append(Paragraph(_esc_xml(_val).replace("\n", "<br/>"), S["body"]))
            else:
                story.append(Paragraph(
                    "<i>" + _esc_xml(_hint_pt if lang == "pt" else _hint_en)
                    + (" — a preencher." if lang == "pt" else " — to be completed.") + "</i>",
                    S["small"]))
            story.append(Spacer(1, 0.25*cm))
        story.append(HRFlowable(width="100%", thickness=0.5,
                                color=colors.HexColor("#DDDDDD"), spaceBefore=6, spaceAfter=8))
        _mf_note = ("Documento estruturado conforme o art. 58 da IN RFB 2.161/2023, anexado "
                    "separadamente ao Arquivo Local no Processo Digital do e-CAC. Arquivo Global "
                    "em idioma estrangeiro (exceto inglês/espanhol) deve vir com tradução simples "
                    "para o português (art. 58, §1º). Esta ferramenta não substitui laudo assinado "
                    "por profissional habilitado."
                    if lang == "pt" else
                    "Document structured per art. 58 of IN RFB 2.161/2023, attached separately to "
                    "the Local File in the e-CAC Digital Process. A Global File in a foreign "
                    "language (except English/Spanish) must include a simple Portuguese translation "
                    "(art. 58, §1º). This tool does not replace a report signed by a qualified "
                    "professional.")
        story.append(Paragraph(_mf_note, S["disc"]))
        NumberedCanvas.lang = lang
        doc.build(story, canvasmaker=NumberedCanvas)
        return buf.getvalue()

    # ── TITLE ─────────────────────────────────────────────────────────────────
    title_txt = ("Relatório de Análise de Preços de Transferência"
                 if lang == "pt" else "Transfer Pricing Analysis Report")
    story.append(Paragraph(title_txt, S["title"]))
    story.append(Spacer(1, 0.4*cm))  # ← FIX: prevents table from overlapping title

    # ── METADATA TABLE ────────────────────────────────────────────────────────
    date_str = analysis_data.get("analysis_date", datetime.now().strftime("%d/%m/%Y"))
    def _mp(txt, bold=False):
        """Make table cell paragraph."""
        fn = FONT_BOLD if bold else FONT
        return Paragraph(str(txt), ParagraphStyle("mc", fontName=fn, fontSize=9,
                         textColor=ALG_DARK if bold else GRAY_TEXT, leading=13))

    _l = lambda pt, en: pt if lang == "pt" else en
    _legacy_law_pt = "Lei 9.430/1996 (legado · revogada)"
    _legacy_law_en = "Law 9.430/1996 (legacy · repealed)"
    _current_law   = "Lei 14.596/2023 · IN RFB 2.161/2023"
    _is_legacy = any(x in _v(analysis_data.get("method"), "") for x in ["PCI", "PECEX"])
    _law_value = (_legacy_law_pt if lang == "pt" else _legacy_law_en) if _is_legacy else _current_law
    meta_rows = [
        [_mp(_l("Empresa", "Company"), True),       _mp(_v(analysis_data.get("company_name"))),
         _mp(_l("Data", "Date"), True),              _mp(date_str)],
        [_mp(_l("Transação", "Transaction"), True), _mp(_v(analysis_data.get("transaction_description"))),
         _mp(_l("Método", "Method"), True),          _mp(_v(analysis_data.get("method")))],
        [_mp(_l("Parte Testada", "Tested Party"), True), _mp(_v(analysis_data.get("tested_party_name"))),
         _mp("PLI", True),                            _mp(_v(analysis_data.get("pli")))],
        [_mp(_l("Exercício Fiscal", "Fiscal Year"), True), _mp(_v(analysis_data.get("fiscal_year"))),
         _mp(_l("Legislação", "Legislation"), True), _mp(_law_value)],
    ]
    meta_table = Table(meta_rows, colWidths=[4.5*cm, 5.5*cm, 3.0*cm, 4.0*cm])
    meta_table.setStyle(TableStyle([
        ("FONTSIZE",       (0,0), (-1,-1), 9),
        ("ROWBACKGROUNDS", (0,0), (-1,-1), [GRAY_LIGHT, WHITE]),
        ("GRID",           (0,0), (-1,-1), 0.25, colors.HexColor("#DDDDDD")),
        ("TOPPADDING",     (0,0), (-1,-1), 6),
        ("BOTTOMPADDING",  (0,0), (-1,-1), 6),
        ("LEFTPADDING",    (0,0), (-1,-1), 8),
    ]))
    story.append(meta_table)
    story.append(Spacer(1, 0.5*cm))

    # ── ITEM I — IDENTIFICAÇÃO DAS PARTES RELACIONADAS (art. 61, I) ───────────
    # Identification of the entities in the controlled transaction. Rendered only
    # when supplied — turns the benchmark study into the fileable Local File.
    _grp = str(analysis_data.get("lf_group") or "").strip()
    _tp_cnpj = str(analysis_data.get("lf_tp_cnpj") or "").strip()
    _rp_name = str(analysis_data.get("lf_rp_name") or "").strip()
    _rp_country = str(analysis_data.get("lf_rp_country") or "").strip()
    _rp_taxid = str(analysis_data.get("lf_rp_taxid") or "").strip()
    if any([_grp, _tp_cnpj, _rp_name, _rp_country, _rp_taxid]):
        story.append(Paragraph(
            ("Identificação das Partes Relacionadas (art. 61, I)" if lang == "pt"
             else "Identification of Related Parties (art. 61, I)"), S["section"]))
        _tp_name = _v(analysis_data.get("tested_party_name"), "—")
        _rows = [[
            _mp(_l("Parte", "Party"), True), _mp(_l("Denominação", "Name"), True),
            _mp(_l("País", "Country"), True), _mp(_l("Registro fiscal", "Tax registration"), True)]]
        _rows.append([_mp(_l("Parte testada", "Tested party")), _mp(_tp_name),
                      _mp("Brasil" if lang == "pt" else "Brazil"), _mp(_tp_cnpj or "—")])
        _rows.append([_mp(_l("Parte relacionada", "Related party")), _mp(_rp_name or "—"),
                      _mp(_rp_country or "—"), _mp(_rp_taxid or "—")])
        if _grp:
            _rows.append([_mp(_l("Grupo econômico", "Economic group")), _mp(_grp),
                          _mp("—"), _mp("—")])
        _pt_table = Table(_rows, colWidths=[4.0*cm, 5.5*cm, 3.5*cm, 4.0*cm])
        _pt_table.setStyle(TableStyle([
            ("FONTSIZE", (0,0), (-1,-1), 9),
            ("BACKGROUND", (0,0), (-1,0), ALG_MID),
            ("TEXTCOLOR", (0,0), (-1,0), WHITE),
            ("ROWBACKGROUNDS", (0,1), (-1,-1), [WHITE, GRAY_LIGHT]),
            ("GRID", (0,0), (-1,-1), 0.25, colors.HexColor("#DDDDDD")),
            ("TOPPADDING", (0,0), (-1,-1), 5), ("BOTTOMPADDING", (0,0), (-1,-1), 5),
            ("LEFTPADDING", (0,0), (-1,-1), 6),
        ]))
        story.append(_pt_table)
        story.append(Spacer(1, 0.4*cm))

    # ── ITEM II — CARACTERIZAÇÃO DA TRANSAÇÃO CONTROLADA (art. 61, II) ────────
    _tx_type = str(analysis_data.get("lf_tx_type") or "").strip()
    _tx_value = str(analysis_data.get("lf_tx_value") or "").strip()
    if _tx_type or _tx_value:
        story.append(Paragraph(
            ("Caracterização da Transação Controlada (art. 61, II)" if lang == "pt"
             else "Characterization of the Controlled Transaction (art. 61, II)"), S["section"]))
        _desc = _v(analysis_data.get("transaction_description"), "—")
        _parts = []
        if _tx_type:
            _parts.append(("<b>" + _l("Tipo: ", "Type: ") + "</b>") + _esc_xml(_tx_type))
        _parts.append(("<b>" + _l("Descrição: ", "Description: ") + "</b>") + _esc_xml(_desc))
        if _tx_value:
            _parts.append(("<b>" + _l("Valor no exercício: ", "Value in the year: ") + "</b>")
                          + _esc_xml(_tx_value))
        story.append(Paragraph("  ·  ".join(_parts), S["body"]))
        story.append(Spacer(1, 0.4*cm))

    # ── FUNCTIONAL ANALYSIS (FAR) — only rendered when the user filled it ─────
    _far_map = [
        ("far_functions", "Funções desempenhadas", "Functions performed"),
        ("far_assets",    "Ativos utilizados",     "Assets employed"),
        ("far_risks",     "Riscos assumidos",      "Risks assumed"),
    ]
    far_items = []
    for _key, _pt, _en in _far_map:
        _val = str(analysis_data.get(_key) or "").strip()
        if _val:
            far_items.append((_pt if lang == "pt" else _en, _val))
    if far_items:
        lbl = "Análise Funcional (FAR)" if lang == "pt" else "Functional Analysis (FAR)"
        story.append(Paragraph(lbl, S["section"]))
        if not _is_legacy:
            intro = ("Perfil funcional da parte testada — funções desempenhadas, ativos "
                     "utilizados e riscos economicamente significativos assumidos (arts. 13 "
                     "e 14 da IN RFB 2.161/2023), fundamento da seleção do método (art. 34, I), "
                     "da parte testada (art. 46, §2º) e do indicador PLI (art. 42, §1º)."
                     if lang == "pt" else
                     "Functional profile of the tested party — functions performed, assets "
                     "employed and economically significant risks assumed (arts. 13–14 of "
                     "IN RFB 2.161/2023), the basis for selecting the method (art. 34, I), "
                     "the tested party (art. 46, §2º) and the PLI (art. 42, §1º).")
            story.append(Paragraph(intro, S["small"]))
        for _lbl, _val in far_items:
            _txt = "<b>" + _lbl + ":</b> " + _esc_xml(_val).replace("\n", "<br/>")
            story.append(Paragraph(_txt, S["body"]))
        story.append(Spacer(1, 0.4*cm))

    # ── COMPLIANCE RESULT ─────────────────────────────────────────────────────
    if iqr and iqr.tested_party_value is not None:
        lbl = "Resultado de Conformidade" if lang == "pt" else "Compliance Result"
        story.append(Paragraph(lbl, S["section"]))

        ok = iqr.is_arms_length
        bg  = colors.HexColor("#DCFCE7") if ok else colors.HexColor("#FEE2E2")
        bdr = colors.HexColor("#16A34A") if ok else colors.HexColor("#DC2626")
        if lang == "pt":
            txt = ("ARM'S LENGTH — Dentro do intervalo interquartil (Q1–Q3)"
                   if ok else
                   "AJUSTE NECESSÁRIO — Fora do intervalo interquartil (Q1–Q3)")
        else:
            txt = ("ARM'S LENGTH — Within the interquartile range (Q1–Q3)"
                   if ok else
                   "ADJUSTMENT REQUIRED — Outside the interquartile range (Q1–Q3)")

        st_table = Table([[Paragraph(txt, S["al_yes"] if ok else S["al_no"])]],
                          colWidths=[17*cm])
        st_table.setStyle(TableStyle([
            ("BACKGROUND",    (0,0), (-1,-1), bg),
            ("LINEBEFORE",    (0,0), (0,-1), 4, bdr),
            ("LINEAFTER",     (0,0), (0,-1), 4, bdr),
            ("LINEABOVE",     (0,0), (-1,0), 4, bdr),
            ("LINEBELOW",     (0,-1),(-1,-1),4, bdr),
            ("TOPPADDING",    (0,0), (-1,-1), 12),
            ("BOTTOMPADDING", (0,0), (-1,-1), 12),
            ("LEFTPADDING",   (0,0), (-1,-1), 14),
        ]))
        story.append(st_table)
        story.append(Spacer(1, 0.4*cm))

    # ── IQR TABLE ─────────────────────────────────────────────────────────────
    if iqr:
        lbl = "Intervalo Interquartil (IQR)" if lang == "pt" else "Interquartile Range (IQR)"
        story.append(Paragraph(lbl, S["section"]))

        if lang == "pt":
            rows = [
                ["Indicador", "Valor", "Descrição"],
                ["Q1 — 1º Quartil", "{:.4f}".format(iqr.q1),
                 "Limite inferior do intervalo arm's length"],
                ["Q2 — Mediana", "{:.4f}".format(iqr.median),
                 "Ponto médio do conjunto de comparáveis"],
                ["Q3 — 3º Quartil", "{:.4f}".format(iqr.q3),
                 "Limite superior do intervalo arm's length"],
                ["IQR (Q3 – Q1)", "{:.4f}".format(iqr.q3 - iqr.q1),
                 "Amplitude do intervalo interquartil"],
            ]
        else:
            rows = [
                ["Indicator", "Value", "Description"],
                ["Q1 — 1st Quartile", "{:.4f}".format(iqr.q1), "Lower bound of arm's length range"],
                ["Q2 — Median",       "{:.4f}".format(iqr.median), "Midpoint of comparable set"],
                ["Q3 — 3rd Quartile", "{:.4f}".format(iqr.q3), "Upper bound of arm's length range"],
                ["IQR (Q3 – Q1)",     "{:.4f}".format(iqr.q3-iqr.q1), "Interquartile range width"],
            ]

        if iqr.tested_party_value is not None:
            tp_name = _v(analysis_data.get("tested_party_name"), "Parte Testada")
            lbl_tp_text = ("Parte Testada: " if lang == "pt" else "Tested Party: ") + tp_name
            # Wrap inside Paragraph so long tested-party names (e.g. "ALGORITIMADO
            # BRASIL LTDA") don't overflow the 5.5cm column and overlap the value
            # column to its right.
            _tp_style = ParagraphStyle("tp", fontName=FONT_BOLD, fontSize=9.5,
                                       textColor=ALG_DARK, leading=12)
            lbl_tp = Paragraph(lbl_tp_text, _tp_style)
            rows.append([lbl_tp, "{:.4f}".format(iqr.tested_party_value), iqr.compliance_status(lang)])

        iqr_table = Table(rows, colWidths=[5.5*cm, 3*cm, 8.5*cm])
        ts = TableStyle([
            ("FONTNAME",       (0,0), (-1,0), FONT_BOLD),
            ("FONTNAME",       (0,1), (-1,-1), FONT),
            ("FONTSIZE",       (0,0), (-1,-1), 9.5),
            ("BACKGROUND",     (0,0), (-1,0), ALG_DARK),
            ("TEXTCOLOR",      (0,0), (-1,0), WHITE),
            ("ROWBACKGROUNDS", (0,1), (-1,-1), [WHITE, GRAY_LIGHT]),
            ("GRID",           (0,0), (-1,-1), 0.25, colors.HexColor("#DDDDDD")),
            ("ALIGN",          (1,0), (1,-1), "CENTER"),
            ("TOPPADDING",     (0,0), (-1,-1), 7),
            ("BOTTOMPADDING",  (0,0), (-1,-1), 7),
            ("LEFTPADDING",    (0,0), (-1,-1), 8),
        ])
        if iqr.tested_party_value is not None:
            tp_row = len(rows) - 1
            bg = colors.HexColor("#DCFCE7") if iqr.is_arms_length else colors.HexColor("#FEE2E2")
            ts.add("BACKGROUND", (0, tp_row), (-1, tp_row), bg)
            ts.add("FONTNAME",   (0, tp_row), (-1, tp_row), FONT_BOLD)
        iqr_table.setStyle(ts)
        story.append(iqr_table)
        story.append(Spacer(1, 0.5*cm))

    # ── COMPARABLES TABLE ─────────────────────────────────────────────────────
    comparables = analysis_data.get("comparables", [])
    if comparables:
        lbl = "Conjunto de Comparáveis" if lang == "pt" else "Comparable Set"
        story.append(Paragraph(lbl, S["section"]))
        note = ("Comparáveis selecionados com base em análise funcional (FAR) conforme "
                "IN RFB 2.161/2023 e Diretrizes OCDE."
                if lang == "pt" else
                "Comparables selected based on functional analysis (FAR) per "
                "IN RFB 2.161/2023 and OECD TP Guidelines.")
        story.append(Paragraph(note, S["small"]))
        story.append(Spacer(1, 0.2*cm))

        pli_full = _v(analysis_data.get("pli"), "PLI")
        # Shorten PLI label for table header — use first part only
        pli_lbl = pli_full.split("/")[0].strip() if "/" in pli_full else pli_full
        if len(pli_lbl) > 22:
            pli_lbl = pli_lbl[:22] + "..."
        h_company = "Empresa / Company" if lang == "pt" else "Company"
        h_source  = "Fonte / Source"    if lang == "pt" else "Source"
        def _hp(txt):
            return Paragraph(txt, ParagraphStyle("ch", fontName=FONT_BOLD, fontSize=9,
                             textColor=WHITE, leading=12))
        _cell_style = ParagraphStyle("cc", fontName=FONT, fontSize=9,
                                     textColor=GRAY_TEXT, leading=11)
        comp_rows = [[_hp("#"), _hp(h_company), _hp(pli_lbl), _hp(h_source)]]
        for i, c in enumerate(comparables, 1):
            # Audit trail: when the fetcher provided a primary-source URL (SEC
            # EDGAR today), render the Source cell as a clickable link to the
            # official filing. Manual entries and CVM rows (no clean permalink)
            # stay as plain text. '&' must be XML-escaped for ReportLab.
            src_txt = c.get("source", "SEC EDGAR / CVM")
            src_url = c.get("source_url") or ""
            if src_url:
                # Filing label depends on the source: SEC = 10-K/20-F, CVM = DFP.
                _up = src_txt.upper()
                _suffix = " (10-K/20-F)" if "SEC" in _up else (" (DFP)" if "CVM" in _up else "")
                _u = src_url.replace("&", "&amp;")
                src_cell = Paragraph(
                    '<a href="{}" color="#1d4ed8"><u>{}{}</u></a>'.format(
                        _u, _esc_xml(src_txt), _suffix),
                    _cell_style)
            else:
                src_cell = Paragraph(_esc_xml(src_txt), _cell_style)
            # Company name, plus a small 'show the math' line underneath when the
            # comparable carries a breakdown (numerator / revenue = margin, from
            # the same filing). Manual/CVM rows have none → just the name.
            name_html = _esc_xml(c.get("name", "—"))
            bd = c.get("breakdown")
            if isinstance(bd, dict):
                name_html += ('<br/><font size="6.5" color="#8A8A8A">'
                              + _esc_xml(_breakdown_text(bd, lang)) + '</font>')
            # Country-risk adjustment line (Anexo II): show the full math —
            # differential × capital employed = adjustment, margin before → after.
            cr = c.get("cr_adjustment")
            if isinstance(cr, dict):
                name_html += ('<br/><font size="6.5" color="#1B4332">'
                              + _esc_xml(_cr_adjustment_text(cr, lang)) + '</font>')
            comp_rows.append([
                str(i),
                # Wrap long names (e.g. "LIFEMED INDUSTRIAL DE EQUIP. E ART.
                # MEDICOS E HOSP. S.A.") in a Paragraph so they break inside
                # the 7cm Company column instead of overflowing into the
                # value column on the right.
                Paragraph(name_html, _cell_style),
                "{:.4f}".format(c.get("value", 0)),
                src_cell,
            ])

        comp_table = Table(comp_rows, colWidths=[0.8*cm, 7.0*cm, 3.2*cm, 6.0*cm])
        comp_table.setStyle(TableStyle([
            ("FONTNAME",       (0,0), (-1,0), FONT_BOLD),
            ("FONTNAME",       (0,1), (-1,-1), FONT),
            ("FONTSIZE",       (0,0), (-1,-1), 9),
            ("BACKGROUND",     (0,0), (-1,0), ALG_MID),
            ("TEXTCOLOR",      (0,0), (-1,0), WHITE),
            ("ROWBACKGROUNDS", (0,1), (-1,-1), [WHITE, GRAY_LIGHT]),
            ("GRID",           (0,0), (-1,-1), 0.25, colors.HexColor("#DDDDDD")),
            ("ALIGN",          (0,0), (0,-1), "CENTER"),
            ("ALIGN",          (2,0), (2,-1), "CENTER"),
            ("TOPPADDING",     (0,0), (-1,-1), 6),
            ("BOTTOMPADDING",  (0,0), (-1,-1), 6),
            ("LEFTPADDING",    (0,0), (-1,-1), 6),
        ]))
        story.append(comp_table)

        # Foreign-comparables note. Two states: adjustment applied (describe the
        # method, premiums and source — Anexo II) or not applied (flag honestly
        # that art. 23 expects adjustments for material differences).
        _has_foreign = any("SEC EDGAR" in str(c.get("source", "")) for c in comparables)
        _cr_meta = analysis_data.get("country_risk") or {}
        _n_adj = _cr_meta.get("n_adjusted", 0)
        if _has_foreign and _n_adj:
            story.append(Spacer(1, 0.15*cm))
            _src = str(_cr_meta.get("source") or "").strip()
            _crp_t = _pct(_cr_meta.get("crp_tested", 0), lang)
            _crp_c = _pct(_cr_meta.get("crp_comp", 0), lang)
            _diff = _pct(_cr_meta.get("crp_tested", 0) - _cr_meta.get("crp_comp", 0), lang)
            if lang == "pt":
                fnote = ("Nota: ajuste de comparabilidade por risco-país aplicado a {} "
                         "comparável(is) estrangeiro(s) (SEC EDGAR), conforme orientação do "
                         "Anexo II da IN RFB 2.161/2023 (art. 23, §4º): diferencial de prêmio "
                         "de risco-país ({} − {}) multiplicado pelo capital empregado e somado "
                         "ao lucro operacional do comparável. Definição operacional adotada: "
                         "capital empregado = imobilizado líquido (PP&E) + ativo circulante − "
                         "passivo circulante, do mesmo filing — a norma não define 'ativos "
                         "fixos operacionais'; intangíveis operacionais e ativos de direito "
                         "de uso não foram incluídos."
                         ).format(_n_adj, _crp_t, _crp_c)
                if _src:
                    fnote += " Fonte dos prêmios: {} (a RFB não prescreve fonte).".format(_src)
                if _cr_meta.get("n_foreign_skipped"):
                    fnote += (" {} comparável(is) da SEC sem capital empregado positivo "
                              "disponível no filing permanecem sem ajuste — avaliar se devem "
                              "permanecer no conjunto ou ser excluídos (art. 32, IV da IN; "
                              "OCDE TPG 3.51)."
                              ).format(_cr_meta["n_foreign_skipped"])
                _just = (_cr_meta.get("justification") or "").strip()
                if not _just:
                    _just = ("A parte testada opera no mercado brasileiro (prêmio de "
                             "risco-país de {}), enquanto os comparáveis ajustados operam em "
                             "mercado com prêmio de {}. A diferença de {} nas circunstâncias "
                             "econômicas é materialmente relevante para margens operacionais "
                             "e não decorre de funções, ativos ou riscos das partes. O ajuste "
                             "elimina especificamente essa diferença, conforme a metodologia "
                             "do Anexo II, e por isso espera-se que aumente a confiabilidade "
                             "da comparação (art. 32, I, V e §1º, da IN RFB 2.161/2023)."
                             ).format(_crp_t, _crp_c, _diff)
                just_lbl = "Justificativa do ajuste (art. 32): "
            else:
                fnote = ("Note: country-risk comparability adjustment applied to {} foreign "
                         "comparable(s) (SEC EDGAR) per the guidance in Annex II of IN RFB "
                         "2.161/2023 (art. 23, §4º): country-risk premium differential "
                         "({} − {}) multiplied by capital employed and added to the "
                         "comparable's operating income. Operational definition adopted: "
                         "capital employed = net PP&E + current assets − current liabilities, "
                         "from the same filing — the rule does not define 'operating fixed "
                         "assets'; operating intangibles and right-of-use assets were not "
                         "included."
                         ).format(_n_adj, _crp_t, _crp_c)
                if _src:
                    fnote += " Premium source: {} (RFB does not prescribe a source).".format(_src)
                if _cr_meta.get("n_foreign_skipped"):
                    fnote += (" {} SEC comparable(s) without positive capital employed "
                              "available in the filing remain unadjusted — assess whether "
                              "they should remain in the set or be excluded (art. 32, IV; "
                              "OECD TPG 3.51)."
                              ).format(_cr_meta["n_foreign_skipped"])
                _just = (_cr_meta.get("justification") or "").strip()
                if not _just:
                    _just = ("The tested party operates in the Brazilian market "
                             "(country-risk premium of {}), while the adjusted comparables "
                             "operate in a market with a premium of {}. The {} difference in "
                             "economic circumstances is materially relevant to operating "
                             "margins and does not derive from the parties' functions, assets "
                             "or risks. The adjustment specifically eliminates this "
                             "difference, per the Annex II methodology, and is therefore "
                             "expected to increase the reliability of the comparison "
                             "(art. 32, I, V and §1º, IN RFB 2.161/2023)."
                             ).format(_crp_t, _crp_c, _diff)
                just_lbl = "Adjustment rationale (art. 32): "
            story.append(Paragraph(_esc_xml(fnote), S["small"]))
            story.append(Spacer(1, 0.1*cm))
            story.append(Paragraph(
                "<b>" + _esc_xml(just_lbl) + "</b>" + _esc_xml(_just), S["small"]))
        elif _has_foreign:
            story.append(Spacer(1, 0.15*cm))
            fnote = ("Nota: o conjunto inclui comparáveis estrangeiros (SEC EDGAR — empresas "
                     "listadas nos EUA). Nenhum ajuste de comparabilidade por risco-país foi "
                     "aplicado. O art. 23 da IN RFB 2.161/2023 admite comparáveis estrangeiros "
                     "desde que realizados ajustes razoavelmente precisos para diferenças "
                     "materiais; avaliar a materialidade da diferença de risco-país "
                     "(orientação no Anexo II da IN)."
                     if lang == "pt" else
                     "Note: the set includes foreign comparables (SEC EDGAR — US-listed "
                     "companies). No country-risk comparability adjustment was applied. "
                     "Art. 23 of IN RFB 2.161/2023 allows foreign comparables provided "
                     "reasonably accurate adjustments are made for material differences; "
                     "assess the materiality of the country-risk difference (guidance in "
                     "Annex II of the IN).")
            story.append(Paragraph(fnote, S["small"]))
        story.append(Spacer(1, 0.5*cm))

    # ── ITEM VI — AJUSTES DE FIM DE EXERCÍCIO (art. 61, VI) ──────────────────
    _adj_type = str(analysis_data.get("lf_adj_type") or "").strip()
    _adj_value = str(analysis_data.get("lf_adj_value") or "").strip()
    _adj_note = str(analysis_data.get("lf_adj_note") or "").strip()
    _adj_is_none = _adj_type in ("Nenhum ajuste realizado", "No adjustment made")
    if _adj_type and (not _adj_is_none or _adj_value or _adj_note):
        story.append(Paragraph(
            ("Ajustes de Fim de Exercício (art. 61, VI)" if lang == "pt"
             else "Year-end Adjustments (art. 61, VI)"), S["section"]))
        _atxt = ("<b>" + _l("Ajuste realizado: ", "Adjustment made: ") + "</b>") + _esc_xml(_adj_type)
        if _adj_value:
            _atxt += "  ·  <b>" + _l("Valor: ", "Value: ") + "</b>" + _esc_xml(_adj_value)
        if _adj_note:
            _atxt += "<br/>" + _esc_xml(_adj_note)
        story.append(Paragraph(_atxt, S["body"]))
        story.append(Spacer(1, 0.4*cm))
    elif _adj_is_none:
        story.append(Paragraph(
            ("Ajustes de Fim de Exercício (art. 61, VI)" if lang == "pt"
             else "Year-end Adjustments (art. 61, VI)"), S["section"]))
        story.append(Paragraph(
            ("Não foram realizados ajustes espontâneos ou compensatórios no encerramento "
             "do exercício." if lang == "pt"
             else "No spontaneous or compensating adjustments were made at year-end."),
            S["body"]))
        story.append(Spacer(1, 0.4*cm))

    # ── METHODOLOGY ───────────────────────────────────────────────────────────
    story.append(HRFlowable(width="100%", thickness=0.5,
                             color=colors.HexColor("#DDDDDD"), spaceBefore=8, spaceAfter=8))
    lbl = "Nota Metodológica" if lang == "pt" else "Methodology Note"
    story.append(Paragraph(lbl, S["section"]))
    method = _v(analysis_data.get("method"), "MLT (TNMM)")
    is_legacy = any(x in method for x in ["PCI", "PECEX"])
    if lang == "pt":
        if is_legacy:
            note = ("Esta análise foi conduzida utilizando o método <b>" + method + "</b>, "
                    "conforme Lei 9.430/1996 (revogada pela Lei 14.596/2023 — aplicável apenas a exercícios fiscais até 2023). "
                    "O intervalo arm's length foi determinado pelo IQR após análise FAR. "
                    "Esta ferramenta não substitui laudo assinado por profissional habilitado.")
        else:
            note = ("Esta análise foi conduzida utilizando o método <b>" + method + "</b>, "
                    "conforme Lei 14.596/2023 e IN RFB 2.161/2023, alinhada às Diretrizes OCDE. "
                    "O intervalo arm's length foi determinado pelo IQR após análise FAR. "
                    "Esta ferramenta não substitui laudo assinado por profissional habilitado.")
        disc = ("AVISO: Este relatório foi gerado pela plataforma Algoritimado para fins "
                "informativos. Não constitui parecer jurídico ou laudo de preços de transferência.")
    else:
        if is_legacy:
            note = ("This analysis was conducted using the <b>" + method + "</b> method, "
                    "per Brazilian Law 9.430/1996 (repealed by Law 14.596/2023 — applicable only to fiscal years through 2023). "
                    "The arm's length range was determined using the IQR after FAR analysis. "
                    "This tool does not replace a report signed by a qualified professional.")
        else:
            note = ("This analysis was conducted using the <b>" + method + "</b> method, "
                    "per Brazilian Law 14.596/2023 and IN RFB 2.161/2023, aligned with OECD Guidelines. "
                    "The arm's length range was determined using the IQR after FAR analysis. "
                    "This tool does not replace a report signed by a qualified professional.")
        disc = ("DISCLAIMER: This report was generated by the Algoritimado platform for "
                "informational purposes only. It does not constitute legal advice or a "
                "formal transfer pricing study.")
    story.append(Paragraph(note, S["body"]))

    # Art. 61 coverage map — only for the current regime, and only when the user
    # supplied the identification items (i.e. is using the report as a fileable
    # Local File rather than a standalone benchmark study).
    _has_lf = any(str(analysis_data.get(k) or "").strip() for k in
                  ("lf_group", "lf_tp_cnpj", "lf_rp_name", "lf_rp_country",
                   "lf_rp_taxid", "lf_tx_type", "lf_tx_value"))
    if _has_lf and not is_legacy:
        cov = (("Cobertura do Arquivo Local simplificado (art. 61 da IN RFB 2.161/2023): "
                "I) identificação das partes; II) caracterização da transação; III) método; "
                "IV) comparáveis e intervalos; V) justificativa do método e dos comparáveis "
                "(análise funcional); VI) ajustes de fim de exercício. Este documento pode ser "
                "anexado ao Processo Digital no e-CAC; contratos de suporte (art. 38, §7º) e "
                "Arquivo Global (Master File) devem ser anexados separadamente quando exigidos."
                if lang == "pt" else
                "Simplified Local File coverage (art. 61, IN RFB 2.161/2023): "
                "I) identification of parties; II) characterization of the transaction; "
                "III) method; IV) comparables and ranges; V) justification of method and "
                "comparables (functional analysis); VI) year-end adjustments. This document may "
                "be attached to the e-CAC Digital Process; supporting contracts (art. 38, §7º) "
                "and the Master File must be attached separately when required."))
        story.append(Spacer(1, 0.2*cm))
        story.append(Paragraph(cov, S["small"]))

    story.append(Spacer(1, 0.3*cm))
    story.append(Paragraph(disc, S["disc"]))

    NumberedCanvas.lang = lang
    doc.build(story, canvasmaker=NumberedCanvas)
    return buf.getvalue()
