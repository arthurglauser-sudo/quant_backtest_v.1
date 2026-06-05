name: "Data Layer (Phase 2) — reproducible, leak-safe, two-track CHF dataset"
description: |
  Build `quant_backtest/config/` and `quant_backtest/data/` so every later phase
  reads from one deterministic, calendar-aligned, CHF-denominated local dataset
  with an annotated 1998-proxy / real-ETF splice. This module becomes the
  reference pattern for the rest of the package.

## Reviewer amendments (apply these — they override conflicting lines below)
1. Benchmark = TOTAL RETURN. Use SPY adjusted close (dividends reinvested) as the
   S&P 500 total-return proxy. Keep ^GSPC ONLY as the master trading-calendar source.
   In config/parameters.py: CALENDAR_TICKER="^GSPC", BENCHMARK_TICKER="SPY".
   Store the benchmark series as "SPX_TR" from SPY's adjusted close.
2. Data fetching: do NOT use pandas-datareader (incompatible with pinned pandas 3.0).
   Make direct HTTP the PRIMARY path — FRED via
   https://fred.stlouisfed.org/graph/fredgraph.csv?id=<SERIES_ID>, and Ken French via
   the data-library CSV ZIP. Remove the `uv add pandas-datareader` task.
## Purpose
Implement Phase 2 of the quant-backtest engine: the **data layer**. Produce a
reproducible local dataset (Parquet) of cleaned, calendar-aligned, CHF daily
series for the strategy universe, built from a pinned snapshot date, with a
two-track (proxy vs. real) splice and loud quality checks.

## Core Principles
1. **Context is King** — everything needed is in this PRP + `CLAUDE.md`.
2. **Validation Loops** — ruff / mypy / pytest gates below; iterate until green.
3. **Information Dense** — mirror the conventions established here for later phases.
4. **Progressive Success** — config → sources → store → fx → quality → ingest.
5. **Global rules** — obey `CLAUDE.md`, **especially §7 quant guardrails**.

---

## Goal
A working, tested data layer such that:
- `uv run python -m quant_backtest.data.ingest` rebuilds the **entire** dataset
  deterministically from a pinned snapshot date, writing Parquet to
  `data/processed/` (cleaned) and caching raw pulls in `data/raw/`.
- `quant_backtest.data.store.load(instrument, track)` returns a clean daily CHF
  series for any instrument on the `"proxy"`, `"real"`, or `"spliced"` track.
- Quality checks fail **loudly** (raise + printed report) on missing dates,
  duplicates, NaNs, split jumps, or calendar misalignment.
- All strategy parameters (universe, proxy map, dates, currency) live in
  `config/`, not hard-coded in logic (CLAUDE.md §5).

## Why
- Every later phase (sleeves, backtest, allocation, walk-forward, metrics)
  depends on a single trustworthy data source. A leak or splice bug here
  silently poisons every downstream result.
- The two-track design (CLAUDE.md §7) lets us logic-test on 1998–~2013 proxies
  and execution-test on ~2013→now real ETFs, keeping a real-data out-of-sample
  holdout uncontaminated.

## What
A `config/` package (universe + parameters + paths) and a `data/` package
(sources, store, fx, quality, ingest entry point) per INITIAL.md.

### Success Criteria
- [ ] `config/universe.py` defines a typed `Instrument` spec per name: real
      ticker, inception date, 1998 proxy + source; plus global dates and CHF.
- [ ] `data/sources.py` fetches daily adjusted data from yfinance, Ken French
      (UMD / HML), and FRED (CHF short rate, long gold), each returning a clean
      pandas Series/DataFrame with a `DatetimeIndex`.
- [ ] `data/store.py` writes Parquet to `data/processed/`, caches raw to
      `data/raw/`, and exposes `load(instrument, track)`.
- [ ] `data/fx.py` converts each USD series to CHF via USDCHF and exposes the
      CHF risk-free series for Sharpe.
- [ ] Two-track tagging: each series tagged `proxy` / `real` with the splice
      date; loader can return spliced-continuous or real-only.
- [ ] `data/quality.py` checks missing dates, duplicates, NaNs, split jumps,
      calendar misalignment; **raises** with a report on failure.
