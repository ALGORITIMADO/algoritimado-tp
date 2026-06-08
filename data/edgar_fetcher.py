import requests
import pandas as pd
import streamlit as st
import time
from typing import Optional, List, Dict

HEADERS = {"User-Agent": "Algoritimado research@algoritimado.com"}
EDGAR_BASE = "https://data.sec.gov"

# SIC_MAP: industry → list of (CIK, company_name) seed companies
# Audited 2026-05-16 against SEC EDGAR company_tickers.json — all CIKs verified.
# Removed: Alexion (acquired by AstraZeneca 2021), Pioneer Natural Resources (acquired
# by ExxonMobil 2024), Kellogg (Kellanova acquired by Mars 2025).
SIC_MAP = {
    "Pharmaceutical / Farmacêutico": [
        (78003, "Pfizer Inc"), (310158, "Merck & Co Inc"), (200406, "Johnson & Johnson"),
        (1551152, "AbbVie Inc"), (14272, "Bristol Myers Squibb Co"),
        (59478, "Eli Lilly and Co"), (882095, "Gilead Sciences Inc"),
        (318154, "Amgen Inc"), (875045, "Biogen Inc"), (1682852, "Moderna Inc"),
        (1800, "Abbott Laboratories"), (10456, "Baxter International Inc"),
    ],
    "Biotech / Biotecnologia": [
        (318154, "Amgen Inc"), (882095, "Gilead Sciences Inc"), (875045, "Biogen Inc"),
        (1682852, "Moderna Inc"), (872589, "Regeneron Pharmaceuticals Inc"),
        (875320, "Vertex Pharmaceuticals Inc"),
        (1110803, "Illumina Inc"), (1048477, "BioMarin Pharmaceutical Inc"),
    ],
    "Cannabis / Cannabis Medicinal": [
        (1731348, "Tilray Brands Inc"), (1795139, "Green Thumb Industries Inc"),
        (1754195, "Trulieve Cannabis Corp"), (1848416, "Verano Holdings Corp"),
        (1584549, "Village Farms International Inc"),
        (1813452, "Planet 13 Holdings Inc"), (1522767, "MariMed Inc"),
        (1779474, "WM Technology Inc"), (1656472, "Cronos Group Inc"),
    ],
    "Agriculture / Agronegócio": [
        (7084, "Archer-Daniels-Midland Co"), (1996862, "Bunge Global SA"),
        (1755672, "Corteva Inc"), (100493, "Tyson Foods Inc"),
        (315189, "Deere & Co"), (1324404, "CF Industries Holdings Inc"),
        (37785, "FMC Corp"), (1285785, "Mosaic Co"),
    ],
    "AgTech / Tecnologia Agrícola": [
        (315189, "Deere & Co"), (37785, "FMC Corp"),
        (1755672, "Corteva Inc"), (1285785, "Mosaic Co"),
        (1324404, "CF Industries Holdings Inc"),
    ],
    "Food & Beverage / Alimentos": [
        (21344, "Coca-Cola Co"), (77476, "PepsiCo Inc"),
        (16732, "Campbell's Co"), (40704, "General Mills Inc"),
        (1996862, "Bunge Global SA"),
        (100493, "Tyson Foods Inc"), (1637459, "Kraft Heinz Co"),
    ],
    "Cosmetics / Cosméticos": [
        (1001250, "Estée Lauder Companies Inc"), (1024305, "Coty Inc"),
        (1403568, "Ulta Beauty Inc"), (822663, "Inter Parfums Inc"),
        (1021561, "Nu Skin Enterprises Inc"), (1096752, "Edgewell Personal Care Co"),
    ],
    "Chemicals / Química": [
        (1751788, "Dow Inc"), (1666700, "DuPont de Nemours Inc"),
        (37785, "FMC Corp"), (1285785, "Mosaic Co"),
        (1489393, "LyondellBasell Industries NV"), (1306830, "Celanese Corp"),
        (915389, "Eastman Chemical Co"),
    ],
    "Oil & Gas / Petróleo e Gás": [
        (34088, "Exxon Mobil Corp"), (93410, "Chevron Corp"),
        (1163165, "ConocoPhillips"), (1539838, "Diamondback Energy Inc"),
        (1534701, "Phillips 66"),
    ],
    "Software / Tecnologia": [
        (789019, "Microsoft Corp"), (1108524, "Salesforce Inc"),
        (1341439, "Oracle Corp"), (1373715, "ServiceNow Inc"),
        (1327811, "Workday Inc"), (1393052, "Veeva Systems Inc"),
        (1262039, "Fortinet Inc"),
    ],
    "Medical Devices / Dispositivos": [
        (1613103, "Medtronic plc"), (310764, "Stryker Corp"),
        (10795, "Becton Dickinson & Co"), (1136869, "Zimmer Biomet Holdings Inc"),
        (1035267, "Intuitive Surgical Inc"), (10456, "Baxter International Inc"),
        (313143, "Haemonetics Corp"),
    ],
    "Healthcare / Saúde": [
        (731766, "UnitedHealth Group Inc"), (1156039, "Elevance Health Inc"),
        (49071, "Humana Inc"), (1739940, "Cigna Group"),
        (1022079, "Quest Diagnostics Inc"), (920148, "Labcorp Holdings Inc"),
    ],
    "Education / Educação": [
        (1157408, "Stride Inc"), (1013934, "Strategic Education Inc"),
        (1434588, "Grand Canyon Education Inc"), (1046568, "Perdoceo Education Corp"),
        (1562088, "Duolingo Inc"), (912766, "Laureate Education Inc"),
        (104889, "Graham Holdings Co"),
    ],
    "Financial Services / Financeiro": [
        (19617, "JPMorgan Chase & Co"), (70858, "Bank of America Corp"),
        (886982, "Goldman Sachs Group Inc"), (895421, "Morgan Stanley"),
        (72971, "Wells Fargo & Co"), (831001, "Citigroup Inc"),
    ],
    "Manufacturing / Manufatura": [
        (32604, "Emerson Electric Co"), (773840, "Honeywell International Inc"),
        (40545, "General Electric Co"), (49826, "Illinois Tool Works Inc"),
        (76334, "Parker-Hannifin Corp"), (1024478, "Rockwell Automation Inc"),
    ],
    "Retail / Varejo": [
        (104169, "Walmart Inc"), (1018724, "Amazon.com Inc"),
        (29534, "Dollar General Corp"), (27419, "Target Corp"),
        (354950, "Home Depot Inc"), (935703, "Dollar Tree Inc"),
    ],
    "Real Estate / Imobiliário": [
        (1045609, "Prologis Inc"), (1101239, "Equinix Inc"),
        (1393311, "Public Storage"), (726728, "Realty Income Corp"),
        (1063761, "Simon Property Group Inc"), (766704, "Welltower Inc"),
        (1289490, "Extra Space Storage Inc"),
    ],
    "Sanitation / Saneamento": [
        (1410636, "American Water Works Co Inc"), (78128, "Essential Utilities Inc"),
        (1035201, "California Water Service Group"), (108985, "York Water Co"),
        (928340, "Consolidated Water Co Ltd"), (66004, "Middlesex Water Co"),
    ],
    "Energy / Energia": [
        (753308, "NextEra Energy Inc"), (1326160, "Duke Energy Corp"),
        (715957, "Dominion Energy Inc"), (92122, "Southern Co"),
        (1109357, "Exelon Corp"), (4904, "American Electric Power Co Inc"),
    ],
    "Mining / Mineração": [
        (831259, "Freeport-McMoRan Inc"), (1164727, "Newmont Corp"),
        (73309, "Nucor Corp"), (756894, "Barrick Mining Corp"),
        (1675149, "Alcoa Corp"),
    ],
    "Logistics / Logística": [
        (1048911, "FedEx Corp"), (1090727, "United Parcel Service Inc"),
        (1166003, "XPO Inc"), (793074, "Werner Enterprises Inc"),
        (1043277, "C.H. Robinson Worldwide Inc"),
    ],
    "Telecom / Telecomunicações": [
        (732717, "AT&T Inc"), (732712, "Verizon Communications Inc"),
        (1283699, "T-Mobile US Inc"), (1051470, "Crown Castle Inc"),
        (1053507, "American Tower Corp"),
    ],
}


