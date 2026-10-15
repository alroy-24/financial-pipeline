// LoanTypes: one row per customer per loan type they hold, for the
// "Loan Count Distribution" chart. Built on the cleaned Customers query.
//
// Power BI Desktop: Blank query > Advanced Editor, paste this, name the query "LoanTypes".
let
    Source = Customers,
    PerCustomer = Table.Distinct(Table.SelectColumns(Source, {"Customer_ID", "Type_of_Loan"})),
    WithLoans = Table.SelectRows(PerCustomer, each [Type_of_Loan] <> null),

    // "Auto Loan, Personal Loan, and Home Equity Loan" -> {"Auto Loan", "Personal Loan", "Home Equity Loan"}
    AsLists = Table.TransformColumns(WithLoans, {
        {"Type_of_Loan", each List.Transform(Text.Split(Text.Replace(_, ", and ", ", "), ", "), Text.Trim)}
    }),
    OneRowPerType = Table.ExpandListColumn(AsLists, "Type_of_Loan"),
    Renamed = Table.RenameColumns(OneRowPerType, {{"Type_of_Loan", "Loan_Type"}}),

    // A customer holding two auto loans counts once.
    Distinct = Table.Distinct(Renamed),
    Typed = Table.TransformColumnTypes(Distinct, {{"Customer_ID", type text}, {"Loan_Type", type text}})
in
    Typed
