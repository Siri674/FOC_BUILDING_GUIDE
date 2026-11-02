#!/usr/bin/env python3
"""
iGL-FOC-1 no-PCB rig (NUCLEO-G474RE + BOOSTXL-DRV8323RS + AS5047P + CAN)
Wiring reference generator and checker.

One data table (WIRES) is the single source of truth. The script:
  1. checks every connection against the verified header tables
     (TI SLVUB01C Tables 2-3 for BOOSTXL J3/J4, ST UM2505 Table 16 for the Nucleo morpho headers),
  2. writes the component-wise wiring reference (Markdown),
  3. writes a wire list (CSV) to print and tick off,
  4. draws a wiring diagram (SVG) with every wire ID and colour,
  5. prints the SPI command words used in the bring-up tests.

Usage:  python rig_wiring.py [output_dir]     (default: ./rig_wiring_out)
Only the Python standard library is needed. Exit code 1 if any check FAILS.
"""
import csv
import sys
from pathlib import Path
from xml.sax.saxutils import escape

# --------------------------------------------------------------------------------------
# 1. Verified header pin-outs
# --------------------------------------------------------------------------------------
# ST UM2505 Rev 4, Table 16 (default solder bridges). CN7.36 = PC1 and CN7.38 = PC0 by default.
NUCLEO = {
    "CN7": {1: "PC10", 2: "PC11", 3: "PC12", 4: "PD2", 5: "VDD", 6: "E5V", 7: "BOOT0", 8: "GND",
            9: "NC", 10: "NC", 11: "NC", 12: "IOREF", 13: "PA13", 14: "NRST", 15: "PA14", 16: "3V3",
            17: "PA15", 18: "5V", 19: "GND", 20: "GND", 21: "PB7", 22: "GND", 23: "PC13", 24: "VIN",
            25: "PC14", 26: "NC", 27: "PC15", 28: "PA0", 29: "PF0", 30: "PA1", 31: "PF1", 32: "PA4",
            33: "VBAT", 34: "PB0", 35: "PC2", 36: "PC1", 37: "PC3", 38: "PC0"},
    "CN10": {1: "PC9", 2: "PC8", 3: "PB8", 4: "PC6", 5: "PB9", 6: "PC5", 7: "VREFP", 8: "5V_USB_CHGR",
             9: "GND", 10: "NC", 11: "PA5", 12: "PA12", 13: "PA6", 14: "PA11", 15: "PA7", 16: "PB12",
             17: "PB6", 18: "PB11", 19: "PC7", 20: "GND", 21: "PA9", 22: "PB2", 23: "PA8", 24: "PB1",
             25: "PB10", 26: "PB15", 27: "PB4", 28: "PB14", 29: "PB5", 30: "PB13", 31: "PB3", 32: "AGND",
             33: "PA10", 34: "PC4", 35: "PA2", 36: "NC", 37: "PA3", 38: "NC"},
}
# TI SLVUB01C Rev C, Table 2 (J3) and Table 3 (J4). "(H)" = DRV8323RH only, unused on the RS.
BOOSTXL = {
    "J3": {1: "3.3V_OUT", 2: "NC", 3: "VSENVM", 4: "GND", 5: "NC", 6: "VSENA", 7: "NC", 8: "VSENB",
           9: "ENABLE", 10: "VSENC", 11: "POT", 12: "ISENC", 13: "SCLK", 14: "ISENB", 15: "nFAULT",
           16: "ISENA", 17: "NC", 18: "IDRIVE(H)", 19: "NC", 20: "VDS(H)"},
    "J4": {1: "INHA", 2: "GND", 3: "INLA", 4: "HALLA", 5: "INHB", 6: "HALLB", 7: "INLB", 8: "NC",
           9: "INHC", 10: "NC", 11: "INLC", 12: "SDI", 13: "MODE(H)", 14: "SDO", 15: "LED", 16: "HALLC",
           17: "EVM_ID", 18: "nSCS/GAIN", 19: "EVM_ID", 20: "CAL"},
}
BOOSTXL_DO_NOT_CONNECT = {
    "J3.1": "BOOSTXL's own 3.3 V (DRV8323 buck output). Never join it to the Nucleo 3V3.",
    "J3.6": "VSENA phase voltage: not needed with an encoder (leave open).",
    "J3.8": "VSENB: leave open.", "J3.10": "VSENC: leave open.",
    "J3.18": "IDRIVE: DRV8323RH only.", "J3.20": "VDS: DRV8323RH only.",
    "J4.4": "HALLA: not used (encoder instead).", "J4.6": "HALLB: not used.", "J4.16": "HALLC: not used.",
    "J4.13": "MODE: DRV8323RH only.", "J4.15": "LED: optional, not used.",
    "J4.17": "EVM ID: leave open.", "J4.19": "EVM ID: leave open.",
    "J4.20": "CAL: leave open (offset calibration is done over SPI, CSA_CAL bits).",
}

# Pins that must never be wired on the rig
FORBIDDEN_MCU = {
    "PA13": "SWDIO to the on-board ST-LINK", "PA14": "SWCLK to the on-board ST-LINK",
    "PB8": "BOOT0 function", "PF0": "24 MHz HSE crystal", "PF1": "24 MHz HSE crystal",
    "PA2": "LPUART1 TX, already wired to the ST-LINK virtual COM port",
    "PA3": "LPUART1 RX, already wired to the ST-LINK virtual COM port",
}

# --------------------------------------------------------------------------------------
# 2. Components (reference designators used in every output)
# --------------------------------------------------------------------------------------
COMPONENTS = {
    "U1": ("NUCLEO-G474RE", "MCU board, on-board ST-LINK-V3E, 24 MHz HSE crystal", "R1"),
    "U2": ("BOOSTXL-DRV8323RS", "DRV8323RS gate driver + 6 FETs + 3 shunts, 6-54 V, 15 A max", "R2"),
    "U3": ("AS5047P breakout", "14-bit SPI magnetic encoder, run at 3.3 V", "R3"),
    "U4": ("SN65HVD230 module", "3.3 V CAN transceiver, sits on the breadboard", "R7"),
    "U5": ("CANable 2.0", "USB-CAN adapter for the PC (termination switch ON)", "R4"),
    "M1": ("5010 BLDC motor", "~280 KV, 7 pole pairs (12N14P), clamped to the base plate", "R5"),
    "BB": ("Breadboard MB-102", "Logic only: 3V3 and GND rails, NTC dividers, nFAULT node", "R25"),
    "R1": ("10 kOhm", "NTC_FET divider pull-up (breadboard)", "R29"),
    "R2": ("10 kOhm", "NTC_MOT divider pull-up (breadboard)", "R29"),
    "C1": ("100 nF", "NTC_FET filter (breadboard)", "R30"),
    "C2": ("100 nF", "NTC_MOT filter (breadboard)", "R30"),
    "RT1": ("NTC 10k B3950", "Taped (Kapton) on the BOOSTXL FETs", "R27"),
    "RT2": ("NTC 10k B3950", "Taped (Kapton) on the motor stator", "R27"),
    "SW1": ("Tactile push button", "Soft E-stop / BKIN test: pulls nFAULT low", "kit"),
    "PSU": ("Bench PSU", "24 V max (start at 12 V), current-limited", "R14"),
    "F1": ("Inline ATO fuse 10 A", "Supply + lead", "R16"),
    "D1": ("MBR2045CT Schottky", "TO-220 on heatsink; pin 1 = A1, pin 3 = A2 (tie), pin 2/tab = K", "R9/R10"),
    "C3": ("2200 uF 50 V", "Bus capacitor on perfboard", "R11"),
    "C4": ("2200 uF 50 V", "Bus capacitor on perfboard", "R11"),
    "D2": ("SMCJ28A / 1.5KE33A TVS", "Across the bus, cathode (band) to +", "R12"),
    "PB": ("Perfboard bus node", "Holds D1, C3, C4, D2 with 14 AWG wire", "R13"),
    "SCOPE": ("Oscilloscope", "4-channel; probe grounds to rig GND only", "lab"),
}

