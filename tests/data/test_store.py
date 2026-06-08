"""Parquet round-trip and track selection (splice)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from quant_backtest.config.parameters import SPLICE_DATE
from quant_backtest.data import store


@pytest.fixture(autouse=True)
def _tmp_store(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Redirect raw/processed dirs to a tmp path so tests never touch data/."""
    monkeypatch.setattr(store, "PROCESSED_DIR", tmp_path / "processed")
    monkeypatch.setattr(store, "RAW_DIR", tmp_path / "raw")


def _series(dates: list[str], values: list[float], name: str = "X") -> pd.Series:
    idx = pd.to_datetime(dates)
    idx.name = "date"
    return pd.Series(values, index=idx, name=name)


def test_processed_round_trip() -> None:
    s = _series(["2014-01-02", "2014-01-03"], [1.0, 2.0], "MTUM")
    store.write_processed("MTUM", "real", s)
    loaded = store.load("MTUM", "real")
    pd.testing.assert_series_equal(loaded, s, check_freq=False)
    assert loaded.name == "MTUM"
    assert loaded.index.name == "date"


def test_unknown_track_raises() -> None:
    store.write_processed("MTUM", "real", _series(["2014-01-02"], [1.0], "MTUM"))
    with pytest.raises(ValueError):
        store.load("MTUM", "bogus")  # type: ignore[arg-type]


def test_spliced_concatenates_at_boundary() -> None:
    splice = pd.Timestamp(SPLICE_DATE)
    before = (splice - pd.Timedelta(days=2)).strftime("%Y-%m-%d")
    after = (splice + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    proxy = _series([before, after], [10.0, 99.0], "GLD")  # 'after' must be dropped
    real = _series([before, after], [88.0, 20.0], "GLD")  # 'before' must be dropped
    store.write_processed("GLD", "proxy", proxy)
    store.write_processed("GLD", "real", real)

    spliced = store.load("GLD", "spliced")
    assert spliced.loc[pd.Timestamp(before)] == 10.0  # from proxy
    assert spliced.loc[pd.Timestamp(after)] == 20.0  # from real
    assert spliced.index.is_monotonic_increasing
    assert spliced.index.is_unique


def test_spliced_without_proxy_returns_real() -> None:
    real = _series(["2015-01-02", "2015-01-05"], [1.0, 2.0], "BTC")
    store.write_processed("BTC", "real", real)
    pd.testing.assert_series_equal(store.load("BTC", "spliced"), real, check_freq=False)


def test_raw_cache_round_trip() -> None:
    s = _series(["2014-01-02"], [1.0], "value")
    store.write_raw("^GSPC", s)
    assert store.has_raw("^GSPC")
    frame = store.read_raw("^GSPC")
    assert frame["value"].iloc[0] == 1.0
