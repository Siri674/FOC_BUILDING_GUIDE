# No-PCB rig: wiring, programming and verification procedure

**iGL-FOC-1 · NUCLEO-G474RE + BOOSTXL-DRV8323RS + AS5047P + CAN · 1 Nov 2026**

Work through this file top to bottom. Every wire is named by its ID (W01…W41, P01…P09). The IDs come from `rig_wiring.py`.

| File | Use |
|---|---|
| `rig_wiring.py` | Single source of truth for the wiring. Run `python rig_wiring.py`: it checks every pin and regenerates the files below. Change wiring **only** in its `WIRES` table. |
| `rig_wiring_out/Rig_Wiring_Reference.md` | Component-wise pin tables, master wire list, CubeMX pin table, SPI command words |
| `rig_wiring_out/rig_wire_list.csv` | Print it; tick `continuity_ok` and `checked_by` for every wire |
| `rig_wiring_out/rig_wiring_diagram.svg` | Wiring diagram with wire IDs and colours (open in a browser) |
| `No_PCB_Rig_G474_Buy_List.md` | Parts (R1–R33) |

Header pin numbers were checked against **TI SLVUB01C** (BOOSTXL J3/J4, Tables 2–3) and **ST UM2505 Rev 4** (Nucleo CN7/CN10, Table 16). MCU pin functions were checked against **ST STM32_open_pin_data** (the CubeMX database). The full evidence is in `Rig_Connection_Verification.md`.

### Recommended overall order
§0 → §1 (boards, including the header-orientation check) → §2 (mechanical) → §5 (power harness and BOOSTXL alone, **no logic wires yet**) → §6 (CubeMX project) → **T0 pin walk (Nucleo alone)** → §3 (logic wiring) → §4 (continuity) → T1 … T16.

---

## Safety rules (read before anything is plugged in)

1. **Power never goes on the breadboard.** The 14 AWG harness (P01–P06) and motor wires (P07–P09) go directly between the PSU, fuse, perfboard bus node and BOOSTXL.
2. **Never connect BOOSTXL J3.1 (its own 3.3 V) to the Nucleo 3V3.** The two boards share GND only.
3. Bench PSU: **never above 25.2 V**. Current limit in steps: 0.1 A → 1 A → 3 A → 5 A, only when the test says so. BOOSTXL maximum is 15 A; this rig stays at **10 A or less**.
4. The 5010 winding is 0.05–0.2 Ω. In open-loop voltage mode, never command more than **0.5 V** of phase voltage. The simulation (`rig_sim.py`, T9) shows that 1 V gives about 9 A of phase current and pushes a 12 V / 1 A supply into current limit and the driver into under-voltage lockout.
5. The motor is clamped to the base plate before it ever spins.
6. **Scope probe grounds go to rig GND only** (Nucleo GND / BOOSTXL GND / bus −). Never clip a probe ground to a motor phase or switch node.
7. Re-wire only with the PSU output **off** and the Nucleo USB unplugged.
8. Power-up order: **Nucleo USB first** (firmware holds ENABLE low), then the PSU. Power-down order is the reverse. Never power the BOOSTXL while logic wires connect it to an **unpowered** Nucleo. Its 3.3 V pull-ups and current-sense outputs would back-feed the Nucleo through the pin protection diodes.
9. Keep a hand near the PSU output button for every motor test.

---

## 0. Before you start

### 0.1 Tools
- Multimeter (continuity and DC volts)
- 4-channel oscilloscope with four 10× probes
- Bench PSU (R14), soldering station, flux, solder
- Milliohm/LCR meter (optional, for test T10)
- Labels or masking tape for the wire IDs

### 0.2 Software (install and open each once)
| Software | Use |
|---|---|
| STM32CubeIDE (includes CubeMX) | Project, code, build, debug |
| STM32CubeProgrammer | Read the device ID, flash, erase, option bytes |
| Serial terminal (PuTTY / Tera Term / CubeIDE console) | ST-LINK virtual COM port, 921 600 8N1 |
| Python 3 + `pip install python-can pyserial` | CAN tests, logging |
| Linux PC (recommended for CAN) | CANable 2.0 with candleLight shows up as `can0`. On Windows use the slcan firmware with python-can. |

### 0.3 Read these values from TI documents and write them in the record sheet (§9)
- **R_SH:** shunt resistor value, from the BOOSTXL-DRV8323RS schematic (TI SLVC690).
- **VSENVM divider:** both resistors on the VSENVM line, from the same schematic. You still calibrate the ratio with a DMM in T8.
- **DRV8323 register reset values:** from the DRV8323 datasheet register tables, used in T5.

### 0.4 Generate and print the wiring pack
```bash
python rig_wiring.py
```
All checks must print `[PASS]`. Print `rig_wire_list.csv` and the diagram.

---

## 1. Board preparation (no power)

