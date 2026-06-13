"""Offline smoke tests — no network. Guard the riskiest logic before deploy:
IQR math, year-aligned extraction, breakdown, CVM scale, and PDF generation.

Run locally: scripts/preflight.sh  (or: pytest -q)
Runs automatically in CI on every push/PR (.github/workflows/ci.yml).
"""
import pandas as pd

from calculations.base import calculate_iqr
from calculations.country_risk import adjust_comparable_margin
from data.edgar_fetcher import extract_financials, _pli_breakdown
from data.cvm_fetcher import calculate_margins_cvm, _pli_breakdown_cvm
from reports.pdf_generator import generate_report, _breakdown_text, _cr_adjustment_text


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


# ── Country-risk adjustment — Anexo II IN 2.161/2023 ─────────────────────────
def test_anexo_ii_official_example():
    """The Receita's own worked example (Anexo II, IN 2.161/2023) as fixture:
    differential 3.73% (5.19 − 1.46) applied to 7 comparables. Official table
    rounds half-up to 2 decimals; we compare with ±0.0051 tolerance."""
    rows = {  # name: (revenue, op_income, capital_employed, official_adj_oi, official_adj_ros)
        "A": (1000.00, 30.00, 100, 33.73, 3.37),
        "B": (1500.00, 50.00, 120, 54.48, 3.63),
        "C": (2300.00, 80.00, 150, 85.60, 3.72),
        "D": (1050.00, 40.00, 130, 44.85, 4.27),
        "E": (4000.00, 200.00, 200, 207.46, 5.19),
        "F": (2000.00, 110.00, 300, 121.19, 6.06),
        "G": (3000.00, 200.00, 150, 205.60, 6.85),
    }
    for name, (rev, oi, ce, adj_oi_official, adj_ros_official) in rows.items():
        r = adjust_comparable_margin(oi, rev, ce, 5.19, 1.46)
        assert abs(r["differential_pct"] - 3.73) < 1e-9, name
        assert abs(r["adjusted_operating_income"] - adj_oi_official) <= 0.0051, name
        assert abs(r["adjusted_margin"] - adj_ros_official) <= 0.0051, name


def test_anexo_ii_sign_preserved():
    # Comparable in a riskier country than the tested party → negative adjustment.
    r = adjust_comparable_margin(30.0, 1000.0, 100, 1.46, 5.19)
    assert r["adjustment"] < 0
    assert r["adjusted_margin"] < r["margin_before"]


def test_capital_employed_extracted_same_year():
    facts = _facts()
    facts["facts"]["us-gaap"].update({
        "PropertyPlantAndEquipmentNet": {"units": {"USD": [
            _dp("2023-12-31", 350, "acc-2023"), _dp("2024-12-31", 400, "acc-2024")]}},
        "AssetsCurrent": {"units": {"USD": [
            _dp("2023-12-31", 280, "acc-2023"), _dp("2024-12-31", 300, "acc-2024")]}},
        "LiabilitiesCurrent": {"units": {"USD": [
            _dp("2023-12-31", 190, "acc-2023"), _dp("2024-12-31", 180, "acc-2024")]}},
    })
    fin = extract_financials(facts, target_year=2024)
    assert fin["capital_employed_usd"] == 400 + (300 - 180)   # year-aligned, not mixed
    fin23 = extract_financials(facts, target_year=2023)
    assert fin23["capital_employed_usd"] == 350 + (280 - 190)


def test_pdf_with_country_risk_adjustment():
    iqr = calculate_iqr([24.0, 20.0, 16.0], tested_party_value=20.0)
    cr = adjust_comparable_margin(200e6, 1000e6, 500e6, 3.24, 0.23)
    pdf = generate_report({
        "language": "pt", "company_name": "Teste", "tested_party_name": "Teste",
        "method": "MLT", "pli": "Margem Operacional", "fiscal_year": "2024",
        "iqr_result": iqr,
        "country_risk": {"applied": True, "crp_tested": 3.24, "crp_comp": 0.23,
                         "source": "Damodaran — NYU Stern (jan/2026)",
                         "n_adjusted": 1, "n_foreign_skipped": 1,
                         "justification": ""},  # empty → PDF auto-generates rationale
        "comparables": [
            {"name": "US Adjusted Co", "value": round(cr["adjusted_margin"], 4),
             "source": "SEC EDGAR 2024 (10-K)",
             "source_url": "https://www.sec.gov/x",
             "breakdown": {"kind": "operating", "num": 200e6, "den": 1000e6,
                           "margin": 20.0, "currency": "USD"},
             "cr_adjustment": {**cr, "currency": "USD"}},
            {"name": "US Skipped Co", "value": 24.0, "source": "SEC EDGAR 2024 (10-K)"},
            {"name": "BR Co", "value": 16.0, "source": "CVM Brasil 2024 (DFP)"},
        ],
    })
    assert pdf[:4] == b"%PDF" and len(pdf) > 2000
    # The audit-trail line itself: official-style math, localized
    txt = _cr_adjustment_text({**cr, "currency": "USD"}, "pt")
    assert "Anexo II" in txt and "3,24%" in txt and "0,23%" in txt and "capital empregado" in txt
    # User-provided rationale must also render (art. 32 justification path)
    pdf2 = generate_report({
        "language": "pt", "company_name": "Teste", "tested_party_name": "Teste",
        "method": "MLT", "pli": "Margem Operacional", "fiscal_year": "2024",
        "iqr_result": iqr,
        "country_risk": {"applied": True, "crp_tested": 3.24, "crp_comp": 0.23,
                         "source": "X", "n_adjusted": 1, "n_foreign_skipped": 0,
                         "justification": "Justificativa própria <com& xml>"},
        "comparables": [
            {"name": "US Co", "value": 21.0, "source": "SEC EDGAR 2024 (10-K)",
             "cr_adjustment": {**cr, "currency": "USD"}}],
    })
    assert pdf2[:4] == b"%PDF"


# ── Fileable Local File items I/II/VI (art. 61) ──────────────────────────────
def test_pdf_local_file_items():
    iqr = calculate_iqr([20.0, 15.0, 10.0], tested_party_value=15.0)
    base = {
        "language": "pt", "company_name": "Teste", "tested_party_name": "Exemplo BR Ltda",
        "transaction_description": "Importação de mercadorias da matriz",
        "method": "MLT", "pli": "Margem Operacional", "fiscal_year": "2024",
        "iqr_result": iqr,
        "comparables": [{"name": "A", "value": 20.0, "source": "Annual Report"}],
    }
    # Without the LF items the report still generates (graceful)
    plain = generate_report(base)
    # With items I (parties), II (transaction), VI (adjustment) the report is heavier
    full = generate_report({**base,
        "lf_group": "ABC Group", "lf_tp_cnpj": "00.000.000/0001-00",
        "lf_rp_name": "ABC Holding GmbH & Co", "lf_rp_country": "Alemanha",
        "lf_rp_taxid": "DE123456789",
        "lf_tx_type": "Importação de bens", "lf_tx_value": "R$ 3.200.000,00",
        "lf_adj_type": "Ajuste compensatório", "lf_adj_value": "R$ 180.000,00",
        "lf_adj_note": "Ajuste à base do IRPJ <no> encerramento & fechamento"})
    assert plain[:4] == b"%PDF" and full[:4] == b"%PDF"
    assert len(full) > len(plain) + 300
    # "No adjustment" declaration also renders (art. 61, VI is a required statement)
    none_adj = generate_report({**base, "lf_group": "X",
                                "lf_adj_type": "Nenhum ajuste realizado"})
    assert none_adj[:4] == b"%PDF"
