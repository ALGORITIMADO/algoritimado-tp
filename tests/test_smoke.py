"""Offline smoke tests — no network. Guard the riskiest logic before deploy:
IQR math, year-aligned extraction, breakdown, CVM scale, and PDF generation.

Run locally: scripts/preflight.sh  (or: pytest -q)
Runs automatically in CI on every push/PR (.github/workflows/ci.yml).
"""
import pandas as pd

from calculations.base import calculate_iqr
from calculations.country_risk import adjust_comparable_margin
from calculations.commodities import calculate_pic_commodity
from data.edgar_fetcher import extract_financials, _pli_breakdown
import data.cvm_fetcher as cvm_fetcher
from data.cvm_fetcher import (calculate_margins_cvm, _pli_breakdown_cvm,
                              _only_active_companies, search_companies_cvm)
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
        "CD_CONTA": ["3.01", "3.05", "3.11"],
        "DS_CONTA": ["Receita de Venda de Bens e/ou Serviços",
                     "Resultado Antes do Resultado Financeiro e dos Tributos",
                     "Lucro/Prejuízo Consolidado do Período"],
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
        "CD_CONTA": ["3.01", "3.05", "3.01", "3.05"],
        "DS_CONTA": ["Receita de Venda de Bens e/ou Serviços",
                     "Resultado Antes do Resultado Financeiro e dos Tributos"] * 2,
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
    # Baseline that triggers NEITHER note: a manually typed comparable.
    manual_only = generate_report({**base, "comparables": [
        {"name": "Manual Co", "value": 20.0, "source": "Manual"}]})
    domestic_only = generate_report({**base, "comparables": [
        {"name": "BR Co", "value": 20.0, "source": "CVM Brasil 2024 (DFP)"}]})
    with_foreign = generate_report({**base, "comparables": [
        {"name": "US Co", "value": 20.0, "source": "SEC EDGAR 2024 (10-K)"}]})
    assert all(p[:4] == b"%PDF" for p in (manual_only, domestic_only, with_foreign))
    # Each source carries its own disclosure paragraph: art. 23 / Anexo II for the
    # foreign set, the CVM selection criterion for the Brazilian one.
    assert len(with_foreign) > len(manual_only) + 200
    assert len(domestic_only) > len(manual_only) + 200


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


# ── Master File (Arquivo Global, art. 58) ────────────────────────────────────
def test_master_file_pdf():
    # Empty Global File still renders (shows the 6 art. 58 placeholders)
    empty = generate_report({"doc_type": "master_file", "language": "pt",
                             "mf_group": "ABC Group"})
    assert empty[:4] == b"%PDF" and len(empty) > 2000
    # Filled Global File renders; XML-unsafe text and newlines are handled
    # (the '&' and '<...>' must not break ReportLab markup).
    filled = generate_report({"doc_type": "master_file", "language": "pt",
        "mf_group": "ABC Group", "analysis_date": "13/06/2026",
        "mf_org": "Holding na Alemanha & subsidiárias <BR/AR>\nLinha 2",
        "mf_activities": "Distribuição farma; cadeia dos 5 maiores produtos",
        "mf_intangibles": "Marca e patentes detidas pela holding",
        "mf_financial": "Financiamento centralizado na tesouraria europeia",
        "mf_apa": "Nenhum APA vigente", "mf_financials": "DFs consolidadas 2025"})
    assert filled[:4] == b"%PDF" and len(filled) > 2000
    # English variant
    en = generate_report({"doc_type": "master_file", "language": "en",
                          "mf_group": "ABC Group", "mf_org": "Holding in Germany"})
    assert en[:4] == b"%PDF"


# ── PIC commodities + RTC (art. 37-38) ───────────────────────────────────────
def test_pic_commodity_math():
    # Quotation 100 + adjustments 5 = reference 105; practiced 105 → compliant
    r = calculate_pic_commodity(105.0, 100.0, 5.0, direction="export")
    assert r["reference"] == 105.0 and r["is_arms_length"] is True
    assert abs(r["suggested_adjustment"]) < 1e-9
    # Practiced 98 vs reference 105 → divergence, adjustment +7 to reach arm's length
    r2 = calculate_pic_commodity(98.0, 100.0, 5.0, direction="import")
    assert r2["is_arms_length"] is False
    assert abs(r2["difference"] - (-7.0)) < 1e-9
    assert abs(r2["suggested_adjustment"] - 7.0) < 1e-9
    # Negative adjustments subtract from the quotation
    r3 = calculate_pic_commodity(95.0, 100.0, -5.0, direction="export")
    assert r3["reference"] == 95.0 and r3["is_arms_length"] is True


