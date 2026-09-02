# Opta Valve Control Over Ethernet

This repository contains a complete two-part setup for Arduino Finder Opta + AFX00007:

1. Opta firmware that exposes `/data.json` and `/control.json` over Ethernet.
2. A laptop dashboard server (Flask) to control valves and display all four 4-20 mA inputs.
3. An optional desktop EXE launcher to start the dashboard without opening a terminal.

## Control Rules Implemented

- Valve 1 (inlet): command on output channel O1, default closed.
  - 4 mA = closed
  - 20 mA = fully open
  - Command range is clamped to 4-20 mA

- Valve 2 (outlet): command on output channel O2, default open.
  - Safety rule: it is never commanded below 18 mA
  - Command range is clamped to 18-20 mA

- Inputs shown in dashboard:
  - Klappe Eingang (from I1): shown in degrees (4 mA = 0 deg, 20 mA = 90 deg)
  - Klappe HWE (from I2): shown in degrees (4 mA = 0 deg, 20 mA = 90 deg)
  - I3: flowmeter (mA + converted to 0-200 l/s)
  - Pegel (from I4): shown in cm (4 mA = 0 cm, 20 mA = 100 cm)

- Commands shown in dashboard:
  - Klappe Eingang command in degrees (0-90, internally converted to 4-20 mA)
  - Klappe HWE command in degrees (safety-clamped equivalent of 18-20 mA)

## Repository Layout

- `arduino/opta_valve_controller/opta_valve_controller.ino`
- `opta_laptop_dashboard.py`
- `templates/index.html`
- `static/style.css`
- `static/app.js`
- `requirements.txt`
- `run_dashboard.bat`
- `dashboard_launcher_gui.py`
- `build_dashboard_launcher_exe.bat`

## 1) Flash The Opta Firmware

1. Open `arduino/opta_valve_controller/opta_valve_controller.ino` in Arduino IDE.
2. Install required libraries:
   - `Arduino_Opta_Blueprint`
   - `Ethernet` (if not already available for your core)
3. Verify/update network settings at top of sketch:
   - `MAC_ADDRESS`
   - `STATIC_IP`, `GATEWAY_IP`, `SUBNET_MASK`
4. Verify/update channel mapping constants if your AFX00007 wiring differs.
5. Upload via USB.

After upload, test from a browser on same LAN:

- `http://<opta-ip>/data.json`
- `http://<opta-ip>/control.json`

## 2) Run The Laptop Dashboard

From this repository root:

```powershell
.\run_dashboard.bat
```

Then open:

- `http://127.0.0.1:5070`

In the dashboard:

1. Set Opta host/IP and port.
2. Adjust valve commands in degrees.
3. View live I1-I4 values and flow conversion.
4. Pegel is always converted as 4 mA = 0 cm and 20 mA = 100 cm.
5. Start/stop logging from "Datenlogging" and provide a custom log name.

## CSV Logging Format

- Sampling interval: 1 second
- Output folder: `logs/`
- Filename: `<name>_YYYY_MM_DD_hh_mm_ss.csv`
- Row 1: column names
- Row 2: units
- Row 3+: data rows

First two columns:

1. `timestamp` with format `YYYY_MM_DD_hh_mm_ss_ms`
2. `runtime_s` as seconds from logging start

Then data columns for measured and controlled values:

- I1: mA and deg
- I2: mA and deg
- I3: mA and l/s (4 mA = 0, 20 mA = 200)
- I4: mA and cm
- Command Klappe Eingang: mA and deg
- Command Klappe HWE: mA and deg

## 3) Build EXE Launcher (No Terminal Needed)

From this repository root, run:

```powershell
.\build_dashboard_launcher_exe.bat
```

This creates:

- `dist/OptaValveDashboardLauncher.exe`

When started, the EXE:

1. Starts the dashboard in the background.
2. Opens a small window with controls.
3. Shows a clickable link to `http://127.0.0.1:5070`.

## API Contract

Firmware endpoints:

- `GET /data.json`
  - returns `i1_mA`, `i2_mA`, `i3_mA`, `i4_mA`, `flow_l_s`, valve command echoes, and running state.
- `GET /control.json`
  - returns `running`, `valve1_cmd_mA`, `valve2_cmd_mA`.
- `POST /control.json`
  - accepts any subset of:
    - `running` (bool)
    - `valve1_cmd_mA` (float, clamped 4-20)
    - `valve2_cmd_mA` (float, clamped 18-20)

Dashboard server endpoints:

- `GET /api/state`
- `POST /api/config`
- `POST /api/valves`
- `POST /api/poll`

`POST /api/valves` accepts degree-based command fields:

- `valve1_cmd_deg` (0-90)
- `valve2_cmd_deg` (converted and safety-clamped to 18-20 mA equivalent)

## Notes

- Firmware currently uses simple HTTP parsing to keep dependencies small.
- If your analog expansion channel mapping differs from defaults, only update the constants near the top of the sketch.
- Safety behavior on startup is enforced in firmware: inlet closes (4 mA), outlet opens (20 mA).
