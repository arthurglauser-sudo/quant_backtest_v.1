"""Universe integrity and proxy-map completeness."""

from __future__ import annotations

import pytest

from quant_backtest.config import universe
from quant_backtest.config.universe import ProxySource

_REF_REQUIRED = {
    ProxySource.YFINANCE,
    ProxySource.FRENCH_UMD,
    ProxySource.FRENCH_HML,
    ProxySource.FRED_GOLD,
    ProxySource.FRED_BILL,
}
_FRENCH = {ProxySource.FRENCH_UMD, ProxySource.FRENCH_HML}


def test_names_are_unique() -> None:
    names = universe.names()
    assert len(names) == len(set(names))


def test_by_name_round_trips() -> None:
    for name in universe.names():
        assert universe.by_name(name).name == name


def test_by_name_unknown_raises() -> None:
    with pytest.raises(KeyError):
        universe.by_name("NOPE")


def test_every_instrument_has_core_fields() -> None:
    for inst in universe.UNIVERSE:
        assert inst.name and inst.ticker
        assert inst.inception is not None


def test_proxy_ref_present_when_required() -> None:
    """External-source proxies must name their source; SELF/NONE must not need it."""
    for inst in universe.UNIVERSE:
        if inst.proxy in _REF_REQUIRED:
            assert inst.proxy_ref, f"{inst.name} missing proxy_ref"
        if inst.proxy in (ProxySource.SELF, ProxySource.NONE):
            assert inst.proxy_ref == ""


def test_french_proxies_name_a_column() -> None:
    for inst in universe.UNIVERSE:
        if inst.proxy in _FRENCH:
            assert inst.proxy_column, f"{inst.name} missing proxy_column"


def test_french_proxies_are_not_fx_converted() -> None:
    """Factor indices are dollar-neutral return streams -> never USD->CHF."""
    for inst in universe.UNIVERSE:
        if inst.proxy in _FRENCH:
            assert not inst.proxy_needs_fx()
        elif inst.has_proxy():
            assert inst.proxy_needs_fx() == inst.is_usd


def test_short_history_instruments_have_no_proxy() -> None:
    no_proxy = {i.name for i in universe.UNIVERSE if not i.has_proxy()}
    assert {"USMV", "EUFN", "BTC"} <= no_proxy


def test_expected_proxy_map() -> None:
    assert universe.by_name("MTUM").proxy is ProxySource.FRENCH_UMD
    assert universe.by_name("VLUE").proxy is ProxySource.FRENCH_HML
    assert universe.by_name("GLD").proxy is ProxySource.FRED_GOLD
    assert universe.by_name("BIL").proxy is ProxySource.FRED_BILL
    assert universe.by_name("XLE").proxy is ProxySource.SELF
    assert universe.by_name("BTC").ticker == "BTC-USD"
