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
from data.edgar_fetcher import SIC_MAP
from data.cvm_fetcher import CNAE_MAP
from data.comparables_finder import find_comparables, ALL_INDUSTRIES

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

# ── IDENTIDADE & EVENT LOGGING ────────────────────────────────────────────────
import json as _json
import threading as _threading
import urllib.request as _urlreq
from datetime import timezone as _tz

def _post_to_webhook(rec: dict) -> None:
    url = ""
    try:
        url = st.secrets.get("WEBHOOK_URL", "")
    except Exception:
        url = ""
    if not url:
        return
    try:
        data = _json.dumps(rec, ensure_ascii=False).encode("utf-8")
        req = _urlreq.Request(url, data=data, method="POST",
                              headers={"Content-Type": "application/json"})
        _urlreq.urlopen(req, timeout=3).read()
    except Exception as e:
        print(f"[ALGORITIMADO_WEBHOOK_FAIL] {e}", flush=True)

def _log_event(event_type: str, payload: dict | None = None) -> None:
    rec = {
        "ts": datetime.now(_tz.utc).isoformat(),
        "event": event_type,
        "email": st.session_state.get("user_email", ""),
        "domain": st.session_state.get("user_domain", ""),
        "company": st.session_state.get("user_company", ""),
        "name": st.session_state.get("user_name", ""),
        "role": st.session_state.get("user_role", ""),
        "opt_in_marketing": bool(st.session_state.get("opt_in_marketing", False)),
        "consent_lgpd": bool(st.session_state.get("consent_lgpd", False)),
        "consent_ts": st.session_state.get("consent_ts", ""),
        "source": st.session_state.get("source", ""),
        "payload": payload or {},
    }
    print("[ALGORITIMADO_EVENT] " + _json.dumps(rec, ensure_ascii=False), flush=True)
    _threading.Thread(target=_post_to_webhook, args=(rec,), daemon=True).start()

def _get_query_params() -> dict:
    try:
        qp = st.query_params
        return {k: qp[k] for k in qp}
    except Exception:
        try:
            legacy = st.experimental_get_query_params()
            return {k: (v[0] if isinstance(v, list) and v else v) for k, v in legacy.items()}
        except Exception:
            return {}

def _hydrate_identity_from_url() -> None:
    if st.session_state.get("authenticated"):
        return
    qp = _get_query_params()
    email = (qp.get("email") or "").strip()
    if "@" not in email:
        return
    st.session_state["user_email"] = email
    st.session_state["user_name"] = (qp.get("nome") or qp.get("name") or "").strip()
    st.session_state["user_company"] = (qp.get("empresa") or qp.get("company") or "").strip()
    st.session_state["user_domain"] = email.split("@", 1)[1].lower()
    st.session_state["source"] = (qp.get("utm_source") or "landing").strip()
    st.session_state["authenticated"] = True
    _log_event("session_start_from_landing")

def _inline_signup_form() -> None:
    st.title("📊 Algoritimado — Transfer Pricing Intelligence")
    st.markdown(
        "Preencha os campos abaixo para acessar a plataforma. "
        "Leva 30 segundos, é gratuito, e segue os requisitos da Lei 14.596/2023."
    )
    with st.form("signup_form", clear_on_submit=False):
        c1, c2 = st.columns(2)
        with c1:
            nome = st.text_input("Nome completo *", placeholder="Ex: Maria Silva")
            empresa = st.text_input("Empresa *", placeholder="Ex: ABC Consultoria Tributária")
        with c2:
            email = st.text_input("Email profissional *", placeholder="voce@empresa.com.br")
            cargo = st.text_input("Cargo (opcional)", placeholder="Ex: Tax Manager")
        consent_lgpd = st.checkbox(
            "Li e concordo com a Política de Privacidade e os Termos de Uso da Algoritimado, "
            "e autorizo o tratamento dos meus dados pessoais (nome, email, empresa, cargo) "
            "para liberação de acesso à plataforma, em conformidade com a LGPD (Lei 13.709/2018). *",
            value=False,
            key="consent_lgpd_checkbox",
        )
        opt_in = st.checkbox(
            "Também aceito receber comunicações da Algoritimado sobre Transfer Pricing "
            "e atualizações da plataforma (opcional).",
            value=False,
            key="opt_in_marketing_checkbox",
        )
        st.markdown(
            '<div style="font-size:11px;color:#6B7280;margin-top:.6rem;line-height:1.5">'
            '<a href="https://algoritimado.com/policies/privacy-policy" target="_blank" style="color:#2D6A4F;font-weight:600">Política de Privacidade</a> · '
            '<a href="https://algoritimado.com/policies/terms-of-service" target="_blank" style="color:#2D6A4F;font-weight:600">Termos de Uso</a>. '
            'Você pode revogar consentimentos e solicitar exclusão dos seus dados a qualquer momento via '
            '<a href="mailto:contato@algoritimado.com" style="color:#2D6A4F;font-weight:600">contato@algoritimado.com</a>.'
            '</div>',
            unsafe_allow_html=True
        )
        submitted = st.form_submit_button(
            "Acessar a plataforma →", type="primary", width="stretch"
        )
        if submitted:
            nome_v, email_v, empresa_v = nome.strip(), email.strip(), empresa.strip()
            if not nome_v or "@" not in email_v or not empresa_v:
                st.error("⚠️ Preencha nome, email válido (com @) e empresa.")
            elif not consent_lgpd:
                st.error("⚠️ Para acessar a plataforma é necessário concordar com o tratamento de dados (LGPD).")
            else:
                st.session_state["user_email"] = email_v
                st.session_state["user_name"] = nome_v
                st.session_state["user_company"] = empresa_v
                st.session_state["user_domain"] = email_v.split("@", 1)[1].lower()
                st.session_state["user_role"] = cargo.strip()
                st.session_state["opt_in_marketing"] = bool(opt_in)
                st.session_state["consent_lgpd"] = True
                st.session_state["consent_ts"] = datetime.now(_tz.utc).isoformat()
                st.session_state["source"] = "direct"
                st.session_state["authenticated"] = True
                _log_event("session_start_direct")
                st.rerun()
    st.stop()

