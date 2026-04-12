import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import sys, os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from calculations.base import calculate_iqr
from calculations.methods import (calculate_tnmm, calculate_pic,
                                   calculate_prl_margin_range,
                                   calculate_mcm_markup_range,
                                   calculate_pci_pecex)
from reports.pdf_generator import generate_report

st.set_page_config(page_title="Algoritimado — Transfer Pricing Platform",
                   page_icon="🌿", layout="wide",
                   initial_sidebar_state="expanded")

st.markdown("""<style>
.main{background:#FAFAF8}
h1,h2,h3{color:#1B4332!important}
.stButton>button{background:#1B4332!important;color:white!important;border:none!important;
  border-radius:6px!important;font-weight:600!important;padding:0.5rem 1.5rem!important}
.stButton>button:hover{background:#2D6A4F!important}
.metric-card{background:white;border:1px solid #E5E7EB;border-left:4px solid #E8B931;
  border-radius:8px;padding:1rem 1.2rem;margin-bottom:0.5rem}
.metric-label{font-size:12px;color:#6B7280;font-weight:500;text-transform:uppercase;letter-spacing:.05em}
.metric-value{font-size:24px;font-weight:700;color:#1B4332}
.result-al{background:#DCFCE7;border:1.5px solid #16A34A;border-radius:8px;
  padding:1.2rem;text-align:center;font-size:17px;font-weight:700;color:#15803D}
.result-adj{background:#FEE2E2;border:1.5px solid #DC2626;border-radius:8px;
  padding:1.2rem;text-align:center;font-size:17px;font-weight:700;color:#B91C1C}
.info-box{background:#EBF5EE;border-left:4px solid #2D6A4F;border-radius:4px;
  padding:.8rem 1rem;font-size:13px;color:#1B4332;margin-bottom:1rem}
.gold-badge{background:#E8B931;color:#1B4332;padding:3px 12px;border-radius:12px;
  font-size:11px;font-weight:700}
footer{visibility:hidden}#MainMenu{visibility:hidden}
</style>""", unsafe_allow_html=True)

# ── LABELS ────────────────────────────────────────────────────────────────────
def _labels(pt):
    if pt:
        return dict(method_label="Método de Preço de Transferência",
                    about_title="Sobre a Plataforma",
                    about_text="Plataforma de inteligência fiscal para análise de preços de transferência conforme Lei 14.596/2023, alinhada às Diretrizes OCDE.",
                    company="Empresa / Grupo Econômico",transaction="Descrição da Transação Controlada",
                    tested_party="Nome da Parte Testada",fiscal_year="Exercício Fiscal",
                    add_comparable="➕ Adicionar Comparável",calc_btn="🔍 Calcular Intervalo Arm's Length",
                    download_pdf="📄 Baixar Relatório PDF",results_title="Resultados da Análise",
                    comparables_title="Conjunto de Comparáveis",comp_name="Empresa Comparável",
                    comp_value="Valor do PLI",comp_source="Fonte dos Dados",
                    tested_value="PLI da Parte Testada",
                    include_tested="Incluir parte testada na análise de conformidade",
                    pli_label="Indicador de Nível de Lucro (PLI)",currency="Moeda",
                    resale_price="Preço de Revenda",cost_base="Base de Custo")
    return dict(method_label="Transfer Pricing Method",
                about_title="About the Platform",
                about_text="Tax intelligence platform for transfer pricing analysis under Brazilian regulation (Lei 14.596/2023) aligned with OECD Guidelines.",
                company="Company / Economic Group",transaction="Controlled Transaction Description",
                tested_party="Tested Party Name",fiscal_year="Fiscal Year",
                add_comparable="➕ Add Comparable",calc_btn="🔍 Calculate Arm's Length Range",
                download_pdf="📄 Download PDF Report",results_title="Analysis Results",
                comparables_title="Comparable Set",comp_name="Comparable Company",
                comp_value="PLI Value",comp_source="Data Source",
                tested_value="Tested Party PLI",
                include_tested="Include tested party in compliance assessment",
                pli_label="Profit Level Indicator (PLI)",currency="Currency",
                resale_price="Resale Price",cost_base="Cost Base")

SOURCES = ["SEC EDGAR","Brazil CVM / ITR","Annual Report","Bloomberg",
           "Refinitiv / Orbis","S&P Capital IQ","Other / Outro"]
