"""Deterministic dataset rebuild (entry point).

``uv run python -m quant_backtest.data.ingest`` rebuilds the entire local
dataset from the pinned ``SNAPSHOT_DATE``: it pulls each source (caching raw
pulls under ``data/raw/``), reindexes everything onto the ^GSPC master trading
calendar, converts USD series to CHF, quality-checks each series, and writes
cleaned per-track Parquet under ``data/processed/``.

Determinism: every fetch is bounded by ``[START_DATE, SNAPSHOT_DATE)`` and raw
pulls are reused on rerun unless ``--refresh`` is passed.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable

import pandas as pd

from quant_backtest.config.parameters import (
    BENCHMARK_NAME,
    BENCHMARK_TICKER,
    CALENDAR_TICKER,
    CHF_RF_NAME,
    CRYPTO_SPLIT_JUMP_LOG_THRESHOLD,
    PRICE_FFILL_LIMIT,
    SNAPSHOT_DATE,
    SPLICE_DATE,
    SPLIT_JUMP_LOG_THRESHOLD,
    START_DATE,
    TRADING_DAYS_PER_YEAR,
)
from quant_backtest.config.paths import ensure_dirs
from quant_backtest.config.universe import UNIVERSE, Instrument, ProxySource
from quant_backtest.data import fx, quality, sources, store

# ---------------------------------------------------------------------------
# Raw-cache-aware fetchers
# ---------------------------------------------------------------------------


def _load_or_fetch(
    key: str, fetch_fn: Callable[[], pd.Series], *, refresh: bool
) -> pd.Series:
    """Return a cached raw pull for ``key`` or fetch and cache it.

    Args:
        key: Raw-cache key (ticker / FRED id / dataset name).
        fetch_fn: Zero-arg callable that performs the actual network fetch.
        refresh: If ``True``, bypass the cache and re-fetch.

    Returns:
        The fetched/cached series (named ``key``).
    """
    if not refresh and store.has_raw(key):
        frame = store.read_raw(key)
        series = frame[frame.columns[0]]
        series.index = pd.to_datetime(series.index)
        return series.rename(key)
    series = fetch_fn()
    store.write_raw(key, series)
    return series


# ---------------------------------------------------------------------------
# Alignment helper (calendar reindex + bounded trailing ffill)
# ---------------------------------------------------------------------------


def _align(series: pd.Series, target: pd.DatetimeIndex, *, is_price: bool) -> pd.Series:
    """Reindex ``series`` onto ``target`` (clipped to its span) with ffill.

    The target window is first clipped to the series' own ``[min, max]`` so no
    leading/trailing NaN is fabricated outside the data's coverage. Prices use a
    bounded trailing ffill (small source gaps only); step-like series use an
    unbounded trailing ffill. Forward-fill never looks ahead.

    Args:
        series: Source series (any frequency).
        target: Calendar window to align onto.
        is_price: Whether to bound the ffill (prices) or not (step series).

    Returns:
        The series reindexed onto the (clipped) target window.
    """
    clean = series[~series.index.duplicated(keep="last")].sort_index()
    if clean.empty:
        return clean
    lo = max(target.min(), clean.index.min())
    hi = min(target.max(), clean.index.max())
    window = target[(target >= lo) & (target <= hi)]
    aligned = clean.reindex(window)
    return aligned.ffill(limit=PRICE_FFILL_LIMIT) if is_price else aligned.ffill()


# ---------------------------------------------------------------------------
# Proxy-track construction
# ---------------------------------------------------------------------------


def _build_proxy_raw(inst: Instrument, *, refresh: bool) -> pd.Series:
    """Fetch the raw (un-aligned, USD) proxy level series for ``inst``.

    Returns a price/level series for every proxy source; FX conversion and
    calendar alignment happen in the caller.
    """
    source = inst.proxy
    if source in (ProxySource.YFINANCE, ProxySource.SELF):
        ticker = inst.proxy_ref if source is ProxySource.YFINANCE else inst.ticker
        return _load_or_fetch(
            ticker,
            lambda: sources.fetch_yfinance_series(ticker, START_DATE, SPLICE_DATE),
            refresh=refresh,
        )
    if source in (ProxySource.FRENCH_UMD, ProxySource.FRENCH_HML):
        dataset, column = inst.proxy_ref, inst.proxy_column
        return _load_or_fetch(
            dataset,
            lambda: sources.fetch_french_factor_index(
                dataset, column, START_DATE, SPLICE_DATE
            ),
            refresh=refresh,
        )
    if source is ProxySource.FRED_GOLD:
        return _load_or_fetch(
            inst.proxy_ref,
            lambda: sources.fetch_fred_series(inst.proxy_ref, START_DATE, SPLICE_DATE),
            refresh=refresh,
        )
    if source is ProxySource.FRED_BILL:
        rate = _load_or_fetch(
            inst.proxy_ref,
            lambda: sources.fetch_fred_series(inst.proxy_ref, START_DATE, SPLICE_DATE),
            refresh=refresh,
        )
        return _tbill_index_from_rate(rate)
    raise ValueError(f"Unsupported proxy source {source!r} for {inst.name!r}")


def _tbill_index_from_rate(rate_pct: pd.Series) -> pd.Series:
    """Compound a percent-p.a. T-bill rate into a base-100 total-return index."""
    daily_growth = 1.0 + rate_pct.ffill() / 100.0 / TRADING_DAYS_PER_YEAR
    return daily_growth.cumprod() * 100.0


# ---------------------------------------------------------------------------
# Per-instrument ingestion
# ---------------------------------------------------------------------------


def _jump_threshold(name: str) -> float:
    """Split-jump threshold, loosened for genuinely volatile crypto."""
    return CRYPTO_SPLIT_JUMP_LOG_THRESHOLD if name == "BTC" else SPLIT_JUMP_LOG_THRESHOLD


def _ingest_instrument(
    inst: Instrument,
    calendar: pd.DatetimeIndex,
    usdchf: pd.Series,
    *,
    refresh: bool,
) -> list[dict[str, object]]:
    """Build, check, and write the real (and proxy) tracks for one instrument.

    Returns:
        One summary-row dict per track written.
    """
    rows: list[dict[str, object]] = []
    splice = pd.Timestamp(SPLICE_DATE)
    threshold = _jump_threshold(inst.name)

    # --- Real (execution) track --------------------------------------------
    real_raw = _load_or_fetch(
        inst.ticker,
        lambda: sources.fetch_yfinance_series(inst.ticker, START_DATE, SNAPSHOT_DATE),
        refresh=refresh,
    )
    real_window = calendar[
        (calendar >= max(pd.Timestamp(START_DATE), pd.Timestamp(inst.inception)))
    ]
    real = _align(real_raw, real_window, is_price=True)
    if inst.is_usd:
        real = to_chf_named(real, usdchf, inst.name)
    real.name = inst.name
    quality.check_series(real, calendar, name=f"{inst.name}:real", split_jump_log_threshold=threshold)
    store.write_processed(inst.name, "real", real)
    rows.append(_summary_row(inst.name, "real", real))

    # --- Proxy (logic) track -----------------------------------------------
    if inst.has_proxy():
        proxy_raw = _build_proxy_raw(inst, refresh=refresh)
        proxy_window = calendar[(calendar >= pd.Timestamp(START_DATE)) & (calendar < splice)]
        proxy = _align(proxy_raw, proxy_window, is_price=True)
        if inst.proxy_needs_fx():
            proxy = to_chf_named(proxy, usdchf, inst.name)
        proxy.name = inst.name
        quality.check_series(
            proxy, calendar, name=f"{inst.name}:proxy", split_jump_log_threshold=threshold
        )
        store.write_processed(inst.name, "proxy", proxy)
        rows.append(_summary_row(inst.name, "proxy", proxy))

    return rows


def to_chf_named(series: pd.Series, usdchf: pd.Series, name: str) -> pd.Series:
    """USD->CHF conversion preserving the instrument name."""
    converted = fx.to_chf(series.rename(name), usdchf)
    converted.name = name
    return converted


# ---------------------------------------------------------------------------
# Benchmark & risk-free
# ---------------------------------------------------------------------------


def _ingest_benchmark(
    calendar: pd.DatetimeIndex, usdchf: pd.Series, *, refresh: bool
) -> list[dict[str, object]]:
    """Ingest SPY adjusted close as the CHF total-return benchmark (SPX_TR)."""
    raw = _load_or_fetch(
        BENCHMARK_TICKER,
        lambda: sources.fetch_yfinance_series(BENCHMARK_TICKER, START_DATE, SNAPSHOT_DATE),
        refresh=refresh,
    )
    splice = pd.Timestamp(SPLICE_DATE)
    rows: list[dict[str, object]] = []

    real_window = calendar[calendar >= pd.Timestamp(START_DATE)]
    real = to_chf_named(_align(raw, real_window, is_price=True), usdchf, BENCHMARK_NAME)
    quality.check_series(real, calendar, name=f"{BENCHMARK_NAME}:real")
    store.write_processed(BENCHMARK_NAME, "real", real)
    rows.append(_summary_row(BENCHMARK_NAME, "real", real))

    proxy_window = calendar[(calendar >= pd.Timestamp(START_DATE)) & (calendar < splice)]
    proxy = to_chf_named(_align(raw, proxy_window, is_price=True), usdchf, BENCHMARK_NAME)
    quality.check_series(proxy, calendar, name=f"{BENCHMARK_NAME}:proxy")
    store.write_processed(BENCHMARK_NAME, "proxy", proxy)
    rows.append(_summary_row(BENCHMARK_NAME, "proxy", proxy))
    return rows


def _ingest_riskfree(calendar: pd.DatetimeIndex) -> list[dict[str, object]]:
    """Ingest the daily CHF risk-free rate (already CHF; no FX, no jump check)."""
    rf = fx.load_chf_riskfree_daily(START_DATE, SNAPSHOT_DATE, calendar).dropna()
    rf.name = CHF_RF_NAME
    # A rate is not a price: it can be negative (Swiss rates were) and has no
    # split jumps, so disable the jump check (inf threshold) but keep the rest.
    quality.check_series(
        rf, calendar, name=f"{CHF_RF_NAME}:real", split_jump_log_threshold=float("inf")
    )
    store.write_processed(CHF_RF_NAME, "real", rf)
    return [_summary_row(CHF_RF_NAME, "real", rf)]


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def _summary_row(name: str, track: str, series: pd.Series) -> dict[str, object]:
    """Build a one-line summary record for the final report table."""
    return {
        "instrument": name,
        "track": track,
        "first": None if series.empty else series.index.min().date(),
        "last": None if series.empty else series.index.max().date(),
        "n_obs": int(len(series)),
    }


def _print_summary(rows: list[dict[str, object]]) -> None:
    """Print the ingestion summary table to stdout."""
    header = f"{'instrument':<12}{'track':<10}{'first':<12}{'last':<12}{'n_obs':>8}"
    print("\n" + header)
    print("-" * len(header))
    for row in rows:
        print(
            f"{row['instrument']!s:<12}{row['track']!s:<10}"
            f"{row['first']!s:<12}{row['last']!s:<12}{row['n_obs']!s:>8}"
        )
    print(f"\n{len(rows)} series written to data/processed/.")


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def _build_master_calendar(*, refresh: bool) -> pd.DatetimeIndex:
    """Master NYSE trading calendar from ^GSPC, clipped to [START, SNAPSHOT)."""
    gspc = _load_or_fetch(
        CALENDAR_TICKER,
        lambda: sources.fetch_yfinance_series(CALENDAR_TICKER, START_DATE, SNAPSHOT_DATE),
        refresh=refresh,
    )
    index = pd.DatetimeIndex(gspc.index)
    lo, hi = pd.Timestamp(START_DATE), pd.Timestamp(SNAPSHOT_DATE)
    return index[(index >= lo) & (index < hi)].sort_values().unique()


def run(*, refresh: bool = False) -> int:
    """Rebuild the entire dataset deterministically.

    Args:
        refresh: If ``True``, bypass the raw cache and re-fetch every source.

    Returns:
        Process exit code (0 on success).
    """
    ensure_dirs()
    calendar = _build_master_calendar(refresh=refresh)
    usdchf = fx.load_usdchf(START_DATE, SNAPSHOT_DATE, calendar)

    rows: list[dict[str, object]] = []
    for inst in UNIVERSE:
        rows.extend(_ingest_instrument(inst, calendar, usdchf, refresh=refresh))
    rows.extend(_ingest_benchmark(calendar, usdchf, refresh=refresh))
    rows.extend(_ingest_riskfree(calendar))

    _print_summary(rows)
    return 0


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Rebuild the quant-backtest dataset.")
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Bypass the data/raw cache and re-fetch every source.",
    )
    args = parser.parse_args()
    return run(refresh=args.refresh)


if __name__ == "__main__":
    raise SystemExit(main())
