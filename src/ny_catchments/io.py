"""Loading the North Yorkshire catchment layers.

A shapefile is really a set of sidecar files. The geometry lives in `.shp`, the
index in `.shx`, and the attributes in `.dbf`. All three must be present. This
module checks for them up front so that a missing sidecar produces an actionable
message rather than a GDAL error thirty frames deep.
"""

from __future__ import annotations

import geopandas as gpd
import polars as pl

from .config import BNG, LayerSpec

# Sidecars that must exist for a shapefile to be readable at all.
_REQUIRED_SUFFIXES = (".shp", ".shx", ".dbf")

# Canonical school-name column exposed to callers, regardless of source casing.
NAME_FIELD = "school_name"


def _resolve_field(gdf: gpd.GeoDataFrame, wanted: str) -> str:
    """Find `wanted` among the frame's columns, ignoring case.

    Args:
        gdf: The frame just read from disk.
        wanted: The expected column name.

    Returns:
        The actual column name as it appears in the frame.

    Raises:
        KeyError: If no case-insensitive match exists.
    """
    lookup = {col.casefold(): col for col in gdf.columns}
    try:
        return lookup[wanted.casefold()]
    except KeyError:
        raise KeyError(
            f"No column matching {wanted!r} (case-insensitive) in layer; "
            f"found {list(gdf.columns)}"
        ) from None


class MissingGeometryError(FileNotFoundError):
    """Raised when a layer's sidecar set is incomplete."""


def check_layer_files(spec: LayerSpec) -> None:
    """Verify the shapefile sidecar set is complete.

    Args:
        spec: The layer to check.

    Raises:
        MissingGeometryError: If any of .shp/.shx/.dbf is absent, with a message
            naming what is missing and what to do about it.
    """
    missing = [
        suffix
        for suffix in _REQUIRED_SUFFIXES
        if not spec.shp_path.with_suffix(suffix).exists()
    ]
    if not missing:
        return

    lines = [
        (
            f"Cannot read the {spec.phase_label.lower()} catchment layer: "
            f"missing {', '.join(missing)}."
        ),
        f"  Expected next to: {spec.shp_path}",
    ]
    if ".shp" in missing:
        lines += [
            "",
            "  The .shp file holds the boundary coordinates themselves. Without it",
            "  there is no geometry to draw — the .dbf (school names) and .shx",
            "  (record index) alone cannot reconstruct the polygons.",
            "",
            "  Go back to North Yorkshire Council and ask for the .shp to be included.",
        ]
    raise MissingGeometryError("\n".join(lines))


def load_catchments(spec: LayerSpec) -> gpd.GeoDataFrame:
    """Read a catchment layer and return it in British National Grid.

    Assigns the CRS explicitly (see `LayerSpec.crs` for why autodetection fails),
    drops any Z coordinate, and reprojects to BNG so downstream distances are in
    metres.

    Args:
        spec: The layer to load.

    Returns:
        A GeoDataFrame in EPSG:27700 with 2D geometry, indexed as read.

    Raises:
        MissingGeometryError: If the sidecar set is incomplete.
    """
    check_layer_files(spec)

    gdf = gpd.read_file(spec.shp_path)

    # NYC's field casing differs between layers ("SchoolName" in the primary .dbf,
    # "Schoolname" in the secondary), so resolve it case-insensitively and expose a
    # single canonical column downstream.
    gdf = gdf.rename(columns={_resolve_field(gdf, spec.name_field): NAME_FIELD})

    # The .prj.txt sidecar is invisible to GDAL, so the layer arrives with no CRS.
    # Assign the documented one, then reproject.
    if gdf.crs is None:
        gdf = gdf.set_crs(spec.crs)
    gdf = gdf.to_crs(BNG)

    # These layers are PolygonZ; the Z is a MapInfo artefact and is not meaningful.
    gdf.geometry = gdf.geometry.force_2d()

    # Guard against invalid rings, which are common in exported catchment data and
    # otherwise cause clipping to fail silently.
    invalid = ~gdf.geometry.is_valid
    if invalid.any():
        gdf.loc[invalid, "geometry"] = gdf.loc[invalid, "geometry"].buffer(0)

    return gdf


def assign_catchments(
    transactions: pl.DataFrame,
    catchments: gpd.GeoDataFrame,
) -> pl.DataFrame:
    """Attach the containing catchment to each transaction by point-in-polygon.

    Args:
        transactions: Must carry `easting` and `northing` columns in EPSG:27700.
        catchments: Catchment polygons in EPSG:27700, carrying NAME_FIELD.

    Returns:
        The transactions with `catchment_name` and `catchment_id` added. Rows
        falling outside every catchment are dropped — a postcode inside the
        bounding box is not necessarily inside a catchment.

    Raises:
        ValueError: If the catchment layer is not in EPSG:27700, since a join in
            degrees would silently produce nonsense.
    """
    if catchments.crs is None or catchments.crs.to_epsg() != 27700:
        raise ValueError(
            f"Catchments must be in EPSG:27700 for the spatial join, got {catchments.crs}"
        )

    points = gpd.GeoDataFrame(
        {"_row": range(transactions.height)},
        geometry=gpd.points_from_xy(
            transactions["easting"].to_list(),
            transactions["northing"].to_list(),
        ),
        crs=BNG,
    )

    polygons = catchments[[NAME_FIELD, "geometry"]].copy()
    polygons["catchment_id"] = polygons.index

    joined = gpd.sjoin(points, polygons, how="inner", predicate="within")

    # A point on a shared boundary can match two catchments. Keep the first
    # deterministically rather than double-counting the sale.
    joined = joined.sort_values(["_row", "catchment_id"]).drop_duplicates("_row")

    lookup = pl.DataFrame(
        {
            "_row": joined["_row"].to_numpy(),
            "catchment_name": joined[NAME_FIELD].astype(str).to_numpy(),
            "catchment_id": joined["catchment_id"].to_numpy(),
        }
    )

    return (
        transactions.with_row_index("_row")
        .join(lookup, on="_row", how="inner")
        .drop("_row")
    )
