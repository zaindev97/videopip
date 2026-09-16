"""MCP server: lets Claude Desktop, Claude Code, Cursor, Windsurf, etc. drive videopip.

Run:  videopip-mcp        (or: python -m videopip.mcp_server)

Typical AI flow:
  1. get_guide()                      -> how to turn a messy brief into a spec
  2. analyze_clips(folder)            -> durations, safe-range suggestions
  3. write project.yaml (with the AI's own file tools, or write_project())
  4. preflight(project)               -> fix every error it reports
  5. render_start(project) + render_status(job) -> finished video
"""
from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
import uuid
from importlib import resources
from pathlib import Path

try:  # mcp >= 2
    from mcp.server.mcpserver import MCPServer as _Server
except ImportError:
    try:  # mcp 1.x
        from mcp.server.fastmcp import FastMCP as _Server
    except ImportError as e:  # pragma: no cover
        raise SystemExit("The MCP server needs the `mcp` package: pip install \"videopip[mcp]\"") from e

from .log import console as _console

# stdout carries the JSON-RPC stream; all human-readable logging must go to stderr
_console.file = sys.stderr

server = _Server("videopip")
_JOBS: dict[str, dict] = {}


def _guide_text() -> str:
    return resources.files("videopip").joinpath("guide.md").read_text(encoding="utf-8")


@server.tool()
def get_guide() -> str:
    """How to turn a user's loose video request into a valid VideoPip project.yaml (read this first)."""
    return _guide_text()


@server.tool()
def get_schema() -> str:
    """JSON schema for project.yaml."""
    from .config import json_schema
    return json.dumps(json_schema())


@server.tool()
def get_template(name: str = "product-countdown") -> str:
    """A commented starter project.yaml. Names: product-countdown, vertical-short."""
    from .scaffold import template_text
    return template_text(name)


@server.tool()
def list_assets() -> dict:
    """Builtin sounds, overlay templates and project templates."""
    from .motion import BUILTIN
    from .scaffold import TEMPLATES
    from .sfx import RECIPES
    return {"sounds": [f"builtin:{k}" for k in RECIPES], "overlays": list(BUILTIN),
            "project_templates": list(TEMPLATES), "subscribe_sources": ["builtin", "<path to green-screen clip>"]}


@server.tool()
def analyze_clips(path: str, contact_sheets: bool = True) -> list[dict]:
    """Analyze a clip or a folder of clips: duration, size, static stretches (likely logo/text cards),
    scene cuts, suggested safe ranges and action peaks. Contact sheets (timestamped frame grids) are
    written next to the clips in `_sheets/` - LOOK at them before trusting the suggestions."""
    from .analysis import analyze_clip
    from .scaffold import VIDEO_EXT
    p = Path(path)
    files = [p] if p.is_file() else sorted(f for f in p.iterdir() if f.suffix.lower() in VIDEO_EXT)
    sheets = (p if p.is_dir() else p.parent) / "_sheets" if contact_sheets else None
    return [analyze_clip(f, sheets) for f in files]


@server.tool()
def init_project(folder: str, template: str = "product-countdown", clips_folder: str | None = None,
                 overwrite: bool = False) -> str:
    """Create a starter project.yaml in `folder` (optionally pre-filled from a folder of clips)."""
    from .scaffold import init
    return str(init(Path(folder), template, Path(clips_folder) if clips_folder else None, True, overwrite))


@server.tool()
def write_project(path: str, yaml_text: str) -> dict:
    """Validate YAML against the schema and write it to `path` only if valid."""
    import yaml
    from pydantic import ValidationError
    from .config import Project
    try:
        Project.model_validate(yaml.safe_load(yaml_text))
    except ValidationError as e:
        return {"written": False, "errors": [f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors()]}
    except Exception as e:
        return {"written": False, "errors": [str(e)]}
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(yaml_text, encoding="utf-8")
    return {"written": True, "path": path}


@server.tool()
def preflight(project: str, exact_timing: bool = True, scan_cards: bool = False) -> dict:
    """Check a project before rendering. Returns errors/warnings with suggested fixes and a runtime
    estimate. exact_timing renders (and caches) the voiceover for precise timings."""
    from pydantic import ValidationError
    from .config import load
    from .preflight import run
    try:
        proj = load(project)
    except ValidationError as e:
        return {"ok": False, "issues": [{"level": "error", "where": ".".join(map(str, x["loc"])),
                                         "message": x["msg"]} for x in e.errors()]}
    return run(proj, synth=exact_timing, scan_cards=scan_cards).to_dict()


def _run_job(job_id: str, args: list[str]):
    job = _JOBS[job_id]
    proc = subprocess.Popen([sys.executable, "-m", "videopip", *args], stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                            env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8", "COLUMNS": "120"})
    job["pid"] = proc.pid
    for line in proc.stdout:
        job["log"].append(line.rstrip())
        del job["log"][:-400]
    proc.wait()
    job["exit_code"] = proc.returncode
    job["status"] = "done" if proc.returncode == 0 else "failed"
    job["finished"] = time.time()


@server.tool()
def render_start(project: str, force: bool = False) -> dict:
    """Start rendering in the background (takes minutes). Poll render_status(job_id)."""
    job_id = uuid.uuid4().hex[:8]
    args = ["render", project] + (["--force"] if force else [])
    _JOBS[job_id] = {"status": "running", "log": [], "started": time.time(), "project": project}
    threading.Thread(target=_run_job, args=(job_id, args), daemon=True).start()
    return {"job_id": job_id, "status": "running"}


@server.tool()
def render_status(job_id: str, tail: int = 25) -> dict:
    """Status and last log lines of a render job."""
    job = _JOBS.get(job_id)
    if not job:
        return {"error": f"unknown job {job_id}"}
    return {"status": job["status"], "elapsed_s": round((job.get("finished") or time.time()) - job["started"]),
            "exit_code": job.get("exit_code"), "log_tail": job["log"][-tail:]}


@server.tool()
def verify_video(path: str) -> dict:
    """QA a finished video: freezes, black frames, loudness, dimensions."""
    from .verify import verify
    return verify(Path(path))


@server.tool()
def make_shorts(project: str) -> list[str]:
    """(Re)build the project's vertical shorts from the last render."""
    from .config import load
    from .shorts import make_short
    proj = load(project)
    return [str(make_short(proj, s)) for s in proj.shorts]


@server.tool()
def get_metadata(project: str) -> str:
    """Title/description/chapters/tags text built from the last render."""
    from .config import load
    from .publish import make_metadata
    return make_metadata(load(project)).read_text(encoding="utf-8")


@server.tool()
def audition_voice(text: str, voice: str = "en-US-AndrewMultilingualNeural", out: str = "audition.wav") -> dict:
    """Render a short line to a WAV so the user can check a voice or a pronunciation fix."""
    import shutil
    from .config import VoiceSpec
    from .tts import synthesize
    sp = synthesize(text, VoiceSpec(voice=voice))
    shutil.copy(sp.wav, out)
    return {"file": str(Path(out).resolve()), "duration": sp.duration}


def main():
    server.run()


if __name__ == "__main__":
    main()
