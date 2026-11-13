"""Entry point: python -m mesadock.

Two modes share this entry point:

* no sub-command  -> start the GUI (tray + docks, optionally the Manager)
* a sub-command   -> run the maintenance CLI (doctor, list, add, restore, ...)
"""
from __future__ import annotations

import sys

CLI_COMMANDS = ("doctor", "list", "add", "restore", "autostart", "export", "import")


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)

    if args and args[0] in CLI_COMMANDS:
        from mesadock.cli import main as cli_main

        return cli_main(args)

    import argparse

    parser = argparse.ArgumentParser(prog="mesadock", description="Desktop shortcut docks for Windows")
    parser.add_argument("--version", action="store_true", help="print the version and exit")
    parser.add_argument("--manager", action="store_true", help="open the Manager window on start")
    parser.add_argument("--portable", metavar="DIR", help="keep all data in DIR instead of %%APPDATA%%")
    parser.add_argument("--no-desktop", action="store_true", help="do not attach docks to the desktop (testing)")
    parsed = parser.parse_args(args)

    if parsed.version:
        from mesadock import __version__

        print("MesaDock " + __version__)
        return 0

    if parsed.portable:
        import os

        os.environ["MESADOCK_HOME"] = parsed.portable
    if parsed.no_desktop:
        import os

        os.environ["MESADOCK_NO_DESKTOP"] = "1"

    from mesadock.app_boot import run_app

    return run_app(show_manager=parsed.manager)


if __name__ == "__main__":
    sys.exit(main())
