# OpsPulse — Data Foundation & ETL Handover

**Document type:** End-to-end implementation handover  
**Project:** OpsPulse — Business Operations Intelligence Platform  
**Current phase:** Data Foundation / ETL  
**Current status:** Olist dataset downloaded from Kaggle; processing has not yet been finalized  
**Next major phase:** PostgreSQL loading, followed by external API, ingestion/synchronization, analytics, anomaly detection, frontend, DevOps and deployment

> **Amendments (2026-10-04).** Phase 1 is implemented (`opspulse-etl run`). Where the
> downloaded files contradicted this document, the code follows the data:
>
> - reviews are keyed by (`review_id`, `order_id`);
> - a zip prefix missing from geolocation is a WARNING;
> - lifecycle-ordering anomalies are flagged, not quarantined;
> - lateness compares calendar dates;
> - geolocation centroids use the median of distinct in-Brazil points.
>
> Analytics move after ingestion so the replay drives the dashboard. The package is
> `src/opspulse/etl`, and `uv.lock` replaces the version pins in §7. Rationale and evidence:
> [docs/ROADMAP.md](docs/ROADMAP.md). The enforced contract:
> [docs/data/data_dictionary.md](docs/data/data_dictionary.md).

---

## 1. Purpose of this handover

This document is the definitive implementation guide for the **data foundation of OpsPulse**.

The immediate objective is **not** to build the dashboard, FastAPI application, ML model, Celery workers or deployment.

The immediate objective is to take the downloaded **Olist Brazilian E-Commerce Public Dataset** and turn it into a:

- reproducible
- auditable
- validated
- relationally consistent
- analytically useful
- PostgreSQL-ready

data foundation.

The central principle is:

> **Do not fabricate the business reality when a credible public source already exists.**

The Olist dataset is the business reality for this portfolio project. Python is used to inspect, validate, transform, enrich and derive analytical information from that source. Synthetic data should not be used to manufacture fake customers, fake orders or fake payment history.

Olist describes the source as real commercial data that has been anonymised. Its dataset covers approximately 100,000 orders from 2016–2018 and provides order status, pricing, payment, freight, customer location, product attributes, seller information and reviews. The published package contains nine CSV files.  
Source: https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce  
Metadata: https://www.kaggle.com/olistbr/brazilian-ecommerce/metadata

---

# 2. The data architecture we are implementing

The data flow is:

```text
                  OLIST SOURCE FILES
                         |
                         v
                  +--------------+
                  |     RAW      |
                  |  immutable   |
                  +--------------+
                         |
                         v
                  +--------------+
                  |   PROFILING  |
                  |   + AUDIT    |
                  +--------------+
                         |
                         v
                  +--------------+
                  |   STAGING    |
                  | typed/cleaned|
                  +--------------+
                         |
                         v
                  +--------------+
                  | VALIDATION   |
                  | quality/FKs  |
                  +--------------+
                     /       \
                    /         \
                   v           v
              accepted      rejected
                 data        records
                   |
                   v
             +-------------+
             | CORE DATA   |
             | relational  |
             +-------------+
                   |
                   v
             +-------------+
             | ANALYTICS   |
             | derived     |
             +-------------+
                   |
                   v
              PostgreSQL
                   |
                   v
          External API / OpsPulse
                   |
                   v
             Analytics / ML
                   |
                   v
             Next.js Dashboard
```

There are deliberately separate layers:

```text
RAW
STAGING
CORE
ANALYTICS
```

Do not collapse them into one directory or one database table.

---

# 3. Non-negotiable data principles

## 3.1 Raw source must remain immutable

The original Kaggle files must never be edited.

Do not:

- rename columns inside the raw files
- delete rows
- replace nulls
- correct values
- translate categories
- change encodings and overwrite the originals
- modify dates
- modify IDs

If a transformation is required, perform it downstream.

This guarantees that the entire processed dataset can always be regenerated from the original source.

---

## 3.2 Never silently discard records

Bad:

```python
df = df.dropna()
```

Better:

```text
raw
 |
 +-- valid --> staging/core
 |
 +-- invalid --> rejected/<table>.csv
```

Every rejected record should have:

- source table
- source row identifier if available
- rejection reason
- pipeline stage
- pipeline run ID

Example:

```text
source_table,source_row,rejection_reason,pipeline_run_id
orders,18273,INVALID_ORDER_ID,2026-10-04T...
```

---

## 3.3 Missing does not automatically mean invalid

For example, an order delivery date may be missing because that order was not delivered.

Do not replace it with:

```text
1970-01-01
```

or:

```text
"unknown"
```

and do not automatically reject the order.

Instead preserve the null and interpret it according to the business lifecycle.

---

## 3.4 Never invent information that the source does not contain

Do not infer:

- exact street addresses
- exact customer coordinates
- profit
- business cost
- payment processor fees
- seller cost
- customer income
- customer demographics

unless those data actually exist.

For example, Olist geolocation contains postal-prefix-level geographic observations. It does **not** justify claiming that a coordinate is an exact customer address.

---

## 3.5 Keep source facts separate from derived metrics

Example:

```text
SOURCE FACT
price = 120.00

DERIVED
item_total = price + freight_value
```

Do not overwrite the original source fact.

Likewise:

```text
SOURCE:
order_purchase_timestamp

DERIVED:
purchase_date
purchase_hour
purchase_week
purchase_month
delivery_days
delivery_delay_days
is_late
```

---

# 4. Source inventory

The downloaded dataset should contain these nine files:

```text
olist_customers_dataset.csv
olist_geolocation_dataset.csv
olist_order_items_dataset.csv
olist_order_payments_dataset.csv
olist_order_reviews_dataset.csv
olist_orders_dataset.csv
olist_products_dataset.csv
olist_sellers_dataset.csv
product_category_name_translation.csv
```

These should be stored under:

```text
data/raw/olist/
```

The source metadata identifies the major relationships, including:

```text
customers -> orders
orders -> order_items
orders -> payments
orders -> reviews
order_items -> products
order_items -> sellers
products -> category translation
customers/sellers -> geographic postal prefixes
```

Source:  
https://www.kaggle.com/olistbr/brazilian-ecommerce/metadata

---

# 5. Recommended repository structure

Create the project as:

```text
opspulse/
|
├── data/
│   ├── raw/
│   │   └── olist/
│   │       ├── olist_customers_dataset.csv
│   │       ├── olist_geolocation_dataset.csv
│   │       ├── olist_order_items_dataset.csv
│   │       ├── olist_order_payments_dataset.csv
│   │       ├── olist_order_reviews_dataset.csv
│   │       ├── olist_orders_dataset.csv
│   │       ├── olist_products_dataset.csv
│   │       ├── olist_sellers_dataset.csv
│   │       └── product_category_name_translation.csv
│   │
│   ├── staging/
│   │   └── olist/
│   │
│   ├── processed/
│   │   ├── core/
│   │   └── analytics/
│   │
│   └── rejected/
│       └── olist/
│
├── reports/
│   └── data_quality/
│
├── src/
│   └── etl/
│       ├── __init__.py
│       ├── config.py
│       ├── logging_config.py
│       ├── extract.py
│       ├── profile.py
│       ├── transform.py
│       ├── validate.py
│       ├── lineage.py
│       ├── load_files.py
│       ├── analytics.py
│       ├── pipeline.py
│       └── utils.py
│
├── tests/
│   └── etl/
│       ├── test_extract.py
│       ├── test_transform.py
│       ├── test_validate.py
│       └── test_relationships.py
│
├── docs/
│   └── data/
│       ├── data_dictionary.md
│       ├── source_relationships.md
│       └── data_quality.md
│
├── requirements.txt
├── .gitignore
└── README.md
```

---

# 6. What goes into Git and what does not

Do NOT commit the downloaded source CSV files to GitHub.

The repository should contain:

```text
source metadata
ETL code
schema
tests
configuration examples
documentation
data-quality reports
small samples if needed
```

The repository should NOT contain:

```text
full Olist CSV files
large generated datasets
local database files
secrets
API keys
.env
```

Use a `.gitignore` like:

```gitignore
# Python
__pycache__/
*.py[cod]
.pytest_cache/

# Environment
.env
.env.*
!.env.example

# Data
data/raw/
data/staging/
data/processed/
data/rejected/

# Local database / tooling
*.db
*.sqlite
*.sqlite3

# IDE
.vscode/
.idea/

# OS
.DS_Store
Thumbs.db
```

Important: the source data remains locally available to reproduce the pipeline, but it is not uploaded to the public repository.

---

# 7. Dependencies

For the first data phase:

```text
pandas
numpy
pyarrow
python-dotenv
pydantic
pytest
```

Potential `requirements.txt`:

```text
pandas>=3.0,<4
numpy>=2.0,<3
pyarrow>=18,<24
python-dotenv>=1.0,<2
pydantic>=2.0,<3
pytest>=8,<9
```

The exact versions can be pinned later after the environment has been tested.

