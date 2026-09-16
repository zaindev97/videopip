"""Project spec: the single YAML file an AI assistant writes and `videopip render` executes.

Every field has a sensible default so a minimal spec is ~15 lines. The JSON
schema (`videopip schema`) is generated from these models, so AI tools can
validate what they write before anything renders.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Literal, Optional, Union

import yaml
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, field_validator, model_validator

SPEC_VERSION = 1

Range = tuple[float, float]


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------- clips
class Box(_M):
    """A rectangle in SOURCE pixels, e.g. a third-party watermark to blur out."""
    x: int
    y: int
    w: int
    h: int


class ClipSpec(_M):
    file: str = Field(description="Path to the source clip, relative to clips_dir.")
    safe: Optional[list[Range]] = Field(
        None, description="Verified usable time ranges [start, end] in seconds. Exclude logo cards, "
                          "brand end-cards, text screens and third-party bumpers. Omit = whole clip "
                          "(minus 0.3s at each edge).")
    delogo: list[Box] = Field(default_factory=list,
                              description="Persistent corner logos/watermarks to remove (ffmpeg delogo).")
    crop: Optional[str] = Field(None, description="Pre-crop as ffmpeg 'w:h:x:y', applied before scaling.")
    use_audio: bool = Field(False, description="Keep the clip's own audio (quietly) under the VO.")
    audio_volume: float = 0.15
    notes: str = ""


# --------------------------------------------------------------------------- voice / audio
class VoiceSpec(_M):
    engine: Literal["edge", "openai", "elevenlabs", "piper", "silent"] = Field(
        "edge", description="edge = free Microsoft Edge voices (unofficial service, use at your own risk); "
                            "openai/elevenlabs need an API key env var; piper = offline; "
                            "silent = no voice (timing estimated from word count, for tests).")
    voice: str = "en-US-AndrewMultilingualNeural"
    rate: str = Field("+0%", description="edge only, e.g. '+8%'.")
    model: Optional[str] = Field(None, description="openai/elevenlabs/piper model name or path.")
    api_key_env: Optional[str] = Field(None, description="Env var holding the API key.")
    lexicon: dict[str, str] = Field(default_factory=dict,
                                    description="Pronunciation fixes: {'Makita': 'Mah-KEE-tah'}. "
                                                "Only the TTS text changes, never on-screen text.")
    lexicon_file: Optional[str] = None
    volume_db: float = Field(8.5, description="Gain applied to the VO before mixing.")


class MusicSpec(_M):
    intro: Optional[str] = Field(None, description="Upbeat track for the intro and product 'reveal' stingers.")
    body: Optional[str] = Field(None, description="Background bed under the voiceover (loops).")
    volume: float = 0.38
    duck: bool = Field(True, description="Sidechain-duck the music under the voice.")


class SfxSpec(_M):
    whoosh: Optional[str] = Field("builtin:whoosh",
                                  description="Plays on every transition. 'builtin:whoosh' is synthesized, "
                                              "a path uses your own file, null disables.")
    whoosh_volume: float = 0.85
    cold_open: Optional[str] = Field(None, description="Crisp transient that plays alone before the intro VO "
                                                        "(e.g. a saw bite). 'builtin:impact' or a path.")
    cold_open_volume: float = 0.8
    cold_open_gap: float = Field(1.2, description="Seconds of SFX before the intro VO starts.")
    cold_open_in: Optional[float] = Field(None, description="Start offset inside the SFX file; "
                                                             "omit = loudest window (needs librosa).")


# --------------------------------------------------------------------------- look
class BrandSpec(_M):
    watermark: Optional[str] = Field(None, description="Logo PNG (transparent) shown top-left.")
    watermark_width: int = 160
    font: Optional[str] = Field(None, description="Bold TTF for lower-thirds/cards. Omit = system bold font.")
    title_font: Optional[str] = Field(None, description="Bold-italic TTF for title banners.")
    accent: str = Field("#39FF6E", description="Accent colour for cards and captions.")
    grade: str = Field("eq=contrast=1.06:saturation=1.12:brightness=0.02:gamma=0.97",
                       description="ffmpeg colour grade filter, or 'none'.")
    banner_style: Literal["white", "neon", "dark"] = "white"


class TransitionSpec(_M):
    types: list[str] = Field(default_factory=lambda: ["slideleft", "slideright"],
                             description="ffmpeg xfade transition names, cycled.")
    duration: float = 0.5


class StyleSpec(_M):
    reveal: float = Field(2.6, description="Seconds of music-only 'reveal' before each product's VO.")
    first_reveal: float = Field(1.5, description="Shorter reveal for segment #1 (keeps retention up).")
    reveal_gap: float = Field(0.6, description="Silence between stinger end and VO start.")
    tail: float = Field(0.6, description="Hold after each VO ends.")
    chunk: float = Field(4.0, description="Max seconds per b-roll cut inside a segment.")
    numbering: Literal["ascending", "countdown", "none"] = "ascending"
    lower_third: bool = True
    lower_third_y: int = 40
    banner_y: int = 230
    show_callouts: bool = False
    show_verdict: bool = False
    verdict_hold: float = 4.0
    replay_warn: float = Field(1.6, description="Warn when a segment must replay its footage more than this.")
    transitions: TransitionSpec = Field(default_factory=TransitionSpec)


# --------------------------------------------------------------------------- structure
class SubscribeSpec(_M):
    enabled: bool = True
    source: str = Field("builtin", description="'builtin' (animated button made by videopip) or a "
                                                "green-screen subscribe clip path.")
    at: float = Field(15.0, description="Intro: seconds into the video. Mid: target time (moved to "
                                         "the nearest talking beat).")
    duration: Optional[float] = Field(None, description="Seconds on screen (default: whole asset / 6s mid).")
    position: Literal["bottom-center", "bottom-right", "bottom-left", "top-right", "center"] = "bottom-center"
    width: int = 470
    margin_x: int = 40
    margin_y: int = 130
    chroma_color: str = Field("0x06D806", description="Green-screen key colour (custom source only).")
    chroma_similarity: float = 0.16
    chroma_blend: float = 0.05
    crop: Optional[str] = Field(None, description="Crop the green-screen asset first, 'w:h:x:y'.")
    audio_volume: float = Field(0.55, description="Asset's own click sound; 0 = muted.")


class Callout(_M):
    text: str
    at: float
    duration: float = 2.5


class ForcedTake(_M):
    """A must-show moment played as ONE unbroken take right after the reveal."""
    clip: str
    start: float
    duration: float


class SegmentSfx(_M):
    file: str = Field(description="Path or builtin:whoosh|impact|riser|click|pop.")
    volume: float = 0.2
    at: Optional[float] = Field(None, description="Seconds into the segment; omit = at the reveal.")
    length: float = 4.0
    file_in: Optional[float] = None


class OverlaySpec(_M):
    """Animated motion-graphics overlay (HTML template rendered with Playwright, or builtin)."""
    template: str = Field(description="Builtin: price_tag, rating, badge, progress, lower_third, "
                                      "or a path to your own .html template.")
    data: dict[str, Union[str, int, float]] = Field(default_factory=dict)
    at: float = 0.0
    duration: float = 3.0
    position: Literal["top-left", "top-right", "bottom-left", "bottom-right", "center",
                      "top-center", "bottom-center"] = "top-right"
    width: int = 520
    height: int = 220
    margin: int = 40


class Segment(_M):
    title: str = Field(description="Big slide-in banner during the reveal, e.g. 'Belt Sander Adapter'.")
    label: Optional[str] = Field(None, description="Lower-third text; defaults to title.")
    clips: list[str] = Field(description="Clip ids (keys of `clips`) used as b-roll, first = hero.")
    vo: str = Field(description="Voiceover script for this segment.")
    verdict: Optional[str] = None
    reveal_ranges: Optional[list[Range]] = Field(
        None, description="Where the reveal shot may be picked from (first clip). Use to avoid "
                          "replaying footage already shown in the intro.")
    forced: list[ForcedTake] = Field(default_factory=list)
    sfx: list[SegmentSfx] = Field(default_factory=list)
    callouts: list[Callout] = Field(default_factory=list)
    overlays: list[OverlaySpec] = Field(default_factory=list)
    link: Optional[str] = Field(None, description="Affiliate/product link for the description.")
    price: Optional[str] = None
    chapter: Optional[str] = Field(None, description="Chapter title; defaults to label.")


class IntroShot(_M):
    clip: str
    range: Range = Field(description="Exact window to cut from. Never widened automatically.")
    role: Literal["hero", "cue", "music"] = Field(
        "cue", description="hero = opening hold; cue = cut on the VO sentence naming it; "
                           "music = cut to music under the subscribe beat.")
    length: Optional[float] = Field(None, description="Music shots: seconds on screen (default: split evenly).")


class IntroSpec(_M):
    enabled: bool = True
    vo: str = Field("", description="Hook VO. Sentence 1 = hero, then one sentence per cue shot "
                                    "(plus an optional promise sentence).")
    shots: list[IntroShot] = Field(default_factory=list)
    hero_hold: float = 4.5
    vo_deadline: float = Field(15.0, description="Intro VO must finish before this.")
    cue_lead: float = Field(0.35, description="Cut this many seconds before the naming sentence.")
    subscribe: Optional[SubscribeSpec] = Field(default_factory=SubscribeSpec)
    length: Optional[float] = Field(None, description="Total intro length; default = subscribe end "
                                                       "(or VO end + 1s without subscribe).")
    min_length: Optional[float] = None
    max_length: Optional[float] = None


class OutroSpec(_M):
    enabled: bool = True
    vo: str = ""
    headline: str = "THANKS FOR WATCHING"
    subline: str = "Links in the description"
    background_clip: Optional[str] = None
    dim: float = 0.18


class MidSubscribeSpec(SubscribeSpec):
    source: str = "builtin"
    at: float = 180.0
    duration: Optional[float] = 6.0
    position: Literal["bottom-center", "bottom-right", "bottom-left", "top-right", "center"] = "bottom-right"
    margin_y: int = 70
    audio_volume: float = 0.0


class OutputSpec(_M):
    path: str = "output/video.mp4"
    format: Literal["landscape", "vertical", "square"] = "landscape"
    fps: int = 30
    crf: int = 20
    preset: str = "veryfast"
    lufs: float = -14.0
    target_min: Optional[float] = Field(None, description="Warn if runtime is below this (seconds).")
    target_max: Optional[float] = None

    @property
    def size(self) -> tuple[int, int]:
        return {"landscape": (1920, 1080), "vertical": (1080, 1920), "square": (1080, 1080)}[self.format]


class ShortSpec(_M):
    name: str
    segment: Optional[int] = Field(None, description="1-based segment to cut from the rendered video.")
    start: Optional[float] = Field(None, description="Or an explicit start in the rendered video.")
    duration: Optional[float] = Field(None, description="Seconds (max 60 recommended).")
    hook: str = ""
    cta: str = "Full review on the channel"
    captions: bool = Field(True, description="Burn word-by-word captions from the VO timing.")


class ThumbImage(_M):
    clip: Optional[str] = None
    at: Optional[float] = Field(None, description="Frame time; omit = most action-packed frame.")
    file: Optional[str] = None
    badge: Optional[str] = None
    badge_color: str = "#E74C3C"


class ThumbnailSpec(_M):
    enabled: bool = True
    path: str = "output/thumbnail.jpg"
    headline: str = ""
    subline: str = ""
    images: list[ThumbImage] = Field(default_factory=list,
                                     description="Omit = first frames of the first 3 segments.")
    cutout: bool = Field(False, description="Remove backgrounds (needs `pip install videopip[cutout]`).")


class MetadataSpec(_M):
    title: str = ""
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    disclosure: str = "Some links above are affiliate links; I may earn a commission at no cost to you."
    path: str = "output/metadata.txt"


class Project(_M):
    version: int = SPEC_VERSION
    name: str = "untitled"
    clips_dir: str = "clips"
    work_dir: str = ".videopip-work"
    clips: dict[str, ClipSpec]
    voice: VoiceSpec = Field(default_factory=VoiceSpec)
    music: MusicSpec = Field(default_factory=MusicSpec)
    sfx: SfxSpec = Field(default_factory=SfxSpec)
    brand: BrandSpec = Field(default_factory=BrandSpec)
    style: StyleSpec = Field(default_factory=StyleSpec)
    intro: IntroSpec = Field(default_factory=IntroSpec)
    segments: list[Segment]
    outro: OutroSpec = Field(default_factory=OutroSpec)
    subscribe_mid: Optional[MidSubscribeSpec] = None
    output: OutputSpec = Field(default_factory=OutputSpec)
    shorts: list[ShortSpec] = Field(default_factory=list)
    thumbnail: ThumbnailSpec = Field(default_factory=ThumbnailSpec)
    metadata: MetadataSpec = Field(default_factory=MetadataSpec)

    # resolved at load time; not part of the YAML
    _base_dir: Path = PrivateAttr(default_factory=lambda: Path("."))

    @property
    def base_dir(self) -> Path:
        return self._base_dir

    @field_validator("clips", mode="before")
    @classmethod
    def _clip_shorthand(cls, v):
        # allow `clips: {c1: "1.mp4"}` as shorthand
        if isinstance(v, dict):
            return {k: ({"file": x} if isinstance(x, str) else x) for k, x in v.items()}
        return v

    @model_validator(mode="after")
    def _refs(self):
        ids = set(self.clips)
        errs = []
        for i, s in enumerate(self.segments, 1):
            for c in s.clips:
                if c not in ids:
                    errs.append(f"segments[{i}].clips: unknown clip id '{c}'")
            for f in s.forced:
                if f.clip not in s.clips:
                    errs.append(f"segments[{i}].forced: clip '{f.clip}' is not in this segment's clips")
            if not s.clips:
                errs.append(f"segments[{i}]: needs at least one clip")
        for j, sh in enumerate(self.intro.shots):
            if sh.clip not in ids:
                errs.append(f"intro.shots[{j}]: unknown clip id '{sh.clip}'")
            if sh.range[1] <= sh.range[0]:
                errs.append(f"intro.shots[{j}]: range end must be after start")
        if self.outro.background_clip and self.outro.background_clip not in ids:
            errs.append(f"outro.background_clip: unknown clip id '{self.outro.background_clip}'")
        for c, spec in self.clips.items():
            for a, b in spec.safe or []:
                if b <= a:
                    errs.append(f"clips.{c}.safe: range [{a}, {b}] is empty")
        if self.intro.enabled and self.intro.shots:
            if self.intro.shots[0].role != "hero":
                errs.append("intro.shots[0] must have role: hero")
        if errs:
            raise ValueError("; ".join(errs))
        return self

    # ------------------------------------------------------------------ paths
    def path(self, p: str | None) -> Optional[Path]:
        if not p:
            return None
        if p.startswith("builtin:"):
            return Path(p)
        q = Path(os.path.expandvars(os.path.expanduser(p)))
        return q if q.is_absolute() else (self.base_dir / q)

    def clip_path(self, clip_id: str) -> Path:
        f = self.clips[clip_id].file
        q = Path(os.path.expanduser(f))
        if q.is_absolute():
            return q
        return self.path(self.clips_dir) / q

    @property
    def work(self) -> Path:
        return self.path(self.work_dir)


def load(path: str | os.PathLike) -> Project:
    path = Path(path).resolve()
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    proj = Project.model_validate(data)
    proj._base_dir = path.parent
    if proj.voice.lexicon_file:
        lp = proj.path(proj.voice.lexicon_file)
        with open(lp, encoding="utf-8") as f:
            extra = yaml.safe_load(f) or {}
        proj.voice.lexicon = {**extra, **proj.voice.lexicon}
    return proj


def json_schema() -> dict:
    s = Project.model_json_schema()
    s["title"] = "VideoPip project spec"
    s["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    return s
