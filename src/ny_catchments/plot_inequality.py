"""Figures for inequality within catchments and where it is geographic."""

from __future__ import annotations

import geopandas as gpd
import matplotlib.pyplot as plt
import polars as pl
from matplotlib.colors import BoundaryNorm, ListedColormap
from matplotlib.lines import Line2D

from .io import NAME_FIELD
from .plot import (
    HAIRLINE,
    INK_MUTED,
    INK_PRIMARY,
    INK_SECONDARY,
    SEQUENTIAL_BLUE,
    SERIES_BLUE,
    SURFACE,
)
from .plot_prices import _frame

BAR_FILL = "#86b6ef"
ACCENT = "#e34948"


def plot_inequality_ranking(
    inequality: pl.DataFrame,
    focal_catchment: str | None = None,
    stand_in_note: str | None = None,
):
    """Ranked bar of P90/P10 in price per m², one row per catchment.

    P90/P10 leads rather than Gini because it states itself: "the top tenth of
    homes cost N times the bottom tenth per square metre". Gini is reported in
    the accompanying table for comparability, but it is not a sentence anyone
    can act on.

    Args:
        inequality: Output of `inequality.catchment_inequality`.
        focal_catchment: Catchment to highlight, if any.
        stand_in_note: Caveat line shown above the subtitle.

    Returns:
        The matplotlib Figure.
    """
    ordered = inequality.sort("p90_p10")
    names = ordered["catchment_name"].to_list()
    values = ordered["p90_p10"].to_list()
    counts = ordered["n_priced"].to_list()

    height = max(6.0, 0.32 * len(names) + 3.0)
    fig, ax = plt.subplots(figsize=(12.5, height), dpi=200)

    colours = [
        SERIES_BLUE if focal_catchment and n == focal_catchment else BAR_FILL
        for n in names
    ]
    positions = list(range(len(names)))
    ax.barh(positions, values, color=colours, height=0.66, zorder=2)

    typical = ordered["p90_p10"].median()
    ax.axvline(typical, color=INK_SECONDARY, linewidth=1.2, linestyle=(0, (4, 3)), zorder=3)
    ax.text(
        typical,
        1.004,
        f"Typical catchment  {typical:.2f}×",
        transform=ax.get_xaxis_transform(),
        ha="center",
        va="bottom",
        fontsize=8.5,
        color=INK_SECONDARY,
        clip_on=False,
    )

    for pos, value, count in zip(positions, values, counts, strict=True):
        ax.annotate(
            f"{value:.2f}×",
            xy=(value, pos),
            xytext=(4, 0),
            textcoords="offset points",
            va="center",
            fontsize=7.5,
            color=INK_SECONDARY,
        )

    ax.set_yticks(positions)
    ax.set_yticklabels(
        [f"{n}  (n={c:,})" for n, c in zip(names, counts, strict=True)], fontsize=8
    )
    ax.tick_params(axis="y", length=0, colors=INK_SECONDARY)
    ax.tick_params(axis="x", colors=INK_SECONDARY, labelsize=8.5)
    ax.set_xlim(1.0, max(values) * 1.08)
    ax.xaxis.set_major_formatter(lambda v, _: f"{v:.1f}×")
    ax.set_xlabel(
        "Ratio of the 90th to the 10th percentile of price per m²  "
        "(1.0× would mean every home costs the same per m²)",
        fontsize=9,
        color=INK_SECONDARY,
    )
    ax.grid(axis="x", color=HAIRLINE, linewidth=0.8, zorder=0)
    ax.set_axisbelow(True)
    for spine in ("top", "right", "left"):
        ax.spines[spine].set_visible(False)
    ax.spines["bottom"].set_color(HAIRLINE)

    _frame(
        fig,
        "How unequal is each school catchment?",
        "Spread of price per m² within the catchment · last 5 years (2021–2025)",
        stand_in_note,
    )
    return fig


