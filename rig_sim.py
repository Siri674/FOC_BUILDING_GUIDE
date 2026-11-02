#!/usr/bin/env python3
# ======================================================================================
#  rig_sim.py  -  Offline simulation of the iGL-FOC-1 no-PCB rig driving a 5010 motor
# ======================================================================================
#
#  WHAT THIS IS
#  ------------
#  A self-contained Python simulation of the rig described in No_PCB_Rig_Bringup_Procedure.md:
#
#      bench PSU -> fuse -> Schottky D1 -> bus capacitors (C3, C4) + TVS (D2)
#        -> BOOSTXL-DRV8323RS 3-phase bridge -> 5010 motor (7 pole pairs)
#      NUCLEO-G474RE firmware: 40 kHz current loop (FOC), velocity loop, position loop,
#        hardware over-current comparators (COMP1-3 -> TIM1 break), bus-voltage limiter
#
#  It lets the team check gains, currents, trip times and bus voltages BEFORE spinning the
#  real motor, and re-check them after the real motor has been measured (test T10).
#
#  HOW TO RUN  (Python 3.9+, needs numpy and matplotlib:  pip install numpy matplotlib)
#  ----------
#      python rig_sim.py                         run every scenario (about 1 minute)
#      python rig_sim.py --scenario T11 T14      run only some scenarios
#      python rig_sim.py --quick                 shorter runs (for a fast check)
#      python rig_sim.py --list                  list the scenarios
#      python rig_sim.py --write-params my.json  write all parameters to a JSON file
#      python rig_sim.py --params my.json        run with your edited parameters
#      python rig_sim_ui.py                      the same, from a browser form (every parameter,
#                                                live derived values, plots in the page)
#
#  PARAMETER GROUPS (section 1): motor, inverter, supply, sensing, control, sim,
#  scen (what each test commands: voltages, steps, speeds) and crit (pass/fail limits).
#  JSON files from --write-params, the UI's "Save parameters" and every UI run folder
#  (rig_sim_out/ui_runs/<time>/params.json) all use the same format.
#
#  Results go to ./rig_sim_out/ :  one PNG plot per scenario and rig_sim_report.md
#  (all numbers, every PASS/FAIL against the pass criteria of the bring-up procedure).
#
#  SCENARIOS (named after the tests in No_PCB_Rig_Bringup_Procedure.md)
#  ---------
#      T7   switching-level ripple: real 40 kHz PWM with 200 ns dead time, current ripple,
#           and proof that sampling at the PWM centre gives the average current
#      T8   resolution: current range / LSB, encoder and speed resolution (no simulation)
#      T9   first spin, open loop (voltage mode), PSU 12 V with a 1 A limit
#      T11  current-loop steps on a locked rotor (rise time, overshoot, I_d coupling)
#      T12  hardware over-current trip (normal test + a worst-case runaway fault)
#      T13  velocity steps and position steps on a free shaft
#      T14  regeneration: braking from 100 rad/s with and without load inertia / limiter
#
#  HOW TO USE YOUR MEASURED MOTOR DATA
#  -----------------------------------
#  1. python rig_sim.py --write-params my_motor.json
#  2. edit my_motor.json: R_phase, L_phase, kv_rpm_per_v, J ... from test T10,
#     R_shunt and csa_gain from the BOOSTXL schematic (TI SLVC690)
#  3. python rig_sim.py --params my_motor.json
#  Every value that is still a placeholder is listed in the report under "Parameters".
#
#  WHAT IS MODELLED (and what is NOT)
#  ----------------------------------
#  Modelled:  surface-PM motor (L_d = L_q) in phase quantities, sinusoidal back-EMF,
#             cogging torque, viscous + Coulomb friction, locked-rotor option,
#             inverter as an averaged model (fast) or a real switching model with dead time,
#             FET body diodes when the gates are off, bus capacitance, PSU with current
#             limit behind the Schottky diode (blocks reverse current), TVS clamp,
#             12-bit ADC with noise, 14-bit encoder, one-PWM-period control delay,
#             the firmware control structure from §6 of the procedure.
#  NOT modelled: FET switching losses and ringing, DRV8323 internal V_DS protection,
#             magnetic saturation, temperature rise, CAN, the exact ISR execution time.
#             Use the LTspice netlist (rig_power_stage.cir) for switching-edge details.
#
#  CONVENTIONS (used everywhere below)
#  -----------
#  * Angles in radians. theta_m = mechanical rotor angle, theta_e = pole_pairs * theta_m.
#  * Amplitude-invariant Clarke/Park: a phase current of amplitude I gives |i_dq| = I.
#    Torque = 1.5 * pole_pairs * psi * i_q   (psi = magnet flux linkage, phase peak).
#  * Phase a back-EMF:  e_a = -omega_e * psi * sin(theta_e)   (b, c shifted by -/+120 deg),
#    so in dq coordinates e_d = 0 and e_q = omega_e * psi.
#  * Positive phase current flows out of the inverter leg into the motor.
# ======================================================================================

import argparse
import dataclasses
import json
import math
import random
import sys
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")          # write PNG files, no window needed
import matplotlib.pyplot as plt

SQRT3 = math.sqrt(3.0)
TWO_PI = 2.0 * math.pi


# ======================================================================================
# 1. PARAMETERS
#    Every number the simulation uses lives here. "PLACEHOLDER" in a comment means:
#    replace it with a measured or datasheet value when you have it.
# ======================================================================================
@dataclass
class MotorParams:
    """5010 outrunner (12 slots, 14 magnets). Values are typical for ~280 KV."""
    pole_pairs: int = 7                 # 14 magnets / 2  (confirmed in test T9)
    kv_rpm_per_v: float = 280.0         # PLACEHOLDER: purchase spec; measure Kt in the torque test
    R_phase: float = 0.10               # ohm, phase-to-neutral. PLACEHOLDER: test T10 (line-line / 2)
    L_phase: float = 40e-6              # H, phase (L_d = L_q assumed). PLACEHOLDER: test T10
    J: float = 5e-5                     # kg m^2, rotor inertia. PLACEHOLDER: ~0.1 kg outer rotor at r = 25 mm
    B_visc: float = 1e-5                # N m s/rad, viscous friction (bearings + air)
    T_coulomb: float = 0.004            # N m, dry friction
    T_cog: float = 0.002                # N m, cogging torque amplitude
    cog_per_rev: int = 84               # cogging periods per mechanical turn = LCM(12 slots, 14 poles)

    # ---- values derived from KV (do not edit; they follow kv_rpm_per_v) ----
    def ke_ll(self):
        """Line-to-line peak back-EMF constant, V per (rad/s mechanical). KV is rpm per volt."""
        return 60.0 / (TWO_PI * self.kv_rpm_per_v)

    def psi(self):
        """Magnet flux linkage seen by one phase, peak, in Wb (electrical)."""
        return self.ke_ll() / SQRT3 / self.pole_pairs

    def kt(self):
        """Torque constant in N m per A of i_q (amplitude-invariant). Equals 8.27 / KV."""
        return 1.5 * self.pole_pairs * self.psi()


@dataclass
class InverterParams:
    """BOOSTXL-DRV8323RS bridge driven by TIM1."""
    f_pwm: float = 40e3                 # Hz, centre-aligned PWM (ARR = 2125 at 170 MHz)
    dead_time: float = 200e-9           # s, TIM1 dead time (DTG = 34)
    R_on: float = 0.002                 # ohm, FET on-resistance added to the phase resistance
    v_diode: float = 0.8                # V, FET body-diode drop when the gates are off
    I_max_board: float = 15.0           # A, BOOSTXL-DRV8323RS rating (TI user guide)
    uvlo_v: float = 6.0                 # V, below this the BOOSTXL/DRV8323 switches the gates off
    uvlo_hyst: float = 0.5              # V, gates come back above uvlo_v + uvlo_hyst


@dataclass
class SupplyParams:
    """Bench PSU and the regen kit on the perfboard (D1, C3, C4, D2)."""
    V_psu: float = 24.0                 # V, PSU set voltage (scenarios override it)
    I_limit: float = 3.0                # A, PSU current limit (scenarios override it)
    R_source: float = 0.05              # ohm, PSU output + 14 AWG harness + fuse
    V_schottky: float = 0.45            # V, MBR2045CT forward drop at a few amps
    C_bus: float = 4400e-6              # F, C3 + C4 (2 x 2200 uF). Set 0 to simulate "no regen kit"
    C_board: float = 100e-6             # F, bulk capacitance on the BOOSTXL itself. PLACEHOLDER (SLVC690)
    V_tvs_breakdown: float = 31.1       # V, SMCJ28A minimum breakdown voltage
    R_tvs: float = 0.43                 # ohm, SMCJ28A dynamic resistance: (45.4 V - 31.1 V) / 33 A
    I_quiescent: float = 0.03           # A, BOOSTXL idle current (measure it in procedure 5.6)


@dataclass
class SensingParams:
    """Current sensing (DRV8323 CSAs), ADC, bus-voltage sense and encoder."""
    R_shunt: float = 0.007              # ohm. PLACEHOLDER: read the real value from TI SLVC690
    csa_gain: float = 10.0              # V/V, DRV8323 CSA gain (5/10/20/40). Reset default is 20, but the
                                        # procedure (T5) says: pick the highest gain whose range is > 15 A.
                                        # With the placeholder 7 mOhm shunt that is 10 V/V (+-23.6 A).
    v_ref: float = 3.3                  # V, ADC reference = CSA reference (mid-scale = v_ref / 2)
    adc_bits: int = 12
    adc_noise_lsb: float = 2.0          # LSB rms noise on each current sample
    enc_bits: int = 14                  # AS5047P: 16384 counts per turn
    enc_offset_error_deg: float = 0.0   # electrical degrees of calibration error (test what-if)
    vbus_noise_rel: float = 0.003       # relative noise of the bus-voltage measurement

    def i_range(self):
        """Largest current the CSA + ADC can measure in either direction, in A."""
        return (self.v_ref / 2.0) / (self.csa_gain * self.R_shunt)


