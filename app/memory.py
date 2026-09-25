"""Multi-turn conversation state manager and context inheritance engine.

Persists resolved slots across conversation turns and allows partial updates (e.g., changing only date,
changing only metric, or asking for monthly rollups) to inherit prior context seamlessly.
Refused turns are NEVER remembered.
"""
import time
from typing import Any, Dict, List, Optional, Tuple

from .formatting import pretty_category, range_text

REFERENTIAL_WORDS = {"those", "them", "these", "same", "one", "ones", "recent", "it", "that", "this"}
FOLLOWUP_STARTERS = (
    "show ", "list ", "give me", "and ", "also ", "same", "what about",
    "how about", "can you", "now show", "now list", "just", "in ", "for ",
    "during ", "what was ", "break it down", "monthly"
)


class ConversationStore:
    """In-memory session store tracking per-seller conversation state."""

    def __init__(self):
        self._conversations: Dict[str, Dict[str, Any]] = {}
        self._pending: Dict[str, Dict[str, Any]] = {}

    def get(self, seller_id: str) -> Optional[Dict[str, Any]]:
        return self._conversations.get(seller_id)

    def set_pending(self, seller_id: str, message: str) -> None:
        self._pending[seller_id] = {"message": message, "ts": time.time()}

    def get_pending(self, seller_id: str) -> Optional[Dict[str, Any]]:
        return self._pending.get(seller_id)

    def clear_pending(self, seller_id: str) -> None:
        self._pending.pop(seller_id, None)

    def clear(self, seller_id: str) -> None:
        """Clear conversation memory and pending state for a specific seller."""
        self._conversations.pop(seller_id, None)
        self._pending.pop(seller_id, None)

    def clear_all(self) -> None:
        """Clear all active conversation sessions and pending states."""
        self._conversations.clear()
        self._pending.clear()

    def remember(self, seller_id: str, ex: Any, message: str) -> None:
        """Store the current turn's resolved slots so the next turn can inherit them. Never store refusals."""
        snap = dict(self._conversations.get(seller_id, {}))
        snap.update({"message": message, "ts": time.time(), "intent": ex.intent.value, "topn": getattr(ex, "topn", 5)})
        for name in ("date", "category", "metric"):
            slot = getattr(ex, name)
            if slot.status == "resolved":
                snap[name] = {
                    "status": "resolved",
                    "value": list(slot.value) if isinstance(slot.value, (tuple, list)) else slot.value,
                    "evidence": slot.evidence,
                    "rule": slot.rule
                }
        self._conversations[seller_id] = snap

    def detect_followup_reason(self, message: str, ex: Any, prior: Optional[Dict[str, Any]]) -> str:
        """Return a short reason string if the message looks like a follow-up, else empty string."""
        if not prior:
            return ""
        low = message.lower().strip().rstrip("?!.")
        words = low.split()
        if not words or len(words) > 12:
            return ""

        ref_hit = [w for w in words if w in REFERENTIAL_WORDS]
        if ref_hit:
            return f"referential word: '{ref_hit[0]}'"

        for s in FOLLOWUP_STARTERS:
            if low.startswith(s):
                return f"follow-up starter: '{s.strip()}'"

        has_metric = ex.metric.status == "resolved"
        has_date = ex.date.status == "resolved"
        has_cat = ex.category.status == "resolved"
        has_intent = ex.intent.rule != "default"

        if len(words) <= 7 and (has_metric or has_date or has_cat or has_intent):
            if not (has_metric and has_date and has_cat):
                return "partial query continuing prior context"

        if len(words) <= 4:
            return "short context continuation"

        return ""

    def inherit_from_prior(self, ex: Any, prior: Dict[str, Any]) -> List[str]:
        """Copy resolved date/category/metric/intent from prior turn onto the current extraction if left default."""
        inherited = []
        pd = prior.get("date")
        if pd and pd.get("status") == "resolved" and ex.date.status == "default":
            ex.date.status = "resolved"
            ex.date.value = tuple(pd["value"]) if isinstance(pd["value"], list) else pd["value"]
            ex.date.evidence = pd["evidence"]
            ex.date.rule = pd.get("rule", "inherited")
            ex.date.flags = list(ex.date.flags or []) + ["inherited"]
            inherited.append(f"date ({range_text(*ex.date.value)})")

        pi = prior.get("intent")
        if pi and pi in ("top_categories", "by_month", "by_day", "list_records") and ex.intent.rule == "default":
            ex.intent.value = pi
            ex.intent.rule = "inherited"
            if pi == "top_categories":
                ex.topn = prior.get("topn", 5)
            inherited.append(f"intent ({pi})")

        pc = prior.get("category")
        if pc and pc.get("status") == "resolved" and ex.category.status in ("default", "unresolved"):
            if ex.intent.value != "top_categories":
                ex.category.status = "resolved"
                ex.category.value = list(pc["value"])
                ex.category.evidence = pc["evidence"]
                ex.category.rule = pc.get("rule", "inherited")
                ex.category.flags = list(ex.category.flags or []) + ["inherited"]
                inherited.append(f"category ({', '.join(pretty_category(c) for c in ex.category.value)})")

        pm = prior.get("metric")
        if pm and pm.get("status") == "resolved" and ex.metric.status == "missing":
            ex.metric.status = "resolved"
            ex.metric.value = pm["value"]
            ex.metric.evidence = pm["evidence"]
            ex.metric.rule = pm.get("rule", "inherited")
            ex.metric.flags = list(ex.metric.flags or []) + ["inherited"]
            inherited.append(f"metric ({ex.metric.value})")

        return inherited