Pandas supports CSV ingestion and chunked reading, and `pandas.to_datetime()` provides explicit datetime conversion with controllable invalid-value behavior.  
Sources:  
https://pandas.pydata.org/docs/reference/api/pandas.read_csv.html  
https://pandas.pydata.org/docs/reference/api/pandas.to_datetime.html

---

# 8. Step 1 — Verify the raw files

Before reading the data, confirm that all nine expected files exist.

Create:

```text
src/etl/config.py
```

Example:

```python
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]

RAW_DIR = PROJECT_ROOT / "data" / "raw" / "olist"
STAGING_DIR = PROJECT_ROOT / "data" / "staging" / "olist"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
REJECTED_DIR = PROJECT_ROOT / "data" / "rejected" / "olist"
REPORT_DIR = PROJECT_ROOT / "reports" / "data_quality"


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
```

Then check:

```python
def verify_source_files() -> None:
    missing = []

    for table_name, filename in SOURCE_FILES.items():
        path = RAW_DIR / filename

        if not path.exists():
            missing.append(str(path))

    if missing:
        raise FileNotFoundError(
            "Missing source files:\n" + "\n".join(missing)
        )
```

Do this before any processing.

---

# 9. Step 2 — Create source fingerprints

A professional pipeline should know exactly which input files it processed.

Calculate a SHA-256 checksum for every raw file.

Example:

```python
import hashlib
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)

    return digest.hexdigest()
```

Create a manifest:

```text
reports/data_quality/source_manifest.json
```

Example structure:

```json
{
  "pipeline_run_id": "2026-10-04T12:30:00Z",
  "files": {
    "olist_orders_dataset.csv": {
      "sha256": "...",
      "bytes": 12345678
    }
  }
}
```

This means you can prove:

> "This processed result came from this exact source file."

---

# 10. Step 3 — Profile the raw data BEFORE cleaning

This is critical.

Do not decide how to clean a field before inspecting it.

For every table calculate:

```text
row_count
column_count
column_names
dtype
null_count
null_percentage
unique_count
duplicate_count
min
max
mean
median
```

For categorical columns also calculate:

```text
value_frequency
```

For dates:

```text
minimum_timestamp
maximum_timestamp
invalid_parse_count
```

For identifiers:

```text
duplicate_count
null_count
```

For relationships:

```text
orphan_reference_count
```

---

# 11. Profiling output

Create:

```text
reports/data_quality/
    raw_profile.json
    raw_profile.md
```

Example human-readable output:

```text
TABLE: ORDERS

Rows:
99,XXX

Columns:
9

order_id
---------
nulls: 0
unique: ...
duplicates: ...

order_status
------------
unique values:
delivered
shipped
canceled
...

order_purchase_timestamp
------------------------
min: ...
max: ...
invalid dates: 0

...
```

Do not hard-code any dataset row counts in this report.

The profiling script must calculate them from your actual files.

---

# 12. Raw profiling implementation

Example:

```python
from pathlib import Path
import pandas as pd


def profile_dataframe(df: pd.DataFrame) -> dict:
    profile = {
        "row_count": len(df),
        "column_count": len(df.columns),
        "columns": {}
    }

    for column in df.columns:
        series = df[column]

        info = {
            "dtype": str(series.dtype),
            "null_count": int(series.isna().sum()),
            "null_percentage": float(
                series.isna().mean() * 100
            ),
            "unique_count": int(series.nunique(dropna=True)),
        }

        if pd.api.types.is_numeric_dtype(series):
            info["min"] = (
                float(series.min())
                if not series.dropna().empty else None
            )
            info["max"] = (
                float(series.max())
                if not series.dropna().empty else None
            )

        if pd.api.types.is_object_dtype(series):
            info["top_values"] = (
                series.value_counts(dropna=False)
                .head(20)
                .to_dict()
            )

        profile["columns"][column] = info

    return profile
```

---

# 13. Important: investigate encoding before assuming UTF-8

The Olist source contains text-heavy files, particularly reviews.

Do not blindly assume every file uses exactly the same encoding.

First attempt:

```python
pd.read_csv(path, encoding="utf-8")
```

If a file raises a decoding error, inspect and handle that source explicitly.

Some published analyses of this same dataset have reported encoding complications with the reviews file, but your local copy is the authoritative input for this project. Therefore:

> Detect the actual condition in your files rather than copying someone else's assumed encoding.

A published Olist analysis notes a LATIN1 requirement for its review-file load; treat this as a troubleshooting hint, not as permission to overwrite the raw file or hard-code the encoding without testing.  
Reference: https://www.kaggle.com/writeups/shivamtamboli62/olist-ecommerce-analytics

---

# 14. Recommended extraction strategy

For these files, standard Pandas loading is sufficient during the initial pipeline.

Example:

```python
def load_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(
        path,
        low_memory=False
    )
```

For larger future data sources, use:

```python
pd.read_csv(
    path,
    chunksize=100_000
)
```

The current Olist dataset is manageable for a local ETL workflow, so do not introduce unnecessary distributed-processing technology.

---

# 15. Step 4 — Define the source data dictionary

Create:

```text
docs/data/data_dictionary.md
```

For each source field document:

```text
source table
source column
business meaning
source data type
expected canonical type
nullable?
identifier?
primary key?
foreign key?
transformation
validation
```

Example:

```text
TABLE: orders

Column:
order_id

Meaning:
Unique order identifier in the Olist order dataset.

Canonical type:
VARCHAR / TEXT

Nullable:
No

Key:
Primary key

Transform:
Convert to string and trim whitespace.

Validation:
Must not be null.
Must be unique.
```

Do this for every source column.

This document becomes the contract for the ETL.

---

# 16. Business relationship model

The primary business graph is:

```text
                    customers
                        |
                        | customer_id
                        v
                      orders
                   /    |     \
                  /     |      \
                 v      v       v
          order_items payments reviews
              /   \
             /     \
            v       v
       products   sellers
           |
           v
 category_translation
```

Geographic linkage:

```text
customers.customer_zip_code_prefix
                     |
                     v
             geo_zip_prefix

sellers.seller_zip_code_prefix
                     |
                     v
             geo_zip_prefix
```

The exact source relationships should be confirmed against the Olist metadata before creating constraints.  
Source: https://www.kaggle.com/olistbr/brazilian-ecommerce/metadata

---

# 17. Step 5 — Staging layer

The staging layer is where we perform **technical standardization**, not major business modeling.

The general process is:

```text
RAW CSV
  |
  +--> standardized column names
  |
  +--> typed IDs
  |
  +--> typed numeric values
  |
  +--> parsed timestamps
  |
  +--> normalized whitespace/casing
  |
  v
STAGING
```

The staging dataset should still resemble the source table.

Do not join all tables together in staging.

---

# 18. ID normalization

IDs should generally be represented as strings.

Examples:

```text
customer_id
customer_unique_id
order_id
product_id
seller_id
review_id
```

Use:

```python
df[column] = (
    df[column]
    .astype("string")
    .str.strip()
)
```

Why string?

Because identifiers are labels, not mathematical quantities.

Do not treat:

```text
customer_id = "001234"
```

as the number:

```text
1234
```

where doing so could destroy formatting or semantics.

---

# 19. Postal code normalization

The source uses five-digit postal code prefixes.

Canonical handling:

```python
df["zip_code_prefix"] = (
    df["zip_code_prefix"]
    .astype("string")
    .str.strip()
    .str.zfill(5)
)
```

Validate:

```python
df["zip_code_prefix"].str.fullmatch(r"\d{5}")
```

Invalid values should be reported.

Do not invent missing postal codes.

---

# 20. State normalization

For Brazilian state abbreviations:

```python
df["state"] = (
    df["state"]
    .astype("string")
    .str.strip()
    .str.upper()
)
```

Expected values can be checked against a known reference list of Brazilian state/territory abbreviations.

Validation should report unexpected values rather than silently deleting them.

---

# 21. City normalization

At minimum:

```python
df["city"] = (
    df["city"]
    .astype("string")
    .str.strip()
)
```

Do NOT automatically:

```python
str.title()
```

because casing conventions are not necessarily semantic normalization.

Do not arbitrarily remove accents or special characters.

Preserve the source text unless there is a well-defined normalization requirement.

---

# 22. Timestamp normalization

The orders dataset has lifecycle timestamps.

These should be parsed explicitly.

Recommended:

```python
df[column] = pd.to_datetime(
    df[column],
    errors="coerce"
)
```

Important:

```text
errors="coerce"
```

turns unparseable values into `NaT`, which then must be counted and investigated.

Do not silently accept parsing failures.

For every date field, calculate:

```text
source_non_null_count
parsed_non_null_count
invalid_parse_count
```

Source:  
https://pandas.pydata.org/docs/reference/api/pandas.to_datetime.html

---

# 23. Orders: exact canonical handling

Source columns:

```text
order_id
customer_id
order_status
order_purchase_timestamp
order_approved_at
order_delivered_carrier_date
order_delivered_customer_date
order_estimated_delivery_date
```

