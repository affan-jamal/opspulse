# syntax=docker/dockerfile:1.7
#
# One image for every OpsPulse service (ETL now; provider API, ingestion worker and
# analytics API later). Compose picks the command. Builds for amd64 and arm64
# (Oracle Cloud's free Ampere VMs are arm64).

ARG PYTHON_VERSION=3.13
ARG UV_VERSION=0.12.23

FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv

# ---- build: resolve the locked environment into /opt/venv ----
FROM python:${PYTHON_VERSION}-slim-trixie AS build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /src

# Dependencies first, so this layer is reused until uv.lock changes.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-dev --all-extras --no-install-project

COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --all-extras --no-editable

# ---- runtime: just Python, the venv and a non-root user ----
FROM python:${PYTHON_VERSION}-slim-trixie AS runtime
LABEL org.opencontainers.image.source="https://github.com/affan-jamal/opspulse" \
      org.opencontainers.image.description="OpsPulse: operations intelligence on the Olist dataset"

RUN groupadd --system --gid 1000 opspulse \
    && useradd --system --uid 1000 --gid opspulse --home-dir /app --no-create-home opspulse

ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    OPSPULSE_ROOT=/app

COPY --from=build /opt/venv /opt/venv
WORKDIR /app
RUN mkdir -p data/raw/olist reports/data_quality && chown -R opspulse:opspulse /app
USER opspulse

CMD ["opspulse-etl", "--help"]
