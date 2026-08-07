"""Tests for EPC address parsing and the floor-area join."""

from __future__ import annotations

import polars as pl
import pytest

from ny_catchments.epc import attach_floor_areas, parse_address


class TestParseAddress:
    def test_plain_house_number(self):
        assert parse_address("31")["building"] == "31"

    def test_number_with_letter_suffix(self):
        assert parse_address("31A ALDRICH DRIVE")["building"] == "31A"

    def test_flat_prefix_gives_flat_not_building(self):
        # "Flat 2 Escalada" names the flat, not the building. Reading 2 as the
        # building number is the classic failure mode of this join.
        parsed = parse_address("Flat 2 Escalada")
        assert parsed["flat"] == "2"
        assert parsed["building"] is None

    def test_flat_prefix_with_following_building_number(self):
        parsed = parse_address("Flat 5, 130 High Street")
        assert parsed["flat"] == "5"
        assert parsed["building"] == "130"

    def test_price_paid_splits_building_and_flat(self):
        parsed = parse_address("130", "FLAT 2")
        assert parsed["building"] == "130"
        assert parsed["flat"] == "2"

    def test_trailing_number_after_building_name(self):
        # Price Paid writes "HERONS COURT, 37" often enough to matter.
        assert parse_address("HERONS COURT, 37")["building"] == "37"

    def test_stopwords_excluded_from_name_token(self):
        # "COURT" and "THE" identify nothing on their own.
        assert parse_address("THE OLD COURT HOUSE")["name"] == "OLD"

    def test_named_property_with_no_number(self):
        parsed = parse_address("ROSE COTTAGE")
        assert parsed["building"] is None
        assert parsed["name"] == "ROSE"


class TestAttachFloorAreas:
    @staticmethod
    def _transactions(rows):
        return pl.DataFrame(
            rows,
            schema={"postcode_key": pl.Utf8, "paon": pl.Utf8, "saon": pl.Utf8, "price": pl.Int64},
            orient="row",
        )

    @staticmethod
    def _floor_areas(rows):
        return pl.DataFrame(
            rows,
            schema={
                "postcode_key": pl.Utf8,
                "building": pl.Utf8,
                "flat": pl.Utf8,
                "name_token": pl.Utf8,
                "floor_area_m2": pl.Float64,
            },
            orient="row",
        )

    def test_house_with_no_flat_number_still_matches(self):
        """Regression: polars joins with join_nulls=False by default.

        A house has no flat number on either side, so leaving those keys as
        nulls means the join silently drops every house while continuing to
        match flats — inverting the expected match rates.
        """
        transactions = self._transactions([("YO269RG", "12", None, 300_000)])
        floor_areas = self._floor_areas([("YO269RG", "12", None, "ELM", 90.0)])

        result = attach_floor_areas(transactions, floor_areas)

        assert result["floor_area_m2"][0] == 90.0
        assert result["price_per_m2"][0] == pytest.approx(300_000 / 90.0)

    def test_flat_matches_on_flat_number(self):
        transactions = self._transactions([("YO269RG", "130", "FLAT 2", 200_000)])
        floor_areas = self._floor_areas([("YO269RG", "130", "2", None, 55.0)])

        result = attach_floor_areas(transactions, floor_areas)
        assert result["floor_area_m2"][0] == 55.0

    def test_named_property_falls_back_to_name_token(self):
        # No number in either register, so only the name key can match.
        transactions = self._transactions([("YO269RG", "ROSE COTTAGE", None, 400_000)])
        floor_areas = self._floor_areas([("YO269RG", None, None, "ROSE", 120.0)])

        result = attach_floor_areas(transactions, floor_areas)
        assert result["floor_area_m2"][0] == 120.0

    def test_unmatched_row_yields_null_not_error(self):
        transactions = self._transactions([("YO269RG", "99", None, 250_000)])
        floor_areas = self._floor_areas([("YO269RG", "12", None, "ELM", 90.0)])

        result = attach_floor_areas(transactions, floor_areas)
        assert result["floor_area_m2"][0] is None
        assert result["price_per_m2"][0] is None