Canonical names:

```text
order_id
customer_id
order_status
purchase_at
approved_at
delivered_to_carrier_at
delivered_to_customer_at
estimated_delivery_at
```

Types:

```text
order_id                  TEXT
customer_id               TEXT
order_status              TEXT
purchase_at               TIMESTAMP
approved_at               TIMESTAMP NULL
delivered_to_carrier_at   TIMESTAMP NULL
delivered_to_customer_at  TIMESTAMP NULL
estimated_delivery_at     TIMESTAMP NULL
```

Do not create derived operational fields in the raw layer.

They belong in processed/core or analytics.

---

# 24. Order lifecycle validation

The timestamps represent stages in an order lifecycle.

Where timestamps are present, investigate:

```text
purchase_at <= approved_at
approved_at <= delivered_to_carrier_at
delivered_to_carrier_at <= delivered_to_customer_at
```

However:

> Do not assume every timestamp should always exist.

An order that is canceled may legitimately have no delivery timestamp.

So validation should distinguish:

```text
INVALID:
A timestamp exists but is logically impossible.

EXPECTED NULL:
A lifecycle stage was never reached.
```

Example:

```text
purchase_at = 2017-05-10
approved_at = 2017-05-11

valid.
```

Example:

```text
purchase_at = 2017-05-10
approved_at = 2017-05-09

potentially invalid.
```

Such records should be quarantined/reviewed, not automatically erased.

---

# 25. Order item processing

Source:

```text
order_id
order_item_id
product_id
seller_id
shipping_limit_date
price
freight_value
```

Canonical:

```text
order_id
order_item_id
product_id
seller_id
shipping_limit_at
price
freight_value
```

Types:

```text
order_id           TEXT
order_item_id      INTEGER
product_id         TEXT
seller_id          TEXT
shipping_limit_at  TIMESTAMP
price              NUMERIC
freight_value      NUMERIC
```

Validation:

```text
order_id NOT NULL
order_item_id NOT NULL
product_id NOT NULL
seller_id NOT NULL
price >= 0
freight_value >= 0
```

---

# 26. Item total

Derive:

```python
df["item_total"] = (
    df["price"] + df["freight_value"]
)
```

This is a derived value.

Keep:

```text
price
freight_value
item_total
```

Do not replace `price`.

Business interpretation:

```text
item_total = product price + freight value
```

Do not call this "profit" because product cost/profit is not available in the source.

---

# 27. Products

The product source contains physical/product-description attributes.

Canonical handling:

```text
product_id
product_category_name
product_name_length
product_description_length
product_photos_qty
product_weight_g
product_length_cm
product_height_cm
product_width_cm
```

The source contains misspelled length column names (`lenght` in the published source). Normalize these into correctly named canonical columns while keeping the raw file unchanged.

Recommended canonical mappings:

```text
product_name_lenght
    ->
product_name_length

product_description_lenght
    ->
product_description_length
```

Validation:

```text
product_weight_g >= 0
product_length_cm >= 0
product_height_cm >= 0
product_width_cm >= 0
product_photos_qty >= 0
```

Null physical attributes should remain null when the source provides no value.

---

# 28. Category translation

There are two concepts:

```text
original category
translated English category
```

Do not destroy the source category.

Canonical structure:

```text
product_category_name
product_category_name_english
```

Process:

```text
products
   |
   | product_category_name
   v
category_translation
   |
   v
product_category_name_english
```

If no translation exists:

```text
product_category_name_english = NULL
```

rather than:

```text
"Unknown"
```

This preserves the distinction between:

```text
translation unavailable
```

and:

```text
actual category named Unknown
```

---

# 29. Payments

Source:

```text
order_id
payment_sequential
payment_type
payment_installments
payment_value
```

Canonical:

```text
order_id
payment_sequence
payment_type
payment_installments
payment_value
```

Types:

```text
order_id            TEXT
payment_sequence    INTEGER
payment_type        TEXT
payment_installments INTEGER
payment_value       NUMERIC
```

Validation:

```text
order_id NOT NULL
payment_sequence >= 1
payment_installments >= 1
payment_value >= 0
```

Do not assume one order has one payment record.

The source explicitly supports sequential payment records for an order.

---

# 30. Payment aggregation

For analytics, create a derived order-level payment table.

Example:

```text
analytics.order_payment_summary
```

Fields:

```text
order_id
payment_record_count
total_payment_value
payment_types_used
max_installments
```

This avoids repeatedly aggregating the raw payment table.

Important:

> `total_payment_value` should be calculated from payment records; it should not simply be assumed to equal the order's item/freight total.

The difference itself can become a **reconciliation metric**.

---

# 31. Payment reconciliation

Create:

```text
analytics.order_financial_summary
```

Potential fields:

```text
order_id
item_value
freight_value
order_total
payment_total
payment_difference
payment_reconciled
```

Where:

```python
order_total = item_value + freight_value
payment_difference = payment_total - order_total
```

Then define a tolerance before declaring mismatch.

Do not assume every difference is automatically fraudulent.

Create categories:

```text
MATCHED
MINOR_DIFFERENCE
SIGNIFICANT_DIFFERENCE
NO_PAYMENT_RECORD
```

The exact tolerance must be documented and treated as a business rule.

---

# 32. Reviews

Source:

```text
review_id
order_id
review_score
review_comment_title
review_comment_message
review_creation_date
review_answer_timestamp
```

Canonical:

```text
review_id
order_id
review_score
review_title
review_message
created_at
answered_at
```

Validation:

```text
review_score between 1 and 5
review_id not null
order_id not null
```

Text should remain text.

Do not replace missing comments with artificial sentences.

Optional derived fields:

```text
has_title
has_message
message_length
```

---

# 33. Review duplicate handling

Do not blindly assume:

```text
review_id = unique
```

until profiling confirms it in your downloaded source.

First calculate:

```python
duplicate_review_ids = (
    reviews["review_id"]
    .duplicated(keep=False)
)
```

If duplicate IDs exist, investigate what differs between those records.

Possible workflow:

```text
duplicate detected
      |
      v
compare records
      |
      +--> exact duplicates
      |       |
      |       v
      |   safe deduplication
      |
      +--> conflicting records
              |
              v
        business decision
```

Never use:

```python
drop_duplicates()
```

without understanding the duplicates first.

---

# 34. Customers

Source:

```text
customer_id
customer_unique_id
customer_zip_code_prefix
customer_city
customer_state
```

Canonical:

```text
customer_id
customer_unique_id
zip_code_prefix
city
state
```

Critical distinction:

```text
customer_id
```

is tied to an order in the Olist system.

```text
customer_unique_id
```

is the identifier intended to identify repeat customers across orders.

Olist explicitly documents this distinction.  
Source: https://www.kaggle.com/olistbr/brazilian-ecommerce/metadata

This becomes very important later for customer analytics.

---

# 35. Customers: two different analytical grains

There will be two useful levels.

### Order-linked customer record

Grain:

```text
one customer_id
```

### Real customer history

Grain:

```text
one customer_unique_id
```

Do not confuse the two.

Example analytical question:

> How many orders did this real customer place?

Use:

```text
customer_unique_id
```

not merely `customer_id`.

---

# 36. Sellers

Source:

```text
seller_id
seller_zip_code_prefix
seller_city
seller_state
```

Canonical:

```text
seller_id
zip_code_prefix
city
state
```

Validation:

```text
seller_id NOT NULL
zip_code_prefix valid format
state valid format
```

Seller metrics later will be derived from order items + orders + reviews.

---

# 37. Geolocation

The geolocation table requires special handling.

It contains repeated observations associated with Brazilian zip code prefixes.

It should not be treated as:

```text
customer address
```

or:

```text
seller address
```

Instead build:

```text
core.geo_zip_prefix
```

with:

```text
zip_code_prefix
latitude
longitude
source_observation_count
```

Potentially derive additional geographic data later, but do not invent precision.

---

# 38. Geolocation aggregation

A defensible first approach:

```python
geo = (
    geo.groupby("geolocation_zip_code_prefix")
       .agg(
           latitude=("geolocation_lat", "mean"),
           longitude=("geolocation_lng", "mean"),
           source_observation_count=(
               "geolocation_zip_code_prefix",
               "size",
           ),
       )
       .reset_index()
)
```

Rename:

```text
geolocation_zip_code_prefix
    ->
zip_code_prefix
```

Document:

> The latitude/longitude stored for a postal-prefix record is an aggregate coordinate derived from the source observations and must not be interpreted as an exact address.

Validate geographic bounds:

```text
latitude between -90 and 90
longitude between -180 and 180
```

For Brazil-specific validation, unexpected points can also be reported for investigation, but do not build hard-coded geographical assumptions into the first pass unless they are documented.

---

# 39. Geolocation does NOT belong directly in the customer table

Do not do:

```text
customers.latitude
customers.longitude
```

as though these are exact properties of the customer.

