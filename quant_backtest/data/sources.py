"""Raw data sources: yfinance, Ken French Data Library, and FRED.

Each fetcher returns a sorted, de-duplicated, tz-naive pandas Series with a
``DatetimeIndex`` named ``"date"``. No NaN filling or calendar alignment happens
here -- cleaning is the ingestion step's job. Network failures and empty pulls
raise loudly (CLAUDE.md §8: never swallow fetch errors).

Per the PRP reviewer amendment, FRED and Ken French are fetched over direct
HTTP (pandas-datareader is incompatible with the pinned pandas 3.0). The thin
``_http_get_bytes`` indirection is the single network seam the unit tests
monkeypatch, so parsing logic is exercised without touching the network.
"""

from __future__ import annotations

import io
import re
import zipfile
from datetime import date

import pandas as pd
import requests
import yfinance as yf

# Direct-HTTP endpoints (source implementation detail, not strategy params).
_FRED_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
_FRENCH_ZIP_URL = (
    "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/{dataset}_CSV.zip"
)
_HTTP_TIMEOUT_SECONDS = 60
# Ken French missing-data sentinels.
_FRENCH_NA_VALUES = (-99.99, -999.0)
_DATE_ROW = re.compile(r"^\s*\d{8}\s*$")  # 8-digit YYYYMMDD data-row key


