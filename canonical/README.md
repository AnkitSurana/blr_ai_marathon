# The canonical layer

Five JSON files. This is where you customize the whole starter kit **without editing Python**.

> 💡 **For interactive audience exercises, see the [Hands-On Guide](../HANDS_ON.md).**

## Overview

```
canonical/
├── vocabulary.json    ← phrase → single category (aliases)
├── groups.json        ← one word → many categories
├── calendar.json      ← phrase → date window (MM-DD..MM-DD)
├── amounts.json       ← phrase → WHERE fragment ({column, op, value})
└── unsupported.json   ← scope_words / scope_phrases for refusals
```

Each file is optional. Missing files are skipped; the base rules still work.

## Files with `_` keys

Any top-level key starting with `_` (like `_readme` or `_docs`) is **ignored by the engine**. Use those to keep documentation and examples inside the file itself.

## Editing workflow

1. Edit a JSON file (or use `python3 -m scripts.add_*`).
2. Restart the app (`Ctrl-C` and re-run `python3 -m app.main`).
3. The startup banner shows how many entries loaded.
4. Verify with `python3 -m scripts.ask "your question here"`.

## The 71 Olist categories

For `vocabulary.json` (single category) and `groups.json` (list of categories), keys/values must be real `category_english` values:

```bash
python3 -m scripts.show_canonical --list-categories
```

Common ones:

```
health_beauty                perfumery
sports_leisure               fashion_bags_accessories
housewares                   home_appliances
furniture_decor              bed_bath_table
pet_shop                     baby
toys                         computers_accessories
```

## Merge order

For each rule type, the engine applies:

1. **Base** (shipped in `app/`)
2. **Canonical** (`canonical/*.json`  -  you own this)
3. **Runtime overrides** (`data/*_overrides.json`  -  reviewer UI writes here)

Higher levels ADD; a base entry never disappears because you added a canonical one.

## Validation

- **Vocabulary**: keys must be real categories; unknown categories are silently skipped.
- **Groups**: same  -  unknown categories are silently skipped.
- **Calendar**: value must match `MM-DD..MM-DD`.
- **Amounts**: `column` must be one of {`price`, `freight_value`}; `op` must be one of {`>`, `>=`, `<`, `<=`, `=`, `!=`}; `value` must be numeric. Invalid entries are silently skipped (see `engine._validate_amount`).
- **Unsupported**: keys must be `scope_words` (array) or `scope_phrases` (array).

## Testing your changes

Run the dedicated canonical customization test suite:

```bash
python3 -m unittest tests.test_canonical -v
```

This verifies that all 5 JSON configuration files (`vocabulary.json`, `groups.json`, `calendar.json`, `amounts.json`, and `unsupported.json`) load and take effect deterministically without code modifications.
