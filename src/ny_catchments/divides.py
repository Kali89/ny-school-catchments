"""Anatomy of a price divide: is it the housing, or is it the place?

A gap in median price per m² between two neighbouring areas has two very
different possible causes, and the raw figure cannot tell them apart:

- **Composition.** One side is a new estate of detached houses, the other is
  Victorian terraces. Dividing by floor area removes the size effect but nothing
  else — a detached new-build and a terrace of the same footprint do not sell for
  the same money, and never have.
- **Location.** The same kind of house is worth more on one side of a line than
  the other. This is the interesting case, and the one a catchment boundary could
  plausibly be said to sit on.

Separating them is a hedonic: regress log price per m² on the stock
characteristics available in Price Paid, then work with the residual. The
residual is what a house sells for relative to what its *type* would predict, so
a gap in median residuals between two areas is a location premium with
composition taken out.

The controls are property type, new-build status and tenure. They are the only
stock characteristics Price Paid carries, which bounds what this can claim: a
surviving gap means "not explained by type, age-at-sale or tenure", not "not
explained by the housing".
"""

from __future__ import annotations

import numpy as np
import polars as pl

# Controls entering the hedonic. Each is categorical and enters as dummies.
_CONTROLS = ("property_type", "old_new", "duration")


def hedonic_residuals(transactions: pl.DataFrame) -> pl.DataFrame:
    """Add `price_residual`: log £/m² net of property type, age and tenure.

    Fitted across the whole county at once, so the coefficients describe what a
    detached house or a new build is worth generally rather than being refitted
    inside each comparison.

    Args:
        transactions: Rows carrying price_per_m2 and the control columns.

    Returns:
        The priced rows with `log_ppm2`, `price_predicted` and `price_residual`.
        Rows without a price per m² are dropped — they carry no information here.

    Raises:
        ValueError: If no rows survive, or a control column is missing.
    """
    missing = [c for c in _CONTROLS if c not in transactions.columns]
    if missing:
        raise ValueError(f"Hedonic needs {missing}, which are absent.")

    priced = transactions.filter(
        pl.col("price_per_m2").is_not_null() & (pl.col("price_per_m2") > 0)
    ).with_columns(pl.col("price_per_m2").log().alias("log_ppm2"))
    if priced.height == 0:
        raise ValueError("No priced transactions to fit a hedonic on.")

    # Dummy-encode each control, dropping one level as the reference category so
    # the design matrix stays full rank alongside the intercept.
    columns = [np.ones(priced.height)]
    for control in _CONTROLS:
        levels = sorted(priced[control].drop_nulls().unique().to_list())
        values = priced[control].to_numpy()
        for level in levels[1:]:
            columns.append((values == level).astype(float))

    design = np.column_stack(columns)
    target = priced["log_ppm2"].to_numpy()
    coefficients, *_ = np.linalg.lstsq(design, target, rcond=None)
    predicted = design @ coefficients

    return priced.with_columns(
        pl.Series("price_predicted", predicted),
        pl.Series("price_residual", target - predicted),
    )


def hedonic_r2(residualised: pl.DataFrame) -> float:
    """Share of log-price variance the stock controls explain.

    Args:
        residualised: Output of `hedonic_residuals`.

    Returns:
        R² in [0, 1]. A low value means the controls explain little, so a
        composition-adjusted gap will look much like the raw one.
    """
    target = residualised["log_ppm2"].to_numpy()
    residual = residualised["price_residual"].to_numpy()
    total = float(((target - target.mean()) ** 2).sum())
    return 0.0 if total == 0 else 1.0 - float((residual**2).sum()) / total


def lsoa_composition(
    transactions: pl.DataFrame,
    min_sales: int = 30,
) -> pl.DataFrame:
    """Housing stock mix per neighbourhood.

    Args:
        transactions: Priced sales carrying lsoa21cd and the stock columns.
        min_sales: Neighbourhoods with fewer priced sales are excluded.

    Returns:
        One row per LSOA with the share detached, semi, terraced and flat, the
        new-build and leasehold shares, and the median floor area.
    """
    priced = transactions.filter(pl.col("price_per_m2").is_not_null())
    return (
        priced.group_by("lsoa21cd")
        .agg(
            pl.len().alias("n_priced"),
            (pl.col("property_type") == "D").mean().alias("share_detached"),
            (pl.col("property_type") == "S").mean().alias("share_semi"),
            (pl.col("property_type") == "T").mean().alias("share_terraced"),
            (pl.col("property_type") == "F").mean().alias("share_flat"),
            (pl.col("old_new") == "Y").mean().alias("share_newbuild"),
            (pl.col("duration") == "L").mean().alias("share_leasehold"),
            pl.col("floor_area_m2").median().alias("median_floor_area_m2"),
            pl.col("price_residual").median().alias("median_residual"),
        )
        .filter(pl.col("n_priced") >= min_sales)
    )


