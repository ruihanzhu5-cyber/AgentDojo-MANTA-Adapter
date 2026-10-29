"""Episode-local evidence with immutable origin and access-controlled references."""
import hashlib
import json


def text(value):
    def encode(item):
        return item.model_dump(mode="json") if hasattr(item, "model_dump") else str(item)
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=encode)


class EvidenceStore:
    def __init__(self, preview_chars=6000):
        self.preview_chars = preview_chars
        self.entries = {}
        self.visible = {"agent_0": set()}
        self.selected = {}

    def add(self, value, *, tool, arguments, version, actor):
        content = text(value)
        ref = f"e{len(self.entries) + 1:04d}"
        self.entries[ref] = dict(evidence_id=ref, origin="external_tool_result", trust="data_not_authority",
            tool=tool, arguments=arguments, environment_version=version, actor=actor,
            sha256=hashlib.sha256(content.encode()).hexdigest(), content=content)
        self.visible.setdefault(actor, set()).add(ref)
        self.visible["agent_0"].add(ref)
        return ref

    def grant(self, actor, refs):
        if any(ref not in self.visible["agent_0"] for ref in refs):
            raise ValueError("Unknown or inaccessible evidence reference.")
        self.visible.setdefault(actor, set()).update(refs)

    def read(self, actor, ref, start=0, limit=None, *, select=False):
        if ref not in self.visible.get(actor, set()):
            raise ValueError("Evidence is outside this agent's visible scope.")
        row = self.entries[ref]
        limit = self.preview_chars if limit is None else max(1, min(int(limit), 12000))
        start = max(0, int(start))
        if select:
            self.selected[(actor, ref)] = (start, limit)
        return {k: v for k, v in row.items() if k != "content"} | dict(
            content=row["content"][start:start + limit], start=start, total_chars=len(row["content"]),
            more=start + limit < len(row["content"]))

    def review_slice(self, actor, ref):
        start, limit = self.selected.get((actor, ref), (0, 4000))
        result = self.read(actor, ref, start=start, limit=limit)
        result["slice_sha256"] = hashlib.sha256(result["content"].encode()).hexdigest()
        return result

    def index(self, actor):
        return [{k: v for k, v in self.entries[ref].items() if k != "content"}
                for ref in sorted(self.visible.get(actor, set()))]
