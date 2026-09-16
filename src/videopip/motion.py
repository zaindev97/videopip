"""Motion-graphics overlays rendered to transparent .mov files.

Two kinds:
* builtin templates (price_tag, rating, badge, progress, lower_third) drawn
  frame by frame with Pillow - no extra dependencies;
* custom HTML/CSS templates (any .html file) captured frame by frame with
  Playwright/Chromium. `{{key}}` placeholders are filled from `data`, and CSS
  animations are scrubbed deterministically via the Web Animations API.
"""
from __future__ import annotations

import hashlib
import json
import math
import shutil
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

from . import ff
from .config import OverlaySpec
from .graphics import ASSET_DIR, font, rgba

BUILTIN = ("price_tag", "rating", "badge", "progress", "lower_third")


class MotionUnavailable(RuntimeError):
    pass


def _ease_out(t):
    t = min(max(t, 0.0), 1.0)
    return 1 - (1 - t) ** 3


def _back(t):
    t = min(max(t, 0.0), 1.0)
    return 1 + 2.70158 * (t - 1) ** 3 + 1.70158 * (t - 1) ** 2


def _card(w, h, fill, radius=24):
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    sh = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle((10, 14, w - 6, h - 4), radius, fill=(0, 0, 0, 130))
    im.alpha_composite(sh.filter(ImageFilter.GaussianBlur(8)))
    ImageDraw.Draw(im).rounded_rectangle((4, 4, w - 12, h - 18), radius, fill=fill)
    return im


def _fit_text(d, text, maxw, size, kind="bold"):
    f = font(size, kind)
    while d.textlength(text, font=f) > maxw and size > 14:
        size -= 2
        f = font(size, kind)
    return f


def _masked(layer: Image.Image, mask: Image.Image) -> Image.Image:
    out = layer.copy()
    out.putalpha(ImageChops.multiply(layer.getchannel("A"), mask))
    return out


def _place(dst: Image.Image, src: Image.Image, x: int, y: int):
    """alpha_composite that tolerates negative / off-canvas offsets."""
    sx, sy = max(0, -x), max(0, -y)
    x, y = max(0, x), max(0, y)
    w = min(src.width - sx, dst.width - x)
    h = min(src.height - sy, dst.height - y)
    if w > 0 and h > 0:
        dst.alpha_composite(src.crop((sx, sy, sx + w, sy + h)), (x, y))


def _star(d, cx, cy, r, fill):
    pts = []
    for k in range(10):
        ang = -math.pi / 2 + k * math.pi / 5
        rr = r if k % 2 == 0 else r * 0.45
        pts.append((cx + rr * math.cos(ang), cy + rr * math.sin(ang)))
    d.polygon(pts, fill=fill)


