"""Formatting utilities for dates, numbers, categories, and natural-language responses.

Deterministic, zero LLM dependencies.
"""
from datetime import date
from typing import Any, Dict, List, Optional, Union

MONTH_NAMES = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December"
]


def _to_date(x: Union[str, date]) -> date:
    return date.fromisoformat(x) if isinstance(x, str) else x


def day_text(d: Union[str, date]) -> str:
    """Format single day as '15 Mar 2018'."""
    d = _to_date(d)
    return f"{d.day} {MONTH_NAMES[d.month - 1][:3]} {d.year}"


def range_text(start: Optional[Union[str, date]], end: Optional[Union[str, date]]) -> str:
    """Format inclusive date range into plain English: 'March 2018', 'Q2 2018', '2017', '1 Apr to 30 Jun 2018'."""
    if not start and not end:
        return "all time"
    if start and end:
        s_, e_ = _to_date(start), _to_date(end)
        if s_ == e_:
            return day_text(s_)
        import calendar
        _, last_day = calendar.monthrange(e_.year, e_.month)
        if s_.day == 1 and e_.day == last_day:
            if s_.month == e_.month and s_.year == e_.year:
                return f"{MONTH_NAMES[s_.month - 1]} {s_.year}"
            if s_.year == e_.year and s_.month % 3 == 1 and e_.month == s_.month + 2:
                return f"Q{(s_.month - 1) // 3 + 1} {s_.year}"
            if s_.month == 1 and e_.month == 12 and s_.year == e_.year:
                return str(s_.year)
        return f"{day_text(s_)} to {day_text(e_)}"
    return f"since {day_text(start)}" if start else f"up to {day_text(end)}"


def when_text(start: Optional[Union[str, date]], end: Optional[Union[str, date]]) -> str:
    """Natural prepositional phrase for a period: 'in 2017', 'in March 2018', 'over all time'."""
    r = range_text(start, end)
    if r == "all time":
        return "over all time"
    if r.startswith(("since", "up to")):
        return r
    if " to " in r:
        return "from " + r
    if r[0].isdigit() and len(r) > 4:  # Single day like "24 Nov 2017"
        return "on " + r
    return "in " + r


def pretty_category(name: str) -> str:
    """Convert snake_case database category name to clean English title."""
    if not name:
        return "all your products"
    clean = name.replace("_", " ")
    return clean


def format_value(metric: str, val: Any) -> str:
    """Format numeric values with appropriate symbols and thousand separators."""
    if val is None:
        return "R$ 0.00" if metric == "revenue" else "0"
    try:
        num = float(val)
        return f"R$ {num:,.2f}" if metric == "revenue" else f"{int(num):,}"
    except (ValueError, TypeError):
        return str(val)


