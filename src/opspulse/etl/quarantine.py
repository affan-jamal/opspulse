"""Splits staged rows into accepted, rejected and warning records.

Rejected rows are quarantined with their original raw text, unmodified, plus lineage
columns saying which run, file, record and rules rejected them.
"""

import pandas as pd

from opspulse.etl.config import SOURCE_FILES
from opspulse.etl.schema import KEYS
from opspulse.etl.validate import REJECTING, WARNING, rejected_rows


def _record_keys(df: pd.DataFrame, table: str) -> pd.Series:
    key = KEYS[table]
    if not key:
        return pd.Series(pd.NA, index=df.index, dtype="str")
    return df[key].astype("str").agg("|".join, axis=1)


def split(
    staged: dict[str, pd.DataFrame],
    raw: dict[str, pd.DataFrame],
    issues: pd.DataFrame,
    run_id: str,
) -> tuple[dict[str, pd.DataFrame], dict[str, pd.DataFrame], pd.DataFrame]:
    accepted, rejected, warning_frames = {}, {}, []
    for table, df in staged.items():
        rows = rejected_rows(issues, table)
        accepted[table] = df.drop(index=rows)

        hits = issues[(issues["table"] == table) & issues["severity"].isin(REJECTING)]
        reasons = hits.groupby("row").agg(
            stage=("stage", "first"), reason=("code", lambda codes: ";".join(sorted(set(codes))))
        )
        quarantined = raw[table].loc[reasons.index].copy()
        quarantined.insert(0, "_etl_run_id", run_id)
        quarantined.insert(1, "_source_table", table)
        quarantined.insert(2, "_source_file", SOURCE_FILES[table])
        quarantined.insert(3, "_source_row_number", reasons.index + 1)
        quarantined.insert(4, "_rejection_stage", reasons["stage"].astype("str"))
        quarantined.insert(5, "_rejection_reason", reasons["reason"].astype("str"))
        rejected[table] = quarantined.reset_index(drop=True)

        flagged = issues[
            (issues["table"] == table) & (issues["severity"] == WARNING) & ~issues["row"].isin(rows)
        ]
        if not flagged.empty:
            keys = _record_keys(df.loc[flagged["row"].unique()], table)
            warning_frames.append(
                pd.DataFrame(
                    {
                        "table": table,
                        "source_row_number": flagged["row"].to_numpy() + 1,
                        "record_key": keys.loc[flagged["row"]].to_numpy(),
                        "code": flagged["code"].to_numpy(),
                    }
                )
            )

    warnings = (
        pd.concat(warning_frames, ignore_index=True)
        if warning_frames
        else pd.DataFrame(
            {
                "table": pd.Series(dtype="str"),
                "source_row_number": pd.Series(dtype="int64"),
                "record_key": pd.Series(dtype="str"),
                "code": pd.Series(dtype="str"),
            }
        )
    )
    return accepted, rejected, warnings
