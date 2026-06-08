"""Currency conversion and the CHF risk-free series.

All P&L and metrics are in CHF (CLAUDE.md §7). Yahoo's ``CHF=X`` quotes
USD/CHF = CHF per 1 USD, so ``price_chf = price_usd * usdchf``. Alignment uses
TRAILING forward-fill only -- never bfill, which would pull a future rate
backward.
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from quant_backtest.config.parameters import (
    CHF_RF_FRED_ID,
    TRADING_DAYS_PER_YEAR,
    USDCHF_MAX,
    USDCHF_MIN,
    USDCHF_TICKER,
)
from quant_backtest.data import sources


def load_usdchf(
    start: date, end: date, calendar: pd.DatetimeIndex | None = None
) -> pd.Series:
    """Load the USD/CHF (CHF per USD) series, optionally aligned to a calendar.

    Args:
        start: Inclusive start date.
        end: Exclusive end date.
        calendar: Master trading calendar to reindex onto; if given, FX gaps are
            patched with a TRAILING forward-fill (FX quotes are step-like
            between sessions, so this introduces no look-ahead).

    Returns:
        USD/CHF as a float Series named ``USDCHF_TICKER``.
    """
    fx = sources.fetch_yfinance_series(USDCHF_TICKER, start, end)
    if calendar is not None:
        fx = fx.reindex(calendar).ffill()
    return fx


def to_chf(price_usd: pd.Series, usdchf: pd.Series) -> pd.Series:
    """Convert a USD price series to CHF using USD/CHF.

    Args:
        price_usd: USD-denominated price/level series.
        usdchf: USD/CHF (CHF per USD) series; reindexed onto ``price_usd`` with a
            trailing forward-fill before multiplying.

    Returns:
        CHF series, preserving ``price_usd``'s name and index.

    Raises:
        ValueError: If the aligned FX rate falls outside the plausible
            ``[USDCHF_MIN, USDCHF_MAX]`` range (catches an inverted series).
    """
    fx = usdchf.reindex(price_usd.index).ffill()
    valid = fx.dropna()
    if not valid.empty and not valid.between(USDCHF_MIN, USDCHF_MAX).all():
        raise ValueError(
            f"USDCHF outside [{USDCHF_MIN}, {USDCHF_MAX}] "
            f"(min={valid.min():.4f}, max={valid.max():.4f}) -- check FX direction"
        )
    converted = price_usd * fx
    converted.name = price_usd.name
    return converted


def load_chf_riskfree_daily(
    start: date, end: date, calendar: pd.DatetimeIndex | None = None
) -> pd.Series:
    """Load the CHF risk-free rate as a daily simple rate for Sharpe.

    The FRED CHF 3-month rate is quoted in PERCENT PER ANNUM and is monthly. It
    is converted to a per-trading-day simple rate and forward-filled to daily
    (TRAILING -- the rate is a step function between observations).

    Args:
        start: Inclusive start date.
        end: Exclusive end date.
        calendar: Master trading calendar to reindex onto; if omitted the native
            (forward-filled) index is returned.

    Returns:
        Daily simple CHF risk-free rate named ``CHF_RF_FRED_ID``.
    """
    annual_pct = sources.fetch_fred_series(CHF_RF_FRED_ID, start, end)
    daily = annual_pct / 100.0 / TRADING_DAYS_PER_YEAR
    if calendar is not None:
        union = calendar.union(pd.DatetimeIndex(daily.index))
        daily = daily.reindex(union).ffill().reindex(calendar)
    else:
        daily = daily.ffill()
    return daily.rename(CHF_RF_FRED_ID)
