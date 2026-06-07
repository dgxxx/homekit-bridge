"""SunSpec Modbus register map constants for SolarEdge inverters.

Register addresses are 0-based (as used by pymodbus).
SunSpec uses a value register followed by a signed int16 scale-factor register
(SF); the decoded value = raw_value * 10^SF.

Note: exact registers vary by inverter model and firmware.  These constants
cover the SunSpec Common + Inverter model blocks typically found on SE series.
Verify against the live inverter on first connect and adjust if needed.
"""

# --- Common Model block (starts at 40000) ---
# (manufacturer, model, serial etc. — not needed for telemetry)

# --- Inverter Model block (starts at 40069 for single-phase) ---
# AC output power (W)  — 40083 in 1-based => 40082 0-based
AC_POWER = 40083       # int16, followed by SF at AC_POWER+1
AC_POWER_SF = 40084    # int16 scale-factor for AC_POWER

# AC energy (lifetime Wh) — used as fallback; today's energy needs site data
# SunSpec WH register 40093 (1-based) = 40092 0-based, uint32 (2 regs) + SF
AC_ENERGY_WH = 40093   # uint32 (2 regs), followed by SF at AC_ENERGY_WH+2

# Energy produced today (Wh) — SE-specific register, not part of SunSpec core
# Exposed on some models at 40226 (0-based). Fall back to 0 if unavailable.
ENERGY_TODAY = 40226   # int16 value + SF at +1

# --- Battery / Storage Model (SE-specific, address varies by model) ---
# Battery State of Charge (%) — typically at 62852 (0-based) for SE StorEdge
BATTERY_SOC = 62852    # uint16, direct percentage 0–100
