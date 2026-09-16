"""`videopip init`: create a starter project, optionally from a folder of clips."""
from __future__ import annotations

from importlib import resources
from pathlib import Path

import yaml

from . import analysis

TEMPLATES = {
    "product-countdown": "product-countdown.yaml",
    "vertical-short": "vertical-short.yaml",
}
VIDEO_EXT = {".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi"}


def template_text(name: str) -> str:
    fname = TEMPLATES.get(name)
    if not fname:
        raise ValueError(f"unknown template '{name}'. Available: {', '.join(TEMPLATES)}")
    return resources.files("videopip").joinpath("templates", fname).read_text(encoding="utf-8")


def init(dest: Path, template: str = "product-countdown", clips_dir: Path | None = None,
         analyze: bool = True, overwrite: bool = False) -> Path:
    dest = Path(dest)
    if dest.suffix not in (".yaml", ".yml"):
        dest.mkdir(parents=True, exist_ok=True)
        dest = dest / "project.yaml"
    if dest.exists() and not overwrite:
        raise FileExistsError(f"{dest} already exists (use --force to overwrite)")
    dest.parent.mkdir(parents=True, exist_ok=True)
    text = template_text(template)
    if clips_dir:
        text = _from_folder(text, dest.parent, Path(clips_dir), analyze)
    else:
        (dest.parent / "clips").mkdir(exist_ok=True)
    dest.write_text(text, encoding="utf-8")
    (dest.parent / "output").mkdir(exist_ok=True)
    gi = dest.parent / ".gitignore"
    if not gi.exists():
        gi.write_text(".videopip-work/\noutput/\n", encoding="utf-8")
    return dest


def _from_folder(text: str, base: Path, clips_dir: Path, analyze: bool) -> str:
    """Rewrite the template's clips/segments/intro to match the real files."""
    data = yaml.safe_load(text)
    files = sorted((p for p in clips_dir.iterdir() if p.suffix.lower() in VIDEO_EXT),
                   key=lambda p: (len(p.stem), p.stem))
    if not files:
        raise FileNotFoundError(f"no video files in {clips_dir}")
    try:
        rel = clips_dir.resolve().relative_to(base.resolve())
        data["clips_dir"] = rel.as_posix()
    except ValueError:
        data["clips_dir"] = str(clips_dir.resolve())
    clips, segs, shots = {}, [], []
    for i, f in enumerate(files, 1):
        cid = f"c{i}"
        entry = {"file": f.name}
        if analyze:
            safe = analysis.suggest_safe(f)
            entry["safe"] = [list(r) for r in safe] or None
            entry["notes"] = "auto-suggested safe ranges - verify against the contact sheet"
        clips[cid] = entry
        segs.append({
            "title": f"Product {i}", "clips": [cid],
            "vo": f"TODO: write the voiceover for product {i} - what it does, who it's for, one honest con, "
                  f"and a clear verdict.",
            "link": None,
        })
        if len(shots) < 4:
            rng = (entry.get("safe") or [[0.5, 8.0]])[0]
            a, b = rng[0], min(rng[1], rng[0] + 10)
            shots.append({"clip": cid, "range": [round(a, 1), round(b, 1)],
                          "role": "hero" if not shots else "cue"})
    data["clips"] = clips
    data["segments"] = segs
    if data.get("intro", {}).get("enabled", True):
        data["intro"]["shots"] = shots
        data["intro"]["vo"] = ("TODO: one hook sentence per intro shot. "
                               + " ".join(f"Sentence for shot {k + 2}." for k in range(len(shots) - 1))
                               + " Then promise what the video delivers.")
        data["intro"]["subscribe"]["at"] = 14.0
    data["shorts"] = [s for s in data.get("shorts", []) if s.get("segment", 0) <= len(segs)]
    header = text.split("version:")[0]
    return header + yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=100)
