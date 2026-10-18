"""Run the pinned MANTA engine through AgentDojo's official task runner.

This adapter deliberately keeps AgentDojo in charge of task setup, tool execution,
injection construction, and utility/security evaluation.  MANTA only owns the
multi-agent execution layer.  The pinned MANTA source is vendored under
``upstreams/manta`` and imported by path, separate from the AgentDojo package.
"""

from __future__ import annotations

import json
import os
import sys
import types
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agentdojo.agent_pipeline.base_pipeline_element import BasePipelineElement
from agentdojo.functions_runtime import EmptyEnv, Env, FunctionCall, FunctionsRuntime
from agentdojo.types import (
    ChatAssistantMessage,
    ChatMessage,
    ChatUserMessage,
    text_content_block_from_string,
)


@dataclass(frozen=True)
class AdapterPaths:
    """Paths needed by the adapter, all explicit for reproducibility."""

    manta_root: Path
    playbook_path: Path
    skill_path: Path

    @classmethod
    def from_repo(cls, repo_root: Path, manta_root: Path | None = None) -> "AdapterPaths":
        root = manta_root or repo_root / "upstreams" / "manta"
        return cls(
            manta_root=root,
            playbook_path=root / "config" / "topology_playbook.json",
            skill_path=root / "config" / "topology_skill.md",
        )


@dataclass(frozen=True)
class AgentDojoTask:
    """Small task view matching the attributes used by MANTA's engine/planner."""

    task_id: str
    prompt: str
    benchmark_name: str


def _import_manta(paths: AdapterPaths):
    """Import MANTA without executing its eager top-level package imports.

    MANTA's top-level ``MAS.__init__`` imports every benchmark adapter.  AgentDojo
    has its own dependency graph, so loading MANTA as a namespace package avoids
    importing unrelated benchmark integrations while still executing the official
    self-evolved engine and its relative imports.
    """

    manta_root = str(paths.manta_root.resolve())
    if manta_root not in sys.path:
        sys.path.insert(0, manta_root)
    package = sys.modules.get("MAS")
    if package is None or not getattr(package, "__path__", None):
        package = types.ModuleType("MAS")
        package.__path__ = [str(paths.manta_root / "MAS")]
        package.__package__ = "MAS"
        sys.modules["MAS"] = package

    from MAS.config import OpenRouterConfig, SelfEvolvedConfig  # type: ignore
    from MAS.llm import OpenRouterLLMClient  # type: ignore
    from MAS.langgraph_engine import ExperimentSpec  # type: ignore
    from MAS.self_evolved.engine import SelfEvolvedEngine  # type: ignore

    return OpenRouterConfig, SelfEvolvedConfig, OpenRouterLLMClient, ExperimentSpec, SelfEvolvedEngine


