"""Single source of truth for every threshold, cap and timeout the guardrail uses.

Every value in here is a policy knob, not an implementation detail. Each field carries a comment naming what it
controls and why it was set.

To tune: edit here, run `python3 -m unittest discover -s tests`, then re-run your evaluation benchmarks.
"""
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


def load_dotenv(path: Optional[Path] = None) -> None:
    """Load key-value pairs from .env into os.environ if not already set (standard library only)."""
    candidates = [
        path,
        Path(__file__).resolve().parent.parent / ".env",
        Path(__file__).resolve().parent.parent / ".env.local",
    ]
    for p in candidates:
        if p and p.exists():
            for line in p.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k, v = k.strip(), v.strip().strip("'\"")
                if k and k not in os.environ:
                    os.environ[k] = v
            break


load_dotenv()


@dataclass(frozen=True)
class MatcherThresholds:
    # A phrase→category is accepted only if the token+char match score reaches this floor.
    # Below 0.55 silently-wrong doubles; above 0.7 refusal-rate climbs and coverage drops on typo-fix cases.
    accept_score: float = 0.6

    # Every content word in the phrase must be covered by the matched name(s). "quantum computers" fails coverage
    # for `computers` even though the score is high. 0.999 (not 1.0) allows for a rounding edge; tighten to 1.0 only
    # if a fuzzy test fails.
    coverage_floor: float = 0.999

    # If two candidate categories are within this score, the match is called ambiguous (no answer, ask). 0.15 was
    # chosen from four ambiguous holdout phrases (e.g. "toys / games"); above 0.2 the system falls into wrong bins.
    ambiguity_margin: float = 0.15

    # The `interpret()` API-level gate, used when a caller only wants the "confident" verdict.
    interpret_threshold: float = 0.45

    # A phrase is "close enough" to a category to be clustered in the review queue at this score. Below this the
    # phrase is filed as "no close category" and a reviewer will treat it as vocabulary work.
    cluster_score: float = 0.3

    # Weights inside the match score: token-level dice + char n-gram dice. 60/40 was chosen so a common category
    # word can outweigh a rare misspelling. See matcher.compare().
    token_dice_weight: float = 0.6
    char_dice_weight: float = 0.4


@dataclass(frozen=True)
class SqlCaps:
    # Rows returned by an approved-template query. Templates only ever return a bounded shape (a total, a top-N,
    # or a per-month roll-up), so 100 is a generous ceiling that still fits in one chat bubble.
    template_max_rows: int = 100

    # Rows returned by a free-form model-written SELECT (baseline "Model only" design). Tighter than templates,
    # since the shape is unknown and could be very wide.
    guarded_max_rows: int = 50

    # Hard cap on how long a guarded query is allowed to run before the SQLite progress handler yanks it.
    guarded_query_timeout_s: int = 3

    # How many SQLite VM steps between progress-handler checks. Lower = more granular timeout at a small cost.
    guarded_progress_step: int = 20000


@dataclass(frozen=True)
class LlmCaps:
    # max_tokens per task. These were sized to fit worst-case JSON schemas plus a slack of ~2x.
    max_tokens_fill_date: int = 200         # was 80; too tight if the reply is a full JSON with reasoning
    max_tokens_fill_category: int = 200     # was 120; same reason
    max_tokens_plan: int = 500              # was 400; SQL for a top-N with a WHERE-IN of five categories can hit 400
    max_tokens_summarize: int = 350

    # HTTP timeout for one call to the model provider (whole request, not just headers).
    http_timeout_s: int = 30

    # For OpenAI reasoning models (o1/o3/o4/gpt-5), max_completion_tokens must be larger because
    # the model spends part of the token budget on internal reasoning.
    reasoning_min_completion_tokens: int = 3000


@dataclass(frozen=True)
class InputCaps:
    # Trim inbound chat messages to this length. 300 chars is well over any real question, and stops one input
    # from blowing up an LLM prompt.
    message_max_chars: int = 300


@dataclass(frozen=True)
class Config:
    matcher: MatcherThresholds = field(default_factory=MatcherThresholds)
    sql: SqlCaps = field(default_factory=SqlCaps)
    llm: LlmCaps = field(default_factory=LlmCaps)
    input: InputCaps = field(default_factory=InputCaps)

    # Prompt bytes are hashed into the LLM cache key. Bump this when a prompt's INTENT changes.
    prompt_version: str = "v2"


CONFIG = Config()

# Default dataset and marketing calendar configurations
DEFAULT_TODAY = "2018-09-01"
DATA_MIN_DATE = "2016-01-01"
DATA_MAX_DATE = "2018-12-31"

DEMO_SELLERS = [
    "955fee9216a65b617aa5c0531780ce60",
    "4869f7a5dfa277a7dca6462dcf3b52b2",
    "8b321bb669392f5163d04c59e235e066"
]

METRIC_OPTIONS = [
    ("Number of orders", "orders"),
    ("Revenue", "revenue"),
    ("Items sold", "items sold")
]

DEFAULT_CALENDAR = {
    "black friday 2017": ("2017-11-24", "2017-11-27"),
    "black friday 2016": ("2016-11-25", "2016-11-28"),
    "christmas 2017": ("2017-12-01", "2017-12-25"),
    "cyber monday 2017": ("2017-11-27", "2017-11-27"),
    "festive season": "10-01..12-31",
    "holiday season": "11-15..12-31",
    "summer sale": "06-01..07-31",
    "new year sale": "12-26..01-02",
}
