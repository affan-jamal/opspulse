import pandas as pd

from opspulse.etl.profile import profile_column, profile_relationships, profile_table


def text(*values):
    return pd.Series(values, dtype="str")


def test_timestamp_invalid_parses_are_counted_not_hidden():
    info = profile_column(
        text("2017-10-02 10:56:33", "2017-13-40 00:00:00", None), is_timestamp=True
    )

    assert info["kind"] == "timestamp"
    assert info["null_count"] == 1
    assert info["invalid_parse_count"] == 1
    assert info["min"] == "2017-10-02 10:56:33"


def test_numeric_profile_reports_negatives():
    info = profile_column(text("1.5", "-2", "3"))

    assert info["kind"] == "numeric"
    assert info["min"] == -2.0
    assert info["negative_count"] == 1


def test_patterned_codes_are_text_not_numbers():
    info = profile_column(text("01037", "14409", "123"), pattern=r"\d{5}")

    assert info["kind"] == "text"
    assert (info["length_min"], info["length_max"]) == (3, 5)
    assert info["pattern_nonconforming_count"] == 1


def test_nonconforming_hash_ids_are_counted():
    info = profile_column(text("0" * 32, "not-a-hash", "a" * 32), pattern=r"[0-9a-f]{32}")

    assert info["pattern_nonconforming_count"] == 1


def test_candidate_key_duplicates_are_reported():
    reviews = pd.DataFrame(
        {"review_id": ["r1", "r1", "r2"], "order_id": ["o1", "o2", "o3"]}, dtype="str"
    )

    key = profile_table("reviews", reviews)["candidate_key"]

    assert key == {"columns": ["review_id"], "duplicate_row_count": 2, "duplicate_key_count": 1}


def test_orphans_and_unreferenced_parents():
    raw = {
        "orders": pd.DataFrame({"customer_id": ["c1", "c9", "c9", None]}, dtype="str"),
        "customers": pd.DataFrame({"customer_id": ["c1", "c2"]}, dtype="str"),
    }

    [result] = profile_relationships(raw, [("orders", "customer_id", "customers", "customer_id")])

    assert result["orphan_row_count"] == 2
    assert result["orphan_key_count"] == 1
    assert result["sample_orphan_keys"] == ["c9"]
    assert result["child_null_count"] == 1
    assert result["unreferenced_parent_key_count"] == 1
