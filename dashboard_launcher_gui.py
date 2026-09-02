#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import subprocess
import sys
import tkinter as tk
from tkinter import filedialog
import webbrowser
from pathlib import Path

DASHBOARD_URL = "http://127.0.0.1:5070"


LAUNCHER_DIR = Path(os.getenv("APPDATA", str(Path.home()))) / "OptaValveDashboardLauncher"
LAUNCHER_CONFIG = LAUNCHER_DIR / "launcher_config.json"


def load_saved_base_dir() -> Path | None:
    try:
        payload = json.loads(LAUNCHER_CONFIG.read_text(encoding="utf-8"))
        saved = payload.get("project_dir", "")
        if saved:
            path = Path(saved)
            if (path / "run_dashboard.bat").exists():
                return path
    except Exception:
        pass
    return None


def save_base_dir(path: Path) -> None:
    LAUNCHER_DIR.mkdir(parents=True, exist_ok=True)
    LAUNCHER_CONFIG.write_text(json.dumps({"project_dir": str(path)}, indent=2), encoding="utf-8")


def detect_base_dir() -> Path:
    saved = load_saved_base_dir()
    if saved is not None:
        return saved

    # In a PyInstaller EXE, the executable usually lives in dist/ while
    # run_dashboard.bat is in the project root one level above.
    exe_dir = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
    candidates = [exe_dir, exe_dir.parent, Path.cwd()]
    for candidate in candidates:
        if (candidate / "run_dashboard.bat").exists():
            return candidate
    return exe_dir


BASE_DIR = detect_base_dir()
RUN_SCRIPT = BASE_DIR / "run_dashboard.bat"


class LauncherApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.process: subprocess.Popen[str] | None = None
        self.base_dir = BASE_DIR
        self.run_script = self.base_dir / "run_dashboard.bat"

        root.title("Opta Dashboard Launcher")
        root.geometry("860x360")
        root.minsize(640, 280)
        root.resizable(True, True)

        frame = tk.Frame(root, padx=16, pady=16)
        frame.pack(fill="both", expand=True)

        title = tk.Label(frame, text="Opta Valve Dashboard", font=("Segoe UI", 14, "bold"))
        title.pack(anchor="w")

        desc = tk.Label(
            frame,
            text="Start/stop the dashboard service manually and open it in your browser when needed.",
            font=("Segoe UI", 10),
            anchor="w",
            justify="left",
            wraplength=700,
        )
        desc.pack(anchor="w", fill="x", pady=(6, 12))

        self.status_label = tk.Label(
            frame,
            text=f"Status: stopped | Script: {self.run_script}",
            font=("Segoe UI", 10),
            anchor="w",
            justify="left",
            wraplength=820,
        )
        self.status_label.pack(anchor="w", fill="x", pady=(0, 12))

        self.path_label = tk.Label(
            frame,
            text=f"Projektordner: {self.base_dir}",
            font=("Segoe UI", 9),
            anchor="w",
            justify="left",
            wraplength=820,
        )
        self.path_label.pack(anchor="w", fill="x", pady=(0, 12))

        button_row = tk.Frame(frame)
        button_row.pack(anchor="w", pady=(0, 10))

        tk.Button(button_row, text="Start Dashboard", width=16, command=self.start_dashboard).pack(side="left")
        tk.Button(button_row, text="Stop Dashboard", width=16, command=self.stop_dashboard).pack(side="left", padx=(8, 0))
        tk.Button(button_row, text="Select Folder", width=16, command=self.select_folder).pack(side="left", padx=(8, 0))

        link = tk.Label(frame, text=DASHBOARD_URL, fg="#0a66c2", cursor="hand2", font=("Segoe UI", 10, "underline"))
        link.pack(anchor="w")
        link.bind("<Button-1>", lambda _evt: self.open_dashboard())

        tk.Button(frame, text="Open Dashboard", width=16, command=self.open_dashboard).pack(anchor="w", pady=(10, 0))

        root.protocol("WM_DELETE_WINDOW", self.on_close)

    def select_folder(self) -> None:
        selected = filedialog.askdirectory(initialdir=str(self.base_dir))
        if not selected:
            return

        path = Path(selected)
        script = path / "run_dashboard.bat"
        if not script.exists():
            self.status_label.config(text=f"Status: run_dashboard.bat not found in {path}")
            return

        self.base_dir = path
        self.run_script = script
        save_base_dir(path)
        self.path_label.config(text=f"Projektordner: {self.base_dir}")
        self.status_label.config(text=f"Status: folder set | Script: {self.run_script}")

    def start_dashboard(self) -> None:
        if self.process is not None and self.process.poll() is None:
            self.status_label.config(text="Status: already running")
            return

        if not self.run_script.exists():
            self.status_label.config(text=f"Status: run_dashboard.bat not found at {self.run_script}")
            return

        self.process = subprocess.Popen(
            ["cmd", "/c", str(self.run_script)],
            cwd=str(self.base_dir),
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        self.status_label.config(text=f"Status: running (PID {self.process.pid}) | Script: {self.run_script}")

    def stop_dashboard(self) -> None:
        if self.process is None or self.process.poll() is not None:
            self.status_label.config(text="Status: already stopped")
            return

        subprocess.run(
            ["taskkill", "/PID", str(self.process.pid), "/T", "/F"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.status_label.config(text="Status: stopped")

    def open_dashboard(self) -> None:
        webbrowser.open(DASHBOARD_URL)

    def on_close(self) -> None:
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    LauncherApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
