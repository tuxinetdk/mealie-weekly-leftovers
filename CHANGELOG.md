# Changelog

## Unreleased - Rester7 / Mealie v3.29.0

- Added Rester7 patch compatibility for Mealie v3.29.0.
- Preserved recipe scaling when creating and editing meal plan entries.
- Excluded leftovers from day-level and bulk shopping-list additions.
- Preserved legacy Mealie patch compatibility.
- Extended GitHub Actions compatibility matrix to Mealie v3.29.0.
- No changes to production installations.

## 1.1.0

- Added Mealie v3.24.0 compatibility for the refactored Meal Planner entry dialog.
- Added structural patch dispatch for Mealie v3.23.x and v3.24+ layouts.
- Added Yarn/pnpm auto-detection for Fast Build.
- Added automatic Fast Build → Full Build fallback while production stays online.
- Added persistent candidate build logs and detailed build-failure stages.
- Fixed Discord messages that displayed literal `\n` instead of line breaks.
- CI now validates and compiles the patch against Mealie v3.23.1 and v3.24.0.
- Added a non-destructive `scripts/upgrade.sh` for existing installations.
- Increased automatic update service timeout to 60 minutes for Full Build fallback.

## 1.0.0

- Weekly Leftovers mode in Meal Planner.
- Select multiple earlier source days.
- "Select the whole week" shortcut.
- Optional note.
- One special no-ingredient recipe for leftovers.
- Exclusion from bulk shopping-list addition.
- Danish and English translations as external JSON files.
- Translation template and validator.
- Fast frontend-overlay Docker builds.
- Automatic stable Mealie release checks.
- Verified backup, health check, diagnostics, and rollback.
- Legacy compatibility with early TuxiNet Rester metadata.

## v1.0.0

- Added GitHub Issue Forms for bug reports, feature requests, and translations.
- Added Pull Request template with validation, translation, compatibility, and safety checks.
- Expanded translation contribution documentation while keeping `locales/TEMPLATE.json` directly copyable.
