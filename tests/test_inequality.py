"""Tests for the inequality measures and the adjacency logic."""

from __future__ import annotations

import numpy as np
import polars as pl
import pytest

from ny_catchments.inequality import (
    decompose_dispersion,
    gini,
    lsoa_adjacency,
    neighbouring_contrasts,
)


class TestGini:
    def test_perfect_equality_is_zero(self):
        assert gini(np.array([100.0, 100.0, 100.0])) == pytest.approx(0.0)

    def test_maximal_concentration_approaches_one(self):
        # One holder of everything, n-1 with nothing: Gini -> (n-1)/n.
        values = np.array([0.0] * 99 + [100.0])
        assert gini(values) == pytest.approx(0.99, abs=1e-9)

    def test_known_value(self):
        # For the uniform sequence 1..n, Gini is (n-1)/(3n).
        n = 100
        values = np.arange(1, n + 1, dtype=float)
        assert gini(values) == pytest.approx((n - 1) / (3 * n), abs=1e-9)

    def test_scale_invariance(self):
        values = np.array([1.0, 2.0, 3.0, 10.0])
        assert gini(values) == pytest.approx(gini(values * 1000))

    def test_empty_raises(self):
        with pytest.raises(ValueError, match="empty"):
            gini(np.array([]))

    def test_negative_raises(self):
        with pytest.raises(ValueError, match="negative"):
            gini(np.array([1.0, -2.0]))


class TestAdjacency:
    @staticmethod
    def _points(rows):
        return pl.DataFrame(
            rows,
            schema={
                "lsoa21cd": pl.Utf8,
                "postcode_key": pl.Utf8,
                "easting": pl.Float64,
                "northing": pl.Float64,
            },
            orient="row",
        )

    def test_close_lsoas_are_adjacent(self):
        points = self._points(
            [
                ("A", "P1", 400_000.0, 400_000.0),
                ("B", "P2", 400_300.0, 400_000.0),
            ]
        )
        result = lsoa_adjacency(points, distance_m=500)
        assert result.height == 1
        assert result["min_distance_m"][0] == pytest.approx(300.0)

    def test_distant_lsoas_are_not_adjacent(self):
        points = self._points(
            [
                ("A", "P1", 400_000.0, 400_000.0),
                ("B", "P2", 408_000.0, 400_000.0),
            ]
        )
        assert lsoa_adjacency(points, distance_m=500).height == 0

    def test_pair_is_reported_once_not_twice(self):
        # The self-join yields (A,B) and (B,A); they must collapse.
        points = self._points(
            [
                ("A", "P1", 400_000.0, 400_000.0),
                ("A", "P2", 400_050.0, 400_000.0),
                ("B", "P3", 400_200.0, 400_000.0),
            ]
        )
        result = lsoa_adjacency(points, distance_m=500)
        assert result.height == 1
        # The minimum over all postcode pairs, not the first found.
        assert result["min_distance_m"][0] == pytest.approx(150.0)


class TestNeighbouringContrasts:
    @staticmethod
    def _profile(rows):
        return pl.DataFrame(
            rows,
            schema={
                "lsoa21cd": pl.Utf8,
                "catchment_name": pl.Utf8,
                "median_price_per_m2": pl.Float64,
                "imd_rank": pl.Float64,
                "easting": pl.Float64,
                "northing": pl.Float64,
                "n_priced": pl.UInt32,
            },
            orient="row",
        )

    @staticmethod
    def _adjacency(rows):
        return pl.DataFrame(
            rows,
            schema={"lsoa_a": pl.Utf8, "lsoa_b": pl.Utf8, "min_distance_m": pl.Float64},
            orient="row",
        )

    def test_richer_and_poorer_sides_are_ordered(self):
        profile = self._profile(
            [
                ("A", "Catch", 4000.0, 30000.0, 0.0, 0.0, 50),
                ("B", "Catch", 2000.0, 5000.0, 100.0, 0.0, 50),
            ]
        )
        result = neighbouring_contrasts(profile, self._adjacency([("A", "B", 100.0)]))
        assert result.height == 1
        row = result.row(0, named=True)
        assert row["richer_lsoa"] == "A"
        assert row["poorer_lsoa"] == "B"
        assert row["price_ratio"] == pytest.approx(2.0)
        assert row["imd_gap"] == pytest.approx(25000.0)

    def test_pairs_across_catchments_are_excluded(self):
        # The question is about division inside a catchment, not across its edge.
        profile = self._profile(
            [
                ("A", "Catch one", 4000.0, 30000.0, 0.0, 0.0, 50),
                ("B", "Catch two", 2000.0, 5000.0, 100.0, 0.0, 50),
            ]
        )
        result = neighbouring_contrasts(profile, self._adjacency([("A", "B", 100.0)]))
        assert result.height == 0

    def test_negative_imd_gap_when_pricier_side_is_more_deprived(self):
        # Price and deprivation are different axes and do diverge in the real
        # data; the sign has to survive rather than be normalised away.
        profile = self._profile(
            [
                ("A", "Catch", 4000.0, 5000.0, 0.0, 0.0, 50),
                ("B", "Catch", 2000.0, 20000.0, 100.0, 0.0, 50),
            ]
        )
        result = neighbouring_contrasts(profile, self._adjacency([("A", "B", 100.0)]))
        assert result["imd_gap"][0] == pytest.approx(-15000.0)


