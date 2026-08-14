"""Which fiscal year actually has published data in both sources.

The app used to hardcode the default fiscal year. That default goes stale
every January: through most of 2026 the app opened on 2024 while the Arquivo
Local due 31/10/2026 documents exercise 2025 — a visitor who didn't notice
would benchmark against the wrong year and get a report stamped with it.

Publication lag is what sets the answer, and both sources land in the same
window:
  - CVM: the DFP for exercise Y is filed by 31/March of Y+1 (Lei 6.404 art. 132
    + ICVM/RCVM filing calendar), and the open-data zip is consolidated after.
  - SEC: the 10-K for FY Y is due 60 days after year-end for large accelerated
    filers and up to 90 days for the rest — so by late March of Y+1.

We wait until 1 May of Y+1 before treating Y as available. That is ~1 month of
slack past both deadlines, covering late filers and the CVM dataset rebuild,
and it errs toward a year that is complete rather than one that is half-filed:
a thin year silently shrinks the comparables set, which is worse than being one
year conservative for four months.
"""

from datetime import date
from typing import Optional

# Month from which exercise (year - 1) is considered fully published.
_AVAILABILITY_CUTOFF_MONTH = 5

# Earliest exercise the sources are wired for (matches the UI floor).
EARLIEST_FISCAL_YEAR = 2015


def latest_available_fiscal_year(today: Optional[date] = None) -> int:
    """Most recent fiscal year with complete data in CVM and SEC.

    >>> latest_available_fiscal_year(date(2026, 8, 14))   # past the cutoff
    2025
    >>> latest_available_fiscal_year(date(2027, 2, 10))   # 2026 not filed yet
    2025
    >>> latest_available_fiscal_year(date(2027, 5, 1))    # cutoff day itself
    2026
    """
    today = today or date.today()
    year = today.year - 1 if today.month >= _AVAILABILITY_CUTOFF_MONTH else today.year - 2
    return max(year, EARLIEST_FISCAL_YEAR)
