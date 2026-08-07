"""Per-catchment price aggregates.

Three quantities, deliberately reported together:

- **Mean** price — what the user asked for, and what most people expect.
- **Median** price — the headline. House price distributions are strongly right
  skewed, so in a catchment with a handful of large country houses the mean sits
  well above anything a buyer would actually encounter.
- **Median price per m²** — the comparable figure. A raw average mostly tracks
  what *kind* of housing a catchment contains: a catchment of four-bed detached
  houses will beat one of terraces regardless of how desirable either is. Dividing
  by floor area removes most of that composition effect.

Transaction counts sit alongside every figure, so a reader can see how much data
each rests on.
"""

from __future__ import annotations

import polars as pl

# Catchments with fewer sales than this get their price statistics suppressed.
# A median over a handful of rural sales is dominated by which houses happened to
# change hands, and £/m² is noisier still. The count itself is always shown.
MIN_TRANSACTIONS = 30


def catchment_summary(
    transactions: pl.DataFrame,
    min_transactions: int = MIN_TRANSACTIONS,
) -> pl.DataFrame:
    """Aggregate transactions to one row per catchment.

    Args:
        transactions: Located transactions carrying `catchment_name`, `price`,
            and optionally `floor_area_m2` / `price_per_m2`.
        min_transactions: Below this count, price statistics are nulled out.

    Returns:
        One row per catchment, sorted by median price descending, with a
        `suppressed` flag marking rows held back for thinness.
    """
    has_ppm2 = "price_per_m2" in transactions.columns

    aggregations = [
        pl.len().alias("n_sales"),
        pl.col("price").mean().round(0).alias("mean_price"),
        pl.col("price").median().round(0).alias("median_price"),
        pl.col("price").quantile(0.25).round(0).alias("p25_price"),
        pl.col("price").quantile(0.75).round(0).alias("p75_price"),
    ]
    if has_ppm2:
        aggregations += [
            pl.col("price_per_m2").median().round(0).alias("median_price_per_m2"),
            pl.col("floor_area_m2").median().round(1).alias("median_floor_area_m2"),
            pl.col("floor_area_m2").is_not_null().mean().alias("epc_match_rate"),
        ]

    summary = transactions.group_by("catchment_name").agg(aggregations)

    price_columns = [
        c for c in summary.columns if c not in ("catchment_name", "n_sales")
    ]
    thin = pl.col("n_sales") < min_transactions
    summary = summary.with_columns(
        thin.alias("suppressed"),
        *[
            pl.when(thin).then(None).otherwise(pl.col(c)).alias(c)
            for c in price_columns
        ],
    )

    return summary.sort("median_price", descending=True, nulls_last=True)


def to_markdown(summary: pl.DataFrame) -> str:
    """Render the summary as a Markdown table for the report.

    Args:
        summary: Output of `catchment_summary`.

    Returns:
        A Markdown table as a string.
    """
    has_ppm2 = "median_price_per_m2" in summary.columns

    headers = ["Catchment", "Sales", "Mean", "Median", "IQR"]
    if has_ppm2:
        headers += ["Median £/m²", "Median m²"]

    def money(value: float | None) -> str:
        return "—" if value is None else f"£{value:,.0f}"

    lines = ["| " + " | ".join(headers) + " |"]
    lines.append("|" + "|".join(["---"] * len(headers)) + "|")

    for row in summary.iter_rows(named=True):
        cells = [
            row["catchment_name"],
            f"{row['n_sales']:,}",
            money(row["mean_price"]),
            money(row["median_price"]),
            (
                "—"
                if row["p25_price"] is None
                else f"{money(row['p25_price'])}–{money(row['p75_price'])}"
            ),
        ]
        if has_ppm2:
            cells += [
                money(row.get("median_price_per_m2")),
                (
                    "—"
                    if row.get("median_floor_area_m2") is None
                    else f"{row['median_floor_area_m2']:,.0f}"
                ),
            ]
        lines.append("| " + " | ".join(cells) + " |")

    return "\n".join(lines)
