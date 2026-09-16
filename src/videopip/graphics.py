"""Still and animated graphics made with Pillow: fonts, banners, watermark,
the builtin animated subscribe button, and thumbnails."""
from __future__ import annotations

import hashlib
import math
import shutil
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from . import ff

FONT_DIR = Path.home() / ".videopip" / "fonts"
ASSET_DIR = Path.home() / ".videopip" / "assets"

_CANDIDATES = {
    "bold": [
        "C:/Windows/Fonts/arialbd.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/Library/Fonts/Arial Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        str(FONT_DIR / "Lato-Bold.ttf"),
    ],
    "bolditalic": [
        "C:/Windows/Fonts/arialbi.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold Italic.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-BoldOblique.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-BoldOblique.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-BoldItalic.ttf",
        str(FONT_DIR / "Lato-BoldItalic.ttf"),
    ],
    "display": [
        str(FONT_DIR / "Anton-Regular.ttf"),
        "C:/Windows/Fonts/impact.ttf",
        "/System/Library/Fonts/Supplemental/Impact.ttf",
        "/usr/share/fonts/truetype/msttcorefonts/Impact.ttf",
    ],
}


def find_font(kind: str = "bold", override: str | None = None) -> str:
    if override and Path(override).exists():
        return str(override)
    for c in _CANDIDATES.get(kind, []):
        if Path(c).exists():
            return c
    if kind != "bold":
        return find_font("bold")
    raise FileNotFoundError("No bold TTF font found. Run `videopip setup` to download one, "
                            "or set brand.font to a .ttf file.")


def font(size: int, kind: str = "bold", override: str | None = None) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(find_font(kind, override), size)


def local_font(cwd: Path, kind: str = "bold", override: str | None = None) -> str:
    """Copy a font next to the ffmpeg job and return its bare name. ffmpeg's
    filtergraph parser chokes on the drive colon in Windows font paths."""
    cwd = Path(cwd)
    cwd.mkdir(parents=True, exist_ok=True)
    name = f"font_{kind}.ttf"
    dst = cwd / name
    src = find_font(kind, override)
    if not dst.exists() or dst.stat().st_size != Path(src).stat().st_size:
        shutil.copy(src, dst)
    return name


def rgba(color: str, alpha: int = 255) -> tuple[int, int, int, int]:
    c = color.lstrip("#").replace("0x", "")
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16), alpha


def ffcolor(color: str) -> str:
    return "0x" + color.lstrip("#").replace("0x", "")[:6]


# --------------------------------------------------------------------------- banners
def banner(text: str, out: Path, style: str = "white", size: int = 68, font_path: str | None = None,
           bg: tuple | None = None, fg: tuple | None = None) -> tuple[int, int]:
    """Title banner PNG sized to its text. Returns (w, h)."""
    f = font(size, "bolditalic", font_path)
    probe = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    x0, y0, x1, y1 = probe.textbbox((0, 0), text, font=f)
    tw, th = x1 - x0, y1 - y0
    if style == "neon":
        return _neon(text.upper(), out, f)
    pad_x, pad_y = 44, 28
    if bg is None:
        bg = (255, 255, 255, 235) if style == "white" else (12, 12, 16, 225)
    if fg is None:
        fg = (15, 15, 15, 255) if style == "white" else (255, 255, 255, 255)
    w, h = tw + pad_x * 2, th + pad_y * 2
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, w - 1, h - 1), radius=10, fill=bg)
    if style == "dark":
        d.rectangle((0, 0, 10, h), fill=(57, 255, 110, 255))
    d.text((pad_x - x0, pad_y - y0), text, font=f, fill=fg)
    img.save(out)
    return w, h


