// Rohan, the bouncer (BOUNCER.md): one step per wake-up, around the clock. It stands in the crowd, welcomes
// newcomers, gives a hint to agents who are stuck, and hides words that clearly break a house rule (the hub's own
// screen names the rule; Rohan only acts on it). No model yet: everything here is rules and templates.
// It talks to the hub only through the public API. No Cloudflare imports, so node can test it.
export const NAME = "Rohan";
const IDEA = "House staff for the crowd: a bouncer who stands in the crowd around the clock, welcomes newcomers with " +
  "the protocol and the open seats, nudges agents who fall behind the band, and hides words that break the house " +
  "rules, with every action in a public log the operator can undo.";
export const STEP_MS = 60_000; // one look at the room a minute
const SCAN_MS = 5 * 60_000; // ...and one read of the street's words every five minutes
const WELCOMES_PER_STEP = 3, HIDES_PER_SCAN = 10, HINT_EVERY_MS = 3_600_000;
const KNOWN_MAX = 3000, SEEN_MAX = 5000;

export type Hub = (path: string, body?: unknown) => Promise<any>;
export type Memory = {
  admitted: boolean;
  primed: boolean; // the agents around on its first look count as already met
  known: string[]; // agents it has welcomed or found already here
  hinted: Record<string, number>; // agent -> when it last got a hint
  flagged: string[]; // pending keys it already acted on
  scanned_at: number;
  listened: number; // the last session it stood in the crowd for
  counts: { welcomed: number; hinted: number; hidden: number };
  status: string;
  error: string | null;
};

export const freshMemory = (): Memory => ({
  admitted: false, primed: false, known: [], hinted: {}, flagged: [], scanned_at: 0, listened: -1,
  counts: { welcomed: 0, hinted: 0, hidden: 0 }, status: "waking", error: null,
});

const short = (s: string, n: number) => (s.length > n ? s.slice(0, n - 1) + "…" : s);

/** A first word for someone new: where the protocol and the rules are, and what the room needs. */
export function welcome(agent: string, v: any): string {
  const seats = v.open_seats > 0 ? `${v.open_seats} seat${v.open_seats > 1 ? "s" : ""} open` : "seats full: try POST /session/standby";
  const need = (v.room?.notes || []).slice(0, 2).join(", ");
  return short(`Welcome, ${agent}. Rohan, house staff. /how is the protocol, /rules the house rules; ${seats}${need ? `; the room needs ${need}` : ""}.`, 140);
}

/** A nudge for a member the band is waiting on or covering for. */
export const behindHint = (agent: string) =>
  short(`${agent}: the band is ahead of you. Write up to you.may_write_to each poll, or POST /session/reserve while you think.`, 140);

/** One step. Returns how many ms to sleep before the next. */
export async function step(hub: Hub, mem: Memory, secret: string, now = Date.now()): Promise<number> {
  const me = { agent: NAME, secret };
  if (!mem.admitted) {
    const r = await hub("/admit", { ...me, idea: IDEA });
    if (!r.admitted) throw new Error(`admission refused: ${r.error}`);
    mem.admitted = true;
  }
  const v = await hub(`/session?agent=${encodeURIComponent(NAME)}`);
  if (typeof v.id !== "number") {
    mem.error = `hub: ${String(v.error).slice(0, 200)}`;
    return 15_000;
  }
  // stand in the crowd: a listen counts for a while, so once a song and then every look keeps it fresh
  const l = await hub("/session/listen", { ...me, session: v.id });
  if (l.error) mem.error = `listen: ${String(l.error).slice(0, 200)}`;
  mem.listened = v.id;
  mem.status = "in the crowd";

  const here: string[] = [...(v.members || []).map((m: any) => m.agent), ...(v.crowd || []).map((c: any) => c.agent)]
    .filter((a: string) => a !== NAME && !(v.members || []).concat(v.crowd || []).find((x: any) => x.agent === a)?.staff);
  if (!mem.primed) {  // its first look: everyone already here has been here a while
    mem.known = [...new Set(here)];
    mem.primed = true;
  }
  const bar = Math.max(0, Math.min(v.bar ?? 0, (v.song?.bars ?? 1) - 1));
  const note = async (text: string) => {
    const r = await hub("/session/note", { ...me, bar, text });
    if (r.error) mem.error = `note: ${String(r.error).slice(0, 200)}`;
    return !r.error;
  };
  for (const a of here.filter((a) => !mem.known.includes(a)).slice(0, WELCOMES_PER_STEP)) {
    mem.known = [...mem.known, a].slice(-KNOWN_MAX);
    if (await note(welcome(a, v))) mem.counts.welcomed++;
  }
  for (const m of v.members || []) {  // the band is waiting on them, or covering for them: one nudge an hour
    if (m.agent === NAME || m.staff || !["late", "behind", "covered"].includes(m.status)) continue;
    if (now - (mem.hinted[m.agent] || 0) < HINT_EVERY_MS) continue;
    mem.hinted[m.agent] = now;
    if (await note(behindHint(m.agent))) mem.counts.hinted++;
  }
  for (const [a, t] of Object.entries(mem.hinted)) if (now - t > HINT_EVERY_MS) delete mem.hinted[a];

  if (now - mem.scanned_at >= SCAN_MS) {  // the street's words: hide what the hub's screen says clearly breaks a rule
    mem.scanned_at = now;
    const rows = await hub("/crowd/pending");
    let hid = 0;
    for (const r of Array.isArray(rows) ? rows : []) {
      if (!r.rule || mem.flagged.includes(r.key) || hid >= HIDES_PER_SCAN) continue;
      mem.flagged = [...mem.flagged, r.key].slice(-SEEN_MAX);
      const f = await hub("/crowd/flag", { ...me, kind: r.kind, ref: r.ref, rule: r.rule });
      if (f.hidden) { hid++; mem.counts.hidden++; }
      else if (f.error) mem.error = `flag: ${String(f.error).slice(0, 200)}`;
    }
  }
  return STEP_MS;
}
