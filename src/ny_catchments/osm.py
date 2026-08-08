"""What physical feature, if any, lies between two neighbourhoods.

Queries OpenStreetMap through Overpass for the kinds of line that plausibly
divide a place — railways, trunk and primary roads, rivers — then tests which of
them actually separate the two areas rather than merely being nearby.

The separation test is deliberately strict. A road running *through* both
neighbourhoods is not a divide; a road running *between* them is. So a feature
counts only if it crosses the segment joining the two closest sales, one from
each side. That segment is the shortest path between the two populations, so
anything on it is genuinely in the way.

OpenStreetMap data is © OpenStreetMap contributors, available under the Open
Database Licence. Results are cached to disk: this hits a shared public endpoint,
and re-running an analysis should not re-query it.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import geopandas as gpd
import polars as pl
from shapely.geometry import LineString

from .config import BNG

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# Seconds to wait before each call. Overpass is a free shared service; hammering
# it is both rude and a quick way to be rate-limited. The pause is taken *before*
# the request, not after, so a failure does not lead straight into a retry.
REQUEST_PAUSE_S = 3.0

# 429 (rate limited) and 504 (the query timed out server-side) are both worth
# retrying after a wait; anything else is a real error and is raised.
RETRY_STATUSES = frozenset({429, 502, 503, 504})
MAX_ATTEMPTS = 4
BACKOFF_BASE_S = 8.0

# How far beyond the two points to search, in metres. Wide enough to catch a
# feature whose nodes sit outside the immediate gap.
SEARCH_PAD_M = 400.0

#: Feature classes tested, in the order they are reported. Each maps a label to
#: the Overpass filters that select it.
FEATURE_CLASSES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("railway", ('way["railway"~"^(rail|light_rail)$"]',)),
    (
        "major road",
        ('way["highway"~"^(motorway|trunk|primary)$"]',),
    ),
    (
        "secondary road",
        ('way["highway"="secondary"]',),
    ),
    ("river", ('way["waterway"~"^(river|canal)$"]',)),
    ("large green space", ('way["leisure"="park"]', 'way["landuse"="cemetery"]')),
)


def bbox_wgs84(
    easting_a: float,
    northing_a: float,
    easting_b: float,
    northing_b: float,
    pad_m: float = SEARCH_PAD_M,
) -> tuple[float, float, float, float]:
    """Bounding box around two BNG points, returned as WGS84 for Overpass.

    Args:
        easting_a: Easting of the first point.
        northing_a: Northing of the first point.
        easting_b: Easting of the second point.
        northing_b: Northing of the second point.
        pad_m: Padding in metres.

    Returns:
        (south, west, north, east) in degrees, the order Overpass expects.
    """
    corners = gpd.GeoSeries(
        gpd.points_from_xy(
            [min(easting_a, easting_b) - pad_m, max(easting_a, easting_b) + pad_m],
            [min(northing_a, northing_b) - pad_m, max(northing_a, northing_b) + pad_m],
        ),
        crs=BNG,
    ).to_crs("EPSG:4326")
    return (
        float(corners.y.min()),
        float(corners.x.min()),
        float(corners.y.max()),
        float(corners.x.max()),
    )


def fetch_features(
    bbox: tuple[float, float, float, float],
    cache_dir: Path,
    timeout_s: int = 90,
) -> dict:
    """Fetch dividing-line candidates in a bounding box, with disk caching.

    Args:
        bbox: (south, west, north, east) in WGS84 degrees.
        cache_dir: Directory for cached responses.
        timeout_s: Overpass query timeout.

    Returns:
        The parsed Overpass JSON response.

    Raises:
        RuntimeError: If Overpass returns something unparseable.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    key = "_".join(f"{v:.5f}" for v in bbox).replace(".", "p").replace("-", "m")
    cached = cache_dir / f"osm_{key}.json"
    if cached.exists():
        return json.loads(cached.read_text())

    selectors = "".join(
        f"{filt}({bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]});"
        for _, filters in FEATURE_CLASSES
        for filt in filters
    )
    query = f"[out:json][timeout:{timeout_s}];({selectors});out geom;"

    request = urllib.request.Request(
        OVERPASS_URL,
        data=urllib.parse.urlencode({"data": query}).encode(),
        headers={"User-Agent": "ny-school-catchments/0.1 (research; contact via repo)"},
    )

    last_error: Exception | None = None
    for attempt in range(MAX_ATTEMPTS):
        # Wait first, so a retry never follows a failure immediately.
        time.sleep(REQUEST_PAUSE_S if attempt == 0 else BACKOFF_BASE_S * 2**(attempt - 1))
        try:
            with urllib.request.urlopen(request, timeout=timeout_s + 30) as response:
                payload = response.read().decode()
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code not in RETRY_STATUSES:
                raise
            continue
        except (urllib.error.URLError, TimeoutError) as exc:
            last_error = exc
            continue

        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Overpass returned non-JSON: {payload[:200]}") from exc

        cached.write_text(json.dumps(parsed))
        return parsed

    raise RuntimeError(
        f"Overpass failed after {MAX_ATTEMPTS} attempts: {last_error}"
    ) from last_error


