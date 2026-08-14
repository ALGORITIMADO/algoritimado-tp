import requests
import pandas as pd
import streamlit as st
import io
import unicodedata
import zipfile
from typing import Optional, List

from data.fiscal_calendar import latest_available_fiscal_year

CVM_BASE = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/DFP/DADOS"

# CNAE sector map — sector name → keywords for filtering
CNAE_MAP = {
    "Pharmaceutical / Farmacêutico":  ["FARMAC", "MEDIC", "LABORAT", "BIOMED"],
    # A CVM não tem balde de biotecnologia: classifica a Biomm, que é biotech, como
    # "Farmacêutico e Higiene". Sem FARMAC aqui o setor devolvia zero comparável
    # doméstico — e comparável doméstico é o que o art. 23 da IN 2.161 prioriza.
    "Biotech / Biotecnologia":        ["BIOTEC", "BIOLOG", "GENOMA", "FARMAC"],
    "Cannabis / Cannabis Medicinal":  ["CANNABIS", "CANABIS", "MACONHA", "CANABIDIOL", "CBD"],
    "Agriculture / Agronegócio":      ["AGRO", "AGRICOL", "CULTIVO", "RURAL", "GRAOS", "CANA"],
    "AgTech / Tecnologia Agrícola":   ["AGRO", "IRRIGAC", "SEMENTES", "FERTIL"],
    "Food & Beverage / Alimentos":    ["ALIMENT", "BEBID", "FRIGORI", "LATICIN", "ACUCAR"],
    # Mesma história: a Natura está sob "Farmacêutico e Higiene" no cadastro da CVM.
    "Cosmetics / Cosméticos":         ["COSMETIC", "BELEZA", "PERFUMARIA", "HIGIENE", "NATURA", "BOTICARIO"],
    "Chemicals / Química":            ["QUIMIC", "PETROQUIM", "RESINAS", "FERTILIZ"],
    "Oil & Gas / Petróleo e Gás":     ["PETROLEO", "GAS", "PETROQ", "COMBUSTIV"],
    "Software / Tecnologia":          ["TECNOL", "SOFTWARE", "INFORM", "DIGITAL", "DADOS"],
    "Medical Devices / Dispositivos": ["HOSPITAL", "MEDIC", "ORTOP", "IMPLANT"],
    "Healthcare / Saúde":             ["SAUDE", "HOSPITAL", "CLINIC", "DIAGNOST"],
    "Education / Educação":           ["EDUCAC", "ENSINO", "ESCOL", "UNIVERS", "COGNA", "YDUQS", "ANIMA"],
    "Financial Services / Financeiro":["FINANC", "BANCO", "CREDITO", "SEGURO"],
    "Manufacturing / Manufatura":     ["INDUSTRI", "MANUFAT", "FABRIC", "METALURG"],
    "Retail / Varejo":                ["VAREJO", "COMERCIO", "SUPERM", "LOJA"],
    "Real Estate / Imobiliário":      ["IMOBILI", "INCORPOR", "CONSTRUTOR", "EMPREENDIM", "SHOPPING"],
    "Sanitation / Saneamento":        ["SANEAM", "SABESP", "SANEPAR", "AGUA", "ESGOTO"],
    "Energy / Energia":               ["ENERG", "ELETRIC", "SOLAR", "EOLICA"],
    "Mining / Mineração":             ["MINER", "EXTRATIV", "MINERIO", "CARBO"],
    "Logistics / Logística":          ["LOGIST", "TRANSPORT", "ARMAZ", "CARGA"],
    # Telecom estava só no SIC_MAP (EDGAR) desde o commit original e nunca teve
    # balde aqui. Como o dropdown é a união dos dois mapas, escolher Telecom caía
    # no ramo "setor não mapeado" e a CVM devolvia o começo alfabético do cadastro
    # como se fossem comparáveis do setor.
    "Telecom / Telecomunicações":     ["TELECOM", "TELEFON", "COMUNICAC", "CELULAR"],
}

