"""Validation: decides which staged rows are accepted, flagged or rejected.

Every rule returns a boolean mask of failing rows, and every failure of a row is
collected (a row can fail several rules). Severity then decides the outcome:

    CRITICAL  the run fails and nothing is promoted
    ERROR     the row is rejected and quarantined with its reasons
    WARNING   the row is kept and the issue is recorded
"""

import math
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

import pandas as pd

from opspulse.etl import config
from opspulse.etl.schema import CODE, FLOAT, ID, INT, KEYS, MONEY, STAGING, STATE, TIMESTAMP


class Severity(StrEnum):
    CRITICAL = "CRITICAL"
    ERROR = "ERROR"
    WARNING = "WARNING"


CRITICAL, ERROR, WARNING = Severity.CRITICAL, Severity.ERROR, Severity.WARNING
REJECTING = [CRITICAL, ERROR]

ISSUE_COLUMNS = ["table", "row", "code", "severity", "stage"]

# A mask function receives the staged table and the raw (text) table, same index.
Mask = Callable[[pd.DataFrame, pd.DataFrame], pd.Series]


@dataclass(frozen=True)
class Rule:
    table: str
    code: str
    severity: Severity
    gate: str  # keys | completeness | values | dates | references
    description: str
    failing: Mask


@dataclass(frozen=True)
class Reference:
    child: str
    column: str
    parent: str
    parent_column: str
    code: str
    severity: Severity
    description: str


def _mismatch(series: pd.Series, pattern: str) -> pd.Series:
    return series.notna() & ~series.fillna("").str.fullmatch(pattern)


def outside_brazil(geo: pd.DataFrame) -> pd.Series:
    inside = geo["latitude"].between(*config.BRAZIL_LATITUDE) & geo["longitude"].between(
        *config.BRAZIL_LONGITUDE
    )
    return geo["latitude"].notna() & geo["longitude"].notna() & ~inside


def _outside_source_period(*columns: str) -> Mask:
    def failing(df: pd.DataFrame, raw: pd.DataFrame) -> pd.Series:
        mask = pd.Series(False, index=df.index)
        for column in columns:
            mask |= df[column].notna() & ~df[column].between(*config.SOURCE_PERIOD)
        return mask

    return failing


def _column_rules(table: str) -> list[Rule]:
    """Rules every column gets from its kind in the staging contract."""
    key = KEYS[table] or []
    rules = []
    for name, column in STAGING[table].items():
        upper = name.upper()
        if column.required:
            in_key = name in key
            rules.append(
                Rule(
                    table,
                    f"MISSING_{upper}",
                    CRITICAL if in_key else ERROR,
                    "keys" if in_key else "completeness",
                    f"`{name}` is empty.",
                    lambda df, raw, n=name: df[n].isna(),
                )
            )
        if column.kind == ID:
            rules.append(
                Rule(
                    table,
                    f"INVALID_{upper}",
                    ERROR,
                    "keys",
                    f"`{name}` is not a 32-character lowercase hex id.",
                    lambda df, raw, n=name: _mismatch(df[n], config.HASH_ID),
                )
            )
        elif column.kind == CODE:
            rules.append(
                Rule(
                    table,
                    f"INVALID_{upper}",
                    ERROR if column.required else WARNING,
                    "values",
                    f"`{name}` is not five digits.",
                    lambda df, raw, n=name: _mismatch(df[n], config.ZIP_PREFIX),
                )
            )
        elif column.kind == STATE:
            rules.append(
                Rule(
                    table,
                    f"INVALID_{upper}",
                    WARNING,
                    "values",
                    f"`{name}` is not a Brazilian state abbreviation.",
                    lambda df, raw, n=name: df[n].notna() & ~df[n].isin(config.BRAZIL_STATES),
                )
            )
        elif column.kind in (INT, MONEY, FLOAT, TIMESTAMP):
            expected = "a timestamp" if column.kind == TIMESTAMP else "a number"
            rules.append(
                Rule(
                    table,
                    f"INVALID_{upper}",
                    ERROR,
                    "dates" if column.kind == TIMESTAMP else "values",
                    f"`{column.source}` has text that does not parse as {expected}.",
                    lambda df, raw, n=name, s=column.source: (
                        raw[s].fillna("").str.strip().ne("") & df[n].isna()
                    ),
                )
            )
    if key:
        rules.append(
            Rule(
                table,
                "DUPLICATE_KEY",
                CRITICAL,
                "keys",
                f"More than one row shares the key ({', '.join(key)}).",
                lambda df, raw, k=tuple(key): df.duplicated(list(k), keep=False),
            )
        )
    return rules


