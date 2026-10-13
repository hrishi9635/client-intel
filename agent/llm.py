"""Talks to a free AI model through the standard 'OpenAI-compatible' web API (Groq's free tier by default).

Free-tier care:
 - waits LLM_PAUSE_SECONDS between calls and retries when told to slow down (HTTP 429)
 - keeps every request below LLM_MAX_PROMPT_CHARS so it fits the per-minute token limit
 - counts the tokens used today per model (data/ai_usage.json) and switches to the fallback model,
   or stops, before the daily allowance runs out
"""
import json
import re
import time
from datetime import datetime, timezone

import requests

from .settings import read_json, write_json


class AIError(Exception):
    pass


class BudgetExhausted(AIError):
    pass


class LLM:
    def __init__(self, settings):
        self.base = settings["LLM_BASE_URL"].rstrip("/")
        self.models = [m for m in (settings["LLM_MODEL"], settings.get("LLM_FALLBACK_MODEL")) if m]
        self.key = settings.get("LLM_API_KEY", "")
        self.pause = settings.get("LLM_PAUSE_SECONDS", 0)
        self.daily = settings.get("LLM_DAILY_TOKENS", 180000)
        self.max_chars = settings.get("LLM_MAX_PROMPT_CHARS", 15000)
        self.local = "localhost" in self.base or "127.0.0.1" in self.base
        self.calls = 0
        self.tokens = 0
        self._last = 0.0
        self.exhausted = set()
        self.today = datetime.now(timezone.utc).date().isoformat()
        usage = read_json("ai_usage.json", {})
        self.usage = {self.today: usage.get(self.today, {})}  # keep only today

    def available(self):
        return bool(self.key) or self.local

    def used_today(self, model=None):
        day = self.usage.get(self.today, {})
        return day.get(model, 0) if model else sum(day.values())

    def left_today(self):
        return sum(max(0, self.daily - self.used_today(m)) for m in self.models if m not in self.exhausted)

    def _record(self, model, n):
        day = self.usage.setdefault(self.today, {})
        day[model] = day.get(model, 0) + int(n)
        self.tokens += int(n)
        write_json("ai_usage.json", self.usage)

    def _post(self, model, messages, max_tokens, json_mode, extra):
        body = {"model": model, "messages": messages, "temperature": 0.1, "max_tokens": max_tokens}
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        body.update(extra)
        headers = {"Content-Type": "application/json"}
        if self.key:
            headers["Authorization"] = f"Bearer {self.key}"
        return requests.post(f"{self.base}/chat/completions", headers=headers, json=body, timeout=180)

    def chat_json(self, system, user, max_tokens=2400):
        if len(user) > self.max_chars:  # last-resort trim; callers already size their inputs
            user = user[: self.max_chars - 200] + "\n[...trimmed to fit the free AI limit...]\n" + user[-200:]
        need = (len(system) + len(user)) // 4 + max_tokens
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        for model in self.models:
            if model in self.exhausted or (not self.local and self.used_today(model) + need > self.daily):
                continue
            json_mode = True
            extra = {"reasoning_effort": "low"} if "gpt-oss" in model and not self.local else {}
            for attempt in range(6):
                wait = self.pause - (time.time() - self._last)
                if self._last and wait > 0:
                    time.sleep(wait)
                try:
                    r = self._post(model, messages, max_tokens, json_mode, extra)
                except requests.RequestException as e:
                    if attempt >= 2:
                        raise AIError(f"Could not reach the AI service: {e}") from e
                    time.sleep(10)
                    continue
                self._last = time.time()
                if r.status_code == 200:
                    self.calls += 1
                    data = r.json()
                    used = (data.get("usage") or {}).get("total_tokens") or need
                    self._record(model, used)
                    msg = data["choices"][0]["message"]
                    try:
                        return parse_json(msg.get("content") or "")
                    except AIError:
                        if attempt >= 1:
                            raise
                        continue  # ask once more
                text = r.text[:400]
                low = text.lower()
                if r.status_code == 429:
                    secs = float(r.headers.get("retry-after", 0) or 0) or 20 * (attempt + 1)
                    if "per day" in low or "tpd" in low or "rpd" in low or secs > 300:
                        print(f"      Daily AI allowance used up for {model}; trying the next model")
                        self.exhausted.add(model)
                        break
                    print(f"      AI speed limit reached, waiting {int(min(secs, 120))}s...")
                    time.sleep(min(secs, 120))
                    continue
                if r.status_code == 413 or "too large" in low:
                    # request bigger than the per-minute allowance: shrink it and try again
                    half = len(user) // 2
                    user = user[:half] + "\n[...trimmed...]"
                    messages[1]["content"] = user
                    continue
                if r.status_code in (401, 403):
                    raise AIError("The AI key was refused (refused). Check the LLM_API_KEY secret (see the guide).")
                if r.status_code == 400 and extra and "reasoning" in low:
                    extra = {}
                    continue
                if r.status_code == 400 and json_mode and ("response_format" in low or "json" in low):
                    json_mode = False
                    continue
                if r.status_code in (400, 404) and "model" in low:
                    print(f"      Model '{model}' unavailable, trying the next one...")
                    break
                if r.status_code >= 500:
                    time.sleep(15)
                    continue
                raise AIError(f"AI service error {r.status_code}: {text}")
        if all(m in self.exhausted or self.used_today(m) + need > self.daily for m in self.models):
            raise BudgetExhausted("Today's free AI allowance is used up; the rest waits for the next run.")
        raise AIError("No AI model worked. Check LLM_MODEL in settings.txt against your provider's model list.")


def parse_json(text):
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
    raise AIError("The AI answer was not valid JSON.")
