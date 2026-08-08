#!/usr/bin/env python
"""What do the sharp price divides inside catchments actually sit on?

Separates two explanations for a gap between neighbouring areas:

    composition — one side is new detached housing, the other older terraces
    location    — the same kind of house is worth more on one side of a line

then asks, for the divides that survive the composition adjustment, what
physical feature lies between the two areas.

Usage:
    uv run python scripts/analyse_divides.py --layer secondary --top 12
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import polars as pl

from ny_catchments.config import DATA_INTERIM, LAYERS, OUTPUTS
from ny_catchments.divides import (
    adjusted_contrasts,
    describe_divide,
    hedonic_r2,
    hedonic_residuals,
    lsoa_composition,
    variance_by_level,
)
from ny_catchments.inequality import (
    lsoa_adjacency,
    lsoa_profile,
    neighbouring_contrasts,
    sharpest_divides,
)
from ny_catchments.osm import (
    bbox_wgs84,
    closest_sales_seam,
    fetch_features,
    separating_features,
)
from ny_catchments.periods import RECENT, assign_periods


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--layer", choices=sorted(LAYERS), default="secondary")
    parser.add_argument("--top", type=int, default=12,
                        help="How many divides to look up in OSM (default: %(default)s).")
    parser.add_argument("--skip-osm", action="store_true")
    args = parser.parse_args()

    spec = LAYERS[args.layer]
    source = DATA_INTERIM / f"transactions_{spec.key}_with_epc.parquet"
    if not source.exists():
        print(f"{source} not found — run the build stages first.", file=sys.stderr)
        return 1

    transactions = assign_periods(pl.read_parquet(source))
    recent = transactions.filter(pl.col("period") == RECENT.key)

    residualised = hedonic_residuals(recent)
    r2 = hedonic_r2(residualised)
    print(
        f"Hedonic on property type, new-build and tenure explains "
        f"{r2:.1%} of log £/m² variance ({residualised.height:,} sales)"
    )

    profile = lsoa_profile(residualised)
    adjacency = lsoa_adjacency(residualised)
    contrasts = neighbouring_contrasts(profile, adjacency)
    composition = lsoa_composition(residualised)
    adjusted = adjusted_contrasts(contrasts, composition)

    if adjusted.height == 0:
        print("No divides survived the join to composition.", file=sys.stderr)
        return 1

    # One row per catchment, its sharpest divide once composition is removed.
    per_catchment = (
        adjusted.sort("adjusted_ratio", descending=True)
        .group_by("catchment_name", maintain_order=True)
        .first()
    )
    print(f"{adjusted.height} neighbouring pairs · {per_catchment.height} catchments")

    raw_top = sharpest_divides(contrasts).head(5)["catchment_name"].to_list()
    adj_top = per_catchment.head(5)["catchment_name"].to_list()
    print(f"\nTop 5 by raw gap:      {[n[:34] for n in raw_top]}")
    print(f"Top 5 by adjusted gap: {[n[:34] for n in adj_top]}")

    seams = []
    if not args.skip_osm:
        cache = DATA_INTERIM / "osm_cache"
        print(f"\nLooking up what sits between the top {args.top} divides…")
        for row in per_catchment.head(args.top).iter_rows(named=True):
            try:
                seam, endpoints = closest_sales_seam(
                    residualised, row["richer_lsoa"], row["poorer_lsoa"]
                )
                response = fetch_features(bbox_wgs84(*endpoints), cache_dir=cache)
                features = separating_features(seam, response)
            except Exception as exc:  # noqa: BLE001 - one bad lookup must not stop the run
                print(f"  ! {row['catchment_name'][:40]}: {exc}")
                seams.append({**row, "features": [], "error": str(exc)})
                continue

            label = (
                ", ".join(
                    f"{f['feature_class']}"
                    + (f" ({f['name']})" if f["name"] else "")
                    for f in features
                )
                or "nothing — the two run straight into each other"
            )
            print(
                f"  {row['catchment_name'][:36]:38s} "
                f"{row['adjusted_ratio']:.2f}x  {label}"
            )
            seams.append({**row, "features": features, "error": None})

    levels = variance_by_level(recent)
    print("\nWhere the price variation lives:")
    for row in levels.iter_rows(named=True):
        print(
            f"  between {row['level']:16s} ({row['n_groups']:3d} groups): "
            f"{row['between_share']:.1%}"
        )

    _write_report(spec, r2, per_catchment, adjusted, seams, levels)
    return 0


def _write_report(spec, r2, per_catchment, adjusted, seams, levels) -> None:
    """Write the divide anatomy report."""
    lines = [
        f"# What the price divides inside {spec.phase_label.lower()} catchments sit on",
        "",
        f"North Yorkshire · {RECENT.label.lower()} ({RECENT.span_label}).",
        "",
        "## The question",
        "",
        "A gap in price per m² between two neighbouring areas has two very different",
        "possible causes, and the raw figure cannot tell them apart:",
        "",
        "- **Composition** — one side is a new estate of detached houses, the other is",
        "  Victorian terraces. Dividing by floor area removes the size effect but",
        "  nothing else.",
        "- **Location** — the same kind of house is worth more on one side of a line.",
        "",
        "To separate them, log price per m² is regressed on property type, new-build",
        "status and tenure across the whole county, and the divides are recomputed on",
        f"the residuals. Those controls explain **{r2:.1%}** of the variance.",
        "",
        "**What this cannot claim.** Those three are the only stock characteristics",
        "Price Paid carries. A surviving gap means 'not explained by type, age-at-sale",
        "or tenure' — not 'not explained by the housing'. Build quality, plot size,",
        "garages and condition are all absent and all price-relevant.",
        "",
        "## Divides, before and after adjusting for housing stock",
        "",
        "| Catchment | Raw gap | Adjusted gap | Explained by stock | What it is |",
        "|---|---:|---:|---:|---|",
    ]
    for row in per_catchment.iter_rows(named=True):
        lines.append(
            f"| {row['catchment_name']} | {row['price_ratio']:.2f}× | "
            f"{row['adjusted_ratio']:.2f}× | {row['share_explained']:.0%} | "
            f"{describe_divide(row)} |"
        )

    if seams:
        lines += [
            "",
            "## What lies between them",
            "",
            "A feature counts only if it crosses the segment joining the two closest",
            "sales, one from each side — the shortest path between the two populations.",
            "A road running *through* both areas is not a divide; one running *between*",
            "them is.",
            "",
            "| Catchment | Adjusted gap | Apart | What sits on the seam |",
            "|---|---:|---:|---|",
        ]
        for entry in seams:
            if entry.get("error"):
                what = f"lookup failed: {entry['error'][:60]}"
            elif entry["features"]:
                what = ", ".join(
                    f["feature_class"] + (f" ({f['name']})" if f["name"] else "")
                    for f in entry["features"]
                )
            else:
                what = "nothing — the two run straight into each other"
            lines.append(
                f"| {entry['catchment_name']} | {entry['adjusted_ratio']:.2f}× | "
                f"{entry['min_distance_m']:,.0f} m | {what} |"
            )
        lines += [
            "",
            "Feature data © OpenStreetMap contributors, under the Open Database Licence.",
        ]

    def share(level: str) -> float:
        return levels.filter(pl.col("level") == level)["between_share"][0]

    between_catchment = share("catchment_name")
    between_postcode = share("postcode_key")

    lines += [
        "",
        "## What this implies for redrawing boundaries",
        "",
        "A boundary can only reallocate variation lying *between* the units it",
        "follows. It cannot separate two houses inside a unit it never cuts — so the",
        "ceiling depends on **the grain at which lines may be drawn**, which is a",
        "choice, not a fact about the data.",
        "",
        "| Grain | Groups | Mean sales/group | Raw | Noise-corrected |",
        "|---|---:|---:|---:|---:|",
    ]
    labels = {
        "catchment_name": "Catchments as drawn today",
        "lsoa21cd": "LSOA-shaped boundaries",
        "postcode_key": "Postcode-shaped boundaries",
    }
    for row in levels.iter_rows(named=True):
        lines += [
            (
                f"| {labels.get(row['level'], row['level'])} | {row['n_groups']:,} | "
                f"{row['mean_group_size']:.0f} | {row['between_share_raw']:.1%} | "
                f"**{row['between_share']:.1%}** |"
            )
        ]
    lines += [
        "",
        "**An LSOA is not an atom.** It is a statistical area, and a catchment",
        "boundary can and does run straight through one. The LSOA row therefore",
        "bounds only LSOA-shaped boundaries — it is not a limit on boundaries in",
        "general, and reading it as one understates the available freedom badly.",
        "",
        "**The noise correction is not a detail either.** With a handful of sales per",
        "group the group means are noisy, and that noise inflates the raw share — a",
        "partition into singletons would score 100% while explaining nothing. The",
        "corrected column is the one-way random-effects estimate.",
        "",
        (
            f"Taking postcodes as the practical grain, the headroom between today's "
            f"{between_catchment:.0%} and the {between_postcode:.0%} ceiling is about "
            f"{100 * (between_postcode - between_catchment):.0f} points of total "
            f"variation."
        ),
        "",
        "**That ceiling is for an unconstrained partition** — any postcode assigned",
        "to any school. Requiring each catchment to be contiguous, within a travel",
        "distance of its school, and to match school capacity will cut it, probably",
        "a long way. By how much is an empirical question this repo has not answered,",
        "and it cannot be reasoned out from these numbers.",
        "",
        "**The direction of the objective matters more than the optimisation.**",
        "Minimising inequality *within* each catchment means making each one",
        "internally uniform — which maximises the differences *between* catchments.",
        "That is a design for segregated intakes, and it is the opposite of what",
        "most people mean when they ask for fairer boundaries. Maximising within-",
        "catchment mix is a coherent objective too, and points the other way.",
        "Whichever is chosen has to be stated before any optimisation is run,",
        "because the same solver produces opposite maps from the two.",
        "",
        "Neither is a free choice in practice: catchments also have to respect school",
        "capacity, travel distance and contiguity, none of which is modelled here.",
        "",
        "## Composition detail",
        "",
        "| Catchment | Detached R/P | Terraced R/P | New-build R/P | Median m² R/P |",
        "|---|---:|---:|---:|---:|",
    ]
    for row in per_catchment.iter_rows(named=True):
        lines.append(
            f"| {row['catchment_name']} | "
            f"{row['share_detached_richer']:.0%} / {row['share_detached_poorer']:.0%} | "
            f"{row['share_terraced_richer']:.0%} / {row['share_terraced_poorer']:.0%} | "
            f"{row['share_newbuild_richer']:.0%} / {row['share_newbuild_poorer']:.0%} | "
            f"{row['median_floor_area_m2_richer']:,.0f} / "
            f"{row['median_floor_area_m2_poorer']:,.0f} |"
        )

    path = OUTPUTS / f"divide_anatomy_{spec.key}.md"
    path.write_text("\n".join(lines) + "\n")
    print(f"\nWrote {path}")


if __name__ == "__main__":
    raise SystemExit(main())
