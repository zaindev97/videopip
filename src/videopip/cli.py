"""videopip command line."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

import typer
from pydantic import ValidationError
from rich.markup import escape
from rich.table import Table

from . import __version__
from .log import console

app = typer.Typer(add_completion=False, no_args_is_help=True, rich_markup_mode="rich",
                  help="[bold]VideoPip[/bold] - describe a video, let your AI write the spec, render it with one command.")


def _load(project: Path):
    from .config import load
    try:
        return load(project)
    except FileNotFoundError:
        console.print(f"[red]project file not found:[/red] {project}")
        raise typer.Exit(2)
    except ValidationError as e:
        console.print(f"[red]spec is invalid ({e.error_count()} problem(s)):[/red]")
        for err in e.errors():
            loc = ".".join(str(x) for x in err["loc"])
            console.print(f"  - [bold]{loc or 'project'}[/bold]: {err['msg']}")
        raise typer.Exit(2)
    except Exception as e:
        console.print(f"[red]could not load {project}:[/red] {e}")
        raise typer.Exit(2)


def _print_report(rep, as_json: bool):
    if as_json:
        print(json.dumps(rep.to_dict(), indent=1))
        return
    colors = {"error": "red", "warning": "yellow", "info": "dim"}
    for i in rep.issues:
        console.print(f"[{colors[i.level]}]{i.level.upper():7}[/] [bold]{i.where}[/bold]: {i.message}"
                      + (f"\n          [dim]fix: {i.fix}[/dim]" if i.fix else ""))
    est = rep.estimate
    if est.get("runtime"):
        console.print(f"\nestimated runtime [bold]{est['runtime_hms']}[/bold] ({est['timing']})"
                      + (f", intro {est['intro']}s" if est.get("intro") else ""))
    console.print(f"\n{'[green]PREFLIGHT OK[/green]' if rep.ok else '[red]PREFLIGHT FAILED[/red]'} - "
                  f"{len(rep.errors)} error(s), {sum(i.level == 'warning' for i in rep.issues)} warning(s)")


@app.command()
def version():
    """Print the version."""
    console.print(__version__)


@app.command()
def setup(full: bool = typer.Option(False, "--full", help="Also install librosa, MCP and Playwright+Chromium.")):
    """Install everything a render needs (ffmpeg, fonts, builtin assets)."""
    from .setup_deps import setup as do_setup
    do_setup(full=full, log=lambda m: console.print(f"[cyan]>>[/cyan] {m}"))
    doctor()


@app.command()
def doctor():
    """Check your system: ffmpeg, filters, fonts, voices, optional extras."""
    from .setup_deps import doctor as do_doctor
    t = Table(title="videopip doctor", show_lines=False)
    t.add_column("check")
    t.add_column("")
    t.add_column("details", overflow="fold")
    bad = False
    for name, ok_, msg in do_doctor():
        opt = name.startswith("optional")
        t.add_row(name, "[green]OK[/green]" if ok_ else ("[yellow]--[/yellow]" if opt else "[red]MISSING[/red]"),
                  escape(msg))
        bad |= (not ok_ and not opt)
    console.print(t)
    if bad:
        console.print("[red]Required pieces are missing - run `videopip setup`.[/red]")
        raise typer.Exit(1)


@app.command()
def init(path: Path = typer.Argument(Path("."), help="Folder (or .yaml path) for the new project."),
         template: str = typer.Option("product-countdown", "--template", "-t",
                                      help="product-countdown | vertical-short"),
         clips: Optional[Path] = typer.Option(None, "--clips", "-c", help="Build clips/segments from this folder."),
         no_analyze: bool = typer.Option(False, "--no-analyze", help="Skip safe-range suggestions."),
         force: bool = typer.Option(False, "--force")):
    """Create a starter project.yaml."""
    from .scaffold import init as do_init
    try:
        p = do_init(path, template, clips, not no_analyze, force)
    except (FileExistsError, FileNotFoundError, ValueError) as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    console.print(f"[green]created[/green] {p}\nnext: edit it (or ask your AI assistant to), then "
                  f"`videopip preflight {p}` and `videopip render {p}`")


@app.command()
def demo(path: Path = typer.Argument(Path("videopip-demo")),
         offline: bool = typer.Option(False, "--offline", help="Silent voice (no internet needed)."),
         no_render: bool = typer.Option(False, "--no-render")):
    """Create (and render) a demo project with generated footage - no clips needed."""
    from .demo import create
    p = create(path, offline)
    console.print(f"[green]demo project[/green] {p}")
    if not no_render:
        render(p, force=False, skip_preflight=False, no_extras=False, no_verify=False)


@app.command()
def guide():
    """Print the guide AI assistants follow to turn a request into a spec."""
    from importlib import resources
    print(resources.files("videopip").joinpath("guide.md").read_text(encoding="utf-8"))


@app.command()
def schema(out: Optional[Path] = typer.Option(None, "--out", "-o")):
    """Print the JSON schema of project.yaml (for AI tools and editors)."""
    from .config import json_schema
    s = json.dumps(json_schema(), indent=1)
    if out:
        out.write_text(s, encoding="utf-8")
        console.print(f"wrote {out}")
    else:
        print(s)


@app.command()
def validate(project: Path):
    """Check that project.yaml is structurally valid (fast, no media access)."""
    p = _load(project)
    console.print(f"[green]valid[/green]: {len(p.clips)} clips, {len(p.segments)} segments, format {p.output.format}")


@app.command()
def analyze(target: Path = typer.Argument(..., help="A clip or a folder of clips."),
            sheets: Optional[Path] = typer.Option(None, "--sheets", help="Write contact sheets here."),
            as_json: bool = typer.Option(False, "--json")):
    """Scan footage: duration, logo/text-card candidates, scene cuts, suggested safe ranges, action peaks."""
    from .analysis import analyze_clip
    from .scaffold import VIDEO_EXT
    files = [target] if target.is_file() else sorted(p for p in target.iterdir() if p.suffix.lower() in VIDEO_EXT)
    results = []
    for f in files:
        if not as_json:
            console.print(f"[cyan]analyzing[/cyan] {f.name} ...")
        r = analyze_clip(f, sheets)
        results.append(r)
        if not as_json:
            console.print(f"  duration {r['duration']}s  size {r['size']}  audio {r['has_audio']}")
            console.print(f"  static (possible logo/text cards): {r['static_runs']}")
            console.print(f"  suggested safe: [bold]{r['suggested_safe']}[/bold]")
            console.print(f"  action peaks: {r['action_peaks']}")
            if r.get("contact_sheet"):
                console.print(f"  contact sheet: {r['contact_sheet']}")
    if as_json:
        print(json.dumps(results, indent=1))


@app.command()
def preflight(project: Path,
              no_tts: bool = typer.Option(False, "--no-tts", help="Estimate timings from word counts (offline)."),
              scan_cards: bool = typer.Option(False, "--scan-cards", help="Flag static stretches inside safe ranges."),
              as_json: bool = typer.Option(False, "--json")):
    """Validate files, ranges, intro timing and runtime BEFORE rendering."""
    from .preflight import run
    p = _load(project)
    rep = run(p, synth=not no_tts, scan_cards=scan_cards)
    _print_report(rep, as_json)
    if not rep.ok:
        raise typer.Exit(1)


@app.command()
def render(project: Path,
           force: bool = typer.Option(False, "--force", help="Re-render every piece (ignore the cache)."),
           skip_preflight: bool = typer.Option(False, "--skip-preflight"),
           no_extras: bool = typer.Option(False, "--no-extras", help="Skip shorts, thumbnail and metadata."),
           no_verify: bool = typer.Option(False, "--no-verify")):
    """Render the video (+ shorts, thumbnail, metadata, QA check)."""
    from .ff import FFmpegError
    from .planner import PlanError
    p = _load(project)
    if not skip_preflight:
        from .preflight import run
        console.print("[bold]preflight[/bold]")
        rep = run(p)
        if not rep.ok:
            _print_report(rep, False)
            raise typer.Exit(1)
        for i in rep.issues:
            if i.level == "warning":
                console.print(f"   [yellow]! {i.where}: {i.message}[/yellow]")
        console.print(f"   estimated runtime {rep.estimate.get('runtime_hms')}")
    from .render import Renderer
    try:
        man = Renderer(p, force=force).render()
        if not no_extras:
            from .publish import make_metadata, make_thumbnail
            from .shorts import make_short
            for sh in p.shorts:
                make_short(p, sh)
            make_thumbnail(p)
            make_metadata(p)
        if not no_verify:
            from .verify import verify as do_verify
            v = do_verify(Path(man["output"]), p.output.lufs)
            if v["ok"]:
                console.print("[green]QA passed[/green]: no freezes, no black gaps, loudness on target")
            else:
                for x in v["issues"]:
                    console.print(f"[yellow]QA: {x}[/yellow]")
    except (FFmpegError, PlanError, FileNotFoundError, ValueError) as e:
        console.print(f"[red]render failed:[/red] {e}")
        raise typer.Exit(1)
    console.print(f"\n[bold green]done[/bold green] -> {man['output']}")


@app.command()
def short(project: Path, name: Optional[str] = typer.Argument(None, help="Short name (default: all).")):
    """(Re)build vertical shorts from the last render."""
    from .shorts import make_short
    p = _load(project)
    todo = [s for s in p.shorts if name in (None, s.name)]
    if not todo:
        console.print("[yellow]no matching shorts in the project[/yellow]")
        raise typer.Exit(1)
    for s in todo:
        make_short(p, s)


@app.command()
def thumbnail(project: Path):
    """(Re)build the thumbnail."""
    from .publish import make_thumbnail
    make_thumbnail(_load(project))


@app.command()
def metadata(project: Path):
    """(Re)write title / description / chapters / tags from the last render."""
    from .publish import make_metadata
    out = make_metadata(_load(project))
    print(out.read_text(encoding="utf-8"))


@app.command()
def verify(video: Path, lufs: float = -14.0, as_json: bool = typer.Option(False, "--json")):
    """QA a finished video: freezes, black frames, loudness, dimensions."""
    from .verify import verify as do_verify
    r = do_verify(video, lufs)
    if as_json:
        print(json.dumps(r, indent=1))
        return
    console.print(f"{video}: {r['duration']}s {r['size']} {r['lufs']} LUFS")
    for x in r["issues"]:
        console.print(f"  [yellow]! {x}[/yellow]")
    console.print("[green]OK[/green]" if r["ok"] else "[red]issues found[/red]")
    if not r["ok"]:
        raise typer.Exit(1)


@app.command()
def voices(lang: str = typer.Option("en-", help="Locale prefix, e.g. en-US, es-, hi-IN.")):
    """List free Edge voices."""
    from .tts import list_edge_voices
    for v in list_edge_voices(lang):
        print(v)


@app.command()
def say(text: str, out: Path = typer.Option(Path("say.wav"), "--out", "-o"),
        voice: str = "en-US-AndrewMultilingualNeural", engine: str = "edge"):
    """Render a line of voiceover to a file (to audition voices/pronunciations)."""
    import shutil
    from .config import VoiceSpec
    from .tts import synthesize
    sp = synthesize(text, VoiceSpec(engine=engine, voice=voice))
    shutil.copy(sp.wav, out)
    console.print(f"{out} ({sp.duration:.2f}s, {len(sp.sentences)} sentence(s))")


@app.command()
def assets():
    """List builtin sounds, motion templates and project templates."""
    from .motion import BUILTIN
    from .scaffold import TEMPLATES
    from .sfx import RECIPES
    console.print("[bold]sounds[/bold]: " + ", ".join(f"builtin:{k}" for k in RECIPES))
    console.print("[bold]overlays[/bold]: " + ", ".join(BUILTIN) + ", or a path to your own .html")
    console.print("[bold]project templates[/bold]: " + ", ".join(TEMPLATES))
    console.print("[bold]subscribe[/bold]: builtin, or a green-screen clip path")


@app.command("clear-cache")
def clear_cache():
    """Delete cached voiceovers (forces fresh TTS)."""
    from .tts import clear_cache as cc
    console.print(f"removed {cc()} cached file(s)")


@app.command()
def upload(video: Path, title: str = typer.Option(...), description_file: Optional[Path] = None,
           tags: str = "", privacy: str = typer.Option("private", help="private | unlisted | public"),
           thumbnail_file: Optional[Path] = typer.Option(None, "--thumbnail"),
           client_secret: Path = typer.Option(..., help="OAuth client JSON from Google Cloud (YouTube Data API v3).")):
    """Upload to YouTube with YOUR OWN Google OAuth credentials (default: private)."""
    from .upload import upload_video
    desc = description_file.read_text(encoding="utf-8") if description_file else ""
    vid = upload_video(video, title, desc, [t.strip() for t in tags.split(",") if t.strip()],
                       privacy, client_secret, thumbnail_file)
    console.print(f"[green]uploaded[/green] https://youtu.be/{vid} ({privacy})")


@app.command()
def mcp():
    """Run the MCP server (stdio) so AI tools can drive videopip."""
    from .mcp_server import main
    main()


def run():
    try:
        app()
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    run()
