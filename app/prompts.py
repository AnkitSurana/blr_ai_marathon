"""Prompt templates, JSON schemas, and few-shot examples for LLM slot filling and SQL planning.

All prompt schemas enforce strict structured JSON output so models cannot return free-form text
or malformed shapes.
"""
from typing import Any, Dict, List, Optional


SCHEMA_TEXT = (
    "View my_items(order_id TEXT, category_english TEXT, price REAL, freight_value REAL, order_status TEXT, "
    "purchase_ts TEXT, purchase_date TEXT 'YYYY-MM-DD') = this seller's order lines, one row per item. "
    "It is the ONLY thing you may read. order_status values include delivered, shipped, canceled, unavailable."
)

PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "sql": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "reason": {"type": "string"}
    },
    "required": ["sql", "reason"],
    "additionalProperties": False,
}

FILL_DATE_SCHEMA = {
    "type": "object",
    "properties": {
        "start": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "end": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]}
    },
    "required": ["start", "end", "confidence"],
    "additionalProperties": False,
}

FILL_CATEGORY_SCHEMA = {
    "type": "object",
    "properties": {
        "categories": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]}
    },
    "required": ["categories", "confidence"],
    "additionalProperties": False,
}


# 10 Diverse, Highly Structured Few-Shot Prompting Examples
FEW_SHOT_PLAN_EXAMPLES = (
    "\n\n=== EXAMPLES: Natural Language Queries -> Canonical Slots -> Parameterized SQL ===\n\n"
    "Example 1: Total Order Count in Specific Category & Calendar Year\n"
    "  Query: 'How many beauty orders did I get in 2017?'\n"
    "  Canonical Slots: metric='orders', category=['health_beauty'], date=['2017-01-01', '2017-12-31'], intent='total'\n"
    "  Generated SQL:\n"
    "    SELECT COUNT(DISTINCT order_id) AS value\n"
    "    FROM my_items\n"
    "    WHERE category_english IN ('health_beauty')\n"
    "      AND purchase_date >= '2017-01-01'\n"
    "      AND purchase_date <= '2017-12-31'\n\n"
    "Example 2: Total Revenue in Relative Month Window\n"
    "  Query: 'What was my revenue last month?'\n"
    "  Canonical Slots: metric='revenue', date=['2018-08-01', '2018-08-31'], intent='total'\n"
    "  Generated SQL:\n"
    "    SELECT ROUND(SUM(price), 2) AS value\n"
    "    FROM my_items\n"
    "    WHERE purchase_date >= '2018-08-01'\n"
    "      AND purchase_date <= '2018-08-31'\n\n"
    "Example 3: Total Unit Items Sold with Price Threshold Filter\n"
    "  Query: 'How many high value items over 300 did I sell in 2017?'\n"
    "  Canonical Slots: metric='items', date=['2017-01-01', '2017-12-31'], filter='price >= 300', intent='total'\n"
    "  Generated SQL:\n"
    "    SELECT COUNT(*) AS value\n"
    "    FROM my_items\n"
    "    WHERE purchase_date >= '2017-01-01'\n"
    "      AND purchase_date <= '2017-12-31'\n"
    "      AND price >= 300\n\n"
    "Example 4: Multi-Category Group Bundle Aggregation\n"
    "  Query: 'Show me total revenue for furniture in 2018'\n"
    "  Canonical Slots: metric='revenue', category=['furniture_bedroom', 'furniture_decor', 'furniture_living_room', 'furniture_mattress_and_upholstery'], date=['2018-01-01', '2018-12-31']\n"
    "  Generated SQL:\n"
    "    SELECT ROUND(SUM(price), 2) AS value\n"
    "    FROM my_items\n"
    "    WHERE category_english IN ('furniture_bedroom', 'furniture_decor', 'furniture_living_room', 'furniture_mattress_and_upholstery')\n"
    "      AND purchase_date >= '2018-01-01'\n"
    "      AND purchase_date <= '2018-12-31'\n\n"
    "Example 5: Top N Categories Ranked by Metric\n"
    "  Query: 'What were my top 5 categories by sales in 2018?'\n"
    "  Canonical Slots: metric='revenue', intent='top_categories', topn=5, date=['2018-01-01', '2018-12-31']\n"
    "  Generated SQL:\n"
    "    SELECT category_english, ROUND(SUM(price), 2) AS value\n"
    "    FROM my_items\n"
    "    WHERE purchase_date >= '2018-01-01'\n"
    "      AND purchase_date <= '2018-12-31'\n"
    "    GROUP BY category_english\n"
    "    ORDER BY value DESC\n"
    "    LIMIT 5\n\n"
    "Example 6: Month-by-Month Rollup Breakdown\n"
    "  Query: 'Monthly revenue for watches in 2017'\n"
    "  Canonical Slots: metric='revenue', category=['watches_gifts'], intent='by_month', date=['2017-01-01', '2017-12-31']\n"
    "  Generated SQL:\n"
    "    SELECT substr(purchase_date, 1, 7) AS month, ROUND(SUM(price), 2) AS value\n"
    "    FROM my_items\n"
    "    WHERE category_english IN ('watches_gifts')\n"
    "      AND purchase_date >= '2017-01-01'\n"
    "      AND purchase_date <= '2017-12-31'\n"
    "    GROUP BY month\n"
    "    ORDER BY month\n\n"
    "Example 7: Individual Order Records Listing\n"
    "  Query: 'List my orders for electronics in 2017'\n"
    "  Canonical Slots: category=['electronics'], intent='list_records', date=['2017-01-01', '2017-12-31']\n"
    "  Generated SQL:\n"
    "    SELECT order_id, category_english, price, purchase_date\n"
    "    FROM my_items\n"
    "    WHERE category_english IN ('electronics')\n"
    "      AND purchase_date >= '2017-01-01'\n"
    "      AND purchase_date <= '2017-12-31'\n"
    "    ORDER BY purchase_date DESC\n"
    "    LIMIT 25\n\n"
    "Example 8: Specific Promotional Calendar Window\n"
    "  Query: 'How many orders did I get during black friday 2017?'\n"
    "  Canonical Slots: metric='orders', date=['2017-11-24', '2017-11-27'], intent='total'\n"
    "  Generated SQL:\n"
    "    SELECT COUNT(DISTINCT order_id) AS value\n"
    "    FROM my_items\n"
    "    WHERE purchase_date >= '2017-11-24'\n"
    "      AND purchase_date <= '2017-11-27'\n\n"
    "Example 9: Year-over-Year Single Period Baseline\n"
    "  Query: 'How did my revenue do in Q1 2018?'\n"
    "  Canonical Slots: metric='revenue', date=['2018-01-01', '2018-03-31'], intent='total'\n"
    "  Generated SQL:\n"
    "    SELECT ROUND(SUM(price), 2) AS value\n"
    "    FROM my_items\n"
    "    WHERE purchase_date >= '2018-01-01'\n"
    "      AND purchase_date <= '2018-03-31'\n\n"
    "Example 10: Non-Existent Entity or Out-of-Scope Query\n"
    "  Query: 'What were my sales for quantum teleporters in 2018?'\n"
    "  Canonical Slots: category=None (unknown entity)\n"
    "  Generated SQL: null (Reason: 'No product category exists for quantum teleporters')"
)


