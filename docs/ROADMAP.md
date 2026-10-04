# OpsPulse roadmap

**Phase 1 is complete:** `opspulse-etl run` passes all 14 steps on the real data in about 50 s,
locally and in Docker. Next up is Phase 2 (database).

The handover's data rules still apply: immutable raw files, no invented facts, explicit grains,
and flags instead of silent drops. Its strict waterfall does not. Each phase ships something that
runs, and everything runs on free tiers.

## Target architecture

```text
 Kaggle CSVs ──► ETL (Phase 1) ──► provider.* ──► Provider API ──HTTP──► Ingestion ──► ops.*
 (read-only)     Parquet + report   (Postgres)    replay clock,          retries,       (Postgres)
                                                  429/5xx injection      watermarks       │
                                                                                          ▼
          Next.js dashboard ◄── Analytics API ◄── SQL views + anomalies over ops.* ◄──────┘
          (Vercel)              (FastAPI)          (rules + Isolation Forest)
```

There is one Postgres with two schemas. `provider` stands in for a third party's database, and
`ops` is OpsPulse's own. Only HTTP crosses between them.

## Phases

| # | Phase | Done when | Days | Status |
|---|---|---|---|---|
| 1 | Data foundation | One command builds validated staging/core/analytics + quality report, locally and in Docker | 3 | ✅ |
| 2 | Database | Alembic migrations for `provider` + `ops`; core Parquet loaded into `provider` with `COPY`; row counts match | 1 | |
| 3 | Provider API + replay | Paginated, keyed, rate-limited read API; replay clock; injectable 429/500/503/timeouts; contract tests | 2 | |
| 4 | Ingestion + sync | Retrying client upserts into `ops`; watermarks; `ops.sync_runs`; Celery beat tick; survives a provider crash mid-sync | 2 | |
| 5 | Analytics API | SQL views over `ops` equal the Phase 1 oracle marts after a full replay; FastAPI endpoints + OpenAPI | 2 | |
| 6 | Anomalies | 3 explainable rules + Isolation Forest on pre-delivery features; documented severity policy; `ops.anomalies` | 2 | |
| 7 | Dashboard | Next.js: Executive, Operations, Anomaly Center, System Health; deployed on Vercel | 4 | |
| 8 | Ship | `compose.prod.yaml` on the free VM behind Caddy TLS; deploy on push; uptime + error monitoring | 2 | |

About 18 focused days. The handover's separate phases for testing (9) and monitoring (13) are
folded in: tests ship with every phase, and monitoring is `ops.sync_runs`, `/health`, the System
Health page and the uptime/error tools below.

## Where this plan improves on the handover

1. **Analytics come after ingestion.** In the handover, analytics were built before the provider
   API, so the replay could never change the dashboard. Here they are SQL views over `ops`. The
   two pandas marts from Phase 1 serve as a test oracle for those views.
2. **Status as-of the replay clock.** The provider derives each order's status from which
   lifecycle timestamps have already passed. An order shows up as `approved`, later becomes
   `shipped`, then `delivered`, so the ingestion upserts are real updates rather than one-shot
   inserts.
3. **Decisions come from the data, not from assumptions.** The handover assumed reviews were
   keyed by `review_id`, treated a missing zip as an ERROR, quarantined lifecycle anomalies and
   relied on RFM. The profile disproved all four; the decisions are in the table below.
4. **Lateness compares calendar dates.** The promised delivery is a date, so a parcel delivered at
   15:00 on that date is on time. `is_late` is null, never false, for undelivered orders. Late
   rate: 6.77% of 96,470 delivered orders.
5. **"Catastrophic" has a number.** A run fails if any table loses more than 1% of its rows to
   rejection, or if any CRITICAL rule fires (duplicate or missing keys).
6. **The documentation can't drift.** The data dictionary is generated from the code, and CI
   fails if it is stale.
7. **Failures are safe.** Outputs are promoted only after every check passes, and reruns are
   idempotent (both are tested).
8. **Production details the handover skipped.** Lockfile (`uv.lock`), one multi-arch image,
   non-root containers, read-only raw mounts, localhost-only ports, Dependabot, and a backup
   strategy. The backup strategy is that the whole database can be rebuilt from the raw files by
   ETL + replay, so nothing needs paid backup storage.

## Free stack

Limits were checked on 2026-10-04. Free tiers change, so re-check before you sign up.

