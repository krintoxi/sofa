--[[ Sofa box: the TV's player screen, drawn by mpv itself (in place of mpv's own desktop controls, --osc=no).

Every video the box plays goes through mpv with this script: Sofa's films and episodes (as they are or converted),
Live TV, USB drives and discs. It draws, in Sofa's look and inside the TV's safe area (5% in from every edge, so a
TV that crops the picture's edges, "overscan", still shows all of it), at 720p and 1080p alike:

  * the start card, from the moment mpv opens until the picture moves (Resuming <title> from 1:02:03…);
  * the panel along the bottom: title, the time line, where it is, how long is left and when it ends;
  * Skip intro (OK), messages from the box, Live TV's channel banner, the options menu (Menu).

Keys (mpv-input.conf): OK pauses or skips the intro, left and right skip back 10 s and on 30 s (pressed again
quickly, they add up: the line moves at once and the picture follows once you stop), up and down show the panel,
Back stops (exit code 10, so the box knows it was you). The box's agent (sofa-box-agent.py) sends what only it knows
with `script-message-to sofa_player sofa <json>`: {"card": text} while starting (null: it plays), {"toast": text},
{"banner": {...}} (Live TV), {"volume": {"level", "muted"}}, {"menu": {...}} (false closes it). What's playing comes in a file named by the script
option `info` (--script-opts=sofa_player-info=<path>), written before mpv starts, so the start card is there at once.
]]
local mp = require "mp"
local utils = require "mp.utils"
local options = require "mp.options"

local o = { info = "", hide_after = 4.5, scrub_wait = 0.6 }
options.read_options(o, "sofa_player")

local info = {}
if o.info ~= "" then
    local f = io.open(o.info, "r")
    if f then
        info = utils.parse_json(f:read("*a") or "") or {}
        f:close()
    end
end

local W, H = 1920, 1080                 -- drawn as if on a 1080p TV; mpv scales it to the screen (720p alike)
local L, R, T, B = 96, 1824, 54, 1026   -- the safe area: 5% in from each edge
local FONT, TITLE_FONT = "Instrument Sans", "Bricolage Grotesque"
local function bgr(hex, fallback)       -- "FF2E88" (as CSS writes it) -> "882EFF" (as ASS does: blue, green, red)
    hex = tostring(hex or ""):gsub("#", "")
    if not hex:match("^%x%x%x%x%x%x$") then hex = fallback or "FF2E88" end
    return hex:sub(5, 6) .. hex:sub(3, 4) .. hex:sub(1, 2)
end
local WHITE, MIST, INK, PANEL = bgr("FFFFFF"), bgr("C4C4CE"), bgr("000000"), bgr("1A1216")
local ACCENT = bgr(info.accent)         -- the box's theme colour
local function col(c) return "\\1c&H" .. c .. "&" end

local function esc(s)                   -- text as ASS shows it, as written
    s = tostring(s or "")
    s = s:gsub("\\", "\\\239\187\191"):gsub("{", "\\{"):gsub("}", "\\}"):gsub("\n", " ")
    return s
