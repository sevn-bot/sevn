# Agent, models, voice, skills, and tools

Mission Control agent panel data is available from the CLI:

| Command | Purpose |
|---------|---------|
| `sevn agent status` | Active run snapshots |
| `sevn agent config` | Resolved model slots |
| `sevn models show` | Same slots as agent config |
| `sevn models params` | `LLM_params_config.json` sampling overrides |
| `sevn voice show` | Local `sevn.json` voice settings |
| `sevn voice status` | Live STT/TTS provider probes |
| `sevn skills list` | Workspace skill inventory |
| `sevn tools health` | Chronic tool/skill failure rows |

All support `--json`.
