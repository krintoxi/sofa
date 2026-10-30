' Sofa for Roku. One scene, a few views shown one at a time:
'   find  - which Sofa (found on the network, or a typed address)
'   pair  - a code to type on a phone that's signed in to Sofa (Sofa -> your picture -> Pair a TV)
'   home  - Continue watching, Shows, Movies
'   show  - a show's episodes, a row per season
'   video - Roku's own player
' Sofa's address and the sign-in are kept in the registry, so next time it goes straight to Home.

sub init()
    m.reg = CreateObject("roRegistrySection", "sofa")
    m.base = m.reg.Read("server")
    m.token = m.reg.Read("token")
    m.tasks = []
    m.view = ""
    m.back = "home"
    m.status = m.top.findNode("status")
    m.findView = m.top.findNode("findView")
    m.findHint = m.top.findNode("findHint")
    m.serverList = m.top.findNode("serverList")
    m.pairView = m.top.findNode("pairView")
    m.pairCode = m.top.findNode("pairCode")
    m.pairHint = m.top.findNode("pairHint")
    m.homeView = m.top.findNode("homeView")
    m.rows = m.top.findNode("rows")
    m.showView = m.top.findNode("showView")
    m.showTitle = m.top.findNode("showTitle")
    m.episodes = m.top.findNode("episodes")
    m.video = m.top.findNode("video")
    m.pollTimer = m.top.findNode("pollTimer")

    m.serverList.observeField("itemSelected", "onServerChosen")
    m.rows.observeField("rowItemSelected", "onHomeChosen")
    m.episodes.observeField("rowItemSelected", "onEpisodeChosen")
    m.video.observeField("state", "onVideoState")
    m.video.observeField("position", "onVideoPosition")
    m.video.notificationInterval = 1
    m.pollTimer.observeField("fire", "onPollTimer")
    m.caps = deviceCaps()

    if m.base <> "" and m.token <> "" then
        say("Connecting to Sofa…")
        api("GET", "/api/session", invalid, "session")
    else if m.base <> "" then
        showPair()
    else
        showFind("")
    end if
end sub

' ---------------------------------------------------------------- talking to Sofa

sub api(method as string, path as string, body as object, tag as string)
    t = CreateObject("roSGNode", "ApiTask")
    t.observeField("response", "onApi")
    t.request = { method: method, url: m.base + path, body: body, token: m.token, tag: tag }
    t.control = "run"
    m.tasks.Push(t)
end sub

sub onApi(ev as object)
    r = ev.getData()
    done = ev.getRoSGNode()
    keep = []
    for each t in m.tasks
        if not t.isSameNode(done) then keep.Push(t)
    end for
    m.tasks = keep
    tag = r.tag
    if tag = "session" then
        onSession(r)
    else if tag = "info" then
        onInfo(r)
    else if tag = "pairStart" then
        onPairStart(r)
    else if tag = "pairPoll" then
        onPairPoll(r)
    else if tag = "library" then
        m.library = r.json
        if m.library = invalid then
            failed(r)
        else
            api("GET", "/api/progress", invalid, "progress")
        end if
    else if tag = "progress" then
        m.progress = r.json
        if m.progress = invalid then m.progress = {}
        showHome()
    else if tag = "play" then
        onPlan(r)
    else if tag = "hls" then
        onHls(r)
    end if
end sub

sub failed(r as object)
    if r.code = 401 then
        m.token = ""
        m.reg.Delete("token")
        m.reg.Flush()
        showPair()
    else if r.code = 0 then
        showFind("Sofa didn't answer at " + m.base + ". Is the Sofa computer on?")
    else if r.json <> invalid and r.json.error <> invalid then
        say(r.json.error)
    else
        say("Sofa said no (" + r.code.ToStr() + ").")
    end if
end sub

sub say(text as string)
    m.status.text = text
    if text <> "" then print "[sofa] "; text
end sub

sub showOnly(view as string)
    print "[sofa] view: "; view
    m.view = view
    m.findView.visible = view = "find"
    m.pairView.visible = view = "pair"
    m.homeView.visible = view = "home"
    m.showView.visible = view = "show"
    m.video.visible = view = "video"
    if view <> "pair" then m.pollTimer.control = "stop"
    say("")
