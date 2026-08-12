#!/usr/bin/env python3
"""Fail when committed skill packages differ from canonical generation."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


SCRIPT = Path(__file__).with_name("build_skills.py")


def main() -> int:
    return subprocess.run([sys.executable, str(SCRIPT), "--check"], check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())

