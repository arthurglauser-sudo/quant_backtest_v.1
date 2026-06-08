"""Data layer: fetch, store, FX-convert, and quality-check the universe.

Produces one deterministic, calendar-aligned, CHF-denominated local dataset
(Parquet) with an annotated proxy/real splice. Rebuild via
``uv run python -m quant_backtest.data.ingest``.
"""
