"""Controlled local engine checks: no model client or network is constructed."""
import json
import sys
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from agentdojo_manta.adapter import AdapterPaths, _import_manta

_import_manta(AdapterPaths.from_repo(ROOT))
from MAS.config import SelfEvolvedConfig
from MAS.langgraph_engine import ExperimentSpec
from MAS.llm import LLMResult
from MAS.self_evolved.engine import SelfEvolvedEngine
from MAS.self_evolved.spec import AgentNode, GroupSpec, TopologySpec


class LocalHarness:
    def __init__(self):
        self.writes = []

    def generate(self, **kwargs):
        records = []
        for tool in kwargs.get("tools") or []:
            if tool["name"] == "update_record":
                output = tool["handler"]({"actor": kwargs["agent_id"]})
                records.append(dict(tool_name="update_record", arguments={"actor": kwargs["agent_id"]},
                                    status="completed", error=None, output=output))
        return LLMResult(text=json.dumps(dict(answer="Checked the record.", confidence=0.4,
            evidence=["Local controlled tool output."], unresolved_issues=["Needs another check."])),
            token_in=0, token_out=0, cost_usd=0, model="local-test-only", mock_used=False, tool_calls=records)


def run_controlled(protocol):
    harness = LocalHarness()
    config = SelfEvolvedConfig(write_protocol=protocol, max_turns=2, repair_budget=1,
        audit_mode="heuristic", skill_update_batch_size=0, playbook_read=False)
    engine = SelfEvolvedEngine(harness, config)
    requested = []

    def initial(task, num_agents, benchmark_name, tools_available):
        requested.append(num_agents)
        ids = tuple(f"agent_{i}" for i in range(num_agents))
        return TopologySpec(version=0, agents=tuple(AgentNode(i, "g") for i in ids),
            groups=(GroupSpec("g", "chain", ids, leader_id=ids[0]),), root_group_id="g"), {}

    engine._propose_initial_spec = initial
    engine._audit_turn = lambda *a, **k: {"repair_recommended": True, "detected_modes": []}
    repair_gates = []

    def termination(state, **kwargs):
        available = kwargs["repair_available"]
        repair_gates.append(available)
        return dict(should_stop=not available, next_step="apply_mutation" if available else "finalize", reason="controlled")

    engine._meta_termination = termination

    def mutate(state, spec, audit, **kwargs):
        changed = replace(spec, version=1, groups=(replace(spec.groups[0], pattern="voting", leader_id=None),))
        changed.validate(max_agents=10)
        return changed, {"mutation": {"ops": [{"op": "set_group_pattern", "args": {"group_id": "g", "pattern": "voting"}}]}}

    engine._apply_mutation = mutate
    engine._finalize = lambda *a, **k: "Local test complete."

    def write(arguments):
        harness.writes.append(arguments["actor"])
        return {"success": True, "write_count": len(harness.writes)}

    result = engine.run(task=SimpleNamespace(task_id="local", prompt="Check a local record."),
        run_index=0, seed=42, spec=ExperimentSpec(topology="self_evolved", num_agents=5, rounds=1,
        benchmark_name="agentdojo", enable_dynamic_roles=False, termination_consensus_mode="lexical",
        final_vote_mode="deterministic"), agent_types=["general"],
        tools=[dict(name="update_record", description="Local test write", parameters={"type": "object"}, handler=write, side_effect=True)],
        max_tool_iterations=1)
    return result.run_metadata["self_evolved"], harness, requested, repair_gates


class AdaptiveExecutionChecks(unittest.TestCase):
    def test_native_keeps_chain_then_executes_mutated_voting_after_real_local_writes(self):
        metadata, harness, requested, gates = run_controlled("adaptive_native")
        self.assertEqual(requested, [5])
        self.assertTrue(gates[0], "A completed write must not disable the approved adaptive repair")
        graphs = metadata["execution_graphs"]
        self.assertEqual([g["topology_spec"]["groups"][0]["pattern"] for g in graphs], ["chain", "voting"])
        self.assertEqual([s["agent_id"] for s in graphs[0]["stage_sequence"]], [f"agent_{i}" for i in range(5)])
        self.assertGreaterEqual(len(harness.writes), 5)
        self.assertNotIn("transaction_protocol_reapplied", metadata["mutations"][0])

    def test_legacy_still_caps_three_and_contracts_to_star(self):
        metadata, harness, requested, gates = run_controlled("transactional_star")
        self.assertEqual(requested, [3])
        self.assertFalse(gates[0])
        self.assertEqual(len(metadata["execution_graphs"]), 1)
        self.assertEqual(metadata["execution_graphs"][0]["topology_spec"]["groups"][0]["pattern"], "star")
        self.assertEqual(len(harness.writes), 1)


if __name__ == "__main__":
    unittest.main()
