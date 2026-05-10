from .base import calculate_iqr, IQRResult
from typing import Optional
import pandas as pd

# ── MLT — Margem Líquida da Transação (TNMM, Transactional Net Margin Method) ────
def calculate_tnmm(comparables_df: pd.DataFrame,
                   pli_column: str,
                   tested_party_value: Optional[float] = None) -> IQRResult:
    """
    MLT (TNMM) — Método da Margem Líquida da Transação
    Most widely used under IN RFB 2.161/2023 / OECD TP Guidelines.
    PLI options: operating margin, EBITDA margin, Berry ratio, net margin, ROCE
    """
    values = comparables_df[pli_column].dropna().tolist()
    pli_labels = {
        "operating_margin": "Operating Margin (%)",
        "ebitda_margin": "EBITDA Margin (%)",
        "berry_ratio": "Berry Ratio",
        "net_margin": "Net Profit Margin (%)",
        "roce": "Return on Operating Assets (%)"
    }
    pli_label = pli_labels.get(pli_column, pli_column)
    return calculate_iqr(values, tested_party_value, method="MLT (TNMM)", pli=pli_label)


# ── PIC (Comparable Uncontrolled Price / CUP) ───────────────────────────────
def calculate_pic(comparable_prices: list,
                  tested_party_price: Optional[float] = None,
                  currency: str = "USD") -> IQRResult:
    """
    PIC / CUP — Preço Independente Comparável
    Compares transaction price directly against comparable uncontrolled prices.
    """
    return calculate_iqr(
        comparable_prices, tested_party_price,
        method="PIC / CUP",
        pli=f"Transaction Price ({currency})"
    )


# ── PRL (Resale Price Method / RPM) ─────────────────────────────────────────
def calculate_prl(resale_price: float,
                  gross_margin_pct: float) -> dict:
    """
    PRL — Preço de Revenda menos Lucro
    Arms length price = Resale Price × (1 - Gross Margin %)
    """
    arms_length_price = resale_price * (1 - gross_margin_pct / 100)
    return {
        "method": "PRL / Resale Price Method",
        "resale_price": resale_price,
        "gross_margin_pct": gross_margin_pct,
        "arms_length_price": arms_length_price,
        "formula": f"{resale_price:.2f} × (1 - {gross_margin_pct:.1f}%) = {arms_length_price:.2f}"
    }


def calculate_prl_margin_range(comparable_margins: list,
                               resale_price: float,
                               tested_party_price: Optional[float] = None) -> dict:
    """
    PRL with IQR on comparable gross margins, then compute price range.
    """
    iqr = calculate_iqr(comparable_margins, method="PRL / Resale Price Method",
                        pli="Gross Margin (%)")
    price_at_q1 = resale_price * (1 - iqr.q3 / 100)
    price_at_q3 = resale_price * (1 - iqr.q1 / 100)
    price_at_median = resale_price * (1 - iqr.median / 100)

    is_arms_length = None
    if tested_party_price is not None:
        is_arms_length = price_at_q1 <= tested_party_price <= price_at_q3

    return {
        "iqr": iqr,
        "resale_price": resale_price,
        "price_range": (price_at_q1, price_at_median, price_at_q3),
        "tested_party_price": tested_party_price,
        "is_arms_length": is_arms_length,
        "method": "PRL / Resale Price Method"
    }


# ── MCL — Custo Mais Lucro (Cost Plus Method) ─────────────────────────────────
def calculate_mcm(cost_base: float,
                  markup_pct: float) -> dict:
    """
    MCL — Método do Custo mais Lucro
    Arms length price = Cost × (1 + Markup %)
    """
    arms_length_price = cost_base * (1 + markup_pct / 100)
    return {
        "method": "MCL (Cost Plus)",
        "cost_base": cost_base,
        "markup_pct": markup_pct,
        "arms_length_price": arms_length_price,
        "formula": f"{cost_base:.2f} × (1 + {markup_pct:.1f}%) = {arms_length_price:.2f}"
    }


def calculate_mcm_markup_range(comparable_markups: list,
                                cost_base: float,
                                tested_party_price: Optional[float] = None) -> dict:
    """
    MCL with IQR on comparable markups, then compute price range.
    """
    iqr = calculate_iqr(comparable_markups, method="MCL (Cost Plus)",
                        pli="Gross Markup (%)")
    price_at_q1 = cost_base * (1 + iqr.q1 / 100)
    price_at_q3 = cost_base * (1 + iqr.q3 / 100)
    price_at_median = cost_base * (1 + iqr.median / 100)

    is_arms_length = None
    if tested_party_price is not None:
        is_arms_length = price_at_q1 <= tested_party_price <= price_at_q3

    return {
        "iqr": iqr,
        "cost_base": cost_base,
        "price_range": (price_at_q1, price_at_median, price_at_q3),
        "tested_party_price": tested_party_price,
        "is_arms_length": is_arms_length,
        "method": "MCL (Cost Plus)"
    }


# ── PCI / PECEX (Import/Export Price Methods) ────────────────────────────────
def calculate_pci_pecex(comparable_prices: list,
                         tested_party_price: Optional[float] = None,
                         direction: str = "import",
                         currency: str = "USD") -> IQRResult:
    """
    PCI — Preço sob Cotação na Importação (imports from commodities markets)
    PECEX — Preço sob Cotação na Exportação (exports to commodities markets)
    Primarily used for commodities with public quotation prices.
    """
    method_name = "PCI (Import)" if direction == "import" else "PECEX (Export)"
    return calculate_iqr(
        comparable_prices, tested_party_price,
        method=method_name,
        pli=f"Quoted Market Price ({currency})"
    )
