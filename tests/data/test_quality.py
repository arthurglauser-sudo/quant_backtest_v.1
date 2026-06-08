"""Each quality check fires and raises QualityError loudly."""

from __future__ import annotations

import pandas as pd
import pytest

from quant_backtest.data import quality

CAL = pd.DatetimeIndex(pd.bdate_range("2020-01-01", "2020-01-31"))


def _clean() -> pd.Series:
    """A clean series aligned to the first five calendar sessions."""
    idx = CAL[:5]
    return pd.Series([100.0, 101.0, 100.5, 102.0, 101.5], index=idx, name="X")


def test_clean_series_passes() -> None:
    report = quality.check_series(_clean(), CAL)
    assert report.ok
    assert report.n_obs == 5
    assert report.messages == []


def test_raises_on_nan() -> None:
    s = pd.Series([1.0, float("nan")], index=CAL[:2], name="X")
    with pytest.raises(quality.QualityError):
        quality.check_series(s, CAL)


def test_raises_on_duplicate() -> None:
    idx = pd.DatetimeIndex([CAL[0], CAL[0]])
    s = pd.Series([1.0, 1.0], index=idx, name="X")
    with pytest.raises(quality.QualityError):
        quality.check_series(s, CAL)


def test_raises_on_off_calendar_date() -> None:
    s = pd.Series([1.0, 2.0], index=pd.to_datetime(["2020-01-04", "2020-01-06"]), name="X")
    # 2020-01-04 is a Saturday -> not on the business-day master calendar.
    with pytest.raises(quality.QualityError):
        quality.check_series(s, CAL)


def test_raises_on_missing_session() -> None:
    # Skip CAL[2] within the span -> a missing session.
    idx = CAL[[0, 1, 3, 4]]
    s = pd.Series([1.0, 2.0, 3.0, 4.0], index=idx, name="X")
    with pytest.raises(quality.QualityError):
        quality.check_series(s, CAL)


def test_raises_on_split_jump() -> None:
    # 100 -> 300 is a |log return| ~1.10, exceeding the default threshold.
    s = pd.Series([100.0, 300.0, 305.0], index=CAL[:3], name="X")
    with pytest.raises(quality.QualityError):
        quality.check_series(s, CAL)


def test_no_raise_when_disabled() -> None:
    s = pd.Series([1.0, float("nan")], index=CAL[:2], name="X")
    report = quality.check_series(s, CAL, raise_on_fail=False)
    assert not report.ok
    assert report.n_nans == 1
