"""Recompute the dashboard's numbers in pandas, straight from the raw files.

An independent check on powerbi/Customers.pq (the cleaning) and powerbi/measures.dax
(the analysis): the same rules written a second time, in a different tool. If a number
here disagrees with the dashboard, one of the two has a bug. Both break ties the same
way, so the numbers should match exactly, not just roughly.

    python tools/check_numbers.py "C:/Users/you/OneDrive/FinancialReports"   # latest day there
    python tools/check_numbers.py ../Data                                     # every file in a folder
"""

import argparse
import re
from pathlib import Path

import numpy as np
import pandas as pd

DATED = re.compile(r"^(\d{4}-\d{2}-\d{2})_.+\.(csv|xlsx)$", re.IGNORECASE)

NUMERIC = [
    "Age", "Annual_Income", "Monthly_Inhand_Salary", "Num_Bank_Accounts", "Num_Credit_Card",
    "Interest_Rate", "Num_of_Loan", "Delay_from_due_date", "Num_of_Delayed_Payment",
    "Changed_Credit_Limit", "Num_Credit_Inquiries", "Outstanding_Debt", "Credit_Utilization_Ratio",
    "Total_EMI_per_month", "Amount_invested_monthly", "Monthly_Balance",
]
VALID_RANGE = {
    "Age": (14, 56), "Num_Bank_Accounts": (0, 11), "Num_Credit_Card": (0, 11), "Interest_Rate": (1, 34),
    "Num_of_Loan": (0, 9), "Num_of_Delayed_Payment": (0, 28), "Num_Credit_Inquiries": (0, 17),
}
FILLER = {"Amount_invested_monthly": "__10000__", "Monthly_Balance": "__-333333333333333333333333333__"}
PLACEHOLDER = {"Occupation": "_______", "Credit_Mix": "_"}
FIXED_PER_CUSTOMER = [
    "Age", "Occupation", "Annual_Income", "Interest_Rate", "Num_of_Loan", "Type_of_Loan",
    "Credit_Mix", "Outstanding_Debt",
]
AGE_GROUPS = ["Teen", "Young Adult", "Old Adult", "Old1", "Old2"]
CREDIT_MIX = ["Good", "Standard", "Bad"]


def pick_files(folder: Path, day: str | None) -> tuple[list[Path], str | None]:
    """Every report file in the folder; if the names are dated, only the latest (or given) day's."""
    files = sorted(p for p in folder.iterdir() if p.suffix.lower() in {".csv", ".xlsx"} and not p.name.startswith("~$"))
    dated = {p: m.group(1) for p in files if (m := DATED.match(p.name))}
    if dated:
        day = day or max(dated.values())
        files = [p for p, d in dated.items() if d == day]
    return files, day


def read_raw(files: list[Path]) -> pd.DataFrame:
    frames = [
        pd.read_csv(p, dtype=str, keep_default_na=False, na_values=[""], encoding="utf-8-sig")
        if p.suffix.lower() == ".csv"
        else pd.read_excel(p, dtype=str, keep_default_na=False, na_values=[""])
        for p in files
    ]
    return pd.concat(frames, ignore_index=True)


def to_number(values: pd.Series) -> pd.Series:
    return pd.to_numeric(values.str.replace("_", "", regex=False), errors="coerce")


def most_common_per_customer(df: pd.DataFrame, col: str) -> pd.Series:
    """Each customer's most common non-null value; ties go to the larger value."""
    counts = df[["Customer_ID", col]].value_counts().reset_index(name="n")
    counts = counts.sort_values(["Customer_ID", "n", col], ascending=[True, False, False])
    winner = counts.drop_duplicates("Customer_ID").set_index("Customer_ID")[col]
    return df["Customer_ID"].map(winner)


def clean(raw: pd.DataFrame) -> pd.DataFrame:
    """The rules in powerbi/Customers.pq, in the same order."""
    df = raw.drop(columns=["SSN", "Name"])
    for col, filler in FILLER.items():
        df[col] = df[col].mask(df[col] == filler)
    for col in NUMERIC:
        df[col] = to_number(df[col])
    for col, (low, high) in VALID_RANGE.items():
        df[col] = df[col].where(df[col].between(low, high))
    for col, placeholder in PLACEHOLDER.items():
        df[col] = df[col].mask(df[col] == placeholder)
    df["Payment_Behaviour"] = df["Payment_Behaviour"].replace("!@9#%8", "Unknown")
    for col in FIXED_PER_CUSTOMER:
        df[col] = most_common_per_customer(df, col)
    return df


