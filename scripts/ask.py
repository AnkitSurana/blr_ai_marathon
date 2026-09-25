"""Ask a question from the CLI, see the full trace and the answer. No browser required.

    python3 -m scripts.ask "How many orders did I get in 2017?"
    python3 -m scripts.ask "revenue in health beauty in March 2018"

By default uses the first seller in the dataset. Override with --seller <32-char hex id>.
Use this to test your canonical additions:

    python3 -m scripts.add_vocab pet_shop "puppy chow"
    python3 -m scripts.ask "how many puppy chow orders did I get in 2017?"
"""
import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
# The CLI defaults to 'auto': the LLM is used only when an API key is set, otherwise the slot
# stays unresolved and the pipeline refuses cleanly. Set GUARDRAIL_LLM=off to force zero LLM calls.
os.environ.setdefault("GUARDRAIL_LLM", "auto")
from app import Engine
from app.engine import DEMO_SELLERS, TODAY


C = {"ok": "\033[32m", "gap": "\033[33m", "warn": "\033[33m", "fail": "\033[31m", "END": "\033[0m",
     "b": "\033[1m", "dim": "\033[2m"}


def col(s, c):
    if os.environ.get("NO_COLOR") or not sys.stdout.isatty():
        return s
    return f"{C.get(c, '')}{s}{C['END']}"


def print_turn(t, question, show_trace=True):
    print()
    print(col("Question:", "b"), question)
    print()
    if show_trace:
        print(col("Execution Trace:", "b"))
        for i, s in enumerate(t["steps"], 1):
            status = col(f"[{s['status']:4}]", s["status"])
            src = col(f"[{s['source']:7}]", "dim")
            print(f"  {i:2d}. {src} {status}  {col(s['name'], 'b')}")
            print(f"       {col(s['detail'], 'dim')}")
        print()

    route = t["route"]
    tokens = t["tokens"]["calls"]
    outcome = t["outcome"]
    hdr = col(f"Route {route}", "b") + f"   ·   outcome: {outcome}   ·   {tokens} LLM call{'' if tokens == 1 else 's'}"
    print(hdr)
    print(col("─" * 60, "dim"))
    print(t["reply"])
    print()


def interactive_loop(engine: Engine, seller: str, show_trace: bool, design: str = "deterministic"):
    print("=" * 60)
    print(col("Retrieval-as-a-Guardrail: Interactive Terminal Chat", "b"))
    print(f"Seller ID: {seller[:8]}... | Today: {TODAY} | Mode: {design}")
    print("Commands: 'exit' to quit, 'clear' to reset conversation memory")
    print("=" * 60)
    print()

    while True:
        try:
            q = input(col("You > ", "b")).strip()
        except (KeyboardInterrupt, EOFError):
            print("\nExiting.")
            break

        if not q:
            continue
        if q.lower() in ("exit", "quit", "q"):
            print("Goodbye!")
            break
        if q.lower() in ("clear", "reset"):
            engine.memory.clear(seller)
            print("Conversation memory cleared.\n")
            continue

        t = engine.chat(seller, q, design=design)
        print_turn(t, q, show_trace=show_trace)


def main():
    ap = argparse.ArgumentParser(description="Ask questions via CLI with full execution trace and deterministic answers.")
    ap.add_argument("question", nargs="?", default=None, help="Natural language question. If omitted, starts interactive chat mode.")
    ap.add_argument("-i", "--interactive", action="store_true", help="Launch interactive multi-turn terminal chat session.")
    ap.add_argument("--seller", default=DEMO_SELLERS[0], help="Seller ID (32 hex chars). Defaults to first demo seller.")
    ap.add_argument("--llm", default=None, choices=["auto", "live", "replay", "off"], help="LLM execution mode (default: auto if API key is present, else off).")
    ap.add_argument("--model", default=None, help="Model name (e.g. claude-haiku-4-5-20251001 or gpt-4.1-mini).")
    ap.add_argument("--api-key", default=None, help="Direct API key override (or use .env file / environment variable).")
    ap.add_argument("--design", default="deterministic", choices=["deterministic", "all_llm"], help="Execution design: deterministic (rules first) or all_llm (model only).")
    ap.add_argument("--no-trace", action="store_true", help="Hide the step-by-step trace and only show final answers.")
    ap.add_argument("--json", action="store_true", help="Print raw JSON trace and plan instead of formatted text.")
    a = ap.parse_args()

    if a.api_key:
        if a.api_key.startswith("sk-ant-"):
            os.environ["ANTHROPIC_API_KEY"] = a.api_key
        else:
            os.environ["OPENAI_API_KEY"] = a.api_key

    llm_mode = a.llm
    if llm_mode is None:
        # 'auto' means: try the cache first (recorded answers replay for free), then the live API if
        # a key is set, otherwise mark the call unavailable and let the pipeline refuse cleanly.
        # This lets pre-recorded workshop cache entries work on machines without a key set.
        llm_mode = os.environ.get("GUARDRAIL_LLM", "auto")

    e = Engine(data_dir=str(ROOT / "data"), db_path=str(ROOT / "data" / "olist_seller.sqlite"), llm_mode=llm_mode)
    if a.model:
        e.llm.model = a.model

    if a.interactive or a.question is None:
        interactive_loop(e, a.seller, show_trace=not a.no_trace, design=a.design)
        return

    t = e.chat(a.seller, a.question, design=a.design)

    if a.json:
        print(json.dumps(t, indent=2, default=str))
        return

    print_turn(t, a.question, show_trace=not a.no_trace)


if __name__ == "__main__":
    main()
