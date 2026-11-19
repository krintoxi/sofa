/* What the lists of games say about a game: the rows it sits in, the facts on its card, and where you left it.

   One file for both lists: the Sofa Box's Games page (home/home.js) and Sofa's own in a browser (client/app.js), so
   the two say the same thing. Nothing here draws; it reads games.json's entries and the games' own saves.

     SofaShelf.KINDS            the rows by kind, in order: [id, title]
     SofaShelf.players(n)       "1 player", "1 or 2 players", "1 to 4 players"
     SofaShelf.facts(game)      the card's facts, in order: kind, 2D or 3D, who plays, what it's played with
     SofaShelf.where(id, get)   where a game was left, from its own save: { line, pct } (pct only where the game has an
                                end to count towards), or null when it hasn't been played here. `get` reads a key of
                                the page's storage (k => localStorage.getItem(k)): the games keep their saves there, at
                                the same address as the lists.
     SofaShelf.rows(games)      the games row by row: [{ id, title, games }], no row empty

   A save is read, never written, and a save that isn't the shape its game writes is as good as none: the tests take
   each game's own fresh save from its page and check these lines against it, so a game that changes what it keeps
   shows up there and not on a TV. */
(function (root) {
  "use strict";
  const KINDS = [["adventure", "Adventures"], ["action", "Action"], ["racing", "Racing"], ["mind", "Puzzles and tactics"], ["arcade", "Quick ones"]];
  const WITH = { controller: "Controller", keys: "Keyboard", touch: "Touch", remote: "TV remote" };
  const players = n => n >= 4 ? "1 to 4 players" : n >= 2 ? "1 or 2 players" : "1 player";
  const facts = g => [g.kind, g.dim, players(g.players || 1)].concat((g.with || []).map(w => WITH[w])).filter(Boolean);

  const obj = (get, key) => { try { const v = JSON.parse(get(key) || "null"); return v && typeof v === "object" ? v : null; } catch (e) { return null; } };
  const num = (get, key) => { try { const v = +get(key); return v > 0 && isFinite(v) ? Math.floor(v) : 0; } catch (e) { return 0; } };
  const count = o => o && typeof o === "object" ? Object.keys(o).filter(k => o[k]).length : 0;
  const whole = v => typeof v === "number" && isFinite(v) && v >= 0 ? Math.floor(v) : null;
  const of = (n, all, what) => ({ line: n >= all ? "All " + all + " " + what : n + " of " + all + " " + what, pct: Math.round(100 * Math.min(n, all) / all) });
  // the one being played of a game's three, or the one that has got furthest
  const slotOf = (slots, last, far) => {
    const s = (Array.isArray(slots) ? slots : []).filter(x => x && typeof x === "object");
    return (Array.isArray(slots) && slots[last] && typeof slots[last] === "object" ? slots[last] : null) || s.sort((a, b) => far(b) - far(a))[0] || null;
  };
  const WHERE = {
    wyrd(get) {
      const s = obj(get, "wyrd"), d = s && slotOf(s.slots, s.last, x => x.level | 0);
      return d && whole(d.level) ? { line: (d.name ? String(d.name).slice(0, 16) + ", level " : "Level ") + whole(d.level) } : null;
    },
    gloamwell(get) {
      const d = slotOf([0, 1, 2].map(i => obj(get, "gloamwell-slot-" + i)), -1, x => x.lvl | 0);
      if (!d || !whole(d.lvl)) return null;
      return { line: "Level " + whole(d.lvl) + (whole(d.deepest) ? ", down to floor " + whole(d.deepest) : "") };
    },
    "cinder-knight"(get) {
      const s = obj(get, "cinder-knight"), d = s && slotOf(s.slots, s.slot, x => x.reached | 0);
      return !d || whole(d.reached) == null ? null : d.done ? { line: "Finished", pct: 100 } : { line: "Stage " + (whole(d.reached) + 1) };
    },
    "shadow-heist"(get) {
      const s = obj(get, "shadow-heist"), n = s && whole(s.reached);
      return n ? of(n, 12, "heists pulled") : null;
    },
    "rune-tactics"(get) {
      const s = obj(get, "rune-tactics");
      if (!s) return null;
      if (s.camp && typeof s.camp === "object" && count(s.camp.done)) return of(count(s.camp.done), 15, "battles won");
      return s.wins && s.wins.campaigns > 0 ? { line: "Campaign won", pct: 100 } : s.camp ? { line: "Campaign begun", pct: 0 } : null;
    },
    "micro-drifters"(get) {
      const s = obj(get, "micro-drifters");
      if (!s) return null;
      const cups = count(s.cups), races = whole(s.races) || 0;
      return cups ? { line: cups + (cups === 1 ? " cup" : " cups") + " with a medal" } : races ? { line: races + (races === 1 ? " race run" : " races run") } : null;
    },
    "neon-brawler"(get) {
      const s = obj(get, "neon-brawler");
      if (!s) return null;
      const n = whole(s.reached) || 0, best = whole(s.best) || 0;
      return n ? { line: "Stage " + Math.min(5, n + 1) + " of 5", pct: Math.round(100 * Math.min(4, n) / 5) } : best ? { line: "Best: " + best } : null;
    },
    "void-drifter"(get) {
      const s = obj(get, "void-drifter");
      if (!s) return null;
      const deep = whole(s.deepest) || 0, runs = whole(s.runs) || 0;      // (the game's own words for it, on its records)
      return deep >= 4 ? { line: "All the way through", pct: 100 } : runs || deep ? { line: "Zone " + Math.max(1, deep + (runs ? 1 : 0)) + " reached" } : null;
    },
    "cosmic-cascade"(get) {
      const s = obj(get, "cosmic-cascade");
      if (!s) return null;
      const n = count(s.solved), best = s.endless && whole(s.endless.score) || 0;
      return n ? of(n, 60, "boards solved") : best ? { line: "Best: " + best } : null;
    },
    tidewing(get) {
      const s = obj(get, "tidewing");
      if (!s) return null;
      const open = whole(s.open) || 0, cups = count(s.cups);
      return open > 1 || cups ? of(Math.max(1, open), 12, "courses open") : count(s.best) ? { line: "First course run", pct: 8 } : null;
    },
    ironmaw(get) {
      const s = obj(get, "ironmaw"), n = s && whole(s.reached);
      return n > 1 || (s && count(s.best)) ? { line: "Level " + Math.min(9, Math.max(1, n)) + " of 9", pct: Math.round(100 * (Math.min(9, Math.max(1, n)) - 1) / 9) } : null;
    },
    halogen(get) {
      const s = obj(get, "halogen"), n = s && count(s.best);                // (a race it has a best for is a race run)
      return n ? of(n, 6, "races run") : null;
    },
    "neon-dodge"(get) { const n = num(get, "neonDodgeHi"); return n ? { line: "Best: " + n } : null; },
    "sky-hop"(get) { const n = num(get, "skyHopHi"); return n ? { line: "Best: " + n } : null; },
    "pair-up"(get) { const n = num(get, "pairBest"); return n ? { line: "Best: " + n + (n === 1 ? " turn" : " turns") } : null; }
  };
  function where(id, get) {
    try { const w = Object.prototype.hasOwnProperty.call(WHERE, id) ? WHERE[id](get) : null; return w && w.line ? w : null; } catch (e) { return null; }
  }
  function rows(games) {
    return KINDS.map(([id, title]) => ({ id, title, games: games.filter(g => g.shelf === id) })).filter(r => r.games.length);
  }
  const api = { KINDS, WITH, players, facts, where, rows, saved: Object.keys(WHERE) };
  if (typeof module === "object" && module.exports) module.exports = api; else root.SofaShelf = api;
})(typeof window === "object" ? window : globalThis);
