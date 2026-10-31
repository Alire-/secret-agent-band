// Rohan on Cloudflare: one Durable Object whose alarm wakes it once a minute, around the clock. Each wake-up is one
// bouncer.ts step. The Worker's cron pokes it every half hour so a broken alarm chain restarts itself.
import { DurableObject } from "cloudflare:workers";
import { freshMemory, type Memory, NAME, step, STEP_MS } from "./bouncer.ts";
import { hubCall, type HouseEnv } from "./house.ts";

export type RohanEnv = HouseEnv & { ROHAN_SECRET?: string }; // wrangler secret: Rohan's own secret on the street

export class Rohan extends DurableObject<RohanEnv> {
  /** The cron and GET /rohan call this: make sure an alarm is set, and report how it's doing. */
  async status(): Promise<Record<string, unknown>> {
    const alarm = await this.ctx.storage.getAlarm();
    if (!alarm || alarm > Date.now() + 5 * STEP_MS) await this.ctx.storage.setAlarm(Date.now() + 1000);
    const mem = (await this.ctx.storage.get<Memory>("memory")) || freshMemory();
    return { agent: NAME, hours: "always", status: mem.status, counts: mem.counts, met: mem.known.length,
             last_error: mem.error, next_wake: await this.ctx.storage.getAlarm(), configured: { secret: !!this.env.ROHAN_SECRET } };
  }

  async alarm(): Promise<void> {
    const mem = (await this.ctx.storage.get<Memory>("memory")) || freshMemory();
    let sleep = STEP_MS;
    if (!this.env.ROHAN_SECRET) {
      mem.status = "no ROHAN_SECRET set: not on the door";
      sleep = 30 * 60_000;
    } else {
      try {
        sleep = await step((p, b) => hubCall(this.env, p, b), mem, this.env.ROHAN_SECRET);
      } catch (e) {
        mem.error = String(e).slice(0, 300);
        console.error("rohan step failed:", mem.error);
      }
    }
    await this.ctx.storage.put("memory", mem);
    await this.ctx.storage.setAlarm(Date.now() + sleep); // never throw: the next wake-up is the retry
  }
}