# --------------------------------------------------------------------------------------
# 3. Wires: the single source of truth
#    (id, group, (ref, pin), (ref, pin), net, MCU function, colour, max length cm, wire, note)
# --------------------------------------------------------------------------------------
G_DRV, G_SPI, G_ANA, G_RAIL, G_ENC, G_CAN, G_NTC, G_DBG, G_PWR, G_MOT = (
    "A Driver PWM", "B Driver control/SPI", "C Driver analog", "D Breadboard rails", "E Encoder",
    "F CAN", "G Temperature", "H Debug", "P Power harness", "M Motor")

WIRES = [
    ("W01", G_DRV, ("U1", "CN10.23"), ("U2", "J4.1"), "PWM_AH", "TIM1_CH1", "orange", 10, "Dupont", "Twist W01-W06 with W07 (GND)"),
    ("W02", G_DRV, ("U1", "CN10.30"), ("U2", "J4.3"), "PWM_AL", "TIM1_CH1N", "yellow", 10, "Dupont", ""),
    ("W03", G_DRV, ("U1", "CN10.21"), ("U2", "J4.5"), "PWM_BH", "TIM1_CH2", "orange", 10, "Dupont", ""),
    ("W04", G_DRV, ("U1", "CN10.28"), ("U2", "J4.7"), "PWM_BL", "TIM1_CH2N", "yellow", 10, "Dupont", ""),
    ("W05", G_DRV, ("U1", "CN10.33"), ("U2", "J4.9"), "PWM_CH", "TIM1_CH3", "orange", 10, "Dupont", ""),
    ("W06", G_DRV, ("U1", "CN10.26"), ("U2", "J4.11"), "PWM_CL", "TIM1_CH3N", "yellow", 10, "Dupont", ""),
    ("W07", G_DRV, ("U1", "CN10.20"), ("U2", "J4.2"), "GND", "GND", "black", 10, "Dupont", "Return for the PWM bundle"),
    ("W08", G_SPI, ("U1", "CN10.2"), ("U2", "J3.9"), "DRV_EN", "GPIO_Output (reset low)", "purple", 10, "Dupont", "Low = DRV8323 asleep, gates off"),
    ("W09a", G_SPI, ("U1", "CN10.13"), ("BB", "NFLT"), "nFAULT_BKIN", "TIM1_BKIN (+EXTI)", "purple", 15, "Dupont", "Via breadboard node so SW1 can pull it low"),
    ("W09b", G_SPI, ("BB", "NFLT"), ("U2", "J3.15"), "nFAULT_BKIN", "-", "purple", 15, "Dupont", "Pull-up is on the BOOSTXL"),
    ("W10", G_SPI, ("U1", "CN7.1"), ("U2", "J3.13"), "DRV_SCK", "SPI3_SCK", "blue", 20, "Dupont", "SPI mode 1, start at <= 1 MHz"),
    ("W11", G_SPI, ("U1", "CN7.3"), ("U2", "J4.12"), "DRV_SDI", "SPI3_MOSI", "blue", 20, "Dupont", ""),
    ("W12", G_SPI, ("U1", "CN7.2"), ("U2", "J4.14"), "DRV_SDO", "SPI3_MISO", "blue", 20, "Dupont", ""),
    ("W13", G_SPI, ("U1", "CN7.17"), ("U2", "J4.18"), "DRV_nCS", "GPIO_Output (reset high)", "blue", 20, "Dupont", "PA15 is also JTDI on the Nucleo CN4 debug connector: never plug a JTAG probe into CN4"),
    ("W14", G_ANA, ("U1", "CN7.28"), ("U2", "J3.16"), "ISENSE_A", "ADC1_IN1 + COMP3_INP", "green", 15, "Dupont", "Keep away from PWM wires"),
    ("W15", G_ANA, ("U1", "CN7.30"), ("U2", "J3.14"), "ISENSE_B", "ADC1/2_IN2 + COMP1_INP", "green", 15, "Dupont", ""),
    ("W16", G_ANA, ("U1", "CN10.15"), ("U2", "J3.12"), "ISENSE_C", "ADC2_IN4 + COMP2_INP", "green", 10, "Dupont", ""),
    ("W17", G_ANA, ("U1", "CN7.38"), ("U2", "J3.3"), "VBUS_SNS", "ADC1/2_IN6", "green", 15, "Dupont", "Before plugging W17: VSENVM must read < 3.3 V at 25.2 V (procedure §5); then calibrate the ratio with a DMM"),
    ("W18", G_ANA, ("U1", "CN7.22"), ("U2", "J3.4"), "GND", "GND", "black", 15, "Dupont", "Analog return; route next to W14-W17"),
    ("W19", G_ANA, ("U1", "CN7.37"), ("U2", "J3.11"), "POT_CMD", "ADC (PC3, optional)", "white", 15, "Dupont", "OPTIONAL: BOOSTXL pot as a command knob"),
    ("W20", G_RAIL, ("U1", "CN7.16"), ("BB", "+3V3 rail"), "+3V3", "3V3", "red", 15, "Dupont", "Nucleo 3V3 feeds encoder, CAN module, NTC dividers"),
    ("W21", G_RAIL, ("U1", "CN7.8"), ("BB", "GND rail"), "GND", "GND", "black", 15, "Dupont", ""),
    ("W22", G_ENC, ("U1", "CN10.31"), ("U3", "CLK"), "ENC_SCK", "SPI1_SCK", "blue", 15, "Dupont", "SPI mode 1, <= 10 MHz. PB3 is also the ST-LINK SWO line: keep SWV/trace OFF in the debugger"),
    ("W23", G_ENC, ("U1", "CN10.27"), ("U3", "MISO"), "ENC_MISO", "SPI1_MISO", "blue", 15, "Dupont", ""),
    ("W24", G_ENC, ("U1", "CN10.29"), ("U3", "MOSI"), "ENC_MOSI", "SPI1_MOSI", "blue", 15, "Dupont", ""),
    ("W25", G_ENC, ("U1", "CN10.17"), ("U3", "CSn"), "ENC_CS", "GPIO_Output (reset high)", "blue", 15, "Dupont", "Enable the internal pull-up too"),
    ("W26", G_ENC, ("BB", "+3V3 rail"), ("U3", "VDD3V3"), "+3V3", "-", "red", 15, "Dupont", "3.3 V mode: VDD and VDD3V3 joined (check the breakout jumper)"),
    ("W27", G_ENC, ("BB", "GND rail"), ("U3", "GND"), "GND", "-", "black", 15, "Dupont", "Twist with W22-W25"),
    ("W28", G_CAN, ("BB", "+3V3 rail"), ("U4", "3V3"), "+3V3", "-", "red", 5, "Breadboard", ""),
    ("W29", G_CAN, ("BB", "GND rail"), ("U4", "GND"), "GND", "-", "black", 5, "Breadboard", ""),
    ("W30", G_CAN, ("U1", "CN10.12"), ("U4", "CTX"), "CAN_TX", "FDCAN1_TX", "white", 15, "Dupont", "Module 'CTX/D' input. The module Rs pin must be tied to GND (0 ohm) for 1 Mbit/s"),
    ("W31", G_CAN, ("U1", "CN10.14"), ("U4", "CRX"), "CAN_RX", "FDCAN1_RX", "grey", 15, "Dupont", "Module 'CRX/R' output"),
    ("W32", G_CAN, ("U4", "CANH"), ("U5", "CANH"), "CANH", "-", "white", 200, "Twisted pair", "Twist W32/W33"),
    ("W33", G_CAN, ("U4", "CANL"), ("U5", "CANL"), "CANL", "-", "grey", 200, "Twisted pair", ""),
    ("W34", G_CAN, ("U4", "GND"), ("U5", "GND"), "GND", "-", "black", 200, "Wire", "CAN ground reference"),
    ("W35", G_NTC, ("BB", "NTC_FET"), ("U1", "CN7.36"), "NTC_FET", "ADC1/2_IN7", "green", 15, "Dupont", "Node of R1 / RT1 / C1"),
    ("W36", G_NTC, ("BB", "NTC_MOT"), ("U1", "CN7.35"), "NTC_MOT", "ADC1/2_IN8", "green", 15, "Dupont", "Node of R2 / RT2 / C2"),
    ("W37", G_NTC, ("BB", "NTC_FET"), ("RT1", "1"), "NTC_FET", "-", "white", 30, "Wire", "Extension to the FET area"),
    ("W38", G_NTC, ("BB", "GND rail"), ("RT1", "2"), "GND", "-", "black", 30, "Wire", ""),
    ("W39", G_NTC, ("BB", "NTC_MOT"), ("RT2", "1"), "NTC_MOT", "-", "white", 40, "Wire", "Extension to the motor"),
    ("W40", G_NTC, ("BB", "GND rail"), ("RT2", "2"), "GND", "-", "black", 40, "Wire", ""),
    ("W41", G_DBG, ("U1", "CN7.32"), ("SCOPE", "CH4"), "DBG_DAC1", "DAC1_OUT1 (PA4)", "brown", 20, "Probe loop", "Firmware writes Iq / angle here"),
    ("P01", G_PWR, ("PSU", "+"), ("F1", "in"), "VBUS_PSU", "-", "red", 50, "14 AWG", "XT30 between PSU lead and harness"),
    ("P02", G_PWR, ("F1", "out"), ("D1", "A1+A2"), "VBUS_F", "-", "red", 20, "14 AWG", "Pins 1 and 3 joined"),
    ("P03", G_PWR, ("D1", "K"), ("PB", "BUS+"), "VBUS", "-", "red", 5, "14 AWG", "Pin 2 / tab"),
    ("P04", G_PWR, ("PB", "BUS+"), ("U2", "VM+"), "VBUS", "-", "red", 20, "14 AWG", "BOOSTXL power terminal +"),
    ("P05", G_PWR, ("PSU", "-"), ("PB", "BUS-"), "PGND", "-", "black", 70, "14 AWG", "XT30"),
    ("P06", G_PWR, ("PB", "BUS-"), ("U2", "VM-"), "PGND", "-", "black", 20, "14 AWG", "BOOSTXL power terminal GND"),
    ("P07", G_MOT, ("U2", "J5.A"), ("M1", "A"), "PH_A", "-", "red", 15, "18 AWG + bullet", "Phase order is free; calibration finds direction"),
    ("P08", G_MOT, ("U2", "J5.B"), ("M1", "B"), "PH_B", "-", "yellow", 15, "18 AWG + bullet", ""),
    ("P09", G_MOT, ("U2", "J5.C"), ("M1", "C"), "PH_C", "-", "blue", 15, "18 AWG + bullet", ""),
]
OPTIONAL = {"W19"}