- [ ] `uv run python -m quant_backtest.data.ingest` rebuilds deterministically.
- [ ] Data files are gitignored (never committed); `.gitkeep` retained.
- [ ] No-look-ahead / trailing-only guardrail tests pass (see §7 of CLAUDE.md).
- [ ] `ruff check .` clean, `mypy quant_backtest` clean, `pytest` green.

## All Needed Context

### Documentation & References
```yaml
- url: https://ranaroussi.github.io/yfinance/reference/api/yfinance.download.html
  why: yf.download params — auto_adjust, group_by, threads, multi-ticker MultiIndex.
  critical: auto_adjust defaults to True now. Multi-ticker -> MultiIndex columns.
            Prefer downloading ONE ticker at a time to keep code simple and avoid
            MultiIndex/column-order churn across versions.

- url: https://pandas-datareader.readthedocs.io/en/latest/readers/famafrench.html
  why: 'famafrench' reader returns a dict-like; data is in [0]; values are PERCENT.
  critical: Ken French factor returns are in percent (0.53 == 0.53%) -> divide by 100.
            Daily momentum dataset name: "F-F_Momentum_Factor_daily" (col "Mom"/"WML").
            Value (HML) daily: "F-F_Research_Data_Factors_daily" (col "HML").
            These are LONG-SHORT factor returns, not long-only ETF returns — annotate
            the proxy as a factor-return index, not a tradeable price (see Gotchas).

- url: https://fred.stlouisfed.org/series/IR3TIB01CHM156N
  why: Switzerland 3-month interbank rate (CHF short rate / risk-free proxy). MONTHLY,
       in percent per annum, starts 1999-07. Forward-fill to daily; convert to a daily
       rate for Sharpe. (Quarterly alt: IR3TIB01CHQ156N.)

- url: https://fred.stlouisfed.org/series/GOLDPMGBD228NLBM
  why: LBMA Gold Price PM fixing, USD/oz — long spot-gold proxy for GLD pre-2004.
       (AM fixing alt: GOLDAMGBD228NLBM.) Daily, USD. Convert to CHF via USDCHF.

- url: https://pandas-datareader.readthedocs.io/en/latest/remote_data.html#fred
  why: web.DataReader(series_id, 'fred', start, end). No API key required.
  critical: pandas-datareader lags pandas releases and MAY break on pandas 3.0.
            FALLBACK (preferred if it errors): fetch FRED directly via CSV —
            https://fred.stlouisfed.org/graph/fredgraph.csv?id=<SERIES_ID>
            and Ken French via the data-library ZIP. Document whichever path is used.

- url: https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html
  why: Canonical Ken French dataset names if direct ZIP download is needed.

- url: https://arrow.apache.org/docs/python/parquet.html
  why: Parquet read/write. Use pandas df.to_parquet(path, engine="pyarrow").

- file: C:\Users\Utilisateur\Projects\quant-backtest\CLAUDE.md
  why: §3 architecture (where code goes), §5 style, §6 testing, §7 guardrails
       (NON-NEGOTIABLE), §8 AI behavior. The proxy map in INITIAL "OTHER
       CONSIDERATIONS" is authoritative for which proxy maps to which ticker.

- file: C:\Users\Utilisateur\Projects\quant-backtest\INITIAL.md
  why: The feature spec for this PRP. Proxy map + short-history gaps are binding.
```

### Current Codebase tree
```
quant-backtest/
├── CLAUDE.md
├── INITIAL.md
├── README.md
├── pyproject.toml          # deps: duckdb, matplotlib, numpy, pandas>=3.0.3,
│                           #       pyarrow, yfinance ; dev: mypy, pytest, ruff
├── uv.lock                 # requests present transitively (via yfinance)
├── .python-version         # 3.13
├── .gitignore              # venv/__pycache__/.ruff_cache/.pytest_cache (NOT data/)
├── .gitattributes
├── data/
│   ├── processed/.gitkeep  # keep; generated parquet goes here, gitignored
│   └── raw/.gitkeep        # keep; raw cache here, gitignored
├── examples/.gitkeep       # empty (greenfield)
├── quant_backtest/
│   └── __init__.py         # empty
└── tests/
    └── __init__.py         # empty
```

