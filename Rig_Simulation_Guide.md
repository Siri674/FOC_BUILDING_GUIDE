# Rig simulation guide (5010 motor on the no-PCB rig)

**iGL-FOC-1 · for every team member · 1 Nov 2026**

Two offline, free simulations of the rig in `No_PCB_Rig_Bringup_Procedure.md`. Run them before each real test, and run them again after the motor has been measured.

| File | What it is | Needs |
|---|---|---|
| `rig_sim.py` | Full rig simulation: motor, inverter, bus with the regen kit, sensors, and a Python copy of the firmware (FOC current loop, velocity and position loops, over-current comparators, bus limiter). Runs the tests T7, T8, T9, T11, T12, T13 and T14, with PASS/FAIL. | Python 3.9+, `pip install numpy matplotlib` |
| `rig_sim_ui.py` | **Browser UI** for `rig_sim.py`: every parameter, test setting and pass criterion as a form field; derived values update while you type; plots and PASS/FAIL tables appear in the page. Runs only on your own PC (127.0.0.1). | Same as `rig_sim.py`; no extra packages |
| `rig_power_stage.cir` | LTspice switching-level netlist of the power stage (three half-bridges with dead time, shunts, motor R-L-EMF, PSU, Schottky, capacitors, TVS). Open loop, for ripple / dead time / bus behaviour. | LTspice (free). **Not yet run: the first person to run it, record the results.** |

---

## 0. Easiest way: the browser UI

```bash
python rig_sim_ui.py
```

It opens http://127.0.0.1:8050 in your browser. Stop it with Ctrl+C in the terminal.

| Part of the page | Use |
|---|---|
| Left: parameter groups (Motor, Inverter, Supply, Sensing, Firmware control, Simulation engine, Test settings, Pass criteria) | Type values in normal units (mΩ, µH, µF, ns …). **Highlighted rows are placeholders**; a bold label means the value differs from the default. Lists (V_q steps, velocity steps …) are typed comma-separated. |
| Right top: Derived values | Recomputed while you type: K_t, ψ, current range, trip level, PI gains, T9 current estimate, T14 braking energy and worst-case bus voltage, ripple. **⚠ = check this before running.** |
| Top bar | Pick scenarios, tick **quick** for shorter runs, then **Run selected**. Results appear one scenario at a time. |
| Save / Load parameters | JSON in SI units, the same format as `rig_sim.py --write-params` / `--params`. |
| Download report | Markdown report of the last run. Every run is also kept in `rig_sim_out/ui_runs/<date-time>/` (plots, report, params.json). |

Other start options: `--port 8060` (another port), `--no-browser` (open the address yourself).

**Keep the terminal window open while you use the page.** The page talks to that running program. If the browser says "127.0.0.1 refused to connect", the program isn't running: start it again.

### 0.1 Wiring flow tab (animated wiring)

The **Wiring flow (animated)** tab shows the physical layout of the rig (every wire W01…W41, P01…P09 from `rig_wiring.py`), driven by a simulation run with the parameters on the left. Click **Hide parameters** for a bigger view.

1. Pick a trace and click **Simulate trace** (2–10 s). The traces are: first spin (T9), current steps (T11), over-current trip (T12), velocity steps, position steps (T13), braking (T14), and **PWM close-up**.
2. It plays at once. Use **Play/Pause**, the **timeline**, **Speed** and **loop**. Click the charts to jump in time.

| On the drawing | Meaning |
|---|---|
| Moving dots on power and motor wires (P01–P09) | Current: direction of travel = direction of current, size and speed = magnitude. During braking, the bus wires reverse (energy into the capacitors) and the PSU wires stop (D1 blocks). |
| PWM wires W01–W06 | Brightness = duty cycle (normal traces). In **PWM close-up**: lit = that FET is on, both dim = dead time. |
| W08 ENABLE / W09 nFAULT | Lit = driver enabled. nFAULT turns red on a driver under-voltage fault. |
| Current-sense W14–W16 and bus-sense W17 wires | Colour follows the voltage (green ≈ mid-scale, red/orange near the rails). |
| Encoder, DRV SPI and CAN wires | Blink to show activity. **Illustrative only: their timing is not simulated.** |
| Red marker on the motor | Rotor angle. |
| Live values panel and badges | Mode, duties or leg states, V_bus, PSU / bus / TVS currents, i_q, i_d, speed, position, phase currents. Badges: OCP TRIP, UVLO, REGEN, TVS conducting, dead time. |

Speeds: normal traces run from ×0.001 to ×1 real time. PWM close-up runs from ×0.000001 to ×0.0001: at ×0.00001 one 25 µs PWM period takes 2.5 s on screen. NTC temperatures are not simulated, so those wires stay static.

## 1. Run rig_sim.py from the command line

```bash
pip install numpy matplotlib
```
```bash
python rig_sim.py
```

That runs every scenario in about 1 minute. The outputs go to `rig_sim_out/`:

