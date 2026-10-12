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


ASSETS = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
INSTALL_DIR = Path(os.environ.get("ProgramW6432") or os.environ.get("ProgramFiles")
                   or r"C:\Program Files") / "CampusLogin"
LOG = INSTALL_DIR / "campus-login.log"
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
        raise OSError("需要管理员权限才能安装开机任务。请允许 Windows 权限提示后重试。")
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
        raise OSError(result.stderr.strip() or result.stdout.strip() or "安装程序运行失败。")
    return result.stdout


def install(user, password, network, interface, *, preview=False):
    for name in ("campus-login.exe", "install-campus-login.ps1", "run-campus-login.ps1"):
        if not (ASSETS / name).is_file():
            raise OSError("发布包缺少 %s，请完整解压 ZIP 后再运行。" % name)
    if not all(value.strip() for value in (user, password, network, interface)):
        raise ValueError("请填写账号、密码、校园网络名称和 Wi-Fi 网卡。")
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


# The worker logs in English; students read this window. Each pattern maps the
# start of a log message (after the "<interface>: " prefix) to plain Chinese.
MESSAGES = (
    (r"logged in to (.+)", "已自动登录校园网 {0}。"),
    (r"on (.+) and online", "已连接校园网 {0}，当前在线，无需再次登录。"),
    (r"login failed \((.*)\)", "登录失败：{0}。请检查账号和密码，然后重新安装。"),
    (r"waiting for (.+) \(current network: (.*)\)", "当前没有连接校园网（现在的网络：{1}），连上 {0} 后会自动登录。"),
    (r"network check failed: (.*)", "暂时无法读取 Wi-Fi 状态：{0}"),
    (r"no usable credentials", "保存的账号密码不可用，请重新安装并填写账号密码。"),
)


