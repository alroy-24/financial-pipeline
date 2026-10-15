# Registers the loader in Windows Task Scheduler: daily at 3:30, 4:30, 5:30 and 6:30 PM.
# Extra runs are harmless: loaded files are skipped, and a day only loads once all 25 are in.
#
# Run once, from the financial-pipeline folder:
#     powershell -ExecutionPolicy Bypass -File tools\register_task.ps1

$project = Split-Path -Parent $PSScriptRoot
$python = (Get-Command python -ErrorAction Stop).Source

$action = New-ScheduledTaskAction -Execute $python -Argument "`"$project\load_to_sql.py`"" -WorkingDirectory $project
$triggers = '15:30', '16:30', '17:30', '18:30' | ForEach-Object { New-ScheduledTaskTrigger -Daily -At $_ }
# StartWhenAvailable: if the laptop was asleep at a run time, run as soon as it wakes.
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 30)

Register-ScheduledTask -TaskName 'Financial data loader' -Action $action -Trigger $triggers -Settings $settings `
    -Description 'Loads the day''s report files from the OneDrive landing folder into Azure SQL.' -Force

Write-Host "Registered. Each run appends to $project\logs\loader.log; a failed run shows 'Last Run Result' 0x1."
