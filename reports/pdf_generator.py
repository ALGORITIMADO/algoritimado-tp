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

    meta_rows = [
        [_mp("Empresa / Company", True),      _mp(_v(analysis_data.get("company_name"))),
         _mp("Data / Date", True),             _mp(date_str)],
        [_mp("Transação / Transaction", True), _mp(_v(analysis_data.get("transaction_description"))),
         _mp("Método / Method", True),         _mp(_v(analysis_data.get("method")))],
        [_mp("Parte Testada / Tested Party", True), _mp(_v(analysis_data.get("tested_party_name"))),
         _mp("PLI", True),                     _mp(_v(analysis_data.get("pli")))],
        [_mp("Exercício Fiscal / Fiscal Year", True), _mp(_v(analysis_data.get("fiscal_year"))),
         _mp("Legislação", True),              _mp("Lei 14.596/2023 · IN RFB 2.161/2023")],
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
            lbl_tp = ("Parte Testada: " if lang == "pt" else "Tested Party: ") + tp_name
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
        comp_rows = [[_hp("#"), _hp(h_company), _hp(pli_lbl), _hp(h_source)]]
        for i, c in enumerate(comparables, 1):
            comp_rows.append([
                str(i),
                c.get("name", "—"),
                "{:.4f}".format(c.get("value", 0)),
                c.get("source", "SEC EDGAR / CVM"),
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
        story.append(Spacer(1, 0.5*cm))

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
    story.append(Spacer(1, 0.3*cm))
    story.append(Paragraph(disc, S["disc"]))

    NumberedCanvas.lang = lang
    doc.build(story, canvasmaker=NumberedCanvas)
    return buf.getvalue()
