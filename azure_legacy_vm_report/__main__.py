"""Module entry point: ``python3 -m azure_legacy_vm_report``."""

from __future__ import annotations

import sys

from .cli import run_cli

if __name__ == "__main__":
    sys.exit(run_cli())
