"""Non-map figures: distributions and change over time.

Form follows the job. A ranked box plot answers "how tightly are catchments
bunched, and where does mine sit" — the spread is the point, so a bar of medians
would throw away exactly the information wanted. A diverging bar answers "who
moved outsized", which has a meaningful zero (the county-wide change), so it
takes the diverging palette with a neutral midpoint rather than a sequential
ramp.
"""

from __future__ import annotations

import matplotlib.pyplot as plt
import polars as pl
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

from .plot import (
    HAIRLINE,
    INK_MUTED,
    INK_PRIMARY,
    INK_SECONDARY,
    SERIES_BLUE,
    SURFACE,
)

# Diverging pair: warm/cool poles that read as opposite, with a neutral gray
# midpoint so "no different from the county" reads as nothing rather than as a
# weak version of one pole.
DIVERGING_HIGH = "#2a78d6"  # outpaced the county
DIVERGING_LOW = "#e34948"  # lagged the county
NEUTRAL_MID = "#c3c2b7"

BOX_FILL = "#cde2fb"
FOCAL_FILL = SERIES_BLUE


def _box_stats(values: pl.Series, label: str) -> dict:
    """Precomputed box statistics for one catchment.

    Whiskers are the 10th and 90th percentiles rather than the Tukey 1.5×IQR
    rule. House prices are strongly right skewed, so the Tukey rule would mark
    hundreds of ordinary sales as outliers and bury the boxes under a cloud of
    dots. Stating the percentile explicitly is more honest than a convention
    most readers would assume means something else.

    Args:
        values: Price per m² for one catchment.
        label: Catchment name.

    Returns:
        A stats dict in the shape matplotlib's `bxp` expects.
    """
    return {
        "label": label,
        "med": values.median(),
        "q1": values.quantile(0.25),
        "q3": values.quantile(0.75),
        "whislo": values.quantile(0.10),
        "whishi": values.quantile(0.90),
        "fliers": [],
    }


def plot_price_distribution(
    transactions: pl.DataFrame,
    min_transactions: int,
    focal_catchment: str | None = None,
    title: str = "Price per m² by school catchment",
    subtitle: str = "",
    stand_in_note: str | None = None,
):
    """Ranked box plot of price per m², one row per catchment.

    Args:
        transactions: Rows carrying `catchment_name` and `price_per_m2`.
        min_transactions: Catchments with fewer priced sales are excluded.
        focal_catchment: Catchment to highlight, if any.
        title: Figure title.
        subtitle: Line under the title.
        stand_in_note: Caveat line shown above the subtitle.

    Returns:
        The matplotlib Figure.

    Raises:
        ValueError: If no catchment clears the threshold.
    """
    priced = transactions.filter(pl.col("price_per_m2").is_not_null())
    counts = priced.group_by("catchment_name").agg(pl.len().alias("n"))
    keep = counts.filter(pl.col("n") >= min_transactions)["catchment_name"]
    if keep.len() == 0:
        raise ValueError(
            f"No catchment has {min_transactions} priced sales — nothing to plot."
        )

    priced = priced.filter(pl.col("catchment_name").is_in(keep))
    order = (
        priced.group_by("catchment_name")
        .agg(pl.col("price_per_m2").median().alias("med"))
        .sort("med")
    )

    stats, colours, labels = [], [], []
    count_lookup = dict(zip(counts["catchment_name"], counts["n"], strict=True))
    for name in order["catchment_name"]:
        values = priced.filter(pl.col("catchment_name") == name)["price_per_m2"]
        stats.append(_box_stats(values, name))
        is_focal = focal_catchment is not None and name == focal_catchment
        colours.append(FOCAL_FILL if is_focal else BOX_FILL)
        labels.append(f"{name}  (n={count_lookup[name]:,})")

    height = max(6.0, 0.34 * len(stats) + 3.0)
    fig, ax = plt.subplots(figsize=(13, height), dpi=200)

    boxes = ax.bxp(
        stats,
        vert=False,
        showfliers=False,
        patch_artist=True,
        widths=0.62,
        medianprops={"color": INK_PRIMARY, "linewidth": 1.6},
        whiskerprops={"color": INK_MUTED, "linewidth": 1.0},
        capprops={"color": INK_MUTED, "linewidth": 1.0},
        boxprops={"edgecolor": SURFACE, "linewidth": 1.0},
    )
    for patch, colour in zip(boxes["boxes"], colours, strict=True):
        patch.set_facecolor(colour)

    # County reference: the median catchment median, i.e. the typical catchment.
    county = order["med"].median()
    ax.axvline(county, color=INK_SECONDARY, linewidth=1.2, linestyle=(0, (4, 3)), zorder=0)
    # Anchored in axes fraction vertically so it sits just above the plot area
    # rather than at a data coordinate that the axes may clip.
    ax.text(
        county,
        1.004,
        f"Typical catchment  £{county:,.0f}",
        transform=ax.get_xaxis_transform(),
        ha="center",
        va="bottom",
        fontsize=8.5,
        color=INK_SECONDARY,
        clip_on=False,
    )

    ax.set_yticklabels(labels, fontsize=8)
    ax.tick_params(axis="y", length=0, colors=INK_SECONDARY)
    ax.tick_params(axis="x", colors=INK_SECONDARY, labelsize=8.5)
    ax.xaxis.set_major_formatter(lambda v, _: f"£{v:,.0f}")
    ax.set_xlabel("Price per m² (median, box = middle 50%, whiskers = 10th–90th percentile)",
                  fontsize=9, color=INK_SECONDARY)

    ax.grid(axis="x", color=HAIRLINE, linewidth=0.8, zorder=0)
    ax.set_axisbelow(True)
    for spine in ("top", "right", "left"):
        ax.spines[spine].set_visible(False)
    ax.spines["bottom"].set_color(HAIRLINE)

    if focal_catchment is not None and focal_catchment in set(order["catchment_name"]):
        ax.legend(
            handles=[
                Patch(facecolor=FOCAL_FILL, edgecolor=SURFACE, label=focal_catchment),
                Patch(facecolor=BOX_FILL, edgecolor=SURFACE, label="Other catchments"),
            ],
            loc="lower right",
            frameon=True,
            facecolor=SURFACE,
            edgecolor=HAIRLINE,
            framealpha=1.0,
            fontsize=8.5,
            labelcolor=INK_SECONDARY,
        )

    _frame(fig, title, subtitle, stand_in_note)
    return fig


