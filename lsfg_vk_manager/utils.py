from __future__ import annotations

import re
from pathlib import Path


def parse_acf(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    return parse_acf_text(text)


def parse_acf_text(text: str) -> dict[str, str]:
    tokens = re.findall(r'"([^"]+)"|([{}])', text)
    flat_tokens = [quoted or brace for quoted, brace in tokens]

    result: dict[str, str] = {}
    pending_key: str | None = None
    stack: list[str] = []

    for token in flat_tokens:
        if token == "{":
            if pending_key is not None:
                stack.append(pending_key)
                pending_key = None
            else:
                stack.append("")
            continue
        if token == "}":
            if stack:
                stack.pop()
            pending_key = None
            continue

        if pending_key is None:
            pending_key = token
            continue

        if stack == ["AppState"]:
            result[pending_key] = token
        pending_key = None

    return result


def normalize_exec(value: str) -> str:
    return value.strip().replace("\\", "/").lower()


def escape_toml(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def format_error_message(exc: Exception) -> str:
    message = str(exc).strip()
    if message:
        return message
    return exc.__class__.__name__
