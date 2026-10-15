-- Data-quality checks. Run after a load (Azure portal query editor, SSMS or VS Code).


-- 1. Did each day load completely?  Good: 25 files per load_date.
SELECT load_date,
       COUNT(*)       AS files,
       SUM(row_count) AS rows_loaded
FROM dbo.load_log
GROUP BY load_date
ORDER BY load_date DESC;


-- 2. What Power BI will see.  Good: ~150,000 rows and ~12,500 customers, one load_date.
SELECT COUNT(*)                    AS rows_in_view,
       COUNT(DISTINCT Customer_ID) AS customers,
       MIN(load_date)              AS load_date
FROM dbo.financial_data_latest;


-- 3. What did the loader actually do?  The 30 most recent files, with row counts.
SELECT TOP (30) file_name, load_date, row_count, loaded_at
FROM dbo.load_log
ORDER BY loaded_at DESC, file_name;


-- 4. Junk values in the latest day, one count per problem column, in a single pass.
--    If a count jumps, or a new kind of junk value appears, check that the cleaning in
--    powerbi/Customers.pq still covers it before trusting the dashboard.
--    In LIKE, _ is a wildcard for "any one character"; [_] means a literal underscore.
--    TRY_CAST returns NULL instead of failing, and a NULL fails NOT BETWEEN, so ages that
--    aren't numbers at all are not counted here (add OR TRY_CAST(...) IS NULL for those).
SELECT
    SUM(CASE WHEN Annual_Income LIKE '%[_]%' THEN 1 ELSE 0 END)   AS income_with_underscore,
    SUM(CASE WHEN TRY_CAST(REPLACE(Age, '_', '') AS INT) NOT BETWEEN 14 AND 56 THEN 1 ELSE 0 END) AS age_out_of_range,
    SUM(CASE WHEN Credit_Mix = '_' THEN 1 ELSE 0 END)             AS credit_mix_placeholder,
    SUM(CASE WHEN Payment_Behaviour = '!@9#%8' THEN 1 ELSE 0 END) AS payment_behaviour_garbled,
    SUM(CASE WHEN Occupation = '_______' THEN 1 ELSE 0 END)       AS occupation_placeholder
FROM dbo.financial_data_latest;


-- Undo a day, so it can be reloaded after a file is fixed. The loader decides what to
-- load from load_log, so deleting the day's log entries is what lets it pick those files
-- up again. Set the date, then select the block and run it.
--
-- DECLARE @day DATE = '2026-10-15';
-- BEGIN TRANSACTION;
--     DELETE FROM dbo.financial_data WHERE load_date = @day;
--     DELETE FROM dbo.load_log       WHERE load_date = @day;
-- COMMIT;
