"""End-to-end run: raw -> profile -> staging -> validation -> core -> analytics -> report.

Every output is written to a scratch directory and promoted only after every check
passed, so a failed run never leaves a half-built "successful" dataset behind. Runs are
idempotent: each one replaces the previous outputs instead of appending to them.
"""

import shutil
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

import pandas as pd

from opspulse.etl.analytics import build_analytics
from opspulse.etl.config import CATASTROPHIC_REJECTION_SHARE, PATHS, Paths
from opspulse.etl.core import build_core
from opspulse.etl.extract import (
    check_columns,
    create_run_id,
    extract_all,
    fingerprint_source_files,
    verify_source_files,
)
from opspulse.etl.profile import profile_all, write_profile
from opspulse.etl.quarantine import split
from opspulse.etl.report import RunState, build_report, write_report
from opspulse.etl.transform import stage_all
from opspulse.etl.validate import (
    check_analytics,
    check_core,
    critical_problems,
    validate_references,
    validate_rows,
)

STEP_COUNT = 14
WIDTH = 50


class PipelineFailed(Exception):
    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems))
        self.problems = problems


class Console:
    def __init__(self, total: int):
        self.total = total
        self.index = 0

    @contextmanager
    def step(self, label: str) -> Iterator[None]:
        self.index += 1
        prefix = f"[{self.index}/{self.total}] {label}".ljust(42, ".")
        try:
            yield
        except Exception:
            print(f"{prefix} FAIL", flush=True)
            raise
        print(f"{prefix} PASS", flush=True)


def _fail_if(problems: list[str]) -> None:
    if problems:
        raise PipelineFailed(problems)


def _write_outputs(
    paths: Paths, run_id: str, layers: dict[str, dict[str, pd.DataFrame]]
) -> dict[str, dict[str, int]]:
    work = paths.work / run_id
    targets = {
        "staging": paths.staging,
        "core": paths.core,
        "analytics": paths.analytics,
        "quality": paths.quality,
        "rejected": paths.rejected,
    }
    counts = {}
    for layer, frames in layers.items():
        (work / layer).mkdir(parents=True, exist_ok=True)
        for name, df in frames.items():
            df.to_parquet(work / layer / f"{name}.parquet", index=False)
        counts[layer] = {name: len(df) for name, df in frames.items()}
    for layer, target in targets.items():
        if target.exists():
            shutil.rmtree(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(work / layer, target)
    shutil.rmtree(work)
    return counts


def _staging_frames(staged: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    frames = {}
    for table, df in staged.items():
        frame = df.copy()
        frame.insert(0, "_source_row_number", frame.index + 1)
        frames[table] = frame.reset_index(drop=True)
    return frames


def run_pipeline(
    paths: Paths = PATHS, max_rejection_share: float = CATASTROPHIC_REJECTION_SHARE
) -> dict:
    run_id = create_run_id()
    state = RunState(run_id=run_id, started_at=datetime.now(UTC).isoformat(timespec="seconds"))
    started = time.monotonic()
    console = Console(STEP_COUNT)

    print("=" * WIDTH, "OPSPULSE ETL".center(WIDTH), "=" * WIDTH, sep="\n")
    print(f"\nRun ID: {run_id}\n")
    try:
        with console.step("Checking source files"):
            try:
                verify_source_files(paths.raw)
            except FileNotFoundError as exc:
                state.gates["source_files"] = "FAIL"
                raise PipelineFailed([str(exc)]) from exc
            state.gates["source_files"] = "PASS"

        with console.step("Fingerprinting sources"):
            state.manifest = fingerprint_source_files(run_id, paths.raw)

        with console.step("Extracting"):
            raw = extract_all(paths.raw)
            state.source_rows = {table: len(df) for table, df in raw.items()}
            mismatches = [
                f"{table}: missing {columns['missing']}, unexpected {columns['unexpected']}"
                for table, df in raw.items()
                if (columns := check_columns(table, df))["missing"] or columns["unexpected"]
            ]
            state.gates["column_contract"] = "FAIL" if mismatches else "PASS"
            _fail_if(mismatches)

        with console.step("Profiling"):
            write_profile(profile_all(raw, state.manifest), state.manifest, paths.reports)

        with console.step("Transforming"):
            staged = stage_all(raw)

        with console.step("Staging validation"):
            state.issues = validate_rows(staged, raw)
            _fail_if(critical_problems(staged, state.issues, max_rejection_share))

        with console.step("Referential integrity"):
            state.issues = pd.concat(
                [state.issues, validate_references(staged, state.issues)], ignore_index=True
            )
            _fail_if(critical_problems(staged, state.issues, max_rejection_share))

        with console.step("Rejected-record handling"):
            accepted, rejected, warnings = split(staged, raw, state.issues, run_id)
            state.accepted_rows = {table: len(df) for table, df in accepted.items()}
            state.rejected_rows = {table: len(df) for table, df in rejected.items()}

        with console.step("Building core datasets"):
            core = build_core(accepted, state.issues)

        with console.step("Core validation"):
            problems = check_core(core, accepted)
            state.gates["outputs"] = "FAIL" if problems else "PASS"
            _fail_if(problems)

        with console.step("Building analytics"):
            analytics = build_analytics(core)

        with console.step("Analytics validation"):
            problems = check_analytics(core, analytics)
            state.gates["outputs"] = "FAIL" if problems else "PASS"
            _fail_if(problems)

        with console.step("Writing and promoting outputs"):
            state.outputs = _write_outputs(
                paths,
                run_id,
                {
                    "staging": _staging_frames(staged),
                    "core": core,
                    "analytics": analytics,
                    "quality": {"warnings": warnings},
                    "rejected": rejected,
                },
            )
    except PipelineFailed as failure:
        state.problems = failure.problems
        shutil.rmtree(paths.work / run_id, ignore_errors=True)

    report = build_report(state, time.monotonic() - started)
    if not state.problems:
        with console.step("Writing quality report"):
            write_report(report, paths.reports)
    else:
        write_report(report, paths.reports)
    _print_result(report)
    return report


def _print_result(report: dict) -> None:
    totals = report["totals"]
    print("\n" + "-" * WIDTH, "RESULT", "-" * WIDTH, sep="\n")
    print(f"\nStatus: {report['status']}\n")
    print(f"Source rows processed: {totals['source_rows']:,}")
    print(f"Accepted rows:         {totals['accepted_rows']:,}")
    print(f"Rejected rows:         {totals['rejected_rows']:,}")
    print(f"\nCritical errors: {len(report['critical_problems'])}")
    print(f"Warnings:        {totals['warnings']:,}")
    for problem in report["critical_problems"]:
        print(f"  - {problem}")
    print("\nReport: reports/data_quality/latest_report.md")
    print("=" * WIDTH)
