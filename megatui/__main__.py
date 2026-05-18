"""CLI entry point for megatui."""
import argparse
import os
import sys

from .backends import available_backends
from .tui import run


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="megatui",
        description="curses TUI for LSI MegaCli64 / storcli64 (MegaRAID & SAS HBAs).",
    )
    p.add_argument(
        "--backend",
        choices=("auto", "megacli", "storcli"),
        default="auto",
        help="Which CLI backend to drive. 'auto' prefers storcli when installed.",
    )
    p.add_argument(
        "--no-sudo",
        action="store_true",
        help="Don't prepend sudo when calling the backend binary.",
    )
    p.add_argument(
        "--fixtures",
        metavar="DIR",
        help=(
            "Replay backend output from DIR (offline / dry-run mode). "
            "Write actions are logged but not executed."
        ),
    )
    p.add_argument(
        "--list-backends",
        action="store_true",
        help="Print which backends are installed and exit.",
    )
    args = p.parse_args(argv)

    if args.list_backends:
        installed = available_backends()
        print("Installed backends:", ", ".join(installed) if installed else "(none)")
        return 0

    if args.fixtures:
        os.environ["MEGATUI_FIXTURES"] = args.fixtures
    fixtures_dir = args.fixtures or os.environ.get("MEGATUI_FIXTURES")
    fixture_mode = bool(fixtures_dir)
    return run(
        use_sudo=not args.no_sudo,
        fixture_mode=fixture_mode,
        backend_name=args.backend,
        fixtures_dir=fixtures_dir,
    )


if __name__ == "__main__":
    sys.exit(main())
