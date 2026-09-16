"""Vertical Shorts/Reels/TikToks cut from the rendered video, with word-by-word captions."""
from __future__ import annotations

from pathlib import Path

from . import ff, graphics
from .config import Project, ShortSpec
from .log import ok, warn
from .render import load_manifest


def _display_words(words, lexicon: dict[str, str]):
    """Undo pronunciation respellings so captions show the real spelling."""
    rev = {v.lower(): k for k, v in lexicon.items() if " " not in v}
    out = []
    for st, d, w in words:
        core = w.strip(".,!?;:\"'")
        out.append((st, d, w.replace(core, rev.get(core.lower(), core)) if core else w))
    return out


def caption_groups(words, start: float, end: float, max_words: int = 3, max_gap: float = 0.6):
    """Group words into short on-screen phrases, times relative to `start`."""
    groups, cur = [], []
    for st, d, w in words:
        if st < start - 0.05 or st >= end:
            continue
        if cur and (len(cur) >= max_words or st - (cur[-1][0] + cur[-1][1]) > max_gap
                    or cur[-1][2].rstrip()[-1:] in ".!?,"):
            groups.append(cur)
            cur = []
        cur.append((st, d, w))
    if cur:
        groups.append(cur)
    out = []
    for i, g in enumerate(groups):
        a = g[0][0] - start
        b = (groups[i + 1][0][0] - start) if i + 1 < len(groups) else (g[-1][0] + g[-1][1] - start + 0.3)
        b = min(b, g[-1][0] + g[-1][1] - start + 0.6, end - start)
        text = " ".join(w for _, _, w in g).upper()
        out.append((round(max(0.0, a), 3), round(max(a + 0.2, b), 3), text))
    return out


def make_short(proj: Project, spec: ShortSpec, out_dir: Path | None = None) -> Path:
    man = load_manifest(proj)
    src = Path(man["output"])
    pieces = man["pieces"]
    if spec.segment is not None:
        seg = next((p for p in pieces if p["kind"] == "segment" and p["index"] == spec.segment), None)
        if seg is None:
            raise ValueError(f"short '{spec.name}': segment {spec.segment} not found in the render")
        start = seg["start"] + 0.3
        dur = spec.duration or min(seg["duration"] - 0.6, 59.0)
        hook = spec.hook or (seg["label"] or "").upper()
    else:
        start = spec.start or 0.0
        dur = spec.duration or 45.0
        hook = spec.hook
    dur = round(min(dur, man["duration"] - start), 3)
    if dur > 180:
        warn(f"short '{spec.name}' is {dur:.0f}s - YouTube Shorts are capped at 3 minutes")
    elif dur > 60:
        warn(f"short '{spec.name}' is {dur:.0f}s - fine for YouTube Shorts, but some platforms cap at 60s")
    out_dir = out_dir or proj.path(proj.output.path).parent
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"short_{spec.name}.mp4"
    work = proj.work / "shorts"
    work.mkdir(parents=True, exist_ok=True)
    font = graphics.local_font(work, "display")
    txt = ff.TextFiles(work, spec.name)
    W, H = 1080, 1920
    vertical_src = man.get("format") == "vertical"
    if vertical_src:
        fc = [f"[0:v]scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2[v0]"]
    else:
        fc = [f"[0:v]split=2[bg][fg];"
              f"[bg]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},gblur=sigma=28,"
              f"eq=brightness=-0.25[bgb];"
              f"[fg]scale={W}:-2[fgs];[bgb][fgs]overlay=(W-w)/2:(H-h)/2[v0]"]
    draws = []
    accent = graphics.ffcolor(proj.brand.accent)
    if hook:
        draws.append(f"drawtext=fontfile={font}:textfile={txt(hook)}:fontcolor=white:fontsize=72:"
                     f"borderw=6:bordercolor=black:x=(w-text_w)/2:y=260:box=1:boxcolor=0xE74C3C:boxborderw=24")
    if spec.cta:
        draws.append(f"drawtext=fontfile={font}:textfile={txt(spec.cta)}:fontcolor=white:fontsize=46:"
                     f"borderw=4:bordercolor=black:x=(w-text_w)/2:y=h-300:box=1:boxcolor=0x000000AA:boxborderw=18")
    if spec.captions:
        words = [tuple(w) for p in pieces for w in p["words"]]
        words = _display_words(words, proj.voice.lexicon)
        for a, b, text in caption_groups(words, start, start + dur):
            draws.append(f"drawtext=fontfile={font}:textfile={txt(text)}:fontcolor={accent}:fontsize=92:"
                         f"borderw=8:bordercolor=black:x=(w-text_w)/2:y=h*0.64:"
                         f"enable='between(t,{a},{b})'")
    if draws:
        fc.append("[v0]" + ",".join(draws) + "[v]")
    else:
        fc.append("[v0]null[v]")
    ff.run(["-y", "-ss", round(start, 3), "-t", dur, "-i", src.resolve(), "-filter_complex", ";".join(fc),
            "-map", "[v]", "-map", "0:a?", "-r", proj.output.fps, "-c:v", "libx264", "-preset", "veryfast",
            "-crf", 20, "-pix_fmt", "yuv420p", "-c:a", "aac", "-ar", "48000", "-b:a", "192k",
            "-af", "afade=t=in:d=0.2,afade=t=out:st=" + str(round(max(0, dur - 0.5), 2)) + ":d=0.5",
            "-movflags", "+faststart", out.resolve()], cwd=work, desc=f"short {spec.name}")
    ok(f"short {out} ({dur:.1f}s)")
    return out
