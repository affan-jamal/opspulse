"""Staging: technical standardization only.

Each staged table keeps the source grain and the raw row index (its record number),
renames columns to canonical names and casts them to real types. Values that fail
to cast become null here; validate.py compares against the raw text and reports them.
"""

import pandas as pd

from opspulse.etl import config
from opspulse.etl.schema import CODE, FLOAT, ID, INT, MONEY, STAGING, STATE, TEXT, TIMESTAMP


def _text(series: pd.Series) -> pd.Series:
    """Trim surrounding whitespace; whitespace-only becomes null. Case and accents are kept."""
    stripped = series.str.strip()
    return stripped.mask(stripped == "")


def _number(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series.str.strip(), errors="coerce").astype("float64")


def _integer(series: pd.Series) -> pd.Series:
    numbers = _number(series)
    return numbers.where(numbers % 1 == 0).astype("Int64")


def _timestamp(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series.str.strip(), format=config.RAW_TIMESTAMP_FORMAT, errors="coerce")


CASTS = {
    ID: _text,
    CODE: _text,
    TEXT: _text,
    STATE: lambda series: _text(series).str.upper(),
    INT: _integer,
    MONEY: _number,
    FLOAT: _number,
    TIMESTAMP: _timestamp,
}


def stage_table(table: str, raw: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(
        {name: CASTS[column.kind](raw[column.source]) for name, column in STAGING[table].items()},
        index=raw.index,
    )


def stage_all(raw: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    return {table: stage_table(table, df) for table, df in raw.items()}
