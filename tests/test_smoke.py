"""Offline smoke tests — no network. Guard the riskiest logic before deploy:
IQR math, year-aligned extraction, breakdown, CVM scale, and PDF generation.

Run locally: scripts/preflight.sh  (or: pytest -q)
Runs automatically in CI on every push/PR (.github/workflows/ci.yml).
"""
import pandas as pd

from calculations.base import calculate_iqr
from data.edgar_fetcher import extract_financials, _pli_breakdown
from data.cvm_fetcher import calculate_margins_cvm, _pli_breakdown_cvm
from reports.pdf_generator import generate_report, _breakdown_text


# ── helpers ──────────────────────────────────────────────────────────────────
def _dp(end, val, accn):
    return {"form": "10-K", "fp": "FY", "end": end, "val": val, "accn": accn}


def _facts():
    """Minimal SEC companyfacts with two fiscal years."""
    return {"facts": {"us-gaap": {
        "Revenues": {"units": {"USD": [
            _dp("2023-12-31", 900, "acc-2023"), _dp("2024-12-31", 1000, "acc-2024")]}},
        "OperatingIncomeLoss": {"units": {"USD": [
            _dp("2023-12-31", 90, "acc-2023"), _dp("2024-12-31", 200, "acc-2024")]}},
        "NetIncomeLoss": {"units": {"USD": [_dp("2024-12-31", 100, "acc-2024")]}},
    }}}


# ── IQR ──────────────────────────────────────────────────────────────────────
def test_iqr_basic():
    r = calculate_iqr([10, 20, 30, 40, 50], tested_party_value=25)
    assert r.median == 30
    assert r.is_arms_length is True


def test_iqr_outside_range():
    r = calculate_iqr([10, 20, 30, 40, 50], tested_party_value=99)
    assert r.is_arms_length is False


# ── Year alignment (the bug Gabriela caught) ─────────────────────────────────
def test_year_alignment_picks_requested_year():
    fin24 = extract_financials(_facts(), target_year=2024)
    assert fin24["operating_margin"] == 20.0      # 200 / 1000
    assert fin24["_accn"] == "acc-2024"

    fin23 = extract_financials(_facts(), target_year=2023)
    assert fin23["operating_margin"] == 10.0      # 90 / 900  (not mixed)
    assert fin23["_accn"] == "acc-2023"


def test_missing_year_excluded():
    assert extract_financials(_facts(), target_year=1999) is None


# ── Breakdown (show the math) ────────────────────────────────────────────────
def test_breakdown_operating():
    bd = _pli_breakdown(extract_financials(_facts(), target_year=2024), "operating_margin")
    assert bd["kind"] == "operating" and bd["num"] == 200 and bd["den"] == 1000


def test_breakdown_text_markup_and_brl():
    t = _breakdown_text({"kind": "markup", "num": 45e9, "den": 18e9,
                         "margin": 250.0, "currency": "USD"}, "pt")
    assert "Lucro bruto" in t and "CMV" in t and "US$" in t
    t2 = _breakdown_text({"kind": "operating", "num": 2e9, "den": 8e9,
                          "margin": 25.0, "currency": "BRL"}, "pt")
    assert "R$" in t2 and "Receita" in t2


# ── CVM scale (ESCALA_MOEDA = MIL → thousands) ───────────────────────────────
def test_cvm_scale_mil():
    df = pd.DataFrame({
        "CD_CVM": ["1", "1", "1"],
        "DT_FIM_EXERC": ["2024-12-31"] * 3,
        "ESCALA_MOEDA": ["MIL"] * 3,
        "CD_CONTA": ["3.01", "3.07", "3.11"],
        "VL_CONTA": [1000, 200, 100],
    })
    m = calculate_margins_cvm(df, "1", "CD_CVM")
    assert m["operating_margin"] == 20.0          # ratio: scale cancels
    assert m["revenue_brl"] == 1_000_000          # 1000 * 1000 (MIL)
    assert m["ebit_brl"] == 200_000
    bd = _pli_breakdown_cvm(m, "operating_margin")
    assert bd["currency"] == "BRL" and bd["num"] == 200_000