LIFECYCLE_CODES = frozenset(
    {
        "APPROVED_BEFORE_PURCHASE",
        "CARRIER_BEFORE_APPROVAL",
        "DELIVERED_BEFORE_CARRIER",
        "DELIVERED_BEFORE_PURCHASE",
        "DELIVERED_WITHOUT_DELIVERY_DATE",
        "DELIVERY_DATE_ON_UNDELIVERED_ORDER",
    }
)

MEASUREMENTS = [
    "name_length",
    "description_length",
    "photos_qty",
    "weight_g",
    "length_cm",
    "height_cm",
    "width_cm",
]
DIMENSIONS = ["weight_g", "length_cm", "height_cm", "width_cm"]

# fmt: off
BUSINESS_RULES = [
    # orders
    Rule("orders", "UNEXPECTED_ORDER_STATUS", WARNING, "values",
         "Status is not one of the statuses observed in the source.",
         lambda df, raw: df["order_status"].notna()
         & ~df["order_status"].isin(config.KNOWN_ORDER_STATUSES)),
    Rule("orders", "APPROVED_BEFORE_PURCHASE", WARNING, "dates",
         "Approval is earlier than purchase.",
         lambda df, raw: df["approved_at"] < df["purchase_at"]),
    Rule("orders", "CARRIER_BEFORE_APPROVAL", WARNING, "dates",
         "Hand-over to the carrier is earlier than approval.",
         lambda df, raw: df["delivered_to_carrier_at"] < df["approved_at"]),
    Rule("orders", "DELIVERED_BEFORE_CARRIER", WARNING, "dates",
         "Delivery to the customer is earlier than hand-over to the carrier.",
         lambda df, raw: df["delivered_to_customer_at"] < df["delivered_to_carrier_at"]),
    Rule("orders", "DELIVERED_BEFORE_PURCHASE", WARNING, "dates",
         "Delivery to the customer is earlier than purchase.",
         lambda df, raw: df["delivered_to_customer_at"] < df["purchase_at"]),
    Rule("orders", "DELIVERED_WITHOUT_DELIVERY_DATE", WARNING, "dates",
         "Status is delivered but there is no delivery timestamp.",
         lambda df, raw: df["order_status"].eq("delivered")
         & df["delivered_to_customer_at"].isna()),
    Rule("orders", "DELIVERY_DATE_ON_UNDELIVERED_ORDER", WARNING, "dates",
         "There is a delivery timestamp but the status is not delivered.",
         lambda df, raw: df["order_status"].ne("delivered")
         & df["delivered_to_customer_at"].notna()),
    Rule("orders", "TIMESTAMP_OUTSIDE_SOURCE_PERIOD", WARNING, "dates",
         "A timestamp falls outside 2016-2018.",
         _outside_source_period("purchase_at", "approved_at", "delivered_to_carrier_at",
                                "delivered_to_customer_at", "estimated_delivery_at")),
    # order_items
    Rule("order_items", "NEGATIVE_PRICE", ERROR, "values", "Price is below zero.",
         lambda df, raw: df["price"] < 0),
    Rule("order_items", "NEGATIVE_FREIGHT", ERROR, "values", "Freight is below zero.",
         lambda df, raw: df["freight_value"] < 0),
    Rule("order_items", "ZERO_PRICE", WARNING, "values", "Price is exactly zero.",
         lambda df, raw: df["price"] == 0),
    Rule("order_items", "TIMESTAMP_OUTSIDE_SOURCE_PERIOD", WARNING, "dates",
         "Shipping limit falls outside 2016-2018.",
         _outside_source_period("shipping_limit_at")),
    # payments
    Rule("payments", "PAYMENT_SEQUENCE_BELOW_ONE", ERROR, "values",
         "Payment sequence is below 1.",
         lambda df, raw: df["payment_sequence"] < 1),
    Rule("payments", "NEGATIVE_INSTALLMENTS", ERROR, "values", "Installments are below zero.",
         lambda df, raw: df["payment_installments"] < 0),
    Rule("payments", "NEGATIVE_PAYMENT_VALUE", ERROR, "values", "Payment value is below zero.",
         lambda df, raw: df["payment_value"] < 0),
    Rule("payments", "ZERO_INSTALLMENTS", WARNING, "values", "Installments are zero.",
         lambda df, raw: df["payment_installments"] == 0),
    Rule("payments", "ZERO_PAYMENT_VALUE", WARNING, "values", "Payment value is zero.",
         lambda df, raw: df["payment_value"] == 0),
    Rule("payments", "UNDEFINED_PAYMENT_TYPE", WARNING, "values",
         "Payment type is `not_defined`.",
         lambda df, raw: df["payment_type"].eq("not_defined")),
    # reviews
    Rule("reviews", "REVIEW_SCORE_OUT_OF_RANGE", ERROR, "values", "Score is not 1 to 5.",
         lambda df, raw: df["review_score"].notna() & ~df["review_score"].between(1, 5)),
    Rule("reviews", "ANSWERED_BEFORE_CREATED", WARNING, "dates",
         "The answer is earlier than the survey.",
         lambda df, raw: df["answered_at"] < df["created_at"]),
    Rule("reviews", "TIMESTAMP_OUTSIDE_SOURCE_PERIOD", WARNING, "dates",
         "A timestamp falls outside 2016-2018.",
         _outside_source_period("created_at", "answered_at")),
    # products
    Rule("products", "NEGATIVE_MEASUREMENT", ERROR, "values",
         "A length, count, weight or dimension is below zero.",
         lambda df, raw: (df[MEASUREMENTS] < 0).any(axis=1)),
    Rule("products", "ZERO_WEIGHT", WARNING, "values", "Weight is exactly zero.",
         lambda df, raw: df["weight_g"] == 0),
    Rule("products", "MISSING_CATEGORY", WARNING, "completeness", "Category is empty.",
         lambda df, raw: df["category_name"].isna()),
    Rule("products", "MISSING_DIMENSIONS", WARNING, "completeness",
         "Weight or a package dimension is empty.",
         lambda df, raw: df[DIMENSIONS].isna().any(axis=1)),
    # geolocation
    Rule("geolocation", "COORDINATES_OUT_OF_RANGE", ERROR, "values",
         "Latitude is outside ±90 or longitude outside ±180.",
         lambda df, raw: (df["latitude"].abs() > 90) | (df["longitude"].abs() > 180)),
    Rule("geolocation", "OUTSIDE_BRAZIL", WARNING, "values",
         "Point is outside Brazil's bounding box; excluded from zip centroids.",
         lambda df, raw: outside_brazil(df)),
]
# fmt: on

