"""tools/traction.py: the week's GitHub numbers as Markdown, from canned answers (no network, no gh)."""
import importlib.util
import json
import os
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("traction", os.path.join(HERE, "..", "tools", "traction.py"))
traction = importlib.util.module_from_spec(spec)
spec.loader.exec_module(traction)

CANNED = {
    "repo": {"stargazers_count": 41, "forks_count": 3, "subscribers_count": 5, "open_issues_count": 4},
    "views": {"count": 900, "uniques": 300, "views": [
        {"timestamp": "2026-11-01T00:00:00Z", "count": 500, "uniques": 200},       # before the week: left out
        {"timestamp": "2026-11-04T00:00:00Z", "count": 100, "uniques": 40},
        {"timestamp": "2026-11-09T00:00:00Z", "count": 250, "uniques": 50},
        {"timestamp": "2026-11-10T00:00:00Z", "count": 50, "uniques": 10}]},
    "clones": {"count": 30, "uniques": 20, "clones": [
        {"timestamp": "2026-11-02T00:00:00Z", "count": 20, "uniques": 15},
        {"timestamp": "2026-11-08T00:00:00Z", "count": 10, "uniques": 5}]},
    "referrers": [{"referrer": "news.ycombinator.com", "count": 300, "uniques": 120},
                  {"referrer": "reddit.com", "count": 200, "uniques": 90}],
    "paths": [{"path": "/krintoxi/sofa", "title": "x", "count": 400, "uniques": 200},
              {"path": "/krintoxi/sofa/blob/main/docs/compare.md", "title": "y", "count": 80, "uniques": 60}],
    "issues": [
        {"number": 50, "title": "Runs on a Pi 5 ", "created_at": "2026-11-09T10:00:00Z", "author_association": "NONE", "user": {"login": "someone"}},
        {"number": 49, "title": "Docker image", "created_at": "2026-11-08T10:00:00Z", "author_association": "OWNER", "user": {"login": "krintoxi"}},
        {"number": 48, "title": "Fix a typo", "created_at": "2026-11-08T09:00:00Z", "author_association": "NONE", "user": {"login": "x"}, "pull_request": {"url": "u"}},
        {"number": 20, "title": "Old one", "created_at": "2026-10-20T09:00:00Z", "author_association": "NONE", "user": {"login": "y"}}],
    "releases": [{"tag_name": "sofa-box", "assets": [{"name": "sofa-box.img.xz", "download_count": 14}, {"name": "sofa-box-report.txt", "download_count": 0}]},
                 {"tag_name": "sofa-box-stable", "assets": [{"name": "sofa-box-stable.img.xz", "download_count": 3}]}],
}


class Report(unittest.TestCase):
    def test_the_week_s_numbers(self):
        md = traction.report(CANNED, "krintoxi/sofa", "2026-11-10")
        self.assertIn("## krintoxi/sofa: the 7 days to 2026-11-10", md)
        self.assertIn("**Stars** 41 · forks 3 · watching 5 · open issues 4", md)
        self.assertIn("**Visits** 400 page views by 100 people · **clones** 10 by 5", md)   # only the days from 11-04 on
        self.assertIn("**New** 2 issues (1 from outside) · 1 pull request", md)
        self.assertIn("news.ycombinator.com (120), reddit.com (90)", md)
        self.assertIn("`/krintoxi/sofa/blob/main/docs/compare.md` (60)", md)
        self.assertIn("sofa-box.img.xz 14 · sofa-box-stable.img.xz 3", md)
        self.assertNotIn("sofa-box-report.txt", md)                                       # nothing downloaded: left out
        self.assertIn("- #50 Runs on a Pi 5 (someone)", md)
        self.assertNotIn("#20", md)
        self.assertIn("14 days", md)

    def test_fourteen_days_and_empty_answers(self):
        md = traction.report(CANNED, "krintoxi/sofa", "2026-11-10", days=14)
        self.assertIn("the 14 days to", md)
        self.assertIn("**Visits** 900 page views by 300 people · **clones** 30 by 20", md)
        bare = traction.report({}, "o/r", "2026-01-01")
        self.assertIn("**Stars** ? · forks ?", bare)
        self.assertIn("**Visits** 0 page views by 0 people", bare)
        self.assertNotIn("**From**", bare)

    def test_main_reads_a_saved_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "week.json")
            with open(path, "w") as f:
                json.dump(CANNED, f)
            import contextlib, io
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = traction.main(["--json", path, "--today", "2026-11-10"])
            self.assertEqual(code, 0)
            self.assertIn("**Stars** 41", out.getvalue())


if __name__ == "__main__":
    unittest.main()
