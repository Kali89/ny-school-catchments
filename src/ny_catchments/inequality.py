"""Inequality within catchments, and where rich and poor sit side by side.

Two different questions, and conflating them would be a mistake:

**How unequal is a catchment?** Dispersion of price per m² across its sales.
Reported as P90/P10 (the top decile costs N× the bottom) and Gini. P90/P10 is
the headline because it survives small samples far better than Gini and states
itself in a sentence.

**Is that inequality geographic?** A catchment can be unequal because expensive
and cheap homes are mixed street by street, or because it contains one wealthy
village and one deprived estate. Only the second is "rich and poor areas next to
each other". Separating them needs a sub-catchment unit, which is the LSOA —
around 650 households, and already attached to every sale through ONSPD.

So dispersion is decomposed: how much of it is *between* LSOAs versus *within*
them. A catchment whose inequality is mostly between LSOAs is spatially divided.

Adjacency
---------
LSOA boundaries are not needed and would arguably be worse. Two rural LSOAs can
share a long boundary across open moorland while their inhabited parts are eight
kilometres apart — polygon contiguity would call that neighbouring, which is not
what the question means. Instead two LSOAs are adjacent when they contain
postcodes within `ADJACENCY_M` of each other: a measure of where people actually
live close together.
"""

from __future__ import annotations

import geopandas as gpd
import numpy as np
import polars as pl

from .config import BNG

# Two LSOAs count as neighbours when any postcode of one lies within this
# distance of any postcode of the other. 500m is about the point at which
# "next to each other" stops being a fair description in a rural county.
ADJACENCY_M = 500.0

# An LSOA needs at least this many priced sales before its median is used.
MIN_LSOA_SALES = 30

# A catchment needs at least this many priced sales before its dispersion is
# reported. Dispersion is noisier than a median, so this is deliberately higher
# than the threshold used for medians elsewhere.
MIN_CATCHMENT_SALES = 100


def gini(values: np.ndarray) -> float:
    """Gini coefficient of a non-negative array.

    Args:
        values: Positive values, e.g. price per m².

    Returns:
        Gini in [0, 1]. 0 is perfect equality.

    Raises:
        ValueError: If the array is empty or contains negatives.
    """
    if values.size == 0:
        raise ValueError("Gini is undefined for an empty array.")
    if (values < 0).any():
        raise ValueError("Gini is undefined for negative values.")

    ordered = np.sort(values)
    n = ordered.size
    total = ordered.sum()
    if total == 0:
        return 0.0
    index = np.arange(1, n + 1)
    return float((2 * index - n - 1).dot(ordered) / (n * total))


def catchment_inequality(
    transactions: pl.DataFrame,
    min_sales: int = MIN_CATCHMENT_SALES,
) -> pl.DataFrame:
    """Dispersion of price per m² within each catchment.

    Args:
        transactions: Rows carrying `catchment_name` and `price_per_m2`.
        min_sales: Catchments with fewer priced sales are excluded.

    Returns:
        One row per catchment with `p90_p10`, `gini_ppm2`, `median_price_per_m2`
        and `n_priced`, sorted by P90/P10 descending.
    """
    priced = transactions.filter(pl.col("price_per_m2").is_not_null())

    summary = (
        priced.group_by("catchment_name")
        .agg(
            pl.len().alias("n_priced"),
            pl.col("price_per_m2").median().alias("median_price_per_m2"),
            pl.col("price_per_m2").quantile(0.10).alias("p10"),
            pl.col("price_per_m2").quantile(0.90).alias("p90"),
        )
        .filter(pl.col("n_priced") >= min_sales)
        .with_columns((pl.col("p90") / pl.col("p10")).alias("p90_p10"))
    )

    ginis = []
    for name in summary["catchment_name"]:
        values = priced.filter(pl.col("catchment_name") == name)["price_per_m2"]
        ginis.append(gini(values.to_numpy()))

    return summary.with_columns(
        pl.Series("gini_ppm2", ginis, dtype=pl.Float64)
    ).sort("p90_p10", descending=True)


