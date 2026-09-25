"""Parameterized SQL template generation and guarded execution engine.

All queries on the deterministic path use pre-approved, parameterized templates
executed against the 'items' SQLite table in read-only mode.
"""
import sqlite3
import time
from typing import Any, Dict, List, Optional, Tuple

from .config import CONFIG

BASE_WHERE = "seller_id = ? AND order_status NOT IN ('canceled', 'unavailable')"
METRIC_SQL = {
    "orders": "COUNT(DISTINCT order_id)",
    "revenue": "ROUND(SUM(price), 2)",
    "items": "COUNT(*)"
}


def plan_sql(plan: Dict[str, Any], seller_id: str) -> Tuple[str, List[Any]]:
    """Build a parameterized SQL query and parameter list from a validated plan.
    
    Guarantees:
    - seller_id is always bound as a parameter (never string interpolated)
    - Canceled/unavailable orders are excluded
    - Categories are parameter-bound
    """
    m_sql = METRIC_SQL.get(plan.get("metric", "orders"), METRIC_SQL["orders"])
    cats = plan.get("categories") or []
    where = [BASE_WHERE]
    params: List[Any] = [seller_id]

    if cats:
        placeholders = ", ".join("?" for _ in cats)
        where.append(f"category_english IN ({placeholders})")
        params.extend(cats)

    if plan.get("start"):
        where.append("purchase_date >= ?")
        params.append(plan["start"])

    if plan.get("end"):
        where.append("purchase_date <= ?")
        params.append(plan["end"])

    # Canonical amount filter (e.g. price >= 300)
    amt = plan.get("amount")
    if amt and isinstance(amt, dict):
        col = "price" if amt["column"] == "price" else "freight_value"
        where.append(f"{col} {amt['op']} ?")
        params.append(amt["value"])

    w = " AND ".join(where)
    intent = plan.get("intent", "total")

    if intent == "total":
        sql = f"SELECT {m_sql} AS metric_value FROM items WHERE {w}"
    elif intent == "by_month":
        sql = (
            f"SELECT substr(purchase_date, 1, 7) AS month, {m_sql} AS metric_value "
            f"FROM items WHERE {w} "
            f"GROUP BY month ORDER BY month"
        )
    elif intent == "top_categories":
        topn = max(1, min(int(plan.get("topn") or 5), 20))
        sql = (
            f"SELECT category_english AS category, {m_sql} AS metric_value "
            f"FROM items WHERE {w} "
            f"GROUP BY category_english "
            f"ORDER BY metric_value DESC LIMIT {topn}"
        )
    elif intent == "list_records":
        sql = (
            f"SELECT order_id, category_english, price, purchase_date "
            f"FROM items WHERE {w} "
            f"ORDER BY purchase_date DESC LIMIT 25"
        )
    else:
        sql = f"SELECT {m_sql} AS metric_value FROM items WHERE {w}"

    return sql, params


def execute_template(db_conn: sqlite3.Connection, plan: Dict[str, Any], seller_id: str) -> Dict[str, Any]:
    """Execute a parameterized SQL template against the read-only database."""
    sql, params = plan_sql(plan, seller_id)
    t0 = time.perf_counter()
    cur = db_conn.execute(sql, params)
    raw_rows = cur.fetchall()
    duration_ms = round((time.perf_counter() - t0) * 1000, 2)
    cols = [c[0] for c in cur.description] if cur.description else ["metric_value"]

    intent = plan.get("intent", "total")
    if intent == "total":
        val = raw_rows[0][0] if raw_rows and raw_rows[0] else 0
        return {
            "type": "total",
            "value": val or 0,
            "columns": cols,
            "rows": [list(r) for r in raw_rows],
            "sql": sql,
            "params": params,
            "duration_ms": duration_ms
        }
    elif intent in ("by_month", "top_categories"):
        dict_rows = [{cols[0]: r[0], cols[1]: r[1]} for r in raw_rows]
        return {
            "type": intent,
            "columns": cols,
            "rows": [list(r) for r in raw_rows],
            "dict_rows": dict_rows,
            "sql": sql,
            "params": params,
            "duration_ms": duration_ms
        }
    elif intent == "list_records":
        dict_rows = [dict(zip(cols, r)) for r in raw_rows]
        return {
            "type": "list_records",
            "columns": cols,
            "rows": [list(r) for r in raw_rows],
            "dict_rows": dict_rows,
            "sql": sql,
            "params": params,
            "duration_ms": duration_ms
        }

    val = raw_rows[0][0] if raw_rows and raw_rows[0] else 0
    return {
        "type": "total",
        "value": val or 0,
        "columns": cols,
        "rows": [list(r) for r in raw_rows],
        "sql": sql,
        "params": params,
        "duration_ms": duration_ms
    }
