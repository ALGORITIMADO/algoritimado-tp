"""Ajuste de comparabilidade por risco-país — Anexo II da IN RFB 2.161/2023.

Fórmula oficial (orientação, não obrigação — o Anexo "ilustra uma possível
abordagem"):

    Ajuste = (Prêmio Risco-País do país da parte testada
              − Prêmio Risco-País do país do comparável) × Capital Empregado

    Capital Empregado = ativos fixos operacionais + capital de giro
    Capital de Giro   = ativo circulante − passivo circulante

O valor do ajuste é SOMADO ao lucro operacional do comparável e a margem é
recalculada sobre a mesma receita. O sinal do diferencial é preservado: se o
comparável operar em país mais arriscado que a parte testada, o ajuste é
negativo. Cálculo em precisão cheia; arredondamento (half-up, como na tabela
oficial) é responsabilidade da camada de exibição.
"""
from typing import Dict


def adjust_comparable_margin(
    operating_income: float,
    revenue: float,
    capital_employed: float,
    crp_tested_pct: float,
    crp_comparable_pct: float,
) -> Dict:
    """Aplica o ajuste do Anexo II a UM comparável e devolve a conta inteira.

    Os prêmios entram em pontos percentuais (ex.: 3.24 = 3,24%). Retorna dict
    com o ajuste monetário, o lucro operacional ajustado e a margem ajustada
    (%), além das peças necessárias para "mostrar a conta" no relatório.
    """
    if revenue is None or revenue <= 0:
        raise ValueError("revenue must be positive")
    if operating_income is None or capital_employed is None:
        raise ValueError("operating_income and capital_employed are required")

    differential_pct = crp_tested_pct - crp_comparable_pct
    adjustment = differential_pct / 100.0 * capital_employed
    adjusted_oi = operating_income + adjustment
    return {
        "differential_pct": differential_pct,
        "capital_employed": capital_employed,
        "adjustment": adjustment,
        "operating_income_before": operating_income,
        "adjusted_operating_income": adjusted_oi,
        "margin_before": operating_income / revenue * 100.0,
        "adjusted_margin": adjusted_oi / revenue * 100.0,
        "crp_tested_pct": crp_tested_pct,
        "crp_comparable_pct": crp_comparable_pct,
    }
