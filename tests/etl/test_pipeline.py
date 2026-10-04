"""End-to-end runs over tests/fixtures/olist, a tiny dataset where each row covers one rule."""

import json

import pandas as pd
import pytest

from conftest import hex_id as h
from opspulse.etl.pipeline import run_pipeline

# The fixture rejects about 17% of its orders on purpose; the production limit is 1%.
LENIENT = 0.5


def read(directory, name: str) -> pd.DataFrame:
    return pd.read_parquet(directory / f"{name}.parquet")


@pytest.fixture
def paths(fixture_project):
    report = run_pipeline(fixture_project, max_rejection_share=LENIENT)
    assert report["status"] == "SUCCESS_WITH_WARNINGS"
    return fixture_project


def test_report_counts_rejections_and_gates(paths):
    report = json.loads((paths.reports / "latest_report.json").read_text(encoding="utf-8"))

    assert report["totals"]["rejected_rows"] == 6
    assert report["quality_gates"]["keys"] == "PASS"
    assert report["quality_gates"]["references"] == "WARN"


def test_missing_customer_cascades_to_the_order_children(paths):
    orders = read(paths.rejected, "orders")
    assert orders["order_id"].tolist() == [h("a4")]
    assert orders["_rejection_reason"].tolist() == ["MISSING_CUSTOMER_REFERENCE"]

    for table in ("order_items", "payments", "reviews"):
        rejected = read(paths.rejected, table)
        cascaded = rejected[rejected["order_id"] == h("a4")]
        assert cascaded["_rejection_reason"].tolist() == ["MISSING_ORDER_REFERENCE"]
        assert cascaded["_rejection_stage"].tolist() == ["referential_integrity"]


def test_every_failed_rule_is_recorded_and_raw_text_is_kept(paths):
    items = read(paths.rejected, "order_items")
    row = items[items["order_item_id"] == "3"].iloc[0]

    assert row["_rejection_reason"] == "NEGATIVE_FREIGHT;NEGATIVE_PRICE"
    assert row["price"] == "-5.00"
    assert row["_source_row_number"] == 5


def test_review_shared_by_two_orders_is_kept_and_text_is_trimmed(paths):
    reviews = read(paths.core, "reviews")
    shared = reviews[reviews["review_id"] == h("e1")].set_index("order_id")

    assert sorted(shared.index) == [h("a1"), h("a2")]
    assert shared.loc[h("a1"), "review_message"] == "Ótimo produto"
    assert pd.isna(shared.loc[h("a2"), "review_message"])
    assert sorted(read(paths.rejected, "reviews")["_rejection_reason"]) == [
        "MISSING_ORDER_REFERENCE",
        "REVIEW_SCORE_OUT_OF_RANGE",
    ]


def test_delivery_metrics(paths):
    orders = read(paths.core, "orders").set_index("order_id")

    on_time = orders.loc[h("a1")]
    assert on_time["delivery_delay_days"] == -1
    assert not on_time["is_late"]
    assert on_time["delivery_days"] == pytest.approx(3.21)

    late = orders.loc[h("a2")]
    assert late["delivery_delay_days"] == 5
    assert late["is_late"]
    assert late["has_lifecycle_anomaly"]  # reached the carrier before approval

    # Delivered at 15:00 on the promised date: on time, because the promise is a date.
    assert orders.loc[h("a6"), "delivery_delay_days"] == 0
    assert not orders.loc[h("a6"), "is_late"]

    # Undelivered is not late: the metrics stay null instead of false or zero.
    undelivered = orders.loc[h("a3")]
    assert not undelivered["is_delivered"]
    assert pd.isna(undelivered["is_late"])
    assert pd.isna(undelivered["delivery_days"])


def test_reconciliation_statuses(paths):
    summary = read(paths.analytics, "order_financial_summary").set_index("order_id")

    assert summary["reconciliation_status"].to_dict() == {
        h("a1"): "MATCHED",
        h("a2"): "MINOR_DIFFERENCE",
        h("a3"): "NO_PAYMENT_RECORD",
        h("a5"): "NO_ITEMS",
        h("a6"): "SIGNIFICANT_DIFFERENCE",
    }
    assert summary.loc[h("a2"), "payment_types_used"] == "boleto,voucher"


def test_daily_sales_counts_each_order_once(paths):
    daily = read(paths.analytics, "daily_sales").set_index("sales_date")
    day = daily.loc[pd.Timestamp("2017-03-01")]

    assert day["orders_count"] == 3
    assert day["unique_customers"] == 2  # a1 and a2 belong to the same real customer
    assert day["item_count"] == 5
    assert day["gross_order_value"] == 545.0  # a2 has 2 items x 2 payments, counted once
    assert daily.loc[pd.Timestamp("2017-03-02"), "orders_count"] == 0  # no calendar gaps


def test_geo_centroid_ignores_duplicates_and_points_outside_brazil(paths):
    geo = read(paths.core, "geo_zip_prefix").set_index("zip_code_prefix").loc["01037"]

    assert geo["latitude"] == pytest.approx(-23.5463)
    assert geo["longitude"] == pytest.approx(-46.63965)
    assert geo["observation_count"] == 4
    assert geo["distinct_observation_count"] == 2
    assert geo["excluded_observation_count"] == 1


def test_untranslated_category_stays_null(paths):
    products = read(paths.core, "products").set_index("product_id")

    assert products.loc[h("b1"), "category_name_english"] == "health_beauty"
    assert pd.isna(products.loc[h("b2"), "category_name_english"])


def test_runs_are_idempotent(fixture_project):
    run_pipeline(fixture_project, max_rejection_share=LENIENT)
    first = {name: read(fixture_project.core, name) for name in ("orders", "order_items")}

    run_pipeline(fixture_project, max_rejection_share=LENIENT)

    for name, df in first.items():
        pd.testing.assert_frame_equal(read(fixture_project.core, name), df)


def test_critical_failure_keeps_previous_outputs(fixture_project):
    run_pipeline(fixture_project, max_rejection_share=LENIENT)
    before = read(fixture_project.core, "orders")
    orders_csv = fixture_project.raw / "olist_orders_dataset.csv"
    lines = orders_csv.read_text(encoding="utf-8").splitlines()
    orders_csv.write_text("\n".join([*lines, lines[1]]) + "\n", encoding="utf-8")

    report = run_pipeline(fixture_project, max_rejection_share=LENIENT)

    assert report["status"] == "FAILED"
    assert any("DUPLICATE_KEY" in problem for problem in report["critical_problems"])
    pd.testing.assert_frame_equal(read(fixture_project.core, "orders"), before)
    assert not any(fixture_project.work.iterdir())


def test_production_limit_fails_a_run_that_rejects_too_much(fixture_project):
    report = run_pipeline(fixture_project)

    assert report["status"] == "FAILED"
    assert any("rows rejected" in problem for problem in report["critical_problems"])
    assert not fixture_project.core.exists()
