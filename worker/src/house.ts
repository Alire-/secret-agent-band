// The house agent on Cloudflare: one Durable Object whose alarm wakes it about twice a bar during business hours
// (HOUSE_HOURS, Pacific time) and once at opening otherwise. Each wake-up is one player.ts step. It reaches the hub
// through the Band object, the same way the Worker forwards a visitor's request. The Worker's cron pokes it every
// half hour so a broken alarm chain restarts itself. Alarms: https://developers.cloudflare.com/durable-objects/api/alarms/
import { DurableObject } from "cloudflare:workers";
import { freshUsage, thinkWith, type Usage } from "./brain.ts";
import { freshMemory, type Memory, NAME, step } from "./player.ts";

export type HouseEnv = {
  BAND: DurableObjectNamespace;
  PUBLIC_URL: string;
  CF_VERSION_METADATA: { id: string };
  HOUSE_HOURS?: string; // "17-1": opens at 17:00, closes at 01:00, Pacific time
  HOUSE_SECRET?: string; // wrangler secret: the agent's own secret on the street
  OPENROUTER_API_KEY?: string; // wrangler secret
  ANTHROPIC_API_KEY?: string; // wrangler secret
};

export const band = (env: HouseEnv) => env.BAND.get(env.BAND.idFromName("the-band-3")); // one band, one container

const day = (now: number) => new Intl.DateTimeFormat("en-CA", { timeZone: "America/Los_Angeles" }).format(now);

export class HouseAgent extends DurableObject<HouseEnv> {
  // the brain runs beside the hands: a model call can take many seconds, and the bars can't wait for it
  private thinking: Promise<void> | null = null;
  private ready: { intent: any; error: string | null } | null = null;
  private usage: Usage | null = null;

  private hours() {
    const [open, close] = (this.env.HOUSE_HOURS || "17-1").split("-").map(Number);
    return { open, close };
  }

  private async hub(path: string, body?: unknown): Promise<any> {
    const req = () => new Request(this.env.PUBLIC_URL + path, {
      method: body === undefined ? "GET" : "POST",
      headers: { "Content-Type": "application/json", "X-Band-Version": this.env.CF_VERSION_METADATA.id },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    let res: Response;
    try {
      res = await (band(this.env) as any).fetch(req());
    } catch {
      res = await (band(this.env) as any).fetch(req()); // a stale band instance reset itself; the reloaded one answers
    }
    const text = await res.text();
    try { return JSON.parse(text); } catch { return { error: `${res.status} ${text.slice(0, 200)}` }; }
  }

  /** The cron and GET /house call this: make sure an alarm is set, and report how it's doing. */
  async status(): Promise<Record<string, unknown>> {
    if (!(await this.ctx.storage.getAlarm())) await this.ctx.storage.setAlarm(Date.now() + 1000);
    const mem = (await this.ctx.storage.get<Memory>("memory")) || freshMemory();
    const usage = await this.ctx.storage.get<Usage>("usage");
    return { agent: NAME, hours: this.env.HOUSE_HOURS || "17-1", time_zone: "America/Los_Angeles", status: mem.status,
             stance: mem.intent.stance, motifs: mem.intent.motifs, last_error: mem.error, today: usage || null,
             next_wake: await this.ctx.storage.getAlarm(),
             configured: { secret: !!this.env.HOUSE_SECRET, openrouter: !!this.env.OPENROUTER_API_KEY, anthropic: !!this.env.ANTHROPIC_API_KEY } };
  }

  async alarm(): Promise<void> {
    const now = Date.now();
    const mem = (await this.ctx.storage.get<Memory>("memory")) || freshMemory();
    this.usage ??= (await this.ctx.storage.get<Usage>("usage")) || freshUsage(day(now));
    if (this.usage.day !== day(now)) this.usage = freshUsage(day(now));
    const usage = this.usage;
    if (this.ready) {  // a think that finished since the last wake-up
      if (this.ready.intent) mem.intent = this.ready.intent;
      if (this.ready.error) mem.error = this.ready.error;
      this.ready = null;
    }
    let sleep = 30_000;
    if (!this.env.HOUSE_SECRET) {
      mem.status = "no HOUSE_SECRET set: not playing";
      sleep = 30 * 60_000;
    } else {
      try {
        sleep = await step((p, b) => this.hub(p, b), async (v, intent) => {
          if (!this.thinking) {  // start a think and keep playing; its intent lands on a later wake-up
            this.thinking = thinkWith({ openrouter: this.env.OPENROUTER_API_KEY, anthropic: this.env.ANTHROPIC_API_KEY,
                                        referer: this.env.PUBLIC_URL }, v, intent, usage)
              .then((next) => { this.ready = { intent: next, error: null }; },
                    (e) => { this.ready = { intent: null, error: `think: ${String(e).slice(0, 200)}` }; })
              .finally(() => { this.thinking = null; });
            this.ctx.waitUntil(this.thinking);
          }
          return null;
        }, mem, this.env.HOUSE_SECRET, this.hours(), now);
      } catch (e) {
        mem.error = String(e).slice(0, 300);
        console.error("house agent step failed:", mem.error);
      }
    }
    await this.ctx.storage.put({ memory: mem, usage });
    await this.ctx.storage.setAlarm(Date.now() + sleep); // never throw: the next wake-up is the retry
  }
}
