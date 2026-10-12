"""Graphical Windows installer; release users do not need Python installed."""

import argparse
import ctypes
import json
import os
from pathlib import Path
import queue
import re
import subprocess
import sys
import tempfile
import threading
import time
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk

import campus_login_windows as windows
from setup_i18n import (LANGUAGES, SetupError, error_message, preferred_language,
                        save_language, translate)


ASSETS = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
INSTALL_DIR = Path(os.environ.get("ProgramW6432") or os.environ.get("ProgramFiles")
                   or r"C:\Program Files") / "CampusLogin"
LOG = INSTALL_DIR / "campus-login.log"
# Where 0.1.0 installed; read only to carry settings over on the first upgrade.
LEGACY_DIR = Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "CampusLogin"
VERSION = (ASSETS / "VERSION").read_text(encoding="utf-8").strip()


def powershell():
    return str(Path(os.environ["SystemRoot"]) / "System32" / "WindowsPowerShell"
               / "v1.0" / "powershell.exe")


def ensure_administrator():
    """Relaunch the directory-based setup through UAC before asking for secrets."""
    shell = ctypes.WinDLL("shell32", use_last_error=True)
    shell.IsUserAnAdmin.restype = ctypes.c_bool
    if shell.IsUserAnAdmin():
        return True
    shell.ShellExecuteW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_wchar_p,
                                  ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_int]
    shell.ShellExecuteW.restype = ctypes.c_void_p
    arguments = sys.argv[1:]
    if not getattr(sys, "frozen", False):
        arguments = [str(Path(__file__).resolve()), *arguments]
    result = shell.ShellExecuteW(None, "runas", sys.executable,
                                subprocess.list2cmdline(arguments), None, 1)
    if not result or result <= 32:
        raise SetupError("admin_required")
    return False


def installer_command(credential, network, interface, *, preview=False):
    command = [powershell(), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
               "-File", str(ASSETS / "install-campus-login.ps1"),
               "-LoginExecutable", str(ASSETS / "campus-login.exe"),
               "-CredentialPath", str(credential), "-Network", network, "-Interface", interface]
    if preview:
        command.append("-WhatIf")
    return command


def run_command(command):
    environment = os.environ.copy()
    environment.pop("PSModulePath", None)
    environment.pop("PSMODULEPATH", None)
    result = subprocess.run(command, capture_output=True, encoding="utf-8", errors="replace",
                            creationflags=subprocess.CREATE_NO_WINDOW, timeout=120,
                            env=environment)
    if result.returncode:
        details = result.stderr.strip() or result.stdout.strip()
        if details:
            raise OSError(details)
        raise SetupError("command_failed")
    return result.stdout


def install(user, password, network, interface, *, preview=False):
    for name in ("campus-login.exe", "install-campus-login.ps1", "run-campus-login.ps1"):
        if not (ASSETS / name).is_file():
            raise SetupError("missing_asset", name=name)
    if not all(value.strip() for value in (user, password, network, interface)):
        raise SetupError("incomplete")
    # Protect the temporary file before writing any secrets; they never appear
    # in command-line arguments and the temporary copy is deleted on exit.
    with tempfile.TemporaryDirectory(prefix="campus-setup-") as directory:
        credential = Path(directory) / "credentials.json"
        credential.touch()
        windows.protect_credential(str(credential))
        credential.write_text(json.dumps({"user": user.strip(), "password": password},
                                         ensure_ascii=False), encoding="utf-8")
        return run_command(installer_command(credential, network.strip(), interface.strip(),
                                              preview=preview))


def uninstall(remove_data=False):
    command = [powershell(), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
               "-File", str(ASSETS / "install-campus-login.ps1"), "-Uninstall"]
    if remove_data:
        command.append("-RemoveData")
    return run_command(command)


# Keep the diagnostic logs unchanged; translate their plain-language summaries.
MESSAGES = (
    (r"logged in to (.+)", "logged_in"),
    (r"on (.+) and online", "online"),
    (r"login failed \((.*)\)", "login_failed"),
    (r"waiting for (.+) \(current network: (.*)\)", "waiting"),
    (r"network check failed: (.*)", "network_failed"),
    (r"no usable credentials", "credentials_unusable"),
    # Supervisor records (run-campus-login.ps1): newer failures must not be
    # hidden behind an older successful login.
    (r"Supervisor failed: (.*)", "supervisor_failed"),
    (r"Login process exited with code (-?\d+)", "process_exited"),
)


