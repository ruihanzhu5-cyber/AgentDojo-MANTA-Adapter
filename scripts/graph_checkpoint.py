"""Version-locked, JSON-only checkpoints at the native MANTA turn boundary.

The continuation executes the original loop and finalize AST. It skips the
already-completed prefix; it does not replay tasks or recorded model replies.
"""
from __future__ import annotations

import ast
import copy
import dataclasses
import hashlib
import inspect
import random
import sys
import textwrap
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from enum import Enum
from pathlib import Path

from context_replay_lib import ROOT, digest

ENGINE_SHA = "4f16864f566d72e4b80652254015170002551d099666c9b2b4cebfe2a080e66c"


def native_parts():
    from MAS.self_evolved.engine import SelfEvolvedEngine
    path = ROOT / "upstreams/manta/MAS/self_evolved/engine.py"
    if hashlib.sha256(path.read_bytes()).hexdigest() != ENGINE_SHA:
        raise ValueError("Native engine changed; checkpoint adapter requires a new review")
    fn = ast.parse(textwrap.dedent(inspect.getsource(SelfEvolvedEngine.run))).body[0]
    loops = [i for i, node in enumerate(fn.body) if isinstance(node, ast.For)
             and isinstance(node.target, ast.Name) and node.target.id == "turn_index"]
    if len(loops) != 1:
        raise ValueError("Native control-loop boundary is ambiguous")
    index = loops[0]
    if ast.unparse(fn.body[index].iter) != "range(max_turns)":
        raise ValueError("Native turn schedule changed")
    first = fn.body[index].body[0]
    if ast.unparse(first) != "result = executor.run_turn(state, topo_spec, turn_index=turn_index)":
        raise ValueError("Native checkpoint no longer precedes executor.run_turn")
    return SelfEvolvedEngine, fn, index


def compile_capture():
    cls, fn, index = native_parts()
    fn.name = "capture_run"
    fn.body[index].body.insert(0, ast.parse("self._checkpoint_hook(locals())").body[0])
    fn.body.insert(index + 1, ast.parse("self._prefix_finished(locals())").body[0])
    namespace = dict(cls.run.__globals__)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])),
                 "<native-manta-capture>", "exec"), namespace)
    return namespace[fn.name]


def compile_resume(names):
    cls, native, index = native_parts()
    if any(not n.isidentifier() or n == "_saved_frame" for n in names):
        raise ValueError("Unexpected frame-local identifier")
    assignments = [ast.parse(f"{n} = _saved_frame[{n!r}]").body[0] for n in names if n != "self"]
    loop = copy.deepcopy(native.body[index])
    loop.iter = ast.parse("range(_saved_frame['turn_index'], max_turns)", mode="eval").body
    fn = ast.parse("def resume_run(self, _saved_frame):\n    pass\n").body[0]
    fn.body = assignments + [loop] + copy.deepcopy(native.body[index + 1:])
    namespace = dict(cls.run.__globals__)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])),
                 "<native-manta-resume>", "exec"), namespace)
    return namespace[fn.name]


def class_registry():
    from MAS.config import SelfEvolvedConfig
    from MAS.langgraph_engine import ExperimentSpec
    from MAS.relay import TopologyLayout
    from MAS.self_evolved.spec import AgentNode, ContextPolicy, GroupSpec, TopologySpec
    from MAS.self_evolved.executor import TurnExecutor, TurnResult
    from MAS.self_evolved.context import SharedContextController
    from MAS.self_evolved.playbook import ShortTermTopologyPlaybook, TopologyPlaybook
    from MAS.monitor import NullDescriptor
    from agentdojo_manta.adapter import AgentDojoTask
    classes = (SelfEvolvedConfig, ExperimentSpec, TopologyLayout, AgentNode, ContextPolicy,
               GroupSpec, TopologySpec, TurnExecutor, TurnResult, SharedContextController,
               ShortTermTopologyPlaybook, TopologyPlaybook, AgentDojoTask, NullDescriptor)
    return {c.__name__: c for c in classes}


