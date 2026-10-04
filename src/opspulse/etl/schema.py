"""The staging contract: canonical name, type and meaning of every source column.

docs/data/data_dictionary.md is generated from this module (`opspulse-etl dictionary`),
so the documentation cannot drift from what the code does.
"""

from dataclasses import dataclass

# Column kinds. Each maps to one cast in transform.py and one set of checks in validate.py.
ID = "id"  # 32-char hex hash, kept as text
CODE = "code"  # numeric-looking label (zip prefix), kept as text
STATE = "state"  # Brazilian UF abbreviation, upper-cased
TEXT = "text"  # free text, trimmed, otherwise untouched
INT = "int"
MONEY = "money"  # BRL amount
FLOAT = "float"
TIMESTAMP = "timestamp"  # naive America/Sao_Paulo local time


@dataclass(frozen=True)
class Column:
    source: str
    kind: str
    description: str
    required: bool = False


STAGING: dict[str, dict[str, Column]] = {
    "customers": {
        "customer_id": Column(
            "customer_id", ID, "Customer key of one order. Olist issues a new one per order.", True
        ),
        "customer_unique_id": Column(
            "customer_unique_id",
            ID,
            "The real customer across orders. Use it for repeat-customer analysis.",
            True,
        ),
        "zip_code_prefix": Column(
            "customer_zip_code_prefix", CODE, "First five digits of the postal code."
        ),
        "city": Column("customer_city", TEXT, "City as written in the source."),
        "state": Column("customer_state", STATE, "State (UF) abbreviation."),
    },
    "geolocation": {
        "zip_code_prefix": Column(
            "geolocation_zip_code_prefix",
            CODE,
            "Postal-code prefix the observation belongs to.",
            True,
        ),
        "latitude": Column(
            "geolocation_lat", FLOAT, "Observed latitude. Several observations per prefix.", True
        ),
        "longitude": Column(
            "geolocation_lng", FLOAT, "Observed longitude. Several observations per prefix.", True
        ),
        "city": Column("geolocation_city", TEXT, "City as written in the source."),
        "state": Column("geolocation_state", STATE, "State (UF) abbreviation."),
    },
    "order_items": {
        "order_id": Column("order_id", ID, "Order the item belongs to.", True),
        "order_item_id": Column(
            "order_item_id", INT, "Position of the item within its order (1, 2, ...).", True
        ),
        "product_id": Column("product_id", ID, "Product sold.", True),
        "seller_id": Column("seller_id", ID, "Seller who fulfilled the item.", True),
        "shipping_limit_at": Column(
            "shipping_limit_date",
            TIMESTAMP,
            "Deadline for the seller to hand the item to the carrier.",
        ),
        "price": Column("price", MONEY, "Item price.", True),
        "freight_value": Column(
            "freight_value",
            MONEY,
            "Freight charged for the item. Split across items when an order has several.",
            True,
        ),
    },
    "payments": {
        "order_id": Column("order_id", ID, "Order paid for.", True),
        "payment_sequence": Column(
            "payment_sequential",
            INT,
            "Sequence of payment methods used on one order (vouchers add records).",
            True,
        ),
        "payment_type": Column("payment_type", TEXT, "Payment method.", True),
        "payment_installments": Column(
            "payment_installments", INT, "Installments chosen by the customer."
        ),
        "payment_value": Column("payment_value", MONEY, "Amount paid with this method.", True),
    },
    "reviews": {
        "review_id": Column(
            "review_id", ID, "Review survey. The same survey can cover several orders.", True
        ),
        "order_id": Column("order_id", ID, "Order reviewed.", True),
        "review_score": Column("review_score", INT, "Satisfaction score, 1 to 5.", True),
        "review_title": Column("review_comment_title", TEXT, "Optional title, in Portuguese."),
        "review_message": Column(
            "review_comment_message", TEXT, "Optional comment, in Portuguese."
        ),
        "created_at": Column(
            "review_creation_date", TIMESTAMP, "When the survey was sent (date only)."
        ),
        "answered_at": Column("review_answer_timestamp", TIMESTAMP, "When the customer answered."),
    },
    "orders": {
        "order_id": Column("order_id", ID, "Order.", True),
        "customer_id": Column("customer_id", ID, "Customer key of this order.", True),
        "order_status": Column("order_status", TEXT, "Lifecycle status at export time.", True),
        "purchase_at": Column(
            "order_purchase_timestamp", TIMESTAMP, "When the order was placed.", True
        ),
        "approved_at": Column("order_approved_at", TIMESTAMP, "When payment was approved."),
        "delivered_to_carrier_at": Column(
            "order_delivered_carrier_date", TIMESTAMP, "When the order was handed to the carrier."
        ),
        "delivered_to_customer_at": Column(
            "order_delivered_customer_date", TIMESTAMP, "When the customer received the order."
        ),
        "estimated_delivery_at": Column(
            "order_estimated_delivery_date",
            TIMESTAMP,
            "Delivery date promised at purchase (date only).",
        ),
    },
    "products": {
        "product_id": Column("product_id", ID, "Product.", True),
        "category_name": Column("product_category_name", TEXT, "Category, in Portuguese."),
        "name_length": Column("product_name_lenght", INT, "Characters in the product name."),
        "description_length": Column(
            "product_description_lenght", INT, "Characters in the description."
        ),
        "photos_qty": Column("product_photos_qty", INT, "Published photos."),
        "weight_g": Column("product_weight_g", FLOAT, "Weight in grams."),
        "length_cm": Column("product_length_cm", FLOAT, "Package length in cm."),
        "height_cm": Column("product_height_cm", FLOAT, "Package height in cm."),
        "width_cm": Column("product_width_cm", FLOAT, "Package width in cm."),
    },
    "sellers": {
        "seller_id": Column("seller_id", ID, "Seller.", True),
        "zip_code_prefix": Column(
            "seller_zip_code_prefix", CODE, "First five digits of the postal code."
        ),
        "city": Column("seller_city", TEXT, "City as written in the source."),
        "state": Column("seller_state", STATE, "State (UF) abbreviation."),
    },
    "category_translation": {
        "category_name": Column("product_category_name", TEXT, "Category, in Portuguese.", True),
        "category_name_english": Column(
            "product_category_name_english", TEXT, "Category, in English.", True
        ),
    },
}

