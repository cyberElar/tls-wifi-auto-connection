import argparse
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.parse

import campus_login_windows as windows


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("campus_login", ROOT / "campus-login.py")
login = importlib.util.module_from_spec(spec)
spec.loader.exec_module(login)


class LoginTests(unittest.TestCase):
    def test_rc4_matches_known_vectors(self):
        self.assertEqual(login.rc4_hex("Plaintext", "Key"), "bbf316e8d940af0ad3")
        self.assertEqual(login.rc4_hex("pedia", "Wiki"), "1021bf0420")

    def test_windows_probe_distinguishes_redirect_timeout_and_online(self):
        with patch.object(login.platform, "system", return_value="Windows"), \
             patch.object(login, "windows", windows, create=True), \
             patch.object(windows, "request") as request:
            request.return_value = (302, "http://4.3.2.1/ac_portal/login.php", "")
            self.assertEqual(login.state("10.0.0.2", "WLAN"), "portal")
            request.assert_called_with("10.0.0.2", login.PROBE, 5, iface="WLAN", read_body=False)
            request.return_value = (404, "", "")
            self.assertEqual(login.state("10.0.0.2", "WLAN"), "online")
            request.side_effect = OSError("disconnected")
            self.assertEqual(login.state("10.0.0.2", "WLAN"), "unknown")

    def test_portal_payload_and_response_formats(self):
        with patch.object(login.platform, "system", return_value="Windows"), \
             patch.object(login, "windows", windows, create=True), \
             patch.object(windows, "request") as request, \
             patch.object(login.time, "time", return_value=123456):
            for body in ('{"success": false, "msg": "don\'t retry"}',
                         "{'success':true,'msg':'ok','other':null}",
                         "{'success':False,'msg':'denied'}"):
                request.return_value = (200, "", body)
                self.assertIn("success", login.login("10.0.0.2", "a&b", "Plaintext", "WLAN"))
            args, kwargs = request.call_args
            payload = urllib.parse.parse_qs(kwargs["body"].decode("ascii"))
            self.assertEqual(payload["opr"], ["pwdLogin"])
            self.assertEqual(payload["userName"], ["a&b"])
            self.assertEqual(payload["auth_tag"], ["123456000"])
            self.assertNotIn("Plaintext", kwargs["body"].decode("ascii"))
            self.assertEqual(kwargs["iface"], "WLAN")
            request.return_value = (200, "", '__import__("os").getcwd()')
            self.assertFalse(login.login("10.0.0.2", "test", "test")["success"])

    def test_credentials_accept_utf8_bom_and_reject_invalid_values(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            path = Path(directory) / "credentials.json"
            path.write_text(json.dumps({"user": "测试", "password": "test"}), encoding="utf-8-sig")
            self.assertEqual(login.load_cred(path), ("测试", "test"))
            for value in (None, [], {"user": 3, "password": "test"}, {"user": "test", "password": ""}):
                path.write_text(json.dumps(value), encoding="utf-8")
                with self.assertRaises(ValueError):
                    login.load_cred(path)

    def test_save_failure_preserves_existing_credentials(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            path = Path(directory) / "credentials.json"
            path.write_text("original", encoding="utf-8")
            with patch.object(login.platform, "system", return_value="Windows"), \
                 patch.object(login, "windows", windows, create=True), \
                 patch.object(windows, "protect_credential", side_effect=OSError("ACL denied")):
                with self.assertRaises(OSError):
                    login.save_cred(path, "test", "test")
            self.assertEqual(path.read_text(encoding="utf-8"), "original")
            self.assertEqual(list(Path(directory).iterdir()), [path])

    @unittest.skipUnless(os.name == "nt", "Requires Windows file permissions")
    def test_saved_credentials_have_owner_only_access(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            path = Path(directory) / "test credentials.json"
            login.save_cred(path, "test-user", "test-password")
            self.assertEqual(login.load_cred(path), ("test-user", "test-password"))
            environment = os.environ.copy()
            environment["CAMPUS_CREDENTIAL_FILE"] = str(path)
            result = json.loads(windows.run_powershell(
                "$acl = [IO.File]::GetAccessControl($env:CAMPUS_CREDENTIAL_FILE); "
                "@{ protected = $acl.AreAccessRulesProtected; "
                "user = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value; "
                "rules = @($acl.GetAccessRules($true, $true, [Security.Principal.SecurityIdentifier]) | "
                "ForEach-Object { @{ sid = $_.IdentityReference.Value; "
                "type = $_.AccessControlType.ToString(); inherited = $_.IsInherited } }) } | "
                "ConvertTo-Json -Depth 4", env=environment,
            ))
            self.assertTrue(result["protected"])
            self.assertEqual(result["rules"], [{"sid": result["user"], "type": "Allow", "inherited": False}])

    def test_save_only_prompts_without_contacting_network(self):
        with patch.object(login.sys, "argv", ["campus-login.py", "--save-only"]), \
             patch("builtins.input", return_value="test-user"), \
             patch.object(login.getpass, "getpass", return_value="test-password"), \
             patch.object(login, "save_cred") as save, \
             patch.object(login, "source_address") as address, \
             contextlib.redirect_stdout(io.StringIO()):
            login.main()
            save.assert_called_once()
            self.assertEqual(save.call_args.args[1:], ("test-user", "test-password"))
            address.assert_not_called()

    def test_watch_never_contacts_portal_off_campus(self):
        args = argparse.Namespace(iface="WLAN", watch="Tsinglan-School", cred="unused")
        with patch.object(login, "current_network", return_value=("Home", "Home")), \
             patch.object(login, "source_address") as source, \
             patch.object(login, "login") as authenticate, \
             patch.object(login.time, "sleep", side_effect=StopIteration):
            with self.assertRaises(StopIteration):
                login.watch(args)
            source.assert_not_called()
            authenticate.assert_not_called()

    def test_watch_bounds_failed_login_backoff(self):
        args = argparse.Namespace(iface="WLAN", watch="Tsinglan-School", cred="unused")
        delays = []

        def sleep(seconds):
            delays.append(seconds)
            if len(delays) == 30:
                raise StopIteration

        with patch.object(login, "current_network", return_value=(args.watch, args.watch)), \
             patch.object(login, "source_address", return_value="10.0.0.2"), \
             patch.object(login, "state", return_value="portal"), \
             patch.object(login, "load_cred", return_value=("test", "test")), \
             patch.object(login, "login", return_value={"success": False}), \
             patch.object(login.time, "sleep", side_effect=sleep), \
             contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(StopIteration):
                login.watch(args)
        self.assertEqual(delays[1:12:2], [20, 40, 80, 160, 320, 600])
        self.assertTrue(all(delay == 600 for delay in delays[13::2]))

    def test_watch_logs_repeated_network_error_once(self):
        args = argparse.Namespace(iface="WLAN", watch="Tsinglan-School", cred="unused")
        output = io.StringIO()
        with patch.object(login, "current_network", side_effect=OSError("adapter unavailable")), \
             patch.object(login.time, "sleep", side_effect=[None, StopIteration]), \
             contextlib.redirect_stdout(output):
            with self.assertRaises(StopIteration):
                login.watch(args)
        self.assertEqual(output.getvalue().count("network check failed"), 1)


if __name__ == "__main__":
    unittest.main()
