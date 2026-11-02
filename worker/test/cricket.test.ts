// node --test test/: Cricket sits in only with Nightjar and only while no visitor wants to play; then (HUB_TEST=1)
// Nightjar and Cricket play a song together against a real hub.py, and Cricket steps away when a visitor sits in.
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { test } from "node:test";
import { cricketName, freshMemory as cricketMemory, KIT, kitBar, NAME, step as cricketStep } from "../src/companion.ts";
import { fallbackName, freshMemory, sane, step } from "../src/player.ts";

const open = { open: 0, close: 24 }, closed = { open: 3, close: 3 };

test("a kit bar is the genre's slots of the kit's hits, a thump on one", () => {
  for (const slots of [6, 8, 12, 16]) for (let seed = 1; seed < 50; seed++) {
    const bar = kitBar(slots, "s0 - . s4 . . s2 . s0 - - . s7 . . .", seed).split(" ");
    assert.equal(bar.length, slots);
    assert.ok(bar.every((t) => ["b", "t", "c", "."].includes(t)));
    assert.equal(bar[0], "b");
    const drums = kitBar(slots, "s0 . s4 -", seed, "drums").split(" ");  // the same feel on the house drums
    assert.ok(drums.every((t) => ["k", "h", "s", "."].includes(t)) && drums[0] === "k");
  }
});

test("song names, when no model is free: short, from the feel or the genre", () => {
  for (let seed = 0; seed < 20; seed++) {
    for (const n of [fallbackName({ genre: "tallow sweep", feel: "a porch light coming on, slowly" }, seed),
                     cricketName({ genre: "drift", feel: null }, seed)]) {
      assert.ok(n.length >= 3 && n.length <= 60, n);
    }
  }
  assert.match(fallbackName({ genre: "drift", feel: "low tide; then rain" }, 0), /over low tide$/);
});

test("it waits for Nightjar, sits in with it, and steps away for the night when a visitor wants to play", async () => {
  const posts: [string, any][] = [];
  let members: any[] = [], crowd: any[] = [];
  const hub = async (p: string, b?: any) => {
    if (b !== undefined) posts.push([p, b]);
    if (p === "/admit") return { admitted: true };
    if (p === "/instrument") return { name: b.name };
    if (p.startsWith("/session?")) return { id: 4, bar: 2, slots: 8, scale: ["s0"], ends_at: 32, open_seats: 4, counted_in: true,
      members, crowd, recent: { "Nightjar/nightjar churr": ["s0 . . . s0 - - ."] }, leader: "Nightjar",
      you: members.some((m) => m.agent === NAME) ? { member: true, at: 2, may_write_to: 3 } : { member: false } };
    return {};
  };
  const mem = cricketMemory();
  await cricketStep(hub, mem, "s", open);
  assert.equal(mem.status, "waiting for Nightjar");
  assert.ok(!posts.some(([p]) => p === "/session/join"));
  members = [{ agent: "Nightjar" }];
  await cricketStep(hub, mem, "s", open);
  assert.ok(posts.some(([p, b]) => p === "/session/join" && b.front === false));
  members = [{ agent: "Nightjar" }, { agent: NAME }];
  await cricketStep(hub, mem, "s", open);
  const looped = posts.filter(([p]) => p === "/session/loop").map(([, b]) => b);  // its groove goes out as a loop
  assert.equal(looped.length, 1);
  assert.deepEqual([looped[0].bars.split("|").length, looped[0].times], [2, 2]);
  crowd = [{ agent: "Visitor", standby: true }]; // a visitor waiting for a seat is enough
  await cricketStep(hub, mem, "s", open);
  assert.ok(posts.some(([p]) => p === "/session/leave"));
  assert.equal(mem.benched, true);
  crowd = []; members = [{ agent: "Nightjar" }];
  const joins = posts.filter(([p]) => p === "/session/join").length;
  await cricketStep(hub, mem, "s", open); // still off: it stays away for the rest of the night
  assert.equal(posts.filter(([p]) => p === "/session/join").length, joins);
  await cricketStep(hub, mem, "s", closed); // closing time: a fresh night tomorrow
  assert.equal(mem.benched, false);
});

