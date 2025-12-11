#!/usr/bin/env python
# coding: utf-8

# In[1]:


# Standard library
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, date, time, timedelta
from zoneinfo import ZoneInfo
import json
import re
from typing import Dict, List, Any

# Third party
import requests




# In[2]:


# =========================
# Config and lookup tables
# =========================
TZ = ZoneInfo("America/Chicago")

# Secrets: replace at runtime or inject via env/secret manager
W2W_TOKEN = "Bearer D002558B6-8FC026DF3A80494AA11E6AB68F6787FC"  # keep the "Bearer " prefix here to match W2W's expectation
EN_TOKEN  = "eyJ0eXAiOiJKV1QiLCJhbGciOiJSUzI1NiJ9.eyJhdWQiOiIyIiwianRpIjoiMTNhYTcwYzc2ZDVmZTlkMThiNDA5YzhkZTIyZGQzOGM2ZGVkNmVmZDU2NTRjNGU4Y2E4ZTdmMDU0YzQyNTk5Yzk1ZDRkYTIxZWZmOTY3NmYiLCJpYXQiOjE3NjIxMzgzMTMuNTY4NDQsIm5iZiI6MTc2MjEzODMxMy41Njg0NDIsImV4cCI6MjA3NzY3MTExMy41NDAxOCwic3ViIjoiMzAyNjA4NTQwIiwic2NvcGVzIjpbInNjaGVkdWxlOndyaXRlIl19.aCdyoyDrgc9NnmgYZ2YS-XtTvU0ZYNl0YZmxW5k1JCFCT369FzzysSUh9JG46JQ-hKu38Xj_4IoAw1s5vqPlBj5xBxDBygkY8kYEnLJsqbf2hcpThv2PKOXCyGubyW308BqrtNt9wGPoY67xS1W2hFsOufcoYZocLM739FyLjeTb4qL_F6UdYJ3a3iD2Xqrk9LnC1m_Bfn4qbLY_Rr3cDow73hMB7mxg-4KH1tf0DerMVLVfyB7snivNUevsvIROhlRIG3aXeM4c19jhAt81sCzWfb9J75Em2dZ7F6RtyjU-RW4_a2JB4_xWMJru12EwX-jahLnuiW4-F8xSxLa5-YGqY488dus3dhmH-XMrbx1Rfkmg4baQ-AyYioTEhu5latH57mvT0FzYyngNAYQBcdPQCYgDSmT9Fa0LaCmnAWltvxGavvwyZL_MURVfq4iSfJAvumcLCSg4e1OUBKmHaZHDqqoy8pL3SaqYTI5rHcDF18jScZlG8Z0QQlLTXuo8vp55qnQJ-DRa_zuGyN2zBkJ76Fn81f0YJo_6vUIUMYD3WSkAwUXpdbmZdG6cpQknPPKL7ZY3_cwl4WyqmjEmr3oGI6KplrCzoY-Nz7-Rgl33F_W-KB_JYcRr6w5F6yozbSjRKicOLbUvaFeTZXjz8qSDdfbqP4-gXOShmcX9PT8"       # send as-is, no "Bearer " prefix

