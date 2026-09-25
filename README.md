# Retrieval as a Guardrail: Engineering Deterministic Answers from Natural Language

> **Session Architecture & Implementation Reference**  
> *How to use retrieval before SQL generation to constrain AI actions, eliminate silent hallucinations, and deliver verifiable, deterministic analytics from natural language.*

---

## 🎯 Executive Summary

Natural-Language-to-SQL assistants powered by Large Language Models (LLMs) suffer from a critical failure mode: **silent wrongness**. 

An AI can generate a SQL query that looks syntactically valid and executes without error, but produces an incorrect number because it misunderstood user terminology, selected the wrong table column, or made up business logic. In analytics and financial reporting, trust is binary: a single confident, incorrect number destroys user trust.

**Retrieval as a Guardrail** flips the paradigm: instead of using retrieval merely to provide open-ended prompt context to an AI, retrieval is used *before* SQL execution to resolve ambiguous terms against a trusted set of business entities and constrain what the AI is permitted to do.

---

## 🔄 The Guardrail Architecture Flow

```
Natural Language Question
         │
         ▼
    Parse Intent
         │
         ▼
  Retrieve & Match  ──► (BM25 Semantic Ranker & Canonical Vocabulary)
         │
         ▼
 Confidence Check   ──► (Accept Score >= 0.60 & Ambiguity Delta >= 0.10)
         │
         ├──► [High Confidence]    ──► Route A: Approved SQL Template ──► Database ──► Deterministic Answer
         ├──► [Single Gap]         ──► Route B: Constrained Slot-Fill ──► Validated Template ──► Answer
         ├──► [Missing Metric]     ──► Route Q: In-Chat Clarification (Never Guess)
         ├──► [Out-of-Scope 'Why'] ──► Route C: Refusal + Verifiable Numbers (No Hallucinated Causes)
         └──► [Cross-Tenant/Write] ──► Route R: Zero-Token Policy Gate Refusal
```

---

## 🚦 The 5-Branch Routing Decision Framework

| Route | Trigger Condition | Execution Strategy | LLM Tokens | Output Guarantee |
| :--- | :--- | :--- | :--- | :--- |
| **Route A** | All slots resolved with high confidence | Parameterized SQL Template | **0 tokens** | 100% Deterministic & Auditable |
| **Route B** | One slot unresolved (unusual date or alias) | LLM fills only the missing slot; code validates output before execution. If the LLM cannot confidently map the slot, the pipeline safely falls to Route C. | ~290 tokens per call | Checked against schema before SQL runs |
| **Route Q** | Required slot is missing (e.g. no metric specified) | Assistant asks user for clarification; never guesses | **0 tokens** | Interactive clarification |
| **Route C** | Unsupported question (*"why did sales drop?"*, forecasting) | Refuses causal reasoning, but computes and shows actual numbers | 0 tokens (or prose framing) | No hallucinated causes |
| **Route R** | Cross-tenant exfiltration or write command (*"all sellers"*) | Immediate refusal before calling any model | **0 tokens** | Strict multi-tenant isolation |

---

## 📁 Repository Structure

