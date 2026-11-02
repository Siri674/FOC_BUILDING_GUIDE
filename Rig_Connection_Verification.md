# No-PCB rig: connection verification report

**iGL-FOC-1 · NUCLEO-G474RE + BOOSTXL-DRV8323RS · double-checked 1 Nov 2026**

## Verdict

All **51 connections are correct on paper**: each one passed independent checks against the manufacturers' own data (§1). The review found **no wrong pin**. It added **7 safety and robustness changes** (§4).

Eight points can only be confirmed on the real hardware with a multimeter (§5). They are built into the bring-up procedure as steps 1.8b, 1.10, 1.11, 5.6 and T0. Do them before any logic wire is plugged in.

## 1. How it was checked

| # | Check | Source of truth | Result |
|---|---|---|---|
| 1 | Every BOOSTXL J3/J4 pin name in `rig_wiring.py` compared with TI's table, parsed from the PDF text | TI SLVUB01C Rev C, Tables 2 and 3 | 40 / 40 pins match |
| 2 | Every Nucleo CN7/CN10 pin name compared with ST's table, parsed from the PDF text | ST UM2505 Rev 4, Table 16 | 76 / 76 pins match |
| 3 | Default solder bridges behind every used header pin | UM2505 solder-bridge tables + §8 I/O assignment | CN7.38 = PC0 and CN7.36 = PC1 (PA15/PB9 bridges off); CN7.17 = PA15; PA2/PA3 → ST-LINK VCP; PB3 also on ST-LINK SWO; PA15 also on CN4 JTDI (external tools only) |
| 4 | Every MCU pin really has the peripheral signal its net needs (TIM1 channels, BKIN, SPI1/3, FDCAN1, ADC channels, COMP inputs, DAC) | ST STM32_open_pin_data (the CubeMX database): STM32G474R(B-C-E)Tx + GPIO-STM32G47x_gpio_v1_0 | 26 / 26 nets OK. Now an automatic check in `rig_wiring.py`; tested by forcing W16 → PB1 and W02 → PB12 (both caught) |
| 5 | Electrical review of every net: direction, levels, pull-ups, reset state, ground return, protection | DRV8323 / AS5047P / SN65HVD230 behaviour, rig power path | Table in §3; findings in §4 |
| 6 | Physical reach of every wire on the plate layout | `rig_physical_layout.py` | 0 wires over their length limit |
| 7 | All `rig_wiring.py` rule checks | — | ALL PASS |

## 2. Rule checks (from rig_wiring.py)

| Result | Check |
|---|---|
| PASS | Wire IDs are unique |
| PASS | Every Nucleo pin matches UM2505 Table 16 and the design pin map |
| PASS | Every BOOSTXL pin matches SLVUB01C Tables 2-3 |
| PASS | No header pin carries two Dupont wires |
| PASS | Every net has two or more endpoints |
| PASS | BOOSTXL J3.1 (its own 3.3 V) is not joined to the Nucleo 3V3 |
| PASS | No power or motor wire touches the breadboard |
| PASS | At least two GND wires between Nucleo and BOOSTXL (W07, W18) |
| PASS | Wire limits: PWM 10 cm, analog 15 cm, DRV control/SPI 20 cm (slow SPI, crosses the Nucleo) |
| PASS | Every MCU pin provides its peripheral signal (ST STM32_open_pin_data, STM32G474RxT) |

## 3. Every connection

✓ = matches the TI or ST source. The "MCU signal needed" column is checked against ST's pin database.

