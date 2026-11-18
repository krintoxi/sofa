"""Watching together: a room where two or more people on this Sofa watch one title in step, each on their own screen.

Someone starts a room from the player and is its host. The others join with the room's code (six letters) or its
link, signed in to one of this Sofa's profiles: never a Visitor from the share link, and not a guest from the guest QR
code either. Play, pause, skips and speed follow the host; the host can let everyone steer. A room never plays a title
from the Adult section, and a Kids profile joins only rooms whose title its rules allow (sofa/web.py checks both).

The room keeps one timeline, not a list of commands: where the video was (`pos`) at a moment on this server's clock
(`at`), whether it's paused, and at what speed. Every screen works out from that where it should be now, and puts its
own player there (sofa/web.py has the routes, client/app.js the player's side). Someone who joins late, or whose
connection dropped for a while, reads the same timeline and lands in the same place.

A screen asks for news and waits for it (one request at a time, answered the moment the room changes, as the phone
remote's screens do), so it works wherever the player works: at home, over Tailscale, or from the internet over
HTTPS, with nothing outside Sofa. Everything is in memory: nothing is written down, a room ends when its last person
leaves, and a screen not heard from for a while is taken out of the room.
"""
import random
import threading
import time

WAIT = 25               # a screen's wait for news is answered after this long at most
GONE = 45               # a screen not heard from for this long has left the room
ENDED_KEPT = 300        # how long a room's end is remembered, to tell its people why it went
MAX_ROOMS = 32
MAX_MEMBERS = 16
MAX_HOURS = 24          # a room older than this ends when it's next quiet
LETTERS = "BCDFGHJKLMNPQRSTVWXZ"      # 20 consonants: no vowels (no words), no I/O/0/1 to mix up
CODE_LEN = 6
MISSES = 12             # wrong codes from one profile in MISS_WINDOW seconds, then it has to wait
MISS_WINDOW = 600
ACTS = ("play", "pause", "seek", "rate", "item", "everyone")
RATES = (0.5, 2.0)

_cond = threading.Condition()
_rooms = {}             # code -> room
_ended = {}             # code -> (why, when)
_misses = {}            # user id -> [times of wrong codes]
_rng = random.SystemRandom()


class Refused(Exception):
    """Not allowed, or not there: the status for the answer and what to say."""

    def __init__(self, status, message):
        super().__init__(message)
        self.status, self.message = status, message


def clock():
    """This server's clock for rooms: steady (a change to the computer's time doesn't move it) and fine-grained."""
    return time.perf_counter()


def normal_code(code):
    return "".join(c for c in str(code or "").upper() if c in LETTERS)[:CODE_LEN]


def _key(user, tab):
    return "%s:%s" % (user["id"], str(tab or "")[:40])


def _position(room, at=None):
    if room["paused"]:
        return room["pos"]
    return max(0.0, room["pos"] + ((clock() if at is None else at) - room["at"]) * room["rate"])


def _set_time(room, pos, paused=None, rate=None):
    room["pos"], room["at"] = max(0.0, float(pos)), clock()
    if paused is not None:
        room["paused"] = bool(paused)
    if rate is not None:
        room["rate"] = rate


def _clean():
    now, wall = clock(), time.time()
    for code, room in list(_rooms.items()):
        for key in [k for k, m in room["members"].items() if now - m["seen"] > GONE]:
            _drop(room, key, "You were away too long, so you left the room.")
        if not room["members"] or wall - room["made"] > MAX_HOURS * 3600:
            del _rooms[code]
            _ended[code] = ("The room ended." if room["members"] else "Everyone left, so the room ended.", wall)
    for code in [c for c, (_, at) in _ended.items() if wall - at > ENDED_KEPT]:
        del _ended[code]


def _drop(room, key, why):
    """Takes someone out of the room: they're told `why` when they next ask. A host leaving hands the room on."""
    m = room["members"].pop(key, None)
    if not m:
        return
    room["gone"][key] = why
    if room["host"] == key and room["members"]:
        room["host"] = min(room["members"].values(), key=lambda x: x["joined"])["key"]
        _note(room, "host", room["members"][room["host"]]["name"])
    else:
        _note(room, "left", m["name"])


def _note(room, act, by, t=None):
    room["rev"] += 1
    room["last"] = {"act": act, "by": by, "t": round(t, 2) if t is not None else None, "rev": room["rev"]}
    _cond.notify_all()