### Desired Codebase tree (files to add + responsibility)
```
quant_backtest/
├── config/
│   ├── __init__.py
│   ├── paths.py            # PROJECT_ROOT, DATA_DIR, RAW_DIR, PROCESSED_DIR (pathlib)
│   ├── parameters.py       # START_DATE(1998-01-01), SPLICE_DATE(~2013-06-01),
│   │                       # SNAPSHOT_DATE(pinned, e.g. 2026-06-01), BASE_CCY="CHF",
│   │                       # USDCHF_TICKER, BENCHMARK_TICKER, RNG_SEED
│   └── universe.py         # @dataclass(frozen) Instrument + ProxySource enum +
│                           # UNIVERSE tuple + helpers (usd vs already-CHF, etc.)
├── data/
│   ├── __init__.py
│   ├── sources.py          # fetch_yfinance_series, fetch_french_factor_index,
│   │                       # fetch_fred_series  (+ thin _fred_csv_fallback)
│   ├── fx.py               # load_usdchf, to_chf(series), load_chf_riskfree_daily
│   ├── store.py            # write_raw, write_processed, load(instrument, track),
│   │                       # _processed_path / _raw_path naming
│   ├── quality.py          # @dataclass QualityReport, QualityError(Exception),
│   │                       # check_series(...) -> QualityReport (raises on fail)
│   └── ingest.py           # __main__: orchestrate full deterministic rebuild
tests/
├── config/
│   ├── __init__.py
│   └── test_universe.py            # universe integrity, proxy map completeness
├── data/
│   ├── __init__.py
│   ├── test_sources.py             # mocked network; shape/units/percent->ret
│   ├── test_fx.py                  # USD->CHF direction; rf daily conversion
│   ├── test_store.py               # round-trip parquet; track selection
│   ├── test_quality.py             # each check fires; raises QualityError
│   └── test_no_lookahead.py        # GUARDRAIL: splice + align introduce no future data
└── __init__.py  (exists)
```

### Known Gotchas & Library Quirks
```python
# CRITICAL: pandas 3.0 is pinned (>=3.0.3) and is bleeding-edge. pandas-datareader
#   historically lags pandas. If `web.DataReader(..., 'fred'/'famafrench')` raises,
#   use direct HTTP fallbacks (document which path ran):
#     FRED CSV: https://fred.stlouisfed.org/graph/fredgraph.csv?id=<SERIES_ID>
#               (parse with pandas.read_csv, na_values=["."], parse_dates=[0])
#     French:   download the dataset ZIP from the data library and parse the CSV.
#   Add the dep first:  uv add pandas-datareader  (requests already present).

# CRITICAL: yfinance multi-ticker -> MultiIndex columns with version-dependent order.
#   DOWNLOAD ONE TICKER AT A TIME via yf.Ticker(t).history(auto_adjust=True,...) or
#   yf.download(t, auto_adjust=True). Take the 'Close' column (already adjusted).
#   auto_adjust=True default => 'Close' is split+div adjusted; do NOT also use 'Adj Close'.

# CRITICAL: BTC-USD trades 7 days/week; equities/FX trade ~5. CALENDAR MISALIGNMENT.
#   Define the MASTER trading calendar as the DatetimeIndex of ^GSPC (NYSE sessions),
#   then REINDEX every series onto it. BTC weekend bars are dropped to align to NYSE.
#   This is dependency-free (no exchange-calendars lib needed).

# CRITICAL (CLAUDE.md §7 currency): Yahoo "CHF=X" quotes USD/CHF = CHF per 1 USD.
#   price_chf = price_usd * usdchf.  Double-check direction with a sanity assert
#   (USDCHF historically ~0.8–1.1). Convert the benchmark (^GSPC) too.

# CRITICAL (CLAUDE.md §7 no-look-ahead / trailing-only): this is the DATA layer, so
#   it must not itself inject future info. Rules enforced here:
#   - Reindex/align with NO unbounded forward-fill of prices. For low-frequency
#     series that are genuinely step-functions (FRED monthly rate), forward-fill is
#     allowed but must be TRAILING (ffill only, never bfill). NEVER bfill prices.
#   - The splice must be a hard cut at SPLICE_DATE: proxy strictly BEFORE, real ON/AFTER.
#     No blending across the boundary that would leak real data into the proxy era.

# Ken French factors are in PERCENT and are LONG-SHORT factor returns, not prices.
#   Build a synthetic TOTAL-RETURN INDEX: idx = (1 + ret/100).cumprod() * 100.0.
#   Annotate clearly that MTUM/VLUE proxies are factor-return indices (logic-test
#   track), NOT tradeable ETF prices. This is acceptable for the 1998–2013 logic test.

# Determinism: pin SNAPSHOT_DATE and pass end=SNAPSHOT_DATE to every fetch so reruns
#   are reproducible. Set/Document RNG_SEED even if unused yet (CLAUDE.md §5/§7).

# Gitignore: append data/processed/ and data/raw/ contents (keep .gitkeep) so
#   regenerated parquet is never committed (CLAUDE.md §3, INITIAL reproducibility).

# Style: PEP8, full type hints, Google-style docstrings on public funcs; no magic
#   numbers in logic (all in config/); files < ~500 lines (CLAUDE.md §5).
```

