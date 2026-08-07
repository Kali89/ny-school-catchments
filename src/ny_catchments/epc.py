"""Floor areas from the EPC domestic register, for price per square metre.

Price Paid carries no floor area, so £/m² needs the EPC register joined on
address. The archive is ~6.5GB compressed and far larger expanded, so each yearly
file is extracted to a temporary path, filtered with DuckDB, and deleted before
the next one is touched.

Address matching
----------------
The two registers describe the same building differently, and the difference is
not cosmetic. Price Paid separates the building ("130") from the dwelling within
it ("FLAT 2") across its PAON and SAON fields. An EPC assessor types a single
line, and for a flat that line usually names the *flat* — "Flat 2 Escalada". A key
built from the leading number therefore picks up the flat number from one source
and the building number from the other, which is why a naive join matches flats
at roughly a third the rate of houses.

This mirrors the approach taken in the sibling asylum-site project so the two
remain comparable.

Coverage limit
--------------
This archive begins in 2012. A dwelling last certified before then — or never
certified, since a certificate is only required on sale or let — has no floor
area here and drops out of the £/m² figures. That is a systematic gap, not a
random one: it skews toward homes that have not changed hands recently.
"""

from __future__ import annotations

import re
import shutil
import tempfile
import zipfile
from pathlib import Path

import duckdb
import polars as pl

from .config import EPC_ZIP

# Columns needed from the certificate files. Selecting a handful keeps parsing
# cost down; the decompression cost is unavoidable.
_EPC_COLUMNS = ["address1", "address2", "postcode", "total_floor_area", "property_type"]

_FLAT_PREFIX = re.compile(r"^\s*(FLAT|APARTMENT|APT|UNIT)\s*([0-9]+[A-Z]?)", re.IGNORECASE)
_LEADING_NUMBER = re.compile(r"^\s*([0-9]+[A-Z]?)\b", re.IGNORECASE)
_ANY_NUMBER = re.compile(r"\b([0-9]+[A-Z]?)\b")

# Words too generic to identify a building on their own.
_STOPWORDS = frozenset(
    {"FLAT", "APARTMENT", "APT", "UNIT", "THE", "HOUSE", "COURT", "ROAD", "STREET"}
)

# A dwelling smaller than this or larger than this is almost certainly a data
# entry error in the EPC register (a decimal point in the wrong place, or a
# whole block recorded against one certificate). Both tails distort £/m² badly.
MIN_FLOOR_AREA_M2 = 15.0
MAX_FLOOR_AREA_M2 = 1_000.0


def parse_address(primary: str | None, secondary: str | None = None) -> dict[str, str | None]:
    """Split an address into the parts that can be matched across registers.

    Args:
        primary: Price Paid PAON, or an EPC address line.
        secondary: Price Paid SAON. Omitted for EPC, which has one line.

    Returns:
        ``building`` (number), ``flat`` (number within the building) and ``name``
        (first distinctive alphabetic token), any of which may be None.
    """
    primary = (primary or "").strip()
    secondary = (secondary or "").strip()

    flat: str | None = None
    building: str | None = None

    prefixed = _FLAT_PREFIX.match(primary)
    if prefixed:
        # "Flat 2 Escalada" — the flat number, then the building number if present.
        flat = prefixed.group(2).upper()
        remainder = primary[prefixed.end() :]
        later = _ANY_NUMBER.search(remainder)
        building = later.group(1).upper() if later else None
    else:
        leading = _LEADING_NUMBER.match(primary)
        if leading:
            building = leading.group(1).upper()
        else:
            # Price Paid often writes "HERONS COURT, 37" — name first, number
            # after. Taking only a leading number would discard it entirely.
            later = _ANY_NUMBER.search(primary)
            building = later.group(1).upper() if later else None

    if secondary:
        secondary_flat = _FLAT_PREFIX.match(secondary) or _LEADING_NUMBER.match(secondary)
        if secondary_flat:
            flat = secondary_flat.groups()[-1].upper()

    tokens = [
        token for token in re.findall(r"[A-Za-z]{3,}", primary.upper())
        if token not in _STOPWORDS
    ]
    return {"building": building, "flat": flat, "name": tokens[0] if tokens else None}


def _address_parts(frame: pl.DataFrame, primary: str, secondary: str | None) -> pl.DataFrame:
    """Add building/flat/name columns parsed from the given address fields."""
    primaries = frame[primary].to_list()
    secondaries = frame[secondary].to_list() if secondary else [None] * frame.height
    parsed = [parse_address(p, s) for p, s in zip(primaries, secondaries, strict=True)]
    return frame.with_columns(
        pl.Series("building", [p["building"] for p in parsed], dtype=pl.Utf8),
        pl.Series("flat", [p["flat"] for p in parsed], dtype=pl.Utf8),
        pl.Series("name_token", [p["name"] for p in parsed], dtype=pl.Utf8),
    )


