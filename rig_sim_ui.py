#!/usr/bin/env python3
# ======================================================================================
#  rig_sim_ui.py  -  Browser UI for rig_sim.py (iGL-FOC-1 no-PCB rig + 5010 motor)
# ======================================================================================
#
#  WHAT IT DOES
#  ------------
#  Starts a small web server on YOUR computer only (http://127.0.0.1:8050) and opens it in
#  your browser. The page shows every parameter of rig_sim.py as an input field (motor,
#  inverter, supply, sensing, control loops, test settings, pass criteria). While you type,
#  the "Derived values" panel updates (torque constant, current range, PI gains, braking
#  energy, warnings). "Run" executes the selected scenarios one by one and shows the
#  PASS/FAIL table, all numbers and the plot of each, as soon as each one finishes.
#
#  HOW TO RUN  (same requirements as rig_sim.py: Python 3.9+, numpy, matplotlib)
#  ----------
#      python rig_sim_ui.py                 start and open the browser
#      python rig_sim_ui.py --port 8060     use another port
#      python rig_sim_ui.py --no-browser    start the server only (open the address yourself)
#  Stop it with Ctrl+C in the terminal.
#
#  FILES
#  -----
#  * "Save parameters" downloads a JSON file in the same format as
#    `python rig_sim.py --write-params` (SI units), so the command line and the UI share files.
#  * "Load parameters" reads such a file back into the form.
#  * Every run is stored in rig_sim_out/ui_runs/<date-time>/ (plots + rig_sim_report.md);
#    "Download report" gives you the Markdown report of the last run.
#
#  NOTES FOR DEVELOPERS
#  --------------------
#  * No extra packages: the server uses Python's built-in http.server.
#  * The page talks to the server with three JSON calls:
#        POST /derived  {params}                      -> derived values + warnings
#        POST /run      {batch, params, scenario, quick} -> one scenario result (plot as base64 PNG)
#        POST /report   {batch}                       -> writes and returns the Markdown report
#        POST /trace    {params, trace, quick}        -> time series for the animated wiring view
#        GET  /layout.svg                              -> physical layout drawing (rig_physical_layout.py)
#  * "Wiring flow" tab: the physical layout of the rig (every wire of rig_wiring.py) is animated
#    from a simulation trace: moving dots = current (direction and size), brightness = PWM duty
#    or logic level, colour = analog voltage, red = fault. Speed, play/pause and a timeline let
#    you watch it in slow motion. See flowStep() in the page script for the signal -> wire mapping.
#  * FIELD_INFO below holds the label, display unit and scale of each parameter.
#    A parameter that is missing from FIELD_INFO still appears (raw SI value), so new
#    parameters added to rig_sim.py show up automatically.
#  * The server is single-threaded on purpose (matplotlib is not thread-safe): one run at a time.
# ======================================================================================

import argparse
import base64
import json
import math
import sys
import time
import traceback
import webbrowser
from dataclasses import asdict, fields
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rig_sim as rs  # noqa: E402

HERE = Path(__file__).resolve().parent
_LAYOUT_SVG = None


def layout_svg():
    """Physical layout drawing, built once (rig_physical_layout allocates breadboard holes
    as it goes, so it must not be rebuilt in the same process)."""
    global _LAYOUT_SVG
    if _LAYOUT_SVG is None:
        import rig_physical_layout as rpl
        import rig_wiring as rw
        _LAYOUT_SVG = rpl.svg_doc(rpl.build(), rw.run_checks())
    return _LAYOUT_SVG


def wire_map():
    """Wire id -> net, group and both ends (from rig_wiring.py), for the animation."""
    import rig_wiring as rw
    return [dict(id=w[0], group=w[1], a=f"{w[2][0]} {w[2][1]}", b=f"{w[3][0]} {w[3][1]}", net=w[4],
                 colour=rw.COLOURS[w[6]]) for w in rw.WIRES]
RUNS_DIR = HERE / "rig_sim_out" / "ui_runs"

# --------------------------------------------------------------------------------------
# Display information: group -> {parameter: (label, display unit, scale, help text)}
# display value = SI value * scale.  Example: L_phase 40e-6 H is shown as 40 µH (scale 1e6).
# --------------------------------------------------------------------------------------
GROUP_TITLES = {"motor": "Motor (5010)", "inverter": "Inverter / BOOSTXL", "supply": "Supply and regen kit",
                "sensing": "Sensing (CSA, ADC, encoder)", "control": "Firmware control", "scen": "Test settings",
                "crit": "Pass criteria", "sim": "Simulation engine"}

