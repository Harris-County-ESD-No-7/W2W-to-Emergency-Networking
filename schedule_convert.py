from __future__ import annotations
import requests
import json
import os
import re
import smtplib
import sys
import traceback
import argparse
from email.message import EmailMessage
from typing import Dict, List, Any
from dataclasses import dataclass
from datetime import datetime, date, time, timedelta
from zoneinfo import ZoneInfo
from crew_mapping import W2W_TO_EN, Always_ON_SHIFT, Ignored_Positions, POSITION_AND_CATEGORY_TO_EQUIPMENT
from config import W2W_TOKEN, EN_TOKEN

TZ = ZoneInfo("America/Chicago")

Four_Hour_Window = (2, 6, 10, 14, 18, 22)

W2W_EMPLOYEE_LIST_URL = "https://www4.whentowork.com/cgi-bin/w2wD.dll/api/EmployeeList"
NOT_ASSIGNED = "9999999"

# Alerts go here (helpdesk@ -> BossDesk ticket). Override with env if needed.
ALERT_TO = os.environ.get("W2W_EN_ALERT_TO", "helpdesk@springfd.org")
ALERT_FROM = os.environ.get("W2W_EN_ALERT_FROM", "noreply@springfd.org")
SMTP_HOST = os.environ.get("W2W_EN_SMTP_HOST", "relay.springfd.int")
SMTP_PORT = int(os.environ.get("W2W_EN_SMTP_PORT", "25"))


def log(msg: str) -> None:
    """Timestamped line to stderr (systemd journal keeps stdout+stderr)."""
    print(f"[{datetime.now(TZ).strftime('%H:%M:%S')}] {msg}", file=sys.stderr, flush=True)


def send_alert(subject: str, body: str) -> None:
    """Best-effort email alert via the internal relay (no auth/TLS), same path
    Traccar and the W2W->Baikal sync use. Never raises -- a failed alert must
    not crash the run."""
    try:
        msg = EmailMessage()
        msg["From"] = ALERT_FROM
        msg["To"] = ALERT_TO
        msg["Subject"] = f"[W2W->EN] {subject}"
        msg.set_content(body)
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as s:
            s.send_message(msg)
        log(f"alert emailed to {ALERT_TO}: {subject}")
    except Exception as e:  # noqa: BLE001 -- alerting is best-effort
        log(f"alert email FAILED (non-fatal): {e}")


_PLACEHOLDER_NAME_RE = re.compile(r"\b(STATION|DISTRICT)\b", re.IGNORECASE)


def _looks_placeholder(first: str, last: str) -> bool:
    """True for the W2W non-person accounts ('78 STATION', '70 DISTRICT',
    'North Comm', 'Not Assigned', 'Cadet') that shouldn't count as scheduled
    people in the reconciliation."""
    name = f"{first} {last}".strip().upper()
    return bool(_PLACEHOLDER_NAME_RE.search(name)) or name in {
        "NORTH COMM", "NOT ASSIGNED", "CADET",
    }

def parse_args(tz):
    """Parse CLI args. Returns (manual_window_or_None, dry_run).

    With no positional args the caller builds the next auto 4-hour window (the
    behaviour the systemd timer relies on). --dry-run builds + reconciles but
    does NOT POST to EN -- safe for testing.
    """
    parser = argparse.ArgumentParser(description="Build crew schedule (W2W -> EN)")
    parser.add_argument("--dry-run", action="store_true",
                        help="build and reconcile but do NOT POST to EN")
    parser.add_argument("start_date", nargs="?", help="MM/DD/YYYY")
    parser.add_argument("start_time", nargs="?", help="HH:MM")
    parser.add_argument("end_date", nargs="?", help="MM/DD/YYYY")
    parser.add_argument("end_time", nargs="?", help="HH:MM")

    args = parser.parse_args()

    if not all([args.start_date, args.start_time, args.end_date, args.end_time]):
        return None, args.dry_run

    start = datetime.strptime(
        f"{args.start_date} {args.start_time}", "%m/%d/%Y %H:%M"
    ).replace(tzinfo=tz)

    end = datetime.strptime(
        f"{args.end_date} {args.end_time}", "%m/%d/%Y %H:%M"
    ).replace(tzinfo=tz)

    return (start, end), args.dry_run

