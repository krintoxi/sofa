sub init()
    m.thumb = m.top.findNode("thumb")
    m.label = m.top.findNode("label")
    m.bar = m.top.findNode("bar")
    m.seen = m.top.findNode("seen")
end sub

sub onContent()
    c = m.top.itemContent
    if c = invalid then return
    m.thumb.uri = c.HDPosterUrl
    m.label.text = c.title
    part = 0
    if c.ShortDescriptionLine2 <> invalid and c.ShortDescriptionLine2 <> "" then part = Val(c.ShortDescriptionLine2)
    m.seen.visible = part >= 1
    m.bar.visible = part > 0 and part < 1
    m.bar.width = 400 * part
end sub
