"""Pipeline coordinator for the Retrieval-as-a-Guardrail system.

Coordinates deterministic intent/slot extraction, semantic category matching, policy gates,
parameterized SQL template execution, and LLM fallback for gap-filling.
"""
import json
import os
import re
import sqlite3
import threading
import time
import uuid
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from . import matcher as gm
from .config import CONFIG, DEFAULT_CALENDAR, DEFAULT_TODAY, DEMO_SELLERS, METRIC_OPTIONS
from .dates import POLICIES
from .extract import (
    CHANGE_WORDS, POLICY_PHRASES, POLICY_WORDS, UNSUPPORTED, UNSUPPORTED_PHRASES,
    Extraction, cal_range, compare_hit, extract, load_groups, policy_hit, route
)
from .formatting import (
    day_text, format_comparison, format_response, format_value, pretty_category,
    range_text, when_text
)
from .llm import LLM, est_tokens, parse_json
from .memory import ConversationStore
from .prompts import (
    FILL_CATEGORY_SCHEMA, FILL_DATE_SCHEMA, PLAN_SCHEMA,
    build_fill_category_prompt, build_fill_date_prompt, build_plan_prompt
)
from .sql import execute_template, plan_sql

PKG = Path(__file__).resolve().parent
TODAY = date(2018, 9, 1)
DAY_FIRST = True
METRIC_OPTIONS = [("Number of orders", "orders"), ("Revenue", "revenue"), ("Items sold", "items sold")]
DATA_MIN, DATA_MAX = date(2016, 1, 1), date(2018, 12, 31)
DEMO_SELLERS = [
    "955fee9216a65b617aa5c0531780ce60",
    "4869f7a5dfa277a7dca6462dcf3b52b2",
    "8b321bb669392f5163d04c59e235e066"
]
SELLER_RE = re.compile(r"^[0-9a-f]{32}$")


