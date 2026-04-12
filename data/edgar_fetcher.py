import requests
import pandas as pd
import streamlit as st
import time
from typing import Optional, List, Dict

HEADERS = {"User-Agent": "Algoritimado research@algoritimado.com"}
EDGAR_BASE = "https://data.sec.gov"

# SIC code map — industry name → list of SIC codes
SIC_MAP = {
    "Pharmaceutical / Farmacêutico":     ["2830","2833","2834","2835","2836"],
    "Biotech / Biotecnologia":           ["2836","8731","2835"],
    "Agriculture / Agronegócio":         ["0100","0110","0111","0112","0115","0119","0130","0160","0170","0180","0190"],
    "AgTech / Tecnologia Agrícola":      ["0100","3523","7372"],
    "Food & Beverage / Alimentos":       ["2000","2010","2020","2030","2040","2050","2060","2070","2080","2090"],
    "Chemicals / Química":               ["2810","2820","2860","2870","2890"],
    "Oil & Gas / Petróleo e Gás":        ["1311","1381","1382","1389","2911"],
    "Software / Tecnologia":             ["7372","7371","7374","7379"],
    "Medical Devices / Dispositivos":    ["3840","3841","3842","3845"],
    "Healthcare / Saúde":                ["8000","8011","8049","8051","8062"],
    "Financial Services / Financeiro":   ["6020","6021","6022","6159","6199"],
    "Manufacturing / Manufatura":        ["3500","3510","3560","3570","3580","3590"],
    "Retail / Varejo":                   ["5900","5910","5912","5940","5945"],
    "Telecom / Telecomunicações":        ["4810","4812","4813","4899"],
    "Logistics / Logística":             ["4210","4213","4215","4220","4730"],
    "Mining / Mineração":                ["1000","1040","1090","1094","1400"],
    "Energy / Energia":                  ["4911","4931","4941","4991","5172"],
}


@st.cache_data(ttl=86400, show_spinner=False)
def get_edgar_company_list() -> pd.DataFrame:
    """Download full EDGAR company list with SIC codes. Cached 24h."""
    url = "https://www.sec.gov/files/company_tickers_exchange.json"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        df = pd.DataFrame(data["data"], columns=data["fields"])
        return df
    except Exception as e:
        return pd.DataFrame(columns=["cik", "name", "ticker", "exchange"])


def search_companies_edgar(
    industry: Optional[str] = None,
    sic_codes: Optional[List[str]] = None,
    company_name: Optional[str] = None,
    limit: int = 20
) -> pd.DataFrame:
    """
    Search EDGAR for companies matching criteria.
    Returns DataFrame with cik, name, ticker.
    """
    df = get_edgar_company_list()
    if df.empty:
        return df

    # Filter by SIC code if provided
    if sic_codes:
        sic_filter = "|".join(sic_codes)
        url = f"https://efts.sec.gov/EDGAR/search-index?q=%22%22&forms=10-K&dateRange=custom&startdt=2022-01-01&enddt=2024-12-31"
        # Use SIC-based search from EDGAR company search
        results = []
        for sic in sic_codes[:3]:  # limit to 3 SIC codes to avoid too many requests
            try:
                cgi_url = (f"https://www.sec.gov/cgi-bin/browse-edgar?"
                           f"action=getcompany&SIC={sic}&type=10-K&dateb=&owner=include"
                           f"&count={limit}&search_text=&output=atom")
                r = requests.get(cgi_url, headers=HEADERS, timeout=15)
                # Parse atom feed for company names and CIKs
                import re
                ciks = re.findall(r'CIK=(\d+)', r.text)
                names = re.findall(r'<company-name>(.*?)</company-name>', r.text)
                for cik, name in zip(ciks[:limit], names[:limit]):
                    results.append({"cik": int(cik), "name": name, "sic": sic})
                time.sleep(0.15)
            except Exception:
                continue
        if results:
            return pd.DataFrame(results).drop_duplicates("cik").head(limit)

    # Filter by company name
    if company_name and not df.empty:
        mask = df["name"].str.contains(company_name, case=False, na=False)
        return df[mask].head(limit)[["cik", "name", "ticker"]].reset_index(drop=True)

    return pd.DataFrame(columns=["cik", "name", "ticker"])