def _frame(template: str, data: dict, W: int, H: int, t: float, dur: float) -> Image.Image:
    accent = rgba(str(data.get("color", "#FFE24A")))
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    intro = _back(t / 0.45)
    fade = min(1.0, max(0.0, (dur - t) / 0.35))
    if template == "price_tag":
        card = _card(W, H, (15, 15, 20, 235))
        d = ImageDraw.Draw(card)
        label = str(data.get("label", "PRICE"))
        price = str(data.get("price", "$0"))
        d.rounded_rectangle((4, 4, 26, H - 18), 12, fill=accent)
        fl = _fit_text(d, label.upper(), W - 70, int(H * 0.2))
        d.text((44, int(H * 0.12)), label.upper(), font=fl, fill=(200, 200, 200, 255))
        # price counts up
        num = "".join(ch for ch in price if ch.isdigit() or ch == ".")
        shown = price
        try:
            val = float(num)
            v = val * _ease_out(t / 0.9)
            shown = price.replace(num, f"{v:.2f}" if "." in num else f"{int(round(v))}")
        except ValueError:
            pass
        fp = _fit_text(d, price, W - 70, int(H * 0.46), "display")
        d.text((44, int(H * 0.36)), shown, font=fp, fill=accent)
        s = max(0.01, intro)
        card = card.resize((max(1, int(W * s)), max(1, int(H * s))), Image.LANCZOS)
        _place(img, card, (W - card.width) // 2, (H - card.height) // 2)
    elif template == "rating":
        card = _card(W, H, (15, 15, 20, 235))
        d = ImageDraw.Draw(card)
        stars = float(data.get("stars", 4.5))
        r = int(min(H * 0.2, (W - 80) / 11))
        for k in range(5):
            cx = 44 + r + k * (2.2 * r)
            cy = int(H * 0.36)
            appear = _back((t - 0.1 - k * 0.12) / 0.3)
            if appear <= 0.02:
                continue
            rr = r * appear
            _star(d, cx, cy, rr, (70, 70, 80, 255))
            fill_frac = min(1.0, max(0.0, stars - k))
            if fill_frac > 0:
                layer = Image.new("RGBA", card.size, (0, 0, 0, 0))
                _star(ImageDraw.Draw(layer), cx, cy, rr, accent)
                mask = Image.new("L", card.size, 0)
                ImageDraw.Draw(mask).rectangle((0, 0, int(cx - rr + 2 * rr * fill_frac), card.height), fill=255)
                card.alpha_composite(_masked(layer, mask))
        text = str(data.get("text", f"{stars} / 5"))
        ft = _fit_text(d, text, W - 70, int(H * 0.2))
        d.text((44, int(H * 0.62)), text, font=ft, fill=(255, 255, 255, 255))
        x = int((1 - _ease_out(t / 0.4)) * -W)
        _place(img, card, x, 0)
    elif template == "badge":
        text = str(data.get("text", "BEST VALUE"))
        s = max(0.01, intro)
        card = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(card)
        d.rounded_rectangle((8, 8, W - 8, H - 8), int(H * 0.25), fill=accent)
        f = _fit_text(d, text, W - 60, int(H * 0.5), "display")
        d.text((W / 2, H / 2), text, font=f, fill=str(data.get("text_color", "#111111")), anchor="mm")
        shine = (t % 2.0) / 2.0
        sl = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        sx = int(-W * 0.3 + shine * W * 1.6)
        ImageDraw.Draw(sl).polygon([(sx, 0), (sx + 40, 0), (sx - 20, H), (sx - 60, H)], fill=(255, 255, 255, 90))
        card.alpha_composite(sl)
        card = _masked(card, _rounded_mask(W, H, int(H * 0.25)))
        ang = -6 * (1 - _ease_out(t / 0.5))
        card = card.resize((max(1, int(W * s)), max(1, int(H * s))), Image.LANCZOS).rotate(ang, expand=False)
        _place(img, card, (W - card.width) // 2, (H - card.height) // 2)
    elif template == "progress":
        cur, total = int(data.get("current", 1)), int(data.get("total", 10))
        card = _card(W, H, (15, 15, 20, 225))
        d = ImageDraw.Draw(card)
        f = _fit_text(d, f"{cur} OF {total}", W - 60, int(H * 0.3), "display")
        d.text((32, int(H * 0.1)), f"{cur} OF {total}", font=f, fill=(255, 255, 255, 255))
        bx0, by0, bx1, by1 = 32, int(H * 0.58), W - 44, int(H * 0.72)
        d.rounded_rectangle((bx0, by0, bx1, by1), (by1 - by0) // 2, fill=(60, 60, 70, 255))
        frac = ((cur - 1) + _ease_out(t / 0.8)) / max(1, total)
        d.rounded_rectangle((bx0, by0, bx0 + max(by1 - by0, int((bx1 - bx0) * frac)), by1),
                            (by1 - by0) // 2, fill=accent)
        y = int((1 - _ease_out(t / 0.4)) * -H)
        _place(img, card, 0, y)
    elif template == "lower_third":
        title = str(data.get("title", ""))
        sub = str(data.get("subtitle", ""))
        wipe = _ease_out(t / 0.5)
        card = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(card)
        d.rectangle((0, int(H * 0.08), 14, int(H * 0.92)), fill=accent)
        d.rectangle((14, int(H * 0.08), W, int(H * 0.58)), fill=(15, 15, 20, 235))
        d.rectangle((14, int(H * 0.58), int(W * 0.8), int(H * 0.92)), fill=accent)
        ft = _fit_text(d, title, W - 60, int(H * 0.34))
        d.text((36, int(H * 0.33)), title, font=ft, fill=(255, 255, 255, 255), anchor="lm")
        fs = _fit_text(d, sub, int(W * 0.8) - 60, int(H * 0.22))
        d.text((36, int(H * 0.75)), sub, font=fs, fill=(15, 15, 20, 255), anchor="lm")
        mask = Image.new("L", (W, H), 0)
        ImageDraw.Draw(mask).rectangle((0, 0, int(W * wipe), H), fill=255)
        img.alpha_composite(_masked(card, mask))
    else:
        raise ValueError(f"unknown builtin template {template}")
    if fade < 1.0:
        img.putalpha(img.getchannel("A").point(lambda v: int(v * fade)))
    return img


def _rounded_mask(w, h, r):
    m = Image.new("L", (w, h), 0)
    ImageDraw.Draw(m).rounded_rectangle((8, 8, w - 8, h - 8), r, fill=255)
    return m


def _encode(frames_dir: Path, fps: int, out: Path):
    ff.run(["-y", "-framerate", fps, "-i", "f%04d.png", "-c:v", "png", "-pix_fmt", "rgba", str(out)],
           cwd=frames_dir, desc="motion overlay")


def render(ov: OverlaySpec, proj, fps: int = 30) -> Path:
    tpl = ov.template
    custom = None
    if tpl not in BUILTIN:
        custom = proj.path(tpl)
        if not custom or not custom.exists():
            raise MotionUnavailable(f"overlay template not found: {tpl} (builtins: {', '.join(BUILTIN)})")
    src_sig = custom.read_text(encoding="utf-8") if custom else tpl
    key = hashlib.sha1(json.dumps([src_sig, ov.data, ov.width, ov.height, ov.duration, fps, "m2"],
                                  sort_keys=True).encode()).hexdigest()[:14]
    out_dir = ASSET_DIR / "motion"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{Path(tpl).stem}_{key}.mov"
    if out.exists():
        return out
    frames = out_dir / f"frames_{key}"
    frames.mkdir(exist_ok=True)
    n = max(1, int(round(ov.duration * fps)))
    # render at 2x the overlay width for crisp downscaling
    W, H = ov.width, ov.height
    if custom:
        _render_html(custom, ov.data, W, H, n, fps, frames)
    else:
        for i in range(n):
            _frame(tpl, ov.data, W, H, i / fps, ov.duration).save(frames / f"f{i:04d}.png")
    _encode(frames, fps, out)
    shutil.rmtree(frames, ignore_errors=True)
    return out


def _render_html(path: Path, data: dict, W: int, H: int, n: int, fps: int, frames: Path):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        raise MotionUnavailable("custom HTML overlays need Playwright: pip install 'videopip[motion]' "
                                "&& playwright install chromium") from e
    html = path.read_text(encoding="utf-8")
    for k, v in data.items():
        html = html.replace("{{" + k + "}}", str(v))
    html = html.replace("{{duration}}", str(n / fps))
    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch()
        except Exception as e:
            raise MotionUnavailable("Chromium is not installed for Playwright: run `playwright install chromium`") from e
        page = browser.new_page(viewport={"width": W, "height": H})
        page.set_content(html, wait_until="load")
        page.evaluate("document.fonts && document.fonts.ready")
        for i in range(n):
            t_ms = i * 1000 / fps
            page.evaluate("""(t) => {
                document.getAnimations().forEach(a => { a.pause(); a.currentTime = t; });
                if (window.videopipSeek) window.videopipSeek(t / 1000);
            }""", t_ms)
            page.screenshot(path=str(frames / f"f{i:04d}.png"), omit_background=True)
        browser.close()
