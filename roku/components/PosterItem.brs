sub init()
    m.poster = m.top.findNode("poster")
    m.label = m.top.findNode("label")
    m.bar = m.top.findNode("bar")
end sub

sub onContent()
    c = m.top.itemContent
    if c = invalid then return
    m.poster.uri = c.HDPosterUrl
    m.label.text = c.title
    if c.ShortDescriptionLine2 <> invalid and c.ShortDescriptionLine2 <> "" then
        m.bar.width = 240 * Val(c.ShortDescriptionLine2)
        m.bar.visible = true
    else
        m.bar.visible = false
    end if
end sub
