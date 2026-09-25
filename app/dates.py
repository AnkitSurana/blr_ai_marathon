"""
Deterministic date extraction for chat questions. Standard library only, no model.

    parse_dates("how many orders in the last 3 months?", today=date(2018, 9, 1))
    -> DateResult(status='resolved', start=2018-06-01, end=2018-08-31, rule='rolling', ...)

Every interpretation is an explicit POLICY (see POLICIES) rather than a guess, so the same phrase always gives the
same range. Where a phrase is genuinely ambiguous (03/04/2018) the policy is applied AND flagged. Where it contains a
time cue the rules do not understand ("around Black Friday", "recently"), the status is 'unresolved' and the caller
hands just that slot to an LLM (and validates what comes back).
Well-established temporal taggers exist (SUTime, HeidelTime, dateparser, chrono, Duckling); this is a small, readable
rule set for the demo.
"""
import calendar
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

POLICIES = {
    "today": "supplied by the caller (never read from the model)",
    "last N days": "the N complete days before today",
    "last N weeks/months/quarters/years": "the N complete ISO weeks / calendar months / quarters / years before the current one",
    "this month/quarter/year": "the whole current calendar period, including days not yet happened",
    "year/month to date": "period start through today",
    "month or quarter without a year": "the most recent one that has already started",
    "since X": "start of X through today",
    "until X": "everything up to the end of X (open start)",
    "numeric a/b/yyyy": "day/month/year when both parts are 12 or less (locale rule), flagged as ambiguous",
}

MONTHS = {"jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3, "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6,
          "jul": 7, "july": 7, "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10, "october": 10,
          "nov": 11, "november": 11, "dec": 12, "december": 12}
MON = "(?:" + "|".join(sorted(MONTHS, key=len, reverse=True)) + ")"
ORD = {"first": 1, "1st": 1, "second": 2, "2nd": 2, "third": 3, "3rd": 3, "fourth": 4, "4th": 4}
# words that show a time expression is present; if any are left after parsing, the slot is 'unresolved'
CUES = {"last", "past", "previous", "prior", "next", "ago", "recent", "recently", "lately", "season", "festive", "holiday", "holidays",
        "christmas", "xmas", "diwali", "easter", "thanksgiving", "friday", "summer", "winter", "spring", "autumn", "fall", "week", "weeks",
        "weekend", "month", "months", "year", "years", "quarter", "quarters", "day", "days", "today", "tonight", "earlier", "couple", "few",
        "several", "while", "yesterday", "tomorrow", "annual", "annually", "fiscal", "fy"}


@dataclass
class Span:
    a: int
    b: int
    text: str
    rule: str
    prio: int
    start: Optional[date]
    end: Optional[date]
    resolver: object = None          # callable(year) -> (start, end) for periods that were written without a year
    has_year: bool = True
    flags: list = field(default_factory=list)


@dataclass
class DateResult:
    status: str                       # 'none' | 'resolved' | 'unresolved'
    start: Optional[date] = None
    end: Optional[date] = None
    rule: str = ""
    evidence: str = ""
    flags: list = field(default_factory=list)
    leftover: list = field(default_factory=list)
    spans: list = field(default_factory=list)

    def iso(self):
        return (self.start.isoformat() if self.start else None, self.end.isoformat() if self.end else None)


# ---------- calendar helpers ----------
def month_range(y, m):
    return date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1])


def quarter_range(y, q):
    return date(y, 3 * q - 2, 1), month_range(y, 3 * q)[1]


def year_range(y):
    return date(y, 1, 1), date(y, 12, 31)


def add_months(y, m, k):
    n = y * 12 + (m - 1) + k
    return n // 12, n % 12 + 1


def year2(s):
    s = s.lstrip("'")
    return int(s) if len(s) == 4 else 2000 + int(s)


def valid(y, m, d):
    try:
        return date(y, m, d)
    except ValueError:
        return None


