"""Parquet store for raw pulls and cleaned, calendar-aligned series.

Raw fetches are cached under ``data/raw/`` (so reruns need not re-hit the
network) and cleaned per-track series are written under ``data/processed/`` as
``{instrument}__{track}.parquet``. Both directories are gitignored.

Series are persisted as a one-column ``DataFrame`` (column ``"value"``, index
name ``"date"``) and reloaded back to a Series, since Parquet needs a frame.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import pandas as pd

from quant_backtest.config.parameters import SPLICE_DATE
from quant_backtest.config.paths import PROCESSED_DIR, RAW_DIR

Track = Literal["proxy", "real", "spliced"]
_VALUE_COL = "value"
_INDEX_NAME = "date"


def _raw_path(key: str) -> Path:
    """Path of the raw cache for ``key`` (e.g. a ticker or FRED id)."""
    return RAW_DIR / f"{_sanitize(key)}.parquet"


def _processed_path(instrument: str, track: str) -> Path:
    """Path of the cleaned series for ``instrument`` on ``track``."""
    return PROCESSED_DIR / f"{instrument}__{track}.parquet"


def _sanitize(key: str) -> str:
    """Make a source key safe as a filename (e.g. ``^GSPC`` -> ``_GSPC``)."""
    return "".join(c if (c.isalnum() or c in "-_.") else "_" for c in key)


def _to_frame(series: pd.Series) -> pd.DataFrame:
    """Wrap a Series as the canonical single-column frame for Parquet."""
    frame = series.rename(_VALUE_COL).to_frame()
    frame.index.name = _INDEX_NAME
    return frame


def _read_series(path: Path, name: str) -> pd.Series:
    """Read a single-column Parquet frame back into a named Series."""
    if not path.exists():
        raise FileNotFoundError(f"No processed data at {path}")
    frame = pd.read_parquet(path)
    series = frame[_VALUE_COL]
    series.index = pd.to_datetime(series.index)
    series.index.name = _INDEX_NAME
    series.name = name
    return series


def write_raw(key: str, frame: pd.DataFrame | pd.Series) -> Path:
    """Cache a raw pull under ``data/raw/``.

    Args:
        key: Source key (ticker / FRED id / dataset name).
        frame: Raw data to cache; a Series is wrapped to a frame.

    Returns:
        The path written.
    """
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    path = _raw_path(key)
    payload = _to_frame(frame) if isinstance(frame, pd.Series) else frame.copy()
    payload.index.name = _INDEX_NAME
    payload.to_parquet(path, engine="pyarrow")
    return path


def read_raw(key: str) -> pd.DataFrame:
    """Read a cached raw pull, or raise if it is absent."""
    path = _raw_path(key)
    if not path.exists():
        raise FileNotFoundError(f"No raw cache at {path}")
    return pd.read_parquet(path)


def has_raw(key: str) -> bool:
    """Whether a raw cache exists for ``key``."""
    return _raw_path(key).exists()


def write_processed(instrument: str, track: str, series: pd.Series) -> Path:
    """Write a cleaned per-track series to ``data/processed/``.

    Args:
        instrument: Canonical instrument name.
        track: ``"proxy"`` or ``"real"``.
        series: Cleaned, calendar-aligned series to persist.

    Returns:
        The path written.
    """
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    path = _processed_path(instrument, track)
    _to_frame(series).to_parquet(path, engine="pyarrow")
    return path


def load(instrument: str, track: Track = "spliced") -> pd.Series:
    """Load a cleaned CHF series for ``instrument`` on the requested track.

    ``"proxy"`` and ``"real"`` read the stored single-track files. ``"spliced"``
    concatenates the proxy (strictly BEFORE ``SPLICE_DATE``) with the real series
    (ON/AFTER it) into one continuous, leak-free series; if no proxy exists, it
    returns the real series alone.

    Args:
        instrument: Canonical instrument name (e.g. ``"MTUM"``).
        track: ``"proxy"``, ``"real"``, or ``"spliced"`` (default).

    Returns:
        The requested series, named ``instrument``.

    Raises:
        ValueError: If ``track`` is not recognised.
        FileNotFoundError: If the required processed file is missing.
    """
    if track in ("proxy", "real"):
        return _read_series(_processed_path(instrument, track), instrument)
    if track == "spliced":
        return _load_spliced(instrument)
    raise ValueError(f"Unknown track {track!r}; expected proxy/real/spliced")


def _load_spliced(instrument: str) -> pd.Series:
    """Concatenate proxy (<SPLICE_DATE) and real (>=SPLICE_DATE) with no leak."""
    splice = pd.Timestamp(SPLICE_DATE)
    real = _read_series(_processed_path(instrument, "real"), instrument)
    proxy_path = _processed_path(instrument, "proxy")
    if not proxy_path.exists():  # NONE-proxy instruments: real series is all we have
        return real
    proxy = _read_series(proxy_path, instrument)
    proxy = proxy[proxy.index < splice]
    real = real[real.index >= splice]
    spliced = pd.concat([proxy, real]).sort_index()
    if not spliced.index.is_unique:
        raise ValueError(
            f"Spliced index for {instrument!r} has overlapping dates at the boundary"
        )
    spliced.name = instrument
    return spliced
