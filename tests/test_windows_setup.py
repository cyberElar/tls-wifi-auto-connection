"""Release installer checks without tasks, real credentials, or network login."""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

if os.name == "nt":
    import windows_setup as setup


ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name == "nt", "Requires Windows setup")
class WindowsSetupTests(unittest.TestCase):
    def test_credentials_are_protected_before_writing_and_removed_after_failure(self):
        with tempfile.TemporaryDirectory(prefix="campus test ", dir=ROOT) as directory:
            assets = Path(directory)
            for name in ("campus-login.exe", "install-campus-login.ps1", "run-campus-login.ps1"):
                (assets / name).touch()
            seen = []

            def protect(path):
                self.assertEqual(Path(path).read_bytes(), b"")
                seen.append(Path(path))

            def execute(command):
                credential = Path(command[command.index("-CredentialPath") + 1])
                self.assertEqual(credential, seen[0])
                self.assertEqual(json.loads(credential.read_text(encoding="utf-8")),
                                 {"user": "dummy-user", "password": "dummy-secret"})
                self.assertNotIn("dummy-secret", " ".join(command))
                self.assertNotIn("dummy-user", " ".join(command))
                raise OSError("simulated failure")

            with patch.object(setup, "ASSETS", assets), \
                 patch.object(setup.windows, "protect_credential", side_effect=protect), \
                 patch.object(setup, "run_command", side_effect=execute):
                with self.assertRaisesRegex(OSError, "simulated failure"):
                    setup.install(" dummy-user ", "dummy-secret", "Campus With Spaces", "Wi-Fi Adapter")
            self.assertFalse(seen[0].exists())

    def test_preview_uses_frozen_worker_without_python(self):
        command = setup.installer_command(Path("credential fixture.json"), "Campus With Spaces", "WLAN", preview=True)
        self.assertIn("-LoginExecutable", command)
        self.assertIn("-WhatIf", command)
        self.assertNotIn("-PythonPath", command)
        self.assertNotIn("-LoginScript", command)
        self.assertEqual(command[command.index("-Network") + 1], "Campus With Spaces")

    def test_subprocess_failure_is_reported_and_console_is_hidden(self):
        result = subprocess.CompletedProcess([], 1, "", "installer error")
        with patch.dict(os.environ, {"PSMODULEPATH": r"C:\PowerShell7\Modules"}), \
             patch.object(setup.subprocess, "run", return_value=result) as run:
            with self.assertRaisesRegex(OSError, "installer error"):
                setup.run_command(["installer"])
        self.assertEqual(run.call_args.kwargs["creationflags"], subprocess.CREATE_NO_WINDOW)
        self.assertNotIn("PSMODULEPATH", run.call_args.kwargs["env"])

    def test_uninstall_only_removes_data_when_asked(self):
        with patch.object(setup, "run_command", side_effect=lambda command: command):
            self.assertNotIn("-RemoveData", setup.uninstall())
            self.assertIn("-RemoveData", setup.uninstall(True))

    def test_install_directory_is_program_files(self):
        self.assertNotIn("ProgramData", str(setup.INSTALL_DIR))
        self.assertEqual(setup.INSTALL_DIR.name, "CampusLogin")

    def test_log_lines_are_explained_in_chinese(self):
        prefix = "2026-10-12 08:00:01 WLAN: "
        self.assertIn("已自动登录", setup.describe(prefix + "logged in to Tsinglan-School"))
        self.assertIn("当前在线", setup.describe(prefix + "on Tsinglan-School and online"))
        self.assertIn("密码错误", setup.describe(prefix + "login failed (密码错误)"))
        self.assertIn("Home", setup.describe(prefix + "waiting for Tsinglan-School (current network: Home)"))
        self.assertIsNone(setup.describe("2026-10-12 08:00:01 unrelated diagnostic output"))

    def test_status_does_not_hide_newer_failures_behind_old_success(self):
        lines = ["2026-10-12 08:00:01 WLAN: logged in to Tsinglan-School",
                 "2026-10-12 09:00:01 Supervisor failed: Required file is missing: C:\\x"]
        self.assertIn("后台程序出错", setup.summarize("Running", lines))
        stopped = setup.summarize("Ready", lines[:1])
        self.assertIn("没有在运行", stopped)
        self.assertNotIn("后台任务：", stopped)
        self.assertIn("没有安装", setup.summarize("", lines[:1]))
        exited = lines[:1] + ["2026-10-12 09:00:01 Login process exited with code 1; restarting in 10 seconds."]
        self.assertIn("意外退出", setup.summarize("Running", exited))
        self.assertIn("已自动登录", setup.summarize("Running", exited + [lines[0]]))

    def test_english_log_summaries_keep_network_names_and_latest_failure(self):
        records = (
            ("WLAN: logged in to Tsinglan-School", "Automatically signed in"),
            ("WLAN: on Tsinglan-School and online", "already online"),
            ("WLAN: login failed (bad password)", "Check your account and password"),
            ("WLAN: waiting for Tsinglan-School (current network: Home)", "current network: Home"),
            ("WLAN: network check failed: denied", "Could not read Wi-Fi status: denied"),
            ("no usable credentials in file", "Saved credentials are unusable"),
            ("Supervisor failed: missing file", "supervisor failed: missing file"),
            ("Login process exited with code -1; restarting", "code -1"),
        )
        for line, expected in records:
            with self.subTest(line=line):
                self.assertIn(expected, setup.describe("2026-10-12 08:00:01 " + line, "en"))
        lines = [records[0][0], records[-2][0]]
        self.assertIn("supervisor failed", setup.summarize("Running", lines, "en"))
        self.assertIn("background task is stopped", setup.summarize("Ready", lines[:1], "en"))
        self.assertIn("not installed", setup.summarize("", lines, "en"))

    def test_upgrade_reads_legacy_settings_but_not_password(self):
        class Field:
            def __init__(self, value=""):
                self.value = value
            def set(self, value):
                self.value = value
        with tempfile.TemporaryDirectory(prefix="campus test ", dir=ROOT) as directory:
            current, legacy = Path(directory) / "new", Path(directory) / "old"
            legacy.mkdir()
            (legacy / "config.json").write_text(
                json.dumps({"network": "CustomCampus", "interface": "WLAN 2"}), encoding="utf-8")
            (legacy / "credentials.json").write_text(
                json.dumps({"user": "legacy-user", "password": "legacy-secret"}), encoding="utf-8")
            window = type("Window", (), {})()
            window.user, window.password = Field(), Field()
            window.network, window.interface = Field("Tsinglan-School"), Field()
            with patch.object(setup, "INSTALL_DIR", current), patch.object(setup, "LEGACY_DIR", legacy):
                setup.SetupWindow.load_settings(window)
            self.assertEqual((window.network.value, window.interface.value, window.user.value),
                             ("CustomCampus", "WLAN 2", "legacy-user"))
            self.assertEqual(window.password.value, "")
            current.mkdir()
            (current / "config.json").write_text(
                json.dumps({"network": "Tsinglan-School", "interface": "WLAN"}), encoding="utf-8")
            with patch.object(setup, "INSTALL_DIR", current), patch.object(setup, "LEGACY_DIR", legacy):
                setup.SetupWindow.load_settings(window)
            self.assertEqual((window.network.value, window.interface.value), ("Tsinglan-School", "WLAN"))

    def test_ambiguous_wifi_remains_available_for_manual_selection(self):
        values = [{"Name": "Wi-Fi 2", "Status": "Disconnected"}, {"Name": "WLAN", "Status": "Up"}]
        with patch.object(setup.windows, "run_powershell", return_value=json.dumps(values)):
            self.assertEqual([item["Name"] for item in setup.wifi_choices()], ["WLAN", "Wi-Fi 2"])