## Implementation Blueprint

### Data models / structure
```python
# config/universe.py
from dataclasses import dataclass
from datetime import date
from enum import Enum

class ProxySource(Enum):
    YFINANCE = "yfinance"      # e.g. ^GSPC EW (RSP), MSCI EAFE (EFA), SPDR self-history
    FRENCH_UMD = "french_umd"  # MTUM momentum factor index
    FRENCH_HML = "french_hml"  # VLUE value factor index
    FRED_GOLD = "fred_gold"    # GLD spot-gold (LBMA)
    FRED_BILL = "fred_bill"    # BIL 3M T-bill
    SELF = "self"              # real ticker is long enough (XLP, XLE, KO, PEP)
    NONE = "none"              # no clean 1998 proxy -> start at inception (USMV, EUFN, BTC)

@dataclass(frozen=True)
class Instrument:
    name: str            # canonical key, e.g. "MTUM"
    ticker: str          # real yfinance ticker, e.g. "MTUM"
    inception: date      # real ETF inception (when 'real' track begins)
    proxy: ProxySource   # how the 1998–splice proxy is built
    proxy_ref: str       # source identifier (yf ticker / FRED id / french dataset)
    is_usd: bool = True  # whether series needs USD->CHF conversion

# UNIVERSE: tuple[Instrument, ...] encoding the INITIAL proxy map exactly:
#   MTUM->FRENCH_UMD, VLUE->FRENCH_HML, RSP->yf "^SP500EW"/RSP (start 2003 if needed),
#   GLD->FRED_GOLD(GOLDPMGBD228NLBM), EFA->yf MSCI EAFE proxy, BIL->FRED_BILL,
#   XLE/XLP->SELF (SPDRs from Dec 1998), KO/PEP->SELF, USMV/EUFN/BTC->NONE (inception).
#   VRP options sleeve EXCLUDED from data layer (INITIAL). SPY tail-put underlier=SPY.
```

