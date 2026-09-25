"""Add a phrase → category alias to canonical/vocabulary.json.

Usage:
    python3 -m scripts.add_vocab health_beauty "cosmetics"
    python3 -m scripts.add_vocab pet_shop "puppy chow"

The category must be a real Olist category_english (see `python3 -m scripts.show_canonical --list-categories`).
Duplicates are silently skipped. The file is written back with sorted keys and stable formatting."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
CANONICAL = ROOT / "canonical" / "vocabulary.json"


def load_base_categories():
    with open(CANONICAL) as f:
        return set(json.load(f))


def main():
    ap = argparse.ArgumentParser(description="Add a phrase → category alias to canonical/vocabulary.json")
    ap.add_argument("category", help="Olist category_english value (e.g. 'health_beauty')")
    ap.add_argument("phrase", help="Natural-language phrase to add (e.g. 'lipstick')")
    a = ap.parse_args()

    cat = a.category.strip().lower()
    phrase = a.phrase.strip().lower()

    known = load_base_categories()
    if cat not in known:
        print(f"error: '{cat}' is not a category in the base vocab.", file=sys.stderr)
        print(f"       run: python3 -m scripts.show_canonical --list-categories", file=sys.stderr)
        sys.exit(1)
    if not phrase:
        print("error: phrase is empty", file=sys.stderr)
        sys.exit(1)

    data = {}
    if CANONICAL.exists():
        with open(CANONICAL) as f:
            data = json.load(f)
    aliases = data.setdefault(cat, [])
    if not isinstance(aliases, list):
        print(f"error: canonical/vocabulary.json[{cat}] is not a list", file=sys.stderr)
        sys.exit(1)
    if phrase in aliases:
        print(f"already present: {cat} ← \"{phrase}\"")
        return
    aliases.append(phrase)
    aliases.sort()

    # Preserve `_readme` / `_docs` at the top, then sorted category keys.
    ordered = {k: data[k] for k in data if k.startswith("_")}
    for k in sorted(k for k in data if not k.startswith("_")):
        ordered[k] = data[k]

    with open(CANONICAL, "w") as f:
        json.dump(ordered, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"added: {cat} ← \"{phrase}\"")
    print(f"       ({CANONICAL.relative_to(ROOT)}). Restart the app to pick up the change.")


if __name__ == "__main__":
    main()