def adjusted_contrasts(
    contrasts: pl.DataFrame,
    composition: pl.DataFrame,
) -> pl.DataFrame:
    """Attach composition and the composition-adjusted gap to each divide.

    Args:
        contrasts: Output of `inequality.neighbouring_contrasts`, carrying
            `richer_lsoa` / `poorer_lsoa` and `price_ratio`.
        composition: Output of `lsoa_composition`.

    Returns:
        The contrasts with, for each side, the stock shares and median residual;
        plus `adjusted_ratio` — the ratio implied by the residual gap alone — and
        `share_explained`, the fraction of the log gap the stock controls absorb.
    """
    richer = composition.rename(
        {c: f"{c}_richer" for c in composition.columns if c != "lsoa21cd"}
    )
    poorer = composition.rename(
        {c: f"{c}_poorer" for c in composition.columns if c != "lsoa21cd"}
    )

    joined = (
        contrasts.join(richer, left_on="richer_lsoa", right_on="lsoa21cd", how="inner")
        .join(poorer, left_on="poorer_lsoa", right_on="lsoa21cd", how="inner")
    )
    if joined.height == 0:
        return joined

    # The residual gap is already in logs, so exponentiating gives a ratio
    # directly comparable to the raw price_ratio.
    residual_gap = pl.col("median_residual_richer") - pl.col("median_residual_poorer")
    return joined.with_columns(
        residual_gap.exp().alias("adjusted_ratio"),
    ).with_columns(
        (
            1 - residual_gap / pl.col("price_ratio").log()
        ).alias("share_explained")
    ).sort("adjusted_ratio", descending=True)


def describe_divide(row: dict) -> str:
    """A one-line characterisation of what a divide is made of.

    Args:
        row: A row from `adjusted_contrasts`.

    Returns:
        A short human-readable summary, e.g. "new-build detached vs terraces".
    """
    def side(prefix: str) -> str:
        detached = row[f"share_detached_{prefix}"]
        terraced = row[f"share_terraced_{prefix}"] + row[f"share_flat_{prefix}"]
        newbuild = row[f"share_newbuild_{prefix}"]

        if detached >= 0.5:
            stock = "mostly detached"
        elif terraced >= 0.5:
            stock = "mostly terraced/flats"
        else:
            stock = "mixed stock"
        return f"{'new-build ' if newbuild >= 0.35 else ''}{stock}"

    return f"{side('richer')} vs {side('poorer')}"


def variance_by_level(
    transactions: pl.DataFrame,
    levels: tuple[str, ...] = ("catchment_name", "lsoa21cd"),
) -> pl.DataFrame:
    """How much price variation sits at each geographic level.

    This is what bounds any proposal to redraw boundaries. A boundary can only
    reallocate variation that lies *between* the units it is drawn around; two
    houses in the same neighbourhood end up on the same side of every possible
    line. So the between-neighbourhood share is a ceiling on what redrawing could
    ever move, no matter how the lines are optimised.

    Args:
        transactions: Priced sales carrying price_per_m2 and the level columns.
        levels: Grouping columns, coarsest first.

    Returns:
        One row per level with `between_share` — the fraction of total log price
        variance lying between groups at that level.

    Raises:
        ValueError: If there is no variance to decompose.
    """
    priced = transactions.filter(
        pl.col("price_per_m2").is_not_null() & (pl.col("price_per_m2") > 0)
    ).with_columns(pl.col("price_per_m2").log().alias("_log_ppm2"))

    values = priced["_log_ppm2"].to_numpy()
    grand_mean = values.mean()
    total = float(((values - grand_mean) ** 2).mean())
    if total == 0:
        raise ValueError("No variance in log price per m² to decompose.")

    rows = []
    for level in levels:
        grouped = priced.group_by(level).agg(
            pl.col("_log_ppm2").mean().alias("_m"), pl.len().alias("_n")
        )
        weights = grouped["_n"].to_numpy()
        means = grouped["_m"].to_numpy()
        between = float((weights * (means - grand_mean) ** 2).sum() / weights.sum())
        rows.append(
            {
                "level": level,
                "n_groups": grouped.height,
                "between_share": between / total,
            }
        )

    return pl.DataFrame(rows)