def plot_inequality_vs_price(
    inequality: pl.DataFrame,
    decomposition: pl.DataFrame,
    correlation: float,
    focal_catchment: str | None = None,
    stand_in_note: str | None = None,
):
    """Scatter of catchment price level against inequality.

    Args:
        inequality: Output of `inequality.catchment_inequality`.
        decomposition: Output of `inequality.decompose_dispersion`, used to mark
            which catchments' inequality is geographic.
        focal_catchment: Catchment to highlight, if any.
        stand_in_note: Caveat line shown above the subtitle.

    Returns:
        The matplotlib Figure.
    """
    merged = inequality.join(decomposition, on="catchment_name", how="left")

    fig, ax = plt.subplots(figsize=(11, 8), dpi=200)

    x = merged["median_price_per_m2"].to_list()
    y = merged["p90_p10"].to_list()
    share = [s if s is not None else 0.0 for s in merged["between_share"].to_list()]

    # Colour carries the between-LSOA share: dark means the inequality is mostly
    # geographic — distinct richer and poorer neighbourhoods rather than mixing.
    edges = [0.0, 0.1, 0.2, 0.3, 0.5, 1.0]
    colours = [SEQUENTIAL_BLUE[i] for i in (0, 3, 6, 8, 11)]
    cmap = ListedColormap(colours)
    norm = BoundaryNorm(edges, ncolors=len(colours), clip=True)

    ax.scatter(x, y, c=share, cmap=cmap, norm=norm, s=90,
               edgecolor=SURFACE, linewidth=1.2, zorder=3)

    # Label only the extremes — a label on all 37 would be unreadable. Just one
    # label at each end of the price axis: the expensive catchments bunch into a
    # single corner at similar inequality, and three labels there overprint no
    # matter how they are nudged. Their position on the axis says it anyway.
    labelled = {
        *merged.sort("p90_p10", descending=True)["catchment_name"][:3],
        *merged.sort("p90_p10")["catchment_name"][:2],
        merged.sort("median_price_per_m2")["catchment_name"][0],
        merged.sort("median_price_per_m2", descending=True)["catchment_name"][0],
    }
    if focal_catchment:
        labelled.add(focal_catchment)

    # Alternate labels above and below, and anchor those near the right edge to
    # the left of their point. Several of the labelled catchments are the
    # expensive ones, which cluster in the same corner and otherwise overprint.
    to_label = merged.filter(pl.col("catchment_name").is_in(list(labelled))).sort(
        "median_price_per_m2"
    )
    x_span = max(x) - min(x)
    for i, row in enumerate(to_label.iter_rows(named=True)):
        name = row["catchment_name"]
        is_focal = name == focal_catchment
        near_right = row["median_price_per_m2"] > min(x) + 0.78 * x_span
        offset_y = 12 if i % 2 == 0 else -16
        ax.annotate(
            _short(name),
            xy=(row["median_price_per_m2"], row["p90_p10"]),
            xytext=(-10 if near_right else 0, offset_y),
            textcoords="offset points",
            ha="right" if near_right else "center",
            fontsize=7.5,
            color=INK_PRIMARY if is_focal else INK_SECONDARY,
            fontweight="bold" if is_focal else "normal",
        )
        if is_focal:
            ax.scatter([row["median_price_per_m2"]], [row["p90_p10"]], s=170,
                       facecolor="none", edgecolor=SERIES_BLUE, linewidth=2.2, zorder=4)

    ax.set_xlabel("Median price per m²", fontsize=9, color=INK_SECONDARY)
    ax.set_ylabel("Inequality within the catchment (P90 ÷ P10)", fontsize=9,
                  color=INK_SECONDARY)
    ax.xaxis.set_major_formatter(lambda v, _: f"£{v:,.0f}")
    ax.yaxis.set_major_formatter(lambda v, _: f"{v:.1f}×")
    ax.tick_params(colors=INK_SECONDARY, labelsize=8.5)
    ax.grid(color=HAIRLINE, linewidth=0.8, zorder=0)
    ax.set_axisbelow(True)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    for spine in ("left", "bottom"):
        ax.spines[spine].set_color(HAIRLINE)

    handles = [
        Line2D([], [], marker="o", linestyle="none", markersize=9,
               markerfacecolor=colours[i], markeredgecolor=SURFACE,
               label=f"{edges[i]:.0%}–{edges[i + 1]:.0%}")
        for i in range(len(colours))
    ]
    legend = ax.legend(
        handles=handles,
        title="Share of the spread that is\nbetween neighbourhoods",
        loc="upper right",
        frameon=True,
        facecolor=SURFACE,
        edgecolor=HAIRLINE,
        framealpha=1.0,
        fontsize=8,
        labelcolor=INK_SECONDARY,
    )
    legend.get_title().set_fontsize(8.5)
    legend.get_title().set_color(INK_PRIMARY)

    _frame(
        fig,
        "How unequal a catchment is barely follows how expensive it is",
        f"Each point is a catchment · Spearman correlation {correlation:+.2f} · "
        f"last 5 years (2021–2025)",
        stand_in_note,
    )
    return fig