def _member(user, tab, device):
    return {"key": _key(user, tab), "user": {k: user.get(k) for k in ("id", "name", "admin", "adult", "kids", "guest", "visitor")},
            "name": str(user.get("name") or "Someone")[:40], "avatar": user.get("avatar") or 0,
            "device": str(device or "")[:40], "joined": clock(), "seen": clock(), "gen": 0}


def _new_code():
    for _ in range(100):
        code = "".join(_rng.choice(LETTERS) for _ in range(CODE_LEN))
        if code not in _rooms and code not in _ended:
            return code
    raise Refused(503, "Couldn't make a room just now. Try again.")


def _view(room, key):
    """The room as one of its people sees it."""
    host = room["members"].get(room["host"])
    me = room["members"].get(key)
    may = bool(me) and (key == room["host"] or room["everyone"])
    return {"code": room["code"], "item": room["item"], "pos": round(room["pos"], 3), "at": room["at"], "now": clock(),
            "paused": room["paused"], "rate": room["rate"], "rev": room["rev"], "everyone": room["everyone"],
            "host": host["name"] if host else "", "is_host": key == room["host"], "may_steer": may, "last": room["last"],
            "members": [{"name": m["name"], "avatar": m["avatar"], "device": m["device"], "host": m["key"] == room["host"],
                         "you": m["key"] == key} for m in sorted(room["members"].values(), key=lambda x: x["joined"])]}


def _room(code):
    code = normal_code(code)
    room = _rooms.get(code)
    if room is None:
        why = _ended.get(code)
        raise Refused(410 if why else 404, why[0] if why else "There's no room with that code. Check the letters, or ask for the link again.")
    return room


def _missed(user):
    now = time.time()
    times = [t for t in _misses.get(user["id"], []) if now - t < MISS_WINDOW] + [now]
    _misses[user["id"]] = times
    return len(times) > MISSES


def _rate(value):
    try:
        r = float(value)
    except (TypeError, ValueError):
        raise Refused(400, "That speed isn't one Sofa plays at.")
    if not RATES[0] <= r <= RATES[1]:
        raise Refused(400, "That speed isn't one Sofa plays at.")
    return round(r, 3)


def _time(value, room):
    if value is None:
        return _position(room)
    try:
        t = float(value)
    except (TypeError, ValueError):
        raise Refused(400, "That isn't a place in the video.")
    if t != t or t < 0 or t > 100 * 3600:           # (not a number, before the start, or nowhere near any video)
        raise Refused(400, "That isn't a place in the video.")
    return t


# ------------------------------------------------------------ what the routes call


def start(user, tab, device, item_id, pos=0, paused=False, rate=1):
    """A new room playing `item_id` from `pos`, with this screen as its host. A screen already in a room leaves it."""
    with _cond:
        _clean()
        key = _key(user, tab)
        for room in list(_rooms.values()):
            if key in room["members"]:
                _drop(room, key, "You started another room.")
        _clean()
        if len(_rooms) >= MAX_ROOMS:
            raise Refused(503, "This Sofa has as many rooms open as it can take. Try again when one has ended.")
        room = {"code": _new_code(), "item": str(item_id), "pos": 0.0, "at": clock(), "paused": False, "rate": 1.0,
                "rev": 0, "everyone": False, "members": {}, "gone": {}, "made": time.time(), "last": None, "host": key}
        _set_time(room, _time(pos, room), paused, _rate(rate))
        room["members"][key] = _member(user, tab, device)
        _rooms[room["code"]] = room
        _note(room, "start", room["members"][key]["name"])
        return _view(room, key)


def peek(user, code):
    """The room behind a code, for someone about to join: (its item, its host's name). A wrong code counts."""
    with _cond:
        _clean()
        if _missed_recently(user):
            raise Refused(429, "That's a lot of wrong codes. Wait a few minutes, then try again.")
        try:
            room = _room(code)
        except Refused:
            _missed(user)
            raise
        host = room["members"].get(room["host"])
        return room["item"], host["name"] if host else ""


def _missed_recently(user):
    now = time.time()
    return len([t for t in _misses.get(user["id"], []) if now - t < MISS_WINDOW]) >= MISSES


