"""Raw profiling: measure what the source actually contains before any cleaning.

Columns are profiled as loaded (text), so the profile reports how well each one
parses as a number or timestamp instead of trusting pandas' type inference.
"""

import json
import logging
from pathlib import Path

import pandas as pd

from opspulse.etl import config
from opspulse.etl.extract import check_columns

log = logging.getLogger(__name__)

NUMERIC_THRESHOLD = 0.95  # share of values that must parse for a column to count as numeric
FULL_FREQUENCY_MAX_VALUES = 50  # below this cardinality, keep every value's frequency
TOP_VALUES = 10
MARKDOWN_INLINE_VALUES = 15


def profile_column(
    series: pd.Series, *, is_timestamp: bool = False, pattern: str | None = None
) -> dict:
    non_null = series.dropna()
    lengths = non_null.str.len()
    info = {
        "null_count": int(series.isna().sum()),
        "null_pct": round(float(series.isna().mean() * 100), 4),
        "unique_count": int(non_null.nunique()),
        "length_min": int(lengths.min()) if len(non_null) else None,
        "length_max": int(lengths.max()) if len(non_null) else None,
        "whitespace_padded_count": int((non_null != non_null.str.strip()).sum()),
    }

    if is_timestamp:
        parsed = pd.to_datetime(non_null, format=config.RAW_TIMESTAMP_FORMAT, errors="coerce")
        has_values = bool(parsed.notna().any())
        info |= {
            "kind": "timestamp",
            "invalid_parse_count": int(parsed.isna().sum()),
            "min": str(parsed.min()) if has_values else None,
            "max": str(parsed.max()) if has_values else None,
        }
        return info

    numeric = pd.to_numeric(non_null, errors="coerce")
    parsed_count = int(numeric.notna().sum())
    if pattern is None and parsed_count and parsed_count >= NUMERIC_THRESHOLD * len(non_null):
        valid = numeric.dropna()
        info |= {
            "kind": "numeric",
            "numeric_parse_failures": len(non_null) - parsed_count,
            "min": float(valid.min()),
            "max": float(valid.max()),
            "mean": round(float(valid.mean()), 4),
            "median": float(valid.median()),
            "negative_count": int((valid < 0).sum()),
            "zero_count": int((valid == 0).sum()),
        }
        return info

    info["kind"] = "text"
    if pattern is not None:
        info["pattern"] = pattern
        info["pattern_nonconforming_count"] = int((~non_null.str.fullmatch(pattern)).sum())
    counts = non_null.value_counts()
    if info["unique_count"] <= FULL_FREQUENCY_MAX_VALUES:
        info["value_frequency"] = counts.to_dict()
    else:
        info["top_values"] = counts.head(TOP_VALUES).to_dict()
    return info


def profile_table(table: str, df: pd.DataFrame) -> dict:
    timestamps = set(config.TIMESTAMP_COLUMNS.get(table, []))
    patterns = config.COLUMN_PATTERNS.get(table, {})
    columns = check_columns(table, df)

    profile = {
        "row_count": len(df),
        "column_count": len(df.columns),
        "missing_columns": columns["missing"],
        "unexpected_columns": columns["unexpected"],
        "duplicate_row_count": int(df.duplicated().sum()),
    }

    key = config.CANDIDATE_KEYS.get(table)
    if key and set(key) <= set(df.columns):
        duplicated = df.duplicated(subset=key, keep=False)
        profile["candidate_key"] = {
            "columns": key,
            "duplicate_row_count": int(duplicated.sum()),
            "duplicate_key_count": len(df.loc[duplicated, key].drop_duplicates()),
        }

    profile["columns"] = {
        column: profile_column(
            df[column], is_timestamp=column in timestamps, pattern=patterns.get(column)
        )
        for column in df.columns
    }
    return profile


def profile_relationships(
    raw: dict[str, pd.DataFrame], relationships=config.RELATIONSHIPS
) -> list[dict]:
    results = []
    for child, child_column, parent, parent_column in relationships:
        child_values = raw[child][child_column].dropna()
        parent_values = raw[parent][parent_column].dropna()
        orphans = child_values[~child_values.isin(parent_values)]
        results.append(
            {
                "child": f"{child}.{child_column}",
                "parent": f"{parent}.{parent_column}",
                "child_null_count": int(raw[child][child_column].isna().sum()),
                "orphan_row_count": len(orphans),
                "orphan_key_count": int(orphans.nunique()),
                "sample_orphan_keys": orphans.drop_duplicates().head(5).tolist(),
                "unreferenced_parent_key_count": int(
                    parent_values[~parent_values.isin(child_values)].nunique()
                ),
            }
        )
    return results


