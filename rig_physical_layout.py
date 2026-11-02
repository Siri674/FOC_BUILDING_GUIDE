#!/usr/bin/env python3
"""
iGL-FOC-1 no-PCB rig: physical layout drawing (top view of the base plate).

Draws every board where it sits on the plate, every header pin in its physical position
(2.54 mm grid), the breadboard holes, rails and placed parts, and every wire from
rig_wiring.py between the exact pins it plugs into.

Outputs (in ./rig_wiring_out by default):
  rig_physical_layout.svg   printable drawing (open in a browser, zoom in)
  rig_physical_layout.html  interactive: hover a wire or a table row to highlight it,
                            filter by group, search by wire ID / pin / net
It also prints a physical length check: straight-line distance between the two pins and the
shortest standard jumper that reaches it (straight distance <= 0.85 x jumper length).

Usage:  python rig_physical_layout.py [output_dir]
Needs rig_wiring.py in the same folder. Standard library only.

Geometry notes (check against your boards before wiring):
  * Nucleo-64 (UM2505): morpho CN7 on the left edge, CN10 on the right edge, 2 x 19 pins,
    pin 1 = top-left pin of each header at the ST-LINK USB end, odd pins in the left column.
  * BOOSTXL-DRV8323RS (SLVUB01C, BoosterPack 40-pin standard): J3 on the left edge
    (odd pins outer column, even pins inner column), J4 on the right edge (odd pins inner,
    even pins outer), pin pairs 1/2 at the top (the end with J3.1 = 3.3 V and J4.2 = GND).
  * Power terminal and motor terminal J5 positions are drawn approximately: follow the silkscreen.
  * Breadboard: MB-102, 63 columns, rows a-e / f-j, top rails + (3V3) and - (GND).
"""
import math
import sys
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rig_wiring as rw  # noqa: E402

S = 4.0                 # px per mm
OX, OY = 30, 60         # px offset of the plate origin
PITCH = 2.54
PLATE_W, PLATE_H = 430, 250   # mm

# --------------------------------------------------------------------------------------
# Board positions on the plate (mm, top-left corners)
# --------------------------------------------------------------------------------------
NUC = dict(x=150, y=40, w=70, h=82.5)          # NUCLEO-G474RE
BXL = dict(x=238, y=68, w=58, h=62)            # BOOSTXL-DRV8323RS
BB = dict(x=45, y=150, w=165, h=55)            # MB-102 breadboard
MOT = dict(cx=300, cy=178, r=28.5)             # 5010 motor (top view)
ENC = dict(x=289, y=167, w=22, h=22)           # AS5047P breakout on the bracket over the shaft
PB = dict(x=345, y=62, w=62, h=58)             # perfboard regen kit
CANABLE = dict(x=8, y=214, w=48, h=24)
PSU = dict(x=350, y=8, w=70, h=26)
FUSE = dict(x=322, y=40, w=18, h=8)


def mm(x, y):
    return OX + x * S, OY + y * S


# --------------------------------------------------------------------------------------
# Pin coordinates
# --------------------------------------------------------------------------------------
def nucleo_xy(pin):
    hdr, n = pin.split(".")
    n = int(n)
    row, odd = (n - 1) // 2, n % 2 == 1
    y = NUC["y"] + 16 + row * PITCH
    if hdr == "CN7":
        x = NUC["x"] + (3.0 if odd else 3.0 + PITCH)
    else:
        x = NUC["x"] + NUC["w"] - (3.0 + PITCH if odd else 3.0)
    return x, y


def boostxl_xy(pin):
    if pin.startswith("J3.") or pin.startswith("J4."):
        hdr, n = pin.split(".")
        n = int(n)
        row, odd = (n - 1) // 2, n % 2 == 1
        y = BXL["y"] + 8 + row * PITCH
        if hdr == "J3":
            x = BXL["x"] + (3.0 if odd else 3.0 + PITCH)
        else:
            x = BXL["x"] + BXL["w"] - (3.0 + PITCH if odd else 3.0)
        return x, y
    if pin in ("VM+", "VM-"):
        return BXL["x"] + BXL["w"] + 4, BXL["y"] + (40 if pin == "VM+" else 47)
    if pin.startswith("J5."):
        k = "ABC".index(pin[-1])
        return BXL["x"] + 32 + k * 7, BXL["y"] + BXL["h"] + 3
    raise KeyError(pin)


def bb_hole(col, row):
    """col 1..63, row in 'abcde' (top half) or '+' / '-' (top rails)."""
    x = BB["x"] + 6 + (col - 1) * PITCH
    if row == "+":
        y = BB["y"] + 4
    elif row == "-":
        y = BB["y"] + 4 + PITCH
    else:
        y = BB["y"] + 12 + "abcde".index(row) * PITCH
    return x, y


def bb_col_from_x(x):
    return max(1, min(63, round((x - BB["x"] - 6) / PITCH) + 1))


