## Summary

Describe what this pull request changes and why.

## Type of change

- [ ] Bug fix
- [ ] Feature
- [ ] Translation
- [ ] Documentation
- [ ] Build / Update Guard
- [ ] Refactor / maintenance

## Testing

Describe how the change was tested.

- [ ] `python3 scripts/validate-locales.py` passes
- [ ] Python files compile
- [ ] Shell scripts pass `bash -n`
- [ ] Patch `--check` passes against the supported Mealie version
- [ ] Patch `--apply` succeeds against the supported Mealie version
- [ ] Docker build tested, when applicable

## Translation changes

If this PR changes locale files:

- [ ] I started from `locales/TEMPLATE.json`
- [ ] I preserved placeholders such as `{count}`
- [ ] The locale filename matches a locale shipped by Mealie

## Safety

- [ ] No passwords, API keys, tokens, webhook URLs, or private data are included
- [ ] Existing Weekly Leftovers metadata remains backward compatible, or the migration is documented