METHOD_OPTIONS = ["TNMM / MLT — Margem Líquida da Transação",
                  "PIC / CUP — Preço Independente Comparável",
                  "PRL / RPM — Preço de Revenda menos Lucro",
                  "MCM / CPM — Custo mais Lucro",
                  "PCI — Importação (Commodities)",
                  "PECEX — Exportação (Commodities)"]
PLI_OPTIONS = {"operating_margin":"Operating Margin / Margem Operacional (%)",
               "ebitda_margin":"EBITDA Margin (%)","net_margin":"Net Profit Margin (%)",
               "berry_ratio":"Berry Ratio","roce":"Return on Operating Assets / ROCE (%)"}

if "comparables" not in st.session_state:
    st.session_state.comparables = [{"name":"","value":0.0,"source":"SEC EDGAR"} for _ in range(5)]

# ── SIDEBAR ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown('<div style="text-align:center;padding:1rem 0"><div style="font-size:22px;font-weight:800;color:#1B4332;letter-spacing:2px">🌿 ALGORITIMADO</div><div style="font-size:11px;color:#6B7280;margin-top:4px">Transfer Pricing Intelligence</div><div style="font-size:11px;color:#2D6A4F;font-weight:600">Lei 14.596/2023 · OECD</div></div>', unsafe_allow_html=True)
    st.divider()
    lang = st.selectbox("🌐 Language / Idioma", ["🇧🇷 Português","🇺🇸 English"])
    is_pt = "Português" in lang
    L = _labels(is_pt)
    st.divider()
    st.markdown(f"**{L['method_label']}**")
    method = st.selectbox("method_sel", METHOD_OPTIONS, label_visibility="collapsed")
    st.divider()
    st.markdown(f"**{L['about_title']}**")
    st.markdown(f'<div style="font-size:12px;color:#6B7280">{L["about_text"]}</div>', unsafe_allow_html=True)
    st.markdown('<a href="https://algoritimado.com" target="_blank" style="font-size:12px;color:#2D6A4F;font-weight:600">algoritimado.com ↗</a>', unsafe_allow_html=True)

# ── HEADER ────────────────────────────────────────────────────────────────────
c_h, c_b = st.columns([5,1])
with c_h:
    st.markdown(f"# {'Análise de Preços de Transferência' if is_pt else 'Transfer Pricing Analysis'}")
    st.markdown(f'<div style="color:#2D6A4F;font-size:15px;margin-bottom:1rem">{method}</div>', unsafe_allow_html=True)
with c_b:
    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown('<span class="gold-badge">OCDE · IN 2.161/2023</span>', unsafe_allow_html=True)
st.divider()

# ── TRANSACTION DATA ──────────────────────────────────────────────────────────
with st.expander(f"📋 {'Dados da Transação' if is_pt else 'Transaction Data'}", expanded=True):
    c1,c2,c3,c4 = st.columns(4)
    with c1: company_name = st.text_input(L["company"], placeholder="Ex: Grupo ABC S.A.")
    with c2: transaction_desc = st.text_input(L["transaction"], placeholder="Ex: Venda de mercadorias para matriz")
    with c3: tested_party_name = st.text_input(L["tested_party"], placeholder="Ex: ABC Brasil Ltda")
    with c4: fiscal_year = st.text_input(L["fiscal_year"], placeholder="2024", value="2024")

# ── PLI SELECTION ─────────────────────────────────────────────────────────────
pli_option = "operating_margin"
pli_label_display = PLI_OPTIONS["operating_margin"]
currency = "USD"
resale_price_val = 100.0
cost_base_val = 100.0

if "TNMM" in method:
    pli_option = st.selectbox(L["pli_label"], list(PLI_OPTIONS.keys()),
                               format_func=lambda x: PLI_OPTIONS[x])
    pli_label_display = PLI_OPTIONS[pli_option]
elif any(x in method for x in ["PIC","PCI","PECEX"]):
    currency = st.selectbox(L["currency"], ["USD","EUR","BRL","GBP"])
    pli_label_display = f"Transaction Price ({currency})"
elif "PRL" in method:
    pli_label_display = "Gross Margin / Margem Bruta (%)"
    resale_price_val = st.number_input(L["resale_price"], value=100.0, step=0.01, min_value=0.01)