def _make_llm_client(paths: AdapterPaths, model: str | None = None, *, observer=None):
    OpenRouterConfig, _SelfEvolvedConfig, OpenRouterLLMClient, _ExperimentSpec, _Engine = _import_manta(paths)

    api_key = os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_COMPATIBLE_API_KEY")
    base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
    model_name = model or os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

    config = OpenRouterConfig(
        api_key=api_key,
        base_url=base_url,
        timeout_s=float(os.getenv("V1_LLM_TIMEOUT_S", "180")),
    )
    models = {
        "default": model_name,
        "general": model_name,
        "planner": os.getenv("DEEPSEEK_PLANNER_MODEL", model_name),
        "auditor": os.getenv("DEEPSEEK_AUDITOR_MODEL", model_name),
    }
    client = OpenRouterLLMClient(config, models)
    from agentdojo_manta.budget import configured_budget
    budget = configured_budget()
    if budget is not None:
        from urllib.parse import urlparse
        if urlparse(base_url).hostname != "api.deepseek.com":
            raise ValueError("Verified budget prices require api.deepseek.com")
        # MANTA's own retries remain observed; eliminate hidden SDK retries.
        if client.client is not None:
            client.client = client.client.with_options(max_retries=0)

    # OpenRouterLLMClient adds OpenRouter-only ``extra_body.provider`` routing.
    # DeepSeek's endpoint is OpenAI-compatible but does not need that routing
    # payload.  Disable only the provider wrapper; MANTA's tool loop and accounting
    # remain unchanged.
    client._apply_openrouter_routing_overrides = lambda kwargs, retry_index=0: dict(kwargs)  # type: ignore[attr-defined]

    # DeepSeek's OpenAI-compatible endpoint is stricter than OpenRouter about
    # parallel tool calls.  MANTA's tool-loop already serializes handler
    # execution and records one tool response per call, so forcing a single
    # call per completion preserves the algorithm while keeping the assistant
    # tool-call / tool-response sequence valid for DeepSeek.
    _create_chat_completion = client._create_chat_completion

    def _deepseek_chat_completion(**kwargs: Any):
        if kwargs.get("tools"):
            kwargs["parallel_tool_calls"] = False
        return _create_chat_completion(**kwargs)

    client._create_chat_completion = _deepseek_chat_completion  # type: ignore[method-assign]
    if observer is not None:
        original_once = client._create_chat_completion_once
        original_generate = client.generate
        actor_context = threading.local()

        def observed_generate(**kwargs):
            actor_context.agent_id = kwargs.get("agent_id")
            try:
                result = original_generate(**kwargs)
                with observer._metrics_lock:
                    observer.mock_used = observer.mock_used or bool(result.mock_used)
                return result
            finally:
                actor_context.agent_id = None

        def observed_once(**kwargs):
            def strings(value):
                if isinstance(value, str):
                    yield value
                elif isinstance(value, dict):
                    for item in value.values():
                        yield from strings(item)
                elif isinstance(value, (list, tuple)):
                    for item in value:
                        yield from strings(item)
            messages_text = "\n".join(strings(kwargs.get("messages", [])))
            with observer._metrics_lock:
                matches = [key for key, payload in observer.injections.items()
                           if payload and payload in messages_text]
            record = {"agent_id": getattr(actor_context, "agent_id", None),
                      "model": kwargs.get("model"), "status": "error",
                      "matched_injection_keys": matches, "usage_available": False}
            start = time.perf_counter()
            reservation = None
            try:
                if budget is not None:
                    reservation = budget.reserve(kwargs.get("model"), int(kwargs["max_tokens"]))
                    record["budget_request_id"] = reservation
                response = original_once(**kwargs)
                usage = getattr(response, "usage", None)
                record["provider_model"] = getattr(response, "model", None)
                if budget is not None:
                    record["cost_upper_bound_usd"] = budget.settle(reservation, usage)
                record.update(status="completed", usage_available=usage is not None,
                              token_in=getattr(usage, "prompt_tokens", None),
                              token_out=getattr(usage, "completion_tokens", None))
                return response
            except Exception as exc:
                if budget is not None and reservation is not None:
                    budget.uncertain(reservation)
                record["error_type"] = type(exc).__name__
                record["http_status"] = getattr(exc, "status_code", None)
                raise
            finally:
                record["latency_s"] = time.perf_counter() - start
                with observer._metrics_lock:
                    observer.request_records.append(record)

        client.generate = observed_generate
        client._create_chat_completion_once = observed_once
    return client


def _function_to_manta_tool(runtime: FunctionsRuntime, env: Env, function: Any, *, observer=None) -> dict[str, Any]:
    """Convert one AgentDojo Function into MANTA's tool schema + bound handler."""

    schema = function.parameters.model_json_schema()

    def handler(arguments: dict[str, Any]) -> Any:
        value, error = runtime.run_function(env, function.name, arguments)
        if observer is not None:
            from agentdojo.agent_pipeline.tool_execution import tool_result_to_str
            with observer._metrics_lock:
                observer.runtime_calls.append({
                    "tool_name": function.name, "arguments": dict(arguments),
                    "output": tool_result_to_str(value) if error is None else str(error),
                    "error": error,
                })
        if error is not None:
            return {"error": error}
        return value

    mutation_verbs = {
        "add",
        "book",
        "cancel",
        "create",
        "delete",
        "modify",
        "move",
        "remove",
        "rename",
        "schedule",
        "send",
        "set",
        "submit",
        "update",
        "write",
    }
    name_tokens = {token for token in function.name.replace("-", "_").split("_") if token}
    return {
        "name": function.name,
        "description": function.description,
        "parameters": schema,
        "handler": handler,
        "side_effect": bool(name_tokens & mutation_verbs),
    }


