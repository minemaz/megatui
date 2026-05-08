"""Audit log for write operations.

Appends one line per invocation to ~/.local/share/megatui/audit.log
(overridable via MEGATUI_AUDIT_LOG).
"""
from __future__ import annotations

import os
import time
from pathlib import Path


def _log_path() -> Path:
    override = os.environ.get("MEGATUI_AUDIT_LOG")
    if override:
        return Path(override).expanduser()
    base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return Path(base) / "megatui" / "audit.log"


def log(action: str, argv: tuple[str, ...] | list[str], rc: int, summary: str = "") -> None:
    path = _log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    cmd = " ".join(argv)
    one_line_summary = " | ".join(s.strip() for s in summary.splitlines() if s.strip())[:400]
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"{ts}\t{action}\trc={rc}\t{cmd}\t{one_line_summary}\n")


def tail(n: int = 50) -> list[str]:
    path = _log_path()
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.readlines()[-n:]