Instead:

```text
customers.zip_code_prefix
        |
        v
geo_zip_prefix
        |
        +--> latitude
        +--> longitude
```

This preserves the data's actual level of precision.

---

# 40. Step 6 — Transformation categories

Every transformation should be labeled internally as one of:

```text
TYPE_CAST
STANDARDIZATION
RENAMING
DERIVATION
AGGREGATION
TRANSLATION
QUALITY_FILTER
RELATIONSHIP_VALIDATION
```

Example:

```text
product_name_lenght
→ product_name_length
```

is:

```text
RENAMING
```

Example:

```text
order_purchase_timestamp
→ purchase_at datetime
```

is:

```text
TYPE_CAST + RENAMING
```

Example:

```text
delivered_at - purchase_at
→ delivery_days
```

is:

```text
DERIVATION
```

Example:

```text
geolocation rows
→ one postal-prefix centroid
```

is:

```text
AGGREGATION
```

This creates lineage.

---

# 41. Step 7 — Do not create one giant joined dataframe

A common beginner mistake is:

```python
df = (
    orders
    .merge(customers)
    .merge(items)
    .merge(products)
    .merge(payments)
    .merge(reviews)
    .merge(sellers)
)
```

and then treating this as the "clean dataset".

Do NOT make this your core data model.

Why?

Because different tables have different grains.

Example:

```text
orders
1 row = 1 order

order_items
1 row = 1 item within an order

payments
1 row = 1 payment record

reviews
1 row = 1 review record
```

If you join them carelessly, one order can explode into many rows.

Example:

```text
1 order
× 3 items
× 2 payments
× 1 review
= 6 joined rows
```

That can silently double/triple counts.

Keep source entities separate.

---

# 42. Grain must be documented

Every table should have a declared grain.

Examples:

```text
customers
grain = one customer_id

orders
grain = one order_id

order_items
grain = one order_id + order_item_id

payments
grain = one order_id + payment_sequence

reviews
grain = one review_id

products
grain = one product_id

sellers
grain = one seller_id
```

This should be in `docs/data/data_dictionary.md`.

---

# 43. Step 8 — Referential-integrity tests

After technical cleaning, validate relationships.

Examples:

```python
missing_customer_refs = (
    set(orders["customer_id"])
    - set(customers["customer_id"])
)
```

Expected:

```text
empty set
```

Likewise:

```text
order_items.order_id → orders.order_id

order_items.product_id → products.product_id

order_items.seller_id → sellers.seller_id

payments.order_id → orders.order_id

reviews.order_id → orders.order_id
```

If an orphan exists:

```text
do not silently delete it
```

Write it to the rejected/quarantine dataset and produce a report.

---

# 44. Composite key validation

Some entities do not necessarily have one simple business identifier.

For order items:

```text
(order_id, order_item_id)
```

should be treated as the natural row grain.

Validation:

```python
duplicate_items = order_items.duplicated(
    subset=["order_id", "order_item_id"]
)
```

For payment records:

```text
(order_id, payment_sequence)
```

should be checked similarly.

---

# 45. Step 9 — Business validation

Technical integrity is not enough.

We also need business-quality checks.

Examples:

### Price checks

```text
price >= 0
freight_value >= 0
payment_value >= 0
```

### Review checks

```text
review_score ∈ {1,2,3,4,5}
```

### Date checks

```text
purchase_at <= approved_at
```

when both are present.

### Delivery checks

```text
delivered_to_customer_at >= purchase_at
```

when both exist.

### Physical measurements

```text
weight >= 0
dimensions >= 0
```

---

# 46. Do not over-constrain status logic

Order status is business state.

First profile the actual values.

For example:

```text
delivered
shipped
canceled
unavailable
...
```

Do not hard-code your own status list without comparing it to the source.

The validation layer should report:

```text
observed values
unexpected values
null values
```

rather than silently coercing unknown statuses.

---

# 47. Step 10 — Rejected records

Create:

```text
data/rejected/olist/
```

For each source table:

```text
orders_rejected.parquet
products_rejected.parquet
payments_rejected.parquet
...
```

Recommended columns added to rejected data:

```text
_etl_run_id
_source_table
_source_file
_source_row_number
_rejection_stage
_rejection_reason
```

Example:

```text
_etl_run_id
_source_table = orders
_source_file = olist_orders_dataset.csv
_source_row_number = 18273
_rejection_stage = referential_integrity
_rejection_reason = missing_customer_reference
```

Do not modify the original row contents.

---

# 48. One record can have multiple validation failures

Do not stop at the first problem.

Bad:

```python
if bad_customer:
    reject()
```

Better:

```text
reasons = []

if invalid_id:
    reasons.append("INVALID_ID")

if invalid_date:
    reasons.append("INVALID_DATE")

if missing_customer:
    reasons.append("MISSING_CUSTOMER_REFERENCE")
```

Then store:

```text
INVALID_DATE;MISSING_CUSTOMER_REFERENCE
```

This makes quality remediation much easier.

---

# 49. Step 11 — Staging output format

Use Parquet for staging and processed files.

Example:

```python
df.to_parquet(
    STAGING_DIR / "orders.parquet",
    index=False
)
```

Why Parquet?

- preserves columnar types better than CSV
- is efficient for analytical workloads
- supports compression
- is convenient for downstream data processing
- reduces repeated CSV parsing

The raw CSV remains the source-of-truth artifact.

The Parquet output is a generated artifact.

---

# 50. Staging output requirements

Every staging file should satisfy:

```text
correct columns
correct types
normalized IDs
normalized strings
parsed timestamps
no unexplained invalid values
known null semantics
```

But staging should still preserve the source table's grain.

---

# 51. Step 12 — Canonical/core layer

After staging passes validation, write canonical data into:

```text
data/processed/core/
```

Recommended datasets:

```text
customers.parquet
orders.parquet
order_items.parquet
payments.parquet
reviews.parquet
products.parquet
sellers.parquet
geo_zip_prefix.parquet
product_categories.parquet
```

This should be structurally aligned with the eventual PostgreSQL `core` schema.

---

# 52. Core layer philosophy

Core tables should contain:

```text
stable business entities
stable identifiers
source facts
carefully derived operational fields
```

Core should NOT contain:

```text
dashboard-specific formatting
presentation labels
ML model scores that can change frequently
frontend-specific fields
```

Keep it reusable.

---

# 53. Derived order fields

Good examples:

```text
purchase_date
purchase_year
purchase_month
purchase_day
purchase_hour
purchase_weekday
delivery_days
estimated_delivery_days
delivery_delay_days
is_late
```

These are derived deterministically from source timestamps.

Example:

```python
df["purchase_date"] = df["purchase_at"].dt.date

df["purchase_year"] = df["purchase_at"].dt.year

df["purchase_month"] = df["purchase_at"].dt.month

df["purchase_hour"] = df["purchase_at"].dt.hour

df["purchase_weekday"] = df["purchase_at"].dt.dayofweek
```

These fields should be reproducible.

---

# 54. Delivery metric definitions

This must be documented before analytics.

### Actual delivery duration

```text
delivery_days =
delivered_to_customer_at - purchase_at
```

only when the delivery timestamp exists.

### Expected delivery duration

```text
estimated_delivery_days =
estimated_delivery_at - purchase_at
```

### Delivery delay

```text
delivery_delay_days =
delivery_days - estimated_delivery_days
```

### Late flag

```text
is_late =
delivered_to_customer_at > estimated_delivery_at
```

Do not classify undelivered orders as "late" simply because there is no delivery date.

Undelivered and late-delivered are different states.

---

# 55. Step 13 — Analytics layer

Create:

```text
data/processed/analytics/
```

This layer contains data specifically designed for the business dashboards and models.

Recommended initial datasets:

```text
daily_sales
order_financial_summary
customer_metrics
seller_metrics
product_metrics
delivery_metrics
payment_metrics
review_metrics
```

---

# 56. Daily sales dataset

Grain:

```text
one row per calendar date
```

Potential fields:

```text
sales_date
orders_count
unique_customers
item_count
product_value
freight_value
gross_order_value
average_order_value
```

Definition:

```text
gross_order_value
=
sum(item price + freight value)
```

Do not call this profit.

---

# 57. Customer metrics

Grain:

```text
one row per customer_unique_id
```

Potential fields:

```text
customer_unique_id
order_count
item_count
total_spend
average_order_value
first_order_at
last_order_at
days_since_last_order
```

This becomes the foundation for RFM analysis.

---

# 58. RFM analysis

RFM:

```text
Recency
Frequency
Monetary
```

For each customer:

### Recency

```text
analysis_date - last_order_date
```

### Frequency

```text
number of orders
```

### Monetary

```text
sum of relevant order values
```

Important:

Define the analysis date explicitly.

For historical analysis:

```text
analysis_date = max relevant purchase timestamp
```

rather than using today's date.

This keeps the dataset temporally consistent.

---

# 59. Seller metrics

Grain:

