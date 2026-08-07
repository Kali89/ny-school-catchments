"""Rendering the catchment map.

Design notes
------------
The data's job here is *identity and location* — show where the boundaries fall
and where one school sits inside them — not magnitude. So this is deliberately
not a choropleth: context polygons carry a single recessive neutral fill, and
exactly one hue is spent on the focal catchment. When house prices are joined in
(the eventual goal), that hue budget is what a sequential ramp will occupy.

Colours are the validated defaults: series blue #2a78d6 (passes lightness band,
CVD separation, and 3:1 contrast against the #fcfcfb surface), with neutral ink
and hairlines for chrome.
"""

from __future__ import annotations

import geopandas as gpd
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from shapely.geometry import Point, box

from .config import (
    DEFAULT_RADIUS_M,
    FOCUS_EASTING,
    FOCUS_NORTHING,
    FOCUS_SCHOOL_NAME,
    LayerSpec,
)
from .io import NAME_FIELD

# --- Palette (validated defaults; see references/palette.md) ---
SURFACE = "#fcfcfb"
INK_PRIMARY = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#898781"
HAIRLINE = "#e1e0d9"

SERIES_BLUE = "#2a78d6"
CONTEXT_FILL = "#f0efec"  # neutral midpoint — context, not a series

plt.rcParams.update(
    {
        # Concrete families matplotlib can actually resolve — it does not
        # understand the CSS "system-ui" keyword and silently falls back.
        "font.family": ["Helvetica Neue", "Helvetica", "Arial", "DejaVu Sans"],
        "figure.facecolor": SURFACE,
        "axes.facecolor": SURFACE,
    }
)


def _window(radius_m: float) -> box:
    """Square map window centred on the focal school, in BNG metres."""
    return box(
        FOCUS_EASTING - radius_m,
        FOCUS_NORTHING - radius_m,
        FOCUS_EASTING + radius_m,
        FOCUS_NORTHING + radius_m,
    )


def _add_scale_bar(ax, radius_m: float) -> None:
    """Draw a simple metric scale bar in the lower-left of the axes."""
    # A bar roughly a fifth of the window, rounded to a tidy kilometre count.
    span_km = max(1, round((radius_m * 2 / 5) / 1000))
    x0 = FOCUS_EASTING - radius_m * 0.92
    y0 = FOCUS_NORTHING - radius_m * 0.90
    ax.plot(
        [x0, x0 + span_km * 1000], [y0, y0], color=INK_SECONDARY, linewidth=2, solid_capstyle="butt"
    )
    ax.text(
        x0 + span_km * 500,
        y0 + radius_m * 0.025,
        f"{span_km} km",
        ha="center",
        va="bottom",
        fontsize=8,
        color=INK_SECONDARY,
    )


