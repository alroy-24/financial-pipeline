# Power Automate flow: save the report attachments into OneDrive

The flow's only job is moving files. Every email from the survey team that has attachments
gets each `.csv` / `.xlsx` attachment saved into the OneDrive folder `/FinancialReports`, with
the date the email arrived in front of the name:

```
combined_part_1.xlsx  ->  /FinancialReports/2026-10-04_combined_part_1.xlsx
```

That date is how the loader knows which files belong to which day. The flow never touches the
database and does no cleaning.

You need a Microsoft 365 work or school account (for the Office 365 Outlook and OneDrive for
Business connectors). If your account offers the Outlook.com and OneDrive (personal)
connectors instead, the steps are the same.

## Build it

1. Go to <https://make.powerautomate.com> → **Create** → **Automated cloud flow**.
   Name it `Save financial reports` and pick the trigger **When a new email arrives (V3)**
   (Office 365 Outlook).

2. Trigger settings (open **Advanced parameters**):
   | Setting | Value |
   |---|---|
   | Folder | Inbox |
   | Include Attachments | Yes |
   | Only with Attachments | Yes |
   | From | the survey team's address(es), separated by `;` |

   Set **From** (or a **Subject Filter**). Without it, every spreadsheet anyone emails you
   lands in the folder and counts toward the day's 25 files.

3. Add an action: **Control → Apply to each**. For its input, choose the dynamic content
   **Attachments**. The loop gets a name such as `Apply_to_each` (classic designer) or
   `For_each` (new designer). The expressions below use `Apply_to_each`; change it to your
   loop's name.

4. Inside the loop, add **Control → Condition** to skip signature images and other
   non-report attachments. Choose **Expression** on the left side:

   ```
   or(endsWith(toLower(items('Apply_to_each')?['name']), '.csv'), endsWith(toLower(items('Apply_to_each')?['name']), '.xlsx'))
   ```

   and set it to **is equal to** `true`.

5. In the condition's **True** branch, add **OneDrive for Business → Create file**:
   | Field | Value |
   |---|---|
   | Folder Path | `/FinancialReports` (create the folder in OneDrive first) |
   | File Name | expression below |
   | File Content | dynamic content **Attachments Content** |

   File Name expression, with your own time zone:

   ```
   concat(convertFromUtc(triggerOutputs()?['body/receivedDateTime'], 'India Standard Time', 'yyyy-MM-dd'), '_', items('Apply_to_each')?['name'])
   ```

   `receivedDateTime` is in UTC. Converting it to your time zone means a file that arrives
   in the evening gets that day's date, not tomorrow's. Other zone names:
   `Eastern Standard Time`, `GMT Standard Time`, `Pacific Standard Time`.

6. **Save**. The **False** branch stays empty.

## Test it

Send yourself (from an address in the **From** list) an email with two report files and a
small image attached. Within a minute or two, `/FinancialReports` should contain the two
files with today's date in front, and no image.

If the saved files won't open (they contain base64 text instead of a spreadsheet), change
**File Content** to the expression `base64ToBinary(items('Apply_to_each')?['contentBytes'])`.

## Getting the files onto the laptop

The loader reads the folder through the OneDrive sync client:

1. Sign in to the OneDrive app on the laptop with the same account.
2. In File Explorer, right-click `FinancialReports` → **Always keep on this device**, so the
   files are real local files and not cloud-only placeholders when the loader runs.
3. Put the folder's local path in `.env` as `LANDING_DIR`, for example
   `C:\Users\you\OneDrive - YourOrg\FinancialReports`.

## Things to know

- **Re-sent files.** If the survey team re-sends a file on the same day, check the folder. The
  loader loads each day once. If a day was loaded and a corrected file arrives later, use the
  undo at the bottom of `sql/02_checks.sql`, then let the next run reload the day.
- **Why the flow doesn't write to SQL itself.** The SQL Server connector is a premium
  connector, and it inserts one row per action: about 150,000 actions a day through a loop.
  Power Automate is good at moving files; bulk loading is the Python loader's job.
