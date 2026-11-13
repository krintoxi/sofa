# Security

Sofa sits on a home network and, if you switch that on, answers from the internet. A hole in it matters, so
reports of one are welcome and get read first.

## Reporting a problem

**Please don't open a public issue for it.** Use either of these:

- **GitHub:** the repository's **Security** tab → **Report a vulnerability** (a private report only the maintainers see).
- **Email:** hello@edgeventure.uk, with "Sofa security" in the subject.

What helps: the Sofa or Sofa Box OS version (Server → Updates, or the box's Settings → This box → About), how Sofa is
reached (at home only, Tailscale, or its own address on the internet), the steps, and what someone could do with it.
A box's report code (Settings → Help → Send a report) is fine to include; nothing in it names what was watched.

We answer as soon as we can, say what we found, fix it in a new version, and name you in the changelog if you'd like
that. There is no bounty.

## What counts

Anything that lets someone who shouldn't: sign in or stay signed in, read or change the library, another profile or
the settings, reach files outside the library's folders, run a command on the computer or the box, get past a Kids
profile or a PIN, see more of a shared library than the titles its owner picked, or reach Sofa from the internet
when it is set to answer the home network only.

How Sofa is meant to behave away from home is in [docs/remote-access.md](docs/remote-access.md), and everything it
sends or fetches over the internet is listed in [docs/privacy.md](docs/privacy.md). Where the code does something
else, that's a report.

## Which versions get fixes

The newest Sofa and the newest Sofa Box OS card. Both update themselves from their own pages (Server → Updates;
Settings → Software → Update the box), and Docker by pulling the new image, so a fix reaches an install in one step.
Older versions aren't patched.