def plot_excess_change(
    changes: pl.DataFrame,
    from_label: str,
    to_label: str,
    county_change_pct: float,
    focal_catchment: str | None = None,
    stand_in_note: str | None = None,
):
    """Diverging bar of change in £/m² relative to the county-wide change.

    Args:
        changes: Output of `periods.relative_change`.
        from_label: Human label for the baseline period.
        to_label: Human label for the comparison period.
        county_change_pct: The county-wide change, for the subtitle.
        focal_catchment: Catchment to mark, if any.
        stand_in_note: Caveat line shown above the subtitle.

    Returns:
        The matplotlib Figure.
    """
    ordered = changes.sort("excess_change_pct")
    names = ordered["catchment_name"].to_list()
    values = ordered["excess_change_pct"].to_list()

    height = max(6.0, 0.32 * len(names) + 3.0)
    fig, ax = plt.subplots(figsize=(13, height), dpi=200)

    colours = [DIVERGING_HIGH if v >= 0 else DIVERGING_LOW for v in values]
    positions = range(len(names))
    ax.barh(list(positions), values, color=colours, height=0.66, zorder=2)

    ax.axvline(0, color=NEUTRAL_MID, linewidth=1.4, zorder=1)

    labels = []
    for name in names:
        marker = "  ◂" if focal_catchment and name == focal_catchment else ""
        labels.append(f"{name}{marker}")
    ax.set_yticks(list(positions))
    ax.set_yticklabels(labels, fontsize=8)
    ax.tick_params(axis="y", length=0, colors=INK_SECONDARY)
    ax.tick_params(axis="x", colors=INK_SECONDARY, labelsize=8.5)
    ax.xaxis.set_major_formatter(lambda v, _: f"{v:+.0f} pp")
    ax.set_xlabel(
        "Change in median £/m², percentage points above or below the county-wide change",
        fontsize=9,
        color=INK_SECONDARY,
    )

    ax.grid(axis="x", color=HAIRLINE, linewidth=0.8, zorder=0)
    ax.set_axisbelow(True)
    for spine in ("top", "right", "left"):
        ax.spines[spine].set_visible(False)
    ax.spines["bottom"].set_color(HAIRLINE)

    ax.legend(
        handles=[
            Patch(facecolor=DIVERGING_HIGH, label="Outpaced the county"),
            Patch(facecolor=DIVERGING_LOW, label="Lagged the county"),
        ],
        loc="lower right",
        frameon=True,
        facecolor=SURFACE,
        edgecolor=HAIRLINE,
        framealpha=1.0,
        fontsize=8.5,
        labelcolor=INK_SECONDARY,
    )

    _frame(
        fig,
        f"Outsized movers in price per m²: {from_label} to {to_label}",
        f"Zero is the typical catchment, which changed by {county_change_pct:+.0f}% "
        f"in nominal terms over this span",
        stand_in_note,
    )
    return fig


