"""Explicit model/endpoint binding; no implicit provider or model fallback."""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Provider:
    name: str
    base_url: str
    api_key: str | None
    model: str
    planner_model: str
    auditor_model: str


def provider_config(model: str | None = None) -> Provider:
    name = os.getenv("MANTA_PROVIDER", "deepseek")
    if name == "deepseek":
        model = model or os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
        if model == "deepseek-v4-pro" and any(os.getenv(k, model) != model for k in ("DEEPSEEK_PLANNER_MODEL", "DEEPSEEK_AUDITOR_MODEL")):
            raise ValueError("All DeepSeek Pro experiment roles must use deepseek-v4-pro")
        return Provider(name, os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
                        os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_COMPATIBLE_API_KEY"), model,
                        os.getenv("DEEPSEEK_PLANNER_MODEL", model), os.getenv("DEEPSEEK_AUDITOR_MODEL", model))
    endpoints = {"openai": "https://api.openai.com/v1", "qdd": "https://api2.aigcbest.top/v1"}
    if name not in endpoints:
        raise ValueError(f"Unsupported explicit provider: {name}")
    if model not in (None, "gpt-4o"):
        raise ValueError("GPT-4o replication requires exactly gpt-4o for every role")
    endpoint = os.getenv("OPENAI_BASE_URL", endpoints[name]).rstrip("/")
    if endpoint != endpoints[name]:
        raise ValueError(f"Endpoint does not match explicitly selected provider {name}")
    for key in ("OPENAI_MODEL", "OPENAI_PLANNER_MODEL", "OPENAI_AUDITOR_MODEL"):
        if os.getenv(key, "gpt-4o") != "gpt-4o":
            raise ValueError(f"{key} must be gpt-4o")
    return Provider(name, endpoint, os.getenv("OPENAI_API_KEY"), "gpt-4o", "gpt-4o", "gpt-4o")


def gpt4o_sampling(kwargs, *, temperature=None):
    """Preserve baseline sampling/output policy without inheriting other providers' env."""
    result = dict(kwargs)
    if temperature is not None:
        result["temperature"] = temperature
    # The original MANTA client overrides even planner max_tokens with 4096.
    result["max_tokens"] = 4096
    result.pop("extra_body", None)
    return result


def validate_gpt4o_response(response):
    model = getattr(response, "model", None)
    if model not in {"gpt-4o", "gpt-4o-2024-05-13", "gpt-4o-2024-08-06", "gpt-4o-2024-11-20"}:
        raise ValueError(f"Unexpected GPT-4o response model: {model!r}; stop without fallback")
    usage = getattr(response, "usage", None)
    values = [getattr(usage, key, None) for key in ("prompt_tokens", "completion_tokens", "total_tokens")]
    if any(type(v) is not int or v < 0 for v in values) or values[2] != values[0] + values[1]:
        raise ValueError("Missing or inconsistent GPT-4o response usage")
