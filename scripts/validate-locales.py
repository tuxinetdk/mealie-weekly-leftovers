#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

def load(path: Path) -> dict[str, str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in data.items()):
        raise SystemExit(f"{path}: locale must be a JSON object of string -> string")
    return data

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--locales", type=Path, default=Path(__file__).resolve().parents[1] / "locales")
    parser.add_argument("--fallback", default="en-US")
    args = parser.parse_args()

    fallback = load(args.locales / f"{args.fallback}.json")
    expected = set(fallback)
    failed = False

    for path in sorted(args.locales.glob("*.json")):
        if path.name == "TEMPLATE.json":
            continue
        values = load(path)
        missing = sorted(expected - set(values))
        extra = sorted(set(values) - expected)
        if missing or extra:
            failed = True
            print(f"{path.name}:")
            if missing:
                print("  missing:", ", ".join(missing))
            if extra:
                print("  extra:", ", ".join(extra))
        else:
            print(f"{path.name}: OK")

    return 1 if failed else 0

if __name__ == "__main__":
    raise SystemExit(main())
