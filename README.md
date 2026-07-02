# W2W-to-Emergency-Networking
This converts a When To Work schedule into Emergency Reporting. 

We were told that Emergency Networking was still working on an integration with WhenToWork (W2W). W2W has worked very well for us in the past. We would like to keep using the product but need a single place to manage the schedule. Both products provide an API interface that allows for the agency to interact with it's data programatically. 

I am using chron to run the script at regular intervals. At this point the script has no idea when it ran last. 

## 12/17/2025
The script now uses the category to determine which apparatus the employee is riding

## 2026-07-02 — error handling, count reconciliation, and a forward coverage check

The failure mode we hit: people scheduled in W2W were silently missing from the
EN crew schedule. `schedule_convert.py` drops a shift with no output whenever the
employee has no `W2W_TO_EN` row (or maps to `9999999`), or the position/category
isn't in `POSITION_AND_CATEGORY_TO_EQUIPMENT`. On top of that the EN POST swallowed
all HTTP errors, so a failed upload looked like success.

Changes:

- **EN POST errors are surfaced.** `post_en_schedule` now checks the HTTP status;
  a non-2xx response makes the run fail (and alert) instead of returning
  `{"status": "ok"}`. The EN token is read from `config.EN_TOKEN` — it is **no
  longer hard-coded in source** (this repo is public; rotate the old token).
- **Count reconciliation every run.** After building a window's payload,
  `reconcile_window()` compares the real people scheduled in that window against
  who actually made it into the EN payload and reports anyone dropped, with the
  reason. If anyone was dropped, an email alert goes to `helpdesk@` (override with
  `W2W_EN_ALERT_TO`). Placeholder accounts (`## STATION`/`## DISTRICT`/etc.) are
  excluded.
- **`--dry-run`** builds and reconciles but does not POST — safe for testing.
- **Top-level guard**: any unhandled error is logged and emailed, and the process
  exits non-zero (so systemd marks the run failed).
- **`coverage_check.py`** (read-only, AD-free): pulls the actual W2W schedule for a
  forward window and reports every person who would not transfer, with the exact
  `W2W_TO_EN` row to add. `--days N` (default 28), `--all-employees`, `--json PATH`,
  `--alert` (email helpdesk on real drops). Run daily over the next 7 days via a
  systemd timer to catch future fall-throughs before they matter.

Alert email uses the internal relay; override with `W2W_EN_ALERT_TO`,
`W2W_EN_SMTP_HOST`, `W2W_EN_SMTP_PORT`. `crew_mapping.py`/`config.py` remain
git-ignored (never commit tokens).