end
local function cut(s, n)                -- long titles end in "…" (ASS would wrap them over the rest)
    s = tostring(s or "")
    local chars = {}
    for ch in s:gmatch("[%z\1-\127\194-\244][\128-\191]*") do chars[#chars + 1] = ch end
    if #chars <= n then return s end
    return table.concat(chars, "", 1, n - 1):gsub("%s+$", "") .. "…"
end

local function clock(t)                 -- 1:02:03 or 2:05
    t = math.max(0, math.floor((t or 0) + 0.5))
    local h, m, s = math.floor(t / 3600), math.floor(t / 60) % 60, t % 60
    if h > 0 then return string.format("%d:%02d:%02d", h, m, s) end
    return string.format("%d:%02d", m, s)
end
local function wall(after)              -- the time it ends, as the TV's clock says it
    local at = os.time() + math.floor(after or 0)
    if info.h24 then return os.date("%H:%M", at) end
    local s = os.date("%I:%M %p", at):gsub("^0", "")
    return s
end

-- drawing: rectangles (rounded) and text, at 1920x1080
local function box(x, y, w, h, r, color, alpha)
    r = math.max(0, math.min(r or 0, w / 2, h / 2))
    local p
    if r == 0 then
        p = string.format("m 0 0 l %g 0 l %g %g l 0 %g", w, w, h, h)
    else
        local k = r * 0.4477            -- (a quarter circle as one curve)
        p = table.concat({
            string.format("m %g 0 l %g 0", r, w - r),
            string.format("b %g 0 %g %g %g %g", w - k, w, k, w, r),
            string.format("l %g %g", w, h - r),
            string.format("b %g %g %g %g %g %g", w, h - k, w - k, h, w - r, h),
            string.format("l %g %g", r, h),
            string.format("b %g %g 0 %g 0 %g", k, h, h - k, h - r),
            string.format("l 0 %g", r),
            string.format("b 0 %g %g 0 %g 0", k, k, r) }, " ")
    end
    return string.format("{\\an7\\pos(%g,%g)\\bord0\\shad0\\blur0%s\\1a&H%s&\\p1}%s{\\p0}", x, y, col(color), alpha or "00", p)
end
local function text(x, y, an, size, s, opts)
    opts = opts or {}
    local c = opts.color or WHITE
    -- bold: Sofa's typefaces are variable fonts (one face, every weight), and libass can't pick a weight from one, so a
    -- thin outline in the text's own colour thickens it (DejaVu, if the fonts aren't there, has a real bold)
    local bold = opts.bold and string.format("\\b1\\bord%g\\3c&H%s&", math.max(0.6, size / 48), c) or "\\b0\\bord0"
    return string.format("{\\an%d\\pos(%g,%g)\\fn%s\\fs%d%s\\shad%s\\4c&H000000&\\4a&H80&%s\\1a&H%s&\\fsp%g}%s",
        an, x, y, opts.font or FONT, size, bold, opts.shadow and "2" or "0", col(c), opts.alpha or "00", opts.space or 0, s)
end

local ov = mp.create_osd_overlay("ass-events")
ov.res_x, ov.res_y, ov.z = W, H, 10

-- what's showing
local state = {
    card = true,                        -- the start card, until the picture moves
    status = info.status or "",         -- the card's second line (the agent says when it's slow)
    panel_until = 0,                    -- the panel shows until then (and while paused)
    paused = false, idle = true,
    target = nil, target_from = nil,    -- skipping: where to, from where (the whole video's seconds)
    toast = nil, toast_until = 0,
    banner = nil, banner_until = 0,
    volume = nil, volume_until = 0,
    menu = nil,
    skip_shown = nil,
}

local offset = tonumber(info.offset) or 0        -- a converted video starts at `offset` into the whole video
local function pos()
    local t = mp.get_property_number("time-pos")
    return t and (t + offset) or nil
end
local function duration()
    local d = tonumber(info.duration) or 0
    if d > 0 then return d end
    local m = mp.get_property_number("duration")
    return m and (m + offset) or 0
