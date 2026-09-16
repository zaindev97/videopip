"""Thumbnail + title/description/chapters/tags from the render manifest."""
from __future__ import annotations

from pathlib import Path

from PIL import Image

from . import analysis, ff, graphics
from .config import Project
from .log import ok, warn
from .render import fmt_ts, load_manifest


def make_thumbnail(proj: Project) -> Path | None:
    t = proj.thumbnail
    if not t.enabled:
        return None
    work = proj.work / "thumb"
    work.mkdir(parents=True, exist_ok=True)
    imgs = t.images
    if not imgs:
        from .config import ThumbImage
        colors = ["#2ECC71", "#3498DB", "#E74C3C"]
        imgs = [ThumbImage(clip=s.clips[0], badge=(s.label or s.title).upper()[:18], badge_color=colors[i % 3])
                for i, s in enumerate(proj.segments[:3])]
    panels = []
    for i, im in enumerate(imgs):
        if im.file:
            src = proj.path(im.file)
            if not src.exists():
                warn(f"thumbnail image not found: {src}")
                continue
            pil = Image.open(src)
            if abs(pil.width / pil.height - 16 / 9) > 0.2 and len(imgs) == 1:
                pil = graphics.fit_16x9(pil)
        else:
            clip = proj.clip_path(im.clip)
            spec = proj.clips[im.clip]
            ranges = spec.safe or [(0.3, max(0.6, ff.duration(clip) - 0.3))]
            at = im.at if im.at is not None else analysis.best_window(clip, 0.6, ranges) + 0.3
            frame = work / f"frame_{i}.png"
            ff.run(["-y", "-ss", round(at, 3), "-i", clip, "-frames:v", "1", frame], desc="thumb frame")
            pil = Image.open(frame)
        panels.append((pil, im.badge, im.badge_color))
    if not panels:
        warn("no thumbnail images available")
        return None
    out = proj.path(t.path)
    out.parent.mkdir(parents=True, exist_ok=True)
    graphics.thumbnail(panels, t.headline, t.subline, out, cutout=t.cutout)
    ok(f"thumbnail {out}")
    return out


def make_metadata(proj: Project) -> Path:
    man = load_manifest(proj)
    m = proj.metadata
    lines = []
    if m.title:
        lines += [f"TITLE: {m.title}", ""]
    if m.description:
        lines += [m.description.strip(), ""]
    links = [p for p in man["pieces"] if p["kind"] == "segment"]
    if any(p.get("link") for p in links):
        lines.append("PRODUCTS")
        for p in links:
            if p.get("link"):
                lines.append(f"{p['index']}. {p['label']}: {p['link']}")
        lines.append("")
    lines.append("CHAPTERS")
    first = True
    for p in man["pieces"]:
        if p["kind"] == "outro":
            label = "Final thoughts"
        elif p["kind"] == "intro":
            label = "Intro"
        else:
            seg = proj.segments[p["index"] - 1]
            label = seg.chapter or p["label"]
        # YouTube requires the first chapter at 0:00
        ts = "0:00" if first else fmt_ts(p["start"] + 0.5)
        lines.append(f"{ts} {label}")
        first = False
    lines.append("")
    if m.disclosure:
        lines += [m.disclosure, ""]
    if m.tags:
        lines += ["TAGS: " + ", ".join(m.tags)]
    out = proj.path(m.path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    if len(links) + 2 < 3:
        warn("YouTube needs at least 3 chapters to show them")
    ok(f"metadata {out}")
    return out
