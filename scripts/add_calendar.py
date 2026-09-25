"""Add a named business period to canonical/calendar.json.

Usage:
    python3 -m scripts.add_calendar "spring sale" 03-15 03-22
    python3 -m scripts.add_calendar "holiday season" 12-19 01-05    # wraps year boundary

The window is inclusive. Years are inferred from the question at query time (see canonical/calendar.json)."""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CANONICAL = ROOT / "canonical" / "calendar.json"


def check_mmdd(s, name):
    if not re.fullmatch(r"\d{2}-\d{2}", s):
        print(f"error: {name} must be 'MM-DD' (zero-padded). got: {s!r}", file=sys.stderr)
        sys.exit(1)
    m, d = int(s[:2]), int(s[3:])
    if not (1 <= m <= 12 and 1 <= d <= 31):
        print(f"error: {name}={s!r} is not a real date", file=sys.stderr)
        sys.exit(1)


def main():
    ap = argparse.ArgumentParser(description="Add a named business period to canonical/calendar.json")
    ap.add_argument("phrase", help="Named period as sellers type it (e.g. 'spring sale')")
    ap.add_argument("start", help="Start MM-DD (e.g. '03-15')")
    ap.add_argument("end", help="End MM-DD (e.g. '03-22'); may wrap year boundary")
    a = ap.parse_args()

    phrase = a.phrase.strip().lower()
    if not phrase:
        print("error: phrase is empty", file=sys.stderr)
        sys.exit(1)
    check_mmdd(a.start, "start")
    check_mmdd(a.end, "end")
    window = f"{a.start}..{a.end}"

    data = {}
    if CANONICAL.exists():
        with open(CANONICAL) as f:
            data = json.load(f)
    if phrase in data and data[phrase] == window:
        print(f"already present: '{phrase}' → {window}")
        return
    replaced = data.get(phrase)
    data[phrase] = window

    ordered = {k: data[k] for k in data if k.startswith("_")}
    for k in sorted(k for k in data if not k.startswith("_")):
        ordered[k] = data[k]

    with open(CANONICAL, "w") as f:
        json.dump(ordered, f, indent=2, ensure_ascii=False)
        f.write("\n")

    if replaced:
        print(f"updated: '{phrase}' {replaced} → {window}")
    else:
        print(f"added:   '{phrase}' → {window}")
    print(f"         ({CANONICAL.relative_to(ROOT)}). Restart the app to pick up the change.")


if __name__ == "__main__":
    main()
