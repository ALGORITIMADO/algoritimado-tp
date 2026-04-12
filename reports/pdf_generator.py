import io
import os
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
    paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf",
    ]
    for p in paths:
        if not os.path.exists(p):
            return False
    pdfmetrics.registerFont(TTFont("DejaVuSans", paths[0]))
    pdfmetrics.registerFont(TTFont("DejaVuSans-Bold", paths[1]))
    pdfmetrics.registerFont(TTFont("DejaVuSans-Oblique", paths[2]))
    return True

HAS_DEJAVU  = _register_fonts()
FONT        = "DejaVuSans" if HAS_DEJAVU else "Helvetica"
FONT_BOLD   = "DejaVuSans-Bold" if HAS_DEJAVU else "Helvetica-Bold"
FONT_ITALIC = "DejaVuSans-Oblique" if HAS_DEJAVU else "Helvetica-Oblique"


class NumberedCanvas(canvas.Canvas):
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
            self.draw_page_number(num_pages)
            canvas.Canvas.showPage(self)
        canvas.Canvas.save(self)

    def draw_page_number(self, page_count):
        self.setFillColor(colors.HexColor("#888888"))
        self.setFont(FONT, 8)
        self.drawRightString(A4[0] - 1.5 * cm, 1 * cm,
                             "Page " + str(self._pageNumber) + " of " + str(page_count))
        self.setStrokeColor(ALG_GOLD)
        self.setLineWidth(1.5)
        self.line(1.5 * cm, 1.5 * cm, A4[0] - 1.5 * cm, 1.5 * cm)
        self.setFillColor(ALG_MID)
        self.setFont(FONT, 8)
        self.drawString(1.5 * cm, 1 * cm,
                        "Algoritimado - Transfer Pricing Intelligence Platform | algoritimado.com")


