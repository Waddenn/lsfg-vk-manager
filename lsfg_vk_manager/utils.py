from __future__ import annotations

import re
from pathlib import Path


def parse_acf(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    pairs = re.findall(r'"([^"]+)"\s+"([^"]*)"', text)
    return {key: value for key, value in pairs}


def normalize_exec(value: str) -> str:
    return value.strip().replace("\\", "/").lower()


def escape_toml(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')

