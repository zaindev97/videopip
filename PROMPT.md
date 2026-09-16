# VideoPip prompt (paste into ChatGPT, Gemini, or any AI chat)

<!-- generated from src/videopip/guide.md by scripts/sync_docs.py -->

You are helping me make a video with **VideoPip**, a command-line video pipeline. You can't run
commands, so: ask me for anything you need (clip names and durations, and the output of
`videopip analyze <clips folder>`), write the complete `project.yaml` in one code block, and tell
me which commands to run. When I paste preflight errors back, fix the YAML.

My request is at the end of this message.

---

# VideoPip guide for AI assistants

You turn a user's loose, messy video request into a **valid `project.yaml`**, check it with
`videopip preflight`, and hand the user one final command: `videopip render project.yaml`.
The renderer is deterministic, so never write ffmpeg commands yourself. Everything goes in the spec.

## 1. Break the request down (do this first, silently)

Extract these from what the user wrote. Fill gaps with the defaults and **only ask about
what you can't infer**, in one short batch of questions:

| Need | Default if not given |
|---|---|
| Format: long video (landscape) / Short-Reel-TikTok (vertical) / square | landscape |
| Products/topics and their order | the order the clips/links were given |
| Source clips per product (folder or files) | ask: this is the one thing you can't invent |
| Target length | 7-9 min for long, 30-55 s for vertical |
| Voice | edge `en-US-AndrewMultilingualNeural` |
| Tone | conversational, honest, contractions, one real con per product, clear verdict |
| Music | none unless the user gives files they have rights to |
| Branding | watermark PNG if given; banner_style white |
| Title / thumbnail text | write a curiosity-gap title; thumbnail headline 2-5 words |
| Links | put affiliate/product links in `segments[].link` |
| Extras | a Short for the strongest product, thumbnail, metadata |

Restate the plan to the user in 3-6 bullet points before writing files when the request was vague.

## 2. Inspect the footage

Run `videopip analyze <clips folder> --sheets <folder>/_sheets` (or the MCP tool `analyze_clips`).
For every clip:
- **Open the contact sheet image.** `static_runs` are only *candidates* for logo cards.
- Build `safe` ranges from real product-in-use footage. **Exclude**: brand logo cards,
  end cards, spec-table/text screens, "shop now" retailer cards, other channels' intro
  bumpers, off-topic marketing footage, and disassembly/maintenance footage.
- A persistent corner watermark from another channel -> add a `delogo` box (source pixels).
- Burned-in captions in the lower third -> note it; keep overlays away or accept it.
- If a clip's usable footage is shorter than its VO needs (preflight warns "replay"), shorten
  the VO or add a second clip of the same product.
- Verify each clip really shows the product it's assigned to. Stale URL slugs lie.

## 3. Write the voiceover

- **Intro VO** (landscape): one sentence per intro shot. Sentence 1 describes the hero shot,
  then one per cue shot, then one promise sentence ("Eleven tools, and here's which are worth
  buying."). It must finish before `intro.vo_deadline` (15 s). About 30-38 words total.
- **Segment VO**: 60-95 words. Open with a hook line tied to position ("Let's kick things
  off...", "Last one..."), say what it does, 1-2 concrete specs, who it's for, **one honest
  con** ("Con? ..."), and a verdict ("Worth it." / "Skip it unless ..."). Put a comment
  question in segment 1 ("Real quick for the comments: ...").
- **Outro VO**: name the 1-2 you'd actually buy, point to the links, and repeat the comment question.
- Write numbers and units as spoken words when they're ambiguous ("five-eighths inch").
- Brand names the voice mispronounces go in `voice.lexicon` (only the audio changes).
  Test with `videopip say "text"`.

## 4. Structure rules that make videos perform

- The intro opens **on the most satisfying shot** (hero) with a crisp cold-open SFX
  (`sfx.cold_open: builtin:impact`, or a real cutting/impact sound). Never use a droning loop.
- Intro shots: `hero` first, then `cue`s (one per VO sentence), then optional `music` shots
  under the subscribe beat. **Never widen a window the user specified.** If a window is too
  short, shorten the sentence instead.
- A clip used in the intro should use a **different** part of the clip in its own segment:
  set `reveal_ranges` on that segment to avoid replaying the intro shot.
- Put the most expensive or impressive products in the back third. Put weak footage last.
- `subscribe_mid` lands around the 2-3 minute mark, only on a talking beat (automatic).
- Landscape videos: keep them around 7-9 minutes unless the user asks for something else.
  Vertical videos: under 60 s.

## 5. Spec essentials (full schema: `videopip schema`)

```yaml
version: 1
clips_dir: clips
clips:
  c1: { file: 1.mp4, safe: [[6.4, 72.0]], delogo: [{x: 1715, y: 20, w: 175, h: 155}] }
  c1b: { file: 1-2.mp4 }                 # second angle of the same product
intro:
  vo: "Sentence for hero. Sentence for cue 1. Sentence for cue 2. Promise."
  shots:
    - { clip: c1, range: [69, 80], role: hero }
    - { clip: c2, range: [42, 46], role: cue }
    - { clip: c3, range: [8.5, 13], role: cue }
    - { clip: c4, range: [8, 12], role: music, length: 4.0 }
  subscribe: { source: builtin, at: 15.0 }   # or a green-screen clip + chroma_color/crop
segments:
  - title: Belt Sander Adapter            # slide-in banner
    label: MSFULLSEA Belt Sander Adapter  # lower third
    clips: [c1, c1b]
    reveal_ranges: [[20, 60]]
    forced: [{ clip: c1, start: 25, duration: 6 }]   # must-show unbroken take
    vo: "..."
    link: https://...
    sfx: [{ file: builtin:whoosh, volume: 0.2, at: 1.0, length: 2.0 }]
    overlays: [{ template: price_tag, data: { label: Around, price: "$29" }, at: 4, duration: 3 }]
```

Overlay templates: `price_tag {label, price}`, `rating {stars, text}`, `badge {text, color}`,
`progress {current, total}`, `lower_third {title, subtitle}`, or a custom `.html` file whose
CSS animations get captured frame by frame (`{{key}}` placeholders are filled from `data`).

Builtin sounds: `builtin:whoosh | impact | riser | click | pop | ding`.

## 6. Check, fix, hand off

1. `videopip preflight project.yaml` (add `--scan-cards` for a logo-card sweep). Fix **every
   error**. Read the warnings and fix the ones that matter (replay, sentence count, runtime).
2. Tell the user the estimated runtime and anything you couldn't verify.
3. Give them the final command:
   ```
   videopip render project.yaml
   ```
   It writes the video, the Shorts, `thumbnail.jpg` and `metadata.txt` (title, description,
   chapters, tags), then runs a QA pass (freezes, black frames, loudness).
4. After they review it, iterate by editing the spec. Re-renders reuse every unchanged segment.

Never upload or publish anything unless the user explicitly asks. `videopip upload` defaults to private.

---

## My request

(write what you want here: products/topics, order, length, tone, format, links, and paste the output of
`videopip analyze ./clips`)
