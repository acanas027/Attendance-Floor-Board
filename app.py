"""Floor Board — demo.

Live crew board for the Fill and Pack floors: start-of-shift attendance, tap-to-move
crew tracking, break groups, supervisor view and end-of-shift minutes by area.

Run:  streamlit run floor_board.py
Demo: sample names, memory only (a page refresh resets it).

Moving into the Schedule Board app: add `pages()` to its st.navigation, e.g.
    st.navigation({"Schedule": [...], "Floor Board": floor_board.pages()})
and replace get_state()/_save() with Google Sheets reads/writes.
"""

from __future__ import annotations

import copy
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

# ================= sample data =================

ROLES = {
    "Operator": "#60A5FA",
    "Assistant": "#FBBF24",
    "Palletizer": "#2DD4BF",
    "Kit line": "#C4B5FD",
}

LINE_IDS = [f"L{n}" for n in range(1, 19)]
AREA_TEMPLATE = (
    [{"id": "KIT", "name": "Kit Line", "short": "Kit"}]
    + [{"id": i, "name": f"Line {i[1:]}", "short": i} for i in LINE_IDS]
    + [{"id": "PAL", "name": "Palletizing", "short": "Pallet"},
       {"id": "BRK", "name": "Break", "short": "Break"}]
)

# Break groups for the two break buttons.
BREAK_GROUPS = {
    "A": {"label": "lines Kit Line – 9", "areas": ["KIT"] + [f"L{n}" for n in range(1, 10)]},
    "B": {"label": "lines 10 – 17", "areas": [f"L{n}" for n in range(10, 18)]},
}

FLOORS = {
    "fill": {
        "name": "Fill",
        "lead": "A. Rivera",
        "std": {**{i: 2 for i in LINE_IDS}, "L3": 3, "L7": 3, "L10": 3, "L15": 3, "KIT": 5, "PAL": 6, "BRK": None},
        "employees": [
            ("Maria R.", "Operator", "L1"), ("Jose L.", "Operator", "L1"),
            ("Ana P.", "Operator", "L2"), ("Luis G.", "Operator", "L2"),
            ("Carmen D.", "Operator", "L3"), ("Pedro S.", "Operator", "L3"), ("Sofia M.", "Assistant", "L3"),
            ("Juan C.", "Operator", "L4"), ("Rosa T.", "Operator", "L4"),
            ("Miguel A.", "Operator", "L5"), ("Elena V.", "Operator", "L5"),
            ("Diego F.", "Operator", "L6"), ("Laura B.", "Operator", "L6"),
            ("Carlos N.", "Operator", "L7"), ("Teresa G.", "Operator", "L7"), ("Emilio P.", "Assistant", "L7"),
            ("Isabel Q.", "Operator", "L8"), ("Jorge H.", "Operator", "L8"),
            ("Lucia K.", "Operator", "L9"), ("Raul E.", "Operator", "L9"),
            ("Paula W.", "Operator", "L10"), ("Tomas Y.", "Operator", "L10"), ("Hector Z.", "Assistant", "L10"),
            ("Daniel O.", "Operator", "L11"), ("Marta I.", "Operator", "L11"),
            ("Sergio V.", "Operator", "L12"), ("Andrea F.", "Operator", "L12"),
            ("Victor U.", "Operator", "L13"), ("Silvia J.", "Operator", "L13"),
            ("Pablo X.", "Operator", "L14"), ("Teresa M.", "Operator", "L14"),
            ("Ramon G.", "Operator", "L15"), ("Alicia C.", "Operator", "L15"), ("Ruben L.", "Assistant", "L15"),
            ("Gloria P.", "Operator", "L16"), ("Fernando D.", "Operator", "L16"),
            ("Adrian S.", "Operator", "L17"), ("Beatriz N.", "Operator", "L17"),
            ("Hugo R.", "Operator", "L18"), ("Nora T.", "Operator", "L18"),
            ("Irene A.", "Kit line", "KIT"), ("Oscar B.", "Kit line", "KIT"), ("Clara E.", "Kit line", "KIT"),
            ("Felipe G.", "Kit line", "KIT"), ("Ines H.", "Kit line", "KIT"),
            ("Mateo I.", "Palletizer", "PAL"), ("Julia K.", "Palletizer", "PAL"), ("Samuel L.", "Palletizer", "PAL"),
            ("Rocio M.", "Palletizer", "PAL"), ("Ivan N.", "Palletizer", "PAL"), ("Lorena O.", "Palletizer", "PAL"),
        ],
    },
    "pack": {
        "name": "Pack",
        "lead": "M. Torres",
        "std": {**{i: 2 for i in LINE_IDS}, "L5": 3, "L12": 3, "KIT": 4, "PAL": 4, "BRK": None},
        "employees": [
            ("Alma B.", "Operator", "L1"), ("Bruno C.", "Operator", "L1"),
            ("Celia D.", "Operator", "L2"), ("Dario E.", "Operator", "L2"),
            ("Eva F.", "Operator", "L3"), ("Fabian G.", "Operator", "L3"),
            ("Gina H.", "Operator", "L4"), ("Ivan J.", "Operator", "L4"),
            ("Jana K.", "Operator", "L5"), ("Kevin L.", "Operator", "L5"), ("Lidia M.", "Assistant", "L5"),
            ("Mario N.", "Operator", "L6"), ("Nadia O.", "Operator", "L6"),
            ("Omar P.", "Operator", "L7"), ("Patricia Q.", "Operator", "L7"),
            ("Quique R.", "Operator", "L8"), ("Rita S.", "Operator", "L8"),
            ("Saul T.", "Operator", "L9"), ("Tania U.", "Operator", "L9"),
            ("Ulises V.", "Operator", "L10"), ("Vera W.", "Operator", "L10"),
            ("Walter X.", "Operator", "L11"), ("Ximena Y.", "Operator", "L11"),
            ("Yago Z.", "Operator", "L12"), ("Zoe A.", "Operator", "L12"), ("Abel B.", "Assistant", "L12"),
            ("Berta C.", "Operator", "L13"), ("Cesar D.", "Operator", "L13"),
            ("Dalia E.", "Operator", "L14"), ("Efren F.", "Operator", "L14"),
            ("Flor G.", "Operator", "L15"), ("Gabriel H.", "Operator", "L15"),
            ("Hilda I.", "Operator", "L16"), ("Ignacio J.", "Operator", "L16"),
            ("Julieta K.", "Operator", "L17"), ("Kike L.", "Operator", "L17"),
            ("Lorenzo M.", "Operator", "L18"), ("Marisol N.", "Operator", "L18"),
            ("Noemi O.", "Kit line", "KIT"), ("Oscar P.", "Kit line", "KIT"),
            ("Pilar Q.", "Kit line", "KIT"), ("Rafael R.", "Kit line", "KIT"),
            ("Selena S.", "Palletizer", "PAL"), ("Tobias T.", "Palletizer", "PAL"),
            ("Ursula U.", "Palletizer", "PAL"), ("Vicente V.", "Palletizer", "PAL"),
        ],
    },
}