# Parts placed on the breadboard / perfboard (not wires)
PLACEMENTS = [
    ("R1", "+3V3 rail", "NTC_FET", "10 k pull-up"),
    ("C1", "NTC_FET", "GND rail", "100 nF filter"),
    ("R2", "+3V3 rail", "NTC_MOT", "10 k pull-up"),
    ("C2", "NTC_MOT", "GND rail", "100 nF filter"),
    ("SW1", "NFLT", "GND rail", "Press = nFAULT low = PWM stops (BKIN)"),
    ("U4", "rows 40-45", "", "SN65HVD230 module plugged into the breadboard"),
    ("C3", "BUS+", "BUS-", "2200 uF 50 V, observe polarity"),
    ("C4", "BUS+", "BUS-", "2200 uF 50 V, observe polarity"),
    ("D2", "BUS+ (cathode/band)", "BUS- (anode)", "TVS"),
]

# CubeMX functions per MCU pin on the rig (the Rev A PCB uses the same pins)
CUBEMX = {
    "PA8": "TIM1_CH1", "PB13": "TIM1_CH1N", "PA9": "TIM1_CH2", "PB14": "TIM1_CH2N", "PA10": "TIM1_CH3",
    "PB15": "TIM1_CH3N", "PA6": "TIM1_BKIN", "PC8": "GPIO_Output, pull-down, initial low", "PC10": "SPI3_SCK", "PC11": "SPI3_MISO, pull-up (DRV8323 SDO)",
    "PC12": "SPI3_MOSI", "PA15": "GPIO_Output", "PA0": "ADC1_IN1 / COMP3_INP", "PA1": "ADC2_IN2 / COMP1_INP",
    "PA7": "ADC2_IN4 / COMP2_INP", "PC0": "ADC1_IN6", "PC1": "ADC1_IN7", "PC2": "ADC1_IN8", "PC3": "ADC (optional POT)",
    "PB3": "SPI1_SCK", "PB4": "SPI1_MISO", "PB5": "SPI1_MOSI", "PB6": "GPIO_Output", "PA12": "FDCAN1_TX",
    "PA11": "FDCAN1_RX", "PA4": "DAC1_OUT1", "PA2": "LPUART1_TX (ST-LINK VCP, no wire)",
    "PA3": "LPUART1_RX (ST-LINK VCP, no wire)", "PA5": "GPIO_Output: LD2 green LED (no wire)",
    "PC13": "GPIO_Input: B1 blue button (no wire)", "PA13": "SYS_SWDIO (no wire)", "PA14": "SYS_SWCLK (no wire)",
}

