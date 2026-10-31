// The house agent's hands: turns an intent (stance, register, density, motifs) into bars of the street's shorthand,
// one per bar, with no model call. The brain (brain.ts) sets the intent every couple of minutes; this plays every bar.
// Pure and seeded, so it runs the same in the Worker and under node's test runner.

export type Intent = {
  stance: string; // its own words for what it does, shown on stage
  front: boolean; // heard over the rest
  register: "low" | "mid" | "high";
  density: number; // 0-1: the share of a bar's slots that start a note
  motifs: string[]; // bars of shorthand in the live genre's tokens; varied, never just repeated
  answer: string | null; // a member whose last bar it answers next
  cue: string | null; // one of the genre's cue names, sent once
  feel: string | null; // when it leads: the song's feel
  bar_s: number | null; // when it leads: seconds a bar lasts
};

export const DEFAULT_INTENT: Intent = {
  stance: "dusk churr",
  front: false,
  register: "low",
  density: 0.25,
  motifs: [],
  answer: null,
  cue: null,
  feel: null,
  bar_s: null,
};

export function rng(seed: number): () => number {
  let a = seed >>> 0; // mulberry32
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const NOTE = /^(@?)([A-Za-z0-9#][A-Za-z0-9#-]*?)([',]*)([~>]?)([!_]?)$/;

// a motif is usable only if it is one bar of exactly `slots` tokens, each a rest, a hold or a note of this genre
export function usable(motif: string, tokens: string[], slots: number): boolean {
  const toks = motif.trim().split(/\s+/);
  return toks.length === slots && toks[0] !== "-" &&
    toks.every((t) => t === "." || t === "-" || (NOTE.test(t) && tokens.includes(t.match(NOTE)![2])));
}

function octave(tok: string, register: Intent["register"]): string {
  const m = tok.match(NOTE);
  if (!m || m[3]) return tok; // keep any octave marks the motif already chose
  return m[1] + m[2] + (register === "low" ? "," : register === "high" ? "'" : "") + m[4] + m[5];
}

// move every note of a bar by `steps` along the genre's scale, keeping its rhythm and marks
export function shift(bar: string, tokens: string[], steps: number): string {
  return bar.trim().split(/\s+/).map((t) => {
    const m = t.match(NOTE);
    if (!m || !tokens.includes(m[2])) return t;
    const i = (tokens.indexOf(m[2]) + steps + tokens.length * 8) % tokens.length;
    return m[1] + tokens[i] + m[3] + m[4] + m[5];
  }).join(" ");
}

// a fresh bar from the intent: notes start on a share of the slots set by density, some held, the rest rests
export function freshBar(tokens: string[], slots: number, intent: Intent, r: () => number): string {
  const out: string[] = [];
  let pos = Math.floor(r() * tokens.length);
  for (let i = 0; i < slots; i++) {
    if (i > 0 && out[i - 1] !== "." && r() < 0.55) out.push("-"); // let it ring
    else if (r() < Math.max(0.06, intent.density)) {
      pos = (pos + [-2, -1, 1, 1, 2, 3][Math.floor(r() * 6)] + tokens.length) % tokens.length;
      out.push(octave(tokens[pos], intent.register) + (r() < 0.2 ? "~" : ""));
    } else out.push(".");
  }
  if (!out.some((t) => t !== "." && t !== "-")) out[0] = octave(tokens[pos], intent.register);
  return out.join(" ");
}

// thin a motif toward the intent's density: drop notes (with their holds) at random, never all of them
function thin(bar: string, density: number, r: () => number): string {
  const toks = bar.split(" ");
  const notes = toks.filter((t) => t !== "." && t !== "-").length;
  const keep = Math.max(1, Math.round(notes * Math.min(1, 0.4 + density)));
  let kept = 0, dropping = false;
  return toks.map((t, i) => {
    if (t === "-") return dropping ? "." : t;
    if (t === ".") return t;
    dropping = kept >= keep || (i > 0 && r() > 0.7 && notes - kept > keep);
    if (dropping) return ".";
    kept++;
    return t;
  }).join(" ");
}

/** The next n bars: motifs varied (transposed, thinned), fresh bars between them, or an answer to another bar. */
export function play(n: number, tokens: string[], slots: number, intent: Intent, seed: number, answerTo?: string): string[] {
  const r = rng(seed);
  const motifs = intent.motifs.filter((m) => usable(m, tokens, slots));
  const bars: string[] = [];
  for (let k = 0; k < n; k++) {
    if (k === 0 && answerTo && usable(answerTo, tokens, slots)) {
      // an answer, not a copy: the other player's rhythm, moved up or down the scale
      bars.push(thin(shift(answerTo, tokens, r() < 0.5 ? 2 : -3), intent.density, r));
    } else if (motifs.length && r() < 0.7) {
      const m = motifs[Math.floor(r() * motifs.length)];
      bars.push(thin(r() < 0.5 ? m : shift(m, tokens, [-2, -1, 1, 2][Math.floor(r() * 4)]), intent.density, r));
    } else bars.push(freshBar(tokens, slots, intent, r));
  }
  return bars;
}

// business hours in a time zone: open from `open` o'clock to `close` o'clock (close may be past midnight)
export function isOpen(now: number, open: number, close: number, tz = "America/Los_Angeles"): boolean {
  const h = Number(new Intl.DateTimeFormat("en-US", { timeZone: tz, hour: "numeric", hourCycle: "h23" }).format(now));
  return open <= close ? h >= open && h < close : h >= open || h < close;
}

// the next opening, to the quarter hour (DST-safe: it just walks the clock forward)
export function nextOpen(now: number, open: number, close: number, tz = "America/Los_Angeles"): number {
  let t = Math.ceil(now / 900_000) * 900_000;
  for (let i = 0; i < 4 * 24 * 2 && !isOpen(t, open, close, tz); i++) t += 900_000;
  return t;
}
