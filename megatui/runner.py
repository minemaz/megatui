"""Subprocess wrapper for vendor CLIs (MegaCli64 / storcli64).

Generic enough to be shared by both backends. Each backend owns the
fixture-name mapping that decides which file in MEGATUI_FIXTURES is
served for a given argv vector.
"""
from __future__ import annotations

import os
import shlex
import subprocess
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class Result:
    rc: int
    stdout: str
    stderr: str
    argv: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return self.rc == 0

    @property
    def text(self) -> str:
        return self.stdout if self.stdout else self.stderr


# Fixture lookup callable: (args, fixtures_dir) -> filename | None
FixtureLookup = Callable[[list[str], str], str | None]


class Runner:
    """Wraps a vendor CLI with optional sudo and per-backend fixture replay."""

    def __init__(
        self,
        binary: str,
        *,
        use_sudo: bool = True,
        timeout: float = 30.0,
        fixtures_dir: str | None = None,
        fixture_lookup: FixtureLookup | None = None,
        append_args: list[str] | None = None,
    ) -> None:
        self.binary = binary
        self.use_sudo = use_sudo
        self.timeout = timeout
        self.fixtures_dir = fixtures_dir or os.environ.get("MEGATUI_FIXTURES")
        self.fixture_lookup = fixture_lookup
        # Args appended to every invocation (e.g. MegaCli's -NoLog suppress)
        self.append_args = list(append_args or [])

    def _build_argv(self, args: list[str]) -> list[str]:
        return self._build_argv_with(self.binary, args, include_append_args=True)

    def _build_argv_with(self, binary: str, args: list[str],
                         *, include_append_args: bool = False) -> list[str]:
        """Build a full argv but for a possibly-different binary.

        Used by actions that bypass the backend's vendor CLI (sg_format
        for sector reformat). `include_append_args` is False by default
        so the backend's `-NoLog` / `J` suffix isn't accidentally
        appended to a foreign tool.
        """
        argv: list[str] = []
        if self.use_sudo:
            argv.extend(["sudo", "-n"])
        argv.append(binary)
        argv.extend(args)
        if include_append_args:
            for tail in self.append_args:
                if tail not in args:
                    argv.append(tail)
        return argv

    def _fixture_path(self, args: list[str]) -> str | None:
        if not self.fixtures_dir or not self.fixture_lookup:
            return None
        name = self.fixture_lookup(args, self.fixtures_dir)
        if name is None:
            return None
        path = os.path.join(self.fixtures_dir, name)
        return path if os.path.isfile(path) else None

    def run(self, args: list[str]) -> Result:
        return self._exec(self._build_argv(args), allow_fixture=True, fixture_args=args)

    def run_with(self, binary: str, args: list[str]) -> Result:
        """Run a different binary (e.g. sg_format) without fixture replay
        or backend-binary append-args."""
        return self._exec(
            self._build_argv_with(binary, args),
            allow_fixture=False,
            fixture_args=args,
        )

    def _exec(self, argv: list[str], *, allow_fixture: bool,
              fixture_args: list[str]) -> Result:
        argv_t = tuple(argv)

        if allow_fixture:
            fixture = self._fixture_path(fixture_args)
            if fixture is not None:
                with open(fixture, "r", encoding="utf-8", errors="replace") as f:
                    return Result(rc=0, stdout=f.read(), stderr="", argv=argv_t)

        try:
            proc = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                check=False,
            )
        except FileNotFoundError as exc:
            return Result(rc=127, stdout="", stderr=f"binary not found: {exc}", argv=argv_t)
        except subprocess.TimeoutExpired as exc:
            return Result(
                rc=124,
                stdout=exc.stdout or "",
                stderr=(exc.stderr or "") + f"\ntimeout after {self.timeout}s",
                argv=argv_t,
            )
        return Result(
            rc=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
            argv=argv_t,
        )

    @staticmethod
    def shell_repr(argv: tuple[str, ...]) -> str:
        return " ".join(shlex.quote(a) for a in argv)
