#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
from pathlib import Path

ENTRY_DIALOG_PATH = Path("frontend/app/components/Domain/Household/GroupMealPlanEntryDialog.vue")


def argument_value(name: str) -> str | None:
    try:
        index = sys.argv.index(name)
    except ValueError:
        return None
    if index + 1 >= len(sys.argv):
        return None
    return sys.argv[index + 1]


def main() -> int:
    root_value = argument_value("--root")
    if not root_value:
        print("Weekly Leftovers patch FAILED: --root is required", file=sys.stderr)
        return 2

    root = Path(root_value).resolve()
    module_dir = Path(__file__).resolve().parent

    # Mealie v3.24 moved the meal-plan entry form into this component. Use its
    # presence as a structural feature check instead of relying on a version string.
    if (root / ENTRY_DIALOG_PATH).exists():
        implementation = module_dir / "apply_patch_v324.py"
    else:
        implementation = module_dir / "apply_patch_v323.py"

    if not implementation.is_file():
        print(f"Weekly Leftovers patch FAILED: missing implementation {implementation}", file=sys.stderr)
        return 2

    os.execv(sys.executable, [sys.executable, str(implementation), *sys.argv[1:]])
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