class Codec:
    """Preserve container aliases; reject unknown objects and executable payloads."""
    def __init__(self, bindings):
        self.bindings = bindings
        self.reverse = {id(v): k for k, v in bindings.items()}
        if len(self.reverse) != len(bindings):
            raise ValueError("Bindings must have one canonical name per runtime object")
        self.classes = class_registry()
        from pydantic import BaseModel
        self.models, self.enums = {}, {}
        for name, module in list(sys.modules.items()):
            if not name.startswith("agentdojo.default_suites.") or module is None:
                continue
            for value in list(vars(module).values()):
                if isinstance(value, type) and value.__module__.startswith("agentdojo.default_suites."):
                    key = value.__module__ + "." + value.__qualname__
                    if issubclass(value, BaseModel):
                        self.models[key] = value
                    elif issubclass(value, Enum):
                        self.enums[key] = value

    def encode(self, root):
        import numpy as np
        from pydantic import BaseModel
        nodes, seen = [], {}

        def put(value):
            if value is None or type(value) in (str, int, float, bool):
                return value
            if id(value) in self.reverse:
                return {"binding": self.reverse[id(value)]}
            if isinstance(value, Path):
                return {"path": str(value)}
            if isinstance(value, Enum):
                key = type(value).__module__ + "." + type(value).__qualname__
                if key not in self.enums:
                    raise TypeError("Unsupported checkpoint enum")
                return {"enum": key, "value": put(value.value)}
            if type(value) in (datetime, date, time):
                if getattr(value, "tzinfo", None) is not None and type(value.tzinfo) is not timezone:
                    raise TypeError("Custom timezone checkpointing is not supported")
                return {"temporal": type(value).__name__, "iso": value.isoformat(), "fold": getattr(value, "fold", 0)}
            if type(value) is timedelta:
                return {"timedelta": [value.days, value.seconds, value.microseconds]}
            if type(value) is Decimal:
                return {"decimal": str(value)}
            if id(value) in seen:
                return {"ref": seen[id(value)]}
            number = len(nodes)
            seen[id(value)] = number
            node = {}
            nodes.append(node)
            if type(value) is dict:
                node.update(type="dict", items=[[put(k), put(v)] for k, v in value.items()])
            elif type(value) in (list, tuple, set):
                values = sorted(value) if type(value) is set else value
                node.update(type=type(value).__name__, items=[put(v) for v in values])
            elif type(value) is np.ndarray:
                node.update(type="ndarray", dtype=str(value.dtype), shape=list(value.shape), items=value.tolist())
            elif isinstance(value, BaseModel):
                key = type(value).__module__ + "." + type(value).__qualname__
                if key not in self.models:
                    raise TypeError(f"Unsupported checkpoint model: {key}")
                node.update(type="pydantic", model=key, data=put(value.__dict__),
                            fields_set=put(value.__pydantic_fields_set__), extra=put(value.__pydantic_extra__),
                            private=put(value.__pydantic_private__))
            elif type(value) in self.classes.values():
                attrs = ({f.name: getattr(value, f.name) for f in dataclasses.fields(value)}
                         if dataclasses.is_dataclass(value) else vars(value))
                node.update(type=type(value).__name__, attrs={k: put(v) for k, v in attrs.items()})
            else:
                raise TypeError(f"Unsupported checkpoint object: {type(value).__module__}.{type(value).__name__}")
            return {"ref": number}

        encoded = put(root)
        return dict(format="manta-frame-json-v1", root=encoded, nodes=nodes)

    def decode(self, payload, *, reference=None, cache=None):
        import numpy as np
        if payload["format"] != "manta-frame-json-v1":
            raise ValueError("Unknown checkpoint format")
        cache, building = ({} if cache is None else cache), set()

        def get(value):
            if not isinstance(value, dict):
                return value
            if set(value) == {"binding"}:
                return self.bindings[value["binding"]]
            if set(value) == {"path"}:
                return Path(value["path"])
            if set(value) == {"enum", "value"}:
                return self.enums[value["enum"]](get(value["value"]))
            if set(value) == {"temporal", "iso", "fold"}:
                types = {"datetime": datetime, "date": date, "time": time}
                result = types[value["temporal"]].fromisoformat(value["iso"])
                return result.replace(fold=value["fold"]) if value["temporal"] != "date" else result
            if set(value) == {"timedelta"}:
                days, seconds, micros = value["timedelta"]
                return timedelta(days=days, seconds=seconds, microseconds=micros)
            if set(value) == {"decimal"}:
                return Decimal(value["decimal"])
            if set(value) != {"ref"}:
                raise ValueError("Unexpected checkpoint reference")
            index = value["ref"]
            if index in cache:
                return cache[index]
            if index in building:
                raise ValueError("Cyclic immutable checkpoint container")
            building.add(index)
            node = payload["nodes"][index]
            kind = node["type"]
            if kind == "dict":
                obj = cache[index] = {}
                obj.update((get(k), get(v)) for k, v in node["items"])
            elif kind == "list":
                obj = cache[index] = []
                obj.extend(get(v) for v in node["items"])
            elif kind == "set":
                obj = cache[index] = set()
                obj.update(get(v) for v in node["items"])
            elif kind == "tuple":
                obj = tuple(get(v) for v in node["items"])
                cache[index] = obj
            elif kind == "ndarray":
                obj = np.array(node["items"], dtype=node["dtype"]).reshape(node["shape"])
                cache[index] = obj
            elif kind == "pydantic":
                cls = self.models[node["model"]]
                obj = cache[index] = cls.__new__(cls)
                # Validators rebuild indexes/defaults; restoring live state must not run them.
                object.__setattr__(obj, "__dict__", get(node["data"]))
                object.__setattr__(obj, "__pydantic_fields_set__", get(node["fields_set"]))
                object.__setattr__(obj, "__pydantic_extra__", get(node["extra"]))
                object.__setattr__(obj, "__pydantic_private__", get(node["private"]))
            elif kind in self.classes:
                obj = cache[index] = self.classes[kind].__new__(self.classes[kind])
                for key, val in node["attrs"].items():
                    object.__setattr__(obj, key, get(val))
            else:
                raise ValueError(f"Unknown checkpoint class: {kind}")
            building.remove(index)
            return obj

        return get(payload["root"] if reference is None else reference)