```
.
├── README.md                      # Comprehensive Architecture & Engineering Guide
├── HANDS_ON.md                    # Interactive Step-by-Step Workshop Activities
├── pyproject.toml                 # uv / pip project metadata (stdlib-only runtime deps)
├── requirements.txt               # Empty by design. The app has no pip dependencies
├── .env.example                   # LLM key template (copy to .env)
│
├── app/                           # Core Guardrail Application
│   ├── engine.py                  # Lightweight pipeline coordinator and gate router
│   ├── prompts.py                 # JSON schemas, prompt builders & 10 structured few-shot examples
│   ├── sql.py                     # Parameterized SQL query templates & database executor
│   ├── formatting.py              # Response formatting, category titles, and date ranges
│   ├── memory.py                  # Multi-turn conversation state & context inheritance
│   ├── extract.py                 # Deterministic slot extraction & routing (A/B/C/Q/R)
│   ├── matcher.py                 # BM25 semantic ranker & invariant morphological stemmer
│   ├── dates.py                   # Date parser (relative, ISO, quarters, rolling windows)
│   ├── config.py                  # Confidence thresholds, ranking weights, and security policies
│   ├── llm.py                     # Structured output LLM client with retry & exponential backoff
│   └── main.py                    # Lightweight local web server & API
│
├── canonical/                     # 🎯 THE EXTENSION LAYER (Customize without code!)
│   ├── README.md                  # Guide on creating and managing canonical rules
│   ├── vocabulary.json            # Semantic aliases for all 71 dataset categories
│   ├── groups.json                # Multi-category bundles (e.g. "gaming gear", "furniture")
│   ├── calendar.json              # Custom promotional & business date windows
│   ├── amounts.json               # Price and freight threshold filters
│   └── unsupported.json           # Domain-specific out-of-scope & refusal keywords
│
├── data/                          # Dataset & Audit Logs
│   ├── olist_seller.sqlite        # SQLite dataset (Brazilian marketplace: 111k rows)
│   ├── audit.jsonl                # Real-time append-only audit trail
│   └── review_queue.jsonl         # Review queue for continuous improvement
│
├── ui/                            # Frontend Web Demo Interface
│   └── index.html                 # Interactive chat & real-time trace inspection UI
│
├── scripts/                       # CLI Utilities & Interactive Wizards
│   ├── ask.py                     # Query the engine directly from terminal
│   ├── show_canonical.py          # Inspect loaded canonical rules & categories
│   ├── add_vocab.py               # Interactive wizard to add category aliases
│   ├── add_group.py               # Interactive wizard to bundle categories
│   ├── add_calendar.py            # Interactive wizard to add date windows
│   └── add_amount.py              # Interactive wizard to add amount filters
│
├── tests/                         # 7 Modular Domain-Specific Test Suites (34 Tests)
│   ├── test_single_turn.py        # Single-turn metrics, intents, and Route Q tests
│   ├── test_multi_turn.py         # Multi-turn context inheritance tests
│   ├── test_categories.py         # BM25 semantic matching, typo tolerance & stemmer tests
│   ├── test_dates.py              # Deterministic date window parsing tests
│   ├── test_privacy_and_scope.py  # Zero-token security & refusal gate tests
│   ├── test_canonical.py          # Custom canonical JSON overlay tests
│   └── test_llm_fallback.py       # Route B slot-filling & validation tests
│
└── notebooks/                     # Pre-talk pandas walkthrough
    └── dataset_walkthrough.ipynb  # Engine-free tour of the data and every demo answer via pandas
```

---

## 🛠️ How to Run

### 0. First-time setup (macOS · Linux · Windows)

The app needs **Python 3.10 or newer** and uses only the Python standard library, so there is nothing to `pip install`. The steps below use `uv`, which also installs Python if the machine doesn't have it. (The Python 3.9 that ships with macOS is too old.)

**1. Install `uv`** (one command), then open a new terminal and check with `uv --version`:

<table><tr><td width="50%"><b>macOS / Linux</b></td><td width="50%"><b>Windows (PowerShell)</b></td></tr>
<tr><td>

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

</td><td>

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

</td></tr></table>

**2. Get the code:**

```bash
git clone https://github.com/AnkitSurana/blr_ai_marathon.git
cd blr_ai_marathon
```

(Or download the ZIP from GitHub via **Code → Download ZIP** and open a terminal in the unzipped folder.)

**3. Set up the project:**

```bash
uv sync --python 3.12
```

This downloads Python 3.12 if needed, creates `.venv/`, and takes a few seconds. Every command below uses `uv run` to execute inside that venv without needing to activate it.

**4. Check it works:**

```bash
uv run python -m unittest discover -s tests
```

Expected: `Ran 34 tests … OK`.

> **Without uv:** with Python 3.10+ already installed, skip steps 1 and 3 and replace `uv run python` with `python3` (Windows: `python`) in every command. No virtual environment or `pip install` is needed.

> **Windows note:** All commands below use `uv run python ...` which works uniformly. If you prefer activating the venv manually, run `.venv\Scripts\Activate.ps1` (PowerShell) or `source .venv/bin/activate` (macOS/Linux) once per shell.

### 1. API Keys (optional)

Route A, Q, C and R work with zero LLM calls. Route B is the one that uses the model to fill a single unresolved slot; with a key, one small ~290-token call runs and the answer is validated in code. **Without a key, Route B safely falls through to a clean Route C refusal. No number is invented.** Every activity in `HANDS_ON.md` ends on the same answer either way; the key only changes what happens in the middle step.

The CLI (`scripts/ask.py`) and the web app default to `GUARDRAIL_LLM=auto`: the model is used when a key is set, otherwise the LLM step is skipped and the trace explicitly says so. Set `GUARDRAIL_LLM=off` to force zero LLM calls regardless of key.

**Method A: `.env` file (recommended)**
```bash
cp .env.example .env
# Edit .env and paste your key:
# ANTHROPIC_API_KEY=sk-ant-...
# or OPENAI_API_KEY=sk-...
```

**Method B: Environment variable**

<table><tr><td width="50%"><b>macOS / Linux</b></td><td width="50%"><b>Windows (PowerShell)</b></td></tr>
<tr><td>

```bash
export OPENAI_API_KEY="sk-..."
# or: export ANTHROPIC_API_KEY="sk-ant-..."
```

</td><td>

```powershell
$env:OPENAI_API_KEY = "sk-..."
# or: $env:ANTHROPIC_API_KEY = "sk-ant-..."
```