def join(user, tab, device, code):
    """This screen in the room (again, if it was already): the room as it sees it."""
    with _cond:
        _clean()
        room = _room(code)
        key = _key(user, tab)
        if key not in room["members"]:
            if len(room["members"]) >= MAX_MEMBERS:
                raise Refused(409, "That room is full (%d screens)." % MAX_MEMBERS)
            room["gone"].pop(key, None)
            room["members"][key] = _member(user, tab, device)
            _note(room, "joined", room["members"][key]["name"])
        return _view(room, key)


def wait(user, tab, code, since):
    """News for this screen: the room as soon as it's changed since `since` (or after a while anyway), or why this
    screen is no longer in it ({"gone": why})."""
    deadline = time.time() + WAIT
    with _cond:
        _clean()
        key = _key(user, tab)
        try:
            room = _room(code)
        except Refused as exc:
            return {"gone": exc.message}
        m = room["members"].get(key)
        if m is None:
            return {"gone": room["gone"].get(key) or "You're not in this room any more."}
        m["seen"] = clock()
        m["gen"] += 1
        gen = m["gen"]
        _cond.notify_all()                              # (this screen's wait from before, if any, is answered now)
        while room["rev"] <= since and time.time() < deadline and m["gen"] == gen and _rooms.get(room["code"]) is room \
                and key in room["members"]:
            _cond.wait(max(0.1, deadline - time.time()))
            m["seen"] = clock()
        if _rooms.get(room["code"]) is not room:
            why = _ended.get(room["code"])
            return {"gone": why[0] if why else "The room ended."}
        if key not in room["members"]:
            return {"gone": room["gone"].get(key) or "You're not in this room any more."}
        return _view(room, key)


def steer(user, tab, code, act, t=None, rate=None, item=None, everyone=None, may_see=None):
    """Play, pause, a skip, the speed, another title (`item`, from `t`), or the host's "everyone can steer".
    `may_see(user, item_id)` says whether a profile may watch a title: whoever may not is taken out of the room."""
    if act not in ACTS:
        raise Refused(400, "Rooms don't do that.")
    with _cond:
        _clean()
        room = _room(code)
        key = _key(user, tab)
        m = room["members"].get(key)
        if m is None:
            raise Refused(403, "You're not in this room any more.")
        m["seen"] = clock()
        host = room["members"].get(room["host"])
        if act == "everyone":
            if key != room["host"]:
                raise Refused(403, "Only the host chooses who steers.")
            room["everyone"] = bool(everyone)
            _note(room, "everyone" if room["everyone"] else "host-only", m["name"])
            return _view(room, key)
        if key != room["host"] and not room["everyone"]:
            raise Refused(403, "%s is steering this room." % (host["name"] if host else "The host"))
        if act == "play":
            _set_time(room, _time(t, room), paused=False)
        elif act == "pause":
            _set_time(room, _time(t, room), paused=True)
        elif act == "seek":
            _set_time(room, _time(t, room))
        elif act == "rate":
            _set_time(room, _time(t, room), rate=_rate(rate))
        elif act == "item":
            item = str(item or "")
            if not item or (may_see and not may_see(m["user"], item)):
                raise Refused(404, "That video isn't in the library any more.")
            room["item"] = item
            _set_time(room, _time(t if t is not None else 0, room), paused=False)
            for other in [x for x in room["members"].values() if x["key"] != key]:
                if may_see and not may_see(other["user"], item):
                    _drop(room, other["key"], "The room moved on to something this profile can't watch.")
        _note(room, act, m["name"], room["pos"])
        return _view(room, key)


def leave(user, tab, code, end=False):
    """This screen out of the room. The host can end it for everyone instead."""
    with _cond:
        try:
            room = _room(code)
        except Refused:
            return
        key = _key(user, tab)
        if key not in room["members"]:
            return
        if end:
            if key != room["host"]:
                raise Refused(403, "Only the host can end the room.")
            del _rooms[room["code"]]
            _ended[room["code"]] = ("%s ended the room." % room["members"][key]["name"], time.time())
            _cond.notify_all()
            return
        _drop(room, key, "You left the room.")
        _clean()


def rooms_of(user_id):
    """The codes of the rooms a profile is in (for the tests and the Server page)."""
    with _cond:
        _clean()
        return sorted(code for code, room in _rooms.items() if any(m["user"]["id"] == user_id for m in room["members"].values()))


def reset():
    """Every room gone (the tests)."""
    with _cond:
        _rooms.clear()
        _ended.clear()
        _misses.clear()
        _cond.notify_all()
