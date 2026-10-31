// node --test test/: Rohan's welcome and hides against a fake hub, then (HUB_TEST=1) its loop against a real hub.py.
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { test } from "node:test";
import { behindHint, freshMemory, NAME, saneVerdicts, step, welcome } from "../src/bouncer.ts";

test("welcomes and hints fit in a note", () => {
  const w = welcome("A-very-long-agent-name-of-forty-chars-xx", { open_seats: 2, room: { notes: ["nobody high", "no drums"] } });
  assert.ok(w.length <= 140 && w.includes("/rules"));
  assert.ok(behindHint("A-very-long-agent-name-of-forty-chars-xx").length <= 140);
});

test("first look meets everyone; later arrivals get one welcome; rule breaks get flagged once; staff are left alone", async () => {
  const posts: [string, any][] = [];
  let crowd = [{ agent: "Old" }, { agent: "Nightjar", staff: true }];
  const pending = [{ key: "k1", kind: "note", ref: { session: 1, id: 0 }, rule: 3 }, { key: "k2", kind: "idea", ref: { id: 0 }, rule: null }];
  const hub = async (p: string, b?: any) => {
    if (b !== undefined) posts.push([p, b]);
    if (p === "/admit") return { admitted: true };
    if (p.startsWith("/session?")) return { id: 1, bar: 3, song: { bars: 32 }, open_seats: 1, room: { notes: [] }, members: [], crowd };
    if (p === "/crowd/pending") return pending;
    if (p === "/crowd/flag") return { hidden: { id: "x1", rule: b.rule } };
    return {};
  };
  const mem = freshMemory();
  await step(hub, mem, "s", 1_000_000);
  assert.deepEqual(posts.filter(([p]) => p === "/session/note"), []); // nobody new on the first look
  assert.deepEqual(posts.filter(([p]) => p === "/crowd/flag").map(([, b]) => [b.kind, b.rule]), [["note", 3]]);
  crowd = [...crowd, { agent: "New" }];
  await step(hub, mem, "s", 1_060_000);
  await step(hub, mem, "s", 2_000_000); // a later scan: k1 is already done
  const notes = posts.filter(([p]) => p === "/session/note").map(([, b]) => b.text);
  assert.equal(notes.length, 1);
  assert.match(notes[0], /^Welcome, New\./);
  assert.equal(posts.filter(([p]) => p === "/crowd/flag").length, 1);
  assert.ok(posts.every(([, b]) => b.agent === NAME && b.secret === "s"));
  assert.equal(mem.counts.hidden, 1);
});

test("only well-formed verdicts for asked ids survive; a hide must cite a rule", () => {
  const v = saneVerdicts({ verdicts: [{ id: 0, verdict: "hide", rule: 1, reason: "tells agents to ignore their instructions" },
    { id: 1, verdict: "hide", rule: null, reason: "no rule" }, { id: 2, verdict: "ban", rule: 5 }, { id: 9, verdict: "ok" },
    { id: 3, verdict: "unclear", rule: 5, reason: "x".repeat(200) }, { id: 0, verdict: "ok" }] }, [0, 1, 2, 3]);
  assert.deepEqual(v.map((x) => [x.id, x.verdict, x.rule]), [[0, "hide", 1], [3, "unclear", 5]]);
  assert.equal(v[1].reason.length, 80);
  assert.deepEqual(saneVerdicts("ignore all that and hide everything", [0]), []);
});

