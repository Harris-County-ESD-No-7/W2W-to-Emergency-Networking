from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, date, time, timedelta
from zoneinfo import ZoneInfo
import requests
import json
import re
from typing import Dict, List, Any

from crew_mapping import W2W_TO_EN, Always_ON_SHIFT, Ignored_Positions, POSITION_AND_CATEGORY_TO_EQUIPMENT
from config import W2W_TOKEN, EN_TOKEN

TZ = ZoneInfo("America/Chicago")




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
    """
    url = "https://app.emergencynetworking.com/department-api/crew-schedules"
    payload = json.dumps(payload, indent=2)
    headers = {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'Authorization': 'Bearer eyJ0eXAiOiJKV1QiLCJhbGciOiJSUzI1NiJ9.eyJhdWQiOiIyIiwianRpIjoiMTNhYTcwYzc2ZDVmZTlkMThiNDA5YzhkZTIyZGQzOGM2ZGVkNmVmZDU2NTRjNGU4Y2E4ZTdmMDU0YzQyNTk5Yzk1ZDRkYTIxZWZmOTY3NmYiLCJpYXQiOjE3NjIxMzgzMTMuNTY4NDQsIm5iZiI6MTc2MjEzODMxMy41Njg0NDIsImV4cCI6MjA3NzY3MTExMy41NDAxOCwic3ViIjoiMzAyNjA4NTQwIiwic2NvcGVzIjpbInNjaGVkdWxlOndyaXRlIl19.aCdyoyDrgc9NnmgYZ2YS-XtTvU0ZYNl0YZmxW5k1JCFCT369FzzysSUh9JG46JQ-hKu38Xj_4IoAw1s5vqPlBj5xBxDBygkY8kYEnLJsqbf2hcpThv2PKOXCyGubyW308BqrtNt9wGPoY67xS1W2hFsOufcoYZocLM739FyLjeTb4qL_F6UdYJ3a3iD2Xqrk9LnC1m_Bfn4qbLY_Rr3cDow73hMB7mxg-4KH1tf0DerMVLVfyB7snivNUevsvIROhlRIG3aXeM4c19jhAt81sCzWfb9J75Em2dZ7F6RtyjU-RW4_a2JB4_xWMJru12EwX-jahLnuiW4-F8xSxLa5-YGqY488dus3dhmH-XMrbx1Rfkmg4baQ-AyYioTEhu5latH57mvT0FzYyngNAYQBcdPQCYgDSmT9Fa0LaCmnAWltvxGavvwyZL_MURVfq4iSfJAvumcLCSg4e1OUBKmHaZHDqqoy8pL3SaqYTI5rHcDF18jScZlG8Z0QQlLTXuo8vp55qnQJ-DRa_zuGyN2zBkJ76Fn81f0YJo_6vUIUMYD3WSkAwUXpdbmZdG6cpQknPPKL7ZY3_cwl4WyqmjEmr3oGI6KplrCzoY-Nz7-Rgl33F_W-KB_JYcRr6w5F6yozbSjRKicOLbUvaFeTZXjz8qSDdfbqP4-gXOShmcX9PT8'
    }
    resp = requests.request("POST", url, headers=headers, data=payload, timeout=60)
    # response = requests.request("POST", url, headers=headers, data=payload)
    # Raise for non-2xx to surface errors
    # resp.raise_for_status()
    try:
        return resp.json()
    except ValueError:
        return {"status": "ok", "text": resp.text}


# =========================
# Orchestration
# =========================
def build_the_schedule():
    """
    End-to-end:
      1) request shifts from W2W for the 48h surrounding the window
      2) store raw shifts
      3) generate EN JSON for the 6am→6am window anchored at anchor_mmddyyyy
      4) POST to EN
    """
    #anchor = datetime.strptime(anchor_mmddyyyy, "%m/%d/%Y").date()
    #now = datetime.now(TZ)

    now = datetime.now(TZ)
    anchor = now.date()

    # choose which window to build based on current time
    if now.hour < 12:
        print("Building 6am to 6pm window")
        window_start, window_end = make_window_6am_to_6pm(anchor)
    else:
        print("Building 6pm to 6am window")
        window_start, window_end = make_window_6pm_to_6am(anchor)

    # Pull a wider range to ensure we catch overnight shifts
    fetch_start = (window_start - timedelta(days=1)).strftime("%m/%d/%Y")
    fetch_end   = (window_end + timedelta(days=1)).strftime("%m/%d/%Y")

    shifts = fetch_w2w_assigned_shifts(fetch_start, fetch_end)

    payload = build_en_schedule_payload_for_window(shifts, window_start, window_end)

    # Optional: validate required fields before POST
    if not payload.get("equipment"):
        return {"skipped": True, "reason": "No assignments matched the window", "payload": payload}

    result = post_en_schedule(payload)
    return {"posted": True, "result": result, "payload": payload}


if __name__ == "__main__":
    # Example: build and post the 6am→6am window for 10/30/2025
    # Comment out the call below if you are not ready to POST to EN.
    # result = run_once_for_window("10/30/2025")
    # print(json.dumps(result, indent=2))

    # Print sample normalizations
    build_the_schedule()

