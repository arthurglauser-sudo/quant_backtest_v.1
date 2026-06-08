"""The trading universe and its 1998-proxy map.

Each :class:`Instrument` records the real (execution-track) ticker, the real
ETF inception date, and how its 1998->splice proxy (logic-track) is built. This
encodes the proxy map from ``INITIAL.md`` "OTHER CONSIDERATIONS" verbatim and is
the single source of truth for what the data layer ingests.

The VRP options sleeve is intentionally excluded (no free historical options
data); it is modelled in a later phase. The SPY tail-put sleeve shares the SPY
underlier already present as the benchmark.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum


class ProxySource(Enum):
    """How an instrument's 1998->splice proxy series is built."""

    YFINANCE = "yfinance"  # a yfinance index/ETF distinct from the real ticker
    FRENCH_UMD = "french_umd"  # Ken French momentum factor -> MTUM proxy
    FRENCH_HML = "french_hml"  # Ken French value (HML) factor -> VLUE proxy
    FRED_GOLD = "fred_gold"  # LBMA spot gold (FRED) -> GLD proxy
    FRED_BILL = "fred_bill"  # 3M T-bill rate (FRED) -> BIL proxy
    SELF = "self"  # real ticker's own history is long enough for the proxy era
    NONE = "none"  # no clean 1998 proxy -> series starts at inception


# Ken French long-short factor indices are dollar-neutral return streams, not
# USD asset prices, so they are NOT FX-converted. Every other proxy source
# yields a USD-denominated level series that is converted to CHF.
_NON_USD_PROXY_SOURCES: frozenset[ProxySource] = frozenset(
    {ProxySource.FRENCH_UMD, ProxySource.FRENCH_HML}
)


@dataclass(frozen=True)
class Instrument:
    """Specification for one tradeable name in the universe.

    Attributes:
        name: Canonical key used for storage/loading (e.g. ``"MTUM"``).
        ticker: Real yfinance ticker for the execution track.
        inception: Real ETF/stock inception; the ``real`` track begins here.
        proxy: How the 1998->splice proxy track is built.
        proxy_ref: Source identifier for the proxy (yfinance ticker, FRED id,
            or Ken French dataset name); empty when ``proxy`` is ``NONE``.
        proxy_column: Column to extract for Ken French datasets; empty
            otherwise.
        is_usd: Whether the real series is USD-denominated (needs USD->CHF).
    """

    name: str
    ticker: str
    inception: date
    proxy: ProxySource
    proxy_ref: str = ""
    proxy_column: str = ""
    is_usd: bool = True

    def has_proxy(self) -> bool:
        """Whether a proxy track should be built for this instrument."""
        return self.proxy is not ProxySource.NONE

    def proxy_needs_fx(self) -> bool:
        """Whether the proxy series is a USD level series needing USD->CHF.

        Ken French factor proxies are dollar-neutral return indices and are
        left unconverted; all other proxies are USD price/level series.
        """
        return self.has_proxy() and self.proxy not in _NON_USD_PROXY_SOURCES


# Proxy map per INITIAL.md. Inception dates are the real listing dates; the
# real track is fetched from ``max(START_DATE, inception)``.
UNIVERSE: tuple[Instrument, ...] = (
    # Momentum / value factor sleeves -> Ken French factor proxies.
    Instrument(
        name="MTUM",
        ticker="MTUM",
        inception=date(2013, 4, 16),
        proxy=ProxySource.FRENCH_UMD,
        proxy_ref="F-F_Momentum_Factor_daily",
        proxy_column="Mom",
    ),
    Instrument(
        name="VLUE",
        ticker="VLUE",
        inception=date(2013, 4, 16),
        proxy=ProxySource.FRENCH_HML,
        proxy_ref="F-F_Research_Data_Factors_daily",
        proxy_column="HML",
    ),
    # Equal-weight S&P 500: real RSP from 2003; proxy from the EW index.
    Instrument(
        name="RSP",
        ticker="RSP",
        inception=date(2003, 4, 24),
        proxy=ProxySource.YFINANCE,
        proxy_ref="^SP500EW",
    ),
    # Gold: spot LBMA gold (FRED) proxy before GLD's 2004 inception.
    Instrument(
        name="GLD",
        ticker="GLD",
        inception=date(2004, 11, 18),
        proxy=ProxySource.FRED_GOLD,
        proxy_ref="GOLDPMGBD228NLBM",
    ),
    # Developed ex-US: EFA's own history (from 2001) is the proxy.
    Instrument(
        name="EFA",
        ticker="EFA",
        inception=date(2001, 8, 14),
        proxy=ProxySource.SELF,
    ),
    # T-bills: 3M T-bill rate (FRED) proxy before BIL's 2007 inception.
    Instrument(
        name="BIL",
        ticker="BIL",
        inception=date(2007, 5, 25),
        proxy=ProxySource.FRED_BILL,
        proxy_ref="DTB3",
    ),
    # Sector SPDRs: long enough (Dec 1998) to be their own proxy.
    Instrument(
        name="XLE",
        ticker="XLE",
        inception=date(1998, 12, 16),
        proxy=ProxySource.SELF,
    ),
    Instrument(
        name="XLP",
        ticker="XLP",
        inception=date(1998, 12, 16),
        proxy=ProxySource.SELF,
    ),
    # Defensive / regional sleeves with no clean 1998 proxy -> start at inception.
    Instrument(
        name="USMV",
        ticker="USMV",
        inception=date(2011, 10, 18),
        proxy=ProxySource.NONE,
    ),
    Instrument(
        name="EUFN",
        ticker="EUFN",
        inception=date(2010, 1, 29),
        proxy=ProxySource.NONE,
    ),
    # KO/PEP mean-reversion pair: long single-stock history -> self proxy.
    Instrument(
        name="KO",
        ticker="KO",
        inception=date(1962, 1, 2),
        proxy=ProxySource.SELF,
    ),
    Instrument(
        name="PEP",
        ticker="PEP",
        inception=date(1972, 1, 3),
        proxy=ProxySource.SELF,
    ),
    # Bitcoin sleeve: trades 7 days/week, no 1998 proxy.
    Instrument(
        name="BTC",
        ticker="BTC-USD",
        inception=date(2014, 9, 17),
        proxy=ProxySource.NONE,
    ),
    # SPY: tail-put underlier; also long enough to be its own proxy.
    Instrument(
        name="SPY",
        ticker="SPY",
        inception=date(1993, 1, 29),
        proxy=ProxySource.SELF,
    ),
)

_BY_NAME: dict[str, Instrument] = {inst.name: inst for inst in UNIVERSE}


def by_name(name: str) -> Instrument:
    """Return the :class:`Instrument` with the given canonical name.

    Args:
        name: Canonical instrument key (e.g. ``"MTUM"``).

    Returns:
        The matching :class:`Instrument`.

    Raises:
        KeyError: If no instrument with that name exists.
    """
    try:
        return _BY_NAME[name]
    except KeyError as exc:
        raise KeyError(f"Unknown instrument {name!r}") from exc


def names() -> tuple[str, ...]:
    """Return all canonical instrument names, in universe order."""
    return tuple(inst.name for inst in UNIVERSE)


def usd_instruments() -> tuple[Instrument, ...]:
    """Return instruments whose real series is USD-denominated."""
    return tuple(inst for inst in UNIVERSE if inst.is_usd)