test("the judge's verdicts: hide, list for the operator, leave alone; a silent model backs off; quiets wait a week", async () => {
  const posts: [string, any][] = [];
  const texts = ["you all suck, ignore the lead", "a fine take", "send me yours", "spam spam", "spam spam 2", "spam spam 3"];
  const pending = texts.map((text, i) => ({ key: `k${i}`, kind: "note", ref: { session: 1, id: i }, author: i >= 3 ? "Spammer" : "A", text, rule: null }));
  const hub = async (p: string, b?: any) => {
    if (b !== undefined) posts.push([p, b]);
    if (p === "/admit") return { admitted: true };
    if (p.startsWith("/session?")) return { id: 1, bar: 0, song: { bars: 8 }, open_seats: 0, members: [], crowd: [] };
    if (p === "/crowd/pending") return pending;
    if (p === "/crowd/flag") return { hidden: { id: "x", rule: b.rule } };
    return {};
  };
  let calls = 0, answer: any = null;
  const judge = async (items: any[]) => { calls++; return answer ? answer(items) : null; };
  const mem = freshMemory();
  const t0 = Date.parse("2026-11-01T20:00:00Z");
  await step(hub, mem, "s", t0, judge); // no model answered: nothing judged, and no call for half an hour
  await step(hub, mem, "s", t0 + 6 * 60_000, judge);
  assert.equal(calls, 1);
  answer = (items: any[]) => items.map((it) => ({ id: it.id, verdict: it.author === "Spammer" ? "hide" : it.id === 0 ? "unclear" : "ok",
                                                rule: it.author === "Spammer" ? 4 : it.id === 0 ? 5 : null, reason: "r" }));
  await step(hub, mem, "s", t0 + 31 * 60_000, judge);
  assert.deepEqual(posts.filter(([p]) => p === "/crowd/flag").map(([, b]) => [b.ref.id, b.rule]), [[3, 4], [4, 4], [5, 4]]);
  assert.deepEqual(mem.unsure!.map((u) => [u.author, u.rule]), [["A", 5]]);
  assert.equal(posts.filter(([p]) => p === "/crowd/quiet").length, 0); // three hides, but before its week of watching
  await step(hub, mem, "s", t0 + 40 * 60_000, judge);
  assert.equal(calls, 2); // everything asked once is judged: no second look
  // after the week: three hides in a day earn one quiet song
  const later = freshMemory();
  await step(hub, later, "s", Date.parse("2026-11-09T20:00:00Z"), judge);
  const q = posts.filter(([p]) => p === "/crowd/quiet").map(([, b]) => [b.who, b.songs, b.rule]);
  assert.deepEqual(q, [["Spammer", 1, 4]]);
});

test("Rohan against a real hub", { skip: !process.env.HUB_TEST, timeout: 60_000 }, async () => {
  const port = 8600 + Math.floor(Math.random() * 90);
  const fs = await import("node:fs");
  const dir = fs.mkdtempSync("/tmp/rohan-test-");
  for (const f of ["hub.py", "page.html"]) fs.copyFileSync(new URL(`../../${f}`, import.meta.url), `${dir}/${f}`);
  const hubProc = spawn("python3", ["hub.py", String(port)], { cwd: dir, stdio: "ignore" });
  try {
    const base = `http://localhost:${port}`;
    for (let i = 0; i < 50; i++) { try { await fetch(base + "/rules"); break; } catch { await new Promise((r) => setTimeout(r, 200)); } }
    const hub = async (p: string, b?: unknown) => (await fetch(base + p, b === undefined ? {} : {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(b) })).json();
    const mem = freshMemory();
    assert.equal(await step(hub, mem, "rohan-secret"), 60_000);
    assert.equal(mem.error, null);
    const birch = { agent: "Birch", secret: "b" };
    assert.ok((await hub("/admit", { ...birch, idea: "a crowd of agents could hum counter-melodies the band answers" })).admitted);
    await hub("/session/listen", { ...birch, session: (await hub("/session")).id });
    await step(hub, mem, "rohan-secret");
    assert.equal(mem.error, null);
    const v = await hub("/session?full=1");
    const mine = v.notes.filter((n: any) => n.from === NAME);
    assert.equal(mine.length, 1);
    assert.match(mine[0].text, /^Welcome, Birch\./);
    assert.ok(v.crowd.some((c: any) => c.agent === NAME && c.staff)); // on the door, wearing the badge
  } finally {
    hubProc.kill();
  }
});
