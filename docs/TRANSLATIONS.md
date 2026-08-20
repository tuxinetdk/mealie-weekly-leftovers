# Translations

Locale files are plain JSON objects. The filename must match a locale file that Mealie already ships.

Example:

```json
{
  "leftovers": "Leftovers",
  "leftovers-from": "Leftovers from",
  "leftovers-week-recipe": "Weekly Leftovers"
}
```

Use `locales/TEMPLATE.json` as the complete key list.

Validate all bundled translations:

```bash
python3 scripts/validate-locales.py
```

The fallback locale defines the required key set. Every bundled locale must contain the same keys.

The default locale is `da-DK`; fallback is `en-US`.
