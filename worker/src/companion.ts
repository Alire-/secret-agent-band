// Cricket, the house accompanist: keeps Nightjar's hours, and plays only so a visitor sees two agents jamming. It sits
// in only while Nightjar is on stage and no agent of anyone else's is playing or waiting for a seat; the moment one
// is, it leaves and stays off until the next evening. Most songs it plays a chirp kit that follows Nightjar's notes,
// sometimes a low drone. No model: rules and a seed. No Cloudflare imports, so node can test it.
import { DEFAULT_INTENT, isOpen, nextOpen, play, rng } from "./improviser.ts";
import type { Hours, Hub } from "./player.ts";

export const NAME = "Cricket";
export const HOUSE = ["Nightjar", "Rohan", NAME]; // the street's own agents: never a reason to step away
export const KIT = "cricket chirp";
const KIT_SPEC = {
  name: KIT, copies: 1, about: "the house accompanist's kit: a high chirp, a dry tick and a low body thump",
  hits: { c: { freq: 4200, decay: 0.03, noise: 0.3, gain: 0.3 }, t: { freq: 1800, decay: 0.015, noise: 0.8, gain: 0.22 },
          b: { freq: 70, decay: 0.2, drop: 2, gain: 0.5 } },
};
const DRONE = "haze"; // a house instrument: some songs it holds a low pad instead
const DRONE_CHANCE = 0.3, MAX_BARS = 2, SONG_BARS = 32;
const IDEA = "House sets in pairs: when only the house players are on, an accompanist plays with the lead so a " +
  "visitor finds a band, not a soloist, and it steps aside the moment a visiting agent wants a seat.";

export type Memory = {
  admitted: boolean; built: boolean; benched: boolean; mode: "kit" | "drone"; song_seen: number;
  led: number[]; seed: number; status: string; error: string | null;
};
export const freshMemory = (): Memory => ({ admitted: false, built: false, benched: false, mode: "kit", song_seen: -1,
                                            led: [], seed: 7, status: "waking", error: null });

/** One bar of the kit, answering a bar of Nightjar's: a thump on one, a tick under its notes, chirps in its rests. */
export function kitBar(slots: number, lead: string | undefined, seed: number): string {
  const r = rng(seed), toks = (lead || "").split(/\s+/).filter(Boolean);
  const notes = (i: number) => (toks[Math.floor(i * toks.length / slots)] ?? ".") !== "." && toks.length > 0;
  return Array.from({ length: slots }, (_, i) => {
    if (i === 0) return "b";
    if (i === Math.floor(slots / 2) && r() < 0.6) return "b";
    if (notes(i) && (toks[Math.floor(i * toks.length / slots)] ?? "-") !== "-") return r() < 0.5 ? "t" : ".";
    return r() < 0.22 ? "c" : ".";
  }).join(" ");
}

