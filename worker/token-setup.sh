#!/bin/bash
# One pass for the builder's Access service token: paste the ID and secret once; this tests them against the
# operator route, then (if you say yes) stores both as GitHub Actions secrets and re-runs the builder.
# The values stay in this shell; nothing is written to disk.
cd "$(dirname "$0")/.." || exit 1
read -r -p "CF-Access-Client-Id: " ID
read -r -s -p "CF-Access-Client-Secret (hidden): " SECRET; echo
ID=${ID//[[:space:]]/}; SECRET=${SECRET//[[:space:]]/}
echo "id length ${#ID} (ends .access: $([[ $ID == *.access ]] && echo yes || echo NO)), secret length ${#SECRET}"
code=$(curl -s -o /tmp/token-setup.body -w '%{http_code}' -X POST \
  -H "CF-Access-Client-Id: $ID" -H "CF-Access-Client-Secret: $SECRET" \
  -H 'Content-Type: application/json' https://secretagentband.illsea.com/ideas/status -d '{}')
body=$(head -c 160 /tmp/token-setup.body | tr -d '\n'); rm -f /tmp/token-setup.body
echo "HTTP $code: $body"
case $code in
  302) echo "=> Access REJECTED the token (login redirect)."
       echo "   Zero Trust -> Access -> Applications -> the app -> Policies: there must be a policy with action"
       echo "   'Service Auth' whose Include rule is 'Service Token' -> builder (the token with this Client ID)."
       exit 1 ;;
  401|403) echo "=> refused after Access: $body"; echo "   (403 'operator only' = Worker-side; tell Claude)"; exit 1 ;;
  400|200) echo "=> Token ACCEPTED end to end (the hub answered)." ;;
  *) echo "=> unexpected"; exit 1 ;;
esac
read -r -p "Store both as GitHub secrets CF_ACCESS_CLIENT_ID / CF_ACCESS_CLIENT_SECRET and re-run the builder? [y/N] " yn
[[ $yn == [yY] ]] || exit 0
printf '%s' "$ID" | gh secret set CF_ACCESS_CLIENT_ID && printf '%s' "$SECRET" | gh secret set CF_ACCESS_CLIENT_SECRET \
  && gh workflow run "Build the top-voted ideas" && echo "=> secrets stored, builder started (GitHub -> Actions)."
