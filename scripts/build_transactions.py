#!/usr/bin/env python
"""Build the located, catchment-assigned transaction table.

Stages:
    1. Load the catchment layer and take its bounding box.
    2. Pull postcode centroids inside that box from ONSPD.
    3. Stream Price Paid for those postcodes since the cutoff year.
    4. Attach coordinates, then assign each sale to a catchment.

Writes `data/interim/transactions_<layer>.parquet` (gitignored — this is an
address-level extract and must not be published; only aggregates may be).

Usage:
    uv run python scripts/build_transactions.py --layer secondary --years 5
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import polars as pl

from ny_catchments.config import (
    BBOX_PAD_M,
    DATA_INTERIM,
    DEFAULT_YEARS,
    LAYERS,
)
from ny_catchments.io import assign_catchments, load_catchments
from ny_catchments.postcodes import build_postcode_lookup
from ny_catchments.prices import load_transactions


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--layer", choices=sorted(LAYERS), default="secondary")
    parser.add_argument(
        "--years",
        type=int,
        default=DEFAULT_YEARS,
        help="Trailing window in whole years (default: %(default)s).",
    )
    parser.add_argument("--reference-year", type=int, default=2026)
    args = parser.parse_args()

    spec = LAYERS[args.layer]
    since_year = args.reference_year - args.years

    print(f"[1/4] Loading {spec.phase_label.lower()} catchments…")
    catchments = load_catchments(spec)
    min_e, min_n, max_e, max_n = catchments.total_bounds
    bbox = (
        min_e - BBOX_PAD_M,
        min_n - BBOX_PAD_M,
        max_e + BBOX_PAD_M,
        max_n + BBOX_PAD_M,
    )
    print(f"      {len(catchments)} catchments; bbox {tuple(round(v) for v in bbox)}")

    print("[2/4] Reading ONSPD postcode centroids…")
    postcodes = build_postcode_lookup(bbox)
    print(f"      {postcodes.height:,} postcodes in box")

    print(f"[3/4] Streaming Price Paid since {since_year}…")
    transactions = load_transactions(postcodes["postcode_key"], since_year)
    print(f"      {transactions.height:,} transactions matched")

    print("[4/4] Assigning to catchments…")
    located = transactions.join(postcodes, on="postcode_key", how="inner")
    assigned = assign_catchments(located, catchments)
    dropped = located.height - assigned.height
    print(
        f"      {assigned.height:,} inside a catchment "
        f"({dropped:,} in the bounding box but outside every catchment)"
    )

    DATA_INTERIM.mkdir(parents=True, exist_ok=True)
    out = DATA_INTERIM / f"transactions_{spec.key}.parquet"
    assigned.write_parquet(out)
    print(f"\nWrote {out}")

    summary = (
        assigned.group_by("catchment_name")
        .agg(pl.len().alias("n"))
        .sort("n", descending=True)
    )
    print(f"\nTop catchments by transaction count:\n{summary.head(5)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
