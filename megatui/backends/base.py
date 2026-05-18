"""Backend abstract interface."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from ..parsers import Adapter, BBUStatus, Enclosure, LogicalDrive, PhysicalDrive
from ..runner import Result, Runner


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

    @abstractmethod
    def supports(self, action_key: str) -> bool:
        """Whether this backend has an argv translation for action_key."""

    @abstractmethod
    def build_argv(self, action_key: str, target: Any) -> list[str]:
        """Translate logical action_key + target into backend-specific argv.

        Raises NotImplementedError if `supports(action_key)` is False.
        """

    def run(self, argv: list[str]) -> Result:
        """Execute argv through this backend's Runner (subprocess / fixture)."""
        return self.runner.run(argv)

    def shell_repr(self, argv: tuple[str, ...]) -> str:
        return self.runner.shell_repr(argv)

    def preview_argv(self, argv: list[str]) -> list[str]:
        """Return the full argv (with sudo / binary prepended) that would run."""
        return self.runner._build_argv(argv)  # noqa: SLF001
