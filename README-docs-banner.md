# Mealie Weekly Leftovers ♻️

<p align="center">
  <img src="docs/banner.png" alt="Mealie Weekly Leftovers banner" width="100%">
</p>

<p align="center">
  Add first-class weekly leftovers support to Mealie's Meal Planner — select previous meals, add notes, and avoid duplicate shopping-list ingredients.
</p>

<p align="center">
  <a href="https://github.com/tuxinetdk/mealie-weekly-leftovers/issues">Report Bug</a>
  ·
  <a href="https://github.com/tuxinetdk/mealie-weekly-leftovers/issues">Request Feature</a>
  ·
  <a href="https://github.com/tuxinetdk/mealie-weekly-leftovers/pulls">Pull Requests</a>
</p>

> **Default language:** Danish (`da-DK`)  
> **Fallback language:** English (`en-US`)  
> This is an independent community project and is **not** an official Mealie feature.

---

## ✨ What it adds

Meal Planner gets three creation modes:

- **Recipe**
- **Leftovers / Rester**
- **Note**

For a leftovers entry you choose one destination day, select one or more earlier meal-plan days, optionally write a note, and save one special recipe entry.

### Example

```text
Wednesday
♻ Weekly Leftovers

From:
✓ Monday — Spaghetti Bolognese
✓ Tuesday — Homemade Pizza

Note:
There is also salad and bread left.
```

The project automatically creates the special recipe **“Rester fra Ugen”** (or the localized equivalent) the first time it is needed. It has no ingredients.

---

## 🛒 Shopping lists

Weekly Leftovers entries are explicitly excluded from Meal Planner's **Add all to shopping list** flow, so leftovers do not add duplicate ingredients to your list.

The source recipes remain untouched.

---

## 🌍 Languages

Translations live in `locales/` as plain JSON files.

Bundled by default:

- `da-DK.json`
- `en-US.json`
- `en-GB.json`

To add a language:

1. Copy `locales/TEMPLATE.json`
2. Rename it to the correct Mealie locale, for example `de-DE.json`
3. Translate the values, **not** the keys
4. Run:

```bash
python3 scripts/validate-locales.py
```

No Python code changes are required.

If Mealie does not ship a matching locale file, that locale is skipped during patching.

---

## ⚙️ Configuration

`config/default.json` controls the default locale, fallback locale, and optional recipe name.

```json
{
  "default_locale": "da-DK",
  "fallback_locale": "en-US",
  "recipe_name": null
}
```

When `recipe_name` is `null`, the special recipe name is taken from the default locale’s `leftovers-week-recipe` string.

---

## 🚀 Fast Docker builds

Weekly Leftovers changes frontend code only.  
The included build flow therefore avoids rebuilding the full Mealie runtime for every small patch.

The fast build process:

1. Downloads the exact pinned Mealie source tag
2. Applies the Weekly Leftovers patch
3. Reuses a cached frontend dependency image based on `package.json` + `yarn.lock`
4. Runs `yarn generate`
5. Starts from the official Mealie image for the exact same version
6. Overlays only the generated frontend bundle

This keeps the official backend, Python environment, OS packages, healthcheck, and entrypoint intact.

---

## 🔄 Automatic Mealie updates

The included Update Guard checks the latest stable Mealie release hourly.

When a newer stable release exists it:

1. Keeps the current Mealie online
2. Downloads the new source
3. Verifies patch compatibility
4. Builds the patched candidate image
5. Only if that succeeds, creates a verified backup
6. Switches to the new image
7. Waits for Docker health
8. Rolls back automatically if activation fails

Major version jumps and releases that explicitly require manual or breaking migration are blocked for review.

---

## 🧩 Install

### Requirements

- Docker + Docker Compose v2
- Mealie pinned with an exact `MEALIE_VERSION=vX.Y.Z` in `.env`
- PostgreSQL container named `mealie-postgres`
- Linux with `systemd` for the supplied automatic timers

### Install the update guard

```bash
chmod +x scripts/install.sh
sudo ./scripts/install.sh
```

### Recommended first test

```bash
sudo mealie-update-guard dry-run
sudo mealie-update-guard backup
sudo mealie-update-guard install-leftovers
sudo mealie-update-guard status
```

`install-rester` remains an alias for compatibility with early development builds.

---

## ✅ Compatibility

`v1.0.0` is validated against **Mealie v3.23.1**.

The patcher is deliberately **fail-closed**:

- if the upstream Vue source anchors change,
- `--check` fails,
- and the automatic updater keeps the currently working Mealie version online.

---

## 🔁 Legacy compatibility

Entries created by early TuxiNet development builds are still recognized:

- `tuxinet:mealplan:leftovers-week:v3|`
- `tuxinet:mealplan:leftover:v1|`

New entries use:

```text
mealie-weekly-leftovers:v1|
```

---

## 🛠 Manual patch check

```bash
python3 patch/apply_patch.py \
  --root /path/to/mealie-source \
  --config config/default.json \
  --locales locales \
  --check
```

---

## 🤝 Contributing

Contributions are welcome.

Please use:

- **Bug Report** for problems
- **Feature Request** for ideas and improvements
- **Translation** for new or updated language files
- **Pull Request** for code contributions

See also:

- `CONTRIBUTING.md`
- `docs/TRANSLATIONS.md`

---

## 📈 Repository activity

[![Star History Chart](https://api.star-history.com/svg?repos=tuxinetdk/mealie-weekly-leftovers&type=Date)](https://www.star-history.com/#tuxinetdk/mealie-weekly-leftovers&Date)

---

## 📄 License

MIT — see `LICENSE`.