FIELD_INFO = {
    "motor": {
        "pole_pairs": ("Pole pairs", "", 1, "14 magnets → 7. Confirmed in T9 (counts per electrical turn)."),
        "kv_rpm_per_v": ("KV", "rpm/V", 1, "Motor velocity constant. K_t = 8.27 / KV."),
        "R_phase": ("Phase resistance", "mΩ", 1e3, "Phase-to-neutral = line-to-line ÷ 2. Measure in T10."),
        "L_phase": ("Phase inductance", "µH", 1e6, "L_d = L_q assumed (surface magnets). Measure in T10."),
        "J": ("Rotor inertia", "g·cm²", 1e7, "Motor rotor only. 500 g·cm² = 5×10⁻⁵ kg·m²."),
        "B_visc": ("Viscous friction", "µN·m·s/rad", 1e6, "Bearing / air drag, proportional to speed."),
        "T_coulomb": ("Dry friction", "mN·m", 1e3, "Constant friction torque."),
        "T_cog": ("Cogging amplitude", "mN·m", 1e3, "Detent torque amplitude."),
        "cog_per_rev": ("Cogging periods per turn", "", 1, "LCM(slots, poles) = LCM(12, 14) = 84."),
    },
    "inverter": {
        "f_pwm": ("PWM frequency", "kHz", 1e-3, "Centre-aligned. The current loop runs once per period."),
        "dead_time": ("Dead time", "ns", 1e9, "TIM1 DTG setting."),
        "R_on": ("FET on-resistance", "mΩ", 1e3, "Added to the phase resistance."),
        "v_diode": ("Body-diode drop", "V", 1, "Used when the gates are off."),
        "I_max_board": ("Board current rating", "A", 1, "BOOSTXL-DRV8323RS: 15 A."),
        "uvlo_v": ("Under-voltage lockout", "V", 1, "Gates switch off below this bus voltage."),
        "uvlo_hyst": ("UVLO hysteresis", "V", 1, "Gates return above UVLO + this."),
    },
    "supply": {
        "V_psu": ("PSU voltage (default)", "V", 1, "Tests override it: see Test settings."),
        "I_limit": ("PSU current limit (default)", "A", 1, "Tests override it: see Test settings."),
        "R_source": ("Source resistance", "mΩ", 1e3, "PSU output + harness + fuse."),
        "V_schottky": ("Schottky drop (D1)", "V", 1, "MBR2045CT at a few amps."),
        "C_bus": ("Regen-kit capacitance (C3+C4)", "µF", 1e6, "0 = no regen kit."),
        "C_board": ("BOOSTXL bulk capacitance", "µF", 1e6, "Read from TI SLVC690."),
        "V_tvs_breakdown": ("TVS breakdown (D2)", "V", 1, "SMCJ28A minimum breakdown."),
        "R_tvs": ("TVS dynamic resistance", "Ω", 1, "SMCJ28A ≈ 0.43 Ω."),
        "I_quiescent": ("Board idle current", "mA", 1e3, "Measure in procedure 5.6."),
    },
    "sensing": {
        "R_shunt": ("Shunt resistance", "mΩ", 1e3, "Read from TI SLVC690 before trusting currents."),
        "csa_gain": ("CSA gain", "V/V", 1, "DRV8323: 5, 10, 20 or 40."),
        "v_ref": ("ADC / CSA reference", "V", 1, "Mid-scale = v_ref / 2 at 0 A."),
        "adc_bits": ("ADC bits", "", 1, "STM32G474: 12."),
        "adc_noise_lsb": ("ADC noise", "LSB rms", 1, "Per sample."),
        "enc_bits": ("Encoder bits", "", 1, "AS5047P: 14 (16384 counts)."),
        "enc_offset_error_deg": ("Encoder offset error", "° el", 1, "What-if: a calibration error."),
        "vbus_noise_rel": ("Bus-voltage noise", "%", 100, "Relative noise of the V_bus reading."),
    },
    "control": {
        "current_bw_hz": ("Current-loop bandwidth", "Hz", 1, "K_p = L·ω_c, K_i = R·ω_c."),
        "decoupling": ("Decoupling feed-forward", "", 1, "Back-EMF and cross-coupling compensation."),
        "v_limit_factor": ("Voltage limit factor", "× V/√3", 1, "Fraction of the SVPWM linear limit."),
        "vel_divider": ("Velocity-loop divider", "ISRs", 1, "8 → 5 kHz at 40 kHz PWM."),
        "vel_filter_tau": ("Speed filter time constant", "ms", 1e3, "Low-pass on the encoder speed."),
        "vel_bw_hz": ("Velocity-loop bandwidth", "Hz", 1, ""),
        "pos_bw_hz": ("Position-loop bandwidth", "Hz", 1, ""),
        "iq_limit": ("i_q limit", "A", 1, "Used by the velocity / position loops."),
        "vel_limit": ("Velocity limit", "rad/s", 1, "Used by the position loop."),
        "ocp_threshold_A": ("Comparator trip level", "A", 1, "0 = automatic: min(0.9 × range, rig max)."),
        "ocp_rig_max_A": ("Rig maximum current", "A", 1, "Procedure safety rule 3: 10 A."),
        "ocp_delay": ("Comparator reaction time", "µs", 1e6, "COMP + blanking + TIM1 break."),
        "vbus_limiter": ("Bus-voltage limiter", "", 1, "Reduce regenerative torque and brake with −I_d."),
        "vbus_lim_start": ("Limiter starts at", "V", 1, ""),
        "vbus_lim_full": ("Limiter fully on at", "V", 1, ""),
        "id_brake": ("Braking −I_d", "A", 1, "Burns energy in the winding."),
    },
    "sim": {
        "dt_avg_div": ("Steps per PWM period", "", 1, "Averaged model resolution."),
        "dt_switching": ("Switching-model step", "ns", 1e9, "Must be well below the dead time."),
        "seed": ("Random seed", "", 1, "ADC noise; the same seed gives the same result."),
    },
    "scen": {
        "test_V_psu": ("PSU voltage, T7 + T11–T14", "V", 1, ""),
        "test_I_limit": ("PSU limit, T7 + T11–T14", "A", 1, ""),
        "t7_iq_A": ("T7 i_q", "A", 1, "Constant current, locked rotor."),
        "t7_duration_ms": ("T7 duration", "ms", 1, "Switching model is slow: keep it short."),
        "t9_V_psu": ("T9 PSU voltage", "V", 1, ""),
        "t9_I_limit": ("T9 PSU current limit", "A", 1, ""),
        "t9_vq_steps": ("T9 V_q steps", "V, list", 1, "Comma-separated, e.g. 0.3, 0.5, 1.0"),
        "t9_f_el_hz": ("T9 field frequency", "Hz el", 1, ""),
        "t9_segment_s": ("T9 time per step", "s", 1, ""),
        "t9_vq_max_procedure": ("Procedure maximum V_q", "V", 1, "Checked against the PSU limit."),
        "t11_iq_steps": ("T11 i_q steps", "A, list", 1, "0 → first → second → 0"),
        "t12_test_threshold_A": ("T12 test threshold", "A", 1, "Lowered comparator level."),
        "t12_test_iq_A": ("T12 test i_q", "A", 1, "Must exceed the test threshold."),
        "t12_fault_angle_deg": ("T12 fault vector angle", "° el", 1, "≈ 100° is the worst case for positive-only comparators."),
        "t13_vel_steps": ("T13 velocity steps", "rad/s, list", 1, ""),
        "t13_vel_hold_s": ("T13 velocity hold", "s", 1, ""),
        "t13_pos_steps_deg": ("T13 position steps", "deg, list", 1, ""),
        "t13_pos_hold_s": ("T13 position hold", "s", 1, ""),
        "t14_speed": ("T14 speed before braking", "rad/s", 1, ""),
        "t14_load_inertia_mult": ("T14 load inertia", "× rotor", 1, "Variants b–d: a real joint."),
    },
    "crit": {
        "vbus_max_V": ("Max V_bus", "V", 1, "T13, T14"), "rise_max_ms": ("Max rise time", "ms", 1, "T11"),
        "overshoot_max_pct": ("Max overshoot", "%", 1, "T11"), "id_dev_max_A": ("Max |i_d|", "A", 1, "T11"),
        "ss_err_max_A": ("Max steady-state error", "A", 1, "T11"),
        "ocp_reaction_max_us": ("Max trip reaction", "µs", 1, "T12"),
        "speed_ripple_max_pct": ("Max speed ripple", "%", 1, "T13"), "pos_err_max_deg": ("Max position error", "°", 1, "T13"),
        "ripple_max_frac": ("Max current ripple", "× test current", 1, "T7"),
        "sample_err_max_A": ("Max sample error", "A", 1, "T7"),
        "enc_res_max_deg_e": ("Max encoder step", "° el", 1, "T8"),
        "psu_margin": ("PSU-limit margin", "× limit", 1, "T9: above this the PSU counts as limiting."),
    },
}