_hydrate_identity_from_url()
if not st.session_state.get("authenticated"):
    _inline_signup_form()



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
METHOD_OPTIONS = ["MLT (TNMM) — Margem Líquida da Transação",
                  "PIC (CUP) — Preço Independente Comparável",
                  "PRL (RPM) — Preço de Revenda menos Lucro",
                  "MCL (Cost Plus) — Custo mais Lucro",
                  "PCI — Importação Commodities (legado · Lei 9.430/96)",
                  "PECEX — Exportação Commodities (legado · Lei 9.430/96)"]
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
    with st.expander("ℹ️ Quando usar cada método" if is_pt else "ℹ️ When to use each method"):
        if is_pt:
            st.markdown(
                "- **MLT (TNMM)** — mais usado. Distribuidores, prestadores de serviços, manufatura contratada\n"
                "- **PIC (CUP)** — preços de mercado observáveis; commodities com cotação pública\n"
                "- **PRL (RPM)** — distribuidores e revendedores sem transformação significativa\n"
                "- **MCL (Cost Plus)** — fabricantes sob contrato; serviços de baixo risco\n"
                "- **PCI / PECEX** — legado Lei 9.430/96, só pra exercícios até 2023"
            )
        else:
            st.markdown(
                "- **MLT (TNMM)** — most used. Distributors, service providers, contract manufacturers\n"
                "- **PIC (CUP)** — observable market prices; commodities with public quotations\n"
                "- **PRL (RPM)** — distributors and resellers without significant transformation\n"
                "- **MCL (Cost Plus)** — contract manufacturers; low-risk service providers\n"
                "- **PCI / PECEX** — legacy Law 9.430/96, fiscal years through 2023 only"
            )
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

if any(x in method for x in ["PCI", "PECEX"]):
    st.warning(
        ("⚠️ **Método legado** — PCI e PECEX foram revogados pela Lei 14.596/2023 e aplicam-se apenas a exercícios fiscais até 2023. Para transações de commodities a partir de 2024, use o método **PIC**."
         if is_pt else
         "⚠️ **Legacy method** — PCI and PECEX were repealed by Law 14.596/2023 and apply only to fiscal years through 2023. For commodity transactions from 2024 onward, use the **PIC** method.")
    )

st.divider()

# Tutorial info box — como usar o app
if is_pt:
    st.info(
        "**ℹ️ Como usar o app:**\n\n"
        "**1.** Selecione o método de TP e o PLI (Indicador de Nível de Lucro)\n\n"
        "**2.** Adicione comparáveis manualmente OU use o Auto Search (SEC EDGAR + CVM)\n\n"
        "⚠️ *Resultados do Auto Search aparecem no final da tabela — role para baixo na seção 'Conjunto de Comparáveis' para visualizá-los*\n\n"
        "**3.** Clique em **Calcular Intervalo Arm's Length** para gerar análise IQR e relatório PDF"
    )
else:
    st.info(
        "**ℹ️ How to use:**\n\n"
        "**1.** Select the TP method and the PLI (Profit Level Indicator)\n\n"
        "**2.** Add comparables manually OR use Auto Search (SEC EDGAR + CVM)\n\n"
        "⚠️ *Auto Search results appear at the bottom of the table — scroll down to the 'Comparable Set' section to view them*\n\n"
        "**3.** Click **Calculate Arm's Length Range** to generate IQR analysis and PDF report"
    )

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

if "MLT" in method:
    pli_option = st.selectbox(L["pli_label"], list(PLI_OPTIONS.keys()),
                               format_func=lambda x: PLI_OPTIONS[x])
    pli_label_display = PLI_OPTIONS[pli_option]
elif any(x in method for x in ["PIC","PCI","PECEX"]):
    currency = st.selectbox(L["currency"], ["USD","EUR","BRL","GBP"])
    pli_label_display = f"Transaction Price ({currency})"
elif "PRL" in method:
    pli_label_display = "Gross Margin / Margem Bruta (%)"
    pc1, pc2 = st.columns([1, 2])
    with pc1:
        currency = st.selectbox(L["currency"], ["BRL","USD","EUR","GBP"], key="prl_currency")
    with pc2:
        resale_price_val = st.number_input(
            f"{L['resale_price']} ({currency})",
            value=100.0, step=0.01, min_value=0.01, key="prl_resale")
elif "MCL" in method:
    pli_label_display = "Gross Markup / Markup Bruto (%)"
    mc1, mc2 = st.columns([1, 2])
    with mc1:
        currency = st.selectbox(L["currency"], ["BRL","USD","EUR","GBP"], key="mcl_currency")
    with mc2:
        cost_base_val = st.number_input(
            f"{L['cost_base']} ({currency})",
            value=100.0, step=0.01, min_value=0.01, key="mcl_cost")

