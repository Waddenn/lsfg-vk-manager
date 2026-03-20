from __future__ import annotations

import unittest

from lsfg_vk_manager.utils import format_error_message


class UtilsTests(unittest.TestCase):
    def test_format_error_message_uses_exception_text(self) -> None:
        self.assertEqual(format_error_message(ValueError("broken config")), "broken config")

    def test_format_error_message_falls_back_to_exception_type(self) -> None:
        self.assertEqual(format_error_message(RuntimeError()), "RuntimeError")


if __name__ == "__main__":
    unittest.main()
