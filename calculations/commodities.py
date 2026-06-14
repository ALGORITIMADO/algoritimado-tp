"""Método PIC para commodities — Art. 35–38 da IN RFB 2.161/2023.

Mecânica verificada no texto primário (Art. 37):
- O valor arm's length da commodity é a COTAÇÃO na data de precificação
  (Art. 37 §3) obtida de bolsa/agência reconhecida (Art. 36, II), AJUSTADA
  por diferenças que afetem materialmente o preço (Art. 37 §1: frete,
  qualidade, prêmio, condições de entrega...).
- O preço praticado na transação controlada é comparado a essa referência
  ajustada; a divergência é o ajuste de preços de transferência.
- A transação deve ser registrada no RTC (Art. 38; IN 2.246/2024).

Não há intervalo interquartil aqui: a referência é uma cotação única
ajustada, não um conjunto de comparáveis. Os ajustes entram com sinal
definido pelo usuário (o profissional decide o sentido conforme a base da
cotação vs. as condições da transação) — a ferramenta mostra a conta.
"""
from typing import Dict


def calculate_pic_commodity(
    practiced_price: float,
    quotation_price: float,
    adjustments_total: float = 0.0,
    direction: str = "import",
    currency: str = "USD",
) -> Dict:
    """Compara o preço praticado com a cotação ajustada (Art. 37).

    `adjustments_total` é o total LÍQUIDO de ajustes de comparabilidade, com
    sinal (positivo soma à cotação, negativo subtrai). Retorna a referência
    arm's length, a diferença e o ajuste sugerido — em precisão cheia.
    """
    if quotation_price is None or quotation_price <= 0:
        raise ValueError("quotation_price must be positive")
    if practiced_price is None:
        raise ValueError("practiced_price is required")

    reference = quotation_price + adjustments_total       # cotação ± ajustes
    if reference <= 0:
        # Ajustes líquidos não podem anular/inverter a cotação: uma referência
        # arm's length ≤ 0 não tem sentido econômico (Art. 37). Sinaliza erro de
        # entrada em vez de produzir percentual/ajuste com sinal invertido.
        raise ValueError(
            "adjusted reference must be positive (quotation + adjustments)"
        )
    difference = practiced_price - reference               # praticado vs. referência
    suggested_adjustment = reference - practiced_price     # quanto mover a base
    pct_diff = (difference / reference * 100.0) if reference else 0.0
    # Conformidade: o preço praticado deve igualar a cotação ajustada. Tolerância
    # apenas para ruído de float (não é uma faixa legal — qualquer divergência
    # material é ajuste, Art. 37).
    is_arms_length = abs(difference) <= 1e-9
    return {
        "method": "PIC — Commodities" + (" (Importação)" if direction == "import"
                                          else " (Exportação)"),
        "direction": direction,
        "currency": currency,
        "quotation_price": quotation_price,
        "adjustments_total": adjustments_total,
        "reference": reference,
        "practiced_price": practiced_price,
        "difference": difference,
        "pct_diff": pct_diff,
        "suggested_adjustment": suggested_adjustment,
        "is_arms_length": is_arms_length,
    }
