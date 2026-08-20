# Contributing

Contributions are welcome.

## Translations

The easiest contribution is a locale file:

1. copy `locales/TEMPLATE.json`;
2. name it after a locale already supported by Mealie;
3. translate values only;
4. run `python3 scripts/validate-locales.py`.

## Code changes

Before opening a pull request run:

```bash
python3 -m py_compile patch/apply_patch.py scripts/validate-locales.py
bash -n scripts/install.sh
bash -n scripts/mealie-update-guard.sh
python3 scripts/validate-locales.py
```

The CI workflow also validates patch compatibility against the currently supported Mealie version.
