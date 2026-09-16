"""The renderer: project spec -> finished MP4 (+ manifest for shorts/metadata).

Pipeline
  intro montage  ->  N product segments  ->  outro card
  -> xfade/acrossfade assembly (+ mid-video subscribe overlay)
  -> music / ducking / whoosh / stingers / SFX mix
  -> loudness mastering (default -14 LUFS)

Hard-won rules baked in:
* every b-roll cut is pre-extracted with its OWN -ss read. A shared split+trim
  graph deadlocks or freezes on backward seeks.
* montage windows are never widened; slots are clamped to them.
* reveal/filler selection only looks inside verified-safe ranges.
* delogo boxes are clamped off the frame edge (delogo rejects x=0/y=0).
"""
from __future__ import annotations

import hashlib
import json
import math
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import analysis, ff, graphics, planner, sfx, tts
from .config import OverlaySpec, Project, Segment, SubscribeSpec
from .log import info, ok, step, warn


@dataclass
class Built:
    path: Path
    duration: float
    kind: str                       # intro | segment | outro
    index: int = 0
    reveal: float = 0.0
    speech_start: float = 0.0
    words: list = field(default_factory=list)   # (start, dur, text) relative to the piece
    sfx: list = field(default_factory=list)     # (path, volume, at, length, file_in) relative
    sub_audio: list = field(default_factory=list)
    label: str = ""
    link: str | None = None


