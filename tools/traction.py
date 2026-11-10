#!/usr/bin/env python3
"""The week's numbers for a GitHub repository, as a short Markdown block, from GitHub's API through `gh api`.

    python3 tools/traction.py                     # krintoxi/sofa, the last 7 days
    python3 tools/traction.py --repo owner/name --days 14
    python3 tools/traction.py --json saved.json   # print a report from numbers saved earlier (no network)
    python3 tools/traction.py --save week.json    # keep the raw answers (GitHub's traffic numbers last 14 days)

Needs `gh` signed in to an account that can see the repository's traffic (its owner, or a push collaborator).
Standard library only. Nothing is written anywhere unless --save is given.
"""
import argparse
import datetime as dt
import json
import subprocess
import sys

ENDPOINTS = {
    "repo": "repos/{repo}",
    "views": "repos/{repo}/traffic/views",
    "clones": "repos/{repo}/traffic/clones",
    "referrers": "repos/{repo}/traffic/popular/referrers",
    "paths": "repos/{repo}/traffic/popular/paths",
    "issues": "repos/{repo}/issues?state=all&sort=created&direction=desc&per_page=100",
    "releases": "repos/{repo}/releases?per_page=30",
}


def gh(path):
    out = subprocess.run(["gh", "api", path], capture_output=True, text=True)
    if out.returncode:
        raise SystemExit("gh api %s failed: %s" % (path, (out.stderr or out.stdout).strip()[:300]))
    return json.loads(out.stdout or "null")


def fetch(repo):
    """Every endpoint's raw answer, keyed by name."""
    return {k: gh(v.format(repo=repo)) for k, v in ENDPOINTS.items()}


def _day(stamp):
    return stamp[:10]


def _since(today, days):
    return (dt.date.fromisoformat(today) - dt.timedelta(days=days - 1)).isoformat()


def week(traffic, since):
    """Views or clones from `since` on: (count, uniques); GitHub gives 14 days, per day."""
    days = [d for d in (traffic or {}).get("views", (traffic or {}).get("clones", [])) if _day(d["timestamp"]) >= since]
    return sum(d["count"] for d in days), sum(d["uniques"] for d in days)


def report(data, repo, today, days=7):
    """The Markdown block. `data` is what fetch() returns (or a saved copy); `today` is an ISO date."""
    since = _since(today, days)
    r = data.get("repo") or {}
    views, viewers = week(data.get("views"), since)
    clones, cloners = week(data.get("clones"), since)
    new = [i for i in (data.get("issues") or []) if _day(i.get("created_at", "")) >= since]
    issues = [i for i in new if "pull_request" not in i]
    pulls = [i for i in new if "pull_request" in i]
    outsiders = [i for i in issues if (i.get("author_association") or "") not in ("OWNER", "MEMBER", "COLLABORATOR")]
    refs = sorted(data.get("referrers") or [], key=lambda x: -x.get("uniques", 0))[:6]
    paths = sorted(data.get("paths") or [], key=lambda x: -x.get("uniques", 0))[:5]
    downloads = []
    for rel in data.get("releases") or []:
        for a in rel.get("assets") or []:
            if a.get("download_count"):
                downloads.append((a["download_count"], a["name"], rel.get("tag_name") or ""))
    downloads.sort(reverse=True)

    lines = ["## %s: the %d days to %s" % (repo, days, today), ""]
    lines.append("- **Stars** %s · forks %s · watching %s · open issues %s"
                 % (r.get("stargazers_count", "?"), r.get("forks_count", "?"), r.get("subscribers_count", "?"), r.get("open_issues_count", "?")))
    lines.append("- **Visits** %d page views by %d people · **clones** %d by %d" % (views, viewers, clones, cloners))
    lines.append("- **New** %d issue%s (%d from outside) · %d pull request%s"
                 % (len(issues), "" if len(issues) == 1 else "s", len(outsiders), len(pulls), "" if len(pulls) == 1 else "s"))
    if refs:
        lines.append("- **From** " + ", ".join("%s (%d)" % (x.get("referrer"), x.get("uniques", 0)) for x in refs))
    if paths:
        lines.append("- **Read** " + ", ".join("`%s` (%d)" % (x.get("path"), x.get("uniques", 0)) for x in paths))
    if downloads:
        lines.append("- **Downloads, all time** " + " · ".join("%s %d" % (name, n) for n, name, _ in downloads[:8]))
    if issues:
        lines.append("")
        lines.append("New issues:")
        for i in issues[:12]:
            lines.append("- #%s %s (%s)" % (i.get("number"), i.get("title", "").strip(), (i.get("user") or {}).get("login", "?")))
    lines.append("")
    lines.append("_GitHub keeps traffic for 14 days: save this block somewhere (a Discussions thread, a file) or it's gone._")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description="The week's GitHub numbers as Markdown.")
    ap.add_argument("--repo", default="krintoxi/sofa")
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--json", help="read saved raw answers from this file instead of asking GitHub")
    ap.add_argument("--save", help="write the raw answers to this file")
    ap.add_argument("--today", default=dt.date.today().isoformat(), help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    if a.json:
        with open(a.json, encoding="utf-8") as f:
            data = json.load(f)
    else:
        data = fetch(a.repo)
    if a.save:
        with open(a.save, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=1)
    print(report(data, a.repo, a.today, a.days))
    return 0


if __name__ == "__main__":
    sys.exit(main())
