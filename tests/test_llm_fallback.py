"""Tests for Route B LLM slot-filling, structured schema validation, error recovery, and offline replay."""
import http.server
import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.engine import DEMO_SELLERS, TODAY, Engine
from app.llm import LLM

SELLER_ID = DEMO_SELLERS[0]


class _MockModelServer(http.server.BaseHTTPRequestHandler):
    mock_responses = {}

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        user_msg = body["messages"][0]["content"]
        task = "fill_date" if "Time phrase" in user_msg else "fill_category"
        text = _MockModelServer.mock_responses.get(task, "{}")
        output = json.dumps({"content": [{"text": text}], "usage": {"input_tokens": 80, "output_tokens": 15}}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(output)))
        self.end_headers()
        self.wfile.write(output)

    def log_message(self, *args):
        pass


class TestLLMFallbackAndValidation(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = Engine(data_dir=self.tmp.name, canonical_dir=Path(self.tmp.name) / "canonical")

    def tearDown(self):
        self.engine.ro.close()
        self.tmp.cleanup()

    def _start_mock_server(self, **responses):
        _MockModelServer.mock_responses = responses
        server = http.server.HTTPServer(("127.0.0.1", 0), _MockModelServer)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        os.environ["ANTHROPIC_API_KEY"] = "mock_key"
        os.environ["ANTHROPIC_BASE_URL"] = f"http://127.0.0.1:{server.server_port}"
        self.addCleanup(lambda: [os.environ.pop(k, None) for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL")])
        self.engine.llm = LLM(Path(self.tmp.name) / "cache.jsonl")
        self.engine.llm.mode = "live"

    def test_route_b_fills_unresolved_category_slot(self):
        """Unresolved category slot is filled by model, verified by code, and template runs."""
        self._start_mock_server(fill_category=json.dumps({"categories": ["pet_shop"]}))
        response = self.engine.chat(SELLER_ID, "how many puppy chow orders did I get in 2017?")
        self.assertEqual(response["initial_route"], "B")
        self.assertEqual(response["plan"]["categories"], ["pet_shop"])
        self.assertEqual(response["outcome"], "answered")

    def test_route_b_rejects_hallucinated_category(self):
        """If model returns a non-existent category, validator rejects it and safely falls to Route C."""
        self._start_mock_server(fill_category=json.dumps({"categories": ["non_existent_fake_category"]}))
        response = self.engine.chat(SELLER_ID, "how many puppy chow orders did I get in 2017?")
        self.assertEqual(response["route"], "C")

    def test_offline_cache_replay(self):
        """Recorded live answers can be replayed offline without making network calls."""
        self._start_mock_server(fill_category=json.dumps({"categories": ["pet_shop"]}))
        # Call 1: Live call is recorded to cache
        self.engine.chat(SELLER_ID, "how many puppy chow orders did I get in 2017?")
        
        # Switch to offline replay mode
        self.engine.llm = LLM(Path(self.tmp.name) / "cache.jsonl")
        self.engine.llm.mode = "replay"
        os.environ.pop("ANTHROPIC_API_KEY", None)
        
        # Call 2: Replays cached output
        response = self.engine.chat(SELLER_ID, "how many puppy chow orders did I get in 2017?")
        self.assertEqual(response["llm_calls"][0]["source"], "recorded")


if __name__ == "__main__":
    unittest.main()
