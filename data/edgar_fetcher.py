import requests
import pandas as pd
import streamlit as st
import time
from typing import Optional, List, Dict

HEADERS = {"User-Agent": "Algoritimado research@algoritimado.com"}
EDGAR_BASE = "https://data.sec.gov"

# SIC_MAP: industry → list of (CIK, company_name) seed companies
SIC_MAP = {
    "Pharmaceutical / Farmacêutico": [
        (78003, "Pfizer Inc"), (310158, "Merck & Co"), (200406, "Johnson & Johnson"),
        (1551152, "AbbVie Inc"), (14272, "Bristol-Myers Squibb"),
        (59478, "Eli Lilly and Co"), (882095, "Gilead Sciences"),
        (318154, "Amgen Inc"), (875320, "Biogen Inc"), (1682852, "Moderna Inc"),
        (315966, "Abbott Laboratories"), (216346, "Baxter International"),
    ],
    "Biotech / Biotecnologia": [
        (318154, "Amgen Inc"), (882095, "Gilead Sciences"), (875320, "Biogen Inc"),
        (1682852, "Moderna Inc"), (1124140, "Regeneron Pharmaceuticals"),
        (1403708, "Alexion Pharmaceuticals"), (1326428, "Vertex Pharmaceuticals"),
        (1038357, "Illumina Inc"), (1117304, "BioMarin Pharmaceutical"),
    ],
    "Agriculture / Agronegócio": [
        (7084, "Archer-Daniels-Midland Co"), (1144519, "Bunge Ltd"),
        (1751788, "Corteva Inc"), (100493, "Tyson Foods"),
        (49519, "Deere & Company"), (315189, "CF Industries"),
        (764180, "FMC Corp"), (813672, "Mosaic Co"),
    ],
    "AgTech / Tecnologia Agrícola": [
        (49519, "Deere & Company"), (764180, "FMC Corp"),
        (1751788, "Corteva Inc"), (813672, "Mosaic Co"),
        (315189, "CF Industries Holdings"),
    ],
    "Food & Beverage / Alimentos": [
        (21344, "Coca-Cola Co"), (77476, "PepsiCo Inc"),
        (16160, "Campbell Soup Co"), (23666, "General Mills"),
        (40987, "Kellogg Co"), (1144519, "Bunge Ltd"),
        (100493, "Tyson Foods Inc"), (1637459, "Kraft Heinz Co"),
    ],
    "Chemicals / Química": [
        (30554, "Dow Inc"), (23632, "DuPont de Nemours"),
        (764180, "FMC Corp"), (813672, "Mosaic Co"),
        (1324789, "LyondellBasell Industries"), (1306965, "Celanese Corp"),
        (28823, "Eastman Chemical"),
    ],
    "Oil & Gas / Petróleo e Gás": [
        (101778, "Exxon Mobil Corp"), (93410, "Chevron Corp"),
        (858470, "ConocoPhillips"), (1656081, "Diamondback Energy"),
        (77159, "Phillips 66"), (1108827, "Pioneer Natural Resources"),
    ],
    "Software / Tecnologia": [
        (789019, "Microsoft Corp"), (1108524, "Salesforce Inc"),
        (1341439, "Oracle Corp"), (1108827, "ServiceNow Inc"),
        (1467858, "Workday Inc"), (1085869, "Veeva Systems"),
        (1393612, "Fortinet Inc"),
    ],
    "Medical Devices / Dispositivos": [
        (310764, "Medtronic plc"), (319201, "Stryker Corp"),
        (202058, "Becton Dickinson"), (1120670, "Zimmer Biomet"),
        (1393898, "Intuitive Surgical"), (216346, "Baxter International"),
        (1374690, "Haemonetics Corp"),
    ],
    "Healthcare / Saúde": [
        (72971, "UnitedHealth Group"), (1156039, "Anthem Inc"),
        (784977, "Humana Inc"), (1071739, "Cigna Corp"),
        (800166, "Quest Diagnostics"), (920371, "Laboratory Corp"),
    ],
    "Financial Services / Financeiro": [
        (70858, "JPMorgan Chase"), (60667, "Bank of America"),
        (831001, "Goldman Sachs"), (895421, "Morgan Stanley"),
        (92122, "Wells Fargo"), (19617, "Citigroup"),
    ],
    "Manufacturing / Manufatura": [
        (40987, "Emerson Electric"), (66740, "Honeywell International"),
        (40533, "General Electric"), (49196, "Illinois Tool Works"),
        (723254, "Parker Hannifin"), (97476, "Rockwell Automation"),
    ],
    "Retail / Varejo": [
        (104169, "Walmart Inc"), (1018724, "Amazon.com Inc"),
        (1373715, "Dollar General"), (34408, "Target Corp"),
        (86312, "Home Depot"), (1564708, "Dollar Tree"),
    ],
    "Energy / Energia": [
        (1012100, "NextEra Energy"), (1013871, "Duke Energy"),
        (1042482, "Dominion Energy"), (1043604, "Southern Co"),
        (1004440, "Exelon Corp"), (1126234, "American Electric Power"),
    ],
    "Mining / Mineração": [
        (1532187, "Freeport-McMoRan"), (1045810, "Newmont Corp"),
        (719413, "Nucor Corp"), (101929, "Barrick Gold"),
        (277135, "Alcoa Corp"),
    ],
    "Logistics / Logística": [
        (78814, "FedEx Corp"), (100030, "United Parcel Service"),
        (1043279, "XPO Inc"), (1308179, "Werner Enterprises"),
        (65011, "CH Robinson Worldwide"),
    ],
    "Telecom / Telecomunicações": [
        (732717, "AT&T Inc"), (101830, "Verizon Communications"),
        (1051512, "T-Mobile US"), (1418135, "Crown Castle"),
        (1053507, "American Tower Corp"),
    ],
}


