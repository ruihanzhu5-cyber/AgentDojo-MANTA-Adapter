"""Physical execution units for folded MANTA; logical responsibilities remain explicit."""
from dataclasses import dataclass, field
from .spec import AgentNode, GroupSpec, TopologySpec


@dataclass
class ExecutionPlan:
    max_workers: int = 2
    workers: dict = field(default_factory=dict)
    verifier_used: bool = False
    versions: list = field(default_factory=list)
    events: list = field(default_factory=list)

    def snapshot(self):
        ids = ["agent_0", *self.workers]
        if self.verifier_used:
            ids.append("action_verifier")
        spec = TopologySpec(version=len(self.versions), root_group_id="root",
            agents=tuple(AgentNode(i, "root", structural_role="coordinator" if i == "agent_0" else
                "verifier" if i == "action_verifier" else "worker",
                stage_role="critic" if i == "action_verifier" else "worker") for i in ids),
            groups=(GroupSpec("root", "singleton" if len(ids) == 1 else "star", tuple(ids),
                leader_id="agent_0"),), rationale="Shared evidence roles run in agent_0; fresh contexts are explicit tools.")
        spec.validate(max_agents=self.max_workers + 2)
        payload = spec.to_payload()
        self.versions.append(payload)
        return payload

    def worker(self, subgoal, evidence_need, allowed_tools):
        if not subgoal.strip() or not evidence_need.strip():
            raise ValueError("Delegation requires a subgoal and a distinct evidence need.")
        key = (subgoal.strip().casefold(), evidence_need.strip().casefold())
        if any(w["key"] == key for w in self.workers.values()):
            raise ValueError("This investigation already has a result; reuse it or name a new evidence gap.")
        if len(self.workers) >= self.max_workers:
            raise ValueError("Independent worker budget exhausted; continue in the main loop.")
        agent = f"agent_{len(self.workers) + 1}"
        self.workers[agent] = dict(key=key, subgoal=subgoal, evidence_need=evidence_need, allowed_tools=allowed_tools)
        self.events.append(dict(event="spawn", agent_id=agent, subgoal=subgoal, evidence_need=evidence_need))
        self.snapshot()
        return agent

    def payload(self):
        return dict(shared_roles={role: "agent_0" for role in ("planning", "retrieval", "analysis", "synthesis")},
                    independent_workers={k: {f: v for f, v in w.items() if f != "key"} for k, w in self.workers.items()},
                    verifier="action_verifier" if self.verifier_used else None,
                    events=self.events, physical_loop_count=1 + len(self.workers) + int(self.verifier_used))