def _neon(text: str, out: Path, f) -> tuple[int, int]:
    cyan, green = (35, 225, 255, 255), (70, 255, 110, 255)
    probe = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    x0, y0, x1, y1 = probe.textbbox((0, 0), text, font=f)
    tw, th = x1 - x0, y1 - y0
    W, H = tw + 300, th + 170
    x, y = 90 - x0, 30 - y0
    base = 30 + th + 30
    left = [(30, base + 6), (72, 18)]
    under = [(34, base), (90 + tw + 24, base), (90 + tw + 86, base + 58)]
    grn = [(90 + tw - 150, base + 96 - 30), (90 + tw + 120, base + 96 - 30), (90 + tw + 178, base + 20)]
    layers = []
    for blur, col_t, col_l, col_g, width in ((14, (0, 0, 0, 255), (0, 0, 0, 255), (0, 0, 0, 255), 16),
                                              (10, (150, 240, 255, 255), cyan, green, 11),
                                              (0, (255, 255, 255, 255), cyan, green, 11)):
        im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        d.line(left, fill=col_l, width=width, joint="curve")
        d.line(under, fill=col_l, width=width, joint="curve")
        d.line(grn, fill=col_g, width=max(9, width - 2), joint="curve")
        d.text((x, y), text, font=f, fill=col_t, stroke_width=6 if blur == 14 else 0,
               stroke_fill=(0, 0, 0, 255))
        if blur:
            im = im.filter(ImageFilter.GaussianBlur(blur))
        layers.append(im)
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    for im, times in zip(layers, (2, 2, 1)):
        for _ in range(times):
            img = Image.alpha_composite(img, im)
    img.save(out)
    return W, H


def watermark(logo: Path, out: Path, width: int = 160) -> tuple[int, int]:
    src = Image.open(logo).convert("RGBA")
    h = max(1, round(src.height * width / src.width))
    src = src.resize((width, h), Image.LANCZOS)
    pad = 12
    canvas = Image.new("RGBA", (width + pad * 2, h + pad * 2), (0, 0, 0, 0))
    shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    shadow.paste(Image.new("RGBA", src.size, (0, 0, 0, 190)), (pad, pad), src)
    shadow = shadow.filter(ImageFilter.GaussianBlur(5))
    canvas = Image.alpha_composite(Image.alpha_composite(canvas, shadow), shadow)
    canvas.paste(src, (pad, pad), src)
    canvas.save(out)
    return canvas.size


# --------------------------------------------------------------------------- builtin subscribe
def _ease_back(t: float) -> float:
    c1, c3 = 1.70158, 2.70158
    t = min(max(t, 0.0), 1.0)
    return 1 + c3 * (t - 1) ** 3 + c1 * (t - 1) ** 2


def _lerp(a, b, t):
    t = min(max(t, 0.0), 1.0)
    return a + (b - a) * t


def _cursor(d: ImageDraw.ImageDraw, x: float, y: float, s: float = 1.0):
    pts = [(0, 0), (0, 46), (12, 35), (21, 56), (30, 52), (21, 32), (38, 32)]
    poly = [(x + px * s, y + py * s) for px, py in pts]
    d.polygon(poly, fill=(255, 255, 255, 255), outline=(0, 0, 0, 255), width=3)


