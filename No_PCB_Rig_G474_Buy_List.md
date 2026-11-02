# No-PCB test rig (STM32G474): buy list

**iGL-FOC-1 · breadboard / no-PCB stage · reviewed 1 Nov 2026**
Source: tab *No-PCB Rig (G474)* in `ODrive_Breadboard_Procurement.xlsx`. Wiring: build guide §6B.2. Tests: §6B.3 (R1–R10).

The rig uses the same chips and pin map as the Rev A PCB (NUCLEO-G474RE + BOOSTXL-DRV8323RS + AS5047P + CAN on PA11/PA12), so all firmware carries over to the board unchanged.

## 1. Order online (not stocked in local shops)

| # | Component | Role in the rig | Qty | Replaces team row | Source | Price (₹/unit) | Notes |
|---|---|---|---|---|---|---|---|
| R1 | NUCLEO-G474RE | STM32G474RE Nucleo-64, built-in ST-LINK. Same MCU and pin map as the Rev A PCB, so firmware carries over. | 2 pcs | B1 (NUCLEO-F446RE) | DigiKey / Mouser / element14 India | est. ₹2,000–2,800 | One spare. USB is Micro-B. |
| R2 | TI BOOSTXL-DRV8323RS | DRV8323RS + 6 FETs + 3 shunts, 6–54 V, 15 A cont. Same driver chip as Rev A. | 2 pcs | B2 (BOOSTXL-DRV8301) | DigiKey / Mouser / TI store | est. ₹3,500–5,500 | One spare: a burnt board must not stop the work. Read the shunt value from TI SLVC690 and set it in firmware. |
| R3 | AS5047P breakout board | 14-bit SPI magnetic encoder, 3.3 V. CLK PB3, MISO PB4, MOSI PB5, CSn PB6. | 2 pcs | B3 + B23 (AMT102-V + cable) | DigiKey / Mouser (AS5047P-TS_EK_AB) or a good clone | est. ₹800–2,500 | Same encoder as Rev A. |
| R4 | CANable 2.0 USB-CAN adapter | PC side of the CAN bus; candleLight/gs_usb (SocketCAN) or slcan firmware. 120 Ω switch on board. | 1 pcs | new | Robu.in / Tindie | est. ₹2,000–4,000 | Check which USB connector your unit has (row R24). |

## 2. Local market (CTC Secunderabad, Robu.in, Evelta)

