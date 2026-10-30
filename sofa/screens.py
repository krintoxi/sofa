"""Screens: every open Sofa page is a screen that can be told what to play.

A phone (or any other device signed in as the same person) sees that person's other screens that
are open right now (the TV in the living room, a laptop), sends one a video and controls it:
pause, skip, seek, next episode, stop. The TV asks for commands and waits for them (one request
at a time, answered the moment there's something to do), and says what it's playing.

Only the same person's screens are listed or controlled, with one exception: a guest at home (the
guest QR code) sees the house's TVs and can send them something from what guests can watch. A guest
never sees what a TV is playing unless a guest started it. Everything is in memory, on the home
network: nothing is written down, and a screen that's closed is forgotten within a minute.
"""
import threading
import time

WAIT = 25           # a screen's request for commands is answered after this long at most
GONE = 70           # a screen not heard from for this long is closed
COMMANDS = ("play", "toggle", "pause", "resume", "seek", "skip", "next", "stop")

_cond = threading.Condition()
_screens = {}       # id -> {"id", "name", "user", "tv", "seen", "gen", "queue", "state", "from"}


def _clean():
    cut = time.time() - GONE
    for sid in [k for k, s in _screens.items() if s["seen"] < cut]:
        del _screens[sid]


def wait(screen_id, name, user_id, tv):
    """A screen asking for commands: returns them as soon as there are any, or [] after a while."""
    deadline = time.time() + WAIT
    with _cond:
        _clean()
        s = _screens.get(screen_id)
        if s is None or s["user"] != user_id:          # new, or the same browser signed in as someone else
            s = _screens[screen_id] = {"id": screen_id, "queue": [], "state": {}, "gen": 0}
        s.update(name=(name or "Screen")[:40], user=user_id, tv=bool(tv), seen=time.time())
        s["gen"] += 1
        gen = s["gen"]
        while not s["queue"] and time.time() < deadline and s["gen"] == gen:
            _cond.wait(max(0.1, deadline - time.time()))
            s["seen"] = time.time()
        if s["gen"] != gen:                             # the page asked again (reloaded): that request answers
            return []
        out, s["queue"] = s["queue"], []
        return out


def report(screen_id, user_id, state):
    """What a screen is playing now: {"item", "t", "d", "paused"} or {} when nothing."""
    with _cond:
        s = _screens.get(screen_id)
        if s and s["user"] == user_id:
            s["state"] = {k: state.get(k) for k in ("item", "t", "d", "paused") if k in state}
            s["state"]["at"] = time.time()
            s["seen"] = time.time()


def listing(user_id, exclude=None):
    """This person's open screens (not the asking one), most recently used first."""
    with _cond:
        _clean()
        out = [{"id": s["id"], "name": s["name"], "tv": s["tv"], "state": s["state"]}
               for s in _screens.values() if s["user"] == user_id and s["id"] != exclude]
    return sorted(out, key=lambda s: (not s["tv"], -(s["state"].get("at") or 0), s["name"]))


def send(screen_id, user_id, command, sender_name):
    """Queue a command for one of this person's screens. False if there's no such screen open."""
    if command.get("cmd") not in COMMANDS:
        return False
    with _cond:
        s = _screens.get(screen_id)
        if not s or s["user"] != user_id:
            return False
        cmd = {k: command[k] for k in ("cmd", "item", "t", "by") if k in command}
        cmd["from"] = (sender_name or "")[:40]
        s["queue"].append(cmd)
        _cond.notify_all()
        return True


def tvs_for_guest(exclude=None):
    """The TVs a guest at home can send things to (any person's), without what they're playing."""
    with _cond:
        _clean()
        out = [{"id": s["id"], "name": s["name"], "tv": True,
                "state": s["state"] if s.get("guest_item") and s["state"].get("item") == s["guest_item"] else {}}
               for s in _screens.values() if s["tv"] and s["id"] != exclude]
    return sorted(out, key=lambda s: s["name"])


def send_as_guest(screen_id, command, sender_name):
    """A guest's command for a TV. False if there's no such TV, or it's something a guest can't ask."""
    if command.get("cmd") not in COMMANDS:
        return False
    with _cond:
        s = _screens.get(screen_id)
        if not s or not s["tv"]:
            return False
        if command["cmd"] != "play" and s["state"].get("item") != s.get("guest_item"):
            return False                     # only what a guest started can be paused, skipped or stopped by one
        cmd = {k: command[k] for k in ("cmd", "item", "t", "by") if k in command}
        cmd["from"] = ((sender_name or "A guest")[:40])
        if cmd["cmd"] == "play":
            s["guest_item"] = cmd.get("item")
        s["queue"].append(cmd)
        _cond.notify_all()
        return True
