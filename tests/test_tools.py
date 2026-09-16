"""CLI, MCP and generated-docs checks (fast, no rendering)."""
import asyncio
import subprocess
import sys
from pathlib import Path

import yaml
from typer.testing import CliRunner

from videopip.cli import app

ROOT = Path(__file__).resolve().parents[1]
runner = CliRunner()


def test_cli_schema_and_validate(tmp_path):
    r = runner.invoke(app, ["schema"])
    assert r.exit_code == 0 and '"segments"' in r.stdout
    r = runner.invoke(app, ["init", str(tmp_path / "proj")])
    assert r.exit_code == 0, r.stdout
    r = runner.invoke(app, ["validate", str(tmp_path / "proj" / "project.yaml")])
    assert r.exit_code == 0, r.stdout


def test_cli_rejects_bad_spec(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text(yaml.safe_dump({"clips": {"a": "a.mp4"}, "segments": [{"title": "x", "clips": ["zz"], "vo": "v"}]}))
    r = runner.invoke(app, ["validate", str(p)])
    assert r.exit_code == 2 and "unknown clip id" in r.stdout


def test_init_from_folder(tmp_path, clips_dir):
    r = runner.invoke(app, ["init", str(tmp_path / "p"), "--clips", str(clips_dir)])
    assert r.exit_code == 0, r.stdout
    data = yaml.safe_load((tmp_path / "p" / "project.yaml").read_text(encoding="utf-8"))
    assert len(data["clips"]) == 3 and len(data["segments"]) == 3
    assert data["clips"]["c1"]["safe"][0][0] >= 1.8   # the fake logo card is excluded
    assert data["intro"]["shots"][0]["role"] == "hero"


def test_generated_docs_in_sync():
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "sync_docs.py"), "--check"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout


def test_mcp_tools_registered(tmp_path):
    from videopip import mcp_server
    names = {t.name for t in asyncio.run(mcp_server.server.list_tools())}
    for n in ("get_guide", "analyze_clips", "write_project", "preflight", "render_start", "render_status"):
        assert n in names
    bad = mcp_server.write_project(str(tmp_path / "x.yaml"), "clips: {}\nsegments: [{title: a}]")
    assert bad["written"] is False and bad["errors"]
    assert "guide for AI assistants" in mcp_server.get_guide()


def test_plugin_manifests():
    import json
    m = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text())
    assert m["plugins"][0]["source"] == "./plugin"
    assert json.loads((ROOT / "plugin" / ".claude-plugin" / "plugin.json").read_text())["name"] == "videopip"
    skill = (ROOT / "plugin" / "skills" / "videopip" / "SKILL.md").read_text(encoding="utf-8")
    assert skill.startswith("---\nname: videopip\n")