end
local function marker(t)                -- an intro or recap on now (the whole video's seconds)
    if not t then return nil end
    for _, m in ipairs(info.markers or {}) do
        if (m.kind == "intro" or m.kind == "recap") and m.start <= t and t < m["end"] - 1 then return m end
    end
    return nil
end

local draw                              -- (below)
local tick = mp.add_periodic_timer(1, function() draw() end)
local shown = nil                       -- what the overlay has now (an update only when that changes)
tick:kill()

local function panel_on() return state.paused or mp.get_time() < state.panel_until or state.target ~= nil end
local function show_panel(secs)
    state.panel_until = mp.get_time() + (secs or o.hide_after)
    draw()
end

local function card_lines()
    local kind = info.kind or "start"
    local label = ({ resume = "RESUMING", start = "STARTING", live = "LIVE TV", file = "PLAYING", disc = "PLAYING" })[kind] or "STARTING"
    local a = {}
    a[#a + 1] = box(0, 0, W, H, 0, INK, "00")
    local y = 470
    a[#a + 1] = text(L + 64, y, 1, 30, label, { bold = true, color = ACCENT, space = 6 })
    a[#a + 1] = text(L + 64, y + 112, 1, 92, esc(cut(info.title or "", 34)), { bold = true, font = TITLE_FONT })
    local sub = info.sub or ""
    if kind == "live" and info.number then sub = tostring(info.number) .. (sub ~= "" and "  ·  " .. sub or "") end
    local next_y = y + 112
    if sub ~= "" then
        next_y = next_y + 58
        a[#a + 1] = text(L + 64, next_y, 1, 40, esc(cut(sub, 60)), { color = MIST })
    end
    local where = kind == "resume" and ("from " .. clock(info.at)) or ""
    next_y = next_y + 74
    a[#a + 1] = text(L + 64, next_y, 1, 34, esc(where) .. (where ~= "" and "   " or "") .. "{" .. col(ACCENT) .. "}•••")
    if state.status ~= "" then
        next_y = next_y + 56
        a[#a + 1] = text(L + 64, next_y, 1, 32, esc(cut(state.status, 90)), { color = MIST })
    end
    a[#a + 1] = text(R, B, 3, 28, "Back stops it", { color = MIST })
    return a
end

local function bar_lines(t, d)
    local a, x0, x1, y = {}, L, R, 948
    local w = x1 - x0
    a[#a + 1] = box(x0, y, w, 10, 5, WHITE, "B0")                     -- the line
    local cache = mp.get_property_number("demuxer-cache-time")
    if cache and d > 0 then
        local c = math.min(1, (cache + offset) / d)
        a[#a + 1] = box(x0, y, math.max(10, w * c), 10, 5, WHITE, "90") -- what it has (converted: made so far)
    end
    local shown = state.target or t
    local f = d > 0 and math.max(0, math.min(1, shown / d)) or 0
    a[#a + 1] = box(x0, y, math.max(10, w * f), 10, 5, ACCENT, "00")
    local kx = x0 + w * f
    a[#a + 1] = box(kx - 14, y - 9, 28, 28, 14, WHITE, "00")             -- where it is
    for _, m in ipairs(info.markers or {}) do                          -- intros and recaps, marked on the line
        if (m.kind == "intro" or m.kind == "recap") and d > 0 then
            a[#a + 1] = box(x0 + w * m.start / d, y + 14, math.max(4, w * (m["end"] - m.start) / d), 4, 2, WHITE, "60")
        end
    end
    if state.target then                                               -- skipping: where it goes, and how far
        local delta = state.target - (state.target_from or t)
        local bx = math.max(x0 + 110, math.min(x1 - 110, kx))
        a[#a + 1] = box(bx - 110, y - 92, 220, 68, 16, INK, "30")
        a[#a + 1] = text(bx, y - 58, 5, 36, clock(state.target), { bold = true })
        a[#a + 1] = text(bx, y - 112, 2, 28, (delta >= 0 and "+" or "−") .. clock(math.abs(delta)), { color = ACCENT, bold = true })
    end
    local left = d > 0 and math.max(0, d - shown) or 0
    a[#a + 1] = text(x0, B, 1, 32, clock(shown))
    if d > 0 then
        local speed = mp.get_property_number("speed") or 1
        a[#a + 1] = text(x1, B, 3, 32, "−" .. clock(left) .. "{" .. col(MIST) .. "}   ·   ends at " .. wall(left / speed))
    end
    return a
end

local function panel_lines()
    local a = {}
    a[#a + 1] = "{\\an7\\pos(0,0)\\bord0\\shad0\\blur70\\1c&H000000&\\1a&H50&\\p1}m -200 760 l 2120 760 l 2120 1300 l -200 1300{\\p0}"
    local live = info.live
    local title = live and ((info.number and (tostring(info.number) .. "  ") or "") .. (info.channel or info.title or "")) or info.title
    a[#a + 1] = text(L, 858, 1, 52, esc(cut(title or "", 40)), { bold = true, font = TITLE_FONT, shadow = true })
    local sub = info.sub or ""
    if sub ~= "" then a[#a + 1] = text(L, 906, 1, 32, esc(cut(sub, 70)), { color = MIST }) end
    if live then
        a[#a + 1] = box(L, 944, 116, 44, 22, ACCENT, "00")
        a[#a + 1] = text(L + 58, 966, 5, 26, "LIVE", { bold = true, color = INK, space = 3 })
        a[#a + 1] = text(R, B, 3, 28, "Up and down change the channel   ·   Back stops it", { color = MIST })
    else
        local t, d = pos() or 0, duration()
        for _, l in ipairs(bar_lines(t, d)) do a[#a + 1] = l end
    end
    if state.paused and not state.card then                            -- paused: a big pause sign, mid-screen
        a[#a + 1] = box(W / 2 - 80, H / 2 - 80, 160, 160, 80, INK, "60")
        a[#a + 1] = box(W / 2 - 30, H / 2 - 38, 20, 76, 4, WHITE, "00")
        a[#a + 1] = box(W / 2 + 10, H / 2 - 38, 20, 76, 4, WHITE, "00")
    end
    return a
end

local function skip_lines(m, raised)
    local label = m.kind == "recap" and "Skip recap" or "Skip intro"
    local w, h = 300, 76
    local x, y = R - w, raised and 760 or (B - h)
    return { box(x, y, w, h, 38, WHITE, "00"),
             text(x + 42, y + h / 2, 4, 34, label, { bold = true, color = INK }),
             box(x + w - 84, y + 18, 58, 40, 20, ACCENT, "00"),
             text(x + w - 55, y + h / 2, 5, 24, "OK", { bold = true }) }
end

local function toast_lines(s)
    local w = math.min(860, 120 + 17 * #s)
    return { box(R - w, T, w, 96, 24, INK, "28"), box(R - w, T, 10, 96, 5, ACCENT, "00"),
             text(R - w + 40, T + 48, 4, 32, esc(cut(s, 52))) }
end

local function banner_lines(b)
    local a, x, y, w, h = {}, L, 724, 980, 230
    a[#a + 1] = box(x, y, w, h, 28, INK, "30")
    local head = (b.number and ("{" .. col(ACCENT) .. "}" .. esc(b.number) .. "  {" .. col(WHITE) .. "}") or "") .. esc(cut(b.name or "", 36))
    a[#a + 1] = text(x + 44, y + 64, 1, 40, head, { bold = true })
    if b.now then a[#a + 1] = text(x + 44, y + 136, 1, 54, esc(cut(b.now, 34)), { bold = true, font = TITLE_FONT })
    elseif b.sub and b.sub ~= "" then a[#a + 1] = text(x + 44, y + 136, 1, 40, esc(cut(b.sub, 46)), { color = MIST }) end
    if b.next then a[#a + 1] = text(x + 44, y + 192, 1, 32, "Next: " .. esc(cut(b.next, 46)), { color = MIST }) end
    return a
end

local function volume_lines(v)
    local w, h, x, y = 420, 118, R - 420, T
    local a = { box(x, y, w, h, 24, INK, "28") }
    local level = tonumber(v.level)
    a[#a + 1] = text(x + 36, y + 42, 4, 32, v.muted and "Sound off" or level and ("Volume  " .. math.floor(level) .. "%") or "Volume", { bold = true })
    if level and not v.muted then
        a[#a + 1] = box(x + 36, y + 80, w - 72, 10, 5, WHITE, "B0")
        a[#a + 1] = box(x + 36, y + 80, math.max(10, (w - 72) * math.min(1, level / 100)), 10, 5, ACCENT, "00")
    end
    return a
end

local function menu_lines(m)
    local a, x, w = {}, R - 640, 640
    local rows = m.rows or {}
    local h = 150 + 84 * #rows + 70
    local y = math.max(T, (H - h) / 2)
    a[#a + 1] = box(0, 0, W, H, 0, INK, "A0")
    a[#a + 1] = box(x, y, w, h, 32, PANEL, "08")
    a[#a + 1] = text(x + 48, y + 92, 1, 46, esc(m.title or "Options"), { bold = true, font = TITLE_FONT })
    for i, r in ipairs(rows) do
        local ry = y + 130 + (i - 1) * 84
        if r.on then a[#a + 1] = box(x + 24, ry, w - 48, 72, 20, ACCENT, "00") end
        a[#a + 1] = text(x + 56, ry + 36, 4, 34, esc(r.label), { bold = r.on })
        if r.value and r.value ~= "" then
            local v = esc(cut(r.value, 22))
            if r.on and r.more then v = "‹  " .. v .. "  ›" end
            a[#a + 1] = text(x + w - 56, ry + 36, 6, 32, v, { color = r.on and WHITE or MIST })
        end
    end
    a[#a + 1] = text(x + 48, y + h - 34, 4, 26, esc(m.hint or "Left and right change it   ·   Back closes"), { color = MIST })
    return a
end

function draw()
    local now = mp.get_time()
    local a = {}
    if state.card then
        for _, l in ipairs(card_lines()) do a[#a + 1] = l end
    else
        local t = pos()
        local m = not info.live and marker(t) or nil
        local panel = panel_on()
        if panel then for _, l in ipairs(panel_lines()) do a[#a + 1] = l end end
        if m and not state.menu then
            if state.skip_shown ~= m.start then state.skip_shown = m.start end
            for _, l in ipairs(skip_lines(m, panel)) do a[#a + 1] = l end
        end
        if state.banner and now < state.banner_until and not panel then
            for _, l in ipairs(banner_lines(state.banner)) do a[#a + 1] = l end
        end
    end
    if state.volume and now < state.volume_until then
        for _, l in ipairs(volume_lines(state.volume)) do a[#a + 1] = l end
    elseif state.toast and now < state.toast_until then
        for _, l in ipairs(toast_lines(state.toast)) do a[#a + 1] = l end
    end
    if state.menu then for _, l in ipairs(menu_lines(state.menu)) do a[#a + 1] = l end end
    local data = table.concat(a, "\n")
    if data ~= shown then
        shown = data
        ov.data = data
        ov:update()
    end
    -- keep ticking while something moves on its own (the time, a message that goes, an intro that comes)
    local busy = panel_on() or (state.toast and now < state.toast_until) or (state.banner and now < state.banner_until) or
                 (state.volume and now < state.volume_until) or
                 (not state.card and not state.paused and #(info.markers or {}) > 0)
    if busy then tick:resume() else tick:kill() end
end

-- the picture moving ends the start card
mp.observe_property("core-idle", "bool", function(_, idle)
    state.idle = idle
    if idle == false and state.card and mp.get_property_number("time-pos") then
        state.card = false
        show_panel(info.live and 0 or 3)
    end
end)
mp.observe_property("pause", "bool", function(_, p)
    state.paused = p or false
    if not state.card then show_panel() end
end)
mp.observe_property("seeking", "bool", function(_, s)
    if s and not state.card and not state.target then show_panel() end    -- (the phone remote's skips show here too)
end)

-- skipping: each press moves the line at once; the picture follows when the presses stop (one seek, not ten)
local scrub = nil
local function skip(by)
    if state.card or info.live then
        if info.live then mp.commandv("seek", tostring(by), "relative") end
        return
    end
    local t = pos()
    if not t then return end
    if not state.target then state.target, state.target_from = t, t end
    local d = duration()
    local lo = offset                                                  -- (converted: it starts at offset)
    local hi = d > 0 and math.max(lo, d - 3) or math.huge
    state.target = math.max(lo, math.min(hi, state.target + by))
    show_panel()
    if scrub then scrub:kill() end
    scrub = mp.add_timeout(o.scrub_wait, function()
        local to = state.target
        state.target, state.target_from, scrub = nil, nil, nil
        if to then mp.commandv("seek", tostring(to - offset), "absolute+keyframes") end
        show_panel()
    end)
end

local function ok()
    if state.menu then return end
    local m = not info.live and marker(pos()) or nil
    if m and not state.card then
        mp.commandv("seek", tostring(m["end"] - offset), "absolute+exact")
        state.skip_shown = nil
        show_panel(2)
        return
    end
    if state.target then return end
    mp.commandv("cycle", "pause")
end

mp.add_key_binding(nil, "ok", ok)
mp.add_key_binding(nil, "toggle", function() mp.commandv("cycle", "pause") end)
mp.add_key_binding(nil, "back", function() mp.commandv("quit", "10") end)           -- 10: stopped by Back
mp.add_key_binding(nil, "show", function() if not state.card then show_panel() end end)
mp.add_key_binding(nil, "back10", function() skip(-10) end, { repeatable = true })
mp.add_key_binding(nil, "on30", function() skip(30) end, { repeatable = true })
mp.add_key_binding(nil, "back300", function() skip(-300) end, { repeatable = true })
mp.add_key_binding(nil, "on300", function() skip(300) end, { repeatable = true })

-- what the box's agent says
mp.register_script_message("sofa", function(json)
    local m = utils.parse_json(json or "") or {}
    if m.card ~= nil then
        if m.card == false then
            if state.card then state.card = false; show_panel(info.live and 0 or 3) end
        else
            state.status = tostring(m.card or "")
        end
    end
    if m.toast then state.toast, state.toast_until = tostring(m.toast), mp.get_time() + (tonumber(m.secs) or 4.5) end
    if m.volume then state.volume, state.volume_until = m.volume, mp.get_time() + 1.8 end
    if m.banner then                    -- (a new channel or programme: its banner, in place of the panel)
        state.banner, state.banner_until = m.banner, mp.get_time() + (tonumber(m.secs) or 5)
        if not state.paused then state.panel_until = 0 end
        if m.banner.name then info.channel = m.banner.name end
        info.number = m.banner.number
        info.sub = m.banner.now or m.banner.sub or info.sub
    end
    if m.menu ~= nil then state.menu = m.menu ~= false and m.menu or nil end
    if m.info then for k, v in pairs(m.info) do info[k] = v end; offset = tonumber(info.offset) or 0 end
    draw()
end)

mp.register_event("end-file", function() tick:kill(); ov:remove() end)
draw()
