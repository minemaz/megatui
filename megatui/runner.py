"""MegaCli64 invocation wrapper.

Runs MegaCli64 (typically via sudo) and returns (rc, stdout, stderr).
Supports a fixture mode for offline development: set MEGATUI_FIXTURES to a
directory and any matching command will be served from a file there instead
of executing the binary.
"""
from __future__ import annotations

import os
import shlex
import subprocess
from dataclasses import dataclass


DEFAULT_BIN = "/opt/MegaRAID/MegaCli/MegaCli64"


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


def _fixture_lookup(args: tuple[str, ...]) -> str | None:
    """Map a MegaCli arg vector to a fixture filename inside MEGATUI_FIXTURES."""
    fixtures_dir = os.environ.get("MEGATUI_FIXTURES")
    if not fixtures_dir:
        return None
    joined = " ".join(args).lower()
    candidates: list[str] = []
    if "-pdlist" in joined:
        candidates.append("pdlist.txt")
    elif "-ldinfo" in joined:
        candidates.append("ldinfo.txt")
    elif "-adpallinfo" in joined:
        candidates.append("adpinfo.txt")
    elif "-encinfo" in joined:
        candidates.append("encinfo.txt")
    elif "-getbbustatus" in joined or "-adpbbucmd" in joined:
        candidates.append("bbu.txt")
    elif "-adpcount" in joined:
        candidates.append("adpcount.txt")
    for name in candidates:
        path = os.path.join(fixtures_dir, name)
        if os.path.isfile(path):
            return path
    return None


class Runner:
    """Wraps MegaCli64 with optional sudo and fixture replay."""

    def __init__(
        self,
        binary: str = DEFAULT_BIN,
        use_sudo: bool = True,
        timeout: float = 30.0,
    ) -> None:
        self.binary = binary
        self.use_sudo = use_sudo
        self.timeout = timeout

    def _build_argv(self, args: list[str]) -> list[str]:
        argv: list[str] = []
        if self.use_sudo:
            argv.extend(["sudo", "-n"])
        argv.append(self.binary)
        argv.extend(args)
        if "-NoLog" not in args:
            argv.append("-NoLog")
        return argv

    def run(self, args: list[str]) -> Result:
        argv = self._build_argv(args)
        argv_t = tuple(argv)

        fixture = _fixture_lookup(argv_t)
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

    def adp_count(self) -> int:
        r = self.run(["-adpCount"])
        for line in r.stdout.splitlines():
            if "Controller Count" in line:
                _, _, rhs = line.partition(":")
                rhs = rhs.strip().rstrip(".")
                if rhs.isdigit():
                    return int(rhs)
        return 0

    def pdlist(self, adapter: int | str = "ALL") -> Result:
        return self.run(["-PDList", f"-a{adapter}"])

    def ldinfo(self, adapter: int | str = "ALL") -> Result:
        return self.run(["-LDInfo", "-Lall", f"-a{adapter}"])

    def adp_all_info(self, adapter: int | str = "ALL") -> Result:
        return self.run(["-AdpAllInfo", f"-a{adapter}"])

    def enc_info(self, adapter: int | str = "ALL") -> Result:
        return self.run(["-EncInfo", f"-a{adapter}"])

    def bbu_status(self, adapter: int | str = "ALL") -> Result:
        return self.run(["-AdpBbuCmd", "-GetBbuStatus", f"-a{adapter}"])

    @staticmethod
    def shell_repr(argv: tuple[str, ...]) -> str:
        return " ".join(shlex.quote(a) for a in argv)
