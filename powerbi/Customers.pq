// Customers: the latest day's rows from Azure SQL, cleaned and typed on the way into the model.
//
// Power BI Desktop: Get data > Blank query > Advanced Editor, paste this, name the query
// "Customers", and put your own server and database on the Source line.
//
// tools/check_numbers.py applies the same rules in pandas. Change a rule here, change it there.
let
    Source = Sql.Database("your-server.database.windows.net", "your-database"),
    Raw = Source{[Schema = "dbo", Item = "financial_data_latest"]}[Data],

    // 1. Personal data the dashboard doesn't need never enters the model.
    NoPersonalData = Table.RemoveColumns(Raw, {"SSN", "Name"}),

    // 2. Text to numbers. Stray underscores are stripped ("102594.9_" -> 102594.9) and
    //    anything still unreadable becomes null. "en-US" so a decimal point parses the
    //    same way whatever the machine's regional settings are.
    ToNumber = (value as nullable text) as nullable number =>
        if value = null then null
        else try Number.FromText(Text.Remove(value, "_"), "en-US") otherwise null,

    // 3. Impossible values (an age of 5,615, 2,000 credit inquiries) become null.
    Within = (low as number, high as number) as function =>
        (value as nullable text) as nullable number =>
            let n = ToNumber(value)
            in if n <> null and n >= low and n <= high then n else null,

    // 4. Filler values become null. Matched as raw text, because once its underscores
    //    are stripped "__10000__" would look like a real 10,000.
    Unless = (filler as text) as function =>
        (value as nullable text) as nullable number =>
            if value = filler then null else ToNumber(value),

    Numbers = Table.TransformColumns(NoPersonalData, {
        {"Age",                      Within(14, 56), Int64.Type},
        {"Annual_Income",            ToNumber,       type number},
        {"Monthly_Inhand_Salary",    ToNumber,       type number},
        {"Num_Bank_Accounts",        Within(0, 11),  Int64.Type},
        {"Num_Credit_Card",          Within(0, 11),  Int64.Type},
        {"Interest_Rate",            Within(1, 34),  Int64.Type},
        {"Num_of_Loan",              Within(0, 9),   Int64.Type},
        {"Delay_from_due_date",      ToNumber,       Int64.Type},
        {"Num_of_Delayed_Payment",   Within(0, 28),  Int64.Type},
        {"Changed_Credit_Limit",     ToNumber,       type number},
        {"Num_Credit_Inquiries",     Within(0, 17),  Int64.Type},
        {"Outstanding_Debt",         ToNumber,       type number},
        {"Credit_Utilization_Ratio", ToNumber,       type number},
        {"Total_EMI_per_month",      ToNumber,       type number},
        {"Amount_invested_monthly",  Unless("__10000__"), type number},
        {"Monthly_Balance",          Unless("__-333333333333333333333333333__"), type number}
    }),

    // Placeholder categories become null (filled in step 5). Payment behaviour changes
    // month to month, so a garbled value can't be filled from the customer's other
    // months; it is labelled "Unknown" rather than guessed.
    Categories = Table.TransformColumns(Numbers, {
        {"Occupation",        each if _ = "_______" then null else _, type text},
        {"Credit_Mix",        each if _ = "_" then null else _, type text},
        {"Payment_Behaviour", each if _ = "!@9#%8" then "Unknown" else _, type text}
    }),

    // 5. Attributes that are fixed per customer take the customer's most common valid
    //    value across their twelve monthly rows. That repairs typos (an income in the
    //    millions) and fills the nulls left by steps 2-4. Age is included so each
    //    customer has a single age. Ties go to the larger value, so the result never
    //    depends on row order. Columns that really do change month to month (inquiries,
    //    cards, balances...) are not filled: a bad value there stays null.
    FixedPerCustomer = {
        "Age", "Occupation", "Annual_Income", "Interest_Rate", "Num_of_Loan",
        "Type_of_Loan", "Credit_Mix", "Outstanding_Debt"
    },
    MostCommon = (values as list) as any =>
        let present = List.RemoveNulls(values)
        in if List.IsEmpty(present) then null else List.Max(List.Modes(present)),

    Cleaned = Table.Buffer(Categories),
    PerCustomer = Table.Group(
        Cleaned,
        {"Customer_ID"},
        List.Transform(FixedPerCustomer, (name) =>
            {name, (rows) => MostCommon(Table.Column(rows, name)), Type.TableColumn(Value.Type(Cleaned), name)})
    ),
    Joined = Table.Join(
        Table.RemoveColumns(Cleaned, FixedPerCustomer), "Customer_ID",
        Table.RenameColumns(PerCustomer, {{"Customer_ID", "Customer_ID_key"}}), "Customer_ID_key",
        JoinKind.LeftOuter
    ),
    Filled = Table.ReorderColumns(Table.RemoveColumns(Joined, {"Customer_ID_key"}), Table.ColumnNames(Cleaned)),

    Typed = Table.TransformColumnTypes(Filled, {
        {"ID", type text}, {"Customer_ID", type text}, {"Month", type text},
        {"Type_of_Loan", type text}, {"Credit_History_Age", type text},
        {"Payment_of_Min_Amount", type text}, {"Credit_Score", type text},
        {"source_file", type text}, {"load_date", type date}
    }, "en-US")
in
    Typed