RULES: list[Rule] = [rule for table in STAGING for rule in _column_rules(table)] + BUSINESS_RULES

# fmt: off
# Order matters: parents are settled before their children, so rejections cascade
# (an order rejected for a missing customer takes its items, payments and reviews with it).
REFERENCES = [
    Reference("orders", "customer_id", "customers", "customer_id",
              "MISSING_CUSTOMER_REFERENCE", ERROR, "Order's customer does not exist."),
    Reference("order_items", "order_id", "orders", "order_id",
              "MISSING_ORDER_REFERENCE", ERROR, "Item's order does not exist."),
    Reference("order_items", "product_id", "products", "product_id",
              "MISSING_PRODUCT_REFERENCE", ERROR, "Item's product does not exist."),
    Reference("order_items", "seller_id", "sellers", "seller_id",
              "MISSING_SELLER_REFERENCE", ERROR, "Item's seller does not exist."),
    Reference("payments", "order_id", "orders", "order_id",
              "MISSING_ORDER_REFERENCE", ERROR, "Payment's order does not exist."),
    Reference("reviews", "order_id", "orders", "order_id",
              "MISSING_ORDER_REFERENCE", ERROR, "Review's order does not exist."),
    Reference("products", "category_name", "category_translation", "category_name",
              "MISSING_CATEGORY_TRANSLATION", WARNING, "Category has no English translation."),
    Reference("customers", "zip_code_prefix", "geolocation", "zip_code_prefix",
              "ZIP_NOT_IN_GEOLOCATION", WARNING, "Zip prefix has no geolocation observation."),
    Reference("sellers", "zip_code_prefix", "geolocation", "zip_code_prefix",
              "ZIP_NOT_IN_GEOLOCATION", WARNING, "Zip prefix has no geolocation observation."),
]
# fmt: on


@dataclass(frozen=True)
class CatalogueEntry:
    severity: Severity
    gate: str
    description: str


CATALOGUE: dict[tuple[str, str], CatalogueEntry] = {
    (rule.table, rule.code): CatalogueEntry(rule.severity, rule.gate, rule.description)
    for rule in RULES
} | {
    (ref.child, ref.code): CatalogueEntry(ref.severity, "references", ref.description)
    for ref in REFERENCES
}


def _issues(table: str, rows: pd.Index, code: str, severity: Severity, stage: str) -> pd.DataFrame:
    return pd.DataFrame(
        {"table": table, "row": rows, "code": code, "severity": str(severity), "stage": stage}
    )


