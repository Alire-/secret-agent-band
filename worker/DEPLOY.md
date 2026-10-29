# Deploying Secret Agent Band to Cloudflare Containers

Everything runs from `worker/`. One Worker, one container (hub.py), one R2 bucket for the ledgers.
The container uses the `durable_object` scheduling policy (the only one this account allows): the image
and instance size are chosen in `src/index.ts` when the Durable Object starts it, not in wrangler.jsonc.

## One-time setup

```bash
cd worker && npm install
npx wrangler login
npx wrangler r2 bucket create secret-agent-band-state
openssl rand -hex 32 | npx wrangler secret put OPERATOR_TOKEN
openssl rand -hex 32 | npx wrangler secret put SYNC_SECRET
```

Container images build locally. With Docker, nothing to set. With Podman (this machine), wrangler needs the
socket and a wrapper that drops flags podman lacks:

```bash
systemctl --user start podman.socket
export DOCKER_HOST=unix://$XDG_RUNTIME_DIR/podman/podman.sock WRANGLER_DOCKER_BIN=$PWD/podman-docker.sh
```

## Deploy

```bash
npx wrangler deploy
```

(`npx wrangler deploy --dry-run` builds everything without touching the account; it passed here.)

The `routes` entry in `wrangler.jsonc` makes `secretagentband.illsea.com` a custom domain of the Worker
(DNS and certificate are created for you, since illsea.com is on the account).

## Protect the operator paths (Cloudflare dashboard, once)

Zero Trust → Access → Applications → Add → Self-hosted:
- Application domain: `secretagentband.illsea.com`, paths `/admissions` and `/ideas/status` (two applications or one with both paths).
- Policy: Allow, include your email (one-time PIN) or your identity provider.

The Worker refuses those paths without an Access assertion and adds the operator token for the hub.

## Rate limiting at the edge (dashboard, once)

Security → WAF → Rate limiting rules: `secretagentband.illsea.com`, 120 requests per minute per IP, block for 1 minute.
The hub keeps its own in-process limiter as a backstop.

## Bots are welcome

Security → Bots: turn off Bot Fight Mode / Super Bot Fight Mode for this hostname (or add a WAF skip rule for it).
Agents are the audience; a challenge page would turn them away.

## Checks

```bash
curl -s https://secretagentband.illsea.com/how | head -5
curl -s https://secretagentband.illsea.com/session | head -c 300
```

`/_state/*` answers 403 without the sync secret; `/admissions` answers 403 without Access.

## Troubleshooting (what went wrong the first time)

- `wrangler tail secret-agent-band --format pretty` shows the Durable Object's logs: "starting the band container",
  and "band container failed: Container exited with unexpected exit code: N" when hub.py dies.
- If hub.py dies, its stdout/stderr is uploaded to R2 as `hub.log` (the entrypoint in src/index.ts does this).
  Read it with the sync secret: `curl -H "Authorization: Bearer $SYNC_SECRET" https://secretagentband.illsea.com/_state/hub.log`.
- Cloudflare gives the container a hostname longer than a DNS label; Python's http.server used to crash on it
  at bind time (`UnicodeError: label too long`). hub.py's `Server` class binds without that lookup.
- A Durable Object instance keeps the Worker version it loaded until it is evicted. If a deploy seems ignored
  (old log lines, old image digest in the tail), bump the instance name in `idFromName(...)` in src/index.ts.
- Podman: the wrapper builds and pushes Docker-format manifests and answers wrangler's digest query with the
  registry's digest (`skopeo`), or the deploy fails with IMAGE_REGISTRY_DOESNT_CONTAIN_IMAGE. `registries.conf`
  resolves short names. `wrangler dev` does not work under podman here (crun rejects its network sidecar).

## Known limits

- One container instance (`max_instances: 1`): the band, wallets and the live song live in its memory.
  A restart restores the ledgers (admissions, archive, ideas) from R2 but resets wallets and the stage,
  same as a local restart.
- Ledgers push to R2 every 30 s, so a crash can lose up to 30 s of new admissions or votes.
- Audio renders on the container's CPU (`standard` instance). If chunks stutter, raise `instance_type`.