| # | Component | Role in the rig | Qty | Replaces team row | Source | Price (₹/unit) | Notes |
|---|---|---|---|---|---|---|---|
| R5 | BLDC motor 5010, ~280 KV | Target motor. 200–300 KV suits the 24 V bus. | 2 pcs | B5 (qty 1 → 2) | Robu.in / iFlight / T-Motor dealers | ₹2,239 | One spare. Prefer ~280 KV if available. |
| R6 | Diametric magnets Ø6×2.5 or Ø8×3 mm, N35 | On the motor shaft, 1–2 mm under the AS5047P. | 4 pcs | new | Robu.in / local magnet shop | est. ₹30–80 each | Must be DIAMETRIC (not axial). |
| R7 | SN65HVD230 CAN transceiver module | 3.3 V node transceiver. TX → PA12, RX → PA11 (FDCAN1), NOT PB8/PB9 (PB8 is BOOT0 on the G474). | 2 pcs | B4 (qty 1 → 2) | Robu.in / Evelta | ₹291 | Check if the module already has a 120 Ω resistor. |
| R8 | 120 Ω resistors + twisted-pair cable 2 m | One 120 Ω at each bus end (the CANable switch counts as one). | 1 set | new | CTC Secunderabad / Robu.in | est. ₹50–100 | Resistors can come from the B9 kit. |
| R9 | Schottky diode MBR2045CT or MBR3045 (TO-220) | Regen kit: in the supply + line, blocks braking energy from flowing back into the PSU. Stands in for the Rev A LM74700 ideal diode. Tie both package diodes in parallel. | 1 pcs | Validation tab "MBR2045 REMOVED" → restored | CTC Secunderabad / Robu.in | est. ₹40–80 | Needed whenever a bench PSU powers the rig. |
| R10 | TO-220 heatsink | For the Schottky diode. | 1 pcs | B20 (qty 2 → 1) | CTC Secunderabad / Robu.in | est. ₹20–50 |  |
| R11 | 2200 µF 50 V low-ESR electrolytic capacitor | Regen kit: on the bus after the Schottky, absorbs braking energy. | 2 pcs | new | CTC Secunderabad / Robu.in | est. ₹40–80 each | 50 V rating, not 35 V. |
| R12 | TVS diode SMCJ28A (or through-hole 1.5KE33A) | Regen kit: clamps bus spikes (about 45 V). Across the bus at the BOOSTXL VM input. | 2 pcs | new | Robu.in / DigiKey / CTC | est. ₹10–30 each | One spare. |
| R13 | Perfboard, double-sided 7 × 9 cm | Mounts the regen kit (Schottky, capacitors, TVS) with thick wire. Power never on the breadboard. | 1 pcs | P9 (new job) | Robu.in | ₹59 |  |
| R14 | Bench PSU 24 V, ≥ 10 A, current-limited | Rig supply. Current limit: 0.1 A (SPI/PWM), 1 A (first spin), 3–5 A (current control). | 1 pcs | P1 | Robu.in (Wanptek WPS3010H) | ₹8,139 | Never above 25.2 V for this project. |
| R15 | XT30 connector pairs | Supply harness. | 3 pairs | P2 (qty 2 → 3) | Robu.in / CTC | ₹55 |  |
| R16 | Inline ATO fuse holder + 10 A and 15 A fuses | In the supply + lead. 10 A for the rig; 25 A only for the later battery harness. | 1 set | P3 | CTC / auto-parts shop | ₹11 | Holder price not in the team sheet. |
| R17 | Latching E-stop (mushroom) | Switch the PSU AC side or its output-enable, not 10 A DC directly. | 1 pcs | P4 | Robu.in | ₹200 |  |
| R18 | Silicone wire 14 AWG red + black | Supply leads. | 2 m (pair) | P5 | Robu.in | ₹169.10 |  |
| R19 | Silicone wire 18 AWG, 3 m red + 3 m black | Motor phases and regen-kit wiring. | 1 set | P6 | Robu.in | ₹320.15 |  |
| R20 | 3.5 mm bullet connectors (male + female) | Motor phase connections; swap motors quickly. | 10 pairs | P7 (qty → 10 pairs) | Robu.in / CTC | est. ₹15–30 per pair |  |
| R21 | Heat-shrink assortment | Insulation and strain relief. | 1 kit | P10 | Robu.in | ₹398 |  |
| R22 | Dupont jumpers, mostly F-F, 10 cm | Nucleo and BOOSTXL headers are both male, so F-F. Keep under 10 cm; twist each PWM wire with a GND wire. | 1 kit | P8 | Robu.in / CTC | est. ₹100–200 |  |
| R23 | USB A to Micro-B data cable | NUCLEO-G474RE programming and virtual COM port (PA2/PA3). | 2 pcs | B22 (qty 1 → 2) | Robu.in | ₹69 | Data cable, not charge-only. |
| R24 | USB cable for the CANable | Match the CANable 2.0 connector (USB-C or Micro-B, depends on the unit). | 1 pcs | new | Robu.in / local | est. ₹100–200 |  |
| R25 | Breadboard 830-point (MB-102) | Logic only: encoder and CAN module signal distribution. Never motor or bus power. | 1 pcs | B8 | Robu.in | ₹45 |  |
| R26 | Male pin header strip 2.54 mm 1×40 | Breakout and test pins. | 2 pcs | B24 (qty 1 → 2) | Robu.in / CTC | est. ₹10–20 |  |
| R27 | 10 kΩ NTC thermistor B3950 | Motor and FET temperature logging; taped with Kapton. | 5 pcs | B12 (qty 3 → 5) | Robu.in | ₹30 | Filter with 100 nF from the B10 kit (2.2 µF row B11 dropped). |
| R28 | Kapton tape | Fixes NTCs to FETs / motor. | 1 roll | B13 | Robu.in / CTC | est. ₹100–250 |  |
| R29 | Resistor kit 1/4 W metal film | General use, 120 Ω terminations, pull-ups. | 1 kit | B9 | Robu.in | ₹175 |  |
| R30 | Ceramic capacitor kit (2 pF – 100 nF) | Decoupling and filters. | 1 kit | B10 | Robu.in | ₹150 |  |
| R31 | Base plate (acrylic / MDF) + M3 standoffs + 3D-printed motor clamp | Both boards on one plate; the motor must never move freely. | 1 set | new (mechanical) | CTC / T-Works / in-house printer | est. ₹300–800 | Tick if made in-house. |

