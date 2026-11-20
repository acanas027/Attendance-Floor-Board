"""Floor Board — demo.

Live crew board for the Fill and Pack floors, by day and shift: start-of-shift
attendance, drag-and-drop crew tracking, break groups, supervisor view and
end-of-shift minutes by line.

Run:  streamlit run floor_board.py
Demo: memory only (a page refresh resets it). Crews, line requirements, usual
layout and logins come from floor_board_setup.xlsx next to this file (sheets Crew,
Lines, Logins). Without that file the app uses made-up sample data.

Moving into the Schedule Board app: add `pages()` to its st.navigation, e.g.
    st.navigation({"Schedule": [...], "Floor Board": floor_board.pages()})
and replace get_state()/_save() with Google Sheets reads/writes.
"""

from __future__ import annotations

import io
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st
from streamlit_sortables import sort_items

# ================= configuration =================

TZ = ZoneInfo("America/Chicago")

FLOORS = {"fill": "Fill", "pack": "Pack"}
SHIFTS = {"1st": time(6, 0), "2nd": time(16, 0)}  # 1st 6 AM–4 PM; 2nd 4 PM–end of night (2–3 AM), dated by its start day

ALL_LINES = [{"id": "KIT", "name": "Kit Line", "short": "Kit"}] + \
            [{"id": f"L{n}", "name": f"Line {n}", "short": f"L{n}"} for n in range(1, 19)]
BREAK = {"id": "BRK", "name": "Break", "short": "Break"}
AREAS = ALL_LINES + [BREAK]

# Lines on each floor (Fill has no Kit Line).
FLOOR_LINE_IDS = {
    "fill": [f"L{n}" for n in range(1, 19)],
    "pack": ["KIT"] + [f"L{n}" for n in range(1, 19)],
}
GROUP_KEYS = ("A", "B")


def floor_lines(floor: str) -> list[dict]:
    return [AREA_BY_ID[i] for i in FLOOR_LINE_IDS[floor]]


def floor_areas(floor: str) -> list[dict]:
    return floor_lines(floor) + [BREAK]


def lead_groups(floor: str) -> dict:
    """Each lead owns one group of lines on their floor: (Kit Line) 1–9 and 10–18."""
    ids = FLOOR_LINE_IDS[floor]
    a = [i for i in ["KIT"] + [f"L{n}" for n in range(1, 10)] if i in ids]
    return {"A": {"label": "Kit Line – 9" if "KIT" in ids else "Lines 1 – 9", "areas": a},
            "B": {"label": "Lines 10 – 18", "areas": [f"L{n}" for n in range(10, 19)]}}


def break_groups(floor: str) -> dict:
    """The two break buttons: (Kit Line) 1–9 and 10–17."""
    a = lead_groups(floor)["A"]
    return {"A": {"label": "lines " + a["label"].replace("Lines ", ""), "areas": a["areas"]},
            "B": {"label": "lines 10 – 17", "areas": [f"L{n}" for n in range(10, 18)]}}

DATA_FILE = Path(__file__).with_name("floor_board_setup.xlsx")

# Sample logins (used when there is no setup file). group None = supervisor (both floors, all lines).
USERS = [
    {"name": "A. Rivera", "pin": "1111", "floor": "fill", "group": "A"},
    {"name": "B. Lopez", "pin": "1112", "floor": "fill", "group": "B"},
    {"name": "M. Torres", "pin": "2221", "floor": "pack", "group": "A"},
    {"name": "C. Diaz", "pin": "2222", "floor": "pack", "group": "B"},
    {"name": "D. Morgan", "pin": "9999", "floor": None, "group": None},
]
LOGIN_HOURS = 12
CHECK_EVERY_MIN = 120

AREA_BY_ID = {a["id"]: a for a in AREAS}
BOX = None  # not on any line = "in the box"


def _sample_setup() -> tuple[list[dict], dict]:
    """Made-up crews for both floors and shifts. Replaced by the Setup upload."""
    firsts = ["Maria", "Jose", "Ana", "Luis", "Carmen", "Pedro", "Sofia", "Juan", "Rosa", "Miguel", "Elena", "Diego",
              "Laura", "Carlos", "Teresa", "Emilio", "Isabel", "Jorge", "Lucia", "Raul", "Paula", "Tomas", "Hector",
              "Daniel", "Marta", "Sergio", "Andrea", "Victor", "Silvia", "Pablo", "Ramon", "Alicia", "Ruben", "Gloria",
              "Fernando", "Adrian", "Beatriz", "Hugo", "Nora", "Irene", "Oscar", "Clara", "Felipe", "Ines", "Mateo",
              "Julia", "Samuel", "Rocio", "Ivan", "Lorena", "Alma", "Bruno", "Celia", "Dario", "Eva", "Fabian"]
    roster, reqs = [], {}
    for fi, floor in enumerate(FLOORS):
        for si, shift in enumerate(SHIFTS):
            seed = fi * 2 + si
            need = {"KIT": 4 + (seed % 2)} if "KIT" in FLOOR_LINE_IDS[floor] else {}
            need.update({f"L{n}": 3 if n in (3 + seed, 10 + seed) else 2 for n in range(1, 19)})
            for lid, n in need.items():
                reqs[(floor, shift, lid)] = n
            k = 0
            for lid, n in need.items():
                for _ in range(n):
                    first = firsts[(k + seed * 7) % len(firsts)]
                    roster.append({"floor": floor, "shift": shift, "name": f"{first} {chr(65 + (k * 3 + seed) % 26)}.",
                                   "line": lid})
                    k += 1
    return roster, reqs


# ================= state =================

STATE_KEY = "floor_board"
AUTH_KEY = "floor_board_auth"


def get_state() -> dict:
    if STATE_KEY not in st.session_state:
        roster, reqs, users, errors = load_setup()
        today = datetime.now(TZ).date()
        st.session_state[STATE_KEY] = {
            "roster": roster,  # {"floor", "shift", "name", "line"}
            "reqs": reqs,      # (floor, shift, line_id) -> required people
            "users": users,
            "setup_errors": errors,
            "boards": {},      # "YYYY-MM-DD|shift|floor" -> board
            "clock_mode": "demo",
            "demo_now": datetime.combine(today, SHIFTS["1st"], tzinfo=TZ),
        }
    return st.session_state[STATE_KEY]


def reset() -> None:
    st.session_state.pop(STATE_KEY, None)


