"""All folded loops share this pre-handler gateway; cache hits are not runtime calls."""
import json
import threading
from .action_policy import effect


class ToolGateway:
    def __init__(self, tools, store, contract, review):
        self.tools = {t["name"]: t for t in tools}
        self.store, self.contract, self.review = store, contract, review
        self.version = 0
        self.cache, self.effects, self.events, self.permissions = {}, {}, [], {}
        self.lock = threading.RLock()

    def permit(self, actor, names):
        self.permissions[actor] = set(names)

    def call(self, actor, name, arguments, evidence_ids=()):
        # Serializes effects and single-flights reads. No parallel state mutation.
        with self.lock:
            event = dict(actor=actor, tool=name, arguments=arguments, environment_version=self.version, handler_invoked=False)
            self.events.append(event)
            def deny(reason):
                event.update(status="blocked", reason=reason)
                return dict(error="ACTION_BLOCKED", reason=reason, instruction="Continue the legitimate task using an authorized alternative.")
            if name not in self.tools or name not in self.permissions.get(actor, set()):
                return deny("Tool is not in this actor's declared capabilities.")
            kind = effect(name)
            signature = (name, json.dumps(arguments, sort_keys=True, separators=(",", ":"), ensure_ascii=False))
            if kind in {"send", "mutate"} and signature in self.effects:
                saved = self.effects[signature]
                if saved.get("uncertain"):
                    return deny("An earlier identical action has uncertain effects; inspect state before proposing a different action.")
                self.store.grant(actor, [saved["ref"]])
                event.update(status="already_applied", evidence_id=saved["ref"])
                return dict(already_applied=True, **self.store.read(actor, saved["ref"]))
            decision, reason = self.contract.initial_decision(name, arguments, actor)
            if decision == "review":
                try:
                    decision, reason = self.review(name, arguments, evidence_ids)
                except Exception as exc:
                    event.update(status="review_error", error_type=type(exc).__name__, phase="before_handler")
                    raise
            event.update(policy_decision=decision, policy_reason=reason)
            if decision != "allow":
                return deny(reason)
            key = (signature, self.version)
            if kind == "read" and key in self.cache:
                ref = self.cache[key]
                self.store.grant(actor, [ref])
                event.update(status="cache_hit", evidence_id=ref)
                return dict(cache_hit=True, **self.store.read(actor, ref))
            try:
                event["handler_invoked"] = True
                output = self.tools[name]["handler"](arguments)
            except Exception as exc:
                # A mutation may have partially taken effect before an exception.
                if kind != "read":
                    self.version += 1
                    self.cache.clear()
                    if kind in {"send", "mutate"}:
                        self.effects[signature] = {"uncertain": True}
                event.update(status="handler_exception", error=type(exc).__name__)
                raise
            failed = isinstance(output, dict) and bool(output.get("error"))
            ref = self.store.add(output, tool=name, arguments=arguments, version=self.version, actor=actor)
            event.update(status="runtime_error" if failed else "executed", evidence_id=ref)
            if kind == "read" and not failed:
                self.cache[key] = ref
            elif kind != "read":
                self.version += 1
                self.cache.clear()
                if kind in {"send", "mutate"}:
                    self.effects[signature] = {"ref": ref, "uncertain": failed}
            return self.store.read(actor, ref)
