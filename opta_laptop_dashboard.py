#!/usr/bin/env python3

from __future__ import annotations

import csv
import json
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from flask import Flask, jsonify, render_template, request
from werkzeug.serving import make_server

BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
RUNTIME_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
APP = Flask(
    __name__,
    template_folder=str(BUNDLE_DIR / "templates"),
    static_folder=str(BUNDLE_DIR / "static"),
)
CONFIG_PATH = RUNTIME_DIR / "opta_valve_config.json"
LOG_DIR = RUNTIME_DIR / "logs"

DEFAULT_CONFIG: Dict[str, Any] = {
    "opta_host": "138.232.90.35",
    "opta_port": 80,
    "dashboard_port": 5070,
    "poll_interval_s": 1.0,
    "log_dir": "",
}

STATE_LOCK = threading.RLock()
STATE: Dict[str, Any] = {
    "config": dict(DEFAULT_CONFIG),
    "control": {
        "valve1_cmd_mA": 4.0,
        "valve2_cmd_mA": 20.0,
        "running": True,
    },
    "data": {},
    "last_poll": None,
    "last_error": None,
    "logging_enabled": False,
    "log_name": "",
    "log_filename": "",
    "log_started_at": None,
    "log_started_monotonic": None,
}

RUNTIME_LOCK = threading.RLock()
WORKERS_STARTED = False
SERVER_INSTANCE = None
SERVER_THREAD = None

CSV_NAME_ROW = [
    "timestamp",
    "runtime_s",
    "i1_klappe_eingang_mA",
    "i1_klappe_eingang_deg",
    "i2_klappe_hwe_mA",
    "i2_klappe_hwe_deg",
    "i3_flow_mA",
    "i3_flow_l_s",
    "i4_pegel_mA",
    "i4_pegel_cm",
    "cmd_klappe_eingang_mA",
    "cmd_klappe_eingang_deg",
    "cmd_klappe_hwe_mA",
    "cmd_klappe_hwe_deg",
]

CSV_UNIT_ROW = [
    "YYYY_MM_DD_hh_mm_ss_ms",
    "s",
    "mA",
    "deg",
    "mA",
    "deg",
    "mA",
    "l/s",
    "mA",
    "cm",
    "mA",
    "deg",
    "mA",
    "deg",
]


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def map_current_to_engineering(milli_amp: float, out_min: float, out_max: float) -> float:
    m = clamp(milli_amp, 4.0, 20.0)
    return out_min + ((m - 4.0) / 16.0) * (out_max - out_min)


def current_to_degrees(milli_amp: float) -> float:
    return map_current_to_engineering(milli_amp, 0.0, 90.0)


def degrees_to_current(degrees: float) -> float:
    d = clamp(degrees, 0.0, 90.0)
    return 4.0 + (d / 90.0) * 16.0


def enrich_control(control_payload: Dict[str, Any]) -> Dict[str, Any]:
    enriched = dict(control_payload)
    valve1_ma = clamp(float(enriched.get("valve1_cmd_mA", 4.0)), 4.0, 20.0)
    valve2_ma = clamp(float(enriched.get("valve2_cmd_mA", 20.0)), 18.0, 20.0)
    enriched["valve1_cmd_mA"] = valve1_ma
    enriched["valve2_cmd_mA"] = valve2_ma
    enriched["valve1_cmd_deg"] = current_to_degrees(valve1_ma)
    enriched["valve2_cmd_deg"] = current_to_degrees(valve2_ma)
    return enriched


def sanitize_log_name(name: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in name.strip())
    cleaned = cleaned.strip("_")
    return cleaned or "opta_log"


def now_file_timestamp() -> str:
    return datetime.now().strftime("%Y_%m_%d_%H_%M_%S")


def now_row_timestamp() -> str:
    now = datetime.now()
    return now.strftime("%Y_%m_%d_%H_%M_%S_") + f"{now.microsecond // 1000:03d}"


def create_log_file(log_name: str) -> str:
    log_dir = get_log_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    safe_name = sanitize_log_name(log_name)
    filename = f"{safe_name}_{now_file_timestamp()}.csv"
    path = log_dir / filename
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(CSV_NAME_ROW)
        writer.writerow(CSV_UNIT_ROW)
    return filename


