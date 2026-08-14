import pandas as pd
import streamlit as st
from typing import Optional, List
from data.edgar_fetcher import fetch_comparables_edgar, SIC_MAP
from data.cvm_fetcher import fetch_comparables_cvm, CNAE_MAP
from data.fiscal_calendar import latest_available_fiscal_year

# Unified industry list (all sectors from both sources)
ALL_INDUSTRIES = sorted(set(list(SIC_MAP.keys()) + list(CNAE_MAP.keys())))


def find_comparables(
    industry: Optional[str] = None,
    sic_codes: Optional[List[str]] = None,
    company_name_edgar: Optional[str] = None,
    company_name_cvm: Optional[str] = None,
    sources: List[str] = ("SEC EDGAR", "CVM Brasil"),
    year: Optional[int] = None,
    limit: int = 15,
    pli: str = "operating_margin"
) -> pd.DataFrame:
    """
    Search both EDGAR and CVM for comparables and merge results.
    `year` is the fiscal year both sources must return (same-year comparability).
    """
    year = year or latest_available_fiscal_year()
    all_results = []

    if "SEC EDGAR" in sources:
        sic = SIC_MAP.get(industry) if industry else sic_codes
        edgar_df = fetch_comparables_edgar(
            industry=industry,
            sic_codes=sic,
            company_name=company_name_edgar,
            limit=limit,
            pli=pli,
            year=year
        )
        if not edgar_df.empty:
            all_results.append(edgar_df)

    if "CVM Brasil" in sources:
        cvm_df = fetch_comparables_cvm(
            industry=industry,
            company_name=company_name_cvm,
            year=year,
            limit=limit,
            pli=pli
        )
        if not cvm_df.empty:
            all_results.append(cvm_df)

    if not all_results:
        return pd.DataFrame()

    combined = pd.concat(all_results, ignore_index=True)
    combined = combined.drop_duplicates(subset=["name"])
    combined = combined.sort_values("value").reset_index(drop=True)
    return combined
