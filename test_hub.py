import io, json, os, tempfile, time, unittest, wave
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
            self.hub.join({**agent(n), "instruments": [inst], "role": ROLE[inst]})

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
        self.assertEqual([self.hub.instruments[i]["roles"] for i in ("harp", "keys", "bass", "drums", "guitar")],
                         [["lead"], ["chords", "lead"], ["bass", "lead"], ["percussion", "lead"], ["lead", "chords"]])
        with self.assertRaises(ValueError):
            H.make_instrument({"hits": {"k": {}}, "roles": ["bass"]})  # drums can't hold the bass seat

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

    def test_discovery_texts(self):
        self.assertIn("/how", H.LLMS_TXT)
        self.assertEqual(H.AGENT_CARD["documentationUrl"], "/how")
        H.json.dumps(H.AGENT_CARD)

    def test_admission(self):
        hub = self.hub
        with self.assertRaises(PermissionError):
            hub.join({**agent("a"), "instruments": ["harp"], "role": "lead"})
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
        self.admit("a", "b", "c", "d", "e", "fan")
        with self.assertRaises(ValueError):  # a role your instrument can't play
            hub.join({**agent("a"), "instruments": ["harp"], "role": "bass"})
        self.seat(("a", "harp"), ("b", "keys"), ("c", "bass"), ("d", "drums"))
        with self.assertRaises(PermissionError):
            hub.join({**agent("e"), "instruments": ["harp"], "role": "lead"})
        with self.assertRaises(ValueError):  # b holds the chords seat; drums can't play it
            hub.join({**agent("b"), "instruments": ["drums"]})
        hub.join({**agent("b"), "instruments": ["guitar"]})  # nothing played yet: swap to another chords instrument
        self.assertEqual((hub.band["b"]["instruments"], hub.band["b"]["role"]), (["guitar"], "chords"))
        with self.assertRaises(ValueError):  # 3 bars would be past the slowest member + 2
            hub.play({**agent("a"), "bars": "1|1|1"})
        r = hub.play({**agent("a"), "bars": "1|1"})
        self.assertEqual((r["landed_at"], r["roles"]), (0, ["lead", "lead"]))
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
        r = hub.play({**agent("c"), "bars": "1|1"})
        self.assertEqual(r["cues_for_you"], [])  # the take-it cue is aimed at b
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

    def test_slow_member_warned_skipped_then_kicked(self):
        hub = self.hub
        self.admit("fast", "slow")
        self.seat(("fast", "harp"), ("slow", "bass"))
        hub.play({**agent("fast"), "bars": "1|1"})
        s = hub.session
        hub.tick()
        self.assertEqual(hub.status(s, "slow"), "behind")
        s["behind"]["slow"] -= H.WARN_S
        hub.tick()
        self.assertEqual((hub.status(s, "slow"), s["events"][-1]["kind"]), ("late", "warn"))
        s["behind"]["slow"] -= H.SKIP_S
        hub.tick()
        self.assertEqual((s["events"][-1]["kind"], hub.member_at(s, "slow"), hub.band["slow"]["strikes"]), ("skip", 2, 1))
        hub.play({**agent("fast"), "bars": "1|1"})
        hub.tick()
        s["behind"]["slow"] -= H.SKIP_S
        hub.tick()
        self.assertEqual(s["events"][-1]["kind"], "kick")
        self.assertNotIn("slow", hub.band)

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
        self.seat(("a", "harp"), ("b", "keys"), ("c", "bass"), ("d", "drums"))
        hub.song({**agent("a"), "bars": 4})
        hub.band["b"]["since"] = 0  # b has held chords since the song before: tenured
        hub.stand_by({**agent("sub"), "instruments": ["keys"]})
        for _ in range(2):
            for m in ("a", "b", "c", "d"):
                hub.play({**agent(m), "bars": "1|1" if m != "d" else "k|k"})
        hub.tick()
        done = hub.archive[-1]
        self.assertEqual([(c["out"], c["in"], c["role"]) for c in done["changes"]], [("b", "sub", "chords")])
        self.assertEqual(hub.band["sub"]["role"], "chords")
        self.assertIsNone(hub.delays(done, done["parts"]["a/harp"])[0])  # first written bar is startup, not delay

    def test_song_end_reshuffles_band(self):
        hub = self.hub
        self.admit("good", "dud", "x", "y", "rich", "hummer", "f1", "f2", "f3")
        self.seat(("good", "harp"), ("dud", "keys"), ("x", "bass"), ("y", "drums"))
        hub.song({**agent("good"), "bars": 4, "tonic": 196, "sign": "come in"})
        hub.equip({**agent("rich"), "instruments": ["keys"]})  # rich can only take a chords seat
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
        # dud (-1, chords) goes to the patron with keys; the liked caller (no gear yet) takes y's percussion seat
        self.assertEqual([(c["out"], c["in"], c["role"]) for c in done["changes"]],
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
        hub.join({**agent("a"), "instruments": ["guitar"], "role": "lead"})
        hub.join({**agent("b"), "instruments": ["keys"], "role": "chords"})
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
        self.assertEqual((r["roles_at"]["a"], r["roles_at"]["b"]), ("chords", "lead"))
        self.assertEqual([hub.role_map(s, n)["b"] for n in (1, 2, 3, 4)], ["chords", "lead", "lead", "chords"])
        with self.assertRaises(ValueError):  # the guitar can't play percussion
            hub.trade({**agent("a"), "with": "d"})
        rot = hub.rotate({**agent("a"), "every": 2, "at": 4})["rotation"]
        self.assertEqual(rot["order"], ["a", "b"])  # c's bass and d's drums can't be covered by a's guitar
        self.assertEqual(hub.view()["lead_by_bar"][4:10], ["a", "a", "b", "b", "a", "a"])
        w = hub.waggle({**agent("c"), "direction": "up", "distance": 200, "at": 6})["waggle"]
        hub.follow({**agent("d"), "waggle": w["id"]})
        self.assertIsNone(w["landed"])  # 2 of 4 is not more than half
        hub.follow({**agent("b"), "waggle": w["id"]})
        self.assertEqual(w["landed"], 6)
        self.assertEqual([x["shift"] for x in hub.view()["forecast"] if x["bar"] in (5, 6)], [0, 200])
        with self.assertRaises(ValueError):
            hub.drive({**agent("a"), "shift": 100})  # key changes go through the dance
        hub.equip({**agent("p"), "instruments": ["drums"]})
        self.assertFalse(hub.promote(s, "p", "bass", "test", s["id"]))  # drums can't take a bass seat
        hub.vacate(s, "c", "leave", "test")
        self.assertTrue(hub.promote(s, "q", "bass", "test", s["id"]))  # q has no gear: seat held for them
        with self.assertRaises(ValueError):
            hub.play({**agent("q"), "bars": "1"})
        hub.join({**agent("q"), "instruments": ["bass"]})
        self.assertEqual(hub.status(s, "q"), "ok")

    def test_crowd_and_band_tools(self):
        hub = self.hub
        self.admit("lead", "b", "patron", "sub", "critic")
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
        self.assertEqual(s["events"][-1]["kind"], "over-fire")
        hub.play({**agent("b"), "bars": "1|1"})
        with self.assertRaises(ValueError):
            hub.stand_by({**agent("sub")})  # nothing equipped
        hub.stand_by({**agent("sub"), "instruments": ["bass"]})  # chords and percussion are open: bass can't play them
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
        self.assertEqual(hub.view()["seat_queue"]["standby"][0]["can_play"], ["lead", "bass"])
        self.assertEqual(hub.view()["grid"]["lead/harp"], "##")
        hub.reserve({**agent("b"), "bars": 2})
        hub.play({**agent("lead"), "bars": "1|1"})  # b is 2 behind but holds a reservation: not late
        hub.tick()
        self.assertNotIn("b", s["behind"])
        s["reservations"][0]["until"] = 0
        hub.tick()
        s["behind"]["b"] -= H.SKIP_S
        hub.tick()  # skipped: part filled to the front and marked
        self.assertEqual(hub.view()["grid"]["b/bass"], "##__")
        hub.play({**agent("lead"), "bars": "1|1"})
        hub.tick()
        s["behind"]["b"] -= H.SKIP_S
        hub.tick()  # removed; the standby takes the bass seat with the instruments it equipped
        self.assertEqual((s["events"][-2]["kind"], s["events"][-1]["kind"]), ("kick", "join"))
        self.assertEqual((hub.band["sub"]["instruments"], hub.band["sub"]["role"]), (["bass"], "bass"))
        hub.tip({**agent("patron"), "amount": 5, "to": "b"})  # b still has a part this song
        self.assertEqual(hub.play({**agent("sub"), "instrument": "bass", "bars": "1|1"})["landed_at"], 6)
        lines = hub.transcript(s)
        self.assertTrue(any(l["mark"] == "_" for l in lines) and all("delay_ms" in l for l in lines))
        self.assertEqual(hub.coins()["diff"], 0)
        self.assertEqual(hub.patronage["patron"], 55)  # carries across songs until seated (hall tips too)
        hub.stand_by({**agent("patron"), "instruments": ["keys"]})  # an open role it fits: seated at once
        self.assertEqual(hub.band["patron"]["role"], "chords")

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
        hub.join({**agent("a"), "instruments": ["glass bell"], "role": "lead"})
        hub.join({**agent("b"), "instruments": ["bass"], "role": "bass"})  # hasn't played: a's bars stay unheard
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


if __name__ == "__main__":
    unittest.main()
