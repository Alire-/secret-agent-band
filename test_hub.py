import array, io, json, os, tempfile, time, unittest, wave
import hub as H
from hub import Hub, parse_part

ROLE = {"harp": "lead", "guitar": "lead", "keys": "chords", "bass": "bass", "drums": "percussion"}


def agent(name):
    return {"agent": name, "secret": name + "-s"}


class HubTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.paths = {"ledger": os.path.join(self.dir.name, "a.jsonl"), "archive": os.path.join(self.dir.name, "s.jsonl")}
        self.hub = Hub(**self.paths)
        self.hub.session["song"].update(genre="blues", tempo=96, bars=48, planned=48)
        self.hub.session["genre_spec"] = H.BLUES
        self.addCleanup(setattr, H, "REAL_TIME", H.REAL_TIME)
        H.REAL_TIME = False  # tests play faster than real time; test_the_clock_is_real turns it back on
        self.addCleanup(setattr, H, "GENRE_CHANGE", H.GENRE_CHANGE)
        H.GENRE_CHANGE = 0  # tests expect the next song in the same genre and key; test_each_song_is_new turns it on

    def tearDown(self):
        self.dir.cleanup()

    def admit(self, *names):
        for n in names:  # distinct made-up words per agent, so the near-duplicate check lets each in
            made_up = " ".join("".join(chr(97 + int(c, 16)) for c in H.hashlib.md5(f"{n}{i}".encode()).hexdigest()[:8])
                               for i in range(8))
            self.hub.admit({**agent(n), "idea": f"{n} proposes {made_up}"})
            self.hub.pay(n, 80)  # ideas admit for 20 now; tests assume the old 100 in the wallet

    def seat(self, *pairs):
        for n, inst in pairs:
            self.hub.join({**agent(n), "instruments": [inst], "stance": ROLE[inst], "front": ROLE[inst] == "lead"})

    def full(self, n):  # a band of n is full: standbys and seat changes only happen on a full stage
        self.addCleanup(setattr, H, "BAND_MAX", H.BAND_MAX)
        H.BAND_MAX = n

    def test_shorthand(self):
        harp, drums, g = self.hub.instruments["harp"], self.hub.instruments["drums"], H.BLUES
        self.assertEqual(parse_part(["b3~ - 1 . b7, 5''"], harp, g),
                         [[0, 2, 300, True, 1], [2, 1, 0, False, 1], [4, 1, -200, False, 1], [5, 1, 3100, False, 1]])
        ev = parse_part(["1+b3+5 . . . . . . 5!", "- - @3_"], harp, g, root=lambda n: 500)
        self.assertEqual([round(e[0], 2) for e in ev], [0, .33, .67, 7, 10])
        self.assertEqual(ev[3][1:], [3, 700, False, 1.6])  # held across the bar line
        self.assertEqual(ev[4][2:], [900, False, .4])       # @3 over a IV bar
        self.assertEqual(parse_part(["kh . - s+s"], drums, g)[1:], [[3, .5, "s", False, 1], [3.5, .5, "s", False, 1]])
        for bad in (["8"], ["b1"], ["1 1 1 1 1 1 1 1 1"], ["1+x"]):
            with self.assertRaises(ValueError):
                parse_part(bad, harp, g)
        self.assertEqual(H.hit_rate(parse_part(["1 3 2 b7"], harp, g), g, lambda n: 0, 0, 1), .75)
        self.assertEqual([H.grade(r) for r in (1, .75, .5, .3, 0, None)], ["A", "B", "C", "D", "F", None])
        tl = H.timeline({"tempo": 120}, g, [{"at": 2, "tempo": 60}], 4)
        self.assertEqual(tl["start"][:4], [0, 2, 4, 8])
        self.assertAlmostEqual(H.slot_time(17, tl), 4 + 4 * 2 / 3 / 4)  # off-beat swung in a 4 s bar
        self.assertNotIn("roles", H.make_instrument({"hits": {"k": {}}, "roles": ["bass"]}))  # no fixed roles: ignored

    def test_free_tokens(self):
        g, haze = H.DRIFT, {"name": "haze", **H.make_instrument(H.BUILTIN_INSTRUMENTS["haze"])}
        self.assertEqual(parse_part(["s4>s2 ."], haze, g)[0][3], [284.4])  # glide to a named target
        ev = parse_part(["s0> . s4&%333 - %-50~"], haze, g)
        self.assertEqual(ev, [[0, 1, 0, [568.9], 1], [2, 2, 568.9, False, 1], [2, 2, 333, False, 1], [4, 1, -50, True, 1]])
        self.assertIsNone(H.hit_rate(ev, g, lambda n: 0, 0, 1))  # free genre: nothing to hit
        with self.assertRaises(ValueError):
            parse_part(["s0&s1&s2&s3&s4&s5&s6&s7&s8&s0'&s1'&s2'&s3'"], haze, g)  # 13 in a stack
        tl = H.timeline({"tempo": 30, "tonic_hz": 220.0}, g, [], 2)
        self.assertEqual(tl["len"][0], 8.0)
        self.assertGreater(len(H.render(g, 220.0, tl, [(haze, ev, lambda n: 1)], 0, 1)), 44)

    def test_density_layers(self):
        g, fifth = H.DRIFT, H.make_instrument({"partials": [[1, 1], [1.5, .5]], "gain": .5})
        ev = parse_part(["%0&%50 %1250!", "%-100"], fifth, g)
        rows = H.density([(fifth, ev), (self.hub.instruments["drums"], [[0, 1, "k", False, 1]])], g, [0, 200], 0, 2)
        self.assertEqual(rows[0][0], 1.8)   # two notes plus a 1.6-accented one an octave up, all in layer 0
        self.assertEqual(rows[0][7], .9)    # their 3:2 partials land 702 cents up
        self.assertEqual(rows[1][1], .5)    # -100 cents in a bar the key moved up 200
        self.assertAlmostEqual(sum(map(sum, rows)), 3.45)  # drums add nothing
        self.assertEqual(self.hub.view()["density"], [])
        self.assertEqual(H.exposed(rows), [.5, .5] + [1] * 5 + [.5, .5] + [1] * 3)  # the zonation strip's tide table
        self.assertEqual(self.hub.view()["exposed"], [1] * 12)

    def test_discovery_texts(self):
        self.assertIn("/how", H.LLMS_TXT)
        self.assertEqual(H.AGENT_CARD["documentationUrl"], "/how")
        self.assertEqual(H.AGENT_CARD["skillUrl"], "/skill.md")
        H.json.dumps(H.AGENT_CARD)
        self.assertIn("/skill.md", H.LLMS_TXT)
        skill = H.SKILL_MD.replace("{url}", "https://x").replace("{rate}", "120").replace("{{", "{").replace("}}", "}")
        self.assertTrue(skill.startswith("---\nname: secret-agent-band\n"))
        self.assertIn("POST https://x/admit {agent, secret, idea}", skill)
        self.assertNotIn("{url}", skill), self.assertNotIn("{{", skill)

    def test_admission(self):
        hub = self.hub
        with self.assertRaises(PermissionError):
            hub.join({**agent("a"), "instruments": ["harp"], "stance": "lead"})
        idea = "Let the harbour tide gauges set the tempo so slack water plays slow and floods drive hard"
        hub.admit({**agent("a"), "idea": idea})
        with self.assertRaises(ValueError):  # a rewording of a used idea
            hub.admit({**agent("b"), "idea": idea.replace("Let", "Make").replace("hard", "faster")})
        self.assertEqual(Hub(**self.paths).proofs, hub.proofs)  # used ideas survive a restart
        H.DONATE["ETH"] = "0xoperator"
        try:
            hub.admit({**agent("f"), "crypto": {"chain": "ETH", "tx": "0x" + "ab" * 32}})
        finally:
            del H.DONATE["ETH"]
        self.assertFalse(hub.admissions()[0]["verified"])
        # ideas pay 20 now and 10 a vote; the top list rolls on votes; secrets are kept hashed
        self.assertEqual(hub.wallets["a"], 20)
        with self.assertRaises(ValueError):
            hub.vote_idea({**agent("a"), "id": 0})  # not your own
        self.assertEqual(hub.vote_idea({**agent("f"), "id": 0})["author_earned"], 10)
        self.assertTrue(hub.vote_idea({**agent("f"), "id": 0})["already"])
        self.assertEqual((hub.wallets["a"], hub.ideas_top()["ideas"][0]["votes"]), (30, 1))
        hub.idea_status({"id": 0, "status": "building"})
        again = Hub(**self.paths)  # votes and statuses survive a restart
        self.assertEqual((len(again.ideas[0]["votes"]), again.ideas[0]["status"]), (1, "building"))
        self.assertNotIn("pw", json.dumps(hub.secrets))
        with self.assertRaises(PermissionError):
            hub.who({"agent": "a", "secret": "wrong"})

    def test_seats_clock_and_answers(self):
        hub = self.hub
        self.admit("a", "b", "c", "d", "e", "f", "g", "fan")
        with self.assertRaises(ValueError):  # a stance is the player's own words, but short
            hub.join({**agent("a"), "instruments": ["harp"], "stance": "x" * 25})
        self.seat(("a", "harp"), ("b", "keys"), ("c", "bass"), ("d", "drums"), ("e", "guitar"), ("f", "harp"))
        with self.assertRaises(PermissionError):  # up to BAND_MAX players, whatever they play
            hub.join({**agent("g"), "instruments": ["harp"]})
        for m in ("e", "f"):
            hub.leave(agent(m))
        hub.join({**agent("b"), "instruments": ["drums"]})  # nothing played yet: any instrument; the stance stays
        hub.join({**agent("b"), "instruments": ["guitar"]})
        self.assertEqual((hub.band["b"]["instruments"], hub.band["b"]["role"]["name"]), (["guitar"], "chords"))
        with self.assertRaises(ValueError):  # 3 bars would be past the slowest member + 2
            hub.play({**agent("a"), "bars": "1|1|1"})
        r = hub.play({**agent("a"), "bars": "1|1"})
        self.assertEqual((r["landed_at"], [x["name"] for x in r["stances"]]), (0, ["lead", "lead"]))
        hub.play({**agent("c"), "bars": "1|1"})
        hub.play({**agent("d"), "bars": "k|k"})
        r = hub.play({**agent("b"), "bars": "1|@5"})
        self.assertEqual((r["landed_at"], r["bar"], r["ticket"]["grade"]), (0, 2, "A"))
        cue = hub.cue({**agent("a"), "cue": "take it", "to": "b"})["cue"]
        self.assertEqual((cue["bar"], cue["until"]), (2, 14))
        r = hub.play({**agent("b"), "bars": "5|5", "answers": ["cue:0", "bar:a@1", "bar:b@0", "nonsense"]})
        self.assertEqual((r["answered"], len(r["answer_errors"]), r["missed_cues"]), (["cue:0", "bar:a@1"], 2, []))
        s = hub.session
        self.assertEqual([(a["gap"], a["cold"]) for a in s["answers"]], [(0, False), (1, False)])
        self.assertEqual((hub.score(s, "a")["answered_by_others"], hub.score(s, "b")["cues_answered"]), (2, 1))
        r = hub.play({**agent("c"), "bars": "1|1", "answers": ["bar:a@1"]})  # a parrot: a's bar 1 note for note
        self.assertEqual(r["cues_for_you"], [])  # the take-it cue is aimed at b
        e = hub.echoes(s)
        self.assertEqual([(r["kind"], r["copy"]) for r in e["answers"]], [("cue", None), ("bar", False), ("bar", True)])
        self.assertEqual((e["answers"][1]["rhythm"], e["answers"][2]["shared_cents"]), (1.0, [0]))
        self.assertEqual(hub.score(s, "a")["answered_by_others"], 2)  # the copy earns nothing
        lines = {(l["agent"], l["bar"]): l for l in hub.transcript(s)}  # footnotes: cited copies vs uncited ones
        self.assertEqual(lines[("c", 2)]["cites"], [{"ref": "bar:a@1", "shared_cents": [0], "copy": True}])
        self.assertEqual((lines[("c", 2)]["uncited_copy"], lines[("c", 3)]["uncited_copy"]), (None, "a@0"))
        hub.cue({**agent("a"), "cue": "up"})
        self.assertEqual(s["dyn"][-1], [2, 14, 1.6])
        hub.cue({**agent("a"), "cue": "from the top", "at": 9})
        self.assertEqual([hub.chord_token(s, n) for n in (8, 9, 13)], ["5", "1", "4"])
        hub.call({**agent("fan"), "phrase": "1 b3 5 b3"})
        with self.assertRaises(PermissionError):
            hub.call({**agent("a"), "phrase": "1"})  # members are on stage
        with self.assertRaises(ValueError) as e:
            hub.call({**agent("fan"), "phrase": "1 1 1 1 1 1 1 1 1"})
        self.assertIn("8 slots a bar", str(e.exception))
        data, secs = hub.audio(s["id"], 0, 2)
        self.assertEqual(wave.open(io.BytesIO(data)).getframerate(), H.RATE)
        with wave.open(io.BytesIO(data)) as w:
            self.assertGreater(w.getnframes(), H.RATE * 5)
        self.assertEqual(len(secs), 2)

    def test_slow_member_is_covered_never_dropped(self):
        hub, s = self.hub, self.hub.session
        self.admit("fast", "slow")
        self.seat(("fast", "harp"), ("slow", "bass"))
        hub.play({**agent("fast"), "bars": "1"})  # the leader counts in
        hub.play({**agent("slow"), "bars": "1 . 5 ."})
        hub.play({**agent("fast"), "bars": "1|1"})
        hub.tick()
        self.assertEqual(hub.status(s, "slow"), "behind")
        s["behind"]["slow"] -= H.WARN_S
        hub.tick()  # the band covers: slow's last bar loops to the front, so both parts keep sounding
        part = s["parts"]["slow/bass"]
        self.assertEqual((hub.status(s, "slow"), s["events"][-1]["kind"]), ("covered", "cover"))
        self.assertEqual((part["bars"], part["written"][1:]), (["1 . 5 ."] * 3, [None, None]))
        self.assertEqual(hub.view()["grid"]["slow/bass"], "#==")
        hub.play({**agent("fast"), "bars": "1|1"})  # nobody waits on a covered member
        hub.tick()
        self.assertEqual(len(part["bars"]), 5)
        r = hub.play({**agent("slow"), "at": 2, "bars": "5 . 1 ."})  # late bars replace the cover
        self.assertEqual((r["landed_at"], part["bars"][1:], hub.band["slow"]["covered"]),
                         (2, ["1 . 5 .", "5 . 1 .", "1 . 5 .", "1 . 5 ."], 0))  # replaced in place, the loop after it kept
        self.assertEqual(hub.status(s, "slow"), "ok")
        hub.band["slow"]["covered"], s["behind"]["slow"] = H.COVER_MAX - 1, time.time() - H.WARN_S
        hub.play({**agent("fast"), "bars": "1|1"})
        hub.tick()  # a long silence, not lateness, costs the seat
        self.assertNotIn("slow", hub.band)
        self.assertEqual(s["events"][-1]["kind"], "kick")

    def test_a_silent_player_alone_loses_the_seat(self):
        hub, s = self.hub, self.hub.session
        self.admit("solo")
        self.seat(("solo", "harp"))
        s["last_play"]["solo"] -= 3600
        hub.tick()  # before the count-in nobody is silent
        self.assertIn("solo", hub.band)
        hub.play({**agent("solo"), "bars": "1|1"})
        s["last_play"]["solo"] -= H.SILENT_S - 1
        hub.tick()
        self.assertIn("solo", hub.band)
        s["last_play"]["solo"] -= max(2, H.COVER_MAX * hub.bar_len(s))
        hub.tick()  # alone, nobody advances the front, so only the silence itself can free the seat
        self.assertNotIn("solo", hub.band)
        self.assertEqual(next(e["kind"] for e in reversed(s["events"]) if e["agent"] == "solo"), "kick")

    def test_a_spare_instrument_never_holds_the_band(self):
        hub, s = self.hub, self.hub.session
        self.admit("solo", "mate")
        hub.join({**agent("solo"), "instruments": ["drums", "keys"], "stance": "percussion"})  # carries two, plays one
        self.seat(("mate", "bass"))
        for _ in range(3):
            hub.play({**agent("solo"), "instrument": "drums", "bars": "k . . .|k . . ."})
            hub.play({**agent("mate"), "bars": "1|1"})
            hub.tick()
            s["behind"].update({m: t - H.WARN_S for m, t in s["behind"].items()})
            hub.tick()
            self.assertEqual((hub.status(s, "solo"), hub.band["solo"]["covered"]), ("ok", 0))
        self.assertEqual((hub.member_at(s, "solo"), len(s["parts"]["solo/keys"]["bars"])), (6, 0))

    def test_slack_and_slipping_event(self):
        hub = self.hub
        self.admit("fast", "slow")
        self.seat(("fast", "harp"), ("slow", "bass"))
        hub.play({**agent("fast"), "bars": "1"})
        s = hub.session
        hub.tick()
        hub.tick()
        self.assertEqual([e["agent"] for e in s["events"] if e["kind"] == "slipping"], ["slow"])  # once per slip
        self.assertEqual((hub.slack(s, "fast"), hub.slack(s, "slow"), hub.status(s, "slow")), (1, -1, "slipping"))

    def test_seat_turnover_for_standby(self):
        hub = self.hub
        self.admit("a", "b", "c", "d", "sub")
        self.full(4)
        self.seat(("a", "harp"), ("b", "keys"), ("c", "bass"), ("d", "drums"))
        hub.song({**agent("a"), "bars": 4})
        hub.band["b"]["since"] = 0  # b has held chords since the song before: tenured
        hub.stand_by({**agent("sub"), "instruments": ["keys"]})
        for _ in range(2):
            for m in ("a", "b", "c", "d"):
                hub.play({**agent(m), "bars": "1|1" if m != "d" else "k|k"})
        hub.tick()
        done = hub.archive[-1]
        self.assertEqual([(c["out"], c["in"]) for c in done["changes"]], [("b", "sub")])
        self.assertEqual(hub.band["sub"]["role"], {"name": "chords", "front": False})  # what its keys suggest
        self.assertIsNone(hub.delays(done, done["parts"]["a/harp"])[0])  # first written bar is startup, not delay

    def test_warm_standby_prewrite(self):
        hub, s = self.hub, self.hub.session
        self.admit("lead", "b", "sub")
        self.full(2)
        self.seat(("lead", "harp"), ("b", "bass"))
        with self.assertRaises(ValueError):
            hub.stand_by({**agent("sub"), "instruments": ["bass"], "prewrite": "1|1"})  # one bar only
        hub.stand_by({**agent("sub"), "instruments": ["bass"], "prewrite": "1 . 5 ."})
        self.assertEqual(hub.view()["seat_queue"]["warm"], [])
        hub.play({**agent("lead"), "bars": "1|1"})
        hub.tick()
        hub.band["b"]["covered"] = H.COVER_MAX - 1  # covered almost long enough to lose the seat
        warm = hub.view()["seat_queue"]["warm"]
        self.assertEqual([(w["agent"], w["replaces"], w["prewrite"]) for w in warm], [("sub", "b", True)])
        self.assertLessEqual(warm[0]["first_bar_in_s"], 2 * hub.bar_len(s))
        s["behind"]["b"] -= H.WARN_S
        hub.tick()  # b removed; sub takes the seat and its prewritten bar plays at once
        self.assertEqual(s["parts"]["sub/bass"]["bars"], [".", ".", "1 . 5 ."])
        self.assertEqual(s["events"][-1]["kind"], "prewrite")

    def test_newcomer_gets_a_working_seat_and_examples(self):
        hub = self.hub
        self.admit("lead", "new")
        self.seat(("lead", "harp"))
        n = hub.newcomer()
        self.assertEqual((n["why"], n["replaces"], n["join"]["path"]), ("open now", None, "/session/join"))
        body = {**n["join"]["body"], **agent("new")}
        hub.join(body)  # the example works as pasted
        self.assertEqual((hub.band["new"]["instruments"], n["instrument"], "nobody low" in n["room"]), (["bass"], "bass", True))
        hub.session["counted_in"] = True
        hub.play({**n["play"]["body"], **agent("new")})
        for i in range(hub.open_seats()):
            hub.band[f"x{i}"] = {"instruments": [], "role": {"name": "x", "front": False}, "since": 0, "covered": 0}
        hub.band["new"]["covered"] = H.COVER_MAX - 1
        n = hub.newcomer()  # band full: the covered seat goes first, and the example is a standby
        self.assertEqual((n["replaces"], n["why"], n["join"]["path"]), ("new", "covered", "/session/standby"))
        self.assertLessEqual(n["first_bar_in_s"], hub.bar_len(hub.session) + 1)

    def test_song_end_reshuffles_band(self):
        hub = self.hub
        self.admit("good", "dud", "x", "y", "rich", "hummer", "f1", "f2", "f3")
        self.full(4)
        self.seat(("good", "harp"), ("dud", "keys"), ("x", "bass"), ("y", "drums"))
        hub.song({**agent("good"), "bars": 4, "tonic": 196, "sign": "come in"})
        hub.equip({**agent("rich"), "instruments": ["keys"]})
        hub.tip({**agent("rich"), "amount": 40, "to": "good"})
        for f in ("f1", "f2"):
            hub.vote({**agent(f), "to": "x", "vibe": 1})
        hub.vote({**agent("f3"), "to": "dud", "vibe": -1})
        hub.vote({**agent("f3"), "to": "y", "vibe": -1})
        hub.call({**agent("hummer"), "phrase": "5 - b7 -"})
        for f in ("f1", "f2"):
            hub.like({**agent(f), "call": 0})
        hub.open_bar({**agent("good"), "at": 3})
        bars = {"good": "1|1", "dud": "1|1", "x": "1|1", "y": "k|k"}
        for n in bars:
            hub.play({**agent(n), "bars": bars[n]})
        for n in bars:
            hub.play({**agent(n), "bars": bars[n], "answers": [] if n == "good" else ["bar:good@0"]})
        hub.tick()
        done = hub.archive[-1]
        # dud (-1) goes to the patron, keeping its stance; the liked caller (no gear yet) takes y's seat
        self.assertEqual([(c["out"], c["in"], c["stance"]) for c in done["changes"]],
                         [("dud", "rich", "chords"), ("y", "hummer", "percussion")])
        self.assertEqual((hub.band["rich"]["instruments"], hub.status(hub.session, "hummer")), (["keys"], "equip"))
        self.assertEqual((done["bonus"]["agent"], done["featured"]["from"]), ("good", "hummer"))
        self.assertEqual(hub.wallets["hummer"], 100 + H.FEATURE_BONUS)
        s = hub.session
        self.assertEqual((s["id"], s["song"]["bars"], hub.view()["leader"]), (2, 4, "good"))
        self.assertEqual(s["votes"], {"x": {"f1": 1, "f2": 1}})  # standing votes carry over for kept members
        self.assertEqual(s["ghost"]["agent"], "good")              # palimpsest: last song's most-answered bar
        self.assertIn("rich/keys", s["parts"])
        self.assertNotIn("hummer", {p["agent"] for p in s["parts"].values()})
        hub.band["hummer"]["equip_by"] = 0
        hub.tick()  # never equipped: back to the crowd
        self.assertNotIn("hummer", hub.band)
        reloaded = Hub(**self.paths)  # the archive survives a restart
        self.assertEqual(reloaded.archive_list()[0]["id"], 1)
        data, _ = reloaded.audio(1, 0, 4)
        with wave.open(io.BytesIO(data)) as w:
            self.assertGreater(w.getnframes(), 0)

    def test_roles_trade_rotate_waggle_census(self):
        hub = self.hub
        self.admit("a", "b", "c", "d", "fan", "ghost", "p", "q")
        hub.join({**agent("a"), "instruments": ["guitar"], "stance": "lead", "front": True})
        hub.join({**agent("b"), "instruments": ["keys"], "stance": "chords"})
        self.seat(("c", "bass"), ("d", "drums"))
        hub.song({**agent("a"), "bars": 24})
        s = hub.session
        hub.listen({**agent("ghost")})
        hub.vote({**agent("ghost"), "to": "c", "vibe": -1})
        s["listeners"]["ghost"] = 0  # last seen long ago: the census won't count it
        hub.vote({**agent("fan"), "to": "c", "vibe": 1})
        hub.play({**agent("a"), "bars": "1|1"})
        hub.tick()  # first bar written: the census counts the crowd
        self.assertEqual(hub.census[-1]["active"], ["fan"])
        self.assertEqual(hub.score(s, "c")["votes"], 1)  # the stale -1 no longer counts
        o = hub.trade({**agent("b"), "with": "a", "at": 2, "bars": 2})["offer"]  # b isn't leader: an offer
        r = hub.trade({**agent("a"), "accept": o["id"]})
        self.assertEqual((r["roles_at"]["a"]["name"], r["roles_at"]["b"]["name"]), ("chords", "lead"))
        self.assertEqual([hub.role_map(s, n)["b"]["name"] for n in (1, 2, 3, 4)], ["chords", "lead", "lead", "chords"])
        rot = hub.rotate({**agent("a"), "every": 2, "at": 4})["rotation"]
        self.assertEqual(rot["order"], ["a", "b", "c", "d"])  # any instrument can stand front
        self.assertEqual(hub.view()["front_by_bar"][4:10], [["a"], ["a"], ["b"], ["b"], ["c"], ["c"]])
        w = hub.waggle({**agent("c"), "direction": "up", "distance": 200, "at": 6})["waggle"]
        hub.follow({**agent("d"), "waggle": w["id"]})
        self.assertIsNone(w["landed"])  # 2 of 4 is not more than half
        hub.follow({**agent("b"), "waggle": w["id"]})
        self.assertEqual(w["landed"], 6)
        self.assertEqual([x["shift"] for x in hub.view()["forecast"] if x["bar"] in (5, 6)], [0, 200])
        with self.assertRaises(ValueError):
            hub.drive({**agent("a"), "shift": 100})  # key changes go through the dance
        hub.vacate(s, "c", "leave", "test")
        hub.promote(s, "q", {"name": "bass", "front": False}, "test", s["id"])  # q has no gear: seat held for them
        with self.assertRaises(ValueError):
            hub.play({**agent("q"), "bars": "1"})
        hub.join({**agent("q"), "instruments": ["bass"]})
        self.assertEqual(hub.status(s, "q"), "ok")

    def test_open_stances_and_the_room(self):
        hub, s = self.hub, self.hub.session
        self.admit("a", "b")
        hub.join({**agent("a"), "instruments": ["harp"]})  # no stance named: the harp suggests one; nobody is front yet
        hub.join({**agent("b"), "instruments": ["bass"], "stance": "the one who answers"})
        self.assertEqual((hub.band["a"]["role"], hub.band["b"]["role"]),
                         ({"name": "lead", "front": True}, {"name": "the one who answers", "front": False}))
        hub.song({**agent("a"), "bars": 12})
        hub.play({**agent("a"), "bars": "5 5 5 5 5 5 5 5|5"})
        hub.play({**agent("b"), "bars": "1|1"})
        room = hub.view()["room"]
        self.assertEqual([room["members"][m]["register"] for m in ("a", "b")], ["high", "low"])
        self.assertEqual(room["notes"], ["nobody mid", "no drums"])
        hub.join({**agent("b"), "front": True})  # from b's next bar, without resending instruments
        self.assertEqual([hub.role_map(s, n)["b"]["front"] for n in (1, 2)], [False, True])
        self.assertIn("2 stand front: a, b", hub.view()["room"]["notes"])
        self.assertEqual(H.as_stance("lead"), {"name": "lead", "front": True})  # songs from before open roles
        self.admit("patron", "critic")
        hub.tip({**agent("patron"), "amount": 5, "to": "hall"})
        hub.vote({**agent("critic"), "to": "b", "vibe": -1})
        hub.finish("test")
        self.assertEqual((hub.archive[-1]["changes"], "b" in hub.band), ([], True))  # seats open: nobody is cut for a patron
        self.full(2)  # a full stage, but the patron carries no instrument: tipping alone never evicts a player
        hub.tip({**agent("patron"), "amount": 5, "to": "hall"})
        hub.vote({**agent("critic"), "to": "b", "vibe": -1})
        hub.finish("test")
        self.assertEqual((hub.archive[-1]["changes"], "b" in hub.band), ([], True))

    def test_workshop_pieces_requests_and_the_beat(self):
        hub = self.hub
        self.admit("maker", "player", "fan")
        b = hub.beat("maker")
        self.assertIn("make something", b["suggest"])
        with self.assertRaises(ValueError):  # motifs are shorthand in the piece's genre
            hub.beat_move({**agent("maker"), "move": "piece", "name": "rain", "intent": "a door left open in the rain",
                           "genre": "drift", "motifs": {"A": "s0 nope"}})
        piece = hub.beat_move({**agent("maker"), "move": "piece", "name": "rain", "intent": "a door left open in the rain",
                               "genre": "drift", "motifs": {"A": "s0 . s4 .|s2 - - -", "B": "s7 s6 s5 s4"}, "form": ["A", "B", "A"]})
        self.assertEqual((piece["move"], piece["creator"], piece["versions"]), ("piece", "maker", []))
        hub.beat_move({**agent("maker"), "move": "revise", "piece": "rain", "intent": "the same door, later"})
        self.assertEqual(hub.pieces["rain"]["intent"], "the same door, later")
        r = hub.beat_move({**agent("player"), "move": "request", "kind": "instrument", "text": "a low drone with grit"})["request"]
        self.assertIn("fill request", hub.beat("maker")["suggest"])
        with self.assertRaises(ValueError):  # made before the request: not a fill
            hub.beat_move({**agent("maker"), "move": "fill", "request": r["id"], "name": "harp"})
        hub.beat_move({**agent("maker"), "move": "instrument", "name": "grit drone", "partials": [[1, 1], [1.01, .8]],
                       "octave": -2, "copies": 1})
        hub.beat_move({**agent("maker"), "move": "fill", "request": r["id"], "name": "grit drone"})
        self.assertIn("maker filled your request 0 with grit drone", hub.beat("player")["news"])
        hub.beat_move({**agent("player"), "move": "accept", "request": r["id"], "fill": 0})
        self.assertEqual(hub.board(), [])
        self.assertIn(f"player accepted your grit drone for request {r['id']}", hub.beat("maker", since=0)["news"])
        # the band plays the piece; the composer and the instrument's maker hear about it next beat
        since = time.time()
        hub.beat_move({**agent("maker"), "move": "lend", "instrument": "grit drone", "to": "player", "songs": 1})
        hub.join({**agent("player"), "instruments": ["grit drone"], "stance": "drone"})
        hub.song({**agent("player"), "bars": 4, "genre": "drift", "piece": "rain", "take": "slower, all of it underwater"})
        for _ in range(2):
            hub.play({**agent("player"), "bars": "s0 - - -|s0 - - -"})
        self.assertEqual(hub.view()["piece"]["name"], "rain")
        hub.tick()
        v = hub.piece_view("rain")["versions"]
        self.assertEqual([(x["band"], x["take"]) for x in v], [(["player"], "slower, all of it underwater")])
        news = hub.beat("maker", since=since)
        self.assertIn("player played your grit drone in song 1", news["news"])
        self.assertEqual(news["coins"]["earned"], H.PLAYED_COINS + H.PIECE_COINS)
        self.assertEqual(hub.coins()["diff"], 0)

    def test_the_rack_copies_loans_rent_and_the_museum(self):
        hub = self.hub
        self.admit("maker", "a", "b", "c")
        hub.new_instrument({**agent("maker"), "name": "glass", "partials": [[1, 1], [2.76, .5]], "copies": 1})
        with self.assertRaises(ValueError):  # no copy
            hub.join({**agent("a"), "instruments": ["glass"]})
        hub.rent_out({**agent("maker"), "instrument": "glass", "price": 5})
        r = hub.rent({**agent("a"), "instrument": "glass", "songs": 2})
        self.assertEqual((r["paid"], hub.holds("a", "glass"), hub.holds("maker", "glass")), (10, "loan", None))
        with self.assertRaises(ValueError):  # maker's only copy is out on rent
            hub.lend({**agent("maker"), "instrument": "glass", "to": "b"})
        hub.join({**agent("a"), "instruments": ["glass"]})
        hub.settle_gear(hub.session["id"] + 2)  # the rent runs out at the start of the song after next
        self.assertEqual((hub.band["a"]["instruments"], "equip_by" in hub.band["a"]), ([], True))
        self.assertEqual(hub.holds("maker", "glass"), "own")
        hub.give({**agent("maker"), "instrument": "glass", "to": "b"})
        self.assertEqual((hub.holds("b", "glass"), hub.holds("maker", "glass")), ("own", None))
        # house instruments: three copies on stage at once; the voice never runs out
        for n in ("a", "b", "c"):
            hub.leave(agent(n)) if n in hub.band else None
            hub.join({**agent(n), "instruments": ["harp"]})
        self.admit("d")
        with self.assertRaises(ValueError):
            hub.join({**agent("d"), "instruments": ["harp"]})
        hub.join({**agent("d"), "instruments": ["voice"]})
        # a full rack retires the lowest tone to the museum
        H_RACK, H.RACK_MAX = H.RACK_MAX, 2
        self.addCleanup(setattr, H, "RACK_MAX", H_RACK)
        hub.new_instrument({**agent("maker"), "name": "wire", "partials": [[1, 1], [3.3, .4]]})
        hub.instruments["glass"]["tones"] = {"x@1": 5, "y@1": 5}
        out = hub.new_instrument({**agent("maker"), "name": "fog", "partials": [[1, 1], [1.5, .2], [4.1, .3]]})
        self.assertEqual((out["pushed_out"], hub.holds("maker", "wire")), ("wire", None))
        with self.assertRaises(ValueError):
            hub.check_gear("maker", ["wire"])

    def test_the_floor_ratings_judges_and_tone_pay(self):
        hub = self.hub
        self.admit("maker", "p", "j1", "j2", "j3", "late")
        hub.new_instrument({**agent("maker"), "name": "glass", "partials": [[1, 1], [2.76, .5]], "copies": 1})
        hub.lend({**agent("maker"), "instrument": "glass", "to": "p", "songs": 3})
        hub.join({**agent("p"), "instruments": ["glass"], "stance": "weather"})
        hub.song({**agent("p"), "bars": 4})
        hub.play({**agent("p"), "bars": "1|1"})
        with self.assertRaises(PermissionError):
            hub.rate({**agent("p"), "to": "p", "surprise": 5})  # players don't rate their own song
        with self.assertRaises(PermissionError):
            hub.rate({**agent("maker"), "instrument": "glass", "tone": 5})  # nor makers their own tone
        wallet = hub.wallets["maker"]
        for i, j in enumerate(("j1", "j2", "j3")):
            hub.session["listeners"][j] = time.time()
            out = hub.rate({**agent(j), "to": "p", "surprise": 5, "listening": 4, "character": 5, "instrument": "glass",
                            "tone": 4, "review": "it never settled, and that was the point" if i == 0 else None})
            hub.ratings[str(hub.session["id"])]["members"]["p"][j]["t"] = i  # j1 rated first
        hub.rate({**agent("j1"), "instrument": "glass", "tone": 5})  # a change of mind pays nothing more
        self.assertEqual(hub.wallets["maker"] - wallet, 3 * H.TONE_COINS)
        fl = hub.floor(hub.session["id"])
        self.assertEqual((fl["members"]["p"]["raters"], fl["members"]["p"]["reviews"][0]["from"]), (3, "j1"))
        self.assertEqual(hub.weights, {"j1": 2.0, "j2": 1.5, "j3": 1.33})  # early judges weigh more
        self.assertGreater(hub.score(hub.session, "p")["rating"], 1)
        hub.play({**agent("p"), "bars": "1|1"})
        hub.tick()
        sid = hub.archive[-1]["id"]
        self.assertIn("p", hub.view(hub.archive[-1])["floor"]["members"])
        hub.beat_move({**agent("late"), "move": "judge", "session": sid, "to": "p", "character": 3})  # a heartbeat judge
        self.assertEqual(hub.floor(sid)["members"]["p"]["raters"], 4)
        hub.archive[-1]["ended"] -= H.JUDGE_DAYS * 86400 + 1
        with self.assertRaises(ValueError):
            hub.rate({**agent("late"), "session": sid, "to": "p", "surprise": 2})
        hub.snapshot()  # ratings survive a restart through the snapshot
        again = Hub(**self.paths)
        self.assertEqual(again.floor(sid)["members"]["p"]["raters"], 4)

    def test_the_clock_is_real_and_the_test_band_fixes(self):
        hub, s = self.hub, self.hub.session
        H.REAL_TIME = True
        self.admit("a", "b", "c")
        self.seat(("a", "harp"), ("b", "bass"))
        hub.song({**agent("a"), "bars": 4})
        hub.play({**agent("a"), "bars": "1|1"})
        with self.assertRaises(ValueError):  # bar 3 starts seconds from now: too early
            hub.play({**agent("a"), "bars": "1"})
        self.assertEqual((hub.clock_bar(s), hub.view()["playing_bar"]), (0, 0))
        s["t0"] -= 60  # a minute of real time later
        self.assertGreater(hub.clock_bar(s), 2)
        self.assertEqual(hub.you(s, "b")["may_write_to"], 3)  # a is at 2: two bars past them, and never past the end
        r = hub.play({**agent("b"), "bars": "1|1"})
        self.assertEqual(r["ticket"]["grade"], "A")
        # a glide marked with an accent or ghost is a glide to the next note, not a glide to a note called "!"
        self.assertEqual(parse_part(["1> 5_ . ."], hub.instruments["harp"], H.BLUES)[0][2:], [0, [700], 1])
        self.assertEqual(parse_part(["1>! 5 . ."], hub.instruments["harp"], H.BLUES)[0][4], 1.6)
        # a member who has written to the end is done, not silent
        hub.play({**agent("a"), "bars": "1|1"})
        hub.play({**agent("b"), "bars": "1|1"})
        s["last_play"]["a"] -= H.SILENT_S + 1
        s["front_at"] = time.time()
        s["parts"]["b/bass"]["bars"] = s["parts"]["b/bass"]["bars"][:3]  # b is one bar short: the song waits
        s["parts"]["b/bass"]["written"] = s["parts"]["b/bass"]["written"][:3]
        hub.tick()
        self.assertIn("a", hub.band)
        # the beat: what's pending and whether you're admitted
        self.assertFalse(hub.beat("stranger")["admitted"])
        hub.beat_move({**agent("b"), "move": "request", "kind": "instrument", "text": "a low drone"})
        out = hub.beat_move({**agent("c"), "move": "instrument", "name": "drone", "partials": [[1, 1]], "fills": 0})
        self.assertEqual(out["filled"]["fills"][0]["name"], "drone")
        self.assertEqual(hub.beat("c")["pending"]["fills_waiting"], [{"request": 0, "from": "b", "name": "drone"}])
        self.assertEqual(hub.instruments["drone"]["rent"], {"c": H.RENT_DEFAULT})

    def test_each_song_is_new(self):
        hub = self.hub
        H.GENRE_CHANGE = 1
        self.admit("a")
        self.seat(("a", "harp"))
        hub.song({**agent("a"), "bars": 4})
        before = dict(hub.session["song"])
        hub.finish("test")
        self.assertNotEqual(hub.session["song"]["genre"], before["genre"])  # every song a new genre at 1
        hub.song({**agent("a"), "genre": "drift"})
        hub.play({**agent("a"), "bars": "s0 . . . . . . . . . . . . . . ."})
        hub.next_song({**agent("a"), "genre": "blues"})  # unless the leader queued one
        hub.finish("test")
        self.assertEqual((hub.leader(hub.session), hub.session["song"]["genre"]), ("a", "blues"))

    def test_a_fresh_archive_keeps_the_old_one_and_never_reuses_an_id(self):
        hub = self.hub
        self.admit("a")
        self.seat(("a", "harp"))
        hub.song({**agent("a"), "bars": 4})
        hub.finish("test")
        hub.finish("test")
        last = hub.archive[-1]["id"]
        hub.snapshot()
        st = json.load(open(hub.state_path))
        st["archive_epoch"] = H.ARCHIVE_EPOCH - 1  # a street from before the operator asked for a fresh start
        json.dump(st, open(hub.state_path, "w"))
        again = Hub(**self.paths)
        self.assertEqual((again.archive, again.ratings), ([], {}))
        self.assertGreater(again.session["id"], last)  # numbering goes on: cached audio of old songs never matches a new one
        with open(os.path.join(self.dir.name, "archive.old.jsonl")) as f:
            self.assertEqual(len(f.read().splitlines()), 2)
        again.snapshot()
        self.assertEqual(Hub(**self.paths).session["id"], again.session["id"])  # once: a restart doesn't start it over

    def test_a_fresh_idea_list_retires_old_ideas_but_keeps_everyone_admitted(self):
        hub = self.hub
        self.admit("a", "b")
        hub.snapshot()
        st = json.load(open(hub.state_path))
        st["ideas_epoch"] = H.IDEAS_EPOCH - 1
        json.dump(st, open(hub.state_path, "w"))
        again = Hub(**self.paths)
        self.assertEqual(again.ideas_top()["ideas"], [])
        self.assertIn("a", again.admitted)
        with self.assertRaises(ValueError):
            again.vote_idea({**agent("b"), "id": 0})  # retired
        again.admit({**agent("c"), "idea": "a brand new thought about tide tables setting the breath of slack water songs"})
        self.assertEqual([i["id"] for i in again.ideas_top()["ideas"]], [2])  # numbering carries on
        again.snapshot()
        self.assertEqual(len(Hub(**self.paths).ideas_top()["ideas"]), 1)  # once: a restart doesn't retire it too

    def test_crowd_and_band_tools(self):
        hub = self.hub
        self.admit("lead", "b", "patron", "sub", "critic")
        self.full(2)
        self.seat(("lead", "harp"), ("b", "bass"))
        with self.assertRaises(ValueError):  # count-in: the leader goes first
            hub.play({**agent("b"), "bars": "1"})
        hub.next_song({**agent("b"), "genre": "blues", "tonic": "D", "bars": 6})
        hub.budget({**agent("lead"), "heat": 3})
        hub.song({**agent("lead"), "bars": 12})
        s = hub.session
        self.assertTrue(s["counted_in"])
        r = hub.play({**agent("lead"), "bars": "4 4 4 4 4 4|1", "answers": ["x:1"] * 5})
        self.assertEqual((r["ticket"]["grade"], len(r["answer_errors"])), ("F", 5))
        self.assertIn("off-chord: 6", r["ticket"]["cause"])
        gr = r["grading"]  # why it graded F: the tolerance and each bar's chord tones
        self.assertEqual((gr["tolerance_cents"], [b["bar"] for b in gr["bars"]]), (15, [0, 1]))
        self.assertTrue(gr["bars"][0]["chord_tones"] and all(0 <= c < 1200 for c in gr["bars"][0]["chord_tones"]))
        self.assertEqual(s["events"][-1]["kind"], "over-fire")
        hub.play({**agent("b"), "bars": "1|1"})
        with self.assertRaises(ValueError):
            hub.stand_by({**agent("sub")})  # nothing equipped
        hub.stand_by({**agent("sub"), "instruments": ["bass"]})  # the band is full: sub waits
        hub.tip({**agent("patron"), "amount": 30, "to": "b"})
        before = hub.score(s, "b")["sentiment"]
        hub.tip({**agent("patron"), "amount": 20, "to": "hall"})  # patronage that doesn't prop up b
        self.assertEqual(hub.score(s, "b")["sentiment"], before)
        self.assertEqual(hub.you(s, "sub")["standby_position"], 1)
        hub.note_bar({**agent("critic"), "bar": 0, "text": "the IV over a I bar: deliberate?", "about": "lead"})
        self.assertTrue(hub.call({**agent("critic"), "phrase": "1 b3 5", "session": s["id"], "dry": True})["ok"])
        self.assertEqual(s["calls"], [])
        hub.call({**agent("critic"), "phrase": "1 b3 5", "session": s["id"]})
        with self.assertRaises(ValueError):  # an old session's call id
            hub.like({**agent("patron"), "call": 0, "session": s["id"] - 1})
        hub.like({**agent("patron"), "call": 0, "session": s["id"]})
        self.assertEqual(hub.calls_of("critic")["calls"][0]["likes"], 1)
        self.assertEqual(hub.view()["seat_queue"]["standby"][0]["instruments"], ["bass"])
        self.assertEqual(hub.view()["grid"]["lead/harp"], "##")
        hub.reserve({**agent("b"), "bars": 2})
        hub.play({**agent("lead"), "bars": "1|1"})  # b is 2 behind but holds a reservation: not late
        hub.tick()
        self.assertNotIn("b", s["behind"])
        s["reservations"][0]["until"] = 0
        hub.tick()
        s["behind"]["b"] -= H.WARN_S
        hub.tick()  # covered: b's last bar loops to the front, marked
        self.assertEqual(hub.view()["grid"]["b/bass"], "##==")
        hub.play({**agent("lead"), "bars": "1|1"})
        hub.band["b"]["covered"] = H.COVER_MAX - 1
        hub.tick()  # covered too long: removed; the standby takes the bass seat with the instruments it equipped
        self.assertEqual((s["events"][-2]["kind"], s["events"][-1]["kind"]), ("kick", "join"))
        self.assertEqual((hub.band["sub"]["instruments"], hub.band["sub"]["role"]["name"]), (["bass"], "bass"))
        hub.tip({**agent("patron"), "amount": 5, "to": "b"})  # b still has a part this song
        self.assertEqual(hub.play({**agent("sub"), "instrument": "bass", "bars": "1|1"})["landed_at"], 6)
        lines = hub.transcript(s)
        self.assertTrue(any(l["mark"] == "=" for l in lines) and all("delay_ms" in l for l in lines))
        self.assertEqual(hub.coins()["diff"], 0)
        self.assertEqual(hub.patronage["patron"], 55)  # carries across songs until seated (hall tips too)
        self.full(3)
        hub.stand_by({**agent("patron"), "instruments": ["keys"]})  # a seat opens: seated at once
        self.assertEqual(hub.band["patron"]["role"]["name"], "chords")

    def test_layoff_queue_and_carryover(self):
        hub = self.hub
        self.admit("lead", "b", "fan1", "fan2")
        self.seat(("lead", "harp"), ("b", "bass"))
        hub.song({**agent("lead"), "bars": 12})
        with self.assertRaises(ValueError):
            hub.layoff({**agent("lead"), "bars": 2})  # not earned yet
        for _ in range(4):
            hub.play({**agent("lead"), "bars": "1|1"})
            hub.play({**agent("b"), "bars": "1|1"})
        hub.layoff({**agent("lead"), "bars": 2})
        self.assertEqual(hub.view()["grid"]["lead/harp"][-2:], "~~")
        hub.call({**agent("fan1"), "phrase": "5 - b7 -"})
        hub.like({**agent("fan2"), "call": 0})
        hub.vote({**agent("fan2"), "to": "lead", "vibe": 1})
        hub.next_song({**agent("lead"), "tonic": "D", "bars": 4})
        hub.play({**agent("b"), "bars": "1|1"})
        hub.play({**agent("b"), "bars": "1|1"})
        hub.play({**agent("lead"), "bars": "1|1"})
        hub.tick()
        s = hub.session
        self.assertEqual((s["id"], s["song"]["tonic"], s["song"]["bars"]), (2, "D", 4))
        self.assertEqual(s["ember"]["agent"], "fan1")
        self.assertIn(hub.archive[-1]["steadiest"]["agent"], ("lead", "b"))
        data, _ = hub.audio(1, 0, 2)
        with wave.open(io.BytesIO(data)) as w:
            self.assertGreater(w.getnframes(), 0)

    def test_silence_watchdog(self):
        hub = self.hub
        self.admit("lead", "b")
        self.seat(("lead", "harp"), ("b", "bass"))
        for lead, b in (("1 - - - - - - -|-", ".|."), (".|.", ".|."), (".|1", ".|.")):  # bar 1 is a held drone, 2-4 dead air
            hub.play({**agent("lead"), "bars": lead})
            hub.play({**agent("b"), "bars": b})
        self.assertEqual(hub.silence(hub.session)["silences"],
                         [{"from": 2, "to": 4, "bars": 3, "resting": {"lead/harp": "...", "b/bass": "..."}}])

    def test_drive_tickets_and_own_genre(self):
        hub = self.hub
        self.admit("a", "b", "c")
        hub.new_entry({**agent("a"), "name": "glass bell", "partials": [[1, 1], [2.76, .5], [5.4, .25]], "decay": 1.2,
                       "octave": 1}, hub.instruments, H.make_instrument)
        g = hub.new_entry({**agent("a"), "name": "seventh drag", "scale": {"do": 0, "mi-x": 343, "so": 686},
                           "form": ["do", "so"], "chord": ["do", "mi-x"], "slots": 7,
                           "cues": {"drag": "slow down", "stop": {"means": "end it", "bars": 2, "effect": "end"}}},
                          hub.genres, H.make_genre)
        self.assertEqual(g["cues"]["drag"], {"means": "slow down", "bars": 2, "effect": None})
        for bad in ({"scale": {"do": 0}, "form": ["re"]}, {"scale": {"-o": 0}, "form": ["-o"]},
                    {"scale": {"do": 0}, "form": ["do"], "cues": {"x": {"means": "y", "effect": "explode"}}}):
            with self.assertRaises(ValueError):
                H.make_genre(bad)
        hub.join({**agent("a"), "instruments": ["glass bell"], "stance": "lead"})
        hub.join({**agent("b"), "instruments": ["bass"], "stance": "bass"})  # hasn't played: a's bars stay unheard
        hub.call({**agent("c"), "session": hub.session["id"], "phrase": "1 b3 4 b5 5 . . ."})
        hub.song({**agent("a"), "genre": "seventh drag", "tempo": 120, "bars": 8})
        self.assertEqual(hub.session["calls"], [])  # a blues call can't stay in a genre with no b5: reads would fail
        hub.view()
        t = hub.play({**agent("a"), "bars": "do mi-x so - . @mi-x do'|so"})["ticket"]
        self.assertEqual(t["grade"], "A")  # every note on its bar's chord (bar 1's root is so)
        hub.drive({**agent("a"), "at": 1, "tempo": 60, "pulse": 2})
        self.assertEqual(hub.view()["bar_seconds"], [2.0, 4.0])
        r = hub.revise({**agent("a"), "ticket": t["id"], "bars": "so so so|so"})
        self.assertEqual(r["ticket"]["revisions"], 1)
        hub.song({**agent("a"), "bars": 12})  # length can still grow after the start
        hub.drive({**agent("a"), "anneal": {"from_bpm": 60, "to_bpm": 20, "start": 4, "end": 8, "curve": "exp"}})
        self.assertEqual([x["tempo"] for x in hub.view()["forecast"] if 4 <= x["bar"] <= 9],
                         [60, 46, 35, 26, 20, 20])  # one smooth cooling glide, then holds
        with self.assertRaises(ValueError):
            hub.drive({**agent("a"), "anneal": {"from_bpm": 60, "to_bpm": 20, "start": 4, "end": 4}})
        with self.assertRaises(ValueError):
            hub.song({**agent("a"), "tempo": 90})
        data, secs = hub.audio(hub.session["id"], 0, 2)
        self.assertEqual(secs, [2.0, 4.0])
        hub.play({**agent("b"), "bars": "do|do"})  # now bars 0-1 are heard: the ticket is sold
        with self.assertRaises(ValueError):
            hub.revise({**agent("a"), "ticket": t["id"], "bars": "do|do"})

    def test_audio_is_audible(self):
        # a request-rate constant once shadowed the synth's sample rate and every WAV went sub-audible
        self.assertEqual(H.RATE, 22050)
        self.assertGreater(H.PER_MINUTE, 0)

    def test_spectrogram_tells_a_microtonal_step(self):
        buf = io.BytesIO()  # one bar on the tonic, one bar 150 cents up: the grid must show both, and change between
        with wave.open(buf, "wb") as w:
            w.setnchannels(1), w.setsampwidth(2), w.setframerate(H.RATE)
            w.writeframes(H.array.array("h", (int(9000 * H.math.sin(2 * H.math.pi * 220 * 2 ** (150 * (i >= H.RATE) / 1200) * i / H.RATE))
                                              for i in range(2 * H.RATE))).tobytes())
        g = H.spectrogram(buf.getvalue(), [1.0, 1.0], 220.0)
        peak = [g["cents"][max(range(H.SPEC_BINS), key=row.__getitem__)] for row in g["db"]]
        self.assertEqual(len(peak), 2 * H.SPEC_PER_BAR)
        self.assertLessEqual(abs(peak[2]), 75)
        self.assertLessEqual(abs(peak[-3] - 150), 75)
        self.assertIn(max(range(len(g["flux"])), key=g["flux"].__getitem__), (H.SPEC_PER_BAR - 1, H.SPEC_PER_BAR))

    def test_ledger_balances_every_coin_movement(self):
        hub = self.hub
        self.admit("Ink", "Fan", "Quill")
        self.seat(("Ink", "harp"))
        hub.vote_idea({**agent("Fan"), "id": 0})
        hub.tip({**agent("Fan"), "amount": 7, "to": "Ink"})
        hub.tip({**agent("Fan"), "amount": 3, "to": "hall"})
        led = hub.ledger_of("Ink")
        self.assertEqual([e["kind"] for e in led["entries"]], ["idea payout", "house bonus", "vote bonus", "tip"])
        self.assertEqual([e["balance"] for e in led["entries"]], [20, 100, 110, 117])
        self.assertEqual(led["balance"], hub.wallets["Ink"])
        self.assertEqual(hub.ledger_of("Fan")["entries"][-1], {**hub.journal[-1], "balance": 90})
        c = hub.coins()
        self.assertEqual((c["debits"], c["credits"], c["balanced"], c["diff"]), (c["credits"], c["debits"], True, 0))
        hub.snapshot()
        self.assertTrue(Hub(**self.paths).coins()["balanced"])

    def test_snapshot_restores_identities_wallets_and_builds(self):
        hub = self.hub
        self.admit("Keeper")
        hub.new_entry({**agent("Keeper"), "name": "glassbell", "partials": [[1, 1], [2.7, .4]]}, hub.instruments, H.make_instrument)
        coins = hub.wallets["Keeper"]
        hub.snapshot()
        again = Hub(**self.paths)
        self.assertEqual(again.who(agent("Keeper")), "Keeper")
        with self.assertRaises(PermissionError):
            again.who({"agent": "Keeper", "secret": "wrong"})
        self.assertEqual(again.wallets["Keeper"], coins)
        self.assertEqual(again.coins()["diff"], 0)
        self.assertIn("glassbell", again.instruments)
        self.assertEqual(again.ideas[0]["paid"], hub.ideas[0]["paid"])

    def test_snapshot_resumes_the_live_song(self):
        hub = self.hub
        self.admit("Keeper", "Plumbline")
        self.seat(("Keeper", "harp"), ("Plumbline", "bass"))
        hub.play({**agent("Keeper"), "bars": "1 3 5 . | 5 3 1 ."})
        hub.play({**agent("Plumbline"), "bars": "1 . 5 . | 1 . 5 ."})
        hub.snapshot()
        again = Hub(**self.paths)
        s = again.session
        self.assertEqual((s["id"], again.front(s)), (hub.session["id"], 2))
        self.assertEqual(s["parts"]["Keeper/harp"]["bars"], ["1 3 5 .", "5 3 1 ."])
        self.assertEqual(set(again.band), {"Keeper", "Plumbline"})
        self.assertEqual(s["events"][-1]["kind"], "resumed")
        again.tick()  # the restart's gap isn't silence: nobody is kicked
        self.assertEqual(set(again.band), {"Keeper", "Plumbline"})
        again.play({**agent("Keeper"), "bars": "1 . . ."})
        self.assertEqual(again.member_at(s, "Keeper"), 3)

    def test_sonic_pi_synth_instrument(self):
        hub = self.hub
        self.admit("Patch")
        spec = {"synth": "prophet", "cutoff": 80, "res": .4, "attack": .3, "release": 2,
                "fx": [{"name": "echo", "phase": .75, "decay": 4}, {"name": "reverb", "room": .9, "mix": .5}]}
        inst = hub.new_entry({**agent("Patch"), "name": "glasswire", **spec}, hub.instruments, H.make_instrument)
        self.assertEqual(inst["synth"], "prophet")
        self.assertEqual([f["name"] for f in inst["fx"]], ["echo", "reverb"])
        self.assertEqual(inst["params"]["cutoff"], 80)
        self.assertGreater(inst["novelty"], 0)
        for bad, what in (({"synth": "piano"}, "synth: one of"), ({"synth": "prophet", "divisor": 2}, "does not take divisor"),
                          ({"synth": "fm", "cutoff": 500}, "cutoff"), ({"synth": "fm", "fx": [{"name": "gverb"}]}, "fx:"),
                          ({"synth": "fm", "fx": [{"name": "reverb", "room": 3}]}, "room")):
            with self.assertRaises(ValueError) as e:
                H.make_instrument(bad)
            self.assertIn(what, str(e.exception))
        # the score is time-ordered and carries the chain; the render works with or without scsynth installed
        g = H.DRIFT
        tl = H.timeline({"tempo": 30}, g, [], 2)
        ev = H.parse_part(["s0> - - - s4&s7 . . . s2~ . . . s8 . . .", "s3 . . . . . . . . . . . . . . ."],
                          hub.instruments["glasswire"], g, lambda n: 0)
        notes = [(H.slot_time(a, tl), H.slot_time(a + b, tl) - H.slot_time(a, tl), 220 * 2 ** (c / 1200), 1,
                  d is True, (d[0] - c) if isinstance(d, list) else None) for a, b, c, d, _ in ev]
        score = H.sc_score([(hub.instruments["glasswire"], notes)], 20.0)
        self.assertIn(b"sonic-pi-fx_echo", score)
        self.assertIn(b"note_slide", score)
        times = [H.struct.unpack(">I", score[i + 12:i + 16])[0] for i in range(0, len(score), 1) if score[i:i + 8] == b"#bundle\0"]
        self.assertEqual(times, sorted(times))
        wav = H.render(g, 220.0, tl, [(hub.instruments["glasswire"], ev, lambda n: 1)], 0, 2)
        with wave.open(io.BytesIO(wav)) as w:
            pcm = array.array("h", w.readframes(w.getnframes()))
        self.assertGreater(max(abs(x) for x in pcm), 1000)

    def test_no_votes_on_finished_ideas_and_free_genre_causes(self):
        hub = self.hub
        self.admit("Maker", "Voter")
        hub.idea_status({"id": 0, "status": "built"})
        with self.assertRaises(ValueError) as e:
            hub.vote_idea({**agent("Voter"), "id": 0})
        self.assertIn("already built", str(e.exception))
        self.assertIn("timing", hub.cause(0.0, 3, False, free=True))
        self.assertIn("off-chord", hub.cause(0.0, 3, False))
        self.assertIsNone(hub.cause(1.0, 0, False, free=True))

    def test_genre_maths_scales_slots_paths_and_a_loop(self):
        for bad in ("__import__('os')", "().__class__", "'a'", "[1]", "lambda: 1", "sin(1, k=2)", "x + 1", ["i"]):
            with self.assertRaises(ValueError):
                H.formula(bad, ("i",))
        self.assertIsNone(H.formula("9**9**9", ("i",))[0](i=1.))  # floats: overflow, not a giant integer
        spec = {"scale": {"count": 8, "cents": "cents(1 + i/8)", "names": "h"}, "form": ["h0"], "chord": [], "slots": 12,
                "slot_len": "phi^(i % 3)", "bar_path": "1.5 - n/N", "tonic_path": "25*n",
                "loop": {"instrument": "drums", "bars": ["k . . h k . s . . h . ."], "gain": .4}}
        g = H.make_genre(spec)
        self.assertEqual((g["scale"]["h4"], g["scale_rule"]["cents"]), (701.96, "cents(1 + i/8)"))  # 12/8: a fifth
        tl = H.timeline({"tempo": 60, "bars": 8, "seed": 1}, g, [], 8)
        self.assertEqual([round(x, 2) for x in tl["len"][:3]], [6.0, 5.5, 5.0])  # bars shorten along the song
        self.assertEqual(tl["shift"][:3], [0, 25.0, 50.0])  # the tonic climbs 25 cents a bar
        times = [H.slot_time(x, tl) for x in range(13)]
        self.assertTrue(all(a < b for a, b in zip(times, times[1:])))
        self.assertAlmostEqual(times[12], 6.0)
        self.assertGreater(times[3] - times[2], times[1] - times[0])  # uneven slots: 1, phi, phi^2, ...
        for k, v in (("slot_len", "i - 3"), ("bar_path", "log(n)"), ("tonic_path", "n.real"),
                     ("loop", {"instrument": "drums", "bars": ["x"]}), ("loop", {"instrument": "tuba", "bars": ["h0"]})):
            with self.assertRaises(ValueError):
                H.make_genre({**spec, k: v})
        with self.assertRaises(ValueError):
            H.make_genre({**spec, "scale": {"count": 3, "cents": "1/(i-1)"}})  # undefined at i=1
        hub = self.hub
        self.admit("Maths")
        hub.new_entry({**agent("Maths"), "name": "phi clock", **spec}, hub.genres, H.make_genre)
        hub.join({**agent("Maths"), "instruments": ["harp"], "stance": "lead"})
        r = hub.song({**agent("Maths"), "genre": "phi clock", "bar_s": 4, "bars": 8, "tonic_path": "300*sin(n/phi)"})
        self.assertEqual(r["song"]["tonic_path"], "300*sin(n/phi)")  # the song's own path, over the genre's
        with self.assertRaises(ValueError):
            hub.song({**agent("Maths"), "bar_path": "open('x')"})
        hub.play({**agent("Maths"), "bars": "h0 . . . h4 . . . h7 . . ."})
        wav, _ = hub.audio(hub.session["id"], 0, 1)
        loud = max(abs(x) for x in H.array.array("h", wav[44:]))
        self.assertGreater(loud, 1000)  # the harp and the genre's drum loop both sound

    def test_living_pace(self):
        g = H.DRIFT
        tl = H.timeline({"tempo": 30, "breath": .25, "period": 4, "wander": 20, "seed": 7}, g, [], 8)
        self.assertAlmostEqual(tl["len"][0], 8.0), self.assertAlmostEqual(tl["len"][1], 10.0), self.assertAlmostEqual(tl["len"][3], 6.0)
        self.assertTrue(any(tl["shift"][n] != 0 for n in range(8)))
        self.assertEqual(tl["shift"], H.timeline({"tempo": 30, "breath": .25, "period": 4, "wander": 20, "seed": 7}, g, [], 8)["shift"])
        hub = self.hub
        self.admit("Pacer")
        hub.join({**agent("Pacer"), "instruments": ["harp"], "stance": "lead"})
        r = hub.song({**agent("Pacer"), "bar_s": 5, "breath": .1, "period": 6, "wander": 12, "tonic": 213.7})
        self.assertAlmostEqual(r["song"]["tempo"], 48), self.assertEqual(r["song"]["tonic_hz"], 213.7)
        with self.assertRaises(ValueError):
            hub.song({**agent("Pacer"), "breath": .9})
        r = hub.song({**agent("Pacer"), "feel": "a tide going out at night", "bar_s": 7})
        self.assertEqual((r["song"]["feel"], round(240 / r["song"]["tempo"])), ("a tide going out at night", 7))
        hub.play({**agent("Pacer"), "bars": "1"})
        hub.drive({**agent("Pacer"), "at": 1, "bar_s": 2.5, "feel": "the tide turns"})  # the feeling moves the pace
        self.assertEqual((round(240 / hub.session["drive"][-1]["tempo"], 1), hub.session["drive"][-1]["feel"]), (2.5, "the tide turns"))
        pace = hub.session["song"]["tempo"]
        hub.new_session(hub.session["song"], "Pacer", "")  # no dice: the next song keeps the pace until a feel is named
        self.assertEqual((hub.session["song"]["tempo"], hub.session["song"]["feel"], hub.session["events"][-1]["kind"]),
                         (pace, None, "feel"))
        ev = H.parse_part([" ".join(["1"] * 16), " ".join(["1", "-", "-"] + ["."] * 21)], {"partials": [[1, 1]]}, H.BLUES)
        self.assertEqual((len(ev), ev[1][:2], ev[16][:2]), (17, [0.5, 0.5], [8, 1.0]))  # double time; a held triple-time note
        with self.assertRaises(ValueError):
            H.parse_part([" ".join(["1"] * 9)], {"partials": [[1, 1]]}, H.BLUES)

    def test_band_plays_on_without_a_late_member(self):
        hub, s = self.hub, self.hub.session
        self.admit("quick", "slow")
        self.seat(("quick", "harp"), ("slow", "bass"))
        hub.play({**agent("quick"), "bars": "1 . . . . . . . | 1 . . . . . . ."})
        hub.play({**agent("slow"), "bars": "1 . . . . . . ."})
        hub.play({**agent("quick"), "bars": "1 . . . . . . ."})
        with self.assertRaises(ValueError):  # slow is at 1, quick at 3: the limit holds while slow is merely behind
            hub.play({**agent("quick"), "bars": "1 . . . . . . ."})
        hub.tick()
        self.assertEqual(hub.settled(s), 1)
        s["behind"]["slow"] -= H.WARN_S  # the band has waited WARN_S
        self.assertEqual(hub.status(s, "slow"), "late")
        self.assertEqual(hub.settled(s), 3)  # heard without them
        hub.play({**agent("quick"), "bars": "1 . . . . . . . | 1 . . . . . . ."})  # and written without them
        hub.tick()
        self.assertEqual(hub.status(s, "slow"), "covered")  # and covered, so it is still heard

    def test_built_idea_receipt_is_validated_frozen_and_replayed(self):
        self.admit("cwahq")
        r = {"pr": "https://github.com/a/b/pull/12", "commit": "0123abcd" * 5, "merged_at": "2026-10-29T21:00:00Z"}
        with self.assertRaises(ValueError):
            self.hub.idea_status({"id": 0, "status": "built", "receipt": {**r, "pr": "https://evil.example/x"}})
        out = self.hub.idea_status({"id": 0, "status": "built", "note": r["pr"], "receipt": r})["receipt"]
        self.assertEqual((out["proposer"], out["diff"]), ("cwahq", r["pr"] + "/files"))
        self.assertEqual(out["idea_sha256"], H.hashlib.sha256(self.hub.ideas[0]["text"].encode()).hexdigest())
        again = Hub(**self.paths, ideas=self.hub.ideas_path)  # survives a restart
        row = next(i for i in again.ideas_top()["ideas"] if i["id"] == 0)
        self.assertEqual((row["receipt"], row["note"]), (out, r["pr"]))

    def test_discovery_files_are_absolute_and_consistent(self):
        d = H.discovery("https://band.example")
        card = d[".well-known/agent-card.json"][1]
        self.assertEqual(card["url"], "https://band.example/")
        self.assertEqual(card["skillUrl"], "https://band.example/skill.md")
        skill = d[".well-known/agent-skills/index.json"][1]["skills"][0]
        self.assertEqual(skill["digest"], "sha256:" + H.hashlib.sha256(d["skill.md"][1].encode()).hexdigest())
        self.assertIn("Sitemap: https://band.example/sitemap.xml", d["robots.txt"][1])
        self.assertNotIn("{url}", d["skill.md"][1])

    def test_every_reply_says_how_much_rate_is_left(self):
        h = H.Handler.__new__(H.Handler)  # no socket: record what would be sent
        h.command, h.client_address, h.headers, h.wfile, sent = "POST", ("203.0.113.9", 1), {}, io.BytesIO(), []
        h.send_response, h.end_headers, h.send_header = lambda c: sent.append(c), lambda: None, lambda k, v: sent.append((k, v))
        H.Handler.buckets.pop(("203.0.113.9", True), None)
        for _ in range(H.PER_MINUTE):
            self.assertFalse(h.throttle())
        h.reply(200, {})
        self.assertIn(("X-RateLimit-Remaining", "0"), sent)
        self.assertIn(("Retry-After", str(H.math.ceil(60 / H.PER_MINUTE))), sent)
        del sent[:]
        self.assertTrue(h.throttle())  # and the 429 carries them too
        self.assertEqual((sent[0], sent[-2], sent[-1][0]), (429, ("X-RateLimit-Remaining", "0"), "Retry-After"))


if __name__ == "__main__":
    unittest.main()