# Person lookup (W2W → EN)
# Use W2W_ID strings for keys to match typical API payload typing
W2W_TO_EN: Dict[str, str] = {
    "317595647": "9999999", # CADET
    "318972808": "67151", # Jason Adams
    "145773476": "67153", # Calvin Adkins
    "318965955": "67152", # Brandon Adkins
    "127924093": "67155", # Michael Alaniz
    "498916346": "67156", # Abraham Arroyo
    "213200353": "67157", # Luis Arzate
    "97411094": "9999999", # Not Assigned
    "183973669": "67158", # Daniel Atkinson
    "498925669": "67159", # Nikolas Atkinson
    "200856496": "67160", # Joe Attaway
    "626265856": "67161", # Zacharya Ayoub
    "668851220": "9999999", # Colton Baack
    "657364054": "67162", # Fletcher Babitt
    "200856946": "67163", # Jacob Bailey
    "263866445": "67164", # Jakob Ballard
    "542307117": "67165", # Shane Barnes
    "230121393": "67166", # Emmanuel Barrera
    "127923136": "67167", # Colby Bates
    "645452325": "67168", # John Benavides
    "626266663": "67169", # Joy Bernabel
    "96216415": "67170", # Bryan Blackburn
    "318971501": "67171", # Collin Bosworth
    "96217754": "67172", # John Bradley
    "368158228": "67173", # Brandon Braswell
    "579293621": "9999999", # Alex Bregenzer
    "178516137": "67175", # Jeremie Bricout
    "98567235": "67176", # Larry Brooks
    "152458797": "67177", # Billy Burdge
    "413816504": "67178", # Thomas Carlton
    "454755950": "67180", # George Castro
    "543654610": "53350", # Landon Churchill
    "168684926": "67181", # Richard Cinco
    "457735165": "9999999", # North Comm
    "657311667": "67182", # Natalia Contreras
    "177373588": "67183", # Marc Corbeil
    "20441315": "67184", # Matthew Corso
    "96218447": "67185", # Dave Corson
    "668858898": "9999999", # Champ Craven
    "96207594": "67187", # Joel Crenshaw
    "185710124": "9999999", # Sylvia Cuevas
    "178511899": "67188", # Marcos DaCunha
    "626266617": "67189", # Zachary Danford
    "96204502": "44965", # Jerod Davenport
    "433026040": "67190", # Carlos Diaz
    "562016091": "9999999", # 70 DISTRICT
    "562016126": "9999999", # 72 DISTRICT
    "96217709": "67191", # Wayne Doss
    "433011999": "67192", # Samuel Dufford
    "368161343": "67193", # Trevor Duncan
    "168685057": "67194", # Santiago Eckardt
    "200854813": "67195", # Tracee Evans
    "263967778": "67196", # Brandon Fielder
    "668861806": "9999999", # Brian Franks II
    "489156667": "67197", # Celine Gomez
    "657311360": "67198", # Lia Gonzales
    "498320947": "67199", # Darian Goodlander
    "96218336": "67201", # T.J. Greenan
    "220878597": "67202", # Dan Greenwood
    "131849455": "9999999", # Michael Gross
    "498926637": "67204", # Samuel Guzman
    "230122567": "67205", # Lucas Hale
    "230161888": "67206", # Logan Hall
    "466455315": "67207", # Tyler Hamlin
    "148988166": "67208", # Red Haney
    "263952534": "67209", # Jonathan Hart
    "433011561": "67211", # Heath Hawkins
    "230161596": "67212", # Anthony Hempel
    "168685011": "67214", # Rodger Hernandez
    "584743873": "67213", # Andrew Hernandez
    "430790056": "67215", # Blake Hliva
    "498931049": "67216", # Cole Hudspeth
    "454755960": "67217", # Cody Humes
    "96217713": "67218", # Mark Hutchison
    "579704981": "9999999", # Michelle Jahr
    "116767864": "67219", # Cody Jankowski
    "162053920": "67220", # Kevin Jennings
    "466438093": "67222", # Kenneth Johnson
    "542305055": "67221", # Harold Johnson
    "626265793": "67223", # Erik Johnston
    "626266111": "67224", # Tyrone Joyce
    "127923149": "67225", # Walter Juarez
    "135642264": "9999999", # Steve Kiebzak
    "480051071": "67227", # Jeffery King
    "668863011": "9999999", # Richard Kingham
    "263902565": "67228", # Brad Koenig
    "353548874": "67229", # Marcus Lackey
    "246498242": "67230", # Mathieu Lafreniere
    "96217661": "53351", # Rocky Langone
    "135618356": "67231", # William Lara
    "149768959": "67232", # Wade Lawrence
    "183974147": "67233", # Curtis Lawson
    "579294051": "67235", # Mark Leander
    "148522955": "67236", # Hamilton Ledkins
    "200853353": "67237", # Matthew Lee
    "542315253": "67238", # Nathan Lee
    "626266040": "67239", # Levin Liddell
    "96212216": "67240", # Robert Logan
    "542299758": "67241", # Manuel Longoria
    "353554976": "67244", # Philbert Lopez
    "466444588": "67242", # Isaac Lopez
    "543629832": "67243", # Jose Lopez
    "199798332": "67245", # Kevin Lu
    "550535390": "67246", # Matthew Lu
    "413608007": "67247", # Johnathan Lumpkin
    "498932621": "67248", # Daniel Macias
    "499092010": "67249", # Brian Mackay
    "183974957": "67250", # Michael Manshack
    "498934304": "67251", # Cameron Marlowe
    "660406340": "67252", # Mason Marquez
    "157754747": "67253", # Joe Marroni
    "263949027": "67254", # Steffon Marsh
    "454756071": "67255", # Matthew Martinez
    "187153660": "67256", # Donald May
    "148522950": "67257", # Shawn Maya
    "184654765": "67258", # Forrest McCord
    "148522941": "67259", # Daniel McCune
    "200846740": "67260", # Cody McDougald
    "318973411": "67261", # Omar Medina
    "668874627": "9999999", # Trenton Meisetschleager
    "184695399": "67262", # Mark Millikin
    "498934803": "67263", # Ayden Montemayor
    "413671160": "67264", # Austin Mooney
    "188262378": "67265", # Thomas Moriarty
    "657309359": "67266", # Ian Moscoso
    "466434376": "67267", # Cliff Moulton
    "184691727": "67268", # Christopher Mouton
    "657310585": "67269", # Max Munoz
    "16204520": "67270", # John Nanninga
    "81653805": "67272", # Jeff Paige
    "133940332": "67271", # David Paige
    "466437247": "67273", # Colton Parr
    "48033420": "67274", # Fernando Pecina
    "96217279": "67275", # Chris Pedroza
    "550535987": "67277", # Benny Phan
    "96218861": "67278", # William Plattenburg
    "96207563": "67279", # Josh Posey
    "150951251": "67280", # Brian Powers
    "542305546": "67281", # Andrew Presa
    "584743891": "67282", # Kennedy Ragsdale
    "127924323": "67283", # Richard Rakus
    "135551055": "67285", # Ryan Rebarcak
    "584743902": "67286", # Jonathan Reuscher
    "498939933": "67287", # Deauntae Richardson
    "368172275": "67288", # Keenan Roche
    "626266650": "67289", # Alan Rodriguez
    "177390690": "67290", # Lewis Rougeou
    "318975730": "67291", # Colton Russell
    "626266672": "67292", # Brandon Sanson
    "177430106": "67293", # Andres Santacoloma
    "542310908": "67294", # Nicole Sardelich
    "668879236": "9999999", # Justin Sawtell
    "96216358": "67295", # Steve Schoonover
    "96218911": "44964", # Scott Schoonover
    "178516368": "67296", # Matthew Sears
    "96207782": "67297", # Scott Seifert
    "145773406": "67298", # John Shultz
    "125278219": "67299", # Brent Silvey
    "626265901": "67300", # Daniel Simmons
    "595808248": "67339", # James Singleton
    "601649276": "67301", # Jacob Sisson
    "178510802": "67304", # Nathan Smith
    "245379220": "67303", # Mike Smith
    "630702630": "67302", # Jackie Smith
    "181281996": "9999999", # 70 STATION
    "181282000": "9999999", # 71 STATION
    "181282005": "9999999", # 72 STATION
    "181282008": "9999999", # 73 STATION
    "181282010": "9999999", # 74 STATION
    "181282012": "9999999", # 75 STATION
    "181282015": "9999999", # 76 STATION
    "181282017": "9999999", # 77 STATION
    "181282019": "9999999", # 78 STATION
    "413669935": "67305", # Zane Stavinoha
    "147929020": "67306", # Jimmy Stewart
    "16204512": "67307", # Shannon Stryk
    "353548461": "67308", # William Stuart
    "183987912": "67309", # Sydney Sundell
    "16204515": "67310", # Brian Taylor
    "185710136": "9999999", # Shannon Taylor
    "263905996": "67312", # Joshua Taylor
    "454755870": "67311", # George Taylor
    "246503868": "67313", # Brandon Testut
    "149373486": "67314", # Brian Tharp
    "102679562": "67315", # Blake Thompson
    "57497744": "67316", # Keith Topper
    "168685039": "67317", # Christopher Torres
    "498955887": "67319", # Andrew Veerman
    "668884183": "9999999", # Robert Velasquez
    "168685045": "67321", # Steven Villarreal
    "200856443": "67320", # Michael Villarreal
    "200855949": "67322", # Juan Villatoro
    "668885786": "9999999", # Thomas Vincent
    "150815265": "67323", # Chris vonWiesenthal
    "96625395": "67324", # Jason Wal
    "263862933": "67325", # Colten Walla
    "230116850": "67326", # Aaron Weghorst
    "116767718": "67327", # Timothy Weiman
    "200848179": "67328", # Bradley Whitlock
    "127922808": "53429", # Larry Wilkinson
    "130466337": "67329", # Andrew Williams
    "657310513": "67330", # Samir Williams
    "78790754": "67331", # Jermaine Wilson
    "626266627": "67332", # Liam Wilson
    "127923105": "67333", # Kevin Wise
    "147929055": "67334", # Kevin Wiseman
    "454755975": "67335", # Christopher Yager
    "668886756": "9999999", # Trinton Ynclan
    "642234755": "67336", # Chandler Young
    "96218880": "67337", # Matt Zmolek
    "626266640": "67338", # Kevin Zuniga
}