@st.cache_data(ttl=7200, show_spinner=False)
def get_company_facts_v2(cik: int) -> Optional[Dict]:
    """Fetch XBRL company facts from EDGAR. Cached 2h."""
    cik_str = str(cik).zfill(10)
    url = f"{EDGAR_BASE}/api/xbrl/companyfacts/CIK{cik_str}.json"
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        return r.json() if r.status_code == 200 else None
    except Exception:
        return None


def _latest_annual_record(gaap: Dict, fields: List[str], target_year: Optional[int] = None):
    """Annual 10-K/20-F datapoint across ALL listed fields.

    Returns (value, accn, end) or None. `accn` is the SEC accession number of
    the filing the value came from — used to build a direct link to the exact
    source document (audit trail). `end` is the fiscal-period end date.

    When `target_year` is given, only datapoints whose fiscal-period END falls in
    that year are considered — so a 2024 analysis pulls 2024 financials, not the
    latest. Comparability requires same-year data; if a company has no datapoint
    for that year, this returns None and the caller excludes it (never mixes years).

    When `target_year` is None, returns the value with the latest end_date —
    companies that migrated to ASC 606 fields often leave legacy fields frozen at
    2020 data, so iterating field-by-field would return stale values.
    """
    best = None  # (end, value, accn)
    for field in fields:
        if field not in gaap:
            continue
        usd_vals = gaap[field].get("units", {}).get("USD", [])
        annual = [u for u in usd_vals
                  if u.get("form") in ("10-K", "20-F") and u.get("fp") == "FY"]
        if not annual:
            annual = [u for u in usd_vals if u.get("form") in ("10-K", "20-F")]
        if not annual:
            continue
        annual.sort(key=lambda x: x.get("end", ""), reverse=True)
        for u in annual:
            val = u.get("val")
            end = u.get("end", "")
            if val is None or val == 0:
                continue
            # Honor the requested fiscal year: skip non-matching years and keep
            # scanning older datapoints until the right year is found.
            if target_year is not None and not str(end).startswith(str(target_year)):
                continue
            if best is None or end > best[0]:
                best = (end, float(val), u.get("accn", ""))
            break
    return (best[1], best[2], best[0]) if best else None


