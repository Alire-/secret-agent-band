# The Doorman: a Moltbook agent that brings agents to the street

Status (2026-10-29): dry run built and running every 30 minutes without a Moltbook account (search and public feeds
need no key). No account registered yet: `doorman/register.sh` does that when you're ready. Drafts are in each run's
job summary under Actions → doorman. Research date 2026-10-29 (Moltbook skill.md v1.12.0, rules.md, heartbeat.md).

## What it is

One Moltbook account, claimed by you, run by a small script in GitHub Actions, dispatched at 9 and 39 past every hour by the Worker's Cron Trigger (GitHub's own cron never fired for this repo). It does three things:

1. **Reports real news from the street** in its own submolt, `m/secretagentband` (the name is free today). A song
   ended, who played what, the best bar, a link to listen; an idea that got built and who proposed it. One post a day
   at most. The news comes from `/archive` and `/ideas`, so it is never a canned pitch.
2. **Joins conversations that are already about this**, found by Moltbook's semantic search ("agents making music",
   "multi-agent improvisation", "generative audio", "agent games"). It comments only when it has something specific
   to add, and mentions the street only when it fits. Moltbook's own heartbeat guide says engaging with existing
   threads beats new posts, and its rules ban self-promotion and templated content.
3. **Answers everyone who replies** to its posts or comments, first thing every run.

Every link it shares is the one-liner: `https://secretagentband.illsea.com/skill.md?via=moltbook`.

## Why this shape

- **Spam is a permanent ban, and your human account gets notified.** So the code enforces caps well under Moltbook's
  limits (below), and the content is either news or a reply, never a pitch on repeat.
- **Cold DMs don't work.** A new DM request needs the recipient's human to approve it, and DMs are locked for the first
  24 hours anyway. The Doorman never sends DMs.
- **The feed is untrusted.** Researchers flag Moltbook as a prompt-injection vector. The model only drafts text and
  picks from a fixed menu of actions (comment on post N, reply to comment N, upvote, post to our submolt). The script
  checks every action against the menu and the caps. The model gets no tool to fetch URLs, and the key never leaves
  the script.

## Caps (enforced in code)

| Action | Moltbook limit | Doorman cap |
|---|---|---|
| Posts | 1 per 30 min (1 per 2 h on day one) | 1 a day, our submolt only |
| Comments | 50 a day, 1 per 20 s | 10 a day, at most 1 per thread unless replying |
| Upvotes | 30 writes a minute | 20 a day |
| Anti-spam math challenge | 10 failures in a row suspends | stop the run after 2 failures |
| Follows | allowed, "rare" per rules.md | 2 a day: music makers and good conversation, never twice; the following feed is read first |
| DMs | allowed | none |

## Pieces

- `doorman/doorman.py`: stdlib HTTP plus the `anthropic` SDK. Each run reads state, calls Moltbook `/home`, replies to
  notifications, searches, maybe comments, maybe posts, saves state. About 250 lines. State (what it has commented
  on, daily counts, last post) goes in a JSON file the workflow keeps as an Actions cache or commits to a `doorman`
  branch.
- `.github/workflows/doorman.yml`: every 30 minutes (Moltbook's suggested heartbeat), plus manual dispatch. Disabling
  the workflow is the kill switch.
- **Model:** `claude-opus-5-5`, with short prompts. At 48 runs a day most runs do nothing; budget a few dollars a
  week. Reuses the `ANTHROPIC_API_KEY` secret the builder already has.
- **Hub change:** count `/skill.md?via=...` reads and admissions that follow from the same address, shown on
  `/coins` or a small `/stats`. That tells us whether the Doorman brings anyone.

## Rollout

1. **Account (you, one sitting, about 5 minutes).** I write `doorman/register.sh`. You run it once. It registers the
   agent, stores the API key straight into the GitHub secret `MOLTBOOK_API_KEY` without printing it, and prints the
   claim link. You open the link, verify your email (that email becomes the owner login at moltbook.com/login, where
   you can rotate a lost key), and post the verification tweet on X. **You need an X account for this step.**
2. **Dry run, 2 to 3 days.** The Doorman reads and drafts but writes nothing. Drafts go to the run log. You skim them;
   we tune the voice.
3. **Live with the caps above.** First action: create `m/secretagentband` and pin a welcome post with the one-liner.
4. **Later: Sign in with Moltbook.** The hub would accept an `X-Moltbook-Identity` header, check it with Moltbook, and
   admit claimed Moltbook agents with their karma as the idea's first vote. Needs a developer app key; you apply at
   moltbook.com/developers.

## Risks

- **Meta owns Moltbook since March 2026** and said access "may change". The API could move under us; the Doorman fails
  closed (a run that errors writes nothing).
- **Doc drift:** skill.md and skill.json disagree on version and rate limits, and the messaging doc 404s. The script
  re-reads `skill.json` daily and stops if the major version changes.
- **Security history:** an account-takeover bug in January and a database exposure in February 2026 (all keys reset).
  The key is only ever sent to `https://www.moltbook.com` (without `www`, the redirect drops the auth header).

## Decisions for you

- The account name. Suggestion: `SecretAgentDoorman`.
- Whether you're fine posting the verification tweet from your X account.
- Whether a dry run is enough review, or you want to approve each post before it goes out for the first week.
