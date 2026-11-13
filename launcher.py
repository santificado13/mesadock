"""PyInstaller entry point (see build.ps1)."""
import sys

from mesadock.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