# ST STM32_open_pin_data (github.com/STMicroelectronics/STM32_open_pin_data): mcu/STM32G474R(B-C-E)Tx.xml and
# mcu/IP/GPIO-STM32G47x_gpio_v1_0_Modes.xml, read 1 Nov 2026. MCU pin -> (LQFP64 position, {signal: AF or 'analog'})
ST_PIN_DATA = {
    'PA0': (12, {'ADC1_IN1': 'analog', 'COMP3_INP': 'analog', 'GPIO_Output': 'GPIO'}),
    'PA1': (13, {'ADC2_IN2': 'analog', 'COMP1_INP': 'analog', 'GPIO_Output': 'GPIO'}),
    'PA2': (14, {'LPUART1_TX': 'AF12_LPUART1', 'GPIO_Output': 'GPIO'}),
    'PA3': (17, {'COMP2_INP': 'analog', 'LPUART1_RX': 'AF12_LPUART1', 'GPIO_Output': 'GPIO'}),
    'PA4': (18, {'DAC1_OUT1': 'analog', 'GPIO_Output': 'GPIO'}),
    'PA5': (19, {'DAC1_OUT2': 'analog', 'SPI1_SCK': 'AF5_SPI1', 'GPIO_Output': 'GPIO'}),
    'PA6': (20, {'SPI1_MISO': 'AF5_SPI1', 'TIM1_BKIN': 'AF6_TIM1', 'GPIO_Output': 'GPIO'}),
    'PA7': (21, {'ADC2_IN4': 'analog', 'COMP2_INP': 'analog', 'SPI1_MOSI': 'AF5_SPI1', 'TIM1_CH1N': 'AF6_TIM1', 'GPIO_Output': 'GPIO'}),
    'PA8': (42, {'TIM1_CH1': 'AF6_TIM1', 'GPIO_Output': 'GPIO'}),
    'PA9': (43, {'TIM1_CH2': 'AF6_TIM1', 'GPIO_Output': 'GPIO'}),
    'PA10': (44, {'TIM1_CH3': 'AF6_TIM1', 'GPIO_Output': 'GPIO'}),
    'PA11': (45, {'FDCAN1_RX': 'AF9_FDCAN1', 'TIM1_CH1N': 'AF6_TIM1', 'GPIO_Output': 'GPIO'}),
    'PA12': (46, {'FDCAN1_TX': 'AF9_FDCAN1', 'TIM1_CH2N': 'AF6_TIM1', 'GPIO_Output': 'GPIO'}),
    'PA13': (49, {'SYS_JTMS-SWDIO': 'AF0_TRACE', 'GPIO_Output': 'GPIO'}),
    'PA14': (50, {'SYS_JTCK-SWCLK': 'AF0_TRACE', 'TIM1_BKIN': 'AF6_TIM1', 'GPIO_Output': 'GPIO'}),
    'PA15': (51, {'TIM1_BKIN': 'AF9_TIM1', 'GPIO_Output': 'GPIO'}),
    'PB3': (56, {'SPI1_SCK': 'AF5_SPI1', 'SPI3_SCK': 'AF6_SPI3', 'GPIO_Output': 'GPIO'}),
    'PB4': (57, {'SPI1_MISO': 'AF5_SPI1', 'SPI3_MISO': 'AF6_SPI3', 'GPIO_Output': 'GPIO'}),
    'PB5': (58, {'SPI1_MOSI': 'AF5_SPI1', 'SPI3_MOSI': 'AF6_SPI3', 'GPIO_Output': 'GPIO'}),
    'PB6': (59, {'GPIO_Output': 'GPIO'}),
    'PB13': (35, {'TIM1_CH1N': 'AF6_TIM1', 'GPIO_Output': 'GPIO'}),
    'PB14': (36, {'TIM1_CH2N': 'AF6_TIM1', 'GPIO_Output': 'GPIO'}),
    'PB15': (37, {'TIM1_CH3N': 'AF4_TIM1', 'GPIO_Output': 'GPIO'}),
    'PC0': (8, {'ADC1_IN6': 'analog', 'LPUART1_RX': 'AF8_LPUART1', 'TIM1_CH1': 'AF2_TIM1', 'GPIO_Output': 'GPIO'}),
    'PC1': (9, {'ADC1_IN7': 'analog', 'COMP3_INP': 'analog', 'LPUART1_TX': 'AF8_LPUART1', 'TIM1_CH2': 'AF2_TIM1', 'GPIO_Output': 'GPIO'}),
    'PC2': (10, {'ADC1_IN8': 'analog', 'TIM1_CH3': 'AF2_TIM1', 'GPIO_Output': 'GPIO'}),
    'PC3': (11, {'ADC1_IN9': 'analog', 'GPIO_Output': 'GPIO'}),
    'PC6': (38, {'GPIO_Output': 'GPIO'}),
    'PC8': (40, {'GPIO_Output': 'GPIO'}),
    'PC10': (52, {'SPI3_SCK': 'AF6_SPI3', 'GPIO_Output': 'GPIO'}),
    'PC11': (53, {'SPI3_MISO': 'AF6_SPI3', 'GPIO_Output': 'GPIO'}),
    'PC12': (54, {'SPI3_MOSI': 'AF6_SPI3', 'GPIO_Output': 'GPIO'}),
    'PC13': (2, {'TIM1_BKIN': 'AF2_TIM1', 'TIM1_CH1N': 'AF4_TIM1', 'GPIO_Output': 'GPIO'}),
}
# Peripheral signal(s) each MCU-side net needs; checked against ST_PIN_DATA
REQUIRED_SIGNALS = {
    'PWM_AH': ['TIM1_CH1'],
    'PWM_AL': ['TIM1_CH1N'],
    'PWM_BH': ['TIM1_CH2'],
    'PWM_BL': ['TIM1_CH2N'],
    'PWM_CH': ['TIM1_CH3'],
    'PWM_CL': ['TIM1_CH3N'],
    'nFAULT_BKIN': ['TIM1_BKIN'],
    'DRV_SCK': ['SPI3_SCK'],
    'DRV_SDO': ['SPI3_MISO'],
    'DRV_SDI': ['SPI3_MOSI'],
    'ENC_SCK': ['SPI1_SCK'],
    'ENC_MISO': ['SPI1_MISO'],
    'ENC_MOSI': ['SPI1_MOSI'],
    'CAN_TX': ['FDCAN1_TX'],
    'CAN_RX': ['FDCAN1_RX'],
    'ISENSE_A': ['ADC1_IN1', 'COMP3_INP'],
    'ISENSE_B': ['ADC2_IN2', 'COMP1_INP'],
    'ISENSE_C': ['ADC2_IN4', 'COMP2_INP'],
    'VBUS_SNS': ['ADC1_IN6'],
    'NTC_FET': ['ADC1_IN7'],
    'NTC_MOT': ['ADC1_IN8'],
    'POT_CMD': ['ADC1_IN9'],
    'DBG_DAC1': ['DAC1_OUT1'],
    'DRV_EN': ['GPIO_Output'],
    'DRV_nCS': ['GPIO_Output'],
    'ENC_CS': ['GPIO_Output'],
}

