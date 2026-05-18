"""SCSI generic helpers — used by drive-level operations that bypass the
vendor CLI (sg_format for sector-size reformat being the canonical case).

These functions resolve a `PhysicalDrive` (described by SAS address /
WWN / Serial) to its `/dev/sgN` device path so we can hand it to
`sg_format`. The lookup needs whatever path-mapping the kernel has set
up, so we ask `lsscsi -tg` for the authoritative view. If the drive
isn't visible to the OS (typical when it's a member of a non-JBOD
MegaRAID VD), the lookup returns None and the caller surfaces a clear
error in the confirmation modal instead of running anything.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .parsers import PhysicalDrive


SG_FORMAT_PATH = "/usr/bin/sg_format"


def sg_format_installed() -> bool:
    return os.path.isfile(SG_FORMAT_PATH) or shutil.which("sg_format") is not None


def _normalize_sas(s: str) -> str:
    """Canonicalize a SAS address for comparison: lowercase, no '0x' prefix,
    no separators."""
    return (s or "").lower().replace("0x", "").replace("-", "").replace(":", "").strip()


def find_sg_path(pd: "PhysicalDrive") -> str | None:
    """Return /dev/sgN for `pd` by matching SAS address via lsscsi.

    Tries the PD's `SAS Address(0)`, falling back to the WWN field. Both
    storcli and ircu populate at least one of these. MegaCli does too on
    most controllers but doesn't generally expose the drive to the OS,
    so the match falls through to None for VD-member drives behind
    non-JBOD MegaRAID — which is correct, since sg_format can't reach
    them anyway.
    """
    candidates: list[str] = []
    for key in ("SAS Address(0)", "SAS Address", "WWN"):
        v = (pd.raw.get(key) or "").strip()
        if v:
            candidates.append(_normalize_sas(v))
    if not candidates:
        return None

    try:
        result = subprocess.run(
            ["lsscsi", "-tg"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None

    for line in result.stdout.splitlines():
        line_norm = _normalize_sas(line)
        if not any(c in line_norm for c in candidates):
            continue
        parts = line.split()
        for part in parts:
            if part.startswith("/dev/sg"):
                return part
    return None


def sg_format_argv(sg_path: str, *, size: int = 512, fmtpinfo: int = 0,
                   early: bool = True, quick: bool = True) -> list[str]:
    """Build the argv for sg_format on a freshly-staged device.

    Defaults are tuned for the homelab "reformat NetApp/HP/Sun SAS HDD
    from 520-byte to 512-byte sectors" case:
        --format                       issue FORMAT UNIT
        --size=512                     target logical block length
        --fmtpinfo=0                   no T10 PI
        --early                        return after kicking off (host
                                       doesn't tie up an SSH session for
                                       the 8-12h drive-internal pass)
        --quick                        skip sg_format's interactive
                                       'are you sure' prompt — we already
                                       did the typed-phrase confirmation
                                       in the TUI
    """
    args = ["--format", f"--size={size}", f"--fmtpinfo={fmtpinfo}"]
    if early:
        args.append("--early")
    if quick:
        args.append("--quick")
    args.append(sg_path)
    return args


class SgPathNotFound(RuntimeError):
    """Raised when no /dev/sgN can be located for a PhysicalDrive."""