# Breadboard plan: node columns and part placements
NODE_COL = {"NFLT": 62, "NTC_FET": 14, "NTC_MOT": 22}
U4_COL = {"3V3": 44, "GND": 45, "CTX": 46, "CRX": 47}     # module 4-pin header in row e
rail_used = {"+": set(), "-": set()}
col_rows_free = {c: list("abcd") for c in list(NODE_COL.values()) + list(U4_COL.values())}
col_rows_free[59] = list("abcd")
BB_PARTS = []   # (ref, (x1,y1), (x2,y2), kind, label)


def take_row(col):
    return col_rows_free[col].pop(0)


def take_rail(rail, near_x):
    c0 = bb_col_from_x(near_x)
    for d in range(0, 63):
        for c in (c0 - d, c0 + d):
            if 1 <= c <= 63 and c not in rail_used[rail]:
                rail_used[rail].add(c)
                return bb_hole(c, rail)
    raise RuntimeError("rail full")


def place_bb_parts():
    for ref, node, rail, kind in (("R1", "NTC_FET", "+", "res"), ("C1", "NTC_FET", "-", "cap"),
                                  ("R2", "NTC_MOT", "+", "res"), ("C2", "NTC_MOT", "-", "cap")):
        c = NODE_COL[node]
        hole = bb_hole(c, take_row(c))
        rc = c if rail == "+" else c + 1
        rail_used[rail].add(rc)
        BB_PARTS.append((ref, bb_hole(rc, rail), hole, kind, f"{ref} {rw.COMPONENTS[ref][0]}"))
    # SW1: legs in NFLT column and column 8, short link from column 8 to the GND rail
    c = NODE_COL["NFLT"]
    BB_PARTS.append(("SW1", bb_hole(c, "e"), bb_hole(59, "e"), "sw", "SW1"))
    rail_used["-"].add(59)
    BB_PARTS.append(("link", bb_hole(59, take_row(59)), bb_hole(59, "-"), "link", "link"))


ENC_PINS = ["CLK", "MISO", "MOSI", "CSn", "VDD3V3", "GND"]
_cache = {}


def ep_xy(wid, ref, pin, other_x):
    key = (wid, ref, pin)
    if key in _cache:
        return _cache[key]
    if ref == "U1":
        p = nucleo_xy(pin)
    elif ref == "U2":
        p = boostxl_xy(pin)
    elif ref == "BB":
        if pin == "+3V3 rail":
            p = take_rail("+", other_x)
        elif pin == "GND rail":
            p = take_rail("-", other_x)
        else:
            c = NODE_COL[pin]
            p = bb_hole(c, take_row(c))
    elif ref == "U3":
        p = (ENC["x"] + 2, ENC["y"] + 3 + ENC_PINS.index(pin) * PITCH)
    elif ref == "U4":
        if pin in U4_COL:
            c = U4_COL[pin]
            p = bb_hole(c, take_row(c))
        else:  # CANH / CANL screw terminal on the module body
            p = (bb_hole(45, "e")[0] + (0 if pin == "CANH" else 5), BB["y"] + 46)
    elif ref == "U5":
        p = (CANABLE["x"] + CANABLE["w"], CANABLE["y"] + 6 + ["CANH", "CANL", "GND"].index(pin) * 6)
    elif ref == "M1":
        a = math.radians({"A": 240, "B": 270, "C": 300}[pin])
        p = (MOT["cx"] + MOT["r"] * math.cos(a), MOT["cy"] + MOT["r"] * math.sin(a))
    elif ref == "RT1":
        p = (BXL["x"] + 30 + (0 if pin == "1" else 3), BXL["y"] + 46)
    elif ref == "RT2":
        p = (MOT["cx"] + 20 + (0 if pin == "1" else 3), MOT["cy"] + 21)
    elif ref == "SCOPE":
        p = (140, 132)
    elif ref == "PSU":
        p = (PSU["x"] + (14 if pin == "+" else 30), PSU["y"] + PSU["h"])
    elif ref == "F1":
        p = (FUSE["x"] + (0 if pin == "in" else FUSE["w"]), FUSE["y"] + FUSE["h"] / 2)
    elif ref == "D1":
        p = (PB["x"] + (8 if pin.startswith("A") else 30), PB["y"] + 10)
    elif ref == "PB":
        p = (PB["x"] + 4, PB["y"] + (40 if pin == "BUS+" else 50))
    else:
        raise KeyError(f"{wid}: no physical position for {ref}.{pin}")
    _cache[key] = p
    return p


def rough_xy(ref, pin):
    """Position used only to pick the nearest rail hole."""
    try:
        return ep_xy("_probe", ref, pin, 0) if ref not in ("BB", "U4") else (bb_hole(30, "a"))
    finally:
        _cache.pop(("_probe", ref, pin), None)