def test_pic_commodity_guards():
    # Quotation must be positive
    try:
        calculate_pic_commodity(100.0, 0.0, 0.0)
        assert False, "expected ValueError for non-positive quotation"
    except ValueError:
        pass
    # Adjustments cannot cancel/invert the quotation (reference must stay > 0)
    try:
        calculate_pic_commodity(100.0, 100.0, -100.0)
        assert False, "expected ValueError for reference <= 0"
    except ValueError:
        pass
    try:
        calculate_pic_commodity(100.0, 100.0, -120.0)
        assert False, "expected ValueError for negative reference"
    except ValueError:
        pass


def test_pdf_with_commodity_pic():
    # New commodity-PIC flow (art. 37): single quotation ± adjustments, NO IQR
    # and NO comparable set. The PDF must build from commodity_pic alone, with
    # iqr_result=None and comparables=[].
    cp = calculate_pic_commodity(98.0, 100.0, 5.0, direction="import", currency="USD")
    cp.update({"commodity": "Soja em grão", "source": "CME / CBOT",
               "pricing_date": "15/03/2025", "rtc_receipt": "RTC-2025-000123",
               "adj_desc": "+ frete CIF; − desconto de qualidade <2%> & ajuste"})
    pdf = generate_report({
        "language": "pt", "company_name": "Teste", "tested_party_name": "Teste",
        "method": "PIC — Commodities", "pli": "Preço (USD)", "fiscal_year": "2025",
        "iqr_result": None, "commodity_pic": cp,
        "comparables": [],
    })
    assert pdf[:4] == b"%PDF" and len(pdf) > 2000

    # English locale + an arm's-length (compliant) case must also build cleanly.
    cp_ok = calculate_pic_commodity(105.0, 100.0, 5.0, direction="export", currency="USD")
    cp_ok.update({"commodity": "Soybean", "source": "CME / CBOT",
                  "pricing_date": "03/15/2025", "rtc_receipt": "RTC-2025-000999"})
    pdf_ok = generate_report({
        "language": "en", "company_name": "Test Co", "tested_party_name": "Test Co",
        "method": "PIC — Commodities", "pli": "Price (USD)", "fiscal_year": "2025",
        "iqr_result": None, "commodity_pic": cp_ok,
        "comparables": [],
    })
    assert pdf_ok[:4] == b"%PDF" and len(pdf_ok) > 2000


# ── Auto Search: name filter must COMPOSE with the sector ────────────────────
# Regression guard for the 26/07/2026 lead: with a sector selected, the typed
# company name was silently discarded (`if industry ... elif company_name`), so
# eight different searches all returned the same six sector seeds.
def _patch_edgar_facts(monkeypatch):
    """Every CIK resolves to the same 2024 filing — isolates seed SELECTION."""
    import data.edgar_fetcher as ef
    monkeypatch.setattr(ef, "get_company_facts_v2", lambda cik: _facts())


def test_name_filters_within_selected_industry(monkeypatch):
    from data.edgar_fetcher import fetch_comparables_edgar
    _patch_edgar_facts(monkeypatch)
    df = fetch_comparables_edgar(industry="Manufacturing / Manufatura",
                                 company_name="Illinois", year=2024)
    assert list(df["name"]) == ["Illinois Tool Works Inc"]


def test_industry_only_still_returns_full_seed_list(monkeypatch):
    from data.edgar_fetcher import fetch_comparables_edgar, SIC_MAP
    _patch_edgar_facts(monkeypatch)
    df = fetch_comparables_edgar(industry="Manufacturing / Manufatura", year=2024)
    assert len(df) == len(SIC_MAP["Manufacturing / Manufatura"])


def test_unmatched_name_returns_empty_not_the_whole_sector(monkeypatch):
    """"FASTENERS" is a product, not a company name: honest empty beats a fake hit."""
    from data.edgar_fetcher import fetch_comparables_edgar
    _patch_edgar_facts(monkeypatch)
    df = fetch_comparables_edgar(industry="Manufacturing / Manufatura",
                                 company_name="FASTENERS", year=2024)
    assert df.empty


def test_name_outside_chosen_sector_widens_the_search(monkeypatch):
    from data.edgar_fetcher import fetch_comparables_edgar
    _patch_edgar_facts(monkeypatch)
    df = fetch_comparables_edgar(industry="Manufacturing / Manufatura",
                                 company_name="Walmart", year=2024)
    assert list(df["name"]) == ["Walmart Inc"]


def test_no_industry_and_no_name_returns_empty(monkeypatch):
    from data.edgar_fetcher import fetch_comparables_edgar
    _patch_edgar_facts(monkeypatch)
    assert fetch_comparables_edgar(year=2024).empty