# DRE account codes (CVM standard). Verified 28/07/2026 against the filed DFP of
# Blau Farmacêutica (CD_CVM 24627, FY2024) and cross-checked across all 467
# companies in dfp_cia_aberta_DRE_con_2024:
#
#   3.01  Receita de Venda de Bens e/ou Serviços                    → revenue
#   3.02  Custo dos Bens e/ou Serviços Vendidos
#   3.03  Resultado Bruto                                           → gross profit
#   3.04  Despesas/Receitas Operacionais
#   3.05  Resultado Antes do Resultado Financeiro e dos Tributos    → EBIT
#   3.06  Resultado Financeiro
#   3.07  Resultado Antes dos Tributos sobre o Lucro                → EBT, NOT EBIT
#   3.11  Lucro/Prejuízo Consolidado do Período                     → net income
#
# This map used to read 3.05 as gross profit and 3.07 as EBIT — off by one rung of
# the ladder, so every Brazilian comparable reported its OPERATING margin as gross
# and its PRE-TAX margin as operating (median error 17.5 p.p. and 8.6 p.p.).
#
# Banks and insurers shift the ladder (their 3.05 is already "antes dos tributos"),
# so each code also carries the label it must match: the code alone is not enough.
ACCOUNT_MAP = {
    "3.01": ("revenue", None),
    "3.03": ("gross_profit", "RESULTADO BRUTO"),
    "3.05": ("ebit", "ANTES DO RESULTADO FINANCEIRO"),
    "3.11": ("net_income", None),
}


def _norm_label(s) -> str:
    """Upper-case, accent-stripped account label for robust matching."""
    return unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().upper()


# Sectors the CVM's taxonomy does not carry, answered from the nearest bucket the
# regulator actually uses. Surfaced to the user: a widened search the analyst
# doesn't know about is a comparability problem waiting to happen.
CVM_SECTOR_FALLBACK = {
    "Biotech / Biotecnologia": "Farmacêutico e Higiene",
    "Cosmetics / Cosméticos": "Farmacêutico e Higiene",
}


@st.cache_data(ttl=86400, show_spinner=False)
def download_cvm_dre_v2(year: Optional[int] = None) -> Optional[pd.DataFrame]:
    """
    Download CVM DRE (Income Statement) data for a given year.
    CVM bundles every DFP statement (BPA/BPP/DRE/DFC/...) inside
    a single dfp_cia_aberta_{year}.zip — extract the consolidated DRE.
    """
    year = year or latest_available_fiscal_year()
    url = f"{CVM_BASE}/dfp_cia_aberta_{year}.zip"
    try:
        resp = requests.get(url, timeout=60)
        if resp.status_code != 200:
            return None
        with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
            target = f"dfp_cia_aberta_DRE_con_{year}.csv"
            names = z.namelist()
            if target not in names:
                target = next((n for n in names if "DRE_ind" in n), None)
                if not target:
                    return None
            with z.open(target) as f:
                df = pd.read_csv(f, sep=";", encoding="latin-1", low_memory=False)
        return df
    except Exception:
        return None


@st.cache_data(ttl=86400, show_spinner=False)
def get_cvm_doc_links(year: Optional[int] = None) -> dict:
    """Map CD_CVM -> official DFP document link for the year.

    The DFP zip's index file (dfp_cia_aberta_{year}.csv) carries a LINK_DOC column
    pointing to the official CVM document download (a package with the DFP PDF +
    XMLs). This is the audit-trail source link for Brazilian comparables — unlike
    the RAD search form, it opens the actual filed document. Keeps the latest
    version per company.
    """
    year = year or latest_available_fiscal_year()
    url = f"{CVM_BASE}/dfp_cia_aberta_{year}.zip"
    try:
        resp = requests.get(url, timeout=90)
        if resp.status_code != 200:
            return {}
        with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
            head = f"dfp_cia_aberta_{year}.csv"
            if head not in z.namelist():
                return {}
            with z.open(head) as f:
                idx = pd.read_csv(f, sep=";", encoding="latin-1", low_memory=False)
        idx = idx[idx["CATEG_DOC"] == "DFP"].sort_values("VERSAO") \
                 .drop_duplicates("CD_CVM", keep="last")
        out = {}
        for _, r in idx.iterrows():
            link = str(r.get("LINK_DOC", "") or "").strip().replace("http://", "https://")
            if link:
                out[int(r["CD_CVM"])] = link
        return out
    except Exception:
        return {}


# Emitter states that disqualify a company as a comparable, matched as substrings
# of the CVM's own `SIT_EMISSOR` field (accent/case-insensitive) so a relabelling
# upstream doesn't silently let them back in. Of the 663 active registrants in
# 2026: 21 in judicial recovery, 15 pre-operational, 5 in extrajudicial
# liquidation, 2 bankrupt, 2 dormant — 615 remain in FASE OPERACIONAL.
NON_COMPARABLE_EMITTER_STATES = ("RECUPERA", "FALID", "LIQUIDA", "PARALISA", "PRE-OPERACIONAL")