@dataclass
class ControlParams:
    """Firmware control loops (they mirror the CubeMX/firmware plan in the procedure)."""
    current_bw_hz: float = 1000.0       # current-loop bandwidth -> Kp = L*wc, Ki = R*wc
    decoupling: bool = True             # feed-forward of back-EMF and cross-coupling terms
    v_limit_factor: float = 0.95        # fraction of the SVPWM linear limit (V_bus / sqrt 3)
    vel_divider: int = 8                # velocity loop runs every 8th current-loop ISR (5 kHz)
    vel_filter_tau: float = 1e-3        # s, low-pass on the encoder speed estimate
    vel_bw_hz: float = 30.0             # velocity-loop bandwidth
    pos_bw_hz: float = 5.0              # position-loop bandwidth
    iq_limit: float = 5.0               # A, current limit used by the velocity loop
    vel_limit: float = 150.0            # rad/s, limit used by the position loop
    ocp_threshold_A: float = 0.0        # A, comparator trip level; 0 = automatic:
                                        #    min(0.9 x measurable range, ocp_rig_max_A)
    ocp_rig_max_A: float = 10.0         # A, the rig never runs above 10 A (procedure safety rule 3)
    ocp_delay: float = 1e-6             # s, comparator + blanking + TIM1 break reaction time
    vbus_limiter: bool = True           # firmware V_bus limiter (reduce regen, brake with I_d)
    vbus_lim_start: float = 26.0        # V, limiter starts acting
    vbus_lim_full: float = 27.5         # V, limiter fully active (no regenerative torque left)
    id_brake: float = 5.0               # A, maximum -I_d injected to burn energy in the winding


@dataclass
class ScenarioParams:
    """Test settings used by the scenarios (what the firmware is told to do in each test).
    Lists are typed as text, comma-separated, e.g. "0.3, 0.5, 1.0"."""
    test_V_psu: float = 24.0            # V, PSU setting for T7 and T11-T14
    test_I_limit: float = 3.0           # A, PSU current limit for T7 and T11-T14
    t7_iq_A: float = 3.0                # A, constant i_q in the switching-level test
    t7_duration_ms: float = 2.0         # ms simulated (switching model is slow: keep it short)
    t9_V_psu: float = 12.0              # V, PSU setting for the first spin
    t9_I_limit: float = 1.0             # A, PSU current limit for the first spin
    t9_vq_steps: str = "0.3, 0.5, 1.0"  # V, open-loop V_q steps
    t9_f_el_hz: float = 1.0             # Hz, electrical frequency of the open-loop field
    t9_segment_s: float = 0.8           # s per V_q step
    t9_vq_max_procedure: float = 0.5    # V, the procedure's maximum open-loop V_q (checked)
    t11_iq_steps: str = "1, 3"          # A, i_q goes 0 -> first -> second -> 0
    t12_test_threshold_A: float = 2.0   # A, lowered comparator level used in the procedure test
    t12_test_iq_A: float = 3.0          # A, i_q step that must trip it
    t12_fault_angle_deg: float = 100.0  # electrical deg of the runaway voltage vector (worst case ~100)
    t13_vel_steps: str = "20, 100, -100, 0"   # rad/s, velocity steps (from 0)
    t13_vel_hold_s: float = 0.3         # s each velocity step is held
    t13_pos_steps_deg: str = "90, 180, 90"    # deg mechanical, position steps (from 0)
    t13_pos_hold_s: float = 0.4         # s each position step is held
    t14_speed: float = 100.0            # rad/s, speed before braking
    t14_load_inertia_mult: float = 20.0 # x motor inertia for the "real joint" variants (b, c, d)


@dataclass
class CriteriaParams:
    """Pass/fail limits. Defaults are the pass criteria in No_PCB_Rig_Bringup_Procedure.md."""
    vbus_max_V: float = 28.0            # T13, T14
    rise_max_ms: float = 0.5            # T11 (10-90 %)
    overshoot_max_pct: float = 20.0     # T11
    id_dev_max_A: float = 0.2           # T11
    ss_err_max_A: float = 0.05          # T11
    ocp_reaction_max_us: float = 2.0    # T12
    speed_ripple_max_pct: float = 5.0   # T13
    pos_err_max_deg: float = 0.5        # T13
    ripple_max_frac: float = 0.5        # T7, ripple / test current
    sample_err_max_A: float = 0.05      # T7
    enc_res_max_deg_e: float = 1.0      # T8
    psu_margin: float = 0.95            # T9: a PSU current above margin x limit counts as "in limit"


@dataclass
class SimParams:
    dt_avg_div: int = 8                 # averaged model: 8 integration steps per PWM period
    dt_switching: float = 25e-9         # switching model time step (must be << dead time)
    seed: int = 1                       # random seed for ADC noise (repeatable results)


@dataclass
class Params:
    motor: MotorParams = field(default_factory=MotorParams)
    inverter: InverterParams = field(default_factory=InverterParams)
    supply: SupplyParams = field(default_factory=SupplyParams)
    sensing: SensingParams = field(default_factory=SensingParams)
    control: ControlParams = field(default_factory=ControlParams)
    sim: SimParams = field(default_factory=SimParams)
    scen: ScenarioParams = field(default_factory=ScenarioParams)
    crit: CriteriaParams = field(default_factory=CriteriaParams)

    @staticmethod
    def from_json(path):
        """Load defaults, then overwrite with whatever the JSON file contains."""
        p = Params()
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        p.update(data)
        return p

    def update(self, data):
        """Overwrite values from a nested dict {group: {name: value}}. Values are converted to
        the type of the default (so "0.1" from a web form becomes 0.1). Unknown names raise."""
        for group, values in data.items():
            obj = getattr(self, group)
            for k, v in values.items():
                if not hasattr(obj, k):
                    raise KeyError(f"unknown parameter {group}.{k}")
                cur = getattr(obj, k)
                if isinstance(cur, bool):
                    v = v if isinstance(v, bool) else str(v).strip().lower() in ("1", "true", "yes", "on")
                elif isinstance(cur, int):
                    v = int(float(v))
                elif isinstance(cur, float):
                    v = float(v)
                else:
                    v = str(v)
                setattr(obj, k, v)
        return self

    def to_json(self, path):
        Path(path).write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")


GROUPS = ("motor", "inverter", "supply", "sensing", "control", "sim", "scen", "crit")

PLACEHOLDERS = ["motor.kv_rpm_per_v", "motor.R_phase", "motor.L_phase", "motor.J",
                "supply.C_board", "sensing.R_shunt"]


def copy_params(p):
    """Deep copy, so a scenario can change values without touching the caller's copy."""
    return Params(**{k: dataclasses.replace(getattr(p, k)) for k in
                     GROUPS})


# ======================================================================================
# 2. MATH HELPERS (same formulas the firmware uses)
# ======================================================================================
def clarke(ia, ib):
    """abc -> alpha/beta, amplitude-invariant, using ia + ib + ic = 0."""
    return ia, (ia + 2.0 * ib) / SQRT3


def park(alpha, beta, th):
    """alpha/beta -> d/q in the rotor frame at electrical angle th."""
    c, s = math.cos(th), math.sin(th)
    return alpha * c + beta * s, -alpha * s + beta * c


def inv_park(d, q, th):
    """d/q -> alpha/beta."""
    c, s = math.cos(th), math.sin(th)
    return d * c - q * s, d * s + q * c


def svpwm(v_alpha, v_beta, vbus):
    """alpha/beta voltage -> three duty cycles 0..1 (min-max zero-sequence injection,
    equivalent to space-vector PWM). Linear up to |v| = vbus / sqrt(3)."""
    va = v_alpha
    vb = -0.5 * v_alpha + 0.5 * SQRT3 * v_beta
    vc = -0.5 * v_alpha - 0.5 * SQRT3 * v_beta
    off = -(max(va, vb, vc) + min(va, vb, vc)) / 2.0
    inv = 1.0 / max(vbus, 1e-3)
    return tuple(min(1.0, max(0.0, 0.5 + (v + off) * inv)) for v in (va, vb, vc))


def wrap(a):
    """Wrap an angle to -pi .. +pi."""
    return (a + math.pi) % TWO_PI - math.pi