def field_list():
    """Every parameter with its default, type and display info, for the web form."""
    p = rs.Params()
    out = []
    for g in rs.GROUPS:
        obj = getattr(p, g)
        for f in fields(obj):
            v = getattr(obj, f.name)
            label, unit, scale, help_ = FIELD_INFO.get(g, {}).get(f.name, (f.name, "SI", 1, ""))
            typ = "bool" if isinstance(v, bool) else "int" if isinstance(v, int) else "float" if isinstance(v, float) else "str"
            out.append(dict(group=g, name=f.name, label=label, unit=unit, scale=scale, help=help_, type=typ,
                            default=v, placeholder=f"{g}.{f.name}" in rs.PLACEHOLDERS))
    return out


def params_from(data):
    """Nested dict (SI units) from the page -> rig_sim.Params, with type conversion and sanity checks."""
    p = rs.Params().update(data)
    errors = []
    pos = [("motor", "R_phase"), ("motor", "L_phase"), ("motor", "J"), ("motor", "kv_rpm_per_v"),
           ("inverter", "f_pwm"), ("supply", "R_source"), ("sensing", "R_shunt"), ("sensing", "csa_gain"),
           ("control", "current_bw_hz"), ("control", "vel_bw_hz"), ("sim", "dt_switching")]
    for g, n in pos:
        if not getattr(getattr(p, g), n) > 0:
            errors.append(f"{GROUP_TITLES[g]} → {FIELD_INFO[g][n][0]} must be greater than 0")
    if p.motor.pole_pairs < 1:
        errors.append("Pole pairs must be ≥ 1")
    if p.sim.dt_switching >= p.inverter.dead_time > 0:
        errors.append("Switching-model step must be smaller than the dead time")
    if p.control.vbus_lim_full <= p.control.vbus_lim_start:
        errors.append("'Limiter fully on at' must be above 'Limiter starts at'")
    for g, n in (("scen", "t9_vq_steps"), ("scen", "t11_iq_steps"), ("scen", "t13_vel_steps"), ("scen", "t13_pos_steps_deg")):
        try:
            rs.parse_list(getattr(p.scen, n))
        except ValueError:
            errors.append(f"Test settings → {FIELD_INFO[g][n][0]}: enter numbers separated by commas")
    if errors:
        raise ValueError("; ".join(errors))
    return p


def derived(p):
    """Quick numbers that update while the user types (no simulation needed).
    Returns rows (label, value text, status) with status 'ok', 'warn' or ''."""
    m, inv, s, c, sp, sc = p.motor, p.inverter, p.sensing, p.control, p.supply, p.scen
    R = m.R_phase + inv.R_on
    rows = []
    add = lambda lab, val, st="": rows.append((lab, val, st))
    add("Flux linkage ψ", f"{m.psi() * 1e3:.3f} mWb")
    add("Torque constant K_t", f"{m.kt() * 1e3:.1f} mN·m/A")
    add("Back-EMF constant (line-line)", f"{m.ke_ll() * 1e3:.2f} mV/(rad/s)")
    add("Electrical time constant L/R", f"{m.L_phase / R * 1e3:.3f} ms")
    add("No-load speed at the test voltage", f"{sc.test_V_psu / m.ke_ll():.0f} rad/s ({sc.test_V_psu * m.kv_rpm_per_v:.0f} rpm)")
    rng = s.i_range()
    add("Measurable current range", f"±{rng:.1f} A", "ok" if rng >= inv.I_max_board else "warn")
    add("Current LSB", f"{2 * rng / 2 ** s.adc_bits * 1e3:.2f} mA")
    thr = c.ocp_threshold_A if c.ocp_threshold_A > 0 else min(0.9 * rng, c.ocp_rig_max_A)
    add("Comparator trip level", f"{thr:.1f} A", "ok" if thr <= c.ocp_rig_max_A + 1e-9 else "warn")
    wc = 2 * math.pi * c.current_bw_hz
    add("Current PI: K_p / K_i", f"{m.L_phase * wc:.4f} V/A / {R * wc:.1f} V/(A·s)")
    loop_over = c.current_bw_hz > inv.f_pwm / 20
    add("Current bandwidth vs PWM", f"{c.current_bw_hz:.0f} Hz vs {inv.f_pwm / 1e3:.0f} kHz",
        "warn" if loop_over else "ok")
    wv = 2 * math.pi * c.vel_bw_hz
    add("Velocity PI: K_p / K_i", f"{m.J * wv / m.kt():.3f} A/(rad/s) / {m.J * wv / m.kt() * wv / 5:.2f} A/rad")
    add("Torque at the i_q limit", f"{m.kt() * c.iq_limit * 1e3:.0f} mN·m")
    dt_err = inv.dead_time * inv.f_pwm * sp.V_psu
    add("Dead-time voltage error", f"{dt_err:.3f} V")
    # T9 first-spin estimate at the procedure maximum
    vq = sc.t9_vq_max_procedure
    dte9 = inv.dead_time * inv.f_pwm * sc.t9_V_psu
    i_ph = max(vq - dte9, 0.0) / R
    i_psu = 1.5 * vq * i_ph / max(sc.t9_V_psu, 1e-6)
    add(f"T9 at V_q = {vq} V: phase / PSU current (estimate)", f"{i_ph:.1f} A / {i_psu:.2f} A",
        "ok" if i_psu < p.crit.psu_margin * sc.t9_I_limit and i_ph < inv.I_max_board else "warn")
    # T14 braking energy and the bus rise if it all went into the capacitors (no losses)
    J = m.J * sc.t14_load_inertia_mult
    E = 0.5 * J * sc.t14_speed ** 2
    C = sp.C_bus + sp.C_board
    v0 = sc.test_V_psu - sp.V_schottky
    v_end = math.sqrt(v0 ** 2 + 2 * E / C) if C > 0 else float("inf")
    add(f"T14 kinetic energy ({sc.t14_load_inertia_mult:g}× inertia)", f"{E:.2f} J")
    add("Bus voltage if all of it charged the capacitors", f"{v_end:.1f} V",
        "ok" if v_end < p.crit.vbus_max_V else "warn")
    add("Worst-case PWM current ripple", f"{sc.test_V_psu / (4 * m.L_phase * inv.f_pwm) * 2 / 3:.2f} A p-p")
    return rows


