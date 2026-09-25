"""
Deterministic extraction of the four things a question needs: INTENT, METRIC, CATEGORY, DATE. Standard library only.
Anything the rules can extract is extracted here, so a model is never asked to. Anything they can't is marked
'unresolved' with the exact words responsible, so the model (if used at all) is asked about that gap and nothing else.
"""
import json
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from . import matcher as gm
from .config import CONFIG
from .dates import CUES, parse_dates

PKG = Path(__file__).resolve().parent

FILLER = set("""i my me mine we our you your please tell show give list what whats what's was were is are am do does did doing done get got make made much many
how of for in on at by from to the a an and or with per each every all total number count overall currently now so far sell sold selling sale
than then that this these those it its as be been being can could would should will shall may might have has had into out up over under between
during since until till about around approximately roughly any some there here also just only which who where when whom whose
compare compared compares comparing comparison vs versus against yoy y/y mom m/m""".split())
METRIC = {"revenue": {"revenue", "sales", "earnings", "earned", "earn", "income", "turnover", "money", "gmv"},
          "orders": {"orders", "order", "purchases", "purchase"},
          "items": {"items", "item", "units", "unit", "pieces", "piece"}}
METRIC_PHRASES = [("brought in", "revenue"), ("bring in", "revenue"), ("order count", "orders")]
INTENT_WORDS = {"top", "best", "selling", "popular", "highest", "leading", "categories", "category", "monthly", "month", "months", "wise", "by",
                # List-intent words: the seller asks for individual records instead of a summary aggregate.
                "show", "list", "give", "find", "pull", "record", "records", "row", "rows",
                # Daily roll-up.
                "daily",
                # Referential words used in follow-ups. Consumed here so they do not leak into category matching.
                "those", "them", "these", "same", "one", "ones", "recent"}
UNSUPPORTED = {"why", "growth", "growing", "grow", "grew", "trend", "trending", "drop", "dropped", "decline", "declined",
               "increase", "increased", "reduce", "reduced", "decrease", "decreased", "lower", "lowered", "fall", "fell", "gained", "gaining",
               "average", "avg", "mean", "median", "rate", "ratio", "share", "percentage", "percent", "margin", "profit",
               "customer", "customers", "cancel", "cancellation", "cancelled", "canceled", "expensive", "cheapest", "should",
               "ignore", "instead", "forecast", "predict", "delete", "remove", "update", "insert", "stock", "more"}
# Words that describe a change over time.
CHANGE_WORDS = {"why", "drop", "dropped", "decline", "declined", "reduce", "reduced", "decrease", "decreased",
                "lower", "lowered", "fall", "fell", "grow", "grew", "growing", "growth",
                "increase", "increased", "gained", "gaining", "trend", "trending"}
UNSUPPORTED_PHRASES = ["more than"]

# Security policy rules for multi-tenant isolation and write protection.
POLICY_WORDS = {"peers", "everyone", "ignore", "delete", "remove", "update", "insert", "merchants", "competitors"}
POLICY_PHRASES = ["all sellers", "every seller", "other sellers", "another seller", "not just mine",
                  "all merchants", "every merchant", "other merchants", "another merchant",
                  "all stores", "other stores", "all accounts", "platform total", "across all",
                  "ignore my login", "ignore my session",
                  # Cross-tenant comparison phrases:
                  "compared to other", "compare to other", "compared with other", "compare with other",
                  "vs other sellers", "versus other sellers", "against other sellers",
                  "compare with peers", "compare to peers", "compared to peers", "how do i compare"]

# Markers that indicate the seller is asking to compare TIME PERIODS of their own data.
# When any of these appears alongside a resolved date, the router treats it as `compare_periods` intent  -  two
# Route A queries whose numbers are shown side by side.
COMPARE_PHRASES = ["compared to", "compared with", "compare to", "compare with",
                   " vs ", " versus ", " against ",
                   "year over year", "year-over-year", "y/y",
                   "month over month", "month-over-month", "m/m",
                   "yoy", "mom"]


