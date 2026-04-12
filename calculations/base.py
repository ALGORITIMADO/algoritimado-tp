import numpy as np
import pandas as pd
from dataclasses import dataclass
from typing import Optional

@dataclass
class IQRResult:
    q1: float
    median: float
    q3: float
    min_val: float
    max_val: float
    values: list
    tested_party_value: Optional[float] = None
    is_arms_length: Optional[bool] = None
    adjustment_needed: Optional[float] = None
    method: str = ""
    pli: str = ""

    def compliance_status(self, lang: str = "pt") -> str:
        if self.tested_party_value is None:
            return "N/A"
        if self.is_arms_length:
            return "Arm's Length" if lang == "en" else "Arm's Length"
        if lang == "pt":
            if self.tested_party_value < self.q1:
                return "Abaixo do Q1 — Ajuste Necessário"
            return "Acima do Q3 — Ajuste Necessário"
        else:
            if self.tested_party_value < self.q1:
                return "Below Q1 — Adjustment Needed"
            return "Above Q3 — Adjustment Needed"

    def compliance_color(self) -> str:
        if self.tested_party_value is None:
            return "gray"
        return "green" if self.is_arms_length else "red"


def calculate_iqr(values: list, tested_party_value: Optional[float] = None,
                  method: str = "", pli: str = "") -> IQRResult:
    arr = np.array([v for v in values if v is not None and not np.isnan(v)])
    if len(arr) < 3:
        raise ValueError("At least 3 comparable values required for IQR calculation.")

    q1 = float(np.percentile(arr, 25))
    median = float(np.percentile(arr, 50))
    q3 = float(np.percentile(arr, 75))
    min_val = float(np.min(arr))
    max_val = float(np.max(arr))

    is_arms_length = None
    adjustment_needed = None
    if tested_party_value is not None:
        is_arms_length = q1 <= tested_party_value <= q3
        if not is_arms_length:
            adjustment_needed = median - tested_party_value

    return IQRResult(
        q1=q1, median=median, q3=q3,
        min_val=min_val, max_val=max_val,
        values=list(arr),
        tested_party_value=tested_party_value,
        is_arms_length=is_arms_length,
        adjustment_needed=adjustment_needed,
        method=method,
        pli=pli
    )