def extract_floor_areas(
    postcode_keys: pl.Series,
    zip_path: Path | str = EPC_ZIP,
) -> pl.DataFrame:
    """Read floor areas for a set of postcodes from the EPC archive.

    Args:
        postcode_keys: Normalised postcode keys to keep.
        zip_path: The EPC domestic bulk archive.

    Returns:
        One row per (postcode_key, building, flat, name_token) with a
        `floor_area_m2` column. Where an address has been certified more than
        once, the median area is taken — re-lodgements often disagree by a metre
        or two and the median is stable against that.

    Raises:
        FileNotFoundError: If the archive is absent.
    """
    zip_path = Path(zip_path)
    if not zip_path.exists():
        raise FileNotFoundError(
            f"EPC archive not found at {zip_path}. "
            "Set NY_CATCHMENTS_MIRROR or see data/README.md."
        )

    wanted = pl.DataFrame({"postcode_key": postcode_keys}).unique()
    con = duckdb.connect()
    con.execute("PRAGMA threads=4")
    con.register("wanted", wanted.to_arrow())

    frames: list[pl.DataFrame] = []
    with zipfile.ZipFile(zip_path) as archive:
        # The archive also holds recommendations-YYYY.csv, which share no columns
        # with the certificates and would fail the query.
        members = sorted(
            n for n in archive.namelist() if Path(n).name.startswith("certificates-")
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            for member in members:
                scratch = Path(tmpdir) / "certificates.csv"
                with archive.open(member) as src, scratch.open("wb") as dst:
                    shutil.copyfileobj(src, dst, length=8 * 1024 * 1024)

                query = f"""
                    SELECT
                        replace(upper(c.postcode), ' ', '') AS postcode_key,
                        c.address1,
                        c.address2,
                        TRY_CAST(c.total_floor_area AS DOUBLE) AS floor_area_m2,
                        c.property_type
                    FROM read_csv('{scratch.as_posix()}',
                                  header = true,
                                  all_varchar = true,
                                  ignore_errors = true) AS c
                    INNER JOIN wanted w
                        ON replace(upper(c.postcode), ' ', '') = w.postcode_key
                    WHERE TRY_CAST(c.total_floor_area AS DOUBLE)
                          BETWEEN {MIN_FLOOR_AREA_M2} AND {MAX_FLOOR_AREA_M2}
                """
                chunk = con.execute(query).pl()
                if chunk.height:
                    frames.append(chunk)
                scratch.unlink(missing_ok=True)

    if not frames:
        raise ValueError(
            "No EPC certificates matched the requested postcodes. "
            "That is implausible for a populated area — check the postcode keys."
        )

    combined = pl.concat(frames)
    combined = _address_parts(combined, "address1", None)

    return (
        combined.group_by(["postcode_key", "building", "flat", "name_token"])
        .agg(
            pl.col("floor_area_m2").median().alias("floor_area_m2"),
            pl.len().alias("n_certificates"),
        )
    )


#: Join tiers, most specific first. Each is tried on whatever the previous tiers
#: left unmatched, and the tier a match came from is recorded, so the report can
#: show how much of the match rate rests on the loosest key.
#:
#: Adapted from the sibling asylum-site project, whose tiering this mirrors so
#: the two remain comparable.
MATCH_TIERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("building+flat", ("postcode_key", "building", "flat")),
    ("building", ("postcode_key", "building")),
    ("flat+name", ("postcode_key", "flat", "name_token")),
    # Postcode plus flat number, with no building identifier on either side.
    # This is the tier that reaches the commonest EPC flat record: an address
    # line reading simply "Flat 2". Without it a flat whose PAON is a bare
    # number can never match, which is most of them — and the resulting gap is
    # not random, since it falls entirely on flats.
    #
    # The risk is two blocks sharing a postcode, where flat 2 of one could reach
    # flat 2 of the other. Postcodes are small — typically around fifteen
    # addresses — so this is uncommon, and it sits after the tiers that can
    # disambiguate by name.
    ("flat", ("postcode_key", "flat")),
    ("name", ("postcode_key", "name_token")),
)