def _bell(img: Image.Image, cx: float, cy: float, r: float, angle: float, color):
    layer = Image.new("RGBA", (int(r * 3), int(r * 3)), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    c = r * 1.5
    d.pieslice((c - r * 0.8, c - r * 0.95, c + r * 0.8, c + r * 0.65), 180, 360, fill=color)
    d.polygon([(c - r * 0.8, c - r * 0.15), (c + r * 0.8, c - r * 0.15),
               (c + r * 1.0, c + r * 0.55), (c - r * 1.0, c + r * 0.55)], fill=color)
    d.ellipse((c - r * 0.22, c + r * 0.55, c + r * 0.22, c + r * 0.95), fill=color)
    d.ellipse((c - r * 0.12, c - r * 1.08, c + r * 0.12, c - r * 0.84), fill=color)
    layer = layer.rotate(angle, resample=Image.BICUBIC, center=(c, c - r * 0.9))
    img.alpha_composite(layer, (int(cx - c), int(cy - c)))


def builtin_subscribe(duration: float = 5.0, fps: int = 30, accent: str = "#FF0000") -> Path:
    """Animated subscribe button + cursor click + bell, rendered to a transparent .mov.
    Cached in ~/.videopip/assets."""
    key = hashlib.sha1(f"sub3|{duration}|{fps}|{accent}".encode()).hexdigest()[:12]
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    out = ASSET_DIR / f"subscribe_{key}.mov"
    if out.exists():
        return out
    frames = ASSET_DIR / f"sub_frames_{key}"
    frames.mkdir(exist_ok=True)
    W, H = 900, 300
    red = rgba(accent)
    grey = (96, 96, 96, 255)
    f = font(64, "bold")
    n = int(duration * fps)
    click1, click2 = 1.45, 2.55
    bx, by, bw, bh = 60, 95, 560, 130
    bell_c = (760, 160)
    for i in range(n):
        t = i / fps
        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        # button pop-in and click squish
        s = _ease_back(t / 0.35)
        if click1 <= t < click1 + 0.14:
            s *= 0.92
        s = max(s, 0.001)
        subscribed = t >= click1 + 0.07
        btn = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
        bd = ImageDraw.Draw(btn)
        bd.rounded_rectangle((0, 0, bw - 1, bh - 1), radius=26, fill=grey if subscribed else red)
        label = "SUBSCRIBED" if subscribed else "SUBSCRIBE"
        tx0, ty0, tx1, ty1 = bd.textbbox((0, 0), label, font=f)
        bd.text(((bw - (tx1 - tx0)) / 2 - tx0, (bh - (ty1 - ty0)) / 2 - ty0), label, font=f,
                fill=(255, 255, 255, 255))
        sw, sh = max(1, int(bw * s)), max(1, int(bh * s))
        btn = btn.resize((sw, sh), Image.LANCZOS)
        shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ImageDraw.Draw(shadow).rounded_rectangle(
            (bx + bw / 2 - sw / 2 + 6, by + bh / 2 - sh / 2 + 8, bx + bw / 2 + sw / 2 + 6, by + bh / 2 + sh / 2 + 8),
            radius=26, fill=(0, 0, 0, 140))
        img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(8)))
        img.alpha_composite(btn, (int(bx + bw / 2 - sw / 2), int(by + bh / 2 - sh / 2)))
        # bell
        if t >= 0.5:
            bs = _ease_back((t - 0.5) / 0.35)
            ang = 0.0
            if click2 <= t < click2 + 0.9:
                ang = 22 * math.sin((t - click2) * 30) * (1 - (t - click2) / 0.9)
            bell_col = (255, 255, 255, 255) if t >= click2 else (230, 230, 230, 255)
            bg = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            ImageDraw.Draw(bg).ellipse((bell_c[0] - 62 * bs, bell_c[1] - 62 * bs,
                                        bell_c[0] + 62 * bs, bell_c[1] + 62 * bs),
                                       fill=red if t >= click2 else (40, 40, 40, 230))
            img.alpha_composite(bg)
            if bs > 0.2:
                _bell(img, bell_c[0], bell_c[1] + 4, 34 * bs, ang, bell_col)
        # cursor path: offscreen -> button -> bell -> away
        if 0.6 <= t:
            if t < click1:
                u = (t - 0.6) / (click1 - 0.6)
                cx, cy = _lerp(W + 20, bx + bw * 0.62, u), _lerp(H + 20, by + bh * 0.55, u)
            elif t < click1 + 0.45:
                cx, cy = bx + bw * 0.62, by + bh * 0.55
            elif t < click2:
                u = (t - click1 - 0.45) / (click2 - click1 - 0.45)
                cx, cy = _lerp(bx + bw * 0.62, bell_c[0] + 8, u), _lerp(by + bh * 0.55, bell_c[1] + 10, u)
            else:
                u = (t - click2 - 0.5) / 0.8
                cx, cy = _lerp(bell_c[0] + 8, W + 60, u), _lerp(bell_c[1] + 10, H + 60, u)
            pressed = (click1 <= t < click1 + 0.14) or (click2 <= t < click2 + 0.14)
            _cursor(ImageDraw.Draw(img), cx, cy, 0.88 if pressed else 1.0)
        # fade out
        fade = min(1.0, max(0.0, (duration - t) / 0.4))
        if fade < 1.0:
            a = img.getchannel("A").point(lambda v: int(v * fade))
            img.putalpha(a)
        img.save(frames / f"f{i:04d}.png")
    ff.run(["-y", "-framerate", fps, "-i", "f%04d.png", "-c:v", "png", "-pix_fmt", "rgba", str(out)],
           cwd=frames, desc="subscribe animation")
    shutil.rmtree(frames, ignore_errors=True)
    return out


