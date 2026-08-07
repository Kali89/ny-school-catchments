"""Postcode centroids from the ONS Postcode Directory.

Two traps in ONSPD are handled here, both of which fail silently if ignored
(documented in the sibling asylum-site project, which hit both):

1. **Northern Ireland coordinates are Irish Grid**, held in the same unlabelled
   easting/northing columns as the British National Grid ones. Read as BNG they
   land roughly 250km away *together*, forming a plausible-looking cluster rather
   than obvious outliers. Filtered out by country code.
2. **The null-island sentinel.** Postcodes with no grid reference carry
   `lat = 99.999999`, `long = 0.0` and `gridind = 9`. Dropped and counted.

Terminated postcodes are deliberately *retained*: a house sold in 1998 may sit in
a postcode that no longer exists, and filtering to "live today" would silently
drop those sales.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import polars as pl

from .config import ONSPD_ZIP

# Column positions are stable within an ONSPD release but not across releases,
# so select by name.
_COLUMNS = ["pcds", "east1m", "north1m", "gridind", "ctry25cd", "lsoa21cd", "imd20ind"]

# ONS country codes: E=England, W=Wales, S=Scotland, N=Northern Ireland.
# Price Paid covers England and Wales only, and NI carries Irish Grid coordinates,
# so both reasons point the same way.
_KEEP_COUNTRIES = ("E92000001", "W92000004")

# Grid indicator 9 marks "no grid reference held" — the null-island sentinel.
_NO_GRID_REFERENCE = "9"


def normalise_postcode(expr: pl.Expr) -> pl.Expr:
    """Reduce a postcode to a comparable key.

    ONSPD, Price Paid and EPC all space postcodes differently. Stripping all
    whitespace and uppercasing gives a key that survives the difference.

    Args:
        expr: A string expression holding a postcode.

    Returns:
        The normalised expression.
    """
    return expr.str.replace_all(r"\s+", "").str.to_uppercase()


def build_postcode_lookup(
    bbox: tuple[float, float, float, float],
    zip_path: Path | str = ONSPD_ZIP,
) -> pl.DataFrame:
    """Read postcode centroids inside a bounding box.

    ONSPD ships split by postcode area (one CSV per "YO", "HG", …). Every file is
    scanned rather than guessing which areas matter — the bounding box is the
    filter, so a catchment straddling an area boundary cannot be missed.

    Args:
        bbox: (min_easting, min_northing, max_easting, max_northing) in EPSG:27700.
        zip_path: The ONSPD archive.

    Returns:
        A DataFrame of postcode_key, easting, northing, lsoa21cd, imd20ind.

    Raises:
        FileNotFoundError: If the archive is absent.
    """
    zip_path = Path(zip_path)
    if not zip_path.exists():
        raise FileNotFoundError(
            f"ONSPD archive not found at {zip_path}. "
            "Set NY_CATCHMENTS_MIRROR or see data/README.md."
        )

    min_e, min_n, max_e, max_n = bbox
    frames: list[pl.DataFrame] = []

    with zipfile.ZipFile(zip_path) as archive:
        members = [
            name
            for name in archive.namelist()
            if name.startswith("Data/multi_csv/") and name.lower().endswith(".csv")
        ]
        for member in members:
            with archive.open(member) as handle:
                raw = pl.read_csv(
                    io.BytesIO(handle.read()),
                    columns=_COLUMNS,
                    schema_overrides={
                        "east1m": pl.Float64,
                        "north1m": pl.Float64,
                        "gridind": pl.Utf8,
                        "imd20ind": pl.Float64,
                    },
                    ignore_errors=True,
                )
            kept = raw.filter(
                pl.col("ctry25cd").is_in(_KEEP_COUNTRIES)
                & (pl.col("gridind") != _NO_GRID_REFERENCE)
                & pl.col("east1m").is_not_null()
                & pl.col("north1m").is_not_null()
                & pl.col("east1m").is_between(min_e, max_e)
                & pl.col("north1m").is_between(min_n, max_n)
            )
            if kept.height:
                frames.append(kept)

    if not frames:
        # An empty reference set must fail loudly rather than silently matching
        # nothing downstream.
        raise ValueError(
            f"No postcodes found inside bbox {bbox}. Check the bounding box CRS "
            "— it must be EPSG:27700 eastings/northings, not degrees."
        )

    combined = pl.concat(frames)
    return (
        combined.with_columns(normalise_postcode(pl.col("pcds")).alias("postcode_key"))
        .select(
            "postcode_key",
            pl.col("east1m").alias("easting"),
            pl.col("north1m").alias("northing"),
            "lsoa21cd",
            "imd20ind",
        )
        .unique(subset="postcode_key", keep="first")
    )
