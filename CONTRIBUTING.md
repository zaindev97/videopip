# Contributing

Thanks for helping! VideoPip is small on purpose: a validated spec in, a deterministic render out.

## Dev setup

```bash
git clone https://github.com/zaindev97/videopip && cd videopip
python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e ".[dev,mcp,audio,motion]"
videopip setup
pytest -q
```

Tests render real (tiny) videos with synthetic clips and the offline `silent` voice. They need
ffmpeg but no network.

## Layout

| Path | What |
|---|---|
| `src/videopip/config.py` | the spec (pydantic). Every new option starts here, with a `description` |
| `src/videopip/planner.py` | pure timing logic (chunk walking, montage slots). Unit-test here |
| `src/videopip/render.py` | ffmpeg graph building: intro, segments, outro, assembly, mix, master |
| `src/videopip/preflight.py` | checks that run before rendering. Add one for every new footgun |
| `src/videopip/motion.py` | builtin animated overlays + HTML template capture |
| `src/videopip/graphics.py` | banners, subscribe animation, thumbnails |
| `src/videopip/tts.py` | voice engines + cache |
| `src/videopip/guide.md` | the instructions AI assistants follow; source of SKILL.md and PROMPT.md |
| `src/videopip/mcp_server.py` | MCP tools |

## Rules of the road

- **Never use a shared `split`+`trim` graph for cuts.** Pre-extract each cut with its own `-ss`
  (it deadlocks or freezes on backward seeks).
- **Never widen user-given time windows.** Clamp and report instead.
- Text goes into `drawtext` via `textfile=` (see `ff.TextFiles`), and fonts are copied next to the
  job. No drive-letter colons in filtergraphs.
- After editing `guide.md` or `config.py`, run `python scripts/sync_docs.py` (CI checks it).
- Only ship assets you can redistribute. Built-in sounds are synthesized in `sfx.py`.

## Ideas for contributions

- New overlay templates (builtin in `motion.py` or example HTML in `examples/overlays/`)
- New project templates in `src/videopip/templates/`
- More TTS engines (Azure, Google, Coqui/XTTS)
- Caption styles (karaoke highlight, emoji)
- Auto-reframe (face/object tracking) for vertical crops
- Beat-synced cuts from music onsets
