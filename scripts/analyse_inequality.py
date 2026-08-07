#!/usr/bin/env python
"""Measure inequality within catchments and locate rich/poor neighbours.

Produces:
    inequality_ranking_<layer>.png      P90/P10 per catchment
    inequality_vs_price_<layer>.png     price level against inequality
    divided_catchments_<layer>.png      the sharpest adjacent contrasts
    inequality_<layer>.md               the numbers behind all three

Usage:
    uv run python scripts/analyse_inequality.py --layer secondary
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import polars as pl

from ny_catchments.config import LAYERS, OUTPUTS
from ny_catchments.inequality import (
    ADJACENCY_M,
    MIN_CATCHMENT_SALES,
    MIN_LSOA_SALES,
    catchment_inequality,
    decompose_dispersion,
    lsoa_adjacency,
    lsoa_profile,
    neighbouring_contrasts,
    sharpest_divides,
)
from ny_catchments.io import load_catchments
from ny_catchments.periods import RECENT, assign_periods
from ny_catchments.plot_inequality import (
    plot_divided_catchments,
    plot_inequality_ranking,
    plot_inequality_vs_price,
)

STAND_IN_NOTE = (
    "STAND-IN: SECONDARY catchments — the primary layer's .shp was not supplied by NYC."
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--layer", choices=sorted(LAYERS), default="secondary")
    parser.add_argument("--panels", type=int, default=4)
    args = parser.parse_args()

    spec = LAYERS[args.layer]
    source = Path("data/interim") / f"transactions_{spec.key}_with_epc.parquet"
    if not source.exists():
        print(f"{source} not found — run the build stages first.", file=sys.stderr)
        return 1

    transactions = assign_periods(pl.read_parquet(source))
    recent = transactions.filter(pl.col("period") == RECENT.key)
    print(f"{recent.height:,} sales in {RECENT.span_label}")

    inequality = catchment_inequality(recent)
    profile = lsoa_profile(recent)
    adjacency = lsoa_adjacency(recent)
    contrasts = neighbouring_contrasts(profile, adjacency)
    divides = sharpest_divides(contrasts)
    decomposition = decompose_dispersion(recent, profile)

    print(
        f"{inequality.height} catchments · {profile.height} neighbourhoods · "
        f"{adjacency.height} adjacent pairs · {contrasts.height} within a catchment"
    )

    focal = "Boroughbridge High School"
    note = STAND_IN_NOTE if spec.key == "secondary" else None
    OUTPUTS.mkdir(parents=True, exist_ok=True)

    price_inequality_corr = inequality.select(
        pl.corr("median_price_per_m2", "p90_p10", method="spearman")
    ).item()
    print(f"Spearman, median £/m² vs P90/P10: {price_inequality_corr:+.3f}")

    figures = [
        (
            plot_inequality_ranking(inequality, focal_catchment=focal, stand_in_note=note),
            f"inequality_ranking_{spec.key}.png",
        ),
        (
            plot_inequality_vs_price(
                inequality, decomposition, price_inequality_corr,
                focal_catchment=focal, stand_in_note=note,
            ),
            f"inequality_vs_price_{spec.key}.png",
        ),
        (
            plot_divided_catchments(
                load_catchments(spec), profile, divides,
                n_panels=args.panels, stand_in_note=note,
            ),
            f"divided_catchments_{spec.key}.png",
        ),
    ]
    for fig, filename in figures:
        path = OUTPUTS / filename
        fig.savefig(path, dpi=200, bbox_inches="tight", facecolor=fig.get_facecolor())
        print(f"Wrote {path}")

    _write_report(spec, inequality, decomposition, divides, contrasts, profile)
    return 0


def _write_report(spec, inequality, decomposition, divides, contrasts, profile) -> None:
    """Write the numbers behind the inequality figures."""
    merged = inequality.join(decomposition, on="catchment_name", how="left")

    # Do price and deprivation agree? They measure different things — what a
    # house costs versus how deprived the people living around it are — and
    # where they disagree is worth knowing before either is used as a proxy.
    usable = profile.drop_nulls(["median_price_per_m2", "imd_rank"])
    correlation = usable.select(
        pl.corr("median_price_per_m2", "imd_rank", method="spearman")
    ).item()

    lines = [
        f"# Inequality within {spec.phase_label.lower()} school catchments",
        "",
        f"North Yorkshire · {RECENT.label.lower()} ({RECENT.span_label}).",
        "",
        "## What is measured",
        "",
        "**P90/P10** — the 90th percentile of price per m² divided by the 10th.",
        "Read it as: the top tenth of homes cost this many times more per square",
        "metre than the bottom tenth. Preferred over Gini as a headline because it",
        "survives these sample sizes better and states itself in a sentence.",
        "",
        "**Between-neighbourhood share** — how much of a catchment's price variation",
        "sits *between* its LSOAs rather than within them, from a variance",
        "decomposition on log price per m². A high share means distinct richer and",
        "poorer neighbourhoods; a low share means the variation is mixed in street",
        "by street. This is the measure that separates 'unequal' from 'divided'.",
        "",
        "**Adjacency** — two neighbourhoods count as next to each other when they",
        f"contain postcodes within {ADJACENCY_M:,.0f}m. Boundary contiguity was not",
        "used deliberately: two rural LSOAs can share a long boundary across open",
        "moorland while the places people actually live are kilometres apart.",
        "",
        (
            f"Thresholds: {MIN_CATCHMENT_SALES} priced sales for a catchment, "
            f"{MIN_LSOA_SALES} for a neighbourhood."
        ),
        "",
        "## Price and deprivation are not the same axis",
        "",
        "Spearman correlation between a neighbourhood's median £/m² and its IMD 2020",
        f"rank is **{correlation:+.2f}** (rank 1 = most deprived in England, so a",
        "positive figure means pricier areas are less deprived).",
        "",
        "Where the two disagree, the tables below show it: `IMD gap` is positive when",
        "the pricier side of a divide is also the less deprived one, and negative when",
        "it is not.",
        "",
        "## Most divided: sharpest gap between adjacent neighbourhoods",
        "",
        "| Catchment | Richer | Poorer | Gap | Apart | IMD gap |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in divides.head(15).iter_rows(named=True):
        lines.append(
            f"| {row['catchment_name']} | £{row['richer_ppm2']:,.0f} | "
            f"£{row['poorer_ppm2']:,.0f} | {row['price_ratio']:.2f}× | "
            f"{row['min_distance_m']:,.0f} m | {row['imd_gap']:+,.0f} |"
        )

    lines += [
        "",
        "## Inequality by catchment",
        "",
        "| Catchment | Sales | Median £/m² | P90/P10 | Gini | Between-neighbourhood |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in merged.iter_rows(named=True):
        share = row["between_share"]
        lines.append(
            f"| {row['catchment_name']} | {row['n_priced']:,} | "
            f"£{row['median_price_per_m2']:,.0f} | {row['p90_p10']:.2f}× | "
            f"{row['gini_ppm2']:.3f} | "
            f"{'—' if share is None else f'{share:.0%}'} |"
        )

    lines += [
        "",
        "## All adjacent contrasts above 1.3×",
        "",
        "| Catchment | Richer | Poorer | Gap | Apart |",
        "|---|---:|---:|---:|---:|",
    ]
    for row in contrasts.filter(pl.col("price_ratio") >= 1.3).iter_rows(named=True):
        lines.append(
            f"| {row['catchment_name']} | £{row['richer_ppm2']:,.0f} | "
            f"£{row['poorer_ppm2']:,.0f} | {row['price_ratio']:.2f}× | "
            f"{row['min_distance_m']:,.0f} m |"
        )

    path = OUTPUTS / f"inequality_{spec.key}.md"
    path.write_text("\n".join(lines) + "\n")
    print(f"Wrote {path}")


if __name__ == "__main__":
    raise SystemExit(main())