class Handler(BaseHTTPRequestHandler):
    results = {}            # batch id -> (params, [results], start time)

    def log_message(self, *a):  # keep the terminal quiet
        pass

    def _send(self, code, body, ctype="application/json"):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj, default=str))

    def do_GET(self):
        if self.path == "/layout.svg":
            self._send(200, layout_svg(), "image/svg+xml")
            return
        if self.path in ("/", "/index.html"):
            page = PAGE.replace("__FIELDS__", json.dumps(field_list())) \
                       .replace("__GROUPS__", json.dumps([[g, GROUP_TITLES[g]] for g in rs.GROUPS])) \
                       .replace("__SCEN__", json.dumps([[k, (f.__doc__ or "").strip().splitlines()[0]]
                                                         for k, f in rs.SCENARIOS.items()])) \
                       .replace("__TRACES__", json.dumps(list(rs.TRACES.items()))) \
                       .replace("__WIRES__", json.dumps(wire_map()))
            self._send(200, page, "text/html")
        else:
            self._send(404, "not found", "text/plain")

    def do_POST(self):
        try:
            n = int(self.headers.get("Content-Length", 0))
            req = json.loads(self.rfile.read(n) or b"{}")
            if self.path == "/derived":
                p = params_from(req.get("params", {}))
                self._json(200, {"rows": derived(p)})
            elif self.path == "/run":
                p = params_from(req.get("params", {}))
                batch = req["batch"]
                name = req["scenario"]
                if name not in rs.SCENARIOS:
                    raise ValueError(f"unknown scenario {name}")
                out = RUNS_DIR / batch
                out.mkdir(parents=True, exist_ok=True)
                if batch not in self.results:
                    self.results[batch] = (p, [], time.time())
                t0 = time.time()
                r = rs.SCENARIOS[name](p, out, bool(req.get("quick")))
                self.results[batch][1].append(r)
                img = base64.b64encode((out / r["fig"]).read_bytes()).decode() if r.get("fig") else None
                self._json(200, {"title": r["title"], "checks": r["checks"], "note": r.get("note", ""),
                                 "metrics": [[k, (f"{v:.4g}" if isinstance(v, float) else str(v))] for k, v in r["metrics"].items()],
                                 "img": img, "seconds": round(time.time() - t0, 1)})
            elif self.path == "/trace":
                p = params_from(req.get("params", {}))
                t0 = time.time()
                tr = rs.trace(p, req["trace"], bool(req.get("quick")))
                tr["seconds"] = round(time.time() - t0, 1)
                self._json(200, tr)
            elif self.path == "/report":
                batch = req["batch"]
                p, res, t0 = self.results[batch]
                out = RUNS_DIR / batch
                rs.write_report(p, res, out, time.time() - t0)
                (out / "params.json").write_text(json.dumps(asdict(p), indent=2), encoding="utf-8")
                md = (out / "rig_sim_report.md").read_text(encoding="utf-8")
                self._json(200, {"markdown": md, "folder": str(out)})
            else:
                self._send(404, "not found", "text/plain")
        except Exception as e:  # report every problem to the page instead of crashing the server
            self._json(400, {"error": str(e), "trace": traceback.format_exc(limit=3)})


PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Rig Simulator</title>
<style>
:root{--bg:#f6f7f9;--panel:#fff;--ink:#1d2127;--muted:#5f6772;--line:#dde1e6;--accent:#1f6f8b;--ok:#2e7d32;--bad:#c62828;--warn:#a86b00;--ph:#fff4d6}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){--bg:#15181c;--panel:#1d2126;--ink:#e6e8eb;--muted:#9aa3ad;--line:#333a42;--accent:#5fb7d6;--ok:#6cc58f;--bad:#ff7a70;--warn:#e0a83a;--ph:#3a3220}}
:root[data-theme="dark"]{--bg:#15181c;--panel:#1d2126;--ink:#e6e8eb;--muted:#9aa3ad;--line:#333a42;--accent:#5fb7d6;--ok:#6cc58f;--bad:#ff7a70;--warn:#e0a83a;--ph:#3a3220}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 system-ui,Segoe UI,Arial,sans-serif}
header{padding:12px 16px;background:var(--panel);border-bottom:1px solid var(--line);display:flex;flex-wrap:wrap;gap:10px;align-items:center;position:sticky;top:0;z-index:5}
h1{font-size:18px;margin:0 12px 0 0}button,.btn{font:inherit;padding:6px 12px;border-radius:6px;border:1px solid var(--line);background:var(--panel);color:var(--ink);cursor:pointer}
button.primary{background:var(--accent);color:#fff;border-color:var(--accent)}button:disabled{opacity:.5;cursor:default}
.scen label{margin-right:8px;white-space:nowrap}main{display:grid;grid-template-columns:minmax(330px,430px) 1fr;gap:14px;padding:14px}
@media (max-width:900px){main{grid-template-columns:1fr}}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:10px 12px;margin-bottom:12px}
details summary{cursor:pointer;font-weight:600;padding:4px 0}.row{display:grid;grid-template-columns:1fr 110px 74px;gap:6px;align-items:center;padding:3px 0;border-bottom:1px dashed var(--line)}
.row:last-child{border-bottom:none}.row label{font-size:13px}.row .u{font-size:12px;color:var(--muted)}
.row input,.row select{width:100%;padding:4px 6px;border:1px solid var(--line);border-radius:5px;background:var(--bg);color:var(--ink);font:inherit}
.row.ph{background:var(--ph);border-radius:4px}.row.changed label{font-weight:700}.help{font-size:11.5px;color:var(--muted);grid-column:1/-1;margin-top:-2px}
table{border-collapse:collapse;width:100%;font-size:13px}th,td{text-align:left;padding:4px 6px;border-bottom:1px solid var(--line);vertical-align:top}
.ok{color:var(--ok);font-weight:700}.bad{color:var(--bad);font-weight:700}.warn{color:var(--warn);font-weight:700}
.card img{max-width:100%;border:1px solid var(--line);border-radius:6px;background:#fff}.card h3{margin:2px 0 8px;font-size:16px}
#status{color:var(--muted)}#summary{font-weight:700}.err{color:var(--bad);white-space:pre-wrap}.note{color:var(--muted);font-size:13px;margin-top:6px}
.legend{font-size:12px;color:var(--muted)}
.tabs{display:flex;gap:6px;margin-bottom:10px}.tab.on{background:var(--accent);color:#fff;border-color:var(--accent)}
main.wide{grid-template-columns:1fr}main.wide>section:first-child{display:none}
.flowbar{display:flex;flex-wrap:wrap;gap:8px;align-items:center}.flowgrid{display:grid;grid-template-columns:1fr 270px;gap:12px}
@media (max-width:1100px){.flowgrid{grid-template-columns:1fr}}
#svgBox{overflow:auto;background:#fff}#svgBox svg{width:100%;height:auto;display:block}
#readout table td:last-child{text-align:right;font-variant-numeric:tabular-nums}#charts{width:100%;height:auto;cursor:crosshair}
.badge{display:inline-block;padding:1px 6px;border-radius:4px;font-size:12px;font-weight:700;margin:1px}
.b-ok{background:#e6f4ea;color:#1b5e20}.b-bad{background:#fde7e7;color:#b71c1c}.b-warn{background:#fff4d6;color:#7a4f00}
</style></head><body>
<header>
 <h1>iGL-FOC-1 rig simulator · 5010</h1>
 <span class="scen" id="scen"></span>
 <label><input type="checkbox" id="quick"> quick</label>
 <button class="primary" id="run">Run selected</button>
 <button id="reset">Reset defaults</button>
 <button id="save">Save parameters</button>
 <label class="btn">Load parameters<input type="file" id="load" accept=".json" hidden></label>
 <button id="dl" disabled>Download report</button>
 <button id="hideForm">Hide parameters</button>
 <span id="status"></span> <span id="summary"></span>
</header>
<main>
 <section><div class="legend">Highlighted rows = <b>placeholders</b>: replace them with measured / datasheet values. Bold label = changed from default.</div>
  <div id="form"></div></section>
 <section>
  <div class="tabs"><button class="tab on" id="tabSim">Simulate &amp; check</button><button class="tab" id="tabFlow">Wiring flow (animated)</button></div>
  <div id="paneSim">
   <div class="panel"><b>Derived values</b> <span class="legend">(update while you type)</span><div id="derived"></div></div>
   <div id="results"></div>
  </div>
  <div id="paneFlow" hidden>
   <div class="panel flowbar">
    <select id="trSel"></select>
    <label><input type="checkbox" id="trQuick" checked> quick</label>
    <button class="primary" id="trGo">Simulate trace</button>
    <button id="play" disabled>▶ Play</button>
    <label>Speed <select id="spd"></select></label>
    <label><input type="checkbox" id="loop" checked> loop</label>
    <input type="range" id="scrub" min="0" max="1000" value="0" style="width:240px" disabled>
    <span id="tlabel"></span> <span id="trStatus" class="legend">Uses the parameters on the left (Hide parameters for a bigger view).</span>
   </div>
   <div class="flowgrid">
    <div class="panel" id="svgBox">Loading the layout…</div>
    <div class="panel" id="readout"><b>Live values</b><div class="legend">Simulate a trace, then press Play.</div></div>
   </div>
   <div class="panel"><canvas id="charts" width="1200" height="360"></canvas>
    <div class="legend">Click the charts to jump. Moving dots = current (direction and size); PWM wire brightness = duty or FET state;
    sense-wire colour = voltage; red = fault / trip. SPI and CAN activity is illustrative (timing not simulated); NTC temperatures are not simulated.</div></div>
  </div>
 </section>
</main>
<script>
const FIELDS = __FIELDS__, GROUPS = __GROUPS__, SCEN = __SCEN__, TRACES = __TRACES__, WIRES = __WIRES__;
const $ = s => document.querySelector(s);
const fmt = v => { if (typeof v !== 'number') return v; const r = Number(v.toPrecision(10)); return String(r); };
let lastMd = null, running = false;

function buildForm(){
  const f = $('#form'); f.innerHTML = '';
  for (const [g, title] of GROUPS){
    const d = document.createElement('details'); d.className = 'panel'; d.open = ['motor','supply','sensing','scen'].includes(g);
    d.innerHTML = `<summary>${title}</summary>`;
    for (const x of FIELDS.filter(x => x.group === g)){
      const row = document.createElement('div'); row.className = 'row' + (x.placeholder ? ' ph' : '');
      const id = `${g}.${x.name}`; let input;
      if (x.type === 'bool') input = `<select id="${id}"><option value="true">on</option><option value="false">off</option></select>`;
      else if (x.group === 'sensing' && x.name === 'csa_gain') input = `<select id="${id}">${[5,10,20,40].map(v=>`<option>${v}</option>`).join('')}</select>`;
      else input = `<input id="${id}" ${x.type==='str'?'type="text"':'type="number" step="any"'}>`;
      row.innerHTML = `<label for="${id}" title="${x.name}">${x.label}</label>${input}<span class="u">${x.unit}</span>` + (x.help ? `<div class="help">${x.help}</div>` : '');
      d.appendChild(row);
    }
    f.appendChild(d);
  }
  f.addEventListener('input', onChange); f.addEventListener('change', onChange);
}
function el(x){ return document.getElementById(`${x.group}.${x.name}`); }
function setValues(si){            // si = nested dict in SI units (missing values keep defaults)
  for (const x of FIELDS){
    let v = (si[x.group] && x.name in si[x.group]) ? si[x.group][x.name] : x.default;
    if (x.type === 'bool') el(x).value = v ? 'true' : 'false';
    else if (x.type === 'str') el(x).value = v;
    else el(x).value = fmt(v * x.scale);
  }
  markChanged(); onChange();
}
function getParams(){              // form -> nested dict in SI units (what rig_sim.py expects)
  const p = {};
  for (const x of FIELDS){
    p[x.group] = p[x.group] || {};
    const raw = el(x).value;
    if (x.type === 'bool') p[x.group][x.name] = raw === 'true';
    else if (x.type === 'str') p[x.group][x.name] = raw;
    else { const v = parseFloat(raw); p[x.group][x.name] = isNaN(v) ? raw : (x.type === 'int' ? Math.round(v / x.scale) : v / x.scale); }
  }
  return p;
}
function markChanged(){
  for (const x of FIELDS){
    const raw = el(x).value; let same;
    if (x.type === 'bool') same = (raw === 'true') === x.default;
    else if (x.type === 'str') same = raw === x.default;
    else same = Math.abs(parseFloat(raw) / x.scale - x.default) <= 1e-12 * Math.max(1, Math.abs(x.default));
    el(x).closest('.row').classList.toggle('changed', !same);
  }
}
let tmr = null;
function onChange(){ markChanged(); clearTimeout(tmr); tmr = setTimeout(updateDerived, 250); }
async function post(url, body){
  const r = await fetch(url, {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)});
  const j = await r.json(); if (!r.ok) throw new Error(j.error || 'server error'); return j;
}
async function updateDerived(){
  try{
    const j = await post('/derived', {params: getParams()});
    $('#derived').innerHTML = '<table>' + j.rows.map(([l,v,s]) => `<tr><td>${l}</td><td class="${s}">${v}${s==='warn'?' ⚠':''}</td></tr>`).join('') + '</table>';
  } catch(e){ $('#derived').innerHTML = `<div class="err">${e.message}</div>`; }
}
function card(r){
  const c = document.createElement('div'); c.className = 'panel card';
  const pass = r.checks.filter(x => x[3]).length;
  c.innerHTML = `<h3>${r.title} <span class="${pass===r.checks.length?'ok':'bad'}">${pass}/${r.checks.length} pass</span> <span class="legend">${r.seconds} s</span></h3>
   <table><tr><th>Check</th><th>Simulated</th><th>Criterion</th><th>Result</th></tr>${r.checks.map(x=>`<tr><td>${x[0]}</td><td>${x[1]}</td><td>${x[2]}</td><td class="${x[3]?'ok':'bad'}">${x[3]?'PASS':'FAIL'}</td></tr>`).join('')}</table>
   ${r.note?`<div class="note">${r.note}</div>`:''}
   ${r.img?`<p><img src="data:image/png;base64,${r.img}" alt="${r.title} plot"></p>`:''}
   <details><summary>All numbers</summary><table>${r.metrics.map(([k,v])=>`<tr><td>${k}</td><td>${v}</td></tr>`).join('')}</table></details>`;
  return c;
}
async function run(){
  if (running) return;
  const sel = SCEN.map(s=>s[0]).filter(k => document.getElementById('sc-'+k).checked);
  if (!sel.length){ $('#status').textContent = 'Select at least one scenario.'; return; }
  running = true; $('#run').disabled = true; $('#dl').disabled = true; $('#results').innerHTML = ''; $('#summary').textContent = '';
  const batch = new Date().toISOString().replace(/[-:]/g,'').replace('T','-').slice(0,15);
  const params = getParams(); let pass = 0, all = 0;
  try{
    for (let i = 0; i < sel.length; i++){
      $('#status').textContent = `Running ${sel[i]} (${i+1}/${sel.length})…`;
      const r = await post('/run', {batch, params, scenario: sel[i], quick: $('#quick').checked});
      pass += r.checks.filter(x=>x[3]).length; all += r.checks.length;
      $('#results').appendChild(card(r));
      $('#summary').innerHTML = `<span class="${pass===all?'ok':'bad'}">${pass}/${all} checks pass</span>`;
    }
    const rep = await post('/report', {batch});
    lastMd = rep.markdown; $('#dl').disabled = false; $('#status').textContent = `Done. Saved in ${rep.folder}`;
  } catch(e){
    const d = document.createElement('div'); d.className = 'panel err'; d.textContent = 'Error: ' + e.message; $('#results').appendChild(d);
    $('#status').textContent = 'Stopped on an error.';
  }
  running = false; $('#run').disabled = false;
}
function download(name, text, type){
  const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([text], {type})); a.download = name; a.click();
  setTimeout(()=>URL.revokeObjectURL(a.href), 1000);
}
$('#scen').innerHTML = SCEN.map(([k,d]) => `<label title="${d}"><input type="checkbox" id="sc-${k}" checked> ${k}</label>`).join('');
buildForm(); setValues({});

// ================= Wiring flow (animated) =================
// One trace = arrays sampled in time (tr.t). Each animation frame picks the sample at the
// current simulated time and restyles every wire of the layout drawing from it.
let tr = null, tSim = 0, playing = false, lastTs = 0, layoutLoaded = false;
const offs = {};                       // stroke-dashoffset per wire (moving dots)
const SPEEDS_AVG = [[0.001,'×0.001 (1 ms per s)'],[0.01,'×0.01'],[0.05,'×0.05'],[0.1,'×0.1'],[0.25,'×0.25'],[1,'×1 real time']];
const SPEEDS_PWM = [[1e-6,'×0.000001 (1 µs per s)'],[3e-6,'×0.000003'],[1e-5,'×0.00001'],[3e-5,'×0.00003'],[1e-4,'×0.0001']];
$('#trSel').innerHTML = TRACES.map(([k,d]) => `<option value="${k}">${d}</option>`).join('');
function setSpeeds(kind){
  const L = kind === 'pwm' ? SPEEDS_PWM : SPEEDS_AVG;
  $('#spd').innerHTML = L.map(([v,l]) => `<option value="${v}">${l}</option>`).join('');
  $('#spd').value = String(kind === 'pwm' ? 1e-5 : 0.1);
}
setSpeeds('avg');
function showTab(flow){
  $('#paneSim').hidden = flow; $('#paneFlow').hidden = !flow;
  $('#tabSim').classList.toggle('on', !flow); $('#tabFlow').classList.toggle('on', flow);
  if (flow && !layoutLoaded){ loadLayout(); }
}
$('#tabSim').onclick = () => showTab(false);
$('#tabFlow').onclick = () => showTab(true);
$('#hideForm').onclick = () => { const m = document.querySelector('main'); m.classList.toggle('wide');
  $('#hideForm').textContent = m.classList.contains('wide') ? 'Show parameters' : 'Hide parameters'; };
async function loadLayout(){
  const r = await fetch('/layout.svg'); $('#svgBox').innerHTML = await r.text(); layoutLoaded = true;
  for (const w of WIRES){ const el = document.getElementById('w-'+w.id); if (el){ el.dataset.base = el.getAttribute('stroke-width'); } }
}
const fmtT = t => t < 1e-3 ? (t*1e6).toFixed(2)+' µs' : t < 1 ? (t*1e3).toFixed(2)+' ms' : t.toFixed(3)+' s';
function idxAt(t){ const T = tr.t; let lo = 0, hi = T.length - 1; while (lo < hi){ const m = (lo + hi + 1) >> 1; if (T[m] <= t) lo = m; else hi = m - 1; } return lo; }
async function simulateTrace(){
  $('#trGo').disabled = true; playing = false; $('#play').textContent = '▶ Play';
  $('#trStatus').textContent = 'Simulating…';
  try{
    if (!layoutLoaded) await loadLayout();
    tr = await post('/trace', {params: getParams(), trace: $('#trSel').value, quick: $('#trQuick').checked});
    // per-trace scales for wire widths and charts
    const absmax = k => tr[k] ? Math.max(1e-9, ...tr[k].map(Math.abs)) : 1e-9;
    tr.imax = Math.max(absmax('ia'), absmax('ib'), absmax('ic'));
    if (tr.kind === 'pwm'){            // bus current from the leg states (dead time: diode decides)
      tr.ibus = tr.t.map((_, i) => ['sa','sb','sc'].reduce((s, k, j) => { const st = tr[k][i], c = tr[['ia','ib','ic'][j]][i];
        return s + (st === 1 ? c : (st === 0.5 && c < 0 ? c : 0)); }, 0));
      const avg = tr.ibus.reduce((a, b) => a + b, 0) / tr.ibus.length; tr.ipsu = tr.t.map(() => Math.max(avg, 0));
    } else {
      tr.ibus = tr.iinv.map(x => x + tr.meta.I_quiescent);
    }
    tr.pmax = Math.max(absmax('ibus'), absmax('ipsu'), 0.05);
    setSpeeds(tr.kind); tSim = 0; $('#scrub').disabled = false; $('#play').disabled = false;
    $('#trStatus').textContent = `${tr.title} · ${tr.t.length} frames · simulated in ${tr.seconds} s`;
    playing = true; $('#play').textContent = '❚❚ Pause'; lastTs = 0; drawFrame();
  } catch(e){ $('#trStatus').textContent = 'Error: ' + e.message; }
  $('#trGo').disabled = false;
}
$('#trGo').onclick = simulateTrace;
$('#play').onclick = () => { playing = !playing; $('#play').textContent = playing ? '❚❚ Pause' : '▶ Play';
  if (playing && tSim >= tr.t[tr.t.length-1]) tSim = 0; lastTs = 0; };
$('#scrub').oninput = () => { if (!tr) return; tSim = $('#scrub').value / 1000 * tr.t[tr.t.length-1]; drawFrame(true); };
$('#charts').onclick = e => { if (!tr) return; const r = e.target.getBoundingClientRect();
  const x = (e.clientX - r.left) / r.width; tSim = Math.min(Math.max((x * 1200 - 60) / (1200 - 80), 0), 1) * tr.t[tr.t.length-1]; drawFrame(true); };

function styleWire(id, o){
  const el = document.getElementById('w-'+id); if (!el) return;
  el.style.stroke = o.colour || ''; el.style.opacity = o.opacity == null ? 1 : o.opacity;
  el.style.strokeWidth = o.width || el.dataset.base; el.style.strokeDasharray = o.dash || '';
  if (o.flow != null){ offs[id] = (offs[id] || 0) - o.flow; el.style.strokeDashoffset = offs[id]; }
  else el.style.strokeDashoffset = 0;
  el.style.filter = o.glow ? 'drop-shadow(0 0 3px ' + (o.colour || '#ff0') + ')' : '';
}
function flowStyle(i, scale, dtReal, colour){            // moving dots along the wire, a -> b for positive current
  const a = Math.abs(i), rel = Math.min(a / scale, 1);
  return {colour, width: 2 + 7 * rel, dash: a < 0.02 * scale ? '' : '3 11', opacity: a < 0.02 * scale ? 0.35 : 1,
          flow: Math.sign(i) * (20 + 220 * rel) * dtReal};
}
const PH = {PH_A:'ia', PH_B:'ib', PH_C:'ic'};
function flowStep(dtReal){
  const k = idxAt(tSim), v = key => tr[key] ? tr[key][k] : 0, m = tr.meta, pwm = tr.kind === 'pwm';
  const mode = pwm ? 'current' : m.modes[v('mode')];
  const fault = !pwm && v('uvlo') > 0.5, trip = !pwm && v('trip') > 0.5;
  const enc = (tSim * m.f_pwm) % 1 < 0.35, can = (tSim * 1000) % 1 < 0.13, drvspi = !pwm && tSim < 0.002;
  const duty = {A: pwm ? null : v('da'), B: pwm ? null : v('db'), C: pwm ? null : v('dc')};
  const st = {A: pwm ? v('sa') : null, B: pwm ? v('sb') : null, C: pwm ? v('sc') : null};
  for (const w of WIRES){
    const n = w.net, c = w.colour;
    if (w.id === 'P01' || w.id === 'P02' || w.id === 'P03') styleWire(w.id, flowStyle(v('ipsu'), tr.pmax, dtReal, '#d62728'));
    else if (w.id === 'P05') styleWire(w.id, flowStyle(-v('ipsu'), tr.pmax, dtReal, '#222'));
    else if (w.id === 'P04') styleWire(w.id, flowStyle(tr.ibus[k], tr.pmax, dtReal, '#d62728'));
    else if (w.id === 'P06') styleWire(w.id, flowStyle(-tr.ibus[k], tr.pmax, dtReal, '#222'));
    else if (PH[n]) styleWire(w.id, flowStyle(v(PH[n]), tr.imax, dtReal, c));
    else if (/^PWM_[ABC][HL]$/.test(n)){
      const ph = n[4], hi = n[5] === 'H';
      if (pwm){ const s = st[ph]; const on = s === 0.5 ? false : (hi ? s === 1 : s === 0);
        styleWire(w.id, {colour: s === 0.5 ? '#999' : c, opacity: on ? 1 : 0.15, width: on ? 4 : 2, glow: on}); }
      else { const d = hi ? duty[ph] : 1 - duty[ph]; const off = trip || fault || mode === 'off';
        styleWire(w.id, {colour: c, opacity: off ? 0.12 : 0.15 + 0.85 * d, width: 2 + 3 * (off ? 0 : d), dash: off ? '4 4' : ''}); }
    }
    else if (n === 'DRV_EN') styleWire(w.id, {colour: mode !== 'off' ? c : '#999', opacity: mode !== 'off' ? 1 : 0.3, glow: mode !== 'off'});
    else if (n === 'nFAULT_BKIN') styleWire(w.id, {colour: fault ? '#e00' : c, width: fault ? 5 : null, glow: fault, opacity: 1});
    else if (/^ISENSE_[ABC]$/.test(n)){
      const i = v(PH['PH_' + n.slice(-1)]), volts = m.v_ref / 2 + m.csa_v_per_a * i, r = Math.min(Math.max(volts / m.v_ref, 0), 1);
      styleWire(w.id, {colour: `hsl(${120 - 120 * Math.abs(2 * r - 1)},70%,40%)`, width: 3});
    }
    else if (n === 'VBUS_SNS') styleWire(w.id, {colour: `hsl(${140 - 140 * Math.min(v('vbus') / 31, 1)},70%,40%)`, width: 3});
    else if (n === 'DBG_DAC1') styleWire(w.id, {colour: c, opacity: 0.3 + 0.7 * Math.min(Math.abs(v('iq')) / tr.imax, 1)});
    else if (/^ENC_/.test(n)) styleWire(w.id, {colour: c, opacity: enc ? 1 : 0.25, glow: enc});
    else if (/^CAN/.test(n)) styleWire(w.id, {colour: c, opacity: can ? 1 : 0.25, glow: can});
    else if (/^DRV_(SCK|SDI|SDO|nCS)$/.test(n)) styleWire(w.id, {colour: c, opacity: drvspi ? 1 : 0.3, glow: drvspi});
    else styleWire(w.id, {colour: c, opacity: 0.85});
  }
  const rot = document.getElementById('rotor');
  if (rot){ const ang = pwm ? 0 : v('pos') * 180 / Math.PI; rot.setAttribute('transform', rot.getAttribute('transform').replace(/rotate\(([-\d.e]+)/, `rotate(${ang.toFixed(2)}`)); }
  // live values
  const rows = [['Time', fmtT(tSim)], ['Firmware mode', mode]];
  if (pwm) rows.push(['Leg states A/B/C', ['A','B','C'].map(p => st[p] === 0.5 ? 'dead' : st[p] ? 'HIGH' : 'low').join(' / ')],
                     ['V_bus', v('vbus').toFixed(2) + ' V']);
  else rows.push(['Duty A/B/C', ['da','db','dc'].map(x => (v(x) * 100).toFixed(1)).join(' / ') + ' %'],
                 ['V_bus', v('vbus').toFixed(2) + ' V'], ['PSU current', v('ipsu').toFixed(2) + ' A'],
                 ['Bus → bridge current', tr.ibus[k].toFixed(2) + ' A'], ['TVS current', v('itvs').toFixed(2) + ' A'],
                 ['i_q / ref', v('iq').toFixed(2) + ' / ' + v('iq_ref').toFixed(2) + ' A'], ['i_d', v('id').toFixed(2) + ' A'],
                 ['Speed / ref', v('w').toFixed(1) + ' / ' + v('vel_ref').toFixed(1) + ' rad/s'],
                 ['Position', (v('pos') * 180 / Math.PI).toFixed(1) + '°']);
  rows.push(['i_a / i_b / i_c', ['ia','ib','ic'].map(x => v(x).toFixed(2)).join(' / ') + ' A']);
  const badges = (mode !== 'off' ? '<span class="badge b-ok">ENABLE</span>' : '<span class="badge b-warn">driver off</span>') +
    (trip ? '<span class="badge b-bad">OCP TRIP: gates off</span>' : '') + (fault ? '<span class="badge b-bad">UVLO: nFAULT low</span>' : '') +
    (!pwm && v('itvs') > 0.01 ? '<span class="badge b-bad">TVS conducting</span>' : '') +
    (!pwm && tr.ibus[k] < -0.05 ? '<span class="badge b-warn">REGEN into capacitors</span>' : '') +
    (pwm && ['A','B','C'].some(p => st[p] === 0.5) ? '<span class="badge b-warn">dead time</span>' : '');
  $('#readout').innerHTML = `<b>Live values</b><div>${badges}</div><table>${rows.map(([a,b]) => `<tr><td>${a}</td><td>${b}</td></tr>`).join('')}</table>`;
  $('#tlabel').textContent = fmtT(tSim) + ' / ' + fmtT(tr.t[tr.t.length-1]);
  $('#scrub').value = Math.round(tSim / tr.t[tr.t.length-1] * 1000);
  drawCharts(k);
}
function drawCharts(k){
  const cv = $('#charts'), g = cv.getContext('2d'), W = cv.width, H = cv.height, x0 = 60, x1 = W - 20, T = tr.t, tEnd = T[T.length-1];
  const dark = matchMedia('(prefers-color-scheme: dark)').matches && document.documentElement.dataset.theme !== 'light';
  g.clearRect(0, 0, W, H); g.font = '12px system-ui'; g.lineWidth = 1.3;
  const pwm = tr.kind === 'pwm';
  const panels = pwm
    ? [['Phase currents (A)', [['ia','#1f77b4'],['ib','#ff7f0e'],['ic','#2ca02c']]], ['Leg states A/B/C (offset)', [['sa','#1f77b4',0],['sb','#ff7f0e',1.3],['sc','#2ca02c',2.6]]], ['Bus → bridge current (A)', [['ibus','#d62728']]]]
    : [['Phase currents (A)', [['ia','#1f77b4'],['ib','#ff7f0e'],['ic','#2ca02c']]], ['V_bus (V) · PSU and bus current (A, dashed)', [['vbus','#d62728'],['ipsu','#555',null,true],['ibus','#9467bd',null,true]]],
       ['Speed (rad/s) and reference', [['w','#1f77b4'],['vel_ref','#888',null,true]]]];
  const ph = (H - 10) / panels.length;
  panels.forEach(([title, series], pi) => {
    const top = 5 + pi * ph, bot = top + ph - 18;
    let lo = Infinity, hi = -Infinity;
    for (const [key, , off, dashed] of series){ if (dashed && key !== 'vel_ref') continue; const a = tr[key]; if (!a) continue;
      for (const x of a){ const y = x + (off || 0); if (y < lo) lo = y; if (y > hi) hi = y; } }
    if (hi - lo < 1e-6){ hi += 0.5; lo -= 0.5; } const pad = (hi - lo) * 0.08; lo -= pad; hi += pad;
    g.strokeStyle = dark ? '#444' : '#ddd'; g.strokeRect(x0, top, x1 - x0, bot - top);
    g.fillStyle = dark ? '#ccc' : '#333'; g.fillText(title, x0 + 4, top + 13);
    g.fillText(hi.toPrecision(3), 4, top + 10); g.fillText(lo.toPrecision(3), 4, bot);
    for (const [key, col, off, dashed] of series){
      const a = tr[key]; if (!a) continue; let s_lo = lo, s_hi = hi;
      if (dashed && key !== 'vel_ref'){ s_lo = Math.min(...a, 0); s_hi = Math.max(...a, 0.01); }
      g.strokeStyle = col; g.setLineDash(dashed ? [5, 4] : []); g.beginPath();
      const step = Math.max(1, Math.floor(a.length / 1500));
      for (let i = 0; i < a.length; i += step){ const x = x0 + (T[i] / tEnd) * (x1 - x0), y = bot - ((a[i] + (off || 0)) - s_lo) / (s_hi - s_lo) * (bot - top);
        if (i === 0) g.moveTo(x, y); else g.lineTo(x, y); }
      g.stroke(); g.setLineDash([]);
    }
  });
  const xp = x0 + (T[k] / tEnd) * (x1 - x0); g.strokeStyle = '#e00'; g.lineWidth = 2; g.beginPath(); g.moveTo(xp, 2); g.lineTo(xp, H - 4); g.stroke();
}
function drawFrame(once){
  if (!tr) return;
  const now = performance.now(); const dtReal = lastTs ? Math.min((now - lastTs) / 1000, 0.1) : 0; lastTs = now;
  const tEnd = tr.t[tr.t.length-1];
  if (playing && !once){ tSim += dtReal * parseFloat($('#spd').value);
    if (tSim > tEnd){ if ($('#loop').checked) tSim = 0; else { tSim = tEnd; playing = false; $('#play').textContent = '▶ Play'; } } }
  flowStep(playing && !once ? dtReal : 0);
  if (playing && !once) requestAnimationFrame(() => drawFrame());
}
setInterval(() => { if (playing && tr && !document.hidden && !window.__raf){ window.__raf = true; requestAnimationFrame(() => { window.__raf = false; drawFrame(); }); } }, 250);

$('#run').onclick = run;
$('#reset').onclick = () => setValues({});
$('#save').onclick = () => download('rig_params.json', JSON.stringify(getParams(), null, 2), 'application/json');
$('#dl').onclick = () => lastMd && download('rig_sim_report.md', lastMd, 'text/markdown');
$('#load').onchange = async e => { const f = e.target.files[0]; if (!f) return;
  try { setValues(JSON.parse(await f.text())); $('#status').textContent = 'Loaded ' + f.name; }
  catch(err){ $('#status').textContent = 'Could not read ' + f.name + ': ' + err.message; } e.target.value = ''; };
</script></body></html>"""


def main():
    ap = argparse.ArgumentParser(description="Browser UI for rig_sim.py")
    ap.add_argument("--port", type=int, default=8050)
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    srv = HTTPServer(("127.0.0.1", a.port), Handler)    # localhost only: not reachable from the network
    url = f"http://127.0.0.1:{a.port}/"
    print(f"Rig simulator UI running at {url}  (Ctrl+C to stop)")
    if not a.no_browser:
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("stopped")


if __name__ == "__main__":
    main()