end sub

' What this Roku plays itself, so Sofa only converts what it has to.
function deviceCaps() as string
    di = CreateObject("roDeviceInfo")
    hevc = di.CanDecodeVideo({ Codec: "hevc" }).result = true
    hevc10 = di.CanDecodeVideo({ Codec: "hevc", Profile: "main 10" }).result = true
    ac3 = di.CanDecodeAudio({ Codec: "ac3" }).result = true
    return "mkv=1&hevc=" + flag(hevc) + "&hevc10=" + flag(hevc10) + "&ac3=" + flag(ac3) + "&vp9=0"
end function

function flag(on as boolean) as string
    if on then return "1"
    return "0"
end function

function esc(text as string) as string
    return CreateObject("roUrlTransfer").Escape(text)
end function

' "/art/shows/The Sopranos/folder.jpg?v=12" -> a full address with each part escaped, at `width` pixels.
function artUrl(path as dynamic, width as integer) as string
    if path = invalid or path = "" then return ""
    parts = path.Split("?")
    segments = parts[0].Split("/")
    out = []
    for each s in segments
        out.Push(esc(s))
    end for
    url = m.base + out.Join("/")
    if parts.Count() > 1 then url = url + "?" + parts[1] + "&w=" + width.ToStr() else url = url + "?w=" + width.ToStr()
    return url
end function

' ---------------------------------------------------------------- finding Sofa

sub showFind(problem as string)
    showOnly("find")
    if problem <> "" then m.findHint.text = problem else m.findHint.text = "Looking for Sofa on your home network…"
    m.found = []
    fillServers()
    m.serverList.setFocus(true)
    d = CreateObject("roSGNode", "DiscoveryTask")
    d.observeField("servers", "onServers")
    d.control = "run"
    m.discovery = d
end sub

sub onServers(ev as object)
    m.found = ev.getData()
    print "[sofa] found "; m.found.Count(); " Sofa"
    if m.view <> "find" then return
    if m.found.Count() = 0 then
        m.findHint.text = "No Sofa found. Is the Sofa computer on, and on the same network? You can type its address."
    else
        m.findHint.text = "Pick your Sofa."
    end if
    fillServers()
end sub

sub fillServers()
    c = CreateObject("roSGNode", "ContentNode")
    for each s in m.found
        it = c.CreateChild("ContentNode")
        it.title = s.name + "   " + s.url
    end for
    c.CreateChild("ContentNode").title = "Look again"
    c.CreateChild("ContentNode").title = "Type the address…"
    m.serverList.content = c
end sub

sub onServerChosen()
    i = m.serverList.itemSelected
    if i < m.found.Count() then
        m.base = m.found[i].url
        m.reg.Write("server", m.base)
        m.reg.Flush()
        showPair()
    else if i = m.found.Count() then
        showFind("")
    else
        k = CreateObject("roSGNode", "StandardKeyboardDialog")
        k.title = "The Sofa computer's address"
        k.message = ["Like 192.168.1.20 (Sofa's Server page shows it under Addresses)."]
        k.buttons = ["OK", "Cancel"]
        k.observeField("buttonSelected", "onAddressTyped")
        m.top.dialog = k
    end if
end sub

sub onAddressTyped()
    k = m.top.dialog
    typed = k.text.Trim()
    k.close = true
    m.serverList.setFocus(true)
    if k.buttonSelected <> 0 or typed = "" then return
    if Left(typed, 4) <> "http" then typed = "http://" + typed
    if typed.Right(1) = "/" then typed = typed.Left(typed.Len() - 1)
    m.tries = [typed]
    if CreateObject("roRegex", ":\d+$", "").IsMatch(typed) = false then m.tries = [typed + ":8090", typed]
    say("Looking at " + typed + "…")
    tryNext()
end sub

sub tryNext()
    if m.tries.Count() = 0 then
        m.findHint.text = "There's no Sofa at that address. Check it on Sofa's Server page (Addresses)."
        say("")
        return
    end if
    m.base = m.tries.Shift()
    api("GET", "/api/info", invalid, "info")
end sub

