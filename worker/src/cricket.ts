// Cricket on Cloudflare: one Durable Object, woken by its own alarm about twice a bar during Nightjar's hours. Each
// wake-up is one companion.ts step. Its secret on the street is derived from Nightjar's (HMAC of HOUSE_SECRET), so
// there is no secret of its own to set. The Worker's cron pokes it every half hour so a broken alarm chain restarts.
import { DurableObject } from "cloudflare:workers";
import { freshMemory, type Memory, NAME, step } from "./companion.ts";
import { hubCall, type HouseEnv } from "./house.ts";

async function derived(secret: string): Promise<string> {
  const key = await crypto.subtle.importKey("raw", new TextEncoder().encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const mac = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode("cricket"));
  return [...new Uint8Array(mac)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

export class Cricket extends DurableObject<HouseEnv> {
  private hours() {
    const [open, close] = (this.env.HOUSE_HOURS || "17-1").split("-").map(Number);
    return { open, close };
  }

  /** The cron and GET /cricket call this: make sure an alarm is set, and report how it's doing. */
  async status(): Promise<Record<string, unknown>> {
    const alarm = await this.ctx.storage.getAlarm();
    if (!alarm || alarm > Date.now() + 31 * 60_000) await this.ctx.storage.setAlarm(Date.now() + 1000);
    const mem = (await this.ctx.storage.get<Memory>("memory")) || freshMemory();
    return { agent: NAME, hours: this.env.HOUSE_HOURS || "17-1", time_zone: "America/Los_Angeles", status: mem.status,
             mode: mem.mode, benched_tonight: mem.benched, last_error: mem.error, next_wake: await this.ctx.storage.getAlarm(),
             configured: { secret: !!this.env.HOUSE_SECRET } };
  }

  async alarm(): Promise<void> {
    const mem = (await this.ctx.storage.get<Memory>("memory")) || freshMemory();
    let sleep = 30_000;
    if (!this.env.HOUSE_SECRET) {
      mem.status = "no HOUSE_SECRET set: not playing";
      sleep = 30 * 60_000;
    } else {
      try {
        sleep = await step((p, b) => hubCall(this.env, p, b), mem, await derived(this.env.HOUSE_SECRET), this.hours());
      } catch (e) {
        mem.error = String(e).slice(0, 300);
        console.error("cricket step failed:", mem.error);
      }
    }
    await this.ctx.storage.put("memory", mem);
    await this.ctx.storage.setAlarm(Date.now() + sleep); // never throw: the next wake-up is the retry
  }
}
