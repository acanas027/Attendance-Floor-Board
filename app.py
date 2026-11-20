"""Floor Board — demo.

Live crew board for floor leads: start-of-shift attendance, tap-to-move crew
tracking, supervisor view and end-of-shift minutes by area.

Run:  streamlit run floor_board.py
Demo: sample names, memory only (a page refresh resets it). When this moves into
the Schedule Board app, call page() from its window and replace get_state()/_save()
with Google Sheets reads/writes.
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

# id, name, short label, standard crew size (None = no standard)
AREAS = [
    *[{"id": f"L{n}", "name": f"Line {n}", "short": f"L{n}", "std": 2} for n in range(1, 19)],
    {"id": "KIT", "name": "Kit Line", "short": "Kit", "std": 5},
    {"id": "PAL", "name": "Palletizing", "short": "Pallet", "std": 6},
    {"id": "BRK", "name": "Break", "short": "Break", "std": None},
]
# A few lines run with an assistant.
for _a in AREAS:
    if _a["id"] in ("L3", "L7", "L10", "L15"):
        _a["std"] = 3

# name, role, usual area
EMPLOYEES = [
    ("Maria R.", "Operator", "L1"), ("Jose L.", "Operator", "L1"),
    ("Ana P.", "Operator", "L2"), ("Luis G.", "Operator", "L2"),
    ("Carmen D.", "Operator", "L3"), ("Pedro S.", "Operator", "L3"), ("Sofia M.", "Assistant", "L3"),
    ("Juan C.", "Operator", "L4"), ("Rosa T.", "Operator", "L4"),
    ("Miguel A.", "Operator", "L5"), ("Elena V.", "Operator", "L5"),
    ("Diego F.", "Operator", "L6"), ("Laura B.", "Operator", "L6"),
    ("Carlos N.", "Operator", "L7"), ("Teresa G.", "Operator", "L7"),
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
    ("Emilio P.", "Assistant", "L7"),
]

SHIFTS = {
    "1st shift": {"start": (6, 0)},
    "2nd shift": {"start": (16, 0)},
}

CHECK_EVERY_MIN = 120


# ================= state and rules =================

TZ = ZoneInfo("America/Chicago")
BOX = None  # an employee not on any area is "in the box"
STATE_KEY = "floor_board"


# ---------- setup ----------

def _fresh_state() -> dict:
    employees = [
        {"id": f"E{i:03d}", "name": n, "role": r, "home": h}
        for i, (n, r, h) in enumerate(EMPLOYEES, start=1)
    ]
    return {
        "employees": employees,
        "areas": copy.deepcopy(AREAS),
        "assign": {e["id"]: BOX for e in employees},
        "selected": None,
        "lead": "A. Rivera",
        "shift": "1st shift",
        "clock_mode": "demo",  # "demo" = clock moves only with the demo buttons; "real" = wall clock
        "demo_minutes": 0,
        "attendance_confirmed": False,
        "attendance_time": None,
        "attendance": {},  # eid -> {"status": Present|Absent|Late, "time": datetime}
        "left": {},  # eid -> datetime they were moved back to the box after attendance
        "open": {},  # eid -> (area_id, start)
        "intervals": [],  # {"eid", "area", "start", "end"}
        "events": [],  # {"t", "kind", "text"}
        "last_check": None,
        "checkins": 0,
        "ended": False,
        "end_time": None,
    }


def get_state() -> dict:
    if STATE_KEY not in st.session_state:
        st.session_state[STATE_KEY] = _fresh_state()
    return st.session_state[STATE_KEY]


def reset() -> None:
    st.session_state[STATE_KEY] = _fresh_state()


def _save(s: dict) -> None:
    """Live version: write changes to the backend here. Demo: nothing to do."""


# ---------- lookups ----------

def emp(s: dict, eid: str) -> dict:
    return next(e for e in s["employees"] if e["id"] == eid)


def area(s: dict, aid: str | None) -> dict | None:
    return next((a for a in s["areas"] if a["id"] == aid), None)


def area_short(s: dict, aid: str | None) -> str:
    return "Box" if aid is BOX else area(s, aid)["short"]


def crew(s: dict, aid: str | None) -> list[dict]:
    return [e for e in s["employees"] if s["assign"].get(e["id"]) == aid]


def is_line(a: dict) -> bool:
    return a["id"] != "BRK"


# ---------- clock ----------

def shift_start(s: dict) -> datetime:
    h, m = SHIFTS[s["shift"]]["start"]
    today = datetime.now(TZ).date()
    return datetime(today.year, today.month, today.day, h, m, tzinfo=TZ)


def now(s: dict) -> datetime:
    if s["clock_mode"] == "demo":
        return shift_start(s) + timedelta(minutes=s["demo_minutes"])
    return datetime.now(TZ)


def advance_clock(s: dict, minutes: int) -> None:
    s["demo_minutes"] += minutes


def fmt(t: datetime | None) -> str:
    if t is None:
        return ""
    return t.strftime("%I:%M %p").lstrip("0")


def fmt_min(m: float) -> str:
    m = int(round(m))
    return f"{m // 60}h {m % 60:02d}m"


# ---------- actions ----------

def _log(s: dict, kind: str, text: str) -> None:
    s["events"].insert(0, {"t": now(s), "kind": kind, "text": text})


def select(s: dict, eid: str) -> None:
    if s["ended"]:
        return
    s["selected"] = None if s["selected"] == eid else eid


def cancel_selection(s: dict) -> None:
    s["selected"] = None


def move_selected(s: dict, target: str | None) -> None:
    eid = s["selected"]
    s["selected"] = None
    if eid is None or s["ended"]:
        return
    prev = s["assign"][eid]
    if prev == target:
        return
    s["assign"][eid] = target

    if not s["attendance_confirmed"]:
        _save(s)
        return  # placing people before attendance is confirmed is not timed

    t = now(s)
    e = emp(s, eid)
    if eid in s["open"]:
        a, start = s["open"].pop(eid)
        s["intervals"].append({"eid": eid, "area": a, "start": start, "end": t})
    if target is not BOX:
        s["open"][eid] = (target, t)

    att = s["attendance"][eid]
    if prev is BOX and target is not BOX:
        if att["status"] == "Absent":
            att.update(status="Late", time=t)
            _log(s, "late", f"{e['name']} arrived late → {area_short(s, target)}")
        else:
            s["left"].pop(eid, None)
            _log(s, "move", f"{e['name']} back on the floor → {area_short(s, target)}")
    elif target is BOX:
        s["left"][eid] = t
        _log(s, "left", f"{e['name']} left the floor ({area_short(s, prev)} → Box)")
    else:
        _log(s, "move", f"{e['name']}  {area_short(s, prev)} → {area_short(s, target)}")
    _save(s)


def load_usual_layout(s: dict) -> None:
    if s["attendance_confirmed"]:
        return
    for e in s["employees"]:
        s["assign"][e["id"]] = e["home"]
    s["selected"] = None


def clear_board(s: dict) -> None:
    if s["attendance_confirmed"]:
        return
    for e in s["employees"]:
        s["assign"][e["id"]] = BOX
    s["selected"] = None


def confirm_attendance(s: dict) -> None:
    if s["attendance_confirmed"]:
        return
    t = now(s)
    present = absent = 0
    for e in s["employees"]:
        aid = s["assign"][e["id"]]
        if aid is BOX:
            s["attendance"][e["id"]] = {"status": "Absent", "time": t}
            absent += 1
        else:
            s["attendance"][e["id"]] = {"status": "Present", "time": t}
            s["open"][e["id"]] = (aid, t)
            present += 1
    s["attendance_confirmed"] = True
    s["attendance_time"] = t
    s["last_check"] = t
    s["selected"] = None
    _log(s, "attendance", f"Attendance confirmed by {s['lead']}: {present} present, {absent} absent")
    _save(s)


def confirm_board(s: dict) -> None:
    if not s["attendance_confirmed"] or s["ended"]:
        return
    t = now(s)
    on_time = check_minutes_left(s) >= 0
    s["last_check"] = t
    s["checkins"] += 1 if on_time else 0
    _log(s, "check", f"Board confirmed correct by {s['lead']}" + ("" if on_time else " (late)"))
    _save(s)


def end_shift(s: dict) -> None:
    if not s["attendance_confirmed"] or s["ended"]:
        return
    t = now(s)
    for eid, (a, start) in list(s["open"].items()):
        s["intervals"].append({"eid": eid, "area": a, "start": start, "end": t})
    s["open"].clear()
    s["ended"] = True
    s["end_time"] = t
    s["selected"] = None
    _log(s, "end", f"Shift ended by {s['lead']} · all times closed")
    _save(s)


# ---------- read models ----------

def check_minutes_left(s: dict) -> int:
    if not s["attendance_confirmed"] or s["last_check"] is None:
        return CHECK_EVERY_MIN
    due = s["last_check"] + timedelta(minutes=CHECK_EVERY_MIN)
    return int((due - now(s)).total_seconds() // 60)


def minutes_by_area(s: dict, eid: str) -> dict[str, float]:
    out: dict[str, float] = {}
    for iv in s["intervals"]:
        if iv["eid"] == eid:
            out[iv["area"]] = out.get(iv["area"], 0) + (iv["end"] - iv["start"]).total_seconds() / 60
    if eid in s["open"]:
        a, start = s["open"][eid]
        out[a] = out.get(a, 0) + max(0.0, (now(s) - start).total_seconds() / 60)
    return out


def summary_rows(s: dict) -> list[dict]:
    rows = []
    for e in s["employees"]:
        att = s["attendance"].get(e["id"], {})
        status = att.get("status", "Not confirmed")
        if status == "Late":
            status = f"Late ({fmt(att['time'])})"
        if e["id"] in s["left"]:
            status += f" · left {fmt(s['left'][e['id']])}"
        mins = minutes_by_area(s, e["id"])
        brk = mins.pop("BRK", 0)
        rows.append({
            "eid": e["id"],
            "Employee": e["name"],
            "Role": e["role"],
            "Attendance": status,
            "areas": mins,
            "Time by area": " · ".join(f"{area_short(s, a)} {fmt_min(m)}" for a, m in mins.items() if m >= 1),
            "Break": fmt_min(brk) if brk >= 1 else "",
            "Worked": fmt_min(sum(mins.values())),
            "worked_min": round(sum(mins.values())),
        })
    return rows


def short_areas(s: dict) -> list[tuple[dict, int]]:
    out = []
    for a in s["areas"]:
        if a["std"] is None:
            continue
        n = len(crew(s, a["id"]))
        if n < a["std"]:
            out.append((a, n))
    return out


# ================= screens =================

ROLE_KEY = {"Operator": "op", "Assistant": "as", "Palletizer": "pa", "Kit line": "kt"}
GRID_COLS = 7

CSS = """
<style>
/* chips: one per employee, colored by role */
[class*="st-key-chip-"] button {
  border-radius: 999px; border: 0; min-height: 40px; padding: 2px 14px;
  font-weight: 700; color: #0B1220 !important;
}
[class*="st-key-chip-op-"] button { background: #60A5FA; }
[class*="st-key-chip-as-"] button { background: #FBBF24; }
[class*="st-key-chip-pa-"] button { background: #2DD4BF; }
[class*="st-key-chip-kt-"] button { background: #C4B5FD; }
[class*="st-key-chip-"] button:hover { filter: brightness(1.1); color: #0B1220 !important; }
[class*="st-key-chip-"][class*="-sel-"] button {
  outline: 3px solid #FACC15; outline-offset: 2px; transform: scale(1.05);
}
[class*="st-key-chip-"][class*="-dim-"] button { opacity: .7; }

/* primary buttons: dark text on yellow */
button[kind="primary"] { background: #FACC15 !important; border-color: #FACC15 !important; }
button[kind="primary"] p, [class*="st-key-chip-"] button p, [class*="st-key-zh-target-"] button p {
  color: #0B1220 !important; font-weight: 700;
}
[class*="st-key-zh-"] button p { color: inherit; }
.fb-boxtitle { color: #E5ECF6; font-weight: 700; padding: 4px 0; }
.fb-boxtitle span { color: #94A3B8; font-weight: 400; }

/* area header buttons */
[class*="st-key-zh-"] button {
  min-height: 44px; border: 0; background: #1B2740; color: #E5ECF6 !important; font-weight: 700;
}
[class*="st-key-zh-short-"] button { color: #FCA5A5 !important; }
[class*="st-key-zh-target-"] button { background: #FACC15; color: #0B1220 !important; }

.fb-zh { color:#E5ECF6; display:flex; justify-content:space-between; align-items:center; min-height:44px; padding:0 12px;
  border-radius:10px; background:#1B2740; font-weight:700; font-size:15px; }
.fb-zh span { color:#94A3B8; font-size:14px; }
.fb-zh.short span { color:#FCA5A5; }
.fb-zh.brk { background:#151E30; }

/* area tiles */
[class*="st-key-zone-"] { background: #131C2E; border-radius: 14px; }
[class*="st-key-zone-short-"] { border: 1px solid #F87171 !important; }
[class*="st-key-zone-target-"] { border: 1px solid #FACC15 !important; }
[class*="st-key-zone-brk-"] { border: 1px dashed #475569 !important; background: #0F1626; }
[class*="st-key-boxzone"] { background: #131C2E; border-radius: 14px; }

/* pills */
.fb-pill { color:#E5ECF6; display:inline-block; padding:6px 12px; border-radius:12px; background:#131C2E;
  border:1px solid #26344D; font-size:14px; margin-right:6px; }
.fb-pill b { font-weight:700; }
.fb-live { display:inline-block; padding:3px 10px; border-radius:999px; background:#0F2A1E;
  color:#4ADE80; font-size:12px; font-weight:700; letter-spacing:.06em; }
.fb-due { display:inline-block; padding:8px 12px; border-radius:12px; font-weight:600; font-size:14px; }
.fb-hint { padding:10px 14px; border-radius:12px; background:#FACC15; color:#0B1220; font-weight:600; }
.fb-move { color:#E5ECF6; display:inline-block; padding:6px 10px; border-radius:10px; background:#1B2740;
  font-size:13px; margin:0 6px 6px 0; }
.fb-move span { color:#94A3B8; margin-right:6px; }
.fb-legend span { display:inline-flex; align-items:center; gap:5px; margin-right:12px; font-size:13px; color:#94A3B8; }
.fb-legend i { width:10px; height:10px; border-radius:50%; display:inline-block; }
</style>
"""


# ---------- shared pieces ----------

def _moves(s: dict) -> int:
    return sum(1 for ev in s["events"] if ev["kind"] in ("move", "late", "left"))


def _chip(s: dict, e: dict, where: str) -> None:
    sel = s["selected"]
    state = "sel" if sel == e["id"] else ("dim" if sel else "n")
    st.button(
        e["name"],
        key=f"chip-{ROLE_KEY[e['role']]}-{state}-{where}-{e['id']}",
        on_click=select, args=(s, e["id"]),
        help=f"{e['name']} · {e['role']}",
        disabled=s["ended"],
        width="stretch" if where == "tile" else "content",
    )


def _legend() -> None:
    items = "".join(f'<span><i style="background:{c}"></i>{r}</span>' for r, c in ROLES.items())
    st.markdown(f'<div class="fb-legend">{items}</div>', unsafe_allow_html=True)


# ---------- dialogs ----------

@st.dialog("Confirm attendance")
def _attendance_dialog(s: dict) -> None:
    absent = crew(s, BOX)
    present = len(s["employees"]) - len(absent)
    st.write(f"**{present} present** (on a line) · **{len(absent)} absent** (still in the box)")
    if absent:
        st.caption("Will be marked absent: " + ", ".join(e["name"] for e in absent))
    st.caption("Line time starts now. Anyone placed later from the box is recorded as late.")
    c1, c2 = st.columns(2)
    if c1.button("Confirm", type="primary", width="stretch"):
        confirm_attendance(s)
        st.rerun()
    if c2.button("Go back", width="stretch"):
        st.rerun()


@st.dialog("End shift")
def _end_dialog(s: dict) -> None:
    st.write("This closes everyone's time at " + fmt(now(s)) + " and locks the board.")
    c1, c2 = st.columns(2)
    if c1.button("End shift", type="primary", width="stretch"):
        end_shift(s)
        st.rerun()
    if c2.button("Cancel", width="stretch"):
        st.rerun()


# ---------- sub-window 1: floor lead board ----------

def board(s: dict) -> None:
    on_floor = sum(1 for e in s["employees"] if s["assign"][e["id"]] not in (BOX, "BRK"))
    in_box = len(crew(s, BOX))

    top_l, top_r = st.columns([3, 2], vertical_alignment="center")
    with top_l:
        st.markdown(
            f"### Floor Board &nbsp;<span class='fb-live'>LIVE</span>\n"
            f"{s['shift']} · Floor lead: {s['lead']} · {fmt(now(s))}",
            unsafe_allow_html=True,
        )
    with top_r:
        box_label = "Absent" if s["attendance_confirmed"] else "Not placed"
        st.markdown(
            f"<span class='fb-pill'>On floor <b>{on_floor}</b></span>"
            f"<span class='fb-pill'>{box_label} <b>{in_box}</b></span>"
            f"<span class='fb-pill'>Moves <b>{_moves(s)}</b></span>"
            f"<span class='fb-pill'>Check-ins <b style='color:#FACC15'>{s['checkins']}</b></span>",
            unsafe_allow_html=True,
        )

    # status / action row
    if s["ended"]:
        st.success(f"Shift ended at {fmt(s['end_time'])}. See End of shift for the totals.")
    elif not s["attendance_confirmed"]:
        st.info(
            "**Start of shift:** tap a name, then tap the line they're working. "
            "When everyone who's here is placed, confirm attendance. Anyone left in the box is marked absent."
        )
        a, b, c = st.columns([1, 1, 2])
        a.button("Load usual layout", on_click=load_usual_layout, args=(s,), width="stretch")
        b.button("Clear board", on_click=clear_board, args=(s,), width="stretch")
        present = len(s["employees"]) - in_box
        if c.button(f"Confirm attendance · {present} present · {in_box} absent", type="primary", width="stretch"):
            _attendance_dialog(s)
    else:
        left = check_minutes_left(s)
        if left >= 0:
            pill = f"<span class='fb-due' style='background:#2A2111;color:#FBBF24'>Board check due in {left} min</span>"
        else:
            pill = f"<span class='fb-due' style='background:#2A1517;color:#FCA5A5'>Board check overdue by {-left} min</span>"
        a, b = st.columns([3, 1], vertical_alignment="center")
        a.markdown(pill, unsafe_allow_html=True)
        b.button("Board is correct", type="primary", on_click=confirm_board, args=(s,), width="stretch")

    # selection hint
    if s["selected"]:
        e = emp(s, s["selected"])
        h1, h2 = st.columns([5, 1], vertical_alignment="center")
        h1.markdown(f"<div class='fb-hint'>Moving {e['name']} — tap <b>Move here</b> on the area they're going to.</div>",
                    unsafe_allow_html=True)
        h2.button("Cancel", on_click=cancel_selection, args=(s,), width="stretch")
    else:
        _legend()

    # the box
    sel = s["selected"]
    with st.container(border=True, key="boxzone"):
        title = "Absent / off the floor" if s["attendance_confirmed"] else "Not placed yet"
        if sel and s["assign"][sel] is not BOX:
            label = "Move here · left the floor" if s["attendance_confirmed"] else "Move here · back to the box"
            st.button(label, key="zh-target-BOX", on_click=move_selected, args=(s, BOX), width="stretch")
        else:
            st.markdown(f"<div class='fb-boxtitle'>{title} <span>· {in_box}</span></div>", unsafe_allow_html=True)
        with st.container(horizontal=True, wrap=True, gap="small"):
            for e in crew(s, BOX):
                _chip(s, e, "box")

    # the areas
    areas = s["areas"]
    for i in range(0, len(areas), GRID_COLS):
        cols = st.columns(GRID_COLS, gap="small")
        for col, a in zip(cols, areas[i:i + GRID_COLS]):
            with col:
                _tile(s, a)

    # latest moves
    moves = [ev for ev in s["events"]][:5]
    if moves:
        html = "".join(f"<span class='fb-move'><span>{fmt(ev['t'])}</span>{ev['text']}</span>" for ev in moves)
        st.markdown("**Latest** &nbsp; " + html, unsafe_allow_html=True)


def _tile(s: dict, a: dict) -> None:
    people = crew(s, a["id"])
    n = len(people)
    sel = s["selected"]
    is_target = bool(sel) and s["assign"][sel] != a["id"]
    is_short = a["std"] is not None and n < a["std"] and s["attendance_confirmed"]
    if is_target:
        state = "target"
    elif a["id"] == "BRK":
        state = "brk"
    elif is_short:
        state = "short"
    else:
        state = "ok"
    count = str(n) if a["std"] is None else f"{n}/{a['std']}"
    with st.container(border=True, key=f"zone-{state}-{a['id']}"):
        if is_target:
            st.button(f"Move to {a['short']}", key=f"zh-target-{a['id']}", on_click=move_selected,
                      args=(s, a["id"]), width="stretch", help=f"Move to {a['name']}")
        else:
            st.markdown(f"<div class='fb-zh {state}'>{a['name']}<span>{count}</span></div>",
                        unsafe_allow_html=True)
        for e in people:
            _chip(s, e, "tile")


# ---------- sub-window 2: supervisor live view ----------

def supervisor(s: dict) -> None:
    st.markdown(f"### Live floor &nbsp;<span class='fb-live'>LIVE</span>", unsafe_allow_html=True)
    st.caption(f"{s['shift']} · as of {fmt(now(s))} · in the live version this refreshes every few seconds")

    att = s["attendance"]
    on_floor = sum(1 for e in s["employees"] if s["assign"][e["id"]] not in (BOX, "BRK"))
    on_break = len(crew(s, "BRK"))
    absent = sum(1 for v in att.values() if v["status"] == "Absent")
    late = sum(1 for v in att.values() if v["status"] == "Late")
    short = short_areas(s) if s["attendance_confirmed"] else []

    m = st.columns(5)
    m[0].metric("On the floor", on_floor, help=f"{on_break} on break")
    m[1].metric("Absent", absent if s["attendance_confirmed"] else "—")
    m[2].metric("Late", late if s["attendance_confirmed"] else "—")
    m[3].metric("Areas short", len(short) if s["attendance_confirmed"] else "—")
    m[4].metric("Moves", _moves(s))

    if not s["attendance_confirmed"]:
        st.info("Attendance not confirmed yet. Line time starts when the floor lead confirms.")
    else:
        st.markdown("**Needs attention**")
        left = check_minutes_left(s)
        any_alert = False
        if left < 0 and not s["ended"]:
            st.warning(f"Board check overdue by {-left} min ({s['lead']})")
            any_alert = True
        for a, n in short:
            st.error(f"{a['name']}: {n} of {a['std']}")
            any_alert = True
        if not any_alert:
            st.success("All areas staffed and the board is up to date.")

    st.markdown("**Crews**")
    rows = []
    for a in s["areas"]:
        people = crew(s, a["id"])
        rows.append({
            "Area": a["name"],
            "Crew": ", ".join(e["name"] for e in people),
            "On crew": len(people),
            "Standard": a["std"],
        })
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch", height=420)

    st.markdown("**Latest moves**")
    if s["events"]:
        st.dataframe(
            pd.DataFrame([{"Time": fmt(ev["t"]), "What": ev["text"]} for ev in s["events"][:10]]),
            hide_index=True, width="stretch",
        )
    else:
        st.caption("No moves yet.")


# ---------- sub-window 3: end of shift ----------

def summary(s: dict) -> None:
    st.markdown("### End of shift · time by area")
    if not s["attendance_confirmed"]:
        st.info("Nothing recorded yet. Time starts when attendance is confirmed on the Floor Board.")
        return

    if s["ended"]:
        st.caption(f"{s['shift']} · {fmt(s['attendance_time'])} – {fmt(s['end_time'])} · built from the board moves")
    else:
        c1, c2 = st.columns([3, 1], vertical_alignment="center")
        c1.caption(f"Shift in progress · totals as of {fmt(now(s))}")
        if c2.button("End shift", type="primary", width="stretch"):
            _end_dialog(s)

    rows = summary_rows(s)
    view = pd.DataFrame(rows)[["Employee", "Role", "Attendance", "Time by area", "Break", "Worked"]]
    st.dataframe(view, hide_index=True, width="stretch", height=460)

    # downloads: one row per employee per area (what scoring uses), attendance, move log
    long_rows = []
    for r in rows:
        for a, mins in r["areas"].items():
            long_rows.append({"Employee": r["Employee"], "Role": r["Role"], "Area": area(s, a)["name"],
                              "Minutes": round(mins)})
    att_rows = [{"Employee": r["Employee"], "Role": r["Role"], "Attendance": r["Attendance"]} for r in rows]
    log_rows = [{"Time": fmt(ev["t"]), "Event": ev["text"]} for ev in reversed(s["events"])]

    d1, d2, d3 = st.columns(3)
    d1.download_button("Minutes by area (CSV)", pd.DataFrame(long_rows).to_csv(index=False),
                       "minutes_by_area.csv", "text/csv", width="stretch")
    d2.download_button("Attendance (CSV)", pd.DataFrame(att_rows).to_csv(index=False),
                       "attendance.csv", "text/csv", width="stretch")
    d3.download_button("Move log (CSV)", pd.DataFrame(log_rows).to_csv(index=False),
                       "move_log.csv", "text/csv", width="stretch")

    st.markdown("**Move log**")
    st.dataframe(pd.DataFrame(log_rows), hide_index=True, width="stretch")


# ---------- sub-window 4: setup ----------

def setup(s: dict) -> None:
    st.markdown("### Setup")
    locked = s["attendance_confirmed"]

    c1, c2 = st.columns(2)
    s["lead"] = c1.text_input("Floor lead", s["lead"])
    shift = c2.selectbox("Shift", list(SHIFTS), index=list(SHIFTS).index(s["shift"]), disabled=locked,
                         help="Locked after attendance is confirmed.")
    s["shift"] = shift

    st.markdown("**Areas and standard crew size**")
    area_df = pd.DataFrame([{"Area": a["name"], "Standard crew": a["std"]} for a in s["areas"]])
    edited = st.data_editor(area_df, hide_index=True, disabled=["Area"], key="areas_editor", width="stretch",
                            column_config={"Standard crew": st.column_config.NumberColumn(min_value=0, step=1)})
    for a, std in zip(s["areas"], edited["Standard crew"]):
        a["std"] = None if pd.isna(std) else int(std)

    st.markdown("**Roster**")
    if locked:
        st.caption("Roster is locked after attendance is confirmed. Reset the demo to edit it.")
    area_names = {a["id"]: a["name"] for a in s["areas"]}
    name_to_id = {v: k for k, v in area_names.items()}
    roster_df = pd.DataFrame([{"Name": e["name"], "Role": e["role"], "Usual area": area_names.get(e["home"], "")}
                              for e in s["employees"]])
    roster = st.data_editor(
        roster_df, hide_index=True, num_rows="dynamic" if not locked else "fixed", disabled=locked,
        key="roster_editor", width="stretch",
        column_config={
            "Role": st.column_config.SelectboxColumn(options=list(ROLES), required=True),
            "Usual area": st.column_config.SelectboxColumn(options=list(area_names.values())),
        },
    )
    if not locked and st.button("Save roster"):
        new = []
        for i, r in roster.iterrows():
            if not isinstance(r["Name"], str) or not r["Name"].strip():
                continue
            new.append({"id": f"E{i + 1:03d}", "name": r["Name"].strip(),
                        "role": r["Role"] if r["Role"] in ROLES else "Operator",
                        "home": name_to_id.get(r["Usual area"], "L1")})
        s["employees"] = new
        s["assign"] = {e["id"]: BOX for e in new}
        s["selected"] = None
        st.success(f"Roster saved: {len(new)} employees, all back in the box.")

    st.divider()
    st.markdown("**Demo**")
    s["clock_mode"] = st.radio(
        "Clock", ["demo", "real"], index=["demo", "real"].index(s["clock_mode"]), horizontal=True,
        format_func=lambda v: "Demo clock (moves with the sidebar buttons)" if v == "demo" else "Real time",
    )
    if st.button("Reset demo", type="secondary"):
        reset()
        st.rerun()


# ---------- the window ----------

def page() -> None:
    st.markdown(CSS, unsafe_allow_html=True)
    s = get_state()

    with st.sidebar:
        st.markdown("**Floor Board demo**")
        st.caption("Memory only: refreshing the page resets the demo.")
        if s["clock_mode"] == "demo":
            st.markdown(f"Demo clock: **{fmt(now(s))}**")
            b1, b2 = st.columns(2)
            b1.button("+15 min", on_click=advance_clock, args=(s, 15), width="stretch")
            b2.button("+1 hour", on_click=advance_clock, args=(s, 60), width="stretch")
        else:
            st.markdown(f"Clock: **{fmt(now(s))}** (real time)")

    t1, t2, t3, t4 = st.tabs(["Floor Board", "Supervisor view", "End of shift", "Setup"])
    with t1:
        board(s)
    with t2:
        supervisor(s)
    with t3:
        summary(s)
    with t4:
        setup(s)


if __name__ == "__main__":
    st.set_page_config(page_title="Floor Board", page_icon=":material/groups:", layout="wide",
                       initial_sidebar_state="collapsed")
    page()