def _http_get_bytes(url: str) -> bytes:
    """Fetch a URL and return the raw response body.

    Single network seam for the HTTP-based sources; monkeypatched in tests.

    Args:
        url: Absolute URL to fetch.

    Returns:
        The response body as bytes.

    Raises:
        requests.HTTPError: If the response status is an error.
    """
    response = requests.get(url, timeout=_HTTP_TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.content


def _clean_index(series: pd.Series) -> pd.Series:
    """Return the series with a sorted, de-duplicated, tz-naive date index."""
    series = series.copy()
    index = pd.to_datetime(series.index)
    if index.tz is not None:
        index = index.tz_localize(None)
    series.index = index
    series = series[~series.index.duplicated(keep="last")].sort_index()
    series.index.name = "date"
    return series.astype(float)


def fetch_yfinance_series(ticker: str, start: date, end: date) -> pd.Series:
    """Fetch a single ticker's split/dividend-adjusted daily close.

    One ticker at a time so the result has simple (non-MultiIndex) columns
    regardless of yfinance version. ``auto_adjust=True`` makes ``Close`` the
    adjusted series, so ``Adj Close`` is not used.

    Args:
        ticker: Yahoo Finance symbol (e.g. ``"MTUM"``, ``"^SP500EW"``).
        start: Inclusive start date.
        end: Exclusive end date (Yahoo treats ``end`` as exclusive).

    Returns:
        Adjusted close as a float Series named ``ticker``.

    Raises:
        ValueError: If yfinance returns no data.
    """
    frame = yf.download(
        ticker,
        start=start.isoformat(),
        end=end.isoformat(),
        auto_adjust=True,
        progress=False,
    )
    if frame is None or frame.empty:
        raise ValueError(f"yfinance returned no data for {ticker!r}")
    close = frame["Close"]
    if isinstance(close, pd.DataFrame):  # defensive vs a residual MultiIndex
        close = close.iloc[:, 0]
    series = _clean_index(close)
    series.name = ticker
    return series


def _parse_french_returns(csv_text: str, column: str) -> pd.Series:
    """Parse a Ken French daily CSV into a percent-return Series.

    The data library CSVs carry descriptive header text, then a header row whose
    first field is blank, then ``YYYYMMDD,value,...`` rows, then a footer. This
    locates the header row by its named column and collects subsequent date
    rows until the first non-date line.

    Args:
        csv_text: Decoded CSV contents from the dataset ZIP.
        column: Factor column to extract (e.g. ``"Mom"``, ``"HML"``).

    Returns:
        Percent factor returns indexed by date (sentinels -> NaN).

    Raises:
        ValueError: If the column or any data rows cannot be found.
    """
    lines = csv_text.splitlines()
    header_idx: int | None = None
    col_pos: int | None = None
    for i, line in enumerate(lines):
        fields = [f.strip() for f in line.split(",")]
        if column in fields[1:]:  # fields[0] is the blank date column
            header_idx = i
            col_pos = fields.index(column)
            break
    if header_idx is None or col_pos is None:
        raise ValueError(f"Column {column!r} not found in Ken French CSV")

    dates: list[str] = []
    values: list[float] = []
    for line in lines[header_idx + 1 :]:
        fields = [f.strip() for f in line.split(",")]
        if not _DATE_ROW.match(fields[0]):
            if dates:  # reached the footer / next section after the daily block
                break
            continue
        dates.append(fields[0])
        values.append(float(fields[col_pos]))
    if not dates:
        raise ValueError(f"No daily rows parsed for column {column!r}")

    series = pd.Series(values, index=pd.to_datetime(dates, format="%Y%m%d"))
    series = series.replace(list(_FRENCH_NA_VALUES), float("nan")).astype(float)
    series.index.name = "date"
    return series


def fetch_french_factor_index(
    dataset: str, column: str, start: date, end: date
) -> pd.Series:
    """Build a base-100 total-return index from a Ken French daily factor.

    Ken French factor returns are LONG-SHORT and in PERCENT (``0.53`` == 0.53%).
    They are converted to fractions and compounded into a synthetic total-return
    index. The result is a factor-return *index*, not a tradeable price -- it is
    only used on the 1998->splice logic-test track.

    Args:
        dataset: Data-library dataset name (e.g. ``"F-F_Momentum_Factor_daily"``).
        column: Factor column to extract (e.g. ``"Mom"``).
        start: Inclusive start date (index is clipped to ``[start, end)``).
        end: Exclusive end date.

    Returns:
        Base-100 cumulative total-return index as a float Series named ``column``.

    Raises:
        ValueError: If the ZIP holds no CSV or the column is missing.
    """
    url = _FRENCH_ZIP_URL.format(dataset=dataset)
    content = _http_get_bytes(url)
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        csv_names = [n for n in archive.namelist() if n.lower().endswith(".csv")]
        if not csv_names:
            raise ValueError(f"No CSV inside Ken French ZIP for {dataset!r}")
        csv_text = archive.read(csv_names[0]).decode("utf-8", errors="replace")

    returns = _parse_french_returns(csv_text, column) / 100.0  # percent -> fraction
    index = (1.0 + returns).cumprod() * 100.0  # synthetic base-100 TR index
    index = _clean_index(index)
    index.name = column
    start_ts, end_ts = pd.Timestamp(start), pd.Timestamp(end)
    return index[(index.index >= start_ts) & (index.index < end_ts)]


def fetch_fred_series(series_id: str, start: date, end: date) -> pd.Series:
    """Fetch a FRED series via the public ``fredgraph.csv`` endpoint.

    No API key required. Missing observations (``.``) become NaN. The first CSV
    column is the date and the second the value, regardless of header naming
    (FRED has used both ``DATE`` and ``observation_date``).

    Args:
        series_id: FRED series id (e.g. ``"GOLDPMGBD228NLBM"``).
        start: Inclusive start date (index is clipped to ``[start, end)``).
        end: Exclusive end date.

    Returns:
        The series values as a float Series named ``series_id``.

    Raises:
        ValueError: If the response contains no observations.
    """
    url = _FRED_CSV_URL.format(series_id=series_id)
    text = _http_get_bytes(url).decode("utf-8", errors="replace")
    frame = pd.read_csv(io.StringIO(text), na_values=["."])
    if frame.shape[1] < 2 or frame.empty:
        raise ValueError(f"FRED returned no data for {series_id!r}")
    date_col, value_col = frame.columns[0], frame.columns[1]
    series = pd.Series(
        pd.to_numeric(frame[value_col], errors="coerce").to_numpy(),
        index=pd.to_datetime(frame[date_col]),
        name=series_id,
    )
    series = _clean_index(series)
    series.name = series_id
    start_ts, end_ts = pd.Timestamp(start), pd.Timestamp(end)
    return series[(series.index >= start_ts) & (series.index < end_ts)]
