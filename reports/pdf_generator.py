import io
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                 TableStyle, HRFlowable, KeepTogether)
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import os

ALG_DARK  = colors.HexColor("#1B4332")
ALG_MID   = colors.HexColor("#2D6A4F")
ALG_GOLD  = colors.HexColor("#E8B931")
ALG_LIGHT = colors.HexColor("#D8F3DC")
GRAY_LIGHT= colors.HexColor("#F5F5F3")
GRAY_TEXT = colors.HexColor("#4A4A4A")
WHITE     = colors.white

def _register_fonts():
    font_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf",
    ]
    for fp in font_paths:
        if not os.path.exists(fp):
            return False
    pdfmetrics.registerFont(TTFont("DejaVuSans", font_paths[0]))
    pdfmetrics.registerFont(TTFont("DejaVuSans-Bold", font_paths[1]))
    pdfmetrics.registerFont(TTFont("DejaVuSans-Oblique", font_paths[2]))
    return True

HAS_DEJAVU = _register_fonts()
FONT       = "DejaVuSans" if HAS_DEJAVU else "Helvetica"
FONT_BOLD  = "DejaVuSans-Bold" if HAS_DEJAVU else "Helvetica-Bold"
FONT_ITALIC= "DejaVuSans-Oblique" if HAS_DEJAVU else "Helvetica-Oblique"

def _styles():
    styles = {
        "title": ParagraphStyle("title", fontName=FONT_BOLD, fontSize=18, textColor=ALG_DARK, spaceAfter=4),
        "subtitle": ParagraphStyle("subtitle", fontName=FONT, fontSize=11, textColor=ALG_MID, spaceAfter=12),
        "section": ParagraphStyle("section", fontName=FONT_BOLD, fontSize=12, textColor=ALG_DARK, spaceBefore=14, spaceAfter=6),
        "body": ParagraphStyle("body", fontName=FONT, fontSize=10, textColor=GRAY_TEXT, spaceAfter=4, leading=15),
        "small": ParagraphStyle("small", fontName=FONT, fontSize=9, textColor=colors.HexColor("#888888"), spaceAfter=2),
        "arms_length_yes": ParagraphStyle("al_yes", fontName=FONT_BOLD, fontSize=13, textColor=colors.HexColor("#1A6B3C")),
        "arms_length_no": ParagraphStyle("al_no", fontName=FONT_BOLD, fontSize=13, textColor=colors.HexColor("#B91C1C")),
        "disclaimer": ParagraphStyle("disclaimer", fontName=FONT_ITALIC, fontSize=8, textColor=colors.HexColor("#888888"), leading=12),
    }
    return styles

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
        self.drawRightString(A4[0] - 1.5*cm, 1*cm, f"Page {self._pageNumber} of {page_count}")
        self.setStrokeColor(ALG_GOLD)
        self.setLineWidth(1.5)
        self.line(1.5*cm, 1.5*cm, A4[0]-1.5*cm, 1.5*cm)
        self.setFillColor(ALG_MID)
        self.setFont(FONT, 8)
        self.drawString(1.5*cm, 1*cm, "Algoritimado — Transfer Pricing Intelligence Platform  |  algoritimado.com")