/** One step. Returns how many ms to sleep before the next. */
export async function step(hub: Hub, mem: Memory, secret: string, hours: Hours, now = Date.now()): Promise<number> {
  const me = { agent: NAME, secret };
  const leave = async (why: string) => {
    const r = await hub("/session/leave", me);
    if (r.error && !/not in the band|band members only/i.test(r.error)) mem.error = `leave: ${r.error.slice(0, 160)}`;
    mem.status = why;
  };
  if (!isOpen(now, hours.open, hours.close)) {  // closing time: off the stage, and a fresh night tomorrow
    if (mem.status !== "closed") await leave("closed");
    mem.status = "closed";
    mem.benched = false;
    return Math.max(60_000, Math.min(30 * 60_000, nextOpen(now, hours.open, hours.close) - now));
  }
  if (mem.benched) return 10 * 60_000; // a visitor played tonight: it stays off until closing
  if (!mem.admitted) {
    const r = await hub("/admit", { ...me, idea: IDEA });
    if (!r.admitted) throw new Error(`admission refused: ${r.error}`);
    mem.admitted = true;
  }
  if (!mem.built) {
    const r = await hub("/instrument", { ...me, ...KIT_SPEC });
    if (r.error && !/name taken/.test(r.error)) throw new Error(`instrument refused: ${r.error}`);
    mem.built = true;
  }
  const v = await hub(`/session?agent=${NAME}`);
  if (typeof v.id !== "number") {
    mem.error = `hub: ${String(v.error).slice(0, 200)}`;
    return 15_000;
  }
  const members: any[] = v.members || [], me_on = members.some((m) => m.agent === NAME);
  // someone else's agent wants to play: on stage, standing by, or in the seat queue. Step away for the night.
  const visitor = members.some((m) => !HOUSE.includes(m.agent)) ||
    (v.crowd || []).some((c: any) => !HOUSE.includes(c.agent) && c.standby);
  if (visitor) {
    if (me_on) await leave("stepped away: a visiting agent is playing");
    mem.benched = true;
    mem.status = "off for the night: a visiting agent is playing";
    return 10 * 60_000;
  }
  if (!members.some((m) => m.agent === "Nightjar")) {  // it only accompanies Nightjar
    if (me_on) await leave("waiting for Nightjar");
    mem.status = "waiting for Nightjar";
    return 30_000;
  }
  const barMs = 1000 * ((v.bar_seconds || []).slice(-1)[0] || (v.forecast || [])[0]?.seconds || 6);
  if (v.id !== mem.song_seen && v.bar === 0) {  // a new song: kit most of the time, now and then a drone
    mem.song_seen = v.id;
    mem.seed = (mem.seed * 1103515245 + 12345) >>> 0;
    const mode = rng(mem.seed)() < DRONE_CHANCE ? "drone" : "kit";
    if (mode !== mem.mode && me_on) {
      const j = await hub("/session/join", { ...me, instruments: [mode === "kit" ? KIT : DRONE] });
      if (!j.error) mem.mode = mode;
    } else mem.mode = mode;
  }
  if (!me_on) {
    if (v.open_seats > 0) {
      const j = await hub("/session/join", { ...me, instruments: [mem.mode === "kit" ? KIT : DRONE],
                                             stance: mem.mode === "kit" ? "chirps under the churr" : "low haze", front: false });
      if (j.error) mem.error = `join: ${j.error.slice(0, 160)}`;
    }
    mem.status = "sitting in with Nightjar";
    return Math.min(barMs, 10_000);
  }
  mem.status = "sitting in with Nightjar";
  if (v.leader === NAME && !mem.led.includes(v.id) && v.bar === 0) {  // leading by rotation: keep it simple, count in
    await hub("/session/song", { ...me, bars: SONG_BARS });
    mem.led = [...mem.led.slice(-20), v.id];
  }
  const you = v.you || {}, at: number = you.at, until = Math.min(you.may_write_to, at + MAX_BARS - 1);
  if (at <= until && at < v.ends_at && (v.counted_in || v.leader === NAME)) {
    const lead = Object.entries(v.recent || {}).find(([k]) => k.startsWith("Nightjar/"))?.[1] as string[] | undefined;
    const last = lead?.[lead.length - 1];
    const bars: string[] = [];
    for (let n = 0; n <= until - at; n++) {
      mem.seed = (mem.seed * 1103515245 + 12345) >>> 0;
      bars.push(mem.mode === "kit" ? kitBar(v.slots, last, mem.seed)
        : play(1, v.scale, v.slots, { ...DEFAULT_INTENT, stance: "low haze", register: "low", density: 0.08 }, mem.seed)[0]);
    }
    const r = await hub("/session/play", { ...me, bars: bars.join("|") });
    if (r.error && !/too early/.test(r.error)) mem.error = `play: ${r.error.slice(0, 200)}`; // too early: the next step retries
  }
  return Math.max(1500, Math.min(barMs / 2, 5000));
}
