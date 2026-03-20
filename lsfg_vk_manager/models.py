from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .gpu import GPU_FALLBACK_NAME


@dataclass
class Profile:
    name: str
    active_in: list[str]
    multiplier: int = 2
    flow_scale: float = 1.0
    performance_mode: bool = False
    pacing: str = "none"
    gpu: str | None = None
    managed_appid: str | None = None


@dataclass
class Game:
    appid: str
    name: str
    installdir: str
    install_path: Path
    executables: list[str]
    detected_executables: list[str] = field(default_factory=list)
    enabled: bool = False
    profile_name: str = ""
    multiplier: int = 2
    flow_scale: float = 1.0
    performance_mode: bool = False
    pacing: str = "none"
    gpu: str = GPU_FALLBACK_NAME
    matched_profile_name: str | None = None
    matched_profile: Profile | None = None
    profile_source: str | None = None