| Need | Tool | Free allowance | Notes |
|---|---|---|---|
| Code, CI, images | GitHub (public repo), Actions, GHCR | Actions and public GHCR images are free | Public also unlocks free CodeQL; enable *default setup* in repo settings |
| Server (primary) | **Oracle Cloud Always Free**, Ampere A1 | 2 OCPU / 12 GB RAM (halved from 4/24 on 2026-06-15) + 200 GB block storage | Runs the whole compose stack; the image is built for arm64 |
| Frontend | **Vercel Hobby** | 100 GB transfer, 1M function invocations, 4 h active CPU | Personal, non-commercial use only; pauses at limits instead of billing |
| HTTPS + domain | Caddy + DuckDNS subdomain | Free | Caddy fetches Let's Encrypt certificates automatically |
| Errors | Sentry (Developer plan) | Free tier | SDKs for FastAPI and Next.js |
| Uptime | UptimeRobot | Free tier | Pings `/health` |
| Dataset | Kaggle | Free | CLI download proves the clean-machine gate |

### Primary deployment: one free VM

Oracle VM (Ubuntu, arm64) runs `compose.prod.yaml`: postgres, redis, provider, api, worker,
beat and caddy, with images pulled from GHCR. The web app runs on Vercel and calls the API over
HTTPS. A GitHub Actions job deploys on push with `docker compose pull && up -d` over SSH. Redis
runs on the VM because a Celery worker polls constantly, and Upstash's free 500k commands/month
would run out within days.

### Fallback if the Oracle sign-up fails

- **Neon free** for Postgres: 0.5 GB storage and 100 CU-hours per project, suspends after
  5 minutes idle. Use one project per schema. Each copy is about the size of the
  non-geolocation CSVs (~62 MB) plus indexes, so it fits.
- **Render free** for the APIs: 750 instance-hours/month, sleeps after 15 minutes idle,
  ~1 minute cold start.
- **GitHub Actions cron** replaces Celery beat. Render's free tier has no background workers, so
  the cron calls a sync endpoint.

**Avoid:**
- **Render free Postgres** expires after 30 days.
- **Supabase free** pauses after 7 idle days.
- **Koyeb** allows one 0.1 vCPU instance and needs a card.

## Phase 1: decisions forced by the actual data

Every rule below is enforced in code and listed in the
[data dictionary](data/data_dictionary.md). Numbers are from `reports/data_quality/`.

| Finding | Handover assumed | Decision |
|---|---|---|
| 789 `review_id`s repeat across 1,603 rows, always on different orders; 547 orders have >1 review | grain = one `review_id` | Key (`review_id`, `order_id`); no dedup |
| 278 customer + 7 seller rows have a zip prefix with no geolocation | missing FK → ERROR | WARNING: geo is enrichment; rejecting would orphan orders |
| 1,359 orders reached the carrier before approval, 23 the customer before the carrier | quarantine | WARNING + `has_lifecycle_anomaly` (1,396 orders); rejecting would orphan items, payments, reviews |
| 8 delivered orders have no delivery date; 6 undelivered have one | — | WARNING; such orders are not `is_delivered` |
| 2 zero-installment card payments, 9 zero-value payments, 3 `not_defined` | `installments >= 1` | WARNING, kept |
| Reconciliation: 98,362 MATCHED · 54 MINOR · 249 SIGNIFICANT · 775 NO_ITEMS · 1 NO_PAYMENT | tolerance TBD | ≤ R$0.01 / ≤ R$1 / more; NO_ITEMS bucket added |
| Geolocation: 261,831 exact-duplicate rows; 31 points outside Brazil | mean per prefix | Distinct in-Brazil points, **median** per prefix (19,011 prefixes) |
| 2016 holds 329 orders; Sep–Oct 2018 holds 20 | `analysis_date` = max purchase | Analysis window 2017-01-01 → 2018-08-31 (`in_analysis_window`) |
| 3.1% of real customers ordered more than once | RFM as a foundation | RFM cut from the MVP |
| Zip prefixes are quoted 5-digit text; one file has a UTF-8 BOM | `zfill(5)`; try UTF-8 | Read everything as text with `utf-8-sig`; pattern checks instead of repair |
| Nothing fails a hard rule | big quarantine machinery | 0 rows rejected; the reject path is proven on fixtures instead |

## Build notes for Phases 2–8

