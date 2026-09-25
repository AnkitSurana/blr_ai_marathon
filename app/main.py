"""Local web application for the Retrieval-as-a-Guardrail system.

Standard library only. Run from the project root:

    python3 -m app.main                # open http://localhost:8000
    python3 -m app.main --port 9000

The app loads rules from canonical/ on startup. See canonical/README.md.
"""
import argparse
import hashlib
import json
import mimetypes
import os
import sys
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# Support both `python3 -m app.main` (package import) and `python3 app/main.py` (script mode).
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from app import Engine
    from app.dates import parse_dates
    from app.engine import TODAY
else:
    from . import Engine
    from .dates import parse_dates
    from .engine import TODAY

ROOT = Path(__file__).resolve().parent.parent
UI = ROOT / "ui"
GAUNTLET_PATH = ROOT / "data" / "gauntlet.json"
engine = None
DECK = None


class H(BaseHTTPRequestHandler):
    def _send(self, code, obj=None, raw=None, ctype="application/json"):
        body = raw if raw is not None else json.dumps(obj, default=str).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if self.path.startswith("/api/info"):
            self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass

    def do_GET(self):
        p = self.path.split("?")[0]
        routes = {"/api/info": engine.info, "/api/sellers": engine.sellers, "/api/categories": engine.categories,
                  "/api/queue": engine.queue, "/api/audit": engine.audit_tail}
        if p in routes:
            return self._send(200, routes[p]())
        if p == "/api/gauntlet":
            return self._send(200, [self._date_row(g) for g in json.loads(GAUNTLET_PATH.read_text())])
        if p == "/deck" and DECK:
            return self._send(200, raw=DECK.read_bytes(), ctype="text/html; charset=utf-8")
        f = UI / ("index.html" if p == "/" else p.lstrip("/"))
        if f.is_file() and UI in f.resolve().parents:
            return self._send(200, raw=f.read_bytes(), ctype=mimetypes.guess_type(str(f))[0] or "text/plain")
        self._send(404, {"error": "not found"})

    def _date_row(self, g):
        r = parse_dates("orders " + g["phrase"], TODAY)
        got = list(r.iso())
        want = [g["start"], g["end"]]
        expected = "unresolved" if g["set"] == "unresolved" else "resolved"
        ok = (r.status == "unresolved") if g["set"] == "unresolved" else (r.status == "resolved" and got == want)
        return {**g, "status": r.status, "start_got": got[0], "end_got": got[1], "rule": r.rule, "flags": r.flags, "ok": ok, "expected": expected}

    def do_POST(self):
        if self.client_address[0] not in ("127.0.0.1", "::1") or self.headers.get("X-Demo") != "1":
            return self._send(403, {"error": "This endpoint accepts only local browser requests. See CUSTOMIZE.md."})
        try:
            data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            p = self.path
            if p == "/api/key":
                return self._send(200, engine.set_api_key(str(data.get("key", "")), str(data.get("provider", "openai"))))
            if p == "/api/model":
                return self._send(200, engine.set_model(data.get("model")))
            if p == "/api/key/clear":
                engine.clear_api_key()
                return self._send(200, {"ok": True})
            if p == "/api/chat":
                return self._send(200, engine.chat(data["seller_id"], data["message"], data.get("design", "deterministic")))
            if p == "/api/dates":
                return self._send(200, self._date_row({"phrase": str(data["text"])[:120], "start": None, "end": None, "set": "typed"}) | {"ok": None})
            if p == "/api/repeat":
                n, seen = min(int(data.get("n", 1000)), 5000), {}
                for _ in range(n):
                    t = engine.chat(data["seller_id"], data["message"], "deterministic")
                    h = hashlib.sha256(json.dumps([t["route"], t["plan"] if "plan" in t else None, t["result"]["rows"] if t["result"] else None], sort_keys=True).encode()).hexdigest()[:8]
                    seen[h] = seen.get(h, 0) + 1
                return self._send(200, {"runs": n, "distinct": len(seen), "hashes": seen, "route": t["route"], "llm_calls": t["tokens"]["calls"]})
            if p == "/api/approve_category":
                engine.approve_category(data["phrase"], data["category"])
                return self._send(200, {"ok": True})
            if p == "/api/approve_date":
                engine.approve_date(data["phrase"], data["window"])
                return self._send(200, {"ok": True})
            if p == "/api/reset":
                engine.reset()
                return self._send(200, {"ok": True})
            if p == "/api/memory/clear":
                engine.memory.clear(data["seller_id"])
                return self._send(200, {"ok": True})
            self._send(404, {"error": "not found"})
        except (KeyError, ValueError) as e:
            self._send(400, {"error": str(e)})


def main():
    global engine, DECK
    ap = argparse.ArgumentParser(description="Retrieval-as-a-Guardrail local web application.")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--deck", help="Path to a presentation HTML file to serve at /deck (optional)")
    a = ap.parse_args()
    engine = Engine(data_dir=str(ROOT / "data"), db_path=str(ROOT / "data" / "olist_seller.sqlite"))
    if a.deck:
        DECK = Path(a.deck).resolve()
    st = engine.llm.status()
    print("=" * 66)
    print("  Retrieval as a Guardrail: Deterministic Natural Language Engine")
    print("=" * 66)
    print(f"  Model      : {'LIVE (' + st['model'] + ')' if st['live_available'] else 'not available'}")
    print(f"  Recorded   : {st['recorded_answers']} cached answer(s)")
    print(f"  Canonical  : loaded {len(engine.calendar)} calendar entries, "
          f"{sum(len(v['aliases']) for v in engine.vocab.values())} vocabulary aliases")
    print(f"  Today      : {TODAY} (frozen benchmark reference date)")
    print()
    print(f"  Open http://{a.host}:{a.port} in your browser")
    print(f"  Or run: python3 -m scripts.ask 'How many orders did I get in 2017?'")
    print("=" * 66)
    ThreadingHTTPServer((a.host, a.port), H).serve_forever()


if __name__ == "__main__":
    main()
