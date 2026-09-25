"""
The language model, used only for the gaps rules can't fill. Standard library only.

Modes (env GUARDRAIL_LLM):
  auto    (default) replay a recorded answer if one exists, else call the API if ANTHROPIC_API_KEY or OPENAI_API_KEY is set, else 'unavailable'
  live    always call the API (and record the answer)
  replay  only replay recorded answers
  off     never call, never replay
Recorded answers live in data/llm_cache.jsonl, keyed by a hash of (model, system, user). A recorded answer is shown as
RECORDED in the trace, so nobody mistakes it for a live call. If no answer is available the trace shows the exact prompt
that WOULD have been sent and its estimated size, and never invents a reply.
"""
import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

from .config import CONFIG


def est_tokens(text):
    return max(1, (len(text) + 3) // 4)


DEFAULT_MODELS = {
    "openai": ["gpt-4o-mini", "gpt-4o", "gpt-4.1-mini", "o3-mini", "o1"],
    "anthropic": ["claude-haiku-4-5-20251001", "claude-3-5-sonnet-20241022", "claude-3-5-haiku-20241022"],
}


class LLM:
    def __init__(self, cache_path):
        self.cache_path = Path(cache_path)
        self.mode = os.environ.get("GUARDRAIL_LLM", "auto")
        self.provider = os.environ.get("GUARDRAIL_LLM_PROVIDER", "").lower()

        anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
        openai_key = os.environ.get("OPENAI_API_KEY", "").strip()

        if self.provider == "anthropic" or (not self.provider and anthropic_key and not openai_key):
            self.provider = "anthropic"
            self.key = anthropic_key
            default_model = "claude-haiku-4-5-20251001"
            self.models = list(DEFAULT_MODELS["anthropic"])
        elif self.provider == "openai" or (not self.provider and openai_key):
            self.provider = "openai"
            self.key = openai_key
            default_model = "gpt-4o-mini"
            self.models = list(DEFAULT_MODELS["openai"])
        else:
            self.provider = "openai"
            self.key = openai_key
            default_model = "gpt-4o-mini"
            self.models = list(DEFAULT_MODELS["openai"])

        self.model = os.environ.get("GUARDRAIL_LLM_MODEL", default_model)
        self.bases = {
            "anthropic": os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com").rstrip("/"),
            "openai": os.environ.get("OPENAI_BASE_URL", "https://api.openai.com").rstrip("/")
        }
        self.key_verified = False
        self.cache = {}
        if self.cache_path.exists():
            for line in self.cache_path.read_text().splitlines():
                if line.strip():
                    try:
                        d = json.loads(line)
                        self.cache[d["key"]] = d
                    except Exception:
                        pass

    @property
    def base(self):
        env_key = "ANTHROPIC_BASE_URL" if self.provider == "anthropic" else "OPENAI_BASE_URL"
        default = "https://api.anthropic.com" if self.provider == "anthropic" else "https://api.openai.com"
        return os.environ.get(env_key, default).rstrip("/")

    def set_key(self, key, verified=False, provider=None, models=None):
        if provider:
            self.provider = provider
        self.key = key.strip()
        self.key_verified = verified
        if self.mode == "off" and self.key:
            self.mode = "auto"

        if models:
            self.models = list(models)
        elif not self.models or provider:
            self.models = list(DEFAULT_MODELS.get(self.provider, ["gpt-4o-mini" if self.provider == "openai" else "claude-haiku-4-5-20251001"]))

        # Update model to align with provider
        if self.provider == "openai":
            if not self.model or self.model.startswith("claude") or self.model not in self.models:
                preferred = ["gpt-4o-mini", "gpt-4o", "gpt-4.1-mini", "gpt-4-turbo"]
                self.model = next((m for m in preferred if m in self.models), self.models[0] if self.models else "gpt-4o-mini")
        elif self.provider == "anthropic":
            if not self.model or not self.model.startswith("claude") or self.model not in self.models:
                preferred = ["claude-haiku-4-5-20251001", "claude-3-5-haiku-20241022", "claude-3-5-sonnet-20241022"]
                self.model = next((m for m in preferred if m in self.models), self.models[0] if self.models else "claude-haiku-4-5-20251001")

    def clear_key(self):
        self.key, self.key_verified = "", False

    def set_model(self, model):
        if self.models and model not in self.models:
            self.models.append(model)
        self.model = model

    def _headers(self, key, provider):
        if provider == "openai":
            return {"authorization": "Bearer " + key, "content-type": "application/json"}
        return {"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"}

    def list_models(self, key, provider):
        """The chat models this account can use, from the provider itself. Empty if it can't be fetched."""
        req = urllib.request.Request(self.bases[provider] + "/v1/models", headers=self._headers(key, provider))
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                ids = [m["id"] for m in json.load(r).get("data", [])]
        except Exception:
            return []
        if provider == "openai":
            skip = ("embedding", "audio", "realtime", "transcribe", "tts", "image", "moderation", "whisper", "dall", "search", "codex", "instruct", "computer")
            ids = [i for i in ids if (i.startswith("gpt-") or i[:2] in ("o1", "o3", "o4")) and not any(w in i for w in skip) and not i[-10:].replace("-", "").isdigit()]
        return sorted(set(ids))

    def check_key(self, key, provider="openai"):
        """Asks the provider whether it accepts this key. Returns 'valid', 'invalid' or 'unreachable'. Never returns the key."""
        if provider == "openai":
            req = urllib.request.Request(self.bases["openai"] + "/v1/models", headers=self._headers(key, "openai"))
        else:
            body = {"model": "claude-3-5-haiku-20241022", "max_tokens": 1, "messages": [{"role": "user", "content": "hi"}]}
            req = urllib.request.Request(self.bases["anthropic"] + "/v1/messages", data=json.dumps(body).encode(), method="POST", headers=self._headers(key, "anthropic"))
        try:
            with urllib.request.urlopen(req, timeout=10):
                return "valid"
        except urllib.error.HTTPError as e:
            return "invalid" if e.code in (401, 403) else "valid" if e.code in (400, 429) else "unreachable"
        except Exception:
            return "unreachable"

    def status(self):
        live = self.mode in ("auto", "live") and bool(self.key)
        return {"mode": self.mode, "live_available": live, "provider": self.provider, "model": self.model, "models": self.models,
                "recorded_answers": len(self.cache), "key_set": bool(self.key), "key_verified": self.key_verified}

    def _key(self, system, user, temperature=0, schema=None):
        # Include CONFIG.prompt_version and the schema (if any) so a prompt change or a schema tightening invalidates
        # every previously recorded answer for the affected task.
        parts = [CONFIG.prompt_version, self.model, system, user, schema] + ([temperature] if temperature else [])
        return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()

    def complete(self, task, system, user, max_tokens=None, temperature=0, schema=None):
        """Call the model with provider-enforced structured output when `schema` is given.

        `schema` is a JSON Schema for the desired output. On Anthropic we route it through a single-tool call
        (`tool_use`). On OpenAI we use `response_format: json_schema` with `strict: true`. In both cases the returned
        `text` is the JSON payload as a string, so callers can `json.loads(...)` it without regex fishing.

        Unknown provider or model? We fall back to plain text and the caller runs `parse_json`.
        """
        if max_tokens is None:
            max_tokens = CONFIG.llm.max_tokens_plan
        k = self._key(system, user, temperature, schema)
        prompt_tokens = est_tokens(system) + est_tokens(user) + (est_tokens(json.dumps(schema)) if schema else 0)
        base = {"task": task, "system": system, "user": user, "model": self.model, "prompt_tokens_est": prompt_tokens, "schema": schema}
        if self.mode in ("auto", "replay") and k in self.cache:
            d = self.cache[k]
            return {**base, "text": d["text"], "tokens_in": d["tokens_in"], "tokens_out": d["tokens_out"], "source": "recorded"}
        if self.mode in ("auto", "live") and self.key:
            if self.provider == "openai":
                reasoning = self.model.startswith(("o1", "o3", "o4", "gpt-5"))
                body = {
                    "model": self.model,
                    "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]
                }
                if reasoning:
                    body["max_completion_tokens"] = max(max_tokens, CONFIG.llm.reasoning_min_completion_tokens)
                else:
                    body["max_tokens"] = max_tokens
                    body["temperature"] = temperature
                if schema:
                    body["response_format"] = {
                        "type": "json_schema",
                        "json_schema": {"name": task, "schema": schema, "strict": True}
                    }
                url = self.base + "/v1/chat/completions"
            else:
                body = {"model": self.model, "max_tokens": max_tokens, "temperature": temperature, "system": system,
                        "messages": [{"role": "user", "content": user}]}
                if schema:
                    body["tools"] = [{"name": task, "description": "Return the answer as JSON matching this schema.", "input_schema": schema}]
                    body["tool_choice"] = {"type": "tool", "name": task}
                url = self.base + "/v1/messages"
            req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST", headers=self._headers(self.key, self.provider))
            resp = None
            last_err = None
            max_retries = 2
            for attempt in range(max_retries + 1):
                try:
                    with urllib.request.urlopen(req, timeout=CONFIG.llm.http_timeout_s) as r:
                        resp = json.load(r)
                        break
                except urllib.error.HTTPError as e:
                    try:
                        err_body = e.read().decode("utf-8")
                        err_json = json.loads(err_body)
                        err_msg = err_json.get("error", {}).get("message") or err_body
                    except Exception:
                        err_msg = str(e)
                    last_err = f"HTTP {e.code}: {err_msg}"
                    if e.code in (429, 500, 502, 503, 504) and attempt < max_retries:
                        time.sleep(0.1 * (2 ** attempt))
                        continue
                    break
                except Exception as e:
                    last_err = str(e)
                    break
            if resp is None:
                return {**base, "text": None, "tokens_in": prompt_tokens, "tokens_out": 0, "source": "error", "error": f"{last_err}"[:300]}
            u = resp.get("usage", {})
            if self.provider == "openai":
                text = (resp["choices"][0]["message"].get("content") or "")
                tin, tout = u.get("prompt_tokens", prompt_tokens), u.get("completion_tokens", est_tokens(text))
            else:
                # Anthropic: when tool_use is forced, content[0] is {type: "tool_use", name, input: <dict>}.
                text = ""
                for block in resp.get("content", []):
                    if block.get("type") == "tool_use" and block.get("input") is not None:
                        text = json.dumps(block["input"])
                        break
                    if block.get("type") == "text":
                        text = block.get("text", "")
                        break
                if not text and resp.get("content") and "text" in resp["content"][0]:  # older test-double shape
                    text = resp["content"][0]["text"]
                tin, tout = u.get("input_tokens", prompt_tokens), u.get("output_tokens", est_tokens(text))
            rec = {"key": k, "task": task, "model": self.model, "system": system, "user": user, "text": text,
                    "tokens_in": tin, "tokens_out": tout,
                    "ts": time.strftime("%Y-%m-%d %H:%M:%S")}
            self.cache[k] = rec
            with open(self.cache_path, "a") as f:
                f.write(json.dumps(rec) + "\n")
            return {**base, "text": text, "tokens_in": rec["tokens_in"], "tokens_out": rec["tokens_out"], "source": "live"}
        return {**base, "text": None, "tokens_in": prompt_tokens, "tokens_out": 0, "source": "unavailable"}


def parse_json(text):
    """Pull the first JSON object out of a model reply; returns None if there isn't a clean one."""
    if not text:
        return None
    try:
        return json.loads(text[text.index("{"): text.rindex("}") + 1])
    except (ValueError, json.JSONDecodeError):
        return None
