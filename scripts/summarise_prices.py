#!/usr/bin/env python
"""Summarise house prices per school catchment and render the choropleths.

Reads whichever transaction table is available (preferring the EPC-enriched one)
and writes a Markdown table plus one map per measure.

Usage:
    uv run python scripts/summarise_prices.py --layer secondary
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import polars as pl

from ny_catchments.config import DATA_INTERIM, DEFAULT_YEARS, LAYERS, OUTPUTS
from ny_catchments.io import load_catchments
from ny_catchments.plot import plot_choropleth
from ny_catchments.summarise import MIN_TRANSACTIONS, catchment_summary, to_markdown

STAND_IN_NOTE = (
    "STAND-IN: SECONDARY catchments — the primary layer's .shp was not supplied by NYC."
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--layer", choices=sorted(LAYERS), default="secondary")
    parser.add_argument("--years", type=int, default=DEFAULT_YEARS)
    args = parser.parse_args()

    spec = LAYERS[args.layer]

    enriched = DATA_INTERIM / f"transactions_{spec.key}_with_epc.parquet"
    plain = DATA_INTERIM / f"transactions_{spec.key}.parquet"
    source = enriched if enriched.exists() else plain
    if not source.exists():
        print(
            "No transaction table found. Run scripts/build_transactions.py first.",
            file=sys.stderr,
        )
        return 1

    transactions = pl.read_parquet(source)
    has_ppm2 = "price_per_m2" in transactions.columns
    print(f"Reading {source.name} ({transactions.height:,} sales, £/m²: {has_ppm2})")

    summary = catchment_summary(transactions)
    catchments = load_catchments(spec)

    OUTPUTS.mkdir(parents=True, exist_ok=True)

    table_path = OUTPUTS / f"catchment_prices_{spec.key}.md"
    window = f"last {args.years} years"
    header = (
        f"# House prices by {spec.phase_label.lower()} school catchment\n\n"
        f"North Yorkshire, {window}. HM Land Registry Price Paid, category A "
        f"(open-market) sales only.\n\n"
        f"Catchments with fewer than {MIN_TRANSACTIONS} sales are not reported.\n\n"
    )
    if has_ppm2:
        rate = transactions["floor_area_m2"].is_not_null().mean()
        flats = transactions.filter(pl.col("property_type") == "F")
        flat_rate = flats["floor_area_m2"].is_not_null().mean() if flats.height else 0.0
        header += (
            f"£/m² rests on an EPC floor-area match for **{rate:.1%}** of sales "
            f"(flats {flat_rate:.1%} — several flats in one block often share a "
            f"name with no distinguishing number, and an ambiguous address is left "
            f"unmatched rather than guessed). Unmatched sales still count toward "
            f"`Sales`, mean and median.\n\n"
        )
    table_path.write_text(header + to_markdown(summary) + "\n")
    print(f"Wrote {table_path}")

    reported = summary.filter(~pl.col("suppressed"))
    note = STAND_IN_NOTE if spec.key == "secondary" else None

    figures = [
        (
            "median_price",
            f"Median house price by {spec.phase_label.lower()} school catchment",
            "Median price",
            lambda v: f"£{v / 1000:,.0f}k",
        )
    ]
    if has_ppm2:
        figures.append(
            (
                "median_price_per_m2",
                f"Median price per m² by {spec.phase_label.lower()} school catchment",
                "Median £ per m²",
                lambda v: f"£{v:,.0f}",
            )
        )

    for column, title, legend_title, fmt in figures:
        values = dict(zip(reported["catchment_name"], reported[column], strict=True))
        fig = plot_choropleth(
            catchments,
            values,
            title=title,
            subtitle=f"North Yorkshire · {window} · {transactions.height:,} sales",
            value_label=legend_title,
            fmt=fmt,
            stand_in_note=note,
        )
        out = OUTPUTS / f"{column}_{spec.key}.png"
        fig.savefig(out, dpi=200, bbox_inches="tight", facecolor=fig.get_facecolor())
        print(f"Wrote {out}")

    print(f"\n{to_markdown(summary.head(10))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
