# Financial Reporting Automation & Customer Analytics Pipeline

A team receives about 25 report files by email every afternoon and used to download, merge and
clean them by hand to build an evening dashboard. This pipeline does it with no manual steps:

```
Outlook          the day's 25 files arrive as email attachments
   │
Power Automate   saves each attachment into OneDrive as YYYY-MM-DD_<name>
   │
OneDrive         the landing folder, synced onto the laptop
   │
load_to_sql.py   checks all 25 files arrived with the 28 expected columns, then loads
   │             them into Azure SQL in one transaction and logs each file
Azure SQL        keeps every day's raw rows; Power BI reads a view of the latest day
   │
Power Query      cleans and types the rows as they load into the model
   │
DAX              all the analysis: age groups, loan-outreach rule, LTV promotions
   │
Power BI         two-page dashboard, refreshed daily
```

`tools/check_numbers.py` recomputes the dashboard's numbers in pandas, straight from the raw
files, as an independent check on the Power Query cleaning and the DAX.

## What's where

| Path | What it is |
|---|---|
| `load_to_sql.py` | The loader. Run on a schedule by Windows Task Scheduler |
| `sql/01_create_tables.sql` | Storage layer: `dbo.financial_data` (raw staging table, clustered on `load_date`), `dbo.load_log` (one row per loaded file), `dbo.financial_data_latest` (the view Power BI reads) |
| `sql/02_checks.sql` | Data-quality checks to run after a load, plus an undo for reloading a day |
| `power_automate/FLOW_SETUP.md` | How to build the Outlook → OneDrive flow |
| `powerbi/Customers.pq` | Power Query: cleaning and typing |
| `powerbi/LoanTypes.pq` | Power Query: one row per customer per loan type |
| `powerbi/measures.dax` | DAX calculated columns and measures |
| `powerbi/REPORT_BUILD.md` | How to build the two report pages, and the numbers to expect |
| `tools/check_numbers.py` | The independent pandas recalculation |
| `tools/simulate_delivery.py` | Stands in for Power Automate: copies files into the landing folder with a date in front |
| `tools/register_task.ps1` | Registers the loader's daily runs in Task Scheduler |
| `tests/` | Six loader tests against a throwaway database |

## Setup

### 1. Azure SQL

1. In the Azure portal, create a **SQL Database** and apply the **free offer** (when the free
   monthly limit is reached, choose to auto-pause until next month, so it never bills).
2. Create a new server with **SQL authentication** and an admin login.
3. Networking: **Public endpoint**, **Add current client IP address**: Yes, and
   **Allow Azure services and resources to access this server**: Yes. The Power BI service
   needs that for its scheduled refresh.

Optional but better: give the loader and Power BI their own logins instead of the admin one.
Run this in the database (Query editor in the portal), with your own passwords:

```sql
CREATE USER loader WITH PASSWORD = '<strong password>';
GRANT SELECT, INSERT ON dbo.financial_data TO loader;
GRANT SELECT, INSERT ON dbo.load_log TO loader;

CREATE USER powerbi_reader WITH PASSWORD = '<strong password>';
GRANT SELECT ON dbo.financial_data_latest TO powerbi_reader;
```

(Create the tables first, step 3 below, as the admin.)

### 2. Laptop

1. Install **ODBC Driver 18 for SQL Server** (Microsoft's download page: "Download ODBC Driver
   for SQL Server").
2. `pip install -r requirements.txt`
3. Copy `.env.example` to `.env` and fill it in. `.env` is git-ignored; the password never goes
   in the code.
4. Set up the OneDrive sync for the landing folder: see the end of
   [`power_automate/FLOW_SETUP.md`](power_automate/FLOW_SETUP.md).

### 3. Create the tables

```
python load_to_sql.py --create-tables
```

(Or run `sql/01_create_tables.sql` in SSMS or VS Code's mssql extension. The Azure portal's
query editor doesn't understand `GO`.)

### 4. Power Automate

Follow [`power_automate/FLOW_SETUP.md`](power_automate/FLOW_SETUP.md).

### 5. Try a load before the flow is live

```
python tools/simulate_delivery.py ../Data "C:\Users\you\OneDrive - YourOrg\FinancialReports"
python load_to_sql.py
```

The log should end with `loaded 25 files, 150000 rows`. Then run `sql/02_checks.sql`.

### 6. Schedule the loader

```
powershell -ExecutionPolicy Bypass -File tools\register_task.ps1
```

This runs the loader daily at 3:30, 4:30, 5:30 and 6:30 PM. Extra runs are harmless: loaded
files are skipped, and a day only loads once all 25 files are in.

### 7. Power BI

Follow [`powerbi/REPORT_BUILD.md`](powerbi/REPORT_BUILD.md). The scheduled refresh runs at
7 PM, after the loader's last run.

## How the loader behaves

| Situation | What happens |
|---|---|
| All 25 of a day's files are in | Loaded in one transaction: 25 files, ~150,000 rows. Each row is tagged with `source_file` and `load_date` |
| Only some have arrived | Not loaded: `ERROR 2026-10-04: 24 of 25 files have arrived. Waiting for the rest.` The run exits with code 1, and the next run tries again |
| A file has missing or extra columns, or can't be read | The whole day is not loaded, and the error names the file and the columns |
| A database error partway through | The transaction rolls back; nothing from that day is kept |
| The loader runs again | Files already in `dbo.load_log` are skipped: `Nothing new to load.` |
| Other files in the folder (images, undated names) | Ignored, with a warning |

Every run appends to `logs/loader.log`. In Task Scheduler, a failed run shows **Last Run
Result** `0x1`.

**Reloading a day** (for example after a corrected file arrives): run the undo at the bottom of
`sql/02_checks.sql` for that date. It deletes the day's rows and its `load_log` entries, and the
next run loads the day again.

## Cleaning rules (`powerbi/Customers.pq`)

Each customer appears once a month for twelve months, so bad values can be repaired from the
same customer's other months instead of being guessed.

1. **SSN and Name are dropped.** The dashboard doesn't need personal data.
2. **Text to numbers.** Stray underscores are stripped (`102594.9_` → 102594.9). Anything still
   unreadable becomes blank.
3. **Impossible values become blank:** age outside 14–56, credit inquiries outside 0–17, loans
   outside 0–9, bank accounts or credit cards outside 0–11, interest rate outside 1–34, delayed
   payments outside 0–28.
4. **Filler values become blank:** `__10000__` invested, and a balance of
   `-333333333333333333333333333`.
5. **Fixed attributes take the customer's most common valid value** across their twelve months:
   age, occupation, annual income, interest rate, number of loans, loan types, credit mix and
   outstanding debt. That fixes the 5,615-year-old, the typo incomes in the millions, and fills
   the `_______` / `_` placeholders. Ties go to the larger value. Columns that really do change
   month to month (inquiries, cards, balances, delays) are not filled: a bad value there stays
   blank and the averages skip it.
6. **Garbled payment behaviour** (`!@9#%8`) becomes `Unknown`. It changes month to month, so it
   can't be filled.

## Tests

```
python -m pytest tests
```

Six tests run the loader against a throwaway SQLite database (attached as `dbo`, so the
loader's SQL is unchanged). They cover a complete day, an incomplete day waiting for its last
file, re-runs, a bad file and a mid-load database failure rolling back the whole day, the
latest-day view, and stray files.