| Wire | From | To | Net | MCU signal needed | Electrical check | Result |
|---|---|---|---|---|---|---|
| W01 | U1 CN10.23 = PA8 (LQFP 42) ✓ | U2 J4.1 = INHA ✓ | PWM_AH | TIM1_CH1 ✓ | 3.3 V push-pull into a DRV8323 logic input (internal pull-down): the gate stays off while the MCU pin is high-Z in reset | PASS |
| W02 | U1 CN10.30 = PB13 (LQFP 35) ✓ | U2 J4.3 = INLA ✓ | PWM_AL | TIM1_CH1N ✓ | same as PWM_AH | PASS |
| W03 | U1 CN10.21 = PA9 (LQFP 43) ✓ | U2 J4.5 = INHB ✓ | PWM_BH | TIM1_CH2 ✓ | same as PWM_AH | PASS |
| W04 | U1 CN10.28 = PB14 (LQFP 36) ✓ | U2 J4.7 = INLB ✓ | PWM_BL | TIM1_CH2N ✓ | same as PWM_AH | PASS |
| W05 | U1 CN10.33 = PA10 (LQFP 44) ✓ | U2 J4.9 = INHC ✓ | PWM_CH | TIM1_CH3 ✓ | same as PWM_AH | PASS |
| W06 | U1 CN10.26 = PB15 (LQFP 37) ✓ | U2 J4.11 = INLC ✓ | PWM_CL | TIM1_CH3N ✓ | same as PWM_AH | PASS |
| W07 | U1 CN10.20 = GND (LQFP —) ✓ | U2 J4.2 = GND ✓ | GND | — | Shared logic ground. Motor current returns PSU− → BOOSTXL GND only; no motor current in the Duponts while the PSU output floats | PASS |
| W08 | U1 CN10.2 = PC8 (LQFP 40) ✓ | U2 J3.9 = ENABLE ✓ | DRV_EN | GPIO_Output ✓ | MCU output, pull-down set in CubeMX → driver asleep from reset until the firmware enables it | PASS |
| W09a | U1 CN10.13 = PA6 (LQFP 20) ✓ | BB NFLT | nFAULT_BKIN | TIM1_BKIN ✓ | Open-drain DRV output with a BOOSTXL pull-up to its 3.3 V; SW1 to GND is a safe short (mA only); TIM1 BKIN active low | PASS |
| W09b | BB NFLT | U2 J3.15 = nFAULT ✓ | nFAULT_BKIN | — | Open-drain DRV output with a BOOSTXL pull-up to its 3.3 V; SW1 to GND is a safe short (mA only); TIM1 BKIN active low | PASS |
| W10 | U1 CN7.1 = PC10 (LQFP 52) ✓ | U2 J3.13 = SCLK ✓ | DRV_SCK | SPI3_SCK ✓ | MCU output, 0.66 MHz; 20 cm is fine at this speed | PASS |
| W11 | U1 CN7.3 = PC12 (LQFP 54) ✓ | U2 J4.12 = SDI ✓ | DRV_SDI | SPI3_MOSI ✓ | MCU output → DRV SDI | PASS |
| W12 | U1 CN7.2 = PC11 (LQFP 53) ✓ | U2 J4.14 = SDO ✓ | DRV_SDO | SPI3_MISO ✓ | DRV output → MCU input with PC11 pull-up; check the on-board pull-up in §5.6 | PASS |
| W13 | U1 CN7.17 = PA15 (LQFP 51) ✓ | U2 J4.18 = nSCS/GAIN ✓ | DRV_nCS | GPIO_Output ✓ | MCU output, idle high; PA15 also reaches the CN4 JTDI pin (used only by external JTAG tools) | PASS |
| W14 | U1 CN7.28 = PA0 (LQFP 12) ✓ | U2 J3.16 = ISENA ✓ | ISENSE_A | ADC1_IN1, COMP3_INP ✓ | CSA output 0–3.3 V (BOOSTXL VREF = its 3.3 V) into the ADC + comparator input; within VDDA | PASS |
| W15 | U1 CN7.30 = PA1 (LQFP 13) ✓ | U2 J3.14 = ISENB ✓ | ISENSE_B | ADC2_IN2, COMP1_INP ✓ | same as ISENSE_A | PASS |
| W16 | U1 CN10.15 = PA7 (LQFP 21) ✓ | U2 J3.12 = ISENC ✓ | ISENSE_C | ADC2_IN4, COMP2_INP ✓ | same as ISENSE_A | PASS |
| W17 | U1 CN7.38 = PC0 (LQFP 8) ✓ | U2 J3.3 = VSENVM ✓ | VBUS_SNS | ADC1_IN6 ✓ | BOOSTXL divider output. **Must measure < 3.0 V at 25.2 V before connecting (§5.6)**: the divider ratio is not in the user guide | PASS |
| W18 | U1 CN7.22 = GND (LQFP —) ✓ | U2 J3.4 = GND ✓ | GND | — | Shared logic ground. Motor current returns PSU− → BOOSTXL GND only; no motor current in the Duponts while the PSU output floats | PASS |
| W19 | U1 CN7.37 = PC3 (LQFP 11) ✓ | U2 J3.11 = POT ✓ | POT_CMD | ADC1_IN9 ✓ | 0–3.3 V from the BOOSTXL pot (optional) | PASS |
| W20 | U1 CN7.16 = 3V3 (LQFP —) ✓ | BB +3V3 rail | +3V3 | — | Nucleo 3V3 feeds the encoder, CAN module and NTC dividers (< 100 mA total) | PASS |
| W21 | U1 CN7.8 = GND (LQFP —) ✓ | BB GND rail | GND | — | Shared logic ground. Motor current returns PSU− → BOOSTXL GND only; no motor current in the Duponts while the PSU output floats | PASS |
| W22 | U1 CN10.31 = PB3 (LQFP 56) ✓ | U3 CLK | ENC_SCK | SPI1_SCK ✓ | SPI1 mode 1 (AS5047P: CPOL 0, CPHA 1), 5.3 MHz; PB3 is also the ST-LINK SWO input (keep SWV off) | PASS |
| W23 | U1 CN10.27 = PB4 (LQFP 57) ✓ | U3 MISO | ENC_MISO | SPI1_MISO ✓ | AS5047P output at 3.3 V | PASS |
| W24 | U1 CN10.29 = PB5 (LQFP 58) ✓ | U3 MOSI | ENC_MOSI | SPI1_MOSI ✓ | MCU output | PASS |
| W25 | U1 CN10.17 = PB6 (LQFP 59) ✓ | U3 CSn | ENC_CS | GPIO_Output ✓ | MCU output, idle high, internal pull-up | PASS |
| W26 | BB +3V3 rail | U3 VDD3V3 | +3V3 | — | Nucleo 3V3 feeds the encoder, CAN module and NTC dividers (< 100 mA total) | PASS |
| W27 | BB GND rail | U3 GND | GND | — | Shared logic ground. Motor current returns PSU− → BOOSTXL GND only; no motor current in the Duponts while the PSU output floats | PASS |
| W28 | BB +3V3 rail | U4 3V3 | +3V3 | — | Nucleo 3V3 feeds the encoder, CAN module and NTC dividers (< 100 mA total) | PASS |
| W29 | BB GND rail | U4 GND | GND | — | Shared logic ground. Motor current returns PSU− → BOOSTXL GND only; no motor current in the Duponts while the PSU output floats | PASS |
| W30 | U1 CN10.12 = PA12 (LQFP 46) ✓ | U4 CTX | CAN_TX | FDCAN1_TX ✓ | MCU TX → transceiver D (CTX); Rs must be at GND for 1 Mbit/s | PASS |
| W31 | U1 CN10.14 = PA11 (LQFP 45) ✓ | U4 CRX | CAN_RX | FDCAN1_RX ✓ | Transceiver R (CRX) → MCU RX; 3.3 V module, levels match | PASS |
| W32 | U4 CANH | U5 CANH | CANH | — | Twisted pair; 2 × 120 Ω in total (measure 60 Ω) | PASS |
| W33 | U4 CANL | U5 CANL | CANL | — | Twisted pair | PASS |
| W34 | U4 GND | U5 GND | GND | — | Shared logic ground. Motor current returns PSU− → BOOSTXL GND only; no motor current in the Duponts while the PSU output floats | PASS |
| W35 | BB NTC_FET | U1 CN7.36 = PC1 (LQFP 9) ✓ | NTC_FET | ADC1_IN7 ✓ | 10 k / NTC divider from 3V3, 1.65 V at 25 °C, 100 nF filter | PASS |
| W36 | BB NTC_MOT | U1 CN7.35 = PC2 (LQFP 10) ✓ | NTC_MOT | ADC1_IN8 ✓ | same as NTC_FET | PASS |
| W37 | BB NTC_FET | RT1 1 | NTC_FET | — | 10 k / NTC divider from 3V3, 1.65 V at 25 °C, 100 nF filter | PASS |
| W38 | BB GND rail | RT1 2 | GND | — | Shared logic ground. Motor current returns PSU− → BOOSTXL GND only; no motor current in the Duponts while the PSU output floats | PASS |
| W39 | BB NTC_MOT | RT2 1 | NTC_MOT | — | same as NTC_FET | PASS |
| W40 | BB GND rail | RT2 2 | GND | — | Shared logic ground. Motor current returns PSU− → BOOSTXL GND only; no motor current in the Duponts while the PSU output floats | PASS |
| W41 | U1 CN7.32 = PA4 (LQFP 18) ✓ | SCOPE CH4 | DBG_DAC1 | DAC1_OUT1 ✓ | DAC output 0–3.3 V into the scope (high impedance) | PASS |
| P01 | PSU + | F1 in | VBUS_PSU | — | 14 AWG, 10 A fuse | PASS |
| P02 | F1 out | D1 A1+A2 | VBUS_F | — | Into the D1 anodes (pins 1 + 3) | PASS |
| P03 | D1 K | PB BUS+ | VBUS | — | D1 cathode (pin 2 / tab) → bus node → BOOSTXL VM+; ≤ 25.2 V, inside the BOOSTXL 6–54 V range | PASS |
| P04 | PB BUS+ | U2 VM+ | VBUS | — | D1 cathode (pin 2 / tab) → bus node → BOOSTXL VM+; ≤ 25.2 V, inside the BOOSTXL 6–54 V range | PASS |
| P05 | PSU - | PB BUS- | PGND | — | PSU− → bus− → BOOSTXL GND | PASS |
| P06 | PB BUS- | U2 VM- | PGND | — | PSU− → bus− → BOOSTXL GND | PASS |
| P07 | U2 J5.A | M1 A | PH_A | — | 18 AWG to J5; phase order is free | PASS |
| P08 | U2 J5.B | M1 B | PH_B | — | same as PH_A | PASS |
| P09 | U2 J5.C | M1 C | PH_C | — | same as PH_A | PASS |