sub onInfo(r as object)
    if r.json <> invalid and r.json.sofa = true then
        m.reg.Write("server", m.base)
        m.reg.Flush()
        showPair()
    else
        tryNext()
    end if
end sub

' ---------------------------------------------------------------- signing in with a phone

sub showPair()
    showOnly("pair")
    m.pairCode.text = "……"
    m.pairHint.text = "Getting a code from Sofa…"
    m.top.setFocus(true)
    model = CreateObject("roDeviceInfo").GetModelDisplayName()
    if Left(model, 4) <> "Roku" then model = "Roku " + model
    api("POST", "/api/pair/start", { name: model }, "pairStart")
end sub

sub onPairStart(r as object)
    if r.json = invalid or r.json.code = invalid then
        if r.code = 0 then
            showFind("Sofa didn't answer at " + m.base + ". Is the Sofa computer on?")
        else if r.json <> invalid and r.json.error <> invalid then
            m.pairHint.text = r.json.error
        end if
        return
    end if
    code = r.json.code
    m.pairCode.text = code.Left(3) + " " + code.Mid(3)
    print "[sofa] pairing code "; code
    m.pairHint.text = "On your phone, open Sofa, press your picture at the top, then Pair a TV, and type this code. Or open " + r.json.url + " on your phone. Press * to use a different Sofa."
    m.poll = r.json.poll
    m.pollTimer.control = "start"
end sub

sub onPollTimer()
    if m.view = "pair" and m.poll <> invalid then api("GET", "/api/pair/poll?poll=" + esc(m.poll), invalid, "pairPoll")
end sub

sub onPairPoll(r as object)
    if m.view <> "pair" or r.json = invalid then return
    if r.json.state = "approved" then
        m.pollTimer.control = "stop"
        m.token = r.json.token
        m.reg.Write("token", m.token)
        m.reg.Flush()
        loadHome()
    else if r.json.state = "expired" then
        m.pollTimer.control = "stop"
        showPair()
    end if
end sub

sub onSession(r as object)
    if r.json <> invalid and r.json.user <> invalid then
        loadHome()
    else
        failed(r)
    end if
end sub

' ---------------------------------------------------------------- Home

sub loadHome()
    say("Loading your library…")
    api("GET", "/api/library", invalid, "library")
end sub

sub showHome()
    showOnly("home")
    m.byId = {}
    for each s in m.library.shows
        for each season in s.seasons
            for each e in season.episodes
                e.showId = s.id
                m.byId[e.id] = e
            end for
        end for
        m.byId[s.id] = s
    end for
    for each mv in m.library.movies
        m.byId[mv.id] = mv
    end for

    root = CreateObject("roSGNode", "ContentNode")
    going = []
    for each id in m.progress
        p = m.progress[id]
        if p.done <> true and p.t > 30 and m.byId.DoesExist(id) then going.Push({ id: id, at: p.at })
    end for
    going.SortBy("at", "r")
    if going.Count() > 0 then
        row = root.CreateChild("ContentNode")
        row.title = "Continue watching"
        for i = 0 to going.Count() - 1
            if i >= 20 then exit for
            addPoster(row, m.byId[going[i].id])
        end for
    end if
    shows = m.library.shows
    shows.SortBy("name", "i")
    if shows.Count() > 0 then
        row = root.CreateChild("ContentNode")
        row.title = "Shows"
        for each s in shows
            addPoster(row, s)
        end for
    end if
    movies = m.library.movies
    movies.SortBy("title", "i")
    if movies.Count() > 0 then
        row = root.CreateChild("ContentNode")
        row.title = "Movies"
        for each mv in movies
            addPoster(row, mv)
        end for
    end if
    m.rows.content = root
    if root.getChildCount() = 0 then say("Nothing in the library yet. Add videos on the Sofa computer.") else say("Press * to change the Sofa computer or sign out.")
    m.rows.setFocus(true)
end sub

