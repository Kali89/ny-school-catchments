"""Splitting transactions into comparable time periods.

The question this supports is "which catchments have seen outsized gains or
falls in price per m²", which needs two things the raw figures do not give:

**A baseline.** Nominal £/m² roughly doubled across the county over twenty
years, so almost every catchment "gained". The only meaningful reading of
*outsized* is relative to what the county as a whole did, so every change is
reported both in its own right and net of the county-wide change.

**An honest coverage statement.** The EPC register begins in 2012. A sale in
2008 carries a floor area only if that property was certified later — which
happens when it is marketed again, so coverage in the early period is a function
of subsequent market activity rather than a random sample. Match rate is
therefore reported per period, never assumed.
"""

from __future__ import annotations

from dataclasses import dataclass

import polars as pl


@dataclass(frozen=True)
class Period:
    """A labelled half-open interval of transfer years, [start, end)."""

    key: str
    label: str
    start_year: int
    end_year: int

    @property
    def span_label(self) -> str:
        return f"{self.start_year}–{self.end_year - 1}"


# Periods run back from a 2026 reference and cover whole calendar years only.
# The part-year 2026 is deliberately excluded: a half-year of sales would sit in
# the recent window at half the weight of every other year, and if prices moved
# within 2026 it would tug the median for reasons that have nothing to do with
# the comparison being made.
#
# Deliberately unequal lengths: the recent and prior windows are five years each
# so they are directly comparable, while the early window is ten, because thinner
# catchments would otherwise carry too few sales to support a median that far
# back.
RECENT = Period("recent", "Last 5 years", 2021, 2026)
PRIOR = Period("prior", "5–10 years ago", 2016, 2021)
EARLY = Period("early", "10–20 years ago", 2006, 2016)

PERIODS: tuple[Period, ...] = (EARLY, PRIOR, RECENT)


def assign_periods(transactions: pl.DataFrame) -> pl.DataFrame:
    """Label each transaction with the period its transfer date falls in.

    Args:
        transactions: Must carry `transfer_date`.

    Returns:
        The transactions with a `period` column. Sales outside every period are
        labelled null and should be filtered by the caller.
    """
    year = pl.col("transfer_date").dt.year()
    expr = pl.when(pl.lit(False)).then(pl.lit(None, dtype=pl.Utf8))
    for period in PERIODS:
        expr = expr.when(
            (year >= period.start_year) & (year < period.end_year)
        ).then(pl.lit(period.key))
    return transactions.with_columns(expr.otherwise(None).alias("period"))


def period_coverage(transactions: pl.DataFrame) -> pl.DataFrame:
    """EPC match rate per period.

    Coverage falls away in the early period because the register starts in 2012.
    Reporting it is what stops a comparison across periods being read as a
    comparison of like with like when it is not.

    Args:
        transactions: Output of `assign_periods`, carrying `floor_area_m2`.

    Returns:
        One row per period with transaction and match counts.
    """
    return (
        transactions.filter(pl.col("period").is_not_null())
        .group_by("period")
        .agg(
            pl.len().alias("transactions"),
            pl.col("floor_area_m2").is_not_null().sum().alias("with_floor_area"),
            pl.col("floor_area_m2").is_not_null().mean().alias("match_rate"),
        )
        .sort("period")
    )


def period_medians(
    transactions: pl.DataFrame,
    min_transactions: int,
) -> pl.DataFrame:
    """Median £/m² per catchment per period.

    Args:
        transactions: Output of `assign_periods`, carrying `price_per_m2`.
        min_transactions: Below this count of *floor-area-matched* sales, the
            median is suppressed. Applied per catchment-period, not per
            catchment, since a catchment can be thick recently and thin in 2006.

    Returns:
        One row per catchment-period with `median_price_per_m2` and `n_priced`.
    """
    priced = transactions.filter(
        pl.col("period").is_not_null() & pl.col("price_per_m2").is_not_null()
    )
    summary = priced.group_by(["catchment_name", "period"]).agg(
        pl.len().alias("n_priced"),
        pl.col("price_per_m2").median().alias("median_price_per_m2"),
    )
    return summary.with_columns(
        pl.when(pl.col("n_priced") < min_transactions)
        .then(None)
        .otherwise(pl.col("median_price_per_m2"))
        .alias("median_price_per_m2")
    )


def relative_change(
    medians: pl.DataFrame,
    from_period: Period,
    to_period: Period,
) -> pl.DataFrame:
    """Change in median £/m² between two periods, and net of the county.

    Args:
        medians: Output of `period_medians`.
        from_period: The baseline period.
        to_period: The comparison period.

    Returns:
        One row per catchment with both periods' medians, the percentage change,
        and `excess_change_pct` — the percentage change less the county-wide
        percentage change over the same pair of periods. Positive means the
        catchment outpaced the county; negative means it lagged. Catchments
        suppressed in either period are dropped.

    Raises:
        ValueError: If either period has no reportable catchment, which would
            make the county baseline meaningless.
    """
    wide = (
        medians.filter(pl.col("period").is_in([from_period.key, to_period.key]))
        .pivot(on="period", index="catchment_name", values="median_price_per_m2")
    )
    for period in (from_period, to_period):
        if period.key not in wide.columns:
            raise ValueError(f"No data at all for period {period.key!r}.")

    wide = wide.drop_nulls([from_period.key, to_period.key])
    if wide.height == 0:
        raise ValueError(
            f"No catchment is reportable in both {from_period.key} and "
            f"{to_period.key}; the county baseline cannot be computed."
        )

    wide = wide.with_columns(
        (
            (pl.col(to_period.key) - pl.col(from_period.key))
            / pl.col(from_period.key)
            * 100
        ).alias("change_pct")
    )

    # The county baseline is the median catchment's change, not the change in the
    # county median. The former asks "what did a typical catchment do", which is
    # the right comparator for judging one catchment against its peers; the
    # latter is dominated by wherever the most sales happened to be.
    county_change = wide["change_pct"].median()

    return wide.with_columns(
        (pl.col("change_pct") - county_change).alias("excess_change_pct"),
        pl.lit(county_change).alias("county_change_pct"),
    ).sort("excess_change_pct", descending=True)
