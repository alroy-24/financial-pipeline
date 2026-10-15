-- Storage layer for the daily financial reports (Azure SQL Database).
--
-- Run once, either with  python load_to_sql.py --create-tables  or in SSMS / VS Code
-- (the mssql extension). It is safe to run again: nothing that exists is recreated.
--
--   dbo.financial_data         every day's rows exactly as they arrived (all text)
--   dbo.load_log               one row per loaded file; what makes re-runs safe
--   dbo.financial_data_latest  the latest day only; this is what Power BI reads


-- Staging table. Every source column is text, so a value like '102594.9_' can never
-- fail the load. Cleaning and typing happen downstream, in Power Query.
IF OBJECT_ID('dbo.financial_data', 'U') IS NULL
CREATE TABLE dbo.financial_data (
    ID                        NVARCHAR(100) NULL,
    Customer_ID               NVARCHAR(100) NULL,
    Month                     NVARCHAR(100) NULL,
    Name                      NVARCHAR(100) NULL,
    Age                       NVARCHAR(100) NULL,
    SSN                       NVARCHAR(100) NULL,
    Occupation                NVARCHAR(100) NULL,
    Annual_Income             NVARCHAR(100) NULL,
    Monthly_Inhand_Salary     NVARCHAR(100) NULL,
    Num_Bank_Accounts         NVARCHAR(100) NULL,
    Num_Credit_Card           NVARCHAR(100) NULL,
    Interest_Rate             NVARCHAR(100) NULL,
    Num_of_Loan               NVARCHAR(100) NULL,
    Type_of_Loan              NVARCHAR(400) NULL,
    Delay_from_due_date       NVARCHAR(100) NULL,
    Num_of_Delayed_Payment    NVARCHAR(100) NULL,
    Changed_Credit_Limit      NVARCHAR(100) NULL,
    Num_Credit_Inquiries      NVARCHAR(100) NULL,
    Credit_Mix                NVARCHAR(100) NULL,
    Outstanding_Debt          NVARCHAR(100) NULL,
    Credit_Utilization_Ratio  NVARCHAR(100) NULL,
    Credit_History_Age        NVARCHAR(100) NULL,
    Payment_of_Min_Amount     NVARCHAR(100) NULL,
    Total_EMI_per_month       NVARCHAR(100) NULL,
    Amount_invested_monthly   NVARCHAR(100) NULL,
    Payment_Behaviour         NVARCHAR(100) NULL,
    Monthly_Balance           NVARCHAR(100) NULL,
    Credit_Score              NVARCHAR(100) NULL,
    source_file               NVARCHAR(260) NOT NULL,  -- the landed file each row came from
    load_date                 DATE          NOT NULL   -- the day the file arrived (from its name)
);
GO

-- The view filters on load_date = MAX(load_date) and the table grows by ~150,000 rows
-- a day. Clustering on load_date keeps each day's rows together, so finding the latest
-- day and reading it is a seek over that day's rows, not a scan of the whole history.
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'ix_financial_data_load_date'
               AND object_id = OBJECT_ID('dbo.financial_data'))
CREATE CLUSTERED INDEX ix_financial_data_load_date ON dbo.financial_data (load_date);
GO

-- Load audit log. The loader skips any file already listed here, and the primary key
-- stops the same file from ever being logged twice.
IF OBJECT_ID('dbo.load_log', 'U') IS NULL
CREATE TABLE dbo.load_log (
    file_name  NVARCHAR(260) NOT NULL CONSTRAINT pk_load_log PRIMARY KEY,
    load_date  DATE          NOT NULL,
    row_count  INT           NOT NULL,
    loaded_at  DATETIME2(0)  NOT NULL  -- UTC
);
GO

-- Each day's files are a full snapshot (every customer, all twelve months), so Power BI
-- must see exactly one day; reading the whole table would count every customer once per
-- day loaded. "Latest" means the newest load_date, not the most recently loaded files.
CREATE OR ALTER VIEW dbo.financial_data_latest AS
SELECT
    ID, Customer_ID, Month, Name, Age, SSN, Occupation, Annual_Income,
    Monthly_Inhand_Salary, Num_Bank_Accounts, Num_Credit_Card, Interest_Rate,
    Num_of_Loan, Type_of_Loan, Delay_from_due_date, Num_of_Delayed_Payment,
    Changed_Credit_Limit, Num_Credit_Inquiries, Credit_Mix, Outstanding_Debt,
    Credit_Utilization_Ratio, Credit_History_Age, Payment_of_Min_Amount,
    Total_EMI_per_month, Amount_invested_monthly, Payment_Behaviour,
    Monthly_Balance, Credit_Score,
    source_file, load_date
FROM dbo.financial_data
WHERE load_date = (SELECT MAX(load_date) FROM dbo.financial_data);
GO