def _save(b: dict) -> None:
    """Live version: write the board's changes to the backend here. Demo: nothing to do."""
    b["rev"] += 1


# ---------- clock, days and shifts ----------

def now() -> datetime:
    g = get_state()
    return g["demo_now"] if g["clock_mode"] == "demo" else datetime.now(TZ)


def advance_clock(minutes: int) -> None:
    get_state()["demo_now"] += timedelta(minutes=minutes)


def current_slot(t: datetime | None = None) -> tuple[date, str]:
    t = t or now()
    if t.time() < SHIFTS["1st"]:
        return t.date() - timedelta(days=1), "2nd"
    return (t.date(), "1st") if t.time() < SHIFTS["2nd"] else (t.date(), "2nd")


def jump_to_next_shift() -> None:
    d, s = current_slot()
    nxt = datetime.combine(d, SHIFTS["2nd"], tzinfo=TZ) if s == "1st" else \
        datetime.combine(d + timedelta(days=1), SHIFTS["1st"], tzinfo=TZ)
    get_state()["demo_now"] = nxt


def fmt(t: datetime | None) -> str:
    return "" if t is None else t.strftime("%I:%M %p").lstrip("0")


def fmt_day(d: date) -> str:
    return d.strftime("%a %b %d")


def fmt_min(m: float) -> str:
    m = int(round(m))
    return f"{m // 60}h {m % 60:02d}m"


# ---------- boards ----------

def board_key(d: date, shift: str, floor: str) -> str:
    return f"{d.isoformat()}|{shift}|{floor}"


def _new_board(d: date, shift: str, floor: str) -> dict:
    g = get_state()
    people = [r for r in g["roster"] if r["floor"] == floor and r["shift"] == shift]
    employees = [{"id": f"{floor[0].upper()}{shift[0]}{i:03d}", "name": r["name"], "home": r["line"]}
                 for i, r in enumerate(people, start=1)]
    return {
        "date": d, "shift": shift, "floor": floor, "rev": 0,
        "employees": employees,
        "reqs": {l["id"]: g["reqs"].get((floor, shift, l["id"]), 0) for l in floor_lines(floor)},
        "assign": {e["id"]: BOX for e in employees},
        "confirmed": {},        # group -> {"by", "t"}
        "finalized": None,      # time attendance became final (all groups confirmed)
        "attendance": {},       # eid -> {"status": Present|Absent|Late, "time", "by"}
        "left": {},             # eid -> time sent back to the box after being present
        "open": {},             # eid -> (area, start)
        "intervals": [],        # {"eid", "area", "start", "end"}
        "events": [],           # {"t", "kind", "text"}
        "break_from": {},       # eid -> line before a group break
        "group_break": {g_: False for g_ in GROUP_KEYS},
        "last_check": {},       # group -> time
        "ended": None,          # {"by", "t"}
    }


def get_board(d: date, shift: str, floor: str) -> dict:
    g = get_state()
    k = board_key(d, shift, floor)
    if k not in g["boards"]:
        g["boards"][k] = _new_board(d, shift, floor)
    return g["boards"][k]


def emp(b: dict, eid: str) -> dict:
    return next(e for e in b["employees"] if e["id"] == eid)


def crew(b: dict, aid: str | None) -> list[dict]:
    return [e for e in b["employees"] if b["assign"].get(e["id"]) == aid]


def short(aid: str | None) -> str:
    return "Box" if aid is BOX else AREA_BY_ID[aid]["short"]


def group_of(b: dict, aid: str) -> str | None:
    return next((g for g, grp in lead_groups(b["floor"]).items() if aid in grp["areas"]), None)


def on_group_break(b: dict, aid: str) -> bool:
    return any(b["group_break"][g] and aid in grp["areas"] for g, grp in break_groups(b["floor"]).items())


def is_short(b: dict, aid: str) -> bool:
    req = b["reqs"].get(aid, 0)
    return bool(req) and group_of(b, aid) in b["confirmed"] and not on_group_break(b, aid) and len(crew(b, aid)) < req


# ---------- rules ----------

def _log(b: dict, kind: str, text: str) -> None:
    b["events"].insert(0, {"t": now(), "kind": kind, "text": text})


def _timed(b: dict, area: str | None) -> bool:
    """Time counts on a line once its lead has confirmed; Break counts once anyone has."""
    if area is BOX:
        return False
    return bool(b["confirmed"]) if area == "BRK" else group_of(b, area) in b["confirmed"]


def _move(b: dict, eid: str, target: str | None, by: str, log: bool = True) -> None:
    prev = b["assign"][eid]
    if prev == target:
        return
    t = now()
    e = emp(b, eid)
    b["assign"][eid] = target
    if target != "BRK":
        b["break_from"].pop(eid, None)

    if eid in b["open"]:
        a, start = b["open"].pop(eid)
        b["intervals"].append({"eid": eid, "area": a, "start": start, "end": t})
    if not _timed(b, target):
        if target is BOX and eid in b["attendance"]:
            b["left"][eid] = t
            if log:
                _log(b, "left", f"{e['name']} left the floor ({short(prev)} → Box) · {by}")
        return

    b["open"][eid] = (target, t)
    att = b["attendance"].get(eid)
    if att is None:
        b["attendance"][eid] = {"status": "Present", "time": t, "by": by}
        if log:
            _log(b, "move", f"{e['name']} placed on {short(target)} · {by}")
    elif att["status"] == "Absent":
        att.update(status="Late", time=t, by=by)
        if log:
            _log(b, "late", f"{e['name']} arrived late → {short(target)} · {by}")
    else:
        b["left"].pop(eid, None)
        if log:
            _log(b, "move", f"{e['name']}  {short(prev)} → {short(target)} · {by}")


def apply_layout(b: dict, layout: dict[str | None, list[str]], by: str) -> int:
    """Apply a dragged layout {area: [eid, …]}; returns how many people moved."""
    moved = 0
    for area, eids in layout.items():
        for eid in eids:
            if b["assign"].get(eid) != area:
                _move(b, eid, area, by)
                moved += 1
    if moved:
        _save(b)
    return moved


def load_usual_layout(b: dict, group: str | None, by: str) -> None:
    groups = [group] if group else list(GROUP_KEYS)
    for g in groups:
        if g in b["confirmed"]:
            continue
        for e in crew(b, BOX):
            if e["home"] in lead_groups(b["floor"])[g]["areas"]:
                _move(b, e["id"], e["home"], by, log=False)
    _save(b)