def _only_active_companies(df: pd.DataFrame) -> pd.DataFrame:
    """Keep only registrants that are alive AND operating, one row each.

    Two filters, both on official CVM fields:

    `SIT` — the registry lists every company that EVER registered: 1,912 of its
    2,677 rows are CANCELADA. Keeping them poisons the candidate pool, because the
    search takes the first N keyword matches; in "Manufatura" 220 of the 259
    matches were long-dead registrations with no DFP to fetch, which is why a
    sector that broad came back with two comparables instead of fifteen.

    `SIT_EMISSOR` — a company in judicial recovery, bankrupt, in liquidation,
    dormant or pre-operational is not operating under normal market conditions,
    so its margin is not an arm's length benchmark (Bardella at -50.34% and
    Americanas were sitting in the set). Excluding them on the regulator's own
    published flag keeps the criterion auditable in the report — which is the
    point: an exclusion a reviewer can verify beats one a model asserted.
    """
    if df is None or df.empty:
        return df
    if "SIT" in df.columns:
        df = df[df["SIT"].astype(str).str.strip().str.upper() == "ATIVO"]
    if "SIT_EMISSOR" in df.columns:
        estado = df["SIT_EMISSOR"].map(_norm_label)
        df = df[~estado.str.contains("|".join(NON_COMPARABLE_EMITTER_STATES),
                                     regex=True, na=False)]
    if "CD_CVM" in df.columns:
        df = df.drop_duplicates(subset=["CD_CVM"], keep="last")
    return df.reset_index(drop=True)


@st.cache_data(ttl=86400, show_spinner=False)
def get_cvm_company_list(year: Optional[int] = None) -> Optional[pd.DataFrame]:
    """Get list of CVM registered companies (active only) with sector info."""
    url = f"https://dados.cvm.gov.br/dados/CIA_ABERTA/CAD/DADOS/cad_cia_aberta.csv"
    try:
        resp = requests.get(url, timeout=30)
        df = pd.read_csv(io.StringIO(resp.content.decode("latin-1")),
                         sep=";", low_memory=False)
        return _only_active_companies(df)
    except Exception:
        return None


def search_companies_cvm(
    industry: Optional[str] = None,
    cnpj: Optional[str] = None,
    company_name: Optional[str] = None,
    limit: int = 20
) -> pd.DataFrame:
    """Search CVM registered companies by industry keywords or name."""
    cad = get_cvm_company_list()
    if cad is None or cad.empty:
        return pd.DataFrame()

    # Identify name column
    name_col = None
    for col in ["DENOM_SOCIAL", "DENOM_CIA", "NM_CIA"]:
        if col in cad.columns:
            name_col = col
            break
    if not name_col:
        return pd.DataFrame()

    filtered = cad.copy()

    # Accent-insensitive matching on BOTH sides. The CVM's own sector vocabulary is
    # accented — "Petroquímicos e Borracha", "Farmacêutico e Higiene", "Serviços
    # Médicos" — while the keywords are plain ASCII, so "QUIMIC" never matched
    # "Petroquímicos" and the Chemicals sector returned zero Brazilian comparables.
    nome_norm = filtered[name_col].map(_norm_label)

    if company_name:
        filtered = filtered[nome_norm.str.contains(
            _norm_label(company_name), regex=False, na=False)]
        nome_norm = nome_norm.loc[filtered.index]

    if industry and industry not in CNAE_MAP:
        # The dropdown is the union of SIC_MAP and CNAE_MAP, so a sector can be
        # offered while having no CVM keyword bucket. Falling through used to
        # skip the filter entirely and hand back the alphabetical head of the
        # registry — 45 unrelated companies presented as sector comparables.
        # Silence is the wrong answer here, but a wrong answer is worse: with no
        # bucket we cannot say anything about this sector, so return nothing and
        # let the caller's "no companies found" notice do its job.
        if not company_name:
            return pd.DataFrame()

    elif industry:
        keywords = CNAE_MAP[industry]
        sector_cols = [c for c in filtered.columns if any(k in c.upper()
                       for k in ["SETOR", "ATIVID", "CNAE", "DESCR"])]
        por_nome = pd.Series([False] * len(filtered), index=filtered.index)
        for kw in keywords:
            por_nome |= nome_norm.str.contains(kw, regex=False, na=False)
        if sector_cols:
            por_setor = pd.Series([False] * len(filtered), index=filtered.index)
            for col in sector_cols[:3]:
                col_norm = filtered[col].map(_norm_label)
                for kw in keywords:
                    por_setor |= col_norm.str.contains(kw, regex=False, na=False)
            filtered = filtered[por_setor | por_nome]
        else:
            filtered = filtered[por_nome]

    # The CAD CSV often has multiple rows for the same company (different
    # CD_CVM as the company re-registered, share class splits, etc.). Dedupe
    # by company name so Auto Search doesn't show Eurofarma three times.
    filtered = filtered.drop_duplicates(subset=[name_col], keep="first")

    # Get CNPJ column
    cnpj_col = next((c for c in filtered.columns if "CNPJ" in c.upper()), None)
    cod_col = next((c for c in filtered.columns
                   if any(k in c.upper() for k in ["CD_CVM", "COD_CVM", "CODIGO"])), None)

    cols = [name_col]
    if cnpj_col:
        cols.append(cnpj_col)
    if cod_col:
        cols.append(cod_col)

    return filtered[cols].head(limit).reset_index(drop=True)