### Tasks (in order)
```yaml
Task 1 — Dependencies & gitignore:
  RUN: uv add pandas-datareader
  MODIFY .gitignore:
    - APPEND lines: "data/processed/*", "!data/processed/.gitkeep",
      "data/raw/*", "!data/raw/.gitkeep"
  VERIFY: requests already resolvable (transitive via yfinance) — no extra add.

Task 2 — config/ package:
  CREATE quant_backtest/config/__init__.py  (empty or re-export key constants)
  CREATE quant_backtest/config/paths.py:
    - PROJECT_ROOT = Path(__file__).resolve().parents[2]
    - DATA_DIR, RAW_DIR=DATA_DIR/"raw", PROCESSED_DIR=DATA_DIR/"processed"
    - helper ensure_dirs() (mkdir parents/exist_ok) — used by ingest, not import-time
  CREATE quant_backtest/config/parameters.py:
    - START_DATE=date(1998,1,1); SPLICE_DATE=date(2013,6,1);
      SNAPSHOT_DATE=date(2026,6,1)  # pinned; end of every fetch
    - BASE_CCY="CHF"; USDCHF_TICKER="CHF=X"; BENCHMARK_TICKER="^GSPC"
    - CHF_RF_FRED_ID="IR3TIB01CHM156N"; GOLD_FRED_ID="GOLDPMGBD228NLBM"
    - TRADING_DAYS_PER_YEAR=252; RNG_SEED=20260605
  CREATE quant_backtest/config/universe.py:
    - Instrument dataclass + ProxySource enum + UNIVERSE tuple (per blueprint)
    - by_name(name)->Instrument ; usd_instruments() helper

Task 3 — data/sources.py:
  CREATE quant_backtest/data/sources.py with:
    - fetch_yfinance_series(ticker, start, end) -> pd.Series[float]  (adjusted Close,
      ONE ticker, name=ticker, DatetimeIndex tz-naive)
    - fetch_french_factor_index(dataset, column, start, end) -> pd.Series  (percent ->
      cumprod total-return index base 100.0)
    - fetch_fred_series(series_id, start, end) -> pd.Series  (DataReader 'fred' with
      try/except -> _fred_csv_fallback using fredgraph.csv URL via requests/read_csv)
  PATTERN: each returns sorted, de-duplicated, tz-naive DatetimeIndex; no NaN fill here
           (cleaning/alignment happens in ingest). Raise clear errors on empty pulls.

Task 4 — data/store.py:
  CREATE quant_backtest/data/store.py with:
    - _raw_path(key) -> RAW_DIR/f"{key}.parquet"
    - _processed_path(instrument, track) -> PROCESSED_DIR/f"{instrument}__{track}.parquet"
    - write_raw(key, frame) / write_processed(instrument, track, series)
    - load(instrument, track) -> pd.Series : track in {"proxy","real","spliced"};
      "spliced" reads proxy (<SPLICE_DATE) + real (>=SPLICE_DATE) and concatenates,
      asserting the boundary is clean (no overlap leak).
  GOTCHA: store a single-column DataFrame (col="value") or use Series.to_frame for
          parquet; reload to Series. Keep index name "date".

Task 5 — data/fx.py:
  CREATE quant_backtest/data/fx.py with:
    - load_usdchf(start, end) -> pd.Series  (fetch CHF=X, reindex to master calendar,
      TRAILING ffill for FX gaps only)
    - to_chf(price_usd: pd.Series, usdchf: pd.Series) -> pd.Series  (align on index,
      multiply; assert plausible USDCHF range ~0.7–1.3 to catch inverted direction)
    - load_chf_riskfree_daily(start, end) -> pd.Series  (FRED CHF 3M rate, percent p.a.
      -> daily simple rate /100/TRADING_DAYS_PER_YEAR; ffill monthly->daily, TRAILING)

Task 6 — data/quality.py:
  CREATE quant_backtest/data/quality.py with:
    - class QualityError(Exception)
    - @dataclass QualityReport: name, n_obs, first, last, n_missing_sessions,
      n_duplicates, n_nans, max_abs_log_jump, ok: bool, messages: list[str]
    - check_series(series, calendar, *, split_jump_log_threshold=0.5) -> QualityReport
        * duplicates in index, NaNs, missing sessions vs master calendar,
          calendar misalignment (index ⊆ calendar), unadjusted-split jumps
          (|log return| > threshold flagged), then raise QualityError if not ok.
    - render(report) -> str for the printed failure report.

Task 7 — data/ingest.py (entry point / orchestrator):
  CREATE quant_backtest/data/ingest.py with main():
    1. ensure_dirs()
    2. master_calendar = fetch ^GSPC index -> its DatetimeIndex (clip to [START,SNAPSHOT])
    3. usdchf = load_usdchf(START, SNAPSHOT) reindexed to master_calendar
    4. For each Instrument:
         - REAL track: fetch real ticker from max(inception) -> reindex master_calendar
           -> to_chf if is_usd -> quality.check -> write_processed(name,"real")
         - PROXY track (if proxy != NONE): build per ProxySource (yf/french/fred),
           clip to [START, SPLICE_DATE) -> to_chf where USD -> quality.check ->
           write_processed(name,"proxy")
    5. Benchmark ^GSPC -> CHF -> write_processed("SPX_TR","real") (+ proxy = itself pre-splice)
    6. CHF risk-free -> write_processed("CHF_RF","real")
    7. Print a summary table (instrument, track, first, last, n_obs).
  PATTERN: `if __name__ == "__main__": raise SystemExit(main())`
  DETERMINISM: pass end=SNAPSHOT_DATE everywhere; cache raw pulls to data/raw first,
               and prefer cached raw on rerun unless a --refresh flag is passed (argparse).

Task 8 — Tests (mirror package; mock all network):
  CREATE tests/config/test_universe.py, tests/data/test_*.py per desired tree.
  Use monkeypatch to replace fetch_* with deterministic synthetic Series (DO NOT hit
  the network in unit tests). Cover: percent->index conversion, USD->CHF direction,
  rf daily conversion, parquet round-trip, each quality check firing, and the
  no-look-ahead splice/alignment guarantees.
```

