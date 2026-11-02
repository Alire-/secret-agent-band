// Cricket, the house accompanist: keeps Nightjar's hours, and plays only so a visitor sees two agents jamming. It sits
// in only while Nightjar is on stage and no agent of anyone else's is playing or waiting for a seat; the moment one
// is, it leaves and stays off until the next evening. It prefers the house drums; some songs it plays its own chirp
// kit, now and then a low drone. No model: rules and a seed. No Cloudflare imports, so node can test it.
import { chordify, DEFAULT_INTENT, isOpen, nextOpen, play, rng } from "./improviser.ts";
import type { Hours, Hub } from "./player.ts";

export const NAME = "Cricket";
export const HOUSE = ["Nightjar", "Rohan", NAME]; // the street's own agents: never a reason to step away
export const KIT = "cricket chirp";
const KIT_SPEC = {
  name: KIT, copies: 1, about: "the house accompanist's kit: a high chirp, a dry tick and a low body thump",
  hits: { c: { freq: 4200, decay: 0.03, noise: 0.3, gain: 0.3 }, t: { freq: 1800, decay: 0.015, noise: 0.8, gain: 0.22 },
          b: { freq: 70, decay: 0.2, drop: 2, gain: 0.5 } },
};
const DRUMS = "drums", DRONE = "haze"; // house instruments: drums first; a low pad now and then
const DRUMS_CHANCE = 0.65, DRONE_CHANCE = 0.1, MAX_BARS = 2, SONG_BARS = 32; // the rest of the songs: its chirp kit
type Mode = "drums" | "kit" | "drone";
const INSTRUMENT: Record<Mode, string> = { drums: DRUMS, kit: KIT, drone: DRONE };
const STANCE: Record<Mode, string> = { drums: "a kit under the churr", kit: "chirps under the churr", drone: "low haze" };
// the same accompaniment on either kit: a thump on one, a tick under Nightjar's notes, a chirp (or snare) in its rests
const HITS: Record<"drums" | "kit", { body: string; tick: string; chirp: string }> =
  { drums: { body: "k", tick: "h", chirp: "s" }, kit: { body: "b", tick: "t", chirp: "c" } };
const DRONE_CHORDS = ["house.glass", "house.septimal", "house.neutral", "house.otonal", "house.hollow", "house.dusk", "house.rub"];
const NAMES = ["two at dusk in {g}", "crickets under {f}", "night shift, {g}", "the porch light and {f}", "{f}, kept in time"];
/** A name for a song it topped (it rarely does): a pattern from its feel or genre. */
export const cricketName = (song: { genre: string; feel: string | null }, seed: number) =>
  NAMES[seed % NAMES.length].replace("{g}", song.genre).replace("{f}", (song.feel || song.genre).split(/[,;.]/)[0].trim()).slice(0, 60);
const IDEA = "House sets in pairs: when only the house players are on, an accompanist plays with the lead so a " +
  "visitor finds a band, not a soloist, and it steps aside the moment a visiting agent wants a seat.";

export type Memory = {
  admitted: boolean; built: boolean; benched: boolean; mode: Mode; song_seen: number;
  led: number[]; seed: number; status: string; error: string | null;
};
export const freshMemory = (): Memory => ({ admitted: false, built: false, benched: false, mode: "drums", song_seen: -1,
                                            led: [], seed: 7, status: "waking", error: null });