# Demo logins. Leads open their own floor; supervisors pick a floor.
USERS = [
    {"name": "A. Rivera", "pin": "1111", "role": "Lead", "floor": "fill"},
    {"name": "M. Torres", "pin": "2222", "role": "Lead", "floor": "pack"},
    {"name": "D. Morgan", "pin": "9999", "role": "Supervisor", "floor": None},
]
LOGIN_HOURS = 12

SHIFTS = {"1st shift": (6, 0), "2nd shift": (16, 0)}
CHECK_EVERY_MIN = 120

# ================= state and rules =================

TZ = ZoneInfo("America/Chicago")
BOX = None  # an employee not on any area is "in the box"
STATE_KEY = "floor_board"
AUTH_KEY = "floor_board_auth"


def _fresh_floor(key: str) -> dict:
    cfg = FLOORS[key]
    employees = [{"id": f"{key[0].upper()}{i:03d}", "name": n, "role": r, "home": h}
                 for i, (n, r, h) in enumerate(cfg["employees"], start=1)]
    areas = [dict(a, std=cfg["std"].get(a["id"])) for a in AREA_TEMPLATE]
    return {
        "key": key, "name": cfg["name"], "lead": cfg["lead"],
        "employees": employees, "areas": areas,
        "assign": {e["id"]: BOX for e in employees},
        "selected": None,
        "attendance_confirmed": False, "attendance_time": None,
        "attendance": {},      # eid -> {"status": Present|Absent|Late, "time": datetime}
        "left": {},            # eid -> time sent back to the box after attendance
        "open": {},            # eid -> (area_id, start)
        "intervals": [],       # {"eid", "area", "start", "end"}
        "events": [],          # {"t", "kind", "text"}
        "break_from": {},      # eid -> area they were on before a group break
        "group_break": {g: False for g in BREAK_GROUPS},
        "last_check": None, "checkins": 0,
        "ended": False, "end_time": None,
    }


def _fresh_state() -> dict:
    return {
        "floors": {k: _fresh_floor(k) for k in FLOORS},
        "users": copy.deepcopy(USERS),
        "shift": "1st shift",
        "clock_mode": "demo",  # "demo" = clock moves with the sidebar buttons; "real" = wall clock
        "demo_minutes": 0,
    }


def get_state() -> dict:
    if STATE_KEY not in st.session_state:
        st.session_state[STATE_KEY] = _fresh_state()
    return st.session_state[STATE_KEY]


def reset() -> None:
    st.session_state[STATE_KEY] = _fresh_state()


def _save(f: dict) -> None:
    """Live version: write the floor's changes to the backend here. Demo: nothing to do."""


# ---------- lookups ----------

def emp(f: dict, eid: str) -> dict:
    return next(e for e in f["employees"] if e["id"] == eid)


def area(f: dict, aid: str | None) -> dict | None:
    return next((a for a in f["areas"] if a["id"] == aid), None)


def area_short(f: dict, aid: str | None) -> str:
    return "Box" if aid is BOX else area(f, aid)["short"]


def crew(f: dict, aid: str | None) -> list[dict]:
    return [e for e in f["employees"] if f["assign"].get(e["id"]) == aid]


# ---------- clock ----------

def shift_start() -> datetime:
    h, m = SHIFTS[get_state()["shift"]]
    today = datetime.now(TZ).date()
    return datetime(today.year, today.month, today.day, h, m, tzinfo=TZ)


def now() -> datetime:
    g = get_state()
    if g["clock_mode"] == "demo":
        return shift_start() + timedelta(minutes=g["demo_minutes"])
    return datetime.now(TZ)


def advance_clock(minutes: int) -> None:
    get_state()["demo_minutes"] += minutes


def fmt(t: datetime | None) -> str:
    return "" if t is None else t.strftime("%I:%M %p").lstrip("0")


def fmt_min(m: float) -> str:
    m = int(round(m))
    return f"{m // 60}h {m % 60:02d}m"


# ---------- actions ----------

def _log(f: dict, kind: str, text: str) -> None:
    f["events"].insert(0, {"t": now(), "kind": kind, "text": text})


def select(f: dict, eid: str) -> None:
    if not f["ended"]:
        f["selected"] = None if f["selected"] == eid else eid