```text
one row per seller_id
```

Potential fields:

```text
seller_id
orders_count
items_sold
gross_sales
average_item_price
average_freight
average_delivery_days
late_delivery_rate
average_review_score
```

The seller metrics need to be carefully calculated at the correct grain.

For example:

```text
seller review score
```

should not be calculated from duplicated rows created by a many-to-many style join.

Use pre-aggregated datasets first.

---

# 60. Product metrics

Grain:

```text
one row per product_id
```

Potential fields:

```text
product_id
category
items_sold
order_count
gross_item_value
average_price
average_review_score
average_delivery_days
```

Again, preserve the distinction between:

```text
number of items
number of orders
```

because one order can contain multiple items.

---

# 61. Review metrics

Potential analytics:

```text
average_score
review_count
one_star_rate
two_star_rate
five_star_rate
comment_rate
```

Later we can connect review scores to delivery outcomes.

For example:

```text
late_delivery
      |
      v
review_score
```

This should initially be presented as an association/correlation, not a claim of causality.

---

# 62. Delivery analytics

Create:

```text
analytics.delivery_metrics
```

Potential fields:

```text
date
orders_delivered
average_delivery_days
median_delivery_days
p90_delivery_days
late_orders
late_delivery_rate
```

Percentiles are useful because averages can be distorted by extreme cases.

For example:

```text
median delivery = 8 days
p90 delivery = 19 days
```

is more informative than only:

```text
average = 10.4
```

---

# 63. Step 14 — Validation report

The pipeline must generate a report after every run.

Recommended files:

```text
reports/data_quality/
├── latest_report.json
├── latest_report.md
├── source_manifest.json
└── runs/
    └── <run_id>.json
```

The report should contain:

```text
pipeline run
source hashes
row counts
null statistics
duplicate statistics
validation results
referential-integrity results
rejection counts
accepted counts
transformation counts
warnings
errors
duration
```

---

# 64. Quality gates

The pipeline should not continue when critical checks fail.

Define levels:

```text
CRITICAL
ERROR
WARNING
INFO
```

Examples:

### CRITICAL

```text
required source file missing
orders has duplicate primary key
customer foreign-key integrity catastrophically broken
required identifier entirely missing
```

### ERROR

```text
invalid numeric values
invalid dates
unexpected lifecycle values
```

### WARNING

```text
missing optional review comment
missing optional product dimension
translation unavailable
```

### INFO

```text
number of unique cities
number of categories
number of payment types
```

---

# 65. Example quality report structure

```json
{
  "run_id": "2026-10-04T12:30:00Z",
  "status": "SUCCESS_WITH_WARNINGS",

  "tables": {
    "orders": {
      "source_rows": 0,
      "accepted_rows": 0,
      "rejected_rows": 0,
      "null_issues": {},
      "duplicate_issues": {},
      "relationship_issues": {}
    }
  },

  "quality_gates": {
    "source_files": "PASS",
    "primary_keys": "PASS",
    "foreign_keys": "PASS",
    "value_ranges": "PASS",
    "date_integrity": "PASS"
  }
}
```

The zeroes above are placeholders only. Your implementation must populate them from the actual files.

---

# 66. Step 15 — ETL idempotency

Running:

```bash
python -m src.etl.pipeline
```

twice against the same raw files should produce the same logical output.

This is called idempotency/reproducibility.

Do NOT:

```text
append to existing processed data
```

unless the pipeline has intentionally entered an incremental mode.

For the first historical-load version:

```text
delete/recreate generated staging
delete/recreate generated core
delete/recreate analytics
generate fresh report
```

or write each run to an isolated run directory and promote the successful output.

---

# 67. Recommended run IDs

Every ETL execution receives:

```text
run_id
```

Example:

```text
20261004_123000
```

Generated artifacts can be associated with the run.

For example:

```text
reports/data_quality/runs/20261004_123000.json
```

This will become very useful later when Celery performs scheduled ingestion.

---

# 68. Step 16 — Logging

The pipeline should log:

```text
INFO
WARNING
ERROR
```

Example:

```text
2026-10-04 12:30:01 INFO Source validation started
2026-10-04 12:30:02 INFO Found 9/9 expected files
2026-10-04 12:30:03 INFO Loading orders
2026-10-04 12:30:04 INFO Orders loaded
2026-10-04 12:30:04 INFO Orders transformation completed
2026-10-04 12:30:05 WARNING 14 records contain missing delivery timestamps
2026-10-04 12:30:06 INFO Referential integrity passed
```

Later, these logs can be surfaced by the OpsPulse system-health dashboard.

---

# 69. Step 17 — ETL tests

Create unit tests before considering the pipeline complete.

Example:

```python
def test_customer_ids_are_strings():
    result = clean_customers(sample_customers)

    assert str(result["customer_id"].dtype) in {
        "string",
        "string[python]",
        "string[pyarrow]",
    }
```

Example:

```python
def test_negative_price_is_rejected():
    ...
```

Example:

```python
def test_order_customer_relationship():
    ...
```

Example:

```python
def test_delivery_delay_calculation():
    ...
```

---

# 70. Test transformations with tiny fixtures

Do not run the full 100k-order dataset for every unit test.

Create miniature fixtures:

```text
tests/fixtures/
├── customers.csv
├── orders.csv
├── order_items.csv
└── payments.csv
```

Example order fixture:

```text
order_id = ORDER-1
customer_id = CUSTOMER-1
purchase_at = 2020-01-01
estimated = 2020-01-05
delivered = 2020-01-04
```

Expected:

```text
is_late = false
delivery_delay_days = -1
```

This makes tests fast.

---

# 71. Step 18 — Data lineage

Each derived field should have a known parent.

Create a lineage table in the documentation:

| Derived field | Source fields | Transformation |
|---|---|---|
| `item_total` | `price`, `freight_value` | sum |
| `delivery_days` | `purchase_at`, `delivered_to_customer_at` | datetime difference |
| `estimated_delivery_days` | `purchase_at`, `estimated_delivery_at` | datetime difference |
| `delivery_delay_days` | `delivery_days`, `estimated_delivery_days` | subtraction |
| `is_late` | `delivered_to_customer_at`, `estimated_delivery_at` | comparison |
| `purchase_month` | `purchase_at` | date extraction |
| `total_spend` | order/item totals | customer aggregation |
| `late_delivery_rate` | `is_late` | seller aggregation |

This makes every dashboard metric explainable.

---

# 72. Step 19 — Analytics definitions before dashboard development

Before creating a chart, define:

```text
metric name
business definition
grain
source table(s)
filters
formula
known limitations
```

Example:

```text
Metric:
Late Delivery Rate

Definition:
Percentage of delivered orders whose actual
customer-delivery timestamp occurs after the
estimated delivery timestamp.

Numerator:
count(delivered orders where is_late = true)

Denominator:
count(delivered orders)

Important:
orders without actual delivery timestamps
are excluded from this metric.
```

This avoids dashboard numbers changing depending on how a query was written.

---

# 73. Important distinction: source date vs business date

OpsPulse will eventually have many time dimensions:

```text
purchase date
approval date
shipping date
delivery date
review date
```

Do not call all of these simply:

```text
date
```

Use explicit names.

This prevents subtle analytics bugs.

---

# 74. Step 20 — Do not use current date for historical customer metrics

Suppose the last purchase in Olist is in 2018.

If you calculate:

```text
recency = today - last_purchase
```

then every customer appears extremely inactive.

That is not useful for historical behavioral analysis.

Instead:

```text
analysis_date =
maximum relevant purchase timestamp in dataset
```

or use a documented cutoff date for a train/test split.

---

# 75. Time-based ML preparation

Later, when we build the delivery-risk model:

```text
features:
information available before delivery
```

must not accidentally include information from after delivery.

For example, these should NOT be used as pre-delivery predictive features:

```text
actual delivery duration
review score
review creation date after delivery
```

Those are leakage.

Possible legitimate pre-delivery features include:

```text
seller location
customer location
product dimensions
product weight
freight value
purchase date/time
shipping_limit_date
product category
item count
```

This is critical if we want the ML portion to be credible.

---

# 76. Anomaly detection data design

Anomaly detection should consume the **canonical/analytical layer**, not raw CSV text.

We will eventually build:

```text
analytics.anomaly_features
```

Possible fields:

```text
transaction/order identifier
order_value
payment_value
freight_value
item_count
customer_order_count
customer_avg_order_value
seller_order_count
seller_avg_order_value
delivery_days
delivery_delay_days
hour_of_day
weekday
```

These features are derived from real observed records.

---

# 77. Hybrid anomaly approach

OpsPulse should NOT rely solely on ML.

Use:

```text
                 Anomaly Engine
                     |
            +--------+--------+
            |                 |
      Business Rules      ML Model
            |                 |
            |           Isolation Forest
            |                 |
            +--------+--------+
                     |
                     v
                 anomaly record
```

Why?

Business rules are:

```text
explainable
auditable
domain-specific
```