def _hash(obj) -> str:
    return hashlib.sha1(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()[:16]


def pos_expr(position: str, mx: int, my: int) -> tuple[str, str]:
    return {
        "bottom-center": ("(W-w)/2", f"H-h-{my}"),
        "bottom-right": (f"W-w-{mx}", f"H-h-{my}"),
        "bottom-left": (f"{mx}", f"H-h-{my}"),
        "top-right": (f"W-w-{mx}", f"{my}"),
        "top-left": (f"{mx}", f"{my}"),
        "top-center": ("(W-w)/2", f"{my}"),
        "center": ("(W-w)/2", "(H-h)/2"),
    }[position]


class Renderer:
    def __init__(self, proj: Project, force: bool = False, log_cb=None):
        self.p = proj
        self.force = force
        self.W, self.H = proj.output.size
        self.fps = proj.output.fps
        self.work = proj.work
        self.work.mkdir(parents=True, exist_ok=True)
        self.font = graphics.local_font(self.work, "bold", proj.path(proj.brand.font) and str(proj.path(proj.brand.font)))
        self.k = self.W / 1920 if self.W >= self.H else self.W / 1080  # UI scale
        self.txt = ff.TextFiles(self.work, "t")
        self._safe_cache: dict[str, list] = {}
        self.wm = None

    # ------------------------------------------------------------------ helpers
    def venc(self, crf=None) -> list:
        o = self.p.output
        return ["-r", self.fps, "-c:v", "libx264", "-preset", o.preset, "-crf", crf or o.crf,
                "-pix_fmt", "yuv420p"]

    AENC_PCM = ["-c:a", "pcm_s16le", "-ar", "48000", "-ac", "2"]

    def safe(self, clip_id: str) -> list[tuple[float, float]]:
        if clip_id not in self._safe_cache:
            spec = self.p.clips[clip_id]
            if spec.safe:
                rs = [tuple(r) for r in spec.safe]
            else:
                d = ff.duration(self.p.clip_path(clip_id))
                rs = [(0.3, max(0.6, round(d - 0.3, 2)))]
            self._safe_cache[clip_id] = rs
        return self._safe_cache[clip_id]

    def grade(self) -> str:
        g = self.p.brand.grade
        return "" if not g or g == "none" else f",{g}"

    def prep(self, src: str, out: str, clip_id: str) -> str:
        """crop -> delogo -> fit into W x H over a blurred copy of itself -> fps -> grade."""
        spec = self.p.clips[clip_id]
        chain, cur = [], src
        if spec.crop:
            chain.append(f"[{cur}]crop={spec.crop}[{out}_c]")
            cur = f"{out}_c"
        if spec.delogo:
            size = ff.video_size(self.p.clip_path(clip_id)) or (1920, 1080)
            if spec.crop:
                parts = spec.crop.split(":")
                try:
                    size = (int(parts[0]), int(parts[1]))
                except ValueError:
                    pass
            for j, b in enumerate(spec.delogo):
                x, y = max(1, b.x), max(1, b.y)
                w = min(b.w, size[0] - x - 1)
                h = min(b.h, size[1] - y - 1)
                chain.append(f"[{cur}]delogo=x={x}:y={y}:w={w}:h={h}[{out}_d{j}]")
                cur = f"{out}_d{j}"
        W, H = self.W, self.H
        bw, bh = W // 4 // 2 * 2, H // 4 // 2 * 2
        chain.append(
            f"[{cur}]split=2[{out}_bs][{out}_fs];"
            f"[{out}_bs]scale={bw}:{bh}:force_original_aspect_ratio=increase,crop={bw}:{bh},"
            f"gblur=sigma=12,scale={W}:{H},eq=brightness=-0.06:saturation=0.9[{out}_bb];"
            f"[{out}_fs]scale={W}:{H}:force_original_aspect_ratio=decrease[{out}_fv];"
            f"[{out}_bb][{out}_fv]overlay=(W-w)/2:(H-h)/2,setsar=1,fps={self.fps}{self.grade()},"
            f"format=yuv420p[{out}]")
        return ";".join(chain)

    def extract(self, clip_id: str, start: float, dur: float, out: Path) -> Path:
        """One cut, its own -ss read, normalised video + a 48k stereo audio track."""
        spec = self.p.clips[clip_id]
        src = self.p.clip_path(clip_id)
        use_a = spec.use_audio and ff.has_audio(src)
        args = ["-y", "-ss", round(start, 3), "-i", src]
        if not use_a:
            args += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
        fc = self.prep("0:v", "vout", clip_id)
        if use_a:
            fc += (f";[0:a]volume={spec.audio_volume},aresample=48000,"
                   f"aformat=channel_layouts=stereo[aout]")
            amap = "[aout]"
        else:
            amap = "1:a"
        args += ["-t", round(dur, 3), "-filter_complex", fc, "-map", "[vout]", "-map", amap]
        args += self.venc(18) + self.AENC_PCM + [out]
        ff.run(args, desc=f"extract {clip_id}@{start}")
        return out

    def concat_chunks(self, paths: list[Path]) -> tuple[list, str, str]:
        inputs = []
        for p in paths:
            inputs += ["-i", p]
        n = len(paths)
        labels = "".join(f"[{j}:v][{j}:a]" for j in range(n))
        return inputs, f"{labels}concat=n={n}:v=1:a=1[bg][bga]", "bg"

    def watermark(self) -> Path | None:
        if self.wm is None and self.p.brand.watermark:
            src = self.p.path(self.p.brand.watermark)
            if src and src.exists():
                self.wm = self.work / "wm.png"
                graphics.watermark(src, self.wm, int(self.p.brand.watermark_width * self.k))
            else:
                warn(f"brand.watermark not found: {src}")
                self.wm = False
        return self.wm or None

    def banner_png(self, text: str, out: Path, size: int = 68, **kw) -> tuple[int, int]:
        size = int(size * max(self.k, 0.6))
        tf = self.p.brand.title_font and str(self.p.path(self.p.brand.title_font))
        while True:
            w, h = graphics.banner(text, out, self.p.brand.banner_style, size, tf, **kw)
            if w <= self.W - 40 or size <= 24:
                return w, h
            size -= 4

    def subscribe_asset(self, spec: SubscribeSpec) -> tuple[Path, float, bool]:
        """(file, duration, is_builtin)"""
        if spec.source == "builtin":
            dur = spec.duration or 5.0
            return graphics.builtin_subscribe(max(dur, 3.0), self.fps), dur, True
        path = self.p.path(spec.source)
        if not path or not path.exists():
            raise FileNotFoundError(f"subscribe source not found: {path}")
        return path, spec.duration or ff.duration(path), False

    def subscribe_filter(self, idx: int, spec: SubscribeSpec, at: float, dur: float, builtin: bool,
                         base: str, out: str) -> list[str]:
        w = int(spec.width * self.k) // 2 * 2
        x, y = pos_expr(spec.position, int(spec.margin_x * self.k), int(spec.margin_y * self.k))
        if builtin:
            prep = f"[{idx}:v]fps={self.fps},format=rgba,scale={w}:-2"
        else:
            crop = f"crop={spec.crop}," if spec.crop else ""
            prep = (f"[{idx}:v]{crop}fps={self.fps},chromakey={spec.chroma_color}:{spec.chroma_similarity}:"
                    f"{spec.chroma_blend},format=yuva420p,split=2[sr{idx}][sa{idx}];"
                    f"[sa{idx}]alphaextract,erosion,erosion[sb{idx}];"
                    f"[sr{idx}][sb{idx}]alphamerge,scale={w}:-2")
        return [f"{prep},trim=0:{round(dur, 3)},setpts=PTS-STARTPTS+{round(at, 3)}/TB[sub{idx}]",
                f"[{base}][sub{idx}]overlay={x}:{y}:eof_action=pass:"
                f"enable='between(t,{round(at, 3)},{round(at + dur, 3)})'[{out}]"]

    def subscribe_sounds(self, spec: SubscribeSpec, at: float, dur: float, builtin: bool, asset: Path):
        if spec.audio_volume <= 0:
            return []
        if builtin:
            click = sfx.builtin("click")
            return [(click, spec.audio_volume * 1.6, round(at + t, 3), 0.1, 0.0)
                    for t in graphics.builtin_subscribe_click_times() if t < dur]
        if ff.has_audio(asset):
            return [(asset, spec.audio_volume, round(at, 3), round(dur, 3), 0.0)]
        return []

    def speech(self, text: str) -> tts.Speech:
        return tts.synthesize(text, self.p.voice)

    def vo_track(self, speech: tts.Speech | None, delay: float, total: float, out: Path) -> Path:
        if speech is None:
            ff.run(["-y", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", round(total, 3),
                    "-c:a", "pcm_s16le", out])
            return out
        ms = int(delay * 1000)
        ff.run(["-y", "-i", speech.wav, "-af",
                f"adelay={ms}|{ms},apad,atrim=0:{round(total, 3)},aresample=48000,aformat=channel_layouts=stereo",
                "-c:a", "pcm_s16le", out], desc="vo track")
        return out

    def _cached(self, name: str, key: str) -> Path | None:
        seg, meta = self.work / f"{name}.mkv", self.work / f"{name}.json"
        if self.force or not seg.exists() or not meta.exists():
            return None
        try:
            m = json.loads(meta.read_text(encoding="utf-8"))
        except Exception:
            return None
        return seg if m.get("key") == key else None

    def _meta_save(self, name: str, key: str, b: Built):
        d = {"key": key, "duration": b.duration, "reveal": b.reveal, "speech_start": b.speech_start,
             "words": b.words, "sfx": [[str(x[0]), *x[1:]] for x in b.sfx],
             "sub_audio": [[str(x[0]), *x[1:]] for x in b.sub_audio]}
        (self.work / f"{name}.json").write_text(json.dumps(d), encoding="utf-8")

    def _meta_load(self, name: str, b: Built) -> Built:
        m = json.loads((self.work / f"{name}.json").read_text(encoding="utf-8"))
        b.duration, b.reveal, b.speech_start = m["duration"], m["reveal"], m["speech_start"]
        b.words = [tuple(w) for w in m["words"]]
        b.sfx = [(Path(x[0]), *x[1:]) for x in m["sfx"]]
        b.sub_audio = [(Path(x[0]), *x[1:]) for x in m.get("sub_audio", [])]
        return b

    def _clip_sig(self, ids) -> dict:
        out = {}
        for c in ids:
            p = self.p.clip_path(c)
            out[c] = [self.p.clips[c].model_dump(), p.stat().st_mtime if p.exists() else 0]
        return out

    def _common_sig(self) -> dict:
        return {"W": self.W, "fps": self.fps, "brand": self.p.brand.model_dump(), "voice": self.p.voice.model_dump(),
                "style": self.p.style.model_dump(), "crf": self.p.output.crf, "v": 3}

    # ------------------------------------------------------------------ intro
    def auto_intro_shots(self):
        from .config import IntroShot
        shots = []
        for i, seg in enumerate(self.p.segments[:4]):
            c = seg.clips[0]
            a, b = max(self.safe(c), key=lambda r: r[1] - r[0])
            shots.append(IntroShot(clip=c, range=(a, b), role="hero" if i == 0 else "cue"))
        return shots

    def build_intro(self) -> Built:
        ip = self.p.intro
        shots = ip.shots or self.auto_intro_shots()
        sub = ip.subscribe if (ip.subscribe and ip.subscribe.enabled) else None
        key = _hash([ip.model_dump(), [s.model_dump() for s in shots], self._common_sig(),
                     self._clip_sig({s.clip for s in shots}), self.p.sfx.model_dump(), self.W])
        name = "seg_00_intro"
        b = Built(self.work / f"{name}.mkv", 0, "intro", 0, label="Intro")
        if self._cached(name, key):
            info("intro unchanged - reusing")
            return self._meta_load(name, b)

        speech = self.speech(ip.vo) if ip.vo.strip() else None
        cold = self.p.sfx.cold_open_gap if self.p.sfx.cold_open else (0.6 if speech else 0.0)
        sub_file, sub_len, sub_builtin = (self.subscribe_asset(sub) if sub else (None, 0.0, False))
        windows = []
        for s in shots:
            rng = planner.intersect(self.safe(s.clip), s.range) or [tuple(s.range)]
            windows.append(rng)
        plan = planner.plan_montage(
            [(s.role, max(b_ - a_ for a_, b_ in w), s.length) for s, w in zip(shots, windows)],
            [st for st, _ in speech.sentences] if speech else [], speech.duration if speech else 0.0,
            cold_gap=cold, hero_hold=ip.hero_hold, vo_deadline=ip.vo_deadline, cue_lead=ip.cue_lead,
            sub_at=sub.at if sub else None, sub_len=sub_len, intro_len=ip.length)
        for n in plan.notes:
            warn(n)
        pieces = []
        for i, (s, rng, plen) in enumerate(zip(shots, windows, plan.lengths)):
            if plen < 0.2:
                continue
            clip = self.p.clip_path(s.clip)
            win = min(1.8, plen)
            bw = analysis.best_window(clip, win, rng)
            a, b_ = next(((a, b_) for a, b_ in rng if a <= bw < b_), rng[0])
            st = bw - (plen - win) / 2.0
            st = min(max(a, st), max(a, b_ - plen))
            take = round(min(plen, b_ - st), 3)
            info(f"intro shot {i} [{s.role}] {s.clip} {st:.2f}s +{take:.2f}s (on screen {plan.starts[i]:.2f}s)")
            pieces.append(self.extract(s.clip, st, take, self.work / f"m_{i:02d}.mkv"))
        reals = [ff.duration(p) for p in pieces]
        total = round(sum(reals), 3)
        if ip.min_length and total < ip.min_length:
            warn(f"intro is {total}s, below intro.min_length {ip.min_length}s")
        if ip.max_length and total > ip.max_length:
            warn(f"intro is {total}s, above intro.max_length {ip.max_length}s")

        inputs, fc0, cur = self.concat_chunks(pieces)
        fc = [fc0]
        n = len(pieces)
        nxt = n
        wm = self.watermark()
        if wm:
            inputs += ["-loop", "1", "-i", wm]
            m = int(24 * self.k)
            fc.append(f"[{cur}][{nxt}:v]overlay={m}:{m}:shortest=1[vwm]")
            cur, nxt = "vwm", nxt + 1
        sub_sounds = []
        if sub:
            at = plan.sub_at
            dur = round(min(sub_len, max(0.5, total - at)), 3)
            inputs += ["-i", sub_file]
            fc += self.subscribe_filter(nxt, sub, at, dur, sub_builtin, cur, "vsub")
            cur, nxt = "vsub", nxt + 1
            sub_sounds = self.subscribe_sounds(sub, at, dur, sub_builtin, sub_file)
            info(f"subscribe beat @ {at:.2f}s for {dur:.2f}s ({sub.position})")
        vo = self.vo_track(speech, cold, total, self.work / "vo_intro.wav")
        inputs += ["-i", vo]
        fc.append(f"[bga][{nxt}:a]amix=inputs=2:normalize=0:duration=first[aout]")
        ff.run(["-y"] + inputs + ["-filter_complex", ";".join(fc), "-map", f"[{cur}]", "-map", "[aout]",
                                  "-t", total] + self.venc() + self.AENC_PCM + [b.path], desc="intro")
        b.duration = round(ff.duration(b.path), 3)
        b.speech_start = cold
        b.words = [(round(cold + w[0], 3), w[1], w[2]) for w in (speech.words if speech else [])]
        cs = self.p.sfx.cold_open
        if cs:
            path = sfx.resolve(cs, self.p)
            length = round(cold + 0.6, 3)
            fin = self.p.sfx.cold_open_in
            if fin is None:
                fin = analysis.loudest_window(path, length)
            b.sfx.append((path, self.p.sfx.cold_open_volume, 0.0, length, fin))
        b.sub_audio = sub_sounds
        self._meta_save(name, key, b)
        ok(f"intro {b.duration:.2f}s")
        return b

    # ------------------------------------------------------------------ segments
    def number_for(self, i: int) -> str:
        n = len(self.p.segments)
        mode = self.p.style.numbering
        if mode == "none":
            return ""
        return f"#{(n - i + 1) if mode == 'countdown' else i}  "

    def build_segment(self, i: int, seg: Segment) -> Built:
        st = self.p.style
        key = _hash([seg.model_dump(), self._common_sig(), self._clip_sig(seg.clips), i,
                     len(self.p.segments), self.p.sfx.model_dump()])
        name = f"seg_{i:02d}"
        label = seg.label or seg.title
        b = Built(self.work / f"{name}.mkv", 0, "segment", i, label=label, link=seg.link)
        if self._cached(name, key):
            info(f"segment {i} unchanged - reusing")
            return self._meta_load(name, b)
        speech = self.speech(seg.vo)
        reveal = st.first_reveal if i == 1 else st.reveal
        ss = planner.speech_start(reveal, st.reveal_gap)
        seglen = planner.segment_length(ss, speech.duration, st.tail)
        ranges = [self.safe(c) for c in seg.clips]
        clip0 = self.p.clip_path(seg.clips[0])
        rr = ranges[0]
        if seg.reveal_ranges:
            rr = [r for w in seg.reveal_ranges for r in planner.intersect(ranges[0], w)] or ranges[0]
        rstart = analysis.best_window(clip0, reveal, rr)
        forced = [(seg.clips.index(f.clip), f.start, f.duration) for f in seg.forced]
        chunks = planner.plan_chunks(ranges, seglen, rstart, reveal, st.chunk, forced)
        pool = planner.footage_pool(ranges)
        replay = seglen / pool if pool else 99
        info(f"segment {i} '{label}': VO {speech.duration:.1f}s -> {seglen:.1f}s, {len(chunks)} cuts, "
             f"reveal @{rstart}s, footage replay {replay:.2f}x")
        if replay > st.replay_warn:
            warn(f"segment {i} replays its footage {replay:.2f}x - shorten the VO or add clips")
        pieces = [self.extract(seg.clips[ci], s, d, self.work / f"ck_{i:02d}_{j:02d}.mkv")
                  for j, (ci, s, d) in enumerate(chunks)]

        inputs, fc0, cur = self.concat_chunks(pieces)
        fc = [fc0]
        nxt = len(pieces)
        m = int(24 * self.k)
        wm = self.watermark()
        if wm:
            inputs += ["-loop", "1", "-i", wm]
            fc.append(f"[{cur}][{nxt}:v]overlay={m}:{m}:shortest=1[vwm]")
            cur, nxt = "vwm", nxt + 1
        r = round(reveal, 2)
        # title banner slides in from the left during the reveal
        bpng = self.work / f"banner_{i:02d}.png"
        bw, bh = self.banner_png(seg.title, bpng)
        by = int(st.banner_y * self.k) if self.W >= self.H else int(self.H * 0.2)
        sd = 0.4
        bx = 0 if self.W >= self.H else (self.W - bw) // 2
        xexpr = f"if(lt(t,{sd}),-{bw}+({bw}+{bx})*(t/{sd}),{bx})"
        inputs += ["-loop", "1", "-i", bpng]
        fc.append(f"[{cur}][{nxt}:v]overlay=x='{xexpr}':y={by}:shortest=1:enable='between(t,0,{r})'[vban]")
        cur, nxt = "vban", nxt + 1
        # verdict banner at the end
        v0 = round(max(r + 1.0, seglen - st.verdict_hold - 0.4), 2)
        if st.show_verdict and seg.verdict:
            vpng = self.work / f"verdict_{i:02d}.png"
            bad = seg.verdict.upper().startswith(("SKIP", "ONLY", "NOT"))
            vw, vh = self.banner_png(f"VERDICT: {seg.verdict}", vpng, 56,
                                     bg=(196, 32, 32, 240) if bad else (255, 255, 255, 240),
                                     fg=(255, 255, 255, 255) if bad else (15, 15, 15, 255))
            vxc = (self.W - vw) // 2
            vx = f"if(lt(t,{round(v0 + sd, 2)}),{self.W}-({self.W}-{vxc})*((t-{v0})/{sd}),{vxc})"
            inputs += ["-loop", "1", "-i", vpng]
            fc.append(f"[{cur}][{nxt}:v]overlay=x='{vx}':y={by}:shortest=1:"
                      f"enable='between(t,{v0},{round(seglen - 0.4, 2)})'[vver]")
            cur, nxt = "vver", nxt + 1
        # motion-graphics overlays
        for k_, ov in enumerate(seg.overlays):
            mov = self.motion(ov)
            if mov is None:
                continue
            my = int(ov.margin * self.k)
            if ov.position.startswith("top") and st.lower_third:
                # keep clear of the lower-third text band (source-caption collision lesson)
                my += int((st.lower_third_y + 90) * self.k) if self.W >= self.H else int(self.H * 0.08) + 90
            x, y = pos_expr(ov.position, int(ov.margin * self.k), my)
            at = round(min(ov.at, max(0.0, seglen - 0.5)), 3)
            inputs += ["-i", mov]
            fc.append(f"[{nxt}:v]fps={self.fps},format=rgba,scale={int(ov.width * self.k) // 2 * 2}:-2,"
                      f"setpts=PTS-STARTPTS+{at}/TB[ov{k_}]")
            fc.append(f"[{cur}][ov{k_}]overlay={x}:{y}:eof_action=pass:"
                      f"enable='between(t,{at},{round(at + ov.duration, 3)})'[vov{k_}]")
            cur, nxt = f"vov{k_}", nxt + 1
        # text: lower third + callouts
        draws = []
        fs_lt = int(40 * self.k) if self.W >= self.H else 44
        if st.lower_third:
            t = self.txt(f"{self.number_for(i)}{label}".strip())
            lty = int(st.lower_third_y * self.k) if self.W >= self.H else int(self.H * 0.08)
            ltx = f"w-text_w-{int(70 * self.k)}" if self.W >= self.H else "(w-text_w)/2"
            draws.append(f"drawtext=fontfile={self.font}:textfile={t}:fontcolor=white:fontsize={fs_lt}:"
                         f"x={ltx}:y={lty}:box=1:boxcolor=0x000000D9:boxborderw={int(14 * self.k)}:"
                         f"enable='gte(t,{r})'")
        if st.show_callouts:
            for c in seg.callouts:
                t0 = min(c.at, max(r + 0.5, v0 - c.duration - 0.6))
                t1 = round(min(t0 + c.duration, v0 - 0.3), 2)
                if t1 - t0 < 0.8:
                    continue
                t = self.txt(c.text)
                draws.append(f"drawtext=fontfile={self.font}:textfile={t}:fontcolor={graphics.ffcolor('#FFE24A')}:"
                             f"fontsize={int(72 * self.k)}:x=(w-text_w)/2:y={int(self.H * 0.37)}:box=1:"
                             f"boxcolor=0x000000B4:boxborderw={int(20 * self.k)}:"
                             f"enable='between(t,{round(t0, 2)},{t1})'")
        if draws:
            fc.append(f"[{cur}]" + ",".join(draws) + "[vtxt]")
            cur = "vtxt"
        vo = self.vo_track(speech, ss, seglen, self.work / f"vo_{i:02d}.wav")
        inputs += ["-i", vo]
        fc.append(f"[bga][{nxt}:a]amix=inputs=2:normalize=0:duration=first,"
                  f"afade=t=in:st=0:d=0.05,afade=t=out:st={round(seglen - 0.05, 2)}:d=0.05[aout]")
        ff.run(["-y"] + inputs + ["-filter_complex", ";".join(fc), "-map", f"[{cur}]", "-map", "[aout]",
                                  "-t", seglen] + self.venc() + self.AENC_PCM + [b.path],
               cwd=self.work, desc=f"segment {i}")
        b.duration = round(ff.duration(b.path), 3)
        b.reveal, b.speech_start = reveal, ss
        b.words = [(round(ss + w[0], 3), w[1], w[2]) for w in speech.words]
        for s_ in seg.sfx:
            path = sfx.resolve(s_.file, self.p)
            if not path or not Path(path).exists():
                warn(f"segment {i} sfx missing: {s_.file} (skipped - never substitute a mismatched sound)")
                continue
            fin = s_.file_in if s_.file_in is not None else analysis.loudest_window(path, s_.length)
            at = s_.at if s_.at is not None else 0.25
            b.sfx.append((path, s_.volume, round(at, 3), s_.length, fin))
        self._meta_save(name, key, b)
        ok(f"segment {i} {b.duration:.2f}s")
        return b

    def motion(self, ov: OverlaySpec) -> Path | None:
        from . import motion
        try:
            return motion.render(ov, self.p, self.fps)
        except motion.MotionUnavailable as e:
            warn(str(e))
            return None

    # ------------------------------------------------------------------ outro
    def build_outro(self) -> Built:
        o = self.p.outro
        bg = o.background_clip or self.p.segments[-1].clips[0]
        key = _hash([o.model_dump(), self._common_sig(), self._clip_sig([bg])])
        name = "seg_99_outro"
        b = Built(self.work / f"{name}.mkv", 0, "outro", 99, label="Outro")
        if self._cached(name, key):
            info("outro unchanged - reusing")
            return self._meta_load(name, b)
        speech = self.speech(o.vo) if o.vo.strip() else None
        seglen = round((speech.duration + 1.5) if speech else 4.0, 2)
        clip = self.p.clip_path(bg)
        start = analysis.best_window(clip, min(2.6, seglen), self.safe(bg))
        chunks = planner.plan_chunks([self.safe(bg)], seglen, start, 2.6, self.p.style.chunk)
        pieces = [self.extract(bg, s, d, self.work / f"ck_99_{j:02d}.mkv") for j, (_, s, d) in enumerate(chunks)]
        inputs, fc0, cur = self.concat_chunks(pieces)
        fc = [fc0]
        nxt = len(pieces)
        fo = round(seglen - 0.6, 2)
        fc.append(f"[{cur}]eq=brightness=-{o.dim}[dim]")
        cur = "dim"
        wm = self.watermark()
        if wm:
            m = int(24 * self.k)
            inputs += ["-loop", "1", "-i", wm]
            fc.append(f"[{cur}][{nxt}:v]overlay={m}:{m}:shortest=1[dw]")
            cur, nxt = "dw", nxt + 1
        h1, h2 = self.txt(o.headline), self.txt(o.subline)
        fs1 = int(92 * self.k) if self.W >= self.H else 84
        fs2 = int(48 * self.k) if self.W >= self.H else 48
        fc.append(f"[{cur}]drawtext=fontfile={self.font}:textfile={h1}:fontcolor=white:fontsize={fs1}:"
                  f"borderw={max(2, int(4 * self.k))}:bordercolor=black@0.8:x=(w-text_w)/2:y=(h/2)-{int(90 * self.k)},"
                  f"drawtext=fontfile={self.font}:textfile={h2}:fontcolor={graphics.ffcolor(self.p.brand.accent)}:"
                  f"fontsize={fs2}:box=1:boxcolor=0x000000B0:boxborderw={int(14 * self.k)}:"
                  f"x=(w-text_w)/2:y=(h/2)+{int(40 * self.k)},fade=t=out:st={fo}:d=0.6[vout]")
        vo = self.vo_track(speech, 0.0, seglen, self.work / "vo_outro.wav")
        inputs += ["-i", vo]
        fc.append(f"[bga][{nxt}:a]amix=inputs=2:normalize=0:duration=first,"
                  f"afade=t=out:st={fo}:d=0.5[aout]")
        ff.run(["-y"] + inputs + ["-filter_complex", ";".join(fc), "-map", "[vout]", "-map", "[aout]",
                                  "-t", seglen] + self.venc() + self.AENC_PCM + [b.path],
               cwd=self.work, desc="outro")
        b.duration = round(ff.duration(b.path), 3)
        b.words = [tuple(w) for w in (speech.words if speech else [])]
        self._meta_save(name, key, b)
        ok(f"outro {b.duration:.2f}s")
        return b

    # ------------------------------------------------------------------ assembly
    def pick_mid_sub(self, pieces: list[Built], offsets: list[float], spec) -> float | None:
        show = spec.duration or 6.0
        st = self.p.style
        best, gap = None, 1e9
        for b, cut in zip(pieces, offsets):
            if b.kind != "segment":
                continue
            a_ = cut + b.speech_start + 1.0
            z_ = cut + b.duration - st.verdict_hold - st.transitions.duration - show - 0.5
            if z_ <= a_:
                continue
            cand = min(max(spec.at, a_), z_)
            if abs(cand - spec.at) < gap:
                best, gap = round(cand, 2), abs(cand - spec.at)
        return best

    def assemble(self, pieces: list[Built], out: Path) -> tuple[float, list[float], float | None, list]:
        durs = [b.duration for b in pieces]
        tspec = self.p.style.transitions
        ds, offs, total = planner.xfade_offsets(durs, tspec.duration)
        starts = [0.0] + offs
        inputs, fc = [], []
        for j, b in enumerate(pieces):
            inputs += ["-i", b.path]
            fc.append(f"[{j}:v]settb=AVTB,fps={self.fps},format=yuv420p[v{j}]")
        vprev, aprev = "v0", "0:a"
        for j in range(1, len(pieces)):
            t = tspec.types[(j - 1) % len(tspec.types)] if tspec.types else "fade"
            fc.append(f"[{vprev}][v{j}]xfade=transition={t}:duration={ds[j - 1]}:offset={offs[j - 1]}[vx{j}]")
            fc.append(f"[{aprev}][{j}:a]acrossfade=d={ds[j - 1]}[ax{j}]")
            vprev, aprev = f"vx{j}", f"ax{j}"
        mid_at, mid_sounds = None, []
        ms = self.p.subscribe_mid
        if ms and ms.enabled:
            mid_at = self.pick_mid_sub(pieces, starts, ms)
            if mid_at is None:
                warn("no segment has a long enough talking beat for subscribe_mid - skipped")
            else:
                f, dur, bi = self.subscribe_asset(ms)
                dur = ms.duration or dur
                idx = len(pieces)
                inputs += ["-i", f]
                fc += self.subscribe_filter(idx, ms, mid_at, dur, bi, vprev, "vmid")
                vprev = "vmid"
                mid_sounds = self.subscribe_sounds(ms, mid_at, dur, bi, f)
                info(f"mid-video subscribe @ {mid_at:.2f}s ({ms.position})")
        if len(pieces) == 1:
            aprev = "0:a"
        amap = f"[{aprev}]" if ":" not in aprev else aprev
        ff.run(["-y"] + inputs + ["-filter_complex", ";".join(fc), "-map", f"[{vprev}]", "-map", amap,
                                  "-t", total] + self.venc() + self.AENC_PCM + [out], desc="assemble")
        return total, starts, mid_at, mid_sounds

    # ------------------------------------------------------------------ audio mix
    def mix(self, base: Path, total: float, pieces: list[Built], starts: list[float], extra_sounds: list,
            out: Path):
        p, st = self.p, self.p.style
        intro_music = p.path(p.music.intro)
        body_music = p.path(p.music.body)
        for m in (intro_music, body_music):
            if m and not m.exists():
                warn(f"music not found, skipping: {m}")
        intro_music = intro_music if intro_music and intro_music.exists() else None
        body_music = body_music if body_music and body_music.exists() else None
        hook_len = pieces[0].duration if pieces[0].kind == "intro" else 0.0
        reveals = [(starts[j], b.reveal) for j, b in enumerate(pieces) if b.kind == "segment"]
        cuts = starts[1:]

        inputs = ["-i", base]
        fc = [f"[0:a]volume={p.voice.volume_db}dB,alimiter=limit=0.95,aformat=sample_rates=48000:"
              f"channel_layouts=stereo,apad,atrim=0:{total},asplit=2[vo][vokey]"]
        labels = ["[vo]"]
        n = 1

        def add_input(path, loop=False):
            nonlocal n
            if loop:
                inputs.extend(["-stream_loop", "-1"])
            inputs.extend(["-i", path])
            n += 1
            return n - 1

        music_parts = []
        if intro_music and hook_len > 0.5:
            k = add_input(intro_music, loop=True)
            fc.append(f"[{k}:a]atrim=0:{hook_len},asetpts=PTS-STARTPTS,afade=t=out:st={round(hook_len - 0.6, 2)}:d=0.6,"
                      f"aformat=sample_rates=48000:channel_layouts=stereo[mh]")
            music_parts.append("[mh]")
        body_src = body_music or intro_music
        if body_src:
            body_len = round(max(0.5, total - (hook_len if music_parts else 0.0)), 3)
            k = add_input(body_src, loop=True)
            gates = ""
            if intro_music:
                off0 = hook_len if music_parts else 0.0
                gates = "".join(f",volume=0.04:enable='between(t,{round(c - off0, 2)},"
                                f"{round(c - off0 + planner.stinger_len(rl), 2)})'" for c, rl in reveals)
            fc.append(f"[{k}:a]atrim=0:{body_len},asetpts=PTS-STARTPTS,afade=t=in:st=0:d=0.6{gates},"
                      f"afade=t=out:st={round(max(0.0, body_len - 1.5), 2)}:d=1.5,"
                      f"aformat=sample_rates=48000:channel_layouts=stereo[mb]")
            music_parts.append("[mb]")
        if music_parts:
            fc.append("".join(music_parts) + f"concat=n={len(music_parts)}:v=0:a=1,volume={p.music.volume}[music]")
            if p.music.duck:
                fc.append("[music][vokey]sidechaincompress=threshold=0.03:ratio=8:attack=20:release=700:makeup=1.5[mus]")
            else:
                fc.append("[vokey]anullsink;[music]anull[mus]")
            labels.append("[mus]")
        else:
            fc.append("[vokey]anullsink")
        # reveal stingers: slices of the intro track under each product reveal
        if intro_music and reveals:
            mdur = ff.duration(intro_music)
            k = add_input(intro_music)
            fc.append(f"[{k}:a]asplit={len(reveals)}" + "".join(f"[sti{j}]" for j in range(len(reveals))))
            for j, (c, rl) in enumerate(reveals):
                sl = planner.stinger_len(rl)
                off = round((j * 4.0) % max(1.0, mdur - sl), 2)
                ms_ = int(c * 1000)
                fc.append(f"[sti{j}]atrim={off}:{round(off + sl, 2)},asetpts=PTS-STARTPTS,"
                          f"afade=t=in:st=0:d=0.2,afade=t=out:st={round(sl - 0.6, 2)}:d=0.6,volume={p.music.volume * 2.2},"
                          f"aformat=sample_rates=48000:channel_layouts=stereo,adelay={ms_}|{ms_}[st{j}]")
                labels.append(f"[st{j}]")
        # whooshes on every transition
        wpath = sfx.resolve(p.sfx.whoosh, p)
        if wpath and Path(wpath).exists() and cuts:
            k = add_input(wpath)
            fc.append(f"[{k}:a]atrim=0:1.0,afade=t=out:st=0.7:d=0.3,volume={p.sfx.whoosh_volume},"
                      f"aformat=sample_rates=48000:channel_layouts=stereo,asplit={len(cuts)}"
                      + "".join(f"[w{j}]" for j in range(len(cuts))))
            for j, c in enumerate(cuts):
                ms_ = int(max(0.0, c) * 1000)
                fc.append(f"[w{j}]adelay={ms_}|{ms_}[wd{j}]")
                labels.append(f"[wd{j}]")
        # per-piece SFX, cold open and subscribe sounds
        events = []
        for j, b in enumerate(pieces):
            for path, vol, at, length, fin in b.sfx + b.sub_audio:
                events.append((path, vol, starts[j] + at, length, fin))
        events += extra_sounds
        for j, (path, vol, at, length, fin) in enumerate(events):
            if not Path(path).exists():
                continue
            k = add_input(path)
            ms_ = int(max(0.0, at) * 1000)
            fo = round(max(0.05, length - 0.4), 2)
            fc.append(f"[{k}:a]atrim={fin or 0}:{round((fin or 0) + length, 3)},asetpts=PTS-STARTPTS,"
                      f"afade=t=in:st=0:d=0.02,afade=t=out:st={fo}:d={round(min(0.4, length - fo), 2) or 0.05},"
                      f"volume={vol},aformat=sample_rates=48000:channel_layouts=stereo,adelay={ms_}|{ms_}[ev{j}]")
            labels.append(f"[ev{j}]")
        fc.append("".join(labels) + f"amix=inputs={len(labels)}:normalize=0:duration=first,alimiter=limit=0.95[aout]")
        ff.run(["-y"] + inputs + ["-filter_complex", ";".join(fc), "-map", "0:v", "-map", "[aout]",
                                  "-c:v", "copy", "-c:a", "aac", "-ar", "48000", "-b:a", "192k", "-t", total, out],
               desc="audio mix")

    def master(self, src: Path, dst: Path) -> tuple[float | None, float | None]:
        target = self.p.output.lufs
        measured = analysis.lufs(src, target)
        dst.parent.mkdir(parents=True, exist_ok=True)
        if measured is None:
            warn("loudness measurement failed - keeping the un-mastered mix")
            shutil.copy(src, dst)
            return None, None
        delta = round(target - measured, 2)
        ff.run(["-y", "-i", src, "-af", f"volume={delta}dB,alimiter=limit=0.97", "-c:v", "copy",
                "-c:a", "aac", "-ar", "48000", "-b:a", "192k", "-movflags", "+faststart", dst], desc="master")
        return measured, analysis.lufs(dst, target)

    # ------------------------------------------------------------------ main
    def render(self) -> dict:
        t0 = time.time()
        p = self.p
        pieces: list[Built] = []
        if p.intro.enabled:
            step("intro montage")
            pieces.append(self.build_intro())
        for i, seg in enumerate(p.segments, 1):
            step(f"segment {i}/{len(p.segments)}: {seg.label or seg.title}")
            pieces.append(self.build_segment(i, seg))
        if p.outro.enabled:
            step("outro")
            pieces.append(self.build_outro())
        step("assembling with transitions")
        base = self.work / "assembled.mkv"
        total, starts, mid_at, mid_sounds = self.assemble(pieces, base)
        step("mixing audio (music, ducking, whooshes, stingers, SFX)")
        mixed = self.work / "mixed.mp4"
        self.mix(base, total, pieces, starts, mid_sounds, mixed)
        step(f"mastering to {p.output.lufs} LUFS")
        out = p.path(p.output.path)
        before, after = self.master(mixed, out)
        final = ff.duration(out)
        manifest = {
            "output": str(out), "duration": round(final, 3), "lufs_before": before, "lufs_after": after,
            "format": p.output.format, "size": [self.W, self.H], "mid_subscribe_at": mid_at,
            "render_seconds": round(time.time() - t0, 1),
            "pieces": [{"kind": b.kind, "index": b.index, "label": b.label, "start": round(s, 3),
                        "duration": b.duration, "speech_start": b.speech_start, "link": b.link,
                        "words": [(round(s + w[0], 3), w[1], w[2]) for w in b.words]}
                       for b, s in zip(pieces, starts)],
        }
        (self.work / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
        ok(f"rendered {out} ({int(final // 60)}:{int(final % 60):02d}, {after} LUFS) "
           f"in {manifest['render_seconds']}s")
        return manifest


def load_manifest(proj: Project) -> dict:
    m = proj.work / "manifest.json"
    if not m.exists():
        raise FileNotFoundError("No render manifest yet - run `videopip render` first.")
    return json.loads(m.read_text(encoding="utf-8"))


def fmt_ts(t: float) -> str:
    t = int(math.floor(t))
    h, m, s = t // 3600, (t % 3600) // 60, t % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