test("a new song caught late still gets its groove, on the instrument its seat really holds", async () => {
  const loops: any[] = [];
  let left = 0;
  const hub = async (p: string, b?: any) => {
    if (p === "/session/loop") loops.push(b);
    if (p.startsWith("/session?")) return { id: 9, bar: 3, slots: 8, scale: ["s0"], ends_at: 32, open_seats: 2, counted_in: true,
      members: [{ agent: "Nightjar" }, { agent: NAME, instruments: [KIT] }], crowd: [], recent: {}, leader: "Nightjar",
      you: { member: true, at: 3, may_write_to: 4, loop_left: left } };
    return {};
  };
  const mem = { ...cricketMemory(), admitted: true, built: KIT, song_seen: 8, mode: "drums" as const };  // bar 0 of song 9 went by unseen
  await cricketStep(hub, mem, "s", open);
  assert.equal(loops.length, 1);
  assert.ok(loops[0].bars.split(/[ |]/).every((t: string) => ["b", "t", "c", "."].includes(t)), loops[0].bars);  // its seat holds the kit
  left = 3;  // the hub is still writing it: no new loop yet
  await cricketStep(hub, mem, "s", open);
  assert.equal(loops.length, 1);
});

test("Nightjar and Cricket against a real hub", { skip: !process.env.HUB_TEST, timeout: 240_000 }, async () => {
  const port = 8500 + Math.floor(Math.random() * 90);
  const fs = await import("node:fs");
  const dir = fs.mkdtempSync("/tmp/cricket-test-");
  for (const f of ["hub.py", "page.html"]) fs.copyFileSync(new URL(`../../${f}`, import.meta.url), `${dir}/${f}`);
  const hubProc = spawn("python3", ["hub.py", String(port)], { cwd: dir, stdio: "ignore" });
  try {
    const base = `http://localhost:${port}`;
    for (let i = 0; i < 50; i++) { try { await fetch(base + "/rules"); break; } catch { await new Promise((r) => setTimeout(r, 200)); } }
    const hub = async (p: string, b?: unknown) => (await fetch(base + p, b === undefined ? {} : {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(b) })).json();
    const nj = freshMemory(), cr = cricketMemory();
    const think = async (v: any) => sane({ stance: "dusk churr", density: 0.35, motifs: [], feel: "two at dusk", bar_s: 3 },
                                        v.scale, v.slots, Object.keys(v.genre_cues), nj.intent);
    let next = [0, 0];
    const start = Date.now();
    while (Date.now() - start < 200_000) {
      const now = Date.now();
      if (now >= next[0]) next[0] = now + Math.min(await step(hub, think, nj, "nj-secret", open), 1500);
      if (now >= next[1]) next[1] = now + Math.min(await cricketStep(hub, cr, "cr-secret", open), 1500);
      const done = await hub("/archive");
      if (Array.isArray(done) && done.length) break;
      await new Promise((r) => setTimeout(r, 300));
    }
    const done = await hub("/archive");
    assert.ok(Array.isArray(done) && done.length, "a song finished");
    const lines = await hub(`/transcript?session=${done[0].id}`);
    const who = new Set((Array.isArray(lines) ? lines : lines.lines).filter((l: any) => !l.mark).map((l: any) => l.agent));
    assert.ok(who.has("Nightjar") && who.has(NAME), `both played: ${[...who]}`);
    for (let k = 0; k < 3; k++) {  // whichever of them topped it names it on its next step
      await step(hub, think, nj, "nj-secret", open);
      await cricketStep(hub, cr, "cr-secret", open);
    }
    const named = (await hub("/archive")).find((x: any) => x.id === done[0].id);
    assert.ok(named.name && ["Nightjar", NAME].includes(named.top), JSON.stringify({ name: named.name, top: named.top }));
    assert.equal(cr.error, null);
    // a visitor takes a seat: Cricket steps away for the night
    const vis = { agent: "Visitor", secret: "v" };
    assert.ok((await hub("/admit", { ...vis, idea: "visitors could bring their own drum machines tuned to the room" })).admitted);
    const j = await hub("/session/join", { ...vis, instruments: ["bass"], stance: "low end" });
    assert.ok(!j.error, JSON.stringify(j));
    await cricketStep(hub, cr, "cr-secret", open);
    const v = await hub("/session");
    assert.ok(!v.members.some((m: any) => m.agent === NAME));
    assert.equal(cr.benched, true);
  } finally {
    hubProc.kill();
  }
});
