"""Prune test runs older than RETENTION_DAYS from AllTestRuns/, keeping their numbers.

Run folders are dated from their metadata.json "timestamp" field, falling back to
the DD-MM-YYYY_HH-MM-SS stamp in the folder name. A folder whose date can't be
read is kept - never guess a run into the trash.

Retention matches the Google Drive cleanup window: once Drive drops a run, its
drive_link is dead, so keeping the row on the dashboard is misleading.

What survives the prune is the performance history: one trimmed metadata entry per
run in performance-history.json, plus its raw per-second CSV zipped under
performance-history/. Only successful nightly runs are recorded - a broken run's
numbers would read as a regression, and a manual run on a branch is not comparable
with the nightly trend. The CSV is kept because metadata only holds the metrics we
report today; with the series we can recompute a metric we have not thought of yet
across the whole history.
"""

import json
import os
import re
import shutil
import sys
import zipfile
from datetime import datetime, timedelta, timezone

RUNS_DIR = "AllTestRuns"
HISTORY_JSON = "performance-history.json"
HISTORY_CSV_DIR = "performance-history"
RETENTION_DAYS = int(os.environ.get("RETENTION_DAYS", "10"))

# Only the nightly trend is comparable run to run.
HISTORY_STARTED_BY = "Nightly"

# What a history entry carries. Dropped on purpose: drive_link (dead once Drive
# expires the folder), has_thumbnail and isArchived (dashboard state), and the checks
# array (test_successful is the part the trend needs). Keys absent from a repo's
# metadata are simply skipped, so one list serves both dashboards.
HISTORY_FIELDS = (
    "timestamp", "test_name", "scene_name", "started_by",
    "commit_sha", "commit_ref", "github_run_id",
    "bots_joined", "bots_requested", "errors", "exceptions",
    "fps_average", "fps_median", "fps_diff",
    "app_time_average", "app_time_median", "app_time_diff",
    "gpu_average", "gpu_median", "gpu_diff",
)

# DD-MM-YYYY_HH-MM-SS, also tolerating DD-MM-YY and a missing time part.
STAMP = re.compile(r"(\d{1,2})-(\d{1,2})-(\d{2,4})(?:[_ ](\d{1,2})-(\d{1,2})-(\d{1,2}))?")


def parse_stamp(text):
    m = STAMP.search(text or "")
    if not m:
        return None
    day, month, year, hour, minute, sec = m.groups()
    year = int(year)
    if year < 100:
        year += 2000
    try:
        return datetime(year, int(month), int(day),
                        int(hour or 0), int(minute or 0), int(sec or 0),
                        tzinfo=timezone.utc)
    except ValueError:
        return None


def read_metadata(folder_path):
    meta_path = os.path.join(folder_path, "metadata.json")
    if not os.path.isfile(meta_path):
        return None
    try:
        with open(meta_path, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"  WARNING: could not read {meta_path}: {e}")
        return None


def run_date(meta, folder_name):
    """metadata.json is authoritative; the folder name is the fallback."""
    if meta:
        parsed = parse_stamp(meta.get("timestamp"))
        if parsed:
            return parsed
    return parse_stamp(folder_name)


def load_history():
    if not os.path.isfile(HISTORY_JSON):
        return []
    try:
        with open(HISTORY_JSON, encoding="utf-8") as f:
            entries = json.load(f)
        return entries if isinstance(entries, list) else []
    except Exception as e:
        print(f"WARNING: could not read {HISTORY_JSON}, starting a new one: {e}")
        return []


def archive(meta, folder_path, folder_name, history, recorded):
    """Add this run to the history, unless it is not the kind we trend or is already in.
    Returns a one-word reason for the log."""
    if not meta:
        return "no metadata"
    if meta.get("started_by") != HISTORY_STARTED_BY:
        return f"not {HISTORY_STARTED_BY.lower()}"
    if not meta.get("test_successful"):
        return "not successful"

    key = meta.get("timestamp") or folder_name
    if key in recorded:
        return "already recorded"

    entry = {k: meta[k] for k in HISTORY_FIELDS if k in meta}
    entry["folder_name"] = folder_name
    history.append(entry)
    recorded.add(key)

    csv_path = os.path.join(folder_path, "CSV_REPORT.csv")
    if os.path.isfile(csv_path):
        os.makedirs(HISTORY_CSV_DIR, exist_ok=True)
        # Named by the run's own timestamp so a history entry and its series line up
        # without the folder name, which carries a runner-local prefix.
        out = os.path.join(HISTORY_CSV_DIR, f"{key}.csv.zip")
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(csv_path, "CSV_REPORT.csv")
        return "recorded + csv"
    return "recorded, no csv"


def main():
    if not os.path.isdir(RUNS_DIR):
        print(f"No {RUNS_DIR}/ directory - nothing to prune.")
        return 0

    cutoff = datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)
    print(f"Retention: {RETENTION_DAYS} days (cutoff {cutoff:%Y-%m-%d %H:%M} UTC)")

    history = load_history()
    recorded = {e.get("timestamp") or e.get("folder_name") for e in history}
    before = len(history)

    deleted = 0
    for name in sorted(os.listdir(RUNS_DIR)):
        path = os.path.join(RUNS_DIR, name)
        if not os.path.isdir(path):
            continue

        meta = read_metadata(path)
        date = run_date(meta, name)
        if date is None:
            print(f"  KEEP (undated) {name}")
            continue
        if date >= cutoff:
            print(f"  keep  {date:%Y-%m-%d}  {name}")
            continue

        reason = archive(meta, path, name, history, recorded)
        shutil.rmtree(path)
        deleted += 1
        print(f"  PRUNE {date:%Y-%m-%d}  {name}  [{reason}]")

    if len(history) != before:
        history.sort(key=lambda e: parse_stamp(e.get("timestamp")) or datetime.min.replace(tzinfo=timezone.utc))
        with open(HISTORY_JSON, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2, ensure_ascii=False)
        print(f"History: {len(history) - before} run(s) added, {len(history)} total in {HISTORY_JSON}.")
    else:
        print(f"History: nothing added, {len(history)} total in {HISTORY_JSON}.")

    print(f"Pruned {deleted} run(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
