"""Built-in sound effects synthesized with ffmpeg (no redistribution issues)."""
from __future__ import annotations

from pathlib import Path

from . import ff
from .graphics import ASSET_DIR

RECIPES = {
    # airy transition swoosh
    "whoosh": ("anoisesrc=d=1.0:c=pink:a=0.9,highpass=f=350,lowpass=f=5200,"
               "afade=t=in:d=0.45:curve=exp,afade=t=out:st=0.45:d=0.55:curve=exp,"
               "aecho=0.6:0.4:40:0.25,volume=1.4"),
    # low punchy hit for cold opens
    "impact": ("sine=f=55:d=0.9,volume=2.2[s];anoisesrc=d=0.25:c=brown:a=0.9,lowpass=f=900[n];"
               "[s][n]amix=inputs=2:normalize=0,afade=t=out:st=0.05:d=0.85:curve=exp"),
    # rising tension
    "riser": ("anoisesrc=d=2.0:c=white:a=0.5,highpass=f=200,"
              "vibrato=f=6:d=0.3,afade=t=in:d=1.9:curve=exp,afade=t=out:st=1.9:d=0.1"),
    # UI click (subscribe button)
    "click": ("sine=f=2400:d=0.04,volume=1.5[a];anoisesrc=d=0.03:c=white:a=0.6,highpass=f=3000[b];"
              "[a][b]amix=inputs=2:normalize=0,afade=t=out:st=0.005:d=0.035"),
    # soft pop for overlays
    "pop": "sine=f=660:d=0.12,afreqshift=shift=-300,afade=t=out:st=0.02:d=0.1,volume=1.2",
    # ding for verdicts / bell
    "ding": "sine=f=1318:d=1.2,afade=t=out:st=0.02:d=1.15:curve=exp,volume=0.8",
}


def resolve(name_or_path: str | None, project=None) -> Path | None:
    """'builtin:whoosh' -> generated file; a path -> resolved path; None -> None."""
    if not name_or_path:
        return None
    if name_or_path.startswith("builtin:"):
        return builtin(name_or_path.split(":", 1)[1])
    return project.path(name_or_path) if project else Path(name_or_path)


def builtin(name: str) -> Path:
    if name not in RECIPES:
        raise ValueError(f"unknown builtin sound '{name}'. Available: {', '.join(RECIPES)}")
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    out = ASSET_DIR / f"sfx_{name}_v1.wav"
    if not out.exists():
        graph = RECIPES[name]
        if ";" in graph or "[" in graph:
            ff.run(["-y", "-filter_complex", graph + ",aresample=48000,aformat=channel_layouts=stereo[o]",
                    "-map", "[o]", str(out)], desc=f"sfx {name}")
        else:
            ff.run(["-y", "-f", "lavfi", "-i", graph, "-af", "aresample=48000,aformat=channel_layouts=stereo",
                    str(out)], desc=f"sfx {name}")
    return out
