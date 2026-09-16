"""Preflight: catch every problem we can BEFORE spending minutes rendering.

Returns a structured report so AI assistants can read it and fix the spec.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import analysis, ff, planner, sfx, tts
from .config import Project


@dataclass
class Issue:
    level: str          # error | warning | info
    where: str
    message: str
    fix: str = ""


@dataclass
class Report:
    issues: list[Issue] = field(default_factory=list)
    estimate: dict = field(default_factory=dict)

    def add(self, level, where, message, fix=""):
        self.issues.append(Issue(level, where, message, fix))

    @property
    def errors(self):
        return [i for i in self.issues if i.level == "error"]

    @property
    def ok(self):
        return not self.errors

    def to_dict(self):
        return {"ok": self.ok, "errors": len(self.errors),
                "warnings": sum(i.level == "warning" for i in self.issues),
                "issues": [asdict(i) for i in self.issues], "estimate": self.estimate}


def _inside(r, ranges) -> bool:
    return any(a - 1e-6 <= r[0] and r[1] <= b + 1e-6 for a, b in ranges)


def run(proj: Project, synth: bool = True, scan_cards: bool = False) -> Report:
    """synth=True renders the VO (cached) for exact timings; False estimates from word counts."""
    rep = Report()
    durations: dict[str, float] = {}
    sizes: dict[str, tuple] = {}

    # ---- tools
    try:
        ff.binaries()
    except ff.FFmpegError as e:
        rep.add("error", "ffmpeg", str(e), "run `videopip setup`")
        return rep

    # ---- clips
    for cid, spec in proj.clips.items():
        p = proj.clip_path(cid)
        where = f"clips.{cid}"
        if not p.exists():
            rep.add("error", where, f"file not found: {p}", "fix `file` or `clips_dir`")
            continue
        try:
            d = ff.duration(p)
            durations[cid] = d
            sizes[cid] = ff.video_size(p)
        except Exception as e:
            rep.add("error", where, f"cannot read video: {e}")
            continue
        if not sizes[cid]:
            rep.add("error", where, "file has no video stream")
            continue
        if sizes[cid][1] < 700:
            rep.add("warning", where, f"low resolution source {sizes[cid][0]}x{sizes[cid][1]} - will look soft",
                    "find an HD version of this clip")
        for a, b in spec.safe or []:
            if b > d + 0.05:
                rep.add("error", where, f"safe range [{a}, {b}] runs past the clip end ({d:.2f}s)",
                        f"end it at or before {d - 0.3:.1f}")
        if spec.safe is None:
            rep.add("info", where, "no `safe` ranges - the whole clip is treated as usable",
                    "run `videopip analyze` and exclude logo cards / text screens")
        sw, sh = sizes[cid]
        if spec.crop:
            try:
                cw, ch, cx, cy = (int(x) for x in spec.crop.split(":"))
                if cx + cw > sw or cy + ch > sh:
                    rep.add("error", where, f"crop {spec.crop} exceeds the {sw}x{sh} frame")
                sw, sh = cw, ch
            except ValueError:
                rep.add("warning", where, f"crop '{spec.crop}' is not plain numbers w:h:x:y - not validated")
        for bx in spec.delogo:
            if bx.x <= 0 or bx.y <= 0 or bx.x + bx.w >= sw or bx.y + bx.h >= sh:
                rep.add("warning", where, f"delogo box {bx.model_dump()} touches the frame edge - "
                                          "it will be clamped 1px inside (ffmpeg rejects edge boxes)")
        if scan_cards:
            safe = spec.safe or [(0.3, d - 0.3)]
            hits = []
            for a, b in analysis.static_runs(p):
                hits += [f"{max(a, x):.1f}-{min(b, y):.1f}s" for x, y in safe if min(b, y) - max(a, x) > 0.5]
            if hits:
                rep.add("warning", where, f"static stretches inside safe ranges (possible logo/end cards or text "
                                          f"screens, or just a still demo): {', '.join(hits)}",
                        "look at those moments on the contact sheet; exclude any that aren't real product footage")

    def safe_of(cid):
        s = proj.clips[cid].safe
        if s:
            return [tuple(r) for r in s]
        d = durations.get(cid, 0)
        return [(0.3, max(0.6, d - 0.3))]

    # ---- assets
    for label, path in (("music.intro", proj.music.intro), ("music.body", proj.music.body),
                        ("brand.watermark", proj.brand.watermark), ("brand.font", proj.brand.font),
                        ("sfx.whoosh", proj.sfx.whoosh), ("sfx.cold_open", proj.sfx.cold_open)):
        if not path:
            continue
        try:
            rp = sfx.resolve(path, proj) if label.startswith("sfx") else proj.path(path)
        except ValueError as e:
            rep.add("error", label, str(e))
            continue
        if rp and not Path(rp).exists():
            rep.add("error", label, f"file not found: {rp}")
    if not proj.music.intro and not proj.music.body:
        rep.add("info", "music", "no music set - the video will have voice and SFX only",
                "add royalty-free tracks you have the rights to")
    for label, s in (("intro.subscribe", proj.intro.subscribe), ("subscribe_mid", proj.subscribe_mid)):
        if s and s.enabled and s.source != "builtin":
            rp = proj.path(s.source)
            if not rp.exists():
                rep.add("error", label, f"subscribe asset not found: {rp}", "use source: builtin")
    for i, seg in enumerate(proj.segments, 1):
        for s in seg.sfx:
            try:
                rp = sfx.resolve(s.file, proj)
            except ValueError as e:
                rep.add("error", f"segments[{i}].sfx", str(e))
                continue
            if not Path(rp).exists():
                rep.add("warning", f"segments[{i}].sfx", f"not found, will be skipped: {rp}")
        for ov in seg.overlays:
            from .motion import BUILTIN
            if ov.template not in BUILTIN and not proj.path(ov.template).exists():
                rep.add("error", f"segments[{i}].overlays", f"template not found: {ov.template}",
                        f"use one of {', '.join(BUILTIN)} or a .html path")

    if rep.errors:
        return rep

    def speak(text):
        if not text.strip():
            return 0.0, []
        if synth:
            try:
                sp = tts.synthesize(text, proj.voice)
                return sp.duration, [s for s, _ in sp.sentences]
            except Exception as e:
                rep.add("warning", "voice", f"TTS failed ({e}); timings estimated from word count")
        est = tts.estimate(text)
        n = len(tts.split_sentences(text))
        return est, [est * k / max(1, n) for k in range(n)]

    st = proj.style
    total = 0.0
    n_pieces = 0
    # ---- intro
    ip = proj.intro
    if ip.enabled:
        n_pieces += 1
        shots = ip.shots
        if not shots:
            rep.add("info", "intro", "no intro shots - the first 4 segments' hero clips will be used")
            shots = []
            from .config import IntroShot
            for k, seg in enumerate(proj.segments[:4]):
                c = seg.clips[0]
                shots.append(IntroShot(clip=c, range=max(safe_of(c), key=lambda r: r[1] - r[0]),
                                       role="hero" if k == 0 else "cue"))
        roles = [s.role for s in shots]
        if roles != sorted(roles, key=lambda r: {"hero": 0, "cue": 1, "music": 2}[r]):
            rep.add("error", "intro.shots", f"shots must be ordered hero, cue..., music... (got {roles})")
        windows = []
        for j, s in enumerate(shots):
            if s.clip not in durations:
                continue
            if s.range[1] > durations[s.clip] + 0.05:
                rep.add("error", f"intro.shots[{j}]", f"range {list(s.range)} runs past the clip end")
            w = planner.intersect(safe_of(s.clip), s.range)
            if not w:
                rep.add("error", f"intro.shots[{j}]", f"range {list(s.range)} lies entirely outside the clip's "
                                                       "safe ranges", "pick a window inside `safe`")
                w = [tuple(s.range)]
            elif not _inside(s.range, safe_of(s.clip)):
                rep.add("warning", f"intro.shots[{j}]", f"range {list(s.range)} is only partly inside the safe "
                                                         "ranges - it will be trimmed to them")
            windows.append(w)
        vo_d, sents = speak(ip.vo)
        sub = ip.subscribe if ip.subscribe and ip.subscribe.enabled else None
        sub_len = (sub.duration or 5.0) if sub else 0.0
        if sub and sub.source != "builtin" and not sub.duration:
            try:
                sub_len = ff.duration(proj.path(sub.source))
            except Exception:
                pass
        cold = proj.sfx.cold_open_gap if proj.sfx.cold_open else (0.6 if vo_d else 0.0)
        if len(windows) == len(shots) and not rep.errors:
            try:
                plan = planner.plan_montage(
                    [(s.role, max(b - a for a, b in w), s.length) for s, w in zip(shots, windows)],
                    sents, vo_d, cold_gap=cold, hero_hold=ip.hero_hold, vo_deadline=ip.vo_deadline,
                    cue_lead=ip.cue_lead, sub_at=sub.at if sub else None, sub_len=sub_len, intro_len=ip.length)
                for note in plan.notes:
                    rep.add("warning", "intro", note)
                total += plan.total
                rep.estimate["intro"] = plan.total
                rep.estimate["intro_slots"] = plan.lengths
                if ip.min_length and plan.total < ip.min_length:
                    rep.add("warning", "intro", f"intro {plan.total}s is below min_length {ip.min_length}s")
                if ip.max_length and plan.total > ip.max_length:
                    rep.add("warning", "intro", f"intro {plan.total}s is above max_length {ip.max_length}s")
            except planner.PlanError as e:
                rep.add("error", "intro", str(e))
        cues = roles.count("cue")
        if ip.vo and cues and len(sents) < cues + 1:
            rep.add("warning", "intro.vo", f"{len(sents)} sentence(s) for 1 hero + {cues} cue shots",
                    "write one sentence per shot so cuts land on the words")

    # ---- segments
    seg_est = []
    for i, seg in enumerate(proj.segments, 1):
        n_pieces += 1
        where = f"segments[{i}]"
        if any(c not in durations for c in seg.clips):
            continue
        vo_d, _ = speak(seg.vo)
        reveal = st.first_reveal if i == 1 else st.reveal
        seglen = planner.segment_length(planner.speech_start(reveal, st.reveal_gap), vo_d, st.tail)
        ranges = [safe_of(c) for c in seg.clips]
        pool = planner.footage_pool(ranges)
        replay = seglen / pool if pool else 99
        if replay > st.replay_warn:
            rep.add("warning", where, f"'{seg.label or seg.title}' needs {seglen:.1f}s but has {pool:.1f}s of "
                                      f"usable footage ({replay:.2f}x replay)",
                    "shorten the VO or add another clip of this product")
        for f in seg.forced:
            ci = seg.clips.index(f.clip)
            if not _inside((f.start, f.start + f.duration), ranges[ci]):
                rep.add("error", where, f"forced take {f.clip} {f.start}+{f.duration}s is not inside a safe range")
        if seg.reveal_ranges:
            if not any(planner.intersect(ranges[0], w) for w in seg.reveal_ranges):
                rep.add("warning", where, "reveal_ranges don't overlap the hero clip's safe ranges - ignored")
        if len(seg.vo.split()) < 12:
            rep.add("warning", where, "very short VO - the segment will feel abrupt")
        seg_est.append(seglen)
        total += seglen

    # ---- outro
    if proj.outro.enabled:
        n_pieces += 1
        od, _ = speak(proj.outro.vo)
        total += (od + 1.5) if od else 4.0
    total -= st.transitions.duration * max(0, n_pieces - 1)
    rep.estimate.update({"segments": seg_est, "runtime": round(total, 1),
                         "runtime_hms": f"{int(total // 60)}:{int(total % 60):02d}",
                         "timing": "exact (voice rendered)" if synth else "estimated from word counts"})
    o = proj.output
    if o.target_min and total < o.target_min:
        rep.add("warning", "output", f"estimated runtime {total:.0f}s is below target_min {o.target_min}s",
                "add detail to the VOs or add segments")
    if o.target_max and total > o.target_max:
        rep.add("warning", "output", f"estimated runtime {total:.0f}s is above target_max {o.target_max}s",
                "tighten the VOs")
    if o.format != "landscape" and total > 180:
        rep.add("warning", "output", f"{o.format} video is {total:.0f}s - Shorts/Reels are capped at 60-180s")
    for sh in proj.shorts:
        if sh.segment is not None and not (1 <= sh.segment <= len(proj.segments)):
            rep.add("error", f"shorts.{sh.name}", f"segment {sh.segment} does not exist")
    try:
        from .graphics import find_font
        find_font("bold", str(proj.path(proj.brand.font)) if proj.brand.font else None)
    except FileNotFoundError as e:
        rep.add("error", "fonts", str(e), "run `videopip setup`")
    return rep
