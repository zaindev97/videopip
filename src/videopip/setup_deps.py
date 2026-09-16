"""`videopip setup` and `videopip doctor`: install/verify everything a render needs."""
from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

from .graphics import FONT_DIR

FONTS = {
    # all SIL Open Font License - free to download and use
    "Lato-Bold.ttf": "https://github.com/google/fonts/raw/main/ofl/lato/Lato-Bold.ttf",
    "Lato-BoldItalic.ttf": "https://github.com/google/fonts/raw/main/ofl/lato/Lato-BoldItalic.ttf",
    "Anton-Regular.ttf": "https://github.com/google/fonts/raw/main/ofl/anton/Anton-Regular.ttf",
}

OPTIONAL = {
    "librosa": ("audio", "smarter action-window detection (audio onsets) and SFX loudest-window picking"),
    "playwright": ("motion", "custom HTML/CSS motion-graphics templates"),
    "mcp": ("mcp", "MCP server for Claude Desktop / Cursor / other AI tools"),
    "openai": ("openai", "OpenAI text-to-speech"),
    "rembg": ("cutout", "background removal for thumbnails"),
    "googleapiclient": ("youtube", "YouTube upload"),
}


def _has(mod: str) -> bool:
    return importlib.util.find_spec(mod) is not None


def pip_install(*pkgs: str) -> bool:
    r = subprocess.run([sys.executable, "-m", "pip", "install", *pkgs])
    return r.returncode == 0


def check_ffmpeg() -> tuple[bool, str]:
    from . import ff
    try:
        ff.binaries.cache_clear()
        a, b = ff.binaries()
        out = subprocess.run([a, "-version"], capture_output=True, text=True).stdout.splitlines()[0]
        return True, f"{out}  ({a})"
    except Exception as e:
        return False, str(e)


def check_filters() -> list[str]:
    from . import ff
    need = {"xfade", "acrossfade", "sidechaincompress", "chromakey", "delogo", "drawtext", "loudnorm",
            "freezedetect", "gblur", "alimiter", "afreqshift"}
    try:
        have = ff.filters_available()
    except Exception:
        return sorted(need)
    return sorted(need - have)


def check_fonts() -> tuple[bool, str]:
    from .graphics import find_font
    try:
        return True, ", ".join(f"{k}={Path(find_font(k)).name}" for k in ("bold", "bolditalic", "display"))
    except FileNotFoundError as e:
        return False, str(e)


def download_fonts(log=print) -> None:
    FONT_DIR.mkdir(parents=True, exist_ok=True)
    for name, url in FONTS.items():
        dst = FONT_DIR / name
        if dst.exists():
            continue
        log(f"downloading font {name}")
        try:
            urllib.request.urlretrieve(url, dst)
        except Exception as e:
            log(f"  failed: {e}")


def check_edge_tts() -> tuple[bool, str]:
    return (_has("edge_tts"), "edge-tts installed" if _has("edge_tts") else "edge-tts missing")


def doctor() -> list[tuple[str, bool, str]]:
    rows = []
    rows.append(("python", sys.version_info >= (3, 10), sys.version.split()[0]))
    ok, msg = check_ffmpeg()
    rows.append(("ffmpeg", ok, msg))
    if ok:
        missing = check_filters()
        rows.append(("ffmpeg filters", not missing, "all present" if not missing else
                     f"missing: {', '.join(missing)} - install a 'full' ffmpeg build"))
    rows.append(("fonts",) + check_fonts())
    rows.append(("voice (edge-tts)",) + check_edge_tts())
    for mod, (extra, why) in OPTIONAL.items():
        rows.append((f"optional: {mod}", _has(mod), f"{why}  ->  pip install \"videopip[{extra}]\""
                     if not _has(mod) else why))
    if _has("playwright"):
        if os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
            base = Path(os.environ["PLAYWRIGHT_BROWSERS_PATH"])
        elif sys.platform == "win32":
            base = Path.home() / "AppData/Local/ms-playwright"
        elif sys.platform == "darwin":
            base = Path.home() / "Library/Caches/ms-playwright"
        else:
            base = Path.home() / ".cache/ms-playwright"
        chromium = base.exists() and any(base.glob("chromium*"))
        rows.append(("optional: chromium", chromium, "for HTML templates" if chromium else
                     "run: playwright install chromium"))
    return rows


def setup(full: bool = False, log=print) -> None:
    ok, msg = check_ffmpeg()
    if not ok:
        log("ffmpeg not found - installing static-ffmpeg (downloads a build for your OS)...")
        if not _has("static_ffmpeg"):
            pip_install("static-ffmpeg")
        try:
            from static_ffmpeg import run as sf_run  # type: ignore
            sf_run.get_or_fetch_platform_executables_else_raise()
        except Exception as e:
            log(f"could not download ffmpeg automatically: {e}")
            log("install it manually: https://ffmpeg.org/download.html (Windows: `winget install Gyan.FFmpeg`)")
    download_fonts(log)
    if full:
        want = ["librosa", "mcp", "playwright"]
        missing = [m for m in want if not _has(m)]
        if missing:
            log(f"installing optional extras: {', '.join(missing)}")
            pip_install(*missing)
        if _has("playwright") or "playwright" in missing:
            log("installing Chromium for motion templates...")
            subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"])
    log("pre-building builtin assets (subscribe animation, sound effects)...")
    try:
        from . import graphics, sfx
        for name in sfx.RECIPES:
            sfx.builtin(name)
        graphics.builtin_subscribe(5.0, 30)
    except Exception as e:
        log(f"  asset build failed: {e}")
    if shutil.which("videopip") is None:
        log("note: the `videopip` command is not on PATH; use `python -m videopip` or install with pipx.")