sub addPoster(row as object, x as object)
    it = row.CreateChild("ContentNode")
    it.addFields({ sofaId: x.id })
    if x.kind = "episode" then
        s = m.byId[x.showId]
        it.title = s.name + "  S" + x.s.ToStr() + " E" + x.e.ToStr()
        it.HDPosterUrl = artUrl(s.poster, 360)
    else if x.seasons <> invalid then
        it.title = x.name
        it.HDPosterUrl = artUrl(x.poster, 360)
    else
        it.title = x.title
        it.HDPosterUrl = artUrl(x.poster, 360)
    end if
    it.ShortDescriptionLine2 = part(x.id)
end sub

' How much of it has been watched, "0".."1" ("" when not started).
function part(id as string) as string
    if m.progress = invalid or not m.progress.DoesExist(id) then return ""
    p = m.progress[id]
    if p.done = true then return "1"
    if p.d = invalid or p.d <= 0 then return ""
    return Str(p.t / p.d).Trim()
end function

sub onHomeChosen()
    pick = m.rows.rowItemSelected
    it = m.rows.content.getChild(pick[0]).getChild(pick[1])
    x = m.byId[it.sofaId]
    if x.seasons <> invalid then
        showShow(x)
    else
        m.back = "home"
        play(x)
    end if
end sub

' ---------------------------------------------------------------- a show

sub showShow(s as object)
    showOnly("show")
    m.show = s
    m.showTitle.text = s.name
    root = CreateObject("roSGNode", "ContentNode")
    focusRow = 0
    focusItem = 0
    r = 0
    for each season in s.seasons
        row = root.CreateChild("ContentNode")
        if season.n = 0 then row.title = "Specials" else row.title = "Season " + season.n.ToStr()
        i = 0
        for each e in season.episodes
            it = row.CreateChild("ContentNode")
            it.addFields({ sofaId: e.id })
            name = "Episode " + e.e.ToStr()
            if e.title <> invalid and e.title <> "" then name = e.title
            it.title = "E" + e.e.ToStr() + " · " + name
            if e.thumb <> invalid then it.HDPosterUrl = artUrl(e.thumb, 400) else it.HDPosterUrl = artUrl(s.poster, 400)
            it.ShortDescriptionLine2 = part(e.id)
            p = part(e.id)
            if p <> "" and p <> "1" then
                focusRow = r
                focusItem = i
            end if
            i = i + 1
        end for
        r = r + 1
    end for
    m.episodes.content = root
    m.episodes.jumpToRowItem = [focusRow, focusItem]
    m.episodes.setFocus(true)
end sub

sub onEpisodeChosen()
    pick = m.episodes.rowItemSelected
    it = m.episodes.content.getChild(pick[0]).getChild(pick[1])
    m.back = "show"
    play(m.byId[it.sofaId])
end sub

' The episode after this one, or invalid.
function nextEpisode(x as object) as object
    if x.kind <> "episode" then return invalid
    s = m.byId[x.showId]
    take = false
    for each season in s.seasons
        for each e in season.episodes
            if take then return e
            if e.id = x.id then take = true
        end for
    end for
    return invalid
end function

' ---------------------------------------------------------------- playing

sub play(x as object)
    m.item = x
    say("Getting it ready…")
    api("GET", "/api/play/" + esc(x.id) + "?" + m.caps, invalid, "play")
end sub

sub onPlan(r as object)
    p = r.json
    if p = invalid then
        failed(r)
        return
    end if
    if p.mode = "unsupported" then
        say(p.message)
        return
    end if
    m.plan = p
    m.resume = 0
    if m.progress.DoesExist(m.item.id) then
        q = m.progress[m.item.id]
        if q.done <> true and q.t > 30 and (p.duration = invalid or q.t < p.duration - 30) then m.resume = q.t
    end if
    if p.mode = "direct" then
        startVideo(m.base + p.url, formatOf(m.item), m.resume, 0)
    else
        say("Converting it for this Roku…")
        api("GET", "/api/hls/" + esc(m.item.id) + "?mode=" + p.mode + "&t=" + Str(m.resume).Trim() + "&" + m.caps, invalid, "hls")
    end if
end sub

sub onHls(r as object)
    if r.json = invalid or r.json.url = invalid then
        failed(r)
        return
    end if
    startVideo(m.base + r.json.url, "hls", 0, m.resume)
end sub

function formatOf(x as object) as string
    name = ""
    if x.file <> invalid then name = LCase(x.file)
    if name.Right(4) = ".mkv" then return "mkv"
    return "mp4"