# =========================
# 1) Normalize local date+time to ISO-8601 with offset
# =========================
_TIME_RE = re.compile(
    r"^\s*(?P<h>\d{1,2})(:(?P<m>\d{2}))?\s*(?P<ampm>[AaPp][Mm])?\s*$"
)

def normalize_local_datetime(
    mmddyyyy: str,
    clock_text: str,
    tz: ZoneInfo = TZ
    ) -> str:
    """
    Inputs like:
      mmddyyyy = "10/30/2025"
      clock_text = "6am", "6 am", "06:00", "6:30pm"
    Output:
      "YYYY-MM-DDTHH:MM:SS±HH:MM" in local time with correct DST offset.
    """
    # Parse date
    d = datetime.strptime(mmddyyyy.strip(), "%m/%d/%Y").date()

    # Parse time
    m = _TIME_RE.match(clock_text.strip())
    if not m:
        # fall back to 00:00 local if unrecognized
        hh, mm = 0, 0
    else:
        hh = int(m.group("h"))
        mm = int(m.group("m") or 0)
        ampm = m.group("ampm")
        if ampm:
            ampm = ampm.lower()
            if ampm == "am":
                if hh == 12:
                    hh = 0
            else:
                if hh != 12:
                    hh += 12
        # if no am/pm provided, assume 24-hour input

    dt_local = datetime.combine(d, time(hh, mm))
    dt_zoned = dt_local.replace(tzinfo=tz)
    return dt_zoned.isoformat()


# =========================
# 2) Fetch shifts from WhenToWork
# =========================
def fetch_w2w_assigned_shifts(
    start_date_mmddyyyy: str,
    end_date_mmddyyyy: str,
    w2w_token: str = W2W_TOKEN
    ) -> List[Dict[str, Any]]:
    """
    Calls W2W AssignedShiftList.
    Accepts date strings in MM/DD/YYYY.
    Returns the 'AssignedShiftList' as a list of dicts.
    """
    print(f"Fetching shifts from W2W from {start_date_mmddyyyy} to {end_date_mmddyyyy}")
    # W2W accepts start_date and end_date as M/D/YYYY or MM/DD/YYYY
    # Build URL per user's pattern. W2W supports key in query or Authorization header.
    url = (
        "https://www4.whentowork.com/cgi-bin/w2wD.dll/api/AssignedShiftList"
        f"?start_date={start_date_mmddyyyy}&end_date={end_date_mmddyyyy}"
    )

    headers = {
        "Accept": "application/json",
        "Authorization": w2w_token,  # example: "Bearer 123abc"
    }

    resp = requests.get(url, headers=headers, timeout=60)
    resp.raise_for_status()

    try:
        data = resp.json()
    except ValueError:
        # Fallback if API returns text
        raise RuntimeError(f"W2W non-JSON response: {resp.text[:300]}")

    # Common shape: {"AssignedShiftList":[ {...}, ... ]}
    if isinstance(data, dict) and "AssignedShiftList" in data:
        print("Successfully fetched shifts from W2W")
        return data["AssignedShiftList"] or []
    # Some tenants return the array directly
    if isinstance(data, list):
        print("Successfully fetched shifts from W2W as a list")
        return data
    print(f"Unexpected W2W payload shape: {type(data)}")
    raise RuntimeError(f"Unexpected W2W payload shape: {type(data)}")


def fetch_w2w_employee_index(w2w_token: str = W2W_TOKEN) -> Dict[str, Dict[str, Any]]:
    """{W2W_EMPLOYEE_ID: {"name": str, "placeholder": bool}} for reconciliation
    output. Best-effort: if it fails the reconciliation still runs (names fall
    back to the id and everyone is treated as a real person -> over-report
    rather than miss a drop)."""
    try:
        r = requests.get(
            W2W_EMPLOYEE_LIST_URL,
            headers={"Accept": "application/json", "Authorization": w2w_token},
            timeout=60,
        )
        r.raise_for_status()
        data = r.json()
        rows = (data.get("EmployeeList") if isinstance(data, dict) else data) or []
    except Exception as e:  # noqa: BLE001
        log(f"EmployeeList fetch failed (reconciliation names limited): {e}")
        return {}
    idx: Dict[str, Dict[str, Any]] = {}
    for e in rows:
        eid = str(e.get("W2W_EMPLOYEE_ID") or e.get("EMPLOYEE_ID") or "").strip()
        if not eid:
            continue
        first = re.sub(r"^\([^)]+\)\s*", "", (e.get("FIRST_NAME") or "").strip()).strip()
        last = (e.get("LAST_NAME") or "").strip()
        idx[eid] = {
            "name": f"{first} {last}".strip() or eid,
            "placeholder": _looks_placeholder(first, last),
        }
    return idx


