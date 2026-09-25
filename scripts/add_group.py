"""Add a named group to canonical/groups.json.

A group is one word ("electronics") that expands to many categories
("computers", "computers_accessories", "telephony", ...).

Usage:
    python3 -m scripts.add_group "electronics" computers computers_accessories telephony
    python3 -m scripts.add_group "beauty" health_beauty perfumery

Every member must be a real category_english (see `python3 -m scripts.show_canonical --list-categories`)."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CANONICAL = ROOT / "canonical" / "groups.json"


def load_categories():
    with open(ROOT / "canonical" / "vocabulary.json") as f:
        return set(json.load(f))


def main():
    ap = argparse.ArgumentParser(description="Add a named group to canonical/groups.json")
    ap.add_argument("name", help="Group name (e.g. 'electronics')")
    ap.add_argument("members", nargs="+", help="One or more category_english values")
    a = ap.parse_args()

    name = a.name.strip().lower()
    if not name:
        print("error: group name is empty", file=sys.stderr); sys.exit(1)
    known = load_categories()
    unknown = [m for m in a.members if m not in known]
    if unknown:
        print(f"error: unknown categories: {unknown}", file=sys.stderr)
        print(f"       run: python3 -m scripts.show_canonical --list-categories", file=sys.stderr)
        sys.exit(1)

    data = {}
    if CANONICAL.exists():
        with open(CANONICAL) as f:
            data = json.load(f)
    existing = data.get(name, [])
    if not isinstance(existing, list):
        print(f"error: canonical/groups.json[{name}] is not a list", file=sys.stderr); sys.exit(1)
    added = []
    for m in a.members:
        if m not in existing:
            existing.append(m); added.append(m)
    existing.sort()
    data[name] = existing

    ordered = {k: data[k] for k in data if k.startswith("_")}
    for k in sorted(k for k in data if not k.startswith("_")):
        ordered[k] = data[k]

    with open(CANONICAL, "w") as f:
        json.dump(ordered, f, indent=2, ensure_ascii=False)
        f.write("\n")

    if added:
        print(f"added to '{name}': {', '.join(added)}")
    else:
        print(f"no change (all members already in '{name}')")
    print(f"         ({CANONICAL.relative_to(ROOT)}). Restart the app to pick up the change.")


if __name__ == "__main__":
    main()
