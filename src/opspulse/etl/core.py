"""Core: the canonical relational model built from accepted staged rows.

Source facts are kept as they are; derived fields are added next to them, never over them.
"""

import pandas as pd

from opspulse.etl import config
from opspulse.etl.validate import LIFECYCLE_CODES, outside_brazil


def build_orders(orders: pd.DataFrame, lifecycle_anomaly_rows: pd.Index) -> pd.DataFrame:
    out = orders.copy()
    purchase = out["purchase_at"]
    delivered = out["delivered_to_customer_at"]
    estimated = out["estimated_delivery_at"]

    out["purchase_date"] = purchase.dt.normalize()
    out["purchase_year"] = purchase.dt.year.astype("Int64")
    out["purchase_month"] = purchase.dt.month.astype("Int64")
    out["purchase_weekday"] = purchase.dt.dayofweek.astype("Int64")
    out["purchase_hour"] = purchase.dt.hour.astype("Int64")

    # Undelivered and late are different states: delivery metrics only exist for
    # orders that were actually delivered, and stay null (not false/zero) otherwise.
    is_delivered = out["order_status"].eq("delivered") & delivered.notna()
    out["is_delivered"] = is_delivered
    out["delivery_days"] = (
        ((delivered - purchase).dt.total_seconds() / 86400).round(2).where(is_delivered)
    )
    out["estimated_delivery_days"] = ((estimated - purchase).dt.total_seconds() / 86400).round(2)

    # The promise is a date (midnight), so lateness compares calendar dates: an order
    # delivered at 15:00 on the promised day is on time.
    delay = (delivered.dt.normalize() - estimated.dt.normalize()).dt.days
    out["delivery_delay_days"] = delay.where(is_delivered).astype("Int64")
    is_late = pd.Series(pd.NA, index=out.index, dtype="boolean")
    is_late[is_delivered] = delay[is_delivered] > 0
    out["is_late"] = is_late

    out["has_lifecycle_anomaly"] = out.index.isin(lifecycle_anomaly_rows)
    out["in_analysis_window"] = purchase.between(*config.ANALYSIS_WINDOW)
    return out


def build_products(products: pd.DataFrame, translation: pd.DataFrame) -> pd.DataFrame:
    english = dict(
        zip(translation["category_name"], translation["category_name_english"], strict=True)
    )
    out = products.copy()
    out.insert(
        out.columns.get_loc("category_name") + 1,
        "category_name_english",
        out["category_name"].map(english).astype("str"),
    )
    return out


def build_geo_zip_prefix(geo: pd.DataFrame) -> pd.DataFrame:
    """One centroid per zip prefix: median of distinct in-Brazil observations.

    This is an area centroid, never a customer or seller address.
    """
    excluded = outside_brazil(geo)
    usable = geo.loc[~excluded, ["zip_code_prefix", "latitude", "longitude"]].drop_duplicates()
    out = usable.groupby("zip_code_prefix").agg(
        latitude=("latitude", "median"),
        longitude=("longitude", "median"),
        distinct_observation_count=("latitude", "size"),
    )
    out["observation_count"] = geo.groupby("zip_code_prefix").size()
    out["excluded_observation_count"] = (
        geo[excluded].groupby("zip_code_prefix").size().reindex(out.index, fill_value=0)
    )
    return out.reset_index()


def build_reviews(reviews: pd.DataFrame) -> pd.DataFrame:
    out = reviews.copy()
    out["has_title"] = out["review_title"].notna()
    out["has_message"] = out["review_message"].notna()
    out["message_length"] = out["review_message"].str.len().astype("Int64")
    return out


def build_order_items(items: pd.DataFrame) -> pd.DataFrame:
    out = items.copy()
    out["item_total"] = out["price"] + out["freight_value"]
    return out


def build_core(accepted: dict[str, pd.DataFrame], issues: pd.DataFrame) -> dict[str, pd.DataFrame]:
    lifecycle = issues[(issues["table"] == "orders") & issues["code"].isin(LIFECYCLE_CODES)]
    core = {
        "customers": accepted["customers"],
        "sellers": accepted["sellers"],
        "product_categories": accepted["category_translation"],
        "products": build_products(accepted["products"], accepted["category_translation"]),
        "geo_zip_prefix": build_geo_zip_prefix(accepted["geolocation"]),
        "orders": build_orders(accepted["orders"], pd.Index(lifecycle["row"].unique())),
        "order_items": build_order_items(accepted["order_items"]),
        "payments": accepted["payments"],
        "reviews": build_reviews(accepted["reviews"]),
    }
    return {name: df.reset_index(drop=True) for name, df in core.items()}