| # | Board | Action | Check |
|---|---|---|---|
| 1.1 | U1 Nucleo | Jumper **JP5** in the ST-LINK 5 V position (default). The board is powered from the ST-LINK USB CN1. | LD3 lights when USB is plugged |
| 1.2 | U1 | Jumper **JP8 on [2-3]**: VREF+ = VDD (ADC reference = 3.3 V) | Measure VREF+ (CN10.7) ≈ VDD in T1 |
| 1.3 | U1 | Leave the default solder bridges: CN7.38 = PC0, CN7.36 = PC1, CN7.17 = PA15, LPUART1 (PA2/PA3) → ST-LINK VCP | Look up SB36, SB35, SB7, SB17/SB23 in UM2505 if unsure |
| 1.4 | U1 | Note: HSE crystal X3 = **24 MHz**. The Rev A PCB uses 8 MHz. | Used in §6 CubeMX |
| 1.5 | U2 BOOSTXL | Check the board is marked **DRV8323RS** (SPI variant). Nothing plugged into its headers. | — |
| 1.6 | U2 | Find the power screw terminal (VM +, GND −) and the motor terminal **J5 (A, B, C)** | Mark + with red tape |
| 1.7 | U3 AS5047P | Set the board for **3.3 V operation**: VDD joined to VDD3V3 (jumper or solder bridge, per the breakout's silkscreen) | Continuity VDD ↔ VDD3V3 |
| 1.8 | U4 SN65HVD230 | Check whether it has a 120 Ω resistor between CANH and CANL (measure with a DMM). If yes, the bus already has one end termination. | Write it in §9 |
| 1.8b | U4 | The chip's **Rs pin (pin 8) must read about 0 Ω to GND** (high-speed mode). If the module has 10 kΩ or more there (slope control), bridge it to GND, or run CAN at 500 kbit/s. | DMM: Rs ↔ GND |
| 1.10 | U1 header orientation | Identify pin 1 of CN7 and CN10 (square pad / silkscreen). Confirm with beep tests to a known GND (for example the USB connector shield): **CN7.8, CN7.19, CN7.20, CN7.22, CN10.9, CN10.20 = GND**. CN7.16 (3V3) is not GND. | All six beep. If not, your pin numbering is mirrored: stop and recount. |
| 1.11 | U2 header orientation | Identify J3.1 and J4.1 on the silkscreen. Beep to the power-terminal GND: **J3.4 and J4.2 = GND**; J3.1, J3.3 and J4.1 are not. | Both beep. If not, recount. |
| 1.9 | U5 CANable | Termination switch **ON**. Flash candleLight (Linux) or slcan (Windows) firmware. | Linux: `ip link` shows `can0` |

---

## 2. Mechanical setup

1. Fix U1 and U2 on the base plate with M3 standoffs, about 5–8 cm apart, headers facing each other.
2. Put the breadboard on the U1 side, away from the BOOSTXL power terminal and J5.
3. Clamp the motor M1. Glue the **diametric** magnet on the shaft end, centred (CA glue or epoxy; let it cure).
4. Mount U3 on the 3D-printed bracket: chip centred on the shaft axis, **1–2 mm** gap to the magnet.
5. Solder the regen kit on the perfboard (PB):
   - D1 MBR2045CT: pins 1 and 3 (anodes) joined; pin 2 / tab = cathode; on its heatsink.
   - C3, C4 (2200 µF 50 V) from BUS+ to BUS−. **Check polarity.**
   - D2 TVS from BUS+ (cathode, band side) to BUS− (anode).
   - Use 14 AWG wire on the bus. Keep C3, C4 and D2 within 3 cm of each other.

---

## 3. Wiring (PSU off, USB unplugged)

Do this only after §5 (harness and BOOSTXL alone) and T0 (pin walk) have passed. Wire one group at a time, in this order. After each wire, label both ends with its ID and tick it in `rig_wire_list.csv`. The power harness (row 9) is already built and tested in §5: leave the PSU output off.

| Order | Group | Wires | Notes |
|---|---|---|---|
| 1 | D Breadboard rails | W20 (CN7.16 3V3 → + rail), W21 (CN7.8 GND → − rail) | Red / black |
| 2 | A Driver PWM | W01–W06, W07 (GND) | Keep ≤ 10 cm. Twist the six PWM wires loosely with W07. |
| 3 | B Driver control / SPI | W08 (EN), W09a + W09b (nFAULT through breadboard node NFLT), W10–W13 | Place SW1 from NFLT to the GND rail |
| 4 | C Driver analog | W14–W17, W18 (GND) | Run them as a bundle **away** from the PWM bundle. **W17 only if the §5.6 VSENVM check passed.** W19 (POT) is optional. |
| 5 | E Encoder | W22–W25, W26 (3V3), W27 (GND) | Twist the encoder bundle; keep it away from the motor wires |
| 6 | F CAN | U4 on the breadboard; W28, W29 (rails), W30 (PA12 → CTX), W31 (PA11 ← CRX); W32/W33 twisted pair + W34 GND to U5 | |
| 7 | G Temperature | R1, C1 at node NTC_FET; R2, C2 at node NTC_MOT; W35, W36 to U1; W37–W40 to RT1 (FETs), RT2 (motor) | Tape the NTCs with Kapton |
| 8 | H Debug | W41: a short wire loop on CN7.32 (PA4) for scope CH4 | |
| 9 | P Power harness | P01–P06, with XT30s | Already built and tested in §5. PSU output stays off while wiring. |
| 10 | M Motor | P07–P09 into J5 A/B/C | Only from test T9 on |

Leave every BOOSTXL pin listed under "pins to leave open" in `Rig_Wiring_Reference.md` unconnected. That list includes J3.1.

---

## 4. Continuity check: test R1 (PSU off, USB unplugged)

Use the multimeter beep mode, pin to pin, as close to the IC side as you can reach.

| # | Measure | Expect |
|---|---|---|
| 4.1 | Every wire W01–W41: one end ↔ the other end | Beep (< 1 Ω). Tick `continuity_ok`. |
| 4.2 | Each PWM pin (CN10.23, .30, .21, .28, .33, .26) ↔ its neighbours | **No** beep (no shorts between strands) |
| 4.3 | Nucleo 3V3 (CN7.16) ↔ BOOSTXL J3.1 | **Open.** If it beeps, a wire is wrong. Stop. |
| 4.4 | Breadboard + rail ↔ − rail | > 1 kΩ (no short) |
| 4.5 | Nucleo GND ↔ BOOSTXL GND (J4.2, J3.4) | Beep |
| 4.6 | Perfboard BUS+ ↔ BUS− | Climbs from low to high as C3/C4 charge from the meter; never a steady short |
| 4.7 | D1 diode test: red probe F1 side, black probe BUS+ | 0.2–0.4 V. Reversed: open. |
| 4.8 | D2 diode test: red probe BUS−, black probe BUS+ | About 0.6–0.7 V (TVS forward). Reversed: open. |
| 4.9 | J5 A/B/C ↔ BUS− and ↔ BUS+ (motor not connected) | FET body diode one way, open the other way |
| 4.10 | NTC nodes (W35/W36 ends) ↔ GND rail | About 10 kΩ at 25 °C, through RT1 / RT2 |

**Pass:** every wire beeps, and 4.2–4.4 are open or high resistance. Sign §9.

---

## 5. Power harness test before the BOOSTXL sees power

1. Unplug P04 and P06 from the BOOSTXL terminal.
2. PSU: **12.0 V, current limit 0.1 A**. Enable the output.
3. Measure at the perfboard: BUS+ to BUS− = **11.5–11.8 V** (12 V minus the Schottky drop). PSU current ≈ 0 after the capacitors charge.
4. Reverse test: disable the output, swap the PSU leads at the PSU end, enable for 1 s. Bus reads about 0 V and the current is about 0, so D1 blocks. Restore the leads.
5. Disable the output. Connect P04 → VM+ and P06 → GND on the BOOSTXL. **No Dupont wires on the BOOSTXL headers yet.**
6. **BOOSTXL alone.** PSU 12.0 V, limit 0.1 A, enable the output, and measure with the DMM (black probe on BOOSTXL GND):

   | Point | Expect | If not |
   |---|---|---|
   | J3.1 | 3.3 V (BOOSTXL's own buck) | Board fault; stop |
   | J3.3 VSENVM | V₁₂. Compute the full-load value **V₁₂ × 25.2 / 12**: it must be **< 3.0 V** | **Do not connect W17.** Add a divider, or never exceed V_bus = 3.0 × 12 / V₁₂ |
   | J3.15 nFAULT | 3.3 V (on-board pull-up present) | Enable the PA6 pull-up in CubeMX (already in §6.2) |
   | J4.14 SDO | Write down the value. 3.3 V means an on-board pull-up; 0 V or floating means the PC11 internal pull-up does the job (§6.2). | — |
   | PSU current | Idle current, tens of mA. Write it in §9. | > 100 mA: stop, check for shorts |

   Disable the output when done.

---

## 6. Firmware project (STM32CubeIDE / CubeMX)

Create the project for **STM32G474RETx** (board: NUCLEO-G474RE) and set the following. Commit the `.ioc` to Git before writing code.

### 6.1 Clock (rig)
| Item | Setting |
|---|---|
| HSE | **Crystal 24 MHz** (Nucleo X3) |
| PLL | Source HSE, M = /6, N = ×85, R = /2 → **SYSCLK 170 MHz**; power regulator boost mode; flash latency 4 WS (CubeMX sets this) |
| APB1 / APB2 | 170 MHz (timers 170 MHz) |
| FDCAN kernel clock | PCLK1 = 170 MHz |

The Rev A PCB uses an 8 MHz crystal (M = /2). That is the **only** CubeMX difference between rig and PCB.

### 6.2 Peripherals
| Block | Setting |
|---|---|
| TIM1 | Centre-aligned mode 1, prescaler 0, **ARR = 2125** → 40 kHz PWM. CH1–CH3 PWM mode 1 + complementary outputs CH1N–CH3N. **Dead time 200 ns (DTG = 34).** Break input BKIN on PA6, **active low**. Off-state selection OSSR/OSSI on, idle state low. CH4: compare = ARR − 1, TRGO2 = OC4REF (ADC trigger once per PWM period, at the centre of the low-side on-time). |
| ADC1 + ADC2 | Dual mode, **injected simultaneous**, trigger TIM1_TRGO2. Rank 1: ADC1 IN1 (PA0, I_A) with ADC2 IN2 (PA1, I_B). Rank 2: ADC1 IN6 (PC0, V_BUS) with ADC2 IN4 (PA7, I_C). Sample time 12.5 cycles. Regular conversions (software trigger): ADC1 IN7 (PC1), IN8 (PC2). Run the self-calibration before enabling. |
| COMP3 / COMP1 / COMP2 | INP = PA0 / PA1 / PA7. INM = an internal DAC3 / DAC4 channel (CubeMX lists the allowed ones). Medium hysteresis. Output → TIM1 BKIN2 (internal). Enable only in test T12. |
| DAC3 / DAC4 | Internal connection (no pin), buffer off. Threshold set in T12. |
| DAC1 CH1 | Output on PA4 (W41) for the scope. CH2 is not used: PA5 drives LED LD2. |
| SPI1 (encoder) | Master, 16-bit, CPOL 0 / CPHA 1 (mode 1), MSB first, prescaler 32 → 5.3 MHz, NSS by software on PB6 |
| SPI3 (DRV8323) | Master, 16-bit, mode 1, MSB first, prescaler 256 → 0.66 MHz, NSS by software on PA15 |
| FDCAN1 | Classic CAN, 1 Mbit/s: **nominal prescaler 5, TSEG1 27, TSEG2 6, SJW 6** (82.4 % sample point, as in the 5010 plan §7.4) |
| LPUART1 | 921 600 baud 8N1 on PA2/PA3 (ST-LINK virtual COM port) |
| GPIO | PC8 output, **initial level low, pull-down on** (ENABLE). PA15 and PB6 outputs, initial level high. PC11 (SPI3 MISO): **pull-up on** (DRV8323 SDO). PA5 output (LD2). PC13 input (B1). PA6 = TIM1_BKIN, internal pull-up on. |
| CORDIC | On (sine/cosine) |
| NVIC | ADC1/2 (injected end of conversion) highest priority; FDCAN1 lower; LPUART lowest |
| Debug | SYS: **Serial Wire** (keeps PA13/PA14 for the ST-LINK). In the CubeIDE debug configuration, keep **SWV / trace OFF**: PB3 is wired to the ST-LINK SWO line, and enabling SWV takes PB3 away from the encoder clock (SPI1_SCK). Never plug a JTAG probe into the Nucleo CN4 connector: its JTDI line is PA15 (DRV nCS). |
| All other pins | Analog (CubeMX "Set unused pins to analog") |

### 6.3 Firmware modules to write, in this order
`hal_test.c` (T1), `as5047p.c` (T3), `can_test.c` (T4), `drv8323.c` (T5), `pwm.c` + break handling (T6/T7), `adc_cs.c` (T8), `openloop.c` (T9), `calib.c` (T10), `foc.c` + current PI (T11), `ocp.c` (T12), `vel_pos.c` (T13). Each test below needs only its own module plus the earlier ones.

### 6.4 Programming
1. Connect the Nucleo USB (CN1). LD1 (COM) and LD3 light.
2. CubeIDE: **Run → Debug As → STM32 C/C++ Application**. ST-LINK, SWD, "Connect under reset" if the board doesn't respond.
3. Or CubeProgrammer: ST-LINK → Connect → Open file (`.elf` / `.hex`) → **Download**, then Disconnect.
4. Open the serial terminal on the ST-LINK virtual COM port at 921 600 baud.
5. If the MCU locks up (pins misconfigured): CubeProgrammer, mode "Under reset", **Full chip erase**, then reflash.

---

## 7. Tests with inputs, expected outputs and pass criteria

Record every measured number in §9. **Do not start a test until the previous one passes.**

### T0 · Pin walk: proves every header pin is the MCU pin you think it is · Nucleo alone, USB only, **no logic wires**
- **Firmware:** configure each MCU pin used by the rig as a GPIO output:
  - PA8, PB13, PA9, PB14, PA10, PB15, PC8, PA6, PC10, PC12, PC11, PA15, PA0, PA1, PA7, PC0, PC1, PC2, PC3, PB3, PB4, PB5, PB6, PA12, PA11, PA4.
  - Every 3 s, drive exactly **one** pin high (all others low) and print its name and header position on the virtual COM port, for example `PA8 -> CN10.23`.
  - Take the header positions from `Rig_Wiring_Reference.md` §2 (U1 table).
- **Check:** DMM black probe on GND, red probe on the printed header pin.
  - The printed pin reads **3.3 V**.
  - Its two neighbours read **0 V**.
  - Go through the whole list.
- **Pass:** every pin matches. This catches a mirrored header count, a wrong solder bridge (for example CN7.38 not being PC0) or a damaged pin, before anything is connected to them.
- Reflash the normal test firmware afterwards. Never run the pin walk with the BOOSTXL wired: it would drive PWM inputs and ENABLE.

### T1 · Nucleo alone (guide R2) · USB only, PSU off
- **Input:** firmware blinks LD2 (PA5) at 2 Hz and prints `hello`, the device ID and `SystemCoreClock` every second.
- **Expected:**
  - LD2 blinks.
  - The terminal shows **device ID 0x469** (STM32G47x/48x; CubeProgrammer shows the same) and **170000000**.
  - Pressing B1 (PC13) prints `button`.
- **Measure:** VREF+ (CN10.7) ≈ 3.3 V; + rail ≈ 3.3 V.
- **Pass:** all of the above.

### T2 · Rails and idle levels · USB only
| Point | Expected |
|---|---|
| Breadboard + rail | 3.25–3.35 V |
| PC8 (CN10.2, ENABLE) | 0 V (driver kept asleep) |
| PA15 (CN7.17), PB6 (CN10.17) | 3.3 V (chip selects idle high) |
| PA6 (CN10.13, nFAULT) | Undefined while the BOOSTXL is unpowered: its pull-up has no supply, so either level is acceptable here. PWM is off anyway. It must read 3.3 V in T5. |
| NTC nodes (PC1 / PC2) | 1.5–1.8 V at room temperature |

### T3 · Encoder (AS5047P) · USB only
- **Input:** SPI1 frames. Send `0x4001` (ERRFL), then `0xFFFC` (DIAAGC), then `0xFFFF` (ANGLECOM) repeatedly. Each answer arrives in the **next** frame; send `0xC000` (NOP) to fetch the last one.
- **Expected:**
  - ERRFL bits 2:0 = 0.
  - DIAAGC: LF (bit 8) = 1, COF (bit 9) = 0, MAGH (bit 10) = 0, MAGL (bit 11) = 0. AGC (bits 7:0) mid-range, never stuck at 0 or 255.
  - Received frames have bit 14 (error flag) = 0 and correct even parity.
- **Turn the shaft by hand:** ANGLECOM (bits 13:0) runs 0 → 16383 smoothly, wraps once per mechanical turn, changes direction with the shaft, and never jumps.
- **Pass:** 100 turns logged with no parity or error-flag frames.
- **If it fails:** MAGH set → magnet too close; MAGL set → too far; COF set → magnet off-centre.

### T4 · CAN link · USB only
- **Input, step 1:** FDCAN1 in internal loopback mode. Send ID 0x123 and receive it back.
- **Input, step 2:** normal mode. The firmware sends ID 0x100 with a counter every 100 ms. On Linux:
  ```bash
  sudo ip link set can0 type can bitrate 1000000
  sudo ip link set can0 up
  candump can0
  ```
  Then send to the rig with `cansend can0 101#DEADBEEF`.
- **Windows:**
  ```python
  import can
  bus = can.Bus(interface="slcan", channel="COM7", bitrate=1000000)
  print(bus.recv(1))
  ```
- **Expected:** candump shows 0x100 every 100 ms with an incrementing counter; the firmware prints the received 0x101 frame. Error counters (TEC/REC) stay 0.
- **Measure (power off):** CANH ↔ CANL ≈ **60 Ω** (two 120 Ω terminations in parallel).
- **Pass:** 10 000 frames with no error frames.

### T5 · Driver power and DRV8323 SPI (guide R3) · PSU 12 V, limit 0.1 A, no motor
- **Power-up:** USB first (ENABLE low), then the PSU output. PSU current: write down the idle value (tens of mA). BOOSTXL J3.1: measure **3.3 V** (its own buck). **Measure only, never connect.**
- PA6 (nFAULT) now reads **3.3 V**.
- **Input:**
  1. Set ENABLE high (PC8), wait 1 ms.
  2. Read registers 0x00–0x06 with read words `0x8000, 0x8800, 0x9000, 0x9800, 0xA000, 0xA800, 0xB000`.
  3. Clear faults: write Driver Control with CLR_FLT (bit 0) = 1.
  4. Read 0x00 and 0x01 again.
- **Expected:**
  - Fault Status 1 and 2 read **0x000** (bits 10:0) after CLR_FLT.
  - Registers 0x02–0x06 match the datasheet reset values.
  - Driver Control PWM_MODE (bits 6:5) = 00 (6× PWM).
- **Write test:** write CSA Control with a new gain, read it back, then restore the value. A write word is `(addr << 11) | data`. Example: CSA Control (0x06) with VREF_DIV = 1, gain 40, SEN_LVL = 11 → data 0x2C3 → word **0x32C3**.
- **Choosing the CSA gain:** keep the range above 15 A, so G ≤ 1.65 V / (R_SH × 15 A). Keep the reset-value gain until R_SH is known.
- **Pass:** every read is stable over 100 reads, writes read back correctly, and no fault bits are set.

### T6 · Break input and E-stop · PSU 12 V, 0.1 A, no motor
- **Input:** start PWM at 10 % duty (from T7 firmware) with ENABLE high. Press **SW1**.
- **Expected:**
  - PA6 goes to 0 V.
  - All six TIM1 outputs drop to their idle state (low) **immediately** (scope CH1 on CN10.23 PA8).
  - The TIM1 break flag (BIF) is set and the firmware prints `BREAK`.
  - PWM does **not** restart by itself when SW1 is released; restart only with a command.
- **Pass:** the outputs go idle within 1 µs of PA6 falling (scope: CH1 PA8, CH2 PA6).

### T7 · PWM without motor (guide R4) · PSU 12 V, 0.1 A
- **Input:** 40 kHz centre-aligned PWM, duty 10 %, then 50 %, then 90 %, on all three phases. ENABLE high.
- **Scope at the Nucleo pins:**
  - CH1 PA8 (CN10.23) and CH2 PB13 (CN10.30): complementary, period 25.0 µs, **dead time ≈ 200 ns** at both edges, no overlap.
  - Repeat for phases B (CN10.21 / CN10.28) and C (CN10.33 / CN10.26).
- **Scope at J5 (probe ground on BUS−):** each phase switches 0 ↔ 12 V at the set duty, and the edges ring less than 3 V.
- **Expected:** PSU current is only the idle value (no load), nothing gets warm (touch-test the FETs after 1 minute), and no DRV8323 fault bits.
- **Pass:** all of the above for all three phases.

### T8 · Current-sense zero and bus voltage (guide R5) · PSU 12 V, 0.1 A, gates idle
- **Input, step 1:** ENABLE high, PWM off (MOE = 0). Average 1000 ADC samples on PA0, PA1, PA7.
- **Expected:** each reads near mid-scale. Mid-scale is the BOOSTXL VREF/2 converted with the Nucleo 3.3 V reference, about **2048 ± 60 counts**. Noise under ±5 counts after averaging.
- **Input, step 2:** run CSA_CAL (set CSA_CAL_A/B/C, sample, clear). Store each phase offset V_off in firmware.
- **Input, step 3:** read PC0 (VSENVM). Measure BUS+ with the DMM and compute **k = V_bus(DMM) / V_adc**. Check at 12 V and at 18 V; the two k values must agree within 1 %. Store k.
- **Expected:** the firmware's V_bus agrees with the DMM within 2 %.
- **Formulas:**
  - Phase current: I = (V_adc − V_off) / (G × R_SH)
  - Bus voltage: V_bus = V_adc × k
  - NTC: R = 10 kΩ × V / (3.3 − V); T = 1 / (1/298.15 + ln(R/10 kΩ)/3950) − 273.15 °C
- **Pass:** offsets stored, V_bus within 2 %, NTC readings within 3 °C of room temperature.

### T9 · First spin, open loop (guide R7) · motor connected (P07–P09), PSU 12 V, limit 1 A
- **Input:**
  - Voltage-mode SVPWM with V_d = 0.
  - **V_q = 0.3 V** at first. The electrical angle ramps at 1 Hz (0.14 turn/s for 7 pole pairs).
  - Raise V_q slowly, **never above 0.5 V** (≈ 5 A of phase current; see `rig_sim.py` T9).
- **Expected:**
  - Smooth rotation with no cogging jumps; PSU current under 1 A (the PSU must never go into constant-current mode).
  - The encoder advances **2340.6 counts per electrical turn** (16384 / 7).
  - After 7 electrical turns the shaft has made exactly one mechanical turn.
- **Record:** the motor direction for a positive angle ramp versus the encoder count direction (same or opposite).
- **Pass:** 10 mechanical turns each way, smooth, current < 1 A, pole pairs = 7.

### T10 · Auto-calibration (guide R8) · PSU 12 V, limit 2 A
| Step | Input | Expected / record |
|---|---|---|
| R | Lock the rotor at θ_e = 0 with I_d = 2 A, I_q = 0 (current from the T8 formula). R = V_d / I_d. | R_phase. Compare with a milliohm meter (line-to-line ÷ 2): within **10 %**. |
| L | Apply a V_d step of 0.5 V and fit the current rise time constant τ. L = R × τ. Or inject a small square wave and use the current ripple. | L_phase (typically tens of µH for a 5010) |
| Offset | Lock at θ_e = 0 with I_d = 2 A, wait 1 s, read the encoder → electrical offset. Repeat at θ_e = 90°, 180°, 270°. | The four readings are 90° (585 counts) apart, within 2° electrical |
| Direction | Use the T9 result | Sign stored |
| Pole pairs | Count from T9 | 7 |

**Pass:** R within 10 % of the meter; offset repeatable within 2° electrical over 3 runs.

### T11 · Current control (guide R9) · rotor clamped, PSU 24 V, limit 3 A
- **Gains:** bandwidth ω_c = 2π × 1 kHz; K_p = L × ω_c; K_i = R × ω_c (pole-zero cancellation).
- **Input:**
  - I_q steps 0 → 1 A → 3 A → 0.
  - The firmware writes I_q to DAC1 (PA4, W41).
  - Scope CH4 on W41; CH1 on a spare GPIO toggled in the ISR (probe **CN10.4, PC6**, directly on the header pin).
- **Expected:**
  - I_q follows each step in about **0.35 ms** (10–90 %) with less than 20 % overshoot.
  - I_d stays at 0 ± 0.2 A.
  - The ISR pulse width on PC6 is **under 15 µs** (fits in the 25 µs period).
  - PSU current stays below the limit.
- **Pass:** all of the above, and 5 minutes at 3 A with FET NTC < 60 °C.

### T12 · Hardware overcurrent trip · rotor clamped, PSU 24 V, limit 3 A
- **Input:**
  1. Set the DAC3/DAC4 thresholds to V_off + G × R_SH × **2 A**.
  2. Enable COMP1–3 → BKIN2.
  3. Command an I_q step to 3 A.
- **Expected:**
  - The gates switch off as the current crosses 2 A; the scope shows a phase (J5) collapsing **within 2 µs** of the current-sense rise.
  - The firmware latches OVERCURRENT_HW, and PWM stays off until a clear command.
- **Restore:** set the threshold back to its working value (for example 0.9 × the measurable range).
- **Pass:** trip time < 2 µs, latched, no restart.

### T13 · Velocity and position (guide R10) · free shaft, PSU 24 V, limit 3 A
- **Input:**
  - Velocity commands 0 → 20 → 100 → −100 → 0 rad/s.
  - Position steps of 90°, then a 0.5 Hz ±90° sine.
- **Expected:** smooth tracking, no encoder error flags, no audible grinding, and the bus stays under 28 V during stops (check with the scope on BUS+).
- **Pass:** position error under 0.5° at standstill; velocity ripple under 5 % at 100 rad/s.

### T14 · Regeneration check · free shaft, PSU 24 V
- **Input:** spin at 100 rad/s, then command 0 with maximum deceleration.
- **Expected:** BUS+ (scope CH1, probe ground on BUS−) rises less than 3 V above the PSU setting, and D1 blocks current back into the PSU.
- **Pass:** peak under 28 V. If it is higher, lower the deceleration or add the firmware V_bus limit (brake by raising I_d).

### T15 · CAN control and timing · PSU 24 V
- **Input:** the PC sends MIT-mode or command frames at 1 kHz over the CANable.
- **Expected:** every command answered, no missed frames in `candump`, the loop-time jitter measured on PC6 stays under 2 µs, and a CAN timeout (stop the PC sender) puts the joint into damping, then idle.
- **Pass:** 60 s at 1 kHz with 0 errors; timeout behaviour correct.

### T16 · Thermal soak · rotor clamped, PSU 24 V, limit 5 A
- **Input:** I_q = 4 A for 10 minutes.
- **Expected:** RT1/RT2 readings track a thermocouple within 3 °C; FETs < 80 °C; motor < 80 °C.
- **Pass:** stable temperatures and no derating trips. This is the rig's maximum load test.

---

## 8. Pin input / output summary (what each pin should show)

| MCU pin (header) | Dir | Signal | Normal value / range |
|---|---|---|---|
| PA8, PA9, PA10 (CN10.23, .21, .33) | Out | High-side PWM | 0 / 3.3 V, 40 kHz |
| PB13, PB14, PB15 (CN10.30, .28, .26) | Out | Low-side PWM | Complement of the above, 200 ns dead time |
| PC8 (CN10.2) | Out | ENABLE | 0 V at reset, 3.3 V when running |
| PA6 (CN10.13) | In | nFAULT / BKIN | 3.3 V normal; 0 V on driver fault, SW1, or BOOSTXL unpowered |
| PC10, PC12 (CN7.1, .3) | Out | SPI3 SCK / MOSI | Bursts of 16 clocks |
| PC11 (CN7.2) | In | SPI3 MISO (DRV SDO) | Data during frames |
| PA15 (CN7.17) | Out | DRV nCS | 3.3 V idle, 0 V during a frame |
| PA0, PA1, PA7 (CN7.28, .30, CN10.15) | In (analog) | I_A, I_B, I_C | ≈ 1.65 V at 0 A; 0–3.3 V |
| PC0 (CN7.38) | In (analog) | V_BUS sense | V_bus / k |
| PC1, PC2 (CN7.36, .35) | In (analog) | NTC_FET, NTC_MOT | ≈ 1.65 V at 25 °C; falls when hot |
| PB3, PB5 (CN10.31, .29) | Out | SPI1 SCK / MOSI | Bursts |
| PB4 (CN10.27) | In | SPI1 MISO | Encoder data |
| PB6 (CN10.17) | Out | Encoder CSn | 3.3 V idle |
| PA12 (CN10.12) | Out | FDCAN1 TX | 3.3 V idle (recessive) |
| PA11 (CN10.14) | In | FDCAN1 RX | 3.3 V idle |
| PA4 (CN7.32) | Out (analog) | DAC1 debug | 0–3.3 V |
| PA2 / PA3 | Out / In | LPUART1 (ST-LINK VCP) | No wire; 921 600 baud |
| PA5 | Out | LD2 LED | — |
| PC13 | In | B1 button | Low when pressed |
| PC6 (CN10.4) | Out | ISR timing pulse (probe directly) | Pulse width = ISR time |

---

## 9. Record sheet (fill in, sign, keep in Git)

| Item | Value | Date / initials |
|---|---|---|
| R_SH (from SLVC690) | ______ mΩ | |
| CSA gain used | ______ V/V | |
| VSENVM ratio k (T8) | ______ | |
| U4 has an on-board 120 Ω? | yes / no | |
| CANH–CANL resistance | ______ Ω | |
| BOOSTXL idle current at 12 V (T5) | ______ mA | |
| CS offsets A / B / C (T8) | ______ / ______ / ______ counts | |
| R_phase: firmware / meter (T10) | ______ / ______ mΩ | |
| L_phase (T10) | ______ µH | |
| Encoder electrical offset (T10) | ______ counts | |
| Direction sign (T9) | + / − | |
| Pole pairs | 7 | |
| ISR time (T11) | ______ µs | |
| OCP trip time (T12) | ______ µs | |
| Peak V_bus on stop (T14) | ______ V | |
| T1–T16 passed | ☐ T1 ☐ T2 ☐ T3 ☐ T4 ☐ T5 ☐ T6 ☐ T7 ☐ T8 ☐ T9 ☐ T10 ☐ T11 ☐ T12 ☐ T13 ☐ T14 ☐ T15 ☐ T16 | |

---

## 10. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| CubeProgrammer cannot connect | PA13/PA14 reconfigured by firmware, or board in low power | Connect "under reset"; full chip erase |
| `SystemCoreClock` is not 170 MHz | HSE set to 8 MHz (PCB value) | Set HSE = 24 MHz on the rig (§6.1) |
| DRV8323 reads 0x0000 or 0xFFFF | ENABLE low, VM off, wrong SPI mode, or nCS not toggling | Check PC8 = 3.3 V, VM present, CPHA = 1, nCS low only during the frame |
| Fault bit UVLO / CPUV set | VM too low, or PSU in current limit | Raise the PSU limit slightly; VM ≥ 8 V; then CLR_FLT |
| PA6 low with everything powered | DRV fault latched, or SW1 stuck | Read Fault Status 1/2, then CLR_FLT; check SW1 |
| Phase-current offsets far from 2048 | VREF+ jumper (JP8) wrong, or W14–W16 swapped | JP8 on [2-3]; recheck W14–W16 against J3.16/.14/.12 |
| Current noisy or jumping | Analog wires next to the PWM bundle, or GND W18 missing | Separate the bundles; check W07/W18 |
| Encoder jumps | Magnet off-centre or wrong type (axial), or motor wires too close | Use a diametric magnet, re-centre it, re-route the wires |
| Encoder dead only while debugging | SWV/trace is enabled, so PB3 is switched to SWO | Turn SWV off in the debug configuration |
| CAN works at 500 kbit/s but not at 1 Mbit/s | SN65HVD230 Rs pin in slope-control mode | Tie Rs to GND (§1.8b) |
| Motor buzzes but doesn't turn in T9 | Phase wire loose, or V_q too low | Check P07–P09; raise V_q in 0.1 V steps (≤ 0.5 V) |
| Motor runs backwards in closed loop | Direction sign wrong | Repeat T9/T10 direction step |
| CAN error frames or no traffic | Bitrate mismatch, missing termination, or TX/RX swapped | Both sides at 1 Mbit/s; measure 60 Ω; check W30 → CTX, W31 ← CRX |
| Bus voltage spikes on stop | Too much deceleration for the bench PSU | Lower the deceleration; check D1/C3/C4/D2; enable the V_bus limit |
| BOOSTXL very hot at low current | Shoot-through: dead time 0 or PWM polarity wrong | Check the T7 dead time on the scope at the Nucleo pins |