def generate_report(analysis_data: dict) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=1.8*cm, rightMargin=1.8*cm,
                            topMargin=2.2*cm, bottomMargin=2.5*cm,
                            title="Transfer Pricing Analysis Report — Algoritimado")
    st = _styles()
    lang = analysis_data.get("language", "pt")
    iqr = analysis_data.get("iqr_result")
    story = []

    header_data = [[
        Paragraph("ALGORITIMADO", ParagraphStyle("hdr", fontName=FONT_BOLD, fontSize=20, textColor=WHITE, spaceAfter=0)),
        Paragraph("Transfer Pricing<br/>Intelligence Platform", ParagraphStyle("hdr2", fontName=FONT, fontSize=9, textColor=ALG_LIGHT, spaceAfter=0, alignment=2))
    ]]
    header_table = Table(header_data, colWidths=[9*cm, 8*cm])
    header_table.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), ALG_DARK),
        ("TOPPADDING", (0,0), (-1,-1), 14), ("BOTTOMPADDING", (0,0), (-1,-1), 14),
        ("LEFTPADDING", (0,0), (0,-1), 14), ("RIGHTPADDING", (-1,0), (-1,-1), 14),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
    ]))
    story.append(header_table)
    story.append(Spacer(1, 0.4*cm))
    story.append(HRFlowable(width="100%", thickness=3, color=ALG_GOLD, spaceAfter=10, spaceBefore=0))

    title_text = "Relatório de Análise de Preços de Transferência" if lang == "pt" else "Transfer Pricing Analysis Report"
    story.append(Paragraph(title_text, st["title"]))

    date_str = analysis_data.get("analysis_date", datetime.now().strftime("%d/%m/%Y"))
    meta = [
        ["Empresa / Company", analysis_data.get("company_name", "—"), "Data / Date", date_str],
        ["Transação / Transaction", analysis_data.get("transaction_description", "—"), "Método / Method", analysis_data.get("method", "—")],
        ["Parte Testada / Tested Party", analysis_data.get("tested_party_name", "—"), "PLI", analysis_data.get("pli", "—")],
        ["Exercício Fiscal / Fiscal Year", analysis_data.get("fiscal_year", "—"), "Legislação / Regulation", "Lei 14.596/2023 · IN RFB 2.161/2023"],
    ]
    meta_table = Table(meta, colWidths=[4.5*cm, 5.5*cm, 3.5*cm, 4.5*cm])
    meta_table.setStyle(TableStyle([
        ("FONTNAME", (0,0), (-1,-1), FONT), ("FONTNAME", (0,0), (0,-1), FONT_BOLD),
        ("FONTNAME", (2,0), (2,-1), FONT_BOLD), ("FONTSIZE", (0,0), (-1,-1), 9),
        ("TEXTCOLOR", (0,0), (-1,-1), GRAY_TEXT), ("TEXTCOLOR", (0,0), (0,-1), ALG_DARK),
        ("TEXTCOLOR", (2,0), (2,-1), ALG_DARK),
        ("ROWBACKGROUNDS", (0,0), (-1,-1), [GRAY_LIGHT, WHITE]),
        ("GRID", (0,0), (-1,-1), 0.25, colors.HexColor("#DDDDDD")),
        ("TOPPADDING", (0,0), (-1,-1), 6), ("BOTTOMPADDING", (0,0), (-1,-1), 6),
        ("LEFTPADDING", (0,0), (-1,-1), 8),
    ]))
    story.append(meta_table)
    story.append(Spacer(1, 0.5*cm))

    if iqr and iqr.tested_party_value is not None:
        story.append(Paragraph("Resultado de Conformidade" if lang == "pt" else "Compliance Result", st["section"]))
        status_color = colors.HexColor("#DCFCE7") if iqr.is_arms_length else colors.HexColor("#FEE2E2")
        border_color = colors.HexColor("#16A34A") if iqr.is_arms_length else colors.HexColor("#DC2626")
        status_text = ("✓  TRANSAÇÃO ARM'S LENGTH — Dentro do intervalo interquartil" if iqr.is_arms_length else "✗  AJUSTE NECESSÁRIO — Fora do intervalo interquartil") if lang == "pt" else ("✓  ARM'S LENGTH — Within the interquartile range" if iqr.is_arms_length else "✗  ADJUSTMENT REQUIRED — Outside the interquartile range")
        status_style = st["arms_length_yes"] if iqr.is_arms_length else st["arms_length_no"]
        status_table = Table([[Paragraph(status_text, status_style)]], colWidths=[17*cm])
        status_table.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,-1), status_color),
            ("LINEAFTER", (0,0), (0,-1), 3, border_color), ("LINEBEFORE", (0,0), (0,-1), 3, border_color),
            ("LINEABOVE", (0,0), (-1,0), 3, border_color), ("LINEBELOW", (0,-1), (-1,-1), 3, border_color),
            ("TOPPADDING", (0,0), (-1,-1), 12), ("BOTTOMPADDING", (0,0), (-1,-1), 12),
            ("LEFTPADDING", (0,0), (-1,-1), 14),
        ]))
        story.append(status_table)
        story.append(Spacer(1, 0.4*cm))

    if iqr:
        story.append(Paragraph("Intervalo Interquartil (IQR)" if lang == "pt" else "Interquartile Range (IQR)", st["section"]))
        iqr_rows = [
            ["Indicador" if lang == "pt" else "Indicator", "Valor" if lang == "pt" else "Value", "Descrição" if lang == "pt" else "Description"],
            ["Q1 — 1º Quartil", f"{iqr.q1:.4f}", "Limite inferior do intervalo arm's length" if lang == "pt" else "Lower bound of arm's length range"],
            ["Q2 — Mediana", f"{iqr.median:.4f}", "Ponto médio do conjunto de comparáveis" if lang == "pt" else "Midpoint of comparable set"],
            ["Q3 — 3º Quartil", f"{iqr.q3:.4f}", "Limite superior do intervalo arm's length" if lang == "pt" else "Upper bound of arm's length range"],
            ["IQR (Q3 – Q1)", f"{iqr.q3 - iqr.q1:.4f}", "Amplitude do intervalo interquartil" if lang == "pt" else "Interquartile range width"],
        ]
        if iqr.tested_party_value is not None:
            iqr_rows.append([f"Parte Testada: {analysis_data.get('tested_party_name', '')}", f"{iqr.tested_party_value:.4f}", iqr.compliance_status()])
            if iqr.adjustment_needed and not iqr.is_arms_length:
                iqr_rows.append(["Ajuste Sugerido" if lang == "pt" else "Suggested Adjustment", f"{abs(iqr.adjustment_needed):.4f}", "Diferença para a mediana" if lang == "pt" else "Distance to median"])
        iqr_table = Table(iqr_rows, colWidths=[5.5*cm, 3*cm, 8.5*cm])
        ts = TableStyle([
            ("FONTNAME", (0,0), (-1,0), FONT_BOLD), ("FONTNAME", (0,1), (-1,-1), FONT),
            ("FONTSIZE", (0,0), (-1,-1), 9.5), ("BACKGROUND", (0,0), (-1,0), ALG_DARK),
            ("TEXTCOLOR", (0,0), (-1,0), WHITE), ("ROWBACKGROUNDS", (0,1), (-1,-1), [WHITE, GRAY_LIGHT]),
            ("GRID", (0,0), (-1,-1), 0.25, colors.HexColor("#DDDDDD")),
            ("ALIGN", (1,0), (1,-1), "CENTER"), ("TOPPADDING", (0,0), (-1,-1), 7),
            ("BOTTOMPADDING", (0,0), (-1,-1), 7), ("LEFTPADDING", (0,0), (-1,-1), 8),
        ])
        if iqr.tested_party_value is not None:
            tp_row = len(iqr_rows) - (2 if (iqr.adjustment_needed and not iqr.is_arms_length) else 1)
            bg = colors.HexColor("#DCFCE7") if iqr.is_arms_length else colors.HexColor("#FEE2E2")
            ts.add("BACKGROUND", (0, tp_row), (-1, tp_row), bg)
            ts.add("FONTNAME", (0, tp_row), (-1, tp_row), FONT_BOLD)
        iqr_table.setStyle(ts)
        story.append(iqr_table)
        story.append(Spacer(1, 0.5*cm))

    comparables = analysis_data.get("comparables", [])
    if comparables:
        story.append(Paragraph("Conjunto de Comparáveis" if lang == "pt" else "Comparable Set", st["section"]))
        story.append(Paragraph("Os comparáveis foram selecionados com base em análise funcional (FAR) conforme IN RFB 2.161/2023 e Diretrizes OCDE." if lang == "pt" else "Comparables selected based on functional analysis (FAR) per IN RFB 2.161/2023 and OECD TP Guidelines.", ParagraphStyle("small", fontName=FONT, fontSize=9, textColor=colors.HexColor("#888888"))))
        story.append(Spacer(1, 0.2*cm))
        comp_rows = [["#", "Empresa / Company" if lang == "pt" else "Company", iqr.pli if iqr else "Value", "Fonte / Source" if lang == "pt" else "Source"]]
        for i, c in enumerate(comparables, 1):
            comp_rows.append([str(i), c.get("name", f"Comparable {i}"), f"{c.get('value', 0):.4f}", c.get("source", "SEC EDGAR / CVM")])
        comp_table = Table(comp_rows, colWidths=[0.8*cm, 6.5*cm, 3.5*cm, 6.2*cm])
        comp_table.setStyle(TableStyle([
            ("FONTNAME", (0,0), (-1,0), FONT_BOLD), ("FONTNAME", (0,1), (-1,-1), FONT),
            ("FONTSIZE", (0,0), (-1,-1), 9), ("BACKGROUND", (0,0), (-1,0), ALG_MID),
            ("TEXTCOLOR", (0,0), (-1,0), WHITE), ("ROWBACKGROUNDS", (0,1), (-1,-1), [WHITE, GRAY_LIGHT]),
            ("GRID", (0,0), (-1,-1), 0.25, colors.HexColor("#DDDDDD")),
            ("ALIGN", (0,0), (0,-1), "CENTER"), ("ALIGN", (2,0), (2,-1), "CENTER"),
            ("TOPPADDING", (0,0), (-1,-1), 6), ("BOTTOMPADDING", (0,0), (-1,-1), 6),
            ("LEFTPADDING", (0,0), (-1,-1), 6),
        ]))
        story.append(comp_table)
        story.append(Spacer(1, 0.5*cm))

    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#DDDDDD"), spaceBefore=8, spaceAfter=8))
    story.append(Paragraph("Nota Metodológica" if lang == "pt" else "Methodology Note", st["section"]))
    story.append(Paragraph(
        f"Esta análise foi conduzida utilizando o método <b>{analysis_data.get('method', '')}</b>, conforme Lei 14.596/2023 e IN RFB 2.161/2023, alinhada às Diretrizes OCDE. O intervalo arm's length foi determinado pelo IQR do conjunto de comparáveis após análise FAR. Esta ferramenta não substitui laudo assinado por profissional habilitado."
        if lang == "pt" else
        f"This analysis was conducted using the <b>{analysis_data.get('method', '')}</b> method, per Brazilian Law 14.596/2023 and IN RFB 2.161/2023, aligned with OECD Guidelines. The arm's length range was determined using the IQR of the comparable set after FAR analysis. This tool does not replace a report signed by a qualified professional.",
        st["body"]))
    story.append(Spacer(1, 0.3*cm))
    story.append(Paragraph(
        "AVISO: Este relatório foi gerado pela plataforma Algoritimado para fins informativos. Não constitui parecer jurídico ou laudo de preços de transferência."
        if lang ==
