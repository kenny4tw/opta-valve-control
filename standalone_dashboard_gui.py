#!/usr/bin/env python3

from __future__ import annotations

import tkinter as tk
import webbrowser

from opta_laptop_dashboard import get_dashboard_url, start_background_dashboard, stop_background_dashboard


class StandaloneDashboardApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.running = False
        self.url = get_dashboard_url()

        root.title("Opta Valve Dashboard")
        root.geometry("760x300")
        root.minsize(620, 260)
        root.resizable(True, True)

        frame = tk.Frame(root, padx=18, pady=18)
        frame.pack(fill="both", expand=True)

        tk.Label(frame, text="Opta Valve Dashboard", font=("Segoe UI", 16, "bold")).pack(anchor="w")
        tk.Label(
            frame,
            text="Standalone dashboard host. Start or stop the local web server and open the dashboard in your browser.",
            font=("Segoe UI", 10),
            justify="left",
            anchor="w",
            wraplength=700,
        ).pack(anchor="w", fill="x", pady=(8, 14))

        self.status_label = tk.Label(
            frame,
            text="Status: stopped",
            font=("Segoe UI", 10),
            justify="left",
            anchor="w",
            wraplength=700,
        )
        self.status_label.pack(anchor="w", fill="x", pady=(0, 10))

        self.url_label = tk.Label(
            frame,
            text=self.url,
            fg="#0a66c2",
            cursor="hand2",
            font=("Segoe UI", 10, "underline"),
        )
        self.url_label.pack(anchor="w")
        self.url_label.bind("<Button-1>", lambda _evt: self.open_dashboard())

        button_row = tk.Frame(frame)
        button_row.pack(anchor="w", pady=(16, 0))

        tk.Button(button_row, text="Start Dashboard", width=16, command=self.start_dashboard).pack(side="left")
        tk.Button(button_row, text="Stop Dashboard", width=16, command=self.stop_dashboard).pack(side="left", padx=(8, 0))
        tk.Button(button_row, text="Open Dashboard", width=16, command=self.open_dashboard).pack(side="left", padx=(8, 0))

        root.protocol("WM_DELETE_WINDOW", self.on_close)

    def start_dashboard(self) -> None:
        try:
            self.url = start_background_dashboard()
            self.running = True
            self.url_label.config(text=self.url)
            self.status_label.config(text=f"Status: running | URL: {self.url}")
        except Exception as exc:
            self.status_label.config(text=f"Status: start failed | {exc}")

    def stop_dashboard(self) -> None:
        try:
            stop_background_dashboard()
            self.running = False
            self.status_label.config(text="Status: stopped")
        except Exception as exc:
            self.status_label.config(text=f"Status: stop failed | {exc}")

    def open_dashboard(self) -> None:
        webbrowser.open(self.url)

    def on_close(self) -> None:
        if self.running:
            try:
                stop_background_dashboard()
            except Exception:
                pass
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    StandaloneDashboardApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
