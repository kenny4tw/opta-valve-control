#!/usr/bin/env python3

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict

from flask import Flask, jsonify, render_template, request

APP = Flask(__name__)
BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "opta_valve_config.json"

DEFAULT_CONFIG: Dict[str, Any] = {
    "opta_host": "192.168.1.50",
    "opta_port": 80,
    "dashboard_port": 5070,
    "poll_interval_s": 1.0,
    "level_min": 0.0,
    "level_max": 100.0,
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
}


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def map_current_to_engineering(milli_amp: float, out_min: float, out_max: float) -> float:
    m = clamp(milli_amp, 4.0, 20.0)
    return out_min + ((m - 4.0) / 16.0) * (out_max - out_min)


def load_config() -> Dict[str, Any]:
    if not CONFIG_PATH.exists():
        CONFIG_PATH.write_text(json.dumps(DEFAULT_CONFIG, indent=2), encoding="utf-8")
        return dict(DEFAULT_CONFIG)
    try:
        cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        merged = dict(DEFAULT_CONFIG)
        merged.update(cfg)
        return merged
    except Exception:
        return dict(DEFAULT_CONFIG)


def save_config(config: Dict[str, Any]) -> None:
    CONFIG_PATH.write_text(json.dumps(config, indent=2, sort_keys=True), encoding="utf-8")


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

    with STATE_LOCK:
        level_min = float(STATE["config"].get("level_min", 0.0))
        level_max = float(STATE["config"].get("level_max", 100.0))

    flow_l_s = map_current_to_engineering(i3, 0.0, 300.0)
    level_value = map_current_to_engineering(i4, level_min, level_max)

    normalized = dict(data_payload)
    normalized["i1_mA"] = i1
    normalized["i2_mA"] = i2
    normalized["i3_mA"] = i3
    normalized["i4_mA"] = i4
    normalized["flow_l_s"] = flow_l_s
    normalized["level_value"] = level_value
    return normalized


def poll_once() -> None:
    base = get_opta_base_url()
    data_payload = fetch_json(f"{base}/data.json")
    control_payload = fetch_json(f"{base}/control.json")

    normalized_data = normalize_payload(data_payload)

    with STATE_LOCK:
        STATE["data"] = normalized_data
        STATE["control"].update(control_payload)
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


def push_control_to_opta(payload: Dict[str, Any]) -> Dict[str, Any]:
    base = get_opta_base_url()
    control_payload = fetch_json(f"{base}/control.json", method="POST", payload=payload)
    with STATE_LOCK:
        STATE["control"].update(control_payload)
    return control_payload


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
        if "level_min" in payload:
            STATE["config"]["level_min"] = float(payload["level_min"])
        if "level_max" in payload:
            STATE["config"]["level_max"] = float(payload["level_max"])
        save_config(STATE["config"])
    return jsonify({"ok": True, "config": STATE["config"]})


@APP.route("/api/valves", methods=["POST"])
def api_valves() -> Any:
    payload = request.get_json(force=True, silent=False) or {}
    forwarded: Dict[str, Any] = {}

    if "valve1_cmd_mA" in payload:
        forwarded["valve1_cmd_mA"] = clamp(float(payload["valve1_cmd_mA"]), 4.0, 20.0)

    if "valve2_cmd_mA" in payload:
        # Outlet valve safety: never below 18 mA.
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


def bootstrap_state() -> None:
    config = load_config()
    with STATE_LOCK:
        STATE["config"] = config


def main() -> None:
    bootstrap_state()
    poller = threading.Thread(target=poller_loop, daemon=True, name="opta-poller")
    poller.start()
    with STATE_LOCK:
        port = int(STATE["config"].get("dashboard_port", 5070))
    APP.run(host="0.0.0.0", port=port, debug=False)


if __name__ == "__main__":
    main()