# ======================================================================================
# 3. PLANT: motor + inverter + DC bus (the physical world)
# ======================================================================================
class Plant:
    """State: phase currents ia, ib (ic = -ia - ib, star point not connected),
    mechanical angle and speed, bus voltage. Integrated with explicit Euler; the time step
    is far below the electrical time constant L/R (0.4 ms), so Euler is accurate here."""

    def __init__(self, p: Params, locked=False, theta0=0.0):
        self.p = p
        m = p.motor
        self.R = m.R_phase + p.inverter.R_on
        self.L = m.L_phase
        self.psi = m.psi()
        self.pp = m.pole_pairs
        self.Jt = m.J
        self.locked = locked
        self.ia = self.ib = 0.0
        self.theta_m = theta0
        self.omega_m = 0.0
        self.vbus = p.supply.V_psu - p.supply.V_schottky   # bus pre-charged by the PSU
        self.C = p.supply.C_bus + p.supply.C_board
        self.gates_on = True            # False after an over-current trip (all six FETs off, latched)
        self.uvlo = False               # True while the bus is below the driver's under-voltage level
        self.uvlo_events = 0            # how many times under-voltage lockout happened
        self.floating = [False, False, False]   # phases with zero current while the gates are off
        self.e_tvs = 0.0                # energy absorbed by the TVS, J
        self.i_psu = 0.0
        self.i_inv = 0.0                # A, current the bridge draws from the bus (negative = regen)
        self.i_tvs = 0.0                # A, TVS current
        self.t_load = 0.0               # external load torque, N m (scenarios set it)
        self.rect_warning = False       # back-EMF higher than the bus while the gates are off

    def emf(self):
        """Phase back-EMFs (V) for the present rotor angle and speed."""
        we = self.pp * self.omega_m
        th = self.pp * self.theta_m
        k = -we * self.psi
        return (k * math.sin(th), k * math.sin(th - TWO_PI / 3), k * math.sin(th + TWO_PI / 3))

    def iq(self):
        a, b = clarke(self.ia, self.ib)
        return park(a, b, self.pp * self.theta_m)[1]

    def step(self, legs, dt, duties_for_bus=None):
        """Advance by dt.
        legs: three leg voltages (V, relative to bus minus) when the gates are on.
        duties_for_bus: three numbers telling how much of each phase current is drawn from
        the bus (the duty in the averaged model, 1/0 switch states in the switching model)."""
        p = self.p
        ea, eb, ec = self.emf()
        ia, ib = self.ia, self.ib
        ic = -ia - ib
        R, L = self.R, self.L
        vd = p.inverter.v_diode

        if self.gates_on and not self.uvlo:
            va, vb, vc = legs
            vn = (va + vb + vc) / 3.0                       # star-point voltage
            dia = (va - vn - R * ia - ea) / L
            dib = (vb - vn - R * ib - eb) / L
            self.ia += dia * dt
            self.ib += dib * dt
            s = duties_for_bus
            i_inv = s[0] * ia + s[1] * ib + s[2] * (-ia - ib)
        else:
            # Gates off: current can only flow through the body diodes.
            # A phase with positive current conducts through its low-side diode (leg = -vd),
            # negative current through its high-side diode (leg = vbus + vd).
            # A phase whose current reaches zero stays at zero ("floating").
            cur = [ia, ib, ic]
            for k in range(3):
                if abs(cur[k]) < 1e-4:
                    self.floating[k] = True
            n_float = sum(self.floating)
            if n_float >= 2:
                self.ia = self.ib = 0.0
                ell = max(abs(ea - eb), abs(eb - ec), abs(ec - ea))
                if ell > self.vbus + 2 * vd:
                    self.rect_warning = True                # motor would start to rectify
                i_inv = 0.0
            elif n_float == 1:
                # Two phases carry +i and -i in series through two diodes.
                f = self.floating.index(True)
                y, z = [k for k in range(3) if k != f]
                e = (ea, eb, ec)
                i = cur[y]
                leg = lambda x: -vd if x > 0 else self.vbus + vd
                di = (leg(i) - leg(-i) - 2 * R * i - (e[y] - e[z])) / (2 * L)
                i_new = i + di * dt
                if i_new * i <= 0:                          # crossed zero: all floating
                    i_new = 0.0
                    self.floating = [True, True, True]
                newc = [0.0, 0.0, 0.0]
                newc[y], newc[z] = i_new, -i_new
                self.ia, self.ib = newc[0], newc[1]
                i_inv = (i if i < 0 else 0.0) + (-i if -i < 0 else 0.0)  # current into the bus
            else:
                legs_d = [(-vd if c > 0 else self.vbus + vd) for c in cur]
                vn = sum(legs_d) / 3.0
                self.ia += (legs_d[0] - vn - R * ia - ea) / L * dt
                self.ib += (legs_d[1] - vn - R * ib - eb) / L * dt
                i_inv = sum(c for c in cur if c < 0)        # negative currents feed the bus

        # ---- DC bus: PSU through the Schottky (one direction only), TVS, quiescent load ----
        sp = p.supply
        i_psu = (sp.V_psu - sp.V_schottky - self.vbus) / sp.R_source
        i_psu = min(max(i_psu, 0.0), sp.I_limit)             # diode blocks, PSU limits
        i_tvs = max(0.0, (self.vbus - sp.V_tvs_breakdown) / sp.R_tvs)
        self.e_tvs += i_tvs * self.vbus * dt
        self.vbus += (i_psu - i_inv - i_tvs - sp.I_quiescent) / self.C * dt
        self.i_psu = i_psu
        self.i_inv = i_inv
        self.i_tvs = i_tvs
        # DRV8323 under-voltage lockout (not latched): gates off below uvlo_v, back on above uvlo_v + hyst
        inv = p.inverter
        if not self.uvlo and self.vbus < inv.uvlo_v:
            self.uvlo = True
            self.uvlo_events += 1
            self.floating = [False, False, False]
        elif self.uvlo and self.vbus > inv.uvlo_v + inv.uvlo_hyst:
            self.uvlo = False
            self.floating = [False, False, False]

        # ---- Mechanics ----
        if not self.locked:
            m = p.motor
            te = 1.5 * self.pp * self.psi * self.iq()
            t_cog = -m.T_cog * math.sin(m.cog_per_rev * self.theta_m)
            t_drive = te + t_cog - self.t_load - m.B_visc * self.omega_m
            if abs(self.omega_m) < 1e-4 and abs(t_drive) <= m.T_coulomb:
                self.omega_m = 0.0                         # static friction holds the rotor
            else:
                sgn = math.copysign(1.0, self.omega_m if abs(self.omega_m) >= 1e-4 else t_drive)
                self.omega_m += (t_drive - m.T_coulomb * sgn) / self.Jt * dt
            self.theta_m += self.omega_m * dt


# ======================================================================================
# 4. SENSORS: what the firmware actually sees
# ======================================================================================
class Sensors:
    def __init__(self, p: Params, rng):
        self.p = p
        self.rng = rng
        s = p.sensing
        self.full = (1 << s.adc_bits) - 1
        self.amp_per_volt = 1.0 / (s.csa_gain * s.R_shunt)
        self.enc_counts = 1 << s.enc_bits
        self.enc_offset = math.radians(s.enc_offset_error_deg)

    def csa_volts(self, i):
        """Analog CSA output for phase current i (also used by the comparators)."""
        s = self.p.sensing
        return s.v_ref / 2.0 + s.csa_gain * s.R_shunt * i

    def adc_current(self, i):
        """One ADC sample of one phase: CSA -> clamp to 0..Vref -> 12-bit -> back to amps.
        The CSA offset is assumed calibrated away (test T8)."""
        s = self.p.sensing
        v = min(max(self.csa_volts(i), 0.0), s.v_ref)
        counts = round(v / s.v_ref * self.full + self.rng.gauss(0.0, s.adc_noise_lsb))
        counts = min(max(counts, 0), self.full)
        return (counts / self.full * s.v_ref - s.v_ref / 2.0) * self.amp_per_volt

    def encoder(self, theta_m):
        """14-bit absolute angle in counts (0..16383)."""
        return int(math.floor((theta_m % TWO_PI) / TWO_PI * self.enc_counts)) % self.enc_counts

    def vbus(self, v):
        return v * (1.0 + self.rng.gauss(0.0, self.p.sensing.vbus_noise_rel))


# ======================================================================================
# 5. CONTROLLER: a Python copy of the firmware ISR (runs once per PWM period)
# ======================================================================================
MODES = ("off", "openloop", "current", "velocity", "position")   # index is logged as "mode"


class Controller:
    """Modes:
       'off'       duties 0.5 (no voltage), used before a test starts
       'openloop'  voltage-mode FOC with a ramped angle (test T9, encoder not used)
       'current'   i_d / i_q PI control (test T11, T12)
       'velocity'  speed PI -> i_q reference (test T13a, T14)
       'position'  position P -> velocity loop (test T13b)
    The scenario sets the references (iq_ref, vel_ref, pos_ref, vq_ol, f_ol) over time."""

    def __init__(self, p: Params, sensors: Sensors):
        self.p = p
        self.s = sensors
        m, c = p.motor, p.control
        self.Ts = 1.0 / p.inverter.f_pwm
        wc = TWO_PI * c.current_bw_hz
        L = m.L_phase
        R = m.R_phase + p.inverter.R_on
        # Current PI by pole-zero cancellation: the closed loop behaves like a first-order
        # system with bandwidth wc. Kp in V/A, Ki in V/(A s).
        self.kp_i, self.ki_i = L * wc, R * wc
        # Velocity PI: plant J*s, Kt converts A -> N m. Integral corner at wv/5.
        wv = TWO_PI * c.vel_bw_hz
        self.kp_v = m.J * wv / m.kt()
        self.ki_v = self.kp_v * wv / 5.0
        # Position P: velocity reference = kp_p * position error.
        self.kp_p = TWO_PI * c.pos_bw_hz
        self.mode = "off"
        self.id_ref = self.iq_ref = 0.0
        self.vel_ref = self.pos_ref = 0.0
        self.vq_ol, self.f_ol, self.th_ol = 0.0, 0.0, 0.0
        self.int_d = self.int_q = self.int_v = 0.0
        self.vel_est = 0.0
        self.pos_est = 0.0
        self.last_count = None
        self.tick = 0
        self.vd = self.vq = 0.0
        self.id_meas = self.iq_meas = 0.0
        self.vbus_meas = p.supply.V_psu

    def _pi(self, err, integ, kp, ki, lo, hi, dt):
        """PI with clamping anti-windup: the integrator stops while the output saturates."""
        out = kp * err + integ
        if lo < out < hi or (out >= hi and err < 0) or (out <= lo and err > 0):
            integ += ki * err * dt
        return min(max(kp * err + integ, lo), hi), integ

    def isr(self, ia_true, ib_true, theta_m_true, vbus_true):
        """One ISR: sample, estimate, control, return the next duty cycles."""
        p, c, m = self.p, self.p.control, self.p.motor
        Ts = self.Ts
        # ---- 1. sample (simultaneous ADC1/ADC2 + bus), encoder over SPI ----
        ia = self.s.adc_current(ia_true)
        ib = self.s.adc_current(ib_true)
        self.vbus_meas = vbus = self.s.vbus(vbus_true)
        cnt = self.s.encoder(theta_m_true)
        if self.last_count is None:
            self.last_count = cnt
        dc = cnt - self.last_count
        if dc > self.s.enc_counts // 2:
            dc -= self.s.enc_counts
        elif dc < -self.s.enc_counts // 2:
            dc += self.s.enc_counts
        self.last_count = cnt
        self.pos_est += dc * TWO_PI / self.s.enc_counts          # multi-turn position
        th_e = m.pole_pairs * cnt * TWO_PI / self.s.enc_counts - self.s.enc_offset

        # ---- 2. velocity + position loops (slower rate) ----
        self.tick += 1
        if self.tick % c.vel_divider == 0:
            dtv = Ts * c.vel_divider
            raw = (self.pos_est - getattr(self, "_pos_prev", self.pos_est)) / dtv
            self._pos_prev = self.pos_est
            a = dtv / (c.vel_filter_tau + dtv)
            self.vel_est += a * (raw - self.vel_est)
            if self.mode == "position":
                self.vel_ref = min(max(self.kp_p * (self.pos_ref - self.pos_est), -c.vel_limit), c.vel_limit)
            if self.mode in ("velocity", "position"):
                self.iq_ref, self.int_v = self._pi(self.vel_ref - self.vel_est, self.int_v,
                                                   self.kp_v, self.ki_v, -c.iq_limit, c.iq_limit, dtv)

        # ---- 3. bus-voltage limiter: stop regenerating, burn energy with -I_d ----
        id_ref, iq_ref = self.id_ref, self.iq_ref
        if c.vbus_limiter and self.mode in ("current", "velocity", "position"):
            k = (c.vbus_lim_full - vbus) / (c.vbus_lim_full - c.vbus_lim_start)
            k = min(max(k, 0.0), 1.0)                     # 1 = normal, 0 = full limiting
            if iq_ref * self.vel_est < 0:                 # regenerative torque request
                iq_ref *= k
            id_ref = id_ref - c.id_brake * (1.0 - k)

        # ---- 4. current loop (FOC) ----
        if self.mode == "openloop":
            self.th_ol = (self.th_ol + TWO_PI * self.f_ol * Ts) % TWO_PI
            th_ctrl = self.th_ol                          # encoder not used in open loop
            vd_cmd, vq_cmd = 0.0, self.vq_ol
            al, be = clarke(ia, ib)
            self.id_meas, self.iq_meas = park(al, be, th_ctrl)
        elif self.mode == "off":
            return (0.5, 0.5, 0.5)
        else:
            th_ctrl = th_e
            al, be = clarke(ia, ib)
            idm, iqm = park(al, be, th_ctrl)
            self.id_meas, self.iq_meas = idm, iqm
            vmax = c.v_limit_factor * vbus / SQRT3
            ff_d = ff_q = 0.0
            if c.decoupling:
                we = m.pole_pairs * self.vel_est
                ff_d = -we * m.L_phase * iqm
                ff_q = we * (m.L_phase * idm + m.psi())
            vd_cmd, self.int_d = self._pi(id_ref - idm, self.int_d, self.kp_i, self.ki_i,
                                          -vmax - ff_d, vmax - ff_d, Ts)
            vd_cmd += ff_d
            vq_lim = math.sqrt(max(vmax * vmax - vd_cmd * vd_cmd, 0.0))
            vq_cmd, self.int_q = self._pi(iq_ref - iqm, self.int_q, self.kp_i, self.ki_i,
                                          -vq_lim - ff_q, vq_lim - ff_q, Ts)
            vq_cmd += ff_q
        self.vd, self.vq = vd_cmd, vq_cmd
        # ---- 5. modulation ----
        # The new duty is applied one PWM period later (written to TIM1 preload registers);
        # rotate by 1.5 periods of electrical motion to compensate the delay, as the firmware does.
        th_mod = th_ctrl + 1.5 * Ts * m.pole_pairs * self.vel_est
        al, be = inv_park(vd_cmd, vq_cmd, th_mod)
        return svpwm(al, be, vbus)