# =========================
# 3) Build EN Crew Schedule JSON
# =========================
@dataclass
class CrewUser:
    id: int | str
    start: str
    end: str
    notes: str | None = "null"

@dataclass
class CrewEquipment:
    call_sign: str
    users: List[CrewUser]
    primary_action: str | None = "null"
    secondary_action: str | None = "null"

def _to_en_user_id(w2w_employee_id: str) -> int | str | None:
    return W2W_TO_EN.get(str(w2w_employee_id))

def _to_equipment_call_sign(position_id: str, category_id: str) -> str | None:
    position_id = str(position_id).strip()
    category_id = str(category_id).strip()
    if position_id in Ignored_Positions:
        return None
    return POSITION_AND_CATEGORY_TO_EQUIPMENT.get((position_id, category_id))

def _clip_interval(
    start_dt: datetime,
    end_dt: datetime,
    window_start: datetime,
    window_end: datetime
) -> tuple[datetime, datetime] | None:
    """
    Clip [start_dt, end_dt) to [window_start, window_end).
    Return None if no overlap.
    """
    s = max(start_dt, window_start)
    e = min(end_dt, window_end)
    if s >= e:
        return None
    return s, e

def make_next_4h_window(now: datetime, tz=TZ) -> tuple[datetime, datetime]:
    """
    Return the next 4-hour window aligned to:
    02:00, 06:00, 10:00, 14:00, 18:00, 22:00 local time.

    Examples with your timer:
      01:55 -> 02:00-06:00
      05:55 -> 06:00-10:00
      09:55 -> 10:00-14:00
      13:55 -> 14:00-18:00
      17:55 -> 18:00-22:00
      21:55 -> 22:00-02:00(next day)
    """
    if now.tzinfo is None:
        now = now.replace(tzinfo=tz)

    today = now.date()

    # build candidate starts for today
    candidates = [
        datetime.combine(today, time(h, 0)).replace(tzinfo=tz)
        for h in Four_Hour_Window
    ]

    # pick the first candidate start strictly after "now"
    for start in candidates:
        if start > now:
            return start, start + timedelta(hours=4)

    # if none left today, next start is tomorrow at 02:00
    start = datetime.combine(today + timedelta(days=1), time(2, 0)).replace(tzinfo=tz)
    return start, start + timedelta(hours=4)

def make_window_6am_to_6am(anchor: date, tz: ZoneInfo = TZ) -> tuple[datetime, datetime]:
    """Build a 24-hour window from 06:00 on 'anchor' to 06:00 next day."""
    start = datetime.combine(anchor, time(6, 0)).replace(tzinfo=tz)
    end = start + timedelta(days=1)
    return start, end

def make_window_6am_to_6pm(anchor: date, tz: ZoneInfo = TZ) -> tuple[datetime, datetime]:
    """Build a 12-hour daytime window from 06:00 to 18:00 on 'anchor'."""
    start = datetime.combine(anchor, time(6, 0)).replace(tzinfo=tz)
    end = datetime.combine(anchor, time(18, 0)).replace(tzinfo=tz)
    return start, end

def make_window_6pm_to_6am(anchor: date, tz: ZoneInfo = TZ) -> tuple[datetime, datetime]:
    """Build a 12-hour overnight window from 18:00 on 'anchor' to 06:00 next day."""
    start = datetime.combine(anchor, time(18, 0)).replace(tzinfo=tz)
    end = datetime.combine(anchor + timedelta(days=1), time(6, 0)).replace(tzinfo=tz)
    return start, end