def runtime_bindings(engine, frame_tools, commit_handlers, raw_tools, descriptor):
    # NullDescriptor contains monitor_records; serialize it as real state.
    bindings = {"engine": engine, "llm": engine.llm_client, "stage": engine._stage}
    seen = {id(v) for v in bindings.values()}
    for prefix, tools in (("official", raw_tools), ("stage", frame_tools)):
        for tool in tools:
            for key in ("handler", "dry_run_handler"):
                value = tool.get(key)
                if callable(value) and id(value) not in seen:
                    bindings[f"{prefix}:{tool['name']}:{key}"] = value
                    seen.add(id(value))
    for name, value in commit_handlers.items():
        if id(value) not in seen:
            bindings[f"commit:{name}"] = value
            seen.add(id(value))
    return bindings


def flip_graph(spec, max_agents=10):
    from MAS.self_evolved.spec import GroupSpec
    groups = sorted(spec.groups, key=lambda g: (g.group_id != spec.root_group_id, g.group_id))
    for group in groups:
        if len(group.member_ids) < 2 or group.pattern not in {"star", "chain", "debate", "voting"}:
            continue
        pattern = "star" if group.pattern == "chain" else "chain"
        leader = (group.member_ids[0] if group.parent_agent_id is None and pattern == "star" else None)
        replacement = GroupSpec(group_id=group.group_id, pattern=pattern, member_ids=group.member_ids,
                                parent_agent_id=group.parent_agent_id, leader_id=leader)
        changed = dataclasses.replace(spec, groups=tuple(replacement if g.group_id == group.group_id else g
                                                        for g in spec.groups))
        changed.validate(max_agents=max_agents)
        if changed.to_layout().adjacency == spec.to_layout().adjacency:
            continue
        if changed.agents != spec.agents or changed.extra_edges != spec.extra_edges:
            raise ValueError("Graph-only intervention changed agent policies or extra edges")
        if changed.to_layout().roles != spec.to_layout().roles:
            raise ValueError("Graph-only intervention changed agent roles")
        return changed
    raise ValueError("No native group switch changes adjacency with fixed nodes and policies")


def engine_cache(engine):
    from MAS.monitor import NullDescriptor
    allowed = {"llm_client", "se_config", "_stage", "planner", "auditor", "_playbook", "_playbook_loaded",
               "_skill_cache", "_skill_loaded", "_checkpoint_hook", "_prefix_finished"}
    if set(vars(engine)) - allowed or engine._stage._graph_cache:
        raise ValueError("Unknown engine state or compiled graph cache cannot be checkpointed")
    if set(vars(engine.planner)) != {"llm_client", "se_config"} or set(vars(engine.auditor)) != {"llm_client", "se_config"}:
        raise ValueError("Unknown planner/auditor state")
    return {key: getattr(engine, key) for key in ("se_config", "_playbook", "_playbook_loaded", "_skill_cache", "_skill_loaded")}