# ======================================================================================
# 6. SIMULATION ENGINE
# ======================================================================================
class Run:
    """Runs one scenario. `refs(t, ctrl, plant)` is called every ISR so the scenario can
    change references, mode or load. Results are logged once per PWM period
    (or every log_every steps in switching mode)."""

    def __init__(self, p: Params, locked=False, switching=False):
        self.p = p
        self.rng = random.Random(p.sim.seed)
        self.plant = Plant(p, locked=locked)
        self.sens = Sensors(p, self.rng)
        self.ctrl = Controller(p, self.sens)
        self.switching = switching
        self.trip_time = None           # time the gates were switched off by the comparators
        self.ocp_cross_time = None      # time a CSA output first exceeded the comparator level
        self.log = {k: [] for k in ("t", "ia", "ib", "ic", "id", "iq", "id_meas", "iq_meas", "vbus",
                                    "ipsu", "w", "w_est", "pos", "pos_ref", "vel_ref", "iq_ref", "vq", "gates",
                                    "th_ol", "uvlo", "da", "db", "dc", "iinv", "itvs", "trip", "mode")}
        self._duty = (0.5, 0.5, 0.5)    # duty cycles being applied (logged for the wiring animation)

    def ocp_level_volts(self):
        c, s = self.p.control, self.p.sensing
        thr = c.ocp_threshold_A if c.ocp_threshold_A > 0 else min(0.9 * s.i_range(), c.ocp_rig_max_A)
        return self.sens.csa_volts(thr), thr

    def _log(self, t):
        pl, ct = self.plant, self.ctrl
        a, b = clarke(pl.ia, pl.ib)
        d, q = park(a, b, pl.pp * pl.theta_m)
        L = self.log
        for k, v in (("t", t), ("ia", pl.ia), ("ib", pl.ib), ("ic", -pl.ia - pl.ib), ("id", d), ("iq", q),
                     ("id_meas", ct.id_meas), ("iq_meas", ct.iq_meas), ("vbus", pl.vbus), ("ipsu", pl.i_psu),
                     ("w", pl.omega_m), ("w_est", ct.vel_est), ("pos", pl.theta_m), ("pos_ref", ct.pos_ref),
                     ("vel_ref", ct.vel_ref), ("iq_ref", ct.iq_ref), ("vq", ct.vq), ("gates", 1.0 if pl.gates_on else 0.0),
                     ("th_ol", ct.th_ol), ("uvlo", 1.0 if pl.uvlo else 0.0),
                     ("da", self._duty[0]), ("db", self._duty[1]), ("dc", self._duty[2]),
                     ("iinv", pl.i_inv), ("itvs", pl.i_tvs), ("trip", 0.0 if pl.gates_on else 1.0),
                     ("mode", float(MODES.index(ct.mode)))):
            L[k].append(v)

    def run(self, t_end, refs, log_every=None):
        if self.switching:
            self._run_switching(t_end, refs, log_every or 10)
        else:
            self._run_averaged(t_end, refs)
        return {k: np.array(v) for k, v in self.log.items()}

    # ---- averaged model: legs = duty * vbus (+ dead-time voltage error) ----
    def _run_averaged(self, t_end, refs):
        p, pl, ct = self.p, self.plant, self.ctrl
        Ts = 1.0 / p.inverter.f_pwm
        n_sub = p.sim.dt_avg_div
        dt = Ts / n_sub
        dt_err = p.inverter.dead_time * p.inverter.f_pwm          # fraction of the period lost
        v_trip, _ = self.ocp_level_volts()
        duty_applied = (0.5, 0.5, 0.5)
        duty_next = (0.5, 0.5, 0.5)
        n_periods = int(round(t_end / Ts))
        t = 0.0
        trip_pending = None
        for k in range(n_periods):
            # ISR at the PWM centre: sample, compute, store the duty for the next period
            refs(t, ct, pl)
            duty_applied = duty_next
            self._duty = duty_applied
            duty_next = ct.isr(pl.ia, pl.ib, pl.theta_m, pl.vbus)
            self._log(t)
            for _ in range(n_sub):
                cur = (pl.ia, pl.ib, -pl.ia - pl.ib)
                # dead time: the leg loses dt_err * vbus when its current is positive, gains it when negative
                legs = tuple(duty_applied[j] * pl.vbus - math.copysign(dt_err * pl.vbus, cur[j])
                             if abs(cur[j]) > 0.05 else duty_applied[j] * pl.vbus for j in range(3))
                pl.step(legs, dt, duty_applied)
                t += dt
                # hardware over-current comparators: watch the analog CSA outputs continuously
                if pl.gates_on:
                    if max(self.sens.csa_volts(c) for c in (pl.ia, pl.ib, -pl.ia - pl.ib)) > v_trip:
                        if trip_pending is None:
                            trip_pending = t
                            self.ocp_cross_time = self.ocp_cross_time or t
                        if t - trip_pending >= p.control.ocp_delay:
                            pl.gates_on = False
                            self.trip_time = t
                    else:
                        trip_pending = None

    # ---- switching model: real centre-aligned PWM with dead time ----
    def _run_switching(self, t_end, refs, log_every):
        p, pl, ct = self.p, self.plant, self.ctrl
        Tp = 1.0 / p.inverter.f_pwm
        dt = p.sim.dt_switching
        n = int(round(t_end / dt))
        duty = (0.5, 0.5, 0.5)
        duty_next = (0.5, 0.5, 0.5)
        state = [0, 0, 0]               # 1 = high FET on, 0 = low FET on
        dead_until = [-1.0, -1.0, -1.0]
        next_isr = 0.5 * Tp             # ISR at the carrier peak (centre of the low-side on-time)
        next_update = Tp                # preload -> active at the next period start
        # fine-grained log for the ripple plot: all three phase currents and the ISR samples
        self.sw_log = {"t": [], "ia": [], "ib": [], "ic": [], "ia_sampled_t": [], "ia_sampled": [],
                       "sa": [], "sb": [], "sc": [], "vbus": []}   # leg states: 1 high FET, 0 low FET, 0.5 dead time
        v_trip, _ = self.ocp_level_volts()
        trip_pending = None
        t = 0.0
        for k in range(n):
            if t >= next_update:
                duty = duty_next
                next_update += Tp
            if t >= next_isr:
                refs(t, ct, pl)
                duty_next = ct.isr(pl.ia, pl.ib, pl.theta_m, pl.vbus)
                self._duty = duty
                self.sw_log["ia_sampled_t"].append(t)
                self.sw_log["ia_sampled"].append((pl.ia, pl.ib, -pl.ia - pl.ib))
                self._log(t)
                next_isr += Tp
            ph = (t % Tp) / Tp
            carrier = 1.0 - abs(2.0 * ph - 1.0)        # 0 at period start, 1 at the centre
            legs, sw, st = [], [], []
            cur = (pl.ia, pl.ib, -pl.ia - pl.ib)
            for j in range(3):
                want = 1 if carrier < duty[j] else 0
                if want != state[j]:
                    state[j] = want
                    dead_until[j] = t + p.inverter.dead_time
                st.append(0.5 if t < dead_until[j] else float(state[j]))
                if t < dead_until[j]:                  # dead time: both FETs off, diode conducts
                    if cur[j] > 0:
                        legs.append(-p.inverter.v_diode); sw.append(0.0)
                    else:
                        legs.append(pl.vbus + p.inverter.v_diode); sw.append(1.0)
                else:
                    legs.append(pl.vbus if state[j] else 0.0); sw.append(float(state[j]))
            pl.step(legs, dt, sw)
            # hardware over-current comparators (same logic as the averaged model)
            if pl.gates_on:
                if max(self.sens.csa_volts(c_) for c_ in (pl.ia, pl.ib, -pl.ia - pl.ib)) > v_trip:
                    if trip_pending is None:
                        trip_pending = t
                        self.ocp_cross_time = self.ocp_cross_time or t
                    if t - trip_pending >= p.control.ocp_delay:
                        pl.gates_on = False
                        self.trip_time = t
                else:
                    trip_pending = None
            if k % log_every == 0:
                self.sw_log["t"].append(t)
                self.sw_log["ia"].append(pl.ia)
                self.sw_log["ib"].append(pl.ib)
                self.sw_log["ic"].append(-pl.ia - pl.ib)
                self.sw_log["sa"].append(st[0]); self.sw_log["sb"].append(st[1]); self.sw_log["sc"].append(st[2])
                self.sw_log["vbus"].append(pl.vbus)
            t += dt


