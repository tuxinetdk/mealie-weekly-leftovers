# Architecture

## Data model

No custom database migration is used.

A Weekly Leftovers meal-plan entry:

- links to one special Mealie recipe with no ingredients;
- stores source meal-plan entry IDs, source dates, recipe names, and the optional user note in the existing meal-plan `text` field;
- uses a versioned marker prefix.

Current marker:

```text
mealie-weekly-leftovers:v1|{"sources":[...],"note":"..."}
```

This keeps the patch independent from Mealie's Alembic migration graph.

## Upgrade safety

The patcher uses exact source anchors and is intentionally fail-closed. Upstream structural changes cause compatibility checks to fail rather than applying a partial patch.

The Update Guard builds candidate images while the current Mealie remains online. Backup and activation occur only after source compatibility and image build succeed.

## Fast build

The dependency image is keyed by a hash of:

- `frontend/package.json`
- `frontend/yarn.lock`

Feature-only changes therefore normally reuse `node_modules` and only regenerate the frontend bundle.
