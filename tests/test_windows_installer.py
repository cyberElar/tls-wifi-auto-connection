"""Windows integration checks without installing a task or using real accounts.

Run: python -m unittest discover -s tests -v
"""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]
POWERSHELL = shutil.which("powershell.exe")


@unittest.skipUnless(os.name == "nt" and POWERSHELL, "Requires Windows PowerShell 5.1")
class WindowsInstallerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="campus test ", dir=ROOT)
        self.directory = Path(self.temporary.name)
        self.worker = self.directory / "campus-login.py"
        self.worker.write_text("pass\n", encoding="utf-8")
        self.credential = self.directory / "credentials.json"
        self.credential.write_text(
            json.dumps({"user": "test-user", "password": "test-password"}),
            encoding="utf-8",
        )

    def tearDown(self):
        self.temporary.cleanup()

    def installer(self, *arguments):
        return subprocess.run(
            [POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-File", str(ROOT / "install-campus-login.ps1"), *map(str, arguments)],
            capture_output=True, text=True, errors="replace", timeout=30,
        )

    def preview(self, *arguments):
        return self.installer(
            "-LoginScript", self.worker, "-CredentialPath", self.credential,
            "-PythonPath", sys.executable, "-Interface", "Wi-Fi Test Adapter",
            "-Network", "Campus Network With Spaces", "-WhatIf", *arguments,
        )

    def test_valid_preview_with_spaces(self):
        result = self.preview()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Campus Network With Spaces", result.stdout)
        self.assertIn("Wi-Fi Test Adapter", result.stdout)

    def test_missing_worker_fails_before_installation(self):
        self.worker.unlink()
        result = self.preview()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Login script not found", result.stderr)

    def test_explicit_missing_credential_is_not_silently_reused(self):
        self.credential.unlink()
        result = self.preview()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Credential file not found", result.stderr)

    def test_invalid_json_does_not_expose_content(self):
        self.credential.write_text("private-test-secret: invalid-json", encoding="utf-8")
        result = self.preview()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Cannot read credential JSON", result.stderr)
        self.assertNotIn("private-test-secret", result.stdout + result.stderr)

    def test_invalid_credential_schema(self):
        for value in ({"user": "test", "password": ""}, {"user": 123, "password": "test"}):
            with self.subTest(value=value):
                self.credential.write_text(json.dumps(value), encoding="utf-8")
                result = self.preview()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Credential JSON must contain", result.stderr)

    def test_uninstall_preview_has_no_login_dependencies(self):
        result = self.installer("-Uninstall", "-WhatIf")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("CampusLogin", result.stdout)

    def test_runner_logs_stderr_preserves_arguments_rotates_and_restarts(self):
        shutil.copyfile(ROOT / "run-campus-login.ps1", self.directory / "run-campus-login.ps1")
        self.worker.write_text(
            "import json, sys\n"
            "print('argv=' + json.dumps(sys.argv[1:]), flush=True)\n"
            "print('test-stderr', file=sys.stderr, flush=True)\n"
            "sys.exit(3)\n",
            encoding="utf-8",
        )
        (self.directory / "config.json").write_text(
            json.dumps({"python": sys.executable, "network": "Campus Network With Spaces",
                        "interface": "Wi-Fi Test Adapter"}),
            encoding="utf-8",
        )
        log = self.directory / "campus-login.log"
        log.write_text("x" * (5 * 1024 * 1024), encoding="utf-8")
        process = subprocess.Popen(
            [POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-File", str(self.directory / "run-campus-login.ps1")],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        try:
            deadline = time.monotonic() + 20
            content = ""
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    self.fail("Supervisor unexpectedly exited")
                content = log.read_text(encoding="utf-8") if log.exists() else ""
                if content.count("restarting in 10 seconds") >= 2 and content.count("argv=") >= 2:
                    break
                time.sleep(0.1)
            self.assertGreaterEqual(content.count("restarting in 10 seconds"), 2, content[-2000:])
            self.assertGreaterEqual(content.count("test-stderr"), 2)
            self.assertIn("code 3", content)
            lines = [line.split("argv=", 1)[1] for line in content.splitlines() if "argv=" in line]
            expected = ["--watch", "Campus Network With Spaces", "-i", "Wi-Fi Test Adapter",
                        "--cred", str(self.credential)]
            self.assertGreaterEqual(len(lines), 2, content[-3000:])
            self.assertTrue(all(json.loads(line) == expected for line in lines))
            rotated_size = (self.directory / "campus-login.log.1").stat().st_size
            self.assertGreaterEqual(rotated_size, 5 * 1024 * 1024)
            self.assertLess(rotated_size, 5 * 1024 * 1024 + 1024)
        finally:
            process.terminate()
            process.wait(timeout=10)


if __name__ == "__main__":
    unittest.main()