COLOURS = {"orange": "#e8820c", "yellow": "#c9a800", "blue": "#1f6fb4", "green": "#2e9d3a", "purple": "#8e44ad",
           "black": "#222222", "red": "#d62728", "white": "#9a9a9a", "grey": "#5f6b75", "brown": "#8c564b"}

# --------------------------------------------------------------------------------------
# 4. Helpers
# --------------------------------------------------------------------------------------
def nucleo_pin(pin):
    hdr, n = pin.split(".")
    return NUCLEO.get(hdr, {}).get(int(n))


def boostxl_pin(pin):
    if "." not in pin or pin.split(".")[0] not in BOOSTXL:
        return pin  # VM+, VM-, J5.x
    hdr, n = pin.split(".")
    return BOOSTXL[hdr].get(int(n))


def endpoint_label(ref, pin):
    if ref == "U1":
        return f"U1 {pin} ({nucleo_pin(pin)})"
    if ref == "U2" and pin.split(".")[0] in BOOSTXL:
        return f"U2 {pin} ({boostxl_pin(pin)})"
    return f"{ref} {pin}"


# Expected signal at each BOOSTXL header pin for each net
EXPECT_BOOSTXL = {"PWM_AH": "INHA", "PWM_AL": "INLA", "PWM_BH": "INHB", "PWM_BL": "INLB", "PWM_CH": "INHC",
                  "PWM_CL": "INLC", "GND": "GND", "DRV_EN": "ENABLE", "nFAULT_BKIN": "nFAULT", "DRV_SCK": "SCLK",
                  "DRV_SDI": "SDI", "DRV_SDO": "SDO", "DRV_nCS": "nSCS/GAIN", "ISENSE_A": "ISENA",
                  "ISENSE_B": "ISENB", "ISENSE_C": "ISENC", "VBUS_SNS": "VSENVM", "POT_CMD": "POT"}
# Expected MCU pin for each net (the design pin map, build guide §6B.2 / Rev A package §5)
EXPECT_MCU = {"PWM_AH": "PA8", "PWM_AL": "PB13", "PWM_BH": "PA9", "PWM_BL": "PB14", "PWM_CH": "PA10",
              "PWM_CL": "PB15", "DRV_EN": "PC8", "nFAULT_BKIN": "PA6", "DRV_SCK": "PC10", "DRV_SDI": "PC12",
              "DRV_SDO": "PC11", "DRV_nCS": "PA15", "ISENSE_A": "PA0", "ISENSE_B": "PA1", "ISENSE_C": "PA7",
              "VBUS_SNS": "PC0", "POT_CMD": "PC3", "ENC_SCK": "PB3", "ENC_MISO": "PB4", "ENC_MOSI": "PB5",
              "ENC_CS": "PB6", "CAN_TX": "PA12", "CAN_RX": "PA11", "NTC_FET": "PC1", "NTC_MOT": "PC2",
              "DBG_DAC1": "PA4", "+3V3": "3V3", "GND": "GND"}


def run_checks():
    res = []
    ok = lambda m: res.append(("PASS", m))
    bad = lambda m: res.append(("FAIL", m))
    ids = [w[0] for w in WIRES]
    (ok if len(ids) == len(set(ids)) else bad)("Wire IDs are unique")
    used_hdr, used_mcu = {}, {}
    for wid, grp, a, b, net, func, col, ln, typ, note in WIRES:
        for ref, pin in (a, b):
            if ref == "U1":
                sig = nucleo_pin(pin)
                if sig is None:
                    bad(f"{wid}: U1 {pin} does not exist on the Nucleo headers")
                    continue
                if sig in FORBIDDEN_MCU:
                    bad(f"{wid}: U1 {pin} is {sig}, reserved ({FORBIDDEN_MCU[sig]})")
                exp = EXPECT_MCU.get(net)
                if exp and exp != sig:
                    bad(f"{wid}: net {net} must use {exp}, but U1 {pin} is {sig}")
                if sig not in ("GND", "3V3"):
                    if sig in used_mcu and used_mcu[sig] != net:
                        bad(f"{wid}: MCU pin {sig} already used by net {used_mcu[sig]}")
                    used_mcu[sig] = net
                key = f"U1.{pin}"
                if key in used_hdr:
                    bad(f"{wid}: header pin {key} already used by {used_hdr[key]} (one Dupont per pin)")
                used_hdr[key] = wid
            if ref == "U2" and pin.split(".")[0] in BOOSTXL:
                sig = boostxl_pin(pin)
                if sig is None:
                    bad(f"{wid}: U2 {pin} does not exist")
                    continue
                if pin in BOOSTXL_DO_NOT_CONNECT:
                    bad(f"{wid}: U2 {pin} is on the do-not-connect list ({BOOSTXL_DO_NOT_CONNECT[pin]})")
                exp = EXPECT_BOOSTXL.get(net)
                if exp and exp != sig:
                    bad(f"{wid}: net {net} must land on BOOSTXL {exp}, but {pin} is {sig}")
                key = f"U2.{pin}"
                if key in used_hdr:
                    bad(f"{wid}: header pin {key} already used by {used_hdr[key]}")
                used_hdr[key] = wid
    if not [r for r in res if r[0] == "FAIL"]:
        ok("Every Nucleo pin matches UM2505 Table 16 and the design pin map")
        ok("Every BOOSTXL pin matches SLVUB01C Tables 2-3")
        ok("No header pin carries two Dupont wires")
    # nets: at least two endpoints, one wire per signal pair
    nets = {}
    for w in WIRES:
        nets.setdefault(w[4], set()).update({w[2], w[3]})
    single = [n for n, e in nets.items() if len(e) < 2]
    (ok if not single else bad)("Every net has two or more endpoints" + (f": {single}" if single else ""))
    # safety rules
    j31 = [w[0] for w in WIRES if ("U2", "J3.1") in (w[2], w[3])]
    (ok if not j31 else bad)("BOOSTXL J3.1 (its own 3.3 V) is not joined to the Nucleo 3V3")
    pwr_on_bb = [w[0] for w in WIRES if w[1] in (G_PWR, G_MOT) and "BB" in (w[2][0], w[3][0])]
    (ok if not pwr_on_bb else bad)("No power or motor wire touches the breadboard")
    gnd_drv = [w[0] for w in WIRES if w[4] == "GND" and "U2" in (w[2][0], w[3][0])]
    (ok if len(gnd_drv) >= 2 else bad)(f"At least two GND wires between Nucleo and BOOSTXL ({', '.join(gnd_drv)})")
    long_sig = [w[0] for w in WIRES if (w[1] == G_DRV and w[7] > 10) or (w[1] == G_ANA and w[7] > 15)
                or (w[1] == G_SPI and w[7] > 20)]
    (ok if not long_sig else bad)("Wire limits: PWM 10 cm, analog 15 cm, DRV control/SPI 20 cm (slow SPI, crosses the Nucleo)")
    # every MCU-side net must land on a pin that has the needed peripheral signal (ST open pin data)
    sig_bad = []
    for wid, grp, a, b, net, *_ in WIRES:
        for ref, pin in (a, b):
            if ref != "U1" or net not in REQUIRED_SIGNALS:
                continue
            mcu = nucleo_pin(pin)
            have = ST_PIN_DATA.get(mcu, (None, {}))[1]
            miss = [sg for sg in REQUIRED_SIGNALS[net] if sg not in have]
            if miss:
                sig_bad.append(f"{wid}: {mcu} has no {', '.join(miss)}")
    (ok if not sig_bad else bad)("Every MCU pin provides its peripheral signal (ST STM32_open_pin_data, STM32G474RxT)"
                                 + (f": {sig_bad}" if sig_bad else ""))
    for need in ("PA2", "PA3", "PA13", "PA14"):
        if need in used_mcu:
            bad(f"{need} is wired, but it belongs to the ST-LINK")
    return res