### Per-task pseudocode (critical details only)
```python
# Task 3 — fetch_yfinance_series
def fetch_yfinance_series(ticker: str, start: date, end: date) -> pd.Series:
    # GOTCHA: one ticker only -> simple columns; auto_adjust=True -> 'Close' is adjusted
    df = yf.download(ticker, start=start, end=end, auto_adjust=True, progress=False)
    if df.empty:
        raise ValueError(f"yfinance returned no data for {ticker}")
    close = df["Close"]
    if isinstance(close, pd.DataFrame):       # defensive vs MultiIndex
        close = close.iloc[:, 0]
    s = close.copy(); s.index = pd.to_datetime(s.index).tz_localize(None)
    s = s[~s.index.duplicated(keep="last")].sort_index()
    s.name = ticker; s.index.name = "date"
    return s.astype(float)

# Task 3 — fetch_french_factor_index
def fetch_french_factor_index(dataset, column, start, end) -> pd.Series:
    # PATTERN: pandas-datareader 'famafrench' -> dict; data in [0]; values in PERCENT
    raw = web.DataReader(dataset, "famafrench", start, end)[0]
    ret = raw[column].astype(float) / 100.0      # CRITICAL percent -> fraction
    idx = (1.0 + ret).cumprod() * 100.0          # synthetic total-return index
    idx.index = pd.to_datetime(idx.index).tz_localize(None); idx.index.name = "date"
    return idx  # ANNOTATE downstream: factor proxy, not tradeable price

# Task 5 — to_chf  (CLAUDE.md §7 currency)
def to_chf(price_usd: pd.Series, usdchf: pd.Series) -> pd.Series:
    fx = usdchf.reindex(price_usd.index).ffill()          # TRAILING only
    assert fx.dropna().between(0.5, 1.5).all(), "USDCHF out of range — check direction"
    return (price_usd * fx).rename(price_usd.name)        # CHF per USD * USD price

# Task 6 — split-jump detection (unadjusted split heuristic)
# log_ret = np.log(series).diff(); flag |log_ret| > split_jump_log_threshold.
# Adjusted series should NOT show 2:1-type ~0.69 jumps; if they do, raise.

# Task 7 — splice cut (no look-ahead)
# proxy = proxy_series[proxy_series.index <  pd.Timestamp(SPLICE_DATE)]
# real  = real_series [real_series.index  >= pd.Timestamp(SPLICE_DATE)]
# spliced = pd.concat([proxy, real]).sort_index(); assert spliced.index.is_unique
```

### Integration Points
```yaml
DEPENDENCIES:
  - run: uv add pandas-datareader            # requests already transitive
  - (optional, only if mypy needs stubs): uv add --dev pandas-stubs

CONFIG:
  - all dates / tickers / FRED ids / seed live in quant_backtest/config/parameters.py
  - universe + proxy map live in quant_backtest/config/universe.py (single source)

GITIGNORE:
  - append: data/processed/*  + !data/processed/.gitkeep
            data/raw/*        + !data/raw/.gitkeep

ENTRY POINT:
  - uv run python -m quant_backtest.data.ingest   (rebuilds everything)
  - reader API: from quant_backtest.data.store import load
```

## Validation Loop

### Level 1: Syntax & Style
```bash
uv run ruff check . --fix
uv run mypy quant_backtest
# Expected: no errors. If mypy complains about pandas types, add pandas-stubs (dev)
# or use precise annotations; do NOT blanket-ignore.
```

