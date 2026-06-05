# INITIAL.md — Feature: Data Layer (Phase 2)

## FEATURE
Build the project's data layer: `quant_backtest/config/` (universe + parameters) and `quant_backtest/data/` (ingestion, storage, FX, quality). It must produce a reproducible, leak-safe local dataset that all later phases read from.

Requirements:
1. **Config** (`config/universe.py`): define the trading universe and, per instrument, its real ticker, inception date, and 1998 proxy + source. Define global dates (start 1998-01-01, splice ~2013, a pinned snapshot date) and base currency (CHF).
2. **Sources** (`data/sources.py`): fetch daily adjusted data from
   - yfinance — ETFs, KO, PEP, BTC-USD, ^GSPC (S&P 500), CHF=X (USDCHF)
   - Ken French Data Library — momentum (UMD) and value (HML) factor returns (the pre-ETF proxies)
   - FRED — a CHF short rate (risk-free) and a long spot-gold series
3. **Store** (`data/store.py`): write cleaned, calendar-aligned daily series to `data/processed/` as Parquet; cache raw pulls in `data/raw/`. Provide a `load(instrument, track)` reader.
4. **FX** (`data/fx.py`): convert each USD price series to CHF via USDCHF; expose the CHF risk-free series for Sharpe.
5. **Two-track**: tag each series as `proxy` (1998–~2013) or `real` (~2013→now) with the splice date; allow loading a spliced continuous series or real-only.
6. **Quality** (`data/quality.py`): check for missing dates, duplicates, NaNs, unadjusted-split jumps, and calendar misalignment; fail loudly with a report.
7. **Entry point**: `uv run python -m quant_backtest.data.ingest` rebuilds the whole dataset deterministically from the pinned snapshot date.

## EXAMPLES
None yet (greenfield). Follow the conventions and guardrails in `CLAUDE.md`. The module built here becomes the reference pattern for later phases.

## DOCUMENTATION
- yfinance: https://ranaroussi.github.io/yfinance/
- Ken French Data Library: https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html
- FRED via pandas-datareader: https://pandas-datareader.readthedocs.io/
- pandas: https://pandas.pydata.org/docs/ · pyarrow/Parquet: https://arrow.apache.org/docs/python/ · DuckDB: https://duckdb.org/docs/

## OTHER CONSIDERATIONS
- **Proxy map** (real ticker → 1998 proxy → source): MTUM→French UMD; VLUE→French HML; RSP→S&P 500 EW index, else start 2003 (yfinance); GLD→spot gold (FRED); EFA→MSCI EAFE (yfinance); BIL→3M T-bill (FRED); XLP/XLE→use the SPDRs (long enough, from Dec 1998); KO/PEP→real (yfinance).
- **Short-history gaps:** USMV (2011) and EUFN (2010) have no clean free 1998 proxy — start them at inception. BTC starts ~2014. The VRP options sleeve has no free historical options data — **exclude it from the data layer** (modeled later).
- **Currency:** everything downstream is CHF — store CHF series and keep USDCHF available.
- **Adjusted prices:** use split/dividend-adjusted series for returns; be consistent across sources.
- **Reproducibility & Git:** deterministic rebuild, pinned snapshot date, data files gitignored (never committed).
- **Guardrails:** see `CLAUDE.md` §7 — especially trailing-only stats and the two-track splice annotation.