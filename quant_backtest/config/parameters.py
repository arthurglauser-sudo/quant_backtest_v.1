"""Global strategy / data parameters.

Single source of truth for dates, currency, tickers, FRED series ids, and the
handful of numeric thresholds the data layer needs. Nothing here is hard-coded
elsewhere (CLAUDE.md §5).
"""

from __future__ import annotations

from datetime import date

# --- Time horizon ----------------------------------------------------------
# Backtest start. Strategy instruments postdate 1998; the proxy track covers
# 1998 -> SPLICE_DATE, the real-ETF track SPLICE_DATE -> SNAPSHOT_DATE.
START_DATE: date = date(1998, 1, 1)

# Hard cut between the proxy (logic-test) and real-ETF (execution-test) tracks
# (CLAUDE.md §7 two-track history). Proxy is used strictly BEFORE this date,
# real strictly ON/AFTER it.
SPLICE_DATE: date = date(2013, 6, 1)

# Pinned data-snapshot date. Passed as ``end`` to every fetch so reruns are
# reproducible (CLAUDE.md §7 reproducibility).
SNAPSHOT_DATE: date = date(2026, 6, 1)

# --- Currency --------------------------------------------------------------
BASE_CCY: str = "CHF"
# Yahoo "CHF=X" quotes USD/CHF = CHF per 1 USD, so price_chf = price_usd * fx.
USDCHF_TICKER: str = "CHF=X"
# Sanity bounds to catch an inverted FX series (USDCHF historically ~0.8-1.1).
USDCHF_MIN: float = 0.5
USDCHF_MAX: float = 1.5

# --- Benchmark & master calendar -------------------------------------------
# ^GSPC defines the master NYSE trading calendar ONLY (price-return, no
# dividends) -- every series is reindexed onto its sessions.
CALENDAR_TICKER: str = "^GSPC"
# Benchmark is TOTAL RETURN: SPY adjusted close (dividends reinvested) is the
# S&P 500 total-return proxy. Stored under BENCHMARK_NAME.
BENCHMARK_TICKER: str = "SPY"
BENCHMARK_NAME: str = "SPX_TR"

# --- FRED series ids -------------------------------------------------------
# Switzerland 3-month interbank rate, percent p.a., monthly (CHF risk-free).
CHF_RF_FRED_ID: str = "IR3TIB01CHM156N"
CHF_RF_NAME: str = "CHF_RF"
# LBMA Gold Price PM fixing, USD/oz (long spot-gold proxy for GLD pre-2004).
GOLD_FRED_ID: str = "GOLDPMGBD228NLBM"
# 3-Month Treasury Bill secondary-market rate, percent p.a., daily (BIL proxy).
TBILL_FRED_ID: str = "DTB3"

# --- Numeric knobs ---------------------------------------------------------
TRADING_DAYS_PER_YEAR: int = 252

# Bounded trailing forward-fill for price gaps during calendar alignment. ffill
# only carries PAST values forward (no look-ahead); the bound stops a stale
# price from spanning a long outage (CLAUDE.md §7 no unbounded ffill).
PRICE_FFILL_LIMIT: int = 3

# |log return| above this flags an unadjusted-split / data-error jump. 0.5 is
# tight enough to catch a 2:1 split (~0.69); crypto gets a looser bound.
SPLIT_JUMP_LOG_THRESHOLD: float = 0.5
CRYPTO_SPLIT_JUMP_LOG_THRESHOLD: float = 1.0

# Fixed RNG seed for any future stochastic step (CLAUDE.md §5/§7). Unused now.
RNG_SEED: int = 20260605
