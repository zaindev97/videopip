"""Text-to-speech with pluggable engines, pronunciation fixes and a render cache.

Every engine returns a WAV plus word/sentence timings. Results are cached by
(engine, voice, rate, text), so re-running a build reuses the exact same audio:
edge-tts renders the same text +-0.4s differently run to run, and a cache is the
only way to make timing decisions stick.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import ff
from .config import VoiceSpec
from .log import info

WORDS_PER_SEC = 2.7  # used by the silent engine and for estimates


@dataclass
class Speech:
    wav: Path
    duration: float
    words: list[tuple[float, float, str]] = field(default_factory=list)      # (start, dur, text)
    sentences: list[tuple[float, float]] = field(default_factory=list)       # (start, dur)


def apply_lexicon(text: str, lexicon: dict[str, str]) -> str:
    for word in sorted(lexicon, key=len, reverse=True):
        text = re.sub(rf"(?<![\w-]){re.escape(word)}(?![\w-])", lexicon[word], text)
    return text


def split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+(?=[\"'“(]?[A-Z0-9])", text.strip())
    return [p for p in (x.strip() for x in parts) if p]


def _norm_word(w: str) -> str:
    return re.sub(r"[^\w]", "", w.lower())


def sentences_from_words(text: str, words, total: float) -> list[tuple[float, float]]:
    """Align sentence starts onto word timings; fall back to character-proportional."""
    sents = split_sentences(text)
    if not sents:
        return []
    starts: list[float] = []
    wi = 0
    for s in sents:
        toks = [t for t in (_norm_word(x) for x in s.split()) if t]
        if not toks or wi >= len(words):
            break
        first = toks[0]
        found = None
        for k in range(wi, min(len(words), wi + 60)):
            if _norm_word(words[k][2]).startswith(first[:4]) or first.startswith(_norm_word(words[k][2])[:4] or "\0"):
                found = k
                break
        if found is None:
            break
        starts.append(words[found][0])
        wi = found + max(1, len(toks) - 2)
    if len(starts) != len(sents):
        lens = [len(s) for s in sents]
        tot, acc, starts = sum(lens), 0, []
        for n in lens:
            starts.append(round(total * acc / tot, 3))
            acc += n
    out = []
    for i, st in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else total
        out.append((round(st, 3), round(max(0.0, end - st), 3)))
    return out


# ------------------------------------------------------------------ engines
def _edge(text: str, spec: VoiceSpec, mp3: Path):
    import edge_tts

    async def go():
        kw = {"rate": spec.rate}
        try:
            comm = edge_tts.Communicate(text, spec.voice, boundary="WordBoundary", **kw)
        except TypeError:  # edge-tts < 7
            comm = edge_tts.Communicate(text, spec.voice, **kw)
        audio, words = bytearray(), []
        async for ch in comm.stream():
            if ch["type"] == "audio":
                audio += ch["data"]
            elif ch["type"] == "WordBoundary":
                words.append((round(ch["offset"] / 1e7, 3), round(ch["duration"] / 1e7, 3), ch.get("text", "")))
        return bytes(audio), words

    last = None
    for attempt in range(5):
        try:
            audio, words = asyncio.run(go())
            if len(audio) > 1000:
                mp3.write_bytes(audio)
                return words
        except Exception as e:  # network hiccups are common
            last = e
        time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"edge-tts failed after 5 attempts: {last}")


def _openai(text: str, spec: VoiceSpec, mp3: Path):
    from openai import OpenAI
    key = os.environ.get(spec.api_key_env or "OPENAI_API_KEY")
    client = OpenAI(api_key=key) if key else OpenAI()
    voice = spec.voice if "Neural" not in spec.voice else "onyx"
    with client.audio.speech.with_streaming_response.create(
            model=spec.model or "gpt-4o-mini-tts", voice=voice, input=text) as r:
        r.stream_to_file(str(mp3))
    return []


def _elevenlabs(text: str, spec: VoiceSpec, mp3: Path):
    import requests
    key = os.environ.get(spec.api_key_env or "ELEVENLABS_API_KEY")
    if not key:
        raise RuntimeError("Set ELEVENLABS_API_KEY (or voice.api_key_env).")
    r = requests.post(f"https://api.elevenlabs.io/v1/text-to-speech/{spec.voice}",
                      headers={"xi-api-key": key, "accept": "audio/mpeg"},
                      json={"text": text, "model_id": spec.model or "eleven_multilingual_v2"}, timeout=180)
    r.raise_for_status()
    mp3.write_bytes(r.content)
    return []


def _piper(text: str, spec: VoiceSpec, wav: Path):
    import subprocess
    import sys
    model = spec.model or spec.voice
    if not model.endswith(".onnx"):
        cand = Path.home() / ".videopip" / "voices" / f"{model}.onnx"
        model = str(cand)
    r = subprocess.run([sys.executable, "-m", "piper", "-m", model, "-f", str(wav)],
                       input=text, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"piper failed: {r.stderr[-400:]}")
    return []


def _silent(text: str, spec: VoiceSpec, wav: Path):
    toks = text.split()
    words, t = [], 0.0
    for w in toks:
        d = max(0.12, len(w) * 0.055)
        words.append((round(t, 3), round(d, 3), w))
        t += d + (0.35 if w[-1:] in ".!?" else 0.06)
    total = max(0.5, round(t, 3))
    ff.run(["-y", "-f", "lavfi", "-i", f"anullsrc=r=48000:cl=stereo", "-t", total, str(wav)])
    return words


ENGINES = {"edge": _edge, "openai": _openai, "elevenlabs": _elevenlabs, "piper": _piper, "silent": _silent}


def cache_dir() -> Path:
    d = Path(os.environ.get("VIDEOPIP_CACHE", Path.home() / ".videopip" / "tts-cache"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def synthesize(text: str, spec: VoiceSpec, use_cache: bool = True) -> Speech:
    spoken = apply_lexicon(text, spec.lexicon)
    key = hashlib.sha1(json.dumps([spec.engine, spec.voice, spec.rate, spec.model, spoken]).encode()).hexdigest()[:20]
    cd = cache_dir()
    wav, meta = cd / f"{key}.wav", cd / f"{key}.json"
    if use_cache and wav.exists() and meta.exists():
        m = json.loads(meta.read_text(encoding="utf-8"))
        return Speech(wav, m["duration"], [tuple(w) for w in m["words"]], [tuple(s) for s in m["sentences"]])

    tmp = cd / f"{key}.raw"
    if spec.engine in ("piper", "silent"):
        raw = cd / f"{key}.src.wav"
        words = ENGINES[spec.engine](spoken, spec, raw)
    else:
        raw = tmp.with_suffix(".mp3")
        words = ENGINES[spec.engine](spoken, spec, raw)
    # normalise to 48k stereo wav once
    ff.run(["-y", "-i", raw, "-af", "aresample=48000,aformat=channel_layouts=stereo",
            "-c:a", "pcm_s16le", wav], desc="tts wav")
    raw.unlink(missing_ok=True)
    dur = ff.duration(wav)
    if not words:
        # engines without timings: spread words proportionally to their length
        toks = spoken.split()
        tot = sum(len(t) + 1 for t in toks) or 1
        acc = 0
        for t in toks:
            words.append((round(dur * acc / tot, 3), round(dur * len(t) / tot, 3), t))
            acc += len(t) + 1
    sents = sentences_from_words(spoken, words, dur)
    meta.write_text(json.dumps({"duration": dur, "words": words, "sentences": sents, "text": spoken}),
                    encoding="utf-8")
    info(f"tts [{spec.engine}] {len(spoken.split())} words -> {dur:.2f}s")
    return Speech(wav, dur, words, sents)


def estimate(text: str) -> float:
    return round(len(text.split()) / WORDS_PER_SEC, 2)


def list_edge_voices(prefix: str = "en-") -> list[str]:
    import edge_tts
    voices = asyncio.run(edge_tts.list_voices())
    return sorted(v["ShortName"] for v in voices if v["ShortName"].startswith(prefix))


def clear_cache() -> int:
    d = cache_dir()
    n = len(list(d.iterdir()))
    shutil.rmtree(d, ignore_errors=True)
    return n