**2 · Database.** Write SQLAlchemy 2 models and Alembic migrations. `provider.*` mirrors the core
tables. `ops.*` holds the same entities plus `sync_state` (one watermark per entity),
`sync_runs`, `anomalies` and `models`. Add primary keys, foreign keys only for the ERROR
references, CHECK constraints mirroring the validation rules, and indexes on foreign keys and
`purchase_at`. A loader streams Parquet into Postgres with psycopg 3 `COPY`.

**3 · Provider API.** `GET /v1/{orders,order-items,payments,reviews,customers,products,sellers}`
with keyset pagination (`cursor`, `limit`) and an `updated_since` filter. Auth is an `X-API-Key`
header. A token bucket returns `429` with `Retry-After`. Environment variables set fault rates
for 500/503/timeouts. The replay clock lives in `provider.replay_clock`, and
`POST /v1/admin/clock/advance` moves it forward.

**4 · Ingestion.** An httpx client with tenacity: exponential backoff with jitter, honouring
`Retry-After`. Upserts use `INSERT … ON CONFLICT DO UPDATE` and the watermark is only
committed after the page is stored. A Celery beat tick runs every 30 s: advance the clock one
simulated day, then sync. Every run writes a row to `ops.sync_runs`.

**5 · Analytics API.** Views and materialized views in `ops` for daily sales, the financial
summary, sellers, delivery and reviews, refreshed after each sync. Endpoints: `/v1/kpis`,
`/daily-sales`, `/sellers`, `/delivery`, `/reconciliation`, `/anomalies`, `/sync-runs` and
`/health`. Seller and product metrics are built from per-order aggregates, never from a
multi-way join.

**6 · Anomalies.** Three rules:
- a SIGNIFICANT_DIFFERENCE payment mismatch;
- a delivery delay above p95 for the seller-state to customer-state route;
- an order value far above the customer's or seller's history.

Isolation Forest uses pre-delivery features only (no leakage): price, freight, item count,
weight and dimensions, category, hour, weekday, and the seller and customer states. Severity is
a documented policy based on score percentiles, not a probability.

**7 · Dashboard.** Set up with:

```bash
npx create-next-app@latest web --ts --tailwind --eslint --app --src-dir --import-alias "@/*"
cd web && npx shadcn@latest init && npx shadcn@latest add card table badge tabs chart
npm i @tanstack/react-query
npx openapi-typescript http://localhost:8000/openapi.json -o src/lib/api-types.ts
```

Every chart states its metric definition, grain and filters, as the data dictionary does.

**8 · Ship.** Steps:
- `compose.prod.yaml`: GHCR images, Caddy, restart policies, no source mounts.
- `infra/oracle/bootstrap.sh`: Docker, ufw allowing 22/80/443 only, and swap.
- A deploy job in CI.
- Sentry and UptimeRobot set up.
- README screenshots and an architecture diagram.

## Prerequisites

| Need | Status |
|---|---|
| Python 3.12+, uv | 3.13.3; uv 0.12.23 in `.venv` (or `pip install uv`) |
| Docker | 29.5.3, stack verified |
| Node 20+ | 22.20.0 (Phase 7) |
| GitHub repo `affan-jamal/opspulse` | create it empty, then `git push -u origin main` |
| Kaggle token, Oracle Cloud, Vercel, DuckDNS, Sentry, UptimeRobot accounts | needed from Phase 8 (Kaggle any time) |

## Sources for the free-tier limits

- Oracle Always Free A1 reduction: [InfoQ](https://infoq.com/news/2026/07/oracle-cloud-free-tier-limits/), [terminalbytes](https://terminalbytes.com/oracle-cloud-free-tier-changes-2026)
- Neon free plan: [costbench](https://costbench.com/software/database-as-service/neon/free-plan)
- Render free tier: [Render](https://render.com/articles/platforms-with-a-real-free-tier-for-developers-in-2026), [kuberns](https://kuberns.com/blogs/render-postgres-pricing-setup-limits/)
- Upstash Redis free tier: [Upstash](https://upstash.com/blog/redis-pricing-comparison-every-major-provider-in-2026-with-numbers)
- Vercel Hobby: [deploywise](https://deploywise.dev/blog/vercel-free-tier-limits-2026)
- Supabase free tier: [automationatlas](https://automationatlas.io/answers/supabase-free-tier-limits-2026/)
- Koyeb free instance: [Koyeb docs](https://www.koyeb.com/docs/faq/pricing)
- GHCR for public images: [GitHub blog](https://github.blog/news-insights/product-news/introducing-github-container-registry/)