def format_response(plan: Dict[str, Any], res: Dict[str, Any]) -> str:
    """Format query execution result into a clean, human-readable response string."""
    m = plan.get("metric") or "orders"
    intent = plan.get("intent", "total")
    label = plan.get("label") or "all your products"
    when = when_text(plan.get("start"), plan.get("end"))
    metric_word = {"orders": "orders", "revenue": "revenue", "items": "items sold"}.get(m, "records")

    notes = []
    if m == "revenue":
        notes.append("('Revenue' here is your price total - shipping paid to logistics is not included.)")

    if intent == "total":
        v = format_value(m, res.get("value"))
        amt = plan.get("amount")
        if amt:
            threshold = f"({amt['column']} {amt['op']} R$ {amt['value']:,.2f})"
            cat_txt = f" in {label.replace(amt['phrase'] + ' in ', '') or 'all your products'}" if plan.get("categories") else ""
            if m == "orders":
                text = f"You had {v} {amt['phrase']}{cat_txt} {when}. {threshold}"
            elif m == "revenue":
                text = f"Your revenue from {amt['phrase']}{cat_txt} {when} was {v}. {threshold}"
            else:
                text = f"You sold {v} items in {amt['phrase']}{cat_txt} {when}. {threshold}"
        else:
            text = {
                "orders": f"You had {v} orders for {label} {when}.",
                "revenue": f"Your revenue for {label} {when} was {v}.",
                "items": f"You sold {v} items of {label} {when}."
            }.get(m, f"Your {metric_word} for {label} {when}: {v}.")

        if notes:
            text += "\n" + "\n".join(notes)
        return text

    elif intent == "by_month":
        rows = res.get("dict_rows") or res.get("rows", [])
        if not rows:
            return f"You had no {metric_word} for {label} {when}."
        lines = [f"Your {metric_word} by month for {label} {when}:"]
        for r in rows:
            if isinstance(r, (list, tuple)):
                month_label, raw_val = r[0], r[1]
            else:
                month_label, raw_val = r.get("month", ""), r.get("metric_value", r.get("value", 0))
            val = format_value(m, raw_val)
            lines.append(f"- {month_label}: {val}")
        if notes:
            lines.append("\n" + "\n".join(notes))
        return "\n".join(lines)

    elif intent == "top_categories":
        rows = res.get("dict_rows") or res.get("rows", [])
        if not rows:
            return f"No category records found for {when}."
        lines = [f"Your top {len(rows)} categories by {metric_word} {when}:"]
        for i, r in enumerate(rows, 1):
            if isinstance(r, (list, tuple)):
                cat_raw, raw_val = r[0], r[1]
            else:
                cat_raw, raw_val = r.get("category_english", r.get("category", "")), r.get("metric_value", r.get("value", 0))
            cat_name = pretty_category(cat_raw)
            val = format_value(m, raw_val)
            lines.append(f"{i}. {cat_name}: {val}")
        if notes:
            lines.append("\n" + "\n".join(notes))
        return "\n".join(lines)

    elif intent == "list_records":
        rows = res.get("dict_rows") or res.get("rows", [])
        if not rows:
            return f"No order records found for {label} {when}."
        lines = [f"Your orders for {label} {when} ({len(rows)} row{'s' if len(rows) != 1 else ''}):"]
        for r in rows:
            if isinstance(r, (list, tuple)):
                oid, cat, price_val, pdate = r[0], r[1], r[2], r[3]
            else:
                oid = r.get("order_id", "")
                cat = r.get("category_english", r.get("category", ""))
                price_val = r.get("price", 0)
                pdate = r.get("purchase_date", "")
            oid_str = str(oid)[:8] + "..."
            cat_str = pretty_category(cat)
            price_str = format_value("revenue", price_val)
            lines.append(f"- Order {oid_str} | {cat_str} | {price_str} | {pdate}")
        return "\n".join(lines)

    val = format_value(m, res.get("value"))
    return f"Result: {val}"


def format_comparison(plan_a: Dict[str, Any], res_a: Dict[str, Any],
                      plan_b: Dict[str, Any], res_b: Dict[str, Any]) -> str:
    """Format side-by-side period comparison response."""
    m = plan_a.get("metric") or "orders"
    word = {"orders": "orders", "revenue": "revenue", "items": "items sold"}.get(m, "results")
    label_a = range_text(plan_a.get("start"), plan_a.get("end"))
    label_b = range_text(plan_b.get("start"), plan_b.get("end"))
    val_a = format_value(m, res_a.get("value", 0))
    val_b = format_value(m, res_b.get("value", 0))

    change_line = ""
    try:
        fa = float(res_a.get("value", 0) or 0)
        fb = float(res_b.get("value", 0) or 0)
        if fb > 0:
            pct = (fa - fb) / fb * 100
            arrow = "^" if pct > 0 else ("v" if pct < 0 else "=")
            change_line = f"\nChange: **{arrow} {abs(pct):.1f}%** ({label_a} vs {label_b})."
        elif fa > 0:
            change_line = f"\nChange: **new activity** ({label_b} had none)."
    except (TypeError, ValueError):
        pass

    note = ""
    if m == "revenue":
        note = "\n(Revenue here is your price total - shipping paid to logistics is not included.)"

    return (
        f"Your {word}:\n"
        f"- **{label_a}**: {val_a}\n"
        f"- **{label_b}**: {val_b}"
        + change_line + note
    )
