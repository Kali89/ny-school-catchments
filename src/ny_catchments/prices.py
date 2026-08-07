"""HM Land Registry Price Paid transactions, filtered and located.

The full Price Paid file is ~5.1GB and ~30M rows covering England and Wales since
1995. DuckDB streams it rather than loading it, which keeps peak memory in the
hundreds of MB.

Two filters are applied for methodological rather than performance reasons:

- **PPD category B is excluded.** Category B covers repossessions, portfolio
  transfers and other sales that are not open-market prices, so including them
  would bias a "what does a house cost here" figure downward.
- **Property type O ("other") is excluded** as overwhelmingly non-residential.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import polars as pl

from .config import PPD_CATEGORY, PRICE_PAID_CSV, RESIDENTIAL_TYPES

# Price Paid ships headerless. Column order is fixed and documented by HMLR.
_PP_COLUMNS = [
    "transaction_id",
    "price",
    "transfer_date",
    "postcode",
    "property_type",
    "old_new",
    "duration",
    "paon",
    "saon",
    "street",
    "locality",
    "town",
    "district",
    "county",
    "ppd_category",
    "record_status",
]


def load_transactions(
    postcode_keys: pl.Series,
    since_year: int,
    csv_path: Path | str = PRICE_PAID_CSV,
) -> pl.DataFrame:
    """Read Price Paid transactions for a set of postcodes since a given year.

    Args:
        postcode_keys: Normalised postcode keys to keep (whitespace stripped,
            uppercased) — see `postcodes.normalise_postcode`.
        since_year: Keep transfers in this calendar year or later.
        csv_path: The Price Paid complete CSV.

    Returns:
        A DataFrame of transactions with a `postcode_key` column ready to join
        against the postcode lookup.

    Raises:
        FileNotFoundError: If the CSV is absent.
    """
    csv_path = Path(csv_path)
    if not csv_path.exists():
        raise FileNotFoundError(
            f"Price Paid CSV not found at {csv_path}. "
            "Set NY_CATCHMENTS_MIRROR or see data/README.md."
        )

    con = duckdb.connect()
    con.execute("PRAGMA threads=4")

    # Register the wanted postcodes as a table so the filter is a hash join rather
    # than a 100k-element IN list.
    wanted = pl.DataFrame({"postcode_key": postcode_keys}).unique()
    con.register("wanted", wanted.to_arrow())

    columns = ", ".join(f"'{name}': 'VARCHAR'" for name in _PP_COLUMNS)
    query = f"""
        SELECT
            TRY_CAST(pp.price AS BIGINT)                     AS price,
            TRY_CAST(substr(pp.transfer_date, 1, 10) AS DATE) AS transfer_date,
            replace(upper(pp.postcode), ' ', '')             AS postcode_key,
            pp.property_type,
            pp.old_new,
            pp.duration,
            pp.paon,
            pp.saon,
            pp.street
        FROM read_csv(
            '{csv_path.as_posix()}',
            header = false,
            columns = {{{columns}}}
        ) AS pp
        INNER JOIN wanted w
            ON replace(upper(pp.postcode), ' ', '') = w.postcode_key
        WHERE pp.ppd_category = '{PPD_CATEGORY}'
          AND pp.property_type IN {tuple(RESIDENTIAL_TYPES)}
          AND TRY_CAST(substr(pp.transfer_date, 1, 10) AS DATE)
              >= DATE '{since_year}-01-01'
          AND TRY_CAST(pp.price AS BIGINT) > 0
    """
    return con.execute(query).pl()
