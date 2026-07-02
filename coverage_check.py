#!/usr/bin/env python3
"""
coverage_check.py -- does every W2W person who is actually scheduled make it
into the Emergency Networking (EN) crew schedule?

This is a READ-ONLY companion to schedule_convert.py. It answers one question:
"Who is being silently dropped on the way from W2W to EN, and how do we fix it?"

Why this exists (and why it differs from roster_sync.py):
  roster_sync.py builds crew_mapping.W2W_TO_EN by joining AD <-> W2W <-> EN and
  only emits a mapping row for a W2W person it can tie to an in-scope AD OU.
  schedule_convert.py, however, only needs a W2W_TO_EN row to move a shift --
  AD is irrelevant to the transfer. So a person who is in BOTH W2W and EN but
  whom roster_sync can't anchor to AD (wrong OU, renamed/disabled AD account,
  no AD account at all) gets NO mapping row and is dropped from the schedule --
  while roster_sync happily reports "0 gaps".  (Verified with Rodger Hernandez:
  W2W 168685011 + EN 67214, clean email match, no mapping row, 0 gaps reported.)

  This tool ignores AD entirely. It matches W2W -> EN directly by email, then by
  (last, first) name, exactly the way a human would, and reports every scheduled
  person whose shift would not transfer -- together with the EN id we'd map them
  to, so the fix is copy-paste.

What "dropped" means, straight from schedule_convert.build_en_schedule_payload_for_window:
  1. W2W emp id not a key in W2W_TO_EN           -> en_id is None  -> shift skipped
  2. W2W emp id maps to the "9999999" sentinel   -> "Not Assigned" -> shift skipped
  3. (POSITION_ID, CATEGORY_ID) not in the
     POSITION_AND_CATEGORY_TO_EQUIPMENT table    -> no call sign   -> shift skipped
  (position in Ignored_Positions and incomplete rows are intentional skips)

Usage (read-only; writes nothing, sends nothing):
  ./venv/bin/python coverage_check.py                 # next 28 days of schedule
  ./venv/bin/python coverage_check.py --days 42       # wider window
  ./venv/bin/python coverage_check.py --all-employees  # audit the whole roster,
                                                       # not just who's scheduled
  ./venv/bin/python coverage_check.py --json out.json  # also dump machine-readable

Tokens + tables come from the adjacent config.py / crew_mapping.py, same as
schedule_convert.py, so nothing new needs configuring.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import smtplib
import sys
from datetime import datetime, timedelta
from email.message import EmailMessage
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

# Alert destination (helpdesk@ -> BossDesk ticket); override via env.
ALERT_TO = os.environ.get("W2W_EN_ALERT_TO", "helpdesk@springfd.org")
ALERT_FROM = os.environ.get("W2W_EN_ALERT_FROM", "noreply@springfd.org")
SMTP_HOST = os.environ.get("W2W_EN_SMTP_HOST", "relay.springfd.int")
SMTP_PORT = int(os.environ.get("W2W_EN_SMTP_PORT", "25"))


def send_alert(subject: str, body: str) -> None:
    """Best-effort email via the internal relay (no auth/TLS). Never raises."""
    try:
        msg = EmailMessage()
        msg["From"] = ALERT_FROM
        msg["To"] = ALERT_TO
        msg["Subject"] = f"[W2W->EN coverage] {subject}"
        msg.set_content(body)
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as s:
            s.send_message(msg)
        print(f"[coverage_check] alert emailed to {ALERT_TO}: {subject}")
    except Exception as e:  # noqa: BLE001
        print(f"[coverage_check] alert email FAILED (non-fatal): {e}", file=sys.stderr)

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from config import W2W_TOKEN  # noqa: E402
try:
    from config import EN_USERS_TOKEN as EN_READ_TOKEN  # users:read scope
except ImportError:
    from config import EN_TOKEN as EN_READ_TOKEN  # may lack users:read -> 403

from crew_mapping import (  # noqa: E402
    W2W_TO_EN,
    Ignored_Positions,
    POSITION_AND_CATEGORY_TO_EQUIPMENT,
)

TZ = ZoneInfo("America/Chicago")
NOT_ASSIGNED = "9999999"

W2W_BASE = "https://www4.whentowork.com/cgi-bin/w2wD.dll/api"
EN_USERS_URL = "https://app.emergencynetworking.com/department-api/users"

# W2W carries display prefixes like "(D) Brian" on first names -- strip them.
_PREFIX_RE = re.compile(r"^\([^)]+\)\s*")


def _clean_first(name: str) -> str:
    return _PREFIX_RE.sub("", (name or "").strip()).strip()


def _name_key(first: str, last: str) -> str:
    return f"{(last or '').strip().lower()}|{_clean_first(first).lower()}"


# --- fetchers ------------------------------------------------------------

def fetch_w2w_employees() -> dict[str, dict]:
    r = requests.get(
        f"{W2W_BASE}/EmployeeList",
        headers={"Accept": "application/json", "Authorization": W2W_TOKEN},
        timeout=60,
    )
    r.raise_for_status()
    data = r.json()
    rows = (data.get("EmployeeList") if isinstance(data, dict) else data) or []
    out: dict[str, dict] = {}
    for e in rows:
        eid = str(e.get("W2W_EMPLOYEE_ID") or e.get("EMPLOYEE_ID") or "").strip()
        if eid:
            out[eid] = e
    return out


def fetch_w2w_scheduled_ids(days: int) -> tuple[set[str], list[dict]]:
    """Distinct W2W employee ids with at least one assigned shift in the window,
    plus the raw shift rows (for position/category coverage)."""
    now = datetime.now(TZ)
    start = now.strftime("%m/%d/%Y")
    end = (now + timedelta(days=days)).strftime("%m/%d/%Y")
    url = f"{W2W_BASE}/AssignedShiftList?start_date={start}&end_date={end}"
    r = requests.get(
        url,
        headers={"Accept": "application/json", "Authorization": W2W_TOKEN},
        timeout=90,
    )
    r.raise_for_status()
    data = r.json()
    shifts = (data.get("AssignedShiftList") if isinstance(data, dict) else data) or []
    ids = {
        str(s.get("W2W_EMPLOYEE_ID") or "").strip()
        for s in shifts
        if str(s.get("W2W_EMPLOYEE_ID") or "").strip()
    }
    return ids, shifts


def fetch_en_users() -> list[dict]:
    r = requests.get(
        EN_USERS_URL,
        headers={"Accept": "application/json",
                 "Authorization": f"Bearer {EN_READ_TOKEN}"},
        timeout=60,
    )
    r.raise_for_status()
    data = r.json()
    users = data.get("data") if isinstance(data, dict) else data
    if users is None and isinstance(data, dict):
        users = data.get("users", [])
    return users or []


# --- EN indexes for direct (AD-free) resolution --------------------------

def _en_field(u: dict, *keys: str) -> str:
    for k in keys:
        v = u.get(k)
        if v:
            return str(v)
    return ""


def build_en_indexes(users: list[dict]) -> tuple[dict[str, dict], dict[str, list[dict]]]:
    by_email: dict[str, dict] = {}
    by_name: dict[str, list[dict]] = {}
    for u in users:
        if u.get("active") == 0:
            continue  # EN soft-deletes; a dropped person needs an ACTIVE target
        email = _en_field(u, "email").strip().lower()
        if email:
            by_email.setdefault(email, u)
        nk = _name_key(_en_field(u, "first_name", "firstName"),
                       _en_field(u, "last_name", "lastName"))
        by_name.setdefault(nk, []).append(u)
    return by_email, by_name


def resolve_en(emp: dict, by_email: dict[str, dict],
               by_name: dict[str, list[dict]]) -> tuple[str | None, str]:
    """Return (en_id, how) for a W2W employee, matched the way a human would."""
    emails_raw = (emp.get("EMAILS") or "").strip()
    cands = [x.strip().lower() for x in emails_raw.split(",") if x.strip()]
    springfd = next((x for x in cands if x.endswith("@springfd.org")), None)
    for e in ([springfd] if springfd else []) + cands:
        if e and e in by_email:
            return str(by_email[e].get("id")), f"email {e}"
    nk = _name_key(emp.get("FIRST_NAME", ""), emp.get("LAST_NAME", ""))
    hits = by_name.get(nk, [])
    if len(hits) == 1:
        return str(hits[0].get("id")), f"name {nk}"
    if len(hits) > 1:
        return None, f"AMBIGUOUS name {nk} ({len(hits)} EN users)"
    return None, "no EN match"


# --- classification ------------------------------------------------------

def w2w_name(emp: dict) -> str:
    return f"{_clean_first(emp.get('FIRST_NAME',''))} {emp.get('LAST_NAME','')}".strip()


def is_placeholder(emp: dict) -> bool:
    """W2W station/district placeholder accounts (e.g. '70 STATION') are meant
    to map to 9999999 -- they are not real people and shouldn't be flagged."""
    name = w2w_name(emp).upper()
    return bool(re.search(r"\b(STATION|DISTRICT)\b", name)) or name in {
        "NORTH COMM", "NOT ASSIGNED", "CADET",
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=28,
                    help="forward schedule window to scan (default 28)")
    ap.add_argument("--all-employees", action="store_true",
                    help="audit every W2W employee, not just those scheduled")
    ap.add_argument("--json", metavar="PATH",
                    help="also write a machine-readable report to PATH")
    ap.add_argument("--alert", action="store_true",
                    help="email helpdesk@ (via relay) when any scheduled person "
                         "would NOT transfer -- for the daily forward-looking timer")
    args = ap.parse_args()

    print(f"[coverage_check] W2W employees + next {args.days}d schedule vs EN\n")
    employees = fetch_w2w_employees()
    scheduled_ids, shifts = fetch_w2w_scheduled_ids(args.days)
    en_users = fetch_en_users()
    by_email, by_name = build_en_indexes(en_users)

    print(f"W2W employees:            {len(employees)}")
    print(f"W2W scheduled (next {args.days}d): {len(scheduled_ids)} distinct people, "
          f"{len(shifts)} shift rows")
    print(f"EN active users:          {sum(1 for u in en_users if u.get('active') != 0)}")
    print(f"W2W_TO_EN rows:           {len(W2W_TO_EN)} "
          f"({sum(1 for v in W2W_TO_EN.values() if str(v) == NOT_ASSIGNED)} -> Not Assigned)\n")

    target_ids = set(employees) if args.all_employees else scheduled_ids

    mapped_ok: list[tuple[str, dict, str]] = []
    not_assigned: list[tuple[str, dict]] = []       # -> 9999999
    unmapped_resolvable: list[tuple[str, dict, str, str]] = []  # (id, emp, en_id, how)
    unmapped_unresolvable: list[tuple[str, dict, str]] = []     # (id, emp, why)

    for eid in sorted(target_ids):
        emp = employees.get(eid)
        if emp is None:
            # scheduled under an id that isn't in EmployeeList (rare/stale)
            unmapped_unresolvable.append((eid, {"FIRST_NAME": "?", "LAST_NAME": "?"},
                                          "id not in W2W EmployeeList"))
            continue
        mapped = W2W_TO_EN.get(eid)
        if mapped is not None and str(mapped) != NOT_ASSIGNED:
            mapped_ok.append((eid, emp, str(mapped)))
            continue
        if str(mapped) == NOT_ASSIGNED:
            if not is_placeholder(emp):
                not_assigned.append((eid, emp))
            continue
        # no row at all -> try to resolve directly, AD-free
        if is_placeholder(emp):
            continue
        en_id, how = resolve_en(emp, by_email, by_name)
        if en_id:
            unmapped_resolvable.append((eid, emp, en_id, how))
        else:
            unmapped_unresolvable.append((eid, emp, how))

    scope = "ALL employees" if args.all_employees else f"scheduled (next {args.days}d)"
    print("=" * 72)
    print(f"COVERAGE for {scope}:")
    print(f"  transfer OK (real EN id):                 {len(mapped_ok)}")
    print(f"  WILL DROP - mapped to 9999999 (a person): {len(not_assigned)}")
    print(f"  WILL DROP - no mapping, EN match found:   {len(unmapped_resolvable)}")
    print(f"  WILL DROP - no mapping, no EN match:      {len(unmapped_unresolvable)}")
    print("=" * 72)

    if unmapped_resolvable:
        print("\n### WILL DROP but FIXABLE -- add these rows to W2W_TO_EN:")
        print("### (person is in W2W and has an active EN account; just no map row)")
        for eid, emp, en_id, how in sorted(unmapped_resolvable,
                                           key=lambda x: w2w_name(x[1]).lower()):
            sched = " [SCHEDULED]" if eid in scheduled_ids else ""
            print(f'    "{eid}": "{en_id}",  # {w2w_name(emp)}  (via {how}){sched}')

    if not_assigned:
        print("\n### WILL DROP -- real person parked at 9999999 (needs a real EN id):")
        for eid, emp in sorted(not_assigned, key=lambda x: w2w_name(x[1]).lower()):
            en_id, how = resolve_en(emp, by_email, by_name)
            fix = f' -> suggest "{en_id}" (via {how})' if en_id else f' -> {how}'
            sched = " [SCHEDULED]" if eid in scheduled_ids else ""
            print(f"    {eid}  {w2w_name(emp)}{fix}{sched}")

    if unmapped_unresolvable:
        print("\n### WILL DROP -- no mapping AND no EN account found (needs EN user first):")
        for eid, emp, why in sorted(unmapped_unresolvable,
                                    key=lambda x: w2w_name(x[1]).lower()):
            sched = " [SCHEDULED]" if eid in scheduled_ids else ""
            print(f"    {eid}  {w2w_name(emp)}  ({why}){sched}")

    # Position/category coverage among scheduled shifts (drop reason #3).
    unmapped_pos: dict[tuple[str, str], int] = {}
    for s in shifts:
        pos = str(s.get("POSITION_ID") or "").strip()
        cat = str(s.get("CATEGORY_ID") or "").strip()
        if not pos or pos in Ignored_Positions:
            continue
        if (pos, cat) not in POSITION_AND_CATEGORY_TO_EQUIPMENT:
            unmapped_pos[(pos, cat)] = unmapped_pos.get((pos, cat), 0) + 1
    if unmapped_pos:
        print("\n### Position/Category pairs on the schedule NOT mapped to equipment:")
        print("### (these shifts also drop -- extend POSITION_AND_CATEGORY_TO_EQUIPMENT)")
        for (pos, cat), n in sorted(unmapped_pos.items(), key=lambda x: -x[1]):
            print(f"    POSITION_ID={pos} CATEGORY_ID={cat}  ({n} shift rows)")

    will_drop = len(not_assigned) + len(unmapped_resolvable) + len(unmapped_unresolvable)
    print(f"\nBOTTOM LINE: {will_drop} scheduled person(s) will NOT transfer to EN "
          f"({len(unmapped_resolvable)} are one-line fixes).")

    # Forward-looking alert (for the daily timer). Only fires on real personnel
    # drops -- unmapped position/category pairs are logged but don't page.
    if args.alert and will_drop:
        lines = [
            f"{will_drop} person(s) scheduled in W2W over the next {args.days} days",
            "will NOT transfer to the Emergency Networking crew schedule.",
            "",
        ]
        for eid, emp, en_id, how in sorted(unmapped_resolvable,
                                           key=lambda x: w2w_name(x[1]).lower()):
            lines.append(f'  FIX (add row): "{eid}": "{en_id}",  # {w2w_name(emp)} (via {how})')
        for eid, emp in sorted(not_assigned, key=lambda x: w2w_name(x[1]).lower()):
            lines.append(f"  PARKED at 9999999: {w2w_name(emp)} (W2W {eid}) -- needs a real EN id")
        for eid, emp, why in sorted(unmapped_unresolvable,
                                    key=lambda x: w2w_name(x[1]).lower()):
            lines.append(f"  NO EN ACCOUNT: {w2w_name(emp)} (W2W {eid}) -- {why}")
        if unmapped_pos:
            lines.append("")
            lines.append("Also: position/category pairs on the schedule not mapped to equipment:")
            for (pos, cat), n in sorted(unmapped_pos.items(), key=lambda x: -x[1]):
                lines.append(f"  POSITION_ID={pos} CATEGORY_ID={cat} ({n} shift rows)")
        lines.append("")
        lines.append("-- coverage_check.py (daily forward check)")
        send_alert(f"{will_drop} member(s) will not transfer (next {args.days}d)",
                   "\n".join(lines))

    if args.json:
        rep = {
            "generated": datetime.now(TZ).isoformat(),
            "window_days": args.days,
            "scope": scope,
            "counts": {
                "transfer_ok": len(mapped_ok),
                "drop_not_assigned": len(not_assigned),
                "drop_unmapped_resolvable": len(unmapped_resolvable),
                "drop_unmapped_unresolvable": len(unmapped_unresolvable),
            },
            "fixable_rows": {eid: en_id for eid, _e, en_id, _h in unmapped_resolvable},
            "not_assigned": [
                {"w2w_id": eid, "name": w2w_name(e)} for eid, e in not_assigned],
            "unresolvable": [
                {"w2w_id": eid, "name": w2w_name(e), "why": why}
                for eid, e, why in unmapped_unresolvable],
            "unmapped_positions": [
                {"position_id": p, "category_id": c, "rows": n}
                for (p, c), n in unmapped_pos.items()],
        }
        Path(args.json).write_text(json.dumps(rep, indent=2), encoding="utf-8")
        print(f"\nwrote {args.json}")


if __name__ == "__main__":
    main()