class Engine:
    """Core Guardrail pipeline coordinator."""

    def __init__(self, data_dir: Optional[str] = None, db_path: Optional[str] = None,
                 canonical_dir: Optional[str] = None, llm_mode: Optional[str] = None, today: Optional[date] = None):
        self.root = Path(data_dir or (PKG.parent / "data")).resolve()
        self.db_path = Path(db_path or (PKG.parent / "data" / "olist_seller.sqlite")).resolve()
        self.canonical_dir = Path(canonical_dir or (PKG.parent / "canonical")).resolve()
        self.today = today or TODAY

        self.canonical_vocab_path = self.canonical_dir / "vocabulary.json"
        self.canonical_groups_path = self.canonical_dir / "groups.json"
        self.canonical_calendar_path = self.canonical_dir / "calendar.json"
        self.canonical_amounts_path = self.canonical_dir / "amounts.json"
        self.canonical_scope_path = self.canonical_dir / "unsupported.json"

        self.audit_log_path = self.root / "audit.jsonl"
        self.review_queue_path = self.root / "review_queue.jsonl"
        self.cache_path = self.root / "llm_cache.jsonl"

        self._lock = threading.Lock()
        self.ro = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True, check_same_thread=False)
        self.ro.execute("PRAGMA query_only = ON;")

        self.llm = LLM(self.cache_path)
        if llm_mode and llm_mode != "env":
            self.llm.mode = llm_mode
        self.memory = ConversationStore()
        # Keep conversations dict property for test backward compatibility
        self.conversations = self.memory._conversations
        self.pending = self.memory._pending

        self.vocab: Dict[str, Any] = {}
        self.groups: Dict[str, List[str]] = {}
        self.calendar: Dict[str, Any] = {}
        self.amounts: Dict[str, Any] = {}
        self.reload()

    def reload(self) -> None:
        """Reload vocabulary, groups, calendar, amounts, and unsupported terms from canonical JSON files."""
        base_dir = (PKG.parent / "canonical").resolve()

        self.vocab = {}
        if (base_dir / "vocabulary.json").exists():
            self._merge_vocab_json(base_dir / "vocabulary.json")
        if self.canonical_vocab_path.exists() and self.canonical_vocab_path != (base_dir / "vocabulary.json"):
            self._merge_vocab_json(self.canonical_vocab_path)

        self.groups = {}
        for gpath in [(base_dir / "groups.json"), self.canonical_groups_path]:
            if gpath.exists():
                with open(gpath) as f:
                    cg = json.load(f)
                for name, members in cg.items():
                    if name.startswith("_") or not isinstance(members, list):
                        continue
                    self.groups.setdefault(name.lower(), [])
                    for m in members:
                        if m in self.vocab and m not in self.groups[name.lower()]:
                            self.groups[name.lower()].append(m)

        self.calendar = dict(DEFAULT_CALENDAR)
        for cpath in [(base_dir / "calendar.json"), self.canonical_calendar_path]:
            if cpath.exists():
                with open(cpath) as f:
                    d = json.load(f)
                    self.calendar.update({k.lower(): v for k, v in d.items() if not k.startswith("_")})

        for spath in [(base_dir / "unsupported.json"), self.canonical_scope_path]:
            if spath.exists():
                self._merge_scope_json(spath)

        self.amounts = {}
        for apath in [(base_dir / "amounts.json"), self.canonical_amounts_path]:
            if apath.exists():
                with open(apath) as f:
                    d = json.load(f)
                for phrase, spec in d.items():
                    if phrase.startswith("_") or not isinstance(spec, dict):
                        continue
                    if self._validate_amount(spec):
                        self.amounts[phrase.lower()] = spec

    def _merge_vocab_json(self, path: Path) -> None:
        with open(path) as f:
            d = json.load(f)
        for cat, aliases in d.items():
            if cat.startswith("_") or not isinstance(aliases, list):
                continue
            if cat not in self.vocab:
                self.vocab[cat] = {"category_english": cat, "aliases": []}
            for a in aliases:
                if a not in self.vocab[cat]["aliases"]:
                    self.vocab[cat]["aliases"].append(a)

    def _merge_scope_json(self, path: Path) -> None:
        from . import extract as _ex
        with open(path) as f:
            d = json.load(f)
        for w in d.get("scope_words", []):
            _ex.UNSUPPORTED.add(w.lower())
        for p in d.get("scope_phrases", []):
            if p and p.lower() not in _ex.UNSUPPORTED_PHRASES:
                _ex.UNSUPPORTED_PHRASES.append(p.lower())

    def _validate_amount(self, spec: Dict[str, Any]) -> bool:
        return (
            isinstance(spec, dict)
            and spec.get("column") in ("price", "freight_value")
            and spec.get("op") in (">=", "<=", ">", "<", "=")
            and isinstance(spec.get("value"), (int, float))
            and spec["value"] >= 0
        )

    def categories(self) -> List[str]:
        return sorted(self.vocab.keys())

    def sellers(self) -> List[Dict[str, Any]]:
        try:
            cur = self.ro.execute(
                "SELECT i.seller_id, s.city, s.state, count(*) AS item_count "
                "FROM items i JOIN sellers s ON i.seller_id = s.seller_id "
                "GROUP BY i.seller_id ORDER BY item_count DESC LIMIT 10"
            )
            out = []
            for sid, city, st, cnt in cur.fetchall():
                top_cats = [
                    r[0] for r in self.ro.execute(
                        "SELECT category_english, count(*) AS c "
                        "FROM items WHERE seller_id = ? "
                        "GROUP BY category_english ORDER BY c DESC LIMIT 3",
                        (sid,)
                    ).fetchall() if r[0]
                ]
                out.append({
                    "seller_id": sid,
                    "label": f"Seller ...{sid[-4:]} : {city}, {st}",
                    "items": cnt,
                    "top_categories": top_cats
                })
            # The workshop demo is designed around DEMO_SELLERS[0]: the only seller with non-zero
            # activity across every HANDS_ON.md activity (health_beauty, furniture-living-room bundle,
            # founders week, mega orders). Pin it to the front so the UI signs in as this seller by
            # default, matching the CLI (scripts/ask.py) and the notebook's engine.sellers()[0].
            demo_ids = set(DEMO_SELLERS)
            preferred = [row for row in out if row["seller_id"] in demo_ids]
            preferred.sort(key=lambda r: DEMO_SELLERS.index(r["seller_id"]))
            others = [row for row in out if row["seller_id"] not in demo_ids]
            return preferred + others
        except Exception:
            return [{"seller_id": s, "label": f"Seller ...{s[-4:]}", "items": 100, "top_categories": []} for s in DEMO_SELLERS]

    def _seller(self, seller_id: str) -> str:
        if not SELLER_RE.match(seller_id or "") or not self.ro.execute("SELECT 1 FROM sellers WHERE seller_id = ?", (seller_id,)).fetchone():
            raise ValueError("unknown seller")
        return seller_id

    # ---------- Main Chat Turn ----------

    def chat(self, seller_id: str, message: str, design: str = "deterministic", today: Optional[date] = None) -> Dict[str, Any]:
        """Process a natural language user query through the Guardrail pipeline."""
        today = today or self.today
        message = (message or "").strip()[:CONFIG.input.message_max_chars]
        seller = self._seller(seller_id)

        T: Dict[str, Any] = {
            "message": message,
            "seller": seller,
            "design": design,
            "today": today.isoformat(),
            "steps": [],
            "llm_calls": [],
            "route": None,
            "initial_route": None,
            "route_reason": None,
            "outcome": None,
            "plan": None,
            "result": None,
            "reply": None,
            "slots": {},
            "tokens": {"calls": 0, "in": 0, "out": 0}
        }

        def step(name: str, status: str, detail: str, source: str = "rule") -> None:
            T["steps"].append({"name": name, "status": status, "detail": detail, "source": source})

        step("Who is asking", "ok", f"Seller ...{seller[-4:]}, from the login session. Read-only isolated data.", "session")

        # Design: Model-Only Mode (all_llm)
        if design == "all_llm":
            step("Prompt model directly", "ok", "Design: Model-only. Model writes SQL directly from question without rule templates.", "llm")
            r, sql = self.llm_plan(message, today, big=True)
            T["llm_calls"].append(r)
            T["route"] = "LLM"
            T["initial_route"] = "LLM"
            T["route_reason"] = "Model-only design baseline"

            if r.get("source") == "error":
                T["outcome"] = "error"
                err_msg = r.get("error", "API request failed")
                step("Model execution", "fail", f"Model API error: {err_msg}", "llm")
                T["reply"] = f"The model request failed with an API error:\n\n`{err_msg}`\n\nPlease check your API key and account quota."
                return self._finish(T)

            if r.get("source") == "unavailable" or not self.llm.key:
                T["outcome"] = "unavailable"
                step("Model execution", "gap", f"Prompt constructed (~{r.get('prompt_tokens_est', 1640)} tokens). Offline: enter an API key in the top bar to run live.", "llm")
                T["reply"] = (
                    "In the baseline **Model only** mode, the entire question and full database schema are sent directly to the model (~1,640 prompt tokens).\n\n"
                    "Connect an API key in the top bar to run live, or switch to **Rules first** to see how the guardrail answers this question deterministically with 0 tokens."
                )
                return self._finish(T)

            if not sql:
                j = parse_json(r.get("text"))
                reason = j.get("reason") if j else None
                T["outcome"] = "refused_scope" if reason else "error"
                if reason:
                    step("Model execution", "ok", f"Model returned no SQL. Reason: {reason}", "llm")
                    T["reply"] = (
                        "**The model chose not to write a query.** Its stated reason:\n\n"
                        f"> {reason}\n\n"
                        "*Switch to Rules first to see how the guardrail handles the same question.*"
                    )
                else:
                    step("Model execution", "fail", "Model did not return a valid SQL query.", "llm")
                    T["reply"] = (
                        "**The model could not generate a query for this question.** "
                        "No structured response was returned.\n\n"
                        "*Switch to Rules first to see how the guardrail handles it.*"
                    )
                return self._finish(T)

            t0 = time.perf_counter()
            try:
                clean_sql = sql.strip().rstrip(";")
                if clean_sql.upper().startswith("WITH "):
                    exec_sql = f"WITH my_items AS (SELECT * FROM items WHERE seller_id = ?), {clean_sql[5:]}"
                else:
                    exec_sql = f"WITH my_items AS (SELECT * FROM items WHERE seller_id = ?)\n{clean_sql}"

                cur = self.ro.execute(exec_sql, [seller])
                raw_rows = cur.fetchall()
                duration_ms = round((time.perf_counter() - t0) * 1000, 2)
                cols = [c[0] for c in cur.description] if cur.description else ["result"]
                res = {
                    "type": "model_sql",
                    "columns": cols,
                    "rows": [list(row) for row in raw_rows],
                    "sql": sql,
                    "params": [seller],
                    "duration_ms": duration_ms
                }
                T["outcome"] = "answered"
                T["result"] = res

                if len(raw_rows) == 0:
                    T["reply"] = "The model query returned no matching records for this period."
                elif len(raw_rows) == 1 and len(raw_rows[0]) == 1:
                    val = raw_rows[0][0]
                    if isinstance(val, float):
                        val_str = f"R$ {val:,.2f}"
                    elif isinstance(val, int):
                        val_str = f"{val:,}"
                    else:
                        val_str = str(val) if val is not None else "0"
                    T["reply"] = f"Result from the model query: **{val_str}**"
                else:
                    def _fmt(v):
                        if isinstance(v, float):
                            return f"R$ {v:,.2f}"
                        if isinstance(v, int):
                            return f"{v:,}"
                        return str(v) if v is not None else "0"

                    single_row_multi_col = len(raw_rows) == 1 and len(raw_rows[0]) > 1
                    lines = [f"Result from the model query ({len(raw_rows)} row{'s' if len(raw_rows) != 1 else ''}):"]
                    if single_row_multi_col:
                        # One row with several columns: label each cell with its column name so the seller can read it.
                        for col_name, cell in zip(cols, raw_rows[0]):
                            lines.append(f"- **{col_name}**: {_fmt(cell)}")
                    else:
                        for i, row in enumerate(raw_rows[:15], 1):
                            if len(row) == 2:
                                col1, col2 = row[0], row[1]
                                cat_label = pretty_category(str(col1)) if isinstance(col1, str) else str(col1)
                                lines.append(f"{i}. {cat_label}: {_fmt(col2)}")
                            else:
                                parts = [f"{col_name}={_fmt(v)}" for col_name, v in zip(cols, row)]
                                lines.append(f"- {' · '.join(parts)}")
                        if len(raw_rows) > 15:
                            lines.append(f"\n*(Showing top 15 of {len(raw_rows)} rows. See table in backend pane)*")
                    T["reply"] = "\n".join(lines)

                step("Execute model SQL", "ok", f"Executed in {duration_ms}ms against isolated seller data.", "llm")
                return self._finish(T)
            except Exception as e:
                T["outcome"] = "error"
                T["reply"] = f"The model-generated query failed to execute: {str(e)}"
                step("Execute model SQL", "fail", f"SQL execution error: {str(e)}", "llm")
                return self._finish(T)

        # Step 1: Policy Gate
        low = message.lower()
        pol_hits = policy_hit(low)
        step("Privacy check", "fail" if pol_hits else "ok",
             f"Cross-tenant / write intent detected: {', '.join(pol_hits)}." if pol_hits else "Policy check passed.",
             "rule")

        # Step 2: Scope Gate
        scope_words = sorted({w for w in re.findall(r"[a-z0-9_']+", low) if w in UNSUPPORTED})
        scope_phrases = [p for p in UNSUPPORTED_PHRASES if p in low]
        scope_hits = scope_phrases + scope_words
        step("Scope check", "fail" if scope_hits and not pol_hits else "ok",
             f"Out-of-scope words: {', '.join(scope_hits)}." if scope_hits and not pol_hits else "Scope check passed.",
             "rule")

        # Step 3: Extract Slots
        ex = extract(message, self.vocab, self.groups, today, day_first=DAY_FIRST, calendar=self.calendar, amounts=self.amounts)

        # Multi-turn context inheritance
        prior = self.memory.get(seller)
        followup_reason = self.memory.detect_followup_reason(message, ex, prior)
        if prior and followup_reason:
            inherited = self.memory.inherit_from_prior(ex, prior)
            if inherited:
                step("Continuing conversation", "ok", f"Follow-up ({followup_reason}): inherited {', '.join(inherited)}.", "rule")

        self._record_slots(T, ex, step)
        rt, why = route(ex)
        T["route"], T["initial_route"], T["route_reason"] = rt, rt, why
        step("Decision", "ok", f"Selected Route {rt} ({why})", "rule")

        plan = None
        if rt == "A":
            plan = self._plan_from(ex)
        elif rt == "B":
            plan = self._route_b(T, step, ex, today)
            if plan is None:
                T["route"] = rt = "C"
                T["route_reason"] += " -> model gap-fill rejected by validation"

        if rt == "R":
            return self._route_r(T, step, ex)
        if rt == "Q":
            # Persist any slots that WERE resolved (e.g. date, category) so the metric-clarify
            # follow-up inherits them instead of asking a fresh unfiltered query. memory.remember()
            # only stores slots whose status is "resolved", so a missing metric is naturally skipped.
            self.memory.remember(seller, ex, message)
            return self._route_q(T, step, seller, message)
        if rt == "C":
            return self._route_c(T, step, seller, message, ex, today)

        # Route A Execution
        if getattr(ex, "compare", "") and ex.date.status == "resolved":
            out = self._answer_compare(T, step, seller, ex, today, plan)
            if out["outcome"] == "answered":
                self.memory.remember(seller, ex, message)
            return out

        out = self._answer(T, step, seller, plan)
        if out["outcome"] == "answered":
            self.memory.remember(seller, ex, message)
        return out

    # ---------- Route Handlers ----------

    def _route_b(self, T: Dict[str, Any], step: Any, ex: Extraction, today: date) -> Optional[Dict[str, Any]]:
        """Constrained slot-filling via LLM with strict deterministic validation."""
        plan = self._plan_from(ex)
        if ex.date.status == "unresolved":
            self._log_review_queue(
                kind="date",
                phrase=ex.date.evidence,
                example=ex.question,
                cluster="time",
                nearest=[]
            )
            r, ok = self.llm_fill_date(ex.question, ex.date.evidence, today)
            T["llm_calls"].append(r)
            if ok:
                ex.date.status, ex.date.value, ex.date.rule = "resolved", ok, "llm"
                plan["start"], plan["end"] = ok[0], ok[1]
                step("Model slot-fill: date", "ok", f"Resolved date: {ok[0]} to {ok[1]}", "llm")
            else:
                if r.get("source") == "unavailable":
                    step("Model slot-fill: date", "fail",
                         "No LLM key configured, so this slot could not be filled by a model. "
                         "Set OPENAI_API_KEY or ANTHROPIC_API_KEY to try Route B end-to-end.", "llm")
                else:
                    step("Model slot-fill: date", "fail", "Model returned invalid/out-of-range date", "llm")
                return None

        if ex.category.status == "unresolved":
            words = ex.category.words or [ex.category.evidence]
            shortlist = self._shortlist_categories(words, k=3)
            self._log_review_queue(
                kind="category",
                phrase=ex.category.evidence or " ".join(words),
                example=ex.question,
                cluster=shortlist[0] if shortlist else "other",
                nearest=[{"category": c, "score": 0.5} for c in shortlist]
            )
            r, ok = self.llm_fill_category(ex.question, words)
            T["llm_calls"].append(r)
            if ok:
                ex.category.status, ex.category.value, ex.category.rule = "resolved", ok, "llm"
                plan["categories"] = ok
                plan["label"] = ", ".join(pretty_category(c) for c in ok)
                step("Model slot-fill: category", "ok", f"Resolved category: {plan['label']}", "llm")
            else:
                if r.get("source") == "unavailable":
                    step("Model slot-fill: category", "fail",
                         "No LLM key configured, so this slot could not be filled by a model. "
                         "Set OPENAI_API_KEY or ANTHROPIC_API_KEY to try Route B end-to-end.", "llm")
                else:
                    step("Model slot-fill: category", "fail", "Model returned no confident category from the shortlist", "llm")
                return None

        return plan

    def _route_r(self, T: Dict[str, Any], step: Any, ex: Extraction) -> Dict[str, Any]:
        """Refuse policy/privacy violations with zero model tokens."""
        step("Refuse policy", "ok", "Refused: only logged-in seller data is accessible.", "rule")
        m = ex.metric.value if ex.metric.status == "resolved" else None
        thing = {"orders": "order count", "revenue": "revenue", "items": "items sold"}.get(m, "metrics")
        when = when_text(ex.date.value[0] if ex.date.value else None, ex.date.value[1] if ex.date.value else None)
        T["outcome"] = "refused_policy"
        T["reply"] = (
            "This portal only shows your own orders - I cannot read other sellers' data or modify accounts.\n"
            f"Would you like {thing} {when}? For example: 'How many orders did I get last month?'"
        )
        return self._finish(T)

    def _route_q(self, T: Dict[str, Any], step: Any, seller: str, message: str) -> Dict[str, Any]:
        """Request missing information from user instead of guessing."""
        self.memory.set_pending(seller, message)
        T["outcome"], T["options"] = "clarify", [o[0] for o in METRIC_OPTIONS]
        step("Ask user", "ok", "Required metric missing. Asking user for clarification.", "rule")
        T["reply"] = "What would you like me to measure: the number of orders, your revenue, or items sold?"
        return self._finish(T)

    def _route_c(self, T: Dict[str, Any], step: Any, seller: str, message: str, ex: Extraction, today: date) -> Dict[str, Any]:
        """Scope refusal: refuse causal 'why'/forecast, OR refuse safely when the LLM slot-fill returned no confident category."""
        is_b_fallback = T.get("initial_route") == "B"

        # Route B fallback: the LLM could not confidently confirm the fuzzy matcher's guess for the
        # unresolved slot. Refuse cleanly with no number. Showing an "unfiltered total for context"
        # was confusing: users read a number and assumed it was the answer to their question. A count
        # only makes sense once we know what they were counting, and here we don't.
        if is_b_fallback:
            # Figure out which slot was actually unresolved, so the message can name it accurately.
            slot_kind = "term"
            slot_evidence = ""
            for name, kind in (("category", "product term"), ("date", "date phrase"), ("amount", "amount phrase")):
                slot = getattr(ex, name, None)
                if slot is not None and getattr(slot, "status", None) == "unresolved":
                    ev = (getattr(slot, "evidence", "") or "").strip()
                    if ev and not ev.startswith("no "):  # skip placeholder texts like "no category in the question"
                        slot_kind = kind
                        slot_evidence = ev
                        break
            step("Fall back to Route C", "ok",
                 f"The LLM could not confidently map the unresolved word(s). "
                 f"Refusing without guessing; no number returned.", "rule")
            T["outcome"] = "refused_unknown_term"
            hint = f" (I could not identify “{slot_evidence}” from what the shop knows.)" if slot_evidence else ""
            T["reply"] = (
                f"I could not identify the {slot_kind} in your question, so I cannot give you a specific answer.{hint}\n\n"
                f"Try rephrasing with terms the shop already knows, or add the phrase to a file under `canonical/` so future asks resolve without me."
            )
            return self._finish(T)

        # Genuine scope refusal (why / forecast / predict, etc.): keep showing the underlying number
        # as context, since the metric and period ARE resolved and the user asked a legitimate question
        # that we just can't answer causally.
        step("Refuse scope", "ok", "Refused: causal reasoning / forecasting / out-of-scope intent.", "rule")
        can_compute = ex.metric.status == "resolved" and (ex.date.status == "resolved" or ex.category.status == "resolved")
        if can_compute:
            plan = self._plan_from(ex)
            plan["intent"] = "total"
            res = execute_template(self.ro, plan, seller)
            T["outcome"] = "refused_scope_with_data"
            T["plan"], T["result"] = plan, res
            formatted_data = format_response(plan, res)
            T["reply"] = (
                "I answer numeric questions from your orders. I cannot infer causes or forecast trends, "
                f"but here is your requested data:\n\n{formatted_data}"
            )
        else:
            T["outcome"] = "refused_scope"
            T["reply"] = (
                "I answer numeric questions from your own orders (counts, revenue, items sold, top categories, monthly breakdowns). "
                "I do not infer causes, forecast trends, or reason about external factors."
            )
        return self._finish(T)

    def _answer(self, T: Dict[str, Any], step: Any, seller: str, plan: Dict[str, Any]) -> Dict[str, Any]:
        """Execute template and format response."""
        res = execute_template(self.ro, plan, seller)
        T["plan"], T["result"] = plan, res
        T["outcome"] = "answered"
        T["reply"] = format_response(plan, res)
        step("Execute SQL Template", "ok", f"Executed in {res['duration_ms']}ms (0 LLM tokens).", "rule")
        return self._finish(T)

    def _answer_compare(self, T: Dict[str, Any], step: Any, seller: str, ex: Extraction, today: date, plan: Dict[str, Any]) -> Dict[str, Any]:
        """Execute period comparison across two windows."""
        plan_a = dict(plan)
        res_a = execute_template(self.ro, plan_a, seller)

        # Compute comparison window
        s_date = date.fromisoformat(plan["start"])
        e_date = date.fromisoformat(plan["end"])
        days = (e_date - s_date).days + 1
        prev_end = s_date - timedelta(days=1)
        prev_start = prev_end - timedelta(days=days - 1)

        plan_b = dict(plan)
        plan_b["start"], plan_b["end"] = prev_start.isoformat(), prev_end.isoformat()
        res_b = execute_template(self.ro, plan_b, seller)

        T["plan"], T["result"] = plan_a, res_a
        T["outcome"] = "answered"
        T["reply"] = format_comparison(plan_a, res_a, plan_b, res_b)
        step("Execute Compare Templates", "ok", "Executed side-by-side period comparisons.", "rule")
        return self._finish(T)

    # ---------- Prompt Helpers ----------

    def llm_fill_date(self, question: str, phrase: str, today: date, temperature: float = 0.0) -> Tuple[Dict[str, Any], Optional[Tuple[str, str]]]:
        system, user = build_fill_date_prompt(today.isoformat(), question, phrase)
        r = self.llm.complete("fill_date", system, user, CONFIG.llm.max_tokens_fill_date, temperature, schema=FILL_DATE_SCHEMA)
        j = parse_json(r["text"])
        ok = self._valid_range(j.get("start"), j.get("end")) if j else None
        return r, ok

    def llm_fill_category(self, question: str, words: List[str]) -> Tuple[Dict[str, Any], Optional[List[str]]]:
        shortlist = self._shortlist_categories(words, k=12)
        system, user = build_fill_category_prompt(question, words, shortlist)
        r = self.llm.complete("fill_category", system, user, CONFIG.llm.max_tokens_fill_category, schema=FILL_CATEGORY_SCHEMA)
        j = parse_json(r["text"])
        cats = j.get("categories") if j else None
        ok = sorted(set(cats)) if isinstance(cats, list) and cats and all(c in self.vocab for c in cats) else None
        return r, ok

    def _shortlist_categories(self, words: List[str], k: int = 12) -> List[str]:
        if not words:
            return sorted(self.vocab.keys())[:k]
        toks = gm.clean_tokens(" ".join(words))
        ranked = gm.score_all(toks, self.vocab)[:k]
        return [c for c, _, _, _ in ranked]

    def llm_plan(self, question: str, today: date, big: bool = False) -> Tuple[Dict[str, Any], Optional[str]]:
        system, user = build_plan_prompt(today.isoformat(), question, self.categories(), big=big)
        r = self.llm.complete("plan_full" if not big else "all_llm", system, user, CONFIG.llm.max_tokens_plan, schema=PLAN_SCHEMA)
        j = parse_json(r["text"])
        return r, (j.get("sql") if j else None)

    def _valid_range(self, start: Any, end: Any) -> Optional[Tuple[str, str]]:
        if not start or not end or not isinstance(start, str) or not isinstance(end, str):
            return None
        try:
            s, e = date.fromisoformat(start), date.fromisoformat(end)
            if s <= e and DATA_MIN <= s <= DATA_MAX and DATA_MIN <= e <= DATA_MAX:
                return start, end
        except ValueError:
            pass
        return None

    def _plan_from(self, ex: Extraction) -> Dict[str, Any]:
        d = ex.date.value or (None, None)
        cats = ex.category.value or []
        label = ", ".join(pretty_category(c) for c in cats) if cats else "all your products"
        plan = {
            "intent": ex.intent.value,
            "metric": ex.metric.value,
            "categories": cats,
            "start": d[0],
            "end": d[1],
            "topn": ex.topn,
            "label": label
        }
        if getattr(ex, "amount", None):
            plan["amount"] = dict(ex.amount)
            plan["label"] = f"{ex.amount['phrase']} in {label}" if cats else ex.amount["phrase"]
        return plan

    def _record_slots(self, T: Dict[str, Any], ex: Extraction, step: Any) -> None:
        for name, slot in ex.slots.items():
            T["slots"][name] = {
                "status": slot.status,
                "value": slot.value,
                "evidence": slot.evidence,
                "rule": slot.rule,
                "flags": slot.flags,
                "words": slot.words,
                "source": "rule"
            }

    def plan_sql(self, plan: Dict[str, Any], seller_id: str) -> Tuple[str, List[Any]]:
        return plan_sql(plan, seller_id)

    def run_template(self, plan: Dict[str, Any], seller: str) -> Dict[str, Any]:
        return execute_template(self.ro, plan, seller)

    def _finish(self, T: Dict[str, Any]) -> Dict[str, Any]:
        T["tokens"]["calls"] = len(T["llm_calls"])
        T["tokens"]["in"] = sum(c.get("tokens_in", 0) for c in T["llm_calls"])
        T["tokens"]["out"] = sum(c.get("tokens_out", 0) for c in T["llm_calls"])
        if any(c.get("source") == "unavailable" for c in T["llm_calls"]):
            T["tokens"]["estimated"] = True
        if "result" in T and T["result"] and "sql" in T["result"]:
            T["sql"] = {"text": T["result"]["sql"], "params": T["result"].get("params", [])}
        else:
            T["sql"] = None
        self._audit_log(T)
        return T

    def _audit_log(self, T: Dict[str, Any]) -> None:
        row = {
            "id": str(uuid.uuid4()),
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
            "timestamp": time.time(),
            "seller": T["seller"][-4:] if len(T.get("seller", "")) >= 4 else T.get("seller", ""),
            "message": T["message"],
            "route": T["route"],
            "outcome": T["outcome"],
            "llm_calls": T["llm_calls"],
            "calls": T["tokens"]["calls"]
        }
        T["audit"] = row
        with self._lock:
            try:
                with open(self.audit_log_path, "a") as f:
                    f.write(json.dumps(row) + "\n")
            except Exception:
                pass

    def audit_tail(self, n: int = 50) -> List[Dict[str, Any]]:
        if not self.audit_log_path.exists():
            return []
        with open(self.audit_log_path) as f:
            lines = f.readlines()
        parsed = []
        for line in reversed(lines):
            line = line.strip()
            if not line:
                continue
            try:
                parsed.append(json.loads(line))
            except Exception:
                pass
            if len(parsed) >= n:
                break
        return parsed

    def _log_review_queue(self, kind: str, phrase: str, example: str, cluster: str,
                          nearest: List[Dict[str, Any]], model_pick: Optional[List[str]] = None) -> None:
        phrase = phrase.strip().lower()
        if not phrase:
            return
        row = {
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
            "kind": kind,
            "phrase": phrase,
            "example": example,
            "cluster": cluster,
            "nearest": nearest,
            "model_pick": model_pick or []
        }
        with self._lock:
            try:
                with open(self.review_queue_path, "a") as f:
                    f.write(json.dumps(row) + "\n")
            except Exception:
                pass

    def queue(self) -> List[Dict[str, Any]]:
        if not self.review_queue_path.exists():
            return []
        rows = []
        with open(self.review_queue_path) as f:
            for line in f:
                if line.strip():
                    try:
                        rows.append(json.loads(line))
                    except Exception:
                        pass

        agg: Dict[Tuple[str, str], Dict[str, Any]] = {}
        for r in rows:
            kind = r.get("kind", "category")
            phrase = r.get("phrase", "")
            if not phrase:
                continue
            key = (kind, phrase.lower())
            if key not in agg:
                cluster = r.get("cluster") or ("time" if kind == "date" else "other")
                mapped = False
                if kind == "category":
                    mapped = any(phrase.lower() in aliases.get("aliases", []) for aliases in self.vocab.values())
                elif kind == "date":
                    mapped = phrase.lower() in self.calendar
                agg[key] = {
                    "kind": kind,
                    "phrase": phrase,
                    "cluster": cluster,
                    "example": r.get("example", phrase),
                    "count": 0,
                    "nearest": r.get("nearest", []),
                    "model_pick": r.get("model_pick", []),
                    "mapped": mapped
                }
            agg[key]["count"] += 1
        return list(agg.values())

    def reset(self) -> None:
        """Reset conversation sessions and review queue, reload canonical definitions."""
        self.memory.clear_all()
        if self.review_queue_path.exists():
            self.review_queue_path.write_text("")
        self.reload()

    def set_api_key(self, key: str, provider: str = "openai") -> Dict[str, Any]:
        """Validate and set model API key."""
        status = self.llm.check_key(key, provider=provider)
        models = self.llm.list_models(key, provider) if status == "valid" else []
        self.llm.set_key(key, verified=(status == "valid"), provider=provider, models=models)
        return {"status": status, "verified": (status == "valid"), "models": self.llm.models, "provider": provider}

    def clear_api_key(self) -> None:
        """Clear model API key."""
        self.llm.clear_key()

    def set_model(self, model: str) -> Dict[str, Any]:
        """Update selected model."""
        self.llm.set_model(model)
        return {"ok": True, "model": model}

    def info(self) -> Dict[str, Any]:
        return {
            "today": self.today.isoformat(),
            "categories_count": len(self.vocab),
            "sellers_count": len(self.sellers()),
            "llm_mode": self.llm.mode,
            "llm": self.llm.status()
        }