# ── Annual period guard: a quarter tagged 10-K/FY is not a year ───────────────
# GE really does carry revenue rows marked form=10-K, fp=FY covering 2024-10-01 →
# 2024-12-31. Pairing a 3-month revenue with a 12-month operating profit inflates
# the margin ~4x, inside a number that goes into a filed report.
def _dpp(start, end, val, accn):
    """Datapoint WITH an explicit period (the `_dp` helper omits `start`)."""
    return {"form": "10-K", "fp": "FY", "start": start, "end": end,
            "val": val, "accn": accn}


def _facts_with_quarterly_revenue():
    return {"facts": {"us-gaap": {
        "Revenues": {"units": {"USD": [
            _dpp("2024-01-01", "2024-12-31", 1000, "acc-fy"),
            _dpp("2024-10-01", "2024-12-31", 250, "acc-q4"),   # quarter, same year
        ]}},
        "OperatingIncomeLoss": {"units": {"USD": [
            _dpp("2024-01-01", "2024-12-31", 200, "acc-fy")]}},
    }}}


def test_quarterly_period_tagged_fy_is_not_used_as_annual():
    fin = extract_financials(_facts_with_quarterly_revenue(), target_year=2024)
    assert fin["revenue_usd"] == 1000             # not the 250 of Q4
    assert fin["operating_margin"] == 20.0        # not 80.0


def test_company_with_only_quarterly_revenue_is_excluded():
    facts = {"facts": {"us-gaap": {
        "Revenues": {"units": {"USD": [_dpp("2024-10-01", "2024-12-31", 250, "acc-q4")]}},
        "OperatingIncomeLoss": {"units": {"USD": [
            _dpp("2024-01-01", "2024-12-31", 200, "acc-fy")]}},
    }}}
    assert extract_financials(facts, target_year=2024) is None


def test_52_53_week_fiscal_year_still_accepted():
    """Retail-style 364-day years must not be mistaken for a partial period."""
    facts = {"facts": {"us-gaap": {
        "Revenues": {"units": {"USD": [_dpp("2023-12-31", "2024-12-29", 1000, "a")]}},
        "OperatingIncomeLoss": {"units": {"USD": [_dpp("2023-12-31", "2024-12-29", 150, "a")]}},
    }}}
    fin = extract_financials(facts, target_year=2024)
    assert fin["operating_margin"] == 15.0


def test_datapoint_without_start_date_still_accepted():
    """Facts arriving with no period start can't be measured — stay permissive."""
    fin = extract_financials(_facts(), target_year=2024)   # _dp() omits `start`
    assert fin["operating_margin"] == 20.0


# ── Revenue selection: total, and net of assessed tax ────────────────────────
def test_partial_revenue_tag_loses_to_the_true_total():
    """General Mills tags `Revenues`=2.0bn beside 19.9bn of net sales (168% margin)."""
    facts = {"facts": {"us-gaap": {
        "Revenues": {"units": {"USD": [_dpp("2023-05-29", "2024-05-26", 2_037_800_000, "a")]}},
        "RevenueFromContractWithCustomerExcludingAssessedTax": {"units": {"USD": [
            _dpp("2023-05-29", "2024-05-26", 19_857_200_000, "a")]}},
        "OperatingIncomeLoss": {"units": {"USD": [
            _dpp("2023-05-29", "2024-05-26", 3_431_700_000, "a")]}},
    }}}
    fin = extract_financials(facts, target_year=2024)
    assert fin["revenue_usd"] == 19_857_200_000
    assert fin["operating_margin"] == 17.2819


def test_gross_revenue_never_beats_net_revenue():
    """Cronos: 161.8M gross (with excise) vs 117.6M net. TP wants the net one —
    so the bigger-wins rule must not drag the denominator up to gross."""
    facts = {"facts": {"us-gaap": {
        "RevenueFromContractWithCustomerExcludingAssessedTax": {"units": {"USD": [
            _dpp("2024-01-01", "2024-12-31", 117_615_000, "a")]}},
        "RevenueFromContractWithCustomerIncludingAssessedTax": {"units": {"USD": [
            _dpp("2024-01-01", "2024-12-31", 161_821_000, "a")]}},
        "OperatingIncomeLoss": {"units": {"USD": [
            _dpp("2024-01-01", "2024-12-31", -76_500_000, "a")]}},
    }}}
    fin = extract_financials(facts, target_year=2024)
    assert fin["revenue_usd"] == 117_615_000