def calculate_margins_cvm(
    dre_df: pd.DataFrame,
    company_code: str,
    code_col: str = "CD_CVM"
) -> Optional[dict]:
    """Calculate margins for a specific company from DRE data."""
    try:
        company_dre = dre_df[dre_df[code_col].astype(str) == str(company_code)]
        if company_dre.empty:
            return None

        # Get most recent exercise. MUST prefer DT_FIM_EXERC (the period END):
        # a year's DFP file carries BOTH the current exercise (ORDEM=ÚLTIMO, e.g.
        # 2025-12-31) AND the prior-year comparative (PENÚLTIMO, 2024-12-31), and
        # both share the same DT_REFER. Picking DT_REFER would not separate them,
        # leaving .iloc[0] to grab the prior year. DT_FIM_EXERC + max() isolates
        # the requested year.
        date_col = (next((c for c in company_dre.columns if "DT_FIM" in c.upper()), None)
                    or next((c for c in company_dre.columns
                             if any(k in c.upper() for k in ["DT_REFER", "ANO"])), None))
        val_col = next((c for c in company_dre.columns
                       if any(k in c.upper() for k in ["VL_CONTA", "VALOR"])), None)
        acc_col = next((c for c in company_dre.columns
                       if any(k in c.upper() for k in ["CD_CONTA", "CONTA"])), None)

        if not all([val_col, acc_col]):
            return None

        if date_col:
            latest_date = company_dre[date_col].max()
            company_dre = company_dre[company_dre[date_col] == latest_date]

        # CVM reports figures in a scale (ESCALA_MOEDA): "MIL" = thousands of BRL,
        # "UNIDADE" = units. Margins are scale-invariant, but the absolute figures
        # shown in the report's breakdown must be scaled to real BRL.
        esc_col = next((c for c in company_dre.columns if "ESCALA" in c.upper()), None)
        scale = 1.0
        if esc_col and not company_dre.empty:
            if "MIL" in str(company_dre[esc_col].iloc[0]).upper():
                scale = 1000.0

        desc_col = next((c for c in company_dre.columns if "DS_CONTA" in c.upper()), None)
        codes = company_dre[acc_col].astype(str).str.strip()

        values = {}
        for acc_code, (acc_name, required_label) in ACCOUNT_MAP.items():
            # Exact code match, never startswith: "3.01" also prefixes "3.01.01"
            # (sub-accounts), and the first sub-account is not the total.
            rows = company_dre[codes == acc_code]
            if rows.empty:
                continue
            # Confirm the code means what we think it means. Financial institutions
            # publish a different DRE ladder under the same codes — matching the
            # label keeps a bank's pre-tax result from being served as EBIT.
            if required_label and desc_col:
                rows = rows[rows[desc_col].map(
                    lambda s: required_label in _norm_label(s))]
                if rows.empty:
                    continue
            val = pd.to_numeric(rows[val_col].iloc[0], errors="coerce")
            if pd.notna(val):
                values[acc_name] = float(val) * scale

        if "revenue" not in values or values["revenue"] == 0:
            return None

        rev = values["revenue"]
        margins = {}
        if "gross_profit" in values:
            margins["gross_margin"] = round(values["gross_profit"] / rev * 100, 4)
            margins["gross_profit_brl"] = values["gross_profit"]
        if "ebit" in values:
            margins["operating_margin"] = round(values["ebit"] / rev * 100, 4)
            margins["ebit_brl"] = values["ebit"]
        if "net_income" in values:
            margins["net_margin"] = round(values["net_income"] / rev * 100, 4)
            margins["net_income_brl"] = values["net_income"]
        margins["revenue_brl"] = rev
        return margins if margins else None

    except Exception:
        return None