def confirm_group(b: dict, group: str, by: str) -> None:
    if group in b["confirmed"] or b["ended"]:
        return
    t = now()
    b["confirmed"][group] = {"by": by, "t": t}
    b["last_check"][group] = t
    n = 0
    for e in b["employees"]:
        a = b["assign"][e["id"]]
        if a is not BOX and (a in lead_groups(b["floor"])[group]["areas"] or a == "BRK") and e["id"] not in b["attendance"]:
            b["attendance"][e["id"]] = {"status": "Present", "time": t, "by": by}
            b["open"][e["id"]] = (a, t)
            n += 1
    _log(b, "attendance", f"{lead_groups(b['floor'])[group]['label']} confirmed by {by}: {n} present")
    if len(b["confirmed"]) == len(GROUP_KEYS):
        absent = [e for e in crew(b, BOX) if e["id"] not in b["attendance"]]
        for e in absent:
            b["attendance"][e["id"]] = {"status": "Absent", "time": t, "by": by}
        b["finalized"] = t
        _log(b, "attendance", f"Attendance final: {len(b['employees']) - len(absent)} present, {len(absent)} absent")
    _save(b)


def toggle_group_break(b: dict, g: str, by: str) -> None:
    grp = break_groups(b["floor"])[g]
    if g not in b["confirmed"] or b["ended"]:
        return
    label = grp["label"][0].upper() + grp["label"][1:]
    if not b["group_break"][g]:
        people = [e for e in b["employees"] if b["assign"][e["id"]] in grp["areas"]]
        for e in people:
            prev = b["assign"][e["id"]]
            _move(b, e["id"], "BRK", by, log=False)
            b["break_from"][e["id"]] = prev
        b["group_break"][g] = True
        _log(b, "break", f"{label} sent to break ({len(people)} people) · {by}")
    else:
        back = [eid for eid, a in b["break_from"].items() if a in grp["areas"] and b["assign"][eid] == "BRK"]
        for eid in back:
            _move(b, eid, b["break_from"][eid], by, log=False)
        b["group_break"][g] = False
        _log(b, "break", f"{label} back from break ({len(back)} people) · {by}")
    _save(b)


def confirm_board(b: dict, group: str, by: str) -> None:
    if group not in b["confirmed"] or b["ended"]:
        return
    late = check_minutes_left(b, group) < 0
    b["last_check"][group] = now()
    _log(b, "check", f"{lead_groups(b['floor'])[group]['label']} board confirmed by {by}" + (" (late)" if late else ""))
    _save(b)


def end_shift(b: dict, by: str) -> None:
    if b["ended"] or not b["confirmed"]:
        return
    t = now()
    for eid, (a, start) in list(b["open"].items()):
        b["intervals"].append({"eid": eid, "area": a, "start": start, "end": t})
    b["open"].clear()
    if not b["finalized"]:  # a lead never confirmed: everyone still in the box is absent
        for e in crew(b, BOX):
            b["attendance"].setdefault(e["id"], {"status": "Absent", "time": t, "by": by})
        b["finalized"] = t
    b["ended"] = {"by": by, "t": t}
    _log(b, "end", f"Shift ended by {by} · all times closed")
    _save(b)


# ---------- read models ----------