# Position → Equipment call sign
POSITION_TO_EQUIPMENT: Dict[str, str] = {
    "127517298": "E71",
    "127517542": "E72",
    "127517885": "E73",
    "127517977": "E77",
    "127518597": "E71",
    "127518604": "E72",
    "127518607": "E73",
    "127518611": "E77",
    "127520131": "L74",
    "127520135": "L74",
    "127520137": "L75",
    "127520184": "L75",
    "127520186": "E76",
    "127520258": "E76",
    "127520262": "E78",
    "127520265": "E78",
    "147931775": "D71",
    "161984755": "TW70",
    "161984756": "TW70",
    "341863201": "D72"
}



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
        return data["AssignedShiftList"] or []
    # Some tenants return the array directly
    if isinstance(data, list):
        return data
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

def _to_equipment_call_sign(position_id: str) -> str | None:
    return POSITION_TO_EQUIPMENT.get(str(position_id))

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

    for s in shifts:
        # Expected W2W fields in each shift item
        # Keys often present: W2W_EMPLOYEE_ID, START_DATE, START_TIME, END_DATE, END_TIME, POSITION_ID
        w2w_emp_id = str(s.get("W2W_EMPLOYEE_ID") or "").strip()
        pos_id = str(s.get("POSITION_ID") or "").strip()
        start_date = str(s.get("START_DATE") or "").strip()
        start_time = str(s.get("START_TIME") or "").strip()
        end_date = str(s.get("END_DATE") or "").strip()
        end_time = str(s.get("END_TIME") or "").strip()

        if not (w2w_emp_id and pos_id and start_date and start_time and end_date and end_time):
            continue  # skip incomplete rows

        en_id = _to_en_user_id(w2w_emp_id)
        if en_id is None or str(en_id) == "9999999":
            continue  # user not mapped

        call_sign = _to_equipment_call_sign(pos_id)
        if call_sign is None:
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
        window_start, window_end = make_window_6am_to_6pm(anchor)
    else:
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





# In[3]:


if __name__ == "__main__":
    # Example: build and post the 6am→6am window for 10/30/2025
    # Comment out the call below if you are not ready to POST to EN.
    # result = run_once_for_window("10/30/2025")
    # print(json.dumps(result, indent=2))

    # Print sample normalizations
    build_the_schedule()

