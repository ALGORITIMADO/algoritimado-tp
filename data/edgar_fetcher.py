import requests
import pandas as pd
import streamlit as st
import time
from typing import Optional, List, Dict

HEADERS = {"User-Agent": "Algoritimado research@algoritimado.com"}
EDGAR_BASE = "https://data.sec.gov"
EDGAR_SEARCH = "https://efts.sec.gov/EDGAR/search-index"

SIC_MAP = {
    "Pharmaceutical / Farmacêutico":     ["pharmaceutical", "pharma drug"],
    "Biotech / Biotecnologia":           ["biotechnology", "biopharmaceutical"],
    "Agriculture / Agronegócio":         ["agricultural products", "crop production"],
    "AgTech / Tecnologia Agrícola":      ["agricultural technology", "precision agriculture"],
    "Food & Beverage / Alimentos":       ["food processing", "packaged foods"],
    "Chemicals / Química":               ["specialty chemicals", "chemical manufacturing"],
    "Oil & Gas / Petróleo e Gás":        ["oil and gas", "petroleum upstream"],
    "Software / Tecnologia":             ["software", "cloud computing SaaS"],
    "Medical Devices / Dispositivos":    ["medical devices", "medical equipment"],
    "Healthcare / Saúde":                ["healthcare services", "hospital systems"],
    "Financial Services / Financeiro":   ["financial services", "asset management"],
    "Manufacturing / Manufatura":        ["industrial manufacturing", "machinery equipment"],
    "Retail / Varejo":                   ["retail stores", "consumer goods retail"],
    "Energy / Energia":                  ["electric utility", "renewable energy"],
    "Mining / Mineração":                ["mining operations", "mineral extraction"],
    "Logistics / Logística":             ["logistics services", "freight transportation"],
    "Telecom / Telecomunicações":        ["telecommunications", "wireless broadband"],
}


@st.cache_data(ttl=3600, show_spinner=False)
def search_edgar_filings(keyword: str, limit: int = 20) -> List[Dict]:
    try:
        encoded = keyword.replace(" ", "+")
        url = (f"{EDGAR_SEARCH}?q=%22{encoded}%22&forms=10-K"
               f"&dateRange=custom&startdt=2021-01-01&enddt=2024-12-31")
        r = requests.get(url, headers=HEADERS, timeout=20)
        if r.status_code != 200:
            return []
        data = r.json()
        hits = data.get("hits", {}).get("hits", [])
        results = []
        seen_ciks = set()
        for hit in hits:
            src = hit.get("_source", {})
            entity = src.get("entity_name", "")
            entity_id = hit.get("_id", "")
            if entity_id and "-" in entity_id:
                cik_raw = entity_id.split("-")[0].lstrip("0")
                if cik_raw and cik_raw.isdigit() and cik_raw not in seen_ciks:
                    seen_ciks.add(cik_raw)
                    results.append({
                        "name": entity,
                        "cik": int(cik_raw),
                        "period": src.get("period_of_report", "2023")
                    })
            if len(results) >= limit:
                break
        return results
    except Exception:
        return []


@st.cache_data(ttl=7200, show_spinner=False)
def get_company_facts(cik: int) -> Optional[Dict]:
    if cik <= 0:
        return None
    cik_str = str(cik).zfill(10)
    url = f"{EDGAR_BASE}/api/xbrl/companyfacts/CIK{cik_str}.json"
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        return r.json() if r.status_code == 200 else None
    except Exception:
        return None


def _latest_annual(gaap: Dict, fields: List[str]) -> Optional[float]:
    for field in fields:
        if field not in gaap:
            continue
        usd_vals = gaap[field].get("units", {}).get("USD", [])
        annual = [u for u in usd_vals if u.get("form") in ("10-K", "20-F") and u.get("fp") == "FY"]
        if not annual:
            annual = [u for u in usd_vals if u.get("form") in ("10-K", "20-F")]
        if annual:
            annual.sort(key=lambda x: x.get("end", ""), reverse=True)
            val = annual[0].get("val")
            if val is not None and val != 0:
                return float(val)
    return None


def extract_financials(facts: Dict) -> Optional[Dict]:
    if not facts:
        return None
    gaap = facts.get("facts", {}).get("us-gaap", {})
    if not gaap:
        return None
    revenue = _latest_annual(gaap, [
        "Revenues",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "SalesRevenueNet",
    ])
    if not revenue or revenue <= 0:
        return None
    op_income  = _latest_annual(gaap, ["OperatingIncomeLoss"])
    net_income = _latest_annual(gaap, ["NetIncomeLoss", "ProfitLoss"])
    gross_profit = _latest_annual(gaap, ["GrossProfit"])
    da = _latest_annual(gaap, ["DepreciationDepletionAndAmortization", "DepreciationAndAmortization"])
    result = {"revenue_usd": revenue}
    if op_income is not None:
        result["operating_margin"] = round(op_income / revenue * 100, 4)
    if net_income is not None:
        result["net_margin"] = round(net_income / revenue * 100, 4)
    if gross_profit is not None:
        result["gross_margin"] = round(gross_profit / revenue * 100, 4)
    if op_income is not None and da is not None:
        result["ebitda_margin"] = round((op_income + da) / revenue * 100, 4)
    return result if len(result) > 1 else None


def fetch_comparables_edgar(
    industry: Optional[str] = None,
    sic_codes: Optional[List[str]] = None,
    company_name: Optional[str] = None,
    limit: int = 15,
    pli: str = "operating_margin"
) -> pd.DataFrame:
    keywords = []
    if industry and industry in SIC_MAP:
        keywords = SIC_MAP[industry][:2]
    elif company_name:
        keywords = [company_name]
    else:
        return pd.DataFrame()

    all_companies = []
    for kw in keywords:
        companies = search_edgar_filings(kw, limit=limit * 2)
        all_companies.extend(companies)
        time.sleep(0.2)

    seen = set()
    unique = []
    for c in all_companies:
        if c["cik"] not in seen and c["cik"] > 0:
            seen.add(c["cik"])
            unique.append(c)

    if not unique:
        return pd.DataFrame()

    results = []
    for company in unique[:limit * 2]:
        if len(results) >= limit:
            break
        facts = get_company_facts(company["cik"])
        if facts:
            fin = extract_financials(facts)
            if fin and pli in fin:
                name = facts.get("entityName", company["name"]) or company["name"]
                results.append({
                    "name": name,
                    "value": fin[pli],
                    "operating_margin": fin.get("operating_margin"),
                    "net_margin": fin.get("net_margin"),
                    "gross_margin": fin.get("gross_margin"),
                    "ebitda_margin": fin.get("ebitda_margin"),
                    "source": "SEC EDGAR",
                })
        time.sleep(0.15)

    if not results:
        return pd.DataFrame()

    df = pd.DataFrame(results).drop_duplicates("name")
    df = df[df["value"].between(-100, 100)]
    return df.reset_index(drop=True)
