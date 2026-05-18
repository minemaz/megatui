"""Pluggable controller-management backends.

Two backends ship today: `megacli` (MegaCli64 text output) and
`storcli` (storcli64 JSON output). Both expose the same typed data
model defined in `megatui.parsers` so the TUI doesn't care which one
produced the snapshot.
"""
from __future__ import annotations

import os
import shutil
from typing import Literal

from .base import Backend, BackendUnavailable
from .megacli import MegaCliBackend, DEFAULT_MEGACLI_PATH
from .storcli import StorcliBackend, DEFAULT_STORCLI_PATH


BackendName = Literal["megacli", "storcli", "auto"]


def available_backends() -> list[str]:
    """Return names of backends whose binary is on disk."""
    out: list[str] = []
    if os.path.isfile(DEFAULT_STORCLI_PATH) or shutil.which("storcli64"):
        out.append("storcli")
    if os.path.isfile(DEFAULT_MEGACLI_PATH) or shutil.which("MegaCli64"):
        out.append("megacli")
    return out


def _fixture_dir_kind(d: str) -> str | None:
    """Inspect a fixtures dir; return 'storcli' or 'megacli' or None."""
    storcli_markers = ("c0_show_all.json", os.path.join("storcli", "c0_show_all.json"))
    megacli_markers = ("pdlist.txt", "adpinfo.txt")
    for m in storcli_markers:
        if os.path.isfile(os.path.join(d, m)):
            return "storcli"
    for m in megacli_markers:
        if os.path.isfile(os.path.join(d, m)):
            return "megacli"
    return None


def detect(name: BackendName = "auto", *, use_sudo: bool = True,
           fixtures_dir: str | None = None) -> Backend:
    """Pick a backend by name, or auto-detect.

    Auto-detection priority:
      1. If `fixtures_dir` is given, inspect its contents (storcli JSON
         files vs MegaCli text files) and pick accordingly.
      2. Otherwise prefer storcli (newer, JSON output) when its binary
         is installed.
      3. Fall back to MegaCli.
    """
    if name == "storcli":
        return StorcliBackend(use_sudo=use_sudo, fixtures_dir=fixtures_dir)
    if name == "megacli":
        return MegaCliBackend(use_sudo=use_sudo, fixtures_dir=fixtures_dir)

    # auto
    if fixtures_dir:
        kind = _fixture_dir_kind(fixtures_dir)
        if kind == "storcli":
            return StorcliBackend(use_sudo=use_sudo, fixtures_dir=fixtures_dir)
        if kind == "megacli":
            return MegaCliBackend(use_sudo=use_sudo, fixtures_dir=fixtures_dir)
    avail = available_backends()
    if "storcli" in avail:
        return StorcliBackend(use_sudo=use_sudo, fixtures_dir=fixtures_dir)
    if "megacli" in avail:
        return MegaCliBackend(use_sudo=use_sudo, fixtures_dir=fixtures_dir)
    raise BackendUnavailable(
        "no storcli64 or MegaCli64 installed; install one or pass --fixtures"
    )


__all__ = [
    "Backend",
    "BackendName",
    "BackendUnavailable",
    "MegaCliBackend",
    "StorcliBackend",
    "available_backends",
    "detect",
]
