"""Paths, the raw-source contract and the business rules of the Olist ETL."""

import os
from dataclasses import dataclass
from pathlib import Path

import pandas as pd


@dataclass(frozen=True)
class Paths:
    root: Path

    @property
    def raw(self) -> Path:
        return self.root / "data" / "raw" / "olist"

    @property
    def staging(self) -> Path:
        return self.root / "data" / "staging" / "olist"

    @property
    def core(self) -> Path:
        return self.root / "data" / "processed" / "core"

    @property
    def analytics(self) -> Path:
        return self.root / "data" / "processed" / "analytics"

    @property
    def quality(self) -> Path:
        return self.root / "data" / "processed" / "quality"

    @property
    def rejected(self) -> Path:
        return self.root / "data" / "rejected" / "olist"

    @property
    def work(self) -> Path:
        """Scratch space where a run writes before its outputs are promoted."""
        return self.root / "data" / ".tmp"

    @property
    def reports(self) -> Path:
        return self.root / "reports" / "data_quality"


PROJECT_ROOT = Path(os.environ.get("OPSPULSE_ROOT", Path(__file__).resolve().parents[3]))
PATHS = Paths(PROJECT_ROOT)

# utf-8-sig decodes plain UTF-8 too, and strips the BOM that
# product_category_name_translation.csv starts with.
RAW_ENCODING = "utf-8-sig"

# Every raw timestamp in the source uses this layout. Parsing with an explicit
# format means any deviation shows up as an invalid-parse count, not a guess.
RAW_TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"

SOURCE_FILES = {
    "customers": "olist_customers_dataset.csv",
    "geolocation": "olist_geolocation_dataset.csv",
    "order_items": "olist_order_items_dataset.csv",
    "payments": "olist_order_payments_dataset.csv",
    "reviews": "olist_order_reviews_dataset.csv",
    "orders": "olist_orders_dataset.csv",
    "products": "olist_products_dataset.csv",
    "sellers": "olist_sellers_dataset.csv",
    "category_translation": "product_category_name_translation.csv",
}

# Raw column contract, exactly as published (including the "lenght" typos).
EXPECTED_COLUMNS = {
    "customers": [
        "customer_id",
        "customer_unique_id",
        "customer_zip_code_prefix",
        "customer_city",
        "customer_state",
    ],
    "geolocation": [
        "geolocation_zip_code_prefix",
        "geolocation_lat",
        "geolocation_lng",
        "geolocation_city",
        "geolocation_state",
    ],
    "order_items": [
        "order_id",
        "order_item_id",
        "product_id",
        "seller_id",
        "shipping_limit_date",
        "price",
        "freight_value",
    ],
    "payments": [
        "order_id",
        "payment_sequential",
        "payment_type",
        "payment_installments",
        "payment_value",
    ],
    "reviews": [
        "review_id",
        "order_id",
        "review_score",
        "review_comment_title",
        "review_comment_message",
        "review_creation_date",
        "review_answer_timestamp",
    ],
    "orders": [
        "order_id",
        "customer_id",
        "order_status",
        "order_purchase_timestamp",
        "order_approved_at",
        "order_delivered_carrier_date",
        "order_delivered_customer_date",
        "order_estimated_delivery_date",
    ],
    "products": [
        "product_id",
        "product_category_name",
        "product_name_lenght",
        "product_description_lenght",
        "product_photos_qty",
        "product_weight_g",
        "product_length_cm",
        "product_height_cm",
        "product_width_cm",
    ],
    "sellers": [
        "seller_id",
        "seller_zip_code_prefix",
        "seller_city",
        "seller_state",
    ],
    "category_translation": [
        "product_category_name",
        "product_category_name_english",
    ],
}

TIMESTAMP_COLUMNS = {
    "order_items": ["shipping_limit_date"],
    "reviews": ["review_creation_date", "review_answer_timestamp"],
    "orders": [
        "order_purchase_timestamp",
        "order_approved_at",
        "order_delivered_carrier_date",
        "order_delivered_customer_date",
        "order_estimated_delivery_date",
    ],
}