# ── LEVEL 2: AUTO SEARCH ─────────────────────────────────────────────────────
ai_label = "🤖 Buscar Comparáveis Automaticamente (SEC EDGAR + CVM)" if is_pt else "🤖 Find Comparables Automatically (SEC EDGAR + CVM)"
with st.expander(ai_label, expanded=False):
    # Compatibility gate: Auto Search only honest for method+PLI combos whose data EDGAR/CVM actually return.
    # PIC/PCI/PECEX use transaction prices (different data type); Berry Ratio/ROCE need fields neither fetcher computes.
    _PRICE_METHODS = ("PIC", "PCI", "PECEX")
    _UNSUPPORTED_PLIS = ("berry_ratio", "roce")
    _method_supports = not any(x in method for x in _PRICE_METHODS)
    _pli_supports = True
    if "MLT" in method:
        _pli_supports = pli_option not in _UNSUPPORTED_PLIS

    # Clear stale results when method/PLI changes — markup values shouldn't display under margin labels.
    _search_key = f"{method}|{pli_option}|{pli_label_display}"
    if st.session_state.get("auto_results_key") != _search_key:
        st.session_state.pop("auto_results", None)
        st.session_state.pop("auto_results_pli_label", None)
        st.session_state["auto_results_key"] = _search_key

    if not _method_supports:
        st.warning(
            "⚠️ **Auto Search não aplicável a este método.**\n\n"
            "PIC, PCI e PECEX usam preços de transação observáveis ou cotações de commodity "
            "(fontes externas como CME, B3). SEC EDGAR e CVM Brasil fornecem dados financeiros "
            "corporativos (margens, lucro), não preços de transação. "
            "**Adicione os preços/cotações manualmente** na tabela abaixo."
            if is_pt else
            "⚠️ **Auto Search not applicable for this method.**\n\n"
            "PIC, PCI, and PECEX use observable transaction prices or commodity quotations "
            "(external sources like CME, B3). SEC EDGAR and CVM Brasil provide corporate "
            "financial data (margins, profit), not transaction prices. "
            "**Add prices/quotations manually** in the table below."
        )
    elif not _pli_supports:
        st.warning(
            "⚠️ **Auto Search ainda não cobre Berry Ratio / ROCE.**\n\n"
            "Esses PLIs requerem dados financeiros adicionais (SG&A, ativos operacionais) "
            "que estão no roadmap (Fase 3 — NVIDIA Inception). "
            "**Opções:** (a) Adicione comparáveis manualmente, ou (b) troque o PLI para "
            "Operating Margin, EBITDA Margin ou Net Profit Margin (cobertos pelo Auto Search)."
            if is_pt else
            "⚠️ **Auto Search does not yet cover Berry Ratio / ROCE.**\n\n"
            "These PLIs require additional financial data (SG&A, operating assets) on the "
            "roadmap (Phase 3 — NVIDIA Inception). **Options:** (a) Add comparables manually, "
            "or (b) switch PLI to Operating Margin, EBITDA Margin or Net Profit Margin "
            "(covered by Auto Search)."
        )
    else:
        st.markdown(
            '<div class="info-box">🌐 ' +
            ("Busca automática em bases públicas: <b>SEC EDGAR</b> (empresas abertas EUA) e <b>CVM Brasil</b> (empresas abertas BR). Selecione os comparáveis encontrados para preencher a tabela abaixo automaticamente."
             if is_pt else
             "Automatic search in public databases: <b>SEC EDGAR</b> (US listed companies) and <b>CVM Brasil</b> (BR listed companies). Select found comparables to auto-fill the table below.") +
            '</div>', unsafe_allow_html=True
        )

        # EBITDA Margin: only SEC EDGAR computes it (CVM DRE doesn't break out D&A).
        if "MLT" in method and pli_option == "ebitda_margin":
            st.info(
                "ℹ️ **EBITDA Margin:** disponível apenas no SEC EDGAR no momento. "
                "CVM Brasil não separa Depreciação/Amortização nas contas padronizadas do DRE consolidado. "
                "Se marcar apenas 'CVM Brasil' como fonte, a busca retornará vazia."
                if is_pt else
                "ℹ️ **EBITDA Margin:** currently only available from SEC EDGAR. "
                "CVM Brasil does not break out D&A in standard consolidated income statement accounts. "
                "If you select only 'CVM Brasil' as source, the search will return empty."
            )

        ac1, ac2, ac3 = st.columns([2, 2, 1])
        with ac1:
            auto_industry = st.selectbox(
                "Setor / Industry" if is_pt else "Industry / Sector",
                ["— Select —"] + ALL_INDUSTRIES,
                key="auto_industry"
            )
            auto_industry = None if auto_industry == "— Select —" else auto_industry

        with ac2:
            sc1, sc2 = st.columns(2)
            with sc1:
                auto_name_edgar = st.text_input(
                    "Nome (EDGAR)" if is_pt else "Name (EDGAR)",
                    placeholder="Ex: Pfizer",
                    key="auto_edgar_name"
                ) or None
            with sc2:
                auto_name_cvm = st.text_input(
                    "Nome (CVM)" if is_pt else "Name (CVM)",
                    placeholder="Ex: EMBRAER",
                    key="auto_cvm_name"
                ) or None

        with ac3:
            auto_sources = st.multiselect(
                "Fontes / Sources",
                ["SEC EDGAR", "CVM Brasil"],
                default=["SEC EDGAR", "CVM Brasil"],
                key="auto_sources"
            )
            auto_limit = st.number_input(
                "Máx resultados" if is_pt else "Max results",
                min_value=5, max_value=30, value=15, key="auto_limit"
            )
            # Same-year comparability: default the search year to the analysis
            # fiscal year so they can't drift apart.
            _def_year = int(fiscal_year) if str(fiscal_year).strip().isdigit() else 2024
            _def_year = min(max(_def_year, 2015), 2025)
            auto_year = st.number_input(
                "Exercício / Fiscal Year",
                min_value=2015, max_value=2025, value=_def_year, step=1, key="auto_year",
                help=("Os comparáveis virão deste exercício (SEC e CVM). Empresas sem "
                      "dado deste ano são excluídas — nunca se mistura ano." if is_pt else
                      "Comparables will come from this fiscal year (SEC and CVM). Companies "
                      "without data for this year are excluded — years are never mixed.")
            )

        search_clicked = st.button(
            "🔍 Buscar Comparáveis" if is_pt else "🔍 Search Comparables",
            key="auto_search_btn", width="stretch"
        )

        if search_clicked:
            # Session-level rate limit: 5 searches per 60s. Protects against SEC EDGAR User-Agent ban
            # (EDGAR enforces ~10 req/sec total — concurrent abuse breaks Auto Search for everyone).
            _now_ts = datetime.now().timestamp()
            _clicks = [t for t in st.session_state.get("auto_search_clicks", []) if _now_ts - t < 60]
            if len(_clicks) >= 5:
                st.error(
                    "⚠️ Limite de **5 buscas por minuto** atingido (proteção contra abuso das APIs públicas SEC EDGAR e CVM). Aguarde alguns segundos e tente novamente."
                    if is_pt else
                    "⚠️ Rate limit: **5 searches per minute** (public API abuse protection for SEC EDGAR and CVM). Wait a few seconds and try again."
                )
            elif not auto_industry and not auto_name_edgar and not auto_name_cvm:
                st.warning("Selecione um setor ou digite um nome para buscar." if is_pt
                           else "Select an industry or enter a company name to search.")
            else:
                _clicks.append(_now_ts)
                st.session_state["auto_search_clicks"] = _clicks

                # Map pli_label_display → fetcher field. Only PLIs whose data exists in EDGAR/CVM
                # (see extract_financials in edgar_fetcher.py and calculate_margins_cvm in cvm_fetcher.py).
                SUPPORTED_PLI_LABEL_MAP = {
                    PLI_OPTIONS["operating_margin"]: "operating_margin",
                    PLI_OPTIONS["ebitda_margin"]: "ebitda_margin",
                    PLI_OPTIONS["net_margin"]: "net_margin",
                    "Gross Margin / Margem Bruta (%)": "gross_margin",    # PRL
                    "Gross Markup / Markup Bruto (%)": "gross_margin",    # MCL — derived below
                }
                search_pli = SUPPORTED_PLI_LABEL_MAP.get(pli_label_display, "operating_margin")

                with st.spinner("🔍 Buscando em SEC EDGAR e CVM Brasil..." if is_pt
                               else "🔍 Searching SEC EDGAR and CVM Brasil..."):
                    results_df = find_comparables(
                        industry=auto_industry,
                        company_name_edgar=auto_name_edgar,
                        company_name_cvm=auto_name_cvm,
                        sources=auto_sources,
                        year=int(auto_year),
                        limit=int(auto_limit),
                        pli=search_pli
                    )

                # MCL: derive Gross Markup from Gross Margin (algebraic identity).
                # revenue = cost + gross_profit ⇒ markup_pct = gm_pct / (100 - gm_pct) * 100
                if "MCL" in method and not results_df.empty and "value" in results_df.columns:
                    results_df["value"] = results_df["value"].apply(
                        lambda gm: round(gm / (100 - gm) * 100, 4)
                        if pd.notna(gm) and gm < 100 else None
                    )
                    results_df = results_df.dropna(subset=["value"]).reset_index(drop=True)
                    # Value was transformed (gross margin → markup), so the margin
                    # breakdown no longer matches the displayed value — drop it.
                    if "breakdown" in results_df.columns:
                        results_df["breakdown"] = None

                if results_df.empty:
                    st.warning(
                        "Nenhum comparável encontrado. Tente outro setor ou nome." if is_pt
                        else "No comparables found. Try a different industry or name."
                    )
                else:
                    st.session_state["auto_results"] = results_df
                    st.session_state["auto_results_pli_label"] = pli_label_display
                    st.success(
                        f"✅ {len(results_df)} comparáveis encontrados!" if is_pt
                        else f"✅ {len(results_df)} comparables found!"
                    )

    # Show results and selection
    if "auto_results" in st.session_state and not st.session_state["auto_results"].empty:
        res = st.session_state["auto_results"]
        st.markdown(f"**{'Resultados encontrados — selecione para adicionar:' if is_pt else 'Results found — select to add:'}**")

        # Display as selectable table
        display_cols = ["name", "value", "source"]
        if "operating_margin" in res.columns:
            display_cols = ["name", "value", "operating_margin", "net_margin", "gross_margin", "source"]
        display_df = res[[c for c in display_cols if c in res.columns]].copy()
        # Show the actual PLI name in the column header (was generic "PLI Selecionado", which masked which value was being shown)
        _displayed_pli = st.session_state.get("auto_results_pli_label", pli_label_display)
        display_df.columns = (
            ["Empresa", _displayed_pli, "Mg. Operacional (%)", "Mg. Líquida (%)", "Mg. Bruta (%)", "Fonte"]
            if is_pt and len(display_df.columns) == 6 else
            ["Company", _displayed_pli, "Op. Margin (%)", "Net Margin (%)", "Gross Margin (%)", "Source"]
            if len(display_df.columns) == 6 else
            ["Empresa/Company", _displayed_pli, "Fonte/Source"]
        )

        # Format numbers
        for col in display_df.columns[1:-1]:
            display_df[col] = display_df[col].apply(
                lambda x: f"{x:.4f}" if pd.notna(x) else "—"
            )

        st.dataframe(display_df, hide_index=False, width="stretch",
                     height=min(60 + len(res) * 38, 400))

        # Selection
        sel_label = "Selecionar por índice (ex: 0,1,2):" if is_pt else "Select by index (e.g. 0,1,2):"
        sel_input = st.text_input(sel_label, placeholder="0,1,2,3,4", key="auto_sel")

        add_label = "➕ Adicionar selecionados à tabela" if is_pt else "➕ Add selected to table"
        if st.button(add_label, key="auto_add_btn"):
            try:
                indices = [int(i.strip()) for i in sel_input.split(",") if i.strip().isdigit()]
                if not indices:
                    indices = list(range(min(5, len(res))))
                added = 0
                for idx in indices:
                    if idx < len(res):
                        row = res.iloc[idx]
                        _src_url = row.get("source_url", "")
                        _bd = row.get("breakdown", None)
                        new_comp = {
                            "name": row["name"],
                            "value": float(row["value"]),
                            "source": row.get("source", "SEC EDGAR / CVM"),
                            # source_url rides along silently (not shown in the
                            # manual table) so the PDF can link to the filing.
                            # CVM rows have no clean permalink → empty/NaN → "".
                            "source_url": "" if pd.isna(_src_url) else str(_src_url),
                        }
                        # breakdown (numerator/revenue/margin from the filing)
                        # rides along too, when present (SEC rows only today).
                        if isinstance(_bd, dict):
                            new_comp["breakdown"] = _bd
                        st.session_state.comparables.append(new_comp)
                        added += 1
                st.success(
                    f"✅ {added} comparáveis adicionados!" if is_pt
                    else f"✅ {added} comparables added!"
                )
                st.rerun()
            except Exception as e:
                st.error(f"Erro: {e}")

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
        _current_src = st.session_state.comparables[i]["source"]
        # Preserve fetcher-provided sources (e.g. "CVM Brasil 2024", "SEC EDGAR")
        # that aren't in the manual SOURCES list — otherwise selectbox silently
        # overwrites the real source with SOURCES[0] (=SEC EDGAR), making BR
        # comparables look like they came from SEC in the final PDF.
        _options = SOURCES if _current_src in SOURCES else [_current_src] + SOURCES
        st.session_state.comparables[i]["source"] = st.selectbox(
            f"s{i}", _options, index=0 if _current_src not in SOURCES else SOURCES.index(_current_src),
            key=f"cs_{i}", label_visibility="collapsed")
    with cd:
        if len(st.session_state.comparables) > 3:
            if st.button("✕", key=f"del_{i}"):
                st.session_state.comparables.pop(i); st.rerun()

