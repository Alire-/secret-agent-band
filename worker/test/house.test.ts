// node --test test/  (node 22.18+/24 runs .ts directly). The house agent's hands and hours, then its whole loop
// against a real hub: HUB_TEST=1 starts ../hub.py on a free port and plays a short song through player.ts step().
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { test } from "node:test";
import { DEFAULT_INTENT, isOpen, nextOpen, play, shift, usable } from "../src/improviser.ts";
import { freshMemory, genreSpec, NAME, sane, step, workshop } from "../src/player.ts";

const DRIFT = ["s0", "s1", "s2", "s3", "s4", "s5", "s6", "s7", "s8"];

test("bars are always exactly one bar of the genre's slots, in its tokens", () => {
  for (let seed = 1; seed < 200; seed++) {
    const intent = { ...DEFAULT_INTENT, density: (seed % 9) / 10, register: (["low", "mid", "high"] as const)[seed % 3],
                     motifs: ["s0 - - - . . s4 . . . . . s2 - . ."] };
    for (const bar of play(2, DRIFT, 16, intent, seed)) {
      assert.ok(usable(bar, DRIFT, 16), `seed ${seed}: ${bar}`);
      assert.ok(bar.split(" ").some((t) => t !== "." && t !== "-"), "never an empty bar");
    }
  }
});

test("an answer keeps the other player's rhythm but moves its notes: not a copy", () => {
  const theirs = "s0 . s2 . s4 - . . s6 . . . s8 . . .";
  const [ans] = play(1, DRIFT, 16, { ...DEFAULT_INTENT, density: 0.9, register: "mid" }, 7, theirs);
  assert.notEqual(ans, theirs);
  assert.equal(shift("s0 . s8 -", DRIFT, 1), "s1 . s0 -");
});

test("a model's intent is clamped: bad motifs, long stances, unknown cues and wild numbers are dropped", () => {
  const x = sane({ stance: "x".repeat(60), front: "yes", register: "loud", density: 7, motifs: ["s0 s1", "nope", "s0 . . . . . . . . . . . . . . ."],
                   cue: "explode", bar_s: 99 }, DRIFT, 16, ["thin", "bloom"], DEFAULT_INTENT);
  assert.equal(x.stance.length, 24);
  assert.deepEqual([x.front, x.register, x.density, x.cue, x.bar_s], [false, "low", 0.9, null, 12]);
  assert.deepEqual(x.motifs, ["s0 . . . . . . . . . . . . . . ."]);
});

test("business hours: 5 PM to 1 AM Pacific, across midnight and daylight saving", () => {
  const pt = (iso: string) => Date.parse(iso); // UTC instants
  assert.equal(isOpen(pt("2026-10-31T00:30:00Z"), 17, 1), true);   // 17:30 PDT
  assert.equal(isOpen(pt("2026-10-31T07:30:00Z"), 17, 1), true);   // 00:30 PDT
  assert.equal(isOpen(pt("2026-10-31T08:30:00Z"), 17, 1), false);  // 01:30 PDT
  assert.equal(isOpen(pt("2026-12-01T01:30:00Z"), 17, 1), true);   // 17:30 PST
  assert.equal(nextOpen(pt("2026-10-31T09:00:00Z"), 17, 1), pt("2026-11-01T00:00:00Z"));  // 02:00 PDT -> 17:00 PDT
});

test("a seeded genre always passes the hub's rules (checked there), and is never a taken name", () => {
  const a = genreSpec(42, []), b = genreSpec(42, [a.name]);
  assert.notEqual(a.name, b.name);
  assert.equal(a.form.every((t: string) => /^n\d+$/.test(t)), true);
});

test("the whole loop against a real hub", { skip: !process.env.HUB_TEST, timeout: 200_000 }, async () => {
  const port = 8700 + Math.floor(Math.random() * 90);
  const dir = (await import("node:fs")).mkdtempSync("/tmp/house-test-");
  for (const f of ["hub.py", "page.html"]) (await import("node:fs")).copyFileSync(new URL(`../../${f}`, import.meta.url), `${dir}/${f}`);
  const hubProc = spawn("python3", ["hub.py", String(port)], { cwd: dir, stdio: "ignore" });
  try {
    const base = `http://localhost:${port}`;
    for (let i = 0; i < 50; i++) { try { await fetch(base + "/coins"); break; } catch { await new Promise((r) => setTimeout(r, 200)); } }
    const hub = async (p: string, b?: unknown) => (await fetch(base + p, b === undefined ? {} : {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(b) })).json();
    const mem = freshMemory();
    let thoughts = 0;
    const think = async (v: any) => { thoughts++; return sane({ stance: "dusk churr", front: true, register: "low", density: 0.3,
      motifs: ["s0 - - - . . s4 . . . . . s2 - . ."], feel: "a porch light coming on", bar_s: 3 }, v.scale, v.slots, Object.keys(v.genre_cues), mem.intent); };
    const open = { open: 0, close: 24 };
    // the workshop: a model's genre the hub refuses (the seed's stands in) and a model's instrument it takes
    assert.ok((await hub("/admit", { agent: NAME, secret: "test-secret", idea: "a test idea about house hours for heartbeats" })).admitted);
    mem.admitted = true;
    const made = await workshop(hub, async () => ({ genre: { name: "bad maths", scale: { count: 3, cents: "import os" } },
      instrument: { name: "test moth", partials: [[1, 1], [2.7, 0.4]], decay: 1 } }), mem, "test-secret");
    assert.equal(made.length, 2, JSON.stringify([made, mem.error]));
    assert.match(mem.error || "", /genre design refused/);
    assert.ok(made.includes("instrument: test moth"));
    const premiere = mem.premiere;
    assert.ok(premiere && premiere.startsWith("nightjar "));
    mem.error = null;
    let errors: string[] = [];
    const start = Date.now();
    while (Date.now() - start < 150_000) {  // the house song is 24 bars; at 3 s a bar, real time, that's ~80 s
      const sleep = await step(hub, think, mem, "test-secret", open);
      if (mem.error) { errors.push(mem.error); mem.error = null; }
      const v = await hub(`/archive`);
      if (Array.isArray(v) && v.length) break;
      await new Promise((r) => setTimeout(r, Math.min(sleep, 1500)));
    }
    const done = await hub("/archive");
    assert.ok(Array.isArray(done) && done.length, "a song finished");
    const song = await hub(`/archive/${done[0].id}`);
    const lines = await hub(`/transcript?session=${done[0].id}`);
    const mine = (Array.isArray(lines) ? lines : lines.lines).filter((l: any) => l.agent === NAME && !l.mark);
    assert.ok(mine.length >= 12, `it played its own bars (${mine.length})`);
    assert.equal(song.song.feel, "a porch light coming on"); // it led, and named the feel
    assert.equal(song.song.genre, premiere); // ...in the genre it built that morning
    assert.deepEqual(errors, []);
    assert.ok(thoughts >= 1);
    // closing time: it leaves the stage
    await step(hub, think, mem, "test-secret", { open: 3, close: 3 });
    const after = await hub(`/session?agent=${NAME}`);
    assert.equal(after.you.member, false);
  } finally {
    hubProc.kill();
  }
});
