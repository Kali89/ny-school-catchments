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


#: Columns used as join keys between the two registers.
_JOIN_KEYS = ("building", "flat", "name_token")


def _fill_join_keys(frame: pl.DataFrame) -> pl.DataFrame:
    """Replace nulls in the address join keys with an empty-string sentinel.

    polars joins with ``join_nulls=False`` by default, so a null on either side
    never matches — not even null-to-null. Most houses have no flat number, so
    left as nulls the precise key silently drops every house while continuing to
    match flats. That inversion (flats matching better than houses) is the
    symptom to watch for if this regresses.

    Args:
        frame: A frame carrying any of the address join key columns.

    Returns:
        The frame with those columns null-filled.
    """
    present = [c for c in _JOIN_KEYS if c in frame.columns]
    return frame.with_columns([pl.col(c).fill_null("") for c in present])


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


def attach_floor_areas(
    transactions: pl.DataFrame,
    floor_areas: pl.DataFrame,
) -> pl.DataFrame:
    """Join floor areas onto transactions, in two passes.

    Pass one matches on (postcode, building, flat), which is the precise key.
    Pass two retries whatever is still unmatched on (postcode, name_token), which
    catches named properties with no number in either register — common in rural
    North Yorkshire, where "Rose Cottage" is a complete address.

    Args:
        transactions: Price Paid rows carrying postcode_key, paon and saon.
        floor_areas: Output of `extract_floor_areas`.

    Returns:
        The transactions with `floor_area_m2` (nullable) and `price_per_m2` added.
    """
    parsed = _fill_join_keys(_address_parts(transactions, "paon", "saon"))
    floor_areas = _fill_join_keys(floor_areas)

    # Pass one — the precise key. Restricted to addresses that carry a number,
    # because (postcode, "", "") is not an identifier: in rural North Yorkshire a
    # single postcode routinely holds many named properties with no number at
    # all, and matching on the empty key hands a sale an arbitrary neighbour's
    # floor area. Named properties are left for pass two instead.
    numbered = floor_areas.filter(
        (pl.col("building") != "") | (pl.col("flat") != "")
    )
    precise = numbered.select(
        "postcode_key", "building", "flat", "floor_area_m2"
    ).unique(subset=["postcode_key", "building", "flat"], keep="first")

    matched = parsed.with_columns(
        pl.when((pl.col("building") != "") | (pl.col("flat") != ""))
        .then(pl.col("building"))
        .otherwise(None)
        .alias("_precise_building")
    ).join(
        precise.rename({"building": "_precise_building"}),
        on=["postcode_key", "_precise_building", "flat"],
        how="left",
    ).drop("_precise_building")

    # Pass two — the named-property key, for rows the precise key could not
    # reach. Only unambiguous names are used: if two certified addresses in a
    # postcode share a leading token ("ROSE" from both Rose Cottage and
    # Rosebank), there is no way to tell which sold, so the sale is left
    # unmatched rather than given a coin-flip floor area.
    by_name = (
        floor_areas.filter(pl.col("name_token") != "")
        .group_by(["postcode_key", "name_token"])
        .agg(
            pl.col("floor_area_m2").median().alias("floor_area_by_name"),
            pl.len().alias("_n_candidates"),
        )
        .filter(pl.col("_n_candidates") == 1)
        .drop("_n_candidates")
    )
    matched = matched.join(by_name, on=["postcode_key", "name_token"], how="left")

    return matched.with_columns(
        pl.coalesce("floor_area_m2", "floor_area_by_name").alias("floor_area_m2")
    ).drop("floor_area_by_name").with_columns(
        (pl.col("price") / pl.col("floor_area_m2")).alias("price_per_m2")
    )
