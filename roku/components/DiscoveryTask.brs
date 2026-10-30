sub init()
    m.top.functionName = "go"
end sub

sub go()
    found = []
    seen = {}
    port = CreateObject("roMessagePort")
    sock = CreateObject("roDatagramSocket")
    sock.setMessagePort(port)
    group = CreateObject("roSocketAddress")
    group.setAddress("239.255.255.250:1900")
    sock.setSendToAddress(group)
    sock.notifyReadable(true)
    crlf = Chr(13) + Chr(10)
    search = "M-SEARCH * HTTP/1.1" + crlf + "HOST: 239.255.255.250:1900" + crlf + "MAN: " + Chr(34) + "ssdp:discover" + Chr(34) + crlf
    search = search + "MX: 2" + crlf + "ST: urn:sofa-media:device:Sofa:1" + crlf + crlf
    re = CreateObject("roRegex", "LOCATION:\s*(https?://[^/\s]+)", "i")
    for round = 1 to 2
        sock.sendStr(search)
        clock = CreateObject("roTimespan")
        while clock.TotalMilliseconds() < 2500
            ev = wait(300, port)
            if type(ev) = "roSocketEvent" and sock.isReadable() then
                text = sock.receiveStr(2048)
                hit = re.Match(text)
                if hit.Count() > 1 and not seen.DoesExist(hit[1]) then
                    seen[hit[1]] = true
                    info = sofaInfo(hit[1])
                    if info <> invalid then found.Push({ name: info.name, url: hit[1] })
                end if
            end if
        end while
    end for
    sock.close()
    m.top.servers = found
end sub

function sofaInfo(base as string) as object
    t = CreateObject("roUrlTransfer")
    t.SetUrl(base + "/api/info")
    text = t.GetToString()
    if text = "" then return invalid
    j = ParseJson(text)
    if j <> invalid and j.sofa = true then return j
    return invalid
end function