def _pli_breakdown_cvm(m: dict, pli: str) -> Optional[dict]:
    """'Show the math' breakdown for a CVM comparable (BRL). DRE 3.05 (EBIT) maps
    to operating, 3.11 net income, 3.03 gross profit. CVM has no D&A split → no EBITDA."""
    rev = m.get("revenue_brl")
    if not rev:
        return None
    if pli == "operating_margin" and m.get("ebit_brl") is not None:
        return {"kind": "operating", "num": m["ebit_brl"], "den": rev,
                "margin": m["operating_margin"], "currency": "BRL"}
    if pli == "net_margin" and m.get("net_income_brl") is not None:
        return {"kind": "net", "num": m["net_income_brl"], "den": rev,
                "margin": m["net_margin"], "currency": "BRL"}
    if pli == "gross_margin" and m.get("gross_profit_brl") is not None:
        return {"kind": "gross", "num": m["gross_profit_brl"], "den": rev,
                "margin": m["gross_margin"], "currency": "BRL"}
    return None


def fetch_comparables_cvm(
    industry: Optional[str] = None,
    company_name: Optional[str] = None,
    year: Optional[int] = None,
    limit: int = 15,
    pli: str = "operating_margin"
) -> pd.DataFrame:
    """
    Full CVM pipeline: search companies → download DRE → calculate margins.
    Returns ready-to-use comparables DataFrame.
    """
    year = year or latest_available_fiscal_year()
    companies = search_companies_cvm(industry=industry, company_name=company_name,
                                      limit=limit * 3)
    if companies.empty:
        return pd.DataFrame()

    dre = download_cvm_dre_v2(year)
    if dre is None:
        return pd.DataFrame()

    # Official DFP document links (audit trail) — maps CD_CVM -> LINK_DOC.
    doc_links = get_cvm_doc_links(year)

    # Identify key columns
    name_cols = [c for c in companies.columns if any(k in c.upper()
                 for k in ["DENOM", "NM_CIA", "NOME"])]
    code_cols = [c for c in companies.columns if any(k in c.upper()
                 for k in ["CD_CVM", "COD_CVM", "CODIGO"])]

    if not name_cols or not code_cols:
        return pd.DataFrame()

    name_col = name_cols[0]
    code_col = code_cols[0]

    # Find matching code column in DRE
    dre_code_col = next((c for c in dre.columns if any(k in c.upper()
                        for k in ["CD_CVM", "COD_CVM", "CODIGO"])), None)
    if not dre_code_col:
        return pd.DataFrame()

    results = []
    for _, row in companies.iterrows():
        if len(results) >= limit:
            break
        company_code = str(row[code_col])
        company_nm = str(row[name_col])
        margins = calculate_margins_cvm(dre, company_code, dre_code_col)
        if margins and pli in margins:
            # Audit trail: official CVM DFP document link (downloads the filed
            # DFP package — PDF + XMLs) from the open-data index. The earlier RAD
            # search-form link opened empty; this one opens the actual document.
            try:
                src_url = doc_links.get(int(float(company_code)), "")
            except (TypeError, ValueError):
                src_url = ""
            results.append({
                "name": company_nm,
                "value": margins[pli],
                "operating_margin": margins.get("operating_margin"),
                "net_margin": margins.get("net_margin"),
                "gross_margin": margins.get("gross_margin"),
                "source": f"CVM Brasil {year}",
                "source_url": src_url,
                "breakdown": _pli_breakdown_cvm(margins, pli),
            })

    if not results:
        return pd.DataFrame()

    df = pd.DataFrame(results)
    df = df.dropna(subset=["value"])
    df = df[df["value"].between(-100, 100)]
    return df.reset_index(drop=True)
