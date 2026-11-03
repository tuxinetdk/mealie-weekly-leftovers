#!/usr/bin/env python3
"""Verify that every upstream Mealie locale has complete Rester7 strings."""
import argparse
import json
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--root", type=Path, required=True)
parser.add_argument("--locales", type=Path, default=Path(__file__).resolve().parents[1] / "locales")
args = parser.parse_args()

fallback = json.loads((args.locales / "en-US.json").read_text(encoding="utf-8"))
keys = set(fallback)
assert keys and all(isinstance(v, str) for v in fallback.values())
localized = {}
for source in args.locales.glob("*.json"):
    if source.name != "TEMPLATE.json":
        obj = json.loads(source.read_text(encoding="utf-8"))
        assert set(obj) == keys, f"{source.name}: keys differ from en-US"
        localized[source.stem] = obj

targets = sorted((args.root / "frontend/app/lang/messages").glob("*.json"))
assert targets, "No Mealie locale files found"
for target in targets:
    meal_plan = json.loads(target.read_text(encoding="utf-8")).get("meal-plan")
    assert isinstance(meal_plan, dict), f"{target.name}: missing meal-plan"
    expected = localized.get(target.stem, fallback)
    for key, value in expected.items():
        assert meal_plan.get(key) == value, f"{target.name}: incorrect {key}"
print(f"PASS: {len(targets)} Mealie locales, {len(keys)} Rester7 keys each")