| Output | Content |
|---|---|
| `rig_sim_report.md` | Every parameter (placeholders marked), every check with PASS/FAIL against the procedure's pass criteria, all numbers, and the plots |
| `T7_switching_ripple.png` … `T14_regeneration.png` | One plot per scenario |

Other options:

| Command | Does |
|---|---|
| `python rig_sim.py --list` | List the scenarios |
| `python rig_sim.py --scenario T11 T14` | Run only those |
| `python rig_sim.py --quick` | Shorter runs (≈ 30 s) |
| `python rig_sim.py --write-params my_motor.json` | Write every parameter to a JSON file |
| `python rig_sim.py --params my_motor.json` | Run with your edited values |

## 2. Put in your measured values (do this after test T10)

1. Write the parameter file:
   ```bash
   python rig_sim.py --write-params my_motor.json
   ```
2. Edit `my_motor.json`. These are the six **placeholders**:

   | Parameter | Where the real value comes from |
   |---|---|
   | `motor.R_phase` | T10 (firmware), or a milliohm meter: line-to-line ÷ 2 |
   | `motor.L_phase` | T10 |
   | `motor.kv_rpm_per_v` | Spec, or the torque test (K_t = 8.27 / KV) |
   | `motor.J` | Spec, or a coast-down test |
   | `sensing.R_shunt` | BOOSTXL schematic, TI SLVC690 |
   | `supply.C_board` | BOOSTXL schematic, TI SLVC690 |

   Also set `sensing.csa_gain` to the gain you program in T5.
3. Run with your values:
   ```bash
   python rig_sim.py --params my_motor.json
   ```
4. Commit `my_motor.json` and `rig_sim_out/rig_sim_report.md` to Git with the test record (procedure §9).

## 3. Scenarios and how they map to the procedure

| Scenario | Simulates | Procedure test | Main question it answers |
|---|---|---|---|
| T7 | Real 40 kHz PWM, 200 ns dead time, locked rotor, I_q = 3 A | T7, T8 | How big is the current ripple, and does sampling at the PWM centre give the average current? |
| T8 | Resolution budget (calculation only) | T5, T8 | Does the CSA gain cover 15 A? What are the LSB and encoder resolution? |
| T9 | Open loop, V_q 0.3 → 0.5 → 1.0 V, PSU 12 V / 1 A | T9 | Which V_q is safe for the first spin? |
| T11 | Current steps 0 → 1 → 3 → 0 A, locked rotor | T11 | Do the gains K_p = L·ω_c, K_i = R·ω_c give a clean step? |
| T12 | (a) comparator test at 2 A; (b) runaway fault at the normal threshold | T12 | Does the hardware trip react in < 2 µs? How high does a fault current go? |
| T13 | Velocity steps ±100 rad/s; 90° position steps | T13 | Are the velocity and position loops stable and accurate? |
| T14 | Braking from 100 rad/s: motor only, and with 20× load inertia, with and without the limiter and kit | T14 | Does V_bus stay < 28 V? What happens with a real joint load? |

## 4. Results with the placeholder 5010 values (run of 1 Nov 2026)

All 21 checks PASS. Things the simulation taught us, already written into the procedure or flagged here:

| # | Finding | Action |
|---|---|---|
| 1 | **Open loop at 1 V on a 12 V / 1 A supply is too much.** It gives ≈ 9 A of phase current, the PSU goes into current limit, the bus collapses and the driver under-voltage lockout trips. 0.5 V gives ≈ 4 A and 0.28 A from the PSU. | Procedure now says V_q ≤ **0.5 V** (safety rule 4, T9). |
| 2 | With the reset-default CSA gain of 20 and a 7 mΩ shunt the range is only ±11.8 A, below the board's 15 A. Gain 10 gives ±23.6 A. | Choose the gain in T5 once R_SH is known (the sim's default is 10). |
| 3 | Current loop: 0.25 ms rise, 1 % overshoot, I_d stays within 0.03 A. | The gain formula is fine; re-run with the measured R and L. |
| 4 | Hardware trip reacts in 1 µs. **But the comparators only see positive phase current.** In a runaway fault the largest phase current can be negative, so the peak reached 14.6 A against a 10 A threshold: just inside the 15 A rating. | Keep the DRV8323 V_DS over-current enabled as the second layer (procedure T5). For the Rev A PCB, consider a second comparator per phase with inverted polarity. |
| 5 | Braking the bare motor from 100 rad/s raises V_bus by < 1 V: the regen kit is plenty. | — |
| 6 | **With 20× load inertia (a real joint), braking without the firmware bus limiter drives V_bus to 31 V, so the TVS conducts.** With the limiter, V_bus stays at 27 V, but the joint coasts down slowly, because the only brake is copper loss in the winding (≈ 4 W). | Keep the bus limiter in the firmware. For fast stops of a loaded joint on a bench PSU, raise `id_brake`, or build the brake chopper (team rows B14–B19) later. |

These numbers depend on the placeholders. **Re-run with the measured values before trusting them.**