def append_log_row(snapshot: Dict[str, Any], runtime_s: float) -> None:
    filename = snapshot.get("log_filename", "")
    if not filename:
        return

    path = get_log_dir() / filename
    data = snapshot.get("data", {})
    control = snapshot.get("control", {})

    row = [
        now_row_timestamp(),
        f"{runtime_s:.3f}",
        f"{float(data.get('i1_mA', 0.0)):.3f}",
        f"{float(data.get('i1_deg', 0.0)):.3f}",
        f"{float(data.get('i2_mA', 0.0)):.3f}",
        f"{float(data.get('i2_deg', 0.0)):.3f}",
        f"{float(data.get('i3_mA', 0.0)):.3f}",
        f"{float(data.get('flow_l_s', 0.0)):.3f}",
        f"{float(data.get('i4_mA', 0.0)):.3f}",
        f"{float(data.get('pegel_cm', 0.0)):.3f}",
        f"{float(control.get('valve1_cmd_mA', 0.0)):.3f}",
        f"{float(control.get('valve1_cmd_deg', 0.0)):.3f}",
        f"{float(control.get('valve2_cmd_mA', 0.0)):.3f}",
        f"{float(control.get('valve2_cmd_deg', 0.0)):.3f}",
    ]

    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(row)


def load_config() -> Dict[str, Any]:
    if not CONFIG_PATH.exists():
        CONFIG_PATH.write_text(json.dumps(DEFAULT_CONFIG, indent=2), encoding="utf-8")
        return dict(DEFAULT_CONFIG)
    try:
        cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        # Migrate the old starter IP to the new default unless the user already customized it.
        if cfg.get("opta_host") == "192.168.1.50":
            cfg["opta_host"] = DEFAULT_CONFIG["opta_host"]
            CONFIG_PATH.write_text(json.dumps(cfg, indent=2, sort_keys=True), encoding="utf-8")
        merged = dict(DEFAULT_CONFIG)
        merged.update(cfg)
        return merged
    except Exception:
        return dict(DEFAULT_CONFIG)


def save_config(config: Dict[str, Any]) -> None:
    CONFIG_PATH.write_text(json.dumps(config, indent=2, sort_keys=True), encoding="utf-8")


def get_log_dir() -> Path:
    with STATE_LOCK:
        configured = str(STATE["config"].get("log_dir", "")).strip()
    if configured:
        return Path(configured)
    return LOG_DIR


def get_opta_base_url() -> str:
    with STATE_LOCK:
        host = str(STATE["config"]["opta_host"])
        port = int(STATE["config"]["opta_port"])
    return f"http://{host}:{port}"


def fetch_json(url: str, method: str = "GET", payload: Dict[str, Any] | None = None) -> Dict[str, Any]:
    body = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url=url, headers=headers, data=body, method=method)
    with urllib.request.urlopen(req, timeout=3) as resp:
        text = resp.read().decode("utf-8")
        return json.loads(text)


def normalize_payload(data_payload: Dict[str, Any]) -> Dict[str, Any]:
    i1 = float(data_payload.get("i1_mA", 0.0))
    i2 = float(data_payload.get("i2_mA", 0.0))
    i3 = float(data_payload.get("i3_mA", 0.0))
    i4 = float(data_payload.get("i4_mA", 0.0))

    flow_l_s = map_current_to_engineering(i3, 0.0, 200.0)
    pegel_cm = map_current_to_engineering(i4, 0.0, 100.0)

    normalized = dict(data_payload)
    normalized["i1_mA"] = i1
    normalized["i2_mA"] = i2
    normalized["i3_mA"] = i3
    normalized["i4_mA"] = i4
    normalized["i1_deg"] = current_to_degrees(i1)
    normalized["i2_deg"] = current_to_degrees(i2)
    normalized["flow_l_s"] = flow_l_s
    normalized["pegel_cm"] = pegel_cm
    return normalized


