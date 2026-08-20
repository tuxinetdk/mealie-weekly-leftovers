# Mealie Weekly Leftovers ♻️

<p align="center">
  <img src="docs/banner.png" alt="Mealie Weekly Leftovers banner" width="100%">
</p>

A community patch for [Mealie](https://github.com/mealie-recipes/mealie) that adds a first-class **Weekly Leftovers** workflow to the Meal Planner.

Default language: **Danish (`da-DK`)**  
Fallback language: **English (`en-US`)**

> This is an independent community project and is not an official Mealie feature.

## What it adds

Meal Planner gets three creation modes:

- **Recipe**
- **Leftovers / Rester**
- **Note**

For a leftovers entry you choose one destination day, select one or more earlier meal-plan days, optionally write a note, and save one special recipe entry.

Example:

```text
Wednesday
♻ Weekly Leftovers

From:
✓ Monday — Spaghetti Bolognese
✓ Tuesday — Homemade pizza

Note:
There is also salad and bread left.
```

The project automatically creates the special recipe (`Rester fra Ugen` by default) the first time it is needed. It has no ingredients.

## Shopping lists

Weekly Leftovers entries are explicitly excluded from Meal Planner's **Add all to shopping list** flow. The source recipes remain untouched.

## Languages

Translations live in [`locales/`](locales/) as plain JSON.

Bundled:

- `da-DK.json`
- `en-US.json`
- `en-GB.json`

To add a language:

1. Copy `locales/TEMPLATE.json` to the Mealie locale name, for example `de-DE.json`.
2. Translate the values, not the keys.
3. Run:

```bash
python3 scripts/validate-locales.py
```

No Python changes are required.

If Mealie does not ship a matching locale file, that locale is skipped during patching.

## Special recipe name

`config/default.json` controls the default/fallback locale and optional recipe name.

```json
{
  "default_locale": "da-DK",
  "fallback_locale": "en-US",
  "recipe_name": null
}
```

When `recipe_name` is `null`, the special recipe name is taken from the default locale's `leftovers-week-recipe` string.

## Fast Docker builds

Weekly Leftovers changes frontend code only. The installer therefore does **not** rebuild the complete Mealie runtime for every patch.

The fast build:

1. downloads the exact pinned Mealie source tag;
2. applies the patch;
3. reuses a frontend dependency image keyed by `package.json` + `yarn.lock`;
4. runs `yarn generate`;
5. starts from the official Mealie image for the exact same version;
6. overlays only the generated frontend bundle.

The official backend, Python environment, OS packages, healthcheck and entrypoint are retained.

## Automatic Mealie updates

The included Update Guard checks the latest stable Mealie release hourly.

When a newer stable release exists it:

1. keeps the current Mealie online;
2. downloads the new source;
3. verifies patch compatibility;
4. builds the patched candidate image;
5. only if that succeeds, creates a verified backup;
6. switches to the new image;
7. waits for Docker health;
8. rolls back automatically if activation fails.

Major-version changes and release notes that explicitly require a manual/breaking migration are blocked for review.

## Install

Prerequisites:

- Docker + Docker Compose v2
- Mealie pinned with an exact `MEALIE_VERSION=vX.Y.Z` in `.env`
- PostgreSQL container named `mealie-postgres`
- Linux with systemd for the supplied automatic timers

```bash
chmod +x scripts/install.sh
sudo ./scripts/install.sh
```

Then test:

```bash
sudo mealie-update-guard dry-run
sudo mealie-update-guard backup
sudo mealie-update-guard install-leftovers
sudo mealie-update-guard status
```

`install-rester` remains an alias for compatibility with early development builds.

## Compatibility

v1.0.0 is validated against **Mealie v3.23.1**.

The patcher is deliberately fail-closed: if the upstream Vue source anchors change, `--check` fails and the automatic updater keeps the currently working Mealie version online.

## Legacy compatibility

Entries created by early TuxiNet development builds are still recognized:

- `tuxinet:mealplan:leftovers-week:v3|`
- `tuxinet:mealplan:leftover:v1|`

New entries use:

```text
mealie-weekly-leftovers:v1|
```

## Manual patch check

```bash
python3 patch/apply_patch.py \
  --root /path/to/mealie-source \
  --config config/default.json \
  --locales locales \
  --check
```


## Repository activity

[![Star History Chart](https://api.star-history.com/svg?repos=tuxinetdk/mealie-weekly-leftovers&type=Date)](https://www.star-history.com/#tuxinetdk/mealie-weekly-leftovers&Date)

## License

MIT. See [LICENSE](LICENSE).