## 3. Optional (torque and temperature tests)

| # | Component | Role in the rig | Qty | Replaces team row | Source | Price (₹/unit) | Notes |
|---|---|---|---|---|---|---|---|
| R32 | 5 kg load cell + HX711 + 100 mm arm | Torque test: measure Kt (Nm/A). | 1 set | new | Robu.in / Robokits | est. ₹400–900 |  |
| R33 | K-type thermocouple + MAX31855 module | Motor winding temperature during current tests. | 1 set | new | Robu.in | est. ₹300–600 |  |

## 4. Cost so far

- Priced lines (team-sheet prices): **₹15,348**, of which ₹8,139 is the bench supply (skip it if the lab has one).
- Lines still to price: **18** (marked "est." with a planning range from build guide §6B).
- Planning estimate: about ₹20k–30k for section 1 and ₹8k–12k for section 2, not counting the bench supply.

## 5. Dropped from the team's ODrive-clone list

| Team row | Item | Why |
|---|---|---|
| B1 | NUCLEO-F446RE | Replaced by NUCLEO-G474RE (R1), the same MCU as the Rev A board |
| B2 | BOOSTXL-DRV8301 | Replaced by BOOSTXL-DRV8323RS (R2), the same driver as the Rev A board |
| B3, B23 | AMT102-V encoder + cable | Replaced by AS5047P (R3) |
| B6 | CP2102 USB-serial | The Nucleo's built-in virtual COM port (PA2/PA3) does this job |
| B7 | Micro-USB breakout | Native USB isn't used in our design |
| B11 | 2.2 µF capacitors | The NTC filter uses 100 nF from the capacitor kit |
| B14–B19 | Brake chopper (LM5109B, IRF3205, 2 Ω 50 W, UF4007, LM2596HV, adapter) | Deferred; the regen kit (R9–R13) protects the rig |
| B21 | USB Mini-B cable | The NUCLEO-G474RE has a Micro-B port |

## 6. Rules to follow when wiring

- Power goes: supply + → fuse (10 A) → E-stop → Schottky → bus node (2 × 2200 µF + TVS) → BOOSTXL VM. **Power never goes on the breadboard.**
- Raise the current limit in steps: 0.1 A for SPI and PWM tests (no motor) → 1 A for the first spin → 3–5 A for current control. Never set the supply above 25.2 V.
- The 5010 winding is only 0.05–0.2 Ω, so in voltage mode never apply more than about 1 V.
- Share GND between the Nucleo and the BOOSTXL, but **don't join their 3.3 V supplies**.
- Keep Dupont jumpers under 10 cm, twist each PWM wire with a GND wire, and keep motor wires away from the encoder.
- Clamp the motor to the base plate. The magnet must be diametric, centred 1–2 mm under the AS5047P.
- CAN: the CANable's 120 Ω on, plus 120 Ω at the far end, so exactly two terminations.
