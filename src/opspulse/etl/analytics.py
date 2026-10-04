"""Analytics: the two reference marts.

All other marts are written once, in SQL, over the ingested database (see docs/ROADMAP.md).
These two stay in pandas as a test oracle for those views. Both are built from
per-order pre-aggregates, so items x payments never fan out into double counting.
"""

import numpy as np
import pandas as pd

from opspulse.etl import config


def build_order_financial_summary(
    orders: pd.DataFrame, items: pd.DataFrame, payments: pd.DataFrame
) -> pd.DataFrame:
    item_totals = items.groupby("order_id").agg(
        item_count=("order_item_id", "size"),
        item_value=("price", "sum"),
        freight_value=("freight_value", "sum"),
    )
    payment_totals = payments.groupby("order_id").agg(
        payment_record_count=("payment_sequence", "size"),
        payment_total=("payment_value", "sum"),
        max_installments=("payment_installments", "max"),
    )
    payment_types = (
        payments.dropna(subset=["payment_type"])
        .drop_duplicates(["order_id", "payment_type"])
        .sort_values(["order_id", "payment_type"])
        .groupby("order_id")["payment_type"]
        .agg(",".join)
        .rename("payment_types_used")
    )

    out = (
        orders[["order_id", "order_status", "purchase_date"]]
        .join(item_totals, on="order_id")
        .join(payment_totals, on="order_id")
        .join(payment_types, on="order_id")
    )
    for column in ("item_count", "payment_record_count"):
        out[column] = out[column].fillna(0).astype("int64")
    out["item_value"] = out["item_value"].round(2)
    out["freight_value"] = out["freight_value"].round(2)
    out["order_total"] = (out["item_value"] + out["freight_value"]).round(2)
    out["payment_total"] = out["payment_total"].round(2)
    out["payment_difference"] = (out["payment_total"] - out["order_total"]).round(2)

    difference = out["payment_difference"].abs()
    out["reconciliation_status"] = np.select(
        [
            out["item_count"] == 0,
            out["payment_record_count"] == 0,
            difference <= config.RECONCILIATION_MATCH_TOLERANCE + 1e-9,
            difference <= config.RECONCILIATION_MINOR_TOLERANCE + 1e-9,
        ],
        ["NO_ITEMS", "NO_PAYMENT_RECORD", "MATCHED", "MINOR_DIFFERENCE"],
        default="SIGNIFICANT_DIFFERENCE",
    )
    out["reconciliation_status"] = out["reconciliation_status"].astype("str")
    return out.reset_index(drop=True)


def build_daily_sales(
    orders: pd.DataFrame, customers: pd.DataFrame, summary: pd.DataFrame
) -> pd.DataFrame:
    sales = summary[
        ~summary["order_status"].isin(config.NON_SALE_STATUSES) & (summary["item_count"] > 0)
    ]
    sales = sales.merge(orders[["order_id", "customer_id"]], on="order_id").merge(
        customers[["customer_id", "customer_unique_id"]], on="customer_id"
    )
    daily = sales.groupby("purchase_date").agg(
        orders_count=("order_id", "size"),
        unique_customers=("customer_unique_id", "nunique"),
        item_count=("item_count", "sum"),
        product_value=("item_value", "sum"),
        freight_value=("freight_value", "sum"),
    )
    # A continuous calendar: days without sales are zero, not missing.
    spine = pd.date_range(daily.index.min(), daily.index.max(), freq="D", name="sales_date")
    daily = daily.reindex(spine, fill_value=0)

    daily["product_value"] = daily["product_value"].round(2)
    daily["freight_value"] = daily["freight_value"].round(2)
    daily["gross_order_value"] = (daily["product_value"] + daily["freight_value"]).round(2)
    daily["average_order_value"] = (
        (daily["gross_order_value"] / daily["orders_count"])
        .where(daily["orders_count"] > 0)
        .round(2)
    )
    daily["in_analysis_window"] = daily.index.to_series().between(*config.ANALYSIS_WINDOW)
    return daily.reset_index()


def build_analytics(core: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    summary = build_order_financial_summary(core["orders"], core["order_items"], core["payments"])
    return {
        "order_financial_summary": summary,
        "daily_sales": build_daily_sales(core["orders"], core["customers"], summary),
    }