def lsoa_profile(
    transactions: pl.DataFrame,
    min_sales: int = MIN_LSOA_SALES,
) -> pl.DataFrame:
    """One row per LSOA: median £/m², deprivation, location and catchment.

    Each LSOA is assigned to the catchment holding most of its sales. LSOAs
    straddling a boundary are uncommon here (58 of 419, and only 32 below 80%
    purity), and the alternative — splitting an LSOA's sales across catchments —
    would give medians resting on a handful of transactions.

    Args:
        transactions: Rows carrying lsoa21cd, catchment_name, price_per_m2,
            imd20ind, easting, northing.
        min_sales: LSOAs with fewer priced sales are excluded.

    Returns:
        One row per LSOA with `median_price_per_m2`, `imd_rank`, `easting`,
        `northing`, `catchment_name` and `n_priced`.
    """
    priced = transactions.filter(pl.col("price_per_m2").is_not_null())

    dominant = (
        priced.group_by(["lsoa21cd", "catchment_name"])
        .agg(pl.len().alias("n"))
        .sort(["lsoa21cd", "n"], descending=[False, True])
        .group_by("lsoa21cd", maintain_order=True)
        .first()
        .select("lsoa21cd", "catchment_name")
    )

    profile = (
        priced.group_by("lsoa21cd")
        .agg(
            pl.len().alias("n_priced"),
            pl.col("price_per_m2").median().alias("median_price_per_m2"),
            # IMD 2020 rank: 1 is the most deprived LSOA in England, so a higher
            # rank means less deprived. Constant within an LSOA, hence first().
            pl.col("imd20ind").first().alias("imd_rank"),
            pl.col("easting").mean().alias("easting"),
            pl.col("northing").mean().alias("northing"),
        )
        .filter(pl.col("n_priced") >= min_sales)
    )
    return profile.join(dominant, on="lsoa21cd", how="inner")


def decompose_dispersion(
    transactions: pl.DataFrame,
    profile: pl.DataFrame,
    min_lsoas: int = 3,
) -> pl.DataFrame:
    """Split each catchment's price variation into between- and within-LSOA parts.

    Uses variance of log price per m², so the split is scale-free and the
    components add. The between share answers the question that matters here: is
    this catchment's inequality a matter of geography, or of variation happening
    everywhere within it?

    Args:
        transactions: Priced sales carrying lsoa21cd and price_per_m2.
        profile: Output of `lsoa_profile`, used for the LSOA-to-catchment map.
        min_lsoas: Catchments with fewer usable LSOAs are excluded — a between
            component computed on two areas is not meaningful.

    Returns:
        One row per catchment with `between_share`, `n_lsoas`, sorted by
        `between_share` descending.
    """
    usable = (
        transactions.filter(pl.col("price_per_m2").is_not_null())
        .join(profile.select("lsoa21cd", "catchment_name"), on="lsoa21cd", how="inner")
        .with_columns(pl.col("price_per_m2").log().alias("log_ppm2"))
    )

    rows = []
    for (name,), group in usable.group_by(["catchment_name"], maintain_order=True):
        lsoa_means = group.group_by("lsoa21cd").agg(
            pl.col("log_ppm2").mean().alias("mean_log"),
            pl.len().alias("n"),
        )
        if lsoa_means.height < min_lsoas:
            continue

        grand_mean = group["log_ppm2"].mean()
        total_var = group["log_ppm2"].var(ddof=0)
        if total_var is None or total_var == 0:
            continue

        weights = lsoa_means["n"].to_numpy()
        between_var = float(
            (weights * (lsoa_means["mean_log"].to_numpy() - grand_mean) ** 2).sum()
            / weights.sum()
        )
        rows.append(
            {
                "catchment_name": name,
                "n_lsoas": lsoa_means.height,
                "between_share": between_var / float(total_var),
            }
        )

    if not rows:
        return pl.DataFrame(
            schema={
                "catchment_name": pl.Utf8,
                "n_lsoas": pl.UInt32,
                "between_share": pl.Float64,
            }
        )
    return pl.DataFrame(rows).sort("between_share", descending=True)


def lsoa_adjacency(
    transactions: pl.DataFrame,
    distance_m: float = ADJACENCY_M,
) -> pl.DataFrame:
    """Pairs of LSOAs with postcodes close enough to count as neighbouring.

    Args:
        transactions: Rows carrying lsoa21cd, easting, northing. One row per
            postcode is enough; duplicates are collapsed first.
        distance_m: Maximum separation between a postcode of each LSOA.

    Returns:
        Unique unordered pairs as `lsoa_a` / `lsoa_b`, with `min_distance_m`.
    """
    points = (
        transactions.select("lsoa21cd", "postcode_key", "easting", "northing")
        .unique(subset="postcode_key")
        .drop_nulls(["lsoa21cd", "easting", "northing"])
    )

    gdf = gpd.GeoDataFrame(
        {"lsoa21cd": points["lsoa21cd"].to_list()},
        geometry=gpd.points_from_xy(
            points["easting"].to_list(), points["northing"].to_list()
        ),
        crs=BNG,
    )

    # "dwithin", not "nearest": every postcode pair inside the radius is wanted.
    # sjoin_nearest would return each point's single closest neighbour, which is
    # itself, and the cross-LSOA pairs would never appear at all.
    gdf = gdf.reset_index(drop=True)
    pairs = gpd.sjoin(
        gdf, gdf, how="inner", predicate="dwithin", distance=distance_m
    )
    pairs = pairs[pairs["lsoa21cd_left"] != pairs["lsoa21cd_right"]]
    if pairs.empty:
        return pl.DataFrame(
            schema={"lsoa_a": pl.Utf8, "lsoa_b": pl.Utf8, "min_distance_m": pl.Float64}
        )

    coordinates = np.column_stack([gdf.geometry.x.to_numpy(), gdf.geometry.y.to_numpy()])
    left_xy = coordinates[pairs.index.to_numpy()]
    right_xy = coordinates[pairs["index_right"].to_numpy()]
    distances = np.hypot(*(left_xy - right_xy).T)

    frame = pl.DataFrame(
        {
            "left": pairs["lsoa21cd_left"].to_numpy(),
            "right": pairs["lsoa21cd_right"].to_numpy(),
            "d": distances,
        }
    )
    # Order each pair so (A,B) and (B,A) collapse to one row.
    return (
        frame.with_columns(
            pl.min_horizontal("left", "right").alias("lsoa_a"),
            pl.max_horizontal("left", "right").alias("lsoa_b"),
        )
        .group_by(["lsoa_a", "lsoa_b"])
        .agg(pl.col("d").min().alias("min_distance_m"))
    )