def profile_all(raw: dict[str, pd.DataFrame], manifest: dict) -> dict:
    tables = {}
    for table, df in raw.items():
        tables[table] = profile_table(table, df)
        log.info("Profiled %s", table)
    return {
        "run_id": manifest["run_id"],
        "sources": manifest["files"],
        "tables": tables,
        "relationships": profile_relationships(raw),
    }


def _column_notes(info: dict) -> str:
    notes = []
    if info["kind"] == "timestamp":
        notes.append(f"{info['min']} → {info['max']}; invalid parses {info['invalid_parse_count']}")
    elif info["kind"] == "numeric":
        notes.append(f"{info['min']:g} → {info['max']:g}; median {info['median']:g}")
        if info["negative_count"]:
            notes.append(f"negatives {info['negative_count']}")
        if info["numeric_parse_failures"]:
            notes.append(f"non-numeric {info['numeric_parse_failures']}")
    else:
        notes.append(f"length {info['length_min']}–{info['length_max']}")
        if "pattern" in info:
            notes.append(f"`{info['pattern']}` mismatches {info['pattern_nonconforming_count']:,}")
        frequency = info.get("value_frequency", {})
        if 0 < len(frequency) <= MARKDOWN_INLINE_VALUES:
            notes.append(", ".join(f"{value}={count:,}" for value, count in frequency.items()))
    if info["whitespace_padded_count"]:
        notes.append(f"whitespace-padded {info['whitespace_padded_count']}")
    return "; ".join(notes)


def render_markdown(profile: dict) -> str:
    lines = [
        "# Raw data profile",
        "",
        f"Run `{profile['run_id']}`. Generated by `opspulse-etl profile`; do not edit by hand.",
        "",
        "## Relationships",
        "",
        "| child | parent | orphan rows | orphan keys | unreferenced parent keys |",
        "|---|---|---:|---:|---:|",
    ]
    for rel in profile["relationships"]:
        lines.append(
            f"| `{rel['child']}` | `{rel['parent']}` | {rel['orphan_row_count']:,} "
            f"| {rel['orphan_key_count']:,} | {rel['unreferenced_parent_key_count']:,} |"
        )

    sources = {source["table"]: (name, source) for name, source in profile["sources"].items()}
    for table, info in profile["tables"].items():
        filename, source = sources[table]
        lines += [
            "",
            f"## {table}",
            "",
            f"`{filename}` · {source['bytes']:,} bytes · {source['encoding']} · "
            f"sha256 `{source['sha256'][:12]}…`",
            "",
            f"Rows {info['row_count']:,} · columns {info['column_count']} · "
            f"exact duplicate rows {info['duplicate_row_count']:,}",
        ]
        if info["missing_columns"] or info["unexpected_columns"]:
            lines.append(
                f"**Column contract mismatch:** missing {info['missing_columns']}, "
                f"unexpected {info['unexpected_columns']}"
            )
        if key := info.get("candidate_key"):
            lines.append(
                f"Candidate key ({', '.join(key['columns'])}): "
                f"{key['duplicate_key_count']:,} duplicated keys across "
                f"{key['duplicate_row_count']:,} rows"
            )
        lines += [
            "",
            "| column | kind | nulls | null % | unique | notes |",
            "|---|---|---:|---:|---:|---|",
        ]
        for column, col in info["columns"].items():
            lines.append(
                f"| `{column}` | {col['kind']} | {col['null_count']:,} | {col['null_pct']:.2f} "
                f"| {col['unique_count']:,} | {_column_notes(col)} |"
            )
    return "\n".join(lines) + "\n"


def write_profile(profile: dict, manifest: dict, report_dir: Path = config.PATHS.reports) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        "source_manifest.json": json.dumps(manifest, indent=2, ensure_ascii=False),
        "raw_profile.json": json.dumps(profile, indent=2, ensure_ascii=False, allow_nan=False),
        "raw_profile.md": render_markdown(profile),
    }
    for name, text in outputs.items():
        (report_dir / name).write_text(text, encoding="utf-8", newline="\n")
    log.info("Wrote raw profile to %s", report_dir)
