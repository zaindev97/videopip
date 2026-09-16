"""Post-render QA: freezes, black frames, loudness, streams, duration."""
from __future__ import annotations

from pathlib import Path

from . import analysis, ff


def verify(path: Path, target_lufs: float = -14.0, ignore_tail: float = 5.0) -> dict:
    path = Path(path)
    issues = []
    info = ff.probe(path)
    streams = info.get("streams", [])
    v = next((s for s in streams if s["codec_type"] == "video"), None)
    a = next((s for s in streams if s["codec_type"] == "audio"), None)
    dur = ff.duration(path)
    if not v:
        issues.append("no video stream")
    if not a:
        issues.append("no audio stream")
    if v and (int(v["width"]) % 2 or int(v["height"]) % 2):
        issues.append(f"odd dimensions {v['width']}x{v['height']} (breaks yuv420p players)")
    fr = analysis.freezes(path, 1.0)
    real_freezes = [f for f in fr if f[0] < dur - ignore_tail]
    for s, e in real_freezes:
        issues.append(f"frozen picture {s}s -> {e if e is not None else 'end'}s (bad cut or seek?)")
    bl = [b for b in analysis.blacks(path) if b[0] > 0.2 and b[1] < dur - 1.0]
    for s, e in bl:
        issues.append(f"black frames {s:.2f}-{e:.2f}s")
    loud = analysis.lufs(path, target_lufs) if a else None
    if loud is not None and abs(loud - target_lufs) > 1.0:
        issues.append(f"loudness {loud} LUFS, target {target_lufs}")
    return {
        "file": str(path), "ok": not issues, "duration": round(dur, 2),
        "size": [v["width"], v["height"]] if v else None,
        "fps": v.get("r_frame_rate") if v else None, "lufs": loud,
        "freezes": fr, "black": bl, "issues": issues,
    }