elif "MCM" in method:
    pli_label_display = "Gross Markup / Markup Bruto (%)"
    cost_base_val = st.number_input(L["cost_base"], value=100.0, step=0.01, min_value=0.01)

# ── COMPARABLES ───────────────────────────────────────────────────────────────
st.markdown(f"### {L['comparables_title']}")
st.markdown(f'<div class="info-box">{"ℹ️ Insira os dados dos comparáveis selecionados após análise FAR. Mínimo recomendado: 5 empresas (IN RFB 2.161/2023)." if is_pt else "ℹ️ Enter data for comparables selected after FAR analysis. Recommended minimum: 5 companies (IN RFB 2.161/2023)."}</div>', unsafe_allow_html=True)

hc1,hc2,hc3,hc4 = st.columns([3,2,2,.5])
with hc1: st.markdown(f"**{L['comp_name']}**")
with hc2: st.markdown(f"**{pli_label_display}**")
with hc3: st.markdown(f"**{L['comp_source']}**")

for i in range(len(st.session_state.comparables)):
    cn,cv,cs,cd = st.columns([3,2,2,.5])
    with cn:
        st.session_state.comparables[i]["name"] = st.text_input(
            f"n{i}", key=f"cn_{i}", value=st.session_state.comparables[i]["name"],
            placeholder=f"Company {i+1}", label_visibility="collapsed")
    with cv:
        st.session_state.comparables[i]["value"] = st.number_input(
            f"v{i}", key=f"cv_{i}", value=float(st.session_state.comparables[i]["value"]),
            step=0.0001, format="%.4f", label_visibility="collapsed")
    with cs:
        idx = SOURCES.index(st.session_state.comparables[i]["source"]) if st.session_state.comparables[i]["source"] in SOURCES else 0
        st.session_state.comparables[i]["source"] = st.selectbox(
            f"s{i}", SOURCES, index=idx, key=f"cs_{i}", label_visibility="collapsed")
    with cd:
        if len(st.session_state.comparables) > 3:
            if st.button("✕", key=f"del_{i}"):
                st.session_state.comparables.pop(i); st.rerun()

if st.button(L["add_comparable"]):
    st.session_state.comparables.append({"name":"","value":0.0,"source":"SEC EDGAR"}); st.rerun()

# ── TESTED PARTY ──────────────────────────────────────────────────────────────
st.divider()
include_tested = st.checkbox(L["include_tested"], value=True)
tested_value = None
if include_tested:
    tv_c, _ = st.columns([2,2])
    with tv_c:
        tested_value = st.number_input(f"{L['tested_value']} — {pli_label_display}",
                                        value=0.0, step=0.0001, format="%.4f")

# ── CALCULATE ─────────────────────────────────────────────────────────────────
st.markdown("<br>", unsafe_allow_html=True)
if st.button(L["calc_btn"], use_container_width=True):
    valid_comps = [c for c in st.session_state.comparables if c["value"] != 0.0]
    if len(valid_comps) < 3:
        st.error("⚠️ Insira pelo menos 3 comparáveis com valores diferentes de zero." if is_pt else "⚠️ Please enter at least 3 comparables with non-zero values.")
    else:
        vals = [c["value"] for c in valid_comps]
        tv = tested_value if include_tested else None
        try:
            if "TNMM" in method:
                df = pd.DataFrame({"name":[c["name"] for c in valid_comps], pli_option: vals})
                iqr_result = calculate_tnmm(df, pli_option, tv)
            elif "PIC" in method:
                iqr_result = calculate_pic(vals, tv, currency)
            elif "PRL" in method:
                res = calculate_prl_margin_range(vals, resale_price_val, tv)
                iqr_result = res["iqr"]
                if tv is not None:
                    iqr_result.tested_party_value = tv
                    iqr_result.is_arms_length = res["is_arms_length"]
            elif "MCM" in method:
                res = calculate_mcm_markup_range(vals, cost_base_val, tv)
                iqr_result = res["iqr"]
                if tv is not None:
                    iqr_result.tested_party_value = tv
                    iqr_result.is_arms_length = res["is_arms_length"]
            elif "PCI" in method:
                iqr_result = calculate_pci_pecex(vals, tv, "import", currency)
            else:
                iqr_result = calculate_pci_pecex(vals, tv, "export", currency)

            st.session_state["iqr_result"] = iqr_result
            st.session_state["valid_comps"] = valid_comps
            st.session_state["meta"] = dict(
                company_name=company_name or "—",
                transaction_description=transaction_desc or "—",
                tested_party_name=tested_party_name or "—",
                fiscal_year=fiscal_year or "2024",
                method=method.split("—")[0].strip(),
                pli=pli_label_display,
                analysis_date=datetime.now().strftime("%d/%m/%Y"),
                language="pt" if is_pt else "en")
            st.success("✅ Cálculo concluído!" if is_pt else "✅ Calculation complete!")
        except Exception as e:
            st.error(f"Erro: {e}")