# ======================================================================================
# 7. SCENARIOS
#    Each returns a dict: title, metrics {name: value}, checks [(name, value, criterion, ok)],
#    figure file name. Criteria come from No_PCB_Rig_Bringup_Procedure.md.
# ======================================================================================
def parse_list(text):
    """'0.3, 0.5, 1.0' -> [0.3, 0.5, 1.0]  (used for the step lists in ScenarioParams)."""
    vals = [float(x) for x in str(text).replace(";", ",").split(",") if x.strip()]
    if not vals:
        raise ValueError(f"empty list: {text!r}")
    return vals


def _metric_rise(t, y, t0, y0, y1):
    """10-90 % rise time and overshoot (%) of a step from y0 to y1 that starts at t0.
    Returns (nan, nan) if the response never reaches 90 % (so a slow loop is never
    reported as fast)."""
    sel = t >= t0
    tt, yy = t[sel], y[sel]
    frac = (yy - y0) / (y1 - y0)
    if not np.any(frac >= 0.9) or not np.any(frac >= 0.1):
        return float("nan"), float("nan")
    t10 = tt[np.argmax(frac >= 0.1)]
    t90 = tt[np.argmax(frac >= 0.9)]
    return (t90 - t10), max((np.max(frac) - 1.0) * 100.0, 0.0)


def _test_supply(q):
    """Supply setting shared by T7, T11-T14 (scenario page in the UI)."""
    q.supply.V_psu, q.supply.I_limit = q.scen.test_V_psu, q.scen.test_I_limit


def _ok(x):
    """True only for a real number (nan / None count as failed)."""
    return x is not None and not (isinstance(x, float) and math.isnan(x))


def sc_T8(p, out, quick):
    """Resolution budget: no simulation, just the numbers the hardware gives you."""
    s, m, c, cr = p.sensing, p.motor, p.control, p.crit
    rng_a = s.i_range()
    lsb = 2 * rng_a / (2 ** s.adc_bits)
    enc_deg_e = 360.0 * m.pole_pairs / 2 ** s.enc_bits
    vel_res = TWO_PI / 2 ** s.enc_bits / (c.vel_divider / p.inverter.f_pwm)
    noise_a = s.adc_noise_lsb * lsb
    gains_ok = [g for g in (5, 10, 20, 40) if (s.v_ref / 2) / (g * s.R_shunt) >= p.inverter.I_max_board]
    best_gain = max(gains_ok) if gains_ok else None
    metrics = {"measurable current range (A, each direction)": rng_a, "current LSB (mA)": lsb * 1e3,
               "current noise per sample (mA rms)": noise_a * 1e3, "torque noise (mN m rms)": noise_a * m.kt() * 1e3,
               "encoder resolution (electrical deg)": enc_deg_e,
               "raw speed resolution at the velocity-loop rate (rad/s per count)": vel_res,
               "highest CSA gain that still covers the board rating": best_gain if best_gain else "none"}
    checks = [("current range covers the board rating", f"{rng_a:.1f} A", f"≥ {p.inverter.I_max_board:.0f} A",
               rng_a >= p.inverter.I_max_board),
              ("encoder resolution", f"{enc_deg_e:.3f} ° el", f"< {cr.enc_res_max_deg_e} ° el", enc_deg_e < cr.enc_res_max_deg_e)]
    note = (f"With R_shunt = {s.R_shunt * 1e3:.2f} mΩ, gain {best_gain} V/V is the highest that still covers "
            f"{p.inverter.I_max_board:.0f} A." if best_gain else
            "No CSA gain covers the board rating with this shunt: use a smaller shunt.")
    return dict(title="T8 · Resolution budget", metrics=metrics, checks=checks, fig=None, note=note)


def sc_T9(p, out, quick):
    """First spin in open loop: low-voltage PSU with a current limit, V_q stepped at a slow electrical frequency."""
    p = copy_params(p)
    sc, cr = p.scen, p.crit
    p.supply.V_psu, p.supply.I_limit = sc.t9_V_psu, sc.t9_I_limit
    seg = sc.t9_segment_s * (0.5 if quick else 1.0)
    vq_list = parse_list(sc.t9_vq_steps)
    steps = [(i * seg, v) for i, v in enumerate(vq_list)]

    def refs(t, c, pl):
        c.mode = "openloop"
        c.f_ol = sc.t9_f_el_hz
        c.vq_ol = [v for t0, v in steps if t >= t0][-1]

    r = Run(p)
    L = r.run(len(steps) * seg, refs)
    t = L["t"]
    iph = np.sqrt(L["id"] ** 2 + L["iq"] ** 2)       # phase current amplitude
    res = {}
    lim = cr.psu_margin * p.supply.I_limit
    for i, (t0, v) in enumerate(steps):
        t1 = steps[i + 1][0] if i + 1 < len(steps) else t[-1]
        sel = (t > t0 + 0.2 * seg) & (t < t1)
        res[v] = (iph[sel].max(), L["ipsu"][sel].max(), L["vbus"][sel].min(), bool(L["uvlo"][sel].max() > 0))
    # Pole-slip check. In open loop only V_q is applied, so near standstill the current vector
    # (and the rotor d-axis, which aligns with it) sits 90 deg AHEAD of the commanded angle th_ol.
    # delta = angle between that current vector and the rotor d-axis. Torque ~ sin(delta), so the
    # rotor slips a pole if |delta| exceeds 90 deg. Only the steps that stay inside the PSU limit count.
    lag = np.degrees(np.angle(np.exp(1j * (L["th_ol"] + math.pi / 2 - p.motor.pole_pairs * L["pos"]))))
    safe = [v for v, (a, b, _, u) in res.items() if b < lim and not u]
    v_safe = max(safe) if safe else 0.0
    t_safe_end = (vq_list.index(v_safe) + 1) * seg if safe else 0.0
    sel = (t > 0.1) & (t < t_safe_end)
    max_lag = float(np.max(np.abs(lag[sel]))) if np.any(sel) else float("nan")
    metrics = {f"V_q = {v} V: phase current peak (A) / PSU current max (A) / V_bus min (V) / driver under-voltage":
               f"{a:.2f} / {b:.2f} / {cmin:.2f} / {'YES' if u else 'no'}" for v, (a, b, cmin, u) in res.items()}
    metrics["largest V_q that stays inside the PSU limit (V)"] = v_safe
    metrics["largest load angle while inside the limit (electrical deg)"] = max_lag
    metrics["encoder counts per electrical turn"] = 2 ** p.sensing.enc_bits / p.motor.pole_pairs
    v1 = vq_list[0]
    checks = [(f"first step V_q = {v1} V keeps the PSU out of current limit", f"{res[v1][1]:.2f} A",
               f"< {lim:.2f} A", res[v1][1] < lim and not res[v1][3]),
              (f"procedure maximum V_q = {sc.t9_vq_max_procedure} V is inside the PSU limit", f"safe up to {v_safe} V",
               f"≥ {sc.t9_vq_max_procedure} V", v_safe >= sc.t9_vq_max_procedure),
              ("rotor follows the field without slipping a pole", f"{max_lag:.0f} ° el", "< 90 ° el", _ok(max_lag) and max_lag < 90.0),
              ("phase current stays below the board rating at every step", f"{max(r_[0] for r_ in res.values()):.1f} A",
               f"< {p.inverter.I_max_board:.0f} A", max(r_[0] for r_ in res.values()) < p.inverter.I_max_board)]
    fig, ax = plt.subplots(3, 1, figsize=(10, 8), sharex=True)
    ax[0].plot(t, L["ia"], lw=.6, label="i_a"); ax[0].plot(t, iph, label="|i| amplitude"); ax[0].set_ylabel("A"); ax[0].legend(); ax[0].grid(alpha=.3)
    ax[0].set_title(f"T9 open loop: V_q {' → '.join(str(v) for v in vq_list)} V at {sc.t9_f_el_hz} Hz el, "
                    f"PSU {sc.t9_V_psu} V / {sc.t9_I_limit} A")
    ax[1].plot(t, L["ipsu"], label="PSU current"); ax[1].axhline(p.supply.I_limit, color="r", ls="--", label="PSU limit")
    ax[1].set_ylabel("A"); ax[1].legend(); ax[1].grid(alpha=.3)
    ax[2].plot(t, L["vbus"], label="V_bus"); ax[2].set_ylabel("V"); ax[2].set_xlabel("s"); ax[2].legend(); ax[2].grid(alpha=.3)
    fn = "T9_openloop.png"; fig.tight_layout(); fig.savefig(out / fn, dpi=110); plt.close(fig)
    over = [v for v in vq_list if v not in safe]
    note = (f"Largest V_q that keeps the {sc.t9_V_psu} V / {sc.t9_I_limit} A PSU out of current limit: {v_safe} V "
            f"({res[v_safe][0]:.1f} A phase current). " if safe else "No step stays inside the PSU limit. ")
    if over:
        note += (f"At {over[0]} V the motor asks for more power than the PSU can give: the bus sags"
                 f"{' and the driver under-voltage lockout switches the gates off' if res[over[0]][3] else ''}.")
    return dict(title="T9 · First spin, open loop", metrics=metrics, checks=checks, fig=fn, note=note)


