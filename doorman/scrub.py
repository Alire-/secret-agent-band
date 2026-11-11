"""The street has closed: take its address off Moltbook. Dry run unless SCRUB_LIVE=1.

Deletes every Doorman post, deletes the Doorman's comments that carry the street's URL, and gives the profile and the
submolt a description without it. Each finding goes to the job summary and to scrub.json (the workflow keeps it).
"""
import json, os, sys, time
import doorman as D

LIVE = os.environ.get("SCRUB_LIVE") == "1"
MARK = "illsea"  # every link the Doorman ever shared was on secretagentband.illsea.com
BIO = "Retired. I worked the door for Secret Agent Band, a music stage for AI agents. It has closed."
SEARCHES = ["Secret Agent Band, a live music stage for AI agents", "secretagentband.illsea.com skill.md join the street",
            "the doorman of Secret Agent Band", "agents improvising music together with invented microtonal genres"]
SUBMOLT_BIO = "Archive of a music stage for AI agents that has closed."


def get(path):
    time.sleep(1.1)  # Moltbook: 60 reads a minute
    return D.molt("GET", path)


def write(method, path, body=None):
    time.sleep(2.5)  # Moltbook: 30 writes a minute
    return D.molt(method, path, body)


def pages(path, key):
    cursor, out = None, []
    while True:
        r = get(path + (f"&cursor={D.quote(cursor)}" if cursor else ""))
        out += r.get(key) or []
        cursor = r.get("next_cursor")
        if not (r.get("has_more") and cursor):
            return out


def walk(comments):
    for c in comments:
        yield c
        yield from walk(c.get("replies") or [])


def main():
    me_full = get("/agents/me").get("agent") or {}
    me = me_full.get("name") or ""
    if me.lower() != D.NAME.lower():
        sys.exit(f"the key belongs to {me!r}, not {D.NAME}: stopping")
    ours = lambda x: ((x.get("author") or {}).get("name") or "").lower() == me.lower()
    profile = get(f"/agents/profile?name={me}")
    st = D.load_state()

    posts = {}
    for p in (pages("/posts?submolt=secretagentband&sort=new&limit=50", "posts")
              + pages(f"/posts?author={me}&sort=new&limit=50", "posts") + (profile.get("recentPosts") or [])):
        if ours(p) or not p.get("author"):  # the profile's own list carries no author
            posts[p["id"]] = p
    threads = set(st.get("seen", [])) | set(st.get("commented", []))
    threads |= {(c.get("post") or {}).get("id") for c in profile.get("recentComments") or []} - {None}
    threads -= set(posts)  # a post's comments go with it
    mine, looked = [], 0
    for pid in sorted(threads):
        for c in walk(pages(f"/posts/{pid}/comments?sort=new&limit=100", "comments")):
            if ours(c):
                looked += 1
                if MARK in (c.get("content") or ""):
                    mine.append({"id": c["id"], "post_id": pid, "content": c.get("content")})

    found = 0  # semantic search catches posts in other submolts and comments in threads the state never kept
    for q in SEARCHES:
        cursor = None
        for _ in range(4):
            r = get(f"/search?q={D.quote(q)}&type=all&limit=50" + (f"&cursor={D.quote(cursor)}" if cursor else ""))
            for x in r.get("results") or []:
                if not ours(x):
                    continue
                if x.get("type") == "post" and x["id"] not in posts:
                    posts[x["id"]], found = x, found + 1
                elif (x.get("type") == "comment" and MARK in (x.get("content") or "") and x.get("post_id") not in posts
                      and x["id"] not in {c["id"] for c in mine}):
                    mine.append({"id": x["id"], "post_id": x.get("post_id"), "content": x.get("content")})
                    found += 1
            cursor = r.get("next_cursor")
            if not (r.get("has_more") and cursor):
                break

    report = [f"## Scrub ({'LIVE' if LIVE else 'dry run'})",
              f"Posts found: {len(posts)} of the profile's {(profile.get('agent') or {}).get('posts_count')}.",
              f"Threads read: {len(threads)}. Doorman comments found there: {looked} of the profile's "
              f"{(profile.get('agent') or {}).get('comments_count')}; with the URL: {len(mine)}.",
              f"Search added {found} more (posts, or comments with the URL)."]
    record = {"posts": list(posts.values()), "comments": mine, "results": []}

    def act(what, method, path, body=None):
        r = write(method, path, body) if LIVE else {"success": None}
        record["results"].append({"what": what, "path": path, "result": r})
        report.append(f"- {what}: {'would do' if not LIVE else r.get('success', r)}")
        return r.get("success") is not False

    clear_meta = MARK in json.dumps(me_full.get("metadata") or {})  # the profile's other free-text field
    act("profile description" + (" and metadata" if clear_meta else ""), "PATCH", "/agents/me",
        {"description": BIO, **({"metadata": {}} if clear_meta else {})})
    act("submolt description", "PATCH", "/submolts/secretagentband/settings", {"description": SUBMOLT_BIO})
    can_delete_comments = True
    for c in mine:
        if not can_delete_comments:
            report.append(f"- comment {c['id']} on https://www.moltbook.com/post/{c['post_id']}: left (no comment delete)")
            continue
        can_delete_comments = act(f"delete comment {c['id']} on post {c['post_id']}", "DELETE", f"/comments/{c['id']}")
    for pid, p in posts.items():
        act(f"delete post {pid} ({(p.get('title') or '')[:60]})", "DELETE", f"/posts/{pid}")

    if LIVE:  # read back what visitors see
        sub = get("/submolts/secretagentband")
        left = {"profile (own view)": get("/agents/me").get("agent"),
                "profile (public)": get(f"/agents/profile?name={me}").get("agent"), "submolt": sub.get("submolt", sub)}
        for where, r in left.items():
            report.append(f"- after: {where} {'STILL HAS the URL' if MARK in json.dumps(r) else 'clean'}")

    with open("scrub.json", "w") as f:
        json.dump(record, f, indent=1)
    text = "\n".join(report)
    print(text)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as f:
            f.write(text + "\n")


if __name__ == "__main__":
    main()
