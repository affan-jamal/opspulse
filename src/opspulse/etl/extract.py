"""Source verification, fingerprinting and raw extraction."""

import codecs
import hashlib
import logging
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from opspulse.etl.config import EXPECTED_COLUMNS, PATHS, RAW_ENCODING, SOURCE_FILES

log = logging.getLogger(__name__)


def create_run_id() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def verify_source_files(raw_dir: Path = PATHS.raw) -> None:
    missing = [
        str(raw_dir / filename)
        for filename in SOURCE_FILES.values()
        if not (raw_dir / filename).exists()
    ]
    if missing:
        raise FileNotFoundError("Missing source files:\n" + "\n".join(missing))
    log.info("Found %d/%d expected source files", len(SOURCE_FILES), len(SOURCE_FILES))


def observed_encoding(data: bytes) -> str:
    """Report the encoding the bytes actually satisfy, rather than assuming one."""
    try:
        data.decode("utf-8")
    except UnicodeDecodeError as exc:
        return f"not utf-8 (first invalid byte at offset {exc.start})"
    return "utf-8 with BOM" if data.startswith(codecs.BOM_UTF8) else "utf-8"


def fingerprint_source_files(run_id: str, raw_dir: Path = PATHS.raw) -> dict:
    files = {}
    for table, filename in SOURCE_FILES.items():
        data = (raw_dir / filename).read_bytes()
        files[filename] = {
            "table": table,
            "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data),
            "encoding": observed_encoding(data),
        }
    return {"run_id": run_id, "files": files}


def read_raw(table: str, raw_dir: Path = PATHS.raw) -> pd.DataFrame:
    """Load a source file exactly as text.

    No type inference (zip prefixes keep leading zeros) and only empty fields
    become null - pandas' default NA strings such as "NA" or "null" stay text.
    """
    return pd.read_csv(
        raw_dir / SOURCE_FILES[table],
        dtype=str,
        encoding=RAW_ENCODING,
        keep_default_na=False,
        na_values=[""],
    )


def extract_all(raw_dir: Path = PATHS.raw) -> dict[str, pd.DataFrame]:
    raw = {}
    for table in SOURCE_FILES:
        raw[table] = read_raw(table, raw_dir)
        log.info("Loaded %s: %d rows", table, len(raw[table]))
    return raw


def check_columns(table: str, df: pd.DataFrame) -> dict[str, list[str]]:
    expected = EXPECTED_COLUMNS[table]
    return {
        "missing": [column for column in expected if column not in df.columns],
        "unexpected": [column for column in df.columns if column not in expected],
    }
