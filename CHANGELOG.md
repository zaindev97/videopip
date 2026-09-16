# Changelog

## 0.1.0 (unreleased)

First public version.

- YAML project spec with JSON schema, strict validation and helpful errors
- Voice: edge-tts, OpenAI, ElevenLabs, Piper, silent; pronunciation lexicon; render cache
- Intro montage cut on VO sentence boundaries, windows never widened, cold-open SFX
- Product segments: action-picked reveal, slide-in banner, numbered lower third, multi-clip b-roll,
  forced takes, verdict banner, callouts
- Footage safety: safe ranges, static-card detection, contact sheets, delogo, pre-crop
- Motion graphics: builtin price tag / rating / badge / progress / lower third; custom HTML templates
- Builtin animated subscribe button; green-screen subscribe clips; mid-video reminder on a talking beat
- Audio: intro + body music, ducking, reveal stingers, whooshes, per-segment SFX, LUFS mastering
- Landscape / vertical / square output; Shorts with word-by-word captions
- Thumbnail, description, chapters, tags; optional YouTube upload (private by default)
- Preflight and post-render QA (freezes, black frames, loudness)
- CLI, MCP server, Claude Code plugin + skill, prompt for other chatbots, `videopip demo`