def describe(line, language="zh-CN"):
    """Plain-language summary of one log line, or None for unrecognised lines."""
    message = re.sub(r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d ", "", line.strip())
    message = re.sub(r"^(?!Supervisor )[^:]+: (?=(logged|on |login|waiting|network))", "", message)
    for pattern, key in MESSAGES:
        match = re.match(pattern, message)
        if match:
            return translate(key, language, *match.groups())
    return None


def read_status(language="zh-CN"):
    output = windows.run_powershell(
        "$task = Get-ScheduledTask -TaskName CampusLogin -TaskPath '\\' -ErrorAction SilentlyContinue; "
        "if ($task) { [string]$task.State } else { '' }"
    )
    try:
        lines = LOG.read_text(encoding="utf-8", errors="replace").splitlines()[-40:]
    except OSError:
        lines = []
    state = output.strip()
    return state, summarize(state, lines, language), lines


def summarize(state, lines, language="zh-CN"):
    """What a student should know now: the task state first, then the newest log record."""
    if state == "":
        return translate("task_absent", language)
    latest = next((text for line in reversed(lines)
                   if (text := describe(line, language))), None)
    if state != "Running":
        # A stopped task means nothing is being logged, so an old success would mislead.
        return translate("task_stopped", language) + (
            "\n" + translate("last_record", language, summary=latest) if latest else "")
    return latest


def wifi_choices():
    output = windows.run_powershell(
        "@(Get-NetAdapter -Physical | Where-Object { "
        "$_.NdisPhysicalMedium -in @(1,9) -and $_.Status -ne 'Not Present' } | "
        "Select-Object Name, Status) | ConvertTo-Json -Compress"
    )
    values = json.loads(output) if output else []
    if isinstance(values, dict):
        values = [values]
    return sorted(values, key=lambda item: item["Status"] != "Up")


class StatusWindow:
    def __init__(self, setup, result):
        self.setup = setup
        self.state, _, self.lines = result
        self.root = tk.Toplevel(setup.root)
        self.root.transient(setup.root)
        self.root.bind("<Destroy>", self.on_destroy)
        frame = ttk.Frame(self.root, padding=16)
        frame.pack(fill="both", expand=True)
        self.task = ttk.Label(frame, font=("Microsoft YaHei UI", 11, "bold"))
        self.task.pack(anchor="w")
        self.latest = ttk.Label(frame, wraplength=560)
        self.latest.pack(anchor="w", pady=(6, 10))
        self.heading = ttk.Label(frame, wraplength=560)
        self.heading.pack(anchor="w")
        self.log = scrolledtext.ScrolledText(frame, width=78, height=14, font=("Consolas", 9))
        self.log.pack(fill="both", expand=True, pady=(4, 10))
        self.close_button = ttk.Button(frame, command=self.root.destroy)
        self.close_button.pack(anchor="e")
        setup.status_windows.add(self)
        self.refresh_language()

    def on_destroy(self, event):
        if event.widget is self.root:
            self.setup.status_windows.discard(self)

    def refresh_language(self):
        tr = self.setup.tr
        states = {"Running": "state_running", "Ready": "state_ready",
                  "Disabled": "state_disabled", "Queued": "state_queued",
                  "Unknown": "state_unknown", "": "state_absent"}
        self.root.title(tr("status_title"))
        self.task.configure(text=tr("task_state", state=tr(states[self.state])
                                   if self.state in states else self.state))
        summary = summarize(self.state, self.lines, self.setup.language)
        self.latest.configure(text=tr("latest_result", summary=summary or tr("no_records")))
        self.heading.configure(text=tr("log_heading"))
        self.close_button.configure(text=tr("close"))
        if not self.lines or not self.log.get("1.0", "end-1c"):
            self.log.configure(state="normal")
            self.log.delete("1.0", "end")
            self.log.insert("1.0", "\n".join(self.lines) or tr("no_logs"))
            self.log.configure(state="disabled")
            self.log.see("end")


class SetupWindow:
    def __init__(self, root, *, discover=True, language=None):
        self.root = root
        self.events = queue.Queue()
        self.busy = False
        self.language = language if language in LANGUAGES else preferred_language()
        self.strings = {}
        self.status_windows = set()
        self.status_message = ("detecting" if discover else "ready", {})
        self.status_result = None
        root.resizable(False, False)
        root.protocol("WM_DELETE_WINDOW", self.close)
        ttk.Style(root).theme_use("vista")
        panel = ttk.Frame(root, padding=24)
        panel.grid(sticky="nsew")
        ttk.Label(panel, textvariable=self.text("heading"), font=("Microsoft YaHei UI", 18, "bold")).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))
        ttk.Label(panel, textvariable=self.text("introduction"), wraplength=520,
                  font=("Microsoft YaHei UI", 10)).grid(row=1, column=0, columnspan=2,
                                                       sticky="w", pady=(0, 20))
        language_row = ttk.Frame(panel)
        language_row.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(0, 12))
        ttk.Label(language_row, text="语言 / Language").pack(side="left", padx=(0, 16))
        self.language_choice = tk.StringVar(value=LANGUAGES[self.language])
        self.language_selector = ttk.Combobox(language_row, textvariable=self.language_choice,
                                              values=tuple(LANGUAGES.values()), state="readonly", width=16)
        self.language_selector.pack(side="right")
        self.language_selector.bind("<<ComboboxSelected>>", self.change_language)
        self.user = tk.StringVar()
        self.password = tk.StringVar()
        self.network = tk.StringVar(value="Tsinglan-School")
        self.interface = tk.StringVar()
        self.status = tk.StringVar()
        self.widgets = []
        fields = (("user", self.user), ("password", self.password), ("network", self.network))
        for row, (key, variable) in enumerate(fields, 3):
            ttk.Label(panel, textvariable=self.text(key)).grid(row=row, column=0, sticky="w", padx=(0, 16), pady=7)
            entry = ttk.Entry(panel, textvariable=variable, width=38,
                              show="●" if variable is self.password else "")
            entry.grid(row=row, column=1, sticky="ew", pady=7)
            self.widgets.append(entry)
        ttk.Label(panel, textvariable=self.text("interface")).grid(row=6, column=0, sticky="w", pady=7)
        self.adapter = ttk.Combobox(panel, textvariable=self.interface, width=36)
        self.adapter.grid(row=6, column=1, sticky="ew", pady=7)
        self.widgets.append(self.adapter)
        ttk.Label(panel, textvariable=self.text("network_hint"),
                  wraplength=520).grid(row=7, column=0, columnspan=2, sticky="w", pady=(5, 16))
        self.install_button = ttk.Button(panel, textvariable=self.text("install"), command=self.start_install)
        self.install_button.grid(row=8, column=0, columnspan=2, sticky="ew", ipady=5)
        controls = ttk.Frame(panel)
        controls.grid(row=9, column=0, columnspan=2, sticky="ew", pady=(10, 16))
        self.uninstall_button = ttk.Button(controls, textvariable=self.text("uninstall"), command=self.start_uninstall)
        self.uninstall_button.pack(side="left")
        # Not "open the folder": it is readable only by administrators, and
        # Explorer's "Continue" prompt would permanently grant the signed-in
        # user access to the saved password. This window already runs elevated.
        self.status_button = ttk.Button(controls, textvariable=self.text("view_status"), command=self.start_status)
        self.status_button.pack(side="right")
        ttk.Label(panel, textvariable=self.status, wraplength=520).grid(
            row=10, column=0, columnspan=2, sticky="w", pady=(0, 12))
        ttk.Separator(panel).grid(row=11, column=0, columnspan=2, sticky="ew")
        ttk.Label(panel, textvariable=self.text("credential_notice", path=INSTALL_DIR / "credentials.json"),
                  wraplength=520).grid(row=12, column=0, columnspan=2, sticky="w", pady=(12, 0))
        self.refresh_language()
        if discover:
            self.load_settings()
        self.widgets[0].focus_set()
        root.after(100, self.poll)
        if discover:
            self.background("adapters", wifi_choices)

    def tr(self, key, **values):
        return translate(key, self.language, **values)

    def text(self, key, **values):
        variable = tk.StringVar(value=self.tr(key, **values))
        self.strings[key] = (variable, values)
        return variable

    def change_language(self, event=None):
        self.language = next(code for code, name in LANGUAGES.items()
                             if name == self.language_choice.get())
        save_language(self.language)
        self.refresh_language()

    def refresh_language(self):
        self.root.title(self.tr("window_title", version=VERSION))
        for key, (variable, values) in self.strings.items():
            variable.set(self.tr(key, **values))
        key, values = self.status_message
        if key == "installed_follow_up":
            state, _, lines = self.status_result
            values = {"summary": summarize(state, lines, self.language) or self.tr("no_records")}
        self.status.set(self.tr(key, **values))
        for window in self.status_windows:
            window.refresh_language()

    def set_status(self, key, **values):
        self.status_message = (key, values)
        self.refresh_language()

    def load_settings(self):
        # Prefer the current installation; on the first upgrade from 0.1.0
        # fall back to its ProgramData settings, which the installer deletes
        # once the new installation succeeds.
        for directory in (INSTALL_DIR, LEGACY_DIR):
            try:
                config = json.loads((directory / "config.json").read_text(encoding="utf-8-sig"))
                network, interface = config["network"], config["interface"]
            except (OSError, ValueError, KeyError, TypeError):
                continue
            self.network.set(network)
            self.interface.set(interface)
            try:
                saved = json.loads((directory / "credentials.json").read_text(encoding="utf-8-sig"))
                self.user.set(saved.get("user", ""))
            except (OSError, ValueError, AttributeError):
                pass
            # Re-enter the password when updating; do not display saved secrets.
            return

    def background(self, action, function, *arguments):
        def work():
            try:
                self.events.put((action, function(*arguments), None))
            except Exception as error:
                self.events.put((action, None, error))
        threading.Thread(target=work, daemon=True).start()

    def set_busy(self, value):
        self.busy = value
        for widget in (*self.widgets, self.install_button, self.uninstall_button, self.status_button):
            widget.configure(state="disabled" if value else "normal")

    def start_install(self):
        values = tuple(variable.get() for variable in
                       (self.user, self.password, self.network, self.interface))
        if not all(value.strip() for value in values):
            messagebox.showerror(self.tr("incomplete_title"), self.tr("incomplete"), parent=self.root)
            return
        self.set_busy(True)
        self.set_status("installing")
        self.background("install", install, *values)

    def start_uninstall(self):
        answer = messagebox.askyesnocancel(
            self.tr("uninstall"), self.tr("uninstall_prompt"),
            parent=self.root)
        if answer is None:
            return
        self.set_busy(True)
        self.set_status("uninstalling")
        self.background("uninstall", uninstall, answer)

    def start_status(self):
        self.set_busy(True)
        self.set_status("reading_status")
        self.background("status", read_status)

    def show_status(self, result):
        return StatusWindow(self, result)

    def poll(self):
        while not self.events.empty():
            action, result, error = self.events.get_nowait()
            if action == "adapters":
                if error:
                    if not self.busy:
                        self.set_status("detection_failed")
                else:
                    self.adapter["values"] = tuple(item["Name"] for item in result)
                    connected = [item for item in result if item["Status"] == "Up"]
                    preferred = connected if len(connected) == 1 else result
                    if not self.interface.get() and len(preferred) == 1:
                        self.interface.set(preferred[0]["Name"])
                    if not self.busy:
                        self.set_status("confirm_settings")
                continue
            if action == "first-status":
                # Quiet follow-up after installing: show the first result, if any.
                if not error and result[1] and not self.busy and self.status_message[0] == "installed_pending":
                    self.status_result = result
                    self.set_status("installed_follow_up")
                continue
            self.set_busy(False)
            if error:
                self.set_status("retry")
                messagebox.showerror(self.tr("operation_failed"), error_message(error, self.language), parent=self.root)
            elif action == "status":
                self.set_status("ready")
                self.show_status(result)
            elif action == "install":
                self.password.set("")
                self.set_status("installed_pending")
                messagebox.showinfo(self.tr("installed_title"), self.tr("installed_message"), parent=self.root)
                self.background("first-status", lambda: (time.sleep(8), read_status())[1])
            else:
                self.set_status("uninstalled")
        self.root.after(100, self.poll)

    def close(self):
        if not self.busy:
            self.root.destroy()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke-test", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--uninstall", action="store_true")
    options = parser.parse_args()
    language = preferred_language()
    root = tk.Tk()
    root.withdraw()
    try:
        if options.smoke_test:
            window = SetupWindow(root, discover=False)
            root.update_idletasks()
            report = {"version": VERSION, "tk": root.tk.call("info", "patchlevel"),
                      "width": root.winfo_reqwidth(), "height": root.winfo_reqheight(),
                      "assets": {name: (ASSETS / name).is_file() for name in
                                 ("campus-login.exe", "install-campus-login.ps1", "run-campus-login.ps1")}}
            report["languages"] = {}
            for language in LANGUAGES:
                window.language = language
                window.refresh_language()
                status_window = window.show_status(("Running", None, ["WLAN: logged in to Campus Smoke Network"]))
                root.update_idletasks()
                report["languages"][language] = {
                    "title": root.title(), "width": root.winfo_reqwidth(), "height": root.winfo_reqheight(),
                    "status": status_window.latest.cget("text"),
                }
                status_window.root.destroy()
            if not all(report["assets"].values()):
                raise OSError("Incomplete release assets")
            report["preview"] = install("release-smoke-user", "release-smoke-password",
                                         "Campus Smoke Network", "Wi-Fi Smoke Adapter", preview=True).strip()
            options.smoke_test.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
            return
        if not ensure_administrator():
            return
        window = SetupWindow(root, language=language)
        if options.uninstall:
            root.after(200, window.start_uninstall)
        root.deiconify()
        root.mainloop()
    except Exception as error:
        if options.smoke_test:
            raise
        messagebox.showerror(translate("startup_failed", language), error_message(error, language), parent=root)
    finally:
        try:
            root.destroy()
        except tk.TclError:
            pass


if __name__ == "__main__":
    main()
