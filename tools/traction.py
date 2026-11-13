#!/usr/bin/env python3
"""The week's numbers for a GitHub repository, as a short Markdown block, from GitHub's API through `gh api`.

    python3 tools/traction.py                     # krintoxi/sofa, the last 7 days
    python3 tools/traction.py --repo owner/name --days 14
    python3 tools/traction.py --json saved.json   # print a report from numbers saved earlier (no network)
    python3 tools/traction.py --save week.json    # keep the raw answers (GitHub's traffic numbers last 14 days)
    python3 tools/traction.py --record FILE       # add today's answers to a history file that outlives the 14 days
    python3 tools/traction.py --trend FILE        # the history as a table, a week a line (no network)

--record is the one to run on a timer (once a week is enough, once a day loses nothing if a week is skipped): it
keeps every day's visits and clones the first time it sees them, the newer number when a day comes again, and one
line a day of stars, forks, where visitors came from and what was downloaded. The file is plain JSON; keep it
outside the repository.

Needs `gh` signed in to an account that can see the repository's traffic (its owner, or a push collaborator).
Standard library only. Nothing is written anywhere unless --save or --record is given.
"""
import argparse
import datetime as dt
import json
import os
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
    if days >= 14:      # the whole of what GitHub keeps: its own count of different people, not each day's added up
        viewers = (data.get("views") or {}).get("uniques", viewers)
        cloners = (data.get("clones") or {}).get("uniques", cloners)
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


def record(history, data, repo, today):
    """Add what GitHub answered today to the history (a dict, changed and returned). Days are kept for good."""
    history.setdefault("repo", repo)
    days = history.setdefault("days", {})
    for kind, people in (("views", "visitors"), ("clones", "cloners")):
        for d in ((data.get(kind) or {}).get(kind) or []):
            day = days.setdefault(_day(d["timestamp"]), {})
            # A day still running is seen again tomorrow with more in it: the larger number is the later one.
            day[kind] = max(day.get(kind, 0), d.get("count", 0))
            day[people] = max(day.get(people, 0), d.get("uniques", 0))
    r = data.get("repo") or {}
    since = _since(today, 7)
    new = [i for i in (data.get("issues") or []) if _day(i.get("created_at", "")) >= since]
    outside = [i for i in new if (i.get("author_association") or "") not in ("OWNER", "MEMBER", "COLLABORATOR")]
    downloads = {}
    for rel in data.get("releases") or []:
        for a in rel.get("assets") or []:
            if a.get("download_count"):
                downloads[a["name"]] = downloads.get(a["name"], 0) + a["download_count"]
    snap = {
        "date": today,
        "stars": r.get("stargazers_count"), "forks": r.get("forks_count"), "watching": r.get("subscribers_count"),
        "open_issues": r.get("open_issues_count"),
        # GitHub's own count of different people over its 14 days; a week's days added up would count some twice.
        "views_14d": (data.get("views") or {}).get("count"), "visitors_14d": (data.get("views") or {}).get("uniques"),
        "clones_14d": (data.get("clones") or {}).get("count"), "cloners_14d": (data.get("clones") or {}).get("uniques"),
        "issues_from_outside_7d": len([i for i in outside if "pull_request" not in i]),
        "pulls_from_outside_7d": len([i for i in outside if "pull_request" in i]),
        "referrers": [[x.get("referrer"), x.get("uniques", 0)] for x in sorted(data.get("referrers") or [], key=lambda x: -x.get("uniques", 0))[:10]],
        "paths": [[x.get("path"), x.get("uniques", 0)] for x in sorted(data.get("paths") or [], key=lambda x: -x.get("uniques", 0))[:10]],
        "downloads": downloads,
    }
    history["snapshots"] = [x for x in history.get("snapshots", []) if x.get("date") != today] + [snap]
    history["snapshots"].sort(key=lambda x: x.get("date") or "")
    return history


def _monday(day):
    d = dt.date.fromisoformat(day)
    return (d - dt.timedelta(days=d.weekday())).isoformat()


def trend(history):
    """The history as Markdown, a week (Monday to Sunday) a line, oldest first."""
    weeks = {}
    for day, n in sorted((history.get("days") or {}).items()):
        w = weeks.setdefault(_monday(day), {"views": 0, "clones": 0, "days": 0})
        w["views"] += n.get("views", 0)
        w["clones"] += n.get("clones", 0)
        w["days"] += 1
    for snap in history.get("snapshots") or []:
        if snap.get("date"):
            weeks.setdefault(_monday(snap["date"]), {"views": 0, "clones": 0, "days": 0})["last"] = snap   # sorted: the week's last one wins
    lines = ["## %s: week by week" % history.get("repo", "?"), "",
             "| Week of | Page views | Clones | Stars | Forks | Watching | People in 14 days | From outside (issues, pull requests) |",
             "|---|---|---|---|---|---|---|---|"]
    show = lambda v: "" if v is None else str(v)
    for monday in sorted(weeks):
        w = weeks[monday]
        last = w.get("last") or {}
        lines.append("| %s | %d | %d | %s | %s | %s | %s | %s |" % (
            monday, w["views"], w["clones"], show(last.get("stars")), show(last.get("forks")), show(last.get("watching")),
            show(last.get("visitors_14d")),
            ("%d, %d" % (last.get("issues_from_outside_7d", 0), last.get("pulls_from_outside_7d", 0))) if last else ""))
    snaps = history.get("snapshots") or []
    if snaps:
        newest = snaps[-1]
        if newest.get("referrers"):
            lines += ["", "Where visitors came from, as of %s: %s" % (newest["date"], ", ".join("%s (%d)" % (a, b) for a, b in newest["referrers"][:6]))]
        if newest.get("downloads"):
            top = sorted(newest["downloads"].items(), key=lambda x: -x[1])[:8]
            lines += ["", "Downloads, all time: " + " · ".join("%s %d" % (a, b) for a, b in top)]
    lines += ["", "_Page views and clones are each day's numbers added up. \"People in 14 days\" is GitHub's own count of different visitors over the 14 days before the week's last record._"]
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description="The week's GitHub numbers as Markdown.")
    ap.add_argument("--repo", default="krintoxi/sofa")
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--json", help="read saved raw answers from this file instead of asking GitHub")
    ap.add_argument("--save", help="write the raw answers to this file")
    ap.add_argument("--record", metavar="FILE", help="add today's answers to this history file (made if it isn't there)")
    ap.add_argument("--trend", metavar="FILE", help="print this history file as a table, a week a line, and stop")
    ap.add_argument("--today", default=dt.date.today().isoformat(), help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    if a.trend:
        with open(a.trend, encoding="utf-8") as f:
            print(trend(json.load(f)))
        return 0
    if a.json:
        with open(a.json, encoding="utf-8") as f:
            data = json.load(f)
    else:
        data = fetch(a.repo)
    if a.save:
        with open(a.save, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=1)
    if a.record:
        history = {}
        if os.path.exists(a.record):
            with open(a.record, encoding="utf-8") as f:
                history = json.load(f)
        record(history, data, a.repo, a.today)
        tmp = a.record + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=1, sort_keys=True)
        os.replace(tmp, a.record)       # never half a file, whatever stops the run
    print(report(data, a.repo, a.today, a.days))
    return 0


if __name__ == "__main__":
    sys.exit(main())
