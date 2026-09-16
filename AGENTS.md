# Notes for AI coding agents working on this repo

- **Making a video for a user?** Don't edit this repo. Follow `src/videopip/guide.md` (also
  available as `videopip guide`) and write a `project.yaml` in the user's own folder.
- **Changing VideoPip itself?** Read `CONTRIBUTING.md` first. Key invariants:
  - every cut is pre-extracted with its own `-ss` read (no shared split+trim graphs)
  - user-given time windows are clamped, never widened
  - drawtext text goes through `ff.TextFiles`; fonts via `graphics.local_font`
  - new spec options need a `description` (it feeds the schema, docs and AI tools)
- Run `pytest -q` (needs ffmpeg, no network) and `python scripts/sync_docs.py` before finishing.
- `SKILL.md`, `PROMPT.md` and `docs/SPEC.md` are generated. Edit `guide.md` / `config.py` instead.