def test_gross_revenue_used_when_net_is_absent():
    """No Excluding tag for the period → the gross figure is all there is."""
    facts = {"facts": {"us-gaap": {
        "RevenueFromContractWithCustomerIncludingAssessedTax": {"units": {"USD": [
            _dpp("2024-01-01", "2024-12-31", 161_821_000, "a")]}},
        "OperatingIncomeLoss": {"units": {"USD": [
            _dpp("2024-01-01", "2024-12-31", 16_182_100, "a")]}},
    }}}
    fin = extract_financials(facts, target_year=2024)
    assert fin["revenue_usd"] == 161_821_000
    assert fin["operating_margin"] == 10.0


def test_lease_heavy_reit_keeps_total_revenue():
    """REIT: rent isn't ASC 606 contract revenue, so `Revenues` is the real total.
    Preferring the contract tag here produced margins above 1000%."""
    facts = {"facts": {"us-gaap": {
        "Revenues": {"units": {"USD": [_dpp("2024-01-01", "2024-12-31", 3_000_000, "a")]}},
        "RevenueFromContractWithCustomerExcludingAssessedTax": {"units": {"USD": [
            _dpp("2024-01-01", "2024-12-31", 100_000, "a")]}},
        "OperatingIncomeLoss": {"units": {"USD": [
            _dpp("2024-01-01", "2024-12-31", 1_200_000, "a")]}},
    }}}
    fin = extract_financials(facts, target_year=2024)
    assert fin["revenue_usd"] == 3_000_000
    assert fin["operating_margin"] == 40.0


# ── CVM account ladder (3.03 bruto / 3.05 EBIT / 3.07 EBT) ───────────────────
def _blau_dre():
    """Blau Farmacêutica FY2024, exactly as filed (CD_CVM 24627, valores em MIL).

    Conferido contra a DFP protocolada — a mesma fixture usada na PoC do motor CVM.
    """
    linhas = [
        ("3.01", "Receita de Venda de Bens e/ou Serviços", 1_754_376),
        ("3.02", "Custo dos Bens e/ou Serviços Vendidos", -1_095_626),
        ("3.03", "Resultado Bruto", 658_750),
        ("3.04", "Despesas/Receitas Operacionais", -329_953),
        ("3.05", "Resultado Antes do Resultado Financeiro e dos Tributos", 328_797),
        ("3.06", "Resultado Financeiro", -36_908),
        ("3.07", "Resultado Antes dos Tributos sobre o Lucro", 291_889),
        ("3.11", "Lucro/Prejuízo Consolidado do Período", 213_525),
    ]
    return pd.DataFrame({
        "CD_CVM": ["24627"] * len(linhas),
        "DT_FIM_EXERC": ["2024-12-31"] * len(linhas),
        "ESCALA_MOEDA": ["MIL"] * len(linhas),
        "CD_CONTA": [l[0] for l in linhas],
        "DS_CONTA": [l[1] for l in linhas],
        "VL_CONTA": [l[2] for l in linhas],
    })


def test_cvm_margins_match_the_filed_statement():
    m = calculate_margins_cvm(_blau_dre(), "24627", "CD_CVM")
    assert m["gross_margin"] == 37.549         # 658.750 / 1.754.376 — era 18.74 (EBIT)
    assert m["operating_margin"] == 18.7415    # 328.797 / 1.754.376 — era 16.64 (EBT)
    assert m["net_margin"] == 12.171          # 213.525 / 1.754.376
    assert m["gross_profit_brl"] == 658_750_000
    assert m["ebit_brl"] == 328_797_000


def test_cvm_never_reads_pre_tax_result_as_operating():
    """3.07 (Resultado Antes dos Tributos) must never feed the operating margin."""
    m = calculate_margins_cvm(_blau_dre(), "24627", "CD_CVM")
    assert m["ebit_brl"] != 291_889_000        # o EBT não pode virar EBIT


def test_cvm_bank_ladder_does_not_masquerade_as_ebit():
    """Bancos publicam outra escada sob os mesmos códigos: o 3.05 deles já é o
    resultado ANTES DOS TRIBUTOS. Sem margem operacional é melhor que uma errada."""
    linhas = [
        ("3.01", "Receitas da Intermediação Financeira", 10_000),
        ("3.03", "Resultado Bruto Intermediação Financeira", 4_000),
        ("3.05", "Resultado Antes dos Tributos sobre o Lucro", 2_500),
        ("3.11", "Lucro ou Prejuízo Líquido Consolidado do Período", 1_800),
    ]
    df = pd.DataFrame({
        "CD_CVM": ["9999"] * len(linhas),
        "DT_FIM_EXERC": ["2024-12-31"] * len(linhas),
        "ESCALA_MOEDA": ["MIL"] * len(linhas),
        "CD_CONTA": [l[0] for l in linhas],
        "DS_CONTA": [l[1] for l in linhas],
        "VL_CONTA": [l[2] for l in linhas],
    })
    m = calculate_margins_cvm(df, "9999", "CD_CVM")
    assert "operating_margin" not in m         # rótulo não bate → não inventa EBIT
    assert m["gross_margin"] == 40.0
    assert m["net_margin"] == 18.0