def _text_blocks(value: Any) -> list[dict[str, str]]:
    if isinstance(value, list):
        blocks = []
        for item in value:
            if isinstance(item, dict) and item.get("type") == "text":
                blocks.append({"type": "text", "content": str(item.get("content", ""))})
        if blocks:
            return blocks
    return [text_content_block_from_string(str(value or ""))]


def _build_agentdojo_messages(query: str, metadata: dict[str, Any], final_answer: str) -> list[ChatMessage]:
    """Project MANTA's interaction logs into AgentDojo's official message shape."""

    messages: list[ChatMessage] = [
        ChatUserMessage(role="user", content=[text_content_block_from_string(query)])
    ]
    # The official judge reconstructs its function trace from assistant calls.
    # Use actual FunctionsRuntime invocations, including calls from discarded
    # stages, and exclude MANTA's synthetic/skipped calls and proposals.
    records = metadata.get("agentdojo_runtime_calls", [])
    logs = [{"assistant_message": {"content": ""}, "tool_calls": [record]}
            for record in records]

    for index, log in enumerate(logs):
        if not isinstance(log, dict):
            continue
        raw_assistant = log.get("assistant_message")
        if isinstance(raw_assistant, dict):
            assistant: ChatAssistantMessage = {
                "role": "assistant",
                "content": _text_blocks(raw_assistant.get("content", "")),
                "tool_calls": [],
            }
            for call_index, record in enumerate(log.get("tool_calls", []) or []):
                if not isinstance(record, dict):
                    continue
                call = FunctionCall(
                    function=str(record.get("tool_name", "")),
                    args=dict(record.get("arguments", {}) or {}),
                    id=str(record.get("id") or f"manta-call-{index}-{call_index}"),
                )
                assistant["tool_calls"].append(call)
            messages.append(assistant)
            for call_index, record in enumerate(log.get("tool_calls", []) or []):
                if not isinstance(record, dict):
                    continue
                call = assistant["tool_calls"][call_index]
                output = record.get("output")
                if not isinstance(output, str):
                    output = json.dumps(output, ensure_ascii=False, default=str)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call": call,
                        "tool_call_id": call.id,
                        "content": [text_content_block_from_string(output)],
                        "error": record.get("error"),
                    }
                )

    messages.append(
        ChatAssistantMessage(
            role="assistant",
            content=[text_content_block_from_string(final_answer)],
            tool_calls=None,
        )
    )
    return messages


