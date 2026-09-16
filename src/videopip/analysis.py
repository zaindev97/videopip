"""Footage analysis: action windows, static/logo-card runs, scene cuts, freezes, loudness.

`best_window` picks the most action-packed window (motion + audio onsets) inside
the verified-safe ranges only: logo cards and CGI score HIGH on motion, so
selection must never look outside `safe`.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

import numpy as np

from . import ff

_MOTION: dict = {}
_AUDIO: dict = {}
_BEST: dict = {}


def motion_profile(path, step: float = 0.2):
    import cv2
    key = (os.path.abspath(path), round(step, 3))
    if key in _MOTION:
        return _MOTION[key]
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        return np.array([]), np.array([]), 0.0
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    n = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
    dur = (n / fps) if fps and n else ff.duration(path)
    times, scores, prev = [], [], None
    # sequential decode is far faster than seeking for every sample
    every = max(1, int(round(fps * step)))
    idx = 0
    while True:
        ok = cap.grab()
        if not ok:
            break
        if idx % every == 0:
            ok, frame = cap.retrieve()
            if not ok:
                break
            g = cv2.cvtColor(cv2.resize(frame, (160, 90)), cv2.COLOR_BGR2GRAY).astype("float32")
            t = idx / fps
            if prev is not None:
                times.append(t)
                scores.append(float(np.mean(np.abs(g - prev))))
            prev = g
        idx += 1
    cap.release()
    res = (np.array(times), np.array(scores), float(dur))
    _MOTION[key] = res
    return res


def audio_profile(path):
    key = os.path.abspath(path)
    if key in _AUDIO:
        return _AUDIO[key]
    res = (None, None)
    try:
        import librosa  # optional
        y, sr = librosa.load(str(path), sr=22050, mono=True)
        if y is not None and len(y) >= sr // 4:
            env = librosa.onset.onset_strength(y=y, sr=sr, hop_length=512)
            res = (librosa.times_like(env, sr=sr, hop_length=512), env)
    except Exception:
        pass
    _AUDIO[key] = res
    return res


def _norm(a):
    a = np.asarray(a, dtype="float32")
    rng = float(a.max() - a.min()) if a.size else 0.0
    return np.zeros_like(a) if rng < 1e-9 else (a - a.min()) / rng


def best_window(path, win: float = 1.8, ranges=None, step: float = 0.2, edge: float = 0.4,
                w_motion: float = 0.6, w_audio: float = 0.4) -> float:
    """Start time of the highest-action `win`-second window, inside `ranges` if given."""
    key = (os.path.abspath(path), round(win, 2), tuple(map(tuple, ranges)) if ranges else None)
    if key in _BEST:
        return _BEST[key]
    mt, ms, dur = motion_profile(path, step)
    if ranges:
        fits = [(a, b) for a, b in ranges if b - a >= win]
        ranges = fits or [max(ranges, key=lambda r: r[1] - r[0])]
    if len(ms) == 0:
        res = float(ranges[0][0]) if ranges else 0.0
        _BEST[key] = res
        return res
    combined = _norm(ms)
    at, ae = audio_profile(path)
    if at is not None and len(ae):
        combined = w_motion * _norm(ms) + w_audio * np.interp(mt, at, _norm(ae))
    hi = max(edge, dur - win - edge)

    def allowed(t0):
        if ranges:
            return any(t0 >= a and t0 + win <= b + 1e-6 for a, b in ranges)
        return edge <= t0 <= hi

    best_s, best = (ranges[0][0] if ranges else edge), -1.0
    for t0 in mt:
        t0 = float(t0)
        if not allowed(t0):
            continue
        m = (mt >= t0) & (mt < t0 + win)
        if m.any():
            sc = float(combined[m].sum())
            if sc > best:
                best, best_s = sc, t0
    res = round(best_s, 2)
    _BEST[key] = res
    return res


def static_runs(path, thresh: float = 0.9, min_run: float = 0.8):
    """Near-motionless stretches: typical of logo cards, end cards and text screens."""
    mt, ms, dur = motion_profile(path)
    runs, start = [], None
    for t, s in zip(mt, ms):
        if s < thresh:
            if start is None:
                start = float(t)
        else:
            if start is not None and float(t) - start >= min_run:
                runs.append((round(start, 1), round(float(t), 1)))
            start = None
    if start is not None and len(mt) and dur - start >= min_run:
        runs.append((round(start, 1), round(dur, 1)))
    return runs


def scene_cuts(path, threshold: float = 0.45):
    r = ff.run_capture(["-i", path, "-vf", f"select='gt(scene,{threshold})',metadata=print:file=-",
                        "-an", "-f", "null", "-"])
    return sorted({round(float(m), 1) for m in re.findall(r"pts_time:([0-9.]+)", r.stdout + r.stderr)})


def suggest_safe(path, head_tail_window: float = 8.0):
    """Whole clip minus static runs. Head/tail static runs (logo/end cards) are
    extended to the clip edge; mid-clip runs are cut out."""
    dur = ff.duration(path)
    cuts = []
    for a, b in static_runs(path):
        if a <= head_tail_window:
            a = 0.0
        if b >= dur - head_tail_window:
            b = dur
        cuts.append((a, b))
    safe, cur = [], 0.3
    for a, b in sorted(cuts):
        if a - cur >= 1.0:
            safe.append((round(cur, 1), round(a, 1)))
        cur = max(cur, b + 0.2)
    if dur - 0.3 - cur >= 1.0:
        safe.append((round(cur, 1), round(dur - 0.3, 1)))
    return safe


def analyze_clip(path, frames_dir: Path | None = None) -> dict:
    path = Path(path)
    dur = ff.duration(path)
    size = ff.video_size(path)
    statics = static_runs(path)
    cuts = scene_cuts(path)
    safe = suggest_safe(path)
    action = [best_window(path, 1.8, [r]) for r in safe if r[1] - r[0] >= 1.8][:6]
    out = {
        "file": str(path), "duration": round(dur, 2), "size": size, "has_audio": ff.has_audio(path),
        "static_runs": statics, "scene_cuts": cuts, "suggested_safe": safe, "action_peaks": action,
        "advice": "static_runs are LIKELY logo/end/text cards - confirm by looking at the frames "
                  "before trusting suggested_safe. Look for corner watermarks too (use delogo).",
    }
    if frames_dir:
        frames_dir.mkdir(parents=True, exist_ok=True)
        sheet = frames_dir / f"{path.stem}_sheet.jpg"
        contact_sheet(path, sheet)
        out["contact_sheet"] = str(sheet)
    return out


def contact_sheet(path, out: Path, cols: int = 6, rows: int = 6):
    """Grid of evenly spaced frames with timestamps burned in (for eyeballing logo cards)."""
    from .graphics import local_font
    out = Path(out).resolve()
    dur = ff.duration(path)
    n = cols * rows
    fps = n / max(dur, 0.1)
    font = local_font(out.parent)
    ff.run(["-y", "-i", Path(path).resolve(), "-vf",
            f"fps={fps:.5f},scale=320:-2,drawtext=fontfile={font}:text='%{{pts\\:hms}}':x=6:y=6:"
            f"fontsize=20:fontcolor=yellow:box=1:boxcolor=black@0.6,tile={cols}x{rows}",
            "-frames:v", "1", "-q:v", "3", out.name], cwd=out.parent, desc="contact sheet")
    return out


def freezes(path, min_dur: float = 1.0, noise: float = 0.003):
    r = ff.run_capture(["-i", path, "-vf", f"freezedetect=n={noise}:d={min_dur}", "-map", "0:v", "-f", "null", "-"])
    starts = [float(x) for x in re.findall(r"freeze_start: ([0-9.]+)", r.stderr)]
    ends = [float(x) for x in re.findall(r"freeze_end: ([0-9.]+)", r.stderr)]
    return [(round(a, 2), round(ends[i], 2) if i < len(ends) else None) for i, a in enumerate(starts)]


def blacks(path, min_dur: float = 0.5):
    r = ff.run_capture(["-i", path, "-vf", f"blackdetect=d={min_dur}:pix_th=0.10", "-an", "-f", "null", "-"])
    return [(float(a), float(b)) for a, b in re.findall(r"black_start:([0-9.]+) black_end:([0-9.]+)", r.stderr)]


def lufs(path, target: float = -14.0):
    r = ff.run_capture(["-i", path, "-af", f"loudnorm=I={target}:TP=-1.5:LRA=11:print_format=json",
                        "-vn", "-f", "null", "-"])
    txt = r.stderr
    try:
        return float(json.loads(txt[txt.rfind("{"): txt.rfind("}") + 1])["input_i"])
    except Exception:
        return None


def loudest_window(path, win: float) -> float:
    try:
        import librosa
        y, sr = librosa.load(str(path), sr=22050, mono=True)
        rms = librosa.feature.rms(y=y, hop_length=512)[0]
        n = max(1, int(win * sr / 512))
        if len(rms) <= n:
            return 0.0
        csum = np.convolve(rms, np.ones(n), "valid")
        return round(float(np.argmax(csum)) * 512 / sr, 2)
    except Exception:
        return 0.0