# --------------------------------------------------------------------------------------
# Drawing
# --------------------------------------------------------------------------------------
def build():
    place_bb_parts()
    wires = []
    for i, w in enumerate(rw.WIRES):
        wid, grp, a, b, net, func, col, maxlen, typ, note = w
        ax_guess = rough_xy(*b)[0]
        pa = ep_xy(wid, a[0], a[1], ax_guess)
        pb = ep_xy(wid, b[0], b[1], pa[0])
        dist_cm = math.dist(pa, pb) / 10
        # a jumper of length L reaches comfortably up to about 0.85 L in a straight line
        std = next((L for L in (5, 10, 15, 20, 30, 40, 60, 100, 200) if dist_cm <= 0.85 * L), 300)
        wires.append(dict(w=w, i=i, pa=pa, pb=pb, dist=dist_cm, std=std))
    return wires


def svg_doc(wires, checks):
    W = int(OX * 2 + PLATE_W * S + 360)
    H = int(OY + PLATE_H * S + 120)
    o = []
    add = o.append
    add(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
        f'font-family="Segoe UI, Arial, sans-serif" id="layout">')
    add('<style>.wire{fill:none;stroke-linecap:round;opacity:.9}.wire.dim{opacity:.08}.wire.hi{stroke-width:6!important;opacity:1}'
        '.pinlbl{font-size:8px;fill:#222;paint-order:stroke;stroke:#fff;stroke-width:2.5px;stroke-linejoin:round}.small{font-size:9px;fill:#444}.title{font-size:13px;font-weight:700}</style>')
    add(f'<rect width="{W}" height="{H}" fill="#ffffff"/>')
    nf = sum(1 for c in checks if c[0] == "FAIL")
    add(f'<text x="{OX}" y="24" font-size="18" font-weight="700">iGL-FOC-1 no-PCB rig: physical layout (top view, base plate {PLATE_W} x {PLATE_H} mm)</text>')
    add(f'<text x="{OX}" y="44" font-size="12" fill="{"#2e7d32" if nf == 0 else "#c62828"}">'
        f'rig_wiring.py checks: {"ALL PASS" if nf == 0 else str(nf) + " FAIL"} · 1 grid square = 10 mm · '
        f'pin 1 of every header = square pad · positions of power terminal / J5 approximate</text>')

    def rect(d, fill, stroke="#555", rx=4, extra=""):
        x, y = mm(d["x"], d["y"])
        add(f'<rect x="{x}" y="{y}" width="{d["w"] * S}" height="{d["h"] * S}" rx="{rx}" fill="{fill}" stroke="{stroke}" stroke-width="1.4" {extra}/>')

    def text(xm, ym, t, cls="small", anchor="start", extra=""):
        x, y = mm(xm, ym)
        add(f'<text x="{x:.1f}" y="{y:.1f}" class="{cls}" text-anchor="{anchor}" {extra}>{escape(t)}</text>')

    # plate and grid
    px, py = mm(0, 0)
    add(f'<rect x="{px}" y="{py}" width="{PLATE_W * S}" height="{PLATE_H * S}" fill="#f7f3ea" stroke="#b9ae98" stroke-width="2" rx="10"/>')
    for gx in range(10, PLATE_W, 10):
        x, _ = mm(gx, 0)
        add(f'<line x1="{x}" y1="{py}" x2="{x}" y2="{py + PLATE_H * S}" stroke="#ebe4d4" stroke-width="1"/>')
    for gy in range(10, PLATE_H, 10):
        _, y = mm(0, gy)
        add(f'<line x1="{px}" y1="{y}" x2="{px + PLATE_W * S}" y2="{y}" stroke="#ebe4d4" stroke-width="1"/>')

    used = {}
    for wd in wires:
        w = wd["w"]
        for ref, pin in (w[2], w[3]):
            used.setdefault((ref, pin), []).append(w[0])

    def header_pins(xy_fn, pins, ref):
        for pin in pins:
            x, y = mm(*xy_fn(pin))
            n = int(pin.split(".")[1])
            u = (ref, pin) in used
            fill = "#ffd54f" if u else "#9e9e9e"
            if n == 1:
                add(f'<rect x="{x - 4}" y="{y - 4}" width="8" height="8" fill="{fill}" stroke="#333" stroke-width="1"/>')
            else:
                add(f'<circle cx="{x}" cy="{y}" r="3.6" fill="{fill}" stroke="#333" stroke-width="{1 if u else .5}"/>')

    # NUCLEO
    rect(NUC, "#dfe9f7")
    text(NUC["x"] + NUC["w"] / 2, NUC["y"] + 7, "U1 NUCLEO-G474RE", "title", "middle")
    ux, uy = mm(NUC["x"] + NUC["w"] / 2 - 6, NUC["y"] - 3)
    add(f'<rect x="{ux}" y="{uy}" width="{12 * S}" height="{8 * S}" fill="#c0c0c0" stroke="#555"/>')
    text(NUC["x"] + NUC["w"] / 2, NUC["y"] - 5, "CN1 USB → PC (ST-LINK, power, VCP)", "small", "middle")
    text(NUC["x"] + NUC["w"] / 2, NUC["y"] + 76, "B1 (PC13) · LD2 (PA5) · X3 24 MHz", "small", "middle")
    for hdr in ("CN7", "CN10"):
        header_pins(nucleo_xy, [f"{hdr}.{n}" for n in range(1, 39)], "U1")
        top = nucleo_xy(f"{hdr}.1")
        text(top[0] + (1.3 if hdr == "CN7" else -1.3), top[1] - 4, hdr, "small", "middle", 'font-weight="700"')
    # Nucleo pin labels (inside the board, one line per header row)
    for hdr, side in (("CN7", 1), ("CN10", -1)):
        for row in range(19):
            items = []
            for n in (2 * row + 1, 2 * row + 2):
                pin = f"{hdr}.{n}"
                if ("U1", pin) in used:
                    items.append(f"{n} {rw.nucleo_pin(pin)} {'/'.join(used[('U1', pin)])}")
            if items:
                x, y = nucleo_xy(f"{hdr}.{2 * row + 1}")
                if side == 1:
                    text(x + 5.5, y + 0.9, " · ".join(items), "pinlbl", "start")
                else:
                    text(x - 2.6, y + 0.9, " · ".join(items), "pinlbl", "end")

    # BOOSTXL
    rect(BXL, "#f6e2d6")
    text(BXL["x"] + BXL["w"] / 2, BXL["y"] - 2, "U2 BOOSTXL-DRV8323RS", "title", "middle")
    fx, fy = mm(BXL["x"] + 18, BXL["y"] + 38)
    add(f'<rect x="{fx}" y="{fy}" width="{24 * S}" height="{14 * S}" fill="#5d4037" opacity=".25" rx="3"/>')
    text(BXL["x"] + 30, BXL["y"] + 54, "FETs (RT1 taped here)", "small", "middle")
    for hdr in ("J3", "J4"):
        header_pins(boostxl_xy, [f"{hdr}.{n}" for n in range(1, 21)], "U2")
        top = boostxl_xy(f"{hdr}.1")
        text(top[0], top[1] - 4, hdr, "small", "middle", 'font-weight="700"')
    for hdr, side in (("J3", 1), ("J4", -1)):
        for row in range(10):
            items = []
            for n in (2 * row + 1, 2 * row + 2):
                pin = f"{hdr}.{n}"
                if ("U2", pin) in used:
                    items.append(f"{n} {rw.boostxl_pin(pin)}")
            if items:
                # J3 labels inside the board, J4 labels outside on the right (keeps the centre readable)
                x0 = boostxl_xy(f"{hdr}.2")[0]
                y = BXL["y"] + 8 + row * PITCH
                text(x0 + 2.6, y + 0.9, " · ".join(items), "pinlbl", "start")
    text(BXL["x"] + 4, BXL["y"] + 36, "J3.1 = 3.3 V OUT: leave open", "small", extra='fill="#c62828"')
    # power terminal + J5
    for pin, lbl in (("VM+", "VM+"), ("VM-", "GND")):
        x, y = mm(*boostxl_xy(pin))
        add(f'<rect x="{x - 10}" y="{y - 10}" width="20" height="20" fill="#2e7d32" stroke="#1b5e20"/>')
        text(boostxl_xy(pin)[0] + 4, boostxl_xy(pin)[1] + 1, lbl, "small")
    for ph in "ABC":
        x, y = mm(*boostxl_xy("J5." + ph))
        add(f'<rect x="{x - 10}" y="{y - 10}" width="20" height="20" fill="#2e7d32" stroke="#1b5e20"/>')
        text(boostxl_xy("J5." + ph)[0], boostxl_xy("J5." + ph)[1] + 6, ph, "small", "middle")
    text(BXL["x"] + 39, BXL["y"] + BXL["h"] + 10, "J5 motor", "small", "middle")
    text(BXL["x"] + BXL["w"] + 8, BXL["y"] + 54, "power terminal", "small")

    # breadboard
    rect(BB, "#fbfbfb", "#999")
    text(BB["x"] + 2, BB["y"] - 2, "BB breadboard MB-102 (logic only: never motor or bus power)", "title")
    for c in range(1, 64):
        for r in "abcde":
            x, y = mm(*bb_hole(c, r))
            add(f'<rect x="{x - 1.6}" y="{y - 1.6}" width="3.2" height="3.2" fill="#ccc"/>')
        for r in "+-":
            x, y = mm(*bb_hole(c, r))
            add(f'<rect x="{x - 1.6}" y="{y - 1.6}" width="3.2" height="3.2" fill="#ccc"/>')
        if c % 5 == 0:
            text(bb_hole(c, "a")[0], BB["y"] + 10.2, str(c), "pinlbl", "middle", 'fill="#999"')
    for r, colr, lbl in (("+", "#d62728", "+ rail = +3V3 (from W20)"), ("-", "#1f4fb4", "− rail = GND (from W21)")):
        x1, y = mm(*bb_hole(1, r))
        x2, _ = mm(*bb_hole(63, r))
        add(f'<line x1="{x1 - 6}" y1="{y}" x2="{x2 + 6}" y2="{y}" stroke="{colr}" stroke-width="1.2" opacity=".6"/>')
        text(BB["x"] + BB["w"] + 1, (BB["y"] + 4 if r == "+" else BB["y"] + 6.8) + 0.8, lbl, "pinlbl")
    for r in "abcde":
        text(BB["x"] + 2.5, bb_hole(1, r)[1] + 0.9, r, "pinlbl", "middle", 'fill="#999"')
    for node, c in NODE_COL.items():
        text(bb_hole(c, "e")[0], bb_hole(c, "e")[1] + 5, node, "pinlbl", "middle", 'font-weight="700"')
    for ref, p1, p2, kind, lbl in BB_PARTS:
        x1, y1 = mm(*p1)
        x2, y2 = mm(*p2)
        colr = {"res": "#c8a165", "cap": "#e3b04b", "sw": "#555", "link": "#222"}[kind]
        add(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="#777" stroke-width="1.5"/>')
        if kind in ("res", "cap", "sw"):
            mx, my = (x1 + x2) / 2, (y1 + y2) / 2
            w_, h_ = (8, 18) if kind != "sw" else (22, 14)
            add(f'<rect x="{mx - w_ / 2}" y="{my - h_ / 2}" width="{w_}" height="{h_}" rx="2" fill="{colr}" stroke="#333" stroke-width=".8"/>')
            add(f'<text x="{mx + w_ / 2 + 2}" y="{my + 3}" class="pinlbl">{escape(ref)}</text>')
        else:
            add(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="#222" stroke-width="2.5"/>')
    # U4 module body (sits over rows f-j)
    mx0, my0 = mm(bb_hole(43, "e")[0] - 1, bb_hole(43, "e")[1] - 1.5)
    add(f'<rect x="{mx0}" y="{my0}" width="{13 * S}" height="{24 * S}" rx="3" fill="#7e57c2" opacity=".35" stroke="#4527a0"/>')
    text(bb_hole(45, "e")[0] + 2, BB["y"] + 34, "U4", "title", "middle")
    text(bb_hole(45, "e")[0] + 2, BB["y"] + 39, "SN65HVD230", "pinlbl", "middle")
    for c, nm in zip(U4_COL.values(), U4_COL.keys()):
        x, y = mm(*bb_hole(c, "e"))
        add(f'<rect x="{x - 3}" y="{y - 3}" width="6" height="6" fill="#ffd54f" stroke="#333"/>')
        add(f'<text x="{x}" y="{y + 11}" class="pinlbl" text-anchor="middle" transform="rotate(90 {x} {y + 11})">{nm}</text>')
    for nm in ("CANH", "CANL"):
        x, y = mm(*ep_xy("_lbl", "U4", nm, 0))
        add(f'<circle cx="{x}" cy="{y}" r="4" fill="#2e7d32"/>')
        add(f'<text x="{x}" y="{y + 13}" class="pinlbl" text-anchor="middle">{nm}</text>')

    # encoder + motor
    cx, cy = mm(MOT["cx"], MOT["cy"])
    add(f'<circle cx="{cx}" cy="{cy}" r="{MOT["r"] * S}" fill="#cfd8dc" stroke="#455a64" stroke-width="2"/>')
    add(f'<circle cx="{cx}" cy="{cy}" r="{4 * S}" fill="#90a4ae" stroke="#455a64"/>')
    # rotor marker: rig_sim_ui.py rotates it with the simulated rotor angle
    add(f'<g id="rotor" transform="rotate(0 {cx} {cy})"><line x1="{cx}" y1="{cy}" x2="{cx}" y2="{cy - MOT["r"] * S * 0.85}" '
        f'stroke="#c62828" stroke-width="5" stroke-linecap="round"/><circle cx="{cx}" cy="{cy - MOT["r"] * S * 0.85}" r="7" fill="#c62828"/></g>')
    text(MOT["cx"], MOT["cy"] + MOT["r"] + 6, "M1 5010 (clamped) · magnet on shaft under U3", "small", "middle")
    rect(ENC, "#c8e6c9", "#2e7d32", 3, 'opacity=".92"')
    text(ENC["x"] + ENC["w"] / 2 + 2, ENC["y"] + ENC["h"] / 2 + 1, "U3 AS5047P", "pinlbl", "middle", 'font-weight="700"')
    for k, pnm in enumerate(ENC_PINS):
        x, y = mm(ENC["x"] + 2, ENC["y"] + 3 + k * PITCH)
        add(f'<circle cx="{x}" cy="{y}" r="3.4" fill="#ffd54f" stroke="#333"/>')
        add(f'<text x="{x + 8}" y="{y + 3}" class="pinlbl">{pnm}</text>')
    for ref, (x_, y_) in (("RT1", (BXL["x"] + 31.5, BXL["y"] + 46)), ("RT2", (MOT["cx"] + 21.5, MOT["cy"] + 21))):
        x, y = mm(x_, y_)
        add(f'<ellipse cx="{x}" cy="{y}" rx="7" ry="4" fill="#212121"/>')
        add(f'<text x="{x + 9}" y="{y + 3}" class="pinlbl">{ref}</text>')

    # regen perfboard, fuse, PSU, CANable, scope probe
    rect(PB, "#e8f5e9", "#2e7d32")
    text(PB["x"] + PB["w"] / 2, PB["y"] - 2, "PB perfboard (regen kit, 14 AWG)", "title", "middle")
    for k, t in enumerate(("D1 MBR2045CT on heatsink (A1+A2 → K)", "C3, C4 2200 µF 50 V (polarity!)",
                           "D2 TVS: band → BUS+")):
        text(PB["x"] + 9, PB["y"] + 14 + k * 8, t, "pinlbl")
    for pin in ("BUS+", "BUS-"):
        x, y = mm(*ep_xy("_lbl", "PB", pin, 0))
        add(f'<rect x="{x - 6}" y="{y - 6}" width="12" height="12" fill="#b0bec5" stroke="#333"/>')
        add(f'<text x="{x + 10}" y="{y + 3}" class="pinlbl">{"BUS+ (P03 in, P04 out)" if pin == "BUS+" else "BUS− (P05 in, P06 out)"}</text>')
    rect(FUSE, "#ffecb3", "#a86b00", 2)
    text(FUSE["x"] + FUSE["w"] / 2, FUSE["y"] - 1.5, "F1 10 A", "pinlbl", "middle")
    rect(PSU, "#eeeeee", "#555")
    text(PSU["x"] + PSU["w"] / 2, PSU["y"] + 10, "PSU (≤ 25.2 V, I-limit)", "title", "middle")
    text(PSU["x"] + PSU["w"] / 2, PSU["y"] + 18, "E-stop on mains / output-enable", "pinlbl", "middle")
    for pin, colr in (("+", "#d62728"), ("-", "#222")):
        x, y = mm(*ep_xy("_lbl", "PSU", pin, 0))
        add(f'<circle cx="{x}" cy="{y}" r="6" fill="{colr}"/>')
    rect(CANABLE, "#ede7f6", "#4527a0")
    text(CANABLE["x"] + 3, CANABLE["y"] + 8, "U5 CANable 2.0", "title")
    text(CANABLE["x"] + 3, CANABLE["y"] + 15, "120 Ω ON · USB → PC", "pinlbl")
    for nm in ("CANH", "CANL", "GND"):
        x, y = mm(*ep_xy("_lbl", "U5", nm, 0))
        add(f'<rect x="{x - 5}" y="{y - 5}" width="10" height="10" fill="#2e7d32"/>')
        add(f'<text x="{x - 8}" y="{y + 3}" class="pinlbl" text-anchor="end">{nm}</text>')
    x, y = mm(*ep_xy("_lbl", "SCOPE", "CH4", 0))
    add(f'<path d="M{x} {y} l-30 18 l-6 -6 z" fill="#607d8b"/>')
    text(130, 140, "scope CH4 hook (PA4 DAC)", "pinlbl", "middle")

    # wires
    for wd in wires:
        w = wd["w"]
        wid, grp, a, b, net, func, col, maxlen, typ, note = w
        x1, y1 = mm(*wd["pa"])
        x2, y2 = mm(*wd["pb"])
        bow = (4 + (wd["i"] % 6) * 2.5) * S   # mm of upward bow, staggered so parallel wires separate
        dx = x2 - x1
        c1 = (x1 + dx * 0.3, min(y1, y2) - bow)
        c2 = (x1 + dx * 0.7, min(y1, y2) - bow)
        if grp in (rw.G_PWR, rw.G_MOT):
            c1 = (x1 + dx * 0.4, y1)
            c2 = (x1 + dx * 0.6, y2)
        width = 5 if grp in (rw.G_PWR, rw.G_MOT) else 2.4
        dash = ' stroke-dasharray="8 5"' if wid in rw.OPTIONAL else ""
        info = (f"{wid} · {grp} · {rw.endpoint_label(*a)} → {rw.endpoint_label(*b)} · net {net} · {func} · "
                f"{col} · straight {wd['dist']:.1f} cm → use {wd['std']} cm{(' · ' + note) if note else ''}")
        add(f'<path class="wire" id="w-{wid}" data-grp={quoteattr(grp)} data-info={quoteattr(info)} '
            f'd="M{x1:.1f},{y1:.1f} C{c1[0]:.1f},{c1[1]:.1f} {c2[0]:.1f},{c2[1]:.1f} {x2:.1f},{y2:.1f}" '
            f'stroke="{rw.COLOURS[col]}" stroke-width="{width}"{dash}><title>{escape(info)}</title></path>')
        for x, y in ((x1, y1), (x2, y2)):
            add(f'<rect x="{x - 2.5}" y="{y - 2.5}" width="5" height="5" fill="#111" pointer-events="none"/>')
        tx, ty = (x1 + 3 * c1[0] + 3 * c2[0] + x2) / 8, (y1 + 3 * c1[1] + 3 * c2[1] + y2) / 8
        add(f'<text x="{tx:.1f}" y="{ty - 3:.1f}" font-size="9" font-weight="700" text-anchor="middle" '
            f'fill="{rw.COLOURS[col]}" stroke="#fff" stroke-width="2.5" paint-order="stroke" pointer-events="none">{wid}</text>')

    # side legend
    lx = OX + PLATE_W * S + 30
    add(f'<text x="{lx}" y="{OY + 10}" font-size="14" font-weight="700">Legend</text>')
    yy = OY + 32
    for name in ("orange", "yellow", "purple", "blue", "green", "red", "black", "white", "grey", "brown"):
        add(f'<line x1="{lx}" y1="{yy}" x2="{lx + 30}" y2="{yy}" stroke="{rw.COLOURS[name]}" stroke-width="4"/>')
        meaning = {"orange": "PWM high side", "yellow": "PWM low side", "purple": "ENABLE / nFAULT", "blue": "SPI",
                   "green": "analog sense", "red": "+3V3 / bus +", "black": "GND / bus −", "white": "CAN H / NTC lead",
                   "grey": "CAN L / RX", "brown": "DAC debug"}[name]
        add(f'<text x="{lx + 38}" y="{yy + 4}" font-size="11">{name}: {meaning}</text>')
        yy += 20
    for t in ("■ yellow pad = used pin, grey = unused", "■ square pad = pin 1 of the header",
              "thick lines = 14/18 AWG power and motor wires", "dashed = optional wire",
              "black squares = Dupont / wire ends", "Hover a wire (HTML) for its full route"):
        add(f'<text x="{lx}" y="{yy + 6}" font-size="11" fill="#444">{escape(t)}</text>')
        yy += 18
    add("</svg>")
    return "\n".join(o)


def html_doc(svg, wires, checks):
    rows = []
    for wd in wires:
        w = wd["w"]
        warn = wd["std"] > w[7]
        rows.append(
            f'<tr data-w="{w[0]}" data-grp={quoteattr(w[1])}><td><b style="color:{rw.COLOURS[w[6]]}">{w[0]}</b></td>'
            f'<td>{escape(rw.endpoint_label(*w[2]))}</td><td>{escape(rw.endpoint_label(*w[3]))}</td><td>{escape(w[4])}</td>'
            f'<td>{wd["dist"]:.1f}</td><td{" class=warn" if warn else ""}>{wd["std"]} cm</td><td>{w[7]} cm</td></tr>')
    groups = sorted({w[1] for w in rw.WIRES})
    boxes = "".join(f'<label><input type="checkbox" class="g" value={quoteattr(g)} checked> {escape(g)}</label>' for g in groups)
    nf = sum(1 for c in checks if c[0] == "FAIL")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Rig Physical Layout</title>
<style>
:root{{--bg:#ffffff;--ink:#1d1f23;--muted:#5d636e;--line:#d9d6cc;--panel:#f6f6f3}}
@media (prefers-color-scheme: dark){{:root:not([data-theme="light"]){{--bg:#16181b;--ink:#e7e5df;--muted:#9aa1ab;--line:#34383e;--panel:#1f2226}}}}
:root[data-theme="dark"]{{--bg:#16181b;--ink:#e7e5df;--muted:#9aa1ab;--line:#34383e;--panel:#1f2226}}
body{{margin:0;font:14px/1.5 system-ui,Segoe UI,Arial,sans-serif;background:var(--bg);color:var(--ink)}}
header{{padding:12px 16px;border-bottom:1px solid var(--line)}} h1{{font-size:20px;margin:0 0 4px}}
.bar{{display:flex;flex-wrap:wrap;gap:10px;align-items:center;padding:8px 16px;border-bottom:1px solid var(--line);background:var(--panel);position:sticky;top:0;z-index:2}}
.bar input[type=search]{{padding:5px 8px;border:1px solid var(--line);border-radius:6px;background:var(--bg);color:var(--ink)}}
#zoomwrap{{overflow:auto;border-bottom:1px solid var(--line);background:#fff}} #zoomwrap svg{{display:block;width:100%;height:auto}}
#info{{padding:8px 16px;min-height:22px;font-family:ui-monospace,Consolas,monospace;font-size:13px;background:var(--panel);border-bottom:1px solid var(--line)}}
table{{border-collapse:collapse;width:100%;font-size:13px}} th,td{{padding:4px 8px;border-bottom:1px solid var(--line);text-align:left}}
tr:hover{{background:rgba(255,213,79,.25);cursor:pointer}} td.warn{{color:#c62828;font-weight:700}} .wrap{{padding:8px 16px 40px;overflow-x:auto}}
.ok{{color:#2e7d32}} .bad{{color:#c62828}}
</style></head><body>
<header><h1>iGL-FOC-1 no-PCB rig: physical layout</h1>
<div>Generated by <code>rig_physical_layout.py</code> from <code>rig_wiring.py</code> ·
<span class="{'ok' if nf == 0 else 'bad'}">wiring checks: {'ALL PASS' if nf == 0 else str(nf) + ' FAIL'}</span> ·
hover a wire or a row to highlight it · zoom: <button id="zin">+</button> <button id="zout">−</button></div></header>
<div class="bar"><input type="search" id="q" placeholder="Search wire / pin / net, e.g. W14, PA0, ISENA">{boxes}</div>
<div id="info">Hover a wire…</div>
<div id="zoomwrap">{svg}</div>
<div class="wrap"><h2 style="font-size:16px">Wires and physical length check</h2>
<p style="color:var(--muted)">"Use" = shortest standard jumper whose length is at least straight distance ÷ 0.85. Red = longer than the limit in rig_wiring.py: move the boards closer or accept the longer wire.</p>
<table><thead><tr><th>Wire</th><th>From</th><th>To</th><th>Net</th><th>Straight (cm)</th><th>Use</th><th>Limit</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table></div>
<script>
const svg=document.getElementById('layout'), info=document.getElementById('info');
let z=1; const zw=document.getElementById('zoomwrap');
function setZ(){{svg.style.width=(100*z)+'%';}}
document.getElementById('zin').onclick=()=>{{z=Math.min(4,z*1.3);setZ();}};
document.getElementById('zout').onclick=()=>{{z=Math.max(1,z/1.3);setZ();}};
const wires=[...svg.querySelectorAll('.wire')];
function hi(id){{wires.forEach(p=>{{p.classList.toggle('hi',p.id==='w-'+id);p.classList.toggle('dim',!!id&&p.id!=='w-'+id);}});
 const p=id&&document.getElementById('w-'+id); info.textContent=p?p.dataset.info:'Hover a wire…';}}
wires.forEach(p=>{{p.addEventListener('mouseenter',()=>hi(p.id.slice(2)));p.addEventListener('mouseleave',()=>hi(null));}});
document.querySelectorAll('tbody tr').forEach(r=>{{r.addEventListener('mouseenter',()=>hi(r.dataset.w));r.addEventListener('mouseleave',()=>hi(null));}});
function filt(){{const on=new Set([...document.querySelectorAll('.g:checked')].map(c=>c.value));
 const q=document.getElementById('q').value.trim().toLowerCase();
 wires.forEach(p=>{{const show=on.has(p.dataset.grp)&&(!q||p.dataset.info.toLowerCase().includes(q));p.style.display=show?'':'none';}});
 document.querySelectorAll('tbody tr').forEach(r=>{{const p=document.getElementById('w-'+r.dataset.w);r.style.display=p.style.display;}});}}
document.querySelectorAll('.g').forEach(c=>c.onchange=filt); document.getElementById('q').oninput=filt;
</script></body></html>"""


def main():
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).with_name("rig_wiring_out")
    out.mkdir(parents=True, exist_ok=True)
    checks = rw.run_checks()
    wires = build()
    svg = svg_doc(wires, checks)
    (out / "rig_physical_layout.svg").write_text(svg, encoding="utf-8")
    (out / "rig_physical_layout.html").write_text(html_doc(svg, wires, checks), encoding="utf-8")
    nf = sum(1 for c in checks if c[0] == "FAIL")
    print(f"wiring checks: {'ALL PASS' if nf == 0 else str(nf) + ' FAIL'}")
    warn = [wd for wd in wires if wd["std"] > wd["w"][7]]
    print(f"{len(wires)} wires drawn. Length check: {len(warn)} wire(s) longer than their limit")
    for wd in warn:
        print(f"  WARN {wd['w'][0]}: straight {wd['dist']:.1f} cm, needs {wd['std']} cm, limit {wd['w'][7]} cm")
    print("->", out / "rig_physical_layout.svg")
    print("->", out / "rig_physical_layout.html")
    sys.exit(1 if nf else 0)


if __name__ == "__main__":
    main()
