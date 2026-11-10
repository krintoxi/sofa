# Launch checklist

**The gate, before anything is posted anywhere:** the owner has tested a card on the Pi 3 B+ and marked it stable
(`deploy/sofa-box/STABLE` names a version). Until then, nothing goes out. The one allowed exception: **the Sofa Server
can launch first, with the box called beta in every post**, once the owner has decided to do that in so many words.

**Who posts:** the owner, from their own accounts. The files in this folder are drafts. No session, script or
workflow in this repository posts anything anywhere.

**r/opensource is out.** Its rules expect an OSI-approved licence; Sofa's PolyForm Noncommercial 1.0.0 isn't one.
Every post says "source-available" in its first lines.

## Before day 1

- [ ] Merge the launch pull request (demo GIF, `docs/compare.md`, `docs/roadmap.md`, this folder, `tools/traction.py`).
- [ ] Upload `docs/images/social-preview.png`: repository Settings → Social preview → Upload an image (no API for it).
- [ ] Pin the welcome discussion (https://github.com/krintoxi/sofa/discussions/47, the ⋯ menu) and add a **Weekly**
      category under Settings → Discussions for the Monday numbers. Suggested extra category: **"Does it run on X?"**
      (or keep those in Q&A with the device in the title; either way the answers go into the tested-on table).
- [ ] Run `python3 tools/traction.py` once and paste the block into a Weekly post, so week 0 is on record.
- [ ] Test the newest card on the Pi; if it passes, write its number into `deploy/sofa-box/STABLE` and merge.
- [ ] Read each community's rules on the day (they change; the quotes in this folder carry the date they were read).

## Day by day

1. **Day 1, the repository.** The merged README (GIF, "Why not Jellyfin or Plex?", Status), topics and description
   (done 2026-11-10), the social preview uploaded, Discussions pinned.
2. **Day 2, the demo.** `docs/images/demo.gif` and `demo.mp4` are in the repository; if a longer narrated video is
   wanted, record it from the same rig (the session notes say how) and host it where the owner likes.
3. **Day 3, r/selfhosted.** A comment in the current **New Project Megathread** ([reddit-selfhosted.md](reddit-selfhosted.md)):
   "all new projects can only be posted here", "Standalone new project posts will be removed" (the megathread's
   own text, read 2026-05-16 snapshot; the repository is a new project there until late January 2027). Answer
   every reply the same day.
4. **Day 4, the article.** [dev-article.md](dev-article.md) on DEV. Also submit the project to selfh.st's weekly
   newsletter (their site has a submission form) and open the awesome-selfhosted non-free pull request
   (`awesome-selfhosted/awesome-selfhosted-data`, `software/sofa.yml`, `non_free: true`; check their
   `licenses-nonfree.yml` has PolyForm Noncommercial, add it if not).
5. **Day 5, testers.** Reply to every "does it run on X" with the hardware report link; add each report to the
   tested-on table the same week.
6. **Day 6, fixes.** Fix what the week found; release; write "what changed" as a Discussions announcement.
7. **Day 7, Show HN**, only when the gate has passed and the Fire TV app and the Roku channel have each run once on a
   real device ([show-hn.md](show-hn.md)). Tuesday to Thursday, 8 to 10 am Eastern, six hours at the keyboard.
   Product Hunt the week after (Tuesday to Thursday, 12:01 am Pacific; gallery: the GIF and six screenshots;
   tagline "Your own streaming service at home, and your own TV box"). r/raspberry_pi and r/homelab that week too,
   the box angle, with a stable card to point at.

## Every Monday

`python3 tools/traction.py` → paste into the Weekly thread. GitHub keeps traffic numbers for 14 days only. Watch, in
this order: hardware reports from machines the owner doesn't have, issues from strangers, clones, unique visitors,
stars, card downloads.

## Rules read, with dates

- **r/selfhosted** (the New Project Megathread, u/AutoModerator, read from a 2026-05-16 snapshot): "This weekly thread
  is the new official home for sharing your new projects (younger than three months) with the community", "all new
  projects can only be posted here", "Standalone new project posts will be removed", "You can post here ANY day of
  the week". The subreddit's wiki rules page couldn't be fetched from here on 2026-11-10 (Reddit blocks non-browser
  clients); read the sidebar before posting.
- **Hacker News, Show HN** (news.ycombinator.com/showhn.html, read 2026-11-10): "The project must be something you've
  worked on personally and which you're around to discuss." "If your work isn't ready for users to try out, please
  don't do a Show HN." "Please don't ask friends to upvote or comment."
- **DEV** (dev.to/terms, section 11, read 2026-11-10): not "designed primarily for the purposes of promotion or creating
  backlinks"; "Posts must contain substantial content".
- **r/raspberry_pi, r/homelab:** not fetched from here on 2026-11-10; read their sidebars on the day.
