"""Load each day's report files from the OneDrive landing folder into Azure SQL.

Power Automate saves every emailed attachment into the landing folder as
YYYY-MM-DD_<original name>. For each day that isn't loaded yet, this script:

  1. checks that exactly EXPECTED_FILES_PER_DAY files have arrived for it,
  2. reads every file as text and checks it has exactly the EXPECTED_COLUMNS,
  3. appends all rows to dbo.financial_data (tagged with source_file and
     load_date) and records each file in dbo.load_log, in ONE transaction.

A day that is incomplete or has a bad file is not loaded, and the script exits
with code 1 so Task Scheduler shows a failed run. Files already in dbo.load_log
are skipped, so running the script again is always safe.

Usage:
    python load_to_sql.py                   # load every complete day not loaded yet
    python load_to_sql.py --create-tables   # one-off: run sql/01_create_tables.sql
"""

import argparse
import logging
import os
import re
import sys
import time
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import Date, DateTime, Integer, column, create_engine, insert, select, table, text
from sqlalchemy.engine import URL, Engine
from sqlalchemy.exc import DBAPIError, SQLAlchemyError

PROJECT_DIR = Path(__file__).resolve().parent

EXPECTED_FILES_PER_DAY = 25

EXPECTED_COLUMNS = [
    "ID", "Customer_ID", "Month", "Name", "Age", "SSN", "Occupation", "Annual_Income",
    "Monthly_Inhand_Salary", "Num_Bank_Accounts", "Num_Credit_Card", "Interest_Rate",
    "Num_of_Loan", "Type_of_Loan", "Delay_from_due_date", "Num_of_Delayed_Payment",
    "Changed_Credit_Limit", "Num_Credit_Inquiries", "Credit_Mix", "Outstanding_Debt",
    "Credit_Utilization_Ratio", "Credit_History_Age", "Payment_of_Min_Amount",
    "Total_EMI_per_month", "Amount_invested_monthly", "Payment_Behaviour",
    "Monthly_Balance", "Credit_Score",
]

# "2026-10-04_combined_part_1.xlsx" belongs to 2026-10-04. Anything else in the folder
# (signature images, Excel lock files, undated names) is ignored.
LANDED_FILE = re.compile(r"^(\d{4}-\d{2}-\d{2})_.+\.(csv|xlsx)$", re.IGNORECASE)

# Rows per INSERT batch. Keeps pyodbc's fast_executemany buffers small.
INSERT_BATCH_ROWS = 2_000

log = logging.getLogger("loader")

financial_data = table(
    "financial_data",
    *(column(name) for name in EXPECTED_COLUMNS),
    column("source_file"),
    column("load_date", Date),
    schema="dbo",
)
load_log = table(
    "load_log",
    column("file_name"),
    column("load_date", Date),
    column("row_count", Integer),
    column("loaded_at", DateTime),
    schema="dbo",
)


class DayNotLoaded(Exception):
    """One of the day's files is unreadable or doesn't have the expected columns."""


def find_landed_files(landing_dir: Path) -> dict[date, list[Path]]:
    """Group the landing folder's dated files by the day in front of their name."""
    days = defaultdict(list)
    for path in sorted(landing_dir.iterdir()):
        if not path.is_file():
            continue
        match = LANDED_FILE.match(path.name)
        if not match:
            log.warning("Ignoring %s: not a dated .csv or .xlsx file.", path.name)
            continue
        try:
            day = date.fromisoformat(match.group(1))
        except ValueError:
            log.warning("Ignoring %s: %s is not a real date.", path.name, match.group(1))
            continue
        days[day].append(path)
    return dict(days)


def read_landed_file(path: Path) -> pd.DataFrame:
    """Read one file with every column as text, exactly as it arrived.

    Everything stays text because columns like Annual_Income hold values such as
    "102594.9_": letting pandas guess would type a column as numbers in one file and
    text in the next. Power Query does the typing and cleaning downstream.
    """
    try:
        if path.suffix.lower() == ".csv":
            df = pd.read_csv(path, dtype=str, keep_default_na=False, na_values=[""], encoding="utf-8-sig")
        else:
            df = pd.read_excel(path, dtype=str, keep_default_na=False, na_values=[""])
    except Exception as exc:
        raise DayNotLoaded(f"{path.name} could not be read: {exc}") from exc

    missing = [name for name in EXPECTED_COLUMNS if name not in df.columns]
    unexpected = [name for name in df.columns if name not in EXPECTED_COLUMNS]
    if missing or unexpected:
        raise DayNotLoaded(
            f"{path.name} does not have the {len(EXPECTED_COLUMNS)} expected columns. "
            f"Missing: {', '.join(missing) or 'none'}. Unexpected: {', '.join(map(str, unexpected)) or 'none'}."
        )
    if df.empty:
        raise DayNotLoaded(f"{path.name} has no rows.")
    return df[EXPECTED_COLUMNS]


def insert_file(conn, file_name: str, df: pd.DataFrame, day: date, loaded_at: datetime) -> None:
    """Append one file's rows and its load_log entry, inside the caller's transaction."""
    rows = df.assign(source_file=file_name, load_date=day)
    records = rows.astype(object).where(rows.notna(), None).to_dict("records")
    for start in range(0, len(records), INSERT_BATCH_ROWS):
        conn.execute(insert(financial_data), records[start:start + INSERT_BATCH_ROWS])
    conn.execute(
        insert(load_log),
        [{"file_name": file_name, "load_date": day, "row_count": len(df), "loaded_at": loaded_at}],
    )