# SPI command words used in the bring-up tests
def drv8323_read(addr):
    return 0x8000 | (addr << 11)


def as5047_cmd(addr, read=True):
    w = (0x4000 if read else 0) | (addr & 0x3FFF)
    if bin(w).count("1") % 2:
        w |= 0x8000  # even parity over bits 0-15
    return w


DRV_REGS = [(0x00, "Fault Status 1"), (0x01, "Fault Status 2 (VGS)"), (0x02, "Driver Control"),
            (0x03, "Gate Drive HS"), (0x04, "Gate Drive LS"), (0x05, "OCP Control"), (0x06, "CSA Control")]
AS_REGS = [(0x0000, "NOP"), (0x0001, "ERRFL"), (0x3FFC, "DIAAGC"), (0x3FFD, "MAG"), (0x3FFE, "ANGLEUNC"),
           (0x3FFF, "ANGLECOM"), (0x0018, "SETTINGS1"), (0x0019, "SETTINGS2")]

# --------------------------------------------------------------------------------------
# 5. Outputs
# --------------------------------------------------------------------------------------
def md_table(head, rows):
    out = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for r in rows:
        out.append("| " + " | ".join(str(c).replace("|", "\\|") for c in r) + " |")
    return "\n".join(out)


def component_rows(ref):
    rows = []
    for wid, grp, a, b, net, func, col, ln, typ, note in WIRES:
        for here, there in ((a, b), (b, a)):
            if here[0] == ref:
                sig = nucleo_pin(here[1]) if ref == "U1" else boostxl_pin(here[1]) if ref == "U2" else ""
                rows.append((here[1], sig or "", net, func if ref == "U1" else "", wid, col,
                             endpoint_label(*there), ("OPTIONAL. " if wid in OPTIONAL else "") + note))
    key = lambda r: (r[0].split(".")[0], int(r[0].split(".")[1]) if "." in r[0] and r[0].split(".")[1].isdigit() else 0, r[0])
    return sorted(rows, key=key)


def write_markdown(path, checks):
    L = []
    L.append("# No-PCB rig: component-wise wiring reference\n")
    L.append("**iGL-FOC-1 · NUCLEO-G474RE + BOOSTXL-DRV8323RS + AS5047P + CAN** · generated by `rig_wiring.py` (edit the script, not this file)\n")
    L.append("Pin tables verified against **TI SLVUB01C** (BOOSTXL J3/J4, Tables 2–3) and **ST UM2505** (Nucleo morpho CN7/CN10, Table 16, default solder bridges).")
    L.append("Bring-up steps: `No_PCB_Rig_Bringup_Procedure.md`. Diagram: `rig_wiring_diagram.svg`. Tick-off list: `rig_wire_list.csv`.\n")
    nf = sum(1 for c in checks if c[0] == "FAIL")
    L.append(f"## 0. Check result: {'ALL PASS' if nf == 0 else f'{nf} FAIL'}\n")
    L.append(md_table(["Result", "Check"], checks) + "\n")
    L.append("## 1. Components\n")
    L.append(md_table(["Ref", "Part", "Role", "Buy list"], [(k, *v) for k, v in COMPONENTS.items()]) + "\n")
    L.append("## 2. Component-wise connections\n")
    for ref in ["U1", "U2", "U3", "U4", "U5", "M1", "BB", "PSU", "F1", "D1", "PB", "RT1", "RT2", "SCOPE"]:
        rows = component_rows(ref)
        if not rows:
            continue
        name = COMPONENTS[ref][0]
        L.append(f"### {ref} · {name}\n")
        if ref == "U1":
            L.append(md_table(["Header pin", "MCU pin", "Net", "CubeMX function", "Wire", "Colour", "Goes to", "Note"], rows))
            L.append("\nAlso on U1 with no wire: PA2/PA3 = LPUART1 to the ST-LINK virtual COM port, PA5 = green LED LD2, "
                     "PC13 = blue button B1, PA13/PA14 = SWD, PF0/PF1 = 24 MHz crystal, PB8 = BOOT0. Power U1 from the ST-LINK USB (CN1).\n")
        elif ref == "U2":
            L.append(md_table(["Pin", "Signal", "Net", "-", "Wire", "Colour", "Goes to", "Note"], rows))
            L.append("\n**BOOSTXL pins to leave open:**\n")
            L.append(md_table(["Pin", "Signal", "Why"], [(p, boostxl_pin(p), why) for p, why in BOOSTXL_DO_NOT_CONNECT.items()]) + "\n")
        else:
            L.append(md_table(["Pin", "-", "Net", "-", "Wire", "Colour", "Goes to", "Note"], rows) + "\n")
    L.append("## 3. Parts placed on the breadboard / perfboard\n")
    L.append(md_table(["Ref", "From", "To", "Note"], PLACEMENTS) + "\n")
    L.append("## 4. Master wire list (build in this order)\n")
    rows = [(w[0], w[1], endpoint_label(*w[2]), endpoint_label(*w[3]), w[4], w[6], f"≤ {w[7]} cm", w[8],
             ("OPTIONAL. " if w[0] in OPTIONAL else "") + w[9], "☐") for w in WIRES]
    L.append(md_table(["Wire", "Group", "From", "To", "Net", "Colour", "Length", "Type", "Note", "Done"], rows) + "\n")
    L.append("## 5. MCU pin functions for CubeMX (rig)\n")
    L.append("Rig clock: **HSE = 24 MHz** (Nucleo crystal X3) → PLLM /6, PLLN ×85, PLLR /2 → **170 MHz**. "
             "The Rev A PCB uses an 8 MHz crystal (PLLM /2); that is the only CubeMX difference between rig and PCB.\n")
    L.append(md_table(["MCU pin", "LQFP64 pin", "Function", "AF / analog (ST pin data)"],
                      [(k, ST_PIN_DATA.get(k, ("-",))[0], v,
                        ", ".join(f"{sg}={af}" for sg, af in ST_PIN_DATA.get(k, (0, {}))[1].items() if sg != "GPIO_Output") or "GPIO")
                       for k, v in sorted(CUBEMX.items())]) + "\n")
    L.append("## 6. SPI command words (for the bring-up tests)\n")
    L.append("DRV8323 (16-bit, SPI mode 1): bit 15 = 1 read, bits 14–11 = address, bits 10–0 = data.\n")
    L.append(md_table(["Addr", "Register", "Read word"], [(f"0x{a:02X}", n, f"0x{drv8323_read(a):04X}") for a, n in DRV_REGS]) + "\n")
    L.append("AS5047P (16-bit, SPI mode 1): bit 14 = 1 read, bit 15 = even parity. The answer comes in the **next** frame.\n")
    L.append(md_table(["Addr", "Register", "Read command"], [(f"0x{a:04X}", n, f"0x{as5047_cmd(a):04X}") for a, n in AS_REGS]) + "\n")
    Path(path).write_text("\n".join(L), encoding="utf-8")


