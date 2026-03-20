from __future__ import annotations

import os
from pathlib import Path

from .constants import EXECUTABLE_SUFFIXES, SKIP_EXEC_NAMES
from .utils import normalize_exec


def is_candidate_executable(path: Path) -> bool:
    if not path.is_file():
        return False

    lower = path.name.lower()
    if lower in SKIP_EXEC_NAMES:
        return False

    if path.suffix.lower() in EXECUTABLE_SUFFIXES:
        return True

    try:
        return os.access(path, os.X_OK)
    except OSError:
        return False


def score_executable(path: Path, game_name: str) -> tuple[int, str]:
    rel = str(path).replace("\\", "/").lower()
    name = path.name.lower()
    base = game_name.lower().replace(":", "").replace("-", "").replace(" ", "")
    score = 0

    if "bin64" in rel or "binlinux" in rel:
        score += 25
    if name.endswith(".exe"):
        score += 20
    if base and base in name.replace(".", "").replace("_", "").replace("-", ""):
        score += 40
    if "demo" in rel and "demo" in base:
        score += 10
    if any(token in name for token in ("launcher", "crash", "support", "eac")):
        score -= 50

    return score, rel


def discover_executables(install_path: Path, game_name: str) -> list[str]:
    if not install_path.exists():
        return []

    candidates: list[Path] = []
    for root, dirs, files in os.walk(install_path):
        rel_depth = len(Path(root).relative_to(install_path).parts)
        if rel_depth > 4:
            dirs[:] = []
            continue
        for filename in files:
            path = Path(root) / filename
            if is_candidate_executable(path):
                candidates.append(path)

    scored = sorted(
        (
            (score_executable(path.relative_to(install_path), game_name), path.relative_to(install_path))
            for path in candidates
        ),
        reverse=True,
    )

    seen: set[str] = set()
    chosen: list[str] = []
    for (_, _), rel_path in scored:
        normalized = normalize_exec(str(rel_path))
        basename = normalize_exec(rel_path.name)
        for candidate in (str(rel_path).replace("\\", "/"), rel_path.name):
            if normalize_exec(candidate) in seen:
                continue
            chosen.append(candidate.replace("\\", "/"))
            seen.add(normalize_exec(candidate))
        seen.add(normalized)
        seen.add(basename)
        if len(chosen) >= 8:
            break

    return chosen