def sc_T11(p, out, quick):
    """Current-loop steps on a locked rotor: i_q 0 -> step 1 -> step 2 -> 0."""
    p = copy_params(p)
    _test_supply(p)
    sc, cr = p.scen, p.crit
    p.control.vbus_limiter = False
    a1, a2 = (parse_list(sc.t11_iq_steps) + [0.0])[:2]
    sched = [(0.0, 0.0), (0.005, a1), (0.015, a2), (0.025, 0.0)]

    def refs(t, c, pl):
        c.mode = "current"
        c.iq_ref = [v for t0, v in sched if t >= t0][-1]

    r = Run(p, locked=True)
    L = r.run(0.035, refs)
    t = L["t"]
    rise, os_ = _metric_rise(t, L["iq"], 0.015, a1, a2)
    sel = (t > 0.02) & (t < 0.025)
    err = abs(np.mean(L["iq"][sel]) - a2)
    id_dev = float(np.max(np.abs(L["id"][t > 0.004])))
    c = Controller(p, Sensors(p, random.Random(0)))
    theory = 2.197 / (TWO_PI * p.control.current_bw_hz)
    metrics = {"Kp (V/A)": c.kp_i, "Ki (V/(A s))": c.ki_i, f"rise time 10–90 % for {a1} → {a2} A (ms)": rise * 1e3,
               "delay-free first-order theory 2.2/ω_c (ms)": theory * 1e3,
               "overshoot (%)": os_, f"steady-state error at {a2} A (A)": err, "max |i_d| (A)": id_dev,
               "max PSU current (A)": float(L["ipsu"].max())}
    checks = [("rise time", f"{rise * 1e3:.3f} ms", f"≤ {cr.rise_max_ms} ms", _ok(rise) and rise <= cr.rise_max_ms * 1e-3),
              ("overshoot", f"{os_:.1f} %", f"< {cr.overshoot_max_pct} %", _ok(os_) and os_ < cr.overshoot_max_pct),
              ("I_d stays near 0", f"{id_dev:.3f} A", f"≤ {cr.id_dev_max_A} A", id_dev <= cr.id_dev_max_A),
              ("steady-state error", f"{err:.3f} A", f"< {cr.ss_err_max_A} A", err < cr.ss_err_max_A)]
    fig, ax = plt.subplots(2, 1, figsize=(10, 6), sharex=True)
    ax[0].plot(t * 1e3, L["iq_ref"], "k--", label="i_q ref"); ax[0].plot(t * 1e3, L["iq"], label="i_q true")
    ax[0].plot(t * 1e3, L["iq_meas"], lw=.5, alpha=.6, label="i_q measured (ADC)"); ax[0].plot(t * 1e3, L["id"], label="i_d true")
    ax[0].set_ylabel("A"); ax[0].legend(); ax[0].grid(alpha=.3)
    ax[0].set_title(f"T11 current steps, locked rotor, {p.supply.V_psu} V, bandwidth {p.control.current_bw_hz} Hz")
    ax[1].plot(t * 1e3, L["vq"], label="v_q command"); ax[1].set_ylabel("V"); ax[1].set_xlabel("ms"); ax[1].legend(); ax[1].grid(alpha=.3)
    fn = "T11_current_steps.png"; fig.tight_layout(); fig.savefig(out / fn, dpi=110); plt.close(fig)
    return dict(title="T11 · Current-loop steps (locked rotor)", metrics=metrics, checks=checks, fig=fn,
                note="The one-PWM-period control delay makes the step slightly faster than the delay-free "
                     "theory (checked with an independent model: 0.250 ms vs 0.350 ms at 1 kHz).")


def sc_T12(p, out, quick):
    """Hardware over-current trip: (a) procedure test with a lowered threshold, (b) runaway fault at the normal threshold."""
    res, logs = {}, {}
    sc, cr = p.scen, p.crit
    for name in ("a", "b"):
        q = copy_params(p)
        _test_supply(q)
        q.control.vbus_limiter = False
        q.sim.dt_avg_div = 200              # 125 ns steps: resolves the ~1 us comparator reaction
        if name == "a":
            q.control.ocp_threshold_A = sc.t12_test_threshold_A

            def refs(t, c, pl):
                c.mode = "current"
                c.iq_ref = sc.t12_test_iq_A if t >= 0.002 else 0.0
        else:
            def refs(t, c, pl):
                c.mode = "openloop"           # bypasses the current loop: voltage is applied blindly
                c.f_ol = 0.0
                c.th_ol = math.radians(sc.t12_fault_angle_deg)
                c.vq_ol = 0.95 * pl.vbus / SQRT3 if t >= 0.002 else 0.0
        r = Run(q, locked=True)
        L = r.run(0.006, refs)
        thr = r.ocp_level_volts()[1]
        peak = float(max(np.max(np.abs(L["ia"])), np.max(np.abs(L["ib"])), np.max(np.abs(L["ic"]))))
        delay = (r.trip_time - r.ocp_cross_time) if r.trip_time else float("nan")
        res[name] = (thr, r.trip_time, delay, peak)
        logs[name] = L
    metrics = {}
    for name, (thr, tt, d, pk) in res.items():
        label = (f"(a) test: {sc.t12_test_threshold_A} A threshold, {sc.t12_test_iq_A} A step" if name == "a"
                 else "(b) runaway fault, normal threshold")
        metrics[f"{label}: threshold (A) / tripped / reaction (µs) / peak |i| (A)"] = \
            f"{thr:.1f} / {'yes' if tt else 'NO'} / {d * 1e6:.2f} / {pk:.2f}"
    a, b = res["a"], res["b"]
    checks = [("(a) gates off after the threshold crossing", f"{a[2] * 1e6:.2f} µs", f"< {cr.ocp_reaction_max_us} µs",
               a[1] is not None and a[2] < cr.ocp_reaction_max_us * 1e-6),
              ("(b) runaway fault is caught", "yes" if b[1] else "no", "trip", b[1] is not None),
              ("(b) peak current stays inside the board rating", f"{b[3]:.1f} A", f"< {p.inverter.I_max_board:.0f} A",
               b[3] < p.inverter.I_max_board)]
    fig, ax = plt.subplots(2, 1, figsize=(10, 6))
    for i, name in enumerate(("a", "b")):
        L = logs[name]
        for ph in ("ia", "ib", "ic"):
            ax[i].plot(L["t"] * 1e3, L[ph], label=ph)
        ax[i].axhline(res[name][0], color="r", ls="--", label="comparator level (positive only)")
        ax[i].plot(L["t"] * 1e3, L["gates"] * res[name][0] * 0.5, "k:", label="gates on")
        ax[i].set_ylabel("A"); ax[i].legend(fontsize=8); ax[i].grid(alpha=.3)
    ax[0].set_title(f"T12 (a) procedure test: threshold {sc.t12_test_threshold_A} A, i_q step to {sc.t12_test_iq_A} A")
    ax[1].set_title("T12 (b) runaway fault: full voltage, normal threshold"); ax[1].set_xlabel("ms")
    fn = "T12_overcurrent_trip.png"; fig.tight_layout(); fig.savefig(out / fn, dpi=110); plt.close(fig)
    note = ("The comparators see only POSITIVE phase current (CSA above mid-scale). In a fault the largest "
            "current can be negative in one phase while the other two share it, so the trip can come late. "
            f"Peak in (b): {b[3]:.1f} A against a {b[0]:.1f} A threshold.")
    return dict(title="T12 · Hardware over-current trip", metrics=metrics, checks=checks, fig=fn, note=note)


def sc_T13(p, out, quick):
    """(a) velocity steps, (b) position steps, free shaft."""
    p = copy_params(p)
    _test_supply(p)
    sc, cr = p.scen, p.crit
    hv = sc.t13_vel_hold_s * (0.6 if quick else 1.0)
    vel_list = parse_list(sc.t13_vel_steps)
    vs = [(0.0, 0.0)] + [(0.05 + i * hv, v) for i, v in enumerate(vel_list)]

    def refs_v(t, c, pl):
        c.mode = "velocity"
        c.vel_ref = [v for t0, v in vs if t >= t0][-1]

    La = Run(p).run(0.05 + len(vel_list) * hv, refs_v)
    t = La["t"]
    # ripple at the fastest commanded speed, in the second half of its hold window
    k_fast = max(range(len(vel_list)), key=lambda i: abs(vel_list[i]))
    v_fast = vel_list[k_fast]
    t0f = 0.05 + k_fast * hv
    sel = (t > t0f + 0.5 * hv) & (t < t0f + hv)
    ripple = float(np.std(La["w"][sel]) / max(abs(v_fast), 1e-9) * 100.0)
    mean_err = float(abs(np.mean(La["w"][sel]) - v_fast))
    hp = sc.t13_pos_hold_s * (0.6 if quick else 1.0)
    pos_list = [math.radians(x) for x in parse_list(sc.t13_pos_steps_deg)]
    ps = [(0.0, 0.0)] + [(0.05 + i * hp, v) for i, v in enumerate(pos_list)]

    def refs_p(t, c, pl):
        c.mode = "position"
        c.pos_ref = [v for t0, v in ps if t >= t0][-1]

    Lb = Run(p).run(0.05 + len(pos_list) * hp, refs_p)
    tb = Lb["t"]
    errs = []
    for i, v in enumerate(pos_list):                     # settled error at the end of each hold
        t0p = 0.05 + i * hp
        selp = (tb > t0p + 0.75 * hp) & (tb < t0p + hp)
        errs.append(np.max(np.abs(Lb["pos"][selp] - v)))
    pos_err = math.degrees(max(errs))
    rise_p, os_p = _metric_rise(tb, Lb["pos"], 0.05, 0.0, pos_list[0])
    vmax_bus = float(max(La["vbus"].max(), Lb["vbus"].max()))
    metrics = {f"speed ripple at {v_fast} rad/s (% rms)": ripple, f"mean speed error at {v_fast} rad/s (rad/s)": mean_err,
               f"first position step: rise 10–90 % (ms)": rise_p * 1e3, "position overshoot (%)": os_p,
               "largest settled position error (deg)": pos_err,
               "max PSU current (A)": float(max(La["ipsu"].max(), Lb["ipsu"].max())), "max V_bus (V)": vmax_bus}
    checks = [(f"speed ripple at {v_fast} rad/s", f"{ripple:.2f} %", f"< {cr.speed_ripple_max_pct} %", ripple < cr.speed_ripple_max_pct),
              ("settled position error", f"{pos_err:.3f} °", f"< {cr.pos_err_max_deg} °", pos_err < cr.pos_err_max_deg),
              ("V_bus during reversals", f"{vmax_bus:.2f} V", f"< {cr.vbus_max_V} V", vmax_bus < cr.vbus_max_V)]
    fig, ax = plt.subplots(3, 1, figsize=(10, 9))
    ax[0].plot(t, La["vel_ref"], "k--", label="ref"); ax[0].plot(t, La["w"], label="true"); ax[0].plot(t, La["w_est"], lw=.6, label="estimate")
    ax[0].set_ylabel("rad/s"); ax[0].legend(); ax[0].grid(alpha=.3); ax[0].set_title("T13 (a) velocity steps, free shaft")
    ax[1].plot(t, La["iq"], label="i_q (A)"); ax[1].plot(t, La["vbus"] - p.supply.V_psu, label=f"V_bus − {p.supply.V_psu} V")
    ax[1].legend(); ax[1].grid(alpha=.3)
    ax[2].plot(tb, np.degrees(Lb["pos_ref"]), "k--", label="ref"); ax[2].plot(tb, np.degrees(Lb["pos"]), label="true")
    ax[2].set_ylabel("deg"); ax[2].set_xlabel("s"); ax[2].legend(); ax[2].grid(alpha=.3); ax[2].set_title("T13 (b) position steps")
    fn = "T13_velocity_position.png"; fig.tight_layout(); fig.savefig(out / fn, dpi=110); plt.close(fig)
    c = Controller(p, Sensors(p, random.Random(0)))
    return dict(title="T13 · Velocity and position loops", metrics=metrics, checks=checks, fig=fn,
                note=f"Gains used: Kp_v = {c.kp_v:.3f} A/(rad/s), Ki_v = {c.ki_v:.2f} A/rad, Kp_pos = {c.kp_p:.1f} 1/s.")