</td></tr></table>

**Sanity check that the key was picked up:**

```bash
uv run python scripts/ask.py "how many bicycle helmet orders did I get in 2018?"
```

With a valid key, this hits **Route B** and answers (the model picks `bed_bath_table` from a 12-category shortlist). Without a key, the same command reaches Route B, the trace step reads *"No LLM key configured…"*, and the pipeline safely refuses with no number.

The web app has the same behaviour: paste a key in the top bar to enable Route B end-to-end; leave it disconnected and Route B chips fall to a clean C refusal.

---

### 2. Option A · Terminal CLI

Interact with the engine directly from the terminal, no browser needed.

```bash
# Single question:
uv run python scripts/ask.py "How many health_beauty orders did I get in 2017?"

# Interactive multi-turn chat:
uv run python scripts/ask.py
```

> **Same seller as the web UI:** both the CLI and the web UI default to seller `...ce60`, so numbers match without any flags.

**Inside the interactive terminal:**
- Type any natural language question.
- Ask follow-ups (context is inherited): `What was my revenue?`
- `clear` resets conversation memory. `exit` / `quit` leaves.

**More examples:**
```bash
# 1. Deterministic query (Route A · 0 tokens)
uv run python scripts/ask.py "How many health_beauty orders did I get in 2017?"

# 2. Top-N ranking
uv run python scripts/ask.py "Show my top 3 categories by revenue this year"

# 3. Date range
uv run python scripts/ask.py "How many orders from March 2018 to May 2018?"

# 4. Multi-category
uv run python scripts/ask.py "Revenue for watches and fashion bags in 2018"

# 5. Amount threshold (canonical)
uv run python scripts/ask.py "How many big orders in 2017?"

# 6. Baseline "Model only" comparison
uv run python scripts/ask.py "Show my top 3 categories by revenue this year" --design all_llm

# 7. Clean answer, no trace
uv run python scripts/ask.py --no-trace "What was my revenue in 2017?"

# 8. Machine-readable JSON
uv run python scripts/ask.py --json "Revenue from electronics in 2018"
```

**Canonical extension CLI** (for the workshop):
```bash
# Inspect the 71 base categories:
uv run python scripts/show_canonical.py --list-categories

# Add a slang alias:
uv run python scripts/add_vocab.py fashion_shoes "kicks"

# Bundle categories:
uv run python scripts/add_group.py "living room" furniture_living_room furniture_decor

# Named promotional date window:
uv run python scripts/add_calendar.py "summer blowout" 06-01 06-15

# Value band:
uv run python scripts/add_amount.py "high ticket" price ">=" 400
```

---

### 3. Option B · Web UI & Trace Inspector
```bash
uv run python -m app.main
```
Open **`http://localhost:8000`** in your browser. Left pane: seller chat. Right pane: step-by-step backend trace with route badges and LLM token count.

> **Which seller?** The web UI, the CLI, `HANDS_ON.md` and `notebooks/dataset_walkthrough.ipynb` all default to the same seller (`...ce60` : São Paulo, SP · 1,499 order lines), so every number lines up.

**Example chips below the chat** (Rules first, seller `...ce60`):