def generate_report(analysis_data):
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=1.8 * cm, rightMargin=1.8 * cm,
        topMargin=2.2 * cm, bottomMargin=2.5 * cm,
        title="Transfer Pricing Analysis Report - Algoritimado"
    )

    lang = analysis_data.get("language", "pt")
    iqr  = analysis_data.get("iqr_result")
    story = []

    S_TITLE = ParagraphStyle("title", fontName=FONT_BOLD, fontSize=18,
                              textColor=ALG_DARK, spaceAfter=4)
    S_SECTION = ParagraphStyle("section", fontName=FONT_BOLD, fontSize=12,
                                textColor=ALG_DARK, spaceBefore=14, spaceAfter=6)
    S_BODY = ParagraphStyle("body", fontName=FONT, fontSize=10,
                             textColor=GRAY_TEXT, spaceAfter=4, leading=15)
    S_SMALL = ParagraphStyle("small", fontName=FONT, fontSize=9,
                              textColor=colors.HexColor("#888888"), spaceAfter=2)
    S_AL_YES = ParagraphStyle("al_yes", fontName=FONT_BOLD, fontSize=13,
                               textColor=colors.HexColor("#1A6B3C"))
    S_AL_NO  = ParagraphStyle("al_no", fontName=FONT_BOLD, fontSize=13,
                               textColor=colors.HexColor("#B91C1C"))
    S_DISC = ParagraphStyle("disc", fontName=FONT_ITALIC, fontSize=8,
                             textColor=colors.HexColor("#888888"), leading=12)

    # Header
    hdr_data = [[
        Paragraph("ALGORITIMADO",
                  ParagraphStyle("hdr", fontName=FONT_BOLD, fontSize=20,
                                 textColor=WHITE, spaceAfter=0)),
        Paragraph("Transfer Pricing<br/>Intelligence Platform",
                  ParagraphStyle("hdr2", fontName=FONT, fontSize=9,
                                 textColor=ALG_LIGHT, spaceAfter=0, alignment=2))
    ]]
    hdr_table = Table(hdr_data, colWidths=[9 * cm, 8 * cm])
    hdr_table.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), ALG_DARK),
        ("TOPPADDING",    (0, 0), (-1, -1), 14),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 14),
        ("LEFTPADDING",   (0, 0), (0, -1), 14),
        ("RIGHTPADDING",  (-1, 0), (-1, -1), 14),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(hdr_table)
    story.append(Spacer(1, 0.4 * cm))
    story.append(HRFlowable(width="100%", thickness=3, color=ALG_GOLD,
                             spaceAfter=10, spaceBefore=0))

    if lang == "pt":
        story.append(Paragraph("Relatorio de Analise de Precos de Transferencia", S_TITLE))
    else:
        story.append(Paragraph("Transfer Pricing Analysis Report", S_TITLE))

    # Metadata
    date_str = analysis_data.get("analysis_date", datetime.now().strftime("%d/%m/%Y"))
    meta_rows = [
        ["Empresa / Company", analysis_data.get("company_name", "-"),
         "Data / Date", date_str],
        ["Transacao / Transaction", analysis_data.get("transaction_description", "-"),
         "Metodo / Method", analysis_data.get("method", "-")],
        ["Parte Testada / Tested Party", analysis_data.get("tested_party_name", "-"),
         "PLI", analysis_data.get("pli", "-")],
        ["Exercicio Fiscal / Fiscal Year", analysis_data.get("fiscal_year", "-"),
         "Legislacao", "Lei 14.596/2023 - IN RFB 2.161/2023"],
    ]
    meta_table = Table(meta_rows, colWidths=[4.5 * cm, 5.5 * cm, 3.5 * cm, 4.5 * cm])
    meta_table.setStyle(TableStyle([
        ("FONTNAME",      (0, 0), (-1, -1), FONT),
        ("FONTNAME",      (0, 0), (0, -1), FONT_BOLD),
        ("FONTNAME",      (2, 0), (2, -1), FONT_BOLD),
        ("FONTSIZE",      (0, 0), (-1, -1), 9),
        ("TEXTCOLOR",     (0, 0), (-1, -1), GRAY_TEXT),
        ("TEXTCOLOR",     (0, 0), (0, -1), ALG_DARK),
        ("TEXTCOLOR",     (2, 0), (2, -1), ALG_DARK),
        ("ROWBACKGROUNDS",(0, 0), (-1, -1), [GRAY_LIGHT, WHITE]),
        ("GRID",          (0, 0), (-1, -1), 0.25, colors.HexColor("#DDDDDD")),
        ("TOPPADDING",    (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING",   (0, 0), (-1, -1), 8),
    ]))
    story.append(meta_table)
    story.append(Spacer(1, 0.5 * cm))

    # Compliance result
    if iqr and iqr.tested_party_value is not None:
        lbl = "Resultado de Conformidade" if lang == "pt" else "Compliance Result"
        story.append(Paragraph(lbl, S_SECTION))

        status_color  = colors.HexColor("#DCFCE7") if iqr.is_arms_length else colors.HexColor("#FEE2E2")
        border_color  = colors.HexColor("#16A34A") if iqr.is_arms_length else colors.HexColor("#DC2626")
        if lang == "pt":
            status_text = ("TRANSACAO ARM'S LENGTH - Dentro do intervalo interquartil"
                           if iqr.is_arms_length else
                           "AJUSTE NECESSARIO - Fora do intervalo interquartil")
        else:
            status_text = ("ARM'S LENGTH - Within the interquartile range"
                           if iqr.is_arms_length else
                           "ADJUSTMENT REQUIRED - Outside the interquartile range")

        s_style = S_AL_YES if iqr.is_arms_length else S_AL_NO
        s_table = Table([[Paragraph(status_text, s_style)]], colWidths=[17 * cm])
        s_table.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, -1), status_color),
            ("LINEAFTER",     (0, 0), (0, -1), 3, border_color),
            ("LINEBEFORE",    (0, 0), (0, -1), 3, border_color),
            ("LINEABOVE",     (0, 0), (-1, 0), 3, border_color),
            ("LINEBELOW",     (0, -1), (-1, -1), 3, border_color),
            ("TOPPADDING",    (0, 0), (-1, -1), 12),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
            ("LEFTPADDING",   (0, 0), (-1, -1), 14),
        ]))
        story.append(s_table)
        story.append(Spacer(1, 0.4 * cm))

    # IQR table
    if iqr:
        lbl = "Intervalo Interquartil (IQR)" if lang == "pt" else "Interquartile Range (IQR)"
        story.append(Paragraph(lbl, S_SECTION))

        if lang == "pt":
            iqr_rows = [
                ["Indicador", "Valor", "Descricao"],
                ["Q1 - 1o Quartil", "{:.4f}".format(iqr.q1), "Limite inferior do intervalo arm's length"],
                ["Q2 - Mediana",    "{:.4f}".format(iqr.median), "Ponto medio do conjunto de comparaveis"],
                ["Q3 - 3o Quartil", "{:.4f}".format(iqr.q3), "Limite superior do intervalo arm's length"],
                ["IQR (Q3 - Q1)",   "{:.4f}".format(iqr.q3 - iqr.q1), "Amplitude do intervalo interquartil"],
            ]
        else:
            iqr_rows = [
                ["Indicator", "Value", "Description"],
                ["Q1 - 1st Quartile", "{:.4f}".format(iqr.q1), "Lower bound of arm's length range"],
                ["Q2 - Median",       "{:.4f}".format(iqr.median), "Midpoint of comparable set"],
                ["Q3 - 3rd Quartile", "{:.4f}".format(iqr.q3), "Upper bound of arm's length range"],
                ["IQR (Q3 - Q1)",     "{:.4f}".format(iqr.q3 - iqr.q1), "Interquartile range width"],
            ]

        if iqr.tested_party_value is not None:
            tp_name = analysis_data.get("tested_party_name", "Tested Party")
            iqr_rows.append([
                "Parte Testada: " + tp_name if lang == "pt" else "Tested Party: " + tp_name,
                "{:.4f}".format(iqr.tested_party_value),
                iqr.compliance_status()
            ])

        iqr_table = Table(iqr_rows, colWidths=[5.5 * cm, 3 * cm, 8.5 * cm])
        ts = TableStyle([
            ("FONTNAME",      (0, 0), (-1, 0), FONT_BOLD),
            ("FONTNAME",      (0, 1), (-1, -1), FONT),
            ("FONTSIZE",      (0, 0), (-1, -1), 9.5),
            ("BACKGROUND",    (0, 0), (-1, 0), ALG_DARK),
            ("TEXTCOLOR",     (0, 0), (-1, 0), WHITE),
            ("ROWBACKGROUNDS",(0, 1), (-1, -1), [WHITE, GRAY_LIGHT]),
            ("GRID",          (0, 0), (-1, -1), 0.25, colors.HexColor("#DDDDDD")),
            ("ALIGN",         (1, 0), (1, -1), "CENTER"),
            ("TOPPADDING",    (0, 0), (-1, -1), 7),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ("LEFTPADDING",   (0, 0), (-1, -1), 8),
        ])
        if iqr.tested_party_value is not None:
            tp_row = len(iqr_rows) - 1
            bg = colors.HexColor("#DCFCE7") if iqr.is_arms_length else colors.HexColor("#FEE2E2")
            ts.add("BACKGROUND", (0, tp_row), (-1, tp_row), bg)
            ts.add("FONTNAME",   (0, tp_row), (-1, tp_row), FONT_BOLD)
        iqr_table.setStyle(ts)
        story.append(iqr_table)
        story.append(Spacer(1, 0.5 * cm))

    # Comparables table
    comparables = analysis_data.get("comparables", [])
    if comparables:
        lbl = "Conjunto de Comparaveis" if lang == "pt" else "Comparable Set"
        story.append(Paragraph(lbl, S_SECTION))
        note = ("Comparaveis selecionados com base em analise FAR conforme IN RFB 2.161/2023 e Diretrizes OCDE."
                if lang == "pt" else
                "Comparables selected based on FAR analysis per IN RFB 2.161/2023 and OECD TP Guidelines.")
        story.append(Paragraph(note, S_SMALL))
        story.append(Spacer(1, 0.2 * cm))

        hdr_lbl = "Empresa / Company" if lang == "pt" else "Company"
        src_lbl = "Fonte / Source" if lang == "pt" else "Source"
        pli_lbl = iqr.pli if iqr else "Value"
        comp_rows = [["#", hdr_lbl, pli_lbl, src_lbl]]
        for i, c in enumerate(comparables, 1):
            comp_rows.append([
                str(i),
                c.get("name", "Comparable " + str(i)),
                "{:.4f}".format(c.get("value", 0)),
                c.get("source", "SEC EDGAR / CVM")
            ])
        comp_table = Table(comp_rows, colWidths=[0.8 * cm, 6.5 * cm, 3.5 * cm, 6.2 * cm])
        comp_table.setStyle(TableStyle([
            ("FONTNAME",      (0, 0), (-1, 0), FONT_BOLD),
            ("FONTNAME",      (0, 1), (-1, -1), FONT),
            ("FONTSIZE",      (0, 0), (-1, -1), 9),
            ("BACKGROUND",    (0, 0), (-1, 0), ALG_MID),
            ("TEXTCOLOR",     (0, 0), (-1, 0), WHITE),
            ("ROWBACKGROUNDS",(0, 1), (-1, -1), [WHITE, GRAY_LIGHT]),
            ("GRID",          (0, 0), (-1, -1), 0.25, colors.HexColor("#DDDDDD")),
            ("ALIGN",         (0, 0), (0, -1), "CENTER"),
            ("ALIGN",         (2, 0), (2, -1), "CENTER"),
            ("TOPPADDING",    (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("LEFTPADDING",   (0, 0), (-1, -1), 6),
        ]))
        story.append(comp_table)
        story.append(Spacer(1, 0.5 * cm))

    # Methodology
    story.append(HRFlowable(width="100%", thickness=0.5,
                             color=colors.HexColor("#DDDDDD"),
                             spaceBefore=8, spaceAfter=8))
    lbl = "Nota Metodologica" if lang == "pt" else "Methodology Note"
    story.append(Paragraph(lbl, S_SECTION))
    method_name = analysis_data.get("method", "")
    if lang == "pt":
        note = ("Esta analise foi conduzida utilizando o metodo " + method_name +
                ", conforme Lei 14.596/2023 e IN RFB 2.161/2023, alinhada as Diretrizes OCDE. "
                "O intervalo arm's length foi determinado pelo IQR apos analise FAR. "
                "Esta ferramenta nao substitui laudo assinado por profissional habilitado.")
    else:
        note = ("This analysis was conducted using the " + method_name +
                " method, per Brazilian Law 14.596/2023 and IN RFB 2.161/2023, "
                "aligned with OECD Guidelines. The arm's length range was determined "
                "using the IQR after FAR analysis. This tool does not replace a report "
                "signed by a qualified professional.")
    story.append(Paragraph(note, S_BODY))
    story.append(Spacer(1, 0.3 * cm))

    if lang == "pt":
        disc = ("AVISO: Este relatorio foi gerado pela plataforma Algoritimado para fins informativos. "
                "Nao constitui parecer juridico ou laudo de precos de transferencia.")
    else:
        disc = ("DISCLAIMER: This report was generated by the Algoritimado platform for informational "
                "purposes only. It does not constitute legal advice or a formal transfer pricing study.")
    story.append(Paragraph(disc, S_DISC))

    doc.build(story, canvasmaker=NumberedCanvas)
    return buf.getvalue()