def plot_divided_catchments(
    catchments: gpd.GeoDataFrame,
    profile: pl.DataFrame,
    divides: pl.DataFrame,
    n_panels: int = 4,
    stand_in_note: str | None = None,
):
    """Small multiples of the catchments with the sharpest neighbouring contrast.

    Each panel shows one catchment, its neighbourhoods as points positioned at
    the centre of their sales and shaded by price per m², and a line joining the
    adjacent pair with the largest gap.

    Args:
        catchments: Catchment polygons in EPSG:27700.
        profile: Output of `inequality.lsoa_profile`.
        divides: Output of `inequality.sharpest_divides`.
        n_panels: How many catchments to show.
        stand_in_note: Caveat line shown above the subtitle.

    Returns:
        The matplotlib Figure.

    Raises:
        ValueError: If there is nothing to draw.
    """
    top = divides.head(n_panels)
    if top.height == 0:
        raise ValueError("No neighbouring contrasts to plot.")

    rows = (top.height + 1) // 2
    fig, axes = plt.subplots(rows, 2, figsize=(12, 6.0 * rows), dpi=200)
    axes = axes.ravel() if hasattr(axes, "ravel") else [axes]

    # One shared colour scale across panels, so a dot's shade means the same
    # thing in every catchment and the panels can be compared.
    all_ppm2 = profile["median_price_per_m2"]
    breaks = sorted({round(all_ppm2.quantile(q)) for q in (0.0, 0.25, 0.5, 0.75, 1.0)})
    colours = [SEQUENTIAL_BLUE[i] for i in (1, 5, 8, 11)][: max(len(breaks) - 1, 1)]
    cmap = ListedColormap(colours)
    norm = BoundaryNorm(breaks, ncolors=len(colours), clip=True)

    for ax, row in zip(axes, top.iter_rows(named=True), strict=False):
        name = row["catchment_name"]
        polygon = catchments[catchments[NAME_FIELD].astype(str).str.strip() == name]
        local = profile.filter(pl.col("catchment_name") == name)

        if not polygon.empty:
            polygon.plot(ax=ax, facecolor="#f6f6f4", edgecolor=INK_MUTED,
                         linewidth=1.0, zorder=1)

        ax.scatter(
            local["easting"].to_list(),
            local["northing"].to_list(),
            c=local["median_price_per_m2"].to_list(),
            cmap=cmap,
            norm=norm,
            s=110,
            edgecolor=SURFACE,
            linewidth=1.4,
            zorder=3,
        )

        # The sharpest adjacent pair, drawn as a link between the two.
        ax.plot(
            [row["easting_a"], row["easting_b"]],
            [row["northing_a"], row["northing_b"]],
            color=ACCENT,
            linewidth=2.4,
            zorder=4,
        )
        midpoint = (
            (row["easting_a"] + row["easting_b"]) / 2,
            (row["northing_a"] + row["northing_b"]) / 2,
        )
        ax.annotate(
            f"{row['price_ratio']:.2f}× gap\n"
            f"£{row['richer_ppm2']:,.0f} vs £{row['poorer_ppm2']:,.0f}/m²\n"
            f"{row['min_distance_m']:,.0f} m apart",
            xy=midpoint,
            xytext=(0, 16),
            textcoords="offset points",
            ha="center",
            fontsize=8,
            fontweight="bold",
            color=INK_PRIMARY,
            bbox={"facecolor": SURFACE, "edgecolor": HAIRLINE, "boxstyle": "round,pad=0.4"},
            zorder=6,
        )

        ax.set_title(_short(name, 46), fontsize=10, color=INK_PRIMARY,
                     fontweight="bold", loc="left")
        ax.set_aspect("equal")
        ax.set_axis_off()

    for ax in axes[top.height:]:
        ax.set_visible(False)

    handles = [
        Line2D([], [], marker="o", linestyle="none", markersize=9,
               markerfacecolor=colours[i], markeredgecolor=SURFACE,
               label=f"£{breaks[i]:,.0f}–£{breaks[i + 1]:,.0f}")
        for i in range(len(colours))
    ]
    handles.append(
        Line2D([], [], color=ACCENT, linewidth=2.4, label="Sharpest adjacent gap")
    )
    fig.legend(
        handles=handles,
        title="Neighbourhood median £/m²",
        loc="lower center",
        ncol=len(handles),
        frameon=False,
        fontsize=8.5,
        labelcolor=INK_SECONDARY,
        # Clear of the source note, which _frame places at y=0.002.
        bbox_to_anchor=(0.5, 0.024),
    )

    _frame(
        fig,
        "Rich and poor next door: the sharpest divides inside a catchment",
        "Each dot is a neighbourhood (LSOA, ~650 households) placed at the centre "
        "of its sales · last 5 years",
        stand_in_note,
    )
    return fig


def _short(name: str, limit: int = 26) -> str:
    """Trim a catchment name for use as a point or panel label."""
    return name if len(name) <= limit else name[: limit - 1] + "…"