class MantaAgentDojoPipeline(BasePipelineElement):
    """AgentDojo pipeline backed by the pinned official MANTA engine."""

    name = "manta-agentdojo"

    def __init__(
        self,
        paths: AdapterPaths,
        *,
        model: str | None = None,
        num_agents: int = 3,
        max_turns: int = 2,
        repair_budget: int = 1,
        initial_planner_mode: str = "task_conditioned",
        audit_mode: str = "heuristic",
    ) -> None:
        _OpenRouterConfig, SelfEvolvedConfig, _Client, ExperimentSpec, SelfEvolvedEngine = _import_manta(paths)
        self.paths = paths
        self.model = model or os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
        self.num_agents = int(num_agents)
        self._metrics_lock = threading.Lock()
        self.request_records: list[dict[str, Any]] = []
        self.runtime_calls: list[dict[str, Any]] = []
        self.injections: dict[str, str] = {}
        self.mock_used = False
        self.execution_completed = False
        self.seed = 0
        self.max_initial_agents = max(
            self.num_agents,
            int(os.getenv("MANTA_MAX_INITIAL_AGENTS", "5")),
        )
        self.max_total_agents = max(
            self.max_initial_agents,
            int(os.getenv("MANTA_MAX_TOTAL_AGENTS", "10")),
        )
        self.se_config = SelfEvolvedConfig(
            harness_backend="openrouter",
            initial_planner_mode=initial_planner_mode,
            max_initial_agents=self.max_initial_agents,
            max_total_agents=self.max_total_agents,
            max_turns=int(max_turns),
            repair_budget=int(repair_budget),
            audit_mode=audit_mode,
            playbook_path=str(paths.playbook_path),
            skill_path=str(paths.skill_path),
            skill_update_batch_size=0,
        )
        self.se_config.validate()
        self._engine = SelfEvolvedEngine(_make_llm_client(paths, self.model, observer=self), self.se_config)
        self._experiment_spec = ExperimentSpec(
            topology="self_evolved",
            num_agents=int(num_agents),
            rounds=1,
            discussion_rounds=1,
            communication_budget_per_agent=2,
            termination_consensus_mode="lexical",
            final_vote_mode="deterministic",
            peer_artifact_max_chars=1200,
            benchmark_name="agentdojo",
        )
        self.task_id_lookup: dict[str, str] = {}
        self.last_run_metadata: dict[str, Any] = {}
        self.last_trace_events: list[Any] = []

    def bind_suite(self, suite: Any) -> None:
        """Bind official task prompts to IDs for trace provenance.

        AgentDojo's public ``BasePipelineElement.query`` contract intentionally
        passes only the prompt.  A lookup keeps the official runner untouched
        while preserving task IDs in the MANTA trace.
        """

        lookup: dict[str, str] = {}
        for task in list(suite.user_tasks.values()) + list(suite.injection_tasks.values()):
            prompt = getattr(task, "PROMPT", None) or getattr(task, "GOAL", None)
            if isinstance(prompt, str):
                lookup[prompt] = str(task.ID)
        self.task_id_lookup = lookup

    def query(
        self,
        query: str,
        runtime: FunctionsRuntime,
        env: Env = EmptyEnv(),
        messages: list[ChatMessage] | tuple[ChatMessage, ...] = (),
        extra_args: dict | None = None,
    ) -> tuple[str, FunctionsRuntime, Env, list[ChatMessage], dict]:
        extra_args = dict(extra_args or {})
        from agentdojo.logging import Logger
        self.injections = dict(getattr(Logger.get(), "context", {}).get("injections", {}))
        task_id = str(extra_args.get("task_id") or self.task_id_lookup.get(query, "agentdojo_task"))
        seed = int(extra_args.get("seed", self.seed))
        run_index = int(extra_args.get("run_index", 0))
        tools = [_function_to_manta_tool(runtime, env, function, observer=self) for function in runtime.functions.values()]
        task = AgentDojoTask(task_id=task_id, prompt=query, benchmark_name="agentdojo")
        result = self._engine.run(
            task=task,
            run_index=run_index,
            seed=seed,
            spec=self._experiment_spec,
            agent_types=["general"],
            tools=tools,
            max_tool_iterations=int(extra_args.get("max_tool_iterations", 8)),
        )
        metadata = dict(result.run_metadata)
        metadata["agentdojo_runtime_calls"] = list(self.runtime_calls)
        metadata["manta_commit"] = os.getenv("MANTA_COMMIT", "3da4087")
        metadata["agentdojo_adapter"] = "official_task_suite_pipeline"
        metadata["manta_config"] = {
            "initial_agent_budget": self.num_agents,
            "max_initial_agents": self.max_initial_agents,
            "max_total_agents": self.max_total_agents,
            "max_turns": self.se_config.max_turns,
            "repair_budget": self.se_config.repair_budget,
            "initial_planner_mode": self.se_config.initial_planner_mode,
            "audit_mode": self.se_config.audit_mode,
        }
        extra_args = {**extra_args, "manta_run_metadata": metadata, "manta_trace_events": result.trace_events}
        self.last_run_metadata = metadata
        self.last_trace_events = list(result.trace_events)
        self.execution_completed = True
        output_messages = _build_agentdojo_messages(query, metadata, result.final_answer)
        # AgentDojo's official runner records messages through its active Logger;
        # custom pipeline elements must forward them explicitly.
        from agentdojo.logging import Logger

        Logger.get().log(output_messages)
        return query, runtime, env, output_messages, extra_args


__all__ = ["AdapterPaths", "AgentDojoTask", "MantaAgentDojoPipeline"]
