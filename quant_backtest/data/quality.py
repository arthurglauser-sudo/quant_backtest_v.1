"""Loud data-quality checks for cleaned series.

``check_series`` validates a cleaned, calendar-aligned series and RAISES
``QualityError`` (with a printable report) on any defect: duplicate dates, NaNs,
calendar misalignment (dates outside the master calendar), missing sessions
within the covered span, or an unadjusted-split / data-error price jump. A
silent data bug here poisons every downstream phase, so failure is never
swallowed (CLAUDE.md §7).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from quant_backtest.config.parameters import SPLIT_JUMP_LOG_THRESHOLD


class QualityError(Exception):
    """Raised when a series fails one or more quality checks."""


@dataclass
class QualityReport:
    """Outcome of :func:`check_series`.

    Attributes:
        name: Series name under check.
        n_obs: Number of observations.
        first: First index timestamp (or ``None`` if empty).
        last: Last index timestamp (or ``None`` if empty).
        n_missing_sessions: Calendar sessions within ``[first, last]`` absent
            from the index.
        n_duplicates: Duplicate index entries.
        n_nans: NaN values.
        n_off_calendar: Index dates not present in the master calendar.
        max_abs_log_jump: Largest absolute daily log return observed.
        ok: Whether all checks passed.
        messages: Human-readable description of each failure.
    """

    name: str
    n_obs: int
    first: pd.Timestamp | None
    last: pd.Timestamp | None
    n_missing_sessions: int
    n_duplicates: int
    n_nans: int
    n_off_calendar: int
    max_abs_log_jump: float
    ok: bool
    messages: list[str] = field(default_factory=list)


def render(report: QualityReport) -> str:
    """Render a :class:`QualityReport` as a multi-line, printable string."""
    status = "OK" if report.ok else "FAIL"
    lines = [
        f"[{status}] quality report for {report.name!r}",
        f"  observations : {report.n_obs}",
        f"  span         : {report.first} -> {report.last}",
        f"  duplicates   : {report.n_duplicates}",
        f"  NaNs         : {report.n_nans}",
        f"  off-calendar : {report.n_off_calendar}",
        f"  missing sess : {report.n_missing_sessions}",
        f"  max |log ret|: {report.max_abs_log_jump:.4f}",
    ]
    lines.extend(f"  - {msg}" for msg in report.messages)
    return "\n".join(lines)


def check_series(
    series: pd.Series,
    calendar: pd.DatetimeIndex,
    *,
    name: str | None = None,
    split_jump_log_threshold: float = SPLIT_JUMP_LOG_THRESHOLD,
    raise_on_fail: bool = True,
) -> QualityReport:
    """Validate a cleaned series against the master calendar.

    Args:
        series: Cleaned, calendar-aligned series to check.
        calendar: Master trading calendar (superset of valid dates).
        name: Override for the report name (defaults to ``series.name``).
        split_jump_log_threshold: ``|log return|`` above this flags a jump.
        raise_on_fail: If ``True`` (default), raise :class:`QualityError` with
            the rendered report when any check fails.

    Returns:
        The :class:`QualityReport` (also returned on success).

    Raises:
        QualityError: If a check fails and ``raise_on_fail`` is ``True``.
    """
    name = name or (str(series.name) if series.name is not None else "series")
    index = pd.DatetimeIndex(series.index)
    cal = pd.DatetimeIndex(calendar)
    messages: list[str] = []

    n_duplicates = int(index.duplicated().sum())
    if n_duplicates:
        messages.append(f"{n_duplicates} duplicate date(s) in index")

    n_nans = int(series.isna().sum())
    if n_nans:
        messages.append(f"{n_nans} NaN value(s)")

    off_calendar = index.difference(cal)
    n_off_calendar = len(off_calendar)
    if n_off_calendar:
        sample = list(off_calendar[:3].strftime("%Y-%m-%d"))
        messages.append(f"{n_off_calendar} date(s) not on master calendar, e.g. {sample}")

    n_missing_sessions = 0
    first = last = None
    if len(index):
        first, last = index.min(), index.max()
        span = cal[(cal >= first) & (cal <= last)]
        missing = span.difference(index)
        n_missing_sessions = len(missing)
        if n_missing_sessions:
            sample = list(missing[:3].strftime("%Y-%m-%d"))
            messages.append(
                f"{n_missing_sessions} missing session(s) within span, e.g. {sample}"
            )

    max_abs_log_jump = _max_abs_log_jump(series)
    if max_abs_log_jump > split_jump_log_threshold:
        messages.append(
            f"max |log return| {max_abs_log_jump:.4f} exceeds "
            f"{split_jump_log_threshold} (possible unadjusted split / data error)"
        )

    ok = not messages
    report = QualityReport(
        name=name,
        n_obs=int(len(series)),
        first=first,
        last=last,
        n_missing_sessions=n_missing_sessions,
        n_duplicates=n_duplicates,
        n_nans=n_nans,
        n_off_calendar=n_off_calendar,
        max_abs_log_jump=max_abs_log_jump,
        ok=ok,
        messages=messages,
    )
    if not ok and raise_on_fail:
        raise QualityError(render(report))
    return report


def _max_abs_log_jump(series: pd.Series) -> float:
    """Largest absolute daily log return over strictly-positive observations."""
    clean = series.dropna()
    positive = clean[clean > 0.0]
    if len(positive) < 2:
        return 0.0
    log_returns = np.log(positive.to_numpy())
    return float(np.abs(np.diff(log_returns)).max())
