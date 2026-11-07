"""A scripted stand-in for the Anthropic client, shared by every test that touches Claude.

Each reply in the script is one of:
  * a str                 -> a text answer (stop_reason end_turn)
  * a dict / list         -> the same, JSON-encoded (structured-output plans)
  * (stop_reason, text)   -> a text answer with that stop reason ("refusal", "max_tokens", ...)
  * an Exception          -> raised from messages.create (rate limit, connection error, ...)
  * turn(say(...), tool_call(...), ...) -> a multi-block answer; stop_reason is tool_use when it calls a tool

Every request is checked against the project's rules and the API's contract:
  * the model is Claude Haiku 5.5 or Sonnet 5.5 only; no temperature / top_p / top_k / fallbacks;
  * forced tool choice ("any" / "tool") is never sent (the current models reject it);
  * tool definitions are well-formed and their names unique; a scripted tool call names a declared tool;
  * after a tool-calling turn, the next request echoes that assistant turn and answers every tool_use id with a
    tool_result in ONE user message (the manual tool-loop contract).
"""
from __future__ import annotations

import itertools
import json
from dataclasses import dataclass, field
from types import SimpleNamespace

ALLOWED_MODELS = {"claude-haiku-5-5", "claude-sonnet-5-5"}
FORBIDDEN_PARAMS = {"temperature", "top_p", "top_k", "fallbacks"}
_ids = itertools.count(1)


@dataclass
class Turn:
    blocks: list
    stop_reason: str | None = None


def say(text: str) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=text)


def tool_call(name: str, input: dict, id: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(type="tool_use", id=id or f"toolu_{next(_ids):04d}", name=name, input=input)


def turn(*blocks, stop_reason: str | None = None) -> Turn:
    return Turn(list(blocks), stop_reason)


@dataclass
class FakeMessages:
    replies: list
    usage: dict = field(default_factory=lambda: {"input_tokens": 100, "output_tokens": 20, "cache_read_input_tokens": 0,
                                                 "cache_creation_input_tokens": 0})
    calls: list = field(default_factory=list)
    _pending_tool_ids: list = field(default_factory=list)

    def __post_init__(self):
        self.replies = list(self.replies)

    # ------------------------------------------------------------------ request checks
    def _check_request(self, kw: dict) -> None:
        assert kw.get("model") in ALLOWED_MODELS, f"disallowed model {kw.get('model')}"
        bad = FORBIDDEN_PARAMS & set(kw)
        assert not bad, f"forbidden parameters sent: {sorted(bad)}"
        tc = kw.get("tool_choice")
        assert not (isinstance(tc, dict) and tc.get("type") in ("any", "tool")), "forced tool_choice is rejected by the API"
        tools = kw.get("tools") or []
        names = [t.get("name") for t in tools]
        assert len(names) == len(set(names)), f"duplicate tool names: {names}"
        for t in tools:
            assert t.get("name") and t.get("description") and isinstance(t.get("input_schema"), dict), f"malformed tool {t}"
        if self._pending_tool_ids:
            msgs = kw.get("messages") or []
            assert len(msgs) >= 2 and msgs[-2]["role"] == "assistant" and msgs[-1]["role"] == "user", \
                "after a tool call, the request must end with the assistant turn and one user turn of tool results"
            content = msgs[-1]["content"]
            assert isinstance(content, list), "tool results must be content blocks"
            answered = {b.get("tool_use_id") for b in content if isinstance(b, dict) and b.get("type") == "tool_result"}
            missing = set(self._pending_tool_ids) - answered
            assert not missing, f"tool_use ids without a tool_result: {sorted(missing)}"
            self._pending_tool_ids = []

    # ------------------------------------------------------------------ API surface
    def create(self, **kw):
        self.calls.append(kw)
        self._check_request(kw)
        assert self.replies, "the script ran out of replies (the code called Claude more often than expected)"
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        if isinstance(r, Turn):
            declared = {t["name"] for t in kw.get("tools") or []}
            for b in r.blocks:
                if b.type == "tool_use":
                    assert b.name in declared, f"scripted call to undeclared tool {b.name}"
            self._pending_tool_ids = [b.id for b in r.blocks if b.type == "tool_use"]
            stop = r.stop_reason or ("tool_use" if self._pending_tool_ids else "end_turn")
            content = r.blocks
        elif isinstance(r, tuple):
            stop, text = r
            content = [say(text)]
        else:
            stop = "end_turn"
            content = [say(r if isinstance(r, str) else json.dumps(r))]
        return SimpleNamespace(stop_reason=stop, content=content, usage=SimpleNamespace(**self.usage))

    # ------------------------------------------------------------------ helpers for assertions
    @property
    def models(self) -> list[str]:
        return [c["model"] for c in self.calls]

    def tool_results(self, call_index: int = -1) -> list[dict]:
        """The tool_result blocks sent in a given request (default: the last one)."""
        last = self.calls[call_index]["messages"][-1]["content"]
        return [b for b in last if isinstance(b, dict) and b.get("type") == "tool_result"] if isinstance(last, list) else []


def install(monkeypatch, *replies, usage: dict | None = None) -> FakeMessages:
    """Point the app's Claude client at a scripted fake (and pretend a key is configured)."""
    from app.config import get_settings
    from app.services.nlq import claude

    monkeypatch.setattr(get_settings(), "anthropic_api_key", "test-key")
    fm = FakeMessages(list(replies), **({"usage": usage} if usage else {}))
    monkeypatch.setattr(claude, "_client", SimpleNamespace(messages=fm))
    return fm