def _latest_annual(gaap: Dict, fields: List[str], target_year: Optional[int] = None) -> Optional[float]:
    """Annual value (float) across ALL listed fields, or None. Honors target_year."""
    rec = _latest_annual_record(gaap, fields, target_year=target_year)
    return rec[0] if rec else None


def extract_financials(facts: Dict, target_year: Optional[int] = None) -> Optional[Dict]:
    """Extract margins from XBRL company facts.

    When `target_year` is given, ALL line items (revenue, operating income, net
    income, COGS, D&A) are taken from that fiscal year so the margins are internally
    consistent and match the analysis year. A company missing that year is dropped.
    """
    if not facts:
        return None
    gaap = facts.get("facts", {}).get("us-gaap", {})
    if not gaap:
        return None

    rev_rec = _latest_annual_record(gaap, [
        "Revenues",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "SalesRevenueNet",
        "SalesRevenueGoodsNet",
    ], target_year=target_year)
    revenue = rev_rec[0] if rev_rec else None
    if not revenue or revenue <= 0:
        return None

    op_income   = _latest_annual(gaap, ["OperatingIncomeLoss"], target_year=target_year)
    net_income  = _latest_annual(gaap, ["NetIncomeLoss", "ProfitLoss"], target_year=target_year)
    cogs        = _latest_annual(gaap, [
        "CostOfGoodsAndServicesSold",
        "CostOfRevenue",
        "CostOfGoodsSold",
    ], target_year=target_year)
    da          = _latest_annual(gaap, [
        "DepreciationDepletionAndAmortization",
        "DepreciationAndAmortization",
    ], target_year=target_year)

    # Keep the raw line items (not just the margins) so the report can "show the
    # math" — numerator and denominator traceable to the same filing.
    result = {"revenue_usd": revenue}
    if rev_rec and rev_rec[1]:
        # Accession number + fiscal-year end of the filing the financials came
        # from → lets the caller link to the exact source 10-K/20-F document.
        result["_accn"] = rev_rec[1]
        result["_fy_end"] = rev_rec[2]
    if op_income is not None:
        result["operating_income_usd"] = op_income
        result["operating_margin"] = round(op_income / revenue * 100, 4)
    if net_income is not None:
        result["net_income_usd"] = net_income
        result["net_margin"] = round(net_income / revenue * 100, 4)
    # Gross margin computed as (Revenue - COGS) / Revenue. The XBRL GrossProfit
    # field is unreliable: companies that adopted ASC 606 left it frozen at 2020,
    # and others tag non-standard values (e.g. AbbVie reports GP=$12B when
    # Revenue-COGS yields $43B).
    if cogs is not None and 0 < cogs < revenue:
        result["cogs_usd"] = cogs
        result["gross_margin"] = round((revenue - cogs) / revenue * 100, 4)
    if op_income is not None and da is not None:
        result["da_usd"] = da
        result["ebitda_margin"] = round((op_income + da) / revenue * 100, 4)
    return result if len(result) > 1 else None