def load_day(engine: Engine, day: date, paths: list[Path]) -> int:
    """Load one day's files all-or-nothing. Returns the number of rows loaded."""
    # Read and check every file before touching the database, so a bad file means
    # the transaction is never even opened.
    files = [(path.name, read_landed_file(path)) for path in paths]
    loaded_at = datetime.now(timezone.utc).replace(tzinfo=None)
    with engine.begin() as conn:  # commits only if every insert succeeds
        for file_name, df in files:
            insert_file(conn, file_name, df, day, loaded_at)
    return sum(len(df) for _, df in files)


def run(engine: Engine, landing_dir: Path, expected_files: int = EXPECTED_FILES_PER_DAY) -> bool:
    """Load every complete day that isn't loaded yet. Returns False if any day was held back."""
    days = find_landed_files(landing_dir)
    with engine.connect() as conn:
        logged = conn.execute(select(load_log.c.file_name, load_log.c.load_date)).all()
    loaded_files = {row.file_name for row in logged}
    loaded_days = {row.load_date for row in logged}

    ok = True
    loaded_any = False
    for day in sorted(days):
        new_files = [path for path in days[day] if path.name not in loaded_files]
        if not new_files:
            continue
        if day in loaded_days:
            log.error(
                "%s: already loaded, but %d new file(s) arrived for it (%s). Not loaded. To reload "
                "the whole day, run the undo at the bottom of sql/02_checks.sql first.",
                day, len(new_files), ", ".join(path.name for path in new_files),
            )
            ok = False
            continue
        if len(new_files) < expected_files:
            log.error("%s: %d of %d files have arrived. Waiting for the rest.", day, len(new_files), expected_files)
            ok = False
            continue
        if len(new_files) > expected_files:
            log.error(
                "%s: %d files arrived but %d were expected. Not loaded; check the landing folder for duplicates.",
                day, len(new_files), expected_files,
            )
            ok = False
            continue

        started = time.perf_counter()
        try:
            rows = load_day(engine, day, new_files)
        except DayNotLoaded as exc:
            log.error("%s: not loaded. %s", day, exc)
            ok = False
            continue
        except SQLAlchemyError as exc:
            log.error("%s: database error, nothing from this day was kept. %s", day, exc)
            ok = False
            continue
        log.info("%s: loaded %d files, %d rows in %.1f s.", day, len(new_files), rows, time.perf_counter() - started)
        loaded_any = True

    if ok and not loaded_any:
        log.info("Nothing new to load.")
    return ok


def make_engine() -> Engine:
    """Connect to Azure SQL with the login from .env."""
    required = ["AZURE_SQL_SERVER", "AZURE_SQL_DATABASE", "AZURE_SQL_USER", "AZURE_SQL_PASSWORD"]
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        raise SystemExit(f"Missing in .env: {', '.join(missing)} (see .env.example)")
    url = URL.create(
        "mssql+pyodbc",
        username=os.environ["AZURE_SQL_USER"],
        password=os.environ["AZURE_SQL_PASSWORD"],
        host=os.environ["AZURE_SQL_SERVER"],
        port=1433,
        database=os.environ["AZURE_SQL_DATABASE"],
        query={
            "driver": os.environ.get("ODBC_DRIVER", "ODBC Driver 18 for SQL Server"),
            "Encrypt": "yes",
            "TrustServerCertificate": "no",
        },
    )
    return create_engine(url, fast_executemany=True)


def wait_for_database(engine: Engine, attempts: int = 4, delay_seconds: int = 30) -> None:
    """Azure SQL's serverless tier pauses when idle and takes a minute to wake up."""
    for attempt in range(1, attempts + 1):
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return
        except DBAPIError as exc:
            if attempt == attempts:
                raise
            log.warning(
                "Database not reachable yet (attempt %d of %d), retrying in %d s: %s",
                attempt, attempts, delay_seconds, exc.orig,
            )
            time.sleep(delay_seconds)


def create_tables(engine: Engine, script: Path) -> None:
    """Run a T-SQL script, splitting it into batches on GO lines like SSMS does."""
    batches = [batch.strip() for batch in re.split(r"^\s*GO\s*$", script.read_text(encoding="utf-8"), flags=re.M | re.I)]
    with engine.begin() as conn:
        for batch in batches:
            if batch:
                conn.exec_driver_sql(batch)
    log.info("Ran %s.", script.name)


def setup_logging(log_file: Path) -> None:
    log_file.parent.mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        handlers=[logging.FileHandler(log_file, encoding="utf-8"), logging.StreamHandler()],
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--landing-dir", type=Path, help="folder Power Automate saves into (default: LANDING_DIR in .env)")
    parser.add_argument("--create-tables", action="store_true", help="run sql/01_create_tables.sql and exit")
    args = parser.parse_args(argv)

    load_dotenv(PROJECT_DIR / ".env")
    setup_logging(PROJECT_DIR / "logs" / "loader.log")
    started = time.perf_counter()
    try:
        engine = make_engine()
        wait_for_database(engine)
        if args.create_tables:
            create_tables(engine, PROJECT_DIR / "sql" / "01_create_tables.sql")
            return 0
        landing_dir = args.landing_dir or os.environ.get("LANDING_DIR")
        if not landing_dir or not Path(landing_dir).is_dir():
            log.error("Landing folder not found: %s (set LANDING_DIR in .env)", landing_dir)
            return 1
        ok = run(engine, Path(landing_dir))
    except Exception:
        log.exception("Loader failed.")
        return 1
    log.info("Run finished in %.1f s.", time.perf_counter() - started)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