class TestAmbiguousMatching:
    """The join must refuse a guess rather than attach the wrong floor area."""

    @staticmethod
    def _t(rows):
        return pl.DataFrame(
            rows,
            schema={"postcode_key": pl.Utf8, "paon": pl.Utf8, "saon": pl.Utf8, "price": pl.Int64},
            orient="row",
        )

    @staticmethod
    def _fa(rows):
        return pl.DataFrame(
            rows,
            schema={
                "postcode_key": pl.Utf8,
                "building": pl.Utf8,
                "flat": pl.Utf8,
                "name_token": pl.Utf8,
                "floor_area_m2": pl.Float64,
            },
            orient="row",
        )

    def test_unnumbered_property_does_not_match_a_neighbour(self):
        # Two named houses share a postcode and neither has a number. The empty
        # key (postcode, "", "") describes both, so it must not match either.
        transactions = self._t([("YO269RG", "ROSE COTTAGE", None, 400_000)])
        floor_areas = self._fa(
            [
                ("YO269RG", None, None, "LAUREL", 80.0),
                ("YO269RG", None, None, "IVY", 200.0),
            ]
        )
        result = attach_floor_areas(transactions, floor_areas)
        assert result["floor_area_m2"][0] is None

    def test_ambiguous_name_match_is_labelled_as_the_loosest_tier(self):
        # "ROSE" cannot distinguish Rose Cottage from Rosebank, so this match is
        # a genuine approximation. It is allowed, but must be recorded as coming
        # from the loosest tier so the report can show how much rests on it —
        # silently refusing would bias against named rural properties, and
        # silently accepting would hide the looseness.
        transactions = self._t([("YO269RG", "ROSE COTTAGE", None, 400_000)])
        floor_areas = self._fa(
            [
                ("YO269RG", None, None, "ROSE", 90.0),
                ("YO269RG", None, None, "ROSE", 250.0),
            ]
        )
        result = attach_floor_areas(transactions, floor_areas)
        assert result["match_tier"][0] == "name"
        assert result["floor_area_m2"][0] == 170.0  # median of the candidates

    def test_flat_matches_when_epc_has_no_building_number(self):
        # The commonest EPC flat record is an address line reading simply
        # "Flat 2", with no building number at all, while Price Paid carries the
        # building in PAON. Without the flat tier this never matches — and the
        # gap falls entirely on flats.
        transactions = self._t([("YO269RG", "130", "FLAT 2", 200_000)])
        floor_areas = self._fa([("YO269RG", None, "2", None, 55.0)])

        result = attach_floor_areas(transactions, floor_areas)
        assert result["floor_area_m2"][0] == 55.0
        assert result["match_tier"][0] == "flat"

    def test_row_count_is_preserved(self):
        # An unmatched transaction is evidence about coverage, not a row to drop.
        transactions = self._t(
            [
                ("YO269RG", "12", None, 300_000),
                ("YO269RG", "99", None, 250_000),
                ("YO519AA", "ROSE COTTAGE", None, 400_000),
            ]
        )
        floor_areas = self._fa([("YO269RG", "12", None, "ELM", 90.0)])

        result = attach_floor_areas(transactions, floor_areas)
        assert result.height == 3
        assert result["floor_area_m2"].is_not_null().sum() == 1

    def test_numbered_property_unaffected_by_the_restriction(self):
        transactions = self._t([("YO269RG", "12", None, 300_000)])
        floor_areas = self._fa(
            [
                ("YO269RG", "12", None, "ELM", 90.0),
                ("YO269RG", None, None, "IVY", 200.0),
            ]
        )
        result = attach_floor_areas(transactions, floor_areas)
        assert result["floor_area_m2"][0] == 90.0