@st.cache_data(ttl=7200, show_spinner=False)
def get_company_facts(cik: int) -> Optional[Dict]:
    """Fetch XBRL company facts from EDGAR. Cached 2h."""
    cik_str = str(cik).zfill(10)
    url = f"{EDGAR_BASE}/api/xbrl/companyfacts/CIK{cik_str}.json"
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        return r.json() if r.status_code == 200 else None
    except Exception:
        return None


def _latest_annual(gaap: Dict, fields: List[str]) -> Optional[float]:
    """Get most recent annual 10-K/20-F value."""
    for field in fields:
        if field not in gaap:
            continue
        usd_vals = gaap[field].get("units", {}).get("USD", [])
        annual = [u for u in usd_vals
                  if u.get("form") in ("10-K", "20-F") and u.get("fp") == "FY"]
        if not annual:
            annual = [u for u in usd_vals if u.get("form") in ("10-K", "20-F")]
        if annual:
            annual.sort(key=lambda x: x.get("end", ""), reverse=True)
            val = annual[0].get("val")
            if val is not None and val != 0:
                return float(val)
    return None


def extract_financials(facts: Dict) -> Optional[Dict]:
    """Extract margins from XBRL company facts."""
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
        "SalesRevenueGoodsNet",
    ])
    if not revenue or revenue <= 0:
        return None

    op_income   = _latest_annual(gaap, ["OperatingIncomeLoss"])
    net_income  = _latest_annual(gaap, ["NetIncomeLoss", "ProfitLoss"])
    gross_profit= _latest_annual(gaap, ["GrossProfit"])
    da          = _latest_annual(gaap, [
        "DepreciationDepletionAndAmortization",
        "DepreciationAndAmortization",
    ])

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
    """
    Fetch comparable companies from EDGAR XBRL.
    Uses sector seed list → live XBRL financial data.
    """
    # Get seed companies for the industry
    seed_companies = []
    if industry and industry in SIC_MAP:
        seed_companies = SIC_MAP[industry]
    elif company_name:
        # Search all sectors for matching name
        name_upper = company_name.upper()
        for sector_companies in SIC_MAP.values():
            for cik, name in sector_companies:
                if name_upper in name.upper():
                    seed_companies.append((cik, name))

    if not seed_companies:
        return pd.DataFrame()

    results = []
    for cik, default_name in seed_companies[:limit * 2]:
        if len(results) >= limit:
            break
        facts = get_company_facts(cik)
        if facts:
            fin = extract_financials(facts)
            if fin and pli in fin:
                name = facts.get("entityName", default_name) or default_name
                results.append({
                    "name": name,
                    "value": fin[pli],
                    "operating_margin": fin.get("operating_margin"),
                    "net_margin": fin.get("net_margin"),
                    "gross_margin": fin.get("gross_margin"),
                    "ebitda_margin": fin.get("ebitda_margin"),
                    "source": "SEC EDGAR",
                })
        time.sleep(0.1)

    if not results:
        return pd.DataFrame()

    df = pd.DataFrame(results).drop_duplicates("name")
    df = df[df["value"].between(-200, 200)]
    return df.reset_index(drop=True)
