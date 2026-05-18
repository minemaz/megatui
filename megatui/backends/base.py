"""Backend abstract interface."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from ..parsers import Adapter, BBUStatus, Enclosure, LogicalDrive, PhysicalDrive
from ..runner import Result, Runner
from ..sg_util import (
    SG_FORMAT_PATH,
    SgPathNotFound,
    find_sg_path,
    sg_format_argv,
    sg_format_installed,
)


# Action keys that are not vendor-CLI operations but tool invocations
# (sg_format etc.). They have unified handling across all backends.
_TOOL_ACTIONS = {"pd_reformat_512": SG_FORMAT_PATH}


class BackendUnavailable(RuntimeError):
    """Raised when a requested backend can't be loaded (missing binary, etc.)."""


class Backend(ABC):
    """Common interface implemented by MegaCliBackend and StorcliBackend.

    A backend wraps a CLI binary (MegaCli64 or storcli64) and produces
    typed snapshots of controller state. Each backend declares which
    write actions it supports — the TUI hides ones a given backend can't
    execute. Action argv is built per-backend since the two CLIs have
    completely different syntaxes for the same logical operation.
    """

    name: str  # "megacli" | "storcli"
    runner: Runner

    # ------------------------------------------------------------------ #
    # Read path
    # ------------------------------------------------------------------ #

    @abstractmethod
    def adp_count(self) -> int:
        """Number of controllers detected."""

    @abstractmethod
    def adapters(self) -> list[Adapter]:
        """One Adapter per controller (with sections / flat fields)."""

    @abstractmethod
    def physical_drives(self) -> list[PhysicalDrive]:
        """All physical drives across adapters."""

    @abstractmethod
    def logical_drives(self) -> list[LogicalDrive]:
        """All logical drives (VDs) across adapters."""

    @abstractmethod
    def enclosures(self) -> list[Enclosure]:
        """All enclosures across adapters. May be empty for direct-attach HBAs."""

    @abstractmethod
    def bbu_statuses(self) -> list[BBUStatus]:
        """BBU status per adapter. `present=False` for absent or unsupported."""

    # ------------------------------------------------------------------ #
    # Write path
    # ------------------------------------------------------------------ #

    def supports(self, action_key: str, target: Any = None) -> bool:
        """Whether this backend can execute `action_key` on `target`.

        Subclasses override to consult their own builder dict, but ALL
        backends share tool-action support (e.g. `pd_reformat_512`
        always uses sg_format regardless of vendor CLI). The default
        impl handles tool actions; subclasses delegate to super() to
        keep that behavior.
        """
        if action_key in _TOOL_ACTIONS:
            if not sg_format_installed():
                return False
            if target is None:
                return True
            # PD must have at least one identifier we can match in lsscsi.
            return bool(getattr(target, "raw", {}).get("SAS Address(0)")
                        or getattr(target, "raw", {}).get("WWN"))
        return False

    @abstractmethod
    def build_argv(self, action_key: str, target: Any) -> list[str]:
        """Translate logical action_key + target into backend-specific argv.

        Raises NotImplementedError if `supports(action_key)` is False.
        Subclasses delegate to `_tool_argv` for tool-action keys.
        """

    def tool_for(self, action_key: str) -> str | None:
        """Return the binary path for tool actions (sg_format etc.), else None."""
        return _TOOL_ACTIONS.get(action_key)

    def _tool_argv(self, action_key: str, target: Any) -> list[str]:
        """Build args for a tool action. Raises SgPathNotFound if the PD
        can't be resolved to /dev/sgN."""
        if action_key == "pd_reformat_512":
            sg = find_sg_path(target)
            if sg is None:
                raise SgPathNotFound(
                    "Drive is not accessible via /dev/sg*. It's probably "
                    "hidden behind a RAID controller without JBOD passthrough."
                )
            return sg_format_argv(sg, size=512, fmtpinfo=0,
                                  early=True, quick=True)
        raise NotImplementedError(f"unknown tool action: {action_key}")

    def run(self, argv: list[str], tool: str | None = None) -> Result:
        """Execute argv. If `tool` is given, runs that binary instead of
        the backend's vendor CLI binary (and skips fixture replay /
        backend append-args)."""
        if tool is not None:
            return self.runner.run_with(tool, argv)
        return self.runner.run(argv)

    def shell_repr(self, argv: tuple[str, ...]) -> str:
        return self.runner.shell_repr(argv)

    def preview_argv(self, argv: list[str], tool: str | None = None) -> list[str]:
        """Return the full argv (with sudo + binary prepended) that would run."""
        if tool is not None:
            return self.runner._build_argv_with(tool, argv)  # noqa: SLF001
        return self.runner._build_argv(argv)  # noqa: SLF001
