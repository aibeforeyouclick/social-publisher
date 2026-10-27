#!/usr/bin/env python3
"""Launcher. Run isolated: `python -I publish.py <command>` (see README)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from socialpub.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
