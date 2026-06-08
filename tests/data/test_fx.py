"""FX conversion and CHF risk-free derivation."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from quant_backtest.config.parameters import TRADING_DAYS_PER_YEAR
from quant_backtest.data import fx
from quant_backtest.data import sources

START = date(1998, 1, 1)
SNAPSHOT = date(2026, 6, 1)


def test_to_chf_direction() -> None:
    """price_chf = price_usd * usdchf (CHF per USD)."""
    usd = pd.Series([100.0], index=pd.to_datetime(["2020-01-02"]))
    fx_series = pd.Series([0.97], index=pd.to_datetime(["2020-01-02"]))
    assert fx.to_chf(usd, fx_series).iloc[0] == pytest.approx(97.0)


def test_to_chf_trailing_ffill_only() -> None:
    """FX gaps are forward-filled (trailing); no future rate is pulled back."""
    usd = pd.Series([100.0, 100.0], index=pd.to_datetime(["2020-01-02", "2020-01-03"]))
    fx_series = pd.Series([0.90], index=pd.to_datetime(["2020-01-02"]))
    out = fx.to_chf(usd, fx_series)
    assert out.iloc[0] == pytest.approx(90.0)
    assert out.iloc[1] == pytest.approx(90.0)  # 01-03 uses the trailing 01-02 rate


def test_to_chf_rejects_out_of_range_fx() -> None:
    usd = pd.Series([100.0], index=pd.to_datetime(["2020-01-02"]))
    bad = pd.Series([150.0], index=pd.to_datetime(["2020-01-02"]))  # e.g. a JPY rate
    with pytest.raises(ValueError):
        fx.to_chf(usd, bad)


def test_riskfree_daily_conversion(monkeypatch: pytest.MonkeyPatch) -> None:
    """Percent-p.a. monthly rate -> per-trading-day simple rate, ffilled to calendar."""
    monthly = pd.Series(
        [2.52, 2.52],
        index=pd.to_datetime(["2020-01-01", "2020-02-01"]),
        name="rf",
    )
    monkeypatch.setattr(sources, "fetch_fred_series", lambda *a, **k: monthly)
    calendar = pd.DatetimeIndex(pd.bdate_range("2020-01-01", "2020-01-10"))
    daily = fx.load_chf_riskfree_daily(START, SNAPSHOT, calendar)
    expected = 2.52 / 100.0 / TRADING_DAYS_PER_YEAR
    assert daily.dropna().iloc[0] == pytest.approx(expected)
    # ffilled across the calendar (step function), no NaN after the first obs.
    assert daily.notna().all()