def plot_rank_shift(
    medians: pl.DataFrame,
    periods,
    focal_catchment: str | None = None,
    stand_in_note: str | None = None,
):
    """Slope chart of each catchment's rank on £/m² across periods.

    Rank is deliberately used rather than level: nominal £/m² roughly doubled
    over twenty years, so a level chart would show forty near-parallel lines
    climbing, and the movement between catchments — the actual question — would
    be invisible inside the common trend.

    Args:
        medians: Output of `periods.period_medians`.
        periods: Ordered sequence of `Period` objects to place on the x axis.
        focal_catchment: Catchment to highlight, if any.
        stand_in_note: Caveat line shown above the subtitle.

    Returns:
        The matplotlib Figure.

    Raises:
        ValueError: If no catchment is reportable in every period.
    """
    keys = [p.key for p in periods]
    wide = (
        medians.filter(pl.col("period").is_in(keys))
        .pivot(on="period", index="catchment_name", values="median_price_per_m2")
        .drop_nulls(keys)
    )
    if wide.height == 0:
        raise ValueError("No catchment is reportable in every period.")

    # Rank 1 = most expensive, so the axis can be inverted and read top-down.
    ranked = wide.with_columns(
        [pl.col(k).rank(descending=True).alias(f"rank_{k}") for k in keys]
    )

    fig, ax = plt.subplots(figsize=(11, 12), dpi=200)
    xs = list(range(len(keys)))

    for row in ranked.iter_rows(named=True):
        ys = [row[f"rank_{k}"] for k in keys]
        is_focal = focal_catchment is not None and row["catchment_name"] == focal_catchment
        ax.plot(
            xs,
            ys,
            color=SERIES_BLUE if is_focal else NEUTRAL_MID,
            linewidth=2.4 if is_focal else 1.0,
            alpha=1.0 if is_focal else 0.55,
            marker="o",
            markersize=6 if is_focal else 4,
            markerfacecolor=SERIES_BLUE if is_focal else NEUTRAL_MID,
            markeredgecolor=SURFACE,
            markeredgewidth=1.2,
            zorder=5 if is_focal else 2,
        )

    # Label the ends only — a label on every point would collide forty times over.
    for row in ranked.iter_rows(named=True):
        is_focal = focal_catchment is not None and row["catchment_name"] == focal_catchment
        weight = "bold" if is_focal else "normal"
        colour = INK_PRIMARY if is_focal else INK_SECONDARY
        ax.annotate(
            _shorten(row["catchment_name"]),
            xy=(xs[0], row[f"rank_{keys[0]}"]),
            xytext=(-8, 0),
            textcoords="offset points",
            ha="right",
            va="center",
            fontsize=7,
            color=colour,
            fontweight=weight,
        )
        ax.annotate(
            _shorten(row["catchment_name"]),
            xy=(xs[-1], row[f"rank_{keys[-1]}"]),
            xytext=(8, 0),
            textcoords="offset points",
            ha="left",
            va="center",
            fontsize=7,
            color=colour,
            fontweight=weight,
        )

    ax.set_xticks(xs)
    ax.set_xticklabels([f"{p.label}\n{p.span_label}" for p in periods], fontsize=9,
                       color=INK_SECONDARY)
    ax.set_xlim(-0.9, len(keys) - 0.1)
    ax.invert_yaxis()
    ax.set_ylabel("Rank on median £/m²  (1 = most expensive)", fontsize=9,
                  color=INK_SECONDARY)
    ax.tick_params(axis="y", colors=INK_SECONDARY, labelsize=8)
    ax.tick_params(axis="x", length=0)
    for spine in ("top", "right", "bottom"):
        ax.spines[spine].set_visible(False)
    ax.spines["left"].set_color(HAIRLINE)

    if focal_catchment:
        ax.legend(
            handles=[
                Line2D([], [], color=SERIES_BLUE, linewidth=2.4, marker="o",
                       markersize=6, label=focal_catchment)
            ],
            loc="lower left",
            frameon=True,
            facecolor=SURFACE,
            edgecolor=HAIRLINE,
            framealpha=1.0,
            fontsize=8.5,
            labelcolor=INK_SECONDARY,
        )

    _frame(
        fig,
        "Where each catchment ranks on price per m², over time",
        "Only catchments reportable in every period are shown",
        stand_in_note,
    )
    return fig


def _shorten(name: str, limit: int = 30) -> str:
    """Trim a catchment name to fit as an end label."""
    return name if len(name) <= limit else name[: limit - 1] + "…"


def _frame(fig, title: str, subtitle: str, stand_in_note: str | None) -> None:
    """Apply the shared title block and source note."""
    fig.suptitle(title, x=0.01, y=0.995, ha="left", fontsize=16,
                 fontweight="bold", color=INK_PRIMARY)
    text = f"{stand_in_note}\n{subtitle}" if stand_in_note else subtitle
    if text.strip():
        fig.text(0.01, 0.973, text, ha="left", va="top", fontsize=9,
                 color=INK_SECONDARY)
    fig.text(
        0.01,
        0.002,
        "Prices: HM Land Registry Price Paid (category A only), Open Government Licence. "
        "Floor areas: EPC domestic register. "
        "Boundaries: North Yorkshire Council (FOI/EIR release).",
        ha="left",
        fontsize=7,
        color=INK_MUTED,
    )
    fig.tight_layout(rect=(0, 0.012, 1, 0.955))