col_add, col_clr = st.columns([2,1])
with col_add:
    if st.button(L["add_comparable"]):
        st.session_state.comparables.append({"name":"","value":0.0,"source":"SEC EDGAR"}); st.rerun()
with col_clr:
    clr_lbl = "🧹 Limpar em branco" if is_pt else "🧹 Clear blank rows"
    if st.button(clr_lbl, key="clr_blank"):
        st.session_state.comparables = [c for c in st.session_state.comparables if c["value"] != 0.0 or c["name"].strip() != ""]
        st.rerun()

# ── TESTED PARTY ──────────────────────────────────────────────────────────────
st.divider()
include_tested = st.checkbox(L["include_tested"], value=True)
tested_value = None
tested_price = None
if include_tested:
    if any(x in method for x in ["PRL", "MCL"]):
        st.markdown(f'<div style="color:#6B7280;font-size:12px;margin-bottom:.3rem">{"O teste arm\'s length oficial é da margem (Art. 39 e Art. 41 da IN RFB 2.161/2023). O preço é derivação informativa." if is_pt else "Official arm\'s length test is on the margin (Art. 39 and Art. 41 of IN RFB 2.161/2023). Price is informative derivation."}</div>', unsafe_allow_html=True)
        tv_c1, tv_c2 = st.columns(2)
        with tv_c1:
            tested_value = st.number_input(
                f"{L['tested_value']} — {pli_label_display} {('(obrigatório)' if is_pt else '(required)')}",
                value=0.0, step=0.0001, format="%.4f", key="tv_margin")
        with tv_c2:
            tested_price = st.number_input(
                f"{('Preço de Transação Realizada' if is_pt else 'Realized Transaction Price')} ({currency}) {('(opcional)' if is_pt else '(optional)')}",
                value=0.0, step=0.0001, format="%.4f", key="tv_price")
    else:
        tv_c, _ = st.columns([2,2])
        with tv_c:
            tested_value = st.number_input(f"{L['tested_value']} — {pli_label_display}",
                                            value=0.0, step=0.0001, format="%.4f")