def compare_hit(low):
    """Return the marker string if a period-comparison intent is present, else empty string."""
    for p in COMPARE_PHRASES:
        if p in " " + low + " ":
            return p.strip()
    return ""


def policy_hit(low):
    """Return the list of policy words/phrases in a lowercased question, or an empty list. A hit means REFUSE."""
    phrases = [p for p in POLICY_PHRASES if p in low]
    words = sorted({w for w in re.findall(r"[a-z']+", low) if w in POLICY_WORDS})
    
    # Check for cross-tenant seller references while allowing product-ranking phrases like "best seller" / "best sellers"
    for m in re.finditer(r"\b(seller|sellers)\b", low):
        # Look behind to see if preceded by "best" or "top"
        start = m.start()
        prefix = low[:start].rstrip()
        if not (prefix.endswith("best") or prefix.endswith("top") or prefix.endswith("best-") or prefix.endswith("top-")):
            words.append(m.group(1))
            break
            
    return phrases + sorted(set(words))



@dataclass
class Slot:
    status: str                      # 'resolved' | 'default' | 'assumed' | 'unresolved'
    value: object = None
    evidence: str = ""
    rule: str = ""
    flags: list = field(default_factory=list)
    words: list = field(default_factory=list)   # the words that could not be explained (for unresolved slots)


@dataclass
class Extraction:
    question: str
    unsupported: list
    intent: Slot
    metric: Slot
    category: Slot
    date: Slot
    topn: int = 5
    residual: list = field(default_factory=list)
    compare: str = ""   # non-empty if the seller wants a period-comparison (own-data year/month/quarter over year)
    amount: dict = field(default_factory=dict)   # {"phrase", "column", "op", "value"} if a canonical amount phrase matched

    @property
    def slots(self):
        return {"intent": self.intent, "metric": self.metric, "category": self.category, "date": self.date}


def load_groups(path=None):
    target = Path(path) if path else (PKG.parent / "canonical" / "groups.json")
    if target.exists():
        return json.loads(target.read_text())
    return {}


def _entries(vocab, groups):
    out = []
    for cat, v in vocab.items():
        out.append(("category", cat, [cat] + list(v["aliases"]), [cat]))
    for name, members in groups.items():
        out.append(("group", name, [name], list(members)))
    return out


def _score(window, texts):
    best, via, cov, fz = 0.0, "", 0.0, []
    for t in texts:
        tt = gm.toks(t)
        s, c = gm.compare(window, tt)
        if s > best:
            best, via, cov, fz = s, t, c, gm.fuzzy_pairs(window, tt)
    return best, via, cov, fz


def cal_range(win, year, today):
    """Resolve a business-calendar entry to a (start, end) date pair. Two accepted shapes:
      - tuple/list (iso_start, iso_end): a FIXED dated window (e.g. 'black friday 2017' → ('2017-11-24','2017-11-27')).
        Used as-is regardless of `year`; ideal for holidays whose date shifts every year.
      - string 'MM-DD..MM-DD': a RECURRING window whose year is inferred from the question (via `year`) or,
        failing that, from `today` (the most recent occurrence that has already started).
    """
    if isinstance(win, (tuple, list)):
        s, e = win
        return date.fromisoformat(s), date.fromisoformat(e)
    (sm, sd), (em, ed) = [tuple(int(x) for x in part.split("-")) for part in win.split("..")]
    y = year or (today.year if date(today.year, sm, sd) <= today else today.year - 1)
    return date(y, sm, sd), date(y if (em, ed) >= (sm, sd) else y + 1, em, ed)


def metric_in(text):
    """The metric named in a short reply like 'revenue' or 'items sold', or None."""
    low = text.lower()
    kinds = {m for m, ws in METRIC.items() if any(w in ws for w in re.findall(r"[a-z]+", low))}
    return kinds.pop() if len(kinds) == 1 else None


