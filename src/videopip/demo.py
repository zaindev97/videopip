"""`videopip demo`: a self-contained project with generated footage, so anyone can
see the whole pipeline work in a couple of minutes without their own clips."""
from __future__ import annotations

from pathlib import Path

import yaml

from . import ff

SCENES = [
    # (name, lavfi source) - colourful moving patterns standing in for product footage
    ("gadget-1", "mandelbrot=s=1280x720:r=30:start_scale=2.5:end_scale=0.02"),
    ("gadget-2", "life=s=1280x720:r=30:mold=10:ratio=0.1:death_color=#1b1b3a:life_color=#39ff6e,scale=1280:720"),
    ("gadget-3", "cellauto=s=1280x720:r=30:rule=110,negate,hue=h=200:s=4"),
    ("gadget-4", "testsrc2=s=1280x720:r=30"),
]


def make_clips(dest: Path, seconds: float = 20.0) -> list[Path]:
    dest.mkdir(parents=True, exist_ok=True)
    out = []
    for i, (name, src) in enumerate(SCENES):
        p = dest / f"{name}.mp4"
        if not p.exists():
            ff.run(["-y", "-f", "lavfi", "-i", f"{src}", "-f", "lavfi",
                    "-i", f"sine=f={220 * (i + 2)}:d={seconds}:sample_rate=48000,volume=0.2",
                    "-t", seconds, "-vf", "format=yuv420p", "-c:v", "libx264", "-preset", "veryfast",
                    "-c:a", "aac", "-shortest", str(p)], desc=f"demo clip {name}")
        out.append(p)
    return out


def create(dest: Path, offline: bool = False) -> Path:
    dest = Path(dest)
    make_clips(dest / "clips")
    spec = {
        "version": 1,
        "name": "videopip-demo",
        "clips_dir": "clips",
        "clips": {f"g{i}": {"file": f"{n}.mp4", "safe": [[0.5, 19.5]]} for i, (n, _) in enumerate(SCENES, 1)},
        "voice": {"engine": "silent" if offline else "edge", "voice": "en-US-AndrewMultilingualNeural"},
        "sfx": {"whoosh": "builtin:whoosh", "cold_open": "builtin:impact", "cold_open_in": 0.0},
        "brand": {"banner_style": "dark"},
        "style": {"numbering": "countdown", "show_verdict": True},
        "intro": {
            "vo": ("This is VideoPip. It turns a plain spec into a finished video. "
                   "Every cut lands on the word. Four gadgets, one command, zero manual editing."),
            "shots": [{"clip": "g1", "range": [1.0, 15.0], "role": "hero"},
                      {"clip": "g2", "range": [2.0, 9.0], "role": "cue"},
                      {"clip": "g3", "range": [2.0, 9.0], "role": "cue"},
                      {"clip": "g4", "range": [2.0, 7.0], "role": "music"}],
            "subscribe": {"source": "builtin", "at": 11.0, "duration": 4.5},
        },
        "segments": [
            {"title": "The Fractal Gadget", "label": "Demo Co. Fractal Gadget", "clips": ["g1"],
             "vo": ("First up, the fractal gadget. It zooms forever, which is exactly what the voiceover "
                    "needs to fill this segment. Con? It never actually finishes. Worth it."),
             "verdict": "WORTH IT", "link": "https://example.com/fractal",
             "overlays": [{"template": "price_tag", "data": {"label": "Around", "price": "$29"},
                           "at": 3.5, "duration": 3.0}]},
            {"title": "The Life Simulator", "clips": ["g2"],
             "vo": ("Next, a life simulator. Tiny cells are born and die every frame, and the cuts walk "
                    "through the footage automatically. Con? The cells don't pay rent. Worth it."),
             "verdict": "WORTH IT", "link": "https://example.com/life",
             "overlays": [{"template": "rating", "data": {"stars": 4.5, "text": "4.5 out of 5"},
                           "at": 3.5, "duration": 3.0}]},
            {"title": "The Automaton", "clips": ["g3"],
             "vo": ("This one's rule one-ten, a cellular automaton that's technically a computer. "
                    "Con? It's slow at spreadsheets. Skip it unless you love patterns."),
             "verdict": "SKIP IT", "link": "https://example.com/automaton",
             "overlays": [{"template": "badge", "data": {"text": "NERD PICK", "color": "#39FF6E"},
                           "at": 3.5, "duration": 3.0, "position": "top-left", "width": 420, "height": 140}]},
            {"title": "The Test Pattern", "clips": ["g4"],
             "vo": ("And finally, the classic test pattern. Moving bars, a sweeping line, and perfect colour. "
                    "Con? Nobody's ever excited to see it. Worth it for nostalgia."),
             "verdict": "WORTH IT",
             "overlays": [{"template": "progress", "data": {"current": 4, "total": 4},
                           "at": 3.0, "duration": 3.0, "position": "bottom-left"}]},
        ],
        "outro": {"vo": "That's the demo. Now point VideoPip at your own clips. See you in the next one.",
                  "headline": "MADE WITH VIDEOPIP", "subline": "github.com/zaindev97/videopip"},
        "subscribe_mid": {"source": "builtin", "at": 40.0, "duration": 5.0},
        "output": {"path": "output/demo.mp4"},
        "shorts": [{"name": "fractal", "segment": 1, "hook": "THIS ZOOMS FOREVER"}],
        "thumbnail": {"headline": "4 DEMO GADGETS", "subline": "MADE BY ONE COMMAND"},
        "metadata": {"title": "VideoPip demo", "description": "Rendered entirely from a YAML spec.",
                     "tags": ["videopip", "demo"]},
    }
    p = dest / "project.yaml"
    p.write_text("# VideoPip demo project - generated by `videopip demo`\n"
                 + yaml.safe_dump(spec, sort_keys=False, width=110), encoding="utf-8")
    return p