## 4b. How the simulator was verified (1 Nov 2026)

| Check | Result |
|---|---|
| Line-by-line review of the motor, inverter, bus, sensor, controller and engine code | Equations and sign conventions consistent: back-EMF ↔ Park (e_q = ω_e ψ), torque = 1.5 p ψ i_q, diode freewheel paths, regen current into the bus, PSU limit behind the Schottky, friction |
| Current loop against an independent model (R-L plant + PI + one-period delay, written separately) | Same rise time: **0.250 ms** in both. The delay-free textbook value is 0.350 ms; the control delay makes the step slightly faster. |
| T9 phase current against hand calculation | (V_q − dead-time error) / R = (0.3 − 0.09) / 0.102 ≈ 2.0 A; simulated 1.9 A |
| T12 trip reaction | Exactly the configured 1.0 µs (resolved with 125 ns steps) |
| T14 energy balance (motor only) | 0.25 J kinetic → +0.7 V on 4.5 mF; the rest goes into copper and friction losses, as expected |
| Regression after making the scenarios and criteria parameters | Same 21/21 results and numbers as before the change |
| UI | Unit conversion (mΩ/µH/g·cm²/ns ↔ SI) checked; an invalid input gives a plain-English error; a saved params.json loads in the command-line `rig_sim.py` |

Fixes made during the review:
- The over-current comparators are now also active in the switching model.
- The rise-time measurement returns "not reached" instead of a wrong number if a step never completes.
- The T9 note uses the simulated current instead of a fixed text.
- The scenario settings and pass limits are now parameters (`scen`, `crit`), so they can be changed from the UI or a JSON file.
- LTspice netlist: behavioural expressions use braced parameters, and the TVS measurement was renamed `ITVS_PEAK` with the correct sign.

## 5. How rig_sim.py works (for anyone editing it)

The file is split into numbered sections, each with comments:

1. **Parameters:** dataclasses; every number lives here.
   - `ScenarioParams` (`scen`) holds what each test commands.
   - `CriteriaParams` (`crit`) holds the pass/fail limits.
   - `PLACEHOLDERS` lists the values still to be measured.
   - A new field added here appears in the UI automatically. Add a label, unit and scale for it in `FIELD_INFO` in `rig_sim_ui.py` for nicer display.
2. **Math helpers:** Clarke, Park, inverse Park and SVPWM. These are the same formulas the firmware uses.
3. **Plant:**
   - Motor in phase currents (star point floating), back-EMF, cogging and friction.
   - Inverter: averaged, or switching with dead time; body diodes when the gates are off.
   - DC bus: PSU with current limit behind the Schottky, capacitors, TVS, and the DRV8323 under-voltage lockout.
4. **Sensors:** CSA → 12-bit ADC with noise, 14-bit encoder, bus-voltage measurement.
5. **Controller:** a line-by-line copy of the planned ISR.
   - Sample, then estimate speed/position.
   - Velocity/position loops at 5 kHz.
   - Bus limiter.
   - d/q PI loops with anti-windup and decoupling.
   - Delay compensation, then SVPWM.
   - The output is applied one PWM period later, as with TIM1 preload.
6. **Engine:** `Run` steps the plant 8× per PWM period (averaged) or every 25 ns (switching). It calls the controller once per period and watches the comparators continuously.
7. **Scenarios:** one function per test, each returning metrics, checks and a figure. **To add a test:** copy a scenario function, change `refs()` (what the firmware is told to do over time) and the checks, then add it to `SCENARIOS`.
8. **Report:** writes `rig_sim_report.md`.

When the real firmware changes (gains, limits, loop rates), make the same change in `ControlParams` or `Controller.isr()`, so the simulation keeps matching the board.

## 6. LTspice netlist (rig_power_stage.cir)

1. Open LTspice → File → Open → file type "All files" → `rig_power_stage.cir` → Run.
2. Plot `V(vbus)`, `I(Ra)`, `I(R1)` (PSU current) and `V(sa)` (phase-A switch node).
3. Ctrl+L opens the log with the `.meas` results:
   - `VBUS_MAX`, `VBUS_MIN`
   - `IA_RMS`, `IA_RIPPLE`
   - `IPSU_AVG`
   - `ITVS_MAX`
4. Scenarios: edit the `.param` lines (they are listed in the file header):
   - A motoring
   - B braking
   - C braking with no regen kit
   - D dead-time comparison
5. Compare the expectations at the bottom of the file with `rig_sim.py` (same parameter names). Record the LTspice version and results in this guide.

## 7. Limits: what neither simulation covers

- FET switching losses, ringing and gate-drive strength. Measure these with the scope in T7.
- DRV8323 internal protections other than under-voltage (V_DS over-current, over-temperature).
- Magnetic saturation, temperature rise, real cogging shape, sensor non-linearity.
- CAN timing and the real ISR execution time. Measure the ISR on PC6 in T11.

**A simulation PASS means the plan is sensible. It never replaces the real test with the scope and the current-limited supply.**