def sc_T14(p, out, quick):
    """Braking from speed: motor only, and with extra load inertia, with/without limiter and regen kit."""
    sc, cr = p.scen, p.crit
    jm = sc.t14_load_inertia_mult
    variants = {"a": (1.0, True, True), "b": (jm, True, False), "c": (jm, True, True), "d": (jm, False, True)}
    labels = {"a": "(a) motor only, kit, limiter on", "b": f"(b) {jm:g}× inertia, kit, limiter OFF",
              "c": f"(c) {jm:g}× inertia, kit, limiter on", "d": f"(d) {jm:g}× inertia, no kit caps, limiter on"}
    res, logs = {}, {}
    for name, (jmul, kit, lim) in variants.items():
        q = copy_params(p)
        _test_supply(q)
        q.motor.J *= jmul
        if not kit:
            q.supply.C_bus = 0.0
        q.control.vbus_limiter = lim
        # spin-up time: accelerate at the current limit, plus margin
        acc = q.control.iq_limit * q.motor.kt() / q.motor.J
        t_brake = max(0.15, 1.5 * sc.t14_speed / acc + 0.1)
        t_window = max(0.15, 2.0 * sc.t14_speed / acc + 0.3) * (0.7 if quick else 1.0)

        def refs(t, c, pl, tb=t_brake):
            c.mode = "velocity"
            c.vel_ref = sc.t14_speed if t < tb else 0.0

        r = Run(q)
        L = r.run(t_brake + t_window, refs)
        r_t = L["t"]
        sel = r_t >= t_brake
        stopped = np.abs(L["w"][sel]) < 1.0
        tstop = (r_t[sel][np.argmax(stopped)] - t_brake) if np.any(stopped) else None
        res[name] = (float(L["vbus"].max()), tstop, 0.5 * q.motor.J * sc.t14_speed ** 2, r.plant.e_tvs, t_window)
        logs[name] = L
    metrics = {}
    for n, (vmax, ts, e, etvs, tw) in res.items():
        stop_txt = f"{ts * 1e3:.0f} ms" if ts is not None else f"not stopped within {tw * 1e3:.0f} ms"
        metrics[f"{labels[n]}: kinetic energy (J) / peak V_bus (V) / stop time / TVS energy (J)"] = \
            f"{e:.2f} / {vmax:.2f} / {stop_txt} / {etvs:.2f}"
    vtvs = p.supply.V_tvs_breakdown
    checks = [("(a) normal rig: peak V_bus", f"{res['a'][0]:.2f} V", f"< {cr.vbus_max_V} V", res["a"][0] < cr.vbus_max_V),
              ("(c) heavy load with limiter: peak V_bus", f"{res['c'][0]:.2f} V", f"< {cr.vbus_max_V} V", res["c"][0] < cr.vbus_max_V),
              ("(d) no kit capacitors, limiter on: peak V_bus", f"{res['d'][0]:.2f} V", f"< {vtvs} V (TVS not reached)",
               res["d"][0] < vtvs)]
    fig, ax = plt.subplots(2, 1, figsize=(10, 7))
    for n in variants:
        L = logs[n]
        ax[0].plot(L["t"], L["vbus"], label=labels[n]); ax[1].plot(L["t"], L["w"], label=labels[n])
    ax[0].axhline(cr.vbus_max_V, color="r", ls="--", lw=.8, label=f"{cr.vbus_max_V} V pass limit")
    ax[0].set_ylabel("V_bus (V)"); ax[0].legend(fontsize=8); ax[0].grid(alpha=.3)
    ax[0].set_title(f"T14 regeneration: braking from {sc.t14_speed} rad/s")
    ax[1].set_ylabel("speed (rad/s)"); ax[1].set_xlabel("s"); ax[1].grid(alpha=.3)
    fn = "T14_regeneration.png"; fig.tight_layout(); fig.savefig(out / fn, dpi=110); plt.close(fig)
    p_cu = 1.5 * (p.motor.R_phase + p.inverter.R_on) * p.control.id_brake ** 2
    note = (f"Variant (b) shows why the firmware V_bus limiter matters once the motor drives a real load: "
            f"peak {res['b'][0]:.1f} V without it, TVS energy {res['b'][3]:.2f} J. With the limiter, braking is limited to "
            f"the copper loss of the winding (1.5 × R × I_d² ≈ {p_cu:.1f} W at id_brake = {p.control.id_brake} A), "
            "so a heavy joint coasts down slowly. For fast stops of a loaded joint on a bench PSU, raise id_brake "
            "or add a brake chopper / resistor (the deferred team rows B14–B19).")
    return dict(title="T14 · Regeneration / braking", metrics=metrics, checks=checks, fig=fn, note=note)


def sc_T7(p, out, quick):
    """Switching-level model: real PWM with dead time, locked rotor, constant i_q."""
    p = copy_params(p)
    _test_supply(p)
    sc, cr = p.scen, p.crit
    p.control.vbus_limiter = False

    def refs(t, c, pl):
        c.mode = "current"
        c.iq_ref = sc.t7_iq_A

    r = Run(p, locked=True, switching=True)
    t_end = sc.t7_duration_ms * 1e-3 * (0.5 if quick else 1.0)
    r.run(t_end, refs)
    sw = r.sw_log
    t = np.array(sw["t"])
    Tp = 1.0 / p.inverter.f_pwm
    sel = t > t_end - 4 * Tp
    # look at the phase that carries the most current (with the rotor locked at 0 deg,
    # i_q flows in phases b and c and phase a carries almost nothing)
    ph = max(range(3), key=lambda j: abs(np.mean(np.array(sw[("ia", "ib", "ic")[j]])[sel])))
    ia = np.array(sw[("ia", "ib", "ic")[ph]])
    # ripple: peak-to-peak inside each PWM period, averaged over the last 4 periods
    pps, errs = [], []
    ts_s = np.array(sw["ia_sampled_t"]); ia_s = np.array(sw["ia_sampled"])[:, ph]
    for kk in range(4):
        t0 = t_end - (kk + 1) * Tp
        m = (t >= t0) & (t < t0 + Tp)
        if m.any():
            pps.append(ia[m].max() - ia[m].min())
            j = np.argmin(np.abs(ts_s - (t0 + 0.5 * Tp)))
            errs.append(abs(ia_s[j] - ia[m].mean()))
    pp_ = float(np.mean(pps)); err = float(np.mean(errs))
    analytic = p.supply.V_psu / (4 * p.motor.L_phase * p.inverter.f_pwm) * (2 / 3)
    rip_lim = cr.ripple_max_frac * abs(sc.t7_iq_A)
    metrics = {"phase-current ripple, peak-to-peak (A)": pp_,
               "worst-case ripple at high modulation, estimate V/(4 L f) × 2/3 (A)": analytic,
               "difference between the centre sample and the period average (A)": err}
    checks = [("centre sample equals the average current", f"{err:.3f} A", f"< {cr.sample_err_max_A} A", err < cr.sample_err_max_A),
              (f"ripple below {cr.ripple_max_frac * 100:.0f} % of the test current", f"{pp_:.2f} A", f"< {rip_lim:.2f} A", pp_ < rip_lim)]
    fig, ax = plt.subplots(1, 1, figsize=(10, 4))
    ax.plot(t[sel] * 1e6, ia[sel], lw=.8, label=f"i_{'abc'[ph]} (switching model)")
    m2 = ts_s > t_end - 4 * Tp
    ax.plot(ts_s[m2] * 1e6, ia_s[m2], "ro", label="ADC sample at the PWM centre")
    ax.set_xlabel("µs"); ax.set_ylabel("A"); ax.grid(alpha=.3); ax.legend()
    ax.set_title(f"T7 switching model: {p.inverter.f_pwm / 1e3:.0f} kHz, {p.inverter.dead_time * 1e9:.0f} ns dead time, "
                 f"i_q = {sc.t7_iq_A} A locked")
    fn = "T7_switching_ripple.png"; fig.tight_layout(); fig.savefig(out / fn, dpi=110); plt.close(fig)
    return dict(title="T7 · Switching-level current ripple", metrics=metrics, checks=checks, fig=fn,
                note="The ripple is small at standstill (low modulation) and grows with speed towards the worst-case "
                     "estimate. A larger inductance or a higher PWM frequency reduces it proportionally.")