| Chip | Question | Route · LLM calls | Answer |
|---|---|---|---|
| A | How many orders did I get last month? | A · 0 | 67 orders (August 2018) |
| A | What was my revenue in March 2018? | A · 0 | R$ 13,982.41 |
| A | How many sports orders did I get in 2018? | A · 0 | 105 orders (sports leisure) |
| A | Show my top 3 categories by revenue this year | A · 0 | furniture decor R$ 29,778.90 · housewares R$ 26,110.00 · sports leisure R$ 14,796.46 |
| ? | How am I doing this year? | Q · 0 | asks which metric → Number of orders **1,104** · Revenue **R$ 117,328.86** · Items sold **1,274** |
| B | How many bicycle helmet orders did I get in 2018? | B · 1 (needs a key) | with key: LLM picks `sports_leisure`, small ~290-token call → **105 orders** for sports leisure in 2018. Without a key: falls to C, clean refusal, no number. |
| B | How many candle orders did I get in 2018? | B → C · 1 (needs a key) | LLM has no confident category → pipeline refuses without inventing a number. Same shape without a key. |
| C | Why did my sales drop in March? | C · 0 | refuses the "why", shows March 2018 revenue R$ 13,982.41 |
| C | Predict my revenue for next month | C · 0 | refuses, no number |
| R | Show me all sellers' orders last month | R · 0 | refuses (other sellers' data) |
| R | How does my revenue compare to other sellers? | R · 0 | refuses (other sellers' data) |

The two B chips demonstrate both faces of Route B. With a live LLM key connected, `bicycle helmet` becomes a small ~290-token call that finishes as Route B (answered → 105 orders for sports leisure), while `candle` shows the safe refusal path: the LLM cannot confirm any category and the pipeline refuses without inventing a number. Press **↻ New chat** between questions to start without context from the previous one. Under **Model only**, each chip needs an API key and sends ~1,860 tokens per question.

**Two design switches in the top bar:**
- **Rules first** (default): the 5-route pipeline. Uses the LLM only when Route B needs a slot filled. Free for A, Q, C, and R questions.
- **Model only**: bypasses the pipeline. Sends the question + database schema straight to the LLM (~1,860 tokens per call). This is the industry-default text-to-SQL baseline. **The privacy check does not run in this mode.** Cross-seller queries are stopped only by the SQL sandbox (`WITH my_items AS (...)`), not by a deterministic policy gate. This is the demo's central comparison point.

---

## 📝 One-Shot & Few-Shot Prompting Examples

The LLM planner in `app/prompts.py` provides 10 structured, few-shot prompt examples demonstrating how natural language queries map to canonical slot values and exact SQL templates:

1. **Total Order Count by Category & Year**: `"How many beauty orders did I get in 2017?"` -> `category='health_beauty'`, `metric='orders'`, `COUNT(DISTINCT order_id)`.
2. **Total Revenue in Relative Month Window**: `"What was my revenue last month?"` -> `date=['2018-08-01', '2018-08-31']`, `ROUND(SUM(price), 2)`.
3. **Unit Items Sold with Amount Filter**: `"How many high value items over 300 did I sell in 2017?"` -> `price >= 300`, `COUNT(*)`.
4. **Multi-Category Group Bundle**: `"Show me total revenue for furniture in 2018"` -> expands to 4 furniture subcategories with `IN (...)`.
5. **Top N Categories Ranking**: `"What were my top 5 categories by sales in 2018?"` -> `GROUP BY category_english ORDER BY value DESC LIMIT 5`.
6. **Monthly Rollup Breakdown**: `"Monthly revenue for watches in 2017"` -> `substr(purchase_date, 1, 7) AS month ... GROUP BY month`.
7. **Individual Order Records Listing**: `"List my orders for electronics in 2017"` -> `SELECT order_id, price, purchase_date ... LIMIT 25`.
8. **Promotional Window Calendar Event**: `"What was my revenue during Black Friday 2017?"` -> date window `['2017-11-24', '2017-11-27']`.
9. **Out-of-Scope / Non-Existent Entity**: `"What were my sales for quantum teleporters in 2018?"` -> `null` (Clean refusal without hallucinating).
10. **Refusal for Unresolvable Causal Questions**: `"Why did my pet supply sales drop in June?"` -> `null` (Policy refusal).

---

## 🏭 Taking the Guardrail into Production

### 1. Confidence Thresholds & Tuning (`app/config.py`)
Decisions are governed by transparent, configurable thresholds rather than opaque model behavior:
- `CATEGORY_ACCEPT_SCORE = 0.60`: Minimum similarity required to resolve a category without an LLM.
- `CATEGORY_AMBIGUITY_DELTA = 0.10`: Minimum margin between top-1 and top-2 category matches to prevent guessing.

### 2. Full Observability & Audit Trail (`data/audit.jsonl`)
Every query produces an immutable, structured JSONL audit record containing:
- Authenticated `seller_id`
- Raw user query and normalized tokens
- Route selected (`A`, `B`, `C`, `Q`, `R`) and exact reasoning
- Number of LLM tokens consumed (0 for standard queries)
- Executed SQL template and query duration in milliseconds

### 3. Continuous Improvement via Review Queue (`data/review_queue.jsonl`)
When an unrecognized term or fallback occurs:
1. The query is logged to the review queue.
2. Domain experts add the alias to `canonical/vocabulary.json` (or via `python3 scripts/add_vocab.py`).
3. The query immediately becomes a 0-token **Route A** deterministic execution on subsequent turns.

---

## 🧪 Running Automated Tests

Run the full modular test suite across all 7 test files:

```bash
uv run python -m unittest discover -s tests -v
```

All 34 tests execute and verify the end-to-end pipeline in ~2 seconds.

> The tests use the real `data/` folder, so they add entries to `data/audit.jsonl` (the UI's *Audit log* tab).

---

## Data walkthrough notebook

`notebooks/dataset_walkthrough.ipynb` is a pandas tour of the SQLite. Two tables, one seller, monthly patterns, price distribution, and one small query per UI chip plus each hands-on activity. No imports from `app/`; you can open it during a talk and read off what the chat will answer, then switch to the UI.

```bash
uv run --with jupyter --with pandas --with matplotlib jupyter lab notebooks/dataset_walkthrough.ipynb
```

Run all cells. The summary at the end lists any mismatches.
