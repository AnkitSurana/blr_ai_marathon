"""Show what's currently in your canonical layer, plus (optionally) the base categories you can extend.

    python3 -m scripts.show_canonical                    # everything you've added
    python3 -m scripts.show_canonical --list-categories  # the 71 Olist categories
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CANONICAL = ROOT / "canonical"
BASE_VOCAB = ROOT / "canonical" / "vocabulary.json"


def load_json(p):
    if not p.exists():
        return {}
    with open(p) as f:
        return json.load(f)


def strip_meta(d):
    return {k: v for k, v in d.items() if not k.startswith("_")}


def main():
    ap = argparse.ArgumentParser(description="Show your canonical additions.")
    ap.add_argument("--list-categories", action="store_true",
                    help="Print the 71 Olist category_english values you can extend.")
    a = ap.parse_args()

    if a.list_categories:
        base = strip_meta(load_json(BASE_VOCAB))
        for c in sorted(base):
            aliases = base[c] if isinstance(base[c], list) else base[c].get("aliases", [])
            print(f"  {c:44s}  {len(aliases):>3} base aliases")
        print(f"\n{len(base)} categories total.")
        return

    vocab = strip_meta(load_json(CANONICAL / "vocabulary.json"))
    calendar = strip_meta(load_json(CANONICAL / "calendar.json"))
    groups = strip_meta(load_json(CANONICAL / "groups.json"))
    amounts = strip_meta(load_json(CANONICAL / "amounts.json"))
    scope = strip_meta(load_json(CANONICAL / "unsupported.json"))

    print("=" * 68)
    print("  YOUR CANONICAL ADDITIONS")
    print("=" * 68)

    print("\n[vocabulary]  -  phrase → single category")
    if not vocab:
        print("  (empty  -  edit canonical/vocabulary.json)")
    else:
        for cat, aliases in sorted(vocab.items()):
            print(f"  {cat}")
            for a_ in aliases:
                print(f"     └─ \"{a_}\"")

    print("\n[groups]  -  one word → many categories")
    if not groups:
        print("  (empty  -  edit canonical/groups.json)")
    else:
        for name, members in sorted(groups.items()):
            print(f"  \"{name}\"  →  {len(members)} categor{'y' if len(members)==1 else 'ies'}: {', '.join(members)}")

    print("\n[calendar]  -  named business periods")
    if not calendar:
        print("  (empty  -  edit canonical/calendar.json)")
    else:
        for phrase, window in sorted(calendar.items()):
            print(f"  \"{phrase}\"  →  {window}")

    print("\n[amounts]  -  named value bands (added to WHERE)")
    if not amounts:
        print("  (empty  -  edit canonical/amounts.json)")
    else:
        for phrase, spec in sorted(amounts.items()):
            print(f"  \"{phrase}\"  →  {spec.get('column')} {spec.get('op')} {spec.get('value')}")

    print("\n[scope refusals]")
    scope_words = scope.get("scope_words", [])
    scope_phrases = scope.get("scope_phrases", [])
    if not scope_words and not scope_phrases:
        print("  (empty  -  edit canonical/unsupported.json)")
    else:
        for w in sorted(scope_words):
            print(f"  word:    {w}")
        for p in sorted(scope_phrases):
            print(f"  phrase:  \"{p}\"")

    print()


if __name__ == "__main__":
    main()
