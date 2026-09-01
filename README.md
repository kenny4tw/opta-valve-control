# Opta Valve Control Over Ethernet

This repository contains a complete two-part setup for Arduino Finder Opta + AFX00007:

1. Opta firmware that exposes `/data.json` and `/control.json` over Ethernet.
2. A laptop dashboard server (Flask) to control valves and display all four 4-20 mA inputs.

## Control Rules Implemented

- Valve 1 (inlet): command on output channel O1, default closed.
  - 4 mA = closed
  - 20 mA = fully open
  - Command range is clamped to 4-20 mA

- Valve 2 (outlet): command on output channel O2, default open.
  - Safety rule: it is never commanded below 18 mA
  - Command range is clamped to 18-20 mA

- Inputs shown in dashboard:
  - I1: valve 1 position feedback (mA)
  - I2: valve 2 position feedback (mA)
  - I3: flowmeter (mA + converted to 0-300 l/s)
  - I4: ultrasonic level (mA + converted using configurable 4 mA and 20 mA scaling)

## Repository Layout

- `arduino/opta_valve_controller/opta_valve_controller.ino`
- `opta_laptop_dashboard.py`
- `templates/index.html`
- `static/style.css`
- `static/app.js`
- `requirements.txt`
- `run_dashboard.bat`

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
2. Adjust valve commands.
3. View live I1-I4 values and flow conversion.
4. Set level scaling (`level_min`, `level_max`) for I4 conversion.

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

## Notes

- Firmware currently uses simple HTTP parsing to keep dependencies small.
- If your analog expansion channel mapping differs from defaults, only update the constants near the top of the sketch.
- Safety behavior on startup is enforced in firmware: inlet closes (4 mA), outlet opens (20 mA).
