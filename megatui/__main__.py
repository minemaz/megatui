"""CLI entry point for megatui."""
import argparse
import os
import sys

from .tui import run


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="megatui",
        description="curses TUI for LSI MegaCli64 (MegaRAID).",
    )
    p.add_argument(
        "--no-sudo",
        action="store_true",
        help="Don't prepend sudo when calling MegaCli64.",
    )
    p.add_argument(
        "--fixtures",
        metavar="DIR",
        help=(
            "Replay MegaCli output from DIR (offline / dry-run mode). "
            "Write actions are logged but not executed."
        ),
    )
    args = p.parse_args(argv)

    if args.fixtures:
        os.environ["MEGATUI_FIXTURES"] = args.fixtures
    fixture_mode = bool(args.fixtures or os.environ.get("MEGATUI_FIXTURES"))
    return run(use_sudo=not args.no_sudo, fixture_mode=fixture_mode)


if __name__ == "__main__":
    sys.exit(main())
