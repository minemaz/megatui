"""CLI entry point for megatui."""
import argparse
import os
import sys

from .backends import available_backends
from .i18n import SUPPORTED, detect_lang, set_lang, t
from .tui import run


def main(argv: list[str] | None = None) -> int:
    # Pick a tentative language from env BEFORE parsing args so --help shows
    # localized text. --lang on the command line still wins later.
    set_lang(detect_lang())

    p = argparse.ArgumentParser(
        prog="megatui",
        description=t(
            "cli.description",
            default=("curses TUI for LSI MegaCli64 / storcli64 / sas3ircu "
                     "(MegaRAID & SAS HBAs)."),
        ),
    )
    p.add_argument(
        "--backend",
        choices=("auto", "megacli", "storcli", "ircu"),
        default="auto",
        help=t(
            "cli.backend.help",
            default=("Which CLI backend to drive. 'auto' prefers storcli, "
                     "then MegaCli64, then sas*ircu."),
        ),
    )
    p.add_argument(
        "--lang",
        choices=SUPPORTED,
        default=None,
        help=t(
            "cli.lang.help",
            default=("UI language. Defaults to LANG/LC_MESSAGES env var, "
                     "then 'en'."),
        ),
    )
    p.add_argument(
        "--no-sudo",
        action="store_true",
        help=t("cli.no_sudo.help",
               default="Don't prepend sudo when calling the backend binary."),
    )
    p.add_argument(
        "--fixtures",
        metavar="DIR",
        help=t(
            "cli.fixtures.help",
            default=("Replay backend output from DIR (offline / dry-run mode). "
                     "Write actions are logged but not executed."),
        ),
    )
    p.add_argument(
        "--list-backends",
        action="store_true",
        help=t("cli.list_backends.help",
               default="Print which backends are installed and exit."),
    )
    args = p.parse_args(argv)

    if args.lang:
        set_lang(args.lang)

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