def _classify(tags: dict) -> str | None:
    """Map an OSM way's tags to one of the reported feature classes."""
    if tags.get("railway") in {"rail", "light_rail"}:
        return "railway"
    if tags.get("highway") in {"motorway", "trunk", "primary"}:
        return "major road"
    if tags.get("highway") == "secondary":
        return "secondary road"
    if tags.get("waterway") in {"river", "canal"}:
        return "river"
    if tags.get("leisure") == "park" or tags.get("landuse") == "cemetery":
        return "large green space"
    return None


def separating_features(
    seam: LineString,
    response: dict,
) -> list[dict]:
    """Which fetched features actually cross the seam between two areas.

    Args:
        seam: The segment joining the two closest sales, in EPSG:4326.
        response: An Overpass response from `fetch_features`.

    Returns:
        One dict per crossing feature with `feature_class`, `name` and `ref`,
        deduplicated by (class, name).
    """
    found: dict[tuple[str, str], dict] = {}

    for element in response.get("elements", []):
        geometry = element.get("geometry")
        if not geometry or len(geometry) < 2:
            continue
        feature_class = _classify(element.get("tags", {}))
        if feature_class is None:
            continue

        line = LineString([(node["lon"], node["lat"]) for node in geometry])
        if not line.intersects(seam):
            continue

        tags = element.get("tags", {})
        name = tags.get("name") or tags.get("ref") or ""
        key = (feature_class, name)
        found.setdefault(
            key,
            {"feature_class": feature_class, "name": name, "ref": tags.get("ref", "")},
        )

    order = [label for label, _ in FEATURE_CLASSES]
    return sorted(found.values(), key=lambda f: order.index(f["feature_class"]))


def closest_sales_seam(
    transactions: pl.DataFrame,
    lsoa_a: str,
    lsoa_b: str,
) -> tuple[LineString, tuple[float, float, float, float]]:
    """The shortest segment joining sales in two neighbourhoods.

    Args:
        transactions: Priced sales carrying lsoa21cd, easting, northing.
        lsoa_a: First neighbourhood.
        lsoa_b: Second neighbourhood.

    Returns:
        The seam as a LineString in EPSG:4326, and the two endpoints in BNG as
        (easting_a, northing_a, easting_b, northing_b).

    Raises:
        ValueError: If either neighbourhood has no located sales.
    """
    def points(code: str) -> gpd.GeoSeries:
        rows = transactions.filter(pl.col("lsoa21cd") == code).unique(
            subset="postcode_key"
        )
        if rows.height == 0:
            raise ValueError(f"No located sales for LSOA {code}.")
        return gpd.GeoSeries(
            gpd.points_from_xy(rows["easting"].to_list(), rows["northing"].to_list()),
            crs=BNG,
        )

    a_points, b_points = points(lsoa_a), points(lsoa_b)

    # Brute force is fine: an LSOA holds a few hundred postcodes at most.
    best = None
    for point in a_points:
        distances = b_points.distance(point)
        index = distances.idxmin()
        candidate = (float(distances.loc[index]), point, b_points.loc[index])
        if best is None or candidate[0] < best[0]:
            best = candidate

    _, point_a, point_b = best
    endpoints = (point_a.x, point_a.y, point_b.x, point_b.y)
    seam_wgs84 = (
        gpd.GeoSeries([LineString([point_a, point_b])], crs=BNG)
        .to_crs("EPSG:4326")
        .iloc[0]
    )
    return seam_wgs84, endpoints
