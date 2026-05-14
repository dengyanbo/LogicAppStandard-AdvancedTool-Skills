# Reference: Time-helper snippets

`lat` takes dates as `yyyyMMdd` (UTC) and date ranges as `--from YYYY-MM-DD
--to YYYY-MM-DD`. Users often say things like "this week", "yesterday",
"90 days ago". Translate to the concrete format before running anything.

All examples below assume **UTC** — that's what the storage table date
suffix uses. If the user is thinking in local time, mention it.

## Single date (`-d` / `--date`)

### Today (UTC)

```powershell
$today = (Get-Date).ToUniversalTime().ToString("yyyyMMdd")
```

```bash
today=$(date -u +%Y%m%d)
```

### Yesterday (UTC)

```powershell
$yesterday = (Get-Date).AddDays(-1).ToUniversalTime().ToString("yyyyMMdd")
```

```bash
yesterday=$(date -u -d 'yesterday' +%Y%m%d)
# macOS BSD date:
# yesterday=$(date -u -v -1d +%Y%m%d)
```

### N days ago

```powershell
$n = 90
$nDaysAgo = (Get-Date).AddDays(-$n).ToUniversalTime().ToString("yyyyMMdd")
```

```bash
n=90
n_days_ago=$(date -u -d "$n days ago" +%Y%m%d)
# macOS BSD date:
# n_days_ago=$(date -u -v -${n}d +%Y%m%d)
```

### Specific calendar date (UTC)

```powershell
$d = [DateTime]::ParseExact("2026-05-14", "yyyy-MM-dd", $null).ToString("yyyyMMdd")
# -> 20260514
```

```bash
d=$(date -u -d '2026-05-14' +%Y%m%d)
```

## Date range (`--from` / `--to`)

`batch-resubmit` and `merge-run-history` use `YYYY-MM-DD` (note the
hyphens), not `yyyyMMdd`.

### "This week" (Monday → today, UTC)

```powershell
$today = (Get-Date).ToUniversalTime()
$diff  = ([int]$today.DayOfWeek + 6) % 7         # 0..6, where Mon = 0
$from  = $today.AddDays(-$diff).ToString("yyyy-MM-dd")
$to    = $today.ToString("yyyy-MM-dd")
# Use as: --from $from --to $to
```

```bash
# bash (GNU date)
today=$(date -u +%Y-%m-%d)
dow=$(date -u +%u)            # 1..7, Mon=1
diff=$((dow - 1))
from=$(date -u -d "$today - $diff days" +%Y-%m-%d)
to=$today
```

### "Last 7 days" (rolling)

```powershell
$to   = (Get-Date).ToUniversalTime().ToString("yyyy-MM-dd")
$from = (Get-Date).AddDays(-7).ToUniversalTime().ToString("yyyy-MM-dd")
```

```bash
to=$(date -u +%Y-%m-%d)
from=$(date -u -d '7 days ago' +%Y-%m-%d)
```

### "Last month" (full previous calendar month, UTC)

```powershell
$firstOfThis = (Get-Date).ToUniversalTime().Date.AddDays(-((Get-Date).Day - 1))
$lastOfPrev  = $firstOfThis.AddDays(-1)
$firstOfPrev = $lastOfPrev.AddDays(-($lastOfPrev.Day - 1))
$from = $firstOfPrev.ToString("yyyy-MM-dd")
$to   = $lastOfPrev.ToString("yyyy-MM-dd")
```

```bash
# bash (GNU date)
first_of_this=$(date -u -d "$(date -u +%Y-%m-01)" +%Y-%m-%d)
last_of_prev=$(date -u -d "$first_of_this - 1 day" +%Y-%m-%d)
first_of_prev=$(date -u -d "$last_of_prev - $(date -u -d "$last_of_prev" +%d) days + 1 day" +%Y-%m-%d)
from=$first_of_prev; to=$last_of_prev
```

## Converting between formats

`lat` is inconsistent (matching the .NET tool):

- **`yyyyMMdd` (no hyphens)** — every command **except** `batch-resubmit`.
  This is the default; assume it unless told otherwise. Commands:
  `workflow backup`, `runs retrieve-failures-by-{date,run}`,
  `runs retrieve-action-payload`, `runs search-in-history`,
  `runs generate-run-history-url`, `workflow merge-run-history --start / --end`,
  and all three `cleanup *`.
- **`yyyy-MM-dd` (with hyphens)** — exactly one command: `runs batch-resubmit`
  with `--from` and `--to`.

| Command | Date format | Param |
| --- | --- | --- |
| `workflow backup` | `yyyyMMdd` | `--date` |
| `runs retrieve-failures-by-date` | `yyyyMMdd` | `-d` |
| `runs retrieve-action-payload` | `yyyyMMdd` | `-d` |
| `runs search-in-history` | `yyyyMMdd` | `-d` |
| `runs generate-run-history-url` | `yyyyMMdd` | `-d` |
| `runs batch-resubmit` | `yyyy-MM-dd` | `--from` / `--to` |
| `workflow merge-run-history` | `yyyyMMdd` | `--start` / `--end` |
| `cleanup containers / tables / run-history` | `yyyyMMdd` | `-d` |

Quick conversion:

```powershell
"20260514" -replace '^(\d{4})(\d{2})(\d{2})$', '$1-$2-$3'   # -> 2026-05-14
"2026-05-14" -replace '-', ''                                # -> 20260514
```

```bash
echo 20260514 | sed -E 's/^(.{4})(.{2})(.{2})$/\1-\2-\3/'    # -> 2026-05-14
echo 2026-05-14 | tr -d '-'                                  # -> 20260514
```

## Sanity checks

Always show the user the **concrete date** you computed before running:

```
"Running with date threshold 20260214 (today UTC minus 90 days). Proceed?"
```

Reject the request if:
- `--end` < `--start`
- The end date is in the future (data doesn't exist for that range)
- The from/to span > 6 months without an explicit "yes, the whole thing"

## Time zones — the most common bug

Storage table date suffixes are **always UTC**. If the user says "from
yesterday" at 11 PM their local time, "yesterday UTC" may include data
they'd expect to be in "today". When in doubt:

```powershell
"UTC now is $((Get-Date).ToUniversalTime()) and your local now is $(Get-Date)."
"I'll use UTC dates throughout; tell me if you'd rather work in local time."
```