def check_user_assigned(users: list[CrewUser], en_id: int | str) -> bool:
    return any(user.id == en_id for user in users)

def build_en_schedule_payload_for_window(
    shifts: List[Dict[str, Any]],
    window_start: datetime,
    window_end: datetime
) -> Dict[str, Any]:
    """
    Build a single EN schedule JSON object for the given 6am→6am window.
    Groups users under equipment call_signs.
    Enforces schema provided by the user.
    """
    # equipment_call_sign -> list[ CrewUser ]
    equipment_assignments: Dict[str, List[CrewUser]] = {}

    for call_sign, en_ids in Always_ON_SHIFT.items():
        print(f"Adding shift for {call_sign} with {en_ids}")
        for en_id in en_ids:
            users = equipment_assignments.get(call_sign, [])
            if check_user_assigned(users, en_id):
                continue

            user_rec = CrewUser(
                id=en_id,
                start=window_start.isoformat(),
                end=window_end.isoformat(),
                notes="null",
            )
            equipment_assignments.setdefault(call_sign, []).append(user_rec)

    for s in shifts:
        # Expected W2W fields in each shift item
        # Keys often present: W2W_EMPLOYEE_ID, START_DATE, START_TIME, END_DATE, END_TIME, POSITION_ID
        w2w_emp_id = str(s.get("W2W_EMPLOYEE_ID") or "").strip()
        pos_id = str(s.get("POSITION_ID") or "").strip()
        cat_id = str(s.get("CATEGORY_ID") or "").strip()
        start_date = str(s.get("START_DATE") or "").strip()
        start_time = str(s.get("START_TIME") or "").strip()
        end_date = str(s.get("END_DATE") or "").strip()
        end_time = str(s.get("END_TIME") or "").strip()

        if pos_id in Ignored_Positions:
            continue  # position is ignored
        
        if not (w2w_emp_id and pos_id and start_date and start_time and end_date and end_time):
            continue  # skip incomplete rows

        en_id = _to_en_user_id(w2w_emp_id)
        if en_id is None or str(en_id) == "9999999":
            continue  # user not mapped

        call_sign = _to_equipment_call_sign(pos_id, cat_id)
        if call_sign is None:
            print(f"Position {pos_id} with category {cat_id} that is assigned to {w2w_emp_id} not mapped to equipment")
            continue  # position not mapped to equipment

        # Build localized datetimes
        s_local = datetime.strptime(start_date, "%m/%d/%Y").replace(
            hour=_hh(start_time), minute=_mm(start_time), tzinfo=TZ
        )
        e_local = datetime.strptime(end_date, "%m/%d/%Y").replace(
            hour=_hh(end_time), minute=_mm(end_time), tzinfo=TZ
        )

        # Defensive: handle shifts that wrap backwards or equal
        if e_local <= s_local:
            # assume overnight if same day and end before start
            e_local = e_local + timedelta(days=1)

        clipped = _clip_interval(s_local, e_local, window_start, window_end)
        if not clipped:
            continue  # outside the window

        cs, ce = clipped
        user_rec = CrewUser(
            id=en_id,
            start=cs.isoformat(),
            end=ce.isoformat(),
            notes="null",
        )
        equipment_assignments.setdefault(call_sign, []).append(user_rec)

    # Build equipment list
    equipment: List[Dict[str, Any]] = []
    for cs, users in equipment_assignments.items():
        equipment.append({
            "call_sign": cs,
            "primary_action": "null",
            "secondary_action": "null",
            "users": [vars(u) for u in users],
        })

    payload: Dict[str, Any] = {
        "start": window_start.isoformat(),
        "end": window_end.isoformat(),
        "notes": None,
        "equipment": equipment,
    }
    return payload

def _hh(clock_text: str) -> int:
    m = _TIME_RE.match(clock_text.strip())
    if not m:
        return 0
    hh = int(m.group("h"))
    ampm = m.group("ampm")
    if ampm:
        ampm = ampm.lower()
        if ampm == "am":
            if hh == 12:
                hh = 0
        else:
            if hh != 12:
                hh += 12
    return hh

def _mm(clock_text: str) -> int:
    m = _TIME_RE.match(clock_text.strip())
    if not m:
        return 0
    return int(m.group("m") or 0)


