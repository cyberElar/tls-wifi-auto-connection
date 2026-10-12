"""Language selection and persistence without touching real user preferences."""

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import setup_i18n as i18n


class LanguagePreferenceTests(unittest.TestCase):
    def test_saved_language_overrides_windows_and_contains_no_account_data(self):
        with tempfile.TemporaryDirectory() as directory:
            preference = Path(directory) / "CampusLogin" / "setup-preferences.json"
            with patch.object(i18n, "PREFERENCES", preference), \
                 patch.object(i18n, "system_language", return_value="zh-CN"):
                self.assertEqual(i18n.preferred_language(), "zh-CN")
                i18n.save_language("en")
                self.assertEqual(i18n.preferred_language(), "en")
                self.assertEqual(json.loads(preference.read_text(encoding="utf-8")), {"language": "en"})

    def test_missing_corrupt_or_unsupported_preference_falls_back_to_windows(self):
        with tempfile.TemporaryDirectory() as directory:
            preference = Path(directory) / "preferences.json"
            with patch.object(i18n, "PREFERENCES", preference), \
                 patch.object(i18n, "system_language", return_value="en"):
                self.assertEqual(i18n.preferred_language(), "en")
                for contents in ("{", "[]", "null", '{"language":"de"}', '{"language":[]}', "\xff"):
                    with self.subTest(contents=contents):
                        preference.write_bytes(contents.encode("latin-1"))
                        self.assertEqual(i18n.preferred_language(), "en")

    def test_read_only_profile_does_not_block_language_selection(self):
        with patch.object(Path, "mkdir", side_effect=PermissionError("read-only profile")):
            i18n.save_language("en")
        with self.assertRaises(ValueError):
            i18n.save_language("unsupported")

    @unittest.skipUnless(os.name == "nt", "Requires Windows UI language API")
    def test_windows_display_language_uses_primary_chinese_id(self):
        kernel = Mock()
        with patch.object(i18n.ctypes, "WinDLL", return_value=kernel):
            for identifier, expected in ((0x0804, "zh-CN"), (0x0404, "zh-CN"),
                                         (0x0C04, "zh-CN"), (0x0409, "en"), (0x0407, "en")):
                with self.subTest(identifier=identifier):
                    kernel.GetUserDefaultUILanguage.return_value = identifier
                    self.assertEqual(i18n.system_language(), expected)

    def test_worker_errors_use_language_at_display_time(self):
        error = i18n.SetupError("missing_asset", name="campus-login.exe")
        self.assertIn("发布包缺少", i18n.error_message(error, "zh-CN"))
        self.assertIn("release is missing campus-login.exe", i18n.error_message(error, "en"))
        external = i18n.error_message(OSError("Windows diagnostic"), "en")
        self.assertIn("Check your settings", external)
        self.assertIn("Windows diagnostic", external)


if __name__ == "__main__":
    unittest.main()