# ── CALCULATE ─────────────────────────────────────────────────────────────────
st.markdown("<br>", unsafe_allow_html=True)
if st.button(L["calc_btn"], width="stretch"):
    valid_comps = [c for c in st.session_state.comparables if c["value"] != 0.0]
    if len(valid_comps) < 3:
        st.error("⚠️ Insira pelo menos 3 comparáveis com valores diferentes de zero (mínimo absoluto para cálculo do IQR)." if is_pt else "⚠️ Please enter at least 3 comparables with non-zero values (minimum for IQR calculation).")
    else:
        # IN RFB 2.161/2023 recomenda preferencialmente 5+ comparáveis. Calcula com 3-4 mas avisa.
        if 3 <= len(valid_comps) < 5:
            st.warning(
                f"⚠️ **Apenas {len(valid_comps)} comparáveis informados.** "
                f"A IN RFB 2.161/2023 recomenda preferencialmente **5 ou mais comparáveis** para garantir robustez estatística do intervalo arm's length. "
                f"O cálculo prosseguirá com {len(valid_comps)} comparáveis, mas a robustez estatística e a defensibilidade legal do resultado podem ser reduzidas. "
                f"Considere adicionar mais comparáveis antes de usar este resultado em documentação oficial."
                if is_pt else
                f"⚠️ **Only {len(valid_comps)} comparables provided.** "
                f"IN RFB 2.161/2023 preferably requires **5+ comparables** for statistical robustness of the arm's length range. "
                f"Calculation will proceed with {len(valid_comps)} comparables, but statistical robustness and legal defensibility may be reduced. "
                f"Consider adding more comparables before using this result in official documentation."
            )
        vals = [c["value"] for c in valid_comps]
        tv = tested_value if include_tested else None
        try:
            if "MLT" in method:
                df = pd.DataFrame({"name":[c["name"] for c in valid_comps], pli_option: vals})
                iqr_result = calculate_tnmm(df, pli_option, tv)
            elif "PIC" in method:
                iqr_result = calculate_pic(vals, tv, currency)
            elif "PRL" in method:
                res = calculate_prl_margin_range(vals, resale_price_val, None)
                iqr_result = res["iqr"]
                iqr_result.tested_party_value = tv
                if tv is not None:
                    iqr_result.is_arms_length = (iqr_result.q1 <= tv <= iqr_result.q3)
                    if not iqr_result.is_arms_length:
                        iqr_result.adjustment_needed = iqr_result.median - tv
                from calculations.base import IQRResult
                p_q1, p_med, p_q3 = res["price_range"]
                derived_prices = [resale_price_val * (1 - m/100) for m in vals]
                _tp = tested_price if tested_price not in (None, 0.0) else None
                _is_in_price_range = (p_q1 <= _tp <= p_q3) if _tp is not None else None
                price_iqr = IQRResult(
                    q1=p_q1, median=p_med, q3=p_q3,
                    min_val=min(derived_prices), max_val=max(derived_prices),
                    values=derived_prices,
                    tested_party_value=_tp,
                    is_arms_length=_is_in_price_range,
                    adjustment_needed=(p_med - _tp) if (_tp is not None and _is_in_price_range is False) else None,
                    method="PRL — Faixa de Preço Derivada (informativa)",
                    pli=f"Preço ({currency})"
                )
                st.session_state["price_iqr_result"] = price_iqr
                st.session_state["price_currency"] = currency
                st.session_state["derived_prices_pairs"] = [
                    {"name": c["name"] or f"C{i+1}",
                     "margin": c["value"],
                     "price": resale_price_val * (1 - c["value"]/100),
                     "source": c["source"]}
                    for i, c in enumerate(valid_comps)
                ]
            elif "MCL" in method:
                res = calculate_mcm_markup_range(vals, cost_base_val, None)
                iqr_result = res["iqr"]
                iqr_result.tested_party_value = tv
                if tv is not None:
                    iqr_result.is_arms_length = (iqr_result.q1 <= tv <= iqr_result.q3)
                    if not iqr_result.is_arms_length:
                        iqr_result.adjustment_needed = iqr_result.median - tv
                from calculations.base import IQRResult
                p_q1, p_med, p_q3 = res["price_range"]
                derived_prices = [cost_base_val * (1 + m/100) for m in vals]
                _tp = tested_price if tested_price not in (None, 0.0) else None
                _is_in_price_range = (p_q1 <= _tp <= p_q3) if _tp is not None else None
                price_iqr = IQRResult(
                    q1=p_q1, median=p_med, q3=p_q3,
                    min_val=min(derived_prices), max_val=max(derived_prices),
                    values=derived_prices,
                    tested_party_value=_tp,
                    is_arms_length=_is_in_price_range,
                    adjustment_needed=(p_med - _tp) if (_tp is not None and _is_in_price_range is False) else None,
                    method="MCL — Faixa de Preço Derivada (informativa)",
                    pli=f"Preço ({currency})"
                )
                st.session_state["price_iqr_result"] = price_iqr
                st.session_state["price_currency"] = currency
                st.session_state["derived_prices_pairs"] = [
                    {"name": c["name"] or f"C{i+1}",
                     "markup": c["value"],
                     "price": cost_base_val * (1 + c["value"]/100),
                     "source": c["source"]}
                    for i, c in enumerate(valid_comps)
                ]
            elif "PCI" in method:
                iqr_result = calculate_pci_pecex(vals, tv, "import", currency)
            else:
                iqr_result = calculate_pci_pecex(vals, tv, "export", currency)

            if not any(x in method for x in ["PRL", "MCL"]):
                st.session_state.pop("price_iqr_result", None)
                st.session_state.pop("derived_prices_pairs", None)
                st.session_state.pop("price_currency", None)

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
            _event_payload = {
                "method": method.split("—")[0].strip(),
                "pli": pli_option,
                "n_comparables": len(valid_comps),
            }
            if any(x in method for x in ["PRL", "MCL"]):
                _event_payload["tested_margin"] = tv
                _event_payload["tested_price"] = tested_price
            else:
                _event_payload["tested_value"] = tv
            _log_event("benchmark_calculated", _event_payload)
            st.success("✅ Cálculo concluído!" if is_pt else "✅ Calculation complete!")
        except Exception as e:
            st.error(f"Erro: {e}")

