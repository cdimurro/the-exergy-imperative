"""Discover, validate, dry-run, and execute an agent recipe."""

from __future__ import annotations

import json
from pathlib import Path

import exergy_imperative as xi

recipe_path = Path(__file__).with_name("agent_process_recipe.json")
recipe = json.loads(recipe_path.read_text(encoding="utf-8"))

print(json.dumps(xi.validate_recipe(recipe, mode="validate-only"), indent=2))

dry_run = xi.run_recipe(recipe, mode="dry-run")
print(dry_run.to_dict()["result"]["assessment"]["tier"])

# Execute only when outputs are intentionally wanted:
# executed = xi.run_recipe(recipe)
# print(executed.to_dict()["artifacts"])