def write_csv(path):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["wire", "group", "from_ref", "from_pin", "from_signal", "to_ref", "to_pin", "to_signal", "net",
                    "mcu_function", "colour", "max_len_cm", "type", "optional", "note", "continuity_ok", "checked_by"])
        for wid, grp, a, b, net, func, col, ln, typ, note in WIRES:
            sig = lambda r, p: nucleo_pin(p) if r == "U1" else (boostxl_pin(p) if r == "U2" else "")
            w.writerow([wid, grp, a[0], a[1], sig(*a), b[0], b[1], sig(*b), net, func, col, ln, typ,
                        "yes" if wid in OPTIONAL else "", note, "", ""])


def write_svg(path, checks):
    W, H = 1560, 1010
    s = []
    add = s.append
    add(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" font-family="Segoe UI, Arial, sans-serif">')
    add('<rect width="100%" height="100%" fill="#ffffff"/>')
    add('<text x="20" y="28" font-size="18" font-weight="700">iGL-FOC-1 no-PCB rig: wiring diagram (generated by rig_wiring.py)</text>')
    nf = sum(1 for c in checks if c[0] == "FAIL")
    add(f'<text x="20" y="50" font-size="12" fill="{"#2e7d32" if nf == 0 else "#c62828"}">Checks: {"ALL PASS" if nf == 0 else str(nf) + " FAIL"} · pins verified vs TI SLVUB01C (J3/J4) and ST UM2505 (CN7/CN10)</text>')

    def box(x, y, w, h, title, sub="", fill="#f4f6f8"):
        add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" fill="{fill}" stroke="#555" stroke-width="1.2"/>')
        add(f'<text x="{x + w / 2}" y="{y + 20}" font-size="14" font-weight="700" text-anchor="middle">{escape(title)}</text>')
        if sub:
            add(f'<text x="{x + w / 2}" y="{y + 36}" font-size="11" fill="#555" text-anchor="middle">{escape(sub)}</text>')

    
def line(pts, colour, width=2.2, dash=False):
    d = " ".join(f"{x},{y}" for x, y in pts)
    dash_attr = ' stroke-dasharray="6 4"' if dash else ''
    add(
        f'<polyline points="{d}" fill="none" '
        f'stroke="{COLOURS.get(colour, colour)}" '
        f'stroke-width="{width}"{dash_attr}/>'
    )

    def label(x, y, t, size=11, anchor="start", colour="#222", weight="400"):
        add(f'<text x="{x}" y="{y}" font-size="{size}" text-anchor="{anchor}" fill="{colour}" font-weight="{weight}">{escape(t)}</text>')

    def dot(x, y, c="#222"):
        add(f'<circle cx="{x}" cy="{y}" r="3.2" fill="{c}"/>')

    # main boxes
    NX0, NX1, BX0, BX1, TOP, BOT = 520, 720, 1080, 1290, 150, 900
    box(NX0, TOP, NX1 - NX0, BOT - TOP, "U1 NUCLEO-G474RE", "ST-LINK USB → PC (power, flash, VCP)", "#eaf1fb")
    box(BX0, TOP, BX1 - BX0, BOT - TOP, "U2 BOOSTXL-DRV8323RS", "J3 / J4 headers (left), J5 motor (right)", "#fbeee6")

    # right side of U1 -> left side of U2 (straight wires)
    right = [w for w in WIRES if w[2][0] == "U1" and (w[3][0] == "U2" or w[3] == ("BB", "NFLT"))]
    right_ids = [w[0] for w in right]
    y = TOP + 60
    step = (BOT - TOP - 80) / max(len(right), 1)
    for w in right:
        wid, grp, a, b, net, func, col, *_ = w
        c = COLOURS[col]
        label(NX1 - 6, y + 4, f"{a[1]} {nucleo_pin(a[1])}", 11, "end")
        if b == ("BB", "NFLT"):
            wb = next(x for x in WIRES if x[0] == "W09b")
            mid = (NX1 + BX0) / 2
            line([(NX1, y), (mid, y)], col)
            line([(mid, y), (BX0, y)], col)
            dot(mid, y, c)
            line([(mid, y), (mid, y + 18)], "#222", 1.4)
            add(f'<rect x="{mid - 14}" y="{y + 18}" width="28" height="10" fill="#fff" stroke="#222"/>')
            label(mid + 18, y + 27, "SW1 → GND (breadboard)", 10)
            label(BX0 + 6, y + 4, f"{wb[3][1]} {boostxl_pin(wb[3][1])}", 11)
            label(NX1 + 8, y - 4, "W09a", 10, colour=c, weight="700")
            label(BX0 - 8, y - 4, "W09b", 10, "end", colour=c, weight="700")
        else:
            line([(NX1, y), (BX0, y)], col, dash=(wid in OPTIONAL))
            label(BX0 + 6, y + 4, f"{b[1]} {boostxl_pin(b[1])}", 11)
            label(NX1 + 8, y - 4, wid + (" (opt)" if wid in OPTIONAL else ""), 10, colour=c, weight="700")
            label(BX0 - 8, y - 4, net, 10, "end", colour="#666")
        dot(NX1, y, c), dot(BX0, y, c)
        y += step

    # left side: rails and peripherals
    RAIL3, RAILG = 400, 430
    line([(RAIL3, TOP + 20), (RAIL3, BOT)], "red", 3)
    line([(RAILG, TOP + 20), (RAILG, BOT)], "black", 3)
    label(RAIL3, TOP + 12, "BB +3V3", 11, "middle", "#d62728", "700")
    label(RAILG + 4, TOP + 12, "BB GND", 11, "start", "#222", "700")

    def periph(x, y0, w, title, sub, pins, fill):
        h = 44 + 26 * len(pins)
        box(x, y0, w, h, title, sub, fill)
        ys = {}
        yy = y0 + 56
        for p in pins:
            label(x + w - 6, yy + 4, p, 11, "end")
            ys[p] = yy
            yy += 26
        return ys, y0 + h

    left_used = {}

    def wire_left(wid, py, px):
        w = next(x for x in WIRES if x[0] == wid)
        a, b = w[2], w[3]
        u1pin = a[1] if a[0] == "U1" else b[1]
        c = COLOURS[w[6]]
        line([(px, py), (NX0, py)], w[6])
        dot(px, py, c), dot(NX0, py, c)
        label(NX0 + 6, py + 4, f"{u1pin} {nucleo_pin(u1pin)}", 11)
        label(NX0 - 8, py - 4, wid, 10, "end", colour=c, weight="700")
        left_used[wid] = py

    def to_rail(wid, py, px, rail_x):
        w = next(x for x in WIRES if x[0] == wid)
        line([(px, py), (rail_x, py)], w[6])
        dot(rail_x, py, COLOURS[w[6]])
        label(px + 6, py - 4, wid, 10, colour=COLOURS[w[6]], weight="700")

    # rail feeds from U1
    for wid, py, rx in (("W20", TOP + 58, RAIL3), ("W21", TOP + 84, RAILG)):
        w = next(x for x in WIRES if x[0] == wid)
        line([(rx, py), (NX0, py)], w[6])
        dot(rx, py, COLOURS[w[6]]), dot(NX0, py, COLOURS[w[6]])
        label(NX0 + 6, py + 4, f"{w[2][1]} {nucleo_pin(w[2][1])}", 11)
        label(NX0 - 8, py - 4, wid, 10, "end", colour=COLOURS[w[6]], weight="700")

    PX, PW = 150, 200
    ys, yend = periph(PX, TOP + 104, PW, "U3 AS5047P", "on bracket over the shaft magnet",
                      ["CLK", "MISO", "MOSI", "CSn", "VDD3V3", "GND"], "#eef7ee")
    for wid, p in (("W22", "CLK"), ("W23", "MISO"), ("W24", "MOSI"), ("W25", "CSn")):
        wire_left(wid, ys[p], PX + PW)
    to_rail("W26", ys["VDD3V3"], PX + PW, RAIL3)
    to_rail("W27", ys["GND"], PX + PW, RAILG)

    ys2, yend2 = periph(PX, yend + 20, PW, "U4 SN65HVD230", "plugged into the breadboard",
                        ["CTX", "CRX", "3V3", "GND"], "#f3eef9")
    for wid, p in (("W30", "CTX"), ("W31", "CRX")):
        wire_left(wid, ys2[p], PX + PW)
    to_rail("W28", ys2["3V3"], PX + PW, RAIL3)
    to_rail("W29", ys2["GND"], PX + PW, RAILG)
    # CANable to the left
    box(20, yend + 20, 110, 120, "U5 CANable", "120 Ω ON → PC")
    for i, (wid, nm) in enumerate((("W32", "CANH"), ("W33", "CANL"), ("W34", "GND"))):
        yy = yend + 80 + i * 22
        w = next(x for x in WIRES if x[0] == wid)
        line([(130, yy), (PX, yy)], w[6])
        label(134, yy - 3, f"{wid} {nm}", 9, colour=COLOURS[w[6]], weight="700")

    ys3, yend3 = periph(PX, yend2 + 20, PW, "NTC dividers (BB)", "R1/C1/RT1 · R2/C2/RT2",
                        ["NTC_FET", "NTC_MOT"], "#fdf6e3")
    wire_left("W35", ys3["NTC_FET"], PX + PW)
    wire_left("W36", ys3["NTC_MOT"], PX + PW)
    label(PX + 4, yend3 + 16, "RT1 (W37/W38) taped on FETs · RT2 (W39/W40) on motor", 10, colour="#666")

    ys4, yend4 = periph(PX, yend3 + 30, PW, "SCOPE", "probe GND → rig GND only", ["CH4"], "#f4f6f8")
    wire_left("W41", ys4["CH4"], PX + PW)

    # motor and power harness
    mx, my = 1440, 520
    for i, ph in enumerate(("A", "B", "C")):
        w = next(x for x in WIRES if x[3] == ("M1", ph))
        yy = my - 40 + i * 40
        line([(BX1, yy), (mx - 52, yy)], w[6], 3.2)
        dot(BX1, yy, COLOURS[w[6]])
        label(BX1 - 6, yy + 4, f"J5.{ph}", 11, "end")
        label(BX1 + 8, yy - 5, f"{w[0]} PH_{ph}", 10, colour=COLOURS[w[6]], weight="700")
    add(f'<circle cx="{mx}" cy="{my}" r="55" fill="#e9f5ec" stroke="#555"/>')
    label(mx, my - 2, "M1 5010", 13, "middle", weight="700")
    label(mx, my + 15, "clamped", 10, "middle", "#555")
    label(mx, my + 78, "magnet on shaft ↔ U3 (1–2 mm)", 10, "middle", "#555")

    hy = 92
    for x, w_, t, sub in ((780, 110, "PSU", "12→24 V, I-limit"), (920, 90, "F1 10 A", "inline fuse"),
                          (1040, 120, "D1 MBR2045CT", "A1+A2 → K"), (1190, 170, "PB bus node", "C3 C4 2200 µF · D2 TVS")):
        box(x, hy - 30, w_, 52, t, sub, "#fdeaea")
    line([(890, hy - 4), (920, hy - 4)], "red", 3.2); label(892, hy - 10, "P01", 10, colour="#d62728", weight="700")
    line([(1010, hy - 4), (1040, hy - 4)], "red", 3.2); label(1012, hy - 10, "P02", 10, colour="#d62728", weight="700")
    line([(1160, hy - 4), (1190, hy - 4)], "red", 3.2); label(1162, hy - 10, "P03", 10, colour="#d62728", weight="700")
    line([(1230, hy + 22), (1230, TOP)], "red", 3.2); label(1224, TOP - 10, "P04 → VM+", 10, "end", colour="#d62728", weight="700")
    line([(835, hy + 22), (835, 132), (1320, 132), (1320, hy + 22)], "black", 3.2)
    label(845, 128, "P05 PSU − → bus −", 10, colour="#222", weight="700")
    line([(1320, 132), (1320, 140), (1270, 140), (1270, TOP)], "black", 3.2)
    label(1276, TOP - 10, "P06 → GND", 10, colour="#222", weight="700")
    label(780, 50, "E-stop: on the PSU mains side or its output-enable (not in the DC line)", 11, colour="#c62828")

    # legend
    lx, ly = 760, 950
    label(20, ly - 10, "Wire colours:", 12, weight="700")
    xx = 20
    for name in ("orange", "yellow", "purple", "blue", "green", "red", "black", "white", "grey", "brown"):
        line([(xx, ly + 4), (xx + 24, ly + 4)], name, 3)
        label(xx + 28, ly + 8, name, 11)
        xx += 92
    label(20, ly + 34, "Orange/yellow = PWM high/low · purple = EN/nFAULT · blue = SPI · green = analog · red/black = 3V3/GND · "
          "white/grey = CAN · brown = DAC debug · dashed = optional", 11, colour="#555")
    add("</svg>")
    Path(path).write_text("\n".join(s), encoding="utf-8")


def main():
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).with_name("rig_wiring_out")
    out.mkdir(parents=True, exist_ok=True)
    checks = run_checks()
    write_markdown(out / "Rig_Wiring_Reference.md", checks)
    write_csv(out / "rig_wire_list.csv")
    write_svg(out / "rig_wiring_diagram.svg", checks)
    nf = sum(1 for c in checks if c[0] == "FAIL")
    for st, msg in checks:
        print(f"[{st}] {msg}")
    print(f"\n{len(WIRES)} wires, {len(COMPONENTS)} components -> {out}")
    print("DRV8323 read words:", ", ".join(f"{n}=0x{drv8323_read(a):04X}" for a, n in DRV_REGS))
    print("AS5047P commands:  ", ", ".join(f"{n}=0x{as5047_cmd(a):04X}" for a, n in AS_REGS))
    sys.exit(1 if nf else 0)


if __name__ == "__main__":
    main()
