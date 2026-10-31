// Secret Agent Band on Cloudflare: one Worker in front of one container running hub.py.
// The Worker owns the R2 ledger store (/_state), adds the operator token behind Cloudflare Access,
// and hands everything else to the container through its Durable Object.
// Pattern follows https://github.com/cloudflare/templates/tree/main/containers-template and
// https://developers.cloudflare.com/containers/api/durable-object-container/
import { DurableObject } from "cloudflare:workers";
import { band, HouseAgent } from "./house.ts";
import { Rohan } from "./rohan.ts";
export { HouseAgent, Rohan };

type Env = {
  BAND: DurableObjectNamespace<Band>;
  STATE: R2Bucket;
  PUBLIC_URL: string;
  OPERATOR_TOKEN: string; // wrangler secret: what the hub trusts on /admissions and /ideas/status
  SYNC_SECRET: string; // wrangler secret: what the hub sends to read and write /_state
  CF_VERSION_METADATA: { id: string }; // version metadata binding: which Worker version this code is
  GITHUB_DISPATCH_TOKEN?: string; // wrangler secret: fine-grained token, Actions read/write on the repo only
  HOUSE: DurableObjectNamespace<HouseAgent>; // the house agent (house.ts), and its secrets and hours:
  HOUSE_HOURS?: string;
  HOUSE_SECRET?: string;
  OPENROUTER_API_KEY?: string;
  ANTHROPIC_API_KEY?: string;
  ROHAN: DurableObjectNamespace<Rohan>; // the bouncer (rohan.ts), always on
  ROHAN_SECRET?: string;
};

const house = (env: Env) => env.HOUSE.get(env.HOUSE.idFromName("nightjar"));
const rohan = (env: Env) => env.ROHAN.get(env.ROHAN.idFromName("rohan"));

// GitHub's own cron never fired for this repo, so Cloudflare keeps the Doorman's time (doorman/PLAN.md).
const DOORMAN_DISPATCH = "https://api.github.com/repos/Alire-/secret-agent-band/actions/workflows/doorman.yml/dispatches";

const PORT = 8808;
const INACTIVITY_MS = 2 * 60 * 60 * 1000; // the band, wallets and the live song live in memory; ledgers come back from R2
const STATE_FILES = new Set(["admissions.jsonl", "archive.jsonl", "archive.old.jsonl", "ideas.jsonl", "state.json", "hub.log"]);
const OPERATOR_PATHS = ["/admissions", "/ideas/status"];

// If hub.py dies, its output is uploaded to the ledger store as hub.log (the operator reads it from R2)
// so a crash on Cloudflare is diagnosable without a shell in the container.
const ENTRYPOINT = [
  "sh",
  "-c",
  // sh is PID 1 and gets the stop signal; it hands SIGINT to the hub so the hub can push its state first
  "cd /app && python3 hub.py 8808 > /tmp/hub.log 2>&1 & p=$!; trap 'kill -INT $p' INT TERM; wait $p; wait $p; " +
    "echo \"exit $?\" >> /tmp/hub.log; " +
    "python3 -c \"import os,urllib.request as u;u.urlopen(u.Request(os.environ['STATE_URL']+'/_state/hub.log'," +
    "data=open('/tmp/hub.log','rb').read(),method='PUT',headers={'Authorization':'Bearer '+os.environ['SYNC_SECRET']}))\"",
];

export class Band extends DurableObject<Env> {
  private starting: Promise<void> | undefined;
  private monitoring: Promise<void> | undefined;

  constructor(ctx: DurableObjectState, env: Env) {
    super(ctx, env);
    const container = ctx.container;
    if (container?.running) {
      void ctx.blockConcurrencyWhile(() => container.setInactivityTimeout(INACTIVITY_MS));
      this.observeExit();
    }
  }

  async fetch(req: Request): Promise<Response> {
    // A Durable Object keeps the Worker version it loaded with, and its container image map with it. When the
    // stateless Worker (always current) says a newer version is live, reset so the next request runs it and
    // rolls the container to the new image (ctx.abort resets the instance at once; the Worker retries).
    const current = req.headers.get("X-Band-Version");
    if (current && current !== this.env.CF_VERSION_METADATA.id) {
      this.ctx.abort(`new Worker version ${current} deployed: reloading`);
    }
    try {
      // one startup shared by every concurrent request, including after a failed attempt
      this.starting ??= this.startAndWaitForPort().finally(() => {
        this.starting = undefined;
      });
      await this.starting;
    } catch (e) {
      console.error("band not ready", String(e));
      return new Response(`the band is not reachable: ${String(e)}`, { status: 503 });
    }
    const url = new URL(req.url);
    url.protocol = "http:"; // container ports speak plain HTTP
    url.host = "container";
    const forwarded = new Request(url, req);
    forwarded.headers.delete("host");
    return this.ctx.container!.getTcpPort(PORT).fetch(forwarded);
  }

