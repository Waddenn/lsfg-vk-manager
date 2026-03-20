from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import struct


APPINFO_MAGIC = 0x07564429
KV1_BINARY_MAGIC = 0x564B4256
KV_END = 8
KV_ALT_END = 11


@dataclass(frozen=True)
class SteamLaunchOption:
    executable: str
    arguments: str = ""
    oslist: str = ""
    launch_type: str = ""
    description: str = ""


def read_steam_launch_options(path: Path, wanted_appids: set[str] | None = None) -> dict[str, list[SteamLaunchOption]]:
    if not path.exists():
        return {}

    with path.open("rb") as handle:
        data = handle.read()

    if len(data) < 16:
        return {}

    magic, universe = struct.unpack_from("<II", data, 0)
    if magic != APPINFO_MAGIC or universe != 1:
        return {}

    string_table_offset = struct.unpack_from("<q", data, 8)[0]
    if string_table_offset <= 0 or string_table_offset >= len(data):
        return {}

    string_table = _read_string_table(data, string_table_offset)
    offset = 16
    launches_by_appid: dict[str, list[SteamLaunchOption]] = {}

    while offset + 4 <= len(data):
        appid = struct.unpack_from("<I", data, offset)[0]
        offset += 4
        if appid == 0:
            break
        if offset + 60 > len(data):
            break

        size = struct.unpack_from("<I", data, offset)[0]
        offset += 4
        entry_start = offset
        entry_end = entry_start + size
        if entry_end > len(data):
            break

        appid_text = str(appid)
        offset += 4  # info state
        offset += 4  # last updated
        offset += 8  # pics token
        offset += 20  # sha1
        offset += 4  # change number
        offset += 20  # binary data sha1

        if wanted_appids is None or appid_text in wanted_appids:
            node, offset = _read_binary_kv(data, offset, string_table)
            launches_by_appid[appid_text] = _extract_launch_options(node)
        else:
            offset = entry_end

        offset = entry_end

    return launches_by_appid


def get_install_valid_launch_executables(
    appinfo_path: Path,
    appid: str,
    install_path: Path,
) -> list[str]:
    launch_options = read_steam_launch_options(appinfo_path, {appid}).get(appid, [])
    candidates = _select_preferred_launches(launch_options, install_path)

    seen: set[str] = set()
    result: list[str] = []
    for option in candidates:
        executable = option.executable.replace("\\", "/").strip()
        if executable.startswith("./"):
            executable = executable[2:]
        if not executable:
            continue
        candidate_path = install_path / executable
        if not candidate_path.exists() or candidate_path.is_dir():
            continue
        key = executable.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(executable)

    return result


def _read_string_table(data: bytes, offset: int) -> list[str]:
    if offset + 4 > len(data):
        return []
    count = struct.unpack_from("<I", data, offset)[0]
    cursor = offset + 4
    strings: list[str] = []
    for _ in range(count):
        value, cursor = _read_c_string(data, cursor)
        strings.append(value)
    return strings


def _read_binary_kv(data: bytes, offset: int, string_table: list[str], end_marker: int = KV_END) -> tuple[dict[str, object], int]:
    if offset + 8 <= len(data) and struct.unpack_from("<I", data, offset)[0] == KV1_BINARY_MAGIC:
        offset += 8
        end_marker = KV_ALT_END

    node: dict[str, object] = {}

    while offset < len(data):
        node_type = data[offset]
        offset += 1
        if node_type == end_marker:
            return node, offset

        key_index = struct.unpack_from("<i", data, offset)[0]
        offset += 4
        if key_index < 0 or key_index >= len(string_table):
            raise ValueError(f"Invalid string table index: {key_index}")
        key = string_table[key_index]

        if node_type == 0:
            value, offset = _read_binary_kv(data, offset, string_table, end_marker=end_marker)
        elif node_type == 1:
            value, offset = _read_c_string(data, offset)
        elif node_type in {2, 4, 6}:
            value = struct.unpack_from("<i", data, offset)[0]
            offset += 4
        elif node_type == 3:
            value = struct.unpack_from("<f", data, offset)[0]
            offset += 4
        elif node_type == 7:
            value = struct.unpack_from("<Q", data, offset)[0]
            offset += 8
        elif node_type == 10:
            value = struct.unpack_from("<q", data, offset)[0]
            offset += 8
        else:
            raise ValueError(f"Unsupported KV1 binary node type: {node_type}")

        node[key] = value

    return node, offset


def _read_c_string(data: bytes, offset: int) -> tuple[str, int]:
    end = data.find(b"\x00", offset)
    if end == -1:
        end = len(data)
    return data[offset:end].decode("utf-8", errors="ignore"), end + 1


def _extract_launch_options(node: dict[str, object]) -> list[SteamLaunchOption]:
    appinfo = _as_dict(node.get("appinfo"))
    config = _as_dict(appinfo.get("config"))
    launch = _as_dict(config.get("launch"))
    if not launch:
        return []

    result: list[SteamLaunchOption] = []
    for value in launch.values():
        option = _as_dict(value)
        executable = str(option.get("executable", "")).strip()
        if not executable:
            continue
        result.append(
            SteamLaunchOption(
                executable=executable,
                arguments=str(option.get("arguments", "")).strip(),
                oslist=str(option.get("oslist", "")).strip(),
                launch_type=str(option.get("type", "")).strip(),
                description=str(option.get("description", "")).strip(),
            )
        )

    return result


def _select_preferred_launches(options: list[SteamLaunchOption], install_path: Path) -> list[SteamLaunchOption]:
    if not options:
        return []

    existing = [option for option in options if (install_path / option.executable.replace("\\", "/")).exists()]
    if not existing:
        return []

    default_options = [option for option in existing if option.launch_type in {"", "default"}] or existing
    classified = {
        "linux": [],
        "windows": [],
        "macos": [],
        "unknown": [],
    }
    for option in default_options:
        classified[_classify_platform(install_path / option.executable.replace("\\", "/"))].append(option)

    preferred_pool = (
        classified["linux"]
        or classified["windows"]
        or classified["macos"]
        or classified["unknown"]
        or default_options
    )
    filtered = [option for option in preferred_pool if not _looks_like_tooling_entry(option)]
    return filtered or preferred_pool


def _looks_like_tooling_entry(option: SteamLaunchOption) -> bool:
    haystack = " ".join(
        (
            option.executable,
            option.arguments,
            option.description,
            option.launch_type,
        )
    ).lower()
    return any(
        token in haystack
        for token in (
            "crash",
            "report",
            "launcher",
            "prelauncher",
            "server",
            "tool",
            "editor",
            "browser",
            "benchmark",
            "setup",
            "installer",
            "prereq",
            "sdk",
            "dedicated",
        )
    )


def _as_dict(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        return value
    return {}


def _classify_platform(path: Path) -> str:
    lower = path.name.lower()
    if lower.endswith(".app"):
        return "macos"
    if lower.endswith(".exe"):
        return "windows"

    try:
        header = path.read_bytes()[:4]
    except OSError:
        return "unknown"

    if header.startswith(b"MZ"):
        return "windows"
    if header.startswith(b"\x7fELF") or header.startswith(b"#!"):
        return "linux"
    return "unknown"
