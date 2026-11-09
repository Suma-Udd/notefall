"""Entry point for the packaged desktop app (PyInstaller)."""

import multiprocessing
import sys

if __name__ == "__main__":
    multiprocessing.freeze_support()
    if len(sys.argv) > 1 and not sys.argv[1].startswith("-psn"):
        # dropped a file on the app, or called from a terminal: act like the CLI
        from notefall.cli import main
    else:
        from notefall.gui import main
    sys.exit(main())