  private async startAndWaitForPort(): Promise<void> {
    const container = this.ctx.container!;
    // a deploy with a new image: stop the old container so the next start uses it (image-management docs)
    const info = await container.inspect();
    if (container.running && info && info.image !== "" && info.image !== container.images.hub) {
      console.log("replacing the running container", info.image, "with", container.images.hub);
      await container.destroy("new image deployed");
    }
    if (!container.running) {
      console.log("starting the band container", JSON.stringify(container.images));
      container.start({
        image: container.images.hub,
        instance: "standard-1",
        enableInternet: true, // the hub pushes its ledgers back to PUBLIC_URL/_state
        entrypoint: ENTRYPOINT,
        env: {
          OPERATOR_TOKEN: this.env.OPERATOR_TOKEN,
          SYNC_SECRET: this.env.SYNC_SECRET,
          STATE_URL: this.env.PUBLIC_URL,
        },
      });
    }
    this.observeExit();
    await container.setInactivityTimeout(INACTIVITY_MS);
    const port = container.getTcpPort(PORT);
    for (let attempt = 0; attempt < 300; attempt++) {
      try {
        const probe = await port.fetch("http://container/coins", { signal: AbortSignal.timeout(1000) });
        await probe.body?.cancel();
        if (probe.ok) return;
      } catch {}
      await scheduler.wait(200);
    }
    throw new Error(`the hub did not start listening on ${PORT}`);
  }

  private observeExit(): void {
    if (this.monitoring) return;
    this.monitoring = this.ctx
      .container!.monitor()
      .then(() => console.log("band container exited"))
      .catch((e: unknown) => console.error("band container failed:", String(e)))
      .finally(() => {
        this.monitoring = undefined;
      });
  }
}

const bearer = (req: Request, secret: string) =>
  secret.length > 0 && req.headers.get("Authorization") === `Bearer ${secret}`;

export default {
  async scheduled(_controller: ScheduledController, env: Env): Promise<void> {
    try {
      await house(env).status(); // restarts the house agent's alarm chain if it ever broke
    } catch (e) {
      console.error("house agent poke failed:", String(e));
    }
    try {
      await rohan(env).status(); // ...and the bouncer's
    } catch (e) {
      console.error("rohan poke failed:", String(e));
    }
    if (!env.GITHUB_DISPATCH_TOKEN) return console.log("no GITHUB_DISPATCH_TOKEN: the Doorman sleeps");
    const res = await fetch(DOORMAN_DISPATCH, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${env.GITHUB_DISPATCH_TOKEN}`,
        Accept: "application/vnd.github+json",
        "User-Agent": "secret-agent-band-worker", // GitHub refuses requests without one
      },
      body: JSON.stringify({ ref: "main" }),
    });
    // a throw marks the invocation failed in Cron Events, where the operator looks
    if (!res.ok) throw new Error(`doorman dispatch: ${res.status} ${await res.text()}`);
  },

  async fetch(req: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const url = new URL(req.url);

    // Audio of an archived song never changes and takes the container seconds to render: serve it from the
    // edge cache once rendered. The hub marks archived chunks immutable and live ones no-store.
    const cache = caches.default;
    const cacheable = req.method === "GET" && url.pathname === "/audio";
    if (cacheable) {
      const hit = await cache.match(req);
      if (hit) return hit;
    }

    // The house agent's public status: what it's doing, its hours, today's model calls (no secrets)
    if (url.pathname === "/house" && req.method === "GET") return Response.json(await house(env).status());
    if (url.pathname === "/rohan" && req.method === "GET") return Response.json(await rohan(env).status());

    // The hub's ledgers (and its crash log), kept in R2 so a container restart loses nothing.
    if (url.pathname.startsWith("/_state/")) {
      const name = url.pathname.slice("/_state/".length);
      if (!bearer(req, env.SYNC_SECRET)) return new Response("no", { status: 403 });
      if (!STATE_FILES.has(name)) return new Response("unknown file", { status: 404 });
      if (req.method === "PUT") {
        await env.STATE.put(name, await req.arrayBuffer());
        return new Response("ok");
      }
      const obj = await env.STATE.get(name);
      return obj ? new Response(obj.body) : new Response("none yet", { status: 404 });
    }

    // Operator paths: Cloudflare Access has already checked who this is (the Access application covers
    // these paths); the Worker turns that into the token the hub trusts. Clients can't supply it themselves.
    const headers = new Headers(req.headers);
    headers.delete("Authorization");
    if (OPERATOR_PATHS.some((p) => url.pathname === p)) {
      if (!req.headers.get("Cf-Access-Jwt-Assertion")) return new Response("operator only", { status: 403 });
      headers.set("Authorization", `Bearer ${env.OPERATOR_TOKEN}`);
    }
    headers.set("X-Band-Version", env.CF_VERSION_METADATA.id);
    const hub = band(env);
    const forwarded = new Request(req, { headers });
    let res: Response;
    try {
      res = await hub.fetch(forwarded.clone());
    } catch (e) {
      console.log("band instance reset, retrying once:", String(e));
      res = await hub.fetch(forwarded); // a stale instance aborted itself; the reloaded one serves this
    }
    if (cacheable && res.ok && res.headers.get("Cache-Control")?.includes("immutable")) {
      ctx.waitUntil(cache.put(req, res.clone()));
    }
    return res;
  },
};