def check_minutes_left(b: dict, group: str) -> int:
    last = b["last_check"].get(group)
    if last is None:
        return CHECK_EVERY_MIN
    return int((last + timedelta(minutes=CHECK_EVERY_MIN) - now()).total_seconds() // 60)


def minutes_by_area(b: dict, eid: str) -> dict[str, float]:
    out: dict[str, float] = {}
    for iv in b["intervals"]:
        if iv["eid"] == eid:
            out[iv["area"]] = out.get(iv["area"], 0) + (iv["end"] - iv["start"]).total_seconds() / 60
    if eid in b["open"]:
        a, start = b["open"][eid]
        out[a] = out.get(a, 0) + max(0.0, (now() - start).total_seconds() / 60)
    return out


def attendance_label(b: dict, eid: str) -> str:
    att = b["attendance"].get(eid)
    if att is None:
        return "Not placed yet"
    s = att["status"] if att["status"] != "Late" else f"Late ({fmt(att['time'])})"
    if eid in b["left"]:
        s += f" · left {fmt(b['left'][eid])}"
    return s


def absent_list(b: dict) -> list[dict]:
    return [e for e in b["employees"] if b["attendance"].get(e["id"], {}).get("status") == "Absent"]


def summary_rows(b: dict) -> list[dict]:
    rows = []
    for e in b["employees"]:
        mins = minutes_by_area(b, e["id"])
        brk = mins.pop("BRK", 0)
        rows.append({
            "Employee": e["name"], "Usual line": AREA_BY_ID[e["home"]]["name"] if e["home"] in AREA_BY_ID else "",
            "Attendance": attendance_label(b, e["id"]), "areas": mins,
            "Time by line": " · ".join(f"{short(a)} {fmt_min(m)}" for a, m in mins.items() if m >= 1),
            "Break": fmt_min(brk) if brk >= 1 else "", "Worked": fmt_min(sum(mins.values())),
        })
    return rows


# ================= login =================

def current_user() -> dict | None:
    a = st.session_state.get(AUTH_KEY)
    if a and datetime.now(TZ) - a["at"] < timedelta(hours=LOGIN_HOURS):
        return a
    st.session_state.pop(AUTH_KEY, None)
    return None


def logout() -> None:
    st.session_state.pop(AUTH_KEY, None)


def user_desc(u: dict) -> str:
    if u["group"] is None:
        return "Supervisor · both floors"
    return f"{FLOORS[u['floor']]} · {lead_groups(u['floor'])[u['group']]['label']}"


def require_login(purpose: str, supervisors_only: bool = False) -> dict | None:
    u = current_user()
    if u:
        if supervisors_only and u["group"] is not None:
            st.warning("Only supervisors can open this page.")
            return None
        return u
    users = get_state()["users"]
    st.markdown("### Sign in")
    st.caption(f"Sign in to {purpose}. You stay signed in for {LOGIN_HOURS} hours on this device.")
    with st.form("fb_login", border=True):
        name = st.selectbox("Name", [x["name"] for x in users])
        pin = st.text_input("PIN", type="password", max_chars=6)
        if st.form_submit_button("Sign in", type="primary"):
            match = next((x for x in users if x["name"] == name and str(x["pin"]) == pin), None)
            if match:
                st.session_state[AUTH_KEY] = {**match, "at": datetime.now(TZ)}
                st.rerun()
            st.error("Wrong PIN.")
    st.caption("Demo PINs: " + " · ".join(f"{x['name']} ({user_desc(x)}) {x['pin']}" for x in users))
    return None


# ================= screens =================

CSS = """
<style>
button[kind="primary"], button[kind="primaryFormSubmit"] { background:#FACC15 !important; border-color:#FACC15 !important; }
button[kind="primary"] p, button[kind="primaryFormSubmit"] p { color:#0B1220 !important; font-weight:700; }
.fb-pill { color:#E5ECF6; display:inline-block; padding:6px 12px; border-radius:12px; background:#131C2E;
  border:1px solid #26344D; font-size:14px; margin:0 6px 6px 0; }
.fb-tag { display:inline-block; padding:3px 10px; border-radius:999px; background:#1B2740; color:#E5ECF6;
  font-size:12px; font-weight:700; letter-spacing:.06em; }
.fb-live { background:#0F2A1E; color:#4ADE80; }
.fb-due { display:inline-block; padding:8px 12px; border-radius:12px; font-weight:600; font-size:14px; }
.fb-move { color:#E5ECF6; display:inline-block; padding:6px 10px; border-radius:10px; background:#1B2740;
  font-size:13px; margin:0 6px 6px 0; }
.fb-move span { color:#94A3B8; margin-right:6px; }
.fb-grid { display:grid; grid-template-columns:repeat(7, minmax(0,1fr)); gap:10px; align-items:start; }
.fb-tile { background:#131C2E; border:1px solid #26344D; border-radius:14px; padding:6px;
  display:flex; flex-direction:column; gap:6px; }
.fb-tile.short { border-color:#F87171; }
.fb-tile.brk { border-style:dashed; border-color:#475569; background:#0F1626; }
.fb-zh { color:#E5ECF6; display:flex; justify-content:space-between; align-items:center; gap:6px; min-height:40px;
  padding:0 10px; border-radius:10px; background:#1B2740; font-weight:700; font-size:14px; white-space:nowrap; }
.fb-zh span { color:#94A3B8; }
.fb-tile.short .fb-zh span { color:#FCA5A5; }
.fb-onbrk { color:#94A3B8; font-size:13px; font-weight:600; text-align:center; padding:4px 0; }
.fb-name { border-radius:999px; padding:7px 10px; font-weight:700; font-size:14px; color:#0B1220;
  background:#60A5FA; text-align:center; }
.fb-box { background:#131C2E; border:1px solid #26344D; border-radius:14px; padding:10px 12px; margin-bottom:10px;
  display:flex; flex-wrap:wrap; gap:6px; align-items:center; color:#E5ECF6; }
.fb-box b { margin-right:6px; }
.fb-box.absent .fb-name { background:#FCA5A5; }
.fb-boxtitle { color:#E5ECF6; font-weight:700; padding:4px 0; }
.fb-boxtitle span { color:#94A3B8; font-weight:400; }
.fb-hint { padding:10px 14px; border-radius:12px; background:#FACC15; color:#0B1220; font-weight:600; }

/* tap mode */
[class*="st-key-chip-"] button { border-radius:999px; border:0; min-height:40px; padding:2px 14px; background:#60A5FA; }
[class*="st-key-chip-"] button p { color:#0B1220 !important; font-weight:700; }
[class*="st-key-chip-"] button:hover { filter:brightness(1.1); }
[class*="st-key-chip-sel-"] button { outline:3px solid #FACC15; outline-offset:2px; transform:scale(1.05); }
[class*="st-key-chip-dim-"] button { opacity:.7; }
[class*="st-key-zh-target-"] button { min-height:44px; border:0; background:#FACC15; }
[class*="st-key-zh-target-"] button p { color:#0B1220 !important; font-weight:700; }
[class*="st-key-zone-"] { background:#131C2E; border-radius:14px; }
[class*="st-key-zone-short-"] { border:1px solid #F87171 !important; }
[class*="st-key-zone-target-"] { border:1px solid #FACC15 !important; }
[class*="st-key-zone-brk-"] { border:1px dashed #475569 !important; background:#0F1626; }
[class*="st-key-tapbox-"] { background:#131C2E; border-radius:14px; }
.fb-zh.short span { color:#FCA5A5; }
</style>
"""

DRAG_CSS = """
.sortable-component { display:grid; grid-template-columns:repeat(5, minmax(0,1fr)); gap:8px; align-items:start;
  border:0; padding:0; background:transparent; }
.sortable-container { background:#131C2E; border:1px solid #26344D; border-radius:12px; padding:6px; margin:0;
  min-height:120px; counter-reset:none; }
.sortable-container:nth-of-type(1) { grid-column:1 / -1; min-height:80px; }
.sortable-container-header { color:#E5ECF6; font-weight:700; font-size:14px; padding:8px 10px; background:#1B2740;
  border-radius:8px; margin-bottom:6px; }
.sortable-container-body { display:flex; flex-wrap:wrap; gap:6px; background:transparent; min-height:60px; }
.sortable-item { background:#60A5FA; color:#0B1220; border:0; border-radius:999px; padding:9px 14px; margin:0;
  font-weight:700; font-size:14px; touch-action:none; }
.sortable-item:hover { filter:brightness(1.1); }
"""


def _slot_picker(key: str) -> tuple[date, str]:
    """Day + shift selector, defaulting to the current shift."""
    d0, s0 = current_slot()
    c1, c2, _ = st.columns([1, 1, 3])
    d = c1.date_input("Day", value=d0, key=f"day_{key}", format="MM/DD/YYYY")
    s = c2.segmented_control("Shift", list(SHIFTS), default=s0, key=f"shift_{key}", required=True)
    return d, s or s0


def _floor_picker(key: str, default: str = "fill") -> str:
    return st.segmented_control("Floor", list(FLOORS), format_func=FLOORS.get, default=default,
                                key=f"floor_{key}", required=True) or default


def _history_pickers(u: dict, key: str) -> tuple[str, date, str]:
    """Supervisors pick any floor, day and shift; leads see their own floor's current shift."""
    if u["group"] is None:
        floor = _floor_picker(key)
        d, s = _slot_picker(key)
        return floor, d, s
    d, s = current_slot()
    return u["floor"], d, s


def _title(b: dict, title: str) -> None:
    live = (b["date"], b["shift"]) == current_slot() and not b["ended"]
    tags = f"<span class='fb-tag'>{FLOORS[b['floor']].upper()}</span> " \
           f"<span class='fb-tag'>{b['shift'].upper()} SHIFT · {fmt_day(b['date']).upper()}</span> " + \
           ("<span class='fb-tag fb-live'>LIVE</span>" if live else "")
    st.markdown(f"### {title} &nbsp;{tags}", unsafe_allow_html=True)


def _pills(b: dict) -> None:
    on_line = sum(1 for e in b["employees"] if b["assign"][e["id"]] not in (BOX, "BRK"))
    box_label = "Absent" if b["finalized"] else "Not placed"
    st.markdown(
        f"<span class='fb-pill'>On lines <b>{on_line}</b></span>"
        f"<span class='fb-pill'>On break <b>{len(crew(b, 'BRK'))}</b></span>"
        f"<span class='fb-pill'>{box_label} <b>{len(crew(b, BOX))}</b></span>"
        f"<span class='fb-pill'>Crew <b>{len(b['employees'])}</b></span>",
        unsafe_allow_html=True,
    )


def _latest(b: dict, n: int = 5) -> None:
    if b["events"]:
        html = "".join(f"<span class='fb-move'><span>{fmt(ev['t'])}</span>{ev['text']}</span>" for ev in b["events"][:n])
        st.markdown("**Latest** &nbsp; " + html, unsafe_allow_html=True)


def _read_only_board(b: dict, areas: list[dict]) -> None:
    box = crew(b, BOX)
    if box:
        label = "Absent" if b["finalized"] else "Not placed yet"
        cls = "absent" if b["finalized"] else ""
        names = "".join(f"<span class='fb-name'>{e['name']}</span>" for e in box)
        st.markdown(f"<div class='fb-box {cls}'><b>{label} · {len(box)}</b>{names}</div>", unsafe_allow_html=True)
    tiles = []
    for a in areas:
        people = crew(b, a["id"])
        brk = a["id"] == "BRK" or on_group_break(b, a["id"])
        cls = "brk" if brk else ("short" if is_short(b, a["id"]) else "")
        req = b["reqs"].get(a["id"])
        count = str(len(people)) if a["id"] == "BRK" else ("" if brk else f"{len(people)}/{req}")
        onbrk = "<div class='fb-onbrk'>On break</div>" if brk and a["id"] != "BRK" else ""
        names = "".join(f"<div class='fb-name'>{e['name']}</div>" for e in people)
        tiles.append(f"<div class='fb-tile {cls}'><div class='fb-zh'>{a['name']}<span>{count}</span></div>{onbrk}{names}</div>")
    st.markdown(f"<div class='fb-grid'>{''.join(tiles)}</div>", unsafe_allow_html=True)


# ---------- read-only floor views ----------

def _view(floor: str) -> None:
    st.markdown(CSS, unsafe_allow_html=True)

    @st.fragment(run_every="10s")
    def _live() -> None:
        d, s = current_slot()
        b = get_board(d, s, floor)
        _title(b, "Floor view")
        _pills(b)
        if not b["confirmed"]:
            st.caption("No lead has confirmed attendance yet for this shift.")
        _read_only_board(b, floor_areas(floor))
        _latest(b)

    _live()


def view_fill() -> None:
    _view("fill")


def view_pack() -> None:
    _view("pack")


# ---------- update (sign-in, drag people) ----------

@st.dialog("End shift")
def _end_dialog(b: dict, by: str) -> None:
    st.write(f"This closes everyone's time on the {FLOORS[b['floor']]} floor ({b['shift']} shift) at {fmt(now())} "
             "and locks the board for both leads.")
    c1, c2 = st.columns(2)
    if c1.button("End shift", type="primary", width="stretch"):
        end_shift(b, by)
        st.rerun()
    if c2.button("Cancel", width="stretch"):
        st.rerun()


def _drag_board(b: dict, areas: list[dict], by: str) -> None:
    """Box + the lead's lines + Break as drag-and-drop containers."""
    labels: dict[str, str] = {}
    used: dict[str, int] = {}
    for e in b["employees"]:
        n = used.get(e["name"], 0) + 1
        used[e["name"]] = n
        labels[e["id"]] = e["name"] if n == 1 else f"{e['name']} ({n})"
    by_label = {v: k for k, v in labels.items()}

    containers = [(BOX, f"{'Absent' if b['finalized'] else 'Not placed yet'} · {len(crew(b, BOX))}  —  "
                        "press and hold a name, then drag it to a line")]
    extra_css = []
    for i, a in enumerate(areas, start=2):  # nth-of-type: the box is 1
        n = len(crew(b, a["id"]))
        if a["id"] == "BRK":
            head = f"Break · {n}"
            extra_css.append(f".sortable-container:nth-of-type({i}){{border-style:dashed;border-color:#475569;background:#0F1626}}")
        elif on_group_break(b, a["id"]):
            head = f"{a['name']} · on break"
            extra_css.append(f".sortable-container:nth-of-type({i}){{border-style:dashed;border-color:#475569}}")
        else:
            head = f"{a['name']} · {n}/{b['reqs'].get(a['id'], 0)}"
            if is_short(b, a["id"]):
                extra_css.append(f".sortable-container:nth-of-type({i}){{border-color:#F87171}}"
                                 f".sortable-container:nth-of-type({i}) .sortable-container-header{{color:#FCA5A5}}")
        containers.append((a["id"], head))

    items = [{"header": head, "items": [labels[e["id"]] for e in crew(b, aid)]} for aid, head in containers]
    result = sort_items(items, multi_containers=True, direction="horizontal",
                        custom_style=DRAG_CSS + "".join(extra_css),
                        key=f"drag-{board_key(b['date'], b['shift'], b['floor'])}-{b['rev']}-{len(areas)}")
    layout = {aid: [by_label[x] for x in c["items"] if x in by_label] for (aid, _), c in zip(containers, result)}
    if apply_layout(b, layout, by):
        st.rerun()


def _bk(b: dict) -> str:
    return board_key(b["date"], b["shift"], b["floor"]).replace("|", "_")


def _selected(b: dict) -> str | None:
    eid = st.session_state.get(f"fb_sel_{_bk(b)}")
    return eid if eid in b["assign"] else None


def _tap_select(b: dict, eid: str) -> None:
    k = f"fb_sel_{_bk(b)}"
    st.session_state[k] = None if st.session_state.get(k) == eid else eid


def _tap_cancel(b: dict) -> None:
    st.session_state[f"fb_sel_{_bk(b)}"] = None


def _tap_move(b: dict, target: str | None, by: str) -> None:
    eid = _selected(b)
    _tap_cancel(b)
    if eid:
        apply_layout(b, {target: [eid]}, by)


def _chip(b: dict, e: dict, where: str, sel: str | None) -> None:
    state = "sel" if sel == e["id"] else ("dim" if sel else "n")
    st.button(e["name"], key=f"chip-{state}-{where}-{_bk(b)}-{e['id']}", on_click=_tap_select, args=(b, e["id"]),
              width="stretch" if where == "tile" else "content")


def _tap_board(b: dict, areas: list[dict], by: str) -> None:
    """Tap a name, then tap 'Move to …' on the line (same result as dragging)."""
    sel = _selected(b)
    if sel:
        h1, h2 = st.columns([5, 1], vertical_alignment="center")
        h1.markdown(f"<div class='fb-hint'>Moving {emp(b, sel)['name']} — tap <b>Move to …</b> on the line "
                    "they're going to.</div>", unsafe_allow_html=True)
        h2.button("Cancel", on_click=_tap_cancel, args=(b,), width="stretch")

    in_box = crew(b, BOX)
    with st.container(border=True, key=f"tapbox-{_bk(b)}"):
        if sel and b["assign"][sel] is not BOX:
            st.button("Move to the box", key=f"zh-target-{_bk(b)}-BOX", on_click=_tap_move, args=(b, BOX, by),
                      width="stretch")
        else:
            title = "Absent" if b["finalized"] else "Not placed yet"
            st.markdown(f"<div class='fb-boxtitle'>{title} <span>· {len(in_box)} — tap a name, then tap where "
                        "they're going</span></div>", unsafe_allow_html=True)
        with st.container(horizontal=True, wrap=True, gap="small"):
            for e in in_box:
                _chip(b, e, "box", sel)

    for i in range(0, len(areas), 5):
        for col, a in zip(st.columns(5, gap="small"), areas[i:i + 5]):
            with col:
                people = crew(b, a["id"])
                is_target = bool(sel) and b["assign"][sel] != a["id"]
                on_brk = a["id"] == "BRK" or on_group_break(b, a["id"])
                state = "target" if is_target else "brk" if on_brk else "short" if is_short(b, a["id"]) else "ok"
                if a["id"] == "BRK":
                    count = str(len(people))
                elif on_group_break(b, a["id"]):
                    count = "on break"
                else:
                    count = f"{len(people)}/{b['reqs'].get(a['id'], 0)}"
                with st.container(border=True, key=f"zone-{state}-{_bk(b)}-{a['id']}"):
                    if is_target:
                        st.button(f"Move to {a['short']}", key=f"zh-target-{_bk(b)}-{a['id']}", on_click=_tap_move,
                                  args=(b, a["id"], by), width="stretch")
                    else:
                        st.markdown(f"<div class='fb-zh {state}'>{a['name']}<span>{count}</span></div>",
                                    unsafe_allow_html=True)
                    for e in people:
                        _chip(b, e, "tile", sel)


def update_page() -> None:
    st.markdown(CSS, unsafe_allow_html=True)
    u = require_login("update the floor")
    if not u:
        return
    by = u["name"]
    d, s = current_slot()  # only the current shift can be changed
    if u["group"] is None:  # supervisor: either floor, all lines
        floor = _floor_picker("update")
        groups = list(GROUP_KEYS)
    else:
        floor = u["floor"]
        groups = [u["group"]]
    b = get_board(d, s, floor)
    areas = [AREA_BY_ID[a] for g in groups for a in lead_groups(floor)[g]["areas"]] + [BREAK]

    _title(b, "Floor Board")
    st.caption(f"Signed in as {by} · {user_desc(u)} · {fmt(now())}")
    _pills(b)

    if b["ended"]:
        st.success(f"Shift ended at {fmt(b['ended']['t'])} by {b['ended']['by']}. See End of shift for the totals.")
        _read_only_board(b, areas)
        return

    # attendance status for every lead on this floor
    status = []
    for g, grp in lead_groups(floor).items():
        c = b["confirmed"].get(g)
        status.append(f"{grp['label']}: " + (f"confirmed by {c['by']} at {fmt(c['t'])}" if c else "waiting"))
    st.caption("Attendance · " + " · ".join(status)
               + (" · **final**" if b["finalized"] else " · people left in the box become absent once every lead confirms"))

    for g in groups:
        grp = lead_groups(floor)[g]
        if g not in b["confirmed"]:
            placed = sum(1 for e in b["employees"] if b["assign"][e["id"]] in grp["areas"])
            c1, c2 = st.columns([1, 2])
            c1.button(f"Load usual layout · {grp['label']}", key=f"usual-{g}", width="stretch",
                      on_click=load_usual_layout, args=(b, g, by))
            c2.button(f"Confirm attendance · {grp['label']} · {placed} on lines", key=f"conf-{g}", type="primary",
                      width="stretch", on_click=confirm_group, args=(b, g, by))
        else:
            left = check_minutes_left(b, g)
            pill = (f"<span class='fb-due' style='background:#2A2111;color:#FBBF24'>{grp['label']}: board check due in {left} min</span>"
                    if left >= 0 else
                    f"<span class='fb-due' style='background:#2A1517;color:#FCA5A5'>{grp['label']}: board check overdue by {-left} min</span>")
            bg = break_groups(floor)[g]
            brk_label = (f"Bring {bg['label']} back from break" if b["group_break"][g] else f"Send {bg['label']} to break")
            c1, c2, c3 = st.columns([2, 2, 1], vertical_alignment="center")
            c1.markdown(pill, unsafe_allow_html=True)
            c2.button(brk_label, key=f"brk-{g}", width="stretch", on_click=toggle_group_break, args=(b, g, by))
            c3.button("Board is correct", key=f"chk-{g}", type="primary", width="stretch",
                      on_click=confirm_board, args=(b, g, by))

    mode = st.segmented_control("Move people by", ["Drag", "Tap"], default="Drag", key="fb_move_mode", required=True)
    if mode == "Tap":
        _tap_board(b, areas, by)
    else:
        _drag_board(b, areas, by)

    c1, c2 = st.columns([4, 1], vertical_alignment="center")
    with c1:
        _latest(b)
    if b["confirmed"] and c2.button("End shift", width="stretch"):
        _end_dialog(b, by)


# ---------- supervisor view (sign-in) ----------

def supervisor_page() -> None:
    st.markdown(CSS, unsafe_allow_html=True)
    u = require_login("see the supervisor view")
    if not u:
        return
    floor, d, s = _history_pickers(u, "sup")
    b = get_board(d, s, floor)
    _title(b, "Supervisor view")

    absent = absent_list(b)
    late = [e for e in b["employees"] if b["attendance"].get(e["id"], {}).get("status") == "Late"]
    shorts = [a for a in floor_lines(floor) if is_short(b, a["id"])]
    m = st.columns(5)
    m[0].metric("On lines", sum(1 for e in b["employees"] if b["assign"][e["id"]] not in (BOX, "BRK")))
    m[1].metric("On break", len(crew(b, "BRK")))
    m[2].metric("Absent", len(absent) if b["finalized"] else "—")
    m[3].metric("Late", len(late))
    m[4].metric("Lines short", len(shorts))

    left, right = st.columns([1, 1])
    with left:
        st.markdown("**Absent**")
        if not b["finalized"]:
            waiting = [grp["label"] for g, grp in lead_groups(floor).items() if g not in b["confirmed"]]
            st.caption("Not final yet · waiting on " + ", ".join(waiting))
        if absent:
            st.dataframe(pd.DataFrame([{"Employee": e["name"], "Usual line": AREA_BY_ID[e["home"]]["name"]}
                                       for e in absent]), hide_index=True, width="stretch")
        elif b["finalized"]:
            st.success("No one absent.")
        if late:
            st.markdown("**Late**")
            st.dataframe(pd.DataFrame([{"Employee": e["name"], "Arrived": fmt(b["attendance"][e["id"]]["time"])}
                                       for e in late]), hide_index=True, width="stretch")
    with right:
        st.markdown("**Needs attention**")
        alerts = 0
        if not b["ended"]:
            for g, grp in lead_groups(floor).items():
                if g in b["confirmed"] and check_minutes_left(b, g) < 0:
                    st.warning(f"{grp['label']}: board check overdue by {-check_minutes_left(b, g)} min")
                    alerts += 1
        for a in shorts:
            st.error(f"{a['name']}: {len(crew(b, a['id']))} of {b['reqs'][a['id']]}")
            alerts += 1
        if not alerts:
            st.success("All lines staffed and boards up to date.")

    st.markdown("**Crews**")
    st.dataframe(pd.DataFrame([{"Line": a["name"], "Crew": ", ".join(e["name"] for e in crew(b, a["id"])),
                                "On line": len(crew(b, a["id"])), "Required": b["reqs"].get(a["id"])}
                               for a in floor_areas(floor)]), hide_index=True, width="stretch", height=420)


# ---------- end of shift (sign-in) ----------

def summary_page() -> None:
    st.markdown(CSS, unsafe_allow_html=True)
    u = require_login("see the end of shift report")
    if not u:
        return
    floor, d, s = _history_pickers(u, "eos")
    b = get_board(d, s, floor)
    _title(b, "End of shift")
    if not b["confirmed"]:
        st.info("Nothing recorded for this shift yet.")
        return
    if b["ended"]:
        st.caption(f"Ended {fmt(b['ended']['t'])} by {b['ended']['by']} · built from the board moves")
    else:
        st.caption(f"Shift in progress · totals as of {fmt(now())} · a lead ends the shift on the Update page")

    absent = absent_list(b)
    st.markdown(f"**Absent · {len(absent)}**" if b["finalized"] else "**Absent** · not final yet")
    if absent:
        st.dataframe(pd.DataFrame([{"Employee": e["name"], "Usual line": AREA_BY_ID[e["home"]]["name"]} for e in absent]),
                     hide_index=True, width="stretch")

    rows = summary_rows(b)
    st.markdown("**Time by line**")
    st.dataframe(pd.DataFrame(rows)[["Employee", "Usual line", "Attendance", "Time by line", "Break", "Worked"]],
                 hide_index=True, width="stretch", height=460)

    tag = f"{FLOORS[floor].lower()}_{d.isoformat()}_{s}"
    long_rows = [{"Date": d.isoformat(), "Shift": s, "Floor": FLOORS[floor], "Employee": r["Employee"],
                  "Line": AREA_BY_ID[a]["name"], "Minutes": round(m)} for r in rows for a, m in r["areas"].items()]
    att_rows = [{"Date": d.isoformat(), "Shift": s, "Floor": FLOORS[floor], "Employee": r["Employee"],
                 "Attendance": r["Attendance"]} for r in rows]
    log_rows = [{"Time": fmt(ev["t"]), "Event": ev["text"]} for ev in reversed(b["events"])]
    c1, c2, c3 = st.columns(3)
    c1.download_button("Minutes by line (CSV)", pd.DataFrame(long_rows).to_csv(index=False),
                       f"{tag}_minutes_by_line.csv", "text/csv", width="stretch")
    c2.download_button("Attendance (CSV)", pd.DataFrame(att_rows).to_csv(index=False),
                       f"{tag}_attendance.csv", "text/csv", width="stretch")
    c3.download_button("Move log (CSV)", pd.DataFrame(log_rows).to_csv(index=False),
                       f"{tag}_move_log.csv", "text/csv", width="stretch")
    st.markdown("**Move log**")
    st.dataframe(pd.DataFrame(log_rows), hide_index=True, width="stretch")


# ---------- setup file (crews, line requirements, usual layout, logins) ----------

def _norm_floor(v) -> str | None:
    v = str(v).strip().lower()
    return next((k for k, name in FLOORS.items() if v in (k, name.lower())), None)


def _norm_shift(v) -> str | None:
    v = str(v).strip().lower().replace("shift", "").strip()
    return {"1": "1st", "1st": "1st", "first": "1st", "2": "2nd", "2nd": "2nd", "second": "2nd"}.get(v)


def _norm_line(v) -> str | None:
    v = str(v).strip().lower().replace("line", "").strip()
    if v in ("kit", "k"):
        return "KIT"
    v = v.lstrip("l").strip()
    try:
        n = int(float(v))
    except ValueError:
        return None
    return f"L{n}" if 1 <= n <= 18 else None


def _norm_group(v) -> str | None | bool:
    v = str(v).strip().lower()
    if v.startswith("sup") or v in ("all", "both"):
        return None
    if "10" in v or "18" in v or v.startswith("b"):
        return "B"
    if "kit" in v or "1" in v or "9" in v or v.startswith("a"):
        return "A"
    return False


def _pin(v) -> str:
    try:
        return str(int(float(v)))
    except (TypeError, ValueError):
        return str(v).strip()


def load_setup(path: Path = DATA_FILE) -> tuple[list[dict], dict, list[dict], list[str]]:
    """Read floor_board_setup.xlsx (sheets Crew, Lines, Logins). Falls back to sample data."""
    if not path.exists():
        roster, reqs = _sample_setup()
        return roster, reqs, [dict(u) for u in USERS], []
    sheets = pd.read_excel(path, sheet_name=None)
    errors, roster, reqs, users = [], [], {}, []
    for i, r in sheets.get("Crew", pd.DataFrame()).iterrows():
        name = str(r.get("Name", "")).strip()
        if not name or name == "nan":
            continue
        f, s, l = _norm_floor(r.get("Floor")), _norm_shift(r.get("Shift")), _norm_line(r.get("Usual line"))
        if f and s and l and l in FLOOR_LINE_IDS[f]:
            roster.append({"floor": f, "shift": s, "name": name, "line": l})
        else:
            errors.append(f"Crew row {i + 2}: check Floor / Shift / Usual line for {name}")
    for i, r in sheets.get("Lines", pd.DataFrame()).iterrows():
        f, s, l = _norm_floor(r.get("Floor")), _norm_shift(r.get("Shift")), _norm_line(r.get("Line"))
        if f and s and l and l in FLOOR_LINE_IDS[f] and not pd.isna(r.get("Required")):
            reqs[(f, s, l)] = int(r["Required"])
        else:
            errors.append(f"Lines row {i + 2}: check Floor / Shift / Line / Required")
    for i, r in sheets.get("Logins", pd.DataFrame()).iterrows():
        name = str(r.get("Name", "")).strip()
        if not name or name == "nan":
            continue
        grp, f = _norm_group(r.get("Lines")), _norm_floor(r.get("Floor"))
        if grp is False or (grp is not None and not f):
            errors.append(f"Logins row {i + 2}: check Floor / Lines for {name}")
            continue
        users.append({"name": name, "pin": _pin(r.get("PIN")), "floor": f if grp else None, "group": grp})
    if not roster:
        errors.append("No crew found in the Crew sheet; using sample data.")
        roster, reqs = _sample_setup()
    if not users:
        errors.append("No logins found in the Logins sheet; using sample logins.")
        users = [dict(u) for u in USERS]
    return roster, reqs, users, errors


def write_setup_template(path: Path) -> None:
    """Writes the setup file filled with the sample data, to edit with the real crews."""
    roster, reqs = _sample_setup()

    with pd.ExcelWriter(path, engine="openpyxl") as xw:
        pd.DataFrame([{"Floor": FLOORS[r["floor"]], "Shift": r["shift"], "Name": r["name"],
                       "Usual line": AREA_BY_ID[r["line"]]["name"]} for r in roster]
                     ).to_excel(xw, sheet_name="Crew", index=False)
        pd.DataFrame([{"Floor": FLOORS[f], "Shift": s, "Line": AREA_BY_ID[l]["name"], "Required": n}
                      for (f, s, l), n in reqs.items()]).to_excel(xw, sheet_name="Lines", index=False)
        pd.DataFrame([{"Name": u["name"], "PIN": u["pin"], "Floor": FLOORS[u["floor"]] if u["floor"] else "Both",
                       "Lines": lead_groups(u["floor"])[u["group"]]["label"] if u["group"] else "Supervisor"}
                      for u in USERS]).to_excel(xw, sheet_name="Logins", index=False)


# ================= navigation =================

def _sidebar() -> None:
    g = get_state()
    d, s = current_slot()
    with st.sidebar:
        st.markdown("**Floor Board demo**")
        st.caption("Memory only: refreshing the page resets the demo.")
        st.markdown(f"Now: **{fmt_day(d)} · {s} shift · {fmt(now())}**")
        real = st.toggle("Real time", value=g["clock_mode"] == "real")
        g["clock_mode"] = "real" if real else "demo"
        if not real:
            b1, b2, b3 = st.columns(3)
            b1.button("+15 min", on_click=advance_clock, args=(15,), width="stretch")
            b2.button("+1 h", on_click=advance_clock, args=(60,), width="stretch")
            b3.button("Next shift", on_click=jump_to_next_shift, width="stretch")
        st.caption("Data: " + (DATA_FILE.name if DATA_FILE.exists() else "sample (no floor_board_setup.xlsx found)"))
        for err in g["setup_errors"][:10]:
            st.warning(err)
        if st.button("Reset demo", width="stretch"):
            reset()
            logout()
            st.rerun()
        u = current_user()
        if u:
            st.divider()
            st.markdown(f"Signed in: **{u['name']}**  \n{user_desc(u)}")
            st.button("Sign out", on_click=logout, width="stretch")


def pages() -> list:
    """The Floor Board window's sub-pages, ready for st.navigation in the Schedule Board app."""
    return [
        st.Page(view_fill, title="Fill floor", icon=":material/visibility:", url_path="fill-floor"),
        st.Page(view_pack, title="Pack floor", icon=":material/visibility:", url_path="pack-floor"),
        st.Page(update_page, title="Update", icon=":material/edit:", url_path="floor-update"),
        st.Page(supervisor_page, title="Supervisor view", icon=":material/lock:", url_path="supervisor"),
        st.Page(summary_page, title="End of shift", icon=":material/lock:", url_path="end-of-shift"),
    ]


if __name__ == "__main__":
    st.set_page_config(page_title="Floor Board", page_icon=":material/groups:", layout="wide",
                       initial_sidebar_state="collapsed")
    nav = st.navigation(pages(), position="top")
    _sidebar()
    nav.run()