### Level 2: Unit Tests (network mocked)
```python
# tests/data/test_sources.py
def test_french_percent_to_index(monkeypatch):
    """Percent factor returns -> base-100 cumulative index."""
    fake = pd.DataFrame({"Mom": [1.0, -1.0]}, index=pd.to_datetime(["2000-01-03","2000-01-04"]))
    monkeypatch.setattr(sources.web, "DataReader", lambda *a, **k: {0: fake})
    idx = sources.fetch_french_factor_index("F-F_Momentum_Factor_daily", "Mom", START, SNAPSHOT)
    assert idx.iloc[0] == pytest.approx(101.0)          # 100*(1+0.01)
    assert idx.iloc[1] == pytest.approx(101.0*0.99)

# tests/data/test_fx.py
def test_to_chf_direction():
    """price_chf = price_usd * usdchf; rejects inverted FX."""
    usd = pd.Series([100.0], index=pd.to_datetime(["2020-01-02"]))
    fx  = pd.Series([0.97],  index=pd.to_datetime(["2020-01-02"]))
    assert fx_mod.to_chf(usd, fx).iloc[0] == pytest.approx(97.0)

# tests/data/test_quality.py
def test_quality_raises_on_nan():
    s = pd.Series([1.0, float("nan")], index=pd.to_datetime(["2020-01-02","2020-01-03"]))
    with pytest.raises(quality.QualityError):
        quality.check_series(s, calendar=s.index)

# tests/data/test_no_lookahead.py  (GUARDRAIL — CLAUDE.md §7)
def test_splice_has_no_future_leak():
    """Proxy strictly before splice, real on/after; no overlap, monotonic index."""
    # build proxy+real, write_processed, load(track="spliced"); assert boundary clean.

def test_no_bfill_of_prices():
    """Alignment uses trailing ffill only; a leading gap stays NaN/dropped, never bfilled."""
```
```bash
uv run pytest tests/ -v
# Iterate until green. Never weaken a guardrail test to pass.
```

### Level 3: Integration (real rebuild — manual, network)
```bash
uv run python -m quant_backtest.data.ingest
# Expected: prints a summary table; writes data/processed/*.parquet and data/raw/*.
# Spot-check:
uv run python -c "from quant_backtest.data.store import load; s=load('MTUM','spliced'); print(s.head(), s.tail(), s.isna().sum())"
# Expected: continuous CHF series 1998->~now, no NaNs, monotonic dates.
# Confirm nothing got committed: `git status` shows only code, data/ stays ignored.
```

## Final Validation Checklist
- [ ] `uv run pytest tests/ -v` green (incl. no-look-ahead guardrails)
- [ ] `uv run ruff check .` clean
- [ ] `uv run mypy quant_backtest` clean
- [ ] `uv run python -m quant_backtest.data.ingest` rebuilds deterministically
- [ ] `load(instrument, track)` returns clean CHF series for proxy/real/spliced
- [ ] Quality checks raise loudly with a readable report on bad data
- [ ] `git status` confirms data/processed + data/raw stay gitignored (.gitkeep kept)
- [ ] All params in config/; no magic numbers in data/ logic
- [ ] Splice annotated; USD->CHF direction asserted; FRED/French units handled

## Anti-Patterns to Avoid
- ❌ Using the same bar's close for signal and fill — N/A here, but never align
     with bfill or unbounded ffill that pulls future values backward.
- ❌ Full-sample normalization — none in the data layer; keep cleaning per-series.
- ❌ Downloading multiple yfinance tickers at once and wrestling MultiIndex.
- ❌ Treating Ken French percent returns as fractions, or as tradeable prices.
- ❌ Committing data files; or hard-coding dates/tickers outside config/.
- ❌ Swallowing fetch errors silently — fail loudly with context.
- ❌ Blanket `# type: ignore` or `except Exception: pass`.

---

## Confidence Score: 8/10
High confidence for one-pass success: the proxy map, dates, FRED ids, French
dataset names, and currency direction are all pinned, and the architecture/validation
gates are explicit. The −2 risk is external/runtime: (a) pandas-datareader
compatibility with pandas 3.0 (mitigated by the documented FRED-CSV / French-ZIP
fallbacks), and (b) live data availability/inception-date edge cases for a few
proxies (RSP pre-2003, MSCI EAFE proxy ticker), which may need a small ticker tweak
during the Level-3 network run. Unit tests are fully network-mocked, so Levels 1–2
are deterministic regardless.
```
