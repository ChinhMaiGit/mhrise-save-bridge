"""PyInstaller entry point: a double-click (no arguments) starts the guided mode."""

import sys

from mhrise_save_bridge.cli import main

sys.exit(main())