@st.cache_data(ttl=3600, show_spinner=False)
def get_company_facts(cik: int) -> Optional[Dict]:
    """Fetch XBRL company facts from EDGAR. Cached 1h."""
    cik_str = str(cik).zfill(10)
    url = f"{EDGAR_BASE}/api/xbrl/companyfacts/CIK{cik_str}.json"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        if resp.status_code == 200:
            return resp.json()
        return None
    except Exception:
        return None


def _get_latest_annual_value(gaap: Dict, fields: List[str]) -> Optional[float]:
    """Extract the most recent annual value for a list of possible GAAP fields."""
    for field in fields:
        if field in gaap:
            units = gaap[field].get("units", {}).get("USD", [])
            annual = [u for u in units
                      if u.get("form") in ("10-K", "20-F") and u.get("fp") == "FY"]
            if annual:
                annual.sort(key=lambda x: x.get("end", ""), reverse=True)
                val = annual[0].get("val")
                if val is not None and val != 0:
                    return float(val)
    return None


def extract_financials(facts: Dict) -> Optional[Dict]:
    """
    Extract key financial metrics from XBRL facts.
    Returns dict with operating_margin, ebitda_margin, net_margin, gross_margin, fiscal_year.
    """
    if not facts:
        return None
    gaap = facts.get("facts", {}).get("us-gaap", {})
    if not gaap:
        return None

    # Revenue
    revenue = _get_latest_annual_value(gaap, [
        "Revenues",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "SalesRevenueNet",
        "SalesRevenueGoodsNet",
        "RevenuesNetOfInterestExpense",
    ])

    if not revenue or revenue <= 0:
        return None

    # Operating income
    op_income = _get_latest_annual_value(gaap, [
        "OperatingIncomeLoss",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
    ])

    # Net income
    net_income = _get_latest_annual_value(gaap, [
        "NetIncomeLoss",
        "ProfitLoss",
        "NetIncomeLossAvailableToCommonStockholdersBasic",
    ])

    # Gross profit
    gross_profit = _get_latest_annual_value(gaap, [
        "GrossProfit",
    ])

    # EBITDA approximation: Operating income + D&A
    da = _get_latest_annual_value(gaap, [
        "DepreciationDepletionAndAmortization",
        "DepreciationAndAmortization",
        "Depreciation",
    ])

    result = {}
    if op_income is not None:
        result["operating_margin"] = round(op_income / revenue * 100, 4)
    if net_income is not None:
        result["net_margin"] = round(net_income / revenue * 100, 4)
    if gross_profit is not None:
        result["gross_margin"] = round(gross_profit / revenue * 100, 4)
    if op_income is not None and da is not None:
        result["ebitda_margin"] = round((op_income + da) / revenue * 100, 4)
    result["revenue_usd"] = revenue

    # Get fiscal year from entity info
    entity = facts.get("entityName", "")
    result["entity"] = entity

    return result if len(result) > 1 else None


def fetch_comparables_edgar(
    industry: Optional[str] = None,
    sic_codes: Optional[List[str]] = None,
    company_name: Optional[str] = None,
    limit: int = 15,
    pli: str = "operating_margin"
) -> pd.DataFrame:
    """
    Full pipeline: search → fetch facts → extract margins.
    Returns ready-to-use comparables DataFrame.
    """
    companies = search_companies_edgar(industry, sic_codes, company_name, limit * 2)

    if companies.empty:
        return pd.DataFrame()

    results = []
    progress_companies = companies.head(limit * 2)

    for _, row in progress_companies.iterrows():
        if len(results) >= limit:
            break
        cik = int(row["cik"])
        name = row.get("name", "")
        facts = get_company_facts(cik)
        if facts:
            fin = extract_financials(facts)
            if fin and pli in fin:
                results.append({
                    "name": name,
                    "value": fin[pli],
                    "operating_margin": fin.get("operating_margin"),
                    "net_margin": fin.get("net_margin"),
                    "gross_margin": fin.get("gross_margin"),
                    "ebitda_margin": fin.get("ebitda_margin"),
                    "source": "SEC EDGAR",
                    "cik": cik,
                })
        time.sleep(0.12)  # Respect EDGAR rate limit

    if not results:
        return pd.DataFrame()

    df = pd.DataFrame(results)
    df = df.dropna(subset=["value"])
    df = df[df["value"].between(-100, 100)]  # Remove outliers
    return df.reset_index(drop=True)