def _concat(frames: list[pd.DataFrame]) -> pd.DataFrame:
    if not frames:
        return pd.DataFrame({column: pd.Series(dtype="str") for column in ISSUE_COLUMNS}).astype(
            {"row": "int64"}
        )
    return pd.concat(frames, ignore_index=True)


def validate_rows(staged: dict[str, pd.DataFrame], raw: dict[str, pd.DataFrame]) -> pd.DataFrame:
    frames = []
    for rule in RULES:
        if rule.table not in staged:
            continue
        df = staged[rule.table]
        mask = rule.failing(df, raw[rule.table]).fillna(False).astype(bool)
        if mask.any():
            frames.append(
                _issues(rule.table, df.index[mask], rule.code, rule.severity, "row_validation")
            )
    return _concat(frames)


def rejected_rows(issues: pd.DataFrame, table: str) -> pd.Index:
    hits = issues[(issues["table"] == table) & issues["severity"].isin(REJECTING)]
    return pd.Index(hits["row"].unique())


def validate_references(staged: dict[str, pd.DataFrame], row_issues: pd.DataFrame) -> pd.DataFrame:
    rejected = {table: rejected_rows(row_issues, table) for table in staged}
    frames = []
    for ref in REFERENCES:
        child, parent = staged[ref.child], staged[ref.parent]
        parent_keys = parent.loc[~parent.index.isin(rejected[ref.parent]), ref.parent_column]
        values = child[ref.column]
        mask = (
            ~child.index.isin(rejected[ref.child])
            & values.notna()
            & ~values.isin(parent_keys.dropna())
        )
        if mask.any():
            rows = child.index[mask]
            frames.append(_issues(ref.child, rows, ref.code, ref.severity, "referential_integrity"))
            if ref.severity in REJECTING:
                rejected[ref.child] = rejected[ref.child].union(rows)
    return _concat(frames)


def critical_problems(
    staged: dict[str, pd.DataFrame],
    issues: pd.DataFrame,
    max_rejection_share: float = config.CATASTROPHIC_REJECTION_SHARE,
) -> list[str]:
    problems = [f"{table}: table is empty" for table, df in staged.items() if df.empty]
    critical = issues[issues["severity"] == CRITICAL]
    for (table, code), group in critical.groupby(["table", "code"]):
        problems.append(f"{table}: {code} on {len(group):,} rows")
    for table, df in staged.items():
        share = len(rejected_rows(issues, table)) / max(len(df), 1)
        if share > max_rejection_share:
            problems.append(
                f"{table}: {share:.1%} of rows rejected (limit {max_rejection_share:.0%})"
            )
    return problems


def check_core(core: dict[str, pd.DataFrame], accepted: dict[str, pd.DataFrame]) -> list[str]:
    """Guards against bugs in core building: grains and references must hold by construction."""
    problems = []
    for table, key in KEYS.items():
        if key and table in core and core[table].duplicated(key).any():
            problems.append(f"core.{table}: duplicate ({', '.join(key)})")
        if table in core and len(core[table]) != len(accepted[table]):
            problems.append(
                f"core.{table}: {len(core[table])} rows, expected {len(accepted[table])}"
            )
    if core["geo_zip_prefix"]["zip_code_prefix"].duplicated().any():
        problems.append("core.geo_zip_prefix: duplicate zip_code_prefix")
    for ref in REFERENCES:
        if ref.severity in REJECTING:
            values = core[ref.child][ref.column]
            if (~values.isin(core[ref.parent][ref.parent_column])).any():
                problems.append(f"core.{ref.child}.{ref.column}: references a missing {ref.parent}")
    return problems


def check_analytics(core: dict[str, pd.DataFrame], analytics: dict[str, pd.DataFrame]) -> list[str]:
    problems = []
    summary, daily = analytics["order_financial_summary"], analytics["daily_sales"]
    if summary["order_id"].duplicated().any() or len(summary) != len(core["orders"]):
        problems.append("analytics.order_financial_summary: not one row per core order")
    if daily["sales_date"].duplicated().any():
        problems.append("analytics.daily_sales: duplicate sales_date")
    sales = summary[~summary["order_status"].isin(config.NON_SALE_STATUSES)]
    if not math.isclose(
        daily["gross_order_value"].sum(), sales["order_total"].sum(), rel_tol=1e-9, abs_tol=0.01
    ):
        problems.append("analytics.daily_sales: gross_order_value does not match order totals")
    if daily["item_count"].sum() != sales["item_count"].sum():
        problems.append("analytics.daily_sales: item_count does not match order items")
    return problems
