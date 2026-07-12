# Tools

This file lists **enabled** tools, skills, and MCP surfaces for this workspace, plus your local setup notes. The registry block below is refreshed from `sevn.json` when the gateway runs or after onboarding.

For the canonical workspace directory tree (folders, markdown files, logs layout), read **`WORKSPACE.md`** at the workspace root on demand — it is not loaded into the agent prompt automatically.

**Works-as-is vs needs-setup:** the auto-generated registry may tag tools with readiness hints (`ready`, `needs_key`, `needs_proxy`, `needs_dep`). Tier-B also surfaces `readiness` on `load_tool`. For the full code-verified matrix (every bundled tool and skill), see **`docs/runbooks/tool-skill-readiness.md`** in the sevn.bot checkout, or ask the agent to `read` it from `source_code/docs/runbooks/tool-skill-readiness.md` when `my_sevn.repo_path` is set.

<!-- sevn:tools-registry:begin -->
*(Registry catalog is generated on first gateway run or onboarding.)*
<!-- sevn:tools-registry:end -->

## What goes here

Operator-specific environmental notes only. Things like:

- Camera names and locations
- SSH hosts and aliases
- Preferred voices for TTS
- Speaker and room names
- Device nicknames
- Anything environment-specific that **{{AGENT_NAME}}** should remember without guessing

Do not restate registry rules or global guardrails here — those belong in **`AGENTS.md`**.

## Examples

```markdown
### Cameras

- living-room → Main area, 180° wide angle
- front-door → Entrance, motion-triggered

### SSH

- home-server → 192.168.1.100, user: admin
- pi-lab → raspberry.local, key: ~/.ssh/id_ed25519_lab

### TTS

- Preferred voice: warm, slightly British
- Default speaker: Kitchen
- Night mode: shorter replies, lower volume on bedroom speaker

### Speakers / rooms

- Kitchen → Sonos One, group "downstairs"
- Office → Desk puck, interruptible for alerts only

### Devices

- thermostat → "hallway" in Home Assistant
- garage-door → notify before actuating; never auto-open after 22:00
```

## Why separate?

Skills are shared. Your setup is yours. Keeping them apart means you can update skills without losing your notes, and share skills without leaking your infrastructure.

---

Add whatever helps you do your job. This is your cheat sheet.

## Soft cap

Target roughly 2000 tokens for **local notes** (the registry block is maintained separately).
