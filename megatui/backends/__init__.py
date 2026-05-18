"""Pluggable controller-management backends.

Three backends ship today: `megacli` (MegaCli64 text output), `storcli`
(storcli64 JSON output), and `ircu` (sas3ircu / sas2ircu text output).
All expose the same typed data model defined in `megatui.parsers` so
the TUI doesn't care which one produced the snapshot.
"""
from __future__ import annotations

import os
from typing import Literal

from .base import Backend, BackendUnavailable
from .ircu import IrcuBackend, find_ircu_binary
from .megacli import MegaCliBackend, DEFAULT_MEGACLI_PATH
from .storcli import StorcliBackend, DEFAULT_STORCLI_PATH


BackendName = Literal["megacli", "storcli", "ircu", "auto"]


def available_backends() -> list[str]:
    """Return names of backends whose binary is on disk."""
    import shutil
    out: list[str] = []
    if os.path.isfile(DEFAULT_STORCLI_PATH) or shutil.which("storcli64"):
        out.append("storcli")
    if os.path.isfile(DEFAULT_MEGACLI_PATH) or shutil.which("MegaCli64"):
        out.append("megacli")
    if find_ircu_binary() is not None:
        out.append("ircu")
    return out


def _fixture_dir_kind(d: str) -> str | None:
    """Inspect a fixtures dir; return 'storcli' / 'megacli' / 'ircu' / None."""
    markers = (
        ("storcli", "c0_show_all.json"),
        ("storcli", os.path.join("storcli", "c0_show_all.json")),
        ("ircu",    "display.txt"),
        ("ircu",    os.path.join("ircu", "display.txt")),
        ("megacli", "pdlist.txt"),
        ("megacli", "adpinfo.txt"),
    )
    for kind, fname in markers:
        if os.path.isfile(os.path.join(d, fname)):
            return kind
    return None


def detect(name: BackendName = "auto", *, use_sudo: bool = True,
           fixtures_dir: str | None = None) -> Backend:
    """Pick a backend by name, or auto-detect.

    Auto-detection priority:
      1. If `fixtures_dir` is given, inspect its contents and pick the
         backend that owns the marker file present.
      2. Otherwise prefer storcli (newer, JSON output), then ircu
         (for IT/IR mode HBAs without storcli), then MegaCli.
    """
    if name == "storcli":
        return StorcliBackend(use_sudo=use_sudo, fixtures_dir=fixtures_dir)
    if name == "megacli":
        return MegaCliBackend(use_sudo=use_sudo, fixtures_dir=fixtures_dir)
    if name == "ircu":
        return IrcuBackend(use_sudo=use_sudo, fixtures_dir=fixtures_dir)

    # auto
    if fixtures_dir:
        kind = _fixture_dir_kind(fixtures_dir)
        if kind == "storcli":
            return StorcliBackend(use_sudo=use_sudo, fixtures_dir=fixtures_dir)
        if kind == "ircu":
            return IrcuBackend(use_sudo=use_sudo, fixtures_dir=fixtures_dir)
        if kind == "megacli":
            return MegaCliBackend(use_sudo=use_sudo, fixtures_dir=fixtures_dir)
    avail = available_backends()
    if "storcli" in avail:
        return StorcliBackend(use_sudo=use_sudo, fixtures_dir=fixtures_dir)
    if "megacli" in avail:
        return MegaCliBackend(use_sudo=use_sudo, fixtures_dir=fixtures_dir)
    if "ircu" in avail:
        return IrcuBackend(use_sudo=use_sudo, fixtures_dir=fixtures_dir)
    raise BackendUnavailable(
        "no storcli64 / MegaCli64 / sas*ircu installed; pass --fixtures or install one"
    )


__all__ = [
    "Backend",
    "BackendName",
    "BackendUnavailable",
    "IrcuBackend",
    "MegaCliBackend",
    "StorcliBackend",
    "available_backends",
    "detect",
]