def test_cvm_picks_current_exercise_not_comparative():
    # A year's DFP file carries the current exercise (ÚLTIMO) AND the prior-year
    # comparative (PENÚLTIMO), both with the same DT_REFER. Must return the
    # current year — the bug Gabriela caught: Cosan 2025 returned 2024 revenue.
    df = pd.DataFrame({
        "CD_CVM": ["1"] * 4,
        "DT_REFER": ["2025-12-31"] * 4,
        "DT_FIM_EXERC": ["2024-12-31", "2024-12-31", "2025-12-31", "2025-12-31"],
        "ORDEM_EXERC": ["PENÚLTIMO", "PENÚLTIMO", "ÚLTIMO", "ÚLTIMO"],
        "ESCALA_MOEDA": ["MIL"] * 4,
        "CD_CONTA": ["3.01", "3.07", "3.01", "3.07"],
        "VL_CONTA": [44000, 9000, 40000, 8000],  # prior comes first in the file
    })
    m = calculate_margins_cvm(df, "1", "CD_CVM")
    assert m["revenue_brl"] == 40000 * 1000      # current (ÚLTIMO), not 44000
    assert m["ebit_brl"] == 8000 * 1000


# ── PDF generation (mixed sources, link + breakdown, manual row) ─────────────
def test_pdf_generates_bytes():
    comps = [
        {"name": "SEC Co", "value": 20.0, "source": "SEC EDGAR",
         "source_url": "https://www.sec.gov/x?a=1&b=2",
         "breakdown": {"kind": "operating", "num": 200e6, "den": 1000e6,
                       "margin": 20.0, "currency": "USD"}},
        {"name": "BR Co", "value": 15.0, "source": "CVM Brasil 2024",
         "source_url": "https://www.rad.cvm.gov.br/x?codigoCVM=1",
         "breakdown": {"kind": "operating", "num": 1.5e9, "den": 1.0e10,
                       "margin": 15.0, "currency": "BRL"}},
        {"name": "Manual & Co", "value": 10.0, "source": "Annual Report"},
    ]
    iqr = calculate_iqr([20.0, 15.0, 10.0], tested_party_value=15.0)
    pdf = generate_report({
        "language": "pt", "company_name": "Teste", "tested_party_name": "Teste",
        "method": "MLT", "pli": "Margem Operacional", "fiscal_year": "2024",
        "iqr_result": iqr, "comparables": comps,
    })
    assert pdf[:4] == b"%PDF" and len(pdf) > 2000


# ── FAR section (Tijolo 2 parte 1) ───────────────────────────────────────────
def test_pdf_far_section():
    iqr = calculate_iqr([20.0, 15.0, 10.0], tested_party_value=15.0)
    base = {
        "language": "pt", "company_name": "Teste", "tested_party_name": "Teste",
        "method": "MLT", "pli": "Margem Operacional", "fiscal_year": "2024",
        "iqr_result": iqr,
        "comparables": [{"name": "A", "value": 20.0, "source": "Annual Report"}],
    }
    plain = generate_report(base)
    # XML chars and newlines in user text must not break ReportLab markup
    with_far = generate_report({**base,
        "far_functions": "Distribuição & revenda <local> de produtos",
        "far_assets": "Centro de distribuição próprio",
        "far_risks": "Risco cambial\nRisco de estoque"})
    assert with_far[:4] == b"%PDF" and len(with_far) > len(plain)
    # Whitespace-only fields are treated as empty (section omitted, no crash)
    blank_far = generate_report({**base, "far_functions": "   ", "far_risks": "\n"})
    assert blank_far[:4] == b"%PDF"


# ── Foreign-comparables note (interim, until Anexo II adjustment exists) ─────
def test_pdf_foreign_comparables_note():
    iqr = calculate_iqr([20.0, 15.0, 10.0], tested_party_value=15.0)
    base = {
        "language": "pt", "company_name": "Teste", "tested_party_name": "Teste",
        "method": "MLT", "pli": "Margem Operacional", "fiscal_year": "2024",
        "iqr_result": iqr,
    }
    domestic_only = generate_report({**base, "comparables": [
        {"name": "BR Co", "value": 20.0, "source": "CVM Brasil 2024 (DFP)"}]})
    with_foreign = generate_report({**base, "comparables": [
        {"name": "US Co", "value": 20.0, "source": "SEC EDGAR 2024 (10-K)"}]})
    assert domestic_only[:4] == b"%PDF" and with_foreign[:4] == b"%PDF"
    # The note adds a paragraph, so the foreign variant must be heavier than
    # the domestic one beyond the small source-label difference.
    assert len(with_foreign) > len(domestic_only) + 200