# Natural key (grain) of each staged table. Geolocation is repeated observations: no key.
KEYS: dict[str, list[str] | None] = {
    "customers": ["customer_id"],
    "geolocation": None,
    "order_items": ["order_id", "order_item_id"],
    "payments": ["order_id", "payment_sequence"],
    "reviews": ["review_id", "order_id"],
    "orders": ["order_id"],
    "products": ["product_id"],
    "sellers": ["seller_id"],
    "category_translation": ["category_name"],
}

GRAIN = {
    "customers": "one row per customer_id (one per order)",
    "geolocation": "one row per observed coordinate; many per zip prefix",
    "order_items": "one row per order_id + order_item_id",
    "payments": "one row per order_id + payment_sequence",
    "reviews": "one row per review_id + order_id",
    "orders": "one row per order_id",
    "products": "one row per product_id",
    "sellers": "one row per seller_id",
    "category_translation": "one row per Portuguese category name",
}


@dataclass(frozen=True)
class Derived:
    table: str
    field: str
    sources: str
    category: str  # DERIVATION | AGGREGATION | TRANSLATION
    definition: str


DERIVED = [
    Derived(
        "core.orders", "purchase_date", "purchase_at", "DERIVATION", "Calendar date of purchase."
    ),
    Derived(
        "core.orders",
        "purchase_year / _month / _weekday / _hour",
        "purchase_at",
        "DERIVATION",
        "Calendar parts of purchase_at; weekday 0 = Monday.",
    ),
    Derived(
        "core.orders",
        "is_delivered",
        "order_status, delivered_to_customer_at",
        "DERIVATION",
        "Status is delivered and a delivery timestamp exists.",
    ),
    Derived(
        "core.orders",
        "delivery_days",
        "purchase_at, delivered_to_customer_at",
        "DERIVATION",
        "Elapsed days from purchase to delivery (fractional). Null when not delivered.",
    ),
    Derived(
        "core.orders",
        "estimated_delivery_days",
        "purchase_at, estimated_delivery_at",
        "DERIVATION",
        "Elapsed days from purchase to the promised date (fractional).",
    ),
    Derived(
        "core.orders",
        "delivery_delay_days",
        "delivered_to_customer_at, estimated_delivery_at",
        "DERIVATION",
        "Delivery date minus promised date, in whole days. Negative = early. Null when not delivered.",
    ),
    Derived(
        "core.orders",
        "is_late",
        "delivered_to_customer_at, estimated_delivery_at",
        "DERIVATION",
        "Delivered on a later calendar date than promised. Null (not false) when not delivered.",
    ),
    Derived(
        "core.orders",
        "has_lifecycle_anomaly",
        "all order timestamps, order_status",
        "DERIVATION",
        "The order carries at least one lifecycle-ordering or status/date warning.",
    ),
    Derived(
        "core.orders",
        "in_analysis_window",
        "purchase_at",
        "DERIVATION",
        "Purchase falls inside the analysis window (2017-01-01 to 2018-08-31).",
    ),
    Derived(
        "core.order_items",
        "item_total",
        "price, freight_value",
        "DERIVATION",
        "price + freight_value.",
    ),
    Derived(
        "core.reviews",
        "has_title / has_message / message_length",
        "review_title, review_message",
        "DERIVATION",
        "Presence and length of the optional texts.",
    ),
    Derived(
        "core.products",
        "category_name_english",
        "category_name, category_translation",
        "TRANSLATION",
        "English category. Null when no translation exists (never 'Unknown').",
    ),
    Derived(
        "core.geo_zip_prefix",
        "latitude, longitude",
        "geolocation",
        "AGGREGATION",
        "Median of distinct in-Brazil observations for the prefix. A prefix centroid, not an address.",
    ),
    Derived(
        "analytics.order_financial_summary",
        "order_total",
        "order_items.price, order_items.freight_value",
        "AGGREGATION",
        "Sum of item price + freight per order.",
    ),
    Derived(
        "analytics.order_financial_summary",
        "payment_total",
        "payments.payment_value",
        "AGGREGATION",
        "Sum of payment records per order.",
    ),
    Derived(
        "analytics.order_financial_summary",
        "reconciliation_status",
        "order_total, payment_total",
        "DERIVATION",
        "MATCHED (within R$0.01), MINOR_DIFFERENCE (within R$1), SIGNIFICANT_DIFFERENCE, "
        "NO_PAYMENT_RECORD or NO_ITEMS.",
    ),
    Derived(
        "analytics.daily_sales",
        "gross_order_value",
        "order_items.price, order_items.freight_value",
        "AGGREGATION",
        "Sum of price + freight of orders placed that day, excluding canceled and unavailable "
        "orders. Not profit.",
    ),
]