def builtin_subscribe_click_times() -> list[float]:
    return [1.45, 2.55]


# --------------------------------------------------------------------------- thumbnails
def cover_crop(img: Image.Image, tw: int, th: int, focal_y: float = 0.5) -> Image.Image:
    iw, ih = img.size
    s = max(tw / iw, th / ih)
    img = img.resize((max(1, int(iw * s)), max(1, int(ih * s))), Image.LANCZOS)
    left = (img.width - tw) // 2
    top = max(0, min(img.height - th, int((img.height - th) * focal_y)))
    return img.crop((left, top, left + tw, top + th))


def fit_16x9(img: Image.Image, W: int = 1280, H: int = 720) -> Image.Image:
    """Square/tall image -> 16:9 with blurred wings (no cropping of the subject)."""
    bg = cover_crop(img.convert("RGB"), W, H).filter(ImageFilter.GaussianBlur(28))
    fg = img.convert("RGBA")
    s = min(W / fg.width, H / fg.height)
    fg = fg.resize((int(fg.width * s), int(fg.height * s)), Image.LANCZOS)
    bg.paste(fg, ((W - fg.width) // 2, (H - fg.height) // 2), fg)
    return bg


def _outlined(d, xy, text, f, fill, outline=(0, 0, 0), ow=6, anchor=None):
    d.text(xy, text, font=f, fill=fill, anchor=anchor, stroke_width=ow, stroke_fill=outline)


def thumbnail(images: list[tuple[Image.Image, str | None, str]], headline: str, subline: str,
              out: Path, W: int = 1280, H: int = 720, cutout: bool = False) -> Path:
    canvas = Image.new("RGB", (W, H), (18, 18, 22))
    n = max(1, min(len(images), 4))
    pw = W // n
    for i, (im, badge, color) in enumerate(images[:n]):
        if cutout:
            try:
                from rembg import remove  # optional
                cut = remove(im.convert("RGBA"))
                panel = Image.new("RGBA", (pw, H), rgba("#1e1e26"))
                cut.thumbnail((pw - 20, H - 180))
                panel.alpha_composite(cut, ((pw - cut.width) // 2, H - cut.height - 20))
                panel = panel.convert("RGB")
            except ImportError:
                panel = cover_crop(im.convert("RGB"), pw, H, 0.45)
        else:
            panel = cover_crop(im.convert("RGB"), pw, H, 0.45)
        canvas.paste(panel, (i * pw, 0))
        if i:
            ImageDraw.Draw(canvas).rectangle((i * pw - 3, 0, i * pw + 3, H), fill=(255, 255, 255))
        if badge:
            d = ImageDraw.Draw(canvas)
            bf = font(44, "display")
            x0, y0, x1, y1 = d.textbbox((0, 0), badge, font=bf)
            bx, by = i * pw + (pw - (x1 - x0)) // 2 - 18, H - 120
            d.rounded_rectangle((bx, by, bx + (x1 - x0) + 36, by + (y1 - y0) + 30), 12, fill=rgba(color)[:3])
            _outlined(d, (bx + 18 - x0, by + 15 - y0), badge, bf, (255, 255, 255), ow=3)
    d = ImageDraw.Draw(canvas)
    if headline:
        size = 118
        hf = font(size, "display")
        while d.textlength(headline, font=hf) > W - 80 and size > 48:
            size -= 6
            hf = font(size, "display")
        grad = Image.new("RGBA", (W, 260), (0, 0, 0, 0))
        gd = ImageDraw.Draw(grad)
        for yy in range(260):
            gd.line((0, yy, W, yy), fill=(0, 0, 0, int(200 * (1 - yy / 260))))
        canvas.paste(grad, (0, 0), grad)
        _outlined(d, (W // 2, 30), headline, hf, (255, 226, 74), ow=8, anchor="ma")
        if subline:
            sf = font(58, "display")
            _outlined(d, (W // 2, 40 + size), subline, sf, (255, 255, 255), ow=6, anchor="ma")
    canvas.save(out, quality=92)
    return out
