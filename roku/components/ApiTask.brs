sub init()
    m.top.functionName = "go"
end sub

sub go()
    req = m.top.request
    t = CreateObject("roUrlTransfer")
    t.SetUrl(req.url)
    t.EnableEncodings(true)
    t.AddHeader("X-Sofa", "1")
    if req.token <> invalid and req.token <> "" then t.AddHeader("Authorization", "Bearer " + req.token)
    port = CreateObject("roMessagePort")
    t.SetMessagePort(port)
    if req.method = "POST" then
        t.AddHeader("Content-Type", "application/json")
        body = "{}"
        if req.body <> invalid then body = FormatJson(req.body)
        t.AsyncPostFromString(body)
    else
        t.AsyncGetToString()
    end if
    msg = wait(30000, port)
    result = { code: 0, json: invalid, tag: req.tag }
    if type(msg) = "roUrlEvent" then
        result.code = msg.GetResponseCode()
        text = msg.GetString()
        if text <> invalid and text <> "" then result.json = ParseJson(text)
    else
        t.AsyncCancel()
    end if
    m.top.response = result
end sub
