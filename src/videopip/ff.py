"""ffmpeg/ffprobe discovery and thin run helpers."""
from __future__ import annotations

import functools
import json
import os
import shutil
import subprocess
from pathlib import Path

from .log import console


class FFmpegError(RuntimeError):
    pass


@functools.lru_cache(maxsize=1)
def binaries() -> tuple[str, str]:
    """Return (ffmpeg, ffprobe). Order: env vars -> PATH -> static-ffmpeg download."""
    ff, fp = os.environ.get("VIDEOPIP_FFMPEG"), os.environ.get("VIDEOPIP_FFPROBE")
    if ff and fp:
        return ff, fp
    ff, fp = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if ff and fp:
        return ff, fp
    try:
        from static_ffmpeg import run as sf_run  # type: ignore
        ff, fp = sf_run.get_or_fetch_platform_executables_else_raise()
        return ff, fp
    except ImportError:
        pass
    raise FFmpegError("ffmpeg not found. Run `videopip setup` (downloads it) or install ffmpeg "
                      "and make sure it is on PATH.")


def ffmpeg() -> str:
    return binaries()[0]


def ffprobe() -> str:
    return binaries()[1]


def run(args: list, cwd: str | os.PathLike | None = None, desc: str = "") -> str:
    """Run ffmpeg (args WITHOUT the binary). Raises with the stderr tail on failure."""
    cmd = [ffmpeg(), "-hide_banner", "-nostdin"] + [str(a) for a in args]
    if os.environ.get("VIDEOPIP_DEBUG"):
        console.print(f"[dim]$ {' '.join(cmd)}[/dim]")
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise FFmpegError(f"ffmpeg failed{(' (' + desc + ')') if desc else ''}:\n{r.stderr[-2500:]}")
    return r.stderr


def run_capture(args: list, cwd=None) -> subprocess.CompletedProcess:
    cmd = [ffmpeg(), "-hide_banner", "-nostdin"] + [str(a) for a in args]
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")


@functools.lru_cache(maxsize=512)
def _probe(path: str, mtime: float) -> dict:
    r = subprocess.run([ffprobe(), "-v", "error", "-print_format", "json", "-show_format",
                        "-show_streams", path], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise FFmpegError(f"ffprobe could not read {path}: {r.stderr.strip()[-300:]}")
    return json.loads(r.stdout)


def probe(path: str | os.PathLike) -> dict:
    p = str(Path(path).resolve())
    if not os.path.exists(p):
        raise FileNotFoundError(p)
    return _probe(p, os.path.getmtime(p))


def duration(path) -> float:
    info = probe(path)
    d = info.get("format", {}).get("duration")
    if d is None:
        for s in info.get("streams", []):
            if s.get("duration"):
                return float(s["duration"])
        return 0.0
    return float(d)


def video_size(path) -> tuple[int, int] | None:
    for s in probe(path).get("streams", []):
        if s.get("codec_type") == "video":
            return int(s["width"]), int(s["height"])
    return None


def has_audio(path) -> bool:
    return any(s.get("codec_type") == "audio" for s in probe(path).get("streams", []))


class TextFiles:
    """drawtext reads its text from small files in the work dir (no escaping pitfalls:
    colons, quotes, commas and % all render literally). Paths are relative to `cwd`,
    so no Windows drive colon ever appears in a filtergraph."""

    def __init__(self, cwd: Path, prefix: str):
        self.cwd, self.prefix, self.n = Path(cwd), prefix, 0

    def __call__(self, text: str) -> str:
        name = f"txt_{self.prefix}_{self.n}.txt"
        self.n += 1
        (self.cwd / name).write_text(text, encoding="utf-8")
        return name


def filters_available() -> set[str]:
    r = run_capture(["-filters"])
    out = set()
    for line in r.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 3 and 2 <= len(parts[0]) <= 4 and set(parts[0]) <= set("TSC.") and "->" in parts[2]:
            out.add(parts[1])
    return out