def cancel_selection(f: dict) -> None:
    f["selected"] = None


def _move(f: dict, eid: str, target: str | None, log: bool = True) -> None:
    """Move one employee. Before attendance is confirmed nothing is timed."""
    prev = f["assign"][eid]
    if prev == target:
        return
    f["assign"][eid] = target
    if target != "BRK":
        f["break_from"].pop(eid, None)
    if not f["attendance_confirmed"]:
        return

    t = now()
    e = emp(f, eid)
    if eid in f["open"]:
        a, start = f["open"].pop(eid)
        f["intervals"].append({"eid": eid, "area": a, "start": start, "end": t})
    if target is not BOX:
        f["open"][eid] = (target, t)

    att = f["attendance"][eid]
    if prev is BOX and target is not BOX:
        if att["status"] == "Absent":
            att.update(status="Late", time=t)
            if log:
                _log(f, "late", f"{e['name']} arrived late → {area_short(f, target)}")
        else:
            f["left"].pop(eid, None)
            if log:
                _log(f, "move", f"{e['name']} back on the floor → {area_short(f, target)}")
    elif target is BOX:
        f["left"][eid] = t
        if log:
            _log(f, "left", f"{e['name']} left the floor ({area_short(f, prev)} → Box)")
    elif log:
        _log(f, "move", f"{e['name']}  {area_short(f, prev)} → {area_short(f, target)}")


def move_selected(f: dict, target: str | None) -> None:
    eid = f["selected"]
    f["selected"] = None
    if eid is None or f["ended"]:
        return
    _move(f, eid, target)
    _save(f)


def toggle_group_break(f: dict, g: str) -> None:
    """Send everyone on a break group's lines to Break, or bring them back to the line they left."""
    if not f["attendance_confirmed"] or f["ended"]:
        return
    grp = BREAK_GROUPS[g]
    f["selected"] = None
    if not f["group_break"][g]:
        people = [e for e in f["employees"] if f["assign"][e["id"]] in grp["areas"]]
        for e in people:
            prev = f["assign"][e["id"]]
            _move(f, e["id"], "BRK", log=False)
            f["break_from"][e["id"]] = prev
        f["group_break"][g] = True
        _log(f, "break", f"{grp['label'][0].upper() + grp['label'][1:]} sent to break ({len(people)} people)")
    else:
        back = [eid for eid, a in f["break_from"].items()
                if a in grp["areas"] and f["assign"][eid] == "BRK"]
        for eid in back:
            _move(f, eid, f["break_from"][eid], log=False)
        f["group_break"][g] = False
        _log(f, "break", f"{grp['label'][0].upper() + grp['label'][1:]} back from break ({len(back)} people)")
    _save(f)


def load_usual_layout(f: dict) -> None:
    if not f["attendance_confirmed"]:
        for e in f["employees"]:
            f["assign"][e["id"]] = e["home"]
        f["selected"] = None


def clear_board(f: dict) -> None:
    if not f["attendance_confirmed"]:
        for e in f["employees"]:
            f["assign"][e["id"]] = BOX
        f["selected"] = None


def confirm_attendance(f: dict, by: str) -> None:
    if f["attendance_confirmed"]:
        return
    t = now()
    present = absent = 0
    for e in f["employees"]:
        aid = f["assign"][e["id"]]
        if aid is BOX:
            f["attendance"][e["id"]] = {"status": "Absent", "time": t}
            absent += 1
        else:
            f["attendance"][e["id"]] = {"status": "Present", "time": t}
            f["open"][e["id"]] = (aid, t)
            present += 1
    f.update(attendance_confirmed=True, attendance_time=t, last_check=t, selected=None)
    _log(f, "attendance", f"Attendance confirmed by {by}: {present} present, {absent} absent")
    _save(f)


def confirm_board(f: dict, by: str) -> None:
    if not f["attendance_confirmed"] or f["ended"]:
        return
    on_time = check_minutes_left(f) >= 0
    f["last_check"] = now()
    f["checkins"] += 1 if on_time else 0
    _log(f, "check", f"Board confirmed correct by {by}" + ("" if on_time else " (late)"))
    _save(f)


def end_shift(f: dict, by: str) -> None:
    if not f["attendance_confirmed"] or f["ended"]:
        return
    t = now()
    for eid, (a, start) in list(f["open"].items()):
        f["intervals"].append({"eid": eid, "area": a, "start": start, "end": t})
    f["open"].clear()
    f.update(ended=True, end_time=t, selected=None)
    _log(f, "end", f"Shift ended by {by} · all times closed")
    _save(f)


# ---------- read models ----------