def test_cvm_subaccount_never_replaces_the_total():
    """"3.01" também é prefixo de "3.01.01": só o código exato vale."""
    linhas = [
        ("3.01.01", "Venda de Mercadorias (segmento)", 300),
        ("3.01", "Receita de Venda de Bens e/ou Serviços", 1_000),
        ("3.05", "Resultado Antes do Resultado Financeiro e dos Tributos", 200),
    ]
    df = pd.DataFrame({
        "CD_CVM": ["1"] * len(linhas),
        "DT_FIM_EXERC": ["2024-12-31"] * len(linhas),
        "ESCALA_MOEDA": ["MIL"] * len(linhas),
        "CD_CONTA": [l[0] for l in linhas],
        "DS_CONTA": [l[1] for l in linhas],
        "VL_CONTA": [l[2] for l in linhas],
    })
    m = calculate_margins_cvm(df, "1", "CD_CVM")
    assert m["revenue_brl"] == 1_000_000       # não os 300 da sub-conta
    assert m["operating_margin"] == 20.0


# ── Cadastro CVM: só empresa viva entra no pool de candidatos ─────────────────
def test_cancelled_registrations_are_dropped():
    """1.912 das 2.677 linhas do cadastro são CANCELADA; em Manufatura, 220 de 259.
    Elas consumiam o orçamento de candidatos e o setor voltava com 2 comparáveis."""
    cad = pd.DataFrame({
        "CD_CVM": [1, 2, 3, 4],
        "DENOM_SOCIAL": ["VIVA SA", "MORTA SA", "SUSPENSA SA", "VIVA2 SA"],
        "SIT": ["ATIVO", "CANCELADA", "SUSPENSO(A) - DECISÃO ADM", "ativo "],
    })
    out = _only_active_companies(cad)
    assert list(out["CD_CVM"]) == [1, 4]        # inclui o "ativo " com espaço/caixa


def test_duplicate_registry_rows_collapse_to_one():
    cad = pd.DataFrame({
        "CD_CVM": [7, 7, 8],
        "DENOM_SOCIAL": ["X SA", "X SA (novo registro)", "Y SA"],
        "SIT": ["ATIVO"] * 3,
    })
    out = _only_active_companies(cad)
    assert len(out) == 2
    assert out[out["CD_CVM"] == 7]["DENOM_SOCIAL"].iloc[0] == "X SA (novo registro)"


# ── Emissor precisa estar operando, não só registrado ────────────────────────
def test_non_operating_issuers_are_excluded():
    """Recuperação judicial, falência, liquidação, paralisia e pré-operacional não
    operam em condições normais — a margem deles não é parâmetro arm's length."""
    cad = pd.DataFrame({
        "CD_CVM": [1, 2, 3, 4, 5, 6],
        "DENOM_SOCIAL": ["OPERANTE SA", "BARDELLA SA", "FALIDA SA",
                         "EM LIQUIDACAO SA", "PARADA SA", "NOVA SA"],
        "SIT": ["ATIVO"] * 6,
        "SIT_EMISSOR": ["FASE OPERACIONAL",
                        "EM RECUPERAÇÃO JUDICIAL OU EQUIVALENTE",
                        "FALIDA", "LIQUIDAÇÃO EXTRAJUDICIAL",
                        "PARALISADA", "FASE PRÉ-OPERACIONAL"],
    })
    assert list(_only_active_companies(cad)["CD_CVM"]) == [1]


def test_registry_without_the_emitter_column_still_works():
    """Se a CVM deixar de publicar SIT_EMISSOR, o filtro de SIT continua valendo."""
    cad = pd.DataFrame({
        "CD_CVM": [1, 2],
        "DENOM_SOCIAL": ["A SA", "B SA"],
        "SIT": ["ATIVO", "CANCELADA"],
    })
    assert list(_only_active_companies(cad)["CD_CVM"]) == [1]


def test_report_documents_why_brazilian_comparables_were_excluded():
    """Art. 32 espera critério de comparabilidade documentado: o laudo tem de
    dizer que emissores fora de fase operacional foram excluídos."""
    from calculations.base import calculate_iqr
    iqr = calculate_iqr([10.0, 15.0, 20.0, 25.0], tested_party_value=18.0)
    pdf = generate_report({
        "language": "pt", "company_name": "Teste", "tested_party_name": "Teste",
        "method": "MLT (TNMM)", "pli": "Margem Operacional (%)", "fiscal_year": "2024",
        "iqr_result": iqr,
        "comparables": [
            {"name": "BLAU FARMACÊUTICA S.A.", "value": 18.74, "source": "CVM Brasil 2024"},
            {"name": "BAUMER SA", "value": 18.51, "source": "CVM Brasil 2024"},
            {"name": "CIA SIDERURGICA NACIONAL", "value": 9.77, "source": "CVM Brasil 2024"},
        ],
    })
    assert pdf[:4] == b"%PDF" and len(pdf) > 2000