def poll_once() -> None:
    base = get_opta_base_url()
    data_payload = fetch_json(f"{base}/data.json")
    control_payload = fetch_json(f"{base}/control.json")

    normalized_data = normalize_payload(data_payload)

    with STATE_LOCK:
        STATE["data"] = normalized_data
        STATE["control"] = enrich_control(control_payload)
        STATE["last_poll"] = time.strftime("%Y-%m-%d %H:%M:%S")
        STATE["last_error"] = None


def poller_loop() -> None:
    while True:
        with STATE_LOCK:
            interval = float(STATE["config"].get("poll_interval_s", 1.0))
        try:
            poll_once()
        except urllib.error.URLError as exc:
            with STATE_LOCK:
                STATE["last_error"] = f"Network error: {exc}"
        except Exception as exc:
            with STATE_LOCK:
                STATE["last_error"] = str(exc)
        time.sleep(max(0.25, interval))


def logger_loop() -> None:
    next_tick = time.monotonic()
    while True:
        now = time.monotonic()
        if now < next_tick:
            time.sleep(min(0.2, next_tick - now))
            continue

        next_tick += 1.0

        with STATE_LOCK:
            enabled = bool(STATE.get("logging_enabled", False))
            start_mono = STATE.get("log_started_monotonic")
            snapshot = {
                "log_filename": STATE.get("log_filename", ""),
                "data": dict(STATE.get("data", {})),
                "control": dict(STATE.get("control", {})),
            }

        if not enabled or start_mono is None:
            continue

        runtime_s = max(0.0, now - float(start_mono))
        try:
            append_log_row(snapshot, runtime_s)
        except Exception as exc:
            with STATE_LOCK:
                STATE["last_error"] = f"Logging error: {exc}"


def push_control_to_opta(payload: Dict[str, Any]) -> Dict[str, Any]:
    base = get_opta_base_url()
    control_payload = fetch_json(f"{base}/control.json", method="POST", payload=payload)
    with STATE_LOCK:
        STATE["control"] = enrich_control(control_payload)
    return enrich_control(control_payload)


@APP.route("/")
def index() -> str:
    return render_template("index.html")


@APP.route("/api/state", methods=["GET"])
def api_state() -> Any:
    with STATE_LOCK:
        return jsonify(dict(STATE))


@APP.route("/api/config", methods=["POST"])
def api_config() -> Any:
    payload = request.get_json(force=True, silent=False) or {}
    with STATE_LOCK:
        if "opta_host" in payload:
            STATE["config"]["opta_host"] = str(payload["opta_host"])
        if "opta_port" in payload:
            STATE["config"]["opta_port"] = int(payload["opta_port"])
        if "poll_interval_s" in payload:
            STATE["config"]["poll_interval_s"] = max(0.25, float(payload["poll_interval_s"]))
        if "log_dir" in payload:
            STATE["config"]["log_dir"] = str(payload["log_dir"])
        save_config(STATE["config"])
    return jsonify({"ok": True, "config": STATE["config"]})


@APP.route("/api/select-log-folder", methods=["POST"])
def api_select_log_folder() -> Any:
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        selected = filedialog.askdirectory(initialdir=str(get_log_dir()))
        root.destroy()
    except Exception as exc:
        return jsonify({"ok": False, "error": f"Folder picker failed: {exc}"}), 500

    if not selected:
        return jsonify({"ok": False, "cancelled": True})

    with STATE_LOCK:
        STATE["config"]["log_dir"] = selected
        save_config(STATE["config"])

    return jsonify({"ok": True, "log_dir": selected})


