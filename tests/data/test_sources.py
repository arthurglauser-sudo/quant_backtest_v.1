"""Source parsing/unit tests with all network access mocked."""

from __future__ import annotations

import io
import zipfile
from datetime import date

import pandas as pd
import pytest

from quant_backtest.data import sources

START = date(1998, 1, 1)
SNAPSHOT = date(2026, 6, 1)

_FRENCH_CSV = """\
This file was created by CMPT_ME ... copyright text

,Mom
20000103,  1.00
20000104, -1.00
20000105,-99.99

  Copyright 2024 Kenneth R. French
"""


def _french_zip(csv_text: str, inner_name: str = "F-F_Momentum_Factor_daily.CSV") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(inner_name, csv_text)
    return buffer.getvalue()


def test_parse_french_returns_units_and_sentinels() -> None:
    series = sources._parse_french_returns(_FRENCH_CSV, "Mom")
    assert list(series.index) == list(pd.to_datetime(["2000-01-03", "2000-01-04", "2000-01-05"]))
    assert series.iloc[0] == pytest.approx(1.00)  # still in PERCENT here
    assert series.iloc[1] == pytest.approx(-1.00)
    assert pd.isna(series.iloc[2])  # -99.99 sentinel -> NaN


def test_french_percent_to_index(monkeypatch: pytest.MonkeyPatch) -> None:
    """Percent factor returns compound to a base-100 total-return index."""
    monkeypatch.setattr(sources, "_http_get_bytes", lambda url: _french_zip(_FRENCH_CSV))
    idx = sources.fetch_french_factor_index(
        "F-F_Momentum_Factor_daily", "Mom", START, SNAPSHOT
    )
    assert idx.iloc[0] == pytest.approx(101.0)  # 100 * (1 + 0.01)
    assert idx.iloc[1] == pytest.approx(101.0 * 0.99)  # then -1%
    assert idx.index.name == "date"


def test_fetch_fred_series_handles_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    csv = "observation_date,DTB3\n2000-01-03,5.00\n2000-01-04,.\n2000-01-05,5.10\n"
    monkeypatch.setattr(sources, "_http_get_bytes", lambda url: csv.encode())
    series = sources.fetch_fred_series("DTB3", START, SNAPSHOT)
    assert series.iloc[0] == pytest.approx(5.00)
    assert pd.isna(series.iloc[1])  # "." -> NaN
    assert series.name == "DTB3"
    assert series.index.name == "date"


def test_fetch_fred_clips_to_window(monkeypatch: pytest.MonkeyPatch) -> None:
    csv = "observation_date,X\n1990-01-02,1.0\n2000-01-03,2.0\n2030-01-03,3.0\n"
    monkeypatch.setattr(sources, "_http_get_bytes", lambda url: csv.encode())
    series = sources.fetch_fred_series("X", START, SNAPSHOT)
    # Pre-START and post-SNAPSHOT rows are clipped out.
    assert series.index.min() >= pd.Timestamp(START)
    assert series.index.max() < pd.Timestamp(SNAPSHOT)


def test_fetch_yfinance_series_takes_adjusted_close(monkeypatch: pytest.MonkeyPatch) -> None:
    frame = pd.DataFrame(
        {"Close": [10.0, 11.0], "Volume": [1, 2]},
        index=pd.to_datetime(["2020-01-02", "2020-01-03"]),
    )
    monkeypatch.setattr(sources.yf, "download", lambda *a, **k: frame)
    series = sources.fetch_yfinance_series("MTUM", START, SNAPSHOT)
    assert list(series) == [10.0, 11.0]
    assert series.name == "MTUM"
    assert series.index.name == "date"


def test_fetch_yfinance_empty_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sources.yf, "download", lambda *a, **k: pd.DataFrame())
    with pytest.raises(ValueError):
        sources.fetch_yfinance_series("MTUM", START, SNAPSHOT)