# ── Seed list: assento só vale se entrega o comparável ───────────────────────
# CIKs auditados em 28/07/2026 contra o XBRL vivo: nenhum devolve margem
# operacional em 2024 nem 2025. Empresas vivas, mas sem subtotal de resultado
# operacional publicado (Pfizer não tem a tag; Public Storage só etiqueta em
# 10-Q; banco não tem resultado operacional por construção). Este teste impede
# que voltem para a lista sem alguém checar de novo — em CI, offline.
CIKS_SEM_MARGEM_OPERACIONAL = {
    78003, 310158, 200406, 14272, 59478, 875045,          # pharma
    1584549, 1813452,                                      # cannabis
    7084, 1996862, 1755672,                                # agro
    1751788, 1666700, 915389,                              # química
    34088, 93410, 1163165, 1534701,                        # óleo e gás
    19617, 70858, 886982, 895421, 72971, 831001,           # bancos
    32604, 40545,                                          # manufatura
    1393311, 726728, 766704,                               # imobiliário
    1164727, 73309, 756894, 1675149,                       # mineração
}


def test_seed_list_has_no_known_dead_seats():
    from data.edgar_fetcher import SIC_MAP
    presentes = {cik for seeds in SIC_MAP.values() for cik, _ in seeds}
    intrusos = presentes & CIKS_SEM_MARGEM_OPERACIONAL
    assert not intrusos, f"CIKs que não entregam margem operacional: {sorted(intrusos)}"


def test_no_duplicate_company_inside_a_sector():
    from data.edgar_fetcher import SIC_MAP
    for setor, seeds in SIC_MAP.items():
        ciks = [cik for cik, _ in seeds]
        assert len(ciks) == len(set(ciks)), f"CIK repetido em {setor}"


def test_every_sector_has_enough_seeds_for_an_iqr():
    """calculate_iqr exige no mínimo 3 comparáveis; setor com menos que isso na
    origem nunca produziria um intervalo."""
    from data.edgar_fetcher import SIC_MAP
    magros = {s: len(v) for s, v in SIC_MAP.items() if len(v) < 5}
    assert not magros, f"setores abaixo de 5 seeds: {magros}"


# ── Busca por setor/nome tem de ignorar acento ───────────────────────────────
def _fake_cadastro():
    return pd.DataFrame({
        "CD_CVM": [1, 2, 3],
        "DENOM_SOCIAL": ["BRASKEM S.A.", "CIA SIDERÚRGICA NACIONAL", "PADARIA SA"],
        "SETOR_ATIV": ["Petroquímicos e Borracha", "Siderurgia e Metalurgia", "Alimentos"],
        "SIT": ["ATIVO"] * 3,
        "SIT_EMISSOR": ["FASE OPERACIONAL"] * 3,
    })


def test_sector_keyword_matches_accented_cvm_taxonomy(monkeypatch):
    """A taxonomia da CVM é acentuada ("Petroquímicos"); as palavras-chave são
    ASCII ("QUIMIC"). Sem normalizar, Química devolvia ZERO comparável no Brasil."""
    monkeypatch.setattr(cvm_fetcher, "get_cvm_company_list", lambda *a, **k: _fake_cadastro())
    out = search_companies_cvm(industry="Chemicals / Química")
    assert "BRASKEM S.A." in list(out["DENOM_SOCIAL"])


def test_company_name_search_ignores_accents(monkeypatch):
    """Ninguém digita "SIDERÚRGICA" com acento na busca."""
    monkeypatch.setattr(cvm_fetcher, "get_cvm_company_list", lambda *a, **k: _fake_cadastro())
    out = search_companies_cvm(company_name="siderurgica")
    assert list(out["DENOM_SOCIAL"]) == ["CIA SIDERÚRGICA NACIONAL"]


# ── Setores que a taxonomia da CVM não carrega ───────────────────────────────
def test_biotech_falls_back_to_the_cvm_pharma_bucket(monkeypatch):
    """A CVM classifica a Biomm (biotech) como "Farmacêutico e Higiene". Sem esse
    mapeamento, Biotecnologia devolvia zero comparável DOMÉSTICO — e é o doméstico
    que o art. 23 da IN 2.161 prioriza."""
    cad = pd.DataFrame({
        "CD_CVM": [1, 2],
        "DENOM_SOCIAL": ["BIOMM SA", "PADARIA SA"],
        "SETOR_ATIV": ["Farmacêutico e Higiene", "Alimentos"],
        "SIT": ["ATIVO"] * 2, "SIT_EMISSOR": ["FASE OPERACIONAL"] * 2,
    })
    monkeypatch.setattr(cvm_fetcher, "get_cvm_company_list", lambda *a, **k: cad)
    out = search_companies_cvm(industry="Biotech / Biotecnologia")
    assert list(out["DENOM_SOCIAL"]) == ["BIOMM SA"]


