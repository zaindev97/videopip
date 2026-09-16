# VideoPip

[![CI](https://github.com/zaindev97/videopip/actions/workflows/ci.yml/badge.svg)](https://github.com/zaindev97/videopip/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/videopip.svg)](https://pypi.org/project/videopip/)
[![Python](https://img.shields.io/pypi/pyversions/videopip.svg)](https://pypi.org/project/videopip/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![MCP server](https://img.shields.io/badge/MCP-server-blueviolet)](docs/AI_TOOLS.md)
[![Claude Code plugin](https://img.shields.io/badge/Claude%20Code-plugin-orange)](docs/AI_TOOLS.md#claude-code)

**Describe a video in plain words. Your AI assistant writes the plan. One command renders it.**

VideoPip is an open-source, AI-driven video pipeline for product videos, countdowns, reviews,
Shorts, Reels and TikToks. Your AI tool (Claude, Cursor, ChatGPT, anything) turns a messy
request into a validated `project.yaml`. VideoPip then does the editing deterministically:
voiceover, intro montage cut to the words, b-roll, motion graphics, subscribe animation,
music with ducking, whooshes, SFX, loudness mastering, vertical Shorts with captions, a
thumbnail, and chapters/description.

```bash
pipx install "videopip[all]"
videopip setup
videopip demo            # renders a sample video from generated footage, no clips needed
```

---

## Why a spec instead of letting the AI edit directly?

AI tools are good at understanding requests and bad at writing correct ffmpeg filtergraphs.
VideoPip splits the job:

```
"make a video of these 8 gadgets, fun tone,       ┌──────────────────────┐
 the drill one first, ~8 min, link in desc"  ───► │ AI assistant         │ breaks the request down,
                                                  │ + VideoPip guide     │ asks only what's missing,
                                                  └──────────┬───────────┘ inspects the clips
                                                             ▼
                                                     project.yaml  (validated by JSON schema)
                                                             ▼
                                        videopip preflight   (files, ranges, timing, runtime)
                                                             ▼
                                        videopip render      (deterministic engine)
                                                             ▼
                        video.mp4 + short_*.mp4 + thumbnail.jpg + metadata.txt + QA report
```

## Features

| Area | What you get |
|---|---|
| **Voice** | Free Edge neural voices, OpenAI, ElevenLabs or offline Piper. Pronunciation lexicon. Cached, so timings never drift between renders |
| **Intro montage** | Hero shot + cuts that land on the sentence naming each product. Windows are never silently widened. Cold-open SFX |
| **Segments** | Most-action reveal shot (motion + audio analysis), slide-in title banner, numbered lower third, b-roll walked across multiple clips, must-show "forced" takes, verdict banner, callouts |
| **Footage safety** | Per-clip `safe` ranges, logo/text-card detection, contact sheets, `delogo` for corner watermarks, pre-crop |
| **Motion graphics** | Built-in animated price tag, star rating, badge, progress bar, lower third, or your own HTML/CSS template rendered frame by frame |
| **Subscribe** | Built-in animated button + cursor + bell (no green-screen needed), or your own green-screen clip with chroma key. Intro beat + a mid-video reminder placed on a talking beat automatically |
| **Audio** | Intro music + body bed, sidechain ducking under the voice, reveal stingers, whoosh on every transition, per-segment SFX, -14 LUFS mastering |
| **Formats** | Landscape 16:9, vertical 9:16, square 1:1 from the same spec |
| **Shorts** | Cut any segment to 9:16 with a blurred background, hook text, CTA and word-by-word captions |
| **Publishing** | Thumbnail generator, title/description/chapters/tags, optional YouTube upload with your own OAuth (defaults to private) |
| **QA** | Preflight before rendering; freeze, black-frame and loudness checks after |
| **AI integration** | Claude Code plugin + skill, MCP server (Claude Desktop, Cursor, Windsurf...), JSON schema, prompt for any chatbot |

## Install

Requires **Python 3.10+**. ffmpeg is downloaded automatically if you don't have it.

```bash
# recommended: isolated install
pipx install "videopip[all]"

# or plain pip
pip install "videopip[all]"

# then download ffmpeg (if missing), fonts, and build the built-in assets
videopip setup          # add --full for Playwright/Chromium (custom HTML overlays)
videopip doctor         # check everything
```

One-line installers for people without Python experience are in [`install.ps1`](install.ps1)
(Windows) and [`install.sh`](install.sh) (macOS/Linux).

Minimal install (no extras): `pip install videopip`. Extras: `ffmpeg`, `audio` (librosa),
`motion` (Playwright), `mcp`, `openai`, `elevenlabs`, `piper`, `cutout`, `youtube`.

## Use it with your AI tool

### Claude Code

```bash
claude plugin marketplace add zaindev97/videopip
claude plugin install videopip@videopip
```

Then just ask: *"Make an 8-minute video from the clips in ./clips: 10 garage gadgets, the
drill first, fun but honest tone, links are in links.txt."* The `videopip` skill takes it
from there and gives you the final `videopip render` command.

### Claude Desktop, Cursor, Windsurf, any MCP client

Add the server to the client's MCP config:

```json
{
  "mcpServers": {
    "videopip": { "command": "videopip-mcp" }
  }
}
```

(or `"command": "uvx", "args": ["--from", "videopip[mcp]", "videopip-mcp"]` without installing).
Tools exposed: `get_guide`, `get_schema`, `get_template`, `analyze_clips`, `init_project`,
`write_project`, `preflight`, `render_start`, `render_status`, `verify_video`, `make_shorts`,
`get_metadata`, `audition_voice`, `list_assets`.

### ChatGPT, Gemini, anything else

Paste [`PROMPT.md`](PROMPT.md) into the chat together with your request, save the YAML it
writes as `project.yaml`, and run `videopip preflight` then `videopip render`.

## Try it in 2 minutes

```bash
videopip demo my-demo            # add --offline to skip the online voice
```

This creates `my-demo/project.yaml` plus generated footage, then renders `output/demo.mp4`,
a Short, a thumbnail and `metadata.txt`. Open the YAML to see how the result maps to the spec.

## Manual quick start

```bash
videopip init my-video --clips ./my-clips     # starter spec with safe-range suggestions
videopip analyze ./my-clips --sheets ./sheets  # look at the contact sheets!
# edit my-video/project.yaml: VO text, order, titles, links
videopip preflight my-video/project.yaml
videopip render my-video/project.yaml
```

Outputs land in `my-video/output/`. Re-rendering reuses every unchanged segment, so
editing one VO only rebuilds that segment.

## Commands

| Command | Purpose |
|---|---|
| `videopip setup` / `doctor` | install / check ffmpeg, filters, fonts, voices, extras |
| `videopip demo [dir] [--offline]` | sample project + render, no footage needed |
| `videopip guide` | the instructions AI assistants follow |
| `videopip init [dir] [--clips DIR] [-t vertical-short]` | new project |
| `videopip analyze CLIP_OR_DIR [--sheets DIR] [--json]` | logo-card candidates, safe ranges, action peaks |
| `videopip validate project.yaml` | schema check only |
| `videopip preflight project.yaml [--scan-cards] [--json]` | full pre-render check + runtime estimate |
| `videopip render project.yaml [--force]` | render everything, then run QA |
| `videopip short / thumbnail / metadata project.yaml` | rebuild one output |
| `videopip verify video.mp4` | QA any video |
| `videopip say "text"` / `voices` | audition a voice or pronunciation |
| `videopip schema` | JSON schema for editors and AI tools |
| `videopip assets` | built-in sounds, overlays, templates |
| `videopip upload video.mp4 --title ... --client-secret ...` | YouTube upload (private by default) |
| `videopip mcp` | run the MCP server |

## The spec

Full field reference: [`docs/SPEC.md`](docs/SPEC.md). AI tool setup: [`docs/AI_TOOLS.md`](docs/AI_TOOLS.md). See also the commented templates in
[`src/videopip/templates/`](src/videopip/templates). A minimal vertical short:

```yaml
version: 1
clips: { c1: { file: gadget.mp4, safe: [[1.0, 28.0]] } }
intro: { enabled: false }
outro: { enabled: false }
segments:
  - title: THIS GADGET IS GENIUS
    clips: [c1]
    vo: You need to see this. It fixes an annoying everyday problem in seconds. Link's in my bio.
output: { path: output/short.mp4, format: vertical }
```

## Legal notes (please read)

- **Use footage you have the rights to**: your own recordings, brand-supplied media, or
  licensed stock. VideoPip does not download videos from any website.
- **Music and sound effects**: VideoPip ships only sounds it synthesizes itself. Bring
  royalty-free tracks you are licensed to use.
- **Edge voices** use Microsoft's online read-aloud service through the community
  [`edge-tts`](https://github.com/rany2/edge-tts) library. It is not an official API; check
  whether its terms fit your use. For commercial work, consider OpenAI, ElevenLabs or Piper.
- **ffmpeg** is not bundled. `videopip setup` downloads a build for you through
  [`static-ffmpeg`](https://github.com/zackees/static_ffmpeg).
- Not affiliated with YouTube, Amazon, Anthropic, OpenAI or Microsoft. Add your own
  affiliate disclosure in `metadata.disclosure`.

## Contributing

Issues and PRs welcome. See [CONTRIBUTING.md](CONTRIBUTING.md). Good first contributions:
new overlay templates, new project templates, more TTS engines, caption styles.

## Support

- Questions and ideas: [GitHub Discussions](https://github.com/zaindev97/videopip/discussions)
- Bugs: [open an issue](https://github.com/zaindev97/videopip/issues) with the output of `videopip doctor`
- If VideoPip saves you time, a star on GitHub helps other people find it

## License

MIT © [Zain](https://github.com/zaindev97)