def _pli_breakdown(fin: Dict, pli: str) -> Optional[Dict]:
    """Build a 'show the math' breakdown for the chosen PLI: numerator,
    denominator (revenue) and resulting margin — all from the same filing.
    Returns None when the PLI's components aren't available (graceful)."""
    rev = fin.get("revenue_usd")
    if not rev:
        return None
    if pli == "operating_margin" and fin.get("operating_income_usd") is not None:
        return {"kind": "operating", "num": fin["operating_income_usd"],
                "den": rev, "margin": fin["operating_margin"], "currency": "USD"}
    if pli == "net_margin" and fin.get("net_income_usd") is not None:
        return {"kind": "net", "num": fin["net_income_usd"],
                "den": rev, "margin": fin["net_margin"], "currency": "USD"}
    if pli == "gross_margin" and fin.get("cogs_usd") is not None:
        return {"kind": "gross", "num": rev - fin["cogs_usd"],
                "den": rev, "margin": fin["gross_margin"], "currency": "USD"}
    if pli == "ebitda_margin" and fin.get("operating_income_usd") is not None \
            and fin.get("da_usd") is not None:
        return {"kind": "ebitda", "num": fin["operating_income_usd"] + fin["da_usd"],
                "den": rev, "margin": fin["ebitda_margin"], "currency": "USD"}
    return None


def fetch_comparables_edgar(
    industry: Optional[str] = None,
    sic_codes: Optional[List[str]] = None,
    company_name: Optional[str] = None,
    limit: int = 15,
    pli: str = "operating_margin",
    year: Optional[int] = None,
) -> pd.DataFrame:
    """
    Fetch comparable companies from EDGAR XBRL.
    Uses sector seed list → live XBRL financial data.
    When `year` is given, financials are pulled from that fiscal year (same-year
    comparability); companies without data for that year are excluded.
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
        facts = get_company_facts_v2(cik)
        if facts:
            fin = extract_financials(facts, target_year=year)
            if fin and pli in fin:
                name = facts.get("entityName", default_name) or default_name
                # Audit trail: link straight to the exact filing the financials
                # were extracted from, using its accession number. Falls back to
                # the company's filing list if the accession number is missing.
                accn = fin.get("_accn")
                if accn:
                    src_url = (
                        "https://www.sec.gov/Archives/edgar/data/"
                        f"{int(cik)}/{accn.replace('-', '')}/{accn}-index.htm"
                    )
                else:
                    src_url = (
                        "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany"
                        f"&CIK={str(cik).zfill(10)}&type=&dateb=&owner=include&count=40"
                    )
                results.append({
                    "name": name,
                    "value": fin[pli],
                    "operating_margin": fin.get("operating_margin"),
                    "net_margin": fin.get("net_margin"),
                    "gross_margin": fin.get("gross_margin"),
                    "ebitda_margin": fin.get("ebitda_margin"),
                    "source": "SEC EDGAR",
                    "source_url": src_url,
                    "breakdown": _pli_breakdown(fin, pli),
                })
        time.sleep(0.1)

    if not results:
        return pd.DataFrame()

    df = pd.DataFrame(results).drop_duplicates("name")
    df = df[df["value"].between(-200, 200)]
    return df.reset_index(drop=True)