def neighbouring_contrasts(
    profile: pl.DataFrame,
    adjacency: pl.DataFrame,
) -> pl.DataFrame:
    """Price and deprivation gaps between neighbouring LSOAs in one catchment.

    Only pairs whose LSOAs share a catchment are kept — the question is about
    division *inside* a catchment, not across its boundary.

    Args:
        profile: Output of `lsoa_profile`.
        adjacency: Output of `lsoa_adjacency`.

    Returns:
        One row per neighbouring same-catchment pair, with the richer and poorer
        side named, `price_ratio` (richer ÷ poorer median £/m²) and `imd_gap`
        (difference in IMD rank, positive meaning the richer side is also the
        less deprived), sorted by `price_ratio` descending.
    """
    side = profile.select(
        "lsoa21cd", "catchment_name", "median_price_per_m2", "imd_rank",
        "easting", "northing", "n_priced",
    )

    pairs = (
        adjacency.join(side, left_on="lsoa_a", right_on="lsoa21cd", how="inner")
        .rename(
            {
                "catchment_name": "catchment_a",
                "median_price_per_m2": "ppm2_a",
                "imd_rank": "imd_a",
                "easting": "easting_a",
                "northing": "northing_a",
                "n_priced": "n_a",
            }
        )
        .join(side, left_on="lsoa_b", right_on="lsoa21cd", how="inner")
        .rename(
            {
                "catchment_name": "catchment_b",
                "median_price_per_m2": "ppm2_b",
                "imd_rank": "imd_b",
                "easting": "easting_b",
                "northing": "northing_b",
                "n_priced": "n_b",
            }
        )
        .filter(pl.col("catchment_a") == pl.col("catchment_b"))
    )

    if pairs.height == 0:
        return pairs

    richer_is_a = pl.col("ppm2_a") >= pl.col("ppm2_b")
    return (
        pairs.with_columns(
            pl.col("catchment_a").alias("catchment_name"),
            pl.when(richer_is_a).then(pl.col("lsoa_a")).otherwise(pl.col("lsoa_b"))
            .alias("richer_lsoa"),
            pl.when(richer_is_a).then(pl.col("lsoa_b")).otherwise(pl.col("lsoa_a"))
            .alias("poorer_lsoa"),
            pl.max_horizontal("ppm2_a", "ppm2_b").alias("richer_ppm2"),
            pl.min_horizontal("ppm2_a", "ppm2_b").alias("poorer_ppm2"),
            pl.when(richer_is_a).then(pl.col("imd_a")).otherwise(pl.col("imd_b"))
            .alias("richer_imd"),
            pl.when(richer_is_a).then(pl.col("imd_b")).otherwise(pl.col("imd_a"))
            .alias("poorer_imd"),
        )
        .with_columns(
            (pl.col("richer_ppm2") / pl.col("poorer_ppm2")).alias("price_ratio"),
            (pl.col("richer_imd") - pl.col("poorer_imd")).alias("imd_gap"),
        )
        .sort("price_ratio", descending=True)
    )


def sharpest_divides(contrasts: pl.DataFrame) -> pl.DataFrame:
    """The single sharpest neighbouring contrast in each catchment.

    Args:
        contrasts: Output of `neighbouring_contrasts`.

    Returns:
        One row per catchment, sorted by `price_ratio` descending.
    """
    if contrasts.height == 0:
        return contrasts
    return (
        contrasts.sort("price_ratio", descending=True)
        .group_by("catchment_name", maintain_order=True)
        .first()
    )
