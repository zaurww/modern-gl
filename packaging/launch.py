"""The entry point PyInstaller freezes (packaging/modern-gl.spec): the desktop program."""

import sys

from modern_gl.desktop.app import main

if __name__ == "__main__":
    sys.exit(main())
