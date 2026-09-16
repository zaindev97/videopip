# Connecting VideoPip to AI tools

VideoPip works with any AI assistant in one of three ways:

| Mode | Best for | What the AI can do |
|---|---|---|
| **MCP server** | Claude Desktop, Claude Code, Cursor, Windsurf, VS Code Copilot, Zed... | analyze clips, write and validate the spec, preflight, render, verify |
| **Claude Code plugin** | Claude Code | everything above, plus the `videopip` skill and a `/videopip:video` command |
| **Prompt file** | ChatGPT, Gemini, any chat without tools | writes the spec; you run the commands |

Install VideoPip first: `pipx install "videopip[all]"` then `videopip setup`.

## Claude Code

```bash
claude plugin marketplace add zaindev97/videopip
claude plugin install videopip@videopip
```

The plugin bundles the skill (`plugin/skills/videopip/SKILL.md`), the MCP server and a
`/videopip:video <brief>` command. Without the plugin you can add just the MCP server:

```bash
claude mcp add videopip -- videopip-mcp
```

## Claude Desktop

Settings -> Developer -> Edit Config, then add:

```json
{
  "mcpServers": {
    "videopip": { "command": "videopip-mcp" }
  }
}
```

If `videopip-mcp` isn't on the PATH Claude Desktop sees, use the full path
(`where videopip-mcp` on Windows, `which videopip-mcp` on macOS/Linux), or run it through uv
without installing anything:

```json
{ "mcpServers": { "videopip": { "command": "uvx", "args": ["--from", "videopip[mcp]", "videopip-mcp"] } } }
```

## Cursor / Windsurf / VS Code

Put the same `mcpServers` block in `.cursor/mcp.json`, `~/.codeium/windsurf/mcp_config.json`,
or `.vscode/mcp.json` (VS Code uses `"servers"` instead of `"mcpServers"`).

## ChatGPT, Gemini and others

Open [`PROMPT.md`](../PROMPT.md), paste it into the chat, and add your request at the bottom
along with the output of `videopip analyze ./clips`. Save the YAML it writes as
`project.yaml`, then run:

```bash
videopip preflight project.yaml
videopip render project.yaml
```

Paste any preflight errors back into the chat and ask it to fix the YAML.

## What a good request looks like

> 8-minute video from the clips in `D:\videos\batch7`. 10 garage tools, the jump starter first,
> the cheapest ones last. Honest but fun tone. Clip 4 has a logo card in the first 6 seconds.
> Clip 9's usable part starts at 0:12. Links are in `links.txt`. Also make a Short of the
> jump starter.

The AI breaks that down into clips, safe ranges, running order, intro shots, voiceover,
overlays, a Short and metadata, and asks only for what's missing.