def client_profile(client):
    return dict(models=dict(client.models), base_url=client.config.base_url,
                timeout_s=client.config.timeout_s, http_referer=client.config.http_referer,
                x_title=client.config.x_title, disable_live=client.disable_live, require_live=client.require_live)


def capture_bundle(engine, frame, env, initial_env, observer, raw_tools):
    import numpy as np
    from MAS.monitor import NullDescriptor
    if type(frame["state"]["descriptor"]) is not NullDescriptor:
        raise ValueError("Only the native NullDescriptor is supported")
    bindings = runtime_bindings(engine, frame["tools"], frame["commit_handlers"], raw_tools,
                                frame["state"]["descriptor"])
    codec = Codec(bindings)
    root = dict(frame=frame, environment=env, initial_environment=initial_env,
                engine_cache=engine_cache(engine), python_rng=random.getstate(),
                numpy_rng=np.random.get_state(), llm_request_seq=engine.llm_client._request_seq,
                client_profile=client_profile(engine.llm_client))
    env_view, initial_view = env.model_dump(mode="json"), initial_env.model_dump(mode="json")
    encoded = codec.encode(root)
    if codec.encode(codec.decode(encoded)) != encoded:
        raise ValueError("Checkpoint round-trip changed values or object aliases")
    return dict(frame=encoded, frame_sha256=digest(encoded), environment=env_view,
                initial_environment=initial_view,
                prefix_runtime_calls=copy.deepcopy(observer.runtime_calls),
                prefix_request_records=copy.deepcopy(observer.request_records),
                boundary=dict(pc="before_native_executor_run_turn", next_turn=frame["turn_index"],
                              max_turns=frame["max_turns"], pending_http=0),
                python_rng_scope="Local RNG only; remote provider randomness cannot be restored")


def restore_environments(bundle):
    """Decode domain models first; full-frame decode reuses this object cache."""
    if digest(bundle["frame"]) != bundle["frame_sha256"]:
        raise ValueError("Checkpoint frame checksum mismatch")
    payload = bundle["frame"]
    root = payload["nodes"][payload["root"]["ref"]]
    references = {k: v for k, v in root["items"] if k in {"environment", "initial_environment"}}
    codec, cache = Codec({}), {}
    env = codec.decode(payload, reference=references["environment"], cache=cache)
    initial = codec.decode(payload, reference=references["initial_environment"], cache=cache)
    if (env.model_dump(mode="json") != bundle["environment"] or
            initial.model_dump(mode="json") != bundle["initial_environment"]):
        raise ValueError("Restored domain model values differ from checkpoint")
    return env, initial, cache


def restore_bundle(bundle, engine, tools, handlers, raw_tools, descriptor, *, cache=None):
    if digest(bundle["frame"]) != bundle["frame_sha256"]:
        raise ValueError("Checkpoint frame checksum mismatch")
    codec = Codec(runtime_bindings(engine, tools, handlers, raw_tools, descriptor))
    restored = codec.decode(bundle["frame"], cache=cache)
    if codec.encode(restored) != bundle["frame"]:
        raise ValueError("Restored frame differs from saved frame")
    if client_profile(engine.llm_client) != restored["client_profile"]:
        raise ValueError("Model/endpoint/client settings changed after capture")
    for key, value in restored["engine_cache"].items():
        setattr(engine, key, value)
    engine.planner.se_config = engine.auditor.se_config = engine.se_config
    engine.llm_client._request_seq = restored["llm_request_seq"]
    frame = restored["frame"]
    if frame["executor"]._context is not frame["context"] or frame["executor"]._engine is not engine._stage:
        raise ValueError("Executor/controller alias restoration failed")
    if frame["context"].spec != frame["topo_spec"] or frame["state"]["layout"] != frame["layout"]:
        raise ValueError("Restored topology/controller mismatch")
    return restored


def set_rng(restored):
    import numpy as np
    random.setstate(restored["python_rng"])
    np.random.set_state(restored["numpy_rng"])
