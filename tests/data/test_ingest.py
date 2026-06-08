"""End-to-end ingestion orchestration with all sources mocked (no network).

Runs the full ``ingest.run()`` pipeline against deterministic synthetic sources
to validate the wiring Level-3 exercises -- calendar alignment, USD->CHF,
quality checks, Parquet persistence, and the proxy/real splice -- without
touching the network.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from quant_backtest.config.parameters import (
    BENCHMARK_NAME,
    CHF_RF_FRED_ID,
    CHF_RF_NAME,
    SPLICE_DATE,
)
from quant_backtest.data import fx, ingest, sources, store


def _fake_yf(ticker: str, start: date, end: date) -> pd.Series:
    idx = pd.bdate_range(start, end, inclusive="left")
    idx.name = "date"
    if ticker == "CHF=X":  # USD/CHF in plausible range
        series = pd.Series(0.92, index=idx)
    else:  # smooth ramp -> no split-jump flags
        series = pd.Series(np.linspace(100.0, 180.0, len(idx)), index=idx)
    series.name = ticker
    return series.astype(float)


def _fake_fred(series_id: str, start: date, end: date) -> pd.Series:
    idx = pd.bdate_range(start, end, inclusive="left")
    idx.name = "date"
    value = 1.0 if series_id == CHF_RF_FRED_ID else 1500.0  # rate% vs gold USD/oz
    series = pd.Series(value, index=idx, name=series_id)
    return series.astype(float)


def _fake_french(dataset: str, column: str, start: date, end: date) -> pd.Series:
    idx = pd.bdate_range(start, end, inclusive="left")
    idx.name = "date"
    series = pd.Series(np.linspace(100.0, 140.0, len(idx)), index=idx, name=column)
    return series.astype(float)


@pytest.fixture
def _mocked(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(store, "PROCESSED_DIR", tmp_path / "processed")
    monkeypatch.setattr(store, "RAW_DIR", tmp_path / "raw")
    monkeypatch.setattr(sources, "fetch_yfinance_series", _fake_yf)
    monkeypatch.setattr(sources, "fetch_fred_series", _fake_fred)
    monkeypatch.setattr(sources, "fetch_french_factor_index", _fake_french)
    # fx imports sources by reference, so patching sources.* is enough.


def test_full_ingest_writes_and_loads(_mocked: None) -> None:
    assert ingest.run(refresh=True) == 0

    # A factor-proxy instrument: spliced series is continuous and CHF-clean.
    spliced = store.load("MTUM", "spliced")
    assert not spliced.isna().any()
    assert spliced.index.is_monotonic_increasing
    assert spliced.index.is_unique
    splice = pd.Timestamp(SPLICE_DATE)
    assert (spliced.index < splice).any() and (spliced.index >= splice).any()

    # Benchmark and risk-free were produced.
    assert not store.load(BENCHMARK_NAME, "real").empty
    assert not store.load(CHF_RF_NAME, "real").empty

    # NONE-proxy instrument has only a real track; spliced falls back to it.
    btc_real = store.load("BTC", "real")
    assert btc_real.index.min() >= pd.Timestamp(date(2014, 9, 17))
    pd.testing.assert_series_equal(
        store.load("BTC", "spliced"), btc_real, check_freq=False
    )


def test_factor_proxy_not_fx_converted(_mocked: None) -> None:
    """French factor proxy is left unconverted; a USD ETF real track is CHF."""
    ingest.run(refresh=True)
    # MTUM proxy = synthetic factor index (ramps from 100); FX (0.92) would scale it.
    proxy = store.load("MTUM", "proxy")
    assert proxy.iloc[0] == pytest.approx(100.0, abs=1.0)
    # SPY real spans from START, so its first ramp value (100) is FX-scaled to ~92.
    spy_real = store.load("SPY", "real")
    assert spy_real.iloc[0] == pytest.approx(100.0 * 0.92, abs=1.0)


def test_usdchf_alignment_is_in_range(_mocked: None) -> None:
    """Smoke: USD->CHF conversion never trips the FX-direction guard."""
    cal = pd.DatetimeIndex(pd.bdate_range("1998-01-01", "1998-02-01"))
    usdchf = fx.load_usdchf(date(1998, 1, 1), date(1998, 2, 1), cal)
    assert usdchf.between(0.5, 1.5).all()
