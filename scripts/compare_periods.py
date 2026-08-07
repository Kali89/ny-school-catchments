#!/usr/bin/env python
"""Rank catchments by price per m², and compare across time periods.

Produces:
    price_per_m2_distribution_<layer>.png   ranked box plot, recent period
    price_per_m2_rank_shift_<layer>.png     rank across all three periods
    price_per_m2_excess_<from>_<to>_<layer>.png   outsized movers
    period_comparison_<layer>.md            the numbers behind all three

Usage:
    uv run python scripts/compare_periods.py --layer secondary
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import polars as pl

from ny_catchments.config import DATA_INTERIM, FOCUS_EASTING, FOCUS_NORTHING, LAYERS, OUTPUTS
from ny_catchments.io import NAME_FIELD, load_catchments
from ny_catchments.periods import (
    EARLY,
    PERIODS,
    PRIOR,
    RECENT,
    assign_periods,
    period_coverage,
    period_medians,
    relative_change,
)
from ny_catchments.plot_prices import (
    plot_excess_change,
    plot_price_distribution,
    plot_rank_shift,
)
from ny_catchments.summarise import MIN_TRANSACTIONS

STAND_IN_NOTE = (
    "STAND-IN: SECONDARY catchments — the primary layer's .shp was not supplied by NYC."
)


def focal_catchment_name(spec) -> str | None:
    """The catchment containing Great Ouseburn, for highlighting."""
    from shapely.geometry import Point

    catchments = load_catchments(spec)
    hit = catchments[catchments.geometry.contains(Point(FOCUS_EASTING, FOCUS_NORTHING))]
    return None if hit.empty else str(hit.iloc[0][NAME_FIELD]).strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--layer", choices=sorted(LAYERS), default="secondary")
    parser.add_argument(
        "--min-sales",
        type=int,
        default=MIN_TRANSACTIONS,
        help="Minimum priced sales per catchment-period (default: %(default)s).",
    )
    args = parser.parse_args()

    spec = LAYERS[args.layer]
    source = DATA_INTERIM / f"transactions_{spec.key}_with_epc.parquet"
    if not source.exists():
        print(f"{source} not found — run build_transactions then build_floor_areas.",
              file=sys.stderr)
        return 1

    transactions = assign_periods(pl.read_parquet(source))
    if "price_per_m2" not in transactions.columns:
        print("No price_per_m2 column — run scripts/build_floor_areas.py first.",
              file=sys.stderr)
        return 1

    focal = focal_catchment_name(spec)
    note = STAND_IN_NOTE if spec.key == "secondary" else None
    OUTPUTS.mkdir(parents=True, exist_ok=True)

    coverage = period_coverage(transactions)
    print(f"EPC coverage by period:\n{coverage}\n")

    # --- Figure 1: ranked distribution, most recent period ---
    recent = transactions.filter(pl.col("period") == RECENT.key)
    fig = plot_price_distribution(
        recent,
        min_transactions=args.min_sales,
        focal_catchment=focal,
        title="Price per m² by secondary school catchment",
        subtitle=(
            f"North Yorkshire · {RECENT.label.lower()} ({RECENT.span_label}) · "
            f"{recent['price_per_m2'].is_not_null().sum():,} priced sales"
        ),
        stand_in_note=note,
    )
    out = OUTPUTS / f"price_per_m2_distribution_{spec.key}.png"
    fig.savefig(out, dpi=200, bbox_inches="tight", facecolor=fig.get_facecolor())
    print(f"Wrote {out}")

    # --- Figure 2: rank across periods ---
    medians = period_medians(transactions, min_transactions=args.min_sales)
    fig = plot_rank_shift(medians, PERIODS, focal_catchment=focal, stand_in_note=note)
    out = OUTPUTS / f"price_per_m2_rank_shift_{spec.key}.png"
    fig.savefig(out, dpi=200, bbox_inches="tight", facecolor=fig.get_facecolor())
    print(f"Wrote {out}")

    # --- Figure 3+: outsized movers, for each period pair ---
    pairs = [(EARLY, RECENT), (PRIOR, RECENT)]
    tables: list[tuple[str, pl.DataFrame]] = []
    for from_period, to_period in pairs:
        changes = relative_change(medians, from_period, to_period)
        county = changes["county_change_pct"][0]
        fig = plot_excess_change(
            changes,
            from_label=f"{from_period.label.lower()} ({from_period.span_label})",
            to_label=f"{to_period.label.lower()} ({to_period.span_label})",
            county_change_pct=county,
            focal_catchment=focal,
            stand_in_note=note,
        )
        out = OUTPUTS / f"price_per_m2_excess_{from_period.key}_to_{to_period.key}_{spec.key}.png"
        fig.savefig(out, dpi=200, bbox_inches="tight", facecolor=fig.get_facecolor())
        print(f"Wrote {out}")
        tables.append((f"{from_period.label} → {to_period.label}", changes))

    _write_report(spec, coverage, medians, tables, args.min_sales, focal)
    return 0


def _write_report(spec, coverage, medians, tables, min_sales: int, focal: str | None) -> None:
    """Write the numbers behind the figures."""
    lines = [
        f"# Price per m² over time, by {spec.phase_label.lower()} school catchment",
        "",
        "North Yorkshire. HM Land Registry Price Paid (category A) with EPC floor areas.",
        f"Catchment-periods with fewer than {min_sales} priced sales are suppressed.",
        "Periods cover whole calendar years; part-year 2026 is excluded.",
        "",
        "All figures are **nominal**. Comparisons across periods are therefore made",
        "relative to the county-wide change, which nets out general house price",
        "inflation — an absolute rise means little when everything rose.",
        "",
        "A caution on the extremes: a catchment near the top or bottom of the",
        "outsized-movers tables is more likely to be one with few sales, where the",
        "median moves on which houses happened to change hands. Read the ranking",
        "alongside the sale counts in the distribution figure.",
        "",
        "## EPC coverage by period — read this before the tables",
        "",
        "The EPC register begins in 2012, so a sale before then carries a floor area",
        "only if the property was certified later. That happens when it is marketed",
        "again, so early-period coverage is a function of subsequent market activity",
        "rather than a random sample of what sold at the time.",
        "",
        "| Period | Sales | With floor area | Coverage |",
        "|---|---:|---:|---:|",
    ]
    label_by_key = {p.key: f"{p.label} ({p.span_label})" for p in PERIODS}
    for row in coverage.iter_rows(named=True):
        lines.append(
            f"| {label_by_key.get(row['period'], row['period'])} | "
            f"{row['transactions']:,} | {row['with_floor_area']:,} | "
            f"{row['match_rate']:.1%} |"
        )

    lines += ["", "## Median £/m² by catchment and period", "",
              "| Catchment | " + " | ".join(label_by_key[p.key] for p in PERIODS) + " |",
              "|---" * (len(PERIODS) + 1) + "|"]
    wide = medians.pivot(
        on="period", index="catchment_name", values="median_price_per_m2"
    ).sort(RECENT.key, descending=True, nulls_last=True)
    for row in wide.iter_rows(named=True):
        cells = []
        for period in PERIODS:
            value = row.get(period.key)
            cells.append("—" if value is None else f"£{value:,.0f}")
        marker = " ◂" if focal and row["catchment_name"] == focal else ""
        lines.append(f"| {row['catchment_name']}{marker} | " + " | ".join(cells) + " |")

    for heading, changes in tables:
        county = changes["county_change_pct"][0]
        lines += [
            "",
            f"## Outsized movers: {heading}",
            "",
            f"The typical catchment changed by **{county:+.1f}%** in nominal terms.",
            "`Excess` is each catchment's change less that figure, in percentage points.",
            "",
            "| Catchment | Change | Excess |",
            "|---|---:|---:|",
        ]
        for row in changes.iter_rows(named=True):
            marker = " ◂" if focal and row["catchment_name"] == focal else ""
            lines.append(
                f"| {row['catchment_name']}{marker} | {row['change_pct']:+.1f}% | "
                f"{row['excess_change_pct']:+.1f} pp |"
            )

    path = OUTPUTS / f"period_comparison_{spec.key}.md"
    path.write_text("\n".join(lines) + "\n")
    print(f"Wrote {path}")


if __name__ == "__main__":
    raise SystemExit(main())