@unittest.skipUnless(os.name == "nt", "Requires Windows Tk GUI")
class BilingualGuiTests(unittest.TestCase):
    def setUp(self):
        self.root = setup.tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.window = setup.SetupWindow(self.root, discover=False, language="zh-CN")
        self.save = patch.object(setup, "save_language").start()
        self.addCleanup(patch.stopall)

    def select_language(self, language):
        self.window.language_choice.set(setup.LANGUAGES[language])
        self.window.language_selector.event_generate("<<ComboboxSelected>>")
        self.root.update_idletasks()

    def test_switch_updates_open_status_and_preserves_fields_and_busy_state(self):
        for variable, value in ((self.window.user, "test-user"), (self.window.password, "test-secret"),
                                (self.window.network, "校园 Wi-Fi"), (self.window.interface, "WLAN 2")):
            variable.set(value)
        lines = ["WLAN 2: logged in to 校园 Wi-Fi"]
        dialog = self.window.show_status(("Running", "stale Chinese summary", lines))
        self.window.set_busy(True)
        self.window.set_status("installing")
        self.select_language("en")
        self.save.assert_called_once_with("en")
        self.assertIn("Campus Wi-Fi", self.root.title())
        self.assertEqual(self.window.strings["install"][0].get(), "Install / Update and enable")
        self.assertEqual(self.window.status.get(), "Installing and starting the background task…")
        self.assertEqual(str(self.window.install_button.cget("state")), "disabled")
        self.assertEqual(str(self.window.language_selector.cget("state")), "readonly")
        self.assertEqual(tuple(v.get() for v in (self.window.user, self.window.password,
                                               self.window.network, self.window.interface)),
                         ("test-user", "test-secret", "校园 Wi-Fi", "WLAN 2"))
        self.assertIn("Automatically signed in", dialog.latest.cget("text"))
        self.assertIn("校园 Wi-Fi", dialog.latest.cget("text"))
        self.assertEqual(dialog.log.get("1.0", "end-1c"), lines[0])
        self.assertEqual(dialog.close_button.cget("text"), "Close")
        self.select_language("zh-CN")
        self.assertIn("已自动登录", dialog.latest.cget("text"))
        self.assertEqual(self.window.status.get(), "正在安装并启动后台任务…")
        dialog.root.destroy()
        self.assertFalse(self.window.status_windows)

    def test_empty_status_window_placeholder_switches_language(self):
        dialog = self.window.show_status(("Running", None, []))
        self.select_language("en")
        self.assertEqual(dialog.log.get("1.0", "end-1c"), "(No logs yet)")
        self.assertIn("No records yet", dialog.latest.cget("text"))

    def test_validation_and_uninstall_confirmation_use_current_language(self):
        self.select_language("en")
        with patch.object(setup.messagebox, "showerror") as error:
            self.window.start_install()
        self.assertEqual(error.call_args.args[0], "Missing information")
        self.assertIn("Enter your account", error.call_args.args[1])
        with patch.object(setup.messagebox, "askyesnocancel", return_value=None) as confirm:
            self.window.start_uninstall()
        self.assertEqual(confirm.call_args.args[0], "Uninstall")
        self.assertIn("Yes: delete all saved data", confirm.call_args.args[1])
        self.assertFalse(self.window.busy)

    def test_queued_worker_results_use_language_selected_after_work_started(self):
        self.window.set_busy(True)
        self.window.set_status("installing")
        self.window.events.put(("install", None, setup.SetupError("missing_asset", name="worker.exe")))
        self.select_language("en")
        with patch.object(setup.messagebox, "showerror") as error:
            self.window.poll()
        self.assertEqual(error.call_args.args[0], "Operation failed")
        self.assertIn("release is missing worker.exe", error.call_args.args[1])
        self.assertFalse(self.window.busy)
        self.window.set_status("installed_pending")
        lines = ["WLAN: logged in to Tsinglan-School"]
        self.window.events.put(("first-status", ("Running", "已自动登录", lines), None))
        self.window.poll()
        self.assertIn("Installation complete. Automatically signed in", self.window.status.get())
        self.select_language("zh-CN")
        self.assertIn("安装完成。已自动登录", self.window.status.get())

    def test_delayed_install_status_does_not_replace_uninstall_result(self):
        self.window.set_status("uninstalled")
        self.window.events.put(("first-status", ("Running", "old login", ["WLAN: logged in to Campus"]), None))
        self.window.poll()
        self.assertEqual(self.window.status.get(), "已卸载。")


if __name__ == "__main__":
    unittest.main()