@APP.route("/api/valves", methods=["POST"])
def api_valves() -> Any:
    payload = request.get_json(force=True, silent=False) or {}
    forwarded: Dict[str, Any] = {}

    if "valve1_cmd_deg" in payload:
        forwarded["valve1_cmd_mA"] = clamp(degrees_to_current(float(payload["valve1_cmd_deg"])), 4.0, 20.0)
    elif "valve1_cmd_mA" in payload:
        forwarded["valve1_cmd_mA"] = clamp(float(payload["valve1_cmd_mA"]), 4.0, 20.0)

    if "valve2_cmd_deg" in payload:
        # Outlet valve safety: never below 18 mA.
        forwarded["valve2_cmd_mA"] = clamp(degrees_to_current(float(payload["valve2_cmd_deg"])), 18.0, 20.0)
    elif "valve2_cmd_mA" in payload:
        forwarded["valve2_cmd_mA"] = clamp(float(payload["valve2_cmd_mA"]), 18.0, 20.0)

    if "running" in payload:
        forwarded["running"] = bool(payload["running"])

    if not forwarded:
        return jsonify({"ok": False, "error": "No valid fields supplied"}), 400

    try:
        control_payload = push_control_to_opta(forwarded)
    except Exception as exc:
        with STATE_LOCK:
            STATE["last_error"] = str(exc)
        return jsonify({"ok": False, "error": str(exc)}), 502

    try:
        poll_once()
    except Exception:
        pass

    return jsonify({"ok": True, "control": control_payload})


@APP.route("/api/poll", methods=["POST"])
def api_poll() -> Any:
    try:
        poll_once()
        return jsonify({"ok": True})
    except Exception as exc:
        with STATE_LOCK:
            STATE["last_error"] = str(exc)
        return jsonify({"ok": False, "error": str(exc)}), 502


@APP.route("/api/logging", methods=["POST"])
def api_logging() -> Any:
    payload = request.get_json(force=True, silent=False) or {}
    enabled = bool(payload.get("enabled", False))
    requested_name = str(payload.get("name", "")).strip()

    with STATE_LOCK:
        if enabled:
            if not STATE.get("logging_enabled", False):
                filename = create_log_file(requested_name)
                STATE["log_name"] = sanitize_log_name(requested_name)
                STATE["log_filename"] = filename
                STATE["log_started_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                STATE["log_started_monotonic"] = time.monotonic()
            STATE["logging_enabled"] = True
        else:
            STATE["logging_enabled"] = False
            STATE["log_started_monotonic"] = None

        response_payload = {
            "ok": True,
            "logging_enabled": STATE["logging_enabled"],
            "log_name": STATE.get("log_name", ""),
            "log_filename": STATE.get("log_filename", ""),
            "log_started_at": STATE.get("log_started_at"),
        }

    return jsonify(response_payload)


def bootstrap_state() -> None:
    config = load_config()
    with STATE_LOCK:
        STATE["config"] = config


def get_dashboard_port() -> int:
    with STATE_LOCK:
        return int(STATE["config"].get("dashboard_port", 5070))


def get_dashboard_url(host: str = "127.0.0.1") -> str:
    return f"http://{host}:{get_dashboard_port()}"


def ensure_background_workers() -> None:
    global WORKERS_STARTED
    with RUNTIME_LOCK:
        if WORKERS_STARTED:
            return
        poller = threading.Thread(target=poller_loop, daemon=True, name="opta-poller")
        logger = threading.Thread(target=logger_loop, daemon=True, name="opta-logger")
        poller.start()
        logger.start()
        WORKERS_STARTED = True


def start_background_dashboard(host: str = "127.0.0.1") -> str:
    global SERVER_INSTANCE, SERVER_THREAD
    bootstrap_state()
    ensure_background_workers()

    with RUNTIME_LOCK:
        if SERVER_INSTANCE is not None:
            return get_dashboard_url(host)

        server = make_server(host, get_dashboard_port(), APP, threaded=True)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True, name="opta-http-server")
        server_thread.start()
        SERVER_INSTANCE = server
        SERVER_THREAD = server_thread

    return get_dashboard_url(host)


def stop_background_dashboard() -> None:
    global SERVER_INSTANCE, SERVER_THREAD
    with RUNTIME_LOCK:
        server = SERVER_INSTANCE
        server_thread = SERVER_THREAD
        SERVER_INSTANCE = None
        SERVER_THREAD = None

    if server is not None:
        server.shutdown()
    if server_thread is not None:
        server_thread.join(timeout=2.0)


def main() -> None:
    bootstrap_state()
    ensure_background_workers()
    APP.run(host="0.0.0.0", port=get_dashboard_port(), debug=False)


if __name__ == "__main__":
    main()
