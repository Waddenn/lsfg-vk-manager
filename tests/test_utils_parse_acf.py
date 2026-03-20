from __future__ import annotations

import unittest

from lsfg_vk_manager.utils import parse_acf_text


class ParseAcfTests(unittest.TestCase):
    def test_parse_acf_text_reads_appstate_values_only(self) -> None:
        text = """
"AppState"
{
    "appid"      "100"
    "Universe"   "1"
    "UserConfig"
    {
        "language" "english"
    }
    "name"       "Cool Game"
    "installdir" "Cool Game"
}
"""

        data = parse_acf_text(text)

        self.assertEqual(data["appid"], "100")
        self.assertEqual(data["name"], "Cool Game")
        self.assertEqual(data["installdir"], "Cool Game")
        self.assertNotIn("language", data)


if __name__ == "__main__":
    unittest.main()