end function

' Converted video starts where they left off: 0 in the stream is `offset` seconds into the video.
sub startVideo(url as string, fmt as string, start as float, offset as float)
    c = CreateObject("roSGNode", "ContentNode")
    c.url = url
    c.streamFormat = fmt
    name = "Sofa"
    if m.item.kind = "episode" then
        name = m.byId[m.item.showId].name + "  S" + m.item.s.ToStr() + " E" + m.item.e.ToStr()
    else if m.item.title <> invalid then
        name = m.item.title
    end if
    c.title = name
    c.HttpHeaders = ["Authorization: Bearer " + m.token, "X-Sofa: 1"]
    if start > 0 then c.PlayStart = start
    subs = []
    for each s in m.plan.subtitles
        u = m.base + s.url
        if offset > 0 then u = u + "?offset=" + Str(offset).Trim()
        subs.Push({ Language: s.lang, TrackName: u, Description: s.label })
    end for
    c.SubtitleTracks = subs
    m.offset = offset
    m.duration = 0
    if m.plan.duration <> invalid then m.duration = m.plan.duration
    m.lastSave = 0
    m.started = false
    showOnly("video")
    m.video.content = c
    m.video.setFocus(true)
    m.video.control = "play"
end sub

sub onVideoState()
    state = m.video.state
    if state = "playing" and not m.started then
        m.started = true
        ' A converted video's playlist grows as Sofa converts; Roku may start at its end. Start at the start.
        if m.offset > 0 or m.plan.mode <> "direct" then
            if m.video.position > 15 then m.video.seek = 0
        end if
    else if state = "finished" then
        save(true)
        nxt = nextEpisode(m.item)
        if nxt <> invalid then
            play(nxt)
        else
            leaveVideo()
        end if
    else if state = "error" then
        say("This video stopped: " + m.video.errorMsg)
        leaveVideo()
    end if
end sub

sub onVideoPosition()
    if m.video.position - m.lastSave >= 10 or m.lastSave - m.video.position > 10 then
        m.lastSave = m.video.position
        save(false)
    end if
end sub

sub save(done as boolean)
    if m.item = invalid then return
    if not m.started and not done then return        ' Back before it began: keep where they were
    t = m.offset + m.video.position
    d = m.duration
    if d <= 0 then d = m.offset + m.video.duration
    if d <= 0 then return
    if done or t > d * 0.95 then
        done = true
        t = d
    end if
    m.progress[m.item.id] = { t: t, d: d, done: done, at: CreateObject("roDateTime").AsSeconds() * 1000 }
    api("POST", "/api/progress/" + esc(m.item.id), { t: t, d: d, done: done }, "saved")
end sub

sub leaveVideo()
    m.video.control = "stop"
    m.video.content = invalid
    if m.back = "show" then showShow(m.show) else showHome()
end sub

' ---------------------------------------------------------------- the remote

function onKeyEvent(key as string, press as boolean) as boolean
    if not press then return false
    if key = "back" then
        if m.view = "video" then
            save(false)
            leaveVideo()
            return true
        else if m.view = "show" then
            showHome()
            return true
        else if m.view = "pair" then
            showFind("")
            return true
        end if
    else if key = "options" then
        if m.view = "home" or m.view = "pair" then
            d = CreateObject("roSGNode", "StandardMessageDialog")
            d.title = "Sofa"
            d.message = ["Connected to " + m.base]
            d.buttons = ["Use a different Sofa", "Sign out", "Cancel"]
            d.observeField("buttonSelected", "onMenu")
            m.top.dialog = d
            return true
        end if
    end if
    return false
end function

sub onMenu()
    d = m.top.dialog
    choice = d.buttonSelected
    d.close = true
    if m.view = "home" then m.rows.setFocus(true) else m.top.setFocus(true)
    if choice = 0 then
        m.token = ""
        m.reg.Delete("token")
        m.reg.Delete("server")
        m.reg.Flush()
        showFind("")
    else if choice = 1 then
        m.token = ""
        m.reg.Delete("token")
        m.reg.Flush()
        showPair()
    end if
end sub
