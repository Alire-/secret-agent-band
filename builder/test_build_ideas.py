import unittest
from build_ideas import pick


class PickTest(unittest.TestCase):
    def test_pick_voted_untaken_best_first(self):
        ideas = [{"id": 1, "status": "new", "votes": 2, "score": 1.5}, {"id": 2, "status": "building", "votes": 9, "score": 9},
                 {"id": 3, "status": "new", "votes": 0, "score": 0}, {"id": 4, "status": "top", "votes": 3, "score": 2.9},
                 {"id": 5, "status": "declined", "votes": 5, "score": 5}]
        self.assertEqual([i["id"] for i in pick(ideas)], [4, 1])
        self.assertEqual([i["id"] for i in pick(ideas, 1)], [4])


if __name__ == "__main__":
    unittest.main()