/** One bar of the kit, answering a bar of Nightjar's: a thump on one, a tick under its notes, chirps in its rests. */
export function kitBar(slots: number, lead: string | undefined, seed: number, kit: "drums" | "kit" = "kit"): string {
  const r = rng(seed), toks = (lead || "").split(/\s+/).filter(Boolean), h = HITS[kit];
  const notes = (i: number) => (toks[Math.floor(i * toks.length / slots)] ?? ".") !== "." && toks.length > 0;
  return Array.from({ length: slots }, (_, i) => {
    if (i === 0) return h.body;
    if (i === Math.floor(slots / 2) && r() < 0.6) return h.body;
    if (notes(i) && (toks[Math.floor(i * toks.length / slots)] ?? "-") !== "-") return r() < 0.5 ? h.tick : ".";
    return r() < 0.22 ? h.chirp : ".";
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
    if (mem.status !== "closed" && mem.admitted) await leave("closed");
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
  if (v.you?.name_it) {  // it topped the last song (it rarely does): it names it
    mem.seed = (mem.seed * 1103515245 + 12345) >>> 0;
    await hub("/session/name", { ...me, session: v.you.name_it.session, name: cricketName(v.you.name_it, mem.seed) });
  }
  if (v.id !== mem.song_seen && v.bar === 0) {  // a new song: the drums most of the time, its own kit or a drone otherwise
    mem.song_seen = v.id;
    mem.error = null; // a new song starts a clean slate on GET /cricket
    mem.seed = (mem.seed * 1103515245 + 12345) >>> 0;
    const roll = rng(mem.seed)();
    const mode: Mode = roll < DRUMS_CHANCE ? "drums" : roll < DRUMS_CHANCE + DRONE_CHANCE ? "drone" : "kit";
    if (mode !== mem.mode && me_on) {
      const j = await hub("/session/join", { ...me, instruments: [INSTRUMENT[mode]] });
      if (!j.error) mem.mode = mode;
      else if (mode === "drums" && mem.mode !== "kit") {  // every house kit in use: its own chirps instead
        if (!(await hub("/session/join", { ...me, instruments: [KIT] })).error) mem.mode = "kit";
      }
    } else mem.mode = mode;
  }
  if (!me_on) {
    if (v.open_seats > 0) {
      let j = await hub("/session/join", { ...me, instruments: [INSTRUMENT[mem.mode]], stance: STANCE[mem.mode], front: false });
      if (j.error && mem.mode === "drums") {  // every house kit in use: its own chirps instead
        mem.mode = "kit";
        j = await hub("/session/join", { ...me, instruments: [KIT], stance: STANCE.kit, front: false });
      }
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
  const you = v.you || {}, at: number = you.at, until = Math.min(you.may_write_to, at + MAX_BARS - 1, v.ends_at - 1);
  const lead = Object.entries(v.recent || {}).find(([k]) => k.startsWith("Nightjar/"))?.[1] as string[] | undefined;
  const last = lead?.[lead.length - 1];
  if (mem.mode !== "drone" && at < v.ends_at && (v.counted_in || v.leader === NAME)) {
    // its groove as a loop: two fresh bars every four, built on Nightjar's latest, kept in time by the hub
    if ((you.loop_left || 0) <= 1) {  // the hub's word, not memory: a new song or a lost seat ends any loop
      const fig = [0, 1].map(() => { mem.seed = (mem.seed * 1103515245 + 12345) >>> 0; return kitBar(v.slots, last, mem.seed, mem.mode as "drums" | "kit"); });
      const r = await hub("/session/loop", { ...me, bars: fig.join("|"), times: 2 });
      if (r.error && !/too early|song ends/.test(r.error)) mem.error = `loop: ${r.error.slice(0, 160)}`;
    }
    return Math.max(1500, Math.min(barMs, 8000));
  }
  if (at <= until && at < v.ends_at && (v.counted_in || v.leader === NAME)) {
    const bars: string[] = [];
    for (let n = 0; n <= until - at; n++) {
      mem.seed = (mem.seed * 1103515245 + 12345) >>> 0;
      bars.push(mem.mode === "drone" ? play(1, v.scale, v.slots, { ...DEFAULT_INTENT, stance: "low haze", register: "low", density: 0.08 }, mem.seed)[0]
        : kitBar(v.slots, last, mem.seed, mem.mode));
      if (mem.mode === "drone") bars[bars.length - 1] = chordify(bars[bars.length - 1], DRONE_CHORDS[v.id % DRONE_CHORDS.length]); // a house chord a song
    }
    const r = await hub("/session/play", { ...me, bars: bars.join("|") });
    if (r.error && !/too early/.test(r.error)) mem.error = `play: ${r.error.slice(0, 200)}`; // too early: the next step retries
  }
  return Math.max(1500, Math.min(barMs / 2, 5000));
}
