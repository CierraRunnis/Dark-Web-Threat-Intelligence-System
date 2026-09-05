"""Offline checks only: no service calls, model requests, or task submission."""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

import yaml

BUNDLE = Path(__file__).resolve().parents[1]
BUILTIN_TOOLS = {"read", "grep", "glob", "run_workflow", "delegate_task", "webfetch", "websearch"}


def verify(bundle: Path = BUNDLE) -> dict:
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    listed = set()
    for record in manifest["plugin_files"]:
        relative = Path(record["path"])
        assert not relative.is_absolute() and ".." not in relative.parts and relative.parts[0] == "plugins"
        path = bundle / relative
        assert path.resolve().is_relative_to((bundle / "plugins").resolve())
        assert path.is_file(), f"Missing plugin: {relative}"
        assert hashlib.sha256(path.read_bytes()).hexdigest() == record["sha256"], f"Changed plugin: {relative}"
        listed.add(relative.as_posix())
        if path.suffix == ".py":
            ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(relative))

    workflows = {}
    node_count = 0
    referenced_agents = set()
    for name in manifest["workflow_ids"]:
        data = json.loads((bundle / "plugins/workflows" / name / "workflow.json").read_text(encoding="utf-8-sig"))
        workflows[name] = data
        nodes = data["nodes"]
        ids = {node["id"] for node in nodes}
        assert len(ids) == len(nodes) and data["start"] in ids
        node_count += len(nodes)
        referenced_agents.update(data.get("metadata", {}).get("agents", []))
        entry = data.get("metadata", {}).get("entry_agent")
        if entry:
            referenced_agents.add(entry)
        for edge in data["edges"]:
            assert edge["from"] in ids and edge["to"] in ids
        for node in nodes:
            if node["type"] == "subworkflow":
                assert node["workflow_id"] in manifest["workflow_ids"], "Missing subworkflow"
            if node.get("code"):
                tree = ast.parse(node["code"], filename=f"{name}/{node['id']}")
                for item in ast.walk(tree):
                    if isinstance(item, ast.keyword) and item.arg == "subagent_type" and isinstance(item.value, ast.Constant):
                        referenced_agents.add(item.value.value)
    assert referenced_agents.issubset(set(manifest["agents"]))
    custom_tools = set(manifest["custom_tools"])
    for name in manifest["agents"]:
        folder = bundle / "plugins/agents" / name
        agent = yaml.safe_load((folder / "agent.yaml").read_text(encoding="utf-8-sig"))
        assert agent["name"] == name
        prompt = folder / agent["prompt_file"]
        assert prompt.is_file() and prompt.relative_to(bundle).as_posix() in listed
        assert set(agent.get("tools", [])).issubset(BUILTIN_TOOLS | custom_tools)
    for name in custom_tools:
        path = bundle / "plugins/tools/api" / (name + ".yaml")
        tool = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
        assert tool["name"] == name and tool["handler"]["type"] == "script"
        script = path.with_name(tool["handler"]["script_file"])
        assert script.relative_to(bundle).as_posix() in listed
        tree = ast.parse(script.read_text(encoding="utf-8-sig"))
        assert any(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == tool["handler"]["function"] for node in tree.body)
    runtime = json.loads((bundle / "runtime/version.json").read_text(encoding="utf-8"))
    assert (bundle / "runtime" / runtime["patch"]).is_file()
    return {"workflows": len(workflows), "nodes": node_count, "agents": len(manifest["agents"]), "custom_tools": len(custom_tools), "verified_plugin_files": len(listed)}


if __name__ == "__main__":
    print(json.dumps(verify(), ensure_ascii=False, indent=2))
