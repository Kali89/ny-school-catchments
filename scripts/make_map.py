#!/usr/bin/env python
"""Render a school catchment map centred on Great Ouseburn.

Usage:
    uv run python scripts/make_map.py                    # primary (the goal)
    uv run python scripts/make_map.py --layer secondary  # secondary stand-in
    uv run python scripts/make_map.py --radius-m 8000

Exits non-zero with an actionable message if the layer's geometry is missing.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ny_catchments.config import DEFAULT_RADIUS_M, LAYERS, OUTPUTS
from ny_catchments.io import MissingGeometryError, load_catchments
from ny_catchments.plot import plot_catchments

STAND_IN_NOTE = (
    "STAND-IN: showing SECONDARY catchments — the primary layer's .shp "
    "(geometry) was not supplied by NYC."
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--layer", choices=sorted(LAYERS), default="primary")
    parser.add_argument("--radius-m", type=float, default=DEFAULT_RADIUS_M)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    spec = LAYERS[args.layer]

    try:
        gdf = load_catchments(spec)
    except MissingGeometryError as exc:
        print(f"\n{exc}\n", file=sys.stderr)
        if args.layer == "primary":
            print(
                "  In the meantime you can see the pipeline working with:\n"
                "      uv run python scripts/make_map.py --layer secondary\n",
                file=sys.stderr,
            )
        return 1

    fig = plot_catchments(
        gdf,
        spec,
        radius_m=args.radius_m,
        stand_in_note=STAND_IN_NOTE if args.layer == "secondary" else None,
    )

    OUTPUTS.mkdir(parents=True, exist_ok=True)
    out_path = args.out or OUTPUTS / f"catchments_{spec.key}_great_ouseburn.png"
    fig.savefig(out_path, dpi=200, bbox_inches="tight", facecolor=fig.get_facecolor())
    print(f"Wrote {out_path}")
    print(f"  {len(gdf)} {spec.phase_label.lower()} catchments in layer")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
