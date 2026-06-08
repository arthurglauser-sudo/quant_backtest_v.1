"""GUARDRAIL tests (CLAUDE.md §7): the data layer injects no future data.

Covers the two ways the data layer could leak the future: the proxy/real splice
and calendar alignment. These must never weaken to make a build pass.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from quant_backtest.config.parameters import SPLICE_DATE
from quant_backtest.data import ingest, store


@pytest.fixture(autouse=True)
def _tmp_store(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(store, "PROCESSED_DIR", tmp_path / "processed")
    monkeypatch.setattr(store, "RAW_DIR", tmp_path / "raw")


def test_splice_has_no_future_leak() -> None:
    """Proxy strictly before splice, real on/after; no overlap, monotonic index."""
    splice = pd.Timestamp(SPLICE_DATE)
    dates = pd.bdate_range(splice - pd.Timedelta(days=10), splice + pd.Timedelta(days=10))
    # Proxy and real disagree everywhere so any boundary leak is detectable.
    proxy = pd.Series(1.0, index=dates, name="MTUM")
    real = pd.Series(2.0, index=dates, name="MTUM")
    store.write_processed("MTUM", "proxy", proxy)
    store.write_processed("MTUM", "real", real)

    spliced = store.load("MTUM", "spliced")
    assert spliced.index.is_monotonic_increasing
    assert spliced.index.is_unique
    # Proxy value (1.0) appears only strictly before the splice; real (2.0) on/after.
    assert (spliced[spliced.index < splice] == 1.0).all()
    assert (spliced[spliced.index >= splice] == 2.0).all()
    # No real data leaked into the proxy era and vice versa.
    assert spliced[spliced.index < splice].index.max() < splice


def test_alignment_uses_trailing_ffill_only() -> None:
    """A gap is filled from the PAST (ffill), never back-filled from the future."""
    target = pd.DatetimeIndex(pd.bdate_range("2020-01-01", "2020-01-09"))
    # Source has 2020-01-01 then a gap until 2020-01-06.
    series = pd.Series(
        [10.0, 12.0],
        index=pd.to_datetime(["2020-01-01", "2020-01-06"]),
        name="X",
    )
    aligned = ingest._align(series, target, is_price=True)
    # Days between are carried forward at 10.0 (the last KNOWN value), not 12.0.
    assert aligned.loc[pd.Timestamp("2020-01-02")] == 10.0
    assert aligned.loc[pd.Timestamp("2020-01-03")] == 10.0
    # The future value 12.0 never appears before its own date.
    assert (aligned[aligned.index < pd.Timestamp("2020-01-06")] == 10.0).all()


def test_alignment_does_not_fabricate_leading_data() -> None:
    """Target dates before the first observation are dropped, never back-filled."""
    target = pd.DatetimeIndex(pd.bdate_range("2020-01-01", "2020-01-09"))
    series = pd.Series([10.0], index=pd.to_datetime(["2020-01-06"]), name="X")
    aligned = ingest._align(series, target, is_price=True)
    assert aligned.index.min() == pd.Timestamp("2020-01-06")
    assert aligned.notna().all()


def test_bounded_ffill_leaves_long_gap_as_nan() -> None:
    """Beyond the bounded ffill limit a price gap stays NaN (surfaces in quality)."""
    target = pd.DatetimeIndex(pd.bdate_range("2020-01-01", "2020-01-31"))
    series = pd.Series(
        [10.0, 12.0],
        index=pd.to_datetime(["2020-01-01", "2020-01-31"]),
        name="X",
    )
    aligned = ingest._align(series, target, is_price=True)
    assert aligned.isna().any()  # gap far exceeds PRICE_FFILL_LIMIT