class TestDecomposition:
    def test_all_variation_between_neighbourhoods(self):
        # Two LSOAs, each internally uniform: every bit of spread is between.
        transactions = pl.DataFrame(
            {
                "catchment_name": ["C"] * 6,
                "lsoa21cd": ["A", "A", "A", "B", "B", "B"],
                "price_per_m2": [2000.0] * 3 + [4000.0] * 3,
            }
        )
        profile = pl.DataFrame(
            {"lsoa21cd": ["A", "B"], "catchment_name": ["C", "C"]}
        )
        result = decompose_dispersion(transactions, profile, min_lsoas=2)
        assert result["between_share"][0] == pytest.approx(1.0)

    def test_no_variation_between_neighbourhoods(self):
        # Identical spread in both LSOAs: none of it is geographic.
        transactions = pl.DataFrame(
            {
                "catchment_name": ["C"] * 6,
                "lsoa21cd": ["A", "A", "A", "B", "B", "B"],
                "price_per_m2": [1000.0, 2000.0, 4000.0] * 2,
            }
        )
        profile = pl.DataFrame(
            {"lsoa21cd": ["A", "B"], "catchment_name": ["C", "C"]}
        )
        result = decompose_dispersion(transactions, profile, min_lsoas=2)
        assert result["between_share"][0] == pytest.approx(0.0, abs=1e-12)

    def test_catchment_with_too_few_lsoas_is_dropped(self):
        transactions = pl.DataFrame(
            {
                "catchment_name": ["C"] * 3,
                "lsoa21cd": ["A", "A", "A"],
                "price_per_m2": [1000.0, 2000.0, 3000.0],
            }
        )
        profile = pl.DataFrame({"lsoa21cd": ["A"], "catchment_name": ["C"]})
        assert decompose_dispersion(transactions, profile, min_lsoas=3).height == 0


class TestHedonic:
    """The composition adjustment must remove stock effects, not price effects."""

    @staticmethod
    def _sales(rows):
        return pl.DataFrame(
            rows,
            schema={
                "price_per_m2": pl.Float64,
                "property_type": pl.Utf8,
                "old_new": pl.Utf8,
                "duration": pl.Utf8,
                "lsoa21cd": pl.Utf8,
                "catchment_name": pl.Utf8,
                "floor_area_m2": pl.Float64,
            },
            orient="row",
        )

    def test_pure_composition_difference_is_fully_absorbed(self):
        """Two areas differing only in stock type must show no residual gap.

        Detached sells above terraced everywhere. If one area is all detached
        and the other all terraced, at the same type-specific prices, the
        residual medians must coincide — the gap is composition, not place.
        """
        from ny_catchments.divides import hedonic_residuals, lsoa_composition

        rows = []
        for _ in range(20):
            rows.append((4000.0, "D", "N", "F", "A", "C", 100.0))
            rows.append((2000.0, "T", "N", "F", "B", "C", 100.0))
        residualised = hedonic_residuals(self._sales(rows))
        composition = lsoa_composition(residualised, min_sales=5)

        medians = dict(
            zip(
                composition["lsoa21cd"],
                composition["median_residual"],
                strict=True,
            )
        )
        assert medians["A"] == pytest.approx(medians["B"], abs=1e-9)

    def test_location_difference_survives_adjustment(self):
        # Same stock on both sides, different prices: this is a place effect and
        # must not be explained away.
        from ny_catchments.divides import hedonic_residuals, lsoa_composition

        rows = []
        for _ in range(20):
            rows.append((4000.0, "T", "N", "F", "A", "C", 100.0))
            rows.append((2000.0, "T", "N", "F", "B", "C", 100.0))
        residualised = hedonic_residuals(self._sales(rows))
        composition = lsoa_composition(residualised, min_sales=5)
        medians = dict(
            zip(composition["lsoa21cd"], composition["median_residual"], strict=True)
        )
        gap = medians["A"] - medians["B"]
        assert np.exp(gap) == pytest.approx(2.0, rel=1e-6)


class TestVarianceByLevel:
    def test_between_share_is_one_when_groups_are_internally_uniform(self):
        from ny_catchments.divides import variance_by_level

        frame = pl.DataFrame(
            {
                "price_per_m2": [1000.0] * 4 + [4000.0] * 4,
                "lsoa21cd": ["A"] * 4 + ["B"] * 4,
            }
        )
        result = variance_by_level(frame, levels=("lsoa21cd",))
        assert result["between_share"][0] == pytest.approx(1.0)

    def test_between_share_is_zero_when_groups_are_identical(self):
        from ny_catchments.divides import variance_by_level

        frame = pl.DataFrame(
            {
                "price_per_m2": [1000.0, 4000.0] * 4,
                "lsoa21cd": ["A", "A", "B", "B"] * 2,
            }
        )
        result = variance_by_level(frame, levels=("lsoa21cd",))
        assert result["between_share"][0] == pytest.approx(0.0, abs=1e-12)
