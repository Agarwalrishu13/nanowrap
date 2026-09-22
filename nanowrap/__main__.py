"""Command line entry point.

Three ways in, in increasing order of nerdiness::

    python start.py             # start the app and open the browser
    python -m nanowrap          # the same thing
    python -m nanowrap doctor   # list the programs this computer has, and stop
"""

from __future__ import annotations

import argparse
import sys

from . import APP_NAME, __version__, store, toolbox


def _doctor() -> int:
    print()
    print("  %s %s — what this computer has" % (APP_NAME, __version__))
    print("  " + "-" * 62)
    print("  %s" % toolbox.version_line())
    print("  Your files live in: %s" % store.data_dir())
    print("  Finished files go to: %s" % store.outputs_dir())
    free = store.free_space_mb()
    if free >= 0:
        print("  Free space there: %s MB" % ("{:,}".format(free)))
    print()
    print("  Programs found")
    for entry in toolbox.find_all(use_cache=False):
        if entry["builtin"]:
            mark, detail = "yes", "built in — nothing to install"
        elif entry["available"]:
            mark = "yes"
            detail = "%s%s" % (entry["path"], ("  (%s)" % entry["version"]) if entry["version"] else "")
        else:
            mark = "no "
            detail = "not installed — %s" % (entry["get_it"] or entry["homepage"])
        print("    [%s] %-12s %s" % (mark, entry["called"], detail))
    print()
    print("  %s" % toolbox.machine_note())
    print()
    print("  Nothing is installed, changed or uploaded by this program. It only runs")
    print("  what is already here, on the files you drop in.")
    print()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="nanowrap",
        description="%s — %s" % (APP_NAME, "the programs already on your computer, with buttons."),
        epilog="Run it with no arguments and a browser window opens.",
    )
    parser.add_argument("command", nargs="?", default="run", choices=["run", "doctor", "version"])
    parser.add_argument("--port", type=int, default=8765, help="which port to use (default 8765)")
    parser.add_argument("--host", default="127.0.0.1", help="address to listen on (default: this computer only)")
    parser.add_argument("--no-browser", action="store_true", help="do not open a browser window")
    parser.add_argument("--version", action="store_true", help="print the version and stop")
    args = parser.parse_args(argv)

    if args.version or args.command == "version":
        print("%s %s" % (APP_NAME, __version__))
        return 0
    if args.command == "doctor":
        return _doctor()

    store.tidy_outputs()

    from .server import create_app

    app = create_app()
    try:
        app.serve(host=args.host, port=args.port, open_browser=not args.no_browser)
    except OSError as exc:
        print("\n  Could not start on %s:%d (%s).\n  Try a different port: --port 8775\n"
              % (args.host, args.port, exc))
        return 1
    finally:
        store.clear_dropped_input()
    return 0


if __name__ == "__main__":
    sys.exit(main())