## 4. Changes made during this review

| # | Finding | Change |
|---|---|---|
| 1 | The BOOSTXL VSENVM divider ratio is not in TI's user guide, so at 25.2 V the pin could exceed the MCU's 3.3 V. | Procedure §5.6: measure J3.3 with the BOOSTXL alone; connect W17 only if 25.2 V gives < 3.0 V. Note added to W17. |
| 2 | Powering the BOOSTXL while it is wired to an unpowered Nucleo back-feeds the MCU through its pins. | Safety rule 8 extended; the §5 checks run with no logic wires. |
| 3 | PB3 (encoder SCK) is also the ST-LINK SWO line. | Keep SWV/trace off (§6.2, W22 note, troubleshooting). |
| 4 | PA15 (DRV nCS) is also JTDI on the CN4 debug connector. | Never plug a JTAG probe into CN4 (§6.2, W13 note). |
| 5 | The SN65HVD230 Rs pin sets the speed; slope-control modules may fail at 1 Mbit/s. | Check 1.8b: Rs ↔ GND ≈ 0 Ω. Note added to W30. |
| 6 | DRV8323 SDO and ENABLE rely on board pull resistors. | CubeMX: PC11 pull-up, PC8 pull-down (§6.2 and the CUBEMX table). |
| 7 | A mirrored header count or a non-default solder bridge would silently move every wire. | New steps 1.10 / 1.11 (GND-pin orientation beep test) and the **T0 pin walk** (each MCU pin driven high in turn and found with the DMM). |

## 5. Still to confirm on the real hardware (cannot be checked on paper)

| # | Item | Where in the procedure |
|---|---|---|
| 1 | Header pin 1 and numbering direction on both boards | 1.10, 1.11 |
| 2 | Every Nucleo header pin is the expected MCU pin (solder bridges as delivered) | T0 pin walk |
| 3 | VSENVM voltage at 25.2 V < 3.0 V | 5.6 |
| 4 | Pull-ups on the BOOSTXL SDO / nFAULT lines | 5.6 |
| 5 | SN65HVD230 Rs at GND; does the module carry its own 120 Ω? | 1.8, 1.8b |
| 6 | AS5047P breakout set for 3.3 V (VDD joined to VDD3V3), and its pin order | 1.7; breakout silkscreen |
| 7 | BOOSTXL power-terminal polarity and J5 position | 1.6; board silkscreen |
| 8 | Shunt value R_SH (TI SLVC690 schematic), before current tests | 0.3, T5 |

Regenerate the evidence at any time with `python rig_wiring.py`. Any wiring change that breaks a pin, a signal or a rule shows up as FAIL.