def extract(question, vocab, groups, today, day_first=True, calendar=None, amounts=None):
    q = question.strip()
    low = q.lower().replace("’", "'")
    unsupported = sorted({w for w in re.findall(r"[a-z']+", low) if w in UNSUPPORTED}) + [p for p in UNSUPPORTED_PHRASES if p in low]
    # Amount phrases (canonical/amounts.json). Longest-match first so "premium products" wins over "products".
    # When a match hits, its span is masked out of the question BEFORE category matching so its words don't
    # end up in the residual/category slot.
    amount_hit = {}
    if amounts:
        for phrase in sorted(amounts, key=lambda p: -len(p)):
            i = low.find(phrase)
            if i >= 0:
                amount_hit = {"phrase": phrase, **amounts[phrase]}
                q = q[:i] + " " * len(phrase) + q[i + len(phrase):]
                low = q.lower().replace("’", "'")
                break

    # ---- intent (rules) ----
    # Five shapes, checked in order of specificity: top-N ranking, monthly roll-up, daily roll-up, individual-rows
    # listing, and (fallback) a single total. Each shape has its own SQL template downstream.
    intent, topn = "total", 5
    intent_rule = "default"
    if re.search(r"\b(top|best|best[- ]selling|most popular|highest|leading)\b", low) and re.search(r"\bcategor", low):
        intent, intent_rule = "top_categories", "top-N + categories"
        n = re.search(r"\b(?:top|best|leading)\s+(\d+)\b", low) or re.search(r"\b(\d+)\s+(?:top|best|leading|categories|most)\b", low)
        topn = int(n.group(1)) if n else 5
    elif re.search(r"\b(monthly|per month|by month|each month|every month|month[- ]by[- ]month|month[- ]wise)\b", low):
        intent, intent_rule = "by_month", "monthly roll-up keyword"
    elif re.search(r"\b(daily|per day|by day|each day|every day|day[- ]by[- ]day|day[- ]wise)\b", low):
        intent, intent_rule = "by_day", "daily roll-up keyword"
    elif (re.search(r"\b(show|list|give|find|pull)\b", low) and re.search(r"\b(order|orders|item|items|record|records|row|rows|purchase|purchases)\b", low)) \
            or re.search(r"\bwhich\s+(order|orders|item|items)\b", low):
        intent, intent_rule = "list_records", "list-verb + record noun"
    intent_slot = Slot("resolved", intent, evidence=intent_rule if intent != "total" else "default",
                       rule=intent_rule if intent != "total" else "default")

    # ---- date (rules) ----
    ign = {"month", "months", "monthly", "categories", "category", "top", "best"} if intent != "total" else set()
    cal_hit = None
    for phrase, win in sorted((calendar or {}).items(), key=lambda kv: -len(kv[0])):
        i = low.find(phrase.lower())
        if i >= 0:
            cal_hit = (phrase, win, i, i + len(phrase))
            break
    dr = parse_dates(q if not cal_hit else q[:cal_hit[2]] + " " * (cal_hit[3] - cal_hit[2]) + q[cal_hit[3]:], today, day_first, ignore_words=ign)
    cal_slot = None
    if cal_hit:
        phrase, win, ci, cj = cal_hit
        if dr.status == "none" or (dr.status == "resolved" and dr.rule == "year"):
            yr = dr.start.year if dr.status == "resolved" else None
            cal_slot = Slot("resolved", tuple(d.isoformat() for d in cal_range(win, yr, today)),
                            evidence=phrase + (f" {yr}" if yr else ""), rule="business calendar", flags=["approved_by_reviewer"])
    if cal_slot:
        date_slot = cal_slot
    elif dr.status == "resolved":
        date_slot = Slot("resolved", dr.iso(), evidence=dr.evidence, rule=dr.rule, flags=dr.flags)
    elif dr.status == "none":
        date_slot = Slot("default", (None, None), evidence="no date in the question", rule="all time")
    else:
        date_slot = Slot("unresolved", None, evidence=dr.evidence, rule="", flags=dr.flags, words=dr.leftover)

    # ---- word bookkeeping: what has been consumed, what is left over ----
    words = [(m.group(0), m.start(), m.end()) for m in re.finditer(r"[A-Za-z0-9$%]+(?:['’][A-Za-z]+)?", q)]
    consumed_chars = set()
    for s in dr.spans:
        consumed_chars.update(range(s.a, s.b))
    if cal_slot:
        consumed_chars.update(range(cal_hit[2], cal_hit[3]))
    text_low = low
    for ph, _m in METRIC_PHRASES:
        for mm in re.finditer(re.escape(ph), text_low):
            consumed_chars.update(range(mm.start(), mm.end()))

    def consumed(w):
        return w[1] in consumed_chars or w[0].lower() in FILLER or w[0].isdigit()

    # ---- metric (rules) ----
    found = []
    for ph, metric in METRIC_PHRASES:
        if ph in low:
            found.append((metric, ph))
    metric_words = set()
    for w in words:
        lw = w[0].lower()
        for metric, ws in METRIC.items():
            if lw in ws:
                found.append((metric, lw))
                metric_words.add(w[1])
    kinds = {m for m, _ in found}
    if len(kinds) == 1:
        metric_slot = Slot("resolved", kinds.pop(), evidence=found[0][1], rule="keyword")
    elif len(kinds) > 1 and "items" in kinds and "revenue" not in kinds:
        metric_slot = Slot("resolved", "items", evidence=", ".join(x for _, x in found), rule="keyword", flags=["several_metric_words"])
    elif len(kinds) > 1:
        metric_slot = Slot("unresolved", None, evidence=", ".join(x for _, x in found), words=[x for _, x in found])
    else:
        metric_slot = Slot("missing", None, evidence="the question doesn't say what to measure")

    # ---- category (rules over the words nothing else has explained) ----
    intent_word_idx = {w[1] for w in words if intent != "total" and w[0].lower() in INTENT_WORDS}
    content = [w for w in words if not consumed(w) and w[1] not in metric_words and w[1] not in intent_word_idx and w[0].lower() not in UNSUPPORTED]
    toks = [(w, gm.stem(w[0].lower().replace("'", ""))) for w in content]
    entries = _entries(vocab, groups)
    chosen, used = [], set()
    n = len(toks)
    cands = []
    for size in range(min(4, n), 0, -1):
        for i in range(0, n - size + 1):
            window = [t for _, t in toks[i:i + size]]
            best = None
            for kind, name, texts, members in entries:
                sc, via, cov, fz = _score(window, texts)
                if cov >= CONFIG.matcher.coverage_floor and sc >= CONFIG.matcher.accept_score and not fz and (best is None or sc > best[0] or (sc == best[0] and kind == "group")):
                    best = (sc, kind, name, via, members)
            if best:
                cands.append((size, best[0], i, size, best))
    cands.sort(key=lambda c: (-c[0], -c[1], c[2]))
    for size, sc, i, sz, best in cands:
        rng = set(range(i, i + sz))
        if rng & used:
            continue
        used |= rng
        chosen.append((i, sz, best))
    leftover = [toks[k][0][0] for k in range(n) if k not in used]
    # a category name can itself contain a time word ("christmas supplies"): those words are not date cues
    cat_words = {toks[k][0][0].lower() for k in used}
    if date_slot.status == "unresolved" and dr.leftover and len(dr.spans) <= 1 and all(w in cat_words for w in dr.leftover):
        date_slot = (Slot("resolved", dr.spans[0].start and (dr.spans[0].start.isoformat(), dr.spans[0].end.isoformat()) or (None, dr.spans[0].end.isoformat() if dr.spans[0].end else None),
                          evidence=dr.spans[0].text, rule=dr.spans[0].rule, flags=dr.spans[0].flags) if dr.spans else Slot("default", (None, None), evidence="no date in the question", rule="all time"))
    # residual words sitting in a run that contains a time cue belong to the DATE slot, not the category slot
    widx = {w[1]: k for k, w in enumerate(words)}
    left_pos = sorted(widx[w[1]] for w in [toks[k][0] for k in range(n) if k not in used])
    runs, cur = [], []
    for p_ in left_pos:
        if cur and p_ - cur[-1] > 1 and not all(words[j][0].lower() in FILLER for j in range(cur[-1] + 1, p_)):
            runs.append(cur)
            cur = []
        cur.append(p_)
    if cur:
        runs.append(cur)
    date_words, cat_left = [], []
    for run in runs:
        ws = [words[j][0] for j in run]
        (date_words if any(w.lower() in CUES for w in ws) else cat_left).extend(ws)
    if date_words and date_slot.status != "unresolved":
        date_slot = Slot("unresolved", None, evidence=" ".join(date_words), words=date_words)
    elif date_slot.status == "unresolved" and date_words:
        date_slot.words = date_words
    leftover = cat_left
    if not toks or (not chosen and not leftover):
        category_slot = Slot("default", [], evidence="no category in the question", rule="all categories")
    elif leftover:
        category_slot = Slot("unresolved", sorted({c for _, _, b in chosen for c in b[4]}) or None,
                             evidence=" ".join(w[0] for w, _ in toks), words=leftover)
    else:
        cats = sorted({c for _, _, b in chosen for c in b[4]})
        ev = "; ".join(f"{' '.join(toks[j][0][0] for j in range(i, i + sz))} → {b[2]}" + (f" (via “{b[3]}”)" if b[3] != b[2] else "") for i, sz, b in sorted(chosen))
        category_slot = Slot("resolved", cats, evidence=ev, rule="group" if any(b[1] == "group" for _, _, b in chosen) else "vocabulary",
                             flags=["group"] if any(b[1] == "group" for _, _, b in chosen) else [])
    residual = leftover
    ex_out = Extraction(q, unsupported, intent_slot, metric_slot, category_slot, date_slot, topn, residual)
    if amount_hit:
        ex_out.amount = amount_hit
    # Compare-periods intent is detected AFTER the primary extraction. It rides alongside the base intent
    # (`total` becomes `total` on two windows)  -  the router uses it to pick Route A×2 instead of Route A.
    ex_out.compare = compare_hit(low)
    # Metric defaults  -  applied HERE (not in route()) so the trace pane shows the resolved metric with the reason,
    # instead of showing "the question doesn't say" and then quietly defaulting in the router.
    if ex_out.metric.status == "missing" and ex_out.intent.value in ("list_records", "by_day"):
        ex_out.metric.status = "resolved"
        ex_out.metric.value = "orders"
        ex_out.metric.evidence = f"defaulted for {ex_out.intent.value} (lists rows, not a metric)"
        ex_out.metric.rule = "intent_default"
    if ex_out.metric.status == "missing" and ex_out.amount:
        ex_out.metric.status = "resolved"
        ex_out.metric.value = "orders"
        ex_out.metric.evidence = f"defaulted from amount phrase “{ex_out.amount['phrase']}”"
        ex_out.metric.rule = "amount_default"
    return ex_out


def route(ex):
    """A: everything extracted by rules. B: rules got the shape, a model fills only the gap. C: nothing usable extracted.
    Q: something REQUIRED is missing (not merely unreadable), so the assistant asks. R: the question crosses a policy
    boundary (other sellers, session override, write op)  -  refuse and explain, never call the model. Nothing is ever assumed."""
    policy = policy_hit(ex.question.lower())
    if policy:
        return "R", "policy: this portal only reads the logged-in seller's own data (" + ", ".join(policy) + ")"
    if ex.unsupported:
        return "C", "unsupported intent: " + ", ".join(ex.unsupported)
    if (ex.metric.status == "missing" and ex.category.status in ("default", "unresolved") and ex.category.value in (None, [])
            and ex.date.status == "default" and ex.intent.rule == "default"):
        return "C", "nothing could be extracted from the question"
    if ex.metric.status == "missing":
        return "Q", "the question doesn't say what to measure, and nobody can guess that for the user"
    gaps = [n for n, s in ex.slots.items() if s.status == "unresolved"]
    if gaps:
        return "B", "rules could not resolve: " + ", ".join(gaps)
    return "A", "every slot resolved by rules"