def add_model_columns(df: pd.DataFrame) -> pd.DataFrame:
    """The calculated columns in powerbi/measures.dax."""
    age = df["Age"]
    df["Age Group"] = np.select(
        [age.isna(), age < 19, age < 25, age < 35, age < 45], ["Unknown", *AGE_GROUPS[:4]], default="Old2"
    )
    df["Credit Score Num"] = df["Credit_Mix"].map({"Good": 3.0, "Standard": 1.5, "Bad": 0.0})
    return df


def ltv(grouped) -> pd.Series:
    return (
        0.30 * grouped["Annual_Income"].mean()
        - 0.15 * grouped["Delay_from_due_date"].mean()
        + 0.40 * grouped["Credit Score Num"].mean()
        + 0.075 * grouped["Amount_invested_monthly"].mean()
        + 0.075 * grouped["Monthly_Balance"].mean()
    )


def promotion(score: float) -> str:
    if pd.isna(score):
        return ""
    if score > 80000:
        return "30% off on online purchases + home loan at 4% interest"
    if score >= 60000:
        return "15% off on online purchases + 10000 worth gift hampers"
    if score >= 50000:
        return "Any loan at 5% interest rate"
    return "No promotion (LTV below 50,000)"


def loan_types(df: pd.DataFrame) -> pd.Series:
    """Customers holding each loan type (a customer with two auto loans counts once)."""
    per_customer = df[["Customer_ID", "Type_of_Loan"]].dropna().drop_duplicates()
    split = per_customer.assign(
        Loan_Type=per_customer["Type_of_Loan"].str.replace(", and ", ", ", regex=False).str.split(", ")
    ).explode("Loan_Type")
    split["Loan_Type"] = split["Loan_Type"].str.strip()
    return split.drop_duplicates(["Customer_ID", "Loan_Type"])["Loan_Type"].value_counts()


def junk_counts(raw: pd.DataFrame) -> dict[str, int]:
    """The junk-value query in sql/02_checks.sql, on the raw text."""
    age_text = raw["Age"].str.replace("_", "", regex=False)
    age = pd.to_numeric(age_text.where(age_text.str.fullmatch(r"\s*[+-]?\d+\s*")), errors="coerce")
    return {
        "income_with_underscore": int(raw["Annual_Income"].str.contains("_", regex=False, na=False).sum()),
        "age_out_of_range": int(((age < 14) | (age > 56)).sum()),
        "credit_mix_placeholder": int((raw["Credit_Mix"] == "_").sum()),
        "payment_behaviour_garbled": int((raw["Payment_Behaviour"] == "!@9#%8").sum()),
        "occupation_placeholder": int((raw["Occupation"] == "_______").sum()),
    }


def section(title: str) -> None:
    print(f"\n{title}\n{'-' * len(title)}")


