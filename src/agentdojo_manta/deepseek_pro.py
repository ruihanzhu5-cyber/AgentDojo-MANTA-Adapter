"""DeepSeek Pro wire-protocol metadata; no changes to MANTA's decisions."""
from __future__ import annotations


def assistant_key(message):
    calls = message.get("tool_calls") or []
    return (message.get("content") or "", tuple(c["id"] for c in calls))


class ProReasoningHistory:
    """Restore provider-required reasoning on retained assistant turns."""

    def __init__(self):
        self.turns = {}

    def prepare(self, kwargs):
        request = dict(kwargs)
        messages = []
        for original in kwargs["messages"]:
            message = dict(original)
            if message.get("role") == "assistant":
                key = assistant_key(message)
                if key in self.turns:
                    message["reasoning_content"] = self.turns[key]
                elif message.get("tool_calls") and "reasoning_content" not in message:
                    raise ValueError("DeepSeek Pro tool history is missing actual reasoning_content")
            messages.append(message)
        request["messages"] = messages
        request["extra_body"] = {**request.get("extra_body", {}), "thinking": {"type": "enabled"}}
        return request

    def remember(self, response):
        if not response.choices:
            return
        message = response.choices[0].message
        reasoning = getattr(message, "reasoning_content", None)
        calls = getattr(message, "tool_calls", None) or []
        if calls and not isinstance(reasoning, str):
            raise ValueError("DeepSeek Pro response lacks required tool-turn reasoning_content")
        if isinstance(reasoning, str):
            key = (message.content or "", tuple(c.id for c in calls))
            self.turns[key] = reasoning


def validate_pro_response(response):
    if response.model not in {"deepseek-v4-pro", "deepseek-v4-pro-0813", "deepseek-pro"}:
        raise ValueError(f"Unexpected DeepSeek Pro response model: {response.model!r}")
    usage = response.usage
    values = [getattr(usage, k, None) for k in ("prompt_tokens", "completion_tokens", "total_tokens")]
    if any(type(v) is not int or v < 0 for v in values) or values[2] != values[0] + values[1]:
        raise ValueError("DeepSeek Pro usage missing or inconsistent")