HASH_ID = r"[0-9a-f]{32}"
ZIP_PREFIX = r"\d{5}"
STATE = r"[A-Z]{2}"

# Columns that are labels, not quantities, and the pattern every value must match.
# They are profiled as text even when they look numeric (zip prefixes).
COLUMN_PATTERNS = {
    "customers": {
        "customer_id": HASH_ID,
        "customer_unique_id": HASH_ID,
        "customer_zip_code_prefix": ZIP_PREFIX,
        "customer_state": STATE,
    },
    "geolocation": {"geolocation_zip_code_prefix": ZIP_PREFIX, "geolocation_state": STATE},
    "order_items": {"order_id": HASH_ID, "product_id": HASH_ID, "seller_id": HASH_ID},
    "payments": {"order_id": HASH_ID},
    "reviews": {"review_id": HASH_ID, "order_id": HASH_ID},
    "orders": {"order_id": HASH_ID, "customer_id": HASH_ID},
    "products": {"product_id": HASH_ID},
    "sellers": {"seller_id": HASH_ID, "seller_zip_code_prefix": ZIP_PREFIX, "seller_state": STATE},
}

# Candidate keys to test for uniqueness during profiling.
CANDIDATE_KEYS = {
    "customers": ["customer_id"],
    "orders": ["order_id"],
    "order_items": ["order_id", "order_item_id"],
    "payments": ["order_id", "payment_sequential"],
    "reviews": ["review_id"],
    "products": ["product_id"],
    "sellers": ["seller_id"],
    "category_translation": ["product_category_name"],
}

# (child_table, child_column, parent_table, parent_column)
RELATIONSHIPS = [
    ("orders", "customer_id", "customers", "customer_id"),
    ("order_items", "order_id", "orders", "order_id"),
    ("order_items", "product_id", "products", "product_id"),
    ("order_items", "seller_id", "sellers", "seller_id"),
    ("payments", "order_id", "orders", "order_id"),
    ("reviews", "order_id", "orders", "order_id"),
    ("products", "product_category_name", "category_translation", "product_category_name"),
    ("customers", "customer_zip_code_prefix", "geolocation", "geolocation_zip_code_prefix"),
    ("sellers", "seller_zip_code_prefix", "geolocation", "geolocation_zip_code_prefix"),
]

# --- Business rules (documented in docs/data/data_dictionary.md) ---

# Olist timestamps are naive local times (America/Sao_Paulo). They stay naive.
# Anything outside the export's lifetime is flagged, not changed.
SOURCE_PERIOD = (pd.Timestamp("2016-01-01"), pd.Timestamp("2018-12-31 23:59:59"))

# Months before 2017 and after 2018-08 hold a few hundred orders between them,
# so trend metrics and recency use this window instead of the full date range.
ANALYSIS_WINDOW = (pd.Timestamp("2017-01-01"), pd.Timestamp("2018-08-31 23:59:59"))

# Bounding box for mainland Brazil plus its Atlantic islands. Geolocation points
# outside it are kept in staging but excluded from zip-prefix centroids.
BRAZIL_LATITUDE = (-34.0, 5.5)
BRAZIL_LONGITUDE = (-74.5, -28.5)

BRAZIL_STATES = frozenset(
    "AC AL AP AM BA CE DF ES GO MA MT MS MG PA PB PR PE PI RJ RN RS RO RR SC SP SE TO".split()
)

# Statuses observed in the source. Anything else is reported, not coerced.
KNOWN_ORDER_STATUSES = frozenset(
    {
        "created",
        "approved",
        "invoiced",
        "processing",
        "shipped",
        "delivered",
        "canceled",
        "unavailable",
    }
)

# Orders in these statuses never became sales and are left out of sales metrics.
NON_SALE_STATUSES = frozenset({"canceled", "unavailable"})

# Payment reconciliation, in BRL: |payment_total - order_total|.
RECONCILIATION_MATCH_TOLERANCE = 0.01
RECONCILIATION_MINOR_TOLERANCE = 1.00

# A relationship or table that rejects more than this share of its rows is
# treated as structurally broken and fails the run.
CATASTROPHIC_REJECTION_SHARE = 0.01