ML is:

```text
pattern-based
less dependent on manually defined thresholds
```

Using both is stronger.

Scikit-learn documents Isolation Forest as an outlier-detection method based on how easily observations can be isolated.  
Source: https://scikit-learn.org/stable/auto_examples/ensemble/plot_isolation_forest.html

---

# 78. Business-rule anomaly examples

### High transaction deviation

```text
current order value
versus
customer historical average
```

### Payment mismatch

```text
payment total
versus
order value
```

### Delivery anomaly

```text
actual delivery time
versus
normal delivery distribution
```

### Duplicate invoice/order behavior

```text
same reference
same payment
same amount
```

These are deterministic rules and should include explicit reasons.

---

# 79. ML anomaly example

Use Isolation Forest after feature engineering.

Feature matrix:

```text
order_value
freight_value
item_count
customer_frequency
customer_avg_value
seller_frequency
seller_avg_value
delivery_days
hour
weekday
```

The model produces:

```text
anomaly_score
prediction
```

The application should store:

```text
anomaly_id
entity_type
entity_id
model
score
severity
reason
detected_at
status
```

Do not display a raw ML score to the user without a useful interpretation.

---

# 80. Severity is an application-level interpretation

For example:

```text
Isolation Forest score
        |
        v
severity classification
```

Do not imply that:

```text
score = probability of fraud
```

unless the model was actually trained/calibrated to estimate that probability.

For OpsPulse:

```text
LOW
MEDIUM
HIGH
CRITICAL
```

should represent the platform's documented operational severity policy.

---

# 81. Controlled synthetic data is allowed — but only for the right purpose

After the real historical pipeline works, synthetic data can be introduced for:

```text
test users
load testing
API rate-limit testing
failure simulation
future-date demo scenarios
controlled anomaly evaluation
```

It should not replace:

```text
customers
orders
payments
products
sellers
reviews
```

The README should explicitly disclose synthetic components.

---

# 82. External API strategy after ETL

The Olist CSV dataset is not itself an external API.

Do not claim:

> "OpsPulse consumes the Olist API."

Instead:

```text
Olist dataset
      |
      v
our External Data Provider service
      |
      | REST API
      v
OpsPulse ingestion client
```

The External Data Provider is a deliberate simulation of a third-party commerce data provider.

Its underlying records originate from the real Olist dataset.

Document this clearly.

---

# 83. External API data flow

Eventually:

```text
Olist raw
   |
   v
canonical database
   |
   v
External Data Provider API
   |
   +-- GET /orders
   +-- GET /customers
   +-- GET /products
   +-- GET /payments
   +-- GET /reviews
   |
   v
OpsPulse ingestion service
   |
   v
OpsPulse PostgreSQL
```

This creates a realistic separation between:

```text
third-party source
```

and:

```text
internal application database
```

---

# 84. Why not directly expose the original CSV files as the API?

Because we want to demonstrate actual backend integration.

The API should support:

```text
pagination
date filtering
status filtering
sorting
authentication
rate limits
HTTP error responses
```

For example:

```http
GET /api/v1/orders?page=1&page_size=100
```

or:

```http
GET /api/v1/orders?from=2017-05-01&to=2017-05-31
```

That gives the ingestion service a real contract to consume.

---

# 85. External API fault simulation

Use synthetic failures only at the infrastructure boundary.

Possible controlled responses:

```text
200 OK
429 Too Many Requests
500 Internal Server Error
503 Service Unavailable
timeout
```

Then OpsPulse can demonstrate:

```text
retry
backoff
logging
failed-sync recording
recovery
```

This is much more credible than inventing fake transaction records.

---

# 86. Data replay

Because the source is historical, we can create a replay mechanism.

Example:

```text
2017-01-01 data
2017-01-02 data
2017-01-03 data
...
2018-XX-XX data
```

The replay service exposes historical records in chronological batches.

OpsPulse can therefore behave like a system receiving live data without inventing a fake business history.

Conceptually:

```text
historical records
      |
      v
replay clock
      |
      v
external provider
      |
      v
OpsPulse ingestion
```

This will later make the synchronization dashboard much more impressive.

---

# 87. Important replay rule

The replay clock must be clearly identified as:

```text
SIMULATED EVENT TIME
```

It should not be confused with:

```text
real-world current events.
```

The source events remain historical observations.

---

# 88. PostgreSQL boundary

PostgreSQL should be introduced only after:

```text
raw
profiling
staging
validation
core
```

are reproducible locally.

At that point, PostgreSQL receives well-defined canonical data.

Recommended schemas:

```text
core
analytics
```

Optionally:

```text
staging
```

inside PostgreSQL as well.

A first implementation can keep raw source files on disk and use PostgreSQL for staging/core/analytics.

PostgreSQL provides `COPY` for bulk file loading and supports CSV input.  
Official documentation: https://www.postgresql.org/docs/current/sql-copy.html

---

# 89. Recommended PostgreSQL core tables

```text
core.customers
core.orders
core.order_items
core.payments
core.reviews
core.products
core.sellers
core.geo_zip_prefix
core.product_categories
```

Recommended analytical tables/views:

```text
analytics.daily_sales
analytics.order_financial_summary
analytics.customer_metrics
analytics.seller_metrics
analytics.product_metrics
analytics.delivery_metrics
analytics.payment_metrics
analytics.review_metrics
```

The exact SQL schema should be written after the cleaned Parquet outputs are verified.

---

# 90. Suggested core relational model

```text
core.customers
---------------------------
customer_id PK
customer_unique_id
zip_code_prefix
city
state


core.orders
---------------------------
order_id PK
customer_id FK
order_status
purchase_at
approved_at
delivered_to_carrier_at
delivered_to_customer_at
estimated_delivery_at


core.order_items
---------------------------
order_id FK
order_item_id
product_id FK
seller_id FK
shipping_limit_at
price
freight_value

PK(order_id, order_item_id)


core.payments
---------------------------
order_id FK
payment_sequence
payment_type
payment_installments
payment_value

PK(order_id, payment_sequence)


core.products
---------------------------
product_id PK
category_name
category_name_english
name_length
description_length
photos_qty
weight_g
length_cm
height_cm
width_cm


core.sellers
---------------------------
seller_id PK
zip_code_prefix
city
state


core.reviews
---------------------------
review_id
order_id FK
review_score
review_title
review_message
created_at
answered_at
```

The actual schema must be reconciled with the characteristics of the downloaded files before finalizing constraints.

---

# 91. Exact ETL pipeline

The final pipeline should be conceptually:

```text
pipeline()
|
+-- generate_run_id()
|
+-- verify_source_files()
|
+-- fingerprint_source_files()
|
+-- extract()
|
+-- profile_raw()
|
+-- transform_to_staging()
|
+-- validate_staging()
|
+-- write_rejected_records()
|
+-- validate_relationships()
|
+-- build_core()
|
+-- build_analytics()
|
+-- run_final_quality_checks()
|
+-- write_quality_report()
|
+-- write_lineage_report()
|
+-- complete_pipeline()
```

---

# 92. Exact execution order

The safest order is:

```text
1. Source validation
2. Source fingerprinting
3. Raw extraction
4. Raw profiling
5. Transformation
6. Staging output
7. Staging validation
8. Referential integrity
9. Rejected-record output
10. Core dataset generation
11. Core validation
12. Analytics dataset generation
13. Analytics validation
14. Quality report
15. Run manifest
```

If a critical step fails:

```text
STOP
```

Do not create a supposedly successful downstream dataset.

---

# 93. Pipeline pseudocode

```python
def run_pipeline():

    run_id = create_run_id()

    verify_source_files()

    manifest = fingerprint_source_files()

    raw = extract_all()

    raw_profile = profile_all(raw)
    save_raw_profile(raw_profile)

    staging = transform_all(raw)

    staging_results = validate_all(staging)

    write_rejected_records(
        staging_results,
        run_id=run_id
    )

    if staging_results.has_critical_errors:
        fail_pipeline()

    relationship_results = validate_relationships(staging)

    if relationship_results.has_critical_errors:
        fail_pipeline()

    core = build_core(staging)

    validate_core(core)

    analytics = build_analytics(core)

    validate_analytics(analytics)

    report = create_quality_report(
        run_id=run_id,
        manifest=manifest,
        raw_profile=raw_profile,
        validation_results=staging_results,
        relationship_results=relationship_results
    )

    save_report(report)

    mark_success(run_id)
```

---

# 94. Step 23 — The pipeline's final console output

Aim for something like:

```text
==================================================
                 OPSPULSE ETL
==================================================

Run ID:
20261004_123000

[1/14] Checking source files............ PASS
[2/14] Fingerprinting sources.......... PASS
[3/14] Extracting...................... PASS
[4/14] Profiling....................... PASS
[5/14] Transforming.................... PASS
[6/14] Staging validation.............. PASS
[7/14] Referential integrity........... PASS
[8/14] Rejected-record handling........ PASS
[9/14] Building core datasets.......... PASS
[10/14] Core validation................ PASS
[11/14] Building analytics............. PASS
[12/14] Analytics validation........... PASS
[13/14] Writing quality report......... PASS
[14/14] Writing lineage manifest....... PASS

--------------------------------------------------
RESULT
--------------------------------------------------

Status: SUCCESS

Source rows processed: <calculated>
Accepted rows:         <calculated>
Rejected rows:         <calculated>

Critical errors: 0
Warnings:         <calculated>

Output:
data/staging/
data/processed/core/
data/processed/analytics/
reports/data_quality/

==================================================
```

Do not hard-code these numbers.

---

# 95. Data quality checks to implement

Minimum checks:

## File checks

```text
all expected files exist
file readable
header exists
required columns exist
```

## Schema checks

```text
expected columns
unexpected columns reported
column names standardized
```

## Null checks

```text
required identifiers non-null
optional fields allowed to be null
```

## Duplicate checks

```text
primary key uniqueness
composite key uniqueness
duplicate source rows
```

## Range checks

```text
price >= 0
freight >= 0
payment >= 0
review 1–5
coordinates valid
```

## Date checks

```text
timestamps parse
lifecycle ordering
expected temporal range
```

## Referential checks

```text
customers
orders
items
payments
reviews
products
sellers
```

## Business consistency

```text
item total
payment reconciliation
delivery status consistency
```

---

# 96. Data-quality severity example

```text
CHECK                                  SEVERITY

Missing source file                   CRITICAL
Missing primary ID                    CRITICAL
Duplicate primary key                 CRITICAL
Missing FK reference                  ERROR
Invalid date                          ERROR
Negative payment                      ERROR
Review score outside 1–5              ERROR
Missing optional review message       WARNING
Missing category translation          WARNING
Missing optional product dimensions   WARNING
```

The final policy can be adjusted after profiling the actual source.

---

# 97. What should happen if quality checks discover issues?

There are four possible outcomes:

```text
PASS
```

Data is acceptable.

```text
PASS WITH WARNING
```

Data is usable but has documented limitations.

```text
REJECT RECORD
```

Specific rows are invalid and quarantined, while valid rows continue.

```text
FAIL PIPELINE
```

A critical structural problem prevents trustworthy output.

This is much better than:

```text
try:
    ...
except:
    pass
```

Never hide ETL failures.

---

# 98. Do not silently use `errors="ignore"`

Avoid:

```python
pd.to_datetime(..., errors="ignore")
```

If a timestamp cannot be parsed, either:

```text
parse successfully
```

or:

```text
mark invalid and report
```

Pandas explicitly supports `errors="raise"` and `errors="coerce"` for datetime parsing.  
Source: https://pandas.pydata.org/docs/reference/api/pandas.to_datetime.html

For ETL, `coerce` can be appropriate when paired with explicit invalid-count checks.

---

# 99. Do not silently use generic `fillna`

Avoid indiscriminate:

```python
df.fillna(0)
```

This is dangerous.

Example:

```text
missing delivery date
```

does not mean:

```text
delivery date = 0
```

Instead, each nullable field needs a semantic decision.

---

# 100. What "cleaned data" means for OpsPulse

Cleaned does NOT mean:

```text
zero nulls
zero duplicates
zero unusual records
```

Cleaned means:

```text
known structure
known types
known null semantics
known identifiers
known invalid records
known relationships
known transformations
known limitations
```

This is a much more mature definition.

---

# 101. Source vs staging vs core vs analytics

Use this mental model throughout development.

| Layer | Purpose | Modification allowed? |
|---|---|---|
| Raw | exact source | No |
| Staging | technical normalization | Yes |
| Core | canonical business model | Yes, deterministic |
| Analytics | derived business metrics | Yes |
| ML features | model-specific features | Yes |
| Dashboard | presentation | Yes |

Do not mix responsibilities.

---

# 102. Data lineage example

Example:

```text
Olist:
price
    |
    +----------------------+
                           |
Olist:
freight_value             |
    |                     |
    +-----------> item_total
                           |
                           v
                     order_total
                           |
                           v
                   daily_sales
```

For delivery:

```text
purchase_timestamp
          |
          +--------------------+
                               |
delivered_customer_date       |
          |                   |
          +---------> delivery_days
                               |
estimated_delivery_date        |
          |                   |
          +---------> delivery_delay_days
                               |
                               v
                         is_late
```

For customer:

```text
customer_unique_id
        |
        +--> order_count
        +--> total_spend
        +--> average_order_value
        +--> first_order
        +--> last_order
        +--> recency
```

This is the lineage story you should later explain in an interview.

---

# 103. A critical issue: order value vs payment value

Never casually equate:

```text
order value
```

with:

```text
payment value
```

Compute them separately.

Possible order value:

```text
sum(order_items.price)
+
sum(order_items.freight_value)
```

Payment value:

```text
sum(order_payments.payment_value)
```

Then compare them.

This creates a useful business-reconciliation capability.

---

# 104. A critical issue: order count vs item count

Never use:

```sql
COUNT(order_items.order_id)
```

when you mean:

```text
number of orders
```

Use:

```text
COUNT(DISTINCT order_id)
```

where appropriate.

Similarly:

```text
item count
```

is a different metric.

OpsPulse should document these grains everywhere.

---

# 105. A critical issue: reviews and duplicated joins

Suppose:

```text
order
1
```

has:

```text
3 items
2 payment records
1 review
```

A naïve multi-join can create:

```text
3 × 2 × 1 = 6 rows
```

Then:

```text
SUM(payment_value)
```

could become six times too large.

The correct architecture is:

```text
pre-aggregate payment data
pre-aggregate review data
pre-aggregate item data
then join at the desired grain
```

This is a core data-engineering lesson.

---

# 106. Recommended aggregation pattern

Instead of:

```python
orders
.merge(items)
.merge(payments)
.merge(reviews)
```

build:

```text
items_by_order
payments_by_order
reviews_by_order
```

then:

```text
orders
 + items_by_order
 + payments_by_order
 + reviews_by_order
```

This preserves one-row-per-order grain.

---

# 107. The first analytical model should be intentionally simple

Do not build dozens of dashboard tables immediately.

Start with:

```text
daily_sales
order_financial_summary
customer_metrics
seller_metrics
delivery_metrics
```

Then build new datasets only when a dashboard requirement justifies them.

This prevents unnecessary transformation complexity.

---

# 108. Data processing checklist

Before PostgreSQL:

```text
[ ] All nine raw files stored
[ ] Raw files unchanged
[ ] Source checksums generated
[ ] File inventory generated
[ ] Raw schema captured
[ ] Data dictionary written
[ ] Raw profile generated
[ ] Null distributions inspected
[ ] Duplicate distributions inspected
[ ] Date ranges inspected
[ ] Categorical values inspected
[ ] Encoding issues resolved
[ ] IDs normalized
[ ] Numeric fields typed
[ ] Dates parsed
[ ] Text normalized
[ ] Product field names normalized
[ ] Category translation handled
[ ] Geolocation aggregated
[ ] Business derivations defined
[ ] Referential-integrity rules implemented
[ ] Rejected records separated
[ ] Staging Parquet generated
[ ] Core Parquet generated
[ ] Analytics Parquet generated
[ ] Automated quality report generated
[ ] ETL tests passing
[ ] Pipeline reproducible
```

---

# 109. PostgreSQL readiness gate

Do not move to PostgreSQL until this statement is true:

> **A clean machine can receive the repository, place the original Olist files into `data/raw/olist/`, install dependencies, run one ETL command, and reproduce the staging/core/analytics datasets and quality reports without manually editing data.**

That is the definition of "data phase complete."

---

# 110. What comes after this

Once the data foundation passes the readiness gate:

```text
PHASE 1
Data Foundation
        |
        v
PHASE 2
PostgreSQL
        |
        v
PHASE 3
External Data Provider API
        |
        v
PHASE 4
OpsPulse Ingestion Client
        |
        v
PHASE 5
Celery + Redis synchronization
        |
        v
PHASE 6
Analytics API
        |
        v
PHASE 7
Anomaly Detection
        |
        v
PHASE 8
Next.js Dashboard
        |
        v
PHASE 9
Testing
        |
        v
PHASE 10
Docker
        |
        v
PHASE 11
CI/CD
        |
        v
PHASE 12
Deployment
        |
        v
PHASE 13
Monitoring
```

---

# 111. What NOT to build yet

Until the data foundation is complete, do not spend implementation time on:

```text
Next.js components
Recharts
dashboard animations
JWT
OAuth
Celery
Redis
Isolation Forest
Docker deployment
Nginx
cloud hosting
```

Those all depend on a stable data contract.

---

# 112. Immediate implementation sequence

The next coding session should contain exactly these tasks.

## Task A — Create directories