def check_minutes_left(f: dict) -> int:
    if not f["attendance_confirmed"] or f["last_check"] is None:
        return CHECK_EVERY_MIN
    due = f["last_check"] + timedelta(minutes=CHECK_EVERY_MIN)
    return int((due - now()).total_seconds() // 60)


def minutes_by_area(f: dict, eid: str) -> dict[str, float]:
    out: dict[str, float] = {}
    for iv in f["intervals"]:
        if iv["eid"] == eid:
            out[iv["area"]] = out.get(iv["area"], 0) + (iv["end"] - iv["start"]).total_seconds() / 60
    if eid in f["open"]:
        a, start = f["open"][eid]
        out[a] = out.get(a, 0) + max(0.0, (now() - start).total_seconds() / 60)
    return out


def summary_rows(f: dict) -> list[dict]:
    rows = []
    for e in f["employees"]:
        att = f["attendance"].get(e["id"], {})
        status = att.get("status", "Not confirmed")
        if status == "Late":
            status = f"Late ({fmt(att['time'])})"
        if e["id"] in f["left"]:
            status += f" · left {fmt(f['left'][e['id']])}"
        mins = minutes_by_area(f, e["id"])
        brk = mins.pop("BRK", 0)
        rows.append({
            "Employee": e["name"], "Role": e["role"], "Attendance": status, "areas": mins,
            "Time by area": " · ".join(f"{area_short(f, a)} {fmt_min(m)}" for a, m in mins.items() if m >= 1),
            "Break": fmt_min(brk) if brk >= 1 else "",
            "Worked": fmt_min(sum(mins.values())),
        })
    return rows


def on_group_break(f: dict, aid: str) -> bool:
    return any(f["group_break"][g] and aid in grp["areas"] for g, grp in BREAK_GROUPS.items())


def short_areas(f: dict) -> list[tuple[dict, int]]:
    out = []
    for a in f["areas"]:
        if a["std"] is not None and a["id"] != "BRK" and not on_group_break(f, a["id"]):
            n = len(crew(f, a["id"]))
            if n < a["std"]:
                out.append((a, n))
    return out


def moves_count(f: dict) -> int:
    return sum(1 for ev in f["events"] if ev["kind"] in ("move", "late", "left"))


# ================= login =================

def current_user() -> dict | None:
    a = st.session_state.get(AUTH_KEY)
    if a and datetime.now(TZ) - a["at"] < timedelta(hours=LOGIN_HOURS):
        return a
    st.session_state.pop(AUTH_KEY, None)
    return None


def logout() -> None:
    st.session_state.pop(AUTH_KEY, None)


def require_login(purpose: str) -> dict | None:
    """Returns the logged-in user, or draws the PIN form and returns None."""
    u = current_user()
    if u:
        return u
    users = get_state()["users"]
    st.markdown(f"### Sign in")
    st.caption(f"Sign in to {purpose}. You stay signed in for {LOGIN_HOURS} hours on this device.")
    with st.form("fb_login", border=True):
        name = st.selectbox("Name", [x["name"] for x in users])
        pin = st.text_input("PIN", type="password", max_chars=6)
        if st.form_submit_button("Sign in", type="primary"):
            match = next((x for x in users if x["name"] == name and x["pin"] == pin), None)
            if match:
                st.session_state[AUTH_KEY] = {**match, "at": datetime.now(TZ)}
                st.rerun()
            st.error("Wrong PIN.")
    st.caption("Demo PINs: " + " · ".join(f"{x['name']} ({x['role']}, "
                                         f"{FLOORS[x['floor']]['name'] if x['floor'] else 'both floors'}) {x['pin']}"
                                         for x in users))
    return None


def _floor_for(u: dict, key: str) -> dict:
    """Leads get their own floor; supervisors choose."""
    g = get_state()
    if u["floor"]:
        return g["floors"][u["floor"]]
    pick = st.segmented_control("Floor", list(FLOORS), format_func=lambda k: FLOORS[k]["name"],
                                default="fill", key=f"floor_pick_{key}", required=True)
    return g["floors"][pick or "fill"]


# ================= screens =================

ROLE_KEY = {"Operator": "op", "Assistant": "as", "Palletizer": "pa", "Kit line": "kt"}
GRID_COLS = 7

CSS = """
<style>
/* chips: one per employee, colored by role */
[class*="st-key-chip-"] button {
  border-radius: 999px; border: 0; min-height: 40px; padding: 2px 14px; font-weight: 700;
}
[class*="st-key-chip-op-"] button { background: #60A5FA; }
[class*="st-key-chip-as-"] button { background: #FBBF24; }
[class*="st-key-chip-pa-"] button { background: #2DD4BF; }
[class*="st-key-chip-kt-"] button { background: #C4B5FD; }
[class*="st-key-chip-"] button:hover { filter: brightness(1.1); }
[class*="st-key-chip-"][class*="-sel-"] button { outline: 3px solid #FACC15; outline-offset: 2px; transform: scale(1.05); }
[class*="st-key-chip-"][class*="-dim-"] button { opacity: .7; }

/* buttons: dark text on yellow */
button[kind="primary"], button[kind="primaryFormSubmit"] { background: #FACC15 !important; border-color: #FACC15 !important; }
button[kind="primary"] p, button[kind="primaryFormSubmit"] p, [class*="st-key-chip-"] button p, [class*="st-key-zh-target-"] button p {
  color: #0B1220 !important; font-weight: 700;
}
[class*="st-key-zh-target-"] button { min-height: 44px; border: 0; background: #FACC15; }

/* area tiles */
[class*="st-key-zone-"] { background: #131C2E; border-radius: 14px; }
[class*="st-key-zone-short-"] { border: 1px solid #F87171 !important; }
[class*="st-key-zone-target-"] { border: 1px solid #FACC15 !important; }
[class*="st-key-zone-brk-"] { border: 1px dashed #475569 !important; background: #0F1626; }
[class*="st-key-boxzone"] { background: #131C2E; border-radius: 14px; }
.fb-zh { color:#E5ECF6; display:flex; justify-content:space-between; align-items:center; gap:6px; min-height:44px;
  padding:0 10px; border-radius:10px; background:#1B2740; font-weight:700; font-size:14px; white-space:nowrap; }
.fb-onbrk { color:#94A3B8; font-size:13px; font-weight:600; text-align:center; padding:4px 0; }
.fb-zh span { color:#94A3B8; font-size:14px; }
.fb-zh.short span { color:#FCA5A5; }
.fb-zh.brk { background:#151E30; }
.fb-boxtitle { color:#E5ECF6; font-weight:700; padding:4px 0; }
.fb-boxtitle span { color:#94A3B8; font-weight:400; }

/* pills and strips */
.fb-pill { color:#E5ECF6; display:inline-block; padding:6px 12px; border-radius:12px; background:#131C2E;
  border:1px solid #26344D; font-size:14px; margin:0 6px 6px 0; }
.fb-live { display:inline-block; padding:3px 10px; border-radius:999px; background:#0F2A1E; color:#4ADE80;
  font-size:12px; font-weight:700; letter-spacing:.06em; }
.fb-floor { display:inline-block; padding:3px 10px; border-radius:999px; background:#1B2740; color:#E5ECF6;
  font-size:12px; font-weight:700; letter-spacing:.06em; }
.fb-due { display:inline-block; padding:8px 12px; border-radius:12px; font-weight:600; font-size:14px; }
.fb-hint { padding:10px 14px; border-radius:12px; background:#FACC15; color:#0B1220; font-weight:600; }
.fb-move { color:#E5ECF6; display:inline-block; padding:6px 10px; border-radius:10px; background:#1B2740;
  font-size:13px; margin:0 6px 6px 0; }
.fb-move span { color:#94A3B8; margin-right:6px; }
.fb-legend span { display:inline-flex; align-items:center; gap:5px; margin-right:12px; font-size:13px; color:#94A3B8; }
.fb-legend i { width:10px; height:10px; border-radius:50%; display:inline-block; }

/* read-only floor view */
.fb-grid { display:grid; grid-template-columns:repeat(7, minmax(0,1fr)); gap:10px; align-items:start; }
.fb-tile { background:#131C2E; border:1px solid #26344D; border-radius:14px; padding:6px;
  display:flex; flex-direction:column; gap:6px; min-height:120px; }
.fb-tile.short { border-color:#F87171; }
.fb-tile.brk { border-style:dashed; border-color:#475569; background:#0F1626; }
.fb-name { border-radius:999px; padding:8px 10px; font-weight:700; font-size:14px; color:#0B1220; text-align:center; }
.fb-box { background:#131C2E; border:1px solid #26344D; border-radius:14px; padding:10px 12px; margin-bottom:10px;
  display:flex; flex-wrap:wrap; gap:6px; align-items:center; }
</style>
"""


def _header(f: dict, title: str) -> None:
    on_floor = sum(1 for e in f["employees"] if f["assign"][e["id"]] not in (BOX, "BRK"))
    in_box = len(crew(f, BOX))
    box_label = "Absent" if f["attendance_confirmed"] else "Not placed"
    left, right = st.columns([3, 2], vertical_alignment="center")
    left.markdown(
        f"### {title} &nbsp;<span class='fb-floor'>{f['name'].upper()}</span> <span class='fb-live'>LIVE</span>\n"
        f"{get_state()['shift']} · Floor lead: {f['lead']} · {fmt(now())}",
        unsafe_allow_html=True,
    )
    right.markdown(
        f"<span class='fb-pill'>On floor <b>{on_floor}</b></span>"
        f"<span class='fb-pill'>{box_label} <b>{in_box}</b></span>"
        f"<span class='fb-pill'>On break <b>{len(crew(f, 'BRK'))}</b></span>"
        f"<span class='fb-pill'>Moves <b>{moves_count(f)}</b></span>",
        unsafe_allow_html=True,
    )


def _legend() -> None:
    items = "".join(f'<span><i style="background:{c}"></i>{r}</span>' for r, c in ROLES.items())
    st.markdown(f'<div class="fb-legend">{items}</div>', unsafe_allow_html=True)


def _latest(f: dict, n: int = 5) -> None:
    if f["events"]:
        html = "".join(f"<span class='fb-move'><span>{fmt(ev['t'])}</span>{ev['text']}</span>" for ev in f["events"][:n])
        st.markdown("**Latest** &nbsp; " + html, unsafe_allow_html=True)


# ---------- read-only floor views ----------

def _view(floor_key: str) -> None:
    st.markdown(CSS, unsafe_allow_html=True)

    @st.fragment(run_every="10s")
    def _live() -> None:
        f = get_state()["floors"][floor_key]
        _header(f, "Floor view")
        if not f["attendance_confirmed"]:
            st.caption("Attendance not confirmed yet.")
        _legend()
        absent = crew(f, BOX)
        if absent:
            label = "Absent / off the floor" if f["attendance_confirmed"] else "Not placed yet"
            names = "".join(f"<span class='fb-name' style='background:{ROLES[e['role']]}'>{e['name']}</span>" for e in absent)
            st.markdown(f"<div class='fb-box'><span class='fb-boxtitle'>{label} <span>· {len(absent)}</span></span>{names}</div>",
                        unsafe_allow_html=True)
        tiles = []
        for a in f["areas"]:
            people = crew(f, a["id"])
            n = len(people)
            on_brk = on_group_break(f, a["id"])
            short = a["std"] is not None and n < a["std"] and f["attendance_confirmed"] and not on_brk
            cls = "brk" if a["id"] == "BRK" or on_brk else ("short" if short else "")
            count = "" if on_brk else str(n) if a["std"] is None else f"{n}/{a['std']}"
            names = "".join(f"<div class='fb-name' style='background:{ROLES[e['role']]}'>{e['name']}</div>" for e in people)
            onbrk = "<div class='fb-onbrk'>On break</div>" if on_brk else ""
            tiles.append(f"<div class='fb-tile {cls}'><div class='fb-zh {cls}'>{a['name']}<span>{count}</span></div>{onbrk}{names}</div>")
        st.markdown(f"<div class='fb-grid'>{''.join(tiles)}</div>", unsafe_allow_html=True)
        _latest(f)

    _live()


def view_fill() -> None:
    _view("fill")


def view_pack() -> None:
    _view("pack")


# ---------- update (sign-in, move people) ----------

@st.dialog("Confirm attendance")
def _attendance_dialog(f: dict, by: str) -> None:
    absent = crew(f, BOX)
    present = len(f["employees"]) - len(absent)
    st.write(f"**{present} present** (on a line) · **{len(absent)} absent** (still in the box)")
    if absent:
        st.caption("Will be marked absent: " + ", ".join(e["name"] for e in absent))
    st.caption("Line time starts now. Anyone placed later from the box is recorded as late.")
    c1, c2 = st.columns(2)
    if c1.button("Confirm", type="primary", width="stretch"):
        confirm_attendance(f, by)
        st.rerun()
    if c2.button("Go back", width="stretch"):
        st.rerun()


@st.dialog("End shift")
def _end_dialog(f: dict, by: str) -> None:
    st.write(f"This closes everyone's time on the {f['name']} floor at {fmt(now())} and locks the board.")
    c1, c2 = st.columns(2)
    if c1.button("End shift", type="primary", width="stretch"):
        end_shift(f, by)
        st.rerun()
    if c2.button("Cancel", width="stretch"):
        st.rerun()


def _chip(f: dict, e: dict, where: str) -> None:
    sel = f["selected"]
    state = "sel" if sel == e["id"] else ("dim" if sel else "n")
    st.button(
        e["name"], key=f"chip-{ROLE_KEY[e['role']]}-{state}-{where}-{e['id']}",
        on_click=select, args=(f, e["id"]), help=f"{e['name']} · {e['role']}",
        disabled=f["ended"], width="stretch" if where == "tile" else "content",
    )


def _tile(f: dict, a: dict) -> None:
    people = crew(f, a["id"])
    n = len(people)
    sel = f["selected"]
    is_target = bool(sel) and f["assign"][sel] != a["id"]
    on_brk = on_group_break(f, a["id"])
    is_short = a["std"] is not None and n < a["std"] and f["attendance_confirmed"] and not on_brk
    state = "target" if is_target else "brk" if a["id"] == "BRK" or on_brk else "short" if is_short else "ok"
    count = "" if on_brk else str(n) if a["std"] is None else f"{n}/{a['std']}"
    with st.container(border=True, key=f"zone-{state}-{f['key']}-{a['id']}"):
        if is_target:
            st.button(f"Move to {a['short']}", key=f"zh-target-{f['key']}-{a['id']}", on_click=move_selected,
                      args=(f, a["id"]), width="stretch", help=f"Move to {a['name']}")
        else:
            st.markdown(f"<div class='fb-zh {state}'>{a['name']}<span>{count}</span></div>"
                        + ("<div class='fb-onbrk'>On break</div>" if on_brk else ""), unsafe_allow_html=True)
        for e in people:
            _chip(f, e, "tile")


def update_page() -> None:
    st.markdown(CSS, unsafe_allow_html=True)
    u = require_login("update the floor")
    if not u:
        return
    f = _floor_for(u, "update")
    by = u["name"]
    _header(f, "Floor Board")
    in_box = len(crew(f, BOX))

    if f["ended"]:
        st.success(f"Shift ended at {fmt(f['end_time'])}. See End of shift for the totals.")
    elif not f["attendance_confirmed"]:
        st.info("**Start of shift:** tap a name, then tap the line they're working. When everyone who's here is "
                "placed, confirm attendance. Anyone left in the box is marked absent.")
        a, b, c = st.columns([1, 1, 2])
        a.button("Load usual layout", on_click=load_usual_layout, args=(f,), width="stretch")
        b.button("Clear board", on_click=clear_board, args=(f,), width="stretch")
        present = len(f["employees"]) - in_box
        if c.button(f"Confirm attendance · {present} present · {in_box} absent", type="primary", width="stretch"):
            _attendance_dialog(f, by)
    else:
        left = check_minutes_left(f)
        pill = (f"<span class='fb-due' style='background:#2A2111;color:#FBBF24'>Board check due in {left} min</span>"
                if left >= 0 else
                f"<span class='fb-due' style='background:#2A1517;color:#FCA5A5'>Board check overdue by {-left} min</span>")
        a, d, e_ = st.columns([3, 2, 1], vertical_alignment="center")
        a.markdown(pill, unsafe_allow_html=True)
        d.button("Board is correct", type="primary", on_click=confirm_board, args=(f, by), width="stretch")
        if e_.button("End shift", width="stretch"):
            _end_dialog(f, by)
        for col, g in zip(st.columns(2), BREAK_GROUPS):
            grp = BREAK_GROUPS[g]
            label = (f"Bring {grp['label']} back from break" if f["group_break"][g]
                     else f"Send {grp['label']} to break")
            col.button(label, key=f"grpbrk-{f['key']}-{g}", on_click=toggle_group_break, args=(f, g), width="stretch")

    if f["selected"]:
        e = emp(f, f["selected"])
        h1, h2 = st.columns([5, 1], vertical_alignment="center")
        h1.markdown(f"<div class='fb-hint'>Moving {e['name']} — tap <b>Move to …</b> on the area they're going to.</div>",
                    unsafe_allow_html=True)
        h2.button("Cancel", on_click=cancel_selection, args=(f,), width="stretch")
    else:
        _legend()

    sel = f["selected"]
    with st.container(border=True, key=f"boxzone-{f['key']}"):
        title = "Absent / off the floor" if f["attendance_confirmed"] else "Not placed yet"
        if sel and f["assign"][sel] is not BOX:
            label = "Move here · left the floor" if f["attendance_confirmed"] else "Move here · back to the box"
            st.button(label, key=f"zh-target-{f['key']}-BOX", on_click=move_selected, args=(f, BOX), width="stretch")
        else:
            st.markdown(f"<div class='fb-boxtitle'>{title} <span>· {in_box}</span></div>", unsafe_allow_html=True)
        with st.container(horizontal=True, wrap=True, gap="small"):
            for e in crew(f, BOX):
                _chip(f, e, "box")

    areas = f["areas"]
    for i in range(0, len(areas), GRID_COLS):
        for col, a in zip(st.columns(GRID_COLS, gap="small"), areas[i:i + GRID_COLS]):
            with col:
                _tile(f, a)
    _latest(f)


# ---------- supervisor view (sign-in) ----------

def supervisor_page() -> None:
    st.markdown(CSS, unsafe_allow_html=True)
    u = require_login("see the supervisor view")
    if not u:
        return
    f = _floor_for(u, "supervisor")
    st.markdown(f"### Live floor &nbsp;<span class='fb-floor'>{f['name'].upper()}</span> <span class='fb-live'>LIVE</span>",
                unsafe_allow_html=True)
    st.caption(f"{get_state()['shift']} · lead {f['lead']} · as of {fmt(now())}")

    att = f["attendance"]
    ok = f["attendance_confirmed"]
    short = short_areas(f) if ok else []
    m = st.columns(5)
    m[0].metric("On the floor", sum(1 for e in f["employees"] if f["assign"][e["id"]] not in (BOX, "BRK")),
                help=f"{len(crew(f, 'BRK'))} on break")
    m[1].metric("Absent", sum(1 for v in att.values() if v["status"] == "Absent") if ok else "—")
    m[2].metric("Late", sum(1 for v in att.values() if v["status"] == "Late") if ok else "—")
    m[3].metric("Areas short", len(short) if ok else "—")
    m[4].metric("Moves", moves_count(f))

    if not ok:
        st.info("Attendance not confirmed yet. Line time starts when the floor lead confirms.")
    else:
        st.markdown("**Needs attention**")
        left = check_minutes_left(f)
        alerts = 0
        if left < 0 and not f["ended"]:
            st.warning(f"Board check overdue by {-left} min ({f['lead']})")
            alerts += 1
        for a, n in short:
            st.error(f"{a['name']}: {n} of {a['std']}")
            alerts += 1
        if not alerts:
            st.success("All areas staffed and the board is up to date.")

    st.markdown("**Crews**")
    rows = [{"Area": a["name"], "Crew": ", ".join(e["name"] for e in crew(f, a["id"])),
             "On crew": len(crew(f, a["id"])), "Minimum": a["std"]} for a in f["areas"]]
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch", height=420)

    st.markdown("**Latest moves**")
    if f["events"]:
        st.dataframe(pd.DataFrame([{"Time": fmt(ev["t"]), "What": ev["text"]} for ev in f["events"][:10]]),
                     hide_index=True, width="stretch")
    else:
        st.caption("No moves yet.")


# ---------- end of shift (sign-in) ----------

def summary_page() -> None:
    st.markdown(CSS, unsafe_allow_html=True)
    u = require_login("see the end of shift report")
    if not u:
        return
    f = _floor_for(u, "summary")
    st.markdown(f"### End of shift · time by area &nbsp;<span class='fb-floor'>{f['name'].upper()}</span>",
                unsafe_allow_html=True)
    if not f["attendance_confirmed"]:
        st.info("Nothing recorded yet. Time starts when attendance is confirmed on the Update page.")
        return
    if f["ended"]:
        st.caption(f"{get_state()['shift']} · {fmt(f['attendance_time'])} – {fmt(f['end_time'])} · built from the board moves")
    else:
        st.caption(f"Shift in progress · totals as of {fmt(now())} · the floor lead ends the shift on the Update page")

    rows = summary_rows(f)
    st.dataframe(pd.DataFrame(rows)[["Employee", "Role", "Attendance", "Time by area", "Break", "Worked"]],
                 hide_index=True, width="stretch", height=460)

    long_rows = [{"Floor": f["name"], "Employee": r["Employee"], "Role": r["Role"],
                  "Area": area(f, a)["name"], "Minutes": round(mins)}
                 for r in rows for a, mins in r["areas"].items()]
    att_rows = [{"Floor": f["name"], "Employee": r["Employee"], "Role": r["Role"], "Attendance": r["Attendance"]}
                for r in rows]
    log_rows = [{"Time": fmt(ev["t"]), "Event": ev["text"]} for ev in reversed(f["events"])]
    k = f["name"].lower()
    d1, d2, d3 = st.columns(3)
    d1.download_button("Minutes by area (CSV)", pd.DataFrame(long_rows).to_csv(index=False),
                       f"{k}_minutes_by_area.csv", "text/csv", width="stretch")
    d2.download_button("Attendance (CSV)", pd.DataFrame(att_rows).to_csv(index=False),
                       f"{k}_attendance.csv", "text/csv", width="stretch")
    d3.download_button("Move log (CSV)", pd.DataFrame(log_rows).to_csv(index=False),
                       f"{k}_move_log.csv", "text/csv", width="stretch")
    st.markdown("**Move log**")
    st.dataframe(pd.DataFrame(log_rows), hide_index=True, width="stretch")


# ---------- setup (sign-in) ----------

def setup_page() -> None:
    st.markdown(CSS, unsafe_allow_html=True)
    u = require_login("change the setup")
    if not u:
        return
    g = get_state()
    f = _floor_for(u, "setup")
    st.markdown(f"### Setup &nbsp;<span class='fb-floor'>{f['name'].upper()}</span>", unsafe_allow_html=True)
    locked = f["attendance_confirmed"]

    c1, c2 = st.columns(2)
    f["lead"] = c1.text_input("Floor lead", f["lead"], key=f"lead_{f['key']}")
    g["shift"] = c2.selectbox("Shift (both floors)", list(SHIFTS), index=list(SHIFTS).index(g["shift"]),
                              disabled=any(x["attendance_confirmed"] for x in g["floors"].values()))

    st.markdown("**Minimum staff by area**")
    area_df = pd.DataFrame([{"Area": a["name"], "Minimum staff": a["std"]} for a in f["areas"] if a["id"] != "BRK"])
    edited = st.data_editor(area_df, hide_index=True, disabled=["Area"], key=f"areas_editor_{f['key']}", width="stretch",
                            column_config={"Minimum staff": st.column_config.NumberColumn(min_value=0, step=1)})
    for a, std in zip([a for a in f["areas"] if a["id"] != "BRK"], edited["Minimum staff"]):
        a["std"] = None if pd.isna(std) else int(std)

    st.markdown("**Roster**")
    if locked:
        st.caption("Roster is locked after attendance is confirmed. Reset the demo to edit it.")
    names = {a["id"]: a["name"] for a in f["areas"]}
    ids = {v: k for k, v in names.items()}
    roster = st.data_editor(
        pd.DataFrame([{"Name": e["name"], "Role": e["role"], "Usual area": names.get(e["home"], "")}
                      for e in f["employees"]]),
        hide_index=True, num_rows="fixed" if locked else "dynamic", disabled=locked,
        key=f"roster_editor_{f['key']}", width="stretch",
        column_config={"Role": st.column_config.SelectboxColumn(options=list(ROLES), required=True),
                       "Usual area": st.column_config.SelectboxColumn(options=list(names.values()))},
    )
    if not locked and st.button("Save roster"):
        new = [{"id": f"{f['key'][0].upper()}{i + 1:03d}", "name": r["Name"].strip(),
                "role": r["Role"] if r["Role"] in ROLES else "Operator", "home": ids.get(r["Usual area"], "L1")}
               for i, r in roster.iterrows() if isinstance(r["Name"], str) and r["Name"].strip()]
        f.update(employees=new, assign={e["id"]: BOX for e in new}, selected=None)
        st.success(f"Roster saved: {len(new)} employees, all back in the box.")

    if u["role"] == "Supervisor":
        st.markdown("**Logins (demo)**")
        users = st.data_editor(
            pd.DataFrame([{"Name": x["name"], "PIN": x["pin"], "Role": x["role"],
                           "Floor": FLOORS[x["floor"]]["name"] if x["floor"] else "Both"} for x in g["users"]]),
            hide_index=True, num_rows="dynamic", key="users_editor", width="stretch",
            column_config={"Role": st.column_config.SelectboxColumn(options=["Lead", "Supervisor"], required=True),
                           "Floor": st.column_config.SelectboxColumn(options=["Fill", "Pack", "Both"], required=True)},
        )
        if st.button("Save logins"):
            back = {"Fill": "fill", "Pack": "pack", "Both": None}
            g["users"] = [{"name": r["Name"], "pin": str(r["PIN"]), "role": r["Role"], "floor": back.get(r["Floor"])}
                          for _, r in users.iterrows() if isinstance(r["Name"], str) and r["Name"].strip()]
            st.success("Logins saved.")

    st.divider()
    st.markdown("**Demo**")
    g["clock_mode"] = st.radio("Clock", ["demo", "real"], index=["demo", "real"].index(g["clock_mode"]), horizontal=True,
                               format_func=lambda v: "Demo clock (sidebar buttons)" if v == "demo" else "Real time")
    if st.button("Reset demo (both floors)"):
        reset()
        st.rerun()


# ================= navigation =================

def _sidebar() -> None:
    g = get_state()
    with st.sidebar:
        st.markdown("**Floor Board demo**")
        st.caption("Memory only: refreshing the page resets the demo.")
        if g["clock_mode"] == "demo":
            st.markdown(f"Demo clock: **{fmt(now())}**")
            b1, b2 = st.columns(2)
            b1.button("+15 min", on_click=advance_clock, args=(15,), width="stretch")
            b2.button("+1 hour", on_click=advance_clock, args=(60,), width="stretch")
        else:
            st.markdown(f"Clock: **{fmt(now())}** (real time)")
        u = current_user()
        if u:
            st.divider()
            where = FLOORS[u["floor"]]["name"] if u["floor"] else "both floors"
            st.markdown(f"Signed in: **{u['name']}** · {u['role']}, {where}")
            st.button("Sign out", on_click=logout, width="stretch")


def pages() -> list:
    """The Floor Board window's sub-pages, ready for st.navigation in the Schedule Board app."""
    return [
        st.Page(view_fill, title="Fill floor", icon=":material/visibility:", url_path="fill-floor"),
        st.Page(view_pack, title="Pack floor", icon=":material/visibility:", url_path="pack-floor"),
        st.Page(update_page, title="Update", icon=":material/edit:", url_path="floor-update"),
        st.Page(supervisor_page, title="Supervisor view", icon=":material/lock:", url_path="supervisor"),
        st.Page(summary_page, title="End of shift", icon=":material/lock:", url_path="end-of-shift"),
        st.Page(setup_page, title="Setup", icon=":material/settings:", url_path="floor-setup"),
    ]


if __name__ == "__main__":
    st.set_page_config(page_title="Floor Board", page_icon=":material/groups:", layout="wide",
                       initial_sidebar_state="collapsed")
    nav = st.navigation(pages(), position="top")
    _sidebar()
    nav.run()