def plot_catchments(
    gdf: gpd.GeoDataFrame,
    spec: LayerSpec,
    radius_m: float = DEFAULT_RADIUS_M,
    stand_in_note: str | None = None,
):
    """Render catchment boundaries around the focal school.

    Args:
        gdf: Catchment polygons in EPSG:27700.
        spec: The layer being drawn, used for the name field and title.
        radius_m: Half-width of the square map window, in metres.
        stand_in_note: If set, a caveat line printed under the title. Used when
            the layer on screen is not the one actually wanted.

    Returns:
        The matplotlib Figure.
    """
    window = _window(radius_m)
    school = Point(FOCUS_EASTING, FOCUS_NORTHING)

    # Clip to the window so labels and extents follow what is actually visible.
    visible = gdf[gdf.intersects(window)].copy()
    visible["geometry"] = visible.geometry.intersection(window)
    visible = visible[~visible.geometry.is_empty]

    # The focal catchment is the polygon containing the school. With the primary
    # layer this is Great Ouseburn's own catchment; with any other layer it is
    # simply whichever catchment the school's coordinates fall inside.
    contains = visible.geometry.contains(school)
    focal = visible[contains]
    context = visible[~contains]

    fig, ax = plt.subplots(figsize=(11, 11), dpi=200)

    context.plot(ax=ax, facecolor=CONTEXT_FILL, edgecolor=SURFACE, linewidth=1.4, zorder=1)
    # A hairline over the white separator keeps boundaries legible where two
    # context polygons meet without competing with the focal outline.
    context.boundary.plot(ax=ax, color=INK_MUTED, linewidth=0.5, alpha=0.7, zorder=2)

    if not focal.empty:
        focal.plot(
            ax=ax, facecolor=SERIES_BLUE, alpha=0.18, edgecolor="none", zorder=3
        )
        focal.boundary.plot(ax=ax, color=SERIES_BLUE, linewidth=2.0, zorder=4)

    # Selective direct labels: only polygons with enough visible area to hold text.
    threshold = visible.geometry.area.quantile(0.55) if len(visible) > 3 else 0
    for _, row in visible.iterrows():
        if row.geometry.area < threshold:
            continue
        pt = row.geometry.representative_point()
        is_focal = bool(row.geometry.contains(school))
        # The focal catchment's representative point often lands near the school
        # marker (both sit toward the middle of the polygon). Lift its label clear
        # so the two never overprint.
        label_y = pt.y + radius_m * 0.10 if is_focal else pt.y
        ax.annotate(
            _wrap_name(str(row[NAME_FIELD]).strip()),
            xy=(pt.x, label_y),
            ha="center",
            va="center",
            fontsize=7.5 if not is_focal else 8.5,
            color=INK_PRIMARY if is_focal else INK_SECONDARY,
            fontweight="bold" if is_focal else "normal",
            zorder=6,
        )

    # School marker: 2px surface ring so it reads over any fill beneath it.
    ax.scatter(
        [school.x],
        [school.y],
        s=90,
        color=INK_PRIMARY,
        edgecolor=SURFACE,
        linewidth=2,
        zorder=7,
    )
    ax.annotate(
        FOCUS_SCHOOL_NAME,
        xy=(school.x, school.y),
        xytext=(0, -15),
        textcoords="offset points",
        ha="center",
        va="top",
        fontsize=9,
        fontweight="bold",
        color=INK_PRIMARY,
        zorder=8,
    )

    ax.set_xlim(FOCUS_EASTING - radius_m, FOCUS_EASTING + radius_m)
    ax.set_ylim(FOCUS_NORTHING - radius_m, FOCUS_NORTHING + radius_m)
    ax.set_aspect("equal")
    ax.set_axis_off()

    _add_scale_bar(ax, radius_m)

    # Legend: identity is never carried by colour alone.
    handles = [
        Patch(facecolor=CONTEXT_FILL, edgecolor=INK_MUTED, linewidth=0.5,
              label=f"{spec.phase_label} catchment"),
        Patch(facecolor=SERIES_BLUE, alpha=0.18, edgecolor=SERIES_BLUE, linewidth=2.0,
              label="Catchment containing the school"),
        Line2D([], [], marker="o", linestyle="none", markersize=8,
               markerfacecolor=INK_PRIMARY, markeredgecolor=SURFACE, markeredgewidth=2,
               label=FOCUS_SCHOOL_NAME),
    ]
    # An opaque legend box: the map fills the frame edge to edge, so a frameless
    # legend would sit directly on top of boundary lines.
    legend = ax.legend(
        handles=handles,
        loc="upper left",
        frameon=True,
        facecolor=SURFACE,
        edgecolor=HAIRLINE,
        framealpha=1.0,
        borderpad=0.8,
        fontsize=8.5,
        labelcolor=INK_SECONDARY,
    )
    legend.set_zorder(10)

    title = f"{spec.phase_label} school catchments around Great Ouseburn"
    fig.suptitle(title, x=0.06, y=0.955, ha="left", fontsize=17,
                 fontweight="bold", color=INK_PRIMARY)

    subtitle = "North Yorkshire Council catchment boundaries · British National Grid"
    if stand_in_note:
        subtitle = f"{stand_in_note}\n{subtitle}"
    fig.text(0.06, 0.925, subtitle, ha="left", va="top", fontsize=9.5, color=INK_SECONDARY)

    fig.text(
        0.06,
        0.045,
        "Boundaries: North Yorkshire Council (FOI/EIR release). "
        "School location: DfE Get Information About Schools, URN 121393.",
        ha="left",
        fontsize=7.5,
        color=INK_MUTED,
    )

    fig.subplots_adjust(top=0.88, bottom=0.08, left=0.06, right=0.94)
    return fig


def _wrap_name(name: str, width: int = 22) -> str:
    """Soft-wrap a school name onto at most three lines for in-map labelling."""
    words, lines, current = name.split(), [], ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) > width and current:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    if len(lines) > 3:
        lines = lines[:3]
        lines[-1] += "…"
    return "\n".join(lines)