def build_fill_date_prompt(today_iso: str, question: str, phrase: str) -> tuple[str, str]:
    """Build the system and user prompt for resolving an unparsed time phrase."""
    system = (
        f"You resolve natural language time phrases to inclusive ISO date ranges (YYYY-MM-DD).\n"
        f"Today's date is {today_iso}. The account uses day/month/year order (Brazil).\n"
        "If the phrase cannot be mapped to a definite date window, return null for start and end with confidence 'low'.\n\n"
        "Examples:\n"
        "  Phrase 'last month'              -> {\"start\":\"2018-08-01\",\"end\":\"2018-08-31\",\"confidence\":\"high\"}\n"
        "  Phrase 'last quarter'            -> {\"start\":\"2018-04-01\",\"end\":\"2018-06-30\",\"confidence\":\"high\"}\n"
        "  Phrase '03/04/2018'              -> {\"start\":\"2018-04-03\",\"end\":\"2018-04-03\",\"confidence\":\"high\"} (day/month/year)\n"
        "  Phrase 'the festive season'      -> {\"start\":\"2017-10-01\",\"end\":\"2017-12-31\",\"confidence\":\"medium\"}\n"
        "  Phrase 'when sales were high'    -> {\"start\":null,\"end\":null,\"confidence\":\"low\"}\n"
        "  Phrase 'recently'                -> {\"start\":null,\"end\":null,\"confidence\":\"low\"}"
    )
    user = f"Question: {question}\nTime phrase the rules could not read: {phrase}"
    return system, user


def build_fill_category_prompt(question: str, words: List[str], shortlist: List[str]) -> tuple[str, str]:
    """Build the system and user prompt for mapping unrecognized category terms against a shortlist."""
    system = (
        "You map natural language product terms to matching categories using ONLY names from the provided shortlist.\n"
        "Select 1 to 3 relevant categories. If no category clearly fits, return an empty list with confidence 'low'.\n\n"
        "Examples:\n"
        "  Input: 'dog food' | Shortlist includes 'pet_shop' -> {\"categories\":[\"pet_shop\"],\"confidence\":\"high\"}\n"
        "  Input: 'sneakers' | Shortlist includes 'fashion_shoes' -> {\"categories\":[\"fashion_shoes\"],\"confidence\":\"high\"}\n"
        "  Input: 'living room sofa' | Shortlist includes 'furniture_living_room' -> {\"categories\":[\"furniture_living_room\"],\"confidence\":\"high\"}\n"
        "  Input: 'spaceship parts' | Shortlist has no match -> {\"categories\":[],\"confidence\":\"low\"}"
    )
    user = f"Question: {question}\nWords the rules could not match: {' '.join(words)}\nCategories to choose from (shortlist): {', '.join(shortlist)}"
    return system, user


def build_plan_prompt(today_iso: str, question: str, categories: List[str], big: bool = False) -> tuple[str, str]:
    """Build system and user prompt for generating parameterized SQL plans with few-shot examples."""
    rules = ""
    if big:
        rules = (
            "\nValid category_english values: " + ", ".join(categories) + ".\n"
            "Date rules: 'last month' = previous calendar month; 'last quarter' = previous calendar quarter; 'last N months' = the N complete months before this one; "
            "'this year' = calendar year to date; numeric dates a/b/yyyy are day/month/year. 'orders' = COUNT(DISTINCT order_id); 'revenue' = ROUND(SUM(price), 2); 'items' = COUNT(*).\n"
            "Business rule (ALWAYS apply): every query MUST include `AND order_status NOT IN ('canceled', 'unavailable')` in its WHERE clause. Canceled and unavailable orders never count toward any metric. Do not omit this filter under any circumstances."
        )
    system = (
        f"You write one SQLite SELECT for a seller-portal chatbot. Today's date is {today_iso}.\n"
        f"{SCHEMA_TEXT}{rules}{FEW_SHOT_PLAN_EXAMPLES}\n"
        "Return the SQL in the sql field, or null with a one-sentence reason if it cannot be answered from my_items."
    )
    user = f"Question: {question}"
    return system, user
