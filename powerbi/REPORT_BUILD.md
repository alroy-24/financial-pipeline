# Building the Power BI report

Two pages on top of the latest day in Azure SQL. Before you start, load at least one day and
check that `sql/02_checks.sql` shows 25 files for it.

## 1. Queries

1. Power BI Desktop → **Get data** → **Blank query** → **Advanced Editor**. Paste
   [`Customers.pq`](Customers.pq), replace the server and database names on the `Source`
   line, and click **Done**. Rename the query `Customers`.
   When asked for credentials, choose **Database** and enter the SQL login (see the README's
   optional read-only login).
2. **New Source** → **Blank query** again, paste [`LoanTypes.pq`](LoanTypes.pq), and rename it
   `LoanTypes`.
3. **Close & Apply**. Customers should have 150,000 rows and LoanTypes about 35,000.

The two tables stay unrelated. The loan chart only uses LoanTypes, and everything else only
uses Customers.

## 2. Model

In the **Data** pane, select the Customers table.

1. **Calculated columns.** Table tools → **New column**, once for each of the three columns
   at the top of [`measures.dax`](measures.dax): `Age Group`, `Age Group Order`,
   `Credit Score Num`.
2. **Sort the age groups.** Select `Age Group` → Column tools → **Sort by column** →
   `Age Group Order`. Without this, charts list the groups alphabetically.
3. **Measures.** Table tools → **New measure**, once for each measure in `measures.dax`.
4. **Formats** (Measure tools):

   | Measure | Format |
   |---|---|
   | Avg Annual Income | Currency, 0 decimals |
   | Avg Monthly Balance | Currency, 2 decimals |
   | Avg Delayed Payments | Decimal, 1 decimal |
   | Avg Credit Utilization | Percentage, 1 decimal |
   | Age-CreditLimit Correlation | Decimal, 2 decimals |
   | LTV Score | Whole number, thousands separator |
   | Avg Credit Inquiries, Avg Loans, Avg Credit Cards, Avg Changed Credit Limit | Decimal, 2 decimals |

5. Select `Age` → Column tools → **Summarization: Don't summarize**, so it works as an axis.

## 3. Page 1: "USA Financial Data"

Rename the page `USA Financial Data`.

| Visual (title) | Type | Fields |
|---|---|---|
| 4 KPI cards, down the left | Card | one each: `Avg Annual Income`, `Avg Monthly Balance`, `Avg Delayed Payments`, `Avg Credit Utilization` |
| Relation of Age with Changed Credit Limit | Line chart | X-axis `Age`, Y-axis `Avg Changed Credit Limit` |
| Age vs credit limit correlation | Card | `Age-CreditLimit Correlation` |
| Distribution (Frequency) of Age | Column chart | X-axis `Age`, Y-axis `Customer Count` |
| Credit Mix for each Age Group | Clustered bar chart | Y-axis `Age Group`, X-axis `Customer Count`, Legend `Credit_Mix` |
| Payment Behaviour as per Credit Mix | Clustered column chart | X-axis `Credit_Mix`, Y-axis `Records`, Legend `Payment_Behaviour` |

## 4. Page 2: "Targeting"

| Visual (title) | Type | Fields |
|---|---|---|
| Average Credit Inquiries for each Age Group | Clustered bar chart | Y-axis `Age Group`, X-axis `Avg Credit Inquiries` |
| Potential Customers | Table | `Age`, `Avg Credit Inquiries`, `Potential Customer`. In the Filters pane, filter this visual on **Avg Credit Inquiries is greater than 7.5** |
| LTV Score Based Promotions | Table | `Age`, `LTV Score`, `Promotion` |
| Loan Count Distribution | Clustered column chart | X-axis `LoanTypes[Loan_Type]`, Y-axis `Customers With Loan Type`, sorted descending |
| Average Loans and Credit Cards as per Age | Line chart | X-axis `Age`, Y-axis `Avg Loans` and `Avg Credit Cards` |

## 5. Check the numbers

Run the pandas recalculation on the same day's files and compare:

```
python tools/check_numbers.py "C:\Users\you\OneDrive - YourOrg\FinancialReports"
```

Both apply the same rules and break ties the same way, so the numbers should match exactly. If
they don't, one of them has a bug. With the sample files in `../Data`, you should see:

| | Value |
|---|---|
| Customers | 12,500 (150,000 records) |
| Avg Annual Income | $50,505 |
| Avg Monthly Balance | $402.72 |
| Avg Delayed Payments | 13.4 |
| Avg Credit Utilization | 32.3% |
| Age-CreditLimit Correlation | −0.16 |
| Potential Customers | 4 rows: ages 14–17 |
| LTV Score | 10,769 to 20,373 across ages; every row "No promotion" |
| Loan types | Auto Loan lowest (3,820), Payday Loan highest (3,993) |

## 6. Publish and schedule the refresh

1. **Publish** (Home → Publish) to a workspace.
2. In the Power BI service, open the semantic model's **Settings**:
   - **Data source credentials** → Edit → Authentication method **Basic**, with the SQL login.
     Azure SQL is a cloud source, so no gateway is needed. It does need "Allow Azure services
     and resources to access this server" switched on in the SQL server's Networking page.
   - **Scheduled refresh** → On, daily at **7:00 PM** in your time zone, after the loader's
     last run at 6:30.
3. After the first scheduled refresh, check **Refresh history** shows it completed.
