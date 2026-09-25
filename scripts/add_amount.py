"""Add a named value band to canonical/amounts.json.

Usage:
    python3 -m scripts.add_amount "big orders"     price ">=" 500
    python3 -m scripts.add_amount "cheap items"    price "<"  20
    python3 -m scripts.add_amount "heavy shipping" freight_value ">=" 30

Column must be `price` or `freight_value`. Op must be one of >, >=, <, <=, =, !=.
The engine adds this WHERE clause to any question that includes the phrase.
No LLM call  -  pure lookup."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CANONICAL = ROOT / "canonical" / "amounts.json"

ALLOWED_COLS = {"price", "freight_value"}
ALLOWED_OPS = {">", ">=", "<", "<=", "=", "!="}


def main():
    ap = argparse.ArgumentParser(description="Add a named value band to canonical/amounts.json")
    ap.add_argument("phrase", help="What the seller says (e.g. 'big orders')")
    ap.add_argument("column", help=f"Column to filter  -  one of {sorted(ALLOWED_COLS)}")
    ap.add_argument("op", help=f"Operator  -  one of {sorted(ALLOWED_OPS)}")
    ap.add_argument("value", type=float, help="Threshold value (e.g. 500)")
    a = ap.parse_args()

    phrase = a.phrase.strip().lower()
    if not phrase:
        print("error: phrase is empty", file=sys.stderr); sys.exit(1)
    if a.column not in ALLOWED_COLS:
        print(f"error: column must be one of {sorted(ALLOWED_COLS)}", file=sys.stderr); sys.exit(1)
    if a.op not in ALLOWED_OPS:
        print(f"error: op must be one of {sorted(ALLOWED_OPS)}", file=sys.stderr); sys.exit(1)

    data = {}
    if CANONICAL.exists():
        with open(CANONICAL) as f:
            data = json.load(f)
    spec = {"column": a.column, "op": a.op, "value": int(a.value) if a.value.is_integer() else a.value}
    was = data.get(phrase)
    data[phrase] = spec

    ordered = {k: data[k] for k in data if k.startswith("_")}
    for k in sorted(k for k in data if not k.startswith("_")):
        ordered[k] = data[k]

    with open(CANONICAL, "w") as f:
        json.dump(ordered, f, indent=2, ensure_ascii=False)
        f.write("\n")

    if was:
        print(f"updated: '{phrase}' {was} → {spec}")
    else:
        print(f"added:   '{phrase}' → {a.column} {a.op} {spec['value']}")
    print(f"         ({CANONICAL.relative_to(ROOT)}). Restart the app to pick up the change.")


if __name__ == "__main__":
    main()
