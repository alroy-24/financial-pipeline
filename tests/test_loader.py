"""Loader tests, run against a throwaway database (see conftest.py).

    python -m pytest tests
"""

import logging

import pytest
from sqlalchemy import text

import load_to_sql
from conftest import count, sample_frame, write_day, write_file

ROWS_PER_FILE = len(sample_frame(1))


def test_complete_day_is_loaded(engine, landing):
    write_day(landing, "2026-10-04")

    assert load_to_sql.run(engine, landing) is True

    assert count(engine, "SELECT COUNT(*) FROM dbo.financial_data") == 25 * ROWS_PER_FILE
    assert count(engine, "SELECT COUNT(*) FROM dbo.load_log") == 25
    assert count(engine, "SELECT SUM(row_count) FROM dbo.load_log") == 25 * ROWS_PER_FILE
    assert count(engine, "SELECT COUNT(DISTINCT source_file) FROM dbo.financial_data") == 25
    assert count(engine, "SELECT DISTINCT load_date FROM dbo.financial_data") == "2026-10-04"
    # Raw values are kept exactly as they arrived, junk included; empty cells become NULL.
    with engine.connect() as conn:
        row = conn.execute(text(
            "SELECT Age, Annual_Income, Occupation, Payment_Behaviour FROM dbo.financial_data "
            "WHERE source_file = '2026-10-04_combined_part_2.xlsx' AND Month = 'February'"
        )).one()
        assert tuple(row) == ("-500", "19114.12_", "_______", "!@9#%8")
        assert conn.execute(text(
            "SELECT COUNT(*) FROM dbo.financial_data WHERE Month = 'March' AND Annual_Income IS NULL"
        )).scalar() == 25


def test_incomplete_day_waits_for_its_last_file(engine, landing, caplog):
    write_day(landing, "2026-10-04", files=24)

    assert load_to_sql.run(engine, landing) is False
    assert count(engine, "SELECT COUNT(*) FROM dbo.financial_data") == 0
    assert "24 of 25 files have arrived" in caplog.text

    write_day(landing, "2026-10-04", files=1, first=25)
    assert load_to_sql.run(engine, landing) is True
    assert count(engine, "SELECT COUNT(*) FROM dbo.load_log") == 25


def test_rerun_loads_nothing_twice(engine, landing, caplog):
    write_day(landing, "2026-10-04")
    assert load_to_sql.run(engine, landing) is True

    caplog.clear()
    with caplog.at_level(logging.INFO, logger="loader"):
        assert load_to_sql.run(engine, landing) is True
        assert load_to_sql.run(engine, landing) is True

    assert count(engine, "SELECT COUNT(*) FROM dbo.financial_data") == 25 * ROWS_PER_FILE
    assert count(engine, "SELECT COUNT(*) FROM dbo.load_log") == 25
    assert "Nothing new to load." in caplog.text


def test_bad_file_rolls_back_its_whole_day(engine, landing, caplog, monkeypatch):
    # A file with a missing and an extra column: the error names both, nothing is kept.
    write_day(landing, "2026-10-04", files=24)
    broken = sample_frame(25).drop(columns=["Credit_Mix"]).assign(Notes="x")
    write_file(landing, "2026-10-04_combined_part_25.csv", broken)

    assert load_to_sql.run(engine, landing) is False
    assert "Missing: Credit_Mix. Unexpected: Notes." in caplog.text
    assert count(engine, "SELECT COUNT(*) FROM dbo.financial_data") == 0
    assert count(engine, "SELECT COUNT(*) FROM dbo.load_log") == 0

    # A database failure halfway through the day: files 1-9 were already inserted,
    # and the rollback must remove them too.
    write_day(landing, "2026-10-05")
    real_insert_file = load_to_sql.insert_file
    inserted = []

    def fail_on_tenth_file(conn, file_name, *args):
        if len(inserted) == 9:
            raise load_to_sql.SQLAlchemyError("simulated failure")
        real_insert_file(conn, file_name, *args)
        inserted.append(file_name)

    monkeypatch.setattr(load_to_sql, "insert_file", fail_on_tenth_file)
    assert load_to_sql.run(engine, landing) is False
    assert len(inserted) == 9
    assert "nothing from this day was kept" in caplog.text
    assert count(engine, "SELECT COUNT(*) FROM dbo.financial_data") == 0
    assert count(engine, "SELECT COUNT(*) FROM dbo.load_log") == 0

    # Once the cause is fixed, the next run loads the day normally.
    monkeypatch.setattr(load_to_sql, "insert_file", real_insert_file)
    write_file(landing, "2026-10-04_combined_part_25.csv", sample_frame(25))
    assert load_to_sql.run(engine, landing) is True
    assert count(engine, "SELECT COUNT(*) FROM dbo.load_log") == 50


def test_view_shows_only_the_latest_day(engine, landing):
    write_day(landing, "2026-10-05")
    assert load_to_sql.run(engine, landing) is True
    # An older day that arrives late is kept for history but doesn't replace the latest.
    write_day(landing, "2026-10-04", first=101)
    assert load_to_sql.run(engine, landing) is True

    assert count(engine, "SELECT COUNT(*) FROM dbo.financial_data") == 2 * 25 * ROWS_PER_FILE
    assert count(engine, "SELECT COUNT(*) FROM dbo.financial_data_latest") == 25 * ROWS_PER_FILE
    assert count(engine, "SELECT DISTINCT load_date FROM dbo.financial_data_latest") == "2026-10-05"


@pytest.mark.parametrize("stray_name", [
    "image001.png",                       # email signature image
    "combined_part_1.csv",                # no date in front
    "2026-13-45_combined_part_1.csv",     # not a real date
    "~$2026-10-04_combined_part_2.xlsx",  # Excel lock file
    "2026-10-04_notes.txt",               # dated, but not .csv/.xlsx
])
def test_stray_files_are_ignored(engine, landing, stray_name):
    write_day(landing, "2026-10-04")
    (landing / stray_name).write_text("not a report")
    (landing / "subfolder").mkdir()

    assert load_to_sql.run(engine, landing) is True
    assert count(engine, "SELECT COUNT(*) FROM dbo.load_log") == 25
    assert count(engine, f"SELECT COUNT(*) FROM dbo.load_log WHERE file_name = '{stray_name}'") == 0
