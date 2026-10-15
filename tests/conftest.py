"""Test fixtures: a throwaway database and a fake landing folder.

The database is SQLite with a second database attached as "dbo", so the loader's
dbo.financial_data / dbo.load_log / dbo.financial_data_latest names work unchanged.
SQLITE_SCHEMA mirrors sql/01_create_tables.sql.
"""

import sys
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import create_engine, event, text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from load_to_sql import EXPECTED_COLUMNS  # noqa: E402

SQLITE_SCHEMA = [
    "CREATE TABLE dbo.financial_data ("
    + ", ".join(f'"{name}" TEXT' for name in EXPECTED_COLUMNS)
    + ", source_file TEXT NOT NULL, load_date DATE NOT NULL)",
    "CREATE INDEX dbo.ix_financial_data_load_date ON financial_data (load_date)",
    "CREATE TABLE dbo.load_log (file_name TEXT PRIMARY KEY, load_date DATE NOT NULL,"
    " row_count INTEGER NOT NULL, loaded_at TIMESTAMP NOT NULL)",
    "CREATE VIEW dbo.financial_data_latest AS SELECT * FROM financial_data"
    " WHERE load_date = (SELECT MAX(load_date) FROM financial_data)",
]

# Three monthly rows for one customer, with the kinds of junk the real files contain.
SAMPLE_ROWS = [
    {"Customer_ID": "CUS_0xd40", "Month": "January", "Age": "23", "Annual_Income": "19114.12",
     "Occupation": "Scientist", "Credit_Mix": "Good", "Payment_Behaviour": "High_spent_Small_value_payments"},
    {"Customer_ID": "CUS_0xd40", "Month": "February", "Age": "-500", "Annual_Income": "19114.12_",
     "Occupation": "_______", "Credit_Mix": "_", "Payment_Behaviour": "!@9#%8"},
    {"Customer_ID": "CUS_0xd40", "Month": "March", "Age": "23", "Annual_Income": "",
     "Occupation": "Scientist", "Credit_Mix": "Good", "Payment_Behaviour": "Low_spent_Large_value_payments"},
]


@pytest.fixture
def engine(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'main.db').as_posix()}")
    dbo_file = (tmp_path / "dbo.db").as_posix()

    @event.listens_for(engine, "connect")
    def attach_dbo(dbapi_connection, _):
        dbapi_connection.execute(f"ATTACH DATABASE '{dbo_file}' AS dbo")

    with engine.begin() as conn:
        for statement in SQLITE_SCHEMA:
            conn.execute(text(statement))
    yield engine
    engine.dispose()


@pytest.fixture
def landing(tmp_path):
    folder = tmp_path / "FinancialReports"
    folder.mkdir()
    return folder


def sample_frame(file_number: int) -> pd.DataFrame:
    rows = [{name: "" for name in EXPECTED_COLUMNS} | row for row in SAMPLE_ROWS]
    df = pd.DataFrame(rows, columns=EXPECTED_COLUMNS)
    df["ID"] = [f"0x{file_number:03d}{i}" for i in range(len(df))]
    return df


def write_file(folder: Path, name: str, df: pd.DataFrame) -> Path:
    path = folder / name
    if path.suffix == ".csv":
        df.to_csv(path, index=False)
    else:
        df.to_excel(path, index=False)
    return path


def write_day(folder: Path, day: str, files: int = 25, first: int = 1) -> list[Path]:
    """Land one day's report files the way Power Automate names them; every other one is .xlsx."""
    return [
        write_file(folder, f"{day}_combined_part_{n}.{'xlsx' if n % 2 == 0 else 'csv'}", sample_frame(n))
        for n in range(first, first + files)
    ]


def count(engine, sql: str):
    with engine.connect() as conn:
        return conn.execute(text(sql)).scalar()
