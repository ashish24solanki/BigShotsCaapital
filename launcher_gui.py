import os
import sys
import subprocess
import threading
import tkinter as tk
from tkinter import messagebox

# ======================================================
# PATH RESOLUTION (WORKS FOR EXE + SOURCE)
# ======================================================
if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

BASE_DIR = os.path.dirname(sys.executable if getattr(sys, "frozen", False) else os.path.abspath(__file__))
MAIN_DIR = os.path.join(BASE_DIR, "main")


SCRIPTS = {
    "market": os.path.join(MAIN_DIR, "market_data_updater.py"),
    "strategy": os.path.join(MAIN_DIR, "strategy_engine.py"),
    "membership": os.path.join(MAIN_DIR, "membership_bot.py"),
}

# ======================================================
# GUI APP
# ======================================================
class ControlPanel(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title("BigShots Capital Control Panel")
        self.geometry("650x420")
        self.resizable(False, False)

        self.processes = {}

        self.build_ui()
        self.poll_processes()

    # --------------------------------------------------
    def build_ui(self):
        tk.Label(
            self,
            text="BigShots Capital",
            font=("Segoe UI", 22, "bold"),
        ).pack(pady=10)

        tk.Label(
            self,
            text=(
                "Market Data → database/market_ohlc.db\n"
                "Strategy → exports/*.xlsx + Telegram\n"
                "Membership → database/members.db"
            ),
            font=("Segoe UI", 9),
            fg="gray",
        ).pack(pady=5)

        self.rows = {}

        container = tk.Frame(self)
        container.pack(pady=20)

        self.create_row(container, "Market Data Updater", "market")
        self.create_row(container, "Strategy Engine", "strategy")
        self.create_row(container, "Membership Bot", "membership")

        tk.Button(
            self,
            text="Exit",
            width=18,
            height=2,
            command=self.exit_app,
        ).pack(pady=20)

    # --------------------------------------------------
    def create_row(self, parent, label, key):
        row = tk.Frame(parent)
        row.pack(fill="x", pady=8)

        tk.Label(
            row,
            text=label,
            font=("Segoe UI", 11, "bold"),
            width=20,
            anchor="w",
        ).pack(side="left", padx=5)

        status = tk.Label(
            row,
            text="Idle",
            font=("Segoe UI", 10),
            fg="gray",
            width=10,
        )
        status.pack(side="left")

        run_btn = tk.Button(
            row,
            text="Run",
            width=10,
            height=2,
            command=lambda k=key: self.run_script(k),
        )
        run_btn.pack(side="left", padx=5)

        stop_btn = tk.Button(
            row,
            text="Stop",
            width=10,
            height=2,
            command=lambda k=key: self.stop_script(k),
        )
        stop_btn.pack(side="left", padx=5)

        self.rows[key] = {
            "status": status,
            "run": run_btn,
            "stop": stop_btn,
        }

    # --------------------------------------------------
    def run_script(self, key):
        if key in self.processes and self.processes[key].poll() is None:
            messagebox.showwarning("Already running", "Process already running")
            return

        script = SCRIPTS[key]
        if not os.path.exists(script):
            messagebox.showerror("Missing file", script)
            return

        try:
            proc = subprocess.Popen(
                [sys.executable, script],
                cwd=BASE_DIR,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self.processes[key] = proc
            self.set_status(key, "Running", "green")
        except Exception as e:
            self.set_status(key, "Error", "red")
            messagebox.showerror("Execution failed", str(e))

    # --------------------------------------------------
    def stop_script(self, key):
        proc = self.processes.get(key)
        if proc and proc.poll() is None:
            proc.terminate()
            self.set_status(key, "Stopped", "orange")
        else:
            self.set_status(key, "Idle", "gray")

    # --------------------------------------------------
    def poll_processes(self):
        for key, proc in list(self.processes.items()):
            if proc.poll() is not None:
                if proc.returncode == 0:
                    self.set_status(key, "Completed", "blue")
                else:
                    self.set_status(key, "Error", "red")
                del self.processes[key]

        self.after(1000, self.poll_processes)

    # --------------------------------------------------
    def set_status(self, key, text, color):
        lbl = self.rows[key]["status"]
        lbl.config(text=text, fg=color)

    # --------------------------------------------------
    def exit_app(self):
        for proc in self.processes.values():
            if proc.poll() is None:
                proc.terminate()
        self.destroy()


# ======================================================
if __name__ == "__main__":
    app = ControlPanel()
    app.mainloop()
