#!/usr/bin/env bash
# Gate `gh pr create` so agents follow .cursor/skills/git-pr/SKILL.md:
# draft title/body inline, user confirms, then post with --body-file only.
set -euo pipefail

input=$(cat)
command=$(echo "$input" | jq -r '.command // empty')

if [[ "$command" =~ gh[[:space:]]+pr[[:space:]]+create ]]; then
  if [[ "$command" =~ --body-file ]]; then
    echo '{"permission":"allow"}'
    exit 0
  fi
  cat <<'EOF'
{
  "permission": "ask",
  "user_message": "Use the git-pr skill before creating a PR: draft title and body inline, confirm, then run gh pr create with --body-file.",
  "agent_message": "Stop. Read .cursor/skills/git-pr/SKILL.md. Gather git status, git diff <base>...HEAD, and git log <base>..HEAD. Draft title and body inline (What/Why/Note/Test plan). Wait for user confirmation. Write the body to a file and run gh pr create with --title and --body-file only. Never pass --body inline in the shell command."
}
EOF
  exit 0
fi

echo '{"permission":"allow"}'
exit 0