SCENARIOS = {"T7": sc_T7, "T8": sc_T8, "T9": sc_T9, "T11": sc_T11, "T12": sc_T12, "T13": sc_T13, "T14": sc_T14}



# ======================================================================================
# 9. TRACES FOR THE ANIMATED WIRING VIEW (rig_sim_ui.py, "Wiring flow" tab)
#    A trace is one simulation run whose time series drive the wiring animation:
#    every wire of rig_wiring.py is coloured / animated from these signals.
# ======================================================================================
TRACES = {
    "firstspin": "T9 first spin, open loop (PSU and V_q from Test settings)",
    "current": "T11 current steps, locked rotor",
    "overcurrent": "T12 over-current trip (lowered test threshold)",
    "velocity": "T13 velocity steps, free shaft",
    "position": "T13 position steps, free shaft",
    "braking": "T14 braking with the load inertia from Test settings (limiter as set in Firmware control)",
    "pwm": "PWM close-up: switching model, real 40 kHz edges and dead time (T7 settings)",
}


def _decimate(arrs, n_max):
    """Keep at most n_max samples (even stride) so the browser stays fast."""
    n = len(arrs["t"])
    step = max(1, int(math.ceil(n / n_max)))
    return {k: [float(f"{x:.5g}") for x in np.asarray(v)[::step]] for k, v in arrs.items()}


def trace(p, name, quick=False, max_frames=4000):
    """Run one trace and return {title, kind, t, signals..., meta}.
    kind 'avg' = averaged model (duty cycles), 'pwm' = switching model (real leg states)."""
    q = copy_params(p)
    sc = q.scen
    k = 0.5 if quick else 1.0
    locked = False
    if name == "firstspin":
        q.supply.V_psu, q.supply.I_limit = sc.t9_V_psu, sc.t9_I_limit
        vq = parse_list(sc.t9_vq_steps)
        seg = sc.t9_segment_s * k
        steps = [(i * seg, v) for i, v in enumerate(vq)]
        t_end = len(steps) * seg

        def refs(t, c, pl):
            c.mode, c.f_ol = "openloop", sc.t9_f_el_hz
            c.vq_ol = [v for t0, v in steps if t >= t0][-1]
    elif name == "current":
        _test_supply(q); q.control.vbus_limiter = False; locked = True
        a1, a2 = (parse_list(sc.t11_iq_steps) + [0.0])[:2]
        sched = [(0.0, 0.0), (0.005, a1), (0.015, a2), (0.025, 0.0)]
        t_end = 0.035

        def refs(t, c, pl):
            c.mode = "current"
            c.iq_ref = [v for t0, v in sched if t >= t0][-1]
    elif name == "overcurrent":
        _test_supply(q); q.control.vbus_limiter = False; locked = True
        q.control.ocp_threshold_A = sc.t12_test_threshold_A
        q.sim.dt_avg_div = 40
        t_end = 0.006

        def refs(t, c, pl):
            c.mode = "current"
            c.iq_ref = sc.t12_test_iq_A if t >= 0.002 else 0.0
    elif name == "velocity":
        _test_supply(q)
        hv = sc.t13_vel_hold_s * k
        vl = parse_list(sc.t13_vel_steps)
        vs = [(0.0, 0.0)] + [(0.05 + i * hv, v) for i, v in enumerate(vl)]
        t_end = 0.05 + len(vl) * hv

        def refs(t, c, pl):
            c.mode = "velocity"
            c.vel_ref = [v for t0, v in vs if t >= t0][-1]
    elif name == "position":
        _test_supply(q)
        hp = sc.t13_pos_hold_s * k
        pl_ = [math.radians(x) for x in parse_list(sc.t13_pos_steps_deg)]
        ps = [(0.0, 0.0)] + [(0.05 + i * hp, v) for i, v in enumerate(pl_)]
        t_end = 0.05 + len(pl_) * hp

        def refs(t, c, pl):
            c.mode = "position"
            c.pos_ref = [v for t0, v in ps if t >= t0][-1]
    elif name == "braking":
        _test_supply(q)
        q.motor.J *= sc.t14_load_inertia_mult
        acc = q.control.iq_limit * q.motor.kt() / q.motor.J
        t_brake = max(0.15, 1.5 * sc.t14_speed / acc + 0.1)
        t_end = t_brake + max(0.15, 2.0 * sc.t14_speed / acc + 0.3) * (0.7 if quick else 1.0)

        def refs(t, c, pl):
            c.mode = "velocity"
            c.vel_ref = sc.t14_speed if t < t_brake else 0.0
    elif name == "pwm":
        _test_supply(q); q.control.vbus_limiter = False
        r = Run(q, locked=True, switching=True)
        t_end = max(sc.t7_duration_ms * 1e-3 * k, 0.5e-3)

        def refs(t, c, pl):
            c.mode, c.iq_ref = "current", sc.t7_iq_A
        r.run(t_end, refs, log_every=4)                      # 100 ns resolution
        sw = r.sw_log
        tt = np.array(sw["t"])
        sel = tt >= t_end - 8.0 / q.inverter.f_pwm             # last 8 PWM periods
        data = {key: np.array(sw[key])[sel] for key in ("t", "ia", "ib", "ic", "sa", "sb", "sc", "vbus")}
        data["t"] = data["t"] - data["t"][0]
        out = _decimate(data, max_frames)
        out.update(title=TRACES[name], kind="pwm", meta=_trace_meta(q))
        return out
    else:
        raise ValueError(f"unknown trace {name}")
    L = Run(q, locked=locked).run(t_end, refs)
    keep = ("t", "ia", "ib", "ic", "iq", "id", "iq_ref", "vbus", "ipsu", "iinv", "itvs", "w", "pos",
            "vel_ref", "pos_ref", "da", "db", "dc", "uvlo", "trip", "mode")
    out = _decimate({key: L[key] for key in keep}, max_frames)
    out.update(title=TRACES[name], kind="avg", meta=_trace_meta(q))
    return out


def _trace_meta(q):
    """Constants the animation needs (to turn currents into sense-wire voltages etc.)."""
    s = q.sensing
    return dict(v_ref=s.v_ref, csa_v_per_a=s.csa_gain * s.R_shunt, f_pwm=q.inverter.f_pwm,
                pole_pairs=q.motor.pole_pairs, i_board=q.inverter.I_max_board, I_quiescent=q.supply.I_quiescent,
                V_psu=q.supply.V_psu, modes=list(MODES))


# ======================================================================================
# 8. REPORT
# ======================================================================================
def write_report(p, results, out, elapsed):
    lines = ["# rig_sim.py results\n",
             "Offline simulation of the iGL-FOC-1 no-PCB rig with a 5010 motor. Generated by `rig_sim.py`. "
             "The pass criteria come from `No_PCB_Rig_Bringup_Procedure.md`. "
             "**A simulation PASS is not a substitute for the real test.** It shows that the plan, gains and "
             "limits are sensible for the parameters below.\n"]
    n_pass = sum(1 for r in results for c in r["checks"] if c[3])
    n_all = sum(len(r["checks"]) for r in results)
    lines.append(f"**Summary: {n_pass} / {n_all} checks pass** · run time {elapsed:.0f} s\n")
    lines.append("## Parameters used\n")
    lines.append("| Group | Parameter | Value | Note |\n|---|---|---|---|")
    for g in GROUPS:
        for k, v in asdict(getattr(p, g)).items():
            note = "**PLACEHOLDER: replace with a measured/datasheet value**" if f"{g}.{k}" in PLACEHOLDERS else ""
            lines.append(f"| {g} | {k} | {v} | {note} |")
    m = p.motor
    lines.append(f"\nDerived: line-line K_e = {m.ke_ll() * 1e3:.2f} mV/(rad/s), ψ = {m.psi() * 1e3:.3f} mWb, "
                 f"K_t = {m.kt() * 1e3:.1f} mN m/A, measurable current range ±{p.sensing.i_range():.1f} A.\n")
    for r in results:
        lines.append(f"## {r['title']}\n")
        if r["fig"]:
            lines.append(f"![{r['title']}]({r['fig']})\n")
        lines.append("| Check | Simulated | Criterion | Result |\n|---|---|---|---|")
        for name, val, crit, ok in r["checks"]:
            lines.append(f"| {name} | {val} | {crit} | {'PASS' if ok else '**FAIL**'} |")
        lines.append("\n| Quantity | Value |\n|---|---|")
        for k, v in r["metrics"].items():
            lines.append(f"| {k} | {v:.4g} |" if isinstance(v, float) else f"| {k} | {v} |")
        if r.get("note"):
            lines.append(f"\n{r['note']}\n")
    (out / "rig_sim_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description="Simulate the iGL-FOC-1 no-PCB rig with a 5010 motor.")
    ap.add_argument("--scenario", nargs="*", default=list(SCENARIOS), help="scenarios to run (default: all)")
    ap.add_argument("--params", help="JSON file with parameter overrides (see --write-params)")
    ap.add_argument("--write-params", metavar="FILE", help="write every parameter to FILE and exit")
    ap.add_argument("--out", default=str(Path(__file__).with_name("rig_sim_out")), help="output folder")
    ap.add_argument("--quick", action="store_true", help="shorter runs")
    ap.add_argument("--list", action="store_true", help="list the scenarios and exit")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # Windows consoles: allow Ω, µ, °
    if a.list:
        for k, f in SCENARIOS.items():
            print(f"{k:4} {f.__doc__.strip().splitlines()[0]}")
        return 0
    p = Params.from_json(a.params) if a.params else Params()
    if a.write_params:
        p.to_json(a.write_params)
        print("parameters written to", a.write_params)
        return 0
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    results = []
    for name in a.scenario:
        if name not in SCENARIOS:
            print(f"unknown scenario {name}; use --list")
            return 2
        ts = time.time()
        r = SCENARIOS[name](p, out, a.quick)
        results.append(r)
        print(f"\n== {r['title']}  ({time.time() - ts:.1f} s)")
        for nm, val, crit, ok in r["checks"]:
            print(f"   [{'PASS' if ok else 'FAIL'}] {nm}: {val} (criterion {crit})")
        if r.get("note"):
            print("   note:", r["note"])
    write_report(p, results, out, time.time() - t0)
    print(f"\nreport: {out / 'rig_sim_report.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