def test_cosmetics_falls_back_to_the_same_bucket(monkeypatch):
    cad = pd.DataFrame({
        "CD_CVM": [1, 2],
        "DENOM_SOCIAL": ["NATURA COSMETICOS SA", "MINERADORA SA"],
        "SETOR_ATIV": ["Farmacêutico e Higiene", "Extração Mineral"],
        "SIT": ["ATIVO"] * 2, "SIT_EMISSOR": ["FASE OPERACIONAL"] * 2,
    })
    monkeypatch.setattr(cvm_fetcher, "get_cvm_company_list", lambda *a, **k: cad)
    out = search_companies_cvm(industry="Cosmetics / Cosméticos")
    assert list(out["DENOM_SOCIAL"]) == ["NATURA COSMETICOS SA"]


def test_fallback_sectors_are_declared_for_the_ui():
    """O app precisa poder avisar de qual balde vieram — busca ampliada em
    silêncio é problema de comparabilidade esperando para acontecer."""
    from data.cvm_fetcher import CVM_SECTOR_FALLBACK, CNAE_MAP
    assert set(CVM_SECTOR_FALLBACK) <= set(CNAE_MAP)
    assert "Cannabis / Cannabis Medicinal" not in CVM_SECTOR_FALLBACK  # zero é fato de mercado


# ── Rastreabilidade CVM: extração da DRE do PDF protocolado ──────────────────
# Tudo offline: o que se testa é o parsing, a validação, a aritmética das margens
# e o confronto com o dado estruturado. A chamada ao Bedrock não entra em teste.
from data.cvm_pdf_extractor import (parse_extraction, normalize_extraction,      # noqa: E402
                                    cross_check, citation_text, _num)

_RESPOSTA_BLAU = """Segue o JSON solicitado:
{
  "empresa": "BLAU FARMACÊUTICA S.A.",
  "exercicio": "2024",
  "escala": "MIL",
  "itens": {
    "receita_liquida":       {"valor": 1754376, "pagina": 21, "rotulo": "Receita de Venda de Bens e/ou Serviços"},
    "lucro_bruto":           {"valor": 658750,  "pagina": 21, "rotulo": "Resultado Bruto"},
    "resultado_operacional": {"valor": 328797,  "pagina": 21, "rotulo": "Resultado Antes do Resultado Financeiro e dos Tributos"},
    "lucro_liquido":         {"valor": 213525,  "pagina": 21, "rotulo": "Lucro/Prejuízo Consolidado do Período"}
  }
}
"""


def test_parse_extraction_ignores_text_around_the_json():
    d = parse_extraction(_RESPOSTA_BLAU)
    assert d["empresa"].startswith("BLAU")


def test_parse_extraction_rejects_non_json():
    assert parse_extraction("não encontrei a DRE neste documento") is None
    assert parse_extraction("") is None


def test_margins_are_recomputed_from_the_extracted_values():
    """A divisão é NOSSA: o modelo lê a tabela bem e erra a aritmética às vezes."""
    d = normalize_extraction(parse_extraction(_RESPOSTA_BLAU))
    assert d["margens"]["margem_bruta_pct"] == 37.549        # 658.750 / 1.754.376
    assert d["margens"]["margem_operacional_pct"] == 18.7415
    assert d["margens"]["margem_liquida_pct"] == 12.171


def test_model_supplied_margins_are_never_trusted():
    """Mesmo que o modelo mande margem errada no JSON, vale a nossa conta."""
    payload = parse_extraction(_RESPOSTA_BLAU)
    payload["margens"] = {"margem_operacional_pct": 99.9}     # valor absurdo
    d = normalize_extraction(payload)
    assert d["margens"]["margem_operacional_pct"] == 18.7415


def test_extraction_without_revenue_fails_instead_of_guessing():
    payload = {"itens": {"lucro_bruto": {"valor": 100, "pagina": 3, "rotulo": "x"}}}
    assert normalize_extraction(payload) is None


def test_brazilian_number_format_is_accepted():
    assert _num("1.754.376") == 1754376.0
    assert _num("18,7415") == 18.7415
    assert _num("(1.208.109)") == -1208109.0
    assert _num(None) is None and _num("") is None


