import requests
import pandas as pd
import streamlit as st
import io
import zipfile
from typing import Optional, List

CVM_BASE = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/DFP/DADOS"

# CNAE sector map — sector name → keywords for filtering
CNAE_MAP = {
    "Pharmaceutical / Farmacêutico":  ["FARMAC", "MEDIC", "LABORAT", "BIOMED"],
    "Biotech / Biotecnologia":        ["BIOTEC", "BIOLOG", "GENOMA"],
    "Cannabis / Cannabis Medicinal":  ["CANNABIS", "CANABIS", "MACONHA", "CANABIDIOL", "CBD"],
    "Agriculture / Agronegócio":      ["AGRO", "AGRICOL", "CULTIVO", "RURAL", "GRAOS", "CANA"],
    "AgTech / Tecnologia Agrícola":   ["AGRO", "IRRIGAC", "SEMENTES", "FERTIL"],
    "Food & Beverage / Alimentos":    ["ALIMENT", "BEBID", "FRIGORI", "LATICIN", "ACUCAR"],
    "Cosmetics / Cosméticos":         ["COSMETIC", "BELEZA", "PERFUMARIA", "HIGIENE PESSOAL", "NATURA", "BOTICARIO"],
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
}

# DRE account codes (CVM standard)
# 3.01 = Net Revenue
# 3.05 = Gross Profit (Resultado Bruto)
# 3.07 = EBIT (Resultado antes do financeiro)
# 3.11 = Net Income (Resultado Líquido)
ACCOUNT_MAP = {
    "3.01": "revenue",
    "3.05": "gross_profit",
    "3.07": "ebit",
    "3.11": "net_income",
}


@st.cache_data(ttl=86400, show_spinner=False)
def download_cvm_dre_v2(year: int = 2024) -> Optional[pd.DataFrame]:
    """
    Download CVM DRE (Income Statement) data for a given year.
    CVM bundles every DFP statement (BPA/BPP/DRE/DFC/...) inside
    a single dfp_cia_aberta_{year}.zip — extract the consolidated DRE.
    """
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
def get_cvm_company_list(year: int = 2023) -> Optional[pd.DataFrame]:
    """Get list of CVM registered companies with sector info."""
    url = f"https://dados.cvm.gov.br/dados/CIA_ABERTA/CAD/DADOS/cad_cia_aberta.csv"
    try:
        resp = requests.get(url, timeout=30)
        df = pd.read_csv(io.StringIO(resp.content.decode("latin-1")),
                         sep=";", low_memory=False)
        return df
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

    if company_name:
        mask = filtered[name_col].str.contains(company_name.upper(), na=False)
        filtered = filtered[mask]

    if industry and industry in CNAE_MAP:
        keywords = CNAE_MAP[industry]
        # Search in sector/activity columns
        sector_cols = [c for c in filtered.columns if any(k in c.upper()
                       for k in ["SETOR", "ATIVID", "CNAE", "DESCR"])]
        if sector_cols:
            mask = pd.Series([False] * len(filtered), index=filtered.index)
            for col in sector_cols[:3]:
                for kw in keywords:
                    mask |= filtered[col].astype(str).str.contains(kw, case=False, na=False)
            filtered = filtered[mask | filtered[name_col].str.contains(
                "|".join(keywords), case=False, na=False)]
        else:
            mask = filtered[name_col].str.contains("|".join(keywords), case=False, na=False)
            filtered = filtered[mask]

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

        # Get most recent exercise
        date_col = next((c for c in company_dre.columns
                        if any(k in c.upper() for k in ["DT_FIM", "DT_REFER", "ANO"])), None)
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

        values = {}
        for acc_code, acc_name in ACCOUNT_MAP.items():
            row = company_dre[company_dre[acc_col].astype(str).str.startswith(acc_code)]
            if not row.empty:
                val = pd.to_numeric(row[val_col].iloc[0], errors="coerce")
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
    """'Show the math' breakdown for a CVM comparable (BRL). DRE 3.07 (EBIT) maps
    to operating, 3.11 net income, 3.05 gross profit. CVM has no D&A split → no EBITDA."""
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
    year: int = 2023,
    limit: int = 15,
    pli: str = "operating_margin"
) -> pd.DataFrame:
    """
    Full CVM pipeline: search companies → download DRE → calculate margins.
    Returns ready-to-use comparables DataFrame.
    """
    companies = search_companies_cvm(industry=industry, company_name=company_name,
                                      limit=limit * 3)
    if companies.empty:
        return pd.DataFrame()

    dre = download_cvm_dre_v2(year)
    if dre is None:
        return pd.DataFrame()

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
            results.append({
                "name": company_nm,
                "value": margins[pli],
                "operating_margin": margins.get("operating_margin"),
                "net_margin": margins.get("net_margin"),
                "gross_margin": margins.get("gross_margin"),
                "source": f"CVM Brasil {year}",
                # 'Show the math' breakdown (BRL). CVM has no clean per-document
                # permalink yet, so source_url stays empty — link is a follow-up.
                "breakdown": _pli_breakdown_cvm(margins, pli),
            })

    if not results:
        return pd.DataFrame()

    df = pd.DataFrame(results)
    df = df.dropna(subset=["value"])
    df = df[df["value"].between(-100, 100)]
    return df.reset_index(drop=True)