# =========================
# 4) POST to Emergency Networking (EN)
# =========================
def post_en_schedule(payload: Dict[str, Any]) -> dict:
    """
    Posts a single crew schedule to EN.

    The token comes from config.EN_TOKEN (never hard-coded -- this repo is
    public). The HTTP status is CHECKED: a non-2xx response is surfaced as
    ok=False so the caller can alert, instead of the old code that silently
    returned {"status": "ok"} on any failure and hid outages.
    """
    url = "https://app.emergencynetworking.com/department-api/crew-schedules"
    body = json.dumps(payload, indent=2)
    headers = {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'Authorization': f'Bearer {EN_TOKEN}',
    }
    try:
        resp = requests.post(url, headers=headers, data=body, timeout=60)
    except requests.RequestException as e:
        return {"ok": False, "status": None, "body": f"request error: {e}"}

    ok = 200 <= resp.status_code < 300
    try:
        parsed = resp.json()
    except ValueError:
        parsed = {"text": resp.text[:500]}
    return {"ok": ok, "status": resp.status_code, "body": parsed}


def reconcile_window(
    shifts: List[Dict[str, Any]],
    window_start: datetime,
    window_end: datetime,
    emp_index: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    """Count comparison: of the REAL people scheduled in this window, how many
    actually transferred to the EN payload? Re-walks the shifts read-only using
    the SAME skip rules as build_en_schedule_payload_for_window, so a person who
    would be dropped there (no EN mapping, mapped to 9999999, or an unmapped
    position/category) is reported here as a drop with the reason.

    Returns {"scheduled": int, "transferred": int, "drops": [ {w2w_id, name,
    reason} ]}. Placeholder accounts (STATION/DISTRICT/etc.) are excluded --
    they aren't people and are meant to be unmapped.
    """
    scheduled_real: set[str] = set()
    transferred: set[str] = set()
    drop_reason: Dict[str, str] = {}

    for s in shifts:
        emp = str(s.get("W2W_EMPLOYEE_ID") or "").strip()
        pos = str(s.get("POSITION_ID") or "").strip()
        cat = str(s.get("CATEGORY_ID") or "").strip()
        sd = str(s.get("START_DATE") or "").strip()
        st = str(s.get("START_TIME") or "").strip()
        ed = str(s.get("END_DATE") or "").strip()
        et = str(s.get("END_TIME") or "").strip()

        if pos in Ignored_Positions:
            continue
        if not (emp and pos and sd and st and ed and et):
            continue

        # Only count people whose shift actually overlaps this window.
        try:
            s_local = datetime.strptime(sd, "%m/%d/%Y").replace(
                hour=_hh(st), minute=_mm(st), tzinfo=TZ)
            e_local = datetime.strptime(ed, "%m/%d/%Y").replace(
                hour=_hh(et), minute=_mm(et), tzinfo=TZ)
        except ValueError:
            continue
        if e_local <= s_local:
            e_local = e_local + timedelta(days=1)
        if _clip_interval(s_local, e_local, window_start, window_end) is None:
            continue

        info = emp_index.get(emp, {})
        if info.get("placeholder"):
            continue  # not a real person
        scheduled_real.add(emp)
        name = info.get("name", emp)

        en_id = _to_en_user_id(emp)
        if en_id is None or str(en_id) == NOT_ASSIGNED:
            drop_reason.setdefault(emp, f"{name}: no EN mapping (add W2W_TO_EN row)")
            continue
        if _to_equipment_call_sign(pos, cat) is None:
            drop_reason.setdefault(
                emp, f"{name}: position {pos}/category {cat} not mapped to equipment")
            continue
        transferred.add(emp)

    # A person with several shifts counts as transferred if ANY shift made it.
    drops = [
        {"w2w_id": emp, "name": emp_index.get(emp, {}).get("name", emp),
         "reason": reason}
        for emp, reason in drop_reason.items()
        if emp not in transferred
    ]
    return {
        "scheduled": len(scheduled_real),
        "transferred": len(transferred),
        "drops": drops,
    }


# =========================
# Orchestration
# =========================
def build_the_schedule(manual_window=None, dry_run: bool = False):
    """
    End-to-end:
      1) request shifts from W2W for the 48h surrounding the window
      2) generate EN JSON for the window
      3) reconcile: did every real person scheduled in the window transfer?
      4) POST to EN (unless dry_run)

    Raises on a failed EN POST so main() can alert. Returns a dict with the
    reconciliation summary and the post result.
    """

    now = datetime.now(TZ)

    if manual_window:
        window_start, window_end = manual_window
        print(f"Building manual window: {window_start.isoformat()} to {window_end.isoformat()}")
    else:
        window_start, window_end = make_next_4h_window(now, TZ)
        print(f"Building 4-hour window: {window_start.isoformat()} to {window_end.isoformat()}")

    # Pull a wider range to ensure we catch overnight shifts
    fetch_start = (window_start - timedelta(hours=12)).strftime("%m/%d/%Y")
    fetch_end   = (window_end + timedelta(hours=12)).strftime("%m/%d/%Y")

    shifts = fetch_w2w_assigned_shifts(fetch_start, fetch_end)
    emp_index = fetch_w2w_employee_index()

    payload = build_en_schedule_payload_for_window(shifts, window_start, window_end)

    # Count comparison: real people scheduled in this window vs actually posted.
    recon = reconcile_window(shifts, window_start, window_end, emp_index)
    recon["window"] = f"{window_start.isoformat()} .. {window_end.isoformat()}"
    print(f"Reconciliation: scheduled={recon['scheduled']} "
          f"transferred={recon['transferred']} dropped={len(recon['drops'])}")
    for d in recon["drops"]:
        print(f"  DROP {d['w2w_id']}  {d['reason']}")

    if not payload.get("equipment"):
        print("No assignments matched the window -- nothing to POST")
        return {"skipped": True, "reason": "No assignments matched the window",
                "recon": recon, "dry_run": dry_run}

    if dry_run:
        print("[dry-run] built + reconciled; NOT posting to EN")
        return {"posted": False, "dry_run": True, "recon": recon, "payload": payload}

    result = post_en_schedule(payload)
    if not result.get("ok"):
        # Surface the failure so the run is marked failed and alerts fire.
        raise RuntimeError(
            f"EN POST failed: HTTP {result.get('status')} -- {result.get('body')}"
        )
    print(f"Posted to EN: HTTP {result.get('status')}")
    return {"posted": True, "result": result, "recon": recon}


def render_drop_alert(recon: Dict[str, Any], window: str) -> str:
    lines = [
        f"Window: {window}",
        f"Scheduled (real people): {recon['scheduled']}",
        f"Transferred to EN:       {recon['transferred']}",
        f"DID NOT TRANSFER:        {len(recon['drops'])}",
        "",
        "These people are on the W2W schedule for this window but were dropped",
        "on the way to Emergency Networking:",
    ]
    for d in recon["drops"]:
        lines.append(f"  - {d['reason']}  (W2W id {d['w2w_id']})")
    lines.append("")
    lines.append("Fix: add/repair the W2W_TO_EN row (roster_sync regenerates it) or")
    lines.append("map the position/category in POSITION_AND_CATEGORY_TO_EQUIPMENT.")
    lines.append("-- schedule_convert.py")
    return "\n".join(lines)


def main() -> None:
    manual_window, dry_run = parse_args(TZ)
    window_label = "manual" if manual_window else "auto 4h"
    try:
        out = build_the_schedule(manual_window, dry_run=dry_run)
    except Exception as e:  # noqa: BLE001 -- top-level guard: log + alert, then fail
        log(f"FATAL: {e}")
        send_alert(
            "sync FAILED",
            f"schedule_convert.py ({window_label}) raised:\n\n{e}\n\n"
            f"{traceback.format_exc()}",
        )
        sys.exit(1)

    recon = out.get("recon") or {}
    drops = recon.get("drops") or []
    if drops and not dry_run:
        send_alert(
            f"{len(drops)} scheduled member(s) did NOT transfer",
            render_drop_alert(recon, recon.get("window", window_label)),
        )

    print(json.dumps({"summary": recon, "posted": out.get("posted", False),
                      "dry_run": dry_run}, indent=2))


if __name__ == "__main__":
    main()