def describe(line):
    """Plain-language summary of one log line, or None for unrecognised lines."""
    message = re.sub(r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d ", "", line.strip())
    message = re.sub(r"^[^:]+: (?=(logged|on |login|waiting|network))", "", message)
    for pattern, text in MESSAGES:
        match = re.match(pattern, message)
        if match:
            return text.format(*match.groups())
    return None


def read_status():
    output = windows.run_powershell(
        "$task = Get-ScheduledTask -TaskName CampusLogin -TaskPath '\\' -ErrorAction SilentlyContinue; "
        "if ($task) { [string]$task.State } else { '' }"
    )
    try:
        lines = LOG.read_text(encoding="utf-8", errors="replace").splitlines()[-40:]
    except OSError:
        lines = []
    summary = next((text for text in map(describe, reversed(lines)) if text), None)
    return output.strip(), summary, lines


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


class SetupWindow:
    def __init__(self, root, *, discover=True):
        self.root = root
        self.events = queue.Queue()
        self.busy = False
        root.title("TLS 校园网自动登录 · %s" % VERSION)
        root.resizable(False, False)
        root.protocol("WM_DELETE_WINDOW", self.close)
        ttk.Style(root).theme_use("vista")
        panel = ttk.Frame(root, padding=24)
        panel.grid(sticky="nsew")
        ttk.Label(panel, text="校园网自动登录", font=("Microsoft YaHei UI", 18, "bold")).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))
        ttk.Label(panel, text="填好账号密码，点一次安装。以后开机会自动登录校园网。",
                  font=("Microsoft YaHei UI", 10)).grid(row=1, column=0, columnspan=2,
                                                       sticky="w", pady=(0, 20))
        self.user = tk.StringVar()
        self.password = tk.StringVar()
        self.network = tk.StringVar(value="Tsinglan-School")
        self.interface = tk.StringVar()
        self.status = tk.StringVar(value="正在检测 Wi-Fi 网卡…" if discover else "就绪")
        self.widgets = []
        fields = (("校园账号", self.user), ("密码", self.password), ("校园网络名称 / SSID", self.network))
        for row, (label, variable) in enumerate(fields, 2):
            ttk.Label(panel, text=label).grid(row=row, column=0, sticky="w", padx=(0, 16), pady=7)
            entry = ttk.Entry(panel, textvariable=variable, width=38,
                              show="●" if variable is self.password else "")
            entry.grid(row=row, column=1, sticky="ew", pady=7)
            self.widgets.append(entry)
        ttk.Label(panel, text="Wi-Fi 网卡").grid(row=5, column=0, sticky="w", pady=7)
        self.adapter = ttk.Combobox(panel, textvariable=self.interface, width=36)
        self.adapter.grid(row=5, column=1, sticky="ew", pady=7)
        self.widgets.append(self.adapter)
        ttk.Label(panel, text="网络名称应与校园 Wi-Fi 的 SSID 或 Windows 网络配置名称一致。",
                  wraplength=490).grid(row=6, column=0, columnspan=2, sticky="w", pady=(5, 16))
        self.install_button = ttk.Button(panel, text="安装 / 更新并启用", command=self.start_install)
        self.install_button.grid(row=7, column=0, columnspan=2, sticky="ew", ipady=5)
        controls = ttk.Frame(panel)
        controls.grid(row=8, column=0, columnspan=2, sticky="ew", pady=(10, 16))
        self.uninstall_button = ttk.Button(controls, text="卸载", command=self.start_uninstall)
        self.uninstall_button.pack(side="left")
        # Not "open the folder": it is readable only by administrators, and
        # Explorer's "Continue" prompt would permanently grant the signed-in
        # user access to the saved password. This window already runs elevated.
        self.status_button = ttk.Button(controls, text="查看运行状态", command=self.start_status)
        self.status_button.pack(side="right")
        ttk.Label(panel, textvariable=self.status, wraplength=490).grid(
            row=9, column=0, columnspan=2, sticky="w", pady=(0, 12))
        ttk.Separator(panel).grid(row=10, column=0, columnspan=2, sticky="ew")
        ttk.Label(panel, text="账号密码文件：%s\n仅 SYSTEM 和管理员可访问。" % (
            INSTALL_DIR / "credentials.json"), wraplength=490).grid(
                row=11, column=0, columnspan=2, sticky="w", pady=(12, 0))
        if discover:
            self.load_settings()
        self.widgets[0].focus_set()
        root.after(100, self.poll)
        if discover:
            self.background("adapters", wifi_choices)

    def load_settings(self):
        try:
            config = json.loads((INSTALL_DIR / "config.json").read_text(encoding="utf-8-sig"))
            self.network.set(config["network"])
            self.interface.set(config["interface"])
            saved = json.loads((INSTALL_DIR / "credentials.json").read_text(encoding="utf-8-sig"))
            self.user.set(saved.get("user", ""))
            # Re-enter the password when updating; do not display saved secrets.
        except (OSError, ValueError, KeyError):
            pass

    def background(self, action, function, *arguments):
        def work():
            try:
                self.events.put((action, function(*arguments), None))
            except Exception as error:
                self.events.put((action, None, str(error)))
        threading.Thread(target=work, daemon=True).start()

    def set_busy(self, value):
        self.busy = value
        for widget in (*self.widgets, self.install_button, self.uninstall_button, self.status_button):
            widget.configure(state="disabled" if value else "normal")

    def start_install(self):
        values = tuple(variable.get() for variable in
                       (self.user, self.password, self.network, self.interface))
        if not all(value.strip() for value in values):
            messagebox.showerror("信息不完整", "请填写账号、密码、校园网络名称和 Wi-Fi 网卡。", parent=self.root)
            return
        self.set_busy(True)
        self.status.set("正在安装并启动后台任务…")
        self.background("install", install, *values)

    def start_uninstall(self):
        answer = messagebox.askyesnocancel(
            "卸载", "停止自动登录并移除开机任务。\n\n是否同时删除保存的账号密码和日志？\n"
            "· 是：全部删除（推荐，不再使用时）\n· 否：只停止任务，保留账号密码\n· 取消：不卸载",
            parent=self.root)
        if answer is None:
            return
        self.set_busy(True)
        self.status.set("正在停止并移除后台任务…")
        self.background("uninstall", uninstall, answer)

    def start_status(self):
        self.set_busy(True)
        self.status.set("正在读取运行状态…")
        self.background("status", read_status)

    def show_status(self, result):
        state, summary, lines = result
        states = {"Running": "正在运行", "Ready": "已安装但没有运行（重启电脑后会启动）",
                  "Disabled": "已被禁用", "": "未安装"}
        window = tk.Toplevel(self.root)
        window.title("运行状态")
        window.transient(self.root)
        frame = ttk.Frame(window, padding=16)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="后台任务：%s" % states.get(state, state),
                  font=("Microsoft YaHei UI", 11, "bold")).pack(anchor="w")
        ttk.Label(frame, text="最近结果：%s" % (summary or "还没有记录，请稍等几秒后再查看。"),
                  wraplength=520).pack(anchor="w", pady=(6, 10))
        ttk.Label(frame, text="详细日志（遇到问题时可截图发给维护者）：").pack(anchor="w")
        text = scrolledtext.ScrolledText(frame, width=78, height=14, font=("Consolas", 9))
        text.insert("1.0", "\n".join(lines) or "（暂无日志）")
        text.configure(state="disabled")
        text.see("end")
        text.pack(fill="both", expand=True, pady=(4, 10))
        ttk.Button(frame, text="关闭", command=window.destroy).pack(anchor="e")

    def poll(self):
        while not self.events.empty():
            action, result, error = self.events.get_nowait()
            if action == "adapters":
                if error:
                    self.status.set("未能自动检测网卡，请填写 Windows 中的 Wi-Fi 网卡名称。")
                else:
                    self.adapter["values"] = tuple(item["Name"] for item in result)
                    connected = [item for item in result if item["Status"] == "Up"]
                    preferred = connected if len(connected) == 1 else result
                    if not self.interface.get() and len(preferred) == 1:
                        self.interface.set(preferred[0]["Name"])
                    if not self.busy:
                        self.status.set("请确认账号、校园网络名称和 Wi-Fi 网卡。")
                continue
            if action == "first-status":
                # Quiet follow-up after installing: show the first result, if any.
                if not error and result[1]:
                    self.status.set("安装完成。%s" % result[1])
                continue
            self.set_busy(False)
            if error:
                self.status.set("操作失败，请检查填写的信息后重试。")
                messagebox.showerror("操作失败", error, parent=self.root)
            elif action == "status":
                self.status.set("就绪")
                self.show_status(result)
            elif action == "install":
                self.password.set("")
                self.status.set("安装完成，后台正在检查网络…稍后可点“查看运行状态”确认结果。")
                messagebox.showinfo("安装完成", "开机自动登录已启用，以后开机会自动登录校园网。\n"
                                    "可以点“查看运行状态”确认是否登录成功。", parent=self.root)
                self.background("first-status", lambda: (time.sleep(8), read_status())[1])
            else:
                self.status.set("已卸载。")
        self.root.after(100, self.poll)

    def close(self):
        if not self.busy:
            self.root.destroy()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke-test", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--uninstall", action="store_true")
    options = parser.parse_args()
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
            if not all(report["assets"].values()):
                raise OSError("Incomplete release assets")
            report["preview"] = install("release-smoke-user", "release-smoke-password",
                                         "Campus Smoke Network", "Wi-Fi Smoke Adapter", preview=True).strip()
            options.smoke_test.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
            return
        if not ensure_administrator():
            return
        window = SetupWindow(root)
        if options.uninstall:
            root.after(200, window.start_uninstall)
        root.deiconify()
        root.mainloop()
    except Exception as error:
        if options.smoke_test:
            raise
        messagebox.showerror("无法启动安装程序", str(error), parent=root)
    finally:
        try:
            root.destroy()
        except tk.TclError:
            pass


if __name__ == "__main__":
    main()