def test_cross_check_confirms_when_sources_agree():
    d = normalize_extraction(parse_extraction(_RESPOSTA_BLAU))
    r = cross_check(d, 18.74, "operating_margin")
    assert r["status"] == "confere"


def test_cross_check_flags_divergence_instead_of_averaging():
    """Duas fontes que discordam são um aviso — nunca uma média."""
    d = normalize_extraction(parse_extraction(_RESPOSTA_BLAU))
    r = cross_check(d, 16.64, "operating_margin")   # o valor do mapa de contas antigo
    assert r["status"] == "divergente"
    assert r["diferenca_pp"] > 2


def test_citation_carries_page_and_exact_line_label():
    d = normalize_extraction(parse_extraction(_RESPOSTA_BLAU))
    cit = citation_text(d, "operating_margin", "pt")
    assert "pág. 21" in cit and "Resultado Antes do Resultado Financeiro" in cit
    assert "p. 21" in citation_text(d, "operating_margin", "en")


def test_pdf_report_prints_the_page_citation():
    from calculations.base import calculate_iqr
    iqr = calculate_iqr([10.0, 15.0, 20.0, 25.0], tested_party_value=18.0)
    base = {
        "language": "pt", "company_name": "Teste", "tested_party_name": "Teste",
        "method": "MLT (TNMM)", "pli": "Margem Operacional (%)", "fiscal_year": "2024",
        "iqr_result": iqr,
    }
    sem = generate_report({**base, "comparables": [
        {"name": "BLAU", "value": 18.74, "source": "CVM Brasil 2024",
         "source_url": "https://cvm.gov.br/doc?x=1"}]})
    com = generate_report({**base, "comparables": [
        {"name": "BLAU", "value": 18.74, "source": "CVM Brasil 2024",
         "source_url": "https://cvm.gov.br/doc?x=1",
         "pdf_citation": 'DFP protocolada, pág. 21 · linha "Resultado Bruto"'}]})
    assert sem[:4] == b"%PDF" and com[:4] == b"%PDF"
    assert len(com) > len(sem)      # a citação acrescenta conteúdo à célula de fonte


# ── Trava de acesso: crédito de IA não é público ─────────────────────────────
# O app é aberto e cada extração custa dinheiro. O limite por sessão protege
# contra clique repetido; sessão qualquer visitante abre quantas quiser.
def test_allowlist_fails_closed_when_unset(monkeypatch):
    """Chave do Bedrock no secrets sem allowlist = ninguém autorizado.
    O pior caso passa a ser 'a funcionalidade não aparece', nunca crédito queimado."""
    import data.cvm_pdf_extractor as ex
    monkeypatch.setattr(ex, "_secret", lambda n, d="": "")
    assert ex.extraction_allowed("gabriela@algoritimado.com") is False


def test_allowlist_accepts_exact_email_and_domain(monkeypatch):
    import data.cvm_pdf_extractor as ex
    monkeypatch.setattr(ex, "_secret",
                        lambda n, d="": "JUNIOR@hassmann.com.br, @algoritimado.com")
    assert ex.extraction_allowed("junior@hassmann.com.br") is True      # caixa ignorada
    assert ex.extraction_allowed("  Junior@Hassmann.com.br ") is True   # espaços ignorados
    assert ex.extraction_allowed("qualquer@algoritimado.com") is True   # domínio liberado
    assert ex.extraction_allowed("curioso@gmail.com") is False
    assert ex.extraction_allowed("") is False
    assert ex.extraction_allowed("sem-arroba") is False


def test_domain_entry_does_not_match_lookalike_domain(monkeypatch):
    """'@algoritimado.com' não pode liberar 'algoritimado.com.br' ou sufixos."""
    import data.cvm_pdf_extractor as ex
    monkeypatch.setattr(ex, "_secret", lambda n, d="": "@algoritimado.com")
    assert ex.extraction_allowed("x@algoritimado.com.br") is False
    assert ex.extraction_allowed("x@naoalgoritimado.com") is False


def test_pipeline_refuses_unauthorized_before_spending(monkeypatch):
    """A checagem vive no pipeline também — não depende de a tela esconder o botão."""
    import data.cvm_pdf_extractor as ex
    monkeypatch.setattr(ex, "bedrock_available", lambda: True)
    monkeypatch.setattr(ex, "extraction_allowed", lambda e: False)
    def _nao_deveria(*a, **k):
        raise AssertionError("baixou o PDF de um usuário não autorizado")
    monkeypatch.setattr(ex, "download_dfp_pdf", _nao_deveria)
    assert ex.extract_from_link("https://x/y.zip", email="curioso@gmail.com") == {
        "ok": False, "erro": "nao_autorizado"}
