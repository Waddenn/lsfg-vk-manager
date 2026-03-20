from __future__ import annotations

import struct
import tempfile
import unittest
from pathlib import Path

from lsfg_vk_manager.appinfo import get_install_valid_launch_executables, read_steam_launch_options


def _kv_child(key_index: int, payload: bytes) -> bytes:
    return bytes([0]) + struct.pack("<i", key_index) + payload + bytes([8])


def _kv_string(key_index: int, value: str) -> bytes:
    return bytes([1]) + struct.pack("<i", key_index) + value.encode("utf-8") + b"\x00"


def _make_appinfo_file(path: Path, appid: int, launch_entries: list[dict[str, str]]) -> None:
    strings = [
        "appinfo",
        "config",
        "launch",
        "executable",
        "type",
        "description",
        "arguments",
    ]
    strings.extend(str(index) for index in range(len(launch_entries)))
    string_index = {value: index for index, value in enumerate(strings)}

    launch_payload = bytearray()
    for index, entry in enumerate(launch_entries):
        launch_option_payload = bytearray()
        for key in ("executable", "type", "description", "arguments"):
            if key in entry:
                launch_option_payload.extend(_kv_string(string_index[key], entry[key]))
        launch_payload.extend(_kv_child(string_index[str(index)], bytes(launch_option_payload)))

    root_payload = _kv_child(
        string_index["appinfo"],
        _kv_child(
            string_index["config"],
            _kv_child(
                string_index["launch"],
                bytes(launch_payload),
            ),
        ),
    )
    binary_vdf = bytes(root_payload) + bytes([8])

    entry_meta = b"".join(
        (
            struct.pack("<I", 2),
            struct.pack("<I", 0),
            struct.pack("<Q", 0),
            bytes(20),
            struct.pack("<I", 0),
            bytes(20),
        )
    )
    entry_data = entry_meta + binary_vdf

    header = struct.pack("<IIq", 0x07564429, 1, 16 + 4 + 4 + len(entry_data) + 4)
    body = struct.pack("<II", appid, len(entry_data)) + entry_data
    footer = struct.pack("<I", 0)
    string_table = struct.pack("<I", len(strings)) + b"".join(value.encode("utf-8") + b"\x00" for value in strings)
    path.write_bytes(header + body + footer + string_table)


class AppInfoTests(unittest.TestCase):
    def test_read_steam_launch_options_parses_launch_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "appinfo.vdf"
            _make_appinfo_file(
                path,
                100,
                [
                    {
                        "executable": "Game.exe",
                        "type": "default",
                        "description": "Launch",
                    }
                ],
            )

            launches = read_steam_launch_options(path, {"100"})

            self.assertEqual(len(launches["100"]), 1)
            self.assertEqual(launches["100"][0].executable, "Game.exe")
            self.assertEqual(launches["100"][0].launch_type, "default")

    def test_get_install_valid_launch_executables_prefers_linux_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            appinfo_path = root / "appinfo.vdf"
            install_path = root / "game"
            install_path.mkdir()
            (install_path / "Launcher.exe").write_bytes(b"MZ")
            (install_path / "BinLinux").mkdir()
            (install_path / "BinLinux" / "Game.x86_64").write_bytes(b"\x7fELF")

            _make_appinfo_file(
                appinfo_path,
                100,
                [
                    {
                        "executable": "Launcher.exe",
                        "type": "default",
                        "description": "Launcher",
                    },
                    {
                        "executable": "BinLinux/Game.x86_64",
                        "type": "default",
                        "description": "Game",
                    },
                ],
            )

            executables = get_install_valid_launch_executables(appinfo_path, "100", install_path)

            self.assertEqual(executables, ["BinLinux/Game.x86_64"])

    def test_get_install_valid_launch_executables_filters_windows_launcher(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            appinfo_path = root / "appinfo.vdf"
            install_path = root / "game"
            install_path.mkdir()
            (install_path / "Launcher.exe").write_bytes(b"MZ")
            (install_path / "Game.exe").write_bytes(b"MZ")

            _make_appinfo_file(
                appinfo_path,
                100,
                [
                    {
                        "executable": "Launcher.exe",
                        "type": "default",
                        "description": "Launcher",
                    },
                    {
                        "executable": "Game.exe",
                        "type": "default",
                        "description": "Game",
                    },
                ],
            )

            executables = get_install_valid_launch_executables(appinfo_path, "100", install_path)

            self.assertEqual(executables, ["Game.exe"])


if __name__ == "__main__":
    unittest.main()
