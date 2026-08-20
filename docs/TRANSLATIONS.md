# Translations

Mealie Weekly Leftovers keeps feature translations outside the patcher as plain JSON files.

## Add a language

1. Confirm that Mealie itself ships the locale you want to add.
2. Copy `locales/TEMPLATE.json` to the exact Mealie locale filename, for example:

   ```bash
   cp locales/TEMPLATE.json locales/de-DE.json
   ```

3. Translate **values only**. Do not rename or remove keys.
4. Preserve placeholders exactly. For example, `{count}` in:

   ```json
   "leftovers-selected-days": "{count} days selected"
   ```

   must remain `{count}` in the translated value.
5. Validate the locale set:

   ```bash
   python3 scripts/validate-locales.py
   ```

6. Open a Pull Request. GitHub's **New translation / translation fix** issue template can be used first if wording needs discussion.

## Template file

`locales/TEMPLATE.json` is intentionally valid, comment-free JSON so it can be copied directly. Its English values are reference text; the keys are the contract used by the patcher.

Do not add `_comment`, metadata, translator names, or other extra keys to locale JSON files. The validator expects every bundled locale to contain exactly the same feature keys as the fallback locale.

## Bundled locales

The initial release includes:

- `da-DK` — Danish, default
- `en-US` — English, fallback
- `en-GB` — British English

The default and fallback locales are configured in `config/default.json`.