# ── RESULTS ───────────────────────────────────────────────────────────────────
if "iqr_result" in st.session_state:
    iqr = st.session_state["iqr_result"]
    vc  = st.session_state["valid_comps"]
    meta= st.session_state["meta"]

    st.divider()
    st.markdown(f"## {L['results_title']}")

    if iqr.tested_party_value is not None:
        if iqr.is_arms_length:
            st.markdown(f'<div class="result-al">✅  {"TRANSAÇÃO ARM\'S LENGTH — Dentro do intervalo interquartil (Q1–Q3)" if is_pt else "ARM\'S LENGTH TRANSACTION — Within the interquartile range (Q1–Q3)"}</div>', unsafe_allow_html=True)
        else:
            adj = abs(iqr.adjustment_needed) if iqr.adjustment_needed else 0
            pos = ("abaixo do Q1" if iqr.tested_party_value < iqr.q1 else "acima do Q3") if is_pt else ("below Q1" if iqr.tested_party_value < iqr.q1 else "above Q3")
            st.markdown(f'<div class="result-adj">⚠️  {"AJUSTE NECESSÁRIO" if is_pt else "ADJUSTMENT REQUIRED"} — {("Parte testada está " if is_pt else "Tested party is ")}{pos} | {"Ajuste sugerido" if is_pt else "Suggested adjustment"}: {adj:.4f}</div>', unsafe_allow_html=True)
        st.markdown("<br>", unsafe_allow_html=True)

    m1,m2,m3,m4 = st.columns(4)
    for col, lbl, val, sub in [
        (m1,"Q1 — 1º Quartil",f"{iqr.q1:.4f}","Limite inferior"),
        (m2,"Q2 — Mediana",f"{iqr.median:.4f}","Ponto médio"),
        (m3,"Q3 — 3º Quartil",f"{iqr.q3:.4f}","Limite superior"),
        (m4,"IQR (Q3–Q1)",f"{iqr.q3-iqr.q1:.4f}","Amplitude")]:
        with col:
            st.markdown(f'<div class="metric-card"><div class="metric-label">{lbl}</div><div class="metric-value">{val}</div><div style="font-size:11px;color:#9CA3AF">{sub}</div></div>', unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    ch, tc = st.columns([3,2])

    with ch:
        st.markdown(f"**{'Distribuição dos Comparáveis — Intervalo Arm\'s Length' if is_pt else 'Comparables Distribution — Arm\'s Length Range'}**")
        paired = sorted(zip(iqr.values, [c["name"] or f"C{i+1}" for i,c in enumerate(vc)]))
        sv, sn = [p[0] for p in paired], [p[1] for p in paired]
        fig = go.Figure()
        fig.add_shape(type="rect", x0=-0.5, x1=len(sv)-.5, y0=iqr.q1, y1=iqr.q3,
                      fillcolor="rgba(45,106,79,.10)", line=dict(color="rgba(45,106,79,.25)", width=1))
        for yv, lb, ds in [(iqr.q1,"Q1","dash"),(iqr.median,"Median","solid"),(iqr.q3,"Q3","dash")]:
            fig.add_shape(type="line", x0=-0.5, x1=len(sv)-.5, y0=yv, y1=yv,
                          line=dict(color="#2D6A4F", width=1.5, dash=ds))
            fig.add_annotation(x=len(sv)-.4, y=yv, text=f"{lb}: {yv:.4f}", showarrow=False,
                               font=dict(size=10, color="#2D6A4F"), xanchor="left")
        fig.add_trace(go.Scatter(x=sn, y=sv, mode="markers",
                                  marker=dict(size=13, color="#2D6A4F", line=dict(color="white",width=2)),
                                  name="Comparáveis", hovertemplate="<b>%{x}</b><br>%{y:.4f}<extra></extra>"))
        if iqr.tested_party_value is not None:
            tpc = "#16A34A" if iqr.is_arms_length else "#DC2626"
            tpn = meta.get("tested_party_name") or "Tested Party"
            fig.add_trace(go.Scatter(x=[tpn], y=[iqr.tested_party_value], mode="markers",
                                      marker=dict(size=17, color=tpc, symbol="diamond",
                                                  line=dict(color="white",width=2)),
                                      name=tpn, hovertemplate=f"<b>{tpn}</b><br>{iqr.tested_party_value:.4f}<extra></extra>"))
        fig.update_layout(plot_bgcolor="white", paper_bgcolor="white",
                          font=dict(family="Inter,sans-serif",size=12,color="#374151"),
                          xaxis=dict(showgrid=False, zeroline=False),
                          yaxis=dict(showgrid=True, gridcolor="#F3F4F6", zeroline=False,
                                     title=dict(text=pli_label_display,font=dict(size=11))),
                          legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
                          margin=dict(l=20,r=90,t=40,b=20), height=390)
        fig.add_annotation(x=-0.45, y=(iqr.q1+iqr.q3)/2, text="Arm's<br>Length<br>Range",
                           showarrow=False, font=dict(size=9,color="#2D6A4F"), xanchor="right")
        st.plotly_chart(fig, use_container_width=True)

    with tc:
        st.markdown(f"**{'Conjunto de Comparáveis' if is_pt else 'Comparable Set'}**")
        st.dataframe(pd.DataFrame([{"#":i+1,("Empresa" if is_pt else "Company"):c["name"] or f"C{i+1}",
                                     pli_label_display:f"{c['value']:.4f}",
                                     ("Fonte" if is_pt else "Source"):c["source"]}
                                    for i,c in enumerate(vc)]),
                     hide_index=True, use_container_width=True,
                     height=min(60+len(vc)*38,380))
        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown(f"**{'Estatísticas' if is_pt else 'Statistics'}**")
        st.dataframe(pd.DataFrame({"":["Min","Q1","Median","Q3","Max","Std Dev","n"],
                                    "Valor":[f"{iqr.min_val:.4f}",f"{iqr.q1:.4f}",f"{iqr.median:.4f}",
                                             f"{iqr.q3:.4f}",f"{iqr.max_val:.4f}",
                                             f"{np.std(iqr.values):.4f}",str(len(iqr.values))]}),
                     hide_index=True, use_container_width=True)

    st.divider()
    st.markdown(f"### {'📄 Relatório PDF' if is_pt else '📄 PDF Report'}")
    st.markdown(f'<div class="info-box">{"Relatório formatado conforme IN RFB 2.161/2023 — inclui dados da transação, intervalo IQR, comparáveis e nota metodológica." if is_pt else "Report formatted per IN RFB 2.161/2023 — includes transaction data, IQR range, comparables and methodology note."}</div>', unsafe_allow_html=True)
    try:
        pdf_bytes = generate_report({**meta, "iqr_result": iqr, "comparables": vc,
                                      "tested_party_value": iqr.tested_party_value})
        slug = (meta.get("company_name") or "analysis").replace(" ","-").lower()
        st.download_button(label=L["download_pdf"], data=pdf_bytes,
                           file_name=f"algoritimado-tp-{slug}-{datetime.now().strftime('%Y%m%d')}.pdf",
                           mime="application/pdf", use_container_width=True)
    except Exception as e:
        st.warning(f"PDF: {e}")

st.divider()
st.markdown('<div style="text-align:center;font-size:12px;color:#9CA3AF;padding:1rem 0"><strong style="color:#1B4332">ALGORITIMADO</strong> · Transfer Pricing Intelligence Platform · MVP v0.1<br>Lei 14.596/2023 · IN RFB 2.161/2023 · OECD Transfer Pricing Guidelines<br><a href="https://algoritimado.com" style="color:#2D6A4F">algoritimado.com</a> · Esta plataforma não substitui laudo assinado por profissional habilitado</div>', unsafe_allow_html=True)
