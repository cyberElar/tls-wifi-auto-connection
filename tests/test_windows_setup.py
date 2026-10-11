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
        with patch.object(setup.subprocess, "run", return_value=result) as run:
            with self.assertRaisesRegex(OSError, "installer error"):
                setup.run_command(["installer"])
        self.assertEqual(run.call_args.kwargs["creationflags"], subprocess.CREATE_NO_WINDOW)

    def test_ambiguous_wifi_remains_available_for_manual_selection(self):
        values = [{"Name": "Wi-Fi 2", "Status": "Disconnected"}, {"Name": "WLAN", "Status": "Up"}]
        with patch.object(setup.windows, "run_powershell", return_value=json.dumps(values)):
            self.assertEqual([item["Name"] for item in setup.wifi_choices()], ["WLAN", "Wi-Fi 2"])


if __name__ == "__main__":
    unittest.main()
