from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from wiifit_trackpad.settings import AppSettings


class SettingsTests(unittest.TestCase):
    def test_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            expected = AppSettings(
                control_mode="joystick",
                gain=3.2,
                impact_click_enabled=False,
                impact_click_rise_kg=6.5,
                dwell_click_enabled=True,
                dwell_seconds=1.4,
            )
            expected.save(path)
            self.assertEqual(AppSettings.load(path), expected)

    def test_invalid_file_uses_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            path.write_text("not json", encoding="utf-8")
            self.assertEqual(AppSettings.load(path), AppSettings())


if __name__ == "__main__":
    unittest.main()