def attach_floor_areas(
    transactions: pl.DataFrame,
    floor_areas: pl.DataFrame,
) -> pl.DataFrame:
    """Join floor areas onto transactions through a cascade of keys.

    A single key cannot work here. Price Paid separates the building ("130")
    from the dwelling within it ("FLAT 2") across two fields, while EPC writes
    one line — so "130"/"FLAT 2" has to be able to reach a certificate whose
    address is simply "Flat 2", and "ROSE COTTAGE" has no number on either side.

    Tiers run most specific first, each on what the previous ones left. Only
    rows whose key is *fully populated* can match on a given tier: a property
    with no building number is not eligible for the building tier at all. That
    is what stops an absent identifier from behaving like a value and matching
    every other address that also lacks one.

    Args:
        transactions: Price Paid rows carrying postcode_key, paon, saon, price.
        floor_areas: Output of `extract_floor_areas`.

    Returns:
        The transactions with `floor_area_m2`, `price_per_m2` and `match_tier`
        added, all null where unmatched. Row count is preserved — an unmatched
        transaction is evidence about coverage, not a row to drop.

    Raises:
        RuntimeError: If the cascade changes the row count, which would mean
            transactions were silently lost rather than left unmatched.
    """
    left = _address_parts(transactions, "paon", "saon").with_row_index("_txn_id")
    right = _certificate_parts(floor_areas)

    remaining = left
    matched_parts: list[pl.DataFrame] = []

    for tier_name, keys in MATCH_TIERS:
        if remaining.height == 0:
            break

        populated = pl.all_horizontal([pl.col(k).is_not_null() for k in keys])
        usable = remaining.filter(populated)
        skipped = remaining.filter(~populated)
        if usable.height == 0:
            remaining = skipped
            continue

        # Collapse the certificate side to one floor area per key. Several
        # certificates can share a key — re-lodgements of the same dwelling, or
        # (on the looser tiers) different dwellings in one building — and the
        # median is stable against both.
        candidates = (
            right.filter(pl.all_horizontal([pl.col(k).is_not_null() for k in keys]))
            .group_by(list(keys))
            .agg(pl.col("floor_area_m2").median().alias("_tier_area"))
        )

        joined = usable.join(candidates, on=list(keys), how="left")
        hit = joined.filter(pl.col("_tier_area").is_not_null())

        if hit.height:
            matched_parts.append(
                hit.with_columns(
                    pl.col("_tier_area").alias("floor_area_m2"),
                    pl.lit(tier_name).alias("match_tier"),
                ).drop("_tier_area")
            )

        missed = joined.filter(pl.col("_tier_area").is_null()).drop("_tier_area")
        remaining = pl.concat([missed, skipped], how="diagonal")

    unmatched = remaining.with_columns(
        pl.lit(None, dtype=pl.Float64).alias("floor_area_m2"),
        pl.lit(None, dtype=pl.Utf8).alias("match_tier"),
    )
    result = (
        pl.concat([*matched_parts, unmatched], how="diagonal")
        if matched_parts
        else unmatched
    )

    if result.height != transactions.height:
        raise RuntimeError(
            f"Tiered matching changed the row count: {transactions.height:,} in, "
            f"{result.height:,} out. A left join must preserve rows — an unmatched "
            "transaction is evidence about coverage, not a row to drop."
        )

    return (
        result.sort("_txn_id")
        .drop("_txn_id")
        .with_columns((pl.col("price") / pl.col("floor_area_m2")).alias("price_per_m2"))
    )


def _certificate_parts(floor_areas: pl.DataFrame) -> pl.DataFrame:
    """Present the certificate side with parsed address parts.

    `extract_floor_areas` already parses and groups by address, so its output is
    used as-is. A frame still carrying a raw `address1` is parsed here, which is
    what the tests and any ad-hoc use supply.

    Args:
        floor_areas: Either the grouped extract or raw certificate rows.

    Returns:
        A frame carrying postcode_key, building, flat, name_token, floor_area_m2.

    Raises:
        KeyError: If neither the parsed parts nor an address line is present.
    """
    parsed_columns = {"building", "flat", "name_token"}
    if parsed_columns.issubset(floor_areas.columns):
        return floor_areas.select(
            "postcode_key", "building", "flat", "name_token", "floor_area_m2"
        )
    if "address1" in floor_areas.columns:
        return _address_parts(floor_areas, "address1", None).select(
            "postcode_key", "building", "flat", "name_token", "floor_area_m2"
        )
    raise KeyError(
        "floor_areas must carry either building/flat/name_token or address1; "
        f"found {list(floor_areas.columns)}"
    )


def composition_check(matched: pl.DataFrame) -> pl.DataFrame:
    """Compare matched against unmatched transactions.

    A match rate says nothing on its own. If matched sales differ systematically
    from unmatched ones, £/m² is computed on a different population than the
    mean and median are, and the difference between them stops being comparable.

    Args:
        matched: Output of `attach_floor_areas`.

    Returns:
        One row per group with counts, median price and the share of flats.
    """
    return (
        matched.with_columns(
            pl.col("floor_area_m2").is_not_null().alias("has_floor_area")
        )
        .group_by("has_floor_area")
        .agg(
            pl.len().alias("transactions"),
            pl.col("price").median().round(0).alias("median_price"),
            (pl.col("property_type") == "F").mean().alias("share_flats"),
            (pl.col("property_type") == "D").mean().alias("share_detached"),
        )
        .sort("has_floor_area")
    )
