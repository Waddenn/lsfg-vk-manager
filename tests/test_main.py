from __future__ import annotations

import io
import unittest
from unittest.mock import patch

from lsfg_vk_manager.main import main


class MainTests(unittest.TestCase):
    def test_main_reports_startup_failure(self) -> None:
        stderr = io.StringIO()
        with patch("lsfg_vk_manager.main.SettingsStore", side_effect=RuntimeError("bad settings")):
            code = main([], stderr=stderr)

        self.assertEqual(code, 1)
        self.assertIn("Startup failed: bad settings", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
