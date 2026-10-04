# OpsPulse

Business operations intelligence platform built on the real, anonymised
[Olist Brazilian E-Commerce dataset](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce)
(~100k orders, 2016–2018). It covers a reproducible ETL with quality gates, a simulated
third-party provider API, a resilient ingestion pipeline, an analytics API, anomaly detection
and a dashboard.

**Status:** Phase 1 (data foundation) is complete. One command turns the nine raw CSVs into
validated staging, core and analytics datasets plus a quality report, locally or in Docker.
See [docs/ROADMAP.md](docs/ROADMAP.md) for the plan and the free-tier deployment.

## Quickstart

Put the nine Kaggle CSVs, unmodified, in `data/raw/olist/`. With the
[Kaggle CLI](https://github.com/Kaggle/kaggle-api) and an API token:

```bash
kaggle datasets download -d olistbr/brazilian-ecommerce -p data/raw/olist --unzip
```

### With Docker (nothing else to install)

```bash
docker compose run --rm etl                          # full pipeline
docker compose run --rm etl opspulse-etl verify      # just check the source files
```

### With Python 3.12+ and [uv](https://docs.astral.sh/uv/)

```bash
uv sync --all-extras          # creates .venv from uv.lock (no uv yet? pip install uv)
uv run opspulse-etl run       # full pipeline, ~50 s
uv run pytest                 # 25 tests on tiny fixtures; no raw data needed
uv run ruff check . && uv run ruff format --check .
```

| Command | What it does |
|---|---|
| `opspulse-etl verify` | Files present and readable, columns match the contract, row counts |
| `opspulse-etl profile` | SHA-256 manifest + raw profile → `reports/data_quality/raw_profile.md` |
| `opspulse-etl run` | verify → fingerprint → profile → stage → validate → quarantine → core → analytics → report |
| `opspulse-etl dictionary` | Regenerates [docs/data/data_dictionary.md](docs/data/data_dictionary.md) from the code |

## What a run produces

```text
data/staging/olist/*.parquet          typed, renamed, source grain (+ _source_row_number)
data/processed/core/*.parquet         canonical model + derived fields (delivery, lateness, ...)
data/processed/analytics/*.parquet    order_financial_summary, daily_sales
data/processed/quality/warnings.parquet  every WARNING, per record
data/rejected/olist/*.parquet         rejected rows: raw text untouched + run, file, row, reasons
reports/data_quality/latest_report.md gates, counts, every issue code with its meaning
```

Outputs are written to a scratch directory and promoted only if every check passes, so a
failed run never replaces good data. Re-running replaces outputs instead of appending.

## Local infrastructure

```bash
docker compose up -d postgres             # Postgres 17, schemas provider + ops
docker compose --profile tools up -d      # + Adminer at http://localhost:8080
docker compose --profile worker up -d     # + Redis (sync broker, Phase 4)
```

Ports bind to `127.0.0.1` only. Copy `.env.example` to `.env` to change credentials.

## Layout

```text
src/opspulse/etl/       config · schema (staging contract) · extract · profile · transform
                        validate (rules) · quarantine · core · analytics · report · pipeline · cli
tests/                  unit + end-to-end tests over tests/fixtures/olist
docs/                   ROADMAP.md, data/data_dictionary.md (generated)
reports/data_quality/   committed quality reports
infra/postgres/init/    database bootstrap SQL
Dockerfile, compose.yaml, .github/workflows/ci.yml
```

## Data provenance

- All customers, orders, payments, products, sellers and reviews come from the Olist dataset
  (CC BY-NC-SA 4.0). Nothing in them is synthetic.
- Raw CSVs are never modified (they are mounted read-only in Docker) and never committed.
  Every run records their SHA-256 in `reports/data_quality/source_manifest.json`.
- Synthetic components are limited to infrastructure: the simulated provider API, its replay
  clock and fault injection. They will be listed here as they are added.
