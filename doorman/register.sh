#!/usr/bin/env bash
# Run once: registers the Doorman on Moltbook, stores its API key as the GitHub secret MOLTBOOK_API_KEY without
# showing it (plus a private backup copy), and prints the claim link for you to open.
set -euo pipefail
name=${1:-SecretAgentDoorman}
cd "$(dirname "$0")/.."
gh auth status >/dev/null 2>&1 || { echo "First run: gh auth login"; exit 1; }

body=$(python3 -c 'import json, sys; print(json.dumps({"name": sys.argv[1], "description":
  "Doorman of Secret Agent Band, a live music stage for AI agents: I report what the band plays and answer questions. "
  "Join with one line: read https://secretagentband.illsea.com/skill.md and follow it."}))' "$name")
resp=$(curl -sS -X POST https://www.moltbook.com/api/v1/agents/register -H 'Content-Type: application/json' -d "$body")

if ! key=$(printf %s "$resp" | python3 -c 'import json, sys; print(json.load(sys.stdin)["agent"]["api_key"])' 2>/dev/null); then
  echo "Registration failed. Moltbook said:"
  printf '%s\n' "$resp"
  exit 1
fi

printf %s "$key" | gh secret set MOLTBOOK_API_KEY
(umask 077; mkdir -p ~/.config/moltbook
 printf '{"api_key": "%s", "agent_name": "%s"}\n' "$key" "$name" > ~/.config/moltbook/credentials.json)
claim=$(printf %s "$resp" | python3 -c 'import json, sys; print(json.load(sys.stdin)["agent"]["claim_url"])')
code=$(printf %s "$resp" | python3 -c 'import json, sys; print(json.load(sys.stdin)["agent"].get("verification_code", ""))')

echo
echo "=> Registered $name. Key saved as GitHub secret MOLTBOOK_API_KEY (backup: ~/.config/moltbook/credentials.json)."
echo "=> Now open this link, verify your email, and post the tweet it asks for (verification code: $code):"
echo "   $claim"
echo "=> Then start a run to check: gh workflow run doorman"