```bash
mkdir -p data/raw/olist
mkdir -p data/staging/olist
mkdir -p data/processed/core
mkdir -p data/processed/analytics
mkdir -p data/rejected/olist
mkdir -p reports/data_quality
mkdir -p src/etl
mkdir -p tests/etl
mkdir -p tests/fixtures
mkdir -p docs/data
```

On Windows PowerShell, create the directories using:

```powershell
New-Item -ItemType Directory -Force data/raw/olist
New-Item -ItemType Directory -Force data/staging/olist
New-Item -ItemType Directory -Force data/processed/core
New-Item -ItemType Directory -Force data/processed/analytics
New-Item -ItemType Directory -Force data/rejected/olist
New-Item -ItemType Directory -Force reports/data_quality
New-Item -ItemType Directory -Force src/etl
New-Item -ItemType Directory -Force tests/etl
New-Item -ItemType Directory -Force tests/fixtures
New-Item -ItemType Directory -Force docs/data
```

---

# 113. Task B — Put the downloaded CSVs in exactly one place

Place the nine downloaded files under:

```text
data/raw/olist/
```

Do not rename them yet.

Expected:

```text
data/raw/olist/
├── olist_customers_dataset.csv
├── olist_geolocation_dataset.csv
├── olist_order_items_dataset.csv
├── olist_order_payments_dataset.csv
├── olist_order_reviews_dataset.csv
├── olist_orders_dataset.csv
├── olist_products_dataset.csv
├── olist_sellers_dataset.csv
└── product_category_name_translation.csv
```

---

# 114. Task C — Implement source verification

Write:

```text
src/etl/config.py
src/etl/extract.py
```

The first command should only answer:

```text
Are all expected files present?
Can they be opened?
What are their actual columns?
How many rows do they contain?
```

No transformation yet.

---

# 115. Task D — Generate raw profiling

Create:

```text
src/etl/profile.py
```

Output:

```text
reports/data_quality/raw_profile.json
reports/data_quality/raw_profile.md
```

Profile every source file.

Do not manually inspect the files one by one in Excel as the primary process.

The code must produce the profile.

---

# 116. Task E — Review the actual profile

Only after the profile exists should we decide:

```text
encoding
null handling
duplicate handling
data types
date conversion
range validation
relationship validation
```

This is important because:

> The source profile, not our assumptions, should drive the cleaning rules.

---

# 117. Task F — Freeze the data contract

After profiling, update:

```text
docs/data/data_dictionary.md
```

with the exact facts observed in your downloaded copy.

Do not use internet-derived row counts as your authoritative counts.

The internet establishes provenance and dataset meaning.

Your local files establish:

```text
actual row counts
actual nulls
actual duplicates
actual parsing behavior
```

---

# 118. Task G — Implement transformations

Create:

```text
src/etl/transform.py
```

with functions such as:

```python
clean_customers()
clean_orders()
clean_order_items()
clean_payments()
clean_reviews()
clean_products()
clean_sellers()
clean_geolocation()
clean_category_translation()
```

Each function should:

```text
input = DataFrame
output = DataFrame
```

It should not secretly write files.

Writing belongs in the pipeline/orchestration layer.

---

# 119. Task H — Implement validation independently

Create:

```text
src/etl/validate.py
```

Validation must be callable independently from transformation.

For example:

```python
orders = clean_orders(raw_orders)

result = validate_orders(orders)
```

This separation makes testing easier.

---

# 120. Task I — Build rejected-record handling

Create:

```text
src/etl/utils.py
```

or:

```text
src/etl/lineage.py
```

to capture:

```text
run_id
source
row
reason
stage
```

Do not simply print rejected rows.

Save them.

---

# 121. Task J — Build staging Parquet

Once transformation and validation work:

```text
data/staging/olist/*.parquet
```

should be generated automatically.

No manual exports.

---

# 122. Task K — Build core datasets

Create:

```text
src/etl/analytics.py
```

or split it into:

```text
src/etl/core.py
src/etl/analytics.py
```

Recommended if the project becomes larger.

Start with:

```text
core
customers
orders
order_items
payments
reviews
products
sellers
geo_zip_prefix
product_categories
```

Then:

```text
analytics
daily_sales
order_financial_summary
customer_metrics
seller_metrics
delivery_metrics
```

---

# 123. Task L — Generate final report

The pipeline must write:

```text
reports/data_quality/latest_report.md
reports/data_quality/latest_report.json
```

and preserve historical reports:

```text
reports/data_quality/runs/<run_id>.json
```

---

# 124. Completion criteria

Data Phase 1 is complete only when:

```text
RAW SOURCE
     |
     v
PROFILE
     |
     v
TRANSFORM
     |
     v
VALIDATE
     |
     v
REJECT INVALID
     |
     v
CORE
     |
     v
ANALYTICS
```

can be run without manual intervention.

And:

```text
python -m src.etl.pipeline
```

returns success.

---

# 125. What the final output should represent

At the end of this phase, you will have:

```text
REAL SOURCE DATA
        +
REPRODUCIBLE ETL
        +
DATA QUALITY
        +
RELATIONAL MODEL
        +
DERIVED BUSINESS METRICS
```

That becomes the actual foundation of OpsPulse.

It is not:

```text
random Faker data
+
pretty charts
```

It is:

```text
real anonymized commercial observations
+
professional data engineering
+
analytical modeling
```

---

# 126. Why this matters for your portfolio

The project should eventually let you say:

> I designed a reproducible ETL pipeline around a real anonymized e-commerce transaction dataset rather than synthetic business records. I preserved an immutable raw layer, profiled the source, standardized schemas and data types, implemented quality and referential-integrity validation, quarantined invalid records, produced canonical relational datasets and built analytical marts for operational reporting.

That sentence demonstrates much more than:

> "Used Pandas to clean a Kaggle dataset."

---

# 127. Expected final data journey

The complete eventual architecture is:

```text
                  REAL OLIST SOURCE
                         |
                  immutable raw CSV
                         |
                         v
                  Python ETL layer
                         |
          +--------------+--------------+
          |              |              |
       profile        transform      lineage
          |              |              |
          +--------------+--------------+
                         |
                         v
                      STAGING
                         |
                         v
                   QUALITY GATES
                         |
              +----------+----------+
              |                     |
          accepted               rejected
              |                     |
              v                     v
             CORE              quarantine
              |
              v
          ANALYTICS
              |
              v
          PostgreSQL
              |
              v
     External Provider API
              |
              v
      OpsPulse Ingestion
              |
        +-----+-----+
        |           |
      Redis       Celery
        |           |
        +-----+-----+
              |
              v
           FastAPI
              |
              v
           Next.js
              |
       +------+------+----------------+
       |             |                |
   Executive     Operations      Anomaly Center
   Dashboard     Dashboard          |
                                ML + Rules
```

---

# 128. Source and documentation references

### Olist dataset — primary source

Brazilian E-Commerce Public Dataset by Olist:

https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce

The source describes the dataset as real, anonymized commercial data with approximately 100,000 orders and multiple related dimensions.

### Olist metadata

https://www.kaggle.com/olistbr/brazilian-ecommerce/metadata

Use this for source-column meanings and relationship information. In particular, it documents the distinction between `customer_id` and `customer_unique_id`.

### Pandas CSV loading

https://pandas.pydata.org/docs/reference/api/pandas.read_csv.html

### Pandas datetime conversion

https://pandas.pydata.org/docs/reference/api/pandas.to_datetime.html

### PostgreSQL bulk loading

https://www.postgresql.org/docs/current/sql-copy.html

### Scikit-learn Isolation Forest

https://scikit-learn.org/stable/auto_examples/ensemble/plot_isolation_forest.html

### Additional dataset analysis reference

https://www.kaggle.com/writeups/shivamtamboli62/olist-ecommerce-analytics

This is useful as a troubleshooting/reference source, but it is **not** the authority for the contents of your downloaded files. Your local source files are the authority for actual row counts, nulls, duplicates and parsing behavior.

---

# 129. Final handover instruction

At the current stage, the correct implementation order is:

```text
DO NOT START POSTGRESQL YET.

FIRST:

1. Verify all 9 raw CSV files.
2. Fingerprint them.
3. Profile them programmatically.
4. Create the data dictionary.
5. Inspect actual nulls/duplicates/encodings.
6. Define transformation contracts.
7. Implement staging transformations.
8. Implement validation.
9. Implement referential-integrity checks.
10. Implement rejected-record handling.
11. Generate staging Parquet.
12. Generate canonical/core Parquet.
13. Generate analytics Parquet.
14. Generate the data-quality report.
15. Add automated ETL tests.
16. Run the pipeline from a clean environment.
17. Confirm reproducibility.
18. ONLY THEN design the PostgreSQL schema/load.
```

The next concrete artifact after this handover should therefore be the **actual Raw Data Inventory + Profiling implementation**, using the exact nine files currently present in your local `data/raw/olist/` directory.

Once that inventory exists, every subsequent cleaning rule should be based on what the files actually contain—not on assumptions, a tutorial, a Kaggle notebook, or generated fake data.

