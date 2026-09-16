"""End-to-end renders with the offline `silent` voice (no network needed)."""
import json

import yaml

from videopip import analysis, config, ff, preflight
from videopip.publish import make_metadata, make_thumbnail
from videopip.render import Renderer
from videopip.shorts import make_short
from videopip.verify import verify

VO = ("This is a test product with a pretty long description so the segment has some length to it. "
      "It does a useful thing. Con? It is only a test. Worth it.")


def _spec(tmp, **over):
    spec = {
        "clips": {f"c{i}": {"file": f"{i}.mp4", "safe": [[2.2, 13.8]], "use_audio": True, "audio_volume": 0.3}
                  for i in range(1, 4)},
        "voice": {"engine": "silent"},
        "sfx": {"whoosh": "builtin:whoosh", "cold_open": "builtin:impact", "cold_open_in": 0.0},
        "intro": {
            "vo": "Hero line here. Cue line one. Cue line two. The promise.",
            "shots": [{"clip": "c1", "range": [2.5, 13.5], "role": "hero"},
                      {"clip": "c2", "range": [3, 9], "role": "cue"},
                      {"clip": "c3", "range": [3, 9], "role": "cue"},
                      {"clip": "c2", "range": [9, 13], "role": "music"}],
            "subscribe": {"source": "builtin", "at": 9.0, "duration": 4.0},
            "vo_deadline": 12.0,
        },
        "segments": [
            {"title": "Product One", "clips": ["c1", "c2"], "vo": VO, "link": "https://example.com/1",
             "reveal_ranges": [[3, 8]],
             "forced": [{"clip": "c2", "start": 4.0, "duration": 3.0}],
             "sfx": [{"file": "builtin:ding", "volume": 0.3, "at": 1.0, "length": 1.0, "file_in": 0.0}],
             "overlays": [{"template": "price_tag", "data": {"label": "Around", "price": "$29"},
                           "at": 3.0, "duration": 2.0}]},
            {"title": "Product Two", "clips": ["c2"], "vo": VO, "link": "https://example.com/2"},
            {"title": "Product Three", "clips": ["c3"], "vo": VO,
             "overlays": [{"template": "rating", "data": {"stars": 4.5}, "at": 2.0, "duration": 2.0},
                          {"template": "badge", "data": {"text": "BEST VALUE"}, "at": 4.0, "duration": 2.0}]},
        ],
        "outro": {"vo": "Thanks for watching this test."},
        "subscribe_mid": {"source": "builtin", "at": 30.0, "duration": 3.0},
        "style": {"show_verdict": True, "numbering": "countdown"},
        "output": {"path": "output/video.mp4", "format": "landscape", "preset": "ultrafast"},
        "shorts": [{"name": "p1", "segment": 1, "hook": "LOOK AT THIS"}],
        "thumbnail": {"headline": "TEST VIDEO", "subline": "2026"},
        "metadata": {"title": "Test", "tags": ["a", "b"]},
    }
    spec.update(over)
    p = tmp / "project.yaml"
    p.write_text(yaml.safe_dump(spec), encoding="utf-8")
    return config.load(p)


def test_analyze_finds_cards(clips_dir):
    runs = analysis.static_runs(clips_dir / "1.mp4")
    assert runs and runs[0][0] <= 0.3 and 1.6 <= runs[0][1] <= 2.4
    safe = analysis.suggest_safe(clips_dir / "1.mp4")
    assert safe[0][0] >= 1.8 and safe[-1][1] <= 14.4


def test_full_landscape_render(project_dir):
    proj = _spec(project_dir)
    rep = preflight.run(proj)
    assert rep.ok, rep.to_dict()
    man = Renderer(proj).render()
    out = project_dir / "output" / "video.mp4"
    assert out.exists()
    assert ff.video_size(out) == (1920, 1080)
    kinds = [p["kind"] for p in man["pieces"]]
    assert kinds == ["intro", "segment", "segment", "segment", "outro"]
    assert abs(man["duration"] - rep.estimate["runtime"]) < 3.0
    assert man["lufs_after"] is None or abs(man["lufs_after"] + 14) < 1.5
    v = verify(out)
    assert not [i for i in v["issues"] if "frozen" in i], v

    short = make_short(proj, proj.shorts[0])
    assert ff.video_size(short) == (1080, 1920)
    assert make_thumbnail(proj).exists()
    meta = make_metadata(proj).read_text(encoding="utf-8")
    assert "0:00 Intro" in meta and "https://example.com/1" in meta

    # second render reuses every piece
    man2 = Renderer(proj).render()
    assert abs(man2["duration"] - man["duration"]) < 0.05


def test_vertical_render(project_dir):
    proj = _spec(project_dir, intro={"enabled": False}, outro={"enabled": False}, subscribe_mid=None,
                 output={"path": "output/v.mp4", "format": "vertical", "preset": "ultrafast"}, shorts=[])
    proj.segments = proj.segments[:1]
    man = Renderer(proj).render()
    assert ff.video_size(project_dir / "output" / "v.mp4") == (1080, 1920)
    assert len(man["pieces"]) == 1


def test_preflight_catches_bad_ranges(project_dir):
    proj = _spec(project_dir)
    proj.clips["c1"].safe = [(2.0, 99.0)]
    rep = preflight.run(proj, synth=False)
    assert not rep.ok and "runs past the clip end" in json.dumps(rep.to_dict())

    proj = _spec(project_dir)
    proj.segments[0].forced[0].start = 12.0
    rep = preflight.run(proj, synth=False)
    assert not rep.ok and "forced take" in json.dumps(rep.to_dict())
