import codecs

import pandas as pd
import pytest

from opspulse.etl.config import EXPECTED_COLUMNS, SOURCE_FILES
from opspulse.etl.extract import (
    check_columns,
    fingerprint_source_files,
    read_raw,
    verify_source_files,
)


@pytest.fixture
def raw_dir(tmp_path):
    for table, filename in SOURCE_FILES.items():
        (tmp_path / filename).write_text(",".join(EXPECTED_COLUMNS[table]) + "\n", encoding="utf-8")
    return tmp_path


def test_verify_lists_every_missing_file(raw_dir):
    (raw_dir / SOURCE_FILES["orders"]).unlink()
    (raw_dir / SOURCE_FILES["sellers"]).unlink()

    with pytest.raises(FileNotFoundError) as exc:
        verify_source_files(raw_dir)

    assert SOURCE_FILES["orders"] in str(exc.value)
    assert SOURCE_FILES["sellers"] in str(exc.value)


def test_fingerprint_reports_bom(raw_dir):
    path = raw_dir / SOURCE_FILES["category_translation"]
    path.write_bytes(codecs.BOM_UTF8 + path.read_bytes())

    files = fingerprint_source_files("run", raw_dir)["files"]

    assert files[SOURCE_FILES["category_translation"]]["encoding"] == "utf-8 with BOM"
    assert files[SOURCE_FILES["orders"]]["encoding"] == "utf-8"
    assert len(files[SOURCE_FILES["orders"]]["sha256"]) == 64


def test_read_raw_keeps_source_text_exact(raw_dir):
    path = raw_dir / SOURCE_FILES["sellers"]
    path.write_text(
        "seller_id,seller_zip_code_prefix,seller_city,seller_state\n"
        'abc,"01037",NA,SP\n'
        "def,,null,\n",
        encoding="utf-8",
    )

    sellers = read_raw("sellers", raw_dir)

    assert sellers.loc[0, "seller_zip_code_prefix"] == "01037"
    assert sellers.loc[0, "seller_city"] == "NA"
    assert sellers.loc[1, "seller_city"] == "null"
    assert pd.isna(sellers.loc[1, "seller_zip_code_prefix"])
    assert pd.isna(sellers.loc[1, "seller_state"])


def test_read_raw_strips_bom_from_header(raw_dir):
    path = raw_dir / SOURCE_FILES["category_translation"]
    path.write_bytes(codecs.BOM_UTF8 + path.read_bytes())

    df = read_raw("category_translation", raw_dir)

    assert check_columns("category_translation", df) == {"missing": [], "unexpected": []}
