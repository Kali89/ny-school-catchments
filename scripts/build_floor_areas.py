#!/usr/bin/env python
"""Attach EPC floor areas to the located transactions, giving price per m².

Reads `data/interim/transactions_<layer>.parquet`, pulls matching certificates
from the EPC archive, and rewrites the table with `floor_area_m2` and
`price_per_m2` columns.

This is the slow stage: the EPC archive expands to tens of GB and every yearly
file has to be decompressed to be filtered. Expect it to take a while.

Usage:
    uv run python scripts/build_floor_areas.py --layer secondary
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import polars as pl

from ny_catchments.config import DATA_INTERIM, LAYERS
from ny_catchments.epc import attach_floor_areas, composition_check, extract_floor_areas


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--layer", choices=sorted(LAYERS), default="secondary")
    parser.add_argument(
        "--refresh-epc",
        action="store_true",
        help="Rescan the EPC archive even if a cached extract exists.",
    )
    args = parser.parse_args()

    spec = LAYERS[args.layer]
    source = DATA_INTERIM / f"transactions_{spec.key}.parquet"
    if not source.exists():
        print(
            f"{source} not found — run scripts/build_transactions.py first.",
            file=sys.stderr,
        )
        return 1

    transactions = pl.read_parquet(source)
    postcodes = transactions["postcode_key"].unique()
    print(f"[1/3] {transactions.height:,} transactions across {postcodes.len():,} postcodes")

    # The archive scan dominates the runtime, and the address matching downstream
    # is the part worth iterating on, so the extract is cached.
    #
    # The cache is only valid for the postcodes it was built from. Widening the
    # date window pulls in postcodes that were not requested last time, and those
    # would come back unmatched with no error at all — the match rate would just
    # quietly sag. So coverage is checked, not assumed.
    cache = DATA_INTERIM / "epc_floor_areas.parquet"
    stale = False
    if cache.exists() and not args.refresh_epc:
        floor_areas = pl.read_parquet(cache)
        cached_postcodes = set(floor_areas["postcode_key"].unique().to_list())
        missing = set(postcodes.to_list()) - cached_postcodes
        # Postcodes with no certificate at all are legitimately absent, so a
        # small shortfall is expected. A large one means the window moved.
        if len(missing) > 0.05 * postcodes.len():
            stale = True
            print(
                f"[2/3] Cached extract covers {len(cached_postcodes):,} postcodes but "
                f"{len(missing):,} of {postcodes.len():,} requested are absent — rescanning."
            )
        else:
            print(f"[2/3] Reusing cached EPC extract ({cache.name}) — --refresh-epc to rescan")

    if not cache.exists() or args.refresh_epc or stale:
        print("      Scanning the EPC archive (slow — decompressing every yearly file)…")
        floor_areas = extract_floor_areas(postcodes)
        floor_areas.write_parquet(cache)
    print(f"      {floor_areas.height:,} distinct certified addresses")

    print("[3/3] Matching addresses…")
    enriched = attach_floor_areas(transactions, floor_areas)
    matched = enriched["floor_area_m2"].is_not_null().sum()
    rate = matched / enriched.height if enriched.height else 0.0
    print(f"      {matched:,} of {enriched.height:,} matched ({rate:.1%})")

    # Match rate by property type: flats matching far below houses is the known
    # failure mode of this join, so it is checked every run rather than assumed.
    by_type = (
        enriched.group_by("property_type")
        .agg(
            pl.len().alias("n"),
            pl.col("floor_area_m2").is_not_null().mean().alias("match_rate"),
        )
        .sort("property_type")
    )
    print(f"\nMatch rate by property type:\n{by_type}")

    # Where the matches came from. A rate resting mostly on the loosest key is
    # worth considerably less than the same rate resting on building+flat.
    tiers = (
        enriched.filter(pl.col("match_tier").is_not_null())
        .group_by("match_tier")
        .agg(pl.len().alias("n"))
        .sort("n", descending=True)
    )
    print(f"\nMatches by tier:\n{tiers}")

    # Is the matched sample representative? If matched sales differ from
    # unmatched ones, £/m² is computed on a different population than the mean
    # and median are.
    print(f"\nComposition, matched vs unmatched:\n{composition_check(enriched)}")

    out = DATA_INTERIM / f"transactions_{spec.key}_with_epc.parquet"
    enriched.write_parquet(out)
    print(f"\nWrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
