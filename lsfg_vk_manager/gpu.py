from __future__ import annotations

import subprocess


GPU_FALLBACK_NAME = "Auto-detected GPU"


def _detect_with_lspci() -> str | None:
    try:
        result = subprocess.run(
            ["lspci"],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return None

    if result.returncode != 0:
        return None

    candidates: list[str] = []
    for line in result.stdout.splitlines():
        lower = line.lower()
        if "vga compatible controller" in lower or "3d controller" in lower:
            candidates.append(line.strip())

    if not candidates:
        return None

    primary = candidates[0]
    parts = primary.split(": ", 2)
    if len(parts) >= 3:
        return parts[2].strip()
    if len(parts) == 2:
        return parts[1].strip()
    return primary


def detect_default_gpu() -> str:
    return _detect_with_lspci() or GPU_FALLBACK_NAME