def report(raw: pd.DataFrame, df: pd.DataFrame) -> None:
    print(f"Rows: {len(df):,}   Customers: {df['Customer_ID'].nunique():,}")

    section("Page 1 - KPI cards")
    raw_income = to_number(raw["Annual_Income"]).mean()
    print(f"Avg Annual Income        {df['Annual_Income'].mean():>12,.2f}   (raw, before cleaning: {raw_income:,.2f})")
    print(f"Avg Monthly Balance      {df['Monthly_Balance'].mean():>12,.2f}")
    print(f"Avg Delayed Payments     {df['Num_of_Delayed_Payment'].mean():>12,.2f}")
    print(f"Avg Credit Utilization   {df['Credit_Utilization_Ratio'].mean():>11,.2f}%")

    section("Page 1 - Age vs changed credit limit")
    pair = df[["Age", "Changed_Credit_Limit"]].dropna()
    by_age_limit = df.groupby("Age")["Changed_Credit_Limit"].mean()
    print(f"Age-CreditLimit Correlation (r)   {np.corrcoef(pair['Age'], pair['Changed_Credit_Limit'])[0, 1]:.4f}")
    print(f"Avg change per age ranges from {by_age_limit.min():.2f} (age {by_age_limit.idxmin():.0f})"
          f" to {by_age_limit.max():.2f} (age {by_age_limit.idxmax():.0f})")

    section("Page 1 - Customers per age group and credit mix")
    customers = df.drop_duplicates("Customer_ID")
    mix = pd.crosstab(customers["Age Group"], customers["Credit_Mix"]).reindex(index=AGE_GROUPS, columns=CREDIT_MIX)
    mix["Total"] = mix.sum(axis=1)
    print(mix.to_string())

    section("Page 1 - Payment behaviour per credit mix (records)")
    print(pd.crosstab(df["Payment_Behaviour"], df["Credit_Mix"]).reindex(columns=CREDIT_MIX).to_string())

    section("Page 2 - Avg credit inquiries, loans and credit cards per age group")
    by_group = df.groupby("Age Group")[["Num_Credit_Inquiries", "Num_of_Loan", "Num_Credit_Card"]].mean()
    by_group.columns = ["Avg Credit Inquiries", "Avg Loans", "Avg Credit Cards"]
    print(by_group.reindex(AGE_GROUPS).round(2).to_string())

    section("Per age - distribution, potential customers, LTV and promotions")
    grouped = df.groupby("Age")
    per_age = pd.DataFrame({
        "Customers": grouped["Customer_ID"].nunique(),
        "Avg Inquiries": grouped["Num_Credit_Inquiries"].mean(),
        "Avg Limit Chg": grouped["Changed_Credit_Limit"].mean(),
        "Avg Loans": grouped["Num_of_Loan"].mean(),
        "Avg Cards": grouped["Num_Credit_Card"].mean(),
        "LTV Score": ltv(grouped),
    })
    per_age["Potential"] = np.where(per_age["Avg Inquiries"] > 7.5, "Potential customer", "")
    per_age.index = per_age.index.astype(int)
    print(per_age.to_string(float_format=lambda v: f"{v:,.2f}"))
    potential = per_age.index[per_age["Avg Inquiries"] > 7.5].tolist()
    print(f"\nPotential customers (avg inquiries > 7.5): ages {potential}")
    print("Promotions:")
    print(per_age["LTV Score"].map(promotion).value_counts().to_string())

    section("Page 2 - Loan count distribution (customers holding each type)")
    print(loan_types(df).to_string())

    section("What cleaning changed")
    raw_inquiries = df.assign(Num_Credit_Inquiries=to_number(raw["Num_Credit_Inquiries"]))
    raw_potential = raw_inquiries.groupby("Age")["Num_Credit_Inquiries"].mean()
    print(f"With raw inquiry counts (up to {to_number(raw['Num_Credit_Inquiries']).max():,.0f}), "
          f"{(raw_potential > 7.5).sum()} ages clear 7.5 instead of {len(potential)}.")
    raw_incomes = df.assign(Annual_Income=to_number(raw["Annual_Income"]))
    raw_ltv = ltv(raw_incomes.groupby("Age"))
    print(f"With raw incomes (typos up to {to_number(raw['Annual_Income']).max():,.0f}), LTV per age ranges "
          f"{raw_ltv.min():,.0f}-{raw_ltv.max():,.0f} and {(raw_ltv >= 50000).sum()} ages land in a promotion tier;"
          f" cleaned, it ranges {per_age['LTV Score'].min():,.0f}-{per_age['LTV Score'].max():,.0f}.")

    section("Junk values in the raw files (sql/02_checks.sql, check 4)")
    for name, n in junk_counts(raw).items():
        print(f"{name:28s} {n:>7,}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("folder", type=Path, help="landing folder, or any folder of report files")
    parser.add_argument("--day", help="YYYY-MM-DD: check this day instead of the latest one")
    args = parser.parse_args()

    files, day = pick_files(args.folder, args.day)
    if not files:
        raise SystemExit(f"No report files found in {args.folder}" + (f" for {day}" if day else ""))
    print(f"Files: {len(files)}" + (f" from {day}" if day else ""))
    raw = read_raw(files)
    report(raw, add_model_columns(clean(raw)))


if __name__ == "__main__":
    pd.set_option("display.width", 200)
    main()