def parse_dates(text, today, day_first=True, ignore_words=()):
    t = text.lower().replace("’", "'").replace("‘", "'")
    spans = []

    def add(m, rule, prio, start, end, resolver=None, has_year=True, flags=None):
        spans.append(Span(m.start(), m.end(), text[m.start():m.end()], rule, prio, start, end, resolver, has_year, list(flags or [])))

    # ---- full dates ----
    for m in re.finditer(r"\b(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})\b", t):
        d = valid(int(m[1]), int(m[2]), int(m[3]))
        if d:
            add(m, "iso_date", 1, d, d)
    for m in re.finditer(r"\b(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})\b", t):
        a, b, y = int(m[1]), int(m[2]), int(m[3])
        flags = []
        if a > 12:                    # 24/11/2017
            d, mo = a, b
        elif b > 12:                  # 11/24/2017, month first, unambiguous because the day is above 12
            d, mo = b, a
        else:                         # 03/04/2018: both readings are valid, so apply the locale rule and flag it
            d, mo = (a, b) if day_first else (b, a)
            flags = ["ambiguous_numeric_date"]
        dd = valid(y, mo, d)
        if dd:
            add(m, "numeric_date", 1, dd, dd, flags=flags)
    for m in re.finditer(r"\b(?:the\s+)?(\d{1,2})(?:st|nd|rd|th)?(?:\s+of)?\s+(" + MON + r")\b\.?,?\s+(\d{4}|'\d{2})\b", t):
        d = valid(year2(m[3]), MONTHS[m[2]], int(m[1]))
        if d:
            add(m, "day_month_year", 1, d, d)
    for m in re.finditer(r"\b(" + MON + r")\b\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4}|'\d{2})\b", t):
        d = valid(year2(m[3]), MONTHS[m[1]], int(m[2]))
        if d:
            add(m, "month_day_year", 1, d, d)

    # ---- year-month ----
    for m in re.finditer(r"(?<![\d/.-])(\d{4})[-/](\d{1,2})(?![\d/.-])", t):
        if 1 <= int(m[2]) <= 12:
            s, e = month_range(int(m[1]), int(m[2]))
            add(m, "year_month", 2, s, e)
    for m in re.finditer(r"(?<![\d/.-])(\d{1,2})[-/](\d{4})(?![\d/.-])", t):
        if 1 <= int(m[1]) <= 12:
            s, e = month_range(int(m[2]), int(m[1]))
            add(m, "month_year_numeric", 2, s, e)
    for m in re.finditer(r"\b(" + MON + r")\b\.?[\s,'-]*(?:of\s+)?(\d{4}|'\d{2})\b", t):
        s, e = month_range(year2(m[2]), MONTHS[m[1]])
        add(m, "month_year", 2, s, e)
    for m in re.finditer(r"\b(" + MON + r")'(\d{2})\b", t):
        s, e = month_range(2000 + int(m[2]), MONTHS[m[1]])
        add(m, "month_year", 2, s, e)
    for m in re.finditer(r"\b(" + MON + r")\b(?!\s*[\d'])", t):
        prev = t[:m.start()].split()[-1:] or [""]
        if m[1] == "may" and prev[0] not in ("in", "of", "during", "for", "from", "to", "since", "until", "till", "and", "through", "between"):
            continue                  # "may" is only a month after a preposition
        mo = MONTHS[m[1]]
        y = today.year if date(today.year, mo, 1) <= today else today.year - 1

        def res(year=None, mo=mo, y=y):
            return month_range(year if year else y, mo)
        s_, e_ = res()
        add(m, "month_only", 4, s_, e_, resolver=res, has_year=False, flags=["no_year_assumed"])

    # ---- quarters and halves ----
    def qres(q, y=None):
        def res(year=None):
            yy = year if year else (y if y else (today.year if quarter_range(today.year, q)[0] <= today else today.year - 1))
            return quarter_range(yy, q)
        return res
    for m in re.finditer(r"\bq([1-4])\b[\s'-]*(?:of\s+)?(\d{4}|\d{2}\b)?", t):
        y = year2(m[2]) if m[2] else None
        r = qres(int(m[1]), y)
        s, e = r()
        add(m, "quarter", 2 if y else 4, s, e, resolver=r, has_year=bool(y), flags=[] if y else ["no_year_assumed"])
    for m in re.finditer(r"\b(20\d{2})[\s-]+q([1-4])\b", t):
        s, e = quarter_range(int(m[1]), int(m[2]))
        add(m, "quarter", 2, s, e)
    for m in re.finditer(r"\b(first|1st|second|2nd|third|3rd|fourth|4th)\s+quarter\b(?:\s+of)?\s*(\d{4})?", t):
        y = int(m[2]) if m[2] else None
        r = qres(ORD[m[1]], y)
        s, e = r()
        add(m, "quarter", 2 if y else 4, s, e, resolver=r, has_year=bool(y), flags=[] if y else ["no_year_assumed"])
    for m in re.finditer(r"\bquarter\s+([1-4])\b(?:\s+of)?\s*(\d{4})?", t):
        y = int(m[2]) if m[2] else None
        r = qres(int(m[1]), y)
        s, e = r()
        add(m, "quarter", 2 if y else 4, s, e, resolver=r, has_year=bool(y), flags=[] if y else ["no_year_assumed"])
    for m in re.finditer(r"\b(?:h([12])|(first|second)\s+half(?:\s+of)?)\s*'?(\d{4}|\d{2}\b)?", t):
        h = int(m[1]) if m[1] else (1 if m[2] == "first" else 2)
        if not m[3]:
            continue
        y = year2(m[3])
        add(m, "half_year", 2, date(y, 1 if h == 1 else 7, 1), date(y, 6, 30) if h == 1 else date(y, 12, 31))

    # ---- relative and rolling ----
    cur_q = (today.month - 1) // 3 + 1
    week0 = today - timedelta(days=today.weekday())
    fixed = [
        (r"\btoday\b", lambda: (today, today)), (r"\byesterday\b", lambda: (today - timedelta(days=1),) * 2),
        (r"\bthis week\b", lambda: (week0, week0 + timedelta(days=6))),
        (r"\b(?:last|previous|prior) week\b", lambda: (week0 - timedelta(days=7), week0 - timedelta(days=1))),
        (r"\bthis month\b", lambda: month_range(today.year, today.month)),
        (r"\b(?:last|previous|prior) (?:calendar )?month\b", lambda: month_range(*add_months(today.year, today.month, -1))),
        (r"\bthis quarter\b", lambda: quarter_range(today.year, cur_q)),
        (r"\b(?:last|previous|prior) quarter\b", lambda: quarter_range(today.year, cur_q - 1) if cur_q > 1 else quarter_range(today.year - 1, 4)),
        (r"\bthis (?:calendar )?year\b(?! so far)", lambda: year_range(today.year)),
        (r"\b(?:last|previous|prior) (?:calendar )?year\b", lambda: year_range(today.year - 1)),
        (r"\b(?:year[- ]to[- ]date|ytd|so far this year|this year so far)\b", lambda: (date(today.year, 1, 1), today)),
        (r"\b(?:month[- ]to[- ]date|mtd|so far this month)\b", lambda: (date(today.year, today.month, 1), today)),
    ]
    for pat, fn in fixed:
        for m in re.finditer(pat, t):
            s, e = fn()
            add(m, "relative", 3, s, e)
    for m in re.finditer(r"\b(?:last|past|previous)\s+(\d{1,3})\s+(day|week|month|quarter|year)s?\b", t):
        n, unit = int(m[1]), m[2]
        if n < 1:
            continue
        if unit == "day":
            s, e = today - timedelta(days=n), today - timedelta(days=1)
        elif unit == "week":
            s, e = week0 - timedelta(days=7 * n), week0 - timedelta(days=1)
        elif unit == "month":
            y0, m0 = add_months(today.year, today.month, -n)
            s, e = date(y0, m0, 1), month_range(*add_months(today.year, today.month, -1))[1]
        elif unit == "quarter":
            qi = today.year * 4 + (cur_q - 1) - n
            s, e = quarter_range(qi // 4, qi % 4 + 1)[0], (quarter_range(today.year, cur_q - 1)[1] if cur_q > 1 else quarter_range(today.year - 1, 4)[1])
        else:
            s, e = date(today.year - n, 1, 1), date(today.year - 1, 12, 31)
        add(m, "rolling", 3, s, e)
    for m in re.finditer(r"\b(?:the\s+)?(?:whole|entire)\s+(?:of\s+)?(\d{4})\b|\b(?:calendar\s+)?year\s+(\d{4})\b", t):
        y = int(m[1] or m[2])
        s, e = year_range(y)
        add(m, "year", 2, s, e)
    for m in re.finditer(r"(?<![\d/.:-])\b(19\d{2}|20\d{2})\b(?![\d/.-]\d)", t):
        s, e = year_range(int(m[1]))
        add(m, "year", 5, s, e)

    # ---- resolve overlaps: longest span wins, then the more specific rule ----
    spans.sort(key=lambda s: (-(s.b - s.a), s.prio))
    kept = []
    for s in spans:
        if all(s.b <= k.a or s.a >= k.b for k in kept):
            kept.append(s)
    kept.sort(key=lambda s: s.a)

    # ---- ranges: "X to Y", "from X to Y", "between X and Y", "X - Y" ----
    merged, i = [], 0
    while i < len(kept):
        s = kept[i]
        if i + 1 < len(kept):
            n = kept[i + 1]
            gap, before = t[s.b:n.a], t[:s.a]
            between = re.search(r"\bbetween\s*$", before) is not None
            conn = re.fullmatch(r"\s*(?:to|through|thru|until|till|-)\s*", gap) or (between and re.fullmatch(r"\s*and\s*", gap))
            if conn:
                s0, e0 = s.start, s.end
                if s.resolver and not s.has_year and n.has_year and n.start:
                    s0, e0 = s.resolver(n.start.year)
                s1, e1 = n.start, n.end
                if n.resolver and not n.has_year and s.has_year and s.start:
                    s1, e1 = n.resolver(s.start.year)
                lead = re.search(r"\b(?:from|between)\s*$", before)
                a = lead.start() if lead else s.a
                merged.append(Span(a, n.b, text[a:n.b], "range", 0, s0, e1, flags=sorted(set(s.flags + n.flags) - {"no_year_assumed"} if s.has_year or n.has_year else set(s.flags + n.flags))))
                i += 2
                continue
        merged.append(s)
        i += 1

    # ---- open bounds: since / until ----
    final = []
    for s in merged:
        before = t[:s.a]
        m1 = re.search(r"\b(?:since|starting(?:\s+from)?|beginning(?:\s+from)?|after)\s*$", before)
        m2 = re.search(r"\b(?:until|till|up\s+to|before|through|by)\s*$", before)
        if s.rule != "range" and m1 and s.rule not in ("relative", "rolling"):
            final.append(Span(m1.start(), s.b, text[m1.start():s.b], "since", 0, s.start, today, flags=s.flags))
        elif s.rule != "range" and m2 and s.rule not in ("relative", "rolling"):
            final.append(Span(m2.start(), s.b, text[m2.start():s.b], "until", 0, None, s.end, flags=s.flags))
        else:
            final.append(s)

    # ---- leftover time cues ----
    mask = list(text)
    for s in final:
        for k in range(s.a, s.b):
            mask[k] = " "
    rest = "".join(mask).lower()
    ign = {w.lower() for w in ignore_words}
    leftover = [w for w in re.findall(r"[a-z']+", rest) if w in CUES and w not in ign]
    if not final and not leftover:
        return DateResult("none")
    if len(final) > 1 or leftover or not final:
        return DateResult("unresolved", flags=["multiple_periods"] if len(final) > 1 else [], leftover=leftover, spans=final,
                          evidence=", ".join(s.text for s in final))
    s = final[0]
    return DateResult("resolved", s.start, s.end, s.rule, s.text, s.flags, [], final)