# ── RESULTS ───────────────────────────────────────────────────────────────────
if "iqr_result" in st.session_state:
    iqr = st.session_state["iqr_result"]
    vc  = st.session_state["valid_comps"]
    meta= st.session_state["meta"]
    price_iqr_state = st.session_state.get("price_iqr_result")
    price_currency_state = st.session_state.get("price_currency", "")

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

    if price_iqr_state is not None:
        st.markdown(f"### {'Bloco 1 — Margens (teste arm\'s length oficial)' if is_pt else 'Block 1 — Margins (official arm\'s length test)'}")
        st.markdown(f'<div style="color:#6B7280;font-size:13px;margin-bottom:.5rem">{"Indicador testado conforme IN RFB 2.161/2023 (Art. 39 PRL · Art. 41 MCL). O status acima é decidido por este bloco." if is_pt else "Indicator tested per IN RFB 2.161/2023 (Art. 39 PRL · Art. 41 MCL). The status above is decided by this block."}</div>', unsafe_allow_html=True)

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
        st.plotly_chart(fig, width="stretch")

    with tc:
        st.markdown(f"**{'Conjunto de Comparáveis' if is_pt else 'Comparable Set'}**")
        st.dataframe(pd.DataFrame([{"#":i+1,("Empresa" if is_pt else "Company"):c["name"] or f"C{i+1}",
                                     pli_label_display:f"{c['value']:.4f}",
                                     ("Fonte" if is_pt else "Source"):c["source"]}
                                    for i,c in enumerate(vc)]),
                     hide_index=True, width="stretch",
                     height=min(60+len(vc)*38,380))
        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown(f"**{'Estatísticas' if is_pt else 'Statistics'}**")
        st.dataframe(pd.DataFrame({"":["Min","Q1","Median","Q3","Max","Std Dev","n"],
                                    "Valor":[f"{iqr.min_val:.4f}",f"{iqr.q1:.4f}",f"{iqr.median:.4f}",
                                             f"{iqr.q3:.4f}",f"{iqr.max_val:.4f}",
                                             f"{np.std(iqr.values):.4f}",str(len(iqr.values))]}),
                     hide_index=True, width="stretch")

    if price_iqr_state is not None:
        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown(f"### {'Bloco 2 — Faixa de Preços Derivada (informativa)' if is_pt else 'Block 2 — Derived Price Range (informative)'}")
        st.markdown(f'<div style="color:#6B7280;font-size:13px;margin-bottom:.5rem">{"Derivada de Preço de Revenda × (1 − margem) ou Custo × (1 + markup). Útil para precificação prospectiva — <b>não é o teste arm\'s length oficial</b>." if is_pt else "Derived from Resale × (1 − margin) or Cost × (1 + markup). Useful for prospective pricing — <b>not the official arm\'s length test</b>."}</div>', unsafe_allow_html=True)

        piqr = price_iqr_state
        cur = price_currency_state
        dpp = st.session_state.get("derived_prices_pairs", [])

        pm1, pm2, pm3, pm4 = st.columns(4)
        for col, lbl, val, sub in [
            (pm1, f"Q1 ({cur})", f"{piqr.q1:.4f}", "Limite inferior" if is_pt else "Lower bound"),
            (pm2, f"Mediana ({cur})", f"{piqr.median:.4f}", "Ponto médio" if is_pt else "Midpoint"),
            (pm3, f"Q3 ({cur})", f"{piqr.q3:.4f}", "Limite superior" if is_pt else "Upper bound"),
            (pm4, f"IQR ({cur})", f"{piqr.q3-piqr.q1:.4f}", "Amplitude")]:
            with col:
                st.markdown(f'<div class="metric-card"><div class="metric-label">{lbl}</div><div class="metric-value">{val}</div><div style="font-size:11px;color:#9CA3AF">{sub}</div></div>', unsafe_allow_html=True)

        if piqr.tested_party_value is not None:
            in_range_text = ("dentro" if piqr.is_arms_length else "fora") if is_pt else ("inside" if piqr.is_arms_length else "outside")
            color = "#16A34A" if piqr.is_arms_length else "#DC2626"
            st.markdown(f'<div style="margin-top:.8rem;padding:.5rem .8rem;background:#F9FAFB;border-left:3px solid {color};font-size:13px;color:#374151">{"Preço realizado " if is_pt else "Realized price "}<b>{piqr.tested_party_value:.4f} {cur}</b>{" está " if is_pt else " is "}<b style="color:{color}">{in_range_text}</b>{" da faixa derivada (informativo)." if is_pt else " of the derived range (informative)."}</div>', unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)
        pch, ptc = st.columns([3, 2])

        with pch:
            st.markdown(f"**{'Distribuição dos Preços Derivados' if is_pt else 'Derived Prices Distribution'} ({cur})**")
            paired_p = sorted(zip(piqr.values, [d["name"] for d in dpp]))
            psv = [p[0] for p in paired_p]
            psn = [p[1] for p in paired_p]
            fig_p = go.Figure()
            fig_p.add_shape(type="rect", x0=-0.5, x1=len(psv)-.5, y0=piqr.q1, y1=piqr.q3,
                          fillcolor="rgba(45,106,79,.10)", line=dict(color="rgba(45,106,79,.25)", width=1))
            for yv, lb, ds in [(piqr.q1,"Q1","dash"),(piqr.median,"Median","solid"),(piqr.q3,"Q3","dash")]:
                fig_p.add_shape(type="line", x0=-0.5, x1=len(psv)-.5, y0=yv, y1=yv,
                              line=dict(color="#2D6A4F", width=1.5, dash=ds))
                fig_p.add_annotation(x=len(psv)-.4, y=yv, text=f"{lb}: {yv:.4f}", showarrow=False,
                                   font=dict(size=10, color="#2D6A4F"), xanchor="left")
            fig_p.add_trace(go.Scatter(x=psn, y=psv, mode="markers",
                                      marker=dict(size=13, color="#2D6A4F", line=dict(color="white",width=2)),
                                      name="Comparáveis", hovertemplate="<b>%{x}</b><br>%{y:.4f}<extra></extra>"))
            if piqr.tested_party_value is not None:
                tpc_p = "#16A34A" if piqr.is_arms_length else "#DC2626"
                tpn_p = meta.get("tested_party_name") or "Tested Party"
                fig_p.add_trace(go.Scatter(x=[tpn_p], y=[piqr.tested_party_value], mode="markers",
                                          marker=dict(size=17, color=tpc_p, symbol="diamond",
                                                      line=dict(color="white",width=2)),
                                          name=tpn_p, hovertemplate=f"<b>{tpn_p}</b><br>{piqr.tested_party_value:.4f}<extra></extra>"))
            fig_p.update_layout(plot_bgcolor="white", paper_bgcolor="white",
                              font=dict(family="Inter,sans-serif",size=12,color="#374151"),
                              xaxis=dict(showgrid=False, zeroline=False),
                              yaxis=dict(showgrid=True, gridcolor="#F3F4F6", zeroline=False,
                                         title=dict(text=f"Preço ({cur})",font=dict(size=11))),
                              legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
                              margin=dict(l=20,r=90,t=40,b=20), height=390)
            st.plotly_chart(fig_p, width="stretch", key="chart_price_iqr")

        with ptc:
            st.markdown(f"**{'Comparáveis — Margem → Preço' if is_pt else 'Comparables — Margin → Price'}**")
            mkey = "margin" if (dpp and "margin" in dpp[0]) else "markup"
            mlabel = ("Margem %" if mkey == "margin" else "Markup %") if is_pt else ("Margin %" if mkey == "margin" else "Markup %")
            st.dataframe(pd.DataFrame([{
                "#": i+1,
                ("Empresa" if is_pt else "Company"): d["name"],
                mlabel: f"{d[mkey]:.4f}",
                f"Preço ({cur})": f"{d['price']:.4f}",
                ("Fonte" if is_pt else "Source"): d["source"]
            } for i, d in enumerate(dpp)]),
                hide_index=True, width="stretch",
                height=min(60+len(dpp)*38, 380))

    st.divider()
    st.markdown(f"### {'📄 Relatório PDF' if is_pt else '📄 PDF Report'}")
    st.markdown(f'<div class="info-box">{"Relatório formatado conforme IN RFB 2.161/2023 — inclui dados da transação, intervalo IQR, comparáveis e nota metodológica." if is_pt else "Report formatted per IN RFB 2.161/2023 — includes transaction data, IQR range, comparables and methodology note."}</div>', unsafe_allow_html=True)
    try:
        pdf_bytes = generate_report({**meta, "iqr_result": iqr, "comparables": vc,
                                      "tested_party_value": iqr.tested_party_value})
        slug = (meta.get("company_name") or "analysis").replace(" ","-").lower()
        _log_event("pdf_generated", {
            "method": method.split("—")[0].strip(),
            "pli": pli_option,
            "company": meta.get("company_name", ""),
        })
        st.download_button(label=L["download_pdf"], data=pdf_bytes,
                           file_name=f"algoritimado-tp-{slug}-{datetime.now().strftime('%Y%m%d')}.pdf",
                           mime="application/pdf", width="stretch")
    except Exception as e:
        st.warning(f"PDF: {e}")

st.divider()
st.markdown('<div style="text-align:center;font-size:12px;color:#9CA3AF;padding:1rem 0"><strong style="color:#1B4332">ALGORITIMADO</strong> · Transfer Pricing Intelligence Platform · MVP v0.1<br>Lei 14.596/2023 · IN RFB 2.161/2023 · OECD Transfer Pricing Guidelines<br><a href="https://algoritimado.com" style="color:#2D6A4F">algoritimado.com</a> · Esta plataforma não substitui laudo assinado por profissional habilitado</div>', unsafe_allow_html=True)
