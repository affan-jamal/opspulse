"""Command-line entry point: `opspulse-etl <command>` or `python -m opspulse.etl <command>`."""

import argparse
import logging

import pandas as pd

from opspulse.etl import config
from opspulse.etl.dictionary import write_dictionary
from opspulse.etl.extract import (
    check_columns,
    create_run_id,
    extract_all,
    fingerprint_source_files,
    read_raw,
    verify_source_files,
)
from opspulse.etl.logging_config import setup_logging
from opspulse.etl.pipeline import run_pipeline
from opspulse.etl.profile import profile_all, write_profile

log = logging.getLogger("opspulse.etl")


def verify() -> int:
    """Are all files present, can they be opened, what columns and rows do they have?"""
    verify_source_files()
    failures = 0
    for table in config.SOURCE_FILES:
        try:
            df = read_raw(table)
        except (UnicodeDecodeError, pd.errors.ParserError) as exc:
            print(f"{table:<22} {'':>10}        FAIL  unreadable: {exc}")
            failures += 1
            continue
        columns = check_columns(table, df)
        ok = not columns["missing"] and not columns["unexpected"]
        failures += not ok
        detail = "" if ok else f"  missing={columns['missing']} unexpected={columns['unexpected']}"
        print(f"{table:<22} {len(df):>10,} rows  {'PASS' if ok else 'FAIL'}{detail}")
    return 1 if failures else 0


def profile() -> int:
    run_id = create_run_id()
    log.info("Run %s", run_id)
    verify_source_files()
    manifest = fingerprint_source_files(run_id)
    raw = extract_all()
    write_profile(profile_all(raw, manifest), manifest)
    return 0


def run() -> int:
    return 1 if run_pipeline()["status"] == "FAILED" else 0


def dictionary() -> int:
    print(f"Wrote {write_dictionary()}")
    return 0


COMMANDS = {"verify": verify, "profile": profile, "run": run, "dictionary": dictionary}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="opspulse-etl", description="OpsPulse Olist ETL")
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("verify", help="check source files exist, open and match the contract")
    subcommands.add_parser("profile", help="fingerprint + profile raw sources into reports/")
    subcommands.add_parser(
        "run", help="full pipeline: raw -> staging -> core -> analytics + report"
    )
    subcommands.add_parser("dictionary", help="regenerate docs/data/data_dictionary.md")
    parser.add_argument("-v", "--verbose", action="store_true", help="log every stage")
    args = parser.parse_args(argv)

    # `run` prints its own step-by-step summary; logs would interleave with it.
    quiet = args.command == "run" and not args.verbose
    setup_logging(logging.WARNING if quiet else logging.INFO)
    try:
        return COMMANDS[args.command]()
    except FileNotFoundError as exc:
        log.error("%s", exc)
        return 1
