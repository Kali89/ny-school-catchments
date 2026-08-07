"""Project configuration: paths, CRS handling, and the map's focal point.

The two shapefiles supplied by North Yorkshire Council need different handling,
so each layer carries its own spec rather than relying on GDAL autodetection.
See `LayerSpec.crs` for why the CRS must be stated explicitly.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# Repo root, resolved from this file so scripts work from any working directory.
REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_RAW = REPO_ROOT / "data" / "raw"
DATA_INTERIM = REPO_ROOT / "data" / "interim"
OUTPUTS = REPO_ROOT / "outputs"

# National reference data already downloaded for the sibling asylum-site study.
# Treated as a strictly read-only local mirror of public sources — nothing in this
# project writes there. Override with NY_CATCHMENTS_MIRROR if the data moves.
MIRROR = Path(
    os.environ.get("NY_CATCHMENTS_MIRROR", "/Users/matt/src/asylum-site-local-impacts/data/raw")
)
ONSPD_ZIP = MIRROR / "onspd" / "ONSPD_MAY_2026.zip"
PRICE_PAID_CSV = MIRROR / "land_registry" / "pp-complete.csv"
EPC_ZIP = MIRROR / "epc" / "domestic-csv.zip"

# British National Grid. All plotting happens in this CRS so that distances and
# the scale bar are in metres rather than degrees.
BNG = "EPSG:27700"


@dataclass(frozen=True)
class LayerSpec:
    """A single catchment layer as delivered by North Yorkshire Council.

    Attributes:
        key: Short name used on the command line (e.g. "primary").
        stem: Filename stem shared by the .shp/.shx/.dbf sidecar set.
        crs: CRS to assign to the geometry after reading.

            This is stated explicitly and deliberately. NYC supplied the
            projection sidecars named `.prj.txt`, not `.prj`, so GDAL does not
            pick them up and the layers load with no CRS at all. Rather than
            renaming the user's files, we assign the CRS from the sidecar's
            documented contents:
              - Secondary: British_National_Grid (EPSG:27700).
              - Primary:   "MapInfo Generic Lat/Long" on a WGS84 spheroid,
                           which is EPSG:4326 for practical purposes.
        name_field: .dbf column holding the school name.
        phase_label: Human-readable phase, used in map titles.
    """

    key: str
    stem: str
    crs: str
    name_field: str
    phase_label: str

    @property
    def shp_path(self) -> Path:
        return DATA_RAW / f"{self.stem}.shp"


PRIMARY = LayerSpec(
    key="primary",
    stem="250901 nh Primary named catchments region",
    crs="EPSG:4326",
    name_field="SchoolName",
    phase_label="Primary",
)

SECONDARY = LayerSpec(
    key="secondary",
    stem="250207 Synergy areas Secondary update July 2025 region",
    crs=BNG,
    name_field="SchoolName",
    phase_label="Secondary",
)

LAYERS = {spec.key: spec for spec in (PRIMARY, SECONDARY)}

# Great Ouseburn Community Primary School, URN 121393, postcode YO26 9RG.
# Easting/Northing taken from the DfE "Get Information About Schools" extract
# (edubasealldata, 2026-05-01), which publishes coordinates in British National Grid.
FOCUS_SCHOOL_NAME = "Great Ouseburn Community Primary School"
FOCUS_SCHOOL_URN = 121393
FOCUS_EASTING = 444791.0
FOCUS_NORTHING = 461825.0

# Half-width of the map window in metres. 12km comfortably contains the
# neighbouring villages without shrinking Great Ouseburn to a speck.
DEFAULT_RADIUS_M = 12_000.0

# --- Price Paid extract parameters ---

# Trailing window, in years, for the "recent sales" summary.
DEFAULT_YEARS = 5

# Price Paid "property type": D=detached, S=semi, T=terraced, F=flat/maisonette,
# O=other. O is excluded — it is overwhelmingly non-residential or otherwise
# atypical, and it carries no floor area worth speaking of.
RESIDENTIAL_TYPES = ("D", "S", "T", "F")

# PPD category A is a standard full-market-value sale at arm's length.
# Category B covers repossessions, buy-to-let portfolios and transfers that are
# not open-market prices, so it is excluded throughout.
PPD_CATEGORY = "A"

# Padding around the catchment layer when selecting postcodes, in metres.
# Generous: a postcode centroid can sit outside a catchment whose houses are in it.
BBOX_PAD_M = 2_000.0
